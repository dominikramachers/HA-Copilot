"""Auf einen Ausschnitt einer Antwort antworten (Zitat).

Die Oberfläche schickt den markierten Text getrennt von der eigenen Nachricht (``quote``). Gespeichert und an die KI gegeben wird beides
als eine Nachricht: ein Zitatblock im Markdown-Stil (jede Zeile mit ``> ``), eine Leerzeile, dann der eigene Text. So bleibt das Zitat
beim Neuladen, im Export und für die KI sichtbar, ohne dass die Datenbank sich ändert. ``static/app.js`` (``withQuote``/``splitQuote``)
arbeitet nach demselben Muster.
"""
from __future__ import annotations

QUOTE_MAX = 2000  # Zeichen, die von einem Zitat übernommen werden


def clean(quote: str | None) -> str:
    """Zitat bereinigen: Zeilenenden vereinheitlichen, Ränder und mehrfache Leerzeilen entfernen, auf ``QUOTE_MAX`` kürzen."""
    text = (quote or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = [line.rstrip() for line in text.split("\n")]
    out: list[str] = []
    for line in lines:
        if not line and out and not out[-1]:
            continue
        out.append(line)
    text = "\n".join(out).strip()
    return text[:QUOTE_MAX].rstrip() + ("…" if len(text) > QUOTE_MAX else "")


def with_quote(quote: str | None, text: str) -> str:
    """Eigene Nachricht mit vorangestelltem Zitatblock; ohne Zitat unverändert."""
    cleaned = clean(quote)
    if not cleaned:
        return text
    block = "\n".join(f"> {line}" if line else ">" for line in cleaned.split("\n"))
    return f"{block}\n\n{text}"


def split_quote(content: str) -> tuple[str, str]:
    """Gegenstück zu :func:`with_quote`: ``(Zitat, eigener Text)``; ohne führenden Zitatblock ist das Zitat leer."""
    lines = content.split("\n")
    count = 0
    while count < len(lines) and (lines[count].startswith("> ") or lines[count] == ">"):
        count += 1
    if count == 0 or count >= len(lines) or lines[count] != "":
        return "", content
    quote = "\n".join(line[2:] if line.startswith("> ") else "" for line in lines[:count])
    return quote, "\n".join(lines[count + 1:]).lstrip("\n")
