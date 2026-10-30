"""Projektwissen: Dateien lesen (Text, Word, Excel, PDF, ZIP mit solchen Dateien) und gezielt durchsuchen.

Das Wissen liegt als reiner Text in der Datenbank (zählt in der HA-Sicherung). Die KI bekommt nicht alles auf einmal,
sondern ein Inhaltsverzeichnis und sucht oder liest bei Bedarf, so bleibt auch ein großes Wissen bezahlbar.
"""
from __future__ import annotations

import base64
import binascii
import io
import re
import zipfile

from . import office
from .i18n import tr
from .attachments import _is_utf8, _looks_binary

MAX_FILE_CHARS = 1_000_000  # Text je Datei
MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # Rohdaten je Hochladen (eine Datei oder ein ZIP)
MAX_BASE64_CHARS = int(MAX_UPLOAD_BYTES * 4 / 3) + 16
MAX_FILES = 300  # Dateien je Projekt
MAX_PROJECT_CHARS = 15_000_000  # Text je Projekt zusammen
ZIP_MAX_ENTRIES = 600
ZIP_MEMBER_BYTES = 4 * 1024 * 1024
ZIP_TOTAL_BYTES = 60 * 1024 * 1024
NAME_MAX = 160
SKIP_EXT = {
    "png", "jpg", "jpeg", "gif", "webp", "bmp", "ico", "svg", "mp3", "mp4", "mov", "avi", "mkv", "wav", "zip", "gz", "tgz",
    "7z", "rar", "exe", "dll", "so", "bin", "pyc", "class", "jar", "woff", "woff2", "ttf", "otf", "db", "sqlite", "sqlite3",
}


class KnowledgeError(ValueError):
    """Meldung für die Person (ohne Dateinamen; der Aufrufer ergänzt ihn)."""


def clean_name(raw: str) -> str | None:
    """Dateiname bzw. relativer Pfad im Wissen; ``None``, wenn nichts Brauchbares übrig bleibt."""
    parts = [re.sub(r"[\x00-\x1f\x7f<>\"\\|?*]", "", p).strip() for p in (raw or "").replace("\\", "/").split("/")]
    parts = [p for p in parts if p and p != "."]
    if not parts or any(p == ".." for p in parts):
        return None
    name = "/".join(parts)
    if len(name) > NAME_MAX:
        name = "…" + name[-(NAME_MAX - 1):]
    return name


def _decode(data: bytes) -> str:
    text = data.decode("utf-8-sig") if _is_utf8(data) else data.decode("cp1252", "replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def extract_text(data: bytes) -> str:
    """Text einer einzelnen Datei; wirft ``KnowledgeError``."""
    if not data:
        raise KnowledgeError("ist leer.")
    try:
        if data.startswith(b"%PDF-"):
            text = office.pdf_to_text(data, MAX_FILE_CHARS)
            if not text.strip():
                raise KnowledgeError(tr("enthält keinen lesbaren Text (vermutlich ein Scan)."))
            return text
        kind = office.kind_of(data)
        if kind == "word":
            return office.docx_to_text(data, MAX_FILE_CHARS)
        if kind == "excel":
            return office.xlsx_to_text(data, MAX_FILE_CHARS)
    except office.OfficeError as exc:
        raise KnowledgeError(str(exc)) from None
    if data.startswith(b"PK\x03\x04") or _looks_binary(data):
        raise KnowledgeError(tr("hat ein Format, das nicht als Wissen taugt (nur Text, Markdown, Word, Excel, PDF)."))
    text = _decode(data)
    if len(text) > MAX_FILE_CHARS:
        raise KnowledgeError(tr("ist zu lang (höchstens {file_chars} Zeichen).", file_chars=format(MAX_FILE_CHARS, ',')).replace(",", "."))
    if not text.strip():
        raise KnowledgeError("ist leer.")
    return text


def _is_zip_archive(data: bytes) -> bool:
    if not data.startswith(b"PK\x03\x04"):
        return False
    try:
        return office.kind_of(data) is None
    except office.OfficeError:
        return False


def expand(name: str, data: bytes) -> tuple[list[tuple[str, str]], list[dict]]:
    """Hochgeladene Datei oder ZIP in ``[(Name, Text)]`` umwandeln; Übersprungenes mit Grund in ``skipped``."""
    label = clean_name(name) or tr("Datei")
    if not _is_zip_archive(data):
        try:
            return [(label, extract_text(data))], []
        except KnowledgeError as exc:
            raise KnowledgeError(tr("„{label}“ {exc}", label=label, exc=exc)) from None
    items: list[tuple[str, str]] = []
    skipped: list[dict] = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise KnowledgeError(tr("„{label}“ ist beschädigt oder kein gültiges ZIP.", label=label)) from None
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if len(infos) > ZIP_MAX_ENTRIES or sum(i.file_size for i in infos) > ZIP_TOTAL_BYTES:
        raise KnowledgeError(tr("„{label}“ ist zu groß oder zu verschachtelt (höchstens {zip_max_entries} Dateien, {mb} MB entpackt).", label=label, zip_max_entries=ZIP_MAX_ENTRIES, mb=ZIP_TOTAL_BYTES // 1024 // 1024))
    for info in infos:
        member = clean_name(info.filename)
        base = (member or "").rsplit("/", 1)[-1]
        if not member or info.filename.startswith("__MACOSX/") or base.startswith(".") or "/." in member:
            continue  # Systemdateien still übergehen
        if base.rsplit(".", 1)[-1].lower() in SKIP_EXT and "." in base:
            skipped.append({"name": member, "reason": tr("Dateityp wird nicht übernommen")})
            continue
        if info.file_size > ZIP_MEMBER_BYTES:
            skipped.append({"name": member, "reason": tr("zu groß")})
            continue
        try:
            with zf.open(info) as handle:
                raw = handle.read(ZIP_MEMBER_BYTES + 1)
            if len(raw) > ZIP_MEMBER_BYTES:
                skipped.append({"name": member, "reason": tr("zu groß")})
                continue
            items.append((member, extract_text(raw)))
        except KnowledgeError as exc:
            skipped.append({"name": member, "reason": str(exc).removeprefix("ist ").rstrip(".")})
        except (zipfile.BadZipFile, RuntimeError, OSError, EOFError):
            skipped.append({"name": member, "reason": "nicht lesbar"})
    if not items and not skipped:
        raise KnowledgeError(tr("„{label}“ enthält keine Dateien.", label=label))
    return items, skipped


def decode_upload(b64: str) -> bytes:
    if len(b64) > MAX_BASE64_CHARS:
        raise KnowledgeError(tr("Die Datei ist zu groß (höchstens {mb} MB je Hochladen).", mb=MAX_UPLOAD_BYTES // 1024 // 1024))
    try:
        return base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise KnowledgeError(tr("Die Datei konnte nicht gelesen werden.")) from None


# ------------------------------------------------------------------------ Suche

CHUNK_CHARS = 1400
_WORD = re.compile(r"[\wäöüßÄÖÜ.\-/]{2,}")
_STOP = {"der", "die", "das", "und", "oder", "ein", "eine", "wie", "was", "wo", "ist", "sind", "von", "mit", "für", "zu", "im", "in", "an", "auf", "the", "and", "for"}


def terms(query: str) -> list[str]:
    seen: list[str] = []
    for word in _WORD.findall(query.lower()):
        word = word.strip(".-/")
        if len(word) >= 2 and word not in _STOP and word not in seen:
            seen.append(word)
    return seen[:10]


def chunks(text: str) -> list[tuple[int, str]]:
    """Abschnitte (ab Zeile, Text) von etwa CHUNK_CHARS Zeichen an Zeilengrenzen."""
    out: list[tuple[int, str]] = []
    current: list[str] = []
    size = 0
    start = 1
    for number, line in enumerate(text.split("\n"), 1):
        if current and size + len(line) > CHUNK_CHARS:
            out.append((start, "\n".join(current)))
            current, size, start = [], 0, number
        current.append(line)
        size += len(line) + 1
    if current:
        out.append((start, "\n".join(current)))
    return out


def search(files: list[tuple[str, str]], query: str, limit: int = 8, excerpt: int = 700) -> list[dict]:
    """Beste Abschnitte zur Suchanfrage: ``[{name, line, text, score}]``."""
    words = terms(query)
    if not words:
        return []
    scored: list[tuple[float, str, int, str]] = []
    for name, text in files:
        lowered_name = name.lower()
        name_hits = sum(1 for w in words if w in lowered_name)
        for line, chunk in chunks(text):
            low = chunk.lower()
            present = [w for w in words if w in low]
            if not present and not name_hits:
                continue
            score = sum(min(low.count(w), 5) for w in present) + 3 * name_hits + 4 * len(present) ** 1.5
            if len(present) == len(words):
                score *= 1.5
            scored.append((score, name, line, chunk))
    scored.sort(key=lambda r: -r[0])
    results = []
    for score, name, line, chunk in scored[:limit]:
        first = min((chunk.lower().find(w) for w in words if w in chunk.lower()), default=0)
        begin = max(0, first - excerpt // 4)
        results.append({"name": name, "line": line, "text": chunk[begin:begin + excerpt].strip(), "score": round(score, 1)})
    return results


def read_lines(text: str, first_line: int = 1, max_chars: int = 20000) -> tuple[str, int, int, int]:
    """Zeilen ab ``first_line`` bis ``max_chars``: (Text, erste, letzte, Gesamtzahl der Zeilen)."""
    lines = text.split("\n")
    total = len(lines)
    start = max(1, min(first_line, total))
    out: list[str] = []
    size = 0
    last = start - 1
    for number in range(start, total + 1):
        line = lines[number - 1]
        if out and size + len(line) > max_chars:
            break
        out.append(line[:max_chars])
        size += len(line) + 1
        last = number
    return "\n".join(out), start, last, total


def find_file(files: list[tuple[str, str]], wanted: str) -> tuple[str, str] | None:
    """Datei nach Namen: genau (ohne Groß-/Kleinschreibung), sonst eindeutig als Endung oder Teilstück."""
    low = wanted.strip().lower()
    for name, text in files:
        if name.lower() == low:
            return name, text
    for test in (lambda n: n.lower().endswith("/" + low), lambda n: low in n.lower()):
        hits = [(n, t) for n, t in files if test(n)]
        if len(hits) == 1:
            return hits[0]
    return None
