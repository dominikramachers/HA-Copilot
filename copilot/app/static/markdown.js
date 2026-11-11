"use strict";

// Kleiner, sicherer Markdown-Renderer: baut ausschließlich DOM-Knoten (nie innerHTML),
// Links nur mit http(s)/mailto. Unterstützt Absätze, Überschriften, (verschachtelte) Listen, Zitate,
// Codeblöcke (``` oder ~~~, auch länger oder eingerückt), **fett**, *kursiv*, `code` und [Text](URL).
// ``renderMarkdownInto`` gleicht eine schon angezeigte Antwort mit dem neuen Stand ab, statt sie neu zu bauen
// (beim Streamen bleiben Knöpfe, Auswahl und Bildlaufposition erhalten).
(function () {
  const SAFE_URL = /^(https?:|mailto:)/i;
  const TABLE_SEP = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;
  const INLINE = /(``[^\n]+?``)|(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(\*[^*\s][^*\n]*\*)|(\[[^\]\n]+\]\([^)\s]+\))/;
  const LI = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/;
  const HR = /^\s*([-*_])(\s*\1){2,}\s*$/;
  const FENCE = /^(\s*)(`{3,}|~{3,})(.*)$/;

  // Der Nur-Text-Modus (``plain``) ist für eigene Nachrichten: dort gibt es nur Listen, sonst bleibt alles, wie getippt.
  function inline(text, parent, plain) {
    if (plain) { parent.append(text); return; }
    let rest = text;
    while (rest) {
      const m = INLINE.exec(rest);
      if (!m) { parent.append(rest); return; }
      if (m.index) parent.append(rest.slice(0, m.index));
      const tok = m[0];
      if (m[1]) {
        const el = document.createElement("code");
        el.textContent = tok.slice(2, -2).trim();
        parent.append(el);
      } else if (m[2]) {
        const el = document.createElement("code");
        el.textContent = tok.slice(1, -1);
        parent.append(el);
      } else if (m[3]) {
        const el = document.createElement("strong");
        inline(tok.slice(2, -2), el);
        parent.append(el);
      } else if (m[4]) {
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

  // Codeblock wie bei Claude: kompakter Kasten, oben rechts kleine Symbolknöpfe (Vorschau, Herunterladen, Kopieren)
  function codeBlock(lines, info) {
    const meta = parseInfo(info);
    const box = document.createElement("div");
    box.className = "codebox";
    box.dataset.info = (info || "").trim();
    const pre = document.createElement("pre");
    const code = document.createElement("code");
    code.textContent = lines.join("\n");
    const tools = document.createElement("div");
    tools.className = "code-tools";
    const show = (button, name, label) => {
      button.replaceChildren(window.kiIcon ? window.kiIcon(name) : document.createTextNode(label));
      button.title = label;
      button.setAttribute("aria-label", label);
    };
    const action = (name, label, handler) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "code-btn";
      show(button, name, label);
      button.addEventListener("click", () => handler(button, () => show(button, name, label)));
      tools.append(button);
      return button;
    };
    // kurz das Ergebnis zeigen (Haken oder Kreuz), dann wieder das Symbol
    const flash = (button, restore, ok, text) => {
      show(button, ok ? "check" : "close", text);
      setTimeout(restore, 1500);
    };
    if (meta.language === "html" && window.kiFile) {
      action("eye", tr("Vorschau"), (button) => window.kiFile.preview(box, button, code.textContent));
    }
    if (window.kiFile) {
      action("download", tr("Herunterladen"), async (button, restore) => {
        try {
          if (await window.kiFile.save(meta.name, code.textContent, meta.mime)) flash(button, restore, true, tr("Gespeichert"));
        } catch { flash(button, restore, false, tr("Nicht möglich")); }
      });
    }
    action("copy", tr("Kopieren"), async (button, restore) => {
      try {
        await navigator.clipboard.writeText(code.textContent);
        flash(button, restore, true, tr("Kopiert"));
      } catch {
        flash(button, restore, false, tr("Nicht möglich"));
      }
    });
    // Platz für die Knöpfe, damit die erste Zeile nicht darunter läuft (der Text bricht um sie herum)
    const gap = document.createElement("span");
    gap.className = "code-gap";
    gap.style.width = `${tools.children.length * 29 + 8}px`;
    code.prepend(gap);
    pre.append(code);
    box.append(pre, tools);
    return box;
  }

  const indentOf = (text) => text.replace(/\t/g, "    ").length;
  const leading = (line) => indentOf(/^\s*/.exec(line)[0]);

  // Öffnende Zeile eines Codeblocks: drei oder mehr ` oder ~, eingerückt erlaubt. Bei ` darf die Sprache selbst kein ` enthalten
  // (sonst ist es Code in einer Zeile, etwa ```x```).
  function fenceStart(line) {
    const m = FENCE.exec(line);
    if (!m || (m[2][0] === "`" && m[3].includes("`"))) return null;
    return { indent: indentOf(m[1]), mark: m[2], info: m[3] };
  }

  // Liest den Block bis zur schließenden Zeile (gleiche Zeichen, mindestens so lang). Fehlt sie noch, läuft er bis zum Ende.
  function readFence(lines, i, fence) {
    const close = new RegExp(`^\\s*${fence.mark[0] === "`" ? "`" : "~"}{${fence.mark.length},}\\s*$`);
    const body = [];
    let j = i + 1;
    let closed = false;
    while (j < lines.length) {
      if (close.test(lines[j])) { closed = true; j++; break; }
      body.push(lines[j++]);
    }
    // Während des Streamens kommt die schließende Zeile Zeichen für Zeichen: ein angefangenes „``“ gehört noch nicht zum Code.
    if (!closed && body.length && /^\s*`{1,2}\s*$/.test(body[body.length - 1])) body.pop();
    const strip = (line) => {
      let width = 0;
      let k = 0;
      while (k < line.length && width < fence.indent && (line[k] === " " || line[k] === "\t")) { width += line[k] === "\t" ? 4 : 1; k++; }
      return line.slice(k);
    };
    return { body: body.map(strip), next: j };
  }

  // Liste ab Zeile ``start``: Einrückung bestimmt die Ebene, tiefere Punkte werden zur Unterliste des Punkts davor.
  function parseList(lines, start, plain) {
    const first = LI.exec(lines[start]);
    const base = indentOf(first[1]);
    const ordered = /\d/.test(first[2]);
    const list = document.createElement(ordered ? "ol" : "ul");
    if (ordered && parseInt(first[2], 10) !== 1) list.start = parseInt(first[2], 10);
    let i = start;
    let last = null;
    while (i < lines.length) {
      const line = lines[i];
      const m = !HR.test(line) && LI.exec(line);
      if (m) {
        const level = indentOf(m[1]);
        if (level < base) break;
        if (level > base && last) {
          const sub = parseList(lines, i, plain);
          last.append(sub.el);
          i = sub.next;
          continue;
        }
        if (/\d/.test(m[2]) !== ordered) break;
        const li = document.createElement("li");
        inline(m[3], li, plain);
        list.append(li);
        last = li;
        i++;
        continue;
      }
      if (/^\s*$/.test(line)) { // Leerzeile: die Liste geht weiter, wenn danach wieder ein Punkt dieser oder einer tieferen Ebene kommt
        let j = i + 1;
        while (j < lines.length && /^\s*$/.test(lines[j])) j++;
        const next = j < lines.length && LI.exec(lines[j]);
        if (next && indentOf(next[1]) >= base) { i = j; continue; }
        if (!next && last && j < lines.length && leading(lines[j]) > base) { i = j; continue; } // eingerückter Absatz oder Codeblock im Punkt
        break;
      }
      if (last && leading(line) > base) { // eingerückte Fortsetzung des Punkts (Text oder Codeblock)
        const fence = !plain && fenceStart(line);
        if (fence) {
          const read = readFence(lines, i, fence);
          last.append(codeBlock(read.body, fence.info));
          i = read.next;
        } else {
          last.append(document.createElement("br"));
          inline(line.trim(), last, plain);
          i++;
        }
        continue;
      }
      break;
    }
    return { el: list, next: i };
  }

  function render(source, options = {}) {
    const plain = !!options.plain;
    const root = document.createElement("div");
    root.className = "md";
    const lines = source.replace(/\r\n?/g, "\n").split("\n");
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      const fence = !plain && fenceStart(line);
      if (fence) {
        const read = readFence(lines, i, fence);
        root.append(codeBlock(read.body, fence.info));
        i = read.next;
      } else if (/^\s*$/.test(line)) {
        i++;
      } else if (!plain && HR.test(line)) {
        root.append(document.createElement("hr"));
        i++;
      } else if (!plain && /\|/.test(line) && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1])) {
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
      } else if (!plain && /^#{1,4}\s/.test(line)) {
        const level = line.match(/^#+/)[0].length;
        const h = document.createElement(`h${level}`);
        inline(line.replace(/^#+\s+/, ""), h);
        root.append(h);
        i++;
      } else if (LI.test(line)) {
        const list = parseList(lines, i, plain);
        root.append(list.el);
        i = list.next;
      } else if (!plain && /^>\s?/.test(line)) {
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
          !(body.length && (LI.test(lines[i]) || (!plain && (fenceStart(lines[i]) || /^(#{1,4}\s|>\s?)/.test(lines[i])))))
        ) body.push(lines[i++]);
        body.forEach((text, n) => {
          if (n) p.append(document.createElement("br"));
          inline(text, p, plain);
        });
        root.append(p);
      }
    }
    return root;
  }

  // ---- Abgleich statt Neuaufbau (Streaming) ----

  const sameKind = (a, b) => a.nodeType === b.nodeType && a.nodeName === b.nodeName && (a.nodeType !== 1 || a.className === b.className);

  function syncAttributes(old, next) {
    for (const { name, value } of [...next.attributes]) if (old.getAttribute(name) !== value) old.setAttribute(name, value);
    for (const { name } of [...old.attributes]) if (!next.hasAttribute(name)) old.removeAttribute(name);
  }

  // Ein Codeblock bleibt als Element bestehen (mit seinen Knöpfen); nur der Text darin wird nachgezogen.
  function syncCode(old, next) {
    const from = next.querySelector("code");
    const to = old.querySelector("code");
    const text = from.lastChild;
    if (to.lastChild && to.lastChild.nodeType === 3 && text && text.nodeType === 3) {
      if (to.lastChild.data !== text.data) to.lastChild.data = text.data;
    } else {
      to.replaceChildren(...[...from.childNodes]);
    }
  }

  function morph(old, next) {
    const before = [...old.childNodes];
    const after = [...next.childNodes];
    after.forEach((n, k) => {
      const o = before[k];
      if (!o) { old.append(n); return; }
      if (o.nodeType === 3 && n.nodeType === 3) { if (o.data !== n.data) o.data = n.data; return; }
      if (!sameKind(o, n)) { o.replaceWith(n); return; }
      if (o.nodeType !== 1) return;
      if (o.classList.contains("codebox")) {
        if (o.dataset.info !== n.dataset.info) o.replaceWith(n);
        else syncCode(o, n);
        return;
      }
      syncAttributes(o, n);
      morph(o, n);
    });
    for (let k = before.length - 1; k >= after.length; k--) before[k].remove();
  }

  function renderInto(container, source, options) {
    const fresh = render(source, options);
    const current = container.firstElementChild;
    if (current && current.classList.contains("md")) morph(current, fresh);
    else container.replaceChildren(fresh);
  }

  window.renderMarkdown = render;
  window.renderMarkdownInto = renderInto;
})();
