"""HA Copilot: Profile, Chat-Verwaltung, Streaming-Antworten; Zugang über HA-Ingress und über die Domain (Entra)."""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import html
import ipaddress
import json
import logging
import os
import re
import secrets
import signal
import socket
import sqlite3
import time
from urllib.parse import quote
from datetime import datetime, timezone
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from starlette.datastructures import Headers
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .backend import (
    BackendError,
    ChatBackend,
    ClaudeSdkBackend,
    EchoBackend,
    scrub_environment,
)
from . import attachments as filelib, compact, safety
from . import i18n
from .i18n import tr, trn
from .previews import MAX_CHARS as PREVIEW_MAX_CHARS, PREVIEW_HEADERS, PreviewStore
from .branding import Branding
from .config import (
    BRANDING_DIR,
    DB_PATH,
    HA_REST_URL,
    HA_WEBSOCKET_URL,
    SNAPSHOT_DIR,
    SUPERVISOR_TOKEN,
    Profile,
    Settings,
    load_settings,
)
from .ha_client import HaApi, HaApiError
from . import knowledge as knowlib
from .context_tools import RESERVED_TEXT, ContextToolbox, _RESERVED
from .ha_tools import HaToolbox
from .outbox import FILES_NOTE, MAX_PROFILE_BYTES, OutboxToolbox
from . import exporter
from . import limits as limitlib
from . import schedule as sched
from .scheduler import NOTIFY_MODES, PROMPT_MAX, NAME_MAX, Scheduler, plain_excerpt
from .web_tools import WEB_NOTE, WebToolbox
from .github_api import GithubApi, RepoPolicy
from .github_tools import GITHUB_NOTE, GITHUB_OFF_NO_RIGHT, GITHUB_OFF_NO_TOKEN, GITHUB_OFF_NOTE, GithubToolbox, level_text as github_level_text
from .ha_scan import OverviewScanner
from .db import INSTRUCTIONS_MAX, Store
from .ha_login import HaLoginClient, HaLoginError
from .identity import AccessDenied, Registry, resolve_entra, resolve_ingress
from .oidc import EntraClient, OidcError, PendingLogins, pkce_pair
from .ops import Health
from . import setup_check
from .setup_check import PeerLog, subscription_shared
from .ratelimit import RateLimiter

log = logging.getLogger("ki_chat")

STATIC_DIR = Path(__file__).parent / "static"
INGRESS_PORT = int(os.environ.get("KI_CHAT_PORT", "8099"))
PUBLIC_PORT = 8100

MAX_PARALLEL = 2  # gleichzeitige KI-Anfragen insgesamt (jede startet einen eigenen Prozess)
REQUEST_TIMEOUT = 600  # Sekunden
TOOL_EXTRA_TIMEOUT = 1500  # zusätzlich, wenn die KI Home Assistant benutzen darf (Rückfragen dauern)
APPROVAL_TIMEOUT = 600  # so lange wartet eine Rückfrage auf Antwort, danach gilt sie als abgelehnt
HA_BACKUP_DIR = DB_PATH.parent / "ha-backups"
TITLE_TIMEOUT = 40  # Sekunden für den automatischen Chat-Titel
SUMMARY_TIMEOUT = 240  # Sekunden für das Zusammenfassen eines langen Verlaufs
SWEEP_SECONDS = 1800  # Aufräumen der Zwischendateien des Claude-Programms
DELETE_WORDS = ("LÖSCHEN", "DELETE")  # eines davon muss zur Sicherheit eingetippt werden, bevor alle Chats gelöscht werden (die Oberfläche zeigt das Wort ihrer Sprache)
LONG_ANSWER_SECONDS = 45  # ab dieser Dauer meldet sich die Antwort per Benachrichtigung, wenn niemand zusieht
KEEPALIVE_SECONDS = 15  # Cloudflare trennt Verbindungen, über die ~100 s nichts fließt
SESSION_COOKIE = "__Host-ki_session"
LOGIN_COOKIE = "__Host-ki_login"
DEFAULT_TITLES = frozenset({"Neuer Chat", "New chat"})  # Standardtitel aus jeder Sprache gelten als „noch nicht benannt“


def default_title() -> str:
    return tr("Neuer Chat")


def _asset_version() -> str:
    """Kurzer Hash der Oberflächen-Dateien: ändert sich eine Datei, ändert sich die URL (kein veralteter Cache)."""
    digest = hashlib.sha1()
    for path in sorted(STATIC_DIR.glob("*")):
        if path.is_file():
            digest.update(path.name.encode() + path.read_bytes())
    return digest.hexdigest()[:10]

def denied_page(headers) -> str:
    """Ablehnungsseite. Kommt die Anfrage aus Home Assistant, zeigt sie dem Benutzer seine eigene Kennung,
    damit sie in der Add-on-Konfiguration eingetragen werden kann."""
    own_id = headers.get("x-remote-user-id", "").strip().lower()
    hint = ""
    if _HA_ID.match(own_id):
        name = html.escape(re.sub(r"[^\w.@ -]", "", headers.get("x-remote-user-name", ""))[:64])
        hint = (
            "<p>" + tr("Trage in der Add-on-Konfiguration beim Profil entweder deinen Home-Assistant-Benutzernamen")
            + (f" (<b>{name}</b>)" if name else "")
            + " " + tr("unter <code>ha_user</code> oder diese ID unter <code>ha_user_id</code> ein:") + "</p>"
            f"<p><code style='font-size:1.05rem;word-break:break-all'>{own_id}</code></p>"
        )
    return denied_html() + hint


def denied_html() -> str:
    return (
        f"<!doctype html><html lang='{i18n.language()}'><meta charset=utf-8><meta name=viewport content='width=device-width'>"
        f"<title>{tr('Kein Zugriff')}</title>"
        "<body style='font-family:system-ui;padding:2rem;max-width:32rem;margin:auto'>"
        f"<h1>{tr('Kein Zugriff')}</h1><p>{tr('Dein Benutzerkonto ist für diesen Dienst nicht freigegeben.')}</p>"
    )

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), payment=(), usb=(), serial=(), bluetooth=()",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; frame-ancestors 'self'"
    ),
}


class TitleBody(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class FileBody(BaseModel):
    name: str = Field(max_length=255)
    data: str = Field(max_length=filelib.MAX_BASE64_CHARS)  # Base64; wird nur im Arbeitsspeicher verarbeitet


class PreviewBody(BaseModel):
    html: str = Field(min_length=1, max_length=PREVIEW_MAX_CHARS)


class SendBody(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    effort: Literal["low", "medium", "high"] | None = None
    model: str | None = Field(default=None, max_length=64)  # nur aus der Liste der Konfiguration; sonst gilt das Standard-Modell
    web: bool | None = None  # False = Websuche für diese Nachricht abschalten
    files: list[FileBody] = Field(default_factory=list, max_length=filelib.MAX_FILES)


class CreateChatBody(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    project_id: str | None = Field(default=None, max_length=64)


class PatchChatBody(BaseModel):
    """Teiländerung eines Chats; nicht mitgeschickte Felder bleiben unverändert (``project_id: null`` nimmt den Chat aus dem Projekt)."""

    title: str | None = Field(default=None, min_length=1, max_length=120)
    pinned: bool | None = None
    unread: bool | None = None
    project_id: str | None = Field(default=None, max_length=64)


class ProjectBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class PatchProjectBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    pinned: bool | None = None
    instructions: str | None = Field(default=None, max_length=INSTRUCTIONS_MAX)


class DeleteChatsBody(BaseModel):
    confirm: str = Field(default="", max_length=40)


class ScheduleBody(BaseModel):
    name: str = Field(min_length=1, max_length=NAME_MAX)
    prompt: str = Field(min_length=1, max_length=PROMPT_MAX)
    freq: str = Field(max_length=12)
    at: str = Field(max_length=5)
    days: str = Field(default="", max_length=40)
    enabled: bool = True
    model: str = Field(default="", max_length=64)
    web: bool = True
    notify: str = Field(default="chat", max_length=8)


class PatchScheduleBody(BaseModel):
    """Teiländerung; nicht mitgeschickte Felder bleiben unverändert."""

    name: str | None = Field(default=None, min_length=1, max_length=NAME_MAX)
    prompt: str | None = Field(default=None, min_length=1, max_length=PROMPT_MAX)
    freq: str | None = Field(default=None, max_length=12)
    at: str | None = Field(default=None, max_length=5)
    days: str | None = Field(default=None, max_length=40)
    enabled: bool | None = None
    model: str | None = Field(default=None, max_length=64)
    web: bool | None = None
    notify: str | None = Field(default=None, max_length=8)


SMALL_BODY_BYTES = 128 * 1024  # alle Anfragen außer dem Senden mit Dateien
SEND_PATH = re.compile(r"^/api/chats/[^/]+/send$")
PREVIEW_PATH = re.compile(r"^/api/previews$")
KNOWLEDGE_PATH = re.compile(r"^/api/projects/[^/]+/knowledge$")
KNOWLEDGE_BODY_BYTES = knowlib.MAX_BASE64_CHARS + 64 * 1024
PREVIEW_BODY_BYTES = 700_000


class BodyLimit:
    """Begrenzt die Größe von Anfragetexten, bevor sie gelesen werden (reines ASGI).

    Nur nachweislich angemeldete Anfragen dürfen beim Senden bis zur Dateigrenze groß sein; alles andere bleibt klein.
    Ob jemand angemeldet ist, entscheidet ``signed_in`` (Ingress: Anfrage vom HA-Proxy mit Benutzer-Kennung;
    Domain: gültige Sitzung). Ein bloßer Cookie-Name oder Header genügt nicht.
    """

    def __init__(self, app, signed_in: Callable[[dict], bool] | None = None) -> None:
        self.app = app
        self.signed_in = signed_in or (lambda scope: False)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT", "PATCH", "DELETE"):
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        limit = SMALL_BODY_BYTES
        big = (
            filelib.MAX_BODY_BYTES if SEND_PATH.match(scope["path"])
            else PREVIEW_BODY_BYTES if PREVIEW_PATH.match(scope["path"])
            else KNOWLEDGE_BODY_BYTES if KNOWLEDGE_PATH.match(scope["path"])
            else 0
        )
        if big and self.signed_in(scope):  # nur dann prüfen (Datenbankzugriff), wenn die Grenze davon abhängt
            limit = big
        try:
            declared = int(headers.get(b"content-length", b"0") or 0)
        except ValueError:
            declared = limit + 1
        if declared > limit:
            await JSONResponse({"detail": tr("Die Anfrage ist zu groß.")}, status_code=413)(scope, receive, send)
            return
        seen = 0

        async def limited():
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    return {"type": "http.disconnect"}  # ohne Content-Length: Verbindung als abgebrochen behandeln
            return message

        await self.app(scope, limited, send)


class CollapseSlashes:
    """Fasst mehrfache Schrägstriche im Pfad zusammen.

    Der HA-Ingress ruft das Add-on je nach Konfiguration mit ``//`` oder ``//static/...``
    statt ``/`` auf. Ohne diese Normalisierung findet das Routing dafür keine Route.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] in ("http", "websocket") and "//" in scope["path"]:
            scope = dict(scope)
            scope["path"] = re.sub(r"/{2,}", "/", scope["path"])
            if scope.get("raw_path"):
                scope["raw_path"] = re.sub(rb"/{2,}", b"/", scope["raw_path"])
        await self.app(scope, receive, send)


class SecurityHeaders:
    """Sicherheits-Header für jede Antwort (reines ASGI, damit Streaming nicht gepuffert wird)."""

    def __init__(self, app, headers: dict[str, str] | None = None) -> None:
        self.app = app
        self.headers = headers or SECURITY_HEADERS

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        no_store = scope["path"].startswith(("/api/", "/auth/"))
        revalidate = scope["path"].startswith(("/static/", "/branding/"))

        async def wrapped(message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                present = {k.lower() for k, _ in headers}
                for key, value in self.headers.items():
                    if key.lower().encode() not in present:
                        headers.append((key.lower().encode(), value.encode()))
                if no_store:
                    headers[:] = [(k, v) for k, v in headers if k.lower() != b"cache-control"]
                    headers.append((b"cache-control", b"no-store"))
                elif revalidate:
                    headers[:] = [(k, v) for k, v in headers if k.lower() != b"cache-control"]
                    headers.append((b"cache-control", b"no-cache"))
            await send(message)

        await self.app(scope, receive, wrapped)


PUBLIC_SECURITY_HEADERS = {
    **SECURITY_HEADERS,
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; "
        "base-uri 'self'; form-action 'self'"
    ),
    "Strict-Transport-Security": "max-age=31536000",
}


def _add_security_headers(app: FastAPI, headers: dict[str, str] | None = None) -> None:
    app.add_middleware(SecurityHeaders, headers=headers)


PING = b": ping\n\n"


def _sse(payload: dict) -> bytes:
    return b"data: " + json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n\n"


async def _pump(factory: Callable[[], AsyncIterator[str]], interval: float) -> AsyncIterator[str | None]:
    """Stücke der Quelle durchreichen; ``None`` als Lebenszeichen, wenn länger nichts kommt.

    Die Quelle läuft komplett in einer eigenen Task (SDK und anyio verlangen, dass ein
    Generator in derselben Task beendet wird, in der er gestartet wurde).
    """
    queue: asyncio.Queue = asyncio.Queue()

    async def produce() -> None:
        try:
            async with contextlib.aclosing(factory()) as source:
                async for piece in source:
                    queue.put_nowait(("piece", piece))
            queue.put_nowait(("end", None))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            queue.put_nowait(("error", exc))

    task = asyncio.create_task(produce())
    try:
        while True:
            try:
                kind, value = await asyncio.wait_for(queue.get(), interval)
            except TimeoutError:
                yield None
                continue
            if kind == "piece":
                yield value
            elif kind == "end":
                return
            else:
                raise value
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def _title_from(text: str) -> str:
    lines = (ln.strip() for ln in text.splitlines())
    line = next((ln for ln in lines if ln and not ln.startswith("```")), "")
    line = re.sub(r"[`*#>_]", "", line)
    line = re.sub(r"\s+", " ", line).strip()
    return (line[:50].rstrip() + "…") if len(line) > 50 else (line or default_title())


FINISHED_KEEP_SECONDS = 1800  # fehlgeschlagene Läufe ohne Antwort bleiben so lange abrufbar (Seite war inzwischen neu geladen)


class Run:
    """Eine laufende Antwort. Sie gehört dem Server, nicht der Verbindung des Browsers.

    Der Browser hängt sich nur an (``follow``): Schließt er den Tab, lädt neu oder wechselt den Chat,
    läuft die Antwort weiter, wird gespeichert und der Chat als ungelesen markiert.
    """

    def __init__(self, key: tuple[str, str], text: str, first_exchange: bool) -> None:
        self.key = key
        self.text = text
        self.first_exchange = first_exchange
        self.events: list[dict] = []  # status, compacted, delta in Reihenfolge; Nachzügler spielen sie ab
        self.parts: list[str] = []
        self.finished = False
        self.finished_at = 0.0
        self.error: str | None = None
        self.error_resets_at: int | None = None  # Nutzungslimit erreicht: Unix-Zeit der Rücksetzung
        self.kept = False  # Teilantwort trotz Fehler gespeichert
        self.title: str | None = None
        self.followers = 0
        self.started = time.monotonic()
        self.task: asyncio.Task | None = None
        self.pending: dict[int, asyncio.Future] = {}  # offene Rückfragen (Zulassen/Ablehnen), nach ID
        self.actions: dict[int, dict] = {}  # Aktionen in Home Assistant, nach ID (zuletzt bekannter Stand)
        self.approval_seq = 0
        self.tool_seq = 0
        self._tick = asyncio.Event()

    def push(self, event: dict) -> None:
        self.events.append(event)
        if event["type"] == "delta":
            self.parts.append(event["text"])
        elif event["type"] == "tool":
            self.actions[event["id"]] = {k: event.get(k, "") for k in ("label", "kind", "status", "note")}
            if event.get("file"):
                self.actions[event["id"]]["file"] = event["file"]
            if event.get("link"):
                self.actions[event["id"]]["link"] = event["link"]
        self.wake()

    def next_tool_id(self) -> int:
        self.tool_seq += 1
        return self.tool_seq

    def action_log(self) -> list[dict]:
        """Protokoll für die Datenbank: was lief, ohne noch offene Zustände."""
        done = {"running": "abgebrochen", "waiting": "abgebrochen"}
        return [{**a, "status": done.get(a["status"], a["status"])} for a in self.actions.values()]

    def wake(self) -> None:
        tick, self._tick = self._tick, asyncio.Event()
        tick.set()

    async def wait(self, timeout: float) -> bool:
        tick = self._tick
        try:
            await asyncio.wait_for(tick.wait(), timeout)
        except TimeoutError:
            return False
        return True

    def final_event(self) -> dict:
        if self.error:
            event = {"type": "error", "message": self.error, "kept": self.kept, "text": "" if self.kept else self.text}
            if self.error_resets_at:
                event["resets_at"] = self.error_resets_at
            return event
        return {"type": "done", "title": self.title}


async def follow(run: Run) -> AsyncIterator[bytes]:
    """Den Verlauf einer Antwort als Ereignisstrom ausliefern (von Anfang an, auch für Nachzügler)."""
    run.followers += 1
    seen = 0
    try:
        while True:
            batch = run.events[seen:]
            seen += len(batch)
            text: list[str] = []
            for event in batch:
                if event["type"] == "delta":
                    text.append(event["text"])  # viele kleine Stücke beim Nachholen zu einem zusammenfassen
                    continue
                if text:
                    yield _sse({"type": "delta", "text": "".join(text)})
                    text = []
                yield _sse(event)
            if text:
                yield _sse({"type": "delta", "text": "".join(text)})
            if run.finished and seen >= len(run.events):
                break
            if not batch and not await run.wait(KEEPALIVE_SECONDS):
                yield PING
        yield _sse(run.final_event())
    finally:
        run.followers -= 1


IMAGE_HEADERS = {
    # Eigene Bilder (auch SVG) dürfen nie Skripte der App-Herkunft ausführen, falls jemand die Adresse direkt öffnet.
    "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'",
    "Cache-Control": "no-cache",
}


def register_branding_routes(app: FastAPI, branding: Branding) -> None:
    """Name, Logo, Theme und eigenes CSS; bewusst ohne Anmeldung, die Anmeldeseite braucht sie ebenfalls."""

    def image(kind: str) -> FileResponse:
        path, media = branding.asset(kind)
        return FileResponse(path, media_type=media, headers=IMAGE_HEADERS)

    @app.get("/branding/logo", include_in_schema=False)
    def logo() -> FileResponse:
        return image("logo")

    @app.get("/branding/logo-full", include_in_schema=False)
    def logo_full() -> FileResponse:
        return image("logo-full")

    @app.api_route("/branding/icon", methods=["GET", "HEAD"], include_in_schema=False)
    def icon() -> FileResponse:
        return image("icon")

    @app.api_route("/favicon.ico", methods=["GET", "HEAD"], include_in_schema=False)
    def favicon() -> FileResponse:
        return image("icon")

    @app.get("/branding/theme.css", include_in_schema=False)
    async def theme_css() -> Response:
        css = await branding.theme_css()
        etag = '"' + hashlib.sha1(css.encode()).hexdigest()[:16] + '"'
        return Response(css, media_type="text/css", headers={"ETag": etag, "Cache-Control": "no-cache"})

    @app.get("/branding/custom.css", include_in_schema=False)
    def custom_css() -> Response:
        return Response(branding.custom_css(), media_type="text/css", headers={"Cache-Control": "no-cache"})

    @app.get("/branding/lang.js", include_in_schema=False)
    def lang_js() -> Response:
        """Sprache der Oberfläche und (für Englisch) das Wörterbuch; bewusst ohne Anmeldung wie die übrigen Branding-Dateien."""
        return Response(i18n.ui_script(), media_type="text/javascript", headers={"Cache-Control": "no-cache"})

    @app.get("/branding/manifest.webmanifest", include_in_schema=False)
    def manifest() -> Response:
        return Response(branding.manifest_json(), media_type="application/manifest+json")


def _login_page(branding: Branding, version: str) -> HTMLResponse:
    page = i18n.translate_html((STATIC_DIR / "login.html").read_text(encoding="utf-8"))
    return HTMLResponse(branding.render(page, version), headers={"Cache-Control": "no-store"})


def _index_page(branding: Branding, version: str, embed: str) -> HTMLResponse:
    page = i18n.translate_html((STATIC_DIR / "index.html").read_text(encoding="utf-8"))
    return HTMLResponse(branding.render(page, version, embed), headers={"Cache-Control": "no-store"})


class KnowledgeBody(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    data: str = Field(max_length=knowlib.MAX_BASE64_CHARS)  # Base64; Datei oder ZIP, wird nur im Arbeitsspeicher verarbeitet


class MemoryBody(BaseModel):
    scope: Literal["household", "person"]
    topic: str = Field(min_length=2, max_length=60)
    content: str = Field(min_length=3, max_length=800)


class ApproveBody(BaseModel):
    id: int
    decision: Literal["allow", "deny", "allow_chat"]


def register_chat_routes(
    app: FastAPI,
    settings: Settings,
    store: Store,
    backend: ChatBackend,
    runs: dict,
    current_profile: Callable[..., Profile],
    write_guard: Callable[..., None],
    me_extra: dict,
    health: Health | None = None,
    ha: HaApi | None = None,
    channel: str = "ingress",
    scanner: OverviewScanner | None = None,
    github: GithubApi | None = None,
    scheduler: Scheduler | None = None,
    registry: Registry | None = None,
    public_peers: PeerLog | None = None,
) -> None:
    """Chat-API; für Ingress und Domain identisch, nur die Zuordnung der Person unterscheidet sich."""
    chat_allow: set[tuple[str, str]] = set()  # Chats, in denen Änderungen in Home Assistant dauerhaft erlaubt wurden (nur Arbeitsspeicher)
    github_allow: set[tuple[str, str]] = set()  # dasselbe für GitHub
    limits = limitlib.shared(store)
    model_ids = {m["id"] for m in settings.model_choices()}
    github_policy = RepoPolicy(settings.github_repos)
    title_lock = asyncio.Lock()  # Titel einzeln nacheinander, damit sie keine Antworten ausbremsen
    previews = PreviewStore()  # HTML-Vorschauen, nur im Arbeitsspeicher
    export_limit = RateLimiter(4, 600)  # ZIP-Export nicht im Sekundentakt
    scan_limit = RateLimiter(4, 600)  # „Neu einlesen“ nicht im Sekundentakt

    def ha_level(profile: Profile) -> str:
        """Stufe des Zugriffs auf Home Assistant für diese Person über diesen Zugangsweg."""
        if ha is None or not ha.enabled:
            return "none"
        if channel == "public" and not settings.ha_access_via_domain:
            return "none"
        return profile.ha_access or settings.ha_access_default

    def github_level(profile: Profile) -> str:
        """Stufe des Zugriffs auf GitHub für diese Person (none, read, write)."""
        if github is None or not github.enabled:
            return "none"
        return profile.github_access or settings.github_access_default

    def household_writable(profile: Profile) -> bool:
        """Darf diese Person das Haushaltsgedächtnis ändern? (Einstellung der Konfiguration, unabhängig vom Zugangsweg)"""
        if settings.memory_household_writers == "all":
            return True
        return (profile.ha_access or settings.ha_access_default) == "write"

    def overview_allowed(profile: Profile) -> bool:
        """Der Smarthome-Überblick gilt für alle Personen mit Zugriff auf Home Assistant (mindestens Lesen)."""
        return settings.memory_enabled and scanner is not None and ha_level(profile) != "none"

    def scan_status() -> dict:
        return {**scanner.status(), "auto_days": settings.ha_scan_days}

    @app.get("/api/me")
    def me(profile: Profile = Depends(current_profile)) -> dict:
        return {
            "id": profile.id,
            "label": profile.label,
            "app_name": settings.app_name,
            "default_effort": settings.default_effort,
            "test_mode": settings.backend == "echo",
            "notices": health.notices() if health else [],
            "ha_access": ha_level(profile),
            "github": github_level(profile),
            "web": settings.web_level(profile) == "on",
            "models": settings.model_choices(),
            "default_model": settings.model,
            "limits": limits.current(),
            "schedules": settings.schedules_enabled and scheduler is not None,
            "notify_phone": bool(profile.notify_service),
            "notify_ha": ha is not None and ha.enabled,
            "memory": settings.memory_enabled,
            "overview": overview_allowed(profile),
            "setup": channel == "ingress",
            "setup_open": setup_check.banner(settings) if channel == "ingress" else None,
            **me_extra,
        }

    @app.get("/api/setup")
    async def setup(profile: Profile = Depends(current_profile)) -> dict:
        """Einrichtungsprüfung (nur über Home Assistant; die Konfiguration ändert man dort)."""
        if channel != "ingress":
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        items = setup_check.static_items(
            settings, profile,
            ha_enabled=ha is not None and ha.enabled,
            github_enabled=github is not None and github.enabled,
            ha_level=ha_level(profile),
            github_level=github_level(profile),
            db_problem=health.db_problem if health else None,
            pending_users=registry.pending() if registry else (),
            hostname=socket.gethostname(),
            public_peers=public_peers.recent() if public_peers else (),
        )
        await setup_check.run_live(items, ha if ha is not None and ha.enabled else None, github if github is not None and github.enabled else None, profile)
        return {"items": items, "open": setup_check.open_count(items)}

    @app.get("/api/limits")
    def usage_limits(profile: Profile = Depends(current_profile)) -> list[dict]:
        """Warnungen zum Nutzungslimit des Abos (leer, solange alles in Ordnung ist)."""
        return limits.current()

    @app.get("/api/chats")
    def list_chats(profile: Profile = Depends(current_profile)) -> list[dict]:
        # "running": Antwort wird gerade erzeugt (auch wenn der Browser nicht mehr zuhört)
        return [
            {
                **chat,
                "running": bool((run := runs.get((profile.id, chat["id"]))) and not run.finished),
                "needs_approval": bool(run and not run.finished and run.pending),
            }
            for chat in store.list_chats(profile.id)
        ]

    @app.post("/api/chats", status_code=201, dependencies=[Depends(write_guard)])
    def create_chat(
        body: CreateChatBody | None = None, profile: Profile = Depends(current_profile)
    ) -> dict:
        title = (body.title if body else None) or default_title()
        project_id = body.project_id if body else None
        chat = store.create_chat(profile.id, title, project_id)
        if chat is None:
            raise HTTPException(status_code=404, detail=tr("Projekt nicht gefunden"))
        return chat

    @app.get("/api/projects")
    def list_projects(profile: Profile = Depends(current_profile)) -> list[dict]:
        return store.list_projects(profile.id)

    @app.post("/api/projects", status_code=201, dependencies=[Depends(write_guard)])
    def create_project(body: ProjectBody, profile: Profile = Depends(current_profile)) -> dict:
        name = " ".join(body.name.split())
        if not name:
            raise HTTPException(status_code=422, detail=tr("Name fehlt"))
        return store.create_project(profile.id, name)

    @app.patch("/api/projects/{project_id}", dependencies=[Depends(write_guard)])
    def update_project(
        project_id: str, body: PatchProjectBody, profile: Profile = Depends(current_profile)
    ) -> dict:
        if store.get_project(profile.id, project_id) is None:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        if body.name is not None:
            name = " ".join(body.name.split())
            if not name:
                raise HTTPException(status_code=422, detail=tr("Name fehlt"))
            store.rename_project(profile.id, project_id, name)
        if body.pinned is not None:
            store.set_project_pinned(profile.id, project_id, body.pinned)
        if body.instructions is not None:
            store.set_project_instructions(profile.id, project_id, body.instructions.strip())
        return store.get_project(profile.id, project_id) or {}

    @app.delete("/api/projects/{project_id}", status_code=204, dependencies=[Depends(write_guard)])
    def delete_project(project_id: str, profile: Profile = Depends(current_profile)) -> Response:
        if not store.delete_project(profile.id, project_id):
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        return Response(status_code=204)

    @app.post("/api/previews", status_code=201, dependencies=[Depends(write_guard)])
    def create_preview(body: PreviewBody, profile: Profile = Depends(current_profile)) -> dict:
        return {"id": previews.put(profile.id, body.html)}

    @app.get("/preview/{preview_id}", response_class=HTMLResponse)
    def show_preview(preview_id: str, profile: Profile = Depends(current_profile)) -> HTMLResponse:
        page = previews.get(profile.id, preview_id)
        if page is None:
            raise HTTPException(status_code=404, detail=tr("Die Vorschau ist abgelaufen."))
        return HTMLResponse(page, headers=PREVIEW_HEADERS)

    @app.get("/api/files/{file_id}")
    def download_file(file_id: str, profile: Profile = Depends(current_profile)) -> FileResponse:
        """Eine von der KI erzeugte Datei herunterladen (nur die eigene, solange sie nicht abgelaufen ist)."""
        found = store.outfile_open(profile.id, file_id)
        if found is None:
            raise HTTPException(status_code=404, detail=tr("Die Datei ist abgelaufen oder gehört nicht zu diesem Konto."))
        meta, path = found
        return FileResponse(
            path, media_type=meta["mime"], filename=meta["name"], content_disposition_type="attachment",
            headers={"Content-Security-Policy": "sandbox; default-src 'none'", "Cache-Control": "private, no-store"},
        )

    @app.get("/api/chats/{chat_id}/messages")
    def messages(chat_id: str, profile: Profile = Depends(current_profile)) -> list[dict]:
        result = store.list_messages(profile.id, chat_id)
        if result is None:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        return result

    @app.patch("/api/chats/{chat_id}", dependencies=[Depends(write_guard)])
    def update_chat(
        chat_id: str, body: PatchChatBody, profile: Profile = Depends(current_profile)
    ) -> dict:
        if store.get_chat(profile.id, chat_id) is None:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        if "project_id" in body.model_fields_set and not store.move_chat(
            profile.id, chat_id, body.project_id
        ):
            raise HTTPException(status_code=404, detail=tr("Projekt nicht gefunden"))
        if body.title is not None:
            title = " ".join(body.title.split())
            if not title:
                raise HTTPException(status_code=422, detail=tr("Titel fehlt"))
            store.rename_chat(profile.id, chat_id, title)
        if body.pinned is not None:
            store.set_chat_pinned(profile.id, chat_id, body.pinned)
        if body.unread is not None:
            store.set_chat_unread(profile.id, chat_id, body.unread)
        return store.get_chat(profile.id, chat_id) or {}

    @app.delete("/api/chats/{chat_id}", status_code=204, dependencies=[Depends(write_guard)])
    def delete(chat_id: str, profile: Profile = Depends(current_profile)) -> Response:
        if not store.delete_chat(profile.id, chat_id):
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        chat_allow.discard((profile.id, chat_id))
        github_allow.discard((profile.id, chat_id))
        run = runs.pop((profile.id, chat_id), None)
        if run and not run.finished and run.task:
            run.task.cancel()  # niemand wartet mehr auf diese Antwort
        return Response(status_code=204)

    # ------------------------------------------------- Suche, Export, eigene Daten

    @app.get("/api/search")
    def search_chats(q: str = "", profile: Profile = Depends(current_profile)) -> list[dict]:
        """Volltextsuche in den eigenen Chats (Titel und Nachrichten)."""
        query = " ".join(q.split())
        if len(query) < 2:
            return []
        return store.search_chats(profile.id, query[:100])

    def download(data: bytes | str, name: str, media: str) -> Response:
        return Response(
            data, media_type=media,
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}", "Cache-Control": "private, no-store"},
        )

    @app.get("/api/chats/{chat_id}/export")
    def export_chat(chat_id: str, profile: Profile = Depends(current_profile)) -> Response:
        chat = store.get_chat(profile.id, chat_id)
        found = store.list_messages(profile.id, chat_id) if chat else None
        if chat is None or found is None:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        project = next((p["name"] for p in store.list_projects(profile.id) if p["id"] == chat["project_id"]), "")
        text = exporter.chat_markdown(chat, found, project, settings.app_name)
        return download(text, exporter.safe_name(chat["title"]) + ".md", "text/markdown; charset=utf-8")

    @app.get("/api/export")
    async def export_all(profile: Profile = Depends(current_profile)) -> Response:
        """Alle eigenen Chats, Projekte, das persönliche Gedächtnis und die geplanten Aufgaben als ZIP."""
        if not export_limit.allow(profile.id):
            raise HTTPException(status_code=429, detail=tr("Bitte etwas später noch einmal versuchen."))
        data = await asyncio.to_thread(exporter.build_zip, store, profile.id, settings.app_name)
        stamp = datetime.now().strftime("%Y-%m-%d")
        return download(data, f"{exporter.safe_name(settings.app_name, 'HA Copilot')} Export {stamp}.zip", "application/zip")

    @app.post("/api/data/delete-chats", dependencies=[Depends(write_guard)])
    def delete_all_chats(body: DeleteChatsBody, profile: Profile = Depends(current_profile)) -> dict:
        """Alle eigenen Chats unwiderruflich löschen (Projekte, Gedächtnis und geplante Aufgaben bleiben)."""
        if body.confirm.strip().casefold() not in {word.casefold() for word in DELETE_WORDS}:
            raise HTTPException(status_code=422, detail=tr("Zur Bestätigung „{word}“ eingeben.", word=tr("LÖSCHEN")))
        if any(key[0] == profile.id and not run.finished for key, run in runs.items()):
            raise HTTPException(status_code=409, detail=tr("Es läuft noch eine Antwort. Bitte erst beenden oder abwarten."))
        count = store.delete_all_chats(profile.id)
        for key in [k for k in runs if k[0] == profile.id]:
            runs.pop(key, None)
        for allowed in (chat_allow, github_allow):
            for key in [k for k in allowed if k[0] == profile.id]:
                allowed.discard(key)
        return {"deleted": count}

    # ------------------------------------------------------------ Projektwissen

    @app.get("/api/projects/{project_id}/knowledge")
    def list_knowledge(project_id: str, profile: Profile = Depends(current_profile)) -> dict:
        files = store.list_knowledge(profile.id, project_id)
        if files is None:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        chars = sum(f["size"] for f in files)
        return {"files": files, "chars": chars, "max_files": knowlib.MAX_FILES, "max_chars": knowlib.MAX_PROJECT_CHARS}

    @app.post("/api/projects/{project_id}/knowledge", dependencies=[Depends(write_guard)])
    async def add_knowledge(project_id: str, body: KnowledgeBody, profile: Profile = Depends(current_profile)) -> dict:
        if store.get_project(profile.id, project_id) is None:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        try:
            data = knowlib.decode_upload(body.data)
            body.data = ""
            items, skipped = await asyncio.to_thread(knowlib.expand, body.name, data)
        except knowlib.KnowledgeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        existing = {f["name"].lower(): f["size"] for f in store.list_knowledge(profile.id, project_id) or []}
        count, chars = len(existing), sum(existing.values())
        added: list[str] = []
        for name, text in items:
            old = existing.get(name.lower())
            if old is None and count >= knowlib.MAX_FILES:
                skipped.append({"name": name, "reason": tr("Dateilimit erreicht ({max})", max=knowlib.MAX_FILES)})
                continue
            if chars - (old or 0) + len(text) > knowlib.MAX_PROJECT_CHARS:
                skipped.append({"name": name, "reason": tr("Speichergrenze des Projekts erreicht")})
                continue
            if store.add_knowledge(profile.id, project_id, name, text) is None:
                raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
            if old is None:
                count += 1
            chars += len(text) - (old or 0)
            existing[name.lower()] = len(text)
            added.append(name)
        if not added and not skipped:
            raise HTTPException(status_code=422, detail=tr("Nichts übernommen"))
        return {"added": added, "skipped": skipped[:50]}

    @app.delete("/api/projects/{project_id}/knowledge/{knowledge_id}", status_code=204, dependencies=[Depends(write_guard)])
    def delete_knowledge(project_id: str, knowledge_id: int, profile: Profile = Depends(current_profile)) -> Response:
        if not store.delete_knowledge(profile.id, project_id, knowledge_id):
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        return Response(status_code=204)

    # --------------------------------------------------------------- Gedächtnis

    def memory_enabled_or_404() -> None:
        if not settings.memory_enabled:
            raise HTTPException(status_code=404, detail=tr("Nicht verfügbar"))

    @app.get("/api/memory")
    def get_memory(profile: Profile = Depends(current_profile)) -> dict:
        memory_enabled_or_404()
        names = {p.id: (p.label or p.id) for p in settings.profiles}
        household = [{**m, "by": names.get(m["author"], "")} for m in store.memory_list("household", auto=False)]
        out = {
            "household": household,
            "person": store.memory_list("person", profile.id),
            "household_write": household_writable(profile),
        }
        if overview_allowed(profile):
            out["overview"] = {"status": scan_status(), "entries": store.memory_list("household", auto=True)}
        return out

    @app.get("/api/overview")
    def get_overview(profile: Profile = Depends(current_profile)) -> dict:
        """Stand des Smarthome-Überblicks (für den Hinweis oben und die Fortschrittsanzeige)."""
        if not overview_allowed(profile):
            raise HTTPException(status_code=404, detail=tr("Nicht verfügbar"))
        return {"status": scan_status()}

    @app.post("/api/overview/scan", dependencies=[Depends(write_guard)])
    async def scan_overview(profile: Profile = Depends(current_profile)) -> dict:
        """Den Überblick jetzt neu einlesen (läuft im Hintergrund)."""
        if not overview_allowed(profile):
            raise HTTPException(status_code=404, detail=tr("Nicht verfügbar"))
        if not scanner.running:
            if not scan_limit.allow(profile.id):
                raise HTTPException(status_code=429, detail=tr("Bitte einen Moment warten."))
            scanner.start("manual")
        return {"status": scan_status()}

    @app.post("/api/memory", dependencies=[Depends(write_guard)])
    def save_memory(body: MemoryBody, profile: Profile = Depends(current_profile)) -> dict:
        memory_enabled_or_404()
        if body.scope == "household" and not household_writable(profile):
            raise HTTPException(status_code=403, detail=tr("Das Haushaltsgedächtnis darfst du nicht ändern."))
        topic = " ".join(body.topic.split())
        if len(topic) < 2:
            raise HTTPException(status_code=422, detail=tr("Thema fehlt"))
        if _RESERVED.match(topic):
            raise HTTPException(status_code=422, detail=tr(RESERVED_TEXT))
        return store.memory_save(body.scope, profile.id, topic, body.content.strip(), profile.id)

    @app.delete("/api/memory/{scope}/{memory_id}", status_code=204, dependencies=[Depends(write_guard)])
    def delete_memory(scope: Literal["household", "person"], memory_id: int, profile: Profile = Depends(current_profile)) -> Response:
        memory_enabled_or_404()
        if scope == "household" and not household_writable(profile):
            raise HTTPException(status_code=403, detail=tr("Das Haushaltsgedächtnis darfst du nicht ändern."))
        if not store.memory_delete(scope, profile.id, memory_id):
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        return Response(status_code=204)

    # ------------------------------------------------------ Geplante Aufgaben

    def schedules_or_404() -> Scheduler:
        if not settings.schedules_enabled or scheduler is None:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        return scheduler

    def shown(row: dict, profile: Profile) -> dict:
        """Aufgabe für die Oberfläche: mit Satz zum Zeitplan; ein gelöschter Ergebnis-Chat wird nicht mehr verlinkt."""
        last = row["last_chat_id"]
        return {
            **row,
            "summary": sched.describe(row["freq"], row["at"], row["days"]),
            "last_chat_id": last if last and store.get_chat(profile.id, last) else "",
            "running": row["id"] in scheduler.live,
        }

    def clean_schedule(fields: dict, profile: Profile) -> dict:
        """Gemeinsame Prüfung für Anlegen und Ändern (``fields`` enthält nur, was geprüft werden soll)."""
        out: dict = {}
        if "name" in fields:
            name = " ".join(str(fields["name"]).split())
            if not name or re.search(r"[<>\x00-\x1f]", name):
                raise HTTPException(status_code=422, detail=tr("Bitte einen Namen eingeben (ohne < und >)."))
            out["name"] = name[:NAME_MAX]
        if "prompt" in fields:
            prompt = str(fields["prompt"]).strip()
            if not prompt:
                raise HTTPException(status_code=422, detail=tr("Bitte beschreiben, was die KI tun soll."))
            out["prompt"] = prompt
        if "model" in fields:
            wanted = (fields["model"] or "").strip()
            if wanted and wanted not in model_ids:
                raise HTTPException(status_code=422, detail=tr("Unbekanntes Modell"))
            out["model"] = "" if wanted == settings.model else wanted
        if "web" in fields:
            out["web"] = bool(fields["web"])
        if "enabled" in fields:
            out["enabled"] = bool(fields["enabled"])
        if "notify" in fields:
            mode = str(fields["notify"])
            if mode not in NOTIFY_MODES:
                raise HTTPException(status_code=422, detail=tr("Unbekannte Art der Benachrichtigung"))
            if mode == "phone" and not profile.notify_service:
                raise HTTPException(status_code=422, detail=tr("Für dich ist kein Benachrichtigungsdienst eingetragen."))
            if mode == "ha" and not (ha is not None and ha.enabled):
                raise HTTPException(status_code=422, detail=tr("Home Assistant ist nicht verbunden."))
            out["notify"] = mode
        return out

    @app.get("/api/schedules")
    def list_schedules(profile: Profile = Depends(current_profile)) -> list[dict]:
        schedules_or_404()
        return [shown(r, profile) for r in store.schedule_list(profile.id)]

    @app.post("/api/schedules", status_code=201, dependencies=[Depends(write_guard)])
    def create_schedule(body: ScheduleBody, profile: Profile = Depends(current_profile)) -> dict:
        schedules_or_404()
        fields = clean_schedule(body.model_dump(include={"name", "prompt", "model", "web", "notify", "enabled"}), profile)
        try:
            freq, at, days = sched.clean(body.freq, body.at, body.days)
        except sched.ScheduleError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        fields.update(freq=freq, at_time=at, days=days)
        upcoming = sched.next_timestamp(freq, at, days) if fields.get("enabled", True) else None
        row = store.schedule_create(profile.id, fields, upcoming)
        if row is None:
            raise HTTPException(status_code=409, detail=tr("Du hast schon 20 geplante Aufgaben. Lösche eine, bevor du eine neue anlegst."))
        return shown(row, profile)

    @app.patch("/api/schedules/{schedule_id}", dependencies=[Depends(write_guard)])
    def update_schedule(schedule_id: str, body: PatchScheduleBody, profile: Profile = Depends(current_profile)) -> dict:
        schedules_or_404()
        row = store.schedule_get(profile.id, schedule_id)
        if row is None:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        given = body.model_dump(exclude_unset=True)
        fields = clean_schedule({k: v for k, v in given.items() if k in ("name", "prompt", "model", "web", "notify", "enabled") and v is not None}, profile)
        timing = any(k in given and given[k] is not None for k in ("freq", "at", "days"))
        enabled = fields.get("enabled", row["enabled"])
        upcoming = row["next_run"]
        if timing or ("enabled" in fields and fields["enabled"] != row["enabled"]):
            try:
                freq, at, days = sched.clean(
                    given.get("freq") or row["freq"], given.get("at") or row["at"],
                    given["days"] if given.get("days") is not None else row["days"],
                )
            except sched.ScheduleError as exc:
                if not enabled and not timing:
                    freq, at, days = row["freq"], row["at"], row["days"]  # nur ausschalten
                else:
                    raise HTTPException(status_code=422, detail=str(exc)) from None
            fields.update(freq=freq, at_time=at, days=days)
            upcoming = sched.next_timestamp(freq, at, days) if enabled else None
        elif not enabled:
            upcoming = None
        updated = store.schedule_update(profile.id, schedule_id, fields, upcoming)
        if updated is None:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        return shown(updated, profile)

    @app.delete("/api/schedules/{schedule_id}", status_code=204, dependencies=[Depends(write_guard)])
    def delete_schedule(schedule_id: str, profile: Profile = Depends(current_profile)) -> Response:
        schedules_or_404()
        if not store.schedule_delete(profile.id, schedule_id):
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        return Response(status_code=204)

    @app.post("/api/schedules/{schedule_id}/run", status_code=202, dependencies=[Depends(write_guard)])
    async def run_schedule(schedule_id: str, profile: Profile = Depends(current_profile)) -> dict:
        """Jetzt ausführen (zusätzlich zum Zeitplan); das Ergebnis steht in einem neuen Chat."""
        schedules_or_404()
        row = store.schedule_get(profile.id, schedule_id)
        if row is None:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        if schedule_id in scheduler.live:
            raise HTTPException(status_code=409, detail=tr("Die Aufgabe läuft gerade."))
        if active_runs() >= MAX_PARALLEL:
            raise HTTPException(status_code=429, detail=tr("Gerade zu viele Anfragen, bitte kurz warten"))
        if any(i["status"] == "rejected" for i in limits.current()):
            raise HTTPException(status_code=429, detail=tr("Das Nutzungslimit deines Abos ist erreicht."))
        return {"chat_id": scheduler.start(row, profile, manual=True)}

    def active_runs() -> int:
        return sum(1 for r in runs.values() if not r.finished)

    def live_run(key: tuple[str, str]) -> Run | None:
        run = runs.get(key)
        if run and run.finished and time.monotonic() - run.finished_at > FINISHED_KEEP_SECONDS:
            runs.pop(key, None)
            return None
        return run

    async def make_title(profile_id: str, chat_id: str) -> dict | None:
        """Kurztitel zum ersten Austausch erzeugen. Ein selbst vergebener Titel wird nie überschrieben."""
        chat = store.get_chat(profile_id, chat_id)
        history = store.list_messages(profile_id, chat_id)
        if chat is None or history is None:
            return None
        if len(history) < 2 or history[0]["role"] != "user":
            return chat
        first, answer = history[0]["content"], history[1]["content"]
        provisional = _title_from(first)
        generate = getattr(backend, "title", None)
        if chat["title"] != provisional or generate is None:
            return chat
        new_title = None
        try:
            async with title_lock, asyncio.timeout(TITLE_TIMEOUT):
                new_title = await generate(first, answer)
        except (TimeoutError, Exception):  # Titel sind Beiwerk: der Vorlauf-Titel bleibt stehen
            log.info("Chat-Titel nicht erzeugt", exc_info=True)
        if new_title and new_title != provisional:
            store.replace_title_if(profile_id, chat_id, provisional, new_title)
        return store.get_chat(profile_id, chat_id) or chat

    @app.post("/api/chats/{chat_id}/title", dependencies=[Depends(write_guard)])
    async def generate_title(chat_id: str, profile: Profile = Depends(current_profile)) -> dict:
        chat = await make_title(profile.id, chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        return chat

    @app.post("/api/chats/{chat_id}/send", dependencies=[Depends(write_guard)])
    async def send(
        chat_id: str, body: SendBody, profile: Profile = Depends(current_profile)
    ) -> StreamingResponse:
        text = body.content.strip()
        if not text:
            raise HTTPException(status_code=422, detail=tr("Leere Nachricht"))
        history = store.list_messages(profile.id, chat_id)
        if history is None:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        try:
            files = await asyncio.to_thread(filelib.parse, [(f.name, f.data) for f in body.files])
        except filelib.AttachmentError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        body.files.clear()  # Base64-Kopien der Anfrage nicht länger festhalten
        # Frühere Dateien liegen nicht mehr vor: Claude bekommt nur den Hinweis, dass es sie gab.
        files_kept = settings.files_enabled and settings.files_edit
        history = [{**m, "content": m["content"] + filelib.note_for_history(m["attachments"], files_kept)} for m in history]
        key = (profile.id, chat_id)
        previous = live_run(key)
        if previous and not previous.finished:
            raise HTTPException(status_code=409, detail=tr("In diesem Chat läuft bereits eine Antwort"))
        if active_runs() >= MAX_PARALLEL:
            raise HTTPException(status_code=429, detail=tr("Gerade zu viele Anfragen, bitte kurz warten"))
        effort = body.effort or settings.default_effort
        chat = store.get_chat(profile.id, chat_id) or {}
        requested_model = (body.model or "").strip()
        if requested_model and requested_model not in model_ids:
            raise HTTPException(status_code=422, detail=tr("Unbekanntes Modell"))
        chosen_model = requested_model or (chat.get("model") if chat.get("model") in model_ids else "")
        model = chosen_model if chosen_model and chosen_model != settings.model else None  # None = Standard-Modell
        web_on = settings.web_level(profile) == "on" and body.web is not False
        first_exchange = not history and chat.get("title") in DEFAULT_TITLES
        metas = [f.meta() for f in files]
        instructions = store.chat_instructions(profile.id, chat_id)
        extra: dict = {"on_limit": limits.update}
        if model:
            extra["model"] = model
        if files:
            extra["attachments"] = files
        if instructions:
            extra["instructions"] = instructions
        summarize = getattr(backend, "summarize", None)
        level = ha_level(profile)

        # Die Frage steht ab jetzt in der Datenbank: Seite neu laden oder Chat wechseln verliert sie nicht mehr.
        question = store.add_message(profile.id, chat_id, "user", text, metas)
        if question is None:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        provisional = _title_from(text)
        if first_exchange:
            store.rename_chat(profile.id, chat_id, provisional)
        if requested_model:
            store.set_chat_model(profile.id, chat_id, "" if requested_model == settings.model else requested_model)
        run = Run(key, text, first_exchange)
        runs[key] = run

        def withdraw_question() -> None:
            """Keine Antwort entstanden: Frage wieder zurücknehmen, damit sie erneut gesendet werden kann."""
            store.delete_message(profile.id, chat_id, question["id"])
            if first_exchange:
                store.replace_title_if(profile.id, chat_id, provisional, chat.get("title") or default_title())

        async def ask_about(topic: str, label: str, details: str, offer_chat: bool) -> str:
            """Rückfrage an die Person: wartet, bis im Chat Zulassen oder Ablehnen gedrückt wurde (topic: ha, memory, github)."""
            run.approval_seq += 1
            aid = run.approval_seq
            future: asyncio.Future = asyncio.get_running_loop().create_future()
            run.pending[aid] = future
            run.push({"type": "approval", "id": aid, "label": label, "details": details, "chat_ok": offer_chat, "topic": topic})
            try:
                return await asyncio.wait_for(future, APPROVAL_TIMEOUT)
            except TimeoutError:
                return "deny"
            finally:
                run.pending.pop(aid, None)
                run.push({"type": "approval_done", "id": aid})

        async def ask(label: str, details: str, offer_chat: bool) -> str:
            return await ask_about("ha", label, details, offer_chat)

        async def ask_memory(label: str, details: str, offer_chat: bool) -> str:
            return await ask_about("memory", label, details, offer_chat)

        async def ask_github(label: str, details: str, offer_chat: bool) -> str:
            return await ask_about("github", label, details, offer_chat)

        stored_files: list[str] = []
        skipped_files: list[str] = []
        if files and files_kept:
            stored_files, skipped_files = await asyncio.to_thread(
                filelib.persist, store, profile.id, chat_id, files, settings.files_keep_days, MAX_PROFILE_BYTES
            )

        specs = []
        if level in ("read", "execute", "write") and ha is not None:
            toolbox = HaToolbox(
                ha, level,
                limit_to_exposed=settings.ha_limit_to_exposed,
                confirm_writes=settings.ha_write_confirm == "ask",
                # Dateien können eingeschleuste Anweisungen enthalten: dann nichts ohne ausdrückliches Zulassen
                force_confirm=lambda: bool(files) or any(a["kind"] in ("web", "gh-read", "file-read") for a in run.actions.values()),
                ask=ask,
                record=run.push,
                chat_allowed=lambda: key in chat_allow,
                allow_chat=lambda: chat_allow.add(key),
                backup_dir=HA_BACKUP_DIR,
                next_id=run.next_tool_id,
            )
            specs += toolbox.specs()
        context = ContextToolbox(
            store, profile.id, profile.label,
            project_id=store.chat_project_id(profile.id, chat_id),
            memory_enabled=settings.memory_enabled,
            household_write=household_writable(profile),
            force_confirm=bool(files),
            ask=ask_memory, record=run.push, next_id=run.next_tool_id,
            tainted=lambda: any(a["kind"] in ("read", "execute", "write", "knowledge", "gh-read", "gh-write", "web", "file-read") for a in run.actions.values()),
            overview=overview_allowed(profile),
        )
        specs += context.specs()
        if settings.files_enabled:
            specs += OutboxToolbox(
                store, profile.id, chat_id, record=run.push, next_id=run.next_tool_id,
                keep_days=settings.files_keep_days, author=settings.app_name, edit=settings.files_edit,
            ).specs()
        gh_level = github_level(profile)
        if gh_level != "none" and github is not None:
            def attachment_bytes(name: str) -> bytes | None:
                """Datei dieses Chats für einen Commit: erzeugte Datei oder Anhang dieser Nachricht (Word/Excel-Anhänge liegen nur als Text vor)."""
                made = store.outfile_bytes(profile.id, chat_id, name)
                if made is not None:
                    return made
                return next((f.data for f in files if f.name == name and f.original_size is None), None)

            specs += GithubToolbox(
                github, gh_level,
                policy=github_policy,
                confirm_writes=settings.github_write_confirm == "ask",
                force_confirm=lambda: bool(files) or any(a["kind"] in ("read", "execute", "write", "knowledge", "gh-read", "web", "file-read") for a in run.actions.values()),
                ask=ask_github, record=run.push, chat_allowed=lambda: key in github_allow, allow_chat=lambda: github_allow.add(key),
                next_id=run.next_tool_id, file_bytes=attachment_bytes,
            ).specs()
        if web_on:
            specs += WebToolbox(run.push, run.next_tool_id).specs()
            extra.update(web=True, record=run.push, next_id=run.next_tool_id)
        if specs:
            extra["tools"] = specs
        extra["note"] = context.note([p.label or p.id for p in settings.profiles], level, any(s.name.startswith("ha_") for s in specs))
        if any(s.name == "file_edit" for s in specs):
            extra["note"] += "\n" + FILES_NOTE
            if stored_files:
                extra["note"] += " In dieser Nachricht angehängt und im Chat abgelegt: " + ", ".join(stored_files) + "."
            if skipped_files:
                extra["note"] += " Nicht bearbeitbar: " + "; ".join(skipped_files) + "."
        if web_on:
            extra["note"] += "\n" + WEB_NOTE
        if any(s.name.startswith("github_") for s in specs):
            extra["note"] += "\n" + GITHUB_NOTE + " " + github_level_text(gh_level, github_policy)
        else:
            why = GITHUB_OFF_NO_RIGHT if github is not None and github.enabled else GITHUB_OFF_NO_TOKEN
            extra["note"] += "\n" + GITHUB_OFF_NOTE.format(why=why)

        async def generate() -> None:
            error: str | None = None
            try:
                # Zu langer Verlauf: älteren Teil zusammenfassen, statt ihn stillschweigend abzuschneiden.
                summary, upto = store.get_summary(profile.id, chat_id)
                pending = [m for m in history if upto is None or m["id"] > upto]
                if summarize and compact.needs_compaction(summary, pending, text):
                    plan = compact.split(pending)
                    if plan:
                        older, recent = plan
                        run.push({"type": "status", "text": tr("Fasse den früheren Verlauf zusammen …")})
                        produced: dict = {}

                        async def work() -> AsyncIterator[str]:
                            async with asyncio.timeout(SUMMARY_TIMEOUT):
                                produced["text"] = await summarize(summary, older)
                            return
                            yield  # macht daraus einen Generator, damit _pump Lebenszeichen senden kann

                        live = _pump(work, KEEPALIVE_SECONDS)
                        try:
                            async with contextlib.aclosing(live):
                                async for _ in live:
                                    pass
                        except Exception:
                            log.warning("Zusammenfassen fehlgeschlagen, Verlauf wird gekürzt", exc_info=True)
                        new_summary = produced.get("text")
                        if new_summary and store.set_summary(profile.id, chat_id, new_summary, older[-1]["id"]):
                            summary, pending = new_summary, recent
                            run.push({"type": "compacted"})
                context = ([{"role": "summary", "content": summary}] if summary else []) + [
                    {"role": m["role"], "content": m["content"]} for m in pending
                ]
                try:
                    async with asyncio.timeout(REQUEST_TIMEOUT + (TOOL_EXTRA_TIMEOUT if specs else 0)):
                        live = _pump(lambda: backend.stream(context, text, effort, **extra), KEEPALIVE_SECONDS)
                        async with contextlib.aclosing(live):
                            async for piece in live:
                                if piece is not None:
                                    run.push({"type": "delta", "text": piece})
                except BackendError as exc:
                    error = exc.user_message
                    run.error_resets_at = exc.resets_at
                except TimeoutError:
                    error = tr("Zeitüberschreitung: Claude hat nicht rechtzeitig geantwortet.")
            except asyncio.CancelledError:
                pass  # Stopp-Knopf oder Herunterfahren: vorhandene Teilantwort wird unten gespeichert
            except Exception:
                log.exception("Antwort fehlgeschlagen")
                error = tr("Unerwarteter Fehler beim Beantworten.")
            try:
                answer = "".join(run.parts)
                actions = run.action_log()
                if not answer and any(a["kind"] in ("execute", "write", "memory", "file") and a["status"] in ("ok", "abgebrochen") for a in actions):
                    answer = tr("_Die Aktionen wurden ausgeführt, die Antwort dazu fehlt. Das Protokoll steht oberhalb._")
                    run.push({"type": "delta", "text": answer})
                if answer:
                    # Auch eine abgebrochene Teilantwort wird behalten (setzt den Chat auf ungelesen).
                    store.add_message(profile.id, chat_id, "assistant", answer, tools=actions)
                else:
                    withdraw_question()
                run.error = error
                run.kept = bool(answer)
                run.title = _title_from(text) if first_exchange and answer else None
            except Exception:
                log.exception("Antwort konnte nicht gespeichert werden")
                run.error = run.error or tr("Die Antwort konnte nicht gespeichert werden.")
            finally:
                for future in list(run.pending.values()):
                    if not future.done():
                        future.cancel()
                files.clear()  # Inhalte verwerfen: sie existieren nur für diese eine Anfrage
                sweep = getattr(backend, "sweep", None)
                if metas and sweep:
                    with contextlib.suppress(Exception):
                        await asyncio.to_thread(sweep)
                run.finished = True
                run.finished_at = time.monotonic()
                run.wake()
                if not (run.error and not run.kept) and runs.get(key) is run:
                    runs.pop(key, None)  # fehlgeschlagene Läufe ohne Antwort bleiben abrufbar
                if run.first_exchange and run.title and run.followers == 0:
                    # Niemand sieht zu (Chat gewechselt, Seite neu geladen): Kurztitel gleich hier erzeugen.
                    with contextlib.suppress(Exception):
                        await make_title(profile.id, chat_id)
                if (
                    scheduler is not None and settings.notify_long_answers and profile.notify_service
                    and run.parts and not run.error and run.followers == 0
                    and run.finished_at - run.started >= LONG_ANSWER_SECONDS
                ):
                    # Eine längere Antwort ist fertig und niemand sieht zu: auf dem Handy Bescheid geben.
                    with contextlib.suppress(Exception):
                        shown_chat = store.get_chat(profile.id, chat_id) or {}
                        await scheduler.notify(profile, "phone", shown_chat.get("title") or tr("Antwort fertig"), plain_excerpt("".join(run.parts)))

        run.task = asyncio.create_task(generate())
        return StreamingResponse(
            follow_and_release(run),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
        )

    async def follow_and_release(run: Run) -> AsyncIterator[bytes]:
        async for chunk in follow(run):
            yield chunk
        # Fehler ohne Antwort sind ausgeliefert: sie müssen nicht länger vorgehalten werden.
        if runs.get(run.key) is run and run.finished:
            runs.pop(run.key, None)

    @app.get("/api/chats/{chat_id}/run")
    async def attach(chat_id: str, profile: Profile = Depends(current_profile)) -> Response:
        """An eine laufende (oder gerade fehlgeschlagene) Antwort wieder anhängen, z. B. nach einem Neuladen."""
        run = live_run((profile.id, chat_id))
        if run is None:
            return Response(status_code=204)
        return StreamingResponse(
            follow_and_release(run), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
        )

    @app.post("/api/chats/{chat_id}/approve", status_code=204, dependencies=[Depends(write_guard)])
    async def approve(chat_id: str, body: ApproveBody, profile: Profile = Depends(current_profile)) -> Response:
        """Antwort auf eine Rückfrage (Zulassen, Ablehnen, in diesem Chat immer zulassen)."""
        run = live_run((profile.id, chat_id))
        future = run.pending.get(body.id) if run else None
        if future is None or future.done():
            raise HTTPException(status_code=404, detail=tr("Keine offene Rückfrage"))
        future.set_result(body.decision)
        return Response(status_code=204)

    @app.post("/api/chats/{chat_id}/stop", status_code=204, dependencies=[Depends(write_guard)])
    async def stop(chat_id: str, profile: Profile = Depends(current_profile)) -> Response:
        run = live_run((profile.id, chat_id))
        if run and not run.finished and run.task:
            run.task.cancel()
        return Response(status_code=204)


_HA_ID = re.compile(r"^[0-9a-f]{32}$")


def make_scheduler(settings: Settings, store: Store, backend: ChatBackend, registry: Registry, ha: HaApi, github: GithubApi, runs: dict) -> Scheduler:
    """Geplante Aufgaben: ein gemeinsamer Ausführer für beide Zugänge (laufende Antworten zählen zusammen)."""
    return Scheduler(
        settings, store, backend, registry, ha, github, limitlib.shared(store), runs,
        lambda key, text: Run(key, text, False),
    )


def build_ingress_app(
    settings: Settings,
    store: Store,
    backend: ChatBackend,
    busy: dict | None = None,
    health: Health | None = None,
    branding: Branding | None = None,
    ha: HaApi | None = None,
    registry: Registry | None = None,
    scanner: OverviewScanner | None = None,
    github: GithubApi | None = None,
    scheduler: Scheduler | None = None,
    public_peers: PeerLog | None = None,
) -> FastAPI:
    i18n.set_language(settings.language)
    registry = registry or Registry.from_settings(settings, store)
    ha = ha or HaApi("", HA_WEBSOCKET_URL)
    scanner = scanner or (OverviewScanner(store, ha) if ha.enabled else None)
    github = github or GithubApi(settings.github_token)
    branding = branding or Branding(BRANDING_DIR, settings, ha)
    busy = busy if busy is not None else {}
    scheduler = scheduler or make_scheduler(settings, store, backend, registry, ha, github, busy)
    asset_version = _asset_version()
    app = FastAPI(title="HA Copilot", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.scheduler = scheduler
    _add_security_headers(app)

    def signed_in(scope: dict) -> bool:
        peer = (scope.get("client") or ("", 0))[0]
        try:
            resolve_ingress(registry, peer, Headers(scope=scope), settings.ingress_peers)
        except AccessDenied:
            return False
        return True

    app.add_middleware(BodyLimit, signed_in=signed_in)
    app.add_middleware(CollapseSlashes)  # zuletzt hinzugefügt = äußerste Schicht

    def current_profile(request: Request) -> Profile:
        peer = request.client.host if request.client else ""
        try:
            return resolve_ingress(registry, peer, request.headers, settings.ingress_peers)
        except AccessDenied as exc:
            log.warning("Zugriff verweigert: %s", exc.reason)
            raise HTTPException(status_code=403, detail=tr("Kein Zugriff")) from None

    def write_guard(request: Request) -> None:
        # Eigener Header erzwingt bei Cross-Site-Anfragen einen CORS-Preflight.
        if request.headers.get("x-requested-with") != "ki-chat":
            raise HTTPException(status_code=403, detail=tr("Kein Zugriff"))

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        try:
            current_profile(request)
        except HTTPException:
            return HTMLResponse(denied_page(request.headers), status_code=403)
        return _index_page(branding, asset_version, "ha")

    register_branding_routes(app, branding)

    @app.get("/login", response_class=HTMLResponse)
    def login_preview(request: Request) -> HTMLResponse:
        # Nur zur Ansicht der Anmeldeseite, solange der Domain-Zugang noch nicht aktiv ist.
        try:
            current_profile(request)
        except HTTPException:
            return HTMLResponse(denied_html(), status_code=403)
        return _login_page(branding, asset_version)

    register_chat_routes(
        app, settings, store, backend, busy, current_profile, write_guard,
        {"mode": "ingress", "can_logout": False},
        health, ha, "ingress", scanner, github, scheduler, registry, public_peers,
    )

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


class StartBody(BaseModel):
    email: str = Field(min_length=3, max_length=254)


def build_public_app(
    settings: Settings,
    store: Store,
    backend: ChatBackend,
    entra: EntraClient | None,
    busy: dict | None = None,
    health: Health | None = None,
    branding: Branding | None = None,
    ha: HaApi | None = None,
    registry: Registry | None = None,
    ha_login: HaLoginClient | None = None,
    scanner: OverviewScanner | None = None,
    github: GithubApi | None = None,
    scheduler: Scheduler | None = None,
    public_peers: PeerLog | None = None,
) -> FastAPI:
    """Domain-Zugang (Cloudflare Tunnel): eigene Anmeldeseite, Entra-Login (und optional Home Assistant), Sitzungs-Cookie.

    Liest absichtlich keine X-Remote-User-*-Header. Die Person steht ausschließlich in der
    serverseitigen Sitzung, die nach erfolgreicher Entra-Anmeldung angelegt wird.
    """
    i18n.set_language(settings.language)
    registry = registry or Registry.from_settings(settings, store)
    ha = ha or HaApi("", HA_WEBSOCKET_URL)
    scanner = scanner or (OverviewScanner(store, ha) if ha.enabled else None)
    github = github or GithubApi(settings.github_token)
    branding = branding or Branding(BRANDING_DIR, settings, ha)
    busy = busy if busy is not None else {}
    scheduler = scheduler or make_scheduler(settings, store, backend, registry, ha, github, busy)
    origin = settings.public_base_url
    version = _asset_version()
    pending = PendingLogins()
    ha_pending = PendingLogins()  # Anmeldung mit Home Assistant (state → Bindung an den Browser)
    start_limit = RateLimiter(10, 600)
    callback_limit = RateLimiter(30, 600)

    app = FastAPI(title="HA Copilot (Domain)", docs_url=None, redoc_url=None, openapi_url=None)
    _add_security_headers(app, PUBLIC_SECURITY_HEADERS)

    def client_ip(request: Request) -> str:
        peer = request.client.host if request.client else ""
        if public_peers is not None:
            public_peers.note(peer)
        if peer in settings.public_trusted_proxies:
            forwarded = request.headers.get("cf-connecting-ip", "").strip()
            try:
                return str(ipaddress.ip_address(forwarded))  # nur echte Adressen (kein Müll in Log und Ratenbegrenzung)
            except ValueError:
                pass
        return peer

    def session_profile(request: Request) -> Profile | None:
        profile_id = store.session_profile(request.cookies.get(SESSION_COOKIE, ""), settings.session_days)
        return registry.by_id(profile_id) if profile_id else None

    def signed_in(scope: dict) -> bool:
        return session_profile(Request(scope)) is not None

    app.add_middleware(BodyLimit, signed_in=signed_in)
    app.add_middleware(CollapseSlashes)

    def current_profile(request: Request) -> Profile:
        profile = session_profile(request)
        if profile is None:
            raise HTTPException(status_code=401, detail=tr("Nicht angemeldet"))
        return profile

    def write_guard(request: Request) -> None:
        # Eigener Header (erzwingt Preflight) und Herkunft müssen stimmen.
        if request.headers.get("x-requested-with") != "ki-chat" or request.headers.get("origin") != origin:
            raise HTTPException(status_code=403, detail=tr("Kein Zugriff"))

    def cookie(response: Response, name: str, value: str, max_age: int) -> None:
        response.set_cookie(
            name, value, max_age=max_age, path="/", secure=True, httponly=True, samesite="lax"
        )

    def back_to_login(code: str) -> RedirectResponse:
        response = RedirectResponse(f"/login?e={code}", status_code=303)
        response.delete_cookie(LOGIN_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
        return response

    register_branding_routes(app, branding)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/login", response_class=HTMLResponse)
    def login(request: Request) -> Response:
        client_ip(request)  # merkt sich die Gegenstelle für die Einrichtungsprüfung
        if session_profile(request) is not None:
            return RedirectResponse("/new", status_code=303)
        return _login_page(branding, version)

    def app_page(request: Request) -> Response:
        if session_profile(request) is None:
            return RedirectResponse("/login", status_code=303)
        return _index_page(branding, version, "web")

    app.add_api_route("/", app_page, methods=["GET"], response_class=HTMLResponse)
    app.add_api_route("/new", app_page, methods=["GET"], response_class=HTMLResponse)

    @app.get("/new/")
    def new_slash() -> RedirectResponse:  # relative Adressen der Oberfläche brauchen "/new" ohne Schrägstrich
        return RedirectResponse("/new", status_code=308)

    @app.post("/auth/start", dependencies=[Depends(write_guard)])
    async def auth_start(body: StartBody, request: Request) -> JSONResponse:
        ip = client_ip(request)
        if entra is None:
            raise HTTPException(status_code=404, detail=tr("Nicht verfügbar"))
        if not start_limit.allow(ip):
            log.warning("Anmeldung gedrosselt: %s", ip)
            raise HTTPException(status_code=429, detail=tr("Zu viele Versuche"))
        address = body.email.strip().lower()
        if registry.by_upn(address) is None:
            log.warning("Anmeldung für unbekannte Adresse abgewiesen (%s)", ip)
            raise HTTPException(status_code=403, detail=tr("Kein Zugang"))
        state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        verifier, challenge = pkce_pair()
        browser = request.cookies.get(LOGIN_COOKIE, "")
        if len(browser) < 32:
            browser = secrets.token_urlsafe(32)
        try:
            pending.add(state, nonce, verifier, browser)
            url = await entra.authorize_url(state, nonce, challenge, address)
        except OidcError as exc:
            log.error("Anmeldung nicht möglich: %s", exc)
            raise HTTPException(status_code=503, detail=tr("Anmeldung nicht verfügbar")) from None
        response = JSONResponse({"redirect": url})
        cookie(response, LOGIN_COOKIE, browser, 600)
        return response

    @app.get("/auth/callback")
    async def auth_callback(
        request: Request, code: str = "", state: str = "", error: str = ""
    ) -> RedirectResponse:
        ip = client_ip(request)
        if not callback_limit.allow(ip):
            log.warning("Rückkehr von Microsoft gedrosselt: %s", ip)
            return back_to_login("failed")
        browser = request.cookies.get(LOGIN_COOKIE, "")
        started = pending.take(state, browser) if entra is not None and state and browser else None
        if started is None:
            return back_to_login("expired")
        if error or not code:
            log.info("Anmeldung bei Microsoft abgebrochen: %r", error[:40])
            return back_to_login("cancelled" if error == "access_denied" else "failed")
        nonce, verifier = started
        try:
            identity = await entra.complete(code, verifier, nonce)
        except OidcError as exc:
            log.warning("Anmeldung fehlgeschlagen: %s", exc)
            return back_to_login("failed")
        try:
            profile = resolve_entra(registry, store, identity)
        except AccessDenied as exc:
            log.warning("Zugriff verweigert: %s", exc.reason)
            return back_to_login("denied")
        token = store.create_session(profile.id, settings.session_days)
        log.info("Anmeldung: Profil %s", profile.id)
        response = RedirectResponse("/new", status_code=303)
        response.delete_cookie(LOGIN_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
        cookie(response, SESSION_COOKIE, token, settings.session_days * 86400)
        return response

    @app.get("/auth/ha-start")
    def ha_start(request: Request) -> Response:
        """Zu Home Assistant weiterleiten (nur mit gesetzter ``ha_url``). Eine gewöhnliche Navigation, kein Schreibzugriff."""
        if ha_login is None:
            return back_to_login("failed")
        ip = client_ip(request)
        if not start_limit.allow(ip):
            log.warning("Anmeldung gedrosselt: %s", ip)
            return back_to_login("throttled")
        state = secrets.token_urlsafe(32)
        browser = request.cookies.get(LOGIN_COOKIE, "")
        if len(browser) < 32:
            browser = secrets.token_urlsafe(32)
        try:
            ha_pending.add(state, "", "", browser)
        except OidcError:
            return back_to_login("failed")
        response = RedirectResponse(ha_login.authorize_url(state), status_code=303)
        cookie(response, LOGIN_COOKIE, browser, 600)
        return response

    @app.get("/auth/ha-callback")
    async def ha_callback(request: Request, code: str = "", state: str = "", error: str = "") -> RedirectResponse:
        ip = client_ip(request)
        if ha_login is None or not callback_limit.allow(ip):
            return back_to_login("failed")
        browser = request.cookies.get(LOGIN_COOKIE, "")
        started = ha_pending.take(state, browser) if state and browser else None
        if started is None:
            return back_to_login("expired")
        if error or not code:
            log.info("Anmeldung bei Home Assistant abgebrochen: %r", error[:40])
            return back_to_login("cancelled" if error == "access_denied" else "failed")
        try:
            identity = await ha_login.complete(code)
        except HaLoginError as exc:
            log.warning("Anmeldung mit Home Assistant fehlgeschlagen: %s", exc)
            return back_to_login("failed")
        profile = registry.admit_ha(identity.user_id, (), identity.name)
        if profile is None:
            log.warning("Zugriff verweigert: Home-Assistant-Benutzer %s ist nicht freigegeben", identity.user_id)
            return back_to_login("denied")
        token = store.create_session(profile.id, settings.session_days)
        log.info("Anmeldung (Home Assistant): Profil %s", profile.id)
        response = RedirectResponse("/new", status_code=303)
        response.delete_cookie(LOGIN_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
        cookie(response, SESSION_COOKIE, token, settings.session_days * 86400)
        return response

    @app.post("/auth/logout", status_code=204, dependencies=[Depends(write_guard)])
    def auth_logout(request: Request) -> Response:
        store.delete_session(request.cookies.get(SESSION_COOKIE, ""))
        response = Response(status_code=204)
        response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
        return response

    register_chat_routes(
        app, settings, store, backend, busy, current_profile, write_guard,
        {"mode": "domain", "can_logout": True},
        health, ha, "public", scanner, github, scheduler, registry, public_peers,
    )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


SNAPSHOT_CHECK_SECONDS = 1800


async def _snapshot_loop(store: Store) -> None:
    """Etwa einmal am Tag einen Schnappschuss der Datenbank anlegen (die nächtliche HA-Sicherung nimmt ihn mit)."""
    while True:
        age = safety.newest_daily_age(SNAPSHOT_DIR, datetime.now(timezone.utc))
        if age is None or age >= safety.SNAPSHOT_EVERY:
            try:
                path = await asyncio.to_thread(store.snapshot, SNAPSHOT_DIR)
                log.info("Datenbank-Schnappschuss angelegt: %s", path.name)
            except Exception:
                log.exception("Datenbank-Schnappschuss fehlgeschlagen")
        await asyncio.sleep(SNAPSHOT_CHECK_SECONDS)


async def _sweep_loop(backend: ChatBackend, store: Store | None = None) -> None:
    """Zwischendateien des Claude-Programms und abgelaufene erzeugte Dateien regelmäßig entfernen."""
    sweep = getattr(backend, "sweep", None)
    while sweep or store:
        if sweep:
            try:
                await asyncio.to_thread(sweep)
            except Exception:
                log.warning("Aufräumen der Zwischendateien fehlgeschlagen", exc_info=True)
        if store:
            try:
                removed = await asyncio.to_thread(store.outfile_sweep)
                if removed:
                    log.info("%d abgelaufene erzeugte Dateien entfernt", removed)
            except Exception:
                log.warning("Aufräumen der erzeugten Dateien fehlgeschlagen", exc_info=True)
        await asyncio.sleep(SWEEP_SECONDS)
    return


RESOLVE_RETRY_SECONDS = 20  # bis Home Assistant nach einem Neustart antwortet
RESOLVE_IDLE_SECONDS = 300  # Benutzername unbekannt: gelegentlich erneut versuchen (Benutzer könnte inzwischen angelegt sein)


async def _resolve_loop(registry: Registry, ha: HaApi) -> None:
    """Benutzernamen aus der Konfiguration zu Home-Assistant-Benutzer-IDs auflösen und die Benutzer ins Protokoll schreiben."""
    listed = False
    while True:
        try:
            users = await ha.users()
        except HaApiError as exc:
            log.info("Home-Assistant-Benutzer noch nicht abrufbar: %s", exc)
            await asyncio.sleep(RESOLVE_RETRY_SECONDS)
            continue
        if not listed:
            listed = True
            for u in users:
                log.info("HA-Benutzer: %s (Anmeldename %s, Person %s) = %s", u["name"] or "-", u["username"] or "-", u["person"] or "-", u["id"])
        for note in registry.apply_ha_users(users):
            (log.info if "zugeordnet" in note else log.warning)("%s", note)
        if not registry.pending():
            return
        await asyncio.sleep(RESOLVE_IDLE_SECONDS)


SCAN_START_DELAY = 30  # Home Assistant nach dem Start erst in Ruhe hochfahren lassen
SCAN_CHECK_SECONDS = 600


async def _scan_loop(scanner: OverviewScanner, settings: Settings) -> None:
    """Den Überblick über Home Assistant beim ersten Start und danach alle ``ha_scan_days`` Tage einlesen."""
    if settings.ha_scan_days <= 0:
        log.info("Smarthome-Überblick: automatisches Einlesen ist aus (ha_scan_days: 0), nur auf Knopfdruck")
        return
    await asyncio.sleep(SCAN_START_DELAY)
    while True:
        try:
            readers = settings.ha_access_default != "none" or any(p.ha_access not in (None, "", "none") for p in settings.profiles)
            if readers and scanner.due(settings.ha_scan_days):
                await scanner.run("auto")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("Smarthome-Überblick: automatischer Lauf fehlgeschlagen", exc_info=True)
        await asyncio.sleep(SCAN_CHECK_SECONDS)


class _QuietServer(uvicorn.Server):
    """uvicorn ohne eigene Signalbehandlung: sonst löst es SIGTERM nach dem Herunterfahren erneut aus (Exit-Code 143)."""

    @contextlib.contextmanager
    def capture_signals(self):
        yield


async def _serve(
    settings: Settings, store: Store, backend: ChatBackend, health: Health | None = None, ha: HaApi | None = None
) -> None:
    branding = Branding(BRANDING_DIR, settings, ha)
    registry = Registry.from_settings(settings, store)
    def server(app: FastAPI, port: int) -> uvicorn.Server:
        config = uvicorn.Config(
            app,
            host="0.0.0.0",
            port=port,
            log_level="info",
            proxy_headers=False,  # Quelladresse ist immer die echte TCP-Gegenstelle
            server_header=False,
            timeout_graceful_shutdown=5,  # offene Streams nicht ewig abwarten (Supervisor beendet nach ca. 10 s hart)
        )
        return _QuietServer(config)

    busy: dict = {}  # laufende Antworten, gilt für beide Zugänge zusammen (MAX_PARALLEL)
    ha = ha or HaApi("", HA_WEBSOCKET_URL)
    scanner = OverviewScanner(store, ha) if ha.enabled else None  # ein gemeinsamer Stand für beide Zugänge
    github = GithubApi(settings.github_token)
    scheduler = make_scheduler(settings, store, backend, registry, ha, github, busy)
    public_peers = PeerLog()  # Gegenstellen der Domain-Seite (für die Einrichtungsprüfung)
    servers = [server(build_ingress_app(settings, store, backend, busy, health, branding, ha, registry, scanner, github, scheduler, public_peers), INGRESS_PORT)]
    if settings.public_enabled:
        entra = (
            EntraClient(
                settings.entra_tenant_id,
                settings.entra_client_id,
                settings.entra_client_secret,
                f"{settings.public_base_url}/auth/callback",
            )
            if settings.entra_enabled
            else None
        )
        ha_login = (
            HaLoginClient(settings.ha_url, f"{settings.public_base_url}/", f"{settings.public_base_url}/auth/ha-callback")
            if settings.ha_login_enabled
            else None
        )
        servers.append(
            server(build_public_app(settings, store, backend, entra, busy, health, branding, ha, registry, ha_login, scanner, github, scheduler, public_peers), PUBLIC_PORT)
        )
        log.info("Domain-Zugang aktiv: %s (Port %d)", settings.public_base_url, PUBLIC_PORT)
    snapshots = asyncio.create_task(_snapshot_loop(store))
    sweeper = asyncio.create_task(_sweep_loop(backend, store))
    tasks = [snapshots, sweeper]
    if settings.schedules_enabled:
        tasks.append(asyncio.create_task(scheduler.loop()))
    if ha.enabled:
        tasks.append(asyncio.create_task(_resolve_loop(registry, ha)))
    if scanner is not None and settings.memory_enabled:
        tasks.append(asyncio.create_task(_scan_loop(scanner, settings)))
    elif registry.pending():
        log.warning("Benutzernamen in den Profilen können nicht aufgelöst werden: keine Verbindung zu Home Assistant (bitte ha_user_id eintragen)")
    def stop() -> None:
        log.info("Beenden angefordert, fahre herunter")
        for s in servers:
            s.should_exit = True

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(sig, stop)
    try:
        await asyncio.gather(*(s.serve() for s in servers))
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await scheduler.shutdown()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    scrub_environment()
    settings = load_settings()
    i18n.set_language(settings.language)
    if settings.backend == "claude":
        backend: ChatBackend = ClaudeSdkBackend(
            settings.claude_oauth_token, settings.model, DB_PATH.parent, settings.title_model,
            api_key=settings.anthropic_api_key,
        )
        log.info("KI-Backend: Claude (%s), Standard-Aufwand %s", settings.model, settings.default_effort)
        if subscription_shared(settings):
            log.warning("Hinweis: Ein Claude-Abo-Token ist nur für den persönlichen Gebrauch gedacht, hier nutzen aber mehrere Personen oder die Domain-Seite die App. Nimm dafür einen API-Schlüssel (anthropic_api_key); siehe Anthropic-Nutzungsbedingungen.")
    else:
        backend = EchoBackend()
        log.warning("KI-Backend: Echo-Testmodus – es wird KEINE echte KI verwendet")
    report = safety.prepare(DB_PATH, SNAPSHOT_DIR, settings.restore_snapshot, BRANDING_DIR)
    for line in report.lines:
        (log.error if line.startswith("DATENBANK-FEHLER") else log.info)("Datensicherheit: %s", line)
    store = Store(DB_PATH)
    store.sync_profiles(p.id for p in settings.profiles)
    if settings.export_database:
        try:
            dest = safety.export_database(DB_PATH, BRANDING_DIR)
            log.warning("Datenbank-Export liegt in %s (Config-Ordner des Add-ons). Er enthält alle Chats und Sitzungen: nach dem Umzug löschen und die Option export_database ausschalten.", dest.name)
        except (OSError, sqlite3.DatabaseError) as exc:
            log.error("Datenbank-Export fehlgeschlagen: %s", exc)
    health = Health(settings, report.problem)
    for notice in health.notices():
        (log.error if notice["level"] == "error" else log.warning)("Hinweis: %s", notice["text"])
    log.info("Profile geladen: %s", ", ".join(p.id for p in settings.profiles))
    try:
        ha = HaApi(SUPERVISOR_TOKEN, HA_WEBSOCKET_URL, rest_url=HA_REST_URL)
        if not ha.enabled:
            log.info("Keine Verbindung zu Home Assistant (SUPERVISOR_TOKEN fehlt): Benutzernamen-Auflösung und Theme-Übernahme sind aus")
        asyncio.run(_serve(settings, store, backend, health, ha))
    finally:
        store.close()


if __name__ == "__main__":
    main()
