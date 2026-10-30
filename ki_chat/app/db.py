"""SQLite-Datenschicht mit erzwungener Profil-Trennung.

Jede Methode, die Chats oder Nachrichten berührt, verlangt die Profil-ID als
erstes Argument und filtert damit immer. Zusätzlich verhindert ein
zusammengesetzter Fremdschlüssel auf Datenbankebene, dass eine Nachricht einem
anderen Profil gehört als ihr Chat.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import json
import sqlite3
import threading
import unicodedata
import uuid
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class _FoldTable(dict):
    """Tabelle für ``str.translate``: Kleinschreibung ohne Akzente, genau ein Zeichen je Zeichen (Positionen bleiben gleich)."""

    def __missing__(self, code: int) -> int:
        ch = chr(code)
        base = (unicodedata.normalize("NFKD", ch)[:1] or ch).lower()[:1] or ch
        self[code] = ord(base)
        return self[code]


_FOLD = _FoldTable()


def fold(text: str | None) -> str:
    """Für die Suche: klein geschrieben und ohne Akzente/Umlautpunkte („Küche“ -> „kuche“); gleiche Länge wie das Original."""
    return (text or "").translate(_FOLD)

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id          TEXT PRIMARY KEY,
    entra_oid   TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS chats (
    id          TEXT PRIMARY KEY,
    profile_id  TEXT NOT NULL REFERENCES profiles(id),
    title       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE (id, profile_id)
);
CREATE INDEX IF NOT EXISTS idx_chats_profile ON chats(profile_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    profile_id  TEXT NOT NULL REFERENCES profiles(id),
    name        TEXT NOT NULL,
    pinned_at   TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE (id, profile_id)
);
CREATE INDEX IF NOT EXISTS idx_projects_profile ON projects(profile_id);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     TEXT NOT NULL,
    profile_id  TEXT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (chat_id, profile_id) REFERENCES chats(id, profile_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, id);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    profile_id  TEXT NOT NULL REFERENCES profiles(id),
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_profile ON sessions(profile_id);
"""

KNOWLEDGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id  TEXT NOT NULL,
    project_id  TEXT NOT NULL,
    name        TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE (project_id, name),
    FOREIGN KEY (project_id, profile_id) REFERENCES projects(id, profile_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS memories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    scope       TEXT NOT NULL CHECK (scope IN ('household', 'person')),
    owner       TEXT NOT NULL DEFAULT '',
    topic       TEXT NOT NULL,
    content     TEXT NOT NULL,
    author      TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    CHECK ((scope = 'household' AND owner = '') OR (scope = 'person' AND owner <> '')),
    UNIQUE (scope, owner, topic COLLATE NOCASE)
);
"""

STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS app_state (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
"""

OUTFILES_SCHEMA = """
CREATE TABLE IF NOT EXISTS outfiles (
    id          TEXT PRIMARY KEY,
    profile_id  TEXT NOT NULL,
    chat_id     TEXT NOT NULL,
    name        TEXT NOT NULL,
    mime        TEXT NOT NULL,
    size        INTEGER NOT NULL,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    FOREIGN KEY (chat_id, profile_id) REFERENCES chats(id, profile_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_outfiles_profile ON outfiles(profile_id, created_at);
"""

SCHEDULES_SCHEMA = """
CREATE TABLE IF NOT EXISTS schedules (
    id           TEXT PRIMARY KEY,
    profile_id   TEXT NOT NULL REFERENCES profiles(id),
    name         TEXT NOT NULL,
    prompt       TEXT NOT NULL,
    freq         TEXT NOT NULL,
    at_time      TEXT NOT NULL,
    days         TEXT NOT NULL DEFAULT '',
    enabled      INTEGER NOT NULL DEFAULT 1,
    model        TEXT NOT NULL DEFAULT '',
    web          INTEGER NOT NULL DEFAULT 1,
    notify       TEXT NOT NULL DEFAULT 'chat',
    next_run     INTEGER,
    last_run     INTEGER,
    last_status  TEXT NOT NULL DEFAULT '',
    last_note    TEXT NOT NULL DEFAULT '',
    last_chat_id TEXT NOT NULL DEFAULT '',
    runs         INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_schedules_profile ON schedules(profile_id, created_at);
CREATE INDEX IF NOT EXISTS idx_schedules_due ON schedules(enabled, next_run);
"""

SCHEDULE_FIELDS = (
    "id, name, prompt, freq, at_time, days, enabled, model, web, notify, next_run, last_run, "
    "last_status, last_note, last_chat_id, runs, created_at"
)
SCHEDULE_LIMIT = 20  # geplante Aufgaben je Person

# Einträge, die das Add-on selbst aus Home Assistant anlegt (Smarthome-Überblick), erkennt man am Verfasser und am Themenpräfix.
AUTO_AUTHOR = "ha-scan"
AUTO_PREFIX = "HA · "

# Wird nach dem Nachrüsten der Spalten angelegt. Die Trigger sichern auf Datenbankebene, dass ein Chat
# nur zu einem Projekt desselben Profils gehören kann.
MIGRATION_OBJECTS = """
CREATE INDEX IF NOT EXISTS idx_chats_project ON chats(project_id);

CREATE TRIGGER IF NOT EXISTS chats_project_profile_insert
BEFORE INSERT ON chats WHEN NEW.project_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'project belongs to another profile')
    WHERE NOT EXISTS (SELECT 1 FROM projects WHERE id = NEW.project_id AND profile_id = NEW.profile_id);
END;

CREATE TRIGGER IF NOT EXISTS chats_project_profile_update
BEFORE UPDATE OF project_id, profile_id ON chats WHEN NEW.project_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'project belongs to another profile')
    WHERE NOT EXISTS (SELECT 1 FROM projects WHERE id = NEW.project_id AND profile_id = NEW.profile_id);
END;

CREATE TRIGGER IF NOT EXISTS projects_release_chats
AFTER DELETE ON projects
BEGIN
    UPDATE chats SET project_id = NULL WHERE project_id = OLD.id;
END;
"""

SESSION_MAX_DAYS = 90
SCHEMA_VERSION = 12  # 12: geplante Aufgaben (schedules, chats.schedule_id); 11: Modell je Chat; 10: erzeugte Dateien (outfiles); 9: Zustandstabelle (Stand des Smarthome-Überblicks); 8: Projektwissen und Gedächtnis; 7: Aktionsprotokoll der Antworten (HA-Werkzeuge); 2: Projekte, Anpinnen, Zusammenfassungen; 3: Anhang-Angaben; 4: Projektanweisungen; 5: Name/HA-Benutzer automatischer Profile; 6: Lesestatus der Chats (siehe Store._migrate)
INSTRUCTIONS_MAX = 4000
CHAT_FIELDS = "id, title, created_at, updated_at, pinned_at, project_id, unread, model, schedule_id"


def _chat(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["pinned"] = data.pop("pinned_at") is not None
    data["unread"] = bool(data.get("unread"))
    return data


def _schedule(row: sqlite3.Row) -> dict[str, Any]:
    data = {k: row[k] for k in row.keys() if k != "profile_id"}
    data["at"] = data.pop("at_time")
    data["enabled"] = bool(data["enabled"])
    data["web"] = bool(data["web"])
    return data


def _project(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["pinned"] = data.pop("pinned_at") is not None
    return data


def _attachments(raw: str | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except ValueError:
        return []
    return [
        {"name": str(i.get("name", "Datei")), "kind": str(i.get("kind", "text")), "size": int(i.get("size", 0))}
        for i in items
        if isinstance(i, dict)
    ]


def _tools(raw: str | None) -> list[dict[str, Any]]:
    """Protokoll der Aktionen in Home Assistant, die zu einer Antwort gehören."""
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except ValueError:
        return []
    out = []
    for i in items:
        if not isinstance(i, dict):
            continue
        entry = {"label": str(i.get("label", ""))[:200], "kind": str(i.get("kind", "read")), "status": str(i.get("status", "ok")), "note": str(i.get("note", ""))[:300]}
        file = i.get("file")
        if isinstance(file, dict) and _FILE_ID.match(str(file.get("id", ""))):
            entry["file"] = {"id": str(file["id"]), "name": str(file.get("name", ""))[:150], "size": int(file.get("size", 0) or 0)}
        link = str(i.get("link", ""))
        if link.startswith("https://github.com/") and len(link) < 400:
            entry["link"] = link
        out.append(entry)
    return out


SNIPPET_BEFORE = 50
SNIPPET_AFTER = 90


def _snippet(texts: list[str], terms: list[str]) -> dict[str, Any]:
    """Ausschnitt um die erste Fundstelle in den Nachrichten: ``{"snippet": str, "hl": [[von, bis], ...]}``."""
    for text in texts:
        low = fold(text)
        spots = [(low.find(t), t) for t in terms if t in low]
        if not spots:
            continue
        pos = min(p for p, _ in spots)
        start = max(0, pos - SNIPPET_BEFORE)
        end = min(len(text), pos + SNIPPET_AFTER)
        if start > 0:  # nicht mitten im Wort anfangen
            space = text.find(" ", start, pos)
            start = space + 1 if space != -1 else start
        piece = re.sub(r"\s", " ", text[start:end])
        lead = "…" if start > 0 else ""
        out = lead + piece
        hl: list[list[int]] = []
        low_piece = low[start:end]
        for term in terms:
            at = 0
            while (i := low_piece.find(term, at)) != -1:
                hl.append([len(lead) + i, len(lead) + i + len(term)])
                at = i + len(term)
        hl.sort()
        merged: list[list[int]] = []
        for a, b in hl:
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        return {"snippet": out + ("…" if end < len(text) else ""), "hl": merged}
    return {"snippet": "", "hl": []}


_FILE_ID = re.compile(r"^[0-9a-f]{32}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _require(profile_id: str) -> str:
    if not isinstance(profile_id, str) or not profile_id:
        raise ValueError("profile_id ist erforderlich")
    return profile_id


class Store:
    def __init__(self, path: Path | str) -> None:
        self._lock = threading.RLock()
        self.files_dir = Path(path).parent / "outfiles"  # erzeugte Dateien (Inhalt); die Angaben dazu stehen in der Tabelle outfiles
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.create_function("fold", 1, fold, deterministic=True)
        self._conn.execute("PRAGMA journal_mode = WAL")
        with self._lock, self._conn:
            self._conn.executescript(SCHEMA)
            self._migrate()

    def _migrate(self) -> None:
        """Spalten und Trigger nachrüsten (bestehende Datenbanken bleiben erhalten)."""
        columns = {r["name"] for r in self._conn.execute("PRAGMA table_info(chats)")}
        if "pinned_at" not in columns:
            self._conn.execute("ALTER TABLE chats ADD COLUMN pinned_at TEXT")
        if "project_id" not in columns:
            self._conn.execute("ALTER TABLE chats ADD COLUMN project_id TEXT")
        if "unread" not in columns:
            self._conn.execute("ALTER TABLE chats ADD COLUMN unread INTEGER NOT NULL DEFAULT 0")  # 1 = neue Antwort noch nicht gesehen
        if "summary" not in columns:
            self._conn.execute("ALTER TABLE chats ADD COLUMN summary TEXT")
        if "model" not in columns:
            self._conn.execute("ALTER TABLE chats ADD COLUMN model TEXT NOT NULL DEFAULT ''")  # zuletzt gewähltes Modell dieses Chats ('' = Standard)
        if "schedule_id" not in columns:
            self._conn.execute("ALTER TABLE chats ADD COLUMN schedule_id TEXT NOT NULL DEFAULT ''")  # Chat entstand durch eine geplante Aufgabe
        if "summary_upto" not in columns:
            self._conn.execute("ALTER TABLE chats ADD COLUMN summary_upto INTEGER")
        profile_columns = {r["name"] for r in self._conn.execute("PRAGMA table_info(profiles)")}
        if "label" not in profile_columns:
            self._conn.execute("ALTER TABLE profiles ADD COLUMN label TEXT")  # nur bei automatisch angelegten HA-Profilen
        if "ha_user_id" not in profile_columns:
            self._conn.execute("ALTER TABLE profiles ADD COLUMN ha_user_id TEXT")
        project_columns = {r["name"] for r in self._conn.execute("PRAGMA table_info(projects)")}
        if "instructions" not in project_columns:
            self._conn.execute("ALTER TABLE projects ADD COLUMN instructions TEXT NOT NULL DEFAULT ''")
        message_columns = {r["name"] for r in self._conn.execute("PRAGMA table_info(messages)")}
        if "attachments" not in message_columns:
            self._conn.execute("ALTER TABLE messages ADD COLUMN attachments TEXT")  # JSON: nur Name, Art, Größe
        if "tools" not in message_columns:
            self._conn.execute("ALTER TABLE messages ADD COLUMN tools TEXT")  # JSON: Aktionen in Home Assistant (Beschriftung, Art, Ergebnis)
        self._conn.executescript(KNOWLEDGE_SCHEMA)
        self._conn.executescript(STATE_SCHEMA)
        self._conn.executescript(OUTFILES_SCHEMA)
        self._conn.executescript(SCHEDULES_SCHEMA)
        self._conn.executescript(MIGRATION_OBJECTS)
        self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def snapshot(self, snap_dir: Path, prefix: str = "ki_chat-") -> Path:
        """Konsistenter Schnappschuss der laufenden Datenbank (siehe safety.py)."""
        from .safety import snapshot_live

        with self._lock:
            return snapshot_live(self._conn, snap_dir, prefix)

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # alles in die Hauptdatei, bevor HA sichert
            except sqlite3.Error:
                pass
            self._conn.close()

    def sync_profiles(self, profile_ids: Iterable[str]) -> None:
        """Profile aus der Konfiguration eintragen. Entfernte Profile behalten ihre Daten."""
        with self._lock, self._conn:
            for pid in profile_ids:
                self._conn.execute(
                    "INSERT OR IGNORE INTO profiles (id) VALUES (?)", (_require(pid),)
                )

    def remember_ha_profile(self, profile_id: str, label: str, ha_user_id: str) -> None:
        """Automatisch zugelassenen HA-Benutzer festhalten (Anzeigename für Domain-Sitzungen nach einem Neustart)."""
        with self._lock, self._conn:
            self._conn.execute("INSERT OR IGNORE INTO profiles (id) VALUES (?)", (_require(profile_id),))
            self._conn.execute("UPDATE profiles SET label = ?, ha_user_id = ? WHERE id = ?", (label, ha_user_id, profile_id))

    def recall_ha_profile(self, profile_id: str) -> tuple[str, str] | None:
        """(Anzeigename, HA-Benutzer-ID) eines automatisch zugelassenen Profils oder ``None``."""
        with self._lock:
            row = self._conn.execute(
                "SELECT label, ha_user_id FROM profiles WHERE id = ? AND ha_user_id IS NOT NULL", (profile_id,)
            ).fetchone()
        return (row["label"] or "", row["ha_user_id"]) if row else None

    # ------------------------------------------------------- Entra-Zuordnung

    def profile_id_for_oid(self, oid: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT id FROM profiles WHERE entra_oid = ?", (oid,)).fetchone()
        return row["id"] if row else None

    def bind_oid(self, profile_id: str, oid: str) -> bool:
        """oid beim ersten Login an das Profil binden. False, wenn es schon anders belegt ist."""
        _require(profile_id)
        try:
            with self._lock, self._conn:
                cur = self._conn.execute(
                    "UPDATE profiles SET entra_oid = ? WHERE id = ? AND entra_oid IS NULL",
                    (oid, profile_id),
                )
                if cur.rowcount == 1:
                    return True
                row = self._conn.execute(
                    "SELECT entra_oid FROM profiles WHERE id = ?", (profile_id,)
                ).fetchone()
                return bool(row) and row["entra_oid"] == oid
        except sqlite3.IntegrityError:  # oid gehört bereits einem anderen Profil
            return False

    # ---------------------------------------------------------------- Sitzungen

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def create_session(self, profile_id: str, days: int) -> str:
        """Neue Sitzung anlegen. Gespeichert wird nur der Hash des Tokens."""
        _require(profile_id)
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO sessions (token_hash, profile_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (self._hash(token), profile_id, now.isoformat(timespec="seconds"),
                 (now + timedelta(days=days)).isoformat(timespec="seconds")),
            )
            self._conn.execute(
                "DELETE FROM sessions WHERE expires_at < ?", (now.isoformat(timespec="seconds"),)
            )
        return token

    def session_profile(self, token: str, days: int) -> str | None:
        """Profil-ID zur Sitzung, solange sie gültig ist. Verlängert sie höchstens täglich."""
        if not token:
            return None
        now = datetime.now(timezone.utc)
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT profile_id, created_at, expires_at FROM sessions WHERE token_hash = ?",
                (self._hash(token),),
            ).fetchone()
            if not row:
                return None
            created = datetime.fromisoformat(row["created_at"])
            if row["expires_at"] < now.isoformat(timespec="seconds") or now - created > timedelta(days=SESSION_MAX_DAYS):
                self._conn.execute("DELETE FROM sessions WHERE token_hash = ?", (self._hash(token),))
                return None
            new_expiry = min(now + timedelta(days=days), created + timedelta(days=SESSION_MAX_DAYS))
            if datetime.fromisoformat(row["expires_at"]) < new_expiry - timedelta(days=1):
                self._conn.execute(
                    "UPDATE sessions SET expires_at = ? WHERE token_hash = ?",
                    (new_expiry.isoformat(timespec="seconds"), self._hash(token)),
                )
        return row["profile_id"]

    def delete_session(self, token: str) -> None:
        if token:
            with self._lock, self._conn:
                self._conn.execute("DELETE FROM sessions WHERE token_hash = ?", (self._hash(token),))

    # ------------------------------------------------------------------ Chats

    def _owns_project(self, profile_id: str, project_id: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM projects WHERE id = ? AND profile_id = ?", (project_id, profile_id)
        ).fetchone() is not None

    def create_chat(
        self, profile_id: str, title: str = "Neuer Chat", project_id: str | None = None, schedule_id: str = ""
    ) -> dict[str, Any] | None:
        """Neuen Chat anlegen. None, wenn das Projekt nicht zu diesem Profil gehört."""
        _require(profile_id)
        chat_id = uuid.uuid4().hex
        now = _now()
        with self._lock, self._conn:
            if project_id is not None and not self._owns_project(profile_id, project_id):
                return None
            self._conn.execute(
                "INSERT INTO chats (id, profile_id, title, created_at, updated_at, project_id, schedule_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (chat_id, profile_id, title, now, now, project_id, schedule_id),
            )
        return {
            "id": chat_id, "title": title, "created_at": now, "updated_at": now,
            "pinned": False, "project_id": project_id, "unread": False, "model": "", "schedule_id": schedule_id,
        }

    def list_chats(self, profile_id: str) -> list[dict[str, Any]]:
        _require(profile_id)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {CHAT_FIELDS} FROM chats "
                "WHERE profile_id = ? ORDER BY updated_at DESC, created_at DESC",
                (profile_id,),
            ).fetchall()
        return [_chat(r) for r in rows]

    def search_chats(self, profile_id: str, query: str, limit: int = 30) -> list[dict[str, Any]]:
        """Chats der Person, in denen alle Suchwörter vorkommen (im Titel oder in den Nachrichten), neueste zuerst.

        Ohne Beachtung von Groß-/Kleinschreibung und Umlautpunkten. Je Treffer ein Ausschnitt mit den Stellen zum Hervorheben.
        """
        _require(profile_id)
        terms = []
        for word in fold(query).split():
            if word not in terms:
                terms.append(word)
        terms = terms[:6]
        if not terms:
            return []
        clauses = " AND ".join(
            "(instr(fold(c.title), ?) > 0 OR EXISTS (SELECT 1 FROM messages m WHERE m.chat_id = c.id AND m.profile_id = c.profile_id "
            "AND instr(fold(m.content), ?) > 0))"
            for _ in terms
        )
        params: list[Any] = [profile_id]
        for term in terms:
            params += [term, term]
        with self._lock:
            chats = self._conn.execute(
                f"SELECT c.id, c.title, c.updated_at, c.project_id, c.schedule_id FROM chats c WHERE c.profile_id = ? AND {clauses} "
                "ORDER BY c.updated_at DESC, c.created_at DESC LIMIT ?",
                (*params, max(1, min(limit, 100))),
            ).fetchall()
            found = []
            for chat in chats:
                texts = [r["content"] for r in self._conn.execute(
                    "SELECT content FROM messages WHERE chat_id = ? AND profile_id = ? ORDER BY id", (chat["id"], profile_id)
                )]
                found.append((chat, texts))
        return [
            {"chat_id": chat["id"], "title": chat["title"], "updated_at": chat["updated_at"],
             "project_id": chat["project_id"], "schedule_id": chat["schedule_id"], **_snippet(texts, terms)}
            for chat, texts in found
        ]

    def get_chat(self, profile_id: str, chat_id: str) -> dict[str, Any] | None:
        _require(profile_id)
        with self._lock:
            row = self._conn.execute(
                f"SELECT {CHAT_FIELDS} FROM chats WHERE id = ? AND profile_id = ?",
                (chat_id, profile_id),
            ).fetchone()
        return _chat(row) if row else None

    def set_chat_model(self, profile_id: str, chat_id: str, model: str) -> bool:
        """Gewähltes Modell eines Chats merken ('' = wieder das Standard-Modell). Ändert weder Titel noch Reihenfolge."""
        _require(profile_id)
        with self._lock, self._conn:
            cur = self._conn.execute("UPDATE chats SET model = ? WHERE id = ? AND profile_id = ?", (model, chat_id, profile_id))
        return cur.rowcount == 1

    # -------------------------------------------------------- Geplante Aufgaben

    def schedule_create(self, profile_id: str, fields: dict[str, Any], next_run: int | None) -> dict[str, Any] | None:
        """Aufgabe anlegen. ``None``, wenn die Person schon ``SCHEDULE_LIMIT`` Aufgaben hat."""
        _require(profile_id)
        sid = uuid.uuid4().hex
        with self._lock, self._conn:
            count = self._conn.execute("SELECT COUNT(*) FROM schedules WHERE profile_id = ?", (profile_id,)).fetchone()[0]
            if count >= SCHEDULE_LIMIT:
                return None
            self._conn.execute(
                "INSERT INTO schedules (id, profile_id, name, prompt, freq, at_time, days, enabled, model, web, notify, next_run, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (sid, profile_id, fields["name"], fields["prompt"], fields["freq"], fields["at_time"], fields["days"],
                 1 if fields.get("enabled", True) else 0, fields.get("model", ""), 1 if fields.get("web", True) else 0,
                 fields.get("notify", "chat"), next_run, _now()),
            )
        return self.schedule_get(profile_id, sid)

    def schedule_list(self, profile_id: str) -> list[dict[str, Any]]:
        _require(profile_id)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {SCHEDULE_FIELDS} FROM schedules WHERE profile_id = ? ORDER BY created_at, id", (profile_id,)
            ).fetchall()
        return [_schedule(r) for r in rows]

    def schedule_get(self, profile_id: str, schedule_id: str) -> dict[str, Any] | None:
        _require(profile_id)
        with self._lock:
            row = self._conn.execute(
                f"SELECT {SCHEDULE_FIELDS} FROM schedules WHERE id = ? AND profile_id = ?", (schedule_id, profile_id)
            ).fetchone()
        return _schedule(row) if row else None

    def schedule_update(self, profile_id: str, schedule_id: str, fields: dict[str, Any], next_run: int | None) -> dict[str, Any] | None:
        """Felder ändern (nur die übergebenen) und den nächsten Zeitpunkt neu setzen."""
        _require(profile_id)
        allowed = {"name", "prompt", "freq", "at_time", "days", "enabled", "model", "web", "notify"}
        sets, values = ["next_run = ?"], [next_run]
        for key, value in fields.items():
            if key not in allowed:
                continue
            sets.append(f"{key} = ?")
            values.append(int(value) if key in ("enabled", "web") else value)
        with self._lock, self._conn:
            cur = self._conn.execute(
                f"UPDATE schedules SET {', '.join(sets)} WHERE id = ? AND profile_id = ?", (*values, schedule_id, profile_id)
            )
        return self.schedule_get(profile_id, schedule_id) if cur.rowcount == 1 else None

    def schedule_delete(self, profile_id: str, schedule_id: str) -> bool:
        _require(profile_id)
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM schedules WHERE id = ? AND profile_id = ?", (schedule_id, profile_id))
        return cur.rowcount == 1

    def schedule_due(self, now: int) -> list[dict[str, Any]]:
        """Alle fälligen Aufgaben (aktiv und ``next_run`` erreicht), mit der Person; die ältesten zuerst."""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT profile_id, {SCHEDULE_FIELDS} FROM schedules WHERE enabled = 1 AND next_run IS NOT NULL AND next_run <= ? "
                "ORDER BY next_run, id",
                (now,),
            ).fetchall()
        return [{**_schedule(r), "profile_id": r["profile_id"]} for r in rows]

    def schedule_claim(self, schedule_id: str, due: int, next_run: int | None) -> bool:
        """Fällige Ausführung übernehmen und gleich den nächsten Zeitpunkt setzen (einmalige Aufgaben werden damit ausgeschaltet).

        Gelingt nur, wenn ``next_run`` noch der erwartete Wert ist; so läuft nichts doppelt und ein Absturz mitten im Lauf
        wiederholt die Aufgabe nicht in Endlosschleife.
        """
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE schedules SET next_run = ?, enabled = CASE WHEN ? IS NULL THEN 0 ELSE enabled END "
                "WHERE id = ? AND enabled = 1 AND next_run = ?",
                (next_run, next_run, schedule_id, due),
            )
        return cur.rowcount == 1

    def schedule_record(self, schedule_id: str, *, status: str, note: str = "", chat_id: str = "", ran: bool = True) -> None:
        """Ergebnis des letzten Laufs festhalten (``ran``: wirklich gelaufen, zählt hoch)."""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE schedules SET last_run = ?, last_status = ?, last_note = ?, last_chat_id = CASE WHEN ? != '' THEN ? ELSE last_chat_id END, "
                "runs = runs + ? WHERE id = ?",
                (int(datetime.now().timestamp()), status, note[:300], chat_id, chat_id, 1 if ran else 0, schedule_id),
            )

    def schedule_enabled(self) -> list[tuple[str, dict[str, Any]]]:
        """Alle eingeschalteten Aufgaben mit der Person (zum Neuberechnen der Zeitpunkte)."""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT profile_id, {SCHEDULE_FIELDS} FROM schedules WHERE enabled = 1 AND next_run IS NOT NULL"
            ).fetchall()
        return [(r["profile_id"], _schedule(r)) for r in rows]

    def schedule_set_next(self, schedule_id: str, next_run: int | None) -> None:
        with self._lock, self._conn:
            self._conn.execute("UPDATE schedules SET next_run = ? WHERE id = ?", (next_run, schedule_id))

    def rename_chat(self, profile_id: str, chat_id: str, title: str) -> bool:
        _require(profile_id)
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE chats SET title = ? WHERE id = ? AND profile_id = ?",
                (title, chat_id, profile_id),
            )
        return cur.rowcount == 1

    def replace_title_if(self, profile_id: str, chat_id: str, expected: str, title: str) -> bool:
        """Titel nur ersetzen, wenn er noch dem automatisch erzeugten Wert entspricht (nie einen eigenen überschreiben)."""
        _require(profile_id)
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE chats SET title = ? WHERE id = ? AND profile_id = ? AND title = ?",
                (title, chat_id, profile_id, expected),
            )
        return cur.rowcount == 1

    def set_chat_unread(self, profile_id: str, chat_id: str, unread: bool) -> bool:
        """Lesestatus setzen; ändert weder Titel noch Reihenfolge (``updated_at`` bleibt)."""
        _require(profile_id)
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE chats SET unread = ? WHERE id = ? AND profile_id = ?",
                (1 if unread else 0, chat_id, profile_id),
            )
        return cur.rowcount == 1

    def set_chat_pinned(self, profile_id: str, chat_id: str, pinned: bool) -> bool:
        _require(profile_id)
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE chats SET pinned_at = ? WHERE id = ? AND profile_id = ?",
                (_now() if pinned else None, chat_id, profile_id),
            )
        return cur.rowcount == 1

    def move_chat(self, profile_id: str, chat_id: str, project_id: str | None) -> bool:
        """Chat in ein Projekt legen (oder mit None herausnehmen). False, wenn Chat oder Projekt nicht passen."""
        _require(profile_id)
        with self._lock, self._conn:
            if project_id is not None and not self._owns_project(profile_id, project_id):
                return False
            cur = self._conn.execute(
                "UPDATE chats SET project_id = ? WHERE id = ? AND profile_id = ?",
                (project_id, chat_id, profile_id),
            )
        return cur.rowcount == 1

    def delete_chat(self, profile_id: str, chat_id: str) -> bool:
        _require(profile_id)
        with self._lock:
            files = [r["id"] for r in self._conn.execute("SELECT id FROM outfiles WHERE chat_id = ? AND profile_id = ?", (chat_id, profile_id))]
            with self._conn:
                cur = self._conn.execute(
                    "DELETE FROM chats WHERE id = ? AND profile_id = ?", (chat_id, profile_id)
                )
        if cur.rowcount == 1:
            for file_id in files:  # Dateien des Chats gehen mit ihm
                self._outfile_path(file_id).unlink(missing_ok=True)
        return cur.rowcount == 1

    def delete_all_chats(self, profile_id: str) -> int:
        """Alle Chats der Person samt Nachrichten und erzeugten Dateien löschen; Projekte, Gedächtnis und Aufgaben bleiben."""
        _require(profile_id)
        with self._lock:
            files = [r["id"] for r in self._conn.execute("SELECT id FROM outfiles WHERE profile_id = ?", (profile_id,))]
            with self._conn:
                cur = self._conn.execute("DELETE FROM chats WHERE profile_id = ?", (profile_id,))
        for file_id in files:
            self._outfile_path(file_id).unlink(missing_ok=True)
        return cur.rowcount

    # ---------------------------------------------------------------- Projekte

    def create_project(self, profile_id: str, name: str) -> dict[str, Any]:
        _require(profile_id)
        project_id = uuid.uuid4().hex
        now = _now()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO projects (id, profile_id, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (project_id, profile_id, name, now, now),
            )
        return {
            "id": project_id, "name": name, "pinned": False, "instructions": "", "created_at": now, "updated_at": now,
        }

    def list_projects(self, profile_id: str) -> list[dict[str, Any]]:
        _require(profile_id)
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, name, pinned_at, instructions, created_at, updated_at, "
                "(SELECT COUNT(*) FROM knowledge k WHERE k.project_id = projects.id) AS knowledge FROM projects "
                "WHERE profile_id = ? ORDER BY name COLLATE NOCASE",
                (profile_id,),
            ).fetchall()
        return [_project(r) for r in rows]

    def get_project(self, profile_id: str, project_id: str) -> dict[str, Any] | None:
        _require(profile_id)
        with self._lock:
            row = self._conn.execute(
                "SELECT id, name, pinned_at, instructions, created_at, updated_at, "
                "(SELECT COUNT(*) FROM knowledge k WHERE k.project_id = projects.id) AS knowledge FROM projects WHERE id = ? AND profile_id = ?",
                (project_id, profile_id),
            ).fetchone()
        return _project(row) if row else None

    def rename_project(self, profile_id: str, project_id: str, name: str) -> bool:
        _require(profile_id)
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE projects SET name = ?, updated_at = ? WHERE id = ? AND profile_id = ?",
                (name, _now(), project_id, profile_id),
            )
        return cur.rowcount == 1

    def set_project_pinned(self, profile_id: str, project_id: str, pinned: bool) -> bool:
        _require(profile_id)
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE projects SET pinned_at = ? WHERE id = ? AND profile_id = ?",
                (_now() if pinned else None, project_id, profile_id),
            )
        return cur.rowcount == 1

    def set_project_instructions(self, profile_id: str, project_id: str, instructions: str) -> bool:
        _require(profile_id)
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE projects SET instructions = ?, updated_at = ? WHERE id = ? AND profile_id = ?",
                (instructions[:INSTRUCTIONS_MAX], _now(), project_id, profile_id),
            )
        return cur.rowcount == 1

    def chat_instructions(self, profile_id: str, chat_id: str) -> str:
        """Anweisungen des Projekts, in dem der Chat liegt (leer, wenn kein Projekt oder keine Anweisungen)."""
        _require(profile_id)
        with self._lock:
            row = self._conn.execute(
                "SELECT p.instructions FROM chats c JOIN projects p ON p.id = c.project_id AND p.profile_id = c.profile_id "
                "WHERE c.id = ? AND c.profile_id = ?",
                (chat_id, profile_id),
            ).fetchone()
        return row["instructions"] if row else ""

    def delete_project(self, profile_id: str, project_id: str) -> bool:
        """Projekt löschen. Die Chats bleiben erhalten und liegen danach ohne Projekt in der Liste."""
        _require(profile_id)
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE chats SET project_id = NULL WHERE project_id = ? AND profile_id = ?",
                (project_id, profile_id),
            )
            cur = self._conn.execute(
                "DELETE FROM projects WHERE id = ? AND profile_id = ?", (project_id, profile_id)
            )
        return cur.rowcount == 1

    # ------------------------------------------------------------ Projektwissen

    def add_knowledge(self, profile_id: str, project_id: str, name: str, content: str) -> dict[str, Any] | None:
        """Datei zum Wissen eines Projekts hinzufügen; gleicher Name ersetzt die alte Fassung."""
        _require(profile_id)
        now = _now()
        with self._lock, self._conn:
            owned = self._conn.execute(
                "SELECT 1 FROM projects WHERE id = ? AND profile_id = ?", (project_id, profile_id)
            ).fetchone()
            if not owned:
                return None
            self._conn.execute(
                "INSERT INTO knowledge (profile_id, project_id, name, content, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(project_id, name) DO UPDATE SET content = excluded.content, updated_at = excluded.updated_at",
                (profile_id, project_id, name, content, now, now),
            )
            row = self._conn.execute(
                "SELECT id, name, length(content) AS size, updated_at FROM knowledge WHERE project_id = ? AND name = ?",
                (project_id, name),
            ).fetchone()
        return dict(row)

    def list_knowledge(self, profile_id: str, project_id: str) -> list[dict[str, Any]] | None:
        """Dateien des Projektwissens (ohne Inhalt); ``None``, wenn das Projekt nicht dem Profil gehört."""
        _require(profile_id)
        with self._lock:
            owned = self._conn.execute(
                "SELECT 1 FROM projects WHERE id = ? AND profile_id = ?", (project_id, profile_id)
            ).fetchone()
            if not owned:
                return None
            rows = self._conn.execute(
                "SELECT id, name, length(content) AS size, updated_at FROM knowledge "
                "WHERE project_id = ? AND profile_id = ? ORDER BY name COLLATE NOCASE",
                (project_id, profile_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def knowledge_totals(self, profile_id: str, project_id: str) -> tuple[int, int]:
        """(Anzahl Dateien, Zeichen insgesamt) des Projektwissens."""
        _require(profile_id)
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(length(content)), 0) AS chars FROM knowledge WHERE project_id = ? AND profile_id = ?",
                (project_id, profile_id),
            ).fetchone()
        return row["n"], row["chars"]

    def knowledge_texts(self, profile_id: str, project_id: str) -> list[tuple[str, str]]:
        """(Name, Inhalt) aller Dateien des Projektwissens, für die Suche."""
        _require(profile_id)
        with self._lock:
            rows = self._conn.execute(
                "SELECT name, content FROM knowledge WHERE project_id = ? AND profile_id = ? ORDER BY name COLLATE NOCASE",
                (project_id, profile_id),
            ).fetchall()
        return [(r["name"], r["content"]) for r in rows]

    def get_knowledge(self, profile_id: str, project_id: str, name: str) -> str | None:
        _require(profile_id)
        with self._lock:
            row = self._conn.execute(
                "SELECT content FROM knowledge WHERE project_id = ? AND profile_id = ? AND name = ? COLLATE NOCASE",
                (project_id, profile_id, name),
            ).fetchone()
        return row["content"] if row else None

    def delete_knowledge(self, profile_id: str, project_id: str, knowledge_id: int) -> bool:
        _require(profile_id)
        with self._lock, self._conn:
            cur = self._conn.execute(
                "DELETE FROM knowledge WHERE id = ? AND project_id = ? AND profile_id = ?",
                (knowledge_id, project_id, profile_id),
            )
        return cur.rowcount == 1

    def chat_project_id(self, profile_id: str, chat_id: str) -> str | None:
        _require(profile_id)
        with self._lock:
            row = self._conn.execute(
                "SELECT project_id FROM chats WHERE id = ? AND profile_id = ?", (chat_id, profile_id)
            ).fetchone()
        return row["project_id"] if row else None

    # --------------------------------------------------------------- Gedächtnis

    @staticmethod
    def _memory_owner(scope: str, profile_id: str) -> str:
        if scope == "household":
            return ""
        if scope == "person":
            return _require(profile_id)
        raise ValueError("scope muss household oder person sein")

    def memory_list(self, scope: str, profile_id: str = "", auto: bool | None = None) -> list[dict[str, Any]]:
        """Einträge des Haushalts (``scope='household'``) oder einer Person; Person nie ohne Profil-ID.

        ``auto``: ``False`` = ohne die automatisch erfassten Überblick-Einträge, ``True`` = nur diese, ``None`` = alle.
        """
        owner = self._memory_owner(scope, profile_id)
        extra = "" if auto is None else (" AND author = ?" if auto else " AND author <> ?")
        params: tuple = (scope, owner) if auto is None else (scope, owner, AUTO_AUTHOR)
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, topic, content, author, updated_at FROM memories WHERE scope = ? AND owner = ?" + extra
                + " ORDER BY topic COLLATE NOCASE",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def memory_count(self, scope: str, profile_id: str = "") -> int:
        """Anzahl der Einträge für die Obergrenze; die automatisch erfassten des Überblicks zählen nicht mit."""
        owner = self._memory_owner(scope, profile_id)
        with self._lock:
            return self._conn.execute(
                "SELECT COUNT(*) FROM memories WHERE scope = ? AND owner = ? AND author <> ?", (scope, owner, AUTO_AUTHOR)
            ).fetchone()[0]

    def memory_replace_auto(self, entries: list[tuple[str, str]]) -> int:
        """Den automatisch erfassten Überblick im Haushalt ersetzen (alles oder nichts); liefert die Anzahl neuer Einträge."""
        now = _now()
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM memories WHERE scope = 'household' AND owner = '' AND author = ?", (AUTO_AUTHOR,))
            for topic, content in entries:
                self._conn.execute(
                    "INSERT INTO memories (scope, owner, topic, content, author, created_at, updated_at) "
                    "VALUES ('household', '', ?, ?, ?, ?, ?) "
                    "ON CONFLICT(scope, owner, topic) DO UPDATE SET content = excluded.content, author = excluded.author, "
                    "updated_at = excluded.updated_at",
                    (topic, content, AUTO_AUTHOR, now, now),
                )
        return len(entries)

    def state_get(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def state_set(self, key: str, value: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO app_state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def memory_save(self, scope: str, profile_id: str, topic: str, content: str, author: str = "") -> dict[str, Any]:
        """Eintrag anlegen oder (gleiches Thema, Groß-/Kleinschreibung egal) aktualisieren."""
        owner = self._memory_owner(scope, profile_id)
        now = _now()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO memories (scope, owner, topic, content, author, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(scope, owner, topic) DO UPDATE SET content = excluded.content, author = excluded.author, "
                "updated_at = excluded.updated_at",
                (scope, owner, topic, content, author, now, now),
            )
            row = self._conn.execute(
                "SELECT id, topic, content, author, updated_at FROM memories WHERE scope = ? AND owner = ? AND topic = ? COLLATE NOCASE",
                (scope, owner, topic),
            ).fetchone()
        return dict(row)

    def memory_has_topic(self, scope: str, profile_id: str, topic: str) -> bool:
        owner = self._memory_owner(scope, profile_id)
        with self._lock:
            return self._conn.execute(
                "SELECT 1 FROM memories WHERE scope = ? AND owner = ? AND topic = ? COLLATE NOCASE AND author <> ?", (scope, owner, topic, AUTO_AUTHOR)
            ).fetchone() is not None

    def memory_delete(self, scope: str, profile_id: str, memory_id: int) -> bool:
        owner = self._memory_owner(scope, profile_id)
        with self._lock, self._conn:
            cur = self._conn.execute(
                "DELETE FROM memories WHERE id = ? AND scope = ? AND owner = ? AND author <> ?", (memory_id, scope, owner, AUTO_AUTHOR)
            )
        return cur.rowcount == 1

    def memory_delete_topic(self, scope: str, profile_id: str, topic: str) -> bool:
        owner = self._memory_owner(scope, profile_id)
        with self._lock, self._conn:
            cur = self._conn.execute(
                "DELETE FROM memories WHERE scope = ? AND owner = ? AND topic = ? COLLATE NOCASE AND author <> ?", (scope, owner, topic, AUTO_AUTHOR)
            )
        return cur.rowcount == 1

    # ------------------------------------------------------- erzeugte Dateien

    def _outfile_path(self, file_id: str) -> Path:
        return self.files_dir / file_id

    def outfile_add(self, profile_id: str, chat_id: str, name: str, mime: str, data: bytes, keep_days: int) -> dict[str, Any] | None:
        """Eine von der KI erzeugte Datei ablegen (Inhalt auf der Platte, Angaben in der Datenbank). ``None``: Chat unbekannt."""
        _require(profile_id)
        file_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc)
        with self._lock:
            owned = self._conn.execute("SELECT 1 FROM chats WHERE id = ? AND profile_id = ?", (chat_id, profile_id)).fetchone()
            if not owned:
                return None
            self.files_dir.mkdir(parents=True, exist_ok=True)
            target = self._outfile_path(file_id)
            partial = target.with_name(file_id + ".part")
            partial.write_bytes(data)
            os.replace(partial, target)
            try:
                with self._conn:
                    self._conn.execute(
                        "INSERT INTO outfiles (id, profile_id, chat_id, name, mime, size, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (file_id, profile_id, chat_id, name, mime, len(data), now.isoformat(timespec="seconds"),
                         (now + timedelta(days=max(1, keep_days))).isoformat(timespec="seconds")),
                    )
            except sqlite3.Error:
                target.unlink(missing_ok=True)
                raise
        return {"id": file_id, "name": name, "mime": mime, "size": len(data)}

    def outfile_open(self, profile_id: str, file_id: str) -> tuple[dict[str, Any], Path] | None:
        """Datei zum Herunterladen: nur für den Besitzer und solange sie nicht abgelaufen ist."""
        _require(profile_id)
        if not _FILE_ID.match(file_id or ""):
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT id, name, mime, size FROM outfiles WHERE id = ? AND profile_id = ? AND expires_at > ?", (file_id, profile_id, _now())
            ).fetchone()
        path = self._outfile_path(file_id)
        if not row or not path.is_file():
            return None
        return dict(row), path

    def outfile_bytes(self, profile_id: str, chat_id: str, name: str) -> bytes | None:
        """Inhalt der zuletzt in diesem Chat erzeugten Datei mit diesem Namen (für Commits zu GitHub)."""
        _require(profile_id)
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM outfiles WHERE profile_id = ? AND chat_id = ? AND name = ? AND expires_at > ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (profile_id, chat_id, name, _now()),
            ).fetchone()
        if not row:
            return None
        try:
            return self._outfile_path(row["id"]).read_bytes()
        except OSError:
            return None

    def outfile_usage(self, profile_id: str) -> int:
        _require(profile_id)
        with self._lock:
            row = self._conn.execute("SELECT COALESCE(SUM(size), 0) AS n FROM outfiles WHERE profile_id = ? AND expires_at > ?", (profile_id, _now())).fetchone()
        return int(row["n"])

    def outfile_sweep(self, grace_seconds: int = 900) -> int:
        """Abgelaufene Dateien entfernen sowie Dateien ohne Eintrag (Chat gelöscht); liefert die Anzahl entfernter Dateien."""
        removed = 0
        with self._lock:
            with self._conn:
                expired = [r["id"] for r in self._conn.execute("SELECT id FROM outfiles WHERE expires_at <= ?", (_now(),))]
                for file_id in expired:
                    self._conn.execute("DELETE FROM outfiles WHERE id = ?", (file_id,))
            known = {r["id"] for r in self._conn.execute("SELECT id FROM outfiles")}
        for file_id in expired:
            self._outfile_path(file_id).unlink(missing_ok=True)
            removed += 1
        if self.files_dir.is_dir():
            cutoff = datetime.now().timestamp() - grace_seconds  # frisch geschriebene Dateien (Eintrag folgt gleich) nicht anfassen
            for path in self.files_dir.iterdir():
                stem = path.name.removesuffix(".part")
                if path.is_file() and stem not in known and path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    removed += 1
        return removed

    # -------------------------------------------------------------- Nachrichten

    def add_message(
        self,
        profile_id: str,
        chat_id: str,
        role: str,
        content: str,
        attachments: list[dict] | None = None,
        tools: list[dict] | None = None,
    ) -> dict[str, Any] | None:
        """Eine Nachricht speichern. Die Frage wird sofort beim Senden abgelegt, die Antwort, sobald sie vorliegt.

        ``attachments`` = nur Angaben zu den Dateien (Name, Art, Größe), nie deren Inhalt.
        """
        _require(profile_id)
        now = _now()
        files = json.dumps(attachments, ensure_ascii=False) if attachments else None
        actions = json.dumps(tools, ensure_ascii=False) if tools else None
        with self._lock, self._conn:
            owned = self._conn.execute(
                "SELECT 1 FROM chats WHERE id = ? AND profile_id = ?", (chat_id, profile_id)
            ).fetchone()
            if not owned:
                return None
            cur = self._conn.execute(
                "INSERT INTO messages (chat_id, profile_id, role, content, created_at, attachments, tools) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (chat_id, profile_id, role, content, now, files, actions),
            )
            self._conn.execute(
                "UPDATE chats SET updated_at = ?, unread = CASE WHEN ? = 'assistant' THEN 1 ELSE unread END "
                "WHERE id = ? AND profile_id = ?",
                (now, role, chat_id, profile_id),
            )
        return {"id": cur.lastrowid, "role": role, "content": content, "created_at": now}

    def delete_message(self, profile_id: str, chat_id: str, message_id: int) -> bool:
        """Eine Nachricht zurücknehmen (Frage ohne jede Antwort)."""
        _require(profile_id)
        with self._lock, self._conn:
            cur = self._conn.execute(
                "DELETE FROM messages WHERE id = ? AND chat_id = ? AND profile_id = ?",
                (message_id, chat_id, profile_id),
            )
        return cur.rowcount == 1

    def add_exchange(
        self,
        profile_id: str,
        chat_id: str,
        user_content: str,
        assistant_content: str,
        attachments: list[dict] | None = None,
    ) -> bool:
        """Frage und Antwort gemeinsam speichern (alles oder nichts).

        ``attachments`` = nur Angaben zu den Dateien (Name, Art, Größe), nie deren Inhalt.
        """
        _require(profile_id)
        now = _now()
        with self._lock, self._conn:
            owned = self._conn.execute(
                "SELECT 1 FROM chats WHERE id = ? AND profile_id = ?", (chat_id, profile_id)
            ).fetchone()
            if not owned:
                return False
            files = json.dumps(attachments, ensure_ascii=False) if attachments else None
            for role, content in (("user", user_content), ("assistant", assistant_content)):
                if content:
                    self._conn.execute(
                        "INSERT INTO messages (chat_id, profile_id, role, content, created_at, attachments) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (chat_id, profile_id, role, content, now, files if role == "user" else None),
                    )
            # Neue Antwort = ungelesen, bis eine Oberfläche sie angezeigt und den Status zurückgesetzt hat.
            self._conn.execute(
                "UPDATE chats SET updated_at = ?, unread = CASE WHEN ? THEN 1 ELSE unread END "
                "WHERE id = ? AND profile_id = ?",
                (now, 1 if assistant_content else 0, chat_id, profile_id),
            )
        return True

    def list_messages(self, profile_id: str, chat_id: str) -> list[dict[str, Any]] | None:
        _require(profile_id)
        with self._lock:
            owned = self._conn.execute(
                "SELECT 1 FROM chats WHERE id = ? AND profile_id = ?", (chat_id, profile_id)
            ).fetchone()
            if not owned:
                return None
            rows = self._conn.execute(
                "SELECT m.id, m.role, m.content, m.created_at, m.attachments, m.tools, "
                "(c.summary_upto IS NOT NULL AND m.id <= c.summary_upto) AS summarized "
                "FROM messages m JOIN chats c ON c.id = m.chat_id AND c.profile_id = m.profile_id "
                "WHERE m.chat_id = ? AND m.profile_id = ? ORDER BY m.id",
                (chat_id, profile_id),
            ).fetchall()
        messages = [
            {**{k: v for k, v in dict(r).items() if k != "tools"}, "summarized": bool(r["summarized"]),
             "attachments": _attachments(r["attachments"]), "tools": _tools(r["tools"])}
            for r in rows
        ]
        self._mark_files(profile_id, messages)
        return messages

    def _mark_files(self, profile_id: str, messages: list[dict[str, Any]]) -> None:
        """Bei Dateikarten vermerken, ob die Datei noch abrufbar ist (``gone``: abgelaufen oder gelöscht)."""
        wanted = {t["file"]["id"] for m in messages for t in m["tools"] if "file" in t}
        if not wanted:
            return
        now = _now()
        marks = ",".join("?" * len(wanted))
        with self._lock:
            alive = {r["id"] for r in self._conn.execute(
                f"SELECT id FROM outfiles WHERE profile_id = ? AND expires_at > ? AND id IN ({marks})", (profile_id, now, *wanted)
            )}
        for m in messages:
            for t in m["tools"]:
                if "file" in t:
                    t["file"]["gone"] = t["file"]["id"] not in alive or not self._outfile_path(t["file"]["id"]).is_file()

    def get_summary(self, profile_id: str, chat_id: str) -> tuple[str | None, int | None]:
        """Zusammenfassung des älteren Verlaufs und die letzte darin enthaltene Nachrichten-ID."""
        _require(profile_id)
        with self._lock:
            row = self._conn.execute(
                "SELECT summary, summary_upto FROM chats WHERE id = ? AND profile_id = ?",
                (chat_id, profile_id),
            ).fetchone()
        if not row or not row["summary"]:
            return None, None
        return row["summary"], row["summary_upto"]

    def set_summary(self, profile_id: str, chat_id: str, summary: str, upto: int) -> bool:
        _require(profile_id)
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE chats SET summary = ?, summary_upto = ? WHERE id = ? AND profile_id = ?",
                (summary, upto, chat_id, profile_id),
            )
        return cur.rowcount == 1
