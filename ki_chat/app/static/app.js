"use strict";

// Alle Pfade sind relativ, damit die Seite unter dem Ingress-Pfad von Home Assistant funktioniert.
const $ = (id) => document.getElementById(id);
const state = { view: "chat", schedules: [], files: [], recent: [], chats: [], projects: [], activeId: null, newProject: null, streaming: null, me: null, effort: "medium", heldUnread: null, shownAt: null, model: "", web: true };
const ui = { projectsOpen: true, openProjects: new Set(), showAll: false };

// ---------------------------------------------------------------- Hilfen

const SVG_NS = "http://www.w3.org/2000/svg";
const ICONS = {
  download: ["M12 4v11M7 11l5 5 5-5M5 20h14"],
  attach: ["M20.5 11.5l-8.2 8.2a5 5 0 0 1-7.1-7.1l8.5-8.5a3.3 3.3 0 0 1 4.7 4.7l-8.5 8.5a1.7 1.7 0 0 1-2.4-2.4l7.8-7.8"],
  note: ["M6 4h12v16H6z", "M9 9h6M9 13h6M9 17h3"],
  file: ["M7 3h7l5 5v13H7z", "M14 3v5h5"],
  picture: ["M4 5h16v14H4z", "M4 16l5-5 4 4 3-3 4 4", "M9 9.5h.01"],
  edit: ["M16.5 4.5l3 3L8 19l-4 1 1-4z"],
  trash: ["M5 7h14M10 7V5h4v2M7 7l1 12h8l1-12"],
  arrowUp: ["M12 19V5M6 11l6-6 6 6"],
  stop: ["M7 7h10v10H7z"],
  copy: ["M9 9h10v10H9zM5 15V5h10"],
  check: ["M5 12l5 5 9-10"],
  more: ["M5 12h.01M12 12h.01M19 12h.01"],
  pin: ["M9 4h6l-1 5 3 3v2H7v-2l3-3zM12 14v7"],
  plus: ["M12 5v14M5 12h14"],
  chevron: ["M9 6l6 6-6 6"],
  folder: ["M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"],
  chat: ["M20 15a2 2 0 0 1-2 2H8l-4 4V6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2z"],
  fold: ["M4 8l4 4-4 4M12 6h8M12 12h8M12 18h8"],
  close: ["M6 6l12 12M18 6L6 18"],
  info: ["M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17z", "M12 11v5.5", "M12 7.8h.01"],
  bolt: ["M13 3L5 13.5h6L10 21l8-10.5h-6z"],
  bug: ["M9 7a3 3 0 0 1 6 0M8 9h8v5a4 4 0 0 1-8 0zM4 10l4 1.5M20 10l-4 1.5M4 18l4-2M20 18l-4-2M12 9v10"],
  code: ["M8 8l-4 4 4 4M16 8l4 4-4 4M13.5 5l-3 14"],
  pen: ["M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"],
  eye: ["M2.5 12C3.5 10.5 7 6 12 6s8.5 4.5 9.5 6c-1 1.5-4.5 6-9.5 6s-8.5-4.5-9.5-6z", "M12 9.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5z"],
  eyeOff: ["M3 3l18 18", "M10.6 6.1A9.6 9.6 0 0 1 12 6c5 0 8.5 4.5 9.5 6a14 14 0 0 1-3.2 3.6M6.5 7.6A14 14 0 0 0 2.5 12c1 1.5 4.5 6 9.5 6 1.5 0 2.8-.4 4-1", "M9.9 10a3 3 0 0 0 4.1 4.1"],
  stack: ["M7 5h10M5 9h14M4 13h16l-1.5 6h-13z"],
  memory: ["M12 3a5 5 0 0 0-5 5c0 2 1 3 2 4v2h6v-2c1-1 2-2 2-4a5 5 0 0 0-5-5z", "M10 18h4M10.5 21h3"],
  sun: ["M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z", "M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M18.7 5.3l-1.4 1.4M6.7 17.3l-1.4 1.4"],
  logout: ["M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4M10 16l-4-4 4-4M6 12h11"],
  upload: ["M12 16V5M7 9l5-5 5 5M5 20h14"],
  globe: ["M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z", "M3 12h18", "M12 3c2.5 2.5 3.8 5.5 3.8 9s-1.3 6.5-3.8 9c-2.5-2.5-3.8-5.5-3.8-9S9.5 5.5 12 3z"],
  clock: ["M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16z", "M12 8v4.5l3 1.8"],
  search: ["M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z", "M16.5 16.5L21 21"],
  setup: ["M4 6.5l1.8 1.8L9 5", "M4 14.5l1.8 1.8L9 13", "M13 7h7", "M13 15h7"],
  data: ["M5 7c0-1.7 3.1-3 7-3s7 1.3 7 3-3.1 3-7 3-7-1.3-7-3z", "M5 7v10c0 1.7 3.1 3 7 3s7-1.3 7-3V7", "M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3"],
  play: ["M8 5.5v13l10.5-6.5z"],
  pause: ["M8 6v12M16 6v12"],
  folderX: ["M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z", "M9.5 11.5l5 5M14.5 11.5l-5 5"],
};

function icon(name, solid) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("class", "icon" + (solid ? " solid" : ""));
  for (const d of ICONS[name]) {
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
}

function node(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text != null) el.textContent = text;
  return el;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers: {
      "X-Requested-With": "ki-chat",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
  });
  if (response.status === 401) { window.location.assign("login"); throw new Error("HTTP 401"); }
  if (!response.ok) {
    const error = new Error(`HTTP ${response.status}`);
    error.status = response.status;
    try { error.detail = (await response.json()).detail; } catch { /* keine Meldung */ }
    throw error;
  }
  return response.status === 204 ? null : response.json();
}

let toastTimer = 0;
function toast(text) {
  const el = $("toast");
  el.textContent = text;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 4000);
}

// ------------------------------------------------------- Sheet (Dialog)

let sheetDone = null;
let sheetOnOk = null; // Formular im Fenster: prüft und speichert selbst; true = Fenster schließen
function closeSheet(result) {
  sheetOnOk = null;
  $("sheet").classList.remove("show");
  $("sheet-scrim").classList.remove("show");
  setTimeout(() => { if (!sheetDone) $("sheet").hidden = true; }, 260);
  const done = sheetDone;
  sheetDone = null;
  if (done) done(result);
}

// Ein Fenster von unten für drei Fälle: Bestätigen, Text eingeben, aus einer Liste wählen (``items``).
// Ergebnis: ``null`` bei Abbruch, sonst true, der Text oder der ``value`` des gewählten Eintrags.
let sheetMultiline = false;
function openSheet({ title, sub = "", label = "", value = null, placeholder = "", ok = tr("OK"), danger = false, items = null, multiline = false, panel = null, onOk = null, plain = false }) {
  return new Promise((resolve) => {
    if (sheetDone) closeSheet(null);
    sheetDone = resolve;
    sheetOnOk = onOk;
    $("sheet-title").textContent = title;
    $("sheet-sub").textContent = sub;
    $("sheet").dataset.plain = plain ? "1" : "";
    $("sheet").dataset.kind = panel ? "panel" : items ? "list" : multiline ? "multiline" : value !== null ? "input" : "confirm";
    const field = $("sheet-label");
    field.textContent = label;
    field.hidden = !label || !!items || !!panel || (value === null && !multiline);
    field.htmlFor = multiline ? "sheet-text" : "sheet-input";
    const input = multiline ? $("sheet-text") : $("sheet-input");
    $("sheet-input").hidden = multiline || value === null || !!panel;
    $("sheet-text").hidden = !multiline || !!panel;
    input.value = value ?? "";
    input.placeholder = placeholder;
    const count = $("sheet-count");
    count.hidden = !multiline || !!panel;
    const updateCount = () => { count.textContent = `${input.value.length} / ${input.maxLength}`; };
    updateCount();
    input.oninput = multiline ? updateCount : null;
    sheetMultiline = multiline;
    const list = $("sheet-list");
    list.replaceChildren();
    list.hidden = !items;
    $("sheet-actions").hidden = !!items || plain;
    $("sheet-cancel").hidden = !!panel && !onOk;
    const body = $("sheet-panel");
    body.replaceChildren();
    body.hidden = !panel;
    if (panel) panel(body);
    for (const entry of items || []) {
      const row = node("button", "sheet-item" + (entry.danger ? " danger" : "") + (entry.active ? " active" : ""));
      row.type = "button";
      if (entry.icon) row.append(icon(entry.icon));
      row.append(node("span", "", entry.label));
      if (entry.active) row.append(icon("check"));
      row.addEventListener("click", () => closeSheet(entry.value));
      list.append(row);
    }
    const okBtn = $("sheet-ok");
    okBtn.textContent = ok;
    okBtn.className = "pill " + (danger ? "danger" : "primary");
    $("sheet").hidden = false;
    requestAnimationFrame(() => {
      $("sheet").classList.add("show");
      $("sheet-scrim").classList.add("show");
      if (items) list.querySelector("button")?.focus();
      else if (panel && onOk) { if (window.matchMedia("(pointer: fine)").matches) body.querySelector("input, textarea")?.focus(); }
      else if (panel) (body.querySelector("input[type=search]") || okBtn).focus();
      else if (value === null) (danger ? $("sheet-cancel") : okBtn).focus(); // Löschen nie als Vorauswahl
      else input.focus();
      if (value !== null && !multiline && !panel) input.select();
    });
  });
}

function initSheet() {
  $("sheet-close").append(icon("close"));
  $("sheet-close").addEventListener("click", () => closeSheet(null));
  $("sheet-cancel").addEventListener("click", () => closeSheet(null));
  $("sheet-scrim").addEventListener("click", () => closeSheet(null));
  $("sheet-ok").addEventListener("click", async () => {
    if (sheetOnOk) {
      const button = $("sheet-ok");
      const handler = sheetOnOk;
      button.disabled = true;
      let done = false;
      try { done = await handler(); } catch { done = false; } finally { button.disabled = false; }
      if (done) closeSheet(true);
      return;
    }
    // Mehrzeiliges Feld darf leer bestätigt werden (z. B. Anweisungen löschen); das einzeilige nicht.
    if (sheetMultiline) closeSheet($("sheet-text").value.trim());
    else closeSheet($("sheet-input").hidden ? true : $("sheet-input").value.trim() || null);
  });
  $("sheet-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); $("sheet-ok").click(); }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const fullscreen = document.querySelector(".preview.full");
    if (pop) closePopover(null);
    else if (sheetDone) closeSheet(null);
    else if (fullscreen) fullscreen.classList.remove("full");
    else closeMenu();
  });
}


// ------------------------------------------------- Popover-Menü (Computer, Tablet)

// Am Computer und Tablet öffnen die Aktionen als kleines Menü direkt am Auslöser, auf dem Handy bleibt es ein Fenster von unten.
const wideScreen = () => window.matchMedia("(min-width: 640px) and (min-height: 520px)").matches;
let pop = null;

function closePopover(result = null) {
  if (!pop) return;
  const current = pop;
  pop = null;
  current.off();
  for (const el of current.nodes) el.remove();
  current.anchorRow?.classList.remove("menu-open");
  current.done(result);
}

// Menü unter den Auslöser setzen (passt es unten nicht, darüber) oder ein Untermenü neben den Eintrag; immer im sichtbaren Bereich.
function placePopover(el, rect, beside) {
  el.style.left = "0px";
  el.style.top = "0px";
  const { width, height } = el.getBoundingClientRect();
  const margin = 8;
  let x = beside ? rect.right + 4 : rect.left;
  let y = beside ? rect.top - 8 : rect.bottom + 6;
  if (beside && x + width > window.innerWidth - margin) x = rect.left - width - 4;
  if (!beside && y + height > window.innerHeight - margin) y = rect.top - height - 6;
  el.style.left = `${Math.max(margin, Math.min(x, window.innerWidth - width - margin))}px`;
  el.style.top = `${Math.max(margin, Math.min(y, window.innerHeight - height - margin))}px`;
}

function popItem(entry) {
  const row = node("button", "pop-item" + (entry.danger ? " danger" : "") + (entry.active ? " active" : "") + (entry.icon ? "" : " plain"));
  row.type = "button";
  row.setAttribute("role", "menuitem");
  if (entry.icon) row.append(icon(entry.icon));
  row.append(node("span", "pop-label", entry.label));
  if (entry.detail) row.append(node("span", "pop-detail", entry.detail));
  if (entry.submenu) { row.classList.add("has-sub"); row.append(icon("chevron")); }
  else if (entry.toggle !== undefined) {
    const sw = node("span", "pop-switch" + (entry.toggle ? " on" : ""));
    sw.setAttribute("aria-hidden", "true");
    row.setAttribute("role", "menuitemcheckbox");
    row.setAttribute("aria-checked", String(!!entry.toggle));
    row.append(sw);
  }
  else if (entry.active) row.append(icon("check"));
  else if (entry.key) row.append(node("kbd", "", entry.key));
  return row;
}

// ``items``: { value, icon, label, key?, danger?, active?, toggle?, submenu?, search? }, { divider: true } oder { heading }; ``opts.compact``: schmaleres, flacheres Menü.
// Ergebnis: ``value`` des gewählten Eintrags, ``null`` bei Abbruch.
function openPopover(anchor, items, opts = {}) {
  return new Promise((resolve) => {
    if (pop) closePopover(null);
    const scrim = node("div", "pop-scrim");
    scrim.addEventListener("click", () => closePopover(null));
    const menu = node("div", "popover" + (opts.compact ? " compact" : ""));
    menu.setAttribute("role", "menu");
    menu.tabIndex = -1;
    const nodes = [scrim, menu];
    const fine = window.matchMedia("(hover: hover)").matches;
    let sub = null;
    let subOwner = null;
    let hoverTimer = 0;

    const dropSub = () => {
      clearTimeout(hoverTimer);
      if (!sub) return;
      sub.remove();
      nodes.splice(nodes.indexOf(sub), 1);
      subOwner?.classList.remove("open");
      sub = null;
      subOwner = null;
    };

    const openSub = (row, entry, focusIt) => {
      if (subOwner === row) { if (focusIt) sub.querySelector("input, .pop-item")?.focus(); return; }
      dropSub();
      const panel = node("div", "popover sub");
      panel.setAttribute("role", "menu");
      let search = null;
      if (entry.search) {
        search = node("input", "pop-search");
        search.type = "text";
        search.placeholder = entry.search;
        search.maxLength = 80;
        search.setAttribute("aria-label", entry.search);
        panel.append(search, node("div", "pop-sep"));
      }
      const list = node("div", "pop-list");
      const rows = [];
      for (const e of entry.submenu) {
        if (e.divider) { list.append(node("div", "pop-sep")); continue; }
        const r = popItem(e);
        r.addEventListener("click", () => closePopover(e.value));
        list.append(r);
        rows.push([e, r]);
      }
      if (search) {
        search.addEventListener("input", () => {
          const q = search.value.trim().toLowerCase();
          for (const [e, r] of rows) r.hidden = !e.sticky && q !== "" && !e.label.toLowerCase().includes(q);
        });
      }
      panel.append(list);
      document.body.append(panel);
      nodes.push(panel);
      sub = panel;
      subOwner = row;
      row.classList.add("open");
      placePopover(panel, row.getBoundingClientRect(), true);
      if (focusIt) (search || list.querySelector(".pop-item"))?.focus();
    };

    for (const entry of items) {
      if (entry.divider) { menu.append(node("div", "pop-sep")); continue; }
      if (entry.heading) { menu.append(node("div", "pop-head", entry.heading)); continue; }
      const row = popItem(entry);
      if (entry.submenu) {
        row.setAttribute("aria-haspopup", "menu");
        row.addEventListener("click", () => openSub(row, entry, true));
        row.addEventListener("mouseenter", () => { if (fine) hoverTimer = setTimeout(() => openSub(row, entry, false), 140); });
        row.addEventListener("mouseleave", () => clearTimeout(hoverTimer));
      } else {
        row.addEventListener("click", () => closePopover(entry.value));
        row.addEventListener("mouseenter", () => { clearTimeout(hoverTimer); dropSub(); });
      }
      menu.append(row);
    }

    const onKey = (event) => {
      if (event.key === "Escape") { event.stopPropagation(); closePopover(null); return; }
      const panel = sub && sub.contains(document.activeElement) ? sub : menu;
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const rows = [...panel.querySelectorAll(".pop-item:not([hidden])")];
        if (!rows.length) return;
        const i = rows.indexOf(document.activeElement);
        rows[event.key === "ArrowDown" ? (i + 1) % rows.length : i <= 0 ? rows.length - 1 : i - 1].focus();
      } else if (event.key === "ArrowRight" && document.activeElement?.classList.contains("has-sub")) {
        event.preventDefault();
        document.activeElement.click();
      } else if (event.key === "ArrowLeft" && panel === sub) {
        event.preventDefault();
        const owner = subOwner;
        dropSub();
        owner?.focus();
      } else if (!(event.target instanceof HTMLInputElement) && !event.metaKey && !event.ctrlKey && !event.altKey && event.key.length === 1) {
        const hit = items.find((e) => e.key && e.key.toLowerCase() === event.key.toLowerCase());
        if (hit) { event.preventDefault(); closePopover(hit.value); }
      }
    };
    const onLeave = () => closePopover(null);
    const sideScroll = $("side-scroll");
    document.addEventListener("keydown", onKey, true);
    window.addEventListener("resize", onLeave);
    window.addEventListener("blur", onLeave);
    sideScroll.addEventListener("scroll", onLeave);

    const anchorRow = anchor.closest(".row");
    anchorRow?.classList.add("menu-open");
    document.body.append(scrim, menu);
    placePopover(menu, anchor.getBoundingClientRect(), false);
    menu.focus({ preventScroll: true });
    pop = {
      nodes, anchorRow, done: resolve,
      off: () => {
        document.removeEventListener("keydown", onKey, true);
        window.removeEventListener("resize", onLeave);
        window.removeEventListener("blur", onLeave);
        sideScroll.removeEventListener("scroll", onLeave);
        clearTimeout(hoverTimer);
      },
    };
  });
}

// ------------------------------------------------------------ Seitenleiste

const isWeb = () => document.documentElement.dataset.embed === "web";
const projectOf = (id) => state.projects.find((p) => p.id === id) || null;

// Ruhezustand der Kopfzeile: leer. „HA Copilot“ steht in HA schon in der Kopfzeile von Home Assistant,
// im Web ist die Marke bereits in der Seitenleiste.
function idleTitle() {
  const project = projectOf(state.newProject);
  return project ? tr("Neuer Chat in {0}", project.name) : "";
}

// Eingabe nur mit Maus/Tastatur automatisch fokussieren. Auf dem Handy würde sonst die Tastatur aufspringen,
// ohne dass die Seite mitscrollt (Eingabefeld bliebe hinter der Tastatur), und sie verdeckt die Startkarten.
function focusInput() {
  if (window.matchMedia("(pointer: fine)").matches) $("input").focus({ preventScroll: true });
}

// Kopfzeile ohne Inhalt (Ruhezustand, kein Testmodus-Hinweis) blendet sich auf dem Handy in HA aus.
function syncTopbar() {
  $("topbar").classList.toggle("empty", !$("chat-title").textContent && $("test-badge").hidden);
}

function setTitle(text) {
  const el = $("chat-title");
  if (el.textContent === text) { syncTopbar(); return; }
  el.textContent = text;
  el.classList.remove("swap");
  void el.offsetWidth; // Animation neu starten
  el.classList.add("swap");
  syncTopbar();
}

function openMenu() { $("app").classList.add("open"); }
function closeMenu() { $("app").classList.remove("open"); }

function loadUi() {
  try {
    const stored = JSON.parse(localStorage.getItem("ki-ui") || "{}");
    if (typeof stored.projectsOpen === "boolean") ui.projectsOpen = stored.projectsOpen;
    if (Array.isArray(stored.openProjects)) ui.openProjects = new Set(stored.openProjects.filter((x) => typeof x === "string"));
  } catch { /* optional */ }
}
function saveUi() {
  try {
    localStorage.setItem("ki-ui", JSON.stringify({ projectsOpen: ui.projectsOpen, openProjects: [...ui.openProjects] }));
  } catch { /* optional */ }
}

function daysAgo(iso) {
  const then = new Date(iso);
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  return Math.round((start - new Date(then.getFullYear(), then.getMonth(), then.getDate())) / 86400000);
}

function groupOf(iso) {
  const days = daysAgo(iso);
  if (days <= 0) return tr("Heute");
  if (days === 1) return tr("Gestern");
  if (days < 8) return tr("Letzte 7 Tage");
  return tr("Älter");
}

function actionButton(label, iconName, extra, handler) {
  const button = node("button", `icon-btn ${extra}`.trim());
  button.type = "button";
  button.title = label;
  button.setAttribute("aria-label", label);
  button.append(icon(iconName));
  button.addEventListener("click", (event) => { event.stopPropagation(); handler(button); });
  return button;
}

function activate(item, handler) {
  item.tabIndex = 0;
  item.addEventListener("click", handler);
  item.addEventListener("keydown", (event) => {
    if (event.target === item && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      handler();
    }
  });
}

function unreadDot() {
  const dot = node("span", "unread-dot");
  dot.setAttribute("role", "img");
  dot.setAttribute("aria-label", tr("Ungelesen"));
  dot.title = tr("Ungelesen");
  return dot;
}

// Kleiner Kreisel: In diesem Chat wird gerade geantwortet (läuft auch ohne geöffnete Ansicht weiter).
function runningMark() {
  const mark = node("span", "run-spin");
  mark.setAttribute("role", "img");
  mark.setAttribute("aria-label", tr("Antwort wird erstellt"));
  mark.title = tr("Antwort wird erstellt");
  return mark;
}

// Die KI wartet auf eine Bestätigung für eine Änderung in Home Assistant.
function askMark() {
  const mark = node("span", "ask-dot");
  mark.setAttribute("role", "img");
  mark.setAttribute("aria-label", tr("Wartet auf deine Bestätigung"));
  mark.title = tr("Wartet auf deine Bestätigung");
  return mark;
}

function chatRow(chat, meta = "") {
  const item = node("div", "row chat-item" + (chat.id === state.activeId ? " active" : ""));
  if (chat.schedule_id) {
    const mark = icon("clock");
    mark.classList.add("sched-mark");
    mark.setAttribute("role", "img");
    mark.setAttribute("aria-label", tr("Geplante Aufgabe"));
    item.append(mark);
  }
  item.append(node("span", "name", chat.title));
  if (meta) item.append(node("span", "meta", meta));
  if (chat.needs_approval) {
    item.classList.add("running");
    item.append(askMark());
  } else if (chat.running) {
    item.classList.add("running");
    item.append(runningMark());
  } else if (chat.unread) {
    item.classList.add("unread");
    item.append(unreadDot());
  }
  item.append(actionButton(tr("Aktionen"), "more", "more", (button) => chatMenu(chat, button)));
  activate(item, () => selectChat(chat.id));
  return item;
}

function sectionHead(label, extra = null) {
  const head = node("div", "sec-head");
  head.append(node("span", "sec-label", label));
  if (extra) head.append(extra);
  return head;
}

function renderProjects(root) {
  const toggle = node("button", "sec-toggle");
  toggle.type = "button";
  toggle.setAttribute("aria-expanded", String(ui.projectsOpen));
  toggle.append(icon("chevron"), node("span", "", tr("Projekte")));
  toggle.addEventListener("click", () => { ui.projectsOpen = !ui.projectsOpen; saveUi(); renderSide(); });
  const head = node("div", "sec-head");
  head.append(toggle, actionButton(`${tr("Neues Projekt")} (${shortcutText("P")})`, "plus", "add", createProject));
  root.append(head);
  if (!ui.projectsOpen) return;

  const body = node("div", "sec-body");
  if (state.projects.length === 0) {
    body.append(node("div", "hint", tr("Fasse zusammengehörige Chats an einem Ort zusammen.")));
  }
  const ordered = [...state.projects].sort((a, b) => Number(b.pinned) - Number(a.pinned) || a.name.localeCompare(b.name, "de"));
  for (const project of ordered) {
    const open = ui.openProjects.has(project.id);
    const row = node("div", "row project-row" + (open ? " open" : ""));
    const label = node("span", "name", project.name);
    if (project.instructions) { const dot = node("i", "dot"); dot.title = tr("Projektanweisungen aktiv"); label.append(dot); }
    if (project.knowledge) { const dot = node("i", "dot know"); dot.title = tr("{0} Wissensdateien", project.knowledge); label.append(dot); }
    row.append(icon("chevron"), label);
    if (project.pinned) { const pin = icon("pin"); pin.classList.add("pin"); row.append(pin); }
    if (!open && state.chats.some((c) => c.project_id === project.id && c.running)) row.append(runningMark());
    else if (!open && state.chats.some((c) => c.project_id === project.id && c.unread)) row.append(unreadDot());
    row.append(
      actionButton(tr("Neuer Chat im Projekt"), "plus", "more", () => startNew(project.id)),
      actionButton(tr("Aktionen"), "more", "more", (button) => projectMenu(project, button)),
    );
    row.setAttribute("aria-expanded", String(open));
    activate(row, () => {
      if (open) ui.openProjects.delete(project.id); else ui.openProjects.add(project.id);
      saveUi();
      renderSide();
    });
    body.append(row);
    if (!open) continue;
    const kids = node("div", "project-children");
    const inside = state.chats.filter((c) => c.project_id === project.id && !c.pinned);
    for (const chat of inside) kids.append(chatRow(chat));
    if (inside.length === 0) kids.append(node("div", "hint", tr("Noch keine Chats.")));
    body.append(kids);
  }
  root.append(body);
}

function renderChats(root) {
  const loose = state.chats.filter((c) => !c.project_id && !c.pinned);
  const recent = loose.filter((c) => daysAgo(c.updated_at) <= 1);
  const shown = ui.showAll ? loose : recent;
  const hidden = loose.length - recent.length;

  root.append(sectionHead(tr("Chats")));
  const body = node("div", "sec-body");
  let current = null;
  for (const chat of shown) {
    const group = groupOf(chat.updated_at);
    if (group !== current) {
      current = group;
      body.append(node("div", "group-label", group));
    }
    body.append(chatRow(chat));
  }
  if (shown.length === 0) {
    const none = state.chats.length === 0 ? tr("Noch keine Chats.") : tr("Keine Chats in den letzten 2 Tagen.");
    body.append(node("div", "hint", none));
  }
  if (hidden > 0) {
    const more = node("button", "show-all", ui.showAll ? tr("Weniger anzeigen") : tr("Alle anzeigen ({0} ältere)", hidden));
    more.type = "button";
    more.addEventListener("click", () => { ui.showAll = !ui.showAll; renderSide(); });
    body.append(more);
  }
  root.append(body);
}

function renderSide() {
  const root = $("side-scroll");
  const scroll = root.scrollTop;
  root.replaceChildren();

  const pinned = state.chats.filter((c) => c.pinned);
  if (pinned.length) {
    root.append(sectionHead(tr("Angepinnt")));
    const body = node("div", "sec-body");
    for (const chat of pinned) body.append(chatRow(chat, projectOf(chat.project_id)?.name || ""));
    root.append(body);
  }
  renderProjects(root);
  renderChats(root);
  root.scrollTop = scroll;
}

async function loadAll() {
  const [chats, projects] = await Promise.all([api("api/chats"), api("api/projects")]);
  state.chats = chats;
  state.projects = projects;
  renderSide();
  syncBadge();
}

// Ein Punkt vor dem Namen im Tab-Titel zeigt ungelesene Chats auch dann, wenn der Tab im Hintergrund liegt.
function syncBadge() {
  const base = state.me?.app_name || "HA Copilot";
  document.title = (state.chats.some((c) => c.unread) ? "● " : "") + base;
}

// Chat gilt als gelesen, sobald er angezeigt wurde (lokal sofort, dann auf dem Server; bei Fehler zurück).
async function markRead(chatId) {
  const chat = state.chats.find((c) => c.id === chatId);
  if (!chat || !chat.unread) return;
  chat.unread = false;
  renderSide();
  syncBadge();
  try {
    await patchChat(chat, { unread: false });
  } catch {
    chat.unread = true;
    renderSide();
    syncBadge();
  }
}

async function setUnread(chat, unread) {
  // Der gerade offene Chat bleibt ungelesen markiert, bis man ihn erneut öffnet.
  if (unread && chat.id === state.activeId) state.heldUnread = chat.id;
  else if (state.heldUnread === chat.id) state.heldUnread = null;
  await changeChat(chat, { unread }, tr("Markieren hat nicht geklappt."));
}

// Zurück im Fenster oder alle 45 Sekunden: Liste neu laden (Antworten von anderen Geräten) und den offenen Chat als gelesen werten.
async function refreshWhenSeen() {
  if (document.hidden || state.streaming || sheetDone || pop || !state.me) return;
  refreshLimits().catch(() => {});
  if (state.view === "schedules") loadSchedules().catch(() => {});
  try { await loadAll(); } catch { return; }
  const active = state.chats.find((c) => c.id === state.activeId);
  if (!active) return;
  if (active.updated_at !== state.shownAt) {
    try {
      renderMessages(await api(`api/chats/${encodeURIComponent(active.id)}/messages`));
      state.shownAt = active.updated_at;
    } catch { return; }
  }
  if (state.heldUnread !== active.id) await markRead(active.id);
}

// Offener Chat bleibt nach dem Neuladen derselbe (nur in diesem Tab).
function rememberActive() {
  try {
    if (state.activeId) sessionStorage.setItem("ki-active", state.activeId);
    else sessionStorage.removeItem("ki-active");
  } catch { /* optional */ }
}

function rememberedActive() {
  try { return sessionStorage.getItem("ki-active"); } catch { return null; }
}

// Solange irgendwo eine Antwort entsteht (auch in einem anderen Chat oder auf einem anderen Gerät): alle 3 Sekunden nachsehen.
// So erscheinen fertige Antworten als ungelesen, und ein offener Chat hängt sich wieder an, falls er den Faden verloren hat.
let polling = false;
async function pollRunning() {
  if (polling || !state.me || sheetDone || pop) return;
  if (state.view === "schedules" && state.schedules.some((t) => t.running)) loadSchedules().catch(() => {});
  const before = new Set(state.chats.filter((c) => c.running).map((c) => c.id));
  const active = state.chats.find((c) => c.id === state.activeId);
  if (before.size === 0 && !(active && !state.streaming && active.running)) return;
  polling = true;
  try {
    await loadAll();
    const now = state.chats.find((c) => c.id === state.activeId);
    if (!now || state.streaming) return;
    if (now.running) attachRun(now.id).catch(() => {});
    else if (before.has(now.id)) await reloadActive(now.id); // in der Zwischenzeit fertig geworden
  } catch { /* nächster Durchlauf */ } finally { polling = false; }
}

// ------------------------------------------------- Aktionen für Chats und Projekte

async function patchChat(chat, body) {
  await api(`api/chats/${encodeURIComponent(chat.id)}`, { method: "PATCH", body: JSON.stringify(body) });
}

async function chatMenu(chat, anchor) {
  const unread = {
    value: "unread",
    icon: chat.unread ? "eye" : "eyeOff",
    label: chat.unread ? tr("Als gelesen markieren") : tr("Als ungelesen markieren"),
    key: "U",
  };
  const pin = { value: "pin", icon: "pin", label: chat.pinned ? tr("Lösen") : tr("Anpinnen"), key: "P" };
  const rename = { value: "rename", icon: "edit", label: tr("Umbenennen"), key: "R" };
  const exportMd = { value: "export", icon: "download", label: tr("Als Markdown exportieren") };
  const remove = { value: "delete", icon: "trash", label: tr("Löschen"), danger: true, key: "D" };
  let choice;
  if (anchor && wideScreen()) {
    const projects = [
      { value: "move:__new", icon: "plus", label: tr("Neues Projekt"), sticky: true },
      { divider: true },
      ...state.projects.map((p) => ({ value: `move:${p.id}`, label: p.name, active: p.id === chat.project_id })),
    ];
    choice = await openPopover(anchor, [
      unread,
      { divider: true },
      pin,
      rename,
      { icon: "stack", label: tr("Projekt wechseln"), submenu: projects, search: tr("Projekt suchen") },
      ...(chat.project_id ? [{ value: "unproject", icon: "folderX", label: tr("Aus Projekt entfernen") }] : []),
      exportMd,
      { divider: true },
      remove,
    ]);
  } else {
    choice = await openSheet({
      title: chat.title,
      items: [
        unread, pin, rename,
        { value: "move", icon: "folder", label: chat.project_id ? tr("Projekt ändern") : tr("In Projekt verschieben") },
        exportMd,
        remove,
      ],
    });
  }
  if (choice === "unread") await setUnread(chat, !chat.unread);
  else if (choice === "pin") await changeChat(chat, { pinned: !chat.pinned }, tr("Anpinnen hat nicht geklappt."));
  else if (choice === "rename") await renameChat(chat);
  else if (choice === "move") await moveChat(chat);
  else if (choice === "unproject") await moveChatTo(chat, "");
  else if (choice === "export") await exportChat(chat);
  else if (typeof choice === "string" && choice.startsWith("move:")) await moveChatTo(chat, choice.slice(5));
  else if (choice === "delete") await deleteChat(chat);
}

async function changeChat(chat, body, failure) {
  try {
    await patchChat(chat, body);
    await loadAll();
  } catch {
    toast(failure);
  }
}

async function moveChat(chat) {
  const items = [
    { value: "", icon: "chat", label: tr("Kein Projekt"), active: !chat.project_id },
    ...state.projects.map((p) => ({ value: p.id, icon: "folder", label: p.name, active: p.id === chat.project_id })),
    { value: "__new", icon: "plus", label: tr("Neues Projekt …") },
  ];
  const target = await openSheet({ title: tr("In Projekt verschieben"), sub: chat.title, items });
  if (target === null) return;
  await moveChatTo(chat, target);
}

async function moveChatTo(chat, target) {
  if (target === "__new") {
    const project = await createProject();
    if (!project) return;
    target = project.id;
  }
  if ((target || null) === chat.project_id) return;
  if (target) { ui.openProjects.add(target); ui.projectsOpen = true; saveUi(); }
  await changeChat(chat, { project_id: target || null }, tr("Verschieben hat nicht geklappt."));
}

async function createProject() {
  const name = await openSheet({
    title: tr("Projekt erstellen"),
    sub: tr("Fasse zusammengehörige Chats an einem Ort zusammen."),
    label: tr("Wie soll das Projekt heißen?"),
    value: "",
    placeholder: tr("Name des Projekts"),
    ok: tr("Projekt erstellen"),
  });
  if (!name) return null;
  try {
    const project = await api("api/projects", { method: "POST", body: JSON.stringify({ name: name.slice(0, 80) }) });
    ui.projectsOpen = true;
    ui.openProjects.add(project.id);
    saveUi();
    await loadAll();
    return project;
  } catch {
    toast(tr("Das Projekt konnte nicht angelegt werden."));
    return null;
  }
}

async function projectMenu(project, anchor) {
  const entries = [
    { value: "new", icon: "plus", label: tr("Neuer Chat im Projekt"), key: "N" },
    { divider: true },
    { value: "pin", icon: "pin", label: project.pinned ? tr("Lösen") : tr("Anpinnen"), key: "P" },
    { value: "instructions", icon: "note", label: project.instructions ? tr("Anweisungen bearbeiten") : tr("Anweisungen festlegen"), key: "A" },
    { value: "knowledge", icon: "stack", label: project.knowledge ? tr("Wissen verwalten ({0})", project.knowledge) : tr("Wissen hinzufügen"), key: "W" },
    { value: "rename", icon: "edit", label: tr("Umbenennen"), key: "R" },
    { divider: true },
    { value: "delete", icon: "trash", label: tr("Projekt löschen"), danger: true, key: "D" },
  ];
  const choice = anchor && wideScreen()
    ? await openPopover(anchor, entries)
    : await openSheet({ title: project.name, items: entries.filter((e) => !e.divider) });
  if (choice === "new") { startNew(project.id); return; }
  if (choice === "knowledge") { await openKnowledge(project); await loadAll().catch(() => {}); return; }
  try {
    if (choice === "pin") {
      await api(`api/projects/${encodeURIComponent(project.id)}`, { method: "PATCH", body: JSON.stringify({ pinned: !project.pinned }) });
    } else if (choice === "instructions") {
      const text = await openSheet({
        title: tr("Anweisungen für das Projekt"),
        label: tr("Was soll Claude in diesem Projekt beachten?"),
        sub: tr("Gelten für jeden Chat in diesem Projekt, zum Beispiel Rolle, Stil oder feste Hintergründe. Leer lassen entfernt sie."),
        value: project.instructions || "",
        placeholder: tr("z. B. Du hilfst bei meinem Home-Assistant-Smarthome. Antworte knapp und zeige YAML in Codeblöcken."),
        ok: tr("Speichern"),
        multiline: true,
      });
      if (text === null) return;
      await api(`api/projects/${encodeURIComponent(project.id)}`, { method: "PATCH", body: JSON.stringify({ instructions: text }) });
      toast(text ? tr("Anweisungen gespeichert.") : tr("Anweisungen entfernt."));
    } else if (choice === "rename") {
      const name = await openSheet({ title: tr("Projekt umbenennen"), label: tr("Name"), value: project.name, ok: tr("Speichern") });
      if (!name) return;
      await api(`api/projects/${encodeURIComponent(project.id)}`, { method: "PATCH", body: JSON.stringify({ name: name.slice(0, 80) }) });
    } else if (choice === "delete") {
      const yes = await openSheet({
        title: tr("Projekt löschen?"),
        sub: tr("„{0}“ wird gelöscht. Die Chats darin bleiben erhalten.", project.name),
        ok: tr("Löschen"),
        danger: true,
      });
      if (!yes) return;
      await api(`api/projects/${encodeURIComponent(project.id)}`, { method: "DELETE" });
      ui.openProjects.delete(project.id);
      if (state.newProject === project.id) state.newProject = null;
      saveUi();
    } else {
      return;
    }
    await loadAll();
  } catch {
    toast(tr("Das hat nicht geklappt."));
  }
}


// ------------------------------------------------------------- Gedächtnis und Projektwissen

function errorText(err, fallback) {
  return typeof err?.detail === "string" ? err.detail : fallback;
}

function dayText(iso) {
  try { return new Date(iso).toLocaleDateString(kiLocale, { day: "numeric", month: "short", year: "numeric" }); } catch { return ""; }
}

// Löschen mit zweitem Klick: der Knopf fragt erst „Wirklich?“.
function confirmButton(label, onConfirm) {
  const b = node("button", "mem-del");
  b.type = "button";
  b.setAttribute("aria-label", label);
  b.title = label;
  b.append(icon("trash"));
  let armed = 0;
  b.addEventListener("click", () => {
    if (!armed) {
      b.classList.add("armed");
      b.replaceChildren(node("span", "", tr("Wirklich löschen?")));
      armed = setTimeout(() => { armed = 0; b.classList.remove("armed"); b.replaceChildren(icon("trash")); }, 3500);
      return;
    }
    clearTimeout(armed);
    onConfirm();
  });
  return b;
}

function memoryEntry(entry, scope, canDelete, refresh) {
  const row = node("div", "mem-entry");
  const text = node("div", "mem-text");
  text.append(node("b", "mem-topic", entry.topic), node("p", "", entry.content));
  const meta = [entry.by ? tr("von {0}", entry.by) : "", dayText(entry.updated_at)].filter(Boolean).join(" · ");
  if (meta) text.append(node("small", "mem-meta", meta));
  row.append(text);
  if (canDelete) {
    row.append(confirmButton(tr("Eintrag löschen"), async () => {
      try {
        await api(`api/memory/${scope}/${entry.id}`, { method: "DELETE" });
        refresh();
      } catch (err) { toast(errorText(err, tr("Löschen hat nicht geklappt."))); }
    }));
  }
  return row;
}

// ------------------------------------------------- Smarthome-Überblick (automatisch aus Home Assistant eingelesen)

const OV_RECENT_MS = 24 * 3600 * 1000;
const overview = { timer: 0, status: null, open: false };

function ago(seconds) {
  const diff = Date.now() / 1000 - seconds;
  if (diff < 90) return tr("gerade eben");
  if (diff < 3600) return tr("vor {0} Min.", Math.round(diff / 60));
  if (diff < 86400) return tr("vor {0} Std.", Math.round(diff / 3600));
  return dayText(new Date(seconds * 1000).toISOString());
}

function overviewSeen(status) {
  try { return localStorage.getItem("ki-ov-seen") === String(status.finished_at); } catch { return false; }
}

function overviewDismiss(status) {
  try { localStorage.setItem("ki-ov-seen", String(status.finished_at)); } catch { /* optional */ }
  renderOverviewNotice(status);
}

// Hinweis oben: läuft gerade / fertig (24 Stunden lang, wegklickbar) / fehlgeschlagen (mit „Erneut versuchen“)
function renderOverviewNotice(status) {
  const box = $("ov-notices");
  box.replaceChildren();
  const recent = status?.finished_at && Date.now() - status.finished_at * 1000 < OV_RECENT_MS && !overviewSeen(status);
  let row = null;
  if (status?.state === "running") {
    row = node("div", "notice info");
    row.append(node("span", "run-spin"), node("span", "notice-text", tr("Home Assistant wird eingelesen ({0} von {1}): {2}", Math.min((status.step || 0) + 1, status.total_steps), status.total_steps, status.label)));
  } else if (status?.state === "ok" && recent) {
    const st = status.stats || {};
    const facts = [st.areas ? trn(st.areas, "1 Bereich", "{0} Bereiche") : "", st.entities ? trn(st.entities, "1 Entität", "{0} Entitäten") : "", st.automations ? trn(st.automations, "1 Automation", "{0} Automationen") : ""].filter(Boolean).join(", ");
    row = node("div", "notice ok");
    row.append(icon("check"), node("span", "notice-text", facts ? tr("Home Assistant eingelesen: {0}. Die KI kann das jetzt für Antworten nutzen.", facts) : tr("Home Assistant eingelesen. Die KI kann das jetzt für Antworten nutzen.")));
    row.append(actionButton(tr("Hinweis ausblenden"), "close", "", () => overviewDismiss(status)));
  } else if (status?.state === "error" && recent) {
    row = node("div", "notice error");
    row.setAttribute("role", "alert");
    row.append(node("span", "notice-text", tr("Home Assistant konnte nicht eingelesen werden.")));
    const retry = node("button", "notice-btn", tr("Erneut versuchen"));
    retry.type = "button";
    retry.addEventListener("click", () => { startOverviewScan().catch(() => {}); });
    row.append(retry, actionButton(tr("Hinweis ausblenden"), "close", "", () => overviewDismiss(status)));
  }
  if (row) {
    if (!row.getAttribute("role")) row.setAttribute("role", "status");
    box.append(row);
  }
  box.hidden = !row;
}

async function pollOverview() {
  clearTimeout(overview.timer);
  let status = null;
  try { status = (await api("api/overview")).status; } catch { /* nicht verfügbar: nichts anzeigen */ }
  overview.status = status;
  renderOverviewNotice(status);
  if (status) overview.timer = setTimeout(pollOverview, document.hidden ? 60000 : status.state === "running" ? 2000 : 30000);
}

async function startOverviewScan() {
  try {
    const { status } = await api("api/overview/scan", { method: "POST" });
    overview.status = status;
    renderOverviewNotice(status);
    clearTimeout(overview.timer);
    overview.timer = setTimeout(pollOverview, 1500);
    return status;
  } catch (err) {
    toast(errorText(err, tr("Das Einlesen konnte nicht gestartet werden.")));
    return null;
  }
}

function overviewShort(status, count) {
  if (status.state === "running") return tr("wird eingelesen …");
  if (status.state === "never") return tr("noch nicht eingelesen");
  if (status.state === "error") return count ? trn(count, "1 Eintrag, letzter Versuch fehlgeschlagen", "{0} Einträge, letzter Versuch fehlgeschlagen") : tr("fehlgeschlagen");
  return trn(count, "1 Eintrag", "{0} Einträge");
}

function overviewLine(status, count) {
  if (status.state === "running") return tr("Wird eingelesen ({0} von {1}): {2}", Math.min((status.step || 0) + 1, status.total_steps), status.total_steps, status.label);
  const auto = status.auto_days > 0 ? trn(status.auto_days, "Wird jeden Tag automatisch aktualisiert.", "Wird alle {0} Tage automatisch aktualisiert.") : tr("Automatisches Einlesen ist ausgeschaltet.");
  if (status.state === "never") return tr("Noch nicht eingelesen. {0}", status.auto_days > 0 ? tr("Das geschieht automatisch kurz nach dem Start.") : auto);
  if (status.state === "error") return tr("Zuletzt {0} fehlgeschlagen: {1}. {2}", ago(status.finished_at), status.error || tr("Home Assistant hat nicht geantwortet"), auto);
  return trn(count, "1 Eintrag, eingelesen {0}. {1}", "{0} Einträge, eingelesen {1}. {2}", ago(status.finished_at), auto);
}

function overviewSection(info, redraw) {
  const box = document.createElement("details");
  box.className = "mem-overview";
  box.open = overview.open || info.status.state === "running";
  box.addEventListener("toggle", () => { overview.open = box.open; });
  const entries = info.entries || [];
  const short = node("small", "mem-meta", overviewShort(info.status, entries.length));
  const head = node("summary", "");
  head.append(node("span", "", tr("Home Assistant-Überblick")), short, icon("chevron"));
  const line = node("p", "mem-ov-status", overviewLine(info.status, entries.length));
  line.classList.toggle("error", info.status.state === "error");
  const hint = node("p", "mem-hint", tr("Damit kennt die KI deine Smarthome-Umgebung: Bereiche, Geräte, Automationen und Integrationen. Das wird automatisch aus Home Assistant eingelesen und hier nur angezeigt."));
  const button = node("button", "pill ghost", info.status.state === "running" ? tr("Läuft …") : tr("Neu einlesen"));
  button.type = "button";
  button.disabled = info.status.state === "running";
  const bar = node("div", "mem-ov-bar");
  bar.append(button);
  const list = node("div", "mem-ov-list");
  for (const e of entries) {
    const row = node("div", "mem-entry");
    const text = node("div", "mem-text");
    text.append(node("b", "mem-topic", e.topic.replace(/^HA · /, "")), node("p", "", e.content));
    row.append(text);
    list.append(row);
  }
  box.append(head, hint, line, bar, list);

  // Läuft gerade ein Einlesen, Anzeige im Dialog mitführen und am Ende neu zeichnen
  const follow = async () => {
    for (;;) {
      await new Promise((resolve) => setTimeout(resolve, 1500)); // erst warten: der Bereich ist beim Start noch nicht im Dialog eingehängt
      if (!box.isConnected) return;
      let status;
      try { status = (await api("api/overview")).status; } catch { return; }
      overview.status = status;
      renderOverviewNotice(status);
      if (status.state !== "running") { redraw(); return; }
      line.textContent = overviewLine(status, entries.length);
      short.textContent = overviewShort(status, entries.length);
    }
  };
  button.addEventListener("click", async () => {
    button.disabled = true;
    const status = await startOverviewScan();
    if (!status) { button.disabled = false; return; }
    redraw();
  });
  if (info.status.state === "running") follow().catch(() => {});
  return box;
}

function memoryPanel(body) {
  const draw = async () => {
    let data;
    try { data = await api("api/memory"); } catch { body.replaceChildren(node("p", "mem-empty", tr("Das Gedächtnis ist gerade nicht erreichbar."))); return; }
    const parts = [];
    const section = (title, hint, entries, scope, canDelete) => {
      const box = node("section", "mem-section");
      box.append(node("h4", "", title), node("p", "mem-hint", hint));
      if (entries.length === 0) box.append(node("p", "mem-empty", tr("Noch nichts gemerkt.")));
      for (const e of entries) box.append(memoryEntry(e, scope, canDelete, draw));
      parts.push(box);
    };
    section(tr("Mein Gedächtnis"), tr("Nur du siehst das und nur dir gegenüber nutzt die KI es."), data.person, "person", true);
    section(tr("Haushalt"), data.household_write ? tr("Gilt für alle im Haushalt.") : tr("Gilt für alle im Haushalt. Du darfst es ansehen, aber nicht ändern."), data.household, "household", data.household_write);
    if (data.overview) parts.push(overviewSection(data.overview, draw));
    // Eintrag selbst hinzufügen
    const form = node("form", "mem-form");
    form.autocomplete = "off";
    const scope = node("select", "field");
    scope.setAttribute("aria-label", tr("Wo speichern"));
    scope.append(new Option(tr("Mein Gedächtnis"), "person"));
    if (data.household_write) scope.append(new Option(tr("Haushalt"), "household"));
    const topic = node("input", "field");
    topic.placeholder = tr("Thema, z. B. Heizung");
    topic.maxLength = 60;
    topic.setAttribute("aria-label", tr("Thema"));
    const content = node("textarea", "field area");
    content.rows = 3;
    content.maxLength = 800;
    content.placeholder = tr("Was soll die KI wissen?");
    content.setAttribute("aria-label", tr("Inhalt"));
    const add = node("button", "pill primary", tr("Merken"));
    add.type = "submit";
    form.append(node("h4", "", tr("Selbst etwas eintragen")), scope, topic, content, add);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (topic.value.trim().length < 2 || content.value.trim().length < 3) { toast(tr("Bitte Thema und Inhalt ausfüllen.")); return; }
      add.disabled = true;
      try {
        await api("api/memory", { method: "POST", body: JSON.stringify({ scope: scope.value, topic: topic.value, content: content.value }) });
        draw();
      } catch (err) { toast(errorText(err, tr("Speichern hat nicht geklappt."))); add.disabled = false; }
    });
    parts.push(form);
    body.replaceChildren(...parts);
  };
  draw();
}

async function openMemory() {
  await openSheet({
    title: tr("Gedächtnis"),
    sub: tr("Die KI merkt sich, was du ihr sagst, und nutzt es in allen Chats. Du kannst jeden Eintrag löschen."),
    ok: tr("Fertig"),
    panel: memoryPanel,
  });
}

const KNOWLEDGE_ACCEPT = ".zip,.pdf,.docx,.xlsx,text/*,.md,.csv,.tsv,.json,.yaml,.yml,.xml,.log,.py,.js,.ts,.sh,.ps1,.ini,.conf,.cfg,.toml,.sql,.html,.css,.jinja,.j2";
const KNOWLEDGE_MAX = 8 * 1024 * 1024;

function knowledgePanel(project) {
  return (body) => {
    const state2 = { busy: false };
    const draw = async () => {
      let data;
      try { data = await api(`api/projects/${encodeURIComponent(project.id)}/knowledge`); } catch { body.replaceChildren(node("p", "mem-empty", tr("Das Wissen ist gerade nicht erreichbar."))); return; }
      const parts = [];
      const picker = node("input");
      picker.type = "file";
      picker.multiple = true;
      picker.accept = KNOWLEDGE_ACCEPT;
      picker.hidden = true;
      const add = node("button", "pill primary know-add");
      add.type = "button";
      add.append(icon("upload"), node("span", "", tr("Dateien oder ZIP hinzufügen")));
      add.disabled = state2.busy;
      add.addEventListener("click", () => picker.click());
      const status = node("p", "mem-hint know-status");
      status.setAttribute("role", "status");
      picker.addEventListener("change", async () => {
        const files = [...picker.files];
        picker.value = "";
        if (!files.length || state2.busy) return;
        state2.busy = true;
        add.disabled = true;
        const report = { added: 0, skipped: [] };
        for (const [i, file] of files.entries()) {
          status.textContent = tr("Lade {0} ({1} von {2}) …", file.name, i + 1, files.length);
          if (file.size > KNOWLEDGE_MAX) { report.skipped.push({ name: file.name, reason: tr("zu groß (höchstens {0} MB je Datei oder ZIP)", KNOWLEDGE_MAX / 1024 / 1024) }); continue; }
          try {
            const answer = await api(`api/projects/${encodeURIComponent(project.id)}/knowledge`, { method: "POST", body: JSON.stringify({ name: file.name, data: await toBase64(file) }) });
            report.added += answer.added.length;
            report.skipped.push(...answer.skipped);
          } catch (err) {
            report.skipped.push({ name: file.name, reason: errorText(err, tr("Hochladen fehlgeschlagen")) });
          }
        }
        state2.busy = false;
        await draw();
        const note = body.querySelector(".know-status");
        if (note) {
          const added = trn(report.added, "1 Datei übernommen", "{0} Dateien übernommen");
          note.textContent = report.skipped.length ? tr("{0}, {1} übersprungen.", added, report.skipped.length) : `${added}.`;
          if (report.skipped.length) {
            const list = node("ul", "know-skipped");
            for (const sk of report.skipped.slice(0, 12)) list.append(node("li", "", `${sk.name}: ${sk.reason}`));
            note.after(list);
          }
        }
        loadAll().catch(() => {});
      });
      parts.push(node("p", "mem-hint", tr("Text, Markdown, YAML, Word, Excel, PDF oder ein ZIP davon. Die KI durchsucht das Wissen bei Bedarf und liest gezielt hinein, nur in den Chats dieses Projekts.")), add, picker, status);
      const list = node("div", "know-list");
      if (data.files.length === 0) list.append(node("p", "mem-empty", tr("Noch keine Dateien. Importiere zum Beispiel Notizen, Anleitungen oder Konfigurationen.")));
      for (const f of data.files) {
        const row = node("div", "know-file");
        const name = node("span", "know-name", f.name);
        name.title = f.name;
        row.append(icon("file"), name, node("small", "mem-meta", tr("{0} Text", formatSize(f.size))));
        row.append(confirmButton(tr("{0} entfernen", f.name), async () => {
          try {
            await api(`api/projects/${encodeURIComponent(project.id)}/knowledge/${f.id}`, { method: "DELETE" });
            await draw();
            loadAll().catch(() => {});
          } catch { toast(tr("Entfernen hat nicht geklappt.")); }
        }));
        list.append(row);
      }
      parts.push(list);
      if (data.files.length) parts.push(node("p", "mem-hint", tr("{0} von {1} Dateien · {2} Text von {3}", data.files.length, data.max_files, formatSize(data.chars), formatSize(data.max_chars))));
      body.replaceChildren(...parts);
    };
    draw();
  };
}

async function openKnowledge(project) {
  await openSheet({
    title: tr("Wissen: {0}", project.name),
    sub: tr("Dateien, aus denen die KI in diesem Projekt nachschlagen darf."),
    ok: tr("Fertig"),
    panel: knowledgePanel(project),
  });
}

// ------------------------------------------------------------- Nachrichten

function greeting() {
  const hour = new Date().getHours();
  const part = hour < 5 ? tr("Gute Nacht") : hour < 11 ? tr("Guten Morgen") : hour < 17 ? tr("Guten Tag") : hour < 22 ? tr("Guten Abend") : tr("Gute Nacht");
  return state.me ? `${part},\n${state.me.label}` : part;
}

const STARTERS = [
  { icon: "bolt", label: tr("Automatisierung planen"), hint: tr("Ablauf und YAML entwerfen"), prompt: tr("Hilf mir, eine Home-Assistant-Automatisierung zu planen. Das soll sie tun: ") },
  { icon: "bug", label: tr("Fehler eingrenzen"), hint: tr("Meldung oder Log einfügen"), prompt: tr("Ich habe einen Fehler und brauche Hilfe bei der Eingrenzung. Hier ist die Meldung:\n\n") },
  { icon: "code", label: tr("Skript schreiben"), hint: tr("Python, Bash, PowerShell"), prompt: tr("Schreib mir ein Skript, das ") },
  { icon: "pen", label: tr("Text formulieren"), hint: tr("Mail, Notiz, Dokumentation"), prompt: tr("Formuliere mir einen Text. Worum es geht: ") },
];

function showHello() {
  const thread = $("thread");
  thread.replaceChildren();
  thread.classList.add("empty");
  const hello = node("div", "hello");
  const project = projectOf(state.newProject);
  // Das Logo steht in Home Assistant auf dem Handy hier (die Seitenleiste fehlt dort); sonst blendet CSS es aus.
  const mark = node("img", "mark hello-mark");
  mark.src = document.querySelector(".brand .mark")?.getAttribute("src") || "";
  mark.alt = "";
  mark.width = mark.height = 44;
  hello.append(
    mark,
    node("h2", "", greeting()),
    node("p", "", project ? tr("Neuer Chat im Projekt „{0}“", project.name) : tr("Womit kann ich helfen?")),
  );
  if (project?.instructions) hello.append(node("p", "hello-note", tr("Die Projektanweisungen gelten für diesen Chat.")));
  const grid = node("div", "starters");
  for (const starter of STARTERS) {
    const card = node("button", "starter");
    card.type = "button";
    const text = node("span", "starter-text");
    text.append(node("b", "", starter.label), node("small", "", starter.hint));
    card.append(text);
    card.addEventListener("click", () => {
      const input = $("input");
      input.value = starter.prompt;
      autosize();
      input.focus();
      input.setSelectionRange(input.value.length, input.value.length);
    });
    grid.append(card);
  }
  hello.append(grid);
  thread.append(hello);
}

// ---------------------------------------------- Dateien und Vorschau aus Antworten
// Antworten bestehen aus Text. Codeblöcke lassen sich als Datei speichern, vollständige HTML-Seiten
// als abgeschottete Vorschau anzeigen (Server: nur im Arbeitsspeicher, siehe previews.py).

async function saveFile(name, text, mime) {
  const file = new File([text], name, { type: mime });
  const touch = window.matchMedia("(pointer: coarse)").matches;
  if (touch && navigator.canShare?.({ files: [file] })) {
    // Auf dem Handy ist das Teilen-Fenster („In Dateien sichern“) der verlässliche Weg.
    try { await navigator.share({ files: [file] }); return true; } catch (err) { if (err.name === "AbortError") return false; }
  }
  const url = URL.createObjectURL(file);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
  return true;
}

async function togglePreview(pre, button, html) {
  const open = pre.nextElementSibling?.classList.contains("preview") ? pre.nextElementSibling : null;
  if (open) { open.remove(); button.textContent = tr("Vorschau"); return; }
  let id;
  try {
    id = (await api("api/previews", { method: "POST", body: JSON.stringify({ html }) })).id;
  } catch {
    toast(tr("Die Vorschau konnte nicht erstellt werden (zu groß?)."));
    return;
  }
  const box = node("div", "preview");
  const bar = node("div", "preview-bar");
  const full = node("button", "", tr("Vollbild"));
  full.type = "button";
  full.addEventListener("click", () => { box.classList.toggle("full"); full.textContent = box.classList.contains("full") ? tr("Schließen") : tr("Vollbild"); });
  bar.append(node("span", "", tr("Vorschau (ohne Netzwerkzugriff)")), full);
  const frame = document.createElement("iframe");
  frame.setAttribute("sandbox", "allow-scripts");
  frame.setAttribute("referrerpolicy", "no-referrer");
  frame.title = tr("Vorschau");
  frame.src = `preview/${encodeURIComponent(id)}`;
  box.append(bar, frame);
  pre.after(box);
  button.textContent = tr("Schließen");
  box.scrollIntoView({ block: "center", behavior: "smooth" });
}

window.kiFile = { save: saveFile, preview: togglePreview };

function downloadButton(getText) {
  const button = node("button", "tool-btn");
  button.type = "button";
  button.append(icon("download"), document.createTextNode(tr("Als Datei")));
  button.addEventListener("click", () => { saveFile(tr("antwort.md"), getText(), "text/markdown").catch(() => toast(tr("Speichern hat nicht geklappt."))); });
  return button;
}

function copyButton(getText) {
  const button = node("button", "tool-btn");
  button.type = "button";
  const label = () => button.replaceChildren(icon("copy"), document.createTextNode(tr("Kopieren")));
  label();
  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(getText());
      button.replaceChildren(icon("check"), document.createTextNode(tr("Kopiert")));
    } catch {
      button.replaceChildren(document.createTextNode(tr("Nicht möglich")));
    }
    setTimeout(label, 1600);
  });
  return button;
}

function fileChip(file, removable) {
  const chip = node("div", "file-chip");
  const thumb = node("span", "file-thumb");
  if (file.thumb) thumb.style.backgroundImage = `url("${file.thumb}")`;
  else thumb.append(icon(file.kind === "image" ? "picture" : "file"));
  const meta = node("span", "file-meta");
  meta.append(node("b", "", file.name), node("small", "", `${KIND_LABEL[file.kind] || tr("Datei")} · ${formatSize(file.size)}`));
  chip.append(thumb, meta);
  if (removable) {
    const x = node("button", "file-x");
    x.type = "button";
    x.setAttribute("aria-label", tr("{0} entfernen", file.name));
    x.append(icon("close"));
    x.addEventListener("click", () => removeFile(file));
    chip.append(x);
  }
  return chip;
}

// Aktionen der KI in Home Assistant: eine einklappbare Liste, die sich während der Antwort laufend aktualisiert.
const ACTION_TEXT = {
  running: tr("läuft …"), waiting: tr("wartet auf deine Antwort"), ok: "", error: tr("fehlgeschlagen"), denied: tr("abgelehnt"), abgebrochen: tr("abgebrochen"),
};

function actionsEl(list = [], open = false) {
  const box = document.createElement("details");
  box.className = "act-log";
  box.open = open;
  const head = document.createElement("summary");
  box.append(head, node("ul", "act-list"));
  box.update = (items) => {
    const ha = items.filter((a) => ["read", "execute", "write"].includes(a.kind));
    const changes = ha.filter((a) => a.kind !== "read").length;
    const wissen = items.filter((a) => a.kind === "knowledge").length;
    const memory = items.filter((a) => a.kind === "memory").length;
    const made = items.filter((a) => a.kind === "file" && a.status === "ok").length;
    const edited = items.filter((a) => a.kind === "file-edit" && a.status === "ok").length;
    const looked = items.filter((a) => a.kind === "file-read").length;
    const gh = items.filter((a) => a.kind === "gh-read" || a.kind === "gh-write");
    const ghChanges = gh.filter((a) => a.kind === "gh-write" && a.status === "ok").length;
    const other = items.filter((a) => a.kind === "memory-read").length;
    const web = items.filter((a) => a.kind === "web");
    const searches = web.filter((a) => a.label.startsWith(tr("Websuche"))).length;
    const pages = web.length - searches;
    const parts = [];
    if (web.length) {
      const bits = [];
      if (searches) bits.push(trn(searches, "1 Suche", "{0} Suchen"));
      if (pages) bits.push(trn(pages, "1 Seite gelesen", "{0} Seiten gelesen"));
      parts.push(tr("Recherche im Web ({0})", bits.join(", ")));
    }
    if (ha.length) parts.push(trn(ha.length, "1 Aktion in Home Assistant", "{0} Aktionen in Home Assistant") + (changes ? trn(changes, ", davon 1 Änderung", ", davon {0} Änderungen") : ""));
    if (gh.length) parts.push(trn(gh.length, "1 Aktion bei GitHub", "{0} Aktionen bei GitHub") + (ghChanges ? trn(ghChanges, ", davon 1 Änderung", ", davon {0} Änderungen") : ""));
    if (wissen) parts.push(trn(wissen, "im Wissen nachgeschlagen", "{0}× im Wissen nachgeschlagen"));
    if (memory) parts.push(trn(memory, "Gedächtnis aktualisiert", "Gedächtnis {0}× aktualisiert"));
    if (made) parts.push(trn(made, "Datei erstellt", "{0} Dateien erstellt"));
    if (edited) parts.push(trn(edited, "Datei bearbeitet", "{0} Dateien bearbeitet"));
    const tried = items.filter((a) => a.kind === "file").length;
    if (!made && tried) parts.push(tr("Datei erstellen"));
    const triedEdit = items.filter((a) => a.kind === "file-edit").length;
    if (!edited && triedEdit) parts.push(tr("Datei bearbeiten"));
    if (looked && !made && !edited && !triedEdit) parts.push(trn(looked, "Datei angesehen", "{0} Dateien angesehen"));
    const lookedUp = items.filter((a) => a.kind === "memory-read" && a.label.startsWith(tr("Smarthome-Überblick"))).length;
    if (!parts.length && other - lookedUp > 0) parts.push(tr("Gedächtnis angesehen"));
    if (!parts.length && lookedUp) parts.push(tr("Smarthome-Überblick nachgesehen"));
    head.textContent = parts.join(" · ");
    box.hidden = items.length === 0;
    box.lastChild.replaceChildren(...items.map(actionLine));
  };
  box.update(list);
  return box;
}

function actionLine(a) {
  const li = node("li", `act-line ${a.status} ${a.kind}`);
  const mark = a.status === "running" ? node("span", "run-spin")
    : a.status === "ok" ? icon("check")
    : a.status === "waiting" ? icon("bolt")
    : icon("close");
  li.append(mark, node("span", "act-label", a.label));
  const text = a.status === "error" && a.note ? a.note : ACTION_TEXT[a.status] || "";
  if (text) li.append(node("span", "act-state", text));
  if (a.link && a.link.startsWith("https://github.com/")) {
    const link = node("a", "act-link", tr("Öffnen"));
    link.href = a.link;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    li.append(link);
  }
  return li;
}

// Dateien, die die KI erzeugt hat (Word, Excel, PDF …): eine Karte je Datei unter der Antwort, Download über den Server.
const FILE_TYPES = {
  docx: [tr("Word-Dokument"), "doc"], xlsx: [tr("Excel-Tabelle"), "sheet"], pptx: [tr("Präsentation"), "slides"], pdf: [tr("PDF-Dokument"), "pdf"],
  ps1: [tr("PowerShell-Skript"), "code"], psm1: [tr("PowerShell-Modul"), "code"], sh: [tr("Shell-Skript"), "code"], bash: [tr("Shell-Skript"), "code"],
  bat: [tr("Batch-Datei"), "code"], cmd: [tr("Batch-Datei"), "code"], py: [tr("Python-Skript"), "code"], js: ["JavaScript", "code"],
  csv: [tr("CSV-Tabelle"), "sheet"], tsv: [tr("Tabelle"), "sheet"], json: [tr("JSON-Datei"), "code"], yaml: [tr("YAML-Datei"), "code"], yml: [tr("YAML-Datei"), "code"],
  md: [tr("Markdown"), "doc"], txt: [tr("Textdatei"), "doc"], html: [tr("HTML-Seite"), "code"], xml: [tr("XML-Datei"), "code"],
};

function fileTypeOf(name) {
  const ext = (name.split(".").pop() || "").toLowerCase();
  return FILE_TYPES[ext] || [tr("{0}-Datei", ext.toUpperCase()), "code"];
}

async function downloadOutFile(file, card) {
  card.classList.add("busy-dl");
  try {
    const response = await fetch(`api/files/${encodeURIComponent(file.id)}`, { credentials: "same-origin", headers: { "X-Requested-With": "ki-chat" } });
    if (response.status === 404) { card.classList.add("gone"); toast(tr("Diese Datei ist abgelaufen.")); return; }
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const blob = await response.blob();
    await saveFile(file.name, blob, blob.type || "application/octet-stream");
  } catch {
    toast(tr("Der Download hat nicht geklappt."));
  } finally {
    card.classList.remove("busy-dl");
  }
}

function fileCard(file) {
  const [label, tone] = fileTypeOf(file.name);
  const card = node("button", `out-card tone-${tone}${file.gone ? " gone" : ""}`);
  card.type = "button";
  card.disabled = !!file.gone;
  card.setAttribute("aria-label", file.gone ? tr("{0} (abgelaufen)", file.name) : tr("{0} herunterladen", file.name));
  const tile = node("span", "out-tile");
  tile.append(icon("file"));
  const meta = node("span", "out-meta");
  meta.append(node("b", "", file.name), node("small", "", file.gone ? tr("Abgelaufen") : `${label} · ${formatSize(file.size)}`));
  const get = node("span", "out-get");
  get.append(icon("download"));
  card.append(tile, meta, get);
  card.addEventListener("click", () => downloadOutFile(file, card));
  return card;
}

function fileCardsEl(actions) {
  const box = node("div", "out-cards");
  box.update = (items) => {
    const files = items.filter((a) => a.file && a.status === "ok").map((a) => a.file);
    box.hidden = files.length === 0;
    box.replaceChildren(...files.map(fileCard));
  };
  box.update(actions);
  return box;
}

function messageEl(role, text, files = [], actions = []) {
  if (role === "user" && files.length) {
    const group = node("div", "msg-group");
    const row = node("div", "msg-files");
    for (const f of files) row.append(fileChip(f, false));
    group.append(row, messageEl("user", text));
    return group;
  }
  const el = node("div", `msg ${role}`);
  if (role === "assistant") {
    if (actions.length) el.append(actionsEl(actions));
    el.append(window.renderMarkdown(text));
    if (actions.some((a) => a.file)) el.append(fileCardsEl(actions));
    const tools = node("div", "msg-tools");
    tools.append(copyButton(() => text), downloadButton(() => text));
    el.append(tools);
  } else {
    el.textContent = text;
  }
  return el;
}

function scrollDown(force) {
  const box = $("messages");
  const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 140;
  if (force || nearBottom) box.scrollTop = box.scrollHeight;
}

// Trennlinie zwischen dem zusammengefassten älteren Verlauf und den wörtlich mitgeschickten Nachrichten.
function compactNote() {
  const note = node("div", "compact-note");
  note.append(icon("fold"), node("span", "", tr("Ältere Nachrichten sind zusammengefasst. Claude kennt sie ab hier nur als Zusammenfassung.")));
  return note;
}

function renderMessages(messages) {
  const thread = $("thread");
  thread.replaceChildren();
  thread.classList.remove("empty");
  if (messages.length === 0) { showHello(); return; }
  let seenLive = false;
  const anySummarized = messages.some((m) => m.summarized);
  for (const m of messages) {
    if (anySummarized && !seenLive && !m.summarized) { thread.append(compactNote()); }
    if (!m.summarized) seenLive = true;
    thread.append(messageEl(m.role, m.content, m.attachments || [], m.tools || []));
  }
}

async function selectChat(id) {
  if (state.streaming && state.streaming.chatId === id) return; // läuft hier schon
  setView("chat");
  detachRun(); // eine laufende Antwort bleibt auf dem Server und wird dort gespeichert
  releaseRecent();
  state.activeId = id;
  rememberActive();
  state.newProject = null;
  state.heldUnread = null;
  renderSide();
  closeMenu();
  const chat = state.chats.find((c) => c.id === id);
  setTitle(chat ? chat.title : idleTitle());
  useChatModel(chat || null);
  $("thread").replaceChildren();
  try {
    const messages = await api(`api/chats/${encodeURIComponent(id)}/messages`);
    renderMessages(messages);
    state.shownAt = chat ? chat.updated_at : null;
    scrollDown(true);
    focusInput();
    await markRead(id); // angezeigt = gelesen
    if (state.activeId === id) attachRun(id).catch(() => {}); // Antwort läuft noch? Dann live weiterverfolgen
  } catch {
    state.activeId = null;
    rememberActive();
    await loadAll().catch(() => {});
    showHello();
  }
}

function startNew(projectId = null) {
  setView("chat");
  detachRun();
  releaseRecent();
  state.activeId = null;
  rememberActive();
  state.heldUnread = null;
  state.newProject = projectId;
  renderSide();
  closeMenu();
  setTitle(idleTitle());
  useChatModel(null);
  showHello();
  focusInput();
}

async function renameChat(chat) {
  const title = await openSheet({ title: tr("Chat umbenennen"), label: tr("Name"), value: chat.title, ok: tr("Speichern") });
  if (!title) return;
  try {
    await patchChat(chat, { title: title.slice(0, 120) });
    await loadAll();
    if (state.activeId === chat.id) setTitle(title.slice(0, 120));
  } catch {
    toast(tr("Umbenennen hat nicht geklappt."));
  }
}

async function deleteChat(chat) {
  const yes = await openSheet({
    title: tr("Chat löschen?"),
    sub: tr("„{0}“ wird endgültig gelöscht.", chat.title),
    ok: tr("Löschen"),
    danger: true,
  });
  if (!yes) return;
  if (state.streaming?.chatId === chat.id) detachRun();
  try {
    await api(`api/chats/${encodeURIComponent(chat.id)}`, { method: "DELETE" });
  } catch {
    toast(tr("Löschen hat nicht geklappt."));
    return;
  }
  if (state.activeId === chat.id) startNew();
  await loadAll();
}

// Kurztitel von der KI holen (der erste Satz der Frage steht bis dahin als Vorlauf-Titel da).
async function refreshTitle(chatId) {
  try {
    const chat = await api(`api/chats/${encodeURIComponent(chatId)}/title`, { method: "POST" });
    const known = state.chats.find((c) => c.id === chatId);
    if (!known || known.title === chat.title) return;
    known.title = chat.title;
    renderSide();
    if (state.activeId === chatId) setTitle(chat.title);
  } catch { /* der Vorlauf-Titel bleibt */ }
}

// ----------------------------------------------------------------- Anhänge
// Dateien bleiben im Arbeitsspeicher des Browsers und gehen mit der Nachricht zum Server. Dort werden sie geprüft und
// weitergereicht; in der Datenbank stehen nur Name, Art und Größe. Mit der Option „Dateien bearbeiten“ legt der Server
// zusätzlich eine Kopie für diesen Chat ab, damit die KI sie lesen und bearbeiten kann (siehe attachments.persist).

const KIND_LABEL = { image: tr("Bild"), pdf: "PDF", text: tr("Text"), word: tr("Word"), excel: tr("Excel"), powerpoint: tr("PowerPoint") };
const MB = 1024 * 1024;
const NATIVE_PDF = 20 * MB; // größere PDFs liest der Server nur als Text (Obergrenze der Claude-API je Anfrage)
const NATIVE_TOTAL = 22 * MB; // Bilder und „angesehene“ PDFs zusammen
const nativeSize = (f) => (f.kind === "image" || (f.kind === "pdf" && f.blob.size <= NATIVE_PDF) ? f.blob.size : 0);
const LIMITS = { files: 5, total: 60 * MB, image: 5 * MB, pdf: 50 * MB, word: 50 * MB, excel: 50 * MB, powerpoint: 50 * MB, text: MB };
const IMAGE_PASSTHROUGH = 1.5 * 1024 * 1024;
const IMAGE_MAX_SIDE = 2000;
const IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"];
let fileId = 0;

function formatSize(size) {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  return `${(size / 1024 / 1024).toLocaleString(kiLocale, { minimumFractionDigits: 1, maximumFractionDigits: 1 })} MB`;
}

function fileKind(file) {
  if (file.type.startsWith("image/")) return "image";
  if (file.type === "application/pdf" || /\.pdf$/i.test(file.name)) return "pdf";
  if (/\.docx$/i.test(file.name)) return "word";
  if (/\.xlsx$/i.test(file.name)) return "excel";
  if (/\.pptx$/i.test(file.name)) return "powerpoint";
  return "text";
}

// Fotos verkleinern: Handy-Bilder sind oft mehrere MB groß; Claude braucht höchstens ~2000 Pixel.
async function prepareImage(file) {
  let bitmap;
  try { bitmap = await createImageBitmap(file); } catch { bitmap = null; }
  const small = IMAGE_TYPES.includes(file.type) && file.size <= IMAGE_PASSTHROUGH;
  if (!bitmap) {
    if (small) return { blob: file, name: file.name, thumb: "" };
    throw new Error(tr("„{0}“ konnte nicht als Bild gelesen werden.", file.name));
  }
  const draw = (maxSide, type, quality) => {
    const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    const ctx = canvas.getContext("2d");
    if (type === "image/jpeg") { ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, canvas.width, canvas.height); }
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    return type ? new Promise((resolve) => canvas.toBlob(resolve, type, quality)) : canvas.toDataURL("image/jpeg", 0.7);
  };
  const thumb = draw(72, null);
  let blob = file;
  let name = file.name;
  if (!small) {
    blob = await draw(IMAGE_MAX_SIDE, "image/jpeg", 0.85);
    if (!blob) throw new Error(tr("„{0}“ konnte nicht verkleinert werden.", file.name));
    name = name.replace(/\.[^.]*$/, "") + ".jpg";
  }
  bitmap.close?.();
  return { blob, name, thumb: await thumb };
}

async function addFiles(list) {
  if (state.streaming) { toast(tr("Während einer Antwort können keine Dateien hinzugefügt werden.")); return; }
  const incoming = [...list];
  if (!incoming.length) return;
  let rejected = null;
  for (const raw of incoming) {
    if (state.files.length >= LIMITS.files) { rejected = tr("Höchstens {0} Dateien pro Nachricht.", LIMITS.files); break; }
    const kind = fileKind(raw);
    try {
      let item = { id: ++fileId, kind, name: raw.name || tr("Datei"), blob: raw, thumb: "" };
      if (kind === "image") Object.assign(item, await prepareImage(raw));
      if (item.blob.size > LIMITS[kind]) throw new Error(tr("„{0}“ ist zu groß (höchstens {1}).", item.name, formatSize(LIMITS[kind])));
      if (item.blob.size === 0) throw new Error(tr("„{0}“ ist leer.", item.name));
      const total = state.files.reduce((sum, f) => sum + f.blob.size, 0) + item.blob.size;
      if (total > LIMITS.total) throw new Error(tr("Die Dateien sind zusammen zu groß (höchstens {0}).", formatSize(LIMITS.total)));
      const native = state.files.reduce((sum, f) => sum + nativeSize(f), 0) + nativeSize(item);
      if (native > NATIVE_TOTAL) throw new Error(tr("Bilder und PDFs zusammen sind zu groß (höchstens {0}).", formatSize(NATIVE_TOTAL)));
      item.size = item.blob.size;
      state.files.push(item);
    } catch (err) {
      rejected = err.message;
    }
  }
  renderTray();
  if (rejected) toast(rejected);
}

function releaseRecent() {
  for (const f of state.recent) f.blob = null;
  state.recent = [];
}

// Dieselben Dateien für die nächste Frage noch einmal anhängen: kommt aus dem Browser-Speicher, nicht vom Server.
function reattachButton(files) {
  const button = node("button", "reattach");
  button.type = "button";
  button.append(icon("attach"), node("span", "", files.length === 1 ? tr("Wieder anhängen") : tr("Alle wieder anhängen")));
  button.addEventListener("click", () => {
    if (state.streaming) return;
    let added = 0;
    for (const f of files) {
      if (!f.blob || state.files.some((x) => x.blob === f.blob)) continue;
      const total = state.files.reduce((sum, x) => sum + x.blob.size, 0) + f.blob.size;
      if (state.files.length >= LIMITS.files || total > LIMITS.total) { toast(tr("Mehr passt nicht in eine Nachricht.")); break; }
      state.files.push({ ...f, id: ++fileId });
      added += 1;
    }
    renderTray();
    if (added) { toast(tr("Dateien angehängt.")); $("input").focus({ preventScroll: true }); }
  });
  return button;
}

function removeFile(file) {
  state.files = state.files.filter((f) => f.id !== file.id);
  renderTray();
}

function renderTray() {
  const tray = $("attach-tray");
  tray.replaceChildren(...state.files.map((f) => fileChip(f, true)));
  tray.hidden = state.files.length === 0;
  $("input").placeholder = state.files.length ? tr("Frage zu den Dateien stellen") : tr("Nachricht schreiben");
}

function toBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

function initAttachments() {
  const picker = $("file-input");
  $("attach").addEventListener("click", () => {
    if (state.streaming) { toast(tr("Während einer Antwort können keine Dateien hinzugefügt werden.")); return; }
    picker.click();
  });
  picker.addEventListener("change", () => {
    const chosen = [...picker.files];
    picker.value = "";
    addFiles(chosen);
  });
  // Dateien aus der Zwischenablage (z. B. Screenshot) einfügen
  $("input").addEventListener("paste", (event) => {
    const files = [...(event.clipboardData?.files || [])];
    if (!files.length) return;
    event.preventDefault();
    addFiles(files);
  });
  // Dateien auf die Seite ziehen
  let depth = 0;
  const hint = $("drop-hint");
  const hasFiles = (event) => [...(event.dataTransfer?.types || [])].includes("Files");
  window.addEventListener("dragenter", (event) => { if (hasFiles(event)) { depth += 1; hint.hidden = false; } });
  window.addEventListener("dragleave", (event) => { if (hasFiles(event) && --depth <= 0) { depth = 0; hint.hidden = true; } });
  window.addEventListener("dragover", (event) => { if (hasFiles(event)) event.preventDefault(); });
  window.addEventListener("drop", (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    depth = 0;
    hint.hidden = true;
    addFiles(event.dataTransfer.files);
  });
}

// ----------------------------------------------------------------- Senden

function setStreaming(active) {
  const button = $("send");
  button.replaceChildren(icon(active ? "stop" : "arrowUp", active));
  button.classList.toggle("stop", active);
  button.setAttribute("aria-label", active ? tr("Antwort stoppen") : tr("Senden"));
  $("input").readOnly = active;
}

function autosize() {
  const input = $("input");
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, window.innerHeight * 0.4)}px`;
}

async function readEvents(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      if (block.startsWith("data: ")) onEvent(JSON.parse(block.slice(6)));
    }
  }
}

// Die Antwort gehört dem Server: Er erzeugt und speichert sie auch dann, wenn dieser Tab den Chat wechselt oder neu lädt.
// Der Browser hängt sich nur an (Senden oder später wieder Anhängen) und zeigt den Verlauf an.
function openRun(chatId) {
  const run = { chatId, controller: new AbortController(), accepted: false, detached: false, stopping: false };
  state.streaming = run;
  setStreaming(true);
  return run;
}

function closeRun(run) {
  if (state.streaming === run) { state.streaming = null; setStreaming(false); }
}

// Ansicht verlässt den laufenden Chat: Verbindung kappen (Server arbeitet weiter), Eingabe sofort wieder frei.
function detachRun() {
  const run = state.streaming;
  if (!run) return;
  run.detached = true;
  clearAsks(run);
  run.busy?.stop();
  state.streaming = null;
  setStreaming(false);
  if (run.accepted) run.controller.abort(); // sonst: sobald der Server die Nachricht angenommen hat (siehe sendMessage)
}

// Stopp-Knopf: Der Server bricht die Antwort ab und behält den bisherigen Text.
function stopAnswer() {
  const run = state.streaming;
  if (!run || run.stopping) return;
  run.stopping = true;
  api(`api/chats/${encodeURIComponent(run.chatId)}/stop`, { method: "POST" }).catch(() => {});
  setTimeout(() => { if (!run.detached) run.controller.abort(); }, 4000); // Notbremse, falls der Server nicht antwortet
}

async function consume(response, run, bubble) {
  const out = { answer: "", failure: null, title: null, compacted: false, ended: false, actions: [] };
  // Aufbau der Blase: Aktionsliste, Text, offene Rückfragen (entsteht erst mit dem ersten Inhalt, damit der leere Zustand erhalten bleibt)
  const parts = {};
  const byId = new Map();
  const cards = new Map(); // offene Rückfragen: stehen über dem Eingabefeld (Dock), nicht im Verlauf
  run.cards = cards;
  const build = () => {
    if (parts.text) return;
    parts.log = actionsEl([], true);
    parts.log.hidden = true;
    parts.text = node("div", "act-text");
    parts.files = fileCardsEl([]);
    bubble.replaceChildren(parts.log, parts.text, parts.files, ...(run.busy ? [run.busy.el] : []));
  };
  // Was die Warteanzeige gerade zeigt: laufende Aktion, Rückfrage, Hinweistext oder (sobald Text kommt) nur das kleine Zeichen
  let statusText = "";
  const syncBusy = () => {
    if (!run.busy || run.detached) return;
    const running = out.actions.filter((a) => a.status === "running");
    const waiting = out.actions.some((a) => a.status === "waiting") || cards.size > 0;
    run.busy.set({ tool: running.at(-1)?.label || "", status: statusText, waiting, streaming: !!out.answer && !running.length && !waiting });
  };
  let frame = 0;
  const paint = () => {
    frame = 0;
    if (run.detached) return;
    build();
    parts.text.replaceChildren(window.renderMarkdown(out.answer));
    scrollDown(false);
  };
  try {
    await readEvents(response, (ev) => {
      if (ev.type === "delta") {
        out.answer += ev.text;
        statusText = "";
        if (!frame) frame = requestAnimationFrame(paint);
      } else if (ev.type === "status") {
        statusText = ev.text.replace(/\s*…\s*$/, "");
      } else if (ev.type === "tool") {
        byId.set(ev.id, { label: ev.label, kind: ev.kind, status: ev.status, note: ev.note || "", file: ev.file || null, link: ev.link || "" });
        out.actions = [...byId.values()];
        if (!run.detached) { build(); parts.log.update(out.actions); parts.files.update(out.actions); scrollDown(false); }
      } else if (ev.type === "approval") {
        if (!run.detached) { build(); const card = approvalCard(run.chatId, ev); cards.set(ev.id, card); $("dock-asks").append(card); syncDock(); }
      } else if (ev.type === "approval_done") {
        cards.get(ev.id)?.remove();
        cards.delete(ev.id);
        syncDock();
      } else if (ev.type === "compacted") {
        out.compacted = true;
      } else if (ev.type === "error") {
        out.failure = { message: withReset(ev.message, ev.resets_at), text: ev.text || "" };
        out.ended = true;
        refreshLimits().catch(() => {});
      } else if (ev.type === "done") {
        out.title = ev.title;
        out.ended = true;
        refreshLimits().catch(() => {});
      }
      syncBusy();
    });
  } catch (err) {
    if (err.name !== "AbortError") out.lost = true;
  } finally {
    if (frame) cancelAnimationFrame(frame);
    clearAsks(run);
  }
  // Strom ohne Abschluss, ohne dass wir ihn selbst beendet haben: Verbindung verloren, der Server macht weiter.
  if (!out.ended && !run.controller.signal.aborted) out.lost = true;
  if (run.controller.signal.aborted) out.lost = false;
  return out;
}

// ------------------------------------------------- Warteanzeige
// Solange die KI arbeitet: kleines bewegtes Zeichen plus ein Wort (oder die laufende Aktion, z. B. „Entitäten suchen: Licht“).
// Beim Schreiben bleibt nur das kleine Zeichen unter dem Text. Nach 20 s kommt die Wartezeit dazu, nach 60 s ein Hinweis.

const THINK_WORDS = [tr("Denkt nach"), tr("Überlegt"), tr("Tüftelt"), tr("Sortiert Gedanken"), tr("Wägt ab"), tr("Grübelt"), tr("Knobelt"), tr("Formuliert")];
const BUSY_SHOW_TIME = 20;
const BUSY_SHOW_HINT = 60;

function makeBusy() {
  const el = node("div", "busy");
  el.setAttribute("role", "status");
  const spark = node("span", "spark");
  const word = node("span", "busy-word");
  const extra = node("span", "busy-extra");
  const hint = node("p", "busy-hint", tr("Das dauert etwas länger. Du kannst den Chat verlassen, die Antwort wird trotzdem fertig."));
  for (const part of [spark, word, extra, hint]) part.setAttribute("aria-hidden", "true");
  hint.hidden = true;
  el.append(node("span", "sr-only", tr("Die Antwort wird erstellt")), spark, word, extra, hint);

  const started = Date.now();
  const words = [...THINK_WORDS].sort(() => Math.random() - 0.5);
  const now = { tool: "", status: "", waiting: false, streaming: false };
  let index = 0;
  let shown = "";
  let timer = 0;

  const paint = () => {
    const seconds = Math.floor((Date.now() - started) / 1000);
    el.classList.toggle("compact", now.streaming);
    el.classList.toggle("paused", now.waiting);
    const label = now.waiting ? tr("Wartet auf deine Freigabe") : (now.tool || now.status || words[index % words.length]) + " …";
    if (label !== shown) {
      shown = label;
      word.textContent = label;
      word.classList.remove("swap");
      void word.offsetWidth; // Animation neu starten
      word.classList.add("swap");
    }
    extra.textContent = !now.streaming && !now.waiting && seconds >= BUSY_SHOW_TIME ? `${seconds} s` : "";
    hint.hidden = now.streaming || now.waiting || seconds < BUSY_SHOW_HINT;
  };
  const stop = () => { clearInterval(timer); timer = 0; };
  let ticks = 0;
  timer = setInterval(() => {
    if (!el.isConnected) { stop(); return; }
    if (++ticks % 4 === 0) index += 1; // alle 4 Sekunden ein neues Wort
    paint();
  }, 1000);
  paint();
  return {
    el,
    stop,
    set(next) { Object.assign(now, next); paint(); },
  };
}

function addBusy(run, bubble) {
  run.busy = makeBusy();
  bubble.append(run.busy.el);
}

// Kurzwahl: ⌘ (Mac) bzw. Strg (Windows, Linux) plus Umschalt plus Buchstabe. Mit Umschalt, weil Strg/⌘ allein
// (F, N, P …) dem Browser gehört. Die Taste steht nur im Hover am Knopf; am Handy gibt es sie nicht.
const IS_MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || "");
const shortcutText = (letter) => (IS_MAC ? `⇧⌘${letter}` : tr("Strg+Umschalt+{0}", letter));

function initShortcuts() {
  for (const key of document.querySelectorAll(".nav-key[data-key]")) key.textContent = shortcutText(key.dataset.key);
  const actions = {
    KeyO: () => startNew(),
    KeyF: () => openSearch(),
    KeyP: () => createProject(),
    KeyG: () => (state.me?.schedules ? openSchedules() : null),
  };
  document.addEventListener("keydown", (event) => {
    const mod = IS_MAC ? event.metaKey && !event.ctrlKey : event.ctrlKey && !event.metaKey;
    const run = actions[event.code];
    if (!run || !mod || !event.shiftKey || event.altKey || event.isComposing) return;
    event.preventDefault();
    if (sheetDone) return;
    Promise.resolve(run()).catch(() => {});
  });
}

// Dock über dem Eingabefeld: Nutzungslimit und offene Rückfragen der KI (wie in Claude selbst).
function syncDock() {
  const dock = $("dock");
  if (!dock) return;
  dock.hidden = $("limit-notices").hidden && $("dock-asks").childElementCount === 0;
}

function clearAsks(run) {
  for (const card of run.cards?.values() || []) card.remove();
  run.cards?.clear();
  syncDock();
}

// Rückfrage der KI vor einer Änderung in Home Assistant.
function approvalCard(chatId, ev) {
  const card = node("div", "ask-card");
  card.setAttribute("role", "group");
  card.setAttribute("aria-label", tr("Rückfrage"));
  const question = { github: tr("Soll diese Änderung bei GitHub ausgeführt werden?"), memory: tr("Soll die KI das im Gedächtnis ändern?") }[ev.topic] || tr("Soll diese Änderung in Home Assistant ausgeführt werden?");
  card.append(node("div", "ask-title", question), node("div", "ask-what", ev.label));
  if (ev.details) {
    const more = document.createElement("details");
    more.className = "ask-details";
    more.append(node("summary", "", tr("Einzelheiten")), node("pre", "", ev.details));
    card.append(more);
  }
  const row = node("div", "ask-actions");
  const answer = async (decision) => {
    for (const b of row.querySelectorAll("button")) b.disabled = true;
    try {
      await api(`api/chats/${encodeURIComponent(chatId)}/approve`, { method: "POST", body: JSON.stringify({ id: ev.id, decision }) });
    } catch {
      toast(tr("Die Rückfrage ist nicht mehr offen."));
    }
  };
  const mk = (label, cls, decision) => {
    const b = node("button", `pill ${cls}`, label);
    b.type = "button";
    b.addEventListener("click", () => answer(decision));
    return b;
  };
  row.append(mk(tr("Zulassen"), "primary", "allow"), mk(tr("Ablehnen"), "ghost", "deny"));
  if (ev.chat_ok) row.append(mk(tr("In diesem Chat immer zulassen"), "ghost", "allow_chat"));
  card.append(row);
  return card;
}

const SEND_ERRORS = {
  409: tr("In diesem Chat läuft bereits eine Antwort."),
  413: tr("Die Dateien sind zusammen zu groß für eine Nachricht."),
  429: tr("Gerade zu viele Anfragen. Bitte kurz warten."),
  404: tr("Dieser Chat existiert nicht mehr."),
};

async function sendFailure(response) {
  if (response.status === 401) { window.location.assign("login"); return new Error("HTTP 401"); }
  let detail = "";
  if (response.status === 422) {
    try { const body = await response.json(); if (typeof body.detail === "string") detail = body.detail; } catch { /* kein Text */ }
  }
  return new Error(detail || SEND_ERRORS[response.status] || tr("Fehler {0}", response.status));
}

// Nach dem Strom: Ansicht abschließen (oder, wenn man den Chat inzwischen verlassen hat, nur die Liste auffrischen).
async function settleRun(run, bubble, out, view = {}) {
  const chatId = run.chatId;
  run.busy?.stop();
  closeRun(run);
  bubble.classList.remove("pending");
  if (run.detached) {
    if (out.failure && !out.answer) toast(out.failure.message);
    await loadAll().catch(() => {});
    return;
  }
  const thread = $("thread");
  if (out.lost) {
    // Verbindung weg, Antwort läuft auf dem Server weiter: neu anhängen (der Text wird von vorn nachgeliefert).
    bubble.remove();
    const attempts = (view.attempts || 0) + 1;
    if (attempts <= 6) setTimeout(() => { if (state.activeId === chatId) attachRun(chatId, attempts).catch(() => {}); }, 1500);
    return;
  }
  if (out.answer) bubble.replaceWith(messageEl("assistant", out.answer, [], out.actions));
  else bubble.remove();
  if (out.failure) {
    if (!out.answer) {
      // Nichts gespeichert: Frage samt Dateien zurück ins Eingabefeld.
      const input = $("input");
      if (view.userEl) {
        view.userEl.remove();
        input.value = view.text;
        if (state.files.length === 0 && view.sentFiles) { state.files = view.sentFiles; renderTray(); }
      } else {
        try { renderMessages(await api(`api/chats/${encodeURIComponent(chatId)}/messages`)); } catch { /* bleibt */ }
        if (!input.value && out.failure.text) input.value = out.failure.text;
      }
      autosize();
    }
    thread.append(node("div", "msg error", out.failure.message));
  }
  // Nur die zuletzt gesendeten Dateien bleiben im Browser-Speicher (zum erneuten Anhängen), nie auf dem Server.
  if (view.sentFiles) {
    releaseRecent();
    if (state.files !== view.sentFiles && out.answer && view.sentFiles.length) {
      state.recent = view.sentFiles;
      view.userEl?.querySelector(".msg-files")?.append(reattachButton(view.sentFiles));
    } else if (state.files !== view.sentFiles) {
      for (const f of view.sentFiles) f.blob = null;
    }
  }
  scrollDown(true);
  // Wird die Antwort gerade angesehen, gilt sie als gelesen; liegt das Fenster im Hintergrund, bleibt der Chat ungelesen.
  if (out.answer && !document.hidden) await patchChat({ id: chatId }, { unread: false }).catch(() => {});
  await loadAll().catch(() => {});
  if (state.activeId === chatId) state.shownAt = state.chats.find((c) => c.id === chatId)?.updated_at ?? null;
  if (out.compacted && state.activeId === chatId) {
    // Trennlinie „ab hier zusammengefasst“ einblenden
    try { renderMessages(await api(`api/chats/${encodeURIComponent(chatId)}/messages`)); } catch { /* bleibt wie es ist */ }
  }
  if (out.title && state.activeId === chatId) setTitle(out.title);
  focusInput();
  if (out.answer && view.first) refreshTitle(chatId);
}

// Wieder an eine laufende Antwort anhängen (Seite neu geladen oder in den Chat zurückgekehrt).
async function attachRun(chatId, attempts = 0) {
  if (state.streaming || state.activeId !== chatId) return;
  const run = openRun(chatId);
  let response;
  try {
    response = await fetch(`api/chats/${encodeURIComponent(chatId)}/run`, {
      credentials: "same-origin",
      signal: run.controller.signal,
      headers: { "X-Requested-With": "ki-chat" },
    });
  } catch {
    closeRun(run);
    return;
  }
  if (response.status === 401) { window.location.assign("login"); return; }
  if (response.status !== 200) {
    closeRun(run);
    if (attempts > 0) await reloadActive(chatId); // vorhin noch laufend, jetzt fertig: gespeicherten Stand zeigen
    return;
  }
  run.accepted = true;
  const thread = $("thread");
  const first = !thread.querySelector(".msg.assistant");
  const bubble = node("div", "msg assistant pending");
  addBusy(run, bubble);
  thread.append(bubble);
  scrollDown(true);
  const out = await consume(response, run, bubble);
  await settleRun(run, bubble, out, { attempts, first });
}

async function reloadActive(chatId) {
  try {
    const messages = await api(`api/chats/${encodeURIComponent(chatId)}/messages`);
    if (state.activeId !== chatId || state.streaming) return;
    renderMessages(messages);
    await loadAll();
    state.shownAt = state.chats.find((c) => c.id === chatId)?.updated_at ?? null;
    scrollDown(true);
    if (!document.hidden && state.heldUnread !== chatId) await markRead(chatId);
  } catch { /* beim nächsten Auffrischen */ }
}

async function sendMessage() {
  if (state.streaming) { stopAnswer(); return; }
  const input = $("input");
  const text = input.value.trim();
  if (!text) {
    if (state.files.length) toast(tr("Schreibe noch eine Frage zu den Dateien."));
    return;
  }

  if (!state.activeId) {
    try {
      const body = state.newProject ? { project_id: state.newProject } : {};
      const chat = await api("api/chats", { method: "POST", body: JSON.stringify(body) });
      if (chat.project_id) { ui.projectsOpen = true; ui.openProjects.add(chat.project_id); saveUi(); }
      state.newProject = null;
      state.activeId = chat.id;
      rememberActive();
      await loadAll();
      $("thread").replaceChildren();
    } catch {
      toast(tr("Der Chat konnte nicht angelegt werden."));
      return;
    }
  }
  const chatId = state.activeId;
  const thread = $("thread");
  const first = !thread.querySelector(".msg");
  thread.querySelector(".hello")?.remove();
  thread.classList.remove("empty");

  const sentFiles = state.files;
  state.files = [];
  renderTray();
  const userEl = messageEl("user", text, sentFiles);
  const bubble = node("div", "msg assistant pending");
  thread.append(userEl, bubble);
  scrollDown(true);

  input.value = "";
  autosize();
  const run = openRun(chatId);
  addBusy(run, bubble);
  const view = { userEl, text, sentFiles, first };

  let out;
  try {
    const files = await Promise.all(sentFiles.map(async (f) => ({ name: f.name, data: await toBase64(f.blob) })));
    const response = await fetch(`api/chats/${encodeURIComponent(chatId)}/send`, {
      method: "POST",
      credentials: "same-origin",
      signal: run.controller.signal,
      headers: { "X-Requested-With": "ki-chat", "Content-Type": "application/json" },
      body: JSON.stringify({
        content: text, effort: state.effort, files,
        ...((state.me?.models?.length || 0) > 1 && validModel(state.model) ? { model: state.model } : {}),
        ...(state.me?.web && !state.web ? { web: false } : {}),
      }),
    });
    if (!response.ok) throw await sendFailure(response);
    run.accepted = true; // ab hier gehört die Antwort dem Server
    loadAll().catch(() => {}); // Kreisel und Titel in der Liste sofort anzeigen
    if (run.detached) run.controller.abort(); // Chat wurde schon während des Hochladens verlassen
    out = await consume(response, run, bubble);
  } catch (err) {
    out = { answer: "", failure: null, title: null, compacted: false, ended: false };
    if (err.name !== "AbortError") out.failure = { message: err.message || tr("Die Verbindung wurde unterbrochen."), text: "" };
  }
  await settleRun(run, bubble, out, view);
}

// -------------------------------------------------------------------- Start

// Aufwand und Modell stehen in einem Knopf unter dem Eingabefeld; das Menü dazu ist toolsMenu().
const EFFORTS = [["low", tr("Niedrig")], ["medium", tr("Mittel")], ["high", tr("Hoch")]];
const effortLabel = (value) => EFFORTS.find(([key]) => key === value)?.[1] || "";

// Hinweise des Add-ons (ablaufende Zugangsdaten, Datenbank). Weggeklickt gilt pro Browser-Sitzung.
function renderNotices(list, box = $("notices")) {
  let dismissed = [];
  try { dismissed = JSON.parse(sessionStorage.getItem("ki-notices") || "[]"); } catch { /* optional */ }
  box.replaceChildren();
  for (const notice of list || []) {
    if (dismissed.includes(notice.id)) continue;
    const row = node("div", `notice ${notice.level === "error" ? "error" : "warn"}`);
    row.setAttribute("role", "alert");
    if (box.id === "limit-notices") row.append(icon("info"));
    row.append(node("span", "notice-text", notice.text));
    if (notice.action) {
      const go = node("button", "notice-btn", notice.action.label);
      go.type = "button";
      go.addEventListener("click", notice.action.run);
      row.append(go);
    }
    row.append(actionButton(tr("Hinweis ausblenden"), "close", "", () => {
      dismissed.push(notice.id);
      try { sessionStorage.setItem("ki-notices", JSON.stringify(dismissed)); } catch { /* optional */ }
      renderNotices(list, box);
    }));
    box.append(row);
  }
  box.hidden = box.children.length === 0;
  syncDock();
}

// ------------------------------------------------- Nutzungslimit, Modell und Websuche

const LIMIT_NAMES = { five_hour: tr("Das Sitzungslimit (5 Stunden)"), seven_day: tr("Das Wochenlimit"), seven_day_opus: tr("Das Wochenlimit für Opus"), seven_day_sonnet: tr("Das Wochenlimit für Sonnet"), overage: tr("Die Zusatznutzung") };

// „um 17:30 Uhr“, „morgen um 08:00 Uhr“ oder „am Do., 29.10. um 08:00 Uhr“ (Ortszeit des Browsers)
function whenText(ts) {
  const d = new Date(ts * 1000);
  const now = new Date();
  const time = d.toLocaleTimeString(kiLocale, { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === now.toDateString()) return tr("um {0} Uhr", time);
  if (d.toDateString() === new Date(now.getTime() + 86400000).toDateString()) return tr("morgen um {0} Uhr", time);
  return tr("am {0} um {1} Uhr", d.toLocaleDateString(kiLocale, { weekday: "short", day: "numeric", month: "numeric" }), time);
}

function withReset(message, resetsAt) {
  return resetsAt ? `${message} ${tr("Es wird {0} zurückgesetzt.", whenText(resetsAt))}` : message;
}

function limitNotices(list) {
  return (list || []).map((l) => {
    const name = LIMIT_NAMES[l.type] || tr("Das Nutzungslimit");
    const pct = typeof l.utilization === "number" ? Math.round(l.utilization * 100) : null;
    const when = l.resets_at ? whenText(l.resets_at) : "";
    const reset = when ? ` ${tr("Es wird {0} zurückgesetzt.", when)}` : "";
    const text = l.status === "rejected"
      ? `${tr("{0} ist erreicht.", name)}${when ? reset : ` ${tr("Bitte später erneut versuchen.")}`}`
      : (pct !== null ? tr("{0} ist zu {1} % verbraucht.", name, pct) : tr("{0} ist fast erreicht.", name)) + reset;
    return { id: `limit-${l.type}-${l.status}-${l.resets_at || 0}`, level: l.status === "rejected" ? "error" : "warn", text };
  });
}

async function refreshLimits() {
  if (!state.me) return;
  renderNotices(limitNotices(await api("api/limits")), $("limit-notices"));
}

const validModel = (id) => !!id && !!state.me?.models?.some((m) => m.id === id);
const effectiveModel = () => (validModel(state.model) ? state.model : state.me?.default_model || "");
const modelLabel = (id) => state.me?.models?.find((m) => m.id === id)?.label || id;

function markTools() {
  const me = state.me;
  const hasModels = (me?.models?.length || 0) > 1;
  const btn = $("tools");
  const model = hasModels ? modelLabel(effectiveModel()) : "";
  $("tools-name").textContent = model;
  $("tools-effort").textContent = effortLabel(state.effort);
  btn.classList.toggle("web-off", !!me?.web && !state.web);
  btn.setAttribute("aria-label", `${tr("Modell, Aufwand und Websuche")}: ${[model, effortLabel(state.effort)].filter(Boolean).join(", ")}`);
}

// Modell des geöffneten Chats (gemerkt auf dem Server) oder, bei einem neuen Chat, das zuletzt gewählte.
function useChatModel(chat) {
  if (chat) { state.model = validModel(chat.model) ? chat.model : ""; }
  else {
    let stored = "";
    try { stored = localStorage.getItem("ki-model") || ""; } catch { /* optional */ }
    state.model = validModel(stored) ? stored : "";
  }
  markTools();
}

const MODEL_HINTS = { sonnet: tr("Am effizientesten für einfachere Aufgaben"), opus: tr("Für komplexe Arbeit und alltägliche Aufgaben"), haiku: tr("Am schnellsten für schnelle Antworten") };
const modelHint = (id) => MODEL_HINTS[Object.keys(MODEL_HINTS).find((family) => id.includes(family))] || "";

// Handy: Fenster „Modell auswählen“ wie in Claude (Modelle mit Kurzbeschreibung, „Aufwand“ als zweite Seite, Websuche).
async function phoneToolsMenu() {
  const me = state.me;
  const models = me.models || [];
  const current = effectiveModel();
  const button = $("tools");
  button.setAttribute("aria-expanded", "true");
  let choice;
  try {
    choice = await openSheet({
      title: tr("Modell auswählen"),
      plain: true,
      panel: (body) => {
        const row = (cls, ...children) => {
          const b = node("button", cls);
          b.type = "button";
          b.append(...children);
          return b;
        };
        const pick = (value) => () => closeSheet(value);
        const main = () => {
          $("sheet-title").textContent = models.length > 1 ? tr("Modell auswählen") : tr("Modell, Aufwand und Websuche");
          body.replaceChildren();
          if (models.length > 1) {
            const card = node("div", "mm-card");
            for (const m of models) {
              const text = node("span", "mm-text");
              text.append(node("span", "mm-name", m.label));
              if (modelHint(m.id)) text.append(node("span", "mm-hint", modelHint(m.id)));
              const r = row("mm-row", text, ...(m.id === current ? [icon("check")] : []));
              r.addEventListener("click", pick(`model:${m.id}`));
              card.append(r);
            }
            body.append(card);
          }
          const effort = row("mm-link", node("span", "mm-name", tr("Aufwand")), node("span", "mm-detail", effortLabel(state.effort)), icon("chevron"));
          effort.addEventListener("click", effortPage);
          body.append(effort);
          if (me.web) {
            const sw = node("span", "pop-switch" + (state.web ? " on" : ""));
            sw.setAttribute("aria-hidden", "true");
            const web = row("mm-link", node("span", "mm-name", tr("Websuche")), sw);
            web.setAttribute("role", "menuitemcheckbox");
            web.setAttribute("aria-checked", String(state.web));
            web.addEventListener("click", pick("web"));
            body.append(web);
          }
        };
        const effortPage = () => {
          $("sheet-title").textContent = tr("Aufwand");
          body.replaceChildren();
          const back = row("mm-back", icon("chevron"), node("span", "", tr("Zurück")));
          back.addEventListener("click", main);
          const card = node("div", "mm-card");
          for (const [value, label] of EFFORTS) {
            const r = row("mm-row", node("span", "mm-text", label), ...(value === state.effort ? [icon("check")] : []));
            r.firstChild.className = "mm-text mm-name";
            r.addEventListener("click", pick(`effort:${value}`));
            card.append(r);
          }
          body.append(back, card);
        };
        main();
      },
    });
  } finally {
    button.setAttribute("aria-expanded", "false");
  }
  return choice;
}

// Menü am Knopf unter dem Eingabefeld wie in Claude: gewähltes Modell, „Aufwand“ und „Weitere Modelle“ als Untermenüs, Websuche.
// Auf dem Handy dieselben Punkte als flache Liste.
async function toolsMenu() {
  const me = state.me;
  const models = me.models || [];
  const current = effectiveModel();
  const several = models.length > 1;
  let choice;
  if (!wideScreen()) {
    choice = await phoneToolsMenu();
  } else {
    const entries = [];
    if (several) entries.push({ value: `model:${current}`, label: modelLabel(current), active: true });
    entries.push({ label: tr("Aufwand"), detail: effortLabel(state.effort), submenu: EFFORTS.map(([value, label]) => ({ value: `effort:${value}`, label, active: value === state.effort })) });
    if (several) entries.push({ label: tr("Weitere Modelle"), submenu: models.filter((m) => m.id !== current).map((m) => ({ value: `model:${m.id}`, label: m.label })) });
    if (me.web) {
      entries.push({ divider: true });
      entries.push({ value: "web", icon: "globe", label: tr("Websuche"), active: state.web, toggle: state.web });
    }
    const button = $("tools");
    button.setAttribute("aria-expanded", "true");
    try {
      choice = await openPopover(button, entries, {});
    } finally {
      button.setAttribute("aria-expanded", "false");
    }
  }
  if (typeof choice === "string" && choice.startsWith("model:")) {
    state.model = choice.slice(6);
    try { localStorage.setItem("ki-model", state.model); } catch { /* optional */ }
  } else if (typeof choice === "string" && choice.startsWith("effort:")) {
    state.effort = choice.slice(7);
    try { localStorage.setItem("ki-effort", state.effort); } catch { /* optional */ }
  } else if (choice === "web") {
    state.web = !state.web;
    try { localStorage.setItem("ki-web", state.web ? "on" : "off"); } catch { /* optional */ }
    toast(state.web ? tr("Websuche ist an.") : tr("Websuche ist aus."));
  }
  markTools();
}

// Seitenleiste einklappen: nur im Web am Computer. In Home Assistant gibt es schon die Seitenleiste von HA.
function initSideToggle() {
  if (!isWeb()) return;
  const apply = (collapsed) => {
    $("app").classList.toggle("collapsed", collapsed);
    $("side-toggle").setAttribute("aria-expanded", String(!collapsed));
  };
  let stored = null;
  try { stored = localStorage.getItem("ki-side"); } catch { /* optional */ }
  apply(stored === "closed");
  $("side-toggle").addEventListener("click", () => {
    const collapsed = !$("app").classList.contains("collapsed");
    apply(collapsed);
    try { localStorage.setItem("ki-side", collapsed ? "closed" : "open"); } catch { /* optional */ }
  });
}


// ------------------------------------------------------------------ Geplant
// Aufgaben, die die KI zu festen Zeiten ohne Rückfragen erledigt. Das Ergebnis steht danach als neuer Chat in der Liste.

const FREQS = [["daily", tr("Täglich")], ["weekdays", tr("Montag bis Freitag")], ["weekly", tr("Wöchentlich")], ["monthly", tr("Monatlich")], ["once", tr("Einmalig")]];
const WEEKDAY_SHORT = [tr("Mo"), tr("Di"), tr("Mi"), tr("Do"), tr("Fr"), tr("Sa"), tr("So")];
const WEEKDAY_LONG = [tr("Montag"), tr("Dienstag"), tr("Mittwoch"), tr("Donnerstag"), tr("Freitag"), tr("Samstag"), tr("Sonntag")];
const NOTIFY_TEXT = { chat: tr("Nur im Chat"), ha: tr("Meldung in Home Assistant"), phone: tr("Aufs Handy") };

function setView(view) {
  state.view = view;
  document.documentElement.dataset.view = view;
  $("messages").hidden = view !== "chat";
  $("composer").hidden = view !== "chat";
  $("schedules").hidden = view !== "schedules";
  $("nav-schedules").classList.toggle("active", view === "schedules");
}

function stampText(ts) {
  const d = new Date(ts * 1000);
  const day = d.toDateString() === new Date().toDateString() ? tr("heute") : d.toLocaleDateString(kiLocale, { weekday: "short", day: "numeric", month: "numeric" });
  return tr("{0}, {1} Uhr", day, d.toLocaleTimeString(kiLocale, { hour: "2-digit", minute: "2-digit" }));
}

async function loadSchedules() {
  if (!state.me?.schedules) return;
  try { state.schedules = await api("api/schedules"); } catch (err) { if (state.view === "schedules") toast(errorText(err, tr("Die Aufgaben sind gerade nicht erreichbar."))); return; }
  if (state.view === "schedules") renderSchedules();
}

async function openSchedules() {
  setView("schedules");
  detachRun();
  releaseRecent();
  state.activeId = null;
  rememberActive();
  state.newProject = null;
  state.heldUnread = null;
  renderSide();
  closeMenu();
  setTitle(tr("Geplant"));
  renderSchedules();
  await loadSchedules();
  $("schedules").scrollTop = 0;
}

function scheduleStatus(task) {
  const lines = [];
  if (task.running) lines.push([tr("Läuft gerade …"), "run"]);
  else if (!task.enabled) lines.push([task.freq === "once" && task.runs > 0 ? tr("Abgeschlossen") : tr("Pausiert"), "off"]);
  else if (task.next_run) lines.push([tr("Nächster Lauf: {0}", stampText(task.next_run)), ""]);
  if (task.last_run) {
    const text = { ok: tr("Zuletzt gelaufen"), skipped: tr("Zuletzt übersprungen"), error: tr("Zuletzt fehlgeschlagen"), cancelled: tr("Zuletzt abgebrochen") }[task.last_status] || tr("Zuletzt");
    lines.push([`${text}: ${stampText(task.last_run)}`, task.last_status === "error" ? "bad" : ""]);
    if (task.last_note && task.last_status !== "ok") lines.push([task.last_note, task.last_status === "error" ? "bad" : ""]);
    else if (task.last_note) lines.push([task.last_note, "bad"]);
  }
  return lines;
}

function scheduleCard(task) {
  const card = node("article", "sched-card" + (task.enabled ? "" : " paused"));
  const head = node("div", "sched-head");
  const text = node("div", "sched-text");
  text.append(node("h3", "", task.name), node("p", "sched-when", task.summary));
  const toggle = node("button", "sched-switch");
  toggle.type = "button";
  toggle.setAttribute("role", "switch");
  toggle.setAttribute("aria-checked", String(task.enabled));
  toggle.setAttribute("aria-label", task.enabled ? tr("{0} pausieren", task.name) : tr("{0} fortsetzen", task.name));
  toggle.title = task.enabled ? tr("Pausieren") : tr("Fortsetzen");
  toggle.append(node("span", "knob"));
  toggle.addEventListener("click", () => toggleSchedule(task));
  head.append(text, toggle);
  card.append(head);
  card.append(node("p", "sched-prompt", task.prompt));
  const info = node("div", "sched-info");
  for (const [line, tone] of scheduleStatus(task)) info.append(node("p", "sched-line" + (tone ? ` ${tone}` : ""), line));
  card.append(info);
  const foot = node("div", "sched-foot");
  if (task.last_chat_id) {
    const open = node("button", "pill ghost", tr("Ergebnis ansehen"));
    open.type = "button";
    open.addEventListener("click", () => selectChat(task.last_chat_id));
    foot.append(open);
  }
  const run = node("button", "pill ghost");
  run.type = "button";
  run.append(icon("play"), node("span", "", tr("Jetzt ausführen")));
  run.disabled = task.running;
  run.addEventListener("click", () => runSchedule(task, run));
  foot.append(run);
  foot.append(actionButton(tr("Weitere Aktionen"), "more", "sched-more", (button) => scheduleMenu(task, button)));
  card.append(foot);
  return card;
}

function renderSchedules() {
  const wrap = $("sched-wrap");
  wrap.replaceChildren();
  const head = node("div", "sched-top");
  const heading = node("div", "");
  heading.append(node("h2", "", tr("Geplant")), node("p", "sched-intro", tr("Die KI erledigt Aufgaben zu festen Zeiten, auch wenn du nicht da bist. Das Ergebnis steht danach als neuer Chat in der Liste.")));
  const add = node("button", "pill primary");
  add.type = "button";
  add.append(icon("plus"), node("span", "", tr("Neue Aufgabe")));
  add.addEventListener("click", () => editSchedule(null));
  head.append(heading, add);
  wrap.append(head);
  if (!state.schedules.length) {
    const empty = node("div", "sched-empty");
    empty.append(
      node("p", "", tr("Noch keine geplanten Aufgaben.")),
      node("p", "mem-hint", tr("Zum Beispiel: jeden Morgen um 7 Uhr eine Zusammenfassung, was im Haus offen oder auffällig ist, oder jeden Freitag eine Übersicht der neuen Issues in einem Repository.")),
    );
    wrap.append(empty);
  } else {
    const list = node("div", "sched-list");
    for (const task of state.schedules) list.append(scheduleCard(task));
    wrap.append(list);
  }
  wrap.append(node("p", "sched-note", tr("Geplante Aufgaben dürfen lesen: Home Assistant (Zustände, Verlauf), GitHub, das Gedächtnis und das Web. Ändern oder schalten können sie nichts, und sie stellen keine Rückfragen. Sie verbrauchen wie jede Nachricht Kontingent deines Abos.")));
}

async function toggleSchedule(task) {
  try {
    await api(`api/schedules/${encodeURIComponent(task.id)}`, { method: "PATCH", body: JSON.stringify({ enabled: !task.enabled }) });
  } catch (err) { toast(errorText(err, tr("Das hat nicht geklappt."))); }
  await loadSchedules();
}

async function runSchedule(task, button) {
  button.disabled = true;
  try {
    const result = await api(`api/schedules/${encodeURIComponent(task.id)}/run`, { method: "POST" });
    await loadAll();
    await selectChat(result.chat_id);
  } catch (err) {
    toast(errorText(err, tr("Die Aufgabe konnte nicht gestartet werden.")));
    button.disabled = false;
    await loadSchedules();
  }
}

async function scheduleMenu(task, anchor) {
  const items = [
    { value: "edit", icon: "edit", label: tr("Bearbeiten"), key: "B" },
    { value: "toggle", icon: task.enabled ? "pause" : "play", label: task.enabled ? tr("Pausieren") : tr("Fortsetzen") },
    { divider: true },
    { value: "delete", icon: "trash", label: tr("Löschen"), danger: true, key: "D" },
  ];
  const choice = anchor && wideScreen()
    ? await openPopover(anchor, items)
    : await openSheet({ title: task.name, items: items.filter((e) => !e.divider) });
  if (choice === "edit") await editSchedule(task);
  else if (choice === "toggle") await toggleSchedule(task);
  else if (choice === "delete") {
    const ok = await openSheet({ title: tr("Aufgabe löschen?"), sub: tr("„{0}“ läuft danach nicht mehr. Die bisherigen Ergebnis-Chats bleiben erhalten.", task.name), ok: tr("Löschen"), danger: true });
    if (!ok) return;
    try { await api(`api/schedules/${encodeURIComponent(task.id)}`, { method: "DELETE" }); } catch (err) { toast(errorText(err, tr("Löschen hat nicht geklappt."))); }
    await loadSchedules();
  }
}

function field(label, input, hint = "", tag = "label") {
  const wrap = node(tag, "f-field");
  wrap.append(node("span", "f-label", label), input);
  if (hint) wrap.append(node("span", "f-hint", hint));
  return wrap;
}

function schedulePanel(task, hook) {
  return (body) => {
    const me = state.me;
    const form = node("form", "sched-form");
    form.autocomplete = "off";
    form.noValidate = true;
    const name = node("input", "field");
    name.maxLength = 60;
    name.value = task?.name || "";
    name.placeholder = tr("z. B. Morgenbericht");
    const prompt = node("textarea", "field area");
    prompt.rows = 5;
    prompt.maxLength = 4000;
    prompt.value = task?.prompt || "";
    prompt.placeholder = tr("z. B. Fasse zusammen, was gestern im Haus passiert ist, und nenne Auffälligkeiten (offene Fenster, Geräte, die lange an sind).");
    const freq = node("select", "field");
    for (const [value, label] of FREQS) freq.append(new Option(label, value));
    freq.value = task?.freq || "daily";
    const time = node("input", "field");
    time.type = "time";
    time.value = task?.at || "07:30";
    time.required = true;
    const days = new Set(task?.freq === "weekly" ? task.days.split(",").filter(Boolean).map(Number) : [0]);
    const chips = node("div", "f-chips");
    chips.setAttribute("role", "group");
    chips.setAttribute("aria-label", tr("Wochentage"));
    WEEKDAY_SHORT.forEach((short, index) => {
      const chip = node("button", "f-chip", short);
      chip.type = "button";
      chip.title = WEEKDAY_LONG[index];
      chip.setAttribute("aria-label", WEEKDAY_LONG[index]);
      chip.setAttribute("aria-pressed", String(days.has(index)));
      chip.addEventListener("click", () => {
        if (days.has(index)) days.delete(index); else days.add(index);
        chip.setAttribute("aria-pressed", String(days.has(index)));
      });
      chips.append(chip);
    });
    const monthDay = node("input", "field");
    monthDay.type = "number";
    monthDay.min = "1";
    monthDay.max = "31";
    monthDay.value = task?.freq === "monthly" ? task.days : "1";
    const date = node("input", "field");
    date.type = "date";
    const tomorrow = new Date(Date.now() + 86400000);
    date.min = new Date().toLocaleDateString("sv-SE");
    date.value = task?.freq === "once" ? task.days : tomorrow.toLocaleDateString("sv-SE");
    const weekRow = field(tr("Wochentage"), chips, "", "div");
    const monthRow = field(tr("Tag im Monat"), monthDay, tr("Der 31. gilt in kürzeren Monaten am letzten Tag."));
    const dateRow = field(tr("Datum"), date);
    const syncFreq = () => {
      weekRow.hidden = freq.value !== "weekly";
      monthRow.hidden = freq.value !== "monthly";
      dateRow.hidden = freq.value !== "once";
    };
    freq.addEventListener("change", syncFreq);
    syncFreq();

    const parts = [field(tr("Name"), name), field(tr("Was soll die KI tun?"), prompt, tr("Schreib es so, dass es ohne Rückfrage geht: Die KI kann während des Laufs nichts nachfragen.")),
      node("div", "f-row")];
    parts[2].append(field(tr("Wie oft"), freq), field(tr("Uhrzeit"), time));
    parts.push(weekRow, monthRow, dateRow);

    const model = node("select", "field");
    const models = me.models || [];
    if (models.length > 1) {
      models.forEach((m, i) => model.append(new Option(i === 0 ? tr("{0} (Standard)", m.label) : m.label, i === 0 ? "" : m.id)));
      model.value = validModel(task?.model) ? task.model : "";
      parts.push(field(tr("Modell"), model));
    }
    const web = node("input");
    web.type = "checkbox";
    web.checked = task ? task.web : true;
    if (me.web) {
      const row = node("label", "f-check");
      row.append(web, node("span", "", tr("Darf im Web recherchieren")));
      parts.push(row);
    }
    const notify = node("select", "field");
    notify.append(new Option(tr("Nur im Chat (mit Punkt für „ungelesen“)"), "chat"));
    if (me.notify_ha) notify.append(new Option(tr("Zusätzlich Meldung in Home Assistant"), "ha"));
    if (me.notify_phone) notify.append(new Option(tr("Zusätzlich aufs Handy"), "phone"));
    notify.value = [...notify.options].some((o) => o.value === task?.notify) ? task.notify : (me.notify_phone ? "phone" : "chat");
    parts.push(field(tr("Benachrichtigung"), notify));

    const error = node("p", "f-error");
    error.setAttribute("role", "alert");
    error.hidden = true;
    form.append(...parts, error);
    const fail = (text) => { error.textContent = text; error.hidden = false; return false; };
    hook.submit = async () => {
      error.hidden = true;
      if (!name.value.trim() || !prompt.value.trim()) return fail(tr("Bitte Name und Auftrag ausfüllen."));
      if (!time.value) return fail(tr("Bitte eine Uhrzeit angeben."));
      const payload = {
        name: name.value, prompt: prompt.value, freq: freq.value, at: time.value,
        days: freq.value === "weekly" ? [...days].sort().join(",") : freq.value === "monthly" ? monthDay.value : freq.value === "once" ? date.value : "",
        model: models.length > 1 ? model.value : "", web: me.web ? web.checked : true, notify: notify.value,
      };
      try {
        const path = task ? `api/schedules/${encodeURIComponent(task.id)}` : "api/schedules";
        await api(path, { method: task ? "PATCH" : "POST", body: JSON.stringify(payload) });
      } catch (err) {
        return fail(errorText(err, tr("Speichern hat nicht geklappt.")));
      }
      toast(task ? tr("Gespeichert.") : tr("Aufgabe angelegt."));
      loadSchedules().catch(() => {});
      return true;
    };
    form.addEventListener("submit", (event) => { event.preventDefault(); $("sheet-ok").click(); });
    body.replaceChildren(form);
  };
}

async function editSchedule(task) {
  const hook = { submit: async () => false };
  await openSheet({
    title: task ? tr("Aufgabe bearbeiten") : tr("Neue geplante Aufgabe"), ok: task ? tr("Speichern") : tr("Anlegen"),
    panel: schedulePanel(task, hook), onOk: () => hook.submit(),
  });
}

// ------------------------------------------------- Suche, Export, Meine Daten

// Datei vom Server holen (mit Schutz-Header) und speichern; der Dateiname kommt vom Server, sonst ``fallback``.
async function downloadFrom(path, fallback) {
  const response = await fetch(path, { credentials: "same-origin", headers: { "X-Requested-With": "ki-chat" } });
  if (response.status === 401) { window.location.assign("login"); throw new Error("HTTP 401"); }
  if (!response.ok) {
    const error = new Error(`HTTP ${response.status}`);
    try { error.detail = (await response.json()).detail; } catch { /* keine Meldung */ }
    throw error;
  }
  let name = fallback;
  const match = /filename\*=UTF-8''([^;]+)/i.exec(response.headers.get("content-disposition") || "");
  if (match) { try { name = decodeURIComponent(match[1]); } catch { /* Ersatzname */ } }
  const blob = await response.blob();
  return saveFile(name, blob, blob.type || "application/octet-stream");
}

async function exportChat(chat) {
  try {
    if (await downloadFrom(`api/chats/${encodeURIComponent(chat.id)}/export`, "Chat.md")) toast(tr("Chat als Markdown gespeichert."));
  } catch (err) {
    toast(errorText(err, tr("Der Export hat nicht geklappt.")));
  }
}

// Ausschnitt mit hervorgehobenen Fundstellen (nur Textknoten, kein HTML)
function highlighted(text, spans) {
  const out = node("span", "srch-snip");
  let at = 0;
  for (const [from, to] of spans) {
    if (from > at) out.append(document.createTextNode(text.slice(at, from)));
    out.append(node("mark", "", text.slice(from, to)));
    at = to;
  }
  if (at < text.length) out.append(document.createTextNode(text.slice(at)));
  return out;
}

const SEARCH_HINT = tr("Sucht in Titeln und Nachrichten aller deiner Chats.");

function searchPanel(body) {
  const input = node("input", "field srch-input");
  input.type = "search";
  input.maxLength = 100;
  input.placeholder = tr("Chats durchsuchen");
  input.setAttribute("aria-label", tr("Chats durchsuchen"));
  input.autocomplete = "off";
  input.enterKeyHint = "search";
  const status = node("p", "mem-hint srch-status", SEARCH_HINT);
  status.setAttribute("role", "status");
  const list = node("div", "srch-list");
  body.append(input, status, list);
  let timer = 0;
  let ticket = 0;
  const rows = () => [...list.querySelectorAll(".srch-item")];
  const open = (id) => { closeSheet(null); closeMenu(); selectChat(id).catch(() => {}); };
  const show = (query, hits) => {
    list.replaceChildren();
    status.textContent = hits.length ? "" : tr("Nichts gefunden für „{0}“.", query);
    for (const hit of hits) {
      const row = node("button", "srch-item");
      row.type = "button";
      const head = node("span", "srch-head");
      head.append(node("b", "srch-title", hit.title), node("small", "srch-date", dayText(hit.updated_at)));
      row.append(head);
      if (hit.snippet) row.append(highlighted(hit.snippet, hit.hl));
      row.addEventListener("click", () => open(hit.chat_id));
      list.append(row);
    }
  };
  // Liefert die Treffer; eine ältere, später eintreffende Antwort wird verworfen.
  const run = async () => {
    const query = input.value.trim().replace(/\s+/g, " ");
    const mine = ++ticket;
    if (query.length < 2) {
      list.replaceChildren();
      status.textContent = query ? tr("Mindestens zwei Zeichen eingeben.") : SEARCH_HINT;
      return [];
    }
    try {
      const hits = await api(`api/search?q=${encodeURIComponent(query)}`);
      if (mine === ticket) show(query, hits);
      return mine === ticket ? hits : [];
    } catch {
      if (mine === ticket) { list.replaceChildren(); status.textContent = tr("Die Suche ist gerade nicht erreichbar."); }
      return [];
    }
  };
  input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, 220); });
  input.addEventListener("keydown", async (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      clearTimeout(timer);
      const hits = await run();
      if (hits.length) open(hits[0].chat_id);
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      rows()[0]?.focus();
    }
  });
  list.addEventListener("keydown", (event) => {
    const all = rows();
    const at = all.indexOf(document.activeElement);
    if (event.key === "ArrowDown") { event.preventDefault(); all[Math.min(at + 1, all.length - 1)]?.focus(); }
    else if (event.key === "ArrowUp") { event.preventDefault(); if (at <= 0) input.focus(); else all[at - 1].focus(); }
  });
}

async function openSearch() {
  if (!state.me) return;
  closePopover(null);
  await openSheet({ title: tr("Suchen"), ok: tr("Schließen"), panel: searchPanel });
}

const DELETE_WORD = tr("LÖSCHEN");

async function exportEverything(button) {
  button.disabled = true;
  try {
    if (await downloadFrom("api/export", "Export.zip")) toast(tr("Export gespeichert."));
  } catch (err) {
    toast(err.status === 429 ? errorText(err, tr("Bitte später noch einmal versuchen.")) : errorText(err, tr("Der Export hat nicht geklappt.")));
  } finally {
    button.disabled = false;
  }
}

// Zweite Sicherung vor dem Löschen: das Wort muss eingetippt werden.
function deleteAllPanel(count, refs) {
  return (body) => {
    const input = node("input", "field");
    input.autocomplete = "off";
    input.setAttribute("aria-label", tr("Zur Bestätigung {0} eingeben", DELETE_WORD));
    input.placeholder = DELETE_WORD;
    const error = node("p", "f-error");
    error.setAttribute("role", "alert");
    error.hidden = true;
    body.append(node("p", "mem-hint", tr("Alle {0} Chats werden gelöscht, auch die erzeugten Dateien. Das lässt sich nicht rückgängig machen. Zur Bestätigung tippe {1}.", count, DELETE_WORD)), input, error);
    input.addEventListener("input", () => { error.hidden = true; });
    refs.input = input;
    refs.error = error;
  };
}

async function deleteAllChats() {
  const count = state.chats.length;
  if (!count) { toast(tr("Es gibt keine Chats zu löschen.")); return; }
  const go = await openSheet({
    title: tr("Alle Chats löschen?"),
    sub: tr("Es werden {0} Chats mit allen Nachrichten gelöscht. Projekte, Gedächtnis und geplante Aufgaben bleiben erhalten. Exportiere die Chats vorher, wenn du sie behalten möchtest.", count),
    ok: tr("Weiter"),
    danger: true,
  });
  if (!go) return;
  const refs = {};
  await openSheet({
    title: tr("Zur Bestätigung eintippen"),
    ok: tr("Alle Chats löschen"),
    danger: true,
    panel: deleteAllPanel(count, refs),
    onOk: async () => {
      const { input, error } = refs;
      if (input.value.trim().toLocaleUpperCase(kiLocale) !== DELETE_WORD) {
        error.textContent = tr("Bitte {0} eintippen.", DELETE_WORD);
        error.hidden = false;
        input.focus();
        return false;
      }
      try {
        const result = await api("api/data/delete-chats", { method: "POST", body: JSON.stringify({ confirm: input.value.trim() }) });
        toast(tr("{0} Chats gelöscht.", result.deleted));
      } catch (err) {
        error.textContent = errorText(err, tr("Das Löschen hat nicht geklappt."));
        error.hidden = false;
        return false;
      }
      return true;
    },
  }).then(async (done) => {
    if (!done) return;
    state.activeId = null;
    await loadAll();
    startNew();
  });
}

function dataPanel(body) {
  const exportBox = node("div", "data-block");
  exportBox.append(node("b", "", tr("Alle Chats exportieren")));
  exportBox.append(node("p", "mem-hint", tr("ZIP-Datei mit allen Chats als Markdown, deinen Projekten samt Anweisungen, deinem persönlichen Gedächtnis und deinen geplanten Aufgaben. Hochgeladene Projektdateien und erzeugte Dateien sind nicht enthalten.")));
  const download = node("button", "pill primary");
  download.type = "button";
  download.append(icon("download"), node("span", "", tr("ZIP herunterladen")));
  download.addEventListener("click", () => { exportEverything(download).catch(() => {}); });
  exportBox.append(download);
  const deleteBox = node("div", "data-block");
  deleteBox.append(node("b", "", tr("Alle Chats löschen")));
  deleteBox.append(node("p", "mem-hint", tr("Entfernt alle deine Chats unwiderruflich. Projekte, Gedächtnis und geplante Aufgaben bleiben.")));
  const remove = node("button", "pill ghost data-danger");
  remove.type = "button";
  remove.append(icon("trash"), node("span", "", tr("Alle Chats löschen …")));
  remove.addEventListener("click", () => { deleteAllChats().catch(() => {}); });
  deleteBox.append(remove);
  body.append(exportBox, deleteBox);
}

async function openMyData() {
  await openSheet({ title: tr("Meine Daten"), sub: tr("Nimm deine Daten mit oder räume auf. Es betrifft nur dein Profil."), ok: tr("Fertig"), panel: dataPanel });
}

// ------------------------------------------------- Einrichtungsprüfung

const SETUP_STATUS = {
  ok: ["check", tr("Erledigt")],
  todo: ["close", tr("Fehlt")],
  warn: ["bolt", tr("Prüfen")],
  off: ["", tr("Nicht eingerichtet")],
  unknown: ["", tr("Nicht prüfbar")],
};
const SETUP_GROUPS = [["required", tr("Nötig")], ["recommended", tr("Empfohlen")], ["optional", tr("Optional")]];

// Text mit `Code` zwischen Gravis-Zeichen als DOM-Knoten (nie als HTML)
function richText(parent, text) {
  String(text).split("`").forEach((part, index) => {
    if (part) parent.append(index % 2 ? node("code", "", part) : document.createTextNode(part));
  });
  return parent;
}

function setupItem(item) {
  const box = document.createElement("details");
  box.className = `setup-item ${item.status}`;
  const head = document.createElement("summary");
  const [iconName, statusText] = SETUP_STATUS[item.status] || SETUP_STATUS.unknown;
  const mark = node("span", "setup-mark");
  if (iconName) mark.append(icon(iconName));
  head.append(mark, node("span", "setup-title", item.title), node("span", "setup-state", statusText));
  box.append(head);
  const body = node("div", "setup-body");
  if (item.detail) body.append(richText(node("p", "setup-detail"), item.detail));
  if (item.steps?.length) {
    const steps = node("ol", "setup-steps");
    for (const step of item.steps) steps.append(richText(node("li"), step));
    body.append(steps);
  }
  box.append(body);
  return box;
}

function setupPanel(body) {
  const status = node("p", "mem-hint setup-status", tr("Prüfe die Einrichtung …"));
  const list = node("div", "setup-list");
  const again = node("button", "pill", tr("Erneut prüfen"));
  again.type = "button";
  body.append(status, list, again);
  const run = async () => {
    again.disabled = true;
    status.textContent = tr("Prüfe die Einrichtung …");
    list.replaceChildren();
    try {
      const data = await api("api/setup");
      for (const [level, heading] of SETUP_GROUPS) {
        const items = data.items.filter((item) => item.level === level);
        if (!items.length) continue;
        const group = node("section", "setup-group");
        group.append(node("h3", "", heading));
        for (const item of items) group.append(setupItem(item));
        list.append(group);
      }
      list.querySelector(".setup-item.todo, .setup-item.warn")?.setAttribute("open", "");  // nur der erste offene Punkt ist aufgeklappt
      status.textContent = data.open
        ? trn(data.open, "1 Punkt braucht Aufmerksamkeit.", "{0} Punkte brauchen Aufmerksamkeit.")
        : tr("Alles Nötige ist eingerichtet.");
    } catch {
      status.textContent = tr("Die Prüfung ist gerade nicht möglich. Versuche es gleich noch einmal.");
    } finally {
      again.disabled = false;
    }
  };
  again.addEventListener("click", () => { run(); });
  run();
}

async function openSetup() {
  await openSheet({
    title: tr("Einrichtungsprüfung"),
    sub: tr("Was eingerichtet ist und was noch fehlt, mit den genauen Schritten. Geändert wird in der Add-on-Konfiguration."),
    ok: tr("Fertig"),
    panel: setupPanel,
  });
}

// ------------------------------------------------- Konto-Menü (unten in der Seitenleiste)

const THEMES = [["auto", tr("Auto")], ["light", tr("Hell")], ["dark", tr("Dunkel")]];

// Einträge hängen von Rechten und Einbettung ab: Gedächtnis (wenn aktiv), Darstellung (nicht in HA, dort gibt HA das Theme vor), Abmelden (nur über die Domain).
function accountEntries() {
  const entries = [];
  if (state.me?.memory) entries.push({ value: "memory", icon: "memory", label: tr("Gedächtnis") });
  entries.push({ value: "data", icon: "data", label: tr("Meine Daten") });
  if (state.me?.setup) entries.push({ value: "setup", icon: "setup", label: tr("Einrichtungsprüfung") });
  if (document.documentElement.dataset.themeSource !== "ha") {
    const current = window.kiTheme.get();
    entries.push({
      value: "theme",
      icon: "sun",
      label: tr("Darstellung"),
      submenu: THEMES.map(([value, label]) => ({ value: `theme:${value}`, label, active: value === current })),
    });
  }
  if (state.me?.can_logout) {
    if (entries.length) entries.push({ divider: true });
    entries.push({ value: "logout", icon: "logout", label: tr("Abmelden") });
  }
  return entries;
}

async function logout() {
  try { await api("auth/logout", { method: "POST" }); } catch { /* Sitzung ist dann ohnehin weg */ }
  window.location.assign("login");
}

async function accountMenu() {
  const entries = accountEntries();
  if (!entries.length) return;
  const button = $("account");
  button.setAttribute("aria-expanded", "true");
  let choice;
  try {
    choice = wideScreen()
      ? await openPopover(button, entries)
      : await openSheet({ title: state.me?.label || tr("Konto"), items: entries.filter((e) => !e.divider) });
    if (choice === "theme") {
      const current = window.kiTheme.get();
      choice = await openSheet({
        title: tr("Darstellung"),
        items: THEMES.map(([value, label]) => ({ value: `theme:${value}`, label, active: value === current })),
      });
    }
  } finally {
    button.setAttribute("aria-expanded", "false");
  }
  if (choice === "memory") { closeMenu(); openMemory(); }
  else if (choice === "data") { closeMenu(); openMyData().catch(() => {}); }
  else if (choice === "setup") { closeMenu(); openSetup().catch(() => {}); }
  else if (choice === "logout") await logout();
  else if (typeof choice === "string" && choice.startsWith("theme:")) window.kiTheme.set(choice.slice(6));
}

async function init() {
  initSheet();
  setStreaming(false);

  loadUi();
  $("menu").addEventListener("click", openMenu);
  $("menu-composer").addEventListener("click", openMenu);
  $("drawer-scrim").addEventListener("click", closeMenu);
  $("new-chat").addEventListener("click", () => startNew());
  $("nav-schedules").addEventListener("click", () => { openSchedules().catch(() => {}); });
  $("nav-search").addEventListener("click", () => { openSearch().catch(() => {}); });
  initShortcuts();
  $("account").addEventListener("click", () => { accountMenu().catch(() => {}); });
  $("new-chat-top").addEventListener("click", () => startNew());
  initSideToggle();
  initAttachments();
  $("composer").addEventListener("submit", (event) => {
    event.preventDefault();
    sendMessage().catch(() => {});
  });
  $("input").addEventListener("input", autosize);
  $("input").addEventListener("keydown", (event) => {
    const touch = window.matchMedia("(pointer: coarse)").matches;
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing && !touch) {
      event.preventDefault();
      sendMessage().catch(() => {});
    }
  });

  try {
    state.me = await api("api/me");
    $("who").textContent = state.me.label;
    $("avatar").textContent = state.me.label.charAt(0).toUpperCase();
    let stored = null;
    try { stored = localStorage.getItem("ki-effort"); } catch { /* optional */ }
    state.effort = ["low", "medium", "high"].includes(stored) ? stored : state.me.default_effort;
    markTools();
    $("test-badge").hidden = !state.me.test_mode;
    let webStored = null;
    try { webStored = localStorage.getItem("ki-web"); } catch { /* optional */ }
    state.web = webStored !== "off";
    useChatModel(null);
    $("nav-schedules").hidden = !state.me.schedules;
    $("tools").addEventListener("click", () => { toolsMenu().catch(() => {}); });
    syncTopbar();
    renderNotices(state.me.setup_open
      ? [{ id: "setup", level: "warn", text: state.me.setup_open, action: { label: tr("Schritte anzeigen"), run: () => { openSetup().catch(() => {}); } } }, ...state.me.notices]
      : state.me.notices);
    renderNotices(limitNotices(state.me.limits), $("limit-notices"));
    if (state.me.overview) pollOverview().catch(() => {});
    $("side-foot").classList.toggle("has-menu", accountEntries().length > 0);
    if (state.me.app_name) document.title = state.me.app_name;
    setTitle(idleTitle());
    showHello();
    await loadAll();
    document.addEventListener("visibilitychange", refreshWhenSeen);
    window.addEventListener("focus", refreshWhenSeen);
    setInterval(refreshWhenSeen, 45000);
    setInterval(pollRunning, 3000);
    const again = rememberedActive();
    if (again && state.chats.some((c) => c.id === again)) await selectChat(again);
  } catch {
    $("who").textContent = tr("Nicht angemeldet");
  }
}

init();
