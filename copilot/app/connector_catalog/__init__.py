"""Katalog der Konnektoren zum Entdecken (``catalog.json``) mit Texten in der eingestellten Sprache.

Jeder Eintrag nennt Adresse, Anmeldeart und Herkunft der Angabe (``source``): ``docs`` = in der Dokumentation des Anbieters
gefunden, ``list`` = aus der Liste der Konnektoren von Anthropic, ``known`` = aus allgemeiner Kenntnis, nicht selbst
geprüft. ``kind`` ist ``server`` (Adresse bekannt) oder ``guide`` (Anleitung, weil es keinen fertigen Server gibt).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..i18n import language

CATALOG_PATH = Path(__file__).parent / "catalog.json"
ICON_DIR = Path(__file__).resolve().parent.parent / "static" / "connector-icons"
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


def find(catalog_id: str) -> dict | None:
    """Rohdaten eines Eintrags (Texte noch zweisprachig)."""
    return next((e for e in _load()["connectors"] if e["id"] == catalog_id), None)


def icon_slug(catalog_id: str) -> str:
    """Name des mitgelieferten Logos zu diesem Katalogeintrag, sonst leer."""
    entry = find(catalog_id) if catalog_id else None
    slug = (entry or {}).get("icon") or ""
    return slug if slug and (ICON_DIR / f"{slug}.svg").is_file() else ""


def categories() -> list[dict]:
    lang = language()
    return [{"id": c["id"], "label": _text(c["label"], lang)} for c in _load()["categories"]]


def entries() -> list[dict]:
    """Alle Einträge mit Text in der eingestellten Sprache; ``icon`` nur, wenn die Logo-Datei da ist."""
    lang = language()
    out = []
    for e in _load()["connectors"]:
        item = {k: v for k, v in e.items() if k not in ("summary", "note")}
        item["summary"] = _text(e["summary"], lang)
        item["note"] = _text(e.get("note"), lang)
        item["icon"] = icon_slug(e["id"])
        out.append(item)
    return out


def guides() -> dict[str, dict]:
    """Anleitungen; ``{redirect}`` bleibt als Platzhalter stehen und wird in der Oberfläche eingesetzt."""
    lang = language()
    return {
        key: {"steps": list(g.get(lang) or g["de"]), "warn": _text(g.get("warn"), lang)}
        for key, g in _load()["guides"].items()
    }


def checked() -> str:
    return str(_load().get("checked", ""))


def defaults(catalog_id: str) -> dict[str, Any]:
    """Felder, die beim Anlegen aus dem Katalog übernommen werden, wenn die Eingabe sie nicht nennt."""
    entry = find(catalog_id)
    if entry is None or entry.get("kind") != "server":
        return {}
    lang = language()
    out: dict[str, Any] = {
        "name": entry["label"], "description": _text(entry["summary"], lang), "url": entry["url"], "auth": entry["auth"],
    }
    for key in ("scopes", "authorization_endpoint", "token_endpoint", "auth_params"):
        if entry.get(key):
            out[key] = entry[key]
    return out
