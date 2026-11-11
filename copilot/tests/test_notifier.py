"""Meldung aufs Handy, wenn eine Antwort ungelesen bleibt: Schonfrist, „Chat offen“, Geräte, Entfernen beim Lesen."""
import asyncio

import pytest
from fastapi.testclient import TestClient

import app.notifier as notifierlib
from app.main import build_ingress_app
from conftest import ADM01, DORA, FakeBackend, as_user
from test_background_run import asgi
from test_schedules import RecordingHa, SETTINGS


class PhoneHa(RecordingHa):
    """Home Assistant mit vier Geräten: Pixel (Admin), Sinas Handy (Dora), ein Tablet und ein Gerät ohne Person.

    Der Admin hat über seine Person nur das Pixel; das Tablet ordnet ``adm01.own("tablet")`` ihm zu.
    """

    def __init__(self):
        super().__init__()
        self.services = {"notify": {"mobile_app_pixel": {}, "mobile_app_tablet": {}, "mobile_app_sinas_handy": {}, "mobile_app_ohne_person": {}, "send_message": {}, "notify": {}}}
        self.persons = [
            {"user_id": ADM01, "device_trackers": ["device_tracker.pixel"]},
            {"user_id": DORA, "device_trackers": ["device_tracker.sinas_handy"]},
        ]

    def give_tablet_to_admin(self):
        self.persons[0]["device_trackers"].append("device_tracker.tablet")

    async def call(self, command):
        if command["type"] == "get_services":
            return self.services
        if command["type"] == "person/list":
            return {"storage": self.persons, "config": []}
        return await super().call(command)

    def sent(self):
        return [c for c in self.calls if c["type"] == "call_service" and c["domain"] == "notify"]


def build(store, ha=None, delay=0):
    ha = ha or PhoneHa()
    app = build_ingress_app(SETTINGS, store, FakeBackend(("Die ", "Antwort.")), ha=ha)
    notifier = notifierlib.notifier_for(store, SETTINGS, ha)
    notifier.delay = delay
    return app, TestClient(app), notifier, ha


def profile():
    return SETTINGS.profiles[0]


def unread_chat(store):
    chat = store.create_chat("adm01", "Heizplan")
    store.add_message("adm01", chat["id"], "assistant", "Antwort.")
    return chat["id"]


def run(coro):
    return asyncio.run(coro)


def test_unread_answer_nobody_watches_is_announced_to_the_own_device(store):
    _, _, notifier, ha = build(store)
    chat = unread_chat(store)
    assert run(notifier.announce(profile(), chat, "Die Heizung läuft jetzt.")) is True
    (call,) = ha.sent()
    assert call["service"] == "mobile_app_pixel"  # nur das Gerät seiner Person
    data = call["service_data"]
    assert data["title"] == "Heizplan"  # Chat-Titel oben, darunter die Antwort
    assert data["message"] == "Die Heizung läuft jetzt."
    assert data["data"]["tag"] == f"copilot-{chat}"


def test_nothing_is_sent_when_the_chat_is_open_somewhere(store):
    _, _, notifier, ha = build(store)
    chat = unread_chat(store)
    notifier.presence.seen("adm01", "laptop", chat)
    assert run(notifier.announce(profile(), chat, "Text")) is False
    notifier.presence.seen("adm01", "laptop", None)  # Tab zu
    notifier.presence.seen("adm01", "tablet", "anderer-chat")  # anderer Chat zählt nicht
    assert run(notifier.announce(profile(), chat, "Text")) is True and len(ha.sent()) == 1


def test_presence_expires_without_heartbeat():
    now = [100.0]
    presence = notifierlib.Presence(clock=lambda: now[0])
    presence.seen("adm01", "laptop", "c1")
    assert presence.watching("adm01", "c1") and not presence.watching("dora", "c1")
    now[0] += notifierlib.PRESENCE_TTL + 1
    assert not presence.watching("adm01", "c1")


def test_nothing_is_sent_when_read_during_the_grace_period(store):
    _, _, notifier, ha = build(store, delay=0.05)
    chat = unread_chat(store)

    async def go():
        task = asyncio.ensure_future(notifier.announce(profile(), chat, "Text"))
        await asyncio.sleep(0.01)
        store.set_chat_unread("adm01", chat, False)  # irgendwo gelesen
        return await task

    assert run(go()) is False and ha.sent() == []


def test_nothing_is_sent_when_switched_off_or_without_devices(store):
    _, _, notifier, ha = build(store)
    chat = unread_chat(store)
    notifier.save(profile(), False, [])
    assert run(notifier.announce(profile(), chat, "Text")) is False
    notifier.save(profile(), True, [])
    ha.persons = []  # keine eigenen Geräte, kein notify_service
    assert run(notifier.announce(profile(), chat, "Text")) is False and ha.sent() == []


def test_chosen_devices_win_and_all_of_them_are_notified(store):
    _, _, notifier, ha = build(store)
    chat = unread_chat(store)
    ha.give_tablet_to_admin()
    assert run(notifier.announce(profile(), chat, "Text")) is True
    assert sorted(c["service"] for c in ha.sent()) == ["mobile_app_pixel", "mobile_app_tablet"]  # ohne Auswahl: alle eigenen Geräte
    ha.calls.clear()
    notifier.save(profile(), True, ["notify.mobile_app_tablet", "notify.send_message", "x"])  # Fremdes wird nicht gespeichert
    assert run(notifier.announce(profile(), chat, "Text")) is True
    assert [c["service"] for c in ha.sent()] == ["mobile_app_tablet"]


def test_foreign_devices_never_get_a_notification_even_if_stored(store):
    _, _, notifier, ha = build(store)
    chat = unread_chat(store)
    notifier.save(profile(), True, ["notify.mobile_app_sinas_handy", "notify.mobile_app_ohne_person"])
    assert run(notifier.selected(profile())) == []
    assert run(notifier.announce(profile(), chat, "Text")) is False and ha.sent() == []


def test_notify_service_of_the_profile_is_the_default(store):
    _, _, notifier, ha = build(store)
    import dataclasses
    with_service = dataclasses.replace(profile(), notify_service="notify.mobile_app_ohne_person")
    assert run(notifier.selected(with_service)) == ["notify.mobile_app_ohne_person"]  # vom Administrator eingetragen: gehört dazu
    ha.give_tablet_to_admin()
    assert run(notifier.selected(profile())) == ["notify.mobile_app_pixel", "notify.mobile_app_tablet"]


def test_notification_is_cleared_when_the_chat_is_read(store):
    app, client, notifier, ha = build(store)
    chat = unread_chat(store)
    run(notifier.announce(profile(), chat, "Text"))
    ha.calls.clear()
    out = client.patch(f"/api/chats/{chat}", json={"unread": False}, headers=as_user(ADM01, True))
    assert out.status_code == 200
    run(notifier.idle())
    (call,) = ha.sent()
    assert call["service_data"] == {"message": "clear_notification", "data": {"tag": f"copilot-{chat}"}}
    client.patch(f"/api/chats/{chat}", json={"unread": False}, headers=as_user(ADM01, True))
    run(notifier.idle())
    assert len(ha.sent()) == 1  # nur einmal entfernt


def test_api_lists_only_the_own_devices_and_saves_the_choice(store):
    _, client, notifier, ha = build(store)
    ha.give_tablet_to_admin()
    h = as_user(ADM01, True)
    first = client.get("/api/notify", headers=h).json()
    assert first["enabled"] is True
    rows = {d["service"]: d for d in first["devices"]}
    assert set(rows) == {"notify.mobile_app_pixel", "notify.mobile_app_tablet"}  # nicht Sinas Handy, nicht das Gerät ohne Person
    assert all(d["selected"] for d in rows.values())
    saved = client.put("/api/notify", json={"enabled": True, "devices": ["notify.mobile_app_tablet"]}, headers=h).json()
    assert [d["service"] for d in saved["devices"] if d["selected"]] == ["notify.mobile_app_tablet"]
    for foreign in ("notify.mobile_app_sinas_handy", "notify.mobile_app_ohne_person", "notify.mobile_app_nope"):
        assert client.put("/api/notify", json={"enabled": True, "devices": [foreign]}, headers=h).status_code == 422
    assert client.put("/api/notify", json={"enabled": True, "devices": []}).status_code in (401, 403)  # ohne Schutzkopf
    # Dora sieht nur ihr eigenes Gerät und kann das des Admins nicht wählen
    dora = client.get("/api/notify", headers=as_user(DORA)).json()
    assert [d["service"] for d in dora["devices"]] == ["notify.mobile_app_sinas_handy"]
    assert client.put("/api/notify", json={"enabled": True, "devices": ["notify.mobile_app_pixel"]}, headers=as_user(DORA, True)).status_code == 422


def test_presence_endpoint_marks_the_chat_as_open(store):
    _, client, notifier, _ = build(store)
    h = as_user(ADM01, True)
    assert client.post("/api/presence", json={"client": "laptop-1", "chat_id": "c1"}, headers=h).status_code == 204
    assert notifier.presence.watching("adm01", "c1") and not notifier.presence.watching("dora", "c1")
    client.post("/api/presence", json={"client": "laptop-1", "chat_id": None}, headers=h)
    assert not notifier.presence.watching("adm01", "c1")
    assert client.post("/api/presence", json={"client": "bad id!", "chat_id": "c1"}, headers=h).status_code == 422


def test_finished_answer_notifies_when_nobody_watches(store, monkeypatch):
    monkeypatch.setattr(notifierlib, "NOTIFY_DELAY_SECONDS", 0)
    ha = PhoneHa()
    app = build_ingress_app(SETTINGS, store, FakeBackend(("Die ", "Antwort.")), ha=ha)
    chat = store.create_chat("adm01", "Neuer Chat")

    async def go():
        await asgi(app, "POST", f"/api/chats/{chat['id']}/send", {"content": "Frage"}, hang_up_after=-1)  # Verbindung sofort weg
        for _ in range(100):
            if ha.sent():
                break
            await asyncio.sleep(0.05)

    asyncio.run(go())
    (call,) = ha.sent()
    assert call["service_data"]["message"] == "Die Antwort." and call["service_data"]["title"] == "Frage"  # Titel aus der ersten Frage


def test_finished_answer_stays_quiet_when_someone_follows_it(store, monkeypatch):
    monkeypatch.setattr(notifierlib, "NOTIFY_DELAY_SECONDS", 0)
    ha = PhoneHa()
    app = build_ingress_app(SETTINGS, store, FakeBackend(("Antwort.",)), ha=ha)
    chat = store.create_chat("adm01", "Neuer Chat")

    async def go():
        await asgi(app, "POST", f"/api/chats/{chat['id']}/send", {"content": "Frage"}, hang_up_after=None)  # jemand sieht zu
        await asyncio.sleep(0.3)

    asyncio.run(go())
    assert ha.sent() == []


def test_scheduled_task_uses_the_chosen_devices(store):
    app, _, notifier, ha = build(store)
    ha.give_tablet_to_admin()
    notifier.save(profile(), True, ["notify.mobile_app_tablet"])
    scheduler = app.state.scheduler
    assert run(scheduler.notify(profile(), "phone", "Bericht", "Text")) is None
    assert [c["service"] for c in ha.sent()] == ["mobile_app_tablet"]


def test_setup_check_shows_the_own_phone_from_home_assistant_without_notify_service(store):
    _, client, _, _ = build(store)
    items = {i["id"]: i for i in client.get("/api/setup", headers=as_user(ADM01)).json()["items"]}
    assert items["notify"]["status"] == "ok" and "Pixel" in items["notify"]["detail"] and "Tablet" not in items["notify"]["detail"]
    other = {i["id"]: i for i in client.get("/api/setup", headers=as_user(DORA)).json()["items"]}
    assert "Sinas handy" in other["notify"]["detail"] and "Pixel" not in other["notify"]["detail"]
