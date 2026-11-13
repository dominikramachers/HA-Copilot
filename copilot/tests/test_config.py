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

    from conftest import nest_options

    def real(raw, peers=None):  # das Format der Konfiguration (Gruppen), ohne die Kurznamen der Tests
        return parse_settings.__wrapped__(nest_options(raw), peers)
    s = real({
        **RAW,
        "chat": {"model": "claude-opus-5-5", "memory_enabled": False, "schedules_enabled": False, "files_enabled": False,
                 "connector_access_default": "own"},
        "images": {"openai_api_key": "sk-o", "google_api_key": "g-k", "provider": "google", "limit_month": 7},
    }, frozenset())
    assert (s.model, s.memory_enabled, s.schedules_enabled, s.files_enabled) == ("claude-opus-5-5", False, False, False)
    assert s.connector_access_default == "own"
    assert (s.openai_api_key, s.google_api_key, s.image_provider, s.image_limit_month) == ("sk-o", "g-k", "google", 7)

    # Ohne Gruppen gelten die Standardwerte, und die früheren flachen Einträge werden nicht mehr gelesen
    plain = parse_settings.__wrapped__({"users": {"profiles": RAW["profiles"]}, "model": "claude-opus-5-5", "image_limit_month": 0, "google_api_key": "x", "memory_enabled": False}, frozenset())
    assert plain.model == "claude-sonnet-5-5" and plain.image_limit_month == 30 and plain.google_api_key == "" and plain.memory_enabled

    for name in ("chat", "images", "voice"):
        with pytest.raises(ConfigError, match="Gruppe"):
            real({**RAW, name: "nein"}, frozenset())
    for bad in ({"images": {"limit_month": -1}}, {"images": {"provider": "bing"}}, {"chat": {"model": "!"}}):
        with pytest.raises(ConfigError):
            real({**RAW, **bad}, frozenset())


def test_shipped_defaults_parse_to_the_documented_defaults():
    import pathlib, yaml

    config = yaml.safe_load((pathlib.Path(__file__).parent.parent / "config.yaml").read_text(encoding="utf-8"))
    options = {**config["options"], "users": {**config["options"]["users"], "profiles": RAW["profiles"]}}
    s = parse_settings.__wrapped__(options, frozenset())
    from app.config import MOVED, MOVED_DEFAULTS
    for group, keys in MOVED.items():  # die Standardwerte im Code stimmen mit config.yaml überein
        for key in keys:
            assert config["options"][group][key] == MOVED_DEFAULTS[key], key
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


OLD_OPTIONS = {  # so sah options.json vor 0.54.0 aus
    "profiles": [{"label": "Admin", "ha_user": "admin"}], "all_ha_users": True,
    "claude_oauth_token": "sk-ant-oat01-x", "claude_token_expires": "2028-10-26", "ha_access_default": "write",
    "public_base_url": "https://ai.example.org", "entra_tenant_id": "d84fc380-4b25-44f7-8a03-7b9f6c792430",
    "entra_client_id": "e0bd5722-44be-4d8d-8990-0a87e0c667c0", "entra_client_secret": "geheim", "public_trusted_proxies": ["10.0.0.3"],
    "app_name": "Aria", "language": "en",
    "chat": {"model": "claude-opus-5-5"}, "images": {"provider": "auto"},
}


def _new_defaults():
    import pathlib, yaml, copy
    config = yaml.safe_load((pathlib.Path(__file__).parent.parent / "config.yaml").read_text(encoding="utf-8"))
    return copy.deepcopy(config["options"])


def _write(path, data):
    import json
    path.write_text(json.dumps(data), encoding="utf-8")


def test_old_values_are_taken_over_after_the_regrouping(tmp_path):
    from app.config import load_settings, BACKUP_NAME
    options = tmp_path / "options.json"
    _write(tmp_path / BACKUP_NAME, OLD_OPTIONS)  # Sicherung aus dem Start vor dem Update
    _write(options, _new_defaults())  # der Supervisor hat die alten Einträge verworfen: alles steht auf Standard
    s = load_settings(options)
    assert s.profiles[0].label == "Admin" and s.all_ha_users and s.claude_oauth_token == "sk-ant-oat01-x"
    assert s.ha_access_default == "write" and s.public_base_url == "https://ai.example.org" and s.app_name == "Aria" and s.language == "en"
    assert "look.app_name" in s.migrated_options and "chat.claude_oauth_token" in s.migrated_options
    assert "chat.model" not in s.migrated_options  # nicht verschoben, kommt aus der Gruppe selbst
    again = load_settings(options)  # auch beim nächsten Start gelten die alten Werte, solange nichts eingetragen ist
    assert again.app_name == "Aria" and again.migrated_options == s.migrated_options


def test_values_entered_in_the_new_groups_win_and_end_the_takeover(tmp_path):
    from app.config import load_settings, BACKUP_NAME
    options = tmp_path / "options.json"
    _write(tmp_path / BACKUP_NAME, OLD_OPTIONS)
    new = _new_defaults()
    new["look"]["app_name"] = "Neu"
    new["users"]["profiles"] = [{"label": "Neu", "ha_user": "neu"}]
    _write(options, new)
    s = load_settings(options)
    assert s.app_name == "Neu" and s.profiles[0].label == "Neu"  # eigener Eintrag gilt
    assert "look.app_name" not in s.migrated_options and "users.profiles" not in s.migrated_options
    assert s.language == "en"  # was nicht überschrieben wurde, kommt weiter aus der alten Konfiguration
    # Wer später wieder den Standardnamen einträgt, bekommt ihn auch (keine Wiederkehr des alten Werts)
    new["look"]["app_name"] = "HA Copilot"
    _write(options, new)
    assert load_settings(options).app_name == "HA Copilot"


def test_takeover_is_silent_without_a_backup(tmp_path):
    from app.config import load_settings
    options = tmp_path / "options.json"
    new = _new_defaults()
    new["users"]["profiles"] = [{"label": "Admin", "ha_user": "admin"}]
    _write(options, new)
    s = load_settings(options)
    assert s.migrated_options == () and s.app_name == "HA Copilot"
