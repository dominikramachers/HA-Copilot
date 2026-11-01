"""Lesestatus der Chats: neue Antworten sind ungelesen, bis eine Oberfläche sie angezeigt hat."""
from conftest import ADM01, DORA, as_user
from test_chat import new_chat, send


def chat(client, chat_id, user=ADM01):
    return next(c for c in client.get("/api/chats", headers=as_user(user)).json() if c["id"] == chat_id)


def mark(client, chat_id, unread, user=ADM01):
    return client.patch(f"/api/chats/{chat_id}", json={"unread": unread}, headers=as_user(user, True))


def test_new_and_empty_chats_are_read(client):
    chat_id = new_chat(client)
    assert chat(client, chat_id)["unread"] is False


def test_a_new_answer_is_unread_until_marked_read(client):
    chat_id = new_chat(client)
    send(client, chat_id, "Hallo")
    assert chat(client, chat_id)["unread"] is True
    assert mark(client, chat_id, False).json()["unread"] is False
    assert chat(client, chat_id)["unread"] is False
    send(client, chat_id, "Noch eine Frage")
    assert chat(client, chat_id)["unread"] is True


def test_marking_does_not_change_order_or_other_fields(client):
    chat_id = new_chat(client)
    send(client, chat_id, "Hallo")
    before = chat(client, chat_id)
    mark(client, chat_id, False)
    after = chat(client, chat_id)
    assert after["updated_at"] == before["updated_at"] and after["title"] == before["title"]
    mark(client, chat_id, True)
    assert chat(client, chat_id)["unread"] is True  # auch von Hand als ungelesen markierbar


def test_read_state_belongs_to_the_owner_only(client):
    chat_id = new_chat(client)
    send(client, chat_id, "Hallo")
    assert mark(client, chat_id, False, user=DORA).status_code == 404
    assert chat(client, chat_id)["unread"] is True


def test_marking_needs_the_write_header(client):
    chat_id = new_chat(client)
    send(client, chat_id, "Hallo")
    r = client.patch(f"/api/chats/{chat_id}", json={"unread": False}, headers=as_user(ADM01))
    assert r.status_code == 403 and chat(client, chat_id)["unread"] is True


def test_existing_databases_gain_the_column(tmp_path):
    import sqlite3

    from app.db import Store

    path = tmp_path / "old.sqlite3"
    first = Store(path)
    first.sync_profiles(["adm01"])
    chat_id = first.create_chat("adm01", "Alt")["id"]
    first.close()
    raw = sqlite3.connect(path)
    raw.execute("ALTER TABLE chats DROP COLUMN unread")
    raw.commit()
    raw.close()
    reopened = Store(path)
    assert reopened.get_chat("adm01", chat_id)["unread"] is False
    reopened.close()
