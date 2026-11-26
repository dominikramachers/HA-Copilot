"""Bilder zu den Funktionen ab 0.60.4 bis 0.67.0: Modell „Auto“, Aktionszeile, Notiz im Projektkontext, Dateifenster mit
Tabellenvorschau, Mermaid-Diagramm, Rückfrage beim Skill, Seite „Plugins“, Übersicht „Alle Personen“.

Braucht die frisch gestartete Demo-App als Administrator (``DEMO_ADMIN=1 python demo_addon.py``, Port 8099).
Aufruf: ``python capture_067.py docs/screenshots``.
"""
import sys
from playwright.sync_api import sync_playwright

OUT = sys.argv[1]
APP = "http://127.0.0.1:8099/"
ME = {"X-Remote-User-Id": "0123456789abcdef0123456789abcdef"}


def context(b, w=1280, h=800, mobile=False):
    kw = dict(viewport={"width": w, "height": h}, color_scheme="light", locale="de-DE", timezone_id="Europe/Berlin", extra_http_headers=ME)
    if mobile:
        kw.update(device_scale_factor=2, is_mobile=True, has_touch=True)
    return b.new_context(**kw)


def calm(pg):
    for _ in range(3):
        if pg.locator("#sheet-scrim.show").count():
            pg.keyboard.press("Escape"); pg.wait_for_timeout(300)


def start(c):
    pg = c.new_page(); pg.goto(APP); pg.wait_for_selector("#input"); pg.wait_for_timeout(900); calm(pg)
    return pg


def send(pg, text):
    for _ in range(120):
        if not pg.locator("#input").evaluate("e => e.readOnly"):
            break
        pg.wait_for_timeout(500)
    pg.locator("#input").fill(text); pg.keyboard.press("Enter")


def idle(pg):
    pg.wait_for_timeout(700)
    for _ in range(120):
        if not pg.locator("#input").evaluate("e => e.readOnly") and not pg.locator(".ask-card").count():
            break
        pg.wait_for_timeout(500)
    pg.wait_for_timeout(800)


def new_project_chat(pg, project="Haus"):
    """Neuen Chat im Projekt anfangen (Projektansicht, dort das Eingabefeld)."""
    pg.locator(".project-row", has_text=project).first.click(); pg.wait_for_timeout(900)


with sync_playwright() as p:
    b = p.chromium.launch()

    # --- Modell „Auto“ im Handy-Menü (Erklärung nennt die drei Modelle)
    c = context(b, 390, 844, mobile=True); pg = start(c)
    pg.click("#tools"); pg.wait_for_timeout(900)
    pg.screenshot(path=f"{OUT}/modell-auto.png")
    c.close()

    # --- Aktionszeile und Notiz im Projektkontext, aufgeklappt, dann die Notiz selbst
    c = context(b, 1280, 860); pg = start(c)
    new_project_chat(pg)
    send(pg, "Sieh dir bitte beide Server an und starte hängende Dienste neu."); idle(pg)
    pg.mouse.move(1200, 820)
    pg.screenshot(path=f"{OUT}/aktionen-kontext.png")
    pg.locator(".act-log summary").last.click(); pg.wait_for_timeout(600); pg.mouse.move(1200, 820)
    pg.screenshot(path=f"{OUT}/aktionen-offen.png")
    pg.locator(".ctx-card").last.click(); pg.wait_for_timeout(1300); pg.mouse.move(640, 840)
    pg.screenshot(path=f"{OUT}/kontext-notiz.png")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(500)

    # --- Dateifenster mit Tabellenvorschau
    send(pg, "Mach mir eine Tabelle mit dem Stromverbrauch des ersten Halbjahrs."); idle(pg)
    pg.locator(".out-open").last.click(); pg.wait_for_timeout(2500); pg.mouse.move(10, 840)
    pg.screenshot(path=f"{OUT}/dateifenster-tabelle.png")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(500)
    c.close()

    # --- Mermaid-Diagramm im Seitenfenster
    c = context(b, 1440, 860); pg = start(c)
    send(pg, "Zeichne den Ablauf an der Haustür als Diagramm."); idle(pg)
    pg.wait_for_timeout(2500); pg.mouse.move(10, 840)
    pg.screenshot(path=f"{OUT}/mermaid.png")
    c.close()

    # --- Rückfrage beim Skill (mit Vorschau der Anleitung)
    c = context(b, 1280, 860); pg = start(c)
    send(pg, "Mach daraus ein Skill für den Wochenbericht.")
    pg.wait_for_selector(".ask-card", timeout=20000); pg.wait_for_timeout(900); pg.mouse.move(10, 840)
    pg.screenshot(path=f"{OUT}/rueckfrage-skill.png")
    pg.locator(".ask-card button", has_text="Ablehnen").click(); pg.wait_for_timeout(800)
    c.close()

    # --- Seite „Plugins“
    c = context(b, 1280, 800); pg = start(c)
    pg.click("#nav-skills"); pg.wait_for_timeout(1500); pg.mouse.move(10, 790)
    pg.screenshot(path=f"{OUT}/plugins.png")
    c.close()

    # --- Einstellungen → Nutzung (Administrator: „Alle Personen“ mit Status)
    c = context(b, 1280, 1000); pg = start(c)
    pg.evaluate("openSettings('usage')"); pg.wait_for_timeout(1800)
    box = pg.locator("h4", has_text="Alle Personen").first
    if box.count():
        box.scroll_into_view_if_needed(); pg.wait_for_timeout(500)
    pg.mouse.move(10, 990)
    pg.screenshot(path=f"{OUT}/nutzung-personen.png")
    c.close()

    b.close()
