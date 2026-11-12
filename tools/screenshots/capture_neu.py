"""Bilder zu den Funktionen ab 0.56.0: Sprechen, Inkognito, Teilen (Fenster, Liste, öffentliche Seite), Deep Research, Projektwissen, Gedächtnis.

Braucht die frisch gestartete Demo-App (``demo_addon.py``, Port 8099, öffentliche Seite auf 8097). Aufruf: ``python capture_neu.py docs/screenshots``.
Die Demo-App danach neu starten: Das Skript legt Freigaben und einen Recherche-Lauf an.
"""
import sys
from playwright.sync_api import sync_playwright

OUT = sys.argv[1]
APP = "http://127.0.0.1:8099/"
ME = {"X-Remote-User-Id": "0123456789abcdef0123456789abcdef"}
SAM = {"X-Remote-User-Id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
FAKE_MIC = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"]


def context(b, headers, w=1280, h=800, scheme="light", mobile=False):
    kw = dict(viewport={"width": w, "height": h}, color_scheme=scheme, locale="de-DE", timezone_id="Europe/Berlin", extra_http_headers=headers,
              permissions=["microphone", "clipboard-read", "clipboard-write"])
    if mobile:
        kw.update(device_scale_factor=2, is_mobile=True, has_touch=True)
    return b.new_context(**kw)


def start(c):
    pg = c.new_page(); pg.goto(APP); pg.wait_for_selector("#input"); pg.wait_for_timeout(900); calm(pg)
    return pg


def calm(pg):
    for _ in range(3):
        if pg.locator("#sheet-scrim.show").count():
            pg.keyboard.press("Escape"); pg.wait_for_timeout(300)


def open_chat(pg, project, chat):
    pg.locator(".project-row", has_text=project).first.click(); pg.wait_for_timeout(300)
    pg.locator(".row.chat-item", has_text=chat).first.click(); pg.mouse.move(900, 620); pg.wait_for_timeout(1200)


def action(pg, text):
    """Aktion aus dem Fenster „Suchen“: Das Suchwort zeigt sie (ohne Suchwort stehen dort nur die ersten drei)."""
    pg.locator("#nav-search").click(); pg.wait_for_timeout(500)
    pg.keyboard.type(text, delay=40); pg.wait_for_timeout(600)
    pg.locator(".srch-item", has_text=text).first.click(); pg.wait_for_timeout(1200)


with sync_playwright() as p:
    b = p.chromium.launch(args=FAKE_MIC)

    # --- Sprechen mit der KI (Fenster mit Partikel-Ring, hört zu)
    c = context(b, ME); pg = start(c)
    pg.click("#voice-btn"); pg.wait_for_timeout(1800)
    pg.screenshot(path=f"{OUT}/sprachchat.png")
    c.close()

    # --- Inkognito-Chat
    c = context(b, ME); pg = start(c)
    pg.click("#incognito-top"); pg.wait_for_timeout(700)
    pg.screenshot(path=f"{OUT}/inkognito.png")
    c.close()

    # --- Chat teilen: Fenster, Link, Liste der anderen Person, öffentliche Seite
    c = context(b, ME, 1280, 900); pg = start(c)
    open_chat(pg, "Haus", "Lichter")
    row = pg.locator(".row.chat-item", has_text="Lichter").first
    row.hover(); row.locator(".more").click(); pg.wait_for_timeout(400)
    pg.locator("button:visible", has_text="Teilen").first.click(); pg.wait_for_selector("#sheet-panel .share-block"); pg.wait_for_timeout(400)
    pg.click("text=In der Instanz teilen"); pg.wait_for_selector("text=Nicht mehr teilen"); pg.wait_for_timeout(300)
    pg.click("text=Link erstellen"); pg.wait_for_selector(".share-url"); pg.evaluate("document.getElementById('toast').hidden = true"); pg.wait_for_timeout(300)  # ohne das Hinweisfenster „Link erstellt“
    url = pg.input_value(".share-url")
    pg.screenshot(path=f"{OUT}/chat-teilen.png")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    c.close()

    c = context(b, {}, 1280, 800); pp = c.new_page(); pp.goto(url); pp.wait_for_selector(".msg.assistant"); pp.wait_for_timeout(600)
    pp.screenshot(path=f"{OUT}/geteilter-chat-oeffentlich.png")
    c.close()

    c = context(b, SAM); pg = start(c)
    pg.wait_for_selector("#nav-shared:not([hidden])"); pg.click("#nav-shared"); pg.wait_for_timeout(1000)
    pg.screenshot(path=f"{OUT}/geteilte-chats.png")
    c.close()

    # --- Deep Research: Menü, Rückfrage, Fortschritt, Bericht
    c = context(b, ME); pg = start(c)
    pg.click("#tools"); pg.wait_for_timeout(500)
    pg.screenshot(path=f"{OUT}/deep-research-menue.png")
    pg.click("text=Deep Research"); pg.wait_for_timeout(700)
    pg.fill("#input", "Lohnt sich eine Wärmepumpe im Altbau?"); pg.click("#send")
    pg.wait_for_selector(".ask-card"); pg.wait_for_timeout(400)
    pg.screenshot(path=f"{OUT}/deep-research-rueckfrage.png")
    pg.click(".ask-actions .primary")
    pg.wait_for_selector(".msg.assistant:not(.pending) h1", timeout=30000); pg.wait_for_timeout(700)
    pg.screenshot(path=f"{OUT}/deep-research-bericht.png")
    c.close()

    # --- Projektwissen (Originale, KI-Notizen) und Gedächtnis (Projekt, Herkunft)
    c = context(b, ME, 1280, 900); pg = start(c)
    pg.locator(".project-row", has_text="Haus").first.hover()
    pg.locator(".project-row", has_text="Haus").first.get_by_label("Aktionen").click(); pg.wait_for_timeout(400)
    pg.locator("button:visible", has_text="Wissen verwalten").first.click(); pg.wait_for_timeout(900)
    pg.screenshot(path=f"{OUT}/projekt-wissen.png")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(400); calm(pg)
    open_chat(pg, "Haus", "Lichter")
    action(pg, "Gedächtnis")
    pg.locator("text=Projekt: Haus").first.scroll_into_view_if_needed(); pg.wait_for_timeout(300)
    pg.locator("#sheet-panel").evaluate("el => { const t = [...el.querySelectorAll('*')].find((e) => e.scrollHeight > e.clientHeight + 20 && getComputedStyle(e).overflowY !== 'visible'); if (t) t.scrollTop += 220; }"); pg.wait_for_timeout(300)
    pg.screenshot(path=f"{OUT}/gedaechtnis-projekt.png")
    c.close()
    b.close()
print("ok")
