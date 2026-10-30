"""Geplante Aufgaben: zur Uhrzeit läuft ein Auftrag ohne dass jemand zusieht, das Ergebnis steht danach in einem neuen Chat.

Ein solcher Lauf ist bewusst enger gefasst als ein Chat, in dem jemand zuschaut:

* Home Assistant nur **lesen** (höchstens die Stufe „read“, auch wenn die Person mehr darf),
* GitHub nur **lesen**,
* Gedächtnis nur **lesen**,
* **keine Rückfragen** (es ist niemand da, der sie beantworten könnte); alles, was eine Rückfrage bräuchte, ist gar nicht
  erst angeboten,
* erlaubt bleiben Websuche (je Aufgabe abschaltbar) und erzeugte Dateien zum Herunterladen.

Das Ergebnis ist ein ganz normaler Chat der Person (ungelesen markiert, mit Uhr-Symbol in der Liste); Rückfragen dazu
laufen im normalen Chat mit den Rechten der Person weiter. Optional kommt eine Benachrichtigung in Home Assistant.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from . import schedule as sched
from .i18n import tr
from .backend import BackendError
from .config import Profile, Settings
from .context_tools import ContextToolbox
from .github_api import GithubApi
from .github_tools import GITHUB_NOTE, GithubToolbox, RepoPolicy, level_text as github_level_text
from .ha_client import HaApi, HaApiError
from .ha_tools import HaToolbox
from .identity import Registry
from .limits import LimitState
from .outbox import OutboxToolbox
from .web_tools import WEB_NOTE, WebToolbox

log = logging.getLogger("ki_chat.scheduler")

TICK_SECONDS = 30
START_DELAY = 20  # nach dem Start Home Assistant erst hochfahren lassen
GRACE_SECONDS = 2 * 3600  # so lange nach dem Zeitpunkt wird eine versäumte Aufgabe noch nachgeholt, danach übersprungen
RUN_TIMEOUT = 1200  # Sekunden je Lauf
MAX_PARALLEL = 2  # gleichzeitige KI-Anfragen insgesamt (wie in main)
NAME_MAX = 60
PROMPT_MAX = 4000
NOTIFY_MODES = ("chat", "ha", "phone")  # nur im Chat | Meldung in Home Assistant | Benachrichtigung aufs Handy
NOTIFY_EXCERPT = 300

SCHEDULED_NOTE = (
    "Dies ist eine geplante Aufgabe, die automatisch zur eingestellten Zeit läuft. Niemand schaut zu und niemand kann dir "
    "antworten: Stelle keine Rückfragen, sondern liefere das bestmögliche Ergebnis mit den Angaben, die du hast, und nenne am "
    "Ende kurz, was du angenommen hast oder nicht herausfinden konntest. Du darfst in dieser Aufgabe nur lesen (Home Assistant, "
    "GitHub, Gedächtnis); Änderungen sind nicht möglich und werden nicht verlangt. Beginne direkt mit dem Ergebnis, ohne "
    "Einleitung wie „Gerne“. Die Antwort wird später gelesen: Schreibe sie so, dass sie ohne den Auftrag verständlich ist."
)


async def _no_ask(label: str, details: str, offer_chat: bool) -> str:
    return "deny"  # Rückfragen gibt es in geplanten Läufen nicht


def plain_excerpt(markdown: str, limit: int = NOTIFY_EXCERPT) -> str:
    """Antwort als schlichter Kurztext für eine Benachrichtigung (ohne Markdown-Zeichen)."""
    text = re.sub(r"```.*?```", " ", markdown, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"(?m)^\s{0,3}(#{1,6}|[-*+>]|\d+[.)])\s+", "", text)
    text = re.sub(r"[*_`~|]+", "", text)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class Scheduler:
    def __init__(
        self,
        settings: Settings,
        store: Any,
        backend: Any,
        registry: Registry,
        ha: HaApi,
        github: GithubApi,
        limits: LimitState,
        runs: dict,
        new_run: Callable[[tuple[str, str], str], Any],
        *,
        clock: Callable[[], float] = time.time,
        backup_dir: Any = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.backend = backend
        self.registry = registry
        self.ha = ha
        self.github = github
        self.limits = limits
        self.runs = runs
        self.new_run = new_run
        self.clock = clock
        self.policy = RepoPolicy(settings.github_repos)
        self._tasks: set[asyncio.Task] = set()
        self.live: dict[str, tuple[str, str]] = {}  # Aufgabe → Schlüssel des laufenden Laufs

    # ---------------------------------------------------------------- Hilfen

    def profile_for(self, profile_id: str) -> Profile | None:
        """Person zur ID: aus der Konfiguration, sonst ein früher automatisch zugelassener Home-Assistant-Benutzer."""
        found = self.registry.by_id(profile_id)
        if found is not None:
            return found
        if self.registry.auto_admit:  # alle HA-Benutzer zugelassen: Profil nach einem Neustart aus der Datenbank
            recalled = self.store.recall_ha_profile(profile_id)
            if recalled:
                return Profile(profile_id, recalled[0] or profile_id, recalled[1], "")
        return None

    def active_runs(self) -> int:
        return sum(1 for r in self.runs.values() if not r.finished)

    def ha_level(self, profile: Profile) -> str:
        """Geplante Läufe lesen höchstens, auch wenn die Person mehr darf."""
        if not self.ha.enabled:
            return "none"
        return "none" if (profile.ha_access or self.settings.ha_access_default) == "none" else "read"

    def github_level(self, profile: Profile) -> str:
        if not self.github.enabled:
            return "none"
        return "none" if (profile.github_access or self.settings.github_access_default) == "none" else "read"

    def model_for(self, row: dict) -> str | None:
        wanted = row.get("model") or ""
        known = {m["id"] for m in self.settings.model_choices()}
        return wanted if wanted in known and wanted != self.settings.model else None

    def following(self, row: dict, now: float | None = None) -> int | None:
        moment = datetime.fromtimestamp(now if now is not None else self.clock())
        return sched.next_timestamp(row["freq"], row["at"], row["days"], moment)

    # ----------------------------------------------------------------- Takt

    async def sync_timezone(self) -> bool:
        """Zeitzone von Home Assistant übernehmen: Sie bestimmt, was „07:30 Uhr“ bedeutet. ``True``, wenn Home Assistant geantwortet hat."""
        try:
            config = await self.ha.call({"type": "get_config"})
        except HaApiError as exc:
            log.info("Zeitzone von Home Assistant nicht abrufbar, es gilt %s: %s", os.environ.get("TZ") or "die Zeitzone des Systems", exc)
            return False
        zone = str((config or {}).get("time_zone") or "") if isinstance(config, dict) else ""
        if not zone:
            return True
        try:
            ZoneInfo(zone)
        except Exception:
            log.warning("Zeitzone %r von Home Assistant ist hier unbekannt, es gilt %s", zone, os.environ.get("TZ") or "die Zeitzone des Systems")
            return True
        if os.environ.get("TZ") != zone:
            os.environ["TZ"] = zone
            time.tzset()
            for profile_id, row in self.store.schedule_enabled():
                self.store.schedule_set_next(row["id"], self.following(row))  # Zeitpunkte in der richtigen Zeitzone neu berechnen
        log.info("Zeitzone für geplante Aufgaben: %s", zone)
        return True

    async def loop(self) -> None:
        """Alle ``TICK_SECONDS`` nach fälligen Aufgaben sehen."""
        await asyncio.sleep(START_DELAY)
        synced = False
        while True:
            try:
                if not synced:
                    synced = await self.sync_timezone()
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Geplante Aufgaben: Durchgang fehlgeschlagen")
            await asyncio.sleep(TICK_SECONDS)

    async def tick(self) -> int:
        """Fällige Aufgaben starten (höchstens so viele, wie parallel laufen dürfen). Liefert die Zahl der gestarteten."""
        if not self.settings.schedules_enabled:
            return 0
        now = int(self.clock())
        started = 0
        for row in self.store.schedule_due(now):
            profile_id = row.pop("profile_id")
            due = row["next_run"]
            upcoming = self.following(row, now)
            profile = self.profile_for(profile_id)
            if profile is None:
                if self.store.schedule_claim(row["id"], due, upcoming):
                    self.store.schedule_record(row["id"], status="skipped", note=tr("Die Person ist in der Konfiguration nicht mehr eingetragen."), ran=False)
                continue
            if now - due > GRACE_SECONDS:
                if self.store.schedule_claim(row["id"], due, upcoming):
                    self.store.schedule_record(row["id"], status="skipped", note=tr("Übersprungen: Das Add-on war zum Zeitpunkt nicht aktiv."), ran=False)
                continue
            rejected = next((i for i in self.limits.current() if i["status"] == "rejected"), None)
            if rejected:
                if self.store.schedule_claim(row["id"], due, upcoming):
                    self.store.schedule_record(row["id"], status="skipped", note=tr("Übersprungen: Das Nutzungslimit des Abos war erreicht."), ran=False)
                continue
            if self.active_runs() >= MAX_PARALLEL or started:
                break  # später erneut versuchen; die Aufgabe bleibt fällig
            if not self.store.schedule_claim(row["id"], due, upcoming):
                continue
            row["next_run"] = upcoming
            try:
                self.start(row, profile)
                started += 1
            except Exception:
                log.exception("Geplante Aufgabe %s konnte nicht gestartet werden", row["id"])
                self.store.schedule_record(row["id"], status="error", note=tr("Die Aufgabe konnte nicht gestartet werden."), ran=False)
        return started

    # ------------------------------------------------------------------ Lauf

    def start(self, row: dict, profile: Profile, *, manual: bool = False) -> str:
        """Chat anlegen, Auftrag als erste Nachricht eintragen und den Lauf im Hintergrund starten. Liefert die Chat-ID."""
        stamp = datetime.fromtimestamp(self.clock())
        title = f"{row['name'][:NAME_MAX]} · {stamp:%d.%m. %H:%M}" if manual else f"{row['name'][:NAME_MAX]} · {stamp:%d.%m.}"
        chat = self.store.create_chat(profile.id, title, None, schedule_id=row["id"])
        if chat is None:
            raise RuntimeError(tr("Chat konnte nicht angelegt werden"))
        self.store.add_message(profile.id, chat["id"], "user", row["prompt"])
        key = (profile.id, chat["id"])
        run = self.new_run(key, row["prompt"])
        self.runs[key] = run
        self.live[row["id"]] = key
        task = asyncio.create_task(self._execute(row, profile, run, chat["id"], title))
        run.task = task
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return chat["id"]

    def _specs(self, row: dict, profile: Profile, run: Any, chat_id: str, extra: dict) -> list:
        settings = self.settings
        specs: list = []
        level = self.ha_level(profile)
        if level != "none":
            specs += HaToolbox(
                self.ha, "read",
                limit_to_exposed=settings.ha_limit_to_exposed, confirm_writes=True, force_confirm=True,
                ask=_no_ask, record=run.push, chat_allowed=lambda: False, allow_chat=lambda: None,
                next_id=run.next_tool_id,
            ).specs()
        context = ContextToolbox(
            self.store, profile.id, profile.label,
            project_id=None, memory_enabled=settings.memory_enabled, household_write=False, force_confirm=True,
            ask=_no_ask, record=run.push, next_id=run.next_tool_id, tainted=lambda: True,
            overview=settings.memory_enabled and level != "none", read_only=True,
        )
        specs += context.specs()
        if settings.files_enabled:
            specs += OutboxToolbox(
                self.store, profile.id, chat_id, record=run.push, next_id=run.next_tool_id,
                keep_days=settings.files_keep_days, author=settings.app_name, edit=settings.files_edit,
            ).specs()
        gh = self.github_level(profile)
        if gh != "none":
            specs += GithubToolbox(
                self.github, "read", policy=self.policy, confirm_writes=True, force_confirm=lambda: True,
                ask=_no_ask, record=run.push, chat_allowed=lambda: False, allow_chat=lambda: None,
                next_id=run.next_tool_id,
            ).specs()
        web = settings.web_level(profile) == "on" and row.get("web", True)
        if web:
            specs += WebToolbox(run.push, run.next_tool_id).specs()
            extra.update(web=True, record=run.push, next_id=run.next_tool_id)
        note = context.note([p.label or p.id for p in settings.profiles], level, any(s.name.startswith("ha_") for s in specs))
        note += "\n" + SCHEDULED_NOTE
        if web:
            note += "\n" + WEB_NOTE
        if gh != "none":
            note += "\n" + GITHUB_NOTE + " " + github_level_text("read", self.policy)
        extra["note"] = note
        return specs

    async def _execute(self, row: dict, profile: Profile, run: Any, chat_id: str, title: str) -> None:
        store = self.store
        error: str | None = None
        cancelled = False
        try:
            extra: dict = {"on_limit": self.limits.update}
            model = self.model_for(row)
            if model:
                extra["model"] = model
            specs = self._specs(row, profile, run, chat_id, extra)
            if specs:
                extra["tools"] = specs
            try:
                async with asyncio.timeout(RUN_TIMEOUT):
                    live = self.backend.stream([], row["prompt"], self.settings.default_effort, **extra)
                    async with contextlib.aclosing(live):
                        async for piece in live:
                            if piece:
                                run.push({"type": "delta", "text": piece})
            except BackendError as exc:
                error = exc.user_message
                run.error_resets_at = exc.resets_at
            except TimeoutError:
                error = tr("Zeitüberschreitung: Die Aufgabe hat zu lange gedauert.")
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            log.exception("Geplante Aufgabe fehlgeschlagen")
            error = tr("Unerwarteter Fehler bei der Ausführung.")
        answer = "".join(run.parts).strip()
        status = "ok"
        note = ""
        try:
            if cancelled:
                status, note = "cancelled", tr("Abgebrochen.")
            elif error:
                status, note = "error", error
            elif not answer:
                status, note = "error", tr("Die KI hat keine Antwort geliefert.")
            if status == "error" and not answer:
                answer = tr("_Die Aufgabe konnte nicht ausgeführt werden: {note}_", note=note)
                run.push({"type": "delta", "text": answer})
            if answer:
                store.add_message(profile.id, chat_id, "assistant", answer, tools=run.action_log())
            run.kept = bool(answer)
            run.error = None  # ein Fehler steht als Antwort im Chat, wer zusieht, bekommt sie so angezeigt
            store.schedule_record(row["id"], status=status, note=note, chat_id=chat_id)
        except Exception:
            log.exception("Ergebnis der geplanten Aufgabe konnte nicht gespeichert werden")
        finally:
            for future in list(run.pending.values()):
                if not future.done():
                    future.cancel()
            run.finished = True
            run.finished_at = time.monotonic()
            run.wake()
            if self.runs.get(run.key) is run:
                self.runs.pop(run.key, None)
            if self.live.get(row["id"]) == run.key:
                del self.live[row["id"]]
        if status == "ok":
            failure = await self.notify(profile, row.get("notify", "chat"), row["name"], plain_excerpt(answer), key=row["id"])
            if failure:
                store.schedule_record(row["id"], status="ok", note=failure, ran=False)

    # ---------------------------------------------------------- Benachrichtigung

    async def notify(self, profile: Profile, mode: str, title: str, message: str, *, key: str = "") -> str | None:
        """Benachrichtigung senden (mode: ``ha`` = Meldung in Home Assistant, ``phone`` = Dienst der Person). Liefert eine Fehlermeldung für die Anzeige oder ``None``."""
        if mode == "ha":
            command = {
                "type": "call_service", "domain": "persistent_notification", "service": "create",
                "service_data": {
                    "title": title[:120], "message": (message or tr("Fertig.")) + tr("\n\nDas Ergebnis steht im {app_name}.", app_name=self.settings.app_name),
                    "notification_id": f"ki_chat_{re.sub('[^a-z0-9_]', '', key.lower())[:40] or 'task'}",
                },
            }
        elif mode == "phone":
            service = profile.notify_service
            if not service:
                return tr("Benachrichtigung nicht gesendet: Für dich ist kein Benachrichtigungsdienst eingetragen.")
            domain, _, name = service.partition(".")
            data: dict[str, Any] = {}
            base = self.settings.public_base_url
            if base:
                data = {"url": base, "clickAction": base}
            command = {
                "type": "call_service", "domain": domain, "service": name,
                "service_data": {"title": title[:120], "message": message or tr("Fertig."), **({"data": data} if data else {})},
            }
        else:
            return None
        try:
            await self.ha.call(command)
        except HaApiError as exc:
            log.warning("Benachrichtigung fehlgeschlagen: %s", exc)
            return tr("Die Benachrichtigung konnte nicht gesendet werden (Home Assistant hat sie abgelehnt oder war nicht erreichbar).")
        return None

    async def idle(self) -> None:
        """Auf alle laufenden Aufgaben warten (für Tests und geordnetes Beenden)."""
        await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
