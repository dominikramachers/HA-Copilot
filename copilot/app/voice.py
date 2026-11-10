"""Sprache: Spracherkennung, Sprachausgabe und der schnelle Pfad für Gerätebefehle.

Die Oberfläche nimmt einen Satz auf und schickt ihn als WAV (16 Bit, mono). Daraus wird hier Text: über OpenAI, wenn ein
Schlüssel eingetragen ist, sonst über die Spracherkennung der bevorzugten Assist-Pipeline von Home Assistant. Ton wird nie
gespeichert und nicht protokolliert.

Der schnelle Pfad (``quick_command``) gibt einen Satz zuerst an die eingebaute Satzerkennung von Home Assistant. Versteht
sie ihn, wird sofort geschaltet, ohne KI. Ein Probelauf nennt vorher die Zielgeräte: heikle Geräte (Schlösser, Alarm,
Türen und Tore) werden per Sprache nie bedient.
"""
from __future__ import annotations

import io
import logging
import re
import wave
from dataclasses import dataclass, field
from typing import Any

import httpx

from .ha_client import HaApi, HaApiError
from .ha_tools import DOOR_CLASSES, RANK, SENSITIVE_DOMAINS_ALWAYS
from .i18n import tr

log = logging.getLogger("copilot.voice")

OPENAI_URL = "https://api.openai.com/v1/audio"
STT_MODEL = "gpt-4o-mini-transcribe"
TTS_MODEL = "gpt-4o-mini-tts"
TTS_VOICE = "alloy"
REQUEST_TIMEOUT = 40
MAX_SECONDS = 45  # längste Aufnahme je Satz
MIN_SECONDS = 0.25
MAX_AUDIO_BYTES = 48000 * 2 * MAX_SECONDS + 4096  # WAV, 16 Bit, mono, bis 48 kHz
MAX_SPEAK_CHARS = 700  # ein Stück Antwort je Aufruf der Sprachausgabe (die Oberfläche schickt Satz für Satz)
MAX_TEXT_CHARS = 600  # ein gesprochener Satz für den schnellen Pfad
HA_AGENT = "conversation.home_assistant"

# Hinweis an die KI für gesprochene Antworten (wird an die Sitzungshinweise angehängt)
VOICE_NOTE = (
    "Diese Nachricht wurde gesprochen (Spracherkennung, Hörfehler sind möglich) und deine Antwort wird vorgelesen. "
    "Antworte deshalb kurz und so, wie man spricht: höchstens zwei bis drei Sätze, kein Markdown, keine Listen, keine "
    "Tabellen, keine Codeblöcke, keine Emojis, keine Entitäts-IDs. Zahlen und Einheiten so, dass sie sich gut vorlesen lassen. "
    "Ist etwas zu lang zum Vorlesen, nenne das Wichtigste und biete an, den Rest hier im Chat aufzuschreiben. "
    "Hast du etwas geschaltet, bestätige es in einem kurzen Satz. Ist der Satz unverständlich, frage kurz nach. "
    "Per Sprache sind Schlösser, Alarmanlagen, Türen und Tore gesperrt und Rückfragen werden automatisch abgelehnt: "
    "sag dann, dass das nur getippt im Chat geht."
)


class VoiceError(Exception):
    """Sprache nicht möglich; ``str()`` ist die Meldung für die Person."""


def read_wav(data: bytes) -> tuple[bytes, int]:
    """WAV prüfen und ``(PCM, Abtastrate)`` liefern: 16 Bit, mono, 8 bis 48 kHz, nicht zu kurz und nicht zu lang."""
    try:
        with wave.open(io.BytesIO(data), "rb") as source:
            channels, width, rate, frames = source.getnchannels(), source.getsampwidth(), source.getframerate(), source.getnframes()
            pcm = source.readframes(frames)
    except (wave.Error, EOFError, ValueError, OSError):
        raise VoiceError(tr("Die Aufnahme konnte nicht gelesen werden.")) from None
    if channels != 1 or width != 2 or not 8000 <= rate <= 48000:
        raise VoiceError(tr("Die Aufnahme hat ein unerwartetes Format."))
    seconds = len(pcm) / (2 * rate)
    if seconds < MIN_SECONDS:
        raise VoiceError(tr("Die Aufnahme war zu kurz."))
    if seconds > MAX_SECONDS + 1:
        raise VoiceError(tr("Die Aufnahme ist zu lang."))
    return pcm, rate


def strip_wake(text: str, name: str) -> str:
    """Den Namen der KI am Satzanfang entfernen: „Aria, mach das Licht aus“ → „mach das Licht aus“."""
    text = " ".join(text.split())
    name = name.strip()
    if not name:
        return text
    pattern = r"^(?:(?:hey|hallo|hi|ok|okay)[\s,]+)?" + re.escape(name) + r"(?![\w-])[\s,.:;!?-]*"
    rest = re.sub(pattern, "", text, count=1, flags=re.IGNORECASE)
    return rest.strip() if rest != text else text


def _api_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
        err = payload.get("error", payload) if isinstance(payload, dict) else {}
        text = err.get("message") if isinstance(err, dict) else str(err)
    except ValueError:
        text = response.text
    return re.sub(r"\s+", " ", str(text or "")).strip()[:200]


def _openai_failure(response: httpx.Response) -> VoiceError:
    status, message = response.status_code, _api_message(response)
    log.warning("OpenAI (Sprache) meldet HTTP %s: %s", status, message)
    if status in (401, 403):
        return VoiceError(tr("OpenAI hat den Schlüssel abgelehnt. Bitte den Eintrag `openai_api_key` in der Konfiguration prüfen."))
    if status == 402 or (status == 429 and re.search(r"quota|billing|credit|insufficient|exhaust", message, re.I)):
        return VoiceError(tr("Das Guthaben bei OpenAI ist aufgebraucht."))
    if status == 429:
        return VoiceError(tr("OpenAI bremst gerade. Bitte gleich noch einmal versuchen."))
    return VoiceError(tr("OpenAI meldet einen Fehler (HTTP {status}).", status=status))


@dataclass
class QuickResult:
    """Ergebnis des schnellen Pfads: ``speech`` ist der Satz von Home Assistant, ``blocked`` = heikles Gerät, nichts ausgeführt."""

    speech: str
    blocked: bool = False
    targets: list[str] = field(default_factory=list)


class VoiceService:
    """Spracherkennung und Sprachausgabe für alle Personen (Schlüssel und Verbindung aus der Konfiguration)."""

    def __init__(self, settings: Any, ha: HaApi | None = None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.openai_key = getattr(settings, "openai_api_key", "")
        self.output = getattr(settings, "voice_output", "device")
        self.language = getattr(settings, "language", "de")
        self.ha = ha if ha is not None and ha.enabled else None
        self.transport = transport

    # ------------------------------------------------------------------ Stand

    async def provider(self) -> str:
        """Dienst für die Spracherkennung: ``openai``, ``ha`` (Assist-Pipeline) oder leer (nichts eingerichtet)."""
        if self.openai_key:
            return "openai"
        if self.ha is not None and (await self.ha.pipeline_engines())["stt"]:
            return "ha"
        return ""

    async def speech(self) -> str:
        """Woher die Stimme kommt: ``device`` (Stimme des Geräts), ``openai`` oder ``ha``."""
        if self.output != "service":
            return "device"
        if self.openai_key:
            return "openai"
        if self.ha is not None and (await self.ha.pipeline_engines())["tts"]:
            return "ha"
        return "device"

    # ---------------------------------------------------------- Spracherkennung

    async def transcribe(self, wav: bytes) -> str:
        pcm, rate = read_wav(wav)
        provider = await self.provider()
        if provider == "openai":
            return await self._openai_stt(wav)
        if provider == "ha":
            try:
                return await self.ha.pipeline_stt(pcm, rate)  # type: ignore[union-attr]
            except HaApiError as exc:
                log.warning("Spracherkennung über Home Assistant fehlgeschlagen: %s", exc)
                raise VoiceError(tr("Die Spracherkennung von Home Assistant antwortet nicht.")) from None
        raise VoiceError(tr("Es ist keine Spracherkennung eingerichtet."))

    async def _openai_stt(self, wav: bytes) -> str:
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=10)) as client:
                response = await client.post(
                    f"{OPENAI_URL}/transcriptions",
                    headers={"Authorization": f"Bearer {self.openai_key}"},
                    data={"model": STT_MODEL, "language": self.language, "response_format": "json"},
                    files={"file": ("aufnahme.wav", wav, "audio/wav")},
                )
        except (httpx.HTTPError, TimeoutError) as exc:
            log.warning("OpenAI (Spracherkennung) nicht erreichbar: %s", type(exc).__name__)
            raise VoiceError(tr("Die Spracherkennung ist gerade nicht erreichbar.")) from None
        if response.status_code != 200:
            raise _openai_failure(response)
        try:
            return str(response.json().get("text") or "").strip()
        except (ValueError, AttributeError):
            raise VoiceError(tr("Die Spracherkennung hat eine unlesbare Antwort geliefert.")) from None

    # ------------------------------------------------------------ Sprachausgabe

    async def speak(self, text: str) -> tuple[bytes, str]:
        """Text sprechen lassen: ``(Ton, Medientyp)``. Nur wenn die Stimme nicht vom Gerät kommt."""
        text = " ".join(text.split())[:MAX_SPEAK_CHARS]
        if not text:
            raise VoiceError(tr("Kein Text zum Vorlesen."))
        provider = await self.speech()
        if provider == "openai":
            return await self._openai_tts(text)
        if provider == "ha":
            try:
                return await self.ha.pipeline_tts(text)  # type: ignore[union-attr]
            except HaApiError as exc:
                log.warning("Sprachausgabe über Home Assistant fehlgeschlagen: %s", exc)
                raise VoiceError(tr("Die Sprachausgabe von Home Assistant antwortet nicht.")) from None
        raise VoiceError(tr("Die Stimme kommt vom Gerät."))

    async def _openai_tts(self, text: str) -> tuple[bytes, str]:
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=10)) as client:
                response = await client.post(
                    f"{OPENAI_URL}/speech",
                    headers={"Authorization": f"Bearer {self.openai_key}"},
                    json={"model": TTS_MODEL, "voice": TTS_VOICE, "input": text, "response_format": "mp3"},
                )
        except (httpx.HTTPError, TimeoutError) as exc:
            log.warning("OpenAI (Sprachausgabe) nicht erreichbar: %s", type(exc).__name__)
            raise VoiceError(tr("Die Sprachausgabe ist gerade nicht erreichbar.")) from None
        if response.status_code != 200 or not response.content:
            raise _openai_failure(response)
        return response.content, "audio/mpeg"

    # ------------------------------------------------------------ Schneller Pfad

    async def quick_command(self, text: str, level: str) -> QuickResult | None:
        """Satz von Home Assistant selbst ausführen lassen. ``None`` = nicht verstanden oder nicht erlaubt: die KI übernimmt."""
        if self.ha is None or RANK.get(level, 0) < RANK["execute"]:
            return None
        text = " ".join(text.split())
        if not text or len(text) > MAX_TEXT_CHARS:
            return None
        try:
            debug = await self.ha.call({"type": "conversation/agent/homeassistant/debug", "sentences": [text], "language": self.language})
        except HaApiError as exc:
            log.info("Probelauf der Satzerkennung nicht möglich: %s", exc)
            return None  # ohne Probelauf keine Prüfung der Zielgeräte: lieber die KI mit ihren Regeln
        results = (debug or {}).get("results") if isinstance(debug, dict) else None
        match = results[0] if isinstance(results, list) and results else None
        if not isinstance(match, dict) or not match.get("match"):
            return None
        raw_targets = match.get("targets") if isinstance(match.get("targets"), dict) else {}
        targets = [str(entity) for entity, info in raw_targets.items() if isinstance(info, dict) and info.get("matched")]
        try:
            if await self._sensitive(targets):
                return QuickResult(tr("Das geht per Sprache nicht. Türen, Schlösser und Alarmanlagen bediene ich nur getippt im Chat."), blocked=True, targets=targets)
            result = await self.ha.call({"type": "conversation/process", "text": text, "language": self.language, "agent_id": HA_AGENT}, timeout=20)
        except HaApiError as exc:
            log.info("Satz konnte nicht über Home Assistant ausgeführt werden: %s", exc)
            return None
        response = (result or {}).get("response") if isinstance(result, dict) else None
        if not isinstance(response, dict) or response.get("response_type") not in ("action_done", "query_answer"):
            return None
        speech = str((((response.get("speech") or {}).get("plain") or {}).get("speech")) or "").strip()
        return QuickResult(speech or tr("Erledigt."), targets=targets)

    async def _sensitive(self, targets: list[str]) -> bool:
        """Heikles Zielgerät dabei? Schlösser, Alarm und Sirenen immer; Abdeckungen, wenn sie Tür, Tor oder Garage sind."""
        domains = {entity.split(".", 1)[0] for entity in targets}
        if domains & SENSITIVE_DOMAINS_ALWAYS:
            return True
        covers = {entity for entity in targets if entity.startswith("cover.")}
        if not covers:
            return False
        states = await self.ha.call({"type": "get_states"}) or []  # type: ignore[union-attr]
        classes = {s.get("entity_id"): (s.get("attributes") or {}).get("device_class") for s in states if isinstance(s, dict)}
        return any(classes.get(entity) in DOOR_CLASSES for entity in covers)
