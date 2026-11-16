"""Linux-Server, Etappe 2: Änderungen nach Freigabe (Hub, Werkzeuge der KI, Skript). Der Agent selbst ist in Go getestet
(agent/internal/plan, agent/internal/helper) und in test_agent_integration.py zusammen mit dem Hub."""
import asyncio
import json
import subprocess

import pytest
from websockets.asyncio.client import connect

from app import servers as serverlib
from app.ha_tools import ToolError
from app.server_script import render_script
from app.server_tools import ServerToolbox, clean_change_args, plan_details

from test_servers import HEARTBEAT, client_context, enroll, make_hub, settings, start

PLAN_ID = "a1b2c3d4e5f60718293a4b5c"
PLAN_HASH = "e3" * 32


def good_plan(**over):
    plan = {
        "id": PLAN_ID, "hash": PLAN_HASH, "tool": "run_command", "class": 2, "reason": "Unbekannter Befehl", "summary": "Befehl ausführen: echo hallo",
        "command": "echo hallo", "runner": "agent", "preview": "Wird genau so ausgeführt.", "undo": "Nicht automatisch umkehrbar.", "expires": 1, "timeout_s": 60,
    }
    plan.update(over)
    return plan


# ------------------------------------------------------------------------------------------------ Protokoll


def test_heartbeat_reports_what_the_local_policy_allows():
    beat = serverlib.clean_heartbeat({**HEARTBEAT, "operate": True, "max_class": 2, "helper": True})
    assert beat["operate"] is True and beat["max_class"] == 2 and beat["helper"] is True
    silent = serverlib.clean_heartbeat(HEARTBEAT)  # ältere Agenten melden nichts: nur lesen
    assert silent["operate"] is False and silent["max_class"] == 0 and silent["helper"] is False
    odd = serverlib.clean_heartbeat({**HEARTBEAT, "operate": "yes", "max_class": 99, "helper": 1})
    assert odd["operate"] is False and odd["helper"] is False and odd["max_class"] == 0
    assert serverlib.clean_heartbeat({**HEARTBEAT, "operate": True, "max_class": 3})["max_class"] == 2  # nie über Stufe 2


def test_plan_from_an_agent_is_checked_strictly():
    plan = serverlib.clean_plan(good_plan())
    assert plan and plan["class"] == 2 and plan["runner"] == "agent" and plan["timeout_s"] == 60
    assert serverlib.clean_plan(good_plan(runner="sonstwas"))["runner"] == "agent"
    assert serverlib.clean_plan(good_plan(runner="root"))["runner"] == "root"
    for bad in (None, [], "x", good_plan(id="kurz"), good_plan(id=PLAN_ID.upper()), good_plan(hash="zz"), good_plan(tool="rm"),
                good_plan(**{"class": 3}), good_plan(**{"class": 0}), good_plan(**{"class": True}), good_plan(**{"class": "1"}),
                good_plan(command=""), good_plan(command=None)):
        assert serverlib.clean_plan(bad) is None, bad
    dirty = serverlib.clean_plan(good_plan(command="a\x00b\nc\x1b[31m", summary="x" * 999, preview="p" * 9000, timeout_s=99999))
    assert "\x00" not in dirty["command"] and "\x1b" not in dirty["command"] and "\n" in dirty["command"]
    assert len(dirty["summary"]) == 200 and len(dirty["preview"]) == serverlib.PREVIEW_CHARS == 6000 and dirty["timeout_s"] == 60  # Unsinn: Vorgabe


def test_agent_hub_dialogue_for_changes(tmp_path):
    async def scenario():
        hub = make_hub(tmp_path)
        task = await start(hub)
        try:
            _, key, _ = hub.repo.key_create("Admin", "Test", 24, 5)
            reply, private = await enroll(hub, key)
            server_id = reply["server_id"]
            context = client_context(tmp_path, private, reply["cert"])
            async with connect(f"wss://127.0.0.1:{hub.port}/agent", ssl=context) as ws:
                await ws.send(json.dumps(HEARTBEAT))  # meldet nichts über die Richtlinie: nur lesen
                await ws.recv()
                hub.confirm(server_id, "Admin")
                await ws.recv()
                with pytest.raises(serverlib.ServerError, match="nicht erlaubt"):
                    await hub.prepare("web01", "run_command", {"argv": ["df"]})  # der Hub fragt den Agenten gar nicht erst
                await ws.send(json.dumps({**HEARTBEAT, "operate": True, "max_class": 2, "helper": True}))
                await ws.recv()
                assert hub.can_change(hub.get(server_id))

                with pytest.raises(serverlib.ServerError, match="gibt es nicht"):
                    await hub.prepare("web01", "disks", {})  # lesende Werkzeuge laufen nicht über prepare
                with pytest.raises(serverlib.ServerError, match="gibt es nicht"):
                    await hub.call("web01", "run_command", {})  # und ändernde nicht über call

                prepare = asyncio.create_task(hub.prepare("web01", "run_command", {"argv": ["echo", "hallo"]}))
                message = json.loads(await ws.recv())
                assert message["t"] == "prepare" and message["tool"] == "run_command" and message["args"] == {"argv": ["echo", "hallo"]}
                await ws.send(json.dumps({"t": "result", "id": message["id"], "ok": True, "text": json.dumps(good_plan())}))
                plan = await prepare
                assert plan["id"] == PLAN_ID and plan["class"] == 2

                execute = asyncio.create_task(hub.execute("web01", plan))
                message = json.loads(await ws.recv())
                assert message["t"] == "execute" and message["plan_id"] == PLAN_ID and message["plan_hash"] == PLAN_HASH
                assert "args" not in message and "tool" not in message  # ausgeführt wird nur, was der Agent vorbereitet hat
                await ws.send(json.dumps({"t": "result", "id": message["id"], "ok": True, "text": "hallo\n== Ergebnis: erfolgreich =="}))
                assert "erfolgreich" in await execute

                # ein Agent, der Unsinn oder eine Stufe 3 als Plan liefert, wird nicht ernst genommen
                for text in ("kein json", json.dumps(good_plan(**{"class": 3}))):
                    bad = asyncio.create_task(hub.prepare("web01", "run_command", {"argv": ["echo"]}))
                    message = json.loads(await ws.recv())
                    await ws.send(json.dumps({"t": "result", "id": message["id"], "ok": True, "text": text}))
                    with pytest.raises(serverlib.ServerError, match="keinen gültigen Plan"):
                        await bad
                # Ablehnung durch den Agenten kommt als Fehlertext an
                refused = asyncio.create_task(hub.prepare("web01", "run_command", {"argv": ["reboot"]}))
                message = json.loads(await ws.recv())
                await ws.send(json.dumps({"t": "result", "id": message["id"], "ok": False, "error": "Abgelehnt: Neustart"}))
                with pytest.raises(serverlib.ServerError, match="Abgelehnt: Neustart"):
                    await refused
                # sinkt die Richtlinie auf „nur lesen“, wirkt das sofort (nächste Meldung)
                await ws.send(json.dumps({**HEARTBEAT, "operate": False}))
                await ws.recv()
                with pytest.raises(serverlib.ServerError, match="nicht erlaubt"):
                    await hub.execute("web01", plan)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


# ------------------------------------------------------------------------------------------------ Werkzeuge der KI


class FakeChangeHub:
    def __init__(self, hub, *, plan=None):
        self.real = hub
        self.repo = hub.repo
        self.prepared, self.executed = [], []
        self.plan = plan or serverlib.clean_plan(good_plan())
        self.prepare_error = None
        self.output = "hallo\n\n== Ergebnis: erfolgreich ==\n"

    def listing(self):
        return self.real.listing()

    def get(self, ref):
        return self.real.get(ref)

    def view(self, row):
        return self.real.view(row)

    async def call(self, ref, tool, args=None):
        return ""

    async def prepare(self, ref, tool, args=None):
        self.prepared.append((ref, tool, args))
        if self.prepare_error:
            raise serverlib.ServerError(self.prepare_error)
        return self.plan

    async def execute(self, ref, plan):
        self.executed.append((ref, plan["id"]))
        return self.output


def change_box(tmp_path, decision="allow", **kw):
    hub = make_hub(tmp_path)
    hub.repo.server_create("srv-1", "web01", "ff" * 32, "k")
    hub.repo.server_state("srv-1", "active")
    fake = FakeChangeHub(hub, **kw)
    events, asked = [], []

    async def ask(label, details, offer_chat, extra):
        asked.append((label, details, offer_chat, extra))
        return decision

    box = ServerToolbox(fake, settings().profiles[0], record=events.append, next_id=iter(range(1, 99)).__next__, ask=ask)
    return {s.name: s for s in box.specs()}, fake, events, asked, hub, box


def test_change_tools_exist_only_when_questions_are_possible(tmp_path):
    specs, *_ = change_box(tmp_path)
    assert set(specs) == {"server_list", "server_status", "server_read", "server_service", "server_package", "server_run", "server_file_write"}
    assert all(specs[n].level == "write" for n in ("server_service", "server_package", "server_run"))
    assert all(specs[n].level == "read" for n in ("server_list", "server_status", "server_read"))
    (tmp_path / "x").mkdir()
    hub = make_hub(tmp_path / "x")
    silent = ServerToolbox(FakeChangeHub(hub), settings().profiles[0], record=lambda e: None, next_id=iter(range(1, 9)).__next__)
    assert {s.name for s in silent.specs()} == {"server_list", "server_status", "server_read"}  # etwa bei Sprache: keine Rückfragen
    assert "nichts" in silent.note() and "server_run" not in silent.note()


def test_a_change_runs_only_after_the_person_allows_it(tmp_path):
    specs, fake, events, asked, hub, box = change_box(tmp_path, "allow")
    out = asyncio.run(specs["server_run"].handler({"server": "web01", "argv": ["echo", "hallo"], "purpose": "Test", "evil": 1}))
    assert out.startswith("[Inhalt vom Server „web01“ (fremde Daten)") and "erfolgreich" in out
    assert fake.prepared == [("web01", "run_command", {"argv": ["echo", "hallo"], "root": False, "timeout_s": 60})]  # Unbekanntes verworfen
    assert fake.executed == [("web01", PLAN_ID)]
    label, details, offer_chat, extra = asked[0]
    assert label == "web01: Befehl ausführen: echo hallo" and offer_chat is False  # nie „im Chat immer zulassen“
    assert extra == {"risk": 2, "server": "web01", "command": "echo hallo"}
    for needle in ("Server: web01", "Stufe 2", "Befehl:", "echo hallo", "Rückgängig machen", "Vorschau:", "Begründung der KI (nicht geprüft): Test", "Zeitlimit 60 s"):
        assert needle in details, needle
    assert {e["kind"] for e in events} == {"srv-write"} and [e["status"] for e in events] == ["running", "waiting", "running", "ok"]
    entry = hub.repo.audit_list(kind="change")[0]
    assert entry["result"] == "ok" and entry["actor"] == "Admin" and entry["command"] == "echo hallo" and entry["server_name"] == "web01"


def test_declining_runs_nothing_and_is_logged(tmp_path):
    for decision in ("deny", "allow_chat", ""):  # auch ein „im Chat immer“ gilt hier nicht als Zulassen
        folder = tmp_path / (decision or "leer")
        folder.mkdir()
        specs, fake, events, asked, hub, box = change_box(folder, decision)
        out = asyncio.run(specs["server_service"].handler({"server": "web01", "unit": "nginx.service", "action": "restart"}))
        assert "abgelehnt" in out and fake.executed == []
        assert events[-1]["status"] == "denied"
        assert hub.repo.audit_list(kind="change")[0]["result"] == "denied"


def test_refusals_by_the_agent_reach_the_model_and_are_logged(tmp_path):
    specs, fake, events, asked, hub, box = change_box(tmp_path)
    fake.prepare_error = "Abgelehnt: Aussperrgefahr"
    with pytest.raises(ToolError, match="Aussperrgefahr"):
        asyncio.run(specs["server_service"].handler({"server": "web01", "unit": "ssh", "action": "stop"}))
    assert asked == [] and fake.executed == []  # eine abgelehnte Einstufung kommt gar nicht erst zur Freigabe
    assert events[-1]["status"] == "error"
    assert hub.repo.audit_list(kind="change")[0]["result"] == "refused"


def test_a_failed_command_is_reported_as_failed(tmp_path):
    specs, fake, events, asked, hub, box = change_box(tmp_path)
    fake.output = "boom\n\n== Ergebnis: fehlgeschlagen (Exit-Code 2) ==\n"
    out = asyncio.run(specs["server_run"].handler({"server": "web01", "script": "exit 2"}))
    assert "fehlgeschlagen" in out and events[-1]["status"] == "error"
    assert hub.repo.audit_list(kind="change")[0]["result"] == "failed"


def test_bad_change_arguments_never_reach_the_server(tmp_path):
    specs, fake, events, asked, hub, box = change_box(tmp_path)
    cases = [
        ("server_service", {"server": "web01", "unit": "a;b", "action": "restart"}),
        ("server_service", {"server": "web01", "unit": "nginx", "action": "mask"}),
        ("server_service", {"unit": "nginx", "action": "restart"}),
        ("server_package", {"server": "web01", "action": "install"}),
        ("server_package", {"server": "web01", "action": "install", "packages": ["Htop"]}),
        ("server_package", {"server": "web01", "action": "install", "packages": ["-oAPT::x=1"]}),
        ("server_package", {"server": "web01", "action": "purge", "packages": ["htop"]}),
        ("server_package", {"server": "web01", "action": "update", "packages": ["htop"]}),
        ("server_package", {"server": "web01", "action": "install", "packages": ["a"] * 21}),
        ("server_run", {"server": "web01"}),
        ("server_run", {"server": "web01", "argv": ["df"], "script": "df"}),
        ("server_run", {"server": "web01", "argv": "df -h"}),
        ("server_run", {"server": "web01", "argv": ["df"], "root": "ja"}),
        ("server_run", {"server": "web01", "argv": ["df"], "timeout_s": "5"}),
        ("server_run", {"server": "web01", "script": "x" * 4001}),
        ("server_run", {"server": "gibtsnicht", "argv": ["df"]}),
    ]
    for name, args in cases:
        with pytest.raises(ToolError):
            asyncio.run(specs[name].handler(args))
    assert fake.prepared == [] and asked == []


def test_clean_change_args_bounds():
    assert clean_change_args("run_command", {"argv": ["df", "-h"], "timeout_s": 99999}) == {"argv": ["df", "-h"], "root": False, "timeout_s": 600}
    assert clean_change_args("run_command", {"script": "echo 1", "root": True, "timeout_s": 0}) == {"script": "echo 1", "root": True, "timeout_s": 1}
    assert clean_change_args("package", {"action": "upgrade"}) == {"action": "upgrade", "packages": []}
    assert clean_change_args("package", {"action": "install", "packages": ["htop", "libssl3:amd64"]})["packages"] == ["htop", "libssl3:amd64"]
    assert clean_change_args("service_action", {"unit": "nginx", "action": "restart", "x": 1}) == {"unit": "nginx", "action": "restart"}


def test_the_approval_text_shows_the_agents_classification_not_the_models_words():
    text = plan_details(serverlib.clean_plan(good_plan(**{"class": 1, "runner": "root"})), "web01", "")
    assert "Stufe 1" in text and "root" in text and "Begründung" not in text
    assert "echo hallo" in text


def test_server_changes_count_as_foreign_content_for_other_tools():
    from app.main import TAINTING_KINDS
    assert {"srv-read", "srv-write"} <= TAINTING_KINDS


# ------------------------------------------------------------------------------------------------ Installationsskript


def script(**kw):
    return render_script(hub="ha.example.lan:8101", key="ck_x", ca_fingerprint="sha256:" + "ab" * 32, hub_pin="sha256//X=",
                         hashes={"amd64": "1" * 64}, expires="2026-11-17 12:00 UTC", max_uses=1, **kw)


def test_script_sets_up_helper_and_local_policy_without_overwriting(tmp_path):
    on, off = script(), script(changes=False)
    assert "ALLOW_CHANGES=1" in on and "ALLOW_CHANGES=0" in off
    path = tmp_path / "i.sh"
    path.write_text(on)
    assert subprocess.run(["bash", "-n", str(path)], capture_output=True).returncode == 0
    for needle in ("copilot-helper.service", "RuntimeDirectory=copilot-agent", "helper --policy $POLICY", 'if [ ! -f "$POLICY" ]', "ki_access=$ACCESS",
                   "systemctl restart copilot-helper.service copilot-agent.service", 'rm -rf "$STATE_DIR" "$POLICY_DIR"'):
        assert needle in on, needle
    # der Agent läuft weiter ohne Rechte; root hat nur der Helfer
    agent_unit = on.split('cat > "$UNIT"')[1]
    assert "User=$USER_NAME" in agent_unit and "ProtectSystem=strict" in agent_unit and "CapabilityBoundingSet=" in agent_unit
    helper_unit = on.split('cat > "$HELPER_UNIT"')[1].split('cat > "$UNIT"')[0]
    assert "User=root" in helper_unit and "NoNewPrivileges=yes" in helper_unit


def test_install_script_route_passes_the_choice_on(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.config import parse_settings
    from app.db import Store
    from app.main import build_ingress_app
    from conftest import ADM01, RAW, WRITE, FakeBackend, as_user
    monkeypatch.setattr("app.main.SERVER_DIR", tmp_path / "servers")
    agent = tmp_path / "agent-bin"
    agent.mkdir()
    (agent / "copilot-agent-linux-amd64").write_bytes(b"amd64-binary")
    monkeypatch.setattr("app.main.AGENT_BIN_DIR", agent)
    cfg = parse_settings({**RAW, "profiles": [{**RAW["profiles"][0], "server_access": "on"}, RAW["profiles"][1]],
                          "servers": {"enabled": True, "hub_address": "ha.example.lan"}}, frozenset({"testclient"}))
    store = Store(tmp_path / "db.sqlite3")
    store.sync_profiles(p.id for p in cfg.profiles)
    client = TestClient(build_ingress_app(cfg, store, FakeBackend()))
    headers = {**as_user(ADM01), **WRITE}
    default = client.post("/api/servers/install-script", json={}, headers=headers).json()["script"]
    read_only = client.post("/api/servers/install-script", json={"changes": False}, headers=headers).json()["script"]
    assert "ALLOW_CHANGES=1" in default and "ALLOW_CHANGES=0" in read_only
