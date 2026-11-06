"""Logos für Konnektoren: prüfen, von einer Adresse holen, als Bild ausliefern.

Erlaubt sind nur Rasterbilder (PNG, JPEG, GIF, WebP), erkannt an den ersten Bytes und nicht an Dateiendung oder Antwort-Kopf.
SVG ist bewusst ausgeschlossen: Es kann Skripte enthalten. Die mitgelieferten Marken-Logos (``static/connector-icons``) sind
eigene, geprüfte Dateien und laufen nicht durch diesen Weg.

Holen einer Adresse: nur ``https``, öffentlich erreichbar (``netguard``, auch für jede Weiterleitung), höchstens 128 kB.
"""
from __future__ import annotations

import base64
import binascii
from collections.abc import Awaitable, Callable
from urllib.parse import urljoin

import httpx

from .i18n import tr

MAX_ICON_BYTES = 128 * 1024
MAX_REDIRECTS = 3
TIMEOUT = 8.0
Guard = Callable[[str], Awaitable[str]]


class IconError(ValueError):
    """Das Logo ist unbrauchbar; der Text ist für die Person gedacht."""


def sniff(data: bytes) -> str | None:
    """Bildart an den ersten Bytes erkennen, sonst ``None``."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def check(data: bytes) -> str:
    """Bildart liefern oder ``IconError`` auslösen."""
    if not data:
        raise IconError(tr("Das Logo ist leer."))
    if len(data) > MAX_ICON_BYTES:
        raise IconError(tr("Das Logo ist zu groß (höchstens {kb} kB).", kb=MAX_ICON_BYTES // 1024))
    mime = sniff(data)
    if mime is None:
        raise IconError(tr("Das Logo muss ein PNG-, JPEG-, GIF- oder WebP-Bild sein."))
    return mime


def from_base64(text: str) -> tuple[str, bytes]:
    """Hochgeladenes Bild (Base64, auch als ``data:``-Adresse) prüfen."""
    body = text.split(",", 1)[1] if text.startswith("data:") and "," in text else text
    if len(body) > MAX_ICON_BYTES * 4 // 3 + 16:
        raise IconError(tr("Das Logo ist zu groß (höchstens {kb} kB).", kb=MAX_ICON_BYTES // 1024))
    try:
        data = base64.b64decode(body, validate=True)
    except (binascii.Error, ValueError):
        raise IconError(tr("Das Logo konnte nicht gelesen werden.")) from None
    return check(data), data


async def fetch(url: str, guard: Guard, transport: httpx.AsyncBaseTransport | None = None) -> tuple[str, bytes]:
    """Logo von einer Adresse holen. ``guard`` prüft jede Adresse (auch Weiterleitungen) und liefert sie zurück."""
    current = url.strip()
    if not current.lower().startswith("https://"):
        raise IconError(tr("Die Adresse des Logos muss mit https:// beginnen."))
    try:
        async with httpx.AsyncClient(transport=transport, timeout=TIMEOUT, follow_redirects=False) as client:
            for _ in range(MAX_REDIRECTS + 1):
                try:
                    current = await guard(current)
                except ValueError as exc:  # UrlRejected ist ein ValueError
                    raise IconError(str(exc)) from None
                async with client.stream("GET", current, headers={"Accept": "image/*"}) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        target = response.headers.get("location", "")
                        if not target:
                            raise IconError(tr("Das Logo konnte nicht geholt werden."))
                        current = urljoin(current, target)
                        if not current.lower().startswith("https://"):
                            raise IconError(tr("Die Adresse des Logos muss mit https:// beginnen."))
                        continue
                    if response.status_code != 200:
                        raise IconError(tr("Das Logo konnte nicht geholt werden (Antwort {code}).", code=response.status_code))
                    body = b""
                    async for chunk in response.aiter_bytes():
                        body += chunk
                        if len(body) > MAX_ICON_BYTES:
                            raise IconError(tr("Das Logo ist zu groß (höchstens {kb} kB).", kb=MAX_ICON_BYTES // 1024))
                    return check(body), body
    except httpx.TimeoutException:
        raise IconError(tr("Das Logo wurde nicht rechtzeitig geliefert.")) from None
    except httpx.HTTPError:
        raise IconError(tr("Das Logo konnte nicht geholt werden.")) from None
    raise IconError(tr("Zu viele Weiterleitungen beim Holen des Logos."))
