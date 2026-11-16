"""Texte der Server-Agenten in der Sprache der Person.

Der Agent schreibt **nur Englisch** (Begründung, Vorschau, Rückgängig-Hinweis, Zusammenfassung). Jeder dieser Texte trägt einen
Code und seine Werte (``msgs`` im Plan, siehe ``agent/internal/plan/msg.go``). Der Hub zeigt in der Freigabekarte

* bei Englisch den Text des Agenten unverändert,
* bei Deutsch die Vorlage zum Code (``TEMPLATES``) mit den Werten des Agenten.

Kennt der Hub einen Code nicht (etwa von einem neueren Agenten), bleibt es bei dem englischen Text des Agenten, nie bei einem
halben Satz. Befehle, Pfade und Namen sind keine Texte und bleiben, wie sie sind.

Die Vorlagen stehen hier als eigene Zuordnung und nicht als ``tr()``-Aufrufe: Die englische Seite liefert der Agent selbst, ein
zweites Wörterbuch dafür würde nur auseinanderlaufen.
"""
from __future__ import annotations

import re
from typing import Any

from .i18n import language

MAX_DEPTH = 3
MAX_THEN = 60
_CODE = re.compile(r"^[a-z][a-z0-9_.]{0,47}$")
_PLACEHOLDER = re.compile(r"\{(\w+)\}")

SERVICE_ACTIONS_DE = {
    "start": "starten", "stop": "stoppen", "restart": "neu starten", "reload": "neu laden",
    "enable": "beim Start aktivieren", "disable": "beim Start deaktivieren",
}

TEMPLATES: dict[str, str] = {
    # Dienste
    **{f"svc.summary.{action}": "{unit}: " + text for action, text in SERVICE_ACTIONS_DE.items()},
    "svc.never": "Der Agent selbst und sein Helfer werden nie über die KI verändert.",
    "svc.lockout_stop": "Aussperrgefahr: Anmeldung, Netzwerk oder Systemdienst dürfen nicht gestoppt oder deaktiviert werden.",
    "svc.lockout": "Dieser Dienst kann beim Neustart kurz die Verbindung unterbrechen (Anmeldung, Netzwerk oder Systemdienst).",
    "svc.wide": "Dieser Dienst hat weitreichende Wirkung (Firewall, Container, Zeitplan oder Sicherheit).",
    "svc.single": "Ein einzelner Dienst, jederzeit wieder umkehrbar.",
    "svc.undo_none": "Nicht nötig: der Dienst läuft danach wie zuvor weiter.",
    "svc.preview": "Zustand jetzt: {state}, beim Start: {boot}",
    # Pakete
    "pkg.summary.update": "Paketlisten aktualisieren ({command})",
    "pkg.summary.install": "Installieren: {packages}",
    "pkg.summary.remove": "Entfernen: {packages}",
    "pkg.summary.upgrade_all": "Alle Pakete aktualisieren ({command})",
    "pkg.summary.upgrade": "Aktualisieren: {packages}",
    "pkg.reason.update": "Lädt nur die Paketlisten, installiert nichts.",
    "pkg.reason.install": "Pakete aus den eingerichteten Quellen installieren.",
    "pkg.reason.remove": "Das Entfernen von Paketen kann Dienste und Abhängigkeiten betreffen.",
    "pkg.reason.protected": "{package} gehört zum Grundsystem oder zur Anmeldung und wird nie über die KI entfernt.",
    "pkg.reason.upgrade_all": "Viele Pakete können sich gleichzeitig ändern, auch Dienste werden dabei neu gestartet.",
    "pkg.reason.upgrade": "Nur die genannten Pakete werden auf die neueste Version gebracht.",
    "pkg.reason.would_remove_protected": "Dabei würde auch {package} entfernt (Grundsystem oder Anmeldung).",
    "pkg.reason.also_removes": "Zusätzlich würden Pakete entfernt: {packages}",
    "pkg.undo_none": "Nicht nötig.",
    "pkg.undo_upgrade_all": "Nicht einfach umkehrbar (alte Versionen müssten einzeln neu installiert werden).",
    "pkg.undo_upgrade": "Nicht einfach umkehrbar (die alte Version müsste gezielt neu installiert werden).",
    "pkg.preview.update": "Lädt die Paketlisten neu; es werden keine Pakete verändert.",
    "pkg.preview.sim": "Trockenlauf: {inst} Paket(e) installieren oder aktualisieren, {remv} entfernen.",
    "pkg.preview.installs": "Installieren/Aktualisieren: {packages}",
    "pkg.preview.removes": "Entfernen: {packages}",
    # Freie Befehle
    "run.read": "Lesender Befehl: verändert nichts.",
    "run.destructive": "{program} kann Datenträger, Benutzer oder den Betrieb des Servers zerstören.",
    "run.no_preserve_root": "Schutz des Wurzelverzeichnisses abgeschaltet.",
    "run.dd_device": "dd würde direkt auf einen Datenträger schreiben.",
    "run.dd": "dd schreibt Rohdaten.",
    "run.rm_system": "Löschen eines Systemverzeichnisses.",
    "run.rm_recursive": "Rekursives Löschen.",
    "run.rm": "Löscht Dateien.",
    "run.chmod_system": "Rechte eines Systemverzeichnisses rekursiv ändern.",
    "run.chmod": "Ändert Rechte oder Besitzer.",
    "run.kill_init": "Prozess 1 oder alle Prozesse zu beenden würde den Server stoppen.",
    "run.kill": "Beendet Prozesse.",
    "run.power": "Würde den Server abschalten oder neu starten.",
    "run.lockout": "Aussperrgefahr: dieser Dienst darf nicht gestoppt oder deaktiviert werden.",
    "run.systemctl": "Ändert den Zustand von Diensten.",
    "run.firewall_flush": "Firewall-Regeln würden geleert oder abgeschaltet (Aussperrgefahr).",
    "run.firewall": "Ändert oder liest Firewall-Regeln.",
    "run.shell": "Eine Shell kann beliebig viel tun.",
    "run.sensitive": "Greift auf möglicherweise vertrauliche Dateien zu.",
    "run.ip_write": "Ändert die Netzwerkeinstellungen.",
    "run.journal_write": "Ändert das Journal.",
    "run.pkg_write": "Ändert Pakete oder Container.",
    "run.unknown": "Unbekannter Befehl: er kann Änderungen vornehmen, die sich nicht einstufen lassen.",
    "run.script_deny": "Das Skript enthält Anweisungen, die Daten zerstören, Benutzer oder Anmeldung verändern oder den Server abschalten könnten.",
    "run.script": "Ein Shell-Skript kann beliebig viel tun. Prüfe den Wortlaut genau.",
    "run.root": "Der Befehl läuft als root.",
    "run.summary_script": "Shell-Skript ausführen",
    "run.summary_cmd": "Befehl ausführen: {command}",
    "run.undo_none": "Nicht nötig: der Befehl verändert nichts.",
    "run.undo_manual": "Nicht automatisch umkehrbar.",
    "run.preview_read": "Lesender Befehl; laut Einstufung verändert er nichts.",
    "run.preview": "Der Befehl wird genau so ausgeführt, wie oben gezeigt.",
    # Dateien schreiben
    "file.summary.write": "Datei {path} schreiben",
    "file.summary.create": "Datei {path} anlegen",
    "file.summary.append": "An Datei {path} anhängen",
    "file.denied": "Dieser Pfad gehört zum System, zur Anmeldung, zum Start oder zum Agenten selbst und wird nie über die KI geschrieben.",
    "file.reason_new": "Legt eine neue Datei an.",
    "file.reason": "Ändert eine Datei auf dem Server. Die bisherige Fassung bleibt daneben als Sicherungskopie erhalten.",
    "file.undo": "Die Sicherungskopie {path}.copilot-bak-<Datum> zurückkopieren, die neben der Datei liegt.",
    "file.preview_unreadable": "Der Benutzer des Agenten kann den bisherigen Inhalt von {path} nicht lesen, deshalb gibt es keinen Vergleich. Der neue Text wird so geschrieben, wie er ist.",
    "file.preview_same": "Die Datei hat schon genau diesen Inhalt; es würde sich nichts ändern.",
    "file.preview_diff": "Änderungen an {path}: {added} Zeile(n) neu, {removed} entfernt.",
    "file.preview_new": "Neue Datei {path} mit {lines} Zeile(n):",
}

MORE_DE = " … und {more} weitere"


def clean_msg(data: Any, depth: int = 0) -> dict[str, Any] | None:
    """Eine Nachricht des Agenten streng prüfen (fremder Inhalt): Code in fester Form, Werte als gekürzte Texte, begrenzte Tiefe."""
    if not isinstance(data, dict) or depth >= MAX_DEPTH:
        return None
    text = data.get("text")
    if not isinstance(text, str):
        return None
    out: dict[str, Any] = {"text": _block(text, 6000)}
    code = data.get("code")
    if isinstance(code, str) and _CODE.match(code):
        out["code"] = code
    params = data.get("params")
    if isinstance(params, dict):
        out["params"] = {str(k)[:40]: _block(v, 1200) for k, v in list(params.items())[:12] if isinstance(k, str) and isinstance(v, str)}
    then = data.get("then")
    if isinstance(then, list):
        items = [clean_msg(item, depth + 1) for item in then[:MAX_THEN]]
        out["then"] = [item for item in items if item is not None]
    return out


_CTRL_BLOCK = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _block(value: Any, limit: int) -> str:
    return _CTRL_BLOCK.sub(" ", value.replace("\r\n", "\n")).strip()[:limit] if isinstance(value, str) else ""


def clean_msgs(data: Any) -> dict[str, dict[str, Any]]:
    """``msgs`` eines Plans: nur die vier bekannten Felder."""
    out: dict[str, dict[str, Any]] = {}
    if isinstance(data, dict):
        for key in ("reason", "summary", "undo", "preview"):
            msg = clean_msg(data.get(key))
            if msg is not None:
                out[key] = msg
    return out


def _known(msg: dict[str, Any]) -> bool:
    code = msg.get("code")
    if code is not None and code not in TEMPLATES:
        return False
    return all(_known(item) for item in msg.get("then", []))


# Agenten bis 0.61.0 schickten den Befehl noch im Text und ohne Angabe (sie kannten nur apt)
_DEFAULT_PARAMS = {"pkg.summary.update": {"command": "apt-get update"}, "pkg.summary.upgrade_all": {"command": "apt-get upgrade"}}


def _head(msg: dict[str, Any]) -> str:
    code = msg.get("code")
    if code is None:
        return msg["text"]
    params = {**_DEFAULT_PARAMS.get(code, {}), **msg.get("params", {})}
    text = _PLACEHOLDER.sub(lambda m: params.get(m.group(1), m.group(0)), TEMPLATES[code])
    if params.get("more"):
        text += _PLACEHOLDER.sub(lambda m: params.get(m.group(1), m.group(0)), MORE_DE)
    return text


def _render(msg: dict[str, Any], sep: str) -> str:
    parts = [_head(msg)] + [_render(item, sep) for item in msg.get("then", [])]
    return sep.join(part for part in parts if part)


def localize(plan: dict[str, Any], field: str, *, sep: str = "\n") -> str:
    """Ein Textfeld des Plans (``reason``, ``summary``, ``undo``, ``preview``) in der Sprache der Person.

    Englisch: der Text des Agenten. Deutsch: die Vorlage zum Code; ist irgendein Code unbekannt, bleibt der englische Text.
    """
    english = plan.get(field, "")
    msg = (plan.get("msgs") or {}).get(field)
    if language() == "en" or not msg or not _known(msg):
        return english
    return _render(msg, sep) or english
