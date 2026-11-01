"""Word und Excel werden ohne Zusatzpakete in Text umgewandelt, gegen präparierte Dateien abgesichert."""
import base64
import io
import zipfile

import pytest

from app import attachments as att
from app import office

WNS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
SNS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
RNS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def zipped(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def docx(body: str) -> bytes:
    return zipped({"word/document.xml": f'<?xml version="1.0"?><w:document {WNS}><w:body>{body}</w:body></w:document>'})


def p(text, style=None, listed=False):
    props = ""
    if style:
        props += f'<w:pStyle w:val="{style}"/>'
    if listed:
        props += "<w:numPr><w:ilvl w:val=\"0\"/><w:numId w:val=\"1\"/></w:numPr>"
    return f"<w:p><w:pPr>{props}</w:pPr><w:r><w:t>{text}</w:t></w:r></w:p>"


def test_docx_headings_lists_tables_and_breaks():
    body = (
        p("Wartungsplan", "berschrift1")  # so heißt die Überschrift-Formatvorlage in deutschem Word
        + p("Einleitung mit Umlauten: äöü")
        + p("Erster Punkt", listed=True)
        + '<w:p><w:r><w:t>vor</w:t><w:tab/><w:t>nach</w:t><w:br/><w:t>Zeile 2</w:t></w:r></w:p>'
        + "<w:tbl><w:tr><w:tc>" + p("Host") + "</w:tc><w:tc>" + p("Status") + "</w:tc></w:tr>"
        "<w:tr><w:tc>" + p("srv01") + "</w:tc><w:tc>" + p("ok") + "</w:tc></w:tr></w:tbl>"
    )
    text = office.docx_to_text(docx(body), 10_000)
    assert "# Wartungsplan" in text and "äöü" in text and "- Erster Punkt" in text
    assert "vor\tnach\nZeile 2" in text
    assert "| Host | Status |" in text and "| srv01 | ok |" in text


def test_docx_without_text_is_refused():
    with pytest.raises(office.OfficeError, match="keinen lesbaren Text"):
        office.docx_to_text(docx(p("")), 1000)


def xlsx(sheets: dict[str, str], strings=(), styles="", hidden=()):
    files = {
        "xl/workbook.xml": f'<workbook {SNS} {RNS}><sheets>'
        + "".join(
            f'<sheet name="{n}" sheetId="{i + 1}" r:id="rId{i + 1}"' + (' state="hidden"' if n in hidden else "") + "/>"
            for i, n in enumerate(sheets)
        )
        + "</sheets></workbook>",
        "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(
            f'<Relationship Id="rId{i + 1}" Target="worksheets/sheet{i + 1}.xml" Type="x"/>' for i in range(len(sheets))
        )
        + "</Relationships>",
        "xl/sharedStrings.xml": f"<sst {SNS}>" + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>",
    }
    if styles:
        files["xl/styles.xml"] = styles
    for i, rows in enumerate(sheets.values()):
        files[f"xl/worksheets/sheet{i + 1}.xml"] = f"<worksheet {SNS}><sheetData>{rows}</sheetData></worksheet>"
    return zipped(files)


def test_xlsx_values_strings_dates_and_gaps():
    styles = (
        f"<styleSheet {SNS}><numFmts><numFmt numFmtId=\"164\" formatCode=\"dd.mm.yyyy\"/></numFmts>"
        '<cellXfs><xf numFmtId="0"/><xf numFmtId="164"/><xf numFmtId="14"/></cellXfs></styleSheet>'
    )
    rows = (
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="D1" t="s"><v>2</v></c></row>'
        '<row r="2"><c r="A2" t="s"><v>3</v></c><c r="B2"><v>42.5</v></c><c r="C2" s="1"><v>45992</v></c><c r="D2" t="b"><v>1</v></c></row>'
        '<row r="3"/>'
        '<row r="4"><c r="A4" s="2"><v>45992.5</v></c><c r="B4"><v>7</v></c></row>'
    )
    data = xlsx({"Server": rows}, strings=("Host", "Last", "Aktiv", "srv01"), styles=styles)
    text = office.xlsx_to_text(data, 10_000)
    assert text.startswith("## Tabellenblatt: Server")
    assert "Host | Last |  | Aktiv" in text  # leere Zelle C bleibt als Lücke
    assert "srv01 | 42.5 | 01.12.2025 | WAHR" in text
    assert "01.12.2025 12:00 | 7" in text
    assert "\n\n" not in text.split("\n", 1)[1]  # leere Zeilen entfallen


def test_xlsx_hidden_sheets_skipped_and_limits():
    rows = '<row r="1"><c r="A1" t="inlineStr"><is><t>sichtbar</t></is></c></row>'
    secret = '<row r="1"><c r="A1" t="inlineStr"><is><t>versteckt</t></is></c></row>'
    text = office.xlsx_to_text(xlsx({"A": rows, "B": secret}, hidden=("B",)), 1000)
    assert "sichtbar" in text and "versteckt" not in text

    big = "".join(f'<row r="{i}"><c r="A{i}" t="inlineStr"><is><t>zeile {i}</t></is></c></row>' for i in range(1, 300))
    cut = office.xlsx_to_text(xlsx({"A": big}), 800)
    assert cut.endswith("nicht übernommen …]") and len(cut) < 1000


def test_parse_one_wraps_office_files():
    word = att.parse_one("bericht.docx", b64(docx(p("Hallo Welt"))))
    assert word.kind == "text" and word.meta()["kind"] == "word" and word.meta()["size"] == word.size
    assert "Hallo Welt" in word.text() and word.size == len(docx(p("Hallo Welt")))
    sheet = att.parse_one("liste.xlsx", b64(xlsx({"A": '<row r="1"><c r="A1"><v>5</v></c></row>'})))
    assert sheet.meta()["kind"] == "excel" and "5" in sheet.text()
    inline = att.with_inline_text("Frage", [word])
    assert 'name="bericht.docx"' in inline and "Hallo Welt" in inline


def test_other_zip_and_old_office_and_broken_files_are_refused():
    with pytest.raises(att.AttachmentError, match="noch nicht unterstützt"):
        att.parse_one("x.zip", b64(zipped({"a.txt": "hi"})))
    with pytest.raises(att.AttachmentError, match="altes Office-Format"):
        att.parse_one("alt.doc", b64(office.OLE_MAGIC + b"\x00" * 100))
    with pytest.raises(att.AttachmentError, match="beschädigt"):
        att.parse_one("kaputt.docx", b64(b"PK\x03\x04" + b"\x00" * 60))


def test_xml_entities_and_zip_bombs_are_refused():
    evil = zipped({
        "word/document.xml": '<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "aaaa">]><w:document ' + WNS + "><w:body>&a;</w:body></w:document>"
    })
    with pytest.raises(att.AttachmentError, match="unzulässige XML"):
        att.parse_one("evil.docx", b64(evil))
    bomb = zipped({"word/document.xml": "<w:document " + WNS + "><w:body>" + "<w:p/>" * 8_000_000 + "</w:body></w:document>"})
    assert len(bomb) < 100_000  # winzig gepackt, riesig entpackt
    with pytest.raises(att.AttachmentError, match="zu groß zum Auslesen"):
        att.parse_one("bombe.docx", b64(bomb))
    many = zipped({f"f{i}.txt": "x" for i in range(office.MAX_ENTRIES + 1)} | {"word/document.xml": "<a/>"})
    with pytest.raises(att.AttachmentError, match="ungewöhnlich aufgebaut"):
        att.parse_one("viele.docx", b64(many))


def test_real_word_and_excel_files():
    """Dateien aus den echten Bibliotheken (nur wenn installiert), damit die Handarbeit oben nicht täuscht."""
    docx_lib = pytest.importorskip("docx")
    openpyxl = pytest.importorskip("openpyxl")
    import datetime

    d = docx_lib.Document()
    d.add_heading("Titel", 1)
    d.add_paragraph("Fließtext mit ß.")
    d.add_paragraph("Punkt A", style="List Bullet")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text, t.cell(1, 0).text, t.cell(1, 1).text = "A", "B", "1", "2"
    buf = io.BytesIO()
    d.save(buf)
    text = att.parse_one("echt.docx", b64(buf.getvalue())).text()
    assert "# Titel" in text and "Fließtext mit ß." in text and "- Punkt A" in text and "| A | B |" in text

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Daten"
    ws.append(["Name", "Datum", "Wert"])
    ws.append(["a", datetime.date(2026, 3, 5), 1.5])
    ws.append(["b", None, "=SUM(C2:C2)"])
    buf = io.BytesIO()
    wb.save(buf)
    text = att.parse_one("echt.xlsx", b64(buf.getvalue())).text()
    assert "## Tabellenblatt: Daten" in text and "a | 05.03.2026 | 1.5" in text
