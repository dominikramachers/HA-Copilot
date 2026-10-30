"""Sicherheitsprüfung 0.24.0: Größengrenzen nur für Angemeldete, Adressen, Header, Prozessumgebung."""
import copy

import httpx
import pytest
from fastapi.testclient import TestClient

from app import attachments as att
from app.backend import ClaudeSdkBackend
from app.config import parse_settings
from app.main import SMALL_BODY_BYTES, build_ingress_app, build_public_app
from app.oidc import EntraClient

from conftest import ADM01, RAW, as_user
from test_domain import BASE, CLIENT, TENANT, WRITE_PUBLIC, FakeIdp, location, login

BIG = SMALL_BODY_BYTES + 50_000  # über der kleinen Grenze, weit unter der Dateigrenze
JSON = {"Content-Type": "application/json"}


def public_client(store, backend, **extra):
    raw = copy.deepcopy(RAW)
    raw.update(
        public_enabled=True, public_base_url=BASE, entra_tenant_id=TENANT,
        entra_client_id=CLIENT, entra_client_secret="geheim", **extra,
    )
    settings = parse_settings(raw, frozenset({"testclient"}))
    idp = FakeIdp()
    http = httpx.AsyncClient(transport=httpx.MockTransport(idp.handler))
    entra = EntraClient(TENANT, CLIENT, "geheim", f"{BASE}/auth/callback", http, "https://idp.test")
    return TestClient(build_public_app(settings, store, backend, entra), base_url=BASE, follow_redirects=False), idp


# ------------------------------------------------- Größengrenzen nur für Angemeldete


def test_domain_big_body_needs_a_real_session(store, backend):
    pub, idp = public_client(store, backend)
    path = "/api/chats/abc/send"
    # Nur ein Cookie mit dem richtigen Namen genügt nicht: die kleine Grenze gilt.
    fake = pub.post(path, content=b"x" * BIG, headers={**WRITE_PUBLIC, **JSON, "Cookie": "__Host-ki_session=erfunden"})
    assert fake.status_code == 413
    # Ohne Cookie sowieso.
    assert pub.post(path, content=b"x" * BIG, headers={**WRITE_PUBLIC, **JSON}).status_code == 413
    # Mit gültiger Sitzung darf die Anfrage größer sein (hier scheitert sie erst später, nicht an der Größe).
    assert login(pub, idp).status_code == 303
    real = pub.post(path, content=b"x" * BIG, headers={**WRITE_PUBLIC, **JSON})
    assert real.status_code != 413
    # Auch angemeldet bleibt die Dateigrenze eine Grenze.
    huge = pub.post(path, content=b"x" * (att.MAX_BODY_BYTES + 10), headers={**WRITE_PUBLIC, **JSON})
    assert huge.status_code == 413


def test_domain_ignores_ingress_header_for_size_limit(store, backend):
    pub, _ = public_client(store, backend)
    response = pub.post(
        "/api/chats/abc/send", content=b"x" * BIG, headers={**WRITE_PUBLIC, **JSON, **as_user(ADM01)}
    )
    assert response.status_code == 413


def test_ingress_big_body_needs_the_trusted_proxy(client, client_untrusted_peer):
    path = "/api/chats/abc/send"
    headers = {**as_user(ADM01, True), **JSON}
    # Vertrauter Proxy mit bekanntem Benutzer: große Anfrage wird angenommen (Chat unbekannt → 404, nicht 413).
    assert client.post(path, content=b"x" * BIG, headers=headers).status_code != 413
    # Gleiche Header von einer fremden Gegenstelle: klein bleibt klein.
    assert client_untrusted_peer.post(path, content=b"x" * BIG, headers=headers).status_code == 413
    # Unbekannte Kennung vom Proxy: ebenfalls klein.
    stranger = {**as_user("f" * 32, True), **JSON}
    assert client.post(path, content=b"x" * BIG, headers=stranger).status_code == 413


# ------------------------------------------------- Client-Adresse hinter Cloudflare


def test_forged_forwarded_addresses_do_not_dodge_the_rate_limit(store, backend):
    pub, _ = public_client(store, backend, public_trusted_proxies=["testclient"])
    codes = []
    for n in range(12):
        # Wechselnder Müll im Header darf nicht jedes Mal einen neuen Zähler ergeben.
        response = pub.post(
            "/auth/start", json={"email": "niemand@example.org"},
            headers={**WRITE_PUBLIC, "CF-Connecting-IP": f"kein-ip-{n}"},
        )
        codes.append(response.status_code)
    assert codes[:10] == [403] * 10 and codes[10:] == [429, 429]


def test_real_forwarded_addresses_are_counted_separately(store, backend):
    pub, _ = public_client(store, backend, public_trusted_proxies=["testclient"])
    for n in range(12):
        response = pub.post(
            "/auth/start", json={"email": "niemand@example.org"},
            headers={**WRITE_PUBLIC, "CF-Connecting-IP": f"203.0.113.{n + 1}"},
        )
        assert response.status_code == 403  # jede Adresse hat ihren eigenen Zähler


# ------------------------------------------------- Header


@pytest.mark.parametrize("path", ["/login", "/healthz"])
def test_domain_responses_carry_hardening_headers(store, backend, path):
    pub, _ = public_client(store, backend)
    headers = pub.get(path).headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["cross-origin-opener-policy"] == "same-origin"
    assert headers["cross-origin-resource-policy"] == "same-origin"
    assert "geolocation=()" in headers["permissions-policy"]
    assert "frame-ancestors 'none'" in headers["content-security-policy"]
    assert "max-age" in headers["strict-transport-security"]


def test_ingress_keeps_framing_for_home_assistant(client):
    headers = client.get("/", headers=as_user(ADM01)).headers
    assert "frame-ancestors 'self'" in headers["content-security-policy"]
    assert "geolocation=()" in headers["permissions-policy"]
    assert "cross-origin-opener-policy" not in headers  # Ingress läuft im Rahmen von Home Assistant


def test_login_cookies_are_locked_down(store, backend):
    pub, idp = public_client(store, backend)
    response = login(pub, idp)
    assert location(response) == "/new"
    cookies = " ".join(v for k, v in response.headers.multi_items() if k == "set-cookie").lower()
    assert "__host-ki_session" in cookies and "httponly" in cookies and "secure" in cookies and "samesite=lax" in cookies


# ------------------------------------------------- Claude-Prozess


def test_claude_process_does_not_get_the_supervisor_token(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERVISOR_TOKEN", "geheim")
    env = ClaudeSdkBackend("abo", "m", tmp_path)._options("low").env
    assert env["SUPERVISOR_TOKEN"] == ""
    assert "geheim" not in "".join(str(v) for v in env.values())
