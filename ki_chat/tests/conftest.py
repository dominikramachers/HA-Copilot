import pytest
from fastapi.testclient import TestClient

from app import i18n
from app.backend import BackendError
from app.config import parse_settings
from app.db import Store
from app.main import build_ingress_app

ADM01 = "0123456789abcdef0123456789abcdef"
DORA = "fedcba9876543210fedcba9876543210"
SAM = "5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a"

RAW = {
    "profiles": [
        {"id": "adm01", "label": "Admin", "ha_user_id": ADM01, "entra_upn": "adm01@example.org"},
        {
            "id": "dora",
            "label": "Dora",
            "ha_user_id": DORA,
            "entra_upn": "dora@example.org",
        },
    ],
    "public_enabled": False,
}

WRITE = {"X-Requested-With": "ki-chat"}


class FakeBackend:
    """Skriptbares Test-Backend: merkt sich Aufrufe, liefert Stücke oder wirft einen Fehler."""

    def __init__(self, pieces=("Hallo ", "Welt"), error=None, fail_after=None):
        self.pieces = list(pieces)
        self.error = error
        self.fail_after = fail_after  # Fehler erst nach so vielen Stücken
        self.calls = []

    async def stream(self, history, message, effort, attachments=None, instructions=None, tools=None, note="", **_):
        self.calls.append({"history": history, "message": message, "effort": effort, "attachments": list(attachments) if attachments is not None else None, "live": attachments, "instructions": instructions, "tools": tools, "note": note})
        for i, piece in enumerate(self.pieces):
            if self.error and self.fail_after is not None and i == self.fail_after:
                raise BackendError(self.error)
            yield piece
        if self.error and self.fail_after is None:
            raise BackendError(self.error)


def as_user(user_id: str, write: bool = False) -> dict:
    headers = {"X-Remote-User-Id": user_id}
    if write:
        headers.update(WRITE)
    return headers


@pytest.fixture(autouse=True)
def german_by_default():
    """Die Sprache ist global; jeder Test beginnt (und endet) mit der Standardsprache Deutsch."""
    i18n.set_language("de")
    yield
    i18n.set_language("de")


@pytest.fixture()
def store(tmp_path):
    s = Store(tmp_path / "test.sqlite3")
    s.sync_profiles(["adm01", "dora"])
    yield s
    s.close()


@pytest.fixture()
def backend():
    return FakeBackend()


@pytest.fixture()
def client(store, backend):
    # Der TestClient meldet sich als Gegenstelle "testclient"; die ist hier als Ingress-Proxy erlaubt.
    settings = parse_settings(RAW, frozenset({"testclient"}))
    return TestClient(build_ingress_app(settings, store, backend))


@pytest.fixture()
def client_untrusted_peer(store, backend):
    settings = parse_settings(RAW, frozenset({"172.30.32.2"}))
    return TestClient(build_ingress_app(settings, store, backend))
