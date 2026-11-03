"""Kleiner Markdown-Zerleger für die Dateiausgabe (Word, PDF, PowerPoint).

Bewusst nur das, was die KI in Dokumenten braucht: Überschriften, Absätze, Listen (auch verschachtelt),
Tabellen, Codeblöcke, Zitate, Trennlinien sowie **fett**, *kursiv*, `Code` und Links. Keine Bibliothek nötig.

Ergebnis von :func:`parse`: eine Liste von Blöcken (Tupel):

* ``("h", Ebene, Runs)``
* ``("p", Runs)``
* ``("list", ordered, [(Ebene, Runs), …])``
* ``("table", [[Runs, …], …])``   (erste Zeile = Kopfzeile)
* ``("code", Text)``
* ``("quote", Runs)``
* ``("hr",)``
* ``("image", Beschreibung, Verweis)``   (eigene Zeile ``![Beschreibung](dateiname.png)``)
* ``("chart", JSON-Text)``              (Codeblock mit der Sprache ``chart``, siehe ``charts.py``)
* ``("toc",)``                          (eigene Zeile ``[TOC]`` oder ``[Inhaltsverzeichnis]``)

Ein *Run* ist ``(Text, Stil)`` mit Stil als Zeichenkette aus ``b`` (fett), ``i`` (kursiv), ``c`` (Code).
"""
from __future__ import annotations

import re

Run = tuple[str, str]
Block = tuple


class LinkRun(tuple):
    """Run eines Links: verhält sich wie ``(Text, Stil)``, trägt aber zusätzlich die Adresse in ``url``."""

    url: str

    def __new__(cls, text: str, style: str, url: str) -> "LinkRun":
        obj = super().__new__(cls, (text, style))
        obj.url = url
        return obj

_FENCE = re.compile(r"^\s*(```|~~~)")
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_RULE = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
_ITEM = re.compile(r"^(\s*)([-*+•]|\d{1,3}[.)])\s+(.*)$")
_IMAGE = re.compile(r"^\s*!\[(?P<alt>[^\]]*)\]\(\s*<?(?P<ref>[^)>]+?)>?(?:\s+\"[^\"]*\")?\s*\)\s*$")
_TOC = re.compile(r"^\s*\[{1,2}\s*(toc|inhaltsverzeichnis|table of contents)\s*\]{1,2}\s*$", re.I)
_QUOTE = re.compile(r"^\s{0,3}>\s?(.*)$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_INLINE = re.compile(
    r"(\*\*\*(?P<bi>.+?)\*\*\*)|(\*\*(?P<b>.+?)\*\*)|(__(?P<b2>.+?)__)|(`(?P<c>[^`]+)`)|"
    r"(\[(?P<lt>[^\]]+)\]\((?P<lu>[^)\s]+)\))|(?P<bare>https?://[^\s<>()\[\]]*[^\s<>()\[\].,;:!?'\"])|(\*(?P<i>[^*\s][^*]*?)\*)|(?<![A-Za-z0-9_])_(?P<i2>[^_\s][^_]*?)_(?![A-Za-z0-9_])"
)


def inline(text: str) -> list[Run]:
    """Zeichenformate eines Textes in Runs zerlegen. Links (http, https, mailto) und nackte Webadressen werden :class:`LinkRun`."""
    runs: list[Run] = []
    pos = 0
    for m in _INLINE.finditer(text):
        if m.start() > pos:
            runs.append((text[pos:m.start()], ""))
        if m.group("bi"):
            runs.append((m.group("bi"), "bi"))
        elif m.group("b") or m.group("b2"):
            runs.append((m.group("b") or m.group("b2"), "b"))
        elif m.group("c"):
            runs.append((m.group("c"), "c"))
        elif m.group("lt"):
            label, url = m.group("lt"), m.group("lu")
            runs.append(LinkRun(label, "", url) if re.match(r"(https?://|mailto:)", url) else (f"{label} ({url})" if label != url else label, ""))
        elif m.group("bare"):
            runs.append(LinkRun(m.group("bare"), "", m.group("bare")))
        else:
            runs.append((m.group("i") or m.group("i2"), "i"))
        pos = m.end()
    if pos < len(text):
        runs.append((text[pos:], ""))
    return [r for r in runs if r[0]] or [("", "")]


def plain(runs: list[Run]) -> str:
    return "".join(t for t, _ in runs)


def _cells(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line)]


def parse(text: str) -> list[Block]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[Block] = []
    para: list[str] = []
    i = 0

    def flush() -> None:
        if para:
            blocks.append(("p", inline(" ".join(s.strip() for s in para))))
            para.clear()

    while i < len(lines):
        line = lines[i]
        if _FENCE.match(line):
            flush()
            marker = _FENCE.match(line).group(1)  # type: ignore[union-attr]
            code: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(marker):
                code.append(lines[i])
                i += 1
            i += 1
            language = line.strip()[len(marker):].strip().split(" ")[0].lower()
            blocks.append(("chart", "\n".join(code)) if language == "chart" else ("code", "\n".join(code)))
            continue
        if not line.strip():
            flush()
            i += 1
            continue
        picture = _IMAGE.match(line)
        if picture:
            flush()
            blocks.append(("image", picture.group("alt").strip(), picture.group("ref").strip()))
            i += 1
            continue
        if _TOC.match(line):
            flush()
            blocks.append(("toc",))
            i += 1
            continue
        heading = _HEADING.match(line)
        if heading:
            flush()
            blocks.append(("h", len(heading.group(1)), inline(heading.group(2))))
            i += 1
            continue
        if _RULE.match(line):
            flush()
            blocks.append(("hr",))
            i += 1
            continue
        if "|" in line and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1]) and "-" in lines[i + 1]:
            flush()
            rows = [[inline(c) for c in _cells(line)]]
            i += 2
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append([inline(c) for c in _cells(lines[i])])
                i += 1
            width = max(len(r) for r in rows)
            blocks.append(("table", [r + [[("", "")]] * (width - len(r)) for r in rows]))
            continue
        item = _ITEM.match(line)
        if item:
            flush()
            ordered = item.group(2)[0].isdigit()
            items: list[tuple[int, list[Run]]] = []
            while i < len(lines):
                m = _ITEM.match(lines[i])
                if m and m.group(2)[0].isdigit() == ordered:
                    level = min(len(m.group(1).replace("\t", "    ")) // 2, 3)
                    items.append((level, inline(m.group(3).strip())))
                    i += 1
                elif m:
                    break
                elif lines[i].strip() and lines[i].startswith((" ", "\t")) and items:
                    level, runs = items[-1]  # Fortsetzungszeile eines Listenpunkts
                    items[-1] = (level, runs + [(" " + lines[i].strip(), "")])
                    i += 1
                else:
                    break
            blocks.append(("list", ordered, items))
            continue
        quote = _QUOTE.match(line)
        if quote:
            flush()
            quoted: list[str] = []
            while i < len(lines) and _QUOTE.match(lines[i]):
                quoted.append(_QUOTE.match(lines[i]).group(1))  # type: ignore[union-attr]
                i += 1
            blocks.append(("quote", inline(" ".join(q.strip() for q in quoted if q.strip()))))
            continue
        para.append(line)
        i += 1
    flush()
    return blocks
