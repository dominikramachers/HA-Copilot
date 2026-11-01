"""Chat-Suche, Export (Markdown und ZIP) und Löschen der eigenen Chats."""
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from app import exporter
from app.config import parse_settings
from app.db import fold
from app.main import Run, build_ingress_app
from conftest import ADM01, DORA, RAW, FakeBackend, as_user

SETTINGS = parse_settings(RAW, frozenset({"testclient"}))


def make_app(store):
    app = build_ingress_app(SETTINGS, store, FakeBackend(("ok",)))
    return app, TestClient(app)


def chat_with(store, profile, title, *texts, project_id=None):
    chat = store.create_chat(profile, title, project_id)
    for i, text in enumerate(texts):
        store.add_message(profile, chat["id"], "user" if i % 2 == 0 else "assistant", text)
    return chat


# ------------------------------------------------------------------------ Suche

def test_fold_ignores_case_and_accents_and_keeps_length():
    assert fold("Küche ÄÖÜ Café") == "kuche aou cafe"
    assert fold(None) == ""
    for text in ("Straße", "İstanbul", "ﬁsch", "Größe 😀"):
        assert len(fold(text)) == len(text)


def test_search_finds_words_in_messages_and_titles(store):
    a = chat_with(store, "adm01", "Heizung", "Wie warm ist es in der Küche?", "In der Küche sind es 21 Grad.")
    b = chat_with(store, "adm01", "Einkauf Küche", "Milch und Brot")
    chat_with(store, "adm01", "Garten", "Rasen mähen")
    found = store.search_chats("adm01", "kuche")
    assert {r["chat_id"] for r in found} == {a["id"], b["id"]}
    by_id = {r["chat_id"]: r for r in found}
    assert "Küche" in by_id[a["id"]]["snippet"] and by_id[a["id"]]["hl"]
    assert by_id[b["id"]]["snippet"] == "" and by_id[b["id"]]["hl"] == []  # nur im Titel


def test_search_needs_all_words_in_any_order(store):
    a = chat_with(store, "adm01", "A", "Die Heizung im Keller ist kalt", "Ich prüfe den Thermostat.")
    chat_with(store, "adm01", "B", "Die Heizung im Bad ist warm")
    assert [r["chat_id"] for r in store.search_chats("adm01", "keller heizung")] == [a["id"]]
    assert [r["chat_id"] for r in store.search_chats("adm01", "thermostat KELLER")] == [a["id"]]  # in verschiedenen Nachrichten
    assert store.search_chats("adm01", "keller bad") == []


def test_search_is_per_profile(store):
    chat_with(store, "dora", "Privat", "geheimes Passwort-Thema")
    assert store.search_chats("adm01", "geheimes") == []
    assert len(store.search_chats("dora", "geheimes")) == 1


def test_search_newest_first_limit_and_blank(store):
    ids = [chat_with(store, "adm01", f"Chat {i}", "Stichwort hier")["id"] for i in range(5)]
    store.add_message("adm01", ids[0], "user", "noch eine Frage")  # ältester Chat wird aktualisiert → ganz oben
    found = store.search_chats("adm01", "stichwort", limit=3)
    assert len(found) == 3 and found[0]["chat_id"] == ids[0]
    assert store.search_chats("adm01", "   ") == []


def test_search_treats_sql_wildcards_literally(store):
    chat_with(store, "adm01", "A", "100% sicher")
    chat_with(store, "adm01", "B", "nichts besonderes")
    assert len(store.search_chats("adm01", "%")) == 1
    assert len(store.search_chats("adm01", "_")) == 0


def test_snippet_highlights_all_terms_and_cuts_long_text(store):
    text = "Anfang " * 30 + "Die Temperatur in der Küche ist gut." + " Ende" * 60
    chat_with(store, "adm01", "Lang", text)
    hit = store.search_chats("adm01", "kuche temperatur")[0]
    shown = hit["snippet"]
    assert shown.startswith("…") and shown.endswith("…") and len(shown) < 200
    marked = [shown[a:b] for a, b in hit["hl"]]
    assert marked == ["Temperatur", "Küche"]


def test_search_endpoint(store):
    _, client = make_app(store)
    chat_with(store, "adm01", "Licht", "Schalte das Licht im Flur an")
    ok = client.get("/api/search", params={"q": "  FLUR  "}, headers=as_user(ADM01)).json()
    assert len(ok) == 1 and ok[0]["title"] == "Licht"
    assert client.get("/api/search", params={"q": "f"}, headers=as_user(ADM01)).json() == []
    assert client.get("/api/search", headers=as_user(ADM01)).json() == []
    assert client.get("/api/search", params={"q": "flur"}, headers=as_user(DORA)).json() == []
    assert client.get("/api/search", params={"q": "x" * 500}, headers=as_user(ADM01)).status_code == 200


# ----------------------------------------------------------------------- Export

def test_chat_markdown_content(store):
    project = store.create_project("adm01", "Haus")
    chat = store.create_chat("adm01", "Wärmepumpe", project["id"])
    store.add_message("adm01", chat["id"], "user", "Wie läuft sie?", attachments=[{"name": "log.txt", "kind": "text", "size": 5}])
    store.add_message("adm01", chat["id"], "assistant", "Gut: **COP 4**.", tools=[
        {"label": "Lesen: sensor.cop", "kind": "read", "status": "ok"},
        {"label": "Schalten: switch.pumpe", "kind": "write", "status": "denied", "note": "abgelehnt"},
    ])
    text = exporter.chat_markdown(store.get_chat("adm01", chat["id"]), store.list_messages("adm01", chat["id"]), "Haus", "AXON")
    assert text.startswith("# Wärmepumpe\n")
    assert "Projekt: Haus" in text and "exportiert aus AXON" in text
    assert "## Du · " in text and "## Assistent · " in text
    assert "Wie läuft sie?" in text and "Gut: **COP 4**." in text
    assert "*Anhänge: log.txt*" in text
    assert "> - Lesen: sensor.cop\n" in text and "> - Schalten: switch.pumpe (denied): abgelehnt" in text


def test_chat_export_endpoint(store):
    _, client = make_app(store)
    chat = chat_with(store, "adm01", "Größe/Test: <1>", "Hallo", "Hi")
    r = client.get(f"/api/chats/{chat['id']}/export", headers=as_user(ADM01))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/markdown")
    assert "attachment" in r.headers["content-disposition"] and ".md" in r.headers["content-disposition"]
    assert "/" not in r.headers["content-disposition"].split("''")[1]
    assert "Hallo" in r.text
    assert client.get(f"/api/chats/{chat['id']}/export", headers=as_user(DORA)).status_code == 404
    assert client.get("/api/chats/gibtsnicht/export", headers=as_user(ADM01)).status_code == 404


def test_safe_name():
    assert exporter.safe_name('a/b\\c:d*e?"f<g>h|i') == "a b c d e f g h i"
    assert exporter.safe_name("   ...   ") == "Chat"
    assert exporter.safe_name("", "X") == "X"
    assert len(exporter.safe_name("x" * 500)) == 80


def read_zip(data):
    archive = zipfile.ZipFile(io.BytesIO(data))
    return {n: archive.read(n).decode() for n in archive.namelist()}


def test_zip_contains_everything_of_the_person_only(store):
    project = store.create_project("adm01", "Haus")
    store.set_project_instructions("adm01", project["id"], "Antworte kurz.")
    chat_with(store, "adm01", "Heizung", "Frage", "Antwort", project_id=project["id"])
    chat_with(store, "adm01", "Heizung", "Zweite", "Antwort")  # gleicher Titel, anderer Ordner
    chat_with(store, "adm01", "Heizung", "Dritte", "Antwort")  # gleicher Titel und Ordner
    store.memory_save("person", "adm01", "Vorliebe", "Mag es warm.")
    store.schedule_create("adm01", {"name": "Bericht", "prompt": "Fasse zusammen.", "freq": "daily", "at_time": "07:30", "days": ""}, 1)
    chat_with(store, "dora", "Fremd", "gehört Dora")
    files = read_zip(exporter.build_zip(store, "adm01", "AXON"))
    chats = sorted(n for n in files if n.startswith("chats/"))
    assert len(chats) == 3 and len({n.lower() for n in chats}) == 3
    assert any("/Haus/" in n for n in chats) and sum("/Ohne Projekt/" in n for n in chats) == 2
    assert not any("Fremd" in text for text in files.values())
    assert "Antworte kurz." in files["projekte.md"] and "## Haus" in files["projekte.md"]
    assert "Mag es warm." in files["gedaechtnis.md"]
    assert "Jeden Tag um 07:30 Uhr" in files["geplante-aufgaben.md"] and "Fasse zusammen." in files["geplante-aufgaben.md"]
    assert "LIESMICH.txt" in files


def test_zip_puts_scheduled_runs_in_own_folder_and_handles_empty(store):
    empty = read_zip(exporter.build_zip(store, "adm01"))
    assert set(empty) == {"LIESMICH.txt", "projekte.md", "gedaechtnis.md", "geplante-aufgaben.md"}
    assert "Keine Projekte." in empty["projekte.md"]
    store.create_chat("adm01", "Morgenbericht · 26.10.", None, schedule_id="s1")
    assert any(n.startswith("chats/Geplante Aufgaben/") for n in read_zip(exporter.build_zip(store, "adm01")))


def test_zip_endpoint_and_rate_limit(store):
    _, client = make_app(store)
    chat_with(store, "adm01", "Eins", "Hallo")
    r = client.get("/api/export", headers=as_user(ADM01))
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert ".zip" in r.headers["content-disposition"]
    assert any(n.startswith("chats/") for n in read_zip(r.content))
    for _ in range(3):
        client.get("/api/export", headers=as_user(ADM01))
    assert client.get("/api/export", headers=as_user(ADM01)).status_code == 429
    assert client.get("/api/export", headers=as_user(DORA)).status_code == 200  # Begrenzung gilt je Person


# ---------------------------------------------------------------------- Löschen

def test_delete_all_chats_keeps_the_rest(store):
    _, client = make_app(store)
    h = as_user(ADM01, True)
    project = store.create_project("adm01", "Haus")
    chat = chat_with(store, "adm01", "Eins", "a", project_id=project["id"])
    chat_with(store, "adm01", "Zwei", "b")
    other = chat_with(store, "dora", "Fremd", "c")
    store.memory_save("person", "adm01", "T", "Inhalt")
    store.schedule_create("adm01", {"name": "N", "prompt": "P", "freq": "daily", "at_time": "07:30", "days": ""}, 1)
    file = store.outfile_add("adm01", chat["id"], "bericht.txt", "text/plain", b"abc", 3)
    path = store._outfile_path(file["id"])
    assert path.exists()
    r = client.post("/api/data/delete-chats", json={"confirm": "löschen"}, headers=h)
    assert r.status_code == 200 and r.json() == {"deleted": 2}
    assert store.list_chats("adm01") == [] and not path.exists()
    assert len(store.list_projects("adm01")) == 1 and len(store.memory_list("person", "adm01")) == 1
    assert len(store.schedule_list("adm01")) == 1
    assert [c["id"] for c in store.list_chats("dora")] == [other["id"]]
    assert client.post("/api/data/delete-chats", json={"confirm": "LÖSCHEN"}, headers=h).json() == {"deleted": 0}


@pytest.mark.parametrize("word", ["", "ja", "LOSCHEN", "LÖSCHEN bitte"])
def test_delete_all_needs_the_exact_word_and_write_guard(store, word):
    _, client = make_app(store)
    chat_with(store, "adm01", "Eins", "a")
    assert client.post("/api/data/delete-chats", json={"confirm": word}, headers=as_user(ADM01, True)).status_code == 422
    assert client.post("/api/data/delete-chats", json={"confirm": "LÖSCHEN"}, headers=as_user(ADM01)).status_code == 403
    assert len(store.list_chats("adm01")) == 1


def test_delete_all_refused_while_an_answer_is_running(store):
    app, client = make_app(store)
    chat = chat_with(store, "adm01", "Läuft", "a")
    run = Run(("adm01", chat["id"]), "text", False)
    app.state.scheduler.runs[("adm01", chat["id"])] = run
    r = client.post("/api/data/delete-chats", json={"confirm": "LÖSCHEN"}, headers=as_user(ADM01, True))
    assert r.status_code == 409 and len(store.list_chats("adm01")) == 1
    run.finished = True
    assert client.post("/api/data/delete-chats", json={"confirm": "LÖSCHEN"}, headers=as_user(ADM01, True)).json() == {"deleted": 1}
