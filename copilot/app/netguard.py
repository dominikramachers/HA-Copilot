"""Adress-Schutz für Konnektoren: Wohin darf das Add-on im Auftrag einer Person Anfragen schicken?

Ein eigener Konnektor ist eine frei eingegebene Adresse. Ohne Schutz könnte jede Person darüber das Heimnetz abtasten
oder Dienste im Add-on-Netz ansprechen (SSRF). Deshalb:

* Normalfall: nur ``https`` und nur Adressen, die ins öffentliche Internet führen.
* Mit ``allow_private`` (Stufe ``global``): auch Heimnetz-Adressen und ``http``.
* Nie erlaubt, auch dann nicht: Link-Local-Adressen (u. a. Cloud-Metadaten 169.254.169.254), nicht routbare Adressen und die
  Namen ``supervisor`` und ``hassio`` (Verwaltung des Home-Assistant-Systems).

Der Name wird aufgelöst und jede gefundene Adresse geprüft. Das Auflösen und das spätere Verbinden sind zwei Schritte;
gegen DNS-Rebinding schützt das nur teilweise (siehe DOCS.md).
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urlsplit

from .i18n import tr

BLOCKED_NAMES = frozenset({"supervisor", "hassio"})
# 100::/64 (RFC 6666) ist das „Discard-Präfix“: Pakete dorthin werden verworfen. Heimnetz-DNS (Pi-hole, AdGuard, Router)
# setzt es gern als IPv6-Antwort, damit ein Name nur über IPv4 erreichbar ist. Es führt nirgendwohin, ist also harmlos.
DISCARD_NET = ipaddress.ip_network("100::/64")
Resolver = Callable[..., list]


class UrlRejected(ValueError):
    """Die Adresse ist nicht erlaubt; die Meldung darf der Person gezeigt werden."""


def _is_discard(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%")[0])
    return isinstance(ip, ipaddress.IPv6Address) and ip in DISCARD_NET


def _kind(address: str) -> str:
    """``public``, ``private`` (Heimnetz, Loopback) oder ``never`` (immer abgelehnt)."""
    ip = ipaddress.ip_address(address.split("%")[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped  # ::ffff:169.254.169.254 ist dieselbe Adresse wie 169.254.169.254
    if ip.is_loopback:
        return "private"
    if ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
        return "never"
    return "public" if ip.is_global else "private"  # Heimnetz, Loopback, 100.64.0.0/10 und Ähnliches


def check_url(url: str, *, allow_private: bool = False, resolver: Resolver = socket.getaddrinfo) -> str:
    """Adresse prüfen und bereinigt zurückgeben. Wirft ``UrlRejected``."""
    text = (url or "").strip()
    if not text or len(text) > 500 or any(c in text for c in "\r\n\t \x00"):
        raise UrlRejected(tr("Die Adresse ist leer, zu lang oder enthält Leerzeichen."))
    parts = urlsplit(text)
    if parts.scheme not in ("https", "http"):
        raise UrlRejected(tr("Die Adresse muss mit https:// beginnen."))
    if parts.username or parts.password:
        raise UrlRejected(tr("Zugangsdaten gehören nicht in die Adresse."))
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise UrlRejected(tr("In der Adresse fehlt der Servername."))
    if host in BLOCKED_NAMES:
        raise UrlRejected(tr("Diese Adresse ist nicht erlaubt."))
    try:
        port = parts.port
    except ValueError:
        raise UrlRejected(tr("Der Port in der Adresse ist ungültig.")) from None
    if port is not None and not 1 <= port <= 65535:
        raise UrlRejected(tr("Der Port in der Adresse ist ungültig."))
    try:
        infos = resolver(host, port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        raise UrlRejected(tr("Der Servername „{host}“ lässt sich nicht auflösen.", host=host[:80])) from None
    addresses = {info[4][0] for info in infos}
    if not addresses:
        raise UrlRejected(tr("Der Servername „{host}“ lässt sich nicht auflösen.", host=host[:80]))
    # Discard-Adressen (100::) übergehen, solange der Name noch eine brauchbare Adresse hat; steht nur 100:: da, bleibt es abgelehnt.
    usable = {a for a in addresses if not _is_discard(a)}
    if usable:
        addresses = usable
    kinds = {_kind(a) for a in addresses}
    if "never" in kinds:
        bad = sorted(a for a in addresses if _kind(a) == "never")[0].split("%")[0]
        raise UrlRejected(tr("Der Servername „{host}“ zeigt auf {ip}. Diese Adresse ist nicht erlaubt (Link-Local, Multicast oder reserviert).", host=host[:80], ip=bad))
    if "private" in kinds:
        if not allow_private:
            raise UrlRejected(tr("Adressen im Heimnetz darf nur eine Person mit der Stufe „global“ eintragen."))
    elif parts.scheme != "https" and not allow_private:
        raise UrlRejected(tr("Die Adresse muss mit https:// beginnen."))
    if parts.scheme == "http" and not allow_private:
        raise UrlRejected(tr("Die Adresse muss mit https:// beginnen."))
    return text


async def acheck_url(url: str, *, allow_private: bool = False, resolver: Resolver = socket.getaddrinfo) -> str:
    """Wie ``check_url``, ohne den Ereignisschleife-Thread zu blockieren (DNS kann dauern)."""
    return await asyncio.to_thread(lambda: check_url(url, allow_private=allow_private, resolver=resolver))
