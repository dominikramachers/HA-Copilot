"""Suche im offenen MCP-Register (registry.modelcontextprotocol.io) nach Servern, die sich über das Netz erreichen lassen.

Das Register ist eine Sammlung, in die jede Person Einträge stellen kann; die Einträge sind nicht geprüft. Deshalb liefert
dieses Modul nur Angaben zum Anzeigen und Übernehmen. Gespeichert wird erst, wenn die Person bewusst hinzufügt, und auch dann
gelten die üblichen Schutzregeln für Adressen. Es werden nur Server mit festem ``https``-Endpunkt (Streamable HTTP) übernommen.
"""
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from .i18n import tr

BASES = (
    "https://registry.modelcontextprotocol.io/v0.1/servers",
    "https://registry.modelcontextprotocol.io/v0/servers",
)
MAX_BODY = 1024 * 1024
PAGE = 20
TTL = 600
TIMEOUT = 10.0
HTTP_TYPES = ("streamable-http", "streamable_http")
Guard = Callable[[str], Awaitable[str]]


class RegistryError(Exception):
    """Die Suche ist gescheitert; der Text ist für die Person gedacht."""


def _line(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _icon(server: dict) -> str:
    for icon in server.get("icons") or []:
        if not isinstance(icon, dict):
            continue
        src = str(icon.get("src") or "")
        kind = str(icon.get("mimeType") or "").lower()
        if src.startswith("https://") and "svg" not in kind and not src.lower().split("?")[0].endswith(".svg"):
            return src[:500]
    return ""


def parse_item(entry: Any) -> dict[str, Any] | None:
    """Einen Registereintrag in die Angaben zum Anzeigen umsetzen; ``None``, wenn er sich nicht anbinden lässt."""
    if not isinstance(entry, dict):
        return None
    server = entry.get("server") if isinstance(entry.get("server"), dict) else entry
    name = _line(server.get("name"), 200)
    if not name:
        return None
    remote = next(
        (
            r for r in server.get("remotes") or []
            if isinstance(r, dict) and str(r.get("type", "")).lower() in HTTP_TYPES
            and str(r.get("url", "")).startswith("https://") and "{" not in str(r.get("url", ""))
        ),
        None,
    )
    if remote is None:
        return None
    needed = [h for h in remote.get("headers") or [] if isinstance(h, dict) and h.get("name") and (h.get("isRequired") or h.get("isSecret"))]
    auth, header = "none", ""
    if needed:
        header = _line(needed[0].get("name"), 60)
        auth = "bearer" if header.lower() == "authorization" else "header"
    repo = server.get("repository") if isinstance(server.get("repository"), dict) else {}
    website = str(server.get("websiteUrl") or repo.get("url") or "")
    return {
        "id": name,
        "name": _line(server.get("title") or name.rsplit("/", 1)[-1], 40),
        "description": _line(server.get("description"), 300),
        "url": str(remote["url"])[:500],
        "auth": auth,
        "header_name": "" if auth == "bearer" else header,
        "website": website[:300] if website.startswith("https://") else "",
        "icon_url": _icon(server),
    }


def parse_page(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise RegistryError(tr("Das Register hat unerwartet geantwortet."))
    raw = body.get("servers")
    if not isinstance(raw, list):
        raise RegistryError(tr("Das Register hat unerwartet geantwortet."))
    seen: set[str] = set()
    items = []
    for entry in raw:
        item = parse_item(entry)
        if item and item["id"] not in seen:
            seen.add(item["id"])
            items.append(item)
    meta = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    return {"items": items, "next": _line(meta.get("nextCursor") or meta.get("next_cursor"), 300)}


class Registry:
    def __init__(self, guard: Guard, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._guard = guard
        self._transport = transport
        self._cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}

    async def _get(self, client: httpx.AsyncClient, base: str, params: dict[str, str]) -> httpx.Response:
        url = str(httpx.URL(base, params=params))
        await self._guard(url)
        try:
            async with client.stream("GET", url, headers={"Accept": "application/json"}) as response:
                body = b""
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_BODY:
                        raise RegistryError(tr("Die Antwort des Registers ist zu groß."))
                return httpx.Response(response.status_code, content=body, request=response.request)
        except httpx.TimeoutException:
            raise RegistryError(tr("Das Register hat nicht rechtzeitig geantwortet.")) from None
        except httpx.HTTPError:
            raise RegistryError(tr("Keine Verbindung zum Register.")) from None

    async def search(self, query: str, cursor: str = "") -> dict[str, Any]:
        query = _line(query, 80)
        cursor = _line(cursor, 300)
        key = (query.lower(), cursor)
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < TTL:
            return hit[1]
        params = {"limit": str(PAGE), "version": "latest"}
        if query:
            params["search"] = query
        if cursor:
            params["cursor"] = cursor
        result: dict[str, Any] | None = None
        async with httpx.AsyncClient(transport=self._transport, timeout=TIMEOUT, follow_redirects=False) as client:
            for base in BASES:  # die Pfadversion hat sich beim Register schon geändert: zuerst die neue, dann die alte
                response = await self._get(client, base, params)
                if response.status_code == 404:
                    continue
                if response.status_code != 200:
                    raise RegistryError(tr("Das Register hat mit einem Fehler geantwortet ({code}).", code=response.status_code))
                try:
                    result = parse_page(response.json())
                except ValueError:
                    raise RegistryError(tr("Das Register hat unerwartet geantwortet.")) from None
                break
        if result is None:
            raise RegistryError(tr("Das Register ist unter der bekannten Adresse nicht erreichbar."))
        if len(self._cache) > 50:
            self._cache.clear()
        self._cache[key] = (time.monotonic(), result)
        return result
