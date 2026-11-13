"""Verbrauchsprotokoll und die Übersicht „Alle Personen“ (nur für Administratoren)."""
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import usage as usagelib
from app.config import parse_settings
from app.ha_client import HaApi
from app.main import build_ingress_app
from conftest import ADM01, DORA, RAW, as_user
from test_github_accounts import FakeChat


class AdminHa(HaApi):
    def __init__(self, admins=()):
        super().__init__("", "ws://x")
        self.admins = frozenset(admins)

    async def admin_ids(self, max_age=300.0):
        return self.admins


def client(store, admins=(), profiles=None, **options):
    raw = {**RAW, **({"profiles": profiles} if profiles else {}), **options}
    settings = parse_settings(raw, frozenset({"testclient"}))
    return TestClient(build_ingress_app(settings, store, FakeChat(), ha=AdminHa(admins)))


def test_ledger_sums_per_person_and_range(store):
    now = datetime(2026, 11, 18, 12, 0)  # Mittwoch
    t = lambda days, hours=0: int((now - timedelta(days=days, hours=hours)).timestamp())  # noqa: E731
    store.usage_add("adm01", "claude", "m", tokens_in=1000, tokens_out=500, cost_usd=0.5, ts=t(0, 1))
    store.usage_add("adm01", "claude", "m", tokens_in=100, tokens_out=100, cost_usd=0.1, ts=t(2))  # Montag
    store.usage_add("dora", "openai", "g", tokens_in=300, tokens_out=100, ts=t(10))  # Anfang des Monats
    store.usage_add("dora", "claude", "", kind="image", images=2, ts=t(0, 2))
    day = usagelib.overview(store, {"adm01": "Admin", "dora": "Dora"}, "today", 0.9, now)
    assert [p["id"] for p in day["people"]] == ["adm01", "dora"]
    assert day["people"][0]["tokens"] == 1500 and day["people"][0]["cost"] == 0.45 and day["people"][1]["images"] == 2
    week = usagelib.overview(store, {"adm01": "Admin", "dora": "Dora"}, "week", 1.0, now)
    assert week["total"]["tokens"] == 1700 and week["total"]["calls"] == 3
    month = usagelib.overview(store, {"adm01": "Admin", "dora": "Dora"}, "month", 1.0, now)
    assert month["total"]["tokens"] == 2100
    assert round(sum(p["share"] for p in month["people"]), 1) == 100.0
    assert usagelib.overview(store, {}, "gibt-es-nicht", 1.0, now)["range"] == "month"


def test_people_without_usage_are_listed(store):
    data = usagelib.overview(store, {"adm01": "Admin", "dora": "Dora"}, "month", 1.0)
    assert {p["id"] for p in data["people"]} == {"adm01", "dora"} and data["total"]["tokens"] == 0


def test_compaction_keeps_the_sums(store):
    old = int(time.time()) - 120 * 86400
    store.usage_add("dora", "claude", "m", tokens_in=10, tokens_out=5, cost_usd=0.2, ts=old)
    store.usage_add("dora", "claude", "m", tokens_in=20, tokens_out=5, cost_usd=0.3, ts=old + 60)
    store.usage_add("dora", "claude", "m", tokens_in=1, tokens_out=1)
    assert usagelib.compact(store) == 2
    day = datetime.fromtimestamp(old).strftime("%Y-%m-%d")
    rows = store.usage_summary(0, int(time.time()) + 10, day, day)
    assert rows[0]["tokens_in"] == 31 and rows[0]["calls"] == 3 and round(rows[0]["cost_usd"], 2) == 0.5
    assert usagelib.compact(store) == 0


def test_report_goes_to_the_bound_person_only(store):
    usagelib.report("claude", "m", 5, 5)  # ohne Bindung: nichts
    with usagelib.bound(store, "dora", "voice"):
        usagelib.report("claude", "m", 7, 3, 0.01)
    usagelib.report("claude", "m", 9, 9)
    rows = store.usage_summary(0, int(time.time()) + 10, "2000-01-01", "2000-01-01")
    assert len(rows) == 1 and rows[0]["profile_id"] == "dora" and rows[0]["tokens_in"] == 7


def test_report_claude_uses_model_usage_and_falls_back():
    seen = []
    with usagelib.bound(SimpleNamespace(usage_add=lambda pid, **kw: seen.append((pid, kw))), "dora"):
        usagelib.report_claude(SimpleNamespace(model_usage={"claude-haiku-5-5": {"inputTokens": 10, "cacheReadInputTokens": 90, "outputTokens": 4, "costUSD": 0.02}}, usage=None, total_cost_usd=0.02))
        usagelib.report_claude(SimpleNamespace(model_usage=None, usage={"input_tokens": 3, "output_tokens": 2}, total_cost_usd=0.01))
    assert seen[0][1]["tokens_in"] == 100 and seen[0][1]["tokens_out"] == 4 and seen[0][1]["model"] == "claude-haiku-5-5"
    assert seen[1][1]["tokens_in"] == 3 and seen[1][1]["cost_usd"] == 0.01


def test_overview_is_admin_only(store):
    app = client(store, admins={ADM01})
    assert app.get("/api/usage/all", headers=as_user(DORA)).status_code == 403
    assert app.get("/api/me", headers=as_user(DORA)).json()["usage_all"] is False
    assert app.get("/api/me", headers=as_user(ADM01)).json()["usage_all"] is True
    store.usage_add("dora", "claude", "m", tokens_in=2_000_000, tokens_out=0, cost_usd=10.0)
    data = app.get("/api/usage/all?range=month", headers=as_user(ADM01)).json()
    dora = next(p for p in data["people"] if p["id"] == "dora")
    assert dora["tokens"] == 2_000_000 and dora["share"] == 100.0 and data["currency"] == "EUR" and dora["cost"] == 9.2


def test_profile_flag_makes_admin_without_home_assistant(store):
    profiles = [{"id": "adm01", "label": "Admin", "ha_user_id": ADM01, "admin": True}, {"id": "dora", "label": "Dora", "ha_user_id": DORA}]
    app = client(store, profiles=profiles)  # keine Administratoren in Home Assistant
    assert app.get("/api/usage/all", headers=as_user(ADM01)).status_code == 200
    assert app.get("/api/usage/all", headers=as_user(DORA)).status_code == 403


def test_nobody_is_admin_without_a_source(store):
    assert client(store).get("/api/usage/all", headers=as_user(ADM01)).status_code == 403


def test_rate_is_validated(store):
    import pytest
    from app.config import ConfigError
    assert parse_settings({**RAW, "chat": {"usd_eur_rate": 0.5}}, frozenset()).usd_eur_rate == 0.5
    for bad in (0, 11, "viel"):
        with pytest.raises(ConfigError):
            parse_settings({**RAW, "chat": {"usd_eur_rate": bad}}, frozenset())
