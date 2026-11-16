"""Der echte Go-Agent gegen den echten Hub: Anmeldung, Bestätigung, Meldungen und Aufrufe (wird übersprungen, wenn Go fehlt)."""
import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app import servers as serverlib
from app.db import Store

from test_servers import make_hub

AGENT_SRC = Path(__file__).resolve().parent.parent / "agent"

pytestmark = pytest.mark.skipif(shutil.which("go") is None, reason="Go ist nicht installiert")


@pytest.fixture(scope="module")
def agent_binary(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("agent-bin") / "copilot-agent"
    env = {**os.environ, "GOFLAGS": "-mod=vendor", "CGO_ENABLED": "0"}
    build = subprocess.run(
        ["go", "build", "-trimpath", "-ldflags", "-X main.version=9.9.9", "-o", str(out), "./cmd/copilot-agent"],
        cwd=AGENT_SRC, env=env, capture_output=True, text=True, timeout=240,
    )
    assert build.returncode == 0, build.stderr
    return out


async def sh(*argv: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return await asyncio.to_thread(
        subprocess.run, list(argv), capture_output=True, text=True, timeout=60, env={**os.environ, **(env or {})})


async def started(hub) -> asyncio.Task:
    task = asyncio.create_task(hub.serve(port=0, host="127.0.0.1"))
    for _ in range(100):
        if hub.port:
            return task
        await asyncio.sleep(0.02)
    raise AssertionError("Hub startet nicht")


async def wait_for(check, seconds=15):
    for _ in range(int(seconds / 0.1)):
        value = check()
        if value:
            return value
        await asyncio.sleep(0.1)
    raise AssertionError("Zeit abgelaufen")


def test_agent_enrolls_reports_and_answers_calls(tmp_path, agent_binary):
    async def scenario():
        hub = make_hub(tmp_path)
        task = await started(hub)
        state = tmp_path / "state"
        agent = None
        try:
            _, key, _ = hub.repo.key_create("Admin", "Integration", 1, 1)
            address = f"127.0.0.1:{hub.port}"
            fingerprint = hub.pki.ca_fingerprint

            # falscher Fingerabdruck: der Agent darf dem Hub nicht vertrauen und den Schlüssel nicht preisgeben
            wrong = await sh(str(agent_binary), "enroll", "--hub", address, "--key", key, "--ca-fingerprint", "sha256:" + "0" * 64, "--state-dir", str(tmp_path / "x"))
            assert wrong.returncode == 1 and "vertrauenswürdig" in wrong.stderr
            assert hub.repo.key_check(key) is not None and hub.repo.server_list() == []

            done = await sh(str(agent_binary), "enroll", "--hub", address, "--ca-fingerprint", fingerprint, "--state-dir", str(state),
                            "--name", "integration01", env={"COPILOT_AGENT_KEY": key})
            assert done.returncode == 0, done.stderr
            assert oct((state / "agent.key").stat().st_mode & 0o777) == "0o600"
            [row] = hub.repo.server_list()
            assert row["state"] == "pending" and row["name"] == "integration01"
            again = await sh(str(agent_binary), "enroll", "--hub", address, "--ca-fingerprint", fingerprint, "--state-dir", str(state), env={"COPILOT_AGENT_KEY": key})
            assert again.returncode == 1  # schon angemeldet

            agent = await asyncio.create_subprocess_exec(str(agent_binary), "run", "--state-dir", str(state), stderr=asyncio.subprocess.PIPE)
            await wait_for(lambda: "hostname" in json.loads(hub.repo.server_get(row["id"])["info"] or "{}"))
            info = json.loads(hub.repo.server_get(row["id"])["info"])
            assert info["agent_version"] == "9.9.9" and info["arch"] and info["hostname"] and info["cpus"] >= 1
            with pytest.raises(serverlib.ServerError, match="nicht bestätigt"):
                await hub.call(row["id"], "load")

            hub.confirm(row["id"], "Admin")
            await wait_for(lambda: hub.view(hub.repo.server_get(row["id"]))["status"] in ("online", "degraded"), 70)
            load = None
            for _ in range(20):  # der Agent erfährt die Bestätigung mit der nächsten Antwort
                try:
                    load = await hub.call("integration01", "load")
                    break
                except serverlib.ServerError as exc:
                    if "nicht bestätigt" not in str(exc):
                        raise
                    await asyncio.sleep(0.5)
            assert load and "Load (1/5/15 Min)" in load
            assert "Hostname:" in await hub.call(row["id"], "system")
            assert "Mem" in await hub.call(row["id"], "memory")
            with pytest.raises(serverlib.ServerError, match="ungültige Zeichen"):
                await hub.call(row["id"], "service", {"unit": "a;id"})
            with pytest.raises(serverlib.ServerError, match="Priority|priority"):
                await hub.call(row["id"], "journal", {"priority": "laut"})

            # gesperrt: die Verbindung wird getrennt und kommt nicht wieder durch
            hub.block(row["id"], "Admin")
            with pytest.raises(serverlib.ServerError):
                await hub.call(row["id"], "load")
        finally:
            if agent is not None and agent.returncode is None:
                agent.terminate()
                await asyncio.wait_for(agent.wait(), 10)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


def test_agent_changes_only_with_local_policy_and_after_preparing(tmp_path, agent_binary):
    async def scenario():
        hub = make_hub(tmp_path)
        task = await started(hub)
        state = tmp_path / "state"
        policy = tmp_path / "policy"
        agent = None
        try:
            _, key, _ = hub.repo.key_create("Admin", "Integration", 1, 1)
            address = f"127.0.0.1:{hub.port}"
            done = await sh(str(agent_binary), "enroll", "--hub", address, "--ca-fingerprint", hub.pki.ca_fingerprint, "--state-dir", str(state),
                            "--name", "change01", env={"COPILOT_AGENT_KEY": key})
            assert done.returncode == 0, done.stderr
            [row] = hub.repo.server_list()
            hub.confirm(row["id"], "Admin")  # vor dem Start: die erste Antwort des Hubs nennt den Zustand schon als bestätigt
            run = [str(agent_binary), "run", "--state-dir", str(state), "--policy", str(policy), "--helper-socket", str(tmp_path / "kein-helfer.sock")]

            # ohne Richtlinie: nur lesen, der Hub fragt den Agenten gar nicht erst
            agent = await asyncio.create_subprocess_exec(*run, stderr=asyncio.subprocess.PIPE)
            await wait_for(lambda: "hostname" in json.loads(hub.repo.server_get(row["id"])["info"] or "{}"))
            info = json.loads(hub.repo.server_get(row["id"])["info"])
            assert info["operate"] is False and info["helper"] is False
            with pytest.raises(serverlib.ServerError, match="nicht erlaubt"):
                await hub.prepare("change01", "run_command", {"argv": ["echo", "x"]})
            agent.terminate()
            await asyncio.wait_for(agent.wait(), 10)

            # mit Richtlinie „operate“
            policy.write_text("# Test\nki_access=operate\nmax_class=2\n")
            agent = await asyncio.create_subprocess_exec(*run, stderr=asyncio.subprocess.PIPE)
            await wait_for(lambda: hub.can_change(hub.get(row["id"])))
            assert json.loads(hub.repo.server_get(row["id"])["info"])["max_class"] == 2

            plan = None
            for _ in range(20):
                try:
                    plan = await hub.prepare("change01", "run_command", {"argv": ["echo", "integration-ok"]})
                    break
                except serverlib.ServerError as exc:
                    if "nicht bestätigt" not in str(exc):
                        raise
                    await asyncio.sleep(0.5)
            assert plan and plan["class"] == 2 and plan["runner"] == "agent" and plan["command"] == "echo integration-ok"

            out = await hub.execute("change01", plan)
            assert "integration-ok" in out and "== Ergebnis: erfolgreich ==" in out
            with pytest.raises(serverlib.ServerError, match="unbekannt|abgelaufen|ausgeführt"):
                await hub.execute("change01", plan)  # ein Plan gilt genau einmal
            with pytest.raises(serverlib.ServerError, match="passt nicht"):
                other = await hub.prepare("change01", "run_command", {"argv": ["echo", "zweiter"]})
                await hub.execute("change01", {**other, "hash": "0" * 64})

            # Stufe 3, Root ohne Helfer, ungültige Angaben: abgelehnt, bevor etwas geschieht
            with pytest.raises(serverlib.ServerError, match="Abgelehnt"):
                await hub.prepare("change01", "run_command", {"argv": ["reboot"]})
            with pytest.raises(serverlib.ServerError, match="Abgelehnt"):
                await hub.prepare("change01", "service_action", {"unit": "ssh", "action": "stop"})
            with pytest.raises(serverlib.ServerError, match="Helfer"):
                await hub.prepare("change01", "service_action", {"unit": "nginx", "action": "restart"})
            with pytest.raises(serverlib.ServerError, match="ungültig"):
                await hub.prepare("change01", "package", {"action": "install", "packages": ["Foo;id"]})

            # die Richtlinie wirkt sofort: vorbereiten, dann auf „nur lesen“ stellen, dann scheitert die Ausführung
            plan = await hub.prepare("change01", "run_command", {"argv": ["echo", "spaet"]})
            policy.write_text("ki_access=read\n")
            with pytest.raises(serverlib.ServerError, match="nicht erlaubt"):
                await hub.execute("change01", plan)
        finally:
            if agent is not None and agent.returncode is None:
                agent.terminate()
                await asyncio.wait_for(agent.wait(), 10)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())
