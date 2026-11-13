"""App-Zugang: Anmeldung der mobilen App über den Systembrowser (PKCE, Einmal-Code, Gerätetoken, Einmal-Ticket)."""
import copy
import secrets
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from app import appaccess
from app.config import ConfigError, parse_settings
from app.main import build_public_app
from app.oidc import EntraClient

from conftest import RAW
from test_domain import BASE, CLIENT, TENANT, WRITE_PUBLIC, FakeIdp, start

APP_HEADERS = {"Cache-Control": "no-store"}


def _raw(**extra):
    raw = copy.deepcopy(RAW)
    raw.update(public_enabled=True, public_base_url=BASE, entra_tenant_id=TENANT, entra_client_id=CLIENT,
               entra_client_secret="geheim", app_access=True)
    raw.update(extra)
    return raw


@pytest.fixture()
def idp():
    return FakeIdp()


def make(store, backend, idp, **extra):
    settings = parse_settings(_raw(**extra), frozenset({"testclient"}))
    http = httpx.AsyncClient(transport=httpx.MockTransport(idp.handler))
    entra = EntraClient(TENANT, CLIENT, "geheim", f"{BASE}/auth/callback", http, "https://idp.test")
    return TestClient(build_public_app(settings, store, backend, entra), base_url=BASE, follow_redirects=False)


@pytest.fixture()
def pub(store, backend, idp):
    return make(store, backend, idp)


def pkce():
    verifier = secrets.token_urlsafe(48)
    return verifier, appaccess.s256(verifier)


def app_login(client, idp, email="dora@example.org", verifier_challenge=None, state=None, **params):
    """Kompletter Anmeldeweg der App bis zur Rückleitung. Gibt (Antwort der Rückleitung, verifier, state) zurück."""
    verifier, challenge = verifier_challenge or pkce()
    state = state or secrets.token_urlsafe(16)
    query = {"challenge": challenge, "state": state, "device": "Doras iPhone", "platform": "ios", "app_version": "1.0.0", **params}
    first = client.get("/app/v1/login", params=query)
    assert first.status_code == 303 and first.headers["location"] == "/login", first.text
    response, entra_state, nonce = start(client, email)
    assert response.status_code == 200, response.text
    idp.claims = idp.claims_for(nonce)
    done = client.get("/auth/callback", params={"code": "abc", "state": entra_state})
    return done, verifier, state


def redeem(client, done, verifier):
    target = urlparse(done.headers["location"])
    code = parse_qs(target.query)["code"][0]
    return client.post("/app/v1/token", json={"code": code, "verifier": verifier})


def enroll(client, idp):
    done, verifier, _ = app_login(client, idp)
    response = redeem(client, done, verifier)
    assert response.status_code == 200, response.text
    return response.json()


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------- Bausteine

def test_s256_matches_the_rfc7636_example():
    assert appaccess.s256("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


@pytest.mark.parametrize("raw,expected", [
    ("  Doras\n iPhone ", "Doras iPhone"),
    ("<script>x</script>", "scriptx/script"),
    ("", "iPhone"),
    ("\x00\x1f", "iPhone"),
    ("x" * 100, "x" * 40),
])
def test_device_names_are_cleaned(raw, expected):
    assert appaccess.clean_name(raw, "ios") == expected


def test_pending_entries_expire_and_are_single_use():
    now = [0.0]
    pending = appaccess.Pending(10, lambda: now[0])
    assert pending.add("k", "v")
    assert pending.peek("k") == "v"
    assert pending.take("k") == "v"
    assert pending.take("k") is None  # nur einmal
    pending.add("k2", "v")
    now[0] = 11
    assert pending.take("k2") is None  # abgelaufen
    assert pending.take("") is None


def test_pending_is_bounded():
    pending = appaccess.Pending(1000)
    for i in range(appaccess.MAX_PENDING):
        assert pending.add(f"k{i}", i)
    assert not pending.add("zu-viel", 1)


# ---------------------------------------------------------------- Konfiguration

def test_app_access_needs_the_domain_access():
    off = parse_settings({**RAW, "app_access": True}, frozenset({"testclient"}))  # ohne Domain-Zugang
    assert off.public_enabled is False and off.app_access is False
    assert parse_settings(_raw(), frozenset({"testclient"})).app_access is True
    assert parse_settings(_raw(app_access=False), frozenset({"testclient"})).app_access is False


@pytest.mark.parametrize("override", [{"device_days": 0}, {"device_days": 181}, {"app_access": "ja"}])
def test_app_access_rejects_bad_values(override):
    with pytest.raises(ConfigError):
        parse_settings(_raw(**override), frozenset({"testclient"}))


def test_routes_do_not_exist_when_switched_off(store, backend, idp):
    client = make(store, backend, idp, app_access=False)
    assert client.get("/app/v1/discovery").status_code == 404
    assert client.get("/app/v1/login", params={"challenge": "x"}).status_code == 404
    assert client.post("/app/v1/token", json={}).status_code in (404, 405)
    assert client.get("/api/me").status_code == 401


# ---------------------------------------------------------------- Entdeckung

def test_discovery_describes_the_server(pub):
    first = pub.get("/app/v1/discovery")
    assert first.status_code == 200 and first.headers["cache-control"] == "no-store"
    data = first.json()
    assert data["api"] == 1 and data["auth"] == ["entra"] and len(data["server_id"]) == 32 and data["version"]
    assert pub.get("/app/v1/discovery").json()["server_id"] == data["server_id"]  # bleibt gleich


def test_discovery_does_not_leak_internals(pub):
    text = pub.get("/app/v1/discovery").text
    for secret in ("geheim", TENANT, CLIENT, "dora", "adm01"):
        assert secret not in text


# ---------------------------------------------------------------- Anmeldeweg

def test_full_login_flow(pub, idp):
    done, verifier, state = app_login(pub, idp)
    assert done.status_code == 303 and done.headers["cache-control"] == "no-store"
    target = urlparse(done.headers["location"])
    assert (target.scheme, target.netloc) == ("ha-copilot", "auth")
    assert parse_qs(target.query)["state"] == [state]
    assert "set-cookie" not in {k.lower() for k, v in done.headers.items() if "ki_session" in v}  # kein Sitzungs-Cookie im Systembrowser
    assert pub.get("/api/me").status_code == 401

    token = redeem(pub, done, verifier)
    assert token.status_code == 200 and token.headers["cache-control"] == "no-store"
    data = token.json()
    assert data["device_token"].startswith("hcd_") and len(data["device_token"]) > 40
    assert data["profile"] == {"label": "Dora"} and data["expires_at"] and data["refresh_after"]

    ticket = pub.post("/app/v1/ticket", headers=bearer(data["device_token"]))
    assert ticket.status_code == 200 and ticket.json()["expires_in"] == 30
    entered = pub.get("/app/v1/enter", params={"ticket": ticket.json()["ticket"]})
    assert entered.status_code == 303 and entered.headers["location"] == "/new"
    assert entered.headers["referrer-policy"] == "no-referrer"
    assert "__Host-ki_session" in entered.headers["set-cookie"] and "Max-Age=604800" in entered.headers["set-cookie"]
    me = pub.get("/api/me")
    assert me.status_code == 200 and me.json()["id"] == "dora" and me.json()["app_access"] is True


def test_the_device_token_is_stored_only_as_a_hash(pub, idp, store):
    data = enroll(pub, idp)
    rows = store._conn.execute("SELECT * FROM devices").fetchall()
    assert len(rows) == 1 and data["device_token"] not in "".join(str(tuple(r)) for r in rows)
    assert rows[0]["token_hash"] == store._hash(data["device_token"])


def test_wrong_verifier_is_rejected_and_burns_the_code(pub, idp):
    done, verifier, _ = app_login(pub, idp)
    code = parse_qs(urlparse(done.headers["location"]).query)["code"][0]
    wrong = pub.post("/app/v1/token", json={"code": code, "verifier": secrets.token_urlsafe(48)})
    assert wrong.status_code == 400
    again = pub.post("/app/v1/token", json={"code": code, "verifier": verifier})
    assert again.status_code == 400  # auch der richtige Verifier hilft jetzt nicht mehr


def test_the_code_works_only_once(pub, idp):
    done, verifier, _ = app_login(pub, idp)
    assert redeem(pub, done, verifier).status_code == 200
    assert redeem(pub, done, verifier).status_code == 400


def test_the_code_expires(pub, idp, monkeypatch):
    done, verifier, _ = app_login(pub, idp)
    code = parse_qs(urlparse(done.headers["location"]).query)["code"][0]
    from app import appaccess as module

    real = module.time.monotonic
    monkeypatch.setattr(module.time, "monotonic", lambda: real() + 61)
    assert pub.post("/app/v1/token", json={"code": code, "verifier": verifier}).status_code == 400


@pytest.mark.parametrize("params", [
    {"challenge": "zu-kurz"},
    {"challenge": "a" * 44},
    {"state": "x"},
    {"state": "ungültig mit leerzeichen!"},
    {"platform": "windows"},
    {"platform": ""},
])
def test_login_start_rejects_bad_parameters(pub, params):
    good = {"challenge": pkce()[1], "state": secrets.token_urlsafe(16), "platform": "ios"}
    response = pub.get("/app/v1/login", params={**good, **params})
    assert response.status_code == 400
    assert "set-cookie" not in response.headers


def test_token_endpoint_validates_input(pub):
    for body in ({}, {"code": "x", "verifier": "y"}, {"code": "a" * 300, "verifier": "b" * 50}):
        assert pub.post("/app/v1/token", json=body).status_code in (400, 422)


def test_login_page_shows_the_app_hint_only_for_the_app(pub, idp):
    plain = pub.get("/login")
    assert plain.status_code == 200 and "für die App an" not in plain.text and "__APPNOTE__" not in plain.text
    verifier, challenge = pkce()
    pub.get("/app/v1/login", params={"challenge": challenge, "state": secrets.token_urlsafe(16), "platform": "ios"})
    hinted = pub.get("/login")
    assert "für die App an" in hinted.text and "__APPNOTE__" not in hinted.text


def test_an_existing_browser_session_does_not_skip_the_app_login(pub, idp):
    """Schutz vor untergeschobenen Anmeldungen: für die App immer frische Anmeldung."""
    from test_domain import login as browser_login

    assert browser_login(pub, idp).status_code == 303
    assert pub.get("/login").status_code == 303  # gewöhnlich: weiter in die Oberfläche
    verifier, challenge = pkce()
    pub.get("/app/v1/login", params={"challenge": challenge, "state": secrets.token_urlsafe(16), "platform": "ios"})
    assert pub.get("/login").status_code == 200


def test_the_flow_is_bound_to_the_browser_that_started_it(store, backend, idp):
    """Ein anderer Browser (ohne Vorgangs-Cookie) bekommt kein App-Token, sondern die gewöhnliche Anmeldung."""
    one = make(store, backend, idp)
    other = make(store, backend, idp)
    verifier, challenge = pkce()
    one.get("/app/v1/login", params={"challenge": challenge, "state": secrets.token_urlsafe(16), "platform": "ios"})
    response, state, nonce = start(other, "dora@example.org")
    idp.claims = idp.claims_for(nonce)
    done = other.get("/auth/callback", params={"code": "abc", "state": state})
    assert done.headers["location"] == "/new"  # gewöhnliche Anmeldung, keine Rückleitung in die App


def test_a_normal_browser_login_is_unchanged(pub, idp):
    from test_domain import login as browser_login

    done = browser_login(pub, idp)
    assert done.status_code == 303 and done.headers["location"] == "/new" and "__Host-ki_session" in done.headers["set-cookie"]
    assert pub.get("/api/me").status_code == 200


def test_denied_users_get_no_code(pub, idp, store):
    from test_domain import OID_DORA

    assert store.bind_oid("dora", OID_DORA)  # Dora ist schon an ihr Entra-Konto gebunden; ein anderes Konto passt nicht
    verifier, challenge = pkce()
    pub.get("/app/v1/login", params={"challenge": challenge, "state": secrets.token_urlsafe(16), "platform": "ios"})
    response, state, nonce = start(pub, "dora@example.org")
    idp.claims = idp.claims_for(nonce, oid="0f0f0f0f-0000-0000-0000-000000000003")
    done = pub.get("/auth/callback", params={"code": "abc", "state": state})
    assert done.headers["location"].startswith("/login?e=")


def test_unknown_address_never_reaches_the_app(pub, idp):
    pub.get("/app/v1/login", params={"challenge": pkce()[1], "state": secrets.token_urlsafe(16), "platform": "ios"})
    assert start(pub, "fremd@example.org")[0].status_code == 403


# ---------------------------------------------------------------- Ticket und Sitzung im WebView

def test_the_ticket_works_once(pub, idp):
    data = enroll(pub, idp)
    ticket = pub.post("/app/v1/ticket", headers=bearer(data["device_token"])).json()["ticket"]
    assert pub.get("/app/v1/enter", params={"ticket": ticket}).headers["location"] == "/new"
    second = pub.get("/app/v1/enter", params={"ticket": ticket})
    assert second.headers["location"] == "/login?e=expired" and "ki_session" not in second.headers.get("set-cookie", "")


def test_the_ticket_expires(pub, idp, monkeypatch):
    data = enroll(pub, idp)
    ticket = pub.post("/app/v1/ticket", headers=bearer(data["device_token"])).json()["ticket"]
    from app import appaccess as module

    real = module.time.monotonic
    monkeypatch.setattr(module.time, "monotonic", lambda: real() + 31)
    assert pub.get("/app/v1/enter", params={"ticket": ticket}).headers["location"] == "/login?e=expired"


def test_enter_rejects_garbage(pub):
    for ticket in ("", "x", "a" * 500):
        assert pub.get("/app/v1/enter", params={"ticket": ticket}).headers["location"] == "/login?e=expired"
    assert pub.get("/api/me").status_code == 401


def test_the_device_token_does_not_work_as_a_session_cookie(pub, idp):
    data = enroll(pub, idp)
    pub.cookies.set("__Host-ki_session", data["device_token"])
    assert pub.get("/api/me").status_code == 401


def test_the_session_cookie_does_not_work_as_a_bearer_token(pub, idp):
    data = enroll(pub, idp)
    ticket = pub.post("/app/v1/ticket", headers=bearer(data["device_token"])).json()["ticket"]
    pub.get("/app/v1/enter", params={"ticket": ticket})
    session = pub.cookies.get("__Host-ki_session")
    assert pub.post("/app/v1/ticket", headers=bearer(session)).status_code == 401
    assert pub.post("/app/v1/ticket", headers=bearer(ticket)).status_code == 401


@pytest.mark.parametrize("header", [{}, {"Authorization": "Bearer "}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer hcd_gibtesnicht"},
                                    {"Authorization": "Bearer " + "x" * 500}])
def test_bearer_endpoints_need_a_valid_token(pub, header):
    for path in ("/app/v1/ticket", "/app/v1/refresh", "/app/v1/logout"):
        response = pub.post(path, headers=header)
        assert response.status_code == 401 and response.headers["cache-control"] == "no-store"


def test_a_device_session_is_cut_off_after_removal(pub, idp):
    data = enroll(pub, idp)
    ticket = pub.post("/app/v1/ticket", headers=bearer(data["device_token"])).json()["ticket"]
    pub.get("/app/v1/enter", params={"ticket": ticket})
    assert pub.get("/api/me").status_code == 200
    assert pub.post("/app/v1/logout", headers=bearer(data["device_token"])).status_code == 204
    assert pub.get("/api/me").status_code == 401  # auch die laufende Sitzung im WebView endet sofort
    assert pub.post("/app/v1/ticket", headers=bearer(data["device_token"])).status_code == 401


def test_device_sessions_last_seven_days_at_most(pub, idp, store):
    data = enroll(pub, idp)
    ticket = pub.post("/app/v1/ticket", headers=bearer(data["device_token"])).json()["ticket"]
    pub.get("/app/v1/enter", params={"ticket": ticket})
    row = store._conn.execute("SELECT created_at, expires_at, device_id FROM sessions").fetchone()
    from datetime import datetime, timedelta, timezone

    span = datetime.fromisoformat(row["expires_at"]) - datetime.fromisoformat(row["created_at"])
    assert row["device_id"] and span.days == 7
    # Die Gültigkeit lässt sich auch durch viele Aufrufe nicht über das Maß hinaus verlängern.
    old = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat(timespec="seconds")
    soon = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="seconds")
    store._conn.execute("UPDATE sessions SET created_at = ?, expires_at = ?", (old, soon))
    store._conn.commit()
    for _ in range(3):
        pub.get("/api/me")
    after = store._conn.execute("SELECT expires_at FROM sessions").fetchone()["expires_at"]
    remaining = datetime.fromisoformat(after) - datetime.now(timezone.utc)
    assert timedelta(days=6) < remaining <= timedelta(days=7)  # verlängert, aber nur auf die 7 Tage der App


# ---------------------------------------------------------------- Erneuerung und Diebstahl

def test_refresh_rotates_the_token(pub, idp):
    data = enroll(pub, idp)
    old = data["device_token"]
    fresh = pub.post("/app/v1/refresh", headers=bearer(old))
    assert fresh.status_code == 200
    new = fresh.json()["device_token"]
    assert new != old and new.startswith("hcd_")
    assert pub.post("/app/v1/ticket", headers=bearer(new)).status_code == 200
    # Kurz nach der Erneuerung gilt das alte Token noch (Antwort ging unterwegs verloren)
    assert pub.post("/app/v1/ticket", headers=bearer(old)).status_code == 200


def test_reusing_an_old_token_after_the_grace_period_revokes_the_device(pub, idp, store):
    data = enroll(pub, idp)
    old = data["device_token"]
    new = pub.post("/app/v1/refresh", headers=bearer(old)).json()["device_token"]
    ticket = pub.post("/app/v1/ticket", headers=bearer(new)).json()["ticket"]
    pub.get("/app/v1/enter", params={"ticket": ticket})
    assert pub.get("/api/me").status_code == 200
    store._conn.execute("UPDATE devices SET prev_valid_until = '2000-01-01T00:00:00+00:00'")
    store._conn.commit()
    assert pub.post("/app/v1/ticket", headers=bearer(old)).status_code == 401  # Wiederverwendung
    assert pub.post("/app/v1/ticket", headers=bearer(new)).status_code == 401  # das Gerät ist gesperrt
    assert pub.get("/api/me").status_code == 401  # und seine Sitzungen sind weg
    listed = store.device_list("dora")
    assert listed[0]["status"] == "revoked" and listed[0]["reason"] == "reuse"


def test_an_expired_device_is_rejected(pub, idp, store):
    data = enroll(pub, idp)
    store._conn.execute("UPDATE devices SET expires_at = '2000-01-01T00:00:00+00:00'")
    store._conn.commit()
    assert pub.post("/app/v1/refresh", headers=bearer(data["device_token"])).status_code == 401


def test_a_device_cannot_outlive_the_hard_limit(store):
    device_id, token = store.device_create("dora", "iPhone", "ios", "1", 180)
    store._conn.execute("UPDATE devices SET created_at = '2000-01-01T00:00:00+00:00'")
    store._conn.commit()
    assert store.device_auth(token) is None
    assert store.device_active(device_id, "dora") is False


def test_rotation_never_extends_past_the_hard_limit(store):
    from datetime import datetime, timedelta, timezone

    device_id, token = store.device_create("dora", "iPhone", "ios", "1", 90)
    created = datetime.now(timezone.utc) - timedelta(days=170)
    store._conn.execute("UPDATE devices SET created_at = ?", (created.isoformat(timespec="seconds"),))
    store._conn.commit()
    _, expires = store.device_rotate(device_id, 90)
    assert datetime.fromisoformat(expires) <= created + timedelta(days=180, seconds=1)


def test_the_profile_must_still_exist(pub, idp, store, backend):
    data = enroll(pub, idp)
    store._conn.execute("PRAGMA foreign_keys = OFF")
    store._conn.execute("UPDATE devices SET profile_id = 'unbekannt'")
    store._conn.commit()
    assert pub.post("/app/v1/ticket", headers=bearer(data["device_token"])).status_code == 401


# ---------------------------------------------------------------- Geräteliste

def sign_in(client, idp):
    data = enroll(client, idp)
    ticket = client.post("/app/v1/ticket", headers=bearer(data["device_token"])).json()["ticket"]
    client.get("/app/v1/enter", params={"ticket": ticket})
    return data


def test_the_device_list_shows_only_own_devices_without_secrets(pub, idp, store, backend):
    sign_in(pub, idp)
    other_id, _ = store.device_create("adm01", "Admin-iPhone", "ios", "1", 90)
    listed = pub.get("/api/devices").json()["devices"]
    assert [d["name"] for d in listed] == ["Doras iPhone"]
    entry = listed[0]
    assert entry["status"] == "active" and entry["platform"] == "ios"
    text = pub.get("/api/devices").text
    assert "token" not in text and "hash" not in text and other_id not in text


def test_a_device_can_be_removed_from_the_list(pub, idp, store):
    data = sign_in(pub, idp)
    device_id = pub.get("/api/devices").json()["devices"][0]["id"]
    assert pub.delete(f"/api/devices/{device_id}").status_code == 403  # Schreibschutz (Header + Herkunft)
    assert pub.delete(f"/api/devices/{device_id}", headers=WRITE_PUBLIC).status_code == 204
    assert pub.get("/api/me").status_code == 401  # die Sitzung des Geräts ist beendet
    assert pub.post("/app/v1/ticket", headers=bearer(data["device_token"])).status_code == 401


def test_nobody_can_remove_foreign_devices(pub, idp, store):
    sign_in(pub, idp)
    other_id, other_token = store.device_create("adm01", "Admin-iPhone", "ios", "1", 90)
    assert pub.delete(f"/api/devices/{other_id}", headers=WRITE_PUBLIC).status_code == 404
    assert store.device_auth(other_token) is not None
    assert pub.delete("/api/devices/..%2F..", headers=WRITE_PUBLIC).status_code in (404, 405)
    assert pub.delete("/api/devices/ZZZZ", headers=WRITE_PUBLIC).status_code == 404


def test_all_devices_can_be_removed_at_once(pub, idp, store):
    sign_in(pub, idp)
    store.device_create("dora", "iPad", "ios", "1", 90)
    other_id, other_token = store.device_create("adm01", "Admin-iPhone", "ios", "1", 90)
    assert pub.delete("/api/devices", headers=WRITE_PUBLIC).status_code == 204
    assert pub.get("/api/devices").status_code == 401  # die eigene Sitzung war ein Gerät
    assert store.device_auth(other_token) is not None  # fremde bleiben


def test_the_list_is_empty_when_the_app_access_is_off(store, backend, idp):
    client = make(store, backend, idp, app_access=False)
    from test_domain import login as browser_login

    browser_login(client, idp)
    assert client.get("/api/devices").json() == {"devices": []}
    assert client.get("/api/me").json()["app_access"] is False


# ---------------------------------------------------------------- Begrenzung

def test_login_starts_are_rate_limited(pub):
    codes = []
    for _ in range(25):
        codes.append(pub.get("/app/v1/login", params={"challenge": pkce()[1], "state": secrets.token_urlsafe(16), "platform": "ios"}).status_code)
    assert codes[:20] == [303] * 20 and 429 in codes[20:]


def test_token_attempts_are_rate_limited(pub):
    codes = [pub.post("/app/v1/token", json={"code": secrets.token_urlsafe(32), "verifier": secrets.token_urlsafe(48)}).status_code
             for _ in range(35)]
    assert codes[0] == 400 and codes[-1] == 429


def test_failed_bearer_attempts_are_rate_limited(pub):
    codes = [pub.post("/app/v1/ticket", headers=bearer("hcd_" + secrets.token_urlsafe(32))).status_code for _ in range(35)]
    assert codes[0] == 401 and codes[-1] == 429


# ---------------------------------------------------------------- Anmeldung mit Home Assistant

def test_the_app_login_works_with_home_assistant_only(store, backend, monkeypatch):
    """Nur Home Assistant (ohne Entra): derselbe Weg, die App sieht nie ein Home-Assistant-Token."""
    import test_ha_access as ha

    server = ha.FakeHaServer()
    server.user = {"id": ha.DORA.upper(), "name": "Dora"}

    class FakeWs:
        def __init__(self, token, url):
            pass

        async def call(self, command):
            return server.user

    monkeypatch.setattr(ha.ha_login_module, "HaApi", FakeWs)
    client = ha.make_domain(store, backend, server, ha_url=ha.HA, app_access=True)
    assert client.get("/app/v1/discovery").json()["auth"] == ["ha"]
    verifier, challenge = pkce()
    state = secrets.token_urlsafe(16)
    client.get("/app/v1/login", params={"challenge": challenge, "state": state, "platform": "ios", "device": "iPhone"})
    ha_state, _ = ha.ha_start(client)
    done = client.get("/auth/ha-callback", params={"code": "abc", "state": ha_state})
    assert done.status_code == 303 and done.headers["location"].startswith("ha-copilot://auth?code=")
    assert server.revoked  # Home-Assistant-Token wurde sofort widerrufen
    token = redeem(client, done, verifier)
    assert token.status_code == 200 and token.json()["profile"] == {"label": "Dora"}
    assert "zugriff" not in token.text and "erneuern" not in token.text
