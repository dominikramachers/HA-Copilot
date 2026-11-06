"""Tresor für Zugangsdaten der Konnektoren (Token, Client-Geheimnisse).

Die Werte stehen verschlüsselt in der Datenbank. Der Schlüssel liegt als eigene Datei im Datenordner des Add-ons, nicht im
Config-Ordner und nicht in den Schnappschüssen: Der Datenbank-Export (Option ``export_database``) und die Schnappschüsse
sind so allein nicht lesbar, wenn sie in falsche Hände geraten. Eine Sicherung von Home Assistant enthält beides.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger("copilot.vault")


class Vault:
    def __init__(self, key_path: Path) -> None:
        self._path = Path(key_path)
        self._cached: Fernet | None = None

    @property
    def _fernet(self) -> Fernet:
        """Der Schlüssel wird erst beim ersten Gebrauch geladen oder angelegt (ohne Konnektoren entsteht keine Datei)."""
        if self._cached is None:
            self._cached = Fernet(self._load_or_create())
        return self._cached

    def _load_or_create(self) -> bytes:
        try:
            key = self._path.read_bytes().strip()
            Fernet(key)  # prüft die Form
            return key
        except FileNotFoundError:
            pass
        except (ValueError, OSError):
            log.error("Der Schlüssel der Konnektoren ist unlesbar; bestehende Zugangsdaten lassen sich nicht mehr öffnen")
        key = Fernet.generate_key()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(self._path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(key)
        tmp.replace(self._path)
        return key

    def seal(self, text: str) -> str:
        return self._fernet.encrypt(text.encode("utf-8")).decode("ascii")

    def unseal(self, token: str) -> str | None:
        """Klartext, oder ``None``, wenn der Wert nicht (mehr) zu diesem Schlüssel passt."""
        if not token:
            return None
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError, ValueError):
            return None
