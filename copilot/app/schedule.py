"""Zeitpläne der geplanten Aufgaben: prüfen, nächsten Zeitpunkt berechnen, in Worten beschreiben.

Alle Zeiten sind Ortszeit des Add-ons (Zeitzone von Home Assistant, die der Supervisor als ``TZ`` mitgibt).
Der Zeitplan besteht aus drei Angaben: ``freq`` (Häufigkeit), ``at`` (Uhrzeit ``HH:MM``) und ``days`` (je nach Häufigkeit
Wochentage, Tag im Monat oder Datum). Bewusst keine freien Cron-Ausdrücke: Die Oberfläche bietet nur, was hier steht.
"""
from __future__ import annotations

import calendar
import re
from datetime import date, datetime, time, timedelta

from .i18n import tr

FREQUENCIES = ("daily", "weekdays", "weekly", "monthly", "once")
WEEKDAYS = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")
_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class ScheduleError(ValueError):
    """Ungültiger Zeitplan (Meldung ist für die Person bestimmt)."""


def clean(freq: str, at: str, days: str, now: datetime | None = None) -> tuple[str, str, str]:
    """Angaben prüfen und in die gespeicherte Form bringen: ``(freq, at, days)``."""
    freq = (freq or "").strip().lower()
    at = (at or "").strip()
    days = (days or "").strip()
    if freq not in FREQUENCIES:
        raise ScheduleError(tr("Unbekannte Häufigkeit."))
    if not _TIME.match(at):
        raise ScheduleError(tr("Die Uhrzeit muss im Format HH:MM angegeben werden."))
    if freq in ("daily", "weekdays"):
        return freq, at, ""
    if freq == "weekly":
        try:
            picked = sorted({int(x) for x in re.split(r"[,\s]+", days) if x != ""})
        except ValueError:
            raise ScheduleError(tr("Ungültige Wochentage.")) from None
        if not picked or any(not 0 <= d <= 6 for d in picked):
            raise ScheduleError(tr("Mindestens einen Wochentag wählen."))
        return freq, at, ",".join(str(d) for d in picked)
    if freq == "monthly":
        try:
            day = int(days)
        except ValueError:
            raise ScheduleError(tr("Der Tag im Monat muss eine Zahl von 1 bis 31 sein.")) from None
        if not 1 <= day <= 31:
            raise ScheduleError(tr("Der Tag im Monat muss eine Zahl von 1 bis 31 sein."))
        return freq, at, str(day)
    try:
        when = date.fromisoformat(days)
    except ValueError:
        raise ScheduleError(tr("Das Datum muss im Format JJJJ-MM-TT angegeben werden.")) from None
    if next_after(freq, at, days, now or datetime.now()) is None:
        raise ScheduleError(tr("Der Zeitpunkt liegt in der Vergangenheit."))
    return freq, at, when.isoformat()


def _matches(freq: str, days: str, day: date) -> bool:
    if freq == "daily":
        return True
    if freq == "weekdays":
        return day.weekday() < 5
    if freq == "weekly":
        return str(day.weekday()) in days.split(",")
    if freq == "monthly":
        last = calendar.monthrange(day.year, day.month)[1]
        return day.day == min(int(days), last)  # „31.“ gilt in kürzeren Monaten am letzten Tag
    return False


def next_after(freq: str, at: str, days: str, now: datetime) -> datetime | None:
    """Nächster Zeitpunkt strikt nach ``now`` (Ortszeit, ohne Zeitzone); ``None``, wenn nichts mehr kommt (einmalig, vorbei)."""
    hour, minute = int(at[:2]), int(at[3:5])
    if freq == "once":
        moment = datetime.combine(date.fromisoformat(days), time(hour, minute))
        return moment if moment > now else None
    for offset in range(0, 400):
        day = now.date() + timedelta(days=offset)
        if not _matches(freq, days, day):
            continue
        moment = datetime.combine(day, time(hour, minute))
        if moment > now:
            return moment
    return None


def next_timestamp(freq: str, at: str, days: str, now: datetime | None = None) -> int | None:
    """Wie ``next_after``, als Unix-Zeit."""
    moment = next_after(freq, at, days, now or datetime.now())
    return int(moment.timestamp()) if moment else None


def describe(freq: str, at: str, days: str) -> str:
    """Zeitplan in einem Satz, z. B. „Jeden Montag und Freitag um 08:00 Uhr“."""
    clock = tr("{at} Uhr", at=at)
    if freq == "daily":
        return tr("Jeden Tag um {clock}", clock=clock)
    if freq == "weekdays":
        return tr("Montag bis Freitag um {clock}", clock=clock)
    if freq == "weekly":
        names = [tr(WEEKDAYS[int(d)]) for d in days.split(",") if d.isdigit()]
        if len(names) == 1:
            return tr("Jeden {day} um {clock}", day=names[0], clock=clock)
        return tr("Jeden {days} und {last} um {clock}", days=", ".join(names[:-1]), last=names[-1], clock=clock)
    if freq == "monthly":
        return tr("Am {day}. jedes Monats um {clock}", day=int(days), clock=clock)
    try:
        return tr("Einmalig am {date} um {clock}", date=format(date.fromisoformat(days), "%d.%m.%Y"), clock=clock)
    except ValueError:
        return tr("Einmalig")
