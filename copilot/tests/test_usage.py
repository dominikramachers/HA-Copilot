"""Seite „Nutzung“: Abo-Limit und Bilder der Person im Monat."""
from datetime import datetime

from fastapi.testclient import TestClient

from app.config import parse_settings
from app.main import build_ingress_app
from conftest import ADM01, DORA, RAW, as_user
from test_github_accounts import FakeChat


def client(store, **options):
    settings = parse_settings({**RAW, **options}, frozenset({"testclient"}))
    return TestClient(build_ingress_app(settings, store, FakeChat()))


def test_usage_without_images_and_limits(store):
    data = client(store).get("/api/usage", headers=as_user(ADM01)).json()
    assert data["limits"] == [] and data["images"] == {"enabled": False, "month": datetime.now().strftime("%Y-%m"), "used": 0, "limit": data["images"]["limit"]}


def test_usage_counts_images_per_person(store):
    app = client(store, openai_api_key="sk-test-abcdefghijklmnop", image_limit_month=5)
    month = datetime.now().strftime("%Y-%m")
    store.image_usage_add("adm01", month)
    store.image_usage_add("adm01", month)
    mine = app.get("/api/usage", headers=as_user(ADM01)).json()["images"]
    other = app.get("/api/usage", headers=as_user(DORA)).json()["images"]
    assert mine["enabled"] is True and mine["used"] == 2 and mine["limit"] == 5
    assert other["used"] == 0


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
