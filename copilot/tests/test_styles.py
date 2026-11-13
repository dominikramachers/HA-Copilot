"""Schreibstile: Vorgaben, eigene Stile, Wahl je Chat, Standard je Person, Ableiten aus Beispieltexten."""
import sqlite3

from app import styles
from app.backend import EchoBackend, compose_system
from tests.conftest import ADM01, DORA, as_user


def mk(client, user=DORA):
    return client.post("/api/chats", json={}, headers=as_user(user, True)).json()["id"]


def send(client, chat, text="Hallo", user=DORA, **extra):
    return client.post(f"/api/chats/{chat}/send", json={"content": text, **extra}, headers=as_user(user, True))


def body(name="Mein Stil", text="Schreibe kurz."):
    return {"name": name, "description": "Beschreibung", "instructions": text}


def test_list_has_presets_and_no_own_styles(client):
    data = client.get("/api/styles", headers=as_user(DORA)).json()
    assert [p["id"] for p in data["presets"]][:2] == ["preset:short", "preset:explain"]
    assert data["own"] == [] and data["default"] == ""
    assert all(p["name"] and p["description"] for p in data["presets"])


def test_own_style_lifecycle_and_isolation(client):
    h = as_user(DORA, True)
    made = client.post("/api/styles", json=body(), headers=h).json()
    assert made["name"] == "Mein Stil" and made["preset"] is False
    assert [s["id"] for s in client.get("/api/styles", headers=as_user(DORA)).json()["own"]] == [made["id"]]
    assert client.get("/api/styles", headers=as_user(ADM01)).json()["own"] == []
    changed = client.put(f"/api/styles/{made['id']}", json=body("Neu", "Schreibe lang."), headers=h).json()
    assert changed["name"] == "Neu" and changed["instructions"] == "Schreibe lang."
    assert client.put(f"/api/styles/{made['id']}", json=body(), headers=as_user(ADM01, True)).status_code == 404
    assert client.delete(f"/api/styles/{made['id']}", headers=as_user(ADM01, True)).status_code == 404
    assert client.delete(f"/api/styles/{made['id']}", headers=h).status_code == 204
    assert client.get("/api/styles", headers=as_user(DORA)).json()["own"] == []


def test_limit_of_own_styles(client):
    h = as_user(DORA, True)
    for i in range(styles.MAX_OWN):
        assert client.post("/api/styles", json=body(f"S{i}"), headers=h).status_code == 201
    assert client.post("/api/styles", json=body("zu viel"), headers=h).status_code == 409


def test_style_reaches_the_backend_and_is_remembered_per_chat(client, backend):
    chat = mk(client)
    send(client, chat)
    assert backend.calls[-1]["style"] is None
    send(client, chat, style="preset:short")
    assert "knapp" in backend.calls[-1]["style"]
    send(client, chat)  # ohne Angabe bleibt der Stil des Chats
    assert "knapp" in backend.calls[-1]["style"]
    assert client.get("/api/chats", headers=as_user(DORA)).json()[0]["style_id"] == "preset:short"
    send(client, chat, style="none")
    assert backend.calls[-1]["style"] is None
    assert send(client, chat, style="preset:gibtesnicht").status_code == 422
    assert send(client, chat, style="fremd").status_code == 422


def test_default_style_applies_unless_chat_says_none(client, backend):
    h = as_user(DORA, True)
    own = client.post("/api/styles", json=body("Eigen", "Schreibe wie ein Pirat."), headers=h).json()
    assert client.put("/api/me/style", json={"style": own["id"]}, headers=h).json() == {"style": own["id"]}
    assert client.put("/api/me/style", json={"style": "nope"}, headers=h).status_code == 422
    chat = mk(client)
    send(client, chat)
    assert backend.calls[-1]["style"] == "Schreibe wie ein Pirat."
    send(client, chat, style="none")
    assert backend.calls[-1]["style"] is None
    # fremder Stil lässt sich nicht als Standard oder im Chat wählen
    other = client.post("/api/styles", json=body("Fremd"), headers=as_user(ADM01, True)).json()
    assert client.put("/api/me/style", json={"style": other["id"]}, headers=h).status_code == 422
    assert send(client, chat, style=other["id"]).status_code == 422


def test_deleting_a_style_resets_chat_and_default(client, backend):
    h = as_user(DORA, True)
    own = client.post("/api/styles", json=body(), headers=h).json()
    client.put("/api/me/style", json={"style": own["id"]}, headers=h)
    chat = mk(client)
    send(client, chat, style=own["id"])
    client.delete(f"/api/styles/{own['id']}", headers=h)
    assert client.get("/api/styles", headers=as_user(DORA)).json()["default"] == ""
    assert client.get("/api/chats", headers=as_user(DORA)).json()[0]["style_id"] == ""
    send(client, chat)
    assert backend.calls[-1]["style"] is None


def test_system_prompt_block_keeps_the_rules():
    plain = compose_system(None)
    styled = compose_system(None, style="Schreibe knapp.")
    assert styled.startswith(plain) and "Schreibe knapp." in styled and "Rückfragen" in styled
    assert compose_system(None, style="   ") == plain
    assert len(styles.block("x" * 5000)) < styles.STYLE_MAX + 400


def test_learn_from_sample_text(client):
    h = as_user(DORA, True)
    assert client.post("/api/styles/learn", json={"text": "zu kurz"}, headers=h).status_code == 422
    found = client.post("/api/styles/learn", json={"text": "Das ist ein Beispiel. " * 30}, headers=h)
    # das Test-Backend (FakeBackend) kann es nicht: verständliche Meldung statt Absturz
    assert found.status_code == 502


def test_learn_with_echo_backend(store):
    from fastapi.testclient import TestClient

    from app.config import parse_settings
    from app.main import build_ingress_app
    from tests.conftest import RAW

    client = TestClient(build_ingress_app(parse_settings(RAW, frozenset({"testclient"})), store, EchoBackend()))
    found = client.post("/api/styles/learn", json={"text": "Das ist ein Beispiel. " * 30}, headers=as_user(DORA, True))
    assert found.status_code == 200 and found.json()["instructions"]


def test_migration_adds_columns(tmp_path):
    from app.db import Store

    path = tmp_path / "alt.db"
    Store(path)
    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE chats DROP COLUMN style_id")
    conn.execute("ALTER TABLE profiles DROP COLUMN default_style")
    conn.commit()
    conn.close()
    again = Store(path)
    assert "style_id" in {r["name"] for r in again._conn.execute("PRAGMA table_info(chats)")}
    assert "default_style" in {r["name"] for r in again._conn.execute("PRAGMA table_info(profiles)")}
