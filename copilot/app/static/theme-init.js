"use strict";

// Läuft vor dem ersten Zeichnen (blockierend im <head>), damit die Seite nicht kurz in der falschen Farbwelt aufblitzt.
//
// Eingebettet in Home Assistant (Ingress, gleiche Herkunft) übernimmt die Seite live die Farben des aktiven HA-Themes
// (Profil des Benutzers, Hell/Dunkel von HA) und blendet den eigenen Hell/Dunkel-Umschalter aus. Ohne Einbettung
// (Domain) oder wenn der Zugriff auf HA nicht klappt, gilt der eigene Umschalter (Auto/Hell/Dunkel) und das
// Standard-Theme, das der Server als branding/theme.css liefert.
(function () {
  const KEY = "ki-theme";
  const dark = window.matchMedia("(prefers-color-scheme: dark)");
  const stored = () => {
    try { return localStorage.getItem(KEY) || "auto"; } catch { return "auto"; }
  };
  const root = document.documentElement;
  const embedded = root.dataset.embed === "ha";
  const follow = root.dataset.followHa !== "false";

  // Variablen von Home Assistant, aus denen die Oberfläche ihre Farben ableitet (siehe theme.css).
  const HA_VARS = [
    "primary-color", "primary-background-color", "card-background-color", "sidebar-background-color",
    "primary-text-color", "secondary-text-color", "text-primary-color", "error-color", "warning-color",
  ];
  let applied = [];

  function luminance(color) {
    let m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(color);
    let rgb;
    if (m) {
      const hex = m[1].length === 3 ? m[1].replace(/./g, "$&$&") : m[1];
      rgb = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16));
    } else {
      m = /^rgba?\(\s*(\d+)[ ,]+(\d+)[ ,]+(\d+)/i.exec(color);
      if (!m) return null;
      rgb = [+m[1], +m[2], +m[3]];
    }
    return (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255;
  }

  // Aktuelles Aussehen von Home Assistant: { mode, vars } oder null (nicht eingebettet / kein Zugriff).
  function haLook() {
    if (!embedded) return null;
    try {
      const parentDoc = window.parent.document;
      const style = getComputedStyle(parentDoc.documentElement);
      const vars = {};
      for (const name of HA_VARS) {
        const value = style.getPropertyValue("--" + name).trim();
        if (value) vars[name] = value;
      }
      const lum = luminance(vars["primary-background-color"] || "");
      if (lum === null) return null;
      let mode = lum < 0.5 ? "dark" : "light";
      try {
        const flag = parentDoc.querySelector("home-assistant")?.hass?.themes?.darkMode;
        if (typeof flag === "boolean") mode = flag ? "dark" : "light";
      } catch { /* Luminanz genügt */ }
      return { mode, vars };
    } catch {
      return null;
    }
  }

  const apply = () => {
    const look = follow ? haLook() : null;
    for (const name of applied) root.style.removeProperty("--" + name);
    applied = [];
    if (look) {
      for (const [name, value] of Object.entries(look.vars)) {
        root.style.setProperty("--" + name, value);
        applied.push(name);
      }
      root.dataset.theme = look.mode;
      root.dataset.mode = "ha";
      root.dataset.themeSource = "ha";
      return;
    }
    const mode = stored();
    root.dataset.theme = mode === "auto" ? (dark.matches ? "dark" : "light") : mode;
    root.dataset.mode = mode;
    root.dataset.themeSource = "own";
  };

  // Hintergrund-Muster (Einstellungen → Allgemein → Design). Die Wahl gehört der Person und liegt im Add-on (gilt auf jedem Gerät);
  // hier steht nur die letzte bekannte Wahl dieses Geräts, damit das Muster ohne Aufblitzen sofort da ist. Gezeichnet wird es in style.css.
  const DESIGN_KEY = "ki-design";
  const DESIGNS = ["dots", "hex", "plus", "plain"];
  const storedDesign = () => {
    try {
      const v = localStorage.getItem(DESIGN_KEY);
      return DESIGNS.includes(v) ? v : "dots";
    } catch { return "dots"; }
  };
  root.dataset.design = storedDesign();
  window.kiDesign = {
    options: DESIGNS,
    get: () => root.dataset.design,
    set(value) {
      const v = DESIGNS.includes(value) ? value : "dots";
      try { localStorage.setItem(DESIGN_KEY, v); } catch { /* optional */ }
      root.dataset.design = v;
    },
  };

  window.kiTheme = {
    get: stored,
    set(mode) {
      try { localStorage.setItem(KEY, mode); } catch { /* optional */ }
      apply();
    },
  };
  dark.addEventListener("change", apply);
  if (embedded && follow) {
    document.addEventListener("visibilitychange", apply);
    // HA schreibt die Theme-Variablen als Stil an das Wurzelelement; bei jeder Änderung neu übernehmen.
    try {
      new MutationObserver(apply).observe(window.parent.document.documentElement, { attributes: true, attributeFilter: ["style", "class"] });
    } catch { /* kein Zugriff: dann bleibt es bei der Abfrage beim Sichtbarwerden */ }
  }
  apply();
})();
