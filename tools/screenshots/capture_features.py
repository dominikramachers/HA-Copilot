import json, os, sys, urllib.parse, urllib.request
exec(open(os.path.join(os.path.dirname(__file__), "capture_ha.py")).read().split("with sync_playwright() as p:")[0])
H = {"X-Remote-User-Id": DEMO_ID, "X-Requested-With": "ki-chat", "Content-Type": "application/json"}
def api(method, path, body=None):
    r = urllib.request.Request(APP + path, method=method, headers=H, data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(r) as f:
        t = f.read(); return json.loads(t) if t else None
for s in api("GET", "/api/schedules"): api("DELETE", f"/api/schedules/{s['id']}")
api("POST", "/api/schedules", {"name": "Morgenüberblick", "prompt": "Fasse jeden Morgen zusammen, was im Haus offen oder auffällig ist (Fenster, Türen, Licht).", "freq": "daily", "at": "07:30", "notify": "chat"})
api("POST", "/api/schedules", {"name": "Wochenbericht Strom", "prompt": "Fasse den Stromverbrauch der Woche zusammen und nenne Auffälligkeiten.", "freq": "weekly", "at": "18:00", "days": "4", "notify": "chat"})
api("POST", "/api/schedules", {"name": "Erinnerung Filterwechsel", "prompt": "Erinnere mich an den Filterwechsel der Lüftung.", "freq": "monthly", "at": "09:00", "days": "1", "notify": "chat", "enabled": False})

def account_item(fr, text):
    fr.locator("#account").click(); pg_wait(400)
    fr.locator("button:visible", has_text=text).first.click(); pg_wait(1200)

with sync_playwright() as p:
    b = p.chromium.launch()
    c = ctx(b, 1440, 860, "light"); pg = c.new_page()
    pg_wait = pg.wait_for_timeout
    pg.goto(HA + "/ha-copilot-panel"); pg.wait_for_timeout(5000)
    fr = pg.frame_locator("iframe")
    # Einrichtungsprüfung
    pg.set_viewport_size({"width": 1440, "height": 1040}); pg.wait_for_timeout(600)
    account_item(fr, "Einrichtungsprüfung")
    pg.screenshot(path=f"{OUT}/einrichtungspruefung.png")
    pg.set_viewport_size({"width": 1440, "height": 860}); pg.wait_for_timeout(400)
    fr.locator("#sheet-ok").click(); pg.wait_for_timeout(400)
    # Gedächtnis
    account_item(fr, "Gedächtnis")
    pg.screenshot(path=f"{OUT}/gedaechtnis.png")
    fr.locator("#sheet-ok").click(); pg.wait_for_timeout(400)
    # Suche
    fr.locator("#nav-search").click(); pg.wait_for_timeout(500)
    pg.keyboard.type("licht", delay=60); pg.wait_for_timeout(1200)
    pg.screenshot(path=f"{OUT}/suche.png")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(500)
    # Geplant
    fr.locator("#nav-schedules").click(); pg.wait_for_timeout(1200)
    pg.screenshot(path=f"{OUT}/geplant.png")
    # Chat-Menü
    pg.goto(HA + "/ha-copilot-panel"); pg.wait_for_timeout(4500)
    fr = pg.frame_locator("iframe")
    fr.locator(".project-row", has_text="Haus").first.click(); pg.wait_for_timeout(300)
    row = fr.locator(".row.chat-item", has_text="rollläden").first if False else fr.locator(".row.chat-item", has_text="Rollläden").first
    row.hover(); row.locator(".more").click(); pg.wait_for_timeout(500)
    pg.screenshot(path=f"{OUT}/menue.png")
    c.close()
    # Handy in Home Assistant
    c = ctx(b, 390, 844, "light", mobile=True); pg = c.new_page()
    pg.goto(HA + "/mein-zuhause"); pg.wait_for_timeout(7000)
    pg.screenshot(path=f"{OUT}/ha-handy-dashboard.png")
    pg.goto(HA + "/ha-copilot-panel"); pg.wait_for_timeout(5000)
    fr = pg.frame_locator("iframe")
    try:
        fr.locator("#menu-composer").click(); pg.wait_for_timeout(500)
        fr.locator(".project-row", has_text="Haus").first.click(); pg.wait_for_timeout(300)
        fr.locator(".row.chat-item", has_text="Lichter").first.click(); pg.wait_for_timeout(1500)
    except Exception as e: print("mobile", e)
    pg.screenshot(path=f"{OUT}/ha-handy-copilot.png")
    c.close(); b.close()
print("ok")
