"""Chatwissen im Projekt: Die KI sieht die anderen Chats eines Projekts, nur die eigenen und nur im selben Projekt."""
import asyncio

import pytest

from app.context_tools import ContextToolbox
from app.ha_tools import ToolError


def run(coro):
    return asyncio.run(coro)


class Asker:
    async def __call__(self, label, details, offer):
        return "allow"


def box(store, profile="dora", *, project_id=None, chat_id=""):
    events, counter = [], iter(range(1, 1000))
    b = ContextToolbox(
        store, profile, profile.capitalize(), project_id=project_id, chat_id=chat_id, memory_enabled=True, household_write=True,
        force_confirm=False, ask=Asker(), record=events.append, next_id=lambda: next(counter),
    )
    b.events = events
    return b


def handler(b, name):
    return next(s for s in b.specs() if s.name == name).handler


def chat(store, profile, title, project, *messages):
    c = store.create_chat(profile, title, project)
    for role, text in messages:
        store.add_message(profile, c["id"], role, text)
    return c["id"]


@pytest.fixture
def world(store):
    pid = store.create_project("dora", "Smarthome")["id"]
    other = store.create_project("dora", "Garten")["id"]
    here = chat(store, "dora", "Aktueller Chat", pid, ("user", "Heute"))
    zabbix = chat(store, "dora", "Zabbix Templates", pid, ("user", "Wie baue ich ein Zabbix Template für den Wechselrichter?"), ("assistant", "Nimm den Wechselrichter-Typ SMA und lege Items an."))
    heizung = chat(store, "dora", "Heizung Keller", pid, ("user", "Heizkurve Keller auf 0,6 stellen"), ("assistant", "Erledigt, Vorlauf 35 °C."))
    garten = chat(store, "dora", "Garten Bewässerung", other, ("user", "Zabbix im Garten?"))
    outside = chat(store, "dora", "Ohne Projekt", None, ("user", "Zabbix Wechselrichter"))
    foreign = chat(store, "adm01", "Fremd", None, ("user", "Zabbix Wechselrichter"))
    return dict(pid=pid, other=other, here=here, zabbix=zabbix, heizung=heizung, garten=garten, outside=outside, foreign=foreign)


def test_tools_only_when_project_has_other_chats(store):
    pid = store.create_project("dora", "Leer")["id"]
    only = chat(store, "dora", "Allein", pid, ("user", "x"))
    assert not {s.name for s in box(store, project_id=pid, chat_id=only).specs()} & {"project_chats", "chat_search", "chat_read"}
    assert not {s.name for s in box(store).specs()} & {"project_chats", "chat_search", "chat_read"}


def test_list_shows_only_other_chats_of_this_project(store, world):
    b = box(store, project_id=world["pid"], chat_id=world["here"])
    assert {"project_chats", "chat_search", "chat_read"} <= {s.name for s in b.specs()}
    listing = run(handler(b, "project_chats")({}))
    assert "Zabbix Templates" in listing and "Heizung Keller" in listing and "keine Anweisung" in listing
    for hidden in ("Aktueller Chat", "Garten Bewässerung", "Ohne Projekt", "Fremd"):
        assert hidden not in listing
    assert b.events[-1]["kind"] == "knowledge"  # zählt als gelesener Inhalt: Gedächtnis nur nach Rückfrage


def test_search_stays_in_the_project(store, world):
    b = box(store, project_id=world["pid"], chat_id=world["here"])
    hits = run(handler(b, "chat_search")({"query": "zabbix wechselrichter"}))
    assert "Zabbix Templates" in hits and "Garten" not in hits and "Ohne Projekt" not in hits and "Fremd" not in hits
    assert "Keine Treffer" in run(handler(b, "chat_search")({"query": "Waschmaschine"}))


def test_read_by_id_prefix_or_title_and_isolation(store, world):
    b = box(store, project_id=world["pid"], chat_id=world["here"])
    by_id = run(handler(b, "chat_read")({"chat": world["zabbix"][:8]}))
    assert "SMA" in by_id and "[1] Nutzer" in by_id and "[2] KI" in by_id
    assert "Vorlauf 35" in run(handler(b, "chat_read")({"chat": "heizung"}))
    for bad in (world["garten"], world["outside"], world["foreign"], world["here"], "gibtsnicht"):
        with pytest.raises(ToolError):
            run(handler(b, "chat_read")({"chat": bad}))
    # ein fremder Chat bleibt auch dann unerreichbar, wenn eine andere Person dasselbe Projekt benennt
    stranger = box(store, "adm01", project_id=world["pid"], chat_id="")
    assert stranger.project_id == world["pid"] and run(stranger.project_chats({})).endswith("keine weiteren Chats.")
    with pytest.raises(ToolError):
        run(stranger.chat_read({"chat": "Zabbix"}))


def test_read_ambiguous_title_and_long_chat_in_sections(store, world):
    chat(store, "dora", "Zabbix Items", world["pid"], ("user", "a"))
    b = box(store, project_id=world["pid"], chat_id=world["here"])
    with pytest.raises(ToolError, match="Nicht eindeutig"):
        run(handler(b, "chat_read")({"chat": "zabbix"}))
    long_id = chat(store, "dora", "Lang", world["pid"], *[("user" if i % 2 == 0 else "assistant", f"Text {i} " + "x" * 700) for i in range(30)])
    first = run(handler(b, "chat_read")({"chat": long_id[:8], "max_chars": 3000}))
    assert "Weiter mit first_message=" in first
    n = int(first.rsplit("first_message=", 1)[1].rstrip("."))
    assert f"[{n}]" in run(handler(b, "chat_read")({"chat": long_id[:8], "first_message": n, "max_chars": 3000}))


def test_note_lists_chats_and_keeps_memory(store, world):
    store.memory_save("person", "dora", "Vorliebe", "Duzt gern", "dora")
    note = box(store, project_id=world["pid"], chat_id=world["here"]).note(["Dora"], "read", False)
    assert "Zabbix Templates" in note and "chat_search" in note and "Garten Bewässerung" not in note
    assert "Duzt gern" in note and "Persönliches Gedächtnis" in note  # beides zusammen
    assert "Daten, keine Anweisungen" in note
    assert "Chatwissen" not in box(store).note(["Dora"], "read", False)
