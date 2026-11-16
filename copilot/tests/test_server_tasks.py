"""Linux-Server in geplanten Aufgaben (nur lesen) und dnf-Anpassungen des Hubs (Pläne alter und neuer Agenten, Paketnamen)."""
import asyncio

import pytest

from app import server_messages
from app.ha_tools import ToolError
from app.i18n import set_language
from app.server_tools import SERVER_SCHEDULED_NOTE, ServerToolbox, clean_change_args

from test_schedules import SETTINGS, build, make_task, run_tick
from test_servers import FakeHub, make_hub, settings

CHANGE_TOOLS = {"server_service", "server_package", "server_run", "server_file_write"}
READ_TOOLS = {"server_list", "server_status", "server_read"}


def hub_with_server(tmp_path):
    hub = make_hub(tmp_path)
    hub.repo.server_create("srv-1", "web01", "ff" * 32, "k")
    hub.repo.server_state("srv-1", "active")
    return hub


def server_tool_names(backend) -> set[str]:
    return {t.name for t in backend.calls[0]["tools"] if t.name.startswith("server_")}


def allowed(value: bool):
    async def check(profile):
        return value
    return check


# ----------------------------------------------------------------------------------------- geplante Läufe

def test_a_scheduled_run_gets_only_the_read_tools_for_servers(store, tmp_path):
    scheduler, backend, *_ = build(store, now=2_000)
    scheduler.server_hub = hub_with_server(tmp_path)
    scheduler.server_allowed = allowed(True)
    make_task(store, next_run=1_000)
    assert run_tick(scheduler) == 1
    assert server_tool_names(backend) == READ_TOOLS
    assert not CHANGE_TOOLS & {t.name for t in backend.calls[0]["tools"]}
    assert all(t.level == "read" for t in backend.calls[0]["tools"] if t.name.startswith("server_"))
    note = backend.calls[0]["note"]
    assert SERVER_SCHEDULED_NOTE.strip()[:40] in note and "server_run" in note  # sagt ausdrücklich, was nicht erlaubt ist


@pytest.mark.parametrize("hub, check", [(None, allowed(True)), ("hub", None), ("hub", allowed(False))])
def test_a_scheduled_run_has_no_server_tools_without_hub_or_permission(store, tmp_path, hub, check):
    scheduler, backend, *_ = build(store, now=2_000)
    scheduler.server_hub = hub_with_server(tmp_path) if hub else None
    scheduler.server_allowed = check
    make_task(store, next_run=1_000)
    assert run_tick(scheduler) == 1
    assert server_tool_names(backend) == set()
    assert "server_list" not in backend.calls[0]["note"]


def test_the_permission_check_is_made_for_the_owner_of_the_task(store, tmp_path):
    scheduler, backend, *_ = build(store, now=2_000)
    scheduler.server_hub = hub_with_server(tmp_path)
    seen = []

    async def check(profile):
        seen.append(profile.id)
        return False
    scheduler.server_allowed = check
    make_task(store, next_run=1_000)
    run_tick(scheduler)
    assert seen == ["adm01"]


def test_scheduled_reads_are_logged_as_scheduled_task(tmp_path):
    hub = hub_with_server(tmp_path)
    fake = FakeHub(hub)
    box = ServerToolbox(fake, settings().profiles[0], record=lambda e: None, next_id=iter(range(1, 99)).__next__, ask=None, scheduled=True)
    specs = {s.name: s for s in box.specs()}
    assert set(specs) == READ_TOOLS
    out = asyncio.run(specs["server_read"].handler({"server": "web01", "what": "disks"}))
    assert out
    entries = hub.repo.audit_list(kind="read")
    assert len(entries) == 1 and entries[0]["server_name"] == "web01"
    assert "(geplante Aufgabe)" in entries[0]["actor"] and entries[0]["result"] == "ok"


def test_the_scheduled_actor_is_translated(tmp_path):
    hub = hub_with_server(tmp_path)
    set_language("en")  # der Name wird beim Aufbau der Werkzeuge gebildet
    box = ServerToolbox(FakeHub(hub), settings().profiles[0], record=lambda e: None, next_id=iter(range(1, 99)).__next__, ask=None, scheduled=True)
    specs = {s.name: s for s in box.specs()}
    asyncio.run(specs["server_read"].handler({"server": "web01", "what": "disks"}))
    assert "scheduled task" in hub.repo.audit_list(kind="read")[0]["actor"]


def test_a_chat_toolbox_is_not_marked_as_scheduled(tmp_path):
    hub = hub_with_server(tmp_path)
    box = ServerToolbox(FakeHub(hub), settings().profiles[0], record=lambda e: None, next_id=iter(range(1, 99)).__next__)
    specs = {s.name: s for s in box.specs()}
    asyncio.run(specs["server_read"].handler({"server": "web01", "what": "disks"}))
    assert "geplante" not in hub.repo.audit_list(kind="read")[0]["actor"]
    assert "geplante" not in box.note()


# ----------------------------------------------------------------------------------------- dnf im Hub

def plan_with(code, **params):
    return {"summary": "english text", "msgs": {"summary": {"code": code, "params": params}}}


def test_old_agents_without_command_parameter_still_read_as_apt():
    assert server_messages.localize(plan_with("pkg.summary.update"), "summary") == "Paketlisten aktualisieren (apt-get update)"
    assert server_messages.localize(plan_with("pkg.summary.upgrade_all"), "summary") == "Alle Pakete aktualisieren (apt-get upgrade)"


def test_new_agents_name_their_own_package_manager():
    assert server_messages.localize(plan_with("pkg.summary.update", command="dnf makecache"), "summary") == "Paketlisten aktualisieren (dnf makecache)"
    assert server_messages.localize(plan_with("pkg.summary.upgrade_all", command="dnf upgrade"), "summary") == "Alle Pakete aktualisieren (dnf upgrade)"


def test_english_keeps_the_agents_text():
    set_language("en")
    assert server_messages.localize(plan_with("pkg.summary.update", command="dnf makecache"), "summary") == "english text"


@pytest.mark.parametrize("name", ["nginx", "libstdc++-devel", "python3.12", "NetworkManager", "glibc_common", "gcc-c++", "libfoo:amd64", "kernel-6.1.0-1.el9"])
def test_package_names_of_apt_and_dnf_are_accepted(name):
    assert clean_change_args("package", {"action": "install", "packages": [name]})["packages"] == [name]


@pytest.mark.parametrize("name", ["", "-y", "--help", "a b", "a;b", "$(x)", "a/b", "x" * 101, ".hidden", "a\nb", "@group"])
def test_dangerous_package_names_are_still_refused(name):
    with pytest.raises(ToolError):
        clean_change_args("package", {"action": "install", "packages": [name]})
