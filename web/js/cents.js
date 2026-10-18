// Hz <-> cents and octave folding. Same behavior as src/avaz/cents.py.
//
// Cents are a logarithmic pitch unit: 1200 cents is one octave, 100 cents one
// equal tempered semitone. Unvoiced frames are NaN and stay NaN.

export const OCTAVE = 1200;

export function hzToCents(f0Hz, tonicHz) {
  if (!(f0Hz > 0)) return NaN;
  return OCTAVE * Math.log2(f0Hz / tonicHz);
}

export function centsToHz(cents, tonicHz) {
  return tonicHz * Math.pow(2, cents / OCTAVE);
}

/** Fold into [0, 1200). */
export function foldOctave(cents) {
  return ((cents % OCTAVE) + OCTAVE) % OCTAVE;
}

/** Shift by whole octaves so the value lands within 600 cents of `reference`. */
export function foldToReference(cents, reference) {
  return cents + Math.round((reference - cents) / OCTAVE) * OCTAVE;
}

/** Median of the finite values, NaN when there are none. */
export function median(values) {
  const v = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (v.length === 0) return NaN;
  const m = v.length >> 1;
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
}
