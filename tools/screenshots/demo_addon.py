"""Demo-Add-on für die Doku-Screenshots: echte App, neutrale Beispieldaten, nachgebildete KI (kein Claude-Zugang)."""
import os, sys, tempfile, pathlib
ROOT = os.environ.get("KI_ROOT", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "copilot"))
sys.path.insert(0, ROOT); sys.path.insert(0, ROOT + "/tests")
import asyncio, base64, io, json, re
import httpx, uvicorn
from app.config import parse_settings
from app.db import Store
from app.branding import Branding
from app.github_api import GithubApi
from app.images import ImageService
from app.main import build_ingress_app
from app.ops import Health
from test_setup import FakeHa

DEMO_ID = "0123456789abcdef0123456789abcdef"
LANG = os.environ.get("KI_LANG", "de")
PORT = int(os.environ.get("KI_PORT", "8099"))

class Ha(FakeHa):
    async def themes(self):
        return None

SVG_PLAN = """<svg viewBox="0 0 640 420" xmlns="http://www.w3.org/2000/svg" font-family="Helvetica, Arial, sans-serif">
<rect width="640" height="420" fill="#f7f8fa"/>
<g fill="#ffffff" stroke="#3b4a5a" stroke-width="4"><rect x="40" y="40" width="360" height="200"/><rect x="400" y="40" width="200" height="130"/><rect x="400" y="170" width="200" height="70"/><rect x="40" y="240" width="560" height="140"/></g>
<g fill="#3b4a5a" font-size="20" text-anchor="middle"><text x="220" y="150">Wohnzimmer</text><text x="500" y="112">Küche</text><text x="500" y="212">Bad</text><text x="320" y="318">Flur und Schlafzimmer</text></g>
<g fill="#2f6fed" opacity=".85"><circle cx="90" cy="90" r="9"/><circle cx="330" cy="90" r="9"/><circle cx="500" cy="70" r="9"/></g>
<text x="40" y="404" font-size="14" fill="#6b7785">Blaue Punkte: Leuchten</text></svg>"""

def scene(wall):
    from PIL import Image, ImageDraw
    w, h = 1536, 1024
    img = Image.new("RGB", (w, h), wall); d = ImageDraw.Draw(img)
    d.rectangle([0, 700, w, h], fill=(150, 110, 78))                      # Boden
    for i in range(0, w, 192): d.line([i, 700, i - 140, h], fill=(131, 95, 66), width=4)
    for y in range(120, 560):                                                # Fenster mit Abendhimmel
        t = (y - 120) / 440; d.line([980, y, 1380, y], fill=(int(250 - 40 * t), int(150 + 20 * t - 90 * t * t), int(70 + 120 * t)))
    d.ellipse([1110, 330, 1250, 470], fill=(255, 214, 120))
    d.polygon([(980, 560), (1100, 470), (1180, 540), (1280, 450), (1380, 560)], fill=(70, 62, 96))
    d.rectangle([980, 120, 1380, 560], outline=(245, 240, 232), width=18); d.line([1180, 120, 1180, 560], fill=(245, 240, 232), width=12)
    d.rounded_rectangle([140, 520, 760, 760], radius=40, fill=(86, 112, 148))   # Sofa
    d.rounded_rectangle([140, 440, 760, 580], radius=40, fill=(104, 134, 176))
    d.rounded_rectangle([120, 520, 200, 770], radius=30, fill=(72, 96, 130)); d.rounded_rectangle([700, 520, 780, 770], radius=30, fill=(72, 96, 130))
    d.rounded_rectangle([280, 540, 400, 620], radius=18, fill=(236, 190, 90))
    d.rectangle([880, 800, 1240, 830], fill=(110, 78, 52)); d.rectangle([900, 830, 920, 930], fill=(110, 78, 52)); d.rectangle([1200, 830, 1220, 930], fill=(110, 78, 52))
    d.rectangle([1440, 300, 1452, 720], fill=(60, 60, 66)); d.polygon([(1400, 300), (1492, 300), (1470, 220), (1422, 220)], fill=(250, 226, 160))
    d.ellipse([60, 690, 140, 770], fill=(190, 98, 62)); 
    for a, b in ((-50, -170), (-10, -190), (30, -160), (60, -120)): d.line([100, 700, 100 + a, 700 + b], fill=(60, 140, 84), width=14)
    buf = io.BytesIO(); img.save(buf, "PNG", optimize=True); return buf.getvalue()

DELAY_FLAG = pathlib.Path(tempfile.gettempdir()) / "demo_img_delay"
async def fake_image_api(request):
    if DELAY_FLAG.exists():
        await asyncio.sleep(float(DELAY_FLAG.read_text() or 0))
    wall = (96, 140, 104) if b"gr\xc3\xbcn" in request.content or b"green" in request.content else (232, 218, 196)
    data = base64.b64encode(scene(wall)).decode()
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": data}}]}}]})

class Backend:
    last_image = None

    async def stream(self, history, message, effort, attachments=None, instructions=None, tools=None, note="", **kw):
        handlers = {t.name: t.handler for t in tools or []}
        low = message.lower()
        de = LANG == "de"
        if "image_svg" in handlers and ("grundriss" in low or "floor plan" in low):
            await handlers["image_svg"]({"svg": SVG_PLAN, "title": "Grundriss Erdgeschoss" if de else "Floor plan ground floor"})
            yield ("Ich habe den Grundriss als SVG gezeichnet, weil das ein einfacher Plan ist und nichts kostet. Die blauen Punkte sind die Leuchten." if de
                   else "I drew the floor plan as an SVG because it is a simple plan and costs nothing. The blue dots are the lights.")
        elif "image_generate" in handlers and ("male" in low or "paint" in low or "ändere" in low or "wand" in low or "wall" in low):
            edit = Backend.last_image if any(k in low for k in ("wand", "wall", "ändere")) else None
            title = ("Schlafzimmer" if "schlafzimmer" in low else "Wohnzimmer bei Sonnenuntergang") if de else "Living room at sunset"
            args = {"prompt": message, "title": title, "format": "landscape"}
            if edit: args["reference"] = edit
            try:
                result = await handlers["image_generate"](args)
            except Exception:
                yield "Alles klar, dann lasse ich das Bild weg." if de else "All right, I will skip the image."
                return
            Backend.last_image = (re.search(r"Bild (\S+\.png) erzeugt", result) or [None, None])[1]
            if edit:
                yield ("Ich habe die Wand grün gemacht. Das war eine Änderung am vorhandenen Bild, deshalb habe ich Google genutzt. Die erste Fassung bleibt erhalten." if de
                       else "I made the wall green. That was an edit of the existing image, so I used Google. The first version is kept.")
            else:
                yield ("Das ist ein Bild mit Licht und Stimmung, deshalb habe ich es mit Google erzeugen lassen und nicht als SVG gezeichnet. Soll ich etwas ändern?" if de
                       else "This image is about light and mood, so I had Google generate it instead of drawing an SVG. Shall I change anything?")
        else:
            yield "Antwort."


raw = {
    "language": LANG, "backend": "claude", "anthropic_api_key": "sk-ant-platzhalter",
    "github_token": "ghp_platzhalter", "github_access_default": "read", "ha_access_default": "read",
    "google_api_key": "AIza-platzhalter", "image_limit_month": 2,
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
app = build_ingress_app(settings, store, Backend(), health=Health(settings), ha=ha, github=github, branding=Branding(brand, settings, None),
                        images=ImageService(settings, httpx.MockTransport(fake_image_api)))
uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
