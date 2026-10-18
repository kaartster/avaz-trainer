// Plain words for the live readout: which note I'm on and whether I'm in tune.
//
// The gentle level (default) is lenient and says only "in tune", "a bit low" or
// "low". The detailed level is stricter and the UI also shows the cents.

import { nearestNote } from "./scales.js";

export const LEVELS = {
  gentle: { tolerance: 30 },
  detailed: { tolerance: 25 },
};

/**
 * Keeps the current note steady while the voice slides between two notes:
 * it only switches when the new note is clearly closer (by `margin` cents).
 */
export class NoteTracker {
  constructor(scale, margin = 15) {
    this.scale = scale;
    this.margin = margin;
    this.current = null;
  }

  update(cents) {
    if (!Number.isFinite(cents)) return this.current;
    const near = nearestNote(cents, this.scale);
    const cur = this.current;
    if (cur === null ||
        Math.abs(cents - cur.position) > Math.abs(cents - near.position) + this.margin) {
      this.current = { position: near.position, label: near.label };
    }
    return this.current;
  }

  reset() {
    this.current = null;
  }
}

/** {state, words, arrow} for a deviation in cents from the current note. */
export function tuneWords(deviation, level = "gentle") {
  if (!Number.isFinite(deviation)) return { state: "silent", words: "Listening", arrow: "" };
  const tol = (LEVELS[level] || LEVELS.gentle).tolerance;
  const a = Math.abs(deviation);
  if (a <= tol) return { state: "in", words: "In tune", arrow: "" };
  const low = deviation < 0;
  const bit = a <= 2 * tol;
  return {
    state: low ? "low" : "high",
    words: `${bit ? "A bit " : ""}${low ? "low" : "high"}, go ${low ? "up" : "down"}`
      .replace(/^./, (s) => s.toUpperCase()),
    arrow: low ? "up" : "down",
  };
}
