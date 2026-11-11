"""Plugins: Bündel aus Skills und Konnektoren zu einem Thema.

Zwei Wege führen zu einem Plugin:

* **Katalog** (``package_catalog``): Die Kennungen verweisen auf mitgelieferte Skills und Katalog-Konnektoren. Hinzufügen legt die Skills an
  und die Konnektoren als „nicht verbunden“; wo eine eigene App nötig ist (Google), bleibt es bei einem Hinweis zum Einrichten.
* **GitHub-Link** (``plugins_github``): Ein Claude-Plugin; übernommen werden nur Skills (als importiert, also Fremdinhalt) und Adressen aus
  ``.mcp.json`` (https, Streamable HTTP). Befehle, Unteragenten, Hooks und Skripte nicht.

Gespeichert wird das Plugin als Eintrag in ``plugins`` mit dem, was es mitgebracht hat. Beim Entfernen verschwinden nur die Teile, die es selbst
neu angelegt hat; was die Person schon vorher hatte oder selbst geändert hat, bleibt.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from typing import Any

from . import connector_catalog as ccat
from . import package_catalog as pcat
from . import skills as sk
from .connectors import RANK, ConnectorError
from .i18n import tr

MAX_PLUGINS = 40
MAX_IMPORT_SKILLS = 40
MAX_IMPORT_SERVERS = 10
AUTH_CHOICES = ("none", "oauth", "bearer", "header")


class PluginError(ValueError):
    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def fallback_name(source: str) -> str:
    """Name, falls das Plugin keinen nennt: Ordner aus der Quelle, sonst das Repository."""
    head, _, folder = source.partition(" ")
    return (folder.rsplit("/", 1)[-1] if folder else head.partition("@")[0].rsplit("/", 1)[-1]) or "plugin"


def _line(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


# ------------------------------------------------------------------------- Import: ZIP lesen

def _read_zip(data: bytes) -> dict[str, bytes]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise PluginError(tr("Das Plugin ist beschädigt oder kein gültiges ZIP.")) from None
    infos = [i for i in archive.infolist() if not i.is_dir()]
    if len(infos) > 400 or sum(i.file_size for i in infos) > sk.ZIP_TOTAL_BYTES:
        raise PluginError(tr("Das Plugin ist zu groß."))
    out: dict[str, bytes] = {}
    for info in infos:
        path = sk._clean_path(info.filename)
        if path is None or info.file_size > sk.ZIP_MEMBER_BYTES:
            continue
        with archive.open(info) as handle:
            out[path] = handle.read(sk.ZIP_MEMBER_BYTES + 1)[: sk.ZIP_MEMBER_BYTES]
    return out


def _server_auth(entry: dict) -> tuple[str, str]:
    """Anmeldeart und Name des Kopfs aus den ``headers`` des Eintrags raten; ohne Kopf gilt OAuth (die meisten Dienste)."""
    headers = entry.get("headers") if isinstance(entry.get("headers"), dict) else {}
    for name in headers:
        if str(name).lower() == "authorization":
            return "bearer", ""
    for name in headers:
        return "header", _line(name, 60)
    return "oauth", ""


def _parse_servers(raw: bytes | None) -> tuple[list[dict], list[str]]:
    """Server aus ``.mcp.json`` (``mcpServers`` oder direkt die Einträge). Nur ``https`` mit Streamable HTTP; der Rest wird genannt."""
    if raw is None:
        return [], []
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        return [], [tr(".mcp.json ist kein gültiges JSON")]
    if isinstance(data, dict) and isinstance(data.get("mcpServers"), dict):
        data = data["mcpServers"]
    if not isinstance(data, dict):
        return [], [tr(".mcp.json hat einen unerwarteten Aufbau")]
    servers: list[dict] = []
    notes: list[str] = []
    for name, entry in list(data.items())[:50]:
        if not isinstance(entry, dict):
            continue
        label = _line(name, 40) or "?"
        kind = str(entry.get("type") or ("http" if entry.get("url") else "stdio")).lower()
        url = str(entry.get("url") or "").strip()
        if kind in ("sse",):
            notes.append(tr("{name}: alter SSE-Transport wird nicht unterstützt", name=label))
        elif kind != "http" and kind != "streamable-http":
            notes.append(tr("{name}: läuft als Programm auf dem eigenen Rechner (wird nicht übernommen)", name=label))
        elif not url.lower().startswith("https://") or "${" in url or "{" in url:
            notes.append(tr("{name}: Adresse fehlt, ist nicht https oder enthält Platzhalter", name=label))
        else:
            auth, header = _server_auth(entry)
            known = next((c for c in ccat._load()["connectors"] if c.get("url", "").rstrip("/") == url.rstrip("/")), None)
            if known:
                auth = known["auth"]
                header = ""
            servers.append({"name": label, "url": url[:500], "auth": auth, "header_name": header, "catalog_id": known["id"] if known else ""})
    return servers[:MAX_IMPORT_SERVERS], notes


def parse_plugin_zip(data: bytes, fallback_name: str) -> dict[str, Any]:
    """Das vom GitHub-Abruf gebaute ZIP lesen: Name, Beschreibung, Skills (geprüft) und Server."""
    files = _read_zip(data)
    manifest: dict = {}
    if ".claude-plugin/plugin.json" in files:
        try:
            parsed = json.loads(files[".claude-plugin/plugin.json"].decode("utf-8-sig"))
            manifest = parsed if isinstance(parsed, dict) else {}
        except (ValueError, UnicodeDecodeError):
            manifest = {}
    name = _line(manifest.get("name") or fallback_name, 60) or tr("Plugin")
    folders: dict[str, dict[str, bytes]] = {}
    for path, content in files.items():
        parts = path.split("/")
        if parts[0] == "skills" and len(parts) > 2:
            folders.setdefault(parts[1], {})["/".join(parts[2:])] = content
    skills: list[dict] = []
    skipped: list[dict] = []
    for folder, members in sorted(folders.items())[:MAX_IMPORT_SKILLS]:
        if "SKILL.md" not in members:
            skipped.append({"name": folder, "reason": tr("keine SKILL.md")})
            continue
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel, content in members.items():
                zf.writestr(f"{folder}/{rel}", content)
        try:
            pkg = sk.parse_upload(f"{folder}.zip", buffer.getvalue())
        except sk.SkillError as exc:
            skipped.append({"name": folder, "reason": str(exc)})
            continue
        skills.append({"package": pkg})
    servers, notes = _parse_servers(files.get(".mcp.json"))
    return {
        "name": name, "description": _line(manifest.get("description"), 300), "version": _line(manifest.get("version"), 40),
        "skills": skills, "servers": servers, "skipped": skipped, "notes": notes,
    }


# ------------------------------------------------------------------------------- Dienst

class PluginService:
    def __init__(self, store: Any, connectors: Any) -> None:
        self._store = store
        self._connectors = connectors

    # ---------------------------------------------------------------------- Ansicht

    def _connector_views(self, profile_id: str) -> list[dict]:
        try:
            return self._connectors.listing(profile_id)
        except Exception:  # noqa: BLE001 - ohne Recht oder deaktiviert gibt es einfach keine Konnektoren zu zeigen
            return []

    def _skill_state(self, profile_id: str, skill_id: str, have: dict[str, str]) -> dict:
        entry = next((s for s in sk.recommended_list() if s["id"] == skill_id), None)
        label = entry["label"] if entry else skill_id
        name = entry["name"] if entry else skill_id
        origin = have.get(name)
        return {"id": skill_id, "name": name, "label": label, "state": "present" if origin == "recommended" else "taken" if origin else "missing"}

    def catalog(self, profile_id: str) -> list[dict]:
        have = {r["name"]: r["origin"] for r in self._store.skill_list(profile_id)}
        views = self._connector_views(profile_id)
        by_catalog = {v["catalog_id"]: v for v in views if v.get("catalog_id")}
        records = {r["key"]: r for r in self._store.plugin_list(profile_id)}
        labels = {s["id"]: s for s in sk.recommended_list()}
        out = []
        for entry in pcat.entries():
            skills = [
                {"id": sid, "label": (labels.get(sid) or {}).get("label", sid), "state": ("present" if have.get((labels.get(sid) or {}).get("name", sid)) == "recommended" else "taken" if (labels.get(sid) or {}).get("name", sid) in have else "missing")}
                for sid in entry["skills"]
            ]
            conns = []
            for cid in entry["connectors"]:
                meta = ccat.find(cid) or {}
                view = by_catalog.get(cid)
                conns.append({
                    "id": cid, "label": meta.get("label", cid), "icon": ccat.icon_slug(cid),
                    "state": "present" if view else "setup" if (meta.get("pre_registered") or meta.get("kind") == "guide") else "missing",
                })
            record = records.get(f"catalog:{entry['id']}")
            out.append({
                **entry, "skills": skills, "connectors": conns, "installed": bool(record),
                "complete": all(s["state"] != "missing" for s in skills) and all(c["state"] == "present" for c in conns),
            })
        return out

    def mine(self, profile_id: str) -> list[dict]:
        names = {r["name"]: r for r in self._store.skill_list(profile_id)}
        views = self._connector_views(profile_id)
        by_id = {v["id"]: v for v in views}
        by_catalog = {v["catalog_id"]: v for v in views if v.get("catalog_id")}
        out = []
        for rec in self._store.plugin_list(profile_id):
            parts_skills = [{"name": s["name"], "present": s["name"] in names} for s in rec["skills"]]
            parts_conns = []
            for c in rec["connectors"]:
                view = by_id.get(c.get("id")) if c.get("id") else by_catalog.get(c.get("catalog_id") or "")
                parts_conns.append({"name": c["name"], "catalog_id": c.get("catalog_id") or "", "icon": ccat.icon_slug(c.get("catalog_id") or ""),
                                    "connector_id": view["id"] if view else None, "status": view["status"] if view else "missing"})
            known = pcat.find(rec["key"][len("catalog:"):]) if rec["kind"] == "catalog" else None
            out.append({
                "id": rec["id"], "key": rec["key"], "kind": rec["kind"], "icon": (known or {}).get("icon", ""), "name": rec["name"], "description": rec["description"], "source": rec["source"],
                "skills": parts_skills, "connectors": parts_conns, "notes": rec["notes"],
                "missing": sum(1 for s in parts_skills if not s["present"]) + sum(1 for c in parts_conns if c["connector_id"] is None),
                "added": {"skills": len(rec["added_skills"]), "connectors": len(rec["added_connectors"])},
            })
        return out

    # ------------------------------------------------------------------- Skills anlegen

    def _add_skill(self, profile_id: str, pkg: sk.Package, origin: str) -> tuple[str, bool]:
        """(Zustand, neu angelegt). Zustände: added, present, taken, limit."""
        rows = {r["name"]: r["origin"] for r in self._store.skill_list(profile_id)}
        if pkg.name in rows:
            if rows[pkg.name] == origin:
                if origin == "imported":
                    self._store.skill_save(profile_id, pkg.name, pkg.description, pkg.files, origin=origin)  # neuere Fassung desselben Plugins
                return "present", False
            return "taken", False
        if len(rows) >= sk.PER_PERSON:
            return "limit", False
        self._store.skill_save(profile_id, pkg.name, pkg.description, pkg.files, origin=origin)
        return "added", True

    async def _add_connector(self, profile_id: str, data: dict) -> tuple[str, str, int | None]:
        """(Zustand, Hinweis, Konnektor-Nummer). Zustände: added, no_rights, failed."""
        if not self._connectors.can_create(profile_id)["private"]:
            return "no_rights", tr("Dafür fehlt dir das Recht, Konnektoren anzulegen."), None
        try:
            made = await self._connectors.create(profile_id, data)
        except ConnectorError as exc:
            return "failed", str(exc), None
        return "added", "", made["id"]

    # ------------------------------------------------------------------- Katalog-Plugin

    async def install(self, profile_id: str, plugin_id: str) -> dict[str, Any]:
        entry = pcat.find(plugin_id)
        if entry is None:
            raise PluginError(tr("Nicht gefunden"), 404)
        key = f"catalog:{plugin_id}"
        record = self._store.plugin_by_key(profile_id, key)
        if not record and self._store.plugin_count(profile_id) >= MAX_PLUGINS:
            raise PluginError(tr("Es sind höchstens {n} Plugins je Person möglich.", n=MAX_PLUGINS))
        lang_entry = next(e for e in pcat.entries() if e["id"] == plugin_id)
        added_skills = list(record["added_skills"]) if record else []
        added_conns = list(record["added_connectors"]) if record else []
        skills_out, parts_skills = [], []
        for sid in entry["skills"]:
            pkg = sk.recommended_package(sid)
            if pkg is None:
                skills_out.append({"id": sid, "label": sid, "state": "missing"})
                continue
            label = next((s["label"] for s in sk.recommended_list() if s["id"] == sid), pkg.name)
            state, fresh = self._add_skill(profile_id, pkg, "recommended")
            if fresh and pkg.name not in added_skills:
                added_skills.append(pkg.name)
            parts_skills.append({"name": pkg.name, "id": sid})
            skills_out.append({"id": sid, "label": label, "state": state})
        views = {v["catalog_id"]: v for v in self._connector_views(profile_id) if v.get("catalog_id")}
        conns_out, parts_conns = [], []
        for cid in entry["connectors"]:
            meta = ccat.find(cid) or {}
            label = meta.get("label", cid)
            parts_conns.append({"name": label, "catalog_id": cid})
            if self._connectors.level(profile_id) < RANK["use"]:
                conns_out.append({"id": cid, "label": label, "icon": ccat.icon_slug(cid), "state": "no_access", "message": tr("Konnektoren sind für dich nicht freigegeben.")})
            elif cid in views:
                conns_out.append({"id": cid, "label": label, "icon": ccat.icon_slug(cid), "state": "present", "message": ""})
            elif meta.get("pre_registered") or meta.get("kind") == "guide":
                conns_out.append({"id": cid, "label": label, "icon": ccat.icon_slug(cid), "state": "setup", "message": ""})
            else:
                state, message, made = await self._add_connector(profile_id, {"catalog_id": cid})
                if made is not None:
                    added_conns.append(made)
                    parts_conns[-1]["id"] = made
                conns_out.append({"id": cid, "label": label, "icon": ccat.icon_slug(cid), "state": state, "message": message})
        saved = self._store.plugin_save(
            profile_id, key, kind="catalog", name=lang_entry["label"], description=lang_entry["summary"], source="",
            skills=parts_skills, connectors=parts_conns, added_skills=added_skills, added_connectors=added_conns, notes=[],
        )
        return {"id": saved["id"], "key": key, "skills": skills_out, "connectors": conns_out}

    # --------------------------------------------------------------------- Import

    def preview_import(self, profile_id: str, data: bytes, fallback_name: str, source: str) -> dict[str, Any]:
        found = parse_plugin_zip(data, fallback_name)
        if not found["skills"] and not found["servers"]:
            raise PluginError(tr("In diesem Plugin gibt es weder Skills noch Server-Adressen, die sich übernehmen lassen."))
        have = {r["name"]: r["origin"] for r in self._store.skill_list(profile_id)}
        urls = {v["url"].rstrip("/") for v in self._connector_views(profile_id) if v.get("url")}
        skills = []
        for item in found["skills"]:
            pkg = item["package"]
            skills.append({
                "name": pkg.name, "description": pkg.description, "files": len(pkg.files), "size": pkg.size, "warnings": pkg.warnings[:5],
                "state": "taken" if have.get(pkg.name, "imported") != "imported" else "replaces" if pkg.name in have else "new",
            })
        servers = [{**s, "present": s["url"].rstrip("/") in urls} for s in found["servers"]]
        return {
            "name": found["name"], "description": found["description"], "version": found["version"], "source": source,
            "skills": skills, "servers": servers, "skipped": found["skipped"], "notes": found["notes"],
            "can_connectors": self._connectors.can_create(profile_id)["private"],
            "replaces": bool(self._store.plugin_by_key(profile_id, self.import_key(source))),
        }

    @staticmethod
    def import_key(source: str) -> str:
        """Schlüssel eines importierten Plugins: Quelle ohne den Commit (neuere Fassungen ersetzen die alte)."""
        return "import:" + re.sub(r"@[0-9a-f]{7}", "", source).strip()[:150]

    async def commit_import(
        self, profile_id: str, data: bytes, fallback_name: str, source: str, skill_names: list[str], servers: list[dict],
    ) -> dict[str, Any]:
        key = self.import_key(source)
        record = self._store.plugin_by_key(profile_id, key)
        if not record and self._store.plugin_count(profile_id) >= MAX_PLUGINS:
            raise PluginError(tr("Es sind höchstens {n} Plugins je Person möglich.", n=MAX_PLUGINS))
        found = parse_plugin_zip(data, fallback_name)
        wanted = set(skill_names)
        added_skills = list(record["added_skills"]) if record else []
        added_conns = list(record["added_connectors"]) if record else []
        skills_out, parts_skills = [], []
        for item in found["skills"]:
            pkg = item["package"]
            if pkg.name not in wanted:
                continue
            state, fresh = self._add_skill(profile_id, pkg, "imported")
            if fresh and pkg.name not in added_skills:
                added_skills.append(pkg.name)
            if state in ("added", "present"):
                parts_skills.append({"name": pkg.name})
            skills_out.append({"name": pkg.name, "state": "added" if state == "present" else state})
        known = {s["name"]: s for s in found["servers"]}
        urls = {v["url"].rstrip("/"): v for v in self._connector_views(profile_id) if v.get("url")}
        conns_out, parts_conns = [], []
        for chosen in servers[:MAX_IMPORT_SERVERS]:
            base = known.get(str(chosen.get("name") or ""))
            if base is None:
                continue
            auth = chosen.get("auth") if chosen.get("auth") in AUTH_CHOICES else base["auth"]
            if base["url"].rstrip("/") in urls:
                view = urls[base["url"].rstrip("/")]
                parts_conns.append({"name": view["name"], "id": view["id"], "catalog_id": view.get("catalog_id") or ""})
                conns_out.append({"name": base["name"], "state": "present", "message": ""})
                continue
            payload: dict[str, Any] = {"name": base["name"], "url": base["url"], "auth": auth, "description": tr("Aus dem Plugin {name}", name=found["name"])[:300]}
            if auth == "header":
                payload["header_name"] = base["header_name"] or "X-API-Key"
            if base["catalog_id"]:
                payload["catalog_id"] = base["catalog_id"]
            state, message, made = await self._add_connector(profile_id, payload)
            if made is not None:
                added_conns.append(made)
                parts_conns.append({"name": base["name"], "id": made, "catalog_id": base["catalog_id"]})
            conns_out.append({"name": base["name"], "state": state, "message": message})
        saved = self._store.plugin_save(
            profile_id, key, kind="imported", name=found["name"], description=found["description"], source=source,
            skills=parts_skills, connectors=parts_conns, added_skills=added_skills, added_connectors=added_conns, notes=found["notes"],
        )
        return {"id": saved["id"], "skills": skills_out, "connectors": conns_out}

    # --------------------------------------------------------------------- Entfernen

    def remove(self, profile_id: str, plugin_id: int) -> dict[str, int]:
        record = self._store.plugin_get(profile_id, plugin_id)
        if record is None:
            raise PluginError(tr("Nicht gefunden"), 404)
        skills = connectors = 0
        rows = {r["name"]: r for r in self._store.skill_list(profile_id)}
        for name in record["added_skills"]:
            row = rows.get(name)
            if row and row["origin"] in ("recommended", "imported") and self._store.skill_delete(profile_id, row["id"]):
                skills += 1
        for connector_id in record["added_connectors"]:
            try:
                self._connectors.delete(profile_id, int(connector_id))
                connectors += 1
            except (ConnectorError, ValueError):
                continue
        self._store.plugin_delete(profile_id, plugin_id)
        return {"skills": skills, "connectors": connectors}
