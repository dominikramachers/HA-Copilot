"""Optionale Anmeldung mit einem Home-Assistant-Konto auf der Domain.

Nur aktiv, wenn in den Add-on-Optionen ``ha_url`` (die von außen erreichbare Adresse von Home Assistant) eingetragen
ist. Es ist der gewöhnliche Autorisierungsablauf von Home Assistant für eigene Webanwendungen:

1. Der Browser geht zu ``<ha_url>/auth/authorize`` – dort meldet sich die Person bei Home Assistant an (auch mit
   Zwei-Faktor); das Passwort sieht dieses Add-on nie.
2. Home Assistant schickt den Browser mit einem einmaligen Code zurück an ``/auth/ha-callback``.
3. Das Add-on tauscht den Code gegen ein Zugriffstoken, fragt damit nur ab, **wer** die Person ist
   (``auth/current_user``), und widerruft das Token sofort wieder. Es bleibt nichts Anmelde-Ähnliches zurück.

Welche Person hereinkommt, entscheidet danach ausschließlich die Registry (Eintrag in der Konfiguration oder
„Alle Home-Assistant-Benutzer“, abzüglich der Ausgeschlossenen).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from .ha_client import HaApi, HaApiError

log = logging.getLogger("ki_chat.ha_login")


class HaLoginError(Exception):
    """Anmeldung mit Home Assistant fehlgeschlagen (Meldung nur fürs Protokoll)."""


@dataclass(frozen=True)
class HaIdentity:
    user_id: str
    name: str


class HaLoginClient:
    def __init__(self, ha_url: str, client_id: str, redirect_uri: str, http: httpx.AsyncClient | None = None) -> None:
        self._base = ha_url.rstrip("/")
        self._client_id = client_id
        self._redirect_uri = redirect_uri
        self._http = http or httpx.AsyncClient(timeout=10.0)

    @property
    def websocket_url(self) -> str:
        return "wss://" + self._base.removeprefix("https://") + "/api/websocket"

    def authorize_url(self, state: str) -> str:
        query = urlencode({"client_id": self._client_id, "redirect_uri": self._redirect_uri, "state": state})
        return f"{self._base}/auth/authorize?{query}"

    async def complete(self, code: str) -> HaIdentity:
        try:
            response = await self._http.post(
                f"{self._base}/auth/token",
                data={"grant_type": "authorization_code", "code": code, "client_id": self._client_id},
            )
        except httpx.HTTPError as exc:
            raise HaLoginError(f"Token-Abruf: {type(exc).__name__}") from None
        if response.status_code != 200:
            raise HaLoginError(f"Token-Abruf abgelehnt (HTTP {response.status_code})")
        try:
            data = response.json()
            access, refresh = str(data["access_token"]), str(data.get("refresh_token") or "")
        except (ValueError, KeyError, TypeError):
            raise HaLoginError("Token-Antwort unbrauchbar") from None
        try:
            user = await self._current_user(access)
        finally:
            await self._revoke(refresh)
        return user

    async def _current_user(self, access_token: str) -> HaIdentity:
        try:
            info = await HaApi(access_token, self.websocket_url).call({"type": "auth/current_user"})
        except HaApiError as exc:
            raise HaLoginError(str(exc)) from None
        if not isinstance(info, dict) or not str(info.get("id") or "").strip():
            raise HaLoginError("Benutzer nicht ermittelbar")
        return HaIdentity(str(info["id"]).lower(), str(info.get("name") or ""))

    async def _revoke(self, refresh_token: str) -> None:
        if not refresh_token:
            return
        try:
            await self._http.post(f"{self._base}/auth/revoke", data={"token": refresh_token, "action": "revoke"})
        except httpx.HTTPError:
            log.warning("Widerruf des Anmelde-Tokens bei Home Assistant fehlgeschlagen")
