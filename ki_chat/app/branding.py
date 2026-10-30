"""Name, Logo, Texte und Farben der App: Standardwerte, Werte aus der Konfiguration, Dateien im Add-on-Ordner.

Im Ordner ``addon_config`` des Add-ons (``BRANDING_DIR``) dürfen liegen:

* ``logo.png`` (oder .svg/.webp/.jpg): quadratisches Zeichen für die Seitenleiste, Startseite und als Quelle der Symbole
* ``logo-full.png``: größeres Logo (auch mit Schriftzug) für die Anmeldeseite; sonst wird ``logo`` verwendet
* ``icon.png``: Symbol für Browser-Tab und Startbildschirm (mindestens 512 × 512, PNG); sonst ``logo.png``
* ``custom.css``: eigene Stile, werden zuletzt geladen und haben Vorrang vor allem anderen
"""
from __future__ import annotations

import html
import json
import struct
from pathlib import Path

from .config import LOGIN_PLACEHOLDER_DEFAULT, LOGIN_TEXT_DEFAULT, Settings
from .i18n import language, tr
from .ha_client import HaApi
from .theme import build_theme_css

STATIC_DIR = Path(__file__).parent / "static"
MAX_ASSET_BYTES = 2 * 1024 * 1024
MAX_CSS_BYTES = 256 * 1024
IMAGE_TYPES = {".png": "image/png", ".svg": "image/svg+xml", ".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}

DEFAULTS = {"logo": "logo-mark.png", "logo-full": "logo-full.png", "icon": "app-icon-512.png"}


class Branding:
    def __init__(self, directory: Path, settings: Settings, ha: HaApi | None = None) -> None:
        self.directory = Path(directory)
        self.settings = settings
        self.ha = ha

    # ------------------------------------------------------------------ Dateien

    def _custom(self, stem: str, only_png: bool = False) -> Path | None:
        for suffix in IMAGE_TYPES:
            if only_png and suffix != ".png":
                continue
            path = self.directory / f"{stem}{suffix}"
            try:
                if path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= MAX_ASSET_BYTES:
                    return path
            except OSError:
                continue
        return None

    def asset(self, kind: str) -> tuple[Path, str]:
        """Pfad und Medientyp des Bildes; ohne eigene Datei das mitgelieferte."""
        found: Path | None
        if kind == "icon":
            found = self._custom("icon", only_png=True) or self._custom("logo", only_png=True)
        elif kind == "logo-full":
            found = self._custom("logo-full") or self._custom("logo")
        else:
            found = self._custom("logo")
        if found:
            return found, IMAGE_TYPES[found.suffix.lower()]
        return STATIC_DIR / DEFAULTS[kind], "image/png"

    def custom_css(self) -> str:
        path = self.directory / "custom.css"
        try:
            if path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_CSS_BYTES:
                return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
        return ""

    # ------------------------------------------------------------------- Theme

    async def theme_css(self) -> str:
        themes = None
        if self.settings.follow_ha_theme and self.ha is not None and self.ha.enabled:
            themes = await self.ha.themes()
        return build_theme_css(themes, self.settings)

    # -------------------------------------------------------------------- Seiten

    def render(self, page: str, version: str, embed: str = "") -> str:
        s = self.settings
        values = {
            "__NAME__": s.app_name,
            "__LOGIN_TEXT__": tr(LOGIN_TEXT_DEFAULT) if s.login_text == LOGIN_TEXT_DEFAULT else s.login_text,
            "__PLACEHOLDER__": tr(LOGIN_PLACEHOLDER_DEFAULT) if s.login_placeholder == LOGIN_PLACEHOLDER_DEFAULT else s.login_placeholder,
            "__FOLLOW__": "true" if s.follow_ha_theme else "false",
            "__TILE__": "true" if s.logo_tile else "false",
            "__ENTRA__": "true" if s.entra_enabled else "false",
            "__HALOGIN__": "true" if s.ha_login_enabled else "false",
            "__EMBED__": embed,
        }
        for token, value in values.items():
            page = page.replace(token, html.escape(value, quote=True))
        return page.replace("__V__", version)

    def manifest(self) -> dict:
        path, _ = self.asset("icon")
        size = _png_size(path) or 512
        return {
            "name": self.settings.app_name,
            "short_name": self.settings.app_name[:12],
            "lang": language(),
            "start_url": "/new",
            "scope": "/",
            "display": "standalone",
            "background_color": "#0A1120",
            "theme_color": "#0A1120",
            "icons": [{"src": "icon", "sizes": f"{size}x{size}", "type": "image/png", "purpose": "any"}],
        }

    def manifest_json(self) -> str:
        return json.dumps(self.manifest(), ensure_ascii=False)


def _png_size(path: Path) -> int | None:
    try:
        with path.open("rb") as fh:
            head = fh.read(24)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            width, height = struct.unpack(">II", head[16:24])
            return min(width, height)
    except OSError:
        pass
    return None
