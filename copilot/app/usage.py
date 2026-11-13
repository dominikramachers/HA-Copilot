"""Verbrauchsprotokoll: wer wie viel der KI genutzt hat (nur Zahlen, nie Inhalte).

Die Backends melden jeden Aufruf mit :func:`report`. Wohin die Zahlen gehen, bestimmt :func:`bound`: der Lauf, der gerade
für eine Person arbeitet, hängt das Protokoll der Person an. Außerhalb eines solchen Blocks (Test, Systemaufruf) wird
nichts gezählt. Die Übersicht „Alle Personen“ ist nur für Administratoren.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import time
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

KEEP_DAYS = 90  # so lange stehen einzelne Aufrufe im Protokoll, danach nur noch Tagessummen
RANGES = ("24h", "today", "week", "month", "lastmonth")

_sink: contextvars.ContextVar[Callable[[dict], None] | None] = contextvars.ContextVar("usage_sink", default=None)


def _make_sink(store, profile_id: str, kind: str) -> Callable[[dict], None]:
    def sink(entry: dict) -> None:
        store.usage_add(profile_id, kind=entry.pop("kind", None) or kind, **entry)

    return sink


@contextlib.contextmanager
def bound(store, profile_id: str, kind: str = "chat") -> Iterator[None]:
    """Verbrauch im Block dieser Person zuschreiben (``kind``: chat, voice, scheduled, image, …)."""
    token = _sink.set(_make_sink(store, profile_id, kind))
    try:
        yield
    finally:
        _sink.reset(token)


def bind(store, profile_id: str, kind: str = "chat") -> None:
    """Wie :func:`bound`, aber für den Rest des laufenden Tasks (ein Lauf oder eine Anfrage hat ihren eigenen Kontext)."""
    _sink.set(_make_sink(store, profile_id, kind))


def report(provider: str, model: str = "", tokens_in: int = 0, tokens_out: int = 0, cost_usd: float | None = None, images: int = 0, kind: str | None = None) -> None:
    """Einen Verbrauch melden; ohne ``bound`` oder bei Fehlern passiert nichts (das Zählen darf nie eine Antwort stören)."""
    sink = _sink.get()
    if sink is None:
        return
    entry = {"provider": provider, "model": model or "", "tokens_in": int(tokens_in or 0), "tokens_out": int(tokens_out or 0), "cost_usd": float(cost_usd or 0.0), "images": int(images or 0)}
    if kind:
        entry["kind"] = kind
    try:
        sink(entry)
    except Exception:
        log.warning("Verbrauch konnte nicht gezählt werden", exc_info=True)


def report_claude(result) -> None:
    """Verbrauch aus der Abschlussmeldung des Claude-SDK (``ResultMessage``) melden, je Modell getrennt."""
    models = getattr(result, "model_usage", None) or {}
    if models:
        for name, info in models.items():
            info = info or {}
            report(
                "claude", str(name),
                int(info.get("inputTokens") or 0) + int(info.get("cacheReadInputTokens") or 0) + int(info.get("cacheCreationInputTokens") or 0),
                int(info.get("outputTokens") or 0), info.get("costUSD"),
            )
        return
    usage = getattr(result, "usage", None) or {}
    report(
        "claude", "",
        int(usage.get("input_tokens") or 0) + int(usage.get("cache_read_input_tokens") or 0) + int(usage.get("cache_creation_input_tokens") or 0),
        int(usage.get("output_tokens") or 0), getattr(result, "total_cost_usd", None),
    )


def period(name: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    """Zeitraum ``[von, bis)`` in Ortszeit zu einem der Namen aus ``RANGES``."""
    now = now or datetime.now()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if name == "24h":
        return now - timedelta(hours=24), now + timedelta(seconds=1)
    if name == "today":
        return midnight, now + timedelta(seconds=1)
    if name == "week":  # laufende Woche ab Montag
        return midnight - timedelta(days=midnight.weekday()), now + timedelta(seconds=1)
    first = midnight.replace(day=1)
    if name == "lastmonth":
        return (first - timedelta(days=1)).replace(day=1), first
    return first, now + timedelta(seconds=1)  # month


def overview(store, labels: dict[str, str], name: str, rate: float, now: datetime | None = None, resolve: Callable[[str], str] | None = None) -> dict:
    """Zahlen für die Admin-Seite: je Person Aufrufe, Token, Bilder und Wert; dazu die Summe und der Anteil je Person."""
    if name not in RANGES:
        name = "month"
    start, end = period(name, now)
    rows = store.usage_summary(int(start.timestamp()), int(end.timestamp()), start.strftime("%Y-%m-%d"), (end - timedelta(seconds=1)).strftime("%Y-%m-%d"))
    seen = {row["profile_id"] for row in rows}
    rows += [{"profile_id": pid, "calls": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "images": 0} for pid in labels if pid not in seen]  # auch wer nichts genutzt hat
    out = []
    for row in rows:
        tokens = row["tokens_in"] + row["tokens_out"]
        out.append({
            "id": row["profile_id"], "label": labels.get(row["profile_id"]) or (resolve(row["profile_id"]) if resolve else "") or row["profile_id"], "calls": row["calls"],
            "tokens_in": row["tokens_in"], "tokens_out": row["tokens_out"], "tokens": tokens,
            "images": row["images"], "cost": round(row["cost_usd"] * rate, 2),
        })
    total = {k: sum(r[k] for r in out) for k in ("calls", "tokens_in", "tokens_out", "tokens", "images")}
    total["cost"] = round(sum(r["cost"] for r in out), 2)
    for r in out:
        r["share"] = round(100 * r["tokens"] / total["tokens"], 1) if total["tokens"] else 0.0
    out.sort(key=lambda r: (-r["tokens"], -r["images"], r["label"].lower()))
    return {"range": name, "from": int(start.timestamp()), "to": int(end.timestamp()), "people": out, "total": total}


def compact(store, now: float | None = None) -> int:
    """Einzelne Aufrufe nach ``KEEP_DAYS`` Tagen zu Tagessummen verdichten."""
    return store.usage_compact(int((now or time.time()) - KEEP_DAYS * 86400))
