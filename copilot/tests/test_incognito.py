"""Inkognito-Chat: nichts bleibt zurück (keine Liste, kein Gedächtnis, kein Export, keine Sicherung, keine Handy-Meldung)."""
import asyncio
import dataclasses
import io
import sqlite3
import zipfile

import pytest
from fastapi.testclient import TestClient

import app.notifier as notifierlib
from app.config import parse_settings
from app.main import build_ingress_app
from conftest import ADM01, DORA, RAW, FakeBackend, as_user
from test_background_run import asgi
from test_notifier import PhoneHa
from test_schedules import SETTINGS

H = as_user(DORA, True)


def make(store, **raw):
    backend = FakeBackend(("Geheime ", "Antwort"))
    settings = parse_settings({**RAW, **raw}, frozenset({"testclient"}))
    return TestClient(build_ingress_app(settings, store, backend)), backend


def incognito(client):
    r = client.post("/api/chats", json={"incognito": True}, headers=H)
    assert r.status_code == 201, r.text
    return r.json()


def test_created_hidden_and_not_in_any_list(store):
    client, _ = make(store)
    normal = client.post("/api/chats", json={}, headers=H).json()
    client.post(f"/api/chats/{normal['id']}/send", json={"content": "Sichtwort Zebra"}, headers=H)  # Kontrolle: ein normaler Chat taucht auf
    chat = incognito(client)
    assert chat["kind"] == "incognito" and chat["project_id"] is None
    client.post(f"/api/chats/{chat['id']}/send", json={"content": "Geheimwort Zebra"}, headers=H)
    assert [c["id"] for c in client.get("/api/chats", headers=as_user(DORA)).json()] == [normal["id"]]
    assert [h["chat_id"] for h in client.get("/api/search", params={"q": "Zebra"}, headers=as_user(DORA)).json()] == [normal["id"]]
    assert client.get("/api/voice/chats", headers=as_user(DORA)).json() == []
    export = client.get("/api/export", headers=as_user(DORA))
    pack = zipfile.ZipFile(io.BytesIO(export.content))
    text = "".join(pack.read(n).decode("utf-8", "ignore") for n in pack.namelist())
    assert "Sichtwort" in text and "Geheimwort" not in text
    # während er offen ist, lässt er sich wie ein Chat lesen
    assert [m["role"] for m in client.get(f"/api/chats/{chat['id']}/messages", headers=as_user(DORA)).json()] == ["user", "assistant"]


def test_foreign_person_cannot_touch_it(store):
    client, _ = make(store)
    chat = incognito(client)
    assert client.get(f"/api/chats/{chat['id']}/messages", headers=as_user(ADM01)).status_code == 404
    assert client.delete(f"/api/chats/{chat['id']}", headers=as_user(ADM01, True)).status_code == 404


def test_no_project_no_patch_no_export_no_keep(store):
    client, _ = make(store)
    pid = client.post("/api/projects", json={"name": "P"}, headers=H).json()["id"]
    assert client.post("/api/chats", json={"incognito": True, "project_id": pid}, headers=H).status_code == 422
    chat = incognito(client)
    for body in ({"project_id": pid}, {"pinned": True}, {"keep": True}, {"title": "Neu"}):
        assert client.patch(f"/api/chats/{chat['id']}", json=body, headers=H).status_code == 409
    assert client.get(f"/api/chats/{chat['id']}/export", headers=as_user(DORA)).status_code == 409
    assert store.get_chat("dora", chat["id"])["kind"] == "incognito"


def test_option_switches_it_off(store):
    client, _ = make(store, incognito_enabled=False)
    assert client.post("/api/chats", json={"incognito": True}, headers=H).status_code == 403
    assert client.get("/api/me", headers=as_user(DORA)).json()["incognito"] is False
    on, _ = make(store)
    assert on.get("/api/me", headers=as_user(DORA)).json()["incognito"] is True


def test_no_memory_for_the_ai_in_any_scope(store):
    client, backend = make(store)
    pid = store.create_project("dora", "Heizung")["id"]
    store.memory_save("person", "dora", "Vorliebe", "Mag Zitronentee", "dora")
    store.memory_save("household", "dora", "Heizplan", "Winterplan Sieben", "dora")
    store.project_memory_save("dora", pid, "Absprache", "Vorlauf Fünfunddreißig", "dora")
    normal = client.post("/api/chats", json={"project_id": pid}, headers=H).json()
    client.post(f"/api/chats/{normal['id']}/send", json={"content": "Hallo"}, headers=H)
    seen = backend.calls[-1]
    assert "Zitronentee" in seen["note"] and "Winterplan" in seen["note"] and "Fünfunddreißig" in seen["note"]
    assert {"memory_save", "memory_list", "memory_forget"} <= {t.name for t in seen["tools"]}

    chat = incognito(client)
    client.post(f"/api/chats/{chat['id']}/send", json={"content": "Hallo"}, headers=H)
    seen = backend.calls[-1]
    assert "Zitronentee" not in seen["note"] and "Winterplan" not in seen["note"] and "Fünfunddreißig" not in seen["note"]
    names = {t.name for t in (seen["tools"] or [])}
    assert not [n for n in names if n.startswith(("memory_", "knowledge_", "chat_", "project_"))]
    assert "Inkognito-Chat" in seen["note"]


def test_nothing_is_written_to_memory_or_knowledge(store):
    client, _ = make(store)
    chat = incognito(client)
    client.post(f"/api/chats/{chat['id']}/send", json={"content": "Merk dir: ich mag Tee"}, headers=H)
    assert store.memory_list("person", "dora") == [] and store.memory_list("household", auto=False) == []
    assert store._conn.execute("SELECT COUNT(*) FROM project_memories").fetchone()[0] == 0


def test_no_title_call_and_stays_named(store):
    client, _ = make(store)
    chat = incognito(client)
    client.post(f"/api/chats/{chat['id']}/send", json={"content": "Eine ziemlich lange erste Frage zum Wetter"}, headers=H)
    assert store.get_chat("dora", chat["id"])["title"] == "Inkognito-Chat"
    assert client.post(f"/api/chats/{chat['id']}/title", headers=H).json()["title"] == "Inkognito-Chat"


def test_delete_removes_messages_and_generated_files(store):
    client, _ = make(store)
    chat = incognito(client)
    client.post(f"/api/chats/{chat['id']}/send", json={"content": "Geheimwort Zebra"}, headers=H)
    file = store.outfile_add("dora", chat["id"], "bericht.txt", "text/plain", b"Geheimer Inhalt", 7)
    path = store._outfile_path(file["id"])
    assert path.exists()
    assert client.delete(f"/api/chats/{chat['id']}", headers=H).status_code == 204
    assert not path.exists()
    assert store._conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
    assert store._conn.execute("SELECT COUNT(*) FROM outfiles").fetchone()[0] == 0


def test_sweep_removes_idle_and_purge_removes_all(store):
    old = store.create_chat("dora", "Inkognito-Chat", kind="incognito")["id"]
    new = store.create_chat("dora", "Inkognito-Chat", kind="incognito")["id"]
    normal = store.create_chat("dora", "Normal")["id"]
    store._conn.execute("UPDATE chats SET updated_at = '2020-01-01T00:00:00+00:00' WHERE id IN (?, ?)", (old, normal))
    store._conn.commit()
    assert store.incognito_sweep(180) == 1
    assert store.get_chat("dora", old) is None and store.get_chat("dora", new) and store.get_chat("dora", normal)
    assert store.incognito_sweep(0) == 1 and store.get_chat("dora", new) is None and store.get_chat("dora", normal)


def test_snapshots_and_database_export_leave_it_out(store, tmp_path):
    chat = store.create_chat("dora", "Inkognito-Chat", kind="incognito")["id"]
    store.add_message("dora", chat, "user", "Geheimwort Zebra")
    keep = store.create_chat("dora", "Normal")["id"]
    store.add_message("dora", keep, "user", "Sichtbar Giraffe")
    path = store.snapshot(tmp_path / "snaps")
    raw = path.read_bytes()
    assert b"Zebra" not in raw and b"Giraffe" in raw
    db = sqlite3.connect(path)
    assert db.execute("SELECT COUNT(*) FROM chats WHERE kind = 'incognito'").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM chats").fetchone()[0] == 1
    db.close()
    assert store.get_chat("dora", chat)  # die laufende Datenbank bleibt unberührt


def test_deleted_text_is_overwritten_not_only_unlinked(store):
    assert store._conn.execute("PRAGMA secure_delete").fetchone()[0] == 1


def test_no_phone_notification_for_incognito(store, monkeypatch):
    monkeypatch.setattr(notifierlib, "NOTIFY_DELAY_SECONDS", 0)
    ha = PhoneHa()
    app = build_ingress_app(SETTINGS, store, FakeBackend(("Antwort.",)), ha=ha)
    secret = store.create_chat("adm01", "Inkognito-Chat", kind="incognito")["id"]
    normal = store.create_chat("adm01", "Neuer Chat")["id"]

    async def go(chat_id):
        await asgi(app, "POST", f"/api/chats/{chat_id}/send", {"content": "Frage"}, hang_up_after=-1)
        await asyncio.sleep(0.4)

    asyncio.run(go(secret))
    assert ha.sent() == []
    asyncio.run(go(normal))
    assert len(ha.sent()) == 1  # zur Kontrolle: ein normaler Chat meldet sich


def test_delete_all_chats_includes_it(store):
    client, _ = make(store)
    chat = incognito(client)
    client.post("/api/data/delete-chats", json={"confirm": "LÖSCHEN"}, headers=H)
    assert store.get_chat("dora", chat["id"]) is None
