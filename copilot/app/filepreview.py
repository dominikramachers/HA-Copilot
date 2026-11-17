"""Erzeugte Dateien im Fenster neben dem Chat: Vorschau, Bearbeiten, Kopieren (wie bei Artefakten).

Textdateien lassen sich lesen und ändern. Word, Excel, PowerPoint und PDF zeigen den enthaltenen Text, nur zum Lesen:
Ihr Aufbau (Formatierung, Formeln, Seitenlayout) würde beim Zurückschreiben verloren gehen.
"""
from __future__ import annotations

from . import office
from .i18n import tr
from .outbox import OFFICE_TYPES, TEXT_TYPES, render_text

VIEW_CHARS = 200_000  # so viel Text zeigt das Fenster höchstens
EDIT_CHARS = 200_000  # größer als das, was das Fenster zeigt, wird nicht bearbeitet
BOM = "﻿"


class PreviewError(ValueError):
    """Zu dieser Datei gibt es keine Vorschau (Meldung für die Person)."""


def extension(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else name.lower()


def kind_of(name: str) -> str | None:
    """``text`` (lesen und bearbeiten), ``extract`` (nur den Text lesen) oder ``None`` (keine Vorschau)."""
    ext = extension(name)
    if ext in TEXT_TYPES:
        return "text"
    if ext in OFFICE_TYPES:
        return "extract"
    return None


def describe(name: str, data: bytes) -> dict:
    """Inhalt für das Fenster: ``kind``, ``content``, ``truncated``, ``editable``. Wirft :class:`PreviewError`."""
    kind = kind_of(name)
    if kind is None:
        raise PreviewError(tr("Für diese Dateiart gibt es keine Vorschau."))
    ext = extension(name)
    if kind == "text":
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise PreviewError(tr("Diese Datei ist kein lesbarer Text (UTF-8).")) from None
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        truncated = len(text) > VIEW_CHARS
        return {"kind": "text", "content": text[:VIEW_CHARS], "truncated": truncated, "editable": not truncated and len(text) <= EDIT_CHARS}
    try:
        if ext == "pdf":
            text = office.pdf_to_text(data, VIEW_CHARS + 1)
        else:
            reader = {"docx": office.docx_to_text, "xlsx": office.xlsx_to_text, "pptx": office.pptx_to_text}[ext]
            text = reader(data, VIEW_CHARS + 1)
    except office.OfficeError as exc:
        raise PreviewError(str(exc)) from None
    except Exception:  # fremde Dateien dürfen die Vorschau nicht abstürzen lassen
        raise PreviewError(tr("Der Text dieser Datei konnte nicht gelesen werden.")) from None
    if not text.strip():
        text = ""
    return {"kind": "extract", "content": text[:VIEW_CHARS], "truncated": len(text) > VIEW_CHARS, "editable": False}


def encode(name: str, content: str) -> bytes:
    """Text zurück in Bytes, mit denselben Regeln wie beim Erzeugen (Zeilenenden, BOM für Windows-Programme)."""
    if kind_of(name) != "text":
        raise PreviewError(tr("Diese Dateiart lässt sich hier nicht bearbeiten."))
    return render_text(name, content)
