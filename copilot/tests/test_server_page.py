"""Server-Seite (ab 0.63.0): Skript bleibt abrufbar, Schlüssel zeigen ihre Server, Hinweis aufs Handy bei wartendem Server."""
import asyncio

import pytest
from fastapi.testclient import TestClient

import app.notifier as notifierlib
from app import servers as serverlib
from app.config import parse_settings
from app.db import Store
from app.main import build_ingress_app
from conftest import ADM01, DORA, RAW, WRITE, FakeBackend
from test_notifier import PhoneHa
from test_servers import Who, api, enroll, make_hub, start  # noqa: F401  (api ist eine Fixture)


def create_script(admin, **body):
    response = admin.post("/api/servers/install-script", json=body or {"name": "web01"}, headers=WRITE)
    assert response.status_code == 200
    return response.json()


# ----------------------------------------------------------------------------------------- Skript erneut abrufen

def test_a_script_can_be_fetched_again_while_its_key_is_valid(api):
    client, store, cfg = api
    admin = Who(client, ADM01)
    created = create_script(admin)
    key = next(k for k in admin.get("/api/servers").json()["keys"] if k["id"] == created["key_id"])
    assert key["active"] and key["has_script"] and key["servers"] == []
    again = admin.get(f"/api/servers/keys/{created['key_id']}/script")
    assert again.status_code == 200 and again.headers["cache-control"] == "no-store"
    assert again.json()["script"] == created["script"] and again.json()["key_id"] == created["key_id"] and again.json()["uses"] == 1


def test_a_script_is_gone_when_its_key_is_revoked_used_up_or_after_a_restart(api):
    client, store, cfg = api
    admin = Who(client, ADM01)
    hub = serverlib.hub_for(store, cfg)
    revoked = create_script(admin)
    assert admin.delete(f"/api/servers/keys/{revoked['key_id']}", headers=WRITE).status_code == 200
    gone = admin.get(f"/api/servers/keys/{revoked['key_id']}/script")
    assert gone.status_code == 404 and "nicht mehr abrufbar" in gone.json()["detail"]

    used = create_script(admin, name="db01")
    key = next(line.split("=", 1)[1] for line in used["script"].splitlines() if line.startswith("KEY="))
    assert hub.repo.key_consume(key)  # die einzige Anmeldung ist verbraucht
    assert admin.get(f"/api/servers/keys/{used['key_id']}/script").status_code == 404

    kept = create_script(admin, name="app01")
    hub._scripts.clear()  # Neustart des Add-ons: der Arbeitsspeicher ist leer
    overview = admin.get("/api/servers").json()["keys"]
    assert next(k for k in overview if k["id"] == kept["key_id"]) == {**next(k for k in overview if k["id"] == kept["key_id"]), "active": True, "has_script": False}
    assert admin.get(f"/api/servers/keys/{kept['key_id']}/script").status_code == 404


def test_nobody_without_access_can_fetch_a_script(api):
    client, store, cfg = api
    created = create_script(Who(client, ADM01))
    assert Who(client, DORA).get(f"/api/servers/keys/{created['key_id']}/script").status_code == 403


def test_the_script_cache_is_limited(tmp_path):
    hub = make_hub(tmp_path)
    ids = []
    for n in range(serverlib.SCRIPT_CACHE_MAX + 5):
        key_id, _, expires = hub.repo.key_create("Admin", f"k{n}", 24, 1)
        hub.script_remember(key_id, f"script {n}", "install.sh", expires, 1)
        ids.append(key_id)
    assert len(hub._scripts) == serverlib.SCRIPT_CACHE_MAX
    assert hub.script_get(ids[0]) is None and hub.script_get(ids[-1])["script"] == f"script {len(ids) - 1}"


def test_keys_list_the_servers_that_registered_with_them(api):
    client, store, cfg = api
    admin = Who(client, ADM01)
    hub = serverlib.hub_for(store, cfg)
    key_id, _, _ = hub.repo.key_create("Admin", "Test", 24, 2)
    hub.repo.server_create("srv-1", "web01", "aa" * 32, key_id)
    entry = next(k for k in admin.get("/api/servers").json()["keys"] if k["id"] == key_id)
    assert entry["servers"] == [{"id": "srv-1", "name": "web01", "state": "pending"}]
    hub.repo.server_state("srv-1", "active")
    assert next(k for k in admin.get("/api/servers").json()["keys"] if k["id"] == key_id)["servers"][0]["state"] == "active"


# ----------------------------------------------------------------------------------------- Hinweis bei wartendem Server

def test_enrolling_reports_the_new_server_and_its_key_to_the_hook(tmp_path):
    async def scenario():
        hub = make_hub(tmp_path)
        seen = []

        async def pending(server, key):
            seen.append((server["name"], key["created_by"]))
        hub.on_pending = pending
        task = await start(hub)
        try:
            _, key, _ = hub.repo.key_create("Admin", "Test", 24, 1)
            reply, _ = await enroll(hub, key, hostname="web01")
            assert reply["t"] == "enrolled"
            await asyncio.sleep(0.2)  # der Hinweis folgt, nachdem die Antwort an den Agenten raus ist
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return seen
    assert asyncio.run(scenario()) == [("web01", "Admin")]


def test_a_failing_hook_does_not_break_the_enrollment(tmp_path):
    async def scenario():
        hub = make_hub(tmp_path)

        async def broken(server, key):
            raise RuntimeError("kaputt")
        hub.on_pending = broken
        task = await start(hub)
        try:
            _, key, _ = hub.repo.key_create("Admin", "Test", 24, 1)
            reply, _ = await enroll(hub, key)
            await asyncio.sleep(0.2)
            return reply["t"], hub.repo.server_get(reply["server_id"])["state"]
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert asyncio.run(scenario()) == ("enrolled", "pending")


@pytest.fixture
def phone_app(tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.SERVER_DIR", tmp_path / "servers")
    cfg = parse_settings({
        **RAW,
        "profiles": [{**RAW["profiles"][0], "server_access": "on"}, RAW["profiles"][1]],
        "servers": {"enabled": True, "hub_address": "ha.example.lan"},
    }, frozenset({"testclient"}))
    store = Store(tmp_path / "db.sqlite3")
    store.sync_profiles(p.id for p in cfg.profiles)
    ha = PhoneHa()
    build_ingress_app(cfg, store, FakeBackend(), ha=ha)
    notifier = notifierlib.notifier_for(store, cfg, ha)
    notifier.delay = 0
    return cfg, store, ha, notifier, serverlib.hub_for(store, cfg)


def run_hook(hub, notifier, created_by):
    async def go():
        await hub.on_pending({"id": "srv-1", "name": "web01"}, {"created_by": created_by})
        await notifier.idle()
    asyncio.run(go())


def test_the_person_who_made_the_script_gets_a_phone_notice(phone_app):
    cfg, store, ha, notifier, hub = phone_app
    run_hook(hub, notifier, cfg.profiles[0].label or cfg.profiles[0].id)
    (call,) = ha.sent()
    assert call["service"] == "mobile_app_pixel"
    data = call["service_data"]
    assert data["title"] == "Neuer Server wartet auf Bestätigung" and "web01" in data["message"] and data["data"]["tag"] == "copilot-server-srv-1"


def test_nothing_is_sent_while_the_person_has_the_app_open(phone_app):
    cfg, store, ha, notifier, hub = phone_app
    notifier.presence.seen(cfg.profiles[0].id, "laptop", "view:servers")
    run_hook(hub, notifier, cfg.profiles[0].label or cfg.profiles[0].id)
    assert ha.sent() == []
    notifier.presence.seen(cfg.profiles[0].id, "laptop", None)  # Tab zu
    run_hook(hub, notifier, cfg.profiles[0].label or cfg.profiles[0].id)
    assert len(ha.sent()) == 1


def test_an_unknown_creator_notifies_everybody_with_server_access(phone_app):
    cfg, store, ha, notifier, hub = phone_app
    run_hook(hub, notifier, "Jemand, den es nicht mehr gibt")
    assert [c["service"] for c in ha.sent()] == ["mobile_app_pixel"]  # Dora hat keinen Serverzugriff


def test_without_a_phone_the_notice_goes_to_home_assistant(phone_app):
    cfg, store, ha, notifier, hub = phone_app
    ha.persons = []
    texts = []

    async def notify(title, message):
        texts.append((title, message))
    hub.notify = notify
    run_hook(hub, notifier, cfg.profiles[0].label or cfg.profiles[0].id)
    assert ha.sent() == [] and texts and "web01" in texts[0][1]


def test_switched_off_notices_send_nothing_at_all(phone_app):
    cfg, store, ha, notifier, hub = phone_app
    notifier.save(cfg.profiles[0], False, [])
    texts = []

    async def notify(title, message):
        texts.append(title)
    hub.notify = notify
    run_hook(hub, notifier, cfg.profiles[0].label or cfg.profiles[0].id)
    assert ha.sent() == [] and texts == []  # wer Meldungen ausgeschaltet hat, bekommt auch keine Ersatzmeldung


# ----------------------------------------------------------------------------------------- Anwesenheit

def test_presence_counts_any_open_page_and_expires():
    now = [100.0]
    presence = notifierlib.Presence(clock=lambda: now[0])
    assert not presence.active("adm01")
    presence.seen("adm01", "laptop", "view:servers")
    assert presence.active("adm01") and not presence.active("dora")
    assert not presence.watching("adm01", "ein-chat")  # eine Seite ist kein Chat
    now[0] += notifierlib.PRESENCE_TTL + 1
    assert not presence.active("adm01")


# ----------------------------------------------------------------------------------------- Meldungen in Home Assistant (0.63.1)

def test_home_assistant_notices_of_the_hub_are_off_by_default():
    assert parse_settings({**RAW}).server_ha_notifications is False
    assert parse_settings({**RAW, "servers": {"enabled": True}}).server_ha_notifications is False
    assert parse_settings({**RAW, "servers": {"enabled": True, "ha_notifications": True}}).server_ha_notifications is True
    with pytest.raises(Exception, match="ha_notifications"):
        parse_settings({**RAW, "servers": {"ha_notifications": "ja"}})


def test_the_hub_only_writes_to_the_home_assistant_bell_when_switched_on():
    from app.main import hub_notifier
    ha = PhoneHa()
    assert hub_notifier(parse_settings({**RAW, "servers": {"enabled": True}}), ha) is None
    notify = hub_notifier(parse_settings({**RAW, "servers": {"enabled": True, "ha_notifications": True}}), ha)
    assert notify is not None
    asyncio.run(notify("Server web01 ist offline", "Text"))
    (call,) = [c for c in ha.calls if c.get("domain") == "persistent_notification"]
    assert call["service"] == "create" and call["service_data"]["title"] == "Server web01 ist offline"


def test_an_offline_server_is_still_logged_but_not_announced_without_the_option(tmp_path):
    hub = make_hub(tmp_path)
    hub.repo.server_create("srv-1", "web01", "ff" * 32, "k")
    hub.repo.server_state("srv-1", "active")
    hub.notify = None  # Standard: keine Meldung in Home Assistant
    hub.status_of = lambda row: ("online", {})
    asyncio.run(hub.check_online())  # erste Beobachtung
    hub.status_of = lambda row: ("offline", {})
    asyncio.run(hub.check_online())
    assert any("offline" in e["summary"].lower() for e in hub.repo.audit_list(kind="event"))
