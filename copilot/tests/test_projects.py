"""Projekte, Anheften, Verschieben und automatische Titel."""
import sqlite3

import pytest

from app.backend import EchoBackend, clean_title
from tests.conftest import ADM01, DORA, as_user


def make_chat(client, user=DORA, **body):
    r = client.post("/api/chats", json=body, headers=as_user(user, True))
    assert r.status_code == 201, r.text
    return r.json()


def make_project(client, name="Haus", user=DORA):
    r = client.post("/api/projects", json={"name": name}, headers=as_user(user, True))
    assert r.status_code == 201, r.text
    return r.json()


def test_project_lifecycle(client):
    project = make_project(client, "  Wohnzimmer   Umbau ")
    assert project["name"] == "Wohnzimmer Umbau"
    assert project["pinned"] is False

    r = client.patch(f"/api/projects/{project['id']}", json={"pinned": True, "name": "Umbau"},
                     headers=as_user(DORA, True))
    assert r.json()["pinned"] is True and r.json()["name"] == "Umbau"

    listed = client.get("/api/projects", headers=as_user(DORA)).json()
    assert [p["name"] for p in listed] == ["Umbau"]

    assert client.delete(f"/api/projects/{project['id']}", headers=as_user(DORA, True)).status_code == 204
    assert client.get("/api/projects", headers=as_user(DORA)).json() == []


def test_chat_pin_and_move(client):
    project = make_project(client)
    chat = make_chat(client)
    assert chat["pinned"] is False and chat["project_id"] is None

    r = client.patch(f"/api/chats/{chat['id']}", json={"pinned": True, "project_id": project["id"]},
                     headers=as_user(DORA, True))
    assert r.json()["pinned"] is True and r.json()["project_id"] == project["id"]
    # Titel blieb unverändert, weil nicht mitgeschickt
    assert r.json()["title"] == "Neuer Chat"

    # nur den Titel ändern lässt das Projekt in Ruhe
    r = client.patch(f"/api/chats/{chat['id']}", json={"title": "Neu"}, headers=as_user(DORA, True))
    assert r.json()["project_id"] == project["id"]

    # explizites null nimmt den Chat aus dem Projekt
    r = client.patch(f"/api/chats/{chat['id']}", json={"project_id": None}, headers=as_user(DORA, True))
    assert r.json()["project_id"] is None and r.json()["pinned"] is True


def test_chat_created_inside_project(client):
    project = make_project(client)
    chat = make_chat(client, project_id=project["id"])
    assert chat["project_id"] == project["id"]


def test_deleting_project_keeps_chats(client):
    project = make_project(client)
    chat = make_chat(client, project_id=project["id"])
    client.delete(f"/api/projects/{project['id']}", headers=as_user(DORA, True))
    chats = client.get("/api/chats", headers=as_user(DORA)).json()
    assert [c["id"] for c in chats] == [chat["id"]]
    assert chats[0]["project_id"] is None


def test_projects_are_isolated_between_profiles(client):
    mine = make_project(client, "Meins", DORA)
    foreign_chat = make_chat(client, ADM01)
    mine_chat = make_chat(client, DORA)

    assert client.get("/api/projects", headers=as_user(ADM01)).json() == []
    h = as_user(ADM01, True)
    assert client.patch(f"/api/projects/{mine['id']}", json={"name": "x"}, headers=h).status_code == 404
    assert client.delete(f"/api/projects/{mine['id']}", headers=h).status_code == 404
    # fremdes Projekt weder beim Anlegen noch beim Verschieben verwenden
    assert client.post("/api/chats", json={"project_id": mine["id"]}, headers=h).status_code == 404
    r = client.patch(f"/api/chats/{foreign_chat['id']}", json={"project_id": mine["id"]}, headers=h)
    assert r.status_code == 404
    # und umgekehrt: fremden Chat nicht anfassen
    r = client.patch(f"/api/chats/{mine_chat['id']}", json={"pinned": True}, headers=h)
    assert r.status_code == 404
    assert client.get("/api/projects", headers=as_user(DORA)).json()[0]["name"] == "Meins"


def test_database_rejects_foreign_project(store):
    project = store.create_project("dora", "Meins")
    chat = store.create_chat("adm01")
    with pytest.raises(sqlite3.IntegrityError):
        with store._conn:
            store._conn.execute("UPDATE chats SET project_id = ? WHERE id = ?", (project["id"], chat["id"]))
    with pytest.raises(sqlite3.IntegrityError):
        with store._conn:
            store._conn.execute(
                "INSERT INTO chats (id, profile_id, title, created_at, updated_at, project_id) "
                "VALUES ('x', 'adm01', 't', '2026-01-01', '2026-01-01', ?)",
                (project["id"],),
            )


def test_migration_keeps_old_database(tmp_path):
    from app.db import Store

    path = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE profiles (id TEXT PRIMARY KEY, entra_oid TEXT UNIQUE, created_at TEXT NOT NULL DEFAULT '');
        CREATE TABLE chats (id TEXT PRIMARY KEY, profile_id TEXT NOT NULL REFERENCES profiles(id),
            title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE (id, profile_id));
        INSERT INTO profiles (id) VALUES ('dora');
        INSERT INTO chats VALUES ('c1', 'dora', 'Alt', '2026-01-01', '2026-01-02');
        """
    )
    conn.commit()
    conn.close()
    store = Store(path)
    try:
        chat = store.get_chat("dora", "c1")
        assert chat["title"] == "Alt" and chat["pinned"] is False and chat["project_id"] is None
        project = store.create_project("dora", "P")
        assert store.move_chat("dora", "c1", project["id"])
    finally:
        store.close()


class TitleBackend:
    def __init__(self, title="Heizung im Keller"):
        self._title = title
        self.calls = 0

    async def stream(self, history, message, effort, **_):
        yield "Antwort"

    async def title(self, user_text, answer):
        self.calls += 1
        return self._title


@pytest.fixture()
def title_client(store):
    from fastapi.testclient import TestClient

    from app.config import parse_settings
    from app.main import build_ingress_app
    from tests.conftest import RAW

    backend = TitleBackend()
    settings = parse_settings(RAW, frozenset({"testclient"}))
    return TestClient(build_ingress_app(settings, store, backend)), backend


def first_exchange(client, text="Wie stelle ich die Heizung im Keller richtig ein, damit es nicht schimmelt?"):
    chat = make_chat(client)
    r = client.post(f"/api/chats/{chat['id']}/send", json={"content": text}, headers=as_user(DORA, True))
    assert r.status_code == 200
    return chat["id"]


def test_ai_title_replaces_provisional_title(title_client):
    client, backend = title_client
    chat_id = first_exchange(client)
    before = client.get("/api/chats", headers=as_user(DORA)).json()[0]["title"]
    assert before.startswith("Wie stelle ich die Heizung")
    r = client.post(f"/api/chats/{chat_id}/title", headers=as_user(DORA, True))
    assert r.status_code == 200 and r.json()["title"] == "Heizung im Keller"
    # zweiter Aufruf verändert nichts mehr und fragt die KI nicht erneut
    client.post(f"/api/chats/{chat_id}/title", headers=as_user(DORA, True))
    assert backend.calls == 1


def test_ai_title_never_overwrites_custom_title(title_client):
    client, backend = title_client
    chat_id = first_exchange(client)
    client.patch(f"/api/chats/{chat_id}", json={"title": "Mein Titel"}, headers=as_user(DORA, True))
    r = client.post(f"/api/chats/{chat_id}/title", headers=as_user(DORA, True))
    assert r.json()["title"] == "Mein Titel" and backend.calls == 0


def test_title_endpoint_without_backend_support(client):
    chat_id = first_exchange(client)
    before = client.get("/api/chats", headers=as_user(DORA)).json()[0]["title"]
    r = client.post(f"/api/chats/{chat_id}/title", headers=as_user(DORA, True))
    assert r.status_code == 200 and r.json()["title"] == before


def test_title_endpoint_is_profile_scoped(title_client):
    client, _ = title_client
    chat_id = first_exchange(client)
    assert client.post(f"/api/chats/{chat_id}/title", headers=as_user(ADM01, True)).status_code == 404


def test_title_failure_keeps_provisional(store):
    from fastapi.testclient import TestClient

    from app.config import parse_settings
    from app.main import build_ingress_app
    from tests.conftest import RAW

    class Broken(TitleBackend):
        async def title(self, user_text, answer):
            raise RuntimeError("boom")

    settings = parse_settings(RAW, frozenset({"testclient"}))
    client = TestClient(build_ingress_app(settings, store, Broken()))
    chat_id = first_exchange(client, "Kurze Frage")
    r = client.post(f"/api/chats/{chat_id}/title", headers=as_user(DORA, True))
    assert r.status_code == 200 and r.json()["title"] == "Kurze Frage"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('"Heizung im Keller"', "Heizung im Keller"),
        ("Titel: Backup prüfen.", "Backup prüfen"),
        ("**Tunnel einrichten**\nErklärung folgt", "Tunnel einrichten"),
        ("  ", None),
        (None, None),
        ("Ein sehr langer Titel der weit über die erlaubte Länge hinausgeht", "Ein sehr langer Titel der weit über die"),
    ],
)
def test_clean_title(raw, expected):
    result = clean_title(raw)
    assert result == expected or (expected and result and len(result) <= 40 and expected.startswith(result))


def test_echo_backend_title():
    import asyncio

    title = asyncio.run(EchoBackend().title("Wie geht das mit dem Backup heute eigentlich", "x"))
    assert title == "Wie geht das mit dem"


def test_project_instructions_reach_the_backend(client, backend):
    from conftest import ADM01, as_user

    write = as_user(ADM01, True)
    project = client.post("/api/projects", json={"name": "Smarthome"}, headers=write).json()
    assert project["instructions"] == ""
    updated = client.patch(
        f"/api/projects/{project['id']}", json={"instructions": "  Antworte knapp.  "}, headers=write
    ).json()
    assert updated["instructions"] == "Antworte knapp."
    assert client.get("/api/projects", headers=as_user(ADM01)).json()[0]["instructions"] == "Antworte knapp."

    inside = client.post("/api/chats", json={"project_id": project["id"]}, headers=write).json()["id"]
    outside = client.post("/api/chats", json={}, headers=write).json()["id"]
    client.post(f"/api/chats/{inside}/send", json={"content": "Hallo"}, headers=write)
    client.post(f"/api/chats/{outside}/send", json={"content": "Hallo"}, headers=write)
    assert backend.calls[0]["instructions"] == "Antworte knapp."
    assert backend.calls[1]["instructions"] is None  # Chat ohne Projekt bekommt keine

    client.patch(f"/api/projects/{project['id']}", json={"instructions": ""}, headers=write)
    client.post(f"/api/chats/{inside}/send", json={"content": "Nochmal"}, headers=write)
    assert backend.calls[2]["instructions"] is None


def test_project_instructions_are_limited_and_isolated(client):
    from conftest import ADM01, DORA, as_user

    project = client.post("/api/projects", json={"name": "P"}, headers=as_user(ADM01, True)).json()
    too_long = client.patch(
        f"/api/projects/{project['id']}", json={"instructions": "x" * 4001}, headers=as_user(ADM01, True)
    )
    assert too_long.status_code == 422
    foreign = client.patch(
        f"/api/projects/{project['id']}", json={"instructions": "fremd"}, headers=as_user(DORA, True)
    )
    assert foreign.status_code == 404


def test_system_prompt_composition():
    from app.backend import SYSTEM_PROMPT, compose_system

    assert compose_system(None) == SYSTEM_PROMPT and compose_system("  ") == SYSTEM_PROMPT
    text = compose_system("Sprich Schwäbisch.")
    assert text.startswith(SYSTEM_PROMPT) and text.endswith("Sprich Schwäbisch.")
