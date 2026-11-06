"""Gedächtnis-Import aus einem Claude-Export (ZIP/Markdown) und „Meine Anweisungen“."""
import base64
import io
import json
import zipfile

import pytest

from app import memory_import as mi
from app.backend import SYSTEM_PROMPT, compose_system
from app.context_tools import CONTENT_MAX, PERSON_LIMIT
from app.db import INSTRUCTIONS_MAX
from tests.conftest import ADM01, DORA, as_user


def zipped(files: dict[str, str | bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


CLAUDE_EXPORT = {
    "profile.md": "---\nname: profile\ndescription: Wer die Person ist\nsources: [cowork]\n---\n- [stated] IT-Admin, wohnt in Wien\n- [stated] Baut ein Smarthome (for=code)\n",
    "preferences.md": "---\nname: preferences\n---\n- [stated] Antworte kurz und auf Deutsch\n- [stated] Duze mich\n",
    "areas/heizung.md": "---\nname: heizung\ndescription: Heizung im Haus\naliases: []\n---\n- [stated] Vorlauf 35 °C\n- 2026-09-01: Pumpe getauscht\n",
    "people/eli-son.md": "- [stated] Sohn Eli, 7 Jahre\n",
    "topics/kaffee.md": "- [stated] Trinkt Espresso ohne Zucker\n",
    "projects/0123/preferences.md": "- [stated] Nur Stichpunkte\n",
    "__MACOSX/profile.md": "Mac-Müll",
}


# --------------------------------------------------------------------------- Parser

def test_parse_claude_layout():
    files, skipped = mi.read_upload("export.zip", zipped(CLAUDE_EXPORT))
    found = mi.parse(files)
    by_topic = {e["topic"]: e for e in found["entries"]}
    assert by_topic["Profil"]["content"] == "- IT-Admin, wohnt in Wien\n- Baut ein Smarthome"
    assert by_topic["Heizung"]["content"] == "- Vorlauf 35 °C\n- 2026-09-01: Pumpe getauscht"
    assert by_topic["Kaffee"]["content"] == "Trinkt Espresso ohne Zucker"  # ein einzelner Punkt ohne Listenzeichen
    assert "Person: Eli son" in by_topic and by_topic["Person: Eli son"]["content"] == "Sohn Eli, 7 Jahre"
    assert "Vorlieben (Projekt)" in by_topic  # Vorlieben aus einem Projekt sind keine Anweisungen der Person
    assert found["instructions"] == {"text": "- Antworte kurz und auf Deutsch\n- Duze mich", "truncated": False}
    assert not any("stated" in e["content"] or "for=" in e["content"] for e in found["entries"])
    assert not any("Mac-Müll" in e["content"] for e in found["entries"])
    assert skipped == []


def test_parse_own_export_and_plain_lists():
    own = "# Persönliches Gedächtnis\n\n## Kaffee\n\nEspresso\n\n## Auto\n\nSkoda Octavia\n"
    found = mi.parse([("gedaechtnis.md", own)])
    assert [(e["topic"], e["content"]) for e in found["entries"]] == [("Kaffee", "Espresso"), ("Auto", "Skoda Octavia")]
    plain = mi.parse([("memory.txt", "- Mag Pizza\n- Hat einen Hund namens Rex\n")])
    assert [e["topic"] for e in plain["entries"]] == ["Mag Pizza", "Hat einen Hund namens Rex"]


def test_parse_splits_long_text_and_keeps_topics_unique():
    lines = "\n".join(f"- [stated] Punkt {i:03d} " + "x" * 60 for i in range(30))
    found = mi.parse([("areas/lang.md", "---\nname: lang\n---\n" + lines)])
    assert len(found["entries"]) >= 3
    assert all(len(e["content"]) <= CONTENT_MAX for e in found["entries"])
    topics = [e["topic"].casefold() for e in found["entries"]]
    assert len(set(topics)) == len(topics) and topics[0] == "lang" and topics[1] == "lang (2)"
    giant = mi.parse([("areas/riesig.md", "- " + "wort " * 400)])
    assert len(giant["entries"]) >= 3 and all(len(e["content"]) <= CONTENT_MAX for e in giant["entries"])
    long_topic = mi.parse([("x.md", "## " + "T" * 100 + "\n\ntext hier")])
    assert len(long_topic["entries"][0]["topic"]) <= 60


def test_parse_drops_secrets_and_reserved_names():
    found = mi.parse([("areas/zugang.md", "---\nname: zugang\n---\n- Das Passwort: geheim123\n"), ("areas/ok.md", "- Alles gut hier\n")])
    assert [e["topic"] for e in found["entries"]] == ["Ok"]
    assert found["skipped"] and "Zugangsdaten" in found["skipped"][0]["reason"]
    leak = mi.parse([("preferences.md", "- Mein API-Key: sk-ant-abcdefghijklmnopqrstuvwxyz")])
    assert leak["instructions"]["text"] == "" and leak["skipped"]
    reserved = mi.parse([("memory.md", "## HA · Räume\n\nWohnzimmer und Küche")])
    assert reserved["entries"][0]["topic"].startswith("HA –")


def test_instructions_are_cut_at_the_limit():
    lines = "\n".join(f"- Regel {i:04d} " + "y" * 90 for i in range(100))
    found = mi.parse([("preferences.md", lines)])
    assert found["instructions"]["truncated"] is True and len(found["instructions"]["text"]) <= INSTRUCTIONS_MAX


def test_read_upload_is_safe():
    with pytest.raises(mi.ImportError_):
        mi.read_upload("x.zip", b"PK\x03\x04" + b"\x00" * 40)
    with pytest.raises(mi.ImportError_):
        mi.read_upload("x.bin", b"\x00\x01\x02" * 50)
    with pytest.raises(mi.ImportError_):
        mi.read_upload("leer.zip", zipped({"bild.png": b"\x89PNG", "daten.json": "{}"}))
    files, skipped = mi.read_upload("a.zip", zipped({"a.md": "- Eins", "../evil.md": "- Zwei", "b.png": b"\x89PNG", ".versteckt.md": "x"}))
    names = {n for n, _ in files}
    assert "a.md" in names and not any(".." in n for n in names) and ".versteckt.md" not in names
    assert any(s["name"] == "b.png" for s in skipped)
    many = zipped({f"f{i}.md": "- x" for i in range(mi.ZIP_ENTRIES + 1)})
    with pytest.raises(mi.ImportError_):
        mi.read_upload("viele.zip", many)
    with pytest.raises(mi.ImportError_):
        mi.decode("%%%")


# ------------------------------------------------------------------------------ API

def preview(client, user=DORA, data=None, name="export.zip"):
    data = zipped(CLAUDE_EXPORT) if data is None else data
    return client.post("/api/memory/import/preview", json={"name": name, "data": b64(data)}, headers=as_user(user, True))


def test_preview_does_not_save_and_flags_existing(client):
    client.post("/api/memory", json={"scope": "person", "topic": "heizung", "content": "Alt."}, headers=as_user(DORA, True))
    r = preview(client)
    assert r.status_code == 200, r.text
    body = r.json()
    heizung = next(e for e in body["entries"] if e["topic"] == "Heizung")
    assert heizung["exists"]["person"] is True and heizung["exists"]["household"] is False
    assert body["instructions"]["text"].startswith("- Antworte kurz")
    assert body["free"]["person"] == PERSON_LIMIT - 1 and body["household_write"] is True
    mine = client.get("/api/memory", headers=as_user(DORA)).json()
    assert [m["topic"] for m in mine["person"]] == ["heizung"] and mine["instructions"] == ""


def test_preview_rejects_bad_input(client):
    write = as_user(DORA, True)
    assert client.post("/api/memory/import/preview", json={"name": "x.zip", "data": b64(b"PK\x03\x04junk")}, headers=write).status_code == 422
    assert preview(client, data=b"# nur Titel\n", name="x.md").status_code == 422
    assert client.post("/api/memory/import/preview", json={"name": "x.md", "data": "***"}, headers=write).status_code == 422
    assert client.post("/api/memory/import/preview", json={"name": "x.md", "data": b64(b"- hi")}, headers=as_user(DORA)).status_code == 403
    big = b64(b"- " + b"a" * (mi.MAX_UPLOAD_BYTES + 10))
    assert client.post("/api/memory/import/preview", json={"name": "x.md", "data": big}, headers=write).status_code in (413, 422)


def test_commit_saves_replaces_and_skips(client):
    write = as_user(DORA, True)
    client.post("/api/memory", json={"scope": "person", "topic": "Heizung", "content": "Alt."}, headers=write)
    client.post("/api/memory", json={"scope": "person", "topic": "Kaffee", "content": "Alt."}, headers=write)
    payload = {
        "scope": "person",
        "entries": [
            {"topic": "Heizung", "content": "Neu: Vorlauf 35 °C", "replace": True},
            {"topic": "Kaffee", "content": "Soll nicht überschreiben", "replace": False},
            {"topic": "Profil", "content": "IT-Admin"},
            {"topic": "Zugang", "content": "Das Passwort: abc12345"},
            {"topic": "HA · Räume", "content": "reserviert"},
            {"topic": "x", "content": "zu kurzes Thema"},
        ],
        "instructions": "Antworte kurz.",
    }
    r = client.post("/api/memory/import", json=payload, headers=write)
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["saved"] == 1 and result["replaced"] == 1 and result["instructions"] is True
    reasons = {s["name"]: s["reason"] for s in result["skipped"]}
    assert set(reasons) == {"Kaffee", "Zugang", "HA · Räume", "x"}
    mine = {m["topic"]: m["content"] for m in client.get("/api/memory", headers=as_user(DORA)).json()["person"]}
    assert mine == {"Heizung": "Neu: Vorlauf 35 °C", "Kaffee": "Alt.", "Profil": "IT-Admin"}
    assert client.get("/api/memory", headers=as_user(DORA)).json()["instructions"] == "Antworte kurz."
    assert client.get("/api/memory", headers=as_user(ADM01)).json()["person"] == []  # fremde Person sieht nichts


def test_commit_respects_limit_and_household_rights(client, store):
    write = as_user(DORA, True)
    for i in range(PERSON_LIMIT - 1):
        store.memory_save("person", "dora", f"Thema {i}", "Inhalt", "dora")
    entries = [{"topic": "Eins", "content": "aaa"}, {"topic": "Zwei", "content": "bbb"}]
    result = client.post("/api/memory/import", json={"entries": entries}, headers=write).json()
    assert result["saved"] == 1 and result["skipped"][0]["name"] == "Zwei" and "voll" in result["skipped"][0]["reason"]
    # Haushalt: nur mit Schreibrecht
    ok = client.post("/api/memory/import", json={"scope": "household", "entries": [{"topic": "Müll", "content": "Dienstag"}]}, headers=write)
    assert ok.status_code == 200 and ok.json()["saved"] == 1
    assert [m["topic"] for m in client.get("/api/memory", headers=as_user(ADM01)).json()["household"]] == ["Müll"]


def test_commit_household_denied_without_write_right(store):
    from fastapi.testclient import TestClient

    from app.config import parse_settings
    from app.main import build_ingress_app
    from tests.conftest import RAW, FakeBackend

    profiles = [{**RAW["profiles"][0], "ha_access": "write"}, RAW["profiles"][1]]
    settings = parse_settings({**RAW, "profiles": profiles, "memory_household_writers": "ha_write"}, frozenset({"testclient"}))
    client = TestClient(build_ingress_app(settings, store, FakeBackend()))
    body = {"scope": "household", "entries": [{"topic": "Plan", "content": "Umbau im Mai"}]}
    assert client.post("/api/memory/import", json=body, headers=as_user(DORA, True)).status_code == 403
    assert preview(client).json()["household_write"] is False
    assert client.post("/api/memory/import", json={**body, "scope": "person"}, headers=as_user(DORA, True)).status_code == 200


def test_instructions_append_replace_and_limits(client):
    write = as_user(DORA, True)
    put = lambda text: client.put("/api/memory/instructions", json={"text": text}, headers=write)
    assert put("  Duze mich.  ").json() == {"text": "Duze mich."}
    appended = client.post("/api/memory/import", json={"instructions": "Antworte kurz.", "instructions_mode": "append"}, headers=write)
    assert appended.status_code == 200
    assert client.get("/api/memory", headers=as_user(DORA)).json()["instructions"] == "Duze mich.\n\nAntworte kurz."
    client.post("/api/memory/import", json={"instructions": "Nur das.", "instructions_mode": "replace"}, headers=write)
    assert client.get("/api/memory", headers=as_user(DORA)).json()["instructions"] == "Nur das."
    too_long = client.post("/api/memory/import", json={"instructions": "z" * (INSTRUCTIONS_MAX - 3), "instructions_mode": "append"}, headers=write)
    assert too_long.status_code == 422
    assert put("a" * (INSTRUCTIONS_MAX + 1)).status_code == 422
    assert put("Mein Passwort: hunter22").status_code == 422
    assert put("").json() == {"text": ""}
    assert client.put("/api/memory/instructions", json={"text": "x"}, headers=as_user(DORA)).status_code == 403
    assert client.get("/api/memory", headers=as_user(ADM01)).json()["instructions"] == ""


def test_personal_instructions_reach_the_backend_and_the_prompt(client, backend):
    write = as_user(DORA, True)
    chat = client.post("/api/chats", json={}, headers=write).json()["id"]
    client.post(f"/api/chats/{chat}/send", json={"content": "Hallo"}, headers=write)
    assert backend.calls[0]["personal_instructions"] is None
    client.put("/api/memory/instructions", json={"text": "Duze mich."}, headers=write)
    client.post(f"/api/chats/{chat}/send", json={"content": "Nochmal"}, headers=write)
    assert backend.calls[1]["personal_instructions"] == "Duze mich."
    other = client.post("/api/chats", json={}, headers=as_user(ADM01, True)).json()["id"]
    client.post(f"/api/chats/{other}/send", json={"content": "Hi"}, headers=as_user(ADM01, True))
    assert backend.calls[2]["personal_instructions"] is None  # gilt nur für die eigene Person

    assert compose_system(None, personal=None) == SYSTEM_PROMPT
    both = compose_system("Projekt-Regel.", personal="Duze mich.")
    assert both.index("Duze mich.") < both.index("Projekt-Regel.") and both.startswith(SYSTEM_PROMPT)
    assert compose_system(None, personal="Duze mich.").endswith("Duze mich.")


def test_export_contains_instructions_only_when_set(client):
    write = as_user(DORA, True)
    zip_before = zipfile.ZipFile(io.BytesIO(client.get("/api/export", headers=as_user(DORA)).content))
    assert "anweisungen.md" not in zip_before.namelist()
    client.put("/api/memory/instructions", json={"text": "Duze mich."}, headers=write)
    zip_after = zipfile.ZipFile(io.BytesIO(client.get("/api/export", headers=as_user(DORA)).content))
    assert "Duze mich." in zip_after.read("anweisungen.md").decode()


def test_own_export_can_be_imported_again(client):
    write = as_user(DORA, True)
    client.post("/api/memory", json={"scope": "person", "topic": "Kaffee", "content": "Espresso"}, headers=write)
    data = client.get("/api/export", headers=as_user(DORA)).content
    found = preview(client, data=data).json()
    assert any(e["topic"] == "Kaffee" and e["content"] == "Espresso" and e["exists"]["person"] for e in found["entries"])


def test_schema_has_instructions_column(store):
    assert store.profile_instructions("dora") == ""
    assert store.set_profile_instructions("dora", "  hallo ") == "hallo"
    assert store.profile_instructions("dora") == "hallo"
    assert store.profile_instructions("unbekannt") == ""
