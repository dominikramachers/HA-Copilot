"""Persönliche GitHub-Konten: Anmeldung per Device Flow, Token einfügen, verschlüsselte Ablage, kein gemeinsames Token."""
import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import parse_settings
from app.github_accounts import AccountError, GithubAccounts
from app.github_api import GithubApi
from app.main import build_ingress_app
from app.vault import Vault
from conftest import RAW, WRITE

PERSONAL = "gho_persoenliches_token_abcdefghij"
CODE = "geheimer-device-code-xyz"


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class FakeGithub:
    """GitHub: Device Flow (Code, Nachfragen) und /user; merkt sich Aufrufe und Kopfzeilen."""

    def __init__(self):
        self.polls = 0
        self.answers: list[dict] = []  # Antworten auf das Nachfragen, der Reihe nach
        self.start_error: str | None = None
        self.user: dict | tuple = {"login": "dora-gh"}
        self.auth: list[str] = []
        self.sent: list[dict[str, str]] = []

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url.endswith("/login/device/code"):
                form = dict(httpx.QueryParams(request.content.decode()))
                self.sent.append(form)
                if self.start_error:
                    return httpx.Response(200, json={"error": self.start_error})
                return httpx.Response(200, json={"device_code": CODE, "user_code": "ABCD-1234", "verification_uri": "https://github.com/login/device", "expires_in": 900, "interval": 5})
            if url.endswith("/login/oauth/access_token"):
                form = dict(httpx.QueryParams(request.content.decode()))
                self.sent.append(form)
                self.polls += 1
                return httpx.Response(200, json=self.answers.pop(0) if self.answers else {"error": "authorization_pending"})
            if request.url.path == "/user":
                self.auth.append(request.headers.get("authorization", ""))
                if isinstance(self.user, tuple):
                    return httpx.Response(self.user[0], json=self.user[1])
                return httpx.Response(200, json=self.user)
            return httpx.Response(404, json={"message": "Not Found"})
        return httpx.MockTransport(handler)


@pytest.fixture()
def gh():
    return FakeGithub()


@pytest.fixture()
def vault(tmp_path):
    return Vault(tmp_path / "connector.key")


@pytest.fixture()
def clock():
    return FakeClock()


@pytest.fixture()
def accounts(store, vault, gh, clock):
    return GithubAccounts(store, vault, transport=gh.transport(), clock=clock)


def run(coro):
    return asyncio.run(coro)


# ----------------------------------------------------------------------- Device Flow

def test_device_flow_stores_an_encrypted_token(accounts, store, vault, gh, clock):
    started = run(accounts.device_start("dora"))
    assert started["user_code"] == "ABCD-1234" and started["verification_uri"] == "https://github.com/login/device"
    assert CODE not in str(started)  # der Gerätecode bleibt im Add-on
    assert gh.sent[0]["client_id"] and gh.sent[0]["scope"] == "repo"
    assert accounts.info("dora")["pending"] is True and accounts.source("dora") == "none"

    clock.now += 6
    assert run(accounts.device_poll("dora"))["status"] == "pending"
    assert gh.sent[-1]["device_code"] == CODE and gh.sent[-1]["grant_type"] == "urn:ietf:params:oauth:grant-type:device_code"

    gh.answers.append({"access_token": PERSONAL, "token_type": "bearer", "scope": "repo"})
    clock.now += 6
    assert run(accounts.device_poll("dora")) == {"status": "ok", "login": "dora-gh"}
    assert gh.auth[-1] == f"Bearer {PERSONAL}"

    row = store.github_account_get("dora")
    assert row["token"] != PERSONAL and PERSONAL not in str(row) and vault.unseal(row["token"]) == PERSONAL
    assert row["login"] == "dora-gh" and row["via"] == "device"
    api = accounts.api_for("dora")
    assert api.personal and api.enabled and api is not accounts.none
    assert accounts.source("dora") == "personal" and not accounts.policy_for("dora").restricted
    assert accounts.api_for("adm01") is accounts.none and not accounts.api_for("adm01").enabled and not accounts.enabled_for("adm01")
    assert accounts.info("dora")["pending"] is False


def test_polling_too_early_does_not_ask_github(accounts, gh, clock):
    run(accounts.device_start("dora"))
    assert run(accounts.device_poll("dora"))["status"] == "pending" and gh.polls == 0
    clock.now += 6
    run(accounts.device_poll("dora"))
    run(accounts.device_poll("dora"))
    assert gh.polls == 1


def test_slow_down_widens_the_interval(accounts, gh, clock):
    run(accounts.device_start("dora"))
    gh.answers.append({"error": "slow_down", "interval": 10})
    clock.now += 6
    assert run(accounts.device_poll("dora")) == {"status": "pending", "interval": 10}
    clock.now += 6
    run(accounts.device_poll("dora"))
    assert gh.polls == 1  # erst nach 10 Sekunden wieder


@pytest.mark.parametrize("answer,status", [({"error": "access_denied"}, "denied"), ({"error": "expired_token"}, "expired")])
def test_denied_and_expired_end_the_attempt(accounts, gh, clock, answer, status):
    run(accounts.device_start("dora"))
    gh.answers.append(answer)
    clock.now += 6
    assert run(accounts.device_poll("dora"))["status"] == status
    assert run(accounts.device_poll("dora"))["status"] == "none"
    assert accounts.source("dora") == "none"


def test_code_expires_by_the_clock(accounts, clock):
    run(accounts.device_start("dora"))
    clock.now += 901
    assert run(accounts.device_poll("dora"))["status"] == "expired"


def test_device_flow_not_enabled_at_github_is_explained(accounts, gh):
    gh.start_error = "device_flow_disabled"
    with pytest.raises(AccountError, match="Device Flow"):
        run(accounts.device_start("dora"))


def test_cancel_forgets_the_pending_attempt(accounts):
    run(accounts.device_start("dora"))
    accounts.device_cancel("dora")
    assert run(accounts.device_poll("dora"))["status"] == "none"


# ----------------------------------------------------------------------- Token einfügen

def test_pasted_token_is_checked_and_stored(accounts, store, vault, gh):
    assert run(accounts.connect_token("dora", f"  {PERSONAL}\n")) == "dora-gh"
    assert store.github_account_get("dora")["via"] == "token" and vault.unseal(store.github_account_get("dora")["token"]) == PERSONAL
    assert gh.auth == [f"Bearer {PERSONAL}"]


def test_pasted_token_with_wrong_shape_is_rejected_without_asking_github(accounts, gh):
    for bad in ("", "abc", "mit leerzeichen drin 12345678901234567890", "x" * 300):
        with pytest.raises(AccountError):
            run(accounts.connect_token("dora", bad))
    assert gh.auth == []


def test_rejected_token_is_not_stored_and_not_echoed(accounts, store, gh):
    gh.user = (401, {"message": "Bad credentials"})
    with pytest.raises(AccountError) as err:
        run(accounts.connect_token("dora", PERSONAL))
    assert "ablehnen" in str(err.value) or "lehnt" in str(err.value)
    assert PERSONAL not in str(err.value) and store.github_account_get("dora") is None


def test_disconnect_switches_github_off_for_the_person(accounts, store):
    run(accounts.connect_token("dora", PERSONAL))
    assert accounts.disconnect("dora") is True and accounts.disconnect("dora") is False
    assert store.github_account_get("dora") is None and accounts.api_for("dora") is accounts.none and not accounts.enabled_for("dora")


def test_token_that_no_longer_fits_the_key_is_ignored(accounts, store, tmp_path, gh, clock):
    run(accounts.connect_token("dora", PERSONAL))
    other = GithubAccounts(store, Vault(tmp_path / "anderer.key"), transport=gh.transport(), clock=clock)
    assert other.personal("dora") is None and other.source("dora") == "none"  # kein Absturz, kein Klartext


def test_replacing_the_token_takes_effect_immediately(accounts, gh):
    run(accounts.connect_token("dora", PERSONAL))
    first = accounts.api_for("dora")
    second_token = "gho_zweites_token_abcdefghijkl"
    run(accounts.connect_token("dora", second_token))
    assert accounts.api_for("dora") is not first and accounts.api_for("dora")._token == second_token


def test_personal_rejection_names_the_person_not_the_administrator():
    api = GithubApi(PERSONAL, personal=True, transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"message": "Bad credentials"})))
    with pytest.raises(Exception) as err:
        run(api.request("GET", "/user"))
    assert "neu verbinden" in str(err.value) and "Administrator" not in str(err.value)


# ----------------------------------------------------------------------- Einbindung in die App

def app_client(store, vault, gh, clock, **options):
    settings = parse_settings({**RAW, **options}, frozenset({"testclient"}))
    accounts = GithubAccounts(store, vault, transport=gh.transport(), clock=clock)
    return TestClient(build_ingress_app(settings, store, FakeChat(), github_accounts=accounts)), accounts


class FakeChat:
    def __init__(self):
        self.tools = []

    async def stream(self, history, message, effort, attachments=None, instructions=None, tools=None, note="", **_):
        self.tools = [t.name for t in tools or []]
        yield "ok"


def headers(user):
    from conftest import as_user  # noqa: PLC0415
    return {**as_user(user, True), **WRITE}


def test_connect_with_token_end_to_end_and_chat_uses_the_personal_token(store, vault, gh, clock):
    from conftest import ADM01  # noqa: PLC0415
    client, accounts = app_client(store, vault, gh, clock)
    answer = client.post("/api/github/token", json={"token": PERSONAL}, headers=headers(ADM01))
    assert answer.status_code == 200 and answer.json() == {"login": "dora-gh"} and PERSONAL not in answer.text
    info = client.get("/api/github/account", headers=headers(ADM01)).json()
    assert info["source"] == "personal" and info["login"] == "dora-gh" and info["via"] == "token" and PERSONAL not in str(info)
    assert accounts.api_for("adm01")._token == PERSONAL
    assert client.delete("/api/github/account", headers=headers(ADM01)).status_code == 204
    assert client.get("/api/github/account", headers=headers(ADM01)).json()["source"] == "none"


def test_without_a_connected_account_the_person_can_connect_and_tools_appear(store, vault, gh, clock):
    from conftest import ADM01  # noqa: PLC0415
    settings = parse_settings(RAW, frozenset({"testclient"}))
    accounts = GithubAccounts(store, vault, transport=gh.transport(), clock=clock)
    chat = FakeChat()
    client = TestClient(build_ingress_app(settings, store, chat, github_accounts=accounts))
    assert client.get("/api/me", headers=headers(ADM01)).json()["github"] == "none"  # noch nichts verbunden
    assert client.post("/api/github/token", json={"token": PERSONAL}, headers=headers(ADM01)).status_code == 200
    assert client.get("/api/me", headers=headers(ADM01)).json()["github"] == "write"
    chat_id = client.post("/api/chats", json={}, headers=headers(ADM01)).json()["id"]
    client.post(f"/api/chats/{chat_id}/send", json={"content": "Hi"}, headers=headers(ADM01))
    assert "github_read_file" in chat.tools and "github_commit_files" in chat.tools


def test_device_endpoints_and_other_people_stay_separate(store, vault, gh, clock):
    from conftest import ADM01, DORA  # noqa: PLC0415
    client, accounts = app_client(store, vault, gh, clock)
    start = client.post("/api/github/device", headers=headers(ADM01))
    assert start.status_code == 200 and start.json()["user_code"] == "ABCD-1234" and CODE not in start.text
    assert client.get("/api/github/account", headers=headers(ADM01)).json()["pending"] is True
    assert client.get("/api/github/account", headers=headers(DORA)).json()["pending"] is False
    gh.answers.append({"access_token": PERSONAL})
    clock.now += 6
    done = client.post("/api/github/device/poll", headers=headers(ADM01)).json()
    assert done == {"status": "ok", "login": "dora-gh"}
    assert accounts.source("adm01") == "personal" and accounts.source("dora") == "none"
    assert client.post("/api/github/device/poll", headers=headers(DORA)).json() == {"status": "none"}
    assert client.get("/api/github/device/poll", headers=headers(ADM01)).status_code == 405  # Abfragen, die etwas speichern, sind nie GET


def test_changing_endpoints_need_the_csrf_header(store, vault, gh, clock):
    from conftest import ADM01, as_user  # noqa: PLC0415
    client, _ = app_client(store, vault, gh, clock)
    plain = as_user(ADM01)
    assert client.post("/api/github/device", headers=plain).status_code == 403
    assert client.post("/api/github/device/poll", headers=plain).status_code == 403
    assert client.post("/api/github/token", json={"token": PERSONAL}, headers=plain).status_code == 403
    assert client.delete("/api/github/account", headers=plain).status_code == 403


def test_a_wrong_token_gives_a_readable_error(store, vault, gh, clock):
    from conftest import ADM01  # noqa: PLC0415
    client, _ = app_client(store, vault, gh, clock)
    assert client.post("/api/github/token", json={"token": "kurz"}, headers=headers(ADM01)).status_code == 400
    gh.user = (401, {"message": "Bad credentials"})
    bad = client.post("/api/github/token", json={"token": PERSONAL}, headers=headers(ADM01))
    assert bad.status_code == 400 and PERSONAL not in bad.text
