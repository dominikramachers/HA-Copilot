"""Hinweise für den Betrieb: ablaufende Zugangsdaten und Probleme der Datenbank.

Die Hinweise erscheinen in der Oberfläche (``/api/me``) und im Add-on-Protokoll.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .i18n import tr
from .config import Settings

WARN_DAYS = 30


def _expiry(kind: str, expires: date | None, today: date, what: str, remedy: str) -> dict | None:
    if expires is None:
        return None
    days = (expires - today).days
    if days > WARN_DAYS:
        return None
    when = expires.strftime("%d.%m.%Y")
    if days < 0:
        text = tr("{what} ist seit dem {when} abgelaufen. {remedy}", what=what, when=when, remedy=remedy)
        level = "error"
    elif days == 0:
        text = tr("{what} läuft heute ab. {remedy}", what=what, remedy=remedy)
        level = "error"
    else:
        text = tr("{what} läuft in 1 Tag ab ({when}). {remedy}" if days == 1 else "{what} läuft in {days} Tagen ab ({when}). {remedy}", what=what, days=days, when=when, remedy=remedy)
        level = "warn"
    return {"id": f"{kind}-{expires.isoformat()}", "level": level, "text": text}


@dataclass
class Health:
    settings: Settings
    db_problem: str | None = None

    def notices(self, today: date | None = None) -> list[dict]:
        today = today or date.today()
        found: list[dict] = []
        if self.db_problem:
            found.append({"id": "db", "level": "error", "text": self.db_problem})
        s = self.settings
        found.append(
            _expiry(
                "claude", s.claude_token_expires, today,
                tr("Das Claude-Token"),
                tr("Neues Token mit „claude setup-token“ erzeugen und im Add-on eintragen."),
            )
        )
        if s.public_enabled:
            found.append(
                _expiry(
                    "entra", s.entra_secret_expires, today,
                    tr("Das Entra-Client-Secret"),
                    tr("Neues Secret in Entra anlegen und im Add-on eintragen, sonst ist die Anmeldung auf der Domain gesperrt."),
                )
            )
        return [n for n in found if n]
