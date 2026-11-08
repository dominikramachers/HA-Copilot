"""Konfiguration und Profilliste.

Die Profilliste ist die einzige Stelle, an der Identitäten (HA-User-ID, Entra-UPN)
einem internen Profil zugeordnet werden. Chats gehören ausschließlich dem
internen Profil (``Profile.id``), nie einer HA-ID oder einer UPN direkt.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

log = logging.getLogger("copilot.config")

OPTIONS_PATH = Path(os.environ.get("COPILOT_OPTIONS", "/data/options.json"))
# Ordner „addon_config“ des Add-ons (in Home Assistant unter /addon_configs/<Ordner>/ erreichbar, z. B. per Samba):
# hier liegen optional logo.png, logo-full.png und custom.css.
BRANDING_DIR = Path(os.environ.get("COPILOT_BRANDING", "/config"))
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
HA_WEBSOCKET_URL = os.environ.get("COPILOT_HA_WS", "ws://supervisor/core/websocket")
HA_REST_URL = os.environ.get("COPILOT_HA_REST", "http://supervisor/core/api")
DB_PATH = Path(os.environ.get("COPILOT_DB", "/data/copilot.sqlite3"))
SNAPSHOT_DIR = DB_PATH.parent / "snapshots"

# Quelladresse des Supervisor-Ingress-Proxys. Nur von dort werden die
# X-Remote-User-*-Header als vertrauenswürdig behandelt.
DEFAULT_INGRESS_PEERS = frozenset({"172.30.32.2"})

_ID_RE = re.compile(r"^[a-z0-9_-]{2,32}$")
_HA_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_UPN_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_GUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_ORIGIN_RE = re.compile(r"^https://[a-z0-9]([a-z0-9.-]*[a-z0-9])?(:\d{1,5})?$")


_FAMILY_NAMES = {"sonnet": "Sonnet", "opus": "Opus", "haiku": "Haiku", "fable": "Fable", "mythos": "Mythos"}


def model_label(model: str) -> str:
    """Lesbarer Name zu einer Modellkennung: ``claude-sonnet-5-5`` → ``Sonnet 5.5``; Unbekanntes bleibt wie eingetragen."""
    match = re.match(r"^claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?(?:-\d{8})?$", model)
    if match and match.group(1) in _FAMILY_NAMES:
        version = match.group(2) + (f".{match.group(3)}" if match.group(3) else "")
        return f"{_FAMILY_NAMES[match.group(1)]} {version}"
    if model in _FAMILY_NAMES:
        return _FAMILY_NAMES[model]
    return model


class ConfigError(ValueError):
    """Ungültige Add-on-Konfiguration."""


@dataclass(frozen=True)
class Profile:
    id: str
    label: str
    ha_user_id: str  # leer = kein Zugang über Home Assistant
    entra_upn: str  # leer = kein Zugang über die Domain
    ha_user: str = ""  # HA-Benutzername oder Personenname; das Add-on löst ihn zur ID auf (ha_user_id hat Vorrang)
    ha_access: str = ""  # Zugriff auf Home Assistant: none | read | execute | write; leer = ha_access_default
    github_access: str = ""  # Zugriff auf GitHub: none | read | write; leer = github_access_default
    connector_access: str = ""  # Konnektoren: none | use | own | global; leer = connector_access_default
    web_access: str = ""  # Websuche und Seiten lesen: on | off; leer = web_access_default
    notify_service: str = ""  # Benachrichtigungsdienst dieser Person, z. B. notify.mobile_app_pixel; leer = keiner


DEFAULT_MODELS = ("claude-opus-5-5", "claude-haiku-5-5")  # neben ``model`` wählbar
TITLE_MODEL = "claude-haiku-5-5"
IMAGE_MODEL_OPENAI = "gpt-image-2.5-sunburst"
IMAGE_MODEL_GOOGLE = "gemini-3.1-flash-image-preview"
APP_NAME_DEFAULT = "HA Copilot"
LOGIN_PLACEHOLDER_DEFAULT = "name@beispiel.de"
LOGIN_TEXT_DEFAULT = "Melde dich an, um mit der KI zu chatten."


@dataclass(frozen=True)
class Settings:
    profiles: tuple[Profile, ...]
    public_enabled: bool = False
    ingress_peers: frozenset[str] = DEFAULT_INGRESS_PEERS
    backend: str = "echo"  # "echo" (Test, keine Kosten) oder "claude"
    claude_oauth_token: str = field(default="", repr=False)
    anthropic_api_key: str = field(default="", repr=False)  # Alternative zum Abo-Token (Abrechnung über die Claude-Konsole)
    model: str = "claude-sonnet-5-5"
    # Seit 0.45.0 nicht mehr einstellbar (feste Werte, ``parse_settings`` liest die alten Optionen nicht mehr):
    title_model: str = TITLE_MODEL
    models: tuple[str, ...] = DEFAULT_MODELS  # zusätzlich wählbare Modelle (Standard ist ``model``)
    web_access_default: str = "on"  # Websuche und Seiten lesen (on | off), pro Benutzer überschreibbar (web_access)
    schedules_enabled: bool = True  # geplante Aufgaben (Menüpunkt „Geplant“)
    notify_long_answers: bool = True  # Benachrichtigung bei fertiger längerer Antwort; wirkt nur mit notify_service der Person
    restore_snapshot: str = ""
    export_database: bool = False  # Datenbank beim Start in den Config-Ordner kopieren (Umzug in ein anderes Add-on)
    claude_token_expires: date | None = None
    entra_secret_expires: date | None = None
    default_effort: str = "medium"  # fest; im Chat wählbar
    language: str = "de"  # Sprache der Oberfläche und der Systemmeldungen: de oder en (die KI antwortet standardmäßig in dieser Sprache)
    # Zugriff der KI auf Home Assistant (pro Benutzer überschreibbar)
    ha_access_default: str = "execute"  # lesen und ausführen; Ändern (write) nur, wenn es im Profil steht
    ha_write_confirm: str = "ask"  # fest: jede Änderung wird im Chat bestätigt (in diesem Chat immer zulassen geht)
    ha_limit_to_exposed: bool = True  # lesen/ausführen nur für Entitäten, die in HA für Assist freigegeben sind
    ha_access_via_domain: bool = True  # fest: Rechtestufen gelten auch bei Anmeldung über die Domain
    # Gedächtnis der KI (Haushalt und je Person)
    memory_enabled: bool = True
    memory_household_writers: str = "all"  # fest: jeder darf das Haushaltsgedächtnis ändern (ha_write = nur Stufe write, nur noch in Tests)
    ha_scan_days: int = 7  # fest: Überblick über Home Assistant beim ersten Start und dann alle 7 Tage einlesen (Knopf im Gedächtnis-Dialog)
    # GitHub (jede Person verbindet ihr eigenes Konto; wer was darf, steht je Profil bzw. in github_access_default)
    github_access_default: str = "none"
    github_write_confirm: str = "ask"  # fest: jede Änderung wird im Chat bestätigt
    # Konnektoren (MCP-Server): wer sie nutzen, selbst anlegen oder für alle verwalten darf, steht je Profil bzw. hier
    connector_access_default: str = "use"
    connector_write_confirm: str = "ask"  # fest: jede Änderung über einen Konnektor wird im Chat bestätigt
    connector_allow_private: bool = True  # fest: wer Konnektoren anlegen darf, darf auch Adressen im Heimnetz und mit http eintragen (Gesperrtes bleibt gesperrt)
    # Dateien, die die KI erzeugt (Word, Excel, PDF, PowerPoint, Skripte …)
    files_enabled: bool = True
    files_edit: bool = True  # fest: Anhänge im Chat aufbewahren; die KI kann Dateien lesen und bearbeiten
    files_keep_days: int = 14  # fest: so lange bleiben erzeugte Dateien zum Herunterladen verfügbar
    # Bilder (SVG von Claude; Fotos und Kunst über OpenAI oder Google)
    images_enabled: bool = True  # fest: folgt files_enabled; Fotos und Kunst brauchen zusätzlich einen Schlüssel
    openai_api_key: str = field(default="", repr=False)
    google_api_key: str = field(default="", repr=False)
    image_model_openai: str = IMAGE_MODEL_OPENAI
    image_model_google: str = IMAGE_MODEL_GOOGLE
    image_provider: str = "auto"  # auto = die KI wählt je Bild; openai oder google = immer dieser Anbieter
    image_limit_month: int = 30  # Bilder von OpenAI/Google je Person und Monat, danach fragt der Chat vor jedem weiteren nach (0 = kein Limit)
    # Domain-Zugang (nur relevant, wenn public_enabled)
    public_base_url: str = ""
    entra_tenant_id: str = ""
    entra_client_id: str = ""
    entra_client_secret: str = field(default="", repr=False)
    session_days: int = 30
    public_trusted_proxies: frozenset[str] = frozenset()
    ha_url: str = ""  # Adresse von Home Assistant im Browser: schaltet "Mit Home Assistant anmelden" ein
    # Zugang über Home Assistant
    all_ha_users: bool = False  # jeder aktive HA-Benutzer darf die App nutzen
    ha_users_excluded: frozenset[str] = frozenset()  # davon ausgenommen (Benutzername, Name oder ID, kleingeschrieben)
    # Aussehen
    app_name: str = APP_NAME_DEFAULT
    login_text: str = LOGIN_TEXT_DEFAULT
    login_placeholder: str = LOGIN_PLACEHOLDER_DEFAULT
    follow_ha_theme: bool = True
    logo_tile: bool = False  # Logo auf heller Fläche auf dunkler Kachel zeigen
    theme_name: str = ""

    @property
    def entra_enabled(self) -> bool:
        return bool(self.entra_tenant_id and self.entra_client_id and self.entra_client_secret)

    @property
    def ha_login_enabled(self) -> bool:
        return bool(self.ha_url)

    def model_choices(self) -> list[dict[str, str]]:
        """Wählbare Modelle (Standard zuerst); nur eines = nichts zu wählen."""
        if not self.models:
            return []
        return [{"id": m, "label": model_label(m)} for m in dict.fromkeys((self.model, *self.models))]

    def connector_level(self, profile: Profile) -> str:
        """Was darf diese Person bei Konnektoren? (none | use | own | global)"""
        return profile.connector_access or self.connector_access_default

    def web_level(self, profile: Profile) -> str:
        """Darf diese Person die Websuche nutzen? (on | off)"""
        return profile.web_access or self.web_access_default


HA_ACCESS_LEVELS = ("none", "read", "execute", "write")
WEB_ACCESS_LEVELS = ("on", "off")
_NOTIFY_RE = re.compile(r"^notify\.[a-z0-9_]{1,80}$")
GITHUB_ACCESS_LEVELS = ("none", "read", "write")
CONNECTOR_ACCESS_LEVELS = ("none", "use", "own", "global")  # none = keine, use = globale nutzen, own = zusätzlich eigene, global = zusätzlich globale verwalten


_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "ae", "Ö": "oe", "Ü": "ue"})


def slug_id(label: str, taken: set[str]) -> str:
    """Profil-ID aus dem Anzeigenamen ableiten (a-z, 0-9, Bindestrich); bei Bedarf mit Zahl eindeutig machen."""
    base = re.sub(r"[^a-z0-9]+", "-", label.translate(_UMLAUTS).lower()).strip("-")[:26] or "user"
    if len(base) < 2:
        base = f"user-{base}"
    candidate, n = base, 2
    while candidate in taken:
        candidate = f"{base[:26]}-{n}"
        n += 1
    return candidate


def _optional(entry: dict[str, Any], key: str) -> str:
    value = entry.get(key)
    return value.strip() if isinstance(value, str) else ""


def _text(entry: dict[str, Any], key: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"Profil-Feld '{key}' fehlt oder ist leer")
    return value.strip()


def parse_settings(raw: dict[str, Any], ingress_peers: frozenset[str] | None = None) -> Settings:
    entries = raw.get("profiles")
    all_ha_users = bool(raw.get("all_ha_users", False))
    if not isinstance(entries, list):
        raise ConfigError("profiles muss eine Liste sein")
    # Ganz leere Einträge (nichts ausgefüllt) werden übersprungen statt den Start zu verhindern.
    entries = [
        e for e in entries
        if not (isinstance(e, dict) and not any(_optional(e, k) for k in ("label", "ha_user", "ha_user_id", "entra_upn", "id")))
    ]
    if not entries and not all_ha_users:
        raise ConfigError("Mindestens ein Benutzer muss eingetragen sein (oder „Alle Home-Assistant-Benutzer zulassen“ einschalten)")

    profiles: list[Profile] = []
    seen: dict[str, set[str]] = {"id": set(), "ha_user_id": set(), "entra_upn": set(), "ha_user": set()}
    explicit = {_optional(e, "id").lower() for e in entries if isinstance(e, dict) and _optional(e, "id")}

    for entry in entries:
        if not isinstance(entry, dict):
            raise ConfigError("Ungültiger Profileintrag")
        label = re.sub(r"\s+", " ", _optional(entry, "label")) or re.sub(r"\s+", " ", _optional(entry, "ha_user"))
        if not label:
            raise ConfigError("Jeder Benutzer braucht einen Anzeigenamen oder einen Home-Assistant-Benutzernamen")
        if len(label) > 40 or re.search(r"[<>\x00-\x1f]", label):
            raise ConfigError(f"Ungültiger Anzeigename: {label[:20]!r}")
        ha_user_id = _optional(entry, "ha_user_id").lower()
        entra_upn = _optional(entry, "entra_upn").lower()
        profile_id = _optional(entry, "id").lower() or slug_id(label, seen["id"] | explicit)
        if not _ID_RE.match(profile_id):
            raise ConfigError(f"Ungültige Profil-ID: {profile_id!r}")
        ha_user = re.sub(r"\s+", " ", _optional(entry, "ha_user"))
        if len(ha_user) > 64 or re.search(r"[<>\x00-\x1f]", ha_user):
            raise ConfigError(f"Ungültiger HA-Benutzername bei Profil {profile_id!r}")
        if not ha_user_id and not ha_user and not entra_upn:
            # Platzhalter (z. B. frisch installiert): die App startet, das Profil passt aber auf niemanden.
            # Wer die App in Home Assistant öffnet, sieht dann seine Benutzer-ID und kann sie eintragen.
            log.warning("Profil %r hat weder HA-Benutzer noch Entra-E-Mail und ist noch nicht verknüpft", profile_id)
        if ha_user_id and not _HA_ID_RE.match(ha_user_id):
            raise ConfigError(f"Ungültige HA-User-ID bei Profil {profile_id!r}")
        if entra_upn and not _UPN_RE.match(entra_upn):
            raise ConfigError(f"Ungültige UPN bei Profil {profile_id!r}")
        ha_access = _optional(entry, "ha_access").lower()
        if ha_access and ha_access not in HA_ACCESS_LEVELS:
            raise ConfigError(f"ha_access bei Profil {profile_id!r} muss none, read, execute oder write sein")
        github_access = _optional(entry, "github_access").lower()
        if github_access and github_access not in GITHUB_ACCESS_LEVELS:
            raise ConfigError(f"github_access bei Profil {profile_id!r} muss none, read oder write sein")
        connector_access = _optional(entry, "connector_access").lower()
        if connector_access and connector_access not in CONNECTOR_ACCESS_LEVELS:
            raise ConfigError(f"connector_access bei Profil {profile_id!r} muss none, use, own oder global sein")
        web_access = _optional(entry, "web_access").lower()
        if web_access and web_access not in WEB_ACCESS_LEVELS:
            raise ConfigError(f"web_access bei Profil {profile_id!r} muss on oder off sein")
        notify_service = _optional(entry, "notify_service").lower()
        if notify_service and not _NOTIFY_RE.match(notify_service):
            raise ConfigError(f"notify_service bei Profil {profile_id!r} muss ein Benachrichtigungsdienst wie notify.mobile_app_pixel sein")
        profile = Profile(
            id=profile_id, label=label, ha_user_id=ha_user_id, entra_upn=entra_upn, ha_user=ha_user,
            ha_access=ha_access, github_access=github_access, connector_access=connector_access, web_access=web_access, notify_service=notify_service,
        )
        for key in seen:
            value = getattr(profile, key)
            if key == "ha_user":
                value = value.lower()
            if not value:
                continue
            if value in seen[key]:
                raise ConfigError(f"Doppelter Wert für '{key}': {value!r}")
            seen[key].add(value)
        profiles.append(profile)

    claude_token = str(raw.get("claude_oauth_token") or "").strip()
    api_key = str(raw.get("anthropic_api_key") or "").strip()
    backend = "claude" if (claude_token or api_key) else "echo"  # ohne Zugang: Testbetrieb ohne KI
    language = str(raw.get("language") or "de").strip().lower()
    if language not in ("de", "en"):
        raise ConfigError("language muss de oder en sein")
    ha_access_default = str(raw.get("ha_access_default") or "execute").strip().lower()
    if ha_access_default not in HA_ACCESS_LEVELS:
        raise ConfigError("ha_access_default muss none, read, execute oder write sein")
    github_access_default = str(raw.get("github_access_default") or "none").strip().lower()
    if github_access_default not in GITHUB_ACCESS_LEVELS:
        raise ConfigError("github_access_default muss none, read oder write sein")
    connector_access_default = str(raw.get("connector_access_default") or "use").strip().lower()
    if connector_access_default not in CONNECTOR_ACCESS_LEVELS:
        raise ConfigError("connector_access_default muss none, use, own oder global sein")
    try:
        image_limit_month = int(raw.get("image_limit_month", 30))
    except (TypeError, ValueError):
        raise ConfigError("image_limit_month muss eine Zahl von 0 bis 10000 sein (0 = kein Limit)") from None
    if not 0 <= image_limit_month <= 10000:
        raise ConfigError("image_limit_month muss eine Zahl von 0 bis 10000 sein (0 = kein Limit)")
    image_provider = str(raw.get("image_provider") or "auto").strip().lower()
    if image_provider not in ("auto", "openai", "google"):
        raise ConfigError("image_provider muss auto, openai oder google sein")
    model = str(raw.get("model") or "claude-sonnet-5-5").strip()
    if not re.match(r"^[A-Za-z0-9._-]{3,64}$", model):
        raise ConfigError("Ungültiger Modellname")
    restore = str(raw.get("restore_snapshot") or "").strip()
    if restore and not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,100}\.sqlite3$", restore):
        raise ConfigError("restore_snapshot muss ein Dateiname aus dem Ordner snapshots sein (endet auf .sqlite3)")
    token_expires = _parse_date(raw.get("claude_token_expires"), "claude_token_expires")
    secret_expires = _parse_date(raw.get("entra_secret_expires"), "entra_secret_expires")

    base_url = str(raw.get("public_base_url") or "").strip().rstrip("/").lower()
    tenant = str(raw.get("entra_tenant_id") or "").strip().lower()
    client_id = str(raw.get("entra_client_id") or "").strip().lower()
    secret = str(raw.get("entra_client_secret") or "").strip()
    try:
        session_days = int(raw.get("session_days", 30))
    except (TypeError, ValueError):
        raise ConfigError("session_days muss eine Zahl sein") from None
    if not 1 <= session_days <= 90:
        raise ConfigError("session_days muss zwischen 1 und 90 liegen")
    proxies = raw.get("public_trusted_proxies") or []
    if not isinstance(proxies, list) or not all(isinstance(x, str) for x in proxies):
        raise ConfigError("public_trusted_proxies muss eine Liste von Adressen sein")

    ha_url = str(raw.get("ha_url") or "").strip().rstrip("/").lower()
    if ha_url and not _ORIGIN_RE.match(ha_url):
        raise ConfigError("ha_url muss eine https-Adresse ohne Pfad sein, z. B. https://ha.example.org")
    excluded_raw = raw.get("ha_users_excluded") or ""
    if isinstance(excluded_raw, str):
        excluded_raw = re.split(r"[,;\n]", excluded_raw)
    if not isinstance(excluded_raw, list):
        raise ConfigError("ha_users_excluded muss eine Liste von Namen sein (durch Komma getrennt)")
    excluded = frozenset(re.sub(r"\s+", " ", str(x)).strip().lower() for x in excluded_raw if str(x).strip())

    # Der Domain-Zugang ist an, sobald eine öffentliche Adresse und eine Anmeldung (Entra und/oder ha_url) eingetragen sind.
    entra_given = any((tenant, client_id, secret))
    public_enabled = bool(base_url) and bool(entra_given or ha_url)
    if base_url and not public_enabled:
        log.warning("public_base_url ist gesetzt, aber weder Entra noch ha_url: der Domain-Zugang bleibt aus")
    if public_enabled:
        if not _ORIGIN_RE.match(base_url):
            raise ConfigError("public_base_url muss eine https-Adresse ohne Pfad sein, z. B. https://chat.example.org")
        if entra_given or not ha_url:  # ohne ha_url ist die Entra-Anmeldung der einzige Weg und muss vollständig sein
            if not _GUID_RE.match(tenant):
                raise ConfigError("entra_tenant_id fehlt oder ist keine GUID")
            if not _GUID_RE.match(client_id):
                raise ConfigError("entra_client_id fehlt oder ist keine GUID")
            if not secret:
                raise ConfigError("entra_client_secret fehlt")

    app_name = _single_line(raw.get("app_name"), APP_NAME_DEFAULT, 40, "app_name")
    login_text = _single_line(raw.get("login_text"), LOGIN_TEXT_DEFAULT, 120, "login_text")
    login_placeholder = _single_line(raw.get("login_placeholder"), LOGIN_PLACEHOLDER_DEFAULT, 60, "login_placeholder")
    theme_name = _single_line(raw.get("theme_name"), "", 80, "theme_name")

    return Settings(
        profiles=tuple(profiles),
        app_name=app_name,
        login_text=login_text,
        login_placeholder=login_placeholder,
        follow_ha_theme=bool(raw.get("follow_ha_theme", True)),
        logo_tile=bool(raw.get("logo_tile", False)),
        theme_name=theme_name,
        public_enabled=public_enabled,
        public_base_url=base_url,
        entra_tenant_id=tenant,
        entra_client_id=client_id,
        entra_client_secret=secret,
        session_days=session_days,
        public_trusted_proxies=frozenset(x.strip() for x in proxies if x.strip()),
        ha_url=ha_url,
        all_ha_users=all_ha_users,
        ha_users_excluded=excluded,
        ingress_peers=ingress_peers or DEFAULT_INGRESS_PEERS,
        backend=backend,
        claude_oauth_token=claude_token,
        anthropic_api_key=api_key,
        model=model,
        schedules_enabled=bool(raw.get("schedules_enabled", True)),
        restore_snapshot=restore,
        export_database=bool(raw.get("export_database", False)),
        claude_token_expires=token_expires,
        entra_secret_expires=secret_expires,
        language=language,
        ha_access_default=ha_access_default,
        ha_limit_to_exposed=bool(raw.get("ha_limit_to_exposed", True)),
        memory_enabled=bool(raw.get("memory_enabled", True)),
        github_access_default=github_access_default,
        connector_access_default=connector_access_default,
        files_enabled=bool(raw.get("files_enabled", True)),
        openai_api_key=str(raw.get("openai_api_key") or "").strip(),
        google_api_key=str(raw.get("google_api_key") or "").strip(),
        image_provider=image_provider,
        image_limit_month=image_limit_month,
    )


def _single_line(value: Any, default: str, limit: int, name: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return default
    if len(text) > limit or re.search(r"[<>\x00-\x1f]", text):
        raise ConfigError(f"{name} ist zu lang oder enthält unzulässige Zeichen (höchstens {limit} Zeichen, kein < oder >)")
    return text


def _parse_date(value: Any, name: str) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ConfigError(f"{name} muss ein Datum im Format JJJJ-MM-TT sein, z. B. 2027-10-26") from None


def load_settings(path: Path = OPTIONS_PATH) -> Settings:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Optionen nicht lesbar: {exc}") from exc

    override = os.environ.get("COPILOT_INGRESS_PEERS")
    peers = (
        frozenset(p.strip() for p in override.split(",") if p.strip()) if override else None
    )
    return parse_settings(raw, peers)
