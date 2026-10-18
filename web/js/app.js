// The phone live view: wires settings, audio, the pitch pipeline and the chart.

import { MicSource, DemoSource, Drone, ScreenAwake, MicError } from "./audio.js";
import { Chart } from "./chart.js";
import { LEVELS, NoteTracker, tuneWords } from "./feedback.js";
import { SOLFEGE, WESTERN, keyLabel, noteToHz, scaleNoteName } from "./notes.js";
import { Scale, laneEdges, scalesFromJson } from "./scales.js";
import { LiveTrace, PitchStream, followCenter } from "./stream.js";
import { Yin, dbToRms, rms } from "./yin.js";

const DEMO = new URLSearchParams(location.search).has("demo");
const BLOCK = 512;               // samples per audio block, and per pitch estimate (hop)
const FRAME = 2048;              // samples per YIN frame (about 43 ms at 48 kHz)

// Used only if scales.json can't be loaded. `avaz web` exports the real ones.
const FALLBACK_SCALES = {
  shur: { positions: [0, 150, 300, 500, 700, 800, 1000, 1200] },
  mahur: { positions: [0, 200, 400, 500, 700, 900, 1100, 1200] },
};

const DEFAULTS = {
  keyIndex: 2, octave: 3, fine: 0,   // Re (D3) until the singer picks their own key
  scale: "dashti", level: "gentle", view: "notes",
  smoothing: 3, history: 6, gate: -55, drone: false, configured: false,
};

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------- settings

function loadSettings() {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem("avaz.settings") || "{}") };
  } catch {
    return { ...DEFAULTS };
  }
}

function saveSettings() {
  try {
    localStorage.setItem("avaz.settings", JSON.stringify(settings));
  } catch { /* private mode: settings last for this visit only */ }
}

const settings = loadSettings();
let scales = scalesFromJson(FALLBACK_SCALES);

const tonicHz = () => noteToHz(settings.keyIndex, settings.octave) * Math.pow(2, settings.fine / 1200);
const scale = () => scales[settings.scale] || Object.values(scales)[0];
const tolerance = () => (LEVELS[settings.level] || LEVELS.gentle).tolerance;
const titleCase = (s) => s.charAt(0).toUpperCase() + s.slice(1);

// ---------------------------------------------------------------- state

const chart = new Chart($("chart"), () => draw());
const drone = new Drone();
const awake = new ScreenAwake();
let trace = new LiveTrace(settings.history);
let tracker = new NoteTracker(scale());
let source = null;
let stream = null;
let level = 0;                  // mic loudness 0..1 for the ring around the button
let center = 100;               // cents at the middle of the chart
let lastVoiceAt = -Infinity;    // trace time of the last voiced frame
let lastFrame = performance.now();
let lastReadout = 0;

// ---------------------------------------------------------------- listening

async function startListening() {
  source = DEMO ? new DemoSource(BLOCK) : new MicSource(BLOCK);
  try {
    await source.start(onBlock, tonicHz, () => scale().positions);
  } catch (err) {
    source = null;
    toast(err instanceof MicError ? err.message : `Could not start: ${err.message}`);
    return;
  }
  const detector = new Yin({ sampleRate: source.sampleRate, frameLength: FRAME,
                             silenceRms: dbToRms(settings.gate) });
  stream = new PitchStream(detector, tonicHz(), BLOCK, settings.smoothing);
  trace = new LiveTrace(settings.history);
  tracker.reset();
  awake.acquire();
  setListeningUi(true);
  requestAnimationFrame(frame);
}

function stopListening() {
  if (source) source.stop();
  source = null;
  stream = null;
  level = 0;
  awake.release();
  setListeningUi(false);
}

function onBlock(block) {
  if (!stream) return;
  const points = stream.process(block);
  trace.append(points);
  for (const [t, , c] of points) if (Number.isFinite(c)) lastVoiceAt = t;
  // Loudness on a dB scale from the gate (0) to 30 dB above it (1).
  const db = 20 * Math.log10(rms(block) + 1e-9);
  level = Math.max(0, Math.min(1, (db - settings.gate) / 30));
}

function setListeningUi(on) {
  $("micBtn").classList.toggle("on", on);
  $("micBtn").setAttribute("aria-label", on ? "Stop listening" : "Start listening");
  $("micLabel").textContent = on ? (DEMO ? "Demo voice, tap to stop" : "Listening, tap to stop") : "Tap to sing";
  $("micLevel").style.setProperty("--level", 0);
  if (!on) showReadout(null);
  updateHint();
  draw();
}

// ---------------------------------------------------------------- drawing

function lanes() {
  const lo = center - 1600, hi = center + 1600;
  const centers = [...new Set(scale().positionsInRange(lo, hi).map(([c]) => Math.round(c * 1000) / 1000))];
  return laneEdges(centers);
}

function span() {
  // About 50 px per lane: more notes on a tall portrait chart, fewer in landscape.
  return Math.max(800, Math.min(1600, chart.h * 2.7));
}

function draw() {
  const now = trace.latestTime;
  const tonic = tonicHz();
  chart.draw({
    times: trace.times, cents: trace.cents, now, history: settings.history,
    center, span: span(), lanes: lanes(), view: settings.view, tolerance: tolerance(),
    name: (c) => scaleNoteName(tonic, c),
    current: tracker.current && now - lastVoiceAt < 1.5 ? tracker.current.position : null,
  });
}

function frame(ts) {
  if (!stream) return;
  const dt = Math.min(0.1, (ts - lastFrame) / 1000);
  lastFrame = ts;
  center = followCenter(center, trace.recentMedian(2), span(), dt);
  draw();
  $("micLevel").style.setProperty("--level", level.toFixed(2));
  if (ts - lastReadout > 80) {       // about 12 updates a second keeps the text calm
    lastReadout = ts;
    showReadout(trace.stableCents(0.3));
  }
  requestAnimationFrame(frame);
}

function showReadout(cents) {
  const readout = document.querySelector(".readout");
  const name = $("noteName"), dot = $("meterDot"), detail = $("detail");
  if (!stream) {
    readout.className = "readout";
    name.className = "note-name idle";
    name.textContent = "Ready";
    $("words").textContent = "Tap the mic and sing";
    dot.classList.remove("on");
    detail.hidden = true;
    return;
  }
  const note = tracker.update(cents);
  const silentFor = trace.latestTime - lastVoiceAt;
  if (!Number.isFinite(cents)) {
    readout.className = "readout";
    name.className = note && silentFor < 3 ? "note-name faded" : "note-name idle";
    name.textContent = note && silentFor < 3 ? scaleNoteName(tonicHz(), note.position) : "Listening";
    $("words").textContent = note && silentFor < 3 ? "" : "Sing a long note";
    dot.classList.remove("on");
    detail.hidden = true;
    return;
  }
  const dev = cents - note.position;
  const tune = tuneWords(dev, settings.level);
  readout.className = `readout state-${tune.state}`;
  name.className = "note-name";
  name.textContent = scaleNoteName(tonicHz(), note.position);
  $("words").textContent = tune.words;
  // The meter spans 100 cents either side of the note.
  dot.style.left = `${50 + Math.max(-46, Math.min(46, dev / 2))}%`;
  dot.classList.add("on");
  detail.hidden = settings.level !== "detailed";
  if (!detail.hidden) {
    const hz = tonicHz() * Math.pow(2, cents / 1200);
    detail.textContent = `${dev >= 0 ? "+" : ""}${dev.toFixed(0)} cents · ${hz.toFixed(1)} Hz`;
  }
}

function updateHint() {
  const hint = $("hint");
  let text = "";
  if (!stream) text = DEMO ? "Demo mode: tap the button to hear a synthetic singer on the chart."
                           : "Your voice will draw here. Hold a note and watch its lane light up.";
  else if (drone.playing) text = "Use headphones with the drone, or the mic hears it too.";
  hint.textContent = text;
  hint.hidden = !text;
}

// ---------------------------------------------------------------- header

function refreshHeader() {
  $("keyName").textContent = SOLFEGE[settings.keyIndex];
  $("scaleName").textContent = titleCase(scale().name);
  $("droneBtn").setAttribute("aria-pressed", String(drone.playing));
  // Icon shows what a tap switches to.
  $("viewIco").innerHTML = settings.view === "notes"
    ? '<path d="M3 15c3-8 5 4 8-3s5 2 10-5"/>'
    : '<path d="M4 7h7M13 12h7M6 17h8"/>';
  const zone = document.querySelector(".meter-zone");
  zone.style.left = `${50 - tolerance() / 2}%`;
  zone.style.width = `${tolerance()}%`;
}

$("micBtn").addEventListener("click", () => (stream ? stopListening() : startListening()));

$("droneBtn").addEventListener("click", () => {
  if (drone.playing) drone.stop();
  else drone.start(tonicHz());
  refreshHeader();
  updateHint();
});

$("viewBtn").addEventListener("click", () => {
  settings.view = settings.view === "notes" ? "curve" : "notes";
  saveSettings();
  refreshHeader();
  toast(settings.view === "notes" ? "Notes view" : "Curve view", 1200);
  draw();
});

$("keyChip").addEventListener("click", openSettings);

// ---------------------------------------------------------------- settings sheet

function options(container, items, current, onPick) {
  container.innerHTML = "";
  for (const { value, label, small } of items) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "opt";
    b.setAttribute("role", "radio");
    b.setAttribute("aria-checked", String(value === current));
    b.innerHTML = small ? `${label}<small>${small}</small>` : label;
    b.addEventListener("click", () => { onPick(value); applySettings(); });
    container.append(b);
  }
}

function renderSheet() {
  options($("keyGrid"), SOLFEGE.map((s, i) => ({ value: i, label: s, small: WESTERN[i] })),
    settings.keyIndex, (v) => (settings.keyIndex = v));
  options($("octaves"), [2, 3, 4].map((o) => ({
    value: o, label: `${WESTERN[settings.keyIndex]}${o}`,
    small: o === 2 ? "low" : o === 3 ? "middle" : "high",
  })), settings.octave, (v) => (settings.octave = v));
  $("fine").value = settings.fine;
  const fine = settings.fine ? ` ${settings.fine > 0 ? "+" : ""}${settings.fine} cents` : "";
  $("keyHz").textContent = `${keyLabel(noteToHz(settings.keyIndex, settings.octave))}${fine}, ${tonicHz().toFixed(1)} Hz`;
  $("keyIntro").classList.toggle("attention", !settings.configured);
  options($("scales"), Object.keys(scales).map((n) => ({ value: n, label: titleCase(n) })),
    scale().name, (v) => (settings.scale = v));
  options($("levels"), [
    { value: "gentle", label: "Gentle", small: "plain words" },
    { value: "detailed", label: "Detailed", small: "with cents" },
  ], settings.level, (v) => (settings.level = v));
  options($("smoothing"), [[1, "Off"], [3, "Light"], [7, "Strong"]].map(([v, l]) => ({ value: v, label: l })),
    settings.smoothing, (v) => (settings.smoothing = v));
  options($("history"), [4, 6, 10].map((v) => ({ value: v, label: `${v} s` })),
    settings.history, (v) => (settings.history = v));
  $("gate").value = settings.gate;
  $("gateHelp").textContent = `Sounds quieter than ${settings.gate} dB are ignored. ` +
    "Raise it in a noisy room, lower it if soft singing is missed.";
}

$("fine").addEventListener("input", (e) => { settings.fine = Number(e.target.value); applySettings(); });
$("gate").addEventListener("input", (e) => { settings.gate = Number(e.target.value); applySettings(); });

function openSettings() {
  renderSheet();
  $("settings").showModal();
}

$("settings").addEventListener("close", () => {
  settings.configured = true;
  saveSettings();
  renderSheet();
});

// Tap on the dimmed backdrop closes the sheet.
$("settings").addEventListener("click", (e) => {
  if (e.target === $("settings")) $("settings").close();
});

function applySettings() {
  saveSettings();
  tracker = new NoteTracker(scale());
  if (stream) {
    // A new key changes every cents value; start the trace fresh.
    if (stream.tonicHz !== tonicHz()) trace = new LiveTrace(settings.history);
    stream.tonicHz = tonicHz();
    stream.smoothingFrames = settings.smoothing;
    stream.detector.silenceRms = dbToRms(settings.gate);
    trace.historySeconds = settings.history;
  }
  drone.setTonic(tonicHz());
  renderSheet();
  refreshHeader();
  draw();
}

// ---------------------------------------------------------------- misc

let toastTimer = null;
function toast(text, ms = 4000) {
  const t = $("toast");
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), ms);
}

async function init() {
  try {
    const res = await fetch("scales.json", { cache: "no-cache" });
    if (res.ok) scales = scalesFromJson(await res.json());
  } catch { /* offline without a cached copy: built-in scales */ }
  tracker = new NoteTracker(scale());
  refreshHeader();
  updateHint();
  draw();
  if (!settings.configured) openSettings();
  if ("serviceWorker" in navigator && window.isSecureContext) {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }
}

init();

// For the browser console and tests.
window.avaz = { settings, get trace() { return trace; }, get center() { return center; }, Scale };
