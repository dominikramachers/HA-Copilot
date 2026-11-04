"""Neuerungen für Nutzer („Das ist neu“) und der Stand „gesehen“ je Person.

Die Texte stehen in ``news.json`` (neueste Version zuerst) und sind für Menschen geschrieben, nicht für Techniker:
kurz, in der Ich-Form der KI, ohne Optionsnamen, Schnittstellen oder Versionsdetails. Technisches gehört ins
CHANGELOG. Pro Version, die für Nutzer etwas ändert, kommt ein Eintrag mit ``de`` und ``en`` dazu; Versionen ohne
sichtbare Änderung bekommen keinen Eintrag und lösen kein Fenster aus.

Gemerkt wird je Person (``app_state``): ``intro:<id>`` = Einführung bestätigt, ``news:<id>`` = zuletzt gesehene Version.
Wer die Einführung zum ersten Mal sieht, bekommt die Neuerungen bis zur aktuellen Version damit als gesehen markiert.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import i18n
from .db import Store

NEWS_FILE = Path(__file__).parent / "news.json"
MAX_ITEMS = 6  # Mehr zeigt das Fenster nach langer Pause nicht auf einmal


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version))


def releases() -> list[dict[str, Any]]:
    """Alle Einträge, neueste Version zuerst."""
    data = json.loads(NEWS_FILE.read_text(encoding="utf-8"))
    return sorted(data, key=lambda release: _version_key(release["version"]), reverse=True)


def latest() -> str:
    found = releases()
    return found[0]["version"] if found else ""


def _items(release: dict[str, Any]) -> list[dict[str, str]]:
    lang = i18n.language()
    return [dict(item.get(lang) or item["de"]) for item in release["items"]]


def unseen(since: str | None) -> list[dict[str, str]]:
    """Neuerungen nach Version ``since`` (ohne Angabe: nur die letzte Version), neueste zuerst."""
    found = releases()
    if since is None:
        found = found[:1]
    else:
        found = [r for r in found if _version_key(r["version"]) > _version_key(since)]
    return [item for release in found for item in _items(release)][:MAX_ITEMS]


def history() -> list[dict[str, Any]]:
    """Alle Versionen mit ihren Neuerungen (für „Das ist neu“ im Menü)."""
    return [{"version": release["version"], "items": _items(release)} for release in releases()]


class Welcome:
    """Was eine Person beim Öffnen sehen soll: Einführung (einmalig) oder Neuerungen seit ihrem letzten Besuch."""

    def __init__(self, store: Store) -> None:
        self.store = store

    def _intro_key(self, profile_id: str) -> str:
        return f"intro:{profile_id}"

    def _news_key(self, profile_id: str) -> str:
        return f"news:{profile_id}"

    def state(self, profile_id: str) -> dict[str, Any]:
        if self.store.state_get(self._intro_key(profile_id)) is None:
            return {"intro": True, "news": []}
        return {"intro": False, "news": unseen(self.store.state_get(self._news_key(profile_id)))}

    def confirm(self, profile_id: str, what: str) -> None:
        if what == "intro":
            self.store.state_set(self._intro_key(profile_id), "1")
        self.store.state_set(self._news_key(profile_id), latest())
