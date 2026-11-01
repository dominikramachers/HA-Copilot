"""HTML-Vorschauen: nur im Arbeitsspeicher, abgeschottet, pro Profil getrennt."""
from app.previews import PREVIEW_HEADERS, PreviewStore
from tests.conftest import ADM01, DORA, as_user

PAGE = "<!doctype html><title>Rechner</title><script>document.title='x'</script><p>Hallo</p>"


def test_store_expiry_isolation_and_limit():
    now = [0.0]
    store = PreviewStore(ttl=100, per_profile=2, clock=lambda: now[0])
    a = store.put("p1", "A")
    assert store.get("p1", a) == "A" and store.get("p2", a) is None
    b, c = store.put("p1", "B"), store.put("p1", "C")
    assert store.get("p1", a) is None  # ältestes fliegt bei Überschreiten des Limits raus
    assert store.get("p1", b) == "B" and store.get("p1", c) == "C"
    now[0] = 101
    assert store.get("p1", b) is None and len(store) == 0


def test_create_and_show_preview_with_strict_headers(client):
    created = client.post("/api/previews", json={"html": PAGE}, headers=as_user(ADM01, True))
    assert created.status_code == 201
    shown = client.get(f"/preview/{created.json()['id']}", headers=as_user(ADM01))
    assert shown.status_code == 200 and shown.text == PAGE
    csp = shown.headers["content-security-policy"]
    assert "sandbox allow-scripts" in csp and "default-src 'none'" in csp
    assert "connect-src" not in csp and "allow-same-origin" not in csp  # kein Netzwerk, keine Herkunft der App
    assert "'self'" not in csp.replace("frame-ancestors 'self'", "")
    assert shown.headers["cache-control"] == "no-store"
    assert shown.headers["content-security-policy"] == PREVIEW_HEADERS["Content-Security-Policy"]


def test_preview_is_private_to_its_profile_and_guarded(client):
    pid = client.post("/api/previews", json={"html": PAGE}, headers=as_user(ADM01, True)).json()["id"]
    assert client.get(f"/preview/{pid}", headers=as_user(DORA)).status_code == 404
    assert client.get("/preview/gibtsnicht", headers=as_user(ADM01)).status_code == 404
    assert client.post("/api/previews", json={"html": PAGE}, headers=as_user(ADM01)).status_code == 403  # Schutzheader fehlt


def test_preview_size_limits(client):
    too_long = client.post("/api/previews", json={"html": "x" * 150_001}, headers=as_user(ADM01, True))
    assert too_long.status_code == 422
    huge = client.post(
        "/api/previews", content=b"{" + b" " * 800_000 + b"}", headers={**as_user(ADM01, True), "Content-Type": "application/json"}
    )
    assert huge.status_code == 413
