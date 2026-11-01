"""Name, Logo, Farben und eigenes CSS aus Konfiguration und addon_config-Ordner; Theme-Übernahme aus Home Assistant."""
import asyncio
import copy
import json

import pytest
import websockets
from fastapi.testclient import TestClient

from app.branding import MAX_ASSET_BYTES, Branding
from app.config import ConfigError, parse_settings
from app.ha_client import HaApi, HaApiError
from app.main import build_ingress_app
from app.theme import build_theme_css, mix, on_color, overrides, theme_variables

from conftest import DORA, RAW, as_user

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
THEMES = {
    "default_theme": "doralab",
    "default_dark_theme": None,
    "themes": {
        "doralab": {
            "primary-color": "#175CD3",
            "card-background-color": "#ffffff",
            "modes": {"dark": {"primary-color": "#5B9BFF", "card-background-color": "#14213A"}},
            "dl-extra": "1px solid red",
        },
        "other": {"primary-color": "#ff0000"},
    },
}


def settings_with(**extra):
    raw = copy.deepcopy(RAW)
    raw.update(extra)
    return parse_settings(raw, frozenset({"testclient"}))


class FakeThemes(HaApi):
    def __init__(self, themes):
        super().__init__("t", "ws://x")
        self.data = themes
        self.calls = 0

    async def call(self, command):
        self.calls += 1
        if self.data is None:
            raise HaApiError("offline")
        return self.data


def make(store, backend, tmp_path, ha=None, **extra):
    settings = settings_with(**extra)
    branding = Branding(tmp_path, settings, ha)
    return TestClient(build_ingress_app(settings, store, backend, branding=branding, ha=ha)), settings


# ----------------------------------------------------------------------------- Konfiguration


def test_defaults_are_neutral():
    s = parse_settings(copy.deepcopy(RAW))
    assert s.app_name == "HA Copilot" and s.follow_ha_theme is True and s.logo_tile is False and s.colors == ()


def test_texts_are_cleaned_and_limited():
    s = settings_with(app_name="  Haus   KI ", login_text="Hallo\nWelt", login_placeholder="x@y.de")
    assert (s.app_name, s.login_text, s.login_placeholder) == ("Haus KI", "Hallo Welt", "x@y.de")
    for bad in ({"app_name": "A" * 41}, {"app_name": "<b>"}, {"login_text": "x" * 121}):
        with pytest.raises(ConfigError):
            settings_with(**bad)


def test_colours_are_normalised_and_validated():
    s = settings_with(accent_color="175cd3", background_color_dark="#0d192d")
    assert dict(s.colors) == {"accent": "#175CD3", "bg_dark": "#0D192D"}
    for bad in ("rot", "#12345", "#12345G", "url(x)", "#1234567"):
        with pytest.raises(ConfigError):
            settings_with(accent_color=bad)


def test_profiles_need_only_a_name():
    s = settings_with(profiles=[{"label": "Chef Müller", "entra_upn": "Chef@Example.org"}, {"label": "Platzhalter"}])
    assert [p.id for p in s.profiles] == ["chef-mueller", "platzhalter"]
    assert s.profiles[0].entra_upn == "chef@example.org"
    assert s.profiles[1].ha_user_id == "" and s.profiles[1].entra_upn == ""


def test_profile_ids_stay_unique_and_valid():
    s = settings_with(profiles=[{"label": "Anna", "entra_upn": "a@x.de"}, {"label": "Anna", "entra_upn": "b@x.de"}])
    assert [p.id for p in s.profiles] == ["anna", "anna-2"]
    with pytest.raises(ConfigError):
        settings_with(profiles=[{"id": "Böse!", "label": "X", "entra_upn": "a@x.de"}])
    with pytest.raises(ConfigError):
        settings_with(profiles=[{"label": "A", "ha_user_id": "1" * 32}, {"label": "B", "ha_user_id": "1" * 32}])


# ------------------------------------------------------------------------------- Dateien


def test_default_logo_and_icon_are_served(store, backend, tmp_path):
    api, _ = make(store, backend, tmp_path)
    for url in ("/branding/logo", "/branding/logo-full", "/branding/icon", "/favicon.ico"):
        r = api.get(url)
        assert r.status_code == 200 and r.content[:4] == b"\x89PNG", url


def test_own_logo_replaces_the_default_everywhere(store, backend, tmp_path):
    (tmp_path / "logo.png").write_bytes(PNG + b"A")
    api, _ = make(store, backend, tmp_path)
    assert api.get("/branding/logo").content.endswith(b"A")
    assert api.get("/branding/logo-full").content.endswith(b"A")  # ohne logo-full dient logo
    assert api.get("/branding/icon").content.endswith(b"A")
    (tmp_path / "logo-full.png").write_bytes(PNG + b"B")
    (tmp_path / "icon.png").write_bytes(PNG + b"C")
    assert api.get("/branding/logo-full").content.endswith(b"B") and api.get("/branding/icon").content.endswith(b"C")
    assert api.get("/branding/logo").content.endswith(b"A")


def test_svg_logo_is_allowed_but_not_as_home_screen_icon(store, backend, tmp_path):
    (tmp_path / "logo.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    api, _ = make(store, backend, tmp_path)
    r = api.get("/branding/logo")
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert api.get("/branding/icon").content[:4] == b"\x89PNG"  # Symbole müssen PNG sein: Standard bleibt


def test_oversized_or_empty_or_linked_files_are_ignored(store, backend, tmp_path):
    (tmp_path / "logo.png").write_bytes(PNG + b"x" * MAX_ASSET_BYTES)
    (tmp_path / "logo-full.png").write_bytes(b"")
    target = tmp_path.parent / "secret.png"
    target.write_bytes(PNG + b"SECRET")
    (tmp_path / "icon.png").symlink_to(target)
    api, _ = make(store, backend, tmp_path)
    for url in ("/branding/logo", "/branding/logo-full", "/branding/icon"):
        assert b"SECRET" not in api.get(url).content and len(api.get(url).content) < MAX_ASSET_BYTES


def test_missing_branding_folder_is_fine(store, backend, tmp_path):
    api, _ = make(store, backend, tmp_path / "gibt-es-nicht")
    assert api.get("/branding/logo").status_code == 200 and api.get("/branding/custom.css").text == ""


def test_custom_css_is_served_and_limited(store, backend, tmp_path):
    api, _ = make(store, backend, tmp_path)
    assert api.get("/branding/custom.css").text == ""
    (tmp_path / "custom.css").write_text(":root { --accent: hotpink; }", encoding="utf-8")
    r = api.get("/branding/custom.css")
    assert r.headers["content-type"].startswith("text/css") and "hotpink" in r.text and r.headers["cache-control"] == "no-cache"
    (tmp_path / "custom.css").write_text("a{}" + " " * (300 * 1024))
    assert api.get("/branding/custom.css").text == ""


def test_branding_routes_need_no_login_and_ignore_paths(store, backend, tmp_path):
    api, _ = make(store, backend, tmp_path)
    (tmp_path.parent / "geheim.txt").write_text("nein")
    assert api.get("/branding/../geheim.txt").status_code in (404, 400)
    assert api.get("/branding/geheim.txt").status_code == 404


# --------------------------------------------------------------------------------- Seiten


def test_name_and_texts_appear_in_pages_and_manifest(store, backend, tmp_path):
    api, _ = make(store, backend, tmp_path, app_name="Haus & Hof KI", logo_tile=True, follow_ha_theme=False)
    page = api.get("/", headers=as_user(DORA)).text
    assert "Haus &amp; Hof KI" in page and "__NAME__" not in page
    assert 'data-logo-tile="true"' in page and 'data-follow-ha="false"' in page
    manifest = api.get("/branding/manifest.webmanifest").json()
    assert manifest["name"] == "Haus & Hof KI" and manifest["icons"][0]["type"] == "image/png"
    assert api.get("/api/me", headers=as_user(DORA)).json()["app_name"] == "Haus & Hof KI"


def test_login_preview_uses_configured_texts(store, backend, tmp_path):
    api, _ = make(store, backend, tmp_path, app_name="Zuhause", login_text="Willkommen daheim.", login_placeholder="du@zuhause.de")
    page = api.get("/login", headers=as_user(DORA)).text
    assert "Willkommen daheim." in page and 'placeholder="du@zuhause.de"' in page and "Zuhause" in page


def test_injected_app_name_cannot_break_out(store, backend, tmp_path):
    with pytest.raises(ConfigError):
        settings_with(app_name='"><script>alert(1)</script>')


# ---------------------------------------------------------------------------------- Theme


def test_mix_and_contrast_helpers():
    assert mix("#000000", "#FFFFFF", 0.5) in ("#808080", "#7F7F7F")
    assert on_color("#FFFFFF") == "#0A1120" and on_color("#175CD3") == "#FFFFFF"


def test_theme_variables_follow_default_theme_and_modes():
    s = settings_with()
    light = theme_variables(THEMES, s, "light")
    dark = theme_variables(THEMES, s, "dark")
    assert light["primary-color"] == "#175CD3" and dark["primary-color"] == "#5B9BFF"
    assert dark["card-background-color"] == "#14213A" and light["dl-extra"] == "1px solid red"
    assert "modes" not in light


def test_dark_default_theme_and_named_theme():
    themes = {**THEMES, "default_dark_theme": "other"}
    assert theme_variables(themes, settings_with(), "dark")["primary-color"] == "#ff0000"
    assert theme_variables(themes, settings_with(), "light")["primary-color"] == "#175CD3"
    assert theme_variables(THEMES, settings_with(theme_name="other"), "light") == {"primary-color": "#ff0000"}
    assert theme_variables(THEMES, settings_with(theme_name="gibt-es-nicht"), "light") == {}
    assert theme_variables({"default_theme": "default", "themes": {}}, settings_with(), "light") == {}
    assert theme_variables(None, settings_with(), "light") == {}


def test_theme_values_are_sanitised():
    evil = {"default_theme": "t", "themes": {"t": {
        "good-one": "#123456",
        "bad url": "red",
        "has-url": "url(https://evil.example/x.png)",
        "has-brace": "red; } body { display:none",
        "has-comment": "red/*x*/}",
        "Upper": "blue",
        "number": 5,
        "x" * 80: "red",
    }}}
    result = theme_variables(evil, settings_with(), "light")
    assert result == {"good-one": "#123456"}


def test_overrides_beat_the_theme_and_derive_related_colours():
    s = settings_with(accent_color="#FF8800", text_color_dark="#EEEEEE", background_color_dark="#101010")
    dark = overrides(s, "dark")
    assert dark["ov-accent"] == "#FF8800" and dark["ov-on-accent"] == "#FFFFFF"
    assert dark["ov-text"] == "#EEEEEE" and dark["ov-bg"] == "#101010" and dark["ov-text-2"].startswith("#")
    assert "ov-text" not in overrides(s, "light") and overrides(s, "light")["ov-accent"] == "#FF8800"


def test_theme_css_layers_and_modes():
    css = build_theme_css(THEMES, settings_with(accent_color="#FF8800"))
    assert css.startswith("@layer tokens {")
    assert ':root[data-theme="light"]' in css and ':root[data-theme="dark"]' in css
    assert "--primary-color: #175CD3;" in css and "--primary-color: #5B9BFF;" in css and "--ov-accent: #FF8800;" in css


def test_theme_css_without_ha_or_following_off():
    assert "Keine Theme-Anpassung" in build_theme_css(None, settings_with())
    off = build_theme_css(THEMES, settings_with(follow_ha_theme=False, accent_color="#FF8800"))
    assert "--primary-color" not in off and "--ov-accent: #FF8800;" in off


def test_theme_route_uses_ha_and_caches(store, backend, tmp_path):
    ha = FakeThemes(THEMES)
    api, _ = make(store, backend, tmp_path, ha=ha)
    r = api.get("/branding/theme.css")
    assert r.status_code == 200 and "--primary-color: #175CD3;" in r.text and r.headers["etag"]
    api.get("/branding/theme.css")
    assert ha.calls == 1  # kurz zwischengespeichert, Home Assistant wird nicht bei jedem Aufruf gefragt


def test_theme_route_survives_unreachable_ha(store, backend, tmp_path):
    api, _ = make(store, backend, tmp_path, ha=FakeThemes(None), accent_color="#FF8800")
    r = api.get("/branding/theme.css")
    assert r.status_code == 200 and "--ov-accent: #FF8800;" in r.text and "--primary-color" not in r.text


# ----------------------------------------------------------------- HA-Anbindung (WebSocket)


def fake_ha(responses, token="good"):
    async def handler(ws):
        await ws.send(json.dumps({"type": "auth_required"}))
        auth = json.loads(await ws.recv())
        if auth.get("access_token") != token:
            await ws.send(json.dumps({"type": "auth_invalid"}))
            return
        await ws.send(json.dumps({"type": "auth_ok"}))
        command = json.loads(await ws.recv())
        reply = responses.get(command["type"])
        if reply is None:
            await ws.send(json.dumps({"id": command["id"], "type": "result", "success": False, "error": {"code": "unknown_command"}}))
        else:
            await ws.send(json.dumps({"id": command["id"], "type": "result", "success": True, "result": reply}))
    return handler


def with_server(responses, body, token="good"):
    async def main():
        async with websockets.serve(fake_ha(responses, token), "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            return await body(port)
    return asyncio.run(main())


def test_ha_client_reads_users_and_persons():
    responses = {
        "person/list": {"storage": [{"name": "Anna", "user_id": "A" * 32}], "config": []},
        "config/auth/list": [
            {"id": "a" * 32, "name": "anna", "system_generated": False, "is_active": True},
            {"id": "b" * 32, "name": "Bob", "system_generated": False, "is_active": True},
            {"id": "c" * 32, "name": "Supervisor", "system_generated": True, "is_active": True},
        ],
    }

    async def body(port):
        return await HaApi("good", f"ws://127.0.0.1:{port}").users()

    users = with_server(responses, body)
    assert [(u["id"], u["person"], u["name"]) for u in users] == [("a" * 32, "Anna", "anna"), ("b" * 32, "", "Bob")]


def test_ha_client_falls_back_to_persons_when_user_list_is_forbidden():
    responses = {"person/list": {"storage": [{"name": "Anna", "user_id": "a" * 32}], "config": [{"name": "Zed", "user_id": "z" * 32}]}}

    async def body(port):
        return await HaApi("good", f"ws://127.0.0.1:{port}").users()

    users = with_server(responses, body)
    assert [u["person"] for u in users] == ["Anna", "Zed"]


def test_ha_client_reads_themes():
    async def body(port):
        return await HaApi("good", f"ws://127.0.0.1:{port}").themes()

    assert with_server({"frontend/get_themes": THEMES}, body)["default_theme"] == "doralab"


def test_ha_client_errors_are_contained():
    async def wrong_token(port):
        with pytest.raises(HaApiError):
            await HaApi("bad", f"ws://127.0.0.1:{port}").call({"type": "person/list"})
        assert await HaApi("bad", f"ws://127.0.0.1:{port}").themes() is None
        with pytest.raises(HaApiError):
            await HaApi("good", f"ws://127.0.0.1:{port}").users()  # weder Personen noch Benutzer abrufbar

    with_server({}, wrong_token)

    async def unreachable():
        with pytest.raises(HaApiError):
            await HaApi("t", "ws://127.0.0.1:1", timeout=1).call({"type": "x"})
        assert not HaApi("", "ws://x").enabled
        with pytest.raises(HaApiError):
            await HaApi("", "ws://x").call({"type": "x"})

    asyncio.run(unreachable())
