"""App-Zugang: Anmeldung und Geräte der mobilen App (iPhone/iPad), nur über den Domain-Zugang.

Die App meldet sich **nie** in einem eingebetteten Fenster an, sondern im Systembrowser, und bekommt am Ende ein
Gerätetoken, das nur im Schlüsselspeicher des Geräts liegt. Entra und Home Assistant laufen unverändert über die
vorhandenen Rückkehradressen (``/auth/callback`` und ``/auth/ha-callback``); die App sieht nie ein Entra- oder HA-Token.

Ablauf (OAuth für native Apps, RFC 8252, mit PKCE):

1. App erzeugt ``verifier``/``challenge`` (S256) und ``state`` und öffnet ``GET /app/v1/login?challenge=…&state=…`` im
   Systembrowser. Der Server merkt sich den Vorgang (Cookie ``__Host-ki_appflow``) und zeigt die normale Anmeldeseite.
2. Nach erfolgreicher Anmeldung leitet der Server auf ``ha-copilot://auth?code=…&state=…`` weiter (Einmal-Code, 60 s).
3. ``POST /app/v1/token`` tauscht Code + ``verifier`` gegen das Gerätetoken (``hcd_…``, 256 Bit, nur der Hash liegt in der
   Datenbank). Ein abgefangener Code ist ohne ``verifier`` wertlos.
4. ``POST /app/v1/ticket`` (Bearer) liefert ein Einmal-Ticket (30 s); ``GET /app/v1/enter?ticket=…`` setzt im WebView das
   kurzlebige Sitzungs-Cookie (7 Tage) und führt in die Oberfläche. Das Gerätetoken geht nie in eine Adresse.
5. ``POST /app/v1/refresh`` erneuert das Gerätetoken (das alte gilt noch 5 Minuten; danach gilt seine Wiederverwendung als
   Diebstahl und sperrt das Gerät). ``POST /app/v1/logout`` entfernt das Gerät.

Alle Zustände der Anmeldung (Vorgänge, Codes, Tickets) liegen nur im Arbeitsspeicher und nur als Hash.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import secrets
import time
from dataclasses import dataclass
from typing import Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from .config import Profile, Settings
from .db import APP_SESSION_DAYS, DEVICE_MAX_DAYS, Store
from .i18n import tr
from .identity import Registry
from .ratelimit import RateLimiter

log = logging.getLogger("copilot.appaccess")

APP_API = 1
APP_SCHEME = "ha-copilot"
FLOW_COOKIE = "__Host-ki_appflow"
FLOW_TTL = 600.0
CODE_TTL = 60.0
TICKET_TTL = 30.0
REFRESH_AFTER_DAYS = 7
MAX_PENDING = 500

_STATE = re.compile(r"^[A-Za-z0-9._~-]{8,128}$")
_CHALLENGE = re.compile(r"^[A-Za-z0-9_-]{43}$")  # S256 über 32 Byte, Base64url ohne Auffüllung
_VERIFIER = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")
_VERSION = re.compile(r"^[0-9A-Za-z._+-]{1,20}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f<>]")
PLATFORMS = ("ios", "android")


def s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def clean_name(value: str, platform: str) -> str:
    """Gerätename aus der App: ohne Steuerzeichen und spitze Klammern, höchstens 40 Zeichen."""
    text = re.sub(r"\s+", " ", _CONTROL.sub("", value or "")).strip()[:40]
    return text or ("iPhone" if platform == "ios" else "Android")


@dataclass(frozen=True)
class Flow:
    challenge: str
    state: str
    device: str
    platform: str
    app_version: str


class Pending:
    """Kleiner Zwischenspeicher im Arbeitsspeicher: Schlüssel nur als Hash, begrenzte Laufzeit, begrenzte Menge."""

    def __init__(self, ttl: float, clock: Callable[[], float] | None = None) -> None:
        self._ttl = ttl
        self._clock = clock or (lambda: time.monotonic())
        self._items: dict[str, tuple[float, object]] = {}

    def _sweep(self) -> None:
        now = self._clock()
        self._items = {k: v for k, v in self._items.items() if now - v[0] < self._ttl}

    def add(self, key: str, value: object) -> bool:
        self._sweep()
        if len(self._items) >= MAX_PENDING:
            return False
        self._items[_digest(key)] = (self._clock(), value)
        return True

    def peek(self, key: str) -> object | None:
        item = self._items.get(_digest(key)) if key else None
        if item is None or self._clock() - item[0] >= self._ttl:
            return None
        return item[1]

    def take(self, key: str) -> object | None:
        """Einmalig herausgeben (auch bei Fehlversuchen des Aufrufers danach weg)."""
        item = self._items.pop(_digest(key), None) if key else None
        if item is None or self._clock() - item[0] >= self._ttl:
            return None
        return item[1]


class AppAccess:
    def __init__(self, settings: Settings, store: Store, registry: Registry, clock: Callable[[], float] | None = None) -> None:
        self.settings = settings
        self.store = store
        self.registry = registry
        self.flows = Pending(FLOW_TTL, clock)
        self.codes = Pending(CODE_TTL, clock)
        self.tickets = Pending(TICKET_TTL, clock)
        self.start_limit = RateLimiter(20, 600)
        self.token_limit = RateLimiter(30, 600)
        self.discovery_limit = RateLimiter(120, 600)
        self.fail_limit = RateLimiter(30, 600)  # nur Fehlversuche, je Gegenstelle
        self.device_limit = RateLimiter(120, 600)  # je Gerät

    # ------------------------------------------------------------------ Server-Kennung

    def server_id(self) -> str:
        """Zufällige, dauerhafte Kennung dieser Instanz (die App erkennt damit, ob hinter der Adresse noch derselbe Server steht)."""
        found = self.store.state_get("app_server_id")
        if found:
            return found
        fresh = secrets.token_hex(16)
        self.store.state_set("app_server_id", fresh)
        return self.store.state_get("app_server_id") or fresh

    # ------------------------------------------------------------------ Vorgang im Systembrowser

    def begin(self, challenge: str, state: str, device: str, platform: str, app_version: str) -> str | None:
        """Neuen Anmeldevorgang merken; gibt die Kennung für das Cookie zurück (None: ungültig oder zu viele offen)."""
        if platform not in PLATFORMS or not _CHALLENGE.match(challenge or "") or not _STATE.match(state or ""):
            return None
        flow = Flow(challenge, state, clean_name(device, platform), platform, app_version if _VERSION.match(app_version or "") else "")
        key = secrets.token_urlsafe(32)
        return key if self.flows.add(key, flow) else None

    def flow_for(self, request: Request) -> Flow | None:
        found = self.flows.peek(request.cookies.get(FLOW_COOKIE, ""))
        return found if isinstance(found, Flow) else None

    def finish(self, request: Request, profile: Profile) -> RedirectResponse | None:
        """Nach erfolgreicher Anmeldung im Systembrowser: Einmal-Code erzeugen und zur App zurückleiten.

        ``None``, wenn die Anmeldung nicht aus der App kam (dann bleibt es beim gewöhnlichen Cookie).
        """
        flow = self.flows.take(request.cookies.get(FLOW_COOKIE, ""))
        if not isinstance(flow, Flow):
            return None
        code = secrets.token_urlsafe(32)
        if not self.codes.add(code, (profile.id, flow)):
            return None
        log.info("App-Anmeldung vorbereitet: Profil %s (%s)", profile.id, flow.platform)
        return RedirectResponse(f"{APP_SCHEME}://auth?code={code}&state={flow.state}", status_code=303)

    # ------------------------------------------------------------------ Gerätetoken

    def redeem(self, code: str, verifier: str) -> tuple[Profile, Flow] | None:
        taken = self.codes.take(code)
        if not isinstance(taken, tuple) or not _VERIFIER.match(verifier or ""):
            return None
        profile_id, flow = taken
        if not hmac.compare_digest(s256(verifier), flow.challenge):
            return None
        profile = self.registry.by_id(profile_id)
        return (profile, flow) if profile is not None else None


class TokenBody(BaseModel):
    code: str = Field(min_length=16, max_length=200)
    verifier: str = Field(min_length=43, max_length=128)


def _refresh_after(rotated_at_iso: str | None = None) -> str:
    import datetime as dt

    base = dt.datetime.fromisoformat(rotated_at_iso) if rotated_at_iso else dt.datetime.now(dt.timezone.utc)
    return (base + dt.timedelta(days=REFRESH_AFTER_DAYS)).isoformat(timespec="seconds")


def install(
    app: FastAPI,
    access: AppAccess,
    *,
    client_ip: Callable[[Request], str],
    set_cookie: Callable[..., None],
    session_cookie: str,
    addon_version: str,
    auth_methods: Callable[[], list[str]],
    app_name: str,
) -> None:
    """Schnittstelle ``/app/v1/*`` in die Domain-App einhängen."""
    settings, store, registry = access.settings, access.store, access.registry
    no_store = {"Cache-Control": "no-store"}

    def reject(status: int, message: str) -> HTTPException:
        return HTTPException(status_code=status, detail=message, headers=no_store)

    @app.get("/app/v1/discovery")
    def discovery(request: Request) -> JSONResponse:
        if not access.discovery_limit.allow(client_ip(request)):
            raise reject(429, tr("Zu viele Versuche"))
        return JSONResponse(
            {
                "api": APP_API,
                "name": app_name,
                "version": addon_version,
                "server_id": access.server_id(),
                "auth": auth_methods(),
            },
            headers=no_store,
        )

    @app.get("/app/v1/login")
    def login(
        request: Request, challenge: str = "", state: str = "", device: str = "", platform: str = "", app_version: str = ""
    ) -> RedirectResponse:
        """Beginn der Anmeldung im Systembrowser: Vorgang merken, dann die gewöhnliche Anmeldeseite zeigen."""
        ip = client_ip(request)
        if not access.start_limit.allow(ip):
            log.warning("App-Anmeldung gedrosselt: %s", ip)
            raise reject(429, tr("Zu viele Versuche"))
        key = access.begin(challenge, state, device, platform, app_version)
        if key is None:
            raise reject(400, tr("Ungültige Anfrage"))
        response = RedirectResponse("/login", status_code=303)
        set_cookie(response, FLOW_COOKIE, key, int(FLOW_TTL))
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/app/v1/token")
    def token(body: TokenBody, request: Request) -> JSONResponse:
        ip = client_ip(request)
        if not access.token_limit.allow(ip):
            log.warning("App-Tokenabruf gedrosselt: %s", ip)
            raise reject(429, tr("Zu viele Versuche"))
        redeemed = access.redeem(body.code, body.verifier)
        if redeemed is None:
            log.warning("App-Tokenabruf abgelehnt (%s)", ip)
            raise reject(400, tr("Die Anmeldung ist abgelaufen oder ungültig. Bitte erneut anmelden."))
        profile, flow = redeemed
        device_id, secret = store.device_create(profile.id, flow.device, flow.platform, flow.app_version, settings.device_days)
        info = store.device_auth(secret) or {}
        log.info("App-Gerät angemeldet: Profil %s, Gerät %s (%s)", profile.id, device_id, flow.platform)
        return JSONResponse(
            {
                "device_id": device_id,
                "device_token": secret,
                "expires_at": info.get("expires_at", ""),
                "refresh_after": _refresh_after(),
                "profile": {"label": profile.label},
            },
            headers=no_store,
        )

    def device_from(request: Request) -> dict:
        ip = client_ip(request)
        scheme, _, value = request.headers.get("authorization", "").partition(" ")
        device = store.device_auth(value.strip()) if scheme.lower() == "bearer" else None
        if device is None:
            if not access.fail_limit.allow(ip):
                raise reject(429, tr("Zu viele Versuche"))
            raise reject(401, tr("Nicht angemeldet"))
        if registry.by_id(device["profile_id"]) is None:  # Profil wurde aus der Konfiguration entfernt
            raise reject(401, tr("Nicht angemeldet"))
        if not access.device_limit.allow(device["id"]):
            raise reject(429, tr("Zu viele Versuche"))
        return device

    @app.post("/app/v1/refresh")
    def refresh(device: dict = Depends(device_from)) -> JSONResponse:
        new, expires = store.device_rotate(device["id"], settings.device_days)
        return JSONResponse(
            {"device_token": new, "expires_at": expires, "refresh_after": _refresh_after()}, headers=no_store
        )

    @app.post("/app/v1/ticket")
    def ticket(device: dict = Depends(device_from)) -> JSONResponse:
        value = secrets.token_urlsafe(32)
        if not access.tickets.add(value, (device["id"], device["profile_id"])):
            raise reject(503, tr("Anmeldung nicht verfügbar"))
        return JSONResponse({"ticket": value, "expires_in": int(TICKET_TTL)}, headers=no_store)

    @app.get("/app/v1/enter")
    def enter(request: Request, ticket: str = "") -> RedirectResponse:
        """Im WebView: Einmal-Ticket einlösen, Sitzungs-Cookie setzen, in die Oberfläche."""
        ip = client_ip(request)
        taken = access.tickets.take(ticket) if len(ticket) <= 100 else None
        profile = registry.by_id(taken[1]) if isinstance(taken, tuple) else None
        if profile is None or not store.device_active(taken[0], profile.id):
            if not access.fail_limit.allow(ip):
                raise reject(429, tr("Zu viele Versuche"))
            return RedirectResponse("/login?e=expired", status_code=303, headers={**no_store, "Referrer-Policy": "no-referrer"})
        session = store.create_session(profile.id, APP_SESSION_DAYS, taken[0])
        response = RedirectResponse("/new", status_code=303, headers={**no_store, "Referrer-Policy": "no-referrer"})
        set_cookie(response, session_cookie, session, APP_SESSION_DAYS * 86400)
        return response

    @app.post("/app/v1/logout", status_code=204)
    def logout(device: dict = Depends(device_from)) -> Response:
        store.device_revoke(device["profile_id"], device["id"])
        log.info("App-Gerät abgemeldet: Gerät %s", device["id"])
        return Response(status_code=204, headers=no_store)


__all__ = ["APP_API", "APP_SCHEME", "AppAccess", "FLOW_COOKIE", "install", "s256", "DEVICE_MAX_DAYS"]
