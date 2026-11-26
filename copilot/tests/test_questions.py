"""Rückfragen der KI mit Auswahl (ask_user): Prüfung der Eingabe, Antwortweg, Verlauf, nicht per Sprache."""
import asyncio

import pytest

from app import questions as qs
from app.config import parse_settings
from app.ha_tools import ToolError
from app.main import build_ingress_app
from conftest import RAW
from test_background_run import asgi, jget, new_chat, sse, until

TWO = {"questions": [
    {"question": "Wo soll die Box erscheinen?", "header": "Position", "options": [
        {"label": "Über dem Eingabefeld (Empfohlen)", "description": "Wie bei Claude", "preview": "┌──┐\n│ok│\n└──┘"},
        {"label": "Inline im Verlauf"},
        "Als Dialog",
    ]},
    {"question": "Welche Antwortarten?", "header": "Antworttyp", "multi_select": True, "options": [
        {"label": "Einfachauswahl"}, {"label": "Mehrfachauswahl"}, {"label": "Freitext"},
    ]},
]}


# ------------------------------------------------------------------ Prüfung

def test_clean_keeps_form_and_limits_text():
    out = qs.clean_questions(TWO)
    assert [q["header"] for q in out] == ["Position", "Antworttyp"]
    assert out[0]["multi"] is False and out[1]["multi"] is True
    assert out[0]["options"][0] == {"label": "Über dem Eingabefeld (Empfohlen)", "description": "Wie bei Claude", "preview": "┌──┐\n│ok│\n└──┘"}
    assert out[0]["options"][2] == {"label": "Als Dialog"}  # einfache Texte sind erlaubt
    long = qs.clean_questions({"questions": [{"question": "x‮" + "y" * 900, "options": ["a" * 300, "b\n\nc"]}]})[0]
    assert len(long["question"]) <= qs.QUESTION_CHARS and "‮" not in long["question"]
    assert len(long["options"][0]["label"]) == qs.LABEL_CHARS and long["options"][1]["label"] == "b c"
    assert long["header"] == "Frage 1"


@pytest.mark.parametrize("bad", [
    {},
    {"questions": []},
    {"questions": [{"question": "Q?", "options": ["a"]}]},
    {"questions": [{"question": "Q?", "options": ["a", "b", "c", "d", "e"]}]},
    {"questions": [{"question": "", "options": ["a", "b"]}]},
    {"questions": [{"question": "Q?", "options": ["a", "A"]}]},
    {"questions": [{"question": "Q?", "options": ["a", "b"]}, {"question": "q?", "options": ["a", "b"]}]},
    {"questions": [{"question": f"Q{i}?", "options": ["a", "b"]} for i in range(5)]},
])
def test_clean_rejects_bad_input(bad):
    with pytest.raises(ToolError):
        qs.clean_questions(bad)


def test_result_text_for_all_ways_of_answering():
    q = qs.clean_questions(TWO)
    picked = qs.result_text(q, {"answers": [{"selected": [0]}, {"selected": [0, 2, 9], "other": "auch Datum"}]})
    assert "„Über dem Eingabefeld (Empfohlen)“" in picked and "„Einfachauswahl“, „Freitext“; eigene Antwort: „auch Datum“" in picked
    single = qs.result_text(q, {"answers": [{"selected": [1, 2]}, None]})
    assert "„Inline im Verlauf“" in single and "Als Dialog" not in single  # Einfachauswahl: nur die erste zählt
    assert "Welche Antwortarten? → übersprungen" in single
    assert "übersprungen" in qs.result_text(q, {"skipped": True, "answers": [{"selected": [0]}]})
    assert "direkt geantwortet" in qs.result_text(q, {"direct": "Mach es wie bei Claude"})
    assert "Keine Antwort" in qs.result_text(q, None)
    label, details = qs.summary(q, {"answers": [{"selected": [0]}, {"other": "frei"}]})
    assert label == "Rückfrage beantwortet" and details == [
        {"question": "Wo soll die Box erscheinen?", "answer": "Über dem Eingabefeld (Empfohlen)"}, {"question": "Welche Antwortarten?", "answer": "frei"}]
    assert qs.summary(q, {"answers": [{"selected": [1]}]})[1][1] == {"question": "Welche Antwortarten?", "answer": "Übersprungen", "skipped": True}
    label, details = qs.summary(q, {"skipped": True})
    assert label == "Rückfrage übersprungen" and all(d["skipped"] and d["answer"] == "Übersprungen" for d in details)


# ------------------------------------------------------------------ Ablauf im Chat

class AskingBackend:
    """Ruft das Werkzeug ask_user auf und schreibt das Ergebnis in die Antwort."""

    def __init__(self, args=TWO):
        self.args = args
        self.tools: list[str] = []
        self.notes: list[str] = []

    async def stream(self, history, message, effort, tools=None, note="", **_):
        self.tools = [t.name for t in tools or []]
        self.notes.append(note)
        spec = next((t for t in tools or [] if t.name == "ask_user"), None)
        if spec is None:
            yield "ohne Rückfrage"
            return
        yield "Kurz nachgefragt.\n"
        yield await spec.handler(self.args)


def make_app(store, backend):
    return build_ingress_app(parse_settings(RAW, frozenset({"testclient"})), store, backend)


async def waiting(app, chat):
    async def check():
        return next(c for c in jget(await asgi(app, "GET", "/api/chats")) if c["id"] == chat)["needs_approval"]
    await until(check)


def test_question_waits_for_answer_and_lands_in_history(store):
    async def scenario():
        backend = AskingBackend()
        app = make_app(store, backend)
        chat = await new_chat(app)
        post = asyncio.create_task(asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Bau mir eine Rückfrage-Box"}))
        await waiting(app, chat)
        # Eine Freigabe-Antwort passt nicht zu einer Auswahlfrage (und umgekehrt)
        assert (await asgi(app, "POST", f"/api/chats/{chat}/approve", {"id": 1, "decision": "allow"}))["status"] == 404
        assert (await asgi(app, "POST", f"/api/chats/{chat}/answer", {"id": 1, "answers": [{"selected": [11]}]}))["status"] == 422
        ok = await asgi(app, "POST", f"/api/chats/{chat}/answer", {"id": 1, "answers": [{"selected": [0]}, {"selected": [1, 2], "other": "Datum"}]})
        assert ok["status"] == 204
        events = sse(await post)
        shown = next(e for e in events if e["type"] == "question")
        assert shown["id"] == 1 and len(shown["questions"]) == 2 and shown["questions"][1]["multi"] is True
        assert any(e["type"] == "question_done" and e["id"] == 1 for e in events)
        answer = "".join(e["text"] for e in events if e["type"] == "delta")
        assert "„Mehrfachauswahl“, „Freitext“; eigene Antwort: „Datum“" in answer
        msgs = jget(await asgi(app, "GET", f"/api/chats/{chat}/messages"))
        logged = [t for t in msgs[-1]["tools"] if t["kind"] == "question"]
        assert logged and logged[0]["label"] == "Rückfrage beantwortet" and logged[0]["question"][0] == {"question": "Wo soll die Box erscheinen?", "answer": "Über dem Eingabefeld (Empfohlen)"}
        assert logged[0]["at"] == len("Kurz nachgefragt.\n")  # der Block steht dort im Text, wo die KI gefragt hat
        assert "ask_user" in backend.tools and "ask_user" in backend.notes[0]
        # nichts mehr offen
        assert (await asgi(app, "POST", f"/api/chats/{chat}/answer", {"id": 1, "skipped": True}))["status"] == 404

    asyncio.run(scenario())


def test_direct_answer_and_skip(store):
    async def scenario():
        app = make_app(store, AskingBackend())
        chat = await new_chat(app)
        post = asyncio.create_task(asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Hallo"}))
        await waiting(app, chat)
        await asgi(app, "POST", f"/api/chats/{chat}/answer", {"id": 1, "direct": "Mach es wie bei Claude"})
        answer = "".join(e["text"] for e in sse(await post) if e["type"] == "delta")
        assert "„Mach es wie bei Claude“" in answer

        post = asyncio.create_task(asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Nochmal"}))
        await waiting(app, chat)
        await asgi(app, "POST", f"/api/chats/{chat}/answer", {"id": 1, "skipped": True})
        events = sse(await post)
        assert "übersprungen" in "".join(e["text"] for e in events if e["type"] == "delta")
        assert next(e for e in events if e["type"] == "tool" and e["kind"] == "question")["label"] == "Rückfrage übersprungen"

    asyncio.run(scenario())


def test_bad_questions_go_back_to_the_ai_without_a_box(store):
    async def scenario():
        app = make_app(store, AskingBackend({"questions": [{"question": "Nur eine?", "options": ["a"]}]}))
        chat = await new_chat(app)
        events = sse(await asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Hallo"}))
        assert not any(e["type"] == "question" for e in events)

    asyncio.run(scenario())

