"""Benachrichtigung aufs Handy, wenn eine Antwort ungelesen bleibt.

Ablauf: Ist eine Antwort fertig und hat die Person den Chat auf keinem Gerät offen, wartet das Add-on kurz
(``NOTIFY_DELAY_SECONDS``, damit ein Wechsel des Chats oder ein Neuladen nichts auslöst) und prüft dann noch
einmal. Ist der Chat dann noch ungelesen und niemand sieht ihn an, geht eine Meldung an die Geräte der Person
(Home-Assistant-App, ``notify.mobile_app_*``). Wird der Chat danach irgendwo gelesen, verschwindet die Meldung
von den Geräten wieder.

„Chat offen“ meldet die Oberfläche selbst (``Presence``): sichtbarer Tab mit diesem Chat, alle 20 Sekunden erneuert.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any
import weakref

from .config import Profile, Settings
from .db import Store
from .ha_client import HaApi, HaApiError
from .i18n import tr

log = logging.getLogger("ki.notifier")

NOTIFY_DELAY_SECONDS = 10  # Schonfrist, bevor eine ungelesene Antwort gemeldet wird
PRESENCE_TTL = 45  # so lange gilt „Chat ist offen“ nach der letzten Meldung der Oberfläche
EXCERPT = 300  # Länge des Antworttextes in der Meldung (das Telefon kürzt selbst, wenn es nicht passt)
SERVICE_PREFIX = "notify.mobile_app_"
_SERVICE_RE = re.compile(r"^notify\.mobile_app_[a-z0-9_]{1,80}$")
ICON_DOMAIN = "enhanced_notify"  # Integration „Enhanced Notify“: ihr Standard-Icon für Push-Meldungen gilt auch hier
ICON_OPTION = "push_icon"
ICON_CACHE_SECONDS = 600  # so lange gilt der gelesene Wert (Änderungen in Enhanced Notify kommen spätestens dann an)
_ICON_RE = re.compile(r"^(?:/(?!/)\S+|https?://\S+)$")  # wie in Enhanced Notify: Pfad (/local/…) oder Adresse


class Presence:
    """Wer sieht gerade welchen Chat an? Nur im Arbeitsspeicher, gilt für Ingress und Domain zusammen."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._seen: dict[str, dict[str, tuple[str, float]]] = {}

    def seen(self, profile_id: str, client: str, chat_id: str | None) -> None:
        clients = self._seen.setdefault(profile_id, {})
        if chat_id:
            clients[client] = (chat_id, self._clock())
        else:
            clients.pop(client, None)
        self._expire(profile_id)

    def watching(self, profile_id: str, chat_id: str) -> bool:
        self._expire(profile_id)
        return any(chat == chat_id for chat, _ in self._seen.get(profile_id, {}).values())

    def active(self, profile_id: str) -> bool:
        """Hat die Person die Oberfläche gerade irgendwo sichtbar offen (egal ob Chat oder eine andere Seite)?"""
        self._expire(profile_id)
        return bool(self._seen.get(profile_id))

    def _expire(self, profile_id: str) -> None:
        clients = self._seen.get(profile_id)
        if not clients:
            return
        now = self._clock()
        for client in [c for c, (_, at) in clients.items() if now - at > PRESENCE_TTL]:
            del clients[client]
        if not clients:
            del self._seen[profile_id]


def label_of(service: str) -> str:
    """``notify.mobile_app_ipad_von_sina`` → „Ipad von sina“ (der Name, den Home Assistant dem Gerät gibt)."""
    name = service.removeprefix(SERVICE_PREFIX).replace("_", " ").strip()
    return name[:1].upper() + name[1:]


class Notifier:
    def __init__(self, store: Store, settings: Settings, ha: HaApi | None, presence: Presence, *, delay: float | None = None) -> None:
        self.store = store
        self.settings = settings
        self.ha = ha
        self.presence = presence
        self.delay = NOTIFY_DELAY_SECONDS if delay is None else delay
        self._sent: dict[tuple[str, str], list[str]] = {}  # (Person, Chat) → Geräte, die gerade eine Meldung zeigen
        self._tasks: set[asyncio.Task] = set()
        self._icon: tuple[float, str | None] | None = None  # (Zeitpunkt, Icon) aus Enhanced Notify

    # ------------------------------------------------------------ Einstellungen je Person

    @property
    def available(self) -> bool:
        return self.ha is not None and self.ha.enabled

    def _stored(self, profile: Profile) -> dict | None:
        raw = self.store.state_get(f"notify:{profile.id}")
        if not raw:
            return None
        try:
            value = json.loads(raw)
        except ValueError:
            return None
        return value if isinstance(value, dict) else None

    def enabled(self, profile: Profile) -> bool:
        stored = self._stored(profile)
        return bool(stored.get("enabled", True)) if stored else True

    def has_choice(self, profile: Profile) -> bool:
        stored = self._stored(profile)
        return bool(stored and stored.get("devices"))

    def save(self, profile: Profile, enabled: bool, services: list[str]) -> None:
        clean = [s for s in dict.fromkeys(services) if _SERVICE_RE.match(s)]
        self.store.state_set(f"notify:{profile.id}", json.dumps({"enabled": bool(enabled), "devices": clean}))

    async def _services(self) -> list[str]:
        """Alle Geräte, auf denen die Home-Assistant-App angemeldet ist (``notify.mobile_app_*``)."""
        if not self.available:
            return []
        try:
            data = await self.ha.call({"type": "get_services"})  # type: ignore[union-attr]
        except HaApiError as exc:
            log.info("Benachrichtigungsdienste nicht abrufbar: %s", exc)
            return []
        names = data.get("notify") if isinstance(data, dict) else None
        return sorted(f"notify.{n}" for n in (names or {}) if str(n).startswith("mobile_app_"))

    async def _own(self, profile: Profile, services: list[str]) -> list[str]:
        """Geräte der Person in Home Assistant: die Geräteverfolger ihrer Personen-Entität, zugeordnet über den Benutzer."""
        uid = (profile.ha_user_id or "").lower()
        if not uid or not self.available:
            return []
        try:
            data = await self.ha.call({"type": "person/list"})  # type: ignore[union-attr]
        except HaApiError:
            return []
        found: list[str] = []
        for entry in (data or {}).get("storage", []) + (data or {}).get("config", []) if isinstance(data, dict) else []:
            if not isinstance(entry, dict) or str(entry.get("user_id") or "").lower() != uid:
                continue
            for tracker in entry.get("device_trackers") or []:
                service = SERVICE_PREFIX + str(tracker).partition(".")[2]
                if service in services and service not in found:
                    found.append(service)
        return found

    async def allowed(self, profile: Profile, services: list[str] | None = None) -> list[str]:
        """Geräte, die diese Person nutzen darf: nur die, die in Home Assistant zu ihr gehören, dazu ein vom Administrator
        eingetragener ``notify_service``. Fremde Geräte tauchen weder in der Auswahl auf noch bekommen sie Meldungen."""
        services = services if services is not None else await self._services()
        found = await self._own(profile, services)
        if profile.notify_service and profile.notify_service in services and profile.notify_service not in found:
            found.append(profile.notify_service)
        return found

    async def devices(self, profile: Profile) -> dict[str, Any]:
        """Für die Einstellungen: die eigenen Geräte, welche davon gewählt sind, ob die Meldung an ist."""
        allowed = await self.allowed(profile)
        chosen = await self.selected(profile, allowed=allowed)
        rows = [{"service": s, "label": label_of(s), "selected": s in chosen} for s in allowed]
        rows.sort(key=lambda r: r["label"].lower())
        return {"enabled": self.enabled(profile), "devices": rows, "delay": int(self.delay)}

    async def selected(self, profile: Profile, *, allowed: list[str] | None = None) -> list[str]:
        """Geräte, die Meldungen bekommen: die gewählten (soweit sie noch zur Person gehören); sonst ``notify_service``; sonst alle eigenen."""
        allowed = allowed if allowed is not None else await self.allowed(profile)
        stored = self._stored(profile)
        if stored and stored.get("devices"):
            return [s for s in stored["devices"] if s in allowed]
        if profile.notify_service and profile.notify_service in allowed:
            return [profile.notify_service]
        return list(allowed)

    # ------------------------------------------------------------ Logo

    async def push_icon(self) -> str | None:
        """Das Standard-Icon aus den Einstellungen von Enhanced Notify (``push_icon``), sonst ``None``.

        Die Meldungen des Copilot gehen direkt an die Handys und bekämen sonst das Logo von Home Assistant. Das Add-on
        liest das Icon selbst: Es öffnet das Optionsformular von Enhanced Notify, liest den vorgeschlagenen Wert und
        bricht das Formular wieder ab (es wird nichts verändert). Das Ergebnis, auch „kein Icon“, bleibt zehn Minuten.
        """
        now = time.monotonic()
        if self._icon is not None and now - self._icon[0] < ICON_CACHE_SECONDS:
            return self._icon[1]
        value: str | None = None
        try:
            value = await self._read_icon()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - ohne Icon geht die Meldung trotzdem raus
            log.info("Icon von Enhanced Notify nicht gelesen: %s", exc)
        self._icon = (now, value)
        return value

    async def _read_icon(self) -> str | None:
        if self.ha is None or not self.available:
            return None
        entries = await self.ha.call({"type": "config_entries/get", "domain": ICON_DOMAIN})
        entry = next((e for e in entries or [] if isinstance(e, dict) and e.get("domain") == ICON_DOMAIN and e.get("state") == "loaded"), None)
        if not entry or not entry.get("entry_id"):
            return None
        flow = await self.ha.rest("POST", "/config/config_entries/options/flow", {"handler": entry["entry_id"]})
        try:
            for field in (flow or {}).get("data_schema") or []:
                if isinstance(field, dict) and field.get("name") == ICON_OPTION:
                    suggested = (field.get("description") or {}).get("suggested_value")
                    value = str(suggested or "").strip()
                    return value if _ICON_RE.match(value) else None
            return None
        finally:
            flow_id = (flow or {}).get("flow_id")
            if flow_id:
                try:
                    await self.ha.rest("DELETE", f"/config/config_entries/options/flow/{flow_id}")
                except HaApiError as exc:
                    log.info("Optionsformular von Enhanced Notify nicht beendet: %s", exc)

    # ------------------------------------------------------------ Senden

    def spawn(self, profile: Profile, chat_id: str, text: str, title: str = "") -> None:
        """Im Hintergrund: Antwort ist fertig, bei Bedarf melden."""
        task = asyncio.ensure_future(self.announce(profile, chat_id, text, title))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def spawn_clear(self, profile_id: str, chat_id: str) -> None:
        if (profile_id, chat_id) not in self._sent:
            return
        task = asyncio.ensure_future(self.clear(profile_id, chat_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def announce(self, profile: Profile, chat_id: str, text: str, title: str = "") -> bool:
        """Meldet eine ungelesene Antwort. Liefert ``True``, wenn eine Meldung rausging."""
        if not self.available or not self.enabled(profile) or self.presence.watching(profile.id, chat_id):
            return False
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        chat = self.store.get_chat(profile.id, chat_id)
        if not chat or not chat.get("unread") or self.presence.watching(profile.id, chat_id):
            return False
        devices = await self.selected(profile)
        if not devices:
            return False
        data: dict[str, Any] = {"tag": f"copilot-{chat_id}", "group": "copilot"}
        base = self.settings.public_base_url
        if base:
            data.update(url=base, clickAction=base)
        icon = await self.push_icon()
        if icon:
            data["icon_url"] = icon  # dasselbe Logo wie bei Enhanced Notify statt dem von Home Assistant
        # Wie eine Chat-Nachricht: oben der Chat-Titel, darunter die Antwort.
        payload = {"title": (title or chat.get("title") or self.settings.app_name)[:120], "message": text or tr("Antwort fertig"), "data": data}
        sent: list[str] = []
        for device in devices:
            _, _, name = device.partition(".")
            try:
                await self.ha.call({"type": "call_service", "domain": "notify", "service": name, "service_data": payload})  # type: ignore[union-attr]
                sent.append(device)
            except HaApiError as exc:
                log.warning("Benachrichtigung an %s fehlgeschlagen: %s", device, exc)
        if sent:
            self._sent[(profile.id, chat_id)] = sent
        return bool(sent)

    def spawn_text(self, profile: Profile, tag: str, title: str, message: str, *, fallback: Callable[[], Awaitable[None]] | None = None) -> None:
        """Im Hintergrund: einen Hinweis aufs Handy schicken, falls die Person die Oberfläche gerade nicht offen hat."""
        task = asyncio.ensure_future(self._text_then_fallback(profile, tag, title, message, fallback))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _text_then_fallback(self, profile: Profile, tag: str, title: str, message: str, fallback: Callable[[], Awaitable[None]] | None) -> None:
        try:
            result = await self.announce_text(profile, tag, title, message)
            if result == "nodevice" and fallback is not None:
                await fallback()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("Hinweis aufs Handy fehlgeschlagen", exc_info=True)

    async def announce_text(self, profile: Profile, tag: str, title: str, message: str) -> str:
        """Hinweis ohne Chat (zum Beispiel „Ein Server wartet“). Ergebnis: ``sent`` (rausgegangen), ``present`` (die Person ist in der
        Oberfläche, nichts nötig), ``off`` (Meldungen ausgeschaltet) oder ``nodevice`` (kein Gerät oder Home Assistant nicht erreichbar)."""
        if not self.enabled(profile):
            return "off"
        if self.presence.active(profile.id):
            return "present"
        if self.delay > 0:
            await asyncio.sleep(self.delay)  # Schonfrist: ein Neuladen oder Seitenwechsel löst nichts aus
            if self.presence.active(profile.id):
                return "present"
        devices = await self.selected(profile) if self.available else []
        if not devices:
            return "nodevice"
        data: dict[str, Any] = {"tag": tag, "group": "copilot"}
        base = self.settings.public_base_url
        if base:
            data.update(url=base, clickAction=base)
        icon = await self.push_icon()
        if icon:
            data["icon_url"] = icon
        payload = {"title": title[:120], "message": message[:300], "data": data}
        sent = 0
        for device in devices:
            _, _, name = device.partition(".")
            try:
                await self.ha.call({"type": "call_service", "domain": "notify", "service": name, "service_data": payload})  # type: ignore[union-attr]
                sent += 1
            except HaApiError as exc:
                log.warning("Benachrichtigung an %s fehlgeschlagen: %s", device, exc)
        return "sent" if sent else "nodevice"

    async def clear(self, profile_id: str, chat_id: str) -> None:
        """Der Chat wurde gelesen: die Meldung von den Geräten entfernen."""
        for device in self._sent.pop((profile_id, chat_id), []):
            _, _, name = device.partition(".")
            try:
                await self.ha.call({"type": "call_service", "domain": "notify", "service": name,  # type: ignore[union-attr]
                                    "service_data": {"message": "clear_notification", "data": {"tag": f"copilot-{chat_id}"}}})
            except HaApiError as exc:
                log.info("Meldung auf %s nicht entfernt: %s", device, exc)

    async def idle(self) -> None:
        await asyncio.gather(*list(self._tasks), return_exceptions=True)


_PRESENCE: "weakref.WeakKeyDictionary[Store, Presence]" = weakref.WeakKeyDictionary()
_NOTIFIERS: "weakref.WeakKeyDictionary[Store, Notifier]" = weakref.WeakKeyDictionary()


def presence_for(store: Store) -> Presence:
    value = _PRESENCE.get(store)
    if value is None:
        value = _PRESENCE[store] = Presence()
    return value


def notifier_for(store: Store, settings: Settings, ha: HaApi | None) -> Notifier:
    """Ein Melder je Datenbank, gemeinsam für Ingress und Domain (beide laufen im selben Prozess)."""
    value = _NOTIFIERS.get(store)
    if value is None or value.ha is not ha or value.settings is not settings:
        value = _NOTIFIERS[store] = Notifier(store, settings, ha, presence_for(store))
    return value
