"use strict";
// Sprechen mit der KI (Etappe 1: per Knopf). Nutzt die Hilfen aus app.js ($, node, icon, api, tr, toast, state).
//
// Ablauf: Knopf -> Fenster mit Partikel-Ring -> Aufnahme (Pause am Satzende beendet sie) -> api/voice/transcribe ->
// Text. Erst fragt der schnelle Pfad (api/chats/<id>/voice: Home Assistant versteht den Satz selbst, ohne KI),
// sonst geht der Satz als gesprochene Nachricht an die KI (sendMessage mit voice). Die Antwort wird vorgelesen.
// Der Ton wird nicht gespeichert: nur im Arbeitsspeicher aufgenommen, als WAV zum Server gesendet und verworfen.

const VOICE = {
  RATE: 16000,
  MAX_SECONDS: 30,
  END_SILENCE: 1.1,     // so lange Stille nach dem Sprechen beendet die Aufnahme
  START_WAIT: 12,       // so lange wartet das Fenster auf den Satzanfang, danach „Tippe zum Sprechen“
  MIN_SPEECH: 0.25,
  CHUNK_CHARS: 600,
  open: false,
  state: "idle",        // idle | listening | thinking | speaking | muted | error
  muted: false,
  chatId: null,         // Chat, in den geschrieben wird
  standalone: false,    // Sprachgespräch außerhalb eines Chats (nicht in der Chatliste)
  used: false,
  token: 0,             // erhöht sich bei Schließen/Neustart: alte Schleifen hören dann auf
  stream: null, ctx: null, source: null, proc: null, level: 0, target: 0,
  audio: null, urls: [], rec: null, meter: true,
  returnFocus: null,
};

const reducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

// ------------------------------------------------------------- Knopf und Fenster

function voiceAllowed() { return !!state.me?.voice; }

function initVoiceButton() {
  const old = $("voice-btn");
  if (!voiceAllowed()) { old?.remove(); return; }
  if (old) return;
  const button = node("button", "send voice-btn has-tip", "");
  button.id = "voice-btn";
  button.type = "button";
  button.setAttribute("aria-label", tr("Mit der KI sprechen"));
  button.dataset.tip = tr("Mit der KI sprechen");
  button.append(icon("mic"));
  button.addEventListener("click", () => openVoice());
  $("send").before(button);
}

function voiceOverlay() {
  let box = $("voice");
  if (box) return box;
  box = node("div", "voice");
  box.id = "voice";
  box.hidden = true;
  box.setAttribute("role", "dialog");
  box.setAttribute("aria-modal", "true");
  box.setAttribute("aria-label", tr("Sprachgespräch"));
  const canvas = node("canvas", "voice-ring");
  canvas.id = "voice-ring";
  canvas.setAttribute("aria-hidden", "true");
  const status = node("p", "voice-status", "");
  status.id = "voice-status";
  status.setAttribute("aria-live", "polite");
  const said = node("p", "voice-said", "");
  said.id = "voice-said";
  const answer = node("p", "voice-answer", "");
  answer.id = "voice-answer";
  const bar = node("div", "voice-bar");
  const mute = node("button", "voice-btn-round", "");
  mute.id = "voice-mute";
  mute.type = "button";
  mute.setAttribute("aria-pressed", "false");
  mute.append(icon("mic"));
  mute.setAttribute("aria-label", tr("Mikrofon stummschalten"));
  mute.addEventListener("click", () => setMuted(!VOICE.muted));
  const talk = node("button", "voice-btn-round voice-talk", "");
  talk.id = "voice-talk";
  talk.type = "button";
  talk.append(icon("wave"));
  talk.setAttribute("aria-label", tr("Sprechen"));
  talk.addEventListener("click", () => talkNow());
  const close = node("button", "voice-btn-round voice-close", "");
  close.id = "voice-close";
  close.type = "button";
  close.append(icon("close"));
  close.setAttribute("aria-label", tr("Sprachgespräch beenden"));
  close.addEventListener("click", () => closeVoice());
  bar.append(mute, talk, close);
  const keep = node("button", "voice-keep", tr("Als Chat behalten"));
  keep.id = "voice-keep";
  keep.type = "button";
  keep.hidden = true;
  keep.addEventListener("click", () => keepVoiceChat());
  const hint = node("p", "voice-hint", "");
  hint.id = "voice-hint";
  box.append(canvas, status, said, answer, bar, keep, hint);
  document.addEventListener("keydown", (e) => {
    if (!VOICE.open) return;
    if (e.key === "Escape") { e.preventDefault(); closeVoice(); }
    if (e.key === "Tab") { // Fokus bleibt im Fenster
      const items = [...box.querySelectorAll("button:not([hidden])")];
      if (!items.length) return;
      const first = items[0], last = items[items.length - 1];
      if (!box.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
      else if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });
  document.body.append(box);
  return box;
}

const STATUS_TEXT = () => ({
  idle: tr("Tippe zum Sprechen"),
  listening: tr("Ich höre zu …"),
  thinking: tr("Ich denke nach …"),
  speaking: tr("Ich antworte …"),
  muted: tr("Mikrofon aus"),
  error: tr("Das hat nicht geklappt"),
});

function setVoiceState(next, detail = "") {
  VOICE.state = next;
  const box = $("voice");
  if (!box) return;
  box.dataset.state = next;
  $("voice-status").textContent = detail || STATUS_TEXT()[next];
  $("voice-talk").disabled = next === "thinking" || next === "muted";
  kickRing();
}

async function openVoice() {
  if (VOICE.open || !voiceAllowed()) return;
  if (!navigator.mediaDevices?.getUserMedia || !window.isSecureContext) {
    toast(tr("Das Mikrofon geht nur über eine sichere Verbindung (https)."));
    return;
  }
  if (state.streaming) { toast(tr("Warte kurz, bis die Antwort fertig ist.")); return; }
  const box = voiceOverlay();
  VOICE.returnFocus = document.activeElement;
  VOICE.open = true;
  VOICE.used = false;
  VOICE.muted = false;
  VOICE.chatId = state.activeId || null;
  VOICE.standalone = !state.activeId;
  const token = ++VOICE.token;
  $("voice-said").textContent = "";
  $("voice-answer").textContent = "";
  $("voice-keep").hidden = true;
  $("voice-mute").setAttribute("aria-pressed", "false");
  $("voice-hint").textContent = state.me.voice_wake
    ? tr("Sage zum Beispiel: „{0}, mach das Licht im Wohnzimmer aus“", state.me.voice_wake)
    : "";
  box.hidden = false;
  document.body.classList.add("voice-open");
  setVoiceState("idle");
  $("voice-close").focus();
  startRing();
  voiceLoop(token);
}

// Welche Spracherkennung gilt: "server" (OpenAI oder Home Assistant), "browser" (kostenloser Rückfall) oder "" (keine).
async function recognitionMode() {
  voiceInfo = null; // jedes Mal frisch fragen, damit eine neue Einstellung gleich greift
  const info = await voiceSettings();
  if (info.stt) return "server";
  if (info.browser && (window.SpeechRecognition || window.webkitSpeechRecognition)) return "browser";
  return "";
}

async function missingText() {
  const info = await voiceSettings();
  return info.browser
    ? tr("Dieser Browser hat keine eingebaute Spracherkennung. Trage in der Add-on-Konfiguration unter „Sprechen mit der KI“ einen OpenAI-Schlüssel ein oder richte in Home Assistant unter Sprachassistenten eine Spracherkennung ein.")
    : tr("Es ist keine Spracherkennung eingerichtet. Trage in der Add-on-Konfiguration unter „Sprechen mit der KI“ einen OpenAI-Schlüssel ein oder richte in Home Assistant unter Sprachassistenten eine Spracherkennung ein.");
}

function closeVoice() {
  if (!VOICE.open) return;
  VOICE.token++;
  stopCapture();
  stopSpeaking();
  VOICE.open = false;
  stopRing();
  const box = $("voice");
  if (box) box.hidden = true;
  document.body.classList.remove("voice-open");
  const wasStandalone = VOICE.standalone && VOICE.chatId;
  if (wasStandalone && state.activeId === VOICE.chatId) {
    // Das Gespräch steht nicht in der Chatliste: Ansicht zurück auf „Neuer Chat“.
    try { startNew(); } catch { /* optional */ }
  }
  VOICE.chatId = null;
  VOICE.standalone = false;
  if (VOICE.returnFocus?.isConnected) VOICE.returnFocus.focus();
}

async function keepVoiceChat() {
  const id = VOICE.chatId;
  if (!id) return;
  try {
    await api(`api/chats/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify({ keep: true }) });
    VOICE.standalone = false; // bleibt offen und steht jetzt in der Chatliste
    $("voice-keep").hidden = true;
    await loadAll();
    toast(tr("Das Gespräch steht jetzt in deinen Chats."));
  } catch {
    toast(tr("Das Gespräch konnte nicht übernommen werden."));
  }
}

function setMuted(on) {
  VOICE.muted = on;
  const mute = $("voice-mute");
  mute.setAttribute("aria-pressed", on ? "true" : "false");
  mute.setAttribute("aria-label", on ? tr("Mikrofon einschalten") : tr("Mikrofon stummschalten"));
  mute.classList.toggle("off", on);
  if (on) {
    VOICE.token++;           // laufende Aufnahme verwerfen
    stopCapture();
    if (VOICE.state === "listening") setVoiceState("muted");
    else if (VOICE.state === "idle") setVoiceState("muted");
  } else if (VOICE.state === "muted") {
    setVoiceState("idle");
    voiceLoop(++VOICE.token);
  }
}

// Knopf „Sprechen“: unterbricht das Vorlesen oder startet eine neue Aufnahme
function talkNow() {
  if (!VOICE.open || VOICE.state === "thinking") return;
  if (VOICE.muted) setMuted(false);
  stopSpeaking();
  stopCapture();
  voiceLoop(++VOICE.token);
}

// ------------------------------------------------------------- Aufnahme

async function startCapture() {
  VOICE.stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  const Ctx = window.AudioContext || window.webkitAudioContext;
  VOICE.ctx = new Ctx();
  if (VOICE.ctx.state === "suspended") await VOICE.ctx.resume();
  VOICE.source = VOICE.ctx.createMediaStreamSource(VOICE.stream);
  VOICE.proc = VOICE.ctx.createScriptProcessor(4096, 1, 1);
  const mute = VOICE.ctx.createGain();
  mute.gain.value = 0; // nichts auf die Lautsprecher zurückgeben
  VOICE.source.connect(VOICE.proc);
  VOICE.proc.connect(mute);
  mute.connect(VOICE.ctx.destination);
}

function stopCapture() {
  try { VOICE.rec?.abort(); } catch { /* schon beendet */ }
  VOICE.rec = null;
  try { VOICE.proc?.disconnect(); } catch { /* schon getrennt */ }
  try { VOICE.source?.disconnect(); } catch { /* schon getrennt */ }
  VOICE.stream?.getTracks().forEach((t) => t.stop());
  try { VOICE.ctx?.close(); } catch { /* schon zu */ }
  VOICE.proc = VOICE.source = VOICE.stream = VOICE.ctx = null;
  VOICE.level = 0;
}

// Ein Satz: wartet auf den Anfang, nimmt auf, bis eine Pause kommt. Gibt 16-kHz-Samples zurück (null = nichts gesagt / abgebrochen).
function recordSentence(token) {
  return new Promise((resolve) => {
    const inRate = VOICE.ctx.sampleRate;
    const chunks = [];
    let heard = false, speech = 0, quiet = 0, waited = 0, floor = 0.01, total = 0;
    let preroll = [];
    VOICE.proc.onaudioprocess = (event) => {
      if (token !== VOICE.token) { VOICE.proc.onaudioprocess = null; resolve(null); return; }
      const data = new Float32Array(event.inputBuffer.getChannelData(0));
      let sum = 0;
      for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
      const rms = Math.sqrt(sum / data.length);
      const seconds = data.length / inRate;
      VOICE.target = Math.min(1, rms * 9);
      const loud = rms > Math.max(0.02, floor * 3.2);
      if (!heard) {
        if (!loud) floor = floor * 0.95 + rms * 0.05; // Grundrauschen mitführen
        preroll.push(data);
        if (preroll.length > 4) preroll.shift(); // etwas Vorlauf, damit der Satzanfang nicht fehlt
        if (loud) { heard = true; chunks.push(...preroll); preroll = []; speech = seconds; quiet = 0; total = seconds; }
        else {
          waited += seconds;
          if (waited > VOICE.START_WAIT) { VOICE.proc.onaudioprocess = null; resolve(null); }
        }
        return;
      }
      chunks.push(data);
      total += seconds;
      if (loud) { speech += seconds; quiet = 0; } else quiet += seconds;
      if (quiet >= VOICE.END_SILENCE || total >= VOICE.MAX_SECONDS) {
        VOICE.proc.onaudioprocess = null;
        resolve(speech >= VOICE.MIN_SPEECH ? downsample(chunks, inRate) : null);
      }
    };
  });
}

function downsample(chunks, inRate) {
  let length = 0;
  for (const c of chunks) length += c.length;
  const all = new Float32Array(length);
  let at = 0;
  for (const c of chunks) { all.set(c, at); at += c.length; }
  if (inRate === VOICE.RATE) return all;
  const ratio = inRate / VOICE.RATE;
  const out = new Float32Array(Math.floor(all.length / ratio));
  for (let i = 0; i < out.length; i++) { // Mittelwert über das Fenster dämpft Störtöne beim Verkleinern
    const from = Math.floor(i * ratio), to = Math.min(all.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = from; j < to; j++) sum += all[j];
    out[i] = sum / Math.max(1, to - from);
  }
  return out;
}

function toWav(samples) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const text = (offset, s) => { for (let i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i)); };
  text(0, "RIFF"); view.setUint32(4, 36 + samples.length * 2, true); text(8, "WAVE"); text(12, "fmt ");
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, VOICE.RATE, true); view.setUint32(28, VOICE.RATE * 2, true);
  view.setUint16(32, 2, true); view.setUint16(34, 16, true); text(36, "data"); view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buffer], { type: "audio/wav" });
}

// ------------------------------------------------------------- Gespräch

function voiceFail(message) {
  setVoiceState("error", message);
  VOICE.level = 0;
}

async function voiceLoop(token) {
  // Eine Runde je Knopfdruck: zuhören, verstehen, antworten. Danach wartet das Fenster auf „Sprechen“.
  const alive = () => VOICE.open && token === VOICE.token;
  if (VOICE.muted) { setVoiceState("muted"); return; }
  try {
    const mode = await recognitionMode();
    if (!mode) { voiceFail(await missingText()); return; }
    if (!alive()) return;
    setVoiceState("listening");
    const heard = mode === "browser" ? await listenBrowser(alive) : await listenServer(token, alive);
    if (!alive() || heard === null) return;
    if (!heard) { setVoiceState("idle"); return; }
    setVoiceState("thinking");
    const sentence = (heard.command || "").trim();
    if (!heard.text?.trim()) { setVoiceState("idle", tr("Ich habe nichts verstanden. Tippe zum Sprechen.")); return; }
    $("voice-said").textContent = heard.text;
    $("voice-answer").textContent = "";
    if (!sentence) { setVoiceState("idle", tr("Ja? Tippe zum Sprechen.")); return; }
    const answer = await handleSentence(sentence, alive);
    if (!alive() || answer === null) return;
    $("voice-answer").textContent = answer;
    VOICE.used = true;
    if (VOICE.standalone) $("voice-keep").hidden = false;
    if (answer) await speak(answer, alive);
    if (alive()) setVoiceState("idle");
  } catch (err) {
    stopCapture();
    if (!alive()) return;
    if (err?.name === "NotAllowedError" || err?.name === "SecurityError") voiceFail(tr("Das Mikrofon ist blockiert. Erlaube es in den Einstellungen des Browsers oder der App."));
    else if (err?.name === "NotFoundError") voiceFail(tr("Es wurde kein Mikrofon gefunden."));
    else voiceFail(err?.message || tr("Das hat nicht geklappt"));
  }
}

// Spracherkennung über das Add-on (OpenAI oder Home Assistant): Aufnahme als WAV hochladen.
// Gibt {text, command} zurück, "" wenn nichts gesagt wurde, null wenn abgebrochen wurde.
async function listenServer(token, alive) {
  await startCapture();
  if (!alive()) { stopCapture(); return null; }
  VOICE.meter = true;
  const samples = await recordSentence(token);
  stopCapture();
  if (!alive()) return null;
  if (!samples) return "";
  setVoiceState("thinking");
  const response = await fetch("api/voice/transcribe", {
    method: "POST", credentials: "same-origin",
    headers: { "X-Requested-With": "ki-chat", "Content-Type": "audio/wav" },
    body: toWav(samples),
  });
  if (response.status === 401) { window.location.assign("login"); return null; }
  if (!response.ok) throw await voiceError(response);
  return await response.json();
}

// Kostenlose Spracherkennung des Browsers (Rückfall ohne Schlüssel): der Ton geht an Google bzw. Apple, nicht an das Add-on.
function listenBrowser(alive) {
  return new Promise((resolve, reject) => {
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const rec = new Recognition();
    rec.lang = voiceInfo?.language === "en" ? "en-US" : "de-DE";
    rec.interimResults = true;
    rec.continuous = false;
    rec.maxAlternatives = 1;
    VOICE.rec = rec;
    VOICE.meter = false;
    let finalText = "", interim = "", done = false;
    const finish = (value, error) => {
      if (done) return;
      done = true;
      clearInterval(watch);
      if (VOICE.rec === rec) VOICE.rec = null;
      if (error) { reject(error); return; }
      resolve(value);
    };
    rec.onresult = (event) => {
      interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const part = event.results[i];
        if (part.isFinal) finalText += part[0].transcript; else interim += part[0].transcript;
      }
      $("voice-said").textContent = (finalText + interim).trim(); // Zwischenstand sofort zeigen
      VOICE.target = 0.6;
    };
    rec.onerror = (event) => {
      if (event.error === "no-speech" || event.error === "aborted") finish("");
      else if (event.error === "not-allowed" || event.error === "service-not-allowed") finish(null, Object.assign(new Error("denied"), { name: "NotAllowedError" }));
      else if (event.error === "audio-capture") finish(null, Object.assign(new Error("none"), { name: "NotFoundError" }));
      else if (event.error === "network") finish(null, new Error(tr("Die Spracherkennung des Browsers ist nicht erreichbar. Prüfe die Internetverbindung.")));
      else finish(null, new Error(tr("Das hat nicht geklappt")));
    };
    rec.onend = () => {
      const text = (finalText || interim).trim();
      finish(text ? { text, command: stripWake(text, state.me?.voice_wake || "") } : "");
    };
    const watch = setInterval(() => { if (!alive()) { try { rec.abort(); } catch { /* schon beendet */ } finish(null); } }, 200);
    try { rec.start(); } catch (err) { finish(null, err); }
  });
}

function stripWake(text, name) {
  // Gleiche Regel wie auf dem Server: „(Hey|Hallo|Hi|OK) <Name>“ am Satzanfang entfernen.
  text = text.replace(/\s+/g, " ").trim();
  name = (name || "").trim();
  if (!name) return text;
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const rest = text.replace(new RegExp("^(?:(?:hey|hallo|hi|ok|okay)[\\s,]+)?" + escaped + "(?![\\w-])[\\s,.:;!?-]*", "i"), "");
  return rest !== text ? rest.trim() : text;
}

async function voiceError(response) {
  let detail = "";
  try { detail = (await response.json()).detail; } catch { /* keine Meldung */ }
  return new Error(typeof detail === "string" && detail ? detail : tr("Die Sprachverbindung hat nicht geklappt."));
}

// Gibt die Antwort zum Vorlesen zurück, "" wenn nichts zu sagen ist, null wenn abgebrochen wurde.
async function handleSentence(sentence, alive) {
  // Neues Sprachgespräch: der Chat entsteht erst jetzt, ohne Eintrag in der Chatliste.
  if (!VOICE.chatId) {
    const chat = await api("api/chats", { method: "POST", body: JSON.stringify({ voice: true }) });
    VOICE.chatId = chat.id;
    state.activeId = chat.id;
    $("thread").replaceChildren();
  }
  const id = VOICE.chatId;
  const quick = await api(`api/chats/${encodeURIComponent(id)}/voice`, { method: "POST", body: JSON.stringify({ text: sentence }) })
    .catch((err) => { if (err.status === 403 || err.status === 409) throw err; return { handled: false }; });
  if (!alive()) return null;
  if (quick.handled) {
    if (!VOICE.standalone) await selectChat(id); // im sichtbaren Chat erscheinen Frage und Antwort
    return quick.speech || "";
  }
  if (state.activeId !== id) return null;
  const out = await sendMessage(null, { text: sentence, voice: true });
  if (!alive()) return null;
  if (!out || out.failure) throw new Error(out?.failure?.message || tr("Die Antwort ist nicht angekommen."));
  return out.answer || "";
}

// ------------------------------------------------------------- Vorlesen

function plainSpeech(text) {
  return text
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]*)`/g, "$1")
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/https?:\/\/\S+/g, "")
    .replace(/[*_#>~|]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function speechChunks(text) {
  const parts = text.match(/[^.!?…]+[.!?…]*\s*/g) || [text];
  const chunks = [];
  let current = "";
  for (const part of parts) {
    if (current && current.length + part.length > VOICE.CHUNK_CHARS) { chunks.push(current.trim()); current = ""; }
    current += part;
  }
  if (current.trim()) chunks.push(current.trim());
  return chunks;
}

let voiceInfo = null;
async function voiceSettings() {
  if (voiceInfo) return voiceInfo;
  try { voiceInfo = await api("api/voice"); } catch { voiceInfo = { speech: "device", language: "" }; }
  return voiceInfo;
}

async function speak(text, alive) {
  const spoken = plainSpeech(text);
  if (!spoken) return;
  setVoiceState("speaking");
  const info = await voiceSettings();
  if (info.speech !== "device") {
    try { await speakService(spoken, alive); return; } catch { /* Stimme des Geräts als Rückfall */ }
  }
  await speakDevice(spoken, alive, info.language);
}

function speakDevice(text, alive, language) {
  return new Promise((resolve) => {
    const synth = window.speechSynthesis;
    if (!synth || !alive()) { resolve(); return; }
    synth.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = language === "en" ? "en-US" : language === "de" ? "de-DE" : (document.documentElement.lang || "de");
    const voice = synth.getVoices().find((v) => v.lang?.toLowerCase().startsWith(utterance.lang.slice(0, 2).toLowerCase()) && v.localService) ||
      synth.getVoices().find((v) => v.lang?.toLowerCase().startsWith(utterance.lang.slice(0, 2).toLowerCase()));
    if (voice) utterance.voice = voice;
    let done = false;
    const finish = () => { if (done) return; done = true; clearInterval(watch); VOICE.level = 0; resolve(); };
    utterance.onend = finish;
    utterance.onerror = finish;
    const watch = setInterval(() => { if (!alive()) { synth.cancel(); finish(); } }, 200); // Fenster zu: sofort still
    VOICE.speaking = true;
    synth.speak(utterance);
  });
}

async function speakService(text, alive) {
  const chunks = speechChunks(text);
  const fetchChunk = async (part) => {
    const response = await fetch("api/voice/speak", {
      method: "POST", credentials: "same-origin",
      headers: { "X-Requested-With": "ki-chat", "Content-Type": "application/json" },
      body: JSON.stringify({ text: part }),
    });
    if (!response.ok) throw await voiceError(response);
    return URL.createObjectURL(await response.blob());
  };
  let next = fetchChunk(chunks[0]);
  for (let i = 0; i < chunks.length; i++) {
    const url = await next;
    VOICE.urls.push(url);
    if (i + 1 < chunks.length) next = fetchChunk(chunks[i + 1]); // das nächste Stück lädt schon, während das erste läuft
    if (!alive()) return;
    await new Promise((resolve, reject) => {
      const audio = new Audio(url);
      VOICE.audio = audio;
      audio.onended = () => resolve();
      audio.onerror = () => reject(new Error(tr("Die Stimme konnte nicht abgespielt werden.")));
      const watch = setInterval(() => { if (!alive()) { audio.pause(); clearInterval(watch); resolve(); } }, 200);
      audio.addEventListener("ended", () => clearInterval(watch));
      audio.play().catch(reject);
    });
    URL.revokeObjectURL(url);
  }
}

function stopSpeaking() {
  try { window.speechSynthesis?.cancel(); } catch { /* optional */ }
  if (VOICE.audio) { try { VOICE.audio.pause(); } catch { /* optional */ } VOICE.audio = null; }
  for (const url of VOICE.urls.splice(0)) URL.revokeObjectURL(url);
  VOICE.level = 0;
}

// ------------------------------------------------------------- Partikel-Kugel mit Ringen
// Eine leuchtende Kugel aus Partikeln (Fibonacci-Kugel, dreht sich, Tiefe über Größe und Helligkeit) mit leuchtendem Kern
// und drei gegenläufigen Ringen aus Bögen. Der Pegel lässt die Kugel pulsieren und den Rand sprühen, beim Antworten laufen
// Wellen über die Oberfläche, beim Nachdenken drehen Kugel und Ringe schneller. Maus (auch Hover) und Finger wischen
// Teilchen weg; sie schwingen zurück. Nur Partikel, keine Linien.

const RING = {
  p: [], frame: 0, running: false, last: 0, rot: 0, spin: 0.2, w: 0, bound: false,
  ptr: { x: 0, y: 0, vx: 0, vy: 0, on: false, t: 0 },
  arcs: [ // Ringe: Radius (Anteil der Breite), Bögen (Länge, Lücke in Grad), Drehrichtung und Tempo
    { r: 0.335, on: 70, off: 30, dir: 1, speed: 0.30, density: 2.4 },
    { r: 0.39, on: 40, off: 20, dir: -1, speed: 0.22, density: 2.0 },
    { r: 0.45, on: 8, off: 10, dir: 1, speed: 0.12, density: 1.6 },
  ],
};

function startRing() {
  const canvas = $("voice-ring");
  const scale = Math.min(2, window.devicePixelRatio || 1);
  const size = Math.round(Math.min(window.innerWidth - 24, window.innerHeight * 0.6, 480));
  canvas.width = canvas.height = Math.round(size * scale);
  canvas.style.width = canvas.style.height = `${size}px`;
  RING.w = canvas.width;
  const small = size < 340;
  const golden = Math.PI * (3 - Math.sqrt(5));
  const sphere = small ? 900 : 1500;
  RING.p = [];
  for (let i = 0; i < sphere; i++) { // Kugel
    const y = 1 - ((i + 0.5) / sphere) * 2, r = Math.sqrt(1 - y * y), a = i * golden;
    RING.p.push({ kind: 0, ux: Math.cos(a) * r, uy: y, uz: Math.sin(a) * r, size: (0.55 + Math.random() * 0.6) * scale, phase: Math.random() * 6.28, ox: 0, oy: 0, vx: 0, vy: 0, k: 0.05 + Math.random() * 0.03 });
  }
  RING.arcs.forEach((ring, ri) => { // Ringe aus Bögen
    const arcs = Math.round(360 / (ring.on + ring.off));
    for (let n = 0; n < arcs; n++) {
      const start = n * (ring.on + ring.off) + ri * 17;
      const count = Math.max(3, Math.round(ring.on * ring.density * (small ? 0.6 : 1)));
      for (let j = 0; j < count; j++) {
        RING.p.push({ kind: 1, ring: ri, a0: (start + (j / count) * ring.on) * Math.PI / 180, jit: (Math.random() - 0.5) * 0.012, size: (0.6 + Math.random() * 0.7) * scale, phase: Math.random() * 6.28, ox: 0, oy: 0, vx: 0, vy: 0, k: 0.05 + Math.random() * 0.03 });
      }
    }
  });
  if (!RING.bound) {
    RING.bound = true;
    const at = (e) => {
      const box = canvas.getBoundingClientRect();
      const x = (e.clientX - box.left) * (canvas.width / box.width), y = (e.clientY - box.top) * (canvas.height / box.height);
      const q = RING.ptr, dt = Math.max(1, e.timeStamp - q.t);
      q.vx = q.on ? (x - q.x) / dt * 16 : 0; q.vy = q.on ? (y - q.y) / dt * 16 : 0; // Wischgeschwindigkeit je Bild
      q.x = x; q.y = y; q.t = e.timeStamp; q.on = true;
      kickRing();
    };
    canvas.addEventListener("pointermove", at);
    canvas.addEventListener("pointerdown", (e) => { canvas.setPointerCapture?.(e.pointerId); at(e); });
    for (const name of ["pointerleave", "pointerup", "pointercancel"]) canvas.addEventListener(name, () => { RING.ptr.on = false; kickRing(); });
  }
  RING.ptr.on = false;
  RING.last = 0;
  kickRing();
}

function kickRing() {
  if (RING.running || !VOICE.open) return;
  RING.running = true;
  const tick = (now) => {
    const energy = stepRing(now);
    if (VOICE.open && (!reducedMotion() || RING.ptr.on || energy > 0.02)) RING.frame = requestAnimationFrame(tick);
    else RING.running = false;
  };
  RING.frame = requestAnimationFrame(tick);
}

function stopRing() { cancelAnimationFrame(RING.frame); RING.running = false; RING.ptr.on = false; }
function drawRing(now) { stepRing(now); }

function stepRing(now) {
  const canvas = $("voice-ring");
  if (!canvas || !canvas.width || !RING.p.length) return 0;
  const g = canvas.getContext("2d");
  const w = canvas.width, c = w / 2;
  const t = now / 1000, st = VOICE.state, still = reducedMotion();
  const dt = RING.last ? Math.min(0.05, t - RING.last) : 0.016;
  RING.last = t;
  let amp;
  if (st === "listening") amp = VOICE.meter ? VOICE.target : Math.max(VOICE.target, 0.2 + 0.1 * Math.sin(t * 3.1) * Math.sin(t * 1.3)); // Browser-Erkennung liefert keinen Pegel
  else if (st === "speaking") amp = 0.35 + 0.3 * Math.sin(t * 5.1) * Math.sin(t * 2.3);
  else if (st === "thinking") amp = 0.16;
  else amp = 0.04;
  VOICE.level += (amp - VOICE.level) * 0.18;
  VOICE.target *= 0.9;
  const lvl = still ? 0 : VOICE.level;
  const wantSpin = st === "thinking" ? 1.6 : st === "speaking" ? 0.55 : st === "listening" ? 0.4 : 0.22;
  RING.spin += (wantSpin - RING.spin) * 0.05;
  if (!still) RING.rot += dt * RING.spin;
  const speed = st === "thinking" ? 4 : 1;
  const error = st === "error", dim = st === "muted" || st === "idle";
  const hue = error ? "255,112,100" : "96,196,255", hueRing = error ? "255,150,130" : "120,170,255";
  const pulse = still ? 1 : 1 + Math.sin(t * 1.4) * 0.015 + lvl * 0.16;
  const R = w * 0.255 * pulse;
  const q = RING.ptr, reach = w * 0.1;

  g.globalCompositeOperation = "source-over";
  g.clearRect(0, 0, w, w);
  g.globalCompositeOperation = "lighter";
  // Leuchten: weiter Schein, dichter Kern, heller Punkt in der Mitte
  const glow = (radius, alpha, rgb) => {
    radius = Math.min(radius, c); // nie größer als die Fläche, sonst bricht der Schein am Rand als Viereck ab
    const grad = g.createRadialGradient(c, c, 0, c, c, radius);
    for (const [at, k] of [[0, 1], [0.25, 0.62], [0.5, 0.3], [0.75, 0.1], [0.9, 0.025], [1, 0]]) grad.addColorStop(at, `rgba(${rgb},${alpha * k})`); // weich auslaufen
    g.fillStyle = grad; g.beginPath(); g.arc(c, c, radius, 0, Math.PI * 2); g.fill();
  };
  const strength = dim ? 0.7 : 1;
  glow(R * (2.2 + lvl * 1.0), 0.26 * strength, hue);
  glow(R * (1.3 + lvl * 0.4), 0.38 * strength, hue);
  glow(R * 0.55, 0.75 * strength, "200,235,255");

  const cy = Math.cos(RING.rot), sy = Math.sin(RING.rot), tilt = 0.32, ct = Math.cos(tilt), stl = Math.sin(tilt);
  const buckets = [[[], [], [], []], [[], [], [], []]]; // [Kugel, Ringe] x Helligkeitsstufen
  let energy = 0;
  for (const p of RING.p) {
    let sx, sy2, depth = 1, scale = 1, alpha;
    if (p.kind === 0) {
      // Oberfläche: Pegel lässt einzelne Teilchen nach außen springen, beim Antworten laufen Wellen über die Kugel
      const noise = 0.5 + 0.5 * Math.sin(p.phase + t * 6);
      const wave = st === "speaking" ? Math.sin(p.uy * 7 - t * 5) * 0.07 * Math.min(1, lvl * 2.5) : 0;
      const rad = 1 + lvl * 0.42 * noise + wave;
      const x1 = p.ux * cy + p.uz * sy, z1 = -p.ux * sy + p.uz * cy;
      const y2 = p.uy * ct - z1 * stl, z2 = p.uy * stl + z1 * ct;
      depth = (z2 + 1) / 2;
      scale = 1 / (1 - z2 * 0.22);
      sx = c + x1 * R * rad * scale; sy2 = c + y2 * R * rad * scale;
      alpha = 0.18 + 0.82 * depth * depth;
    } else {
      const ring = RING.arcs[p.ring];
      const a = p.a0 + (still ? 0 : t * ring.speed * ring.dir * speed);
      const rr = w * ring.r * (1 + lvl * 0.025 * (p.ring + 1)) * (1 + p.jit);
      sx = c + Math.cos(a) * rr; sy2 = c + Math.sin(a) * rr;
      alpha = 0.35 + 0.35 * (0.5 + 0.5 * Math.sin(p.phase + t * 1.6));
    }
    // Wischen: Versatz je Teilchen, der zurückfedert
    p.vx += -p.ox * p.k; p.vy += -p.oy * p.k;
    if (q.on) {
      const dx = sx + p.ox - q.x, dy = sy2 + p.oy - q.y, d = Math.hypot(dx, dy);
      if (d < reach) {
        const f = (1 - d / reach) ** 2;
        const nx = d > 0.5 ? dx / d : Math.cos(p.phase), ny = d > 0.5 ? dy / d : Math.sin(p.phase);
        p.vx += nx * f * w * 0.016 + q.vx * f * 0.35;
        p.vy += ny * f * w * 0.016 + q.vy * f * 0.35;
      }
    }
    p.vx *= 0.86; p.vy *= 0.86; p.ox += p.vx; p.oy += p.vy;
    energy += Math.abs(p.vx) + Math.abs(p.vy);
    p.sx = sx + p.ox; p.sy = sy2 + p.oy; p.sz = p.size * scale * (p.kind === 0 ? 0.8 + depth * 0.9 : 1) * (1 + lvl * 0.5);
    const a2 = Math.min(1, alpha * (dim ? 0.75 : 1));
    buckets[p.kind][Math.min(3, Math.floor(a2 * 4))].push(p);
  }
  for (let kind = 0; kind < 2; kind++) {
    g.fillStyle = `rgb(${kind ? hueRing : hue})`;
    buckets[kind].forEach((list, i) => {
      g.globalAlpha = (i + 0.6) / 4.2;
      g.beginPath();
      for (const p of list) { g.moveTo(p.sx + p.sz, p.sy); g.arc(p.sx, p.sy, p.sz, 0, Math.PI * 2); }
      g.fill();
    });
  }
  g.globalAlpha = 1;
  g.globalCompositeOperation = "source-over";
  return energy / RING.p.length;
}

document.addEventListener("visibilitychange", () => { if (document.hidden && VOICE.open && VOICE.state === "listening") talkReset(); });
function talkReset() { VOICE.token++; stopCapture(); setVoiceState("idle"); }
