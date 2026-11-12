"""Dateien im Projekt: Originale bleiben erhalten, die KI legt Dateien und Artefakte ab, nichts Fremdes wird überschrieben."""
import asyncio
import io
import zipfile

import pytest

from app import projectfiles as pf
from app.context_tools import ContextToolbox
from app.ha_tools import ToolError
from tests.conftest import ADM01, DORA, as_user
from tests.test_knowledge_memory import Asker, project, upload

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def run(coro):
    return asyncio.run(coro)


def docx_bytes(text="Angebot Heizung"):
    from docx import Document
    buf = io.BytesIO()
    doc = Document()
    doc.add_paragraph(text)
    doc.save(buf)
    return buf.getvalue()


def box(store, pid, chat_id, asker=None):
    events, counter = [], iter(range(1, 1000))
    b = ContextToolbox(
        store, "dora", "Dora", project_id=pid, chat_id=chat_id, memory_enabled=True, household_write=True,
        force_confirm=False, ask=asker or Asker(), record=events.append, next_id=lambda: next(counter),
    )
    b.events = events
    return b


def handler(b, name):
    return next(s for s in b.specs() if s.name == name).handler


def test_upload_keeps_the_original_and_serves_it_back(client, store):
    pid = project(client)
    r = upload(client, pid, "angebot.docx", docx_bytes())
    assert r.status_code == 200 and r.json()["added"] == ["angebot.docx"]
    entry = client.get(f"/api/projects/{pid}/knowledge", headers=as_user(DORA)).json()["files"][0]
    assert entry["has_file"] and entry["origin"] == "upload" and "Heizung" in store.knowledge_texts("dora", pid)[0][1]
    got = client.get(f"/api/projects/{pid}/knowledge/{entry['id']}/file", headers=as_user(DORA))
    assert got.status_code == 200 and got.content == docx_bytes() and "attachment" in got.headers["content-disposition"]
    assert "sandbox" in got.headers["content-security-policy"]
    # fremde Person kommt nicht an das Original
    assert client.get(f"/api/projects/{pid}/knowledge/{entry['id']}/file", headers=as_user(ADM01)).status_code == 404


def test_image_without_text_is_kept_with_placeholder(client, store):
    pid = project(client)
    r = upload(client, pid, "foto.png", PNG)
    assert r.status_code == 200 and r.json()["no_text"] == ["foto.png"]
    name, text = store.knowledge_texts("dora", pid)[0]
    assert name == "foto.png" and "kein durchsuchbarer Text" in text
    entry = client.get(f"/api/projects/{pid}/knowledge", headers=as_user(DORA)).json()["files"][0]
    assert client.get(f"/api/projects/{pid}/knowledge/{entry['id']}/file", headers=as_user(DORA)).content == PNG


def test_plain_text_and_zip_uploads_still_work(client):
    pid = project(client)
    assert upload(client, pid, "notiz.md", b"# Notiz").json()["added"] == ["notiz.md"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.md", "Alpha")
    assert upload(client, pid, "paket.zip", buf.getvalue()).json()["added"] == ["a.md"]


def test_delete_and_project_delete_remove_originals(client, store):
    pid = project(client)
    upload(client, pid, "a.docx", docx_bytes())
    upload(client, pid, "b.png", PNG)
    ids = [r["file_id"] for r in store._conn.execute("SELECT file_id FROM knowledge")]
    assert len(ids) == 2 and all(store._pfile_path(i).is_file() for i in ids)
    entry = client.get(f"/api/projects/{pid}/knowledge", headers=as_user(DORA)).json()["files"][0]
    client.delete(f"/api/projects/{pid}/knowledge/{entry['id']}", headers=as_user(DORA, True))
    assert sum(store._pfile_path(i).is_file() for i in ids) == 1
    client.delete(f"/api/projects/{pid}", headers=as_user(DORA, True))
    assert not any(store._pfile_path(i).is_file() for i in ids)


def test_file_card_button_saves_generated_file(client, store):
    pid = project(client)
    chat = store.create_chat("dora", "Angebot", pid)["id"]
    made = store.outfile_add("dora", chat, "preis.xlsx", "application/octet-stream", b"PK\x03\x04bin", 14)
    r = client.post(f"/api/chats/{chat}/files/{made['id']}/to-project", headers=as_user(DORA, True))
    assert r.status_code == 200 and r.json() == {"name": "preis.xlsx", "replaced": False, "has_text": False}
    assert store.knowledge_entry("dora", pid, "PREIS.xlsx")["origin"] == "ai"
    again = client.post(f"/api/chats/{chat}/files/{made['id']}/to-project", headers=as_user(DORA, True))
    assert again.json()["replaced"] is True
    # Chat ohne Projekt, fremde Person, ohne Schutz-Header
    loose = store.create_chat("dora", "Lose")["id"]
    other = store.outfile_add("dora", loose, "x.txt", "text/plain", b"hallo", 14)
    assert client.post(f"/api/chats/{loose}/files/{other['id']}/to-project", headers=as_user(DORA, True)).status_code == 422
    assert client.post(f"/api/chats/{chat}/files/{made['id']}/to-project", headers=as_user(ADM01, True)).status_code == 404
    assert client.post(f"/api/chats/{chat}/files/{made['id']}/to-project", headers=as_user(DORA)).status_code == 403
    assert client.post(f"/api/chats/{chat}/files/{other['id']}/to-project", headers=as_user(DORA, True)).status_code == 404  # Datei eines anderen Chats


def test_tool_saves_generated_file_and_text_artifact(store):
    pid = store.create_project("dora", "Haus")["id"]
    chat = store.create_chat("dora", "Chat", pid)["id"]
    store.outfile_add("dora", chat, "angebot.docx", "application/octet-stream", docx_bytes("Angebot Heizung"), 14)
    b = box(store, pid, chat)
    assert "project_file_save" in {s.name for s in b.specs()}
    out = run(handler(b, "project_file_save")({"file": "angebot.docx"}))
    assert "Abgelegt im Projekt: angebot.docx" in out
    assert any("Heizung" in t for n, t in store.knowledge_texts("dora", pid) if n == "angebot.docx")  # durchsuchbar
    page = run(handler(b, "project_file_save")({"name": "seite.html", "content": "<h1>Hallo</h1>"}))
    assert "Artefakte/seite.html" in page
    assert store.knowledge_entry("dora", pid, "Artefakte/seite.html")["origin"] == "ai"
    assert "Ersetzt" in run(handler(b, "project_file_save")({"name": "seite.html", "content": "<h1>Neu</h1>"}))
    assert b.events[-1]["kind"] == "knowledge-write"


def test_tool_refuses_bad_requests(store):
    pid = store.create_project("dora", "Haus")["id"]
    chat = store.create_chat("dora", "Chat", pid)["id"]
    b = box(store, pid, chat)
    h = handler(b, "project_file_save")
    for args, match in [
        ({"file": "gibtsnicht.docx"}, "Dateien des Chats"),
        ({"file": "a", "content": "text"}, "nicht beides"),
        ({"name": "x.docx", "content": "text text"}, "Endungen"),
        ({"content": "text text"}, "name fehlt"),
        ({"name": "x.md", "content": "sk-ant-api03-abcdefghijklmnopqrstuvwxyz"}, "Zugangsdaten"),
    ]:
        with pytest.raises(ToolError, match=match):
            run(h(args))
    # nur in Projekt-Chats und nie in geplanten Aufgaben
    assert "project_file_save" not in {s.name for s in box(store, None, chat).specs()}
    ro = ContextToolbox(store, "dora", "Dora", project_id=pid, chat_id=chat, memory_enabled=True, household_write=False, force_confirm=True,
                        ask=Asker(), record=lambda e: None, next_id=lambda: 1, read_only=True)
    assert "project_file_save" not in {s.name for s in ro.specs()}


def test_ai_never_overwrites_uploaded_files(client, store):
    pid = project(client)
    upload(client, pid, "preise.docx", docx_bytes("Original"))
    chat = store.create_chat("dora", "Chat", pid)["id"]
    store.outfile_add("dora", chat, "preise.docx", "application/octet-stream", docx_bytes("KI-Fassung"), 14)
    with pytest.raises(ToolError, match="nicht überschrieben"):
        run(handler(box(store, pid, chat), "project_file_save")({"file": "preise.docx"}))
    assert "Original" in store.knowledge_texts("dora", pid)[0][1]
    # unter anderem Namen geht es
    assert "Abgelegt" in run(handler(box(store, pid, chat), "project_file_save")({"file": "preise.docx", "name": "preise-neu.docx"}))
    # knowledge_save überschreibt keine Datei mit Original
    store.add_knowledge("dora", pid, "KI/x.docx", "text", data=b"abc", mime="x", origin="ai")
    with pytest.raises(ToolError, match="gespeichertes Original"):
        run(handler(box(store, pid, chat), "knowledge_save")({"name": "x.docx", "content": "neu neu"}))


def test_limits(store, monkeypatch):
    pid = store.create_project("dora", "Haus")["id"]
    monkeypatch.setattr(pf, "FILE_MAX_BYTES", 10)
    with pytest.raises(pf.ProjectFileError, match="zu groß"):
        pf.save(store, "dora", pid, "a.bin", b"x" * 11, origin="ai")
    monkeypatch.setattr(pf, "FILE_MAX_BYTES", 1000)
    monkeypatch.setattr(pf, "PROJECT_MAX_BYTES", 15)
    pf.save(store, "dora", pid, "a.bin", b"x" * 10, origin="ai")
    with pytest.raises(pf.ProjectFileError, match="Speicher"):
        pf.save(store, "dora", pid, "b.bin", b"x" * 10, origin="ai")
    pf.save(store, "dora", pid, "a.bin", b"y" * 12, origin="ai")  # Ersetzen zählt die alte Fassung nicht doppelt
    with pytest.raises(pf.ProjectFileError, match="ungültig"):
        pf.save(store, "dora", pid, "../", b"x", origin="ai")
