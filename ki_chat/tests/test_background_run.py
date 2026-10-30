"""Antworten laufen auf dem Server weiter: Chat wechseln, Seite neu laden oder Tab schließen verliert nichts."""
import asyncio
import json

from fastapi.testclient import TestClient

from app.backend import BackendError
from app.config import parse_settings
from app.main import build_ingress_app
from conftest import ADM01, RAW, as_user

SETTINGS = parse_settings(RAW, frozenset({"testclient"}))


class SlowBackend:
    """Liefert Stücke mit Pausen; ``hold`` lässt die Antwort nach dem ersten Stück stehen."""

    def __init__(self, pieces=("Hallo ", "Welt"), pause=0.05, hold=False, error=None, lead=0.0):
        self.pieces, self.pause, self.hold, self.error, self.lead = list(pieces), pause, hold, error, lead
        self.calls = []

    async def stream(self, history, message, effort, attachments=None, instructions=None, **_):
        self.calls.append({"history": history, "message": message})
        if self.lead:
            await asyncio.sleep(self.lead)
        for i, piece in enumerate(self.pieces):
            if i:
                await asyncio.sleep(30 if self.hold else self.pause)
            yield piece
        if self.error:
            raise BackendError(self.error)


async def asgi(app, method, path, body=None, user=ADM01, hang_up_after=None):
    """Rohe ASGI-Anfrage; ``hang_up_after`` trennt die Verbindung nach so vielen Antwortstücken (Tab zu / Reload)."""
    raw = json.dumps(body).encode() if body is not None else b""
    headers = [(k.lower().encode(), v.encode()) for k, v in as_user(user, True).items()]
    if raw:
        headers += [(b"content-type", b"application/json"), (b"content-length", str(len(raw)).encode())]
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http",
        "path": path, "raw_path": path.encode(), "query_string": b"", "headers": headers,
        "client": ("testclient", 50000), "server": ("testserver", 80),
    }
    sent = False
    hangup = asyncio.Event()
    if hang_up_after == -1:
        hangup.set()  # Verbindung ist schon weg, bevor irgendetwas ausgeliefert wird

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": raw, "more_body": False}
        await hangup.wait()
        return {"type": "http.disconnect"}

    out = {"status": None, "body": b"", "chunks": 0}

    async def send(message):
        if message["type"] == "http.response.start":
            out["status"] = message["status"]
        elif message["type"] == "http.response.body" and message.get("body"):
            out["body"] += message["body"]
            out["chunks"] += 1
            if hang_up_after and hang_up_after > 0 and out["chunks"] >= hang_up_after:
                hangup.set()

    await app(scope, receive, send)
    return out


def sse(out):
    return [json.loads(b[6:]) for b in out["body"].decode().split("\n\n") if b.startswith("data: ")]


def jget(out):
    return json.loads(out["body"])


def make(store, backend):
    return build_ingress_app(SETTINGS, store, backend)


async def new_chat(app):
    return jget(await asgi(app, "POST", "/api/chats", {}))["id"]


async def chat_info(app, chat_id):
    return next(c for c in jget(await asgi(app, "GET", "/api/chats")) if c["id"] == chat_id)


async def messages(app, chat_id):
    return jget(await asgi(app, "GET", f"/api/chats/{chat_id}/messages"))


async def until(check, seconds=5.0):
    for _ in range(int(seconds / 0.02)):
        if await check():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("Bedingung nicht rechtzeitig erfüllt")


def test_question_is_stored_at_once_and_answer_finishes_after_hangup(store):
    async def scenario():
        app = make(store, SlowBackend(pause=0.2))
        chat_id = await new_chat(app)
        post = asyncio.create_task(
            asgi(app, "POST", f"/api/chats/{chat_id}/send", {"content": "Hallo KI"}, hang_up_after=1)
        )
        await until(lambda: _stored(app, chat_id, 1))
        # Mitten in der Antwort: Frage steht, Chat gilt als laufend, Titel ist schon gesetzt.
        assert [(m["role"], m["content"]) for m in await messages(app, chat_id)] == [("user", "Hallo KI")]
        info = await chat_info(app, chat_id)
        assert info["running"] is True and info["title"] == "Hallo KI" and info["unread"] is False
        await post  # Verbindung wurde getrennt
        # Die Antwort läuft trotzdem zu Ende, wird gespeichert und ist ungelesen.
        await until(lambda: _stored(app, chat_id, 2))
        assert [(m["role"], m["content"]) for m in await messages(app, chat_id)] == [
            ("user", "Hallo KI"), ("assistant", "Hallo Welt"),
        ]
        info = await chat_info(app, chat_id)
        assert info["running"] is False and info["unread"] is True

    asyncio.run(scenario())


async def _stored(app, chat_id, count):
    return len(await messages(app, chat_id)) >= count


def test_reloaded_page_can_attach_and_gets_the_text_so_far(store):
    async def scenario():
        app = make(store, SlowBackend(pause=0.3))
        chat_id = await new_chat(app)
        first = asyncio.create_task(
            asgi(app, "POST", f"/api/chats/{chat_id}/send", {"content": "Frage"}, hang_up_after=1)
        )
        await until(lambda: _stored(app, chat_id, 1))
        await first
        late = await asgi(app, "GET", f"/api/chats/{chat_id}/run")
        events = sse(late)
        assert "".join(e["text"] for e in events if e["type"] == "delta") == "Hallo Welt"
        assert events[-1]["type"] == "done"
        await until(lambda: _done(app, chat_id))
        # Nichts läuft mehr: Anhängen liefert nichts.
        assert (await asgi(app, "GET", f"/api/chats/{chat_id}/run"))["status"] == 204

    asyncio.run(scenario())


async def _done(app, chat_id):
    return (await chat_info(app, chat_id))["running"] is False


def test_second_message_while_running_is_rejected(store):
    async def scenario():
        app = make(store, SlowBackend(pause=0.3))
        chat_id = await new_chat(app)
        first = asyncio.create_task(asgi(app, "POST", f"/api/chats/{chat_id}/send", {"content": "eins"}))
        await until(lambda: _stored(app, chat_id, 1))
        second = await asgi(app, "POST", f"/api/chats/{chat_id}/send", {"content": "zwei"})
        assert second["status"] == 409
        await first
        assert [m["content"] for m in await messages(app, chat_id)] == ["eins", "Hallo Welt"]  # "zwei" nie gespeichert

    asyncio.run(scenario())


def test_two_chats_run_side_by_side_and_third_is_refused(store):
    async def scenario():
        app = make(store, SlowBackend(pause=0.3))
        ids = [await new_chat(app) for _ in range(3)]
        tasks = [
            asyncio.create_task(asgi(app, "POST", f"/api/chats/{c}/send", {"content": f"Frage {i}"}))
            for i, c in enumerate(ids[:2])
        ]
        await until(lambda: _both_running(app, ids[:2]))
        refused = await asgi(app, "POST", f"/api/chats/{ids[2]}/send", {"content": "zu viel"})
        assert refused["status"] == 429
        assert await messages(app, ids[2]) == []  # abgelehnt = nichts gespeichert
        await asyncio.gather(*tasks)
        for c in ids[:2]:
            assert [m["role"] for m in await messages(app, c)] == ["user", "assistant"]

    asyncio.run(scenario())


async def _both_running(app, ids):
    return all([(await chat_info(app, c))["running"] for c in ids])


def test_stop_keeps_the_partial_answer(store):
    async def scenario():
        app = make(store, SlowBackend(pieces=("Anfang ", "Rest"), hold=True))
        chat_id = await new_chat(app)
        post = asyncio.create_task(asgi(app, "POST", f"/api/chats/{chat_id}/send", {"content": "Lang"}))
        await until(lambda: _stored(app, chat_id, 1))
        await asyncio.sleep(0.1)  # erstes Stück ist da
        assert (await asgi(app, "POST", f"/api/chats/{chat_id}/stop"))["status"] == 204
        out = await asyncio.wait_for(post, 5)
        assert sse(out)[-1] == {"type": "done", "title": "Lang"}
        assert [(m["role"], m["content"]) for m in await messages(app, chat_id)] == [
            ("user", "Lang"), ("assistant", "Anfang "),
        ]
        assert (await chat_info(app, chat_id))["running"] is False

    asyncio.run(scenario())


def test_stop_before_any_text_withdraws_the_question(store):
    async def scenario():
        app = make(store, SlowBackend(pieces=(), lead=30))
        chat_id = await new_chat(app)
        post = asyncio.create_task(asgi(app, "POST", f"/api/chats/{chat_id}/send", {"content": "Hallo"}))
        await until(lambda: _stored(app, chat_id, 1))
        await asgi(app, "POST", f"/api/chats/{chat_id}/stop")
        out = await asyncio.wait_for(post, 5)
        assert sse(out)[-1]["type"] == "error" or sse(out)[-1]["type"] == "done"
        assert await messages(app, chat_id) == []
        assert (await chat_info(app, chat_id))["title"] == "Neuer Chat"

    asyncio.run(scenario())


def test_failed_run_without_answer_is_withdrawn_but_can_still_be_fetched_once(store):
    async def scenario():
        app = make(store, SlowBackend(pieces=(), error="Anmeldung fehlgeschlagen", lead=0.3))
        chat_id = await new_chat(app)
        post = asyncio.create_task(
            asgi(app, "POST", f"/api/chats/{chat_id}/send", {"content": "Wichtige Frage"}, hang_up_after=-1)
        )
        await post  # Verbindung weg, bevor der Fehler ausgeliefert war
        await until(lambda: _done(app, chat_id))
        assert await messages(app, chat_id) == []
        late = await asgi(app, "GET", f"/api/chats/{chat_id}/run")
        assert sse(late)[-1] == {
            "type": "error", "message": "Anmeldung fehlgeschlagen", "kept": False, "text": "Wichtige Frage",
        }
        assert (await asgi(app, "GET", f"/api/chats/{chat_id}/run"))["status"] == 204  # nur einmal

    asyncio.run(scenario())


def test_partial_answer_survives_hangup_and_error(store):
    async def scenario():
        app = make(store, SlowBackend(pieces=("Teil ", "zwei"), pause=0.05, error="Abbruch"))
        chat_id = await new_chat(app)
        await asgi(app, "POST", f"/api/chats/{chat_id}/send", {"content": "F"}, hang_up_after=1)
        await until(lambda: _stored(app, chat_id, 2))
        assert (await messages(app, chat_id))[1]["content"] == "Teil zwei"

    asyncio.run(scenario())


def test_deleting_a_running_chat_stops_the_answer(store):
    async def scenario():
        backend = SlowBackend(pieces=("a", "b"), hold=True)
        app = make(store, backend)
        chat_id = await new_chat(app)
        post = asyncio.create_task(asgi(app, "POST", f"/api/chats/{chat_id}/send", {"content": "Hi"}))
        await until(lambda: _stored(app, chat_id, 1))
        assert (await asgi(app, "DELETE", f"/api/chats/{chat_id}"))["status"] == 204
        await asyncio.wait_for(post, 5)
        # Der Platz wird frei: ein neuer Chat kann sofort antworten.
        other = await new_chat(app)
        backend.hold = False
        out = await asgi(app, "POST", f"/api/chats/{other}/send", {"content": "Neu"})
        assert out["status"] == 200 and sse(out)[-1]["type"] == "done"

    asyncio.run(scenario())


def test_chats_of_other_profiles_cannot_be_attached_or_stopped(store):
    async def scenario():
        app = make(store, SlowBackend(pause=0.3))
        chat_id = await new_chat(app)
        post = asyncio.create_task(asgi(app, "POST", f"/api/chats/{chat_id}/send", {"content": "privat"}))
        await until(lambda: _stored(app, chat_id, 1))
        from conftest import DORA

        assert (await asgi(app, "GET", f"/api/chats/{chat_id}/run", user=DORA))["status"] == 204
        await asgi(app, "POST", f"/api/chats/{chat_id}/stop", user=DORA)
        out = await post
        assert sse(out)[-1]["type"] == "done"  # läuft ungestört zu Ende
        assert [m["role"] for m in await messages(app, chat_id)] == ["user", "assistant"]

    asyncio.run(scenario())


def test_sync_client_still_gets_the_whole_exchange(store):
    # Der gewöhnliche (blockierende) Weg liefert weiterhin Strom und Ergebnis in einer Anfrage.
    client = TestClient(make(store, SlowBackend(pause=0)))
    chat_id = client.post("/api/chats", json={}, headers=as_user(ADM01, True)).json()["id"]
    response = client.post(f"/api/chats/{chat_id}/send", json={"content": "Hi"}, headers=as_user(ADM01, True))
    assert response.status_code == 200 and '"type": "done"' in response.text
