"""Installationszahlen im Skill-Katalog aus der skills.sh-API nachziehen (``copilot/app/skill_catalog/catalog.json``).

Aufruf: ``SKILLS_SH_TOKEN=... python update_installs.py [Pfad zur catalog.json]``. Je Skill aus einem fremden Repository
wird ``GET https://skills.sh/api/v1/skills/<besitzer>/<repo>/<skill>`` abgefragt (Feld ``installs``). Skills, die die API
nicht kennt (404), und eigene Skills behalten ihren Wert. Ein ungültiges Token (401/403) bricht ab, ohne etwas zu ändern.
Geändert wird nur, was sich unterscheidet; ``installs_asof`` wird nur dann auf den aktuellen Monat gesetzt.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path

import httpx

API = "https://skills.sh/api/v1/skills"
OWN = {"dominikramachers"}  # eigene Skills haben keine Zahl
SOURCE = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/tree/[^/]+/(?:.+/)?([^/]+)$")


def lookup_key(source_url: str) -> tuple[str, str, str] | None:
    """(Besitzer, Repo, Skill-Ordner) aus der Quell-Adresse, oder None bei eigenen Skills."""
    m = SOURCE.match(source_url or "")
    if not m or m.group(1) in OWN:
        return None
    return m.group(1), m.group(2), m.group(3)


def fetch_installs(client: httpx.Client, owner: str, repo: str, skill: str) -> int | None:
    """Zahl der Installationen oder None, wenn die API das Skill nicht kennt. Wirft bei ungültigem Token."""
    for attempt in range(3):
        response = client.get(f"{API}/{owner}/{repo}/{skill}")
        if response.status_code == 429:
            time.sleep(min(int(response.headers.get("Retry-After", "5") or 5), 60))
            continue
        if response.status_code in (401, 403):
            raise SystemExit(f"skills.sh lehnt das Token ab ({response.status_code}); nichts geändert.")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        value = response.json().get("installs")
        return value if isinstance(value, int) and value >= 0 else None
    raise SystemExit("skills.sh begrenzt die Anfragen; später noch einmal versuchen.")


def update(catalog: dict, client: httpx.Client, month: str) -> list[str]:
    """Trägt neue Zahlen ein und nennt, was sich geändert hat (leer = nichts zu tun)."""
    changes: list[str] = []
    for skill in catalog["skills"]:
        key = lookup_key(skill.get("source", ""))
        if key is None:
            continue
        installs = fetch_installs(client, *key)
        if installs is None:
            print(f"keine Zahl für {skill['id']} ({'/'.join(key)}), alter Wert bleibt", file=sys.stderr)
        elif installs != skill.get("installs"):
            changes.append(f"{skill['id']}: {skill.get('installs')} -> {installs}")
            skill["installs"] = installs
    if changes:
        catalog["installs_asof"] = month
    return changes


def main(argv: list[str]) -> int:
    path = Path(argv[1] if len(argv) > 1 else "copilot/app/skill_catalog/catalog.json")
    token = os.environ.get("SKILLS_SH_TOKEN", "").strip()
    if not token:
        print("SKILLS_SH_TOKEN fehlt.", file=sys.stderr)
        return 2
    catalog = json.loads(path.read_text(encoding="utf-8"))
    with httpx.Client(headers={"Authorization": f"Bearer {token}", "User-Agent": "ha-copilot-catalog"}, timeout=20.0) as client:
        changes = update(catalog, client, date.today().strftime("%Y-%m"))
    if changes:
        path.write_text(json.dumps(catalog, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("\n".join(changes) if changes else "Keine Änderungen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
