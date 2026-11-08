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
        """Neuer Stand einer Limitart; ``allowed`` räumt eine frühere Warnung ab."""
        kind = str(info.get("type") or "unknown")[:30]
        status = str(info.get("status") or "allowed")
        if status not in ("allowed", "allowed_warning", "rejected"):
            return
        self._items[kind] = {
            "type": kind,
            "status": status,
            "resets_at": info.get("resets_at"),
            "utilization": info.get("utilization"),
            "seen_at": int(self._clock()),
        }
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

        ``expired``: die gemeldete Rücksetzzeit ist vorbei, der Wert gilt nicht mehr; ein neuer kommt mit der nächsten Antwort.
        """
        now = self._clock()
        out = []
        for kind, item in self._items.items():
            if kind == "unknown" or item.get("utilization") is None and item.get("status") == "allowed" and not item.get("resets_at"):
                continue
            resets = item.get("resets_at")
            out.append({
                "type": kind,
                "status": item.get("status"),
                "utilization": item.get("utilization"),
                "resets_at": resets,
                "seen_at": item.get("seen_at"),
                "expired": bool(resets and resets <= now),
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
