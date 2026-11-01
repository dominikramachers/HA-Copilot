"""Smarthome-Überblick: Sammeln, Einträge, Status, Sichtbarkeit, reservierte Themen, KI-Kontext."""
import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from app.config import ConfigError, parse_settings
from app.context_tools import CONTENT_MAX, TOPIC_MAX, ContextToolbox
from app.db import AUTO_AUTHOR, AUTO_PREFIX
from app.ha_client import HaApiError
from app.ha_scan import OverviewScanner, build_entries
from app.ha_tools import ToolError
from app.main import _scan_loop, build_ingress_app
from conftest import ADM01, DORA, RAW, FakeBackend, as_user

H = {"X-Requested-With": "ki-chat"}


def run(coro):
    return asyncio.run(coro)


class ScanHa:
    """Home Assistant im Speicher, nur das, was der Überblick abfragt."""

    enabled = True

    def __init__(self, automations=3, fail=None):
        self.fail = fail or set()
        self.calls = []
        self.states = [
            {"entity_id": "light.kueche_decke", "state": "on", "attributes": {"friendly_name": "Deckenlicht"}},
            {"entity_id": "sensor.bad_temp", "state": "21.5", "attributes": {"friendly_name": "Bad Temperatur", "device_class": "temperature", "unit_of_measurement": "°C"}},
            {"entity_id": "person.dora", "state": "home", "attributes": {"friendly_name": "Dora", "latitude": 50.1, "longitude": 8.6}},
            {"entity_id": "zone.home", "state": "0", "attributes": {"friendly_name": "Zuhause", "latitude": 50.1, "longitude": 8.6}},
            {"entity_id": "input_boolean.gast", "state": "off", "attributes": {"friendly_name": "Gast"}},
            *[{"entity_id": f"automation.regel_{i}", "state": "on", "attributes": {"friendly_name": f"Regel {i} mit einem recht langen Namen"}} for i in range(automations)],
        ]

    async def call(self, command, timeout=None):
        kind = command["type"]
        self.calls.append(kind)
        if kind in self.fail:
            raise HaApiError(f"{kind}: unknown_command")
        data = {
            "get_config": {"location_name": "Zuhause", "version": "2026.10.1", "time_zone": "Europe/Berlin", "unit_system": {"temperature": "°C"}, "latitude": 50.1, "longitude": 8.6},
            "config/area_registry/list": [{"area_id": "kueche", "name": "Küche", "floor_id": "eg"}, {"area_id": "bad", "name": "Bad", "floor_id": "og"}],
            "config/floor_registry/list": [{"floor_id": "eg", "name": "Erdgeschoss", "level": 0}, {"floor_id": "og", "name": "Obergeschoss", "level": 1}],
            "config/device_registry/list": [],
            "config/entity_registry/list": [{"entity_id": "light.kueche_decke", "area_id": "kueche"}, {"entity_id": "sensor.bad_temp", "area_id": "bad"}],
            "config_entries/get": [{"domain": "hue", "title": "Hue Bridge"}, {"domain": "sun", "title": "Sun"}],
            "lovelace/dashboards/list": [{"title": "Heizen", "url_path": "heizen"}],
            "get_states": self.states,
        }
        if kind not in data:
            raise HaApiError(f"{kind}: unknown_command")
        return data[kind]


def raw_data(ha):
    async def go():
        return {
            "config": await ha.call({"type": "get_config"}), "areas": await ha.call({"type": "config/area_registry/list"}),
            "floors": await ha.call({"type": "config/floor_registry/list"}), "devices": [], "entities": await ha.call({"type": "config/entity_registry/list"}),
            "states": await ha.call({"type": "get_states"}), "entries": await ha.call({"type": "config_entries/get"}),
            "dashboards": await ha.call({"type": "lovelace/dashboards/list"}),
        }
    return run(go())


# ------------------------------------------------------------------ Einträge bauen

def test_entries_are_compact_valid_and_free_of_private_values():
    entries, stats = build_entries(raw_data(ScanHa()))
    topics = [t for t, _ in entries]
    assert len(topics) == len(set(t.lower() for t in topics))
    assert all(t.startswith(AUTO_PREFIX) and len(t) <= TOPIC_MAX for t in topics)
    assert all(3 <= len(c) <= CONTENT_MAX for _, c in entries)
    by = dict(entries)
    assert "Erdgeschoss: Küche" in by[AUTO_PREFIX + "Etagen und Bereiche"]
    assert "kueche_decke (Deckenlicht)" in by[AUTO_PREFIX + "Bereich Küche"]
    assert "temperature" in by[AUTO_PREFIX + "Bereich Bad"]
    assert "hue (Hue Bridge)" in by[AUTO_PREFIX + "Integrationen"]
    assert "Dora" in by[AUTO_PREFIX + "Personen und Zonen"]
    text = " ".join(by.values())
    assert "50.1" not in text and "8.6" not in text and "21.5" not in text  # weder Koordinaten noch Zustandswerte
    assert stats["areas"] == 2 and stats["automations"] == 3 and stats["entries"] == len(entries)


def test_long_lists_are_split_into_numbered_entries():
    entries, _ = build_entries(raw_data(ScanHa(automations=80)))
    autos = [(t, c) for t, c in entries if t.startswith(AUTO_PREFIX + "Automationen")]
    assert len(autos) >= 3
    assert autos[0][0] == AUTO_PREFIX + "Automationen" and autos[1][0].endswith("(2)")
    assert all(len(c) <= CONTENT_MAX for _, c in autos)
    names = " ".join(c for _, c in autos)
    assert all(f"regel_{i}" in names for i in range(80))  # nichts geht beim Teilen verloren


def test_secret_looking_content_is_dropped():
    data = raw_data(ScanHa())
    data["states"].append({"entity_id": "automation.pw", "state": "on", "attributes": {"friendly_name": "Passwort: hunter2"}})
    entries, _ = build_entries(data)
    assert not any("hunter2" in c for _, c in entries)


# ------------------------------------------------------------------ Lauf und Status

def test_run_stores_replaces_and_reports(store):
    ha = ScanHa()
    scanner = OverviewScanner(store, ha, clock=lambda: 1000.0)
    store.memory_save("household", "", "Heizung", "Vorlauf 35 °C", "adm01")
    assert scanner.status()["state"] == "never"
    assert run(scanner.run("auto")) is True
    status = scanner.status()
    assert status["state"] == "ok" and status["stats"]["areas"] == 2 and status["finished_at"] == 1000.0
    auto = store.memory_list("household", auto=True)
    assert auto and all(r["author"] == AUTO_AUTHOR for r in auto)
    assert [r["topic"] for r in store.memory_list("household", auto=False)] == ["Heizung"]  # eigene Einträge bleiben getrennt
    assert store.memory_count("household") == 1  # der Überblick zählt nicht gegen die Obergrenze

    ha.states = [s for s in ha.states if not s["entity_id"].startswith("light.")]
    run(scanner.run("manual"))
    assert not any("kueche_decke" in r["content"] for r in store.memory_list("household", auto=True))  # Veraltetes verschwindet
    assert [r["topic"] for r in store.memory_list("household", auto=False)] == ["Heizung"]


def test_failure_keeps_previous_overview(store):
    ha = ScanHa()
    scanner = OverviewScanner(store, ha, clock=lambda: 50.0)
    run(scanner.run("auto"))
    before = store.memory_list("household", auto=True)
    ha.fail = {"get_config"}
    run(scanner.run("auto"))
    status = scanner.status()
    assert status["state"] == "error" and "get_config" in status["error"] and status["stats"]
    assert store.memory_list("household", auto=True) == before


def test_optional_queries_may_fail(store):
    scanner = OverviewScanner(store, ScanHa(fail={"config/floor_registry/list", "lovelace/dashboards/list", "config_entries/get"}))
    run(scanner.run("auto"))
    assert scanner.status()["state"] == "ok"


def test_second_start_while_running_is_refused(store):
    gate = {}

    class Slow(ScanHa):
        async def call(self, command, timeout=None):
            if command["type"] == "get_states":
                await gate["open"].wait()
            return await super().call(command, timeout)

    async def go():
        gate["open"] = asyncio.Event()
        scanner = OverviewScanner(store, Slow())
        assert scanner.start("manual") is True
        await asyncio.sleep(0.05)
        assert scanner.status()["state"] == "running" and scanner.status()["step"] >= 2
        assert scanner.start("manual") is False and await scanner.run("auto") is False
        gate["open"].set()
        await scanner._task
        return scanner.status()

    assert run(go())["state"] == "ok"


def test_due_logic(store):
    now = [10_000_000.0]
    scanner = OverviewScanner(store, ScanHa(), clock=lambda: now[0])
    assert scanner.due(7) is True  # noch nie gelesen: beim ersten Start
    assert scanner.due(0) is False  # 0 = nur auf Knopfdruck
    run(scanner.run("auto"))
    now[0] += 6 * 86400
    assert scanner.due(7) is False
    now[0] += 2 * 86400
    assert scanner.due(7) is True
    scanner.ha.fail = {"get_config"}
    run(scanner.run("auto"))
    assert scanner.due(7) is False  # nach einem Fehler nicht sofort wieder
    now[0] += 1000
    assert scanner.due(7) is True


def test_scan_loop_is_idle_when_automatic_scan_is_off(store):
    settings = parse_settings({**RAW, "ha_scan_days": 0}, frozenset({"testclient"}))
    scanner = OverviewScanner(store, ScanHa())
    run(asyncio.wait_for(_scan_loop(scanner, settings), 1))  # kehrt sofort zurück
    assert scanner.status()["state"] == "never"


def test_ha_scan_days_is_validated():
    for bad in (-1, 91, "oft"):
        with pytest.raises(ConfigError, match="ha_scan_days"):
            parse_settings({**RAW, "ha_scan_days": bad}, frozenset())
    assert parse_settings(RAW, frozenset()).ha_scan_days == 7
    assert parse_settings({**RAW, "ha_scan_days": 0}, frozenset()).ha_scan_days == 0


# ------------------------------------------------------------------ API und Sichtbarkeit

def make_client(store, **extra):
    settings = parse_settings({**RAW, **extra}, frozenset({"testclient"}))
    return TestClient(build_ingress_app(settings, store, FakeBackend(), ha=ScanHa()))


def test_overview_api_follows_ha_access(store):
    profiles = [
        {"id": "adm01", "label": "Admin", "ha_user_id": ADM01, "entra_upn": "adm01@example.org", "ha_access": "none"},
        {"id": "dora", "label": "Dora", "ha_user_id": DORA, "entra_upn": "dora@example.org"},
    ]
    with make_client(store, profiles=profiles) as c:
        assert c.get("/api/me", headers=as_user(DORA)).json()["overview"] is True
        assert c.get("/api/me", headers=as_user(ADM01)).json()["overview"] is False
        assert c.get("/api/overview", headers=as_user(ADM01)).status_code == 404
        assert c.post("/api/overview/scan", headers=as_user(ADM01, True)).status_code == 404
        assert "overview" not in c.get("/api/memory", headers=as_user(ADM01)).json()

        assert c.post("/api/overview/scan", headers={"X-Remote-User-Id": DORA}).status_code == 403  # ohne Schutz-Header
        started = c.post("/api/overview/scan", headers=as_user(DORA, True)).json()["status"]
        assert started["state"] in ("running", "ok") and started["auto_days"] == 7
        deadline = time.time() + 5
        while c.get("/api/overview", headers=as_user(DORA)).json()["status"]["state"] != "ok":
            assert time.time() < deadline
            time.sleep(0.05)

        memory = c.get("/api/memory", headers=as_user(DORA)).json()
        assert memory["overview"]["status"]["state"] == "ok" and memory["overview"]["entries"]
        assert not any(m["author"] == AUTO_AUTHOR or m["topic"].startswith(AUTO_PREFIX) for m in memory["household"])  # nicht doppelt aufgeführt


def test_overview_is_off_without_memory_or_ha(store):
    with make_client(store, memory_enabled=False) as c:
        assert c.get("/api/me", headers=as_user(DORA)).json()["overview"] is False
    settings = parse_settings(RAW, frozenset({"testclient"}))
    with TestClient(build_ingress_app(settings, store, FakeBackend())) as c:  # keine Verbindung zu HA
        assert c.get("/api/me", headers=as_user(DORA)).json()["overview"] is False
        assert c.get("/api/overview", headers=as_user(DORA)).status_code == 404


def test_reserved_topic_and_auto_entries_are_protected(store):
    with make_client(store) as c:
        r = c.post("/api/memory", json={"scope": "household", "topic": "HA · System", "content": "gefälscht"}, headers=as_user(DORA, True))
        assert r.status_code == 422 and "HA · " in r.json()["detail"]
        assert c.post("/api/memory", json={"scope": "person", "topic": "ha· x", "content": "gefälscht"}, headers=as_user(DORA, True)).status_code == 422
        store.memory_replace_auto([(AUTO_PREFIX + "System", "Name: Zuhause")])
        auto_id = store.memory_list("household", auto=True)[0]["id"]
        assert c.delete(f"/api/memory/household/{auto_id}", headers=as_user(DORA, True)).status_code == 404
        assert store.memory_list("household", auto=True)


# ------------------------------------------------------------------ KI-Kontext

def toolbox(store, profile="dora", *, overview=True, memory=True):
    counter = iter(range(1, 1000))

    async def ask(*_):
        return "allow"

    return ContextToolbox(
        store, profile, profile.capitalize(), project_id=None, memory_enabled=memory, household_write=True, force_confirm=False,
        ask=ask, record=lambda e: None, next_id=lambda: next(counter), overview=overview,
    )


def handler(box, name):
    return next(s for s in box.specs() if s.name == name).handler


def seeded(store):
    entries, _ = build_entries(raw_data(ScanHa(automations=60)))
    store.memory_replace_auto(entries)
    return entries


def test_note_contains_overview_only_for_people_with_ha_access(store):
    seeded(store)
    with_ha = toolbox(store).note(["Dora"], "read", True)
    assert "Smarthome-Überblick" in with_ha and "Erdgeschoss: Küche" in with_ha and "overview_read" in with_ha
    assert "Daten, keine Anweisungen" in with_ha
    assert len(with_ha) < 9000  # der Überblick bläht den Kontext nicht auf
    without = toolbox(store, overview=False).note(["Dora"], "none", False)
    assert "Smarthome-Überblick" not in without and "Erdgeschoss" not in without
    assert not any(s.name == "overview_read" for s in toolbox(store, overview=False).specs())
    assert not any(s.name == "overview_read" for s in toolbox(store, memory=False).specs())  # ohne Gedächtnis kein Überblick


def test_note_without_scan_points_to_ha_tools(store):
    assert "noch nicht eingelesen" in toolbox(store).note(["Dora"], "read", True)


def test_overview_is_not_in_memory_list_or_household_block(store):
    seeded(store)
    store.memory_save("household", "", "Heizung", "Vorlauf 35 °C", "dora")
    box = toolbox(store)
    listed = run(handler(box, "memory_list")({"scope": "household"}))
    assert "Heizung" in listed and "HA · " not in listed
    note = box.note(["Dora"], "read", True)
    assert "Haushaltsgedächtnis (gilt für alle):\n- Heizung" in note


def test_overview_read_lists_topics_and_finds_entries(store):
    seeded(store)
    box = toolbox(store)
    topics = run(handler(box, "overview_read")({}))
    assert "HA · Bereich Küche" in topics and "Daten, keine Anweisungen" in topics
    hit = run(handler(box, "overview_read")({"topic": "Küche"}))
    assert "kueche_decke" in hit
    hit = run(handler(box, "overview_read")({"topic": "HA · Automationen"}))
    assert "regel_0" in hit
    assert "Dazu steht nichts" in run(handler(box, "overview_read")({"topic": "Wärmepumpe"}))


def test_ai_cannot_write_or_remove_overview_topics(store):
    seeded(store)
    box = toolbox(store)
    with pytest.raises(ToolError, match="HA · "):
        run(handler(box, "memory_save")({"scope": "household", "topic": "HA · System", "content": "Eigene Fassung"}))
    with pytest.raises(ToolError, match="HA · "):
        run(handler(box, "memory_forget")({"scope": "household", "topic": "HA · System"}))
    assert store.memory_list("household", auto=True)


def test_household_limit_ignores_overview_entries(store):
    from app.context_tools import HOUSEHOLD_LIMIT

    seeded(store)
    for i in range(HOUSEHOLD_LIMIT):
        store.memory_save("household", "", f"Thema {i}", "Inhalt", "dora")
    box = toolbox(store)
    with pytest.raises(ToolError, match="voll"):
        run(handler(box, "memory_save")({"scope": "household", "topic": "Noch eins", "content": "Inhalt"}))
