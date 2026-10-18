// Tests for the pure logic of the phone app. Open tests.html in any browser.
// The cases mirror the Python tests so both apps behave the same.

import { centsToHz, foldOctave, foldToReference, hzToCents, median } from "./cents.js";
import { demoVoice } from "./demo.js";
import { NoteTracker, tuneWords } from "./feedback.js";
import { hzToNote, keyLabel, noteToHz, scaleNoteName } from "./notes.js";
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
