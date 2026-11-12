"""Konfiguration und Profilliste.

Die Profilliste ist die einzige Stelle, an der Identitäten (HA-User-ID, Entra-UPN)
einem internen Profil zugeordnet werden. Chats gehören ausschließlich dem
internen Profil (``Profile.id``), nie einer HA-ID oder einer UPN direkt.
"""
from __future__ import annotations

import dataclasses
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


_OPENAI_MODEL = re.compile(r"^(?:gpt-|chatgpt-|o\d)", re.IGNORECASE)


def provider_of(model: str) -> str:
    """Anbieter einer Modellkennung: ``openai`` für GPT-Modelle (gpt-…, o3, o4-mini …), sonst ``claude``."""
    return "openai" if _OPENAI_MODEL.match(model or "") else "claude"


def model_label(model: str) -> str:
    """Lesbarer Name zu einer Modellkennung: ``claude-sonnet-5-5`` → ``Sonnet 5.5``, ``gpt-5.6-terra`` → ``GPT-5.6 Terra``; Unbekanntes bleibt wie eingetragen."""
    if provider_of(model) == "openai":
        parts = [p for p in model.split("-") if p]
        if parts and parts[0].lower() in ("gpt", "chatgpt") and len(parts) > 1:
            return f"{'GPT' if parts[0].lower() == 'gpt' else 'ChatGPT'}-{parts[1]}" + "".join(f" {p[:1].upper()}{p[1:]}" for p in parts[2:])
        return model
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
    voice_access: str = ""  # Sprechen mit der KI: on | off; leer = voice_access_default


DEFAULT_MODELS = ("claude-opus-5-5", "claude-haiku-5-5")  # neben ``model`` wählbar
TITLE_MODEL = "claude-haiku-5-5"
VOICE_MODEL = "claude-haiku-5-5"  # gesprochene Antworten: das schnelle Modell (bleibt immer Claude)
AUTO_MODEL = "auto"  # in der Modellwahl: das in der App eingestellte Standard-Modell
DEFAULT_OPENAI_MODELS = ("gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.6-sol")  # neben den Claude-Modellen wählbar, wenn OpenAI eingeschaltet ist
OPENAI_LIMIT_MONTH_DEFAULT = 3000  # Tausend Token je Person und Monat (= 3 Mio.), danach fragt der Chat nach (0 = kein Limit)
OPENAI_VOICES = ("alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer", "verse")  # Stimmen von gpt-4o-mini-tts
VOICE_INSTRUCTIONS_MAX = 600  # Zeichen für eigene Wünsche an die gesprochenen Antworten (voice.instructions)
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
    # ChatGPT / OpenAI als zweiter Anbieter für den Chat (global ein-/ausschaltbar, standardmäßig aus)
    openai_enabled: bool = False
    openai_chat_api_key: str = field(default="", repr=False)  # eigener Schlüssel für den Chat; leer = der Schlüssel aus „Bilder“
    openai_chat_key_expires: date | None = None
    openai_models: tuple[str, ...] = DEFAULT_OPENAI_MODELS
    openai_limit_month: int = OPENAI_LIMIT_MONTH_DEFAULT  # Tausend Token je Person und Monat (0 = kein Limit)
    web_access_default: str = "on"  # Websuche und Seiten lesen (on | off), pro Benutzer überschreibbar (web_access)
    schedules_enabled: bool = True  # geplante Aufgaben (Menüpunkt „Geplant“)
    incognito_enabled: bool = True  # Inkognito-Chat (nichts wird gespeichert)
    restore_snapshot: str = ""
    export_database: bool = False  # Datenbank beim Start in den Config-Ordner kopieren (Umzug in ein anderes Add-on)
    claude_token_expires: date | None = None
    entra_secret_expires: date | None = None
    openai_key_expires: date | None = None
    google_key_expires: date | None = None
    migrated_options: tuple[str, ...] = ()  # Optionen, deren Wert aus der alten Konfiguration übernommen wurde (Gruppe.Name)
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
    research_enabled: bool = False  # Deep Research (mehrstufige Recherche mit Quellenbericht); aus, weil sie viel Kontingent braucht
    research_daily_limit: int = 3  # Läufe je Person und Tag
    sharing: str = "instance"  # Chats teilen: off | instance (nur in dieser Instanz) | public (zusätzlich Link ohne Anmeldung über die Domain)
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
    # Sprache (Sprechen per Knopf): Spracherkennung über OpenAI (openai_api_key) oder die Assist-Pipeline von Home Assistant
    voice_access_default: str = "off"  # wer mit der KI sprechen darf (on | off), pro Benutzer überschreibbar (voice_access)
    voice_openai_key_expires: date | None = None
    voice_openai_api_key: str = field(default="", repr=False)  # eigener OpenAI-Schlüssel nur für die Sprache; leer = openai_api_key
    voice_browser_stt: bool = True  # kostenlose Spracherkennung des Browsers, wenn es keine andere gibt
    voice_output: str = "device"  # Stimme: device = Stimme des Geräts (kostenlos), service = derselbe Dienst wie die Spracherkennung
    voice_openai_voice: str = "nova"  # Stimme von OpenAI bei voice.output: service (nova klingt weiblich)
    voice_instructions: str = ""  # eigene Wünsche an die gesprochenen Antworten, werden an den Hinweis für die KI angehängt
    voice_chat_days: int = 30  # Sprachgespräche außerhalb eines Chats nach so vielen Tagen löschen (0 = behalten)
    voice_model: str = VOICE_MODEL  # fest
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

    @property
    def openai_chat_key(self) -> str:
        """OpenAI-Schlüssel für den Chat: der eigene, sonst der gemeinsame (Bilder)."""
        return self.openai_chat_api_key or self.openai_api_key

    @property
    def openai_active(self) -> bool:
        """Ist ChatGPT im Chat nutzbar? Eingeschaltet, mit Schlüssel und mindestens einem Modell."""
        return self.openai_enabled and bool(self.openai_chat_key) and bool(self.openai_models)

    def model_choices(self) -> list[dict[str, str]]:
        """Wählbare Modelle (Standard zuerst, dann Claude, dann OpenAI); ein einziges Modell = nichts zu wählen."""
        claude = list(dict.fromkeys((self.model, *self.models))) if self.models else []
        openai = list(self.openai_models) if self.openai_active else []
        if openai and not claude:
            claude = [self.model]
        return [{"id": m, "label": model_label(m), "provider": provider_of(m)} for m in dict.fromkeys(claude + openai)]

    def connector_level(self, profile: Profile) -> str:
        """Was darf diese Person bei Konnektoren? (none | use | own | global)"""
        return profile.connector_access or self.connector_access_default

    def web_level(self, profile: Profile) -> str:
        """Darf diese Person die Websuche nutzen? (on | off)"""
        return profile.web_access or self.web_access_default

    @property
    def voice_openai_key(self) -> str:
        """OpenAI-Schlüssel für die Sprache: der eigene, sonst der gemeinsame (Bilder)."""
        return self.voice_openai_api_key or self.openai_api_key

    def voice_level(self, profile: Profile) -> str:
        """Darf diese Person mit der KI sprechen? (on | off)"""
        return profile.voice_access or self.voice_access_default


HA_ACCESS_LEVELS = ("none", "read", "execute", "write")
SHARING_MODES = ("off", "instance", "public")
RESEARCH_DAILY_LIMIT_DEFAULT = 3
WEB_ACCESS_LEVELS = ("on", "off")
VOICE_ACCESS_LEVELS = ("on", "off")
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


# Gliederung der Add-on-Konfiguration (ab 0.54.0): Gruppe -> Optionen, die früher einzeln auf oberster Ebene standen.
# ``chat`` hat außerdem die eigenen Felder (model, memory_enabled …), ``images`` und ``voice`` sind unverändert.
MOVED = {
    "users": ("profiles", "all_ha_users", "ha_users_excluded"),
    "chat": ("anthropic_api_key", "claude_oauth_token", "claude_token_expires", "ha_access_default", "ha_limit_to_exposed"),
    "domain": ("public_base_url", "ha_url", "entra_tenant_id", "entra_client_id", "entra_client_secret", "entra_secret_expires", "session_days", "public_trusted_proxies"),
    "look": ("app_name", "language", "login_text", "login_placeholder", "logo_tile", "follow_ha_theme", "theme_name"),
    "global": ("restore_snapshot", "export_database"),
}
_MOVED_FLAT = frozenset(k for keys in MOVED.values() for k in keys)
# Standardwerte der verschobenen Optionen (wie in config.yaml; ein Test vergleicht beides)
MOVED_DEFAULTS: dict[str, Any] = {
    "profiles": [{"label": "Administrator"}], "all_ha_users": False, "ha_users_excluded": "",
    "anthropic_api_key": "", "claude_oauth_token": "", "claude_token_expires": "", "ha_access_default": "execute", "ha_limit_to_exposed": True,
    "public_base_url": "", "ha_url": "", "entra_tenant_id": "", "entra_client_id": "", "entra_client_secret": "", "entra_secret_expires": "",
    "session_days": 30, "public_trusted_proxies": [],
    "app_name": "HA Copilot", "language": "de", "login_text": "", "login_placeholder": "", "logo_tile": False, "follow_ha_theme": True, "theme_name": "",
    "restore_snapshot": "", "export_database": False,
}


def _flatten(raw: dict[str, Any]) -> dict[str, Any]:
    """Die Gruppen ``users``, ``chat``, ``domain``, ``look``, ``global`` auf die einzelnen Namen abbilden, mit denen ``parse_settings`` arbeitet.

    Alte Einträge auf oberster Ebene (vor 0.54.0) werden hier nicht gelesen; ``migrate_options`` übernimmt sie vorher in die Gruppen.
    """
    flat = {k: v for k, v in raw.items() if k not in _MOVED_FLAT}
    for group, keys in MOVED.items():
        values = raw.get(group)
        if values is None:
            continue
        if not isinstance(values, dict):
            raise ConfigError(f"{group} muss eine Gruppe sein")
        for key in keys:
            if key in values:
                flat[key] = values[key]
    return flat


def _legacy_values(backup: dict[str, Any]) -> dict[str, Any]:
    """Die verschobenen Optionen aus einer Sicherung, ob sie noch oben stehen (alte Gliederung) oder schon in Gruppen."""
    found: dict[str, Any] = {}
    for group, keys in MOVED.items():
        values = backup.get(group)
        for key in keys:
            if key in backup:
                found[key] = backup[key]
            elif isinstance(values, dict) and key in values:
                found[key] = values[key]
    return found


def migrate_options(raw: dict[str, Any], backup: dict[str, Any] | None) -> tuple[dict[str, Any], list[str], dict[str, Any]]:
    """Alte Werte in die neue Gliederung übernehmen.

    Beim Wechsel auf die Gruppen wirft der Supervisor die alten Einträge weg; die Gruppen stehen dann auf Standard. Die Kopie der
    Optionen aus dem Start davor (``options-backup.json``) liefert die alten Werte. Sie werden übernommen, solange die Option in der
    neuen Gruppe noch auf dem Standardwert steht. Trägt jemand dort etwas ein, gilt das und die alte Übernahme endet für diese
    Option (``pending`` merkt sich, was noch aussteht). Rückgabe: Optionen mit Übernahme, Namen der übernommenen (``Gruppe.Name``)
    und die noch ausstehenden Werte für die nächste Sicherung.
    """
    if not isinstance(raw, dict):
        return raw, [], {}
    backup = backup if isinstance(backup, dict) else {}
    if isinstance(backup.get(PENDING_KEY), dict):
        pending = dict(backup[PENDING_KEY])
    else:  # erste Sicherung in der neuen Gliederung: alles, was die alte Sicherung abweichend vom Standard enthält
        pending = {k: v for k, v in _legacy_values(backup).items() if v is not None and v != MOVED_DEFAULTS[k]}
    result = dict(raw)
    taken: list[str] = []
    remaining: dict[str, Any] = {}
    for group, keys in MOVED.items():
        current = raw.get(group)
        if current is not None and not isinstance(current, dict):
            continue
        merged = dict(current or {})
        changed = False
        for key in keys:
            if key not in pending:
                continue
            if merged.get(key, MOVED_DEFAULTS[key]) == MOVED_DEFAULTS[key]:
                merged[key] = pending[key]
                remaining[key] = pending[key]
                taken.append(f"{group}.{key}")
                changed = True
        if changed:
            result[group] = merged
    return result, taken, remaining


def _group(raw: dict, name: str, fields: str) -> dict:
    """Eine Gruppe der Add-on-Konfiguration (``chat``, ``images``, ``voice``) als Wörterbuch; fehlt sie, ist sie leer."""
    group = raw.get(name) or {}
    if not isinstance(group, dict):
        raise ConfigError(f"{name} muss eine Gruppe sein ({fields})")
    return group


def parse_settings(raw: dict[str, Any], ingress_peers: frozenset[str] | None = None) -> Settings:
    raw = _flatten(raw)
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
        voice_access = _optional(entry, "voice_access").lower()
        if voice_access and voice_access not in VOICE_ACCESS_LEVELS:
            raise ConfigError(f"voice_access bei Profil {profile_id!r} muss on oder off sein")
        notify_service = _optional(entry, "notify_service").lower()
        if notify_service and not _NOTIFY_RE.match(notify_service):
            raise ConfigError(f"notify_service bei Profil {profile_id!r} muss ein Benachrichtigungsdienst wie notify.mobile_app_pixel sein")
        profile = Profile(
            id=profile_id, label=label, ha_user_id=ha_user_id, entra_upn=entra_upn, ha_user=ha_user,
            ha_access=ha_access, github_access=github_access, connector_access=connector_access, web_access=web_access, notify_service=notify_service,
            voice_access=voice_access,
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
    chat = _group(
        raw, "chat",
        "model, memory_enabled, schedules_enabled, incognito_enabled, sharing, research_enabled, research_daily_limit, files_enabled, github_access_default, connector_access_default, "
        "openai_enabled, openai_api_key, openai_key_expires, openai_models, openai_limit_month",
    )
    openai_models_raw = chat.get("openai_models")
    if openai_models_raw is None or (isinstance(openai_models_raw, str) and not openai_models_raw.strip()):
        openai_models = DEFAULT_OPENAI_MODELS
    else:
        if isinstance(openai_models_raw, str):
            openai_models_raw = re.split(r"[,;\s]+", openai_models_raw)
        if not isinstance(openai_models_raw, list):
            raise ConfigError("chat.openai_models muss eine Liste von Modellnamen sein (durch Komma getrennt)")
        openai_models = tuple(dict.fromkeys(str(m).strip() for m in openai_models_raw if str(m).strip()))
        for name in openai_models:
            if not re.match(r"^[A-Za-z0-9._-]{3,64}$", name) or provider_of(name) != "openai":
                raise ConfigError(f"chat.openai_models: {name!r} ist kein OpenAI-Modellname (z. B. gpt-5.6-terra)")
        if len(openai_models) > 6:
            raise ConfigError("chat.openai_models: höchstens 6 Modelle")
    try:
        openai_limit_month = int(chat.get("openai_limit_month", OPENAI_LIMIT_MONTH_DEFAULT))
    except (TypeError, ValueError):
        raise ConfigError("chat.openai_limit_month muss eine Zahl von 0 bis 100000 sein (Tausend Token, 0 = kein Limit)") from None
    if not 0 <= openai_limit_month <= 100000:
        raise ConfigError("chat.openai_limit_month muss eine Zahl von 0 bis 100000 sein (Tausend Token, 0 = kein Limit)")
    images = _group(raw, "images", "openai_api_key, google_api_key, openai_key_expires, google_key_expires, provider, limit_month")
    github_access_default = str(chat.get("github_access_default") or "none").strip().lower()
    if github_access_default not in GITHUB_ACCESS_LEVELS:
        raise ConfigError("chat.github_access_default muss none, read oder write sein")
    sharing = str(chat.get("sharing") or "instance").strip().lower()
    if sharing not in SHARING_MODES:
        raise ConfigError("chat.sharing muss off, instance oder public sein")
    try:
        research_daily_limit = int(chat.get("research_daily_limit", RESEARCH_DAILY_LIMIT_DEFAULT))
    except (TypeError, ValueError):
        raise ConfigError("chat.research_daily_limit muss eine Zahl von 1 bis 20 sein") from None
    if not 1 <= research_daily_limit <= 20:
        raise ConfigError("chat.research_daily_limit muss eine Zahl von 1 bis 20 sein")
    connector_access_default = str(chat.get("connector_access_default") or "use").strip().lower()
    if connector_access_default not in CONNECTOR_ACCESS_LEVELS:
        raise ConfigError("chat.connector_access_default muss none, use, own oder global sein")
    try:
        image_limit_month = int(images.get("limit_month", 30))
    except (TypeError, ValueError):
        raise ConfigError("images.limit_month muss eine Zahl von 0 bis 10000 sein (0 = kein Limit)") from None
    if not 0 <= image_limit_month <= 10000:
        raise ConfigError("images.limit_month muss eine Zahl von 0 bis 10000 sein (0 = kein Limit)")
    voice = _group(raw, "voice", "access_default, browser_stt, output, openai_voice, instructions, chat_days, openai_api_key, openai_key_expires")
    voice_access_default = str(voice.get("access_default") or "off").strip().lower()
    if voice_access_default not in VOICE_ACCESS_LEVELS:
        raise ConfigError("voice.access_default muss on oder off sein")
    voice_output = str(voice.get("output") or "device").strip().lower()
    if voice_output not in ("device", "service"):
        raise ConfigError("voice.output muss device oder service sein")
    voice_openai_voice = str(voice.get("openai_voice") or "nova").strip().lower()
    if voice_openai_voice not in OPENAI_VOICES:
        raise ConfigError("voice.openai_voice muss eine der Stimmen " + ", ".join(OPENAI_VOICES) + " sein")
    voice_instructions = " ".join(str(voice.get("instructions") or "").split())
    if len(voice_instructions) > VOICE_INSTRUCTIONS_MAX:
        raise ConfigError(f"voice.instructions darf höchstens {VOICE_INSTRUCTIONS_MAX} Zeichen lang sein")
    try:
        voice_chat_days = int(voice.get("chat_days", 30))
    except (TypeError, ValueError):
        raise ConfigError("voice.chat_days muss eine Zahl von 0 bis 365 sein (0 = behalten)") from None
    if not 0 <= voice_chat_days <= 365:
        raise ConfigError("voice.chat_days muss eine Zahl von 0 bis 365 sein (0 = behalten)")
    image_provider = str(images.get("provider") or "auto").strip().lower()
    if image_provider not in ("auto", "openai", "google"):
        raise ConfigError("images.provider muss auto, openai oder google sein")
    model = str(chat.get("model") or "claude-sonnet-5-5").strip()
    if not re.match(r"^[A-Za-z0-9._-]{3,64}$", model):
        raise ConfigError("Ungültiger Modellname")
    restore = str(raw.get("restore_snapshot") or "").strip()
    if restore and not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,100}\.sqlite3$", restore):
        raise ConfigError("restore_snapshot muss ein Dateiname aus dem Ordner snapshots sein (endet auf .sqlite3)")
    token_expires = _parse_date(raw.get("claude_token_expires"), "claude_token_expires")
    secret_expires = _parse_date(raw.get("entra_secret_expires"), "entra_secret_expires")
    openai_key_expires = _parse_date(images.get("openai_key_expires"), "images.openai_key_expires")
    google_key_expires = _parse_date(images.get("google_key_expires"), "images.google_key_expires")

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
        openai_enabled=bool(chat.get("openai_enabled", False)),
        openai_chat_api_key=str(chat.get("openai_api_key") or "").strip(),
        openai_chat_key_expires=_parse_date(chat.get("openai_key_expires"), "chat.openai_key_expires"),
        openai_models=openai_models,
        openai_limit_month=openai_limit_month,
        schedules_enabled=bool(chat.get("schedules_enabled", True)),
        incognito_enabled=bool(chat.get("incognito_enabled", True)),
        sharing=sharing,
        research_enabled=bool(chat.get("research_enabled", False)),
        research_daily_limit=research_daily_limit,
        restore_snapshot=restore,
        export_database=bool(raw.get("export_database", False)),
        claude_token_expires=token_expires,
        entra_secret_expires=secret_expires,
        openai_key_expires=openai_key_expires,
        google_key_expires=google_key_expires,
        language=language,
        ha_access_default=ha_access_default,
        ha_limit_to_exposed=bool(raw.get("ha_limit_to_exposed", True)),
        memory_enabled=bool(chat.get("memory_enabled", True)),
        github_access_default=github_access_default,
        connector_access_default=connector_access_default,
        files_enabled=bool(chat.get("files_enabled", True)),
        openai_api_key=str(images.get("openai_api_key") or "").strip(),
        google_api_key=str(images.get("google_api_key") or "").strip(),
        image_provider=image_provider,
        image_limit_month=image_limit_month,
        voice_access_default=voice_access_default,
        voice_output=voice_output,
        voice_browser_stt=bool(voice.get("browser_stt", True)),
        voice_openai_api_key=str(voice.get("openai_api_key") or "").strip(),
        voice_openai_key_expires=_parse_date(voice.get("openai_key_expires"), "voice.openai_key_expires"),
        voice_chat_days=voice_chat_days,
        voice_instructions=voice_instructions,
        voice_openai_voice=voice_openai_voice,
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


BACKUP_NAME = "options-backup.json"
PENDING_KEY = "_pending"  # in der Sicherung: Werte aus der alten Gliederung, die noch in die neuen Gruppen übernommen werden


def save_options_backup(raw: dict[str, Any], path: Path, pending: dict[str, Any] | None = None) -> None:
    """Legt eine Kopie der Optionen neben ``options.json`` ab (nur wenn sie sich geändert hat).

    Grund: Ändert sich die Gliederung der Add-on-Konfiguration, wirft der Supervisor Einträge weg, die nicht mehr im Schema
    stehen. Mit der Kopie aus dem Stand davor kann eine spätere Version die alten Werte übernehmen. Die Datei liegt im
    Datenordner wie ``options.json`` selbst (Rechte 0600) und steckt in jeder Sicherung des Add-ons.
    """
    target = Path(path).with_name(BACKUP_NAME)
    try:
        text = json.dumps({**raw, PENDING_KEY: pending or {}}, ensure_ascii=False, indent=1, sort_keys=True)
        if target.exists() and target.read_text(encoding="utf-8") == text:
            return
        tmp = target.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, target)
    except OSError as exc:
        logging.getLogger("copilot.config").warning("Sicherung der Optionen nicht möglich: %s", type(exc).__name__)


def _read_backup(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(Path(path).with_name(BACKUP_NAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def load_settings(path: Path = OPTIONS_PATH) -> Settings:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Optionen nicht lesbar: {exc}") from exc
    taken: list[str] = []
    if isinstance(raw, dict):
        raw, taken, pending = migrate_options(raw, _read_backup(path))
        save_options_backup(raw, path, pending)

    override = os.environ.get("COPILOT_INGRESS_PEERS")
    peers = (
        frozenset(p.strip() for p in override.split(",") if p.strip()) if override else None
    )
    settings = parse_settings(raw, peers)
    return dataclasses.replace(settings, migrated_options=tuple(taken)) if taken else settings
