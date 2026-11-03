"""Gestaltung der erzeugten Dateien: Farbthemen und Design-Leitfäden für die KI.

* :class:`Theme`: Farben und Schriften, mit denen ``outbox.py`` Word, PowerPoint, Excel und PDF setzt.
  Alle mitgelieferten Themen halten den Kontrast ein (siehe ``tests/test_design.py``): Text gegen Weiß mindestens 12:1, Weiß auf dem Kopfton
  mindestens 9:1, Akzent gegen Weiß mindestens 4:1, Nebentext gegen Weiß und gegen die Fläche mindestens 4,5:1.
* ``design/*.md``: kurze Leitfäden, die die KI mit dem Werkzeug ``design_guide`` abruft, bevor sie Folien, Dokumente,
  Tabellen oder PDFs neu erzeugt. Sie sind eigene Texte und nennen nur, was die Renderer wirklich können.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

GUIDE_DIR = Path(__file__).with_name("design")
HEX = re.compile(r"^#?([0-9A-Fa-f]{6})$")


def rgb(hex6: str) -> tuple[int, int, int]:
    return int(hex6[0:2], 16), int(hex6[2:4], 16), int(hex6[4:6], 16)


def _hex(color: tuple[float, float, float]) -> str:
    return "".join(f"{max(0, min(255, round(c))):02X}" for c in color)


def mix(base: str, other: str, share: float) -> str:
    """``base`` mit dem Anteil ``share`` (0 bis 1) von ``other`` mischen."""
    a, b = rgb(base), rgb(other)
    return _hex(tuple(a[i] * (1 - share) + b[i] * share for i in range(3)))


def luminance(hex6: str) -> float:
    def lin(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(c) for c in rgb(hex6))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """Kontrastverhältnis nach WCAG (1 bis 21)."""
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def darken_until(color: str, background: str, minimum: float) -> str:
    """Farbe schrittweise abdunkeln, bis sie gegen ``background`` mindestens ``minimum`` erreicht."""
    for step in range(0, 21):
        candidate = mix(color, "000000", step * 0.05)
        if contrast(candidate, background) >= minimum:
            return candidate
    return mix(color, "000000", 1.0)


@dataclass(frozen=True)
class Theme:
    key: str
    label: str
    use: str  # wofür das Thema passt (für die KI)
    dark: str  # Überschriften und Text
    head: str  # tiefer Markenton: Titelfolie, Tabellenkopf
    accent: str  # Akzent: Linien, Zwischenüberschriften
    surface: str  # helle Fläche: Zebrazeilen, Kästen
    grey: str  # Nebentext
    heading_font: str = "Calibri"
    body_font: str = "Calibri"

    @property
    def accent_light(self) -> str:
        """Akzent, der auch auf dem dunklen Kopfton sichtbar ist (Linien auf Titelfolien)."""
        return mix(self.accent, "FFFFFF", 0.45)

    @property
    def on_head_muted(self) -> str:
        """Heller Nebentext auf dem Kopfton."""
        return mix(self.head, "FFFFFF", 0.78)


THEMES: dict[str, Theme] = {t.key: t for t in (
    Theme("klar", "Klar", "neutral und sachlich: Berichte, Angebote, Auswertungen, wenn nichts anderes verlangt ist",
          "1F2937", "1F3A5F", "2F6FED", "F3F5F8", "5F6B77"),
    Theme("ozean", "Ozean", "ruhig und technisch: IT, Betrieb, Konzepte, Dokumentation",
          "12263A", "0B3C5D", "1A7595", "E8F2F6", "56666F"),
    Theme("wald", "Wald", "natürlich und gediegen: Nachhaltigkeit, Garten, Haus, Familie",
          "1E2D26", "1F4D3A", "2E7D52", "EDF4EF", "586861", heading_font="Georgia"),
    Theme("terrakotta", "Terrakotta", "warm und einladend: Einladungen, Ratgeber, Kochen, Reisen",
          "2E2420", "5A2E22", "B5472A", "F8EFE9", "76655C", heading_font="Georgia"),
    Theme("schiefer", "Schiefer", "kräftig und nüchtern: Technik, Preise, Zahlen, Präsentationen mit starkem Kontrast",
          "20242A", "2B323B", "B06F00", "F2F3F5", "606871"),
    Theme("beere", "Beere", "kreativ und markant: Ideen, Events, Konzepte, Marketing",
          "2A1E33", "4A2160", "8E3B9E", "F6EFF8", "71647A"),
    Theme("sand", "Sand", "zurückhaltend und edel: Briefe, Verträge, Lebenslauf, Portfolio",
          "3A342B", "4B4338", "8F6228", "F6F1E7", "6F6859", heading_font="Georgia", body_font="Georgia"),
)}
DEFAULT_THEME = THEMES["klar"]


def resolve(theme: str | None = None, accent: str | None = None) -> Theme:
    """Thema wählen (Name ohne Beachtung der Groß-/Kleinschreibung) und optional die Akzentfarbe ersetzen.

    Wirft ``ValueError`` mit einer Meldung für die KI, wenn der Name oder die Farbe nicht stimmt.
    """
    base = DEFAULT_THEME
    if theme not in (None, ""):
        key = str(theme).strip().lower()
        if key not in THEMES:
            raise ValueError(f"Unbekanntes Thema „{theme}“. Verfügbar: " + ", ".join(THEMES) + ".")
        base = THEMES[key]
    if accent not in (None, ""):
        m = HEX.match(str(accent).strip())
        if not m:
            raise ValueError("accent muss eine Farbe wie #C2410C sein (sechsstelliger Hexwert).")
        color = m.group(1).upper()
        accent_text = darken_until(color, "FFFFFF", 4.0)  # als Text und Linie auf Weiß lesbar
        head = darken_until(mix(color, "000000", 0.45), "FFFFFF", 9.0)
        base = Theme(base.key, base.label, base.use, base.dark, head, accent_text, mix(color, "FFFFFF", 0.93), base.grey,
                     base.heading_font, base.body_font)
    return base


def themes_text() -> str:
    lines = ["Verfügbare Themen (Parameter theme von file_create); mit accent kannst du zusätzlich eine eigene Markenfarbe setzen:"]
    for t in THEMES.values():
        font = t.heading_font if t.heading_font == t.body_font else f"{t.heading_font} für Überschriften, {t.body_font} für Text"
        lines.append(f"- {t.key}: {t.label}. {t.use}. Farben: Text #{t.dark}, Kopfton #{t.head}, Akzent #{t.accent}, Fläche #{t.surface}. Schrift: {font}.")
    lines.append("Ohne Angabe gilt klar. Ein Thema für das ganze Dokument; nie mehrere mischen. Passt keines, nimm accent mit der Farbe der Person oder Marke.")
    return "\n".join(lines)


TOPICS = {
    "allgemein": "Grundregeln für jede Datei: Aufbau, Schrift, Farbe, Weißraum, Zahlen, Sprache",
    "folien": "PowerPoint (.pptx): Aufbau, Folienarten, Dichte, Überschriften, Tabellen, Notizen",
    "dokument": "Word (.docx): Briefe, Berichte, Angebote, Anleitungen, Lebenslauf",
    "tabelle": "Excel (.xlsx): Kopfzeile, Formeln, Zahlen, Blätter",
    "pdf": "PDF (.pdf): Seitenaufbau, Länge, Tabellen",
    "html": "HTML (.html): Präsentationen im Browser, Berichte, Seiten: Technik, Schrift, Rhythmus, Bausteine",
    "themen": "Farbthemen und wann welches passt",
}


@lru_cache(maxsize=None)
def _read(name: str) -> str:
    return (GUIDE_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


def guide(topic: str) -> str:
    """Leitfaden zu einem Thema; ``ValueError`` bei unbekanntem Thema."""
    key = str(topic or "").strip().lower()
    if key == "themen":
        return themes_text()
    if key not in TOPICS:
        raise ValueError("Unbekanntes Thema. Verfügbar: " + ", ".join(TOPICS) + ".")
    return _read(key)
