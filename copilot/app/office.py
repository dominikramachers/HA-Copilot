"""Word (.docx), Excel (.xlsx) und PowerPoint (.pptx) in Text umwandeln, ohne zusätzliche Pakete.

Alle Formate sind ZIP-Archive mit XML. Gelesen wird nur das Nötige (Text, Tabellen, Zellwerte), und das
mit Schutz gegen präparierte Dateien: begrenzte Anzahl und entpackte Größe der Einträge, keine XML-Entitäten
oder DOCTYPE-Deklarationen. Nichts davon wird auf die Platte geschrieben.
"""
from __future__ import annotations

import io
import re
import zipfile
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET

from .i18n import tr

MAX_ENTRIES = 3000
MAX_MEMBER_BYTES = 40 * 1024 * 1024  # entpackt, je XML-Teil
MAX_TOTAL_UNPACKED = 160 * 1024 * 1024
MAX_ROWS_PER_SHEET = 5000
MAX_COLUMNS = 200

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


class OfficeError(ValueError):
    """Meldung ohne Dateinamen; der Aufrufer ergänzt ihn."""


def pdf_to_text(data: bytes, max_chars: int) -> str:
    """Text eines PDFs auslesen (nur im Arbeitsspeicher); bricht beim Zeichenlimit ab."""
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise OfficeError(tr("ist passwortgeschützt."))
        parts: list[str] = []
        total = 0
        for page in reader.pages:
            text = (page.extract_text() or "").strip()
            if text:
                parts.append(text)
                total += len(text)
            if total >= max_chars:
                break
    except OfficeError:
        raise
    except (PyPdfError, ValueError, KeyError, RecursionError, OSError):
        raise OfficeError(tr("ist beschädigt oder kein lesbares PDF.")) from None
    return "\n\n".join(parts)[:max_chars]


def _open(data: bytes) -> zipfile.ZipFile:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise OfficeError(tr("ist beschädigt oder kein gültiges Office-Dokument.")) from None
    infos = zf.infolist()
    if len(infos) > MAX_ENTRIES or sum(i.file_size for i in infos) > MAX_TOTAL_UNPACKED:
        raise OfficeError(tr("ist ungewöhnlich aufgebaut und wird aus Sicherheitsgründen nicht gelesen."))
    return zf


def kind_of(data: bytes) -> str | None:
    """``word``, ``excel``, ``powerpoint`` oder ``None`` (anderes ZIP). Wirft OfficeError für kaputte Archive."""
    if data.startswith(OLE_MAGIC):
        raise OfficeError(
            tr("ist ein altes Office-Format (.doc/.xls) oder passwortgeschützt. Bitte als .docx bzw. .xlsx ohne Passwort speichern.")
        )
    if not data.startswith(b"PK\x03\x04"):
        return None
    names = set(_open(data).namelist())
    if "word/document.xml" in names:
        return "word"
    if "xl/workbook.xml" in names:
        return "excel"
    if "ppt/presentation.xml" in names:
        return "powerpoint"
    return None


def _xml(zf: zipfile.ZipFile, name: str, required: bool = True) -> ET.Element | None:
    try:
        info = zf.getinfo(name)
    except KeyError:
        if required:
            raise OfficeError(tr("ist unvollständig (Teil fehlt).")) from None
        return None
    if info.file_size > MAX_MEMBER_BYTES:
        raise OfficeError(tr("ist zu groß zum Auslesen."))
    with zf.open(info) as fh:
        raw = fh.read(MAX_MEMBER_BYTES + 1)
    if len(raw) > MAX_MEMBER_BYTES:
        raise OfficeError(tr("ist zu groß zum Auslesen."))
    head = raw[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in raw[:65536].lower():
        raise OfficeError(tr("enthält unzulässige XML-Deklarationen und wird nicht gelesen."))
    try:
        return ET.fromstring(raw)
    except ET.ParseError:
        raise OfficeError(tr("ist beschädigt (XML nicht lesbar).")) from None


# ------------------------------------------------------------------- Word

_HEADING = re.compile(r"^(heading|berschrift|überschrift|title|titel)\s*(\d)?$", re.I)
_LIST_STYLE = re.compile(r"^(list|listen|aufz|aufzählung)", re.I)


def _para(p: ET.Element) -> str:
    out: list[str] = []
    for el in p.iter():
        if el.tag == W + "t" and el.text:
            out.append(el.text)
        elif el.tag == W + "tab":
            out.append("\t")
        elif el.tag in (W + "br", W + "cr"):
            out.append("\n")
        elif el.tag == W + "noBreakHyphen":
            out.append("-")
    text = "".join(out).strip()
    if not text:
        return ""
    ppr = p.find(W + "pPr")
    if ppr is not None:
        style = ppr.find(W + "pStyle")
        match = _HEADING.match(style.get(W + "val", "")) if style is not None else None
        if match:
            level = int(match.group(2) or 1)
            return "#" * min(level, 6) + " " + text
        if ppr.find(W + "numPr") is not None or (style is not None and _LIST_STYLE.match(style.get(W + "val", ""))):
            return "- " + text
    return text


def _walk_block(node: ET.Element, lines: list[str]) -> None:
    for child in node:
        if child.tag == W + "p":
            lines.append(_para(child))
        elif child.tag == W + "tbl":
            for row in child.iter(W + "tr"):
                cells = []
                for cell in row.findall(W + "tc"):
                    cells.append(" ".join(t for t in (_para(p) for p in cell.iter(W + "p")) if t))
                if any(cells):
                    lines.append("| " + " | ".join(cells) + " |")
            lines.append("")
        elif child.tag == W + "sdt":
            content = child.find(W + "sdtContent")
            if content is not None:
                _walk_block(content, lines)


def docx_to_text(data: bytes, limit: int) -> str:
    zf = _open(data)
    root = _xml(zf, "word/document.xml")
    body = root.find(W + "body") if root is not None else None
    if body is None:
        raise OfficeError(tr("enthält keinen Text."))
    lines: list[str] = []
    _walk_block(body, lines)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    if not text:
        raise OfficeError(tr("enthält keinen lesbaren Text."))
    return _cut(text, limit)


# ------------------------------------------------------------------ Excel

_BUILTIN_DATE_IDS = set(range(14, 23)) | {27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 45, 46, 47, 50, 51, 52, 53, 54, 55, 56, 57, 58}


def _is_date_format(code: str) -> bool:
    cleaned = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.|_.|\*.', "", code)
    return bool(re.search(r"[dmyhs]", cleaned, re.I)) and "General" not in code


def _date_styles(zf: zipfile.ZipFile) -> set[int]:
    root = _xml(zf, "xl/styles.xml", required=False)
    if root is None:
        return set()
    custom = {
        int(n.get("numFmtId", -1)): n.get("formatCode", "") for n in root.iter(S + "numFmt") if n.get("numFmtId", "").isdigit()
    }
    xfs = root.find(S + "cellXfs")
    result: set[int] = set()
    for index, xf in enumerate(xfs if xfs is not None else []):
        fmt = int(xf.get("numFmtId", "0") or 0)
        if fmt in custom:
            if _is_date_format(custom[fmt]):
                result.add(index)
        elif fmt in _BUILTIN_DATE_IDS:
            result.add(index)
    return result


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    root = _xml(zf, "xl/sharedStrings.xml", required=False)
    if root is None:
        return []
    out = []
    for si in root.findall(S + "si"):
        parts = []
        for child in si:
            if child.tag == S + "t":
                parts.append(child.text or "")
            elif child.tag == S + "r":
                parts.extend(t.text or "" for t in child.findall(S + "t"))
        out.append("".join(parts))
    return out


def _column(ref: str) -> int:
    letters = re.match(r"[A-Za-z]+", ref)
    index = 0
    for ch in (letters.group(0).upper() if letters else "A"):
        index = index * 26 + ord(ch) - 64
    return index - 1


def _number(text: str, as_date: bool) -> str:
    try:
        value = float(text)
    except ValueError:
        return text
    if as_date and 0 < value < 2958466:
        moment = datetime(1899, 12, 30) + timedelta(days=value)
        return moment.strftime("%d.%m.%Y") if value == int(value) else moment.strftime("%d.%m.%Y %H:%M")
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.10g}"


def _sheet_targets(zf: zipfile.ZipFile) -> list[tuple[str, str]]:
    book = _xml(zf, "xl/workbook.xml")
    rels = _xml(zf, "xl/_rels/workbook.xml.rels")
    targets = {r.get("Id"): r.get("Target", "") for r in (rels if rels is not None else []).iter(PKG_REL + "Relationship")}
    result = []
    for sheet in (book if book is not None else []).iter(S + "sheet"):
        if sheet.get("state") in ("hidden", "veryHidden"):
            continue
        target = targets.get(sheet.get(R + "id"), "")
        if not target:
            continue
        path = target.lstrip("/") if target.startswith("/") else "xl/" + target
        result.append((sheet.get("name", "Blatt"), re.sub(r"[^/]+/\.\./", "", path)))
    return result


def xlsx_to_text(data: bytes, limit: int) -> str:
    zf = _open(data)
    strings = _shared_strings(zf)
    date_styles = _date_styles(zf)
    sections: list[str] = []
    used = 0
    for name, path in _sheet_targets(zf):
        root = _xml(zf, path, required=False)
        if root is None:
            continue
        rows: list[str] = []
        for count, row in enumerate(root.iter(S + "row")):
            if count >= MAX_ROWS_PER_SHEET:
                rows.append(f"[… weitere Zeilen nicht übernommen (mehr als {MAX_ROWS_PER_SHEET}) …]")
                break
            cells: dict[int, str] = {}
            for c in row.findall(S + "c"):
                col = _column(c.get("r", ""))
                if col >= MAX_COLUMNS:
                    continue
                kind = c.get("t")
                v = c.find(S + "v")
                if kind == "s" and v is not None and (v.text or "").isdigit():
                    index = int(v.text)
                    value = strings[index] if index < len(strings) else ""
                elif kind == "inlineStr":
                    value = "".join(t.text or "" for t in c.iter(S + "t"))
                elif kind == "b":
                    value = "WAHR" if v is not None and v.text == "1" else "FALSCH"
                elif v is not None and v.text is not None:
                    value = v.text if kind in ("str", "e") else _number(v.text, int(c.get("s", "-1") or -1) in date_styles)
                else:
                    value = ""
                value = " ".join(value.split())
                if value:
                    cells[col] = value
            if cells:
                width = max(cells) + 1
                rows.append(" | ".join(cells.get(i, "") for i in range(width)))
        if not rows:
            continue
        section = f"## Tabellenblatt: {name}\n" + "\n".join(rows)
        sections.append(section)
        used += len(section)
        if used > limit:
            break
    if not sections:
        raise OfficeError(tr("enthält keine Zellwerte."))
    return _cut("\n\n".join(sections), limit)


# ------------------------------------------------------------- PowerPoint

def _slide_paths(zf: zipfile.ZipFile) -> list[str]:
    """Pfade der Folien in Präsentationsreihenfolge."""
    root = _xml(zf, "ppt/presentation.xml")
    rels = _xml(zf, "ppt/_rels/presentation.xml.rels", required=False)
    if root is None or rels is None:
        return []
    targets = {r.get("Id"): r.get("Target", "") for r in rels.findall(PKG_REL + "Relationship")}
    result = []
    for sld in root.iter(P + "sldId"):
        target = targets.get(sld.get(R + "id"), "")
        if not target:
            continue
        path = target.lstrip("/") if target.startswith("/") else "ppt/" + target
        result.append(re.sub(r"[^/]+/\.\./", "", path))
    return result


def _notes_root(zf: zipfile.ZipFile, slide_path: str) -> ET.Element | None:
    """Notizseite einer Folie über deren Beziehungen (die Nummern in den Dateinamen stimmen nicht immer überein)."""
    folder, _, name = slide_path.rpartition("/")
    rels = _xml(zf, f"{folder}/_rels/{name}.rels", required=False)
    if rels is None:
        return None
    for rel in rels.findall(PKG_REL + "Relationship"):
        if rel.get("Type", "").endswith("/notesSlide"):
            target = rel.get("Target", "")
            path = target.lstrip("/") if target.startswith("/") else f"{folder}/{target}"
            path = path.replace("/./", "/")
            while "/../" in path:
                path = re.sub(r"[^/]+/\.\./", "", path, count=1)
            return _xml(zf, path, required=False)
    return None


def _shape_lines(tree: ET.Element) -> list[str]:
    lines: list[str] = []
    for node in tree.iter():
        if node.tag == A + "p":
            text = "".join(t.text or "" for t in node.iter(A + "t")).strip()
            if text:
                lines.append(text)
    return lines


def pptx_to_text(data: bytes, limit: int) -> str:
    zf = _open(data)
    sections: list[str] = []
    used = 0
    for number, path in enumerate(_slide_paths(zf), 1):
        root = _xml(zf, path, required=False)
        if root is None:
            continue
        lines = _shape_lines(root)
        notes = _notes_root(zf, path)
        note_lines = _shape_lines(notes) if notes is not None else []
        note_lines = [n for n in note_lines if not n.isdigit()]
        section = f"## Folie {number}\n" + "\n".join(lines)
        if note_lines:
            section += "\n[Notizen] " + " ".join(note_lines)
        sections.append(section)
        used += len(section)
        if used > limit:
            break
    if not any("\n" in sec and sec.split("\n", 1)[1].strip() for sec in sections):
        raise OfficeError(tr("enthält keinen lesbaren Text."))
    return _cut("\n\n".join(sections), limit)


def _cut(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rsplit("\n", 1)[0] + "\n[… gekürzt: der Rest der Datei wurde nicht übernommen …]"
