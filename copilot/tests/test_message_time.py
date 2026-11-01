"""Zeitangabe unter eigenen Nachrichten (``sentAgo`` in app.js): „vor 33 Minuten“, „Heute Morgen“, „Gestern“ …"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js nicht installiert")


def run_cases(cases: list[list]) -> list[str]:
    """Jeder Fall: [Minuten seit dem Senden] oder [Tag, Stunde] (Oktober 2026); „jetzt“ ist der 31.10.2026, 15:00."""
    source = (STATIC / "app.js").read_text(encoding="utf-8")
    match = re.search(r"function sentAgo\(.*?\n}\n", source, re.S)
    assert match, "sentAgo fehlt in app.js"
    script = "const window = {};\n" + (STATIC / "i18n.js").read_text(encoding="utf-8") + match.group(0) + """
const now = new Date(2026, 9, 31, 15, 0, 0);
const cases = %s;
console.log(JSON.stringify(cases.map((c) => sentAgo(
  (c.length === 1 ? new Date(now - c[0] * 60000) : c.length === 2 ? new Date(2026, 9, c[0], c[1]) : new Date(c[0], c[1], c[2], 9)).toISOString(), now))));
""" % json.dumps(cases)
    out = subprocess.run([shutil.which("node"), "-e", script], capture_output=True, text=True, check=True, env={**os.environ, "TZ": "Europe/Berlin"})
    return json.loads(out.stdout)


def test_minutes_hours_and_days():
    assert run_cases([[0], [1], [33], [59], [60], [89], [90], [150], [359]]) == [
        "gerade eben", "vor 1 Minute", "vor 33 Minuten", "vor 59 Minuten",
        "vor 1 Stunde", "vor 1 Stunde", "vor 2 Stunden", "vor 3 Stunden", "vor 6 Stunden",
    ]
    assert run_cases([[31, 2], [31, 7], [31, 9], [30, 20], [29, 9], [28, 9], [25, 9]]) == [
        "Heute Nacht", "Heute Morgen", "Heute Morgen", "Gestern", "Vorgestern", "vor 3 Tagen", "vor 6 Tagen",
    ]


def test_older_than_a_week_shows_the_date():
    assert run_cases([[23, 9], [2025, 10, 3]]) == ["23. Okt.", "3. Nov. 2025"]
