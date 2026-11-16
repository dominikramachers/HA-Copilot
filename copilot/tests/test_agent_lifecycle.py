"""Der echte Go-Agent gegen den echten Hub (0.61): Zertifikatserneuerung, Selbstaktualisierung, neue Werkzeuge, Dateien schreiben.

Wird übersprungen, wenn Go fehlt; die Tests mit Root-Helfer laufen nur als root (der Helfer verlangt es).
"""
import asyncio
import base64
import hashlib
import json
import os
import shutil
import ssl
import subprocess
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app import servers as serverlib
from app.server_messages import localize
from app.server_tools import plan_details

from test_agent_integration import AGENT_SRC, sh, started, wait_for
from test_servers import make_hub

pytestmark = pytest.mark.skipif(shutil.which("go") is None, reason="Go ist nicht installiert")
needs_root = pytest.mark.skipif(os.geteuid() != 0, reason="der Root-Helfer läuft nur als root")


def build(out: Path, version: str) -> Path:
    env = {**os.environ, "GOFLAGS": "-mod=vendor", "CGO_ENABLED": "0"}
    done = subprocess.run(
        ["go", "build", "-trimpath", "-ldflags", f"-X main.version={version}", "-o", str(out), "./cmd/copilot-agent"],
        cwd=AGENT_SRC, env=env, capture_output=True, text=True, timeout=240,
    )
    assert done.returncode == 0, done.stderr
    return out


@pytest.fixture(scope="module")
def old_agent(tmp_path_factory) -> Path:
    return build(tmp_path_factory.mktemp("agent-old") / "copilot-agent", "9.9.9")


@pytest.fixture(scope="module")
def new_agent(tmp_path_factory) -> Path:
    return build(tmp_path_factory.mktemp("agent-new") / "copilot-agent", "9.9.10")


async def enroll(hub, binary: Path, state: Path, name: str) -> dict:
    _, key, _ = hub.repo.key_create("Admin", "Lifecycle", 1, 1)
    done = await sh(str(binary), "enroll", "--hub", f"127.0.0.1:{hub.port}", "--ca-fingerprint", hub.pki.ca_fingerprint, "--state-dir", str(state),
                    "--name", name, env={"COPILOT_AGENT_KEY": key})
    assert done.returncode == 0, done.stderr
    [row] = [r for r in hub.repo.server_list() if r["name"] == name]
    hub.confirm(row["id"], "Admin")
    return row


def info_of(hub, server_id: str) -> dict:
    return json.loads(hub.repo.server_get(server_id)["info"] or "{}")


def cert_hash_on_disk(state: Path) -> str:
    pem = (state / "agent.crt").read_text()
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()


async def stop(proc) -> None:
    if proc is not None and proc.returncode is None:
        proc.terminate()
        await asyncio.wait_for(proc.wait(), 10)


# ------------------------------------------------------------------------------------------------ Zertifikat


def test_certificate_is_renewed_automatically_before_it_expires(tmp_path, old_agent, monkeypatch):
    monkeypatch.setattr(serverlib, "CERT_DAYS", 100)  # weniger als die 120 Tage, ab denen der Agent erneuert

    async def scenario():
        hub = make_hub(tmp_path)
        task = await started(hub)
        state = tmp_path / "state"
        agent = None
        try:
            row = await enroll(hub, old_agent, state, "renew01")
            first = row["cert_hash"]
            assert cert_hash_on_disk(state) == first
            agent = await asyncio.create_subprocess_exec(str(old_agent), "run", "--state-dir", str(state), "--policy", str(tmp_path / "policy"),
                                                         "--helper-socket", str(tmp_path / "none.sock"), stderr=asyncio.subprocess.PIPE)
            await wait_for(lambda: hub.repo.server_get(row["id"])["cert_hash"] != first, 40)
            renewed = hub.repo.server_get(row["id"])
            assert renewed["cert_renewed_at"]
            # der Agent legt das neue Zertifikat ab und meldet sich damit; danach gilt das alte nicht mehr
            await wait_for(lambda: hub.repo.server_get(row["id"])["prev_cert_hash"] == "", 40)
            assert cert_hash_on_disk(state) == renewed["cert_hash"] != first
            assert hub.repo.server_by_cert(first) is None
            await wait_for(lambda: hub.view(hub.repo.server_get(row["id"]))["status"] in ("online", "degraded"), 40)
            assert any(item["summary"] == "Zertifikat erneuert" for item in hub.repo.audit_list(server_id=row["id"]))
            # das neue Zertifikat ist (wegen der kurzen Laufzeit im Test) schon wieder fällig, aber der Agent fragt nicht bei jeder
            # Verbindung neu an, sondern höchstens alle 30 Minuten
            await asyncio.sleep(4)
            assert hub.repo.server_get(row["id"])["cert_hash"] == renewed["cert_hash"]
        finally:
            await stop(agent)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


def test_certificate_renewal_on_request_from_the_overview(tmp_path, old_agent):
    async def scenario():
        hub = make_hub(tmp_path)
        task = await started(hub)
        state = tmp_path / "state"
        agent = None
        try:
            row = await enroll(hub, old_agent, state, "renew02")
            first = row["cert_hash"]
            agent = await asyncio.create_subprocess_exec(str(old_agent), "run", "--state-dir", str(state), "--policy", str(tmp_path / "policy"),
                                                         "--helper-socket", str(tmp_path / "none.sock"), stderr=asyncio.subprocess.PIPE)
            await wait_for(lambda: info_of(hub, row["id"]).get("cert_expires"), 20)
            days = serverlib.cert_days_left(info_of(hub, row["id"]))
            assert days is not None and 360 <= days <= 365
            hub.renew_now(row["id"], "Admin")
            await wait_for(lambda: hub.repo.server_get(row["id"])["cert_hash"] != first, 20)
            await wait_for(lambda: hub.repo.server_get(row["id"])["prev_cert_hash"] == "", 30)
            assert cert_hash_on_disk(state) == hub.repo.server_get(row["id"])["cert_hash"]
            assert any(item["summary"] == "Zertifikatserneuerung angestoßen" for item in hub.repo.audit_list(server_id=row["id"]))
            hub.block(row["id"], "Admin")
            with pytest.raises(serverlib.ServerError):
                hub.renew_now("srv-unbekannt", "Admin")
        finally:
            await stop(agent)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


# ------------------------------------------------------------------------------------------------ Aktualisierung


class Setup:
    """Hub mit der neuen Fassung im Add-on, ein Server mit der alten, installiert unter ``bin`` mit Root-Helfer."""

    def __init__(self, tmp_path: Path, old_agent: Path, new_agent: Path, policy_text: str) -> None:
        self.tmp = tmp_path
        self.hub = make_hub(tmp_path)
        for item in (tmp_path / "agent-bin").iterdir():
            item.unlink()
        arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(os.uname().machine, "amd64")
        shutil.copy(new_agent, tmp_path / "agent-bin" / f"copilot-agent-linux-{arch}")
        (tmp_path / "agent-bin" / "VERSION").write_text("9.9.10\n")
        self.state = tmp_path / "state"
        self.policy_dir = tmp_path / "etc"
        self.policy_dir.mkdir()
        self.policy = self.policy_dir / "policy"
        self.policy.write_text(policy_text)
        self.bin = tmp_path / "install" / "copilot-agent"
        self.bin.parent.mkdir()
        shutil.copy(old_agent, self.bin)
        self.sock = tmp_path / "helper.sock"
        self.helper = None
        self.agent = None

    async def start_helper(self) -> None:
        self.helper = await asyncio.create_subprocess_exec(
            str(self.bin), "helper", "--policy", str(self.policy), "--socket", str(self.sock), "--agent-user", "root", "--state-dir", str(self.state),
            "--bin", str(self.bin), stderr=asyncio.subprocess.PIPE)
        await wait_for(lambda: self.sock.exists())

    async def start_agent(self) -> None:
        self.agent = await asyncio.create_subprocess_exec(
            str(self.bin), "run", "--state-dir", str(self.state), "--policy", str(self.policy), "--helper-socket", str(self.sock),
            stderr=asyncio.subprocess.PIPE)

    async def stop(self) -> None:
        await stop(self.agent)
        await stop(self.helper)

    def installed_version(self) -> str:
        return subprocess.run([str(self.bin), "version"], capture_output=True, text=True, timeout=10).stdout.strip()


@needs_root
def test_update_on_request_installs_confirms_and_respects_the_local_policy(tmp_path, old_agent, new_agent):
    async def scenario():
        setup = Setup(tmp_path, old_agent, new_agent, "ki_access=operate\nupdate=manual\n")
        hub = setup.hub
        task = await started(hub)
        try:
            row = await enroll(hub, old_agent, setup.state, "update01")
            await setup.start_helper()
            await setup.start_agent()
            await wait_for(lambda: info_of(hub, row["id"]).get("update_mode") == "manual", 20)
            view = hub.view(hub.repo.server_get(row["id"]))
            assert view["update"]["available"] == "9.9.10" and view["update"]["mode"] == "manual"
            assert setup.installed_version() == "9.9.9"
            # manuell: das Angebot im Hub allein ändert nichts
            await asyncio.sleep(3)
            assert setup.installed_version() == "9.9.9"

            message = await hub.update_agent(row["id"], "Admin")
            assert "Update started" in message
            await wait_for(lambda: setup.installed_version() == "9.9.10", 30)
            assert (setup.bin.parent / "copilot-agent.prev").exists() and (setup.policy_dir / "update-pending").exists()

            # Der alte Agent läuft noch (ohne systemd startet nichts neu): wie beim Neustart durch systemd kommt jetzt die neue Fassung
            await stop(setup.agent)
            await setup.start_agent()
            await wait_for(lambda: info_of(hub, row["id"]).get("agent_version") == "9.9.10", 30)
            await wait_for(lambda: not (setup.policy_dir / "update-pending").exists(), 30)  # bestätigt: der Rücksetzer entfällt
            assert hub.view(hub.repo.server_get(row["id"]))["update"]["available"] == ""
            with pytest.raises(serverlib.ServerError, match="keine neuere Fassung"):
                await hub.update_agent(row["id"], "Admin")
            assert any("angestoßen" in item["summary"] for item in hub.repo.audit_list(server_id=row["id"]))
        finally:
            await setup.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


@needs_root
def test_update_is_refused_when_the_policy_says_off(tmp_path, old_agent, new_agent):
    async def scenario():
        setup = Setup(tmp_path, old_agent, new_agent, "ki_access=operate\nupdate=off\n")
        hub = setup.hub
        task = await started(hub)
        try:
            row = await enroll(hub, old_agent, setup.state, "update02")
            await setup.start_helper()
            await setup.start_agent()
            await wait_for(lambda: info_of(hub, row["id"]).get("update_mode") == "off", 20)
            with pytest.raises(serverlib.ServerError, match="update=off"):
                await hub.update_agent(row["id"], "Admin")
            assert setup.installed_version() == "9.9.9"
            assert any(item["result"] == "denied" for item in hub.repo.audit_list(server_id=row["id"]))
        finally:
            await setup.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


@needs_root
def test_update_happens_by_itself_with_update_auto(tmp_path, old_agent, new_agent):
    async def scenario():
        setup = Setup(tmp_path, old_agent, new_agent, "ki_access=read\nupdate=auto\n")
        hub = setup.hub
        task = await started(hub)
        try:
            await enroll(hub, old_agent, setup.state, "update03")
            await setup.start_helper()
            await setup.start_agent()
            await wait_for(lambda: setup.installed_version() == "9.9.10", 40)  # ohne jeden Knopfdruck
            assert (setup.policy_dir / "update-pending").exists()
        finally:
            await setup.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


@needs_root
def test_update_needs_a_valid_signature_when_update_key_is_set(tmp_path, old_agent, new_agent):
    async def scenario():
        key = "A" * 43 + "="  # ein gültig geformter, aber fremder Schlüssel
        setup = Setup(tmp_path, old_agent, new_agent, f"ki_access=read\nupdate=auto\nupdate_key={key}\n")
        hub = setup.hub
        task = await started(hub)
        try:
            row = await enroll(hub, old_agent, setup.state, "update04")
            await setup.start_helper()
            await setup.start_agent()
            await wait_for(lambda: info_of(hub, row["id"]).get("update_mode") == "auto", 20)
            await asyncio.sleep(4)  # der Agent versucht es und die Prüfung der Signatur im Helfer schlägt fehl
            assert setup.installed_version() == "9.9.9"
            assert not (setup.policy_dir / "update-pending").exists()
        finally:
            await setup.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


def signing_pair() -> tuple[Ed25519PrivateKey, str]:
    key = Ed25519PrivateKey.generate()
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return key, base64.b64encode(raw).decode()


def sign_for_hub(setup: "Setup", key: Ed25519PrivateKey, version: str) -> None:
    """Legt die Signatur des Add-ons für das mitgelieferte Programm ab, genau wie der Release-Workflow (copilot-sign)."""
    [(arch, path)] = setup.hub.agent_binaries().items()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    message = f"ha-copilot-agent\n{version}\n{arch}\n{digest}\n".encode()
    path.with_name(path.name + ".sig").write_text(base64.b64encode(key.sign(message)).decode() + "\n")


@needs_root
def test_a_correctly_signed_update_is_installed_when_update_key_is_set(tmp_path, old_agent, new_agent):
    async def scenario():
        key, pub = signing_pair()
        setup = Setup(tmp_path, old_agent, new_agent, f"ki_access=read\nupdate=auto\nupdate_key={pub}\n")
        sign_for_hub(setup, key, "9.9.10")
        hub = setup.hub
        assert hub.update_key() == ""  # noch ohne öffentlichen Schlüssel im Add-on: nicht als signiert gemeldet
        (tmp_path / "agent-bin" / "update_key.pub").write_text(pub + "\n")
        assert hub.update_key() == pub
        task = await started(hub)
        try:
            await enroll(hub, old_agent, setup.state, "update06")
            await setup.start_helper()
            await setup.start_agent()
            await wait_for(lambda: setup.installed_version() == "9.9.10", 40)
        finally:
            await setup.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


@needs_root
def test_an_update_signed_with_another_key_is_refused(tmp_path, old_agent, new_agent):
    async def scenario():
        _, pub = signing_pair()
        stranger, _ = signing_pair()
        setup = Setup(tmp_path, old_agent, new_agent, f"ki_access=read\nupdate=auto\nupdate_key={pub}\n")
        sign_for_hub(setup, stranger, "9.9.10")  # gültig geformt, aber nicht vom Schlüssel der Richtlinie
        hub = setup.hub
        task = await started(hub)
        try:
            row = await enroll(hub, old_agent, setup.state, "update07")
            await setup.start_helper()
            await setup.start_agent()
            await wait_for(lambda: info_of(hub, row["id"]).get("update_mode") == "auto", 20)
            await asyncio.sleep(4)
            assert setup.installed_version() == "9.9.9" and not (setup.policy_dir / "update-pending").exists()
        finally:
            await setup.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


@needs_root
def test_a_download_needs_the_certificate_of_a_confirmed_server(tmp_path, old_agent, new_agent):
    async def scenario():
        setup = Setup(tmp_path, old_agent, new_agent, "ki_access=read\nupdate=manual\n")
        hub = setup.hub
        task = await started(hub)
        try:
            row = await enroll(hub, old_agent, setup.state, "update05")
            arch = next(iter(hub.agent_binaries()))
            url = f"https://127.0.0.1:{hub.port}/agent-update/{arch}"

            def fetch(cert: bool):
                context = ssl.create_default_context(cadata=hub.pki.ca_pem)
                context.check_hostname = False
                context.verify_flags &= ~ssl.VERIFY_X509_STRICT  # Python 3.13 verlangt sonst eine Authority-Key-ID, die die Hub-CA nicht setzt
                if cert:
                    context.load_cert_chain(str(setup.state / "agent.crt"), str(setup.state / "agent.key"))
                import urllib.error
                import urllib.request
                try:
                    with urllib.request.urlopen(url, context=context, timeout=10) as response:
                        return response.status, response.read()
                except urllib.error.HTTPError as exc:
                    return exc.code, b""

            assert (await asyncio.to_thread(fetch, False))[0] == 403  # ohne Zertifikat
            status, body = await asyncio.to_thread(fetch, True)
            assert status == 200 and hashlib.sha256(body).hexdigest() == hub.update_offer(arch, "0.0.1")["sha256"]
            hub.block(row["id"], "Admin")
            assert (await asyncio.to_thread(fetch, True))[0] == 403
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


# ------------------------------------------------------------------------------------------------ Werkzeuge


def test_new_read_tools(tmp_path, old_agent):
    async def scenario():
        hub = make_hub(tmp_path)
        task = await started(hub)
        state = tmp_path / "state"
        agent = None
        try:
            row = await enroll(hub, old_agent, state, "tools01")
            agent = await asyncio.create_subprocess_exec(str(old_agent), "run", "--state-dir", str(state), "--policy", str(tmp_path / "policy"),
                                                         "--helper-socket", str(tmp_path / "none.sock"), stderr=asyncio.subprocess.PIPE)
            await wait_for(lambda: info_of(hub, row["id"]).get("hostname"), 20)
            await asyncio.sleep(1.5)  # nach der Bestätigung erfährt der Agent den Zustand mit der nächsten Antwort

            async def call(tool, args=None):
                for _ in range(30):
                    try:
                        return await hub.call(row["id"], tool, args)
                    except serverlib.ServerError as exc:
                        if "not been confirmed" not in str(exc):
                            raise
                        await asyncio.sleep(0.5)
                raise AssertionError("nicht bestätigt")

            note = tmp_path / "notes.txt"
            note.write_text("\n".join(f"zeile {i}" for i in range(1, 301)) + "\n")
            head = await call("file_read", {"path": str(note), "lines": 3})
            assert "zeile 1\nzeile 2\nzeile 3" in head and "first 3 lines" in head
            tail = await call("file_read", {"path": str(note), "lines": 2, "from": "end"})
            assert "zeile 300" in tail and "zeile 1\n" not in tail
            assert "notes.txt" in await call("file_read", {"path": str(tmp_path)})
            for refused in ("/etc/shadow", str(tmp_path / ".ssh" / "id_rsa")):
                with pytest.raises(serverlib.ServerError, match="confidential|no such|cannot"):
                    await call("file_read", {"path": refused})
            with pytest.raises(serverlib.ServerError):
                await call("file_read", {"path": "relative.txt"})
            assert "Metrics" in await call("metrics", {"minutes": 30}) or "No metrics" in await call("metrics")
            with pytest.raises(serverlib.ServerError, match="package is required"):
                await call("package_info", {"package": "Bad;Name"})
            assert "Package: " in await call("package_info", {"package": "bash"}) or "Not installed" in await call("package_info", {"package": "bash"})
            with pytest.raises(serverlib.ServerError, match="root helper"):
                await call("docker", {"what": "ps"})  # ohne Helfer gibt es kein Docker
            with pytest.raises(serverlib.ServerError):
                await call("docker", {"what": "exec", "container": "x"})
        finally:
            await stop(agent)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


@needs_root
def test_file_write_shows_a_diff_writes_with_a_backup_and_respects_write_paths(tmp_path, old_agent):
    async def scenario():
        work = tmp_path / "work"
        work.mkdir()
        target = work / "app.conf"
        target.write_text("port=80\nmode=old\n")
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        hub = make_hub(tmp_path)
        task = await started(hub)
        state = tmp_path / "state"
        policy = tmp_path / "policy"
        policy.write_text(f"ki_access=operate\nwrite_paths={work}\n")
        sock = tmp_path / "helper.sock"
        helper = agent = None
        try:
            row = await enroll(hub, old_agent, state, "write01")
            helper = await asyncio.create_subprocess_exec(
                str(old_agent), "helper", "--policy", str(policy), "--socket", str(sock), "--agent-user", "root", "--state-dir", str(state),
                "--bin", str(tmp_path / "unused"), stderr=asyncio.subprocess.PIPE)
            await wait_for(lambda: sock.exists())
            agent = await asyncio.create_subprocess_exec(str(old_agent), "run", "--state-dir", str(state), "--policy", str(policy),
                                                         "--helper-socket", str(sock), stderr=asyncio.subprocess.PIPE)
            await wait_for(lambda: info_of(hub, row["id"]).get("operate"), 20)

            async def prepare(path, content, **extra):
                for _ in range(30):
                    try:
                        return await hub.prepare("write01", "file_write", {"path": str(path), "content": content, **extra})
                    except serverlib.ServerError as exc:
                        if "not been confirmed" not in str(exc):
                            raise
                        await asyncio.sleep(0.5)
                raise AssertionError("nicht bestätigt")

            plan = await prepare(target, "port=8080\nmode=new\n")
            assert plan["tool"] == "file_write" and plan["class"] == 2 and plan["runner"] == "root"
            assert "-mode=old" in plan["preview"] and "+mode=new" in plan["preview"] and plan["msgs"]["preview"]["code"] == "file.preview_diff"
            # Freigabekarte: deutsch (Vorlage zum Code) und englisch (Text des Agenten)
            from app.i18n import set_language

            set_language("de")
            card = plan_details(plan, "write01", "Port ändern")
            assert "Änderungen an" in card and "Zeile(n) neu" in card and "Sicherungskopie" in card
            set_language("en")
            try:
                assert "Changes to" in plan_details(plan, "write01", "")
            finally:
                set_language("de")
            assert target.read_text() == "port=80\nmode=old\n"  # nichts passiert vor der Freigabe

            out = await hub.execute("write01", plan)
            assert "Wrote" in out and "Backup of the previous version" in out
            assert target.read_text() == "port=8080\nmode=new\n"
            backups = list(work.glob("app.conf.copilot-bak-*"))
            assert len(backups) == 1 and backups[0].read_text() == "port=80\nmode=old\n"

            # nur im erlaubten Verzeichnis, nie in Systemdateien
            with pytest.raises(serverlib.ServerError, match="not allowed"):
                other = await prepare(elsewhere / "x.conf", "a=1\n")
                await hub.execute("write01", other)
            with pytest.raises(serverlib.ServerError, match="Refused"):
                await prepare("/etc/passwd", "root::0:0:::\n")
            # hat sich die Datei nach der Vorschau geändert, wird nicht geschrieben
            stale = await prepare(target, "a=1\n")
            target.write_text("jemand=anderes\n")
            with pytest.raises(serverlib.ServerError, match="changed since"):
                await hub.execute("write01", stale)
            assert target.read_text() == "jemand=anderes\n"
        finally:
            await stop(agent)
            await stop(helper)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


# ------------------------------------------------------------------------------------------------ Hub allein


def test_old_certificate_stops_working_after_a_week(tmp_path):
    hub = make_hub(tmp_path)
    hub.repo.server_create("srv-a", "a", "hash-old", "k")
    assert hub.repo.server_renewed("srv-a", "hash-new")
    row, old = hub.repo.server_by_cert("hash-old")
    assert row["id"] == "srv-a" and old is True
    row, old = hub.repo.server_by_cert("hash-new")
    assert old is False
    hub.repo._x("UPDATE servers SET cert_renewed_at = ? WHERE id = 'srv-a'", ("2020-01-01T00:00:00+00:00",))
    assert hub.repo.server_by_cert("hash-old") is None  # das alte Zertifikat gilt nur kurz
    assert hub.repo.server_by_cert("hash-new") is not None
    hub.repo.server_cert_settled("srv-a")
    assert hub.repo.server_get("srv-a")["prev_cert_hash"] == ""
    assert hub.repo.server_by_cert("") is None


def test_update_offer_needs_a_newer_version_and_a_real_file(tmp_path):
    hub = make_hub(tmp_path)
    assert hub.update_offer("amd64", "0.60.8") is None  # keine VERSION: Entwicklungsstand
    (tmp_path / "agent-bin" / "VERSION").write_text("0.61.0\n")
    offer = hub.update_offer("amd64", "0.60.8")
    assert offer == {"version": "0.61.0", "sha256": hashlib.sha256(b"amd64-binary").hexdigest(), "size": len(b"amd64-binary")}
    assert hub.update_offer("amd64", "0.61.0") is None and hub.update_offer("amd64", "0.62.0") is None
    assert hub.update_offer("amd64", "dev") is None and hub.update_offer("riscv", "0.60.8") is None
    (tmp_path / "agent-bin" / "copilot-agent-linux-amd64.sig").write_text("c2ln\n")
    assert hub.update_offer("amd64", "0.60.8")["sig"] == "c2ln"
    (tmp_path / "agent-bin" / "VERSION").write_text("kaputt\n")
    assert hub.update_offer("amd64", "0.60.8") is None
    assert serverlib.version_newer("0.61.0", "0.60.9") and not serverlib.version_newer("0.61.0", "0.61.0") and serverlib.version_newer("v1.0.0", "0.99.0")
    assert serverlib.parse_version("0.061.0") is None and serverlib.parse_version("1.2") is None


def test_heartbeat_fields_of_0_61_are_validated():
    base = {"hostname": "h"}
    clean = serverlib.clean_heartbeat({**base, "cert_expires": "2027-03-04T05:06:07+01:00", "update_mode": "auto", "update_failed": "0.61.0", "update_reason": "x" * 999})
    assert clean["cert_expires"] == "2027-03-04T04:06:07+00:00" and clean["update_mode"] == "auto" and len(clean["update_reason"]) == 300
    bad = serverlib.clean_heartbeat({**base, "cert_expires": "morgen", "update_mode": "sofort", "update_failed": 5})
    assert bad["cert_expires"] == "" and bad["update_mode"] == "" and bad["update_failed"] == ""
    assert serverlib.clean_heartbeat({**base, "cert_expires": 1893456000})["cert_expires"] == "2030-01-01T00:00:00+00:00"  # Unix-Sekunden vom Agenten
    assert serverlib.clean_heartbeat({**base, "cert_expires": True})["cert_expires"] == "" and serverlib.clean_heartbeat({**base, "cert_expires": -5})["cert_expires"] == ""
    assert serverlib.clean_heartbeat({**base, "cert_expires": "2027-03-04T05:06:07"})["cert_expires"] == ""  # ohne Zeitzone unbrauchbar


def test_messages_are_shown_in_the_language_of_the_person():
    from app import i18n

    plan = serverlib.clean_plan({
        "id": "a" * 24, "hash": "b" * 64, "tool": "package", "class": 2, "command": "apt-get install x", "reason": "Removing packages can affect services.",
        "summary": "Remove: nginx, curl", "undo": "Not needed.", "preview": "Dry run: 0 package(s) to install or upgrade, 2 to remove.\nRemove: nginx, curl",
        "msgs": {
            "reason": {"code": "pkg.reason.remove", "text": "Removing packages can affect services."},
            "summary": {"code": "pkg.summary.remove", "text": "Remove: nginx, curl", "params": {"packages": "nginx, curl"}},
            "undo": {"code": "pkg.undo_none", "text": "Not needed."},
            "preview": {"code": "pkg.preview.sim", "text": "Dry run: 0 package(s) to install or upgrade, 2 to remove.", "params": {"inst": "0", "remv": "2"},
                        "then": [{"code": "pkg.preview.removes", "text": "Remove: nginx, curl", "params": {"packages": "nginx, curl", "more": "5"}}]},
        },
    })
    i18n.set_language("de")
    try:
        assert localize(plan, "summary") == "Entfernen: nginx, curl"
        assert localize(plan, "preview") == "Trockenlauf: 0 Paket(e) installieren oder aktualisieren, 2 entfernen.\nEntfernen: nginx, curl … und 5 weitere"
        i18n.set_language("en")
        assert localize(plan, "summary") == "Remove: nginx, curl"
        assert localize(plan, "preview").startswith("Dry run: 0 package(s)")
        i18n.set_language("de")
        # unbekannter Code (neuerer Agent): der englische Text bleibt, nie ein halber Satz
        plan["msgs"]["reason"]["code"] = "pkg.reason.erfunden"
        assert localize(plan, "reason") == "Removing packages can affect services."
        # kein msgs (älterer Agent): der Text des Agenten
        assert localize({"reason": "Hallo"}, "reason") == "Hallo"
        # root mit angehängter Begründung
        root = {"reason": "The command runs as root. Deletes files.", "msgs": {"reason": {"code": "run.root", "text": "The command runs as root. Deletes files.",
                                                                                         "then": [{"code": "run.rm", "text": "Deletes files."}]}}}
        assert localize(root, "reason", sep=" ") == "Der Befehl läuft als root. Löscht Dateien."
    finally:
        i18n.set_language("de")


def test_agent_messages_are_cleaned():
    from app.server_messages import clean_msg

    assert clean_msg({"text": 5}) is None and clean_msg("x") is None
    deep = {"text": "a", "then": [{"text": "b", "then": [{"text": "c", "then": [{"text": "d"}]}]}]}
    cleaned = clean_msg(deep)
    assert cleaned["then"][0]["then"][0]["then"] == [] or "then" not in cleaned["then"][0]["then"][0]  # zu tief verschachtelt: gekappt
    dirty = clean_msg({"text": "x\x00y" + "z" * 9000, "code": "Boese Code!", "params": {"k": "v\x1b", 5: "nein", "list": ["x"]}})
    assert "\x00" not in dirty["text"] and len(dirty["text"]) == 6000 and "code" not in dirty and dirty["params"] == {"k": "v"}
