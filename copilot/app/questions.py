"""Rückfragen der KI an die Person (Werkzeug ``ask_user``), wie bei Claude als Box über dem Eingabefeld.

Die KI stellt bis zu vier Fragen mit je zwei bis vier Antwortmöglichkeiten (Einfach- oder Mehrfachauswahl, optional mit
Vorschau). Ein Feld für eine eigene Antwort gibt es immer. Die Antwort läuft wie eine Freigabe über die offenen Rückfragen
des Laufs (``Run.pending``); hier wird nur geprüft, aufbereitet und als Text an die KI zurückgegeben.

Alle Texte stammen von der KI und werden streng begrenzt; die Oberfläche setzt sie nur als Text (nie als HTML) ein.
"""
from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

from .ha_tools import ToolError, ToolSpec
from .i18n import tr

MAX_QUESTIONS = 4
MIN_OPTIONS = 2
MAX_OPTIONS = 4
QUESTION_CHARS = 300
HEADER_CHARS = 24
LABEL_CHARS = 80
DESCRIPTION_CHARS = 200
PREVIEW_CHARS = 2000
PREVIEW_LINES = 40
OTHER_CHARS = 2000
DIRECT_CHARS = 4000

Ask = Callable[[list[dict]], Awaitable[dict | None]]  # Fragen -> Antwort der Oberfläche (oder None: keine Antwort)
Record = Callable[[dict], None]

QUESTIONS_NOTE = (
    "Mit ask_user stellst du der Person Rückfragen mit Antwortmöglichkeiten (eine Box über dem Eingabefeld). Nutze das nur, "
    "wenn die Anfrage wirklich offen ist und eine falsche Annahme teuer wäre (viel Arbeit, schwer rückgängig, mehrere sinnvolle "
    "Wege), nicht für Kleinigkeiten mit naheliegender Lösung und nicht, um für Eindeutiges um Erlaubnis zu bitten. Änderungen "
    "fragen ohnehin selbst nach. Bündle alles in einem Aufruf (bis zu 4 Fragen, je 2 bis 4 Möglichkeiten); setze die Empfehlung "
    "an die erste Stelle und hänge „(Empfohlen)“ an. Ein Feld für eine eigene Antwort gibt es immer, biete also kein „Sonstiges“ an. "
    "Schreib vor dem Aufruf höchstens einen kurzen Satz und wiederhole die Fragen nicht im Text. Übersprungene Fragen entscheidest "
    "du selbst vernünftig und sagst kurz, welche Annahme du getroffen hast."
)

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f​-‏‪-‮⁦-⁩]")


def _line(value: Any, limit: int) -> str:
    """Einzeiliger Text: Steuerzeichen und Zeilenumbrüche raus, Leerraum zusammengezogen, gekürzt."""
    if not isinstance(value, str):
        return ""
    text = re.sub(r"\s+", " ", _CONTROL.sub(" ", value.replace("\n", " "))).strip()
    return text[:limit].rstrip()


def _block(value: Any, limit: int, lines: int) -> str:
    """Mehrzeiliger Text (Vorschau): Steuerzeichen außer Zeilenumbruch raus, Zeilen und Länge begrenzt."""
    if not isinstance(value, str):
        return ""
    text = _CONTROL.sub("", value.replace("\r\n", "\n").replace("\t", "    "))
    text = "\n".join(text.split("\n")[:lines]).strip("\n")
    return text[:limit]


def clean_questions(args: dict[str, Any]) -> list[dict]:
    """Eingabe der KI prüfen und auf die erlaubte Form bringen (wirft ToolError mit einem Hinweis für die KI)."""
    raw = args.get("questions")
    if not isinstance(raw, list) or not raw:
        raise ToolError("questions fehlt: gib 1 bis 4 Fragen an.")
    if len(raw) > MAX_QUESTIONS:
        raise ToolError(f"Höchstens {MAX_QUESTIONS} Fragen auf einmal.")
    questions: list[dict] = []
    seen_q: set[str] = set()
    for number, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise ToolError(f"Frage {number} ist kein Objekt.")
        text = _line(item.get("question"), QUESTION_CHARS)
        if not text:
            raise ToolError(f"Frage {number}: question fehlt.")
        if text.casefold() in seen_q:
            raise ToolError(f"Frage {number} kommt doppelt vor.")
        seen_q.add(text.casefold())
        options_raw = item.get("options")
        if not isinstance(options_raw, list) or not (MIN_OPTIONS <= len(options_raw) <= MAX_OPTIONS):
            raise ToolError(f"Frage {number}: gib {MIN_OPTIONS} bis {MAX_OPTIONS} Antwortmöglichkeiten an (ein Feld für eine eigene Antwort gibt es immer).")
        options: list[dict] = []
        seen_o: set[str] = set()
        for pos, option in enumerate(options_raw, 1):
            if isinstance(option, str):
                option = {"label": option}
            if not isinstance(option, dict):
                raise ToolError(f"Frage {number}, Möglichkeit {pos} ist kein Objekt.")
            label = _line(option.get("label"), LABEL_CHARS)
            if not label:
                raise ToolError(f"Frage {number}, Möglichkeit {pos}: label fehlt.")
            if label.casefold() in seen_o:
                raise ToolError(f"Frage {number}: „{label}“ kommt doppelt vor.")
            seen_o.add(label.casefold())
            entry = {"label": label}
            description = _line(option.get("description"), DESCRIPTION_CHARS)
            if description:
                entry["description"] = description
            preview = _block(option.get("preview"), PREVIEW_CHARS, PREVIEW_LINES)
            if preview.strip():
                entry["preview"] = preview
            options.append(entry)
        header = _line(item.get("header"), HEADER_CHARS) or tr("Frage {n}", n=number)
        questions.append({"question": text, "header": header, "multi": bool(item.get("multi_select")), "options": options})
    return questions


def _picked(question: dict, given: Any) -> tuple[list[str], str]:
    """Gewählte Möglichkeiten (als Text) und eigene Antwort einer Frage; ungültige Angaben fallen still weg."""
    if not isinstance(given, dict):
        return [], ""
    chosen = given.get("selected")
    labels: list[str] = []
    if isinstance(chosen, list):
        for index in chosen:
            if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(question["options"]):
                label = question["options"][index]["label"]
                if label not in labels:
                    labels.append(label)
    if not question["multi"]:
        labels = labels[:1]
    other = _block(given.get("other"), OTHER_CHARS, 30).strip()
    return labels, other


def answered(questions: list[dict], answer: dict | None) -> list[dict]:
    """Je Frage: Überschrift, Frage, gewählte Möglichkeiten und eigene Antwort (leer = übersprungen)."""
    items = answer.get("answers") if isinstance(answer, dict) else None
    items = items if isinstance(items, list) else []
    skipped_all = not isinstance(answer, dict) or bool(answer.get("skipped"))
    result = []
    for index, question in enumerate(questions):
        labels, other = ([], "") if skipped_all else _picked(question, items[index] if index < len(items) else None)
        result.append({"header": question["header"], "question": question["question"], "picked": labels, "other": other})
    return result


def result_text(questions: list[dict], answer: dict | None) -> str:
    """Antwort für die KI."""
    if answer is None:
        return ("Keine Antwort: Die Person hat nicht rechtzeitig geantwortet oder kann gerade nicht antworten. "
                "Triff die vernünftigsten Annahmen, sag kurz, welche, und mach weiter.")
    direct = _block(answer.get("direct"), DIRECT_CHARS, 60).strip() if isinstance(answer, dict) else ""
    if direct:
        listing = "\n".join(f"- {q['question']}" for q in questions)
        return ("Statt in der Box hat die Person direkt geantwortet (eigene Worte, gilt für alle Fragen):\n"
                f"„{direct}“\n\nDie Fragen waren:\n{listing}\nMach damit weiter.")
    rows = answered(questions, answer)
    if all(not r["picked"] and not r["other"] for r in rows):
        return ("Die Person hat die Rückfrage übersprungen. Entscheide selbst vernünftig, sag kurz, welche Annahmen du "
                "getroffen hast, und mach weiter.")
    lines = ["Antworten der Person:"]
    for row in rows:
        bits = []
        if row["picked"]:
            bits.append(", ".join(f"„{p}“" for p in row["picked"]))
        if row["other"]:
            bits.append(f"eigene Antwort: „{row['other']}“")
        lines.append(f"- {row['question']} → " + ("; ".join(bits) if bits else "übersprungen (entscheide selbst und sag kurz, wie)"))
    lines.append("Mach damit weiter.")
    return "\n".join(lines)


def summary(questions: list[dict], answer: dict | None) -> tuple[str, list[dict]]:
    """Eintrag für den Verlauf: kurzes Label und je Frage Frage und Antwort (für den Block im Antworttext, wie bei Claude)."""
    def rows(text: str) -> list[dict]:
        return [{"question": q["question"], "answer": text, "skipped": True} for q in questions]

    if answer is None:
        return tr("Rückfrage ohne Antwort"), rows(tr("Keine Antwort"))
    direct = _block(answer.get("direct"), DIRECT_CHARS, 60).strip() if isinstance(answer, dict) else ""
    if direct:
        lead = questions[0]["question"] if len(questions) == 1 else tr("Direkt geantwortet")
        return tr("Rückfrage direkt beantwortet"), [{"question": lead, "answer": direct[:400]}]
    given = answered(questions, answer)
    if all(not r["picked"] and not r["other"] for r in given):
        return tr("Rückfrage übersprungen"), rows(tr("Übersprungen"))
    details = []
    for row in given:
        parts = list(row["picked"]) + ([row["other"][:300]] if row["other"] else [])
        details.append({"question": row["question"], "answer": ", ".join(parts)} if parts else
                       {"question": row["question"], "answer": tr("Übersprungen"), "skipped": True})
    return tr("Rückfrage beantwortet"), details


SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_QUESTIONS,
            "description": "1 bis 4 Fragen, die nacheinander in der Box erscheinen.",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "Die vollständige Frage, mit Fragezeichen."},
                    "header": {"type": "string", "description": "Sehr kurzes Stichwort (höchstens 12 Zeichen), z. B. „Raum“, „Uhrzeit“."},
                    "multi_select": {"type": "boolean", "description": "true, wenn mehrere Möglichkeiten zugleich gewählt werden dürfen."},
                    "options": {
                        "type": "array",
                        "minItems": MIN_OPTIONS,
                        "maxItems": MAX_OPTIONS,
                        "description": "2 bis 4 Möglichkeiten; die empfohlene zuerst, mit „(Empfohlen)“ am Ende des label. Kein „Sonstiges“: ein Feld für eine eigene Antwort gibt es immer.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string", "description": "Kurzer Titel (1 bis 5 Wörter)."},
                                "description": {"type": "string", "description": "Optional: eine Zeile, was diese Wahl bedeutet."},
                                "preview": {"type": "string", "description": "Optional: Vorschau als reiner Text in Festbreitenschrift (Skizze, YAML, Code), erscheint neben den Möglichkeiten."},
                            },
                            "required": ["label"],
                        },
                    },
                },
                "required": ["question", "options"],
            },
        },
    },
    "required": ["questions"],
}


class QuestionToolbox:
    """Werkzeug ``ask_user``: Rückfrage stellen, auf die Antwort warten, Ergebnis im Verlauf vermerken."""

    def __init__(self, ask: Ask, record: Record, next_id: Callable[[], int], offset: Callable[[], int] | None = None) -> None:
        self._ask = ask
        self._record = record
        self._next_id = next_id
        self._offset = offset or (lambda: 0)  # Stelle im bisherigen Antworttext (UTF-16), dort steht der Block im Chat

    def specs(self) -> list[ToolSpec]:
        return [ToolSpec(
            "ask_user",
            "Stellt der Person eine oder mehrere Rückfragen mit Antwortmöglichkeiten und wartet auf ihre Wahl. "
            "Nur bei echter Mehrdeutigkeit, wenn eine falsche Annahme teuer wäre. Liefert die gewählten Möglichkeiten "
            "bzw. eigene Antworten als Text.",
            SCHEMA,
            self._run,
        )]

    async def _run(self, args: dict[str, Any]) -> str:
        questions = clean_questions(args)
        answer = await self._ask(questions)
        at = self._offset()  # erst nach der Antwort: bis dahin ist der Text vor der Frage sicher angekommen
        label, details = summary(questions, answer)
        self._record({
            "type": "tool", "id": self._next_id(), "label": label, "kind": "question",
            "status": "ok" if answer is not None else "abgebrochen", "note": "", "question": details, "at": at,
        })
        return result_text(questions, answer)
