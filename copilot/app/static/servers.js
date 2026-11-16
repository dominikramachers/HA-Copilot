"use strict";
// Linux-Server (ab 0.60.4): Übersicht, Aktivität und „Server hinzufügen“ (Installationsskript mit allen Angaben).
// Nutzt die Hilfen aus app.js ($, node, icon, api, tr, toast, state, skillHead, errorText, ago, kiLocale, setView …).
//
// Die Seite zeigt nur, was der Hub im Add-on weiß. Ein neuer Server erscheint als „Ausstehend“ und wird erst nach der
// Bestätigung hier für die KI nutzbar (nur lesend). Das Skript enthält einen frischen Registrierungsschlüssel, die Adresse des Hubs
// und den Fingerabdruck der Hub-CA; es wird nur im Arbeitsspeicher gehalten, nie gespeichert.

const srvUi = {
  tab: "overview",            // overview | activity | add
  data: null,                 // Antwort von api/servers
  activity: null,
  filter: { server: "", kind: "", days: 7 },
  form: { hub: "", name: "", hours: 24, uses: 1 },
  script: null,               // { script, filename, expires, uses }
  busy: false,
  status: "",
  editing: false,             // Name wird gerade geändert: Aktualisierung pausiert
  timer: 0,
};

const SRV_STATUS = {
  online: ["●", () => tr("Online")],
  degraded: ["▲", () => tr("Eingeschränkt")],
  offline: ["○", () => tr("Offline")],
  pending: ["◆", () => tr("Ausstehend")],
  blocked: ["⊘", () => tr("Gesperrt")],
};

function initServers() {
  const button = $("nav-servers");
  if (!button) return;
  button.hidden = !state.me?.servers;
  if (button.dataset.bound) return;
  button.dataset.bound = "1";
  button.addEventListener("click", () => { openServers().catch(() => {}); });
}

function srvStop() {
  clearInterval(srvUi.timer);
  srvUi.timer = 0;
}

async function openServers(tab = "overview") {
  if (!state.me?.servers) return;
  setView("servers");
  rememberDetail(tab);
  detachRun();
  releaseRecent();
  state.activeId = null;
  rememberActive();
  state.newProject = null;
  state.heldUnread = null;
  renderSide();
  closeMenu();
  setTitle(tr("Server"));
  srvUi.tab = ["overview", "activity", "add"].includes(tab) ? tab : "overview";
  srvUi.status = "";
  srvUi.script = null;
  srvUi.editing = false;
  renderServers();
  await srvLoad();
  srvStop();
  srvUi.timer = setInterval(() => { if (state.view === "servers" && !document.hidden) srvLoad(true).catch(() => {}); }, 15000);
  $("servers").scrollTop = 0;
}

async function srvLoad(quiet = false) {
  try {
    srvUi.data = await api("api/servers");
    if (!srvUi.form.hub) srvUi.form.hub = srvUi.data.hub.address || location.hostname || "";
    if (srvUi.tab === "activity") await srvLoadActivity(true);
  } catch (err) {
    if (!quiet) srvUi.status = errorText(err, tr("Die Server sind gerade nicht erreichbar."));
  }
  if (state.view === "servers" && !(quiet && (srvUi.editing || srvUi.tab === "add"))) renderServers();
}

async function srvLoadActivity(skipRender = false) {
  const q = new URLSearchParams({ days: String(srvUi.filter.days) });
  if (srvUi.filter.server) q.set("server", srvUi.filter.server);
  if (srvUi.filter.kind) q.set("kind", srvUi.filter.kind);
  try { srvUi.activity = (await api(`api/servers/activity?${q}`)).items; } catch (err) { srvUi.status = errorText(err, tr("Die Aktivität ist gerade nicht erreichbar.")); }
  if (!skipRender && state.view === "servers") renderServers();
}

function srvTime(iso) {
  try { return new Date(iso).toLocaleString(kiLocale, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }); } catch { return ""; }
}

function srvAgo(iso) {
  const ms = Date.parse(iso || "");
  return Number.isFinite(ms) ? ago(ms / 1000) : tr("noch nie");
}

function srvDuration(seconds) {
  if (!Number.isFinite(seconds)) return "–";
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days) return tr("{0} Tage {1} Std.", days, hours);
  if (hours) return tr("{0} Std. {1} Min.", hours, minutes);
  return tr("{0} Min.", minutes);
}

function srvBadge(status) {
  const [glyph, label] = SRV_STATUS[status] || SRV_STATUS.offline;
  const badge = node("span", `srv-badge ${status}`);
  badge.append(node("span", "srv-glyph", glyph), node("span", "", label()));
  return badge;
}

async function srvAct(path, method, body, done) {
  try {
    await api(path, { method, ...(body ? { body: JSON.stringify(body) } : {}) });
    if (done) toast(done);
  } catch (err) {
    toast(errorText(err, tr("Das hat nicht geklappt.")));
  }
  await srvLoad();
}

// ------------------------------------------------------------- Seite

function renderServers() {
  const wrap = $("servers-wrap");
  wrap.replaceChildren();
  skillHead(wrap, tr("Server"), tr("Deine Linux-Server melden sich hier von selbst. Die KI darf sie nur ansehen, nichts verändern."));

  const bar = node("div", "skills-bar");
  const tabs = node("div", "skills-tabs");
  tabs.setAttribute("role", "tablist");
  const pending = srvUi.data?.summary?.pending || 0;
  for (const [id, label] of [["overview", tr("Übersicht")], ["activity", tr("Aktivität")], ["add", tr("Server hinzufügen")]]) {
    const tab = node("button", "skills-tab", label);
    tab.type = "button";
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-selected", String(srvUi.tab === id));
    if (id === "overview" && pending) tab.append(node("span", "srv-count", String(pending)));
    tab.addEventListener("click", () => {
      srvUi.tab = id;
      srvUi.status = "";
      srvUi.editing = false;
      rememberDetail(id);
      renderServers();
      if (id === "activity") srvLoadActivity().catch(() => {});
    });
    tabs.append(tab);
  }
  bar.append(tabs);
  wrap.append(bar);

  const status = node("p", "skills-status", srvUi.status);
  status.setAttribute("role", "status");
  wrap.append(status);

  if (!srvUi.data) {
    if (!srvUi.status) wrap.append(node("p", "skills-status", tr("Wird geladen …")));
    return;
  }
  if (srvUi.tab === "activity") renderServerActivity(wrap);
  else if (srvUi.tab === "add") renderServerAdd(wrap);
  else renderServerOverview(wrap);
}

// ------------------------------------------------------------- Übersicht

function renderServerOverview(wrap) {
  const { servers, summary } = srvUi.data;
  const tiles = node("div", "srv-tiles");
  for (const key of ["online", "degraded", "offline", "pending", "blocked"]) {
    const tile = node("div", `srv-tile ${key}`);
    tile.append(node("b", "", String(summary[key] || 0)), srvBadge(key));
    tiles.append(tile);
  }
  wrap.append(tiles);

  const pending = servers.filter((s) => s.status === "pending");
  if (pending.length) {
    const box = node("section", "srv-pending");
    box.append(node("h3", "", tr("Ausstehend: wartet auf deine Bestätigung")));
    box.append(node("p", "srv-note", tr("Diese Server haben sich gemeldet, aber noch niemand hat sie bestätigt. Erst danach darf die KI sie ansehen. Bestätige nur Server, die du kennst.")));
    for (const s of pending) box.append(serverCard(s));
    wrap.append(box);
  }

  const rest = servers.filter((s) => s.status !== "pending");
  if (!servers.length) {
    const empty = node("div", "sched-empty");
    empty.append(node("p", "", tr("Noch kein Server gemeldet.")), node("p", "sched-note", tr("Unter „Server hinzufügen“ bekommst du ein Skript, das du auf dem Server ausführst.")));
    const go = node("button", "pill primary small", tr("Server hinzufügen"));
    go.type = "button";
    go.addEventListener("click", () => { srvUi.tab = "add"; rememberDetail("add"); renderServers(); });
    empty.append(go);
    wrap.append(empty);
    return;
  }
  if (rest.length) {
    const list = node("div", "srv-list");
    for (const s of rest) list.append(serverCard(s));
    wrap.append(list);
  }
}

function srvFact(label, value, bad) {
  const dt = node("dt", "", label);
  const dd = node("dd", bad ? "bad" : "", value);
  return [dt, dd];
}

function serverCard(s) {
  const info = s.info || {};
  const card = node("article", `srv-card ${s.status}`);
  const head = node("div", "srv-head");
  const title = node("div", "srv-title");
  const name = node("h3", "", s.name);
  title.append(name, srvBadge(s.status));
  head.append(title);
  card.append(head);
  if (s.reasons?.length) card.append(node("p", "srv-reasons", s.reasons.join(" · ")));

  const facts = node("dl", "srv-facts");
  const add = (label, value, bad) => { if (value !== "" && value != null) facts.append(...srvFact(label, String(value), bad)); };
  add(tr("Adresse"), s.ip || "–");
  add(tr("System"), info.os || "–");
  add(tr("Laufzeit"), info.uptime_s != null ? srvDuration(info.uptime_s) : "–");
  if (info.load1 != null) add(tr("Last"), `${info.load1} / ${info.cpus || "?"} ${tr("Kerne")}`, info.cpus && info.load1 > info.cpus * 1.5);
  if (info.mem_used_pct != null) add(tr("Arbeitsspeicher"), `${Math.round(info.mem_used_pct)} %`, info.mem_used_pct >= 90);
  if (info.disk_worst_pct != null) add(tr("Fester Speicher"), `${Math.round(info.disk_worst_pct)} % ${info.disk_worst_mount || ""}`.trim(), info.disk_worst_pct >= 90);
  if (info.failed_units != null) add(tr("Fehlgeschlagene Dienste"), info.failed_units ? `${info.failed_units}: ${(info.failed_unit_names || []).join(", ")}` : tr("keine"), info.failed_units > 0);
  if (info.updates != null) add(tr("Updates"), info.updates === 0 ? tr("keine") : String(info.updates));
  if (info.reboot_required) add(tr("Neustart"), tr("erforderlich"), true);
  add(tr("Letzte Meldung"), s.last_seen_at ? srvAgo(s.last_seen_at) : tr("noch nie"));
  if (info.agent_version) add(tr("Agent"), info.agent_version);
  card.append(facts);

  const foot = node("div", "sched-foot");
  const button = (label, cls, run) => {
    const b = node("button", `pill ${cls}`, label);
    b.type = "button";
    b.addEventListener("click", run);
    return b;
  };
  if (s.state === "pending") {
    foot.append(
      button(tr("Ablehnen"), "ghost", () => srvAct(`api/servers/${s.id}`, "DELETE", null, tr("Der Server wurde abgelehnt."))),
      button(tr("Bestätigen"), "primary", () => srvAct(`api/servers/${s.id}/confirm`, "POST", null, tr("Bestätigt. Die KI darf diesen Server jetzt ansehen."))),
    );
  } else {
    foot.append(button(tr("Umbenennen"), "ghost", () => srvRename(card, name, s)));
    if (s.state === "blocked") foot.append(button(tr("Entsperren"), "ghost", () => srvAct(`api/servers/${s.id}/unblock`, "POST", null, tr("Entsperrt."))));
    else foot.append(button(tr("Sperren"), "ghost", () => srvAct(`api/servers/${s.id}/block`, "POST", null, tr("Gesperrt. Der Server wird getrennt."))));
    let armed = 0;
    const remove = button(tr("Entfernen"), "ghost", () => {
      if (!armed) {
        remove.textContent = tr("Wirklich entfernen?");
        remove.classList.add("danger");
        armed = setTimeout(() => { armed = 0; remove.textContent = tr("Entfernen"); remove.classList.remove("danger"); }, 3500);
        return;
      }
      clearTimeout(armed);
      srvAct(`api/servers/${s.id}`, "DELETE", null, tr("Der Server wurde entfernt."));
    });
    foot.append(remove);
  }
  card.append(foot);
  return card;
}

function srvRename(card, heading, s) {
  srvUi.editing = true;
  const input = node("input", "field srv-rename");
  input.value = s.name;
  input.maxLength = 120;
  input.setAttribute("aria-label", tr("Name des Servers"));
  const save = async () => {
    const value = input.value.trim();
    srvUi.editing = false;
    if (value && value !== s.name) await srvAct(`api/servers/${s.id}`, "PATCH", { name: value }, tr("Umbenannt."));
    else renderServers();
  };
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); save(); }
    if (event.key === "Escape") { srvUi.editing = false; renderServers(); }
  });
  input.addEventListener("blur", save);
  heading.replaceWith(input);
  input.focus();
  input.select();
}

// ------------------------------------------------------------- Aktivität

const SRV_KINDS = () => [["", tr("Alle Arten")], ["read", tr("Lesen")], ["change", tr("Änderungen")], ["event", tr("Ereignisse")]];
const SRV_DAYS = () => [[1, tr("Letzte 24 Stunden")], [7, tr("Letzte 7 Tage")], [30, tr("Letzte 30 Tage")], [90, tr("Letzte 90 Tage")]];

function renderServerActivity(wrap) {
  const filter = node("div", "skills-filter srv-filter");
  const select = (label, options, current, set) => {
    const el = node("select", "field");
    el.setAttribute("aria-label", label);
    for (const [value, text] of options) {
      const o = node("option", "", text);
      o.value = String(value);
      o.selected = String(value) === String(current);
      el.append(o);
    }
    el.addEventListener("change", () => { set(el.value); srvLoadActivity().catch(() => {}); });
    return el;
  };
  filter.append(
    select(tr("Server"), [["", tr("Alle Server")], ...srvUi.data.servers.map((s) => [s.id, s.name])], srvUi.filter.server, (v) => { srvUi.filter.server = v; }),
    select(tr("Art"), SRV_KINDS(), srvUi.filter.kind, (v) => { srvUi.filter.kind = v; }),
    select(tr("Zeitraum"), SRV_DAYS(), srvUi.filter.days, (v) => { srvUi.filter.days = Number(v); }),
  );
  wrap.append(filter);

  const items = srvUi.activity;
  if (!items) { wrap.append(node("p", "skills-status", tr("Wird geladen …"))); return; }
  if (!items.length) { wrap.append(node("p", "srv-note", tr("Keine Einträge im gewählten Zeitraum."))); return; }
  const list = node("ol", "srv-log");
  for (const item of items) {
    const row = node("li", `srv-log-row ${item.result || ""}`);
    const top = node("div", "srv-log-top");
    top.append(
      node("span", "srv-log-time", srvTime(item.ts)),
      node("span", `srv-kind ${item.kind}`, (SRV_KINDS().find(([k]) => k === item.kind) || ["", item.kind])[1]),
      node("b", "", item.server_name || tr("Hub")),
    );
    if (item.result && item.result !== "ok") top.append(node("span", `srv-result ${item.result}`, srvResult(item.result)));
    row.append(top, node("p", "srv-log-text", item.summary));
    const more = [item.command && `${tr("Aufruf")}: ${item.command}`, item.actor && `${tr("Von")}: ${item.actor}`, item.detail].filter(Boolean);
    if (more.length) row.append(node("p", "srv-log-more", more.join(" · ")));
    list.append(row);
  }
  wrap.append(list);
  wrap.append(node("p", "sched-note", tr("Das Protokoll wird 90 Tage aufbewahrt.")));
}

function srvResult(result) {
  return { denied: tr("Abgelehnt"), error: tr("Fehler"), pending: tr("Ausstehend"), offline: tr("Offline") }[result] || result;
}

// ------------------------------------------------------------- Server hinzufügen

async function srvCopy(text, input) {
  try {
    await navigator.clipboard.writeText(text);
    toast(tr("Skript kopiert. Auf dem Server als root einfügen."));
  } catch {
    try {
      input.focus();
      input.select();
      document.execCommand("copy");
      toast(tr("Skript kopiert. Auf dem Server als root einfügen."));
    } catch {
      toast(tr("Zum Kopieren Strg+C drücken."));
    }
  }
}

function srvDownload(script) {
  const blob = new Blob([script.script], { type: "text/x-shellscript" });
  const url = URL.createObjectURL(blob);
  const link = node("a");
  link.href = url;
  link.download = script.filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

async function srvCreateScript() {
  const form = srvUi.form;
  srvUi.busy = true;
  srvUi.status = "";
  renderServers();
  try {
    const result = await api("api/servers/install-script", {
      method: "POST",
      body: JSON.stringify({ hub: form.hub.trim(), name: form.uses === 1 ? form.name.trim() : "", hours: form.hours, max_uses: form.uses }),
    });
    srvUi.script = { ...result, uses: form.uses };
    await srvLoad(true);
  } catch (err) {
    srvUi.status = errorText(err, tr("Das Skript konnte nicht erstellt werden."));
  }
  srvUi.busy = false;
  renderServers();
}

function renderServerAdd(wrap) {
  const { hub, keys } = srvUi.data;
  const form = srvUi.form;
  const card = node("section", "srv-add");
  card.append(
    node("h3", "", tr("Neuen Server verbinden")),
    node("p", "srv-note", tr("Du bekommst ein Skript mit allem, was der Server braucht: Adresse, Schlüssel und Prüfsummen. Führe es auf dem Server als root aus. Danach erscheint der Server hier als „Ausstehend“, und du bestätigst ihn.")),
  );
  if (!hub.agents.length) {
    card.append(node("p", "srv-reasons", tr("In diesem Add-on ist keine Programmdatei des Agenten enthalten. Bitte das Add-on neu bauen oder aktualisieren.")));
    wrap.append(card);
    return;
  }

  const fields = node("div", "srv-form");
  const field = (label, el, hint) => {
    const box = node("label", "srv-field");
    box.append(node("span", "sheet-label", label), el);
    if (hint) box.append(node("small", "srv-hint", hint));
    return box;
  };
  const address = node("input", "field");
  address.value = form.hub;
  address.placeholder = "ha.example.lan";
  address.autocomplete = "off";
  address.spellcheck = false;
  address.addEventListener("input", () => { form.hub = address.value; });
  const name = node("input", "field");
  name.value = form.uses === 1 ? form.name : "";
  name.disabled = form.uses !== 1;
  name.maxLength = 63;
  name.placeholder = tr("z. B. web01");
  name.autocomplete = "off";
  name.addEventListener("input", () => { form.name = name.value; });
  const hours = node("select", "field");
  for (const [value, text] of [[1, tr("1 Stunde")], [24, tr("24 Stunden")], [168, tr("7 Tage")], [336, tr("14 Tage")]]) {
    const o = node("option", "", text);
    o.value = String(value);
    o.selected = value === form.hours;
    hours.append(o);
  }
  hours.addEventListener("change", () => { form.hours = Number(hours.value); });
  const uses = node("input", "field");
  uses.type = "number";
  uses.min = "1";
  uses.max = "100";
  uses.value = String(form.uses);
  uses.addEventListener("change", () => {
    form.uses = Math.max(1, Math.min(100, Math.floor(Number(uses.value) || 1)));
    renderServers();
  });
  fields.append(
    field(tr("Adresse des Hubs"), address, tr("So erreichen die Server diesen Home-Assistant-Rechner. Der Port {0} wird ergänzt.", hub.port)),
    field(tr("Name des Servers (optional)"), name, form.uses === 1 ? tr("Sonst gilt der Hostname.") : tr("Bei mehreren Servern gilt jeweils der Hostname.")),
    field(tr("Das Skript gilt"), hours, tr("Danach ist der Schlüssel im Skript ungültig.")),
    field(tr("Für wie viele Server"), uses, tr("Der Schlüssel wird nach so vielen Anmeldungen ungültig.")),
  );
  card.append(fields);

  const make = node("button", "pill primary small", srvUi.busy ? tr("Wird erstellt …") : tr("Skript erstellen"));
  make.type = "button";
  make.disabled = srvUi.busy || !form.hub.trim();
  make.addEventListener("click", () => { srvCreateScript(); });
  address.addEventListener("input", () => { make.disabled = srvUi.busy || !address.value.trim(); });
  card.append(make);
  wrap.append(card);

  if (srvUi.script) wrap.append(renderScriptResult(srvUi.script, hub));

  const active = keys.filter((k) => k.active);
  const list = node("section", "srv-keys");
  list.append(node("h3", "", tr("Gültige Schlüssel")));
  if (!active.length) {
    list.append(node("p", "srv-note", tr("Zurzeit gibt es keinen gültigen Schlüssel. Für jedes neue Skript entsteht ein neuer.")));
  } else {
    for (const k of active) {
      const row = node("div", "srv-key");
      const text = node("div", "srv-key-text");
      text.append(node("b", "", k.label || tr("Installationsskript")), node("small", "", tr("{0} von {1} genutzt · gültig bis {2} · erstellt von {3}", k.uses, k.max_uses, srvTime(k.expires_at), k.created_by || "–")));
      const revoke = node("button", "pill ghost", tr("Widerrufen"));
      revoke.type = "button";
      revoke.addEventListener("click", () => srvAct(`api/servers/keys/${k.id}`, "DELETE", null, tr("Der Schlüssel ist widerrufen.")));
      row.append(text, revoke);
      list.append(row);
    }
  }
  wrap.append(list);

  const finger = node("section", "srv-keys");
  finger.append(node("h3", "", tr("Sicherheit")), node("p", "srv-note", tr("Der Agent baut die Verbindung selbst auf und prüft den Hub über diesen Fingerabdruck. Wenn sich der Fingerabdruck ändert, ist die CA neu erzeugt worden und alle Server müssen neu angemeldet werden.")));
  finger.append(node("code", "srv-print", hub.fingerprint || "–"));
  wrap.append(finger);
}

function renderScriptResult(script, hub) {
  const box = node("section", "srv-script");
  box.append(node("h3", "", tr("Dein Skript")));
  box.append(node("p", "srv-note", tr("Enthält einen geheimen Schlüssel für {0} Server, gültig bis {1}. Nicht weitergeben und nicht in Chats oder Tickets einfügen.", script.uses, srvTime(script.expires))));
  const area = node("textarea", "srv-code");
  area.readOnly = true;
  area.value = script.script;
  area.rows = 12;
  area.spellcheck = false;
  area.setAttribute("aria-label", tr("Installationsskript"));
  const buttons = node("div", "srv-script-buttons");
  const copy = node("button", "pill primary small", tr("Kopieren"));
  copy.type = "button";
  copy.prepend(icon("copy"));
  copy.addEventListener("click", () => { srvCopy(script.script, area); });
  const download = node("button", "pill ghost small", tr("Herunterladen"));
  download.type = "button";
  download.prepend(icon("download"));
  download.addEventListener("click", () => srvDownload(script));
  buttons.append(copy, download);
  box.append(buttons, area);
  const how = node("p", "srv-note");
  how.append(tr("Auf dem Server als root ausführen:"), " ");
  how.append(node("code", "", `sudo bash ${script.filename}`));
  box.append(how, node("p", "srv-note", tr("Der Server muss {0} auf Port {1} erreichen (Firewall).", srvUi.form.hub.trim() || "–", hub.port)));
  return box;
}
