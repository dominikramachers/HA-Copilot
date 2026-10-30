import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM")
def test_sigterm_shuts_down_cleanly_with_exit_code_zero(tmp_path):
    options = tmp_path / "options.json"
    options.write_text(json.dumps({
        "profiles": [{"id": "adm01", "label": "Admin", "ha_user_id": "0123456789abcdef0123456789abcdef"}],
        "public_enabled": False,
    }))
    port = _free_port()
    env = {
        **os.environ,
        "KI_CHAT_OPTIONS": str(options),
        "KI_CHAT_DB": str(tmp_path / "ki.sqlite3"),
        "KI_CHAT_BRANDING": str(tmp_path / "branding"),
        "KI_CHAT_PORT": str(port),
        "KI_CHAT_INGRESS_PEERS": "127.0.0.1",
    }
    env.pop("SUPERVISOR_TOKEN", None)
    proc = subprocess.Popen([sys.executable, "-m", "app.main"], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            with socket.socket() as s:
                s.settimeout(0.3)
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    break
            assert proc.poll() is None, proc.stdout.read()
            time.sleep(0.2)
        else:
            pytest.fail("Server wurde nicht erreichbar")
        proc.send_signal(signal.SIGTERM)
        code = proc.wait(timeout=15)
        out = proc.stdout.read()
        assert code == 0, f"Exit-Code {code}\n{out}"
    finally:
        if proc.poll() is None:
            proc.kill()
