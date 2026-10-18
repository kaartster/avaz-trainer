// Runs the pitch analysis of a whole recording off the main thread, so the screen
// stays responsive and can show progress.

import { analyzeSamples } from "./offline.js";

self.onmessage = (e) => {
  const { samples, sampleRate } = e.data;
  const result = analyzeSamples(samples, sampleRate, {}, (p) => self.postMessage({ progress: p }));
  self.postMessage({ done: true, hop: result.hop, f0: result.f0 }, [result.f0.buffer]);
};
