"""Auf einen Ausschnitt einer Antwort antworten: Zitatblock vor der Nachricht, im Verlauf, für die KI und im Titel."""
import asyncio
import re
from pathlib import Path

from app import quotes
from test_background_run import SlowBackend, asgi, make, messages, new_chat, sse

APP = Path(__file__).resolve().parent.parent / "app"


def test_with_quote_and_split_are_inverse():
    text = quotes.with_quote("Zeile eins\n\nZeile drei", "Meine Frage")
    assert text == "> Zeile eins\n>\n> Zeile drei\n\nMeine Frage"
    assert quotes.split_quote(text) == ("Zeile eins\n\nZeile drei", "Meine Frage")
    assert quotes.with_quote(None, "x") == "x" and quotes.with_quote("  \n ", "x") == "x"


def test_plain_text_is_not_mistaken_for_a_quote():
    for content in ("> nur zitiert, ohne eigenen Text", "Hallo\n> kein Zitat", "> a\nb", "ohne"):
        assert quotes.split_quote(content) == ("", content)


def test_quote_is_cleaned_and_limited():
    assert quotes.clean("  a \r\n\r\n\r\n\r\nb  ") == "a\n\nb"
    long = quotes.clean("x" * 5000)
    assert len(long) == quotes.QUOTE_MAX + 1 and long.endswith("…")


def test_send_stores_the_quote_and_gives_it_to_claude(store):
    async def scenario():
        backend = SlowBackend(pieces=("Antwort",), pause=0)
        app = make(store, backend)
        chat_id = await new_chat(app)
        out = await asgi(app, "POST", f"/api/chats/{chat_id}/send", {"content": "Erkläre das genauer", "quote": "Wirkungsgrad und\nDrehmoment"})
        assert out["status"] == 200 and any(e["type"] == "done" for e in sse(out))
        expected = "> Wirkungsgrad und\n> Drehmoment\n\nErkläre das genauer"
        assert backend.calls[-1]["message"] == expected
        rows = await messages(app, chat_id)
        assert [m["content"] for m in rows if m["role"] == "user"] == [expected]
        # der Titel stammt aus der eigenen Frage, nicht aus dem Zitat
        chat = next(c for c in store.list_chats("adm01") if c["id"] == chat_id)
        assert "Wirkungsgrad" not in chat["title"]

    asyncio.run(scenario())


def test_edit_keeps_working_with_a_quote(store):
    async def scenario():
        backend = SlowBackend(pieces=("A",), pause=0)
        app = make(store, backend)
        chat_id = await new_chat(app)
        await asgi(app, "POST", f"/api/chats/{chat_id}/send", {"content": "eins", "quote": "Zitat"})
        first = (await messages(app, chat_id))[0]["id"]
        await asgi(app, "POST", f"/api/chats/{chat_id}/send", {"content": "eins neu", "quote": "Zitat", "edit_message_id": first})
        users = [m["content"] for m in await messages(app, chat_id) if m["role"] == "user"]
        assert users == ["> Zitat\n\neins neu"]

    asyncio.run(scenario())


def test_send_without_quote_is_unchanged(store):
    async def scenario():
        backend = SlowBackend(pieces=("A",), pause=0)
        app = make(store, backend)
        chat_id = await new_chat(app)
        await asgi(app, "POST", f"/api/chats/{chat_id}/send", {"content": "nur Text"})
        assert backend.calls[-1]["message"] == "nur Text"

    asyncio.run(scenario())


def test_ui_has_quote_bar_picker_and_matching_format():
    html = (APP / "static" / "index.html").read_text(encoding="utf-8")
    js = (APP / "static" / "app.js").read_text(encoding="utf-8")
    assert 'id="quote-bar"' in html and html.index('id="quote-bar"') < html.index('id="attach-tray"')  # Leiste liegt im Eingabefeld, über den Anhängen
    for needle in ("function initQuotePicker", "function setQuote", "function withQuote", "function splitQuote", "quote-x", "selectionchange", "...(quote ? { quote } : {})"):
        assert needle in js, needle
    assert re.search(r"const QUOTE_MAX = %d;" % quotes.QUOTE_MAX, js)  # gleiche Grenze wie im Backend
    assert js.count('setQuote("")') >= 3  # beim Senden und beim Wechsel des Chats wird das Zitat verworfen
