"""Sprechen mit der KI (Etappe 1): WAV-Prüfung, Weckwort, Spracherkennung und -ausgabe (simuliert), schneller Pfad
über Home Assistant mit Sperre für Türen und Schlösser, Rechte (Standard aus), Sprachgespräche ohne Eintrag in der
Chatliste und ihr automatisches Löschen."""
import io
import json
import struct
import wave

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import ConfigError, parse_settings
from app.ha_client import HaApiError
from app import voice as voicelib
from app.main import build_ingress_app
from app.voice import MAX_AUDIO_BYTES, QuickResult, VoiceError, VoiceService, read_wav, strip_wake
from conftest import ADM01, RAW, as_user, parse_with_fixed

OPENAI = {"openai_api_key": "sk-test", "voice_access_default": "on"}


def nest(options: dict) -> dict:
    """Kurzschreibweise voice_<feld> aus den Tests in die Gruppe `voice:` der Konfiguration übersetzen."""
    out, voice = {}, {}
    for key, value in options.items():
        if key.startswith("voice_") and key != "voice_access":
            voice[key[len("voice_"):]] = value
        else:
            out[key] = value
    return {**out, "voice": voice} if voice else out


def wav(seconds=1.0, rate=16000, channels=1, width=2) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(struct.pack("<h", 500) * int(rate * seconds) * channels if width == 2 else b"\x80" * int(rate * seconds))
    return out.getvalue()


class FakeHa:
    """Simuliertes Home Assistant: Satzerkennung (Probelauf und Ausführung) und Zustände."""

    enabled = True

    def __init__(self, targets=None, match=True, process_type="action_done", states=None, debug_error=False):
        self.targets = targets if targets is not None else {"light.wohnzimmer": {"matched": True}}
        self.match = match
        self.process_type = process_type
        self.states = states or []
        self.debug_error = debug_error
        self.calls = []

    async def call(self, command, timeout=None):
        self.calls.append(command["type"])
        kind = command["type"]
        if kind == "conversation/agent/homeassistant/debug":
            if self.debug_error:
                raise HaApiError("kaputt")
            return {"results": [{"match": self.match, "targets": self.targets}] if self.match else [{"match": False}]}
        if kind == "conversation/process":
            return {"response": {"response_type": self.process_type, "speech": {"plain": {"speech": "Licht ist aus."}}}}
        if kind == "get_states":
            return self.states
        raise AssertionError(kind)

    async def pipeline_engines(self):
        return {"stt": False, "tts": False}


def service(ha=None, transport=None, **options):
    settings = parse_with_fixed({**RAW, **nest(options)}, frozenset({"testclient"}))
    return VoiceService(settings, ha, transport)


# ------------------------------------------------------------------ Aufnahme und Weckwort

def test_read_wav_accepts_mono_16bit_and_rejects_the_rest():
    pcm, rate = read_wav(wav(1.0))
    assert rate == 16000 and len(pcm) == 32000
    with pytest.raises(VoiceError):
        read_wav(b"keine Aufnahme")
    with pytest.raises(VoiceError):
        read_wav(wav(1.0, channels=2))
    with pytest.raises(VoiceError):
        read_wav(wav(0.05))  # zu kurz
    with pytest.raises(VoiceError):
        read_wav(wav(60.0))  # zu lang


@pytest.mark.parametrize("text,expected", [
    ("Aria mach das Licht aus", "mach das Licht aus"),
    ("Hey Aria, mach das Licht aus", "mach das Licht aus"),
    ("ok aria: Wie warm ist es?", "Wie warm ist es?"),
    ("mach das Licht aus", "mach das Licht aus"),
    ("Aria", ""),
    ("Ariane kommt heute", "Ariane kommt heute"),
])
def test_strip_wake_removes_the_name_only_at_the_start(text, expected):
    assert strip_wake(text, "Aria") == expected


def test_strip_wake_without_a_name_keeps_the_sentence():
    assert strip_wake("Mach das Licht aus", "") == "Mach das Licht aus"


# ------------------------------------------------------------------ Spracherkennung und -ausgabe

def test_transcribe_with_openai_sends_the_wav_and_returns_text():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = request.content
        return httpx.Response(200, json={"text": " Aria mach das Licht aus "})

    import asyncio
    voice = service(transport=httpx.MockTransport(handler), **OPENAI)
    assert asyncio.run(voice.transcribe(wav())) == "Aria mach das Licht aus"
    assert seen["url"].endswith("/audio/transcriptions") and seen["auth"] == "Bearer sk-test" and b"RIFF" in seen["body"]


def test_transcribe_errors_are_readable_and_never_leak_the_key():
    import asyncio
    for status, expected in ((401, "abgelehnt"), (429, "bremst"), (500, "HTTP 500")):
        voice = service(transport=httpx.MockTransport(lambda r, s=status: httpx.Response(s, json={"error": {"message": "x"}})), **OPENAI)
        with pytest.raises(VoiceError) as err:
            asyncio.run(voice.transcribe(wav()))
        assert expected in str(err.value) and "sk-test" not in str(err.value)


def test_transcribe_without_any_engine_says_so():
    import asyncio
    voice = service(voice_access_default="on")
    with pytest.raises(VoiceError, match="keine Spracherkennung"):
        asyncio.run(voice.transcribe(wav()))


def test_speech_comes_from_the_device_unless_the_service_voice_is_chosen():
    import asyncio
    assert asyncio.run(service(**OPENAI).speech()) == "device"
    assert asyncio.run(service(voice_output="service", **OPENAI).speech()) == "openai"
    with pytest.raises(VoiceError):
        asyncio.run(service(**OPENAI).speak("Hallo"))


def test_speak_with_openai_returns_mp3():
    import asyncio
    voice = service(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"ID3audio")), voice_output="service", **OPENAI)
    audio, mime = asyncio.run(voice.speak("Hallo   Welt"))
    assert audio == b"ID3audio" and mime == "audio/mpeg"


# ------------------------------------------------------------------ Schneller Pfad

def quick(ha, text="Mach das Licht aus", level="execute"):
    import asyncio
    return asyncio.run(service(ha, **OPENAI).quick_command(text, level))


def test_quick_command_runs_what_home_assistant_understands():
    ha = FakeHa()
    result = quick(ha)
    assert isinstance(result, QuickResult) and result.speech == "Licht ist aus." and not result.blocked
    assert ha.calls == ["conversation/agent/homeassistant/debug", "conversation/process"]  # erst Probelauf, dann Ausführen


def test_quick_command_needs_execute_rights_and_a_match():
    ha = FakeHa()
    assert quick(ha, level="read") is None and ha.calls == []
    assert quick(FakeHa(match=False)) is None
    assert quick(FakeHa(process_type="error")) is None
    assert quick(None) is None


def test_quick_command_without_a_dry_run_falls_back_to_the_ai():
    ha = FakeHa(debug_error=True)
    assert quick(ha) is None and "conversation/process" not in ha.calls


@pytest.mark.parametrize("entity", ["lock.haustuer", "alarm_control_panel.alarm", "siren.sirene"])
def test_quick_command_never_runs_locks_alarms_or_sirens(entity):
    ha = FakeHa(targets={entity: {"matched": True}})
    result = quick(ha, "Schließe auf")
    assert result.blocked and "getippt" in result.speech
    assert "conversation/process" not in ha.calls  # nichts wurde ausgeführt


def test_quick_command_blocks_door_and_garage_covers_but_not_blinds():
    states = [
        {"entity_id": "cover.garage", "attributes": {"device_class": "garage"}},
        {"entity_id": "cover.rollo", "attributes": {"device_class": "blind"}},
    ]
    garage = FakeHa(targets={"cover.garage": {"matched": True}}, states=states)
    assert quick(garage, "Garage auf").blocked
    blind = FakeHa(targets={"cover.rollo": {"matched": True}}, states=states)
    result = quick(blind, "Rollo hoch")
    assert not result.blocked and "conversation/process" in blind.calls


# ------------------------------------------------------------------ Einstellungen

def test_voice_is_off_by_default_and_per_user_overridable():
    off = parse_settings(RAW, frozenset())
    assert off.voice_access_default == "off" and off.voice_chat_days == 30 and off.voice_output == "device"
    assert all(off.voice_level(p) == "off" for p in off.profiles)
    raw = {**RAW, "voice": {"access_default": "on"}, "profiles": [{**RAW["profiles"][0], "voice_access": "off"}, RAW["profiles"][1]]}
    on = parse_settings(raw, frozenset())
    assert [on.voice_level(p) for p in on.profiles] == ["off", "on"]
    raw = {**RAW, "profiles": [{**RAW["profiles"][0], "voice_access": "on"}, RAW["profiles"][1]]}
    one = parse_settings(raw, frozenset())
    assert [one.voice_level(p) for p in one.profiles] == ["on", "off"]


@pytest.mark.parametrize("option,value", [("access_default", "maybe"), ("output", "radio"), ("chat_days", 400), ("chat_days", "x")])
def test_invalid_voice_options_are_rejected(option, value):
    with pytest.raises(ConfigError):
        parse_settings({**RAW, "voice": {option: value}}, frozenset())


# ------------------------------------------------------------------ Web-Schnittstelle

class RecordingBackend:
    def __init__(self):
        self.seen = {}

    async def stream(self, history, message, effort, attachments=None, instructions=None, tools=None, note="", model=None, **_):
        self.seen = {"effort": effort, "tools": sorted(t.name for t in tools or []), "note": note, "model": model}
        yield "Das Licht im Flur ist an."


def app_client(store, ha=None, backend=None, transport=None, **options):
    settings = parse_with_fixed({**RAW, **nest(options)}, frozenset({"testclient"}))
    app = build_ingress_app(settings, store, backend or RecordingBackend(), ha=ha, voice=VoiceService(settings, ha, transport))
    return TestClient(app)


HEAD = as_user(ADM01, True)


def post(client, path, **kwargs):
    headers = {**HEAD, **kwargs.pop("headers", {})}
    return client.post(path, headers=headers, **kwargs)


def test_voice_endpoints_are_closed_by_default(store):
    client = app_client(store)
    assert client.get("/api/me", headers=HEAD).json()["voice"] is False
    assert post(client, "/api/voice/transcribe", content=wav(), headers={"Content-Type": "audio/wav"}).status_code == 403
    assert post(client, "/api/voice/speak", json={"text": "Hallo"}).status_code == 403
    assert post(client, "/api/chats", json={"voice": True}).status_code == 403
    chat = post(client, "/api/chats", json={}).json()["id"]
    assert post(client, f"/api/chats/{chat}/send", json={"content": "Hallo", "voice": True}).status_code == 403


def test_transcribe_returns_the_text_and_the_sentence_without_the_name(store):
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"text": "Aria, mach das Licht aus."}))
    client = app_client(store, transport=transport, app_name="Aria", **OPENAI)
    me = client.get("/api/me", headers=HEAD).json()
    assert me["voice"] is True and me["voice_wake"] == "Aria"
    out = post(client, "/api/voice/transcribe", content=wav(), headers={"Content-Type": "audio/wav"})
    assert out.status_code == 200 and out.json() == {"text": "Aria, mach das Licht aus.", "command": "mach das Licht aus."}
    assert post(client, "/api/voice/transcribe", content=b"nix", headers={"Content-Type": "audio/wav"}).status_code == 422


def test_wake_name_follows_app_name(store):
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"text": "Aria, wie spät ist es"}))
    client = app_client(store, transport=transport, app_name="Aria", **OPENAI)
    out = post(client, "/api/voice/transcribe", content=wav(), headers={"Content-Type": "audio/wav"})
    assert out.json()["command"] == "wie spät ist es"


def test_big_recordings_are_refused_before_they_are_read(store):
    client = app_client(store, **OPENAI)
    out = post(client, "/api/voice/transcribe", content=b"0" * (MAX_AUDIO_BYTES + 10), headers={"Content-Type": "audio/wav"})
    assert out.status_code == 413


def test_spoken_message_uses_the_fast_model_few_tools_and_the_voice_note(store):
    backend = RecordingBackend()
    client = app_client(store, backend=backend, **OPENAI)
    chat = post(client, "/api/chats", json={}).json()["id"]
    out = post(client, f"/api/chats/{chat}/send", json={"content": "Ist das Licht im Flur an?", "voice": True, "effort": "high"})
    assert out.status_code == 200 and "Das Licht im Flur ist an." in out.text
    assert backend.seen["effort"] == "low" and backend.seen["model"] == "claude-haiku-5-5"
    assert "kurz" in backend.seen["note"].lower() and not any(t.startswith(("image_", "github_", "file_")) for t in backend.seen["tools"])


def test_spoken_message_rejects_attachments_and_quotes(store):
    client = app_client(store, **OPENAI)
    chat = post(client, "/api/chats", json={}).json()["id"]
    out = post(client, f"/api/chats/{chat}/send", json={"content": "Hi", "voice": True, "files": [{"name": "a.txt", "data": "aGk="}]})
    assert out.status_code == 422


def test_quick_endpoint_writes_question_and_answer_into_the_chat(store):
    ha = FakeHa()
    client = app_client(store, ha=ha, **OPENAI)
    chat = post(client, "/api/chats", json={}).json()["id"]
    out = post(client, f"/api/chats/{chat}/voice", json={"text": "Mach das Licht aus"})
    assert out.json() == {"handled": True, "speech": "Licht ist aus.", "blocked": False}
    messages = client.get(f"/api/chats/{chat}/messages", headers=HEAD).json()
    assert [m["role"] for m in messages] == ["user", "assistant"] and messages[1]["content"] == "Licht ist aus."
    assert client.get("/api/chats", headers=HEAD).json()[0]["title"] == "Mach das Licht aus"


def test_quick_endpoint_hands_over_to_the_ai_when_unknown_or_blocked(store):
    client = app_client(store, ha=FakeHa(match=False), **OPENAI)
    chat = post(client, "/api/chats", json={}).json()["id"]
    assert post(client, f"/api/chats/{chat}/voice", json={"text": "Erzähl einen Witz"}).json() == {"handled": False}
    assert client.get(f"/api/chats/{chat}/messages", headers=HEAD).json() == []
    blocked = app_client(store, ha=FakeHa(targets={"lock.haustuer": {"matched": True}}), **OPENAI)
    out = post(blocked, f"/api/chats/{chat}/voice", json={"text": "Haustür auf"}).json()
    assert out["handled"] and out["blocked"]


def test_quick_endpoint_needs_a_known_chat(store):
    client = app_client(store, ha=FakeHa(), **OPENAI)
    assert post(client, "/api/chats/gibtsnicht/voice", json={"text": "Licht aus"}).status_code == 404


# ------------------------------------------------------------------ Sprachgespräche in der Chatliste

def test_voice_chats_stay_out_of_the_list_and_search_until_kept(store):
    client = app_client(store, ha=FakeHa(), **OPENAI)
    normal = post(client, "/api/chats", json={}).json()["id"]
    voice = post(client, "/api/chats", json={"voice": True, "project_id": "egal"}).json()
    assert voice["title"] == "Sprachgespräch"
    post(client, f"/api/chats/{voice['id']}/voice", json={"text": "Mach das Licht aus"})
    listed = [c["id"] for c in client.get("/api/chats", headers=HEAD).json()]
    assert listed == [normal]
    assert [c["id"] for c in client.get("/api/voice/chats", headers=HEAD).json()] == [voice["id"]]
    assert store.search_chats("adm01", "Licht") == []  # auch die Suche überspringt Sprachgespräche
    # Das Gespräch lässt sich weiter öffnen und als normaler Chat behalten
    assert client.get(f"/api/chats/{voice['id']}/messages", headers=HEAD).status_code == 200
    kept = client.patch(f"/api/chats/{voice['id']}", headers=HEAD, json={"keep": True})
    assert kept.status_code == 200
    assert {c["id"] for c in client.get("/api/chats", headers=HEAD).json()} == {normal, voice["id"]}
    assert client.get("/api/voice/chats", headers=HEAD).json() == []


def test_voice_sweep_deletes_old_unpinned_voice_chats_only(store):
    profile = "adm01"
    old = store.create_chat(profile, "alt", None, kind="voice")
    pinned = store.create_chat(profile, "angeheftet", None, kind="voice")
    store.set_chat_pinned(profile, pinned["id"], True)
    normal = store.create_chat(profile, "normal", None)
    young = store.create_chat(profile, "jung", None, kind="voice")
    with store._lock:  # noqa: SLF001 – Alter künstlich setzen
        store._conn.execute("UPDATE chats SET updated_at = '2020-01-01T00:00:00+00:00' WHERE id IN (?, ?, ?)", (old["id"], pinned["id"], normal["id"]))
        store._conn.commit()
    assert store.voice_sweep(0) == 0  # 0 = behalten
    assert store.voice_sweep(30) == 1
    assert store.get_chat(profile, old["id"]) is None
    assert store.get_chat(profile, pinned["id"]) and store.get_chat(profile, normal["id"]) and store.get_chat(profile, young["id"])


def test_security_headers_allow_the_microphone_and_blob_audio(store):
    client = app_client(store)
    headers = client.get("/api/me", headers=HEAD).headers
    assert "microphone=(self)" in headers["permissions-policy"] and "media-src 'self' blob:" in headers["content-security-policy"]


# ------------------------------------------------------------------ Spracherkennung des Browsers (Rückfall)

def test_browser_recognition_is_the_default_when_no_service_is_set(store):
    client = app_client(store, voice_access_default="on")
    info = client.get("/api/voice", headers=HEAD).json()
    assert info["stt"] == "" and info["browser"] is True  # der Browser springt ein


def test_browser_recognition_can_be_switched_off_and_yields_to_a_key(store):
    off = app_client(store, voice_access_default="on", voice_browser_stt=False).get("/api/voice", headers=HEAD).json()
    assert off["stt"] == "" and off["browser"] is False
    keyed = app_client(store, **OPENAI).get("/api/voice", headers=HEAD).json()
    assert keyed["stt"] == "openai"  # mit Schlüssel läuft die Erkennung über das Add-on


def test_voice_browser_stt_option_defaults_to_on():
    assert parse_settings(RAW, frozenset()).voice_browser_stt is True
    assert parse_settings({**RAW, "voice": {"browser_stt": False}}, frozenset()).voice_browser_stt is False


def test_voice_group_must_be_a_group_and_has_its_own_openai_key():
    with pytest.raises(ConfigError):
        parse_settings({**RAW, "voice": "on"}, frozenset())
    shared = parse_settings({**RAW, "openai_api_key": "sk-bilder"}, frozenset())
    assert shared.voice_openai_key == "sk-bilder"  # ohne eigenen Schlüssel gilt der gemeinsame
    own = parse_settings({**RAW, "openai_api_key": "sk-bilder", "voice": {"openai_api_key": "sk-sprache"}}, frozenset())
    assert own.voice_openai_key == "sk-sprache" and own.openai_api_key == "sk-bilder"
    assert "sk-sprache" not in repr(own)  # Schlüssel stehen nie im Protokoll
    assert parse_settings(RAW, frozenset()).voice_openai_key == ""


def test_voice_uses_its_own_key_for_recognition():
    import asyncio
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json={"text": "Hallo"})

    voice = service(transport=httpx.MockTransport(handler), openai_api_key="sk-bilder", voice_openai_api_key="sk-sprache", voice_access_default="on")
    asyncio.run(voice.transcribe(wav()))
    assert seen["auth"] == "Bearer sk-sprache"


# ------------------------------------------------------------------ Vorlesen auf dem Handy (0.53.1)

def _voice_js():
    from pathlib import Path
    return (Path(__file__).resolve().parents[1] / "app" / "static" / "voice.js").read_text(encoding="utf-8")


def test_audio_is_unlocked_in_the_click_that_opens_or_restarts_the_conversation():
    js = _voice_js()
    open_voice = js[js.index("async function openVoice()"):js.index("// Welche Spracherkennung gilt")]
    talk_now = js[js.index("function talkNow()"):js.index("// ---", js.index("function talkNow()"))]
    assert "unlockAudio()" in open_voice and "unlockAudio()" in talk_now


def test_the_silent_unlock_sound_is_a_blob_because_the_csp_forbids_data_audio():
    js = _voice_js()
    assert "data:audio" not in js and "createObjectURL(new Blob" in js and "media-src 'self' blob:" in open(
        __import__("pathlib").Path(__file__).resolve().parents[1] / "app" / "main.py", encoding="utf-8").read()


def test_speaking_never_hangs_without_a_start_and_tells_when_nothing_was_heard():
    js = _voice_js()
    assert "PLAY_START_WAIT" in js and "DEVICE_START_WAIT" in js and "utterance.onstart" in js
    assert "Ich konnte die Antwort nicht vorlesen. Den Text siehst du oben." in js


# ------------------------------------------------------------------ Tempo: Zeitmessung und satzweises Sprechen (0.53.3)

def test_timing_endpoint_is_closed_by_default_and_checks_its_numbers(store):
    client = app_client(store)
    assert post(client, "/api/voice/timing", json={"path": "ai"}).status_code == 403
    client = app_client(store, **OPENAI)
    assert post(client, "/api/voice/timing", json={"path": "kaputt"}).status_code == 422
    assert post(client, "/api/voice/timing", json={"path": "ai", "stt_ms": -5}).status_code == 422
    assert post(client, "/api/voice/timing", json={"path": "ai", "total_ms": 10**9}).status_code == 422


def test_timing_endpoint_writes_one_log_line_with_numbers_only(store, caplog):
    client = app_client(store, **OPENAI)
    with caplog.at_level("INFO", logger="copilot"):
        out = post(client, "/api/voice/timing", json={"path": "ai", "stt_ms": 900, "answer_ms": 2400, "first_sound_ms": 700, "total_ms": 5100, "sentences": 3})
    assert out.status_code == 200 and out.json() == {"ok": True}
    line = next(r.getMessage() for r in caplog.records if "Sprache: Runde" in r.getMessage())
    assert line == "Sprache: Runde über KI: Erkennung 0.9 s, KI bis erster Text 2.4 s, bis erster Ton 0.7 s, Antwort gesamt 5.1 s, 3 Sätze"


def test_quick_round_is_labelled_as_quick_path(store, caplog):
    client = app_client(store, **OPENAI)
    with caplog.at_level("INFO", logger="copilot"):
        post(client, "/api/voice/timing", json={"path": "quick", "answer_ms": 300})
    assert any("Schnellpfad: Antwort 0.3 s" in r.getMessage() for r in caplog.records)


def test_transcribe_logs_how_long_the_recognition_took(store, caplog):
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"text": "Aria, mach das Licht aus."}))
    client = app_client(store, transport=transport, **OPENAI)
    with caplog.at_level("INFO", logger="copilot"):
        post(client, "/api/voice/transcribe", content=wav(), headers={"Content-Type": "audio/wav"})
    assert any("Sprache: Erkennung über openai dauerte" in r.getMessage() for r in caplog.records)


def test_the_answer_text_reaches_the_speaker_while_it_streams():
    from pathlib import Path
    static = Path(__file__).resolve().parents[1] / "app" / "static"
    app_js, voice_js = (static / "app.js").read_text(encoding="utf-8"), (static / "voice.js").read_text(encoding="utf-8")
    assert "run.onText = spoken.onText" in app_js and "run.onText?.(out.answer)" in app_js
    assert "createSpeaker(alive, turn)" in voice_js and "speaker.feed(text)" in voice_js and "speaker.finish(answer)" in voice_js
    assert "api/voice/timing" in voice_js


# ------------------------------------------------------------------ Kürzere Antworten, eigene Wünsche, Einheiten (0.53.4)

def test_voice_note_forbids_device_names_and_asks_for_short_confirmations():
    note = voicelib.VOICE_NOTE
    assert "Lichtschalter" in note and "nie Namen oder Kennungen" in note and "Ich habe" in note
    assert "Das Licht im Bad ist an." in note and "21 Grad" in note and "40 Prozent" in note


def test_own_instructions_are_appended_to_the_voice_note_only_when_set():
    assert voicelib.voice_note("") == voicelib.VOICE_NOTE and voicelib.voice_note("   ") == voicelib.VOICE_NOTE
    note = voicelib.voice_note("Nenne Räume immer beim Namen.")
    assert note.startswith(voicelib.VOICE_NOTE) and note.endswith("Nenne Räume immer beim Namen.")


def test_voice_instructions_option_is_trimmed_limited_and_empty_by_default():
    from app.config import VOICE_INSTRUCTIONS_MAX

    assert parse_with_fixed(RAW, frozenset()).voice_instructions == ""
    s = parse_settings({**RAW, "voice": {"instructions": "  Antworte   in einem Satz.\n"}}, frozenset())
    assert s.voice_instructions == "Antworte in einem Satz."
    with pytest.raises(ConfigError, match="voice.instructions"):
        parse_settings({**RAW, "voice": {"instructions": "x" * (VOICE_INSTRUCTIONS_MAX + 1)}}, frozenset())


def test_spoken_message_carries_the_own_instructions(store):
    backend = RecordingBackend()
    client = app_client(store, backend=backend, voice_instructions="Antworte immer mit dem Raumnamen.", **OPENAI)
    chat = post(client, "/api/chats", json={}).json()["id"]
    out = post(client, f"/api/chats/{chat}/send", json={"content": "Licht im Bad an", "voice": True})
    assert out.status_code == 200 and "Antworte immer mit dem Raumnamen." in backend.seen["note"]


def test_units_are_spoken_out_for_the_voice():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "app" / "static" / "voice.js").read_text(encoding="utf-8")
    assert "function spokenUnits" in js and "Grad Celsius" in js and "Prozent" in js and "Kilowattstunden" in js
    assert "speechIsEnglish()" in js


# ------------------------------------------------------------------ Whisper oder Piper fehlen oder laufen nicht (0.53.6)

from app.ha_client import HaApi  # noqa: E402


class PipelineHa(HaApi):
    """Home Assistant mit einer bevorzugten Pipeline und frei wählbaren Zuständen der Engine-Entitäten."""

    def __init__(self, stt="stt.faster_whisper", tts="tts.piper", states=None, states_fail=False):
        super().__init__("t", "ws://x")
        self.pipeline = {"id": "p1", "stt_engine": stt, "tts_engine": tts}
        self.entity_states = states if states is not None else {}
        self.states_fail = states_fail

    async def call(self, command, timeout=None):
        if command["type"] == "assist_pipeline/pipeline/list":
            return {"preferred_pipeline": "p1", "pipelines": [self.pipeline]}
        if command["type"] == "get_states":
            if self.states_fail:
                raise HaApiError("get_states: Zeitüberschreitung")
            return [{"entity_id": k, "state": v} for k, v in self.entity_states.items()]
        raise AssertionError(command)


def run(coro):
    import asyncio
    return asyncio.run(coro)


def test_engines_are_usable_only_when_the_service_really_runs():
    ok = run(PipelineHa(states={"stt.faster_whisper": "unknown", "tts.piper": "unknown"}).pipeline_engines())
    assert ok == {"stt": True, "tts": True, "stt_down": False, "tts_down": False}
    down = run(PipelineHa(states={"stt.faster_whisper": "unavailable", "tts.piper": "unknown"}).pipeline_engines())
    assert down["stt"] is False and down["stt_down"] is True and down["tts"] is True
    removed = run(PipelineHa(states={}).pipeline_engines())  # Add-on und Integration entfernt: die Entitäten gibt es nicht mehr
    assert removed == {"stt": False, "tts": False, "stt_down": True, "tts_down": True}


def test_engines_without_an_entry_are_not_reported_as_down_and_unknown_state_counts_as_present():
    empty = run(PipelineHa(stt=None, tts=None).pipeline_engines())
    assert empty == {"stt": False, "tts": False, "stt_down": False, "tts_down": False}
    legacy = run(PipelineHa(stt="cloud", tts="cloud").pipeline_engines())  # Engine ohne Entität: kein Grund zur Annahme, sie fehle
    assert legacy["stt"] and legacy["tts"] and not legacy["stt_down"]
    silent = run(PipelineHa(states_fail=True).pipeline_engines())  # Home Assistant gibt keine Zustände heraus: im Zweifel vorhanden
    assert silent["stt"] and silent["tts"] and not silent["stt_down"]


def test_a_stopped_whisper_makes_the_app_fall_back_instead_of_failing():
    ha = PipelineHa(states={"stt.faster_whisper": "unavailable", "tts.piper": "unknown"})
    service = VoiceService(parse_with_fixed({**RAW, **nest({"voice_access_default": "on"})}, frozenset()), ha)
    assert run(service.provider()) == ""  # kein Server-Dienst: die Oberfläche nimmt den Browser oder sagt, was fehlt
    with pytest.raises(VoiceError, match="keine Spracherkennung"):
        run(service.transcribe(wav()))


def test_a_failing_whisper_or_piper_names_the_add_on_in_the_error():
    class Broken(PipelineHa):
        async def pipeline_stt(self, *args, **kwargs):
            raise HaApiError("assist_pipeline: Zeitüberschreitung")

        async def pipeline_tts(self, *args, **kwargs):
            raise HaApiError("assist_pipeline: Zeitüberschreitung")

    ha = Broken(states={"stt.faster_whisper": "unknown", "tts.piper": "unknown"})
    service = VoiceService(parse_with_fixed({**RAW, **nest({"voice_access_default": "on", "voice_output": "service"})}, frozenset()), ha)
    with pytest.raises(VoiceError, match="Whisper"):
        run(service.transcribe(wav()))
    with pytest.raises(VoiceError, match="Piper"):
        run(service.speak("Hallo"))


def test_nothing_configured_is_caught_on_the_server_and_in_the_window(store):
    client = app_client(store, voice_access_default="on", voice_browser_stt=False)
    info = client.get("/api/voice", headers=HEAD).json()
    assert info["stt"] == "" and info["speech"] == "device" and info["browser"] is False
    out = post(client, "/api/voice/transcribe", content=wav(), headers={"Content-Type": "audio/wav"})
    assert out.status_code == 422 and "keine Spracherkennung" in out.json()["detail"]
    assert post(client, "/api/voice/speak", json={"text": "Hallo"}).status_code == 422  # ohne Stimme-Dienst: das Gerät spricht, nicht das Add-on


def test_the_window_falls_back_to_the_browser_when_the_recognition_fails():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "app" / "static" / "voice.js").read_text(encoding="utf-8")
    assert "failure.recognition = true" in js and "err?.recognition && !VOICE.browserOnly" in js
    assert "VOICE.browserOnly = false" in js and "Die Spracherkennung im Add-on antwortet nicht. Ich nutze jetzt die des Browsers." in js
