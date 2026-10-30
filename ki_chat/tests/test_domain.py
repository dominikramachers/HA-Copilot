"""Domain-Zugang: Anmeldung über Entra (gegen einen simulierten Identitätsanbieter)."""
import asyncio
import copy
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.config import ConfigError, parse_settings
from app.main import _pump, build_public_app
from app.oidc import EntraClient

from conftest import ADM01, RAW, WRITE, FakeBackend, as_user

TENANT = "11111111-2222-3333-4444-555555555555"
CLIENT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
BASE = "https://ai.test"
OID_DORA = "0d0d0d0d-0000-0000-0000-000000000001"
OID_ADM01 = "0a0a0a0a-0000-0000-0000-000000000002"
OID_OTHER = "0f0f0f0f-0000-0000-0000-000000000003"
WRITE_PUBLIC = {**WRITE, "Origin": BASE}


def _key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeIdp:
    """Simuliert Discovery, Schlüsselliste und Token-Endpunkt von Entra."""

    def __init__(self):
        self.key = _key()
        self.claims: dict = {}
        self.sign_key = self.key
        self.token_status = 200
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        jwk.update(kid="k1", use="sig", alg="RS256")
        self.jwks = {"keys": [jwk]}
        self.issuer = f"https://idp.test/{TENANT}/v2.0"

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json={
                "issuer": self.issuer,
                "authorization_endpoint": f"https://idp.test/{TENANT}/oauth2/v2.0/authorize",
                "token_endpoint": f"https://idp.test/{TENANT}/oauth2/v2.0/token",
                "jwks_uri": "https://idp.test/keys",
            })
        if path == "/keys":
            return httpx.Response(200, json=self.jwks)
        if path.endswith("/token"):
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_grant"})
            form = parse_qs(request.content.decode())
            assert form["client_secret"] == ["geheim"] and form["code_verifier"]
            token = jwt.encode(self.claims, self.sign_key, algorithm="RS256", headers={"kid": "k1"})
            return httpx.Response(200, json={"id_token": token})
        return httpx.Response(404)

    def claims_for(self, nonce_value, **overrides):
        now = int(time.time())
        claims = {
            "iss": self.issuer, "aud": CLIENT, "tid": TENANT, "oid": OID_DORA,
            "preferred_username": "dora@example.org", "name": "Dora",
            "nonce": nonce_value, "iat": now, "nbf": now, "exp": now + 3600,
        }
        claims.update(overrides)
        return claims


@pytest.fixture()
def idp():
    return FakeIdp()


@pytest.fixture()
def settings():
    raw = copy.deepcopy(RAW)
    raw.update(
        public_enabled=True, public_base_url=BASE, entra_tenant_id=TENANT,
        entra_client_id=CLIENT, entra_client_secret="geheim",
    )
    return parse_settings(raw, frozenset({"testclient"}))


@pytest.fixture()
def make_client(settings, store, backend, idp):
    def factory(trusted=False):
        http = httpx.AsyncClient(transport=httpx.MockTransport(idp.handler))
        entra = EntraClient(TENANT, CLIENT, "geheim", f"{BASE}/auth/callback", http, "https://idp.test")
        return TestClient(
            build_public_app(settings, store, backend, entra), base_url=BASE, follow_redirects=False
        )
    return factory


@pytest.fixture()
def pub(make_client):
    return make_client()


def start(client, email="dora@example.org", headers=WRITE_PUBLIC):
    response = client.post("/auth/start", json={"email": email}, headers=headers)
    if response.status_code != 200:
        return response, None, None
    query = parse_qs(urlparse(response.json()["redirect"]).query)
    return response, query["state"][0], query["nonce"][0]


def login(client, idp, email="dora@example.org", **overrides):
    """Kompletter Ablauf. Gibt die Antwort des Rückkehr-Aufrufs zurück."""
    response, state, nonce = start(client, email)
    assert response.status_code == 200, response.text
    idp.claims = idp.claims_for(nonce, **overrides)
    return client.get("/auth/callback", params={"code": "abc", "state": state})


def location(response):
    return response.headers["location"]


# ---------------------------------------------------------------- Konfiguration

def _raw(**extra):
    raw = copy.deepcopy(RAW)
    raw.update(public_enabled=True, public_base_url=BASE, entra_tenant_id=TENANT,
               entra_client_id=CLIENT, entra_client_secret="geheim")
    raw.update(extra)
    return raw


def test_domain_config_is_valid():
    settings = parse_settings(_raw())
    assert settings.public_base_url == BASE and settings.session_days == 30


@pytest.mark.parametrize("override", [
    {"public_base_url": "http://ai.test"},
    {"public_base_url": "https://ai.test/pfad"},
    {"public_base_url": ""},
    {"entra_tenant_id": "nicht-eine-guid"},
    {"entra_client_id": ""},
    {"entra_client_secret": ""},
    {"session_days": 0},
    {"session_days": 400},
    {"public_trusted_proxies": "172.30.33.1"},
])
def test_domain_config_rejects_bad_values(override):
    with pytest.raises(ConfigError):
        parse_settings(_raw(**override))


def test_domain_options_are_not_required_when_disabled():
    assert parse_settings(RAW).public_enabled is False


# ----------------------------------------------------------- Anmeldeablauf

def test_unauthenticated_visitors_get_login_not_data(pub):
    assert pub.get("/healthz").json() == {"status": "ok"}
    assert pub.get("/").status_code == 303 and location(pub.get("/")) == "/login"
    assert location(pub.get("/new")) == "/login"
    assert pub.get("/api/me").status_code == 401
    assert pub.get("/api/chats").status_code == 401
    page = pub.get("/login")
    assert page.status_code == 200 and "E-Mail-Adresse" in page.text
    assert pub.get("/static/theme.css").status_code == 200
    assert pub.get("/favicon.ico").status_code == 200 and 'rel="icon"' in page.text and "branding/logo-full" in page.text
    assert pub.get("/nichts").status_code == 404


def test_ingress_headers_are_ignored_on_the_domain(pub):
    assert pub.get("/api/me", headers=as_user(ADM01)).status_code == 401
    assert pub.post("/api/chats", json={}, headers={**as_user(ADM01, True), "Origin": BASE}).status_code == 401


def test_full_login_creates_session_for_the_right_profile(pub, idp, store):
    response = login(pub, idp)
    assert response.status_code == 303 and location(response) == "/new"
    assert "__Host-ki_session" in response.headers["set-cookie"]
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie and "path=/" in cookie
    me = pub.get("/api/me").json()
    assert me["id"] == "dora" and me["mode"] == "domain" and me["can_logout"] is True
    page = pub.get("/new")
    assert page.status_code == 200 and "KI Chat" in page.text and "__V__" not in page.text
    assert 'data-embed="web"' in page.text
    assert pub.get("/").status_code == 200
    assert location(pub.get("/login")) == "/new"
    assert store.profile_id_for_oid(OID_DORA) == "dora"


def test_two_people_stay_separated_on_the_domain(make_client, idp):
    one, two = make_client(), make_client()
    assert login(one, idp).status_code == 303
    assert login(two, idp, email="adm01@example.org", oid=OID_ADM01,
                 preferred_username="adm01@example.org").status_code == 303
    chat = one.post("/api/chats", json={"title": "Privat"}, headers=WRITE_PUBLIC).json()
    assert [c["title"] for c in one.get("/api/chats").json()] == ["Privat"]
    assert two.get("/api/chats").json() == []
    assert two.get(f"/api/chats/{chat['id']}/messages").status_code == 404
    assert two.delete(f"/api/chats/{chat['id']}", headers=WRITE_PUBLIC).status_code == 404
    assert two.post(f"/api/chats/{chat['id']}/send", json={"content": "hi"}, headers=WRITE_PUBLIC).status_code == 404


def test_domain_and_ingress_share_the_same_chats(settings, store, backend, make_client, idp):
    from app.main import build_ingress_app
    ingress = TestClient(build_ingress_app(settings, store, backend))
    pub = make_client()
    login(pub, idp)
    pub.post("/api/chats", json={"title": "Von der Domain"}, headers=WRITE_PUBLIC)
    from conftest import DORA
    titles = [c["title"] for c in ingress.get("/api/chats", headers=as_user(DORA)).json()]
    assert titles == ["Von der Domain"]
    assert ingress.get("/api/chats", headers=as_user(ADM01)).json() == []


def test_chat_streaming_works_with_a_session(pub, idp, backend):
    login(pub, idp)
    chat = pub.post("/api/chats", json={}, headers=WRITE_PUBLIC).json()
    response = pub.post(f"/api/chats/{chat['id']}/send", json={"content": "Hallo"}, headers=WRITE_PUBLIC)
    assert response.status_code == 200 and '"type": "done"' in response.text
    assert [m["role"] for m in pub.get(f"/api/chats/{chat['id']}/messages").json()] == ["user", "assistant"]


def test_logout_ends_the_session(pub, idp):
    login(pub, idp)
    assert pub.post("/auth/logout").status_code == 403  # ohne Schutz-Header
    assert pub.get("/api/me").status_code == 200
    assert pub.post("/auth/logout", headers=WRITE_PUBLIC).status_code == 204
    stale = pub.cookies.get("__Host-ki_session")
    assert not stale
    assert pub.get("/api/me").status_code == 401


def test_logged_out_token_stays_dead(pub, idp, store):
    login(pub, idp)
    token = pub.cookies.get("__Host-ki_session")
    pub.post("/auth/logout", headers=WRITE_PUBLIC)
    pub.cookies.set("__Host-ki_session", token, domain="ai.test")
    assert pub.get("/api/me").status_code == 401


# --------------------------------------------------------- Start und Schutz

def test_start_needs_header_and_matching_origin(pub):
    assert pub.post("/auth/start", json={"email": "dora@example.org"}).status_code == 403
    assert pub.post("/auth/start", json={"email": "dora@example.org"},
                    headers={"X-Requested-With": "ki-chat"}).status_code == 403
    assert pub.post("/auth/start", json={"email": "dora@example.org"},
                    headers={**WRITE, "Origin": "https://evil.example"}).status_code == 403


def test_unknown_address_gets_no_redirect(pub):
    response, _, _ = start(pub, "fremd@example.com")
    assert response.status_code == 403 and "redirect" not in response.text


def test_start_is_case_insensitive_and_sets_login_hint(pub):
    response, _, _ = start(pub, "  DORA@Example.ORG ")
    assert response.status_code == 200
    url = response.json()["redirect"]
    assert url.startswith("https://idp.test/") and "code_challenge_method=S256" in url
    assert "login_hint=dora%40example.org" in url and f"client_id={CLIENT}" in url


def test_start_is_rate_limited(pub):
    codes = [pub.post("/auth/start", json={"email": "fremd@example.com"}, headers=WRITE_PUBLIC).status_code
             for _ in range(12)]
    assert codes[:10] == [403] * 10 and codes[10:] == [429, 429]


def test_writes_from_other_origins_are_rejected(pub, idp):
    login(pub, idp)
    assert pub.post("/api/chats", json={}, headers={**WRITE, "Origin": "https://evil.example"}).status_code == 403
    assert pub.post("/api/chats", json={}, headers=WRITE).status_code == 403
    assert pub.post("/api/chats", json={}, headers=WRITE_PUBLIC).status_code == 201


def test_domain_responses_carry_strict_headers(pub):
    headers = pub.get("/login").headers
    assert "frame-ancestors 'none'" in headers["content-security-policy"]
    assert headers["strict-transport-security"].startswith("max-age=")
    assert pub.get("/api/me").headers["cache-control"] == "no-store"


# --------------------------------------------------------------- Rückkehr

def test_callback_rejects_unknown_state(pub):
    response = pub.get("/auth/callback", params={"code": "abc", "state": "gibt-es-nicht"})
    assert location(response) == "/login?e=expired"
    assert pub.get("/auth/callback").headers["location"] == "/login?e=expired"


def test_state_is_single_use(pub, idp):
    _, state, nonce = start(pub)
    idp.claims = idp.claims_for(nonce)
    assert location(pub.get("/auth/callback", params={"code": "abc", "state": state})) == "/new"
    assert location(pub.get("/auth/callback", params={"code": "abc", "state": state})) == "/login?e=expired"


def test_state_is_bound_to_the_browser_that_started_it(make_client, idp):
    victim, attacker = make_client(), make_client()
    _, state, nonce = start(victim)
    idp.claims = idp.claims_for(nonce)
    # Ein Angreifer schiebt dem anderen Browser seinen Rückkehr-Link unter (kein Login-Cookie dort).
    response = attacker.get("/auth/callback", params={"code": "abc", "state": state})
    assert location(response) == "/login?e=expired"
    assert attacker.get("/api/me").status_code == 401


def test_provider_error_and_cancel(pub):
    _, state, _ = start(pub)
    response = pub.get("/auth/callback", params={"error": "access_denied", "state": state})
    assert location(response) == "/login?e=cancelled"
    _, state, _ = start(pub)
    assert location(pub.get("/auth/callback", params={"error": "server_error", "state": state})) == "/login?e=failed"


def test_rejected_code_exchange(pub, idp):
    _, state, nonce = start(pub)
    idp.token_status = 400
    assert location(pub.get("/auth/callback", params={"code": "x", "state": state})) == "/login?e=failed"
    assert pub.get("/api/me").status_code == 401


# ----------------------------------------------------- ID-Token-Prüfung

@pytest.mark.parametrize("overrides", [
    {"aud": "anderer-client"},
    {"iss": "https://idp.test/anderer-mandant/v2.0"},
    {"tid": "99999999-2222-3333-4444-555555555555"},
    {"exp": int(time.time()) - 600},
    {"nonce": "falsch"},
    {"oid": ""},
])
def test_invalid_id_tokens_never_create_a_session(pub, idp, overrides):
    response = login(pub, idp, **overrides)
    assert location(response) == "/login?e=failed"
    assert pub.get("/api/me").status_code == 401


def test_token_signed_with_foreign_key_is_rejected(pub, idp):
    idp.sign_key = _key()
    assert location(login(pub, idp)) == "/login?e=failed"
    assert pub.get("/api/me").status_code == 401


def test_unsigned_token_is_rejected(idp):
    from app.oidc import OidcError

    http = httpx.AsyncClient(transport=httpx.MockTransport(idp.handler))
    client = EntraClient(TENANT, CLIENT, "geheim", f"{BASE}/auth/callback", http, "https://idp.test")
    unsigned = jwt.encode(idp.claims_for("n"), None, algorithm="none")
    with pytest.raises(OidcError):
        asyncio.run(client._validate(unsigned, "n"))


# -------------------------------------------------------- Zuordnung (oid)

def test_foreign_account_without_matching_upn_is_denied(pub, idp, store):
    response = login(pub, idp, oid=OID_OTHER, preferred_username="sam@example.org")
    assert location(response) == "/login?e=denied"
    assert pub.get("/api/me").status_code == 401
    assert store.profile_id_for_oid(OID_OTHER) is None


def test_oid_is_bound_on_first_login_and_then_authoritative(pub, idp, store):
    assert location(login(pub, idp)) == "/new"
    assert store.profile_id_for_oid(OID_DORA) == "dora"
    # Gleiche oid darf sich mit anderem Anmeldenamen melden (UPN umbenannt): bleibt Dora.
    pub.post("/auth/logout", headers=WRITE_PUBLIC)
    assert location(login(pub, idp, preferred_username="neu@example.org")) == "/new"
    assert pub.get("/api/me").json()["id"] == "dora"


def test_a_different_oid_cannot_take_over_a_bound_profile(pub, idp):
    assert location(login(pub, idp)) == "/new"
    pub.post("/auth/logout", headers=WRITE_PUBLIC)
    # Anderes Konto, das jetzt dieselbe UPN trägt (z. B. neu angelegt): abgewiesen.
    assert location(login(pub, idp, oid=OID_OTHER)) == "/login?e=denied"
    assert pub.get("/api/me").status_code == 401


def test_an_oid_bound_elsewhere_cannot_claim_another_profile(pub, idp):
    assert location(login(pub, idp)) == "/new"  # OID_DORA → dora
    pub.post("/auth/logout", headers=WRITE_PUBLIC)
    response = login(pub, idp, email="adm01@example.org", oid=OID_DORA,
                     preferred_username="adm01@example.org")
    # Die oid gehört schon Dora; der Name adm01 spielt keine Rolle mehr.
    assert location(response) == "/new"
    assert pub.get("/api/me").json()["id"] == "dora"


def test_email_claim_is_not_used_for_matching(pub, idp):
    response = login(pub, idp, oid=OID_OTHER, preferred_username="sam@example.org",
                     email="dora@example.org")
    assert location(response) == "/login?e=denied"


def test_guest_style_names_are_not_matched(pub, idp):
    response = login(pub, idp, oid=OID_OTHER,
                     preferred_username="dora_example.org#EXT#@x.onmicrosoft.com")
    assert location(response) == "/login?e=denied"


# ------------------------------------------------------- Sitzungen (DB)

def test_sessions_expire_and_store_only_hashes(store):
    token = store.create_session("dora", 30)
    row = store._conn.execute("SELECT token_hash FROM sessions").fetchone()
    assert token not in row["token_hash"] and len(row["token_hash"]) == 64
    assert store.session_profile(token, 30) == "dora"
    assert store.session_profile("falsch", 30) is None and store.session_profile("", 30) is None
    store._conn.execute("UPDATE sessions SET expires_at = '2000-01-01T00:00:00+00:00'")
    assert store.session_profile(token, 30) is None
    assert store._conn.execute("SELECT COUNT(*) c FROM sessions").fetchone()["c"] == 0


def test_sessions_slide_but_have_a_hard_limit(store):
    token = store.create_session("dora", 1)
    assert store.session_profile(token, 30) == "dora"
    expires = store._conn.execute("SELECT expires_at FROM sessions").fetchone()["expires_at"]
    assert expires > "2026"  # verlängert
    store._conn.execute("UPDATE sessions SET created_at = '2000-01-01T00:00:00+00:00'")
    assert store.session_profile(token, 30) is None  # absolute Höchstdauer


def test_removed_profile_loses_access_immediately(store, backend, make_client, idp):
    pub = make_client()
    login(pub, idp)
    assert pub.get("/api/me").status_code == 200
    raw = _raw()
    raw["profiles"] = [p for p in raw["profiles"] if p["id"] == "adm01"]
    reduced = parse_settings(raw, frozenset({"testclient"}))
    http = httpx.AsyncClient(transport=httpx.MockTransport(idp.handler))
    entra = EntraClient(TENANT, CLIENT, "geheim", f"{BASE}/auth/callback", http, "https://idp.test")
    other = TestClient(build_public_app(reduced, store, backend, entra), base_url=BASE)
    other.cookies.set("__Host-ki_session", pub.cookies.get("__Host-ki_session"), domain="ai.test")
    assert other.get("/api/me").status_code == 401


# ------------------------------------------------------------ Keepalive

def test_pump_sends_pings_while_the_source_is_silent():
    async def slow():
        await asyncio.sleep(0.25)
        yield "a"
        yield "b"

    async def run():
        return [item async for item in _pump(slow, 0.05)]

    items = asyncio.run(run())
    assert items.count(None) >= 2 and [i for i in items if i] == ["a", "b"]


def test_pump_passes_errors_and_cleans_up():
    from app.backend import BackendError

    async def broken():
        yield "a"
        raise BackendError("kaputt")

    async def run():
        got = []
        with pytest.raises(BackendError):
            async for item in _pump(broken, 0.05):
                got.append(item)
        return got

    assert asyncio.run(run()) == ["a"]


def test_pump_cancels_source_when_closed_early():
    state = {"closed": False}

    async def endless():
        try:
            while True:
                await asyncio.sleep(0.01)
                yield "x"
        finally:
            state["closed"] = True

    async def run():
        gen = _pump(endless, 1)
        assert await gen.__anext__() == "x"
        await gen.aclose()

    asyncio.run(run())
    assert state["closed"]


def test_domain_has_no_admin_interface(pub, idp):
    assert login(pub, idp).status_code in (302, 303)
    assert pub.get("/api/admin/users").status_code == 404
    assert "admin" not in pub.get("/api/me").json()
