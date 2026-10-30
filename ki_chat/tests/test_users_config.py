"""Benutzer werden nur in der Add-on-Konfiguration gepflegt; Benutzernamen werden zu Home-Assistant-IDs aufgelöst."""
import asyncio
import copy

import pytest
from fastapi.testclient import TestClient

from app.config import ConfigError, parse_settings
from app.ha_client import HaApi, HaApiError
from app.identity import Registry
from app.main import _resolve_loop, build_ingress_app

from conftest import DORA, RAW, as_user

ANNA = "a" * 32
BEN = "b" * 32
USERS = [
    {"id": ANNA, "name": "Anna Müller", "username": "anna", "person": "Anna"},
    {"id": BEN, "name": "Ben", "username": "ben", "person": ""},
    {"id": DORA, "name": "Dora", "username": "dora", "person": "Dora"},
]


def settings_with(profiles):
    raw = copy.deepcopy(RAW)
    raw["profiles"] = profiles
    return parse_settings(raw, frozenset({"testclient"}))


def test_profile_needs_only_label_and_a_user_name():
    s = settings_with([{"label": "Anna", "ha_user": " Anna  "}])
    assert s.profiles[0].id == "anna" and s.profiles[0].ha_user == "Anna" and s.profiles[0].ha_user_id == ""


def test_user_name_rules():
    for bad in ("<b>", "x" * 65):
        with pytest.raises(ConfigError):
            settings_with([{"label": "A", "ha_user": bad}])
    with pytest.raises(ConfigError):  # derselbe Benutzername zweimal (Groß-/Kleinschreibung egal)
        settings_with([{"label": "A", "ha_user": "anna"}, {"label": "B", "ha_user": "ANNA"}])


def test_name_is_resolved_by_login_name_or_person_but_not_by_display_name():
    for wanted in ("anna", "ANNA", "Anna"):
        registry = Registry(settings_with([{"label": "Anna", "ha_user": wanted}]).profiles)
        assert registry.by_ha_user_id(ANNA) is None and len(registry.pending()) == 1
        notes = registry.apply_ha_users(USERS)
        assert registry.by_ha_user_id(ANNA).label == "Anna" and registry.pending() == [] and "zugeordnet" in notes[0]
    registry = Registry(settings_with([{"label": "B", "ha_user": "Ben"}]).profiles)
    registry.apply_ha_users(USERS)
    assert registry.by_ha_user_id(BEN.upper()).id == "user-b"
    # Der Anzeigename ist in HA frei änderbar und darf deshalb nie einen Zugang begründen
    registry = Registry(settings_with([{"label": "A", "ha_user": "Anna Müller"}]).profiles)
    registry.apply_ha_users(USERS)
    assert registry.by_ha_user_id(ANNA) is None and len(registry.pending()) == 1


def test_unknown_or_ambiguous_names_give_no_access():
    registry = Registry(settings_with([{"label": "X", "ha_user": "gibt-es-nicht"}]).profiles)
    notes = registry.apply_ha_users(USERS)
    assert "keinen Home-Assistant-Benutzer" in notes[0] and len(registry.pending()) == 1
    assert all(registry.by_ha_user_id(u["id"]) is None for u in USERS)
    twins = USERS + [{"id": "c" * 32, "name": "X", "username": "anna2", "person": "Anna"}]
    registry = Registry(settings_with([{"label": "A", "ha_user": "Anna"}]).profiles)
    assert "mehrere" in registry.apply_ha_users(twins)[0] and registry.by_ha_user_id(ANNA) is None


def test_an_id_cannot_be_claimed_twice():
    profiles = settings_with([{"label": "Erster", "ha_user_id": ANNA}, {"label": "Zweiter", "ha_user": "anna"}]).profiles
    registry = Registry(profiles)
    assert "anderen Profil" in registry.apply_ha_users(USERS)[0]
    assert registry.by_ha_user_id(ANNA).label == "Erster"


def test_explicit_id_beats_name():
    registry = Registry(settings_with([{"label": "A", "ha_user_id": BEN, "ha_user": "anna"}]).profiles)
    assert registry.pending() == [] and registry.by_ha_user_id(BEN).label == "A" and registry.by_ha_user_id(ANNA) is None


def test_resolved_user_can_open_the_app(store, backend):
    s = settings_with([{"label": "Admin", "ha_user_id": DORA}, {"label": "Anna", "ha_user": "anna"}])
    registry = Registry(s.profiles)
    api = TestClient(build_ingress_app(s, store, backend, registry=registry))
    assert api.get("/api/me", headers=as_user(ANNA)).status_code == 403
    registry.apply_ha_users(USERS)
    me = api.get("/api/me", headers=as_user(ANNA)).json()
    assert me["label"] == "Anna" and "admin" not in me
    store.sync_profiles(p.id for p in s.profiles)


class FakeHa(HaApi):
    def __init__(self, answers):
        super().__init__("t", "ws://x")
        self.answers = list(answers)

    async def users(self):
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def test_resolver_retries_until_home_assistant_answers(monkeypatch):
    import app.main as main

    monkeypatch.setattr(main, "RESOLVE_RETRY_SECONDS", 0)
    monkeypatch.setattr(main, "RESOLVE_IDLE_SECONDS", 0)
    registry = Registry(settings_with([{"label": "Anna", "ha_user": "anna"}, {"label": "Neu", "ha_user": "neu"}]).profiles)
    later = USERS + [{"id": "d" * 32, "name": "Neu", "username": "neu", "person": ""}]
    ha = FakeHa([HaApiError("offline"), USERS, later])
    asyncio.run(asyncio.wait_for(_resolve_loop(registry, ha), 5))
    assert registry.by_ha_user_id(ANNA).label == "Anna" and registry.by_ha_user_id("d" * 32).label == "Neu"
    assert registry.pending() == []


def test_no_user_management_in_the_app(store, backend):
    s = settings_with([{"label": "Admin", "ha_user_id": DORA}])
    api = TestClient(build_ingress_app(s, store, backend))
    for method, url in (("get", "/api/admin/users"), ("get", "/api/admin/ha-users"), ("post", "/api/admin/users")):
        assert getattr(api, method)(url, headers=as_user(DORA, write=True)).status_code in (404, 405)
    me = api.get("/api/me", headers=as_user(DORA)).json()
    assert "admin" not in me
    for name in ("index.html", "app.js", "style.css"):
        text = (__import__("pathlib").Path(__file__).parent.parent / "app" / "static" / name).read_text()
        assert "Benutzer verwalten" not in text and "api/admin" not in text


def test_denied_page_shows_the_users_own_credentials_in_ha(store, backend):
    s = settings_with([{"label": "Admin", "ha_user_id": DORA}])
    api = TestClient(build_ingress_app(s, store, backend))
    page = api.get("/", headers={"X-Remote-User-Id": "e" * 32, "X-Remote-User-Name": "erika"})
    assert page.status_code == 403 and "e" * 32 in page.text and "<b>erika</b>" in page.text and "ha_user" in page.text
    odd = api.get("/", headers={"X-Remote-User-Id": "e" * 32, "X-Remote-User-Name": "<script>x</script>"})
    assert "<script>" not in odd.text
    bad = api.get("/", headers={"X-Remote-User-Id": "<script>alert(1)</script>"})
    assert bad.status_code == 403 and "<script>" not in bad.text
