"""Lange Chats: den älteren Verlauf zusammenfassen, statt ihn stillschweigend abzuschneiden.

Jede Anfrage schickt den ganzen bisherigen Verlauf mit. Das kostet Kontingent und stößt irgendwann an
die Grenze des Modells. Wird der Verlauf zu groß, fasst die KI den älteren Teil zusammen. Die neueren
Nachrichten bleiben wörtlich erhalten, die Zusammenfassung steht in der Datenbank und ersetzt den
alten Teil bei allen weiteren Anfragen (die Nachrichten selbst bleiben sichtbar und erhalten).
"""
from __future__ import annotations

TRIGGER_CHARS = 80_000  # Verlauf insgesamt (Zusammenfassung + Nachrichten + neue Frage) ab dieser Größe
KEEP_RECENT_CHARS = 24_000  # so viel vom Ende bleibt wörtlich
MIN_RECENT_MESSAGES = 4
MAX_PER_MESSAGE = 6_000  # beim Zusammenfassen: längere Nachrichten werden in der Mitte gekürzt


def size_of(summary: str | None, pending: list[dict], new_text: str) -> int:
    return len(summary or "") + sum(len(m["content"]) for m in pending) + len(new_text)


def needs_compaction(summary: str | None, pending: list[dict], new_text: str) -> bool:
    return size_of(summary, pending, new_text) > TRIGGER_CHARS


def split(pending: list[dict]) -> tuple[list[dict], list[dict]] | None:
    """(älter, neuer) aufteilen; ``None``, wenn nichts Sinnvolles zum Zusammenfassen da ist.

    Der neuere Teil beginnt immer mit einer Nutzer-Nachricht, damit Frage und Antwort zusammenbleiben.
    """
    used = 0
    cut = len(pending)
    while cut > 0:
        used += len(pending[cut - 1]["content"])
        cut -= 1
        if used >= KEEP_RECENT_CHARS and len(pending) - cut >= MIN_RECENT_MESSAGES:
            break
    back = cut
    while back > 0 and pending[back]["role"] != "user":
        back -= 1  # lieber etwas mehr wörtlich behalten als eine Antwort von ihrer Frage trennen
    if back > 0:
        cut = back
    else:
        while cut < len(pending) and pending[cut]["role"] != "user":
            cut += 1
    if cut <= 0 or cut >= len(pending):
        return None
    return pending[:cut], pending[cut:]


def clip(text: str, limit: int = MAX_PER_MESSAGE) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n[… {len(text) - limit} Zeichen ausgelassen …]\n{text[-half:]}"
