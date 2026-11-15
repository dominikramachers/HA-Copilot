"""Auflistungen in eigenen Nachrichten (``renderMarkdown`` im Nur-Text-Modus, markdown.js): Struktur der Listen."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js nicht installiert")

# Kleine DOM-Attrappe: reicht für den Nur-Text-Modus (Absätze und Listen).
FAKE_DOM = """
class El {
  constructor(tag) { this.tag = tag; this.kids = []; this.className = ""; }
  append(...items) { for (const i of items) this.kids.push(i); }
  appendChild(i) { this.kids.push(i); }
  replaceChildren(...items) { this.kids = items; }
  set textContent(t) { this.kids = [String(t)]; }
}
const document = { createElement: (t) => new El(t), createTextNode: (t) => String(t) };
const window = {};
const tr = (s) => s;
function shape(n) { return typeof n === "string" ? n : n.tag + (n.kids.length ? "(" + n.kids.map(shape).join(",") + ")" : ""); }
"""


def shapes(sources: list[str]) -> list[str]:
    script = FAKE_DOM + (STATIC / "markdown.js").read_text(encoding="utf-8") + """
const sources = %s;
console.log(JSON.stringify(sources.map((s) => shape(window.renderMarkdown(s, { plain: true })))));
""" % json.dumps(sources)
    out = subprocess.run([shutil.which("node"), "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_numbered_items_with_a_small_indent_stay_one_list():
    # Wie getippt oder eingefügt: ab der zweiten Zeile ein Leerzeichen mehr. Das ist eine Liste, keine Unterliste.
    assert shapes(["1. ja gerne\n 2. direkt\n 3. ja"]) == ["div(ol(li(ja gerne),li(direkt),li(ja)))"]
    assert shapes(["- a\n - b"]) == ["div(ul(li(a),li(b)))"]


def test_real_sublists_still_nest():
    assert shapes(["- a\n  - b\n- c"]) == ["div(ul(li(a,ul(li(b))),li(c)))"]
    assert shapes(["1. a\n   1. b\n2. c"]) == ["div(ol(li(a,ol(li(b))),li(c)))"]
    assert shapes(["1. a\n  - b"]) == ["div(ol(li(a,ul(li(b)))))"]
