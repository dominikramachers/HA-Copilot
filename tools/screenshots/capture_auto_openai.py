"""Bild zu 0.67.0: Auto gibt eine Textanfrage an ChatGPT, der Hinweis steht über der Antwort.

Braucht die frisch gestartete Demo-App mit ChatGPT (``DEMO_OPENAI=1 python demo_addon.py``, Port 8099).
Aufruf: ``python capture_auto_openai.py docs/screenshots``.
"""
import sys
from playwright.sync_api import sync_playwright

OUT = sys.argv[1]
APP = "http://127.0.0.1:8099/"
ME = {"X-Remote-User-Id": "0123456789abcdef0123456789abcdef"}

with sync_playwright() as p:
    b = p.chromium.launch()
    c = b.new_context(viewport={"width": 1280, "height": 760}, color_scheme="light", locale="de-DE", timezone_id="Europe/Berlin", extra_http_headers=ME)
    pg = c.new_page(); pg.goto(APP); pg.wait_for_selector("#input"); pg.wait_for_timeout(900)
    for _ in range(3):
        if pg.locator("#sheet-scrim.show").count():
            pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    pg.locator("#input").fill("Schreib mir einen kurzen Geburtstagsgruß für Oma"); pg.keyboard.press("Enter")
    pg.wait_for_selector(".model-note:not([hidden])"); pg.wait_for_timeout(2500)
    pg.screenshot(path=f"{OUT}/auto-openai.png")
    b.close()
