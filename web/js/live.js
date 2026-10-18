// Free singing: my voice on the note lanes, the note name and plain words.

import { MicSource, DemoSource, Drone, ScreenAwake, MicError } from "./audio.js";
import { Chart } from "./chart.js";
import { NoteTracker, tuneWords } from "./feedback.js";
import { SOLFEGE, scaleNoteName } from "./notes.js";
import { scale, settings, titleCase, tolerance, tonicHz } from "./settings.js";
import { onSettingsChange, openSettings, toggleView, viewIcon } from "./sheet.js";
import { LiveTrace, PitchStream, followCenter } from "./stream.js";
import { $, lanesAround, spanFor, toast } from "./ui.js";
import { Yin, dbToRms, rms } from "./yin.js";

export const DEMO = new URLSearchParams(location.search).has("demo");
export const BLOCK = 512;        // samples per audio block, and per pitch estimate (hop)
export const FRAME = 2048;       // samples per YIN frame (about 43 ms at 48 kHz)

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
let active = false;
let loops = 0;                  // id of the current drawing loop; older ones stop

export function enter() {
  active = true;
  tracker = new NoteTracker(scale());
  refresh();
}

export function leave() {
  active = false;
  stopListening();
  drone.stop();
  refresh();
}

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
  if (!active) return stopListening();
  const detector = new Yin({ sampleRate: source.sampleRate, frameLength: FRAME,
                             silenceRms: dbToRms(settings.gate) });
  stream = new PitchStream(detector, tonicHz(), BLOCK, settings.smoothing);
  trace = new LiveTrace(settings.history);
  tracker.reset();
  awake.acquire();
  setListeningUi(true);
  const loop = ++loops;
  requestAnimationFrame((ts) => frame(ts, loop));
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

function draw() {
  if (!active) return;
  const now = trace.latestTime;
  const tonic = tonicHz();
  chart.draw({
    t0: now - settings.history, t1: now, center, span: spanFor(chart),
    lanes: lanesAround(scale(), center), view: settings.view, tolerance: tolerance(),
    name: (c) => scaleNoteName(tonic, c),
    current: tracker.current && now - lastVoiceAt < 1.5 ? tracker.current.position : null,
    layers: [{ times: trace.times, cents: trace.cents, role: "mine" }],
  });
}

function frame(ts, loop) {
  if (!stream || loop !== loops) return;
  const dt = Math.min(0.1, (ts - lastFrame) / 1000);
  lastFrame = ts;
  center = followCenter(center, trace.recentMedian(2), spanFor(chart), dt);
  draw();
  $("micLevel").style.setProperty("--level", level.toFixed(2));
  if (ts - lastReadout > 80) {       // about 12 updates a second keeps the text calm
    lastReadout = ts;
    showReadout(trace.stableCents(0.3));
  }
  requestAnimationFrame((t) => frame(t, loop));
}

function showReadout(cents) {
  const readout = $("live").querySelector(".readout");
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
  if (!stream) text = DEMO ? "Demo mode: tap the button to see a synthetic singer on the chart."
                           : "Your voice will draw here. Hold a note and watch its lane light up.";
  else if (drone.playing) text = "Use headphones with the drone, or the mic hears it too.";
  hint.textContent = text;
  hint.hidden = !text;
}

function refresh() {
  $("keyName").textContent = SOLFEGE[settings.keyIndex];
  $("scaleName").textContent = titleCase(scale().name);
  $("droneBtn").setAttribute("aria-pressed", String(drone.playing));
  viewIcon($("viewBtn"));
  const zone = $("live").querySelector(".meter-zone");
  zone.style.left = `${50 - tolerance() / 2}%`;
  zone.style.width = `${tolerance()}%`;
  updateHint();
  draw();
}

// ---------------------------------------------------------------- controls

$("micBtn").addEventListener("click", () => (stream ? stopListening() : startListening()));

$("droneBtn").addEventListener("click", () => {
  if (drone.playing) drone.stop();
  else drone.start(tonicHz());
  refresh();
});

$("viewBtn").addEventListener("click", () => {
  toggleView();
  toast(settings.view === "notes" ? "Notes view" : "Curve view", 1200);
});

$("keyChip").addEventListener("click", openSettings);

onSettingsChange(() => {
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
  refresh();
});
