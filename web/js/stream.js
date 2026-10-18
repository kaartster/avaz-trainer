// Live pitch pipeline: audio blocks in, (time, f0, cents) points out.
// Port of PitchStream and LiveTrace in src/avaz/live.py. No DOM, no audio APIs.
//
// Audio arrives in small blocks. The detector needs a longer frame (2048 samples)
// to see a few periods of the lowest note, so blocks go into a ring buffer and
// the detector runs on the latest frame every `hopLength` samples.

import { hzToCents, median } from "./cents.js";

export class PitchStream {
  constructor(detector, tonicHz, hopLength, smoothingFrames = 1) {
    this.detector = detector;
    this.tonicHz = tonicHz;
    this.hopLength = hopLength;
    this.sampleRate = detector.sampleRate;
    this.smoothingFrames = Math.max(1, smoothingFrames | 0);
    this.frame = new Float32Array(detector.frameLength);
    this.filled = 0;
    this.pending = new Float32Array(hopLength);
    this.pendingCount = 0;
    this.samplesSeen = 0;
    this.recent = [];
  }

  smooth(f0) {
    this.recent.push(f0);
    if (this.recent.length > this.smoothingFrames) this.recent.shift();
    if (this.smoothingFrames === 1) return f0;
    const finite = this.recent.filter(Number.isFinite);
    // NaN wins when unvoiced frames are the majority of the window.
    if (finite.length * 2 <= this.recent.length) return NaN;
    return median(finite);
  }

  /** Feed one block. Returns the new [time_s, f0_hz, cents] points. */
  process(block) {
    const out = [];
    const hop = this.hopLength, frame = this.frame;
    for (let i = 0; i < block.length; i++) {
      this.pending[this.pendingCount++] = block[i];
      if (this.pendingCount < hop) continue;
      this.pendingCount = 0;
      frame.copyWithin(0, hop);
      frame.set(this.pending, frame.length - hop);
      this.filled = Math.min(frame.length, this.filled + hop);
      this.samplesSeen += hop;
      if (this.filled < frame.length) continue;
      const f0 = this.smooth(this.detector.detect(frame));
      // Time stamp at the centre of the analysis frame.
      const t = (this.samplesSeen - frame.length / 2) / this.sampleRate;
      out.push([t, f0, hzToCents(f0, this.tonicHz)]);
    }
    return out;
  }
}

/** Rolling history of (time, cents) for the scrolling chart. */
export class LiveTrace {
  constructor(historySeconds) {
    this.historySeconds = historySeconds;
    this.times = [];
    this.cents = [];
  }

  append(points) {
    for (const [t, , c] of points) {
      this.times.push(t);
      this.cents.push(c);
    }
    // Keep a little more than the visible history, trim in chunks.
    const lo = this.latestTime - this.historySeconds - 1;
    let k = 0;
    while (k < this.times.length && this.times[k] < lo) k++;
    if (k > 256) {
      this.times.splice(0, k);
      this.cents.splice(0, k);
    }
  }

  get latestTime() {
    return this.times.length ? this.times[this.times.length - 1] : 0;
  }

  clear() {
    this.times = [];
    this.cents = [];
  }

  /** Median of the voiced values in the last `seconds`, NaN with fewer than 3. */
  stableCents(seconds = 0.3) {
    const lo = this.latestTime - seconds;
    const vals = [];
    for (let i = this.times.length - 1; i >= 0 && this.times[i] >= lo; i--) {
      if (Number.isFinite(this.cents[i])) vals.push(this.cents[i]);
    }
    return vals.length < 3 ? NaN : median(vals);
  }

  /** Median of the voiced values in the last `seconds`, for centering the view. */
  recentMedian(seconds = 2) {
    const lo = this.latestTime - seconds;
    const vals = [];
    for (let i = this.times.length - 1; i >= 0 && this.times[i] >= lo; i--) vals.push(this.cents[i]);
    return median(vals);
  }
}

/**
 * Where the chart should be centered next, in cents.
 * The view stays still while the voice is inside the middle 60% of the span, and
 * otherwise glides toward it, so it never jumps and never needs a finger.
 */
export function followCenter(center, target, span, dt, speed = 3) {
  if (!Number.isFinite(target)) return center;
  if (Math.abs(target - center) <= span * 0.3) return center;
  return center + (target - center) * Math.min(1, dt * speed);
}
