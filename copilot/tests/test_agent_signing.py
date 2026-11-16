"""Signierte Agenten (0.61): Schlüssel des Hubs, Skript (update_key in neuer und alter Richtlinie), Holen der signierten Programme beim Bauen."""
import base64
import hashlib
import http.server
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.server_script import render_script
from test_agent_integration import AGENT_SRC
from test_servers import make_hub

VERSION = "1.2.3"


def pair() -> tuple[Ed25519PrivateKey, str]:
    key = Ed25519PrivateKey.generate()
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return key, base64.b64encode(raw).decode()


def sign(key: Ed25519PrivateKey, version: str, arch: str, data: bytes) -> str:
    message = f"ha-copilot-agent\n{version}\n{arch}\n{hashlib.sha256(data).hexdigest()}\n".encode()
    return base64.b64encode(key.sign(message)).decode() + "\n"


# ------------------------------------------------------------------------------------------------ Hub


def signed_hub(tmp_path, key, key_pub, **override):
    hub = make_hub(tmp_path)
    agent = tmp_path / "agent-bin"
    (agent / "VERSION").write_text(VERSION + "\n")
    for arch in ("amd64", "arm64"):
        path = agent / f"copilot-agent-linux-{arch}"
        (agent / f"copilot-agent-linux-{arch}.sig").write_text(sign(key, override.get("version", VERSION), arch, path.read_bytes()))
    (agent / "update_key.pub").write_text(override.get("pub", key_pub) + "\n")
    return hub, agent


def test_hub_reports_the_key_only_when_every_program_is_validly_signed(tmp_path):
    key, pub = pair()
    hub, agent = signed_hub(tmp_path, key, pub)
    assert hub.update_key() == pub
    # a program that was changed after signing
    (agent / "copilot-agent-linux-arm64").write_bytes(b"other")
    assert hub.update_key() == ""
    (agent / "copilot-agent-linux-arm64").write_bytes(b"arm64-binary")
    assert hub.update_key() == pub
    # a missing signature
    (agent / "copilot-agent-linux-arm64.sig").unlink()
    assert hub.update_key() == ""


@pytest.mark.parametrize("what", ["version", "pub", "garbage_pub", "no_pub"])
def test_hub_does_not_report_a_key_that_would_not_match(tmp_path, what):
    key, pub = pair()
    other_pub = pair()[1]
    if what == "version":
        hub, _ = signed_hub(tmp_path, key, pub, version="0.0.1")  # signature for another version
    elif what == "pub":
        hub, _ = signed_hub(tmp_path, key, pub, pub=other_pub)  # key in the add-on does not belong to the signature
    elif what == "garbage_pub":
        hub, _ = signed_hub(tmp_path, key, pub, pub="not base64!")
    else:
        hub, agent = signed_hub(tmp_path, key, pub)
        (agent / "update_key.pub").unlink()
    assert hub.update_key() == ""


def test_unsigned_programs_have_no_key(tmp_path):
    hub = make_hub(tmp_path)
    (tmp_path / "agent-bin" / "VERSION").write_text(VERSION + "\n")
    assert hub.update_key() == ""


# ------------------------------------------------------------------------------------------------ Skript


def script(**kw) -> str:
    base = dict(hub="ha.example.lan:8101", key="ck_x", ca_fingerprint="ab", hub_pin="cd", hashes={"amd64": "1", "arm64": "2"}, expires="x", max_uses=1)
    return render_script(**{**base, **kw})


def policy_part(text: str, etc: Path) -> str:
    """Der Teil des Skripts, der die Richtlinie anlegt oder ergänzt, lauffähig in einem Testordner."""
    start = text.index("# Local policy:")
    end = text.index("# Root helper:")
    head = "\n".join(line for line in text[: text.index("BIN=/usr/local/bin")].splitlines() if re.match(r"^[A-Z_0-9]+=", line))
    body = text[start:end].replace(" -o root -g root", "")
    return head + f"\nPOLICY_DIR={etc}\nPOLICY=$POLICY_DIR/policy\nsay() {{ echo \"$*\"; }}\n" + body


def run_policy(text: str, etc: Path) -> str:
    done = subprocess.run(["bash", "-c", "set -euo pipefail\n" + policy_part(text, etc)], capture_output=True, text=True, timeout=20)
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_script_writes_update_key_into_a_new_policy(tmp_path):
    _, pub = pair()
    run_policy(script(update_key=pub), tmp_path / "etc")
    policy = (tmp_path / "etc" / "policy").read_text()
    assert re.search(rf"^update_key={re.escape(pub)}$", policy, re.M) and re.search(r"^update=auto$", policy, re.M)
    # without a key the line stays a comment
    run_policy(script(), tmp_path / "etc2")
    assert not re.search(r"^update_key=", (tmp_path / "etc2" / "policy").read_text(), re.M)


def test_script_adds_missing_lines_to_an_old_policy_but_never_changes_existing_ones(tmp_path):
    _, pub = pair()
    etc = tmp_path / "etc"
    etc.mkdir()
    (etc / "policy").write_text("ki_access=read\nmax_class=1\n")  # a 0.60.x policy
    out = run_policy(script(update_key=pub, auto_update=False), etc)
    policy = (etc / "policy").read_text()
    assert policy.startswith("ki_access=read\nmax_class=1\n")  # kept as it was
    assert re.search(r"^update=manual$", policy, re.M) and re.search(rf"^update_key={re.escape(pub)}$", policy, re.M)
    assert "Added the missing line" in out
    # a second run changes nothing
    run_policy(script(update_key=pub, auto_update=False), etc)
    assert (etc / "policy").read_text() == policy
    # existing values (also another key) are never overwritten
    (etc / "policy").write_text("ki_access=operate\nupdate=off\nupdate_key=OTHER\n")
    run_policy(script(update_key=pub, auto_update=True), etc)
    assert (etc / "policy").read_text() == "ki_access=operate\nupdate=off\nupdate_key=OTHER\n"


def test_script_quotes_the_key(tmp_path):
    assert "UPDATE_KEY='a b;c'" in script(update_key="a b;c")


# ------------------------------------------------------------------------------------------------ Holen beim Bauen


@pytest.fixture(scope="module")
def sign_tool(tmp_path_factory) -> Path:
    if shutil.which("go") is None:
        pytest.skip("Go ist nicht installiert")
    out = tmp_path_factory.mktemp("sign") / "copilot-sign"
    done = subprocess.run(["go", "build", "-trimpath", "-o", str(out), "./cmd/copilot-sign"], cwd=AGENT_SRC,
                          env={**os.environ, "GOFLAGS": "-mod=vendor", "CGO_ENABLED": "0"}, capture_output=True, text=True, timeout=240)
    assert done.returncode == 0, done.stderr
    return out


class Release:
    """Ein lokaler Server, der wie GitHub ``/v<Fassung>/<Datei>`` ausliefert."""

    def __init__(self, root: Path) -> None:
        self.root = root
        handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(root), **k)  # noqa: E731
        handler.log_message = lambda *a: None  # type: ignore[attr-defined]
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def publish(self, key, version=VERSION, archs=("amd64", "arm64"), tamper=()) -> None:
        folder = self.root / f"v{version}"
        folder.mkdir(parents=True, exist_ok=True)
        for arch in archs:
            data = f"program-{arch}".encode()
            (folder / f"copilot-agent-linux-{arch}.sig").write_text(sign(key, version, arch, data))
            (folder / f"copilot-agent-linux-{arch}").write_bytes(data + (b"x" if arch in tamper else b""))

    def close(self) -> None:
        self.server.shutdown()


def fetch(tmp_path, tool, pub_text, url, version=VERSION) -> tuple[Path, str]:
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    for arch in ("amd64", "arm64"):
        (out / f"copilot-agent-linux-{arch}").write_bytes(b"local-build")
    pub = tmp_path / "update_key.pub"
    if pub_text is not None:
        pub.write_text(pub_text)
    done = subprocess.run(["sh", str(AGENT_SRC / "fetch-signed.sh"), version, url, str(pub), str(tool), str(out)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr  # the build never fails because of this
    return out, done.stdout


def local_only(out: Path) -> bool:
    return all((out / f"copilot-agent-linux-{a}").read_bytes() == b"local-build" for a in ("amd64", "arm64")) and not list(out.glob("*.sig")) and not (out / "update_key.pub").exists()


@pytest.fixture
def release(tmp_path):
    rel = Release(tmp_path / "releases")
    yield rel
    rel.close()


def test_signed_programs_of_the_release_replace_the_local_build(tmp_path, sign_tool, release):
    key, pub = pair()
    release.publish(key)
    out, said = fetch(tmp_path, sign_tool, pub + "\n", release.url)
    assert (out / "copilot-agent-linux-amd64").read_bytes() == b"program-amd64" and (out / "copilot-agent-linux-arm64").read_bytes() == b"program-arm64"
    assert (out / "copilot-agent-linux-amd64.sig").is_file() and (out / "update_key.pub").read_text().strip() == pub
    assert os.access(out / "copilot-agent-linux-amd64", os.X_OK) and "installed" in said


@pytest.mark.parametrize("case", ["tampered", "other_key", "one_arch_missing", "no_release", "wrong_version"])
def test_anything_wrong_keeps_the_unsigned_local_build(tmp_path, sign_tool, release, case):
    key, pub = pair()
    if case == "tampered":
        release.publish(key, tamper=("arm64",))
    elif case == "other_key":
        release.publish(pair()[0])
    elif case == "one_arch_missing":
        release.publish(key, archs=("amd64",))
    elif case == "wrong_version":
        release.publish(key, version="9.9.9")
    out, said = fetch(tmp_path, sign_tool, pub + "\n", release.url)
    assert local_only(out), said  # nothing is half replaced
    assert "unsigned" in said


@pytest.mark.parametrize("case", ["no_pubkey_file", "empty_pubkey", "dev_version"])
def test_without_key_or_version_nothing_is_fetched(tmp_path, sign_tool, release, case):
    key, pub = pair()
    release.publish(key)
    pub_text = None if case == "no_pubkey_file" else ("" if case == "empty_pubkey" else pub)
    out, said = fetch(tmp_path, sign_tool, pub_text, release.url, version="dev" if case == "dev_version" else VERSION)
    assert local_only(out) and "unsigned" in said


def test_an_unreachable_release_server_does_not_break_the_build(tmp_path, sign_tool):
    key, pub = pair()
    out, said = fetch(tmp_path, sign_tool, pub + "\n", "http://127.0.0.1:9")
    assert local_only(out)
