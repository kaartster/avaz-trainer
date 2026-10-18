// Settings shared by all screens, kept in the browser (each singer has their own).

import { LEVELS } from "./feedback.js";
import { noteToHz } from "./notes.js";
import { scalesFromJson } from "./scales.js";

// Used only if scales.json can't be loaded. `avaz web` exports the real ones.
const FALLBACK_SCALES = {
  shur: { positions: [0, 150, 300, 500, 700, 800, 1000, 1200] },
  mahur: { positions: [0, 200, 400, 500, 700, 900, 1100, 1200] },
};

const DEFAULTS = {
  keyIndex: 2, octave: 3, fine: 0,   // Re (D3) until the singer picks their own key
  scale: "dashti", level: "gentle", view: "notes",
  smoothing: 3, history: 6, gate: -55, configured: false,
};

function load() {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem("avaz.settings") || "{}") };
  } catch {
    return { ...DEFAULTS };
  }
}

export const settings = load();

export function saveSettings() {
  try {
    localStorage.setItem("avaz.settings", JSON.stringify(settings));
  } catch { /* private mode: settings last for this visit only */ }
}

export let scales = scalesFromJson(FALLBACK_SCALES);

export async function loadScales() {
  try {
    const res = await fetch("scales.json", { cache: "no-cache" });
    if (res.ok) scales = scalesFromJson(await res.json());
  } catch { /* offline without a cached copy: built-in scales */ }
}

/** Hz of a key {keyIndex, octave, fine}. */
export const keyHz = (k) => noteToHz(k.keyIndex, k.octave) * Math.pow(2, (k.fine || 0) / 1200);
/** My default key, the one chosen in the settings sheet. */
export const myKey = () => ({ keyIndex: settings.keyIndex, octave: settings.octave, fine: settings.fine });
export const tonicHz = () => keyHz(settings);
export const scale = () => scales[settings.scale] || Object.values(scales)[0];
export const tolerance = () => (LEVELS[settings.level] || LEVELS.gentle).tolerance;
export const titleCase = (s) => s.charAt(0).toUpperCase() + s.slice(1);
