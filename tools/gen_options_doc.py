"""Erzeugt docs/einstellungen.md aus config.yaml und translations/de.yaml.

Aufruf:  python tools/gen_options_doc.py          schreibt die Seite neu
         python tools/gen_options_doc.py --check  prüft nur, ob sie aktuell ist (Exit-Code 1 sonst)
"""
import re, sys, yaml
from pathlib import Path
# Ergänzungen für Optionen, deren Beschreibung in translations/de.yaml leer ist
EXTRA = {
    "entra_tenant_id": "GUID aus der Entra-App-Registrierung (Übersicht, „Verzeichnis-ID (Mandant)“).",
    "entra_client_id": "GUID aus der Entra-App-Registrierung (Übersicht, „Anwendungs-ID (Client)“).",
    "entra_client_secret": "Wert des Clientschlüssels (Zertifikate & Geheimnisse). Läuft ab: Datum bei `entra_secret_expires` eintragen.",
}

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "docs" / "einstellungen.md"


def render(root: Path = ROOT) -> str:
    cfg = yaml.safe_load((root / "copilot/config.yaml").read_text(encoding="utf-8"))
    tr = yaml.safe_load((root / "copilot/translations/de.yaml").read_text(encoding="utf-8"))["configuration"]
    opts, schema = cfg["options"], cfg["schema"]

    GROUPS = [
     ("Benutzer", "Wer die App nutzen darf. Ausführlich in [Benutzer und Rechte](benutzer.md).", ["profiles", "all_ha_users", "ha_users_excluded"]),
     ("Claude (Antworten)", "Zugang zu Claude und Modell. Ausführlich in [Installation](installation.md#4-zugang-zu-claude).", ["anthropic_api_key", "claude_oauth_token", "claude_token_expires", "model"]),
     ("Zugriff auf Home Assistant", "Was die KI in Home Assistant sehen und tun darf.", ["ha_access_default", "ha_limit_to_exposed"]),
     ("Funktionen", "Gedächtnis, geplante Aufgaben und Dateien.", ["memory_enabled", "schedules_enabled", "files_enabled"]),
     ("GitHub", "Optional: die KI arbeitet mit deinen Repositories. Jede Person verbindet ihr eigenes GitHub in den Einstellungen; hier steht nur, wer lesen oder schreiben darf.", ["github_access_default"]),
     ("Konnektoren", "Optional: die KI nutzt Dienste außerhalb von Home Assistant über MCP-Server (Microsoft 365, Google Workspace, Zabbix …). Ausführlich in der [Dokumentation](../copilot/DOCS.md#konnektoren-ab-0410).", ["connector_access_default"]),
     ("Bilder", "Die KI erzeugt Bilder von selbst: SVG kostenlos, Fotos und Kunst über OpenAI oder Google. Ausführlich in der [Dokumentation](../copilot/DOCS.md#bilder-ab-0280).", ["openai_api_key", "google_api_key", "image_provider", "image_limit_month"]),
     ("Sprechen mit der KI", "Optional: mit der KI sprechen (Mikrofon-Knopf im Chat). Ausführlich in der [Dokumentation](../copilot/DOCS.md#sprechen-mit-der-ki-ab-0520).", ["voice"]),
     ("Zugang über eine eigene Domain", "Optional; der Zugang ist an, sobald `public_base_url` und eine Anmeldung eingetragen sind. Ausführlich in [Domain-Zugang](domain-zugang.md).", ["public_base_url", "ha_url", "entra_tenant_id", "entra_client_id", "entra_client_secret", "entra_secret_expires", "session_days", "public_trusted_proxies"]),
     ("Aussehen, Name und Sprache der Oberfläche", "Alles optional. Ausführlich in der [Dokumentation](../copilot/DOCS.md#personalisierung-name-logo-texte-farben).", ["app_name", "language", "login_text", "login_placeholder", "logo_tile", "follow_ha_theme", "theme_name"]),
     ("Daten und Sicherung", "Normalerweise leer oder aus. Siehe [Betrieb](betrieb.md).", ["restore_snapshot", "export_database"]),
    ]
    listed = [k for _, _, ks in GROUPS for k in ks]
    # Die Reihenfolge der Konfiguration in Home Assistant folgt den Gruppen (Schema, Optionen und Übersetzungen gleich)
    assert listed == list(schema) == list(opts) == list(tr), "Reihenfolge in config.yaml, translations/de.yaml und tools/gen_options_doc.py muss übereinstimmen"

    def typ(spec):
        s = str(spec); opt = s.endswith("?"); s = s.rstrip("?")
        m = re.match(r"list\((.*)\)", s)
        if m: return " \\| ".join(f"`{v}`" for v in m.group(1).split("|"))
        if s.startswith("match("):
            if "{6}" in s: return "Hex-Farbe, z. B. `#175CD3`"
            if "{32}" in s: return "32 Hex-Zeichen"
            return "a–z, 0–9, `-`, `_` (2 bis 32 Zeichen)"
        if s.startswith("int("): a, b = s[4:-1].split(","); return f"Zahl {a} bis {b}"
        return {"str": "Text", "bool": "an/aus", "password": "Text (geheim)", "int": "Zahl"}.get(s, s)

    def default(k):
        if k not in opts: return "leer"
        v = opts[k]
        if v is True: return "an"
        if v is False: return "aus"
        if v in ("", None, []): return "leer"
        return f"`{v}`"

    def esc(t): return t.replace("|", "\\|").replace("\n", " ")

    out = ["# Alle Einstellungen", "",
     "Diese Seite listet **jede** Option des Add-ons mit Standardwert und Bedeutung. Du findest sie in Home Assistant unter **Einstellungen → Apps → HA Copilot → Konfiguration**. Mit ⋮ → „In YAML bearbeiten“ kannst du alles als Text sehen, kopieren und einfügen. Nach jeder Änderung speichern und das Add-on **neu starten**.", "",
     f"Pflichtfelder (immer vorhanden, mit Standardwert voreingestellt): {', '.join('`'+k+'`' for k in schema if not str(schema[k]).endswith('?'))}. Alle anderen Optionen sind optional; fehlt eine, gilt der Standardwert. Bestehende Einstellungen werden bei Updates nie überschrieben.", ""]
    for title, intro, keys in GROUPS:
        out += [f"## {title}", "", intro, "", "| Option | Werte | Standard | Bedeutung |", "|---|---|---|---|"]
        for k in keys:
            t = tr.get(k, {})
            name, desc = t.get("name", k), t.get("description", "")
            spec = schema[k]
            if k == "profiles":
                val = "Liste (Felder siehe unten)"
            elif k == "voice":
                val = "Gruppe (Felder siehe unten)"
            elif isinstance(spec, list):
                val = "Liste"
            else:
                val = typ(spec)
            d = "ein Eintrag „Administrator“" if k == "profiles" else "Standardwerte" if k == "voice" else default(k)
            desc = desc.strip() or EXTRA.get(k, "")
            out.append(f"| `{k}` | {val} | {d} | **{esc(name.rstrip('.'))}.** {esc(desc)} |".replace("**. ", "** ").rstrip().replace("|  |", "| |"))
        if "profiles" in keys:
            out += ["", "### Felder je Benutzer (`profiles`)", "", "| Feld | Werte | Bedeutung |", "|---|---|---|"]
            for f, spec in schema["profiles"][0].items():
                t = tr["profiles"]["fields"][f]
                out.append(f"| `{f}` | {typ(spec)} | **{esc(t['name'])}.** {esc(t['description'])} |")
        if "voice" in keys:
            out += ["", "### Felder der Gruppe `voice`", "", "In Home Assistant als eingeklappte Gruppe „Sprechen mit der KI“. In der Konfigurationsdatei steht es so: `voice:` mit den Feldern darunter.", "", "| Feld | Werte | Standard | Bedeutung |", "|---|---|---|---|"]
            for f, spec in schema["voice"].items():
                t = tr["voice"]["fields"][f]
                v = opts["voice"].get(f)
                dv = "leer" if v in ("", None) else "an" if v is True else "aus" if v is False else f"`{v}`"
                out.append(f"| `voice.{f}` | {typ(spec)} | {dv} | **{esc(t['name'])}.** {esc(t['description'])} |")
        out.append("")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    text = render()
    if "--check" in sys.argv:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != text:
            sys.exit("docs/einstellungen.md ist nicht aktuell: python tools/gen_options_doc.py ausführen")
        print("ok")
    else:
        TARGET.write_text(text, encoding="utf-8")
        print("geschrieben:", TARGET)
