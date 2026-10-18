// Adding a teacher recording on the phone: decode, analyze, find the key, store.

import { median } from "./cents.js";
import { ANALYSIS, estimateTonic } from "./offline.js";
import { keyFromName, tonicFromName } from "./notes.js";
import { putSong } from "./store.js";

/** Decode any file Chrome can play (m4a, mp3, opus, wav) to mono at `sampleRate`. */
export async function decodeMono(blob, sampleRate) {
  const ctx = new OfflineAudioContext(1, 1, sampleRate);
  const audio = await ctx.decodeAudioData(await blob.arrayBuffer());
  const n = audio.length, chans = audio.numberOfChannels;
  const mono = new Float32Array(n);
  for (let c = 0; c < chans; c++) {
    const data = audio.getChannelData(c);
    for (let i = 0; i < n; i++) mono[i] += data[i] / chans;
  }
  return mono;
}

function analyzeInWorker(samples, sampleRate, onProgress) {
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL("./analyze-worker.js", import.meta.url), { type: "module" });
    worker.onmessage = (e) => {
      if (e.data.progress !== undefined) onProgress(e.data.progress);
      if (e.data.done) {
        worker.terminate();
        resolve({ hop: e.data.hop, f0: e.data.f0 });
      }
    };
    worker.onerror = (e) => {
      worker.terminate();
      reject(new Error(e.message || "analysis failed"));
    };
    worker.postMessage({ samples, sampleRate }, [samples.buffer]);
  });
}

/** A readable song name from a file name: no extension, underscores as spaces. */
export function songTitle(fileName) {
  return fileName.replace(/\.[^.]+$/, "").replace(/[_]+/g, " ").replace(/\s+/g, " ").trim();
}

/**
 * Import one recording. `onStep(text, fraction)` reports progress.
 * The teacher's key comes from the file name when it is written there
 * ("... دشتی فا دیز"), otherwise it is a guess the singer should check.
 */
export async function importRecording(file, defaults, onStep = () => {}) {
  onStep("Opening the recording", 0);
  let samples;
  try {
    samples = await decodeMono(file, ANALYSIS.sampleRate);
  } catch {
    throw new Error("This file could not be opened as audio.");
  }
  const duration = samples.length / ANALYSIS.sampleRate;
  onStep("Finding the teacher's notes", 0);
  const { hop, f0 } = await analyzeInWorker(samples, ANALYSIS.sampleRate,
    (p) => onStep("Finding the teacher's notes", p));
  const voiced = Array.from(f0).filter(Number.isFinite);
  if (voiced.length < 50) throw new Error("No singing found in this recording.");
  let tonic = tonicFromName(file.name, median(voiced));
  const tonicSource = tonic ? "name" : "guess";
  if (!tonic) tonic = estimateTonic(f0);
  const song = {
    id: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`,
    name: songTitle(file.name),
    fileName: file.name,
    added: Date.now(),
    blob: file,
    duration,
    hop,
    f0,
    teacherTonicHz: tonic,
    tonicSource,
    // When the teacher recorded it in my key ("... دشتی ر" for a singer in Re), I sing
    // it as it is. Otherwise in my own key, compared relative to each tonic.
    sameKey: keyFromName(file.name) === defaults.keyIndex,
    myKey: { ...defaults },
    lastPos: 0,
  };
  onStep("Saving", 1);
  await putSong(song);
  return song;
}
