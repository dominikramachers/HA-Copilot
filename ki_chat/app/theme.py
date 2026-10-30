"""Farben der Oberfläche: Home-Assistant-Theme übernehmen und Farben aus der Konfiguration darüberlegen.

Die Oberfläche kennt feste Farbvariablen (``--bg``, ``--panel``, ``--text``, ``--accent`` …), die in ``theme.css``
aus Home-Assistant-Variablen abgeleitet werden (``--primary-color``, ``--card-background-color`` …). Dieses Modul
liefert den serverseitigen Teil: das Standard-Theme von Home Assistant (für die Domain und als Rückfall, wenn die
Seite nicht in Home Assistant eingebettet ist) und die Farbwerte aus der Add-on-Konfiguration.
"""
from __future__ import annotations

import re

from .config import Settings

# Eingebaute Palette (muss zu den Werten in theme.css passen); nur für die Berechnung abgeleiteter Farben.
BUILTIN = {
    "light": {"bg": "#F3F4F6", "text": "#101B2D"},
    "dark": {"bg": "#0D192D", "text": "#F1F5F9"},
}

_NAME = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_VALUE = re.compile(r"^[#a-zA-Z0-9(),.%\s/_+-]{1,200}$")
_MAX_VARIABLES = 400


def _rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def mix(first: str, second: str, share: float) -> str:
    """``share`` Anteil von ``first`` mit dem Rest von ``second`` mischen (beide ``#rrggbb``)."""
    a, b = _rgb(first), _rgb(second)
    return "#" + "".join(f"{round(x * share + y * (1 - share)):02X}" for x, y in zip(a, b))


def on_color(background: str) -> str:
    """Lesbare Schriftfarbe (weiß oder dunkel) auf einer Fläche in dieser Farbe."""
    r, g, b = _rgb(background)
    luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
    return "#0A1120" if luminance > 0.6 else "#FFFFFF"


def _clean(name: object, value: object) -> tuple[str, str] | None:
    if not isinstance(name, str) or not isinstance(value, str):
        return None
    name = name.removeprefix("--").strip()
    value = value.strip()
    if not _NAME.match(name) or not _VALUE.match(value) or "url(" in value.lower():
        return None
    return name, value


def theme_name(themes: dict | None, settings: Settings, mode: str) -> str:
    """Welches Theme gilt für den Modus: das in der Konfiguration genannte, sonst das Standard-Theme von HA."""
    if not themes:
        return ""
    name = settings.theme_name
    if not name:
        name = (themes.get("default_dark_theme") if mode == "dark" else None) or themes.get("default_theme") or ""
    return name if name and name != "default" and name in (themes.get("themes") or {}) else ""


def theme_variables(themes: dict | None, settings: Settings, mode: str) -> dict[str, str]:
    """Variablen des Themes für diesen Modus (Grundwerte, darüber die Werte aus ``modes``)."""
    name = theme_name(themes, settings, mode)
    if not name:
        return {}
    data = (themes or {}).get("themes", {}).get(name)
    if not isinstance(data, dict):
        return {}
    merged: dict[str, object] = {k: v for k, v in data.items() if k != "modes"}
    modes = data.get("modes")
    if isinstance(modes, dict) and isinstance(modes.get(mode), dict):
        merged.update(modes[mode])
    result: dict[str, str] = {}
    for key, value in merged.items():
        cleaned = _clean(key, value)
        if cleaned:
            result[cleaned[0]] = cleaned[1]
        if len(result) >= _MAX_VARIABLES:
            break
    return result


def overrides(settings: Settings, mode: str) -> dict[str, str]:
    """Farben aus der Konfiguration als ``--ov-*`` (haben Vorrang vor dem Theme)."""
    colors = dict(settings.colors)
    out: dict[str, str] = {}
    if "accent" in colors:
        out["ov-accent"] = colors["accent"]
        out["ov-on-accent"] = on_color(colors["accent"])
    bg = colors.get(f"bg_{mode}")
    card = colors.get(f"card_{mode}")
    text = colors.get(f"text_{mode}")
    if bg:
        out["ov-bg"] = bg
    if card:
        out["ov-card"] = card
    if text:
        out["ov-text"] = text
        out["ov-text-2"] = mix(text, bg or BUILTIN[mode]["bg"], 0.62)
    return out


def build_theme_css(themes: dict | None, settings: Settings) -> str:
    """Stylesheet mit Theme-Variablen und Konfigurationsfarben, getrennt für hell und dunkel."""
    blocks = []
    for mode in ("light", "dark"):
        declarations: dict[str, str] = {}
        if settings.follow_ha_theme:
            declarations.update(theme_variables(themes, settings, mode))
        declarations.update(overrides(settings, mode))
        if declarations:
            body = " ".join(f"--{k}: {v};" for k, v in declarations.items())
            blocks.append(f':root[data-theme="{mode}"] {{ {body} }}')
    if not blocks:
        return "/* Keine Theme-Anpassung: eingebaute Farben */\n"
    return "@layer tokens {\n" + "\n".join(blocks) + "\n}\n"
