"""Zugriff der KI auf Home Assistant: Stufen, Freigabe-Filter, Sperrlisten, Rückfragen."""
import asyncio
import json

import pytest

from app.ha_client import HaApiError
from app.ha_tools import DATA_NOTE, HaToolbox, ToolError
from app.config import parse_settings
from app.main import build_ingress_app
from conftest import ADM01, DORA, RAW
from test_background_run import asgi, jget, new_chat, sse, until


class FakeHa:
    """Home Assistant im Speicher: Zustände, Registries, Dienstaufrufe und gespeicherte Konfigurationen."""

    enabled = True

    def __init__(self):
        self.states = [
            {"entity_id": "light.kueche", "state": "off", "attributes": {"friendly_name": "Küche"}},
            {"entity_id": "light.bad", "state": "on", "attributes": {"friendly_name": "Bad"}},
            {"entity_id": "lock.haustuer", "state": "locked", "attributes": {"friendly_name": "Haustür"}},
            {"entity_id": "cover.garage", "state": "closed", "attributes": {"friendly_name": "Garage", "device_class": "garage"}},
            {"entity_id": "cover.rollo", "state": "open", "attributes": {"friendly_name": "Rollo", "device_class": "shutter"}},
            {"entity_id": "sensor.geheim", "state": "42", "attributes": {"friendly_name": "Geheimer Sensor"}},
        ]
        self.exposed = {"light.kueche", "lock.haustuer", "cover.garage", "cover.rollo"}
        self.calls = []
        self.rest_calls = []
        self.configs = {("automation", "a1"): {"alias": "Alt", "trigger": []}}

    async def call(self, command):
        self.calls.append(command)
        kind = command["type"]
        if kind == "get_states":
            return self.states
        if kind == "homeassistant/expose_entity/list":
            return {"exposed_entities": {e: {"conversation": True} for e in self.exposed}}
        if kind == "config/area_registry/list":
            return [{"area_id": "kueche", "name": "Küche"}]
        if kind == "config/entity_registry/list":
            return [{"entity_id": "light.kueche", "area_id": "kueche", "name": "Deckenlampe"}]
        if kind == "config/device_registry/list":
            return []
        if kind == "get_config":
            return {"location_name": "Zuhause", "version": "2026.10", "time_zone": "Europe/Berlin", "unit_system": {}}
        if kind == "call_service":
            return {}
        if kind == "get_services":
            return {"light": {"turn_on": {"description": "an", "fields": {"brightness": {"description": "Helligkeit"}}}}}
        if kind == "lovelace/config":
            return {"views": [{"title": "Start"}]}
        if kind == "lovelace/config/save":
            return None
        if kind == "input_boolean/create":
            return {"id": "x"}
        raise HaApiError(f"{kind}: unknown_command")

    async def rest(self, method, path, body=None):
        self.rest_calls.append((method, path, body))
        parts = path.strip("/").split("/")
        if parts[0] == "config" and len(parts) == 4:
            key = (parts[1], parts[3])
            if method == "GET":
                if key not in self.configs:
                    raise HaApiError("HTTP 404")
                return self.configs[key]
            if method == "POST":
                self.configs[key] = body
                return {"result": "ok"}
            if method == "DELETE":
                self.configs.pop(key)
                return {"result": "ok"}
        raise HaApiError("HTTP 404")


class Asker:
    def __init__(self, answer="allow"):
        self.answer = answer
        self.asked = []

    async def __call__(self, label, details, offer_chat):
        self.asked.append((label, offer_chat))
        return self.answer


def box(ha, level, *, asker=None, exposed_only=True, confirm=True, force=False, chat=None, tmp=None):
    chat = chat if chat is not None else set()
    events = []
    toolbox = HaToolbox(
        ha, level, limit_to_exposed=exposed_only, confirm_writes=confirm, force_confirm=force,
        ask=asker or Asker(), record=events.append,
        chat_allowed=lambda: "k" in chat, allow_chat=lambda: chat.add("k"), backup_dir=tmp,
    )
    toolbox.events = events
    return toolbox


def tool(toolbox, name):
    return next(s for s in toolbox.specs() if s.name == name).handler


def names(toolbox):
    return {s.name for s in toolbox.specs()}


def run(coro):
    return asyncio.run(coro)


def test_tools_offered_depend_on_level():
    ha = FakeHa()
    read, execute, write = (names(box(ha, lvl)) for lvl in ("read", "execute", "write"))
    assert "ha_get_state" in read and "ha_call_service" not in read and "ha_save_config" not in read
    assert "ha_call_service" in execute and "ha_save_config" not in execute and "ha_ws" not in execute
    assert {"ha_save_config", "ha_delete_config", "ha_save_dashboard", "ha_ws", "ha_render_template"} <= write
    assert names(box(ha, "none")) == set()
    assert "ha_render_template" not in names(box(ha, "read"))  # Vorlagen sehen alles: nur ohne Filter
    assert "ha_render_template" in names(box(ha, "read", exposed_only=False))


def test_read_levels_only_see_exposed_entities():
    ha = FakeHa()
    tb = box(ha, "read")
    found = json.loads(run(tool(tb, "ha_search_entities")({})).removeprefix(DATA_NOTE))
    ids = {e["id"] for e in found["entitaeten"]}
    assert "sensor.geheim" not in ids and "light.bad" not in ids and "light.kueche" in ids
    with pytest.raises(ToolError, match="nicht für Assist freigegeben"):
        run(tool(tb, "ha_get_state")({"entity_ids": ["sensor.geheim"]}))
    with pytest.raises(ToolError):
        run(tool(tb, "ha_get_history")({"entity_id": "sensor.geheim"}))
    overview = json.loads(run(tool(tb, "ha_overview")({})).removeprefix(DATA_NOTE))
    assert overview["entitaeten_je_typ"].get("sensor") is None and overview["nur_freigegebene"] is True
    # Schreibstufe sieht alles
    all_ids = {e["id"] for e in json.loads(run(tool(box(ha, "write"), "ha_search_entities")({})).removeprefix(DATA_NOTE))["entitaeten"]}
    assert "sensor.geheim" in all_ids


def test_results_are_marked_as_data():
    ha = FakeHa()
    text = run(tool(box(ha, "read"), "ha_get_state")({"entity_ids": ["light.kueche"]}))
    assert text.startswith(DATA_NOTE)


def test_execute_runs_without_question_but_sensitive_ones_ask():
    ha = FakeHa()
    asker = Asker("allow")
    tb = box(ha, "execute", asker=asker)
    call = tool(tb, "ha_call_service")
    assert run(call({"domain": "light", "service": "turn_on", "entity_ids": ["light.kueche"]})) == "Ausgeführt."
    assert asker.asked == []
    run(call({"domain": "lock", "service": "unlock", "entity_ids": ["lock.haustuer"]}))
    run(call({"domain": "cover", "service": "open_cover", "entity_ids": ["cover.garage"]}))
    run(call({"domain": "cover", "service": "open_cover", "entity_ids": ["cover.rollo"]}))
    assert [a[0] for a in asker.asked] == ["lock.unlock auf lock.haustuer", "cover.open_cover auf cover.garage"]
    assert all(offer is False for _, offer in asker.asked)  # sensible Aktionen: nie „immer zulassen“


def test_denied_sensitive_action_is_not_executed():
    ha = FakeHa()
    tb = box(ha, "execute", asker=Asker("deny"))
    text = run(tool(tb, "ha_call_service")({"domain": "lock", "service": "unlock", "entity_ids": ["lock.haustuer"]}))
    assert "abgelehnt" in text and not [c for c in ha.calls if c["type"] == "call_service"]
    assert tb.events[-1]["status"] == "denied"


def test_execute_level_limits():
    ha = FakeHa()
    call = tool(box(ha, "execute"), "ha_call_service")
    with pytest.raises(ToolError, match="nicht ausführen"):
        run(call({"domain": "persistent_notification", "service": "create", "entity_ids": []}))
    with pytest.raises(ToolError, match="gesperrt"):
        run(call({"domain": "homeassistant", "service": "restart"}))
    with pytest.raises(ToolError, match="nicht ausführen"):
        run(call({"domain": "homeassistant", "service": "reload_core_config"}))
    with pytest.raises(ToolError, match="entity_ids"):
        run(call({"domain": "light", "service": "turn_off"}))  # ganze Bereiche/Alle nur mit konkreten Entitäten
    with pytest.raises(ToolError, match="konkrete entity_ids"):
        run(call({"domain": "light", "service": "turn_off", "data": {"area_id": "kueche"}}))
    with pytest.raises(ToolError, match="nicht für Assist freigegeben"):
        run(call({"domain": "light", "service": "turn_on", "entity_ids": ["light.bad"]}))
    with pytest.raises(ToolError, match="nicht für Assist freigegeben"):  # versteckt im Datenfeld
        run(call({"domain": "light", "service": "turn_on", "data": {"entity_id": "light.bad"}}))
    assert not [c for c in ha.calls if c["type"] == "call_service"]


def test_nobody_may_call_dangerous_services():
    ha = FakeHa()
    call = tool(box(ha, "write", exposed_only=False), "ha_call_service")
    for domain, service in (("homeassistant", "stop"), ("hassio", "addon_stop"), ("backup", "create"), ("recorder", "purge"), ("shell_command", "x")):
        with pytest.raises(ToolError):
            run(call({"domain": domain, "service": service}))
    assert not [c for c in ha.calls if c["type"] == "call_service"]


def test_read_level_cannot_execute_or_write():
    ha = FakeHa()
    tb = box(ha, "read")
    assert "ha_call_service" not in names(tb)
    with pytest.raises(ToolError, match="Berechtigung"):
        run(tb.call_service({"domain": "light", "service": "turn_on", "entity_ids": ["light.kueche"]}))  # auch direkt aufgerufen
    with pytest.raises(ToolError, match="Berechtigung"):
        run(tb.save_config({"kind": "automation", "id": "x", "config": {"alias": "x"}}))
    with pytest.raises(ToolError, match="Berechtigung"):
        run(box(ha, "execute").ws({"type": "input_boolean/create"}))


def test_write_asks_once_each_and_keeps_backup(tmp_path):
    ha = FakeHa()
    asker = Asker("deny")
    tb = box(ha, "write", asker=asker, tmp=tmp_path)
    save = tool(tb, "ha_save_config")
    text = run(save({"kind": "automation", "id": "a1", "config": {"alias": "Neu"}}))
    assert "abgelehnt" in text and ha.configs[("automation", "a1")]["alias"] == "Alt"
    asker.answer = "allow"
    out = run(save({"kind": "automation", "id": "a1", "config": {"alias": "Neu"}}))
    assert "Gespeichert" in out and ha.configs[("automation", "a1")]["alias"] == "Neu"
    saved = list(tmp_path.glob("*.json"))
    assert len(saved) == 1 and json.loads(saved[0].read_text())["alias"] == "Alt"  # alte Fassung gesichert
    assert [a[1] for a in asker.asked] == [True, True]  # „in diesem Chat immer“ wird angeboten
    run(save({"kind": "automation", "id": "a1", "config": {"alias": "Noch neuer"}}))
    assert len(asker.asked) == 3  # jede Änderung fragt erneut


def test_allow_in_this_chat_and_always_allow_setting():
    ha = FakeHa()
    chat = set()
    asker = Asker("allow_chat")
    tb = box(ha, "write", asker=asker, chat=chat)
    save = tool(tb, "ha_save_config")
    run(save({"kind": "script", "id": "s1", "config": {"alias": "S", "sequence": []}}))
    run(save({"kind": "script", "id": "s2", "config": {"alias": "S2", "sequence": []}}))
    assert len(asker.asked) == 1 and ("script", "s2") in ha.configs
    # Einstellung „Immer zulassen“: nie Rückfrage
    asker2 = Asker("deny")
    run(tool(box(ha, "write", asker=asker2, confirm=False), "ha_save_config")({"kind": "scene", "id": "c1", "config": {"name": "x"}}))
    assert asker2.asked == [] and ("scene", "c1") in ha.configs


def test_attachments_force_questions_even_with_always_allow():
    ha = FakeHa()
    asker = Asker("deny")
    tb = box(ha, "write", asker=asker, confirm=False, force=True)
    run(tool(tb, "ha_save_config")({"kind": "scene", "id": "c1", "config": {"name": "x"}}))
    run(tool(tb, "ha_call_service")({"domain": "light", "service": "turn_on", "entity_ids": ["light.kueche"]}))
    assert len(asker.asked) == 2 and ("scene", "c1") not in ha.configs
    assert all(offer is False for _, offer in asker.asked)  # nach Dateianhang kein „immer zulassen“
    assert not [c for c in ha.calls if c["type"] == "call_service"]


def test_delete_and_dashboard_and_ws_denylist(tmp_path):
    ha = FakeHa()
    tb = box(ha, "write", asker=Asker("allow"), tmp=tmp_path)
    assert "Gelöscht" in run(tool(tb, "ha_delete_config")({"kind": "automation", "id": "a1"}))
    assert ("automation", "a1") not in ha.configs
    with pytest.raises(ToolError, match="gibt es nicht"):
        run(tool(tb, "ha_delete_config")({"kind": "automation", "id": "a1"}))
    assert "gespeichert" in run(tool(tb, "ha_save_dashboard")({"url_path": "start", "config": {"views": []}}))
    for bad in ("auth/delete", "config/auth/create", "hassio/addon_stop", "supervisor/api", "backup/generate", "call_service", "render_template", "subscribe_events", "update/install"):
        with pytest.raises(ToolError, match="gesperrt"):
            run(tool(tb, "ha_ws")({"type": bad}))
    with pytest.raises(ToolError):
        run(tool(tb, "ha_ws")({"type": "input_boolean/create", "data": {"id": 5}}))  # id darf nicht überschrieben werden
    assert run(tool(tb, "ha_ws")({"type": "input_boolean/create", "data": {"name": "Gast"}}))


def test_invalid_input_is_reported_not_crashing():
    ha = FakeHa()
    tb = box(ha, "write")
    with pytest.raises(ToolError):
        run(tool(tb, "ha_get_state")({"entity_ids": ["../etc/passwd"]}))
    with pytest.raises(ToolError):
        run(tool(tb, "ha_get_config")({"kind": "automation", "id": "../x"}))
    with pytest.raises(ToolError):
        run(tool(tb, "ha_save_config")({"kind": "automation", "id": "ok", "config": "text"}))


# ------------------------------------------------------------------ Einbindung in die App

def ha_app(store, ha, **options):
    raw = {**RAW, **options}
    settings = parse_settings(raw, frozenset({"testclient"}))
    seen = {}

    class ToolBackend:
        """Spielt das Modell: ruft nach Anweisung Werkzeuge auf und antwortet danach."""

        script = []

        async def stream(self, history, message, effort, attachments=None, instructions=None, tools=None, note="", **_):
            seen["tools"] = sorted(t.name for t in tools or [])
            seen["note"] = note
            handlers = {t.name: t.handler for t in tools or []}
            for name, args in self.script:
                try:
                    result = await handlers[name](args)
                except ToolError as exc:
                    result = str(exc)
                seen.setdefault("results", []).append(result)
            yield "Erledigt."

    backend = ToolBackend()
    return build_ingress_app(settings, store, backend, ha=ha), backend, seen


def test_level_resolution_default_and_per_profile(store):
    async def scenario():
        profiles = [
            {"id": "adm01", "label": "Admin", "ha_user_id": ADM01, "entra_upn": "adm01@example.org", "ha_access": "write"},
            {"id": "dora", "label": "Dora", "ha_user_id": DORA, "entra_upn": "dora@example.org"},
        ]
        app, backend, seen = ha_app(store, FakeHa(), profiles=profiles)
        me = jget(await asgi(app, "GET", "/api/me", user=ADM01))
        assert me["ha_access"] == "write"
        assert jget(await asgi(app, "GET", "/api/me", user=DORA))["ha_access"] == "read"  # Standard: nur lesen
        chat = jget(await asgi(app, "POST", "/api/chats", {}, user=DORA))["id"]
        await asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Hi"}, user=DORA)
        assert "ha_call_service" not in seen["tools"] and "ha_get_state" in seen["tools"]
        assert "nur lesen" in seen["note"] and "Dora" in seen["note"]

    asyncio.run(scenario())


def test_level_none_and_missing_connection_offer_no_ha_tools(store):
    async def scenario():
        app, backend, seen = ha_app(store, FakeHa(), ha_access_default="none")
        chat = await new_chat(app)
        await asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Hi"})
        assert not [t for t in seen["tools"] if t.startswith("ha_")] and "Zugriff auf Home Assistant" not in seen["note"]
        offline = FakeHa()
        offline.enabled = False
        app, backend, seen = ha_app(store, offline)
        chat = await new_chat(app)
        await asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Hi"})
        assert not [t for t in seen["tools"] if t.startswith("ha_")]
        # ohne Home Assistant und ohne Gedächtnis bleiben nur Dateiwerkzeug und Web ...
        app, backend, seen = ha_app(store, offline, memory_enabled=False)
        chat = await new_chat(app)
        await asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Hi"})
        assert seen["tools"] == ["file_create", "web_fetch"]
        app, backend, seen = ha_app(store, offline, memory_enabled=False, web_access_default="off")
        chat = await new_chat(app)
        await asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Hi"})
        assert seen["tools"] == ["file_create"]
        # ... und ohne das gar keine Werkzeuge
        app, backend, seen = ha_app(store, offline, memory_enabled=False, files_enabled=False, web_access_default="off")
        chat = await new_chat(app)
        await asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Hi"})
        assert seen["tools"] == []

    asyncio.run(scenario())


def test_write_asks_in_chat_and_logs_actions(store):
    async def scenario():
        ha = FakeHa()
        profiles = [{"id": "adm01", "label": "Admin", "ha_user_id": ADM01, "entra_upn": "adm01@example.org", "ha_access": "write"},
                    {"id": "dora", "label": "Dora", "ha_user_id": DORA, "entra_upn": "dora@example.org"}]
        app, backend, seen = ha_app(store, ha, profiles=profiles)
        backend.script = [("ha_get_state", {"entity_ids": ["light.kueche"]}), ("ha_save_config", {"kind": "scene", "id": "n1", "config": {"name": "Abend"}})]
        chat = await new_chat(app)
        post = asyncio.create_task(asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Szene anlegen"}))

        async def waiting():
            info = next(c for c in jget(await asgi(app, "GET", "/api/chats")) if c["id"] == chat)
            return info["needs_approval"]

        await until(waiting)
        assert ("scene", "n1") not in ha.configs  # noch nichts passiert
        # fremde Person kann nicht zustimmen
        other = await asgi(app, "POST", f"/api/chats/{chat}/approve", {"id": 1, "decision": "allow"}, user=DORA)
        assert other["status"] == 404
        bad = await asgi(app, "POST", f"/api/chats/{chat}/approve", {"id": 1, "decision": "vielleicht"})
        assert bad["status"] == 422
        ok = await asgi(app, "POST", f"/api/chats/{chat}/approve", {"id": 1, "decision": "allow"})
        assert ok["status"] == 204
        out = await post
        events = sse(out)
        kinds = [e["type"] for e in events]
        assert "approval" in kinds and "approval_done" in kinds and kinds[-1] == "done"
        approval = next(e for e in events if e["type"] == "approval")
        assert approval["chat_ok"] is True and "Abend" in approval["label"]
        assert ("scene", "n1") in ha.configs
        history = jget(await asgi(app, "GET", f"/api/chats/{chat}/messages"))
        answer = history[-1]
        assert answer["content"] == "Erledigt." and [a["kind"] for a in answer["tools"]] == ["read", "write"]
        assert [a["status"] for a in answer["tools"]] == ["ok", "ok"]

    asyncio.run(scenario())


def test_denied_and_unanswered_requests_do_nothing(store):
    async def scenario():
        ha = FakeHa()
        profiles = [{"id": "adm01", "label": "Admin", "ha_user_id": ADM01, "entra_upn": "adm01@example.org", "ha_access": "write"}]
        app, backend, seen = ha_app(store, ha, profiles=profiles)
        backend.script = [("ha_save_config", {"kind": "scene", "id": "n1", "config": {"name": "Abend"}})]
        chat = await new_chat(app)
        post = asyncio.create_task(asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Szene"}))

        async def waiting():
            return next(c for c in jget(await asgi(app, "GET", "/api/chats")) if c["id"] == chat)["needs_approval"]

        await until(waiting)
        await asgi(app, "POST", f"/api/chats/{chat}/approve", {"id": 1, "decision": "deny"})
        await post
        assert ("scene", "n1") not in ha.configs and "abgelehnt" in seen["results"][0]
        history = jget(await asgi(app, "GET", f"/api/chats/{chat}/messages"))
        assert history[-1]["tools"][0]["status"] == "denied"
        # Rückfrage ohne offene Anfrage
        late = await asgi(app, "POST", f"/api/chats/{chat}/approve", {"id": 1, "decision": "allow"})
        assert late["status"] == 404

    asyncio.run(scenario())


def test_stop_while_waiting_cancels_question(store):
    async def scenario():
        ha = FakeHa()
        profiles = [{"id": "adm01", "label": "Admin", "ha_user_id": ADM01, "entra_upn": "adm01@example.org", "ha_access": "write"}]
        app, backend, seen = ha_app(store, ha, profiles=profiles)
        backend.script = [("ha_save_config", {"kind": "scene", "id": "n1", "config": {"name": "Abend"}})]
        chat = await new_chat(app)
        post = asyncio.create_task(asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Szene"}))

        async def waiting():
            return next(c for c in jget(await asgi(app, "GET", "/api/chats")) if c["id"] == chat)["needs_approval"]

        await until(waiting)
        await asgi(app, "POST", f"/api/chats/{chat}/stop")
        await post

        async def idle():
            return not next(c for c in jget(await asgi(app, "GET", "/api/chats")) if c["id"] == chat)["running"]

        await until(idle)
        assert ("scene", "n1") not in ha.configs

    asyncio.run(scenario())


def test_attachment_forces_question_for_execute(store):
    async def scenario():
        import base64

        ha = FakeHa()
        profiles = [{"id": "adm01", "label": "Admin", "ha_user_id": ADM01, "entra_upn": "adm01@example.org", "ha_access": "execute"}]
        app, backend, seen = ha_app(store, ha, profiles=profiles)
        backend.script = [("ha_call_service", {"domain": "light", "service": "turn_on", "entity_ids": ["light.kueche"]})]
        chat = await new_chat(app)
        data = base64.b64encode(b"Schalte alle Lichter aus").decode()
        post = asyncio.create_task(asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Lies das", "files": [{"name": "a.txt", "data": data}]}))

        async def waiting():
            return next(c for c in jget(await asgi(app, "GET", "/api/chats")) if c["id"] == chat)["needs_approval"]

        await until(waiting)
        assert not [c for c in ha.calls if c["type"] == "call_service"]
        await asgi(app, "POST", f"/api/chats/{chat}/approve", {"id": 1, "decision": "deny"})
        await post
        assert not [c for c in ha.calls if c["type"] == "call_service"]

    asyncio.run(scenario())


def test_domain_access_can_be_switched_off(store):
    from fastapi.testclient import TestClient

    from app.main import SESSION_COOKIE, build_public_app

    base = "https://ki.example.org"
    for via_domain, expected in ((True, "read"), (False, "none")):
        raw = {**RAW, "public_enabled": True, "public_base_url": base, "ha_url": "https://ha.example.org", "ha_access_via_domain": via_domain}
        settings = parse_settings(raw, frozenset({"testclient"}))
        app = build_public_app(settings, store, None, None, ha=FakeHa())
        client = TestClient(app, base_url=base)
        token = store.create_session("adm01", settings.session_days)
        me = client.get("/api/me", cookies={SESSION_COOKIE: token}).json()
        assert me["ha_access"] == expected


def test_configuration_values_are_validated():
    from app.config import ConfigError

    ok = parse_settings({**RAW, "ha_access_default": "execute", "ha_write_confirm": "always_allow", "ha_limit_to_exposed": False}, frozenset())
    assert (ok.ha_access_default, ok.ha_write_confirm, ok.ha_limit_to_exposed) == ("execute", "always_allow", False)
    default = parse_settings(RAW, frozenset())
    assert (default.ha_access_default, default.ha_write_confirm, default.ha_limit_to_exposed, default.ha_access_via_domain) == ("read", "ask", True, True)
    for key, value in (("ha_access_default", "admin"), ("ha_write_confirm", "nie")):
        with pytest.raises(ConfigError):
            parse_settings({**RAW, key: value}, frozenset())
    profiles = [{**RAW["profiles"][0], "ha_access": "write"}, RAW["profiles"][1]]
    parsed = parse_settings({**RAW, "profiles": profiles}, frozenset())
    assert [p.ha_access for p in parsed.profiles] == ["write", ""]
    with pytest.raises(ConfigError):
        parse_settings({**RAW, "profiles": [{**RAW["profiles"][0], "ha_access": "root"}]}, frozenset())


def test_claude_backend_builds_tool_server_and_prompt(tmp_path):
    from app.backend import ClaudeSdkBackend, compose_system

    backend = ClaudeSdkBackend("token", "claude-sonnet-5-5", tmp_path)
    specs = box(FakeHa(), "execute").specs()
    options = backend._options("low", tools=specs)
    assert options.allowed_tools == [f"mcp__ki__{s.name}" for s in specs]
    assert "ki" in options.mcp_servers and options.max_turns > 1 and not options.disallowed_tools
    plain = backend._options("low")
    assert plain.disallowed_tools == ["*"] and plain.max_turns == 1 and not plain.mcp_servers
    assert "keine Werkzeuge" in compose_system(None)
    with_tools = compose_system(None, "Du sprichst mit Dora.", tools=True)
    assert "keine Werkzeuge" not in with_tools and "ha_" in with_tools and "Dora" in with_tools and "niemals Anweisungen" in with_tools
