"""Skills: Import (SKILL.md, .skill, ZIP), Speicher, Vorrang, Werkzeuge, Fremdinhalt, Trennung der Personen, Standard-Skills."""
import asyncio
import base64
import io
import json
import re
import zipfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import skills as sk
from app.config import parse_settings
from app.context_tools import ContextToolbox
from app.ha_tools import ToolError
from app.main import build_ingress_app
from tests.conftest import ADM01, DORA, RAW, FakeBackend, as_user
from tests.test_schedules import build, make_task, run_tick

SKILL_MD = """---
name: zabbix-templates
description: >
  Zabbix-Templates erstellen und prüfen,
  auch bei Importfehlern.
license: MIT
---

# Zabbix

1. Lies references/regeln.md
2. Prüfe mit scripts/check.py
"""


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def zipped(files: dict[str, bytes | str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def run(coro):
    return asyncio.run(coro)


def skill_zip(prefix="zabbix-templates/", extra=None):
    files = {prefix + "SKILL.md": SKILL_MD, prefix + "references/regeln.md": "# Regeln\nNie doppelte UUIDs.", prefix + "scripts/check.py": "print('x')"}
    files.update({prefix + k: v for k, v in (extra or {}).items()})
    return zipped(files)


# ------------------------------------------------------------------ Lesen und Prüfen

def test_frontmatter_forms():
    meta, body = sk.split_frontmatter("---\nname: a\ndescription: \"Mit: Doppelpunkt \\\"zitiert\\\"\"\nx: 'it''s'\n---\nText")
    assert meta == {"name": "a", "description": 'Mit: Doppelpunkt "zitiert"', "x": "it's"} and body == "Text"
    meta, _ = sk.split_frontmatter("---\nname: a\ndescription: |\n  Zeile eins\n  Zeile zwei\n---\nx")
    assert meta["description"] == "Zeile eins\nZeile zwei"
    meta, _ = sk.split_frontmatter("---\r\nname: a\r\ndescription: Lang\r\n  weiter\r\n---\r\nx")
    assert meta["description"] == "Lang weiter"
    for bad in ("kein Kopf", "---\nname: a\n"):
        with pytest.raises(sk.SkillError):
            sk.split_frontmatter(bad)


def test_name_and_description_rules():
    for bad in ("a b", "-x", "x-", "x" * 65, "", "../x"):
        with pytest.raises(sk.SkillError):
            sk.check_name(bad)
    assert sk.check_name("a1-b2") == "a1-b2" and sk.check_name(" Zabbix ") == "zabbix"
    with pytest.raises(sk.SkillError, match="description"):
        sk.parse_skill_md("---\nname: ab\n---\nText")
    with pytest.raises(sk.SkillError, match="zu lang"):
        sk.parse_skill_md("---\nname: ab\ndescription: " + "x" * 1025 + "\n---\nText")
    with pytest.raises(sk.SkillError, match="keine Anleitung"):
        sk.parse_skill_md("---\nname: ab\ndescription: ok\n---\n\n")


def test_parse_single_skill_md_and_zip_with_folder_or_flat():
    single = sk.parse_upload("SKILL.md", SKILL_MD.encode())
    assert single.name == "zabbix-templates" and single.description == "Zabbix-Templates erstellen und prüfen, auch bei Importfehlern." and list(single.files) == ["SKILL.md"]
    folder = sk.parse_upload("x.skill", skill_zip())
    assert set(folder.files) == {"SKILL.md", "references/regeln.md", "scripts/check.py"}
    assert folder.warnings and "nie ausgeführt" in folder.warnings[0] and folder.scripts() == ["scripts/check.py"]
    flat = sk.parse_upload("x.zip", skill_zip(prefix=""))
    assert set(flat.files) == set(folder.files)


def test_zip_hardening():
    arch = skill_zip(extra={"bild.png": b"\x89PNG\x00\x00", "../evil.md": "böse", "assets/bin.dat": b"\x00\x01"})
    pkg = sk.parse_upload("x.skill", arch)
    assert "bild.png" not in pkg.files and not any(".." in p for p in pkg.files)
    assert {s["name"] for s in pkg.skipped} >= {"bild.png", "assets/bin.dat"}
    with pytest.raises(sk.SkillError, match="SKILL.md"):
        sk.parse_upload("x.zip", zipped({"a/b.md": "x"}))
    with pytest.raises(sk.SkillError, match="zu tief"):
        sk.parse_upload("x.zip", zipped({"a/b/c/SKILL.md": SKILL_MD}))
    with pytest.raises(sk.SkillError, match="beschädigt"):
        sk.parse_upload("x.zip", b"PK\x03\x04" + b"\x00" * 40)
    with pytest.raises(sk.SkillError, match="weder"):
        sk.parse_upload("x.bin", b"\x00" * 50)
    with pytest.raises(sk.SkillError, match="leer"):
        sk.parse_upload("x.md", b"")
    too_many = skill_zip(extra={f"references/f{i}.md": "x" for i in range(sk.FILES_MAX + 1)})
    with pytest.raises(sk.SkillError, match="zu viele"):
        sk.parse_upload("x.skill", too_many)
    with pytest.raises(sk.SkillError, match="zu lang"):
        sk.parse_upload("x.md", ("---\nname: ab\ndescription: d\n---\n" + "x" * (sk.SKILL_MD_MAX + 1)).encode())


def test_build_own_skill_roundtrips():
    pkg = sk.build("angebote", 'Wenn ein "Angebot" gebraucht wird', "1. Frage nach dem Kunden")
    name, description, body = sk.parse_skill_md(pkg.files["SKILL.md"])
    assert (name, description) == ("angebote", 'Wenn ein "Angebot" gebraucht wird') and body.startswith("1. Frage")
    assert sk.build("", "Angebote für Müller", "x").name == "angebote-fuer-mueller"
    with pytest.raises(sk.SkillError):
        sk.build("Ungültig Name", "d", "x")
    with pytest.raises(sk.SkillError):
        sk.build("ok", "d", "  ")


def test_export_is_importable_again():
    pkg = sk.parse_upload("x.skill", skill_zip())
    again = sk.parse_upload("y.skill", sk.to_zip(pkg.name, pkg.files))
    assert again.files == pkg.files and again.name == pkg.name


def test_standard_skills_are_the_design_guides():
    names = {s["name"] for s in sk.standard_list()}
    assert names == {f"design-{t}" for t in ("allgemein", "dokument", "folien", "html", "pdf", "tabelle")}
    assert "Dokumente" in sk.standard_text("design-dokument") and sk.standard_text("design-themen") is None and sk.standard_text("x") is None


# ------------------------------------------------------------------ Speicher

def save(store, profile="dora", origin="imported", md=SKILL_MD):
    pkg = sk.parse_upload("SKILL.md", md.encode())
    return store.skill_save(profile, pkg.name, pkg.description, pkg.files, origin=origin)


def test_store_isolation_replace_and_enable(store):
    glob = save(store)
    save(store, md=SKILL_MD.replace("zabbix-templates", "zweites"))
    assert [s["name"] for s in store.skill_list("dora")] == ["zabbix-templates", "zweites"]
    assert {s["name"] for s in store.skills_active("dora")} == {"zabbix-templates", "zweites"}
    # Abschalten
    assert store.skill_set_enabled("dora", glob["id"], False)
    assert {s["name"] for s in store.skills_active("dora")} == {"zweites"}
    # fremde Person: nichts sichtbar, nichts änderbar
    assert store.skill_list("adm01") == [] and store.skills_active("adm01") == []
    assert store.skill_get("adm01", glob["id"]) is None
    assert not store.skill_delete("adm01", glob["id"]) and not store.skill_set_enabled("adm01", glob["id"], False)
    # gleicher Name ersetzt, Dateien und Herkunft inklusive
    pkg = sk.parse_upload("x.skill", skill_zip())
    store.skill_save("dora", pkg.name, pkg.description, pkg.files, origin="imported")
    assert len(store.skill_get("dora", glob["id"])["files"]) == 3
    store.skill_save("dora", pkg.name, "neu", {"SKILL.md": SKILL_MD}, origin="own")
    row = store.skill_get("dora", glob["id"])
    assert row["description"] == "neu" and list(row["files"]) == ["SKILL.md"] and row["origin"] == "own"
    store.skill_set_enabled("dora", glob["id"], True)
    assert {x["name"]: x["imported"] for x in store.skills_active("dora")}["zabbix-templates"] is False
    # Projekte haben mit Skills nichts zu tun
    pid = store.create_project("dora", "P")["id"]
    assert store.delete_project("dora", pid) and store.skill_get("dora", glob["id"]) is not None


# ------------------------------------------------------------------ Werkzeuge für die KI

class Asker:
    async def __call__(self, label, details, offer):
        return "allow"


def toolbox(store, profile="dora", *, project_id=None, tainted=False):
    events, counter = [], iter(range(1, 1000))
    box = ContextToolbox(
        store, profile, profile.capitalize(), project_id=project_id, memory_enabled=True, household_write=True,
        force_confirm=False, ask=Asker(), record=events.append, next_id=lambda: next(counter), tainted=lambda: tainted,
    )
    box.events = events
    return box


def handler(box, name):
    return next(s for s in box.specs() if s.name == name).handler


def test_tools_only_exist_with_active_skills_and_list_goes_into_the_note(store):
    assert not [s for s in toolbox(store).specs() if s.name.startswith("skill_")]
    assert "Skills:" not in toolbox(store).note(["Dora"], "read", False)
    pkg = sk.parse_upload("x.skill", skill_zip())
    store.skill_save("dora", pkg.name, pkg.description, pkg.files, origin="imported")
    box = toolbox(store)
    assert {s.name for s in box.specs()} >= {"skill_load", "skill_file"}
    note = box.note(["Dora"], "read", False)
    assert "zabbix-templates (importiert)" in note and "Standard-Leitfäden" in note and "gehen" in note
    assert "Lies references" not in note  # nur Name und Beschreibung, nicht die Anleitung


def test_skill_load_and_file_with_taint_kind(store):
    pkg = sk.parse_upload("x.skill", skill_zip())
    imported = store.skill_save("dora", pkg.name, pkg.description, pkg.files, origin="imported")
    own = sk.build("eigenes", "Wann auch immer", "Mach X")
    store.skill_save("dora", own.name, own.description, own.files, origin="own")
    rec = sk.recommended_package("frontend-design")
    store.skill_save("dora", rec.name, rec.description, rec.files, origin="recommended")
    box = toolbox(store)
    text = run(handler(box, "skill_load")({"name": "zabbix-templates"}))
    assert "Fremdinhalt" in text and "Lies references/regeln.md" in text and "references/regeln.md" in text and "nicht ausgeführt" in text
    assert "name: zabbix-templates" not in text  # Kopf wird nicht doppelt geliefert
    assert box.events[-1]["kind"] == "skill-ext" and box.events[-1]["status"] == "ok" and box.events[-1]["label"].startswith("Skill genutzt")
    file = run(handler(box, "skill_file")({"name": "zabbix-templates", "path": "regeln.md"}))  # eindeutige Endung genügt
    assert "Nie doppelte UUIDs" in file
    assert "print('x')" in run(handler(box, "skill_file")({"name": "/zabbix-templates", "path": "scripts/check.py"}))
    with pytest.raises(ToolError, match="Dateien"):
        run(handler(box, "skill_file")({"name": "zabbix-templates", "path": "nein.md"}))
    with pytest.raises(ToolError, match="Verfügbar"):
        run(handler(box, "skill_load")({"name": "gibtsnicht"}))
    own_text = run(handler(box, "skill_load")({"name": "eigenes"}))
    assert "Mach X" in own_text and "Fremdinhalt" not in own_text and box.events[-1]["kind"] == "skill"
    # Empfohlene Skills sind mitgeliefert und geprüft: kein Fremdinhalt, die Bestätigungsregeln bleiben unberührt
    rec_text = run(handler(box, "skill_load")({"name": "frontend-design"}))
    assert "Typography carries the personality" in rec_text and "Fremdinhalt" not in rec_text and box.events[-1]["kind"] == "skill"
    assert "(empfohlen)" in box.note(["Dora"], "read", False)
    # ausgeschaltete Skills sind für die KI nicht da
    store.skill_set_enabled("dora", imported["id"], False)
    assert "zabbix-templates" not in {s["name"] for s in toolbox(store).skills}


def test_other_person_never_sees_skills_and_they_apply_in_projects(store):
    pid = store.create_project("dora", "P")["id"]
    save(store)
    assert toolbox(store, "adm01").skills == []
    assert "Zabbix-Templates erstellen" in toolbox(store).note(["Dora"], "read", False)
    assert "Zabbix-Templates erstellen" in toolbox(store, project_id=pid).note(["Dora"], "read", False)  # global: gilt auch im Projekt
    assert toolbox(store, "adm01", project_id=pid).skills == []


def test_imported_skills_count_as_tainted_in_every_confirmation_rule():
    from app import main

    source = (Path(__file__).resolve().parent.parent / "app" / "main.py").read_text(encoding="utf-8")
    assert {"skill-ext", "file-read", "web", "gh-read", "mcp-read"} <= main.TAINTING_KINDS
    rules = re.findall(r"a\[\"kind\"\] in ([^\n]*) for a in run\.actions", source)
    rules = [r for r in rules if "TAINTING_KINDS" in r or '"web"' in r]  # die Regeln „Fremdinhalt gelesen“; nicht die Zählung eigener Änderungen
    assert len(rules) >= 4 and all("TAINTING_KINDS" in r or '"skill-ext"' in r for r in rules)


def test_list_is_capped_in_the_note():
    entries = [{"name": f"s{i}", "description": "wort " * 100, "origin": "own", "imported": False} for i in range(120)]
    block = sk.note_block(entries)
    assert len(block) < sk.LIST_INLINE_CHARS + sk.LIST_NAMES_CHARS + 2500 and "nur mit Namen" in block and sk.note_block([]) == ""
    assert "s119" in block or "weitere" in block  # auch der Rest ist genannt (mit Namen oder als Anzahl)
    assert "wort " * 100 not in block and " …" in block  # lange Beschreibungen sind gekürzt
    short = sk.note_block(entries[:5])
    assert "nur mit Namen" not in short and short.count("\n- ") == 5


# ------------------------------------------------------------------ Programmierschnittstelle

@pytest.fixture()
def api(store):
    backend = FakeBackend()
    return TestClient(build_ingress_app(parse_settings(RAW, frozenset({"testclient"})), store, backend)), backend


def test_api_preview_import_toggle_view_export_delete(api):
    client, _ = api
    h = as_user(DORA, True)
    empty = client.get("/api/skills", headers=as_user(DORA)).json()
    assert empty["skills"] == [] and len(empty["standard"]) == 6 and empty["max"] == sk.PER_PERSON
    prev = client.post("/api/skills/preview", json={"name": "x.skill", "data": b64(skill_zip())}, headers=h)
    assert prev.status_code == 200 and prev.json()["name"] == "zabbix-templates" and prev.json()["warnings"] and prev.json()["replaces"] is False
    assert client.get("/api/skills", headers=as_user(DORA)).json()["skills"] == []  # Vorschau speichert nichts
    done = client.post("/api/skills", json={"name": "x.skill", "data": b64(skill_zip())}, headers=h)
    assert done.status_code == 200 and done.json()["imported"] is True and done.json()["files"] == 3
    sid = done.json()["id"]
    assert client.post("/api/skills/preview", json={"name": "x.skill", "data": b64(skill_zip())}, headers=h).json()["replaces"] is True
    detail = client.get(f"/api/skills/{sid}", headers=as_user(DORA)).json()
    assert "Zabbix" in detail["skill_md"] and {f["path"] for f in detail["files_list"]} == {"SKILL.md", "references/regeln.md", "scripts/check.py"}
    assert "Nie doppelte" in client.get(f"/api/skills/{sid}/file", params={"path": "references/regeln.md"}, headers=as_user(DORA)).json()["text"]
    assert client.get(f"/api/skills/{sid}/file", params={"path": "x"}, headers=as_user(DORA)).status_code == 404
    assert client.patch(f"/api/skills/{sid}", json={"enabled": False}, headers=h).json()["enabled"] is False
    assert client.get("/api/skills", headers=as_user(DORA)).json()["skills"][0]["enabled"] is False
    export = client.get(f"/api/skills/{sid}/export", headers=as_user(DORA))
    assert export.headers["content-type"] == "application/zip" and "zabbix-templates.skill" in export.headers["content-disposition"]
    assert sk.parse_upload("e.skill", export.content).name == "zabbix-templates"
    assert client.delete(f"/api/skills/{sid}", headers=h).status_code == 204
    assert client.get(f"/api/skills/{sid}", headers=as_user(DORA)).status_code == 404


def test_api_write_own_skill_errors_and_standard_view(api):
    client, _ = api
    h = as_user(DORA, True)
    ok = client.post("/api/skills/new", json={"name": "angebote", "description": "Für Angebote", "instructions": "Schritt 1"}, headers=h)
    assert ok.status_code == 200 and ok.json()["imported"] is False and ok.json()["name"] == "angebote"
    assert client.post("/api/skills/new", json={"name": "Nicht Gültig", "description": "d", "instructions": "x"}, headers=h).status_code == 422
    bad = client.post("/api/skills", json={"name": "x.md", "data": b64(b"kein Kopf")}, headers=h)
    assert bad.status_code == 422 and "Kopf" in bad.json()["detail"]
    assert client.post("/api/skills", json={"name": "x.md", "data": "***"}, headers=h).status_code == 422
    assert client.get("/api/skills/standard/design-folien", headers=as_user(DORA)).json()["text"]
    assert client.get("/api/skills/standard/design-themen", headers=as_user(DORA)).status_code == 404
    assert client.post("/api/skills/new", json={"description": "d", "instructions": "x"}, headers=as_user(DORA)).status_code in (400, 403)  # ohne Schreib-Kopfzeile


def test_api_isolation_between_people(api):
    client, _ = api
    h = as_user(DORA, True)
    mine = client.post("/api/skills", json={"name": "x.md", "data": b64(SKILL_MD.encode())}, headers=h).json()
    assert [s["name"] for s in client.get("/api/skills", headers=as_user(DORA)).json()["skills"]] == ["zabbix-templates"]
    a = as_user(ADM01, True)
    assert client.get("/api/skills", headers=as_user(ADM01)).json()["skills"] == []
    assert client.get(f"/api/skills/{mine['id']}", headers=as_user(ADM01)).status_code == 404
    assert client.patch(f"/api/skills/{mine['id']}", json={"enabled": False}, headers=a).status_code == 404
    assert client.delete(f"/api/skills/{mine['id']}", headers=a).status_code == 404
    assert client.get(f"/api/skills/{mine['id']}/export", headers=as_user(ADM01)).status_code == 404
    # Projekte ändern nichts an Skills
    pid = client.post("/api/projects", json={"name": "Z"}, headers=h).json()["id"]
    assert client.delete(f"/api/projects/{pid}", headers=h).status_code == 204
    assert client.get(f"/api/skills/{mine['id']}", headers=as_user(DORA)).status_code == 200


def test_api_per_person_limit(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(sk, "PER_PERSON", 2)
    h = as_user(DORA, True)
    for n in ("a1", "a2"):
        assert client.post("/api/skills/new", json={"name": n, "description": "d", "instructions": "x"}, headers=h).status_code == 200
    assert client.post("/api/skills/new", json={"name": "a3", "description": "d", "instructions": "x"}, headers=h).status_code == 422
    assert client.post("/api/skills/new", json={"name": "a1", "description": "neu", "instructions": "x"}, headers=h).status_code == 200  # Ersetzen zählt nicht


def test_chat_gets_skill_tools_and_note_and_scheduler_reads_them(store):
    backend = FakeBackend()
    client = TestClient(build_ingress_app(parse_settings(RAW, frozenset({"testclient"})), store, backend))
    save(store)
    chat = client.post("/api/chats", json={}, headers=as_user(DORA, True)).json()["id"]
    client.post(f"/api/chats/{chat}/send", json={"content": "Hallo"}, headers=as_user(DORA, True))
    call = backend.calls[-1]
    assert {"skill_load", "skill_file"} <= {t.name for t in call["tools"]} and "zabbix-templates (importiert)" in call["note"]
    other = client.post("/api/chats", json={}, headers=as_user(ADM01, True)).json()["id"]
    client.post(f"/api/chats/{other}/send", json={"content": "Hallo"}, headers=as_user(ADM01, True))
    assert "zabbix-templates" not in backend.calls[-1]["note"]
    # geplante Aufgabe: globale Skills der Person, nur lesend
    save(store, profile="adm01")
    scheduler, sched_backend, _, _, _ = build(store, now=2_000)
    make_task(store, next_run=1_000)
    assert run_tick(scheduler) == 1
    sched_call = sched_backend.calls[0]
    assert {"skill_load", "skill_file"} <= {t.name for t in sched_call["tools"]} and "zabbix-templates" in sched_call["note"]


def test_file_guide_points_to_user_skills(store):
    from app.outbox import OutboxToolbox

    def gate(user_skills):
        box = OutboxToolbox(store, "dora", "chat", record=lambda e: None, next_id=iter(range(1, 99)).__next__, keep_days=1, auto_guides=True, user_skills=user_skills)
        return box._gate("bericht.docx")

    assert "skill_load" in gate(True) and "skill_load" not in gate(False)


def test_skills_are_part_of_my_data_export(store):
    from app import exporter

    save(store)
    save(store, profile="adm01")
    with zipfile.ZipFile(io.BytesIO(exporter.build_zip(store, "dora"))) as zf:
        names = set(zf.namelist())
    assert {n for n in names if n.startswith("skills/")} == {"skills/zabbix-templates/SKILL.md"}  # nur die eigenen, ohne Unterordner „global“


# ------------------------------------------------------------------ Empfohlene Skills

def _catalog():
    return json.loads((sk.CATALOG_DIR / "catalog.json").read_text(encoding="utf-8"))


def test_catalog_entries_are_complete_and_untouched():
    catalog = _catalog()
    entries = catalog["skills"]
    ids = [e["id"] for e in entries]
    assert len(ids) == len(set(ids)) and len(ids) >= 60
    assert {"frontend-design", "internal-comms", "copywriting", "social", "code-review", "geschaeftsbrief-din-5008"} <= set(ids)
    assert "doc-coauthoring" not in ids  # bewusst nicht dabei: keine Lizenzdatei
    categories = {c["id"] for c in catalog["categories"]}
    assert {"marketing", "design", "office"} <= categories
    for c in catalog["categories"]:
        assert c["label"]["de"] and c["label"]["en"]
        assert any(e["category"] == c["id"] for e in entries), c["id"]  # keine leere Kategorie
    folders = {p.name for p in sk.CATALOG_DIR.iterdir() if p.is_dir() and p.name != "licenses"}
    assert folders == set(ids)  # jeder Ordner hat einen Eintrag und umgekehrt
    for e in entries:
        files = sk.catalog_files(e["id"])
        assert e["category"] in categories and e["author"] and e["source"].startswith("https://github.com/")
        assert e["license"] in ("Apache-2.0", "MIT")
        licence = files["LICENSE.txt"]
        assert ("Apache License" in licence and "Version 2.0" in licence) if e["license"] == "Apache-2.0" else "Permission is hereby granted" in licence
        assert e.get("installs") is None or (isinstance(e["installs"], int) and e["installs"] > 0)
        for field in ("label", "summary"):
            assert e[field]["de"] and e[field]["en"]
        assert len(e["label"]["de"]) <= 40 and len(e["summary"]["de"]) <= 260
        assert sk.parse_skill_md(files["SKILL.md"])[0] == e["id"]  # Ordnername = Skill-Name
        assert not [p for p in files if p.startswith(("scripts/", "evals/"))]  # mitgelieferte Skills enthalten keine Skripte
        assert len(files) <= sk.FILES_MAX and sum(len(x) for x in files.values()) <= sk.TOTAL_MAX
        assert len(files["SKILL.md"]) <= sk.SKILL_MD_MAX and all(len(x) <= sk.FILE_MAX for x in files.values())
    assert "examples/3p-updates.md" in sk.catalog_files("internal-comms")


def test_catalog_texts_have_no_hidden_characters():
    import unicodedata

    for path in sk.CATALOG_DIR.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            bad = {hex(ord(c)) for c in text if unicodedata.category(c) in ("Cf", "Co", "Cs") or 0xE0000 <= ord(c) <= 0xE007F}
            assert not bad, (path, bad)


def test_catalog_can_be_added_completely_and_listed_in_the_note(store):
    for r in sk.recommended_list():
        pkg = sk.recommended_package(r["id"])
        store.skill_save("dora", pkg.name, pkg.description, pkg.files, origin="recommended")
    entries = store.skills_active("dora")
    assert len(entries) == len(sk.recommended_list()) <= sk.PER_PERSON
    block = sk.note_block(entries)
    assert "Weitere Skills, nur mit Namen" in block  # nicht alle Beschreibungen passen: der Rest steht mit Namen da
    assert len(block) < sk.LIST_INLINE_CHARS + sk.LIST_NAMES_CHARS + 2500
    for e in entries:
        assert e["name"] in block  # jedes Skill ist mindestens mit seinem Namen genannt


def test_recommended_list_follows_the_language(monkeypatch):
    from app import i18n

    de = {r["id"]: r for r in sk.recommended_list()}
    assert "Gestaltung" in de["frontend-design"]["label"] and de["frontend-design"]["license"] == "Apache-2.0"
    i18n.set_language("en")
    try:
        en = {r["id"]: r for r in sk.recommended_list()}
    finally:
        i18n.set_language("de")
    assert en["frontend-design"]["label"] == "Design with a distinct style" and en["frontend-design"]["description"] == de["frontend-design"]["description"]
    assert sk.recommended_package("gibtsnicht") is None


def test_api_recommended_add_view_and_conflicts(api):
    client, _ = api
    h = as_user(DORA, True)
    listed = client.get("/api/skills", headers=as_user(DORA)).json()["recommended"]
    assert {r["id"] for r in listed} == {e["id"] for e in _catalog()["skills"]} and not any(r["installed"] or r["taken"] for r in listed)
    page = client.get("/api/skills", headers=as_user(DORA)).json()
    assert {c["id"] for c in page["categories"]} == {c["id"] for c in _catalog()["categories"]} and page["max"] == 120
    assert all(r["category"] in {c["id"] for c in page["categories"]} for r in listed)
    detail = client.get("/api/skills/recommended/internal-comms", headers=as_user(DORA)).json()
    assert "3P" in detail["skill_md"] and "Apache License" in detail["license_text"] and len(detail["files_list"]) == 6
    assert "Progress" in client.get("/api/skills/recommended/internal-comms/file", params={"path": "examples/3p-updates.md"}, headers=as_user(DORA)).json()["text"]
    assert client.get("/api/skills/recommended/internal-comms/file", params={"path": "../x"}, headers=as_user(DORA)).status_code == 404
    assert client.get("/api/skills/recommended/nope", headers=as_user(DORA)).status_code == 404
    assert client.post("/api/skills/recommended/nope", headers=h).status_code == 404
    assert client.post("/api/skills/recommended/frontend-design", headers=as_user(DORA)).status_code in (400, 403)  # ohne Schreib-Kopfzeile
    added = client.post("/api/skills/recommended/frontend-design", headers=h)
    assert added.status_code == 200 and added.json()["origin"] == "recommended" and added.json()["imported"] is False and added.json()["files"] == 2
    again = client.post("/api/skills/recommended/frontend-design", headers=h)
    assert again.status_code == 409
    state = {r["id"]: r for r in client.get("/api/skills", headers=as_user(DORA)).json()["recommended"]}
    assert state["frontend-design"]["installed"] and not state["internal-comms"]["installed"]
    assert not any(r["installed"] for r in client.get("/api/skills", headers=as_user(ADM01)).json()["recommended"])  # gilt je Person
    # gleicher Name, aber selbst geschrieben: nicht überschreiben, in der Liste als „vergeben“
    client.post("/api/skills/new", json={"name": "internal-comms", "description": "Meins", "instructions": "x"}, headers=h)
    assert client.post("/api/skills/recommended/internal-comms", headers=h).status_code == 409
    taken = {r["id"]: r for r in client.get("/api/skills", headers=as_user(DORA)).json()["recommended"]}["internal-comms"]
    assert taken["taken"] and not taken["installed"]
    # Entfernen geht wie bei jedem Skill; danach lässt es sich wieder hinzufügen
    sid = added.json()["id"]
    assert client.delete(f"/api/skills/{sid}", headers=h).status_code == 204
    assert client.post("/api/skills/recommended/frontend-design", headers=h).status_code == 200


def test_recommended_skill_is_used_like_an_own_one(store):
    pkg = sk.recommended_package("internal-comms")
    store.skill_save("dora", pkg.name, pkg.description, pkg.files, origin="recommended")
    box = toolbox(store)
    assert "internal-comms (empfohlen)" in box.note(["Dora"], "read", False)
    assert "examples/3p-updates.md" in run(handler(box, "skill_load")({"name": "internal-comms"}))
    assert "Progress, Plans, Problems" in run(handler(box, "skill_file")({"name": "internal-comms", "path": "examples/3p-updates.md"}))
    assert box.events[-1]["kind"] == "skill"


# ------------------------------------------------------------ Import von einem GitHub-Link

SHA = "a" * 40


def github_transport(tree, files, *, seen=None, commit_ok=("main",)):
    """Nachgebautes GitHub: Commit-Auflösung, Dateiliste und Rohdateien (nur dieses Repository)."""
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(str(request.url))
            assert "authorization" not in request.headers  # anonym, nie mit dem Token des Add-ons
        url = request.url
        if url.host == "api.github.com" and url.path.startswith("/repos/o/r/commits/"):
            ref = url.path[len("/repos/o/r/commits/"):]
            return httpx.Response(200, text=SHA) if ref in commit_ok or ref == "HEAD" else httpx.Response(404, json={"message": "No commit found"})
        if url.host == "api.github.com" and url.path == f"/repos/o/r/git/trees/{SHA}":
            return httpx.Response(200, json={"tree": tree, "truncated": False})
        if url.host == "raw.githubusercontent.com" and url.path.startswith(f"/o/r/{SHA}/"):
            path = url.path[len(f"/o/r/{SHA}/"):]
            return httpx.Response(200, content=files[path]) if path in files else httpx.Response(404)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def blobs(files):
    return [{"path": p, "type": "blob", "size": len(c)} for p, c in files.items()]


GH_FILES = {
    "skills/zabbix/SKILL.md": SKILL_MD.encode(),
    "skills/zabbix/references/regeln.md": b"# Regeln\n",
    "skills/zabbix/evals/e.json": b"{}",
    "skills/zabbix/.hidden": b"x",
    "skills/zabbix/pic.png": b"\x89PNG\r\n\x1a\n\x00\x00",
    "skills/other/SKILL.md": b"---\nname: other\ndescription: x\n---\n",
    "README.md": b"hallo",
}


def test_github_urls_are_parsed_strictly():
    from app import skills_github as gh

    t = gh.parse_url("https://github.com/o/r/tree/main/skills/zabbix")
    assert (t.owner, t.repo, t.rest, t.blob) == ("o", "r", ["main", "skills", "zabbix"], False)
    assert gh.parse_url("o/r").rest == [] and gh.parse_url("https://github.com/o/r.git").repo == "r"
    assert gh.parse_url("https://github.com/o/r/blob/main/skills/zabbix/SKILL.md").blob
    for bad in ("", "http://github.com/o/r", "https://evil.example/o/r", "https://github.com.evil.example/o/r", "https://u:p@github.com/o/r",
                "https://github.com/o", "https://github.com/o/r/issues/1", "https://github.com/o/r/tree/main/../x", "https://github.com/o/r/tree",
                "ftp://github.com/o/r", "https://github.com:444/o/r", "o/r extra", "https://github.com/o/r%2F..%2Fx"):
        with pytest.raises(sk.SkillError):
            gh.parse_url(bad)


def test_github_folder_is_fetched_checked_and_stays_foreign_content(store, api, monkeypatch):
    from app import skills_github as gh

    seen: list[str] = []
    monkeypatch.setattr(gh, "TRANSPORT", github_transport(blobs(GH_FILES), GH_FILES, seen=seen))
    client, _ = api
    reply = client.post("/api/skills/github", json={"url": "https://github.com/o/r/tree/main/skills/zabbix"}, headers=as_user(DORA, True))
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["name"] == "zabbix-templates" and body["source"] == f"o/r@{'a' * 7} skills/zabbix" and body["file"] == "zabbix-templates.skill"
    assert {f["path"] for f in body["files"]} == {"SKILL.md", "references/regeln.md"}
    assert not any(".hidden" in u or "evals" in u for u in seen)  # versteckte Dateien und evals/ werden gar nicht erst geladen
    assert any("pic.png" in s["name"] for s in body["skipped"])  # Binärdatei: nicht übernommen, mit Grund
    assert store.skill_list("dora") == []  # die Vorschau speichert nichts
    done = client.post("/api/skills", json={"name": body["file"], "data": body["data"]}, headers=as_user(DORA, True))
    assert done.status_code == 200 and store.skill_list("dora")[0]["origin"] == "imported"  # derselbe Weg wie beim Hochladen: fremder Inhalt


def test_github_branch_with_slash_and_repo_root_and_single_skill_search(store, api, monkeypatch):
    from app import skills_github as gh

    files = {"skills/zabbix/SKILL.md": SKILL_MD.encode()}
    monkeypatch.setattr(gh, "TRANSPORT", github_transport(blobs(files), files, commit_ok=("feature/x",)))
    client, _ = api
    # Zweig mit „/“: die erste Schreibweise („feature“) gibt es nicht, die zweite („feature/x“) schon
    ok = client.post("/api/skills/github", json={"url": "https://github.com/o/r/tree/feature/x/skills/zabbix"}, headers=as_user(DORA, True))
    assert ok.status_code == 200 and ok.json()["name"] == "zabbix-templates"
    # nur das Repository: genau ein Skill darunter wird gefunden
    root = client.post("/api/skills/github", json={"url": "o/r"}, headers=as_user(DORA, True))
    assert root.status_code == 200 and root.json()["source"].endswith("skills/zabbix")


def test_github_errors_are_explained(store, api, monkeypatch):
    from app import skills_github as gh

    monkeypatch.setattr(gh, "TRANSPORT", github_transport(blobs(GH_FILES), GH_FILES))
    client, _ = api
    post = lambda url: client.post("/api/skills/github", json={"url": url}, headers=as_user(DORA, True))
    many = post("https://github.com/o/r/tree/main/skills")
    assert many.status_code == 422 and "mehrere Skills" in many.json()["detail"] and "zabbix" in many.json()["detail"] and "other" in many.json()["detail"]
    assert "keine SKILL.md" in post("https://github.com/o/r/tree/main/nichts").json()["detail"]
    assert "nichts zu holen" in post("https://github.com/o/r/tree/gibtesnicht/skills/zabbix").json()["detail"]
    assert "kein GitHub-Link" in post("https://example.org/o/r").json()["detail"]
    assert post("https://github.com/o/r/tree/main/skills/zabbix").status_code == 200


def test_github_limits_and_redirects(store, api, monkeypatch):
    import httpx

    from app import skills_github as gh

    huge = {f"s/f{i}.md": b"x" for i in range(gh.MAX_FILES + 1)} | {"s/SKILL.md": SKILL_MD.encode()}
    monkeypatch.setattr(gh, "TRANSPORT", github_transport(blobs(huge), huge))
    client, _ = api
    assert "zu viele Dateien" in client.post("/api/skills/github", json={"url": "https://github.com/o/r/tree/main/s"}, headers=as_user(DORA, True)).json()["detail"]

    # eine einzelne zu große Datei wird übersprungen (der Skill bleibt brauchbar), mehrere zusammen begrenzen den Abruf
    big = {"s/SKILL.md": SKILL_MD.encode(), "s/a.md": b"x"}
    tree = [{"path": "s/SKILL.md", "type": "blob", "size": 100}, {"path": "s/a.md", "type": "blob", "size": sk.ZIP_MEMBER_BYTES + 1}]
    monkeypatch.setattr(gh, "TRANSPORT", github_transport(tree, big))
    ok = client.post("/api/skills/github", json={"url": "https://github.com/o/r/tree/main/s"}, headers=as_user(DORA, True))
    assert ok.status_code == 200 and any(s["name"] == "a.md" for s in ok.json()["skipped"])
    many = {"s/SKILL.md": SKILL_MD.encode()} | {f"s/f{i}.md": b"x" for i in range(3)}
    tree = [{"path": p, "type": "blob", "size": gh.MAX_BYTES // 2} for p in many]
    monkeypatch.setattr(gh, "TRANSPORT", github_transport(tree, many))
    assert "zu groß" in client.post("/api/skills/github", json={"url": "https://github.com/o/r/tree/main/s"}, headers=as_user(DORA, True)).json()["detail"]

    def limited(request):
        return httpx.Response(403, json={"message": "rate limit"})

    monkeypatch.setattr(gh, "TRANSPORT", httpx.MockTransport(limited))
    assert "begrenzt" in client.post("/api/skills/github", json={"url": "o/r"}, headers=as_user(DORA, True)).json()["detail"]

    def away(request):
        if request.url.host == "evil.example":
            return httpx.Response(200, text=SHA)
        return httpx.Response(302, headers={"location": "https://evil.example/x"})

    monkeypatch.setattr(gh, "TRANSPORT", httpx.MockTransport(away))
    moved = client.post("/api/skills/github", json={"url": "o/r"}, headers=as_user(DORA, True))
    assert moved.status_code == 422 and "umgeleitet" in moved.json()["detail"]  # andere Adressen als GitHub werden nicht verfolgt


def test_catalog_files_stay_inside_the_catalog_folder():
    assert sk.catalog_files("") == {} and sk.catalog_files(".") == {} and sk.catalog_files("frontend-design/..") == {} and sk.catalog_files("../") == {} and sk.catalog_files("../../etc") == {} and sk.catalog_files("/etc") == {}
    assert "SKILL.md" in sk.catalog_files("frontend-design")
