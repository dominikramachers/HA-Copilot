"""Bilder der KI: erzeugen mit OpenAI oder Google, zeichnen als SVG, bearbeiten im selben Chat.

Claude selbst erzeugt keine Bildpunkte. Deshalb hat die KI zwei Werkzeuge, zwischen denen sie nach Aufwand wählt:

* ``image_svg``: Claude schreibt das Bild als SVG-Quelltext (Diagramme, Logos, Symbole, Pläne). Kostenlos, ohne Schlüssel,
  beliebig oft änderbar. Der Server prüft den Quelltext streng (keine Skripte, kein Netzzugriff).
* ``image_generate``: ein Bildmodell von OpenAI oder Google erzeugt oder verändert ein Bild (Fotos, Illustrationen,
  Kunst, Bilder mit Schrift). Das kostet je Bild Geld auf dem API-Konto des Betreibers, deshalb gibt es ein Monatslimit
  je Person; ab dem Limit fragt der Chat vor jedem weiteren Bild nach.

Die API-Schlüssel liegen nur in der Add-on-Konfiguration und gehen ausschließlich als Anmelde-Kopfzeile an die
jeweilige Schnittstelle; sie tauchen weder in Meldungen noch im Protokoll auf. Der Bildwunsch (und ein Referenzbild
bei Änderungen) wird an den gewählten Anbieter übertragen.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import re
import struct
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx

from .db import Store
from .ha_tools import Ask, ToolError, ToolSpec
from .i18n import tr

log = logging.getLogger("copilot.images")

OPENAI_URL = "https://api.openai.com/v1/images"
GOOGLE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
REQUEST_TIMEOUT = 240
MAX_PROMPT_CHARS = 4000
MAX_REFERENCES = 4
MAX_REF_BYTES = 20 * 1024 * 1024
MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_SVG_BYTES = 1_500_000
MAX_PER_RUN = 4
MAX_PROFILE_BYTES = 300 * 1024 * 1024

SIZES = {  # Bildformat -> (OpenAI-Größe, Google-Seitenverhältnis)
    "square": ("1024x1024", "1:1"),
    "landscape": ("1536x1024", "3:2"),
    "portrait": ("1024x1536", "2:3"),
}
QUALITY = {"draft": "low", "standard": "medium", "high": "high"}  # nur OpenAI; Google kennt keine Stufen
EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}

DENIED_TAGS = {
    "script", "foreignobject", "iframe", "object", "embed", "audio", "video", "canvas", "image", "animate", "animatemotion",
    "animatetransform", "set", "a", "handler", "listener", "switch",
}
_VERSION_RE = re.compile(r"-v(\d+)$")


class ImageError(ToolError):
    """Das Bild konnte nicht erzeugt werden (Meldung geht an die KI)."""


# ------------------------------------------------------------------ Bilddaten

def sniff(data: bytes) -> tuple[str, int, int] | None:
    """(Medientyp, Breite, Höhe) eines PNG-, JPEG-, WebP- oder GIF-Bildes; ``None`` bei allem anderen."""
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
            w, h = struct.unpack(">II", data[16:24])
            return "image/png", w, h
        if data[:6] in (b"GIF87a", b"GIF89a"):
            w, h = struct.unpack("<HH", data[6:10])
            return "image/gif", w, h
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            kind = data[12:16]
            if kind == b"VP8X":
                return "image/webp", 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
            if kind == b"VP8L":
                bits = int.from_bytes(data[21:25], "little")
                return "image/webp", 1 + (bits & 0x3FFF), 1 + ((bits >> 14) & 0x3FFF)
            if kind == b"VP8 ":
                w, h = struct.unpack("<HH", data[26:30])
                return "image/webp", w & 0x3FFF, h & 0x3FFF
            return "image/webp", 0, 0
        if data[:2] == b"\xff\xd8":
            i = 2
            while i + 9 < len(data):
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                    i += 2
                    continue
                length = struct.unpack(">H", data[i + 2:i + 4])[0]
                if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                    h, w = struct.unpack(">HH", data[i + 5:i + 9])
                    return "image/jpeg", w, h
                i += 2 + length
            return "image/jpeg", 0, 0
    except (struct.error, IndexError):
        return None
    return None


def slug(text: str, default: str = "bild") -> str:
    """Dateiname aus einer Kurzbeschreibung: ``Katze im Garten`` -> ``katze-im-garten``."""
    table = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "ae", "Ö": "oe", "Ü": "ue"})
    text = re.sub(r"[^a-z0-9]+", "-", str(text or "").translate(table).lower()).strip("-")[:40].strip("-")
    return text or default


def series_base(name: str) -> str:
    """``katze-v3.png`` -> ``katze``: gemeinsamer Name aller Fassungen eines Bildes."""
    stem = name.rsplit(".", 1)[0]
    return _VERSION_RE.sub("", stem)


# ------------------------------------------------------------------------ SVG

def check_svg(text: str) -> tuple[str, int, int]:
    """SVG-Quelltext prüfen; liefert (Quelltext, Breite, Höhe). Wirft ``ImageError`` bei allem, was nicht rein zeichnerisch ist.

    Erlaubt sind Formen, Text, Verläufe, Muster und Verweise auf Teile derselben Datei (``#id``). Verboten sind Skripte,
    Ereignisattribute, eingebettete Seiten und Bilder, Animationen und jede Adresse außer ``#id``.
    """
    src = str(text or "").strip().lstrip("﻿")
    if not src:
        raise ImageError("svg fehlt. Liefere den vollständigen SVG-Quelltext (beginnend mit <svg …>).")
    if len(src.encode("utf-8")) > MAX_SVG_BYTES:
        raise ImageError(f"Das SVG ist zu groß (höchstens {MAX_SVG_BYTES // 1000} kB). Vereinfache die Zeichnung.")
    if re.search(r"<!(DOCTYPE|ENTITY)", src, re.I):
        raise ImageError("DOCTYPE und ENTITY sind in SVG nicht erlaubt. Beginne direkt mit <svg …>.")
    src = re.sub(r"^<\?xml[^>]*\?>\s*", "", src)
    try:
        root = ET.fromstring(src)
    except ET.ParseError as exc:
        raise ImageError(f"Das SVG ist kein gültiges XML ({exc}). Prüfe geschlossene Tags und maskiere & als &amp;.") from None

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1].lower()

    if local(root.tag) != "svg":
        raise ImageError("Das Wurzelelement muss <svg> sein.")
    for el in root.iter():
        name = local(el.tag) if isinstance(el.tag, str) else ""
        if name in DENIED_TAGS:
            raise ImageError(f"Das Element <{name}> ist in SVG-Bildern nicht erlaubt (keine Skripte, Bilder, Animationen oder Links).")
        if name == "style":
            css = el.text or ""
            if re.search(r"@import|expression\s*\(|javascript:|url\(\s*(?!['\"]?#)", css, re.I):
                raise ImageError("In <style> sind @import und Adressen außer url(#id) nicht erlaubt.")
        for key, value in el.attrib.items():
            attr = key.rsplit("}", 1)[-1].lower()
            if attr.startswith("on"):
                raise ImageError(f"Das Attribut {attr} (Ereignis) ist nicht erlaubt.")
            if attr == "href" and not str(value).strip().startswith("#"):
                raise ImageError("Verweise (href) dürfen nur auf Teile derselben Datei zeigen (#id). Bilder und Adressen von außen sind nicht erlaubt.")
            if re.search(r"javascript:|data:|url\(\s*(?!['\"]?#)", str(value), re.I) and attr != "d":
                raise ImageError(f"Das Attribut {attr} enthält eine unzulässige Adresse. Erlaubt ist nur url(#id).")

    if "xmlns" not in root.attrib and not root.tag.startswith("{"):
        src = re.sub(r"<svg\b", '<svg xmlns="http://www.w3.org/2000/svg"', src, count=1, flags=re.I)

    def num(value: str | None) -> float:
        match = re.match(r"^\s*([0-9]*\.?[0-9]+)", value or "")
        return float(match.group(1)) if match else 0

    width, height = num(root.attrib.get("width")), num(root.attrib.get("height"))
    if not (width and height):
        parts = re.split(r"[\s,]+", (root.attrib.get("viewBox") or "").strip())
        if len(parts) == 4:
            try:
                width, height = float(parts[2]), float(parts[3])
            except ValueError:
                width = height = 0
    if not (width and height):
        raise ImageError("Das <svg> braucht ein viewBox (z. B. viewBox=\"0 0 800 600\") oder width und height.")
    return src, int(width), int(height)


# ---------------------------------------------------------------- Anbieter

def _api_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
        err = payload.get("error", payload) if isinstance(payload, dict) else {}
        text = err.get("message") if isinstance(err, dict) else str(err)
    except ValueError:
        text = response.text
    return re.sub(r"\s+", " ", str(text or "")).strip()[:300]


def explain_failure(provider: str, status: int, message: str) -> str:
    who = {"openai": "OpenAI", "google": "Google"}[provider]
    if status in (401, 403) and re.search(r"verif", message, re.I):
        return f"{who} verlangt für dieses Modell eine verifizierte Organisation ({message}). Der Betreiber muss das im Konto bei {who} abschließen."
    if status in (401, 403):
        return f"{who} hat den API-Schlüssel abgelehnt oder das Konto darf dieses Modell nicht nutzen ({message}). Der Betreiber prüft Schlüssel und Konto."
    if status == 402 or (status == 429 and re.search(r"quota|billing|credit|insufficient|exhaust", message, re.I)):
        return f"Das Guthaben oder Kontingent bei {who} ist aufgebraucht ({message}). Der Betreiber muss es aufladen."
    if status == 429:
        return f"{who} bremst gerade (zu viele Anfragen). In einer Minute noch einmal versuchen."
    if status == 404:
        return f"{who} kennt dieses Bildmodell nicht ({message}). Der Betreiber prüft den Modellnamen in der Konfiguration."
    if status == 400:
        return f"{who} hat den Bildwunsch abgelehnt ({message}). Formuliere ihn anders (keine geschützten Figuren, keine Gewalt, keine erkennbaren realen Personen) und versuche es noch einmal."
    return f"{who} meldet einen Fehler (HTTP {status}): {message}"


class ImageService:
    """Spricht mit OpenAI und Google. Hält die Schlüssel und die Modellnamen aus der Konfiguration."""

    def __init__(self, settings: Any, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.openai_key = getattr(settings, "openai_api_key", "")
        self.google_key = getattr(settings, "google_api_key", "")
        self.openai_model = getattr(settings, "image_model_openai", "")
        self.google_model = getattr(settings, "image_model_google", "")
        self.preferred = getattr(settings, "image_provider", "auto")
        self.transport = transport

    def providers(self) -> list[str]:
        return [p for p, key in (("openai", self.openai_key), ("google", self.google_key)) if key]

    def model_of(self, provider: str) -> str:
        return self.openai_model if provider == "openai" else self.google_model

    def choose(self, requested: str) -> str:
        """Anbieter für dieses Bild: Vorgabe in der Konfiguration, sonst Wunsch der KI, sonst Google (günstiger) bzw. der einzige."""
        have = self.providers()
        if not have:
            raise ImageError("Es ist kein Bildanbieter eingerichtet (OpenAI- oder Google-Schlüssel fehlen). Zeichne das Bild stattdessen als SVG mit image_svg, wenn es sich dafür eignet, und sage der Person, dass für Fotos und Kunstbilder der Betreiber einen Schlüssel eintragen muss.")
        if self.preferred in have:
            return self.preferred
        if requested in have:
            return requested
        return "google" if "google" in have else have[0]

    async def generate(self, provider: str, prompt: str, size: str, quality: str, refs: list[tuple[str, bytes, str]]) -> bytes:
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=15)) as client:
                if provider == "openai":
                    return await self._openai(client, prompt, size, quality, refs)
                return await self._google(client, prompt, size, refs)
        except (httpx.TimeoutException, TimeoutError):
            raise ImageError("Das Bildmodell hat zu lange gebraucht. Noch einmal versuchen oder einen einfacheren Bildwunsch formulieren.") from None
        except httpx.HTTPError as exc:
            log.warning("Bildanbieter %s nicht erreichbar: %s", provider, type(exc).__name__)
            raise ImageError("Der Bildanbieter ist gerade nicht erreichbar. Später noch einmal versuchen.") from None

    async def _openai(self, client: httpx.AsyncClient, prompt: str, size: str, quality: str, refs: list[tuple[str, bytes, str]]) -> bytes:
        headers = {"Authorization": f"Bearer {self.openai_key}"}
        fields = {"model": self.openai_model, "prompt": prompt, "size": SIZES[size][0], "quality": QUALITY[quality], "n": "1"}
        if refs:
            files = [("image[]", (name, data, mime)) for name, data, mime in refs]
            response = await client.post(f"{OPENAI_URL}/edits", headers=headers, data=fields, files=files)
        else:
            response = await client.post(f"{OPENAI_URL}/generations", headers=headers, json={**fields, "n": 1})
        if response.status_code != 200:
            raise ImageError(explain_failure("openai", response.status_code, _api_message(response)))
        try:
            return base64.b64decode(response.json()["data"][0]["b64_json"], validate=False)
        except (ValueError, KeyError, IndexError, TypeError):
            raise ImageError("OpenAI hat kein Bild geliefert. Noch einmal versuchen.") from None

    async def _google(self, client: httpx.AsyncClient, prompt: str, size: str, refs: list[tuple[str, bytes, str]]) -> bytes:
        parts: list[dict] = [{"text": prompt}]
        parts += [{"inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode()}} for _, data, mime in refs]
        body = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"], "imageConfig": {"aspectRatio": SIZES[size][1]}},
        }
        response = await client.post(f"{GOOGLE_URL}/{self.google_model}:generateContent", headers={"x-goog-api-key": self.google_key}, json=body)
        if response.status_code != 200:
            raise ImageError(explain_failure("google", response.status_code, _api_message(response)))
        try:
            payload = response.json()
        except ValueError:
            raise ImageError("Google hat eine unlesbare Antwort geliefert. Noch einmal versuchen.") from None
        blocked = (payload.get("promptFeedback") or {}).get("blockReason")
        for candidate in payload.get("candidates") or []:
            for part in (candidate.get("content") or {}).get("parts") or []:
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    return base64.b64decode(inline["data"])
        if blocked:
            raise ImageError(f"Google hat den Bildwunsch aus Sicherheitsgründen abgelehnt ({blocked}). Formuliere ihn anders und versuche es noch einmal.")
        reasons = ", ".join(str(c.get("finishReason")) for c in payload.get("candidates") or [] if c.get("finishReason"))
        raise ImageError("Google hat kein Bild geliefert" + (f" ({reasons})" if reasons else "") + ". Formuliere den Wunsch anders oder versuche es noch einmal.")


# --------------------------------------------------------------- Werkzeuge

IMAGE_GENERATE_TEXT = (
    "Erzeugt oder verändert ein Bild mit einem Bildmodell (OpenAI oder Google): Fotos, Illustrationen, Kunst, Bilder mit Schrift. "
    "Das kostet echtes Geld und zählt auf das Monatslimit der Person. Für Diagramme, Logos, Symbole und Pläne nimm image_svg. "
    "Mit reference änderst du ein vorhandenes Bild (ein Foto der Person oder ein früher erzeugtes Bild dieses Chats): "
    "beschreibe im prompt nur die Änderung und was gleich bleiben soll. Es erscheint als Karte mit Vorschau unter deiner Antwort."
)
IMAGE_SVG_TEXT = (
    "Zeichnet ein Bild als SVG (kostenlos, ohne Bildmodell): Diagramme, Ablaufpläne, Grundrisse, Logos, Symbole, einfache Illustrationen. "
    "Liefere den vollständigen SVG-Quelltext mit viewBox. Verboten: Skripte, Bilder, Animationen, Links und Adressen von außen. "
    "Mit reference entsteht eine neue Fassung eines früheren SVG (lies den Quelltext vorher mit file_read). Es erscheint als Karte unter deiner Antwort."
)

IMAGES_NOTE = (
    "Bilder: Wünscht die Person ein Bild (Zeichnung, Foto, Logo, Illustration, Diagramm, Plakat, Grundriss …), erzeugst du es selbst mit den Werkzeugen, ohne nachzufragen, ob du darfst. "
    "Wähle nach Aufwand: Diagramme, Ablaufpläne, Grundrisse, Logos, Symbole und einfache Grafiken zeichnest du kostenlos als SVG mit image_svg. "
    "Fotorealistisches, Kunstvolles, Komplexes oder Bilder mit viel Schrift erzeugst du mit image_generate. "
    "Sind beide Anbieter eingerichtet: Google für Entwürfe und Änderungen (günstiger), OpenAI für Bilder mit Schrift oder höchster Qualität. "
    "Sage der Person in einem Satz, welchen Weg du gewählt hast und warum. Erzeuge nur ein Bild je Wunsch, außer die Person bittet um Varianten; jedes Bild von OpenAI oder Google kostet Geld. "
    "Schreibe den Bildwunsch (prompt) in der Sprache der Person oder auf Englisch, konkret mit Motiv, Stil, Stimmung, Bildaufteilung. Texte im Bild exakt in Anführungszeichen. "
    "Änderungswünsche („kleiner“, „anderer Hintergrund“, „gefällt mir nicht“) setzt du im selben Chat am vorhandenen Bild um: reference auf das letzte Bild setzen und nur die Änderung beschreiben. "
    "Es entsteht eine neue Fassung („Version 2“), die alte bleibt erhalten. Ein Foto, das die Person anhängt, kannst du als reference verwenden. "
    "Du siehst die erzeugten Bilder nicht selbst; beschreibe sie nicht im Einzelnen, sondern sage, was du beauftragt hast. Füge keinen SVG-Quelltext in die Antwort ein, außer die Person möchte ihn. "
    "Ein Bild bekommt eine Karte mit Vorschau automatisch; erwähne keinen Link und keinen Pfad."
)


class ImageToolbox:
    """``image_generate`` und ``image_svg``."""

    def __init__(
        self,
        store: Store,
        profile_id: str,
        chat_id: str,
        service: ImageService,
        *,
        record: Callable[[dict], None],
        next_id: Callable[[], int],
        keep_days: int,
        limit_month: int,
        ask: Ask | None,
        tainted: Callable[[], bool],
        generate: bool = True,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.store = store
        self.profile_id = profile_id
        self.chat_id = chat_id
        self.service = service
        self._record = record
        self._next_id = next_id
        self.keep_days = keep_days
        self.limit_month = limit_month
        self._ask = ask
        self._tainted = tainted
        self.generate_enabled = generate and bool(service.providers())
        self._now = now
        self.made = 0

    def month(self) -> str:
        return self._now().strftime("%Y-%m")

    def used(self) -> int:
        return self.store.image_usage(self.profile_id, self.month())

    def usage_note(self) -> str:
        if not self.generate_enabled:
            return ""
        used = self.used()
        if self.limit_month:
            return f" Diesen Monat hat die Person {used} von {self.limit_month} Bildern von OpenAI/Google erzeugt."
        return f" Diesen Monat hat die Person {used} Bilder von OpenAI/Google erzeugt (kein Limit)."

    def _event(self, tid: int, label: str, status: str, note: str = "", file: dict | None = None) -> None:
        event: dict[str, Any] = {"type": "tool", "id": tid, "label": label, "status": status, "kind": "image", "note": note}
        if file:
            event["file"] = file
        self._record(event)

    def _check_room(self) -> None:
        if self.made >= MAX_PER_RUN:
            raise ImageError(f"Pro Antwort sind höchstens {MAX_PER_RUN} Bilder möglich.")
        if self.store.outfile_usage(self.profile_id) >= MAX_PROFILE_BYTES:
            raise ImageError("Der Speicher für erzeugte Dateien ist voll. Die Person kann alte Chats löschen oder wartet, bis die Dateien verfallen.")

    def _images_of_chat(self) -> list[dict]:
        return [m for m in self.store.outfile_list(self.profile_id, self.chat_id) if m["mime"].startswith("image/")]

    def _load_reference(self, raw: Any) -> list[tuple[str, bytes, str]]:
        names = [raw] if isinstance(raw, str) else list(raw or [])
        names = [str(n).strip() for n in names if str(n).strip()]
        if len(names) > MAX_REFERENCES:
            raise ImageError(f"Höchstens {MAX_REFERENCES} Referenzbilder je Wunsch.")
        known = self._images_of_chat()
        result: list[tuple[str, bytes, str]] = []
        for wanted in names:
            meta = next((m for m in known if m["name"] == wanted), None) or next((m for m in known if m["name"].lower() == wanted.lower()), None)
            if meta is None:
                have = ", ".join(m["name"] for m in known[:12]) or "keine"
                raise ImageError(f"Das Bild „{wanted}“ gibt es in diesem Chat nicht. Vorhandene Bilder: {have}. Die Person kann ein Foto neu anhängen.")
            data = self.store.outfile_bytes(self.profile_id, self.chat_id, meta["name"])
            found = sniff(data) if data else None
            if not found:
                raise ImageError(f"„{wanted}“ ist als Referenz nicht brauchbar (PNG, JPEG oder WebP nötig; SVG und GIF gehen nicht).")
            if found[0] == "image/gif":
                raise ImageError(f"„{wanted}“ ist ein GIF und als Referenz nicht möglich (PNG, JPEG oder WebP nötig).")
            if len(data) > MAX_REF_BYTES:
                raise ImageError(f"„{wanted}“ ist zu groß als Referenz (höchstens {MAX_REF_BYTES // 1024 // 1024} MB).")
            result.append((meta["name"], data, found[0]))
        return result

    def _next_name(self, title: str, reference: Any, ext: str) -> tuple[str, int]:
        """Dateiname der neuen Fassung: gehört das Bild zu einer Reihe (Referenz auf ein erzeugtes Bild), zählt die Version weiter."""
        first = reference if isinstance(reference, str) else (list(reference or [""]) or [""])[0]
        files = self.store.outfile_list(self.profile_id, self.chat_id)
        meta = next((m for m in files if m["name"].lower() == str(first).strip().lower()), None) if first else None
        base = series_base(meta["name"]) if meta and meta["origin"] == "ai" else slug(title)
        pattern = re.compile(rf"^{re.escape(base)}(?:-v(\d+))?\.[a-z0-9]+$")
        versions = [int(m.group(1) or 1) for f in files if (m := pattern.match(f["name"]))]
        version = max(versions, default=0) + 1
        return (f"{base}.{ext}" if version == 1 else f"{base}-v{version}.{ext}"), version

    def _store(self, tid: int, title: str, reference: Any, data: bytes, mime: str, w: int, h: int, engine: str) -> dict:
        ext = "svg" if mime == "image/svg+xml" else EXT.get(mime, "png")
        name, version = self._next_name(title, reference, ext)
        meta = self.store.outfile_add(self.profile_id, self.chat_id, name, mime, data, self.keep_days)
        if meta is None:
            raise ImageError("Der Chat existiert nicht mehr.")
        self.made += 1
        return {"id": meta["id"], "name": name, "size": meta["size"], "image": True, "w": w, "h": h, "version": version, "engine": engine}

    async def _confirm(self, label: str, details: str, reasons: list[str]) -> None:
        if self._ask is None:
            raise ImageError("Hier kann nicht nachgefragt werden, deshalb entsteht kein Bild von OpenAI oder Google. Zeichne es als SVG oder sage der Person, dass sie es im Chat selbst anfordern soll.")
        answer = await self._ask(label, details + "\n\n" + "\n".join(reasons), False)
        if answer == "deny":
            raise ImageError("Die Person hat das Bild abgelehnt. Frage nicht erneut nach, sondern biete höchstens eine Alternative an (z. B. SVG).")

    async def image_generate(self, args: dict) -> str:
        tid = self._next_id()
        title = re.sub(r"\s+", " ", str(args.get("title") or "")).strip()[:60]
        label = tr("Bild erzeugen: {name}", name=title) if title else tr("Bild erzeugen")
        self._event(tid, label, "running")
        try:
            prompt = str(args.get("prompt") or "").strip()
            if len(prompt) < 3:
                raise ImageError("prompt fehlt. Beschreibe das Bild (Motiv, Stil, Stimmung) oder bei einer Änderung, was anders werden soll.")
            if len(prompt) > MAX_PROMPT_CHARS:
                raise ImageError(f"prompt ist zu lang (höchstens {MAX_PROMPT_CHARS} Zeichen).")
            size = str(args.get("format") or "square")
            if size not in SIZES:
                raise ImageError("format muss square, landscape oder portrait sein.")
            quality = str(args.get("quality") or "standard")
            if quality not in QUALITY:
                raise ImageError("quality muss draft, standard oder high sein.")
            self._check_room()
            provider = self.service.choose(str(args.get("provider") or ""))
            refs = self._load_reference(args.get("reference"))
            if provider == "google":
                prompt += {"square": "\n\n(Format: quadratisch 1:1)", "landscape": "\n\n(Format: Querformat 3:2)", "portrait": "\n\n(Format: Hochformat 2:3)"}[size]

            reasons, short = [], []
            if self._tainted():
                reasons.append(tr("Vorher wurden Inhalte aus dem Web oder aus Dateien gelesen. Solche Inhalte können Anweisungen enthalten, deshalb wird vor dem Bild nachgefragt."))
                short.append(tr("nach gelesenen Inhalten aus Web oder Dateien"))
            used = self.used()
            if self.limit_month and used >= self.limit_month:
                reasons.append(tr("Das Monatslimit von {limit} Bildern ist erreicht ({used} erzeugt).", limit=self.limit_month, used=used))
                short.append(tr("Monatslimit erreicht: {used} von {limit} Bildern", used=used, limit=self.limit_month))
            if reasons:
                self._event(tid, label, "waiting")
                who = "OpenAI" if provider == "openai" else "Google"
                details = tr("Anbieter: {who} ({model})", who=who, model=self.service.model_of(provider)) + "\n" + tr("Bildwunsch: {prompt}", prompt=prompt[:1500])
                if refs:
                    details += "\n" + tr("Referenzbild: {names}", names=", ".join(r[0] for r in refs)) + " " + tr("(wird an {who} übertragen)", who=who)
                await self._confirm(f"{label} ({'; '.join(short)})", details, reasons)
                self._event(tid, label, "running")

            data = await self.service.generate(provider, prompt, size, quality, refs)
            found = sniff(data)
            if not found or len(data) > MAX_IMAGE_BYTES:
                raise ImageError("Der Anbieter hat kein brauchbares Bild geliefert. Noch einmal versuchen.")
            file = self._store(tid, title or "bild", args.get("reference"), data, found[0], found[1], found[2], provider)
            self.store.image_usage_add(self.profile_id, self.month())
        except ToolError as exc:
            self._event(tid, label, "error", str(exc)[:200])
            raise
        self._event(tid, tr("Bild erzeugt: {name}", name=file["name"]), "ok", file=file)
        who = "OpenAI" if provider == "openai" else "Google"
        return (
            f"Bild {file['name']} erzeugt ({who}, {file['w']}×{file['h']}, Fassung {file['version']}). Es erscheint als Karte mit Vorschau unter deiner Antwort; "
            f"die Person kann es dort öffnen und herunterladen. Du siehst das Bild nicht. Sage kurz, was du beauftragt hast und welchen Weg du gewählt hast. "
            f"Für Änderungen rufst du image_generate mit reference=\"{file['name']}\" auf.{self.usage_note()}"
        )

    async def image_svg(self, args: dict) -> str:
        tid = self._next_id()
        title = re.sub(r"\s+", " ", str(args.get("title") or "")).strip()[:60]
        label = tr("Bild zeichnen: {name}", name=title) if title else tr("Bild zeichnen")
        self._event(tid, label, "running")
        try:
            self._check_room()
            reference = args.get("reference")
            if reference:
                known = {m["name"].lower(): m for m in self.store.outfile_list(self.profile_id, self.chat_id)}
                if str(reference).strip().lower() not in known:
                    raise ImageError(f"Die Datei „{reference}“ gibt es in diesem Chat nicht. Lass reference weg, um ein neues Bild zu beginnen.")
            src, w, h = check_svg(args.get("svg"))
            file = self._store(tid, title or "zeichnung", reference, src.encode("utf-8"), "image/svg+xml", w, h, "svg")
        except ToolError as exc:
            self._event(tid, label, "error", str(exc)[:200])
            raise
        self._event(tid, tr("Bild gezeichnet: {name}", name=file["name"]), "ok", file=file)
        return (
            f"SVG {file['name']} gespeichert (Fassung {file['version']}). Es erscheint als Karte mit Vorschau unter deiner Antwort. "
            f"Du siehst die Zeichnung nicht; sage kurz, was sie zeigt. Für Änderungen lies den Quelltext mit file_read(\"{file['name']}\"), ändere ihn und rufe image_svg mit reference=\"{file['name']}\" auf."
        )

    def specs(self) -> list[ToolSpec]:
        title = {"type": "string", "description": "Kurzer Titel des Bildes (2 bis 5 Wörter), daraus entsteht der Dateiname"}
        reference = {"type": "string", "description": "Optional: Dateiname eines vorhandenen Bildes dieses Chats, das geändert oder als Vorlage dienen soll (Anhang oder früher erzeugt)"}
        specs = []
        if self.generate_enabled:
            specs.append(ToolSpec(
                "image_generate", IMAGE_GENERATE_TEXT,
                {"type": "object", "properties": {
                    "prompt": {"type": "string", "description": "Bildwunsch bzw. gewünschte Änderung"},
                    "title": title,
                    "format": {"type": "string", "enum": list(SIZES), "description": "square (Standard), landscape (Querformat) oder portrait (Hochformat)"},
                    "quality": {"type": "string", "enum": list(QUALITY), "description": "draft (schnell, günstig), standard (Standard), high (beste Qualität); wirkt nur bei OpenAI"},
                    "provider": {"type": "string", "enum": ["openai", "google"], "description": "Wunsch-Anbieter, falls beide eingerichtet sind: google für Entwürfe und Änderungen, openai für Schrift im Bild oder höchste Qualität"},
                    "reference": reference,
                }, "required": ["prompt", "title"]},
                self.image_generate, "execute",
            ))
        specs.append(ToolSpec(
            "image_svg", IMAGE_SVG_TEXT,
            {"type": "object", "properties": {"svg": {"type": "string", "description": "Vollständiger SVG-Quelltext mit viewBox"}, "title": title, "reference": reference}, "required": ["svg", "title"]},
            self.image_svg, "execute",
        ))
        return specs
