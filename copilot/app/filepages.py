"""Echte Vorschau erzeugter Dateien im Fenster neben dem Chat.

* PDF: Seiten werden mit pypdfium2 als Bild gezeichnet.
* Word und PowerPoint: LibreOffice macht daraus erst ein PDF (wie bei der Vorschau für die KI, ``preview.py``), dann dasselbe.
  Fehlt LibreOffice im Add-on, bleibt die Textvorschau.
* Excel: Die Blätter kommen als Tabelle mit Spaltenbreiten, Fett/Kursiv, Farben, Ausrichtung, verbundenen Zellen und Zahlenformaten.
  Formeln ohne gespeicherten Wert (Dateien, die nicht in Excel gespeichert wurden) erscheinen als Formel. Diagramme und Bilder fehlen;
  darauf weist die Ansicht hin.

Alles hier liest nur: Die Datei auf der Platte wird nie verändert. Die Kennung einer Datei ändert sich bei jeder Fassung, deshalb darf alles
nach Kennung zwischengespeichert werden.
"""
from __future__ import annotations

import asyncio
import colorsys
import io
import re
import threading
from collections import OrderedDict
from datetime import date, datetime, time as dtime, timedelta

from . import i18n, preview
from .i18n import tr

MAX_PAGES = 150  # so viele Seiten zeigt das Fenster höchstens
MIN_WIDTH, MAX_WIDTH, DEFAULT_WIDTH = 400, 1800, 1000
MAX_XLSX_BYTES = 6_000_000  # größere Arbeitsmappen bleiben bei der Textvorschau (Laden und Gestalten wären zu schwer)
MAX_ROWS, MAX_COLS, MAX_SHEETS = 300, 40, 20
PDF_CACHE_ENTRIES = 6
PDF_CACHE_BYTES = 80_000_000
PAGE_EXTS = {"pdf", "docx", "pptx", "odt", "odp"}
OFFICE_TO_PDF = {"docx", "pptx", "odt", "odp"}


class ViewError(ValueError):
    """Zu dieser Datei gibt es keine echte Vorschau (Meldung für die Person)."""


def extension(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def capability(name: str) -> str | None:
    """``pages`` (Seiten als Bild), ``sheets`` (Tabellenblätter) oder ``None``. Es wird nichts umgewandelt, nur geprüft, ob es gehen kann."""
    ext = extension(name)
    if ext == "pdf":
        return "pages" if _pdfium() else None
    if ext in OFFICE_TO_PDF:
        return "pages" if _pdfium() and preview.soffice_path() else None
    if ext == "xlsx":
        return "sheets"
    return None


def _pdfium():
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return None
    return pdfium


# ---------------------------------------------------------------------------------------------------- Seiten

_pdf_cache: OrderedDict[str, bytes] = OrderedDict()
_pdf_lock = threading.Lock()  # pypdfium2 ist nicht für gleichzeitige Zugriffe gebaut
_convert_locks: dict[tuple[int, str], asyncio.Lock] = {}


def _cache_put(key: str, pdf: bytes) -> None:
    with _pdf_lock:
        _pdf_cache[key] = pdf
        _pdf_cache.move_to_end(key)
        while len(_pdf_cache) > PDF_CACHE_ENTRIES or (len(_pdf_cache) > 1 and sum(map(len, _pdf_cache.values())) > PDF_CACHE_BYTES):
            _pdf_cache.popitem(last=False)


def _cache_get(key: str) -> bytes | None:
    with _pdf_lock:
        pdf = _pdf_cache.get(key)
        if pdf is not None:
            _pdf_cache.move_to_end(key)
        return pdf


async def pdf_for(key: str, name: str, data: bytes) -> bytes:
    """Die Datei als PDF (Word und PowerPoint werden umgewandelt; das Ergebnis bleibt kurz im Speicher). Wirft :class:`ViewError`."""
    ext = extension(name)
    if ext == "pdf":
        return data
    if ext not in OFFICE_TO_PDF:
        raise ViewError(tr("Für diese Dateiart gibt es keine Seitenansicht."))
    cached = _cache_get(key)
    if cached is not None:
        return cached
    lock = _convert_locks.setdefault((id(asyncio.get_running_loop()), key), asyncio.Lock())
    try:
        async with lock:
            cached = _cache_get(key)
            if cached is not None:
                return cached
            try:
                pdf = await preview.office_to_pdf(ext, data)
            except preview.PreviewError:
                raise ViewError(tr("Die Seitenansicht ist gerade nicht möglich (LibreOffice fehlt oder hat die Datei nicht lesen können). Es bleibt die Textvorschau.")) from None
            _cache_put(key, pdf)
            return pdf
    finally:
        _convert_locks.pop((id(asyncio.get_running_loop()), key), None)


def page_sizes(pdf: bytes) -> tuple[list[list[float]], int]:
    """Breite und Höhe der ersten Seiten (in Punkt) und die Zahl aller Seiten. Wirft :class:`ViewError`."""
    pdfium = _pdfium()
    if pdfium is None:
        raise ViewError(tr("Die Seitenansicht ist in diesem Add-on nicht möglich."))
    with _pdf_lock:
        try:
            doc = pdfium.PdfDocument(pdf)
        except Exception:
            raise ViewError(tr("Das PDF lässt sich nicht öffnen (beschädigt oder mit Kennwort geschützt).")) from None
        try:
            total = len(doc)
            if total == 0:
                raise ViewError(tr("Die Datei hat keine Seiten."))
            sizes = []
            for index in range(min(total, MAX_PAGES)):
                w, h = doc[index].get_size()
                sizes.append([round(w, 1), round(h, 1)])
            return sizes, total
        finally:
            doc.close()


_png_cache: OrderedDict[tuple, bytes] = OrderedDict()
PNG_CACHE_ENTRIES = 60
PNG_CACHE_BYTES = 30_000_000


def render_page(pdf: bytes, index: int, width: int, key: str | None = None) -> bytes:
    """Eine Seite (``index`` ab 0) als PNG in dieser Breite. Mit ``key`` (Kennung der Datei) bleiben die letzten Seiten im Speicher,
    denn die Antworten der Schnittstelle dürfen nicht im Browser liegen bleiben und die Person blättert hin und her. Wirft :class:`ViewError`."""
    pdfium = _pdfium()
    if pdfium is None:
        raise ViewError(tr("Die Seitenansicht ist in diesem Add-on nicht möglich."))
    width = max(MIN_WIDTH, min(MAX_WIDTH, int(width)))
    width = (width + 49) // 100 * 100  # in Hunderterschritten: gleiche Bilder werden wiederverwendet
    cache_key = (key, index, width)
    if key is not None:
        with _pdf_lock:
            hit = _png_cache.get(cache_key)
            if hit is not None:
                _png_cache.move_to_end(cache_key)
                return hit
    png = _render(pdfium, pdf, index, width)
    if key is not None:
        with _pdf_lock:
            _png_cache[cache_key] = png
            while len(_png_cache) > PNG_CACHE_ENTRIES or (len(_png_cache) > 1 and sum(map(len, _png_cache.values())) > PNG_CACHE_BYTES):
                _png_cache.popitem(last=False)
    return png


def _render(pdfium, pdf: bytes, index: int, width: int) -> bytes:
    with _pdf_lock:
        try:
            doc = pdfium.PdfDocument(pdf)
        except Exception:
            raise ViewError(tr("Das PDF lässt sich nicht öffnen (beschädigt oder mit Kennwort geschützt).")) from None
        try:
            if not 0 <= index < min(len(doc), MAX_PAGES):
                raise ViewError(tr("Diese Seite gibt es nicht."))
            page = doc[index]
            image = page.render(scale=width / max(page.get_width(), 1)).to_pil().convert("RGB")
        finally:
            doc.close()
    out = io.BytesIO()
    image.save(out, "PNG", compress_level=3)
    return out.getvalue()


# ------------------------------------------------------------------------------------------------ Tabellen

_THEME = ["FFFFFF", "000000", "E7E6E6", "44546A", "4472C4", "ED7D31", "A5A5A5", "FFC000", "5B9BD5", "70AD47"]  # Standard-Farbschema von Office
_DE_MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]
_DE_DAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
_EN_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
_EN_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _tint(rgb: str, tint: float) -> str:
    r, g, b = (int(rgb[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l = l * (1 + tint) if tint < 0 else l * (1 - tint) + tint
    r, g, b = colorsys.hls_to_rgb(h, max(0.0, min(1.0, l)), s)
    return "".join(f"{round(c * 255):02X}" for c in (r, g, b))


def _color(color) -> str | None:
    """Farbe einer Zelle als ``#RRGGBB``; ``None`` bei Standard oder Unbekanntem."""
    if color is None:
        return None
    try:
        kind = color.type
        if kind == "rgb" and isinstance(color.rgb, str) and re.fullmatch(r"[0-9A-Fa-f]{8}", color.rgb):
            return "#" + color.rgb[2:].upper()
        if kind == "theme" and isinstance(color.theme, int) and 0 <= color.theme < len(_THEME):
            return "#" + _tint(_THEME[color.theme], float(color.tint or 0))
        if kind == "indexed" and isinstance(color.indexed, int):
            from openpyxl.styles.colors import COLOR_INDEX

            if 0 <= color.indexed < len(COLOR_INDEX):
                return "#" + COLOR_INDEX[color.indexed][2:]
    except (AttributeError, ValueError, TypeError):
        return None
    return None


def _separators(lang: str) -> tuple[str, str]:
    return (".", ",") if lang == "de" else (",", ".")  # (Tausender, Dezimal)


def _date_format(fmt: str, lang: str) -> str | None:
    """Zahlenformat mit Datum/Uhrzeit in ein ``strftime``-Muster übersetzen (``None``: kein Datumsformat)."""
    section = fmt.split(";")[0]
    cleaned = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.|_.|\*.', "", section)
    if not re.search(r"[dmyhs]", cleaned, re.I) or "General" in fmt:
        return None
    out: list[str] = []
    rest = re.sub(r"\[(?:h+|m+|s+)\]", lambda m: m.group(0)[1:-1], section)
    tokens = re.findall(r'"[^"]*"|\\.|_.|\*.|\[[^\]]*\]|AM/PM|A/P|yyyy|yy|mmmmm|mmmm|mmm|mm|m|dddd|ddd|dd|d|hh|h|ss|s|.', rest, re.I)
    for index, token in enumerate(tokens):
        low = token.lower()
        if token.startswith('"'):
            out.append(token[1:-1].replace("%", "%%"))
        elif token.startswith(("\\", "_", "*")):
            out.append(token[1:].replace("%", "%%") if token.startswith("\\") else " " if token.startswith("_") else "")
        elif token.startswith("["):
            continue
        elif low in ("am/pm", "a/p"):
            out.append("%p")
        elif low in ("yyyy", "yy"):
            out.append("%Y" if low == "yyyy" else "%y")
        elif low in ("dddd", "ddd"):
            out.append("{DAYNAME}" if low == "dddd" else "{DAYABBR}")
        elif low in ("dd", "d"):
            out.append("%d" if low == "dd" else "{D}")
        elif low in ("hh", "h"):
            out.append("%H" if low == "hh" else "{H}")
        elif low in ("ss", "s"):
            out.append("%S" if low == "ss" else "{S}")
        elif low in ("mmmm", "mmmmm"):
            out.append("{MONTHNAME}")
        elif low == "mmm":
            out.append("{MONTHABBR}")
        elif low in ("mm", "m"):
            before = "".join(tokens[:index]).lower()
            after = "".join(tokens[index + 1:]).lower()
            minute = bool(re.search(r"h\W*$", before)) or bool(re.match(r"\W*s", after))
            out.append(("%M" if low == "mm" else "{MIN}") if minute else ("%m" if low == "mm" else "{M}"))
        else:
            out.append(token.replace("%", "%%"))
    return "".join(out)


def _format_date(value, pattern: str, lang: str) -> str:
    months, days = (_DE_MONTHS, _DE_DAYS) if lang == "de" else (_EN_MONTHS, _EN_DAYS)
    if isinstance(value, dtime):
        value = datetime.combine(date(1900, 1, 1), value)
    elif isinstance(value, date) and not isinstance(value, datetime):
        value = datetime.combine(value, dtime())
    if isinstance(value, timedelta):
        value = datetime(1900, 1, 1) + value
    try:
        text = value.strftime(pattern)
    except ValueError:
        return str(value)
    return (text.replace("{MONTHNAME}", months[value.month - 1]).replace("{MONTHABBR}", months[value.month - 1][:3])
            .replace("{DAYNAME}", days[value.weekday()]).replace("{DAYABBR}", days[value.weekday()][:2 if lang == "de" else 3])
            .replace("{D}", str(value.day)).replace("{M}", str(value.month)).replace("{H}", str(value.hour))
            .replace("{MIN}", str(value.minute)).replace("{S}", str(value.second)))


def _number_text(value: float, fmt: str, lang: str) -> str:
    thousands, decimal = _separators(lang)
    section = fmt.split(";")[0] if fmt else "General"
    if value < 0 and ";" in fmt and len(fmt.split(";")) > 1:
        section = fmt.split(";")[1]
    if section == "General" or not re.search(r"[0#?]", section):
        text = str(int(value)) if value == int(value) and abs(value) < 1e15 else f"{value:.10g}"
        return text.replace(".", decimal) if decimal != "." else text
    plain = re.sub(r'\[(?!\$)[^\]]*\]', "", section)  # Farben und Bedingungen
    placeholder = re.search(r"[#0?][#0?,.]*", plain)
    if not placeholder:
        return str(value)
    prefix = plain[:placeholder.start()]
    suffix = plain[placeholder.end():]

    def literal(part: str) -> str:
        part = re.sub(r'"([^"]*)"', r"\1", part)
        part = re.sub(r"\[\$([^\]\-]*)(?:-[^\]]*)?\]", r"\1", part)
        part = re.sub(r"\\(.)", r"\1", part)
        part = re.sub(r"_.|\*.", " ", part)
        return part.replace("?", "")

    percent = "%" in plain
    number = placeholder.group(0)
    decimals = len(number.split(".")[1].replace(",", "")) if "." in number else 0
    use_thousands = "," in number.split(".")[0]
    shown = abs(value) * (100 if percent else 1)
    if re.search(r"[eE][+-]", plain):
        text = f"{shown:.{decimals}E}"
    else:
        text = f"{shown:,.{decimals}f}" if use_thousands else f"{shown:.{decimals}f}"
        text = text.replace(",", "\0").replace(".", decimal).replace("\0", thousands)
    sign = "-" if value < 0 and ";" not in fmt else ""
    return f"{sign}{literal(prefix)}{text}{literal(suffix)}"


def display(value, fmt: str, lang: str) -> str:
    """Wert einer Zelle so, wie Excel ihn mit diesem Zahlenformat anzeigt (die gängigen Formate; Seltenes bleibt schlicht)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return ("WAHR" if value else "FALSCH") if lang == "de" else ("TRUE" if value else "FALSE")
    if isinstance(value, (datetime, date, dtime, timedelta)):
        pattern = _date_format(fmt or "", lang)
        if pattern is None:
            if isinstance(value, datetime):
                pattern = "%d.%m.%Y %H:%M" if lang == "de" else "%d/%m/%Y %H:%M"
                if value.hour == value.minute == value.second == 0:
                    pattern = pattern.split(" ")[0]
            elif isinstance(value, dtime):
                pattern = "%H:%M:%S"
            else:
                pattern = "%d.%m.%Y" if lang == "de" else "%d/%m/%Y"
        return _format_date(value, pattern, lang)
    if isinstance(value, (int, float)):
        return _number_text(float(value), fmt or "General", lang)
    return str(value)


def _style_of(cell, number: bool) -> tuple:
    font, fill, align = cell.font, cell.fill, cell.alignment
    bg = _color(fill.fgColor) if fill is not None and fill.fill_type == "solid" else None
    fg = _color(font.color) if font is not None and font.color is not None else None
    if fg == "#000000":
        fg = None
    horizontal = align.horizontal if align is not None and align.horizontal in ("left", "center", "right") else ("right" if number else None)
    return (bool(font and font.b), bool(font and font.i), fg, bg, horizontal, bool(align and align.wrap_text))


def sheets(data: bytes, lang: str | None = None) -> dict:
    """Die Blätter einer Excel-Datei für die Tabellenansicht. Wirft :class:`ViewError`."""
    lang = lang or i18n.language()
    if len(data) > MAX_XLSX_BYTES:
        raise ViewError(tr("Diese Arbeitsmappe ist für die Tabellenansicht zu groß. Es bleibt die Textvorschau."))
    try:
        from openpyxl import load_workbook
        from openpyxl.utils import get_column_letter

        values = load_workbook(io.BytesIO(data), data_only=True)
        formulas = load_workbook(io.BytesIO(data), data_only=False)
    except Exception:
        raise ViewError(tr("Die Tabelle konnte nicht gelesen werden.")) from None
    styles: list[tuple] = []
    style_index: dict[tuple, int] = {}
    result = []
    for ws in values.worksheets:
        if ws.sheet_state != "visible":
            continue
        if len(result) >= MAX_SHEETS:
            break
        wf = formulas[ws.title]
        rows_total, cols_total = ws.max_row or 0, ws.max_column or 0
        rows_n, cols_n = min(rows_total, MAX_ROWS), min(cols_total, MAX_COLS)
        rows = []
        for r in range(1, rows_n + 1):
            line = []
            for c in range(1, cols_n + 1):
                cell = ws.cell(row=r, column=c)
                value = cell.value
                text = ""
                number = isinstance(value, (int, float)) and not isinstance(value, bool)
                if value is None:
                    formula = wf.cell(row=r, column=c).value
                    if isinstance(formula, str) and formula.startswith("="):
                        text, number = formula, False
                else:
                    text = display(value, cell.number_format, lang)
                style = _style_of(cell, number)
                if style == (False, False, None, None, None, False) and (not number):
                    line.append(text)
                    continue
                idx = style_index.get(style)
                if idx is None:
                    idx = style_index[style] = len(styles)
                    styles.append(style)
                line.append([text, idx])
            rows.append(line)
        while rows and all(cell == "" for cell in rows[-1]):  # leere Zeilen am Ende weglassen
            rows.pop()
        widths = []
        for c in range(1, cols_n + 1):
            dim = ws.column_dimensions.get(get_column_letter(c))
            if dim is not None and dim.width:
                widths.append(int(max(2.0, min(float(dim.width), 80.0)) * 7 + 5))
                continue
            # Keine Breite gespeichert (Datei nicht in Excel entstanden): so breit, dass der Inhalt der ersten Zeilen passt
            longest = max((len(row[c - 1][0] if isinstance(row[c - 1], list) else row[c - 1]) for row in rows[:60] if c - 1 < len(row)), default=0)
            widths.append(int(max(64, min(longest * 7.4 + 16, 320))))
        merges = []
        for rng in ws.merged_cells.ranges:
            if rng.min_row <= rows_n and rng.min_col <= cols_n:
                merges.append([rng.min_row, rng.min_col, min(rng.max_row, rows_n), min(rng.max_col, cols_n)])
        result.append({
            "name": ws.title, "rows": rows, "widths": widths, "merges": merges, "rows_total": rows_total, "cols_total": cols_total,
            "truncated": rows_total > rows_n or cols_total > cols_n,
            "extras": {"charts": len(getattr(wf, "_charts", None) or []), "images": len(getattr(wf, "_images", None) or [])},
        })
    if not result:
        raise ViewError(tr("Die Tabelle hat kein sichtbares Blatt."))
    packed = [{"b": s[0], "i": s[1], "c": s[2], "f": s[3], "a": s[4], "w": s[5]} for s in styles]
    return {"mode": "sheets", "sheets": result, "styles": packed, "limit": {"rows": MAX_ROWS, "cols": MAX_COLS}}
