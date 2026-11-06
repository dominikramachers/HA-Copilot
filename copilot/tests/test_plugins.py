"""Plugins: Katalog, Installieren und Entfernen (nur was das Plugin selbst angelegt hat), GitHub-Import von Claude-Plugins."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app import connector_catalog as ccat
from app import package_catalog as pcat
from app import plugins as pl
from app import plugins_github as pg
from app import skills as sk
from app.config import parse_settings
from app.main import build_ingress_app
from conftest import ADM01, DORA, RAW, FakeBackend, as_user
from test_connectors import FakeServers, make_service
from test_skills import SKILL_MD, SHA, blobs, github_transport

LEVELS = {"adm01": "global", "dora": "own"}


@pytest.fixture()
def world(store, tmp_path):
    levels = dict(LEVELS)
    service = make_service(store, FakeServers(), tmp_path, levels)
    app = build_ingress_app(parse_settings(RAW, frozenset({"testclient"})), store, FakeBackend(), connectors=service)
    return TestClient(app), service, levels


def run(coro):
    return asyncio.run(coro)


# ----------------------------------------------------------------------------- Katalog

def test_catalog_only_names_real_skills_and_connectors_with_texts_in_both_languages():
    skills = {s["id"] for s in sk.recommended_list()}
    seen = set()
    for entry in pcat._load()["plugins"]:
        assert entry["id"] not in seen
        seen.add(entry["id"])
        assert set(entry["skills"]) <= skills, entry["id"]
        assert entry["skills"] and len(set(entry["skills"])) == len(entry["skills"])
        for cid in entry["connectors"]:
            assert ccat.find(cid), (entry["id"], cid)
        for lang in ("de", "en"):
            assert entry["label"][lang] and entry["summary"][lang]
        assert entry["icon"]
    assert pcat.find("dev") and pcat.find("gibtesnicht") is None and pcat.checked()
    assert {e["label"] for e in pcat.entries()} and all(isinstance(e["label"], str) for e in pcat.entries())


# --------------------------------------------------------------------------- Installieren

def test_install_adds_skills_and_connectors_and_is_repeatable(world, store):
    client, service, _ = world
    h = as_user(DORA, True)
    first = client.post("/api/plugins/catalog/dev", headers=h)
    assert first.status_code == 200, first.text
    body = first.json()
    assert {s["state"] for s in body["skills"]} == {"added"} and len(body["skills"]) == 6
    assert {c["id"]: c["state"] for c in body["connectors"]} == {"sentry": "added", "context7": "added", "deepwiki": "added", "cloudflare-docs": "added"}
    assert {r["origin"] for r in store.skill_list("dora")} == {"recommended"} and len(service.listing("dora")) == 4
    again = client.post("/api/plugins/catalog/dev", headers=h).json()
    assert {s["state"] for s in again["skills"]} == {"present"} and {c["state"] for c in again["connectors"]} == {"present"}
    assert store.plugin_count("dora") == 1 and len(store.skill_list("dora")) == 6 and len(service.listing("dora")) == 4
    listing = client.get("/api/plugins", headers=as_user(DORA)).json()
    mine = listing["mine"][0]
    assert mine["name"] == next(e["label"] for e in pcat.entries() if e["id"] == "dev")
    assert mine["missing"] == 0 and mine["added"] == {"skills": 6, "connectors": 4}
    dev = next(e for e in listing["catalog"] if e["id"] == "dev")
    assert dev["installed"] and dev["complete"]


def test_google_connectors_need_their_own_app_and_are_left_as_setup(world, store):
    client, service, _ = world
    out = client.post("/api/plugins/catalog/inbox", headers=as_user(DORA, True)).json()
    assert {c["id"]: c["state"] for c in out["connectors"]} == {"gmail": "setup", "gcalendar": "setup"}
    assert service.listing("dora") == [] and len(out["skills"]) == 3
    entry = next(e for e in client.get("/api/plugins", headers=as_user(DORA)).json()["catalog"] if e["id"] == "inbox")
    assert entry["installed"] and not entry["complete"]


def test_without_connector_rights_only_skills_come_along(world, store):
    client, service, levels = world
    levels["dora"] = "use"
    out = client.post("/api/plugins/catalog/dev", headers=as_user(DORA, True)).json()
    assert {c["state"] for c in out["connectors"]} == {"no_rights"}
    assert len(store.skill_list("dora")) == 6 and service.listing("dora") == []
    levels["dora"] = "none"
    out = client.post("/api/plugins/catalog/research", headers=as_user(DORA, True)).json()
    assert {c["state"] for c in out["connectors"]} == {"no_access"} and len(out["skills"]) == 3


def test_existing_things_are_kept_and_not_removed_with_the_plugin(world, store):
    client, service, _ = world
    h = as_user(DORA, True)
    # eigenes Skill mit gleichem Namen und schon vorhandener Konnektor aus dem Katalog
    store.skill_save("dora", "code-review", "mein eigenes", {"SKILL.md": "---\nname: code-review\ndescription: mein eigenes\n---\n"}, origin="own")
    run(service.create("dora", {"catalog_id": "context7"}))
    out = client.post("/api/plugins/catalog/dev", headers=h).json()
    states = {s["id"]: s["state"] for s in out["skills"]}
    assert states["code-review"] == "taken" and states["debug"] == "added"
    assert {c["id"]: c["state"] for c in out["connectors"]}["context7"] == "present"
    plugin_id = out["id"]
    removed = client.delete(f"/api/plugins/{plugin_id}", headers=h)
    assert removed.status_code == 200 and removed.json() == {"skills": 5, "connectors": 3}
    assert [r["name"] for r in store.skill_list("dora")] == ["code-review"]  # das eigene Skill bleibt
    assert len(service.listing("dora")) == 1  # nur der schon vorhandene Konnektor bleibt
    assert store.plugin_count("dora") == 0


def test_removal_leaves_things_the_person_changed_alone(world, store):
    client, service, _ = world
    h = as_user(DORA, True)
    out = client.post("/api/plugins/catalog/project", headers=h).json()
    row = next(r for r in store.skill_list("dora") if r["name"] == "standup")
    store.skill_save("dora", "standup", "von mir geändert", {"SKILL.md": "---\nname: standup\ndescription: von mir geändert\n---\n"}, origin="own")
    removed = client.delete(f"/api/plugins/{out['id']}", headers=h).json()
    assert removed["skills"] == 5 and [r["name"] for r in store.skill_list("dora")] == ["standup"] and row["id"]


def test_people_are_separated_and_writing_needs_the_header(world, store):
    client, _, _ = world
    out = client.post("/api/plugins/catalog/design", headers=as_user(DORA, True)).json()
    assert client.post("/api/plugins/catalog/design", headers=as_user(ADM01)).status_code == 403  # Schreibkopf fehlt
    assert client.get("/api/plugins", headers=as_user(ADM01)).json()["mine"] == []
    assert client.delete(f"/api/plugins/{out['id']}", headers=as_user(ADM01, True)).status_code == 404
    assert client.post("/api/plugins/catalog/gibtesnicht", headers=as_user(DORA, True)).status_code == 404
    assert client.delete("/api/plugins/9999", headers=as_user(DORA, True)).status_code == 404
    assert store.plugin_count("dora") == 1


def test_plugin_limit_per_person(world, store, monkeypatch):
    client, _, _ = world
    monkeypatch.setattr(pl, "MAX_PLUGINS", 1)
    h = as_user(DORA, True)
    assert client.post("/api/plugins/catalog/design", headers=h).status_code == 200
    assert client.post("/api/plugins/catalog/design", headers=h).status_code == 200  # dasselbe noch einmal ist kein neues
    assert client.post("/api/plugins/catalog/support", headers=h).status_code == 422


# --------------------------------------------------------------------- Import von GitHub

PLUGIN_FILES = {
    ".claude-plugin/plugin.json": json.dumps({"name": "zabbix-kit", "version": "1.2.0", "description": "Zabbix im Griff"}).encode(),
    "skills/zabbix/SKILL.md": SKILL_MD.encode(),
    "skills/zabbix/references/regeln.md": b"# Regeln\n",
    "skills/leer/notes.md": b"keine SKILL.md",
    ".mcp.json": json.dumps({"mcpServers": {
        "zabbix": {"type": "http", "url": "https://mcp.zabbix.example/mcp", "headers": {"Authorization": "Bearer ${TOKEN}"}},
        "kontext": {"type": "http", "url": "https://mcp.context7.com/mcp"},
        "lokal": {"command": "npx", "args": ["-y", "irgendwas"]},
        "alt": {"type": "sse", "url": "https://alt.example/sse"},
        "unsicher": {"type": "http", "url": "http://klartext.example/mcp"},
    }}).encode(),
    "commands/start.md": b"/start",
    "agents/helfer.md": b"agent",
    "hooks/hooks.json": b"{}",
    "README.md": b"hallo",
}
URL = "https://github.com/o/r"


def test_github_url_with_a_plugin_folder_is_fetched_and_only_skills_and_servers_are_taken(world, store, monkeypatch):
    client, _, _ = world
    seen: list[str] = []
    monkeypatch.setattr(pg.sg, "TRANSPORT", github_transport(blobs(PLUGIN_FILES), PLUGIN_FILES, seen=seen))
    reply = client.post("/api/plugins/github", json={"url": URL}, headers=as_user(DORA, True))
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["name"] == "zabbix-kit" and body["version"] == "1.2.0" and body["source"] == f"o/r@{'a' * 7}"
    assert [s["name"] for s in body["skills"]] == ["zabbix-templates"] and body["skills"][0]["state"] == "new"
    by_name = {s["name"]: s for s in body["servers"]}
    assert set(by_name) == {"zabbix", "kontext"} and by_name["zabbix"]["auth"] == "bearer"
    assert by_name["kontext"]["catalog_id"] == "context7" and by_name["kontext"]["auth"] == "none"  # bekannte Adresse: Angaben aus dem Katalog
    assert any(x["name"] == "leer" and "SKILL.md" in x["reason"] for x in body["skipped"])
    notes = " ".join(body["notes"])
    assert "lokal" in notes and "alt" in notes and "unsicher" in notes
    assert {"commands/ (1 Dateien)", "agents/ (1 Dateien)", "hooks/ (1 Dateien)"} <= set(body["ignored"])
    assert not any("commands" in u or "agents" in u or "README" in u for u in seen)  # Befehle, Agenten, Hooks werden gar nicht geladen
    assert store.skill_list("dora") == [] and store.plugin_count("dora") == 0  # Vorschau speichert nichts


def test_github_import_commits_the_choice_and_a_newer_version_replaces_the_old(world, store, monkeypatch):
    client, service, _ = world
    monkeypatch.setattr(pg.sg, "TRANSPORT", github_transport(blobs(PLUGIN_FILES), PLUGIN_FILES))
    h = as_user(DORA, True)
    body = client.post("/api/plugins/github", json={"url": URL}, headers=h).json()
    done = client.post("/api/plugins/import", headers=h, json={
        "data": body["data"], "source": body["source"], "skills": ["zabbix-templates"],
        "servers": [{"name": "zabbix", "auth": "header"}, {"name": "kontext", "auth": "none"}],
    })
    assert done.status_code == 200, done.text
    out = done.json()
    assert out["skills"] == [{"name": "zabbix-templates", "state": "added"}]
    assert {c["name"]: c["state"] for c in out["connectors"]} == {"zabbix": "added", "kontext": "added"}
    assert store.skill_list("dora")[0]["origin"] == "imported"  # Fremdinhalt wie bei jedem Import
    names = {c["name"]: c for c in service.listing("dora")}
    assert len(names) == 2 and "zabbix" in names
    assert next(c for c in names.values() if c["url"].endswith("zabbix.example/mcp"))["auth"] == "header"
    # noch einmal (z. B. neuerer Commit): dasselbe Plugin wird ersetzt, nichts doppelt angelegt
    again = client.post("/api/plugins/import", headers=h, json={
        "data": body["data"], "source": body["source"].replace("aaaaaaa", "bbbbbbb"), "skills": ["zabbix-templates"],
        "servers": [{"name": "zabbix", "auth": "header"}],
    }).json()
    assert {c["state"] for c in again["connectors"]} == {"present"} and again["skills"][0]["state"] == "added"
    assert store.plugin_count("dora") == 1 and len(store.skill_list("dora")) == 1 and len(service.listing("dora")) == 2
    mine = client.get("/api/plugins", headers=as_user(DORA)).json()["mine"][0]
    assert mine["kind"] == "imported" and mine["missing"] == 0
    removed = client.delete(f"/api/plugins/{mine['id']}", headers=h).json()
    assert removed == {"skills": 1, "connectors": 2}
    assert store.skill_list("dora") == [] and service.listing("dora") == []


def test_github_import_without_connector_right_still_takes_the_skills(world, store, monkeypatch):
    client, service, levels = world
    levels["dora"] = "use"
    monkeypatch.setattr(pg.sg, "TRANSPORT", github_transport(blobs(PLUGIN_FILES), PLUGIN_FILES))
    h = as_user(DORA, True)
    body = client.post("/api/plugins/github", json={"url": URL}, headers=h).json()
    assert body["can_connectors"] is False
    out = client.post("/api/plugins/import", headers=h, json={
        "data": body["data"], "source": body["source"], "skills": ["zabbix-templates"], "servers": [{"name": "zabbix", "auth": "bearer"}],
    }).json()
    assert out["skills"][0]["state"] == "added" and out["connectors"][0]["state"] == "no_rights" and service.listing("dora") == []


def test_github_import_only_takes_what_was_ticked_and_never_overwrites_own_skills(world, store, monkeypatch):
    client, service, _ = world
    monkeypatch.setattr(pg.sg, "TRANSPORT", github_transport(blobs(PLUGIN_FILES), PLUGIN_FILES))
    h = as_user(DORA, True)
    store.skill_save("dora", "zabbix-templates", "eigenes", {"SKILL.md": SKILL_MD}, origin="own")
    body = client.post("/api/plugins/github", json={"url": URL}, headers=h).json()
    assert body["skills"][0]["state"] == "taken"
    out = client.post("/api/plugins/import", headers=h, json={"data": body["data"], "source": body["source"], "skills": ["zabbix-templates"], "servers": []}).json()
    assert out["skills"] == [{"name": "zabbix-templates", "state": "taken"}] and store.skill_list("dora")[0]["origin"] == "own"
    nothing = client.post("/api/plugins/import", headers=h, json={"data": body["data"], "source": body["source"], "skills": [], "servers": []})
    assert nothing.status_code == 200 and nothing.json() == {"id": nothing.json()["id"], "skills": [], "connectors": []}
    assert service.listing("dora") == []


def test_github_errors_are_explained(world, monkeypatch):
    client, _, _ = world
    h = as_user(DORA, True)
    post = lambda url: client.post("/api/plugins/github", json={"url": url}, headers=h)
    plain = {"README.md": b"x", "docs/a.md": b"y"}
    monkeypatch.setattr(pg.sg, "TRANSPORT", github_transport(blobs(plain), plain))
    nothing = post(URL)
    assert nothing.status_code == 422 and "kein Plugin" in nothing.json()["detail"]
    loose = {"skills/a/SKILL.md": SKILL_MD.encode()}  # Ordner mit skills/ ohne plugin.json zählt auch als Plugin
    monkeypatch.setattr(pg.sg, "TRANSPORT", github_transport(blobs(loose), loose))
    assert post(URL).status_code == 200
    two = {".claude-plugin/plugin.json": b"{}", "skills/a/SKILL.md": SKILL_MD.encode(), "x/.claude-plugin/plugin.json": b"{}", "x/skills/b/SKILL.md": SKILL_MD.encode()}
    monkeypatch.setattr(pg.sg, "TRANSPORT", github_transport(blobs(two), two))
    only = post(URL)  # das Hauptverzeichnis ist selbst ein Plugin: es zählt
    assert only.status_code == 200
    several = {"a/.claude-plugin/plugin.json": b"{}", "a/skills/s/SKILL.md": SKILL_MD.encode(), "b/.claude-plugin/plugin.json": b"{}", "b/skills/s/SKILL.md": SKILL_MD.encode()}
    monkeypatch.setattr(pg.sg, "TRANSPORT", github_transport(blobs(several), several))
    many = post(URL)
    assert many.status_code == 422 and "mehrere Plugins" in many.json()["detail"] and "a, b" in many.json()["detail"]
    chosen = post(URL + "/tree/main/b")
    assert chosen.status_code == 200 and chosen.json()["source"].endswith(" b")
    empty = {".claude-plugin/plugin.json": b"{}", "commands/x.md": b"x"}
    monkeypatch.setattr(pg.sg, "TRANSPORT", github_transport(blobs(empty), empty))
    assert "weder Skills noch Server" in post(URL).json()["detail"]
    assert post("https://evil.example/o/r").status_code == 422


def test_servers_in_mcp_json_are_checked_strictly():
    servers, notes = pl._parse_servers(json.dumps({"a": {"url": "https://x.example/mcp", "headers": {"X-Api-Key": "k"}}, "b": {"type": "http", "url": "https://x.example/${HOST}"}}).encode())
    assert servers == [{"name": "a", "url": "https://x.example/mcp", "auth": "header", "header_name": "X-Api-Key", "catalog_id": ""}]
    assert len(notes) == 1 and "b:" in notes[0]
    assert pl._parse_servers(None) == ([], []) and pl._parse_servers(b"{kaputt")[1]
    assert pl._parse_servers(b"[1]")[1]


def test_broken_or_oversized_plugin_zip_is_refused():
    with pytest.raises(pl.PluginError):
        pl.parse_plugin_zip(b"kein zip", "x")
    assert pl.fallback_name("o/r@abcdef1 plugins/kit") == "kit" and pl.fallback_name("o/r@abcdef1") == "r"


def test_body_limit_allows_the_import_but_not_arbitrary_big_bodies(world):
    client, _, _ = world
    big = "A" * (pg.MAX_BYTES * 2)
    assert client.post("/api/plugins/import", content=big, headers={**as_user(DORA, True), "Content-Type": "application/json"}).status_code == 413
    assert client.post("/api/plugins/catalog/dev", content="A" * 300_000, headers={**as_user(DORA, True), "Content-Type": "application/json"}).status_code == 413
