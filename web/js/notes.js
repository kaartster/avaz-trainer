// Note names for choosing a key and naming scale notes. Port of src/avaz/keys.py.
//
// Solfege first (Do, Re, Mi ...) because keys are named that way in class; the
// Western name with its octave number is a secondary label. Equal tempered with
// A4 = 440 Hz, only for naming. The notes of the dastgah come from scales.json.

export const SOLFEGE = ["Do", "Do diez", "Re", "Mi bemol", "Mi", "Fa", "Fa diez", "Sol",
  "Sol diez", "La", "Si bemol", "Si"];
export const WESTERN = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "G#", "A", "Bb", "B"];
const A4_HZ = 440;

/** Frequency of note `index` (0 = Do ... 11 = Si) in `octave` (C4 = middle C). */
export function noteToHz(index, octave) {
  const midi = 12 * (octave + 1) + index;
  return A4_HZ * Math.pow(2, (midi - 69) / 12);
}

/** Nearest note: {index, octave, off}, off in cents within [-50, 50]. */
export function hzToNote(hz) {
  const midi = 69 + 12 * Math.log2(hz / A4_HZ);
  const nearest = Math.round(midi);
  return { index: ((nearest % 12) + 12) % 12, octave: Math.floor(nearest / 12) - 1,
           off: 100 * (midi - nearest) };
}

/** "Re (D3)" */
export function keyLabel(hz) {
  const { index, octave } = hzToNote(hz);
  return `${SOLFEGE[index]} (${WESTERN[index]}${octave})`;
}

const NATURAL = new Set([0, 2, 4, 5, 7, 9, 11]);

/**
 * Solfege name of the note `cents` above `tonicHz`, with koron and sori.
 * Within 25 cents of an equal tempered semitone it gets that name ("Sol").
 * In between: sori on the natural note below (Mi + 150 is "Fa sori"), otherwise
 * koron on the natural note above (La + 150 is "Si koron").
 */
export function scaleNoteName(tonicHz, cents) {
  const { index, off } = hzToNote(tonicHz * Math.pow(2, cents / 1200));
  if (Math.abs(off) <= 25) return SOLFEGE[index];
  const lower = off > 0 ? index : (index + 11) % 12;
  const upper = (lower + 1) % 12;
  if (NATURAL.has(lower)) return `${SOLFEGE[lower]} sori`;
  if (NATURAL.has(upper)) return `${SOLFEGE[upper]} koron`;
  return SOLFEGE[index];
}
