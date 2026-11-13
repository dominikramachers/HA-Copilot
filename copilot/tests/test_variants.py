"""Mehrere Fassungen der letzten Antwort: „Antwort neu erzeugen“ behält die alte, ``‹ 2/3 ›`` blättert."""
import json

from conftest import ADM01, WRITE, as_user

H = {**as_user(ADM01), **WRITE}


def send(client, chat_id, text="Frage", **extra):
    response = client.post(f"/api/chats/{chat_id}/send", headers=H, json={"content": text, **extra})
    assert response.status_code == 200, response.text
    return response


def chat_with_answer(client, backend, answers):
    chat = client.post("/api/chats", headers=H, json={}).json()["id"]
    backend.pieces = [answers[0]]
    send(client, chat)
    return chat


def messages(client, chat):
    return client.get(f"/api/chats/{chat}/messages", headers=H).json()


def regenerate(client, backend, chat, text):
    msgs = messages(client, chat)
    question = [m for m in msgs if m["role"] == "user"][-1]["id"]
    backend.pieces = [text]
    send(client, chat, edit_message_id=question, regenerate=True)


def test_regenerate_keeps_the_old_answer_as_version(client, backend):
    chat = chat_with_answer(client, backend, ["Erste"])
    assert "variant" not in messages(client, chat)[-1]
    regenerate(client, backend, chat, "Zweite")
    last = messages(client, chat)[-1]
    assert last["content"] == "Zweite" and last["variant"] == {"index": 2, "total": 2}
    regenerate(client, backend, chat, "Dritte")
    assert messages(client, chat)[-1]["variant"] == {"index": 3, "total": 3}


def test_choose_a_version_swaps_the_visible_answer(client, backend):
    chat = chat_with_answer(client, backend, ["Erste"])
    regenerate(client, backend, chat, "Zweite")
    done = client.put(f"/api/chats/{chat}/answer", headers=H, json={"index": 1})
    assert done.status_code == 200 and done.json() == {"index": 1, "total": 2}
    last = messages(client, chat)[-1]
    assert last["content"] == "Erste" and last["variant"]["index"] == 1
    assert client.put(f"/api/chats/{chat}/answer", headers=H, json={"index": 5}).status_code == 404
    assert client.put(f"/api/chats/{chat}/answer", headers=H, json={"index": 0}).status_code == 422


def test_a_new_question_drops_the_versions(client, backend):
    chat = chat_with_answer(client, backend, ["Erste"])
    regenerate(client, backend, chat, "Zweite")
    backend.pieces = ["Weiter"]
    send(client, chat, "Noch eine Frage")
    last = messages(client, chat)[-1]
    assert last["content"] == "Weiter" and "variant" not in last
    assert client.put(f"/api/chats/{chat}/answer", headers=H, json={"index": 1}).status_code == 404


def test_only_the_last_answer_gets_versions(client, backend):
    chat = chat_with_answer(client, backend, ["Erste"])
    backend.pieces = ["Zweite Antwort"]
    send(client, chat, "Zweite Frage")
    first_question = [m for m in messages(client, chat) if m["role"] == "user"][0]["id"]
    backend.pieces = ["Neu"]
    send(client, chat, "Frage", edit_message_id=first_question, regenerate=True)  # nicht die letzte Frage
    assert all("variant" not in m for m in messages(client, chat))


def test_a_normal_edit_drops_the_versions(client, backend):
    chat = chat_with_answer(client, backend, ["Erste"])
    regenerate(client, backend, chat, "Zweite")
    question = [m for m in messages(client, chat) if m["role"] == "user"][-1]["id"]
    backend.pieces = ["Anders"]
    send(client, chat, "Andere Frage", edit_message_id=question)
    assert "variant" not in messages(client, chat)[-1]


def test_at_most_ten_versions(client, backend):
    chat = chat_with_answer(client, backend, ["v1"])
    for n in range(2, 14):
        regenerate(client, backend, chat, f"v{n}")
    last = messages(client, chat)[-1]
    assert last["content"] == "v13" and last["variant"] == {"index": 10, "total": 10}
    client.put(f"/api/chats/{chat}/answer", headers=H, json={"index": 1})
    assert messages(client, chat)[-1]["content"] == "v4"  # die drei ältesten sind weggefallen


def test_failed_regeneration_keeps_the_answer(client, backend):
    chat = chat_with_answer(client, backend, ["Erste"])
    question = [m for m in messages(client, chat) if m["role"] == "user"][-1]["id"]
    backend.pieces = []
    backend.error = "kaputt"
    client.post(f"/api/chats/{chat}/send", headers=H, json={"content": "Frage", "edit_message_id": question, "regenerate": True})
    backend.error = None
    last = messages(client, chat)[-1]
    assert last["content"] == "Erste" and "variant" not in last
