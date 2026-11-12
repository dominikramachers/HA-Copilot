"""HA Copilot: Profile, Chat-Verwaltung, Streaming-Antworten; Zugang über HA-Ingress und über die Domain (Entra)."""
from __future__ import annotations

import asyncio
import base64
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
from .backend_openai import OpenAIBackend
from .backend_router import RouterBackend
from . import attachments as filelib, compact, safety
from . import news as newslib
from . import quotes
from . import i18n
from .i18n import tr
from .previews import MAX_CHARS as PREVIEW_MAX_CHARS, PREVIEW_HEADERS, PreviewStore
from .branding import Branding
from .config import (
    BRANDING_DIR,
    DB_PATH,
    HA_REST_URL,
    HA_WEBSOCKET_URL,
    SNAPSHOT_DIR,
    SUPERVISOR_TOKEN,
    AUTO_MODEL,
    Profile,
    Settings,
    load_settings,
    model_label,
    provider_of,
)
from .ha_client import HaApi, HaApiError
from . import knowledge as knowlib
from . import projectfiles as pfiles
from . import skills as skilllib
from . import skills_github
from . import plugins as pluginlib
from . import plugins_github
from . import package_catalog
from . import memory_import as memlib
from .context_tools import (
    CONTENT_MAX, HOUSEHOLD_LIMIT, PERSON_LIMIT, PROJECT_LIMIT, RESERVED_TEXT, TOPIC_MAX, ContextToolbox, _RESERVED, _SECRET,
)
from .ha_tools import HaToolbox
from .images import IMAGES_NOTE, ImageService, ImageToolbox
from .outbox import DESIGN_NOTE, FILES_NOTE, MAX_PROFILE_BYTES, OutboxToolbox
from . import exporter
from . import limits as limitlib
from . import notifier as notifierlib
from . import schedule as sched
from .scheduler import NOTIFY_MODES, PROMPT_MAX, NAME_MAX, Scheduler, plain_excerpt
from .web_tools import WEB_NOTE, WebToolbox
from . import voice as voicelib
from .voice import VoiceError, VoiceService
from .github_accounts import AccountError, GithubAccounts
from . import connector_catalog, connector_icons
from .connectors import ConnectorError, ConnectorService, ConnectorToolbox
from .vault import Vault
from .github_tools import GITHUB_NOTE, GITHUB_OFF_NO_RIGHT, GITHUB_OFF_NO_TOKEN, GITHUB_OFF_NOTE, GithubToolbox, level_text as github_level_text
from .ha_scan import OverviewScanner
from .db import INSTRUCTIONS_MAX, Store
from .ha_login import HaLoginClient, HaLoginError
from .identity import AccessDenied, Registry, resolve_entra, resolve_ingress
from .oidc import EntraClient, OidcError, PendingLogins, pkce_pair
from .ops import Health
from . import setup_check
from .setup_check import PeerLog
from .ratelimit import RateLimiter

log = logging.getLogger("copilot")

STATIC_DIR = Path(__file__).parent / "static"
INGRESS_PORT = int(os.environ.get("COPILOT_PORT", "8099"))
PUBLIC_PORT = 8100

MAX_PARALLEL = 2  # gleichzeitige KI-Anfragen insgesamt (jede startet einen eigenen Prozess)
REQUEST_TIMEOUT = 600  # Sekunden
TOOL_EXTRA_TIMEOUT = 1500  # zusätzlich, wenn die KI Home Assistant benutzen darf (Rückfragen dauern)
APPROVAL_TIMEOUT = 600  # so lange wartet eine Rückfrage auf Antwort, danach gilt sie als abgelehnt
HA_BACKUP_DIR = DB_PATH.parent / "ha-backups"
VAULT_PATH = DB_PATH.parent / "connector.key"  # Schlüssel der Konnektoren: im Datenordner, nicht im Config-Ordner und nicht in den Schnappschüssen
TITLE_TIMEOUT = 40  # Sekunden für den automatischen Chat-Titel
SUMMARY_TIMEOUT = 240  # Sekunden für das Zusammenfassen eines langen Verlaufs
SWEEP_SECONDS = 1800  # Aufräumen der Zwischendateien des Claude-Programms
DELETE_WORDS = ("LÖSCHEN", "DELETE")  # eines davon muss zur Sicherheit eingetippt werden, bevor alle Chats gelöscht werden (die Oberfläche zeigt das Wort ihrer Sprache)
KEEPALIVE_SECONDS = 15  # Cloudflare trennt Verbindungen, über die ~100 s nichts fließt
SESSION_COOKIE = "__Host-ki_session"
LOGIN_COOKIE = "__Host-ki_login"
INCOGNITO_NOTE = (
    "Dies ist ein Inkognito-Chat: Du hast hier kein Gedächtnis und kannst nichts dauerhaft merken oder im Projekt ablegen; "
    "Erinnerungen der Person kennst du in diesem Chat nicht. Bittet die Person, sich etwas zu merken, sag kurz, dass das im Inkognito-Chat nicht geht "
    "und sie dafür einen normalen Chat öffnen kann. Erwähne den Inkognito-Modus sonst nicht. Aktionen in Home Assistant oder anderen Diensten, die du auf Wunsch ausführst, "
    "bleiben dort wie immer im Protokoll."
)
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
    if _HA_ID.fullmatch(own_id):
        name = html.escape(re.sub(r"[^\w.@ -]", "", headers.get("x-remote-user-name", ""))[:64])
        hint = (
            "<p>" + tr("Trage in der Add-on-Konfiguration beim Profil entweder deinen Home-Assistant-Benutzernamen")
            + (f" (<b>{name}</b>)" if name else "")
            + " " + tr("unter <code>ha_user</code> oder diese ID unter <code>ha_user_id</code> ein:") + "</p>"
            f"<p><code style='font-size:1.05rem;word-break:break-all'>{html.escape(own_id)}</code></p>"
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
    "Permissions-Policy": "geolocation=(), payment=(), usb=(), serial=(), bluetooth=(), microphone=(self)",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; frame-ancestors 'self'"
    ),
}


# Aktionsarten, nach denen fremde Inhalte im Chat sein können: danach fragen schreibende Werkzeuge immer nach
TAINTING_KINDS = frozenset({"read", "execute", "write", "knowledge", "gh-read", "gh-write", "web", "file-read", "skill-ext", "mcp-read", "mcp-write"})


class TitleBody(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class FileBody(BaseModel):
    name: str = Field(max_length=255)
    data: str = Field(max_length=filelib.MAX_BASE64_CHARS)  # Base64; wird nur im Arbeitsspeicher verarbeitet
    pasted: bool = False  # eingefügter langer Text (Textanhang der Person selbst, bleibt im Chat stehen)


class PreviewBody(BaseModel):
    html: str = Field(min_length=1, max_length=PREVIEW_MAX_CHARS)


class ConnectorBody(BaseModel):
    scope: str | None = Field(default=None, max_length=10)
    name: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=600)
    url: str | None = Field(default=None, max_length=500)
    auth: str | None = Field(default=None, max_length=10)
    mode: str | None = Field(default=None, max_length=10)
    scopes: str | None = Field(default=None, max_length=600)
    client_id: str | None = Field(default=None, max_length=300)
    client_secret: str | None = Field(default=None, max_length=600)
    clear_client_secret: bool | None = None
    shared_secret: str | None = Field(default=None, max_length=4100)
    header_name: str | None = Field(default=None, max_length=80)
    auth_params: dict[str, str] | None = None
    authorization_endpoint: str | None = Field(default=None, max_length=500)
    token_endpoint: str | None = Field(default=None, max_length=500)
    local_ok: bool | None = None
    catalog_id: str | None = Field(default=None, max_length=40)
    icon_url: str | None = Field(default=None, max_length=500)
    icon_data: str | None = Field(default=None, max_length=connector_icons.MAX_ICON_BYTES * 4 // 3 + 1024)
    icon_best_effort: bool | None = None
    clear_icon: bool | None = None


class ConnectSecretBody(BaseModel):
    secret: str = Field(default="", max_length=4100)


class OauthFinishBody(BaseModel):
    redirect_url: str = Field(min_length=1, max_length=3000)


class AccountBody(BaseModel):
    enabled: bool | None = None
    tools: dict[str, bool] | None = None


class SeenBody(BaseModel):
    what: Literal["intro", "news"]


class SendBody(BaseModel):
    content: str = Field(default="", max_length=20000)  # leer ist erlaubt, wenn Anhänge dabei sind
    effort: Literal["low", "medium", "high"] | None = None
    model: str | None = Field(default=None, max_length=64)  # nur aus der Liste der Konfiguration; sonst gilt das Standard-Modell
    web: bool | None = None  # False = Websuche für diese Nachricht abschalten
    files: list[FileBody] = Field(default_factory=list, max_length=filelib.MAX_FILES)
    # Eine frühere eigene Frage bearbeiten: sie und alles danach werden durch diese Nachricht und die neue Antwort ersetzt.
    edit_message_id: int | None = Field(default=None, ge=1)
    # Markierter Ausschnitt einer früheren Antwort, auf den sich die Nachricht bezieht (wird als Zitatblock vorangestellt, siehe quotes.py)
    quote: str | None = Field(default=None, max_length=quotes.QUOTE_MAX * 2)
    # Gesprochene Nachricht: schnelles Modell, kurze Antwort zum Vorlesen, weniger Werkzeuge, Rückfragen werden abgelehnt
    voice: bool = False


class _Declined(Exception):
    """Die Person hat eine Rückfrage vor dem Start der Antwort abgelehnt (z. B. Monatslimit für ChatGPT)."""


class DefaultModelBody(BaseModel):
    model: str = Field(default="", max_length=64)  # '' oder "auto" = das in der App eingestellte Modell


class CreateChatBody(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    project_id: str | None = Field(default=None, max_length=64)
    voice: bool = False  # Sprachgespräch außerhalb eines Chats: steht nicht in der Chatliste
    incognito: bool = False  # Inkognito-Chat: nichts bleibt zurück (kein Gedächtnis, keine Liste, wird beim Schließen gelöscht)


class ShareBody(BaseModel):
    mode: Literal["instance", "public"]
    expires_days: Literal[0, 7, 30] | None = None  # nur für den öffentlichen Link; 0 = läuft nie ab


class ShareModeBody(BaseModel):
    mode: Literal["instance", "public"]


class VoiceTextBody(BaseModel):
    text: str = Field(min_length=1, max_length=voicelib.MAX_SPEAK_CHARS)


class VoiceTimingBody(BaseModel):
    """Zeiten einer Sprachrunde in Millisekunden, wie die Oberfläche sie gemessen hat (nur zum Protokollieren)."""

    path: str = Field(pattern=r"^(quick|ai)$")
    stt_ms: int | None = Field(default=None, ge=0, le=600_000)    # Aufnahme hochladen bis Text da
    answer_ms: int | None = Field(default=None, ge=0, le=600_000)  # Text da bis erster Antworttext (Schnellpfad: bis Antwort)
    first_sound_ms: int | None = Field(default=None, ge=0, le=600_000)  # Antworttext bis erster Ton
    total_ms: int | None = Field(default=None, ge=0, le=600_000)   # Text da bis Ende der Antwort
    sentences: int | None = Field(default=None, ge=0, le=500)


class PresenceBody(BaseModel):
    """Meldung der Oberfläche: dieses Gerät (``client``) sieht gerade diesen Chat an (``chat_id``) oder keinen (``null``)."""

    client: str = Field(min_length=4, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    chat_id: str | None = Field(default=None, max_length=64)


class NotifyBody(BaseModel):
    enabled: bool
    devices: list[str] = Field(default_factory=list, max_length=20)


class PatchChatBody(BaseModel):
    """Teiländerung eines Chats; nicht mitgeschickte Felder bleiben unverändert (``project_id: null`` nimmt den Chat aus dem Projekt)."""

    title: str | None = Field(default=None, min_length=1, max_length=120)
    pinned: bool | None = None
    unread: bool | None = None
    project_id: str | None = Field(default=None, max_length=64)
    keep: bool | None = None  # True = Sprachgespräch als normalen Chat behalten (erscheint in der Chatliste)


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
SKILLS_PATH = re.compile(r"^/api/skills(/preview)?$")
PLUGINS_PATH = re.compile(r"^/api/plugins/import$")
PLUGINS_BODY_BYTES = int(plugins_github.MAX_BYTES * 4 / 3) + 128 * 1024  # ZIP aus dem GitHub-Abruf als Base64
CONNECTORS_PATH = re.compile(r"^/api/connectors(/\d+)?$")
MEMORY_IMPORT_PATH = re.compile(r"^/api/memory/import(/preview)?$")
CONNECTORS_BODY_BYTES = connector_icons.MAX_ICON_BYTES * 4 // 3 + 64 * 1024  # Logo als Base64 im Anfragetext
PREVIEW_BODY_BYTES = 700_000
VOICE_PATH = re.compile(r"^/api/voice/transcribe$")


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
            else skilllib.MAX_BASE64_CHARS + 64 * 1024 if SKILLS_PATH.match(scope["path"])
            else PLUGINS_BODY_BYTES if PLUGINS_PATH.match(scope["path"])
            else CONNECTORS_BODY_BYTES if CONNECTORS_PATH.match(scope["path"])
            else memlib.MAX_BASE64_CHARS + 64 * 1024 if MEMORY_IMPORT_PATH.match(scope["path"])
            else voicelib.MAX_AUDIO_BYTES if VOICE_PATH.match(scope["path"])
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


SHARE_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")  # secrets.token_urlsafe(32)

PUBLIC_SECURITY_HEADERS = {
    **SECURITY_HEADERS,
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; frame-ancestors 'none'; "
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


ONLY_FILES_PROMPT = "(Die Nachricht enthält nur Anhänge, keinen weiteren Text. Gehe auf die Anhänge ein: fasse sie kurz zusammen und frage, was ich damit vorhabe.)"


def _title_source(text: str, metas: list[dict] | None) -> str:
    """Text für den Chat-Titel: die Frage, bei reinem Anhang dessen Anfang oder Name."""
    if text.strip():
        return text
    for meta in metas or []:
        if meta.get("text"):
            return meta["text"]
    return next((m.get("name", "") for m in metas or []), "")


def _title_from(text: str) -> str:
    text = quotes.split_quote(text)[1] or text  # ein vorangestelltes Zitat gehört nicht in den Titel
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
            if event.get("undo"):
                self.actions[event["id"]]["undo"] = event["undo"]
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


def _shared_page(branding: Branding, version: str) -> HTMLResponse:
    page = i18n.translate_html((STATIC_DIR / "shared.html").read_text(encoding="utf-8"))
    return HTMLResponse(branding.render(page, version), headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow, noarchive", "Referrer-Policy": "no-referrer"})


def _index_page(branding: Branding, version: str, embed: str) -> HTMLResponse:
    page = i18n.translate_html((STATIC_DIR / "index.html").read_text(encoding="utf-8"))
    return HTMLResponse(branding.render(page, version, embed), headers={"Cache-Control": "no-store"})


class KnowledgeBody(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    data: str = Field(max_length=knowlib.MAX_BASE64_CHARS)  # Base64; Datei oder ZIP, wird nur im Arbeitsspeicher verarbeitet


class SkillGithubBody(BaseModel):
    url: str = Field(min_length=1, max_length=500)


class SkillUploadBody(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    data: str = Field(max_length=skilllib.MAX_BASE64_CHARS)  # Base64; SKILL.md, .skill oder ZIP


class SkillWriteBody(BaseModel):
    name: str = Field(default="", max_length=64)
    description: str = Field(min_length=1, max_length=skilllib.DESCRIPTION_MAX)
    instructions: str = Field(min_length=1, max_length=skilllib.SKILL_MD_MAX)


class SkillPatchBody(BaseModel):
    enabled: bool


class PluginServerBody(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    auth: str = Field(default="", max_length=20)


class PluginImportBody(BaseModel):
    data: str = Field(max_length=int(plugins_github.MAX_BYTES * 4 / 3) + 16)  # Base64; ZIP aus der Vorschau
    source: str = Field(min_length=1, max_length=200)
    skills: list[str] = Field(default_factory=list, max_length=pluginlib.MAX_IMPORT_SKILLS)
    servers: list[PluginServerBody] = Field(default_factory=list, max_length=pluginlib.MAX_IMPORT_SERVERS)


class MemoryBody(BaseModel):
    scope: Literal["household", "person", "project"]
    topic: str = Field(min_length=2, max_length=60)
    content: str = Field(min_length=3, max_length=800)
    project_id: str = Field(default="", max_length=64)


class MemoryUndoBody(BaseModel):
    """Eine Gedächtnis-Änderung der KI zurücknehmen: ``prev`` = Text davor (leer: gab es nicht), ``now`` = Text danach (leer: gelöscht)."""
    scope: Literal["household", "person", "project"]
    topic: str = Field(min_length=2, max_length=60)
    prev: str | None = Field(default=None, max_length=800)
    now: str | None = Field(default=None, max_length=800)
    project_id: str = Field(default="", max_length=64)


class InstructionsBody(BaseModel):
    text: str = Field(max_length=INSTRUCTIONS_MAX)


class MemoryImportBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    data: str = Field(min_length=1)


class MemoryImportEntry(BaseModel):
    topic: str = Field(max_length=300)
    content: str = Field(max_length=3000)
    replace: bool = False


class MemoryImportCommit(BaseModel):
    scope: Literal["household", "person"] = "person"
    entries: list[MemoryImportEntry] = Field(default_factory=list, max_length=memlib.MAX_ENTRIES)
    instructions: str | None = Field(default=None, max_length=INSTRUCTIONS_MAX)
    instructions_mode: Literal["replace", "append"] = "replace"


class GithubTokenBody(BaseModel):
    token: str = Field(max_length=400)


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
    scheduler: Scheduler | None = None,
    registry: Registry | None = None,
    public_peers: PeerLog | None = None,
    images: ImageService | None = None,
    connectors: ConnectorService | None = None,
    github_accounts: GithubAccounts | None = None,
    voice: VoiceService | None = None,
) -> None:
    """Chat-API; für Ingress und Domain identisch, nur die Zuordnung der Person unterscheidet sich."""
    chat_allow: set[tuple[str, str]] = set()  # Chats, in denen Änderungen in Home Assistant dauerhaft erlaubt wurden (nur Arbeitsspeicher)
    github_allow: set[tuple[str, str]] = set()  # dasselbe für GitHub
    connector_allow: set[tuple[str, str, int]] = set()  # dasselbe je Konnektor: (Person, Chat, Konnektor)
    connectors = connectors or make_connectors(settings, store, registry or Registry.from_settings(settings, store))
    limits = limitlib.shared(store)
    welcome = newslib.Welcome(store)
    presence = notifierlib.presence_for(store)
    notifier = notifierlib.notifier_for(store, settings, ha)
    if scheduler is not None:
        scheduler.phone_services = notifier.selected  # geplante Aufgaben melden an dieselben Geräte
    model_ids = {m["id"] for m in settings.model_choices()}

    def user_default_model(profile_id: str) -> str:
        """Standardmodell der Person für neue Chats ('' = Auto); ein nicht mehr wählbares Modell zählt als Auto."""
        wanted = store.profile_default_model(profile_id)
        return wanted if wanted in model_ids else ""

    def concrete_model(selection: str) -> str:
        """Auto (oder keine Angabe) = das in der App eingestellte Modell, sonst das gewählte."""
        return settings.model if selection in ("", AUTO_MODEL) else selection
    accounts = github_accounts or GithubAccounts(store, Vault(VAULT_PATH))
    images = images or ImageService(settings)
    voice = voice or VoiceService(settings, ha)
    voice_limit = RateLimiter(90, 60)  # Aufnahmen und Vorlese-Stücke je Person und Minute

    def voice_allowed(profile: Profile) -> bool:
        return settings.voice_level(profile) == "on"

    def need_voice(profile: Profile) -> None:
        if not voice_allowed(profile):
            raise HTTPException(status_code=403, detail=tr("Sprache ist für dich nicht freigeschaltet."))
        if not voice_limit.allow(profile.id):
            raise HTTPException(status_code=429, detail=tr("Gerade zu viele Anfragen, bitte kurz warten"))
    title_lock = asyncio.Lock()  # Titel einzeln nacheinander, damit sie keine Antworten ausbremsen
    previews = PreviewStore()  # HTML-Vorschauen, nur im Arbeitsspeicher
    export_limit = RateLimiter(4, 600)  # ZIP-Export nicht im Sekundentakt
    scan_limit = RateLimiter(4, 600)  # „Neu einlesen“ nicht im Sekundentakt
    import_limit = RateLimiter(30, 600)  # Gedächtnis-Import: Vorschau und Übernehmen

    def ha_level(profile: Profile) -> str:
        """Stufe des Zugriffs auf Home Assistant für diese Person über diesen Zugangsweg."""
        if ha is None or not ha.enabled:
            return "none"
        if channel == "public" and not settings.ha_access_via_domain:
            return "none"
        return profile.ha_access or settings.ha_access_default

    def github_level(profile: Profile) -> str:
        """Stufe des Zugriffs auf GitHub für diese Person (none, read, write)."""
        if not accounts.enabled_for(profile.id):
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
            "picture": bool(profile.ha_user_id) and ha is not None and ha.enabled,
            "app_name": settings.app_name,
            "default_effort": settings.default_effort,
            "test_mode": settings.backend == "echo",
            "notices": health.notices() if health else [],
            "ha_access": ha_level(profile),
            "github": github_level(profile),
            "github_connect": (profile.github_access or settings.github_access_default) != "none",
            "web": settings.web_level(profile) == "on",
            "voice": voice_allowed(profile),
            "voice_wake": settings.app_name if voice_allowed(profile) else "",
            "connectors": connectors.level(profile.id) >= 1,
            "models": settings.model_choices(),
            "default_model": settings.model,
            "user_model": user_default_model(profile.id),
            "openai": settings.openai_active,
            "limits": limits.current(),
            "schedules": settings.schedules_enabled and scheduler is not None,
            "notify_phone": notifier.available,  # die Geräte der Person ermittelt der Melder beim Senden aus Home Assistant
            "notify": notifier.available,
            "notify_ha": ha is not None and ha.enabled,
            "memory": settings.memory_enabled,
            "incognito": settings.incognito_enabled,
            "sharing": settings.sharing,
            "sharing_public": settings.sharing == "public" and bool(settings.public_base_url),
            "overview": overview_allowed(profile),
            "setup": channel == "ingress",
            "setup_open": setup_check.banner(settings) if channel == "ingress" else None,
            "welcome": welcome.state(profile.id),
            **me_extra,
        }

    @app.get("/api/me/picture")
    async def me_picture(profile: Profile = Depends(current_profile)) -> Response:
        """Das Profilbild der Person aus Home Assistant (Einstellungen der Person dort); ohne Bild 404, die Oberfläche zeigt dann den Buchstaben."""
        try:
            found = await ha.person_picture(profile.ha_user_id) if ha is not None and profile.ha_user_id else None
        except HaApiError:
            found = None
        if not found:
            raise HTTPException(status_code=404, detail="kein Profilbild")
        return Response(found[0], media_type=found[1], headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"})

    @app.put("/api/me/model", dependencies=[Depends(write_guard)])
    def save_default_model(body: DefaultModelBody, profile: Profile = Depends(current_profile)) -> dict:
        """Standardmodell der Person für neue Chats (Einstellungen); Auto = das in der App eingestellte Modell."""
        wanted = body.model.strip()
        if wanted == AUTO_MODEL:
            wanted = ""
        if wanted and wanted not in model_ids:
            raise HTTPException(status_code=422, detail=tr("Unbekanntes Modell"))
        return {"model": store.set_profile_default_model(profile.id, wanted)}

    @app.post("/api/presence", status_code=204, dependencies=[Depends(write_guard)])
    def report_presence(body: PresenceBody, profile: Profile = Depends(current_profile)) -> Response:
        """Die Oberfläche meldet, welchen Chat sie gerade zeigt (alle 20 Sekunden und bei jedem Wechsel)."""
        presence.seen(profile.id, body.client, body.chat_id)
        return Response(status_code=204)

    @app.get("/api/notify")
    async def notify_settings(profile: Profile = Depends(current_profile)) -> dict:
        """Meldungen aufs Handy: an/aus und die Geräte, auf denen die Home-Assistant-App der Person angemeldet ist."""
        if not notifier.available:
            raise HTTPException(status_code=404, detail=tr("Home Assistant ist nicht verbunden."))
        return await notifier.devices(profile)

    @app.put("/api/notify", dependencies=[Depends(write_guard)])
    async def save_notify(body: NotifyBody, profile: Profile = Depends(current_profile)) -> dict:
        if not notifier.available:
            raise HTTPException(status_code=404, detail=tr("Home Assistant ist nicht verbunden."))
        known = {d["service"] for d in (await notifier.devices(profile))["devices"]}
        unknown = [d for d in body.devices if d not in known]
        if unknown:
            raise HTTPException(status_code=422, detail=tr("Unbekanntes Gerät: {device}", device=unknown[0]))
        notifier.save(profile, body.enabled, body.devices)
        return await notifier.devices(profile)

    @app.post("/api/welcome/seen", status_code=204, dependencies=[Depends(write_guard)])
    def welcome_seen(body: SeenBody, profile: Profile = Depends(current_profile)) -> Response:
        """Die Person hat die Einführung oder die Neuerungen mit „Okay“ bestätigt; beides erscheint nicht wieder."""
        welcome.confirm(profile.id, body.what)
        return Response(status_code=204)

    @app.get("/api/news")
    def news_history(profile: Profile = Depends(current_profile)) -> list[dict]:
        """Alle Neuerungen nach Version (Menüpunkt „Das ist neu“)."""
        return newslib.history()

    @app.get("/api/setup")
    async def setup(profile: Profile = Depends(current_profile)) -> dict:
        """Einrichtungsprüfung (nur über Home Assistant; die Konfiguration ändert man dort)."""
        if channel != "ingress":
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        items = setup_check.static_items(
            settings, profile,
            ha_enabled=ha is not None and ha.enabled,
            github_enabled=accounts.enabled_for(profile.id),
            ha_level=ha_level(profile),
            github_level=github_level(profile),
            db_problem=health.db_problem if health else None,
            pending_users=registry.pending() if registry else (),
            hostname=socket.gethostname(),
            public_peers=public_peers.recent() if public_peers else (),
        )
        gh_api = accounts.api_for(profile.id)
        await setup_check.run_live(items, ha if ha is not None and ha.enabled else None, gh_api if gh_api.enabled else None, profile, settings, notifier)
        return {"items": items, "open": setup_check.open_count(items)}

    # ------------------------------------------------------------ GitHub-Konto der Person

    github_start_limit = RateLimiter(8, 600)  # neuer Anmeldecode bei GitHub
    github_token_limit = RateLimiter(10, 600)  # eingefügte Token werden bei GitHub geprüft
    github_poll_limit = RateLimiter(400, 600)  # Browser fragt etwa alle 5 Sekunden nach; GitHub selbst wird davon getrennt gedrosselt

    def github_configured_level(profile: Profile) -> str:
        return profile.github_access or settings.github_access_default

    def github_allowed(profile: Profile) -> None:
        if github_configured_level(profile) == "none":
            raise HTTPException(status_code=403, detail=tr("Für dich ist GitHub nicht freigegeben. Der Administrator stellt das in der Konfiguration ein."))

    def github_limit(limiter: RateLimiter, profile: Profile) -> None:
        if not limiter.allow(profile.id):
            raise HTTPException(status_code=429, detail=tr("Zu viele Versuche. Bitte in ein paar Minuten noch einmal."))

    @app.get("/api/github/account")
    def github_account(profile: Profile = Depends(current_profile)) -> dict:
        """Stand des GitHub-Zugangs dieser Person (das Token selbst verlässt das Add-on nie)."""
        return {
            **accounts.info(profile.id),
            "level": github_configured_level(profile),
        }

    @app.post("/api/github/device", dependencies=[Depends(write_guard)])
    async def github_device_start(profile: Profile = Depends(current_profile)) -> dict:
        """Anmeldung bei GitHub beginnen: liefert den Code, den die Person bei GitHub eingibt."""
        github_allowed(profile)
        github_limit(github_start_limit, profile)
        try:
            return await accounts.device_start(profile.id)
        except AccountError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from None

    @app.post("/api/github/device/poll", dependencies=[Depends(write_guard)])
    async def github_device_poll(profile: Profile = Depends(current_profile)) -> dict:
        """Stand der Anmeldung; bewusst POST: über die Domain prüft der Schutz die Herkunft, und die sendet der Browser nur bei POST."""
        github_allowed(profile)
        github_limit(github_poll_limit, profile)
        try:
            return await accounts.device_poll(profile.id)
        except AccountError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from None

    @app.delete("/api/github/device", status_code=204, dependencies=[Depends(write_guard)])
    def github_device_cancel(profile: Profile = Depends(current_profile)) -> Response:
        accounts.device_cancel(profile.id)
        return Response(status_code=204)

    @app.post("/api/github/token", dependencies=[Depends(write_guard)])
    async def github_token(body: GithubTokenBody, profile: Profile = Depends(current_profile)) -> dict:
        """Ein selbst erzeugtes Token einfügen (wird vor dem Speichern bei GitHub geprüft)."""
        github_allowed(profile)
        github_limit(github_token_limit, profile)
        try:
            login = await accounts.connect_token(profile.id, body.token)
        except AccountError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from None
        return {"login": login}

    @app.delete("/api/github/account", status_code=204, dependencies=[Depends(write_guard)])
    def github_disconnect(profile: Profile = Depends(current_profile)) -> Response:
        accounts.disconnect(profile.id)
        github_allow.difference_update({k for k in github_allow if k[0] == profile.id})  # „in diesem Chat immer zulassen“ gilt nicht für ein anderes Konto
        return Response(status_code=204)

    # ------------------------------------------------------------ Konnektoren

    connector_limit = RateLimiter(40, 600)  # Verbinden, Anmelden und Neu-Einlesen sprechen mit fremden Servern: nicht im Sekundentakt
    callback_limit = RateLimiter(30, 600)

    def connector_guard(profile: Profile) -> None:
        if connectors.level(profile.id) < 1:
            raise HTTPException(status_code=403, detail=tr("Kein Zugriff"))

    def connector_call_limit(profile: Profile) -> None:
        if not connector_limit.allow(profile.id):
            raise HTTPException(status_code=429, detail=tr("Zu viele Versuche. Bitte in ein paar Minuten noch einmal."))

    def connector_fail(exc: ConnectorError) -> HTTPException:
        return HTTPException(status_code=exc.status, detail=str(exc))

    def connector_overview(profile: Profile) -> dict:
        redirect, manual = connectors.redirect_uri()
        return {
            "items": connectors.listing(profile.id),
            "can_create": connectors.can_create(profile.id),
            "redirect_uri": redirect,
            "manual_redirect": manual,
            "write_confirm": settings.connector_write_confirm,
            "allow_private": settings.connector_allow_private,
        }

    @app.get("/api/connectors")
    def connectors_list(profile: Profile = Depends(current_profile)) -> dict:
        connector_guard(profile)
        return connector_overview(profile)

    @app.get("/api/connectors/catalog")
    def connectors_catalog(profile: Profile = Depends(current_profile)) -> dict:
        connector_guard(profile)
        return {
            "checked": connector_catalog.checked(),
            "categories": connector_catalog.categories(),
            "connectors": connector_catalog.entries(),
            "guides": connector_catalog.guides(),
        }

    @app.get("/api/connectors/registry")
    async def connectors_registry(q: str = "", cursor: str = "", profile: Profile = Depends(current_profile)) -> dict:
        connector_guard(profile)
        connector_call_limit(profile)
        try:
            return await connectors.registry_search(profile.id, q, cursor)
        except ConnectorError as exc:
            raise connector_fail(exc) from None

    @app.get("/api/connectors/{connector_id}/icon")
    def connectors_icon(connector_id: int, profile: Profile = Depends(current_profile)) -> Response:
        connector_guard(profile)
        try:
            icon = connectors.icon(profile.id, connector_id)
        except ConnectorError as exc:
            raise connector_fail(exc) from None
        if icon is None:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        return Response(
            content=icon["data"], media_type=icon["mime"],
            headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; sandbox", "Cache-Control": "private, max-age=86400"},
        )

    @app.post("/api/connectors", status_code=201, dependencies=[Depends(write_guard)])
    async def connectors_create(body: ConnectorBody, profile: Profile = Depends(current_profile)) -> dict:
        connector_guard(profile)
        try:
            return await connectors.create(profile.id, body.model_dump(exclude_unset=True, exclude_none=True))
        except ConnectorError as exc:
            raise connector_fail(exc) from None

    @app.patch("/api/connectors/{connector_id}", dependencies=[Depends(write_guard)])
    async def connectors_update(connector_id: int, body: ConnectorBody, profile: Profile = Depends(current_profile)) -> dict:
        connector_guard(profile)
        try:
            return await connectors.update(profile.id, connector_id, body.model_dump(exclude_unset=True, exclude_none=True))
        except ConnectorError as exc:
            raise connector_fail(exc) from None

    @app.delete("/api/connectors/{connector_id}", status_code=204, dependencies=[Depends(write_guard)])
    def connectors_delete(connector_id: int, profile: Profile = Depends(current_profile)) -> Response:
        connector_guard(profile)
        try:
            connectors.delete(profile.id, connector_id)
        except ConnectorError as exc:
            raise connector_fail(exc) from None
        return Response(status_code=204)

    @app.post("/api/connectors/{connector_id}/connect", dependencies=[Depends(write_guard)])
    async def connectors_connect(connector_id: int, body: ConnectSecretBody, profile: Profile = Depends(current_profile)) -> dict:
        connector_guard(profile)
        connector_call_limit(profile)
        try:
            return await connectors.connect(profile.id, connector_id, body.secret)
        except ConnectorError as exc:
            raise connector_fail(exc) from None

    @app.post("/api/connectors/{connector_id}/refresh", dependencies=[Depends(write_guard)])
    async def connectors_refresh(connector_id: int, profile: Profile = Depends(current_profile)) -> dict:
        connector_guard(profile)
        connector_call_limit(profile)
        try:
            return await connectors.refresh_tools(profile.id, connector_id)
        except ConnectorError as exc:
            raise connector_fail(exc) from None

    @app.post("/api/connectors/{connector_id}/disconnect", status_code=204, dependencies=[Depends(write_guard)])
    def connectors_disconnect(connector_id: int, profile: Profile = Depends(current_profile)) -> Response:
        connector_guard(profile)
        try:
            connectors.disconnect(profile.id, connector_id)
        except ConnectorError as exc:
            raise connector_fail(exc) from None
        return Response(status_code=204)

    @app.patch("/api/connectors/{connector_id}/account", dependencies=[Depends(write_guard)])
    def connectors_account(connector_id: int, body: AccountBody, profile: Profile = Depends(current_profile)) -> dict:
        connector_guard(profile)
        try:
            return connectors.set_account(profile.id, connector_id, enabled=body.enabled, tools=body.tools)
        except ConnectorError as exc:
            raise connector_fail(exc) from None

    @app.post("/api/connectors/{connector_id}/oauth/start", dependencies=[Depends(write_guard)])
    async def connectors_oauth_start(connector_id: int, profile: Profile = Depends(current_profile)) -> dict:
        connector_guard(profile)
        connector_call_limit(profile)
        try:
            return await connectors.begin_oauth(profile.id, connector_id)
        except ConnectorError as exc:
            raise connector_fail(exc) from None

    @app.post("/api/connectors/oauth/finish", dependencies=[Depends(write_guard)])
    async def connectors_oauth_finish(body: OauthFinishBody, profile: Profile = Depends(current_profile)) -> dict:
        """Ohne Domain-Zugang: die Person fügt die Adresse ein, zu der der Browser nach der Anmeldung weitergeleitet hat."""
        connector_guard(profile)
        connector_call_limit(profile)
        code, state, error = connectors.parse_redirect(body.redirect_url)
        if error and not code:
            raise HTTPException(status_code=400, detail=tr("Der Dienst hat die Anmeldung abgelehnt") + f": {error[:200]}")
        try:
            done = await connectors.finish_oauth(state, code, profile_id=profile.id)
        except ConnectorError as exc:
            raise connector_fail(exc) from None
        return next((v for v in connectors.listing(profile.id) if v["id"] == done["connector"]), {})

    @app.get("/connectors/callback", response_class=HTMLResponse)
    async def connectors_callback(request: Request) -> HTMLResponse:
        """Rückkehr des Browsers nach der Anmeldung beim Dienst (nur mit Domain-Zugang). Keine Sitzung nötig: ``state`` bindet an Person und Konnektor."""
        peer = request.client.host if request.client else ""
        if not callback_limit.allow(peer or "?"):
            return _connector_page(False, tr("Zu viele Versuche. Bitte in ein paar Minuten noch einmal."))
        code = request.query_params.get("code", "")
        state = request.query_params.get("state", "")
        error = request.query_params.get("error_description") or request.query_params.get("error") or ""
        if error and not code:
            connectors.drop_flow(state)
            return _connector_page(False, tr("Der Dienst hat die Anmeldung abgelehnt") + f": {error[:200]}")
        try:
            await connectors.finish_oauth(state, code)
        except ConnectorError as exc:
            # Feste Texte statt der Fehlermeldung selbst: die Seite ist ohne Anmeldung erreichbar und soll keine Einzelheiten preisgeben.
            if exc.status == 502:
                return _connector_page(False, tr("Der Dienst hat die Anmeldung nicht angenommen. Öffne im HA Copilot die Konnektoren und melde dich noch einmal an."))
            return _connector_page(False, tr("Die Anmeldung ist abgelaufen oder gehört nicht zu dieser Sitzung. Bitte noch einmal anmelden."))
        return _connector_page(True, tr("Der Konnektor ist verbunden. Du kannst dieses Fenster schließen und zum HA Copilot zurückkehren."))

    # ------------------------------------------------------------------ Sprache

    @app.get("/api/voice")
    async def voice_status(profile: Profile = Depends(current_profile)) -> dict:
        """Stand der Sprachfunktion für diese Person: freigeschaltet, womit erkannt und womit gesprochen wird."""
        allowed = voice_allowed(profile)
        return {
            "allowed": allowed,
            "stt": await voice.provider() if allowed else "",
            "speech": await voice.speech() if allowed else "device",
            "name": settings.app_name,
            "language": settings.language,
            "browser": settings.voice_browser_stt,
            "chat_days": settings.voice_chat_days,
        }

    @app.post("/api/voice/transcribe", dependencies=[Depends(write_guard)])
    async def voice_transcribe(request: Request, profile: Profile = Depends(current_profile)) -> dict:
        """Aufnahme (WAV, 16 Bit, mono) in Text wandeln. Der Ton wird nur im Arbeitsspeicher verarbeitet und nicht gespeichert."""
        need_voice(profile)
        audio = await request.body()
        if not audio or len(audio) > voicelib.MAX_AUDIO_BYTES:
            raise HTTPException(status_code=422, detail=tr("Die Aufnahme konnte nicht gelesen werden."))
        started = time.monotonic()
        try:
            text = await voice.transcribe(audio)
        except VoiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        log.info("Sprache: Erkennung über %s dauerte %.2f s (%.1f KB Aufnahme)", await voice.provider(), time.monotonic() - started, len(audio) / 1024)
        return {"text": text, "command": voicelib.strip_wake(text, settings.app_name)}

    @app.post("/api/voice/speak", dependencies=[Depends(write_guard)])
    async def voice_speak(body: VoiceTextBody, profile: Profile = Depends(current_profile)) -> Response:
        """Ein Stück Antwort vorlesen lassen (nur wenn die Stimme nicht vom Gerät kommt)."""
        need_voice(profile)
        started = time.monotonic()
        try:
            audio, mime = await voice.speak(body.text)
        except VoiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        log.info("Sprache: Stimme (%s) für %d Zeichen dauerte %.2f s", await voice.speech(), len(body.text), time.monotonic() - started)
        return Response(audio, media_type=mime, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    @app.post("/api/voice/timing", dependencies=[Depends(write_guard)])
    async def voice_timing(body: VoiceTimingBody, profile: Profile = Depends(current_profile)) -> dict:
        """Die Oberfläche meldet die Zeiten einer Sprachrunde; sie landen als eine Zeile im Protokoll (keine Inhalte, nur Zahlen)."""
        need_voice(profile)
        part = lambda label, ms: f"{label} {ms / 1000:.1f} s" if ms is not None else ""  # noqa: E731
        parts = [part("Erkennung", body.stt_ms), part("Antwort" if body.path == "quick" else "KI bis erster Text", body.answer_ms),
                 part("bis erster Ton", body.first_sound_ms), part("Antwort gesamt", body.total_ms)]
        log.info("Sprache: Runde über %s: %s%s", "Schnellpfad" if body.path == "quick" else "KI", ", ".join(x for x in parts if x),
                 f", {body.sentences} Sätze" if body.sentences else "")
        return {"ok": True}

    @app.get("/api/voice/chats")
    def voice_chats(profile: Profile = Depends(current_profile)) -> list[dict]:
        """Sprachgespräche außerhalb eines Chats (stehen nicht in der Chatliste)."""
        return store.list_chats(profile.id, "voice")

    @app.post("/api/chats/{chat_id}/voice", dependencies=[Depends(write_guard)])
    async def voice_command(chat_id: str, body: VoiceTextBody, profile: Profile = Depends(current_profile)) -> dict:
        """Schneller Pfad: den Satz von Home Assistant selbst ausführen lassen, ohne KI.

        ``handled: false`` heißt: nicht verstanden oder nicht erlaubt, die Oberfläche schickt den Satz dann als
        gesprochene Nachricht an die KI. Ausgeführte Befehle stehen als Frage und kurze Antwort im Chat.
        """
        need_voice(profile)
        chat = store.get_chat(profile.id, chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        text = " ".join(body.text.split())
        previous = live_run((profile.id, chat_id))
        if previous and not previous.finished:
            raise HTTPException(status_code=409, detail=tr("In diesem Chat läuft bereits eine Antwort"))
        started = time.monotonic()
        result = await voice.quick_command(text, ha_level(profile))
        log.info("Sprache: Schnellpfad dauerte %.2f s (%s)", time.monotonic() - started, "ausgeführt" if result else "an die KI übergeben")
        if result is None:
            return {"handled": False}
        first = chat.get("title") in DEFAULT_TITLES | {tr("Sprachgespräch")} and not store.list_messages(profile.id, chat_id)
        if store.add_message(profile.id, chat_id, "user", text) is None:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        label = tr("Sprachbefehl über Home Assistant")
        status = "error" if result.blocked else "ok"
        store.add_message(profile.id, chat_id, "assistant", result.speech, tools=[{"label": label, "kind": "execute", "status": status, "note": ""}])
        store.set_chat_unread(profile.id, chat_id, False)  # wurde gerade gehört
        if first:
            store.rename_chat(profile.id, chat_id, _title_from(text))
        return {"handled": True, "speech": result.speech, "blocked": result.blocked}

    @app.get("/api/limits")
    def usage_limits(profile: Profile = Depends(current_profile)) -> list[dict]:
        """Warnungen zum Nutzungslimit des Abos (leer, solange alles in Ordnung ist)."""
        return limits.current()

    @app.get("/api/usage")
    def usage(profile: Profile = Depends(current_profile)) -> dict:
        """Seite „Nutzung“: Stand des Abo-Limits (nur Warnungen, kein laufender Zähler) und die Bilder dieser Person im Monat."""
        generate = bool(settings.images_enabled and settings.files_enabled and images.providers())
        month = datetime.now().strftime("%Y-%m")
        return {
            "limits": limits.current(),
            "windows": limits.overview(),
            "subscription": settings.backend == "claude" and bool(settings.claude_oauth_token),
            "images": {"enabled": generate, "month": month, "used": store.image_usage(profile.id, month) if generate else 0, "limit": settings.image_limit_month},
            "openai": {
                "enabled": settings.openai_active, "month": month,
                "used": store.token_usage(profile.id, month, "openai") if settings.openai_active else 0,
                "limit": settings.openai_limit_month * 1000,
            },
        }

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
        kind = ""
        if body and body.voice:
            if not voice_allowed(profile):
                raise HTTPException(status_code=403, detail=tr("Sprache ist für dich nicht freigeschaltet."))
            kind, project_id, title = "voice", None, tr("Sprachgespräch")
        if body and body.incognito:
            if not settings.incognito_enabled:
                raise HTTPException(status_code=403, detail=tr("Inkognito-Chats sind ausgeschaltet."))
            if kind or project_id:
                raise HTTPException(status_code=422, detail=tr("Ein Inkognito-Chat gehört in kein Projekt."))
            kind, title = "incognito", tr("Inkognito-Chat")
        chat = store.create_chat(profile.id, title, project_id, kind=kind)
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
    async def update_chat(
        chat_id: str, body: PatchChatBody, profile: Profile = Depends(current_profile)
    ) -> dict:
        current = store.get_chat(profile.id, chat_id)
        if current is None:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        if current.get("kind") == "incognito":  # weder anpinnen noch verschieben noch behalten: er wird beim Schließen gelöscht
            raise HTTPException(status_code=409, detail=tr("Ein Inkognito-Chat lässt sich nicht ändern."))
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
        if body.keep:
            store.set_chat_kind(profile.id, chat_id, "")
        if body.unread is not None:
            store.set_chat_unread(profile.id, chat_id, body.unread)
            if not body.unread:
                notifier.spawn_clear(profile.id, chat_id)  # gelesen: Meldung von den Geräten nehmen
        return store.get_chat(profile.id, chat_id) or {}

    @app.delete("/api/chats/{chat_id}", status_code=204, dependencies=[Depends(write_guard)])
    def delete(chat_id: str, profile: Profile = Depends(current_profile)) -> Response:
        if not store.delete_chat(profile.id, chat_id):
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        chat_allow.discard((profile.id, chat_id))
        github_allow.discard((profile.id, chat_id))
        connector_allow.difference_update({k for k in connector_allow if k[:2] == (profile.id, chat_id)})
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
        if chat.get("kind") == "incognito":
            raise HTTPException(status_code=409, detail=tr("Ein Inkognito-Chat lässt sich nicht exportieren."))
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
        for allowed in (chat_allow, github_allow, connector_allow):
            for key in [k for k in allowed if k[0] == profile.id]:
                allowed.discard(key)
        return {"deleted": count}

    # ------------------------------------------------------------ Chats teilen
    # Eine Freigabe ist ein Schnappschuss: Text zum Zeitpunkt des Teilens (ohne Anhänge, Werkzeugprotokolle und Gedächtnis-Hinweise).
    # „instance“: alle angemeldeten Personen dieser Instanz sehen ihn unter „Geteilt“ und können ihn als Kopie weiterführen.
    # „public“: ein langer, nicht erratbarer Link ohne Anmeldung, nur lesen (siehe build_public_app).

    SHARE_MAX_CHARS = 2_000_000

    def sharing_or_404() -> str:
        if settings.sharing == "off":
            raise HTTPException(status_code=404, detail=tr("Nicht verfügbar"))
        return settings.sharing

    def public_ready() -> bool:
        return settings.sharing == "public" and bool(settings.public_base_url)

    def share_view(row: dict | None) -> dict | None:
        if row is None:
            return None
        out = {"mode": row["mode"], "taken_at": row["taken_at"], "created_at": row["created_at"], "expires_at": row["expires_at"]}
        if row["mode"] == "public":
            out["url"] = f"{settings.public_base_url}/s/{row['token']}"
        return out

    def shared_chat(profile: Profile, chat_id: str) -> dict:
        chat = store.get_chat(profile.id, chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        if chat.get("kind"):
            raise HTTPException(status_code=409, detail=tr("Dieser Chat lässt sich nicht teilen."))
        return chat

    def owner_label(profile_id: str) -> str:
        known = registry.by_id(profile_id) if registry is not None else None
        return (known.label or known.id) if known else profile_id

    @app.get("/api/chats/{chat_id}/share")
    def get_share(chat_id: str, profile: Profile = Depends(current_profile)) -> dict:
        sharing_or_404()
        shared_chat(profile, chat_id)
        return {
            "sharing": settings.sharing, "public_available": public_ready(),
            "instance": share_view(store.share_get(profile.id, chat_id, "instance")),
            "public": share_view(store.share_get(profile.id, chat_id, "public")),
        }

    def take_share(profile: Profile, chat_id: str, mode: str, expires_days: int | None) -> dict:
        sharing_or_404()
        shared_chat(profile, chat_id)
        if mode == "public":
            if settings.sharing != "public":
                raise HTTPException(status_code=403, detail=tr("Öffentliche Links sind nicht erlaubt."))
            if not settings.public_base_url:
                raise HTTPException(status_code=409, detail=tr("Dafür ist der Domain-Zugang nötig, und der ist nicht eingerichtet."))
        snap = store.share_snapshot(profile.id, chat_id)
        if snap is None:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        title, messages = snap
        if not messages:
            raise HTTPException(status_code=422, detail=tr("Der Chat ist noch leer."))
        if sum(len(m["content"]) for m in messages) > SHARE_MAX_CHARS:
            raise HTTPException(status_code=422, detail=tr("Der Chat ist zu lang zum Teilen."))
        row = store.share_upsert(profile.id, chat_id, mode, title, messages, expires_days if mode == "public" else 0)
        return share_view(row) or {}

    @app.post("/api/chats/{chat_id}/share", dependencies=[Depends(write_guard)])
    def create_share(chat_id: str, body: ShareBody, profile: Profile = Depends(current_profile)) -> dict:
        return take_share(profile, chat_id, body.mode, 30 if body.expires_days is None and not store.share_get(profile.id, chat_id, body.mode) else body.expires_days)

    @app.post("/api/chats/{chat_id}/share/refresh", dependencies=[Depends(write_guard)])
    def refresh_share(chat_id: str, body: ShareModeBody, profile: Profile = Depends(current_profile)) -> dict:
        sharing_or_404()
        if store.share_get(profile.id, chat_id, body.mode) is None:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        return take_share(profile, chat_id, body.mode, None)

    @app.delete("/api/chats/{chat_id}/share/{mode}", status_code=204, dependencies=[Depends(write_guard)])
    def revoke_share(chat_id: str, mode: Literal["instance", "public"], profile: Profile = Depends(current_profile)) -> Response:
        if not store.share_delete(profile.id, chat_id, mode):
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        return Response(status_code=204)

    @app.get("/api/shared")
    def list_shared(profile: Profile = Depends(current_profile)) -> list[dict]:
        """Von anderen in dieser Instanz geteilte Chats (nur Titel, Person und Stand)."""
        sharing_or_404()
        return [{"id": r["id"], "title": r["title"], "owner": owner_label(r["profile_id"]), "taken_at": r["taken_at"]} for r in store.shares_for_others(profile.id)]

    @app.get("/api/shared/{share_id}")
    def read_shared(share_id: str, profile: Profile = Depends(current_profile)) -> dict:
        sharing_or_404()
        row = store.share_read(share_id=share_id)
        if row is None:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        return {"id": row["id"], "title": row["title"], "owner": owner_label(row["profile_id"]), "taken_at": row["taken_at"],
                "mine": row["profile_id"] == profile.id, "messages": row["messages"]}

    @app.post("/api/shared/{share_id}/copy", status_code=201, dependencies=[Depends(write_guard)])
    def copy_shared(share_id: str, profile: Profile = Depends(current_profile)) -> dict:
        """Als eigene Kopie weiterführen: ein neuer Chat der Person mit dem geteilten Text. Er läuft mit ihren Rechten und ihrem Gedächtnis."""
        sharing_or_404()
        row = store.share_read(share_id=share_id)
        if row is None or not row["messages"]:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        return store.import_chat(profile.id, _title_from(tr("Kopie: {title}", title=row["title"])), row["messages"])

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
        no_text: list[str] = []
        try:
            data = knowlib.decode_upload(body.data)
            body.data = ""
            try:
                items, skipped = await asyncio.to_thread(knowlib.expand, body.name, data)
            except knowlib.KnowledgeError as exc:
                # Bilder, Scans und andere Dateien ohne Text bleiben als Original im Projekt (Platzhalter im Inhaltsverzeichnis)
                if data.startswith(b"PK\x03\x04") or not data or len(data) > pfiles.FILE_MAX_BYTES:  # ZIP und kaputte Office-Dateien: Meldung wie bisher
                    raise
                try:
                    saved = pfiles.save(store, profile.id, project_id, body.name, data, origin="upload", text="")
                except pfiles.ProjectFileError as inner:
                    raise knowlib.KnowledgeError(str(inner)) from None
                return {"added": [saved.name], "skipped": [], "no_text": [saved.name]}
        except knowlib.KnowledgeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        existing = {f["name"].lower(): f["size"] for f in store.list_knowledge(profile.id, project_id) or []}
        count, chars = len(existing), sum(existing.values())
        added: list[str] = []
        single = len(items) == 1 and not knowlib._is_zip_archive(data) and len(data) <= pfiles.FILE_MAX_BYTES
        for name, text in items:
            if single:  # eine einzelne Datei (Word, Excel, PDF, Text): das Original bleibt zusätzlich erhalten
                try:
                    saved = pfiles.save(store, profile.id, project_id, name, data, origin="upload", text=text)
                except pfiles.ProjectFileError as exc:
                    skipped.append({"name": name, "reason": str(exc)})
                else:
                    added.append(saved.name)
                continue
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
        return {"added": added, "skipped": skipped[:50], "no_text": no_text}

    @app.get("/api/projects/{project_id}/knowledge/{knowledge_id}/file")
    def download_project_file(project_id: str, knowledge_id: int, profile: Profile = Depends(current_profile)) -> FileResponse:
        """Das Original einer Projektdatei herunterladen (nur der Besitzer des Projekts)."""
        found = store.knowledge_file_open(profile.id, project_id, knowledge_id)
        if found is None:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        meta, path = found
        return FileResponse(
            path, media_type=meta["mime"] or "application/octet-stream", filename=meta["name"].rsplit("/", 1)[-1], content_disposition_type="attachment",
            headers={"Content-Security-Policy": "sandbox; default-src 'none'", "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
        )

    @app.post("/api/chats/{chat_id}/files/{file_id}/to-project", dependencies=[Depends(write_guard)])
    async def file_to_project(chat_id: str, file_id: str, profile: Profile = Depends(current_profile)) -> dict:
        """Eine Datei aus diesem Chat im Projekt des Chats ablegen (Knopf an der Dateikarte)."""
        if store.get_chat(profile.id, chat_id) is None:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        project_id = store.chat_project_id(profile.id, chat_id)
        if project_id is None:
            raise HTTPException(status_code=422, detail=tr("Dieser Chat gehört zu keinem Projekt."))
        found = store.outfile_open(profile.id, file_id)
        if found is None or not any(f["id"] == file_id for f in store.outfile_list(profile.id, chat_id)):
            raise HTTPException(status_code=404, detail=tr("Die Datei ist abgelaufen oder gehört nicht zu diesem Chat."))
        meta, path = found
        try:
            saved = await asyncio.to_thread(
                lambda: pfiles.save(store, profile.id, project_id, meta["name"], path.read_bytes(), origin="ai")
            )
        except pfiles.ProjectFileError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        return {"name": saved.name, "replaced": saved.replaced, "has_text": saved.has_text}

    @app.delete("/api/projects/{project_id}/knowledge/{knowledge_id}", status_code=204, dependencies=[Depends(write_guard)])
    def delete_knowledge(project_id: str, knowledge_id: int, profile: Profile = Depends(current_profile)) -> Response:
        if not store.delete_knowledge(profile.id, project_id, knowledge_id):
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        return Response(status_code=204)

    # ------------------------------------------------------------------- Skills

    def skill_view(row: dict) -> dict:
        return {
            "id": row["id"], "name": row["name"], "description": row["description"], "enabled": bool(row["enabled"]),
            "origin": row["origin"], "imported": row["origin"] == "imported", "size": row["size"], "files": row["files"],
            "updated_at": row["updated_at"],
        }

    def store_skill(profile: Profile, pkg: skilllib.Package, origin: str) -> dict:
        if not store.skill_exists(profile.id, pkg.name) and store.skill_count(profile.id) >= skilllib.PER_PERSON:
            raise HTTPException(status_code=422, detail=tr("Es sind höchstens {n} Skills je Person möglich.", n=skilllib.PER_PERSON))
        return skill_view(store.skill_save(profile.id, pkg.name, pkg.description, pkg.files, origin=origin))

    @app.get("/api/skills")
    def list_skills(profile: Profile = Depends(current_profile)) -> dict:
        rows = store.skill_list(profile.id)
        have = {r["name"]: r["origin"] for r in rows}
        return {
            "standard": skilllib.standard_list(),
            "recommended": [{**r, "installed": have.get(r["name"]) == "recommended", "taken": r["name"] in have and have[r["name"]] != "recommended"} for r in skilllib.recommended_list()],
            "categories": skilllib.recommended_categories(),
            "skills": [skill_view(r) for r in rows],
            "max": skilllib.PER_PERSON,
        }

    @app.get("/api/skills/standard/{name}")
    def standard_skill(name: str, profile: Profile = Depends(current_profile)) -> dict:
        text = skilllib.standard_text(name)
        if text is None:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        return {"name": name, "text": text}

    @app.get("/api/skills/recommended/{skill_id}")
    def recommended_skill(skill_id: str, profile: Profile = Depends(current_profile)) -> dict:
        pkg = skilllib.recommended_package(skill_id)
        if pkg is None:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        return {
            "id": skill_id, "skill_md": pkg.files["SKILL.md"],
            "files_list": [{"path": p, "size": len(t)} for p, t in pkg.files.items()],
            "license_text": pkg.files.get("LICENSE.txt", ""),
        }

    @app.get("/api/skills/recommended/{skill_id}/file")
    def recommended_skill_file(skill_id: str, path: str, profile: Profile = Depends(current_profile)) -> dict:
        pkg = skilllib.recommended_package(skill_id)
        if pkg is None or path not in pkg.files:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        return {"path": path, "text": pkg.files[path]}

    @app.post("/api/skills/recommended/{skill_id}", dependencies=[Depends(write_guard)])
    def add_recommended_skill(skill_id: str, profile: Profile = Depends(current_profile)) -> dict:
        pkg = skilllib.recommended_package(skill_id)
        if pkg is None:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        if store.skill_exists(profile.id, pkg.name):
            raise HTTPException(status_code=409, detail=tr("Ein Skill mit diesem Namen gibt es schon."))
        return store_skill(profile, pkg, "recommended")

    def skill_preview(pkg: skilllib.Package, profile: Profile) -> dict:
        _, _, text = skilllib.parse_skill_md(pkg.files["SKILL.md"])
        return {
            "name": pkg.name, "description": pkg.description, "size": pkg.size,
            "files": [{"path": p, "size": len(t)} for p, t in sorted(pkg.files.items())],
            "warnings": pkg.warnings, "skipped": pkg.skipped[:50],
            "replaces": store.skill_exists(profile.id, pkg.name),
            "excerpt": text.strip()[:600],
        }

    @app.post("/api/skills/preview", dependencies=[Depends(write_guard)])
    async def preview_skill(body: SkillUploadBody, profile: Profile = Depends(current_profile)) -> dict:
        try:
            pkg = await asyncio.to_thread(skilllib.parse_upload, body.name, skilllib.decode(body.data))
        except skilllib.SkillError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        body.data = ""
        return skill_preview(pkg, profile)

    @app.post("/api/skills/github", dependencies=[Depends(write_guard)])
    async def preview_github_skill(body: SkillGithubBody, profile: Profile = Depends(current_profile)) -> dict:
        """Skill von einem öffentlichen GitHub-Link holen und prüfen; gespeichert wird erst nach der Vorschau (``POST /api/skills`` mit ``data``)."""
        try:
            got = await skills_github.fetch(body.url)
            pkg = await asyncio.to_thread(skilllib.parse_upload, "skill.zip", got.data)
        except skilllib.SkillError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        pkg.skipped = [*got.skipped, *pkg.skipped]
        return {**skill_preview(pkg, profile), "data": base64.b64encode(got.data).decode("ascii"), "file": f"{pkg.name}.skill", "source": got.source}

    @app.post("/api/skills", dependencies=[Depends(write_guard)])
    async def import_skill(body: SkillUploadBody, profile: Profile = Depends(current_profile)) -> dict:
        try:
            pkg = await asyncio.to_thread(skilllib.parse_upload, body.name, skilllib.decode(body.data))
        except skilllib.SkillError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        body.data = ""
        return {**store_skill(profile, pkg, "imported"), "warnings": pkg.warnings, "skipped": pkg.skipped[:50]}

    @app.post("/api/skills/new", dependencies=[Depends(write_guard)])
    def new_skill(body: SkillWriteBody, profile: Profile = Depends(current_profile)) -> dict:
        try:
            pkg = skilllib.build(body.name, body.description, body.instructions)
        except skilllib.SkillError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        return store_skill(profile, pkg, "own")

    @app.get("/api/skills/{skill_id}")
    def get_skill(skill_id: int, profile: Profile = Depends(current_profile)) -> dict:
        row = store.skill_get(profile.id, skill_id)
        if row is None:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        return {**skill_view(row), "files_list": [{"path": p, "size": len(t)} for p, t in row["files"].items()], "skill_md": row["files"].get("SKILL.md", "")}

    @app.get("/api/skills/{skill_id}/file")
    def get_skill_file(skill_id: int, path: str, profile: Profile = Depends(current_profile)) -> dict:
        row = store.skill_get(profile.id, skill_id)
        if row is None or path not in row["files"]:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        return {"path": path, "text": row["files"][path]}

    @app.get("/api/skills/{skill_id}/export")
    def export_skill(skill_id: int, profile: Profile = Depends(current_profile)) -> Response:
        row = store.skill_get(profile.id, skill_id)
        if row is None:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        data = skilllib.to_zip(row["name"], row["files"])
        return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{row["name"]}.skill"'})

    @app.patch("/api/skills/{skill_id}", dependencies=[Depends(write_guard)])
    def patch_skill(skill_id: int, body: SkillPatchBody, profile: Profile = Depends(current_profile)) -> dict:
        if not store.skill_set_enabled(profile.id, skill_id, body.enabled):
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        return {"id": skill_id, "enabled": body.enabled}

    @app.delete("/api/skills/{skill_id}", status_code=204, dependencies=[Depends(write_guard)])
    def delete_skill(skill_id: int, profile: Profile = Depends(current_profile)) -> Response:
        if not store.skill_delete(profile.id, skill_id):
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        return Response(status_code=204)

    # ------------------------------------------------------------------ Plugins

    plugin_service = pluginlib.PluginService(store, connectors)
    plugin_limit = RateLimiter(30, 600)  # Hinzufügen und GitHub-Abruf: nicht im Sekundentakt

    def plugin_call_limit(profile: Profile) -> None:
        if not plugin_limit.allow(profile.id):
            raise HTTPException(status_code=429, detail=tr("Zu viele Versuche. Bitte in ein paar Minuten noch einmal."))

    def plugin_fail(exc: Exception) -> HTTPException:
        return HTTPException(status_code=getattr(exc, "status", 422), detail=str(exc))

    @app.get("/api/plugins")
    def plugins_list(profile: Profile = Depends(current_profile)) -> dict:
        return {
            "catalog": plugin_service.catalog(profile.id),
            "mine": plugin_service.mine(profile.id),
            "checked": package_catalog.checked(),
            "max": pluginlib.MAX_PLUGINS,
            "connector_access": connectors.level(profile.id) >= 1,
            "can_connectors": connectors.can_create(profile.id)["private"],
            "auth_choices": list(pluginlib.AUTH_CHOICES),
        }

    @app.post("/api/plugins/catalog/{plugin_id}", dependencies=[Depends(write_guard)])
    async def plugin_install(plugin_id: str, profile: Profile = Depends(current_profile)) -> dict:
        plugin_call_limit(profile)
        try:
            return await plugin_service.install(profile.id, plugin_id)
        except pluginlib.PluginError as exc:
            raise plugin_fail(exc) from None

    @app.post("/api/plugins/github", dependencies=[Depends(write_guard)])
    async def plugin_github_preview(body: SkillGithubBody, profile: Profile = Depends(current_profile)) -> dict:
        """Claude-Plugin von einem öffentlichen GitHub-Link holen und prüfen; übernommen wird erst nach der Vorschau (``POST /api/plugins/import``)."""
        plugin_call_limit(profile)
        try:
            got = await plugins_github.fetch(body.url)
            preview = await asyncio.to_thread(plugin_service.preview_import, profile.id, got.data, pluginlib.fallback_name(got.source), got.source)
        except (skilllib.SkillError, pluginlib.PluginError) as exc:
            raise plugin_fail(exc) from None
        preview["skipped"] = [*got.skipped, *preview["skipped"]][:50]
        preview["ignored"] = got.ignored
        return {**preview, "data": base64.b64encode(got.data).decode("ascii")}

    @app.post("/api/plugins/import", dependencies=[Depends(write_guard)])
    async def plugin_import(body: PluginImportBody, profile: Profile = Depends(current_profile)) -> dict:
        plugin_call_limit(profile)
        try:
            raw = skilllib.decode(body.data)
            body.data = ""
            return await plugin_service.commit_import(
                profile.id, raw, pluginlib.fallback_name(body.source), body.source, body.skills, [s.model_dump() for s in body.servers],
            )
        except (skilllib.SkillError, pluginlib.PluginError) as exc:
            raise plugin_fail(exc) from None

    @app.delete("/api/plugins/{plugin_id}", dependencies=[Depends(write_guard)])
    def plugin_remove(plugin_id: int, profile: Profile = Depends(current_profile)) -> dict:
        try:
            return plugin_service.remove(profile.id, plugin_id)
        except pluginlib.PluginError as exc:
            raise plugin_fail(exc) from None

    # --------------------------------------------------------------- Gedächtnis

    def memory_enabled_or_404() -> None:
        if not settings.memory_enabled:
            raise HTTPException(status_code=404, detail=tr("Nicht verfügbar"))

    @app.get("/api/memory")
    def get_memory(profile: Profile = Depends(current_profile)) -> dict:
        memory_enabled_or_404()
        names = {p.id: (p.label or p.id) for p in settings.profiles}
        household = [{**m, "by": names.get(m["author"], "")} for m in store.memory_list("household", auto=False)]
        projects = []
        for pr in store.list_projects(profile.id):
            entries = store.project_memory_list(profile.id, pr["id"]) or []
            projects.append({"id": pr["id"], "name": pr["name"], "entries": entries})
        out = {
            "household": household,
            "person": store.memory_list("person", profile.id),
            "projects": projects,
            "household_write": household_writable(profile),
            "instructions": store.profile_instructions(profile.id),
            "instructions_max": INSTRUCTIONS_MAX,
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

    def project_memory_check(profile: Profile, project_id: str) -> None:
        """Das Projekt muss dieser Person gehören; sonst 404 (wie bei allen Projektdaten)."""
        if not project_id or store.project_memory_list(profile.id, project_id) is None:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))

    def memory_write_rules(profile: Profile, scope: str, project_id: str, topic: str, content: str, secrets: bool = True) -> None:
        if scope == "household" and not household_writable(profile):
            raise HTTPException(status_code=403, detail=tr("Das Haushaltsgedächtnis darfst du nicht ändern."))
        if scope == "project":
            project_memory_check(profile, project_id)
        if not 2 <= len(topic) <= TOPIC_MAX:
            raise HTTPException(status_code=422, detail=tr("Thema fehlt"))
        if _RESERVED.match(topic):
            raise HTTPException(status_code=422, detail=tr(RESERVED_TEXT))
        if secrets and (_SECRET.search(topic) or _SECRET.search(content)):
            raise HTTPException(status_code=422, detail=tr("Zugangsdaten, Schlüssel und Kontonummern werden nicht im Gedächtnis gespeichert."))

    def memory_put(profile: Profile, scope: str, project_id: str, topic: str, content: str, origin: str) -> dict:
        if scope == "project":
            if store.project_memory_get(profile.id, project_id, topic) is None and store.project_memory_count(profile.id, project_id) >= PROJECT_LIMIT:
                raise HTTPException(status_code=422, detail=tr("Das Projektgedächtnis ist voll ({n} Einträge).", n=PROJECT_LIMIT))
            return store.project_memory_save(profile.id, project_id, topic, content, profile.id, origin) or {}
        return store.memory_save(scope, profile.id, topic, content, profile.id, origin)

    @app.post("/api/memory", dependencies=[Depends(write_guard)])
    def save_memory(body: MemoryBody, profile: Profile = Depends(current_profile)) -> dict:
        memory_enabled_or_404()
        topic = " ".join(body.topic.split())
        content = body.content.strip()
        memory_write_rules(profile, body.scope, body.project_id, topic, content, secrets=False)  # eigene Einträge der Person: wie bisher keine Prüfung
        return memory_put(profile, body.scope, body.project_id, topic, content, "manual")

    @app.delete("/api/projects/{project_id}/memory/{memory_id}", status_code=204, dependencies=[Depends(write_guard)])
    def delete_project_memory(project_id: str, memory_id: int, profile: Profile = Depends(current_profile)) -> Response:
        memory_enabled_or_404()
        project_memory_check(profile, project_id)
        if not store.project_memory_delete(profile.id, project_id, memory_id):
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        return Response(status_code=204)

    @app.post("/api/memory/undo", dependencies=[Depends(write_guard)])
    def undo_memory(body: MemoryUndoBody, profile: Profile = Depends(current_profile)) -> dict:
        """„Rückgängig“ unter einer Antwort: nur, solange der Eintrag noch so ist, wie die KI ihn hinterlassen hat."""
        memory_enabled_or_404()
        topic = " ".join(body.topic.split())
        if body.scope == "household" and not household_writable(profile):
            raise HTTPException(status_code=403, detail=tr("Das Haushaltsgedächtnis darfst du nicht ändern."))
        if body.scope == "project":
            project_memory_check(profile, body.project_id)
            current = store.project_memory_get(profile.id, body.project_id, topic)
        else:
            current = store.memory_get(body.scope, profile.id, topic)
        if (current["content"] if current else None) != body.now:
            raise HTTPException(status_code=409, detail=tr("Der Eintrag wurde inzwischen geändert. Öffne das Gedächtnis, um ihn anzupassen."))
        if body.prev is None:  # die KI hat den Eintrag neu angelegt: wieder entfernen
            if body.scope == "project":
                store.project_memory_delete(profile.id, body.project_id, topic=topic)
            else:
                store.memory_delete_topic(body.scope, profile.id, topic)
            return {"restored": False}
        memory_write_rules(profile, body.scope, body.project_id, topic, body.prev)
        memory_put(profile, body.scope, body.project_id, topic, body.prev, "")
        return {"restored": True}

    @app.put("/api/memory/instructions", dependencies=[Depends(write_guard)])
    def save_instructions(body: InstructionsBody, profile: Profile = Depends(current_profile)) -> dict:
        """„Meine Anweisungen“: gelten in allen Chats dieser Person (Projektanweisungen kommen dazu)."""
        memory_enabled_or_404()
        if _SECRET.search(body.text):
            raise HTTPException(status_code=422, detail=tr("Zugangsdaten, Schlüssel und Kontonummern gehören nicht in die Anweisungen."))
        return {"text": store.set_profile_instructions(profile.id, body.text)}

    @app.post("/api/memory/import/preview", dependencies=[Depends(write_guard)])
    async def preview_memory_import(body: MemoryImportBody, profile: Profile = Depends(current_profile)) -> dict:
        """Export von Claude (ZIP oder Markdown) einlesen und Vorschläge zeigen. Es wird nichts gespeichert."""
        memory_enabled_or_404()
        if not import_limit.allow(profile.id):
            raise HTTPException(status_code=429, detail=tr("Bitte etwas später noch einmal versuchen."))
        try:
            data = memlib.decode(body.data)
            body.data = ""
            files, skipped = await asyncio.to_thread(memlib.read_upload, body.name, data)
            found = await asyncio.to_thread(memlib.parse, files)
        except memlib.ImportError_ as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        if not found["entries"] and not found["instructions"]["text"]:
            raise HTTPException(status_code=422, detail=tr("In der Datei wurde nichts gefunden, das sich als Gedächtnis oder Anweisung übernehmen lässt."))
        for entry in found["entries"]:
            entry["exists"] = {
                "person": store.memory_has_topic("person", profile.id, entry["topic"]),
                "household": store.memory_has_topic("household", profile.id, entry["topic"]),
            }
        return {
            **found,
            "skipped": [*skipped, *found["skipped"]][:memlib.MAX_SKIPPED],
            "current_instructions": store.profile_instructions(profile.id),
            "instructions_max": INSTRUCTIONS_MAX,
            "free": {
                "person": max(0, PERSON_LIMIT - store.memory_count("person", profile.id)),
                "household": max(0, HOUSEHOLD_LIMIT - store.memory_count("household")),
            },
            "household_write": household_writable(profile),
        }

    @app.post("/api/memory/import", dependencies=[Depends(write_guard)])
    def commit_memory_import(body: MemoryImportCommit, profile: Profile = Depends(current_profile)) -> dict:
        """Die in der Vorschau gewählten (und eventuell geänderten) Einträge speichern. Alles wird hier noch einmal geprüft."""
        memory_enabled_or_404()
        if not import_limit.allow(profile.id):
            raise HTTPException(status_code=429, detail=tr("Bitte etwas später noch einmal versuchen."))
        if body.scope == "household" and body.entries and not household_writable(profile):
            raise HTTPException(status_code=403, detail=tr("Das Haushaltsgedächtnis darfst du nicht ändern."))
        text = (body.instructions or "").strip()
        merged = ""
        if text:
            if _SECRET.search(text):
                raise HTTPException(status_code=422, detail=tr("Zugangsdaten, Schlüssel und Kontonummern gehören nicht in die Anweisungen."))
            current = store.profile_instructions(profile.id)
            merged = f"{current}\n\n{text}" if body.instructions_mode == "append" and current else text
            if len(merged) > INSTRUCTIONS_MAX:
                raise HTTPException(
                    status_code=422,
                    detail=tr("Die Anweisungen wären zu lang (höchstens {n} Zeichen). Kürze sie oder ersetze die bisherigen.", n=INSTRUCTIONS_MAX),
                )
        limit = HOUSEHOLD_LIMIT if body.scope == "household" else PERSON_LIMIT
        free = limit - store.memory_count(body.scope, profile.id)
        saved = replaced = 0
        skipped: list[dict] = []
        for entry in body.entries:
            topic = " ".join(entry.topic.split())
            content = entry.content.strip()
            reason = ""
            if not 2 <= len(topic) <= TOPIC_MAX:
                reason = tr("Thema braucht 2 bis {n} Zeichen", n=TOPIC_MAX)
            elif not 3 <= len(content) <= CONTENT_MAX:
                reason = tr("Text braucht 3 bis {n} Zeichen", n=CONTENT_MAX)
            elif _RESERVED.match(topic):
                reason = tr("Thema ist für den Smarthome-Überblick reserviert")
            elif _SECRET.search(topic) or _SECRET.search(content):
                reason = tr("enthält vermutlich Zugangsdaten oder Kontonummern")
            else:
                exists = store.memory_has_topic(body.scope, profile.id, topic)
                if exists and not entry.replace:
                    reason = tr("gibt es schon")
                elif not exists and free <= 0:
                    reason = tr("Gedächtnis ist voll ({n} Einträge)", n=limit)
                else:
                    store.memory_save(body.scope, profile.id, topic, content, profile.id, "import")
                    if exists:
                        replaced += 1
                    else:
                        saved += 1
                        free -= 1
            if reason:
                skipped.append({"name": topic[:TOPIC_MAX] or "?", "reason": reason})
        if text:
            store.set_profile_instructions(profile.id, merged)
        return {"saved": saved, "replaced": replaced, "skipped": skipped[:memlib.MAX_SKIPPED], "instructions": bool(text)}

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
            if mode == "phone" and not notifier.available:
                raise HTTPException(status_code=422, detail=tr("Home Assistant ist nicht verbunden."))
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
        if chat.get("kind") == "incognito" or len(history) < 2 or history[0]["role"] != "user":
            return chat  # Inkognito: kein zusätzlicher Aufruf der KI nur für einen Titel
        first, answer = history[0]["content"], history[1]["content"]
        provisional = _title_from(_title_source(first, history[0].get("attachments")))
        generate = getattr(backend, "title", None)
        if chat["title"] != provisional or generate is None:
            return chat
        new_title = None
        # Titel erzeugt der Anbieter, bei dem der Chat läuft (ChatGPT-Chats gehen nie an Claude)
        wanted = chat.get("model") if chat.get("model") == AUTO_MODEL or chat.get("model") in model_ids else ""
        title_model = concrete_model(wanted or user_default_model(profile_id))
        extra_args = {"model": title_model} if provider_of(title_model) == "openai" else {}
        try:
            async with title_lock, asyncio.timeout(TITLE_TIMEOUT):
                new_title = await generate(_title_source(first, history[0].get("attachments")), answer, **extra_args)
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
        if not text and not body.files:
            raise HTTPException(status_code=422, detail=tr("Leere Nachricht"))
        spoken = body.voice
        if spoken:
            if not voice_allowed(profile):
                raise HTTPException(status_code=403, detail=tr("Sprache ist für dich nicht freigeschaltet."))
            if not text or body.files or body.quote or body.edit_message_id is not None:
                raise HTTPException(status_code=422, detail=tr("Gesprochene Nachrichten haben keine Anhänge."))
        text = quotes.with_quote(body.quote, text) if text else ""
        history = store.list_messages(profile.id, chat_id)
        if history is None:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        try:
            files = await asyncio.to_thread(filelib.parse, [(f.name, f.data) for f in body.files])
        except filelib.AttachmentError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        for att, sent in zip(files, body.files):
            att.pasted = bool(sent.pasted) and att.kind == "text" and att.shown_kind is None
        body.files.clear()  # Base64-Kopien der Anfrage nicht länger festhalten
        # Hochgeladene Dateien früherer Nachrichten liegen nicht mehr vor: Claude bekommt nur den Hinweis, dass es sie gab.
        # Eingefügte Texte stehen dagegen im Chat und gehen wieder mit.
        files_kept = settings.files_enabled and settings.files_edit
        history = [{**m, "content": filelib.history_content(m, files_kept)} for m in history]
        # Eingefügter Text stammt von der Person selbst (wie getippter Text) und gilt nicht als fremder Inhalt.
        foreign_files = [f for f in files if not f.pasted]
        key = (profile.id, chat_id)
        imported = bool((store.get_chat(profile.id, chat_id) or {}).get("imported"))  # Verlauf aus einem geteilten Chat: fremder Inhalt
        previous = live_run(key)
        if previous and not previous.finished:
            raise HTTPException(status_code=409, detail=tr("In diesem Chat läuft bereits eine Antwort"))
        if active_runs() >= MAX_PARALLEL:
            raise HTTPException(status_code=429, detail=tr("Gerade zu viele Anfragen, bitte kurz warten"))
        effort = "low" if spoken else (body.effort or settings.default_effort)
        chat = store.get_chat(profile.id, chat_id) or {}
        incognito = chat.get("kind") == "incognito"
        if incognito and not settings.incognito_enabled:
            raise HTTPException(status_code=403, detail=tr("Inkognito-Chats sind ausgeschaltet."))
        requested_model = (body.model or "").strip()
        if requested_model and requested_model != AUTO_MODEL and requested_model not in model_ids:
            raise HTTPException(status_code=422, detail=tr("Unbekanntes Modell"))
        # Vorrang: Wahl in diesem Chat, dann Standardmodell der Person, dann das in der App eingestellte Modell („Auto“)
        saved_model = chat.get("model") if chat.get("model") == AUTO_MODEL or chat.get("model") in model_ids else ""
        chosen_model = concrete_model(requested_model or saved_model or user_default_model(profile.id))
        model = chosen_model if chosen_model != settings.model else None  # None = Standard-Modell
        if spoken:  # gesprochen: immer das schnelle Modell (Claude), die Wahl des Chats bleibt unberührt
            requested_model = ""
            chosen_model = settings.voice_model
            model = settings.voice_model if settings.voice_model != settings.model else None
        provider = provider_of(chosen_model)
        # Wechsel des Modells mitten im Chat: der Verlauf (nur der Text) geht an das neue Modell, das bekommt einen Hinweis darauf
        previous_model = concrete_model(saved_model or user_default_model(profile.id))
        switched_from = previous_model if history and not spoken and requested_model and chosen_model != previous_model else ""
        web_on = settings.web_level(profile) == "on" and body.web is not False
        first_exchange = not history and chat.get("title") in DEFAULT_TITLES
        metas = [f.meta() for f in files]
        instructions = store.chat_instructions(profile.id, chat_id)
        extra: dict = {"on_limit": limits.update}
        if model:
            extra["model"] = model
        usage_month = datetime.now().strftime("%Y-%m")
        token_limit = settings.openai_limit_month * 1000
        if provider == "openai":
            extra["on_usage"] = lambda tokens: store.token_usage_add(profile.id, usage_month, tokens, "openai")
        if files:
            extra["attachments"] = files
        if instructions:
            extra["instructions"] = instructions
        personal = store.profile_instructions(profile.id)
        if personal:
            extra["personal_instructions"] = personal
        summarize = getattr(backend, "summarize", None)
        # Zusammenfassungen erzeugt der Anbieter, bei dem der Chat läuft
        summary_args = {"model": chosen_model, "on_usage": extra["on_usage"]} if provider == "openai" else {}
        level = ha_level(profile)
        if spoken and level == "write":
            level = "execute"  # per Sprache nur bedienen, nichts umbauen

        # Frage bearbeiten: die alte Frage und alles danach wird entfernt (bei einem Fehler ohne Antwort kommt es zurück).
        cut = None
        if body.edit_message_id is not None:
            cut = store.cut_from(profile.id, chat_id, body.edit_message_id)
            if cut is None:
                raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
            history = [m for m in history if m["id"] < body.edit_message_id]

        # Die Frage steht ab jetzt in der Datenbank: Seite neu laden oder Chat wechseln verliert sie nicht mehr.
        question = store.add_message(profile.id, chat_id, "user", text, metas)
        if question is None:
            if cut:
                store.restore_cut(profile.id, chat_id, cut)
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        provisional = _title_from(_title_source(text, metas))
        if first_exchange:
            store.rename_chat(profile.id, chat_id, provisional)
        if requested_model:
            # Entspricht die Wahl dem, was ohnehin gilt (Standardmodell der Person), wird nichts gemerkt
            same = concrete_model(requested_model) == concrete_model(user_default_model(profile.id))
            store.set_chat_model(profile.id, chat_id, "" if same else requested_model)
        asked = text or ONLY_FILES_PROMPT  # was Claude zu sehen bekommt; gespeichert und angezeigt wird der leere Text
        run = Run(key, asked, first_exchange)
        runs[key] = run

        def withdraw_question() -> None:
            """Keine Antwort entstanden: Frage wieder zurücknehmen, damit sie erneut gesendet werden kann."""
            store.delete_message(profile.id, chat_id, question["id"])
            if cut:
                store.restore_cut(profile.id, chat_id, cut)
            if first_exchange:
                store.replace_title_if(profile.id, chat_id, provisional, chat.get("title") or default_title())

        async def ask_about(topic: str, label: str, details: str, offer_chat: bool) -> str:
            """Rückfrage an die Person: wartet, bis im Chat Zulassen oder Ablehnen gedrückt wurde (topic: ha, memory, github)."""
            if spoken:
                return "deny"  # per Sprache gibt es keine Rückfragen: heikle Aktionen gehen nur getippt
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

        async def ask_image(label: str, details: str, offer_chat: bool) -> str:
            return await ask_about("image", label, details, offer_chat)

        async def ask_connector(label: str, details: str, offer_chat: bool) -> str:
            return await ask_about("connector", label, details, offer_chat)

        images_enabled = settings.files_enabled and settings.images_enabled and not spoken
        stored_files: list[str] = []
        skipped_files: list[str] = []
        if files and (files_kept or images_enabled):
            stored_files, skipped_files = await asyncio.to_thread(
                filelib.persist, store, profile.id, chat_id, files, settings.files_keep_days, MAX_PROFILE_BYTES, images_enabled, files_kept
            )
        image_names = {f.name for f in files if f.kind == "image"}

        specs = []
        if level in ("read", "execute", "write") and ha is not None:
            toolbox = HaToolbox(
                ha, level,
                limit_to_exposed=settings.ha_limit_to_exposed,
                confirm_writes=settings.ha_write_confirm == "ask",
                # Dateien können eingeschleuste Anweisungen enthalten: dann nichts ohne ausdrückliches Zulassen
                force_confirm=lambda: bool(files) or imported or any(a["kind"] in ("web", "gh-read", "file-read", "skill-ext", "mcp-read", "mcp-write") for a in run.actions.values()),
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
            chat_id=chat_id,
            memory_enabled=settings.memory_enabled and not incognito,  # Inkognito: weder lesen noch schreiben, auch nicht Haushalt und Projekt
            household_write=household_writable(profile),
            force_confirm=bool(foreign_files) or imported,
            ask=ask_memory, record=run.push, next_id=run.next_tool_id,
            tainted=lambda: any(a["kind"] in TAINTING_KINDS for a in run.actions.values()),
            overview=overview_allowed(profile),
        )
        specs += context.specs()
        if settings.files_enabled and not spoken:
            specs += OutboxToolbox(
                store, profile.id, chat_id, record=run.push, next_id=run.next_tool_id,
                keep_days=settings.files_keep_days, author=settings.app_name, edit=settings.files_edit, auto_guides=True,
                user_skills=bool(context.skills),
            ).specs()
        image_box = None
        if images_enabled:
            image_box = ImageToolbox(
                store, profile.id, chat_id, images, record=run.push, next_id=run.next_tool_id,
                keep_days=settings.files_keep_days, limit_month=settings.image_limit_month, ask=ask_image,
                # Gelesene Web- oder Dateiinhalte (und angehängte Dokumente) können Anweisungen enthalten: dann vor jedem Bild nachfragen
                tainted=lambda: imported or any(f.kind != "image" for f in foreign_files) or any(a["kind"] in TAINTING_KINDS for a in run.actions.values()),
            )
            specs += image_box.specs()
        gh_level = "none" if spoken else github_level(profile)
        if gh_level != "none":
            gh_api = accounts.api_for(profile.id)
            gh_policy = accounts.policy_for(profile.id)
            def attachment_bytes(name: str) -> bytes | None:
                """Datei dieses Chats für einen Commit: erzeugte Datei oder Anhang dieser Nachricht (Word/Excel-Anhänge liegen nur als Text vor)."""
                made = store.outfile_bytes(profile.id, chat_id, name)
                if made is not None:
                    return made
                return next((f.data for f in files if f.name == name and f.original_size is None), None)

            specs += GithubToolbox(
                gh_api, gh_level,
                policy=gh_policy,
                confirm_writes=settings.github_write_confirm == "ask",
                force_confirm=lambda: bool(foreign_files) or imported or any(a["kind"] in TAINTING_KINDS - {"gh-write"} for a in run.actions.values()),
                ask=ask_github, record=run.push, chat_allowed=lambda: key in github_allow, allow_chat=lambda: github_allow.add(key),
                next_id=run.next_tool_id, file_bytes=attachment_bytes,
            ).specs()
        connector_box = ConnectorToolbox(
            connectors, profile.id,
            confirm_writes=settings.connector_write_confirm == "ask",
            force_confirm=lambda: bool(foreign_files) or imported or any(a["kind"] in TAINTING_KINDS - {"mcp-write"} for a in run.actions.values()),
            ask=ask_connector, record=run.push,
            chat_allowed=lambda cid: (profile.id, chat_id, cid) in connector_allow,
            allow_chat=lambda cid: connector_allow.add((profile.id, chat_id, cid)),
            next_id=run.next_tool_id,
        )
        connector_specs = [] if spoken else connector_box.specs()
        specs += connector_specs
        if web_on:
            specs += WebToolbox(run.push, run.next_tool_id).specs()
            extra.update(web=True, record=run.push, next_id=run.next_tool_id)
        if specs:
            extra["tools"] = specs
        extra["note"] = context.note([p.label or p.id for p in settings.profiles], level, any(s.name.startswith("ha_") for s in specs))
        if incognito:
            extra["note"] += "\n" + INCOGNITO_NOTE
        if switched_from:
            extra["note"] += "\n" + tr(
                "Dieser Chat lief bisher mit {old}, ab dieser Nachricht antwortest du ({new}). Die früheren Antworten im Verlauf stammen von {old}. Ergebnisse von Werkzeugen aus früheren Antworten liegen nicht mehr vor; lies bei Bedarf noch einmal nach.",
                old=model_label(switched_from), new=model_label(chosen_model),
            )
        if any(s.name == "design_guide" for s in specs):
            extra["note"] += "\n" + DESIGN_NOTE
        if any(s.name == "file_edit" for s in specs):
            extra["note"] += "\n" + FILES_NOTE
            if [n for n in stored_files if n not in image_names]:
                extra["note"] += " In dieser Nachricht angehängt und im Chat abgelegt: " + ", ".join(n for n in stored_files if n not in image_names) + "."
            if skipped_files:
                extra["note"] += " Nicht bearbeitbar: " + "; ".join(skipped_files) + "."
        if image_box is not None:
            extra["note"] += "\n" + IMAGES_NOTE + image_box.usage_note()
            attached_images = [n for n in stored_files if n in image_names]
            if attached_images:
                extra["note"] += " In dieser Nachricht angehängte Bilder (als reference nutzbar): " + ", ".join(attached_images) + "."
            if not image_box.generate_enabled:
                extra["note"] += " Für Fotos und Kunstbilder ist kein Bildanbieter eingerichtet (OpenAI- oder Google-Schlüssel fehlt in der Konfiguration); es geht nur SVG, und das sagst du der Person, wenn sie ein Foto möchte."
        if web_on:
            extra["note"] += "\n" + WEB_NOTE
        if connectors.level(profile.id) >= 1 and not spoken:
            extra["note"] += "\n" + connector_box.note()
        if spoken:
            extra["note"] += "\n" + voicelib.voice_note(settings.voice_instructions)
        elif any(s.name.startswith("github_") for s in specs):
            extra["note"] += "\n" + GITHUB_NOTE + " " + github_level_text(gh_level, accounts.policy_for(profile.id))
        else:
            why = GITHUB_OFF_NO_RIGHT if accounts.enabled_for(profile.id) else GITHUB_OFF_NO_TOKEN
            extra["note"] += "\n" + GITHUB_OFF_NOTE.format(why=why)

        async def generate() -> None:
            error: str | None = None
            try:
                if provider == "openai" and token_limit:
                    used_tokens = store.token_usage(profile.id, usage_month, "openai")
                    if used_tokens >= token_limit:
                        decision = await ask_about(
                            "tokens", tr("Monatslimit für ChatGPT erreicht"),
                            tr("Du hast diesen Monat {used} von {limit} Token mit ChatGPT verbraucht. Jede weitere Antwort verursacht Kosten bei OpenAI.", used=f"{used_tokens:,}".replace(",", "."), limit=f"{token_limit:,}".replace(",", ".")),
                            False,
                        )
                        if decision == "deny":
                            raise _Declined(tr("Nicht gesendet: das Monatslimit für ChatGPT ist erreicht."))
                # Zu langer Verlauf: älteren Teil zusammenfassen, statt ihn stillschweigend abzuschneiden.
                summary, upto = store.get_summary(profile.id, chat_id)
                pending = [m for m in history if upto is None or m["id"] > upto]
                if summarize and compact.needs_compaction(summary, pending, asked):
                    plan = compact.split(pending)
                    if plan:
                        older, recent = plan
                        run.push({"type": "status", "text": tr("Fasse den früheren Verlauf zusammen …")})
                        produced: dict = {}

                        async def work() -> AsyncIterator[str]:
                            async with asyncio.timeout(SUMMARY_TIMEOUT):
                                produced["text"] = await summarize(summary, older, **summary_args)
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
                        live = _pump(lambda: backend.stream(context, asked, effort, **extra), KEEPALIVE_SECONDS)
                        async with contextlib.aclosing(live):
                            async for piece in live:
                                if piece is not None:
                                    run.push({"type": "delta", "text": piece})
                except BackendError as exc:
                    error = exc.user_message
                    run.error_resets_at = exc.resets_at
                except TimeoutError:
                    error = tr("Zeitüberschreitung: ChatGPT hat nicht rechtzeitig geantwortet.") if provider == "openai" else tr("Zeitüberschreitung: Claude hat nicht rechtzeitig geantwortet.")
            except asyncio.CancelledError:
                pass  # Stopp-Knopf oder Herunterfahren: vorhandene Teilantwort wird unten gespeichert
            except _Declined as exc:
                error = str(exc)
            except Exception:
                log.exception("Antwort fehlgeschlagen")
                error = tr("Unerwarteter Fehler beim Beantworten.")
            try:
                answer = "".join(run.parts)
                actions = run.action_log()
                if not answer and any(a["kind"] in ("execute", "write", "memory", "knowledge-write", "file") and a["status"] in ("ok", "abgebrochen") for a in actions):
                    answer = tr("_Die Aktionen wurden ausgeführt, die Antwort dazu fehlt. Das Protokoll steht oberhalb._")
                    run.push({"type": "delta", "text": answer})
                if answer:
                    # Auch eine abgebrochene Teilantwort wird behalten (setzt den Chat auf ungelesen).
                    store.add_message(profile.id, chat_id, "assistant", answer, tools=actions)
                else:
                    withdraw_question()
                run.error = error
                run.kept = bool(answer)
                run.title = _title_from(_title_source(text, metas)) if first_exchange and answer else None
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
                if run.parts and not run.error and run.followers == 0 and not incognito:
                    # Antwort fertig und niemand sieht zu: bei ungelesenem Chat nach kurzer Schonfrist aufs Handy melden (nie bei Inkognito).
                    notifier.spawn(profile, chat_id, plain_excerpt("".join(run.parts), notifierlib.EXCERPT))

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



def _connector_page(ok: bool, message: str) -> HTMLResponse:
    """Schlichte Seite nach der Anmeldung bei einem Konnektor (ohne Inline-Stile: die Domain-Seite erlaubt keine)."""
    title = tr("Konnektor verbunden") if ok else tr("Anmeldung nicht abgeschlossen")
    return HTMLResponse(
        f"<!doctype html><html lang='{i18n.language()}'><meta charset=utf-8><meta name=viewport content='width=device-width'>"
        f"<title>{html.escape(title)}</title><link rel=stylesheet href='/static/style.css'>"
        f"<body><main class='plain-page'><h1>{html.escape(title)}</h1><p>{html.escape(message)}</p></main>",
        status_code=200 if ok else 400,
    )


_HA_ID = re.compile(r"^[0-9a-f]{32}$")


def make_connectors(settings: Settings, store: Store, registry: Registry, *, vault: Vault | None = None) -> ConnectorService:
    """Konnektoren: ein gemeinsamer Dienst für beide Zugänge (Anmeldungen laufen über den Browser, dort wartet der Zwischenstand)."""

    def level_for(profile_id: str) -> str:
        profile = registry.by_id(profile_id)
        return settings.connector_level(profile) if profile is not None else settings.connector_access_default

    return ConnectorService(
        store, vault or Vault(VAULT_PATH),
        level_for=level_for,
        base_url=lambda: settings.public_base_url if settings.public_enabled else "",
        version=_asset_version(),
        allow_private=lambda: settings.connector_allow_private,
    )


def make_scheduler(settings: Settings, store: Store, backend: ChatBackend, registry: Registry, ha: HaApi, runs: dict, connectors: ConnectorService | None = None, github_accounts: GithubAccounts | None = None) -> Scheduler:
    """Geplante Aufgaben: ein gemeinsamer Ausführer für beide Zugänge (laufende Antworten zählen zusammen)."""
    return Scheduler(
        settings, store, backend, registry, ha, limitlib.shared(store), runs,
        lambda key, text: Run(key, text, False),
        connectors=connectors,
        github_accounts=github_accounts,
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
    scheduler: Scheduler | None = None,
    public_peers: PeerLog | None = None,
    images: ImageService | None = None,
    connectors: ConnectorService | None = None,
    github_accounts: GithubAccounts | None = None,
    voice: VoiceService | None = None,
) -> FastAPI:
    i18n.set_language(settings.language)
    registry = registry or Registry.from_settings(settings, store)
    ha = ha or HaApi("", HA_WEBSOCKET_URL)
    scanner = scanner or (OverviewScanner(store, ha) if ha.enabled else None)
    github_accounts = github_accounts or GithubAccounts(store, Vault(VAULT_PATH))
    branding = branding or Branding(BRANDING_DIR, settings, ha)
    busy = busy if busy is not None else {}
    connectors = connectors or make_connectors(settings, store, registry)
    scheduler = scheduler or make_scheduler(settings, store, backend, registry, ha, busy, connectors, github_accounts)
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
        health, ha, "ingress", scanner, scheduler, registry, public_peers, images, connectors, github_accounts, voice,
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
    scheduler: Scheduler | None = None,
    public_peers: PeerLog | None = None,
    images: ImageService | None = None,
    connectors: ConnectorService | None = None,
    github_accounts: GithubAccounts | None = None,
    voice: VoiceService | None = None,
) -> FastAPI:
    """Domain-Zugang (Cloudflare Tunnel): eigene Anmeldeseite, Entra-Login (und optional Home Assistant), Sitzungs-Cookie.

    Liest absichtlich keine X-Remote-User-*-Header. Die Person steht ausschließlich in der
    serverseitigen Sitzung, die nach erfolgreicher Entra-Anmeldung angelegt wird.
    """
    i18n.set_language(settings.language)
    registry = registry or Registry.from_settings(settings, store)
    ha = ha or HaApi("", HA_WEBSOCKET_URL)
    scanner = scanner or (OverviewScanner(store, ha) if ha.enabled else None)
    github_accounts = github_accounts or GithubAccounts(store, Vault(VAULT_PATH))
    branding = branding or Branding(BRANDING_DIR, settings, ha)
    busy = busy if busy is not None else {}
    connectors = connectors or make_connectors(settings, store, registry)
    scheduler = scheduler or make_scheduler(settings, store, backend, registry, ha, busy, connectors, github_accounts)
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

    # Öffentlicher Link zu einem geteilten Chat: ohne Anmeldung, nur lesen. Der Link besteht aus 43 zufälligen Zeichen
    # (256 Bit); wer ihn nicht kennt, kann ihn nicht erraten. Je Gegenstelle begrenzt, nie für Suchmaschinen, nie gemerkt.
    share_limit = RateLimiter(60, 600)

    def public_share(request: Request, token: str) -> dict:
        ip = client_ip(request)
        if not share_limit.allow(ip):
            raise HTTPException(status_code=429, detail=tr("Zu viele Versuche"))
        if settings.sharing != "public" or not SHARE_TOKEN.fullmatch(token):
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        row = store.share_read(token=token, mode="public")
        if row is None:
            raise HTTPException(status_code=404, detail=tr("Nicht gefunden"))
        return row

    @app.get("/s/{token}", response_class=HTMLResponse, include_in_schema=False)
    def shared_page(request: Request, token: str) -> Response:
        # Dieselbe Seite auch bei ungültigem Link (Status 404): sie holt die Daten und zeigt dann die Meldung in der Seitensprache.
        try:
            public_share(request, token)
            status = 200
        except HTTPException as exc:
            status = exc.status_code
        page = _shared_page(branding, version)
        page.status_code = status
        return page

    @app.get("/s/{token}/data", include_in_schema=False)
    def shared_data(request: Request, token: str) -> JSONResponse:
        row = public_share(request, token)
        return JSONResponse(
            {"title": row["title"], "taken_at": row["taken_at"], "expires_at": row["expires_at"], "messages": row["messages"]},
            headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow, noarchive"},
        )

    register_chat_routes(
        app, settings, store, backend, busy, current_profile, write_guard,
        {"mode": "domain", "can_logout": True},
        health, ha, "public", scanner, scheduler, registry, public_peers, images, connectors, github_accounts, voice,
    )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


SNAPSHOT_CHECK_SECONDS = 1800
INCOGNITO_IDLE_MINUTES = 180  # Inkognito-Chats, deren Seite ohne Abmelden verschwand (Handy-Tab beendet), werden nach 3 Stunden gelöscht


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


async def _sweep_loop(backend: ChatBackend, store: Store | None = None, voice_days: int = 0) -> None:
    """Zwischendateien des Claude-Programms, abgelaufene erzeugte Dateien und alte Sprachgespräche regelmäßig entfernen."""
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
            try:
                expired = await asyncio.to_thread(store.share_sweep)
                if expired:
                    log.info("%d abgelaufene Chat-Freigaben entfernt", expired)
            except Exception:
                log.warning("Aufräumen der Chat-Freigaben fehlgeschlagen", exc_info=True)
            try:
                left = await asyncio.to_thread(store.incognito_sweep, INCOGNITO_IDLE_MINUTES)
                if left:
                    log.info("%d liegen gebliebene Inkognito-Chats gelöscht", left)
            except Exception:
                log.warning("Aufräumen der Inkognito-Chats fehlgeschlagen", exc_info=True)
            try:
                gone = await asyncio.to_thread(store.voice_sweep, voice_days)
                if gone:
                    log.info("%d alte Sprachgespräche gelöscht", gone)
            except Exception:
                log.warning("Aufräumen der Sprachgespräche fehlgeschlagen", exc_info=True)
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
    github_accounts = GithubAccounts(store, Vault(VAULT_PATH))
    connectors = make_connectors(settings, store, registry)
    scheduler = make_scheduler(settings, store, backend, registry, ha, busy, connectors, github_accounts)
    public_peers = PeerLog()  # Gegenstellen der Domain-Seite (für die Einrichtungsprüfung)
    servers = [server(build_ingress_app(settings, store, backend, busy, health, branding, ha, registry, scanner, scheduler, public_peers, connectors=connectors, github_accounts=github_accounts), INGRESS_PORT)]
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
            server(build_public_app(settings, store, backend, entra, busy, health, branding, ha, registry, ha_login, scanner, scheduler, public_peers, connectors=connectors, github_accounts=github_accounts), PUBLIC_PORT)
        )
        log.info("Domain-Zugang aktiv: %s (Port %d)", settings.public_base_url, PUBLIC_PORT)
    snapshots = asyncio.create_task(_snapshot_loop(store))
    sweeper = asyncio.create_task(_sweep_loop(backend, store, settings.voice_chat_days))
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
    else:
        backend = EchoBackend()
        log.warning("KI-Backend: Echo-Testmodus – es wird KEINE echte KI verwendet")
    if settings.openai_active:
        backend = RouterBackend(backend, OpenAIBackend(settings.openai_chat_key, settings.openai_models[0]))
        log.info("KI-Backend: zusätzlich ChatGPT (%s)", ", ".join(settings.openai_models))
    elif settings.openai_enabled:
        log.warning("ChatGPT ist eingeschaltet, aber es fehlt der OpenAI-Schlüssel (Gruppe Chat oder Bilder): ChatGPT bleibt aus")
    report = safety.prepare(DB_PATH, SNAPSHOT_DIR, settings.restore_snapshot, BRANDING_DIR)
    for line in report.lines:
        (log.error if line.startswith("DATENBANK-FEHLER") else log.info)("Datensicherheit: %s", line)
    store = Store(DB_PATH)
    store.sync_profiles(p.id for p in settings.profiles)
    if (left := store.incognito_sweep(0)):  # nach einem Absturz liegen gebliebene Inkognito-Chats
        log.info("%d liegen gebliebene Inkognito-Chats gelöscht", left)
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
        with contextlib.suppress(Exception):
            store.incognito_sweep(0)  # beim Beenden (auch vor der Sicherung durch Home Assistant) bleibt nichts zurück
        store.close()


if __name__ == "__main__":
    main()
