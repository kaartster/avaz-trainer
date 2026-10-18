// Plays the teacher's recording from any point and reports where playback is.

import { audioContext } from "./audio.js";

// ?mute plays silently, for trying the screens without sound (tests, during a class).
const MUTE = new URLSearchParams(location.search).has("mute");

export class Player {
  constructor(buffer) {
    this.buffer = buffer;
    this.node = null;
    this.startedAt = 0;      // context time when playback of `offset` started
    this.offset = 0;
    this.sync = 0;           // seconds added to the position: the "picture timing" setting
  }

  get duration() {
    return this.buffer.duration;
  }

  get playing() {
    return this.node !== null;
  }

  play(from) {
    this.stop();
    const ctx = audioContext();
    const node = ctx.createBufferSource();
    node.buffer = this.buffer;
    if (MUTE) {
      const silent = ctx.createGain();
      silent.gain.value = 0;
      node.connect(silent).connect(ctx.destination);
    } else {
      node.connect(ctx.destination);
    }
    node.start(ctx.currentTime + 0.02, Math.max(0, from));
    this.node = node;
    this.startedAt = ctx.currentTime + 0.02;
    this.offset = from;
  }

  stop() {
    if (this.node) {
      try { this.node.stop(); } catch { /* already ended */ }
      this.node.disconnect();
    }
    this.node = null;
  }

  /** The position being heard right now, in seconds. */
  get position() {
    if (!this.node) return this.offset;
    return Math.max(this.offset, this.offset + heardTime() - this.startedAt + this.sync);
  }
}

/**
 * The context time of the sound reaching the speaker right now.
 *
 * getOutputTimestamp() says which context time was at the output at which
 * moment, measured by the audio system itself. The older way, currentTime minus
 * outputLatency and baseLatency, is a guess that on Android can be too large,
 * which made the screen trail the sound. It stays as the fallback.
 */
export function heardTime() {
  const ctx = audioContext();
  const ts = ctx.getOutputTimestamp ? ctx.getOutputTimestamp() : null;
  if (ts && ts.contextTime > 0 && ts.performanceTime > 0) {
    return ts.contextTime + (performance.now() - ts.performanceTime) / 1000;
  }
  return ctx.currentTime - (ctx.outputLatency || 0) - (ctx.baseLatency || 0);
}

/** Latency numbers for the ?debug readout, in milliseconds. */
export function latencyReport() {
  const ctx = audioContext();
  const ms = (s) => Math.round(1000 * s);
  return `output ${ms(ctx.outputLatency || 0)} ms, base ${ms(ctx.baseLatency || 0)} ms, ` +
    `measured ${ms(ctx.currentTime - heardTime())} ms`;
}

/** Decode a stored recording for playback at the device's own sample rate. */
export async function loadPlayer(blob) {
  const ctx = audioContext();
  const buffer = await ctx.decodeAudioData(await blob.arrayBuffer());
  return new Player(buffer);
}
