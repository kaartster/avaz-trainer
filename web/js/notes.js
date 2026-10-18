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

// ---------------------------------------------------------------- key from a file name
//
// The teacher names recordings after their key: "دشتی فا دیز" (Dashti in Fa diez),
// "دشتی ر", "دشتی می بمل". The name gives the note but not the octave, so the
// octave is picked from where the voice actually sits (see tonicFromName).

const PERSIAN_NOTES = { "دو": 0, "ره": 2, "ر": 2, "ری": 2, "می": 4, "فا": 5, "سل": 7, "سول": 7,
  "لا": 9, "سی": 11 };
const LATIN_NOTES = { do: 0, re: 2, mi: 4, fa: 5, sol: 7, la: 9, si: 11 };
const SHARP = ["دیز", "diez", "dies", "sharp", "#"];
const FLAT = ["بمل", "bemol", "flat"];

// Longest names first, so "سول" is tried before "سل" and "ره" before "ر".
// None of the names contain regex special characters, so they go in as they are.
const NOTE_ALTERNATIVES = [...Object.keys(PERSIAN_NOTES), ...Object.keys(LATIN_NOTES)]
  .sort((a, b) => b.length - a.length).join("|");
// Not preceded or followed by a letter or digit (any script).
const KEY_PATTERN = new RegExp(
  String.raw`(?<![\p{L}\p{N}])(${NOTE_ALTERNATIVES})[ _\-]?(${[...SHARP, ...FLAT].join("|")})?` +
  String.raw`(?![\p{L}\p{N}#])`, "giu");

/**
 * Note index (0 = Do ... 11 = Si) of the key written in a recording's name, or null.
 * The last note name wins: the key is written at the end, and earlier words in a
 * title can look like note names ("می" is also a common verb prefix in Persian).
 */
export function keyFromName(name) {
  let text = String(name).replace(/‌/g, "");       // zero width non-joiner
  for (const suffix of [".vocals", ".accompaniment"]) text = text.split(suffix).join(" ");
  text = text.replace(/\.\w+$/, "").replace(/["'«»“”]/g, " ");
  const matches = [...text.matchAll(KEY_PATTERN)];
  if (matches.length === 0) return null;
  const last = matches[matches.length - 1];
  const note = last[1].toLowerCase(), accidental = (last[2] || "").toLowerCase();
  let index = note in PERSIAN_NOTES ? PERSIAN_NOTES[note] : LATIN_NOTES[note];
  if (SHARP.includes(accidental)) index += 1;
  else if (FLAT.includes(accidental)) index -= 1;
  return ((index % 12) + 12) % 12;
}

// In Dashti the melody sits mostly below the tonic: across the teacher's recordings
// the median pitch is 200 to 250 cents (about a whole tone) under it.
export const TONIC_ABOVE_MEDIAN_CENTS = 250;

/** The tonic in Hz from the key in `name`, in the octave that fits the voice, or null. */
export function tonicFromName(name, medianHz) {
  const index = keyFromName(name);
  if (index === null || !(medianHz > 0)) return null;
  const target = 69 + 12 * Math.log2(medianHz / A4_HZ) + TONIC_ABOVE_MEDIAN_CENTS / 100;
  const midi = index + 12 * Math.round((target - index) / 12);
  return A4_HZ * Math.pow(2, (midi - 69) / 12);
}
