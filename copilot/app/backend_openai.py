"""ChatGPT-Anbindung (OpenAI, Responses-API).

Gleiche Schnittstelle wie ``ClaudeSdkBackend`` (``ChatBackend``): Der Chat ist zustandslos, der Verlauf wird bei jeder Anfrage
neu übergeben und bei OpenAI nichts gespeichert (``store: false``). Die Werkzeuge (Home Assistant, Gedächtnis, Dateien, Bilder,
GitHub, Konnektoren, Web lesen) sind anbieterneutrale ``ToolSpec``s; Rechte, Rückfragen und das Aktionsprotokoll liegen in deren
Handlern und gelten damit für ChatGPT genauso wie für Claude. Hier läuft nur die Schleife „Modell fragt Werkzeug an, Ergebnis
zurück“. Die Verbindung geht direkt per httpx (SSE), ohne zusätzliches Paket.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx

from . import usage as usagelib
from .attachments import Attachment, with_inline_text
from .backend import (
    MAX_HISTORY_CHARS,
    MAX_TOOL_TURNS,
    SUMMARY_MAX,
    SUMMARY_PROMPT,
    TITLE_PROMPT,
    BackendError,
    clean_title,
    compose_system,
)
from .ha_tools import ToolError, ToolResult, ToolSpec
from .i18n import tr

log = logging.getLogger("copilot.openai")

OPENAI_BASE_URL = "https://api.openai.com/v1"
EFFORTS = ("low", "medium", "high")
# Ergebnisgrößen wie beim Claude-Zugang (größere Ergebnisse sind für das Modell ohnehin kaum zu gebrauchen)
RESULT_LIMIT = 45_000
RESULT_LIMIT_BIG = 170_000
TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=60.0, pool=15.0)
OPTIONAL_PARAMS = ("reasoning", "include")  # nicht jedes Modell kennt sie: bei „nicht unterstützt“ wird ohne sie wiederholt


# ------------------------------------------------------------------ Fehler

_KEY_LIKE = re.compile(r"sk-[A-Za-z0-9_\-*.]{6,}")


def redact(text: str) -> str:
    """Schlüssel-ähnliche Zeichenfolgen unkenntlich machen (OpenAI nennt in Fehlern manchmal den Anfang des Schlüssels)."""
    return _KEY_LIKE.sub("sk-…", text)


def map_openai_error(status: int | None, payload: Any = None, *, model: str | None = None, retry_after: float | None = None) -> BackendError:
    """OpenAI-Fehler (HTTP-Status plus Fehlerobjekt) in eine verständliche Meldung für die Person übersetzen."""
    error = payload.get("error") if isinstance(payload, dict) and isinstance(payload.get("error"), dict) else {}
    code = str(error.get("code") or error.get("type") or "")
    message = redact(str(error.get("message") or ""))
    resets_at = int(time.time() + retry_after) if retry_after and retry_after > 0 else None
    if status == 401 or code in ("invalid_api_key", "invalid_authentication"):
        return BackendError(tr("Die Anmeldung bei OpenAI ist fehlgeschlagen. Den API-Schlüssel im Add-on prüfen (Chat → OpenAI-API-Schlüssel)."))
    if code in ("insufficient_quota", "billing_hard_limit_reached") or "exceeded your current quota" in message:
        return BackendError(tr("Das Guthaben deines OpenAI-Kontos ist aufgebraucht oder die Abrechnung fehlt. Bei platform.openai.com Guthaben aufladen."))
    if status == 429 or code == "rate_limit_exceeded":
        return BackendError(tr("Das Nutzungslimit bei OpenAI ist erreicht."), resets_at=resets_at)
    if code == "model_not_found" or status == 404:
        return BackendError(tr("OpenAI kennt das Modell „{model}“ nicht oder dein Konto darf es nicht nutzen. Wähle ein anderes Modell oder passe die Liste im Add-on an.", model=model or "?"))
    if status == 403 or "must be verified" in message:
        return BackendError(tr("OpenAI hat den Zugriff abgelehnt (Modell „{model}“ nicht freigegeben, ggf. fehlt die Verifizierung der Organisation bei platform.openai.com).", model=model or "?"))
    if code in ("context_length_exceeded", "string_above_max_length"):
        return BackendError(tr("Der Chat ist für dieses Modell zu lang. Bitte einen neuen Chat beginnen."))
    if (status and status >= 500) or code in ("server_error", "service_unavailable", "overloaded", "internal_error"):
        return BackendError(tr("OpenAI ist gerade nicht erreichbar. Bitte gleich noch einmal versuchen."))
    if status == 400 and message:
        return BackendError(tr("OpenAI hat die Anfrage abgelehnt: {message}", message=message[:200]))
    return BackendError(tr("Unbekannter Fehler bei OpenAI."))


def _retry_after(headers: httpx.Headers) -> float | None:
    try:
        return float(headers.get("retry-after", ""))
    except ValueError:
        return None


def _unsupported_param(status: int, payload: Any, body: dict) -> str | None:
    """Nennt der Fehler einen nur optionalen Parameter als nicht unterstützt? Dann dessen Namen (zum Weglassen)."""
    if status != 400 or not isinstance(payload, dict):
        return None
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    text = f"{error.get('param') or ''} {error.get('message') or ''}".lower()
    if "unsupported" not in text and "not supported" not in text and "unknown parameter" not in text:
        return None
    return next((p for p in OPTIONAL_PARAMS if p in body and p in text), None)


# ---------------------------------------------------------------- Eingabe

def history_items(history: list[dict], reserved: int) -> list[dict]:
    """Verlauf als Eingabeelemente der Responses-API. Ein erster Eintrag ``summary`` (Zusammenfassung) bleibt immer; Älteres fällt zuerst weg."""
    items: list[dict] = []
    used = reserved
    if history and history[0]["role"] == "summary":
        text = "Zusammenfassung des früheren Gesprächs (die älteren Nachrichten wurden dafür ersetzt):\n\n" + history[0]["content"]
        items.append({"role": "user", "content": text})
        used += len(text)
        history = history[1:]
    kept: list[dict] = []
    cut = False
    for item in reversed(history):
        size = len(item["content"])
        if used + size > MAX_HISTORY_CHARS:
            cut = True
            break
        kept.append({"role": "user" if item["role"] == "user" else "assistant", "content": item["content"]})
        used += size
    kept.reverse()
    if cut:
        items.append({"role": "user", "content": "[… ältere Nachrichten wurden gekürzt …]"})
    return items + kept


def user_content(prompt: str, attachments: list[Attachment]) -> list[dict]:
    """Inhaltsteile der neuen Nachricht: Bilder und PDFs als eigene Teile, Textdateien stehen schon im Text."""
    parts: list[dict] = []
    for att in attachments:
        if att.kind == "text":
            continue
        encoded = base64.b64encode(att.data).decode("ascii")
        if att.kind == "image":
            parts.append({"type": "input_image", "image_url": f"data:{att.media_type};base64,{encoded}"})
        else:
            parts.append({"type": "input_file", "filename": att.name, "file_data": f"data:{att.media_type or 'application/pdf'};base64,{encoded}"})
    parts.append({"type": "input_text", "text": prompt})
    return parts


MAX_FUNCTIONS = 120  # die Responses-Schnittstelle erlaubt höchstens 128 Werkzeuge je Anfrage; Platz für die Websuche bleibt


def function_tools(tools: list[ToolSpec]) -> list[dict]:
    result = []
    if len(tools) > MAX_FUNCTIONS:
        log.warning("%d Werkzeuge, die Schnittstelle erlaubt höchstens 128: nur die ersten %d werden angeboten", len(tools), MAX_FUNCTIONS)
    for spec in tools[:MAX_FUNCTIONS]:
        params = spec.schema if isinstance(spec.schema, dict) and spec.schema.get("type") == "object" else {"type": "object", "properties": {}}
        result.append({"type": "function", "name": spec.name, "description": spec.description[:1000], "parameters": params, "strict": False})
    return result


def output_text(response: dict) -> str:
    """Text einer vollständigen (nicht gestreamten) Antwort."""
    parts: list[str] = []
    for item in response.get("output") or []:
        if item.get("type") == "message":
            for block in item.get("content") or []:
                if block.get("type") == "output_text":
                    parts.append(str(block.get("text") or ""))
    return "".join(parts)


class _WebTrace:
    """Meldet die Websuchen von OpenAI (gehostetes Werkzeug) als Aktionen für die Anzeige."""

    def __init__(self, record: Callable[[dict], None], next_id: Callable[[], int]) -> None:
        self._record = record
        self._next_id = next_id
        self._open: dict[str, int] = {}

    def _event(self, tid: int, label: str, status: str, note: str = "") -> None:
        self._record({"type": "tool", "id": tid, "label": label, "status": status, "kind": "web", "note": note})

    def added(self, item: dict) -> None:
        key = str(item.get("id") or "")
        if key and key not in self._open:
            self._open[key] = self._next_id()
            self._event(self._open[key], tr("Websuche"), "running")

    def done(self, item: dict) -> None:
        key = str(item.get("id") or "")
        tid = self._open.pop(key, None)
        if tid is None:
            tid = self._next_id()
        action = item.get("action") if isinstance(item.get("action"), dict) else {}
        query = " ".join(str(action.get("query") or "").split())[:90]
        label = tr("Websuche: {query}", query=query) if query else tr("Websuche")
        failed = item.get("status") == "failed"
        self._event(tid, label, "error" if failed else "ok", tr("Die Suche ist fehlgeschlagen.") if failed else "")

    def close(self) -> None:
        self._open.clear()


# ---------------------------------------------------------------- Backend

class OpenAIBackend:
    def __init__(self, api_key: str, model: str, *, base_url: str = OPENAI_BASE_URL, transport: httpx.AsyncBaseTransport | None = None) -> None:
        if not api_key:
            raise BackendError("Kein OpenAI-Schlüssel hinterlegt (Add-on-Option „openai_api_key“ in der Gruppe Chat oder Bilder).")
        self._key = api_key
        self._model = model
        self._url = base_url.rstrip("/") + "/responses"
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self._transport, timeout=TIMEOUT, follow_redirects=False)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}

    async def _events(self, client: httpx.AsyncClient, body: dict) -> AsyncIterator[dict]:
        """Ereignisse einer gestreamten Antwort. Kennt das Modell einen optionalen Parameter nicht, wird einmal ohne ihn wiederholt."""
        for _attempt in range(len(OPTIONAL_PARAMS) + 1):
            async with client.stream("POST", self._url, json=body, headers=self._headers()) as response:
                if response.status_code != 200:
                    raw = await response.aread()
                    try:
                        payload = json.loads(raw)
                    except ValueError:
                        payload = None
                    param = _unsupported_param(response.status_code, payload, body)
                    if param:
                        log.info("OpenAI: %s wird von %s nicht unterstützt, Wiederholung ohne", param, body.get("model"))
                        body.pop(param, None)
                        continue
                    log.warning("OpenAI-Fehler: status=%s %s", response.status_code, redact(raw[:300].decode("utf-8", "replace")))
                    raise map_openai_error(response.status_code, payload, model=body.get("model"), retry_after=_retry_after(response.headers))
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    try:
                        yield json.loads(data)
                    except ValueError:
                        continue
                return
        raise BackendError(tr("Unbekannter Fehler bei OpenAI."))

    @staticmethod
    def _failure(event: dict, model: str) -> BackendError:
        response = event.get("response") if isinstance(event.get("response"), dict) else {}
        error = event.get("error") if isinstance(event.get("error"), dict) else response.get("error")
        error = error if isinstance(error, dict) else {}
        log.warning("OpenAI-Antwort fehlgeschlagen: %s", redact(json.dumps(error, ensure_ascii=False)[:300]))
        return map_openai_error(None, {"error": error}, model=model) if error.get("code") else BackendError(tr("Unbekannter Fehler bei OpenAI."))

    async def _tool_outputs(self, calls: list[dict], tools: dict[str, ToolSpec]) -> list[dict]:
        """Werkzeugaufrufe nacheinander ausführen; Ergebnisse als Eingabeelemente (Bilder als zusätzliche Nutzernachricht)."""
        outputs: list[dict] = []
        images: list[dict] = []
        for call in calls:
            spec = tools.get(str(call.get("name")))
            text: str
            if spec is None:
                text = "Unbekanntes Werkzeug."
            else:
                try:
                    args = json.loads(call.get("arguments") or "{}")
                except ValueError:
                    args = None
                if not isinstance(args, dict):
                    text = "Die Argumente waren kein gültiges JSON-Objekt."
                else:
                    try:
                        result = await spec.handler(args)
                        text = result.text if isinstance(result, ToolResult) else str(result)
                        if isinstance(result, ToolResult):
                            for data, mime in result.images:
                                images.append({"type": "input_image", "image_url": f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"})
                        limit = RESULT_LIMIT_BIG if spec.big else RESULT_LIMIT
                        if len(text) > limit:
                            text = text[:limit] + f"\n… (gekürzt, {len(text) - limit} Zeichen weggelassen)"
                    except ToolError as exc:
                        text = str(exc)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        log.exception("Werkzeug %s fehlgeschlagen", spec.name)
                        text = "Das Werkzeug ist unerwartet fehlgeschlagen."
            outputs.append({"type": "function_call_output", "call_id": call.get("call_id"), "output": text})
        if images:
            outputs.append({"role": "user", "content": [{"type": "input_text", "text": "Vorschau zu den Werkzeugergebnissen:"}, *images]})
        return outputs

    async def stream(
        self,
        history: list[dict],
        message: str,
        effort: str,
        attachments: list[Attachment] | None = None,
        instructions: str | None = None,
        tools: list[ToolSpec] | None = None,
        note: str = "",
        model: str | None = None,
        web: bool = False,
        record: Callable[[dict], None] | None = None,
        next_id: Callable[[], int] | None = None,
        personal_instructions: str | None = None,
        style: str | None = None,
        on_usage: Callable[[int], None] | None = None,
        **_: object,
    ) -> AsyncIterator[str]:
        model = model or self._model
        system = compose_system(instructions, note, bool(tools), web, personal_instructions, style).replace("WebSearch", "web_search")
        prompt = with_inline_text(message, attachments or [])
        items = history_items(history, len(message))
        items.append({"role": "user", "content": user_content(prompt, attachments or [])})
        by_name = {t.name: t for t in tools or []}
        offered: list[dict] = function_tools(tools or [])
        if web:
            offered.append({"type": "web_search"})
        trace = _WebTrace(record, next_id) if web and record and next_id else None
        body: dict[str, Any] = {
            "model": model,
            "instructions": system,
            "input": items,
            "stream": True,
            "store": False,
            "include": ["reasoning.encrypted_content"],
            "reasoning": {"effort": effort if effort in EFFORTS else "medium"},
        }
        if offered:
            body["tools"] = offered
            body["parallel_tool_calls"] = False
        got_text = False
        turns = MAX_TOOL_TURNS if offered else 1
        try:
            async with self._client() as client:
                for turn in range(turns):
                    output: list[dict] = []
                    seen_items: list[dict] = []
                    new_turn = got_text
                    finished = False
                    async with contextlib.aclosing(self._events(client, body)) as events:
                        async for event in events:
                            kind = str(event.get("type") or "")
                            if kind == "response.output_text.delta":
                                delta = event.get("delta")
                                if delta:
                                    if new_turn:
                                        new_turn = False
                                        yield "\n\n"
                                    got_text = True
                                    yield str(delta)
                            elif kind == "response.output_item.added":
                                item = event.get("item") or {}
                                if trace and item.get("type") == "web_search_call":
                                    trace.added(item)
                            elif kind == "response.output_item.done":
                                item = event.get("item") or {}
                                seen_items.append(item)
                                if trace and item.get("type") == "web_search_call":
                                    trace.done(item)
                            elif kind in ("response.completed", "response.incomplete"):
                                response = event.get("response") or {}
                                output = list(response.get("output") or seen_items)
                                usage = response.get("usage") or {}
                                total = int(usage.get("total_tokens") or (int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)))
                                usagelib.report("openai", model, int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0) )
                                if on_usage and total:
                                    try:
                                        on_usage(total)
                                    except Exception:
                                        log.warning("Tokenverbrauch konnte nicht gezählt werden", exc_info=True)
                                if kind == "response.incomplete":
                                    reason = str((response.get("incomplete_details") or {}).get("reason") or "")
                                    if reason == "content_filter":
                                        raise BackendError(tr("OpenAI hat die Antwort wegen seiner Inhaltsregeln abgebrochen."))
                                    if not got_text and not any(i.get("type") == "function_call" for i in output):
                                        raise BackendError(tr("OpenAI hat die Antwort vorzeitig beendet."))
                                finished = True
                            elif kind in ("response.failed", "error"):
                                raise self._failure(event, model)
                    if not finished:
                        raise BackendError(tr("Die Verbindung zu OpenAI ist abgebrochen."))
                    calls = [i for i in output if i.get("type") == "function_call"]
                    if not calls:
                        break
                    if turn == turns - 1:
                        yield "\n\n" + tr("_Abgebrochen: zu viele Werkzeugaufrufe in einer Antwort._")
                        break
                    # Ausgabe der Runde (samt verschlüsseltem Denkverlauf) und die Werkzeugergebnisse zurückgeben
                    body["input"] = [*body["input"], *output, *await self._tool_outputs(calls, by_name)]
        except BackendError:
            raise
        except asyncio.CancelledError:
            raise
        except httpx.HTTPError as exc:
            log.warning("OpenAI-Verbindung fehlgeschlagen: %s", exc.__class__.__name__)
            raise BackendError(tr("Die Verbindung zu OpenAI ist fehlgeschlagen.")) from exc
        except Exception as exc:
            log.exception("OpenAI-Aufruf fehlgeschlagen")
            raise BackendError(tr("Die Verbindung zu OpenAI ist fehlgeschlagen.")) from exc
        finally:
            if trace:
                trace.close()

    # --------------------------------------------------- Titel und Zusammenfassung

    async def _complete(self, prompt: str, system: str, model: str, on_usage: Callable[[int], None] | None = None) -> str:
        """Einmalige Anfrage ohne Streaming; liefert den Text oder wirft BackendError."""
        body: dict[str, Any] = {
            "model": model, "instructions": system, "input": prompt, "store": False,
            "reasoning": {"effort": "low"},
        }
        async with self._client() as client:
            for _attempt in range(2):
                response = await client.post(self._url, json=body, headers=self._headers())
                if response.status_code == 200:
                    data = response.json()
                    usage = data.get("usage") or {}
                    usagelib.report("openai", model, int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0))
                    if on_usage and usage.get("total_tokens"):
                        with contextlib.suppress(Exception):
                            on_usage(int(usage["total_tokens"]))
                    return output_text(data)
                try:
                    payload = response.json()
                except ValueError:
                    payload = None
                param = _unsupported_param(response.status_code, payload, body)
                if param:
                    body.pop(param, None)
                    continue
                raise map_openai_error(response.status_code, payload, model=model, retry_after=_retry_after(response.headers))
        raise BackendError(tr("Unbekannter Fehler bei OpenAI."))

    async def title(self, user_text: str, answer: str, model: str | None = None, on_usage: Callable[[int], None] | None = None) -> str | None:
        prompt = (
            "Nachricht des Nutzers:\n" + user_text[:1500]
            + "\n\nAntwort des Assistenten (Anfang):\n" + answer[:600]
            + "\n\nTitel:"
        )
        try:
            return clean_title(await self._complete(prompt, TITLE_PROMPT, model or self._model, on_usage))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("Chat-Titel konnte nicht erzeugt werden", exc_info=True)
            return None

    async def summarize(self, previous: str | None, messages: list[dict], model: str | None = None, on_usage: Callable[[int], None] | None = None) -> str | None:
        from .compact import clip

        transcript = "\n\n".join(f"[{'Nutzer' if m['role'] == 'user' else 'Assistent'}]\n{clip(m['content'])}" for m in messages)
        prompt = (
            (f"Bisherige Zusammenfassung:\n{previous}\n\n" if previous else "")
            + "Neue Nachrichten, die in die Zusammenfassung aufgenommen werden sollen:\n\n"
            + transcript
            + "\n\nSchreibe jetzt die vollständige, aktualisierte Zusammenfassung."
        )
        try:
            text = (await self._complete(prompt, SUMMARY_PROMPT, model or self._model, on_usage)).strip()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("Zusammenfassung konnte nicht erzeugt werden", exc_info=True)
            return None
        return text[:SUMMARY_MAX] or None
