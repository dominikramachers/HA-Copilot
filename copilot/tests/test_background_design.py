"""Hintergrund-Muster der Oberfläche (Einstellungen → Allgemein → Design): Wahl je Person, Standard, Prüfung, Auslieferung der Muster."""
import re
from pathlib import Path

from tests.conftest import ADM01, DORA, as_user

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"


def test_default_is_dot_grid_and_choice_is_per_person(client):
    assert client.get("/api/me", headers=as_user(DORA)).json()["design"] == "dots"
    saved = client.put("/api/me/design", json={"design": "hex"}, headers=as_user(DORA, True))
    assert saved.status_code == 200 and saved.json() == {"design": "hex"}
    assert client.get("/api/me", headers=as_user(DORA)).json()["design"] == "hex"
    assert client.get("/api/me", headers=as_user(ADM01)).json()["design"] == "dots"  # andere Person unberührt
    for choice in ("plus", "plain"):
        assert client.put("/api/me/design", json={"design": choice}, headers=as_user(DORA, True)).json() == {"design": choice}
    # zurück auf den Standard
    assert client.put("/api/me/design", json={"design": "dots"}, headers=as_user(DORA, True)).json() == {"design": "dots"}
    assert client.get("/api/me", headers=as_user(DORA)).json()["design"] == "dots"


def test_unknown_design_is_rejected_and_needs_write_header(client):
    assert client.put("/api/me/design", json={"design": "neon"}, headers=as_user(DORA, True)).status_code == 422
    assert client.put("/api/me/design", json={"design": "hex"}, headers=as_user(DORA)).status_code in (400, 403)
    assert client.get("/api/me", headers=as_user(DORA)).json()["design"] == "dots"


def test_styles_and_script_know_the_same_designs():
    """Server, theme-init.js und style.css führen dieselben Muster; sonst bliebe eine Wahl ohne Wirkung."""
    from app.main import DESIGNS

    init = (STATIC / "theme-init.js").read_text(encoding="utf-8")
    listed = re.search(r"const DESIGNS = \[(.*?)\]", init).group(1)
    assert tuple(re.findall(r'"(\w+)"', listed)) == DESIGNS
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    for name in DESIGNS:
        if name != "plain":
            assert f':root[data-design="{name}"]' in css and f'.design-swatch[data-d="{name}"]' in css
    # Farben nur aus dem Theme: keine festen Farbwerte im Musterblock
    block = css[css.index("Hintergrund-Muster (Einstellungen"):]
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b(?!\w)", block.replace("#000", "").replace("%23000", ""))
    assert "prefers-reduced-motion" not in block and "animation" not in block  # steht still
