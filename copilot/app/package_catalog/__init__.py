"""Katalog der Plugins (Pakete) zum Entdecken (``catalog.json``).

Ein Plugin bündelt Skills aus dem Skill-Katalog und Konnektoren aus dem Konnektoren-Katalog zu einem Thema. Der Katalog nennt nur
deren Kennungen; Texte, Dateien und Adressen stehen dort. Nichts hier ist ausführbar.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..i18n import language

CATALOG_PATH = Path(__file__).parent / "catalog.json"
_catalog: dict | None = None


def _load() -> dict:
    global _catalog
    if _catalog is None:
        _catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return _catalog


def _text(value: Any, lang: str) -> str:
    if isinstance(value, dict):
        return str(value.get(lang) or value.get("de") or "")
    return str(value or "")


def find(plugin_id: str) -> dict | None:
    """Rohdaten eines Eintrags (Texte noch zweisprachig)."""
    return next((e for e in _load()["plugins"] if e["id"] == plugin_id), None)


def entries() -> list[dict]:
    """Alle Einträge mit Text in der eingestellten Sprache."""
    lang = language()
    return [
        {**{k: v for k, v in e.items() if k not in ("label", "summary", "note")},
         "label": _text(e["label"], lang), "summary": _text(e["summary"], lang), "note": _text(e.get("note"), lang)}
        for e in _load()["plugins"]
    ]


def checked() -> str:
    return str(_load().get("checked", ""))
