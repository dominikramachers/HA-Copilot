"""Gedächtnis: Projektgedächtnis als dritter Bereich, Herkunft der Einträge, Rückgängig und Themen-Index im Kontext."""
import asyncio

import pytest

from app.context_tools import ContextToolbox, PROJECT_LIMIT
from app.ha_tools import ToolError
from tests.conftest import ADM01, DORA, as_user


def run(coro):
    return asyncio.run(coro)


class Asker:
    async def __call__(self, label, details, offer):
        return "allow"


def box(store, profile="dora", *, project_id=None, read_only=False):
    events, counter = [], iter(range(1, 1000))
    b = ContextToolbox(
        store, profile, profile.capitalize(), project_id=project_id, chat_id="", memory_enabled=True, household_write=True,
        force_confirm=False, ask=Asker(), record=events.append, next_id=lambda: next(counter), read_only=read_only,
    )
    b.events = events
    return b


def handler(b, name):
    return next(s for s in b.specs() if s.name == name).handler


def test_project_scope_only_in_project_chats(store):
    pid = store.create_project("dora", "Heizung")["id"]
    plain = next(s for s in box(store).specs() if s.name == "memory_save")
    assert plain.schema["properties"]["scope"]["enum"] == ["household", "person"]
    inside = next(s for s in box(store, project_id=pid).specs() if s.name == "memory_save")
    assert "project" in inside.schema["properties"]["scope"]["enum"]
    with pytest.raises(ToolError):
        run(handler(box(store), "memory_save")({"scope": "project", "topic": "Absprache", "content": "Vorlauf 35 Grad"}))


def test_save_list_forget_project_memory_and_isolation(store):
    pid = store.create_project("dora", "Heizung")["id"]
    other = store.create_project("dora", "Garten")["id"]
    b = box(store, project_id=pid)
    run(handler(b, "memory_save")({"scope": "project", "topic": "Vorlauf", "content": "35 Grad im Keller"}))
    assert store.project_memory_list("dora", pid)[0]["topic"] == "Vorlauf"
    assert store.project_memory_list("dora", other) == []
    assert store.project_memory_list("adm01", pid) is None  # fremdes Projekt
    assert "35 Grad" in run(handler(b, "memory_list")({"scope": "project"}))
    assert "35 Grad" not in run(handler(box(store, project_id=other), "memory_list")({"scope": "all"}))
    run(handler(b, "memory_forget")({"scope": "project", "topic": "vorlauf"}))
    assert store.project_memory_list("dora", pid) == []


def test_context_has_all_three_scopes(store):
    pid = store.create_project("dora", "Heizung")["id"]
    store.memory_save("person", "dora", "Vorliebe", "Dunkles Design", "dora")
    store.memory_save("household", "dora", "Müll", "Dienstag Biotonne", "dora")
    store.project_memory_save("dora", pid, "Vorlauf", "35 Grad", "dora")
    text = box(store, project_id=pid).note([], "none", False)
    assert "Dunkles Design" in text and "Dienstag Biotonne" in text and "35 Grad" in text and "Projektgedächtnis" in text
    outside = box(store).note([], "none", False)
    assert "35 Grad" not in outside and "Projektgedächtnis" not in outside


def test_project_memory_deleted_with_project(store):
    pid = store.create_project("dora", "Heizung")["id"]
    store.project_memory_save("dora", pid, "Vorlauf", "35 Grad", "dora")
    store.delete_project("dora", pid)
    assert store._conn.execute("SELECT COUNT(*) FROM project_memories").fetchone()[0] == 0


def test_project_limit(store):
    pid = store.create_project("dora", "Heizung")["id"]
    for i in range(PROJECT_LIMIT):
        store.project_memory_save("dora", pid, f"Thema {i}", "Inhalt", "dora")
    b = box(store, project_id=pid)
    with pytest.raises(ToolError):
        run(handler(b, "memory_save")({"scope": "project", "topic": "Noch eins", "content": "Inhalt"}))
    run(handler(b, "memory_save")({"scope": "project", "topic": "Thema 3", "content": "Neu"}))  # Aktualisieren geht weiter


def test_origin_said_or_inferred(store):
    b = box(store)
    run(handler(b, "memory_save")({"scope": "person", "topic": "Gesagt", "content": "Ich mag Tee"}))
    run(handler(b, "memory_save")({"scope": "person", "topic": "Geschlossen", "content": "Arbeitet vermutlich im Homeoffice", "source": "inferred"}))
    rows = {r["topic"]: r for r in store.memory_list("person", "dora")}
    assert rows["Gesagt"]["origin"] == "said" and rows["Geschlossen"]["origin"] == "inferred"
    assert rows["Gesagt"]["created_at"] and rows["Gesagt"]["updated_at"]


def test_event_carries_undo_for_save_and_forget(store):
    b = box(store)
    run(handler(b, "memory_save")({"scope": "person", "topic": "Tee", "content": "Mag Tee"}))
    undo = b.events[-1]["undo"]
    assert undo == {"scope": "person", "topic": "Tee", "prev": None, "now": "Mag Tee", "project": ""}
    run(handler(b, "memory_save")({"scope": "person", "topic": "Tee", "content": "Mag grünen Tee"}))
    assert b.events[-1]["undo"]["prev"] == "Mag Tee"
    run(handler(b, "memory_forget")({"scope": "person", "topic": "Tee"}))
    assert b.events[-1]["undo"]["now"] is None and b.events[-1]["undo"]["prev"] == "Mag grünen Tee"
    assert "undo" not in b.events[0]  # der Zwischenstand „läuft“ trägt kein Rückgängig


def test_large_memory_gets_topic_index(store):
    for i in range(60):
        store.memory_save("person", "dora", f"Thema {i:02d}", "x" * 200, "dora")
    text = box(store).note([], "none", False)
    assert "Weitere" in text and "Thema" in text
    assert text.count("x" * 200) < 60  # nicht alles im Wortlaut


def test_undo_endpoint(client, store):
    mem = {"scope": "person", "topic": "Tee", "content": "Mag Tee", "project_id": ""}
    store.memory_save("person", "dora", "Tee", "Mag grünen Tee", "dora", "said")
    h = as_user(DORA, True)
    # zurück auf den vorigen Text
    r = client.post("/api/memory/undo", json={"scope": "person", "topic": "Tee", "prev": "Mag Tee", "now": "Mag grünen Tee"}, headers=h)
    assert r.status_code == 200 and r.json() == {"restored": True}
    assert store.memory_get("person", "dora", "Tee")["content"] == "Mag Tee"
    # zweiter Versuch: der Eintrag ist nicht mehr so wie von der KI hinterlassen
    r = client.post("/api/memory/undo", json={"scope": "person", "topic": "Tee", "prev": "Mag Tee", "now": "Mag grünen Tee"}, headers=h)
    assert r.status_code == 409
    # neu angelegten Eintrag wieder entfernen
    r = client.post("/api/memory/undo", json={"scope": "person", "topic": "Tee", "prev": None, "now": "Mag Tee"}, headers=h)
    assert r.json() == {"restored": False} and store.memory_get("person", "dora", "Tee") is None
    # gelöschten Eintrag wiederherstellen
    r = client.post("/api/memory/undo", json={"scope": "person", "topic": "Kaffee", "prev": "Mag Kaffee", "now": None}, headers=h)
    assert r.status_code == 200 and store.memory_get("person", "dora", "Kaffee")["content"] == "Mag Kaffee"
    assert mem  # nur zur Ruhe des Linters


def test_undo_needs_write_rights_and_own_data(client, store):
    pid = store.create_project("dora", "Heizung")["id"]
    store.project_memory_save("dora", pid, "Vorlauf", "35 Grad", "dora")
    body = {"scope": "project", "topic": "Vorlauf", "prev": None, "now": "35 Grad", "project_id": pid}
    assert client.post("/api/memory/undo", json=body, headers=as_user(DORA)).status_code in (401, 403)  # ohne Schreibzugriff
    assert client.post("/api/memory/undo", json=body, headers=as_user(ADM01, True)).status_code == 404  # fremdes Projekt
    assert store.project_memory_list("dora", pid)
    assert client.post("/api/memory/undo", json=body, headers=as_user(DORA, True)).status_code == 200
    assert store.project_memory_list("dora", pid) == []


def test_api_lists_projects_and_manual_origin(client, store):
    pid = store.create_project("dora", "Heizung")["id"]
    h = as_user(DORA, True)
    r = client.post("/api/memory", json={"scope": "project", "project_id": pid, "topic": "Vorlauf", "content": "35 Grad"}, headers=h)
    assert r.status_code == 200 and r.json()["origin"] == "manual"
    data = client.get("/api/memory", headers=as_user(DORA)).json()
    assert data["projects"] == [{"id": pid, "name": "Heizung", "entries": data["projects"][0]["entries"]}]
    entry = data["projects"][0]["entries"][0]
    assert entry["topic"] == "Vorlauf" and entry["origin"] == "manual"
    assert client.get("/api/memory", headers=as_user(ADM01)).json()["projects"] == []
    # fremdes Projekt: 404, Projekt ohne Angabe: 404
    assert client.post("/api/memory", json={"scope": "project", "project_id": pid, "topic": "Hack", "content": "xyz"}, headers=as_user(ADM01, True)).status_code == 404
    assert client.post("/api/memory", json={"scope": "project", "topic": "Hack", "content": "xyz"}, headers=h).status_code == 404
    assert client.delete(f"/api/projects/{pid}/memory/{entry['id']}", headers=as_user(ADM01, True)).status_code == 404
    assert client.delete(f"/api/projects/{pid}/memory/{entry['id']}", headers=h).status_code == 204


def test_undo_survives_reload(client, store):
    chat = store.create_chat("dora", "Test", None)
    undo = {"scope": "person", "topic": "Tee", "prev": None, "now": "Mag Tee", "project": ""}
    store.add_message("dora", chat["id"], "user", "Merk dir: ich mag Tee")
    store.add_message("dora", chat["id"], "assistant", "Gern.", tools=[{"label": "Gemerkt", "kind": "memory", "status": "ok", "note": "", "undo": undo}])
    tools = client.get(f"/api/chats/{chat['id']}/messages", headers=as_user(DORA)).json()[-1]["tools"]
    assert tools[0]["undo"] == undo
    bad = {"label": "x", "kind": "memory", "status": "ok", "undo": {"scope": "evil", "topic": "x"}}
    store.add_message("dora", chat["id"], "assistant", "Zwei.", tools=[bad])
    assert "undo" not in client.get(f"/api/chats/{chat['id']}/messages", headers=as_user(DORA)).json()[-1]["tools"][0]
