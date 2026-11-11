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
  audio: null, urls: [],
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
  if (reducedMotion()) drawRing(performance.now());
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
    setVoiceState("listening");
    await startCapture();
    if (!alive()) { stopCapture(); return; }
    const samples = await recordSentence(token);
    stopCapture();
    if (!alive()) return;
    if (!samples) { setVoiceState("idle"); return; }
    setVoiceState("thinking");
    const response = await fetch("api/voice/transcribe", {
      method: "POST", credentials: "same-origin",
      headers: { "X-Requested-With": "ki-chat", "Content-Type": "audio/wav" },
      body: toWav(samples),
    });
    if (response.status === 401) { window.location.assign("login"); return; }
    if (!response.ok) throw await voiceError(response);
    const heard = await response.json();
    if (!alive()) return;
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

// ------------------------------------------------------------- Partikel-Ring

let ringFrame = 0, ringParticles = [];

function startRing() {
  const canvas = $("voice-ring");
  const scale = Math.min(2, window.devicePixelRatio || 1);
  const size = Math.min(window.innerWidth, window.innerHeight, 420) * 0.78;
  canvas.width = canvas.height = Math.round(size * scale);
  canvas.style.width = canvas.style.height = `${Math.round(size)}px`;
  ringParticles = Array.from({ length: 150 }, (_, i) => ({
    angle: (i / 150) * Math.PI * 2, jitter: Math.random(), drift: (Math.random() - 0.5) * 0.4, size: 0.8 + Math.random() * 1.6,
  }));
  cancelAnimationFrame(ringFrame);
  const tick = (now) => { drawRing(now); if (VOICE.open && !reducedMotion()) ringFrame = requestAnimationFrame(tick); };
  if (reducedMotion()) drawRing(performance.now()); else ringFrame = requestAnimationFrame(tick);
}

function stopRing() { cancelAnimationFrame(ringFrame); }

function drawRing(now) {
  const canvas = $("voice-ring");
  if (!canvas || !canvas.width) return;
  const g = canvas.getContext("2d");
  const w = canvas.width, c = w / 2;
  g.clearRect(0, 0, w, w);
  const t = now / 1000;
  const st = VOICE.state;
  // Pegel: beim Zuhören vom Mikrofon, beim Antworten ein ruhiges Wogen, beim Denken ein langsames Kreisen
  let amp;
  if (st === "listening") amp = VOICE.target;
  else if (st === "speaking") amp = 0.35 + 0.3 * Math.sin(t * 5.1) * Math.sin(t * 2.3);
  else if (st === "thinking") amp = 0.12;
  else amp = 0.04;
  VOICE.level += (amp - VOICE.level) * 0.18;
  VOICE.target *= 0.9;
  const style = getComputedStyle(document.documentElement);
  const color = st === "error" ? (style.getPropertyValue("--danger").trim() || "#d92d20") : (style.getPropertyValue("--accent").trim() || "#3b82f6");
  const base = w * 0.3;
  const spin = reducedMotion() ? 0 : st === "thinking" ? t * 0.9 : t * 0.12;
  g.fillStyle = color;
  const muted = st === "muted" || st === "idle";
  for (const p of ringParticles) {
    const wobble = Math.sin(p.angle * 5 + t * (st === "speaking" ? 4 : 2.4) + p.jitter * 6) * 0.5 + 0.5;
    const push = reducedMotion() ? 0 : VOICE.level * w * 0.09 * (0.35 + wobble) * (0.6 + p.jitter * 0.8);
    const radius = base + push + p.drift * w * 0.012;
    const a = p.angle + spin * (p.drift > 0 ? 1 : 0.7);
    g.globalAlpha = muted ? 0.35 : 0.45 + 0.55 * wobble;
    g.beginPath();
    g.arc(c + Math.cos(a) * radius, c + Math.sin(a) * radius, p.size * (w / 400) * (1 + VOICE.level * 0.9), 0, Math.PI * 2);
    g.fill();
  }
  g.globalAlpha = 1;
}

document.addEventListener("visibilitychange", () => { if (document.hidden && VOICE.open && VOICE.state === "listening") talkReset(); });
function talkReset() { VOICE.token++; stopCapture(); setVoiceState("idle"); }
