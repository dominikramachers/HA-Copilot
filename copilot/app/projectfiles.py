"""Dateien im Projekt ablegen: Originale (auch Bilder und Binärdateien) und Artefakte der KI.

Eine Projektdatei ist eine Zeile im Projektwissen (``knowledge``) mit dem durchsuchbaren Text und, wenn vorhanden, dem Original
auf der Platte. So finden ``knowledge_search`` und ``knowledge_read`` auch abgelegte Word-, Excel- und PDF-Dateien, und
Bilder oder Scans stehen mit einem Platzhalter im Inhaltsverzeichnis. Hochgeladene Dateien der Person überschreibt die KI nie.
"""
from __future__ import annotations

import mimetypes
from dataclasses import dataclass

from . import knowledge as kn
from .db import Store
from .i18n import tr

FILE_MAX_BYTES = 25 * 1024 * 1024  # je Datei
PROJECT_MAX_BYTES = 300 * 1024 * 1024  # Originale je Projekt zusammen
ARTIFACT_DIR = "Artefakte/"  # Text, den die KI selbst schreibt (Seiten, Skripte, Tabellen als CSV …), nicht aus einer Datei kopiert
ARTIFACT_EXT = {"html", "htm", "css", "js", "json", "csv", "tsv", "md", "txt", "py", "yaml", "yml", "xml", "sh", "sql", "svg", "ini", "toml"}


class ProjectFileError(ValueError):
    """Meldung für die Person (und die KI)."""


@dataclass
class Saved:
    name: str
    size: int
    has_text: bool
    replaced: bool


def mime_of(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def placeholder(name: str, mime: str, size: int) -> str:
    return f"[Datei {name} ({mime}, {size // 1024 or 1} KB): kein durchsuchbarer Text. Das Original ist im Projekt gespeichert.]"


def save(
    store: Store, profile_id: str, project_id: str, name: str, data: bytes, *, origin: str, text: str | None = None, force_new: bool = False
) -> Saved:
    """Datei im Projekt ablegen; wirft ``ProjectFileError`` mit einer verständlichen Meldung."""
    clean = kn.clean_name(name)
    if clean is None or clean.endswith("/"):
        raise ProjectFileError(tr("Der Dateiname ist ungültig."))
    if not data:
        raise ProjectFileError(tr("Die Datei ist leer."))
    if len(data) > FILE_MAX_BYTES:
        raise ProjectFileError(tr("Die Datei ist zu groß (höchstens {mb} MB).", mb=FILE_MAX_BYTES // 1024 // 1024))
    entries = store.list_knowledge(profile_id, project_id)
    if entries is None:
        raise ProjectFileError(tr("Das Projekt gibt es nicht mehr."))
    old = next((e for e in entries if e["name"].lower() == clean.lower()), None)
    if old is not None and origin == "ai" and old["origin"] == "upload" and (old["has_file"] or not old["name"].startswith(("KI/", ARTIFACT_DIR))):
        raise ProjectFileError(tr("„{name}“ hat die Person selbst hochgeladen und wird nicht überschrieben. Wähle einen anderen Namen.", name=old["name"]))
    if old is None and len(entries) >= kn.MAX_FILES:
        raise ProjectFileError(tr("Dateilimit erreicht ({max}). Zuerst Dateien löschen.", max=kn.MAX_FILES))
    used = store.project_file_bytes_total(profile_id, project_id) - (old["file_size"] if old else 0)
    if used + len(data) > PROJECT_MAX_BYTES:
        raise ProjectFileError(tr("Der Speicher des Projekts ist voll ({mb} MB). Zuerst Dateien löschen.", mb=PROJECT_MAX_BYTES // 1024 // 1024))
    mime = mime_of(clean)
    if text is None:
        try:
            text = kn.extract_text(data)
        except kn.KnowledgeError:
            text = ""
    has_text = bool(text.strip())
    content = text if has_text else placeholder(clean, mime, len(data))
    chars = sum(e["size"] for e in entries) - (old["size"] if old else 0)
    if chars + len(content) > kn.MAX_PROJECT_CHARS:
        raise ProjectFileError(tr("Die Textgrenze des Projekts ist erreicht. Zuerst Dateien löschen."))
    if store.add_knowledge(profile_id, project_id, old["name"] if old else clean, content, data=data, mime=mime, origin=origin) is None:
        raise ProjectFileError(tr("Das Projekt gibt es nicht mehr."))
    return Saved(old["name"] if old else clean, len(data), has_text, old is not None)
