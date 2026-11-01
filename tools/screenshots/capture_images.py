"""Screenshots zur Bildfunktion (0.28.0): Platzhalter, zwei Fassungen, Bildvorschau, Rückfrage beim Limit.

Braucht das Demo-Add-on auf Port 8099 in frischem Zustand (das Demo-Limit steht auf 2 Bilder je Monat).
Aufruf: python capture_images.py <Zielordner>
"""
import os, pathlib, sys, tempfile
from playwright.sync_api import sync_playwright
OUT = sys.argv[1]
DEMO_ID = "0123456789abcdef0123456789abcdef"; H = {"X-Remote-User-Id": DEMO_ID}
FLAG = pathlib.Path(tempfile.gettempdir()) / "demo_img_delay"

def send(pg, text):
    for _ in range(120):
        if not pg.locator("#input").evaluate("e => e.readOnly"): break
        pg.wait_for_timeout(500)
    pg.locator("#input").fill(text); pg.keyboard.press("Enter")

def idle(pg):
    pg.wait_for_timeout(600)
    for _ in range(120):
        if not pg.locator("#input").evaluate("e => e.readOnly") and pg.locator(".img-card.pending").count() == 0: break
        pg.wait_for_timeout(500)
    pg.wait_for_timeout(700)

with sync_playwright() as p:
    b = p.chromium.launch()
    c = b.new_context(viewport={"width": 1280, "height": 1040}, color_scheme="light", locale="de-DE", timezone_id="Europe/Berlin", extra_http_headers=H)
    pg = c.new_page(); pg.goto("http://127.0.0.1:8099/"); pg.wait_for_timeout(900)
    FLAG.write_text("7")
    send(pg, "Male mir ein gemütliches Wohnzimmer bei Sonnenuntergang")
    pg.wait_for_timeout(2600); pg.mouse.move(1000, 700)
    pg.screenshot(path=f"{OUT}/bild-erzeugen.png", clip={"x": 300, "y": 56, "width": 980, "height": 470})
    FLAG.unlink(); idle(pg)
    send(pg, "Mach die Wand grün"); idle(pg)
    pg.set_viewport_size({"width": 1280, "height": 1310}); pg.wait_for_timeout(600); pg.mouse.move(1000, 1200)
    pg.evaluate("document.querySelector('#thread').scrollTop = 0")
    pg.screenshot(path=f"{OUT}/bild-fassungen.png", clip={"x": 300, "y": 56, "width": 980, "height": 1060})
    pg.set_viewport_size({"width": 1280, "height": 800}); pg.wait_for_timeout(400)
    pg.locator("button.img-card").last.click(); pg.wait_for_timeout(900)
    pg.screenshot(path=f"{OUT}/bild-vorschau.png")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(400)
    send(pg, "Male noch ein Bild von einem Schlafzimmer"); pg.wait_for_timeout(2500); pg.mouse.move(1000, 300)
    pg.screenshot(path=f"{OUT}/bild-rueckfrage.png", clip={"x": 300, "y": 520, "width": 980, "height": 280})
    pg.locator(".ask-card button", has_text="Ablehnen").click(); pg.wait_for_timeout(800)
    c.close()
    b.close()
