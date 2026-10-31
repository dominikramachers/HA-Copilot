"""Aufnahmen mit dem DORALAB-Theme (ha_config/themes/doralab.yaml) statt dem Standard-Theme von Home Assistant.

Setzt das Theme über den Dienst frontend.set_theme für die Dauer der Aufnahme und stellt danach den Standard wieder her.
"""
import json, os, sys, urllib.request
exec(open(os.path.join(os.path.dirname(__file__), "capture_ha.py")).read().split("with sync_playwright() as p:")[0])

def access_token():
    """Der gespeicherte Zugriffstoken läuft nach 30 Minuten ab: mit dem Aktualisierungstoken einen frischen holen."""
    data = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": tok["refresh_token"], "client_id": HA + "/"}).encode()
    return json.load(urllib.request.urlopen(urllib.request.Request(HA + "/auth/token", data=data)))["access_token"]

def theme(name):
    body = {"name": name} if name else {"name": "default"}
    r = urllib.request.Request(HA + "/api/services/frontend/set_theme", method="POST", data=json.dumps(body).encode(),
                               headers={"Authorization": "Bearer " + access_token(), "Content-Type": "application/json"})
    urllib.request.urlopen(r).read()

theme("DORALAB")
try:
    with sync_playwright() as p:
        b = p.chromium.launch()
        for scheme in ("light", "dark"):
            suffix = "" if scheme == "light" else "-dunkel"
            c = ctx(b, 1440, 860, scheme); pg = c.new_page()
            pg.goto(HA + "/ha-copilot-panel"); pg.wait_for_timeout(5000)
            fr = pg.frame_locator("iframe")
            fr.locator(".project-row", has_text="Haus").first.click(); pg.wait_for_timeout(400)
            fr.locator(".row.chat-item", has_text="Lichter").first.click(); pg.mouse.move(1000, 600); pg.wait_for_timeout(1500)
            pg.screenshot(path=f"{OUT}/ha-copilot-doralab{suffix}.png")
            c.close()
        b.close()
finally:
    theme(None)
print("ok")
