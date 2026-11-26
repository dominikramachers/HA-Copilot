"""Automatische Aktualisierung der Server: Regeln, Ausnahmen, Zeitplan und Ablauf (Hub). Der Agent ist in Go getestet."""
import asyncio
import json
from datetime import datetime, timedelta

import pytest

from app import server_autoupdate as au
from app import servers as serverlib

from test_servers import make_hub

NOW = datetime(2026, 11, 26, 12, 0)  # Donnerstag


def pkg(name, candidate="2.0-2", installed="2.0-1", **over):
    return {"name": name, "installed": installed, "candidate": candidate, "archive": "bookworm-security", "origin": "Debian", "official": True,
            "security": True, "checked": True, **over}


def evaluate(updates, mode="security", overrides=None, seen=None, grace=0, **report):
    return au.evaluate({"manager": "apt", "updates": updates, **report}, {"mode": mode, "grace_days": grace}, overrides or {}, seen or {}, NOW)


def status_of(result, name):
    return next(i for i in result["items"] if i["name"] == name)


# ------------------------------------------------------------------------------------------------ Regeln


def test_plain_security_update_is_included():
    result = evaluate([pkg("libc6", "2.36-9+deb12u9", "2.36-9+deb12u8")])
    assert status_of(result, "libc6")["status"] == "include"  # Kernbibliotheken sind der Zweck von Sicherheitspatches
    assert [i["name"] for i in au.selected(result)] == ["libc6"]


@pytest.mark.parametrize("name,code", [
    ("linux-image-6.1.0-28-amd64", "kernel"), ("linux-image-amd64", "kernel"), ("kernel-core", "kernel"), ("grub-efi-amd64", "boot"),
    ("intel-microcode", "boot"), ("linux-firmware", "boot"), ("network-manager", "network"), ("netplan.io", "network"), ("ufw", "network"),
    ("postgresql-15", "database"), ("mariadb-server", "database"), ("docker-ce", "container"), ("containerd.io", "container"),
    ("qemu-system-x86", "virtual"), ("zfsutils-linux", "virtual"), ("nginx", "service"), ("postfix", "service"), ("php8.2-fpm", "service"),
])
def test_risky_packages_are_held_back_with_a_reason(name, code):
    item = status_of(evaluate([pkg(name)]), name)
    assert item["status"] == "hold" and item["reasons"][0]["code"] == code and item["can_include"] is True


def test_harmless_neighbours_are_not_caught_by_the_patterns():
    for name in ("openssl", "libssl3", "curl", "sudo", "openssh-server", "tzdata", "libpq5", "mariadb-client", "postgresql-client-15", "nginx-common-docs-x"):
        assert status_of(evaluate([pkg(name)]), name)["status"] in ("include", "hold"), name
    assert status_of(evaluate([pkg("libpq5")]), "libpq5")["status"] == "include"
    assert status_of(evaluate([pkg("openssh-server")]), "openssh-server")["status"] == "include"


def test_major_jump_third_party_and_new_kernel_are_held():
    jump = status_of(evaluate([pkg("foo", "3.0-1", "2.9-1")]), "foo")
    assert jump["status"] == "hold" and jump["reasons"][0]["code"] == "major"
    third = status_of(evaluate([pkg("bar", official=False, origin="Docker", archive="bookworm")]), "bar")
    assert third["status"] == "hold" and third["reasons"][0]["code"] == "third" and "Docker" in third["reasons"][0]["text"]
    unknown = status_of(evaluate([pkg("baz", official=False, origin="", archive="")]), "baz")
    assert unknown["status"] == "hold"
    pulls = status_of(evaluate([pkg("meta", installs=["linux-image-6.1.0-30-amd64"])]), "meta")
    assert pulls["status"] == "hold" and any(r["code"] == "pulls_kernel" for r in pulls["reasons"])
    # Datumsversionen (tzdata 2024a → 2025b, Firmware 20240709) sind kein Sprung; ebenso die Epoche bei dnf
    assert status_of(evaluate([pkg("tzdata", "2025b-0+deb12u1", "2024a-0+deb12u1")]), "tzdata")["status"] == "include"
    assert au.major_jump("1:3.1-1", "3.2-1") and not au.major_jump("1:3.1-1", "3.2-1", ignore_epoch=True)
    assert not au.major_jump("", "3.2") and not au.major_jump("abc", "3.2")


def test_held_or_removing_packages_cannot_be_forced_in():
    held = status_of(evaluate([pkg("foo", held=True)], overrides={"foo": {"decision": "include", "once": False}}), "foo")
    assert held["status"] == "hold" and held["can_include"] is False and held["reasons"][0]["code"] == "held"
    removing = status_of(evaluate([pkg("bar", removes=["baz", "qux"])], overrides={"bar": {"decision": "include", "once": True}}), "bar")
    assert removing["status"] == "hold" and removing["can_include"] is False and "baz" in removing["reasons"][0]["text"]


def test_user_overrides_win_over_the_rules():
    updates = [pkg("nginx"), pkg("libc6")]
    result = evaluate(updates, overrides={"nginx": {"decision": "include", "once": True}, "libc6": {"decision": "exclude", "once": False}})
    assert status_of(result, "nginx")["status"] == "include" and status_of(result, "nginx")["override"] == "once_include"
    assert status_of(result, "libc6")["status"] == "user_excluded" and status_of(result, "libc6")["override"] == "always_exclude"
    assert [i["name"] for i in au.selected(result)] == ["nginx"]


def test_mode_security_leaves_normal_updates_out_and_all_takes_them():
    updates = [pkg("vim", security=False, archive="bookworm-updates"), pkg("libc6")]
    only_security = evaluate(updates, mode="security")
    assert status_of(only_security, "vim")["status"] == "scope" and [i["name"] for i in au.selected(only_security)] == ["libc6"]
    everything = evaluate(updates, mode="all")
    assert sorted(i["name"] for i in au.selected(everything)) == ["libc6", "vim"]
    forced = evaluate(updates, mode="security", overrides={"vim": {"decision": "include", "once": False}})
    assert status_of(forced, "vim")["status"] == "include"


def test_grace_period_delays_normal_updates_but_never_security():
    seen = {"vim": {"candidate": "2.0-2", "first_seen": (NOW - timedelta(days=1)).astimezone().isoformat()},
            "libc6": {"candidate": "2.0-2", "first_seen": NOW.astimezone().isoformat()}}
    updates = [pkg("vim", security=False), pkg("libc6")]
    result = evaluate(updates, mode="all", seen=seen, grace=3)
    assert status_of(result, "vim")["status"] == "waiting" and status_of(result, "vim")["waiting_until"] == "2026-11-28"
    assert status_of(result, "libc6")["status"] == "include"
    old = {"vim": {"candidate": "2.0-2", "first_seen": (NOW - timedelta(days=5)).astimezone().isoformat()}}
    assert status_of(evaluate(updates, mode="all", seen=old, grace=3), "vim")["status"] == "include"
    newer = {"vim": {"candidate": "1.9-1", "first_seen": (NOW - timedelta(days=5)).astimezone().isoformat()}}  # andere Fassung: Zeit beginnt neu
    assert status_of(evaluate(updates, mode="all", seen=newer, grace=3), "vim")["status"] == "include"  # die gemerkte Fassung ist eine andere: sie wird beim Prüfen neu gemerkt


def test_low_disk_space_blocks_the_whole_run():
    result = evaluate([pkg("libc6")], free_mb=300)
    assert result["blocked"] and result["blocked"][0]["code"] == "disk"
    assert not evaluate([pkg("libc6")], free_mb=50000)["blocked"]


def test_duplicate_architectures_and_bad_names_are_dropped():
    result = evaluate([pkg("libc6"), pkg("libc6", arch="i386"), pkg("bad name; rm"), pkg("")])
    assert [i["name"] for i in result["items"]] == ["libc6"]


# ------------------------------------------------------------------------------------------------ Zeitplan


def test_slots():
    assert au.last_slot(NOW, 7, "03:30") == datetime(2026, 11, 26, 3, 30)  # täglich: heute früh
    assert au.next_slot(NOW, 7, "03:30") == datetime(2026, 11, 27, 3, 30)
    assert au.next_slot(NOW, 6, "03:30") == datetime(2026, 11, 29, 3, 30)  # Sonntag
    assert au.last_slot(NOW, 0, "03:30") == datetime(2026, 11, 23, 3, 30)  # letzter Montag
    assert au.last_slot(datetime(2026, 11, 26, 3, 0), 7, "03:30") == datetime(2026, 11, 25, 3, 30)  # noch nicht erreicht: gestern
    assert au.slot_key(datetime(2026, 11, 26, 3, 30)) == "2026-11-26T03:30"


def test_failed_units_and_run_failed():
    text = "● nginx.service loaded failed failed A web server\n* foo@bar.service loaded failed failed X\nUNIT LOAD\n"
    assert au.failed_units(text) == {"nginx.service", "foo@bar.service"}
    assert au.failed_units("No failed services.\n") == set()
    assert au.run_failed("... == Result: failed (exit code 100)") and not au.run_failed("== Result: ok")


# ------------------------------------------------------------------------------------------------ Ablauf mit falschem Agenten


class FakeAgent:
    """Ersetzt die Verbindung zum Agenten: antwortet auf prepare/execute/call und merkt sich, was verlangt wurde."""

    def __init__(self, hub, row, updates, *, free_mb=50000, plan_class=1, execute_text="== Result: ok", failed_after="", reboot=False):
        self.calls, self.prepared, self.updates, self.plan_class, self.execute_text = [], [], list(updates), plan_class, execute_text
        self.free_mb, self.failed_after, self.reboot, self.installed = free_mb, failed_after, reboot, False
        hub._connection = lambda ref: (row, None)
        hub.status_of = lambda r: ("online", [])
        hub.prepare = self.prepare
        hub.execute = self.execute
        hub.call = self.call

    async def prepare(self, ref, tool, args=None):
        self.prepared.append((tool, args))
        klass = 1 if (args or {}).get("action") == "update" else self.plan_class
        return {"id": "a1b2c3d4e5f60718293a4b5c", "hash": "e3" * 32, "tool": tool, "class": klass, "command": "apt-get install --only-upgrade", "preview": "Entfernt: x",
                "reason": "r", "summary": "s", "timeout_s": 60, "runner": "root", "undo": "", "msgs": {}}

    async def execute(self, ref, plan):
        self.calls.append("execute")
        if self.prepared[-1][1].get("action") == "upgrade":
            self.installed = True
        return self.execute_text

    async def call(self, ref, tool, args=None, **kw):
        self.calls.append(tool)
        if tool == "update_candidates":
            ups = [] if self.installed and not self.execute_text.endswith("failed") else self.updates
            return json.dumps({"manager": "apt", "updates": ups, "free_mb": self.free_mb, "reboot_required": self.reboot})
        if tool == "services_failed":
            return self.failed_after if self.installed else "No failed services.\n"
        raise AssertionError(tool)


def server(hub, **info):
    hub.repo.server_create("srv1", "web01", "ab" * 32, "key1")
    hub.repo.server_state("srv1", "active")
    hub.repo.server_seen("srv1", "10.0.0.5", {"os": "Debian 12", "operate": True, **info})
    return hub.repo.server_get("srv1")


def make(tmp_path, updates, **kw):
    hub = make_hub(tmp_path)
    row = server(hub)
    hub.autoupdate.settle = 0
    hub.autoupdate.clock = lambda: NOW
    agent = FakeAgent(hub, row, updates, **kw)
    results = []

    async def on_result(r, run):
        results.append(run)
    hub.autoupdate.on_result = on_result
    return hub, row, agent, results


def test_run_installs_only_the_vetted_list_and_logs_it(tmp_path):
    async def scenario():
        hub, row, agent, results = make(tmp_path, [pkg("libc6", "2.36-9+deb12u9", "2.36-9+deb12u8"), pkg("nginx"), pkg("vim", security=False)])
        run = await hub.autoupdate.run(row, "Dominik", "manual")
        upgrade = [a for t, a in agent.prepared if a["action"] == "upgrade"][0]
        assert upgrade == {"action": "upgrade", "packages": ["libc6"], "auto": True}  # nginx (Anwendung) und vim (nicht Sicherheit) bleiben draußen
        assert run["status"] == "ok" and run["installed"] == [{"name": "libc6", "from": "2.36-9+deb12u8", "to": "2.36-9+deb12u9"}]
        assert run["held_back"] == 2 and results and results[0]["id"] == run["id"]
        audit = hub.repo.audit_list(server_id="srv1", kind="change")
        assert audit and audit[0]["result"] == "ok" and "libc6" in audit[0]["detail"]
    asyncio.run(scenario())


def test_run_with_nothing_to_do_is_quiet(tmp_path):
    async def scenario():
        hub, row, agent, results = make(tmp_path, [pkg("nginx")])
        run = await hub.autoupdate.run(row, "", "schedule")
        assert run["status"] == "ok" and run["installed"] == [] and not any(a["action"] == "upgrade" for _, a in agent.prepared)
        assert results == []  # kein Lärm, wenn nichts passiert ist
    asyncio.run(scenario())


def test_run_is_not_started_with_low_disk_space(tmp_path):
    async def scenario():
        hub, row, agent, results = make(tmp_path, [pkg("libc6")], free_mb=200)
        run = await hub.autoupdate.run(row, "", "schedule")
        assert run["status"] == "attention" and "Platz" in run["summary"] and "execute" not in agent.calls[2:] and results
    asyncio.run(scenario())


def test_run_stops_when_the_agent_dry_run_finds_more(tmp_path):
    async def scenario():
        hub, row, agent, results = make(tmp_path, [pkg("libc6")], plan_class=2)
        run = await hub.autoupdate.run(row, "", "schedule")
        assert run["status"] == "attention" and agent.installed is False and results
    asyncio.run(scenario())


def test_new_failed_service_is_reported(tmp_path):
    async def scenario():
        hub, row, agent, results = make(tmp_path, [pkg("libc6")], failed_after="● cron.service loaded failed failed Cron\n")
        run = await hub.autoupdate.run(row, "", "schedule")
        assert run["status"] == "attention" and run["new_failed"] == ["cron.service"] and "cron.service" in run["summary"]
    asyncio.run(scenario())


def test_failed_install_is_marked_failed(tmp_path):
    async def scenario():
        hub, row, agent, results = make(tmp_path, [pkg("libc6")], execute_text="… == Result: failed (exit code 100)")
        run = await hub.autoupdate.run(row, "", "schedule")
        assert run["status"] == "failed" and run["installed"] == []
    asyncio.run(scenario())


def test_once_overrides_are_used_up_after_a_run(tmp_path):
    async def scenario():
        hub, row, agent, results = make(tmp_path, [pkg("libc6"), pkg("nginx")])
        hub.autoupdate.repo.set_override("srv1", "nginx", "include", True)
        hub.autoupdate.repo.set_override("srv1", "libc6", "exclude", False)
        await hub.autoupdate.run(row, "", "manual")
        upgrade = [a for t, a in agent.prepared if a["action"] == "upgrade"][0]
        assert upgrade["packages"] == ["nginx"]
        assert hub.autoupdate.repo.overrides("srv1") == {"libc6": {"decision": "exclude", "once": False}}
    asyncio.run(scenario())


# ------------------------------------------------------------------------------------------------ Einstellungen


def test_settings_are_validated_and_need_operate(tmp_path):
    hub = make_hub(tmp_path)
    server(hub)
    auto = hub.autoupdate
    auto.clock = lambda: NOW
    view = auto.save_settings("srv1", {"enabled": True, "mode": "all", "weekday": 6, "at_time": "04:15", "grace_days": 2}, "Dominik")
    assert view["settings"] == {"enabled": True, "mode": "all", "weekday": 6, "at_time": "04:15", "grace_days": 2}
    assert view["next_run"] == "2026-11-29T04:15"
    assert auto.repo.settings("srv1")["last_slot"] == "2026-11-22T04:15"  # kein sofortiger Lauf für einen vergangenen Zeitpunkt
    for bad in ({"mode": "alles"}, {"weekday": 9}, {"at_time": "25:00"}, {"at_time": "3:30"}, {"grace_days": 99}, {"enabled": "ja"}):
        with pytest.raises(serverlib.ServerError):
            auto.save_settings("srv1", bad, "x")
    hub.repo.server_seen("srv1", "10.0.0.5", {"os": "Debian 12", "operate": False})
    auto.save_settings("srv1", {"enabled": False}, "x")
    with pytest.raises(serverlib.ServerError, match="nicht erlaubt"):
        auto.save_settings("srv1", {"enabled": True}, "x")
    hub.repo.server_seen("srv1", "10.0.0.5", {"os": "Debian 12", "operate": True, "auto_update_denied": True})
    with pytest.raises(serverlib.ServerError, match="gesperrt"):
        auto.save_settings("srv1", {"enabled": True}, "x")


def test_package_decisions_and_skip(tmp_path):
    hub, row, agent, _ = make(tmp_path, [pkg("nginx"), pkg("held", held=True)])
    auto = hub.autoupdate
    auto.save_settings("srv1", {"enabled": True}, "Dominik")
    auto._store_report("srv1", json.loads(asyncio.run(agent.call("srv1", "update_candidates"))))
    view = auto.set_package("srv1", "nginx", "include", True, "Dominik")
    assert next(i for i in view["preview"]["items"] if i["name"] == "nginx")["status"] == "include"
    with pytest.raises(serverlib.ServerError, match="nicht automatisch"):
        auto.set_package("srv1", "held", "include", False, "Dominik")
    with pytest.raises(serverlib.ServerError):
        auto.set_package("srv1", "bad name", "include", False, "x")
    view = auto.set_package("srv1", "nginx", "clear", False, "Dominik")
    assert next(i for i in view["preview"]["items"] if i["name"] == "nginx")["status"] == "hold"
    assert auto.set_skip("srv1", True, "Dominik")["skip_next"] is True
    assert auto.set_skip("srv1", False, "Dominik")["skip_next"] is False


# ------------------------------------------------------------------------------------------------ Zeitplan im Hub


def test_tick_runs_missed_slot_skips_old_ones_and_honours_skip(tmp_path):
    async def scenario():
        hub, row, agent, results = make(tmp_path, [pkg("libc6")])
        auto = hub.autoupdate
        auto.repo.save("srv1", {"enabled": True, "last_slot": "2026-11-25T03:30"}, "x")
        auto.clock = lambda: datetime(2026, 11, 26, 3, 31)
        await auto.tick()  # Zeitpunkt 03:30 ist da: Lauf startet im Hintergrund
        await asyncio.gather(*auto._tasks)
        runs = auto.repo.runs("srv1")
        assert len(runs) == 1 and runs[0]["status"] == "ok" and runs[0]["trigger"] == "schedule"
        await auto.tick()
        assert len(auto.repo.runs("srv1")) == 1  # nicht zweimal für denselben Zeitpunkt

        # verpasst und zu lange her: übersprungen und gemeldet, nicht mitten am Tag nachgeholt
        auto.repo.save("srv1", {"last_slot": "2026-11-26T03:30"}, "x")
        auto.clock = lambda: datetime(2026, 11, 27, 18, 0)
        await auto.tick()
        assert auto.repo.runs("srv1", 1)[0]["status"] == "skipped" and len(agent.prepared) == 2  # nur der erste Lauf (update, upgrade); der ausgefallene hat nichts verlangt

        # auf Wunsch übersprungen
        auto.repo.save("srv1", {"skip_slot": "2026-11-28T03:30"}, "x")
        auto.clock = lambda: datetime(2026, 11, 28, 3, 40)
        before = len(auto.repo.runs("srv1"))
        await auto.tick()
        assert len(auto.repo.runs("srv1")) == before and auto.repo.settings("srv1")["last_slot"] == "2026-11-28T03:30" and auto.repo.settings("srv1")["skip_slot"] == ""
    asyncio.run(scenario())


def test_tick_waits_for_an_offline_server(tmp_path):
    async def scenario():
        hub, row, agent, results = make(tmp_path, [pkg("libc6")])
        hub.status_of = lambda r: ("offline", [])
        auto = hub.autoupdate
        auto.repo.save("srv1", {"enabled": True, "last_slot": "2026-11-25T03:30"}, "x")
        auto.clock = lambda: datetime(2026, 11, 26, 4, 0)
        await auto.tick()
        assert auto.repo.runs("srv1") == [] and auto.repo.settings("srv1")["last_slot"] == "2026-11-25T03:30"  # später nachholen
        hub.status_of = lambda r: ("online", [])
        await auto.tick()
        await asyncio.gather(*auto._tasks)
        assert auto.repo.runs("srv1")[0]["status"] == "ok"
    asyncio.run(scenario())


def test_removing_a_server_removes_its_settings(tmp_path):
    hub = make_hub(tmp_path)
    server(hub)
    hub.autoupdate.save_settings("srv1", {"enabled": True}, "x")
    hub.autoupdate.repo.set_override("srv1", "nginx", "exclude", False)
    hub.remove("srv1", "Dominik")
    assert hub.autoupdate.repo.enabled_ids() == [] and hub.autoupdate.repo.overrides("srv1") == {}


def test_ai_has_no_way_to_change_it(tmp_path):
    assert "update_candidates" in serverlib.READ_TOOLS and "update_candidates" not in serverlib.AI_READ_TOOLS
    from app.server_tools import clean_change_args
    cleaned = clean_change_args("package", {"action": "upgrade", "packages": ["libc6"], "auto": True})
    assert "auto" not in cleaned  # das Kennzeichen der automatischen Aktualisierung kann die KI nicht setzen


def test_old_agent_is_refused_with_a_clear_message(tmp_path):
    hub = make_hub(tmp_path)
    row = server(hub, agent_version="0.67.1")
    hub._connection = lambda ref: (row, None)
    for action in (lambda: hub.autoupdate._check_runnable(row), lambda: asyncio.run(_start_refresh(hub))):
        with pytest.raises(serverlib.ServerError) as err:
            action()
        assert "zu alt" in str(err.value) and "0.67.1" in str(err.value)
    row = server_with_version(hub, "0.68.0")
    hub.autoupdate._check_agent(row)  # keine Ausnahme
    row = server_with_version(hub, "")
    hub.autoupdate._check_agent(row)  # unbekannte Fassung wird nicht pauschal abgelehnt


async def _start_refresh(hub):
    hub.autoupdate.start_refresh("srv1", "x")


def server_with_version(hub, version):
    hub.repo.server_seen("srv1", "10.0.0.5", {"os": "Debian 12", "operate": True, "agent_version": version})
    return hub.repo.server_get("srv1")


def test_background_refresh_waits_after_a_failure_and_starts_again_later(tmp_path):
    async def scenario():
        hub, row, agent, results = make(tmp_path, [pkg("libc6")])
        auto = hub.autoupdate
        auto.repo.save("srv1", {"enabled": True, "last_slot": "2026-11-26T03:30"}, "x")
        auto.clock = lambda: datetime(2026, 11, 26, 12, 0)

        async def broken(ref, tool, args=None, **kw):
            agent.calls.append(tool)
            raise serverlib.ServerError("Zeitüberschreitung", 504)
        hub.call = broken
        await auto.tick()
        await asyncio.gather(*auto._tasks)
        tries = agent.calls.count("update_candidates")
        assert tries == 1
        auto.clock = lambda: datetime(2026, 11, 26, 12, 5)
        await auto.tick()
        await asyncio.gather(*auto._tasks)
        assert agent.calls.count("update_candidates") == tries  # nicht jede Minute neu versuchen
        auto.clock = lambda: datetime(2026, 11, 26, 12, 40)
        await auto.tick()
        await asyncio.gather(*auto._tasks)
        assert agent.calls.count("update_candidates") == tries + 1
    asyncio.run(scenario())


def test_start_refresh_runs_in_the_background_and_stores_the_result(tmp_path):
    async def scenario():
        hub, row, agent, results = make(tmp_path, [pkg("libc6"), pkg("nginx")])
        auto = hub.autoupdate
        assert auto.start_refresh("srv1", "Dominik") == {"started": True}
        assert auto.view("srv1")["running"]["phase"] == "check"
        with pytest.raises(serverlib.ServerError):  # zweiter Start, solange einer läuft
            auto.start_refresh("srv1", "Dominik")
        await asyncio.gather(*auto._tasks)
        view = auto.view("srv1")
        assert view["running"] is None and view["error"] == ""
        assert [i["name"] for i in view["preview"]["items"] if i["status"] == "include"] == ["libc6"]
        assert agent.prepared[0] == ("package", {"action": "update"}) and "update_candidates" in agent.calls
    asyncio.run(scenario())
