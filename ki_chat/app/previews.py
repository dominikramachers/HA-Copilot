"""Vorschau für HTML-Artefakte: nur im Arbeitsspeicher, nie auf der Platte.

Ein vollständiges HTML-Dokument aus einer Antwort wird kurz im Speicher abgelegt (pro Profil begrenzt,
läuft nach einer Stunde ab) und von einer eigenen Adresse ausgeliefert. Dort gelten strenge Regeln
(``PREVIEW_HEADERS``): eigene Herkunft ohne Zugriff auf die Chat-Oberfläche, kein Netzwerk, keine
Formulare, keine Navigation. Skripte und Stile im Dokument selbst laufen.
"""
from __future__ import annotations

import secrets
import time
from collections import OrderedDict

MAX_CHARS = 150_000
MAX_PER_PROFILE = 12
TTL_SECONDS = 3600

PREVIEW_HEADERS = {
    "Content-Security-Policy": (
        "sandbox allow-scripts; default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
        "img-src data:; font-src data:; media-src data:; frame-ancestors 'self'; base-uri 'none'; form-action 'none'"
    ),
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


class PreviewStore:
    def __init__(self, ttl: float = TTL_SECONDS, per_profile: int = MAX_PER_PROFILE, clock=time.monotonic) -> None:
        self._ttl = ttl
        self._limit = per_profile
        self._clock = clock
        self._items: OrderedDict[str, tuple[str, str, float]] = OrderedDict()  # id -> (profile, html, expires)

    def _expire(self) -> None:
        now = self._clock()
        for key in [k for k, (_, _, until) in self._items.items() if until <= now]:
            del self._items[key]

    def put(self, profile_id: str, html: str) -> str:
        self._expire()
        mine = [k for k, (pid, _, _) in self._items.items() if pid == profile_id]
        for key in mine[: max(0, len(mine) - self._limit + 1)]:
            del self._items[key]  # älteste zuerst
        key = secrets.token_urlsafe(16)
        self._items[key] = (profile_id, html, self._clock() + self._ttl)
        return key

    def get(self, profile_id: str, key: str) -> str | None:
        self._expire()
        item = self._items.get(key)
        return item[1] if item and item[0] == profile_id else None

    def __len__(self) -> int:
        return len(self._items)
