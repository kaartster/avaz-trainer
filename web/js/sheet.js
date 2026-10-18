// The settings sheet (my key, dastgah, feedback) and the key picker it shares with
// the song sheet.

import { SOLFEGE, WESTERN, keyLabel, noteToHz } from "./notes.js";
import { saveSettings, scale, scales, settings, titleCase, tonicHz } from "./settings.js";
import { $, options } from "./ui.js";

/** Twelve note buttons and an octave choice. `onChange({keyIndex, octave})`. */
export function keyPicker(grid, octaves, value, onChange) {
  options(grid, SOLFEGE.map((s, i) => ({ value: i, label: s, small: WESTERN[i] })), value.keyIndex,
    (keyIndex) => onChange({ ...value, keyIndex }));
  options(octaves, [2, 3, 4].map((o) => ({
    value: o, label: `${WESTERN[value.keyIndex]}${o}`,
    small: o === 2 ? "low" : o === 3 ? "middle" : "high",
  })), value.octave, (octave) => onChange({ ...value, octave }));
}

const listeners = [];
/** Called after any change in the settings sheet. */
export function onSettingsChange(fn) {
  listeners.push(fn);
}

function changed() {
  saveSettings();
  render();
  listeners.forEach((fn) => fn());
}

function render() {
  keyPicker($("keyGrid"), $("octaves"), settings, (k) => {
    settings.keyIndex = k.keyIndex;
    settings.octave = k.octave;
    changed();
  });
  $("fine").value = settings.fine;
  const fine = settings.fine ? ` ${settings.fine > 0 ? "+" : ""}${settings.fine} cents` : "";
  $("keyHz").textContent = `${keyLabel(noteToHz(settings.keyIndex, settings.octave))}${fine}, ${tonicHz().toFixed(1)} Hz`;
  $("keyIntro").classList.toggle("attention", !settings.configured);
  options($("scales"), Object.keys(scales).map((n) => ({ value: n, label: titleCase(n) })),
    scale().name, (v) => { settings.scale = v; changed(); });
  options($("levels"), [
    { value: "gentle", label: "Gentle", small: "plain words" },
    { value: "detailed", label: "Detailed", small: "with cents" },
  ], settings.level, (v) => { settings.level = v; changed(); });
  options($("smoothing"), [[1, "Off"], [3, "Light"], [7, "Strong"]].map(([v, l]) => ({ value: v, label: l })),
    settings.smoothing, (v) => { settings.smoothing = v; changed(); });
  options($("history"), [4, 6, 10].map((v) => ({ value: v, label: `${v} s` })),
    settings.history, (v) => { settings.history = v; changed(); });
  $("gate").value = settings.gate;
  $("gateHelp").textContent = `Sounds quieter than ${settings.gate} dB are ignored. ` +
    "Raise it in a noisy room, lower it if soft singing is missed.";
}

$("fine").addEventListener("input", (e) => { settings.fine = Number(e.target.value); changed(); });
$("gate").addEventListener("input", (e) => { settings.gate = Number(e.target.value); changed(); });

$("settings").addEventListener("close", () => {
  settings.configured = true;
  changed();
});

for (const id of ["settings", "songSheet"]) {
  // A tap on the dimmed backdrop closes a sheet.
  $(id).addEventListener("click", (e) => {
    if (e.target === $(id)) $(id).close();
  });
}

export function openSettings() {
  render();
  $("settings").showModal();
}

/** The icon on a view button shows what a tap switches to. */
export function viewIcon(button) {
  button.querySelector("svg").innerHTML = settings.view === "notes"
    ? '<path d="M3 15c3-8 5 4 8-3s5 2 10-5"/>'
    : '<path d="M4 7h7M13 12h7M6 17h8"/>';
}

export function toggleView() {
  settings.view = settings.view === "notes" ? "curve" : "notes";
  changed();
}
