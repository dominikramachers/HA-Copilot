"""Echte Vorschau für Word, Excel und PDF, Fassungen durchblättern und wiederherstellen (0.65.0)."""
import datetime
import io
import shutil

import pytest
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from app import filepages, outbox
from tests.conftest import ADM01, DORA, as_user

needs_office = pytest.mark.skipif(not shutil.which("soffice") and not shutil.which("libreoffice"), reason="LibreOffice fehlt")


def make(store, name, data, chat=None):
    chat = chat or store.create_chat("dora", "Dateien")["id"]
    meta = store.outfile_add("dora", chat, name, outbox.media_type(name), data, 14)
    return chat, meta["id"]


def workbook() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Umsatz"
    ws.append(["Monat", "Umsatz", "Marge", "Datum"])
    ws.append(["Jan", 1234.5, 0.256, datetime.date(2026, 1, 31)])
    ws.append(["Feb", 98765.4321, 0.1, datetime.datetime(2026, 2, 28, 14, 5)])
    ws.append(["Summe", "=SUM(B2:B3)"])
    ws["B2"].number_format = '#,##0.00 "€"'
    ws["B3"].number_format = "#,##0.00"
    ws["C2"].number_format = "0.0%"
    ws["D2"].number_format = "dd.mm.yyyy"
    ws["D3"].number_format = "dddd, d. mmmm yyyy hh:mm"
    ws["A1"].font = Font(bold=True, color="FFFFFF")
    ws["A1"].fill = PatternFill("solid", fgColor="305496")
    ws["A1"].alignment = Alignment(horizontal="center")
    ws.merge_cells("A6:C6")
    ws["A6"] = "Verbunden"
    ws.column_dimensions["A"].width = 20
    hidden = wb.create_sheet("Versteckt")
    hidden["A1"] = "geheim"
    hidden.sheet_state = "hidden"
    wb.create_sheet("Zweites")["A1"] = "zwei"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def test_excel_sheets_formats_styles_merges_and_formulas():
    view = filepages.sheets(workbook(), "de")
    assert [s["name"] for s in view["sheets"]] == ["Umsatz", "Zweites"]  # das versteckte Blatt fehlt
    sheet = view["sheets"][0]
    rows = sheet["rows"]
    text = lambda cell: cell[0] if isinstance(cell, list) else cell  # noqa: E731
    assert text(rows[1][1]) == "1.234,50 €" and text(rows[1][2]) == "25,6%" and text(rows[1][3]) == "31.01.2026"
    assert text(rows[2][1]) == "98.765,43" and text(rows[2][3]) == "Samstag, 28. Februar 2026 14:05"
    assert text(rows[3][1]) == "=SUM(B2:B3)"  # ohne gespeicherten Wert: die Formel
    # Zahlen stehen rechts, die Kopfzelle ist fett, weiß und blau hinterlegt
    right = view["styles"][rows[1][1][1]]
    assert right["a"] == "right"
    head = view["styles"][rows[0][0][1]]
    assert head == {"b": True, "i": False, "c": "#FFFFFF", "f": "#305496", "a": "center", "w": False}
    assert sheet["merges"] == [[6, 1, 6, 3]] and sheet["widths"][0] == 145
    english = filepages.sheets(workbook(), "en")["sheets"][0]["rows"]
    assert english[1][3] == "31.01.2026" and english[2][3] == "Saturday, 28. February 2026 14:05"  # das Zahlenformat der Zelle gilt, die Namen folgen der Sprache


def test_excel_number_formats_english_and_special_cases():
    assert filepages.display(1234.5, '#,##0.00', "en") == "1,234.50"
    assert filepages.display(1234.5, '#,##0.00', "de") == "1.234,50"
    assert filepages.display(0.5, "0%", "de") == "50%"
    assert filepages.display(-3.14159, "0.00", "de") == "-3,14"
    assert filepages.display(12, "General", "de") == "12"
    assert filepages.display(2.5, "General", "de") == "2,5"
    assert filepages.display(True, "General", "de") == "WAHR" and filepages.display(True, "General", "en") == "TRUE"
    assert filepages.display(datetime.time(9, 5), "hh:mm", "de") == "09:05"
    assert filepages.display(datetime.datetime(2026, 3, 4, 10, 30), "yyyy-mm-dd hh:mm", "de") == "2026-03-04 10:30"
    assert filepages.display(None, "General", "de") == ""


def test_excel_limits_and_errors():
    wb = Workbook()
    ws = wb.active
    for r in range(1, filepages.MAX_ROWS + 20):
        ws.cell(row=r, column=1, value=r)
    ws.cell(row=1, column=filepages.MAX_COLS + 5, value="weit rechts")
    buffer = io.BytesIO()
    wb.save(buffer)
    sheet = filepages.sheets(buffer.getvalue(), "de")["sheets"][0]
    assert len(sheet["rows"]) == filepages.MAX_ROWS and len(sheet["widths"]) == filepages.MAX_COLS and sheet["truncated"] is True
    assert sheet["rows_total"] == filepages.MAX_ROWS + 19
    with pytest.raises(filepages.ViewError):
        filepages.sheets(b"keine Tabelle", "de")
    with pytest.raises(filepages.ViewError, match="zu groß"):
        filepages.sheets(b"0" * (filepages.MAX_XLSX_BYTES + 1), "de")


def test_capability():
    assert filepages.capability("a.xlsx") == "sheets" and filepages.capability("a.pdf") == "pages"
    assert filepages.capability("a.sh") is None and filepages.capability("a.csv") is None


def pdf_bytes(pages=3) -> bytes:
    data, _ = outbox.render("brief.pdf", "# Titel\n\n" + "\n\n".join(f"Absatz {n} " * 40 for n in range(pages * 12)))
    return data


def test_pdf_pages_sizes_and_png():
    import asyncio

    pdf = pdf_bytes()
    sizes, total = filepages.page_sizes(pdf)
    assert total >= 2 and len(sizes) == total and all(w > 100 and h > 100 for w, h in sizes)
    png = filepages.render_page(pdf, 0, 700)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert asyncio.run(filepages.pdf_for("k", "x.pdf", pdf)) == pdf
    with pytest.raises(filepages.ViewError):
        filepages.render_page(pdf, 99, 700)
    with pytest.raises(filepages.ViewError, match="Kennwort"):
        filepages.page_sizes(b"%PDF-kaputt")


@needs_office
def test_word_is_converted_to_pages_and_cached():
    import asyncio

    docx, _ = outbox.render("bericht.docx", "# Titel\n\n" + "Ein Absatz mit Inhalt. " * 80)
    pdf = asyncio.run(filepages.pdf_for("docx-1", "bericht.docx", docx))
    assert pdf.startswith(b"%PDF")
    assert asyncio.run(filepages.pdf_for("docx-1", "bericht.docx", b"")) == pdf  # aus dem Speicher, ohne die Datei noch einmal zu brauchen


def test_view_and_page_api_for_pdf_and_excel(client, store):
    chat, pid = make(store, "brief.pdf", pdf_bytes())
    shown = client.get(f"/api/files/{pid}/text", headers=as_user(DORA)).json()
    assert shown["kind"] == "extract" and shown["view"] == "pages"
    view = client.get(f"/api/files/{pid}/view", headers=as_user(DORA))
    assert view.status_code == 200 and view.json()["mode"] == "pages" and view.json()["total"] >= 2
    page = client.get(f"/api/files/{pid}/page/1?w=800", headers=as_user(DORA))
    assert page.status_code == 200 and page.headers["content-type"] == "image/png" and page.content[:4] == b"\x89PNG"
    assert "sandbox" in page.headers["content-security-policy"]
    again = client.get(f"/api/files/{pid}/page/1?w=800", headers=as_user(DORA))
    assert again.content == page.content and (pid, 0, 800) in filepages._png_cache
    assert client.get(f"/api/files/{pid}/page/999", headers=as_user(DORA)).status_code == 415
    # fremde Konten sehen nichts
    assert client.get(f"/api/files/{pid}/view", headers=as_user(ADM01)).status_code == 404
    assert client.get(f"/api/files/{pid}/page/1", headers=as_user(ADM01)).status_code == 404
    # Excel: Blätter statt Seiten
    _, xid = make(store, "zahlen.xlsx", workbook(), chat)
    assert client.get(f"/api/files/{xid}/text", headers=as_user(DORA)).json()["view"] == "sheets"
    sheets = client.get(f"/api/files/{xid}/view", headers=as_user(DORA)).json()
    assert sheets["mode"] == "sheets" and sheets["sheets"][0]["name"] == "Umsatz"
    assert client.get(f"/api/files/{xid}/page/1", headers=as_user(DORA)).status_code == 415
    # Textdateien haben keine Seitenansicht
    _, tid = make(store, "a.sh", b"echo 1\n", chat)
    assert client.get(f"/api/files/{tid}/view", headers=as_user(DORA)).status_code == 415
    # kaputte Dateien melden sich ehrlich
    _, bad = make(store, "kaputt.pdf", b"%PDF-1.4 kaputt", chat)
    assert client.get(f"/api/files/{bad}/view", headers=as_user(DORA)).status_code == 415


@needs_office
def test_view_api_for_word(client, store):
    docx, _ = outbox.render("bericht.docx", "# Titel\n\n" + "Ein Absatz mit Inhalt. " * 80)
    _, did = make(store, "bericht.docx", docx)
    view = client.get(f"/api/files/{did}/view", headers=as_user(DORA))
    assert view.status_code == 200 and view.json()["mode"] == "pages"
    assert client.get(f"/api/files/{did}/page/1", headers=as_user(DORA)).content[:4] == b"\x89PNG"


def test_word_without_libreoffice_keeps_text_preview(client, store, monkeypatch):
    monkeypatch.setattr(filepages.preview, "soffice_path", lambda: None)
    docx, _ = outbox.render("bericht.docx", "# Titel\n\nInhalt")
    _, did = make(store, "bericht.docx", docx)
    shown = client.get(f"/api/files/{did}/text", headers=as_user(DORA)).json()
    assert shown["view"] is None and "Inhalt" in shown["content"]
    assert client.get(f"/api/files/{did}/view", headers=as_user(DORA)).status_code == 415


def test_versions_list_and_restore(client, store):
    chat, v1 = make(store, "motd.sh", b"echo eins\n")
    v2 = client.put(f"/api/files/{v1}/text", json={"content": "echo zwei"}, headers=as_user(DORA, True)).json()["id"]
    v3 = client.put(f"/api/files/{v2}/text", json={"content": "echo drei"}, headers=as_user(DORA, True)).json()["id"]
    other = store.outfile_add("dora", chat, "andere.sh", "text/x-shellscript", b"x", 14)["id"]
    listed = client.get(f"/api/files/{v2}/versions", headers=as_user(DORA)).json()
    assert [v["id"] for v in listed["versions"]] == [v1, v2, v3]
    assert [v["n"] for v in listed["versions"]] == [1, 2, 3] and [v["latest"] for v in listed["versions"]] == [False, False, True]
    assert other not in [v["id"] for v in listed["versions"]]  # andere Datei im selben Chat
    # die neueste lässt sich nicht „wiederherstellen“, eine ältere schon: sie wird zur neuesten Fassung
    assert client.post(f"/api/files/{v3}/restore", headers=as_user(DORA, True)).status_code == 409
    assert client.post(f"/api/files/{v1}/restore", headers=as_user(DORA)).status_code == 403  # ohne Schutz-Header
    restored = client.post(f"/api/files/{v1}/restore", headers=as_user(DORA, True))
    assert restored.status_code == 200 and restored.json()["name"] == "motd.sh"
    new_id = restored.json()["id"]
    assert client.get(f"/api/files/{new_id}", headers=as_user(DORA)).content == b"echo eins\n"
    assert [f["id"] for f in store.outfile_list("dora", chat) if f["name"] == "motd.sh"] == [new_id]
    assert len(client.get(f"/api/files/{new_id}/versions", headers=as_user(DORA)).json()["versions"]) == 4
    # fremde Konten und abgelaufene Dateien
    assert client.get(f"/api/files/{v1}/versions", headers=as_user(ADM01)).status_code == 404
    assert client.post(f"/api/files/{v1}/restore", headers=as_user(ADM01, True)).status_code == 404
    with store._lock, store._conn:
        store._conn.execute("UPDATE outfiles SET expires_at = '2000-01-01T00:00:00+00:00' WHERE id = ?", (v1,))
    assert [v["id"] for v in client.get(f"/api/files/{v2}/versions", headers=as_user(DORA)).json()["versions"]][0] == v2  # abgelaufene fehlen
    assert client.get(f"/api/files/{v1}/versions", headers=as_user(DORA)).status_code == 404


def test_mermaid_frame_can_export_plain_svg():
    from app.mermaid_frame import page

    html = page()
    assert 'd.type === "export"' in html and "htmlLabels = false" in html and 'type: "svg"' in html
