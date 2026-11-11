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
    "entra_client_secret": "Wert des Clientschlüssels (Zertifikate & Geheimnisse). Läuft ab: Datum bei `domain.entra_secret_expires` eintragen.",
}

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "docs" / "einstellungen.md"


def render(root: Path = ROOT) -> str:
    cfg = yaml.safe_load((root / "copilot/config.yaml").read_text(encoding="utf-8"))
    tr = yaml.safe_load((root / "copilot/translations/de.yaml").read_text(encoding="utf-8"))["configuration"]
    opts, schema = cfg["options"], cfg["schema"]

    GROUPS = [
     ("users", "Wer die App nutzen darf. Ausführlich in [Benutzer und Rechte](benutzer.md)."),
     ("chat", "Zugang zu Claude ([Installation](installation.md#4-zugang-zu-claude)), Modell, Gedächtnis, geplante Aufgaben, Dateien, Zugriff auf Home Assistant und die Standards für GitHub und Konnektoren. GitHub und Konnektoren sind ausführlich in der [Dokumentation](../copilot/DOCS.md#konnektoren-ab-0410) beschrieben."),
     ("images", "Die KI erzeugt Bilder von selbst: SVG kostenlos, Fotos und Kunst über OpenAI oder Google. Ausführlich in der [Dokumentation](../copilot/DOCS.md#bilder-ab-0280)."),
     ("voice", "Optional: mit der KI sprechen (Mikrofon-Knopf im Chat). Ausführlich in der [Dokumentation](../copilot/DOCS.md#sprechen-mit-der-ki-ab-0520)."),
     ("domain", "Optional; der Zugang ist an, sobald `domain.public_base_url` und eine Anmeldung eingetragen sind. Ausführlich in [Domain-Zugang](domain-zugang.md)."),
     ("look", "Alles optional. Ausführlich in der [Dokumentation](../copilot/DOCS.md#personalisierung-name-logo-texte-farben)."),
     ("global", "Normalerweise leer oder aus. Siehe [Betrieb](betrieb.md)."),
    ]
    # Die Reihenfolge der Konfiguration in Home Assistant folgt den Gruppen (Schema, Optionen und Übersetzungen gleich)
    assert [g for g, _ in GROUPS] == list(schema) == list(opts) == list(tr), "Reihenfolge in config.yaml, translations/de.yaml und tools/gen_options_doc.py muss übereinstimmen"

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

    def default(v):
        if v is True: return "an"
        if v is False: return "aus"
        if v in ("", None, []): return "leer"
        return f"`{v}`"

    def esc(t): return t.replace("|", "\\|").replace("\n", " ")

    out = ["# Alle Einstellungen", "",
     "Diese Seite listet **jede** Option des Add-ons mit Standardwert und Bedeutung. Du findest sie in Home Assistant unter **Einstellungen → Apps → HA Copilot → Konfiguration**. Die Optionen stehen in eingeklappten Gruppen (ab 0.54.0); der Name einer Option beginnt mit der Gruppe, z. B. `domain.public_base_url`. Mit ⋮ → „In YAML bearbeiten“ siehst du alles als Text, so wie es unten bei jeder Gruppe steht. Nach jeder Änderung speichern und das Add-on **neu starten**.", "",
     "Alle Optionen sind optional; fehlt eine, gilt der Standardwert. Bestehende Einstellungen werden bei Updates nie überschrieben. Beim Wechsel auf die Gruppen (0.54.0) übernimmt das Add-on die alten Werte, bis du sie in den Gruppen einträgst.", ""]
    for key, intro in GROUPS:
        t = tr[key]
        out += [f"## {t['name']} (`{key}`)", "", intro, "", f"In der Konfigurationsdatei: `{key}:` mit den Feldern darunter.", "", "| Option | Werte | Standard | Bedeutung |", "|---|---|---|---|"]
        for f, spec in schema[key].items():
            ft = t["fields"][f]
            name, desc = ft.get("name", f), (ft.get("description") or "").strip() or EXTRA.get(f, "")
            if f == "profiles":
                val, d = "Liste (Felder siehe unten)", "ein Eintrag „Administrator“"
            elif isinstance(spec, list):
                val, d = "Liste", default(opts[key].get(f))
            else:
                val, d = typ(spec), default(opts[key].get(f))
            out.append(f"| `{key}.{f}` | {val} | {d} | **{esc(name.rstrip('.'))}.** {esc(desc)} |".replace("**. ", "** "))
        if key == "users":
            out += ["", "### Felder je Benutzer (`users.profiles`)", "", "| Feld | Werte | Bedeutung |", "|---|---|---|"]
            for f, spec in schema["users"]["profiles"][0].items():
                ft = t["fields"]["profiles"]["fields"][f]
                out.append(f"| `{f}` | {typ(spec)} | **{esc(ft['name'])}.** {esc(ft['description'])} |")
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
