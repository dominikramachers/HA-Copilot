"use strict";
// Sprache der Oberfläche. Die deutschen Texte im Quellcode sind zugleich die Schlüssel; für Englisch liefert der
// Server (branding/lang.js) das Wörterbuch. Platzhalter sind {0}, {1} …; „A||B“ im Wörterbuch heißt Einzahl||Mehrzahl.
const kiLang = (window.kiI18n && window.kiI18n.lang) || "de";
const kiDict = (window.kiI18n && window.kiI18n.dict) || {};
const kiLocale = kiLang === "en" ? "en-GB" : "de-DE";

function tr(text, ...args) {
  let out = Object.prototype.hasOwnProperty.call(kiDict, text) ? kiDict[text] : text;
  if (out.includes("||")) {
    const [one, many] = out.split("||");
    out = args[0] === 1 ? one : many;
  }
  return args.length ? out.replace(/\{(\d+)\}/g, (all, i) => (Number(i) < args.length ? String(args[Number(i)]) : all)) : out;
}

// Einzahl/Mehrzahl: „one“ ohne die Zahl als {0}, „many“ mit der Zahl als {0}.
function trn(n, one, many, ...args) {
  return n === 1 ? tr(one, ...args) : tr(many, n, ...args);
}
