"""Konnektoren entdecken: Katalog, Logos (Link und Upload), Suche im offenen Register (mit simulierten Servern)."""
import asyncio
import base64
import json

import httpx
import pytest

from app import connector_catalog as catalog
from app import connector_icons as icons
from app import connector_registry as registry
from app.connectors import ConnectorError, ConnectorService
from app.netguard import UrlRejected, acheck_url
from app.vault import Vault
from conftest import DORA
from test_background_run import asgi
from test_connectors import PUBLIC_IP, app_with, resolver_for

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 40
GIF = b"GIF89a" + b"\x00" * 40
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 40
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


def run(coro):
    return asyncio.run(coro)


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


class Web:
    """Simuliert Bildserver und Register."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.registry_pages: dict[str, httpx.Response] = {}
        self.registry_calls = 0

    def transport(self):
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host, path = request.url.host, request.url.path
        if host == "img.example.com":
            if path == "/logo.png":
                return httpx.Response(200, content=PNG, headers={"content-type": "text/plain"})
            if path == "/logo.svg":
                return httpx.Response(200, content=SVG, headers={"content-type": "image/svg+xml"})
            if path == "/big.png":
                return httpx.Response(200, content=PNG + b"\x00" * (icons.MAX_ICON_BYTES + 1))
            if path == "/hop":
                return httpx.Response(302, headers={"location": "/logo.png"})
            if path == "/loop":
                return httpx.Response(302, headers={"location": "/loop"})
            if path == "/to-http":
                return httpx.Response(302, headers={"location": "http://img.example.com/logo.png"})
            if path == "/to-intern":
                return httpx.Response(302, headers={"location": "https://intern.example.com/logo.png"})
            return httpx.Response(404)
        if host == "registry.modelcontextprotocol.io":
            self.registry_calls += 1
            key = path + ("?" + request.url.query.decode() if request.url.query else "")
            for known, response in self.registry_pages.items():
                if key.startswith(known):
                    return response
            return httpx.Response(404)
        return httpx.Response(404)


def make(store, web, tmp_path, levels=None):
    table = levels or {"adm01": "global", "dora": "own"}
    mapping = {"intern.example.com": "10.0.0.5"}
    return ConnectorService(
        store, Vault(tmp_path / "connector.key"), level_for=lambda pid: table.get(pid, "none"),
        transport=web.transport(), resolver=resolver_for(mapping=mapping),
    )


def server(name, remotes, **more):
    return {"server": {"name": name, "description": "Beschreibung", "version": "1.0.0", "remotes": remotes, **more}, "_meta": {}}


# ----------------------------------------------------------------------- Bildprüfung

def test_sniff_accepts_only_raster_images_by_content():
    assert [icons.sniff(x) for x in (PNG, JPEG, GIF, WEBP)] == ["image/png", "image/jpeg", "image/gif", "image/webp"]
    assert icons.sniff(SVG) is None and icons.sniff(b"<html>") is None and icons.sniff(b"") is None
    for bad, why in [(b"", "leer"), (SVG, "PNG"), (PNG + b"\x00" * icons.MAX_ICON_BYTES, "zu groß")]:
        with pytest.raises(icons.IconError, match=why):
            icons.check(bad)


def test_upload_accepts_plain_and_data_url_base64():
    assert icons.from_base64(b64(PNG)) == ("image/png", PNG)
    assert icons.from_base64("data:image/png;base64," + b64(PNG)) == ("image/png", PNG)
    for bad in ("kein base64!!", b64(SVG), "A" * (icons.MAX_ICON_BYTES * 2)):
        with pytest.raises(icons.IconError):
            icons.from_base64(bad)


def test_fetch_follows_redirects_through_the_address_guard():
    web = Web()
    guard = lambda url: acheck_url(url, resolver=resolver_for(mapping={"intern.example.com": "10.0.0.5"}))  # noqa: E731

    async def go(url):
        return await icons.fetch(url, guard, web.transport())

    assert run(go("https://img.example.com/logo.png")) == ("image/png", PNG)  # Bildart zählt nach Inhalt, nicht nach Antwort-Kopf
    assert run(go("https://img.example.com/hop")) == ("image/png", PNG)
    for url, why in [
        ("http://img.example.com/logo.png", "https://"),
        ("https://img.example.com/logo.svg", "PNG"),
        ("https://img.example.com/big.png", "zu groß"),
        ("https://img.example.com/nix", "Antwort 404"),
        ("https://img.example.com/loop", "Weiterleitungen"),
        ("https://img.example.com/to-http", "https://"),
        ("https://img.example.com/to-intern", "Heimnetz"),
        ("https://intern.example.com/logo.png", "Heimnetz"),
    ]:
        with pytest.raises(icons.IconError, match=why):
            run(go(url))


# ----------------------------------------------------------------------- Logos am Konnektor

BASE = {"name": "Mail", "url": "https://mcp.example.com/mcp", "auth": "none"}


def test_custom_icon_by_upload_link_replace_and_clear(store, tmp_path):
    web = Web()
    service = make(store, web, tmp_path)

    async def scenario():
        made = await service.create("dora", {**BASE, "icon_data": b64(PNG)})
        assert made["icon"] == {"kind": "custom", "rev": 1}
        assert service.icon("dora", made["id"]) == {"mime": "image/png", "data": PNG, "rev": 1}
        changed = await service.update("dora", made["id"], {"icon_url": "https://img.example.com/logo.png"})
        assert changed["icon"] == {"kind": "custom", "rev": 2}  # neue Version, damit der Browser kein altes Bild zeigt
        assert service.listing("dora")[0]["icon"]["rev"] == 2
        kept = await service.update("dora", made["id"], {"description": "neu"})
        assert kept["icon"]["rev"] == 2
        cleared = await service.update("dora", made["id"], {"clear_icon": True})
        assert cleared["icon"] == {"kind": "", "slug": ""} and service.icon("dora", made["id"]) is None
        service.delete("dora", made["id"])
        assert store.connector_icon_get(made["id"]) is None

    run(scenario())


def test_bad_icon_stops_creation_unless_best_effort(store, tmp_path):
    web = Web()
    service = make(store, web, tmp_path)

    async def scenario():
        with pytest.raises(ConnectorError, match="PNG"):
            await service.create("dora", {**BASE, "icon_url": "https://img.example.com/logo.svg"})
        assert store.connector_list("dora") == []  # nichts halb gespeichert
        soft = await service.create("dora", {**BASE, "icon_url": "https://img.example.com/logo.svg", "icon_best_effort": True})
        assert soft["icon"]["kind"] == ""
        with pytest.raises(ConnectorError):
            await service.update("dora", soft["id"], {"icon_data": b64(SVG)})
        assert service.listing("dora")[0]["icon"]["kind"] == ""

    run(scenario())


def test_icons_are_private_with_the_connector(store, tmp_path):
    web = Web()
    service = make(store, web, tmp_path, {"adm01": "global", "dora": "own", "gast": "use"})

    async def scenario():
        mine = await service.create("dora", {**BASE, "icon_data": b64(PNG)})
        with pytest.raises(ConnectorError) as exc:
            service.icon("adm01", mine["id"])
        assert exc.value.status == 404
        shared = await service.create("adm01", {**BASE, "name": "Firma", "scope": "global", "icon_data": b64(JPEG)})
        assert service.icon("gast", shared["id"])["mime"] == "image/jpeg"  # globale Logos sehen alle, die den Konnektor sehen

    run(scenario())


# ----------------------------------------------------------------------- Katalog

def test_catalog_file_is_consistent():
    entries = catalog.entries()
    ids = [e["id"] for e in entries]
    assert len(ids) == len(set(ids)) >= 25
    categories = {c["id"] for c in catalog.categories()}
    guides = catalog.guides()
    assert categories and all(c["label"] for c in catalog.categories())
    for e in entries:
        assert e["category"] in categories and e["label"] and e["summary"] and e["source"] in ("docs", "list", "known"), e["id"]
        assert e["kind"] in ("server", "guide") and e["auth"] in ("none", "bearer", "header", "oauth")
        if e["kind"] == "server":
            assert e["url"].startswith("https://"), e["id"]
        else:
            assert e["guide"] in guides, e["id"]
        if e.get("guide"):
            assert e["guide"] in guides
        if e["pre_registered"]:
            assert e["auth"] == "oauth"
    for e in entries:  # Anbieter mit Logo-Angabe: die Datei muss da sein, sonst fiele das Logo leise weg
        raw = catalog.find(e["id"])
        if raw.get("icon"):
            assert e["icon"] == raw["icon"], f"Logo-Datei fehlt: {raw['icon']}"
    for guide in guides.values():
        assert len(guide["steps"]) >= 3 and guide["warn"]


def test_catalog_texts_exist_in_both_languages():
    raw = json.loads(catalog.CATALOG_PATH.read_text(encoding="utf-8"))
    for e in raw["connectors"]:
        assert e["summary"]["de"] and e["summary"]["en"], e["id"]
        if e.get("note"):
            assert e["note"]["de"] and e["note"]["en"], e["id"]
    for key, guide in raw["guides"].items():
        assert len(guide["de"]) == len(guide["en"]) and guide["warn"]["de"] and guide["warn"]["en"], key
    assert all(c["label"]["de"] and c["label"]["en"] for c in raw["categories"])


def test_logo_files_are_small_safe_svgs():
    for path in catalog.ICON_DIR.glob("*.svg"):
        text = path.read_text(encoding="utf-8")
        assert len(text) < 6000 and text.startswith("<svg") and "<script" not in text.lower() and "href" not in text.lower(), path.name
        assert text.count("<path") == 1


def test_create_from_catalog_fills_defaults_and_needs_own_app_for_google(store, tmp_path):
    web = Web()
    service = make(store, web, tmp_path)

    async def scenario():
        with pytest.raises(ConnectorError, match="Client-ID"):
            await service.create("dora", {"catalog_id": "gmail"})
        made = await service.create("dora", {"catalog_id": "gmail", "client_id": "abc.apps.googleusercontent.com", "client_secret": "geheim"})
        assert made["catalog_id"] == "gmail" and made["name"] == "Gmail" and made["auth"] == "oauth"
        assert made["url"] == "https://gmailmcp.googleapis.com/mcp/v1" and "gmail.readonly" in made["scopes"]
        assert made["authorization_endpoint"] == "https://accounts.google.com/o/oauth2/v2/auth"
        assert made["auth_params"] == {"access_type": "offline", "prompt": "consent"}
        assert made["icon"] == {"kind": "brand", "slug": "gmail"} and made["pre_registered"]
        assert "geheim" not in json.dumps(service.listing("dora"))
        # eigene Eingaben gehen vor dem Katalog
        custom = await service.create("dora", {"catalog_id": "sentry", "name": "Sentry Firma", "description": "eigener Text"})
        assert custom["name"] == "Sentry Firma" and custom["description"] == "eigener Text" and custom["url"] == "https://mcp.sentry.dev/mcp"

    run(scenario())


def test_unknown_or_guide_only_catalog_ids_become_plain_connectors(store, tmp_path):
    web = Web()
    service = make(store, web, tmp_path)

    async def scenario():
        for cid in ("gibt-es-nicht", "microsoft-365"):
            made = await service.create("dora", {**BASE, "name": f"X {cid}"[:40], "catalog_id": cid})
            assert made["catalog_id"] == "" and made["icon"]["kind"] == ""

    run(scenario())


def test_catalog_api_needs_a_right_and_lists_everything(store, tmp_path):
    web = Web()

    async def scenario():
        app, _seen, _service = app_with(store, type("S", (), {"transport": lambda self: web.transport()})(), tmp_path, levels={"adm01": "global", "dora": "own"})
        out = await asgi(app, "GET", "/api/connectors/catalog", user=DORA)
        assert out["status"] == 200
        data = json.loads(out["body"])
        assert len(data["connectors"]) == len(catalog.entries()) and data["categories"] and "google" in data["guides"] and data["checked"]
        assert "{redirect}" in "".join(data["guides"]["google"]["steps"])
        none_app, *_ = app_with(store, type("S", (), {"transport": lambda self: web.transport()})(), tmp_path, levels={"dora": "none"})
        assert (await asgi(none_app, "GET", "/api/connectors/catalog", user=DORA))["status"] == 403

    run(scenario())


def test_icon_api_serves_with_safe_headers_and_hides_foreign_ones(store, tmp_path):
    web = Web()

    async def scenario():
        fake = type("S", (), {"transport": lambda self: web.transport()})()
        app, _seen, service = app_with(store, fake, tmp_path, levels={"adm01": "global", "dora": "own"})
        made = await service.create("dora", {**BASE, "icon_data": b64(PNG)})
        out = await asgi(app, "GET", f"/api/connectors/{made['id']}/icon", user=DORA)
        headers = out["headers"]
        assert out["status"] == 200 and out["body"] == PNG
        assert headers["content-type"] == "image/png" and headers["x-content-type-options"] == "nosniff" and "sandbox" in headers["content-security-policy"]
        plain = await service.create("dora", {**BASE, "name": "Ohne"})
        assert (await asgi(app, "GET", f"/api/connectors/{plain['id']}/icon", user=DORA))["status"] == 404
        from conftest import ADM01
        assert (await asgi(app, "GET", f"/api/connectors/{made['id']}/icon", user=ADM01))["status"] == 404
        big = {**BASE, "name": "Groß", "icon_data": "A" * (icons.MAX_ICON_BYTES * 2)}
        assert (await asgi(app, "POST", "/api/connectors", big, user=DORA))["status"] in (413, 422)

    run(scenario())


# ----------------------------------------------------------------------- Register

def test_registry_parse_keeps_only_connectable_https_servers():
    ok = server("io.example/mail", [{"type": "streamable-http", "url": "https://mail.example.com/mcp"}], title="Mail", websiteUrl="https://example.com",
                icons=[{"src": "https://example.com/i.svg", "mimeType": "image/svg+xml"}, {"src": "https://example.com/i.png", "mimeType": "image/png"}])
    keyed = server("io.example/key", [{"type": "streamable-http", "url": "https://k.example.com/mcp", "headers": [{"name": "Authorization", "isRequired": True, "isSecret": True}]}])
    custom = server("io.example/hdr", [{"type": "streamable-http", "url": "https://h.example.com/mcp", "headers": [{"name": "X-Key", "isSecret": True}, {"name": "X-Opt"}]}])
    skipped = [
        server("io.example/sse", [{"type": "sse", "url": "https://s.example.com/sse"}]),
        server("io.example/plain-http", [{"type": "streamable-http", "url": "http://p.example.com/mcp"}]),
        server("io.example/template", [{"type": "streamable-http", "url": "https://{tenant}.example.com/mcp"}]),
        server("io.example/local", []),
        "kaputt", {"server": {"remotes": []}},
    ]
    page = registry.parse_page({"servers": [ok, ok, keyed, custom, *skipped], "metadata": {"nextCursor": "abc"}})
    assert [i["id"] for i in page["items"]] == ["io.example/mail", "io.example/key", "io.example/hdr"] and page["next"] == "abc"
    mail, key, hdr = page["items"]
    assert mail["name"] == "Mail" and mail["auth"] == "none" and mail["icon_url"] == "https://example.com/i.png" and mail["website"] == "https://example.com"
    assert (key["auth"], key["header_name"]) == ("bearer", "") and (hdr["auth"], hdr["header_name"]) == ("header", "X-Key")
    assert key["name"] == "key"
    for bad in (None, [], {"servers": "x"}):
        with pytest.raises(registry.RegistryError):
            registry.parse_page(bad)


def test_registry_search_falls_back_caches_and_reports_errors(store, tmp_path):
    web = Web()
    service = make(store, web, tmp_path)
    body = {"servers": [server("io.example/mail", [{"type": "streamable-http", "url": "https://mail.example.com/mcp"}])], "metadata": {}}

    async def scenario():
        with pytest.raises(ConnectorError) as exc:
            await service.registry_search("dora", "mail")
        assert exc.value.status == 502 and "nicht erreichbar" in str(exc.value)
        web.registry_pages["/v0/servers"] = httpx.Response(200, json=body)  # nur die ältere Pfadversion antwortet
        first = await service.registry_search("dora", "mail")
        assert [i["id"] for i in first["items"]] == ["io.example/mail"]
        calls = web.registry_calls
        assert (await service.registry_search("dora", "MAIL"))["items"] == first["items"] and web.registry_calls == calls  # aus dem Zwischenspeicher
        query = [r for r in web.requests if r.url.path == "/v0/servers"][-1].url.params
        assert query["search"] == "mail" and query["limit"] == "20"
        web.registry_pages.clear()
        web.registry_pages["/v0.1/servers"] = httpx.Response(500)
        with pytest.raises(ConnectorError, match="500"):
            await service.registry_search("dora", "anderes")
        web.registry_pages["/v0.1/servers"] = httpx.Response(200, text="<html>")
        with pytest.raises(ConnectorError, match="unerwartet"):
            await service.registry_search("dora", "drittes")
        with pytest.raises(ConnectorError) as denied:
            await service.registry_search("gast", "mail")
        assert denied.value.status == 403

    run(scenario())


def test_registry_address_goes_through_the_guard(store, tmp_path):
    web = Web()
    service = ConnectorService(
        store, Vault(tmp_path / "connector.key"), level_for=lambda pid: "own", transport=web.transport(),
        resolver=resolver_for("10.0.0.5"),
    )
    with pytest.raises(UrlRejected):
        run(service._registry._guard("https://registry.modelcontextprotocol.io/v0.1/servers"))
    assert PUBLIC_IP
