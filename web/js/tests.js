// Tests for the pure logic of the phone app. Open tests.html in any browser.
// The cases mirror the Python tests so both apps behave the same.

import { centsToHz, foldOctave, foldToReference, hzToCents, median } from "./cents.js";
import { demoVoice } from "./demo.js";
import { NoteTracker, tuneWords } from "./feedback.js";
import { hzToNote, keyFromName, keyLabel, noteToHz, scaleNoteName, tonicFromName } from "./notes.js";
import { analyzeSamples, estimateTonic, firstVoicedTime, medianFilter, octaveShift, removeBoundaryPins,
         removeOutliers, removeShortIslands } from "./offline.js";
import { OnsetDetector, SongSession, Take } from "./turns.js";
import { MAX_SPAN, MIN_SPAN, OCTAVE_VIEW, defaultSpan, pinchSpan, wheelSpan } from "./zoom.js";
import { Scale, laneEdges, nearestNote, noteBlocks, scalesFromJson } from "./scales.js";
import { LiveTrace, PitchStream, followCenter } from "./stream.js";
import { Yin } from "./yin.js";

const results = [];

function test(name, fn) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (err) {
    results.push({ name, ok: false, message: err.message });
  }
}

function eq(actual, expected, what = "") {
  const a = JSON.stringify(actual), e = JSON.stringify(expected);
  if (a !== e) throw new Error(`${what} expected ${e}, got ${a}`);
}

function approx(actual, expected, tol = 1e-6, what = "") {
  if (!(Math.abs(actual - expected) <= tol)) {
    throw new Error(`${what} expected ${expected} +/- ${tol}, got ${actual}`);
  }
}

function ok(cond, what = "assertion failed") {
  if (!cond) throw new Error(what);
}

const range = (n, f) => Array.from({ length: n }, (_, i) => f(i));

function tone(freq, n = 2048, sr = 44100, harmonics = [1, 0.5, 0.25]) {
  const y = range(n, (i) => harmonics.reduce((s, a, k) => s + a * Math.sin(2 * Math.PI * freq * (k + 1) * i / sr), 0));
  const peak = Math.max(...y.map(Math.abs));
  return Float32Array.from(y, (v) => (0.3 * v) / peak);
}

// A small seeded random generator, so the noise test is repeatable.
function rng(seed) {
  return () => {
    seed = (seed * 1664525 + 1013904223) % 4294967296;
    return seed / 4294967296;
  };
}

// ---------------------------------------------------------------- cents

test("hz to cents: unison, octaves, semitone", () => {
  approx(hzToCents(220, 220), 0);
  approx(hzToCents(440, 220), 1200);
  approx(hzToCents(110, 220), -1200);
  approx(hzToCents(220 * 2 ** (1 / 12), 220), 100);
});

test("hz to cents: zero and NaN are unvoiced", () => {
  ok(Number.isNaN(hzToCents(0, 220)));
  ok(Number.isNaN(hzToCents(-5, 220)));
  ok(Number.isNaN(hzToCents(NaN, 220)));
});

test("cents round trip", () => {
  for (const hz of [80, 146.83, 196, 523.25]) approx(centsToHz(hzToCents(hz, 196), 196), hz, 1e-9);
});

test("fold octave", () => {
  approx(foldOctave(1350), 150);
  approx(foldOctave(-100), 1100);
  approx(foldOctave(1200), 0);
  ok(Number.isNaN(foldOctave(NaN)));
});

test("fold to reference", () => {
  approx(foldToReference(-1150, 0), 50);
  approx(foldToReference(500, 0), 500);
  approx(foldToReference(1200, 0), 0);
});

test("median ignores NaN", () => {
  eq(median([3, NaN, 1, 2]), 2);
  eq(median([4, 1, 3, 2]), 2.5);
  ok(Number.isNaN(median([NaN])));
});

// ---------------------------------------------------------------- notes

test("note to hz reference points", () => {
  approx(noteToHz(9, 4), 440);
  approx(noteToHz(2, 3), 146.83, 0.01);
  approx(noteToHz(6, 3), 185.0, 0.01);
});

test("hz to note round trip and offset", () => {
  const n = hzToNote(noteToHz(4, 3));
  eq([n.index, n.octave], [4, 3]);
  approx(n.off, 0, 1e-6);
  const m = hzToNote(167.0);
  eq([m.index, m.octave], [4, 3]);
  approx(m.off, 22.6, 0.5);
  const b = hzToNote(noteToHz(11, 2) * 2 ** (49 / 1200));
  eq([b.index, b.octave], [11, 2]);
  const c = hzToNote(noteToHz(11, 2) * 2 ** (51 / 1200));
  eq([c.index, c.octave], [0, 3], "rounds up to Do");
});

test("key label", () => {
  eq(keyLabel(146.83), "Re (D3)");
  eq(keyLabel(185.0), "Fa diez (F#3)");
});

test("scale note names with koron and sori", () => {
  const mi = noteToHz(4, 3), la = noteToHz(9, 3);
  eq(scaleNoteName(mi, 0), "Mi");
  eq(scaleNoteName(mi, 150), "Fa sori");
  eq(scaleNoteName(mi, 300), "Sol");
  eq(scaleNoteName(mi, 1200), "Mi");
  eq(scaleNoteName(la, 150), "Si koron");
  eq(scaleNoteName(la, -200), "Sol");
  eq(scaleNoteName(185.0, 0), "Fa diez");
  eq(scaleNoteName(167.0, 0), "Mi");
});

// ---------------------------------------------------------------- scales

const shur = new Scale("shur", [0, 150, 300, 500, 700, 800, 1000, 1200]);

test("scale label mismatch throws", () => {
  let threw = false;
  try { new Scale("bad", [0, 100], ["only one"]); } catch { threw = true; }
  ok(threw);
});

test("nearest note within and across octaves", () => {
  let n = nearestNote(160, shur);
  eq(n.position, 150); approx(n.deviation, 10);
  n = nearestNote(-20, shur);
  eq(n.position, 0); approx(n.deviation, -20);
  n = nearestNote(1350, shur);
  eq(n.position, 1350); approx(n.deviation, 0);
  n = nearestNote(-1060, shur);
  eq(n.position, -1050); approx(n.deviation, -10);
  ok(Number.isNaN(nearestNote(NaN, shur).deviation));
});

test("positions in range repeat over octaves", () => {
  const p = shur.positionsInRange(-500, 1500).map(([c]) => c);
  eq(p, [-500, -400, -200, 0, 150, 300, 500, 700, 800, 1000, 1200, 1350, 1500]);
});

test("scales from json, list or mapping", () => {
  const s = scalesFromJson({ a: [0, 700], b: { positions: [0, 150], labels: ["t", "k"] } });
  eq(s.a.labels, ["0", "700"]);
  eq(s.b.labels, ["t", "k"]);
});

test("lane edges reach halfway to neighbours", () => {
  eq(laneEdges([0, 150, 300]), [[0, -75, 75], [150, 75, 225], [300, 225, 375]]);
  eq(laneEdges([]), []);
  eq(laneEdges([500]), [[500, 450, 550]]);
});

test("note blocks follow the nearest note", () => {
  const t = range(100, (i) => i * 0.01);
  const c = t.map((x) => (x < 0.5 - 1e-9 ? 10 : 290));
  const b = noteBlocks(t, c, [0, 150, 300]);
  eq(b.map((x) => x.center), [0, 300]);
  approx(b[0].t0, 0); approx(b[0].t1, 0.5, 1e-9);
  approx(b[1].t1, 1.0, 1e-9);
  approx(b[0].dev, 10); approx(b[1].dev, -10);
});

test("note blocks bridge short gaps and drop short blips", () => {
  const t = range(100, (i) => i * 0.01);
  const c = range(100, (i) => (i >= 30 && i < 32) || i >= 80 ? NaN : i >= 60 && i < 63 ? 150 : 0);
  const b = noteBlocks(t, c, [0, 150, 300]);
  eq(b.map((x) => x.center), [0, 0]);
  approx(b[0].t0, 0); approx(b[0].t1, 0.6, 1e-9);
  approx(b[1].t0, 0.63, 1e-9); approx(b[1].t1, 0.8, 1e-9);
  eq(noteBlocks(t, t.map(() => NaN), [0, 150]).length, 0);
});

test("note blocks do not flicker between two lanes", () => {
  const t = range(200, (i) => i * 0.01);
  const c = t.map((x) => -440 + 18 * Math.sin(2 * Math.PI * 5.5 * x));
  eq(noteBlocks(t, c, [-500, -400, -200]).map((b) => b.center), [-400]);
  ok(noteBlocks(t, c, [-500, -400, -200], 0.05, 0.03, 0).length > 3, "without stickiness");
});

// ---------------------------------------------------------------- yin

for (const freq of [80, 110, 196, 261.6, 440, 880]) {
  test(`yin finds ${freq} Hz within 5 cents`, () => {
    const yin = new Yin({ sampleRate: 44100, frameLength: 2048 });
    const f0 = yin.detect(tone(freq));
    ok(Number.isFinite(f0), "voiced");
    approx(hzToCents(f0, freq), 0, 5, "cents off");
  });
}

test("yin at 48 kHz (phone default) on a pure sine", () => {
  const yin = new Yin({ sampleRate: 48000, frameLength: 2048 });
  approx(hzToCents(yin.detect(tone(185, 2048, 48000, [1])), 185), 0, 2);
});

test("yin: silence and noise are unvoiced", () => {
  const yin = new Yin({ sampleRate: 44100, frameLength: 2048 });
  ok(Number.isNaN(yin.detect(new Float32Array(2048))), "silence");
  const r = rng(1);
  // Approximately normal noise: sum of uniforms.
  const noise = Float32Array.from(range(2048, () => 0.1 * (r() + r() + r() + r() - 2) * 1.7));
  ok(Number.isNaN(yin.detect(noise)), "noise");
});

test("yin rejects a wrong frame length", () => {
  const yin = new Yin({ sampleRate: 44100, frameLength: 2048 });
  let threw = false;
  try { yin.detect(new Float32Array(2049)); } catch { threw = true; }
  ok(threw);
});

test("yin difference function matches the direct sum", () => {
  const yin = new Yin({ sampleRate: 44100, frameLength: 2048 });
  const x = tone(150);
  const d = yin.differenceFunction(x);
  for (const tau of [0, 1, 37, 294, yin.tauMax]) {
    let s = 0;
    for (let j = 0; j < yin.window; j++) s += (x[j] - x[j + tau]) ** 2;
    approx(d[tau], s, 1e-6 * Math.max(1, s), `d(${tau})`);
  }
});

// ---------------------------------------------------------------- stream

const SR = 44100, FRAME = 2048, HOP = 256;

test("pitch stream tracks a tone in small blocks", () => {
  const yin = new Yin({ sampleRate: SR, frameLength: FRAME });
  const ps = new PitchStream(yin, 185, HOP, 1);
  const n = Math.round(0.5 * SR);
  const y = range(n, (i) => 0.3 * Math.sin(2 * Math.PI * 220 * i / SR));
  const points = [];
  for (let i = 0; i < n; i += 100) points.push(...ps.process(Float32Array.from(y.slice(i, i + 100))));
  eq(points.length, Math.floor(n / HOP) - FRAME / HOP + 1);
  approx(points[0][0], FRAME / 2 / SR, HOP / SR);
  ok(points.every((p, i) => i === 0 || p[0] > points[i - 1][0]), "times increase");
  ok(points.every((p) => Math.abs(hzToCents(p[1], 220)) < 5), "within 5 cents");
  approx(points[points.length - 1][2], hzToCents(220, 185), 5);
});

test("pitch stream: silence gives NaN", () => {
  const ps = new PitchStream(new Yin({ sampleRate: SR, frameLength: FRAME }), 185, HOP, 3);
  const points = ps.process(new Float32Array(SR / 4));
  ok(points.length > 0 && points.every((p) => Number.isNaN(p[1])));
});

test("median smoothing removes a single slip", () => {
  const values = [200, 200, 400, 200, 200, NaN, NaN, NaN];
  const fake = { sampleRate: SR, frameLength: FRAME, detect: () => values.shift() };
  const ps = new PitchStream(fake, 200, HOP, 3);
  const out = [...ps.process(new Float32Array(FRAME - HOP))];
  for (let i = 0; i < 8; i++) out.push(...ps.process(new Float32Array(HOP)));
  const f0 = out.map((p) => p[1]);
  eq(f0[2], 200, "slip voted out");
  eq(f0[3], 200);
  ok(Number.isNaN(f0[f0.length - 1]), "three NaN in a row");
});

test("live trace readout", () => {
  const tr = new LiveTrace(1.0);
  tr.append(range(25, (i) => [0.1 * (i + 1), 100, 100 + i]));
  approx(tr.latestTime, 2.5, 1e-9);
  approx(tr.stableCents(0.25), 123, 1e-9);
  tr.append([[2.6, NaN, NaN]]);
  ok(Number.isFinite(tr.stableCents(0.3)), "one gap keeps the readout");
  ok(Number.isNaN(new LiveTrace(1).stableCents()), "empty");
});

test("view follows the voice only when it leaves the middle", () => {
  eq(followCenter(0, 200, 1000, 0.016), 0);
  const c = followCenter(0, 700, 1000, 0.1);
  ok(c > 0 && c < 700, `glides, got ${c}`);
  eq(followCenter(0, 700, 1000, 1), 700);
  eq(followCenter(50, NaN, 1000, 0.1), 50);
});

// ---------------------------------------------------------------- feedback

test("tune words", () => {
  eq(tuneWords(10).state, "in");
  eq(tuneWords(-29).words, "In tune");
  eq(tuneWords(-40).words, "A bit low, go up");
  eq(tuneWords(45).words, "A bit high, go down");
  eq(tuneWords(-70).words, "Low, go up");
  eq(tuneWords(28, "detailed").state, "high");
  eq(tuneWords(NaN).state, "silent");
});

test("note tracker does not flicker between two notes", () => {
  const tr = new NoteTracker(shur);
  eq(tr.update(140).position, 150);
  eq(tr.update(70).position, 150, "just past the middle: keep");
  eq(tr.update(60).position, 0, "clearly closer to the tonic: switch");
  eq(tr.update(NaN).position, 0, "silence keeps the note");
});

// ---------------------------------------------------------------- end to end

test("demo voice through the pipeline lands on the scale notes", () => {
  const sr = 48000, tonic = 146.83;
  const voice = demoVoice(sr);
  const ps = new PitchStream(new Yin({ sampleRate: sr, frameLength: 2048 }), tonic, 512, 3);
  const pts = [];
  for (let i = 0; i < Math.round(1.3 * sr / 512); i++) pts.push(...ps.process(voice.next(512, tonic, shur.positions)));
  // The demo opens with 1.4 s on the tonic with 18 cents of vibrato.
  const settled = pts.filter((p) => p[0] > 0.3).map((p) => p[2]);
  ok(settled.length > 50 && settled.every(Number.isFinite), "voiced");
  approx(median(settled), 0, 5, "median on the tonic");
});

// ---------------------------------------------------------------- key from a file name

const NAMES = [
  ["با من صنما_ دشتی_ فا دیز.m4a", 6],
  ["شبانگاهان_ دشتی فادیز.vocals.wav", 6],
  ["دلشکن _ دشتی می بمل.m4a", 3],
  ["شبانگاهان دشتی ''می''.m4a", 4],
  ["کعبه دلها _ دشتی ر.m4a", 2],
  ["کعبه‌ی دل‌ها_ دشتی فا دیز.pitch.json", 6],
  ["dashti in Fa diez.mp3", 6],
  ["exercise Si bemol.wav", 10],
  ["دلم می گیرد دشتی سل.m4a", 7],
  ["my song.m4a", null],
  ["ba_man_sanama.labels.txt", null],
];
for (const [name, index] of NAMES) {
  test(`key from name: ${name}`, () => eq(keyFromName(name), index));
}

test("tonic from name picks the octave from the voice", () => {
  approx(tonicFromName("دشتی می بمل", 136.8), 155.56, 0.01);
  approx(tonicFromName("دشتی فا دیز", 127.6), 185.0, 0.01);
  approx(tonicFromName("دشتی ر", 128.4), 146.83, 0.01);
  approx(tonicFromName("دشتی ر", 2 * 128.4), 293.66, 0.01);
  eq(tonicFromName("no key here", 130), null);
  eq(tonicFromName("دشتی ر", null), null);
});

// ---------------------------------------------------------------- offline analysis

test("short voiced islands are removed", () => {
  const f = Float32Array.from([NaN, 200, NaN, 200, 200, 200, NaN, 300, 300]);
  const out = Array.from(removeShortIslands(f, 3));
  ok(Number.isNaN(out[1]) && out[3] === 200 && out[5] === 200 && Number.isNaN(out[7]));
});

test("median filter votes out a slip and keeps NaN majorities", () => {
  const out = medianFilter(Float32Array.from([200, 200, 400, 200, 200, NaN, NaN, NaN, 200]), 3);
  eq(out[2], 200);
  ok(Number.isNaN(out[6]));
});

test("outliers and boundary pins are blanked", () => {
  const o = removeOutliers(Float32Array.from([200, 210, 190, 200, 200 * 2 ** (1600 / 1200)]), 1500);
  ok(Number.isNaN(o[4]) && o[0] === 200);
  const b = removeBoundaryPins(Float32Array.from([70, 71, 200, 999]), 70, 1000, 25);
  ok(Number.isNaN(b[0]) && Number.isNaN(b[1]) && b[2] === 200 && Number.isNaN(b[3]));
});

test("analysis of a sung tone with a pause", () => {
  const sr = 22050;
  const n = sr * 2;
  const y = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const t = i / sr;
    if (t < 0.8 || t > 1.1) y[i] = 0.2 * Math.sin(2 * Math.PI * 185 * t) + 0.1 * Math.sin(4 * Math.PI * 185 * t);
  }
  const { hop, f0 } = analyzeSamples(y, sr);
  approx(hop, 256 / sr, 1e-12);
  const at = (t) => f0[Math.round(t / hop)];
  approx(hzToCents(at(0.4), 185), 0, 3, "first note");
  approx(hzToCents(at(1.5), 185), 0, 3, "after the pause");
  ok(Number.isNaN(at(0.95)), "pause is unvoiced");
});

test("tonic estimate from a histogram", () => {
  const r = rng(3);
  const noise = () => 8 * (r() + r() + r() - 1.5);
  const f0 = [
    ...range(600, () => 185 * 2 ** (noise() / 1200)),
    ...range(200, () => 185 * 2 ** ((300 + noise()) / 1200)),
    ...range(100, () => 185 * 2 ** ((1200 + noise()) / 1200)),
    ...range(100, () => 185 * 2 ** ((700 + noise()) / 1200)),
    ...range(50, () => NaN),
  ];
  approx(hzToCents(estimateTonic(Float32Array.from(f0)), 185), 0, 10);
});

test("first voiced time needs a run", () => {
  const t = range(10, (i) => i * 0.01);
  approx(firstVoicedTime(t, [NaN, 1, NaN, 1, 1, 1, 1, NaN, NaN, NaN], 3), 0.03, 1e-12);
  ok(Number.isNaN(firstVoicedTime(t, t.map(() => NaN), 3)));
});

test("octave shift moves my median next to the teacher's", () => {
  const teacher = range(30, () => 100), mine = range(30, () => -1100);
  eq(octaveShift(mine, teacher), 1200);
  eq(octaveShift(mine.slice(0, 5), teacher), 0, "too few points");
});

// ---------------------------------------------------------------- singing after the teacher

test("song session: play, my turn, sing, review, continue", () => {
  const s = new SongSession(60);
  s.primary();
  eq(s.phase, "play");
  ok(!s.tick(7.5));
  s.primary();
  eq([s.phase, s.segStart, s.segEnd], ["wait", 0, 7.5]);
  s.voiceStarted();
  eq(s.phase, "sing");
  s.primary();
  eq(s.phase, "review");
  s.primary();
  eq([s.phase, s.segStart, s.pos], ["play", 7.5, 7.5], "continues where I paused");
});

test("song session: hear again pauses at the end of the stretch by itself", () => {
  const s = new SongSession(60, 10);
  s.primary();
  s.tick(14);
  s.primary();
  s.hearAgain();
  eq([s.phase, s.pos], ["play", 10]);
  ok(!s.tick(13.9));
  ok(s.tick(14.05), "auto pause");
  eq([s.phase, s.segStart, s.segEnd], ["wait", 10, 14]);
});

test("song session: sing again, seek and the end of the song", () => {
  const s = new SongSession(20);
  s.primary();
  s.tick(5);
  s.primary();
  s.primary();
  s.singAgain();
  eq(s.phase, "wait");
  s.seek(12);
  eq([s.phase, s.pos], ["idle", 12]);
  s.primary();
  ok(s.tick(20.3), "pauses at the end");
  eq([s.phase, s.segEnd, s.reachedEnd], ["wait", 20, true]);
  s.primary();
  s.primary();
  eq(s.phase, "idle", "nothing left to play");
  s.primary();
  eq([s.phase, s.pos], ["play", 0], "starts over");
});

test("onset needs loud pitched frames after the grace time", () => {
  const o = new OnsetDetector({ graceUntil: 1, rmsDb: -50, voicedFrames: 3 });
  eq(o.feed(0.5, 100, -20), null, "grace time");
  eq(o.feed(1.0, 100, -20), null);
  eq(o.feed(1.01, NaN, -20), null, "run broken");
  o.feed(1.02, 100, -20);
  eq(o.feed(1.03, 100, -60), null, "too quiet");
  o.feed(1.04, 100, -20);
  o.feed(1.05, 100, -20);
  eq(o.feed(1.06, 100, -20), 1.04);
});

test("a take lines my onset up with the teacher's", () => {
  const tt = range(1000, (i) => i * 0.01);
  const tc = tt.map((t) => (t >= 2.5 && t < 4 ? 0 : NaN));     // teacher sings 2.5 to 4 s
  const take = new Take(tt, tc, 2, 5);
  approx(take.teacherOnset, 2.5, 1e-9);
  approx(take.teacherEnd, 3.99, 1e-9);
  for (let i = 0; i < 50; i++) take.listen(10 + i * 0.01, NaN);  // breathing, 10 to 10.5 s mic time
  ok(!take.started);
  take.begin(10.5);
  for (let i = 0; i < 150; i++) take.add(10.5 + i * 0.01, 5);
  approx(take.times[0], 2.35, 1e-9, "0.15 s of preroll kept");
  approx(take.times[take.cents.findIndex(Number.isFinite)], 2.5, 1e-9, "my first note at the teacher's onset");
  approx(take.cursor, 3.99, 1e-9);
  ok(!take.finished(), "still singing");
  for (let i = 0; i < 110; i++) take.add(12 + i * 0.01, NaN);
  ok(take.finished(), "past the end and quiet");
});

// ---------------------------------------------------------------- zoom

test("default view shows at least one octave", () => {
  eq(defaultSpan(300), OCTAVE_VIEW, "short chart");
  ok(defaultSpan(400) >= 1200, "phone portrait");
  eq(defaultSpan(2000), 2400, "very tall chart stops at two octaves");
});

test("pinch: fingers apart zooms in, together zooms out, within limits", () => {
  eq(pinchSpan(1400, 100, 200), 700);
  eq(pinchSpan(1400, 200, 100), 2800);
  eq(pinchSpan(1400, 100, 1000), MIN_SPAN);
  eq(pinchSpan(1400, 1000, 10), MAX_SPAN);
  eq(pinchSpan(1400, 0, 50), 1400, "no distance yet");
});

test("wheel down zooms out", () => {
  ok(wheelSpan(1400, 100) > 1400 && wheelSpan(1400, -100) < 1400);
  eq(wheelSpan(3500, 10000), MAX_SPAN);
});

// ---------------------------------------------------------------- report

const failed = results.filter((r) => !r.ok);
const list = document.getElementById("results");
for (const r of results) {
  const li = document.createElement("li");
  li.className = r.ok ? "pass" : "fail";
  li.textContent = r.ok ? r.name : `${r.name}: ${r.message}`;
  list.append(li);
}
const summary = `${results.length - failed.length} passed, ${failed.length} failed`;
document.getElementById("summary").textContent = summary;
document.getElementById("summary").className = failed.length ? "fail" : "pass";
document.title = `${failed.length ? "FAIL" : "PASS"} ${summary}`;
window.testResults = { passed: results.length - failed.length, failed: failed.map((r) => `${r.name}: ${r.message}`) };
