"""Datensicherheit: Schnappschüsse, Prüfung beim Start, Wiederherstellung, Ablauf-Hinweise."""
import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest

from app import safety
from app.config import ConfigError, parse_settings
from app.db import SCHEMA_VERSION, Store
from app.ops import Health
from tests.conftest import RAW


def filled_store(path):
    store = Store(path)
    store.sync_profiles(["dora"])
    chat = store.create_chat("dora", "Wichtig")
    store.add_exchange("dora", chat["id"], "Frage", "Antwort")
    return store, chat


def test_snapshot_is_consistent_and_pruned(tmp_path):
    store, chat = filled_store(tmp_path / "db.sqlite3")
    snaps = tmp_path / "snapshots"
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for day in range(10):
        safety.snapshot_live(store._conn, snaps, now=start + timedelta(days=day))
    names = [p.name for p in safety.list_snapshots(snaps)]
    assert len(names) == safety.KEEP_DAILY
    assert names[0].startswith("ki_chat-2026-01-10")  # die neuesten bleiben
    copy = sqlite3.connect(snaps / names[0])
    assert copy.execute("SELECT title FROM chats").fetchone()[0] == "Wichtig"
    copy.close()
    store.close()


def test_new_database_gets_schema_version(tmp_path):
    store = Store(tmp_path / "db.sqlite3")
    assert store._conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    store.close()


def test_snapshot_before_update_of_old_database(tmp_path):
    path = tmp_path / "db.sqlite3"
    store, _ = filled_store(path)
    store._conn.execute("PRAGMA user_version = 0")  # Stand einer älteren Version
    store.close()
    report = safety.prepare(path, tmp_path / "snapshots")
    assert report.problem is None
    assert any(p.name.startswith(safety.BEFORE_UPDATE) for p in safety.list_snapshots(tmp_path / "snapshots"))
    # Eine aktuelle Datenbank braucht keinen Update-Schnappschuss.
    Store(path).close()
    again = tmp_path / "snap2"
    safety.prepare(path, again)
    assert not any(p.name.startswith(safety.BEFORE_UPDATE) for p in safety.list_snapshots(again))


def test_corrupt_database_is_reported_not_touched(tmp_path):
    path = tmp_path / "db.sqlite3"
    store, _ = filled_store(path)
    store.close()
    data = bytearray(path.read_bytes())
    for i in range(2 * 4096, 3 * 4096):
        data[i] = 0xFF  # eine ganze Datenseite (Seite 3) beschädigen
    path.write_bytes(bytes(data))
    before = path.read_bytes()
    report = safety.prepare(path, tmp_path / "snapshots")
    assert report.problem and "restore_snapshot" in report.problem
    assert path.read_bytes() == before


def test_restore_from_snapshot_once(tmp_path):
    path = tmp_path / "db.sqlite3"
    snaps = tmp_path / "snapshots"
    store, chat = filled_store(path)
    snap = store.snapshot(snaps)
    store.rename_chat("dora", chat["id"], "Verändert")
    store.close()

    report = safety.prepare(path, snaps, snap.name)
    assert "wiederhergestellt" in (report.problem or "")
    restored = Store(path)
    assert restored.get_chat("dora", chat["id"])["title"] == "Wichtig"
    assert any(p.name.startswith(safety.BEFORE_RESTORE) for p in safety.list_snapshots(snaps))
    restored.rename_chat("dora", chat["id"], "Neu danach")
    restored.close()

    # Bleibt die Option stehen, wird beim nächsten Start nicht erneut überschrieben.
    safety.prepare(path, snaps, snap.name)
    again = Store(path)
    assert again.get_chat("dora", chat["id"])["title"] == "Neu danach"
    again.close()


@pytest.mark.parametrize("name", ["../etc/passwd.sqlite3", "fehlt.sqlite3"])
def test_restore_rejects_bad_names(tmp_path, name):
    path = tmp_path / "db.sqlite3"
    store, chat = filled_store(path)
    store.close()
    report = safety.prepare(path, tmp_path / "snapshots", name)
    assert "fehlgeschlagen" in (report.problem or "")
    assert Store(path).get_chat("dora", chat["id"])["title"] == "Wichtig"


def test_restore_option_is_validated():
    with pytest.raises(ConfigError):
        parse_settings({**RAW, "restore_snapshot": "../x.sqlite3"})
    assert parse_settings({**RAW, "restore_snapshot": "ki_chat-2026-10-27_030000.sqlite3"}).restore_snapshot


def test_expiry_notices():
    settings = parse_settings({**RAW, "public_enabled": False, "claude_token_expires": "2026-11-10"})
    health = Health(settings)
    assert health.notices(date(2026, 10, 1)) == []  # noch weit weg
    warn = health.notices(date(2026, 10, 27))[0]
    assert warn["level"] == "warn" and "14 Tagen" in warn["text"] and "10.11.2026" in warn["text"]
    gone = health.notices(date(2026, 11, 12))[0]
    assert gone["level"] == "error" and "abgelaufen" in gone["text"]
    assert warn["id"] == gone["id"]  # gleiche Meldung lässt sich einmal wegklicken


def test_entra_notice_only_when_domain_is_on():
    raw = {**RAW, "entra_secret_expires": "2026-11-01"}
    assert Health(parse_settings(raw)).notices(date(2026, 10, 27)) == []
    on = {
        **raw, "public_enabled": True, "public_base_url": "https://chat.example.org",
        "entra_tenant_id": "11111111-2222-3333-4444-555555555555",
        "entra_client_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "entra_client_secret": "x",
    }
    assert "Entra" in Health(parse_settings(on)).notices(date(2026, 10, 27))[0]["text"]


def test_bad_date_is_rejected():
    with pytest.raises(ConfigError):
        parse_settings({**RAW, "claude_token_expires": "nächstes Jahr"})


def test_db_problem_becomes_notice():
    notice = Health(parse_settings(RAW), "kaputt").notices()[0]
    assert notice["level"] == "error" and notice["text"] == "kaputt"


def test_export_and_import_move_the_database_to_another_addon(tmp_path):
    # altes Add-on: Export in den Config-Ordner
    old_db = tmp_path / "alt" / "db.sqlite3"
    old_db.parent.mkdir()
    old_cfg = tmp_path / "alt-config"
    old_cfg.mkdir()
    store, chat = filled_store(old_db)
    exported = safety.export_database(old_db, old_cfg)
    store.close()
    assert exported.name == safety.EXPORT_NAME and safety.quick_check(exported) == "ok"
    # Datei wird (per Samba) in den Config-Ordner des neuen Add-ons kopiert
    new_cfg = tmp_path / "neu-config"
    new_cfg.mkdir()
    (new_cfg / exported.name).write_bytes(exported.read_bytes())
    # neues Add-on: leere Datenbank, restore_snapshot nennt die Datei; gefunden im Config-Ordner
    new_db = tmp_path / "neu" / "db.sqlite3"
    new_db.parent.mkdir()
    report = safety.prepare(new_db, new_db.parent / "snapshots", safety.EXPORT_NAME, new_cfg)
    assert "wiederhergestellt" in (report.problem or "")
    moved = Store(new_db)
    assert moved.get_chat("dora", chat["id"])["title"] == "Wichtig"
    moved.close()


def test_import_prefers_own_snapshots_and_still_validates_names(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    snaps = tmp_path / "snapshots"
    report = safety.prepare(tmp_path / "db.sqlite3", snaps, "fehlt.sqlite3", cfg)
    assert "fehlgeschlagen" in (report.problem or "")
    report = safety.prepare(tmp_path / "db.sqlite3", snaps, "../x.sqlite3", cfg)
    assert "fehlgeschlagen" in (report.problem or "")
