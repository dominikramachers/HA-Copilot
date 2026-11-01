"""Kern-Garantie: Ein Profil sieht und verändert nie Daten eines anderen Profils."""
import sqlite3

import pytest


def test_store_hides_foreign_chats(store):
    chat = store.create_chat("adm01", "Geheim")
    store.add_message("adm01", chat["id"], "user", "nur für adm01")

    assert store.list_chats("dora") == []
    assert store.get_chat("dora", chat["id"]) is None
    assert store.list_messages("dora", chat["id"]) is None
    assert store.add_message("dora", chat["id"], "user", "Einschleusen") is None
    assert store.rename_chat("dora", chat["id"], "Gekapert") is False
    assert store.delete_chat("dora", chat["id"]) is False

    # Nichts davon hat den Chat des Besitzers verändert.
    assert store.get_chat("adm01", chat["id"])["title"] == "Geheim"
    messages = store.list_messages("adm01", chat["id"])
    assert [m["content"] for m in messages] == ["nur für adm01"]


def test_store_requires_profile(store):
    with pytest.raises(ValueError):
        store.list_chats("")
    with pytest.raises(ValueError):
        store.create_chat(None)  # type: ignore[arg-type]


def test_database_rejects_message_with_foreign_owner(store):
    chat = store.create_chat("adm01")
    with pytest.raises(sqlite3.IntegrityError):
        with store._conn:  # direkter Zugriff: die Datenbank selbst muss das verhindern
            store._conn.execute(
                "INSERT INTO messages (chat_id, profile_id, role, content, created_at) "
                "VALUES (?, 'dora', 'user', 'x', '2026-01-01')",
                (chat["id"],),
            )


def test_deleting_chat_removes_messages(store):
    chat = store.create_chat("dora")
    store.add_message("dora", chat["id"], "user", "hallo")
    assert store.delete_chat("dora", chat["id"]) is True
    remaining = store._conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    assert remaining == 0


def test_removed_profile_keeps_data_but_is_not_deleted(store):
    chat = store.create_chat("dora", "bleibt")
    store.sync_profiles(["adm01"])  # dora aus der Konfiguration entfernt
    assert store.get_chat("dora", chat["id"])["title"] == "bleibt"
