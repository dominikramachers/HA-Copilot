"""Artefakte: Werkzeuge der KI, Versionen, Schnittstellen und Sicherheit."""
import asyncio

import pytest

from app import artifacts as art
from app.ha_tools import ToolError
from conftest import ADM01, DORA, WRITE, FakeBackend, as_user

H = {**as_user(ADM01), **WRITE}


def box(store, chat="c1", profile="adm01"):
    events = []
    ids = iter(range(1, 100))
    return art.ArtifactToolbox(store, profile, chat, record=events.append, next_id=lambda: next(ids)), events


@pytest.fixture()
def chat(store):
    return store.create_chat("adm01", "Test", None)["id"]


def run(coro):
    return asyncio.run(coro)


def test_create_update_and_read(store, chat):
    tools, events = box(store, chat)
    made = run(tools.create({"title": "Plan", "kind": "markdown", "content": "# Plan\n\nA\nB"}))
    assert "id " in made
    item = store.artifact_list("adm01", chat)[0]
    assert item["version"] == 1 and item["kind"] == "markdown"
    assert events[-1]["artifact"] == {"id": item["id"], "title": "Plan", "kind": "markdown", "language": "", "version": 1}
    run(tools.update({"id": item["id"], "edits": [{"old": "A\nB", "new": "A\nB\nC"}], "note": "C ergänzt"}))
    got = store.artifact_get("adm01", item["id"])
    assert got["version"] == 2 and got["content"].endswith("C") and got["versions"][-1]["note"] == "C ergänzt" and got["versions"][-1]["by"] == "ai"
    assert store.artifact_get("adm01", item["id"], 1)["content"] == "# Plan\n\nA\nB"
    assert "A\nB\nC" in run(tools.read({"id": item["id"]}))
    assert "Keine Änderung" in run(tools.update({"id": item["id"], "content": got["content"]}))
    assert store.artifact_get("adm01", item["id"])["version"] == 2


def test_edits_must_match_exactly_once(store, chat):
    tools, events = box(store, chat)
    run(tools.create({"title": "T", "kind": "code", "language": "python", "content": "x = 1\nx = 1\ny = 2"}))
    art_id = store.artifact_list("adm01", chat)[0]["id"]
    with pytest.raises(ToolError, match="2×"):
        run(tools.update({"id": art_id, "edits": [{"old": "x = 1", "new": "x = 3"}]}))
    with pytest.raises(ToolError, match="nicht vor"):
        run(tools.update({"id": art_id, "edits": [{"old": "z", "new": "q"}]}))
    with pytest.raises(ToolError, match="beides"):
        run(tools.update({"id": art_id, "edits": [{"old": "y", "new": "z"}], "content": "x"}))
    assert store.artifact_get("adm01", art_id)["version"] == 1  # nichts halb geändert
    assert events[-1]["status"] == "error"
    run(tools.update({"id": art_id, "edits": [{"old": "y = 2", "new": "y = 5"}, {"old": "y = 5", "new": "y = 6"}]}))
    assert store.artifact_get("adm01", art_id)["content"].endswith("y = 6")


def test_validation(store, chat):
    tools, _ = box(store, chat)
    for bad in (
        {"title": "", "kind": "html", "content": "<p>x"},
        {"title": "T", "kind": "pdf", "content": "x"},
        {"title": "T", "kind": "html", "content": "   "},
        {"title": "T", "kind": "html", "content": "x" * (art.CONTENT_MAX + 1)},
        {"title": "T", "kind": "code", "language": "py thon!", "content": "x"},
        {"title": "T<b>", "kind": "html", "content": "x"},
        {"title": "T", "kind": "svg", "content": "<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"},
        {"title": "T", "kind": "svg", "content": "kein svg"},
    ):
        with pytest.raises(ToolError):
            run(tools.create(bad))
    assert store.artifact_list("adm01", chat) == []
    run(tools.create({"title": "Bild", "kind": "svg", "content": "<svg width='10' height='10'><rect width='5' height='5'/></svg>"}))
    assert 'xmlns="http://www.w3.org/2000/svg"' in store.artifact_get("adm01", store.artifact_list("adm01", chat)[0]["id"])["content"]


def test_limit_per_chat(store, chat):
    tools, _ = box(store, chat)
    for n in range(art.MAX_PER_CHAT):
        run(tools.create({"title": f"A{n}", "kind": "markdown", "content": f"x{n}"}))
    with pytest.raises(ToolError, match="schon"):
        run(tools.create({"title": "Zu viel", "kind": "markdown", "content": "x"}))


def test_only_artifacts_of_this_chat(store, chat):
    other = store.create_chat("adm01", "Anderer", None)["id"]
    tools, _ = box(store, chat)
    run(tools.create({"title": "A", "kind": "markdown", "content": "x"}))
    art_id = store.artifact_list("adm01", chat)[0]["id"]
    elsewhere, _ = box(store, other)
    for call in (elsewhere.read({"id": art_id}), elsewhere.update({"id": art_id, "content": "y"})):
        with pytest.raises(ToolError):
            run(call)
    foreign, _ = box(store, chat, profile="dora")
    with pytest.raises(ToolError):
        run(foreign.read({"id": art_id}))


def test_versions_are_capped(store, chat):
    tools, _ = box(store, chat)
    run(tools.create({"title": "A", "kind": "markdown", "content": "v1"}))
    art_id = store.artifact_list("adm01", chat)[0]["id"]
    for n in range(2, store.ARTIFACT_VERSIONS_MAX + 6):
        store.artifact_update("adm01", art_id, f"v{n}")
    got = store.artifact_get("adm01", art_id)
    assert len(got["versions"]) == store.ARTIFACT_VERSIONS_MAX and got["versions"][0]["n"] == 6 and got["version"] == store.ARTIFACT_VERSIONS_MAX + 5


def test_api_is_private_and_downloads_safely(client, store):
    chat = store.create_chat("adm01", "Chat", None)["id"]
    made = store.artifact_create("adm01", chat, "html", "", "Meine Seite: 1", "<h1>Hallo</h1><script>1</script>")
    mine = client.get(f"/api/artifacts/{made['id']}", headers=as_user(ADM01)).json()
    assert mine["content"].startswith("<h1>") and mine["chat_title"] == "Chat" and mine["version"] == 1 and mine["latest"] == 1
    assert client.get(f"/api/artifacts/{made['id']}", headers=as_user(DORA)).status_code == 404
    assert client.get(f"/api/artifacts/{made['id']}?version=9", headers=as_user(ADM01)).status_code == 404
    assert client.get(f"/api/chats/{chat}/artifacts", headers=as_user(DORA)).status_code == 404
    listed = client.get(f"/api/chats/{chat}/artifacts", headers=as_user(ADM01)).json()
    assert [a["id"] for a in listed] == [made["id"]] and "content" not in listed[0]
    dl = client.get(f"/api/artifacts/{made['id']}/download", headers=as_user(ADM01))
    assert dl.status_code == 200 and dl.headers["x-content-type-options"] == "nosniff" and "sandbox" in dl.headers["content-security-policy"]
    assert dl.headers["content-disposition"].startswith("attachment; filename*=UTF-8''Meine-Seite-1.html")
    assert client.get(f"/api/artifacts/{made['id']}/download", headers=as_user(DORA)).status_code == 404
    assert client.delete(f"/api/artifacts/{made['id']}", headers=as_user(ADM01)).status_code == 403  # ohne Schreibkopf
    assert client.delete(f"/api/artifacts/{made['id']}", headers={**as_user(DORA), **WRITE}).status_code == 404
    assert client.delete(f"/api/artifacts/{made['id']}", headers=H).status_code == 204
    assert client.get(f"/api/artifacts/{made['id']}", headers=as_user(ADM01)).status_code == 404


def test_deleting_the_chat_deletes_its_artifacts(client, store):
    chat = store.create_chat("adm01", "Chat", None)["id"]
    made = store.artifact_create("adm01", chat, "markdown", "", "A", "x")
    assert client.delete(f"/api/chats/{chat}", headers=H).status_code in (200, 204)
    assert store.artifact_get("adm01", made["id"]) is None


class ArtifactBackend(FakeBackend):
    """Ruft wie die KI das Werkzeug auf, während sie antwortet."""

    async def stream(self, history, message, effort, tools=None, **kwargs):
        async for piece in super().stream(history, message, effort, tools=tools, **kwargs):
            yield piece
        spec = next(t for t in tools if t.name == "artifact_create")
        await spec.handler({"title": "Seite", "kind": "html", "content": "<p>hi</p>"})


def test_send_flow_offers_the_tools_and_keeps_the_card(store):
    from fastapi.testclient import TestClient
    from app.config import parse_settings
    from app.main import build_ingress_app
    from conftest import RAW
    backend = ArtifactBackend(pieces=["Fertig."])
    app = TestClient(build_ingress_app(parse_settings(RAW, frozenset({"testclient"})), store, backend))
    chat = app.post("/api/chats", headers=H, json={}).json()["id"]
    assert app.post(f"/api/chats/{chat}/send", headers=H, json={"content": "Mach eine Seite"}).status_code == 200
    call = backend.calls[-1]
    assert {"artifact_create", "artifact_update", "artifact_read"} <= {t.name for t in call["tools"]}
    assert "Artefakte" in call["note"]
    last = app.get(f"/api/chats/{chat}/messages", headers=H).json()[-1]
    card = next(t["artifact"] for t in last["tools"] if t.get("artifact"))
    assert card["title"] == "Seite" and card["kind"] == "html" and card["version"] == 1
    assert app.get(f"/api/artifacts/{card['id']}", headers=H).json()["content"] == "<p>hi</p>"
    backend.pieces = ["Noch eine."]
    app.post(f"/api/chats/{chat}/send", headers=H, json={"content": "Und weiter"})
    assert f"{card['id']}: „Seite“" in backend.calls[-1]["note"]  # die KI kennt die vorhandenen Artefakte


# --- Paket E2: selbst bearbeiten, wiederherstellen, im Projekt ablegen -------------------------------------------------

def test_user_edit_creates_a_version_by_the_user(client, store):
    chat = store.create_chat("adm01", "Chat", None)["id"]
    made = store.artifact_create("adm01", chat, "markdown", "", "Plan", "eins")
    url = f"/api/artifacts/{made['id']}"
    assert client.put(url, headers=as_user(ADM01), json={"content": "zwei"}).status_code == 403  # ohne Schreibkopf
    assert client.put(url, headers={**as_user(DORA), **WRITE}, json={"content": "zwei"}).status_code == 404
    got = client.put(url, headers=H, json={"content": "zwei"}).json()
    assert got["version"] == 2 and got["content"] == "zwei" and got["versions"][-1]["by"] == "user"
    assert store.artifact_list("adm01", chat)[0]["last_by"] == "user"
    assert client.put(url, headers=H, json={"content": "zwei"}).json()["version"] == 2  # gleicher Inhalt: keine neue Version
    assert client.put(url, headers=H, json={"title": "Neuer Titel"}).json()["title"] == "Neuer Titel"
    assert client.put(url, headers=H, json={}).status_code == 422
    assert client.put(url, headers=H, json={"content": "   "}).status_code == 422
    assert client.put(url, headers=H, json={"title": "a<b>"}).status_code == 422
    assert client.put(url, headers=H, json={"content": "x" * (art.CONTENT_MAX + 1)}).status_code == 422


def test_user_edit_of_svg_is_checked(client, store):
    chat = store.create_chat("adm01", "Chat", None)["id"]
    made = store.artifact_create("adm01", chat, "svg", "", "Bild", "<svg xmlns='http://www.w3.org/2000/svg'><rect width='1' height='1'/></svg>")
    bad = client.put(f"/api/artifacts/{made['id']}", headers=H, json={"content": "<svg xmlns='http://www.w3.org/2000/svg'><script>1</script></svg>"})
    assert bad.status_code == 422
    assert store.artifact_get("adm01", made["id"])["version"] == 1


def test_large_edit_passes_the_body_limit(client, store):
    chat = store.create_chat("adm01", "Chat", None)["id"]
    made = store.artifact_create("adm01", chat, "code", "text", "Lang", "a")
    big = "ä" * 100_000  # über 128 KB als Anfragetext, aber unter der Zeichengrenze
    assert client.put(f"/api/artifacts/{made['id']}", headers=H, json={"content": big}).status_code == 200


def test_restore_makes_an_old_version_current_again(client, store):
    chat = store.create_chat("adm01", "Chat", None)["id"]
    made = store.artifact_create("adm01", chat, "code", "python", "Skript", "v1")
    store.artifact_update("adm01", made["id"], "v2")
    url = f"/api/artifacts/{made['id']}"
    got = client.put(url, headers=H, json={"restore": 1}).json()
    assert got["version"] == 3 and got["content"] == "v1" and got["versions"][-1]["by"] == "user"
    assert client.put(url, headers=H, json={"restore": 9}).status_code == 404
    assert [v["n"] for v in store.artifact_get("adm01", made["id"])["versions"]] == [1, 2, 3]  # nichts geht verloren


def test_the_ai_is_told_when_the_user_changed_an_artifact(store, chat):
    made = store.artifact_create("adm01", chat, "markdown", "", "Plan", "eins")
    assert "selbst geändert" not in art.rules_note(store.artifact_list("adm01", chat))
    store.artifact_update("adm01", made["id"], "zwei", "", "user")
    assert "zuletzt vom Nutzer selbst geändert" in art.rules_note(store.artifact_list("adm01", chat))
    store.artifact_update("adm01", made["id"], "drei", "", "ai")
    assert "selbst geändert" not in art.rules_note(store.artifact_list("adm01", chat))


def test_put_in_the_project(client, store):
    project = store.create_project("adm01", "Projekt")["id"]
    chat = store.create_chat("adm01", "Chat", project)["id"]
    made = store.artifact_create("adm01", chat, "code", "yaml", "Konfig", "a: 1")
    url = f"/api/artifacts/{made['id']}/to-project"
    assert client.post(url, headers=as_user(ADM01)).status_code == 403
    assert client.post(url, headers={**as_user(DORA), **WRITE}).status_code == 404
    first = client.post(url, headers=H).json()
    assert first == {"name": "Artefakte/Konfig.yaml", "replaced": False, "project_id": project}
    store.artifact_update("adm01", made["id"], "a: 2")
    assert client.post(url, headers=H).json()["replaced"] is True
    files = store.list_knowledge("adm01", project)
    assert [f["name"] for f in files] == ["Artefakte/Konfig.yaml"]
    assert store.get_knowledge("adm01", project, "Artefakte/Konfig.yaml") == "a: 2"


def test_without_a_project_nothing_is_put_away(client, store):
    chat = store.create_chat("adm01", "Chat", None)["id"]
    made = store.artifact_create("adm01", chat, "markdown", "", "A", "x")
    assert client.post(f"/api/artifacts/{made['id']}/to-project", headers=H).status_code == 409
