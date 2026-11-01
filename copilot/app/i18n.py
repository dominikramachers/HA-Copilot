"""Sprache der Oberfläche (Add-on-Option ``language``: ``de`` oder ``en``).

Die deutschen Texte im Quellcode sind zugleich die Schlüssel. Für Englisch gibt es zwei Wörterbücher unter
``locales/``: ``en.json`` (Server: Meldungen, Seiten, Export, Einrichtungsprüfung) und ``en-ui.json`` (Browser-Code
in ``static/*.js``). Der Server kennt beide, der Browser bekommt nur ``en-ui.json`` (über ``branding/lang.js``).

* ``tr("Text {name}", name=…)`` im Server, ``tr("Text {0}", wert)`` im Browser: Platzhalter werden nur ersetzt, wenn sie
  angegeben sind; fehlt die Übersetzung, bleibt der deutsche Text stehen (es gibt keinen Absturz).
* Im Wörterbuch bedeutet ``Einzahl||Mehrzahl``: gewählt wird nach dem Zähler (``n`` im Server, erstes Argument im Browser).
* Nicht übersetzt wird bewusst, was nur die KI, das Protokoll oder die Add-on-Konfiguration betrifft: Werkzeugbeschreibungen,
  Werkzeugantworten, Log-Zeilen und Konfigurationsfehler bleiben deutsch.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

LOCALES_DIR = Path(__file__).parent / "locales"
LANGUAGES = ("de", "en")
DEFAULT_LANGUAGE = "de"
LOCALE_TAGS = {"de": "de-DE", "en": "en-GB"}

_language = DEFAULT_LANGUAGE
_cache: dict[str, dict[str, str]] = {}


def _load(name: str) -> dict[str, str]:
    if name not in _cache:
        path = LOCALES_DIR / f"{name}.json"
        _cache[name] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return _cache[name]


def server_dictionary() -> dict[str, str]:
    return _load("en")


def ui_dictionary() -> dict[str, str]:
    return _load("en-ui")


def set_language(lang: str) -> None:
    global _language
    _language = lang if lang in LANGUAGES else DEFAULT_LANGUAGE


def language() -> str:
    return _language


def locale() -> str:
    return LOCALE_TAGS[_language]


_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _fill(text: str, values: dict) -> str:
    if not values:
        return text
    return _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), text)


def _lookup(text: str) -> str:
    if _language == "de":
        return text
    found = server_dictionary().get(text)
    if found is None:
        found = ui_dictionary().get(text)
    return text if found is None else found


def tr(text: str, **values) -> str:
    """Text in der eingestellten Sprache; ``n`` wählt bei ``Einzahl||Mehrzahl`` die Form."""
    out = _lookup(text)
    if "||" in out:
        one, many = out.split("||", 1)
        out = one if values.get("n") == 1 else many
    return _fill(out, values)


def trn(n: int, one: str, many: str, **values) -> str:
    """Einzahl/Mehrzahl: ``one`` ohne Zähler, ``many`` mit ``{n}``."""
    return tr(one if n == 1 else many, n=n, **values)


# ------------------------------------------------------------------ Seiten (HTML)

_SKIP_BLOCK = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
_TEXT_NODE = re.compile(r">([^<>]+)<")
_ATTR = re.compile(r'(\s(?:title|aria-label|placeholder|alt|data-tip)=)"([^"]*)"')


def _translate_fragment(piece: str) -> str:
    def text(match: re.Match) -> str:
        raw = match.group(1)
        key = " ".join(raw.split())
        if not key or not re.search(r"[A-Za-zÄÖÜäöüß]", key):
            return match.group(0)
        out = _lookup(key)
        if out == key:
            return match.group(0)
        lead = raw[: len(raw) - len(raw.lstrip())]
        trail = raw[len(raw.rstrip()):]
        return ">" + lead + html.escape(out, quote=False) + trail + "<"

    def attr(match: re.Match) -> str:
        key = html.unescape(match.group(2))
        out = _lookup(key)
        return match.group(0) if out == key else f'{match.group(1)}"{html.escape(out, quote=True)}"'

    return _ATTR.sub(attr, _TEXT_NODE.sub(text, piece))


def translate_html(page: str) -> str:
    """Seitentexte (Textknoten und title/aria-label/placeholder/alt/data-tip) in die eingestellte Sprache bringen.
    Platzhalter wie ``__NAME__`` bleiben unberührt; ``<script>`` und ``<style>`` werden übersprungen."""
    page = page.replace('<html lang="de"', f'<html lang="{_language}"', 1)
    if _language == "de":
        return page
    out, pos = [], 0
    for block in _SKIP_BLOCK.finditer(page):
        out.append(_translate_fragment(page[pos:block.start()]))
        out.append(block.group(0))
        pos = block.end()
    out.append(_translate_fragment(page[pos:]))
    return "".join(out)


def ui_script() -> str:
    """Inhalt von ``branding/lang.js``: Sprache und (für Englisch) das Wörterbuch des Browser-Codes."""
    dictionary = ui_dictionary() if _language != "de" else {}
    payload = json.dumps({"lang": _language, "dict": dictionary}, ensure_ascii=False, separators=(",", ":"))
    return f"window.kiI18n={payload};\n"
