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


# ------------------------------------------------------------------ Geld nur, wo es anfällt; wer gerade aktiv ist

def _spend(store, now):
    store.usage_add("dora", "claude", "m", tokens_in=1000, tokens_out=500, cost_usd=10.0, ts=int(now.timestamp()) - 60)  # Chat über das Abo
    store.usage_add("dora", "openai", "g", kind="image", images=2, cost_usd=0.5, ts=int(now.timestamp()) - 30)  # Bilder kosten wirklich
    store.usage_add("adm01", "openai", "g", tokens_in=100, tokens_out=100, ts=int(now.timestamp()) - 90)


def test_subscription_calls_are_not_counted_as_money(store):
    now = datetime(2026, 11, 18, 12, 0)
    _spend(store, now)
    names = {"adm01": "Admin", "dora": "Dora"}
    billed = usagelib.overview(store, names, "month", 1.0, now)  # API-Schlüssel: der gemeldete Preis ist echtes Geld
    assert billed["total"]["cost"] == 10.5 and billed["total"]["covered"] == 0
    plan = usagelib.overview(store, names, "month", 0.5, now, claude_billed=False)  # Abo: nur die Bilder, der Rest ist ein Rechenwert
    dora = next(p for p in plan["people"] if p["id"] == "dora")
    assert dora["cost"] == 0.25 and dora["covered"] == 5.0 and plan["total"]["cost"] == 0.25 and plan["total"]["covered"] == 5.0


def test_overview_endpoint_knows_about_the_subscription(store):
    store.usage_add("dora", "claude", "m", tokens_in=2_000_000, tokens_out=0, cost_usd=10.0)
    store.usage_add("dora", "openai", "g", kind="image", images=1, cost_usd=0.2)
    app = client(store, admins={ADM01}, chat={"claude_oauth_token": "sk-ant-oat01-" + "x" * 40})
    data = app.get("/api/usage/all?range=month", headers=as_user(ADM01)).json()
    dora = next(p for p in data["people"] if p["id"] == "dora")
    assert data["subscription"] is True and dora["cost"] == 0.18 and dora["covered"] == 9.2 and data["total"]["covered"] == 9.2
    keyed = client(store, admins={ADM01}, chat={"anthropic_api_key": "sk-ant-api03-" + "x" * 40})
    data = keyed.get("/api/usage/all?range=month", headers=as_user(ADM01)).json()
    assert data["subscription"] is False and next(p for p in data["people"] if p["id"] == "dora")["cost"] == 9.38


def test_last_activity_comes_from_calls_and_chats(store):
    assert store.last_activity() == {}
    store.usage_add("dora", "claude", "m", ts=1_700_000_000)
    chat = store.create_chat("dora", "Hallo", None)["id"]
    store.add_message(chat, "dora", "user", "Hi")
    seen = store.last_activity()
    assert seen["dora"] >= int(time.time()) - 5  # die Chat-Änderung ist jünger als der alte Aufruf
    data = usagelib.overview(store, {"adm01": "Admin", "dora": "Dora"}, "month", 1.0)
    assert next(p for p in data["people"] if p["id"] == "adm01")["last_active"] == 0
    assert next(p for p in data["people"] if p["id"] == "dora")["last_active"] == seen["dora"]
    assert "Hi" not in str(data)  # nur Zeitpunkte, nie Inhalte


def test_overview_shows_who_is_working_right_now(store):
    import asyncio
    from test_background_run import SlowBackend, asgi, jget, new_chat, until  # noqa: PLC0415

    profiles = [{"id": "adm01", "label": "Admin", "ha_user_id": ADM01, "admin": True}, {"id": "dora", "label": "Dora", "ha_user_id": DORA}]
    app = build_ingress_app(parse_settings({**RAW, "profiles": profiles}, frozenset({"testclient"})), store, SlowBackend(hold=True))

    async def scenario():
        chat = jget(await asgi(app, "POST", "/api/chats", {}, user=DORA))["id"]
        post = asyncio.create_task(asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Hallo KI"}, user=DORA, hang_up_after=1))

        async def working():
            people = jget(await asgi(app, "GET", "/api/usage/all", user=ADM01))["people"]
            return next(p for p in people if p["id"] == "dora")["active"] == 1

        await until(working)
        people = jget(await asgi(app, "GET", "/api/usage/all", user=ADM01))["people"]
        dora = next(p for p in people if p["id"] == "dora")
        assert dora["active"] == 1 and dora["waiting"] == 0 and dora["last_active"] > 0
        assert next(p for p in people if p["id"] == "adm01")["active"] == 0
        assert "Hallo KI" not in json_text(people)  # keine Inhalte
        post.cancel()

    def json_text(value):
        import json
        return json.dumps(value, ensure_ascii=False)

    asyncio.run(scenario())
