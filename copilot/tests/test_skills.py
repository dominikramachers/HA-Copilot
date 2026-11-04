"""Skills: Import (SKILL.md, .skill, ZIP), Speicher, Vorrang, Werkzeuge, Fremdinhalt, Trennung der Personen, Standard-Skills."""
import asyncio
import base64
import io
import re
import zipfile
from pathlib import Path

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

def save(store, profile="dora", project=None, imported=True, md=SKILL_MD):
    pkg = sk.parse_upload("SKILL.md", md.encode())
    return store.skill_save(profile, project, pkg.name, pkg.description, pkg.files, imported=imported)


def test_store_scopes_precedence_and_isolation(store):
    pid = store.create_project("dora", "Zabbix")["id"]
    other = store.create_project("adm01", "Fremd")["id"]
    glob = save(store)
    proj = save(store, project=pid, md=SKILL_MD.replace("Zabbix-Templates", "Projekt-Templates"), imported=False)
    save(store, md=SKILL_MD.replace("zabbix-templates", "nur-global"))
    assert [s["name"] for s in store.skill_list("dora", None)] == ["nur-global", "zabbix-templates"]
    assert [s["name"] for s in store.skill_list("dora", pid)] == ["zabbix-templates"]
    active = {s["name"]: s for s in store.skills_active("dora", pid)}
    assert active["zabbix-templates"]["project"] and active["zabbix-templates"]["id"] == proj["id"] and "nur-global" in active
    assert {s["name"]: s["project"] for s in store.skills_active("dora", None)}["zabbix-templates"] is False
    # Abschalten
    assert store.skill_set_enabled("dora", proj["id"], False)
    assert {s["name"]: s for s in store.skills_active("dora", pid)}["zabbix-templates"]["id"] == glob["id"]
    # fremde Person: nichts sichtbar, nichts änderbar, kein Zugriff über fremdes Projekt
    assert store.skill_list("adm01", None) == [] and store.skills_active("adm01", None) == []
    assert store.skill_get("adm01", glob["id"]) is None
    assert not store.skill_delete("adm01", glob["id"]) and not store.skill_set_enabled("adm01", glob["id"], False)
    assert store.skill_list("dora", other) is None and save(store, project=other) is None
    # gleicher Name im gleichen Bereich ersetzt, Dateien inklusive
    pkg = sk.parse_upload("x.skill", skill_zip())
    store.skill_save("dora", None, pkg.name, pkg.description, pkg.files, imported=True)
    store.skill_save("dora", None, pkg.name, "neu", {"SKILL.md": SKILL_MD}, imported=True)
    row = store.skill_get("dora", glob["id"])
    assert row["description"] == "neu" and list(row["files"]) == ["SKILL.md"]
    # Projekt löschen nimmt Projekt-Skills mit
    assert store.delete_project("dora", pid)
    assert store.skill_get("dora", proj["id"]) is None and store.skill_get("dora", glob["id"]) is not None


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
    store.skill_save("dora", None, pkg.name, pkg.description, pkg.files, imported=True)
    box = toolbox(store)
    assert {s.name for s in box.specs()} >= {"skill_load", "skill_file"}
    note = box.note(["Dora"], "read", False)
    assert "zabbix-templates (global, importiert)" in note and "Standard-Leitfäden" in note and "gehen" in note
    assert "Lies references" not in note  # nur Name und Beschreibung, nicht die Anleitung


def test_skill_load_and_file_with_taint_kind(store):
    pkg = sk.parse_upload("x.skill", skill_zip())
    imported = store.skill_save("dora", None, pkg.name, pkg.description, pkg.files, imported=True)
    own = sk.build("eigenes", "Wann auch immer", "Mach X")
    store.skill_save("dora", None, own.name, own.description, own.files, imported=False)
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
    # ausgeschaltete Skills sind für die KI nicht da
    store.skill_set_enabled("dora", imported["id"], False)
    assert "zabbix-templates" not in {s["name"] for s in toolbox(store).skills}


def test_other_person_never_sees_skills_and_project_skill_wins(store):
    pid = store.create_project("dora", "P")["id"]
    save(store)
    save(store, project=pid, md=SKILL_MD.replace("Zabbix-Templates", "Projekt-Version"), imported=False)
    assert toolbox(store, "adm01").skills == []
    in_project = toolbox(store, project_id=pid)
    assert "Projekt-Version" in in_project.note(["Dora"], "read", False) and "Zabbix-Templates erstellen" not in in_project.note(["Dora"], "read", False)
    assert "Zabbix-Templates erstellen" in toolbox(store).note(["Dora"], "read", False)
    assert toolbox(store, "adm01", project_id=pid).skills == []  # fremdes Projekt


def test_imported_skills_count_as_tainted_in_every_confirmation_rule():
    source = (Path(__file__).resolve().parent.parent / "app" / "main.py").read_text(encoding="utf-8")
    rules = re.findall(r"a\[\"kind\"\] in \(([^)]*)\)", source)
    rules = [r for r in rules if '"web"' in r]  # die Regeln „Fremdinhalt gelesen“; nicht die Zählung eigener Änderungen
    assert len(rules) >= 4 and all('"skill-ext"' in r for r in rules)


def test_list_is_capped_in_the_note():
    entries = [{"name": f"s{i}", "description": "x" * 400, "project": False, "imported": False} for i in range(60)]
    block = sk.note_block(entries)
    assert len(block) < sk.LIST_INLINE_CHARS + 2500 and "weitere" in block and sk.note_block([]) == ""


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


def test_api_isolation_between_people_and_projects(api):
    client, _ = api
    h = as_user(DORA, True)
    pid = client.post("/api/projects", json={"name": "Z"}, headers=h).json()["id"]
    mine = client.post("/api/skills", json={"name": "x.md", "data": b64(SKILL_MD.encode()), "project_id": pid}, headers=h).json()
    assert mine["project_id"] == pid
    assert [s["name"] for s in client.get(f"/api/skills?project={pid}", headers=as_user(DORA)).json()["skills"]] == ["zabbix-templates"]
    assert client.get("/api/skills", headers=as_user(DORA)).json()["skills"] == []  # Projekt-Skill nicht global
    a = as_user(ADM01, True)
    assert client.get("/api/skills", headers=as_user(ADM01)).json()["skills"] == []
    assert client.get(f"/api/skills?project={pid}", headers=as_user(ADM01)).status_code == 404
    assert client.get(f"/api/skills/{mine['id']}", headers=as_user(ADM01)).status_code == 404
    assert client.patch(f"/api/skills/{mine['id']}", json={"enabled": False}, headers=a).status_code == 404
    assert client.delete(f"/api/skills/{mine['id']}", headers=a).status_code == 404
    assert client.get(f"/api/skills/{mine['id']}/export", headers=as_user(ADM01)).status_code == 404
    assert client.post("/api/skills", json={"name": "x.md", "data": b64(SKILL_MD.encode()), "project_id": pid}, headers=a).status_code == 404
    assert client.delete(f"/api/projects/{pid}", headers=h).status_code == 204
    assert client.get(f"/api/skills/{mine['id']}", headers=as_user(DORA)).status_code == 404


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
    assert {"skill_load", "skill_file"} <= {t.name for t in call["tools"]} and "zabbix-templates (global, importiert)" in call["note"]
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

    pid = store.create_project("dora", "Zabbix Projekt")["id"]
    save(store)
    save(store, project=pid, imported=False)
    save(store, profile="adm01")
    with zipfile.ZipFile(io.BytesIO(exporter.build_zip(store, "dora"))) as zf:
        names = set(zf.namelist())
    assert "skills/global/zabbix-templates/SKILL.md" in names
    assert any(n.startswith("skills/Zabbix Projekt/zabbix-templates/") for n in names)
    assert len([n for n in names if n.startswith("skills/")]) == 2
