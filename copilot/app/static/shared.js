"use strict";
// Öffentliche Leseseite eines geteilten Chats (ohne Anmeldung). Der Server liefert nur Titel, Text und Zeitpunkte;
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
