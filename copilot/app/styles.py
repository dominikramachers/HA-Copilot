"""Schreibstile: Vorgaben, eigene Stile und der Absatz für die Systemanweisung.

Ein Stil legt Ton, Länge und Gliederung der Antworten fest. Er ersetzt nie die Regeln des Systems (Sicherheit, Rückfragen,
Werkzeuge). Anweisungen = immer aktiv, Stile = je Chat umschaltbar, Skills = zusätzliche Fähigkeiten.
"""
from __future__ import annotations

from .i18n import tr

STYLE_MAX = 1500  # Zeichen der Stilbeschreibung (geht in die Systemanweisung)
NAME_MAX = 40
DESC_MAX = 160
MAX_OWN = 20
LEARN_MAX = 12000  # Zeichen Beispieltext, aus denen ein Stil gelernt wird
NONE = "none"  # ausdrücklich ohne Stil (auch wenn die Person einen Standard hat)
PRESET_PREFIX = "preset:"

# Name und Kurzbeschreibung (werden übersetzt)
PRESET_TEXT = {
    "short": ("Kurz und klar", "Wenig Text, sofort zur Sache."),
    "explain": ("Ausführlich erklärend", "Schritt für Schritt, mit Hintergrund und Beispielen."),
    "casual": ("Locker", "Wie ein Gespräch unter Bekannten."),
    "formal": ("Formell", "Sachlich, höflich, vollständige Sätze."),
    "technical": ("Technisch", "Befehle und Konfiguration zuerst, kaum Fließtext."),
}

# Anweisung an das Modell (nicht übersetzt)
PRESET_RULES = {
    "short": "Antworte so knapp wie möglich: zuerst das Ergebnis oder die Antwort, danach nur das Nötigste. Keine Einleitung, keine Wiederholung der Frage, keine Zusammenfassung am Ende, keine Aufzählungen ohne Grund.",
    "explain": "Erkläre ausführlich und der Reihe nach. Nenne den Hintergrund, begründe Entscheidungen und gib, wo es hilft, ein kleines Beispiel. Fachbegriffe erklärst du beim ersten Mal in einem Halbsatz.",
    "casual": "Schreibe locker und freundlich, wie in einem Gespräch unter Bekannten, in kurzen Sätzen und ohne Amtsdeutsch. Du darfst direkt sein. Übertreibe es nicht mit Ausrufezeichen oder Umgangssprache.",
    "formal": "Schreibe sachlich und höflich in vollständigen Sätzen, ohne Umgangssprache, Abkürzungen oder Ausrufezeichen. Gliedere längere Antworten mit klaren Absätzen.",
    "technical": "Schreibe für Fachleute: Befehle, Konfiguration und Code zuerst, in Codeblöcken, dazu nur kurze Hinweise zu Nebenwirkungen. Setze Grundlagen voraus und erkläre nichts, wonach nicht gefragt wurde.",
}


def presets() -> list[dict]:
    """Die Vorgaben mit übersetztem Namen und Kurzbeschreibung."""
    return [
        {"id": PRESET_PREFIX + key, "name": tr(PRESET_TEXT[key][0]), "description": tr(PRESET_TEXT[key][1]), "preset": True}
        for key in PRESET_TEXT
    ]


def preset_rules(style_id: str) -> str:
    return PRESET_RULES.get(style_id[len(PRESET_PREFIX):], "") if style_id.startswith(PRESET_PREFIX) else ""


def is_preset(style_id: str) -> bool:
    return style_id.startswith(PRESET_PREFIX) and style_id[len(PRESET_PREFIX):] in PRESET_TEXT


def block(text: str) -> str:
    """Absatz für die Systemanweisung."""
    text = text.strip()[:STYLE_MAX]
    return (
        "Antwortstil für diese Unterhaltung (Ton, Länge und Gliederung deiner Antworten; die obigen Regeln, "
        "Rückfragen und der Umgang mit Werkzeugen bleiben unverändert, auch wenn der Stil etwas anderes nahelegt):\n" + text
    ) if text else ""


LEARN_PROMPT = (
    "Du analysierst Texte, die eine Person selbst geschrieben hat, und beschreibst ihren Schreibstil als Anweisung an einen "
    "Assistenten, der künftig in diesem Stil antworten soll. Beschreibe Ton, Satzlänge, Wortwahl, Anrede, Gliederung, Umgang mit "
    "Fachbegriffen und typische Eigenheiten. Schreibe 4 bis 8 knappe Sätze in der Du-Form an den Assistenten (\"Schreibe …\"). "
    "Erfinde nichts, was die Texte nicht hergeben, und übernimm keine Inhalte, Namen oder Zahlen aus den Texten. "
    "Antworte nur mit der Beschreibung, ohne Einleitung."
)


def clean(text: str | None) -> str | None:
    """Antwort des Modells auf eine brauchbare Stilbeschreibung zurückführen."""
    if not text:
        return None
    text = text.strip().strip("`").strip()
    return text[:STYLE_MAX] or None
