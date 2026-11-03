"""Bilder, Diagramme und Inhaltsverzeichnis in erzeugten Dateien sowie die Bildvorschau für die KI."""
import asyncio
import importlib.util
import io
import json
import shutil

import pytest

from app import charts, design, outbox, pictures, preview
from app import mdblocks as md
from app.ha_tools import ToolError, ToolResult

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 120"><rect width="200" height="120" rx="12" fill="#1A7595"/><circle cx="100" cy="60" r="32" fill="white"/></svg>'
needs_svg = pytest.mark.skipif(importlib.util.find_spec("cairosvg") is None, reason="cairosvg fehlt")
needs_office = pytest.mark.skipif(not preview.soffice_path(), reason="LibreOffice fehlt")
CHART = '{"type":"column","title":"Umsatz","unit":"€","labels":["Q1","Q2","Q3"],"series":[{"name":"2025","values":[1,2,3]},{"name":"2026","values":[2,3,5]}]}'


def run(coro):
    return asyncio.run(coro)


def png(w=40, h=20, color="#336699"):
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (w, h), color).save(out, "PNG")
    return out.getvalue()


def source(**files):
    return lambda name: files.get(name)


DOC = f"# Bericht\n\n[TOC]\n\n## Lage\n\nText.\n\n![Das Logo](logo.png)\n\n### Detail\n\n```chart\n{CHART}\n```\n\n## Schluss\n\nEnde."


# ------------------------------------------------------------------- Markdown

def test_markdown_knows_image_chart_and_toc_blocks():
    blocks = md.parse(f"# T\n\n[TOC]\n[Inhaltsverzeichnis]\n\n![Ein Bild](a b.png)\n![x](<c d.png> \"Titel\")\n\n```chart\n{{\"a\": 1}}\n```\n\n```python\nx = 1\n```\n\nText ![kein Block](x.png) im Satz")
    kinds = [b[0] for b in blocks]
    assert kinds == ["h", "toc", "toc", "image", "image", "chart", "code", "p"]
    assert blocks[3][1:] == ("Ein Bild", "a b.png") and blocks[4][2] == "c d.png"
    assert blocks[5][1] == '{"a": 1}' and blocks[6] == ("code", "x = 1")


# ------------------------------------------------------------------- Diagramme

def test_chart_parse_accepts_variants_and_german_numbers():
    c = charts.parse('{"type":"Säulen","labels":["a","b"],"series":{"X":[1,"2,5"],"Y":["1.000,5",3]}}')
    assert c.kind == "column" and [s.values for s in c.series] == [[1.0, 2.5], [1000.5, 3.0]]
    one = charts.parse('{"type":"line","values":[3,4,5],"title":"T"}')
    assert one.labels == ["1", "2", "3"] and one.series[0].name == "T"


@pytest.mark.parametrize("raw, message", [
    ("kein json", "kein gültiges JSON"),
    ("[1]", "JSON-Objekt"),
    ('{"type":"radar","series":[{"values":[1]}]}', "type muss"),
    ('{"type":"bar"}', "series fehlt"),
    ('{"type":"bar","series":[{"name":"a","values":[]}]}', "values"),
    ('{"type":"bar","series":[{"values":["x"]}]}', "keine Zahl"),
    ('{"type":"bar","labels":["a"],"series":[{"values":[1,2]}]}', "gleich lang"),
    ('{"type":"bar","series":[{"values":[1,2]},{"values":[1]}]}', "gleich viele"),
    ('{"type":"pie","series":[{"values":[1]},{"values":[2]}]}', "genau eine"),
    ('{"type":"pie","series":[{"values":[-1,2]}]}', "positive"),
    ('{"type":"pie","series":[{"values":[1,1,1,1,1,1,1,1,1]}]}', "höchstens 8"),
])
def test_chart_errors_tell_the_ai_what_to_fix(raw, message):
    with pytest.raises(charts.ChartError, match=message):
        charts.parse(raw)


def test_number_format_and_ticks():
    assert charts.fmt(1234.5, "€") == "1.234 €" or charts.fmt(1234.5, "€") == "1.235 €"
    assert charts.fmt(0.5) == "0,50" and charts.fmt(12.25, "kg") == "12,2 kg" or charts.fmt(12.25, "kg") == "12,3 kg"
    ticks = charts.nice_ticks(0, 173)
    assert ticks[0] == 0 and ticks[-1] >= 173 and len(ticks) <= 9
    assert charts.nice_ticks(5, 5)[0] <= 5


@pytest.mark.parametrize("kind", ["column", "bar", "line", "pie"])
def test_chart_png_for_every_kind(kind):
    from PIL import Image

    spec = charts.parse(json.dumps({"type": kind, "title": "T", "labels": ["a", "b", "c"], "series": [{"name": "s", "values": [3, 5, 2]}] + ([{"name": "t", "values": [1, 2, 3]}] if kind != "pie" else [])}))
    data = charts.draw_png(spec, design.THEMES["wald"])
    img = Image.open(io.BytesIO(data))
    assert img.size == (1600, 900) and len(img.getcolors(maxcolors=1 << 20) or []) > 3


# ----------------------------------------------------------------------- Bilder

def test_prepare_passes_png_and_jpeg_and_converts_others():
    from PIL import Image

    p = pictures.prepare(png(30, 10))
    assert (p.ext, p.width, p.height) == ("png", 30, 10)
    jpg = io.BytesIO()
    Image.new("RGB", (50, 20), "red").save(jpg, "JPEG")
    assert pictures.prepare(jpg.getvalue()).ext == "jpg"
    webp = io.BytesIO()
    Image.new("RGB", (50, 20), "red").save(webp, "WEBP")
    assert pictures.prepare(webp.getvalue()).ext == "jpg"  # WebP ohne Transparenz wird JPEG
    big = pictures.prepare(png(4000, 1000))
    assert max(big.width, big.height) == pictures.MAX_EDGE and big.height == 600


def test_prepare_rejects_garbage_and_huge_images():
    with pytest.raises(pictures.PictureError, match="kein lesbares Bild"):
        pictures.prepare(b"nur text", "x.png")
    with pytest.raises(pictures.PictureError, match="zu groß"):
        pictures.prepare(png(9000, 9000), "riesig.png")


@needs_svg
def test_svg_is_drawn_and_never_fetches_anything():
    p = pictures.prepare(SVG)
    assert p.ext == "png" and p.width == pictures.SVG_WIDTH
    external = b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="10" height="10"><image xlink:href="http://127.0.0.1:9/x.png" width="5" height="5"/></svg>'
    with pytest.raises(pictures.PictureError, match="externe Dateien"):
        pictures.prepare(external)
    local = external.replace(b"http://127.0.0.1:9/x.png", b"file:///etc/passwd")
    with pytest.raises(pictures.PictureError, match="externe Dateien"):
        pictures.prepare(local)
    with pytest.raises(pictures.PictureError, match="DOCTYPE"):
        pictures.prepare(b'<!DOCTYPE svg [<!ENTITY x "y">]>' + SVG)


# --------------------------------------------------------- eingebettet in Dateien

def test_docx_embeds_image_chart_and_toc():
    import docx

    data, _ = outbox.render("b.docx", DOC, "T", images=source(**{"logo.png": png(800, 400)}))
    d = docx.Document(io.BytesIO(data))
    assert len(d.inline_shapes) == 2
    assert d.inline_shapes[0]._inline.docPr.get("descr") == "Das Logo"
    xml = d.element.xml
    assert 'TOC \\o "1-3"' in xml and "fldCharType=\"begin\"" in xml and "fldCharType=\"end\"" in xml
    texts = [p.text for p in d.paragraphs]
    assert "Inhaltsverzeichnis" in texts and texts.count("Lage") == 2 and texts.count("Detail") == 2  # einmal Verzeichnis, einmal Überschrift
    assert "Bericht" not in texts[texts.index("Inhaltsverzeichnis"):texts.index("Inhaltsverzeichnis") + 5]  # der Titel steht vor dem Verzeichnis
    assert all(i.width <= 16.5 * 360000 for i in d.inline_shapes)


def test_pdf_embeds_image_chart_and_toc_with_page_numbers():
    import pypdfium2 as pdfium

    data, _ = outbox.render("b.pdf", DOC, "T", images=source(**{"logo.png": png(800, 400)}))
    pdf = pdfium.PdfDocument(data)
    text = "\n".join(pdf[i].get_textpage().get_text_range() for i in range(len(pdf)))
    assert "Inhaltsverzeichnis" in text and "Schluss" in text and "Das Logo" in text
    assert len(pdf) >= 2  # das Verzeichnis hat eine eigene Seite
    assert sum(1 for i in range(len(pdf)) for o in pdf[i].get_objects() if o.type == 3) >= 2  # Bild-Objekte (Logo, Diagramm)


def test_pptx_places_image_beside_text_and_chart_natively():
    from pptx import Presentation

    deck = f"# Titel\n\nUntertitel\n\n## Mit Bild\n\n- eins\n- zwei\n\n![Logo](logo.png)\n\n## Nur Diagramm\n\n```chart\n{CHART}\n```\n\n## Zwei Bilder\n\n![a](logo.png)\n\n![b](logo.png)"
    data, _ = outbox.render("d.pptx", deck, "T", images=source(**{"logo.png": png(800, 400)}))
    slides = list(Presentation(io.BytesIO(data)).slides)
    pics = [s for s in slides[1].shapes if s.shape_type == 13]
    text = next(s for s in slides[1].shapes if s.has_text_frame and "eins" in s.text_frame.text)
    assert len(pics) == 1 and pics[0].left > text.left + text.width - 1  # rechts neben dem Text
    assert pics[0]._element.nvPicPr.cNvPr.get("descr") == "Logo"
    assert any(s.has_chart for s in slides[2].shapes) and next(s for s in slides[2].shapes if s.has_chart).chart.plots[0].categories[0] == "Q1"
    pair = sorted((s for s in slides[3].shapes if s.shape_type == 13), key=lambda s: s.left)
    assert len(pair) == 2 and pair[0].left + pair[0].width <= pair[1].left


def test_pptx_toc_becomes_agenda_slide():
    from pptx import Presentation

    deck = "# Titel\n\nSub\n\n## Agenda\n\n[TOC]\n\n## Lage\n\n- a\n\n## Plan\n\n- b\n\n## Kosten\n\n- c"
    slides = list(Presentation(io.BytesIO(outbox.render("d.pptx", deck, "T")[0])).slides)
    agenda = " ".join(s.text_frame.text for s in slides[1].shapes if s.has_text_frame)
    assert "Lage" in agenda and "Plan" in agenda and "Kosten" in agenda
    sections = "# Titel\n\nSub\n\n## Agenda\n\n[TOC]\n\n## Teil A\n\n## Teil B\n\n## Teil C\n\n## Folie\n\n- x"
    agenda = " ".join(s.text_frame.text for s in list(Presentation(io.BytesIO(outbox.render("d.pptx", sections, "T")[0])).slides)[1].shapes if s.has_text_frame)
    assert "Teil A" in agenda and "Folie" not in agenda  # ab drei Zwischenfolien nur diese


def test_xlsx_native_chart_and_its_errors():
    import openpyxl

    rows = [["Quartal", "2025", "2026"], ["Q1", 1, 2], ["Q2", 2, 3], ["Q3", 3, 5]]
    sheet = {"sheets": [{"name": "Umsatz", "rows": rows, "charts": [{"type": "column", "title": "Umsatz"}, {"type": "line", "series": ["2026"]}]}]}
    wb = openpyxl.load_workbook(io.BytesIO(outbox.render("m.xlsx", json.dumps(sheet), "T")[0]))
    assert len(wb["Umsatz"]._charts) == 2
    for bad, message in (({"type": "radar"}, "type muss"), ({"type": "bar", "series": ["gibtsnicht"]}, "nicht in der Kopfzeile")):
        sheet["sheets"][0]["charts"] = [bad]
        with pytest.raises(ToolError, match=message):
            outbox.render("m.xlsx", json.dumps(sheet), "T")


def test_missing_or_bad_references_are_reported():
    with pytest.raises(ToolError, match="gibt es in diesem Chat nicht"):
        outbox.render("b.docx", "# T\n\n![x](fehlt.png)", "T", images=source())
    with pytest.raises(ToolError, match="nicht einbetten"):
        outbox.render("b.docx", "# T\n\n![x](a.png)", "T")
    with pytest.raises(ToolError, match="kein lesbares Bild"):
        outbox.render("b.pdf", "# T\n\n![x](a.png)", "T", images=source(**{"a.png": b"kaputt"}))
    with pytest.raises(ToolError, match="kein gültiges JSON"):
        outbox.render("d.pptx", "# T\n\nU\n\n## A\n\n```chart\nnein\n```", "T")


def test_hints_for_media_slides():
    deck = "# T\n\nU\n\n## A\n\n- a\n- b\n- c\n- d\n\n![x](a.png)"
    assert any("Bild oder Diagramm" in h for h in outbox.design_hints("pptx", deck))


def test_keynote_mode_uses_mac_fonts_and_no_autofit():
    from pptx import Presentation
    from pptx.enum.text import MSO_AUTO_SIZE

    deck = "# Titel\n\nSub\n\n## Eins\n\n" + "\n".join(f"- Punkt {i} mit etwas längerem Text, damit es breiter wird" for i in range(8)) + "\n\n`code` hier"

    def inspect(target):
        prs = Presentation(io.BytesIO(outbox.render("a.pptx", deck, "T", theme="sand", target=target)[0]))
        fonts = {r.font.name for sl in prs.slides for sh in sl.shapes if sh.has_text_frame for p in sh.text_frame.paragraphs for r in p.runs}
        autos = {sh.text_frame.auto_size for sl in prs.slides for sh in sl.shapes if sh.has_text_frame}
        return len(prs.slides), fonts, autos

    slides_pp, fonts_pp, autos_pp = inspect(None)
    slides_kn, fonts_kn, autos_kn = inspect("keynote")
    assert "Consolas" in fonts_pp and MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE in autos_pp
    assert fonts_kn <= {"Georgia", "Helvetica Neue", "Menlo"} and "Menlo" in fonts_kn
    assert MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE not in autos_kn and slides_kn >= slides_pp  # knapper: gleich viele oder mehr Folien
    assert inspect("powerpoint")[1] == fonts_pp
    with pytest.raises(ToolError, match="target muss"):
        outbox.render("a.pptx", deck, "T", target="pages")
    other, _ = outbox.render("a.docx", "# T\n\nText", "T", target="keynote")  # für andere Formate ohne Wirkung
    assert other[:2] == b"PK"


def test_file_create_offers_keynote_target(store):
    box, _, _ = make_box(store)
    spec = next(s for s in box.specs() if s.name == "file_create")
    assert spec.schema["properties"]["target"]["enum"] == ["powerpoint", "keynote"]
    assert "Keynote" in outbox.DESIGN_NOTE and "target=keynote" in outbox.FILE_TOOL_TEXT
    run(box.file_create({"name": "k.pptx", "content": "# T\n\nU\n\n## A\n\n- x", "target": "keynote"}))


# ----------------------------------------------------------------------- Vorschau

def test_parse_pages():
    assert preview.parse_pages(None, 5) == [0, 1, 2, 3, 4]
    assert preview.parse_pages("2-4", 10) == [1, 2, 3]
    assert preview.parse_pages("1, 3;3", 10) == [0, 2]
    assert len(preview.parse_pages(None, 40)) == preview.MAX_PAGES
    for bad in ("x", "0", "5-2"):
        with pytest.raises(preview.PreviewError):
            preview.parse_pages(bad, 10)
    with pytest.raises(preview.PreviewError, match="nur 3"):
        preview.parse_pages("7", 3)


def test_preview_of_pdf_single_and_sheet():
    from PIL import Image

    data, _ = outbox.render("b.pdf", "# A\n\n" + "\n\n".join(f"## Teil {i}\n\n" + "Text. " * 400 for i in range(5)), "T")
    images, note = run(preview.preview("b.pdf", data, "1"))
    assert len(images) == 1 and "Seite 1 von" in note and Image.open(io.BytesIO(images[0][0])).width == preview.SINGLE_WIDTH
    images, note = run(preview.preview("b.pdf", data))
    assert len(images) == 1 and "Übersicht" in note and Image.open(io.BytesIO(images[0][0])).width > preview.SINGLE_WIDTH


@needs_svg
def test_preview_of_image_and_svg():
    for name, data in (("a.png", png(300, 100)), ("z.svg", SVG)):
        images, note = run(preview.preview(name, data))
        assert images[0][1] == "image/jpeg" and "Seite 1 von 1" in note


def test_preview_limits_are_explained():
    with pytest.raises(preview.PreviewError, match="file_read"):
        run(preview.preview("t.xlsx", b"x"))
    with pytest.raises(preview.PreviewError, match="Bildvorschau gibt es für"):
        run(preview.preview("a.txt", b"x"))
    with pytest.raises(preview.PreviewError, match="nicht öffnen"):
        run(preview.preview("a.pdf", b"kein pdf"))


def test_preview_without_libreoffice_says_so(monkeypatch):
    monkeypatch.setattr(preview, "soffice_path", lambda: None)
    with pytest.raises(preview.PreviewError, match="LibreOffice"):
        run(preview.preview("a.pptx", b"x"))


@needs_office
def test_preview_of_pptx_and_docx_through_libreoffice():
    deck, _ = outbox.render("d.pptx", "# Titel\n\nSub\n\n## Eins\n\n- a\n\n## Zwei\n\n- b", "T")
    images, note = run(preview.preview("d.pptx", deck))
    assert "von 3" in note and len(images) == 1
    doc, _ = outbox.render("d.docx", "# Titel\n\nText", "T")
    images, note = run(preview.preview("d.docx", doc))
    assert "Seite 1 von 1" in note


# ------------------------------------------------------------------ Werkzeug

def make_box(store):
    chat = store.create_chat("adm01", "Test") if store.create_chat.__code__.co_argcount == 3 else store.create_chat("adm01")
    chat_id = chat["id"] if isinstance(chat, dict) else chat
    events = []
    counter = iter(range(1, 99))
    box = outbox.OutboxToolbox(store, "adm01", chat_id, record=events.append, next_id=lambda: next(counter), keep_days=7)
    return box, events, chat_id


def test_file_create_embeds_chat_images_and_file_preview_returns_images(store):
    box, events, _ = make_box(store)
    store.outfile_add("adm01", box.chat_id, "logo.png", "image/png", png(400, 200), 7)
    reply = run(box.file_create({"name": "b.pdf", "content": "# Bericht\n\n![Logo](logo.png)\n\nText."}))
    assert "Datei b.pdf erstellt" in reply and "file_preview" in reply
    result = run(box.file_preview({"name": "b.pdf"}))
    assert isinstance(result, ToolResult) and result.images and result.images[0][1] == "image/jpeg" and "Vorschau von b.pdf" in result.text
    with pytest.raises(ToolError, match="gibt es in diesem Chat nicht"):
        run(box.file_preview({"name": "nix.pdf"}))
    with pytest.raises(ToolError, match="gibt es in diesem Chat nicht"):
        run(box.file_create({"name": "c.docx", "content": "# T\n\n![x](fehlt.png)"}))
    assert any(e.get("status") == "error" for e in events)


def test_only_images_of_the_chat_can_be_embedded(store):
    box, _, _ = make_box(store)
    store.outfile_add("adm01", box.chat_id, "notizen.txt", "text/plain", b"geheim", 7)
    assert box._image_bytes("notizen.txt") is None and box._image_bytes("fehlt.png") is None
    store.outfile_add("adm01", box.chat_id, "Logo.PNG", "image/png", png(), 7)
    assert box._image_bytes("logo.png") is not None  # Groß-/Kleinschreibung egal
    store.outfile_add("adm01", box.chat_id, "z.svg", "image/svg+xml", SVG, 7)
    assert box._image_bytes("z.svg") == SVG


def test_backend_passes_images_to_the_model():
    import base64

    from app.backend import tool_content

    assert tool_content("nur Text") == [{"type": "text", "text": "nur Text"}]
    blocks = tool_content(ToolResult("Vorschau", [(b"\xff\xd8abc", "image/jpeg")]))
    assert blocks[0] == {"type": "text", "text": "Vorschau"}
    assert blocks[1]["type"] == "image" and blocks[1]["mimeType"] == "image/jpeg" and base64.b64decode(blocks[1]["data"]) == b"\xff\xd8abc"


# ----------------------------------------------------------------------------- Links

LINK_MD = "# T\n\nSiehe [HA Copilot](https://github.com/x/y) und https://example.com/a.\n\n## A\n\n- Punkt [mail](mailto:a@b.de)\n"


def test_docx_has_clickable_hyperlinks():
    from docx import Document

    data, _ = outbox.render("l.docx", LINK_MD, "T")
    doc = Document(io.BytesIO(data))
    targets = {r.target_ref for r in doc.part.rels.values() if r.is_external}
    assert {"https://github.com/x/y", "https://example.com/a", "mailto:a@b.de"} <= targets
    assert "HA Copilot" in "".join(p.text for p in doc.paragraphs)


def test_pdf_has_link_annotations():
    import re

    data, _ = outbox.render("l.pdf", LINK_MD, "T")
    uris = set(re.findall(rb"/URI \(([^)]*)\)", data))
    assert b"https://github.com/x/y" in uris and b"https://example.com/a" in uris


def test_pptx_runs_carry_hyperlinks():
    from pptx import Presentation

    data, _ = outbox.render("l.pptx", "# T\n\nS\n\n## A\n\n- [x](https://x.de) y", "T")
    prs = Presentation(io.BytesIO(data))
    found = [r.hyperlink.address for s in prs.slides for sh in s.shapes if sh.has_text_frame
             for pa in sh.text_frame.paragraphs for r in pa.runs if r.hyperlink.address]
    assert found == ["https://x.de"]
