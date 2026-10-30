"""Datensicherheit der Chat-Datenbank: Prüfung, Schnappschüsse, Wiederherstellung.

Die Chats liegen in einer SQLite-Datei. Die Sicherung von Home Assistant kopiert sie, und ein
Schnappschuss nach der SQLite-Backup-Schnittstelle ist immer in sich stimmig (auch bei
laufendem Betrieb). Die Schnappschüsse liegen im Datenordner des Add-ons und sind dadurch
in jeder HA-Sicherung enthalten.
"""
from __future__ import annotations

import logging
import re
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .i18n import tr
from .db import SCHEMA_VERSION

log = logging.getLogger("ki_chat.safety")

KEEP_DAILY = 7  # tägliche Schnappschüsse
KEEP_SPECIAL = 3  # je Art: vor einem Update, vor einer Wiederherstellung
SNAPSHOT_EVERY = timedelta(hours=20)

DAILY = "ki_chat-"
BEFORE_UPDATE = "vor-update-"
BEFORE_RESTORE = "vor-wiederherstellung-"
MARKER = ".letzte-wiederherstellung"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,100}\.sqlite3$")


def _stamp(now: datetime) -> str:
    return now.strftime("%Y-%m-%d_%H%M%S")


def copy_database(source: sqlite3.Connection, dest: Path) -> None:
    """Konsistente Kopie nach ``dest`` (über eine Zwischendatei, damit nie eine halbe Datei bleibt)."""
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.unlink(missing_ok=True)
    target = sqlite3.connect(tmp)
    try:
        source.backup(target)
    finally:
        target.close()
    tmp.replace(dest)


def quick_check(path: Path) -> str:
    """Ergebnis der SQLite-Prüfung („ok“ oder die erste Fehlermeldung)."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = conn.execute("PRAGMA quick_check").fetchone()
            return str(row[0]) if row else "keine Antwort"
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        return str(exc)


def list_snapshots(snap_dir: Path) -> list[Path]:
    if not snap_dir.is_dir():
        return []
    return sorted((p for p in snap_dir.glob("*.sqlite3") if NAME_RE.match(p.name)), reverse=True)


def prune(snap_dir: Path, prefix: str, keep: int) -> None:
    for old in [p for p in list_snapshots(snap_dir) if p.name.startswith(prefix)][keep:]:
        old.unlink(missing_ok=True)


def newest_daily_age(snap_dir: Path, now: datetime) -> timedelta | None:
    daily = [p for p in list_snapshots(snap_dir) if p.name.startswith(DAILY)]
    if not daily:
        return None
    return now - datetime.fromtimestamp(daily[0].stat().st_mtime, tz=timezone.utc)


def snapshot_live(conn: sqlite3.Connection, snap_dir: Path, prefix: str = DAILY, now: datetime | None = None) -> Path:
    """Schnappschuss aus einer offenen Verbindung anlegen, prüfen und alte aufräumen."""
    now = now or datetime.now(timezone.utc)
    snap_dir.mkdir(parents=True, exist_ok=True)
    dest = snap_dir / f"{prefix}{_stamp(now)}.sqlite3"
    copy_database(conn, dest)
    result = quick_check(dest)
    if result != "ok":
        dest.unlink(missing_ok=True)
        raise sqlite3.DatabaseError(f"Schnappschuss ist nicht in Ordnung: {result}")
    prune(snap_dir, prefix, KEEP_DAILY if prefix == DAILY else KEEP_SPECIAL)
    return dest


EXPORT_NAME = "ki_chat-export.sqlite3"


def export_database(db_path: Path, dest_dir: Path) -> Path:
    """Konsistente Kopie der Datenbank in den Config-Ordner legen (für den Umzug in ein anderes Add-on, z. B. vom lokalen zum GitHub-Add-on)."""
    dest = dest_dir / EXPORT_NAME
    conn = sqlite3.connect(db_path)
    try:
        copy_database(conn, dest)
    finally:
        conn.close()
    result = quick_check(dest)
    if result != "ok":
        dest.unlink(missing_ok=True)
        raise sqlite3.DatabaseError(f"Export ist nicht in Ordnung: {result}")
    return dest


def _find_snapshot(snap_dir: Path, import_dir: Path | None, name: str) -> Path:
    """Schnappschuss im eigenen Ordner, sonst (Umzug) im Config-Ordner des Add-ons."""
    source = snap_dir / name
    if not source.is_file() and import_dir is not None:
        source = import_dir / name
    return source


def _restore(db_path: Path, snap_dir: Path, name: str, import_dir: Path | None = None) -> str:
    if not NAME_RE.match(name):
        raise ValueError("Ungültiger Dateiname")
    source = _find_snapshot(snap_dir, import_dir, name)
    if not source.is_file():
        raise FileNotFoundError(f"Schnappschuss {name} nicht gefunden")
    result = quick_check(source)
    if result != "ok":
        raise sqlite3.DatabaseError(f"Schnappschuss ist beschädigt: {result}")
    now = datetime.now(timezone.utc)
    if db_path.exists():
        # Den bisherigen Stand erst sichern, auch wenn er beschädigt ist (dann als rohe Kopie).
        safe = snap_dir / f"{BEFORE_RESTORE}{_stamp(now)}.sqlite3"
        try:
            conn = sqlite3.connect(db_path)
            try:
                copy_database(conn, safe)
            finally:
                conn.close()
        except sqlite3.DatabaseError:
            shutil.copy2(db_path, safe)
        prune(snap_dir, BEFORE_RESTORE, KEEP_SPECIAL)
    for suffix in ("", "-wal", "-shm"):
        Path(str(db_path) + suffix).unlink(missing_ok=True)
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        copy_database(src, db_path)
    finally:
        src.close()
    return name


@dataclass
class Report:
    """Was beim Start passiert ist; ``problem`` erscheint als Hinweis in der Oberfläche."""

    lines: list[str] = field(default_factory=list)
    problem: str | None = None


def prepare(db_path: Path, snap_dir: Path, restore_name: str = "", import_dir: Path | None = None) -> Report:
    """Vor dem Öffnen der Datenbank: Wiederherstellen (falls gewünscht), prüfen, Update-Schnappschuss."""
    report = Report()
    snap_dir.mkdir(parents=True, exist_ok=True)

    restore_name = restore_name.strip()
    marker = snap_dir / MARKER
    if restore_name:
        source = _find_snapshot(snap_dir, import_dir, restore_name)
        token = f"{restore_name}:{source.stat().st_mtime_ns}" if source.is_file() else restore_name
        if marker.exists() and marker.read_text().strip() == token:
            report.lines.append(tr("Wiederherstellung von {restore_name} wurde schon durchgeführt (Option kann geleert werden)", restore_name=restore_name))
        else:
            try:
                _restore(db_path, snap_dir, restore_name, import_dir)
                marker.write_text(token)
                report.lines.append(tr("Datenbank aus Schnappschuss {restore_name} wiederhergestellt", restore_name=restore_name))
                report.problem = tr("Datenbank aus Schnappschuss {restore_name} wiederhergestellt. Option „restore_snapshot“ im Add-on leeren.", restore_name=restore_name)
            except (ValueError, OSError, sqlite3.DatabaseError) as exc:
                log.error("Wiederherstellung fehlgeschlagen: %s", exc)
                report.lines.append(tr("Wiederherstellung fehlgeschlagen: {exc}", exc=exc))
                report.problem = tr("Wiederherstellung von {restore_name} fehlgeschlagen: {exc}", restore_name=restore_name, exc=exc)

    if db_path.exists():
        result = quick_check(db_path)
        if result != "ok":
            names = ", ".join(p.name for p in list_snapshots(snap_dir)[:3]) or "keine vorhanden"
            report.lines.append(f"DATENBANK-FEHLER: {result}")
            report.problem = (
                tr("Die Chat-Datenbank meldet einen Fehler. Neueste Schnappschüsse: {names}. Zum Wiederherstellen den Dateinamen in der Add-on-Option „restore_snapshot“ eintragen.", names=names)
            )
            return report
        conn = sqlite3.connect(db_path)
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            has_data = conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'chats'").fetchone() is not None
            if has_data and version < SCHEMA_VERSION:
                dest = snapshot_live(conn, snap_dir, BEFORE_UPDATE)
                report.lines.append(f"Schnappschuss vor dem Update: {dest.name}")
        finally:
            conn.close()
    names = [p.name for p in list_snapshots(snap_dir)]
    report.lines.append(f"Schnappschüsse vorhanden: {len(names)}" + (f" (neuester: {names[0]})" if names else ""))
    return report
