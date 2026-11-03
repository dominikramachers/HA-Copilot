"""Bilder für erzeugte Dateien vorbereiten (Einbetten in Folien, Word und PDF).

Die KI verweist in Markdown mit ``![Beschreibung](dateiname.png)`` auf Bilder dieses Chats (erzeugte Bilder, SVG-Zeichnungen, angehängte Fotos).
Hier werden sie geprüft und in PNG oder JPEG gebracht, die alle Office-Programme und PDF kennen: SVG wird gezeichnet (ohne je etwas aus dem
Netz oder von der Platte nachzuladen), WebP, GIF und BMP werden zu PNG, sehr große Bilder verkleinert.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass

MAX_EDGE = 2400  # längste Seite in Pixel; mehr bringt auf einer Folie oder Seite nichts
MAX_PIXELS = 40_000_000
SVG_WIDTH = 1800


class PictureError(ValueError):
    """Das Bild lässt sich nicht einbetten (Meldung geht an die KI)."""


@dataclass
class Picture:
    data: bytes
    ext: str  # png oder jpg
    width: int
    height: int


def _blocked(url: str, resource_type: str) -> bytes:
    if url.startswith("data:"):
        from cairosvg.url import fetch

        return fetch(url, resource_type)
    raise ValueError("extern")


def is_svg(data: bytes) -> bool:
    head = data[:4000].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    return head.startswith(b"<") and b"<svg" in head


def svg_to_png(data: bytes, width: int = SVG_WIDTH) -> bytes:
    try:
        from cairosvg.surface import PNGSurface
    except (ImportError, OSError):
        raise PictureError("SVG-Bilder lassen sich hier nicht einbetten (Zeichenbibliothek fehlt). Nimm ein PNG- oder JPEG-Bild.") from None
    if re.search(rb"<!(DOCTYPE|ENTITY)", data[:4000], re.I):
        raise PictureError("Das SVG enthält DOCTYPE oder ENTITY und wird nicht gezeichnet.")
    try:
        return PNGSurface.convert(bytestring=data, url_fetcher=_blocked, unsafe=False, output_width=width)
    except PictureError:
        raise
    except Exception as exc:
        text = "verweist auf externe Dateien, die nicht geladen werden (Bilder nur als data:-Adresse einbetten)" if str(exc) == "extern" else f"lässt sich nicht zeichnen ({type(exc).__name__})"
        raise PictureError(f"Das SVG {text}.") from None


def prepare(data: bytes, name: str = "Bild") -> Picture:
    """Bild für Office und PDF vorbereiten. Wirft :class:`PictureError`."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise PictureError("Bilder lassen sich hier nicht einbetten (Pillow fehlt).") from None
    original_png = False
    if is_svg(data):
        data = svg_to_png(data)
        original_png = True
    try:
        img = Image.open(io.BytesIO(data))
        if img.width * img.height > MAX_PIXELS:
            raise PictureError(f"„{name}“ ist zu groß ({img.width}×{img.height} Pixel).")
        fmt = (img.format or "").upper()
        img.load()
    except PictureError:
        raise
    except Exception:
        raise PictureError(f"„{name}“ ist kein lesbares Bild (PNG, JPEG, WebP, GIF oder SVG nötig).") from None
    img = ImageOps.exif_transpose(img)
    width, height = img.size
    if width < 1 or height < 1:
        raise PictureError(f"„{name}“ ist leer.")
    if max(width, height) <= MAX_EDGE and fmt in ("PNG", "JPEG") and not original_png:
        return Picture(data, "png" if fmt == "PNG" else "jpg", width, height)
    if max(width, height) > MAX_EDGE:
        scale = MAX_EDGE / max(width, height)
        img = img.resize((max(1, round(width * scale)), max(1, round(height * scale))), Image.LANCZOS)
    out = io.BytesIO()
    if img.mode in ("RGBA", "LA", "P") or fmt == "PNG" or original_png:
        img.convert("RGBA").save(out, "PNG", optimize=True)
        ext = "png"
    else:
        img.convert("RGB").save(out, "JPEG", quality=88, optimize=True)
        ext = "jpg"
    return Picture(out.getvalue(), ext, img.width, img.height)
