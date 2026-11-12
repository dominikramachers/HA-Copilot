"""ChatGPT (OpenAI, Responses-API): Backend, Verteiler und Einbindung in die App. Die Schnittstelle von OpenAI ist nachgebaut
(``httpx.MockTransport`` mit Server-Sent-Events); echte Anfragen an OpenAI gehen aus den Tests nie hinaus."""
import asyncio
import json

import httpx
import pytest

from app.attachments import Attachment
from app.backend import BackendError
from app.backend_openai import OpenAIBackend, history_items, map_openai_error, user_content
from app.backend_router import RouterBackend
from app.config import ConfigError, model_label, parse_settings, provider_of
from app.ha_tools import ToolError, ToolResult, ToolSpec
from app.main import build_ingress_app
from conftest import ADM01, DORA, RAW, FakeBackend, parse_with_fixed
from test_background_run import asgi, jget, new_chat, sse, until


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- Nachbau der OpenAI-Schnittstelle

def sse_body(events: list[dict]) -> bytes:
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def message_item(text: str) -> dict:
    return {"type": "message", "id": "msg_1", "role": "assistant", "content": [{"type": "output_text", "text": text}]}


def answer(text: str, tokens: int = 30, chunks: int = 2) -> list[dict]:
    """Eine Antwort nur mit Text, in ``chunks`` Stücken."""
    step = max(1, len(text) // chunks)
    pieces = [text[i:i + step] for i in range(0, len(text), step)]
    events = [{"type": "response.output_text.delta", "delta": p} for p in pieces]
    events.append({"type": "response.completed", "response": {"output": [message_item(text)], "usage": {"input_tokens": tokens - 10, "output_tokens": 10, "total_tokens": tokens}}})
    return events


def call(name: str, args: dict, call_id: str = "call_1") -> list[dict]:
    """Eine Runde, in der das Modell ein Werkzeug anfordert (mit verschlüsseltem Denkverlauf davor)."""
    reasoning = {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "ENC"}
    fn = {"type": "function_call", "id": "fc_1", "call_id": call_id, "name": name, "arguments": json.dumps(args)}
    return [
        {"type": "response.output_item.done", "item": reasoning},
        {"type": "response.output_item.done", "item": fn},
        {"type": "response.completed", "response": {"output": [reasoning, fn], "usage": {"total_tokens": 100}}},
    ]


class FakeOpenAI:
    """Beantwortet Anfragen der Reihe nach mit vorbereiteten Ereignislisten oder Fehlern und merkt sich, was gesendet wurde."""

    def __init__(self, *turns):
        self.turns = list(turns)
        self.requests: list[dict] = []
        self.headers: list[httpx.Headers] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.content))
        self.headers.append(request.headers)
        turn = self.turns.pop(0)
        if isinstance(turn, httpx.Response):
            return turn
        return httpx.Response(200, content=sse_body(turn), headers={"content-type": "text/event-stream"})

    def backend(self) -> OpenAIBackend:
        return OpenAIBackend("sk-test-key", "gpt-5.6-terra", transport=httpx.MockTransport(self))


def error_response(status: int, code: str, message: str = "x", headers: dict | None = None, param: str | None = None) -> httpx.Response:
    return httpx.Response(status, json={"error": {"message": message, "code": code, "type": code, "param": param}}, headers=headers or {})


async def collect(backend, *args, **kwargs) -> str:
    return "".join([piece async for piece in backend.stream(*args, **kwargs)])


def spec(name="ha_ping", handler=None, **kw) -> ToolSpec:
    async def default(args):
        return f"pong {args.get('n', '')}"

    return ToolSpec(name, "Test", {"type": "object", "properties": {"n": {"type": "integer"}}}, handler or default, **kw)


# ------------------------------------------------------------------ Modellnamen und Konfiguration

def test_provider_and_labels():
    assert provider_of("gpt-5.6-terra") == "openai" and provider_of("o4-mini") == "openai" and provider_of("claude-opus-5-5") == "claude"
    assert provider_of("") == "claude" and provider_of("sonnet") == "claude"
    assert model_label("gpt-5.6-terra") == "GPT-5.6 Terra"
    assert model_label("gpt-5.6-sol") == "GPT-5.6 Sol"
    assert model_label("gpt-4o-mini") == "GPT-4o Mini"
    assert model_label("o4-mini") == "o4-mini"


def test_openai_is_off_by_default_and_needs_a_key():
    s = parse_settings(RAW, frozenset())
    assert s.openai_enabled is False and s.openai_active is False and s.openai_limit_month == 3000
    assert s.openai_models == ("gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.6-sol")
    assert [c["provider"] for c in s.model_choices()] == ["claude"] * 3
    on_without_key = parse_settings({**RAW, "openai_enabled": True}, frozenset())
    assert on_without_key.openai_active is False and all(c["provider"] == "claude" for c in on_without_key.model_choices())
    on = parse_settings({**RAW, "openai_enabled": True, "openai_chat_api_key": "sk-x"}, frozenset())
    assert on.openai_active is True
    assert [c["id"] for c in on.model_choices()] == ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.6-sol"]
    assert [c["label"] for c in on.model_choices()][-3:] == ["GPT-5.6 Terra", "GPT-5.6 Luna", "GPT-5.6 Sol"]
    assert [c["provider"] for c in on.model_choices()][-3:] == ["openai"] * 3


def test_openai_uses_the_image_key_when_there_is_no_own_one():
    s = parse_settings({**RAW, "openai_enabled": True, "openai_api_key": "sk-images"}, frozenset())
    assert s.openai_chat_key == "sk-images" and s.openai_active
    own = parse_settings({**RAW, "openai_enabled": True, "openai_api_key": "sk-images", "openai_chat_api_key": "sk-chat"}, frozenset())
    assert own.openai_chat_key == "sk-chat"
    assert "sk-chat" not in repr(own) and "sk-images" not in repr(own)  # Schlüssel stehen nie in Protokollen


def test_openai_model_list_and_limit_are_validated():
    s = parse_settings({**RAW, "openai_enabled": True, "openai_chat_api_key": "k", "openai_models": "gpt-5.6-luna, gpt-4o"}, frozenset())
    assert s.openai_models == ("gpt-5.6-luna", "gpt-4o")
    assert parse_settings({**RAW, "openai_models": ""}, frozenset()).openai_models == ("gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.6-sol")
    with pytest.raises(ConfigError):
        parse_settings({**RAW, "openai_models": "claude-opus-5-5"}, frozenset())
    with pytest.raises(ConfigError):
        parse_settings({**RAW, "openai_models": "gpt-a1, gpt-a2, gpt-a3, gpt-a4, gpt-a5, gpt-a6, gpt-a7"}, frozenset())
    assert parse_settings({**RAW, "openai_limit_month": 0}, frozenset()).openai_limit_month == 0
    for bad in (-1, 100001, "viel"):
        with pytest.raises(ConfigError):
            parse_settings({**RAW, "openai_limit_month": bad}, frozenset())
    with pytest.raises(ConfigError):
        parse_settings({**RAW, "openai_chat_key_expires": "morgen"}, frozenset())


def test_voice_stays_on_claude_haiku():
    s = parse_settings({**RAW, "openai_enabled": True, "openai_chat_api_key": "k"}, frozenset())
    assert provider_of(s.voice_model) == "claude" and s.voice_model == "claude-haiku-5-5"


# ----------------------------------------------------------------------------- Text und Verlauf

def test_streams_text_and_sends_the_right_request():
    fake = FakeOpenAI(answer("Hallo Welt, das ist die Antwort.", tokens=42))
    used = []
    history = [{"role": "user", "content": "Frage 1"}, {"role": "assistant", "content": "Antwort 1"}]
    text = run(collect(fake.backend(), history, "Frage 2", "high", instructions="Projektregel", personal_instructions="Duze mich", note="Notiz der Sitzung", on_usage=used.append))
    assert text == "Hallo Welt, das ist die Antwort."
    assert used == [42]
    body = fake.requests[0]
    assert body["model"] == "gpt-5.6-terra" and body["stream"] is True and body["store"] is False  # nichts bei OpenAI aufbewahren
    assert body["include"] == ["reasoning.encrypted_content"] and body["reasoning"] == {"effort": "high"}
    assert "tools" not in body
    for needle in ("Notiz der Sitzung", "Projektregel", "Duze mich"):
        assert needle in body["instructions"]
    assert body["input"] == [
        {"role": "user", "content": "Frage 1"},
        {"role": "assistant", "content": "Antwort 1"},
        {"role": "user", "content": [{"type": "input_text", "text": "Frage 2"}]},
    ]
    assert fake.headers[0]["authorization"] == "Bearer sk-test-key"
    assert str(fake.requests[0]).count("sk-test-key") == 0  # der Schlüssel steht nur im Kopf, nicht im Inhalt


def test_model_override_wins_over_the_default():
    fake = FakeOpenAI(answer("ok"))
    run(collect(fake.backend(), [], "Hi", "low", model="gpt-5.6-sol"))
    assert fake.requests[0]["model"] == "gpt-5.6-sol" and fake.requests[0]["reasoning"] == {"effort": "low"}


def test_history_summary_stays_and_old_messages_drop_first(monkeypatch):
    monkeypatch.setattr("app.backend_openai.MAX_HISTORY_CHARS", 200)
    history = [
        {"role": "summary", "content": "Kurzfassung"},
        {"role": "user", "content": "a" * 60},
        {"role": "assistant", "content": "b" * 30},
        {"role": "user", "content": "c" * 10},
    ]
    items = history_items(history, reserved=5)
    assert items[0]["content"].endswith("Kurzfassung")
    assert items[1]["content"].startswith("[… ältere Nachrichten")
    assert [i["content"] for i in items[2:]] == ["b" * 30, "c" * 10]
    assert history_items([], 0) == []


def test_attachments_become_input_parts():
    image = Attachment("foto.png", "image", "image/png", b"\x89PNG")
    pdf = Attachment("a.pdf", "pdf", "application/pdf", b"%PDF-1.4")
    note = Attachment("n.txt", "text", "text/plain", b"hello")
    parts = user_content("Schau", [image, pdf, note])
    assert parts[0]["type"] == "input_image" and parts[0]["image_url"].startswith("data:image/png;base64,")
    assert parts[1]["type"] == "input_file" and parts[1]["filename"] == "a.pdf" and parts[1]["file_data"].startswith("data:application/pdf;base64,")
    assert parts[-1] == {"type": "input_text", "text": "Schau"} and len(parts) == 3  # Text steht schon im Prompt
    fake = FakeOpenAI(answer("gesehen"))
    run(collect(fake.backend(), [], "Was ist das?", "low", attachments=[image, note]))
    content = fake.requests[0]["input"][-1]["content"]
    assert [p["type"] for p in content] == ["input_image", "input_text"] and "hello" in content[-1]["text"]


# --------------------------------------------------------------------------------- Werkzeuge

def test_tool_loop_runs_handler_and_sends_results_back():
    seen = []

    async def handler(args):
        seen.append(args)
        return "pong 7"

    fake = FakeOpenAI(call("ha_ping", {"n": 7}), answer("Fertig: pong 7"))
    text = run(collect(fake.backend(), [], "Ping", "medium", tools=[spec(handler=handler)], note="n"))
    assert seen == [{"n": 7}] and text == "Fertig: pong 7"
    first, second = fake.requests
    assert first["tools"] == [{"type": "function", "name": "ha_ping", "description": "Test", "parameters": {"type": "object", "properties": {"n": {"type": "integer"}}}, "strict": False}]
    assert first["parallel_tool_calls"] is False
    # zweite Runde: bisherige Eingabe, Ausgabe der ersten Runde (samt verschlüsseltem Denkverlauf) und das Werkzeugergebnis
    tail = second["input"][len(first["input"]):]
    assert [i["type"] for i in tail] == ["reasoning", "function_call", "function_call_output"]
    assert tail[0]["encrypted_content"] == "ENC"
    assert tail[2] == {"type": "function_call_output", "call_id": "call_1", "output": "pong 7"}
    assert second["store"] is False


def test_text_before_and_after_a_tool_call_is_separated():
    first = [{"type": "response.output_text.delta", "delta": "Ich schaue nach."}, *call("ha_ping", {})]
    fake = FakeOpenAI(first, answer("Erledigt."))
    assert run(collect(fake.backend(), [], "Los", "low", tools=[spec()])) == "Ich schaue nach.\n\nErledigt."


def test_tool_errors_are_reported_to_the_model_not_raised():
    async def failing(args):
        raise ToolError("Das darfst du nicht.")

    async def crashing(args):
        raise RuntimeError("intern: geheim")

    for handler, expected in ((failing, "Das darfst du nicht."), (crashing, "Das Werkzeug ist unerwartet fehlgeschlagen.")):
        fake = FakeOpenAI(call("ha_ping", {}), answer("ok"))
        run(collect(fake.backend(), [], "x", "low", tools=[spec(handler=handler)]))
        output = fake.requests[1]["input"][-1]
        assert output["output"] == expected and "geheim" not in json.dumps(fake.requests[1])


def test_unknown_tool_and_broken_arguments():
    fake = FakeOpenAI(call("gibt_es_nicht", {}), answer("ok"))
    run(collect(fake.backend(), [], "x", "low", tools=[spec()]))
    assert fake.requests[1]["input"][-1]["output"] == "Unbekanntes Werkzeug."
    broken = [{"type": "response.completed", "response": {"output": [{"type": "function_call", "call_id": "c", "name": "ha_ping", "arguments": "{kaputt"}]}}]
    fake = FakeOpenAI(broken, answer("ok"))
    run(collect(fake.backend(), [], "x", "low", tools=[spec()]))
    assert "kein gültiges JSON" in fake.requests[1]["input"][-1]["output"]


def test_tool_result_is_clipped_and_images_follow_as_a_user_message():
    async def big(args):
        return ToolResult("x" * 60_000, [(b"PNGDATA", "image/png")])

    fake = FakeOpenAI(call("ha_ping", {}), answer("ok"))
    run(collect(fake.backend(), [], "x", "low", tools=[spec(handler=big)]))
    tail = fake.requests[1]["input"][-2:]
    assert tail[0]["type"] == "function_call_output" and len(tail[0]["output"]) < 46_000 and "gekürzt" in tail[0]["output"]
    assert tail[1]["role"] == "user" and tail[1]["content"][1]["type"] == "input_image"
    assert tail[1]["content"][1]["image_url"].startswith("data:image/png;base64,")


def test_too_many_tool_rounds_stop_with_a_note(monkeypatch):
    monkeypatch.setattr("app.backend_openai.MAX_TOOL_TURNS", 3)
    fake = FakeOpenAI(call("ha_ping", {}), call("ha_ping", {}), call("ha_ping", {}))
    text = run(collect(fake.backend(), [], "x", "low", tools=[spec()]))
    assert "zu viele Werkzeugaufrufe" in text and len(fake.requests) == 3


def test_web_search_is_a_hosted_tool_and_shows_up_as_an_action():
    events = []
    item = {"type": "web_search_call", "id": "ws_1", "status": "completed", "action": {"type": "search", "query": "pellet preise"}}
    turn = [
        {"type": "response.output_item.added", "item": {"type": "web_search_call", "id": "ws_1", "status": "in_progress"}},
        {"type": "response.output_item.done", "item": item},
        *answer("Quellen: https://example.org"),
    ]
    fake = FakeOpenAI(turn)
    ids = iter(range(1, 50))
    text = run(collect(fake.backend(), [], "Recherchiere", "low", web=True, record=events.append, next_id=lambda: next(ids)))
    assert {"type": "web_search"} in fake.requests[0]["tools"] and "WebSearch" not in fake.requests[0]["instructions"]
    assert [(e["status"], e["kind"]) for e in events] == [("running", "web"), ("ok", "web")]
    assert events[0]["id"] == events[1]["id"] and "pellet preise" in events[1]["label"]
    assert text.startswith("Quellen")


# ---------------------------------------------------------------------------------- Fehler

@pytest.mark.parametrize(
    "response, fragment",
    [
        (error_response(401, "invalid_api_key"), "Anmeldung bei OpenAI"),
        (error_response(429, "insufficient_quota"), "Guthaben"),
        (error_response(404, "model_not_found"), "gpt-5.6-terra"),
        (error_response(403, "forbidden", "Your organization must be verified to use this model"), "Verifizierung"),
        (error_response(400, "context_length_exceeded"), "zu lang"),
        (error_response(500, "server_error"), "nicht erreichbar"),
        (error_response(400, "invalid_prompt", "Das ist verboten"), "Das ist verboten"),
        (httpx.Response(502, text="<html>Bad Gateway</html>"), "nicht erreichbar"),
    ],
)
def test_http_errors_become_readable_messages(response, fragment):
    fake = FakeOpenAI(response)
    with pytest.raises(BackendError) as info:
        run(collect(fake.backend(), [], "x", "low"))
    assert fragment in info.value.user_message
    assert "sk-test-key" not in info.value.user_message


def test_rate_limit_carries_the_reset_time():
    fake = FakeOpenAI(error_response(429, "rate_limit_exceeded", headers={"retry-after": "120"}))
    with pytest.raises(BackendError) as info:
        run(collect(fake.backend(), [], "x", "low"))
    assert "Nutzungslimit" in info.value.user_message and info.value.resets_at is not None


def test_failed_stream_events_and_cut_connections():
    failed = [{"type": "response.failed", "response": {"error": {"code": "server_error", "message": "boom"}}}]
    with pytest.raises(BackendError) as info:
        run(collect(FakeOpenAI(failed).backend(), [], "x", "low"))
    assert "nicht erreichbar" in info.value.user_message
    cut = [{"type": "response.output_text.delta", "delta": "Halb"}]  # kein „completed“
    with pytest.raises(BackendError) as info:
        run(collect(FakeOpenAI(cut).backend(), [], "x", "low"))
    assert "abgebrochen" in info.value.user_message

    def refuse(request):
        raise httpx.ConnectError("kein Netz")

    with pytest.raises(BackendError) as info:
        run(collect(OpenAIBackend("k", "gpt-5.6-terra", transport=httpx.MockTransport(refuse)), [], "x", "low"))
    assert "Verbindung zu OpenAI" in info.value.user_message


def test_models_without_reasoning_are_retried_without_it():
    unsupported = error_response(400, "unsupported_parameter", "Unsupported parameter: 'reasoning.effort' is not supported with this model.", param="reasoning.effort")
    fake = FakeOpenAI(unsupported, answer("ok"))
    assert run(collect(fake.backend(), [], "x", "low", model="gpt-4o")) == "ok"
    assert "reasoning" in fake.requests[0] and "reasoning" not in fake.requests[1] and "include" in fake.requests[1]


def test_incomplete_answer_without_text_is_an_error_but_filtering_always_is():
    incomplete = [{"type": "response.incomplete", "response": {"output": [], "incomplete_details": {"reason": "max_output_tokens"}}}]
    with pytest.raises(BackendError):
        run(collect(FakeOpenAI(incomplete).backend(), [], "x", "low"))
    filtered = [{"type": "response.output_text.delta", "delta": "Teil"}, {"type": "response.incomplete", "response": {"output": [], "incomplete_details": {"reason": "content_filter"}}}]
    with pytest.raises(BackendError):
        run(collect(FakeOpenAI(filtered).backend(), [], "x", "low"))


def test_error_mapping_directly():
    assert "Guthaben" in map_openai_error(429, {"error": {"message": "You exceeded your current quota", "code": "x"}}).user_message
    assert "Unbekannter Fehler" in map_openai_error(418).user_message
    with pytest.raises(BackendError):
        OpenAIBackend("", "gpt-5.6-terra")


def test_cancelling_stops_the_request():
    started = asyncio.Event()

    async def scenario():
        def handler(request):
            return httpx.Response(200, content=sse_body(answer("x" * 10)))

        backend = OpenAIBackend("k", "gpt-5.6-terra", transport=httpx.MockTransport(handler))

        async def consume():
            async for _ in backend.stream([], "x", "low"):
                started.set()
                await asyncio.sleep(10)

        task = asyncio.create_task(consume())
        await asyncio.wait_for(started.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    run(scenario())


# ------------------------------------------------------------------ Titel und Zusammenfassung

def test_title_and_summary_use_openai_and_clean_the_result():
    out = {"output": [message_item("„Heizung einstellen“.")], "usage": {"total_tokens": 12}}
    fake = FakeOpenAI(httpx.Response(200, json=out), httpx.Response(200, json={"output": [message_item("Zusammenfassung des Gesprächs")], "usage": {"total_tokens": 20}}))
    backend = fake.backend()
    used = []
    assert run(backend.title("Wie stelle ich die Heizung ein?", "So geht es …", model="gpt-5.6-luna", on_usage=used.append)) == "Heizung einstellen"
    assert run(backend.summarize(None, [{"role": "user", "content": "Hallo"}], model="gpt-5.6-luna", on_usage=used.append)) == "Zusammenfassung des Gesprächs"
    assert used == [12, 20] and fake.requests[0]["model"] == "gpt-5.6-luna" and fake.requests[0]["store"] is False and "stream" not in fake.requests[0]


def test_title_failure_is_not_fatal():
    fake = FakeOpenAI(error_response(500, "server_error"), error_response(500, "server_error"))
    assert run(fake.backend().title("a", "b")) is None
    assert run(fake.backend().summarize(None, [{"role": "user", "content": "Hallo"}])) is None


# ----------------------------------------------------------------------------------- Verteiler

def test_router_picks_the_provider_by_model_and_keeps_chats_apart():
    async def scenario():
        claude = FakeBackend(("von Claude",))
        fake = FakeOpenAI(answer("von OpenAI"), httpx.Response(200, json={"output": [message_item("Titel Eins")]}))
        router = RouterBackend(claude, fake.backend())
        assert "".join([p async for p in router.stream([], "Hi", "low")]) == "von Claude"
        assert "".join([p async for p in router.stream([], "Hi", "low", model="claude-opus-5-5")]) == "von Claude"
        assert len(fake.requests) == 0
        assert "".join([p async for p in router.stream([], "Hi", "low", model="gpt-5.6-sol")]) == "von OpenAI"
        assert len(claude.calls) == 2 and len(fake.requests) == 1
        assert await router.title("Frage", "Antwort", model="gpt-5.6-sol") == "Titel Eins"  # Titel eines ChatGPT-Chats nie über Claude
        assert len(claude.calls) == 2

    run(scenario())


def test_router_without_openai_refuses_gpt_models():
    router = RouterBackend(FakeBackend())

    async def scenario():
        with pytest.raises(BackendError) as info:
            [p async for p in router.stream([], "Hi", "low", model="gpt-5.6-sol")]
        assert "nicht eingerichtet" in info.value.user_message

    run(scenario())


# ----------------------------------------------------------------------- App: Modellwahl und Limit

class Recorder:
    """Backend für App-Tests: merkt sich Modell und Hilfsfunktionen jeder Anfrage."""

    def __init__(self, tokens: int = 0):
        self.calls = []
        self.tokens = tokens
        self.titles = []
        self.summaries = []

    async def stream(self, history, message, effort, attachments=None, instructions=None, tools=None, note="", **kw):
        self.calls.append({"model": kw.get("model"), "kw": sorted(kw), "history": history})
        if kw.get("on_usage") and self.tokens:
            kw["on_usage"](self.tokens)
        yield "Antwort"

    async def title(self, user_text, answer, model=None, **kw):
        self.titles.append(model)
        return "Ein Titel"

    async def summarize(self, previous, messages, model=None, **kw):
        self.summaries.append(model)
        return "Zusammenfassung"


def gpt_app(store, backend=None, **options):
    settings = parse_with_fixed({**RAW, "openai_enabled": True, "openai_chat_api_key": "sk-test", **options}, frozenset({"testclient"}))
    backend = backend or Recorder()
    return build_ingress_app(settings, store, backend), backend


def test_me_lists_gpt_models_only_when_enabled(store):
    async def scenario():
        app, _ = gpt_app(store)
        me = jget(await asgi(app, "GET", "/api/me"))
        assert [m["id"] for m in me["models"]][-3:] == ["gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.6-sol"]
        assert me["openai"] is True and me["user_model"] == "" and me["default_model"] == "claude-sonnet-5-5"
        app, _ = gpt_app(store, openai_enabled=False)
        me = jget(await asgi(app, "GET", "/api/me"))
        assert all(m["provider"] == "claude" for m in me["models"]) and me["openai"] is False
        rejected = await asgi(app, "POST", f"/api/chats/{await new_chat(app)}/send", {"content": "Hi", "model": "gpt-5.6-sol"})
        assert rejected["status"] == 422  # ausgeschaltet = nicht wählbar

    run(scenario())


def test_gpt_chat_uses_the_gpt_model_and_counts_tokens(store):
    async def scenario():
        app, backend = gpt_app(store, backend=Recorder(tokens=1500))
        chat = await new_chat(app)
        await asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Hi", "model": "gpt-5.6-luna"})
        assert backend.calls[-1]["model"] == "gpt-5.6-luna" and "on_usage" in backend.calls[-1]["kw"]
        month = __import__("datetime").datetime.now().strftime("%Y-%m")
        assert store.token_usage("adm01", month, "openai") == 1500 and store.token_usage("dora", month, "openai") == 0
        listed = {c["id"]: c for c in jget(await asgi(app, "GET", "/api/chats"))}
        assert listed[chat]["model"] == "gpt-5.6-luna"
        # Claude-Chats zählen nichts und bekommen keinen Zähler
        other = await new_chat(app)
        await asgi(app, "POST", f"/api/chats/{other}/send", {"content": "Hi"})
        assert "on_usage" not in backend.calls[-1]["kw"] and store.token_usage("adm01", month, "openai") == 1500
        usage = jget(await asgi(app, "GET", "/api/usage"))["openai"]
        assert usage == {"enabled": True, "month": month, "used": 1500, "limit": 3_000_000}

    run(scenario())


def test_auto_default_model_and_precedence(store):
    async def scenario():
        app, backend = gpt_app(store)
        # Auto (ausdrücklich) und keine Angabe = das in der App eingestellte Modell, also gar keine Angabe ans Backend
        chat = await new_chat(app)
        await asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Hi", "model": "auto"})
        assert backend.calls[-1]["model"] is None
        assert next(c for c in jget(await asgi(app, "GET", "/api/chats")) if c["id"] == chat)["model"] == ""  # entspricht dem Standard: nichts gemerkt
        # Standardmodell der Person: gilt in jedem neuen Chat
        saved = await asgi(app, "PUT", "/api/me/model", {"model": "gpt-5.6-terra"})
        assert saved["status"] == 200 and jget(saved) == {"model": "gpt-5.6-terra"}
        assert jget(await asgi(app, "GET", "/api/me"))["user_model"] == "gpt-5.6-terra"
        fresh = await new_chat(app)
        await asgi(app, "POST", f"/api/chats/{fresh}/send", {"content": "Hi"})
        assert backend.calls[-1]["model"] == "gpt-5.6-terra"
        # Die Wahl im Chat schlägt das Standardmodell der Person …
        await asgi(app, "POST", f"/api/chats/{fresh}/send", {"content": "Nochmal", "model": "claude-opus-5-5"})
        assert backend.calls[-1]["model"] == "claude-opus-5-5"
        await asgi(app, "POST", f"/api/chats/{fresh}/send", {"content": "Und weiter"})
        assert backend.calls[-1]["model"] == "claude-opus-5-5"
        # … auch „Auto“ im Chat gilt, obwohl die Person ein anderes Standardmodell hat
        await asgi(app, "POST", f"/api/chats/{fresh}/send", {"content": "Auto", "model": "auto"})
        assert backend.calls[-1]["model"] is None
        await asgi(app, "POST", f"/api/chats/{fresh}/send", {"content": "Bleibt Auto"})
        assert backend.calls[-1]["model"] is None
        # Das Standardmodell einer anderen Person ist unberührt
        other = jget(await asgi(app, "POST", "/api/chats", {}, user=DORA))["id"]
        await asgi(app, "POST", f"/api/chats/{other}/send", {"content": "Hi"}, user=DORA)
        assert backend.calls[-1]["model"] is None
        # Zurück auf Auto
        assert jget(await asgi(app, "PUT", "/api/me/model", {"model": "auto"})) == {"model": ""}
        assert jget(await asgi(app, "GET", "/api/me"))["user_model"] == ""
        assert (await asgi(app, "PUT", "/api/me/model", {"model": "gpt-gibt-es-nicht"}))["status"] == 422

    run(scenario())


def test_default_model_that_is_no_longer_offered_counts_as_auto(store):
    async def scenario():
        app, backend = gpt_app(store)
        store.set_profile_default_model("adm01", "gpt-5.6-terra")
        app, backend = gpt_app(store, openai_enabled=False)  # ChatGPT wird ausgeschaltet
        assert jget(await asgi(app, "GET", "/api/me"))["user_model"] == ""
        chat = await new_chat(app)
        await asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Hi"})
        assert backend.calls[-1]["model"] is None

    run(scenario())


def test_title_and_summary_follow_the_provider_of_the_chat(store):
    async def scenario():
        app, backend = gpt_app(store)
        chat = await new_chat(app)
        await asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Hi", "model": "gpt-5.6-sol"})
        await asgi(app, "POST", f"/api/chats/{chat}/title", {})
        assert backend.titles == ["gpt-5.6-sol"]
        claude_chat = await new_chat(app)
        await asgi(app, "POST", f"/api/chats/{claude_chat}/send", {"content": "Hi"})
        await asgi(app, "POST", f"/api/chats/{claude_chat}/title", {})
        assert backend.titles == ["gpt-5.6-sol", None]  # der Claude-Chat ruft ohne Modellangabe auf: Claude bleibt unberührt

    run(scenario())


def test_spoken_messages_stay_on_claude_even_if_the_default_is_gpt(store):
    async def scenario():
        settings = parse_with_fixed({**RAW, "openai_enabled": True, "openai_chat_api_key": "sk-test", "voice": {"access_default": "on"}}, frozenset({"testclient"}))
        backend = Recorder()
        app = build_ingress_app(settings, store, backend)
        store.set_profile_default_model("adm01", "gpt-5.6-sol")
        chat = await new_chat(app)
        await asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Licht an", "voice": True})
        assert backend.calls[-1]["model"] == "claude-haiku-5-5" and "on_usage" not in backend.calls[-1]["kw"]

    run(scenario())


def test_monthly_token_limit_asks_before_the_next_answer(store):
    async def scenario():
        app, backend = gpt_app(store, openai_limit_month=1)  # 1 Tausend Token
        month = __import__("datetime").datetime.now().strftime("%Y-%m")
        store.token_usage_add("adm01", month, 1000, "openai")
        chat = await new_chat(app)

        async def waiting():
            return next(c for c in jget(await asgi(app, "GET", "/api/chats")) if c["id"] == chat)["needs_approval"]

        # abgelehnt: keine Antwort, Frage zurückgenommen
        post = asyncio.create_task(asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Teuer", "model": "gpt-5.6-terra"}))
        await until(waiting)
        assert (await asgi(app, "POST", f"/api/chats/{chat}/approve", {"id": 1, "decision": "deny"}))["status"] == 204
        events = sse(await post)
        approval = next(e for e in events if e["type"] == "approval")
        assert approval["topic"] == "tokens" and "1.000" in approval["details"] and approval["chat_ok"] is False
        assert events[-1]["type"] == "error" and "Monatslimit" in events[-1]["message"]
        assert backend.calls == [] and jget(await asgi(app, "GET", f"/api/chats/{chat}/messages")) == []
        # zugelassen: die Antwort kommt
        post = asyncio.create_task(asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Teuer", "model": "gpt-5.6-terra"}))
        await until(waiting)
        await asgi(app, "POST", f"/api/chats/{chat}/approve", {"id": 1, "decision": "allow"})
        events = sse(await post)
        assert "".join(e.get("text", "") for e in events if e["type"] == "delta") == "Antwort" and len(backend.calls) == 1
        # Claude-Chats fragen nie
        other = await new_chat(app)
        events = sse(await asgi(app, "POST", f"/api/chats/{other}/send", {"content": "Billig"}))
        assert not any(e["type"] == "approval" for e in events)

    run(scenario())


def test_limit_zero_means_unlimited(store):
    async def scenario():
        app, backend = gpt_app(store, openai_limit_month=0)
        month = __import__("datetime").datetime.now().strftime("%Y-%m")
        store.token_usage_add("adm01", month, 50_000_000, "openai")
        chat = await new_chat(app)
        events = sse(await asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Hi", "model": "gpt-5.6-terra"}))
        assert not any(e["type"] == "approval" for e in events) and len(backend.calls) == 1

    run(scenario())


def test_token_counter_is_per_person_month_and_provider(store):
    assert store.token_usage("adm01", "2026-11") == 0
    assert store.token_usage_add("adm01", "2026-11", 100) == 100
    assert store.token_usage_add("adm01", "2026-11", 50) == 150
    assert store.token_usage_add("adm01", "2026-12", 7) == 7
    assert store.token_usage("dora", "2026-11") == 0 and store.token_usage("adm01", "2026-11", "claude") == 0
    assert store.token_usage_add("adm01", "2026-11", -5) == 150  # nie rückwärts
    assert store.profile_default_model("adm01") == "" and store.set_profile_default_model("adm01", "gpt-5.6-sol") == "gpt-5.6-sol"
    assert store.profile_default_model("adm01") == "gpt-5.6-sol" and store.profile_default_model("dora") == ""


# ---------------------------------------------------------------- Einrichtungsprüfung und Hinweise

def test_setup_check_row_for_chatgpt():
    import copy
    from datetime import date

    from app import setup_check as sc
    from app.ops import Health

    def rows(**extra):
        settings = parse_with_fixed({**copy.deepcopy(RAW), **extra}, frozenset({"testclient"}))
        items = sc.static_items(settings, settings.profiles[0], ha_enabled=True, github_enabled=False, ha_level="read", github_level="none")
        return {i["id"]: i for i in items}

    off = rows()["chatgpt"]
    assert off["status"] == "off" and off["level"] == "optional"
    steps = " ".join(off["steps"])
    for needed in ("platform.openai.com", "openai_enabled", "openai_api_key", "openai_limit_month", "Standardmodell"):
        assert needed in steps
    missing = rows(openai_enabled=True)["chatgpt"]
    assert missing["status"] == "todo" and "Schlüssel" in missing["detail"]
    ready = rows(openai_enabled=True, openai_chat_api_key="sk-geheim")["chatgpt"]
    assert ready["status"] == "ok" and "GPT-5.6 Terra" not in ready["detail"] and "gpt-5.6-terra" in ready["detail"]
    assert "sk-geheim" not in json.dumps(ready) and "nie an Claude" in ready["detail"]
    # Ablaufdatum des eigenen Schlüssels wird angemahnt, bis es eingetragen ist
    assert "chat.openai_key_expires" in " ".join(rows(openai_enabled=True, openai_chat_api_key="sk-x")["expiry"]["steps"])
    done = rows(openai_enabled=True, openai_chat_api_key="sk-x", openai_chat_key_expires="2027-01-01")
    assert done["expiry"]["status"] == "ok"
    settings = parse_with_fixed({**RAW, "openai_enabled": True, "openai_chat_api_key": "sk-x", "openai_chat_key_expires": "2026-11-10"}, frozenset())
    warn = Health(settings).notices(date(2026, 10, 27))[0]
    assert warn["level"] == "warn" and "ChatGPT" in warn["text"] and "14 Tagen" in warn["text"]
    # ausgeschaltet: keine Erinnerung für einen Schlüssel, den niemand benutzt
    off_settings = parse_with_fixed({**RAW, "openai_chat_api_key": "sk-x", "openai_chat_key_expires": "2026-11-10"}, frozenset())
    assert Health(off_settings).notices(date(2026, 10, 27)) == []


def test_keys_in_openai_error_texts_are_masked():
    fake = FakeOpenAI(error_response(400, "invalid_prompt", "Incorrect API key provided: sk-svcacct-abcdef123456. Bitte prüfen."))
    with pytest.raises(BackendError) as info:
        run(collect(fake.backend(), [], "x", "low"))
    assert "sk-svcacct" not in info.value.user_message and "sk-…" in info.value.user_message
