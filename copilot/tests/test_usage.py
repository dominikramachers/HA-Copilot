"""Seite „Nutzung“: Abo-Limit sowie Bilder und ChatGPT-Token des Monats (für alle Personen zusammen)."""
from datetime import datetime

from fastapi.testclient import TestClient

from app.config import parse_settings
from app.main import build_ingress_app
from conftest import ADM01, DORA, RAW, WRITE, as_user
from test_github_accounts import FakeChat


def client(store, **options):
    settings = parse_settings({**RAW, **options}, frozenset({"testclient"}))
    return TestClient(build_ingress_app(settings, store, FakeChat()))


def test_usage_without_images_and_limits(store):
    data = client(store).get("/api/usage", headers=as_user(ADM01)).json()
    assert data["limits"] == [] and data["images"] == {"enabled": False, "month": datetime.now().strftime("%Y-%m"), "used": 0, "limit": data["images"]["limit"]}


def test_usage_counts_images_for_everyone_together(store):
    app = client(store, openai_api_key="sk-test-abcdefghijklmnop", image_limit_month=5)
    month = datetime.now().strftime("%Y-%m")
    store.image_usage_add("adm01", month)
    store.image_usage_add("adm01", month)
    store.image_usage_add("dora", month)
    mine = app.get("/api/usage", headers=as_user(ADM01)).json()["images"]
    other = app.get("/api/usage", headers=as_user(DORA)).json()["images"]
    assert mine["enabled"] is True and mine["used"] == 3 and mine["limit"] == 5
    assert other == mine  # jede Person sieht dieselbe Zahl


def test_usage_counts_chatgpt_tokens_for_everyone_together(store):
    app = client(store, openai_enabled=True, openai_api_key="sk-test-abcdefghijklmnop", openai_limit_month=3000)
    month = datetime.now().strftime("%Y-%m")
    store.token_usage_add("adm01", month, 200_000, "openai")
    store.token_usage_add("dora", month, 7_296, "openai")
    store.token_usage_add("dora", month, 9_999, "claude")  # anderer Anbieter zählt nicht mit
    mine = app.get("/api/usage", headers=as_user(ADM01)).json()["openai"]
    other = app.get("/api/usage", headers=as_user(DORA)).json()["openai"]
    assert mine["used"] == 207_296 and mine["limit"] == 3_000_000
    assert other == mine


def test_usage_reports_server_time_for_the_live_display(store):
    import time  # noqa: PLC0415
    data = client(store).get("/api/usage", headers=as_user(ADM01)).json()
    assert abs(data["server_time"] - time.time()) < 5


def test_usage_shows_another_persons_update_without_own_message(store):
    """Der gemeinsame Stand ändert sich, wenn irgendwer eine Antwort bekommt; jede Person sieht ihn beim nächsten Abruf."""
    from app import limits as limitlib  # noqa: PLC0415
    app = client(store, openai_enabled=True, openai_api_key="sk-test-abcdefghijklmnop")
    month = datetime.now().strftime("%Y-%m")
    before = app.get("/api/usage", headers=as_user(DORA)).json()
    assert before["openai"]["used"] == 0 and before["windows"] == []
    store.token_usage_add("adm01", month, 1234, "openai")
    limitlib.shared(store).update({"status": "allowed", "type": "seven_day", "resets_at": 4_000_500_000, "utilization": 0.77})
    after = app.get("/api/usage", headers=as_user(DORA)).json()
    assert after["openai"]["used"] == 1234 and after["windows"][0]["utilization"] == 0.77


def test_usage_needs_a_person(store):
    assert client(store).get("/api/usage").status_code in (401, 403)


def test_usage_lists_the_known_windows(store):
    from app import limits as limitlib  # noqa: PLC0415
    app = client(store)
    limitlib.shared(store).update({"status": "allowed", "type": "five_hour", "resets_at": 4_000_000_000, "utilization": 0.29})
    limitlib.shared(store).update({"status": "allowed", "type": "seven_day", "resets_at": 4_000_500_000, "utilization": 0.11})
    data = app.get("/api/usage", headers=as_user(ADM01)).json()
    assert [w["type"] for w in data["windows"]] == ["five_hour", "seven_day"]
    assert data["windows"][1]["utilization"] == 0.11 and data["limits"] == []


class ProbeChat(FakeChat):
    """Backend mit Abo: meldet bei der Prüfung einen Stand."""

    def __init__(self, subscription=True, fail=False):
        super().__init__()
        self.subscription = subscription
        self.fail = fail
        self.probes = 0

    async def probe_limits(self, on_limit):
        from app.backend import BackendError  # noqa: PLC0415
        self.probes += 1
        if self.fail:
            raise BackendError("Claude ist gerade nicht erreichbar.")
        on_limit({"status": "allowed", "type": "five_hour", "resets_at": 4_000_000_000, "utilization": 0.25})
        return True


def probe_client(store, chat):
    settings = parse_settings(dict(RAW), frozenset({"testclient"}))
    return TestClient(build_ingress_app(settings, store, chat))


def test_usage_refresh_updates_the_shared_state_for_everyone(store):
    chat = ProbeChat()
    app = probe_client(store, chat)
    assert app.get("/api/usage", headers=as_user(DORA)).json()["subscription"] is True
    result = app.post("/api/usage/refresh", headers={**as_user(ADM01), **WRITE}).json()
    assert result["checked"] is True and result["reported"] is True
    # jede Person sieht den neuen Stand, auch ohne selbst geprüft zu haben
    windows = app.get("/api/usage", headers=as_user(DORA)).json()["windows"]
    assert [(w["type"], w["utilization"]) for w in windows] == [("five_hour", 0.25)]


def test_usage_refresh_has_a_shared_cooldown(store):
    chat = ProbeChat()
    app = probe_client(store, chat)
    first = app.post("/api/usage/refresh", headers={**as_user(ADM01), **WRITE}).json()
    second = app.post("/api/usage/refresh", headers={**as_user(DORA), **WRITE}).json()
    assert first["checked"] is True and second["checked"] is False and 0 < second["retry_in"] <= 60
    assert chat.probes == 1  # die zweite Person löst keine weitere Anfrage aus


def test_usage_refresh_is_only_for_the_subscription(store):
    chat = ProbeChat(subscription=False)  # z. B. mit API-Schlüssel: Abrechnung nach Verbrauch, keine Abo-Fenster
    app = probe_client(store, chat)
    assert app.get("/api/usage", headers=as_user(ADM01)).json()["subscription"] is False
    assert app.post("/api/usage/refresh", headers={**as_user(ADM01), **WRITE}).status_code == 409
    assert chat.probes == 0


def test_usage_refresh_failure_is_reported_and_not_rate_limited(store):
    chat = ProbeChat(fail=True)
    app = probe_client(store, chat)
    bad = app.post("/api/usage/refresh", headers={**as_user(ADM01), **WRITE})
    assert bad.status_code == 502 and bad.json()["detail"] == "Claude ist gerade nicht erreichbar."
    chat.fail = False
    assert app.post("/api/usage/refresh", headers={**as_user(ADM01), **WRITE}).json()["checked"] is True  # Fehlversuch sperrt nicht


def test_usage_refresh_needs_the_write_header(store):
    app = probe_client(store, ProbeChat())
    assert app.post("/api/usage/refresh", headers=as_user(ADM01)).status_code in (400, 403)
