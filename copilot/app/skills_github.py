"""Skill von einem GitHub-Link holen (nur öffentliche Repositories, ohne das GitHub-Token des Add-ons).

Aus dem Link wird ein ZIP mit dem Skill-Ordner gebaut; danach läuft alles wie beim Hochladen (``skills.parse_upload``):
dieselbe Prüfung, dieselbe Vorschau, derselbe Status „importiert“ (= fremder Inhalt). Abgerufen werden ausschließlich
``api.github.com`` (Commit und Dateiliste) und ``raw.githubusercontent.com`` (Dateien); beide Anfragen sind anonym, damit
über den Link nichts erreichbar ist, was nur das Token des Add-ons sehen dürfte. Der Commit wird einmal aufgelöst und für
alle Dateien festgehalten, damit eine Änderung während des Abrufs nichts vermischt.
"""
from __future__ import annotations

import asyncio
import io
import re
import zipfile
from dataclasses import dataclass
from urllib.parse import quote, unquote, urlsplit

import httpx

from . import skills as sk
from .i18n import tr

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
ALLOWED_HOSTS = {"api.github.com", "raw.githubusercontent.com"}
PART = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
MAX_FILES = 120  # so viele Dateien darf der Skill-Ordner höchstens haben
MAX_BYTES = 3 * 1024 * 1024  # Rohdaten aller Dateien zusammen (unter dem Hochlade-Limit)
SKIP_PARTS = {"node_modules", "evals", "__pycache__"}
TRANSPORT: httpx.AsyncBaseTransport | None = None  # nur für Tests
REF_TRIES = 4  # so viele Schreibweisen für den Zweignamen (er darf „/“ enthalten) werden höchstens probiert


@dataclass
class Fetched:
    data: bytes  # ZIP mit dem Skill-Ordner
    source: str  # besitzer/repo@abcdef1 ordner
    skipped: list[dict]


@dataclass
class Target:
    owner: str
    repo: str
    rest: list[str]  # Pfadteile hinter /tree/ oder /blob/ (Zweig und Ordner); leer = Standardzweig, Hauptordner
    blob: bool = False


def parse_url(text: str) -> Target:
    """``https://github.com/<Besitzer>/<Repo>[/tree|blob/<Zweig>/<Pfad>]`` oder ``<Besitzer>/<Repo>``."""
    raw = (text or "").strip()
    bad = SkillGithubError(tr("Das ist kein GitHub-Link. Beispiel: https://github.com/besitzer/repo/tree/main/skills/name"))
    if not raw or len(raw) > 500 or any(c.isspace() for c in raw):
        raise bad
    if re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", raw):
        raw = "https://github.com/" + raw
    parts = urlsplit(raw)
    if parts.scheme != "https" or (parts.hostname or "").lower() not in ("github.com", "www.github.com") or parts.username or parts.port:
        raise bad
    segments = [unquote(s) for s in parts.path.split("/") if s]
    if len(segments) < 2:
        raise bad
    owner, repo = segments[0], segments[1].removesuffix(".git")
    if not PART.match(owner) or not PART.match(repo):
        raise bad
    rest = segments[2:]
    if not rest:
        return Target(owner, repo, [])
    if rest[0] not in ("tree", "blob") or len(rest) < 2:
        raise bad
    if any(p in ("", ".", "..") or "\\" in p or "\x00" in p for p in rest[1:]):
        raise bad
    return Target(owner, repo, rest[1:], blob=rest[0] == "blob")


class SkillGithubError(sk.SkillError):
    pass


def _check(response: httpx.Response) -> None:
    if response.url.host not in ALLOWED_HOSTS:
        raise SkillGithubError(tr("GitHub hat auf eine andere Adresse umgeleitet. Das wird nicht verfolgt."))


def _fail(response: httpx.Response) -> SkillGithubError:
    status = response.status_code
    if status in (403, 429):
        return SkillGithubError(tr("GitHub begrenzt gerade die Anfragen. Versuch es in einigen Minuten noch einmal."))
    if status in (404, 410, 422):
        return SkillGithubError(tr("Dort gibt es nichts zu holen. Das Repository muss öffentlich sein und der Link auf einen vorhandenen Zweig und Ordner zeigen."))
    return SkillGithubError(tr("GitHub antwortet mit einem Fehler ({status}).", status=status))


async def _get(client: httpx.AsyncClient, url: str, *, accept: str = "application/vnd.github+json", params: dict | None = None) -> httpx.Response:
    try:
        response = await client.get(url, params=params, headers={"Accept": accept, "User-Agent": "ha-copilot-addon", "X-GitHub-Api-Version": "2022-11-28"})
    except httpx.TimeoutException:
        raise SkillGithubError(tr("GitHub antwortet nicht (Zeitüberschreitung).")) from None
    except httpx.HTTPError:
        raise SkillGithubError(tr("GitHub ist nicht erreichbar.")) from None
    _check(response)
    return response


async def _commit(client: httpx.AsyncClient, target: Target) -> tuple[str, str]:
    """Commit (voller Hash) und Pfad im Repository. Der Zweigname darf „/“ enthalten: es werden Möglichkeiten der Reihe nach probiert."""
    base = f"{API}/repos/{quote(target.owner)}/{quote(target.repo)}/commits"
    if not target.rest:
        candidates = [("HEAD", [])]
    else:
        candidates = [("/".join(target.rest[:i]), target.rest[i:]) for i in range(1, min(len(target.rest), REF_TRIES) + 1)]
    last: SkillGithubError | None = None
    for ref, path in candidates:
        response = await _get(client, f"{base}/{quote(ref, safe='/')}", accept="application/vnd.github.sha")
        if response.status_code == 200 and re.fullmatch(r"[0-9a-f]{40}", response.text.strip()):
            return response.text.strip(), "/".join(path)
        last = _fail(response)
        if response.status_code in (403, 429):
            break
    raise last or SkillGithubError(tr("Dort gibt es nichts zu holen. Das Repository muss öffentlich sein und der Link auf einen vorhandenen Zweig und Ordner zeigen."))


def _choose(tree: list[dict], path: str, blob: bool) -> str:
    """Ordner des Skills bestimmen: der Link selbst oder, wenn dort keine SKILL.md liegt, genau ein Unterordner mit SKILL.md."""
    marks = {item["path"][: -len("SKILL.md")].rstrip("/") for item in tree if item.get("type") == "blob" and (item["path"] == "SKILL.md" or item["path"].endswith("/SKILL.md"))}
    path = path.strip("/")
    if blob:  # Link auf eine Datei: gemeint ist ihr Ordner
        path = path.rsplit("/", 1)[0] if "/" in path else ""
    if path in marks:
        return path
    def depth(mark: str) -> int:  # wie viele Ordner unter dem Link liegt das Skill (Hauptordner = 0)
        rel = mark[len(path) + 1:] if path else mark
        return rel.count("/") + 1 if rel else 0

    inside = sorted(m for m in marks if (not path or m.startswith(path + "/")) and depth(m) <= 2)
    if len(inside) == 1:
        return inside[0]
    if not inside:
        raise SkillGithubError(tr("In diesem Ordner liegt keine SKILL.md. Gib den Link zu einem Skill-Ordner an."))
    names = ", ".join(m.rsplit("/", 1)[-1] or "(Hauptordner)" for m in inside[:10])
    raise SkillGithubError(tr("Hier liegen mehrere Skills ({names}). Gib den Link zu einem einzelnen Skill-Ordner an.", names=names + (" …" if len(inside) > 10 else "")))


async def fetch(url: str, *, transport: httpx.AsyncBaseTransport | None = None) -> Fetched:
    """Skill-Ordner als ZIP samt Quellenangabe holen."""
    target = parse_url(url)
    async with httpx.AsyncClient(timeout=20.0, transport=transport or TRANSPORT, follow_redirects=True) as client:
        sha, path = await _commit(client, target)
        response = await _get(client, f"{API}/repos/{quote(target.owner)}/{quote(target.repo)}/git/trees/{sha}", params={"recursive": "1"})
        if response.status_code != 200:
            raise _fail(response)
        data = response.json()
        if data.get("truncated"):
            raise SkillGithubError(tr("Das Repository ist zu groß zum Durchsuchen. Gib den Link zu einem Skill-Ordner an."))
        tree = [i for i in data.get("tree", []) if isinstance(i, dict) and isinstance(i.get("path"), str)]
        folder = _choose(tree, path, target.blob)
        prefix = folder + "/" if folder else ""
        files = [
            i for i in tree
            if i.get("type") == "blob" and i["path"].startswith(prefix)
            and not any(p.startswith(".") or p in SKIP_PARTS for p in i["path"][len(prefix):].split("/"))
        ]
        if len(files) > MAX_FILES:
            raise SkillGithubError(tr("Der Ordner hat zu viele Dateien. Gib den Link zu einem einzelnen Skill-Ordner an."))
        skipped: list[dict] = []
        wanted = []
        for item in files:
            rel = item["path"][len(prefix):]
            if int(item.get("size") or 0) > sk.ZIP_MEMBER_BYTES:
                skipped.append({"name": rel, "reason": tr("zu groß")})
            else:
                wanted.append(item)
        if sum(int(i.get("size") or 0) for i in wanted) > MAX_BYTES:
            raise SkillGithubError(tr("Der Ordner ist zu groß (mehr als {mb} MB).", mb=MAX_BYTES // 1024 // 1024))
        gate = asyncio.Semaphore(6)

        async def load(item: dict) -> tuple[str, bytes]:
            async with gate:
                response = await _get(client, f"{RAW}/{quote(target.owner)}/{quote(target.repo)}/{sha}/{quote(item['path'])}", accept="*/*")
            if response.status_code != 200:
                raise _fail(response)
            return item["path"][len(prefix):], response.content

        loaded = await asyncio.gather(*(load(i) for i in wanted))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel, content in loaded:
            zf.writestr(rel, content)
    source = f"{target.owner}/{target.repo}@{sha[:7]}" + (f" {folder}" if folder else "")
    return Fetched(buffer.getvalue(), source, skipped)
