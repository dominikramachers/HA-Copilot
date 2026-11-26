"""Updatepläne: ein Zeitplan mit Zeitfenster für mehrere Server (Hub). Regeln und Läufe der Pakete stehen in test_server_autoupdate.py."""
import asyncio
import json
from datetime import datetime

import pytest

from app import server_autoupdate as au
from app import server_updateplans as up
from app import servers as serverlib

from test_server_autoupdate import pkg
from test_servers import make_hub

NOW = datetime(2026, 11, 26, 12, 0)  # Donnerstag


class Agents:
    """Ersetzt die Verbindungen zu mehreren Agenten. ``gate`` hält einen Lauf an, bis das Ereignis gesetzt wird (um „nacheinander“ zu prüfen)."""

    def __init__(self, hub, updates):
        self.hub, self.updates, self.started, self.gate = hub, list(updates), [], None
        hub._connection = lambda ref: (hub.get(ref), None)
        hub.status_of = lambda r: ("online", [])
        hub.prepare = self.prepare
        hub.execute = self.execute
        hub.call = self.call

    async def prepare(self, ref, tool, args=None):
        return {"id": "a1b2c3d4e5f60718293a4b5c", "hash": "e3" * 32, "tool": tool, "class": 1, "command": "apt-get install --only-upgrade", "preview": "", "reason": "r",
                "summary": "s", "timeout_s": 60, "runner": "root", "undo": "", "msgs": {}, "action": (args or {}).get("action")}

    async def execute(self, ref, plan):
        if plan["action"] == "upgrade":
            self.started.append(self.hub.get(ref)["name"])
            if self.gate is not None:
                await self.gate.wait()
        return "== Result: ok"

    async def call(self, ref, tool, args=None, **kw):
        if tool == "update_candidates":
            done = self.hub.get(ref)["name"] in self.started
            return json.dumps({"manager": "apt", "updates": [] if done else self.updates, "free_mb": 50000, "reboot_required": False})
        if tool == "services_failed":
            return "No failed services.\n"
        raise AssertionError(tool)


def make(tmp_path, count=3, updates=None, **info):
    hub = make_hub(tmp_path)
    for i in range(1, count + 1):
        hub.repo.server_create(f"srv{i}", f"web0{i}", f"{i:02d}" * 32, f"key{i}")
        hub.repo.server_state(f"srv{i}", "active")
        hub.repo.server_seen(f"srv{i}", f"10.0.0.{i}", {"os": "Debian 12", "operate": True, "agent_version": "0.68.0", **info})
    hub.autoupdate.settle = 0
    hub.autoupdate.clock = lambda: NOW
    agents = Agents(hub, updates if updates is not None else [pkg("libc6")])
    results = []

    async def on_result(row, run):
        results.append((row["name"], run))
    hub.autoupdate.on_result = on_result
    return hub, hub.autoupdate, agents, results


PLAN = {"name": "Nacht", "mode": "security", "weekday": 7, "window_start": "02:00", "window_end": "03:00", "grace_days": 0}


# ------------------------------------------------------------------------------------------------ Zeitrechnung


def test_offsets_spread_servers_evenly_and_skip_paused_ones():
    plan = {"window_start": "02:00", "window_end": "03:00"}
    members = [{"server_id": s, "paused": False} for s in ("a", "b", "c")]
    assert up.offsets(plan, members) == {"a": 0, "b": 20, "c": 40}
    members[1]["paused"] = True
    assert up.offsets(plan, members) == {"a": 0, "c": 30}
    assert up.offsets(plan, [{"server_id": "x", "paused": False}]) == {"x": 0}
    ten = [{"server_id": str(i), "paused": False} for i in range(10)]
    assert up.offsets(plan, ten)["1"] == 6 and up.offsets(plan, ten)["9"] == 54  # alle 6 Minuten einer


def test_window_may_cross_midnight_and_offsets_cross_with_it():
    assert up.window_length("23:00", "01:00") == 120 and up.window_length("02:00", "03:00") == 60
    now = datetime(2026, 11, 27, 0, 30)  # Freitag, kurz nach Mitternacht
    assert up.next_slot(now, 7, "23:00", 90) == datetime(2026, 11, 28, 0, 30)  # 00:30 ist jetzt (nicht mehr in der Zukunft), also der nächste
    assert up.next_slot(datetime(2026, 11, 27, 0, 10), 7, "23:00", 90) == datetime(2026, 11, 27, 0, 30)  # das Fenster von gestern Abend ist noch nicht durch
    assert up.last_slot(now, 7, "23:00", 90) == datetime(2026, 11, 27, 0, 30)
    assert up.last_slot(now, 7, "23:00", 0) == datetime(2026, 11, 26, 23, 0)
    # Wochentag gilt für den Beginn des Fensters: Donnerstag 23:00 + 90 Minuten = Freitag 00:30
    assert up.last_slot(datetime(2026, 11, 27, 5, 0), 3, "23:00", 90) == datetime(2026, 11, 27, 0, 30)
    assert up.next_slot(datetime(2026, 11, 27, 5, 0), 3, "23:00", 90) == datetime(2026, 12, 4, 0, 30)


def test_window_length_is_validated(tmp_path):
    hub, auto, agents, results = make(tmp_path)
    with pytest.raises(serverlib.ServerError):
        auto.plans.create({**PLAN, "window_end": "02:05"}, "x")  # zu kurz
    with pytest.raises(serverlib.ServerError):
        auto.plans.create({**PLAN, "window_end": "02:00"}, "x")  # Länge 0
    with pytest.raises(serverlib.ServerError):
        auto.plans.create({**PLAN, "window_start": "02:00", "window_end": "16:00"}, "x")  # länger als 12 Stunden
    for bad in ({"mode": "alles"}, {"weekday": 9}, {"window_start": "25:00"}, {"grace_days": 99}, {"name": "  "}, {"enabled": "ja"}):
        with pytest.raises(serverlib.ServerError):
            auto.plans.create({**PLAN, **bad}, "x")
    assert auto.plans.all() == []


# ------------------------------------------------------------------------------------------------ Zuweisung


def test_server_in_a_plan_follows_the_plan_and_keeps_its_own_settings(tmp_path):
    hub, auto, agents, results = make(tmp_path)
    auto.save_settings("srv1", {"enabled": True, "mode": "all", "weekday": 2, "at_time": "04:15", "grace_days": 5}, "x")
    plan = auto.plans.create({**PLAN, "enabled": True, "servers": ["srv1", "srv2"]}, "Dominik")
    assert [m["id"] for m in plan["members"]] == ["srv1", "srv2"] and [m["slot"] for m in plan["members"]] == ["02:00", "02:30"]
    eff = auto.effective("srv1")
    assert eff["source"] == "plan" and eff["mode"] == "security" and eff["weekday"] == 7 and eff["at_time"] == "02:00" and eff["grace_days"] == 0 and eff["enabled"] is True
    own = auto.repo.settings("srv1")  # der eigene Zeitplan ist unverändert gespeichert
    assert own["enabled"] and own["mode"] == "all" and own["weekday"] == 2 and own["at_time"] == "04:15" and own["grace_days"] == 5
    view = auto.view("srv1")
    assert view["plan"]["name"] == "Nacht" and view["plan"]["slot"] == "02:00" and view["settings"]["at_time"] == "04:15" and view["next_run"] == "2026-11-27T02:00"
    assert auto.view("srv2")["next_run"] == "2026-11-27T02:30"
    brief = auto.brief("srv2")
    assert brief["plan"] == {"id": plan["id"], "name": "Nacht", "paused": False, "enabled": True, "slot": "02:30"} and brief["enabled"] is True
    with pytest.raises(serverlib.ServerError) as err:  # eigene Einstellungen ändern geht erst nach dem Herausnehmen
        auto.save_settings("srv1", {"at_time": "05:00"}, "x")
    assert err.value.status == 409 and "Nacht" in str(err.value)


def test_a_server_belongs_to_one_plan_and_moves_when_added_elsewhere(tmp_path):
    hub, auto, agents, results = make(tmp_path)
    first = auto.plans.create({**PLAN, "servers": ["srv1", "srv2"]}, "x")
    second = auto.plans.create({**PLAN, "name": "Wochenende", "servers": ["srv2", "srv3"]}, "x")
    assert [m["id"] for m in auto.plans.view(auto.plans.get(first["id"]))["members"]] == ["srv1"]
    assert [m["id"] for m in second["members"]] == ["srv2", "srv3"]
    assert auto.plans.membership("srv2")["plan"]["id"] == second["id"]


def test_joining_needs_the_same_permissions_as_enabling(tmp_path):
    hub, auto, agents, results = make(tmp_path)
    plan = auto.plans.create({**PLAN}, "x")
    hub.repo.server_seen("srv1", "10.0.0.1", {"os": "Debian 12", "operate": True, "agent_version": "0.68.0", "auto_update_denied": True})
    with pytest.raises(serverlib.ServerError) as denied:
        auto.plans.join("srv1", plan["id"], "x")
    assert denied.value.status == 403 and "auto_update=deny" in str(denied.value)
    hub.repo.server_seen("srv2", "10.0.0.2", {"os": "Debian 12", "operate": False, "agent_version": "0.68.0"})
    with pytest.raises(serverlib.ServerError):
        auto.plans.join("srv2", plan["id"], "x")
    hub.repo.server_seen("srv3", "10.0.0.3", {"os": "Debian 12", "operate": True, "agent_version": "0.67.1"})
    with pytest.raises(serverlib.ServerError) as old:
        auto.plans.join("srv3", plan["id"], "x")
    assert "zu alt" in str(old.value)
    with pytest.raises(serverlib.ServerError):
        auto.plans.create({**PLAN, "servers": ["srv1"]}, "x")  # auch beim Anlegen
    assert len(auto.plans.all()) == 1 and auto.plans.members(plan["id"]) == []


def test_leave_pause_and_delete(tmp_path):
    hub, auto, agents, results = make(tmp_path)
    auto.save_settings("srv1", {"enabled": True, "weekday": 2, "at_time": "04:15"}, "x")
    plan = auto.plans.create({**PLAN, "enabled": True, "servers": ["srv1", "srv2", "srv3"]}, "x")
    assert [m["slot"] for m in plan["members"]] == ["02:00", "02:20", "02:40"]
    auto.plans.pause("srv2", True, "x")
    assert [m["slot"] for m in auto.plans.view(auto.plans.get(plan["id"]))["members"]] == ["02:00", "", "02:30"]  # pausierte zählen nicht mit
    assert auto.effective("srv2")["enabled"] is False and auto.brief("srv2")["plan"]["paused"] is True
    auto.plans.pause("srv2", False, "x")
    # herausnehmen, eigener Zeitplan bleibt wie er war (srv1 hatte ihn eingeschaltet)
    view = auto.plans.leave("srv1", False, "x")
    assert view["plan"] is None and view["effective"]["source"] == "own" and view["effective"]["enabled"] is True and view["next_run"] == "2026-12-02T04:15"
    assert auto.repo.settings("srv1")["last_slot"] == "2026-11-25T04:15"  # nichts nachholen (der letzte Mittwoch ist schon vorbei)
    # herausnehmen und den eigenen Zeitplan einschalten
    assert auto.repo.settings("srv2")["enabled"] is False
    view = auto.plans.leave("srv2", True, "x")
    assert view["effective"]["source"] == "own" and view["effective"]["enabled"] is True
    with pytest.raises(serverlib.ServerError):
        auto.plans.leave("srv2", False, "x")  # gehört zu keinem Plan mehr
    auto.plans.delete(plan["id"], "x")
    assert auto.plans.all() == [] and auto.plans.membership("srv3") is None and auto.effective("srv3")["source"] == "own"
    with pytest.raises(serverlib.ServerError):
        auto.plans.delete(plan["id"], "x")


def test_removing_a_server_redistributes_the_rest(tmp_path):
    hub, auto, agents, results = make(tmp_path)
    plan = auto.plans.create({**PLAN, "enabled": True, "servers": ["srv1", "srv2", "srv3"]}, "x")
    hub.remove("srv2", "x")
    assert [(m["id"], m["slot"]) for m in auto.plans.view(auto.plans.get(plan["id"]))["members"]] == [("srv1", "02:00"), ("srv3", "02:30")]


def test_reordering_servers_changes_their_times(tmp_path):
    hub, auto, agents, results = make(tmp_path)
    plan = auto.plans.create({**PLAN, "enabled": True, "servers": ["srv1", "srv2", "srv3"]}, "x")
    moved = auto.plans.update(plan["id"], {"servers": ["srv3", "srv1", "srv2"]}, "x")
    assert [(m["id"], m["slot"]) for m in moved["members"]] == [("srv3", "02:00"), ("srv1", "02:20"), ("srv2", "02:40")]
    shrunk = auto.plans.update(plan["id"], {"servers": ["srv3"]}, "x")
    assert [m["id"] for m in shrunk["members"]] == ["srv3"] and auto.plans.membership("srv1") is None


# ------------------------------------------------------------------------------------------------ Läufe


def test_tick_runs_plan_servers_one_after_another_inside_the_window(tmp_path):
    async def scenario():
        hub, auto, agents, results = make(tmp_path)
        plan = auto.plans.create({**PLAN, "enabled": True, "servers": ["srv1", "srv2", "srv3"]}, "x")
        agents.gate = asyncio.Event()
        auto.clock = lambda: datetime(2026, 11, 27, 1, 59)
        await auto.tick()
        await asyncio.gather(*auto._tasks)
        assert agents.started == []  # vor dem Fenster wird nichts installiert
        auto.clock = lambda: datetime(2026, 11, 27, 2, 0)
        await auto.tick()
        await asyncio.sleep(0.05)
        assert agents.started == ["web01"]  # nur der erste
        auto.clock = lambda: datetime(2026, 11, 27, 2, 21)  # der zweite wäre dran, aber web01 läuft noch
        await auto.tick()
        await asyncio.sleep(0.05)
        assert agents.started == ["web01"] and auto.repo.settings("srv2")["last_slot"] != "2026-11-27T02:20"  # wartet, wird nicht verbraucht
        agents.gate.set()
        await asyncio.gather(*auto._tasks)
        assert auto.repo.runs("srv1")[0]["status"] == "ok"
        auto.clock = lambda: datetime(2026, 11, 27, 2, 22)
        await auto.tick()  # jetzt ist web02 dran, obwohl seine Zeit schon 2 Minuten her ist (noch im Fenster)
        await asyncio.gather(*auto._tasks)
        assert agents.started == ["web01", "web02"]
        auto.clock = lambda: datetime(2026, 11, 27, 2, 41)
        await auto.tick()
        await asyncio.gather(*auto._tasks)
        assert agents.started == ["web01", "web02", "web03"]
        await auto.tick()
        assert len(auto.repo.runs("srv1")) == 1 and len(auto.repo.runs("srv3")) == 1  # nicht zweimal
    asyncio.run(scenario())


def test_servers_that_miss_the_window_are_skipped_and_reported(tmp_path):
    async def scenario():
        hub, auto, agents, results = make(tmp_path)
        auto.plans.create({**PLAN, "enabled": True, "servers": ["srv1", "srv2"]}, "x")
        agents.gate = asyncio.Event()
        auto.clock = lambda: datetime(2026, 11, 27, 2, 0)
        await auto.tick()
        await asyncio.sleep(0.05)
        auto.clock = lambda: datetime(2026, 11, 27, 3, 5)  # web01 hängt noch, das Fenster ist vorbei, web02 kam nicht dran
        await auto.tick()
        run = auto.repo.runs("srv2")[0]
        assert run["status"] == "skipped" and "Nacht" in run["summary"] and agents.started == ["web01"]
        assert results and results[-1][0] == "web02"
        agents.gate.set()
        await asyncio.gather(*auto._tasks)
        auto.clock = lambda: datetime(2026, 11, 27, 3, 10)
        await auto.tick()
        assert agents.started == ["web01"]  # nicht außerhalb des Fensters nachholen
    asyncio.run(scenario())


def test_offline_server_in_a_plan_is_not_run_but_waits_for_its_window(tmp_path):
    async def scenario():
        hub, auto, agents, results = make(tmp_path, count=2)
        auto.plans.create({**PLAN, "enabled": True, "servers": ["srv1", "srv2"]}, "x")
        hub.status_of = lambda r: ("offline" if r["id"] == "srv1" else "online", [])
        auto.clock = lambda: datetime(2026, 11, 27, 2, 31)
        await auto.tick()
        await asyncio.gather(*auto._tasks)
        assert agents.started == ["web02"] and auto.repo.runs("srv1") == []
        hub.status_of = lambda r: ("online", [])
        auto.clock = lambda: datetime(2026, 11, 27, 2, 45)  # zurück im Fenster: wird nachgeholt
        await auto.tick()
        await asyncio.gather(*auto._tasks)
        assert agents.started == ["web02", "web01"]
    asyncio.run(scenario())


def test_skipping_the_next_run_of_a_plan_and_of_one_server(tmp_path):
    async def scenario():
        hub, auto, agents, results = make(tmp_path)
        plan = auto.plans.create({**PLAN, "enabled": True, "servers": ["srv1", "srv2"]}, "x")
        view = auto.plans.set_skip(plan["id"], True, "Dominik")
        assert view["skip_next"] is True and auto.view("srv1")["skip_next"] is True and auto.brief("srv2")["skip_next"] is True
        auto.clock = lambda: datetime(2026, 11, 27, 2, 40)
        await auto.tick()
        await asyncio.gather(*auto._tasks)
        assert agents.started == [] and auto.repo.settings("srv1")["last_slot"] == "2026-11-27T02:00"
        auto.clock = lambda: datetime(2026, 11, 28, 2, 31)  # am nächsten Tag läuft es wieder
        await auto.tick()
        await asyncio.gather(*auto._tasks)
        await auto.tick()  # web02 wartet, bis web01 fertig ist
        await asyncio.gather(*auto._tasks)
        assert agents.started == ["web01", "web02"]
        # nur ein Server: überspringen
        auto.set_skip("srv2", True, "x")
        assert auto.view("srv2")["skip_next"] is True and auto.view("srv1")["skip_next"] is False
        assert auto.plans.set_skip(plan["id"], False, "x")["skip_next"] is False
    asyncio.run(scenario())


def test_disabled_plan_and_paused_servers_never_run(tmp_path):
    async def scenario():
        hub, auto, agents, results = make(tmp_path)
        plan = auto.plans.create({**PLAN, "servers": ["srv1", "srv2"]}, "x")  # ausgeschaltet
        auto.clock = lambda: datetime(2026, 11, 27, 2, 40)
        await auto.tick()
        assert agents.started == [] and auto.plans.scheduled_ids() == []
        auto.plans.update(plan["id"], {"enabled": True}, "x")
        auto.plans.pause("srv1", True, "x")
        assert auto.plans.scheduled_ids() == ["srv2"]
        with pytest.raises(serverlib.ServerError):
            auto.plans.set_skip("nope", True, "x")
        auto.plans.update(plan["id"], {"enabled": False}, "x")
        with pytest.raises(serverlib.ServerError):
            auto.plans.set_skip(plan["id"], True, "x")  # nur bei eingeschaltetem Plan
    asyncio.run(scenario())


def test_plan_uses_its_scope_and_grace_period_for_the_preview(tmp_path):
    hub, auto, agents, results = make(tmp_path)
    auto.repo.save("srv1", {"preview": json.dumps({"manager": "apt", "updates": [pkg("vim", security=False, archive="bookworm-updates"), pkg("libc6")]}), "preview_at": serverlib._now()}, "x")
    assert sorted(i["status"] for i in auto.evaluated("srv1")["items"]) == ["include", "scope"]  # eigener Zeitplan: nur Sicherheit
    auto.plans.create({**PLAN, "mode": "all", "servers": ["srv1"]}, "x")
    assert sorted(i["status"] for i in auto.evaluated("srv1")["items"]) == ["include", "include"]  # der Plan sagt: alle Updates
