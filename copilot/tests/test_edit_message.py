"""Eine eigene Nachricht bearbeiten: Die Frage und alles danach wird durch die neue Frage und Antwort ersetzt."""
import asyncio

from test_background_run import SlowBackend, asgi, jget, make, messages, new_chat, sse



async def send(app, chat_id, text, **extra):
    return await asgi(app, "POST", f"/api/chats/{chat_id}/send", {"content": text, **extra})


def contents(rows):
    return [(m["role"], m["content"]) for m in rows]


def test_edit_replaces_question_and_everything_after(store):
    async def scenario():
        backend = SlowBackend(pieces=("Antwort",), pause=0)
        app = make(store, backend)
        chat_id = await new_chat(app)
        await send(app, chat_id, "eins")
        await send(app, chat_id, "zwei")
        rows = await messages(app, chat_id)
        assert [m["content"] for m in rows] == ["eins", "Antwort", "zwei", "Antwort"]
        first_id = rows[0]["id"]
        out = await send(app, chat_id, "eins neu", edit_message_id=first_id)
        assert out["status"] == 200
        assert any(e["type"] == "done" for e in sse(out))
        after = await messages(app, chat_id)
        assert contents(after) == [("user", "eins neu"), ("assistant", "Antwort")]
        # Claude sieht von der alten Unterhaltung nichts mehr
        assert backend.calls[-1]["history"] == [] and backend.calls[-1]["message"] == "eins neu"

    asyncio.run(scenario())


def test_edit_a_later_question_keeps_the_earlier_ones(store):
    async def scenario():
        backend = SlowBackend(pieces=("A",), pause=0)
        app = make(store, backend)
        chat_id = await new_chat(app)
        await send(app, chat_id, "eins")
        await send(app, chat_id, "zwei")
        second = (await messages(app, chat_id))[2]
        await send(app, chat_id, "zwei neu", edit_message_id=second["id"])
        assert contents(await messages(app, chat_id)) == [
            ("user", "eins"), ("assistant", "A"), ("user", "zwei neu"), ("assistant", "A"),
        ]
        assert [h["content"] for h in backend.calls[-1]["history"]] == ["eins", "A"]

    asyncio.run(scenario())


def test_failed_edit_without_answer_restores_the_old_conversation(store):
    async def scenario():
        good = SlowBackend(pieces=("Alt",), pause=0)
        app = make(store, good)
        chat_id = await new_chat(app)
        await send(app, chat_id, "eins")
        await send(app, chat_id, "zwei")
        before = await messages(app, chat_id)
        # Dieselbe Datenbank, aber Claude liefert diesmal nichts als einen Fehler.
        bad = make(store, SlowBackend(pieces=(), pause=0, error="kaputt"))
        out = await send(bad, chat_id, "eins neu", edit_message_id=before[0]["id"])
        assert any(e["type"] == "error" for e in sse(out))
        after = await messages(bad, chat_id)
        assert contents(after) == contents(before)
        assert [m["id"] for m in after] == [m["id"] for m in before]  # auch die Nummern bleiben

    asyncio.run(scenario())


def test_edit_is_limited_to_own_questions_in_this_chat(store):
    async def scenario():
        app = make(store, SlowBackend(pieces=("A",), pause=0))
        chat_id = await new_chat(app)
        other_chat = await new_chat(app)
        await send(app, chat_id, "eins")
        await send(app, other_chat, "fremd")
        rows = await messages(app, chat_id)
        foreign = (await messages(app, other_chat))[0]
        # Antwort-Nachricht, Nachricht aus einem anderen Chat und unbekannte Nummer: nichts wird verändert.
        for bad in (rows[1]["id"], foreign["id"], 99999):
            out = await send(app, chat_id, "neu", edit_message_id=bad)
            assert out["status"] == 404
        assert contents(await messages(app, chat_id)) == [("user", "eins"), ("assistant", "A")]
        assert contents(await messages(app, other_chat)) == [("user", "fremd"), ("assistant", "A")]

    asyncio.run(scenario())


def test_edit_clears_a_summary_that_reaches_into_the_removed_part(store):
    async def scenario():
        app = make(store, SlowBackend(pieces=("A",), pause=0))
        chat_id = await new_chat(app)
        await send(app, chat_id, "eins")
        await send(app, chat_id, "zwei")
        rows = await messages(app, chat_id)
        store.set_summary("adm01", chat_id, "Kurzfassung", rows[1]["id"])
        # Bearbeiten nach der Zusammenfassung: sie bleibt.
        await send(app, chat_id, "zwei neu", edit_message_id=rows[2]["id"])
        assert store.get_summary("adm01", chat_id)[0] == "Kurzfassung"
        # Bearbeiten mitten in der Zusammenfassung: sie wird verworfen.
        await send(app, chat_id, "eins neu", edit_message_id=rows[0]["id"])
        assert store.get_summary("adm01", chat_id) == (None, None)

    asyncio.run(scenario())
