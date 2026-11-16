"""Rahmen für Mermaid-Diagramme: eine feste, abgeschottete Seite, die das Diagramm im Browser zeichnet.

Die Bibliothek (``app/vendor/mermaid.min.js``) liegt im Add-on und wird nie von außen geladen. Die Seite steht in einem
Rahmen ohne ``allow-same-origin`` und mit ``default-src 'none'``: kein Netzwerk, kein Zugriff auf die Chat-Oberfläche. Den
Diagrammtext bekommt sie per ``postMessage`` von der Oberfläche; gezeichnet wird mit ``securityLevel: "strict"``. Die Seite
selbst ist für alle gleich und darf deshalb zwischengespeichert werden.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

LIB = Path(__file__).parent / "vendor" / "mermaid.min.js"

FRAME_HEADERS = {
    "Content-Security-Policy": (
        "sandbox allow-scripts; default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
        "img-src data:; font-src data:; frame-ancestors 'self'; base-uri 'none'; form-action 'none'"
    ),
    "Cache-Control": "private, max-age=86400",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}

PAGE = """<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mermaid</title>
<style>
html,body{margin:0;height:100%}
body{display:flex;align-items:flex-start;justify-content:center;padding:16px;box-sizing:border-box;font:14px/1.4 system-ui,sans-serif;background:#fff;color:#1c1c1c}
#out{max-width:100%}
#out svg{max-width:100%;height:auto}
</style></head>
<body><div id="out"></div>
<script>__LIB__</script>
<script>
(function () {
  var out = document.getElementById("out");
  var n = 0;
  function send(msg) { parent.postMessage(msg, "*"); }
  window.addEventListener("message", function (e) {
    var d = e.data;
    if (e.source !== parent || !d || d.type !== "render" || typeof d.source !== "string") return;
    var m = window.__esbuild_esm_mermaid_nm.mermaid.default;
    m.initialize({startOnLoad: false, securityLevel: "strict", theme: "default", suppressErrorRendering: true, fontFamily: "system-ui, sans-serif"});
    n += 1;
    m.render("mm" + n, d.source).then(function (r) {
      out.innerHTML = r.svg;
      send({type: "done"});
    }, function (err) {
      out.textContent = "";
      send({type: "error", message: String((err && err.message) || err).slice(0, 400)});
    });
  });
  send({type: "ready"});
})();
</script></body></html>
"""


@lru_cache(maxsize=1)
def page() -> str:
    """Die fertige Seite mit eingebauter Bibliothek (einmal gelesen, danach im Speicher)."""
    lib = LIB.read_text(encoding="utf-8").replace("</script", "<\\/script")
    return PAGE.replace("__LIB__", lib)
