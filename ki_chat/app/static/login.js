"use strict";

const stage = document.getElementById("stage");
const form = document.getElementById("form");
const email = document.getElementById("email");
const errEl = document.getElementById("err");
const go = document.getElementById("go");
const goLabel = document.getElementById("go-label");
const errHa = document.getElementById("err-ha");
const GO_TEXT = tr("Mit Microsoft anmelden");

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/;

// Rückmeldung nach der Rückkehr von Microsoft (?e=…), danach die Adresszeile säubern.
const RETURN_ERRORS = {
  denied: tr("Dieses Konto ist für den Dienst nicht freigegeben."),
  failed: tr("Die Anmeldung hat nicht geklappt. Bitte erneut versuchen."),
  expired: tr("Die Anmeldung ist abgelaufen. Bitte noch einmal starten."),
  cancelled: tr("Die Anmeldung wurde abgebrochen."),
  throttled: tr("Zu viele Versuche. Bitte in ein paar Minuten erneut versuchen."),
};

function setState(name) { stage.dataset.state = name; }
function showError(text) {
  errEl.textContent = text;
  email.setAttribute("aria-invalid", text ? "true" : "false");
}

{
  const code = new URLSearchParams(window.location.search).get("e");
  if (code && RETURN_ERRORS[code]) {
    if (document.documentElement.dataset.entra === "false") errHa.textContent = RETURN_ERRORS[code];
    else showError(RETURN_ERRORS[code]);
    window.history.replaceState(null, "", window.location.pathname);
  }
}

email.addEventListener("input", () => showError(""));

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const value = email.value.trim().toLowerCase();
  if (!EMAIL.test(value)) {
    showError(tr("Bitte eine vollständige E-Mail-Adresse eingeben."));
    email.focus();
    return;
  }
  setState("busy");
  go.disabled = true;
  goLabel.textContent = tr("Verbinde mit Microsoft …");
  try {
    const response = await fetch("auth/start", {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-Requested-With": "ki-chat", "Content-Type": "application/json" },
      body: JSON.stringify({ email: value }),
    });
    if (response.ok) {
      const data = await response.json();
      if (typeof data.redirect === "string" && /^https:\/\//.test(data.redirect)) {
        window.location.assign(data.redirect);
        return;
      }
    }
    const messages = {
      503: tr("Microsoft ist gerade nicht erreichbar. Bitte gleich noch einmal versuchen."),
      403: tr("Für diese Adresse gibt es keinen Zugang."),
      429: tr("Zu viele Versuche. Bitte in ein paar Minuten erneut versuchen."),
    };
    showError(messages[response.status] || tr("Die Anmeldung ist gerade nicht möglich."));
  } catch {
    showError(tr("Keine Verbindung. Bitte erneut versuchen."));
  }
  go.disabled = false;
  goLabel.textContent = GO_TEXT;
  setState("idle");
});
