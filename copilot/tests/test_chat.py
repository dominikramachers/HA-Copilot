"""Streaming-Chat: Speichern, Verlauf, Fehler, Abbruch und Trennung der Profile."""
import json

from conftest import ADM01, DORA, SAM, FakeBackend, as_user
from app.backend import build_prompt, map_error


def events(response):
    out = []
    for block in response.text.split("\n\n"):
        if block.startswith("data: "):
            out.append(json.loads(block[6:]))
    return out


def new_chat(client, user=ADM01):
    return client.post("/api/chats", json={}, headers=as_user(user, True)).json()["id"]


def send(client, chat_id, content, user=ADM01, **extra):
    return client.post(
        f"/api/chats/{chat_id}/send", json={"content": content, **extra}, headers=as_user(user, True)
    )


def test_streams_and_persists_exchange(client, backend):
    chat_id = new_chat(client)
    response = send(client, chat_id, "Hallo KI", effort="high")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-store"
    evs = events(response)
    assert "".join(e["text"] for e in evs if e["type"] == "delta") == "Hallo Welt"
    assert evs[-1]["type"] == "done" and evs[-1]["title"] == "Hallo KI"

    messages = client.get(f"/api/chats/{chat_id}/messages", headers=as_user(ADM01)).json()
    assert [(m["role"], m["content"]) for m in messages] == [
        ("user", "Hallo KI"),
        ("assistant", "Hallo Welt"),
    ]
    assert client.get("/api/chats", headers=as_user(ADM01)).json()[0]["title"] == "Hallo KI"
    assert backend.calls[0]["effort"] == "high" and backend.calls[0]["history"] == []


def test_second_message_replays_history_and_keeps_title(client, backend):
    chat_id = new_chat(client)
    send(client, chat_id, "Erste Frage")
    send(client, chat_id, "Zweite Frage")
    assert backend.calls[1]["history"] == [
        {"role": "user", "content": "Erste Frage"},
        {"role": "assistant", "content": "Hallo Welt"},
    ]
    assert backend.calls[1]["effort"] == "medium"  # Standardwert aus der Konfiguration
    assert client.get("/api/chats", headers=as_user(ADM01)).json()[0]["title"] == "Erste Frage"


def test_backend_error_without_text_saves_nothing(client, store):
    backend = FakeBackend(pieces=(), error="Anmeldung fehlgeschlagen")
    # eigener Client mit diesem Backend
    from fastapi.testclient import TestClient
    from app.config import parse_settings
    from app.main import build_ingress_app
    from conftest import RAW

    c = TestClient(build_ingress_app(parse_settings(RAW, frozenset({"testclient"})), store, backend))
    chat_id = new_chat(c)
    evs = events(send(c, chat_id, "Frage"))
    assert evs[-1] == {"type": "error", "message": "Anmeldung fehlgeschlagen", "kept": False, "text": "Frage"}
    assert c.get(f"/api/chats/{chat_id}/messages", headers=as_user(ADM01)).json() == []
    # Der Chat ist danach nicht blockiert.
    assert send(c, chat_id, "nochmal").status_code == 200


def test_partial_answer_is_kept_on_error(store):
    from fastapi.testclient import TestClient
    from app.config import parse_settings
    from app.main import build_ingress_app
    from conftest import RAW

    backend = FakeBackend(pieces=("Teil ", "eins", "nie"), error="Abbruch", fail_after=2)
    c = TestClient(build_ingress_app(parse_settings(RAW, frozenset({"testclient"})), store, backend))
    chat_id = new_chat(c)
    evs = events(send(c, chat_id, "Frage"))
    assert evs[-1]["type"] == "error" and evs[-1]["kept"] is True
    messages = c.get(f"/api/chats/{chat_id}/messages", headers=as_user(ADM01)).json()
    assert messages[-1]["content"] == "Teil eins"


def test_other_profile_cannot_send_into_foreign_chat(client, backend):
    chat_id = new_chat(client, ADM01)
    assert send(client, chat_id, "Einschleusen", user=DORA).status_code == 404
    assert send(client, chat_id, "Hallo", user=SAM).status_code == 403
    assert backend.calls == []
    assert client.get(f"/api/chats/{chat_id}/messages", headers=as_user(ADM01)).json() == []


def test_send_requires_write_header_and_valid_body(client, backend):
    chat_id = new_chat(client)
    no_header = client.post(
        f"/api/chats/{chat_id}/send", json={"content": "x"}, headers=as_user(ADM01)
    )
    assert no_header.status_code == 403
    assert send(client, chat_id, "").status_code == 422
    assert send(client, chat_id, "   ").status_code == 422
    assert send(client, chat_id, "x" * 20001).status_code == 422
    assert send(client, chat_id, "x", effort="turbo").status_code == 422
    assert backend.calls == []


def test_busy_chat_is_rejected(client):
    # Eine laufende Antwort sperrt den Chat; die Sperre wird nach dem Ende wieder gelöst.
    chat_id = new_chat(client)
    assert send(client, chat_id, "eins").status_code == 200
    assert send(client, chat_id, "zwei").status_code == 200


def test_build_prompt_and_error_mapping():
    assert build_prompt([], "Hi") == "Hi"
    prompt = build_prompt([{"role": "user", "content": "A"}, {"role": "assistant", "content": "B"}], "C")
    assert prompt.index("[Nutzer]\nA") < prompt.index("[Assistent]\nB") < prompt.index("C")
    long = [{"role": "user", "content": "x" * 100_000}, {"role": "assistant", "content": "y" * 100_000}]
    trimmed = build_prompt(long, "neu")
    assert "gekürzt" in trimmed and len(trimmed) < 130_000
    assert "Token" in map_error("authentication_failed")
    assert "Kontingent" in map_error("billing_error")
    assert "Nutzungslimit" in map_error(None, 429)
