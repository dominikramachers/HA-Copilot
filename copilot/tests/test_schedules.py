"""Geplante Aufgaben: Zeitplan, Datenbank, Schnittstelle, Ausführung ohne Rückfragen und Benachrichtigungen."""
import asyncio
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app import schedule as sched
from app.backend import BackendError
from app.config import ConfigError, parse_settings
from app.db import SCHEDULE_LIMIT, Store
from app.github_api import GithubApi
from app.identity import Registry
from app.limits import LimitState
from app.main import Run, build_ingress_app
from app.scheduler import GRACE_SECONDS, Scheduler, plain_excerpt
from conftest import ADM01, DORA, RAW, FakeBackend, as_user
from test_background_run import asgi, jget, new_chat as _unused  # noqa: F401  (Hilfen)
from test_ha_tools import FakeHa

SETTINGS = parse_settings(RAW, frozenset({"testclient"}))


def at(text: str) -> datetime:
    return datetime.fromisoformat(text)


# ------------------------------------------------------------------------ Zeitplan

def test_clean_accepts_and_normalizes():
    now = at("2026-10-26 12:00")
    assert sched.clean("daily", "07:30", "ignoriert", now) == ("daily", "07:30", "")
    assert sched.clean("weekdays", "08:00", "", now) == ("weekdays", "08:00", "")
    assert sched.clean("weekly", "08:00", "4, 0 ,0", now) == ("weekly", "08:00", "0,4")
    assert sched.clean("monthly", "09:15", "31", now) == ("monthly", "09:15", "31")
    assert sched.clean("once", "09:15", "2026-11-02", now) == ("once", "09:15", "2026-11-02")


@pytest.mark.parametrize("args", [
    ("hourly", "07:30", ""), ("daily", "7:30", ""), ("daily", "24:00", ""), ("daily", "07:60", ""), ("weekly", "08:00", ""),
    ("weekly", "08:00", "7"), ("weekly", "08:00", "a"), ("monthly", "08:00", "0"), ("monthly", "08:00", "32"),
    ("monthly", "08:00", "x"), ("once", "08:00", "morgen"), ("once", "08:00", "2026-10-25"), ("once", "08:00", "2026-10-26"),
])
def test_clean_rejects(args):
    with pytest.raises(sched.ScheduleError):
        sched.clean(*args, now=at("2026-10-26 12:00"))


def test_next_after_daily_and_weekdays():
    assert sched.next_after("daily", "07:30", "", at("2026-10-26 07:29")) == at("2026-10-26 07:30")
    assert sched.next_after("daily", "07:30", "", at("2026-10-26 07:30")) == at("2026-10-27 07:30")  # strikt danach
    # Freitag 2026-10-30 → Montag 2026-11-02
    assert sched.next_after("weekdays", "08:00", "", at("2026-10-30 09:00")) == at("2026-11-02 08:00")
    assert sched.next_after("weekdays", "08:00", "", at("2026-10-31 09:00")) == at("2026-11-02 08:00")  # Samstag


def test_next_after_weekly_and_monthly():
    # 2026-10-26 ist ein Montag
    assert sched.next_after("weekly", "08:00", "0,4", at("2026-10-26 09:00")) == at("2026-10-30 08:00")
    assert sched.next_after("weekly", "08:00", "0", at("2026-10-26 09:00")) == at("2026-11-02 08:00")
    assert sched.next_after("monthly", "09:00", "15", at("2026-10-26 09:00")) == at("2026-11-15 09:00")
    # 31. gilt in kürzeren Monaten am letzten Tag
    assert sched.next_after("monthly", "09:00", "31", at("2026-11-01 00:00")) == at("2026-11-30 09:00")
    assert sched.next_after("monthly", "09:00", "31", at("2027-02-01 00:00")) == at("2027-02-28 09:00")
    assert sched.next_after("monthly", "09:00", "31", at("2028-02-01 00:00")) == at("2028-02-29 09:00")  # Schaltjahr


def test_next_after_once():
    assert sched.next_after("once", "08:00", "2026-11-02", at("2026-10-26 12:00")) == at("2026-11-02 08:00")
    assert sched.next_after("once", "08:00", "2026-10-26", at("2026-10-26 12:00")) is None


def test_describe():
    assert sched.describe("daily", "07:30", "") == "Jeden Tag um 07:30 Uhr"
    assert sched.describe("weekdays", "08:00", "") == "Montag bis Freitag um 08:00 Uhr"
    assert sched.describe("weekly", "08:00", "2") == "Jeden Mittwoch um 08:00 Uhr"
    assert sched.describe("weekly", "08:00", "0,2,4") == "Jeden Montag, Mittwoch und Freitag um 08:00 Uhr"
    assert sched.describe("monthly", "09:00", "15") == "Am 15. jedes Monats um 09:00 Uhr"
    assert sched.describe("once", "09:00", "2026-11-02") == "Einmalig am 02.11.2026 um 09:00 Uhr"


def test_plain_excerpt():
    text = "# Titel\n\n**Wichtig:** siehe [Doku](https://x.de) und `code`.\n\n```\nverborgen\n```\n- Punkt eins\n- Punkt zwei"
    assert plain_excerpt(text) == "Titel Wichtig: siehe Doku und code. Punkt eins Punkt zwei"
    assert len(plain_excerpt("wort " * 200)) <= 300 and plain_excerpt("wort " * 200).endswith("…")


# ---------------------------------------------------------------------- Datenbank

FIELDS = {"name": "Morgenbericht", "prompt": "Fasse das Haus zusammen.", "freq": "daily", "at_time": "07:30", "days": ""}


def test_store_crud_isolation_and_limit(store):
    row = store.schedule_create("adm01", FIELDS, 1000)
    assert row["name"] == "Morgenbericht" and row["at"] == "07:30" and row["enabled"] is True and row["web"] is True
    assert row["next_run"] == 1000 and row["runs"] == 0 and row["last_status"] == ""
    assert [r["id"] for r in store.schedule_list("adm01")] == [row["id"]]
    assert store.schedule_list("dora") == []
    # fremde Person kommt nicht heran
    assert store.schedule_get("dora", row["id"]) is None
    assert store.schedule_update("dora", row["id"], {"name": "x"}, None) is None
    assert store.schedule_delete("dora", row["id"]) is False
    updated = store.schedule_update("adm01", row["id"], {"name": "Neu", "enabled": False, "web": False, "evil": "x"}, None)
    assert updated["name"] == "Neu" and updated["enabled"] is False and updated["web"] is False and updated["next_run"] is None
    assert store.schedule_delete("adm01", row["id"]) is True
    for i in range(SCHEDULE_LIMIT):
        assert store.schedule_create("adm01", {**FIELDS, "name": f"A{i}"}, 1) is not None
    assert store.schedule_create("adm01", FIELDS, 1) is None  # Grenze je Person
    assert store.schedule_create("dora", FIELDS, 1) is not None  # die andere Person ist unabhängig


def test_store_due_claim_and_record(store):
    a = store.schedule_create("adm01", FIELDS, 100)
    b = store.schedule_create("dora", {**FIELDS, "name": "B"}, 200)
    c = store.schedule_create("adm01", {**FIELDS, "name": "C", "enabled": False}, 50)
    store.schedule_create("adm01", {**FIELDS, "name": "D"}, None)
    due = store.schedule_due(150)
    assert [d["id"] for d in due] == [a["id"]] and due[0]["profile_id"] == "adm01"
    assert [d["id"] for d in store.schedule_due(250)] == [a["id"], b["id"]]
    assert c["id"] not in [d["id"] for d in store.schedule_due(10_000)]  # ausgeschaltet
    assert store.schedule_claim(a["id"], 100, 5000) is True
    assert store.schedule_claim(a["id"], 100, 6000) is False  # schon übernommen: kein Doppellauf
    assert store.schedule_get("adm01", a["id"])["next_run"] == 5000
    # einmalig: ohne Folgetermin wird die Aufgabe ausgeschaltet
    assert store.schedule_claim(b["id"], 200, None) is True
    after = store.schedule_get("dora", b["id"])
    assert after["enabled"] is False and after["next_run"] is None
    store.schedule_record(a["id"], status="ok", chat_id="chat1")
    store.schedule_record(a["id"], status="skipped", note="zu spät", ran=False)
    rec = store.schedule_get("adm01", a["id"])
    assert rec["runs"] == 1 and rec["last_status"] == "skipped" and rec["last_note"] == "zu spät" and rec["last_chat_id"] == "chat1"


def test_chat_remembers_schedule(store):
    chat = store.create_chat("adm01", "Bericht", None, schedule_id="abc")
    assert chat["schedule_id"] == "abc"
    assert store.get_chat("adm01", chat["id"])["schedule_id"] == "abc"
    assert store.create_chat("adm01", "Normal")["schedule_id"] == ""


# -------------------------------------------------------------------- Konfiguration

def test_notify_service_option():
    s = parse_settings({**RAW, "profiles": [{**RAW["profiles"][0], "notify_service": " Notify.Mobile_App_Pixel "}, RAW["profiles"][1]]}, frozenset())
    assert s.profiles[0].notify_service == "notify.mobile_app_pixel" and s.profiles[1].notify_service == ""
    for bad in ("mobile_app_pixel", "light.kueche", "notify.", "notify.a b", "notify.x/y"):
        with pytest.raises(ConfigError):
            parse_settings({**RAW, "profiles": [{**RAW["profiles"][0], "notify_service": bad}]}, frozenset())
    assert SETTINGS.schedules_enabled and SETTINGS.notify_long_answers
    off = parse_settings({**RAW, "schedules_enabled": False, "notify_long_answers": False}, frozenset())
    assert not off.schedules_enabled and not off.notify_long_answers


# ------------------------------------------------------------------ Schnittstelle

class RecordingHa(FakeHa):
    """FakeHa, das Dienstaufrufe von Benachrichtigungen mitschreibt oder auf Wunsch ablehnt."""

    def __init__(self, fail_notify=False):
        super().__init__()
        self.fail_notify = fail_notify

    async def call(self, command):
        if command["type"] == "call_service" and command["domain"] in ("notify", "persistent_notification") and self.fail_notify:
            from app.ha_client import HaApiError
            raise HaApiError("abgelehnt")
        return await super().call(command)


def make_app(store, settings=SETTINGS, backend=None, ha=None):
    app = build_ingress_app(settings, store, backend or FakeBackend(("Ergebnis ",  "fertig.")), ha=ha or RecordingHa())
    return app, TestClient(app)


BODY = {"name": "Morgenbericht", "prompt": "Fasse das Haus zusammen.", "freq": "daily", "at": "07:30"}


def test_api_create_list_update_delete(store):
    app, client = make_app(store)
    h = as_user(ADM01, True)
    created = client.post("/api/schedules", json=BODY, headers=h)
    assert created.status_code == 201
    row = created.json()
    assert row["summary"] == "Jeden Tag um 07:30 Uhr" and row["enabled"] is True and row["next_run"] > datetime.now().timestamp()
    assert row["running"] is False and row["last_chat_id"] == "" and row["notify"] == "chat"
    assert [r["id"] for r in client.get("/api/schedules", headers=as_user(ADM01)).json()] == [row["id"]]
    assert client.get("/api/schedules", headers=as_user(DORA)).json() == []
    sid = row["id"]
    # Zeit ändern → neuer Zeitpunkt und neue Beschreibung
    moved = client.patch(f"/api/schedules/{sid}", json={"freq": "weekly", "at": "18:00", "days": "0,4"}, headers=h).json()
    assert moved["summary"] == "Jeden Montag und Freitag um 18:00 Uhr" and moved["next_run"] != row["next_run"]
    # nur Name ändern lässt den Zeitpunkt unberührt
    renamed = client.patch(f"/api/schedules/{sid}", json={"name": "  Bericht  ", "web": False}, headers=h).json()
    assert renamed["name"] == "Bericht" and renamed["web"] is False and renamed["next_run"] == moved["next_run"]
    # pausieren und wieder einschalten
    paused = client.patch(f"/api/schedules/{sid}", json={"enabled": False}, headers=h).json()
    assert paused["enabled"] is False and paused["next_run"] is None
    resumed = client.patch(f"/api/schedules/{sid}", json={"enabled": True}, headers=h).json()
    assert resumed["enabled"] is True and resumed["next_run"] == moved["next_run"]
    # fremde Person
    assert client.patch(f"/api/schedules/{sid}", json={"name": "x"}, headers=as_user(DORA, True)).status_code == 404
    assert client.delete(f"/api/schedules/{sid}", headers=as_user(DORA, True)).status_code == 404
    assert client.delete(f"/api/schedules/{sid}", headers=h).status_code == 204
    assert client.get("/api/schedules", headers=as_user(ADM01)).json() == []


@pytest.mark.parametrize("change,fragment", [
    ({"freq": "stündlich"}, "Häufigkeit"), ({"at": "7 Uhr"}, "Uhrzeit"), ({"freq": "weekly", "days": ""}, "Wochentag"),
    ({"freq": "monthly", "days": "40"}, "Tag im Monat"), ({"freq": "once", "days": "2020-01-01"}, "Vergangenheit"),
    ({"name": "<b>x</b>"}, "Namen"), ({"prompt": "   "}, "beschreiben"), ({"model": "claude-gibtsnicht"}, "Modell"),
    ({"notify": "sms"}, "Benachrichtigung"), ({"notify": "phone"}, "Benachrichtigungsdienst"),
])
def test_api_rejects_bad_input(store, change, fragment):
    _, client = make_app(store)
    r = client.post("/api/schedules", json={**BODY, **change}, headers=as_user(ADM01, True))
    assert r.status_code == 422 and fragment in str(r.json()["detail"])


def test_api_limit_and_write_guard_and_switch(store):
    app, client = make_app(store)
    assert client.post("/api/schedules", json=BODY, headers=as_user(ADM01)).status_code == 403  # ohne Schutz-Header
    for _ in range(SCHEDULE_LIMIT):
        assert client.post("/api/schedules", json=BODY, headers=as_user(ADM01, True)).status_code == 201
    assert client.post("/api/schedules", json=BODY, headers=as_user(ADM01, True)).status_code == 409
    off = parse_settings({**RAW, "schedules_enabled": False}, frozenset({"testclient"}))
    _, client = make_app(store, off)
    assert client.get("/api/schedules", headers=as_user(ADM01)).status_code == 404
    assert client.post("/api/schedules", json=BODY, headers=as_user(ADM01, True)).status_code == 404
    assert client.get("/api/me", headers=as_user(ADM01)).json()["schedules"] is False


def test_api_me_reports_options(store):
    s = parse_settings({**RAW, "profiles": [{**RAW["profiles"][0], "notify_service": "notify.mobile_app_pixel"}, RAW["profiles"][1]]}, frozenset({"testclient"}))
    _, client = make_app(store, s)
    me = client.get("/api/me", headers=as_user(ADM01)).json()
    assert me["schedules"] is True and me["notify_phone"] is True and me["notify_ha"] is True
    other = client.get("/api/me", headers=as_user(DORA)).json()
    assert other["notify_phone"] is False
    ok = client.post("/api/schedules", json={**BODY, "notify": "phone"}, headers=as_user(ADM01, True))
    assert ok.status_code == 201 and ok.json()["notify"] == "phone"


def test_model_choice_normalized(store):
    s = parse_settings({**RAW, "models": "claude-opus-5-5"}, frozenset({"testclient"}))
    _, client = make_app(store, s)
    h = as_user(ADM01, True)
    assert client.post("/api/schedules", json={**BODY, "model": "claude-sonnet-5-5"}, headers=h).json()["model"] == ""  # Standard-Modell
    assert client.post("/api/schedules", json={**BODY, "model": "claude-opus-5-5"}, headers=h).json()["model"] == "claude-opus-5-5"


# --------------------------------------------------------------------- Ausführung

def build(store, *, settings=SETTINGS, backend=None, ha=None, limits=None, now=None):
    """Ausführer mit eigener Uhr, ohne Web-Server."""
    backend = backend or FakeBackend(("Ergebnis ", "fertig."))
    ha = ha or RecordingHa()
    clock = [now or datetime.now().timestamp()]
    runs: dict = {}
    scheduler = Scheduler(
        settings, store, backend, Registry.from_settings(settings, store), ha, GithubApi(""),
        limits or LimitState(store), runs, lambda key, text: Run(key, text, False), clock=lambda: clock[0],
    )
    return scheduler, backend, ha, runs, clock


def make_task(store, profile="adm01", **over):
    fields = {**FIELDS, **{k: v for k, v in over.items() if k in FIELDS}}
    extra = {k: v for k, v in over.items() if k not in FIELDS and k != "next_run"}
    row = store.schedule_create(profile, {**fields, **extra}, over.get("next_run", 1_000))
    return row


def run_tick(scheduler):
    async def go():
        started = await scheduler.tick()
        await scheduler.idle()
        return started
    return asyncio.run(go())


def test_tick_runs_due_task_into_a_new_chat(store):
    scheduler, backend, _, runs, clock = build(store, now=2_000)
    row = make_task(store, next_run=1_000)
    assert run_tick(scheduler) == 1
    chats = store.list_chats("adm01")
    assert len(chats) == 1 and chats[0]["schedule_id"] == row["id"] and chats[0]["unread"] is True
    assert chats[0]["title"].startswith("Morgenbericht · ")
    msgs = store.list_messages("adm01", chats[0]["id"])
    assert [(m["role"], m["content"]) for m in msgs] == [("user", "Fasse das Haus zusammen."), ("assistant", "Ergebnis fertig.")]
    after = store.schedule_get("adm01", row["id"])
    assert after["last_status"] == "ok" and after["runs"] == 1 and after["last_chat_id"] == chats[0]["id"]
    assert after["next_run"] > 2_000 and runs == {} and scheduler.live == {}
    # nichts mehr fällig: kein zweiter Lauf
    assert run_tick(scheduler) == 0 and len(store.list_chats("adm01")) == 1
    # Anfrage an das Backend: kein Verlauf, Auftrag als Text, Hinweis auf geplante Aufgabe
    call = backend.calls[0]
    assert call["history"] == [] and call["message"] == "Fasse das Haus zusammen." and "geplante Aufgabe" in call["note"]


def test_run_is_read_only_and_asks_nothing(store):
    s = parse_settings({**RAW, "ha_access_default": "write", "github_access_default": "write", "github_token": "t"}, frozenset({"testclient"}))
    scheduler, backend, ha, _, _ = build(store, settings=s, now=2_000)
    scheduler.github = GithubApi("token")  # GitHub ist eingerichtet
    make_task(store, next_run=1_000)
    run_tick(scheduler)
    names = [t.name for t in backend.calls[0]["tools"]]
    assert "ha_get_state" in names and "memory_list" in names and "file_create" in names and "web_fetch" in names
    forbidden = {"ha_call_service", "ha_save_config", "ha_delete_config", "ha_ws", "ha_save_dashboard", "memory_save", "memory_forget"}
    assert not forbidden & set(names), forbidden & set(names)
    assert not [n for n in names if n.startswith("github_") and n in {"github_commit_files", "github_create_pr", "github_create_issue", "github_create_repo", "github_comment", "github_merge_pr"}]
    assert any(n.startswith("github_") for n in names)  # lesende GitHub-Werkzeuge sind da
    levels = {t.level for t in backend.calls[0]["tools"] if t.name.startswith(("ha_", "github_", "memory_"))}
    assert levels <= {"read"}


def test_task_without_web_and_without_rights(store):
    s = parse_settings({**RAW, "ha_access_default": "none"}, frozenset({"testclient"}))
    scheduler, backend, _, _, _ = build(store, settings=s, now=2_000)
    make_task(store, next_run=1_000, web=False)
    run_tick(scheduler)
    names = [t.name for t in backend.calls[0]["tools"]]
    assert not [n for n in names if n.startswith("ha_")] and "web_fetch" not in names and "file_create" in names


def test_missed_task_is_caught_up_or_skipped(store):
    scheduler, backend, _, _, clock = build(store, now=1_000 + 600)
    soon = make_task(store, next_run=1_000)
    assert run_tick(scheduler) == 1  # 10 Minuten zu spät: wird nachgeholt
    assert store.schedule_get("adm01", soon["id"])["last_status"] == "ok"
    scheduler2, backend2, _, _, _ = build(store, now=1_000 + GRACE_SECONDS + 5)
    late = make_task(store, next_run=1_000, name="Spät")
    assert run_tick(scheduler2) == 0 and backend2.calls == []
    after = store.schedule_get("adm01", late["id"])
    assert after["last_status"] == "skipped" and "nicht aktiv" in after["last_note"] and after["runs"] == 0
    assert after["next_run"] > 1_000 + GRACE_SECONDS  # nächster regulärer Termin


def test_limit_reached_skips_and_busy_waits(store):
    limits = LimitState(store)
    limits.update({"status": "rejected", "type": "five_hour", "resets_at": int(datetime.now().timestamp()) + 3600, "utilization": 1})
    scheduler, backend, _, _, _ = build(store, limits=limits, now=2_000)
    row = make_task(store, next_run=1_000)
    assert run_tick(scheduler) == 0 and backend.calls == []
    after = store.schedule_get("adm01", row["id"])
    assert after["last_status"] == "skipped" and "Nutzungslimit" in after["last_note"] and after["next_run"] > 2_000
    # ausgelastet: Aufgabe bleibt fällig und läuft später
    limits.update({"status": "allowed", "type": "five_hour"})  # Limit ist wieder frei
    scheduler, backend, _, runs, _ = build(store, now=2_000)
    runs[("x", "1")] = Run(("x", "1"), "", False)
    runs[("x", "2")] = Run(("x", "2"), "", False)
    waiting = make_task(store, next_run=1_000, name="Wartet")
    assert run_tick(scheduler) == 0 and backend.calls == []
    assert store.schedule_get("adm01", waiting["id"])["next_run"] == 1_000
    runs.clear()
    assert run_tick(scheduler) == 1


def test_once_task_runs_once_and_switches_off(store):
    scheduler, _, _, _, _ = build(store, now=2_000)
    row = make_task(store, freq="once", at_time="11:00", days="1969-12-31", next_run=1_000)  # Uhr der Tests steht auf 1970
    assert run_tick(scheduler) == 1
    after = store.schedule_get("adm01", row["id"])
    assert after["enabled"] is False and after["next_run"] is None and after["runs"] == 1
    assert run_tick(scheduler) == 0


def test_error_becomes_visible_answer(store):
    scheduler, _, _, _, _ = build(store, backend=FakeBackend(pieces=(), error="Das Nutzungslimit deines Abos ist erreicht."), now=2_000)
    row = make_task(store, next_run=1_000)
    run_tick(scheduler)
    chat = store.list_chats("adm01")[0]
    answer = store.list_messages("adm01", chat["id"])[-1]
    assert answer["role"] == "assistant" and "konnte nicht ausgeführt werden" in answer["content"] and "Nutzungslimit" in answer["content"]
    after = store.schedule_get("adm01", row["id"])
    assert after["last_status"] == "error" and "Nutzungslimit" in after["last_note"]
    # Teilantwort vor dem Fehler bleibt erhalten
    scheduler, _, _, _, _ = build(store, backend=FakeBackend(pieces=("Anfang ", "Rest"), error="Verbindung weg", fail_after=1), now=2_000)
    row2 = make_task(store, next_run=1_000, name="Teil")
    run_tick(scheduler)
    chat2 = next(c for c in store.list_chats("adm01") if c["schedule_id"] == row2["id"])
    assert store.list_messages("adm01", chat2["id"])[-1]["content"].startswith("Anfang")
    assert store.schedule_get("adm01", row2["id"])["last_status"] == "error"


def test_unknown_profile_is_skipped(store):
    scheduler, backend, _, _, _ = build(store, now=2_000)
    store.sync_profiles(["weg"])
    row = store.schedule_create("weg", FIELDS, 1_000)
    assert run_tick(scheduler) == 0 and backend.calls == []
    assert "nicht mehr eingetragen" in store.schedule_get("weg", row["id"])["last_note"]


def test_disabled_switch_stops_everything(store):
    off = parse_settings({**RAW, "schedules_enabled": False}, frozenset({"testclient"}))
    scheduler, backend, _, _, _ = build(store, settings=off, now=2_000)
    make_task(store, next_run=1_000)
    assert run_tick(scheduler) == 0 and backend.calls == []


def test_manual_run_endpoint(store):
    backend = FakeBackend(("Fertig.",))
    app, client = make_app(store, backend=backend)
    h = as_user(ADM01, True)
    row = client.post("/api/schedules", json=BODY, headers=h).json()
    before = client.get("/api/schedules", headers=as_user(ADM01)).json()[0]["next_run"]

    async def go():
        out = await asgi(app, "POST", f"/api/schedules/{row['id']}/run")
        await app.state.scheduler.idle()
        return out

    out = asyncio.run(go())
    assert out["status"] == 202
    chat_id = jget(out)["chat_id"]
    msgs = store.list_messages("adm01", chat_id)
    assert msgs[-1]["content"] == "Fertig."
    after = client.get("/api/schedules", headers=as_user(ADM01)).json()[0]
    assert after["last_chat_id"] == chat_id and after["last_status"] == "ok" and after["next_run"] == before  # Zeitplan bleibt unberührt
    assert client.post(f"/api/schedules/{row['id']}/run", headers=as_user(DORA, True)).status_code == 404
    # Ergebnis-Chat erscheint in der Chat-Liste mit Kennzeichen
    listed = client.get("/api/chats", headers=as_user(ADM01)).json()
    assert listed[0]["schedule_id"] == row["id"]


def test_manual_run_refused_while_running_or_limit(store):
    app, client = make_app(store)
    h = as_user(ADM01, True)
    row = client.post("/api/schedules", json=BODY, headers=h).json()
    app.state.scheduler.live[row["id"]] = ("adm01", "x")
    assert client.post(f"/api/schedules/{row['id']}/run", headers=h).status_code == 409
    assert client.get("/api/schedules", headers=as_user(ADM01)).json()[0]["running"] is True
    app.state.scheduler.live.clear()
    app.state.scheduler.limits.update({"status": "rejected", "type": "five_hour", "resets_at": int(datetime.now().timestamp()) + 600})
    r = client.post(f"/api/schedules/{row['id']}/run", headers=h)
    assert r.status_code == 429 and "Nutzungslimit" in r.json()["detail"]


# ------------------------------------------------------------- Benachrichtigungen

def notify_calls(ha):
    return [c for c in ha.calls if c["type"] == "call_service" and c["domain"] in ("notify", "persistent_notification")]


def test_notification_in_home_assistant(store):
    scheduler, _, ha, _, _ = build(store, now=2_000)
    row = make_task(store, next_run=1_000, notify="ha")
    run_tick(scheduler)
    (call,) = notify_calls(ha)
    assert call["domain"] == "persistent_notification" and call["service"] == "create"
    data = call["service_data"]
    assert data["title"] == "Morgenbericht" and data["message"].startswith("Ergebnis fertig.") and data["notification_id"] == f"copilot_{row['id']}"


def test_notification_to_phone_with_link(store):
    s = parse_settings(
        {**RAW, "public_enabled": False, "profiles": [{**RAW["profiles"][0], "notify_service": "notify.mobile_app_pixel"}, RAW["profiles"][1]]},
        frozenset({"testclient"}),
    )
    scheduler, _, ha, _, _ = build(store, settings=s, now=2_000)
    make_task(store, next_run=1_000, notify="phone")
    run_tick(scheduler)
    (call,) = notify_calls(ha)
    assert (call["domain"], call["service"]) == ("notify", "mobile_app_pixel") and call["service_data"]["message"] == "Ergebnis fertig."
    assert "data" not in call["service_data"]  # ohne öffentliche Adresse kein Link


def test_only_chat_sends_nothing_and_failures_are_noted(store):
    scheduler, _, ha, _, _ = build(store, now=2_000)
    make_task(store, next_run=1_000)  # notify = chat
    run_tick(scheduler)
    assert notify_calls(ha) == []
    scheduler, _, ha, _, _ = build(store, ha=RecordingHa(fail_notify=True), now=2_000)
    row = make_task(store, next_run=1_000, notify="ha", name="Meldung")
    run_tick(scheduler)
    after = store.schedule_get("adm01", row["id"])
    assert after["last_status"] == "ok" and "Benachrichtigung konnte nicht gesendet" in after["last_note"]
    # Person ohne Dienst: Hinweis statt Absturz
    row2 = make_task(store, next_run=1_000, notify="phone", name="Ohne Dienst")
    run_tick(scheduler)
    assert "kein Benachrichtigungsdienst" in store.schedule_get("adm01", row2["id"])["last_note"]


def test_no_notification_when_run_failed(store):
    scheduler, _, ha, _, _ = build(store, backend=FakeBackend(pieces=(), error="kaputt"), now=2_000)
    make_task(store, next_run=1_000, notify="ha")
    run_tick(scheduler)
    assert notify_calls(ha) == []


def phone_settings(**extra):
    return parse_settings(
        {**RAW, **extra, "profiles": [{**RAW["profiles"][0], "notify_service": "notify.mobile_app_pixel"}, RAW["profiles"][1]]},
        frozenset({"testclient"}),
    )


def test_long_answer_notifies_when_nobody_watches(store, monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "LONG_ANSWER_SECONDS", 0)
    ha = RecordingHa()
    app, _ = make_app(store, phone_settings(), FakeBackend(("Die ", "lange Antwort.")), ha)
    chat = store.create_chat("adm01", "Neuer Chat")

    async def go():
        # Verbindung ist sofort weg: niemand sieht zu
        await asgi(app, "POST", f"/api/chats/{chat['id']}/send", {"content": "Frage"}, hang_up_after=-1)
        for _ in range(100):
            if notify_calls(ha):
                break
            await asyncio.sleep(0.05)

    asyncio.run(go())
    (call,) = notify_calls(ha)
    assert (call["domain"], call["service"]) == ("notify", "mobile_app_pixel")
    assert call["service_data"]["message"] == "Die lange Antwort."


def test_long_answer_stays_quiet_when_watched_short_or_disabled(store, monkeypatch):
    import app.main as main
    chat_text = {"content": "Frage"}

    def scenario(settings, threshold, hang_up):
        monkeypatch.setattr(main, "LONG_ANSWER_SECONDS", threshold)
        ha = RecordingHa()
        app, _ = make_app(store, settings, FakeBackend(("Antwort.",)), ha)
        chat = store.create_chat("adm01", "Neuer Chat")

        async def go():
            await asgi(app, "POST", f"/api/chats/{chat['id']}/send", chat_text, hang_up_after=hang_up)
            await asyncio.sleep(0.3)

        asyncio.run(go())
        return notify_calls(ha)

    assert scenario(phone_settings(), 0, None) == []  # jemand sieht zu
    assert scenario(phone_settings(), 3600, -1) == []  # zu kurz
    assert scenario(phone_settings(notify_long_answers=False), 0, -1) == []  # ausgeschaltet
    assert scenario(SETTINGS, 0, -1) == []  # Person hat keinen Dienst eingetragen


# --------------------------------------------------------------------- Zeitzone

def test_timezone_is_taken_from_home_assistant(store, monkeypatch):
    import os
    import time as _time
    monkeypatch.setenv("TZ", "UTC")
    _time.tzset()
    try:
        scheduler, _, ha, _, _ = build(store)  # echte Uhr
        row = make_task(store, next_run=None, at_time="07:30")
        store.schedule_set_next(row["id"], sched.next_timestamp("daily", "07:30", ""))
        before = store.schedule_get("adm01", row["id"])["next_run"]
        assert datetime.fromtimestamp(before).strftime("%H:%M") == "07:30"  # in UTC
        assert asyncio.run(scheduler.sync_timezone()) is True  # FakeHa meldet Europe/Berlin
        assert os.environ["TZ"] == "Europe/Berlin"
        after = store.schedule_get("adm01", row["id"])["next_run"]
        assert datetime.fromtimestamp(after).strftime("%H:%M") == "07:30"  # jetzt Berliner Zeit
        assert (before - after) % 86400 in (3600, 7200)  # 07:30 Berlin liegt 1 bzw. 2 Stunden vor 07:30 UTC
    finally:
        monkeypatch.undo()
        _time.tzset()


def test_timezone_unavailable_or_unknown_changes_nothing(store, monkeypatch):
    import os
    import time as _time
    from app.ha_client import HaApiError

    class Broken(RecordingHa):
        async def call(self, command):
            raise HaApiError("offline")

    class Odd(RecordingHa):
        async def call(self, command):
            return {"time_zone": "Mars/Olympus"}

    monkeypatch.setenv("TZ", "UTC")
    _time.tzset()
    try:
        scheduler, *_ = build(store, ha=Broken(), now=2_000)
        assert asyncio.run(scheduler.sync_timezone()) is False and os.environ["TZ"] == "UTC"
        scheduler, *_ = build(store, ha=Odd(), now=2_000)
        assert asyncio.run(scheduler.sync_timezone()) is True and os.environ["TZ"] == "UTC"
    finally:
        monkeypatch.undo()
        _time.tzset()
