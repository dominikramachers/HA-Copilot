"""Aufnahmen zum Design (Einstellungen → Allgemein → Design): die drei Hintergrund-Muster und die weiteren Themes.

Setzt Themes über den Dienst frontend.set_theme für die Dauer der Aufnahme und stellt danach den Standard wieder her.
Braucht zusätzlich die Themes aus docs/themes/ im Ordner themes/ der Test-Instanz (siehe README).
"""
import json, os, sys, urllib.request
from io import BytesIO
exec(open(os.path.join(os.path.dirname(__file__), "capture_ha.py")).read().split("with sync_playwright() as p:")[0])
from PIL import Image

def access_token():
    data = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": tok["refresh_token"], "client_id": HA + "/"}).encode()
    return json.load(urllib.request.urlopen(urllib.request.Request(HA + "/auth/token", data=data)))["access_token"]

def theme(name):
    body = {"name": name} if name else {"name": "default"}
    r = urllib.request.Request(HA + "/api/services/frontend/set_theme", method="POST", data=json.dumps(body).encode(),
                               headers={"Authorization": "Bearer " + access_token(), "Content-Type": "application/json"})
    urllib.request.urlopen(r).read()

def open_chat(pg):
    pg.goto(HA + "/ha-copilot-panel"); pg.wait_for_timeout(5000)
    pg.keyboard.press("Escape"); pg.wait_for_timeout(400)
    fr = pg.frame_locator("iframe")
    fr.locator(".project-row", has_text="Haus").first.click(); pg.wait_for_timeout(400)
    fr.locator(".row.chat-item", has_text="Lichter").first.click(); pg.mouse.move(1000, 640); pg.wait_for_timeout(1500)
    return fr, next(f for f in pg.frames if f != pg.main_frame)

def shot(pg):
    return Image.open(BytesIO(pg.screenshot()))

def side_by_side(light, dark, path, width=640):
    # nur der Chatbereich (ohne die Seitenleisten von Home Assistant und HA Copilot), damit das Muster gut zu sehen ist
    light, dark = light.crop((545, 0, 1440, 860)), dark.crop((545, 0, 1440, 860))
    h = round(light.height * width / light.width)
    out = Image.new("RGB", (width * 2 + 8, h), "#888")
    out.paste(light.resize((width, h), Image.LANCZOS), (0, 0)); out.paste(dark.resize((width, h), Image.LANCZOS), (width + 8, 0))
    out.save(path, optimize=True)

THEMES = ["DORALAB", "DORALAB Nordlicht", "DORALAB Dämmerung", "DORALAB Bernstein", "DORALAB Smaragd"]
try:
    with sync_playwright() as p:
        b = p.chromium.launch()
        # 1) Muster mit dem Standard-Theme DORALAB, hell und dunkel
        theme("DORALAB")
        shots = {}
        for scheme in ("light", "dark"):
            c = ctx(b, 1440, 860, scheme); pg = c.new_page()
            fr, frame = open_chat(pg)
            for design in ("dots", "hex", "plus"):
                frame.evaluate(f"window.kiDesign.set('{design}')"); pg.wait_for_timeout(300)
                shots[(design, scheme)] = shot(pg)
            if scheme == "light":
                frame.evaluate("window.kiDesign.set('dots')")
                pg.mouse.move(5, 5)
                fr.locator("#account").click(); pg.wait_for_timeout(300)
                fr.get_by_text("Einstellungen", exact=True).first.click(); pg.wait_for_timeout(900)
                full = shot(pg)
                full.crop((340, 60, 1356, 540)).save(f"{OUT}/design-einstellung.png", optimize=True)
            c.close()
        for design, name in (("dots", "punktraster"), ("hex", "mikro-wabe"), ("plus", "plus-raster")):
            side_by_side(shots[(design, "light")], shots[(design, "dark")], f"{OUT}/design-{name}.png")
        # 2) Weitere Themes: Standard-Muster, Reihe hell und Reihe dunkel
        tiles = {}
        for name in THEMES[1:]:
            theme(name)
            for scheme in ("light", "dark"):
                c = ctx(b, 1440, 860, scheme); pg = c.new_page()
                open_chat(pg)
                tiles[(name, scheme)] = shot(pg)
                c.close()
        w = 480; h = round(860 * w / 1440)
        sheet = Image.new("RGB", (w * 4 + 12, h * 2 + 4), "#888")
        for col, name in enumerate(THEMES[1:]):
            for row, scheme in enumerate(("light", "dark")):
                sheet.paste(tiles[(name, scheme)].resize((w, h), Image.LANCZOS), (col * (w + 4), row * (h + 4)))
        sheet.save(f"{OUT}/themes-weitere.png", optimize=True)
        b.close()
finally:
    theme(None)
print("ok")
