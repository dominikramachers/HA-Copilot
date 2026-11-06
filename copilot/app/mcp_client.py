"""Kleiner MCP-Client (Streamable HTTP) für die Konnektoren.

Das Add-on spricht selbst mit den MCP-Servern, damit Zugangsdaten, Rückfragen und Protokoll im Add-on bleiben (siehe
``connectors.py``). Gebraucht werden nur ``initialize``, ``tools/list`` und ``tools/call``. Der Server darf mit JSON oder
mit einem Ereignisstrom (SSE) antworten; Anfragen des Servers an den Client (Sampling, Roots …) werden nicht beantwortet.
Der alte SSE-Transport (``/sse``-Adressen) wird nicht unterstützt.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from .i18n import tr

log = logging.getLogger("copilot.mcp")

PROTOCOL_VERSION = "2025-06-18"
MAX_BODY = 4 * 1024 * 1024  # Antworten darüber werden abgebrochen
MAX_PAGES = 10
CLIENT_NAME = "HA Copilot"


class McpError(Exception):
    """Fehler beim Sprechen mit dem Server; die Meldung darf der Person gezeigt werden."""


class McpAuthRequired(McpError):
    """Der Server verlangt eine (neue) Anmeldung (HTTP 401)."""

    def __init__(self, message: str, challenge: str = "") -> None:
        super().__init__(message)
        self.challenge = challenge  # Wert des Headers WWW-Authenticate


def _sse_messages(text: str):
    """Nachrichten (JSON) aus einem SSE-Text."""
    for block in text.replace("\r\n", "\n").split("\n\n"):
        data = "\n".join(line[5:].lstrip(" ") for line in block.split("\n") if line.startswith("data:"))
        if not data:
            continue
        try:
            yield json.loads(data)
        except ValueError:
            continue


class McpClient:
    """Eine Sitzung mit einem Server: ``async with McpClient(url, headers) as client``."""

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 30.0,
        version: str = "0",
    ) -> None:
        self.url = url
        self._headers = dict(headers or {})
        self._timeout = timeout
        self._version = version
        self._session = ""
        self._protocol = PROTOCOL_VERSION
        self._id = 0
        self.server_info: dict[str, Any] = {}
        self._http = httpx.AsyncClient(transport=transport, timeout=timeout, follow_redirects=False)

    async def __aenter__(self) -> "McpClient":
        await self.initialize()
        return self

    async def __aexit__(self, *exc: object) -> None:
        try:
            if self._session:
                await self._http.delete(self.url, headers=self._request_headers())
        except Exception:  # Abmelden ist nur Höflichkeit
            pass
        finally:
            await self._http.aclose()

    def _request_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": self._protocol,
            **self._headers,
        }
        if self._session:
            headers["Mcp-Session-Id"] = self._session
        return headers

    async def _post(self, payload: dict, *, expect: int | None) -> httpx.Response:
        """Senden. ``expect`` = Nummer der Anfrage, auf deren Antwort gewartet wird (``None`` bei Benachrichtigungen)."""
        try:
            async with self._http.stream("POST", self.url, headers=self._request_headers(), content=json.dumps(payload)) as response:
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_BODY:
                        raise McpError(tr("Die Antwort des Servers ist zu groß."))
                    chunks.append(chunk)
                body = b"".join(chunks)
                result = httpx.Response(response.status_code, headers=response.headers, content=body, request=response.request)
        except httpx.TimeoutException:
            raise McpError(tr("Der Server hat nicht rechtzeitig geantwortet.")) from None
        except httpx.HTTPError as exc:
            raise McpError(tr("Keine Verbindung zum Server ({kind}).", kind=type(exc).__name__)) from None
        self._check_status(result)
        return result

    @staticmethod
    def _check_status(response: httpx.Response) -> None:
        status = response.status_code
        if status == 401:
            raise McpAuthRequired(tr("Der Server verlangt eine Anmeldung."), response.headers.get("www-authenticate", ""))
        if status == 403:
            raise McpError(tr("Der Server hat den Zugriff verweigert (403). Vielleicht fehlen Rechte oder die Zustimmung bei der Anmeldung."))
        if status in (301, 302, 303, 307, 308):
            raise McpError(tr("Der Server leitet weiter. Trage die endgültige Adresse ein."))
        if status in (404, 405, 406):
            raise McpError(tr("Unter dieser Adresse gibt es keinen MCP-Server mit Streamable HTTP (Fehler {status}). Adressen mit „/sse“ am Ende (alter Transport) werden nicht unterstützt; oft heißt die neue Adresse „/mcp“.", status=status))
        if status == 429:
            raise McpError(tr("Der Server drosselt die Anfragen (429). Bitte später erneut versuchen."))
        if status >= 400:
            raise McpError(tr("Der Server meldet einen Fehler ({status}).", status=status))

    def _message_for(self, response: httpx.Response, wanted: int) -> dict:
        kind = response.headers.get("content-type", "").split(";")[0].strip().lower()
        text = response.text
        if kind == "text/event-stream":
            candidates = list(_sse_messages(text))
        else:
            try:
                parsed = json.loads(text)
            except ValueError:
                raise McpError(tr("Der Server hat keine gültige Antwort geliefert.")) from None
            candidates = parsed if isinstance(parsed, list) else [parsed]
        for message in candidates:
            if isinstance(message, dict) and message.get("id") == wanted and ("result" in message or "error" in message):
                return message
        raise McpError(tr("Der Server hat nicht auf die Anfrage geantwortet."))

    async def _request(self, method: str, params: dict | None = None) -> Any:
        self._id += 1
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            payload["params"] = params
        response = await self._post(payload, expect=self._id)
        if method == "initialize" and response.headers.get("mcp-session-id"):
            self._session = response.headers["mcp-session-id"]
        message = self._message_for(response, self._id)
        if "error" in message:
            error = message["error"] if isinstance(message["error"], dict) else {}
            raise McpError(str(error.get("message") or tr("Der Server hat die Anfrage abgelehnt."))[:300])
        return message.get("result")

    async def initialize(self) -> None:
        result = await self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": CLIENT_NAME, "version": self._version},
        })
        if not isinstance(result, dict):
            raise McpError(tr("Der Server hat keine gültige Antwort geliefert."))
        self._protocol = str(result.get("protocolVersion") or PROTOCOL_VERSION)
        self.server_info = result.get("serverInfo") if isinstance(result.get("serverInfo"), dict) else {}
        await self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, expect=None)

    async def list_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(MAX_PAGES):
            result = await self._request("tools/list", {"cursor": cursor} if cursor else {})
            if not isinstance(result, dict):
                break
            tools += [t for t in result.get("tools", []) if isinstance(t, dict) and isinstance(t.get("name"), str)]
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await self._request("tools/call", {"name": name, "arguments": arguments})
        return result if isinstance(result, dict) else {}
