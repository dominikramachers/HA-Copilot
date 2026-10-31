import json, sys, urllib.parse
from playwright.sync_api import sync_playwright
import os
SP = os.environ.get("SHOT_WORK", ".")  # Arbeitsordner mit ha_token.json
OUT = sys.argv[1]
APP = "http://127.0.0.1:8099"
HA = "http://127.0.0.1:8123"
DEMO_ID = "0123456789abcdef0123456789abcdef"
tok = json.load(open(f"{SP}/ha_token.json"))
tokens = {"access_token": tok["access_token"], "token_type": "Bearer", "expires_in": 1800, "hassUrl": HA, "clientId": HA + "/",
          "expires": 4102444800000, "refresh_token": tok["refresh_token"]}
INIT = "localStorage.setItem('hassTokens', %s);" % json.dumps(json.dumps(tokens))

def ingress(route):
    u = urllib.parse.urlparse(route.request.url)
    rest = u.path.split("/api/hassio_ingress/demo", 1)[1] or "/"
    url = APP + rest + (("?" + u.query) if u.query else "")
    h = {**route.request.headers, "x-remote-user-id": DEMO_ID}
    h.pop("host", None)
    resp = route.fetch(url=url, headers=h)
    route.fulfill(response=resp)

def ctx(b, w, h, scheme, mobile=False):
    c = b.new_context(viewport={"width": w, "height": h}, color_scheme=scheme, locale="de-DE", timezone_id="Europe/Berlin",
                      device_scale_factor=2 if mobile else 1, is_mobile=mobile, has_touch=mobile)
    c.add_init_script(INIT)
    c.route("**/api/hassio_ingress/demo/**", ingress)
    return c

with sync_playwright() as p:
    b = p.chromium.launch()
    for scheme in ("light", "dark"):
        suffix = "" if scheme == "light" else "-dunkel"
        c = ctx(b, 1440, 860, scheme)
        pg = c.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(HA + "/mein-zuhause"); pg.wait_for_timeout(7000); print(pg.url)
        pg.screenshot(path=f"{OUT}/ha-seitenleiste-dashboard{suffix}.png")
        pg.goto(HA + "/ha-copilot-panel"); pg.wait_for_timeout(5000)
        fr = pg.frame_locator("iframe")
        try:
            fr.locator(".project-row", has_text="Haus").first.click(); pg.wait_for_timeout(400); fr.locator(".row.chat-item", has_text="Lichter").first.click(); pg.mouse.move(1000, 400); pg.wait_for_timeout(1500)
        except Exception as e:
            print("click chat failed", e)
        pg.screenshot(path=f"{OUT}/ha-copilot-im-panel{suffix}.png")
        print(scheme, "errors", errs[:3])
        c.close()
    b.close()
