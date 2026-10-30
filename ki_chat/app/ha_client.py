"""Verbindung zur Home-Assistant-Core-API (WebSocket über den Supervisor-Proxy).

Gebraucht für zwei Dinge: die Benutzerliste (Benutzernamen in der Konfiguration zu IDs auflösen) und die Themes
(``frontend/get_themes``), damit die App dem Standard-Theme von Home Assistant folgen kann.
Voraussetzung ist ``homeassistant_api: true`` in der Add-on-Konfiguration; das Token liefert der Supervisor
in der Umgebungsvariablen ``SUPERVISOR_TOKEN``. Ohne Token (Entwicklung, Tests) ist die Anbindung aus.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx
from websockets.asyncio.client import connect

log = logging.getLogger("ki_chat.ha")

THEME_TTL = 60.0
MAX_MESSAGE = 32 * 1024 * 1024


class HaApiError(Exception):
    """Home Assistant nicht erreichbar oder Befehl abgelehnt (Meldung nur fürs Protokoll)."""


class HaApi:
    def __init__(self, token: str, url: str, timeout: float = 8.0, rest_url: str = "") -> None:
        self._token = token
        self._url = url
        self._rest_url = rest_url.rstrip("/")
        self._timeout = timeout
        self._themes: tuple[float, dict | None] | None = None

    @property
    def enabled(self) -> bool:
        return bool(self._token and self._url)

    async def call(self, command: dict[str, Any], timeout: float | None = None) -> Any:
        """Einen WebSocket-Befehl absetzen und das Ergebnis liefern (``timeout`` überschreibt die Standardzeit, z. B. für große Abfragen)."""
        if not self.enabled:
            raise HaApiError("keine Verbindung zu Home Assistant konfiguriert")
        wait = timeout or self._timeout
        try:
            async with asyncio.timeout(wait):
                async with connect(self._url, max_size=MAX_MESSAGE, open_timeout=wait) as ws:
                    first = json.loads(await ws.recv())
                    if first.get("type") != "auth_required":
                        raise HaApiError(f"unerwartete Antwort: {first.get('type')}")
                    await ws.send(json.dumps({"type": "auth", "access_token": self._token}))
                    auth = json.loads(await ws.recv())
                    if auth.get("type") != "auth_ok":
                        raise HaApiError("Anmeldung bei Home Assistant abgelehnt")
                    await ws.send(json.dumps({"id": 1, **command}))
                    while True:
                        message = json.loads(await ws.recv())
                        if message.get("id") == 1 and message.get("type") == "result":
                            if message.get("success"):
                                return message.get("result")
                            error = message.get("error") or {}
                            raise HaApiError(f"{command.get('type')}: {error.get('code', 'Fehler')}")
        except HaApiError:
            raise
        except (OSError, TimeoutError, ValueError, asyncio.TimeoutError) as exc:
            raise HaApiError(f"{command.get('type')}: {type(exc).__name__}") from None
        except Exception as exc:  # websockets-Fehler (Verbindung geschlossen, ungültige URI …)
            raise HaApiError(f"{command.get('type')}: {type(exc).__name__}") from None

    async def rest(self, method: str, path: str, body: Any = None) -> Any:
        """Eine Anfrage an die REST-Schnittstelle (``/api``) von Home Assistant; liefert JSON oder Text."""
        if not self.enabled or not self._rest_url:
            raise HaApiError("keine Verbindung zu Home Assistant konfiguriert")
        try:
            async with httpx.AsyncClient(timeout=self._timeout + 12) as client:
                response = await client.request(
                    method, self._rest_url + path, json=body if body is not None else None,
                    headers={"Authorization": f"Bearer {self._token}"},
                )
        except httpx.HTTPError as exc:
            raise HaApiError(f"{method} {path}: {type(exc).__name__}") from None
        if response.status_code >= 400:
            raise HaApiError(f"{method} {path}: HTTP {response.status_code} {response.text[:200]}")
        if "json" in response.headers.get("content-type", ""):
            try:
                return response.json()
            except ValueError:
                pass
        return response.text

    async def themes(self) -> dict | None:
        """Themes und Standard-Theme von Home Assistant (kurz zwischengespeichert); ``None``, wenn nicht abrufbar."""
        now = time.monotonic()
        if self._themes and now - self._themes[0] < THEME_TTL:
            return self._themes[1]
        try:
            result = await self.call({"type": "frontend/get_themes"})
            value = result if isinstance(result, dict) else None
        except HaApiError as exc:
            log.info("Themes von Home Assistant nicht abrufbar: %s", exc)
            value = None
        self._themes = (now, value)
        return value

    async def users(self) -> list[dict[str, str]]:
        """Benutzer von Home Assistant: ``[{id, name, username, person}]`` (für die Zuordnung von Benutzernamen zu IDs).

        Quelle ist die Benutzerverwaltung (braucht Administratorrechte des Supervisor-Tokens); wenn sie nicht
        antwortet, dienen die Personen mit verknüpftem Benutzer als Ersatz.
        """
        persons: dict[str, str] = {}
        try:
            data = await self.call({"type": "person/list"})
            for entry in (data or {}).get("storage", []) + (data or {}).get("config", []):
                if isinstance(entry, dict) and entry.get("user_id"):
                    persons[str(entry["user_id"]).lower()] = str(entry.get("name") or "")
        except HaApiError as exc:
            log.info("Personenliste nicht abrufbar: %s", exc)

        users: list[dict[str, str]] = []
        try:
            data = await self.call({"type": "config/auth/list"})
            for entry in data or []:
                if not isinstance(entry, dict) or entry.get("system_generated") or entry.get("is_active") is False:
                    continue
                uid = str(entry.get("id") or "").lower()
                if uid:
                    users.append({"id": uid, "name": str(entry.get("name") or ""), "username": str(entry.get("username") or ""), "person": persons.get(uid, "")})
        except HaApiError as exc:
            log.info("Benutzerliste nicht abrufbar, nutze Personen: %s", exc)
            users = [{"id": uid, "name": name, "username": "", "person": name} for uid, name in persons.items()]
        if not users:
            raise HaApiError("keine Benutzer abrufbar")
        return sorted(users, key=lambda u: (u["person"] or u["name"]).lower())
