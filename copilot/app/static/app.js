"use strict";

// Alle Pfade sind relativ, damit die Seite unter dem Ingress-Pfad von Home Assistant funktioniert.
const $ = (id) => document.getElementById(id);
const state = { research: false, incognito: false, incognitoId: null, view: "chat", schedules: [], files: [], quote: "", recent: [], chats: [], projects: [], activeId: null, newProject: null, streaming: null, me: null, effort: "medium", heldUnread: null, shownAt: null, model: "", web: true };
const ui = { projectsOpen: true, openProjects: new Set(), showAll: false };

// ---------------------------------------------------------------- Hilfen

const SVG_NS = "http://www.w3.org/2000/svg";
const ICONS = {
  sliders: ["M4 7h9M17 7h3M4 17h3M11 17h9", "M15 5v4M9 15v4"],
  lock: ["M7 11V8a5 5 0 0 1 10 0v3", "M6 11h12v9H6z"],
  gauge: ["M4.5 17.5a8.5 8.5 0 1 1 15 0", "M12 13.5l3.2-4.2", "M12 13.5h.01"],
  github: ["M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12"],
  share: ["M18 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6z", "M6 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z", "M18 22a3 3 0 1 0 0-6 3 3 0 0 0 0 6z", "M8.6 13.5l6.8 4M15.4 6.5l-6.8 4"],
  link: ["M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1", "M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"],
  download: ["M12 4v11M7 11l5 5 5-5M5 20h14"],
  attach: ["M20.5 11.5l-8.2 8.2a5 5 0 0 1-7.1-7.1l8.5-8.5a3.3 3.3 0 0 1 4.7 4.7l-8.5 8.5a1.7 1.7 0 0 1-2.4-2.4l7.8-7.8"],
  note: ["M6 4h12v16H6z", "M9 9h6M9 13h6M9 17h3"],
  file: ["M7 3h7l5 5v13H7z", "M14 3v5h5"],
  picture: ["M4 5h16v14H4z", "M4 16l5-5 4 4 3-3 4 4", "M9 9.5h.01"],
  edit: ["M16.5 4.5l3 3L8 19l-4 1 1-4z"],
  refresh: ["M19.5 12a7.5 7.5 0 1 1-2.2-5.3", "M19.5 4.5v4.5H15"],
  arrowDown: ["M12 5v14M6 13l6 6 6-6"],
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
  mic: ["M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3z", "M6 11a6 6 0 0 0 12 0M12 17v4"],
  wave: ["M4 12v0M8 8v8M12 4v16M16 8v8M20 12v0"],
  reply: ["M9 14L4 9l5-5", "M4 9h9a6 6 0 0 1 6 6v4"],
  quote: ["M5 5v6a3 3 0 0 0 3 3h11", "M15 10l4 4-4 4"],
  info: ["M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17z", "M12 11v5.5", "M12 7.8h.01"],
  bolt: ["M13 3L5 13.5h6L10 21l8-10.5h-6z"],
  bell: ["M6 16.5V11a6 6 0 1 1 12 0v5.5l1.5 2h-15z", "M10 20.5h4"],
  bug: ["M9 7a3 3 0 0 1 6 0M8 9h8v5a4 4 0 0 1-8 0zM4 10l4 1.5M20 10l-4 1.5M4 18l4-2M20 18l-4-2M12 9v10"],
  code: ["M8 8l-4 4 4 4M16 8l4 4-4 4M13.5 5l-3 14"],
  pen: ["M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"],
  eye: ["M2.5 12C3.5 10.5 7 6 12 6s8.5 4.5 9.5 6c-1 1.5-4.5 6-9.5 6s-8.5-4.5-9.5-6z", "M12 9.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5z"],
  eyeOff: ["M3 3l18 18", "M10.6 6.1A9.6 9.6 0 0 1 12 6c5 0 8.5 4.5 9.5 6a14 14 0 0 1-3.2 3.6M6.5 7.6A14 14 0 0 0 2.5 12c1 1.5 4.5 6 9.5 6 1.5 0 2.8-.4 4-1", "M9.9 10a3 3 0 0 0 4.1 4.1"],
  stack: ["M7 5h10M5 9h14M4 13h16l-1.5 6h-13z"],
  skill: ["M6 4h11a2 2 0 0 1 2 2v13H8a2 2 0 0 1-2-2z", "M6 17a2 2 0 0 1 2-2h11", "M10 8h5"],
  memory: ["M12 3a5 5 0 0 0-5 5c0 2 1 3 2 4v2h6v-2c1-1 2-2 2-4a5 5 0 0 0-5-5z", "M10 18h4M10.5 21h3"],
  ghost: ["M5 21V11a7 7 0 0 1 14 0v10l-2.33-2-2.34 2-2.33-2-2.33 2-2.34-2z", "M9.5 11h.01M14.5 11h.01"],
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
  megaphone: ["M4 10v4h3l7 4V6L7 10z", "M17.5 9.5a4 4 0 0 1 0 5"],
  chart: ["M5 20V11M12 20V4M19 20v-6"],
  cube: ["M12 3l8 4.5v9L12 21l-8-4.5v-9z", "M4 7.5l8 4.5 8-4.5M12 12v9"],
  headset: ["M5 14v-2a7 7 0 0 1 14 0v2", "M5 14h2.5v5H5zM16.5 14H19v5h-2.5z", "M17.5 19c0 1.5-2 2-4 2"],
  users: ["M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6z", "M3.5 19a5.5 5.5 0 0 1 11 0", "M16 6.3a3 3 0 0 1 0 5.4M17.5 14a5 5 0 0 1 3 5"],
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

// Suche und Kacheln, gemeinsam für Skills, Konnektoren und Pakete
const foldText = (text) => String(text || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");

// Alle Wörter der Suche müssen vorkommen (ohne Groß-/Kleinschreibung und Akzente)
function wordsMatch(query, haystack) {
  const words = foldText(query).split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const text = foldText(haystack);
  return words.every((w) => text.includes(w));
}

function searchInput(label, value) {
  const input = node("input", "field");
  input.type = "search";
  input.maxLength = 80;
  input.placeholder = label;
  input.setAttribute("aria-label", label);
  input.autocomplete = "off";
  input.spellcheck = false;
  input.value = value || "";
  return input;
}

// Kachel mit Symbol; ohne Symbol die Anfangsbuchstaben (zum Beispiel für Dienste ohne Logo)
function tile(iconName, label) {
  const box = node("span", "tile");
  box.setAttribute("aria-hidden", "true");
  if (iconName && ICONS[iconName]) box.append(icon(iconName));
  else box.textContent = initials(label);
  return box;
}

// Rundes Profilbild aus Home Assistant; ohne Bild (oder bei einem Fehler) bleibt der Anfangsbuchstabe
function fillAvatar(box, label) {
  const letter = (label || "?").charAt(0).toUpperCase();
  box.textContent = letter;
  if (!state.me || !state.me.picture) return;
  const img = document.createElement("img");
  img.alt = "";
  img.className = "avatar-img";
  img.addEventListener("load", () => { box.classList.add("has-img"); box.replaceChildren(img); });
  img.addEventListener("error", () => { box.classList.remove("has-img"); box.textContent = letter; });
  img.src = "api/me/picture";
}

function initials(label) {
  const words = String(label || "").split(/[\s\-_.]+/).filter(Boolean);
  const letters = words.length > 1 ? words[0][0] + words[1][0] : (words[0] || "?").slice(0, 2);
  return letters.toUpperCase();
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
  toastTimer = setTimeout(() => { el.hidden = true; }, Math.max(4000, Math.min(9000, text.length * 60)));
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
function openSheet({ title, sub = "", label = "", value = null, placeholder = "", ok = tr("OK"), danger = false, items = null, multiline = false, panel = null, onOk = null, plain = false, wide = false, maxLength = 120 }) {
  return new Promise((resolve) => {
    if (sheetDone) closeSheet(null);
    sheetDone = resolve;
    sheetOnOk = onOk;
    $("sheet-title").textContent = title;
    $("sheet-sub").textContent = sub;
    $("sheet").dataset.plain = plain ? "1" : "";
    $("sheet").dataset.wide = wide ? "1" : "";
    $("sheet").dataset.kind = panel ? "panel" : items ? "list" : multiline ? "multiline" : value !== null ? "input" : "confirm";
    const field = $("sheet-label");
    field.textContent = label;
    field.hidden = !label || !!items || !!panel || (value === null && !multiline);
    field.htmlFor = multiline ? "sheet-text" : "sheet-input";
    const input = multiline ? $("sheet-text") : $("sheet-input");
    $("sheet-input").hidden = multiline || value === null || !!panel;
    $("sheet-text").hidden = !multiline || !!panel;
    if (!multiline) input.maxLength = maxLength;
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
    else if (settingsUi.modal) closeSettingsModal();
    else if (fullscreen) fullscreen.classList.remove("full");
    else closeMenu();
  });
}


// ------------------------------------------------- Popover-Menü (Computer, Tablet)

// Am Computer und Tablet öffnen die Aktionen als kleines Menü direkt am Auslöser, auf dem Handy bleibt es ein Fenster von unten.
const narrowScreen = () => window.matchMedia("(max-width: 760px)").matches;
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
  syncIncognito();
  syncCrumbs();
  $("topbar").classList.toggle("empty", !$("chat-title").textContent && $("test-badge").hidden && $("incognito-top").hidden);
}

// ---------------------------------------------------------------- Pfad in der Kopfzeile
// Wie in Claude: „Projekt / Chatname ▾“. Ein Klick auf den Namen benennt um, der Pfeil öffnet die Aktionen des Chats, rechts steht „Teilen“.

function currentChat() {
  return state.view === "chat" && state.activeId ? state.chats.find((c) => c.id === state.activeId) || null : null;
}

function syncCrumbs() {
  const chat = currentChat();
  const project = chat?.project_id ? state.projects.find((p) => p.id === chat.project_id) : null;
  const crumb = $("crumb-project");
  crumb.hidden = $("crumb-sep").hidden = !project;
  if (project) { crumb.textContent = project.name; crumb.title = tr("Projekt „{0}“ in der Seitenleiste zeigen", project.name); }
  $("crumb-menu").hidden = !chat;
  const title = $("chat-title");
  const editing = !!title.querySelector("input");
  title.classList.toggle("renamable", !!chat);
  if (chat && !editing) { title.tabIndex = 0; title.setAttribute("role", "button"); title.title = tr("Umbenennen"); }
  else if (!editing) { title.removeAttribute("tabindex"); title.removeAttribute("role"); title.removeAttribute("title"); }
  const share = $("share-top");
  share.hidden = !(chat && canShare() && !chat.kind);
  share.classList.toggle("on", !!chat?.shared?.length);
}

function renameInline(chat) {
  const title = $("chat-title");
  if (title.querySelector("input")) return;
  const input = node("input", "title-edit");
  const box = title.getBoundingClientRect();  // das Feld hat genau die Größe des Namens, nichts springt
  input.style.width = `${Math.ceil(Math.max(box.width, 160))}px`;
  input.style.height = `${Math.ceil(box.height)}px`;
  title.classList.add("editing");
  input.type = "text";
  input.maxLength = 120;
  input.value = chat.title;
  input.setAttribute("aria-label", tr("Name"));
  title.textContent = "";
  title.removeAttribute("role");
  title.removeAttribute("tabindex");
  title.append(input);
  input.focus();
  input.select();
  let done = false;
  const finish = async (save) => {
    if (done) return;
    done = true;
    const value = input.value.trim().slice(0, 120);
    title.classList.remove("editing");
    title.textContent = chat.title;
    syncCrumbs();
    if (!save || !value || value === chat.title) return;
    try {
      await patchChat(chat, { title: value });
      await loadAll();
      if (state.activeId === chat.id) setTitle(value);
    } catch {
      toast(tr("Umbenennen hat nicht geklappt."));
    }
  };
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); finish(true); }
    else if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); finish(false); }
  });
  input.addEventListener("blur", () => finish(true));
}

function initCrumbs() {
  $("chat-title").addEventListener("click", () => { const chat = currentChat(); if (chat) renameInline(chat); });
  $("chat-title").addEventListener("keydown", (event) => {
    if ((event.key === "Enter" || event.key === " ") && event.target === $("chat-title")) { event.preventDefault(); const chat = currentChat(); if (chat) renameInline(chat); }
  });
  $("crumb-menu").addEventListener("click", async () => {
    const chat = currentChat();
    if (!chat) return;
    const button = $("crumb-menu");
    button.setAttribute("aria-expanded", "true");
    try { await chatMenu(chat, button); } finally { button.setAttribute("aria-expanded", "false"); }
  });
  $("crumb-project").addEventListener("click", () => {
    const chat = currentChat();
    if (!chat?.project_id) return;
    ui.projectsOpen = true;
    ui.openProjects.add(chat.project_id);
    saveUi();
    renderSide();
    if (narrowScreen()) openMenu();
  });
  $("share-top").addEventListener("click", () => { const chat = currentChat(); if (chat) shareChat(chat).catch(() => {}); });
}

// ---------------------------------------------------------------- Inkognito-Chat
// Das Gespenster-Symbol oben rechts gibt es auf dem Startbild eines neuen Chats und in einem Inkognito-Chat. Der Chat entsteht erst
// mit der ersten Nachricht auf dem Server (Art „incognito“) und wird gelöscht, sobald man ihn verlässt, die Seite schließt oder neu lädt.

function syncIncognito() {
  const button = $("incognito-top");
  const here = state.view === "chat" && !!state.me?.incognito && (state.activeId === null || state.activeId === state.incognitoId);
  button.hidden = !here;
  button.setAttribute("aria-pressed", state.incognito ? "true" : "false");
  document.documentElement.classList.toggle("incognito", here && state.incognito);
  $("input").placeholder = composerPlaceholder();
}

function composerPlaceholder() {
  if (state.files.length) return tr("Frage zu den Dateien stellen");
  return document.documentElement.classList.contains("incognito") ? tr("Inkognito-Nachricht schreiben") : tr("Nachricht schreiben");
}

function endIncognito() {
  const id = state.incognitoId;
  state.incognitoId = null;
  state.incognito = false;
  if (id) api(`api/chats/${encodeURIComponent(id)}`, { method: "DELETE" }).catch(() => {});
  syncIncognito();
}

async function toggleIncognito() {
  if (state.activeId === null) {  // Startbild: Modus an oder aus
    state.incognito = !state.incognito;
    if (state.incognito) state.newProject = null;  // Inkognito gehört in kein Projekt
    setTitle(state.incognito ? tr("Inkognito-Chat") : idleTitle());
    showHello();
    focusInput();
    return;
  }
  if (state.activeId !== state.incognitoId) return;
  const ok = await openSheet({
    title: tr("Inkognito-Chat beenden?"),
    sub: tr("Der Chat und alles, was darin entstanden ist, wird gelöscht. Das lässt sich nicht rückgängig machen."),
    ok: tr("Beenden und löschen"),
    danger: true,
  });
  if (ok) startNew();
}

// Schließt man die Seite oder lädt sie neu, geht die Löschung noch hinaus; was dabei liegen bleibt (Handy beendet den Tab), räumt der Server nach drei Stunden auf.
window.addEventListener("pagehide", () => {
  if (!state.incognitoId) return;
  try {
    fetch(`api/chats/${encodeURIComponent(state.incognitoId)}`, { method: "DELETE", keepalive: true, credentials: "same-origin", headers: { "X-Requested-With": "ki-chat" } });
  } catch { /* der Server räumt auf */ }
});

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
  if (chat.shared?.length) {
    const mark = icon("share");
    mark.classList.add("share-mark");
    mark.setAttribute("role", "img");
    mark.setAttribute("aria-label", tr("Geteilt"));
    item.append(mark);
  }
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
  hoverTip(item, () => ({ title: chat.title, sub: chat.updated_at ? tr("Letzte Aktivität: {0}", ago(Date.parse(chat.updated_at) / 1000)) : "" }));
  return item;
}

// Hover-Hinweis wie in Claude: bleibt die Maus etwa eine Sekunde auf einem Eintrag, erscheint rechts daneben der volle Name
// mit dem Zeitpunkt der letzten Aktivität. Nur mit Maus (nicht am Touchscreen); jeder Klick, Scroll oder Menü schließt ihn.
const TIP_DELAY = 800;
let tipEl = null;
let tipTimer = 0;

function hideTip() {
  clearTimeout(tipTimer);
  tipTimer = 0;
  tipEl?.remove();
  tipEl = null;
}

function hoverTip(item, describe) {
  if (!window.matchMedia("(hover: hover)").matches) return;
  item.addEventListener("mouseenter", () => {
    hideTip();
    tipTimer = setTimeout(() => {
      if (pop || sheetDone || !item.isConnected) return;
      const { title, sub } = describe();
      tipEl = node("div", "hover-tip");
      tipEl.setAttribute("role", "tooltip");
      tipEl.append(node("div", "tip-title", title));
      if (sub) tipEl.append(node("div", "tip-sub", sub));
      document.body.append(tipEl);
      const rect = item.getBoundingClientRect();
      const box = tipEl.getBoundingClientRect();
      const x = Math.min(rect.right + 8, window.innerWidth - box.width - 8);
      const y = Math.max(8, Math.min(rect.top + (rect.height - box.height) / 2, window.innerHeight - box.height - 8));
      tipEl.style.left = `${Math.max(8, x)}px`;
      tipEl.style.top = `${y}px`;
    }, TIP_DELAY);
  });
  item.addEventListener("mouseleave", hideTip);
  item.addEventListener("click", hideTip);
}
document.addEventListener("scroll", hideTip, true);
document.addEventListener("keydown", hideTip, true);

// Ordner-Symbol der Projekte: geschlossen und geöffnet liegen übereinander, CSS blendet beim Öffnen weich über.
function folderIcon() {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("class", "icon folder");
  const shapes = [
    ["f-closed", "M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2.2h7.5A2.5 2.5 0 0 1 21 9.7v7.8a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5z"],
    ["f-open", "M3 17.5V7.5A2.5 2.5 0 0 1 5.5 5H9l2 2.2h6.5A2.5 2.5 0 0 1 20 9.7V10.5"],
    ["f-open", "M3 17.7l2-6.6a1.6 1.6 0 0 1 1.5-1.1H21a1 1 0 0 1 1 1.3l-1.9 6.7a1.6 1.6 0 0 1-1.5 1.2H5a2 2 0 0 1-2-1.5z"],
  ];
  for (const [cls, d] of shapes) {
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", d);
    path.setAttribute("class", cls);
    svg.append(path);
  }
  return svg;
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
    // markiert nur, solange in diesem Projekt kein Chat ausgewählt ist (neuer Chat im Projekt); sonst ist es der Chat
    const current = state.view === "chat" && !state.activeId && state.newProject === project.id;
    const row = node("div", "row project-row" + (open ? " open" : "") + (current ? " current" : ""));
    const label = node("span", "name", project.name);
    if (project.instructions) { const dot = node("i", "dot"); dot.title = tr("Projektanweisungen aktiv"); label.append(dot); }
    if (project.knowledge) { const dot = node("i", "dot know"); dot.title = tr("{0} Wissensdateien", project.knowledge); label.append(dot); }
    row.append(folderIcon(), label);
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
  syncCrumbs();
  syncSharedNav();
}

// „Geteilt“ steht in der Seitenleiste immer, solange das Teilen erlaubt ist (leer zeigt die Seite einen Hinweis).
function syncSharedNav() {
  const button = $("nav-shared");
  if (button) button.hidden = !canShare();
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
  if (state.incognitoId && state.activeId !== state.incognitoId) endIncognito();  // den Inkognito-Chat verlassen: er wird gelöscht
  try {
    if (state.activeId && state.activeId !== state.incognitoId) sessionStorage.setItem("ki-active", state.activeId);
    else sessionStorage.removeItem("ki-active");
  } catch { /* optional */ }
  syncPresence();
}

// Anwesenheit: Der Server erfährt, welchen Chat dieses Gerät gerade zeigt (sichtbarer Tab). Nur so kann er Meldungen
// aufs Handy auf ungelesene Antworten beschränken: Ist der Chat auf irgendeinem Gerät offen, bleibt es still.
const presence = { client: "", sent: undefined, at: 0 };

function presenceClient() {
  if (presence.client) return presence.client;
  let id = "";
  try { id = sessionStorage.getItem("ki-client") || ""; } catch { /* optional */ }
  if (!id) {
    id = ((window.crypto?.randomUUID?.() || `${Math.random()}${Date.now()}`)).replace(/[^A-Za-z0-9_-]/g, "").slice(0, 36);
    try { sessionStorage.setItem("ki-client", id); } catch { /* optional */ }
  }
  presence.client = id;
  return id;
}

function syncPresence() {
  if (!state.me) return;
  const target = state.view === "chat" && !document.hidden && state.activeId ? state.activeId : null;
  const stale = Date.now() - presence.at > 20000;
  if (target === presence.sent && !(target && stale)) return;
  presence.sent = target;
  presence.at = Date.now();
  api("api/presence", { method: "POST", body: JSON.stringify({ client: presenceClient(), chat_id: target }), keepalive: true }).catch(() => {});
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
  const share = canShare() && !chat.kind ? [{ value: "share", icon: "share", label: tr("Teilen …") }] : [];
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
      ...share,
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
        ...share,
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
  else if (choice === "share") await shareChat(chat);
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

function memoryEntry(entry, scope, canDelete, refresh, url = "") {
  const row = node("div", "mem-entry");
  const text = node("div", "mem-text");
  text.append(node("b", "mem-topic", entry.topic), node("p", "", entry.content));
  const shared = scope === "household" && entry.by;  // im Haushalt kann ein Eintrag von jemand anderem stammen
  const origin = { said: shared ? tr("gesagt") : tr("von dir gesagt"), inferred: tr("von der KI abgeleitet"), manual: shared ? tr("eingetragen") : tr("von dir eingetragen"), import: tr("importiert") }[entry.origin] || "";
  const meta = [origin, entry.by ? tr("von {0}", entry.by) : "", dayText(entry.updated_at)].filter(Boolean).join(" · ");
  if (meta) text.append(node("small", "mem-meta", meta));
  row.append(text);
  if (canDelete) {
    row.append(confirmButton(tr("Eintrag löschen"), async () => {
      try {
        await api(url || `api/memory/${scope}/${entry.id}`, { method: "DELETE" });
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

// ------------------------------------------------- Meine Anweisungen und Import aus Claude

const MEMORY_IMPORT_ACCEPT = ".zip,.md,.markdown,.txt,text/markdown,text/plain,application/zip";
const MEMORY_IMPORT_MAX = 4 * 1024 * 1024;

function instructionsSection(data) {
  const box = node("section", "mem-section");
  const area = node("textarea", "field area");
  area.rows = 3;
  area.maxLength = data.instructions_max || 4000;
  area.value = data.instructions || "";
  area.placeholder = tr("z. B. Antworte kurz und duze mich.");
  area.setAttribute("aria-label", tr("Meine Anweisungen"));
  const count = node("small", "mem-meta");
  const save = node("button", "pill primary", tr("Speichern"));
  save.type = "button";
  let saved = area.value.trim();
  const sync = () => {
    count.textContent = `${area.value.length} / ${area.maxLength}`;
    save.disabled = area.value.trim() === saved;
  };
  area.addEventListener("input", sync);
  save.addEventListener("click", async () => {
    save.disabled = true;
    try {
      const answer = await api("api/memory/instructions", { method: "PUT", body: JSON.stringify({ text: area.value }) });
      saved = answer.text;
      area.value = answer.text;
      toast(answer.text ? tr("Anweisungen gespeichert.") : tr("Anweisungen entfernt."));
    } catch (err) { toast(errorText(err, tr("Speichern hat nicht geklappt."))); }
    sync();
  });
  sync();
  const bar = node("div", "mem-bar");
  bar.append(count, save);
  box.append(
    node("h4", "", tr("Meine Anweisungen")),
    node("p", "mem-hint", tr("Gelten in allen deinen Chats, zusätzlich zu den Anweisungen eines Projekts. Nur du siehst sie.")),
    area, bar,
  );
  return box;
}

function memoryImportSection(body, draw) {
  const box = node("section", "mem-section");
  const picker = node("input");
  picker.type = "file";
  picker.accept = MEMORY_IMPORT_ACCEPT;
  picker.hidden = true;
  const add = node("button", "pill know-add");
  add.type = "button";
  add.append(icon("upload"), node("span", "", tr("Export von Claude wählen")));
  add.addEventListener("click", () => picker.click());
  const status = node("p", "mem-hint know-status");
  status.setAttribute("role", "status");
  picker.addEventListener("change", async () => {
    const file = picker.files[0];
    picker.value = "";
    if (!file) return;
    if (file.size > MEMORY_IMPORT_MAX) { status.textContent = tr("Die Datei ist zu groß (höchstens {0} MB).", MEMORY_IMPORT_MAX / 1024 / 1024); return; }
    add.disabled = true;
    status.textContent = tr("Lese {0} …", file.name);
    try {
      const found = await api("api/memory/import/preview", { method: "POST", body: JSON.stringify({ name: file.name, data: await toBase64(file) }) });
      memoryImportReview(body, found, draw);
    } catch (err) {
      status.textContent = errorText(err, tr("Die Datei konnte nicht gelesen werden."));
      add.disabled = false;
    }
  });
  box.append(
    node("h4", "", tr("Aus Claude übernehmen")),
    node("p", "mem-hint", tr("Bei Claude gibt es in den Einstellungen unter „Gedächtnis“ den Export als ZIP-Datei mit Markdown. Wähle sie hier aus (eine einzelne Markdown- oder Textdatei geht auch). Du siehst alles vorher und bestimmst, was übernommen wird.")),
    add, picker, status,
  );
  return box;
}

function memoryImportReview(body, found, back) {
  const parts = [];
  const backLink = node("button", "mem-link", tr("‹ Zurück"));
  backLink.type = "button";
  backLink.addEventListener("click", back);
  parts.push(backLink, node("h4", "mem-review-title", tr("Das habe ich gefunden")));
  const total = found.entries.length;
  parts.push(node("p", "mem-hint", [
    trn(total, "1 Gedächtnis-Eintrag", "{0} Gedächtnis-Einträge"),
    found.instructions.text ? tr("und Anweisungen") : "",
  ].filter(Boolean).join(" ") + ". " + tr("Entferne den Haken bei allem, was nicht mit soll.")));

  let scope = "person";
  const scopeBox = node("div", "mem-scope");
  const scopeSelect = node("select", "field");
  scopeSelect.setAttribute("aria-label", tr("Wo speichern"));
  scopeSelect.append(new Option(tr("Mein Gedächtnis"), "person"));
  if (found.household_write) {
    scopeSelect.append(new Option(tr("Haushalt"), "household"));
    scopeBox.append(node("span", "", tr("Speichern in:")), scopeSelect);
    parts.push(scopeBox);
  }

  // Anweisungen
  let useInstructions = null;
  let instructionsText = null;
  let instructionsMode = null;
  if (found.instructions.text) {
    const card = node("section", "mem-card");
    const head = node("label", "mem-check");
    useInstructions = node("input");
    useInstructions.type = "checkbox";
    useInstructions.checked = true;
    head.append(useInstructions, node("b", "", tr("Als „Meine Anweisungen“ übernehmen")));
    instructionsText = node("textarea", "field area");
    instructionsText.rows = 4;
    instructionsText.maxLength = found.instructions_max;
    instructionsText.value = found.instructions.text;
    instructionsText.setAttribute("aria-label", tr("Meine Anweisungen"));
    card.append(head, instructionsText);
    if (found.instructions.truncated) card.append(node("p", "mem-hint", tr("Der Text war länger und wurde auf {0} Zeichen gekürzt.", found.instructions_max)));
    if (found.current_instructions) {
      instructionsMode = node("select", "field");
      instructionsMode.setAttribute("aria-label", tr("Bisherige Anweisungen"));
      instructionsMode.append(new Option(tr("An meine bisherigen Anweisungen anhängen"), "append"), new Option(tr("Meine bisherigen Anweisungen ersetzen"), "replace"));
      card.append(instructionsMode);
    }
    useInstructions.addEventListener("change", () => { instructionsText.disabled = !useInstructions.checked; if (instructionsMode) instructionsMode.disabled = !useInstructions.checked; });
    parts.push(card);
  }

  // Einträge
  const rows = [];
  const warn = node("p", "mem-hint mem-warn");
  const submit = node("button", "pill primary", tr("Übernehmen"));
  submit.type = "button";
  const refresh = () => {
    let fresh = 0;
    let chosen = 0;
    for (const r of rows) {
      const exists = r.entry.exists[scope];
      r.badge.hidden = !exists;
      r.badge.textContent = exists ? tr("Gibt es schon, Haken ersetzt den Eintrag") : "";
      if (r.box.checked) { chosen += 1; if (!exists) fresh += 1; }
    }
    const free = found.free[scope];
    warn.hidden = fresh <= free;
    warn.textContent = fresh > free ? tr("Im Gedächtnis ist nur noch Platz für {0} neue Einträge. Der Rest wird übersprungen.", free) : "";
    const instr = useInstructions && useInstructions.checked ? 1 : 0;
    submit.disabled = chosen + instr === 0;
    submit.textContent = chosen ? tr("{0} übernehmen", chosen + (instr ? 1 : 0)) : tr("Übernehmen");
  };
  scopeSelect.addEventListener("change", () => {
    scope = scopeSelect.value;
    for (const r of rows) r.box.checked = !r.entry.exists[scope];
    refresh();
  });
  if (useInstructions) useInstructions.addEventListener("change", refresh);
  if (total) {
    const tools = node("div", "mem-tools");
    const all = node("button", "mem-link", tr("Alle wählen"));
    const none = node("button", "mem-link", tr("Keine wählen"));
    all.type = none.type = "button";
    all.addEventListener("click", () => { for (const r of rows) r.box.checked = true; refresh(); });
    none.addEventListener("click", () => { for (const r of rows) r.box.checked = false; refresh(); });
    tools.append(node("b", "", tr("Gedächtnis")), all, none);
    parts.push(tools);
    const list = node("div", "mem-import-list");
    for (const entry of found.entries) {
      const label = node("label", "mem-entry mem-pick");
      const box = node("input");
      box.type = "checkbox";
      box.checked = !entry.exists.person;
      const text = node("div", "mem-text");
      const badge = node("small", "mem-badge");
      text.append(node("b", "mem-topic", entry.topic), badge, node("p", "", entry.content));
      label.append(box, text);
      box.addEventListener("change", refresh);
      rows.push({ entry, box, badge });
      list.append(label);
    }
    parts.push(list, warn);
  }
  if (found.skipped.length) {
    const details = node("details", "mem-skipped");
    details.append(node("summary", "", trn(found.skipped.length, "1 Datei oder Eintrag übersprungen", "{0} Dateien oder Einträge übersprungen")));
    const ul = node("ul", "know-skipped");
    for (const sk of found.skipped) ul.append(node("li", "", `${sk.name}: ${sk.reason}`));
    details.append(ul);
    parts.push(details);
  }
  const actions = node("div", "mem-import-actions");
  actions.append(submit);
  parts.push(actions);
  submit.addEventListener("click", async () => {
    submit.disabled = true;
    const payload = {
      scope,
      entries: rows.filter((r) => r.box.checked).map((r) => ({ topic: r.entry.topic, content: r.entry.content, replace: !!r.entry.exists[scope] })),
    };
    if (useInstructions && useInstructions.checked) {
      payload.instructions = instructionsText.value;
      payload.instructions_mode = instructionsMode ? instructionsMode.value : "replace";
    }
    try {
      const result = await api("api/memory/import", { method: "POST", body: JSON.stringify(payload) });
      memoryImportDone(body, result, back);
    } catch (err) {
      toast(errorText(err, tr("Übernehmen hat nicht geklappt.")));
      refresh();
    }
  });
  refresh();
  body.classList.add("tall");
  body.replaceChildren(...parts);
  body.scrollTop = 0;
}

function memoryImportDone(body, result, back) {
  const parts = [node("h4", "mem-review-title", tr("Fertig"))];
  const lines = [];
  if (result.saved) lines.push(trn(result.saved, "1 neuer Eintrag im Gedächtnis", "{0} neue Einträge im Gedächtnis"));
  if (result.replaced) lines.push(trn(result.replaced, "1 Eintrag ersetzt", "{0} Einträge ersetzt"));
  if (result.instructions) lines.push(tr("Meine Anweisungen aktualisiert"));
  if (!lines.length) lines.push(tr("Es wurde nichts gespeichert."));
  const list = node("ul", "mem-done");
  for (const line of lines) list.append(node("li", "", line));
  parts.push(list);
  if (result.skipped.length) {
    parts.push(node("p", "mem-hint", trn(result.skipped.length, "1 Eintrag wurde übersprungen:", "{0} Einträge wurden übersprungen:")));
    const ul = node("ul", "know-skipped");
    for (const sk of result.skipped) ul.append(node("li", "", `${sk.name}: ${sk.reason}`));
    parts.push(ul);
  }
  const back2 = node("button", "pill primary", tr("Zum Gedächtnis"));
  back2.type = "button";
  back2.addEventListener("click", back);
  parts.push(back2);
  body.replaceChildren(...parts);
  body.scrollTop = 0;
}

function memoryPanel(body) {
  const draw = async () => {
    body.classList.remove("tall");
    let data;
    try { data = await api("api/memory"); } catch { body.replaceChildren(node("p", "mem-empty", tr("Das Gedächtnis ist gerade nicht erreichbar."))); return; }
    const parts = [instructionsSection(data)];
    const section = (title, hint, entries, scope, canDelete, url = null) => {
      const box = node("section", "mem-section");
      box.append(node("h4", "", title), node("p", "mem-hint", hint));
      if (entries.length === 0) box.append(node("p", "mem-empty", tr("Noch nichts gemerkt.")));
      for (const e of entries) box.append(memoryEntry(e, scope, canDelete, draw, url ? url(e) : ""));
      parts.push(box);
    };
    section(tr("Mein Gedächtnis"), tr("Nur du siehst das und nur dir gegenüber nutzt die KI es."), data.person, "person", true);
    section(tr("Haushalt"), data.household_write ? tr("Gilt für alle im Haushalt.") : tr("Gilt für alle im Haushalt. Du darfst es ansehen, aber nicht ändern."), data.household, "household", data.household_write);
    for (const pr of data.projects || []) {
      if (!pr.entries.length) continue;
      section(tr("Projekt: {0}", pr.name), tr("Gilt nur in den Chats dieses Projekts, zusätzlich zu deinem Gedächtnis und dem Haushalt."), pr.entries, "project", true, (e) => `api/projects/${encodeURIComponent(pr.id)}/memory/${e.id}`);
    }
    if (data.overview) parts.push(overviewSection(data.overview, draw));
    parts.push(memoryImportSection(body, draw));
    // Eintrag selbst hinzufügen
    const form = node("form", "mem-form");
    form.autocomplete = "off";
    const scope = node("select", "field");
    scope.setAttribute("aria-label", tr("Wo speichern"));
    scope.append(new Option(tr("Mein Gedächtnis"), "person"));
    if (data.household_write) scope.append(new Option(tr("Haushalt"), "household"));
    for (const pr of data.projects || []) scope.append(new Option(tr("Projekt: {0}", pr.name), `project:${pr.id}`));
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
        const [kind, projectId = ""] = scope.value.split(":");
        await api("api/memory", { method: "POST", body: JSON.stringify({ scope: kind, project_id: projectId, topic: topic.value, content: content.value }) });
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

const KNOWLEDGE_ACCEPT = ".zip,.png,.jpg,.jpeg,.gif,.webp,.pdf,.docx,.xlsx,text/*,.md,.csv,.tsv,.json,.yaml,.yml,.xml,.log,.py,.js,.ts,.sh,.ps1,.ini,.conf,.cfg,.toml,.sql,.html,.css,.jinja,.j2";
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
        const report = { added: 0, skipped: [], noText: [] };
        for (const [i, file] of files.entries()) {
          status.textContent = tr("Lade {0} ({1} von {2}) …", file.name, i + 1, files.length);
          if (file.size > KNOWLEDGE_MAX) { report.skipped.push({ name: file.name, reason: tr("zu groß (höchstens {0} MB je Datei oder ZIP)", KNOWLEDGE_MAX / 1024 / 1024) }); continue; }
          try {
            const answer = await api(`api/projects/${encodeURIComponent(project.id)}/knowledge`, { method: "POST", body: JSON.stringify({ name: file.name, data: await toBase64(file) }) });
            report.added += answer.added.length;
            report.skipped.push(...answer.skipped);
            report.noText.push(...(answer.no_text || []));
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
          if (report.noText.length) note.textContent += " " + tr("Ohne durchsuchbaren Text, das Original ist gespeichert: {0}.", report.noText.join(", "));
          if (report.skipped.length) {
            const list = node("ul", "know-skipped");
            for (const sk of report.skipped.slice(0, 12)) list.append(node("li", "", `${sk.name}: ${sk.reason}`));
            note.after(list);
          }
        }
        loadAll().catch(() => {});
      });
      parts.push(node("p", "mem-hint", tr("Text, Markdown, YAML, Word, Excel, PDF, Bilder oder ein ZIP davon. Das Original bleibt erhalten. Die KI durchsucht das Wissen bei Bedarf und liest gezielt hinein, nur in den Chats dieses Projekts, und legt auf Wunsch eigene Dateien hier ab.")), add, picker, status);
      const list = node("div", "know-list");
      if (data.files.length === 0) list.append(node("p", "mem-empty", tr("Noch keine Dateien. Importiere zum Beispiel Notizen, Anleitungen oder Konfigurationen.")));
      for (const f of data.files) {
        const row = node("div", "know-file");
        const name = node("span", "know-name", f.name);
        name.title = f.name;
        row.append(icon("file"), name, node("small", "mem-meta", f.has_file && !(f.mime || "").startsWith("text/") ? tr("{0} · Original", formatSize(f.file_size)) : tr("{0} Text", formatSize(f.size))));
        if (f.has_file) {
          const get = node("button", "icon-btn");
          get.type = "button";
          get.title = tr("{0} herunterladen", f.name);
          get.setAttribute("aria-label", tr("{0} herunterladen", f.name));
          get.append(icon("download"));
          get.addEventListener("click", () => downloadProjectFile(project, f));
          row.append(get);
        }
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

async function downloadProjectFile(project, entry) {
  try {
    const response = await fetch(`api/projects/${encodeURIComponent(project.id)}/knowledge/${entry.id}/file`, { credentials: "same-origin", headers: { "X-Requested-With": "ki-chat" } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const blob = await response.blob();
    await saveFile(entry.name.split("/").pop(), blob, blob.type || "application/octet-stream");
  } catch {
    toast(tr("Der Download hat nicht geklappt."));
  }
}

async function openKnowledge(project) {
  await openSheet({
    title: tr("Wissen: {0}", project.name),
    sub: tr("Dateien, aus denen die KI in diesem Projekt nachschlagen darf."),
    ok: tr("Fertig"),
    panel: knowledgePanel(project),
  });
}

// ------------------------------------------------------------------- Skills (eigene Seite)

const SKILL_ACCEPT = ".skill,.zip,.md,text/markdown,text/plain";
const SKILL_MAX = 4 * 1024 * 1024;
const skillsUi = { mode: "list", section: "skills", tab: "mine", mineQuery: "", query: "", category: "all", sort: "popular", detail: null, preview: null, data: null, status: "", busy: false };

async function openSkills(section = "skills") {
  if (!state.me) return;
  setView("skills");
  rememberDetail(section);
  detachRun();
  releaseRecent();
  state.activeId = null;
  rememberActive();
  state.newProject = null;
  state.heldUnread = null;
  renderSide();
  closeMenu();
  setTitle(tr("Anpassungen"));
  Object.assign(skillsUi, { mode: "list", section, tab: "mine", mineQuery: "", query: "", category: "all", detail: null, preview: null, status: "", busy: false });
  Object.assign(connUi, { id: null, form: null, flow: null, setup: null, tab: "mine", mineQuery: "", query: "", category: "all" });
  Object.assign(connUi.registry, { q: "", items: [], next: "", loaded: false, error: "" });
  Object.assign(plUi, { data: null, tab: "mine", query: "", detail: null, preview: null, result: null, busy: false });
  await loadSkills();
  if (section === "connectors") loadConnectors();
  if (section === "plugins") loadPlugins();
  $("skills").scrollTop = 0;
}

async function loadSkills() {
  try { skillsUi.data = await api("api/skills"); } catch (err) { skillsUi.data = null; skillsUi.status = errorText(err, tr("Die Skills sind gerade nicht erreichbar.")); }
  if (state.view === "skills") renderSkills();
}

function skillsGo(mode, extra = {}) {
  Object.assign(skillsUi, { mode, status: "", ...extra });
  renderSkills();
  $("skills").scrollTop = 0;
  $("skills-wrap").querySelector("h2")?.focus();
}

function renderSkills() {
  const wrap = $("skills-wrap");
  wrap.replaceChildren();
  if (skillsUi.mode === "detail") renderSkillDetail(wrap);
  else if (skillsUi.mode === "write") renderSkillWrite(wrap);
  else if (skillsUi.mode === "preview") renderSkillPreview(wrap);
  else if (skillsUi.mode === "connector") renderConnectorDetail(wrap);
  else if (skillsUi.mode === "connector-form") renderConnectorForm(wrap);
  else if (skillsUi.mode === "connector-setup") renderConnectorSetup(wrap);
  else if (skillsUi.mode === "plugin") renderPluginDetail(wrap);
  else if (skillsUi.mode === "plugin-preview") renderPluginPreview(wrap);
  else if (skillsUi.mode === "plugin-result") renderPluginResult(wrap);
  else renderSkillList(wrap);
}

function skillHead(wrap, title, intro, ...buttons) {
  const head = node("div", "skills-top");
  const heading = node("div", "");
  const h = node("h2", "", title);
  h.tabIndex = -1;
  heading.append(h);
  if (intro) heading.append(node("p", "skills-intro", intro));
  head.append(heading);
  if (buttons.length) {
    const box = node("div", "skills-buttons");
    box.append(...buttons);
    head.append(box);
  }
  wrap.append(head);
}

function skillBack(wrap, label = tr("Zurück zu den Anpassungen")) {
  const back = node("button", "skills-back");
  back.type = "button";
  back.append(icon("chevron"), node("span", "", label));
  back.addEventListener("click", () => skillsGo("list", { detail: null, preview: null }));
  wrap.append(back);
}

function skillSwitch(s, after) {
  const toggle = node("button", "sched-switch");
  toggle.type = "button";
  toggle.setAttribute("role", "switch");
  toggle.setAttribute("aria-checked", String(s.enabled));
  toggle.setAttribute("aria-label", s.enabled ? tr("{0} ausschalten", s.name) : tr("{0} einschalten", s.name));
  toggle.title = s.enabled ? tr("Ausschalten") : tr("Einschalten");
  toggle.append(node("span", "knob"));
  toggle.addEventListener("click", async (event) => {
    event.stopPropagation();
    try {
      await api(`api/skills/${s.id}`, { method: "PATCH", body: JSON.stringify({ enabled: !s.enabled }) });
      s.enabled = !s.enabled;
      await after();
    } catch { toast(tr("Das hat nicht geklappt.")); }
  });
  return toggle;
}

function skillBadges(s) {
  const row = node("div", "skill-badges");
  if (s.standard) row.append(node("span", "skill-badge", tr("Standard")));
  else if (s.recommended || s.origin === "recommended") row.append(node("span", "skill-badge", s.categoryLabel || tr("empfohlen")));
  else row.append(node("span", "skill-badge" + (s.imported ? " ext" : ""), s.imported ? tr("importiert") : tr("selbst geschrieben")));
  return row;
}

// ---- Liste

function renderSkillList(wrap) {
  const data = skillsUi.data;
  const picker = node("input");
  picker.type = "file";
  picker.accept = SKILL_ACCEPT;
  picker.hidden = true;
  picker.addEventListener("change", async () => {
    const file = picker.files[0];
    picker.value = "";
    if (file) await previewSkillFile(file);
  });
  skillHead(wrap, tr("Anpassungen"), tr("Hier legst du fest, was die KI zusätzlich kann und wie sie arbeitet."), picker);

  const bar = node("div", "skills-bar");
  const tabs = node("div", "skills-tabs");
  tabs.setAttribute("role", "tablist");
  for (const [id, label] of [["skills", tr("Skills")], ["connectors", tr("Konnektoren")], ["plugins", tr("Plugins")]]) {
    if (id === "connectors" && state.me?.connectors === false) continue;
    const tab = node("button", "skills-tab", label);
    tab.type = "button";
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-selected", String(skillsUi.section === id));
    tab.addEventListener("click", () => {
      skillsUi.section = id;
      skillsUi.status = "";
      rememberDetail(id);
      renderSkills();
      if (id === "connectors") loadConnectors();
      if (id === "plugins") loadPlugins();
    });
    tabs.append(tab);
  }
  bar.append(tabs);
  wrap.append(bar);

  if (skillsUi.section === "connectors") { renderConnectors(wrap); return; }
  if (skillsUi.section === "plugins") { renderPlugins(wrap); return; }

  const status = node("p", "skills-status");
  status.setAttribute("role", "status");
  status.textContent = skillsUi.status;
  wrap.append(status);

  const tools = node("div", "skills-tools");
  const seg = node("div", "seg");
  for (const [id, label] of [["mine", tr("Meine")], ["recommended", tr("Entdecken")]]) {
    const b = node("button", "", label);
    b.type = "button";
    b.setAttribute("aria-pressed", String(skillsUi.tab === id));
    b.addEventListener("click", () => { skillsUi.tab = id; skillsUi.status = ""; renderSkills(); });
    seg.append(b);
  }
  const add = node("button", "pill primary");
  add.type = "button";
  add.disabled = skillsUi.busy;
  add.setAttribute("aria-haspopup", "menu");
  add.append(icon("plus"), node("span", "", tr("Hinzufügen")));
  add.addEventListener("click", async () => {
    const entries = [
      { value: "import", icon: "upload", label: tr("Skill importieren") },
      { value: "github", icon: "code", label: tr("Von GitHub-Link") },
      { value: "write", icon: "edit", label: tr("Selbst schreiben") },
    ];
    const choice = wideScreen() ? await openPopover(add, entries) : await openSheet({ title: tr("Skill hinzufügen"), items: entries });
    if (choice === "import") picker.click();
    else if (choice === "github") await previewSkillGithub();
    else if (choice === "write") skillsGo("write");
  });
  tools.append(seg, add);
  wrap.append(tools);

  if (!data) { wrap.append(node("p", "mem-empty", skillsUi.status || tr("Die Skills sind gerade nicht erreichbar."))); return; }
  if (skillsUi.tab === "recommended") renderDiscover(wrap, data);
  else renderMine(wrap, data);
  wrap.append(node("p", "skills-note", tr("Skripte in Skills werden nie ausgeführt. Ein importiertes Skill gilt als fremder Inhalt: Hat die KI eines genutzt, fragt sie vor Änderungen in Home Assistant oder bei GitHub und vor Bildern erst bei dir nach.")));
}

// ---- Plugins: Pakete aus Skills und Konnektoren zu einem Thema

const plUi = { data: null, loading: false, error: "", tab: "mine", query: "", detail: null, preview: null, result: null, busy: false };

async function loadPlugins() {
  plUi.loading = true;
  try { plUi.data = await api("api/plugins"); plUi.error = ""; } catch (err) { plUi.data = null; plUi.error = errorText(err, tr("Die Plugins sind gerade nicht erreichbar.")); }
  plUi.loading = false;
  if (state.view === "skills") renderSkills();
}

function plStateText(state) {
  return {
    added: tr("Hinzugefügt"), present: tr("Schon da"), missing: tr("Fehlt noch"), taken: tr("Name belegt, dein eigenes bleibt"),
    limit: tr("Grenze erreicht"), setup: tr("Eigene App nötig"), no_rights: tr("Dafür fehlt dir das Recht"), no_access: tr("Nicht freigegeben"),
    failed: tr("Hat nicht geklappt"), replaces: tr("Wird ersetzt"), new: tr("Neu"),
  }[state] || state;
}

function plCounts(skills, connectors) {
  return `${trn(skills, "1 Skill", "{0} Skills")} · ${trn(connectors, "1 Konnektor", "{0} Konnektoren")}`;
}

function renderPlugins(wrap) {
  const status = node("p", "skills-status");
  status.setAttribute("role", "status");
  status.textContent = skillsUi.status;
  wrap.append(status);
  const data = plUi.data;
  if (!data) {
    wrap.append(node("p", "mem-empty", plUi.loading ? tr("Lädt …") : plUi.error || tr("Die Plugins sind gerade nicht erreichbar.")));
    if (!plUi.loading && !plUi.error) loadPlugins();
    return;
  }
  const tools = node("div", "skills-tools");
  const seg = node("div", "seg");
  for (const [id, label] of [["mine", tr("Meine")], ["discover", tr("Entdecken")]]) {
    const b = node("button", "", label);
    b.type = "button";
    b.setAttribute("aria-pressed", String(plUi.tab === id));
    b.addEventListener("click", () => { plUi.tab = id; skillsUi.status = ""; renderSkills(); });
    seg.append(b);
  }
  const add = node("button", "pill primary compact");
  add.type = "button";
  add.disabled = plUi.busy;
  add.setAttribute("aria-label", tr("Von GitHub-Link"));
  add.title = tr("Von GitHub-Link");
  add.append(icon("code"), node("span", "", tr("Von GitHub-Link")));
  add.addEventListener("click", pluginGithub);
  tools.append(seg, add);
  wrap.append(tools);
  if (plUi.tab === "discover") renderPluginDiscover(wrap, data);
  else renderPluginMine(wrap, data);
  wrap.append(node("p", "skills-note", tr("Ein Plugin legt Skills und Konnektoren an. Beim Entfernen verschwindet nur, was das Plugin selbst angelegt hat. Skills und Konnektoren aus fremden Plugins gelten als fremder Inhalt.")));
}

function pluginList(wrap, items, card, empty, label) {
  const filter = node("div", "skills-filter");
  const search = searchInput(label, plUi.query);
  filter.append(search);
  const count = node("p", "skills-count");
  count.setAttribute("role", "status");
  const body = node("div", "skills-grid");
  wrap.append(filter, count, body);
  const update = () => {
    const hits = items.filter((p) => wordsMatch(plUi.query, p.haystack));
    body.replaceChildren();
    count.textContent = plUi.query.trim() ? trn(hits.length, "1 Plugin", "{0} Plugins") : "";
    if (!items.length) { body.className = "skills-mine"; body.append(empty()); return; }
    body.className = "skills-grid";
    if (!hits.length) {
      body.className = "skills-mine";
      body.append(connEmpty(tr("Nichts gefunden."), tr("Versuch es mit einem anderen Wort."), connResetButton(() => { plUi.query = ""; search.value = ""; update(); search.focus(); })));
      return;
    }
    for (const p of hits) body.append(card(p));
  };
  search.addEventListener("input", () => { plUi.query = search.value; update(); });
  update();
}

function renderPluginMine(wrap, data) {
  wrap.append(node("p", "skills-hint", tr("Hier stehen die Plugins, die du hinzugefügt hast.")));
  const items = data.mine.map((p) => ({ ...p, haystack: `${p.name} ${p.description}` }));
  const empty = () => {
    const go = node("button", "pill ghost", tr("Plugins entdecken"));
    go.type = "button";
    go.addEventListener("click", () => { plUi.tab = "discover"; renderSkills(); });
    return connEmpty(tr("Noch kein Plugin."), tr("Such dir bei „Entdecken“ ein Paket zu deinem Thema aus oder hol dir ein Claude-Plugin von einem GitHub-Link."), go);
  };
  pluginList(wrap, items, (p) => pluginCard(p, "mine"), empty, tr("Plugins durchsuchen"));
}

function renderPluginDiscover(wrap, data) {
  wrap.append(node("p", "skills-hint", tr("Pakete, die Skills und Konnektoren zu einem Thema zusammen anlegen. Du siehst vorher, was dazugehört.")));
  const items = data.catalog.map((p) => ({ ...p, haystack: `${p.label} ${p.summary} ${p.skills.map((s) => s.label).join(" ")} ${p.connectors.map((c) => c.label).join(" ")}` }));
  pluginList(wrap, items, (p) => pluginCard(p, "catalog"), () => connEmpty(tr("Noch keine Pakete.")), tr("Pakete durchsuchen"));
}

function pluginCard(p, kind) {
  const mine = kind === "mine";
  const name = mine ? p.name : p.label;
  const card = node("article", "skill-card");
  const top = node("div", "skill-card-top");
  const open = node("button", "skill-open", name);
  open.type = "button";
  const go = () => pluginOpen(kind, p.id);
  open.addEventListener("click", go);
  const who = node("div", "skill-card-id");
  who.append(tile(mine && p.kind === "imported" ? "code" : p.icon || "stack", name), open);
  top.append(who);
  const badges = node("div", "skill-badges");
  if (mine) {
    badges.append(node("span", "skill-badge" + (p.kind === "imported" ? " ext" : ""), p.kind === "imported" ? tr("von GitHub") : tr("aus dem Katalog")));
    if (p.missing) badges.append(node("span", "skill-badge off", trn(p.missing, "1 Teil fehlt", "{0} Teile fehlen")));
  } else if (p.installed) badges.append(node("span", "skill-badge" + (p.complete ? "" : " off"), p.complete ? tr("Hinzugefügt") : tr("Unvollständig")));
  card.append(top, badges, node("p", "skill-desc", mine ? p.description || tr("Ohne Beschreibung.") : p.summary));
  card.append(node("small", "mem-meta", mine ? plCounts(p.skills.length, p.connectors.length) : plCounts(p.skills.length, p.connectors.length)));
  if (!mine) {
    const row = node("div", "skill-add");
    if (p.installed && p.complete) row.append(node("span", "skill-added", tr("Schon hinzugefügt")));
    else {
      const add = node("button", "pill primary", p.installed ? tr("Fehlendes ergänzen") : tr("Hinzufügen"));
      add.type = "button";
      add.addEventListener("click", (event) => { event.stopPropagation(); pluginOpen(kind, p.id); });
      row.append(add);
    }
    card.append(row);
  }
  card.addEventListener("click", (event) => { if (!event.target.closest("button")) go(); });
  return card;
}

function pluginOpen(kind, id) {
  plUi.detail = { kind, id };
  skillsGo("plugin");
}

function pluginRow(parts, name, stateKey, extra, stateText) {
  const row = node("li", "pl-row");
  if (parts) row.append(parts);
  const text = node("span", "pl-name", name);
  row.append(text);
  if (stateKey) row.append(node("span", "pl-state " + stateKey, stateText || plStateText(stateKey)));
  if (extra) row.append(extra);
  return row;
}

function pluginHints(data, hasConnectors) {
  const box = [];
  if (!hasConnectors) return box;
  if (!data.connector_access) box.push(node("p", "skills-warn", tr("Konnektoren sind für dich nicht freigegeben. Es kommen nur die Skills mit.")));
  else if (!data.can_connectors) box.push(node("p", "skills-warn", tr("Du darfst keine eigenen Konnektoren anlegen. Es kommen nur die Skills mit.")));
  return box;
}

function renderPluginDetail(wrap) {
  const data = plUi.data;
  const d = plUi.detail;
  const list = d && data ? (d.kind === "mine" ? data.mine : data.catalog) : [];
  const p = list.find((x) => x.id === d?.id);
  skillBack(wrap, tr("Zurück zu den Plugins"));
  if (!p) { wrap.append(node("p", "mem-empty", tr("Dieses Plugin gibt es nicht mehr."))); return; }
  const mine = d.kind === "mine";
  skillHead(wrap, mine ? p.name : p.label, mine ? p.description : p.summary);
  const panel = node("section", "skills-panel");
  panel.append(node("p", "skills-label", trn(p.skills.length, "1 Skill", "{0} Skills")));
  const skills = node("ul", "pl-list");
  for (const s of p.skills) skills.append(pluginRow(null, mine ? s.name : s.label, mine ? (s.present ? "present" : "missing") : s.state));
  panel.append(skills.children.length ? skills : node("p", "skills-hint", tr("Keine.")));
  panel.append(node("p", "skills-label", trn(p.connectors.length, "1 Konnektor", "{0} Konnektoren")));
  const conns = node("ul", "pl-list");
  for (const c of p.connectors) {
    let open = null;
    let stateKey;
    let stateText = "";
    if (mine) {
      stateKey = c.connector_id ? (c.status === "ok" ? "added" : "present") : "missing";
      if (c.connector_id) {
        stateText = connStatusLabel(c);
        open = node("button", "mem-link", tr("Öffnen"));
        open.type = "button";
        open.addEventListener("click", () => { skillsUi.section = "connectors"; connOpen(c.connector_id); loadConnectors(); });
      }
    } else stateKey = c.state;
    conns.append(pluginRow(connTile({ label: c.label || c.name, icon: c.icon }), c.label || c.name, stateKey, open, stateText));
  }
  panel.append(conns.children.length ? conns : node("p", "skills-hint", tr("Keine.")));
  for (const h of pluginHints(data, p.connectors.length > 0)) panel.append(h);
  if (mine && p.source) panel.append(node("p", "skills-hint", tr("Quelle: {0}", p.source)));
  if (mine && p.notes?.length) {
    const notes = node("ul", "skills-files");
    for (const n of p.notes) notes.append(node("li", "", n));
    panel.append(node("p", "skills-label", tr("Nicht übernommen:")), notes);
  }
  if (!mine && p.connectors.some((c) => c.state === "setup")) panel.append(node("p", "skills-hint", tr("Für Google-Dienste brauchst du eine eigene Google-App. Die Anleitung steht bei den Konnektoren unter „Entdecken“.")));
  const foot = node("div", "skills-buttons");
  if (mine) {
    foot.append(node("span", "pl-remove-hint", tr("Entfernt nur, was dieses Plugin selbst angelegt hat ({0}).", plCounts(p.added.skills, p.added.connectors))));
    foot.append(confirmButton(tr("{0} entfernen", p.name), async () => {
      try {
        const out = await api(`api/plugins/${p.id}`, { method: "DELETE" });
        toast(tr("„{0}“ entfernt ({1}).", p.name, plCounts(out.skills, out.connectors)));
        skillsGo("list", { detail: null });
        await Promise.all([loadPlugins(), loadSkills()]);
        if (connUi.data) loadConnectors();
      } catch (err) { toast(errorText(err, tr("Entfernen hat nicht geklappt."))); }
    }));
  } else if (!(p.installed && p.complete)) {
    const add = node("button", "pill primary", p.installed ? tr("Fehlendes ergänzen") : tr("Hinzufügen"));
    add.type = "button";
    add.addEventListener("click", () => pluginInstall(p, add));
    foot.append(add);
  } else foot.append(node("span", "skill-added", tr("Schon hinzugefügt")));
  panel.append(foot);
  wrap.append(panel);
}

async function pluginInstall(entry, button) {
  button.disabled = true;
  try {
    const result = await api(`api/plugins/catalog/${encodeURIComponent(entry.id)}`, { method: "POST" });
    plUi.result = { name: entry.label, ...result };
    plUi.tab = "mine";
    skillsGo("plugin-result");
    await Promise.all([loadPlugins(), loadSkills()]);
    if (connUi.data) loadConnectors();
  } catch (err) { toast(errorText(err, tr("Hinzufügen hat nicht geklappt."))); button.disabled = false; }
}

function renderPluginResult(wrap) {
  const r = plUi.result;
  skillBack(wrap, tr("Zurück zu den Plugins"));
  if (!r) { wrap.append(node("p", "mem-empty", tr("Dieses Plugin gibt es nicht mehr."))); return; }
  skillHead(wrap, tr("„{0}“ ist hinzugefügt", r.name), tr("Das ist passiert:"));
  const panel = node("section", "skills-panel");
  if (r.skills.length) {
    panel.append(node("p", "skills-label", trn(r.skills.length, "1 Skill", "{0} Skills")));
    const skills = node("ul", "pl-list");
    for (const s of r.skills) skills.append(pluginRow(null, s.label || s.name, s.state));
    panel.append(skills);
  }
  if (r.connectors.length) {
    panel.append(node("p", "skills-label", trn(r.connectors.length, "1 Konnektor", "{0} Konnektoren")));
    const conns = node("ul", "pl-list");
    for (const c of r.connectors) {
      const row = pluginRow(connTile({ label: c.label || c.name, icon: c.icon }), c.label || c.name, c.state);
      if (c.message) row.append(node("small", "pl-msg", c.message));
      conns.append(row);
    }
    panel.append(conns);
    const added = r.connectors.some((c) => c.state === "added");
    const setup = r.connectors.some((c) => c.state === "setup");
    if (added) panel.append(node("p", "skills-hint", tr("Die neuen Konnektoren sind noch nicht verbunden. Das machst du bei den Konnektoren mit einem Klick.")));
    if (setup) panel.append(node("p", "skills-hint", tr("Für Google-Dienste brauchst du eine eigene Google-App. Die Anleitung steht bei den Konnektoren unter „Entdecken“.")));
    if (added || setup) {
      const foot = node("div", "skills-buttons");
      const go = node("button", "pill primary", tr("Zu den Konnektoren"));
      go.type = "button";
      go.addEventListener("click", () => {
        skillsUi.section = "connectors";
        connUi.tab = added ? "mine" : "discover";
        skillsGo("list");
        loadConnectors();
      });
      foot.append(go);
      panel.append(foot);
    }
  }
  wrap.append(panel);
}

// ---- Claude-Plugin von einem GitHub-Link

async function pluginGithub() {
  if (plUi.busy) return;
  const url = await openSheet({
    title: tr("Plugin von GitHub holen"),
    sub: tr("Link zu einem öffentlichen Plugin-Ordner, zum Beispiel https://github.com/besitzer/repo/tree/main/plugins/name. Übernommen werden nur Skills und Server-Adressen; Befehle, Unteragenten und Skripte nie. Gespeichert wird erst nach der Vorschau."),
    label: tr("GitHub-Link"), value: "", placeholder: "https://github.com/…", ok: tr("Holen"), maxLength: 500,
  });
  if (!url) return;
  plUi.busy = true;
  skillsUi.status = tr("Hole das Plugin von GitHub …");
  renderSkills();
  try {
    const preview = await api("api/plugins/github", { method: "POST", body: JSON.stringify({ url }) });
    plUi.busy = false;
    plUi.preview = preview;
    plUi.pick = {
      skills: new Set(preview.skills.filter((s) => s.state !== "taken").map((s) => s.name)),
      servers: new Map(preview.servers.map((s) => [s.name, { on: !s.present && preview.can_connectors, auth: s.auth }])),
    };
    skillsGo("plugin-preview");
  } catch (err) {
    plUi.busy = false;
    skillsUi.status = errorText(err, tr("Das Plugin konnte nicht von GitHub geholt werden."));
    renderSkills();
  }
}

const PL_AUTH = () => [["none", tr("Keine Anmeldung")], ["bearer", tr("Token (Bearer)")], ["header", tr("Schlüssel in einem Header")], ["oauth", tr("Anmeldung beim Dienst (OAuth)")]];

function renderPluginPreview(wrap) {
  const p = plUi.preview;
  const pick = plUi.pick;
  if (!p || !pick) { skillBack(wrap, tr("Zurück zu den Plugins")); return; }
  skillBack(wrap, tr("Abbrechen"));
  skillHead(wrap, p.name, p.description || tr("So sieht das Plugin aus. Es wird erst nach „Hinzufügen“ gespeichert."));
  const panel = node("section", "skills-panel");
  const add = node("button", "pill primary", tr("Hinzufügen"));
  add.type = "button";
  const refresh = () => { add.disabled = plUi.busy || (!pick.skills.size && ![...pick.servers.values()].some((s) => s.on)); };

  panel.append(node("p", "skills-label", trn(p.skills.length, "1 Skill", "{0} Skills")));
  const skills = node("ul", "pl-list");
  for (const s of p.skills) {
    const row = node("li", "pl-row");
    const label = node("label", "pl-pick");
    const box = node("input");
    box.type = "checkbox";
    box.checked = pick.skills.has(s.name);
    box.disabled = s.state === "taken";
    box.addEventListener("change", () => { if (box.checked) pick.skills.add(s.name); else pick.skills.delete(s.name); refresh(); });
    const text = node("span", "pl-name");
    text.append(node("b", "", s.name), node("small", "mem-meta", s.description));
    label.append(box, text);
    row.append(label, node("span", "pl-state " + s.state, plStateText(s.state)));
    for (const w of s.warnings) row.append(node("small", "pl-msg", w));
    skills.append(row);
  }
  panel.append(p.skills.length ? skills : node("p", "skills-hint", tr("Keine.")));

  panel.append(node("p", "skills-label", trn(p.servers.length, "1 Konnektor (Server-Adresse)", "{0} Konnektoren (Server-Adressen)")));
  const servers = node("ul", "pl-list");
  for (const s of p.servers) {
    const cfg = pick.servers.get(s.name);
    const row = node("li", "pl-row");
    const label = node("label", "pl-pick");
    const box = node("input");
    box.type = "checkbox";
    box.checked = cfg.on;
    box.disabled = s.present || !p.can_connectors;
    box.addEventListener("change", () => { cfg.on = box.checked; refresh(); });
    const text = node("span", "pl-name");
    text.append(node("b", "", s.name), node("small", "mem-meta pl-url", s.url));
    label.append(box, text);
    row.append(label);
    if (s.present) row.append(node("span", "pl-state present", plStateText("present")));
    else if (!s.catalog_id) {
      const sel = node("select", "field pl-auth");
      sel.setAttribute("aria-label", tr("Anmeldung für {0}", s.name));
      for (const [value, text2] of PL_AUTH()) {
        const o = node("option", "", text2);
        o.value = value;
        sel.append(o);
      }
      sel.value = cfg.auth;
      sel.addEventListener("change", () => { cfg.auth = sel.value; });
      row.append(sel);
    } else row.append(node("span", "pl-state present", tr("Aus dem Katalog bekannt")));
    servers.append(row);
  }
  panel.append(p.servers.length ? servers : node("p", "skills-hint", tr("Keine.")));
  if (p.servers.length && !p.can_connectors) panel.append(node("p", "skills-warn", tr("Du darfst keine eigenen Konnektoren anlegen. Es kommen nur die Skills mit.")));
  if (p.servers.some((s) => !s.present && !s.catalog_id)) panel.append(node("p", "skills-hint", tr("Die Anmeldeart ist geraten. Stimmt sie nicht, kannst du sie später beim Konnektor ändern.")));

  const left = [...(p.notes || []), ...p.skipped.map((s) => `${s.name}: ${s.reason}`)];
  if (left.length) {
    const list = node("ul", "skills-files");
    for (const n of left.slice(0, 20)) list.append(node("li", "", n));
    panel.append(node("p", "skills-label", tr("Nicht übernommen:")), list);
  }
  if (p.ignored?.length) {
    const list = node("ul", "skills-files");
    for (const n of p.ignored) list.append(node("li", "", n));
    panel.append(node("p", "skills-label", tr("Gibt es im Plugin, wird aber nie geladen:")), list);
  }
  if (p.source) panel.append(node("p", "skills-hint", tr("Quelle: {0}", p.source)));
  if (p.replaces) panel.append(node("p", "skills-warn", tr("Dieses Plugin hast du schon. Es wird aktualisiert.")));
  panel.append(node("p", "skills-hint", tr("Skills und Konnektoren aus einem fremden Plugin gelten als fremder Inhalt. Hat die KI einen genutzt, fragt sie vor Änderungen in Home Assistant oder bei GitHub und vor Bildern erst bei dir nach.")));

  const foot = node("div", "skills-buttons");
  const cancel = node("button", "pill ghost", tr("Abbrechen"));
  cancel.type = "button";
  cancel.addEventListener("click", () => skillsGo("list", { preview: null }));
  add.addEventListener("click", async () => {
    plUi.busy = true;
    refresh();
    try {
      const body = {
        data: p.data, source: p.source, skills: [...pick.skills],
        servers: p.servers.filter((s) => pick.servers.get(s.name)?.on).map((s) => ({ name: s.name, auth: pick.servers.get(s.name).auth })),
      };
      const result = await api("api/plugins/import", { method: "POST", body: JSON.stringify(body) });
      plUi.busy = false;
      plUi.result = { name: p.name, skills: result.skills, connectors: result.connectors };
      plUi.preview = null;
      plUi.tab = "mine";
      skillsGo("plugin-result");
      await Promise.all([loadPlugins(), loadSkills()]);
      if (connUi.data) loadConnectors();
    } catch (err) { plUi.busy = false; toast(errorText(err, tr("Hinzufügen hat nicht geklappt."))); refresh(); }
  });
  refresh();
  foot.append(add, cancel);
  panel.append(foot);
  wrap.append(panel);
}

function renderMine(wrap, data) {
  wrap.append(node("p", "skills-hint", tr("Diese Skills gelten in allen deinen Chats. Die KI nimmt eines von selbst, wenn die Aufgabe zur Beschreibung passt.")));
  const filter = node("div", "skills-filter");
  const search = searchInput(tr("Skills durchsuchen"), skillsUi.mineQuery);
  filter.append(search);
  const count = node("p", "skills-count");
  count.setAttribute("role", "status");
  const body = node("div", "skills-mine");
  wrap.append(filter, count, body);

  const update = () => {
    const q = skillsUi.mineQuery;
    const own = data.skills.filter((s) => wordsMatch(q, `${s.name} ${s.description}`));
    const std = data.standard.filter((s) => wordsMatch(q, `${s.label} ${s.name} ${s.description}`));
    body.replaceChildren();
    count.textContent = q.trim() ? trn(own.length + std.length, "1 Skill", "{0} Skills") : "";
    if (q.trim() && !own.length && !std.length) {
      const none = node("div", "skills-empty");
      const reset = node("button", "pill ghost", tr("Suche zurücksetzen"));
      reset.type = "button";
      reset.addEventListener("click", () => { skillsUi.mineQuery = ""; search.value = ""; update(); search.focus(); });
      none.append(node("p", "", tr("Nichts gefunden.")), node("p", "skills-hint", tr("Versuch es mit einem anderen Wort.")), reset);
      body.append(none);
      return;
    }
    if (!data.skills.length && !q.trim()) {
      const empty = node("div", "skills-empty");
      const go = node("button", "pill ghost", tr("Skills entdecken"));
      go.type = "button";
      go.addEventListener("click", () => { skillsUi.tab = "recommended"; renderSkills(); });
      empty.append(
        node("p", "", tr("Noch keine eigenen Skills.")),
        node("p", "skills-hint", tr("Importiere eine SKILL.md oder ein .skill, schreibe selbst eines oder such dir bei „Entdecken“ eines aus.")),
        go,
      );
      body.append(empty);
    } else if (own.length) {
      const grid = node("div", "skills-grid");
      for (const s of own) grid.append(skillCard(s));
      body.append(grid);
    }
    if (std.length) {
      body.append(node("h3", "skills-section", tr("Standard")));
      body.append(node("p", "skills-hint", tr("Mitgeliefert und immer an. Deine eigenen Skills gehen ihnen vor, wenn sie zur Aufgabe passen.")));
      const grid = node("div", "skills-grid");
      for (const s of std) grid.append(skillCard({ ...s, standard: true }));
      body.append(grid);
    }
  };
  search.addEventListener("input", () => { skillsUi.mineQuery = search.value; update(); });
  update();
}

// Entdecken: Suche, Kategorien und Sortierung über die mitgelieferten Skills
function renderDiscover(wrap, data) {
  wrap.append(node("p", "skills-hint", tr("Geprüfte Skills, mitgeliefert und frei nutzbar. Mit „Hinzufügen“ landen sie bei „Meine“; dort kannst du sie jederzeit ausschalten oder entfernen.")));
  const cats = new Map(data.categories.map((c) => [c.id, c.label]));
  const all = data.recommended.map((s) => ({ ...s, recommended: true, categoryLabel: cats.get(s.category) || "", haystack: `${s.label} ${s.name} ${s.summary} ${cats.get(s.category) || ""}` }));

  const controls = node("div", "skills-filter");
  const search = searchInput(tr("Skills durchsuchen"), skillsUi.query);
  const sort = node("select", "field");
  sort.setAttribute("aria-label", tr("Sortierung"));
  for (const [id, label] of [["popular", tr("Beliebteste")], ["az", tr("A bis Z")]]) {
    const o = node("option", "", label);
    o.value = id;
    sort.append(o);
  }
  sort.value = skillsUi.sort;
  controls.append(search, sort);
  const chips = node("div", "skills-cats");
  chips.setAttribute("role", "group");
  chips.setAttribute("aria-label", tr("Kategorien"));
  const count = node("p", "skills-count");
  count.setAttribute("role", "status");
  const grid = node("div", "skills-grid");
  wrap.append(controls, chips, count, grid);

  const update = () => {
    const hits = all.filter((s) => wordsMatch(skillsUi.query, s.haystack));
    const per = new Map();
    for (const s of hits) per.set(s.category, (per.get(s.category) || 0) + 1);
    if (skillsUi.category !== "all" && !cats.has(skillsUi.category)) skillsUi.category = "all";
    chips.replaceChildren();
    for (const [id, label] of [["all", tr("Alle")], ...cats]) {
      const n = id === "all" ? hits.length : per.get(id) || 0;
      const chip = node("button", "skills-cat", `${label} · ${n.toLocaleString(kiLocale)}`);
      chip.type = "button";
      chip.setAttribute("aria-pressed", String(skillsUi.category === id));
      if (!n && skillsUi.category !== id) chip.disabled = true;
      chip.addEventListener("click", () => { skillsUi.category = id; update(); });
      chips.append(chip);
    }
    const shown = hits.filter((s) => skillsUi.category === "all" || s.category === skillsUi.category);
    shown.sort(skillsUi.sort === "az"
      ? (a, b) => a.label.localeCompare(b.label, kiLocale)
      : (a, b) => (b.installs || 0) - (a.installs || 0) || a.label.localeCompare(b.label, kiLocale));
    grid.replaceChildren();
    if (!shown.length) {
      const none = node("div", "skills-empty");
      const reset = node("button", "pill ghost", tr("Suche zurücksetzen"));
      reset.type = "button";
      reset.addEventListener("click", () => { skillsUi.query = ""; skillsUi.category = "all"; search.value = ""; update(); search.focus(); });
      none.append(node("p", "", tr("Nichts gefunden.")), node("p", "skills-hint", tr("Versuch es mit einem anderen Wort oder wähle eine andere Kategorie.")), reset);
      grid.append(none);
      return;
    }
    for (const s of shown) grid.append(skillCard(s));
  };
  search.addEventListener("input", () => { skillsUi.query = search.value; update(); });
  sort.addEventListener("change", () => { skillsUi.sort = sort.value; update(); });
  update();
}

function skillSource(s) {
  const by = tr("von {0}", s.author);
  return by;
}

// Symbol je Kategorie (empfohlene Skills); eigene und importierte Skills haben das Skill-Symbol, die Standard-Skills den Stift
const SKILL_ICONS = { marketing: "megaphone", design: "pen", office: "file", tech: "code", data: "chart", product: "cube", support: "headset", people: "users" };

function skillIcon(s) {
  if (s.standard) return "stack";
  return SKILL_ICONS[s.category] || "skill";
}

function skillCard(s) {
  const card = node("article", "skill-card" + (s.enabled === false ? " off" : ""));
  const top = node("div", "skill-card-top");
  const open = node("button", "skill-open", s.standard || s.recommended ? s.label : s.name);
  open.type = "button";
  open.addEventListener("click", () => openSkillDetail(s));
  const who = node("div", "skill-card-id");
  who.append(tile(skillIcon(s)), open);
  top.append(who);
  if (!s.standard && !s.recommended) top.append(skillSwitch(s, renderSkills));
  card.append(top, skillBadges(s), node("p", "skill-desc", s.recommended ? s.summary : s.description));
  if (s.recommended) card.append(node("small", "mem-meta", skillSource(s)), skillAddRow(s));
  if (!s.standard && !s.recommended) card.append(node("small", "mem-meta", `${trn(s.files, "1 Datei", "{0} Dateien")} · ${tr("{0} Text", formatSize(s.size))}`));
  card.addEventListener("click", (event) => { if (!event.target.closest("button")) openSkillDetail(s); });
  return card;
}

// Empfohlene Skills: Hinzufügen mit einem Klick (die Skills sind mitgeliefert und geprüft)
async function addRecommended(s, button) {
  button.disabled = true;
  try {
    await api(`api/skills/recommended/${encodeURIComponent(s.id)}`, { method: "POST" });
    toast(tr("Skill „{0}“ hinzugefügt.", s.label));
    await loadSkills();
    const fresh = skillsUi.data?.recommended.find((r) => r.id === s.id);
    if (skillsUi.mode === "detail" && fresh) openSkillDetail({ ...fresh, recommended: true, categoryLabel: s.categoryLabel });
  } catch (err) { toast(errorText(err, tr("Hinzufügen hat nicht geklappt."))); button.disabled = false; }
}

function skillAddRow(s) {
  const row = node("div", "skill-add");
  if (s.installed) { row.append(node("span", "skill-added", tr("Schon hinzugefügt"))); return row; }
  if (s.taken) { row.append(node("span", "skill-added", tr("Ein Skill mit diesem Namen gibt es schon."))); return row; }
  const add = node("button", "pill primary", tr("Hinzufügen"));
  add.type = "button";
  add.addEventListener("click", (event) => { event.stopPropagation(); addRecommended(s, add); });
  row.append(add);
  return row;
}

// ---- Import mit Vorschau

async function previewSkillFile(file) {
  if (skillsUi.busy) return;
  if (file.size > SKILL_MAX) { skillsUi.status = tr("„{0}“ ist zu groß (höchstens {1} MB).", file.name, SKILL_MAX / 1024 / 1024); renderSkills(); return; }
  skillsUi.busy = true;
  skillsUi.status = tr("Prüfe {0} …", file.name);
  renderSkills();
  try {
    const data = await toBase64(file);
    const preview = await api("api/skills/preview", { method: "POST", body: JSON.stringify({ name: file.name, data }) });
    skillsUi.busy = false;
    skillsGo("preview", { preview: { ...preview, data, file: file.name } });
  } catch (err) {
    skillsUi.busy = false;
    skillsUi.status = `${file.name}: ${errorText(err, tr("Das Skill konnte nicht gelesen werden."))}`;
    renderSkills();
  }
}

// Skill von einem öffentlichen GitHub-Link holen; danach dieselbe Vorschau wie beim Hochladen
async function previewSkillGithub() {
  if (skillsUi.busy) return;
  const url = await openSheet({
    title: tr("Skill von GitHub holen"),
    sub: tr("Link zu einem öffentlichen Skill-Ordner, zum Beispiel https://github.com/besitzer/repo/tree/main/skills/name. Gespeichert wird erst nach der Vorschau."),
    label: tr("GitHub-Link"), value: "", placeholder: "https://github.com/…", ok: tr("Holen"), maxLength: 500,
  });
  if (!url) return;
  skillsUi.busy = true;
  skillsUi.status = tr("Hole das Skill von GitHub …");
  renderSkills();
  try {
    const preview = await api("api/skills/github", { method: "POST", body: JSON.stringify({ url }) });
    skillsUi.busy = false;
    skillsGo("preview", { preview });
  } catch (err) {
    skillsUi.busy = false;
    skillsUi.status = errorText(err, tr("Das Skill konnte nicht von GitHub geholt werden."));
    renderSkills();
  }
}

function renderSkillPreview(wrap) {
  const p = skillsUi.preview;
  skillBack(wrap, tr("Abbrechen"));
  skillHead(wrap, p.name, tr("So sieht das Skill aus. Es wird erst nach „Hinzufügen“ gespeichert."));
  const card = node("section", "skills-panel");
  card.append(node("p", "skills-label", tr("Beschreibung (so sieht die KI es)")), node("p", "skill-desc full", p.description));
  card.append(node("p", "skills-label", tr("Inhalt")));
  const files = node("ul", "skills-files");
  for (const f of p.files) files.append(node("li", "", `${f.path} · ${formatSize(f.size)}`));
  card.append(files);
  if (p.source) card.append(node("p", "skills-hint", tr("Quelle: {0}", p.source)));
  if (p.replaces) card.append(node("p", "skills-warn", tr("Ein Skill mit diesem Namen gibt es schon. Es wird ersetzt.")));
  for (const w of p.warnings) card.append(node("p", "skills-warn", w));
  if (p.skipped.length) {
    const list = node("ul", "skills-files");
    for (const sk of p.skipped.slice(0, 12)) list.append(node("li", "", `${sk.name}: ${sk.reason}`));
    card.append(node("p", "skills-label", tr("Nicht übernommen:")), list);
  }
  if (p.excerpt) card.append(node("p", "skills-label", tr("Anfang der Anleitung")), node("pre", "skill-text", p.excerpt));
  card.append(node("p", "skills-hint", tr("Ein importiertes Skill gilt als fremder Inhalt. Hat die KI eines genutzt, fragt sie vor Änderungen in Home Assistant oder bei GitHub und vor Bildern erst bei dir nach.")));
  const foot = node("div", "skills-buttons");
  const add = node("button", "pill primary", tr("Hinzufügen"));
  add.type = "button";
  const cancel = node("button", "pill ghost", tr("Abbrechen"));
  cancel.type = "button";
  cancel.addEventListener("click", () => skillsGo("list", { preview: null }));
  add.addEventListener("click", async () => {
    add.disabled = true;
    try {
      await api("api/skills", { method: "POST", body: JSON.stringify({ name: p.file, data: p.data }) });
      toast(tr("Skill „{0}“ hinzugefügt.", p.name));
      skillsUi.tab = "mine";
      skillsGo("list", { preview: null });
      await loadSkills();
    } catch (err) { toast(errorText(err, tr("Hinzufügen hat nicht geklappt."))); add.disabled = false; }
  });
  foot.append(add, cancel);
  card.append(foot);
  wrap.append(card);
}

// ---- Selbst schreiben

function renderSkillWrite(wrap) {
  skillBack(wrap, tr("Abbrechen"));
  skillHead(wrap, tr("Neues Skill"), tr("Schreibe auf, wie die KI bei einer bestimmten Aufgabe vorgehen soll. Sie liest die Anleitung erst, wenn die Aufgabe zur Beschreibung passt."));
  const form = node("form", "skills-panel skills-form");
  form.autocomplete = "off";
  const field = (label, hint, control) => {
    const box = node("label", "f-field");
    box.append(node("span", "f-label", label), control, node("span", "f-hint", hint));
    return box;
  };
  const name = node("input", "field");
  name.maxLength = 64;
  name.placeholder = tr("z. B. angebote-schreiben");
  const description = node("textarea", "field area");
  description.rows = 3;
  description.maxLength = 1024;
  description.placeholder = tr("z. B. Wenn ich ein Angebot für einen Kunden brauche");
  const instructions = node("textarea", "field area skills-editor");
  instructions.rows = 14;
  instructions.maxLength = 40000;
  instructions.placeholder = tr("1. Frage nach Kunde und Leistung …");
  form.append(
    field(tr("Name"), tr("Kleinbuchstaben, Ziffern und Bindestriche. Leer lassen: der Name entsteht aus der Beschreibung."), name),
    field(tr("Wann soll die KI es nutzen?"), tr("Das liest die KI immer. Nenne Aufgaben und Stichwörter, bei denen sie das Skill laden soll."), description),
    field(tr("Anleitung"), tr("Schritte, Regeln und Beispiele. Die KI liest das erst, wenn sie das Skill lädt."), instructions),
  );
  const foot = node("div", "skills-buttons");
  const save = node("button", "pill primary", tr("Speichern"));
  save.type = "submit";
  const cancel = node("button", "pill ghost", tr("Abbrechen"));
  cancel.type = "button";
  cancel.addEventListener("click", () => skillsGo("list"));
  foot.append(save, cancel);
  form.append(foot);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!description.value.trim() || !instructions.value.trim()) { toast(tr("Bitte Beschreibung und Anleitung ausfüllen.")); return; }
    save.disabled = true;
    try {
      await api("api/skills/new", { method: "POST", body: JSON.stringify({ name: name.value, description: description.value, instructions: instructions.value }) });
      toast(tr("Skill gespeichert."));
      skillsUi.tab = "mine";
      skillsGo("list");
      await loadSkills();
    } catch (err) { toast(errorText(err, tr("Speichern hat nicht geklappt."))); save.disabled = false; }
  });
  wrap.append(form);
  name.focus();
}

// ---- Ansicht eines Skills

function openSkillDetail(s) {
  skillsGo("detail", { detail: s });
  loadSkillDetail(s);
}

async function loadSkillDetail(s) {
  let info;
  try {
    info = s.standard
      ? { text: (await api(`api/skills/standard/${encodeURIComponent(s.name)}`)).text, files_list: [] }
      : await api(s.recommended ? `api/skills/recommended/${encodeURIComponent(s.id)}` : `api/skills/${s.id}`);
  } catch { info = null; }
  if (skillsUi.mode !== "detail" || skillsUi.detail !== s) return;
  const slot = $("skills-wrap").querySelector(".skills-body");
  if (!slot) return;
  if (!info) { slot.replaceChildren(node("p", "mem-empty", tr("Das Skill ist gerade nicht erreichbar."))); return; }
  const parts = [node("p", "skills-label", s.standard ? tr("Regeln") : tr("Anleitung (SKILL.md)")), node("pre", "skill-text", s.standard ? info.text : info.skill_md)];
  const others = (info.files_list || []).filter((f) => f.path !== "SKILL.md");
  if (others.length) {
    parts.push(node("p", "skills-label", tr("Weitere Dateien")));
    const list = node("div", "skills-filelist");
    for (const f of others) {
      const box = node("details", "skill-more");
      box.append(node("summary", "", `${f.path} · ${formatSize(f.size)}`));
      const pre = node("pre", "skill-text");
      box.append(pre);
      let loaded = false;
      box.addEventListener("toggle", async () => {
        if (!box.open || loaded) return;
        loaded = true;
        pre.textContent = tr("Lädt …");
        try { pre.textContent = (await api(`api/skills/${s.recommended ? "recommended/" + encodeURIComponent(s.id) : s.id}/file?path=${encodeURIComponent(f.path)}`)).text; } catch { loaded = false; pre.textContent = tr("Das Skill ist gerade nicht erreichbar."); }
      });
      list.append(box);
    }
    parts.push(list);
  }
  slot.replaceChildren(...parts);
}

function renderSkillDetail(wrap) {
  const s = skillsUi.detail;
  skillBack(wrap);
  skillHead(wrap, s.standard || s.recommended ? s.label : s.name);
  wrap.lastElementChild.classList.add("with-tile");
  wrap.lastElementChild.prepend(tile(skillIcon(s)));
  const card = node("section", "skills-panel");
  const meta = node("div", "skills-detail-meta");
  meta.append(skillBadges(s));
  if (!s.standard && !s.recommended) {
    const switchBox = node("label", "skills-onoff");
    const rerender = async () => { renderSkills(); loadSkillDetail(s); };
    switchBox.append(skillSwitch(s, rerender), node("span", "", s.enabled ? tr("An") : tr("Aus")));
    meta.append(switchBox);
  }
  if (s.recommended) card.append(meta, node("p", "skill-desc full", s.summary));
  else card.append(meta);
  card.append(node("p", "skills-label", tr("Beschreibung (so sieht die KI es)")), node("p", "skill-desc full", s.description));
  if (s.standard) {
    card.append(node("p", "skills-hint", tr("Mitgeliefert und immer an. Deine eigenen Skills gehen ihnen vor, wenn sie zur Aufgabe passen.")));
  } else if (s.recommended) {
    const source = node("a", "", s.source);
    source.href = s.source;
    source.target = "_blank";
    source.rel = "noopener noreferrer";
    const from = node("p", "skill-desc full");
    from.append(`${skillSource(s)} · ${tr("Lizenz {0}", s.license)} · `, source);
    card.append(node("p", "skills-label", tr("Herkunft")), from, skillAddRow(s));
    card.append(node("p", "skills-hint", tr("Der Inhalt ist aus der Quelle übernommen; der Lizenztext liegt als LICENSE.txt dabei.")));
  } else {
    const tools = node("div", "skills-buttons");
    const exp = node("button", "pill ghost");
    exp.type = "button";
    exp.append(icon("download"), node("span", "", tr("Als .skill sichern")));
    exp.addEventListener("click", async () => {
      try { await downloadFrom(`api/skills/${s.id}/export`, `${s.name}.skill`); } catch { toast(tr("Sichern hat nicht geklappt.")); }
    });
    tools.append(exp, confirmButton(tr("{0} entfernen", s.name), async () => {
      try {
        await api(`api/skills/${s.id}`, { method: "DELETE" });
        toast(tr("Skill „{0}“ entfernt.", s.name));
        skillsGo("list", { detail: null });
        await loadSkills();
      } catch { toast(tr("Entfernen hat nicht geklappt.")); }
    }));
    card.append(tools);
  }
  const body = node("div", "skills-body");
  body.append(node("p", "mem-empty", tr("Lädt …")));
  card.append(body);
  wrap.append(card);
}

// ------------------------------------------------------------------- Konnektoren (Tab in den Anpassungen)

const connUi = {
  data: null, catalog: null, catalogError: "", catalogLoading: false, tab: "mine", mineQuery: "", query: "", category: "all",
  registry: { q: "", items: [], next: "", loading: false, error: "", loaded: false, seq: 0 },
  id: null, form: null, flow: null, setup: null, error: "", loading: false,
};

async function loadConnectors() {
  connUi.loading = true;
  try { connUi.data = await api("api/connectors"); connUi.error = ""; } catch (err) { connUi.data = null; connUi.error = errorText(err, tr("Die Konnektoren sind gerade nicht erreichbar.")); }
  connUi.loading = false;
  if (state.view === "skills") renderSkills();
}

async function loadConnCatalog() {
  if (connUi.catalog || connUi.catalogLoading) return;
  connUi.catalogLoading = true;
  try { connUi.catalog = await api("api/connectors/catalog"); connUi.catalogError = ""; } catch (err) { connUi.catalogError = errorText(err, tr("Der Katalog ist gerade nicht erreichbar.")); }
  connUi.catalogLoading = false;
  if (state.view === "skills") renderSkills();
}

function connKeep(view) {
  const items = connUi.data?.items || [];
  const at = items.findIndex((c) => c.id === view.id);
  if (at >= 0) items[at] = view; else items.push(view);
  return view;
}

function connStatusLabel(c) {
  return { ok: tr("Verbunden"), new: tr("Nicht verbunden"), reauth: tr("Neu anmelden"), error: tr("Fehler") }[c.status] || c.status;
}

function connBadges(c) {
  const row = node("div", "skill-badges");
  row.append(node("span", "skill-badge", c.scope === "global" ? tr("Für alle") : tr("Privat")));
  row.append(node("span", "skill-badge" + (c.status === "ok" ? " ext" : c.status === "new" ? " off" : ""), c.status === "ok" && !c.enabled ? tr("Ausgeschaltet") : connStatusLabel(c)));
  return row;
}

// Kachel mit Logo: eigenes Bild, mitgeliefertes Marken-Logo (weiße Kachel, damit dunkle Logos auch im dunklen Theme lesbar bleiben) oder Anfangsbuchstaben
function connTile(item) {
  const box = node("span", "tile");
  box.setAttribute("aria-hidden", "true");
  const name = item.name || item.label || "";
  let src = "";
  if (item.icon && typeof item.icon === "object") {
    if (item.icon.kind === "custom") src = `api/connectors/${item.id}/icon?v=${item.icon.rev}`;
    else if (item.icon.kind === "brand" && item.icon.slug) src = `static/connector-icons/${encodeURIComponent(item.icon.slug)}.svg`;
  } else if (typeof item.icon === "string" && item.icon) src = `static/connector-icons/${encodeURIComponent(item.icon)}.svg`;
  if (!src) { box.textContent = initials(name); return box; }
  box.classList.add("logo");
  const img = node("img");
  img.src = src;
  img.alt = "";
  img.decoding = "async";
  img.addEventListener("error", () => { box.classList.remove("logo"); box.replaceChildren(); box.textContent = initials(name); });
  box.append(img);
  return box;
}

function connSwitch(on, label, handler) {
  const toggle = node("button", "sched-switch");
  toggle.type = "button";
  toggle.setAttribute("role", "switch");
  toggle.setAttribute("aria-checked", String(on));
  toggle.setAttribute("aria-label", label);
  toggle.append(node("span", "knob"));
  toggle.addEventListener("click", async (event) => {
    event.stopPropagation();
    toggle.disabled = true;
    try { await handler(!on); } catch (err) { toast(errorText(err, tr("Das hat nicht geklappt."))); toggle.disabled = false; }
  });
  return toggle;
}

function connCard(c) {
  const card = node("article", "skill-card" + (c.status === "ok" && !c.enabled ? " off" : ""));
  const top = node("div", "skill-card-top");
  const open = node("button", "skill-open", c.name);
  open.type = "button";
  open.addEventListener("click", () => connOpen(c.id));
  const who = node("div", "skill-card-id");
  who.append(connTile(c), open);
  top.append(who);
  if (c.status === "ok") top.append(connSwitch(c.enabled, c.enabled ? tr("{0} ausschalten", c.name) : tr("{0} einschalten", c.name), async (on) => {
    connKeep(await api(`api/connectors/${c.id}/account`, { method: "PATCH", body: JSON.stringify({ enabled: on }) }));
    renderSkills();
  }));
  card.append(top, connBadges(c));
  if (c.description) card.append(node("p", "skill-desc", c.description));
  const on = c.tools.filter((t) => t.enabled).length;
  card.append(node("small", "mem-meta", c.status === "ok" ? tr("{0} von {1} Werkzeugen an", on, c.tools.length) : c.message || tr("Noch nicht verbunden.")));
  card.addEventListener("click", (event) => { if (!event.target.closest("button")) connOpen(c.id); });
  return card;
}

function connEmpty(title, hint, ...buttons) {
  const box = node("div", "skills-empty");
  box.append(node("p", "", title));
  if (hint) box.append(node("p", "skills-hint", hint));
  box.append(...buttons);
  return box;
}

function connResetButton(reset) {
  const b = node("button", "pill ghost", tr("Suche zurücksetzen"));
  b.type = "button";
  b.addEventListener("click", reset);
  return b;
}

function renderConnectors(wrap) {
  const status = node("p", "skills-status");
  status.setAttribute("role", "status");
  status.textContent = skillsUi.status;
  wrap.append(status);
  const data = connUi.data;
  if (!data) {
    wrap.append(node("p", "mem-empty", connUi.loading ? tr("Lädt …") : connUi.error || tr("Die Konnektoren sind gerade nicht erreichbar.")));
    return;
  }
  const canAdd = data.can_create.private || data.can_create.global;
  if (!canAdd) connUi.tab = "mine";
  if (canAdd) {
    const tools = node("div", "skills-tools");
    const seg = node("div", "seg three");
    for (const [id, label] of [["mine", tr("Meine")], ["discover", tr("Entdecken")], ["community", tr("Community")]]) {
      const b = node("button", "", label);
      b.type = "button";
      b.setAttribute("aria-pressed", String(connUi.tab === id));
      b.addEventListener("click", () => { connUi.tab = id; skillsUi.status = ""; renderSkills(); });
      seg.append(b);
    }
    const add = node("button", "pill primary compact");
    add.type = "button";
    add.setAttribute("aria-haspopup", "menu");
    add.setAttribute("aria-label", tr("Hinzufügen"));
    add.append(icon("plus"), node("span", "", tr("Hinzufügen")));
    add.addEventListener("click", async () => {
      const entries = [
        { value: "catalog", icon: "stack", label: tr("Aus dem Katalog") },
        { value: "registry", icon: "globe", label: tr("Im Register suchen") },
        { value: "own", icon: "edit", label: tr("Selbst eintragen") },
      ];
      const choice = wideScreen() ? await openPopover(add, entries) : await openSheet({ title: tr("Konnektor hinzufügen"), items: entries });
      if (choice === "catalog") { connUi.tab = "discover"; renderSkills(); }
      else if (choice === "registry") { connUi.tab = "community"; renderSkills(); }
      else if (choice === "own") connForm(null);
    });
    tools.append(seg, add);
    wrap.append(tools);
  }
  if (connUi.tab === "discover") renderConnDiscover(wrap);
  else if (connUi.tab === "community") renderConnCommunity(wrap);
  else renderConnMine(wrap, canAdd);
  wrap.append(node("p", "skills-note", tr("Was ein Konnektor liefert (Mails, Dokumente, Tickets), gilt als fremder Inhalt. Änderungen bei einem Dienst bestätigst du im Chat.")));
}

// Meine: eigene Konnektoren zuerst, danach die für alle freigegebenen
function renderConnMine(wrap, canAdd) {
  const data = connUi.data;
  wrap.append(node("p", "skills-hint", tr("Konnektoren verbinden die KI mit Diensten außerhalb von Home Assistant, zum Beispiel Mail, Kalender oder dein Überwachungssystem.")));
  const filter = node("div", "skills-filter");
  const search = searchInput(tr("Konnektoren durchsuchen"), connUi.mineQuery);
  filter.append(search);
  const count = node("p", "skills-count");
  count.setAttribute("role", "status");
  const body = node("div", "skills-mine");
  wrap.append(filter, count, body);
  const update = () => {
    const q = connUi.mineQuery;
    const hits = data.items.filter((c) => wordsMatch(q, `${c.name} ${c.description} ${connStatusLabel(c)}`));
    body.replaceChildren();
    count.textContent = q.trim() ? trn(hits.length, "1 Konnektor", "{0} Konnektoren") : "";
    if (!data.items.length) {
      if (canAdd) {
        const go = node("button", "pill ghost", tr("Konnektoren entdecken"));
        go.type = "button";
        go.addEventListener("click", () => { connUi.tab = "discover"; renderSkills(); });
        body.append(connEmpty(tr("Noch kein Konnektor."), tr("Such dir bei „Entdecken“ einen Dienst aus oder trage über „Hinzufügen“ einen eigenen MCP-Server ein."), go));
      } else body.append(connEmpty(tr("Noch kein Konnektor."), tr("Die Administration hat noch keinen Konnektor für alle freigegeben.")));
      return;
    }
    if (!hits.length) {
      body.append(connEmpty(tr("Nichts gefunden."), tr("Versuch es mit einem anderen Wort."), connResetButton(() => { connUi.mineQuery = ""; search.value = ""; update(); search.focus(); })));
      return;
    }
    for (const [scope, title] of [["private", tr("Meine eigenen")], ["global", tr("Für alle freigegeben")]]) {
      const group = hits.filter((c) => c.scope === scope);
      if (!group.length) continue;
      if (hits.some((c) => c.scope !== scope)) body.append(node("h3", "skills-section", title));
      const grid = node("div", "skills-grid");
      for (const c of group) grid.append(connCard(c));
      body.append(grid);
    }
  };
  search.addEventListener("input", () => { connUi.mineQuery = search.value; update(); });
  update();
}

// ---- Entdecken: Katalog mit Suche und Kategorien

function renderConnDiscover(wrap) {
  wrap.append(node("p", "skills-hint", tr("Dienste, für die ich die Adresse und die Anmeldung kenne. Mit „Hinzufügen“ landen sie bei „Meine“; verbunden wird danach mit einem Klick.")));
  const cat = connUi.catalog;
  if (!cat) {
    wrap.append(node("p", "mem-empty", connUi.catalogError || tr("Lädt …")));
    loadConnCatalog();
    return;
  }
  const have = new Map(connUi.data.items.filter((c) => c.catalog_id).map((c) => [c.catalog_id, c]));
  const cats = new Map(cat.categories.map((c) => [c.id, c.label]));
  const all = cat.connectors.map((e) => ({ ...e, categoryLabel: cats.get(e.category) || "", haystack: `${e.label} ${e.provider} ${e.summary} ${cats.get(e.category) || ""}` }))
    .sort((a, b) => a.label.localeCompare(b.label, kiLocale));
  const controls = node("div", "skills-filter");
  const search = searchInput(tr("Dienste durchsuchen"), connUi.query);
  controls.append(search);
  const chips = node("div", "skills-cats");
  chips.setAttribute("role", "group");
  chips.setAttribute("aria-label", tr("Kategorien"));
  const count = node("p", "skills-count");
  count.setAttribute("role", "status");
  const grid = node("div", "skills-grid");
  wrap.append(controls, chips, count, grid);
  const update = () => {
    const hits = all.filter((e) => wordsMatch(connUi.query, e.haystack));
    const per = new Map();
    for (const e of hits) per.set(e.category, (per.get(e.category) || 0) + 1);
    if (connUi.category !== "all" && !cats.has(connUi.category)) connUi.category = "all";
    chips.replaceChildren();
    for (const [id, label] of [["all", tr("Alle")], ...cats]) {
      const n = id === "all" ? hits.length : per.get(id) || 0;
      const chip = node("button", "skills-cat", `${label} · ${n.toLocaleString(kiLocale)}`);
      chip.type = "button";
      chip.setAttribute("aria-pressed", String(connUi.category === id));
      if (!n && connUi.category !== id) chip.disabled = true;
      chip.addEventListener("click", () => { connUi.category = id; update(); });
      chips.append(chip);
    }
    const shown = hits.filter((e) => connUi.category === "all" || e.category === connUi.category);
    grid.replaceChildren();
    if (!shown.length) {
      grid.append(connEmpty(tr("Nichts gefunden."), tr("Versuch es mit einem anderen Wort oder wähle eine andere Kategorie."), connResetButton(() => { connUi.query = ""; connUi.category = "all"; search.value = ""; update(); search.focus(); })));
      return;
    }
    for (const e of shown) grid.append(connCatalogCard(e, have.get(e.id)));
  };
  search.addEventListener("input", () => { connUi.query = search.value; update(); });
  update();
}

function connCatalogCard(e, installed) {
  const card = node("article", "skill-card");
  const top = node("div", "skill-card-top");
  const open = node("button", "skill-open", e.label);
  open.type = "button";
  const go = () => (installed ? connOpen(installed.id) : connSetup(e));
  open.addEventListener("click", go);
  const who = node("div", "skill-card-id");
  who.append(connTile(e), open);
  top.append(who);
  const badges = node("div", "skill-badges");
  badges.append(node("span", "skill-badge", e.categoryLabel));
  if (e.preview) badges.append(node("span", "skill-badge off", tr("Vorschau")));
  if (e.kind === "guide") badges.append(node("span", "skill-badge off", tr("Anleitung")));
  card.append(top, badges, node("p", "skill-desc", e.summary), node("small", "mem-meta", tr("von {0}", e.provider)));
  const row = node("div", "skill-add");
  if (installed) row.append(node("span", "skill-added", tr("Schon hinzugefügt")));
  else {
    const add = node("button", "pill primary", e.kind === "guide" ? tr("Anleitung ansehen") : tr("Hinzufügen"));
    add.type = "button";
    add.addEventListener("click", (event) => { event.stopPropagation(); connSetup(e); });
    row.append(add);
  }
  card.append(row);
  card.addEventListener("click", (event) => { if (!event.target.closest("button")) go(); });
  return card;
}

// ---- Einrichten aus dem Katalog

function connSetup(entry) {
  connUi.setup = entry;
  skillsGo("connector-setup");
}

function connSourceHint(e) {
  if (e.source === "list") return tr("Die Adresse stammt aus der Liste der Konnektoren von Anthropic. Ich habe sie nicht selbst ausprobiert.");
  if (e.source === "known") return tr("Die Adresse ist mir bekannt, ich konnte sie aber nicht selbst prüfen. Klappt die Anmeldung nicht, steht der Grund in der Meldung.");
  return "";
}

function copyField(value) {
  const row = node("div", "conn-copy");
  const input = node("input", "field");
  input.readOnly = true;
  input.value = value;
  input.addEventListener("focus", () => input.select());
  const copy = node("button", "pill ghost");
  copy.type = "button";
  copy.append(icon("copy"), node("span", "", tr("Kopieren")));
  copy.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(value); toast(tr("Kopiert.")); } catch { input.select(); toast(tr("Zum Kopieren Strg+C drücken.")); }
  });
  row.append(input, copy);
  return row;
}

function renderConnectorSetup(wrap) {
  const e = connUi.setup;
  const data = connUi.data;
  if (!e || !data) { skillsGo("list"); return; }
  const guide = connUi.catalog?.guides?.[e.guide];
  const can = data.can_create;
  const redirect = data.redirect_uri || "";
  skillBack(wrap, tr("Zurück zu den Konnektoren"));
  skillHead(wrap, e.label, e.summary);
  wrap.lastElementChild.classList.add("with-tile");
  wrap.lastElementChild.prepend(connTile(e));
  const card = node("section", "skills-panel skills-form");
  if (e.note) card.append(node("p", "skills-warn", e.note));
  const hint = connSourceHint(e);
  if (hint) card.append(node("p", "skills-hint", hint));
  if (guide) {
    if (guide.warn) card.append(node("p", "skills-warn", guide.warn));
    card.append(node("p", "skills-label", e.kind === "guide" ? tr("So gehst du vor") : tr("Vorbereitung beim Dienst")));
    const steps = node("ol", "conn-steps");
    for (const line of guide.steps) steps.append(node("li", "", line.replaceAll("{redirect}", redirect || tr("(Adresse dieses Add-ons) /connectors/callback"))));
    card.append(steps);
    if (guide.steps.some((s) => s.includes("{redirect}")) && redirect) card.append(field(tr("Weiterleitungs-URI"), copyField(redirect), tr("Muss beim Dienst genau so eingetragen sein."), "div"));
  }
  if (e.apis?.length) card.append(node("p", "skills-hint", tr("APIs, die du bei Google einschalten musst: {0}", e.apis.join(", "))));
  if (e.docs) {
    const link = node("a", "skills-link", tr("Dokumentation des Anbieters"));
    link.href = e.docs;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    card.append(link);
  }

  const foot = node("div", "skills-buttons");
  const cancel = node("button", "pill ghost", tr("Abbrechen"));
  cancel.type = "button";
  cancel.addEventListener("click", () => skillsGo("list"));
  if (e.kind === "guide") {
    const next = node("button", "pill primary", tr("Weiter"));
    next.type = "button";
    next.addEventListener("click", () => connForm({ scope: "private", name: e.label, description: e.summary, url: "", auth: e.auth, mode: "per_user" }));
    foot.append(next, cancel);
    card.append(foot);
    wrap.append(card);
    return;
  }

  const form = node("form", "skills-form conn-setup");
  form.noValidate = true;
  const name = node("input", "field");
  name.maxLength = 40;
  name.value = e.label;
  const scope = node("select", "field");
  scope.append(new Option(tr("Privat: nur ich"), "private"), new Option(tr("Für alle: jede Person kann ihn nutzen"), "global"));
  scope.disabled = !can.global || !can.private;
  scope.value = can.private ? "private" : "global";
  form.append(field(tr("Name"), name));
  if (can.global && can.private) form.append(field(tr("Wer darf ihn nutzen?"), scope));
  let clientId, clientSecret, scopes;
  if (e.pre_registered) {
    clientId = node("input", "field");
    clientId.maxLength = 300;
    clientSecret = node("input", "field");
    clientSecret.type = "password";
    clientSecret.maxLength = 500;
    scopes = node("input", "field");
    scopes.maxLength = 400;
    scopes.value = e.scopes || "";
    scopes.placeholder = tr("durch Leerzeichen getrennt");
    form.append(
      field(tr("Client-ID"), clientId, tr("Aus der App, die du beim Dienst angelegt hast.")),
      field(tr("Client-Secret"), clientSecret, tr("Wird verschlüsselt im Add-on gespeichert und nie wieder angezeigt.")),
      field(tr("Berechtigungen (Scopes)"), scopes, e.scopes_from_user ? tr("Hier musst du die Berechtigungen laut Dokumentation des Anbieters eintragen.") : tr("Vorgabe laut Anbieter; ändere sie nur, wenn du es genau weißt.")),
    );
  } else if (e.auth === "bearer" || e.auth === "header") {
    form.append(node("p", "skills-hint", tr("Das Token trägst du nach dem Hinzufügen ein.")));
  }
  const save = node("button", "pill primary", tr("Hinzufügen"));
  save.type = "submit";
  foot.append(save, cancel);
  form.append(foot);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!name.value.trim()) { toast(tr("Bitte einen Namen eingeben.")); return; }
    if (e.pre_registered && !clientId.value.trim()) { toast(tr("Bitte die Client-ID eintragen.")); return; }
    if (e.scopes_from_user && !scopes.value.trim()) { toast(tr("Bitte die Berechtigungen eintragen.")); return; }
    const body = { catalog_id: e.id, name: name.value.trim(), scope: can.global && can.private ? scope.value : can.private ? "private" : "global" };
    if (e.pre_registered) {
      body.client_id = clientId.value.trim();
      body.scopes = scopes.value.trim();
      if (clientSecret.value) body.client_secret = clientSecret.value;
    }
    save.disabled = true;
    try {
      const view = connKeep(await api("api/connectors", { method: "POST", body: JSON.stringify(body) }));
      toast(tr("Konnektor „{0}“ hinzugefügt.", view.name));
      connUi.setup = null;
      connOpen(view.id);
    } catch (err) { toast(errorText(err, tr("Hinzufügen hat nicht geklappt."))); save.disabled = false; }
  });
  card.append(form);
  wrap.append(card);
  (e.pre_registered ? clientId : name).focus();
}

// ---- Community: Suche im offenen MCP-Register

async function connRegistrySearch(more, paint) {
  const r = connUi.registry;
  const seq = ++r.seq;
  r.loading = true;
  r.error = "";
  if (!more) { r.items = []; r.next = ""; }
  paint();
  try {
    const out = await api(`api/connectors/registry?q=${encodeURIComponent(r.q)}${more && r.next ? `&cursor=${encodeURIComponent(r.next)}` : ""}`);
    if (seq !== r.seq) return;
    const seen = new Set(r.items.map((i) => i.id));
    r.items = [...r.items, ...out.items.filter((i) => !seen.has(i.id))];
    r.next = out.next || "";
    r.loaded = true;
  } catch (err) {
    if (seq !== r.seq) return;
    r.error = errorText(err, tr("Die Suche hat nicht geklappt."));
  }
  r.loading = false;
  paint();
}

function connRegistryCard(item) {
  const card = node("article", "skill-card");
  const top = node("div", "skill-card-top");
  const who = node("div", "skill-card-id");
  const title = node("span", "skill-open static", item.name);
  who.append(connTile({ name: item.name }), title);
  top.append(who);
  const badges = node("div", "skill-badges");
  badges.append(node("span", "skill-badge off", item.auth === "none" ? tr("ohne Anmeldung") : tr("Token nötig")));
  let host = "";
  try { host = new URL(item.url).host; } catch { host = ""; }
  card.append(top, badges, node("p", "skill-desc", item.description || tr("Keine Beschreibung.")), node("small", "mem-meta", host));
  const row = node("div", "skill-add");
  const add = node("button", "pill primary", tr("Hinzufügen"));
  add.type = "button";
  add.addEventListener("click", () => connForm({
    scope: "private", name: item.name, description: item.description.slice(0, 300), url: item.url, auth: item.auth, header_name: item.header_name,
    mode: "per_user", icon_url: item.icon_url, from_registry: true,
  }));
  row.append(add);
  if (item.website) {
    const link = node("a", "skills-link", tr("Webseite"));
    link.href = item.website;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    row.append(link);
  }
  card.append(row);
  return card;
}

function renderConnCommunity(wrap) {
  const r = connUi.registry;
  wrap.append(node("p", "skills-hint", tr("Hier suchst du im offenen Register für MCP-Server. Es zeigt nur Server, die du über das Internet erreichst.")));
  wrap.append(node("p", "skills-warn", tr("Nicht geprüft: Im Register kann jede Person etwas eintragen. Füge nur hinzu, was du kennst und wem du vertraust. Alles, was ein solcher Server liefert, gilt als fremder Inhalt.")));
  const filter = node("div", "skills-filter");
  const search = searchInput(tr("Im Register suchen"), r.q);
  filter.append(search);
  const body = node("div", "skills-mine");
  wrap.append(filter, body);
  const paint = () => {
    body.replaceChildren();
    if (r.error) body.append(connEmpty(r.error, "", (() => { const b = node("button", "pill ghost", tr("Noch einmal versuchen")); b.type = "button"; b.addEventListener("click", () => connRegistrySearch(false, paint)); return b; })()));
    else if (r.loaded && !r.items.length && !r.loading) body.append(connEmpty(tr("Nichts gefunden."), tr("Versuch es mit einem anderen Wort.")));
    if (r.items.length) {
      const grid = node("div", "skills-grid");
      for (const item of r.items) grid.append(connRegistryCard(item));
      body.append(grid);
    }
    if (r.loading) body.append(node("p", "mem-empty", tr("Suche …")));
    else if (r.next && !r.error) {
      const more = node("button", "pill ghost", tr("Mehr laden"));
      more.type = "button";
      more.addEventListener("click", () => connRegistrySearch(true, paint));
      body.append(more);
    }
  };
  let timer = 0;
  search.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => { r.q = search.value.trim(); connRegistrySearch(false, paint); }, 400);
  });
  paint();
  if (!r.loaded && !r.loading && !r.error) connRegistrySearch(false, paint);
}

function connOpen(id) {
  connUi.id = id;
  connUi.flow = null;
  skillsGo("connector");
}

// ---- Ansicht eines Konnektors

function renderConnectorDetail(wrap) {
  const c = connUi.data?.items.find((x) => x.id === connUi.id);
  if (!c) { skillsGo("list"); return; }
  skillBack(wrap);
  skillHead(wrap, c.name);
  wrap.lastElementChild.classList.add("with-tile");
  wrap.lastElementChild.prepend(connTile(c));
  const card = node("section", "skills-panel");
  const meta = node("div", "skills-detail-meta");
  meta.append(connBadges(c));
  if (c.status === "ok") {
    const box = node("label", "skills-onoff");
    box.append(connSwitch(c.enabled, c.enabled ? tr("{0} ausschalten", c.name) : tr("{0} einschalten", c.name), async (on) => {
      connKeep(await api(`api/connectors/${c.id}/account`, { method: "PATCH", body: JSON.stringify({ enabled: on }) }));
      renderSkills();
    }), node("span", "", c.enabled ? tr("An") : tr("Aus")));
    meta.append(box);
  }
  card.append(meta);
  if (c.description) card.append(node("p", "skill-desc full", c.description));
  if (c.can_edit && c.url) card.append(node("p", "skills-label", tr("Adresse")), node("p", "skill-desc full", c.url));
  if (c.message && c.status !== "ok") card.append(node("p", "skills-warn", c.message));
  else if (c.message) card.append(node("p", "skills-hint", c.message));

  const actions = node("div", "skills-buttons");
  const shot = (label, iconName, run, primary = false) => {
    const b = node("button", "pill " + (primary ? "primary" : "ghost"));
    b.type = "button";
    if (iconName) b.append(icon(iconName));
    b.append(node("span", "", label));
    b.addEventListener("click", async () => {
      b.disabled = true;
      try { await run(); } catch (err) { skillsUi.status = errorText(err, tr("Das hat nicht geklappt.")); await loadConnectors(); }
      b.disabled = false;
    });
    return b;
  };
  if (c.status !== "ok") {
    if (c.auth === "oauth") actions.append(shot(c.status === "reauth" ? tr("Neu anmelden") : tr("Anmelden"), "globe", () => connStartOAuth(c), true));
    else if (!c.needs_secret) actions.append(shot(tr("Verbinden"), "bolt", () => connConnect(c, ""), true));
  }
  if (c.status === "ok") actions.append(shot(tr("Neu einlesen"), "fold", async () => {
    connKeep(await api(`api/connectors/${c.id}/refresh`, { method: "POST" }));
    skillsUi.status = tr("Die Werkzeuge sind neu eingelesen.");
    renderSkills();
  }));
  if (c.status !== "new") actions.append(shot(tr("Trennen"), "logout", async () => {
    await api(`api/connectors/${c.id}/disconnect`, { method: "POST" });
    skillsUi.status = tr("Getrennt.");
    await loadConnectors();
  }));
  if (c.can_edit) {
    actions.append(shot(tr("Bearbeiten"), "edit", async () => connForm(c)));
    actions.append(confirmButton(tr("{0} entfernen", c.name), async () => {
      try {
        await api(`api/connectors/${c.id}`, { method: "DELETE" });
        toast(tr("Konnektor „{0}“ entfernt.", c.name));
        skillsGo("list");
        await loadConnectors();
      } catch (err) { toast(errorText(err, tr("Entfernen hat nicht geklappt."))); }
    }));
  }
  if (actions.children.length) card.append(actions);
  if (c.needs_secret && c.status !== "ok") card.append(connSecretForm(c));
  if (connUi.flow && connUi.flow.id === c.id) card.append(connFlowPanel(c));

  if (c.status === "ok") card.append(connToolList(c));
  wrap.append(card);
}

function connSecretForm(c) {
  const form = node("form", "skills-form conn-secret");
  form.autocomplete = "off";
  const input = node("input", "field");
  input.type = "password";
  input.autocomplete = "off";
  input.maxLength = 4000;
  input.placeholder = c.auth === "header" ? tr("Schlüssel") : tr("Token");
  const go = node("button", "pill primary", tr("Verbinden"));
  go.type = "submit";
  form.append(field(c.auth === "header" ? tr("Schlüssel") : tr("Zugangs-Token"), input, tr("Wird verschlüsselt im Add-on gespeichert und nie wieder angezeigt.")), go);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    go.disabled = true;
    try { await connConnect(c, input.value); } catch (err) { skillsUi.status = errorText(err, tr("Das hat nicht geklappt.")); await loadConnectors(); }
  });
  return form;
}

async function connConnect(c, secret) {
  connKeep(await api(`api/connectors/${c.id}/connect`, { method: "POST", body: JSON.stringify({ secret }) }));
  skillsUi.status = tr("Verbunden.");
  renderSkills();
}

async function connStartOAuth(c) {
  const flow = await api(`api/connectors/${c.id}/oauth/start`, { method: "POST" });
  connUi.flow = { id: c.id, ...flow };
  renderSkills();
  if (!flow.manual) connWatch(c.id);
}

// Mit Domain-Zugang kehrt der Browser von selbst zurück: ab und zu nachsehen, ob die Anmeldung angekommen ist
function connWatch(id) {
  let tries = 0;
  const timer = setInterval(async () => {
    tries += 1;
    if (state.view !== "skills" || connUi.id !== id || !connUi.flow || tries > 60) { clearInterval(timer); return; }
    try {
      const data = await api("api/connectors");
      const now = data.items.find((x) => x.id === id);
      if (now && now.status === "ok") {
        clearInterval(timer);
        connUi.data = data;
        connUi.flow = null;
        skillsUi.status = tr("Verbunden.");
        renderSkills();
      }
    } catch { /* beim nächsten Mal noch einmal */ }
  }, 3000);
}

function connFlowPanel(c) {
  const flow = connUi.flow;
  const box = node("div", "conn-flow");
  const link = node("a", "pill primary", tr("Beim Dienst anmelden"));
  link.href = flow.url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  box.append(
    node("p", "skills-label", tr("Anmeldung")),
  );
  if (flow.manual) {
    const steps = node("ol", "conn-steps");
    for (const line of [tr("Öffne den Link und melde dich an."), tr("Am Ende zeigt der Browser eine Fehlerseite (localhost). Das ist normal."), tr("Kopiere die ganze Adresse aus der Adresszeile und füge sie unten ein.")]) steps.append(node("li", "", line));
    box.append(steps);
  } else {
    box.append(node("p", "skills-hint", tr("Öffne den Link, melde dich an und stimme zu. Danach geht es hier von selbst weiter.")));
  }
  box.append(link);
  if (flow.manual) {
    const form = node("form", "skills-form");
    form.autocomplete = "off";
    const input = node("input", "field");
    input.placeholder = "http://localhost/connectors/callback?code=…";
    input.maxLength = 3000;
    const done = node("button", "pill primary", tr("Anmeldung abschließen"));
    done.type = "submit";
    form.append(field(tr("Adresse aus dem Browser"), input), done);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!input.value.trim()) return;
      done.disabled = true;
      try {
        connKeep(await api("api/connectors/oauth/finish", { method: "POST", body: JSON.stringify({ redirect_url: input.value.trim() }) }));
        connUi.flow = null;
        skillsUi.status = tr("Verbunden.");
      } catch (err) { skillsUi.status = errorText(err, tr("Das hat nicht geklappt.")); connUi.flow = null; }
      renderSkills();
    });
    box.append(form);
  } else {
    const cancel = node("button", "pill ghost", tr("Abbrechen"));
    cancel.type = "button";
    cancel.addEventListener("click", () => { connUi.flow = null; renderSkills(); });
    box.append(cancel);
  }
  return box;
}

function connToolList(c) {
  const wrap = node("div", "conn-tools");
  if (!c.tools.length) { wrap.append(node("p", "skills-hint", tr("Der Server meldet keine Werkzeuge."))); return wrap; }
  const confirm = connUi.data.write_confirm === "ask";
  const part = (title, hint, list) => {
    if (!list.length) return;
    wrap.append(node("p", "skills-label", title), node("p", "skills-hint", hint));
    for (const t of list) {
      const row = node("div", "conn-tool");
      const text = node("div", "conn-tool-text");
      text.append(node("strong", "", t.title), node("small", "mem-meta", t.description || t.name));
      row.append(text, connSwitch(t.enabled, t.enabled ? tr("{0} ausschalten", t.title) : tr("{0} einschalten", t.title), async (on) => {
        connKeep(await api(`api/connectors/${c.id}/account`, { method: "PATCH", body: JSON.stringify({ tools: { [t.name]: on } }) }));
        renderSkills();
      }));
      wrap.append(row);
    }
  };
  part(tr("Lesen"), tr("Diese Werkzeuge verändern nichts. Die KI darf sie ohne Rückfrage nutzen."), c.tools.filter((t) => t.read_only));
  part(tr("Ändern"), confirm ? tr("Diese Werkzeuge können etwas verändern oder senden. Sie sind erst an, wenn du sie einschaltest, und die KI fragt vor jeder Änderung im Chat nach.") : tr("Diese Werkzeuge können etwas verändern oder senden. Sie sind erst an, wenn du sie einschaltest."), c.tools.filter((t) => !t.read_only));
  return wrap;
}

// ---- Logo wählen: Link oder Upload (nur Rasterbilder, höchstens 128 kB; das prüft der Server noch einmal)

const ICON_MAX = 128 * 1024;
const ICON_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp"];

function connLogoField(c, nameInput) {
  const box = node("div", "conn-logo");
  const brand = c.icon?.kind === "brand" ? c.icon : null;
  let tileBox = connTile(c);
  let data = "";
  let clear = false;
  const link = node("input", "field");
  link.type = "url";
  link.maxLength = 500;
  link.placeholder = "https://…/logo.png";
  link.value = c.icon_url || "";
  const initialLink = link.value;
  const picker = node("input");
  picker.type = "file";
  picker.accept = ICON_TYPES.join(",");
  picker.hidden = true;
  const upload = node("button", "pill ghost");
  upload.type = "button";
  upload.append(icon("upload"), node("span", "", tr("Bild hochladen")));
  upload.addEventListener("click", () => picker.click());
  const remove = node("button", "pill ghost", tr("Logo entfernen"));
  remove.type = "button";
  const hint = node("p", "f-hint", tr("Ein Link wird beim Speichern abgerufen. Oder lade ein Bild hoch: PNG, JPEG, GIF oder WebP, höchstens 128 kB. Ohne Logo zeigt die Kachel die Anfangsbuchstaben."));
  const swap = (next) => { tileBox.replaceWith(next); tileBox = next; };
  const showRemove = () => { remove.hidden = !(data || link.value.trim() || (c.icon?.kind === "custom" && !clear)); };
  picker.addEventListener("change", () => {
    const file = picker.files[0];
    picker.value = "";
    if (!file) return;
    if (!ICON_TYPES.includes(file.type)) { toast(tr("Das Logo muss ein PNG-, JPEG-, GIF- oder WebP-Bild sein.")); return; }
    if (file.size > ICON_MAX) { toast(tr("Das Logo ist zu groß (höchstens {0} kB).", ICON_MAX / 1024)); return; }
    const reader = new FileReader();
    reader.onload = () => {
      data = String(reader.result || "");
      clear = false;
      link.value = "";
      const preview = node("span", "tile logo");
      preview.setAttribute("aria-hidden", "true");
      const img = node("img");
      img.alt = "";
      img.src = data;
      preview.append(img);
      swap(preview);
      showRemove();
    };
    reader.onerror = () => toast(tr("Das Logo konnte nicht gelesen werden."));
    reader.readAsDataURL(file);
  });
  link.addEventListener("input", () => { if (link.value.trim()) { data = ""; clear = false; } showRemove(); });
  remove.addEventListener("click", () => {
    data = "";
    link.value = "";
    clear = true;
    swap(connTile({ name: nameInput.value || c.name, icon: brand || {} }));
    showRemove();
  });
  const controls = node("div", "conn-logo-controls");
  controls.append(link, node("div", "skills-buttons", ""), hint);
  controls.children[1].append(upload, remove);
  box.append(tileBox, controls, picker);
  showRemove();
  return {
    el: box,
    value() {
      if (data) return { icon_data: data };
      const url = link.value.trim();
      if (url) return c.from_registry && url === initialLink ? { icon_url: url, icon_best_effort: true } : { icon_url: url };
      return clear ? { clear_icon: true } : {};
    },
  };
}

// ---- Anlegen und Bearbeiten

function connForm(c) {
  connUi.form = c ? { ...c } : { scope: "private", name: "", description: "", url: "", auth: "none", mode: "per_user" };
  skillsGo("connector-form");
}

function renderConnectorForm(wrap) {
  const c = connUi.form;
  const editing = !!c.id;
  const can = connUi.data.can_create;
  skillBack(wrap, tr("Abbrechen"));
  skillHead(wrap, editing ? tr("Konnektor bearbeiten") : tr("Neuer Konnektor"), tr("Verbinde einen MCP-Server (Streamable HTTP). Die Adresse endet oft auf „/mcp“."));
  const form = node("form", "skills-panel skills-form");
  form.autocomplete = "off";
  form.noValidate = true;
  if (c.from_registry) form.append(node("p", "skills-warn", tr("Diese Angaben stammen aus dem Register und sind nicht geprüft. Die Anmeldeart kann falsch sein: Verlangt der Server eine Anmeldung, wähle „Anmeldung beim Dienst (OAuth)“.")));
  const text = (value, max, placeholder = "") => {
    const i = node("input", "field");
    i.maxLength = max;
    i.value = value || "";
    i.placeholder = placeholder;
    return i;
  };
  const select = (options, value) => {
    const s = node("select", "field");
    for (const [v, label] of options) s.append(new Option(label, v));
    s.value = value;
    return s;
  };
  const name = text(c.name, 40, tr("z. B. Zabbix"));
  const description = text(c.description, 300, tr("Wofür ist das gut? (optional)"));
  const logo = connLogoField(c, name);
  const url = text(c.url, 500, "https://…/mcp");
  const scope = select([["private", tr("Privat: nur ich")], ["global", tr("Für alle: jede Person kann ihn nutzen")]], c.scope);
  scope.disabled = editing || !can.global;
  const auth = select([["none", tr("Keine Anmeldung")], ["bearer", tr("Token (Bearer)")], ["header", tr("Schlüssel in einem Header")], ["oauth", tr("Anmeldung beim Dienst (OAuth)")]], c.auth);
  const header = text(c.header_name, 60, "X-API-Key");
  const mode = select([["per_user", tr("Jede Person meldet sich selbst an")], ["shared", tr("Ein gemeinsamer Zugang für alle")]], c.mode || "per_user");
  const shared = text("", 4000);
  shared.type = "password";
  shared.placeholder = c.has_shared_secret ? tr("gespeichert; leer lassen, um ihn zu behalten") : tr("Token oder Schlüssel");
  const local = node("input");
  local.type = "checkbox";
  local.checked = !!c.local_ok;
  const clientId = text(c.client_id, 300);
  const clientSecret = text("", 500);
  clientSecret.type = "password";
  clientSecret.placeholder = c.has_client_secret ? tr("gespeichert; leer lassen, um es zu behalten") : "";
  const scopes = text(c.scopes, 400, tr("durch Leerzeichen getrennt, leer = Vorgabe des Dienstes"));
  const authEndpoint = text(c.authorization_endpoint, 500, "https://…/authorize");
  const tokenEndpoint = text(c.token_endpoint, 500, "https://…/token");
  const params = node("textarea", "field area");
  params.rows = 3;
  params.maxLength = 800;
  params.placeholder = "access_type=offline\nprompt=consent";
  params.value = Object.entries(c.auth_params || {}).map(([k, v]) => `${k}=${v}`).join("\n");

  const rows = {
    scope: field(tr("Wer darf ihn nutzen?"), scope, editing ? tr("Lässt sich nach dem Anlegen nicht mehr ändern.") : can.global ? "" : tr("Für alle freigeben darf nur eine Person mit der Stufe „global“.")),
    header: field(tr("Name des Headers"), header, tr("In diesem Header sendet die KI den Schlüssel, z. B. X-API-Key.")),
    mode: field(tr("Zugang"), mode, tr("Bei „gemeinsam“ hinterlegst du den Zugang einmal; alle nutzen ihn, ohne ihn zu sehen.")),
    shared: field(tr("Gemeinsamer Zugang"), shared, tr("Wird verschlüsselt gespeichert und nie wieder angezeigt.")),
    local: field(tr("Heimnetz"), (() => { const l = node("label", "conn-check"); l.append(local, node("span", "", tr("Adresse im Heimnetz oder ohne https erlauben"))); return l; })(), tr("Nur für Adressen, die du kennst und kontrollierst. Das Add-on spricht dann auch Geräte in deinem Netz an.")),
  };
  rows.local.hidden = !!connUi.data.allow_private;
  const oauthBox = node("details", "skill-more conn-oauth");
  oauthBox.open = !!(c.client_id || c.authorization_endpoint);
  oauthBox.append(
    node("summary", "", tr("Erweitert: eigene App beim Dienst (OAuth)")),
    node("p", "skills-hint", tr("Ohne diese Angaben meldet sich das Add-on beim Dienst selbst an, wenn der das anbietet. Dienste wie Google verlangen eine eigene App: Trage deren Client-ID und das Secret ein.")),
    field(tr("Client-ID"), clientId), field(tr("Client-Secret"), clientSecret), field(tr("Berechtigungen (Scopes)"), scopes),
    field(tr("Anmelde-Adresse"), authEndpoint, tr("Nur nötig, wenn der Dienst sie nicht selbst mitteilt.")), field(tr("Token-Adresse"), tokenEndpoint),
    field(tr("Zusätzliche Angaben"), params, tr("Eine pro Zeile als name=wert.")),
  );

  const sync = () => {
    const global = scope.value === "global";
    rows.header.hidden = auth.value !== "header";
    rows.mode.hidden = !(global && auth.value !== "oauth");
    rows.shared.hidden = rows.mode.hidden || mode.value !== "shared";
    rows.local.hidden = !can.global;
    oauthBox.hidden = auth.value !== "oauth";
  };
  for (const el of [scope, auth, mode]) el.addEventListener("change", sync);
  form.append(
    field(tr("Name"), name), field(tr("Beschreibung"), description), field(tr("Logo"), logo.el, "", "div"), field(tr("Adresse des MCP-Servers"), url, connUi.data.allow_private ? tr("Auch Adressen im Heimnetz und mit http sind erlaubt.") : tr("Aus Sicherheitsgründen nur https und öffentliche Adressen, außer du erlaubst unten das Heimnetz.")),
    rows.scope, field(tr("Anmeldung"), auth), rows.header, rows.mode, rows.shared, oauthBox, rows.local,
  );
  const foot = node("div", "skills-buttons");
  const save = node("button", "pill primary", tr("Speichern"));
  save.type = "submit";
  const cancel = node("button", "pill ghost", tr("Abbrechen"));
  cancel.type = "button";
  cancel.addEventListener("click", () => skillsGo(editing ? "connector" : "list"));
  foot.append(save, cancel);
  form.append(foot);
  sync();

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!name.value.trim() || !url.value.trim()) { toast(tr("Bitte Name und Adresse eintragen.")); return; }
    const body = { name: name.value, description: description.value, url: url.value, auth: auth.value, mode: rows.mode.hidden ? "per_user" : mode.value };
    if (!editing) body.scope = scope.value;
    if (auth.value === "header") body.header_name = header.value;
    if (!rows.shared.hidden && shared.value) body.shared_secret = shared.value;
    if (can.global && !connUi.data.allow_private) body.local_ok = local.checked;
    if (auth.value === "oauth") {
      body.client_id = clientId.value;
      body.scopes = scopes.value;
      body.authorization_endpoint = authEndpoint.value;
      body.token_endpoint = tokenEndpoint.value;
      if (clientSecret.value) body.client_secret = clientSecret.value;
      const extra = {};
      for (const line of params.value.split("\n")) {
        const at = line.indexOf("=");
        if (at > 0) extra[line.slice(0, at).trim()] = line.slice(at + 1).trim();
      }
      body.auth_params = extra;
    }
    Object.assign(body, logo.value());
    save.disabled = true;
    try {
      const view = editing
        ? await api(`api/connectors/${c.id}`, { method: "PATCH", body: JSON.stringify(body) })
        : await api("api/connectors", { method: "POST", body: JSON.stringify(body) });
      connKeep(view);
      toast(tr("Konnektor gespeichert."));
      connOpen(view.id);
    } catch (err) { toast(errorText(err, tr("Speichern hat nicht geklappt."))); save.disabled = false; }
  });
  wrap.append(form);
  name.focus();
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
  if (state.incognito) {
    const ghost = icon("ghost");
    ghost.setAttribute("class", "icon hello-ghost");
    const facts = node("ul", "incognito-facts");
    for (const line of [
      tr("Der Chat steht in keiner Liste und keiner Suche und wird nicht exportiert."),
      tr("Ich lese und ändere kein Gedächtnis: weder deins noch das des Haushalts oder eines Projekts."),
      tr("Er wird gelöscht, sobald du ihn verlässt oder die Seite schließt. Dateien, die ich erstelle, verschwinden mit ihm."),
    ]) facts.append(node("li", "", line));
    hello.append(
      ghost,
      node("h2", "", tr("Inkognito-Chat")),
      node("p", "", tr("Hier bleibt nichts zurück.")),
      facts,
      node("p", "hello-note", tr("Zum Antworten verarbeitet der KI-Anbieter deine Nachrichten trotzdem. Was ich in Home Assistant oder anderen Diensten ausführe, steht dort weiterhin im Protokoll.")),
    );
    thread.append(hello);
    return;
  }
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

function toolIcon(button, name, label) {
  button.replaceChildren(icon(name));
  button.title = label;
  button.setAttribute("aria-label", label);
}

async function togglePreview(anchor, button, html) {
  const open = anchor.nextElementSibling?.classList.contains("preview") ? anchor.nextElementSibling : null;
  if (open) { open.remove(); toolIcon(button, "eye", tr("Vorschau")); return; }
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
  anchor.after(box);
  toolIcon(button, "eyeOff", tr("Schließen"));
  box.scrollIntoView({ block: "center", behavior: "smooth" });
}

window.kiFile = { save: saveFile, preview: togglePreview };
window.kiIcon = icon;

// Inhalt eines eingefügten Textes in einem Fenster zeigen (mit Kopieren).
function openPasted(file) {
  openSheet({
    title: file.name,
    sub: tr("{0} Zeichen", file.text.length.toLocaleString(kiLocale)),
    ok: tr("Schließen"),
    wide: true,
    panel: (body) => {
      const copy = node("button", "pill ghost small pasted-copy", tr("Kopieren"));
      copy.type = "button";
      copy.addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(file.text); toast(tr("Kopiert.")); } catch { toast(tr("Kopieren nicht möglich.")); }
      });
      body.append(node("pre", "pasted-view", file.text), copy);
    },
  });
}

// Jeder Anhang ist eine gleich große Karte (wie bei Claude): eingefügter Text zeigt seinen Anfang, ein Bild sich selbst, andere
// Dateien Symbol und Namen. Unten links steht die Art („Eingefügt“, „Bild“, „PDF“ …), rechts bei eingefügtem Text der Stift.
// Antippen öffnet Text oder Bild in einem Fenster; der Stift (nur vor dem Senden) bearbeitet den Text.
function openImage(file) {
  let url = "";
  if (file.blob) url = URL.createObjectURL(file.blob);
  openSheet({
    title: file.name,
    sub: file.size ? formatSize(file.size) : "",
    ok: tr("Schließen"),
    wide: true,
    panel: (body) => {
      if (url || file.thumb) {
        const img = node("img", "image-view");
        img.alt = file.name;
        img.src = url || file.thumb;
        body.append(img);
      } else {
        body.append(node("p", "image-gone", tr("Das Bild liegt nicht mehr vor. Es wurde nur für die Antwort der KI verwendet.")));
      }
    },
  });
  if (url) {
    const release = new MutationObserver(() => { if ($("sheet").hidden) { URL.revokeObjectURL(url); release.disconnect(); } });
    release.observe($("sheet"), { attributes: true, attributeFilter: ["hidden"] });
  }
}

function attachCard(file, { onEdit = null, onRemove = null } = {}) {
  const pasted = !!(file.pasted && file.text);
  const isImage = file.kind === "image";
  const card = node("div", `paste-card${isImage ? " is-image" : ""}${pasted ? "" : isImage ? "" : " is-file"}`);
  const label = pasted ? tr("Eingefügt") : (KIND_LABEL[file.kind] || tr("Datei"));
  card.title = `${file.name} · ${formatSize(file.size ?? file.text?.length ?? 0)}`;
  if (pasted) card.append(node("div", "paste-snippet", file.text.slice(0, 280)));
  else if (isImage) {
    const pic = node("div", "paste-pic");
    if (file.thumb) pic.style.backgroundImage = `url("${file.thumb}")`;
    else pic.append(icon("picture"));
    card.append(pic);
  } else {
    const info = node("div", "paste-file");
    info.append(icon("file"), node("span", "paste-file-name", file.name));
    card.append(info);
  }
  const foot = node("div", "paste-foot");
  foot.append(node("span", "paste-tag", label));
  const button = (cls, name, text, handler) => {
    const b = node("button", cls);
    b.type = "button";
    b.setAttribute("aria-label", text);
    b.title = text;
    b.append(icon(name));
    b.addEventListener("click", (event) => { event.stopPropagation(); handler(); });
    return b;
  };
  if (onEdit && pasted) foot.append(button("paste-btn", "edit", tr("Eingefügten Text bearbeiten"), onEdit));
  card.append(foot);
  if (onRemove) card.append(button("paste-x", "close", tr("{0} entfernen", file.name), onRemove));
  const open = pasted ? () => openPasted(file) : isImage ? () => openImage(file) : null;
  if (open) {
    card.tabIndex = 0;
    card.setAttribute("role", "button");
    card.setAttribute("aria-label", tr("{0} ansehen", file.name));
    card.classList.add("viewable");
    card.addEventListener("click", open);
    card.addEventListener("keydown", (event) => { if ((event.key === "Enter" || event.key === " ") && event.target === card) { event.preventDefault(); open(); } });
  }
  return card;
}

// Text eines eingefügten Anhangs ändern (im Eingabefeld oder beim Bearbeiten einer Nachricht).
function editPasted(file, after) {
  let area = null;
  openSheet({
    title: tr("Eingefügten Text bearbeiten"),
    ok: tr("Speichern"),
    panel: (body) => {
      area = document.createElement("textarea");
      area.className = "field area pasted-area";
      area.value = file.text;
      area.maxLength = PASTE_MAX_CHARS;
      area.spellcheck = false;
      area.setAttribute("aria-label", tr("Eingefügter Text"));
      body.append(area);
    },
    onOk: async () => {
      if (!area.value.trim()) { toast(tr("Der Text darf nicht leer sein.")); return false; }
      file.text = area.value;
      if ("blob" in file) { file.blob = new Blob([file.text], { type: "text/plain;charset=utf-8" }); file.size = file.blob.size; }
      after();
      return true;
    },
  });
}

function fileChip(file, removable) {
  return attachCard(file, removable ? { onEdit: () => editPasted(file, renderTray), onRemove: () => removeFile(file) } : {});
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
  box.update = (all) => {
    // Gelungene Gedächtnis-Änderungen zeigt der Hinweis unter der Antwort (memoryNoteEl); hier stehen sie nicht doppelt.
    const items = all.filter((a) => !(a.kind === "memory" && a.status === "ok"));
    const ha = items.filter((a) => ["read", "execute", "write"].includes(a.kind));
    const changes = ha.filter((a) => a.kind !== "read").length;
    const wissen = items.filter((a) => a.kind === "knowledge").length;
    const memory = items.filter((a) => a.kind === "memory").length;
    const noted = items.filter((a) => a.kind === "knowledge-write" && a.status === "ok").length;
    const skillsUsed = items.filter((a) => (a.kind === "skill" || a.kind === "skill-ext") && a.label.startsWith(tr("Skill genutzt"))).length;
    const made = items.filter((a) => a.kind === "file" && a.status === "ok").length;
    const edited = items.filter((a) => a.kind === "file-edit" && a.status === "ok").length;
    const looked = items.filter((a) => a.kind === "file-read").length;
    const pics = items.filter((a) => a.kind === "image" && a.status === "ok").length;
    const gh = items.filter((a) => a.kind === "gh-read" || a.kind === "gh-write");
    const ghChanges = gh.filter((a) => a.kind === "gh-write" && a.status === "ok").length;
    const mcp = items.filter((a) => a.kind === "mcp-read" || a.kind === "mcp-write");
    const mcpChanges = mcp.filter((a) => a.kind === "mcp-write" && a.status === "ok").length;
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
    if (mcp.length) parts.push(trn(mcp.length, "1 Aktion über Konnektoren", "{0} Aktionen über Konnektoren") + (mcpChanges ? trn(mcpChanges, ", davon 1 Änderung", ", davon {0} Änderungen") : ""));
    if (wissen) parts.push(trn(wissen, "im Wissen nachgeschlagen", "{0}× im Wissen nachgeschlagen"));
    if (skillsUsed) parts.push(trn(skillsUsed, "Skill genutzt", "{0} Skills genutzt"));
    if (memory) parts.push(trn(memory, "Gedächtnis aktualisiert", "Gedächtnis {0}× aktualisiert"));
    if (noted) parts.push(trn(noted, "Im Projektwissen gespeichert", "{0}× im Projektwissen gespeichert"));
    if (made) parts.push(trn(made, "Datei erstellt", "{0} Dateien erstellt"));
    if (edited) parts.push(trn(edited, "Datei bearbeitet", "{0} Dateien bearbeitet"));
    if (pics) parts.push(trn(pics, "Bild erzeugt", "{0} Bilder erzeugt"));
    else if (items.some((a) => a.kind === "image")) parts.push(tr("Bild erzeugen"));
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

// In einem Projekt-Chat steht neben der Dateikarte ein Knopf, der die Datei im Projekt ablegt (dann bleibt sie, statt nach einigen Tagen abzulaufen).
function fileCardWithSave(file) {
  const card = fileCard(file);
  const chat = state.chats.find((c) => c.id === state.activeId);
  if (!chat || !chat.project_id || file.gone || file.image) return card;
  const wrap = node("div", "out-wrap");
  const save = node("button", "icon-btn out-save");
  save.type = "button";
  save.title = tr("Im Projekt ablegen");
  save.setAttribute("aria-label", tr("{0} im Projekt ablegen", file.name));
  save.append(icon("stack"));
  save.addEventListener("click", async () => {
    save.disabled = true;
    try {
      const answer = await api(`api/chats/${encodeURIComponent(chat.id)}/files/${encodeURIComponent(file.id)}/to-project`, { method: "POST" });
      save.classList.add("done");
      toast(answer.replaced ? tr("Im Projekt ersetzt: {0}", answer.name) : tr("Im Projekt abgelegt: {0}", answer.name));
      loadAll().catch(() => {});
    } catch (err) {
      save.disabled = false;
      toast(errorText(err, tr("Ablegen hat nicht geklappt.")));
    }
  });
  wrap.append(card, save);
  return wrap;
}

// ------------------------------------------------- Bilder
// Bilder (von OpenAI, Google oder als SVG gezeichnet) erscheinen als Vorschaukarte; ein Klick öffnet die Bildvorschau.
const imageUrls = new Map(); // Datei-ID -> Promise mit der Blob-Adresse (die Anfrage braucht den Header, ein <img src> kann ihn nicht senden)
const IMAGE_CACHE = 40;

function imageUrl(file) {
  if (!imageUrls.has(file.id)) {
    const loading = fetch(`api/files/${encodeURIComponent(file.id)}`, { credentials: "same-origin", headers: { "X-Requested-With": "ki-chat" } })
      .then(async (response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return URL.createObjectURL(await response.blob());
      })
      .catch((err) => { imageUrls.delete(file.id); throw err; });
    imageUrls.set(file.id, loading);
    if (imageUrls.size > IMAGE_CACHE) {
      const [oldId, old] = imageUrls.entries().next().value;
      imageUrls.delete(oldId);
      old.then((url) => URL.revokeObjectURL(url), () => {});
    }
  }
  return imageUrls.get(file.id);
}

const IMAGE_ENGINES = { openai: "OpenAI", google: "Google" };
function imageInfo(file) {
  const bits = [file.engine === "svg" ? tr("gezeichnet (SVG)") : IMAGE_ENGINES[file.engine] || ""];
  if (file.version > 1) bits.push(tr("Version {0}", file.version));
  if (file.w && file.h) bits.push(`${file.w}×${file.h}`);
  return bits.filter(Boolean).join(" · ");
}

function imageCard(file, group) {
  const card = node("button", `img-card${file.gone ? " gone" : ""}`);
  card.type = "button";
  card.disabled = !!file.gone;
  card.setAttribute("aria-label", file.gone ? tr("{0} (abgelaufen)", file.name) : tr("Bildvorschau öffnen: {0}", file.name));
  const frame = node("span", "img-frame");
  if (file.w && file.h) {
    frame.style.aspectRatio = `${file.w} / ${file.h}`;
    frame.style.width = `min(100%, 360px, ${Math.round((320 * file.w) / file.h)}px)`;
  }
  const pic = document.createElement("img");
  pic.alt = "";
  pic.decoding = "async";
  frame.append(pic);
  const caption = node("span", "img-cap");
  caption.append(node("b", "", file.name), node("small", "", file.gone ? tr("Abgelaufen") : imageInfo(file)));
  card.append(frame, caption);
  if (file.gone) frame.classList.add("failed");
  else {
    imageUrl(file).then((url) => { pic.src = url; frame.classList.add("loaded"); }, () => frame.classList.add("failed"));
    card.addEventListener("click", () => openImageView(card.group(), file.id, card));
  }
  card.group = () => group();
  card.fileId = file.id;
  return card;
}

function imagePending(action) {
  const drawing = action.label.startsWith(tr("Bild zeichnen"));
  const waiting = action.status === "waiting";
  const card = node("div", `img-card pending${waiting ? " waiting" : ""}`);
  card.setAttribute("role", "status");
  const frame = node("span", "img-frame");
  frame.append(icon("picture"));
  const caption = node("span", "img-cap");
  caption.append(
    node("b", "", waiting ? tr("Wartet auf deine Freigabe") : drawing ? tr("Bild wird gezeichnet …") : tr("Bild wird erzeugt …")),
    node("small", "", action.label.replace(/^[^:]*:\s*/, "")),
  );
  card.append(frame, caption);
  return card;
}

let imageView = null;

function closeImageView() {
  if (!imageView) return;
  const { back, onKey, opener } = imageView;
  document.removeEventListener("keydown", onKey, true);
  document.body.classList.remove("imgview-open");
  back.remove();
  imageView = null;
  if (opener?.isConnected) opener.focus();
}

// Bildvorschau: das Bild groß, Herunterladen, Schließen; bei mehreren Bildern einer Antwort blättern (Pfeiltasten).
function openImageView(files, id, opener) {
  closeImageView();
  let index = Math.max(0, files.findIndex((f) => f.id === id));
  const back = node("div", "imgview");
  back.setAttribute("role", "dialog");
  back.setAttribute("aria-modal", "true");
  back.setAttribute("aria-label", tr("Bildvorschau"));
  const bar = node("div", "imgview-bar");
  const title = node("div", "imgview-title");
  const name = node("b");
  const info = node("small");
  title.append(name, info);
  const tool = (label, iconName, cls = "") => {
    const b = node("button", `imgview-btn ${cls}`.trim());
    b.type = "button";
    b.title = label;
    b.setAttribute("aria-label", label);
    b.append(icon(iconName));
    return b;
  };
  const prev = tool(tr("Vorheriges Bild"), "chevron", "flip");
  const next = tool(tr("Nächstes Bild"), "chevron");
  const save = tool(tr("Herunterladen"), "download");
  const close = tool(tr("Schließen"), "close");
  bar.append(title, ...(files.length > 1 ? [prev, next] : []), save, close);
  const stage = node("div", "imgview-stage");
  const pic = document.createElement("img");
  pic.alt = "";
  pic.draggable = false;
  const note = node("p", "imgview-note");
  stage.append(pic, note);
  back.append(bar, stage);
  const show = (i) => {
    index = (i + files.length) % files.length;
    const file = files[index];
    name.textContent = file.name;
    info.textContent = files.length > 1 ? `${imageInfo(file)} · ${index + 1}/${files.length}` : imageInfo(file);
    stage.classList.remove("zoom", "failed");
    pic.removeAttribute("src");
    note.textContent = tr("Bild wird geladen …");
    imageUrl(file).then((url) => { if (files[index] === file) { pic.src = url; note.textContent = ""; } }, () => { stage.classList.add("failed"); note.textContent = tr("Das Bild ist nicht mehr verfügbar."); });
  };
  prev.addEventListener("click", () => show(index - 1));
  next.addEventListener("click", () => show(index + 1));
  save.addEventListener("click", () => downloadOutFile(files[index], save));
  close.addEventListener("click", closeImageView);
  // Klick auf das Bild: Originalgröße (zum Verschieben scrollbar) und zurück; Klick daneben schließt.
  pic.addEventListener("click", () => stage.classList.toggle("zoom"));
  stage.addEventListener("click", (event) => { if (event.target === stage) closeImageView(); });
  const onKey = (event) => {
    if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); closeImageView(); }
    else if (event.key === "ArrowLeft" && files.length > 1) { event.preventDefault(); show(index - 1); }
    else if (event.key === "ArrowRight" && files.length > 1) { event.preventDefault(); show(index + 1); }
    else if (event.key === "Tab") {
      const stops = [...back.querySelectorAll("button")];
      const at = stops.indexOf(document.activeElement);
      event.preventDefault();
      stops[(at + (event.shiftKey ? -1 : 1) + stops.length) % stops.length].focus();
    }
  };
  document.addEventListener("keydown", onKey, true);
  document.body.classList.add("imgview-open");
  document.body.append(back);
  imageView = { back, onKey, opener };
  show(index);
  close.focus();
}

function fileCardsEl(actions) {
  const box = node("div", "out-cards");
  const made = new Map(); // Bildkarten behalten, damit sie bei jeder neuen Aktion nicht neu geladen werden
  let images = [];
  box.update = (items) => {
    const files = items.filter((a) => a.file && a.status === "ok").map((a) => a.file);
    const pending = items.filter((a) => a.kind === "image" && (a.status === "running" || a.status === "waiting"));
    images = files.filter((f) => f.image);
    const cards = images.map((f) => {
      if (!made.has(f.id)) made.set(f.id, imageCard(f, () => images));
      return made.get(f.id);
    });
    box.hidden = files.length === 0 && pending.length === 0;
    box.replaceChildren(...cards, ...pending.map(imagePending), ...files.filter((f) => !f.image).map(fileCardWithSave));
  };
  box.update(actions);
  return box;
}

// Sichtbarer Hinweis unter der Antwort, wenn die KI etwas im Gedächtnis geändert hat (wie „In Erinnerungen gespeichert“ in Claude),
// mit „Rückgängig“ für jede Änderung. Der Server prüft, ob der Eintrag noch so ist, wie die KI ihn hinterlassen hat.
function memoryNoteEl(actions) {
  const box = node("div", "mem-note");
  const undone = new Set();
  box.update = (items) => {
    const done = items.filter((a) => a.kind === "memory" && a.status === "ok");
    box.hidden = done.length === 0;
    if (!done.length) { box.replaceChildren(); return; }
    const open = node("button", "mem-open", tr("Gedächtnis öffnen"));
    open.type = "button";
    open.addEventListener("click", () => openMemory());
    const list = node("span", "mem-text");
    done.forEach((a, i) => {
      if (i) list.append(" · ");
      const key = `${a.undo?.scope}|${a.undo?.project}|${a.undo?.topic}|${a.undo?.now}`;
      list.append(node("span", "mem-what", a.label));
      if (!a.undo) return;
      if (undone.has(key)) { list.append(" ", node("em", "mem-undone", tr("Rückgängig gemacht"))); return; }
      const undo = node("button", "mem-open mem-undo", tr("Rückgängig"));
      undo.type = "button";
      undo.addEventListener("click", async () => {
        undo.disabled = true;
        try {
          await api("api/memory/undo", { method: "POST", body: JSON.stringify({ scope: a.undo.scope, topic: a.undo.topic, prev: a.undo.prev, now: a.undo.now, project_id: a.undo.project || "" }) });
          undone.add(key);
          box.update(items);
        } catch (err) {
          toast(errorText(err, tr("Rückgängig hat nicht geklappt.")));
          undo.disabled = false;
        }
      });
      list.append(" ", undo);
    });
    box.replaceChildren(icon("memory"), list, open);
  };
  box.update(actions);
  return box;
}

// Wann wurde die Nachricht gesendet? „vor 33 Minuten“, „vor 2 Stunden“ (gerundet), danach „Heute Morgen“, „Gestern“,
// „Vorgestern“, „vor 3 Tagen“ und ab einer Woche das Datum.
function sentAgo(iso, now = new Date()) {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "";
  const mins = Math.max(0, Math.round((now - then) / 60000));
  if (mins < 1) return tr("gerade eben");
  if (mins < 60) return trn(mins, "vor 1 Minute", "vor {0} Minuten");
  if (mins < 360) { const hours = Math.round(mins / 60); return trn(hours, "vor 1 Stunde", "vor {0} Stunden"); }
  const midnight = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const days = Math.round((midnight(now) - midnight(then)) / 86400000);
  if (days <= 0) {
    const h = then.getHours();
    if (h < 5) return tr("Heute Nacht");
    if (h < 11) return tr("Heute Morgen");
    if (h < 14) return tr("Heute Mittag");
    if (h < 18) return tr("Heute Nachmittag");
    return tr("Heute Abend");
  }
  if (days === 1) return tr("Gestern");
  if (days === 2) return tr("Vorgestern");
  if (days < 7) return tr("vor {0} Tagen", days);
  const opts = { day: "numeric", month: "short" };
  if (then.getFullYear() !== now.getFullYear()) opts.year = "numeric";
  return then.toLocaleDateString(kiLocale, opts);
}

const exactTime = (iso) => { const d = new Date(iso); return Number.isNaN(d.getTime()) ? "" : d.toLocaleString(kiLocale, { dateStyle: "medium", timeStyle: "short" }); };

// Eigene Nachricht: Blase, darunter (beim Darüberfahren) Zeitpunkt, Bearbeiten und Kopieren. Die Nummer (data-id)
// kommt vom Server; bis dahin (gerade gesendet) fehlt der Stift.
function userMessage(text, files = [], meta = {}) {
  const group = node("div", "msg-group user-group");
  if (meta.id) group.dataset.id = String(meta.id);
  group.dataset.at = meta.at || new Date().toISOString();
  if (files.length) {
    const row = node("div", "msg-files");
    for (const f of files) row.append(fileChip(f, false));
    group.append(row);
  }
  const bubble = node("div", "msg user");
  const { quote, body } = splitQuote(text);
  if (quote) {
    const cite = node("div", "msg-quote");
    cite.append(icon("quote"), node("span", "msg-quote-text", quote));
    bubble.append(cite, node("div", "msg-text", body));
  } else if (/^\s*([-*+]|\d{1,9}[.)])\s+\S/m.test(text)) {
    bubble.classList.add("has-list"); // Stichpunkte werden als Liste mit Einrückung dargestellt, sonst bleibt der Text, wie getippt
    bubble.append(window.renderMarkdown(text, { plain: true }));
  } else {
    bubble.textContent = text;
  }
  bubble.hidden = !text.trim(); // nur Anhang ohne weiteren Text
  const bar = node("div", "msg-meta");
  const time = node("span", "msg-time");
  const refresh = () => { time.textContent = sentAgo(group.dataset.at); time.title = exactTime(group.dataset.at); };
  const keptText = files.filter((f) => f.pasted && f.text); // eingefügte Texte gehen beim Bearbeiten mit
  group.retry = files.length === keptText.length ? { text: body, quote, pasted: keptText } : null; // mit hochgeladenen Dateien geht „Neu erzeugen“ nicht (sie liegen nicht mehr vor)
  const edit = actionButton(tr("Nachricht bearbeiten"), "edit", "msg-act msg-edit-btn", () => startEdit(group, body, files.length > keptText.length, quote, keptText));
  const copy = actionButton(tr("Nachricht kopieren"), "copy", "msg-act", async () => {
    try {
      await navigator.clipboard.writeText(body);
      copy.replaceChildren(icon("check"));
      setTimeout(() => copy.replaceChildren(icon("copy")), 1600);
    } catch { toast(tr("Kopieren nicht möglich.")); }
  });
  copy.hidden = !body.trim();
  bar.append(time, edit, copy);
  group.append(bubble, bar);
  refresh();
  group.addEventListener("pointerenter", refresh);
  group.addEventListener("focusin", refresh);
  // Touchscreen: Antippen blendet die Leiste ein oder aus (es gibt kein Darüberfahren).
  bubble.addEventListener("click", () => {
    if (!window.matchMedia("(hover: none)").matches || window.getSelection()?.toString()) return;
    refresh();
    group.classList.toggle("show-meta");
  });
  return group;
}

// Nachricht bearbeiten: Die Blase wird zum Eingabefeld; „Senden“ ersetzt diese Frage und alles danach durch eine neue Antwort.
function startEdit(group, text, hadFiles, quote = "", pastedIn = []) {
  if (state.streaming) { toast(tr("Warte, bis die Antwort fertig ist.")); return; }
  if (!group.dataset.id) { toast(tr("Diese Nachricht lässt sich gerade nicht bearbeiten.")); return; }
  const bubble = group.querySelector(".msg.user");
  const box = node("div", "msg-edit");
  const pasted = pastedIn.map((f) => ({ name: f.name, text: f.text })); // Arbeitskopie: Änderungen zählen erst beim Senden
  const cards = node("div", "msg-edit-cards");
  const showCards = () => {
    cards.replaceChildren(...pasted.map((f) => attachCard(f, {
      onEdit: () => editPasted(f, showCards),
      onRemove: () => { pasted.splice(pasted.indexOf(f), 1); showCards(); },
    })));
    cards.hidden = pasted.length === 0;
  };
  showCards();
  const area = document.createElement("textarea");
  area.value = text;
  area.maxLength = 20000;
  area.setAttribute("aria-label", tr("Nachricht bearbeiten"));
  const fit = () => { area.style.height = "auto"; area.style.height = `${Math.min(area.scrollHeight, window.innerHeight * 0.5)}px`; };
  area.addEventListener("input", fit);
  const notes = [];
  if (group.nextElementSibling) notes.push(tr("Spätere Nachrichten in diesem Chat werden durch die neue Antwort ersetzt."));
  if (hadFiles) notes.push(tr("Angehängte Dateien werden nicht übernommen. Hänge sie bei Bedarf neu an."));
  if (quote) notes.push(tr("Das Zitat bleibt erhalten."));
  const row = node("div", "msg-edit-row");
  const cancel = node("button", "pill ghost small", tr("Abbrechen"));
  const save = node("button", "pill primary small", tr("Senden"));
  cancel.type = save.type = "button";
  const close = () => { box.remove(); group.classList.remove("editing"); area.removeEventListener("input", fit); };
  cancel.addEventListener("click", close);
  save.addEventListener("click", () => {
    const value = area.value.trim();
    if (!value && !pasted.length) return;
    close();
    sendMessage({ id: Number(group.dataset.id), text: value, el: group, quote, pasted }).catch(() => {});
  });
  area.addEventListener("keydown", (event) => {
    if (event.key === "Escape") { event.preventDefault(); close(); }
    else if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.isComposing) { event.preventDefault(); save.click(); }
  });
  row.append(cancel, save);
  box.append(cards, area);
  if (notes.length) box.append(node("p", "msg-edit-note", notes.join(" ")));
  box.append(row);
  group.classList.add("editing");
  bubble.after(box);
  fit();
  area.focus();
  area.setSelectionRange(area.value.length, area.value.length);
}

// Nach dem Senden kennt die Oberfläche die Nummern der neuen Fragen noch nicht: vom Server holen (nötig zum Bearbeiten).
async function stampMessages(chatId) {
  try {
    const messages = await api(`api/chats/${encodeURIComponent(chatId)}/messages`);
    if (state.activeId !== chatId) return;
    const mine = messages.filter((m) => m.role === "user");
    const groups = $("thread").querySelectorAll(".msg-group.user-group");
    if (groups.length !== mine.length) return;
    groups.forEach((g, i) => { g.dataset.id = String(mine[i].id); g.dataset.at = mine[i].created_at; });
  } catch { /* der Stift erscheint nach dem nächsten Laden */ }
}

// Unter einer Antwort: Kopieren und „Als Datei“ als dezente Symbole (nur bei der letzten Antwort dauerhaft, sonst beim
// Darüberfahren) und, nur beim Darüberfahren, wann die Antwort fertig wurde.
function answerMeta(text, el) {
  const bar = node("div", "msg-meta answer-meta");
  const copy = actionButton(tr("Antwort kopieren"), "copy", "msg-act", async () => {
    try {
      await navigator.clipboard.writeText(text);
      copy.replaceChildren(icon("check"));
      setTimeout(() => copy.replaceChildren(icon("copy")), 1600);
    } catch { toast(tr("Kopieren nicht möglich.")); }
  });
  const save = actionButton(tr("Als Datei speichern"), "download", "msg-act", () => {
    saveFile(tr("antwort.md"), text, "text/markdown").catch(() => toast(tr("Speichern hat nicht geklappt.")));
  });
  // Antwort neu erzeugen (wie „Erneut versuchen“ bei Claude): sendet die Frage davor noch einmal, die alte Antwort wird ersetzt.
  const again = actionButton(tr("Antwort neu erzeugen"), "refresh", "msg-act answer-retry", () => {
    const group = el.previousElementSibling;
    const retry = group?.retry;
    if (state.streaming || !retry || !group.dataset.id) return;
    sendMessage({ id: Number(group.dataset.id), text: retry.text, el: group, quote: retry.quote, pasted: retry.pasted }).catch(() => {});
  });
  const time = node("span", "msg-time");
  const refresh = () => { time.textContent = sentAgo(el.dataset.at); time.title = exactTime(el.dataset.at); };
  refresh();
  el.addEventListener("pointerenter", refresh);
  el.addEventListener("focusin", refresh);
  bar.append(copy, save, again, time);
  return bar;
}

// Nur die letzte Antwort zeigt ihre Symbole dauerhaft.
function markLastAnswer() {
  const all = $("thread").querySelectorAll(".msg.assistant:not(.pending)");
  all.forEach((el, i) => el.classList.toggle("last-answer", i === all.length - 1));
}

function messageEl(role, text, files = [], actions = [], meta = {}) {
  if (role === "user") return userMessage(text, files, meta);
  const el = node("div", `msg ${role}`);
  if (role === "assistant") {
    if (actions.length) el.append(actionsEl(actions));
    el.append(window.renderMarkdown(text));
    if (actions.some((a) => a.file)) el.append(fileCardsEl(actions));
    if (actions.some((a) => a.kind === "memory" && a.status === "ok")) el.append(memoryNoteEl(actions));
    const at = meta.at || new Date().toISOString();
    el.dataset.at = at;
    el.append(answerMeta(text, el));
    // Touchscreen: Antippen der Antwort blendet die Leiste mit dem Zeitpunkt ein oder aus.
    el.addEventListener("click", (event) => {
      if (!window.matchMedia("(hover: none)").matches || window.getSelection()?.toString() || event.target.closest("a, button, pre, table, summary")) return;
      el.classList.toggle("show-meta");
    });
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

// Mitlaufen während eine Antwort entsteht (wie in Claude): Der Chat folgt dem Text nur, solange die Antwort noch ins Bild passt.
// Wird sie länger, bleibt ihr Anfang oben stehen, damit man von vorn lesen kann. Wer selbst scrollt, wird nicht zurückgeholt.
const follow = { on: true, anchored: false };

function followReset() {
  follow.on = true;
  follow.anchored = false;
}

function followAnswer(el) {
  if (!follow.on || !el?.isConnected) return;
  const box = $("messages");
  const top = el.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop - 12;
  const bottom = box.scrollHeight - box.clientHeight;
  follow.anchored = top < bottom;
  box.scrollTop = Math.min(bottom, Math.max(top, 0));
}

// Seitenmenü per Wischen (wie in der Claude-App): am Handy im Web von links nach rechts öffnen, nach links schließen.
// In Home Assistant bleibt die Geste dem Seitenmenü von Home Assistant überlassen (dort gibt es hier kein Seitenmenü zum Öffnen).
function initSideSwipe() {
  const app = $("app");
  const side = $("sidebar");
  const scrim = $("drawer-scrim");
  const phone = window.matchMedia("(max-width: 800px)");
  const EDGE = 16; // ganz am Rand gehört die Geste dem Browser („zurück“)
  const FAR = 10; // ab so vielen Pixeln gilt es als Wischen
  let gesture = null;

  const scrollsSideways = (el) => {
    for (let node = el; node && node !== document.body && node.id !== "messages"; node = node.parentElement) {
      if (node.scrollWidth <= node.clientWidth + 1) continue;
      const overflow = getComputedStyle(node).overflowX;
      if (overflow === "auto" || overflow === "scroll") return true;
    }
    return false;
  };
  const blocked = (el) =>
    !!document.querySelector(".sheet.show, .set-modal.show, .imgview, .preview.full")
    || !!el.closest("input, textarea, select, [contenteditable='true'], .codebox, .tbl")
    || scrollsSideways(el);

  const setProgress = (progress) => {
    side.style.transform = `translateX(${-(1 - progress) * 105}%)`;
    scrim.style.opacity = String(progress);
    scrim.style.pointerEvents = progress > 0 ? "auto" : "";
  };
  const finish = (open) => {
    side.style.transition = "";
    scrim.style.transition = "";
    void side.offsetWidth; // vom aktuellen Stand aus weiter animieren
    side.style.transform = "";
    scrim.style.opacity = "";
    scrim.style.pointerEvents = "";
    if (open) openMenu(); else closeMenu();
  };

  document.addEventListener("touchstart", (event) => {
    gesture = null;
    if (!isWeb() || !phone.matches || event.touches.length !== 1) return;
    const touch = event.touches[0];
    const open = app.classList.contains("open");
    if (open ? !(side.contains(event.target) || event.target === scrim) : (touch.clientX < EDGE || blocked(event.target))) return;
    gesture = { x: touch.clientX, y: touch.clientY, time: Date.now(), open, width: side.offsetWidth || 300, active: false, progress: open ? 1 : 0 };
  }, { passive: true });

  document.addEventListener("touchmove", (event) => {
    if (!gesture) return;
    const touch = event.touches[0];
    const dx = touch.clientX - gesture.x;
    const dy = touch.clientY - gesture.y;
    if (!gesture.active) {
      // Daumen wischen selten gerade: erst bei deutlich senkrechter Bewegung gilt es als Scrollen.
      if (Math.abs(dy) > 2 * FAR && Math.abs(dy) > Math.abs(dx) * 1.2) { gesture = null; return; }
      if (Math.abs(dx) < FAR) return;
      const wrongWay = gesture.open ? dx > 0 : dx < 0;
      if (wrongWay || Math.abs(dx) < Math.abs(dy) * 0.8) { gesture = null; return; }
      gesture.active = true;
      side.style.transition = "none";
      scrim.style.transition = "none";
    }
    gesture.progress = Math.min(1, Math.max(0, gesture.open ? 1 + dx / gesture.width : dx / gesture.width));
    gesture.dx = dx;
    setProgress(gesture.progress);
  }, { passive: true });

  const end = () => {
    const current = gesture;
    gesture = null;
    if (!current || !current.active) return;
    const speed = (current.dx || 0) / Math.max(1, Date.now() - current.time); // Pixel je Millisekunde, rechts positiv
    const fast = Math.abs(speed) > 0.5;
    finish(fast ? speed > 0 : current.progress > 0.5);
  };
  document.addEventListener("touchend", end, { passive: true });
  document.addEventListener("touchcancel", end, { passive: true });
}

function initFollow() {
  const box = $("messages");
  const leave = () => { follow.on = false; };
  box.addEventListener("wheel", (event) => { if (event.deltaY < 0) leave(); }, { passive: true });
  box.addEventListener("touchmove", leave, { passive: true });
  box.addEventListener("pointerdown", (event) => { if (event.target === box) leave(); }); // Rollbalken ziehen
  document.addEventListener("keydown", (event) => {
    if (["PageUp", "ArrowUp", "Home"].includes(event.key) && !event.target.closest?.("input, textarea")) leave();
  });
  // Wieder ganz unten (und die Antwort passt noch ins Bild): ab hier läuft der Chat wieder mit.
  box.addEventListener("scroll", () => {
    if (!follow.anchored && box.scrollHeight - box.scrollTop - box.clientHeight < 40) follow.on = true;
  }, { passive: true });
  // „Nach unten“ (wie bei Claude): erscheint, sobald man im Chat weit nach oben gescrollt hat.
  const jump = $("to-bottom");
  jump.append(icon("arrowDown"));
  jump.addEventListener("click", () => {
    follow.on = true;
    const far = box.scrollHeight - box.scrollTop - box.clientHeight > 2500; // weite Wege ohne langes Gleiten
    box.scrollTo({ top: box.scrollHeight, behavior: far ? "auto" : "smooth" });
  });
  let queued = false;
  const check = () => {
    queued = false;
    jump.classList.toggle("show", box.scrollHeight - box.scrollTop - box.clientHeight > 320);
  };
  box.addEventListener("scroll", () => { if (!queued) { queued = true; requestAnimationFrame(check); } }, { passive: true });
  new MutationObserver(() => { if (!queued) { queued = true; requestAnimationFrame(check); } }).observe($("thread"), { childList: true });
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
    thread.append(messageEl(m.role, m.content, m.attachments || [], m.tools || [], { id: m.id, at: m.created_at }));
  }
  markLastAnswer();
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
  setQuote("");
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
  state.incognito = false;
  state.activeId = null;
  rememberActive();
  state.heldUnread = null;
  state.newProject = projectId;
  setQuote("");
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
  const thumb = draw(240, null);
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

// Langer eingefügter Text wird ein Textanhang. Er bleibt im Chat gespeichert (die KI sieht ihn auch in Folgefragen) und lässt sich öffnen.
const PASTE_MIN_CHARS = 1500;
const PASTE_MIN_LINES = 20;
const PASTE_MAX_CHARS = 200000; // wie MAX_TEXT_CHARS im Server

function isLongPaste(text) {
  return text.length >= PASTE_MIN_CHARS || text.split("\n").length >= PASTE_MIN_LINES;
}

function pastedFile({ name, text }) {
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  return { id: ++fileId, kind: "text", name, blob, thumb: "", size: blob.size, pasted: true, text };
}

function addPasted(text) {
  if (text.length > PASTE_MAX_CHARS) {
    toast(tr("Der eingefügte Text ist zu lang (höchstens {0} Zeichen).", PASTE_MAX_CHARS.toLocaleString(kiLocale)));
    return;
  }
  const taken = state.files.filter((f) => f.pasted).length;
  const name = taken ? tr("Eingefügter Text ({0}).txt", taken + 1) : tr("Eingefügter Text.txt");
  state.files.push(pastedFile({ name, text }));
  renderTray();
  $("input").focus({ preventScroll: true });
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
  $("input").placeholder = composerPlaceholder();
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
  // Dateien aus der Zwischenablage (z. B. Screenshot) einfügen; langer Text wird (wie in Claude) zum Anhang statt zum Rohtext im Eingabefeld
  $("input").addEventListener("paste", (event) => {
    const files = [...(event.clipboardData?.files || [])];
    if (files.length) {
      event.preventDefault();
      addFiles(files);
      return;
    }
    const text = (event.clipboardData?.getData("text/plain") || "").replace(/\r\n?/g, "\n");
    if (!isLongPaste(text) || state.streaming || state.files.length >= LIMITS.files || $("input").readOnly) return; // sonst normal einfügen
    event.preventDefault();
    addPasted(text);
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
    parts.mem = memoryNoteEl([]);
    bubble.replaceChildren(parts.log, parts.text, parts.files, parts.mem, ...(run.busy ? [run.busy.el] : []));
  };
  // Was die Warteanzeige gerade zeigt: laufende Aktion, Rückfrage, Hinweistext oder (sobald Text kommt) nur das kleine Zeichen
  let statusText = "";
  const syncBusy = () => {
    if (!run.busy || run.detached) return;
    const running = out.actions.filter((a) => a.status === "running");
    const waiting = out.actions.some((a) => a.status === "waiting") || cards.size > 0;
    const current = running.at(-1);
    run.busy.set({ tool: current?.label || "", kind: current?.kind || "", recap: running.length ? "" : recapOf(out.actions), status: statusText, waiting, streaming: !!out.answer && !running.length && !waiting });
  };
  let frame = 0;
  const paint = () => {
    frame = 0;
    if (run.detached) return;
    build();
    window.renderMarkdownInto(parts.text, out.answer); // gleicht ab: Codeblöcke und ihre Knöpfe bleiben bestehen (Kopieren geht schon beim Schreiben)
    followAnswer(bubble);
  };
  try {
    await readEvents(response, (ev) => {
      if (ev.type === "delta") {
        out.answer += ev.text;
        statusText = "";
        try { run.onText?.(out.answer); } catch { /* das Vorlesen darf die Anzeige nicht stören */ }
        if (!frame) frame = requestAnimationFrame(paint);
      } else if (ev.type === "status") {
        statusText = ev.text.replace(/\s*…\s*$/, "");
      } else if (ev.type === "tool") {
        byId.set(ev.id, { label: ev.label, kind: ev.kind, status: ev.status, note: ev.note || "", file: ev.file || null, link: ev.link || "", undo: ev.undo || null });
        out.actions = [...byId.values()];
        if (!run.detached) { build(); parts.log.update(out.actions); parts.files.update(out.actions); parts.mem.update(out.actions); followAnswer(bubble); }
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

const THINK_WORDS = [tr("Denkt nach"), tr("Überlegt"), tr("Tüftelt"), tr("Sortiert Gedanken"), tr("Wägt ab"), tr("Grübelt"), tr("Knobelt"), tr("Formuliert"), tr("Bröselt auf"), tr("Sinniert")];

// Welches Zeichen zur Tätigkeit passt: Feder beim Schreiben von Dateien und Bildern, Lupe beim Suchen und Lesen, Blitz bei Aktionen, sonst Punkte.
const BUSY_ART = {
  file: "pen", "file-edit": "pen", image: "pen",
  web: "look", read: "look", knowledge: "look", skill: "look", "skill-ext": "look", "memory-read": "look", "gh-read": "look", "file-read": "look", "mcp-read": "look",
  execute: "act", write: "act", "gh-write": "act", "mcp-write": "act", memory: "act", "knowledge-write": "pen",
};
const HA_KINDS = ["read", "execute", "write"];

// Kurzfassung des zuletzt Erledigten („2 Dateien erstellt“), damit man zwischen zwei Schritten sieht, was geschehen ist.
function recapOf(actions) {
  const done = actions.filter((a) => a.status === "ok");
  const last = done.at(-1);
  if (!last) return "";
  const count = (kind) => done.filter((a) => a.kind === kind).length;
  const n = count(last.kind);
  switch (last.kind) {
    case "file": return trn(n, "Datei erstellt", "{0} Dateien erstellt");
    case "file-edit": return trn(n, "Datei bearbeitet", "{0} Dateien bearbeitet");
    case "image": return trn(n, "Bild erzeugt", "{0} Bilder erzeugt");
    case "file-read": return trn(n, "Datei angesehen", "{0} Dateien angesehen");
    case "skill": case "skill-ext": {
      const used = done.filter((a) => a.kind === "skill" || a.kind === "skill-ext").length;
      return trn(used, "Skill genutzt", "{0} Skills genutzt");
    }
    case "memory": return tr("Gedächtnis aktualisiert");
    case "knowledge-write": return tr("Im Projektwissen gespeichert");
    case "web": {
      const web = done.filter((a) => a.kind === "web");
      const searches = web.filter((a) => a.label.startsWith(tr("Websuche"))).length;
      const bits = [];
      const pages = web.length - searches;
      if (searches) bits.push(trn(searches, "1 Suche", "{0} Suchen"));
      if (pages) bits.push(trn(pages, "1 Seite gelesen", "{0} Seiten gelesen"));
      return tr("Recherche im Web ({0})", bits.join(", "));
    }
    case "mcp-read": case "mcp-write": {
      const mcp = done.filter((a) => a.kind.startsWith("mcp-")).length;
      return trn(mcp, "1 Aktion über Konnektoren", "{0} Aktionen über Konnektoren");
    }
    case "gh-read": case "gh-write": {
      const gh = done.filter((a) => a.kind.startsWith("gh-")).length;
      return trn(gh, "1 Aktion bei GitHub", "{0} Aktionen bei GitHub");
    }
    default: {
      if (!HA_KINDS.includes(last.kind)) return "";
      const ha = done.filter((a) => HA_KINDS.includes(a.kind)).length;
      return trn(ha, "1 Aktion in Home Assistant", "{0} Aktionen in Home Assistant");
    }
  }
}

// Bewegtes Zeichen (SVG, Farbe aus dem Thema): Punkte, schreibende Feder, Lupe, Blitz. CSS wählt über data-art.
function busyArt() {
  const svg = (tag, attrs = {}, ...kids) => {
    const el = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    el.append(...kids);
    return el;
  };
  const art = svg("svg", { viewBox: "0 0 36 22", class: "busy-art", "aria-hidden": "true" });
  // Feder: Spitze im Ursprung der Gruppe, der Körper wächst nach oben rechts; CSS führt sie über die Wellenlinie.
  const feather = svg("g", { class: "feather-move" },
    svg("g", { transform: "translate(-5 -19)" },
      svg("path", { class: "feather-body", d: "M19 5.2c-6.3.2-10.7 3.6-12.3 9.3l-.9 3.3 3.3-.9c5.7-1.6 9.1-6 9.9-11.7z" }),
      svg("path", { class: "feather-rib", d: "M5 19.2L15.5 8.7M10.4 14.2h4.6M12.4 11.8h3.9" })));
  art.append(
    svg("g", { class: "art-dots" }, ...[11, 18, 25].map((x) => svg("circle", { cx: x, cy: 11, r: 2.6 }))),
    svg("g", { class: "art-pen" }, svg("path", { class: "pen-line", d: "M4 18q3.5-4 7 0t7 0t7 0", pathLength: 24 }), feather),
    svg("g", { class: "art-look", transform: "translate(4 1)" }, svg("circle", { cx: 12, cy: 9, r: 5 }), svg("path", { d: "M16 13l5 5" })),
    svg("g", { class: "art-act", transform: "translate(4 1)" }, svg("path", { d: "M15 2L7 11.5h5.5L11 18l8-9.5h-5.5z" })),
  );
  return art;
}
const BUSY_SHOW_TIME = 20;
const BUSY_SHOW_HINT = 60;

function makeBusy() {
  const el = node("div", "busy");
  el.setAttribute("role", "status");
  const spark = busyArt();
  const word = node("span", "busy-word");
  const extra = node("span", "busy-extra");
  const hint = node("p", "busy-hint", tr("Das dauert etwas länger. Du kannst den Chat verlassen, die Antwort wird trotzdem fertig."));
  for (const part of [spark, word, extra, hint]) part.setAttribute("aria-hidden", "true");
  hint.hidden = true;
  el.append(node("span", "sr-only", tr("Die Antwort wird erstellt")), spark, word, extra, hint);

  const started = Date.now();
  const words = [...THINK_WORDS].sort(() => Math.random() - 0.5);
  const now = { tool: "", kind: "", recap: "", status: "", waiting: false, streaming: false };
  let index = 0;
  let recapShown = "";
  let shown = "";
  let timer = 0;

  const paint = () => {
    const seconds = Math.floor((Date.now() - started) / 1000);
    el.classList.toggle("compact", now.streaming);
    el.classList.toggle("paused", now.waiting);
    if (now.recap !== recapShown) { recapShown = now.recap; index = 0; } // Neues Ergebnis: zuerst kurz zeigen, dann wieder Denkwörter
    const cycle = now.recap ? [now.recap, ...words] : words;
    spark.dataset.art = now.streaming || now.waiting || !now.tool ? "dots" : BUSY_ART[now.kind] || "dots";
    const label = now.waiting ? tr("Wartet auf deine Freigabe") : (now.tool || now.status || cycle[index % cycle.length]) + (now.recap && !now.tool && !now.status && index % cycle.length === 0 ? "" : " …");
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
  const question = { github: tr("Soll diese Änderung bei GitHub ausgeführt werden?"), memory: tr("Soll die KI das im Gedächtnis ändern?"), connector: tr("Soll diese Änderung über den Konnektor ausgeführt werden?"), image: tr("Soll dieses Bild erzeugt werden?"), research: tr("Soll die Recherche gestartet werden?"), tokens: tr("Soll die Antwort trotz erreichtem Monatslimit erzeugt werden?") }[ev.topic] || tr("Soll diese Änderung in Home Assistant ausgeführt werden?");
  card.append(node("div", "ask-title", question), node("div", "ask-what", ev.label));
  if (ev.details) {
    const more = document.createElement("details");
    more.className = "ask-details";
    more.open = ev.topic === "research"; // Zeit und Kosten stehen dort: bei Deep Research gleich sichtbar
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
  const finished = out.answer ? messageEl("assistant", out.answer, [], out.actions) : null;
  if (finished) bubble.replaceWith(finished);
  else bubble.remove();
  markLastAnswer();
  if (out.failure) {
    if (!out.answer) {
      // Nichts gespeichert: Frage samt Dateien zurück ins Eingabefeld.
      const input = $("input");
      if (view.userEl) {
        view.userEl.remove();
        input.value = view.text;
        if (state.files.length === 0 && view.sentFiles) { state.files = view.sentFiles; renderTray(); }
        if (view.quote && !state.quote) setQuote(view.quote);
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
    const reusable = view.sentFiles.filter((f) => !f.pasted); // eingefügter Text bleibt im Chat, er muss nicht neu angehängt werden
    if (state.files !== view.sentFiles && out.answer && reusable.length) {
      state.recent = reusable;
      view.userEl?.querySelector(".msg-files")?.append(reattachButton(reusable));
    } else if (state.files !== view.sentFiles) {
      for (const f of view.sentFiles) f.blob = null;
    }
  }
  // Am Ende nicht nach unten zwingen: eine lange Antwort bleibt mit ihrem Anfang im Bild, wenn man sie von vorn liest.
  if (finished && !(out.failure && !follow.anchored)) followAnswer(finished);
  else if (!finished || follow.on) scrollDown(true);
  // Wird die Antwort gerade angesehen, gilt sie als gelesen; liegt das Fenster im Hintergrund, bleibt der Chat ungelesen.
  if (out.answer && !document.hidden && chatId !== state.incognitoId) await patchChat({ id: chatId }, { unread: false }).catch(() => {});
  await loadAll().catch(() => {});
  if (state.activeId === chatId) state.shownAt = state.chats.find((c) => c.id === chatId)?.updated_at ?? null;
  if (state.activeId === chatId) await stampMessages(chatId);
  if (out.compacted && state.activeId === chatId) {
    // Trennlinie „ab hier zusammengefasst“ einblenden
    try { renderMessages(await api(`api/chats/${encodeURIComponent(chatId)}/messages`)); } catch { /* bleibt wie es ist */ }
  }
  if (out.title && state.activeId === chatId) setTitle(out.title);
  focusInput();
  if (out.answer && view.first && chatId !== state.incognitoId) refreshTitle(chatId);
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
  followReset();
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

// ``edit`` = { id, text, el }: eine frühere Frage bearbeiten (el = ihre Ansicht); sie und alles danach wird ersetzt.
// ------------------------------------------------------- Auf einen Ausschnitt antworten (Zitat)

// Gleiches Muster wie quotes.py: Zitatblock („> “ je Zeile), Leerzeile, eigener Text.
const QUOTE_MAX = 2000;

function cleanQuote(text) {
  const lines = String(text || "").replace(/\r\n?/g, "\n").trim().split("\n").map((line) => line.replace(/\s+$/, ""));
  const out = [];
  for (const line of lines) {
    if (!line && out.length && !out[out.length - 1]) continue;
    out.push(line);
  }
  const joined = out.join("\n").trim();
  return joined.length > QUOTE_MAX ? `${joined.slice(0, QUOTE_MAX).trimEnd()}…` : joined;
}

function withQuote(quote, text) {
  const clean = cleanQuote(quote);
  if (!clean) return text;
  return `${clean.split("\n").map((line) => (line ? `> ${line}` : ">")).join("\n")}\n\n${text}`;
}

function splitQuote(content) {
  const lines = String(content).split("\n");
  let count = 0;
  while (count < lines.length && (lines[count].startsWith("> ") || lines[count] === ">")) count += 1;
  if (count === 0 || count >= lines.length || lines[count] !== "") return { quote: "", body: content };
  return { quote: lines.slice(0, count).map((l) => (l.startsWith("> ") ? l.slice(2) : "")).join("\n"), body: lines.slice(count + 1).join("\n").replace(/^\n+/, "") };
}

// Leiste über dem Eingabefeld: ↳, der Ausschnitt (zwei Zeilen) und „x“. Mit „x“ ist die Nachricht wieder eine gewöhnliche.
function setQuote(text) {
  state.quote = cleanQuote(text);
  const bar = $("quote-bar");
  bar.replaceChildren();
  bar.hidden = !state.quote;
  if (!state.quote) return;
  const label = node("span", "quote-text", state.quote);
  label.title = state.quote;
  bar.append(icon("quote"), label, actionButton(tr("Zitat entfernen"), "close", "quote-x", () => { setQuote(""); $("input").focus({ preventScroll: true }); }));
}

// Markierter Text in einer fertigen Antwort: kleiner Knopf „Antworten“ in der Nähe der Markierung.
function initQuotePicker() {
  const pop = node("button", "quote-pop");
  pop.type = "button";
  pop.hidden = true;
  pop.append(icon("reply"), node("span", "", tr("Antworten")));
  document.body.append(pop);
  let picked = "";
  let pointerDown = false;
  let timer = 0;

  const hide = () => { pop.hidden = true; picked = ""; };
  const hostOf = (n) => (n && (n.nodeType === 1 ? n : n.parentElement))?.closest(".msg.assistant:not(.pending)") || null;

  function update() {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || sel.rangeCount === 0) { hide(); return; }
    const range = sel.getRangeAt(0);
    const host = hostOf(range.startContainer);
    if (!host || host !== hostOf(range.endContainer) || !host.closest("#thread")) { hide(); return; }
    const text = cleanQuote(sel.toString());
    const rect = range.getBoundingClientRect();
    if (!text || (!rect.width && !rect.height)) { hide(); return; }
    picked = text;
    pop.hidden = false;
    const width = pop.offsetWidth;
    const touch = window.matchMedia("(hover: none)").matches;
    // Mit Maus über der Markierung, auf dem Touchscreen darunter (oben erscheint das Menü des Systems).
    let top = touch ? rect.bottom + 14 : rect.top - pop.offsetHeight - 8;
    if (top < 8) top = rect.bottom + 8;
    top = Math.min(top, window.innerHeight - pop.offsetHeight - 8);
    const left = Math.max(8, Math.min(rect.left + rect.width / 2 - width / 2, window.innerWidth - width - 8));
    pop.style.top = `${Math.round(top)}px`;
    pop.style.left = `${Math.round(left)}px`;
  }
  const later = (delay = 120) => { clearTimeout(timer); timer = setTimeout(update, delay); };

  document.addEventListener("selectionchange", () => { if (!pointerDown) later(); });
  document.addEventListener("pointerdown", (event) => { if (!pop.contains(event.target)) { pointerDown = true; hide(); } }, true);
  document.addEventListener("pointerup", () => { pointerDown = false; later(30); }, true);
  document.addEventListener("keyup", (event) => { if (event.key.startsWith("Arrow") || event.key === "Shift") later(30); });
  window.addEventListener("resize", hide);
  $("messages").addEventListener("scroll", () => { if (!pop.hidden) hide(); }, { passive: true });
  // Mausdruck auf den Knopf darf die Markierung nicht aufheben.
  pop.addEventListener("pointerdown", (event) => event.preventDefault());
  pop.addEventListener("mousedown", (event) => event.preventDefault());
  pop.addEventListener("click", () => {
    const text = picked;
    hide();
    window.getSelection()?.removeAllRanges();
    if (!text) return;
    setQuote(text);
    $("input").focus({ preventScroll: true });
  });
}

async function sendMessage(edit = null, spoken = null) {
  if (state.streaming) { if (!edit && !spoken) stopAnswer(); return; }
  const input = $("input");
  const text = edit ? edit.text : spoken ? spoken.text : input.value.trim();
  // Ein Anhang allein genügt (wie bei Claude): die KI geht dann auf den Anhang ein.
  const hasFiles = edit ? (edit.pasted || []).length > 0 : !spoken && state.files.length > 0;
  if (!text && !hasFiles) return;

  if (!state.activeId) {
    try {
      const body = state.incognito ? { incognito: true } : state.newProject ? { project_id: state.newProject } : {};
      const chat = await api("api/chats", { method: "POST", body: JSON.stringify(body) });
      if (chat.project_id) { ui.projectsOpen = true; ui.openProjects.add(chat.project_id); saveUi(); }
      state.newProject = null;
      if (chat.kind === "incognito") state.incognitoId = chat.id;
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
  const first = !edit && !thread.querySelector(".msg");
  thread.querySelector(".hello")?.remove();
  thread.classList.remove("empty");

  if (edit) {
    // Die alte Frage und alles danach verschwindet aus der Ansicht; der Server ersetzt es beim Annehmen.
    for (let n = edit.el; n;) { const next = n.nextElementSibling; n.remove(); n = next; }
  }
  const sentFiles = edit ? (edit.pasted || []).map(pastedFile) : spoken ? [] : state.files;
  const quote = edit ? (edit.quote || "") : spoken ? "" : state.quote;
  if (!edit && !spoken) { state.files = []; renderTray(); setQuote(""); }
  const userEl = messageEl("user", withQuote(quote, text), sentFiles);
  const bubble = node("div", "msg assistant pending");
  thread.append(userEl, bubble);
  followReset();
  scrollDown(true);

  if (!edit && !spoken) { input.value = ""; autosize(); }
  const run = openRun(chatId);
  if (spoken?.onText) run.onText = spoken.onText; // Sprachgespräch: der Text geht schon beim Eintreffen zum Vorlesen
  addBusy(run, bubble);
  // Beim Bearbeiten holt ein Fehler ohne Antwort den alten Stand vom Server zurück (kein ``userEl`` in der Ansicht).
  const view = edit ? { text, sentFiles, first } : { userEl, text, sentFiles, first, quote };

  let out;
  try {
    const files = await Promise.all(sentFiles.map(async (f) => ({ name: f.name, data: await toBase64(f.blob), ...(f.pasted ? { pasted: true } : {}) })));
    const response = await fetch(`api/chats/${encodeURIComponent(chatId)}/send`, {
      method: "POST",
      credentials: "same-origin",
      signal: run.controller.signal,
      headers: { "X-Requested-With": "ki-chat", "Content-Type": "application/json" },
      body: JSON.stringify({
        content: text, effort: state.effort, files,
        ...(quote ? { quote } : {}),
        ...(edit ? { edit_message_id: edit.id } : {}),
        ...(spoken ? { voice: true } : {}),
        ...((state.me?.models?.length || 0) > 1 && validModel(state.model) ? { model: state.model } : {}),
        ...(state.me?.web && !state.web ? { web: false } : {}),
        ...(researchOn() ? { research: true } : {}),
      }),
    });
    if (!response.ok) throw await sendFailure(response);
    run.accepted = true; // ab hier gehört die Antwort dem Server
    if (researchOn()) { state.research = false; $("toast").hidden = true; markTools(); refreshResearch().catch(() => {}); } // gilt nur für diese eine Nachricht
    loadAll().catch(() => {}); // Kreisel und Titel in der Liste sofort anzeigen
    if (run.detached) run.controller.abort(); // Chat wurde schon während des Hochladens verlassen
    out = await consume(response, run, bubble);
  } catch (err) {
    out = { answer: "", failure: null, title: null, compacted: false, ended: false };
    if (err.name !== "AbortError") out.failure = { message: err.message || tr("Die Verbindung wurde unterbrochen."), text: "" };
  }
  await settleRun(run, bubble, out, view);
  return out;
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
  // Das Limit gehört dem Claude-Abo: in einem ChatGPT-Chat ist es nicht von Belang
  if (usesOpenAI()) { renderNotices([], $("limit-notices")); return; }
  renderNotices(limitNotices(await api("api/limits")), $("limit-notices"));
}

// Modellwahl: "" = nichts gewählt (es gilt das Standardmodell der Person), "auto" = das in der App eingestellte Modell, sonst die Kennung.
const AUTO = "auto";
const validModel = (id) => id === AUTO || (!!id && !!state.me?.models?.some((m) => m.id === id));
const selectedModel = () => (validModel(state.model) ? state.model : (validModel(state.me?.user_model) && state.me.user_model) || AUTO);
const concreteModel = (selection) => (selection === AUTO ? state.me?.default_model || "" : selection);
const modelEntry = (id) => state.me?.models?.find((m) => m.id === id);
const modelProvider = (id) => modelEntry(id)?.provider || "claude";
const modelLabel = (id) => (id === AUTO ? tr("Auto") : modelEntry(id)?.label || id);
const usesOpenAI = () => modelProvider(concreteModel(selectedModel())) === "openai";

function markTools() {
  const me = state.me;
  const hasModels = (me?.models?.length || 0) > 1;
  const btn = $("tools");
  const model = hasModels ? modelLabel(selectedModel()) : "";
  $("tools-name").textContent = model;
  $("tools-effort").textContent = researchOn() ? tr("Deep Research") : effortLabel(state.effort);
  btn.classList.toggle("research", researchOn());
  btn.classList.toggle("web-off", !!me?.web && !state.web);
  btn.classList.toggle("on-openai", hasModels && usesOpenAI());
  btn.title = hasModels && usesOpenAI() ? tr("Dieser Chat läuft mit ChatGPT: Nachrichten und Anhänge gehen an OpenAI.") : "";
  btn.setAttribute("aria-label", `${tr("Modell, Aufwand und Websuche")}: ${[model, effortLabel(state.effort)].filter(Boolean).join(", ")}`);
}

// Modell des geöffneten Chats (gemerkt auf dem Server); ein neuer Chat startet ohne eigene Wahl, es gilt dann das Standardmodell der Person.
function useChatModel(chat) {
  state.model = chat && validModel(chat.model) ? chat.model : "";
  markTools();
  refreshLimits().catch(() => {});
}

const MODEL_HINTS = { sonnet: tr("Am effizientesten für einfachere Aufgaben"), opus: tr("Für komplexe Arbeit und alltägliche Aufgaben"), haiku: tr("Am schnellsten für schnelle Antworten") };
const modelHint = (id) => {
  if (id === AUTO) return tr("Das in der App eingestellte Modell ({0})", modelLabel(concreteModel(AUTO)));
  if (modelProvider(id) === "openai") return "";
  return MODEL_HINTS[Object.keys(MODEL_HINTS).find((family) => id.includes(family))] || "";
};

// Reihenfolge im Menü: Auto, die Claude-Modelle, danach ChatGPT.
function modelGroups() {
  const models = state.me?.models || [];
  return [models.filter((m) => m.provider !== "openai"), models.filter((m) => m.provider === "openai")];
}

// Handy: Fenster „Modell auswählen“ wie in Claude (Modelle mit Kurzbeschreibung, „Aufwand“ als zweite Seite, Websuche).
async function phoneToolsMenu() {
  const me = state.me;
  const models = me.models || [];
  const current = selectedModel();
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
            const [claude, openai] = modelGroups();
            const makeCard = (list, heading) => {
              const card = node("div", "mm-card");
              for (const m of list) {
                const text = node("span", "mm-text");
                text.append(node("span", "mm-name", modelLabel(m.id)));
                if (modelHint(m.id)) text.append(node("span", "mm-hint", modelHint(m.id)));
                const r = row("mm-row", text, ...(m.id === current ? [icon("check")] : []));
                r.addEventListener("click", pick(`model:${m.id}`));
                card.append(r);
              }
              if (heading) body.append(node("div", "mm-head", heading));
              body.append(card);
            };
            makeCard([{ id: AUTO }, ...claude]);
            if (openai.length) {
              makeCard(openai, tr("ChatGPT (OpenAI)"));
              body.append(node("div", "mm-note", tr("ChatGPT von OpenAI: Der Chat geht an OpenAI")));
            }
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
          if (researchAvailable()) {
            const rs = node("span", "pop-switch" + (state.research ? " on" : ""));
            rs.setAttribute("aria-hidden", "true");
            const research = row("mm-link", node("span", "mm-name", tr("Deep Research")), rs);
            research.setAttribute("role", "menuitemcheckbox");
            research.setAttribute("aria-checked", String(state.research));
            research.addEventListener("click", pick("research"));
            body.append(research);
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
  const current = selectedModel();
  const several = models.length > 1;
  let choice;
  if (!wideScreen()) {
    choice = await phoneToolsMenu();
  } else {
    const entries = [];
    const modelEntryFor = (id) => ({ value: `model:${id}`, label: modelLabel(id), detail: id === AUTO ? modelLabel(concreteModel(AUTO)) : modelProvider(id) === "openai" ? "OpenAI" : "" });
    if (several) entries.push({ ...modelEntryFor(current), active: true });
    entries.push({ label: tr("Aufwand"), detail: effortLabel(state.effort), submenu: EFFORTS.map(([value, label]) => ({ value: `effort:${value}`, label, active: value === state.effort })) });
    if (several) {
      const [claude, openai] = modelGroups();
      const others = [{ id: AUTO }, ...claude].filter((m) => m.id !== current).map((m) => modelEntryFor(m.id));
      const gpt = openai.filter((m) => m.id !== current).map((m) => modelEntryFor(m.id));
      entries.push({ label: tr("Weitere Modelle"), submenu: [...others, ...(gpt.length ? [{ divider: true }, ...gpt] : [])] });
    }
    if (me.web) {
      entries.push({ divider: true });
      entries.push({ value: "web", icon: "globe", label: tr("Websuche"), active: state.web, toggle: state.web });
    }
    if (researchAvailable()) {
      if (!me.web) entries.push({ divider: true });
      entries.push({ value: "research", icon: "search", label: tr("Deep Research"), active: state.research, toggle: state.research });
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
    const before = concreteModel(selectedModel());
    state.model = choice.slice(6);
    const after = concreteModel(selectedModel());
    if (before !== after && $("messages").querySelector(".msg-group")) {
      // Wechsel mitten im Chat: der Verlauf (nur der Text) geht mit, deshalb sagen, wohin er jetzt geht
      const name = modelLabel(after);
      toast(modelProvider(after) === modelProvider(before)
        ? tr("Ab der nächsten Nachricht antwortet {0}. Der bisherige Verlauf bleibt erhalten.", name)
        : modelProvider(after) === "openai"
          ? tr("Ab der nächsten Nachricht antwortet {0}. Der bisherige Verlauf dieses Chats geht dann auch an OpenAI.", name)
          : tr("Ab der nächsten Nachricht antwortet {0}. Der bisherige Verlauf dieses Chats geht dann an Claude.", name));
    } else if (usesOpenAI()) toast(tr("Dieser Chat läuft mit ChatGPT: Nachrichten und Anhänge gehen an OpenAI, nicht an Claude."));
    refreshLimits().catch(() => {});
  } else if (typeof choice === "string" && choice.startsWith("effort:")) {
    state.effort = choice.slice(7);
    try { localStorage.setItem("ki-effort", state.effort); } catch { /* optional */ }
  } else if (choice === "web") {
    state.web = !state.web;
    try { localStorage.setItem("ki-web", state.web ? "on" : "off"); } catch { /* optional */ }
    toast(state.web ? tr("Websuche ist an.") : tr("Websuche ist aus."));
    if (!state.web) state.research = false;
  } else if (choice === "research") {
    await toggleResearch();
  }
  markTools();
}

// Deep Research: mehrstufige Recherche mit Quellenbericht. Gilt nur für die nächste Nachricht und braucht die Websuche.
const researchAvailable = () => !!state.me?.research && !!state.me?.web && state.web;
const researchOn = () => state.research && researchAvailable();

async function refreshResearch() {
  try { state.me.research = await api("api/research"); } catch { /* Stand bleibt */ }
}

async function toggleResearch() {
  if (state.research) { state.research = false; toast(tr("Deep Research ist aus.")); return; }
  await refreshResearch();
  const info = state.me?.research;
  if (!info) return;
  if (info.left <= 0) { toast(tr("Das Tageslimit für Deep Research ist erreicht. Morgen geht es wieder.")); return; }
  state.research = true;
  toast(tr("Deep Research ist an, nur für die nächste Nachricht. Heute noch {0} von {1} Läufen.", info.left, info.limit));
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
  $("skills").hidden = view !== "skills";
  $("settings").hidden = view !== "settings";
  rememberView(view);
  syncIncognito();
  syncPresence();
  if (view !== "settings") { settingsStop(); settingsStop = () => {}; }
  $("nav-schedules").classList.toggle("active", view === "schedules");
  $("nav-skills").classList.toggle("active", view === "skills");
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

// ------------------------------------------------- Chats teilen

const canShare = () => !!state.me?.sharing && state.me.sharing !== "off";

// Teilen-Fenster (nach dem Vorbild von Claude): „Wer hat Zugriff“ mit zwei Wegen zu teilen (Link nur für Personen dieser Instanz, Link für jede Person),
// darunter Link, Gültigkeit und Abrufe, die Besitzerzeile und unten „Link kopieren“ mit Zahnrad und „Teilen beenden“. Geteilt wird immer ein Stand
// von jetzt; spätere Nachrichten erscheinen erst nach „Stand aktualisieren“. Anhänge und Gedächtnis-Hinweise werden nie mitgeteilt.
async function shareChat(chat) {
  await openSheet({
    title: tr("Chat teilen"), sub: tr("Nur die bisherigen Nachrichten werden geteilt"), plain: true,
    panel: (body) => { body.classList.add("share-panel"); drawSharePanel(body, chat).catch(() => { body.textContent = tr("Das hat nicht geklappt."); }); },
  });
  $("sheet-panel").classList.remove("share-panel");
  await loadAll().catch(() => {});  // Symbol in der Chatliste
}

function shareLevels(data) {
  const linkReady = data.sharing === "public" && data.public_available;
  return [
    { value: "instance", icon: "users", label: tr("Personen dieser Instanz mit Link"), hint: tr("Wer den Link öffnet, findet den Chat unter „Geteilt“. Er oder sie kann ihn lesen und als eigene Kopie weiterführen.") },
    {
      value: "public", icon: "link", label: tr("Jede Person mit dem Link"), disabled: !linkReady,
      hint: linkReady
        ? tr("Lesen ohne Anmeldung. Der Link ist lang und lässt sich nicht erraten. Leite ihn nur an Menschen weiter, denen du den Chat zeigen willst.")
        : data.sharing !== "public"
          ? tr("Nicht freigeschaltet: Der Admin muss in den Einstellungen bei „Chats teilen“ den Wert „public“ wählen.")
          : tr("Dafür ist der Domain-Zugang nötig, und der ist nicht eingerichtet."),
    },
  ];
}

const shareLinkOf = (row) => row.url || `${location.origin}${location.pathname}?share=${row.token}`;

async function drawSharePanel(body, chat, view = { open: false }) {
  const base = `api/chats/${encodeURIComponent(chat.id)}/share`;
  const load = async () => render(await api(base));
  const post = (payload, path = "") => api(`${base}${path}`, { method: "POST", body: JSON.stringify(payload) });
  const del = (mode) => api(`${base}/${mode}`, { method: "DELETE" });
  const run = async (action, success) => {
    try { await action(); if (success) toast(success); } catch (err) { toast(errorText(err, tr("Das hat nicht geklappt."))); }
    await load();
  };
  const expiryLabel = (iso) => {
    if (!iso) return tr("Unbegrenzt");
    const days = Math.max(1, Math.round((new Date(iso).getTime() - Date.now()) / 86400000));
    return days <= 7 ? tr("7 Tage") : tr("30 Tage");
  };
  async function pickExpiry(anchor, data) {
    const row = data.public || data.instance;
    const mark = (n) => (n === 0 ? !row.expires_at : !!row.expires_at && expiryLabel(row.expires_at) === (n === 7 ? tr("7 Tage") : tr("30 Tage")));
    const choice = await openPopover(anchor, [
      { heading: tr("Link gültig") },
      { value: "exp:7", label: tr("7 Tage ab jetzt"), active: mark(7) },
      { value: "exp:30", label: tr("30 Tage ab jetzt"), active: mark(30) },
      { value: "exp:0", label: tr("Unbegrenzt"), active: mark(0) },
    ]);
    if (typeof choice === "string" && choice.startsWith("exp:")) await run(() => post({ mode: row.mode, expires_days: Number(choice.slice(4)) }), tr("Gültigkeit geändert."));
  }

  function render(data) {
    const shared = data.public || data.instance || null;
    const level = data.public ? "public" : data.instance ? "instance" : "private";
    const levels = shareLevels(data);
    const current = levels.find((l) => l.value === level);
    const choose = async (next) => {
      view.open = false;
      if (next === level) { render(data); return; }
      await run(async () => {
        if (next === "instance") { await post({ mode: "instance" }); if (data.public) await del("public"); }
        else { await post({ mode: "public", expires_days: 30 }); if (data.instance) await del("instance"); }
      }, tr("Chat geteilt."));
    };

    const scroll = node("div", "share-scroll");
    const nodes = [node("p", "share-h", tr("Wer hat Zugriff"))];
    const access = node("button", "share-access");
    access.type = "button";
    access.setAttribute("aria-expanded", String(view.open));
    access.append(icon(current ? current.icon : "lock"), node("b", "", current ? current.label : tr("Nur ich")), icon("chevron"));
    access.addEventListener("click", () => { view.open = !view.open; render(data); });
    nodes.push(access);

    if (view.open) {
      const list = node("div", "share-options");
      list.setAttribute("role", "radiogroup");
      list.setAttribute("aria-label", tr("Wer hat Zugriff"));
      for (const l of levels) {
        const row = node("button", "share-opt" + (l.value === level ? " on" : ""));
        row.type = "button";
        row.setAttribute("role", "radio");
        row.setAttribute("aria-checked", String(l.value === level));
        row.disabled = !!l.disabled;
        const t = node("span", "share-text");
        t.append(node("b", "", l.label), node("span", "share-hint", l.hint));
        row.append(icon(l.icon), t);
        if (l.value === level) row.append(icon("check"));
        row.addEventListener("click", () => choose(l.value));
        list.append(row);
      }
      nodes.push(list);
    } else if (!shared) {
      nodes.push(node("p", "share-hint", tr("Niemand sonst sieht diesen Chat. Wähle oben, wie du ihn teilen willst.")));
    } else {
      nodes.push(node("p", "share-hint", current.hint));
      // Link: Ein Klick auf das Feld oder das Symbol kopiert ihn und meldet es im Feld.
      const link = node("section", "share-sec");
      link.append(node("p", "share-h", tr("Link")));
      const box = node("div", "share-urlbox");
      const field = node("input", "share-url");
      field.type = "text";
      field.readOnly = true;
      field.value = shareLinkOf(shared);
      field.setAttribute("aria-label", tr("Link"));
      const copy = node("button", "share-copy");
      copy.type = "button";
      copy.setAttribute("aria-label", tr("Link kopieren"));
      copy.title = tr("Link kopieren");
      copy.append(icon("copy"), icon("check"));
      const done = node("span", "share-copied", tr("Link wurde kopiert."));
      done.setAttribute("role", "status");
      let hideTimer = 0;
      const copyLink = async () => {
        field.select();
        try { await navigator.clipboard.writeText(field.value); } catch { try { document.execCommand("copy"); } catch { toast(tr("Zum Kopieren Strg+C drücken.")); return; } }
        field.setSelectionRange(0, 0);
        field.blur();
        box.classList.add("copied");
        clearTimeout(hideTimer);
        hideTimer = setTimeout(() => box.classList.remove("copied"), 1800);
      };
      field.addEventListener("click", copyLink);
      copy.addEventListener("click", copyLink);
      box.append(field, copy, done);
      const expiry = node("button", "share-expiry");
      expiry.type = "button";
      expiry.setAttribute("aria-haspopup", "menu");
      expiry.append(icon("clock"), node("span", "", tr("Link gültig: {0}", expiryLabel(shared.expires_at))), icon("chevron"));
      expiry.addEventListener("click", () => pickExpiry(expiry, data));
      const until = shared.expires_at ? tr("Gültig bis {0}", exactTime(shared.expires_at)) : tr("Läuft nicht ab");
      const stand = node("div", "share-stand");
      const refresh = node("button", "share-refresh");
      refresh.type = "button";
      refresh.append(icon("refresh"), node("span", "", tr("Aktualisieren")));
      refresh.title = tr("Stand aktualisieren");
      refresh.addEventListener("click", () => run(() => post({ mode: shared.mode }, "/refresh"), tr("Stand aktualisiert.")));
      stand.append(node("span", "", `${tr("Stand {0}", exactTime(shared.taken_at))} · ${until}`), refresh);
      link.append(box, expiry, stand);
      nodes.push(link);
      // Wer hat den Link geöffnet?
      const seen = node("section", "share-sec share-seen");
      if (level === "public") {
        seen.append(node("p", "share-h", tr("Abrufe")), node("p", "share-hint", shared.opens ? tr("Der Link wurde {0} Mal abgerufen.", shared.opens) : tr("Der Link wurde noch nicht abgerufen.")));
      } else {
        seen.append(node("p", "share-h", tr("Geöffnet von")));
        if (!shared.viewers.length) seen.append(node("p", "share-hint", tr("Noch niemand hat den Link geöffnet.")));
        for (const v of shared.viewers) {
          const row = node("div", "share-viewer");
          row.append(node("span", "share-avatar small", (v.name || "?").slice(0, 1).toUpperCase()), node("span", "share-name", v.name),
            node("span", "share-role", v.opens > 1 ? tr("{0}, {1}×", exactTime(v.last_at), v.opens) : exactTime(v.last_at)));
          seen.append(row);
        }
      }
      nodes.push(seen);
    }

    const owner = node("div", "share-owner");
    const name = state.me?.label || "";
    owner.append(node("span", "share-avatar", (name || "?").slice(0, 1).toUpperCase()), node("span", "share-name", `${name} ${tr("(du)")}`.trim()), node("span", "share-role", tr("Besitzer")));
    nodes.push(owner);
    nodes.push(node("p", "share-note", tr("Wer Zugriff hat, sieht den Chat so, wie er jetzt ist. Teile keine persönlichen Informationen oder Inhalte Dritter ohne Erlaubnis.")));
    scroll.append(...nodes);

    const foot = node("div", "share-foot");
    if (shared) {
      // Teilen beenden: Beim ersten Klick fragt der Knopf nach, beim zweiten (innerhalb von 4 Sekunden) beendet er.
      const end = node("button", "share-end");
      end.type = "button";
      const label = node("span", "", tr("Teilen beenden"));
      end.append(icon("trash"), label);
      let armed = 0;
      end.addEventListener("click", () => {
        if (!armed) {
          end.classList.add("armed");
          label.textContent = tr("Wirklich beenden?");
          armed = setTimeout(() => { armed = 0; end.classList.remove("armed"); label.textContent = tr("Teilen beenden"); }, 4000);
          return;
        }
        clearTimeout(armed);
        run(async () => { if (data.public) await del("public"); if (data.instance) await del("instance"); }, tr("Nicht mehr geteilt."));
      });
      foot.append(end);
    } else {
      const main = node("button", "pill primary share-main");
      main.type = "button";
      main.append(node("span", "", tr("Fertig")));
      main.addEventListener("click", () => closeSheet(true));
      foot.append(main);
    }
    body.replaceChildren(scroll, foot);
  }
  await load();
}

// „Geteilt“: alles, was geteilt ist. Mit dir (Personen, deren Link du geöffnet hast; mit Entfernen) und von dir (mit Projekt und Weg).
// Gedacht auch für künftig teilbare Dinge. Steht nichts darin, zeigt die Seite nur den Hinweis.
async function openSharedChats() {
  let picked = null;
  await openSheet({
    title: tr("Geteilt"), plain: true,
    panel: (body) => {
      body.classList.add("shared-panel");
      const draw = async () => {
        let incoming = [];
        try { incoming = await api("api/shared"); } catch (err) { body.textContent = errorText(err, tr("Das hat nicht geklappt.")); return; }
        const mine = state.chats.filter((c) => c.shared?.length);
        const nodes = [];
        const group = (heading, rows) => {
          nodes.push(node("p", "share-h", heading));
          const list = node("div", "shared-list");
          for (const r of rows) {
            const item = node("div", "shared-item");
            const open = node("button", "shared-open");
            open.type = "button";
            const t = node("span", "share-text");
            t.append(node("b", "", r.title), node("span", "share-hint", r.sub));
            open.append(icon("chat"), t);
            open.addEventListener("click", () => { picked = r.open; closeSheet(true); });
            item.append(open);
            if (r.remove) {
              const rm = node("button", "shared-remove");
              rm.type = "button";
              rm.setAttribute("aria-label", tr("Entfernen"));
              rm.title = tr("Entfernen");
              rm.append(icon("trash"));
              rm.addEventListener("click", async () => {
                try { await api(`api/shared/${encodeURIComponent(r.id)}`, { method: "DELETE" }); } catch (err) { toast(errorText(err, tr("Das hat nicht geklappt."))); }
                draw();
              });
              item.append(rm);
            }
            list.append(item);
          }
          nodes.push(list);
        };
        if (incoming.length) {
          group(tr("Mit mir geteilt"), incoming.map((c) => ({
            id: c.id, title: c.title, sub: tr("Von {0} · Stand {1}", c.owner, exactTime(c.taken_at)), open: () => openSharedChat(c.id), remove: true,
          })));
        }
        if (mine.length) {
          group(tr("Von mir geteilt"), mine.map((c) => {
            const project = c.project_id ? state.projects.find((p) => p.id === c.project_id)?.name : "";
            const how = c.shared.includes("public") ? tr("Jede Person mit dem Link") : tr("Personen dieser Instanz mit Link");
            return { id: c.id, title: c.title, sub: project ? `${project} · ${how}` : how, open: () => selectChat(c.id) };
          }));
        }
        if (!incoming.length) {
          const empty = node("div", "shared-empty");
          empty.append(icon("share"), node("p", "", tr("Es wurde nichts mit dir geteilt.")));
          nodes.unshift(empty);
        }
        body.replaceChildren(...nodes);
      };
      draw();
    },
  });
  $("sheet-panel").classList.remove("shared-panel");
  if (picked) await picked();
}

// Einen Link (oder nur den Code) öffnen: Der Chat erscheint danach unter „Geteilt“.
async function takeSharedLink(text) {
  try {
    const found = await api("api/shared/open", { method: "POST", body: JSON.stringify({ token: text.trim().slice(0, 600) }) });
    if (found.mine) toast(tr("Das ist dein eigener Chat."));
    else toast(tr("„{0}“ steht jetzt unter „Geteilt“.", found.title));
    return found;
  } catch (err) {
    toast(errorText(err, tr("Das hat nicht geklappt.")));
    return null;
  }
}

// Adresse mit ?share=…: Link geöffnet, den eine Person geteilt hat. Der Chat landet unter „Geteilt“ und öffnet sich zum Lesen.
async function openSharedFromAddress() {
  const params = new URLSearchParams(location.search);
  const code = params.get("share");
  if (!code) return;
  params.delete("share");
  const rest = params.toString();
  history.replaceState(null, "", location.pathname + (rest ? `?${rest}` : "") + location.hash);
  if (!canShare()) return;
  const found = await takeSharedLink(code);
  if (found && !found.mine) await openSharedChat(found.id);
}

async function openSharedChat(id) {
  let chat;
  try { chat = await api(`api/shared/${encodeURIComponent(id)}`); } catch (err) { toast(errorText(err, tr("Das hat nicht geklappt."))); return; }
  let copied = null;
  await openSheet({
    title: chat.title, sub: tr("Geteilt von {0}, Stand {1}. Du kannst nur lesen.", chat.owner, exactTime(chat.taken_at)),
    ok: tr("Als Kopie weiterführen"),
    panel: (body) => {
      const thread = node("div", "share-thread");
      for (const m of chat.messages) {
        const el = node("div", `msg ${m.role === "user" ? "user" : "assistant"}`);
        if (m.role === "user") el.textContent = m.content; else el.append(window.renderMarkdown(m.content));
        thread.append(el);
      }
      body.append(thread, node("p", "mem-hint", tr("Die Kopie ist ein eigener Chat von dir. Aktionen darin fragen immer erst nach, weil der Inhalt von jemand anderem stammt.")));
    },
    onOk: async () => {
      try {
        copied = await api(`api/shared/${encodeURIComponent(id)}/copy`, { method: "POST" });
        return true;
      } catch (err) {
        toast(errorText(err, tr("Das hat nicht geklappt.")));
        return false;
      }
    },
  });
  if (copied) { await loadAll(); await selectChat(copied.id); }
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

// ------------------------------------------------- Suche: Letzte Elemente, Reiter, Tastatur

function searchTabs() {
  const tabs = [["all", tr("Alle")], ["chats", tr("Chats")], ["projects", tr("Projekte")]];
  if (state.me?.schedules) tabs.push(["schedules", tr("Geplant")]);
  return tabs;
}

// Dinge, die man statt eines Treffers aufrufen will (in der Suche und als Vorschlag ohne Suchwort)
function searchActions() {
  const list = [
    { icon: "plus", label: tr("Neuer Chat"), run: () => startNew() },
    { icon: "folder", label: tr("Neues Projekt"), run: () => createProject() },
    { icon: "skill", label: tr("Anpassungen"), run: () => openSkills() },
  ];
  if (state.me?.schedules) list.push({ icon: "clock", label: tr("Geplant"), run: () => openSchedules() });
  if (state.me?.memory) list.push({ icon: "memory", label: tr("Gedächtnis"), run: () => openMemory() });
  if (canShare()) list.push({ icon: "share", label: tr("Geteilte Chats"), run: () => openSharedChats() });
  list.push({ icon: "download", label: tr("Meine Daten"), run: () => openMyData() });
  return list.map((a) => ({ ...a, id: `a-${a.label}`, title: a.label, meta: "", marks: [] }));
}

// „Heute“, „Gestern“, sonst Tag und Monat (das Jahr nur, wenn es nicht das laufende ist)
function searchDate(iso) {
  if (!iso) return "";
  const days = daysAgo(iso);
  if (days <= 1) return groupOf(iso);
  try {
    const then = new Date(iso);
    const opts = then.getFullYear() === new Date().getFullYear() ? { day: "numeric", month: "short" } : { day: "numeric", month: "short", year: "numeric" };
    return then.toLocaleDateString(kiLocale, opts);
  } catch { return ""; }
}

function chatEntry(chat, hit = null) {
  const marks = [];
  if (chat.needs_approval) marks.push(askMark());
  else if (chat.running) marks.push(runningMark());
  else if (chat.unread) marks.push(unreadDot());
  return {
    id: `c-${chat.id}`, icon: chat.schedule_id ? "clock" : "chat", title: chat.title,
    meta: searchDate(chat.updated_at), marks, snippet: hit?.snippet || "", hl: hit?.hl || [],
    run: () => selectChat(chat.id),
  };
}

function projectEntry(project) {
  return {
    id: `p-${project.id}`, icon: "folder", title: project.name, meta: project.pinned ? tr("Angepinnt") : "", marks: [],
    run: () => {
      // zeigt das Projekt in der Seitenleiste (am Handy öffnet sich die Leiste)
      ui.projectsOpen = true;
      ui.openProjects.add(project.id);
      saveUi();
      renderSide();
      openMenu();
      setTimeout(() => [...document.querySelectorAll("#side-scroll .project-row .name")].find((n) => n.textContent === project.name)?.scrollIntoView({ block: "center" }), 60);
    },
  };
}

function scheduleEntry(task) {
  return { id: `s-${task.id}`, icon: "clock", title: task.name, meta: "", marks: task.running ? [runningMark()] : [], run: () => openSchedules() };
}

function searchPanel(body) {
  const input = node("input", "field srch-input");
  input.type = "search";
  input.maxLength = 100;
  input.placeholder = tr("Chats, Projekte und mehr durchsuchen");
  input.setAttribute("aria-label", tr("Chats, Projekte und mehr durchsuchen"));
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-expanded", "true");
  input.setAttribute("aria-controls", "srch-list");
  input.autocomplete = "off";
  input.enterKeyHint = "search";
  const tabBar = node("div", "srch-tabs");
  tabBar.setAttribute("role", "tablist");
  tabBar.setAttribute("aria-label", tr("Suchen in"));
  const status = node("p", "mem-hint srch-status");
  status.setAttribute("role", "status");
  const list = node("div", "srch-list");
  list.id = "srch-list";
  list.setAttribute("role", "listbox");
  const keys = node("div", "srch-keys");
  keys.setAttribute("aria-hidden", "true");
  for (const [key, label] of [["Esc", tr("Schließen")], ["↑ ↓", tr("Auswählen")], ["← →", tr("Typ wechseln")], ["↵", tr("Öffnen")]]) {
    const item = node("span", "", label);
    item.prepend(node("kbd", "", key));
    keys.append(item);
  }
  body.append(input, tabBar, status, list, keys);

  let tab = "all";
  let entries = [];
  let cursor = -1;
  let ticket = 0;
  let timer = 0;
  let pending = false;
  const tabButtons = new Map();

  const select = (index) => {
    if (cursor >= 0) { const old = entries[cursor]?.row; old?.classList.remove("sel"); old?.setAttribute("aria-selected", "false"); }
    cursor = entries.length ? Math.max(0, Math.min(index, entries.length - 1)) : -1;
    const row = entries[cursor]?.row;
    if (!row) { input.removeAttribute("aria-activedescendant"); return; }
    row.classList.add("sel");
    row.setAttribute("aria-selected", "true");
    input.setAttribute("aria-activedescendant", row.id);
    row.scrollIntoView({ block: "nearest" });
  };

  const choose = (entry) => {
    closeSheet(null);
    Promise.resolve(entry.run()).catch(() => {});
  };

  const render = (groups, emptyText) => {
    list.replaceChildren();
    entries = [];
    cursor = -1;
    for (const group of groups) {
      if (!group.entries.length) continue;
      const head = node("div", "srch-group", group.label);
      head.setAttribute("role", "presentation");
      list.append(head);
      for (const entry of group.entries) {
        const index = entries.length;
        const row = node("button", "srch-item");
        row.type = "button";
        row.tabIndex = -1;
        row.id = `srch-opt-${index}`;
        row.setAttribute("role", "option");
        row.setAttribute("aria-selected", "false");
        const lead = icon(entry.icon);
        lead.classList.add("srch-lead");
        const main = node("span", "srch-main");
        main.append(node("b", "srch-title", entry.title));
        if (entry.snippet) main.append(highlighted(entry.snippet, entry.hl));
        const end = node("span", "srch-end");
        if (entry.meta) end.append(node("small", "srch-date", entry.meta));
        for (const mark of entry.marks) end.append(mark);
        row.append(lead, main, end);
        row.addEventListener("click", () => choose(entry));
        row.addEventListener("mousemove", () => { if (cursor !== index) select(index); });
        list.append(row);
        entries.push({ entry, row });
      }
    }
    status.textContent = entries.length ? "" : emptyText;
    select(0);
  };

  const recents = () => {
    const chats = state.chats;
    if (tab === "chats") {
      const out = [];
      let current = null;
      for (const chat of chats.slice(0, 60)) {
        const label = groupOf(chat.updated_at);
        if (label !== current) { current = label; out.push({ label, entries: [] }); }
        out[out.length - 1].entries.push(chatEntry(chat));
      }
      return { groups: out, empty: tr("Noch keine Chats.") };
    }
    if (tab === "projects") {
      const ordered = [...state.projects].sort((a, b) => Number(b.pinned) - Number(a.pinned) || a.name.localeCompare(b.name, kiLocale));
      return { groups: [{ label: tr("Projekte"), entries: ordered.map(projectEntry) }], empty: tr("Noch keine Projekte.") };
    }
    if (tab === "schedules") {
      return { groups: [{ label: tr("Geplant"), entries: state.schedules.map(scheduleEntry) }], empty: tr("Noch keine geplanten Aufgaben.") };
    }
    const active = chats.filter((c) => c.running || c.needs_approval);
    const rest = chats.filter((c) => !(c.running || c.needs_approval)).slice(0, 6);
    return {
      groups: [
        { label: tr("Aktiv"), entries: active.map((c) => chatEntry(c)) },
        { label: tr("Letzte Elemente"), entries: rest.map((c) => chatEntry(c)) },
        { label: tr("Aktionen"), entries: searchActions().slice(0, 3) },
      ],
      empty: tr("Noch keine Chats."),
    };
  };

  const found = (query, hits) => {
    const all = tab === "all";
    const groups = [];
    if (all || tab === "chats") {
      groups.push({ label: tr("Chats"), entries: hits.map((h) => chatEntry(state.chats.find((c) => c.id === h.chat_id) || { id: h.chat_id, title: h.title, updated_at: h.updated_at, schedule_id: h.schedule_id }, h)) });
    }
    if (all || tab === "projects") groups.push({ label: tr("Projekte"), entries: state.projects.filter((p) => wordsMatch(query, p.name)).map(projectEntry) });
    if ((all || tab === "schedules") && state.me?.schedules) {
      groups.push({ label: tr("Geplant"), entries: state.schedules.filter((t) => wordsMatch(query, `${t.name} ${t.prompt || ""}`)).map(scheduleEntry) });
    }
    if (all) groups.push({ label: tr("Aktionen"), entries: searchActions().filter((a) => wordsMatch(query, a.label)) });
    return groups;
  };

  // Zeigt die Vorschläge oder die Treffer; eine ältere, später eintreffende Antwort wird verworfen.
  const refresh = async () => {
    const query = input.value.trim().replace(/\s+/g, " ");
    const mine = ++ticket;
    if (!query) {
      const { groups, empty } = recents();
      render(groups, empty);
    } else if (query.length < 2) {
      render([], tr("Mindestens zwei Zeichen eingeben."));
    } else {
      let hits = [];
      if (tab === "all" || tab === "chats") {
        try {
          hits = await api(`api/search?q=${encodeURIComponent(query)}`);
        } catch {
          if (mine === ticket) render([], tr("Die Suche ist gerade nicht erreichbar."));
          return;
        }
        if (mine !== ticket) return;
      }
      render(found(query, hits), tr("Nichts gefunden für „{0}“.", query));
    }
    if (mine === ticket) pending = false;
  };

  const setTab = (key, focus = false) => {
    tab = key;
    for (const [k, button] of tabButtons) {
      button.setAttribute("aria-selected", String(k === key));
      button.tabIndex = k === key ? 0 : -1;
      if (focus && k === key) button.focus();
    }
    pending = true;
    clearTimeout(timer);
    refresh().catch(() => {});
  };
  const shift = (step, focus) => {
    const order = searchTabs().map(([k]) => k);
    setTab(order[(order.indexOf(tab) + step + order.length) % order.length], focus);
  };

  for (const [key, label] of searchTabs()) {
    const button = node("button", "srch-tab", label);
    button.type = "button";
    button.setAttribute("role", "tab");
    button.addEventListener("click", () => { setTab(key); input.focus(); });
    button.addEventListener("keydown", (event) => {
      if (event.key === "ArrowRight") { event.preventDefault(); shift(1, true); }
      else if (event.key === "ArrowLeft") { event.preventDefault(); shift(-1, true); }
      else if (event.key === "ArrowDown") { event.preventDefault(); input.focus(); }
    });
    tabButtons.set(key, button);
    tabBar.append(button);
  }

  input.addEventListener("input", () => { pending = true; clearTimeout(timer); timer = setTimeout(() => { refresh().catch(() => {}); }, 200); });
  input.addEventListener("keydown", async (event) => {
    if (event.isComposing) return;
    if (event.key === "Enter") {
      event.preventDefault();
      if (pending) { clearTimeout(timer); await refresh(); }
      if (cursor >= 0) choose(entries[cursor].entry);
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      select(cursor + 1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      select(cursor - 1);
    } else if ((event.key === "ArrowRight" || event.key === "ArrowLeft") && !input.value) {
      event.preventDefault();
      shift(event.key === "ArrowRight" ? 1 : -1, false);
    }
  });

  setTab("all");
  if (state.me?.schedules && !state.schedules.length) loadSchedules().then(() => { if (tab === "all" || tab === "schedules") refresh().catch(() => {}); }).catch(() => {});
}

async function openSearch() {
  if (!state.me) return;
  closePopover(null);
  await openSheet({ title: tr("Suchen"), ok: tr("Schließen"), panel: searchPanel, wide: true });
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

// ------------------------------------------------- Einführung und Neuerungen

const isTouch = () => window.matchMedia("(pointer: coarse)").matches;
let welcomeShown = false; // pro Seitenaufruf höchstens einmal von selbst

function introRow(iconName, title, text) {
  const row = node("div", "intro-row");
  const mark = node("span", "intro-mark");
  mark.append(icon(iconName));
  row.append(mark, node("div", "intro-text"));
  row.lastChild.append(node("b", "", title), node("span", "", text));
  return row;
}

function introGroup(heading, rows) {
  const group = node("section", "intro-group");
  group.append(node("h4", "", heading), ...rows);
  return group;
}

function introCapabilities() {
  const me = state.me || {};
  const rows = [
    introRow("chat", tr("Fragen und Texte"), tr("Ich beantworte Fragen, erkläre Dinge, schreibe und überarbeite Texte und helfe beim Planen.")),
    introRow("file", tr("Dokumente erstellen"), tr("Auf Wunsch baue ich Word-Dokumente, Excel-Tabellen, PowerPoint-Präsentationen und PDFs, schön gestaltet und zum Herunterladen.")),
    introRow("attach", tr("Dateien und Fotos lesen"), tr("Hänge Dokumente, Tabellen oder Fotos an, dann fasse ich sie zusammen oder werte sie aus.")),
  ];
  if (me.web) rows.push(introRow("globe", tr("Im Internet nachsehen"), tr("Für aktuelle Informationen suche ich im Web.")));
  if (me.ha_access === "write") rows.push(introRow("bolt", tr("Dein Smarthome"), tr("Ich sehe nach, wie es zu Hause aussieht, und steuere auf Wunsch Geräte. Bei Änderungen frage ich vorher nach.")));
  else if (me.ha_access === "read") rows.push(introRow("bolt", tr("Dein Smarthome"), tr("Ich sehe nach, wie es zu Hause aussieht, zum Beispiel Temperaturen, Lichter und Verbrauch.")));
  if (me.memory) rows.push(introRow("memory", tr("Dinge merken"), tr("Ich kann mir merken, was für dich wichtig ist. Was gespeichert ist, siehst du im Menü unter „Gedächtnis“.")));
  if (me.schedules) rows.push(introRow("clock", tr("Aufgaben planen"), tr("Ich erledige Aufgaben regelmäßig von selbst, zum Beispiel jeden Morgen eine Zusammenfassung.")));
  return rows;
}

function introHowTo() {
  if (isTouch()) {
    return [
      introRow("pen", tr("Schreiben"), tr("Tippe unten ins Eingabefeld und sende mit dem Pfeil.")),
      introRow("upload", tr("Fotos und Dateien"), tr("Mit der Büroklammer hängst du Fotos und Dateien an.")),
      introRow("reply", tr("Auf einen Satz antworten"), tr("Markiere in meiner Antwort einen Text und tippe auf „Antworten“, wenn du dich genau darauf beziehst.")),
      introRow("chat", tr("Deine Chats"), tr("Das Chat-Symbol öffnet deine bisherigen Chats, das Plus beginnt ein neues Thema.")),
    ];
  }
  return [
    introRow("pen", tr("Schreiben"), tr("Schreibe unten ins Eingabefeld. Mit Enter sendest du, mit Umschalt und Enter beginnst du eine neue Zeile.")),
    introRow("upload", tr("Fotos und Dateien"), tr("Ziehe Dateien einfach ins Fenster oder nutze die Büroklammer.")),
    introRow("reply", tr("Auf einen Satz antworten"), tr("Markiere in meiner Antwort einen Text und wähle „Antworten“, wenn du dich genau darauf beziehst.")),
    introRow("chat", tr("Deine Chats"), tr("Links findest du alle bisherigen Chats. Für ein neues Thema beginnst du am besten einen neuen Chat.")),
  ];
}

function introPanel(body) {
  const list = node("div", "intro-list");
  list.append(
    introGroup(tr("Das kann ich"), introCapabilities()),
    introGroup(tr("So arbeitest du mit mir"), introHowTo()),
    introGroup(tr("Gut zu wissen"), [
      introRow("info", tr("Ich kann mich irren"), tr("Prüfe wichtige Angaben, bevor du dich darauf verlässt.")),
      introRow("eye", tr("Deine Chats sind persönlich"), tr("Andere Personen sehen sie nicht.")),
    ]),
  );
  body.append(list);
}

async function confirmWelcome(what) {
  try {
    await api("api/welcome/seen", { method: "POST", body: JSON.stringify({ what }) });
    if (state.me) state.me.welcome = { intro: false, news: [] };
  } catch { /* nächstes Mal erneut */ }
}

// ``first``: automatisch beim Anmelden; nur dann wird „Okay“ gemerkt. Aus dem Menü ist es nur ein Nachschlagen.
async function openIntro(first = false) {
  const name = state.me?.app_name || "HA Copilot";
  const done = await openSheet({
    title: tr("Hallo, ich bin {0}", name),
    sub: tr("Dein KI-Assistent für Fragen, Texte, Dateien und mehr. Kurz erklärt, wie du mit mir arbeitest."),
    ok: tr("Okay"),
    panel: introPanel,
  });
  if (first && done === true) await confirmWelcome("intro");
}

// ``groups``: [{version?, items}]; ohne Version (Fenster nach einem Update) steht die Liste ohne Überschrift.
function newsPanel(groups) {
  return (body) => {
    const list = node("div", "intro-list");
    for (const group of groups) {
      const rows = group.items.map((item) => introRow("bolt", item.title, item.text));
      if (group.version) list.append(introGroup(tr("Version {0}", group.version), rows));
      else { const plain = node("section", "intro-group"); plain.append(...rows); list.append(plain); }
    }
    body.append(list);
  };
}

async function openNews(items, first = false) {
  const done = await openSheet({
    title: tr("Das ist neu"),
    sub: tr("Das hat sich seit deinem letzten Besuch für dich geändert."),
    ok: tr("Okay"),
    panel: newsPanel([{ items }]),
  });
  if (first && done === true) await confirmWelcome("news");
}

async function openNewsHistory() {
  let history = [];
  try { history = await api("api/news"); } catch { /* leer */ }
  await openSheet({
    title: tr("Das ist neu"),
    sub: tr("Die Neuerungen der letzten Versionen."),
    ok: tr("Fertig"),
    panel: newsPanel(history),
  });
}

async function showWelcome() {
  const welcome = state.me?.welcome;
  if (!welcome || welcomeShown || sheetDone) return;
  welcomeShown = true;
  if (welcome.intro) await openIntro(true);
  else if (welcome.news?.length) await openNews(welcome.news, true);
}

// ------------------------------------------------- GitHub-Konto der Person

const GITHUB_URL = /^https:\/\/github\.com\/[A-Za-z0-9\/_?=&.-]*$/;

function githubLevelText(level) {
  return level === "write" ? tr("Die KI darf mit deinem Konto lesen und (nach deiner Bestätigung) ändern.") : tr("Die KI darf mit deinem Konto lesen.");
}

// Der Dialog fragt bei GitHub nach, solange er offen ist; ``alive()`` wird falsch, sobald er geschlossen wurde.
function githubPanel(body, alive) {
  let timer = 0;
  const stop = () => { clearTimeout(timer); timer = 0; };
  const hint = (text) => node("p", "mem-hint", text);
  const button = (label, kind, handler, logo = false) => {
    const b = node("button", `pill ${kind}`);
    if (logo) b.append(icon("github", true));
    b.append(node("span", "", label));
    b.type = "button";
    b.addEventListener("click", () => { handler(b); });
    return b;
  };
  const actions = (...buttons) => { const row = node("div", "gh-actions"); row.append(...buttons); return row; };
  const fail = (error, fallback) => toast(error?.detail || fallback);
  const refreshMe = async () => { try { state.me = await api("api/me"); syncIncognito(); } catch { /* beim nächsten Laden */ } };

  const show = (...parts) => { if (alive()) body.replaceChildren(...parts); };

  const load = async () => {
    stop();
    show(hint(tr("Lade …")));
    let info;
    try { info = await api("api/github/account"); } catch { show(hint(tr("GitHub ist gerade nicht abrufbar. Versuche es gleich noch einmal."))); return; }
    if (info.source === "personal") renderConnected(info);
    else if (info.level === "none") show(hint(tr("Für dich ist GitHub nicht freigegeben. Der Administrator stellt das in der Add-on-Konfiguration ein (github_access).")));
    else renderStart(info);
  };

  const renderConnected = (info) => {
    const who = node("p", "gh-who");
    who.append(icon("github", true), node("span", "", tr("Verbunden als {0}", info.login || "GitHub")));
    show(
      who,
      hint(githubLevelText(info.level)),
      hint(tr("Das Token liegt verschlüsselt im Add-on und verlässt es nicht. Beim Trennen löscht das Add-on es; der Zugang bei GitHub bleibt bestehen, bis du ihn dort unter Einstellungen → Anwendungen widerrufst.")),
      actions(button(tr("Trennen"), "danger", () => renderDisconnect(info))),
    );
  };

  // Rückfrage im selben Fenster: ein zweites Fenster würde dieses schließen.
  const renderDisconnect = (info) => {
    show(
      hint(tr("GitHub trennen? Die KI kann dann nicht mehr auf dein GitHub zugreifen.")),
      actions(
        button(tr("Trennen"), "danger", async (b) => {
          b.disabled = true;
          try { await api("api/github/account", { method: "DELETE" }); toast(tr("GitHub getrennt.")); await refreshMe(); load(); }
          catch (e) { b.disabled = false; fail(e, tr("Das Trennen hat nicht geklappt.")); }
        }),
        button(tr("Abbrechen"), "ghost", () => renderConnected(info)),
      ),
    );
  };

  const renderStart = (info) => {
    const parts = [];
    parts.push(hint(tr("Verbinde dein GitHub-Konto, dann kann die KI deine Repositories lesen und, wenn du es erlaubst, Änderungen vorschlagen. Jede Änderung bestätigst du im Chat.")));
    parts.push(hint(githubLevelText(info.level)));
    parts.push(actions(
      button(tr("Mit GitHub verbinden"), "primary", (b) => startDevice(b), true),
      button(tr("Token einfügen"), "ghost", () => renderToken()),
    ));
    show(...parts);
  };

  const startDevice = async (b) => {
    b.disabled = true;
    let data;
    try { data = await api("api/github/device", { method: "POST" }); } catch (e) { b.disabled = false; fail(e, tr("Die Anmeldung bei GitHub ließ sich nicht starten.")); return; }
    const status = node("p", "mem-hint gh-wait", tr("Warte auf deine Bestätigung bei GitHub …"));
    const link = node("a", "pill primary");
    link.append(icon("github", true), node("span", "", tr("GitHub öffnen")));
    if (GITHUB_URL.test(data.verification_uri)) { link.href = data.verification_uri; link.target = "_blank"; link.rel = "noopener noreferrer"; }
    const code = node("div", "gh-code");
    const copy = node("button", "icon-btn gh-copy");
    copy.type = "button";
    copy.title = tr("Kopieren");
    copy.setAttribute("aria-label", tr("Kopieren"));
    copy.append(icon("copy"));
    copy.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(data.user_code); toast(tr("Kopiert.")); } catch { toast(tr("Zum Kopieren Strg+C drücken.")); }
    });
    code.append(node("span", "gh-code-text", data.user_code), copy);
    show(
      hint(tr("1. Öffne GitHub und gib diesen Code ein. 2. Bestätige den Zugriff. Danach geht es hier von selbst weiter.")),
      code,
      actions(link, button(tr("Abbrechen"), "ghost", async () => { stop(); try { await api("api/github/device", { method: "DELETE" }); } catch { /* egal */ } load(); })),
      status,
      hint(tr("Der Code gilt {0} Minuten.", String(Math.round(data.expires_in / 60)))),
    );
    const wait = (data.interval || 5) * 1000;
    const poll = async () => {
      if (!alive()) return;
      let result;
      try { result = await api("api/github/device/poll", { method: "POST" }); } catch (e) { status.textContent = e?.detail || tr("GitHub antwortet gerade nicht. Ich versuche es weiter …"); timer = setTimeout(poll, wait * 2); return; }
      if (!alive()) return;
      if (result.status === "ok") { toast(tr("GitHub verbunden.")); await refreshMe(); load(); }
      else if (result.status === "pending") timer = setTimeout(poll, (result.interval || data.interval || 5) * 1000);
      else {
        const text = result.status === "denied" ? tr("Du hast den Zugriff bei GitHub abgelehnt.") : tr("Der Code ist abgelaufen.");
        show(hint(text), actions(button(tr("Neu starten"), "primary", () => load())));
      }
    };
    timer = setTimeout(poll, wait);
  };

  const renderToken = () => {
    const input = node("input", "field");
    input.type = "password";
    input.autocomplete = "off";
    input.spellcheck = false;
    input.maxLength = 400;
    input.setAttribute("aria-label", tr("GitHub-Token"));
    input.placeholder = "github_pat_…";
    const save = button(tr("Speichern"), "primary", async (b) => {
      if (!input.value.trim()) { input.focus(); return; }
      b.disabled = true;
      try { await api("api/github/token", { method: "POST", body: JSON.stringify({ token: input.value }) }); input.value = ""; toast(tr("GitHub verbunden.")); await refreshMe(); load(); }
      catch (e) { b.disabled = false; fail(e, tr("Das Token ließ sich nicht speichern.")); }
    });
    input.addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); save.click(); } });
    show(
      hint(tr("Erzeuge bei GitHub unter Einstellungen → Entwicklereinstellungen → Personal access tokens ein Token, nur mit den Repositories und Rechten, die die KI haben soll (Contents, Pull requests, Issues). Das Token wird geprüft und verschlüsselt gespeichert.")),
      input,
      actions(save, button(tr("Zurück"), "ghost", () => load())),
    );
    if (window.matchMedia("(pointer: fine)").matches) input.focus();
  };

  load();
  return stop;
}

async function openGithub() {
  let open = true;
  let stop = () => {};
  await openSheet({
    title: tr("GitHub"),
    ok: tr("Fertig"),
    panel: (body) => {
      const logo = icon("github", true);
      logo.classList.add("gh-title-logo");
      $("sheet-title").prepend(logo);  // das Fenster wird für andere Inhalte weiterverwendet; setzt deren Titel neu und entfernt das Logo
      stop = githubPanel(body, () => open);
    },
  });
  open = false;
  stop();
}

// ------------------------------------------------- Einstellungen (eigene Seite)
// Links die Gruppen, rechts der Inhalt der gewählten Seite. Die Inhalte sind dieselben Fenster-Panels wie früher (Gedächtnis,
// GitHub, Meine Daten …), nur nicht mehr in einem Dialog. Auf schmalen Bildschirmen erscheint erst die Liste, dann der Inhalt.

const settingsUi = { page: "general", content: false, modal: false };
let settingsStop = () => {};

function rememberView(view) {
  try {
    if (view === "chat") sessionStorage.removeItem("ki-view");
    else sessionStorage.setItem("ki-view", view);
  } catch { /* optional */ }
}

function rememberDetail(detail) {
  try { sessionStorage.setItem("ki-view-detail", detail || ""); } catch { /* optional */ }
}

function rememberedView() {
  try { return [sessionStorage.getItem("ki-view") || "", sessionStorage.getItem("ki-view-detail") || ""]; } catch { return ["", ""]; }
}

function themeRow() {
  const row = node("div", "set-row");
  const text = node("div", "set-row-text");
  text.append(node("b", "", tr("Design")), node("span", "", tr("Hell, dunkel oder wie dein Gerät.")));
  const seg = node("div", "seg");
  seg.setAttribute("role", "group");
  seg.setAttribute("aria-label", tr("Design"));
  const current = () => window.kiTheme.get();
  const draw = () => seg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.value === current())));
  for (const [value, label] of THEMES) {
    const b = node("button", "", label);
    b.type = "button";
    b.dataset.value = value;
    b.addEventListener("click", () => { window.kiTheme.set(value); draw(); });
    seg.append(b);
  }
  draw();
  row.append(text, seg);
  return row;
}

// „Standardmodell“: gilt in jedem neuen Chat. Auto = das in der App eingestellte Modell. Im Chat selbst lässt es sich jederzeit ändern.
function defaultModelRow() {
  const row = node("div", "set-row");
  const text = node("div", "set-row-text");
  const hint = node("span", "", tr("Gilt in jedem neuen Chat; im Chat kannst du es jederzeit wechseln."));
  text.append(node("b", "", tr("Standardmodell")), hint);
  const select = node("select", "field set-select");
  select.setAttribute("aria-label", tr("Standardmodell"));
  select.append(new Option(`${tr("Auto")} (${modelLabel(concreteModel(AUTO))})`, AUTO));
  const [claude, openai] = modelGroups();
  for (const m of claude) select.append(new Option(m.label, m.id));
  if (openai.length) {
    const group = document.createElement("optgroup");
    group.label = tr("ChatGPT (OpenAI)");
    for (const m of openai) group.append(new Option(m.label, m.id));
    select.append(group);
  }
  select.value = validModel(state.me?.user_model) && state.me.user_model ? state.me.user_model : AUTO;
  const note = () => { hint.textContent = modelProvider(select.value) === "openai" ? tr("ChatGPT läuft bei OpenAI: Nachrichten und Anhänge neuer Chats gehen dorthin, nicht an Claude.") : tr("Gilt in jedem neuen Chat; im Chat kannst du es jederzeit wechseln."); };
  note();
  select.addEventListener("change", async () => {
    const wanted = select.value;
    try {
      const saved = await api("api/me/model", { method: "PUT", body: JSON.stringify({ model: wanted }) });
      state.me.user_model = saved.model;
      note();
      markTools();
      refreshLimits().catch(() => {});
      toast(tr("Standardmodell gespeichert."));
    } catch {
      toast(tr("Das hat nicht geklappt."));
      select.value = validModel(state.me?.user_model) && state.me.user_model ? state.me.user_model : AUTO;
      note();
    }
  });
  row.append(text, select);
  return row;
}

function settingsGeneral(body) {
  const list = node("div", "set-rows");
  if (document.documentElement.dataset.themeSource !== "ha") list.append(themeRow());
  else list.append(node("p", "mem-hint", tr("Das Design übernimmt der HA Copilot von Home Assistant (Profil → Design).")));
  const lang = node("div", "set-row");
  const text = node("div", "set-row-text");
  text.append(node("b", "", tr("Sprache")), node("span", "", tr("Der Administrator legt sie in der Add-on-Konfiguration fest (language).")));
  lang.append(text, node("span", "set-value", kiLang === "en" ? "English" : "Deutsch"));
  list.append(lang);
  if ((state.me?.models?.length || 0) > 1) list.append(defaultModelRow());
  const who = node("div", "set-row");
  const whoText = node("div", "set-row-text");
  whoText.append(node("b", "", tr("Angemeldet als")), node("span", "", state.me?.label || ""));
  who.append(whoText);
  list.append(who);
  body.append(list);
}

function usageBar(fraction, tone = "") {
  const bar = node("div", "usage-bar" + (tone ? ` ${tone}` : ""));
  bar.setAttribute("role", "progressbar");
  bar.setAttribute("aria-valuemin", "0");
  bar.setAttribute("aria-valuemax", "100");
  bar.setAttribute("aria-valuenow", String(Math.round(fraction * 100)));
  const fill = node("span");
  fill.style.width = `${Math.max(2, Math.min(100, Math.round(fraction * 100)))}%`;
  bar.append(fill);
  return bar;
}

async function settingsUsage(body, alive) {
  body.append(node("p", "mem-hint", tr("Wird geladen …")));
  let data;
  try { data = await api("api/usage"); } catch { if (alive()) body.replaceChildren(node("p", "mem-empty", tr("Die Nutzung ist gerade nicht erreichbar."))); return; }
  if (!alive()) return;
  const parts = [];

  const plan = node("section", "set-block");
  plan.append(node("h4", "", tr("Claude-Abo")));
  const WINDOW_NAMES = {
    five_hour: [tr("Aktuelle Sitzung"), tr("Fenster von 5 Stunden")],
    seven_day: [tr("Diese Woche"), tr("Wochenlimit")],
    seven_day_opus: [tr("Diese Woche: Opus"), tr("Wochenlimit für Opus")],
    seven_day_sonnet: [tr("Diese Woche: Sonnet"), tr("Wochenlimit für Sonnet")],
    overage: [tr("Zusatznutzung"), ""],
  };
  const windows = data.windows || [];
  if (!windows.length) {
    plan.append(node("p", "set-lead", data.limits.length ? tr("Ein Limit ist fast oder ganz erreicht.") : tr("Noch keine Angabe zum Limit.")));
    plan.append(node("p", "mem-hint", tr("Sobald die KI zum ersten Mal antwortet, meldet Claude den Stand, und er erscheint hier.")));
  }
  for (const w of windows) {
    const [name, hint] = WINDOW_NAMES[w.type] || [tr("Nutzungslimit"), ""];
    const pct = typeof w.utilization === "number" ? Math.max(0, Math.min(100, Math.round(w.utilization * 100))) : null;
    const rejected = w.status === "rejected";
    const row = node("div", "usage-row");
    const head = node("div", "usage-head");
    const title = node("b", "", name);
    if (hint) title.title = hint;
    head.append(title, node("span", "", w.expired ? tr("zurückgesetzt") : rejected ? tr("erreicht") : pct !== null ? tr("{0} % verwendet", pct) : tr("kein Wert gemeldet")));
    row.append(head);
    if (!w.expired && (pct !== null || rejected)) row.append(usageBar(rejected ? 1 : pct / 100, rejected ? "bad" : w.status === "allowed_warning" ? "warn" : ""));
    const info = [];
    if (w.expired) info.push(tr("Das Fenster wurde zurückgesetzt. Der neue Stand erscheint mit der nächsten Antwort der KI."));
    else {
      if (pct !== null && !rejected) info.push(tr("Noch {0} % übrig", 100 - pct));
      if (w.resets_at) info.push(tr("Zurücksetzung {0}", whenText(w.resets_at)));
    }
    if (w.seen_at) info.push(tr("Stand: {0}", stampText(w.seen_at)));
    row.append(node("span", "usage-sub", info.join(" · ")));
    plan.append(row);
  }
  plan.append(node("p", "mem-hint", tr("Das Limit gehört dem Abo und gilt für alle Personen im Add-on zusammen. Die Werte meldet Claude mit jeder Antwort der KI; die Seite zeigt den letzten gemeldeten Stand.")));
  parts.push(plan);

  const gpt = data.openai;
  if (gpt?.enabled) {
    const box = node("section", "set-block");
    box.append(node("h4", "", tr("ChatGPT in diesem Monat")));
    const fmt = (n) => n.toLocaleString(kiLocale);
    box.append(node("p", "set-lead", gpt.limit ? tr("{0} von {1} Token verbraucht.", fmt(gpt.used), fmt(gpt.limit)) : tr("{0} Token verbraucht (kein Limit).", fmt(gpt.used))));
    if (gpt.limit) box.append(usageBar(Math.min(1, gpt.used / gpt.limit), gpt.used >= gpt.limit ? "bad" : gpt.used >= gpt.limit * 0.8 ? "warn" : ""));
    box.append(node("p", "mem-hint", tr("Zählt Eingabe und Ausgabe aller deiner Chats mit ChatGPT-Modellen. Titel und Zusammenfassungen zählen nicht mit. Ist das Limit erreicht, fragt der Chat vor jeder weiteren Antwort nach. Der Zähler beginnt jeden Monat neu.")));
    parts.push(box);
  }

  const img = data.images;
  const pics = node("section", "set-block");
  pics.append(node("h4", "", tr("Bilder in diesem Monat")));
  if (img.enabled) {
    const used = img.used;
    pics.append(node("p", "set-lead", img.limit ? tr("{0} von {1} Bildern erzeugt.", used, img.limit) : trn(used, "{0} Bild erzeugt (kein Limit).", "{0} Bilder erzeugt (kein Limit).", used)));
    if (img.limit) pics.append(usageBar(Math.min(1, used / img.limit), used >= img.limit ? "bad" : ""));
    pics.append(node("p", "mem-hint", tr("Zählt Fotos und Kunstbilder von OpenAI oder Google. Einfache Grafiken (SVG) kosten nichts und zählen nicht.")));
  } else {
    pics.append(node("p", "mem-hint", tr("Fotos und Kunstbilder sind nicht eingerichtet. Einfache Grafiken zeichnet die KI kostenlos als SVG.")));
  }
  parts.push(pics);
  body.replaceChildren(...parts);
}

// Meldungen aufs Handy: an/aus und auf welchen Geräten (Home-Assistant-App). Die Meldung kommt nur, wenn eine Antwort ungelesen bleibt.
function notifyPanel(body, alive) {
  const box = node("div", "notify-box");
  body.append(box);
  let data = null;
  let busy = false;
  const save = async (enabled, devices) => {
    if (busy) return;
    busy = true;
    try {
      data = await api("api/notify", { method: "PUT", body: JSON.stringify({ enabled, devices }) });
    } catch { toast(tr("Das hat nicht geklappt.")); }
    busy = false;
    if (alive()) draw();
  };
  const chosen = () => data.devices.filter((d) => d.selected).map((d) => d.service);
  const draw = () => {
    const parts = [];
    const row = node("div", "set-row");
    const text = node("div", "set-row-text");
    text.append(node("b", "", tr("Meldungen aufs Handy")), node("span", "", tr("Wenn du eine Antwort nicht liest, melde ich mich nach etwa {0} Sekunden. Ist der Chat auf einem deiner Geräte offen, bleibt es still. Sobald du ihn liest, verschwindet die Meldung wieder.", data.delay)));
    const toggle = node("button", "sched-switch");
    toggle.type = "button";
    toggle.setAttribute("role", "switch");
    toggle.setAttribute("aria-checked", String(data.enabled));
    toggle.setAttribute("aria-label", tr("Meldungen aufs Handy"));
    toggle.append(node("span", "knob"));
    toggle.addEventListener("click", () => save(!data.enabled, chosen()));
    row.append(text, toggle);
    parts.push(row);
    const list = node("div", "notify-devices");
    list.append(node("h4", "", tr("Geräte")));
    if (!data.devices.length) {
      list.append(node("p", "mem-hint", tr("Zu dir gehört in Home Assistant noch kein Gerät mit der App. Melde dich in der App an und ordne das Gerät in Home Assistant deiner Person zu (Einstellungen → Personen), dann erscheint es hier.")));
    }
    for (const device of data.devices) {
      const label = node("label", "notify-dev");
      const box2 = node("input");
      box2.type = "checkbox";
      box2.checked = device.selected;
      box2.disabled = !data.enabled;
      box2.addEventListener("change", () => save(data.enabled, data.devices.filter((d) => (d === device ? box2.checked : d.selected)).map((d) => d.service)));
      const name = node("span", "notify-dev-name", device.label);
      label.append(box2, name);
      list.append(label);
    }
    if (data.devices.length) list.append(node("p", "mem-hint", tr("Hier stehen nur Geräte, die in Home Assistant zu dir gehören. Fehlt eins, ordne es dort deiner Person zu (Einstellungen → Personen). Die Auswahl gilt auch für geplante Aufgaben mit „Zusätzlich aufs Handy“.")));
    parts.push(list);
    box.replaceChildren(...parts);
  };
  api("api/notify").then((value) => { if (alive()) { data = value; draw(); } }).catch(() => {
    if (alive()) box.replaceChildren(node("p", "mem-empty", tr("Die Geräte sind gerade nicht abrufbar.")));
  });
}

function settingsGroups() {
  const me = state.me || {};
  const page = (id, iconName, label, sub, render, extra = {}) => ({ id, icon: iconName, label, sub, render, ...extra });
  const prefs = [
    page("general", "sliders", tr("Allgemein"), "", settingsGeneral),
    page("usage", "gauge", tr("Nutzung"), tr("Wie viel vom Abo, von ChatGPT und von den Bildern verbraucht ist."), settingsUsage),
  ];
  if (me.memory) prefs.push(page("memory", "memory", tr("Gedächtnis"), tr("Die KI merkt sich, was du ihr sagst, und nutzt es in allen Chats. Du kannst jeden Eintrag löschen."), memoryPanel));
  if (me.github_connect) prefs.push(page("github", "github", "GitHub", tr("Verbinde dein GitHub-Konto, damit die KI mit deinen Repositories arbeiten kann."), githubPanel, { solid: true }));
  if (me.notify) prefs.push(page("notify", "bell", tr("Benachrichtigungen"), tr("Wann und wohin ich dir aufs Handy Bescheid gebe."), notifyPanel));
  prefs.push(page("data", "data", tr("Meine Daten"), tr("Nimm deine Daten mit oder räume auf. Es betrifft nur dein Profil."), dataPanel));
  const help = [
    page("guide", "info", tr("Kurzanleitung"), tr("Kurz erklärt, wie du mit mir arbeitest."), introPanel),
    page("news", "bolt", tr("Das ist neu"), tr("Die Neuerungen der letzten Versionen."), async (body, alive) => {
      let history = [];
      try { history = await api("api/news"); } catch { /* leer */ }
      if (alive()) newsPanel(history)(body);
    }),
  ];
  if (me.setup) help.push(page("setup", "setup", tr("Einrichtungsprüfung"), tr("Was eingerichtet ist und was noch fehlt, mit den genauen Schritten. Geändert wird in der Add-on-Konfiguration."), setupPanel));
  return [{ title: tr("Präferenzen"), items: prefs }, { title: tr("Hilfe"), items: help }];
}

// Ein Eintrag der Einstellungsliste. Am Handy wird daraus eine Zeile mit Pfeil, am Laptop ein Menüpunkt.
function settingsItem(item, current) {
  const b = node("button", "set-item" + (item.link ? " is-link" : "") + (item.out ? " is-out" : ""));
  b.type = "button";
  b.append(icon(item.icon, !!item.solid), node("span", "", item.label), icon("chevron"));
  b.lastChild.classList.add("set-chev");
  if (!item.link && item === current) b.setAttribute("aria-current", "page");
  b.addEventListener("click", () => {
    if (item.link) { closeSettingsModal(true); item.go(); return; }
    settingsUi.page = item.id;
    settingsUi.content = true;
    if (!settingsUi.modal) rememberDetail(item.id);
    renderSettings();
    settingsScrollTop();
  });
  return b;
}

function renderSettings() {
  settingsStop();
  settingsStop = () => {};
  const wrap = $(settingsUi.modal ? "set-modal-wrap" : "set-wrap");
  const me = state.me || {};
  const groups = settingsGroups();
  const pages = groups.flatMap((g) => g.items).filter((i) => !i.link);
  const current = pages.find((i) => i.id === settingsUi.page) || pages[0];
  settingsUi.page = current.id;
  wrap.classList.toggle("on-content", settingsUi.content);

  const nav = node("nav", "set-nav");
  nav.setAttribute("aria-label", tr("Einstellungen"));
  // Nur am Handy sichtbar: wer eingeloggt ist, wie in der Claude-App.
  const who = node("header", "set-user");
  const whoAvatar = node("span", "avatar", "");
  fillAvatar(whoAvatar, me.label);
  who.append(whoAvatar, node("span", "set-user-text", me.label || ""));
  nav.append(who);
  const section = (title, items) => {
    const sec = node("div", title ? "set-sec" : "set-sec set-sec-plain");
    if (title) sec.append(node("p", "set-group", title));
    const card = node("div", "set-card");
    for (const item of items) card.append(settingsItem(item, current));
    sec.append(card);
    nav.append(sec);
  };
  for (const group of groups) section(group.title, group.items);
  // Am Laptop steht „Abmelden“ im Konto-Menü, am Handy gibt es kein Menü mehr.
  if (me.can_logout) section("", [{ id: "logout", icon: "logout", label: tr("Abmelden"), go: logout, link: true, out: true }]);

  const main = node("section", "set-main");
  const back = node("button", "set-back");
  back.type = "button";
  back.append(icon("chevron"), node("span", "", tr("Zurück")));
  back.addEventListener("click", () => { settingsUi.content = false; renderSettings(); });
  const title = node("h3", "", current.label);
  main.append(back, title);
  if (current.sub) main.append(node("p", "set-sub", current.sub));
  const body = node("div", "set-body");
  main.append(body);
  wrap.replaceChildren(nav, main);

  let alive = true;
  const stop = current.render(body, () => alive);
  settingsStop = () => { alive = false; if (typeof stop === "function") stop(); };
  if (stop && typeof stop.catch === "function") stop.catch(() => {});
}

// Laptop und Tablet: großes Fenster über dem Chat (wie bei Claude). Handy: eigene Seite mit Liste und Inhalt.
function settingsScrollTop() {
  if (settingsUi.modal) document.querySelectorAll("#set-modal .set-main").forEach((el) => { el.scrollTop = 0; });
  else $("settings").scrollTop = 0;
}

let settingsReturn = null;

function closeSettingsModal(keepFocus = false) {
  if (!settingsUi.modal) return;
  settingsUi.modal = false;
  settingsStop();
  settingsStop = () => {};
  $("set-modal").classList.remove("show");
  $("set-scrim").classList.remove("show");
  setTimeout(() => { if (!settingsUi.modal) $("set-modal").hidden = true; }, 220);
  const back = settingsReturn;
  settingsReturn = null;
  if (!keepFocus && back && document.contains(back)) back.focus();
}

function openSettingsModal(page) {
  const modal = $("set-modal");
  settingsReturn = document.activeElement instanceof HTMLElement ? document.activeElement : $("account");
  settingsUi.modal = true;
  if (page) settingsUi.page = page;
  settingsUi.content = true;
  $("set-modal-title").textContent = tr("Einstellungen");
  $("set-modal-close").setAttribute("aria-label", tr("Schließen"));
  modal.hidden = false;
  renderSettings();
  requestAnimationFrame(() => {
    modal.classList.add("show");
    $("set-scrim").classList.add("show");
    modal.focus({ preventScroll: true });
  });
}

function initSettingsModal() {
  $("set-modal-close").append(icon("close"));
  $("set-modal-close").addEventListener("click", () => closeSettingsModal());
  $("set-scrim").addEventListener("click", () => closeSettingsModal());
  $("set-modal").addEventListener("keydown", (event) => {
    if (event.key !== "Tab") return;
    const items = [...$("set-modal").querySelectorAll("button, a[href], input, select, textarea, [tabindex]:not([tabindex='-1'])")].filter((el) => !el.disabled && el.offsetParent !== null);
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && (document.activeElement === first || document.activeElement === $("set-modal"))) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });
  window.matchMedia("(max-width: 760px)").addEventListener("change", (event) => { if (event.matches) closeSettingsModal(true); });
}

async function openSettings(page = "") {
  if (!state.me) return;
  if (!narrowScreen()) { openSettingsModal(page); return; }
  settingsUi.modal = false;
  setView("settings");
  detachRun();
  releaseRecent();
  state.activeId = null;
  rememberActive();
  state.newProject = null;
  state.heldUnread = null;
  renderSide();
  closeMenu();
  setTitle(tr("Einstellungen"));
  if (page) { settingsUi.page = page; settingsUi.content = true; }
  else settingsUi.content = false;
  rememberDetail(page || settingsUi.page);
  renderSettings();
  settingsScrollTop();
}

// ------------------------------------------------- Konto-Menü (unten in der Seitenleiste)

const THEMES = [["auto", tr("Auto")], ["light", tr("Hell")], ["dark", tr("Dunkel")]];

// Wie bei Claude: nur das Wichtigste im Popup; Gedächtnis, Kurzanleitung, Neuerungen usw. stehen in den Einstellungen.
function accountEntries() {
  const entries = [{ value: "settings", icon: "sliders", label: tr("Einstellungen") }, { value: "usage", icon: "gauge", label: tr("Nutzung") }];
  if (state.me?.setup) entries.push({ value: "setup", icon: "setup", label: tr("Einrichtungsprüfung") });
  if (state.me?.can_logout) {
    entries.push({ divider: true });
    entries.push({ value: "logout", icon: "logout", label: tr("Abmelden") });
  }
  return entries;
}

async function logout() {
  try { await api("auth/logout", { method: "POST" }); } catch { /* Sitzung ist dann ohnehin weg */ }
  window.location.assign("login");
}

async function accountMenu() {
  // Am Handy kein Menü: wie in der Claude-App geht es direkt in die Einstellungen (Nutzung, Abmelden usw. stehen dort).
  if (narrowScreen()) { await openSettings(); return; }
  const entries = accountEntries();
  const button = $("account");
  button.setAttribute("aria-expanded", "true");
  let choice;
  try {
    choice = wideScreen()
      ? await openPopover(button, state.me?.label ? [{ heading: state.me.label }, ...entries] : entries)
      : await openSheet({ title: state.me?.label || tr("Konto"), items: entries.filter((e) => !e.divider) });
  } finally {
    button.setAttribute("aria-expanded", "false");
  }
  closeMenu();
  const pages = { settings: "", usage: "usage", setup: "setup" };
  if (typeof choice === "string" && choice in pages) openSettings(pages[choice]).catch(() => {});
  else if (choice === "logout") await logout();
}

// Listen im Eingabefeld: „1. “, „- “ oder „* “ am Zeilenanfang wird eingerückt; Umschalt+Enter (am Handy Enter) führt die Liste fort,
// auf einem leeren Punkt beendet es sie; Tab und Umschalt+Tab rücken einen Punkt ein oder aus.
const LIST_LINE = /^(\s*)(?:(\d{1,3})([.)])|([-*•]))\s+(.*)$/;
const LIST_INDENT = "  ";
const LIST_MAX_INDENT = 6;

// Ersetzt from..to; mit ``caret`` steht der Cursor danach dort (sonst hinter dem eingefügten Text)
function replaceInField(area, from, to, text, caret) {
  area.setSelectionRange(from, to);
  let done = false;
  try { done = document.execCommand("insertText", false, text); } catch { /* ältere Browser */ }
  if (!done) {
    area.setRangeText(text, from, to, "end");
    area.dispatchEvent(new Event("input", { bubbles: true }));
  }
  if (caret !== undefined) area.setSelectionRange(caret, caret);
}

function currentLine(area) {
  const value = area.value;
  const caret = area.selectionStart;
  const start = value.lastIndexOf("\n", caret - 1) + 1;
  let end = value.indexOf("\n", caret);
  if (end < 0) end = value.length;
  return { start, end, caret, text: value.slice(start, end) };
}

// true, wenn die Taste behandelt wurde (dann kein Standardverhalten)
function listEnter(area) {
  if (area.selectionStart !== area.selectionEnd) return false;
  const line = currentLine(area);
  const m = LIST_LINE.exec(line.text);
  if (!m || line.caret - line.start < m[0].length - m[5].length) return false; // Cursor steht noch vor dem Aufzählungszeichen
  const [, indent, number, sep, bullet, content] = m;
  if (!content.trim()) {
    replaceInField(area, line.start, line.end, "", line.start); // leerer Punkt: Liste beenden
    return true;
  }
  const marker = number ? `${Number(number) + 1}${sep}` : bullet;
  replaceInField(area, line.caret, line.caret, `\n${indent}${marker} `);
  return true;
}

function listTab(area, outdent) {
  if (area.selectionStart !== area.selectionEnd) return false;
  const line = currentLine(area);
  const m = LIST_LINE.exec(line.text);
  if (!m) return false;
  const indent = m[1].length;
  if (outdent) {
    if (!indent) return false;
    const cut = Math.min(indent, LIST_INDENT.length);
    replaceInField(area, line.start, line.start + cut, "", Math.max(line.start, line.caret - cut));
    return true;
  }
  if (indent >= LIST_MAX_INDENT) return false;
  replaceInField(area, line.start, line.start, LIST_INDENT, line.caret + LIST_INDENT.length);
  return true;
}

// Wer am Zeilenanfang „1. “, „- “ oder „* “ tippt, bekommt den Punkt gleich eingerückt
function listIndentOnType(area, event) {
  if (event.inputType !== "insertText" || event.data !== " " || area.selectionStart !== area.selectionEnd) return;
  const line = currentLine(area);
  const before = line.text.slice(0, line.caret - line.start);
  if (/^(?:[-*•]|\d{1,2}[.)]) $/.test(before)) replaceInField(area, line.start, line.start, LIST_INDENT, line.caret + LIST_INDENT.length);
}

async function init() {
  initSheet();
  initSettingsModal();
  setStreaming(false);

  loadUi();
  $("menu").addEventListener("click", openMenu);
  $("menu-composer").addEventListener("click", openMenu);
  $("drawer-scrim").addEventListener("click", closeMenu);
  $("new-chat").addEventListener("click", () => startNew());
  $("nav-schedules").addEventListener("click", () => { openSchedules().catch(() => {}); });
  $("nav-search").addEventListener("click", () => { openSearch().catch(() => {}); });
  $("nav-skills").addEventListener("click", () => { openSkills().catch(() => {}); });
  $("nav-shared").addEventListener("click", () => { openSharedChats().catch(() => {}); });
  initCrumbs();
  initShortcuts();
  $("account").addEventListener("click", () => { accountMenu().catch(() => {}); });
  $("new-chat-top").addEventListener("click", () => startNew());
  $("incognito-top").addEventListener("click", () => toggleIncognito());
  initSideToggle();
  initAttachments();
  initFollow();
  initSideSwipe();
  initQuotePicker();
  $("composer").addEventListener("submit", (event) => {
    event.preventDefault();
    sendMessage().catch(() => {});
  });
  $("input").addEventListener("input", (event) => { listIndentOnType($("input"), event); autosize(); });
  $("input").addEventListener("keydown", (event) => {
    if (event.isComposing) return;
    const touch = window.matchMedia("(pointer: coarse)").matches;
    if (event.key === "Enter" && !event.ctrlKey && !event.metaKey && !event.altKey && (event.shiftKey || touch) && listEnter($("input"))) {
      event.preventDefault(); // Liste fortführen (Umschalt+Enter; am Handy Enter)
    } else if (event.key === "Enter" && !event.shiftKey && !touch) {
      event.preventDefault();
      sendMessage().catch(() => {});
    } else if (event.key === "Tab" && !event.ctrlKey && !event.metaKey && !event.altKey && listTab($("input"), event.shiftKey)) {
      event.preventDefault();
    }
  });

  try {
    state.me = await api("api/me");
    syncIncognito();
    initVoiceButton();
    $("who").textContent = state.me.label;
    fillAvatar($("avatar"), state.me.label);
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
    setInterval(syncPresence, 5000);
    document.addEventListener("visibilitychange", syncPresence);
    window.addEventListener("pagehide", syncPresence);
    syncPresence();
    const [view, detail] = rememberedView();
    const again = rememberedActive();
    if (view === "settings" && narrowScreen()) await openSettings(detail);
    else if (view === "skills") await openSkills(["connectors", "plugins"].includes(detail) ? detail : "skills");
    else if (view === "schedules" && state.me.schedules) await openSchedules();
    else if (again && state.chats.some((c) => c.id === again)) await selectChat(again);
    openSharedFromAddress().catch(() => {});
    showWelcome().catch(() => {});
  } catch {
    $("who").textContent = tr("Nicht angemeldet");
  }
}

init();
