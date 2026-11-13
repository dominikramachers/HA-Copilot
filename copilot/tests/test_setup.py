"""Einrichtungsprüfung: Zeilen, genaue Schritte, Abfragen bei Home Assistant und GitHub, Schnittstelle."""
import asyncio
import copy

import httpx
import pytest
from fastapi.testclient import TestClient

from app import setup_check as sc
from app.config import parse_settings
from app.github_api import GithubApi
from app.ha_client import HaApi, HaApiError
from app.main import build_ingress_app, build_public_app
from app.ops import Health

from conftest import ADM01, RAW, as_user, parse_with_fixed
from test_domain import BASE, CLIENT, TENANT, WRITE_PUBLIC

TOKEN = "ghp_geheimes_token_123"
ABO = "sk-ant-oat01-geheimes-abo-token"
KEY = "sk-ant-api03-geheimer-schluessel"


def make(**extra):
    raw = copy.deepcopy(RAW)
    raw.update(extra)
    return parse_with_fixed(raw, frozenset({"testclient"}))


def rows(settings, profile=None, **kw):
    defaults = dict(ha_enabled=True, github_enabled=False, ha_level="read", github_level="none", hostname="abc-copilot")
    defaults.update(kw)
    items = sc.static_items(settings, profile or settings.profiles[0], **defaults)
    return {i["id"]: i for i in items}


# ------------------------------------------------- Claude


def test_test_mode_is_required_and_names_the_exact_options():
    claude = rows(make(backend="echo"))["claude"]
    assert claude["level"] == "required" and claude["status"] == "todo"
    steps = " ".join(claude["steps"])
    for needed in ("claude setup-token", "claude_oauth_token", "anthropic_api_key", "Neustart", "Konfiguration"):
        assert needed in steps
    assert sc.banner(make(backend="echo")) and sc.banner(make(backend="claude", claude_oauth_token=ABO)) is None


def test_claude_ok_names_the_billing_path_without_showing_secrets():
    abo = rows(make(backend="claude", claude_oauth_token=ABO))["claude"]
    assert abo["status"] == "ok" and "Abo" in abo["detail"] and ABO not in str(abo)
    key = rows(make(backend="claude", claude_oauth_token=ABO, anthropic_api_key=KEY))["claude"]
    assert "API-Schlüssel" in key["detail"] and KEY not in str(key) and ABO not in str(key)


def test_subscription_token_with_several_people_gets_no_warning_row():
    assert "claude_terms" not in rows(make(backend="claude", claude_oauth_token=ABO))  # zwei Profile
    assert not hasattr(sc, "subscription_shared")


def test_required_items_come_first():
    items = sc.static_items(make(backend="echo"), make().profiles[0], ha_enabled=True, github_enabled=False, ha_level="read", github_level="none")
    levels = [i["level"] for i in items]
    assert levels == sorted(levels, key=sc.LEVEL_ORDER.get) and items[0]["id"] == "claude"


# ------------------------------------------------- Datenbank, Home Assistant, Benutzer


def test_database_problem_is_a_required_row():
    assert "database" not in rows(make())
    row = rows(make(), db_problem="Die Datenbank ist beschädigt.")["database"]
    assert row["level"] == "required" and row["status"] == "todo" and "restore_snapshot" in " ".join(row["steps"])


def test_missing_home_assistant_connection_explains_what_is_lost():
    row = rows(make(), ha_enabled=False)["ha"]
    assert row["status"] == "todo" and row["steps"] and "ha_access" not in rows(make(), ha_enabled=False)


def test_unresolved_ha_users_are_named():
    settings = make(profiles=[{"label": "Anna", "ha_user": "anna"}, {"label": "Bert", "ha_user_id": ADM01}])
    pending = [p for p in settings.profiles if p.ha_user and not p.ha_user_id]
    row = rows(settings, pending_users=pending)["ha_users"]
    assert row["status"] == "warn" and "Anna" in row["detail"] and "ha_user_id" in " ".join(row["steps"])


@pytest.mark.parametrize("level,expected", [("none", "off"), ("read", "ok"), ("write", "ok")])
def test_ha_access_row_follows_the_level(level, expected):
    row = rows(make(), ha_level=level)["ha_access"]
    assert row["status"] == expected
    if level == "none":
        assert "ha_access_default" in " ".join(row["steps"])
    else:
        assert "Assist" in row["detail"]  # Hinweis auf die Freigabe von Entitäten


# ------------------------------------------------- Bilder


def test_image_rows():
    off = rows(make())["images"]
    assert off["status"] == "off" and "SVG" in off["detail"] and "openai_api_key" in " ".join(off["steps"]) and "Abo reicht dafür nicht" in " ".join(off["steps"])
    ok = rows(make(openai_api_key="sk-geheim", google_api_key="g-geheim", image_limit_month=12))["images"]
    assert ok["status"] == "ok" and "OpenAI + Google" in ok["detail"] and "12 Bilder" in ok["detail"] and "geheim" not in str(ok)
    assert "kein Monatslimit" in rows(make(openai_api_key="sk-x", image_limit_month=0))["images"]["detail"]
    assert "images" not in rows(make(images_enabled=False))


# ------------------------------------------------- GitHub


def test_github_rows():
    off = rows(make())["github"]  # jede Person darf ihr eigenes Konto verbinden, nichts muss freigegeben werden
    assert off["status"] == "off" and "Mit GitHub verbinden" in " ".join(off["steps"]) and "github_access" not in " ".join(off["steps"])
    assert "eigenes Konto" in off["detail"] or "Jede Person" in off["detail"]
    ok = rows(make(), github_enabled=True, github_level="write")["github"]
    assert ok["status"] == "ok" and "schreiben" in ok["detail"] and "eigenes GitHub-Konto" in ok["detail"] and TOKEN not in str(ok)


def test_live_github_rejection_asks_to_reconnect():
    items = list(rows(make(), github_enabled=True, github_level="read").values())
    api = GithubApi(TOKEN, transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"message": "Bad credentials"})), personal=True)
    asyncio.run(sc.run_live(items, None, api, make().profiles[0]))
    github = next(i for i in items if i["id"] == "github")
    assert github["status"] == "todo" and "Einstellungen" in " ".join(github["steps"]) and "github_token" not in " ".join(github["steps"])


def github_api(status, body=None):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/user"
        return httpx.Response(status, json=body or {})
    return GithubApi(TOKEN, transport=httpx.MockTransport(handler))


def test_live_github_valid_token_names_the_account():
    items = list(rows(make(), github_enabled=True, github_level="read").values())
    asyncio.run(sc.run_live(items, None, github_api(200, {"login": "doralab"}), make().profiles[0]))
    github = next(i for i in items if i["id"] == "github")
    assert github["status"] == "ok" and "doralab" in github["detail"] and TOKEN not in str(github)


def test_live_github_unreachable_does_not_turn_red():
    items = list(rows(make(), github_enabled=True, github_level="read").values())
    asyncio.run(sc.run_live(items, None, github_api(502), make().profiles[0]))
    github = next(i for i in items if i["id"] == "github")
    assert github["status"] == "ok" and "nicht geprüft" in github["detail"]


# ------------------------------------------------- Domain


def test_domain_off_lists_the_steps_with_the_hostname():
    row = rows(make())["domain"]
    assert row["status"] == "off"
    steps = " ".join(row["steps"])
    assert "abc-copilot:8100" in steps and "public_base_url" in steps and "/auth/callback" in steps


def domain_settings(**extra):
    return make(
        public_enabled=True, public_base_url=BASE, entra_tenant_id=TENANT, entra_client_id=CLIENT,
        entra_client_secret="geheim", **extra,
    )


def test_domain_on_without_trusted_proxy_names_the_seen_address():
    found = rows(domain_settings(), public_peers=["172.30.33.5"])
    assert found["domain"]["status"] == "ok" and "abc-copilot:8100" in found["domain"]["detail"]
    warn = found["domain_proxies"]
    assert warn["status"] == "warn" and warn["level"] == "recommended" and "172.30.33.5" in " ".join(warn["steps"])
    nothing_seen = rows(domain_settings())["domain_proxies"]
    assert "Anmeldeseite einmal" in " ".join(nothing_seen["steps"])
    assert "domain_proxies" not in rows(domain_settings(public_trusted_proxies=["172.30.33.5"]))


# ------------------------------------------------- Benachrichtigungen, Ablaufdaten


def test_notify_rows_name_the_per_person_setup_not_the_config():
    waiting = rows(make())["notify"]
    assert waiting["status"] == "off" and "Personen" in " ".join(waiting["steps"]) and "Benachrichtigungen" in " ".join(waiting["steps"])
    assert "notify_service" not in " ".join(waiting["steps"]) + waiting["detail"]
    assert rows(make(), ha_enabled=False)["notify"]["detail"].startswith("Braucht die Verbindung")


class FakeNotifier:
    available = True

    def __init__(self, devices, enabled=True):
        self.state = {"enabled": enabled, "devices": devices}

    async def devices(self, profile):
        return self.state


def live_notify(settings, notifier):
    items = list(rows(settings).values())
    asyncio.run(sc.run_live(items, None, None, settings.profiles[0], None, notifier))
    return next(i for i in items if i["id"] == "notify")


def test_live_notify_lists_the_devices_home_assistant_assigns_to_the_person():
    pixel = {"service": "notify.mobile_app_pixel", "label": "Pixel", "selected": True}
    ipad = {"service": "notify.mobile_app_ipad", "label": "Ipad", "selected": False}
    ok = live_notify(make(), FakeNotifier([pixel, ipad]))
    assert ok["status"] == "ok" and "Pixel" in ok["detail"] and "Ipad" not in ok["detail"] and ok["steps"] == []
    none = live_notify(make(), FakeNotifier([]))
    assert none["status"] == "off" and "Personen" in " ".join(none["steps"])
    muted = live_notify(make(), FakeNotifier([pixel], enabled=False))
    assert muted["status"] == "off" and "ausgeschaltet" in muted["detail"] and "Einstellungen" in " ".join(muted["steps"])


def test_live_notify_warns_about_a_stale_notify_service_override():
    settings = make(profiles=[{**RAW["profiles"][0], "notify_service": "notify.mobile_app_alt"}])
    gone = live_notify(settings, FakeNotifier([{"service": "notify.mobile_app_pixel", "label": "Pixel", "selected": True}]))
    assert gone["status"] == "warn" and "notify.mobile_app_alt" in gone["detail"] and gone["steps"]


class FakeHa(HaApi):
    def __init__(self, config=None, services=None, error=None):
        super().__init__("t", "ws://x")
        self.answers = {"get_config": config, "get_services": services}
        self.error = error
        self.asked = []

    async def call(self, command, timeout=None):
        self.asked.append(command["type"])
        if self.error:
            raise self.error
        return self.answers[command["type"]]


def test_live_ha_reports_version():
    settings = make()
    profile = settings.profiles[0]
    good = FakeHa({"location_name": "Zuhause", "version": "2026.10.1"}, {"notify": {"mobile_app_pixel": {}}})
    items = list(rows(settings).values())
    asyncio.run(sc.run_live(items, good, None, profile))
    ha = next(i for i in items if i["id"] == "ha")
    assert ha["status"] == "ok" and "Zuhause" in ha["detail"] and "2026.10.1" in ha["detail"]


def test_live_ha_failure_becomes_a_warning_with_steps():
    items = list(rows(make()).values())
    asyncio.run(sc.run_live(items, FakeHa(error=HaApiError("get_config: TimeoutError")), None, make().profiles[0]))
    ha = next(i for i in items if i["id"] == "ha")
    assert ha["status"] == "warn" and ha["steps"] and "TimeoutError" in ha["detail"]


class VoiceHa:
    """Nur das, was die Sprach-Zeile abfragt: was die bevorzugte Assist-Pipeline kann."""

    def __init__(self, stt=False, tts=False, stt_down=False, tts_down=False):
        self.engines = {"stt": stt, "tts": tts, "stt_down": stt_down, "tts_down": tts_down}

    async def pipeline_engines(self):
        return self.engines


def voice_row(settings, ha):
    items = list(rows(settings).values())
    asyncio.run(sc.run_live(items, ha, None, settings.profiles[0], settings))
    return next(i for i in items if i["id"] == "voice")


def test_voice_row_names_the_recognition_and_voice_really_used():
    on = {"voice": {"access_default": "on"}}
    local = voice_row(make(**on), VoiceHa(stt=True, tts=True))
    assert local["status"] == "ok" and "Home Assistant" in local["detail"] and "Stimme des Geräts" in local["detail"]
    served = voice_row(make(voice={"access_default": "on", "output": "service"}), VoiceHa(stt=True, tts=True))
    assert "Stimme: Home Assistant" in served["detail"]
    no_tts = voice_row(make(voice={"access_default": "on", "output": "service"}), VoiceHa(stt=True))
    assert "keine Sprachausgabe" in no_tts["detail"]
    key = voice_row(make(voice={"access_default": "on", "openai_api_key": "sk-geheim"}), VoiceHa())
    assert "OpenAI" in key["detail"] and "geheim" not in str(key)


def test_voice_row_warns_when_nothing_can_recognise_speech():
    settings = make(voice={"access_default": "on", "browser_stt": False})
    row = voice_row(settings, VoiceHa())
    assert row["status"] == "warn" and "Whisper" in " ".join(row["steps"]) and "browser_stt" in " ".join(row["steps"])
    assert voice_row(make(voice={"access_default": "on", "browser_stt": False}), VoiceHa(stt=True))["status"] == "ok"
    browser = voice_row(make(voice={"access_default": "on"}), VoiceHa())  # Browser-Rückfall ist an
    assert browser["status"] == "ok" and "Browser" in browser["detail"]


def test_voice_row_is_left_alone_when_off():
    row = voice_row(make(), VoiceHa(stt=True))
    assert row["status"] == "off" and "Whisper" in " ".join(row["steps"])


def test_expiry_reminder_rows():
    none_set = rows(make(backend="claude", claude_oauth_token=ABO))["expiry"]
    assert none_set["status"] == "off" and "claude_token_expires" in " ".join(none_set["steps"])
    assert rows(make(backend="claude", claude_oauth_token=ABO, claude_token_expires="2027-10-01"))["expiry"]["status"] == "ok"
    assert "expiry" not in rows(make(backend="claude", anthropic_api_key=KEY))  # API-Schlüssel läuft nicht ab
    images = rows(make(backend="claude", anthropic_api_key=KEY, images={"openai_api_key": "sk-x", "google_api_key": "g-x"}))["expiry"]
    assert images["status"] == "off" and "images.openai_key_expires" in " ".join(images["steps"]) and "images.google_key_expires" in " ".join(images["steps"])
    done = rows(make(backend="claude", anthropic_api_key=KEY, images={"openai_api_key": "sk-x", "openai_key_expires": "2027-01-01"}))["expiry"]
    assert done["status"] == "ok"


def test_every_open_row_has_steps_and_no_row_leaks_secrets():
    settings = domain_settings(backend="claude", claude_oauth_token=ABO, anthropic_api_key=KEY)
    items = list(rows(settings, db_problem="kaputt").values())
    asyncio.run(sc.run_live(items, None, None, settings.profiles[0]))
    for item in items:
        if item["status"] in ("todo", "warn"):
            assert item["steps"], item["id"]
    dump = str(items)
    for secret in (TOKEN, ABO, KEY, "geheim"):
        assert secret not in dump
    assert sc.open_count(items) >= 2


def test_peer_log_keeps_the_latest_few():
    log = sc.PeerLog(size=3)
    for peer in ("a", "b", "c", "d", "b", ""):
        log.note(peer)
    assert log.recent() == ["b", "d", "c"]


# ------------------------------------------------- Schnittstelle


@pytest.fixture()
def api(store, backend):
    settings = make(backend="echo")
    return TestClient(build_ingress_app(settings, store, backend, health=Health(settings), ha=FakeHa({"version": "1"}, {})))


def test_setup_endpoint_lists_items_for_the_signed_in_person(api):
    data = api.get("/api/setup", headers=as_user(ADM01)).json()
    assert data["open"] >= 1 and data["items"][0]["id"] == "claude" and data["items"][0]["status"] == "todo"
    assert {i["level"] for i in data["items"]} <= {"required", "recommended", "optional"}
    assert api.get("/api/setup").status_code == 403  # ohne Home-Assistant-Benutzer


def test_me_offers_the_banner_only_in_test_mode(api, store, backend):
    me = api.get("/api/me", headers=as_user(ADM01)).json()
    assert me["setup"] is True and "Testmodus" in me["setup_open"]
    live = make(backend="claude", claude_oauth_token=ABO)
    client = TestClient(build_ingress_app(live, store, backend))
    assert client.get("/api/me", headers=as_user(ADM01)).json()["setup_open"] is None


def test_setup_is_not_available_on_the_domain(store, backend):
    from test_security import public_client

    pub, idp = public_client(store, backend)
    from test_domain import login

    assert login(pub, idp).status_code == 303
    assert pub.get("/api/setup").status_code == 404
    me = pub.get("/api/me").json()
    assert me["setup"] is False and me["setup_open"] is None


def test_domain_login_page_remembers_the_peer_for_the_check(store, backend):
    peers = sc.PeerLog()
    settings = domain_settings()
    import httpx as _httpx
    from app.oidc import EntraClient
    from test_domain import FakeIdp

    idp = FakeIdp()
    entra = EntraClient(TENANT, CLIENT, "geheim", f"{BASE}/auth/callback", _httpx.AsyncClient(transport=_httpx.MockTransport(idp.handler)), "https://idp.test")
    pub = TestClient(build_public_app(settings, store, backend, entra, public_peers=peers), base_url=BASE, follow_redirects=False)
    assert pub.get("/login").status_code == 200
    assert peers.recent() == ["testclient"]


def test_every_option_named_in_the_steps_exists():
    # Die Schritte verweisen auf Optionen; jede genannte Option muss es in der Konfiguration geben.
    import pathlib, re, yaml

    config = yaml.safe_load((pathlib.Path(__file__).parent.parent / "config.yaml").read_text())
    options = set(config["options"]) | set(config["schema"]) | {"ha_user", "ha_user_id", "notify_service", "ha_access", "connector_access", "voice_access"}
    for value in config["schema"].values():  # Felder in den Gruppen (chat, images, voice) heißen für sich
        if isinstance(value, dict):
            options |= set(value)
    settings = domain_settings(backend="echo")
    items = rows(settings, ha_enabled=False, db_problem="x", pending_users=[settings.profiles[0]], github_level="none")
    items.update(rows(make(backend="claude", claude_oauth_token=ABO), github_enabled=True, github_level="none"))
    for item in items.values():
        for text in [item["detail"], *item["steps"]]:
            for name in re.findall(r"`([a-z_]+)`", text):
                if name in {"read", "write", "execute", "none", "claude", "echo", "snapshots", "on", "off"}:
                    continue
                assert name in options, (item["id"], name)


def test_voice_row_warns_when_whisper_or_piper_are_entered_but_not_running():
    on = {"access_default": "on"}
    # Whisper weg, Browser-Rückfall an (Standard): es läuft über den Browser, die Zeile sagt warum und was zu tun ist
    browser = voice_row(make(voice=on), VoiceHa(stt_down=True))
    assert browser["status"] == "warn" and "Browser" in browser["detail"] and "Whisper" in browser["detail"]
    assert any("Whisper" in step for step in browser["steps"])
    # Whisper weg und kein Rückfall: nichts bleibt zum Verstehen
    nothing = voice_row(make(voice={**on, "browser_stt": False}), VoiceHa(stt_down=True))
    assert nothing["status"] == "warn" and "nicht verfügbar" in nothing["detail"] and any("Whisper" in step for step in nothing["steps"])
    # Piper weg bei voice.output: service: das Gerät spricht, die Zeile nennt Piper
    piper = voice_row(make(voice={**on, "output": "service"}), VoiceHa(stt=True, tts_down=True))
    assert piper["status"] == "warn" and "Piper" in piper["detail"] and "Stimme des Geräts" in piper["detail"]
    assert any("Piper" in step for step in piper["steps"])
    # ein OpenAI-Schlüssel ersetzt beides: dann ist nichts zu warnen
    key = voice_row(make(voice={**on, "output": "service", "openai_api_key": "sk-x"}), VoiceHa(stt_down=True, tts_down=True))
    assert key["status"] == "ok" and "OpenAI" in key["detail"]
    # bei voice.output: device spielt Piper keine Rolle
    device = voice_row(make(voice=on), VoiceHa(stt=True, tts_down=True))
    assert device["status"] == "ok"


def test_voice_row_with_nothing_configured_says_what_to_do():
    none = voice_row(make(voice={"access_default": "on", "browser_stt": False}), VoiceHa())
    assert none["status"] == "warn" and len(none["steps"]) == 3 and any("Whisper" in step for step in none["steps"])
