"""Lange Chats werden zusammengefasst statt still abgeschnitten."""
import json

import pytest
from fastapi.testclient import TestClient

from app import compact
from app.backend import build_prompt
from app.config import parse_settings
from app.main import build_ingress_app
from tests.conftest import DORA, RAW, FakeBackend, as_user

BIG = "x" * 9000


def msgs(n, size=100):
    return [{"id": i + 1, "role": "user" if i % 2 == 0 else "assistant", "content": "a" * size} for i in range(n)]


def test_split_keeps_recent_pairs_together():
    pending = msgs(30, 5000)
    older, recent = compact.split(pending)
    assert recent[0]["role"] == "user"
    assert older + recent == pending
    assert sum(len(m["content"]) for m in recent) >= compact.KEEP_RECENT_CHARS
    assert len(recent) >= compact.MIN_RECENT_MESSAGES


def test_split_without_enough_history_does_nothing():
    assert compact.split(msgs(3)) is None
    assert compact.split(msgs(4, 50)) is None  # alles passt in den „neueren“ Teil


def test_needs_compaction_counts_summary_and_new_text():
    assert not compact.needs_compaction(None, msgs(10, 1000), "hi")
    assert compact.needs_compaction("s" * 50_000, msgs(10, 3000), "hi")


def test_build_prompt_keeps_summary_when_history_is_cut():
    history = [{"role": "summary", "content": "WICHTIGE ZUSAMMENFASSUNG"}] + msgs(40, 5000)
    prompt = build_prompt(history, "neu")
    assert "WICHTIGE ZUSAMMENFASSUNG" in prompt and "gekürzt" in prompt and prompt.endswith("neu")
    assert "WICHTIGE ZUSAMMENFASSUNG" in build_prompt([{"role": "summary", "content": "WICHTIGE ZUSAMMENFASSUNG"}], "neu")


class Summarizer(FakeBackend):
    def __init__(self, result="Kurzfassung"):
        super().__init__()
        self.result = result
        self.summaries = []

    async def summarize(self, previous, messages):
        self.summaries.append({"previous": previous, "count": len(messages)})
        return self.result


def make(store, backend):
    settings = parse_settings(RAW, frozenset({"testclient"}))
    return TestClient(build_ingress_app(settings, store, backend))


def long_chat(store, exchanges=12):
    chat = store.create_chat("dora", "Lang")
    for i in range(exchanges):
        store.add_exchange("dora", chat["id"], f"Frage {i} {BIG}", f"Antwort {i} {BIG}")
    return chat["id"]


def send(client, chat_id, text="weiter"):
    r = client.post(f"/api/chats/{chat_id}/send", json={"content": text}, headers=as_user(DORA, True))
    assert r.status_code == 200
    return [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]


def test_long_chat_is_summarised_once(store):
    backend = Summarizer()
    client = make(store, backend)
    chat_id = long_chat(store)
    events = send(client, chat_id)
    types = [e["type"] for e in events]
    assert "status" in types and "compacted" in types and types[-1] == "done"

    sent = backend.calls[0]["history"]
    assert sent[0] == {"role": "summary", "content": "Kurzfassung"}
    assert sum(len(m["content"]) for m in sent[1:]) < compact.TRIGGER_CHARS
    assert backend.summaries[0]["previous"] is None

    stored = client.get(f"/api/chats/{chat_id}/messages", headers=as_user(DORA)).json()
    flags = [m["summarized"] for m in stored]
    assert flags[0] is True and flags[-1] is False
    assert flags == sorted(flags, reverse=True)  # erst zusammengefasste, dann wörtliche
    assert len(stored) == 12 * 2 + 2  # nichts wurde gelöscht

    # Zweite Nachricht: kurz genug, keine neue Zusammenfassung, Zusammenfassung bleibt vorn.
    again = [e["type"] for e in send(client, chat_id, "noch eine")]
    assert "status" not in again and len(backend.summaries) == 1
    assert backend.calls[1]["history"][0]["role"] == "summary"


def test_second_summary_builds_on_first(store):
    backend = Summarizer()
    client = make(store, backend)
    chat_id = long_chat(store)
    send(client, chat_id)
    for i in range(12):
        store.add_exchange("dora", chat_id, f"Mehr {i} {BIG}", f"Antwort {BIG}")
    send(client, chat_id, "und jetzt")
    assert len(backend.summaries) == 2 and backend.summaries[1]["previous"] == "Kurzfassung"


def test_failed_summary_falls_back_to_cutting(store):
    backend = Summarizer(result=None)
    client = make(store, backend)
    chat_id = long_chat(store)
    types = [e["type"] for e in send(client, chat_id)]
    assert "compacted" not in types and types[-1] == "done"
    assert store.get_summary("dora", chat_id) == (None, None)
    assert backend.calls[0]["history"][0]["role"] != "summary"  # voller Verlauf, build_prompt kürzt


def test_backend_without_summarize_is_unchanged(store, backend):
    client = make(store, backend)
    chat_id = long_chat(store)
    types = [e["type"] for e in send(client, chat_id)]
    assert types == ["delta", "done"]  # Stücke, die schon vorliegen, werden zusammengefasst


def test_short_chat_never_triggers(store):
    backend = Summarizer()
    client = make(store, backend)
    chat = store.create_chat("dora")
    store.add_exchange("dora", chat["id"], "kurz", "kurz")
    send(client, chat["id"])
    assert backend.summaries == []


def test_summary_is_profile_scoped(store):
    chat = store.create_chat("adm01")
    assert store.set_summary("dora", chat["id"], "fremd", 1) is False
    assert store.set_summary("adm01", chat["id"], "meins", 1) is True
    assert store.get_summary("dora", chat["id"]) == (None, None)
    assert store.get_summary("adm01", chat["id"]) == ("meins", 1)
