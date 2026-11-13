"use strict";
// Öffentliche Leseseite eines geteilten Chats oder Artefakts (ohne Anmeldung). Der Server liefert nur Titel, Text und Zeitpunkte;
// angezeigt wird alles als Text beziehungsweise über den sicheren Markdown-Renderer (nie als HTML).
(async function () {
  const $ = (id) => document.getElementById(id);
  const token = location.pathname.split("/").filter(Boolean).pop() || "";
  const fail = (text) => { $("error").textContent = text; $("error").hidden = false; $("note").hidden = true; document.title = tr("Nicht gefunden"); };
  let data;
  try {
    const response = await fetch(`/s/${encodeURIComponent(token)}/data`, { credentials: "omit", headers: { Accept: "application/json" } });
    if (response.status === 429) { fail(tr("Bitte etwas später noch einmal versuchen.")); return; }
    if (!response.ok) { fail(tr("Dieser Link ist ungültig oder abgelaufen.")); return; }
    data = await response.json();
  } catch {
    fail(tr("Der Chat konnte nicht geladen werden."));
    return;
  }
  const when = (iso) => { const d = new Date(iso); return Number.isNaN(d.getTime()) ? "" : d.toLocaleString(kiLocale, { dateStyle: "medium", timeStyle: "short" }); };
  $("title").textContent = data.title;
  document.title = `${data.title} – ${document.title.split("–").pop().trim()}`;
  $("meta").textContent = tr("Stand: {0}", when(data.taken_at)) + (data.expires_at ? " · " + tr("Link gültig bis {0}", when(data.expires_at)) : "");
  const thread = $("thread");
  if (data.artifact) {
    // Geteiltes Artefakt: nur der Text, als Textknoten in einem <pre>; nie als Seite ausgeführt, nie als HTML gedeutet.
    $("note").textContent = tr("Das ist ein geteiltes Artefakt. Du siehst nur den Text und kannst ihn kopieren. Er zeigt den Stand vom Zeitpunkt des Teilens.");
    const pre = document.createElement("pre");
    pre.className = "shared-code";
    pre.tabIndex = 0;
    const code = document.createElement("code");
    code.textContent = data.artifact.content;
    pre.append(code);
    const copy = document.createElement("button");
    copy.type = "button";
    copy.className = "pill ghost small shared-copy";
    copy.textContent = tr("Code kopieren");
    copy.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(data.artifact.content); copy.textContent = tr("Code kopiert."); } catch { copy.textContent = tr("Kopieren nicht möglich."); }
      setTimeout(() => { copy.textContent = tr("Code kopieren"); }, 1800);
    });
    thread.append(copy, pre);
    return;
  }
  for (const m of data.messages) {
    if (m.role === "user") {
      const bubble = document.createElement("div");
      bubble.className = "msg user";
      bubble.textContent = m.content;
      const group = document.createElement("div");
      group.className = "msg-group user-group";
      group.append(bubble);
      thread.append(group);
    } else {
      const el = document.createElement("div");
      el.className = "msg assistant";
      el.append(window.renderMarkdown(m.content));
      thread.append(el);
    }
  }
})();
