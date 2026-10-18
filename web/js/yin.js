// YIN pitch detection on one frame. A port of NumpyYin in src/avaz/pitch_live.py.
//
// For each candidate period tau, YIN measures how different the signal is from
// itself shifted by tau samples (the "difference function"). A periodic signal
// dips near zero at its period. The dips are normalised so the first one below a
// threshold can be picked, and the exact minimum is refined with a parabola.

/** In-place iterative radix-2 FFT on separate real and imaginary arrays. */
class FFT {
  constructor(n) {
    this.n = n;
    this.rev = new Uint32Array(n);
    const bits = Math.log2(n);
    for (let i = 0; i < n; i++) {
      let r = 0;
      for (let b = 0; b < bits; b++) r |= ((i >> b) & 1) << (bits - 1 - b);
      this.rev[i] = r;
    }
    this.cos = new Float64Array(n / 2);
    this.sin = new Float64Array(n / 2);
    for (let i = 0; i < n / 2; i++) {
      this.cos[i] = Math.cos((2 * Math.PI * i) / n);
      this.sin[i] = Math.sin((2 * Math.PI * i) / n);
    }
  }

  /** inverse = false: X[k] = sum x[j] e^{-2 pi i jk/n}. inverse = true: no 1/n scaling. */
  transform(re, im, inverse = false) {
    const n = this.n, rev = this.rev;
    for (let i = 0; i < n; i++) {
      const j = rev[i];
      if (j > i) {
        let t = re[i]; re[i] = re[j]; re[j] = t;
        t = im[i]; im[i] = im[j]; im[j] = t;
      }
    }
    const sign = inverse ? 1 : -1;
    for (let size = 2; size <= n; size <<= 1) {
      const half = size >> 1, step = n / size;
      for (let start = 0; start < n; start += size) {
        for (let k = 0; k < half; k++) {
          const wr = this.cos[k * step], wi = sign * this.sin[k * step];
          const a = start + k, b = a + half;
          const xr = re[b] * wr - im[b] * wi;
          const xi = re[b] * wi + im[b] * wr;
          re[b] = re[a] - xr; im[b] = im[a] - xi;
          re[a] += xr; im[a] += xi;
        }
      }
    }
  }
}

export class Yin {
  constructor({ sampleRate = 44100, frameLength = 2048, fmin = 70, fmax = 1000,
                threshold = 0.15, silenceRms = 0.005 } = {}) {
    this.sampleRate = sampleRate;
    this.frameLength = frameLength;
    this.fmin = fmin;
    this.fmax = fmax;
    this.threshold = threshold;
    this.silenceRms = silenceRms;
    this.tauMin = Math.max(1, Math.floor(sampleRate / fmax));
    this.tauMax = Math.ceil(sampleRate / fmin);
    if (this.tauMax >= frameLength) {
      throw new Error("frameLength must be larger than sampleRate / fmin");
    }
    // Number of samples compared for each lag. Constant so all lags are comparable.
    this.window = frameLength - this.tauMax;
    this.nfft = 1 << Math.ceil(Math.log2(frameLength + this.window));
    this.fft = new FFT(this.nfft);
    this.re = new Float64Array(this.nfft);
    this.im = new Float64Array(this.nfft);
    this.pr = new Float64Array(this.nfft);
    this.pi = new Float64Array(this.nfft);
    this.sq = new Float64Array(frameLength + 1);
    this.d = new Float64Array(this.tauMax + 1);
    this.cmnd = new Float64Array(this.tauMax + 1);
  }

  /** d[tau] = sum_j (x[j] - x[j+tau])^2, j in [0, window), tau in [0, tauMax]. */
  differenceFunction(x) {
    const n = this.nfft, w = this.window;
    const { re, im, pr, pi } = this;
    // Two real FFTs in one: z = x + i * x[:w]. Then X and Xw are separated from Z.
    for (let j = 0; j < n; j++) {
      re[j] = j < x.length ? x[j] : 0;
      im[j] = j < w ? x[j] : 0;
    }
    this.fft.transform(re, im);
    // Cross term c(tau) = sum_j x[j + tau] * x[j]: its spectrum is X * conj(Xw).
    for (let k = 0; k < n; k++) {
      const m = (n - k) % n;
      const xr = (re[k] + re[m]) / 2, xi = (im[k] - im[m]) / 2;   // X[k]
      const wr = (im[k] + im[m]) / 2, wi = (re[m] - re[k]) / 2;   // Xw[k]
      pr[k] = xr * wr + xi * wi;
      pi[k] = xi * wr - xr * wi;
    }
    this.fft.transform(pr, pi, true);
    const sq = this.sq;
    sq[0] = 0;
    for (let j = 0; j < this.frameLength; j++) sq[j + 1] = sq[j] + x[j] * x[j];
    const e0 = sq[w];
    const d = this.d;
    for (let tau = 0; tau <= this.tauMax; tau++) {
      const v = e0 + (sq[tau + w] - sq[tau]) - (2 * pr[tau]) / n;
      d[tau] = v > 0 ? v : 0;
    }
    return d;
  }

  cumulativeMeanNormalized(d) {
    const out = this.cmnd;
    out[0] = 1;
    let sum = 0;
    for (let tau = 1; tau < d.length; tau++) {
      sum += d[tau];
      out[tau] = sum > 0 ? (d[tau] * tau) / sum : 1;
    }
    return out;
  }

  /** f0 in Hz for one frame of `frameLength` samples, or NaN when unvoiced. */
  detect(frame) {
    if (frame.length !== this.frameLength) {
      throw new Error(`expected ${this.frameLength} samples, got ${frame.length}`);
    }
    if (rms(frame) < this.silenceRms) return NaN;
    const cmnd = this.cumulativeMeanNormalized(this.differenceFunction(frame));
    const lo = this.tauMin, hi = this.tauMax;
    // First lag below the threshold, then walk down to the local minimum.
    let tau = -1;
    for (let t = lo; t < hi; t++) {
      if (cmnd[t] < this.threshold) { tau = t; break; }
    }
    if (tau < 0) return NaN;
    while (tau + 1 < hi && cmnd[tau + 1] < cmnd[tau]) tau++;
    // Parabolic interpolation around the minimum for sub-sample precision.
    let shift = 0;
    if (tau > 0 && tau < cmnd.length - 1) {
      const a = cmnd[tau - 1], b = cmnd[tau], c = cmnd[tau + 1];
      const denom = a - 2 * b + c;
      shift = denom !== 0 ? (0.5 * (a - c)) / denom : 0;
      shift = Math.max(-1, Math.min(1, shift));
    }
    return this.sampleRate / (tau + shift);
  }
}

export function rms(x) {
  let s = 0;
  for (let i = 0; i < x.length; i++) s += x[i] * x[i];
  return Math.sqrt(s / x.length);
}

export function dbToRms(db) {
  return Math.pow(10, db / 20);
}
