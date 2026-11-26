"""Jedes Symbol, das ``app.js`` mit ``icon("…")`` benutzt, steht auch in ``ICONS``.

Ein unbekannter Name wirft beim Zeichnen einen Fehler; mitten in einer Antwort bricht dann die Anzeige ab (0.67.0).
"""
import pathlib
import re

APP = pathlib.Path(__file__).resolve().parents[1] / "app" / "static" / "app.js"


def test_every_icon_name_is_defined():
    source = APP.read_text(encoding="utf-8")
    table = source[source.index("const ICONS = {"):source.index("function icon(")]
    defined = set(re.findall(r'^\s+"?([A-Za-z][\w-]*)"?\s*:', table, re.M))
    used = set(re.findall(r'\bicon\("([\w-]+)"', source))
    assert used and not used - defined, sorted(used - defined)
