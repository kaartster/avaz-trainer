// A synthetic singing voice for the demo mode: it walks the scale notes around the
// tonic with vibrato, short slides, slightly off notes and breaths. It lets the app
// (and its tests) run without a microphone.

const PATTERN = [
  // [scale step relative to the tonic, seconds, cents off the note]
  [0, 1.4, 0], [1, 0.9, -10], [2, 1.2, 35], [1, 0.7, 0], [0, 1.6, -5], [null, 0.5, 0],
  [-1, 1.0, 0], [-2, 1.3, -40], [-1, 0.8, 5], [0, 2.0, 0], [null, 0.7, 0],
  [2, 1.0, 0], [3, 1.2, 15], [4, 1.5, 0], [3, 0.6, -45], [2, 1.0, 0], [null, 0.6, 0],
];

/** The cents of scale step `step` (0 = tonic, negative = below) for positions in one octave. */
function stepCents(positions, step) {
  const base = positions.filter((p) => p >= 0 && p < 1200);
  const n = base.length;
  const octave = Math.floor(step / n);
  return base[((step % n) + n) % n] + 1200 * octave;
}

export function demoVoice(sampleRate) {
  let t = 0;                // seconds since start
  let phase = 0;
  let cents = 0;            // glides toward the target
  const total = PATTERN.reduce((s, p) => s + p[1], 0);

  function target(positions) {
    let x = t % total;
    for (const [step, dur, off] of PATTERN) {
      if (x < dur) return step === null ? null : stepCents(positions, step) + off;
      x -= dur;
    }
    return null;
  }

  return {
    next(n, tonicHz, positions) {
      const out = new Float32Array(n);
      for (let i = 0; i < n; i++) {
        const goal = target(positions);
        if (goal === null) {
          out[i] = 0.0005 * (Math.random() - 0.5);       // breath: near silence
        } else {
          cents += (goal - cents) * Math.min(1, 25 / sampleRate);   // about 40 ms slides
          const vibrato = 18 * Math.sin(2 * Math.PI * 5.5 * t);
          const f = tonicHz * Math.pow(2, (cents + vibrato) / 1200);
          phase += (2 * Math.PI * f) / sampleRate;
          // A few harmonics so it sounds (to YIN) like a voice, not a sine.
          out[i] = 0.18 * Math.sin(phase) + 0.08 * Math.sin(2 * phase) + 0.04 * Math.sin(3 * phase);
        }
        t += 1 / sampleRate;
      }
      if (phase > 1e6) phase %= 2 * Math.PI;
      return out;
    },
  };
}
