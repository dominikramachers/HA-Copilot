"use strict";

// Kleiner, sicherer Markdown-Renderer: baut ausschließlich DOM-Knoten (nie innerHTML),
// Links nur mit http(s)/mailto. Unterstützt Absätze, Überschriften, Listen, Zitate,
// Codeblöcke, **fett**, *kursiv*, `code` und [Text](URL).
(function () {
  const SAFE_URL = /^(https?:|mailto:)/i;
  const TABLE_SEP = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;
  const INLINE = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(\*[^*\s][^*\n]*\*)|(\[[^\]\n]+\]\([^)\s]+\))/;

  function inline(text, parent) {
    let rest = text;
    while (rest) {
      const m = INLINE.exec(rest);
      if (!m) { parent.append(rest); return; }
      if (m.index) parent.append(rest.slice(0, m.index));
      const tok = m[0];
      if (m[1]) {
        const el = document.createElement("code");
        el.textContent = tok.slice(1, -1);
        parent.append(el);
      } else if (m[2]) {
        const el = document.createElement("strong");
        inline(tok.slice(2, -2), el);
        parent.append(el);
      } else if (m[3]) {
        const el = document.createElement("em");
        inline(tok.slice(1, -1), el);
        parent.append(el);
      } else {
        const close = tok.indexOf("](");
        const label = tok.slice(1, close);
        const url = tok.slice(close + 2, -1);
        if (SAFE_URL.test(url)) {
          const a = document.createElement("a");
          a.href = url;
          a.target = "_blank";
          a.rel = "noopener noreferrer";
          a.textContent = label;
          parent.append(a);
        } else {
          parent.append(label);
        }
      }
      rest = rest.slice(m.index + tok.length);
    }
  }

  const EXT = {
    yaml: "yaml", yml: "yaml", python: "py", py: "py", bash: "sh", sh: "sh", shell: "sh", zsh: "sh",
    powershell: "ps1", ps1: "ps1", json: "json", html: "html", css: "css", javascript: "js", js: "js",
    typescript: "ts", ts: "ts", sql: "sql", xml: "xml", csv: "csv", markdown: "md", md: "md", ini: "ini",
    toml: "toml", dockerfile: "Dockerfile", jinja: "j2", jinja2: "j2", text: "txt", txt: "txt", log: "log",
  };
  const MIME = {
    html: "text/html", css: "text/css", js: "text/javascript", json: "application/json", csv: "text/csv",
    xml: "application/xml", md: "text/markdown",
  };

  // Eröffnungszeile eines Codeblocks: Sprache und optional datei=name.ext (oder title="name.ext")
  function parseInfo(info) {
    const text = (info || "").trim();
    const named = text.match(/(?:datei|file|title|filename)\s*=\s*"?([^"\s]+)"?/i);
    const lang = (text.split(/\s+/)[0] || "").toLowerCase();
    const language = /=/.test(lang) ? "" : lang;
    let name = named ? named[1].replace(/[\\/:*?"<>|\x00-\x1f]/g, "_").slice(0, 100) : "";
    const ext = EXT[language] || "txt";
    if (!name) name = ext === "Dockerfile" ? "Dockerfile" : tr("datei.{0}", ext);
    const dot = name.lastIndexOf(".");
    return { language, name, mime: MIME[dot >= 0 ? name.slice(dot + 1).toLowerCase() : ""] || "text/plain" };
  }

  function codeBlock(lines, info) {
    const meta = parseInfo(info);
    const pre = document.createElement("pre");
    const code = document.createElement("code");
    code.textContent = lines.join("\n");
    const tools = document.createElement("div");
    tools.className = "code-tools";
    const action = (label, handler) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "copy";
      button.textContent = label;
      button.addEventListener("click", () => handler(button, label));
      tools.append(button);
      return button;
    };
    const flash = (button, label, text) => {
      button.textContent = text;
      setTimeout(() => { button.textContent = label; }, 1500);
    };
    if (meta.language === "html" && window.kiFile) {
      action(tr("Vorschau"), (button) => window.kiFile.preview(pre, button, code.textContent));
    }
    if (window.kiFile) {
      action(tr("Herunterladen"), async (button, label) => {
        try { flash(button, label, (await window.kiFile.save(meta.name, code.textContent, meta.mime)) ? tr("Gespeichert") : label); }
        catch { flash(button, label, tr("Nicht möglich")); }
      });
    }
    action(tr("Kopieren"), async (button, label) => {
      try {
        await navigator.clipboard.writeText(code.textContent);
        flash(button, label, tr("Kopiert"));
      } catch {
        flash(button, label, tr("Nicht möglich"));
      }
    });
    pre.append(tools, code);
    return pre;
  }

  function render(source) {
    const root = document.createElement("div");
    root.className = "md";
    const lines = source.replace(/\r\n?/g, "\n").split("\n");
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (/^```/.test(line)) {
        const info = line.slice(3);
        const body = [];
        i++;
        while (i < lines.length && !/^```/.test(lines[i])) body.push(lines[i++]);
        i++; // schließende Zeile (fehlt sie noch, läuft der Block bis zum Ende)
        root.append(codeBlock(body, info));
      } else if (/^\s*$/.test(line)) {
        i++;
      } else if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
        root.append(document.createElement("hr"));
        i++;
      } else if (/\|/.test(line) && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1])) {
        const cells = (row) => row.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
        const wrap = document.createElement("div");
        wrap.className = "tbl";
        const table = document.createElement("table");
        const head = document.createElement("tr");
        for (const text of cells(line)) { const th = document.createElement("th"); inline(text, th); head.append(th); }
        const thead = document.createElement("thead");
        thead.append(head);
        const tbody = document.createElement("tbody");
        i += 2;
        while (i < lines.length && /\|/.test(lines[i]) && !/^\s*$/.test(lines[i])) {
          const trow = document.createElement("tr");
          for (const text of cells(lines[i])) { const td = document.createElement("td"); inline(text, td); trow.append(td); }
          tbody.append(trow);
          i++;
        }
        table.append(thead, tbody);
        wrap.append(table);
        root.append(wrap);
      } else if (/^#{1,4}\s/.test(line)) {
        const level = line.match(/^#+/)[0].length;
        const h = document.createElement(`h${level}`);
        inline(line.replace(/^#+\s+/, ""), h);
        root.append(h);
        i++;
      } else if (/^\s*([-*+]|\d+[.)])\s+/.test(line)) {
        const ordered = /^\s*\d+[.)]\s+/.test(line);
        const list = document.createElement(ordered ? "ol" : "ul");
        const itemRe = ordered ? /^\s*\d+[.)]\s+/ : /^\s*[-*+]\s+/;
        while (i < lines.length && itemRe.test(lines[i])) {
          const li = document.createElement("li");
          inline(lines[i].replace(itemRe, ""), li);
          list.append(li);
          i++;
        }
        root.append(list);
      } else if (/^>\s?/.test(line)) {
        const quote = document.createElement("blockquote");
        const body = [];
        while (i < lines.length && /^>\s?/.test(lines[i])) body.push(lines[i++].replace(/^>\s?/, ""));
        inline(body.join("\n"), quote);
        root.append(quote);
      } else {
        const p = document.createElement("p");
        const body = [];
        while (
          i < lines.length &&
          !/^\s*$/.test(lines[i]) &&
          !/^(```|#{1,4}\s|>\s?|\s*([-*+]|\d+[.)])\s+)/.test(lines[i])
        ) body.push(lines[i++]);
        body.forEach((text, n) => {
          if (n) p.append(document.createElement("br"));
          inline(text, p);
        });
        root.append(p);
      }
    }
    return root;
  }

  window.renderMarkdown = render;
})();
