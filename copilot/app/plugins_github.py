"""Claude-Plugin von einem öffentlichen GitHub-Link holen (nur Skills und Server-Adressen).

Ein Plugin für Claude Code/Cowork ist ein Ordner mit ``.claude-plugin/plugin.json``, ``skills/<name>/SKILL.md``,
``.mcp.json`` und weiteren Teilen (``commands/``, ``agents/``, ``hooks/``). Hier werden nur die Skills, die Beschreibung
(``plugin.json``) und ``.mcp.json`` geholt; alles andere (Befehle, Unteragenten, Hooks, Skripte) wird nie geladen und der Person nur
genannt. Der Abruf läuft wie beim Skill-Import anonym, nur über ``api.github.com`` und ``raw.githubusercontent.com`` und immer von
einem festen Commit.
"""
from __future__ import annotations

import asyncio
import io
import zipfile
from dataclasses import dataclass, field
from urllib.parse import quote

import httpx

from . import skills as sk
from . import skills_github as sg
from .i18n import tr

MAX_FILES = 400
MAX_BYTES = 6 * 1024 * 1024
MANIFEST = ".claude-plugin/plugin.json"
MCP_FILE = ".mcp.json"
IGNORED_FOLDERS = ("commands", "agents", "hooks", "scripts", "output-styles", "lsp", "monitors")


class PluginGithubError(sk.SkillError):
    pass


@dataclass
class FetchedPlugin:
    data: bytes  # ZIP: plugin.json, .mcp.json und skills/<name>/...
    source: str  # besitzer/repo@abcdef1 ordner
    skipped: list[dict] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)  # Teile, die nicht übernommen werden (Ordnername und Anzahl Dateien)


def _prefixed(path: str, prefix: str) -> str | None:
    return path[len(prefix):] if path.startswith(prefix) else None


def _roots(blobs: set[str]) -> set[str]:
    return {p[: -len(MANIFEST)].rstrip("/") for p in blobs if p == MANIFEST or p.endswith("/" + MANIFEST)}


def _has_parts(blobs: set[str], root: str) -> bool:
    prefix = root + "/" if root else ""
    return prefix + MCP_FILE in blobs or any(b.startswith(prefix + "skills/") and b.endswith("/SKILL.md") for b in blobs)


def choose_root(tree: list[dict], path: str, blob: bool) -> str:
    """Plugin-Ordner bestimmen: der Link selbst oder genau ein Unterordner mit ``plugin.json``."""
    blobs = {i["path"] for i in tree if i.get("type") == "blob"}
    path = path.strip("/")
    if blob:
        path = path.rsplit("/", 1)[0] if "/" in path else ""
    roots = _roots(blobs)
    if path in roots or _has_parts(blobs, path):
        return path

    def depth(root: str) -> int:
        rel = root[len(path) + 1:] if path else root
        return rel.count("/") + 1 if rel else 0

    inside = sorted(r for r in roots if (not path or r.startswith(path + "/")) and depth(r) <= 2)
    if len(inside) == 1:
        return inside[0]
    if not inside:
        raise PluginGithubError(tr("In diesem Ordner liegt kein Plugin (es fehlt .claude-plugin/plugin.json). Gib den Link zu einem Plugin-Ordner an."))
    names = ", ".join(r.rsplit("/", 1)[-1] or "(Hauptordner)" for r in inside[:10])
    raise PluginGithubError(tr("Hier liegen mehrere Plugins ({names}). Gib den Link zu einem einzelnen Plugin-Ordner an.", names=names + (" …" if len(inside) > 10 else "")))


def select_files(tree: list[dict], root: str) -> tuple[list[dict], list[str]]:
    """Dateien, die geholt werden (Manifest, ``.mcp.json``, Skills), und die Liste der nicht übernommenen Teile."""
    prefix = root + "/" if root else ""
    wanted: list[dict] = []
    ignored: dict[str, int] = {}
    for item in tree:
        if item.get("type") != "blob":
            continue
        rel = _prefixed(item["path"], prefix)
        if rel is None:
            continue
        parts = rel.split("/")
        if rel in (MANIFEST, MCP_FILE):
            wanted.append(item)
        elif parts[0] == "skills" and len(parts) > 1:
            if not any(p.startswith(".") or p in sg.SKIP_PARTS for p in parts[1:]):
                wanted.append(item)
        elif parts[0] in IGNORED_FOLDERS:
            ignored[parts[0]] = ignored.get(parts[0], 0) + 1
    notes = [tr("{name}/ ({n} Dateien)", name=name, n=n) for name, n in sorted(ignored.items())]
    return wanted, notes


async def fetch(url: str, *, transport: httpx.AsyncBaseTransport | None = None) -> FetchedPlugin:
    target = sg.parse_url(url)
    try:
        async with httpx.AsyncClient(timeout=20.0, transport=transport or sg.TRANSPORT, follow_redirects=True) as client:
            sha, path = await sg._commit(client, target)
            response = await sg._get(client, f"{sg.API}/repos/{quote(target.owner)}/{quote(target.repo)}/git/trees/{sha}", params={"recursive": "1"})
            if response.status_code != 200:
                raise sg._fail(response)
            data = response.json()
            if data.get("truncated"):
                raise PluginGithubError(tr("Das Repository ist zu groß zum Durchsuchen. Gib den Link zu einem Plugin-Ordner an."))
            tree = [i for i in data.get("tree", []) if isinstance(i, dict) and isinstance(i.get("path"), str)]
            root = choose_root(tree, path, target.blob)
            wanted, ignored = select_files(tree, root)
            prefix = root + "/" if root else ""
            if not any(i["path"] == prefix + MANIFEST or i["path"].startswith(prefix + "skills/") or i["path"] == prefix + MCP_FILE for i in wanted):
                raise PluginGithubError(tr("In diesem Plugin gibt es weder Skills noch Server-Adressen."))
            if len(wanted) > MAX_FILES:
                raise PluginGithubError(tr("Das Plugin hat zu viele Dateien (mehr als {n}).", n=MAX_FILES))
            skipped: list[dict] = []
            keep = []
            for item in wanted:
                rel = item["path"][len(prefix):]
                if int(item.get("size") or 0) > sk.ZIP_MEMBER_BYTES:
                    skipped.append({"name": rel, "reason": tr("zu groß")})
                else:
                    keep.append(item)
            if sum(int(i.get("size") or 0) for i in keep) > MAX_BYTES:
                raise PluginGithubError(tr("Das Plugin ist zu groß (mehr als {mb} MB).", mb=MAX_BYTES // 1024 // 1024))
            gate = asyncio.Semaphore(6)

            async def load(item: dict) -> tuple[str, bytes]:
                async with gate:
                    got = await sg._get(client, f"{sg.RAW}/{quote(target.owner)}/{quote(target.repo)}/{sha}/{quote(item['path'])}", accept="*/*")
                if got.status_code != 200:
                    raise sg._fail(got)
                return item["path"][len(prefix):], got.content

            loaded = await asyncio.gather(*(load(i) for i in keep))
    except sg.SkillGithubError as exc:
        raise PluginGithubError(str(exc)) from None
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel, content in loaded:
            zf.writestr(rel, content)
    source = f"{target.owner}/{target.repo}@{sha[:7]}" + (f" {root}" if root else "")
    return FetchedPlugin(buffer.getvalue(), source, skipped, ignored)
