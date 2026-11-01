"""Modellwahl, Websuche (Anbindung und Anzeige), Nutzungslimit-Hinweis und das Verhalten des Claude-Backends dabei."""
import asyncio
import json

import pytest

from app import backend as be
from app.backend import BackendError, ClaudeSdkBackend, SearchTrace, compose_system, map_error
from app.config import ConfigError, model_label, parse_settings
from app.db import Store
from app.ha_tools import HaToolbox, ToolError
from app.limits import LimitState, shared
from app.main import build_ingress_app
from conftest import ADM01, DORA, RAW
from test_background_run import asgi, jget, new_chat, sse
from test_ha_tools import Asker, FakeHa


def run(coro):
    return asyncio.run(coro)


# ----------------------------------------------------------------------- Konfiguration

def test_model_labels():
    assert model_label("claude-sonnet-5-5") == "Sonnet 5.5"
    assert model_label("claude-opus-4-1-20250805") == "Opus 4.1"
    assert model_label("claude-haiku-5") == "Haiku 5"
    assert model_label("sonnet") == "Sonnet"
    assert model_label("mein-modell-1") == "mein-modell-1"


def test_model_and_web_options():
    s = parse_settings(RAW, frozenset())
    assert s.models == ("claude-opus-5-5", "claude-haiku-5-5") and s.web_access_default == "on"  # leer: gängige Modelle zur Auswahl
    for off in ("none", "off", "AUS", "-"):
        s = parse_settings({**RAW, "models": off}, frozenset())
        assert s.models == () and s.model_choices() == []
    s = parse_settings({**RAW, "models": " claude-opus-5-5, claude-haiku-5-5  claude-sonnet-5-5 claude-opus-5-5"}, frozenset())
    assert s.models == ("claude-opus-5-5", "claude-haiku-5-5")  # Standard-Modell und Doppelte fallen weg
    assert [c["id"] for c in s.model_choices()] == ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"]
    assert parse_settings({**RAW, "models": ["claude-opus-5-5"]}, frozenset()).models == ("claude-opus-5-5",)
    for bad in ({"models": "a b/c"}, {"models": "--x"}, {"models": ",".join(f"claude-m-{i}" for i in range(13))}, {"web_access_default": "maybe"}):
        with pytest.raises(ConfigError):
            parse_settings({**RAW, **bad}, frozenset())
    profiles = [{**RAW["profiles"][0], "web_access": "off"}, RAW["profiles"][1]]
    s = parse_settings({**RAW, "profiles": profiles}, frozenset())
    assert s.web_level(s.profiles[0]) == "off" and s.web_level(s.profiles[1]) == "on"
    with pytest.raises(ConfigError):
        parse_settings({**RAW, "profiles": [{**RAW["profiles"][0], "web_access": "ja"}]}, frozenset())


# --------------------------------------------------------------------------- Limit-Stand

def test_limit_state_lifecycle_and_persistence(tmp_path):
    store = Store(tmp_path / "t.sqlite3")
    now = [1_000_000.0]
    state = LimitState(store, clock=lambda: now[0])
    assert state.current() == []
    state.update({"status": "allowed", "type": "five_hour", "resets_at": 1_005_000, "utilization": 0.2})
    assert state.current() == []
    state.update({"status": "allowed_warning", "type": "five_hour", "resets_at": 1_005_000, "utilization": 0.85})
    state.update({"status": "allowed_warning", "type": "seven_day", "resets_at": 1_500_000, "utilization": 0.9})
    state.update({"status": "bogus", "type": "x"})  # unbekannter Status wird ignoriert
    assert [i["type"] for i in state.current()] == ["seven_day", "five_hour"]  # höhere Auslastung zuerst
    state.update({"status": "rejected", "type": "five_hour", "resets_at": 1_005_000, "utilization": 1.0})
    assert [(i["type"], i["status"]) for i in state.current()] == [("five_hour", "rejected"), ("seven_day", "allowed_warning")]
    # übersteht einen Neustart
    again = LimitState(store, clock=lambda: now[0])
    assert [i["type"] for i in again.current()] == ["five_hour", "seven_day"]
    # nach der Rücksetzzeit verschwindet die Meldung von allein
    now[0] = 1_006_000
    assert [i["type"] for i in again.current()] == ["seven_day"]
    # ohne bekannte Rücksetzzeit gilt eine Warnung nur begrenzt
    again.update({"status": "allowed_warning", "type": "overage", "resets_at": None, "utilization": None})
    assert "overage" in [i["type"] for i in again.current()]
    now[0] += 7 * 3600
    assert "overage" not in [i["type"] for i in again.current()]
    # „allowed“ räumt auf
    again.update({"status": "allowed", "type": "seven_day", "resets_at": 1_500_000, "utilization": 0.1})
    assert again.current() == []
    assert shared(store) is shared(store)
    store.close()


def test_limit_state_survives_garbage(tmp_path):
    store = Store(tmp_path / "t.sqlite3")
    store.state_set("usage_limits", "{kaputt")
    assert LimitState(store).current() == []
    store.close()


# --------------------------------------------------------------- App: Modell, Web, Limit

def model_app(store, script=None, **options):
    settings = parse_settings({**RAW, "models": "claude-opus-5-5, claude-haiku-5-5", **options}, frozenset({"testclient"}))
    seen = {"calls": []}

    class Backend:
        async def stream(self, history, message, effort, attachments=None, instructions=None, tools=None, note="", **kw):
            seen["calls"].append({"model": kw.get("model"), "web": kw.get("web"), "tools": sorted(t.name for t in tools or []), "note": note, "kw": sorted(kw)})
            if script:
                await script(kw, {t.name: t.handler for t in tools or []})
            yield "Antwort"

    return build_ingress_app(settings, store, Backend()), seen


def test_me_lists_models_and_web(store):
    async def scenario():
        app, _ = model_app(store)
        me = jget(await asgi(app, "GET", "/api/me"))
        assert me["default_model"] == "claude-sonnet-5-5" and me["web"] is True and me["limits"] == []
        assert me["models"] == [{"id": "claude-sonnet-5-5", "label": "Sonnet 5.5"}, {"id": "claude-opus-5-5", "label": "Opus 5.5"}, {"id": "claude-haiku-5-5", "label": "Haiku 5.5"}]
        app, _ = model_app(store, models="none", web_access_default="off")
        me = jget(await asgi(app, "GET", "/api/me"))
        assert me["models"] == [] and me["web"] is False

    run(scenario())


def test_model_choice_is_validated_remembered_per_chat_and_default_clears(store):
    async def scenario():
        app, seen = model_app(store)
        chat = await new_chat(app)
        other = await new_chat(app)
        bad = await asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Hi", "model": "claude-gibtsnicht"})
        assert bad["status"] == 422 and jget(await asgi(app, "GET", f"/api/chats/{chat}/messages")) == []
        await asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Hi", "model": "claude-opus-5-5"})
        assert seen["calls"][-1]["model"] == "claude-opus-5-5"
        listed = {c["id"]: c for c in jget(await asgi(app, "GET", "/api/chats"))}
        assert listed[chat]["model"] == "claude-opus-5-5" and listed[other]["model"] == ""
        # ohne Angabe bleibt das gemerkte Modell dieses Chats
        await asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Nochmal"})
        assert seen["calls"][-1]["model"] == "claude-opus-5-5"
        await asgi(app, "POST", f"/api/chats/{other}/send", {"content": "Anderer Chat"})
        assert seen["calls"][-1]["model"] is None  # Standard-Modell: gar keine Angabe an das Backend
        # Standard ausdrücklich wählen löscht die Merkung
        await asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Zurück", "model": "claude-sonnet-5-5"})
        assert seen["calls"][-1]["model"] is None
        assert {c["id"]: c for c in jget(await asgi(app, "GET", "/api/chats"))}[chat]["model"] == ""
        # ein später aus der Liste entferntes Modell fällt auf den Standard zurück
        store.set_chat_model("adm01", chat, "claude-veraltet")
        await asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Und jetzt"})
        assert seen["calls"][-1]["model"] is None

    run(scenario())


def test_no_model_list_ignores_nothing_but_rejects_unknown(store):
    async def scenario():
        app, seen = model_app(store, models="none")
        chat = await new_chat(app)
        assert (await asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Hi", "model": "claude-opus-5-5"}))["status"] == 422
        await asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Hi"})
        assert seen["calls"][-1]["model"] is None

    run(scenario())


def test_web_search_switches(store):
    async def scenario():
        app, seen = model_app(store)
        chat = await new_chat(app)
        await asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Recherchiere"})
        call = seen["calls"][-1]
        assert call["web"] is True and "web_fetch" in call["tools"] and "Web: Du kannst im Web suchen" in call["note"]
        assert {"record", "next_id", "on_limit", "web"} <= set(call["kw"])
        await asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Ohne Web", "web": False})
        call = seen["calls"][-1]
        assert not call["web"] and "web_fetch" not in call["tools"] and "Web: Du kannst" not in call["note"]
        # per Konfiguration aus, aber für ein Profil an
        profiles = [{**RAW["profiles"][0], "web_access": "on"}, RAW["profiles"][1]]
        app, seen = model_app(store, web_access_default="off", profiles=profiles)
        a, d = await new_chat(app), jget(await asgi(app, "POST", "/api/chats", {}, user=DORA))["id"]
        await asgi(app, "POST", f"/api/chats/{a}/send", {"content": "Hi"})
        assert seen["calls"][-1]["web"] is True
        await asgi(app, "POST", f"/api/chats/{d}/send", {"content": "Hi"}, user=DORA)
        assert not seen["calls"][-1]["web"] and "web_fetch" not in seen["calls"][-1]["tools"]

    run(scenario())


def test_limit_events_reach_the_banner_and_errors_carry_reset_time(store):
    async def scenario():
        async def script(kw, tools):
            kw["on_limit"]({"status": "allowed_warning", "type": "five_hour", "resets_at": 4_102_444_800, "utilization": 0.83})

        app, seen = model_app(store, script)
        chat = await new_chat(app)
        await asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Hi"})
        limits = jget(await asgi(app, "GET", "/api/limits"))
        assert limits == [{"type": "five_hour", "status": "allowed_warning", "resets_at": 4_102_444_800, "utilization": 0.83}]
        assert jget(await asgi(app, "GET", "/api/me"))["limits"] == limits
        # fremde Profile sehen denselben Stand (das Limit gehört dem Abo)
        assert jget(await asgi(app, "GET", "/api/limits", user=DORA)) == limits

        async def failing(kw, tools):
            raise BackendError("Das Nutzungslimit deines Abos ist erreicht.", resets_at=4_102_444_800)

        app, _ = model_app(store, failing)
        chat = await new_chat(app)
        events = sse(await asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Hi"}))
        error = events[-1]
        assert error["type"] == "error" and error["resets_at"] == 4_102_444_800 and "erreicht" in error["message"]

    run(scenario())


def test_web_content_makes_later_actions_ask(store):
    async def scenario():
        ha = FakeHa()
        profiles = [{**RAW["profiles"][0], "ha_access": "execute"}, RAW["profiles"][1]]
        results = []

        async def script(kw, tools):
            await tools["ha_call_service"]({"domain": "light", "service": "turn_on", "entity_ids": ["light.kueche"]})
            results.append("ohne Web ausgeführt")
            kw["record"]({"type": "tool", "id": kw["next_id"](), "label": "Websuche: pellets", "status": "ok", "kind": "web", "note": ""})
            await tools["ha_call_service"]({"domain": "light", "service": "turn_off", "entity_ids": ["light.kueche"]})
            results.append("nach Web ausgeführt")

        settings = parse_settings({**RAW, "profiles": profiles}, frozenset({"testclient"}))

        class Backend:
            async def stream(self, history, message, effort, attachments=None, instructions=None, tools=None, note="", **kw):
                await script(kw, {t.name: t.handler for t in tools or []})
                yield "ok"

        app = build_ingress_app(settings, store, Backend(), ha=ha)
        chat = await new_chat(app)
        post = asyncio.create_task(asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Schalte"}))
        from test_background_run import until

        async def waiting():
            return next(c for c in jget(await asgi(app, "GET", "/api/chats")) if c["id"] == chat)["needs_approval"]

        await until(waiting)
        assert results == ["ohne Web ausgeführt"]  # das Ausschalten nach der Websuche wartet auf Zustimmung
        await asgi(app, "POST", f"/api/chats/{chat}/approve", {"id": 1, "decision": "deny"})
        events = sse(await post)
        approval = next(e for e in events if e["type"] == "approval")
        assert approval["topic"] == "ha" and approval["chat_ok"] is False

    run(scenario())


def test_ha_toolbox_force_confirm_accepts_a_callable():
    flag = {"on": False}
    asker = Asker("allow")
    events = []
    tb = HaToolbox(FakeHa(), "execute", limit_to_exposed=True, confirm_writes=True, force_confirm=lambda: flag["on"], ask=asker, record=events.append,
                   chat_allowed=lambda: False, allow_chat=lambda: None)
    call = next(s for s in tb.specs() if s.name == "ha_call_service").handler
    run(call({"domain": "light", "service": "turn_on", "entity_ids": ["light.kueche"]}))
    assert asker.asked == []
    flag["on"] = True
    run(call({"domain": "light", "service": "turn_off", "entity_ids": ["light.kueche"]}))
    assert len(asker.asked) == 1


# ---------------------------------------------------------------- Claude-Backend (SDK-Nachbau)

def sdk(monkeypatch, messages, record):
    """Ersetzt ``claude_agent_sdk.query`` durch einen Ablauf vorbereiteter Meldungen."""
    import claude_agent_sdk

    async def fake_query(prompt, options):
        record["options"] = options
        for m in messages():
            yield m

    monkeypatch.setattr(claude_agent_sdk, "query", fake_query)


def text_turn(text):
    from claude_agent_sdk import AssistantMessage, StreamEvent, TextBlock

    return [
        StreamEvent("u", "s", {"type": "message_start"}),
        StreamEvent("u", "s", {"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}}),
        AssistantMessage([TextBlock(text)], "m"),
    ]


def result(error=False, status=None):
    from claude_agent_sdk import ResultMessage

    return ResultMessage("success", 1, 1, error, 1, "s", api_error_status=status)


def collect(backend, **kw):
    async def go():
        out, err = [], None
        try:
            async for piece in backend.stream([], "Frage", "low", **kw):
                out.append(piece)
        except BackendError as exc:
            err = exc
        return "".join(out), err

    return run(go())


def test_options_for_plain_web_and_tool_requests(tmp_path):
    b = ClaudeSdkBackend("tok", "claude-sonnet-5-5", tmp_path)
    plain = b._options("low")
    assert plain.tools == [] and plain.disallowed_tools == ["*"] and plain.max_turns == 1 and plain.model == "claude-sonnet-5-5"
    web = b._options("low", web=True, model="claude-opus-5-5")
    assert web.tools == ["WebSearch"] and web.allowed_tools == ["WebSearch"] and not web.disallowed_tools and web.max_turns > 1 and web.model == "claude-opus-5-5"
    assert web.permission_mode == "dontAsk"
    from app.ha_tools import ToolSpec

    async def noop(args):
        return ""

    both = b._options("low", tools=[ToolSpec("x", "d", {"type": "object", "properties": {}}, noop)], web=True)
    assert both.allowed_tools == ["mcp__ki__x", "WebSearch"] and both.tools == ["WebSearch"] and "ki" in both.mcp_servers


def test_web_search_blocks_become_actions_and_limits_are_reported(monkeypatch, tmp_path):
    from claude_agent_sdk import AssistantMessage, RateLimitEvent, RateLimitInfo, ToolResultBlock, ToolUseBlock, UserMessage

    def messages():
        yield RateLimitEvent(RateLimitInfo("allowed_warning", 1_900_000_000, "five_hour", 0.81), "u", "s")
        yield AssistantMessage([ToolUseBlock("t1", "WebSearch", {"query": "Pelletpreis   Oktober\n2026"})], "m")
        yield UserMessage([ToolResultBlock("t1", "Treffer …")])
        yield AssistantMessage([ToolUseBlock("t2", "WebSearch", {"query": "zweite Suche"})], "m")
        yield UserMessage([ToolResultBlock("t2", "Fehler", is_error=True)])
        yield from text_turn("Antwort")
        yield result()

    seen: dict = {}
    sdk(monkeypatch, messages, seen)
    events, limits, counter = [], [], iter(range(1, 50))
    backend = ClaudeSdkBackend("tok", "claude-sonnet-5-5", tmp_path)
    text, err = collect(backend, web=True, record=events.append, next_id=lambda: next(counter), on_limit=limits.append, model="claude-opus-5-5")
    assert err is None and text == "Antwort"
    assert [(e["id"], e["label"], e["status"], e["kind"]) for e in events] == [
        (1, "Websuche: Pelletpreis Oktober 2026", "running", "web"), (1, "Websuche: Pelletpreis Oktober 2026", "ok", "web"),
        (2, "Websuche: zweite Suche", "running", "web"), (2, "Websuche: zweite Suche", "error", "web"),
    ]
    assert events[-1]["note"] == "Die Suche ist fehlgeschlagen."
    assert limits == [{"status": "allowed_warning", "type": "five_hour", "resets_at": 1_900_000_000, "utilization": 0.81}]
    assert seen["options"].model == "claude-opus-5-5" and seen["options"].tools == ["WebSearch"]


def test_server_side_search_blocks_are_tracked_too():
    from claude_agent_sdk import ServerToolResultBlock, ServerToolUseBlock

    events, counter = [], iter(range(1, 9))
    trace = SearchTrace(events.append, lambda: next(counter))
    trace.seen([ServerToolUseBlock("s1", "web_search", {"query": "x"})])
    trace.seen([ServerToolResultBlock("s1", {"type": "web_search_tool_result_error", "error_code": "unavailable"})])
    assert [e["status"] for e in events] == ["running", "error"]
    trace.seen([ServerToolUseBlock("s2", "web_fetch", {"url": "https://x"})])  # nur die Suche wird gemeldet
    assert len(events) == 2


def test_rate_limit_error_names_the_reset_time(monkeypatch, tmp_path):
    from claude_agent_sdk import RateLimitEvent, RateLimitInfo

    def messages():
        yield RateLimitEvent(RateLimitInfo("rejected", 1_900_000_000, "five_hour", 1.0), "u", "s")
        yield result(error=True, status=429)

    sdk(monkeypatch, messages, {})
    text, err = collect(ClaudeSdkBackend("tok", "claude-sonnet-5-5", tmp_path))
    assert text == "" and err.resets_at == 1_900_000_000 and err.user_message == "Das Nutzungslimit deines Abos ist erreicht."
    # ohne Rücksetzzeit bleibt es bei der allgemeinen Meldung
    sdk(monkeypatch, lambda: iter([result(error=True, status=429)]), {})
    _text, err = collect(ClaudeSdkBackend("tok", "claude-sonnet-5-5", tmp_path))
    assert err.resets_at is None and "später" in err.user_message


def test_unavailable_model_gets_a_hint(monkeypatch, tmp_path):
    from claude_agent_sdk import AssistantMessage

    def messages():
        yield AssistantMessage([], "m", error="invalid_request")
        yield result(error=True)

    sdk(monkeypatch, messages, {})
    _text, err = collect(ClaudeSdkBackend("tok", "claude-sonnet-5-5", tmp_path), model="claude-opus-5-5")
    assert "claude-opus-5-5" in err.user_message and "nicht verfügbar" in err.user_message
    assert map_error("invalid_request") == "Die Anfrage wurde von Claude abgelehnt."


def test_system_prompt_mentions_web_only_when_enabled():
    assert "WebSearch" in compose_system(None, "", tools=False, web=True)
    assert "keinen Zugriff auf Dateien, Geräte oder das Netzwerk; " in compose_system(None, "", tools=False, web=False)
    assert be.NO_TOOLS not in compose_system(None, "", tools=True, web=True)
