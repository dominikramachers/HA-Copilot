import pytest
from fastapi.testclient import TestClient

from app import i18n
from app.backend import BackendError
import dataclasses

import app.config as _config
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

    async def stream(self, history, message, effort, attachments=None, instructions=None, tools=None, note="", personal_instructions=None, **_):
        self.calls.append({"personal_instructions": personal_instructions, "history": history, "message": message, "effort": effort, "attachments": list(attachments) if attachments is not None else None, "live": attachments, "instructions": instructions, "tools": tools, "note": note})
        for i, piece in enumerate(self.pieces):
            if self.error and self.fail_after is not None and i == self.fail_after:
                raise BackendError(self.error)
            yield piece
        if self.error and self.fail_after is None:
            raise BackendError(self.error)


# Seit 0.45.0 keine Optionen mehr, sondern feste Werte. Einzelne Szenarien brauchen sie trotzdem anders.
FIXED_VALUES = frozenset({
    "files_edit", "files_keep_days", "images_enabled", "web_access_default", "ha_write_confirm",
    "github_write_confirm", "connector_write_confirm", "memory_household_writers", "ha_scan_days", "ha_access_via_domain", "connector_allow_private",
})


# Kurzschreibweise der Tests (flacher Name) -> Gruppe und Feld in der Konfiguration (`chat:`, `images:`, `voice:`)
GROUPED = {
    "model": ("chat", "model"),
    "memory_enabled": ("chat", "memory_enabled"),
    "schedules_enabled": ("chat", "schedules_enabled"),
    "incognito_enabled": ("chat", "incognito_enabled"),
    "sharing": ("chat", "sharing"),
    "research_enabled": ("chat", "research_enabled"),
    "research_daily_limit": ("chat", "research_daily_limit"),
    "files_enabled": ("chat", "files_enabled"),
    "connector_access_default": ("chat", "connector_access_default"),
    "openai_enabled": ("chat", "openai_enabled"),
    "openai_chat_api_key": ("chat", "openai_api_key"),
    "openai_chat_key_expires": ("chat", "openai_key_expires"),
    "openai_models": ("chat", "openai_models"),
    "openai_limit_month": ("chat", "openai_limit_month"),
    "openai_api_key": ("images", "openai_api_key"),
    "google_api_key": ("images", "google_api_key"),
    "image_provider": ("images", "provider"),
    "image_limit_month": ("images", "limit_month"),
}
# Seit 0.54.0 stehen auch die früheren Einzeloptionen in Gruppen (users, chat, domain, look, global)
for _group_name, _keys in _config.MOVED.items():
    for _key in _keys:
        GROUPED[_key] = (_group_name, _key)


def nest_options(raw):
    """Die flachen Kurznamen der Tests in die Gruppen der Add-on-Konfiguration übersetzen (fertige Gruppen bleiben, wie sie sind)."""
    out = {}
    for key, value in raw.items():
        if key in GROUPED:
            group, field = GROUPED[key]
            out.setdefault(group, {})
            if isinstance(out[group], dict):
                out[group] = {**out[group], field: value}
        else:
            out[key] = value if key not in out else out[key]
    for group in ("users", "chat", "images", "voice", "domain", "look", "global"):  # eine fertig angegebene Gruppe ergänzen statt zu überschreiben
        if isinstance(raw.get(group), dict) and isinstance(out.get(group), dict):
            out[group] = {**raw[group], **out[group]}
    return out


def _parse_with_shorthand(raw, *args, **kwargs):
    return _real_parse_settings(nest_options(raw) if isinstance(raw, dict) else raw, *args, **kwargs)


# Alle Tests (auch die, die ``parse_settings`` selbst importieren) dürfen die flachen Kurznamen benutzen; die echte
# Funktion mit dem Format der Konfiguration bleibt über ``parse_settings.__wrapped__`` erreichbar.
_real_parse_settings = getattr(_config.parse_settings, "__wrapped__", _config.parse_settings)  # nicht doppelt einpacken, falls conftest zweimal geladen wird
_parse_with_shorthand.__wrapped__ = _real_parse_settings
_config.parse_settings = parse_settings = _parse_with_shorthand


def parse_with_fixed(raw, peers=None):
    """Wie ``parse_settings`` mit den Kurznamen der Tests (``nest_options``); Schlüssel aus FIXED_VALUES setzen das Feld direkt."""
    raw = dict(raw)
    fixed = {k: raw.pop(k) for k in list(raw) if k in FIXED_VALUES}
    settings = parse_settings(nest_options(raw), peers)
    return dataclasses.replace(settings, **fixed) if fixed else settings


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
