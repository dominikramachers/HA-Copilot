"""Export der eigenen Daten: ein Chat als Markdown, alles als ZIP.

Enthalten sind Chats (Markdown), Projekte mit ihren Anweisungen, das persönliche Gedächtnis und die geplanten Aufgaben.
Nicht enthalten sind hochgeladene Projektdateien und vom Assistenten erzeugte Dateien (sie laufen nach einiger Zeit ab).
"""
from __future__ import annotations

import io
import re
import zipfile
from datetime import datetime
from typing import Any

from . import schedule as sched
from .i18n import tr
from .db import Store

NO_PROJECT = "Ohne Projekt"  # Schlüssel für tr(): Ordnernamen im Export
SCHEDULED = "Geplante Aufgaben"
ROLES = {"user": "Du", "assistant": "Assistent"}

README = (
    "Export deiner Daten aus {app}\n"
    "Erstellt am {when}\n\n"
    "chats/                  alle Chats als Markdown, je Projekt ein Ordner\n"
    "projekte.md             deine Projekte mit ihren Anweisungen\n"
    "gedaechtnis.md          dein persönliches Gedächtnis\n"
    "geplante-aufgaben.md    deine geplanten Aufgaben\n\n"
    "Nicht enthalten: hochgeladene Projektdateien und vom Assistenten erzeugte Dateien.\n"
)


def local_time(iso: str) -> str:
    """Zeitstempel (UTC, ISO) als Ortszeit „TT.MM.JJJJ HH:MM“."""
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return iso


def safe_name(text: str, fallback: str = "Chat", limit: int = 80) -> str:
    """Als Datei- oder Ordnername brauchbar: keine Sonderzeichen, nicht zu lang, nie leer."""
    cleaned = re.sub(r'[\x00-\x1f<>:"/\\|?*]+', " ", text or "")
    cleaned = " ".join(cleaned.split()).strip(". ")
    return (cleaned[:limit].strip(". ") or fallback)


def _action_lines(tools: list[dict[str, Any]]) -> list[str]:
    lines = []
    for tool in tools:
        text = tool.get("label") or ""
        if not text:
            continue
        if tool.get("status", "ok") != "ok":
            text += f" ({tool['status']})"
        if tool.get("note"):
            text += f": {tool['note']}"
        if tool.get("file"):
            text += " – " + tr("Datei: {name}", name=tool["file"].get("name") or tr("Datei"))
        if tool.get("link"):
            text += f" – {tool['link']}"
        lines.append(f"> - {' '.join(text.split())}")
    return lines


def chat_markdown(chat: dict[str, Any], messages: list[dict[str, Any]], project: str = "", app_name: str = "") -> str:
    """Ein Chat als Markdown-Text."""
    title = " ".join((chat.get("title") or tr("Chat")).split())
    meta = [tr("Erstellt: {when}", when=local_time(chat.get("created_at", "")))]
    if project:
        meta.insert(0, tr("Projekt: {project}", project=project))
    if chat.get("schedule_id"):
        meta.insert(0, tr("Geplante Aufgabe"))
    if app_name:
        meta.append(tr("exportiert aus {app}", app=app_name))
    out = [f"# {title}", "", "*" + " · ".join(meta) + "*", ""]
    for message in messages:
        who = tr(ROLES[message["role"]]) if message.get("role") in ROLES else message.get("role", "")
        out += ["---", "", f"## {who} · {local_time(message.get('created_at', ''))}", ""]
        content = (message.get("content") or "").strip()
        if content:
            out += [content, ""]
        names = [a["name"] for a in message.get("attachments", []) if a.get("name")]
        if names:
            out += ["*" + tr("Anhänge: {names}", names=", ".join(names)) + "*", ""]
        actions = _action_lines(message.get("tools", []))
        if actions:
            out += ["> " + tr("Aktionen:"), *actions, ""]
    return "\n".join(out).rstrip() + "\n"


def _projects_markdown(projects: list[dict[str, Any]]) -> str:
    out = ["# " + tr("Projekte"), ""]
    if not projects:
        out += [tr("Keine Projekte."), ""]
    for project in projects:
        out += [f"## {project['name']}", ""]
        out += [project["instructions"].strip() or "*" + tr("Keine Anweisungen.") + "*", ""]
    return "\n".join(out).rstrip() + "\n"


def _memory_markdown(entries: list[dict[str, Any]]) -> str:
    out = ["# " + tr("Persönliches Gedächtnis"), ""]
    if not entries:
        out += [tr("Keine Einträge."), ""]
    for entry in entries:
        out += [f"## {entry['topic']}", "", entry["content"].strip(), ""]
    return "\n".join(out).rstrip() + "\n"


def _schedules_markdown(tasks: list[dict[str, Any]]) -> str:
    out = ["# " + tr("Geplante Aufgaben"), ""]
    if not tasks:
        out += [tr("Keine geplanten Aufgaben."), ""]
    for task in tasks:
        state = tr("aktiv") if task["enabled"] else tr("pausiert")
        out += [f"## {task['name']}", "", f"*{sched.describe(task['freq'], task['at'], task['days'])} · {state}*", "",
                task["prompt"].strip(), ""]
    return "\n".join(out).rstrip() + "\n"


def build_zip(store: Store, profile_id: str, app_name: str = "", now: datetime | None = None) -> bytes:
    """Alle eigenen Daten einer Person als ZIP (im Speicher)."""
    now = now or datetime.now().astimezone()
    projects = store.list_projects(profile_id)
    names = {p["id"]: p["name"] for p in projects}
    used: set[str] = set()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(tr("LIESMICH.txt"), tr(README, app=app_name or "KI Chat", when=now.strftime("%d.%m.%Y %H:%M")))
        for chat in store.list_chats(profile_id):
            messages = store.list_messages(profile_id, chat["id"]) or []
            if chat.get("schedule_id"):
                folder = safe_name(tr(SCHEDULED))
            else:
                folder = safe_name(names.get(chat["project_id"] or "", ""), tr(NO_PROJECT))
            day = chat["created_at"][:10]
            base = f"chats/{folder}/{day} {safe_name(chat['title'])}"
            path, n = base + ".md", 2
            while path.lower() in used:
                path, n = f"{base} ({n}).md", n + 1
            used.add(path.lower())
            archive.writestr(path, chat_markdown(chat, messages, names.get(chat["project_id"] or "", ""), app_name))
        archive.writestr(tr("projekte.md"), _projects_markdown(projects))
        archive.writestr(tr("gedaechtnis.md"), _memory_markdown(store.memory_list("person", profile_id)))
        archive.writestr(tr("geplante-aufgaben.md"), _schedules_markdown(store.schedule_list(profile_id)))
    return buffer.getvalue()
