"""Deep Research: Planen, Recherche in Runden, Abgleich, Bericht mit geprüften Quellen, Grenzen und Rückfrage."""
import asyncio
import json

import pytest

from app import research as rs
from app.backend import BackendError
from app.config import parse_settings
from app.main import build_ingress_app
from conftest import ADM01, RAW
from test_background_run import asgi, jget, new_chat, sse, until

GOOD = "https://example.org/studie"
OTHER = "https://news.example.com/artikel#abschnitt"


# ------------------------------------------------------------------ reine Funktionen

def test_parse_questions_json_lines_dedupe_and_limit():
    assert rs.parse_questions('Hier: ["Wie teuer ist X heute?", "Wie teuer ist X heute?", "kurz", "Welche Alternativen gibt es zu X?"]') == [
        "Wie teuer ist X heute?", "Welche Alternativen gibt es zu X?"]
    assert rs.parse_questions("1. Erste ausreichend lange Frage\n2) Zweite ausreichend lange Frage\n- Dritte ausreichend lange Frage") == [
        "Erste ausreichend lange Frage", "Zweite ausreichend lange Frage", "Dritte ausreichend lange Frage"]
    assert len(rs.parse_questions(json.dumps([f"Teilfrage Nummer {i} zum Thema" for i in range(20)]), 6)) == 6
    assert rs.parse_questions("Das weiß ich nicht.") == []
    assert rs.parse_questions('["a", 5, null]') == []


def test_parse_check_text_and_followups():
    text, follow = rs.parse_check('Ergebnis: {"widersprueche": ["A sagt 5, B sagt 6"], "schwach": [], "luecken": ["Preis fehlt"], "nachfragen": ["Was kostet X 2026 genau?", "x", "Zweite Nachfrage zu Y?", "Dritte Nachfrage zu Z?"]}')
    assert "Widersprüche:\n- A sagt 5, B sagt 6" in text and "Lücken:\n- Preis fehlt" in text and "Schwach" not in text
    assert follow == ["Was kostet X 2026 genau?", "Zweite Nachfrage zu Y?"]
    assert rs.parse_check("kein JSON") == ("", [])
    assert rs.parse_check("[1,2]") == ("", [])


def test_enforce_sources_removes_unknown_addresses():
    known = rs.urls_in(f"- Fakt ({GOOD}).\n- Anderes ({OTHER})")
    report = (
        f"# Titel\n\nBelegt [Studie]({GOOD}) und [Artikel]({OTHER.split('#')[0]}/).\nErfunden [Blog](https://erfunden.example/x) und nackt https://auch-erfunden.example/y.\n\n"
        f"Quellen:\n- [Studie]({GOOD})\n- https://erfunden.example/z\n"
    )
    fixed, removed = rs.enforce_sources(report, known)
    assert removed == 3
    assert "erfunden.example" not in fixed and "auch-erfunden" not in fixed
    assert f"[Studie]({GOOD})" in fixed and "Erfunden Blog und nackt" in fixed
    assert not any(line.strip() in ("-", "*") for line in fixed.splitlines())  # kein leerer Listenpunkt bleibt
    assert "- [Studie]" in fixed and "https://erfunden.example/z" not in fixed
    assert rs.enforce_sources(f"[x]({GOOD})", known) == (f"[x]({GOOD})", 0)
    only, n = rs.enforce_sources("Quellen:\n- [Falsch](https://fake.example/a)\n- [Echt](" + GOOD + ")", known)
    assert n == 1 and "Falsch" not in only and "Echt" in only  # der ganze Listenpunkt fällt weg, kein Name ohne Beleg


def test_normalize_url_and_title():
    assert rs.normalize_url("HTTPS://Example.org/Studie/.") == "https://example.org/studie"
    assert rs.normalize_url("https://a.b/c#x") == "https://a.b/c"
    assert rs.title_of("Text\n# **Mein** Titel\nmehr", "F") == "Mein Titel" and rs.title_of("ohne", "Frage?") == "Frage?"


# ------------------------------------------------------------------ Ablauf mit simulierter KI

class Script:
    """Antwortet je Phase; merkt sich Reihenfolge und Aufträge."""

    def __init__(self, plan=None, check=None, report=None, steps=None, fail_step=None, fail_report=False):
        self.plan = plan if plan is not None else json.dumps(["Erste Teilfrage zum Thema?", "Zweite Teilfrage zum Thema?"])
        self.check = check if check is not None else json.dumps({"widersprueche": [], "schwach": [], "luecken": [], "nachfragen": []})
        self.report = report if report is not None else f"# Bericht\n\nKurzfassung [Studie]({GOOD}).\n\nQuellen:\n- [Studie]({GOOD})\n"
        self.steps = steps
        self.fail_step = fail_step
        self.fail_report = fail_report
        self.log: list[str] = []
        self.n = 0

    async def __call__(self, phase, prompt):
        self.log.append(phase)
        if phase == "plan":
            return self.plan
        if phase == "step":
            self.n += 1
            if self.fail_step == self.n:
                raise BackendError("Limit")
            if self.steps is not None:
                return self.steps[self.n - 1] if self.n <= len(self.steps) else ""
            return f"- Fakt {self.n} ({GOOD})"
        if phase == "check":
            return self.check
        if self.fail_report:
            raise BackendError("kaputt")
        return self.report


def go(script, **kw):
    seen: list[str] = []
    result = asyncio.run(rs.run("Wie ist der Stand bei X?", collect=script, status=seen.append, **kw))
    return result, seen


def test_run_phases_in_order_with_progress():
    script = Script()
    result, seen = go(script)
    assert script.log == ["plan", "step", "step", "check", "report"]
    assert [s for s in seen if s.startswith("Recherche")] == ["Recherche 1 von 2: Erste Teilfrage zum Thema?", "Recherche 2 von 2: Zweite Teilfrage zum Thema?"]
    assert seen[0].startswith("Plane") and seen[-1].startswith("Schreibe")
    assert result.title == "Bericht" and result.steps == 2 and result.removed == 0 and not result.stopped_early


def test_run_followups_after_check_are_limited():
    script = Script(check=json.dumps({"nachfragen": ["Erste Nachfrage dazu?", "Zweite Nachfrage dazu?", "Dritte Nachfrage dazu?"], "luecken": ["x"]}))
    result, seen = go(script)
    assert script.log.count("step") == 2 + rs.MAX_FOLLOWUPS and result.steps == 4
    assert any(s.startswith("Nachrecherche 2 von 2") for s in seen)


def test_run_caps_questions_and_falls_back_to_the_question():
    script = Script(plan=json.dumps([f"Teilfrage Nummer {i} zum Thema" for i in range(30)]))
    result, _ = go(script)
    assert script.log.count("step") == rs.MAX_QUESTIONS
    script = Script(plan="unbrauchbar")
    go(script)
    assert script.log.count("step") == 1


def test_run_removes_invented_sources_and_says_so():
    script = Script(report=f"# T\n\n[Echt]({GOOD}) und [Falsch](https://erfunden.example/q).\n\nQuellen:\n- https://erfunden.example/r\n")
    result, _ = go(script)
    assert result.removed == 2 and "erfunden.example" not in result.report and "2 Quellenangaben" in result.report


def test_run_survives_a_failed_step_but_not_without_any_notes():
    result, _ = go(Script(steps=["- Fakt (" + GOOD + ")", ""]))
    assert result.failed == 1 and len(result.notes) == 1
    with pytest.raises(rs.ResearchError):
        go(Script(steps=["", ""]))
    with pytest.raises(BackendError):  # Fehler der KI vor der ersten Notiz gehört der Person (z. B. Limit erreicht)
        go(Script(fail_step=1))
    result, _ = go(Script(fail_step=2))  # später: mit dem Vorhandenen weiterschreiben
    assert result.steps == 2 and len(result.notes) == 1


def test_run_delivers_notes_when_the_report_fails():
    result, _ = go(Script(fail_report=True))
    assert "nicht fertig geschrieben" in result.report and GOOD in result.report and result.report.startswith("# ")


def test_run_stops_at_the_time_limit_and_says_so():
    class Slow(Script):
        async def __call__(self, phase, prompt):
            if phase == "step":
                await asyncio.sleep(0.2)
            return await super().__call__(phase, prompt)

    script = Slow()
    result, _ = go(script, seconds=0.1)
    assert script.log.count("step") == 1 and result.stopped_early and "Zeitgrenze" in result.report
    with pytest.raises(rs.ResearchError):  # Zeit schon abgelaufen, bevor etwas erledigt war
        go(Script(), seconds=-1)


# ------------------------------------------------------------------ über die Schnittstelle

class ResearchBackend:
    """Echte Reihenfolge wie im Server: plan, step …, check, report. Erkennt die Phase am Auftrag."""

    def __init__(self, **kw):
        self.script = Script(**kw)
        self.calls: list[dict] = []

    async def stream(self, history, message, effort, tools=None, web=False, note="", instructions=None, personal_instructions=None, **_):
        phase = "plan" if message.startswith("Du bereitest") else "step" if message.startswith("Recherchiere") else "check" if message.startswith("Prüfe") else "report" if message.startswith("Schreibe jetzt") else "normal"
        self.calls.append({"phase": phase, "tools": [t.name for t in tools or []], "web": web, "history": len(history), "note": note, "effort": effort, "instructions": instructions, "personal": personal_instructions})
        if phase == "normal":
            yield "Normale Antwort"
            return
        yield await self.script(phase, message)


def make_app(store, backend=None, **options):
    raw = {**RAW, "research_enabled": True, "research_daily_limit": 2, **options}
    settings = parse_settings(raw, frozenset({"testclient"}))
    backend = backend or ResearchBackend()
    return build_ingress_app(settings, store, backend), backend


async def start(app, chat, text="Wie ist der Stand bei X?", **extra):
    return asyncio.create_task(asgi(app, "POST", f"/api/chats/{chat}/send", {"content": text, "research": True, **extra}))


async def approve(app, chat, decision="allow"):
    async def waiting():
        return next(c for c in jget(await asgi(app, "GET", "/api/chats")) if c["id"] == chat)["needs_approval"]
    await until(waiting)
    return await asgi(app, "POST", f"/api/chats/{chat}/approve", {"id": 1, "decision": decision})


def test_full_run_asks_first_then_answers_with_report_and_file(store):
    async def scenario():
        app, backend = make_app(store)
        chat = await new_chat(app)
        post = await start(app, chat)
        await approve(app, chat)
        events = sse(await post)
        approval = next(e for e in events if e["type"] == "approval")
        assert approval["topic"] == "research" and approval["chat_ok"] is False and "Heute noch 2 von 2" in approval["details"]
        status = [e["text"] for e in events if e["type"] == "status"]
        assert status[0].startswith("Plane") and any(s.startswith("Recherche 1 von 2") for s in status) and status[-1].startswith("Schreibe")
        answer = "".join(e["text"] for e in events if e["type"] == "delta")
        assert answer.startswith("# Bericht") and GOOD in answer
        files = [e["file"] for e in events if e["type"] == "tool" and e.get("file")]
        assert len(files) == 1 and files[0]["name"] == "Recherche Bericht.md"
        # gespeichert: Frage und Bericht als Chatverlauf
        msgs = jget(await asgi(app, "GET", f"/api/chats/{chat}/messages"))
        assert [m["role"] for m in msgs] == ["user", "assistant"] and msgs[1]["content"] == answer
        # nur die Rechercheschritte haben Werkzeuge: das Web, sonst nichts
        steps = [c for c in backend.calls if c["phase"] == "step"]
        assert len(steps) == 2 and all(c["web"] and c["tools"] == ["web_fetch"] for c in steps)
        assert all(not c["tools"] and not c["web"] for c in backend.calls if c["phase"] != "step")
        assert all(c["history"] == 0 for c in steps)
        assert [c["phase"] for c in backend.calls] == ["plan", "step", "step", "check", "report"]
        assert backend.calls[0]["effort"] == "low"

    asyncio.run(scenario())


def test_decline_runs_nothing_and_costs_nothing(store):
    async def scenario():
        app, backend = make_app(store)
        chat = await new_chat(app)
        post = await start(app, chat)
        await approve(app, chat, "deny")
        events = sse(await post)
        assert backend.calls == [] and any(e["type"] == "error" and "abgelehnt" in e["message"] for e in events)
        assert store.research_used("adm01", __import__("datetime").datetime.now().strftime("%Y-%m-%d")) == 0
        assert jget(await asgi(app, "GET", f"/api/chats/{chat}/messages")) == []  # die Frage wurde zurückgenommen

    asyncio.run(scenario())


def test_daily_limit_counts_runs_and_blocks_the_next(store):
    async def scenario():
        app, _ = make_app(store)
        for _i in range(2):
            chat = await new_chat(app)
            post = await start(app, chat)
            await approve(app, chat)
            await post
        info = jget(await asgi(app, "GET", "/api/research"))
        assert info["limit"] == 2 and info["left"] == 0 and info["questions"] == rs.MAX_QUESTIONS
        chat = await new_chat(app)
        blocked = await (await start(app, chat))
        assert blocked["status"] == 429 and "Tageslimit" in blocked["body"].decode()
        assert jget(await asgi(app, "GET", f"/api/chats/{chat}/messages")) == []

    asyncio.run(scenario())


def test_failure_before_any_search_gives_the_run_back(store):
    async def scenario():
        app, _ = make_app(store, ResearchBackend(fail_step=1))
        chat = await new_chat(app)
        post = await start(app, chat)
        await approve(app, chat)
        events = sse(await post)
        assert [e["message"] for e in events if e["type"] == "error"] == ["Limit"] and not any(e["type"] == "delta" for e in events)
        assert jget(await asgi(app, "GET", "/api/research"))["left"] == 2

    asyncio.run(scenario())


def test_not_allowed_in_the_wrong_situations(store):
    async def scenario():
        app, _ = make_app(store)
        chat = await new_chat(app)
        for extra, code in (({"web": False}, 422), ({"files": [{"name": "a.txt", "data": "aGFsbG8="}]}, 422), ({"voice": True}, 403)):
            r = await start(app, chat, **extra)
            assert (await r)["status"] == code, extra
        inc = jget(await asgi(app, "POST", "/api/chats", {"incognito": True}))
        assert (await (await start(app, inc["id"])))["status"] == 422
        off, _ = make_app(store, research_enabled=False)
        assert (await (await start(off, chat)))["status"] == 403
        assert (await asgi(off, "GET", "/api/research"))["status"] == 404
        assert jget(await asgi(off, "GET", "/api/me"))["research"] is None
        assert jget(await asgi(app, "GET", "/api/me"))["research"]["limit"] == 2

    asyncio.run(scenario())


def test_normal_messages_are_untouched(store):
    async def scenario():
        app, backend = make_app(store)
        chat = await new_chat(app)
        events = sse(await asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Hallo"}))
        assert "".join(e["text"] for e in events if e["type"] == "delta") == "Normale Antwort"
        assert [c["phase"] for c in backend.calls] == ["normal"] and store.research_used("adm01", __import__("datetime").datetime.now().strftime("%Y-%m-%d")) == 0

    asyncio.run(scenario())


def test_research_options_validated():
    parse_settings({**RAW, "research_daily_limit": 5}, frozenset({"testclient"}))
    for bad in (0, 21, "viele"):
        with pytest.raises(Exception):
            parse_settings({**RAW, "research_daily_limit": bad}, frozenset({"testclient"}))
    assert parse_settings(RAW, frozenset({"testclient"})).research_enabled is False


def test_store_reserve_is_atomic_and_releases(store):
    store.sync_profiles(["adm01"])
    assert [store.research_reserve("adm01", "2026-11-12", 2) for _ in range(3)] == [True, True, False]
    store.research_release("adm01", "2026-11-12")
    assert store.research_used("adm01", "2026-11-12") == 1
    store.research_release("adm01", "2026-11-13")  # nichts vorhanden: kein Fehler, nie negativ
    assert store.research_used("adm01", "2026-11-13") == 0
