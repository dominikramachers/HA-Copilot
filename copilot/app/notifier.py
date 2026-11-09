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
from collections.abc import Callable
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
