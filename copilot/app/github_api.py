"""Verbindung zu GitHub (REST-API) und die Freigabeliste für Repositories.

Das Token liegt nur in der Add-on-Konfiguration und geht ausschließlich als Anmelde-Kopfzeile an ``api.github.com``;
es taucht weder in Meldungen noch in Ergebnissen für die KI auf.
"""
from __future__ import annotations

import fnmatch
import logging
import re
from collections.abc import Iterable
from typing import Any

import httpx

log = logging.getLogger("copilot.github")

BASE_URL = "https://api.github.com"
API_VERSION = "2022-11-28"
MAX_RESPONSE_BYTES = 3_000_000
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
PATTERN_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/([A-Za-z0-9_.-]{1,100}|\*)$")
_URL_RE = re.compile(r"^(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?(?:/.*)?$")


class GithubError(Exception):
    """GitHub hat die Anfrage abgelehnt oder war nicht erreichbar (Meldung ist für die KI bestimmt)."""

    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


def parse_repo(value: str) -> str:
    """``owner/repo`` aus Name oder GitHub-Adresse; wirft ``ValueError`` bei ungültiger Angabe."""
    text = str(value or "").strip()
    match = _URL_RE.match(text)
    if match:
        text = f"{match.group(1)}/{match.group(2)}"
    if not REPO_RE.match(text) or text.endswith(".git") or ".." in text:
        raise ValueError("repo muss die Form besitzer/name haben (z. B. doralab/smarthome) oder eine GitHub-Adresse sein.")
    return text


class RepoPolicy:
    """Freigabeliste der Repositories (``besitzer/name`` oder ``besitzer/*``); leer = alles, was das Token erreicht."""

    def __init__(self, patterns: Iterable[str] = ()) -> None:
        self.patterns = tuple(p.strip().lower() for p in patterns if p and p.strip())

    @property
    def restricted(self) -> bool:
        return bool(self.patterns)

    def allows(self, full_name: str) -> bool:
        name = full_name.lower()
        return not self.patterns or any(fnmatch.fnmatchcase(name, p) for p in self.patterns)

    def exact(self) -> list[str]:
        return [p for p in self.patterns if "*" not in p]


class GithubApi:
    def __init__(self, token: str, transport: httpx.AsyncBaseTransport | None = None, timeout: float = 25.0, base_url: str = BASE_URL) -> None:
        self._token = token
        self._transport = transport
        self._timeout = timeout
        self._base = base_url.rstrip("/")

    @property
    def enabled(self) -> bool:
        return bool(self._token)

    def _clean(self, text: str) -> str:
        return text.replace(self._token, "***") if self._token else text

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        accept: str = "application/vnd.github+json",
    ) -> Any:
        """Eine Anfrage; liefert JSON (Liste/Objekt) oder, bei Rohdaten, Text. Wirft :class:`GithubError`."""
        if not self.enabled:
            raise GithubError("GitHub ist nicht eingerichtet (kein Token in der Add-on-Konfiguration).")
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": accept,
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "ha-copilot-addon",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport, follow_redirects=False) as client:
                response = await client.request(method, self._base + path, params=params, json=json, headers=headers)
        except httpx.TimeoutException:
            raise GithubError("GitHub antwortet nicht (Zeitüberschreitung).") from None
        except httpx.HTTPError as exc:
            log.info("GitHub nicht erreichbar: %s", type(exc).__name__)
            raise GithubError("GitHub ist nicht erreichbar.") from None
        if response.status_code >= 400:
            raise self._error(response)
        if response.status_code == 204 or not response.content:
            return None
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise GithubError("Die Antwort von GitHub ist zu groß. Frage enger (Pfad, Seite, weniger Einträge).")
        if "json" in response.headers.get("content-type", "") and "raw" not in accept:
            try:
                return response.json()
            except ValueError:
                pass
        return response.text

    def _error(self, response: httpx.Response) -> GithubError:
        status = response.status_code
        try:
            body = response.json()
            message = str(body.get("message", ""))
            detail = "; ".join(str(e.get("message") or e.get("code") or e)[:120] for e in (body.get("errors") or [])[:3] if isinstance(e, (dict, str)))
        except (ValueError, AttributeError):
            message, detail = response.text[:200], ""
        message = self._clean(message + (f" ({detail})" if detail else ""))[:300]
        if status == 401:
            return GithubError("Das GitHub-Token wurde abgelehnt (ungültig oder abgelaufen). Der Administrator muss es in der Add-on-Konfiguration erneuern.", 401)
        if status in (403, 429) and ("rate limit" in message.lower() or response.headers.get("x-ratelimit-remaining") == "0"):
            return GithubError("Das Anfragelimit von GitHub ist erreicht. Bitte später erneut versuchen.", status)
        if status == 403:
            return GithubError(f"GitHub verweigert das (Rechte des Tokens prüfen): {message}", 403)
        if status == 404:
            return GithubError("Nicht gefunden (oder das Token hat dort keinen Zugriff).", 404)
        if status == 409:
            return GithubError(f"Konflikt: {message}", 409)
        if status == 422:
            return GithubError(f"GitHub lehnt die Angaben ab: {message}", 422)
        return GithubError(f"GitHub-Fehler {status}: {message}", status)
