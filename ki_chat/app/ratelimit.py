"""Einfache Ratenbegrenzung im Speicher (gleitendes Fenster)."""
from __future__ import annotations

import time
from collections import deque


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float, clock=time.monotonic) -> None:
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        """True, wenn die Anfrage noch erlaubt ist (und zählt sie dann mit)."""
        now = self._clock()
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        if len(self._hits) > 5000:  # Speicher begrenzen
            self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] <= self.window}
        return True
