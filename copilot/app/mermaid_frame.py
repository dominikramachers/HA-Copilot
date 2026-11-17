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
  var last = "";
  function send(msg) { parent.postMessage(msg, "*"); }
  function setup(plain) {
    var m = window.__esbuild_esm_mermaid_nm.mermaid.default;
    var cfg = {startOnLoad: false, securityLevel: "strict", theme: "default", suppressErrorRendering: true, fontFamily: "system-ui, sans-serif"};
    if (plain) { cfg.htmlLabels = false; cfg.flowchart = {htmlLabels: false}; cfg["class"] = {htmlLabels: false}; cfg.state = {htmlLabels: false}; }
    m.initialize(cfg);
    return m;
  }
  // Das Bild für den Export: mit Größe, ohne Skripte und auf weißem Grund. Das macht der Rahmen, denn nur hier sind Inline-Stile erlaubt.
  function finishSvg(text) {
    var doc = new DOMParser().parseFromString(text, "image/svg+xml");
    var root = doc.documentElement;
    if (!root || root.nodeName.toLowerCase() !== "svg" || doc.getElementsByTagName("parsererror").length) throw new Error("svg");
    [].slice.call(root.querySelectorAll("script")).forEach(function (el) { el.parentNode.removeChild(el); });
    [].slice.call(root.querySelectorAll("*")).forEach(function (el) {
      [].slice.call(el.attributes).forEach(function (a) { if (/^on/i.test(a.name)) el.removeAttribute(a.name); });
    });
    var box = (root.getAttribute("viewBox") || "").trim().split(/[ ,]+/).map(Number);
    var ok = box.length === 4 && box.every(isFinite);
    var x = ok ? box[0] : 0, y = ok ? box[1] : 0;
    var w = ok ? box[2] : (parseFloat(root.getAttribute("width")) || 800), h = ok ? box[3] : (parseFloat(root.getAttribute("height")) || 600);
    root.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    root.setAttribute("viewBox", x + " " + y + " " + w + " " + h);
    root.setAttribute("width", String(Math.ceil(w)));
    root.setAttribute("height", String(Math.ceil(h)));
    root.removeAttribute("style");
    var back = doc.createElementNS("http://www.w3.org/2000/svg", "rect");
    back.setAttribute("x", x); back.setAttribute("y", y); back.setAttribute("width", w); back.setAttribute("height", h); back.setAttribute("fill", "#ffffff");
    root.insertBefore(back, root.firstChild);
    return {svg: new XMLSerializer().serializeToString(root), width: Math.ceil(w), height: Math.ceil(h)};
  }
  window.addEventListener("message", function (e) {
    var d = e.data;
    if (e.source !== parent || !d || typeof d !== "object") return;
    if (d.type === "render" && typeof d.source === "string") {
      var m = setup(false);
      last = d.source;
      n += 1;
      m.render("mm" + n, d.source).then(function (r) {
        out.innerHTML = r.svg;
        send({type: "done"});
      }, function (err) {
        out.textContent = "";
        send({type: "error", message: String((err && err.message) || err).slice(0, 400)});
      });
    } else if (d.type === "export" && last) {
      // Zum Speichern als Bild: dasselbe Diagramm noch einmal, mit schlichten SVG-Beschriftungen statt HTML.
      var plain = setup(true);
      n += 1;
      plain.render("mm" + n, last).then(function (r) {
        var file = finishSvg(r.svg);
        send({type: "svg", id: d.id, svg: file.svg, width: file.width, height: file.height});
      }, function (err) {
        send({type: "svg", id: d.id, error: String((err && err.message) || err).slice(0, 200)});
      });
    }
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
