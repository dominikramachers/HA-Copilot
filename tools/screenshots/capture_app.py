import sys
from playwright.sync_api import sync_playwright
OUT = sys.argv[1]
DEMO_ID = "0123456789abcdef0123456789abcdef"; H = {"X-Remote-User-Id": DEMO_ID}
def open_chat(pg, project, chat):
    pg.locator(".project-row", has_text=project).first.click(); pg.wait_for_timeout(300)
    pg.locator(".row.chat-item", has_text=chat).first.click(); pg.mouse.move(900, 620); pg.wait_for_timeout(1200)
with sync_playwright() as p:
    b = p.chromium.launch()
    for scheme, name in (("light", "chat-hell"), ("dark", "chat-dunkel")):
        c = b.new_context(viewport={"width": 1280, "height": 800}, color_scheme=scheme, locale="de-DE", timezone_id="Europe/Berlin", extra_http_headers=H)
        pg = c.new_page(); pg.goto("http://127.0.0.1:8099/"); pg.wait_for_timeout(900)
        open_chat(pg, "Haus", "Lichter"); pg.screenshot(path=f"{OUT}/{name}.png")
        if scheme == "light":
            # Eigene Nachricht: Zeitpunkt, Bearbeiten und Kopieren beim Darüberfahren, dann der Editor
            clip = {"x": 300, "y": 56, "width": 980, "height": 300}
            # Die Demo-Daten sind gerade erst angelegt; für das Bild so tun, als wäre die Frage vor 33 Minuten gesendet worden.
            pg.evaluate("document.querySelector('.msg-group.user-group').dataset.at = new Date(Date.now() - 33 * 60000).toISOString()")
            pg.locator(".msg.user").first.hover(); pg.wait_for_timeout(500)
            pg.screenshot(path=f"{OUT}/nachricht-zeit.png", clip=clip)
            pg.locator(".msg-edit-btn").first.click(); pg.wait_for_timeout(400)
            pg.screenshot(path=f"{OUT}/nachricht-bearbeiten.png", clip=clip)
            pg.locator(".msg-edit .pill.ghost").click(); pg.wait_for_timeout(300)
            # Antwort: Kopieren und „Als Datei“ (bei der letzten Antwort dauerhaft), der Zeitpunkt nur beim Darüberfahren
            pg.mouse.move(5, 5); pg.wait_for_timeout(200)
            pg.evaluate("document.querySelector('.msg.assistant').dataset.at = new Date(Date.now() - 31 * 60000).toISOString()")
            answer = pg.locator(".msg.assistant").first
            answer.hover(); pg.wait_for_timeout(500)
            box = answer.bounding_box()
            pg.screenshot(path=f"{OUT}/antwort-zeit.png", clip={"x": box["x"] - 20, "y": box["y"] + box["height"] - 120, "width": 700, "height": 150})
        c.close()
    c = b.new_context(viewport={"width": 390, "height": 800}, device_scale_factor=2, is_mobile=True, has_touch=True, locale="de-DE", extra_http_headers=H)
    pg = c.new_page(); pg.goto("http://127.0.0.1:8099/"); pg.wait_for_timeout(900)
    pg.click("#menu-composer"); pg.wait_for_timeout(400); open_chat(pg, "Haus", "Lichter"); pg.screenshot(path=f"{OUT}/chat-handy.png"); c.close()
    c = b.new_context(viewport={"width": 1280, "height": 800}, color_scheme="light", locale="en-US", timezone_id="Europe/Berlin", extra_http_headers=H)
    pg = c.new_page(); pg.goto("http://127.0.0.1:8098/"); pg.wait_for_timeout(900)
    open_chat(pg, "House", "lights"); pg.screenshot(path=f"{OUT}/chat-en.png"); c.close()
    b.close()
