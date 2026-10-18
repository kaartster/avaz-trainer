// Singing after the teacher: play the recording, pause wherever I want, sing the
// stretch back, see both on the note lanes, then go on.

import { DemoSource, MicError, MicSource, ScreenAwake } from "./audio.js";
import { hzToCents } from "./cents.js";
import { Chart } from "./chart.js";
import { DEMO, BLOCK, FRAME } from "./live.js";
import { octaveShift } from "./offline.js";
import { SOLFEGE, hzToNote, keyLabel, scaleNoteName } from "./notes.js";
import { latencyReport, loadPlayer } from "./player.js";
import { keyHz, scale, settings, tolerance } from "./settings.js";
import { keyPicker, onSettingsChange, toggleView, viewIcon } from "./sheet.js";
import { addAttempt, deleteSong, getSong, putSong } from "./store.js";
import { PitchStream, followCenter } from "./stream.js";
import { OnsetDetector, SongSession, Take } from "./turns.js";
import { $, clock, lanesAround, options, spanFor, toast, zoomable } from "./ui.js";
import { Yin, dbToRms, rms } from "./yin.js";

const GRACE = 0.4;               // seconds after a pause when the speaker still rings
const ONSET_DB = -50;            // how loud my voice must be to count as singing

const chart = new Chart($("songChart"), () => draw());
zoomable(chart, () => draw());
const awake = new ScreenAwake();

let song = null;                 // the stored record
let player = null;
let session = null;
let teacher = { times: new Float32Array(0), cents: new Float32Array(0) };
let mic = null, stream = null;
let micTime = 0;                 // seconds of mic audio processed
let loudDb = -120;
let take = null, onset = null;
let center = 100;
let lastFrame = 0;
let active = false;
let token = 0;                   // guards against a slow load finishing after leaving
let lastDebug = 0;
// ?debug shows the audio latency numbers under the title instead of the hint.
const DEBUG = new URLSearchParams(location.search).has("debug");

const teacherTonic = () => song.teacherTonicHz;
const myTonic = () => (song.sameKey ? song.teacherTonicHz : keyHz(song.myKey));

export async function enter(id) {
  active = true;
  const mine = ++token;
  show("Loading", "");
  setButtons();
  try {
    song = await getSong(id);
    if (!song) throw new Error("This recording is not on this phone any more.");
    $("songTitle").textContent = song.name;
    player = await loadPlayer(song.blob);
  } catch (err) {
    if (mine === token) {
      toast(err.message || "Could not open this recording.");
      location.hash = "#/";
    }
    return;
  }
  if (mine !== token) return;
  computeTeacher();
  session = new SongSession(player.duration, song.lastPos || 0);
  $("timeLen").textContent = clock(player.duration);
  center = 100;
  viewIcon($("songViewBtn"));
  player.sync = settings.sync / 1000;
  update();
  const loop = token;
  requestAnimationFrame((ts) => frame(ts, loop));
}

export function leave() {
  active = false;
  token++;
  if (player) player.stop();
  stopMic();
  awake.release();
  if (song && session) {
    song.lastPos = session.phase === "play" ? session.segStart : session.pos;
    putSong(song).catch(() => {});
  }
  song = player = session = take = null;
}

/** The teacher's curve in cents from the teacher's own tonic. */
function computeTeacher() {
  const n = song.f0.length;
  const times = new Float32Array(n), cents = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    times[i] = i * song.hop;
    cents[i] = hzToCents(song.f0[i], teacherTonic());
  }
  teacher = { times, cents };
}

// ---------------------------------------------------------------- mic

async function startMic() {
  if (stream) return true;
  mic = DEMO ? new DemoSource(BLOCK) : new MicSource(BLOCK);
  try {
    await mic.start(onBlock, myTonic, () => scale().positions);
  } catch (err) {
    mic = null;
    toast(err instanceof MicError ? err.message : `Could not start the microphone: ${err.message}`);
    return false;
  }
  const detector = new Yin({ sampleRate: mic.sampleRate, frameLength: FRAME, silenceRms: dbToRms(settings.gate) });
  stream = new PitchStream(detector, myTonic(), BLOCK, settings.smoothing);
  micTime = 0;
  return true;
}

function stopMic() {
  if (mic) mic.stop();
  mic = null;
  stream = null;
}

function onBlock(block) {
  if (!stream || !session) return;
  // The demo voice only sings when it is my turn, like a real singer would.
  if (DEMO && session.phase === "play") block = new Float32Array(block.length);
  loudDb = 20 * Math.log10(rms(block) + 1e-9);
  for (const [t, , c] of stream.process(block)) {
    micTime = t;
    if (!take) continue;
    if (session.phase === "wait") {
      take.listen(t, c);
      const start = onset.feed(t, c, loudDb);
      if (start !== null) {
        take.begin(start);
        session.voiceStarted();
        update();
      }
    } else if (session.phase === "sing") {
      take.add(t, c);
    }
  }
}

// ---------------------------------------------------------------- turns

function newTake() {
  take = new Take(teacher.times, teacher.cents, session.segStart, session.segEnd);
  onset = new OnsetDetector({ graceUntil: micTime + GRACE, rmsDb: ONSET_DB });
}

function finishTake() {
  if (take && take.started && take.cents.filter(Number.isFinite).length > 30) {
    addAttempt({
      songId: song.id, created: Date.now(), segStart: take.segStart, segEnd: take.segEnd,
      sameKey: song.sameKey, myTonicHz: myTonic(), teacherTonicHz: teacherTonic(),
      times: Float32Array.from(take.times), cents: Float32Array.from(take.cents),
    }).catch(() => {});
  }
  if (session.phase === "wait" || session.phase === "sing") session.primary();
  update();
}

async function onMain() {
  if (!session) return;
  const phase = session.phase;
  if (phase === "idle") {
    if (!(await startMic())) return;
    awake.acquire();
    session.primary();
    player.play(session.pos);
  } else if (phase === "play") {
    player.stop();
    session.primary();
    newTake();
  } else if (phase === "wait" || phase === "sing") {
    finishTake();
  } else if (phase === "review") {
    take = null;
    session.primary();
    if (session.phase === "play") player.play(session.pos);
  }
  update();
}

function onLeft() {
  if (!session) return;
  if (session.phase === "play") {
    // Back a few seconds.
    session.seek(session.pos - 5);
    player.play(session.pos);
  } else {
    take = null;
    session.hearAgain();
    player.play(session.pos);
  }
  update();
}

function onRight() {
  if (!session || session.phase !== "review") return;
  session.singAgain();
  newTake();
  update();
}

// ---------------------------------------------------------------- screen

function show(phase, sub) {
  $("songPhase").textContent = phase;
  $("songSub").textContent = sub;
}

const ICONS = {
  play: '<svg class="ico" viewBox="0 0 24 24"><path d="M8 5l11 7-11 7z" fill="currentColor"/></svg>',
  mic: '<svg class="ico" viewBox="0 0 24 24"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>',
  check: '<svg class="ico" viewBox="0 0 24 24"><path d="M5 12l5 5 9-10"/></svg>',
  next: '<svg class="ico" viewBox="0 0 24 24"><path d="M6 5l9 7-9 7zM18 5v14" fill="currentColor"/></svg>',
};

function setButtons(main = null, left = null, right = null, mainClass = "") {
  $("songMain").hidden = !main;
  if (main) {
    $("songMainLabel").textContent = main.label;
    $("songMainIco").innerHTML = ICONS[main.icon];
    $("songMain").className = `main-btn ${mainClass}`;
  }
  $("songLeft").hidden = !left;
  if (left) $("songLeftLabel").textContent = left;
  $("songRight").hidden = !right;
  if (right) $("songRightLabel").textContent = right;
}

function update() {
  if (!session) return;
  const p = session.phase;
  if (p === "idle") {
    const atEnd = session.pos >= session.duration - 0.05;
    show(atEnd ? "End of the song" : "Listen to the teacher",
      atEnd ? "Tap Play to start again from the beginning." : "Tap My turn whenever you want to sing back what you heard.");
    setButtons({ label: atEnd ? "From the start" : "Play", icon: "play" });
  } else if (p === "play") {
    show("Listening", "Tap My turn to sing back what you just heard.");
    setButtons({ label: "My turn", icon: "mic" }, "Back 5 s", null, "turn");
  } else if (p === "wait") {
    show("Your turn", "Sing when you are ready.");
    setButtons({ label: "Done", icon: "check" }, "Hear again", null, "sing");
  } else if (p === "sing") {
    show("Singing", "It stops by itself when you finish.");
    setButtons({ label: "Done", icon: "check" }, "Hear again", null, "sing");
  } else if (p === "review") {
    show(take && take.started ? "Your notes are on the chart" : "Nothing heard",
      take && take.started ? "Blue is the teacher, green and orange is you." : "Sing again, or go on.");
    setButtons({ label: session.reachedEnd ? "Finish" : "Continue", icon: "next" }, "Hear again", "Sing again");
  }
  $("songHint").hidden = !((p === "idle" || p === "play") && song.tonicSource === "guess");
  $("songHint").textContent = "The teacher's key is only a guess. Tap the song name to set it.";
}

/** Where the chart looks: around the playhead, or the whole stretch while I sing. */
function viewWindow() {
  const p = session.phase;
  if (p === "play" || p === "idle") return [session.pos - 6, session.pos + 2];
  const len = session.segEnd - session.segStart;
  if (len <= 10) return [session.segStart - 0.3, session.segStart + Math.max(len + 1, 6)];
  const c = take && take.started ? take.cursor : session.segStart;
  return [c - 6, c + 2];
}

function myLayer() {
  if (!take || !take.times.length) return null;
  let cents = take.cents;
  if (!song.sameKey) {
    // Sung an octave lower or higher than the teacher: move the shape onto theirs.
    const seg = teacher.cents.slice(Math.floor(take.segStart / song.hop), Math.ceil(take.segEnd / song.hop));
    const shift = octaveShift(take.cents, Array.from(seg));
    if (shift) cents = take.cents.map((c) => c + shift);
  }
  return { times: take.times, cents, role: "mine" };
}

function draw() {
  if (!active || !session) return;
  const [t0, t1] = viewWindow();
  const layers = [{ times: teacher.times, cents: teacher.cents, role: "teacher" }];
  const mine = myLayer();
  if (mine) layers.push(mine);
  const p = session.phase;
  const tonic = myTonic();
  chart.draw({
    t0, t1, center, span: spanFor(chart), lanes: lanesAround(scale(), center, spanFor(chart)),
    name: (c) => scaleNoteName(tonic, c), view: settings.view, tolerance: tolerance(),
    layers,
    cursor: p === "play" ? session.pos : p === "sing" && take ? take.cursor : null,
    shade: p === "wait" || p === "sing" || p === "review" ? [session.segStart, session.segEnd] : null,
  });
}

function medianInWindow(t0, t1) {
  const i = Math.max(0, Math.floor(t0 / song.hop)), j = Math.min(teacher.cents.length, Math.ceil(t1 / song.hop));
  const vals = [];
  for (let k = i; k < j; k++) if (Number.isFinite(teacher.cents[k])) vals.push(teacher.cents[k]);
  vals.sort((a, b) => a - b);
  return vals.length ? vals[vals.length >> 1] : NaN;
}

function frame(ts, loop) {
  // One drawing loop per visit: an older loop stops when the screen is entered again.
  if (!active || !session || loop !== token) return;
  const dt = lastFrame ? Math.min(0.1, (ts - lastFrame) / 1000) : 0;
  lastFrame = ts;
  if (session.phase === "play") {
    if (session.tick(player.position)) {
      player.stop();
      newTake();
      update();
    }
  }
  if (session.phase === "sing" && take && take.finished()) finishTake();
  const [t0, t1] = viewWindow();
  center = followCenter(center, medianInWindow(t0, t1), spanFor(chart), dt);
  draw();
  drawTimeline();
  if (DEBUG && ts - lastDebug > 500) {
    lastDebug = ts;
    $("songSub").textContent = latencyReport();
  }
  requestAnimationFrame((t) => frame(t, loop));
}

function drawTimeline() {
  const d = session.duration || 1;
  const pos = session.phase === "sing" && take ? Math.min(take.cursor, session.segEnd) : session.pos;
  $("timeDone").style.width = `${(100 * pos) / d}%`;
  $("timeKnob").style.left = `${(100 * pos) / d}%`;
  const seg = $("timeSeg");
  const showSeg = session.phase !== "play" && session.phase !== "idle";
  seg.hidden = !showSeg;
  if (showSeg) {
    seg.style.left = `${(100 * session.segStart) / d}%`;
    seg.style.width = `${(100 * (session.segEnd - session.segStart)) / d}%`;
  }
  $("timePos").textContent = clock(pos);
}

// ---------------------------------------------------------------- song sheet

function renderSheet() {
  const t = song.teacherTonicHz;
  const { index, octave } = hzToNote(t);
  $("teacherKeyText").textContent = song.tonicSource === "name"
    ? `${keyLabel(t)}, read from the file name.`
    : song.tonicSource === "manual" ? `${keyLabel(t)}, set by you.`
    : `${keyLabel(t)} is only a guess. Pick the key your teacher sang in.`;
  $("teacherKeyText").classList.toggle("attention", song.tonicSource === "guess");
  // A key read from the file name is almost always right: keep its grid folded away.
  $("teacherKeyBox").hidden = song.tonicSource === "name" && !teacherKeyOpen;
  $("teacherKeyChange").hidden = !$("teacherKeyBox").hidden;
  keyPicker($("teacherKeyGrid"), $("teacherOctaves"), { keyIndex: index, octave }, (k) => {
    song.teacherTonicHz = keyHz(k);
    song.tonicSource = "manual";
    keysChanged();
  });
  options($("sameKeyChoice"), [
    { value: true, label: "Teacher's key", small: "as recorded" },
    { value: false, label: "My own key", small: "transposed" },
  ], song.sameKey, (v) => { song.sameKey = v; keysChanged(); });
  $("myKeyBox").hidden = song.sameKey;
  keyPicker($("myKeyGrid"), $("myOctaves"), song.myKey, (k) => {
    song.myKey = { ...song.myKey, ...k };
    keysChanged();
  });
  $("myKeyText").textContent = song.sameKey
    ? `You sing exactly the teacher's notes, from ${SOLFEGE[index]}.`
    : `You sing from ${keyLabel(keyHz(song.myKey))}. The teacher's notes are moved to your key on the chart.`;
}

function keysChanged() {
  computeTeacher();
  if (stream) stream.tonicHz = myTonic();
  take = null;
  putSong(song).catch(() => {});
  renderSheet();
  update();
}

let teacherKeyOpen = false;
$("teacherKeyChange").addEventListener("click", () => {
  teacherKeyOpen = true;
  renderSheet();
});

$("songKeyChip").addEventListener("click", () => {
  if (!song) return;
  teacherKeyOpen = false;
  renderSheet();
  $("songSheet").showModal();
});

$("deleteSong").addEventListener("click", async () => {
  if (!song || !confirm(`Remove "${song.name}" from this phone?`)) return;
  const id = song.id;
  $("songSheet").close();
  location.hash = "#/";
  await deleteSong(id);
});

// ---------------------------------------------------------------- controls

$("songMain").addEventListener("click", onMain);
$("songLeft").addEventListener("click", onLeft);
$("songRight").addEventListener("click", onRight);
$("songViewBtn").addEventListener("click", toggleView);

function seekFromEvent(e) {
  if (!session) return;
  const r = $("timeBar").getBoundingClientRect();
  const t = ((e.clientX - r.left) / r.width) * session.duration;
  const playing = session.phase === "play";
  take = null;
  session.seek(t);
  if (playing) player.play(session.pos);
  else player.stop();
  update();
}
$("timeBar").addEventListener("pointerdown", (e) => {
  seekFromEvent(e);
  $("timeBar").setPointerCapture(e.pointerId);
});
$("timeBar").addEventListener("pointermove", (e) => {
  if (e.buttons && session && session.phase !== "play") seekFromEvent(e);
});

onSettingsChange(() => {
  if (!song) return;
  if (player) player.sync = settings.sync / 1000;
  viewIcon($("songViewBtn"));
  if (stream) {
    stream.smoothingFrames = settings.smoothing;
    stream.detector.silenceRms = dbToRms(settings.gate);
  }
  update();
});
