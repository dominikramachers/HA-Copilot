"""Das HA-Theme der Person gilt auch außerhalb von Home Assistant: der eingebettete Copilot meldet es, das Add-on merkt es je Person."""
import re
from pathlib import Path

from app.main import HA_LOOK_VARS
from tests.conftest import ADM01, DORA, as_user

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
LOOK = {"mode": "dark", "vars": {"primary-color": "#B45309", "primary-background-color": "#1a1410", "card-background-color": "rgb(30, 24, 18)"}}


def test_no_look_by_default_and_it_is_remembered_per_person(client):
    assert client.get("/api/me", headers=as_user(DORA)).json()["ha_look"] is None
    saved = client.put("/api/me/ha-look", json=LOOK, headers=as_user(DORA, True))
    assert saved.status_code == 200
    assert client.get("/api/me", headers=as_user(DORA)).json()["ha_look"] == LOOK
    assert client.get("/api/me", headers=as_user(ADM01)).json()["ha_look"] is None  # andere Person unberührt
    # ändert die Person ihr Theme in HA, gilt das neue
    newer = {"mode": "light", "vars": {"primary-color": "#0F766E", "primary-background-color": "#F1F6F5"}}
    assert client.put("/api/me/ha-look", json=newer, headers=as_user(DORA, True)).status_code == 200
    assert client.get("/api/me", headers=as_user(DORA)).json()["ha_look"] == newer


def test_only_known_colour_variables_are_kept(client):
    body = {"mode": "light", "vars": {**LOOK["vars"], "evil": "#fff", "primary-text-color": "url(javascript:alert(1))", "error-color": "red; x:y"}}
    assert client.put("/api/me/ha-look", json=body, headers=as_user(DORA, True)).status_code == 200
    kept = client.get("/api/me", headers=as_user(DORA)).json()["ha_look"]
    assert kept["mode"] == "light"
    assert set(kept["vars"]) == set(LOOK["vars"])


def test_invalid_look_is_rejected_and_needs_write_header(client):
    assert client.put("/api/me/ha-look", json={"mode": "neon", "vars": LOOK["vars"]}, headers=as_user(DORA, True)).status_code == 422
    assert client.put("/api/me/ha-look", json={"mode": "dark", "vars": {"primary-color": "#fff"}}, headers=as_user(DORA, True)).status_code == 422
    assert client.put("/api/me/ha-look", json=LOOK, headers=as_user(DORA)).status_code in (400, 403)
    assert client.get("/api/me", headers=as_user(DORA)).json()["ha_look"] is None


def test_script_and_server_know_the_same_variables():
    init = (STATIC / "theme-init.js").read_text(encoding="utf-8")
    listed = re.search(r"const HA_VARS = \[(.*?)\];", init, re.S).group(1)
    assert tuple(re.findall(r'"([\w-]+)"', listed)) == HA_LOOK_VARS
