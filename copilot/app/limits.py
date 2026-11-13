"""Nutzungslimit des Claude-Abos: letzter bekannter Stand, damit die Oberfläche warnen und die Rücksetzzeit nennen kann.

Das Limit gehört dem Abo und gilt für alle Benutzer des Add-ons zusammen. Das Programm meldet jeden Wechsel (ok → fast erreicht →
erreicht) mit Zeitpunkt der Rücksetzung; hier steht je Limitart der letzte Stand, auch über einen Neustart hinweg.
"""
from __future__ import annotations

import json
import logging
import time
import weakref
from collections.abc import Callable

from .db import Store

log = logging.getLogger("copilot.limits")

STATE_KEY = "usage_limits"
STALE_SECONDS = 6 * 3600  # ohne bekannte Rücksetzzeit gilt eine Warnung höchstens so lange
SEVERITY = {"rejected": 2, "allowed_warning": 1}


class LimitState:
    def __init__(self, store: Store, clock: Callable[[], float] = time.time) -> None:
        self._store = store
        self._clock = clock
        self._items: dict[str, dict] = {}
        try:
            raw = json.loads(store.state_get(STATE_KEY) or "{}")
            if isinstance(raw, dict):
                self._items = {k: v for k, v in raw.items() if isinstance(v, dict)}
        except (ValueError, TypeError):
            log.warning("Gespeicherter Limit-Stand unlesbar, wird verworfen")

    def update(self, info: dict) -> None:
        """Neuer Stand: je Fenster aus ``windows`` (falls das Programm sie meldet), sonst nur die genannte Limitart.

        Der Verbrauch aller Fenster kommt so mit jeder Meldung an, auch das Wochenlimit, wenn das Programm das 5-Stunden-Fenster
        nennt. ``allowed`` räumt eine frühere Warnung ab."""
        kind = str(info.get("type") or "unknown")[:30]
        status = str(info.get("status") or "allowed")
        if status not in ("allowed", "allowed_warning", "rejected"):
            return
        windows = info.get("windows") if isinstance(info.get("windows"), dict) else {}
        for name, window in windows.items():
            own = window.get("status")
            if own is None:
                # ohne eigene Angabe: das genannte Fenster übernimmt den Gesamtstatus, ein anderes behält eine noch gültige Warnung
                previous = self._items.get(name, {})
                if name == kind:
                    own = status
                elif previous.get("status") in SEVERITY and previous.get("resets_at") == window.get("resets_at"):
                    own = previous["status"]
                else:
                    own = "allowed"
            self._set(name, own, window.get("resets_at"), window.get("utilization"))
        if kind not in windows:
            self._set(kind, status, info.get("resets_at"), info.get("utilization"))
        self._save()

    def _set(self, kind: str, status: str, resets_at, utilization) -> None:
        previous = self._items.get(kind, {})
        if utilization is None and resets_at and previous.get("resets_at") == resets_at:
            utilization = previous.get("utilization")  # dasselbe Fenster, nur ohne Zahl gemeldet: der letzte Wert bleibt der beste
        self._items[kind] = {
            "type": kind,
            "status": status,
            "resets_at": resets_at,
            "utilization": utilization,
            "seen_at": int(self._clock()),
        }

    def _save(self) -> None:
        try:
            self._store.state_set(STATE_KEY, json.dumps(self._items))
        except Exception:
            log.warning("Limit-Stand konnte nicht gespeichert werden", exc_info=True)

    def current(self) -> list[dict]:
        """Aktive Warnungen und erreichte Limits, das Schwerste zuerst."""
        now = self._clock()
        active = []
        for item in self._items.values():
            if item.get("status") not in SEVERITY:
                continue
            resets = item.get("resets_at")
            if resets:
                if resets <= now:
                    continue
            elif now - item.get("seen_at", 0) > STALE_SECONDS:
                continue
            active.append({k: item.get(k) for k in ("type", "status", "resets_at", "utilization")})
        active.sort(key=lambda i: (-SEVERITY[i["status"]], -(i.get("utilization") or 0)))
        return active


    ORDER = ("five_hour", "seven_day", "seven_day_opus", "seven_day_sonnet", "overage")

    def overview(self) -> list[dict]:
        """Alle bekannten Zeitfenster mit letztem Stand (auch ohne Warnung), für die Seite „Nutzung“.

        ``expired``: die gemeldete Rücksetzzeit ist vorbei. Das Fenster ist damit zurückgesetzt: Der Verbrauch steht auf 0 und
        ein neuer gemeldeter Wert kommt mit der nächsten Antwort der KI (ein neues 5-Stunden-Fenster beginnt erst mit ihr).
        """
        now = self._clock()
        out = []
        for kind, item in self._items.items():
            if kind == "unknown" or item.get("utilization") is None and item.get("status") == "allowed" and not item.get("resets_at"):
                continue
            resets = item.get("resets_at")
            expired = bool(resets and resets <= now)
            out.append({
                "type": kind,
                "status": "allowed" if expired else item.get("status"),
                "utilization": 0.0 if expired else item.get("utilization"),
                "resets_at": resets,
                "seen_at": item.get("seen_at"),
                "expired": expired,
            })
        out.sort(key=lambda i: (self.ORDER.index(i["type"]) if i["type"] in self.ORDER else len(self.ORDER), i["type"]))
        return out


_SHARED: "weakref.WeakKeyDictionary[Store, LimitState]" = weakref.WeakKeyDictionary()


def shared(store: Store) -> LimitState:
    """Ein Stand je Datenbank, gemeinsam für Ingress und Domain (beide laufen im selben Prozess)."""
    state = _SHARED.get(store)
    if state is None:
        state = _SHARED[store] = LimitState(store)
    return state
