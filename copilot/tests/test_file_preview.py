"""Erzeugte Dateien im Fenster neben dem Chat: Vorschau, Bearbeiten, neue Fassung, Rechte (0.63.1)."""
import pytest

from app import filepreview, outbox
from tests.conftest import ADM01, DORA, as_user


def make(store, name, data, chat=None):
    chat = chat or store.create_chat("dora", "Skripte")["id"]
    meta = store.outfile_add("dora", chat, name, outbox.media_type(name), data, 14)
    return chat, meta["id"]


def test_describe_text_office_and_unknown():
    shown = filepreview.describe("run.ps1", b"\xef\xbb\xbfGet-Date\r\nWrite-Host 'Hallo'\r\n")
    assert shown == {"kind": "text", "content": "Get-Date\nWrite-Host 'Hallo'\n", "truncated": False, "editable": True}
    docx, _ = outbox.render("bericht.docx", "# Titel\n\nEin Absatz mit Inhalt.")
    shown = filepreview.describe("bericht.docx", docx)
    assert shown["kind"] == "extract" and "Ein Absatz" in shown["content"] and shown["editable"] is False
    with pytest.raises(filepreview.PreviewError):
        filepreview.describe("programm.exe", b"MZ")
    with pytest.raises(filepreview.PreviewError, match="UTF-8"):
        filepreview.describe("kaputt.txt", b"\xff\xfe\x00\xd8")
    big = filepreview.describe("gross.log", ("zeile\n" * 60_000).encode())
    assert big["truncated"] is True and big["editable"] is False and len(big["content"]) == filepreview.VIEW_CHARS


def test_encode_keeps_windows_line_endings_and_bom():
    assert filepreview.encode("a.bat", "echo 1\necho 2") == b"echo 1\r\necho 2\r\n"
    assert filepreview.encode("a.ps1", "Get-Date").startswith(b"\xef\xbb\xbf")
    assert filepreview.encode("a.sh", "echo 1") == b"echo 1\n"
    with pytest.raises(filepreview.PreviewError):
        filepreview.encode("a.docx", "Text")


def test_file_text_api_view_edit_and_versions(client, store):
    chat, fid = make(store, "motd.sh", b"#!/bin/sh\necho alt\n")
    got = client.get(f"/api/files/{fid}/text", headers=as_user(DORA))
    body = got.json()
    assert got.status_code == 200 and body["content"] == "#!/bin/sh\necho alt\n" and body["editable"] is True and body["latest_id"] == fid
    assert "no-store" in got.headers["cache-control"]
    # Speichern legt eine neue Fassung unter demselben Namen an
    r = client.put(f"/api/files/{fid}/text", json={"content": "#!/bin/sh\necho neu\r\n"}, headers=as_user(DORA, True))
    assert r.status_code == 200 and r.json()["name"] == "motd.sh" and r.json()["id"] != fid
    new_id = r.json()["id"]
    assert client.get(f"/api/files/{new_id}", headers=as_user(DORA)).content == b"#!/bin/sh\necho neu\n"
    assert [f["id"] for f in store.outfile_list("dora", chat)] == [new_id]
    # die alte Fassung zeigt, dass es eine neuere gibt, und ist nicht mehr bearbeitbar
    old = client.get(f"/api/files/{fid}/text", headers=as_user(DORA)).json()
    assert old["latest_id"] == new_id and old["editable"] is False and old["content"].endswith("echo alt\n")
    assert client.put(f"/api/files/{fid}/text", json={"content": "x"}, headers=as_user(DORA, True)).status_code == 409
    # Prüfungen
    assert client.put(f"/api/files/{new_id}/text", json={"content": "  "}, headers=as_user(DORA, True)).status_code == 422
    assert client.put(f"/api/files/{new_id}/text", json={"content": "x"}, headers=as_user(DORA)).status_code == 403  # ohne Schutz-Header
    assert client.put(f"/api/files/{new_id}/text", json={"content": "x" * (filepreview.EDIT_CHARS + 1)}, headers=as_user(DORA, True)).status_code == 422


def test_file_text_api_rights_and_unsupported(client, store):
    chat, fid = make(store, "geheim.txt", b"Nur fuer Dora")
    assert client.get(f"/api/files/{fid}/text", headers=as_user(ADM01)).status_code == 404
    assert client.put(f"/api/files/{fid}/text", json={"content": "Fremd"}, headers=as_user(ADM01, True)).status_code == 404
    assert client.get("/api/files/nicht-gueltig/text", headers=as_user(DORA)).status_code in (404, 422)
    assert client.get(f"/api/files/{'0' * 32}/text", headers=as_user(DORA)).status_code == 404
    # Office-Dateien: Text lesen ja, schreiben nein
    docx, _ = outbox.render("bericht.docx", "# Titel\n\nInhalt")
    _, did = make(store, "bericht.docx", docx, chat)
    shown = client.get(f"/api/files/{did}/text", headers=as_user(DORA)).json()
    assert shown["kind"] == "extract" and shown["editable"] is False
    assert client.put(f"/api/files/{did}/text", json={"content": "x"}, headers=as_user(DORA, True)).status_code == 422
    # abgelaufen
    with store._lock, store._conn:
        store._conn.execute("UPDATE outfiles SET expires_at = '2000-01-01T00:00:00+00:00'")
    assert client.get(f"/api/files/{fid}/text", headers=as_user(DORA)).status_code == 404
