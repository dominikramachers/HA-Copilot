"""Gedächtnis aus einem Export von Claude (oder aus anderem Text) einlesen.

Claude bietet unter „Einstellungen > Gedächtnis“ einen Export als ZIP mit Markdown-Dateien an (Profil, Vorlieben, Bereiche,
Themen, Personen). Dieses Modul liest so ein ZIP oder eine einzelne Markdown-/Textdatei und macht daraus Vorschläge:

* Einträge für das Gedächtnis (Thema bis 60, Text bis 800 Zeichen), zu lange Texte werden an Zeilengrenzen geteilt;
* „Meine Anweisungen“ aus der Datei ``preferences.md`` (Claudes Vorlieben sind das Gegenstück zu den Anweisungen).

Es wird nichts gespeichert: Die Person sieht die Vorschläge, ändert sie und übernimmt dann bewusst. Das genaue Aufbau des
Exports ist nicht festgeschrieben, deshalb liest der Parser allgemein: Kopfdaten (``---``), Überschriften und Listenpunkte,
Markierungen wie ``[stated]`` und ``(for=code)`` werden entfernt. Hinweise auf Zugangsdaten und Kontonummern werden aussortiert.
"""
from __future__ import annotations

import base64
import binascii
import io
import re
import zipfile

from .attachments import _is_utf8, _looks_binary
from .context_tools import CONTENT_MAX, TOPIC_MAX, _RESERVED, _SECRET
from .db import INSTRUCTIONS_MAX
from .i18n import tr
from .knowledge import clean_name

MAX_UPLOAD_BYTES = 4 * 1024 * 1024
MAX_BASE64_CHARS = int(MAX_UPLOAD_BYTES * 4 / 3) + 16
ZIP_ENTRIES = 400
ZIP_MEMBER_BYTES = 2 * 1024 * 1024
ZIP_TOTAL_BYTES = 20 * 1024 * 1024
MAX_ENTRIES = 400  # Vorschläge je Import
MAX_SKIPPED = 30
TEXT_EXT = {"md", "markdown", "txt", "text"}
INSTRUCTION_STEMS = {"preferences", "preference", "instructions", "custom-instructions", "anweisungen", "vorlieben"}
KNOWN_FOLDERS = {"areas", "topics", "people", "projects"}


class ImportError_(ValueError):
    """Meldung für die Person."""


_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^(\s*)(?:[-*+•]|\d{1,3}[.)])\s+")
_TAG_AT_START = re.compile(r"^(?:\[[A-Za-z_=:/ -]{2,24}\]\s*)+")
_TAG_AT_END = re.compile(r"\s*\((?:for|source|src|from)\s*=[^)]*\)\s*$", re.I)
_PLACEHOLDER = re.compile(r"^\(?\s*(not yet written|noch nicht geschrieben|empty|leer|none|keine)\s*\)?\.?$", re.I)


def _text(data: bytes) -> str:
    text = data.decode("utf-8-sig") if _is_utf8(data) else data.decode("cp1252", "replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def decode(b64: str) -> bytes:
    if len(b64) > MAX_BASE64_CHARS:
        raise ImportError_(tr("Die Datei ist zu groß (höchstens {mb} MB).", mb=MAX_UPLOAD_BYTES // 1024 // 1024))
    try:
        return base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise ImportError_(tr("Die Datei konnte nicht gelesen werden.")) from None


def read_upload(name: str, data: bytes) -> tuple[list[tuple[str, str]], list[dict]]:
    """Datei oder ZIP in ``[(Pfad, Text)]`` umwandeln; Übersprungenes steht mit Grund in der zweiten Liste."""
    label = clean_name(name) or tr("Datei")
    if not data:
        raise ImportError_(tr("Die Datei ist leer."))
    if not data.startswith(b"PK\x03\x04"):
        if _looks_binary(data):
            raise ImportError_(tr("„{label}“ ist weder ein ZIP noch eine Text- oder Markdown-Datei.", label=label))
        return [(label, _text(data))], []
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ImportError_(tr("„{label}“ ist beschädigt oder kein gültiges ZIP.", label=label)) from None
    infos = [i for i in archive.infolist() if not i.is_dir()]
    if len(infos) > ZIP_ENTRIES or sum(i.file_size for i in infos) > ZIP_TOTAL_BYTES:
        raise ImportError_(tr("„{label}“ ist zu groß für einen Gedächtnis-Export.", label=label))
    files: list[tuple[str, str]] = []
    skipped: list[dict] = []
    for info in infos:
        member = clean_name(info.filename)
        base = (member or "").rsplit("/", 1)[-1]
        if not member or info.filename.startswith("__MACOSX/") or base.startswith("."):
            continue
        if base.rsplit(".", 1)[-1].lower() not in TEXT_EXT or "." not in base:
            skipped.append({"name": member, "reason": tr("Kein Text- oder Markdown-Format")})
            continue
        if info.file_size > ZIP_MEMBER_BYTES:
            skipped.append({"name": member, "reason": tr("zu groß")})
            continue
        try:
            with archive.open(info) as handle:
                raw = handle.read(ZIP_MEMBER_BYTES + 1)
        except (zipfile.BadZipFile, RuntimeError, OSError, EOFError):
            skipped.append({"name": member, "reason": tr("nicht lesbar")})
            continue
        if len(raw) > ZIP_MEMBER_BYTES or _looks_binary(raw):
            skipped.append({"name": member, "reason": tr("nicht lesbar")})
            continue
        files.append((member, _text(raw)))
    if not files:
        raise ImportError_(tr("In „{label}“ sind keine Markdown- oder Textdateien.", label=label))
    return files, skipped[:MAX_SKIPPED]


def _front(text: str) -> tuple[dict[str, str], str]:
    """Kopfdaten zwischen ``---`` und den übrigen Text trennen."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text
    head = text[4:end]
    rest = text[end + 4:]
    rest = rest.split("\n", 1)[1] if "\n" in rest else ""
    meta = {}
    for line in head.split("\n"):
        key, sep, value = line.partition(":")
        if sep and key.strip() and not key.startswith((" ", "-")):
            meta[key.strip().lower()] = value.strip().strip("\"'")
    return meta, rest.lstrip("\n")


def _clean_line(line: str) -> str:
    line = line.rstrip()
    match = _BULLET.match(line)
    prefix = ""
    if match:
        prefix = "- "
        line = line[match.end():]
    line = _TAG_AT_START.sub("", line.strip())
    line = _TAG_AT_END.sub("", line).strip()
    if not line or _PLACEHOLDER.match(line):
        return ""
    return prefix + line


def _blocks(body: str) -> list[tuple[str | None, list[str]]]:
    """Text in Abschnitte (Überschrift ab Ebene 2, bereinigte Zeilen) teilen. Die Überschrift der Ebene 1 ist nur der Titel."""
    blocks: list[tuple[str | None, list[str]]] = [(None, [])]
    for raw in body.split("\n"):
        heading = _HEADING.match(raw)
        if heading:
            if len(heading.group(1)) == 1:
                continue
            blocks.append((_TAG_AT_START.sub("", heading.group(2)).strip(), []))
            continue
        line = _clean_line(raw)
        if line:
            blocks[-1][1].append(line)
    return [(h, lines) for h, lines in blocks if lines]


def humanize(stem: str) -> str:
    text = re.sub(r"[-_]+", " ", stem).strip()
    return text[:1].upper() + text[1:] if text else ""


def _fit_topic(topic: str, suffix: str = "") -> str:
    topic = " ".join(topic.split())
    if _RESERVED.match(topic):
        topic = _RESERVED.sub("HA –", topic, count=1)
    room = TOPIC_MAX - len(suffix)
    if len(topic) > room:
        topic = topic[: room - 1].rstrip() + "…"
    return topic + suffix


def _split_long(line: str) -> list[str]:
    parts = []
    while len(line) > CONTENT_MAX:
        cut = line.rfind(" ", 0, CONTENT_MAX)
        cut = cut if cut > CONTENT_MAX // 2 else CONTENT_MAX
        parts.append(line[:cut].rstrip())
        line = line[cut:].lstrip()
    if line:
        parts.append(line)
    return parts


def _chunks(lines: list[str]) -> list[str]:
    """Zeilen zu Texten bis ``CONTENT_MAX`` Zeichen zusammenfassen (immer an Zeilengrenzen, sehr lange Zeilen an Wortgrenzen)."""
    out: list[str] = []
    current = ""
    for line in (p for raw in lines for p in _split_long(raw)):
        if current and len(current) + 1 + len(line) > CONTENT_MAX:
            out.append(current)
            current = ""
        current = f"{current}\n{line}" if current else line
    if current:
        out.append(current)
    return out


def _bullet_topic(line: str) -> str:
    words = re.sub(r"^[-\s]+", "", line).split()
    return " ".join(words[:6]).rstrip(".,;:!?–-")[:50] or tr("Notiz")


class _Names:
    """Vergibt eindeutige Themen innerhalb eines Imports (Groß-/Kleinschreibung egal)."""

    def __init__(self) -> None:
        self.used: set[str] = set()

    def take(self, topic: str) -> str:
        topic = _fit_topic(topic)
        candidate, n = topic, 1
        while candidate.casefold() in self.used:
            n += 1
            candidate = _fit_topic(topic, f" ({n})")
        self.used.add(candidate.casefold())
        return candidate


def _kind(path: str, meta: dict[str, str]) -> tuple[str, str, bool]:
    """(Name der Datei, Ordner-Art, Aufbau wie bei Claude?) aus Pfad und Kopfdaten."""
    parts = path.split("/")
    stem = parts[-1].rsplit(".", 1)[0]
    folder = next((p.lower() for p in reversed(parts[:-1]) if p.lower() in KNOWN_FOLDERS - {"projects"}), "")
    claude_layout = bool(meta) or bool(folder) or stem.lower() in {"profile", "preferences"}
    return stem, folder, claude_layout


def parse(files: list[tuple[str, str]]) -> dict:
    """Vorschläge aus den gelesenen Dateien. Keine Datenbank, keine Prüfung gegen vorhandene Einträge.

    Rückgabe: ``entries`` (``topic``, ``content``, ``source``), ``instructions`` (Text, ``truncated``),
    ``skipped`` (``name``, ``reason``).
    """
    names = _Names()
    entries: list[dict] = []
    skipped: list[dict] = []
    instruction_files: list[tuple[int, str, list[tuple[str | None, list[str]]]]] = []
    parsed = []
    for path, text in sorted(files, key=lambda f: (f[0].count("/"), f[0].lower())):
        meta, body = _front(text)
        blocks = _blocks(body)
        stem, folder, claude_layout = _kind(path, meta)
        if not blocks:
            skipped.append({"name": path, "reason": tr("leer")})
            continue
        if stem.lower() in INSTRUCTION_STEMS:
            instruction_files.append((path.count("/"), path, blocks))
            continue
        parsed.append((path, stem, folder, claude_layout, blocks))

    # Vorlieben: die Datei auf der obersten Ebene sind „Meine Anweisungen“, weitere (etwa aus Projekten) werden Einträge.
    instructions_lines: list[str] = []
    if instruction_files:
        instruction_files.sort()
        top_depth = instruction_files[0][0]
        for depth, path, blocks in instruction_files:
            if depth == top_depth and not instructions_lines:
                for heading, lines in blocks:
                    if heading:
                        instructions_lines.append(heading + ":")
                    instructions_lines.extend(lines)
            else:
                parsed.append((path, tr("Vorlieben (Projekt)"), "", True, blocks))
    instructions, truncated = "", False
    if instructions_lines:
        for line in instructions_lines:
            if len(instructions) + len(line) + 1 > INSTRUCTIONS_MAX:
                truncated = True
                break
            instructions += ("\n" if instructions else "") + line

    for path, stem, folder, claude_layout, blocks in parsed:
        base = tr("Profil") if stem.lower() == "profile" else humanize(stem)
        if folder == "people":
            base = tr("Person: {name}", name=base)
        elif not claude_layout:
            base = ""
        for heading, lines in blocks:
            if not claude_layout and heading is None and len(lines) >= 2 and all(line.startswith("- ") for line in lines):
                for line in lines:  # lose Liste ohne Überschrift (zum Beispiel aus einem anderen KI-Dienst): je Punkt ein Eintrag
                    for chunk in _chunks([line[2:]]):
                        entries.append({"topic": names.take(_bullet_topic(chunk)), "content": chunk, "source": path})
                continue
            if claude_layout:
                topic = f"{base} – {heading}" if heading and base else (heading or base)
            else:
                topic = heading or humanize(path.rsplit("/", 1)[-1].rsplit(".", 1)[0]) or tr("Import")
            pieces = _chunks(lines)
            for n, chunk in enumerate(pieces, 1):
                title = names.take(topic if n == 1 else _fit_topic(topic, f" ({n})"))
                entries.append({"topic": title, "content": chunk, "source": path})

    kept = []
    for entry in entries:
        if "\n" not in entry["content"] and entry["content"].startswith("- "):
            entry["content"] = entry["content"][2:]  # ein einzelner Punkt braucht kein Listenzeichen
        if len(entry["content"]) < 3:
            continue
        if _SECRET.search(entry["topic"]) or _SECRET.search(entry["content"]):
            skipped.append({"name": entry["topic"], "reason": tr("enthält vermutlich Zugangsdaten oder Kontonummern")})
            continue
        kept.append(entry)
    if len(kept) > MAX_ENTRIES:
        skipped.append({"name": tr("Weitere Einträge"), "reason": tr("mehr als {n} Einträge auf einmal", n=MAX_ENTRIES)})
        kept = kept[:MAX_ENTRIES]
    if instructions and _SECRET.search(instructions):
        instructions = ""
        skipped.append({"name": tr("Meine Anweisungen"), "reason": tr("enthält vermutlich Zugangsdaten oder Kontonummern")})
    return {"entries": kept, "instructions": {"text": instructions, "truncated": truncated}, "skipped": skipped[:MAX_SKIPPED]}
