"""Überblick über Home Assistant: einmal einlesen, kompakt im Haushaltsgedächtnis ablegen.

Damit die KI die Smarthome-Umgebung von Anfang an kennt (Bereiche, Geräte, Automationen, Integrationen …), liest das Add-on
sie beim ersten Start und danach in festen Abständen selbst ein; ganz ohne KI-Aufruf, nur mit lesenden Abfragen an Home
Assistant. Das Ergebnis sind normale Haushaltseinträge (Verfasser ``ha-scan``, Thema beginnt mit ``HA · ``), die bei jedem
Lauf vollständig ersetzt werden. Alles hier ist rein lesend; Zugangsdaten, Koordinaten und Zustandswerte werden nicht gespeichert.

* ``collect`` holt die Rohdaten (mit Fortschrittsmeldung), ``build_entries`` formt sie zu Einträgen (reine Funktion, gut testbar).
* ``OverviewScanner`` verwaltet Lauf und Status (läuft / fertig / Fehler) und merkt sich das Ergebnis in der Datenbank.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from .i18n import tr
from .context_tools import _SECRET, CONTENT_MAX, TOPIC_MAX
from .db import AUTO_AUTHOR, AUTO_PREFIX, Store
from .ha_client import HaApi, HaApiError

log = logging.getLogger("copilot.scan")

STATE_KEY = "ha_overview"
QUERY_TIMEOUT = 40.0
RETRY_AFTER = 900  # Sekunden bis zum nächsten automatischen Versuch nach einem Fehler
MAX_AREAS = 60
STEPS = (
    "System und Einstellungen",
    "Etagen und Bereiche",
    "Geräte und Entitäten",
    "Integrationen",
    "Automationen, Skripte und Szenen",
    "Personen, Zonen und Dashboards",
    "Zusammenfassen",
)

# Domänen, die man schaltet oder steuert; diese listet der Überblick je Bereich einzeln auf.
CONTROL = (
    "light", "switch", "cover", "climate", "fan", "media_player", "lock", "vacuum", "camera", "alarm_control_panel",
    "water_heater", "humidifier", "valve", "siren", "lawn_mower", "remote", "button", "scene", "input_boolean",
)
SENSOR = ("sensor", "binary_sensor")
CONTROL_NAME = {
    "light": "Licht", "switch": "Schalter", "cover": "Rollläden/Tore", "climate": "Klima", "fan": "Lüfter",
    "media_player": "Medien", "lock": "Schlösser", "vacuum": "Saugroboter", "camera": "Kameras",
    "alarm_control_panel": "Alarm", "water_heater": "Warmwasser", "humidifier": "Luftbefeuchter", "valve": "Ventile",
    "siren": "Sirenen", "lawn_mower": "Mähroboter", "remote": "Fernbedienungen", "button": "Tasten", "scene": "Szenen",
    "input_boolean": "Schalter (Helfer)",
}
HELPER_DOMAINS = ("input_boolean", "input_number", "input_select", "input_text", "input_datetime", "input_button", "counter", "timer", "schedule")
DOMAIN_NAME = {
    "light": "Lichter", "switch": "Schalter", "sensor": "Sensoren", "binary_sensor": "Binärsensoren", "cover": "Rollläden/Tore",
    "climate": "Klimageräte", "fan": "Lüfter", "media_player": "Mediengeräte", "lock": "Schlösser", "camera": "Kameras",
    "automation": "Automationen", "script": "Skripte", "scene": "Szenen", "person": "Personen", "device_tracker": "Geräte-Tracker",
    "weather": "Wetter", "update": "Updates", "button": "Tasten", "number": "Zahlenwerte", "select": "Auswahlen", "text": "Textfelder",
    "todo": "Aufgabenlisten", "calendar": "Kalender", "vacuum": "Saugroboter", "alarm_control_panel": "Alarmanlagen",
    "water_heater": "Warmwasser", "humidifier": "Luftbefeuchter", "event": "Ereignisse", "tts": "Sprachausgabe", "stt": "Spracheingabe",
    "conversation": "Assist-Agenten", "assist_satellite": "Assist-Satelliten", "sun": "Sonne", "zone": "Zonen", "image": "Bilder",
    "valve": "Ventile", "siren": "Sirenen", "lawn_mower": "Mähroboter", "remote": "Fernbedienungen", "notify": "Benachrichtigungen",
}


def _entity_name(entity_id: str, friendly: str) -> str:
    """„kueche_decke (Deckenlicht)“ – Objekt-ID plus Anzeigename, wenn dieser etwas Neues sagt."""
    obj = entity_id.split(".", 1)[1]
    friendly = " ".join((friendly or "").split())
    flat = re.sub(r"[^a-z0-9]", "", friendly.lower())
    if not friendly or flat == re.sub(r"[^a-z0-9]", "", obj):
        return obj
    return f"{obj} ({friendly[:40]})"


def _chunks(topic: str, parts: list[str], head: str = "", sep: str = "; ") -> list[tuple[str, str]]:
    """Teile auf Einträge von höchstens ``CONTENT_MAX`` Zeichen auf; Folgeeinträge heißen „… (2)“."""
    topic = topic[:TOPIC_MAX - 5]
    out: list[tuple[str, str]] = []
    current: list[str] = []
    size = len(head)

    def flush() -> None:
        if current:
            out.append((topic if not out else f"{topic} ({len(out) + 1})", head + sep.join(current)))

    for part in parts:
        part = part[:CONTENT_MAX - len(head) - 4]
        add = len(part) + (len(sep) if current else 0)
        if current and size + add > CONTENT_MAX:
            flush()
            current, size, add = [], len(head), len(part)
        current.append(part)
        size += add
    flush()
    return out


def _grouped(items: dict[str, list[str]], names: dict[str, str], cap: int = 25) -> list[str]:
    parts = []
    for domain, values in items.items():
        label = names.get(domain, domain)
        shown = values[:cap]
        more = f", … +{len(values) - cap}" if len(values) > cap else ""
        parts.append(f"{label} ({len(values)}): " + ", ".join(shown) + more)
    return parts


# ------------------------------------------------------------------------------------------------ Sammeln

Progress = Callable[[int, str], None]


async def _try(ha: HaApi, command: dict, default: Any, timeout: float | None = None) -> Any:
    try:
        result = await ha.call(command, timeout=timeout)
    except HaApiError as exc:
        log.info("Überblick: %s nicht abrufbar (%s)", command.get("type"), exc)
        return default
    return default if result is None else result


async def collect(ha: HaApi, progress: Progress) -> dict[str, Any]:
    """Rohdaten aus Home Assistant holen (nur lesend). Schlägt nur fehl, wenn Home Assistant gar nicht antwortet."""
    progress(0, tr(STEPS[0]))
    config = await ha.call({"type": "get_config"}, timeout=QUERY_TIMEOUT)
    if not isinstance(config, dict):
        raise HaApiError("get_config: keine Antwort")
    progress(1, tr(STEPS[1]))
    areas = await _try(ha, {"type": "config/area_registry/list"}, [])
    floors = await _try(ha, {"type": "config/floor_registry/list"}, [])
    progress(2, tr(STEPS[2]))
    devices = await _try(ha, {"type": "config/device_registry/list"}, [], QUERY_TIMEOUT)
    entities = await _try(ha, {"type": "config/entity_registry/list"}, [], QUERY_TIMEOUT)
    states = await ha.call({"type": "get_states"}, timeout=QUERY_TIMEOUT) or []
    progress(3, tr(STEPS[3]))
    entries = await _try(ha, {"type": "config_entries/get"}, [], QUERY_TIMEOUT)
    progress(4, tr(STEPS[4]))
    # Automationen, Skripte und Szenen stehen mit Namen schon in den Zuständen.
    progress(5, tr(STEPS[5]))
    dashboards = await _try(ha, {"type": "lovelace/dashboards/list"}, [])
    return {
        "config": config, "areas": areas, "floors": floors, "devices": devices, "entities": entities,
        "states": states, "entries": entries, "dashboards": dashboards,
    }


# ---------------------------------------------------------------------------------------------- Zusammenstellen


def build_entries(data: dict[str, Any]) -> tuple[list[tuple[str, str]], dict[str, int]]:
    """Aus den Rohdaten die Gedächtniseinträge (Thema, Inhalt) und Kennzahlen bilden."""
    config = data.get("config") or {}
    areas = {a["area_id"]: a for a in data.get("areas") or [] if a.get("area_id")}
    floors = {f["floor_id"]: f for f in data.get("floors") or [] if f.get("floor_id")}
    devices = {d["id"]: d for d in data.get("devices") or [] if d.get("id")}
    registry = {e["entity_id"]: e for e in data.get("entities") or [] if e.get("entity_id")}
    states = [s for s in data.get("states") or [] if isinstance(s, dict) and s.get("entity_id")]

    out: list[tuple[str, str]] = []

    def topic(name: str) -> str:
        return AUTO_PREFIX + name

    # --- Entitäten bereichsweise einordnen (sichtbar, nicht deaktiviert, keine Diagnose/Konfiguration)
    by_area: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    no_area: dict[str, list[str]] = defaultdict(list)
    domain_count: dict[str, int] = defaultdict(int)
    sensor_classes: dict[str, int] = defaultdict(int)
    hidden = 0
    for s in states:
        eid = s["entity_id"]
        domain = eid.split(".", 1)[0]
        reg = registry.get(eid, {})
        if reg.get("disabled_by"):
            continue
        domain_count[domain] += 1
        if reg.get("hidden_by") or reg.get("entity_category"):
            hidden += 1
            continue
        attrs = s.get("attributes") or {}
        label = _entity_name(eid, attrs.get("friendly_name") or reg.get("name") or reg.get("original_name") or "")
        area_id = reg.get("area_id") or (devices.get(reg.get("device_id") or "") or {}).get("area_id")
        if domain in SENSOR:
            cls = attrs.get("device_class") or ""
            sensor_classes[cls or domain] += 1
            if domain == "sensor" and not cls and not attrs.get("unit_of_measurement"):
                continue  # Textsensoren ohne Klasse sind selten nützlich
            label = f"{label}" + (f" [{cls}]" if cls else "")
        elif domain not in CONTROL:
            continue
        if area_id and area_id in areas:
            by_area[area_id][domain].append(label)
        else:
            no_area[domain].append(label)

    # --- System
    system = [f"Name: {config.get('location_name') or '?'}", f"Version: {config.get('version') or '?'}", f"Zeitzone: {config.get('time_zone') or '?'}"]
    units = config.get("unit_system") or {}
    if units:
        system.append("Einheiten: " + ", ".join(f"{k} {v}" for k, v in list(units.items())[:5] if isinstance(v, str)))
    if config.get("currency"):
        system.append(f"Währung: {config['currency']}")
    if config.get("country"):
        system.append(f"Land: {config['country']}")
    if config.get("language"):
        system.append(f"Sprache: {config['language']}")
    if config.get("recovery_mode") or config.get("safe_mode"):
        system.append("Achtung: Wiederherstellungs-/abgesicherter Modus")
    system.append(f"{sum(domain_count.values())} Entitäten, {len(devices)} Geräte, {len(areas)} Bereiche")
    out.append((topic("System"), "; ".join(system)[:CONTENT_MAX]))

    # --- Etagen und Bereiche
    floor_of: dict[str, str] = {}
    for a in areas.values():
        if a.get("floor_id") in floors:
            floor_of[a["area_id"]] = floors[a["floor_id"]].get("name", "")
    if areas:
        parts = []
        if floors:
            for fid, f in sorted(floors.items(), key=lambda kv: (kv[1].get("level") is None, kv[1].get("level") or 0, kv[1].get("name", ""))):
                names = sorted(a.get("name", "?") for a in areas.values() if a.get("floor_id") == fid)
                parts.append(f"{f.get('name', fid)}: " + (", ".join(names) or "(keine Bereiche)"))
            loose = sorted(a.get("name", "?") for a in areas.values() if a.get("floor_id") not in floors)
            if loose:
                parts.append("Ohne Etage: " + ", ".join(loose))
        else:
            parts.append("Bereiche: " + ", ".join(sorted(a.get("name", "?") for a in areas.values())))
        out += _chunks(topic("Etagen und Bereiche"), parts)

    # --- Je Bereich die steuerbaren Entitäten und Sensoren
    ordered = sorted(areas.values(), key=lambda a: (a.get("name") or "").lower())[:MAX_AREAS]
    for a in ordered:
        groups = by_area.get(a["area_id"])
        if not groups:
            continue
        controls = {d: groups[d] for d in CONTROL if d in groups}
        sensors = {d: groups[d] for d in SENSOR if d in groups}
        parts = _grouped(controls, CONTROL_NAME) + _grouped(sensors, DOMAIN_NAME, cap=12)
        floor = floor_of.get(a["area_id"])
        head = f"{floor + ': ' if floor else ''}"
        out += _chunks(topic(f"Bereich {a.get('name', '?')}"), parts, head=head)

    # --- Ohne Bereich
    if no_area:
        controls = {d: no_area[d] for d in CONTROL if d in no_area}
        if controls:
            out += _chunks(topic("Ohne Bereich"), _grouped(controls, CONTROL_NAME, cap=15))

    # --- Entitäten je Typ
    if domain_count:
        top = sorted(domain_count.items(), key=lambda kv: (-kv[1], kv[0]))
        text = ", ".join(f"{DOMAIN_NAME.get(d, d)} {n}" for d, n in top[:40])
        if hidden:
            text += f" (davon {hidden} ausgeblendet oder Diagnose)"
        out.append((topic("Entitäten je Typ"), text[:CONTENT_MAX]))
    if sensor_classes:
        top = sorted(sensor_classes.items(), key=lambda kv: (-kv[1], kv[0]))
        out.append((topic("Sensorarten"), ", ".join(f"{c} {n}" for c, n in top[:40])[:CONTENT_MAX]))

    # --- Integrationen
    entries = [e for e in data.get("entries") or [] if isinstance(e, dict) and e.get("domain") and e.get("source") != "ignore" and not e.get("disabled_by")]
    if entries:
        seen: dict[str, list[str]] = defaultdict(list)
        for e in entries:
            title = " ".join(str(e.get("title") or "").split())
            seen[e["domain"]].append(title)
        parts = []
        for domain, titles in sorted(seen.items()):
            extra = [t for t in titles if t and t.lower() != domain.lower()]
            parts.append(domain + (f" ({', '.join(extra[:3])}{', …' if len(extra) > 3 else ''})" if extra else ""))
        out += _chunks(topic("Integrationen"), parts, sep=", ")

    # --- Automationen, Skripte, Szenen (Namen aus den Zuständen)
    for domain, title in (("automation", "Automationen"), ("script", "Skripte"), ("scene", "Szenen")):
        rows = sorted((s for s in states if s["entity_id"].startswith(domain + ".")), key=lambda s: s["entity_id"])
        if not rows:
            continue
        parts = []
        for s in rows:
            attrs = s.get("attributes") or {}
            name = _entity_name(s["entity_id"], attrs.get("friendly_name") or "")
            if domain == "automation" and s.get("state") == "off":
                name += " [aus]"
            parts.append(name)
        out += _chunks(topic(title), parts, head=f"{len(rows)} insgesamt: ", sep=", ")

    # --- Helfer
    helpers = sorted(
        (s["entity_id"], (s.get("attributes") or {}).get("friendly_name") or "")
        for s in states
        if s["entity_id"].split(".", 1)[0] in HELPER_DOMAINS
    )
    if helpers:
        parts = [f"{eid.split('.')[0]}.{_entity_name(eid, name)}" for eid, name in helpers]
        out += _chunks(topic("Helfer"), parts, head=f"{len(parts)} insgesamt: ", sep=", ")

    # --- Personen, Zonen, Dashboards
    people = sorted(
        str((s.get("attributes") or {}).get("friendly_name") or s["entity_id"].split(".", 1)[1])
        for s in states if s["entity_id"].startswith("person.")
    )
    zones = []
    for s in states:
        if s["entity_id"].startswith("zone."):
            attrs = s.get("attributes") or {}
            zones.append(str(attrs.get("friendly_name") or s["entity_id"].split(".", 1)[1]))
    parts = []
    if people:
        parts.append("Personen: " + ", ".join(people))
    if zones:
        parts.append("Zonen: " + ", ".join(sorted(zones)))
    if parts:
        out += _chunks(topic("Personen und Zonen"), parts)
    boards = []
    for d in data.get("dashboards") or []:
        if isinstance(d, dict) and d.get("title"):
            boards.append(f"{d['title']} ({d.get('url_path', '')})")
    if boards:
        out += _chunks(topic("Dashboards"), boards, sep=", ")

    # --- Aufräumen: leere Einträge und Zugangsdaten raus, Längen einhalten, Themen eindeutig
    seen_topics: set[str] = set()
    clean: list[tuple[str, str]] = []
    for t, c in out:
        t = t[:TOPIC_MAX]
        c = " ".join(c.split())[:CONTENT_MAX]
        if not c or _SECRET.search(c) or t.lower() in seen_topics:
            continue
        seen_topics.add(t.lower())
        clean.append((t, c))
    stats = {
        "entries": len(clean), "entities": sum(domain_count.values()), "areas": len(areas), "devices": len(devices),
        "automations": domain_count.get("automation", 0), "integrations": len({e["domain"] for e in entries}),
    }
    return clean, stats


# ----------------------------------------------------------------------------------------------- Verwaltung


class OverviewScanner:
    """Ein Lauf zur gleichen Zeit; der Stand (läuft / fertig / Fehler) ist für die Oberfläche abrufbar."""

    def __init__(self, store: Store, ha: HaApi, *, clock: Callable[[], float] = time.time) -> None:
        self.store = store
        self.ha = ha
        self._clock = clock
        self._lock = asyncio.Lock()
        self._running: dict[str, Any] | None = None
        self._task: asyncio.Task | None = None  # Verweis, damit der Lauf nicht vorzeitig aufgeräumt wird

    def _saved(self) -> dict[str, Any]:
        raw = self.store.state_get(STATE_KEY)
        try:
            value = json.loads(raw) if raw else {}
        except ValueError:
            value = {}
        return value if isinstance(value, dict) else {}

    def status(self) -> dict[str, Any]:
        """Stand für die Oberfläche: ``state`` = never | running | ok | error, dazu Zeiten, Fortschritt und Kennzahlen."""
        saved = self._saved()
        out: dict[str, Any] = {"state": saved.get("state", "never"), **{k: saved[k] for k in ("finished_at", "stats", "error", "trigger") if k in saved}}
        if self._running:
            out.update(state="running", started_at=self._running["started_at"], step=self._running["step"], steps=len(STEPS), label=self._running["label"])
            if saved.get("state") == "ok":
                out["previous_finished_at"] = saved.get("finished_at")
        out["total_steps"] = len(STEPS)
        return out

    def due(self, days: int) -> bool:
        """Soll jetzt automatisch gelesen werden? Nie gelesen oder der letzte Erfolg ist älter als ``days`` Tage (0 = nur auf Knopfdruck); nach einem Fehler frühestens nach 15 Minuten erneut."""
        if self._running or days <= 0:
            return False
        saved = self._saved()
        if saved.get("state") != "ok":
            last_try = float(saved.get("finished_at") or 0)
            return self._clock() - last_try > RETRY_AFTER if saved.get("state") == "error" else True
        return self._clock() - float(saved.get("finished_at") or 0) > days * 86400

    @property
    def running(self) -> bool:
        return self._running is not None

    def start(self, trigger: str = "manual") -> bool:
        """Einen Lauf im Hintergrund starten (für den Knopf); ``False``, wenn schon einer läuft."""
        if self._running or self._lock.locked():
            return False
        self._task = asyncio.create_task(self.run(trigger))
        self._running = {"started_at": self._clock(), "step": 0, "label": tr(STEPS[0])}
        return True

    async def run(self, trigger: str = "auto") -> bool:
        """Einen Lauf durchführen; ``False``, wenn schon einer läuft."""
        if self._lock.locked():
            return False
        async with self._lock:
            self._running = {"started_at": self._clock(), "step": 0, "label": tr(STEPS[0])}

            def progress(step: int, label: str) -> None:
                if self._running:
                    self._running.update(step=step, label=label)

            try:
                data = await collect(self.ha, progress)
                progress(6, tr(STEPS[6]))
                entries, stats = await asyncio.to_thread(build_entries, data)
                if not entries:
                    raise HaApiError("keine Daten erhalten")
                await asyncio.to_thread(self.store.memory_replace_auto, entries)
                result = {"state": "ok", "finished_at": self._clock(), "stats": stats, "trigger": trigger}
                log.info("Überblick über Home Assistant eingelesen: %s", stats)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # Fehler nie nach außen werfen: Status „error“ genügt
                log.warning("Überblick über Home Assistant fehlgeschlagen: %s", exc)
                previous = self._saved()
                result = {"state": "error", "finished_at": self._clock(), "error": str(exc)[:200], "trigger": trigger}
                if previous.get("stats"):
                    result["stats"] = previous["stats"]
            finally:
                self._running = None
            await asyncio.to_thread(self.store.state_set, STATE_KEY, json.dumps(result))
            return True
