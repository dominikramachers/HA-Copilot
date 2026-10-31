import sys
from playwright.sync_api import sync_playwright
OUT = sys.argv[1]
DEMO_ID = "0123456789abcdef0123456789abcdef"; H = {"X-Remote-User-Id": DEMO_ID}
def open_chat(pg, project, chat):
    pg.locator(".project-row", has_text=project).first.click(); pg.wait_for_timeout(300)
    pg.locator(".row.chat-item", has_text=chat).first.click(); pg.mouse.move(900, 400); pg.wait_for_timeout(1200)
with sync_playwright() as p:
    b = p.chromium.launch()
    for scheme, name in (("light", "chat-hell"), ("dark", "chat-dunkel")):
        c = b.new_context(viewport={"width": 1280, "height": 800}, color_scheme=scheme, locale="de-DE", timezone_id="Europe/Berlin", extra_http_headers=H)
        pg = c.new_page(); pg.goto("http://127.0.0.1:8099/"); pg.wait_for_timeout(900)
        open_chat(pg, "Haus", "Lichter"); pg.screenshot(path=f"{OUT}/{name}.png"); c.close()
    c = b.new_context(viewport={"width": 390, "height": 800}, device_scale_factor=2, is_mobile=True, has_touch=True, locale="de-DE", extra_http_headers=H)
    pg = c.new_page(); pg.goto("http://127.0.0.1:8099/"); pg.wait_for_timeout(900)
    pg.click("#menu-composer"); pg.wait_for_timeout(400); open_chat(pg, "Haus", "Lichter"); pg.screenshot(path=f"{OUT}/chat-handy.png"); c.close()
    c = b.new_context(viewport={"width": 1280, "height": 800}, color_scheme="light", locale="en-US", timezone_id="Europe/Berlin", extra_http_headers=H)
    pg = c.new_page(); pg.goto("http://127.0.0.1:8098/"); pg.wait_for_timeout(900)
    open_chat(pg, "House", "lights"); pg.screenshot(path=f"{OUT}/chat-en.png"); c.close()
    b.close()
