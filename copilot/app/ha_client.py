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

log = logging.getLogger("copilot.ha")

THEME_TTL = 60.0
MAX_MESSAGE = 32 * 1024 * 1024
PIPELINE_CHUNK = 4096  # Ton geht in Stücken dieser Größe an die Assist-Pipeline


class HaApiError(Exception):
    """Home Assistant nicht erreichbar oder Befehl abgelehnt (Meldung nur fürs Protokoll)."""


class HaApi:
    def __init__(self, token: str, url: str, timeout: float = 8.0, rest_url: str = "") -> None:
        self._token = token
        self._url = url
        self._rest_url = rest_url.rstrip("/")
        self._timeout = timeout
        self._themes: tuple[float, dict | None] | None = None
        self._engines: tuple[float, dict[str, bool]] | None = None
        self._pictures: dict[str, tuple[bytes, str]] = {}

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

    # ------------------------------------------------------------ Assist-Pipeline (Sprache)

    async def _pipeline_run(self, command: dict[str, Any], audio: bytes | None, wanted: str, timeout: float) -> dict[str, Any]:
        """Einen Lauf der Assist-Pipeline starten und die Daten des Ereignisses ``wanted`` liefern.

        ``audio`` (16-Bit-PCM, mono) wird nach dem Start in Stücken als Binärnachricht gesendet; jedes Stück beginnt mit
        der Kennung, die Home Assistant im Ereignis ``run-start`` nennt, ein leeres Stück beendet die Aufnahme.
        """
        if not self.enabled:
            raise HaApiError("keine Verbindung zu Home Assistant konfiguriert")
        try:
            async with asyncio.timeout(timeout):
                async with connect(self._url, max_size=MAX_MESSAGE, open_timeout=self._timeout) as ws:
                    first = json.loads(await ws.recv())
                    if first.get("type") != "auth_required":
                        raise HaApiError(f"unerwartete Antwort: {first.get('type')}")
                    await ws.send(json.dumps({"type": "auth", "access_token": self._token}))
                    if json.loads(await ws.recv()).get("type") != "auth_ok":
                        raise HaApiError("Anmeldung bei Home Assistant abgelehnt")
                    await ws.send(json.dumps({"id": 1, "type": "assist_pipeline/run", **command}))
                    while True:
                        raw = await ws.recv()
                        if isinstance(raw, bytes):
                            continue
                        message = json.loads(raw)
                        if message.get("id") != 1:
                            continue
                        if message.get("type") == "result" and not message.get("success"):
                            error = message.get("error") or {}
                            raise HaApiError(f"assist_pipeline/run: {error.get('code', 'Fehler')}")
                        if message.get("type") != "event":
                            continue
                        event = message.get("event") or {}
                        kind, data = event.get("type"), event.get("data") or {}
                        if kind == "run-start" and audio is not None:
                            handler = (data.get("runner_data") or {}).get("stt_binary_handler_id")
                            if not isinstance(handler, int) or not 0 <= handler <= 255:
                                raise HaApiError("assist_pipeline/run: keine Kennung für den Ton")
                            prefix = bytes([handler])
                            for start in range(0, len(audio), PIPELINE_CHUNK):
                                await ws.send(prefix + audio[start:start + PIPELINE_CHUNK])
                            await ws.send(prefix)  # Ende der Aufnahme
                        elif kind == wanted:
                            return data
                        elif kind == "error":
                            raise HaApiError(f"assist_pipeline: {data.get('code', 'Fehler')}")
                        elif kind == "run-end":
                            raise HaApiError("assist_pipeline: Lauf ohne Ergebnis beendet")
        except HaApiError:
            raise
        except (OSError, TimeoutError, ValueError, asyncio.TimeoutError) as exc:
            raise HaApiError(f"assist_pipeline/run: {type(exc).__name__}") from None
        except Exception as exc:  # websockets-Fehler
            raise HaApiError(f"assist_pipeline/run: {type(exc).__name__}") from None

    async def pipeline_stt(self, pcm: bytes, sample_rate: int, timeout: float = 40.0) -> str:
        """Ton über die Spracherkennung der bevorzugten Assist-Pipeline in Text wandeln."""
        data = await self._pipeline_run(
            {"start_stage": "stt", "end_stage": "stt", "input": {"sample_rate": sample_rate}}, pcm, "stt-end", timeout
        )
        return str((data.get("stt_output") or {}).get("text") or "").strip()

    async def pipeline_tts(self, text: str, timeout: float = 40.0) -> tuple[bytes, str]:
        """Text über die Sprachausgabe der bevorzugten Assist-Pipeline sprechen lassen: ``(Ton, Medientyp)``."""
        data = await self._pipeline_run(
            {"start_stage": "tts", "end_stage": "tts", "input": {"text": text}}, None, "tts-end", timeout
        )
        output = data.get("tts_output") or {}
        url = str(output.get("url") or "")
        if not url.startswith("/api/") or ".." in url or not self._rest_url:
            raise HaApiError("assist_pipeline: keine Adresse für den Ton")
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(self._rest_url + url[len("/api"):], headers={"Authorization": f"Bearer {self._token}"})
        except httpx.HTTPError as exc:
            raise HaApiError(f"tts_proxy: {type(exc).__name__}") from None
        if response.status_code != 200 or not response.content:
            raise HaApiError(f"tts_proxy: HTTP {response.status_code}")
        return response.content, str(output.get("mime_type") or response.headers.get("content-type") or "audio/mpeg").split(";")[0]

    async def pipeline_engines(self) -> dict[str, bool]:
        """Was die bevorzugte Assist-Pipeline wirklich kann (kurz zwischengespeichert).

        ``stt``/``tts``: Engine ist eingetragen und erreichbar. ``stt_down``/``tts_down``: eingetragen, aber der Dienst
        fehlt oder ist nicht verfügbar (zum Beispiel Add-on „Whisper“ oder „Piper“ gestoppt oder entfernt).
        """
        now = time.monotonic()
        if self._engines and now - self._engines[0] < THEME_TTL:
            return self._engines[1]
        value = {"stt": False, "tts": False, "stt_down": False, "tts_down": False}
        try:
            result = await self.call({"type": "assist_pipeline/pipeline/list"}) or {}
            preferred = result.get("preferred_pipeline")
            for pipeline in result.get("pipelines") or []:
                if pipeline.get("id") == preferred:
                    ids = {"stt": str(pipeline.get("stt_engine") or ""), "tts": str(pipeline.get("tts_engine") or "")}
                    states = await self._engine_states(ids.values())
                    for kind, engine in ids.items():
                        if not engine:
                            continue
                        usable = states.get(engine, "") != "unavailable" and (engine in states or not engine.startswith(("stt.", "tts.")))
                        value[kind], value[kind + "_down"] = usable, not usable
        except HaApiError as exc:
            log.info("Assist-Pipelines nicht abrufbar: %s", exc)
        self._engines = (now, value)
        return value

    async def _engine_states(self, engines) -> dict[str, str]:
        """Zustand der Engine-Entitäten (``stt.…``, ``tts.…``); leer, wenn es keine gibt oder Home Assistant nicht antwortet."""
        wanted = {e for e in engines if e.startswith(("stt.", "tts."))}
        if not wanted:
            return {}
        try:
            states = await self.call({"type": "get_states"}) or []
        except HaApiError as exc:
            log.info("Zustände der Sprach-Engines nicht abrufbar: %s", exc)
            return {engine: "unknown" for engine in wanted}  # ohne Auskunft gilt die Engine als vorhanden
        return {s["entity_id"]: str(s.get("state")) for s in states if isinstance(s, dict) and s.get("entity_id") in wanted}

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

    async def person_picture(self, user_id: str) -> tuple[bytes, str] | None:
        """Profilbild der Person, die in Home Assistant mit diesem Benutzer verknüpft ist: ``(Bild, Medientyp)`` oder ``None``.

        Home Assistant legt hochgeladene Bilder unter ``/api/image/serve/<id>/<Größe>`` ab; nur dieser Pfad wird geholt.
        Der Pfad ändert sich mit jedem neuen Bild, deshalb genügt ein kleiner Zwischenspeicher darauf.
        """
        uid = (user_id or "").lower()
        if not uid or not self.enabled or not self._rest_url:
            return None
        data = await self.call({"type": "person/list"})
        path = ""
        for entry in (data or {}).get("storage", []) + (data or {}).get("config", []) if isinstance(data, dict) else []:
            if isinstance(entry, dict) and str(entry.get("user_id") or "").lower() == uid:
                path = str(entry.get("picture") or "")
                break
        if not path.startswith("/api/image/serve/") or ".." in path or "?" in path:
            return None
        cached = self._pictures.get(path)
        if cached:
            return cached
        try:
            async with httpx.AsyncClient(timeout=self._timeout + 8) as client:
                response = await client.get(self._rest_url + path[len("/api"):], headers={"Authorization": f"Bearer {self._token}"})
        except httpx.HTTPError as exc:
            raise HaApiError(f"person_picture: {type(exc).__name__}") from None
        media = response.headers.get("content-type", "").split(";")[0]
        if response.status_code != 200 or not response.content or not media.startswith("image/") or len(response.content) > 2_000_000:
            return None
        if len(self._pictures) >= 32:
            self._pictures.clear()
        self._pictures[path] = (response.content, media)
        return self._pictures[path]

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
