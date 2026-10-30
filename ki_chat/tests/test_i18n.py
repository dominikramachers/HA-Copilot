"""Sprache der Oberfläche (Option ``language``): Wörterbücher vollständig, Seiten und Meldungen auf Englisch,
Standard bleibt Deutsch."""
import ast
import copy
import html
import json
import re
import shutil
import subprocess
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import exporter, i18n, schedule
from app.backend import compose_system
from app.config import ConfigError, parse_settings
from app.main import build_ingress_app

from conftest import ADM01, RAW, WRITE, as_user

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
STATIC = APP / "static"
JS_FILES = ("app.js", "login.js", "markdown.js")
HTML_FILES = ("index.html", "login.html")

EN = json.loads((APP / "locales" / "en.json").read_text(encoding="utf-8"))
EN_UI = json.loads((APP / "locales" / "en-ui.json").read_text(encoding="utf-8"))

GERMAN_WORD = re.compile(
    r"[äöüÄÖÜß]|\b(und|oder|der|die|das|nicht|ist|wird|bitte|kein|keine|wurde|für|mit|von|zu|auf|nur|noch|alle|neu|neue|"
    r"neuer|Chat|Datei|Fehler|Einstellungen|Nachricht)\b"
)


# ------------------------------------------------------------------------- Schlüssel einsammeln

_STR = r'''("(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\$]|\\.)*`)'''
_JS_TR = re.compile(r"(?<![\w.$])tr\(\s*" + _STR)
_JS_TRN = re.compile(r"(?<![\w.$])trn\(\s*[^,()]+,\s*" + _STR + r"\s*,\s*" + _STR)
_JS_ANY_STRING = re.compile(r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'|`(?:[^`\\]|\\.)*`')
_JS_TR_CALL = re.compile(
    r"(?<![\w.$])trn?\(\s*(?:[^,()\"'`]+,\s*)?(?:" + _JS_ANY_STRING.pattern + r")(?:\s*,\s*(?:" + _JS_ANY_STRING.pattern + r"))?"
)


def _js_literal(token: str) -> str:
    quote, body = token[0], token[1:-1]
    if quote == '"':
        return json.loads(token)
    body = body.replace("\\" + quote, quote).replace('"', '\\"').replace("\n", "\\n")
    return json.loads('"' + body + '"')


def js_keys() -> set[str]:
    keys: set[str] = set()
    for name in JS_FILES:
        text = (STATIC / name).read_text(encoding="utf-8")
        keys.update(_js_literal(m.group(1)) for m in _JS_TR.finditer(text))
        for m in _JS_TRN.finditer(text):
            keys.update((_js_literal(m.group(1)), _js_literal(m.group(2))))
    return keys


def _string_values(node: ast.AST) -> list[str]:
    """Texte einer Konstante; bei Wörterbüchern nur die Werte (die Schlüssel sind Kennungen, keine Texte)."""
    if isinstance(node, ast.Dict):
        return [s for value in node.values for s in _string_values(value)]
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return [s for item in node.elts for s in _string_values(item)]
    return [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _module_constants() -> dict[str, list[str]]:
    consts: dict[str, list[str]] = {}
    for path in APP.glob("*.py"):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.Assign):
                targets, value = [t for t in node.targets if isinstance(t, ast.Name)], node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
                targets, value = [node.target], node.value
            else:
                continue
            strings = _string_values(value)
            for target in targets:
                consts.setdefault(target.id, []).extend(strings)
    return consts


def python_keys() -> tuple[set[str], list[str]]:
    """Alle Texte, die im Server an ``tr``/``trn`` gehen. Konstanten (z. B. Wochentage) werden aufgelöst."""
    consts = _module_constants()
    keys: set[str] = set()
    unresolved: list[str] = []
    for path in sorted(APP.glob("*.py")):
        if path.name == "i18n.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("tr", "trn")):
                continue
            for arg in (node.args[:1] if node.func.id == "tr" else node.args[1:3]):
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    keys.add(arg.value)
                    continue
                names = {n.id for n in ast.walk(arg) if isinstance(n, ast.Name) and n.id in consts}
                found = [s for name in names for s in consts[name]]
                if isinstance(arg, ast.IfExp):
                    found += [n.value for n in ast.walk(arg) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
                found = [s for s in found if re.search(r"[A-Za-zÄÖÜäöüß]{2,}", s)]
                if not found:
                    unresolved.append(f"{path.name}:{node.lineno}")
                keys.update(found)
    return keys, unresolved


def html_keys() -> set[str]:
    keys: set[str] = set()
    for name in HTML_FILES:
        page = re.sub(r"<(script|style)\b.*?</\1>", "", (STATIC / name).read_text(encoding="utf-8"), flags=re.S | re.I)
        for m in i18n._TEXT_NODE.finditer(page):
            keys.add(" ".join(m.group(1).split()))
        for m in i18n._ATTR.finditer(page):
            keys.add(html.unescape(m.group(2)))
    return {k for k in keys if re.search(r"[A-Za-zÄÖÜäöüß]", k) and not re.fullmatch(r"__\w+__", k)}


# ------------------------------------------------------------------------- Wörterbücher

def test_every_browser_text_has_an_english_counterpart():
    keys = js_keys()
    assert len(keys) > 300  # der Sammler findet die Texte wirklich
    missing = sorted(k for k in keys if k not in EN_UI)
    assert not missing, f"Fehlende Übersetzungen (en-ui.json): {missing}"


def test_no_german_text_is_left_unwrapped_in_the_browser_code():
    allowed = {'"KI Chat"', '"Chat.md"'}
    problems = []
    for name in JS_FILES + ("theme-init.js", "i18n.js"):
        text = re.sub(r"/\*.*?\*/", "", (STATIC / name).read_text(encoding="utf-8"), flags=re.S)
        wrapped = [(m.start(), m.end()) for m in _JS_TR_CALL.finditer(text)]
        for m in _JS_ANY_STRING.finditer(text):
            token = m.group(0)
            if any(a <= m.start() < b for a, b in wrapped) or token in allowed or "\n" in token or "tr(" in token:
                continue
            line_start = text.rfind("\n", 0, m.start()) + 1
            if re.search(r"(^|\s)//", text[line_start:m.start()]):
                continue
            if GERMAN_WORD.search(token):
                problems.append(f"{name}:{text.count(chr(10), 0, m.start()) + 1} {token[:70]}")
    assert not problems, "Deutsche Texte ohne tr(): " + "; ".join(problems)


def test_every_server_text_has_an_english_counterpart():
    keys, unresolved = python_keys()
    assert not unresolved, f"tr() mit nicht auflösbarem Text: {unresolved}"
    assert len(keys) > 250
    missing = sorted(k for k in keys if k not in EN and k not in EN_UI)
    assert not missing, f"Fehlende Übersetzungen (en.json): {missing}"


def test_every_page_text_has_an_english_counterpart():
    missing = sorted(k for k in html_keys() if k not in EN and k not in EN_UI)
    assert not missing, f"Fehlende Übersetzungen für Seitentexte: {missing}"


def test_dictionaries_hold_no_stale_entries():
    server_keys, _ = python_keys()
    page_keys = html_keys()
    stale_en = sorted(k for k in EN if k not in server_keys and k not in page_keys)
    stale_ui = sorted(k for k in EN_UI if k not in js_keys() and k not in server_keys and k not in page_keys)
    assert not stale_en, f"Nicht benutzte Einträge in en.json: {stale_en}"
    assert not stale_ui, f"Nicht benutzte Einträge in en-ui.json: {stale_ui}"


def test_shared_entries_agree_and_nothing_is_left_untranslated():
    for key in set(EN) & set(EN_UI):
        assert EN[key] == EN_UI[key], key
    for name, dictionary in (("en.json", EN), ("en-ui.json", EN_UI)):
        for key, value in dictionary.items():
            assert value.strip(), f"{name}: leere Übersetzung für {key!r}"
            assert not re.search(r"[äöüÄÖÜß]", value), f"{name}: Umlaut in der Übersetzung von {key!r}"


@pytest.mark.parametrize("name,dictionary,pattern", [("en.json", EN, r"\{(\w+)\}"), ("en-ui.json", EN_UI, r"\{(\d+)\}")])
def test_placeholders_survive_translation(name, dictionary, pattern):
    for key, value in dictionary.items():
        wanted = set(re.findall(pattern, key))
        for form in value.split("||"):
            got = set(re.findall(pattern, form))
            # Einzahl-Formen dürfen den Zähler weglassen; andere Platzhalter müssen übernommen sein
            assert got <= wanted | {"n"} and (wanted - {"n"}) <= got | ({"n"} if "||" in value else set()), (name, key, value)


def test_no_untranslatable_text_is_wrapped():
    keys, _ = python_keys()
    assert not [k for k in keys if re.search(r"\b(SELECT|INSERT|UPDATE|PRAGMA)\b", k)]


# ------------------------------------------------------------------------- Mechanik

def test_default_language_is_german_and_unknown_languages_fall_back():
    assert i18n.language() == "de" and i18n.tr("Nicht gefunden") == "Nicht gefunden"
    i18n.set_language("fr")
    assert i18n.language() == "de"
    assert i18n.locale() == "de-DE"
    i18n.set_language("en")
    assert i18n.locale() == "en-GB"


def test_tr_translates_fills_placeholders_and_falls_back_to_german():
    i18n.set_language("en")
    assert i18n.tr("Nicht gefunden") == "Not found"
    assert i18n.tr("Websuche: {query}", query="Wetter") == "Web search: Wetter"
    assert i18n.tr("Ein ganz neuer Satz {x}", x=1) == "Ein ganz neuer Satz 1"  # unbekannt: deutscher Text bleibt
    assert i18n.tr("Höchstens {files} Dateien pro Nachricht.") == "At most {files} files per message."  # nicht angegeben: bleibt stehen


def test_plural_forms_choose_by_the_count(monkeypatch):
    monkeypatch.setitem(i18n._load("en"), "{n} Hund||{n} Hunde", "{n} dog||{n} dogs")
    monkeypatch.setitem(i18n._load("en"), "{n} Hund", "{n} dog||{n} dogs")
    i18n.set_language("en")
    assert i18n.tr("{n} Hund", n=1) == "1 dog"
    assert i18n.tr("{n} Hund", n=3) == "3 dogs"
    assert i18n.trn(1, "{n} Hund", "{n} Hunde") == "1 dog"


def test_html_translation_keeps_scripts_placeholders_and_whitespace():
    page = '<html lang="de"><title>Anmelden – __NAME__</title><script>var s = "Nicht gefunden";</script><p>\n  Nachricht\n</p><input placeholder="Nachricht" value="Nachricht">'
    assert i18n.translate_html(page).count("Nachricht") == 3 and 'lang="de"' in i18n.translate_html(page)
    i18n.set_language("en")
    out = i18n.translate_html(page)
    assert 'lang="en"' in out and "<title>Sign in – __NAME__</title>" in out
    assert 'var s = "Nicht gefunden";' in out  # Skripte bleiben unberührt
    assert "<p>\n  Message\n</p>" in out and 'placeholder="Message"' in out and 'value="Nachricht"' in out


def test_browser_translation_function_matches_the_server():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node nicht installiert")
    script = (STATIC / "i18n.js").read_text(encoding="utf-8")
    harness = (
        "global.window = {kiI18n: {lang: 'en', dict: {'Hallo {0}': 'Hello {0}', '{0} Datei': '{0} file', '{0} Dateien': '{0} files',"
        " 'Ein Hund||Hunde': 'one dog||{0} dogs', 'Ein Hund': 'one dog||{0} dogs'}}};\n"
        + script
        + "\nconst r = [tr('Hallo {0}', 'Welt'), trn(1, 'Eine Datei', '{0} Dateien'), trn(3, 'Eine Datei', '{0} Dateien'),"
        " tr('Unbekannt {0}', 5), tr('Hallo {0} {1}', 'a'), kiLocale];\nconsole.log(JSON.stringify(r));"
    )
    out = subprocess.run([node, "-e", harness], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == ["Hello Welt", "Eine Datei", "3 files", "Unbekannt 5", "Hallo a {1}", "en-GB"]


# ------------------------------------------------------------------------- Einstellung

def test_language_option_defaults_to_german_and_is_validated():
    assert parse_settings(RAW, frozenset()).language == "de"
    assert parse_settings({**RAW, "language": "EN"}, frozenset()).language == "en"
    with pytest.raises(ConfigError):
        parse_settings({**RAW, "language": "fr"}, frozenset())


def test_add_on_manifest_offers_the_language_with_german_as_default():
    yaml = pytest.importorskip("yaml")
    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    assert config["options"]["language"] == "de"
    assert config["schema"]["language"] == "list(de|en)?"
    for lang in ("de", "en"):
        translation = yaml.safe_load((ROOT / "translations" / f"{lang}.yaml").read_text(encoding="utf-8"))
        assert translation["configuration"]["language"]["name"]


# ------------------------------------------------------------------------- Englische Oberfläche

def make_client(store, backend, language="en", **extra):
    settings = parse_settings({**copy.deepcopy(RAW), "language": language, **extra}, frozenset({"testclient"}))
    return TestClient(build_ingress_app(settings, store, backend))


def test_german_pages_stay_german_by_default(store, backend):
    client = make_client(store, backend, language="de")
    page = client.get("/", headers=as_user(ADM01)).text
    assert '<html lang="de"' in page and "Konto und Einstellungen" in page
    lang = client.get("/branding/lang.js").text
    assert '"lang":"de"' in lang and '"dict":{}' in lang


def test_english_index_page_and_script(store, backend):
    client = make_client(store, backend)
    page = client.get("/", headers=as_user(ADM01)).text
    assert '<html lang="en"' in page and "Account and settings" in page and "Drop files here" in page
    for german in ("Konto und Einstellungen", "Dateien hier ablegen", "Seitenleiste", "Denkaufwand", "Angemeldet"):
        assert german not in page
    assert "lang.js" in page and "i18n.js" in page
    script = client.get("/branding/lang.js").text
    assert script.startswith("window.kiI18n=") and '"lang":"en"' in script and "Websuche" in script
    assert client.get("/static/i18n.js").status_code == 200


def test_english_denied_page_and_http_errors(store, backend):
    client = make_client(store, backend)
    denied = client.get("/", headers=as_user("00000000000000000000000000000000"))
    assert denied.status_code == 403 and "No access" in denied.text and "Kein Zugriff" not in denied.text
    assert "lang='en'" in denied.text
    r = client.get("/api/chats/gibtsnicht/export", headers=as_user(ADM01))
    assert r.status_code == 404 and r.json()["detail"] == "Not found"


def test_delete_all_chats_confirmation_word_follows_the_language(store, backend):
    en = make_client(store, backend)
    wrong = en.post("/api/data/delete-chats", json={"confirm": "nein"}, headers={**as_user(ADM01), **WRITE})
    assert wrong.status_code == 422 and "DELETE" in wrong.json()["detail"]
    assert en.post("/api/data/delete-chats", json={"confirm": "delete"}, headers={**as_user(ADM01), **WRITE}).status_code == 200
    # das deutsche Wort wird auch in der englischen Oberfläche angenommen (und umgekehrt)
    assert en.post("/api/data/delete-chats", json={"confirm": "LÖSCHEN"}, headers={**as_user(ADM01), **WRITE}).status_code == 200
    de = make_client(store, backend, language="de")
    wrong = de.post("/api/data/delete-chats", json={"confirm": "nein"}, headers={**as_user(ADM01), **WRITE})
    assert wrong.status_code == 422 and "LÖSCHEN" in wrong.json()["detail"]
    assert de.post("/api/data/delete-chats", json={"confirm": "DELETE"}, headers={**as_user(ADM01), **WRITE}).status_code == 200


def test_default_chat_title_is_localised_and_both_defaults_count_as_unnamed(store, backend):
    client = make_client(store, backend)
    chat = client.post("/api/chats", json={}, headers={**as_user(ADM01), **WRITE}).json()
    assert chat["title"] == "New chat"


def test_english_setup_check(store, backend):
    client = make_client(store, backend)
    data = client.get("/api/setup", headers=as_user(ADM01)).json()
    titles = {item["id"]: item["title"] for item in data["items"]}
    assert titles["claude"] == "Access to Claude" and titles["ha"] == "Connection to Home Assistant" and titles["domain"] == "Access through your own address"
    text = json.dumps(data, ensure_ascii=False)
    for german in ("Zugang zu Claude", "Verbindung zu", "Einstellungen → Apps", "Eingerichtet", "Testmodus", "Trage ", "Speichere"):
        assert german not in text
    assert "test mode" in text and "Settings → Apps" in text
    # Namen von Optionen und Befehlen bleiben unverändert
    assert "`claude setup-token`" in text and "`claude_oauth_token`" in text


def test_english_export_names_and_texts(store):
    i18n.set_language("en")
    store.create_chat("adm01", title="Test")
    files = zipfile.ZipFile(BytesIO(exporter.build_zip(store, "adm01", "AXON")))
    names = set(files.namelist())
    assert {"README.txt", "projects.md", "memory.md", "scheduled-tasks.md"} <= names
    assert not names & {"LIESMICH.txt", "projekte.md", "gedaechtnis.md", "geplante-aufgaben.md"}
    readme = files.read("README.txt").decode("utf-8")
    assert "Export of your data from AXON" in readme and "Erstellt" not in readme
    assert files.read("memory.md").decode("utf-8").startswith("#")
    chat = [n for n in names if n.startswith("chats/")]
    assert chat and "exported from AXON" in files.read(chat[0]).decode("utf-8")


def test_english_schedule_descriptions():
    i18n.set_language("en")
    assert schedule.describe("daily", "07:30", "") == "Every day at 07:30"
    assert schedule.describe("weekdays", "07:30", "") == "Monday to Friday at 07:30"
    text = schedule.describe("weekly", "18:00", "0,4")
    assert "Monday" in text and "Friday" in text and "18:00" in text and "Montag" not in text and " und " not in text
    i18n.set_language("de")
    assert schedule.describe("daily", "07:30", "") == "Jeden Tag um 07:30 Uhr"


def test_system_prompt_asks_for_the_chosen_answer_language():
    assert "Antworte standardmäßig auf Deutsch" in compose_system(None)
    i18n.set_language("en")
    prompt = compose_system(None)
    assert "Antworte standardmäßig auf Englisch" in prompt and "auf Deutsch" not in prompt


def test_english_attachment_errors(store, backend):
    i18n.set_language("en")
    from app import attachments
    with pytest.raises(Exception) as caught:
        attachments.read_attachment("x.bin", "application/octet-stream", b"\x00\x01\x02")
    assert "Möglich" not in str(caught.value)


def test_english_login_page_and_manifest(store, backend):
    from test_security import public_client

    i18n.set_language("en")
    client, _ = public_client(store, backend, language="en")
    page = client.get("/login").text
    assert '<html lang="en"' in page
    for german in ("Anmelden", "E-Mail-Adresse", "Mit deinem Konto anmelden", "beispiel.de"):
        assert german not in page, german
    assert "Sign in" in page and "name@example.com" in page
    manifest = client.get("/branding/manifest.webmanifest")
    if manifest.status_code == 200:
        assert manifest.json()["lang"] == "en"


def test_english_error_messages_from_the_backend():
    from app import backend as be

    i18n.set_language("en")
    keys, _ = python_keys()
    for text in ("Das Nutzungslimit ist erreicht. Bitte später erneut versuchen.", "Claude ist gerade nicht erreichbar. Bitte gleich noch einmal versuchen."):
        assert text in keys
        assert re.search(r"[a-z]", i18n.tr(text)) and i18n.tr(text) != text
    assert be is not None
