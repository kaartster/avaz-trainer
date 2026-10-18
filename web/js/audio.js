// Browser audio: microphone input, a synthetic demo voice, the tonic drone, and
// keeping the screen awake. Everything that touches Web Audio lives here.

import { demoVoice } from "./demo.js";

let context = null;

/** One shared AudioContext, created on the first tap (browsers require a gesture). */
export function audioContext() {
  if (!context) context = new AudioContext({ latencyHint: "interactive" });
  if (context.state === "suspended") context.resume();
  return context;
}

export class MicSource {
  constructor(blockSize = 512) {
    this.blockSize = blockSize;
    this.stream = null;
    this.nodes = [];
  }

  get sampleRate() {
    return audioContext().sampleRate;
  }

  /** Ask for the mic and start posting blocks to `onBlock(Float32Array)`. */
  async start(onBlock) {
    if (!window.isSecureContext || !navigator.mediaDevices) {
      throw new MicError("insecure", "The microphone only works over https or on localhost.");
    }
    const ctx = audioContext();
    try {
      // Phone voice processing (echo cancellation, noise suppression, auto gain)
      // bends and flattens pitch, so all of it is turned off.
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false,
                 channelCount: 1 },
      });
    } catch (err) {
      const blocked = err && (err.name === "NotAllowedError" || err.name === "SecurityError");
      throw new MicError(blocked ? "blocked" : "missing",
        blocked ? "Microphone access is blocked. Allow it for this site in Chrome's settings."
                : "No microphone found.");
    }
    await ctx.audioWorklet.addModule(new URL("./capture-worklet.js", import.meta.url));
    const source = ctx.createMediaStreamSource(this.stream);
    const node = new AudioWorkletNode(ctx, "capture", {
      processorOptions: { blockSize: this.blockSize },
    });
    node.port.onmessage = (e) => onBlock(e.data);
    // The worklet only runs when connected to the output; a muted gain keeps it silent.
    const mute = ctx.createGain();
    mute.gain.value = 0;
    source.connect(node).connect(mute).connect(ctx.destination);
    this.nodes = [source, node, mute];
    const track = this.stream.getAudioTracks()[0];
    this.name = track ? track.label : "microphone";
  }

  stop() {
    for (const n of this.nodes) n.disconnect();
    this.nodes = [];
    if (this.stream) this.stream.getTracks().forEach((t) => t.stop());
    this.stream = null;
  }
}

export class MicError extends Error {
  constructor(kind, message) {
    super(message);
    this.kind = kind;
  }
}

/** A synthetic singer for trying the app without a mic (open the page with ?demo). */
export class DemoSource {
  constructor(blockSize = 512, sampleRate = 48000) {
    this.blockSize = blockSize;
    this.sampleRate = sampleRate;
    this.name = "demo voice";
    this.timer = null;
  }

  /** `getTonic` and `getPositions` are read live, so the demo follows the settings. */
  async start(onBlock, getTonic, getPositions) {
    let pos = 0;
    const started = performance.now();
    const voice = demoVoice(this.sampleRate);
    this.timer = setInterval(() => {
      // Produce exactly as many samples as real time has passed.
      const due = Math.floor(((performance.now() - started) / 1000) * this.sampleRate);
      while (pos + this.blockSize <= due) {
        onBlock(voice.next(this.blockSize, getTonic(), getPositions()));
        pos += this.blockSize;
      }
    }, 10);
  }

  stop() {
    clearInterval(this.timer);
    this.timer = null;
  }
}

/** A soft drone on the tonic and the octave below, to sing against. */
export class Drone {
  constructor() {
    this.nodes = null;
  }

  get playing() {
    return this.nodes !== null;
  }

  start(tonicHz, gain = 0.12) {
    this.stop();
    const ctx = audioContext();
    const out = ctx.createGain();
    out.gain.setValueAtTime(0, ctx.currentTime);
    out.gain.linearRampToValueAtTime(gain, ctx.currentTime + 0.4);
    const filter = ctx.createBiquadFilter();
    filter.type = "lowpass";
    filter.frequency.value = tonicHz * 4;
    filter.connect(out).connect(ctx.destination);
    const oscs = [[tonicHz, 0.6, "sawtooth"], [tonicHz / 2, 0.5, "triangle"]].map(([f, g, type]) => {
      const osc = ctx.createOscillator();
      osc.type = type;
      osc.frequency.value = f;
      const level = ctx.createGain();
      level.gain.value = g;
      osc.connect(level).connect(filter);
      osc.start();
      return osc;
    });
    this.nodes = { out, oscs };
  }

  setTonic(tonicHz) {
    if (!this.nodes) return;
    const [a, b] = this.nodes.oscs;
    a.frequency.value = tonicHz;
    b.frequency.value = tonicHz / 2;
  }

  stop() {
    if (!this.nodes) return;
    const ctx = audioContext();
    const { out, oscs } = this.nodes;
    out.gain.cancelScheduledValues(ctx.currentTime);
    out.gain.setValueAtTime(out.gain.value, ctx.currentTime);
    out.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.2);
    oscs.forEach((o) => o.stop(ctx.currentTime + 0.25));
    this.nodes = null;
  }
}

/** Keeps the screen on while listening. Re-acquired when the page comes back. */
export class ScreenAwake {
  constructor() {
    this.lock = null;
    this.wanted = false;
    document.addEventListener("visibilitychange", () => {
      if (this.wanted && document.visibilityState === "visible") this.acquire();
    });
  }

  async acquire() {
    this.wanted = true;
    try {
      if ("wakeLock" in navigator) this.lock = await navigator.wakeLock.request("screen");
    } catch {
      this.lock = null;           // not allowed (battery saver); the app works anyway
    }
  }

  release() {
    this.wanted = false;
    if (this.lock) this.lock.release().catch(() => {});
    this.lock = null;
  }
}
