"""Legt in der Demo-Instanz das Platzhalter-Dashboard „Zuhause“ an, ordnet die Seitenleiste und setzt Demo-Zustände.

Aufruf: python ha_dashboard.py ha_token.json
"""
import asyncio, json, sys
import aiohttp
tok = json.load(open(sys.argv[1]))["access_token"]
BASE = "http://127.0.0.1:8123"

def tile(e, name=None, **kw):
    c = {"type": "tile", "entity": e}
    if name: c["name"] = name
    c.update(kw); return c
def heading(t, icon=None):
    c = {"type": "heading", "heading": t, "heading_style": "title"}
    if icon: c["icon"] = icon
    return c

cfg = {"title": "Zuhause", "views": [{
  "type": "sections", "title": "Zuhause", "path": "uebersicht", "max_columns": 4,
  "sections": [
    {"type": "grid", "cards": [heading("Wohnzimmer", "mdi:sofa"),
        tile("light.living_room_rgbww_lights", "Deckenlicht", features=[{"type": "light-brightness"}]),
        tile("cover.living_room_window", "Fenster", features=[{"type": "cover-open-close"}]),
        tile("media_player.living_room", "Musik"),
        tile("fan.living_room_fan", "Ventilator")]},
    {"type": "grid", "cards": [heading("Küche", "mdi:countertop"),
        tile("light.kitchen_lights", "Licht", features=[{"type": "light-brightness"}]),
        tile("cover.kitchen_window", "Fenster"),
        tile("lock.kitchen_door", "Küchentür"),
        tile("switch.decorative_lights", "Lichterkette")]},
    {"type": "grid", "cards": [heading("Klima", "mdi:thermometer"),
        {"type": "thermostat", "entity": "climate.heatpump", "name": "Heizung"},
        tile("sensor.outside_temperature", "Außen"),
        tile("sensor.outside_humidity", "Luftfeuchte")]},
    {"type": "grid", "cards": [heading("Haus", "mdi:home-outline"),
        tile("lock.front_door", "Haustür"),
        tile("cover.garage_door", "Garagentor"),
        tile("light.entrance_color_white_lights", "Eingang"),
        tile("binary_sensor.movement_backyard", "Bewegung Garten"),
        {"type": "weather-forecast", "entity": "weather.demo_weather_south", "show_current": True, "show_forecast": False, "name": "Wetter"}]},
  ]}]}

STATES = [  # Demo-Zustände, damit Dashboard und Beispiel-Chat zusammenpassen
    ("light", "turn_on", {"entity_id": "light.living_room_rgbww_lights", "brightness_pct": 80}),
    ("light", "turn_on", {"entity_id": "light.kitchen_lights", "brightness_pct": 100}),
    ("light", "turn_on", {"entity_id": "light.entrance_color_white_lights", "brightness_pct": 60}),
    ("light", "turn_off", {"entity_id": ["light.ceiling_lights", "light.office_rgbw_lights"]}),
    ("climate", "set_temperature", {"entity_id": "climate.heatpump", "temperature": 21}),
]

async def main():
    async with aiohttp.ClientSession() as s:
        for domain, service, data in STATES:
            await s.post(f"{BASE}/api/services/{domain}/{service}", json=data, headers={"Authorization": "Bearer " + tok})
        ws = await s.ws_connect(BASE + "/api/websocket")
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": tok}); await ws.receive_json()
        n = 0
        async def call(**m):
            nonlocal n; n += 1
            await ws.send_json({"id": n, **m}); r = await ws.receive_json()
            print(m["type"], r.get("success"), r.get("error") or ""); return r
        await call(type="lovelace/dashboards/create", url_path="mein-zuhause", mode="storage", title="Zuhause", icon="mdi:home-outline", show_in_sidebar=True, require_admin=False)
        await call(type="lovelace/config/save", url_path="mein-zuhause", config=cfg)
        await call(type="frontend/set_user_data", key="sidebar", value={"hiddenPanels": ["home", "lovelace", "calendar", "map"], "panelOrder": ["mein-zuhause"]})
        await call(type="frontend/set_user_data", key="core", value={"defaultPanel": "mein-zuhause"})

asyncio.run(main())
