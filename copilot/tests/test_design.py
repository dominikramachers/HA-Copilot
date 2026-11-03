"""Gestaltungswissen: Farbthemen, Leitfäden, Werkzeug design_guide, Hinweise und die Wirkung in den erzeugten Dateien."""
import asyncio
import io

import pytest

from app import design, outbox
from app.ha_tools import ToolError


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------------ Themen

@pytest.mark.parametrize("theme", list(design.THEMES.values()), ids=list(design.THEMES))
def test_every_theme_keeps_contrast(theme):
    c = design.contrast
    assert c(theme.dark, "FFFFFF") >= 12
    assert c("FFFFFF", theme.head) >= 9
    assert c(theme.accent, "FFFFFF") >= 4
    assert c(theme.accent, theme.surface) >= 3.5  # nur für große Schrift (Zwischenüberschriften) auf Flächen
    assert c(theme.grey, "FFFFFF") >= 4.5 and c(theme.grey, theme.surface) >= 4.5
    assert c(theme.on_head_muted, theme.head) >= 6  # Untertitel auf der Titelfolie
    assert c(theme.accent_light, theme.head) >= 4  # Linie auf der Titelfolie
    assert len(theme.use) > 10


def test_default_theme_and_resolve():
    assert design.resolve() is design.DEFAULT_THEME is design.THEMES["klar"]
    assert design.resolve("  OZEAN ").key == "ozean"
    assert design.resolve("", None) is design.DEFAULT_THEME
    with pytest.raises(ValueError, match="Unbekanntes Thema.*klar"):
        design.resolve("neon")


def test_custom_accent_is_made_readable():
    for color in ("#C2410C", "ffd400", "#FFFFFF", "00FF00", "000000"):
        t = design.resolve("klar", color)
        assert design.contrast(t.accent, "FFFFFF") >= 4.0, color
        assert design.contrast("FFFFFF", t.head) >= 9.0, color
        assert t.dark == design.THEMES["klar"].dark and t.heading_font == "Calibri"
    assert design.resolve(None, "#C2410C").accent != design.DEFAULT_THEME.accent
    for bad in ("rot", "#12345", "#GGGGGG", "12345678"):
        with pytest.raises(ValueError, match="accent"):
            design.resolve(None, bad)


# ---------------------------------------------------------------------- Leitfäden

def test_every_topic_has_a_bounded_guide():
    for topic in design.TOPICS:
        text = design.guide(topic)
        assert 40 < len(text) < 6500, topic  # kurz genug, um nicht jede Antwort zu verteuern
    assert "klar" in design.guide("themen") and "Kopfton" in design.guide("themen")
    assert design.guide(" Folien ") == design.guide("folien")
    with pytest.raises(ValueError, match="Verfügbar"):
        design.guide("comic")


def test_guides_only_promise_what_the_renderers_do():
    text = " ".join(design.guide(t) for t in design.TOPICS if t != "themen").lower()
    for word in ("theme", "titelfolie"):
        assert word in text
    assert "http" not in text  # eigene Texte, keine fremden Quellen


# --------------------------------------------------------------------- Hinweise

BAD_DECK = "\n".join([
    "# Wie wir im kommenden Jahr alle Prozesse im ganzen Haus besser und schneller und günstiger machen werden",
    "",
    "## Folie",
    "",
    *[f"- Punkt {i} " + "wort " * 18 for i in range(8)],
    "",
    "## Breit",
    "",
    "| a | b | c | d | e | f |",
    "|---|---|---|---|---|---|",
    "| 1 | 2 | 3 | 4 | 5 | 6 |",
])


def test_hints_flag_dense_slides():
    hints = outbox.design_hints("pptx", BAD_DECK)
    joined = "\n".join(hints)
    assert "Aufzählungspunkte" in joined and "16 Wörtern" in joined and "Tabelle mit 6 Spalten" in joined
    assert len(hints) <= 6


def test_hints_are_quiet_for_good_content():
    deck = "# Titel\n\nUntertitel\n\n## Ziele\n\n- eins\n- zwei\n- drei\n\n## Zahlen\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
    assert outbox.design_hints("pptx", deck) == []
    doc = "# Bericht\n\nEinleitung.\n\n## Teil\n\nText.\n\n### Detail\n\nMehr."
    assert outbox.design_hints("docx", doc) == [] and outbox.design_hints("pdf", doc) == []
    assert outbox.design_hints("txt", "x") == [] and outbox.design_hints("xlsx", "a,b") == []


def test_hints_flag_document_structure():
    text = "# A\n\n# B\n\n### C\n\n" + "wort " * 450
    joined = "\n".join(outbox.design_hints("docx", text))
    assert "Ebene 1" in joined and "übersprungen" in joined and "Zwischenüberschriften" in joined and "mehr als 120" in joined


def test_hints_never_break_creation(monkeypatch):
    monkeypatch.setattr(outbox.md, "parse", lambda *_: (_ for _ in ()).throw(RuntimeError("x")))
    assert outbox.design_hints("pptx", "# a") == []


# ----------------------------------------------------------------- erzeugte Dateien

MD = "# Jahresbericht\n\nUntertitel der Abteilung\n\n## Abschnitt eins\n\n- Punkt **A**\n- Punkt B\n\n| Name | Wert |\n|---|---|\n| a | 1 |\n| b | 2 |\n| c | 3 |\n\n## Kapitel\n\n## Danach\n\nText.\n\nNotizen: Sprechtext"


def test_unknown_theme_or_accent_is_reported_as_file_error():
    for kwargs in ({"theme": "neon"}, {"accent": "rot"}):
        with pytest.raises(ToolError):
            outbox.render("a.docx", MD, "T", **kwargs)
    outbox.render("a.txt", "x", "T", theme="ozean")  # Textdateien ignorieren das Thema


def test_pptx_uses_theme_for_title_section_and_table():
    from pptx import Presentation

    t = design.THEMES["terrakotta"]
    data, _ = outbox.render("deck.pptx", MD, "T", theme="terrakotta")
    prs = Presentation(io.BytesIO(data))
    slides = list(prs.slides)
    assert len(slides) == 4  # Titel, Abschnitt eins, Kapitel (Zwischenfolie), Danach
    for index in (0, 2):  # Titel- und Zwischenfolie: Hintergrund in Kopfton
        assert str(slides[index].background.fill.fore_color.rgb) == t.head
    assert slides[1].background.fill.type != 1  # Inhaltsfolie bleibt beim Standard (weiß), kein eigener Hintergrund
    table = next(s for s in slides[1].shapes if s.has_table).table
    assert str(table.cell(0, 0).fill.fore_color.rgb) == t.head and str(table.cell(1, 0).fill.fore_color.rgb) == t.surface
    assert any("Jahresbericht" in s.text_frame.text for s in slides[1].shapes if s.has_text_frame and s.text_frame.text != "Abschnitt eins")  # Fußzeile
    assert slides[3].notes_slide.notes_text_frame.text == "Sprechtext"
    assert {r.font.name for sh in slides[1].shapes if sh.has_text_frame for p in sh.text_frame.paragraphs for r in p.runs} == {"Georgia", "Calibri"}


def test_docx_has_footer_page_field_borders_and_theme_colors():
    import docx

    t = design.THEMES["ozean"]
    data, _ = outbox.render("b.docx", MD, "T", theme="ozean")
    doc = docx.Document(io.BytesIO(data))
    assert str(doc.styles["Heading 1"].font.color.rgb) == t.dark and str(doc.styles["Heading 2"].font.color.rgb) == t.head
    xml = doc.element.xml
    assert t.head in xml and 'w:tblBorders' in xml and "pBdr" in xml
    footer = doc.sections[0].footer._element.xml
    assert "PAGE" in footer and "Seite" in footer


def test_xlsx_header_and_banding():
    import openpyxl

    t = design.THEMES["wald"]
    rows = '{"sheets":[{"name":"Z","rows":[["A","B"],[1,2],[3,4],[5,6],[7,8]]}]}'
    ws = openpyxl.load_workbook(io.BytesIO(outbox.render("z.xlsx", rows, "T", theme="wald")[0]))["Z"]
    assert ws["A1"].fill.fgColor.rgb.endswith(t.head)
    assert ws["A3"].fill.fgColor.rgb.endswith(t.surface) and ws["A2"].fill.fill_type is None


def test_pdf_renders_with_every_theme():
    for key in design.THEMES:
        data, mime = outbox.render("p.pdf", MD + "\n\n```\ncode\n```\n\n> Zitat", "T", theme=key)
        assert data.startswith(b"%PDF") and mime == "application/pdf"
    assert outbox.render("p.pdf", MD, "T", accent="#C2410C")[0].startswith(b"%PDF")


# ---------------------------------------------------------------------- Werkzeug

def make_box():
    class Store:
        def outfile_usage(self, _):
            return 0

        def outfile_add(self, profile, chat, name, mime, data, days):
            return {"id": "f1", "size": len(data)}

    events = []
    counter = iter(range(1, 99))
    return outbox.OutboxToolbox(Store(), "p", "c", record=events.append, next_id=lambda: next(counter), keep_days=7), events


def test_design_guide_tool_is_offered_with_and_without_edit_and_returns_text():
    box, _ = make_box()
    names = [s.name for s in box.specs()]
    assert names[:3] == ["file_create", "file_preview", "design_guide"]
    box.edit = False
    specs = {s.name: s for s in box.specs()}
    assert set(specs) == {"file_create", "file_preview", "design_guide"} and specs["design_guide"].level == "read"
    assert "theme" in specs["file_create"].schema["properties"] and "accent" in specs["file_create"].schema["properties"]
    assert specs["file_create"].schema["properties"]["theme"]["enum"] == list(design.THEMES)
    text = run(specs["design_guide"].handler({"topic": "folien"}))
    assert text == design.guide("folien")
    with pytest.raises(ToolError):
        run(specs["design_guide"].handler({"topic": "comic"}))


def test_file_create_returns_hints_and_applies_theme():
    box, _ = make_box()
    reply = run(box.file_create({"name": "d.pptx", "content": BAD_DECK, "theme": "beere"}))
    assert "Datei d.pptx erstellt" in reply and "Gestaltungshinweise" in reply
    reply = run(box.file_create({"name": "ok.docx", "content": "# Titel\n\nText."}))
    assert "Gestaltungshinweise" not in reply
    with pytest.raises(ToolError, match="Unbekanntes Thema"):
        run(box.file_create({"name": "x.docx", "content": "# a", "theme": "neon"}))
