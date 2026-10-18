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

  /** The position being heard right now (output latency taken off), in seconds. */
  get position() {
    if (!this.node) return this.offset;
    const ctx = audioContext();
    const latency = (ctx.outputLatency || 0) + (ctx.baseLatency || 0);
    return Math.max(this.offset, this.offset + ctx.currentTime - this.startedAt - latency);
  }
}

/** Decode a stored recording for playback at the device's own sample rate. */
export async function loadPlayer(blob) {
  const ctx = audioContext();
  const buffer = await ctx.decodeAudioData(await blob.arrayBuffer());
  return new Player(buffer);
}
