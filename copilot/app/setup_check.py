"""Einrichtungsprüfung: Was ist eingerichtet, was fehlt, und wie behebt man es Schritt für Schritt?

Die Prüfung liest nur die Konfiguration und fragt (kurz) bei Home Assistant und GitHub nach. Sie zeigt nie ein Geheimnis,
nur ob es gesetzt ist. Jede Zeile hat eine Wichtigkeit (``required`` nötig, ``recommended`` empfohlen, ``optional``)
und einen Zustand (``ok``, ``todo`` fehlt, ``warn`` Achtung, ``off`` nicht eingerichtet, ``unknown`` nicht prüfbar).
Ein Eintrag mit Zustand ``todo`` oder ``warn`` enthält die genauen Schritte.
"""
from __future__ import annotations

import asyncio
import re
from collections import OrderedDict
from collections.abc import Iterable

from .config import Profile, Settings
from .i18n import tr
from .github_api import GithubApi, GithubError
from .ha_client import HaApi, HaApiError

CONFIG_STEP = "Öffne in Home Assistant Einstellungen → Apps (früher Add-ons) → HA Copilot → Konfiguration."
RESTART_STEP = "Speichere und starte das Add-on neu (Reiter „Info“ → Neustart)."
LEVEL_ORDER = {"required": 0, "recommended": 1, "optional": 2}
ACCESS_TEXT = {
    "read": "Die KI darf in Home Assistant lesen (Zustände, Verläufe, Konfiguration).",
    "execute": "Die KI darf in Home Assistant lesen und Geräte bedienen.",
    "write": "Die KI darf in Home Assistant lesen, Geräte bedienen und Automationen, Skripte und Szenen ändern.",
}
BANNER_TEXT = "Der Chat läuft im Testmodus: Es ist noch kein Zugang zu Claude eingerichtet."


def banner(settings: Settings) -> str | None:
    """Hinweis für den Kopf der Oberfläche, solange etwas Nötiges fehlt (nur Dinge, die ohne Live-Abfrage feststehen)."""
    return tr(BANNER_TEXT) if settings.backend == "echo" else None


class PeerLog:
    """Merkt sich, von welchen Gegenstellen zuletzt Anfragen an die Domain-Seite kamen (nur Arbeitsspeicher, höchstens fünf).

    So kann die Prüfung die Adresse des Tunnels nennen, die bei ``public_trusted_proxies`` einzutragen ist.
    """

    def __init__(self, size: int = 5) -> None:
        self._size = size
        self._peers: OrderedDict[str, None] = OrderedDict()

    def note(self, peer: str) -> None:
        if not peer or len(peer) > 64:
            return
        self._peers.pop(peer, None)
        self._peers[peer] = None
        while len(self._peers) > self._size:
            self._peers.popitem(last=False)

    def recent(self) -> list[str]:
        return list(reversed(self._peers))


def _item(item_id: str, level: str, status: str, title: str, detail: str = "", steps: Iterable[str] = ()) -> dict:
    return {"id": item_id, "level": level, "status": status, "title": title, "detail": detail, "steps": list(steps)}


def _names(profiles: Iterable[Profile], limit: int = 3) -> str:
    labels = [p.label for p in profiles]
    text = ", ".join(labels[:limit])
    return text + (tr(" und {n} weitere", n=len(labels) - limit) if len(labels) > limit else "")


def static_items(
    settings: Settings,
    profile: Profile,
    *,
    ha_enabled: bool,
    github_enabled: bool,
    ha_level: str,
    github_level: str,
    db_problem: str | None = None,
    pending_users: Iterable[Profile] = (),
    hostname: str = "",
    public_peers: Iterable[str] = (),
) -> list[dict]:
    """Alle Zeilen der Prüfung, soweit sie sich aus der Konfiguration ergeben (ohne Abfrage von Home Assistant und GitHub)."""
    items: list[dict] = []

    # --- Claude (nötig)
    if settings.backend == "echo":
        items.append(_item(
            "claude", "required", "todo", tr("Zugang zu Claude"),
            tr("Der Chat läuft im Testmodus und antwortet nur mit einem Echo. Es wird keine echte KI benutzt."),
            [
                tr("Lege fest, wie abgerechnet wird. Für dich allein genügt ein Claude-Abo: Führe am eigenen Computer mit installiertem Claude Code "
                "`claude setup-token` aus und kopiere das ausgegebene Token. Nutzen mehrere Personen den Chat, erzeuge stattdessen in der "
                "Claude Console (console.anthropic.com) unter „API Keys“ einen API-Schlüssel; dann wird nach Verbrauch abgerechnet."),
                tr(CONFIG_STEP),
                tr("Trage das Abo-Token bei `claude_oauth_token` oder den API-Schlüssel bei `anthropic_api_key` ein."),
                tr(RESTART_STEP),
            ],
        ))
    else:
        via = tr("über den API-Schlüssel (Abrechnung nach Verbrauch)") if settings.anthropic_api_key else tr("über dein Claude-Abo")
        items.append(_item("claude", "required", "ok", tr("Zugang zu Claude"), tr("Eingerichtet {via}. Modell: {model}.", via=via, model=settings.model)))

    # --- Datenbank (nur wenn es ein Problem gibt)
    if db_problem:
        items.append(_item(
            "database", "required", "todo", tr("Datenbank"), db_problem,
            [
                tr("Lies die Meldung oben genau; sie sagt, was beim Start gefunden wurde."),
                tr(CONFIG_STEP),
                tr("Trage bei `restore_snapshot` den Dateinamen eines Schnappschusses ein (Ordner `snapshots` im Datenordner des Add-ons, der neueste steht im Protokoll)."),
                tr(RESTART_STEP) + tr(" Danach `restore_snapshot` wieder leeren."),
            ],
        ))

    # --- Home Assistant
    if ha_enabled:
        items.append(_item("ha", "recommended", "ok", tr("Verbindung zu Home Assistant"), tr("Das Add-on ist mit Home Assistant verbunden.")))
    else:
        items.append(_item(
            "ha", "recommended", "todo", tr("Verbindung zu Home Assistant"),
            tr("Ohne die Verbindung fehlen die Auflösung der Benutzernamen, das Theme und der Zugriff der KI auf dein Zuhause."),
            [
                tr("Die Verbindung stellt Home Assistant dem Add-on automatisch bereit. Starte das Add-on neu."),
                tr("Besteht das Problem weiter, schau im Reiter „Protokoll“ des Add-ons nach Fehlern und prüfe, ob Home Assistant selbst läuft."),
            ],
        ))
    pending = list(pending_users)
    if pending:
        items.append(_item(
            "ha_users", "recommended", "warn", tr("Home-Assistant-Benutzer nicht gefunden"),
            tr("Für {names} gibt es in Home Assistant (noch) keinen Benutzer mit dem eingetragenen Namen.", names=_names(pending)),
            [
                tr(CONFIG_STEP),
                tr("Prüfe bei `ha_user` die Schreibweise (Benutzername oder Personenname aus Einstellungen → Personen)."),
                tr("Oder trage die Benutzer-ID bei `ha_user_id` ein. Wer noch keinen Zugriff hat, sieht die eigene ID auf der Seite „Kein Zugriff“."),
                tr(RESTART_STEP),
            ],
        ))
    if ha_enabled:
        if ha_level == "none":
            items.append(_item(
                "ha_access", "optional", "off", tr("Zugriff der KI auf Home Assistant"),
                tr("Für dich ist der Zugriff der KI auf Home Assistant aus."),
                [
                    tr(CONFIG_STEP),
                    tr("Setze `ha_access_default` auf `read` (nur lesen), `execute` (Geräte bedienen) oder `write` (zusätzlich Automationen ändern). "
                    "Einzelnen Personen gibst du mit `ha_access` im Benutzer-Eintrag eine andere Stufe."),
                    tr(RESTART_STEP),
                ],
            ))
        else:
            detail = tr(ACCESS_TEXT[ha_level]) if ha_level in ACCESS_TEXT else ""
            if settings.ha_limit_to_exposed:
                detail += tr(" Sie sieht nur Entitäten, die in Home Assistant für Assist freigegeben sind (Einstellungen → Sprachassistenten → Entitäten).")
            items.append(_item("ha_access", "optional", "ok", tr("Zugriff der KI auf Home Assistant"), detail.strip()))

    # --- GitHub
    if not github_enabled:
        items.append(_item(
            "github", "optional", "off", "GitHub",
            tr("Nicht verbunden. Nur nötig, wenn die KI mit deinen GitHub-Repositories arbeiten soll."),
            [
                tr("Öffne unten links das Konto-Menü, wähle „Einstellungen“ und dort „GitHub“."),
                tr("Wähle „Mit GitHub verbinden“, gib den angezeigten Code bei GitHub ein und bestätige. Alternativ kannst du ein eigenes Token einfügen."),
                tr("Ob du lesen oder auch ändern darfst, legt der Administrator in der Gruppe „Chat“ mit `github_access_default` oder `github_access` im Benutzer-Eintrag fest: `read` oder `write`."),
            ],
        ))
    elif github_level == "none":
        items.append(_item(
            "github", "optional", "warn", "GitHub",
            tr("GitHub ist verbunden, aber für dich ausgeschaltet (Stufe `none`)."),
            [
                tr(CONFIG_STEP),
                tr("Setze in der Gruppe „Chat“ `github_access_default` auf `read` oder `write`, oder trage im Benutzer-Eintrag `github_access` ein."),
                tr(RESTART_STEP),
            ],
        ))
    else:
        scope = tr(" Es ist dein eigenes GitHub-Konto.")
        mode = tr("lesen und schreiben") if github_level == "write" else tr("nur lesen")
        items.append(_item("github", "optional", "ok", "GitHub", tr("Eingerichtet, du darfst {mode}.", mode=mode) + scope))

    # --- Bilder
    if settings.images_enabled and settings.files_enabled:
        names = [n for n, key in (("OpenAI", settings.openai_api_key), ("Google", settings.google_api_key)) if key]
        if names:
            limit = tr("{n} Bilder je Person und Monat", n=settings.image_limit_month) if settings.image_limit_month else tr("kein Monatslimit")
            items.append(_item("images", "optional", "ok", tr("Bilder erzeugen"), tr("Fotos und Kunstbilder über {names} ({limit}); einfache Grafiken zeichnet die KI kostenlos als SVG.", names=" + ".join(names), limit=limit)))
        else:
            items.append(_item(
                "images", "optional", "off", tr("Bilder erzeugen"),
                tr("Einfache Grafiken (Diagramme, Logos, Pläne) zeichnet die KI schon jetzt als SVG. Für Fotos und Kunstbilder fehlt ein Schlüssel von OpenAI oder Google."),
                [
                    tr("Lege bei OpenAI (platform.openai.com) oder Google (aistudio.google.com) ein API-Konto mit Guthaben an und erzeuge einen API-Schlüssel. Ein ChatGPT- oder Google-Abo reicht dafür nicht."),
                    tr(CONFIG_STEP),
                    tr("Trage den Schlüssel in der Gruppe „Bilder“ bei `openai_api_key` oder `google_api_key` ein. Mit `limit_month` legst du fest, wie viele Bilder jede Person im Monat erzeugen darf, bevor der Chat nachfragt."),
                    tr(RESTART_STEP),
                ],
            ))

    # --- Sprache
    if settings.voice_access_default == "on" or any(p.voice_access == "on" for p in settings.profiles):
        if settings.voice_openai_key:
            stt = "OpenAI"
        elif settings.voice_browser_stt:
            stt = tr("den Browser (kostenlos, über Google oder Apple) oder, falls eingerichtet, Home Assistant")
        else:
            stt = tr("Home Assistant (Sprachassistent)")
        items.append(_item("voice", "optional", "ok", tr("Sprechen mit der KI"), tr("Mikrofon-Knopf im Chat. Spracherkennung über {stt}.", stt=stt)))
    else:
        items.append(_item(
            "voice", "optional", "off", tr("Sprechen mit der KI"),
            tr("Aus. Sprechen per Mikrofon-Knopf im Chat, auch um Geräte zu schalten („Aria, mach das Licht aus“)."),
            [
                tr(CONFIG_STEP),
                tr("Stelle in der Gruppe „Sprechen mit der KI“ den Standard auf `on` oder setze im Benutzer-Eintrag `voice_access` auf `on`. Die Spracherkennung des Browsers ist kostenlos und braucht nichts. Besser sind das Add-on „Whisper“ (kostenlos, läuft auf deinem Home Assistant, Spracherkennung im Sprachassistenten einstellen) oder ein OpenAI-Schlüssel in derselben Gruppe."),
                tr(RESTART_STEP),
            ],
        ))

    # --- Domain-Zugang
    if not settings.public_enabled:
        items.append(_item(
            "domain", "optional", "off", tr("Zugang über eine eigene Adresse"),
            tr("Aus. Nur nötig, wenn du den Chat auch außerhalb der Home-Assistant-App über eine eigene Adresse mit Microsoft-Anmeldung nutzen willst."),
            [
                tr("Richte in Microsoft Entra eine App-Registrierung ein. Weiterleitungs-URI: `https://deine-adresse/auth/callback`."),
                tr("Richte einen Cloudflare Tunnel ein (z. B. mit dem Add-on „Cloudflared“), der auf `http://{host}:8100` zeigt.", host=hostname or tr("Hostname-des-Add-ons")),
                tr(CONFIG_STEP) + tr(" Aktiviere unter „Netzwerk“ den Port 8100."),
                tr("Trage `public_base_url`, `entra_tenant_id`, `entra_client_id` und `entra_client_secret` ein (Beschreibung: Dokumentation, Abschnitt „Domain-Zugang“)."),
                tr(RESTART_STEP),
            ],
        ))
    else:
        target = " " + tr("Der Tunnel muss auf `http://{host}:8100` zeigen.", host=hostname) if hostname else ""
        items.append(_item(
            "domain", "optional", "ok", tr("Zugang über eine eigene Adresse"),
            tr("Eingerichtet unter {url}.", url=settings.public_base_url) + target,
        ))
        if not settings.public_trusted_proxies:
            seen = list(public_peers)
            if seen:
                find = tr("Zuletzt kamen die Anfragen an die Domain-Seite von: {peers}. Trage diese Adresse bei `public_trusted_proxies` ein.", peers=", ".join(seen))
            else:
                find = (
                    tr("Rufe die Anmeldeseite einmal über deine Adresse auf und öffne diese Prüfung danach erneut. Dann steht hier die Adresse, "
                    "von der die Anfragen des Tunnels kommen. Trage sie bei `public_trusted_proxies` ein.")
                )
            items.append(_item(
                "domain_proxies", "recommended", "warn", tr("Anmeldeversuche werden nicht je Besucher gezählt"),
                tr("Hinter einem Tunnel kommen alle Besucher von derselben Adresse. Ohne `public_trusted_proxies` teilen sie sich eine gemeinsame Begrenzung: "
                "Wenige falsche Versuche sperren die Anmeldung dann für alle."),
                [tr(CONFIG_STEP), find, tr(RESTART_STEP)],
            ))

    # --- Benachrichtigungen
    if profile.notify_service:
        items.append(_item(
            "notify", "optional", "ok", tr("Benachrichtigungen aufs Handy"),
            tr("Eingerichtet für dich: {service}.", service=profile.notify_service),
        ))
    else:
        items.append(_item(
            "notify", "optional", "off", tr("Benachrichtigungen aufs Handy"),
            tr("Für dich nicht eingerichtet. Damit meldet sich die KI auf deinem Handy, wenn eine längere Antwort oder eine geplante Aufgabe fertig ist."),
            [
                tr("Installiere die Home-Assistant-Companion-App auf dem Handy und melde dich an."),
                tr("Suche in Home Assistant unter Entwicklerwerkzeuge → Aktionen nach „notify.mobile_app“; dein Gerät steht dort, z. B. `notify.mobile_app_pixel`."),
                tr(CONFIG_STEP),
                tr("Trage den Dienst im Benutzer-Eintrag bei `notify_service` ein."),
                tr(RESTART_STEP),
            ],
        ))

    # --- Erinnerungen an Ablaufdaten
    expiring: list[tuple[str, bool]] = []
    if settings.claude_oauth_token and not settings.anthropic_api_key:
        expiring.append(("claude_token_expires", settings.claude_token_expires is not None))
    if settings.public_enabled:
        expiring.append(("entra_secret_expires", settings.entra_secret_expires is not None))
    if expiring:
        missing = [name for name, present in expiring if not present]
        if missing:
            items.append(_item(
                "expiry", "optional", "off", tr("Erinnerung an Ablaufdaten"),
                tr("Zugangsdaten laufen ab. Mit dem Ablaufdatum erinnert dich der Chat 30 Tage vorher."),
                [
                    tr(CONFIG_STEP),
                    tr("Trage das Datum im Format JJJJ-MM-TT ein: ") + " und ".join(f"`{name}`" for name in missing)
                    + tr(". Das Abo-Token läuft ein Jahr nach `claude setup-token` ab, das Entra-Secret nach der Laufzeit, die du beim Anlegen gewählt hast."),
                    tr(RESTART_STEP),
                ],
            ))
        else:
            items.append(_item("expiry", "optional", "ok", tr("Erinnerung an Ablaufdaten"), tr("Die Ablaufdaten sind eingetragen.")))

    items.sort(key=lambda i: LEVEL_ORDER[i["level"]])
    return items


def _find(items: list[dict], item_id: str) -> dict | None:
    return next((i for i in items if i["id"] == item_id), None)


def _service_exists(services: object, name: str) -> bool:
    domain, _, service = name.partition(".")
    return isinstance(services, dict) and service in (services.get(domain) or {})


async def _check_ha(items: list[dict], ha: HaApi, profile: Profile) -> None:
    ha_item = _find(items, "ha")
    if ha_item is None or ha_item["status"] != "ok":
        return
    try:
        config = await ha.call({"type": "get_config"}, timeout=6)
    except HaApiError as exc:
        ha_item.update(
            status="warn",
            detail=tr("Die Verbindung ist eingerichtet, Home Assistant antwortet aber nicht ({error}).", error=exc),
            steps=[tr("Prüfe, ob Home Assistant gerade startet oder neu geladen wird, und öffne diese Prüfung gleich noch einmal."), tr("Bleibt es so, starte das Add-on neu.")],
        )
        return
    if isinstance(config, dict):
        name, version = str(config.get("location_name") or "")[:60], str(config.get("version") or "")[:20]
        ha_item["detail"] = tr("Verbunden") + (tr(" mit „{name}“", name=name) if name else "") + (tr(" (Home Assistant {version}).", version=version) if version else ".")
    notify = _find(items, "notify")
    if notify is not None and notify["status"] == "ok" and profile.notify_service:
        try:
            services = await ha.call({"type": "get_services"}, timeout=8)
        except HaApiError:
            return
        if not _service_exists(services, profile.notify_service):
            notify.update(
                status="warn",
                detail=tr("Der Dienst {service} ist in Home Assistant nicht vorhanden.", service=profile.notify_service),
                steps=[
                    tr("Suche in Home Assistant unter Entwicklerwerkzeuge → Aktionen nach „notify.mobile_app“ und kopiere den Namen deines Geräts."),
                    tr("Prüfe, ob die Companion-App auf dem Handy angemeldet ist (der Dienst verschwindet, wenn das Gerät entfernt wurde)."),
                    tr(CONFIG_STEP),
                    tr("Korrigiere `notify_service` im Benutzer-Eintrag."),
                    tr(RESTART_STEP),
                ],
            )


async def _check_github(items: list[dict], github: GithubApi) -> None:
    item = _find(items, "github")
    if item is None or item["status"] not in ("ok", "warn") or not github.enabled:
        return
    try:
        async with asyncio.timeout(12):
            user = await github.request("GET", "/user")
    except GithubError as exc:
        if exc.status == 401:
            item.update(
                status="todo",
                detail=tr("GitHub lehnt deinen Zugang ab. Er wurde widerrufen oder ist abgelaufen."),
                steps=[tr("Öffne die Einstellungen, wähle „GitHub“ und verbinde dich neu.")],
            )
        else:
            item["detail"] += tr(" (Das Token konnte gerade nicht geprüft werden: {error})", error=str(exc)[:80])
        return
    except TimeoutError:
        item["detail"] += tr(" (Das Token konnte gerade nicht geprüft werden: keine Antwort von GitHub.)")
        return
    login = re.sub(r"[^\w-]", "", str(user.get("login") or ""))[:40] if isinstance(user, dict) else ""
    if login:
        item["detail"] += tr(" Verbunden als {login}; der Zugang ist gültig.", login=login)


async def _check_voice(items: list[dict], ha: HaApi | None, settings: Settings) -> None:
    """Sprechen mit der KI: sagt, welche Spracherkennung und Stimme wirklich benutzt werden, und warnt, wenn keine bleibt."""
    item = _find(items, "voice")
    if item is None or item["status"] != "ok":
        return
    engines = {"stt": False, "tts": False, "stt_down": False, "tts_down": False}
    if ha is not None:
        try:
            engines = await ha.pipeline_engines()
        except Exception:  # noqa: BLE001 - die Prüfung darf nie an der Abfrage scheitern
            return
    has_key = bool(settings.voice_openai_key)
    stt_down = bool(engines.get("stt_down")) and not has_key  # eingetragen, aber der Dienst läuft nicht
    tts_down = bool(engines.get("tts_down")) and not has_key and settings.voice_output == "service"
    whisper_steps = [tr("Starte in Home Assistant unter Einstellungen → Apps das Add-on „Whisper“ (oder installiere es neu) und prüfe unter Einstellungen → Sprachassistenten, dass bei Sprache-zu-Text „faster-whisper“ steht.")]
    piper_steps = [tr("Starte in Home Assistant unter Einstellungen → Apps das Add-on „Piper“ (oder installiere es neu) und prüfe unter Einstellungen → Sprachassistenten, dass bei Text-zu-Sprache „piper“ steht. Oder stelle `voice.output` auf `device`.")]
    if has_key:
        stt = "OpenAI"
    elif engines["stt"]:
        stt = tr("Home Assistant (Sprachassistent)")
    elif settings.voice_browser_stt:
        stt = tr("den Browser (kostenlos, über Google oder Apple)")
    elif stt_down:
        item.update(
            status="warn",
            detail=tr("Im Sprachassistenten ist eine Spracherkennung eingetragen, sie ist aber nicht verfügbar (Add-on „Whisper“ gestoppt oder entfernt), und weder ein OpenAI-Schlüssel noch der Browser-Rückfall sind eingerichtet."),
            steps=whisper_steps,
        )
        return
    else:
        item.update(
            status="warn",
            detail=tr("Das Sprechen ist erlaubt, aber es gibt keine Spracherkennung: Der bevorzugte Sprachassistent in Home Assistant hat keine, und weder ein OpenAI-Schlüssel noch der Browser-Rückfall sind eingerichtet."),
            steps=[
                tr("Installiere in Home Assistant unter Einstellungen → Apps das Add-on „Whisper“ (kostenlos) und stelle dort die Sprache auf `de`."),
                tr("Binde es unter Einstellungen → Geräte & Dienste mit „Wyoming-Protokoll“ ein und wähle im bevorzugten Sprachassistenten bei Sprache-zu-Text „faster-whisper“."),
                tr("Oder schalte in der Add-on-Konfiguration in der Gruppe „Sprechen mit der KI“ den Browser-Rückfall ein (`browser_stt`) oder trage einen OpenAI-Schlüssel ein."),
            ],
        )
        return
    if settings.voice_output != "service":
        voice = tr("die Stimme des Geräts")
    elif has_key:
        voice = "OpenAI"
    elif engines["tts"]:
        voice = tr("Home Assistant (Sprachassistent)")
    elif engines.get("tts_down"):
        voice = tr("die Stimme des Geräts")
    else:
        voice = tr("die Stimme des Geräts (der Sprachassistent hat keine Sprachausgabe)")
    detail = tr("Mikrofon-Knopf im Chat. Spracherkennung über {stt}. Stimme: {voice}.", stt=stt, voice=voice)
    warnings, steps = [], []
    if stt_down and not engines["stt"]:
        warnings.append(tr("Im Sprachassistenten ist eine Spracherkennung eingetragen, sie ist aber nicht verfügbar (Add-on „Whisper“ gestoppt oder entfernt)."))
        steps += whisper_steps
    if tts_down:
        warnings.append(tr("Die Sprachausgabe im Sprachassistenten ist nicht verfügbar (Add-on „Piper“ gestoppt oder entfernt); es spricht das Gerät."))
        steps += piper_steps
    if warnings:
        item.update(status="warn", detail=detail + " " + " ".join(warnings), steps=steps)
    else:
        item["detail"] = detail


async def run_live(items: list[dict], ha: HaApi | None, github: GithubApi | None, profile: Profile, settings: Settings | None = None) -> list[dict]:
    """Ergänzt die Zeilen um Antworten von Home Assistant und GitHub (je höchstens ein paar Sekunden, Fehler werden zu Hinweisen)."""
    jobs = []
    if ha is not None:
        jobs.append(_check_ha(items, ha, profile))
    if github is not None:
        jobs.append(_check_github(items, github))
    if settings is not None:
        jobs.append(_check_voice(items, ha, settings))
    await asyncio.gather(*jobs, return_exceptions=True)
    for item in items:
        if item["status"] in ("todo", "warn") and not item["steps"]:
            item["steps"] = [tr(CONFIG_STEP)]
    return items


def open_count(items: Iterable[dict]) -> int:
    """Anzahl der Zeilen, die Aufmerksamkeit brauchen (nötig und offen, oder mit Warnung)."""
    return sum(1 for i in items if i["status"] in ("todo", "warn"))
