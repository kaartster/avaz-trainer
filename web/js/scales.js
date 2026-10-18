// Scale positions in cents, nearest note, and note lanes.
// Same behavior as src/avaz/scales.py and src/avaz/notes.py.

import { OCTAVE } from "./cents.js";

export class Scale {
  constructor(name, positions, labels = []) {
    this.name = name;
    this.positions = positions.map(Number);
    this.labels = labels.length ? labels : this.positions.map((p) => p.toFixed(0));
    if (this.labels.length !== this.positions.length) {
      throw new Error(`scale ${name}: ${this.labels.length} labels for ${this.positions.length} positions`);
    }
  }

  /** Positions inside one octave [0, 1200) with their labels. */
  base() {
    const pos = [], labels = [];
    this.positions.forEach((p, i) => {
      if (p >= 0 && p < OCTAVE) { pos.push(p); labels.push(this.labels[i]); }
    });
    return { pos, labels };
  }

  /** All [cents, label] pairs, repeated over octaves, inside [lo, hi]. */
  positionsInRange(lo, hi) {
    const { pos, labels } = this.base();
    const out = [];
    const kLo = Math.floor(lo / OCTAVE) - 1, kHi = Math.ceil(hi / OCTAVE) + 1;
    for (let k = kLo; k <= kHi; k++) {
      pos.forEach((p, i) => {
        const c = p + k * OCTAVE;
        if (c >= lo && c <= hi) out.push([c, labels[i]]);
      });
    }
    return out;
  }
}

/** Build scales from the JSON exported by `avaz web` ({name: {positions, labels}}). */
export function scalesFromJson(raw) {
  const out = {};
  for (const [name, entry] of Object.entries(raw)) {
    out[name] = Array.isArray(entry)
      ? new Scale(name, entry)
      : new Scale(name, entry.positions, entry.labels || []);
  }
  return out;
}

/** The scale note closest to `cents`, the scale repeating every octave. */
export function nearestNote(cents, scale) {
  if (!Number.isFinite(cents)) return { position: NaN, label: "", deviation: NaN };
  const { pos, labels } = scale.base();
  const octave = Math.floor(cents / OCTAVE) * OCTAVE;
  let best = null;
  for (const shift of [-OCTAVE, 0, OCTAVE]) {
    pos.forEach((p, i) => {
      const c = p + octave + shift;
      if (best === null || Math.abs(c - cents) < Math.abs(best.position - cents)) {
        best = { position: c, label: labels[i], deviation: cents - c };
      }
    });
  }
  return best;
}

/** [center, low, high] per note: each lane reaches halfway to its neighbours. */
export function laneEdges(centers) {
  const c = [...centers].sort((a, b) => a - b);
  if (c.length === 0) return [];
  if (c.length === 1) return [[c[0], c[0] - 50, c[0] + 50]];
  const mids = c.slice(1).map((v, i) => (v + c[i]) / 2);
  return c.map((center, i) => {
    const low = i === 0 ? center - (mids[0] - center) : mids[i - 1];
    const high = i === c.length - 1 ? center + (center - mids[mids.length - 1]) : mids[i];
    return [center, low, high];
  });
}

/**
 * Blocks of time spent on one scale note, like a piano roll.
 * Each voiced frame goes to its nearest center; runs on the same note become one
 * block. A block survives a gap of up to `maxGap` seconds; blocks shorter than
 * `minSeconds` are dropped. A voice between two notes stays on the one it was on
 * until it is `stickiness` cents closer to the other, so vibrato around the
 * midpoint does not flicker between two lanes. Returns [{t0, t1, center, dev}],
 * dev being the median deviation from the note in cents.
 */
export function noteBlocks(times, cents, centers, minSeconds = 0.05, maxGap = 0.03, stickiness = 20) {
  const c = [...centers].sort((a, b) => a - b);
  const n = times.length;
  const blocks = [];
  if (n === 0 || c.length === 0) return blocks;
  const hop = n > 1 ? medianDiff(times) : 0;
  const idx = new Int32Array(n).fill(-1);
  let prev = -1;
  for (let i = 0; i < n; i++) {
    const x = cents[i];
    if (!Number.isFinite(x)) continue;
    let best = 0;
    for (let k = 1; k < c.length; k++) if (Math.abs(x - c[k]) < Math.abs(x - c[best])) best = k;
    if (prev >= 0 && best !== prev && Math.abs(x - c[prev]) <= Math.abs(x - c[best]) + stickiness) best = prev;
    idx[i] = prev = best;
  }
  let start = -1, last = -1, note = -1;
  const close = () => {
    if (times[last] + hop - times[start] < minSeconds) return;
    const devs = [];
    for (let i = start; i <= last; i++) if (idx[i] === note) devs.push(cents[i] - c[note]);
    blocks.push({ t0: times[start], t1: times[last] + hop, center: c[note], dev: medianOf(devs) });
  };
  for (let i = 0; i < n; i++) {
    const k = idx[i];
    if (k < 0) {
      if (start >= 0 && times[i] - times[last] > maxGap) { close(); start = -1; }
      continue;
    }
    if (start >= 0 && k === note) { last = i; continue; }
    if (start >= 0) close();
    start = last = i;
    note = k;
  }
  if (start >= 0) close();
  return blocks;
}

function medianOf(values) {
  const v = [...values].sort((a, b) => a - b);
  const m = v.length >> 1;
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
}

function medianDiff(times) {
  const d = [];
  for (let i = 1; i < times.length; i++) d.push(times[i] - times[i - 1]);
  return medianOf(d);
}
