import copy

import pytest

from app.config import ConfigError, parse_settings
from app.identity import Registry

from conftest import ADM01, DORA, RAW


def test_values_are_normalised():
    raw = copy.deepcopy(RAW)
    raw["profiles"][0]["ha_user_id"] = ADM01.upper()
    raw["profiles"][0]["entra_upn"] = "  ADM01@Example.ORG "
    settings = parse_settings(raw)
    first = settings.profiles[0]
    assert first.ha_user_id == ADM01
    assert first.entra_upn == "adm01@example.org"


def test_registry_lookup_is_case_insensitive():
    registry = Registry(parse_settings(RAW).profiles)
    assert registry.by_ha_user_id(DORA.upper()).id == "dora"
    assert registry.by_upn("DORA@example.org").id == "dora"
    assert registry.by_upn("niemand@example.org") is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw.update(profiles=[]),
        lambda raw: raw["profiles"][1].update(id="adm01"),
        lambda raw: raw["profiles"][1].update(ha_user_id=ADM01),
        lambda raw: raw["profiles"][1].update(entra_upn="ADM01@example.org"),
        lambda raw: raw["profiles"][0].update(id="Ungültig!"),
        lambda raw: raw["profiles"][0].update(ha_user_id="zu-kurz"),
        lambda raw: raw["profiles"][0].update(entra_upn="keine-upn"),
        lambda raw: raw["profiles"][0].pop("label"),
    ],
)
def test_invalid_configuration_is_rejected(mutate):
    raw = copy.deepcopy(RAW)
    mutate(raw)
    with pytest.raises(ConfigError):
        parse_settings(raw)


def test_api_key_option_is_read_and_takes_precedence(tmp_path):
    from app.backend import BackendError, ClaudeSdkBackend
    from app.config import parse_settings
    from conftest import RAW

    assert parse_settings({**RAW, "anthropic_api_key": "  sk-test  "}, frozenset()).anthropic_api_key == "sk-test"
    assert parse_settings(RAW, frozenset()).anthropic_api_key == ""
    both = ClaudeSdkBackend("abo", "m", tmp_path, api_key="sk-test")._options("low").env
    assert both["ANTHROPIC_API_KEY"] == "sk-test" and "CLAUDE_CODE_OAUTH_TOKEN" not in both
    only_token = ClaudeSdkBackend("abo", "m", tmp_path)._options("low").env
    assert only_token["CLAUDE_CODE_OAUTH_TOKEN"] == "abo" and "ANTHROPIC_API_KEY" not in only_token
    import pytest

    with pytest.raises(BackendError):
        ClaudeSdkBackend("", "m", tmp_path)


def test_chat_and_images_are_groups_and_flat_entries_are_ignored():
    import pytest
    from app.config import ConfigError

    real = parse_settings.__wrapped__  # das Format der Konfiguration, ohne die Kurznamen der Tests
    s = real({
        **RAW,
        "chat": {"model": "claude-opus-5-5", "memory_enabled": False, "schedules_enabled": False, "files_enabled": False,
                 "github_access_default": "read", "connector_access_default": "own"},
        "images": {"openai_api_key": "sk-o", "google_api_key": "g-k", "provider": "google", "limit_month": 7},
    }, frozenset())
    assert (s.model, s.memory_enabled, s.schedules_enabled, s.files_enabled) == ("claude-opus-5-5", False, False, False)
    assert (s.github_access_default, s.connector_access_default) == ("read", "own")
    assert (s.openai_api_key, s.google_api_key, s.image_provider, s.image_limit_month) == ("sk-o", "g-k", "google", 7)

    # Ohne Gruppen gelten die Standardwerte, und die früheren flachen Einträge werden nicht mehr gelesen
    plain = real({**RAW, "model": "claude-opus-5-5", "image_limit_month": 0, "google_api_key": "x", "memory_enabled": False}, frozenset())
    assert plain.model == "claude-sonnet-5-5" and plain.image_limit_month == 30 and plain.google_api_key == "" and plain.memory_enabled

    for name in ("chat", "images", "voice"):
        with pytest.raises(ConfigError, match="Gruppe"):
            real({**RAW, name: "nein"}, frozenset())
    for bad in ({"images": {"limit_month": -1}}, {"images": {"provider": "bing"}}, {"chat": {"github_access_default": "admin"}}, {"chat": {"model": "!"}}):
        with pytest.raises(ConfigError):
            real({**RAW, **bad}, frozenset())


def test_shipped_defaults_parse_to_the_documented_defaults():
    import pathlib, yaml

    config = yaml.safe_load((pathlib.Path(__file__).parent.parent / "config.yaml").read_text(encoding="utf-8"))
    s = parse_settings.__wrapped__({**config["options"], "profiles": RAW["profiles"]}, frozenset())
    assert s.model == "claude-sonnet-5-5" and s.memory_enabled and s.schedules_enabled and s.files_enabled
    assert s.image_provider == "auto" and s.image_limit_month == 30 and s.voice_access_default == "off"
    assert list(config["options"]) == list(config["schema"])  # gleiche Reihenfolge in Optionen und Schema


def test_options_backup_is_written_once_and_private(tmp_path):
    import json, stat
    from app.config import load_settings, BACKUP_NAME
    options = tmp_path / "options.json"
    options.write_text(json.dumps({"profiles": [{"label": "Admin"}], "app_name": "Aria"}), encoding="utf-8")
    load_settings(options)
    backup = tmp_path / BACKUP_NAME
    assert json.loads(backup.read_text(encoding="utf-8"))["app_name"] == "Aria"
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    stamp = backup.stat().st_mtime_ns
    load_settings(options)  # unverändert: keine neue Datei
    assert backup.stat().st_mtime_ns == stamp
    options.write_text(json.dumps({"profiles": [{"label": "Admin"}], "app_name": "Neu"}), encoding="utf-8")
    load_settings(options)
    assert json.loads(backup.read_text(encoding="utf-8"))["app_name"] == "Neu"
