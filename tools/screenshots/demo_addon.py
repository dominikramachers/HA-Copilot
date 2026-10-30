"""Demo-Add-on für die Doku-Screenshots: echte App, neutrale Beispieldaten, nachgebildete KI (kein Claude-Zugang)."""
import os, sys, tempfile, pathlib
ROOT = os.environ.get("KI_ROOT", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "ki_chat"))
sys.path.insert(0, ROOT); sys.path.insert(0, ROOT + "/tests")
import httpx, uvicorn
from app.config import parse_settings
from app.db import Store
from app.branding import Branding
from app.github_api import GithubApi
from app.main import build_ingress_app
from app.ops import Health
from test_setup import FakeHa

DEMO_ID = "0123456789abcdef0123456789abcdef"
LANG = os.environ.get("KI_LANG", "de")
PORT = int(os.environ.get("KI_PORT", "8099"))

class Ha(FakeHa):
    async def themes(self):
        return None

class Backend:
    async def stream(self, history, message, effort, attachments=None, instructions=None, tools=None, note="", **kw):
        yield "Antwort."

raw = {
    "language": LANG, "backend": "claude", "anthropic_api_key": "sk-ant-platzhalter",
    "github_token": "ghp_platzhalter", "github_access_default": "read", "ha_access_default": "read",
    "public_enabled": False, "app_name": "HA Copilot",
    "profiles": [{"id": "demo", "label": "Demo Nutzer", "ha_user_id": DEMO_ID, "ha_access": "write", "github_access": "read",
                  "notify_service": "notify.mobile_app_handy"}],
}
settings = parse_settings(raw, frozenset({"127.0.0.1"}))
d = pathlib.Path(tempfile.mkdtemp()); brand = pathlib.Path(tempfile.mkdtemp())
store = Store(d / "d.sqlite3"); store.sync_profiles([p.id for p in settings.profiles])
U = "demo"
p = store.create_project(U, "Haus" if LANG == "de" else "House")

c1 = store.create_chat(U, "Welche Lichter sind an?" if LANG == "de" else "Which lights are on?", p["id"])
if LANG == "de":
    store.add_exchange(U, c1["id"], "Welche Lichter sind gerade an?",
        "Aktuell sind **drei Lichter** an:\n\n| Raum | Licht | Helligkeit |\n|---|---|---|\n| Wohnzimmer | Deckenlicht | 80 % |\n| Küche | Licht | 100 % |\n| Eingang | Eingangslicht | 60 % |\n\nSoll ich im Wohnzimmer das Licht dimmen oder ausschalten?")
else:
    store.add_exchange(U, c1["id"], "Which lights are on right now?",
        "**Three lights** are on right now:\n\n| Room | Light | Brightness |\n|---|---|---|\n| Living room | Ceiling light | 80 % |\n| Kitchen | Light | 100 % |\n| Entrance | Entrance light | 60 % |\n\nShall I dim or turn off the living room light?")
c2 = store.create_chat(U, "Rollläden nach Sonnenstand" if LANG == "de" else "Blinds by sun position", p["id"])
store.add_exchange(U, c2["id"], "Fenster im Wohnzimmer bei Sonne schließen", "Gern, dafür brauchst du eine Automation mit dem Sonnenstand als Auslöser.")
c3 = store.create_chat(U, "Wochenübersicht Strom" if LANG == "de" else "Weekly power summary", None)
store.add_exchange(U, c3["id"], "Fasse den Stromverbrauch der Woche zusammen", "Der Verbrauch lag im Schnitt bei 8,4 kWh pro Tag.")
store.set_chat_unread(U, c3["id"], True)
c4 = store.create_chat(U, "Flurlicht nachts dimmen" if LANG == "de" else "Dim hallway light at night", None)
store.add_exchange(U, c4["id"], "Licht im Flur nachts nur gedimmt" if LANG == "de" else "Hallway light only dimmed at night", "Gern, dafür legen wir eine Automation an." if LANG == "de" else "Sure, let's create an automation for that.")
store.create_chat(U, "Heizplan Wochenende" if LANG == "de" else "Weekend heating plan", None)
store.memory_save("household", "", "Hausregeln" if LANG == "de" else "House rules", "Nachts ab 22 Uhr Licht im Flur nur gedimmt." if LANG == "de" else "After 10 pm hallway lights only dimmed.", U)
store.memory_save("person", U, "Vorlieben" if LANG == "de" else "Preferences", "Antworten kurz und mit Tabellen." if LANG == "de" else "Short answers, tables welcome.", U)

def gh(request):
    if request.url.path == "/user":
        return httpx.Response(200, json={"login": "demo-konto"}, headers={"x-oauth-scopes": ""})
    return httpx.Response(404, json={"message": "Not Found"})
github = GithubApi("ghp_platzhalter", transport=httpx.MockTransport(gh))
ha = Ha({"location_name": "Zuhause", "version": "2026.10.1"}, {"notify": {"mobile_app_handy": {}}})
app = build_ingress_app(settings, store, Backend(), health=Health(settings), ha=ha, github=github, branding=Branding(brand, settings, None))
uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
