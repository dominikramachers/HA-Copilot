"""Optionale Zugänge: alle Home-Assistant-Benutzer zulassen und Anmeldung mit Home Assistant auf der Domain.

Beides ist standardmäßig aus; die bisherige Konfiguration (eingetragene Benutzer, Microsoft Entra) bleibt unverändert.
"""
import copy
import pathlib
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

import app.ha_login as ha_login_module
from app.config import ConfigError, parse_settings
from app.ha_client import HaApiError
from app.ha_login import HaLoginClient
from app.identity import Registry
from app.main import build_ingress_app, build_public_app

from conftest import DORA, RAW, WRITE, as_user

BASE = "https://chat.example.org"
HA = "https://ha.example.org"
ERIKA = "e" * 32
FRIDA = "f" * 31 + "1"
KIND = "c" * 32
ROOT = pathlib.Path(__file__).parent.parent


def settings_with(**extra):
    raw = copy.deepcopy(RAW)
    raw.update(extra)
    return parse_settings(raw, frozenset({"testclient"}))


# ------------------------------------------------------------------ Konfiguration


def test_defaults_change_nothing_for_existing_installs():
    s = settings_with()
    assert (s.all_ha_users, s.ha_url, s.ha_users_excluded) == (False, "", frozenset())
    assert not s.ha_login_enabled and [p.id for p in s.profiles] == ["adm01", "dora"]


def test_without_users_the_app_needs_the_all_users_switch():
    with pytest.raises(ConfigError):
        settings_with(profiles=[])
    with pytest.raises(ConfigError):
        settings_with(profiles=[{"label": "", "ha_user": ""}])
    s = settings_with(profiles=[], all_ha_users=True)
    assert s.profiles == () and s.all_ha_users


def test_exclusion_list_is_parsed_from_text():
    s = settings_with(all_ha_users=True, ha_users_excluded=" Kind1, GAST ;kind2\nXyz ")
    assert s.ha_users_excluded == frozenset({"kind1", "gast", "kind2", "xyz"})
    assert settings_with(ha_users_excluded="").ha_users_excluded == frozenset()


def test_ha_url_is_validated_and_normalised():
    s = settings_with(ha_url=HA + "/")
    assert s.ha_url == HA and s.ha_login_enabled
    for bad in ("http://ha.example.org", "ha.example.org", HA + "/pfad", "javascript:alert(1)"):
        with pytest.raises(ConfigError):
            settings_with(ha_url=bad)


def _domain(**extra):
    return settings_with(public_enabled=True, public_base_url=BASE, **extra)


ENTRA = dict(
    entra_tenant_id="0f0f0f0f-0000-0000-0000-000000000001",
    entra_client_id="0f0f0f0f-0000-0000-0000-000000000002",
    entra_client_secret="geheim",
)


def test_domain_needs_entra_unless_home_assistant_login_is_set_up():
    with pytest.raises(ConfigError):
        _domain()
    only_ha = _domain(ha_url=HA)
    assert only_ha.ha_login_enabled and not only_ha.entra_enabled
    both = _domain(ha_url=HA, **ENTRA)
    assert both.ha_login_enabled and both.entra_enabled
    assert _domain(**ENTRA).entra_enabled and not _domain(**ENTRA).ha_login_enabled
    with pytest.raises(ConfigError):  # halb ausgefüllte Entra-Angaben bleiben ein Fehler
        _domain(ha_url=HA, entra_tenant_id=ENTRA["entra_tenant_id"])


def test_schema_and_translations_describe_the_same_options():
    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    for lang in ("de", "en"):
        tr = yaml.safe_load((ROOT / "translations" / f"{lang}.yaml").read_text(encoding="utf-8"))["configuration"]
        assert set(tr) == set(config["schema"]), lang
        assert set(tr["profiles"]["fields"]) == set(config["schema"]["profiles"][0]), lang


def test_new_options_are_optional_so_old_configurations_stay_valid():
    schema = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))["schema"]
    for key in ("all_ha_users", "ha_users_excluded", "ha_url"):
        assert schema[key].endswith("?"), key
    assert all(str(v).endswith("?") for v in schema["profiles"][0].values())


# ------------------------------------------------------------------ Registry


def auto(store=None, **extra):
    s = settings_with(all_ha_users=True, **extra)
    return Registry.from_settings(s, store)


def test_switch_off_keeps_unknown_users_out():
    registry = Registry.from_settings(settings_with(), None)
    assert registry.admit_ha(ERIKA, ("erika",), "Erika") is None
    assert registry.admit_ha(DORA, (), "").id == "dora"


def test_switch_on_creates_a_stable_profile_per_ha_user(store):
    registry = auto(store)
    erika = registry.admit_ha(ERIKA.upper(), ("erika",), "Erika Muster")
    frida = registry.admit_ha(FRIDA, ("frida",), "Frida")
    assert erika.id == "ha-" + ERIKA[:12] and erika.label == "Erika Muster" and erika.ha_user_id == ERIKA
    assert frida.id != erika.id
    assert registry.admit_ha(ERIKA, (), "Erika Muster") == erika
    # eingetragene Benutzer behalten ihr Profil
    assert registry.admit_ha(DORA, ("dora",), "Anderer Name").id == "dora"


def test_exclusions_match_id_user_name_and_display_name():
    registry = auto(ha_users_excluded=f"Kind1, {FRIDA}, Gast Konto")
    assert registry.admit_ha(KIND, ("kind1",), "Anna") is None
    assert registry.admit_ha(FRIDA, ("frida",), "Frida") is None
    assert registry.admit_ha(ERIKA, ("erika",), "gast konto") is None
    assert registry.admit_ha(ERIKA, ("erika",), "Erika") is not None


def test_empty_or_odd_names_never_break_the_profile(store):
    registry = auto(store)
    assert registry.admit_ha("", ("x",), "x") is None
    odd = registry.admit_ha(ERIKA, ("<b>",), "<script>x</script>")
    assert "<" not in odd.label and odd.label
    assert registry.admit_ha(FRIDA, (), "").label == "Benutzer"


def test_auto_profiles_survive_a_restart_but_not_a_new_exclusion(store):
    first = auto(store)
    profile = first.admit_ha(ERIKA, ("erika",), "Erika")
    restarted = auto(store)
    assert restarted.by_id(profile.id).label == "Erika"
    assert auto(store, ha_users_excluded="erika" ).by_id(profile.id).ha_user_id == ERIKA  # Name ist der Datenbank unbekannt …
    assert auto(store, ha_users_excluded=ERIKA).by_id(profile.id) is None  # … die ID aber nicht
    assert Registry.from_settings(settings_with(), store).by_id(profile.id) is None  # Schalter aus: kein Zugang mehr
    assert restarted.by_id("ha-unbekannt00") is None


# ------------------------------------------------------------------ Ingress


def test_ingress_admits_every_ha_user_when_switched_on(store, backend):
    api = TestClient(build_ingress_app(settings_with(all_ha_users=True, ha_users_excluded="kind1"), store, backend))
    headers = {"X-Remote-User-Id": ERIKA, "X-Remote-User-Name": "erika", "X-Remote-User-Display-Name": "Erika"}
    me = api.get("/api/me", headers=headers).json()
    assert me["label"] == "Erika"
    created = api.post("/api/chats", headers={**headers, **WRITE}).json()
    # getrennte Chats: ein anderer HA-Benutzer sieht sie nicht
    other = {"X-Remote-User-Id": FRIDA, "X-Remote-User-Name": "frida", "X-Remote-User-Display-Name": "Frida"}
    assert api.get("/api/chats", headers=other).json() == [] and api.get("/api/chats", headers=headers).json()
    assert created
    # ausgeschlossen
    blocked = api.get("/api/me", headers={"X-Remote-User-Id": KIND, "X-Remote-User-Name": "kind1"})
    assert blocked.status_code == 403


def test_ingress_stays_closed_to_strangers_by_default(store, backend):
    api = TestClient(build_ingress_app(settings_with(), store, backend))
    assert api.get("/api/me", headers=as_user(ERIKA)).status_code == 403
    assert api.get("/api/me", headers=as_user(DORA)).status_code == 200


# ------------------------------------------------------------------ Anmeldung mit Home Assistant


class FakeHaServer:
    """Token-Endpunkt, Widerruf und ``auth/current_user`` von Home Assistant."""

    def __init__(self):
        self.user = {"id": ERIKA, "name": "Erika"}
        self.token_status = 200
        self.revoked = []
        self.token_form = {}
        self.ws_error = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        if request.url.path == "/auth/token":
            self.token_form = form
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "zugriff", "refresh_token": "erneuern", "token_type": "Bearer"})
        if request.url.path == "/auth/revoke":
            self.revoked.append(form)
            return httpx.Response(200)
        return httpx.Response(404)


@pytest.fixture()
def hass(monkeypatch):
    server = FakeHaServer()

    class FakeWs:
        def __init__(self, token, url):
            assert token == "zugriff" and url == "wss://ha.example.org/api/websocket"

        async def call(self, command):
            assert command == {"type": "auth/current_user"}
            if server.ws_error:
                raise HaApiError(server.ws_error)
            return server.user

    monkeypatch.setattr(ha_login_module, "HaApi", FakeWs)
    return server


def make_domain(store, backend, hass, **extra):
    settings = _domain(**extra)
    http = httpx.AsyncClient(transport=httpx.MockTransport(hass.handler))
    login = HaLoginClient(HA, BASE + "/", BASE + "/auth/ha-callback", http) if settings.ha_login_enabled else None
    entra = None
    if settings.entra_enabled:
        from app.oidc import EntraClient

        entra = EntraClient(settings.entra_tenant_id, settings.entra_client_id, "geheim", BASE + "/auth/callback", http, "https://idp.test")
    return TestClient(build_public_app(settings, store, backend, entra, ha_login=login), base_url=BASE, follow_redirects=False)


def ha_start(client):
    response = client.get("/auth/ha-start")
    assert response.status_code == 303
    target = urlparse(response.headers["location"])
    assert f"{target.scheme}://{target.netloc}{target.path}" == HA + "/auth/authorize"
    return parse_qs(target.query)["state"][0], parse_qs(target.query)


def test_home_assistant_login_signs_in_a_listed_user(store, backend, hass):
    hass.user = {"id": DORA.upper(), "name": "Dora"}
    client = make_domain(store, backend, hass, ha_url=HA)
    state, query = ha_start(client)
    assert query["client_id"] == [BASE + "/"] and query["redirect_uri"] == [BASE + "/auth/ha-callback"]
    done = client.get("/auth/ha-callback", params={"code": "abc", "state": state})
    assert done.status_code == 303 and done.headers["location"] == "/new"
    assert hass.token_form["code"] == ["abc"] and hass.token_form["grant_type"] == ["authorization_code"]
    assert hass.revoked and hass.revoked[0]["token"] == ["erneuern"]  # Token wird sofort widerrufen
    assert client.get("/api/me").json()["id"] == "dora"


def test_home_assistant_login_follows_the_all_users_switch(store, backend, hass):
    closed = make_domain(store, backend, hass, ha_url=HA)
    state, _ = ha_start(closed)
    denied = closed.get("/auth/ha-callback", params={"code": "abc", "state": state})
    assert denied.headers["location"] == "/login?e=denied" and closed.get("/api/me").status_code == 401

    opened = make_domain(store, backend, hass, ha_url=HA, all_ha_users=True)
    state, _ = ha_start(opened)
    assert opened.get("/auth/ha-callback", params={"code": "abc", "state": state}).headers["location"] == "/new"
    assert opened.get("/api/me").json()["label"] == "Erika"

    barred = make_domain(store, backend, hass, ha_url=HA, all_ha_users=True, ha_users_excluded="Erika")
    state, _ = ha_start(barred)
    assert barred.get("/auth/ha-callback", params={"code": "abc", "state": state}).headers["location"] == "/login?e=denied"


def test_callback_checks_state_and_browser(store, backend, hass):
    client = make_domain(store, backend, hass, ha_url=HA, all_ha_users=True)
    state, _ = ha_start(client)
    assert client.get("/auth/ha-callback", params={"code": "abc", "state": "falsch"}).headers["location"] == "/login?e=expired"
    other = make_domain(store, backend, hass, ha_url=HA, all_ha_users=True)  # anderer Browser, gleicher state
    assert other.get("/auth/ha-callback", params={"code": "abc", "state": state}).headers["location"] == "/login?e=expired"
    assert client.get("/auth/ha-callback", params={"code": "abc", "state": state}).headers["location"] == "/login?e=expired"  # nur einmal gültig
    assert client.get("/api/me").status_code == 401


@pytest.mark.parametrize("problem", ["token", "websocket"])
def test_failures_end_on_the_login_page_without_a_session(store, backend, hass, problem):
    client = make_domain(store, backend, hass, ha_url=HA, all_ha_users=True)
    state, _ = ha_start(client)
    if problem == "token":
        hass.token_status = 400
    else:
        hass.ws_error = "auth/current_user: unknown_command"
    assert client.get("/auth/ha-callback", params={"code": "abc", "state": state}).headers["location"] == "/login?e=failed"
    assert client.get("/api/me").status_code == 401
    if problem == "websocket":
        assert hass.revoked  # auch bei Fehlern wird das Token widerrufen


def test_cancel_at_home_assistant(store, backend, hass):
    client = make_domain(store, backend, hass, ha_url=HA)
    state, _ = ha_start(client)
    assert client.get("/auth/ha-callback", params={"error": "access_denied", "state": state}).headers["location"] == "/login?e=cancelled"


def test_login_page_shows_only_what_is_set_up(store, backend, hass):
    both = make_domain(store, backend, hass, ha_url=HA, **ENTRA).get("/login").text
    assert 'data-entra="true"' in both and 'data-ha="true"' in both and "auth/ha-start" in both
    only_entra = make_domain(store, backend, hass, **ENTRA)
    assert 'data-ha="false"' in only_entra.get("/login").text and 'data-entra="true"' in only_entra.get("/login").text
    assert only_entra.get("/auth/ha-start").headers["location"] == "/login?e=failed"  # ohne ha_url: Anmeldung nicht möglich
    only_ha = make_domain(store, backend, hass, ha_url=HA)
    page = only_ha.get("/login").text
    assert 'data-entra="false"' in page and 'data-ha="true"' in page
    assert only_ha.post("/auth/start", json={"email": "dora@example.org"}, headers={**WRITE, "Origin": BASE}).status_code == 404


def test_entra_login_still_works_next_to_home_assistant(store, backend, hass):
    client = make_domain(store, backend, hass, ha_url=HA, **ENTRA)
    unknown = client.post("/auth/start", json={"email": "fremd@example.org"}, headers={**WRITE, "Origin": BASE})
    assert unknown.status_code == 403  # Entra-Zuordnung wie bisher
