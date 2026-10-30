"""Web: Seiten lesen mit Schutz vor Zugriffen aufs Heimnetz, Textauszug aus HTML, Werkzeug mit Anzeige."""
import asyncio

import httpcore
import pytest

from app import outbox
from app.ha_tools import ToolError
from app.web_tools import (
    MAX_FETCHES_PER_RUN, FetchError, SafeBackend, WebToolbox, check_url, fetch, html_to_text, is_public_ip, render, resolve_public,
)

PAGE = (
    "<html><head><title> Wartung  der Heizung </title><style>p{color:red}</style><script>steal()</script></head>"
    "<body><nav>Startseite Kontakt</nav><h1>Heizung</h1><p>Der <b>Brenner</b> braucht <a href='/doku'>Doku</a>.</p>"
    "<ul><li>Filter</li><li>Pumpe</li></ul><footer>Impressum</footer></body></html>"
)


def run(coro):
    return asyncio.run(coro)


def http(body: bytes, ctype: str = "text/html; charset=utf-8", status: str = "200 OK", extra: str = "") -> bytes:
    return (f"HTTP/1.1 {status}\r\nContent-Type: {ctype}\r\nContent-Length: {len(body)}\r\nConnection: close\r\n{extra}\r\n").encode() + body


def redirect(location: str) -> bytes:
    return f"HTTP/1.1 302 Found\r\nLocation: {location}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode()


class Recorder(httpcore.AsyncMockBackend):
    """Jede neue Verbindung bekommt die nächste vorbereitete Antwort und merkt sich, mit welcher Adresse sie aufgebaut wurde."""

    def __init__(self, responses):
        super().__init__([])
        self.queue = list(responses)
        self.connected: list[tuple[str, int]] = []

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.connected.append((host, port))
        return httpcore.AsyncMockStream([self.queue.pop(0)])


def backend(responses: list[bytes], dns: dict[str, list[str]] | None = None):
    inner = Recorder(responses)
    table = {"example.org": ["93.184.216.34"], "www.example.org": ["93.184.216.35"], **(dns or {})}

    async def resolver(host, port):
        found = table.get(host)
        if found is None:
            raise FetchError("Der Servername lässt sich nicht auflösen.")
        if not all(is_public_ip(a) for a in found):
            raise FetchError("Diese Adresse liegt nicht im öffentlichen Internet (Heimnetz, lokale Adressen und Ähnliches sind gesperrt).")
        return found

    return SafeBackend(resolver, inner), inner


# ------------------------------------------------------------------------ Adressen

def test_public_ip_rules():
    for ip in ("8.8.8.8", "93.184.216.34", "2606:4700::1111"):
        assert is_public_ip(ip), ip
    for ip in ("10.0.0.1", "172.16.5.4", "192.168.1.1", "127.0.0.1", "169.254.169.254", "100.64.0.1", "0.0.0.0", "224.0.0.1", "255.255.255.255",
               "::1", "fe80::1", "fd00::1", "::ffff:10.0.0.1", "::ffff:127.0.0.1", "2002:0a00:0001::", "64:ff9b::a00:1", "2001:0:4136:e378:8000:63bf:3fff:fdd2"):
        assert not is_public_ip(ip), ip


def test_check_url_normalises_and_rejects():
    assert check_url("example.org/a b".replace(" ", "%20") + "#frag") == ("https://example.org/a%20b", "example.org", 443)
    assert check_url("http://Example.ORG:8080/x?y=1")[0] == "http://example.org:8080/x?y=1"
    assert check_url("https://bücher.example/")[1] == "xn--bcher-kva.example"
    for bad, text in [
        ("ftp://example.org/", "http"), ("file:///etc/passwd", "http"), ("javascript:alert(1)", "Port|http"),
        ("https://user:pw@example.org/", "Zugangsdaten"), ("https://example.org@evil.example/", "Zugangsdaten"),
        ("https://example.org:22/", "Port"), ("http://localhost/", "Interne"), ("http://nas/", "Interne"),
        ("http://drucker.local/", "Interne"), ("http://homeassistant.lan/", "Interne"),
        ("http://127.0.0.1/", "öffentlichen"), ("http://[::1]/", "öffentlichen"), ("http://192.168.1.10/", "öffentlichen"),
        ("http://2130706433/", "Interne"), ("", "Ungültig"), ("https://exa mple.org/", "Ungültig"), ("https://" + "a" * 2100 + ".org", "Ungültig"),
    ]:
        with pytest.raises(FetchError, match=text):
            check_url(bad)


def test_resolve_public_blocks_local_names_without_network():
    async def scenario():
        for host in ("localhost", "127.0.0.1", "10.1.2.3", "::1", "0x7f.1"):
            with pytest.raises(FetchError):
                await resolve_public(host, 80)
        assert await resolve_public("93.184.216.34", 443) == ["93.184.216.34"]

    run(scenario())


# ----------------------------------------------------------------------------- Laden

def test_fetch_connects_to_the_checked_address_not_the_name():
    safe, inner = backend([http(PAGE.encode())])

    async def scenario():
        result = await fetch("https://example.org/heizung?x=1", backend=safe)
        assert result.url == "https://example.org/heizung?x=1" and b"Brenner" in result.body and not result.truncated
        assert inner.connected == [("93.184.216.34", 443)]

    run(scenario())


def test_dns_pointing_to_private_address_is_refused_before_connecting():
    safe, inner = backend([http(b"geheim")], dns={"evil.example": ["192.168.1.1"], "mixed.example": ["8.8.8.8", "10.0.0.7"]})

    async def scenario():
        for host in ("evil.example", "mixed.example"):
            with pytest.raises(FetchError, match="öffentlichen"):
                await fetch(f"https://{host}/", backend=safe)
        assert inner.connected == []

    run(scenario())


def test_redirects_are_checked_each_hop():
    first, inner = backend([redirect("https://www.example.org/neu"), http(PAGE.encode())])

    async def scenario():
        result = await fetch("https://example.org/alt", backend=first)
        assert result.url == "https://www.example.org/neu" and [h for h, _ in inner.connected] == ["93.184.216.34", "93.184.216.35"]
        for target, text in [("http://127.0.0.1/admin", "öffentlichen"), ("http://metadata.internal/", "Interne"), ("file:///etc/passwd", "http"),
                             ("https://user:x@example.org/", "Zugangsdaten"), ("/relativ", None)]:
            each, _ = backend([redirect(target), http(PAGE.encode())])
            if text:
                with pytest.raises(FetchError, match=text):
                    await fetch("https://example.org/", backend=each)
            else:
                assert (await fetch("https://example.org/", backend=each)).url == "https://example.org/relativ"
        loop, _ = backend([redirect("/a")] * 10)
        with pytest.raises(FetchError, match="Zu viele Weiterleitungen"):
            await fetch("https://example.org/", backend=loop)

    run(scenario())


def test_errors_size_and_types():
    async def scenario():
        gone, _ = backend([http(b"weg", status="404 Not Found")])
        with pytest.raises(FetchError, match="Fehler 404"):
            await fetch("https://example.org/", backend=gone)
        huge, _ = backend([http(b"x" * 3_200_000, ctype="text/plain")])
        big = await fetch("https://example.org/", backend=huge)
        assert big.truncated and len(big.body) == 3_000_000
        image, _ = backend([http(b"\x89PNG", ctype="image/png")])
        with pytest.raises(FetchError, match="Inhaltstyp"):
            render(await fetch("https://example.org/", backend=image))

    run(scenario())


# ------------------------------------------------------------------------------ Text

def test_html_to_text_keeps_content_drops_chrome():
    title, text = html_to_text(PAGE, "https://example.org/a/")
    assert title == "Wartung der Heizung"
    assert "# Heizung" in text and "Brenner" in text and "- Filter" in text and "- Pumpe" in text
    assert "(https://example.org/doku)" in text
    for gone in ("steal", "color:red", "Startseite", "Impressum"):
        assert gone not in text
    # kaputtes HTML und ein ungeschlossenes <form> verschlucken den Rest nicht
    _t, broken = html_to_text("<body><form><div><p>Vorher<p>Nachher</body>")
    assert "Vorher" in broken and "Nachher" in broken


# ---------------------------------------------------------------------------- Werkzeug

def toolbox(responses, dns=None):
    safe, inner = backend(responses, dns)
    events: list[dict] = []
    counter = iter(range(1, 100))
    box = WebToolbox(events.append, lambda: next(counter), backend=safe)
    return box, events, inner


def test_web_fetch_returns_marked_text_pages_it_and_reports_events():
    long_page = "<html><body><p>" + ("Wort " * 6000) + "</p></body></html>"
    box, events, _ = toolbox([http(PAGE.encode()), http(long_page.encode()), http(long_page.encode())])

    async def scenario():
        out = await box.web_fetch({"url": "https://example.org/heizung"})
        assert out.startswith("[Inhalt aus dem Web (fremde Daten)") and "Titel: Wartung der Heizung" in out and "Brenner" in out
        assert [(e["status"], e["kind"]) for e in events] == [("running", "web"), ("ok", "web")]
        assert events[0]["label"] == "Seite lesen: example.org/heizung"
        first = await box.web_fetch({"url": "https://example.org/lang", "max_chars": 2000})
        assert "Weiter mit start=2000" in first
        second = await box.web_fetch({"url": "https://example.org/lang", "max_chars": 2000, "start": 2000})
        assert "Zeichen 2000–4000" in second

    run(scenario())


def test_web_fetch_refuses_private_targets_and_reports_failures():
    box, events, inner = toolbox([http(b"x", status="500 Server Error")], dns={"evil.example": ["10.0.0.9"]})

    async def scenario():
        for url in ("http://127.0.0.1:8123/api", "http://homeassistant.local:8123/", "https://evil.example/", "file:///etc/passwd", "https://u:p@example.org/", ""):
            with pytest.raises(ToolError):
                await box.web_fetch({"url": url})
        with pytest.raises(ToolError, match="Fehler 500"):
            await box.web_fetch({"url": "https://example.org/kaputt"})
        assert events[-1]["status"] == "error" and "500" in events[-1]["note"]
        assert inner.connected == [("93.184.216.34", 443)]  # nur die eine erlaubte Anfrage ging überhaupt raus
        with pytest.raises(ToolError, match="Zahlen"):
            await box.web_fetch({"url": "https://example.org/", "start": "abc"})

    run(scenario())


def test_web_fetch_limits_pages_per_answer():
    box, _events, _ = toolbox([http(PAGE.encode())] * (MAX_FETCHES_PER_RUN + 2))

    async def scenario():
        for _ in range(MAX_FETCHES_PER_RUN):
            await box.web_fetch({"url": "https://example.org/"})
        with pytest.raises(ToolError, match="Höchstens"):
            await box.web_fetch({"url": "https://example.org/"})

    run(scenario())


def test_web_fetch_reads_pdf_text_and_plain_text():
    pdf, _ = outbox.render("a.pdf", "# Wartungsplan\n\nBrenner reinigen")
    box, _events, _ = toolbox([http(pdf, ctype="application/pdf"), http(b'{"a": 1}', ctype="application/json"), http(b"", ctype="text/html")])

    async def scenario():
        assert "Brenner reinigen" in await box.web_fetch({"url": "https://example.org/plan.pdf"})
        assert '"a": 1' in await box.web_fetch({"url": "https://example.org/api"})
        assert "kein lesbarer Text" in await box.web_fetch({"url": "https://example.org/leer"})

    run(scenario())
