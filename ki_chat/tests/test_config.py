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


def test_subscription_token_shared_warning():
    from app.main import subscription_shared
    one = {**RAW, "profiles": [RAW["profiles"][0]]}
    assert not subscription_shared(parse_settings({**one, "claude_oauth_token": "t"}, frozenset()))  # eine Person: in Ordnung
    assert subscription_shared(parse_settings({**RAW, "claude_oauth_token": "t"}, frozenset()))  # mehrere Personen
    assert subscription_shared(parse_settings({**one, "claude_oauth_token": "t", "all_ha_users": True}, frozenset()))
    assert not subscription_shared(parse_settings({**RAW, "claude_oauth_token": "t", "anthropic_api_key": "k"}, frozenset()))  # API-Schlüssel
    assert not subscription_shared(parse_settings({**RAW}, frozenset()))  # kein Token
