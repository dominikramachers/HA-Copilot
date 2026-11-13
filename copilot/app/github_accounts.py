"""Persönliche GitHub-Konten: jede Person verbindet ihr eigenes GitHub, das Token des Add-ons wird nur noch als Ersatz genutzt.

Zwei Wege zum Verbinden (ein gemeinsames Token in der Add-on-Konfiguration gibt es seit 0.47.0 nicht mehr):

* **Anmeldung bei GitHub (Device Flow):** Die Person bekommt einen Code, gibt ihn auf ``github.com/login/device`` ein und bestätigt dort.
  Das Add-on fragt in der Zwischenzeit nach, bis GitHub das Token herausgibt. Dafür braucht es nur die öffentliche Client-ID der
  OAuth-App (kein Geheimnis, deshalb fest im Add-on).
* **Token einfügen:** ein selbst erzeugtes Token (Fine-grained oder klassisch), das vor dem Speichern bei GitHub geprüft wird.

Das Token liegt verschlüsselt in der Datenbank (Fernet, Schlüssel wie bei den Konnektoren im Datenordner). Es geht nie an den Browser,
nie in Protokoll, Fehlermeldungen oder „Meine Daten“. Der Code der Anmeldung (``device_code``) bleibt im Arbeitsspeicher des Add-ons.
Eine Einstellung der Konfiguration gibt es dafür nicht mehr; ein persönliches Token reicht
ohnehin nur so weit, wie die Person selbst darf.
"""
from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from typing import Any

import httpx

from .db import Store
from .github_api import GithubApi, GithubError, RepoPolicy
from .i18n import tr
from .vault import Vault

log = logging.getLogger("copilot.github")

CLIENT_ID = "Ov23li4C7WuW7LWkCokC"  # öffentliche Kennung der OAuth-App „HA Copilot“ (Device Flow), kein Geheimnis
SCOPE = "repo"
DEVICE_URL = "https://github.com/login/device/code"
TOKEN_URL = "https://github.com/login/oauth/access_token"
GRANT = "urn:ietf:params:oauth:grant-type:device_code"
DEFAULT_INTERVAL = 5
MAX_PENDING_SECONDS = 900
CHECK_SECONDS = 600  # so lange gilt eine Prüfung des Tokens bei GitHub, bevor die Einstellungen erneut nachfragen
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_]{20,255}$")


class AccountError(Exception):
    """Fehler beim Verbinden; die Meldung ist für die Person bestimmt."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class GithubAccounts:
    def __init__(
        self,
        store: Store,
        vault: Vault,
        *,
        client_id: str = CLIENT_ID,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.store = store
        self.vault = vault
        self.none = GithubApi("")  # ausgeschalteter Zugang für Personen ohne verbundenes Konto
        self.client_id = client_id
        self._transport = transport
        self._clock = clock
        self._cache: dict[str, tuple[str, GithubApi]] = {}  # Person → (verschlüsselter Wert, Zugang)
        self._pending: dict[str, dict[str, Any]] = {}  # Person → laufende Anmeldung (nur Arbeitsspeicher)
        self._expired: set[str] = set()  # Personen, deren Token GitHub abgelehnt hat (nur Arbeitsspeicher)
        self._checked: dict[str, float] = {}  # Person → Zeitpunkt der letzten erfolgreichen Prüfung

    # ------------------------------------------------------------------ Zugang je Person

    def personal(self, profile_id: str) -> GithubApi | None:
        row = self.store.github_account_get(profile_id)
        if not row:
            self._cache.pop(profile_id, None)
            return None
        cached = self._cache.get(profile_id)
        if cached and cached[0] == row["token"]:
            return cached[1]
        token = self.vault.unseal(row["token"])
        if not token:
            log.warning("Das gespeicherte GitHub-Token einer Person ist nicht lesbar (Schlüssel passt nicht mehr)")
            return None
        api = GithubApi(token, transport=self._transport, personal=True, on_unauthorized=lambda: self._expired.add(profile_id))
        self._cache[profile_id] = (row["token"], api)
        return api

    def api_for(self, profile_id: str) -> GithubApi:
        """Das eigene Konto der Person, sonst ein ausgeschalteter Zugang (``enabled`` ist dann falsch)."""
        return self.personal(profile_id) or self.none

    def policy_for(self, profile_id: str) -> RepoPolicy:
        """Keine Freigabeliste: ein persönliches Konto reicht nur so weit, wie die Person selbst darf."""
        return RepoPolicy()

    def source(self, profile_id: str) -> str:
        """``personal`` (Konto verbunden) oder ``none``."""
        return "personal" if self.personal(profile_id) is not None else "none"

    def enabled_for(self, profile_id: str) -> bool:
        return self.source(profile_id) != "none"

    def info(self, profile_id: str) -> dict[str, Any]:
        row = self.store.github_account_get(profile_id) if self.personal(profile_id) is not None else None
        return {
            "source": self.source(profile_id),
            "login": (row or {}).get("login", ""),
            "via": (row or {}).get("via", ""),
            "connected_at": (row or {}).get("connected_at", ""),
            "pending": profile_id in self._pending and self._pending[profile_id]["expires"] > self._clock(),
            "expired": row is not None and profile_id in self._expired,
        }

    async def check(self, profile_id: str) -> None:
        """Fragt bei GitHub nach, ob das Token noch gilt (höchstens alle ``CHECK_SECONDS``); ein Fehler außer „abgelehnt“ ändert nichts."""
        api = self.personal(profile_id)
        if api is None:
            return
        last = self._checked.get(profile_id)
        if last is not None and self._clock() - last < CHECK_SECONDS:
            return
        try:
            await api.request("GET", "/user")
        except GithubError as exc:
            if exc.status == 401:
                self._expired.add(profile_id)
                self._checked[profile_id] = self._clock()
                log.warning("GitHub lehnt das gespeicherte Token einer Person ab (widerrufen oder abgelaufen)")
            return
        self._expired.discard(profile_id)
        self._checked[profile_id] = self._clock()

    # ------------------------------------------------------------------ Verbinden

    async def _post(self, url: str, data: dict[str, str]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=15.0, transport=self._transport, follow_redirects=False) as client:
                response = await client.post(url, data=data, headers={"Accept": "application/json", "User-Agent": "ha-copilot-addon"})
        except httpx.TimeoutException:
            raise AccountError(tr("GitHub antwortet nicht (Zeitüberschreitung)."), 504) from None
        except httpx.HTTPError:
            raise AccountError(tr("GitHub ist nicht erreichbar."), 502) from None
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict) or (response.status_code >= 400 and "error" not in body):
            raise AccountError(tr("GitHub-Fehler {status}.", status=response.status_code), 502)
        return body

    async def device_start(self, profile_id: str) -> dict[str, Any]:
        """Neue Anmeldung bei GitHub starten; liefert Code und Adresse für die Person (der ``device_code`` bleibt hier)."""
        body = await self._post(DEVICE_URL, {"client_id": self.client_id, "scope": SCOPE})
        code, user_code, uri = body.get("device_code"), body.get("user_code"), body.get("verification_uri")
        if body.get("error") or not (code and user_code and uri):
            if body.get("error") == "device_flow_disabled":
                raise AccountError(tr("Bei der GitHub-App ist der Device Flow nicht eingeschaltet. Bitte den Administrator fragen."), 502)
            raise AccountError(tr("GitHub hat die Anmeldung nicht gestartet. Versuche es später erneut oder füge ein Token ein."), 502)
        interval = max(int(body.get("interval") or DEFAULT_INTERVAL), 1)
        expires_in = min(int(body.get("expires_in") or MAX_PENDING_SECONDS), MAX_PENDING_SECONDS)
        now = self._clock()
        self._pending[profile_id] = {"device_code": str(code), "expires": now + expires_in, "interval": interval, "next": now + interval}
        return {"user_code": str(user_code), "verification_uri": str(uri), "expires_in": expires_in, "interval": interval}

    async def device_poll(self, profile_id: str) -> dict[str, Any]:
        """Stand der Anmeldung: ``pending``, ``ok`` (dann ist das Konto verbunden), ``expired``, ``denied`` oder ``none``."""
        state = self._pending.get(profile_id)
        now = self._clock()
        if state is None:
            return {"status": "none"}
        if state["expires"] <= now:
            self._pending.pop(profile_id, None)
            return {"status": "expired"}
        if now < state["next"]:
            return {"status": "pending", "interval": state["interval"]}
        state["next"] = now + state["interval"]
        body = await self._post(TOKEN_URL, {"client_id": self.client_id, "device_code": state["device_code"], "grant_type": GRANT})
        error = body.get("error")
        if error in ("authorization_pending", None) and not body.get("access_token"):
            return {"status": "pending", "interval": state["interval"]}
        if error == "slow_down":
            state["interval"] = int(body.get("interval") or state["interval"] + 5)
            state["next"] = now + state["interval"]
            return {"status": "pending", "interval": state["interval"]}
        if error in ("expired_token", "token_expired"):
            self._pending.pop(profile_id, None)
            return {"status": "expired"}
        if error == "access_denied":
            self._pending.pop(profile_id, None)
            return {"status": "denied"}
        token = str(body.get("access_token") or "")
        if error or not token:
            self._pending.pop(profile_id, None)
            raise AccountError(tr("GitHub hat die Anmeldung abgelehnt. Versuche es erneut oder füge ein Token ein."), 502)
        self._pending.pop(profile_id, None)
        login = await self._store_token(profile_id, token, "device")
        return {"status": "ok", "login": login}

    def device_cancel(self, profile_id: str) -> None:
        self._pending.pop(profile_id, None)

    async def connect_token(self, profile_id: str, token: str) -> str:
        """Ein eingefügtes Token prüfen und speichern; liefert den GitHub-Namen."""
        token = (token or "").strip()
        if not _TOKEN_RE.match(token):
            raise AccountError(tr("Das sieht nicht wie ein GitHub-Token aus. Füge nur das Token ein, ohne Leerzeichen."))
        return await self._store_token(profile_id, token, "token")

    async def _store_token(self, profile_id: str, token: str, via: str) -> str:
        api = GithubApi(token, transport=self._transport, personal=True)
        try:
            user = await api.request("GET", "/user")
        except GithubError as exc:
            if exc.status == 401:
                raise AccountError(tr("GitHub lehnt dieses Token ab (ungültig oder abgelaufen)."), 400) from None
            raise AccountError(str(exc), 502) from None
        login = re.sub(r"[^\w-]", "", str(user.get("login") or ""))[:40] if isinstance(user, dict) else ""
        if not login:
            raise AccountError(tr("GitHub hat das Konto zu diesem Token nicht genannt."), 502)
        self.store.github_account_save(profile_id, self.vault.seal(token), login, via)
        self._cache.pop(profile_id, None)
        self._expired.discard(profile_id)
        self._checked.pop(profile_id, None)
        log.info("GitHub verbunden: Person %s als %s (%s)", profile_id, login, via)
        return login

    def disconnect(self, profile_id: str) -> bool:
        self._pending.pop(profile_id, None)
        self._cache.pop(profile_id, None)
        self._expired.discard(profile_id)
        self._checked.pop(profile_id, None)
        return self.store.github_account_delete(profile_id)
