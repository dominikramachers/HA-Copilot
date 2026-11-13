"""Archiv: archivierte Chats verschwinden aus den Listen, bleiben aber auffindbar; Schreiben holt sie zurück."""
from tests.conftest import ADM01, DORA, as_user


def make_chat(client, user=DORA, **body):
    r = client.post("/api/chats", json=body, headers=as_user(user, True))
    assert r.status_code == 201, r.text
    return r.json()


def patch(client, chat_id, user=DORA, **body):
    r = client.patch(f"/api/chats/{chat_id}", json=body, headers=as_user(user, True))
    assert r.status_code == 200, r.text
    return r.json()


def listed(client, chat_id, user=DORA):
    rows = client.get("/api/chats", headers=as_user(user)).json()
    return next((c for c in rows if c["id"] == chat_id), None)


def test_archive_and_restore(client):
    chat = make_chat(client)
    assert chat["archived"] is False
    assert patch(client, chat["id"], archived=True)["archived"] is True
    # bleibt in der Liste der API (die Oberfläche filtert), aber mit Markierung
    assert listed(client, chat["id"])["archived"] is True
    assert patch(client, chat["id"], archived=False)["archived"] is False


def test_archive_and_pin_exclude_each_other(client):
    chat = make_chat(client)
    patch(client, chat["id"], pinned=True)
    done = patch(client, chat["id"], archived=True)
    assert done["archived"] is True and done["pinned"] is False
    done = patch(client, chat["id"], pinned=True)
    assert done["pinned"] is True and done["archived"] is False


def test_writing_returns_chat_from_archive(client, store):
    chat = make_chat(client)
    patch(client, chat["id"], archived=True)
    store.add_message("dora", chat["id"], "user", "Weiter geht es")
    assert listed(client, chat["id"])["archived"] is False


def test_archived_chat_stays_searchable(client, store):
    chat = make_chat(client)
    store.add_message("dora", chat["id"], "user", "Geheimwort Zebra")
    patch(client, chat["id"], archived=True)
    hits = client.get("/api/search", params={"q": "Zebra"}, headers=as_user(DORA)).json()
    assert [h["chat_id"] for h in hits] == [chat["id"]] and hits[0]["archived"] is True


def test_archive_is_per_person(client):
    chat = make_chat(client, ADM01)
    r = client.patch(f"/api/chats/{chat['id']}", json={"archived": True}, headers=as_user(DORA, True))
    assert r.status_code == 404
    assert listed(client, chat["id"], ADM01)["archived"] is False


def test_migration_adds_column(tmp_path):
    import sqlite3

    from app.db import Store

    path = tmp_path / "alt.db"
    first = Store(path)
    first.close() if hasattr(first, "close") else None
    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE chats DROP COLUMN archived_at")
    conn.commit()
    conn.close()
    again = Store(path)
    cols = {r["name"] for r in again._conn.execute("PRAGMA table_info(chats)")}
    assert "archived_at" in cols
