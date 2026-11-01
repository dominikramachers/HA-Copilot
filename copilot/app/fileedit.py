"""Dateien lesen und bearbeiten: Text/Code, Word, Excel, PowerPoint und PDF.

Die KI arbeitet mit zwei Werkzeugen (siehe ``outbox.py``):

* ``read_file(kind, name, data, part)`` liefert eine nummerierte Ansicht der Datei, auf die sich die Änderungen beziehen
  (Zeilen, Absätze ``[P3]``, Tabellen ``[T1]``, Zellen ``B7``, Folien und Formen ``[S2]``, Seiten und Formularfelder).
* ``edit_file(kind, name, data, operations, ctx)`` wendet eine Liste von Änderungen an und liefert die neue Datei.
  Alles oder nichts: scheitert eine Änderung, wird nichts gespeichert und die KI erfährt, welche und warum.

Die Dateien werden mit python-docx, openpyxl, python-pptx, pypdf und fpdf2 bearbeitet (optional wie bei ``file_create``;
fehlt eine Bibliothek, melden die Werkzeuge es verständlich). Es wird nie etwas ausgeführt: weder Makros noch Formeln,
und Formeln mit gefährlichen Funktionen (WEBSERVICE, DDE …) werden entschärft wie beim Erzeugen.

Nummern in Anfragen (Absatz, Tabelle, Folie, Seite, Form) beziehen sich auf den Stand von ``read_file``, bevor die erste
Änderung der Anfrage angewendet wird. Ausnahmen: Excel-Zeilen/Spalten und Zellen (sie wirken der Reihe nach, wie in Excel)
und Seiten-Befehle bei PDF (die Seitenliste ändert sich dort der Reihe nach, ``reorder``/``delete_pages`` am besten allein).
"""
from __future__ import annotations

import copy
import io
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .ha_tools import ToolError

MAX_EDIT_BYTES = 25 * 1024 * 1024
MAX_READ_CHARS = 50_000
MAX_OPERATIONS = 200
MAX_CELLS = 50_000
KINDS = ("text", "docx", "xlsx", "pptx", "pdf")


class EditError(ToolError):
    """Bearbeitung nicht möglich (Meldung geht an die KI)."""


@dataclass
class Context:
    """Was Bearbeitungen von außen brauchen."""

    author: str = "HA Copilot"
    get_file: Callable[[str], bytes | None] = lambda name: None  # andere Datei desselben Chats (z. B. zum Zusammenfügen)
    notes: list[str] = field(default_factory=list)  # Hinweise für die KI zum Ergebnis


def _missing(what: str) -> EditError:
    return EditError(f"Die Bibliothek für {what} ist in dieser Installation nicht verfügbar. Bearbeiten ist für dieses Format nicht möglich.")


# --------------------------------------------------------------- Parameterprüfung

def _str(op: dict, key: str, *, required: bool = True, allow_empty: bool = False) -> str:
    value = op.get(key)
    if value is None:
        if required:
            raise EditError(f"„{key}“ fehlt.")
        return ""
    if not isinstance(value, str):
        value = str(value)
    if required and not allow_empty and value == "":
        raise EditError(f"„{key}“ darf nicht leer sein.")
    return value


def _int(op: dict, key: str, *, minimum: int = 1, default: int | None = None) -> int:
    value = op.get(key, default)
    if value is None:
        raise EditError(f"„{key}“ fehlt.")
    if isinstance(value, bool):
        raise EditError(f"„{key}“ muss eine ganze Zahl sein.")
    try:
        number = int(str(value).strip().lstrip("PTSpts").strip())
    except ValueError:
        raise EditError(f"„{key}“ muss eine ganze Zahl sein (erhalten: {value!r}).") from None
    if number < minimum:
        raise EditError(f"„{key}“ muss mindestens {minimum} sein (erhalten: {number}).")
    return number


def _bool(op: dict, key: str, default: bool) -> bool:
    value = op.get(key, default)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "ja", "yes", "wahr")
    return bool(value)


def _range(spec: Any, total: int, what: str) -> tuple[int, int]:
    """'12-40', '12-' (bis zum Ende), '12' (nur eins) oder leer (alles) → (von, bis), 1-basiert und begrenzt."""
    if spec in (None, ""):
        return 1, max(total, 1) if total else 1
    m = re.fullmatch(r"\s*(\d+)\s*(?:([-–:])\s*(\d*))?\s*", str(spec))
    if not m:
        raise EditError(f"part „{spec}“ ist ungültig. Beispiel: \"1-80\" ({what}).")
    start = int(m.group(1))
    end = (int(m.group(3)) if m.group(3) else total) if m.group(2) else start
    if start < 1 or end < start:
        raise EditError(f"part „{spec}“ ist ungültig ({what} zählen ab 1, von ≤ bis).")
    if total and start > total:
        raise EditError(f"part „{spec}“ liegt hinter dem Ende ({total} {what}).")
    return start, min(end, total) if total else end


def _cut(lines: list[str], limit: int, hint: str) -> str:
    out: list[str] = []
    used = 0
    for index, line in enumerate(lines):
        used += len(line) + 1
        if used > limit and out:
            out.append(f"[… gekürzt nach {index} von {len(lines)} Einträgen. {hint}]")
            break
        out.append(line)
    return "\n".join(out)


# ================================================================== Textdateien

@dataclass
class _TextFormat:
    bom: bool
    encoding: str
    crlf: bool
    trailing_newline: bool


def decode_text(data: bytes) -> tuple[str, _TextFormat]:
    if b"\x00" in data[:8192]:
        raise EditError("Die Datei ist keine Textdatei (enthält Binärdaten).")
    bom = data.startswith(b"\xef\xbb\xbf")
    try:
        text = data.decode("utf-8-sig" if bom else "utf-8")
        encoding = "utf-8"
    except UnicodeDecodeError:
        text = data.decode("cp1252", "replace")
        encoding = "cp1252"
    crlf = "\r\n" in text and text.count("\r\n") * 2 >= text.count("\n")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text, _TextFormat(bom, encoding, crlf, text.endswith("\n"))


def encode_text(text: str, fmt: _TextFormat, ctx: Context | None = None) -> bytes:
    if fmt.crlf:
        text = text.replace("\n", "\r\n")
    encoding = fmt.encoding
    try:
        raw = text.encode(encoding)
    except UnicodeEncodeError:
        encoding = "utf-8"
        raw = text.encode("utf-8")
        if ctx is not None:
            ctx.notes.append("Die Datei war ursprünglich Windows-1252-kodiert, enthält nun aber Zeichen außerhalb davon; sie wurde als UTF-8 gespeichert.")
    return (b"\xef\xbb\xbf" + raw) if fmt.bom and encoding == "utf-8" else raw


def _split_lines(text: str) -> list[str]:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def read_text(data: bytes, part: Any) -> str:
    text, fmt = decode_text(data)
    lines = _split_lines(text)
    if not lines:
        return "(leere Datei)"
    start, end = _range(part, len(lines), "Zeilen")
    width = len(str(end))
    shown = [f"{n:>{width}} | {lines[n - 1]}" for n in range(start, end + 1)]
    head = f"Textdatei, {len(lines)} Zeilen, {fmt.encoding}{' mit BOM' if fmt.bom else ''}, {'CRLF' if fmt.crlf else 'LF'}-Zeilenenden. Zeilen {start}–{end}:"
    return head + "\n" + _cut(shown, MAX_READ_CHARS, f'Mit part="{start + len(shown) // 2}-…" gezielt weiterlesen')


def edit_text(data: bytes, ops: list[dict], ctx: Context) -> tuple[bytes, list[str]]:
    text, fmt = decode_text(data)
    lines = _split_lines(text)
    report: list[str] = []
    # Zeilenbefehle beziehen sich auf den Ausgangsstand und werden von unten nach oben angewendet.
    line_ops = [(i, op) for i, op in enumerate(ops) if op.get("op") in ("replace_lines", "insert_lines", "delete_lines")]
    edits: list[tuple[int, int, list[str], int, str]] = []  # (von, bis exklusiv, neue Zeilen, Befehlsnummer, Beschreibung)
    for i, op in line_ops:
        kind = op["op"]
        try:
            if kind == "insert_lines":
                after = _int(op, "after", minimum=0)
                if after > len(lines):
                    raise EditError(f"„after“ ist {after}, die Datei hat aber nur {len(lines)} Zeilen.")
                new = _str(op, "text", allow_empty=True).split("\n")
                edits.append((after, after, new, i, f"{len(new)} Zeile(n) nach Zeile {after} eingefügt"))
            else:
                first = _int(op, "start")
                last = _int(op, "end", default=first)
                if last < first or last > len(lines):
                    raise EditError(f"Zeilen {first}–{last} liegen außerhalb der Datei ({len(lines)} Zeilen).")
                new = _str(op, "text", allow_empty=True).split("\n") if kind == "replace_lines" else []
                if kind == "replace_lines" and "text" in op and op["text"] == "":
                    new = []
                label = "ersetzt" if kind == "replace_lines" else "gelöscht"
                edits.append((first - 1, last, new, i, f"Zeilen {first}–{last} {label}"))
        except EditError as exc:
            raise EditError(f"Änderung {i + 1} ({kind}): {exc}") from None
    spans = sorted((e for e in edits if e[0] != e[1]), key=lambda e: e[0])
    for a, b in zip(spans, spans[1:]):
        if b[0] < a[1]:
            raise EditError(f"Änderung {a[3] + 1} und {b[3] + 1} überlappen sich. Fasse die Zeilenbereiche zusammen.")
    for start, end, new, _i, desc in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        lines[start:end] = new
    report.extend(e[4] for e in sorted(edits, key=lambda e: e[3]))

    for i, op in enumerate(ops):
        kind = op.get("op")
        if kind in ("replace_lines", "insert_lines", "delete_lines"):
            continue
        try:
            if kind == "replace":
                find = _str(op, "find")
                repl = _str(op, "replace", allow_empty=True)
                body = "\n".join(lines)
                count = body.count(find)
                if count == 0:
                    raise EditError("Der Suchtext kommt nicht vor (Leerzeichen, Einrückung und Groß-/Kleinschreibung müssen genau stimmen; mit file_read prüfen).")
                if count > 1 and not _bool(op, "all", False):
                    raise EditError(f"Der Suchtext kommt {count}-mal vor. Gib mehr Umgebung an, damit er eindeutig ist, oder setze all=true.")
                body = body.replace(find, repl) if _bool(op, "all", False) else body.replace(find, repl, 1)
                lines = body.split("\n")
                report.append(f"{count if _bool(op, 'all', False) else 1}× ersetzt")
            elif kind == "append":
                add = _str(op, "text", allow_empty=True).split("\n")
                lines.extend(add)
                report.append(f"{len(add)} Zeile(n) angehängt")
            elif kind == "write":
                lines = _split_lines(_str(op, "text", allow_empty=True).replace("\r\n", "\n"))
                report.append(f"Datei neu geschrieben ({len(lines)} Zeilen)")
            else:
                raise EditError(f"Unbekannter Befehl. Möglich bei Textdateien: replace, replace_lines, insert_lines, delete_lines, append, write.")
        except EditError as exc:
            raise EditError(f"Änderung {i + 1} ({kind}): {exc}") from None
    body = "\n".join(lines)
    if lines and (fmt.trailing_newline or not text):
        body += "\n"
    return encode_text(body, fmt, ctx), report


# ======================================================================== Word

def _docx():
    try:
        import docx
    except ImportError:
        raise _missing("Word") from None
    return docx


def _iter_blocks(doc):
    """Absätze und Tabellen der obersten Ebene in Dokumentreihenfolge: ('P', n, Absatz) / ('T', n, Tabelle)."""
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    p = t = 0
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p += 1
            yield "P", p, Paragraph(child, doc)
        elif tag == "tbl":
            t += 1
            yield "T", t, Table(child, doc)


def _cell_text(cell) -> str:
    return " / ".join(par.text for par in cell.paragraphs if par.text) if cell.paragraphs else ""


def _open_docx(data: bytes):
    docx = _docx()
    try:
        return docx.Document(io.BytesIO(data))
    except Exception:  # noqa: BLE001 - beschädigte Dateien lösen vielerlei Fehler aus
        raise EditError("Die Word-Datei ist beschädigt oder kein gültiges .docx.") from None


def read_docx(data: bytes, part: Any) -> str:
    doc = _open_docx(data)
    blocks = list(_iter_blocks(doc))
    pars = sum(1 for b in blocks if b[0] == "P")
    start, end = _range(part, pars, "Absätze")
    lines: list[str] = []
    for kind, number, obj in blocks:
        if kind == "P":
            if not start <= number <= end:
                continue
            style = obj.style.name if obj.style is not None else ""
            tag = f" ({style})" if style and style != "Normal" else ""
            lines.append(f"[P{number}]{tag} {obj.text}" if obj.text else f"[P{number}]{tag} (leer)")
        else:
            if lines and not (start <= _last_par(lines) <= end):
                continue
            rows = obj.rows
            lines.append(f"[T{number}] Tabelle {len(rows)} Zeilen × {len(obj.columns)} Spalten")
            for r, row in enumerate(rows, 1):
                lines.append(f"  Z{r}: " + " | ".join(_cell_text(c) for c in row.cells))
    for s, section in enumerate(doc.sections, 1):
        for label, hf in (("Kopfzeile", section.header), ("Fußzeile", section.footer)):
            text = " ".join(p.text for p in hf.paragraphs if p.text).strip()
            if text:
                lines.append(f"[{label} Abschnitt {s}] {text}")
    head = f"Word-Dokument, {pars} Absätze, {sum(1 for b in blocks if b[0] == 'T')} Tabellen. Absätze {start}–{end}:"
    return head + "\n" + _cut(lines, MAX_READ_CHARS, 'Mit part="von-bis" gezielt weiterlesen')


def _last_par(lines: list[str]) -> int:
    for line in reversed(lines):
        m = re.match(r"\[P(\d+)\]", line)
        if m:
            return int(m.group(1))
    return 0


def _replace_in_runs(runs: list, find: str, repl: str, limit: int | None) -> int:
    """Text in Läufen ersetzen, auch wenn der Suchtext über mehrere Läufe geht; Format des ersten betroffenen Laufs bleibt."""
    texts = [r.text for r in runs]
    full = "".join(texts)
    spans: list[int] = []
    i = full.find(find)
    while i != -1 and (limit is None or len(spans) < limit):
        spans.append(i)
        i = full.find(find, i + len(find))
    if not spans:
        return 0
    starts: list[int] = []
    pos = 0
    for t in texts:
        starts.append(pos)
        pos += len(t)
    original = list(texts)

    def run_of(offset: int) -> int:
        """Index des Laufs, der das Zeichen an ``offset`` enthält."""
        for k, t in enumerate(original):
            if starts[k] <= offset < starts[k] + len(t):
                return k
        raise EditError("Interner Fehler beim Ersetzen.")

    for start in reversed(spans):  # von hinten, damit frühere Positionen gültig bleiben
        end = start + len(find)
        first, last = run_of(start), run_of(end - 1)
        head = texts[first][: start - starts[first]]
        tail = texts[last][end - starts[last]:]
        if first == last:
            texts[first] = head + repl + tail
        else:
            texts[first] = head + repl
            for k in range(first + 1, last):
                texts[k] = ""
            texts[last] = tail
    for run, old, new in zip(runs, original, texts):
        if old != new:
            run.text = new
    return len(spans)


def _docx_paragraphs(doc):
    """Alle Absätze: Textkörper, Tabellenzellen (auch verschachtelt), Kopf- und Fußzeilen."""
    def from_container(container):
        for p in container.paragraphs:
            yield p
        for table in container.tables:
            for row in table.rows:
                seen: set[int] = set()
                for cell in row.cells:
                    if id(cell._tc) in seen:
                        continue
                    seen.add(id(cell._tc))
                    yield from from_container(cell)

    yield from from_container(doc)
    for section in doc.sections:
        for hf in (section.header, section.footer, section.first_page_header, section.first_page_footer, section.even_page_header, section.even_page_footer):
            try:
                yield from from_container(hf)
            except Exception:  # noqa: BLE001
                continue


def _par_runs(par) -> list:
    from docx.text.run import Run

    return [Run(r, par) for r in par._p.xpath(".//w:r")]


def _set_par_text(par, text: str) -> None:
    for link in par._p.xpath("./w:hyperlink"):
        link.getparent().remove(link)
    runs = par.runs
    if runs:
        runs[0].text = text
        for run in runs[1:]:
            run._r.getparent().remove(run._r)
    else:
        par.add_run(text)


def _set_cell_text(cell, text: str) -> None:
    pars = cell.paragraphs
    _set_par_text(pars[0], text)
    for extra in pars[1:]:
        extra._p.getparent().remove(extra._p)


def _new_paragraph(anchor_element, parent, *, before: bool = False):
    from docx.oxml import OxmlElement
    from docx.text.paragraph import Paragraph

    element = OxmlElement("w:p")
    (anchor_element.addprevious if before else anchor_element.addnext)(element)
    return Paragraph(element, parent)


def _apply_style(par, style: str) -> None:
    if not style:
        return
    try:
        par.style = style
    except KeyError:
        names = ", ".join(sorted({s.name for s in par.part.document.styles if s.type == 1})[:25])
        raise EditError(f"Formatvorlage „{style}“ gibt es in diesem Dokument nicht. Vorhanden: {names}") from None


def edit_docx(data: bytes, ops: list[dict], ctx: Context) -> tuple[bytes, list[str]]:
    doc = _open_docx(data)
    pars = list(doc.paragraphs)  # Stand zu Beginn
    tables = list(doc.tables)
    body = doc.element.body
    report: list[str] = []
    for i, op in enumerate(ops):
        kind = op.get("op")
        try:
            if kind == "replace_text":
                find = _str(op, "find")
                repl = _str(op, "replace", allow_empty=True)
                limit = None if _bool(op, "all", True) else 1
                total = 0
                for par in _docx_paragraphs(doc):
                    if limit is not None and total >= limit:
                        break
                    total += _replace_in_runs(_par_runs(par), find, repl, None if limit is None else limit - total)
                if total == 0:
                    raise EditError("Der Suchtext kommt nicht vor (innerhalb eines Absatzes, Groß-/Kleinschreibung beachten; mit file_read prüfen).")
                report.append(f"„{find[:40]}“ {total}× ersetzt")
            elif kind == "set_paragraph":
                n = _int(op, "index")
                par = _pick(pars, n, "Absatz")
                if "text" in op:
                    _set_par_text(par, _str(op, "text", allow_empty=True))
                _apply_style(par, _str(op, "style", required=False))
                report.append(f"Absatz {n} gesetzt")
            elif kind == "insert_paragraph":
                after = _int(op, "after", minimum=0)
                if after > len(pars):
                    raise EditError(f"„after“ ist {after}, das Dokument hat {len(pars)} Absätze.")
                text = _str(op, "text", allow_empty=True)
                if after == 0:
                    par = _new_paragraph(pars[0]._p, pars[0]._parent, before=True) if pars else doc.add_paragraph()
                else:
                    par = _new_paragraph(pars[after - 1]._p, pars[after - 1]._parent)
                if text:
                    par.add_run(text)
                _apply_style(par, _str(op, "style", required=False))
                report.append(f"Absatz nach {after} eingefügt")
            elif kind == "append":
                par = doc.add_paragraph(_str(op, "text", allow_empty=True))
                _apply_style(par, _str(op, "style", required=False))
                report.append("Absatz am Ende angehängt")
            elif kind == "delete_paragraph":
                n = _int(op, "index")
                par = _pick(pars, n, "Absatz")
                par._p.getparent().remove(par._p)
                report.append(f"Absatz {n} gelöscht")
            elif kind == "insert_table":
                rows = op.get("rows")
                if not isinstance(rows, list) or not rows or not all(isinstance(r, list) for r in rows):
                    raise EditError("„rows“ muss eine Liste von Zeilen (Listen von Texten) sein.")
                cols = max(len(r) for r in rows)
                table = doc.add_table(rows=len(rows), cols=cols)
                try:
                    table.style = _str(op, "style", required=False) or "Table Grid"
                except KeyError:
                    pass
                for r, row in enumerate(rows):
                    for c, value in enumerate(row):
                        _set_cell_text(table.cell(r, c), "" if value is None else str(value))
                after = _int(op, "after", minimum=0, default=len(pars))
                if after > len(pars):
                    raise EditError(f"„after“ ist {after}, das Dokument hat {len(pars)} Absätze.")
                if after == 0 and pars:
                    pars[0]._p.addprevious(table._tbl)
                elif after:
                    pars[after - 1]._p.addnext(table._tbl)
                report.append(f"Tabelle {len(rows)}×{cols} eingefügt")
            elif kind in ("set_cell", "add_row", "delete_row"):
                tn = _int(op, "table")
                table = _pick(tables, tn, "Tabelle")
                if kind == "set_cell":
                    r, c = _int(op, "row"), _int(op, "col")
                    if r > len(table.rows) or c > len(table.columns):
                        raise EditError(f"Tabelle {tn} hat {len(table.rows)} Zeilen × {len(table.columns)} Spalten.")
                    _set_cell_text(table.cell(r - 1, c - 1), _str(op, "text", allow_empty=True))
                    report.append(f"Tabelle {tn}, Zelle ({r},{c}) gesetzt")
                elif kind == "add_row":
                    cells = op.get("cells")
                    if not isinstance(cells, list):
                        raise EditError("„cells“ muss eine Liste von Texten sein.")
                    new_tr = copy.deepcopy(table.rows[-1]._tr)
                    table._tbl.append(new_tr)
                    row = table.rows[-1]
                    for c, cell in enumerate(row.cells):
                        _set_cell_text(cell, "" if c >= len(cells) or cells[c] is None else str(cells[c]))
                    report.append(f"Tabelle {tn}: Zeile angehängt")
                else:
                    r = _int(op, "row")
                    if r > len(table.rows):
                        raise EditError(f"Tabelle {tn} hat nur {len(table.rows)} Zeilen.")
                    tr_el = table.rows[r - 1]._tr
                    tr_el.getparent().remove(tr_el)
                    report.append(f"Tabelle {tn}: Zeile {r} gelöscht")
            else:
                raise EditError("Unbekannter Befehl. Möglich bei Word: replace_text, set_paragraph, insert_paragraph, append, delete_paragraph, insert_table, set_cell, add_row, delete_row.")
        except EditError as exc:
            raise EditError(f"Änderung {i + 1} ({kind}): {exc}") from None
    _ = body
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue(), report


def _pick(items: list, number: int, what: str):
    if number > len(items):
        raise EditError(f"{what} {number} gibt es nicht (vorhanden: {len(items)}).")
    return items[number - 1]


# ======================================================================= Excel

def _openpyxl():
    try:
        import openpyxl
    except ImportError:
        raise _missing("Excel") from None
    return openpyxl


def _load_xlsx(data: bytes, *, values: bool = False):
    openpyxl = _openpyxl()
    try:
        return openpyxl.load_workbook(io.BytesIO(data), data_only=values)
    except Exception:  # noqa: BLE001
        raise EditError("Die Excel-Datei ist beschädigt oder kein gültiges .xlsx.") from None


def _sheet(wb, name: Any):
    if name in (None, ""):
        return wb.active
    for ws in wb.worksheets:
        if ws.title == str(name):
            return ws
    for ws in wb.worksheets:
        if ws.title.lower() == str(name).strip().lower():
            return ws
    raise EditError(f"Tabellenblatt „{name}“ gibt es nicht. Vorhanden: " + ", ".join(w.title for w in wb.worksheets))


def _show(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat(sep=" ") if hasattr(value, "hour") and (value.hour or value.minute) else value.date().isoformat() if hasattr(value, "date") else value.isoformat()
    return str(value).replace("\n", "⏎").replace("|", "¦")


def read_xlsx(data: bytes, part: Any) -> str:
    from openpyxl.utils import get_column_letter, range_boundaries

    wb = _load_xlsx(data)
    cached = _load_xlsx(data, values=True)
    wanted, cell_range = None, None
    if part not in (None, ""):
        text = str(part)
        wanted, _, cell_range = text.partition("!") if "!" in text else (text, "", "")
        if re.fullmatch(r"[A-Za-z]{1,3}\d+(:[A-Za-z]{1,3}\d+)?", wanted.strip()):
            wanted, cell_range = None, wanted
    sheets = [_sheet(wb, wanted)] if wanted else list(wb.worksheets)
    out: list[str] = [f"Excel-Arbeitsmappe mit {len(wb.worksheets)} Blatt/Blättern: " + ", ".join(w.title for w in wb.worksheets)]
    budget = MAX_READ_CHARS
    for ws in sheets:
        width = min(ws.max_column or 1, 40)
        min_col, min_row, max_col, max_row = 1, 1, width, min(ws.max_row or 1, 400)
        if cell_range:
            try:
                min_col, min_row, max_col, max_row = range_boundaries(cell_range.upper())
            except (ValueError, TypeError):
                raise EditError(f"Bereich „{cell_range}“ ist ungültig (Beispiel: A1:F50).") from None
            max_col, max_row = min(max_col, min_col + 59), min(max_row, min_row + 999)
        total_rows, total_cols = ws.max_row or 0, ws.max_column or 0
        merged = f", verbundene Zellen: {', '.join(str(m) for m in list(ws.merged_cells.ranges)[:8])}" if ws.merged_cells.ranges else ""
        out.append(f"\n## Blatt „{ws.title}“ ({total_rows} Zeilen × {total_cols} Spalten{merged}), Ausschnitt {get_column_letter(min_col)}{min_row}:{get_column_letter(max_col)}{max_row}")
        out.append("Zeile | " + " | ".join(get_column_letter(c) for c in range(min_col, max_col + 1)))
        cws = cached[ws.title]
        for row in range(min_row, max_row + 1):
            cells = []
            empty = True
            for col in range(min_col, max_col + 1):
                v = ws.cell(row, col).value
                if v is None:
                    cells.append("")
                    continue
                empty = False
                shown = _show(v)
                if isinstance(v, str) and v.startswith("="):
                    result = cws.cell(row, col).value
                    shown += f" → {_show(result)}" if result is not None else ""
                cells.append(shown)
            if empty:
                continue
            line = f"{row} | " + " | ".join(cells)
            budget -= len(line)
            if budget < 0:
                out.append(f"[… gekürzt. Mit part=\"{ws.title}!A{row}:{get_column_letter(max_col)}{max_row}\" gezielt weiterlesen]")
                break
            out.append(line)
    return "\n".join(out)


def _col_index(value: Any) -> int:
    from openpyxl.utils import column_index_from_string

    text = str(value).strip().upper()
    if text.isdigit():
        return int(text)
    try:
        return column_index_from_string(text)
    except ValueError:
        raise EditError(f"Spalte „{value}“ ist ungültig (Buchstabe wie C oder Nummer).") from None


def _set_value(cell, value: Any, as_text: bool = False) -> None:
    from . import outbox

    if as_text and isinstance(value, str):
        cell.value = value
        cell.data_type = "s"
        return
    new, fmt = outbox._cell_value(value)
    cell.value = new
    if fmt:
        cell.number_format = fmt


def edit_xlsx(data: bytes, ops: list[dict], ctx: Context) -> tuple[bytes, list[str]]:
    from openpyxl.utils import get_column_letter, range_boundaries
    from openpyxl.utils.cell import coordinate_from_string

    wb = _load_xlsx(data)
    report: list[str] = []
    for i, op in enumerate(ops):
        kind = op.get("op")
        try:
            if kind == "set_cell":
                ws = _sheet(wb, op.get("sheet"))
                ref = _str(op, "cell").upper()
                try:
                    coordinate_from_string(ref)
                except Exception:  # noqa: BLE001 - openpyxl wirft eigene Ausnahmen
                    raise EditError(f"Zelle „{ref}“ ist ungültig (Beispiel: B7).") from None
                _set_value(ws[ref], op.get("value"), _bool(op, "as_text", False))
                report.append(f"{ws.title}!{ref} gesetzt")
            elif kind == "set_range":
                ws = _sheet(wb, op.get("sheet"))
                rows = op.get("rows")
                if not isinstance(rows, list) or not all(isinstance(r, list) for r in rows):
                    raise EditError("„rows“ muss eine Liste von Zeilen (jeweils eine Liste von Werten) sein.")
                if sum(len(r) for r in rows) > MAX_CELLS:
                    raise EditError(f"Zu viele Zellen auf einmal (höchstens {MAX_CELLS}).")
                start = _str(op, "start", required=False).upper() or "A1"
                try:
                    col0, row0, _c, _r = range_boundaries(start + ":" + start)
                except (ValueError, TypeError):
                    raise EditError(f"„start“ ({start}) ist ungültig (Beispiel: A1).") from None
                for r, row in enumerate(rows):
                    for c, value in enumerate(row):
                        _set_value(ws.cell(row0 + r, col0 + c), value, _bool(op, "as_text", False))
                report.append(f"{ws.title}: {len(rows)} Zeile(n) ab {start} geschrieben")
            elif kind == "clear_range":
                ws = _sheet(wb, op.get("sheet"))
                spec = _str(op, "range").upper()
                try:
                    c1, r1, c2, r2 = range_boundaries(spec)
                except (ValueError, TypeError):
                    raise EditError(f"Bereich „{spec}“ ist ungültig (Beispiel: A2:D20).") from None
                if (c2 - c1 + 1) * (r2 - r1 + 1) > 200_000:
                    raise EditError("Der Bereich ist zu groß.")
                for row in ws.iter_rows(min_row=r1, max_row=r2, min_col=c1, max_col=c2):
                    for cell in row:
                        cell.value = None
                report.append(f"{ws.title}!{spec} geleert")
            elif kind in ("insert_rows", "delete_rows"):
                ws = _sheet(wb, op.get("sheet"))
                at, count = _int(op, "at"), _int(op, "count", default=1)
                (ws.insert_rows if kind == "insert_rows" else ws.delete_rows)(at, count)
                report.append(f"{ws.title}: {count} Zeile(n) ab {at} {'eingefügt' if kind == 'insert_rows' else 'gelöscht'}")
                ctx.notes.append("Formeln und verbundene Zellen werden beim Einfügen/Löschen von Zeilen nicht angepasst; prüfe Formeln, die auf verschobene Zellen zeigen.") if "zeilen-formeln" not in " ".join(ctx.notes) else None
            elif kind in ("insert_cols", "delete_cols"):
                ws = _sheet(wb, op.get("sheet"))
                at, count = _col_index(op.get("at")), _int(op, "count", default=1)
                (ws.insert_cols if kind == "insert_cols" else ws.delete_cols)(at, count)
                report.append(f"{ws.title}: {count} Spalte(n) ab {get_column_letter(at)} {'eingefügt' if kind == 'insert_cols' else 'gelöscht'}")
            elif kind == "add_sheet":
                title = _str(op, "name")[:31]
                if any(w.title.lower() == title.lower() for w in wb.worksheets):
                    raise EditError(f"Ein Blatt „{title}“ gibt es schon.")
                ws = wb.create_sheet(title)
                for r, row in enumerate(op.get("rows") or [], 1):
                    for c, value in enumerate(row, 1):
                        _set_value(ws.cell(r, c), value)
                report.append(f"Blatt „{title}“ angelegt")
            elif kind == "rename_sheet":
                ws = _sheet(wb, op.get("sheet"))
                new = _str(op, "name")[:31]
                old, ws.title = ws.title, new
                report.append(f"Blatt „{old}“ in „{new}“ umbenannt")
            elif kind == "delete_sheet":
                ws = _sheet(wb, op.get("sheet"))
                if len(wb.worksheets) == 1:
                    raise EditError("Das letzte Blatt kann nicht gelöscht werden.")
                wb.remove(ws)
                report.append(f"Blatt „{ws.title}“ gelöscht")
            elif kind == "set_width":
                ws = _sheet(wb, op.get("sheet"))
                col = get_column_letter(_col_index(op.get("col")))
                ws.column_dimensions[col].width = max(2, min(float(op.get("width", 12)), 200))
                report.append(f"{ws.title}: Spalte {col} Breite gesetzt")
            else:
                raise EditError("Unbekannter Befehl. Möglich bei Excel: set_cell, set_range, clear_range, insert_rows, delete_rows, insert_cols, delete_cols, add_sheet, rename_sheet, delete_sheet, set_width.")
        except EditError as exc:
            raise EditError(f"Änderung {i + 1} ({kind}): {exc}") from None
    try:
        names = set(__import__("zipfile").ZipFile(io.BytesIO(data)).namelist())
    except Exception:  # noqa: BLE001
        names = set()
    lost = [label for key, label in (("xl/charts/", "Diagramme"), ("xl/pivotTables/", "Pivot-Tabellen"), ("xl/drawings/", "Zeichnungen/Bilder"), ("xl/vbaProject", "Makros")) if any(n.startswith(key) for n in names)]
    if lost:
        ctx.notes.append("Achtung: Die Originaldatei enthielt " + ", ".join(lost) + "; sie können beim Speichern verloren gehen. Sage der Person das und weise darauf hin, dass die Originaldatei unverändert bleibt.")
    ctx.notes.append("Berechnete Formelwerte werden von Excel beim Öffnen neu berechnet.")
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue(), report


# ================================================================== PowerPoint

def _pptx():
    try:
        import pptx
    except ImportError:
        raise _missing("PowerPoint") from None
    return pptx


def _open_pptx(data: bytes):
    pptx = _pptx()
    try:
        return pptx.Presentation(io.BytesIO(data))
    except Exception:  # noqa: BLE001
        raise EditError("Die PowerPoint-Datei ist beschädigt oder kein gültiges .pptx.") from None


def _walk_shapes(shapes, prefix: str = ""):
    for index, shape in enumerate(shapes, 1):
        path = f"{prefix}{index}"
        yield path, shape
        if shape.shape_type == 6:  # Gruppe
            yield from _walk_shapes(shape.shapes, path + ".")


def read_pptx(data: bytes, part: Any) -> str:
    prs = _open_pptx(data)
    slides = list(prs.slides)
    start, end = _range(part, len(slides), "Folien")
    out = [f"PowerPoint mit {len(slides)} Folien. Layouts: " + ", ".join(f"{i}={l.name}" for i, l in enumerate(prs.slide_layouts)) + f". Folien {start}–{end}:"]
    for number in range(start, end + 1):
        slide = slides[number - 1]
        out.append(f"\n## Folie {number} (Layout: {slide.slide_layout.name})")
        for path, shape in _walk_shapes(slide.shapes):
            label = f"[S{path}] {shape.name}"
            if shape.has_text_frame and shape.text_frame.text.strip():
                out.append(f"{label}: " + " ⏎ ".join(p.text for p in shape.text_frame.paragraphs))
            elif getattr(shape, "has_table", False) and shape.has_table:
                out.append(f"{label} Tabelle:")
                for r, row in enumerate(shape.table.rows, 1):
                    out.append(f"  Z{r}: " + " | ".join(c.text for c in row.cells))
            elif shape.shape_type == 13:
                out.append(f"{label} (Bild)")
            elif getattr(shape, "has_chart", False) and shape.has_chart:
                out.append(f"{label} (Diagramm)")
            elif shape.has_text_frame:
                out.append(f"{label} (leeres Textfeld)")
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip():
            out.append("[Notizen] " + slide.notes_slide.notes_text_frame.text.replace("\n", " ⏎ "))
    return _cut(out, MAX_READ_CHARS, 'Mit part="von-bis" gezielt weiterlesen')


def _shape_by_path(slide, path: Any):
    wanted = str(path).strip().lstrip("Ss")
    for p, shape in _walk_shapes(slide.shapes):
        if p == wanted:
            return shape
    raise EditError(f"Form {path} gibt es auf dieser Folie nicht (siehe file_read: [S…]).")


def _set_pptx_paragraph(par, text: str) -> None:
    runs = par.runs
    if runs:
        runs[0].text = text
        for run in runs[1:]:
            run._r.getparent().remove(run._r)
    else:
        par.add_run().text = text


def _set_text_frame(tf, text: str) -> None:
    lines = text.split("\n")
    pars = list(tf.paragraphs)
    for n, line in enumerate(lines):
        if n < len(pars):
            _set_pptx_paragraph(pars[n], line)
        else:
            new = copy.deepcopy(pars[-1]._p) if pars else None
            if new is not None:
                tf._txBody.append(new)
                par = tf.paragraphs[-1]
                _set_pptx_paragraph(par, line)
            else:
                tf.add_paragraph().text = line
    for extra in pars[len(lines):]:
        extra._p.getparent().remove(extra._p)


def _all_pptx_runs_by_paragraph(prs):
    for slide in prs.slides:
        yield from _slide_paragraphs(slide)


def _slide_paragraphs(slide):
    for _path, shape in _walk_shapes(slide.shapes):
        if shape.has_text_frame:
            yield from shape.text_frame.paragraphs
        if getattr(shape, "has_table", False) and shape.has_table:
            for row in shape.table.rows:
                for cell in row.cells:
                    yield from cell.text_frame.paragraphs
    if slide.has_notes_slide:
        yield from slide.notes_slide.notes_text_frame.paragraphs


def _layout(prs, spec: Any):
    layouts = list(prs.slide_layouts)
    if spec in (None, ""):
        return layouts[1] if len(layouts) > 1 else layouts[0]
    if isinstance(spec, int) or str(spec).strip().isdigit():
        index = int(spec)
        if not 0 <= index < len(layouts):
            raise EditError(f"Layout {index} gibt es nicht (0–{len(layouts) - 1}).")
        return layouts[index]
    for layout in layouts:
        if layout.name.lower() == str(spec).strip().lower():
            return layout
    raise EditError(f"Layout „{spec}“ gibt es nicht. Vorhanden: " + ", ".join(f"{i}={l.name}" for i, l in enumerate(layouts)))


def _move_slide(prs, slide, position: int) -> None:
    sld_ids = prs.slides._sldIdLst
    items = list(sld_ids)
    target = next(item for item in items if prs.part.related_part(item.rId) is slide.part)
    sld_ids.remove(target)
    sld_ids.insert(max(0, min(position - 1, len(sld_ids))), target)


def edit_pptx(data: bytes, ops: list[dict], ctx: Context) -> tuple[bytes, list[str]]:
    prs = _open_pptx(data)
    slides = list(prs.slides)  # Stand zu Beginn
    report: list[str] = []
    for i, op in enumerate(ops):
        kind = op.get("op")
        try:
            if kind == "replace_text":
                find = _str(op, "find")
                repl = _str(op, "replace", allow_empty=True)
                if op.get("slide") not in (None, ""):
                    scope = list(_slide_paragraphs(_pick(slides, _int(op, "slide"), "Folie")))
                else:
                    scope = list(_all_pptx_runs_by_paragraph(prs))
                limit = None if _bool(op, "all", True) else 1
                total = 0
                for par in scope:
                    if limit is not None and total >= limit:
                        break
                    total += _replace_in_runs(list(par.runs), find, repl, None if limit is None else limit - total)
                if total == 0:
                    raise EditError("Der Suchtext kommt nicht vor (innerhalb eines Absatzes, Groß-/Kleinschreibung beachten; mit file_read prüfen).")
                report.append(f"„{find[:40]}“ {total}× ersetzt")
            elif kind == "set_text":
                n = _int(op, "slide")
                shape = _shape_by_path(_pick(slides, n, "Folie"), op.get("shape"))
                if not shape.has_text_frame:
                    raise EditError("Diese Form enthält kein Textfeld.")
                _set_text_frame(shape.text_frame, _str(op, "text", allow_empty=True))
                report.append(f"Folie {n}, Form {op.get('shape')} gesetzt")
            elif kind == "set_cell":
                n = _int(op, "slide")
                shape = _shape_by_path(_pick(slides, n, "Folie"), op.get("shape"))
                if not getattr(shape, "has_table", False) or not shape.has_table:
                    raise EditError("Diese Form ist keine Tabelle.")
                r, c = _int(op, "row"), _int(op, "col")
                table = shape.table
                if r > len(table.rows) or c > len(table.columns):
                    raise EditError(f"Die Tabelle hat {len(table.rows)} Zeilen × {len(table.columns)} Spalten.")
                _set_text_frame(table.cell(r - 1, c - 1).text_frame, _str(op, "text", allow_empty=True))
                report.append(f"Folie {n}, Tabellenzelle ({r},{c}) gesetzt")
            elif kind == "set_notes":
                n = _int(op, "slide")
                _pick(slides, n, "Folie").notes_slide.notes_text_frame.text = _str(op, "text", allow_empty=True)
                report.append(f"Folie {n}: Notizen gesetzt")
            elif kind == "add_slide":
                layout = _layout(prs, op.get("layout"))
                slide = prs.slides.add_slide(layout)
                title, body = _str(op, "title", required=False), _str(op, "body", required=False)
                if title and slide.shapes.title is not None:
                    slide.shapes.title.text_frame.text = title
                if body:
                    target = next((p for p in slide.placeholders if p.placeholder_format.idx == 1), None)
                    if target is None:
                        target = next((p for p in slide.placeholders if p.placeholder_format.idx != 0 and p.has_text_frame), None)
                    if target is None:
                        raise EditError(f"Das Layout „{layout.name}“ hat kein Textfeld für „body“. Wähle ein anderes Layout (siehe file_read).")
                    _set_text_frame(target.text_frame, body)
                if _str(op, "notes", required=False):
                    slide.notes_slide.notes_text_frame.text = _str(op, "notes")
                position = _int(op, "position", default=len(prs.slides))
                _move_slide(prs, slide, position)
                report.append(f"Folie hinzugefügt (Layout „{layout.name}“, Position {min(position, len(prs.slides))})")
            elif kind == "delete_slide":
                n = _int(op, "slide")
                slide = _pick(slides, n, "Folie")
                sld_ids = prs.slides._sldIdLst
                item = next((x for x in sld_ids if prs.part.related_part(x.rId) is slide.part), None)
                if item is None:
                    raise EditError(f"Folie {n} wurde schon gelöscht.")
                prs.part.drop_rel(item.rId)
                sld_ids.remove(item)
                report.append(f"Folie {n} gelöscht")
            elif kind == "move_slide":
                n = _int(op, "slide")
                _move_slide(prs, _pick(slides, n, "Folie"), _int(op, "to"))
                report.append(f"Folie {n} nach Position {op.get('to')} verschoben")
            else:
                raise EditError("Unbekannter Befehl. Möglich bei PowerPoint: replace_text, set_text, set_cell, set_notes, add_slide, delete_slide, move_slide.")
        except EditError as exc:
            raise EditError(f"Änderung {i + 1} ({kind}): {exc}") from None
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue(), report


# ======================================================================== PDF

def _pypdf():
    try:
        import pypdf
    except ImportError:
        raise _missing("PDF") from None
    return pypdf


@dataclass
class PdfField:
    name: str
    kind: str  # text | checkbox | radio | button | choice | signature
    flags: int
    value: str
    options: list[str]
    obj: Any  # Feldobjekt (DictionaryObject)
    widgets: list[Any]

    @property
    def readonly(self) -> bool:
        return bool(self.flags & 1)

    @property
    def filled(self) -> bool:
        return self.kind in ("text", "checkbox", "radio", "choice") and self.value.strip() not in ("", "Off")


def _text_of(value: Any) -> str:
    if value is None:
        return ""
    value = value.get_object() if hasattr(value, "get_object") else value
    if isinstance(value, list):
        return ", ".join(_text_of(v) for v in value)
    text = str(value)
    return text[1:] if text.startswith("/") and type(value).__name__ == "NameObject" else text


def pdf_fields(root: Any) -> list[PdfField]:
    """Alle Formularfelder (AcroForm) mit vollständigem Namen; Typ und Flags werden von Elternfeldern geerbt."""
    acro = root.get("/AcroForm")
    if acro is None:
        return []
    acro = acro.get_object()
    result: list[PdfField] = []
    seen: set[int] = set()

    def walk(ref: Any, prefix: str, ft: Any, ff: int, depth: int) -> None:
        if depth > 20:
            return
        obj = ref.get_object()
        key = getattr(ref, "idnum", None) or id(obj)
        if key in seen:
            return
        seen.add(key)
        partial = obj.get("/T")
        name = prefix
        if partial is not None:
            name = f"{prefix}.{_text_of(partial)}" if prefix else _text_of(partial)
        ft = obj.get("/FT", ft)
        ff = int(obj.get("/Ff", ff))
        kids = [k for k in (obj.get("/Kids") or [])]
        field_kids = [k for k in kids if k.get_object().get("/T") is not None]
        if field_kids:
            for kid in kids:
                walk(kid, name, ft, ff, depth + 1)
            return
        if not name:
            return
        widgets = [k.get_object() for k in kids] or ([obj] if obj.get("/Subtype") == "/Widget" else [])
        kind, options = "text", []
        if ft == "/Btn":
            kind = "button" if ff & 65536 else "radio" if ff & 32768 else "checkbox"
            for w in widgets or [obj]:
                states = [str(s)[1:] for s in ((w.get("/AP") or {}).get("/N") or {}) if str(s) != "/Off"]
                options.extend(s for s in states if s not in options)
        elif ft == "/Ch":
            kind = "choice"
            for opt in obj.get("/Opt") or []:
                opt = opt.get_object()
                options.append(_text_of(opt[-1] if isinstance(opt, list) and opt else opt))
        elif ft == "/Sig":
            kind = "signature"
        value = _text_of(obj.get("/V"))
        if kind in ("checkbox", "radio") and not value:
            states = [str(w.get("/AS")) for w in widgets if w.get("/AS") not in (None, "/Off")]
            value = states[0][1:] if states else ""
        result.append(PdfField(name, kind, ff, value, options, obj, widgets))

    for ref in acro.get("/Fields") or []:
        walk(ref, "", None, 0, 0)
    return result


_KIND_DE = {"text": "Text", "checkbox": "Kontrollkästchen", "radio": "Optionsfeld", "button": "Schaltfläche", "choice": "Auswahl", "signature": "Signatur"}


def _open_pdf(data: bytes, *, writer: bool = False):
    pypdf = _pypdf()
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise EditError("Das PDF ist passwortgeschützt. Die Person muss es ohne Passwort speichern und neu anhängen.")
        len(reader.pages)
        return pypdf.PdfWriter(clone_from=reader) if writer else reader
    except EditError:
        raise
    except Exception:  # noqa: BLE001
        raise EditError("Das PDF ist beschädigt oder nicht lesbar.") from None


def read_pdf(data: bytes, part: Any) -> str:
    reader = _open_pdf(data)
    total = len(reader.pages)
    start, end = _range(part, total, "Seiten")
    fields = pdf_fields(reader.trailer["/Root"])
    out = [f"PDF mit {total} Seiten. Seiten {start}–{end} (Maße in Punkten: 1 Punkt = 1/72 Zoll):"]
    if fields:
        out.append(f"\n## Formularfelder ({len(fields)})")
        for f in fields:
            extra = f" Optionen: {', '.join(f.options[:12])}" if f.options else ""
            value = f"„{f.value}“" if f.value else "(leer)"
            out.append(f"- {f.name} [{_KIND_DE[f.kind]}] {value}{' [gesperrt]' if f.readonly else ''}{extra}")
        sigs = [f for f in fields if f.kind == "signature"]
        if sigs:
            out.append("Hinweis: Das PDF enthält Signaturfelder; Änderungen machen vorhandene Signaturen ungültig.")
    elif "/AcroForm" not in reader.trailer["/Root"]:
        out.append("Das PDF hat keine Formularfelder (kein ausfüllbares Formular).")
    for number in range(start, end + 1):
        page = reader.pages[number - 1]
        box = page.mediabox
        text = (page.extract_text() or "").strip()
        out.append(f"\n## Seite {number} ({float(box.width):.0f}×{float(box.height):.0f} Punkt{', gedreht ' + str(page.rotation) + '°' if page.rotation else ''})")
        out.append(text if text else "(kein Text auf dieser Seite; vermutlich ein Scan oder Bild)")
    return _cut("\n".join(out).split("\n"), MAX_READ_CHARS, 'Mit part="von-bis" gezielt Seiten lesen')


_TRUE = {"1", "true", "ja", "yes", "wahr", "x", "an", "on", "ankreuzen", "angekreuzt", "checked"}


def _pdf_page_list(op: dict, total: int, key: str = "pages") -> list[int]:
    raw = op.get(key)
    if raw in (None, ""):
        raise EditError(f"„{key}“ fehlt (Seitennummern wie [1,3] oder \"2-4\").")
    items: list[int] = []
    for part in (raw if isinstance(raw, list) else str(raw).replace(";", ",").split(",")):
        text = str(part).strip()
        m = re.fullmatch(r"(\d+)\s*[-–]\s*(\d+)", text)
        if m:
            items.extend(range(int(m.group(1)), int(m.group(2)) + 1))
        elif text.isdigit():
            items.append(int(text))
        else:
            raise EditError(f"Seitenangabe „{text}“ ist ungültig.")
    bad = [n for n in items if not 1 <= n <= total]
    if bad:
        raise EditError(f"Seite(n) {', '.join(map(str, bad))} gibt es nicht (das PDF hat {total} Seiten).")
    return items


def _find_field(fields: list[PdfField], name: str) -> PdfField:
    for f in fields:
        if f.name == name:
            return f
    folded = [f for f in fields if f.name.lower() == name.strip().lower()]
    if len(folded) == 1:
        return folded[0]
    near = [f.name for f in fields if name.lower() in f.name.lower()][:8]
    raise EditError(f"Formularfeld „{name}“ gibt es nicht." + (f" Ähnliche: {', '.join(near)}." if near else " Alle Felder stehen bei file_read."))


def _set_flag(field: PdfField, bit: int, on: bool) -> None:
    """Flag am Feld setzen; die von Elternfeldern geerbten Flags (Feldart, mehrzeilig …) bleiben erhalten."""
    from pypdf.generic import NameObject, NumberObject

    field.flags = field.flags | bit if on else field.flags & ~bit
    field.obj[NameObject("/Ff")] = NumberObject(field.flags)


def _fill_field(writer: Any, field: PdfField, value: Any) -> None:
    from pypdf.generic import NameObject, TextStringObject

    if field.readonly:
        raise EditError(f"Feld „{field.name}“ ist gesperrt (nur lesbar). Erst mit unlock_fields freigeben, falls die Person das möchte.")
    if field.kind == "checkbox":
        on = value is True or str(value).strip().lower() in _TRUE
        state = (field.options or ["Yes"])[0]
        for w in field.widgets or [field.obj]:
            w[NameObject("/AS")] = NameObject("/" + state if on else "/Off")
        field.obj[NameObject("/V")] = NameObject("/" + state if on else "/Off")
    elif field.kind == "radio":
        state = str(value).strip().lstrip("/")
        if state not in field.options:
            raise EditError(f"Optionsfeld „{field.name}“: „{value}“ ist keine Auswahl. Möglich: {', '.join(field.options)}.")
        for w in field.widgets or [field.obj]:
            has = state in [str(s)[1:] for s in ((w.get("/AP") or {}).get("/N") or {})]
            w[NameObject("/AS")] = NameObject("/" + state if has else "/Off")
        field.obj[NameObject("/V")] = NameObject("/" + state)
    elif field.kind in ("text", "choice"):
        text = "" if value is None else str(value)
        if field.kind == "choice" and field.options and text not in field.options and not field.flags & 262144:
            raise EditError(f"Auswahlfeld „{field.name}“: „{text}“ ist keine Option. Möglich: {', '.join(field.options[:20])}.")
        field.obj[NameObject("/V")] = TextStringObject(text)
        try:
            writer.update_page_form_field_values(None, {field.name: text}, auto_regenerate=False)
        except Exception:  # noqa: BLE001 - Erscheinungsbild ist Zugabe; /V und NeedAppearances reichen den Viewern
            pass
        field.obj[NameObject("/V")] = TextStringObject(text)
    else:
        raise EditError(f"Feld „{field.name}“ ({_KIND_DE[field.kind]}) kann nicht ausgefüllt werden.")
    field.value = "" if field.kind in ("text", "choice") and value in (None, "") else field.value


def _overlay_page(width: float, height: float, draw: Callable[[Any], None]) -> Any:
    try:
        from fpdf import FPDF
    except ImportError:
        raise _missing("PDF-Texte") from None
    from pypdf import PdfReader

    pdf = FPDF(unit="pt", format=(width, height))
    pdf.set_auto_page_break(False)
    pdf.set_margins(0, 0, 0)
    pdf.add_page()
    draw(pdf)
    return PdfReader(io.BytesIO(bytes(pdf.output()))).pages[0]


def _color(spec: Any) -> tuple[int, int, int]:
    text = str(spec or "#000000").strip().lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{6}", text):
        return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
    names = {"schwarz": (0, 0, 0), "black": (0, 0, 0), "rot": (200, 0, 0), "red": (200, 0, 0), "blau": (0, 0, 200), "blue": (0, 0, 200), "weiß": (255, 255, 255), "white": (255, 255, 255)}
    if text.lower() in names:
        return names[text.lower()]
    raise EditError(f"Farbe „{spec}“ ist ungültig (z. B. #1F3A5F oder schwarz).")


def _add_text(writer: Any, op: dict) -> str:
    from . import outbox

    pages = list(writer.pages)
    n = _int(op, "page")
    page = _pick(pages, n, "Seite")
    width, height = float(page.mediabox.width), float(page.mediabox.height)
    text = _str(op, "text")
    x, y = float(op.get("x", 0)), float(op.get("y", 0))
    size = float(op.get("size", 11))
    if not (0 <= x <= width and 0 <= y <= height):
        raise EditError(f"Position ({x:g},{y:g}) liegt außerhalb der Seite ({width:.0f}×{height:.0f} Punkt; x von links, y von oben).")
    box = float(op.get("width", max(40.0, width - x - 20)))
    rgb = _color(op.get("color"))
    fonts = outbox.find_fonts()

    body = text if fonts else text.encode("latin-1", "replace").decode("latin-1")  # ohne Liberation-Schrift nur Latin-1

    def draw(pdf) -> None:
        if fonts:
            files, _mono = fonts
            pdf.add_font("body", "", str(files[""]))
            pdf.set_font("body", size=size)
        else:
            pdf.set_font("Helvetica", size=size)
        pdf.set_text_color(*rgb)
        pdf.set_xy(x, y)
        pdf.multi_cell(box, size * 1.25, body, align="L")

    overlay = _overlay_page(width, height, draw)
    page.merge_page(overlay)
    return f"Seite {n}: Text bei ({x:g},{y:g}) eingefügt"


def _add_text_field(writer: Any, op: dict) -> str:
    from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, NumberObject, TextStringObject

    pages = list(writer.pages)
    n = _int(op, "page")
    page = _pick(pages, n, "Seite")
    name = _str(op, "name")
    root = writer._root_object
    if any(f.name == name for f in pdf_fields(root)):
        raise EditError(f"Ein Feld „{name}“ gibt es schon.")
    width, height = float(op.get("width", 150)), float(op.get("height", 18))
    x, y = float(op.get("x", 0)), float(op.get("y", 0))
    page_h = float(page.mediabox.height)
    rect = [x, page_h - y - height, x + width, page_h - y]
    size = float(op.get("size", 11))
    widget = DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Widget"), NameObject("/FT"): NameObject("/Tx"),
        NameObject("/T"): TextStringObject(name), NameObject("/Rect"): ArrayObject(FloatObject(v) for v in rect),
        NameObject("/F"): NumberObject(4), NameObject("/DA"): TextStringObject(f"/Helv {size:g} Tf 0 g"),
        NameObject("/V"): TextStringObject(_str(op, "value", required=False)),
        NameObject("/Ff"): NumberObject(4096 if _bool(op, "multiline", False) else 0),
    })
    widget[NameObject("/P")] = page.indirect_reference
    ref = writer._add_object(widget)
    annots = page.get("/Annots")
    if annots is None:
        page[NameObject("/Annots")] = ArrayObject([ref])
    else:
        annots.get_object().append(ref)
    acro = root.get("/AcroForm")
    if acro is None:
        acro = DictionaryObject()
        root[NameObject("/AcroForm")] = writer._add_object(acro)
    acro = acro.get_object()
    fields = acro.get("/Fields")
    if fields is None:
        acro[NameObject("/Fields")] = ArrayObject([ref])
    else:
        fields.get_object().append(ref)
    dr = acro.get("/DR")
    if dr is None:
        acro[NameObject("/DR")] = DictionaryObject()
        dr = acro["/DR"]
    dr = dr.get_object()
    fonts = dr.get("/Font")
    if fonts is None:
        dr[NameObject("/Font")] = DictionaryObject()
        fonts = dr["/Font"]
    fonts = fonts.get_object()
    if "/Helv" not in fonts:
        fonts[NameObject("/Helv")] = writer._add_object(DictionaryObject({
            NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"), NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
        }))
    acro[NameObject("/DA")] = TextStringObject("/Helv 0 Tf 0 g")
    return f"Seite {n}: Textfeld „{name}“ angelegt"


def _flatten(writer: Any, fields: list[PdfField]) -> int:
    """Formularinhalte fest in die Seiten einbrennen und die Felder entfernen."""
    from pypdf.generic import NameObject

    values: dict[str, Any] = {}
    for f in fields:
        if f.kind in ("text", "choice"):
            values[f.name] = f.value if f.value else None
        elif f.kind in ("checkbox", "radio"):
            values[f.name] = ("/" + f.value) if f.value and f.value != "Off" else "/Off"
    try:
        if values:
            writer.update_page_form_field_values(None, values, auto_regenerate=False, flatten=True)
    except Exception:  # noqa: BLE001
        pass
    removed = 0
    for page in writer.pages:
        annots = page.get("/Annots")
        if annots is None:
            continue
        keep = [a for a in annots.get_object() if a.get_object().get("/Subtype") != "/Widget"]
        removed += len(annots.get_object()) - len(keep)
        if keep:
            annots.get_object().clear()
            annots.get_object().extend(keep)
        else:
            del page[NameObject("/Annots")]
    acro = writer._root_object.get("/AcroForm")
    if acro is not None:
        del writer._root_object[NameObject("/AcroForm")]
    return removed


def edit_pdf(data: bytes, ops: list[dict], ctx: Context) -> tuple[bytes, list[str]]:
    from pypdf.generic import NameObject, BooleanObject

    pypdf = _pypdf()
    writer = _open_pdf(data, writer=True)
    root = writer._root_object
    report: list[str] = []
    form_touched = False
    if any(f.kind == "signature" and f.value for f in pdf_fields(root)) or "/Sig" in str(root.get("/AcroForm", {}).get("/SigFlags", "")):
        ctx.notes.append("Achtung: Das PDF ist signiert; die Änderung macht vorhandene Signaturen ungültig.")
    for i, op in enumerate(ops):
        kind = op.get("op")
        try:
            fields = pdf_fields(root)
            total = len(writer.pages)
            if kind == "fill_fields":
                values = op.get("values")
                if not isinstance(values, dict) or not values:
                    raise EditError("„values“ muss ein Objekt {\"Feldname\": \"Wert\", …} sein.")
                if not fields:
                    raise EditError("Das PDF hat keine Formularfelder. Mit add_text lässt sich Text auf die Seite schreiben, mit add_text_field entstehen neue Felder.")
                for name, value in values.items():
                    _fill_field(writer, _find_field(fields, str(name)), value)
                form_touched = True
                report.append(f"{len(values)} Feld(er) ausgefüllt")
            elif kind in ("lock_fields", "unlock_fields"):
                if not fields:
                    raise EditError("Das PDF hat keine Formularfelder, die sich sperren ließen. Mit add_text_field können Felder angelegt werden.")
                which = _str(op, "which", required=False) or ("names" if op.get("names") else "filled" if kind == "lock_fields" else "all")
                if which == "names":
                    names = op.get("names")
                    if not isinstance(names, list) or not names:
                        raise EditError("„names“ muss eine Liste von Feldnamen sein.")
                    chosen = [_find_field(fields, str(n)) for n in names]
                elif which == "all":
                    chosen = [f for f in fields if f.kind != "signature"]
                elif which == "filled":
                    chosen = [f for f in fields if f.filled]
                elif which == "empty":
                    chosen = [f for f in fields if f.kind in ("text", "checkbox", "radio", "choice") and not f.filled]
                else:
                    raise EditError("„which“ ist filled, empty, all oder names.")
                lock = kind == "lock_fields"
                for f in chosen:
                    _set_flag(f, 1, lock)
                form_touched = True
                names_txt = ", ".join(f.name for f in chosen[:30]) + (" …" if len(chosen) > 30 else "")
                report.append(f"{len(chosen)} Feld(er) {'gesperrt' if lock else 'freigegeben'}: {names_txt or '–'}")
                if not chosen:
                    ctx.notes.append("Es gab keine passenden Felder; nichts wurde (ent)sperrt.")
            elif kind == "flatten":
                removed = _flatten(writer, fields)
                report.append(f"Formular festgeschrieben ({removed} Felder entfernt)")
            elif kind == "delete_pages":
                pages = sorted(set(_pdf_page_list(op, total)), reverse=True)
                if len(pages) >= total:
                    raise EditError("Es müsste mindestens eine Seite übrig bleiben.")
                for n in pages:
                    writer.remove_page(n - 1)
                report.append(f"Seite(n) {', '.join(map(str, sorted(pages)))} gelöscht")
            elif kind == "rotate_pages":
                angle = _int(op, "angle", minimum=-360)
                if angle % 90:
                    raise EditError("„angle“ muss ein Vielfaches von 90 sein (90, 180, 270).")
                pages = _pdf_page_list(op, total) if op.get("pages") not in (None, "") else list(range(1, total + 1))
                for n in pages:
                    writer.pages[n - 1].rotate(angle)
                report.append(f"Seite(n) {', '.join(map(str, pages))} um {angle}° gedreht")
            elif kind == "reorder":
                order = _pdf_page_list(op, total, "order")
                if len(set(order)) != len(order):
                    raise EditError("„order“ darf keine Seite doppelt enthalten.")
                new = pypdf.PdfWriter()
                src = pypdf.PdfReader(io.BytesIO(_write(writer)))
                for n in order:
                    new.add_page(src.pages[n - 1])
                writer = new
                root = writer._root_object
                report.append("Seiten neu angeordnet: " + ", ".join(map(str, order)))
                ctx.notes.append("Beim Umsortieren gehen Formularfelder verloren; das Ergebnis ist ein einfaches PDF.")
            elif kind == "merge":
                other = _str(op, "file")
                blob = ctx.get_file(other)
                if blob is None:
                    raise EditError(f"Die Datei „{other}“ gibt es in diesem Chat nicht (file_list zeigt die vorhandenen).")
                src = _open_pdf(blob)
                at = _int(op, "after", minimum=0, default=total)
                if at > total:
                    raise EditError(f"„after“ ist {at}, das PDF hat {total} Seiten.")
                for offset, page in enumerate(src.pages):
                    writer.insert_page(page, at + offset)
                report.append(f"{len(src.pages)} Seite(n) aus „{other}“ nach Seite {at} eingefügt")
            elif kind == "add_text":
                report.append(_add_text(writer, op))
            elif kind == "add_text_field":
                report.append(_add_text_field(writer, op))
                form_touched = True
            else:
                raise EditError("Unbekannter Befehl. Möglich bei PDF: fill_fields, lock_fields, unlock_fields, flatten, add_text, add_text_field, delete_pages, rotate_pages, reorder, merge.")
        except EditError as exc:
            raise EditError(f"Änderung {i + 1} ({kind}): {exc}") from None
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            raise EditError(f"Änderung {i + 1} ({kind}) ist an der PDF-Struktur gescheitert ({type(exc).__name__}: {str(exc)[:120]}).") from None
    if form_touched and "/AcroForm" in writer._root_object:
        acro = writer._root_object["/AcroForm"].get_object()
        acro[NameObject("/NeedAppearances")] = BooleanObject(True)
    return _write(writer), report


def _write(writer: Any) -> bytes:
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


# ================================================================ gemeinsamer Zugang

READERS: dict[str, Callable[[bytes, Any], str]] = {
    "text": read_text, "docx": read_docx, "xlsx": read_xlsx, "pptx": read_pptx, "pdf": read_pdf,
}
EDITORS: dict[str, Callable[[bytes, list[dict], Context], tuple[bytes, list[str]]]] = {
    "text": edit_text, "docx": edit_docx, "xlsx": edit_xlsx, "pptx": edit_pptx, "pdf": edit_pdf,
}


def read_file(kind: str, data: bytes, part: Any = None) -> str:
    if kind not in READERS:
        raise EditError(f"Das Format „{kind}“ kann ich nicht lesen.")
    try:
        return READERS[kind](data, part)
    except EditError:
        raise
    except RecursionError:
        raise EditError("Die Datei ist zu verschachtelt zum Lesen.") from None


def _verify(kind: str, data: bytes) -> None:
    """Prüft, dass das Ergebnis wieder lesbar ist; sonst wird nichts gespeichert."""
    try:
        if kind == "docx":
            _open_docx(data)
        elif kind == "xlsx":
            _load_xlsx(data)
        elif kind == "pptx":
            _open_pptx(data)
        elif kind == "pdf":
            reader = _open_pdf(data)
            len(reader.pages)
        else:
            decode_text(data)
    except EditError as exc:
        raise EditError(f"Das Ergebnis wäre nicht lesbar ({exc}). Nichts wurde gespeichert.") from None


def edit_file(kind: str, data: bytes, operations: Any, ctx: Context | None = None) -> tuple[bytes, list[str], list[str]]:
    """Wendet ``operations`` an; liefert (neue Datei, Bericht je Änderung, Hinweise). Wirft EditError ohne Teilergebnis."""
    ctx = ctx or Context()
    if kind not in EDITORS:
        raise EditError(f"Das Format „{kind}“ kann ich nicht bearbeiten.")
    if not isinstance(operations, list) or not operations:
        raise EditError("„operations“ muss eine nicht leere Liste von Änderungen sein, jede mit einem „op“.")
    if len(operations) > MAX_OPERATIONS:
        raise EditError(f"Zu viele Änderungen auf einmal (höchstens {MAX_OPERATIONS}); teile sie auf.")
    for n, op in enumerate(operations, 1):
        if not isinstance(op, dict) or not isinstance(op.get("op"), str):
            raise EditError(f"Änderung {n} braucht ein Feld „op“ (Name des Befehls).")
    if len(data) > MAX_EDIT_BYTES:
        raise EditError(f"Die Datei ist zu groß zum Bearbeiten (höchstens {MAX_EDIT_BYTES // 1024 // 1024} MB).")
    try:
        new, report = EDITORS[kind](data, operations, ctx)
    except EditError:
        raise
    except RecursionError:
        raise EditError("Die Datei ist zu verschachtelt zum Bearbeiten.") from None
    except MemoryError:
        raise EditError("Die Datei ist zu umfangreich zum Bearbeiten.") from None
    except Exception as exc:  # noqa: BLE001 - Bibliotheksfehler bei ungewöhnlichen Dateien: der KI verständlich melden
        raise EditError(f"Die Bearbeitung ist an der Dateistruktur gescheitert ({type(exc).__name__}: {str(exc)[:160]}). Nichts wurde gespeichert.") from None
    if len(new) > MAX_EDIT_BYTES:
        raise EditError("Das Ergebnis wäre zu groß. Nichts wurde gespeichert.")
    _verify(kind, new)
    return new, report, list(dict.fromkeys(ctx.notes))
