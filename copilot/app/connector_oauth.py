"""OAuth 2.1 für Konnektoren (nach der MCP-Spezifikation): Entdeckung, Registrierung, PKCE, Token holen und erneuern.

* Entdeckung: geschützte Ressource (RFC 9728) → Autorisierungsserver (RFC 8414 / OpenID); ohne Angaben gelten die
  Standardpfade ``/authorize``, ``/token`` und ``/register`` am Servernamen.
* Registrierung: dynamisch (RFC 7591), wenn der Server das anbietet; sonst trägt eine Person Client-ID (und Secret) einer
  selbst angelegten App ein (z. B. Google).
* Immer PKCE (S256) und der Parameter ``resource`` (RFC 8707).

Jede Adresse läuft vor dem Aufruf durch den Adress-Schutz (``netguard``). Die Antworten sind auf 256 kB begrenzt.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

from .i18n import tr

MAX_BODY = 256 * 1024
Guard = Callable[[str], Awaitable[str]]


class OAuthError(Exception):
    """Anmeldung nicht möglich; die Meldung darf der Person gezeigt werden."""


@dataclass
class ServerAuth:
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str = ""
    resource: str = ""
    scopes: tuple[str, ...] = ()
    pkce_s256: bool = True


def new_pkce() -> tuple[str, str]:
    """(Verifier, Challenge)."""
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _origin(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}", parts.path.rstrip("/")


class OAuthHelper:
    def __init__(self, guard: Guard, *, transport: httpx.AsyncBaseTransport | None = None, timeout: float = 20.0) -> None:
        self._guard = guard
        self._transport = transport
        self._timeout = timeout

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self._transport, timeout=self._timeout, follow_redirects=False)

    async def _read(self, client: httpx.AsyncClient, method: str, url: str, **kwargs: Any) -> httpx.Response:
        await self._guard(url)
        try:
            async with client.stream(method, url, **kwargs) as response:
                body = b""
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_BODY:
                        raise OAuthError(tr("Die Antwort des Anmeldeservers ist zu groß."))
                return httpx.Response(response.status_code, headers=response.headers, content=body, request=response.request)
        except httpx.TimeoutException:
            raise OAuthError(tr("Der Anmeldeserver hat nicht rechtzeitig geantwortet.")) from None
        except httpx.HTTPError as exc:
            raise OAuthError(tr("Keine Verbindung zum Anmeldeserver ({kind}).", kind=type(exc).__name__)) from None

    async def _json(self, client: httpx.AsyncClient, url: str) -> dict | None:
        try:
            response = await self._read(client, "GET", url, headers={"Accept": "application/json"})
        except OAuthError:
            return None
        if response.status_code != 200:
            return None
        try:
            data = response.json()
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    # ------------------------------------------------------------------ Entdeckung

    async def discover(self, server_url: str, challenge: str = "") -> ServerAuth:
        origin, path = _origin(server_url)
        candidates: list[str] = []
        found = re.search(r'resource_metadata="([^"]+)"', challenge or "")
        if found:
            candidates.append(found.group(1))
        candidates += [f"{origin}/.well-known/oauth-protected-resource{path}", f"{origin}/.well-known/oauth-protected-resource"]
        issuer = origin
        resource = server_url
        async with self._client() as client:
            for url in candidates:
                data = await self._json(client, url)
                servers = data.get("authorization_servers") if data else None
                if isinstance(servers, list) and servers and isinstance(servers[0], str):
                    issuer = servers[0].rstrip("/")
                    resource = str(data.get("resource") or server_url)
                    break
            as_origin, as_path = _origin(issuer)
            meta = None
            for url in (
                f"{as_origin}/.well-known/oauth-authorization-server{as_path}",
                f"{as_origin}/.well-known/openid-configuration{as_path}",
                f"{issuer}/.well-known/openid-configuration",
            ):
                data = await self._json(client, url)
                if data and data.get("authorization_endpoint") and data.get("token_endpoint"):
                    meta = data
                    break
        if meta is None:  # Standardpfade der MCP-Spezifikation
            return ServerAuth(f"{as_origin}/authorize", f"{as_origin}/token", f"{as_origin}/register", resource)
        methods = meta.get("code_challenge_methods_supported")
        return ServerAuth(
            str(meta["authorization_endpoint"]),
            str(meta["token_endpoint"]),
            str(meta.get("registration_endpoint") or ""),
            resource,
            tuple(str(s) for s in (meta.get("scopes_supported") or []) if isinstance(s, str))[:50],
            pkce_s256=not isinstance(methods, list) or "S256" in methods,
        )

    # ------------------------------------------------------------------ Registrierung

    async def register(self, auth: ServerAuth, redirect_uri: str, name: str) -> dict[str, str]:
        if not auth.registration_endpoint:
            raise OAuthError(tr("Dieser Dienst erlaubt keine automatische Registrierung. Lege dort eine eigene App an und trage Client-ID und Secret ein."))
        payload = {
            "client_name": name[:80] or "HA Copilot",
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        }
        async with self._client() as client:
            response = await self._read(client, "POST", auth.registration_endpoint, json=payload, headers={"Accept": "application/json"})
        if response.status_code not in (200, 201):
            raise OAuthError(tr("Der Dienst hat die automatische Registrierung abgelehnt ({status}). Lege dort eine eigene App an und trage Client-ID und Secret ein.", status=response.status_code))
        try:
            data = response.json()
            client_id = str(data["client_id"])
        except (ValueError, KeyError, TypeError):
            raise OAuthError(tr("Der Dienst hat die Registrierung nicht verständlich beantwortet.")) from None
        return {"client_id": client_id, "client_secret": str(data.get("client_secret") or "")}

    # ------------------------------------------------------------------ Anmelden

    @staticmethod
    def authorization_url(
        auth: ServerAuth, client_id: str, redirect_uri: str, state: str, challenge: str, *, scope: str = "", extra: dict[str, str] | None = None,
    ) -> str:
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        if auth.resource:
            params["resource"] = auth.resource
        if scope:
            params["scope"] = scope
        for key, value in (extra or {}).items():
            if key not in params:
                params[key] = value
        base = auth.authorization_endpoint
        return base + ("&" if "?" in base else "?") + urlencode(params)

    async def _token_request(self, auth: ServerAuth, form: dict[str, str], client_id: str, secret: str) -> dict[str, Any]:
        data = {**form, "client_id": client_id}
        if secret:
            data["client_secret"] = secret
        if auth.resource:
            data["resource"] = auth.resource
        async with self._client() as client:
            response = await self._read(client, "POST", auth.token_endpoint, data=data, headers={"Accept": "application/json"})
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code != 200 or not isinstance(body, dict) or not body.get("access_token"):
            reason = ""
            if isinstance(body, dict):
                reason = str(body.get("error_description") or body.get("error") or "")[:200]
            raise OAuthError(tr("Der Dienst hat die Anmeldung abgelehnt") + (f": {reason}" if reason else f" ({response.status_code})") + ".")
        expires = body.get("expires_in")
        return {
            "access_token": str(body["access_token"]),
            "refresh_token": str(body.get("refresh_token") or ""),
            "expires_at": int(time.time() + float(expires)) if isinstance(expires, (int, float)) else None,
        }

    async def exchange(self, auth: ServerAuth, code: str, verifier: str, redirect_uri: str, client_id: str, secret: str) -> dict[str, Any]:
        return await self._token_request(
            auth, {"grant_type": "authorization_code", "code": code, "code_verifier": verifier, "redirect_uri": redirect_uri}, client_id, secret,
        )

    async def refresh(self, auth: ServerAuth, refresh_token: str, client_id: str, secret: str) -> dict[str, Any]:
        token = await self._token_request(auth, {"grant_type": "refresh_token", "refresh_token": refresh_token}, client_id, secret)
        token["refresh_token"] = token["refresh_token"] or refresh_token  # manche Server liefern keinen neuen
        return token


def pack(data: dict[str, Any]) -> str:
    return json.dumps(data, separators=(",", ":"))


def unpack(text: str | None) -> dict[str, Any]:
    try:
        value = json.loads(text or "")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}
