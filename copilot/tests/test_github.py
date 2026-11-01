"""GitHub: Zugriff über ein simuliertes GitHub (httpx.MockTransport) – Stufen, Freigabeliste, Rückfragen, Commits, Sperren."""
import asyncio
import base64
import json
import re

import httpx
import pytest

from app.config import ConfigError, parse_settings
from app.github_api import GithubApi, GithubError, RepoPolicy, parse_repo
from app.github_tools import GithubToolbox
from app.ha_tools import ToolError
from app.main import build_ingress_app
from conftest import ADM01, DORA, RAW
from test_background_run import asgi, jget, new_chat, sse

TOKEN = "ghp_geheimes_testtoken_123"


def run(coro):
    return asyncio.run(coro)


# ----------------------------------------------------------------------- simuliertes GitHub

class FakeGithub:
    """Minimales GitHub: Repositories mit Zweigen (Commit → Dateien), Git-Data-API, Issues, Pull Requests."""

    def __init__(self):
        self.calls: list[tuple[str, str, object]] = []
        self.counter = 0
        self.blobs: dict[str, bytes] = {}
        self.trees: dict[str, dict] = {}
        self.commits: dict[str, dict] = {}
        self.refs: dict[str, dict[str, str]] = {}  # repo → {branch: commit sha}
        self.repos: dict[str, dict] = {}
        self.fail: dict[str, tuple[int, dict]] = {}
        self.add_repo("dora/smarthome", {"README.md": b"# Smarthome\nzeile 2\n", "src/a.py": b"print('a')\n", "bin/x.dat": b"\x00\x01\x02"}, private=True)
        self.add_repo("dora/andere", {"x.txt": b"x"}, private=False)
        self.add_repo("fremd/geheim", {"s.txt": b"nein"}, private=True)

    def _id(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}{self.counter:0>{40 - len(prefix)}x}"

    def add_repo(self, full: str, files: dict[str, bytes], private: bool = True) -> None:
        tree = self._id("a")
        self.trees[tree] = dict(files)
        commit = self._id("c")
        self.commits[commit] = {"tree": tree, "parents": [], "message": "Start"}
        self.refs[full] = {"main": commit}
        self.repos[full] = {"full_name": full, "private": private, "default_branch": "main", "description": f"Repo {full}", "archived": False,
                            "pushed_at": "2026-10-01T10:00:00Z", "html_url": f"https://github.com/{full}", "open_issues_count": 2, "size": 5,
                            "permissions": {"admin": True, "push": True, "pull": True}, "topics": [], "license": {"spdx_id": "MIT"}}

    def files_at(self, repo: str, branch: str) -> dict[str, bytes]:
        return self.trees[self.commits[self.refs[repo][branch]]["tree"]]

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        path = request.url.path
        self.calls.append((request.method, path, body))
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        for pattern, (status, payload) in self.fail.items():
            if re.search(pattern, request.method + " " + path):
                return httpx.Response(status, json=payload)
        return self.route(request.method, path, dict(request.url.params), body)

    def route(self, method: str, path: str, params: dict, body):  # noqa: C901 – eine Weiche, absichtlich flach
        if path == "/user":
            return httpx.Response(200, json={"login": "dora"})
        if path == "/user/repos" and method == "GET":
            return httpx.Response(200, json=[r for r in self.repos.values() if not r["full_name"].startswith("fremd/")] + [self.repos["fremd/geheim"]])
        if path == "/user/repos" and method == "POST":
            full = f"dora/{body['name']}"
            self.add_repo(full, {}, private=body["private"])
            return httpx.Response(201, json=self.repos[full])
        m = re.match(r"^/repos/([^/]+/[^/]+)(/.*)?$", path)
        if not m:
            return httpx.Response(404, json={"message": "Not Found"})
        repo, rest = m.group(1), m.group(2) or ""
        if repo not in self.repos:
            return httpx.Response(404, json={"message": "Not Found"})
        if rest == "" and method == "GET":
            return httpx.Response(200, json=self.repos[repo])
        if rest == "/languages":
            return httpx.Response(200, json={"Python": 100})
        if rest.startswith("/contents/"):
            name = rest[len("/contents/"):]
            files = self.files_at(repo, params.get("ref") or "main")
            if name in files:
                return httpx.Response(200, json={"type": "file", "size": len(files[name]), "encoding": "base64", "content": base64.b64encode(files[name]).decode()})
            kids = sorted({p.split("/")[0] if "/" in p[len(name) + 1:] or True else p for p in files if p.startswith(name.rstrip("/") + "/")} if name else set())
            if name == "":
                kids = sorted({p.split("/")[0] for p in files})
                return httpx.Response(200, json=[{"name": k, "type": "file" if k in files else "dir", "size": len(files.get(k, b""))} for k in kids])
            sub = sorted({p[len(name) + 1:].split("/")[0] for p in files if p.startswith(name + "/")})
            if sub:
                return httpx.Response(200, json=[{"name": k, "type": "file", "size": 1} for k in sub])
            return httpx.Response(404, json={"message": "Not Found"})
        if rest.startswith("/git/ref/heads/"):
            branch = rest[len("/git/ref/heads/"):]
            if branch in self.refs[repo]:
                return httpx.Response(200, json={"object": {"sha": self.refs[repo][branch]}})
            return httpx.Response(404, json={"message": "Not Found"})
        if rest.startswith("/git/commits/") and method == "GET":
            c = self.commits[rest.rsplit("/", 1)[1]]
            return httpx.Response(200, json={"tree": {"sha": c["tree"]}})
        if rest == "/git/blobs":
            sha = self._id("b")
            self.blobs[sha] = base64.b64decode(body["content"])
            return httpx.Response(201, json={"sha": sha})
        if rest == "/git/trees":
            files = dict(self.trees[body["base_tree"]])
            for e in body["tree"]:
                if e["sha"] is None:
                    files.pop(e["path"], None)
                else:
                    files[e["path"]] = self.blobs[e["sha"]]
            sha = self._id("a")
            self.trees[sha] = files
            return httpx.Response(201, json={"sha": sha})
        if rest == "/git/commits":
            sha = self._id("c")
            self.commits[sha] = {"tree": body["tree"], "parents": body["parents"], "message": body["message"]}
            return httpx.Response(201, json={"sha": sha})
        if rest == "/git/refs":
            self.refs[repo][body["ref"].removeprefix("refs/heads/")] = body["sha"]
            return httpx.Response(201, json={})
        if rest.startswith("/git/refs/heads/") and method == "PATCH":
            self.refs[repo][rest[len("/git/refs/heads/"):]] = body["sha"]
            return httpx.Response(200, json={})
        if rest == "/pulls" and method == "POST":
            return httpx.Response(201, json={"number": 7, "html_url": f"https://github.com/{repo}/pull/7"})
        if rest == "/pulls" and method == "GET":
            return httpx.Response(200, json=[{"number": 7, "state": "open", "title": "Mein PR", "head": {"ref": "neu"}, "base": {"ref": "main"}, "user": {"login": "dora"}}])
        if re.match(r"^/pulls/\d+/merge$", rest):
            return httpx.Response(200, json={"sha": "f" * 40, "merged": True})
        if rest == "/issues" and method == "POST":
            return httpx.Response(201, json={"number": 3, "html_url": f"https://github.com/{repo}/issues/3"})
        if rest == "/issues" and method == "GET":
            return httpx.Response(200, json=[{"number": 3, "state": "open", "title": "Fehler", "user": {"login": "x"}, "updated_at": "2026-10-02T00:00:00Z"}])
        if re.match(r"^/issues/\d+/comments$", rest) and method == "POST":
            return httpx.Response(201, json={"html_url": f"https://github.com/{repo}/issues/3#c1"})
        if re.match(r"^/issues/\d+$", rest) and method == "PATCH":
            return httpx.Response(200, json={"html_url": f"https://github.com/{repo}/issues/3"})
        if rest == "/labels":
            return httpx.Response(200, json=[{"name": "bug"}]) if method == "GET" else httpx.Response(201, json={"name": body["name"]})
        return httpx.Response(200, json={})


class Chat:
    """Ersatz für den Chat: sammelt Ereignisse, beantwortet Rückfragen mit einer festen Antwort."""

    def __init__(self, answer="allow"):
        self.answer = answer
        self.events: list[dict] = []
        self.asked: list[tuple[str, str, bool]] = []
        self.allowed_chat = False
        self.touched = False  # „es wurde schon etwas gelesen/gelöscht“ → erzwingt Rückfragen
        self.attachments = False
        self.n = 0

    async def ask(self, label, details, offer_chat):
        self.asked.append((label, details, offer_chat))
        return self.answer

    def next_id(self):
        self.n += 1
        return self.n


def toolbox(gh: FakeGithub, chat: Chat, level="write", repos=(), confirm=True, files=None):
    box = GithubToolbox(
        GithubApi(TOKEN, transport=gh.transport()), level,
        policy=RepoPolicy(repos), confirm_writes=confirm,
        force_confirm=lambda: chat.attachments or chat.touched,
        ask=chat.ask, record=chat.events.append,
        chat_allowed=lambda: chat.allowed_chat, allow_chat=lambda: setattr(chat, "allowed_chat", True),
        next_id=chat.next_id, file_bytes=lambda name: (files or {}).get(name),
    )
    return box, {s.name: s.handler for s in box.specs()}


# ------------------------------------------------------------------------- Grundbausteine

def test_parse_repo_accepts_names_and_urls():
    assert parse_repo("dora/smarthome") == "dora/smarthome"
    assert parse_repo("https://github.com/dora/smarthome.git") == "dora/smarthome"
    assert parse_repo("github.com/dora/smarthome/tree/main/src") == "dora/smarthome"
    for bad in ("", "nur-name", "a/b/c", "../x", "a/..", "a b/c"):
        with pytest.raises(ValueError):
            parse_repo(bad)


def test_repo_policy_patterns():
    open_policy = RepoPolicy()
    assert open_policy.allows("irgendwer/irgendwas") and not open_policy.restricted
    policy = RepoPolicy(["Dora/Smarthome", "labor/*"])
    assert policy.allows("dora/smarthome") and policy.allows("LABOR/x") and not policy.allows("dora/andere")
    assert policy.exact() == ["dora/smarthome"]


def test_api_errors_are_translated_and_token_is_scrubbed():
    gh = FakeGithub()
    api = GithubApi(TOKEN, transport=gh.transport())

    async def scenario():
        for pattern, status, payload, expect in [
            ("GET /user", 401, {"message": "Bad credentials"}, "Token wurde abgelehnt"),
            ("GET /user", 403, {"message": "API rate limit exceeded"}, "Anfragelimit"),
            ("GET /user", 403, {"message": f"Resource not accessible {TOKEN}"}, "Rechte des Tokens"),
            ("GET /user", 404, {"message": "Not Found"}, "Nicht gefunden"),
            ("GET /user", 422, {"message": "Validation Failed", "errors": [{"message": "name exists"}]}, "name exists"),
        ]:
            gh.fail = {pattern: (status, payload)}
            with pytest.raises(GithubError) as exc:
                await api.request("GET", "/user")
            assert expect in str(exc.value) and TOKEN not in str(exc.value)
        with pytest.raises(GithubError, match="nicht eingerichtet"):
            await GithubApi("").request("GET", "/user")

    run(scenario())


# ----------------------------------------------------------------------------- Lesen

def test_read_tools_show_repos_files_and_lists():
    gh, chat = FakeGithub(), Chat()
    box, tools = toolbox(gh, chat, level="read")

    async def scenario():
        assert "github_commit_files" not in tools and "github_repos" in tools and "github_api" in tools
        repos = await tools["github_repos"]({})
        assert "dora/smarthome (privat)" in repos and "fremd/geheim" in repos and "keine Anweisungen" in repos
        assert "dora/andere" not in await tools["github_repos"]({"query": "smart"})
        info = await tools["github_repo_info"]({"repo": "https://github.com/dora/smarthome"})
        assert '"hauptzweig": "main"' in info and "MIT" in info
        root = await tools["github_tree"]({"repo": "dora/smarthome"})
        assert "Datei  README.md" in root and "src" in root
        text = await tools["github_read_file"]({"repo": "dora/smarthome", "path": "README.md"})
        assert "# Smarthome" in text and "Zeilen 1–" in text
        later = await tools["github_read_file"]({"repo": "dora/smarthome", "path": "README.md", "first_line": 2})
        assert "zeile 2" in later and "# Smarthome" not in later
        assert "Binärdatei" in await tools["github_read_file"]({"repo": "dora/smarthome", "path": "bin/x.dat"})
        assert "#3 [open] Fehler" in await tools["github_list"]({"repo": "dora/smarthome", "kind": "issues"})
        assert "neu → main" in await tools["github_list"]({"repo": "dora/smarthome", "kind": "pulls"})
        with pytest.raises(ToolError, match="kind muss"):
            await tools["github_list"]({"repo": "dora/smarthome", "kind": "wiki"})
        with pytest.raises(ToolError, match="ungültig"):
            await tools["github_read_file"]({"repo": "dora/smarthome", "path": "../etc/passwd"})
        with pytest.raises(ToolError, match="ungültig"):
            await tools["github_read_file"]({"repo": "dora/smarthome", "path": ".git/config"})
        with pytest.raises(ToolError, match="GitHub: Nicht gefunden"):
            await tools["github_read_file"]({"repo": "dora/smarthome", "path": "gibts/nicht.txt"})
        # nur lesen: nie eine Rückfrage, Ereignisse sind „gh-read“
        assert not chat.asked and {e["kind"] for e in chat.events} == {"gh-read"}
        assert {e["status"] for e in chat.events} == {"running", "ok", "error"}

    run(scenario())


def test_level_none_offers_nothing_and_read_cannot_write():
    gh, chat = FakeGithub(), Chat()
    assert GithubToolbox(GithubApi(TOKEN), "none", policy=RepoPolicy(), confirm_writes=True, force_confirm=lambda: False, ask=chat.ask,
                         record=chat.events.append, chat_allowed=lambda: False, allow_chat=lambda: None, next_id=chat.next_id).specs() == []
    box, tools = toolbox(gh, chat, level="read")

    async def scenario():
        with pytest.raises(ToolError, match="Berechtigung"):
            await box.commit_files({"repo": "dora/smarthome", "message": "x", "files": [{"path": "a", "content": "b"}]})
        with pytest.raises(ToolError, match="Berechtigung"):
            await tools["github_api"]({"method": "POST", "path": "/repos/dora/smarthome/labels", "body": {"name": "x"}})
        assert not any(m != "GET" for m, _p, _b in gh.calls)

    run(scenario())


def test_allow_list_limits_every_tool():
    gh, chat = FakeGithub(), Chat()
    box, tools = toolbox(gh, chat, level="write", repos=["dora/smarthome"])

    async def scenario():
        rows = await tools["github_repos"]({})
        assert "dora/smarthome" in rows and "geheim" not in rows and "andere" not in rows
        for name, args in [
            ("github_repo_info", {"repo": "fremd/geheim"}),
            ("github_read_file", {"repo": "fremd/geheim", "path": "s.txt"}),
            ("github_commit_files", {"repo": "fremd/geheim", "message": "m", "files": [{"path": "a", "content": "b"}]}),
            ("github_api", {"method": "GET", "path": "/repos/fremd/geheim/contents/s.txt"}),
            ("github_api", {"method": "GET", "path": "/orgs/fremd/repos"}),
            ("github_create_repo", {"name": "neu", "org": "fremd"}),
        ]:
            with pytest.raises(ToolError, match="Freigabeliste|nicht zugegriffen|Pfade unter"):
                await tools[name](args)
        assert not any("fremd" in p for _m, p, _b in gh.calls)
        assert not chat.asked

    run(scenario())


# ------------------------------------------------------------------------ Commits

def test_commit_to_new_branch_asks_once_and_writes_atomically():
    gh, chat = FakeGithub(), Chat()
    box, tools = toolbox(gh, chat)

    async def scenario():
        out = await tools["github_commit_files"]({
            "repo": "dora/smarthome", "message": "Skript ergänzen\n\nLänger", "branch": "feature/skript", "create_branch_from": "main",
            "files": [{"path": "tools/run.ps1", "content": "Write-Host 'Hallo'", "executable": True}, {"path": "src/a.py", "delete": True}, {"path": "docs/n.md", "content": "Ä"}],
        })
        assert "Zweig neu angelegt" in out and "https://github.com/dora/smarthome/commit/" in out
        files = gh.files_at("dora/smarthome", "feature/skript")
        assert files["tools/run.ps1"] == b"Write-Host 'Hallo'" and files["docs/n.md"] == "Ä".encode() and "src/a.py" not in files and "README.md" in files
        assert "src/a.py" in gh.files_at("dora/smarthome", "main")  # Hauptzweig unberührt
        label, details, offer_chat = chat.asked[0]
        assert "feature/skript" in label and "löschen: src/a.py" in details and "schreiben: tools/run.ps1" in details and offer_chat is True
        tree_call = next(b for m, p, b in gh.calls if p.endswith("/git/trees"))
        assert {e["path"]: e["mode"] for e in tree_call["tree"]}["tools/run.ps1"] == "100755"
        done = chat.events[-1]
        assert done["status"] == "ok" and done["kind"] == "gh-write" and done["link"].startswith("https://github.com/dora/smarthome/commit/")

    run(scenario())


def test_commit_on_default_branch_and_workflows_always_ask_even_after_allow_chat():
    gh, chat = FakeGithub(), Chat(answer="allow_chat")
    box, tools = toolbox(gh, chat)

    async def scenario():
        await tools["github_commit_files"]({"repo": "dora/smarthome", "message": "Direkt", "files": [{"path": "a.txt", "content": "1"}]})
        assert chat.asked[-1][2] is False and not chat.allowed_chat  # Hauptzweig: kein „immer zulassen“
        assert gh.files_at("dora/smarthome", "main")["a.txt"] == b"1"
        await tools["github_commit_files"]({"repo": "dora/smarthome", "message": "CI", "branch": "ci", "create_branch_from": "main",
                                            "files": [{"path": ".github/workflows/t.yml", "content": "on: push"}]})
        assert len(chat.asked) == 2 and "Workflow-Dateien" in chat.asked[-1][1] and chat.asked[-1][2] is False
        # normaler Zweig: „in diesem Chat immer zulassen“ gilt danach für unkritische Änderungen
        await tools["github_commit_files"]({"repo": "dora/smarthome", "message": "Weiter", "branch": "ci", "files": [{"path": "b.txt", "content": "2"}]})
        assert len(chat.asked) == 3 and chat.allowed_chat
        await tools["github_commit_files"]({"repo": "dora/smarthome", "message": "Noch mehr", "branch": "ci", "files": [{"path": "c.txt", "content": "3"}]})
        assert len(chat.asked) == 3  # keine neue Rückfrage
        await tools["github_commit_files"]({"repo": "dora/smarthome", "message": "Wieder Haupt", "files": [{"path": "d.txt", "content": "4"}]})
        assert len(chat.asked) == 4

    run(scenario())


def test_denied_commit_changes_nothing():
    gh, chat = FakeGithub(), Chat(answer="deny")
    box, tools = toolbox(gh, chat)

    async def scenario():
        out = await tools["github_commit_files"]({"repo": "dora/smarthome", "message": "Nein", "branch": "x", "create_branch_from": "main", "files": [{"path": "a", "content": "b"}]})
        assert "abgelehnt" in out
        assert "x" not in gh.refs["dora/smarthome"] and not any(m != "GET" for m, _p, _b in gh.calls)
        assert chat.events[-1]["status"] == "denied"

    run(scenario())


def test_always_allow_skips_ordinary_questions_but_not_sensitive_ones():
    gh, chat = FakeGithub(), Chat()
    box, tools = toolbox(gh, chat, confirm=False)

    async def scenario():
        await tools["github_commit_files"]({"repo": "dora/smarthome", "message": "Zweig", "branch": "t", "create_branch_from": "main", "files": [{"path": "a", "content": "b"}]})
        await tools["github_create_issue"]({"repo": "dora/smarthome", "title": "Hallo"})
        assert not chat.asked
        await tools["github_merge_pr"]({"repo": "dora/smarthome", "number": 7, "method": "squash"})
        await tools["github_create_repo"]({"name": "neues"})
        assert [a[0].split(":")[0] for a in chat.asked] == ["Pull Request mergen", "Repository anlegen"] and all(a[2] is False for a in chat.asked)

    run(scenario())


def test_attachments_or_foreign_content_force_questions():
    gh, chat = FakeGithub(), Chat()
    box, tools = toolbox(gh, chat, confirm=False)

    async def scenario():
        chat.attachments = True
        await tools["github_create_issue"]({"repo": "dora/smarthome", "title": "Mit Anhang"})
        assert len(chat.asked) == 1 and chat.asked[0][2] is False  # kein „immer zulassen“ möglich
        chat.attachments, chat.touched = False, True
        await tools["github_comment"]({"repo": "dora/smarthome", "number": 3, "body": "Hi"})
        assert len(chat.asked) == 2

    run(scenario())


def test_commit_validation():
    gh, chat = FakeGithub(), Chat()
    box, tools = toolbox(gh, chat)
    files = {"report.docx": b"PK-docx"}
    box2, tools2 = toolbox(gh, chat, files=files)

    async def scenario():
        base = {"repo": "dora/smarthome", "message": "m"}
        for files_arg, match in [
            ([], "files fehlt"),
            ([{"path": "../x", "content": "1"}], "Ungültiger Pfad"),
            ([{"path": "/abs", "content": "1"}], "Ungültiger Pfad"),
            ([{"path": ".git/config", "content": "1"}], "Ungültiger Pfad"),
            ([{"path": "a", "content": "1"}, {"path": "a", "content": "2"}], "doppelt"),
            ([{"path": "a"}], "fehlt content"),
            ([{"path": "a", "from_file": "nichts.bin"}], "gibt es in diesem Chat nicht"),
            ([{"path": "a", "content": "x" * (8 * 1024 * 1024 + 1)}], "zu groß"),
            ([{"path": f"f{i}", "content": "1"} for i in range(61)], "Höchstens 60"),
        ]:
            with pytest.raises(ToolError, match=match):
                await tools["github_commit_files"]({**base, "files": files_arg})
        with pytest.raises(ToolError, match="message fehlt"):
            await tools["github_commit_files"]({"repo": "dora/smarthome", "message": " ", "files": [{"path": "a", "content": "1"}]})
        with pytest.raises(ToolError, match="Name ungültig"):
            await tools["github_commit_files"]({**base, "branch": "a b", "files": [{"path": "a", "content": "1"}]})
        with pytest.raises(ToolError, match="gibt es nicht"):  # fehlender Zweig ohne create_branch_from
            await tools["github_commit_files"]({**base, "branch": "fehlt", "files": [{"path": "a", "content": "1"}]})
        with pytest.raises(ToolError, match="gibt es schon"):
            await tools["github_commit_files"]({**base, "branch": "main", "create_branch_from": "main", "files": [{"path": "a", "content": "1"}]})
        assert not chat.asked  # alles vor der Rückfrage abgewiesen
        # eine im Chat erzeugte oder angehängte Datei lässt sich einchecken
        await tools2["github_commit_files"]({**base, "branch": "doc", "create_branch_from": "main", "files": [{"path": "docs/report.docx", "from_file": "report.docx"}]})
        assert gh.files_at("dora/smarthome", "doc")["docs/report.docx"] == b"PK-docx"

    run(scenario())


# --------------------------------------------------------- Pull Requests, Issues, Repos

def test_pull_request_issue_comment_merge_and_new_repo():
    gh, chat = FakeGithub(), Chat()
    box, tools = toolbox(gh, chat)

    async def scenario():
        pr = await tools["github_create_pr"]({"repo": "dora/smarthome", "title": "Neu", "head": "feature/x", "body": "Text"})
        assert "#7" in pr and chat.events[-1]["link"] == "https://github.com/dora/smarthome/pull/7"
        post = next(b for m, p, b in gh.calls if m == "POST" and p.endswith("/pulls"))
        assert post["base"] == "main" and post["head"] == "feature/x"
        assert "#3" in await tools["github_create_issue"]({"repo": "dora/smarthome", "title": "Fehler", "labels": ["bug"]})
        assert "geschrieben" in await tools["github_comment"]({"repo": "dora/smarthome", "number": "#3", "body": "Danke"})
        assert "aktualisiert" in await tools["github_update_issue"]({"repo": "dora/smarthome", "number": 3, "state": "closed"})
        with pytest.raises(ToolError, match="Nichts zu ändern"):
            await tools["github_update_issue"]({"repo": "dora/smarthome", "number": 3})
        merged = await tools["github_merge_pr"]({"repo": "dora/smarthome", "number": 7})
        assert "gemergt (merge)" in merged and chat.asked[-1][2] is False
        made = await tools["github_create_repo"]({"name": "projekt", "description": "Neu"})
        assert "dora/projekt" in made and "privat" in made
        sent = next(b for m, p, b in gh.calls if m == "POST" and p == "/user/repos")
        assert sent["private"] is True and sent["auto_init"] is True
        public = await tools["github_create_repo"]({"name": "offen", "private": False})
        assert "öffentlich" in public and "ÖFFENTLICH" in chat.asked[-1][1]
        with pytest.raises(ToolError, match="name ungültig"):
            await tools["github_create_repo"]({"name": "../x"})
        with pytest.raises(ToolError, match="number"):
            await tools["github_merge_pr"]({"repo": "dora/smarthome", "number": "abc"})

    run(scenario())


# ------------------------------------------------------------------- Allgemeiner Zugang

def test_generic_api_get_and_post_with_questions():
    gh, chat = FakeGithub(), Chat()
    box, tools = toolbox(gh, chat)

    async def scenario():
        assert "bug" in await tools["github_api"]({"method": "GET", "path": "/repos/dora/smarthome/labels"})
        assert not chat.asked
        await tools["github_api"]({"method": "POST", "path": "/repos/dora/smarthome/labels", "body": {"name": "neu"}})
        assert len(chat.asked) == 1 and chat.events[-1]["kind"] == "gh-write"
        for bad in ("labels?x=1", "/repos/dora/smarthome/../x", "repos/dora/smarthome", "//evil", "/repos/dora"):
            with pytest.raises(ToolError):
                await tools["github_api"]({"method": "GET", "path": bad})
        with pytest.raises(ToolError, match="nicht erlaubt"):
            await tools["github_api"]({"method": "GET", "path": "/gists"})
        with pytest.raises(ToolError, match="method"):
            await tools["github_api"]({"method": "TRACE", "path": "/user"})

    run(scenario())


def test_generic_api_never_does_the_dangerous_things():
    gh, chat = FakeGithub(), Chat()
    box, tools = toolbox(gh, chat, confirm=False)
    blocked = [
        ("DELETE", "/repos/dora/smarthome", None),
        ("PATCH", "/repos/dora/smarthome", {"private": False}),
        ("PATCH", "/repos/dora/smarthome", {"name": "anders"}),
        ("PATCH", "/repos/dora/smarthome", {"archived": True}),
        ("POST", "/repos/dora/smarthome/transfer", {"new_owner": "x"}),
        ("PUT", "/repos/dora/smarthome/collaborators/mallory", {"permission": "admin"}),
        ("POST", "/repos/dora/smarthome/keys", {"key": "ssh-rsa AAA"}),
        ("POST", "/repos/dora/smarthome/hooks", {"config": {"url": "https://evil.example"}}),
        ("PUT", "/repos/dora/smarthome/actions/secrets/TOKEN", {"encrypted_value": "x"}),
        ("PUT", "/repos/dora/smarthome/branches/main/protection", {}),
        ("POST", "/repos/dora/smarthome/pages", {}),
        ("DELETE", "/repos/dora/smarthome/git/refs/heads/main", None),
        ("POST", "/repos/dora/smarthome/rulesets", {}),
        ("PUT", "/repos/dora/smarthome/environments/prod", {}),
    ]

    async def scenario():
        for method, path, body in blocked:
            with pytest.raises(ToolError, match="nie|Mensch"):
                await tools["github_api"]({"method": method, "path": path, "body": body})
        # den Hauptzweig löscht die KI auch dann nicht, wenn er anders heißt
        gh.repos["dora/smarthome"]["default_branch"] = "trunk"
        gh.refs["dora/smarthome"]["trunk"] = gh.refs["dora/smarthome"]["main"]
        with pytest.raises(ToolError, match="Hauptzweig"):
            await tools["github_api"]({"method": "DELETE", "path": "/repos/dora/smarthome/git/refs/heads/trunk"})
        assert not any(m != "GET" for m, _p, _b in gh.calls) and not chat.asked

    run(scenario())


def test_generic_api_delete_of_other_branch_is_sensitive():
    gh, chat = FakeGithub(), Chat()
    gh.refs["dora/smarthome"]["alt"] = gh.refs["dora/smarthome"]["main"]
    box, tools = toolbox(gh, chat, confirm=False)

    async def scenario():
        await tools["github_api"]({"method": "DELETE", "path": "/repos/dora/smarthome/git/refs/heads/alt"})
        assert len(chat.asked) == 1 and chat.asked[0][2] is False
        assert ("DELETE", "/repos/dora/smarthome/git/refs/heads/alt", None) in gh.calls

    run(scenario())


def test_errors_become_tool_errors_with_event_and_never_leak_the_token():
    gh, chat = FakeGithub(), Chat()
    gh.fail = {"POST .*/issues$": (403, {"message": f"Resource not accessible by personal access token {TOKEN}"})}
    box, tools = toolbox(gh, chat)

    async def scenario():
        with pytest.raises(ToolError) as exc:
            await tools["github_create_issue"]({"repo": "dora/smarthome", "title": "x"})
        assert "Rechte des Tokens" in str(exc.value) and TOKEN not in str(exc.value)
        assert chat.events[-1]["status"] == "error" and TOKEN not in json.dumps(chat.events)

    run(scenario())


# ----------------------------------------------------------------------------- Konfiguration

def test_github_config_options_and_validation():
    s = parse_settings(RAW, frozenset())
    assert s.github_access_default == "none" and s.github_write_confirm == "ask" and s.github_repos == () and s.github_token == ""
    s = parse_settings({**RAW, "github_token": f" {TOKEN} ", "github_access_default": "READ", "github_write_confirm": "always_allow",
                        "github_repos": "Dora/Smarthome, labor/*  dora/smarthome"}, frozenset())
    assert s.github_token == TOKEN and s.github_access_default == "read" and s.github_write_confirm == "always_allow"
    assert s.github_repos == ("dora/smarthome", "labor/*")
    assert TOKEN not in repr(s)
    assert parse_settings({**RAW, "github_repos": ["a/b", "c/*"]}, frozenset()).github_repos == ("a/b", "c/*")
    for bad in ({"github_access_default": "admin"}, {"github_write_confirm": "nie"}, {"github_repos": "kein-slash"}, {"github_repos": "a/b/c"}, {"github_repos": "*/x"}):
        with pytest.raises(ConfigError):
            parse_settings({**RAW, **bad}, frozenset())
    profiles = [{**RAW["profiles"][0], "github_access": "write"}, RAW["profiles"][1]]
    assert parse_settings({**RAW, "profiles": profiles}, frozenset()).profiles[0].github_access == "write"
    with pytest.raises(ConfigError):
        parse_settings({**RAW, "profiles": [{**RAW["profiles"][0], "github_access": "root"}]}, frozenset())


# --------------------------------------------------------------------- Einbindung in die App

def gh_app(store, script, github=None, **options):
    settings = parse_settings({**RAW, "github_token": TOKEN, **options}, frozenset({"testclient"}))
    seen = {}

    class ToolBackend:
        async def stream(self, history, message, effort, attachments=None, instructions=None, tools=None, note="", **_):
            seen["tools"] = sorted(t.name for t in tools or [])
            seen["note"] = note
            handlers = {t.name: t.handler for t in tools or []}
            for name, args in script:
                try:
                    seen.setdefault("results", []).append(await handlers[name](args))
                except ToolError as exc:
                    seen.setdefault("results", []).append("FEHLER " + str(exc))
            yield "Fertig."

    gh = FakeGithub()
    api = github if github is not None else GithubApi(TOKEN, transport=gh.transport())
    return build_ingress_app(settings, store, ToolBackend(), github=api), seen, gh


def test_me_reports_github_level_and_tools_follow_the_level(store):
    async def scenario():
        app, seen, _gh = gh_app(store, [], github_access_default="read")
        me = jget(await asgi(app, "GET", "/api/me"))
        assert me["github"] == "read"
        chat = await new_chat(app)
        await asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Hi"})
        assert "github_read_file" in seen["tools"] and "github_commit_files" not in seen["tools"] and "GitHub" in seen["note"] and "nur lesen" in seen["note"]
        # ohne Token oder Stufe „none“ gibt es nichts
        app, seen, _gh = gh_app(store, [], github_access_default="none")
        assert jget(await asgi(app, "GET", "/api/me"))["github"] == "none"
        chat = await new_chat(app)
        await asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Hi"})
        assert not [t for t in seen["tools"] if t.startswith("github_")] and "keine GitHub-Werkzeuge" in seen["note"]
        assert "github_access" in seen["note"] and "github_token" not in seen["note"]  # Stufe fehlt, Token ist da
        app, seen, _gh = gh_app(store, [], github=GithubApi(""), github_access_default="write")
        assert jget(await asgi(app, "GET", "/api/me"))["github"] == "none"
        chat = await new_chat(app)
        await asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Hi"})
        assert "github_token" in seen["note"] and TOKEN not in seen["note"]  # Token fehlt: Hinweis auf die Einrichtung

    run(scenario())


def test_profile_level_overrides_default(store):
    async def scenario():
        profiles = [{**RAW["profiles"][0], "github_access": "write"}, RAW["profiles"][1]]
        app, seen, _gh = gh_app(store, [], profiles=profiles, github_access_default="read")
        assert jget(await asgi(app, "GET", "/api/me"))["github"] == "write"
        assert jget(await asgi(app, "GET", "/api/me", user=DORA))["github"] == "read"

    run(scenario())


async def until(check, tries=200):
    for _ in range(tries):
        if await check():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("Bedingung nie erreicht")


def test_commit_end_to_end_with_approval_topic_and_link(store):
    async def scenario():
        script = [("github_read_file", {"repo": "dora/smarthome", "path": "README.md"}),
                  ("github_commit_files", {"repo": "dora/smarthome", "message": "Docs", "branch": "docs", "create_branch_from": "main", "files": [{"path": "NEU.md", "content": "hallo"}]})]
        app, seen, gh = gh_app(store, script, github_access_default="write")
        chat = await new_chat(app)
        post = asyncio.create_task(asgi(app, "POST", f"/api/chats/{chat}/send", {"content": "Lege eine Datei an"}))

        async def waiting():
            return next(c for c in jget(await asgi(app, "GET", "/api/chats")) if c["id"] == chat)["needs_approval"]

        await until(waiting)
        assert "docs" not in gh.refs["dora/smarthome"]
        assert (await asgi(app, "POST", f"/api/chats/{chat}/approve", {"id": 1, "decision": "allow"}))["status"] == 204
        events = sse(await post)
        approval = next(e for e in events if e["type"] == "approval")
        assert approval["topic"] == "github" and "NEU.md" in approval["details"]
        # nach dem Lesen fremder Inhalte gibt es kein „in diesem Chat immer zulassen“
        assert approval["chat_ok"] is False
        assert gh.files_at("dora/smarthome", "docs")["NEU.md"] == b"hallo"
        tools = [e for e in events if e["type"] == "tool" and e["status"] == "ok"]
        assert [e["kind"] for e in tools] == ["gh-read", "gh-write"] and tools[-1]["link"].startswith("https://github.com/dora/smarthome/commit/")
        history = jget(await asgi(app, "GET", f"/api/chats/{chat}/messages"))
        saved = history[-1]["tools"]
        assert [t["kind"] for t in saved] == ["gh-read", "gh-write"] and saved[-1]["link"].startswith("https://github.com/")

    run(scenario())


def test_foreign_links_are_not_kept(store):
    # Nur Links auf github.com gelangen in den Verlauf (kein Weg, über Werkzeug-Ereignisse beliebige Adressen einzuschleusen).
    chat_id = store.create_chat("adm01", "T")["id"]
    msg = store.add_message("adm01", chat_id, "assistant", "x", tools=[
        {"id": 1, "label": "a", "status": "ok", "kind": "gh-write", "note": "", "link": "https://github.com/a/b/pull/1"},
        {"id": 2, "label": "b", "status": "ok", "kind": "gh-write", "note": "", "link": "https://evil.example/phish"},
        {"id": 3, "label": "c", "status": "ok", "kind": "gh-write", "note": "", "link": "javascript:alert(1)"},
    ])
    stored = [m for m in store.list_messages("adm01", chat_id) if m["id"] == msg["id"]][0]["tools"]
    assert [t.get("link") for t in stored] == ["https://github.com/a/b/pull/1", None, None]
