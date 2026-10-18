// Pitch analysis of a whole teacher recording on the phone.
//
// The laptop uses pyin (slow, very clean). The phone runs the same YIN as the live
// view over every frame, then cleans the curve the way pitch_offline.py does:
// a short median filter, no pitches pinned at the search limits, no far outliers,
// no tiny voiced islands. Good enough to draw the teacher's notes.

import { OCTAVE, foldOctave, foldToReference, hzToCents, centsToHz, median } from "./cents.js";
import { Yin } from "./yin.js";

export const ANALYSIS = {
  sampleRate: 22050,        // recordings are resampled to this before analysis
  frameLength: 1024,        // 46 ms at 22050 Hz, enough for 70 Hz
  hopLength: 256,           // 11.6 ms between pitch values
  fmin: 70, fmax: 1000,
  silenceDb: -50,
  smoothingFrames: 5,
  minVoicedSeconds: 0.05,
  maxCentsFromMedian: 1500,
  boundaryGuardCents: 25,
};

/**
 * f0 per hop of a mono signal. Returns {hop, f0: Float32Array} with NaN for
 * unvoiced frames; frame i is centred at time i * hop.
 */
export function analyzeSamples(samples, sampleRate, opts = {}, onProgress = () => {}) {
  const o = { ...ANALYSIS, ...opts };
  const yin = new Yin({ sampleRate, frameLength: o.frameLength, fmin: o.fmin, fmax: o.fmax,
                        silenceRms: Math.pow(10, o.silenceDb / 20) });
  const n = Math.ceil(samples.length / o.hopLength);
  const raw = new Float32Array(n);
  const frame = new Float32Array(o.frameLength);
  const half = o.frameLength / 2;
  for (let i = 0; i < n; i++) {
    // Centred frame, zero padded at both ends (like librosa's center=True).
    const start = i * o.hopLength - half;
    frame.fill(0);
    const a = Math.max(0, start), b = Math.min(samples.length, start + o.frameLength);
    if (b > a) frame.set(samples.subarray(a, b), a - start);
    raw[i] = yin.detect(frame);
    if (i % 2000 === 0) onProgress(i / n);
  }
  onProgress(1);
  const hop = o.hopLength / sampleRate;
  let f0 = medianFilter(raw, o.smoothingFrames);
  f0 = removeBoundaryPins(f0, o.fmin, o.fmax, o.boundaryGuardCents);
  f0 = removeOutliers(f0, o.maxCentsFromMedian);
  f0 = removeShortIslands(f0, Math.round(o.minVoicedSeconds / hop));
  return { hop, f0 };
}

/** Median over `width` frames; NaN when unvoiced frames are the majority. */
export function medianFilter(f0, width) {
  if (width <= 1) return Float32Array.from(f0);
  const out = new Float32Array(f0.length);
  const r = width >> 1;
  for (let i = 0; i < f0.length; i++) {
    const win = [];
    let count = 0;
    for (let j = Math.max(0, i - r); j <= Math.min(f0.length - 1, i + r); j++) {
      count++;
      if (Number.isFinite(f0[j])) win.push(f0[j]);
    }
    out[i] = win.length * 2 <= count ? NaN : median(win);
  }
  return out;
}

/** Blank frames within `guardCents` of fmin or fmax: forced picks, not notes. */
export function removeBoundaryPins(f0, fmin, fmax, guardCents = 25) {
  const out = Float32Array.from(f0);
  if (guardCents <= 0) return out;
  const lo = fmin * Math.pow(2, guardCents / OCTAVE), hi = fmax * Math.pow(2, -guardCents / OCTAVE);
  for (let i = 0; i < out.length; i++) if (out[i] <= lo || out[i] >= hi) out[i] = NaN;
  return out;
}

/** Blank voiced frames further than `maxCents` from the median pitch. */
export function removeOutliers(f0, maxCents) {
  const out = Float32Array.from(f0);
  if (maxCents <= 0) return out;
  const m = median(Array.from(out));
  if (!Number.isFinite(m)) return out;
  for (let i = 0; i < out.length; i++) {
    if (Number.isFinite(out[i]) && Math.abs(hzToCents(out[i], m)) > maxCents) out[i] = NaN;
  }
  return out;
}

/** Set voiced runs shorter than `minFrames` to NaN. They are mostly clicks. */
export function removeShortIslands(f0, minFrames) {
  const out = Float32Array.from(f0);
  if (minFrames <= 1) return out;
  let start = -1;
  for (let i = 0; i <= out.length; i++) {
    const v = i < out.length && Number.isFinite(out[i]);
    if (v && start < 0) start = i;
    if (!v && start >= 0) {
      if (i - start < minFrames) out.fill(NaN, start, i);
      start = -1;
    }
  }
  return out;
}

/** Time of the first frame that starts `run` consecutive voiced frames, or NaN. */
export function firstVoicedTime(times, values, run = 6) {
  let count = 0;
  for (let i = 0; i < values.length; i++) {
    count = Number.isFinite(values[i]) ? count + 1 : 0;
    if (count >= run) return times[i - run + 1];
  }
  return NaN;
}

/** Whole octaves to add to my curve so its median lands nearest the teacher's. */
export function octaveShift(mine, teacher, minPoints = 20) {
  const a = mine.filter(Number.isFinite), b = teacher.filter(Number.isFinite);
  if (a.length < minPoints || b.length < minPoints) return 0;
  return Math.round((median(b) - median(a)) / OCTAVE) * OCTAVE;
}

/**
 * The most common folded pitch class, in the octave closest to the median of what
 * was sung. Port of estimate_tonic(method="histogram"). In Dashti this is often a
 * whole tone below the real tonic, so it is only the last resort after the file name.
 */
export function estimateTonic(f0) {
  const ref = 110;
  const cents = Array.from(f0).filter((v) => v > 0).map((v) => hzToCents(v, ref));
  if (cents.length === 0) throw new Error("no voiced frames to estimate a tonic from");
  const bin = 5, nbins = OCTAVE / bin;
  const counts = new Float64Array(nbins);
  for (const c of cents) counts[Math.min(nbins - 1, Math.floor(foldOctave(c) / bin))]++;
  // Circular moving average over 5 bins.
  const smooth = counts.map((_, i) => {
    let s = 0;
    for (let d = -2; d <= 2; d++) s += counts[(i + d + nbins) % nbins];
    return s / 5;
  });
  let peak = (smooth.indexOf(Math.max(...smooth)) + 0.5) * bin;
  // Refine: mean of the folded values within 25 cents of the peak (circular).
  const near = cents.map((c) => ((foldOctave(c) - peak + 600) % OCTAVE + OCTAVE) % OCTAVE - 600)
    .filter((d) => Math.abs(d) < 25);
  if (near.length) peak += near.reduce((s, d) => s + d, 0) / near.length;
  return centsToHz(foldToReference(peak, median(cents)), ref);
}
