// The settings sheet (my key, dastgah, feedback) and the key picker it shares with
// the song sheet.

import { LANGS, dastgahName, keyText, noteName, num, setLang, t } from "./i18n.js";
import { WESTERN, noteToHz } from "./notes.js";
import { chosenLang, saveSettings, scale, scales, settings, tonicHz } from "./settings.js";
import { $, applyLanguage, options } from "./ui.js";

/** Twelve note buttons and an octave choice. `onChange({keyIndex, octave})`. */
export function keyPicker(grid, octaves, value, onChange) {
  options(grid, WESTERN.map((w, i) => ({ value: i, label: noteName(i), small: w })), value.keyIndex,
    (keyIndex) => onChange({ ...value, keyIndex }));
  options(octaves, [2, 3, 4].map((o) => ({
    value: o, label: `${WESTERN[value.keyIndex]}${o}`,
    small: t(o === 2 ? "octaveLow" : o === 3 ? "octaveMiddle" : "octaveHigh"),
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
  options($("langs"), Object.entries(LANGS).map(([value, label]) => ({ value, label })), chosenLang(), (v) => {
    settings.lang = v;
    setLang(v);
    applyLanguage();
    changed();
  });
  keyPicker($("keyGrid"), $("octaves"), settings, (k) => {
    settings.keyIndex = k.keyIndex;
    settings.octave = k.octave;
    changed();
  });
  $("fine").value = settings.fine;
  const fine = settings.fine ? ` ${t("fineCents", { n: num(`${settings.fine > 0 ? "+" : ""}${settings.fine}`) })}` : "";
  $("keyHz").textContent = t("keyHz", { key: keyText(noteToHz(settings.keyIndex, settings.octave)), fine,
                                        hz: num(tonicHz().toFixed(1)) });
  $("keyIntro").classList.toggle("attention", !settings.configured);
  options($("scales"), Object.keys(scales).map((n) => ({ value: n, label: dastgahName(n) })),
    scale().name, (v) => { settings.scale = v; changed(); });
  options($("levels"), [
    { value: "gentle", label: t("gentle"), small: t("plainWords") },
    { value: "detailed", label: t("detailed"), small: t("withCents") },
  ], settings.level, (v) => { settings.level = v; changed(); });
  options($("smoothing"), [[1, "off"], [3, "light"], [7, "strong"]].map(([v, l]) => ({ value: v, label: t(l) })),
    settings.smoothing, (v) => { settings.smoothing = v; changed(); });
  options($("history"), [4, 6, 10].map((v) => ({ value: v, label: t("seconds", { n: v }) })),
    settings.history, (v) => { settings.history = v; changed(); });
  $("gate").value = settings.gate;
  $("gateHelp").textContent = t("gateHelp", { db: settings.gate });
  $("sync").value = settings.sync;
  $("syncHelp").textContent = (settings.sync
    ? t(settings.sync > 0 ? "syncAhead" : "syncBack", { ms: Math.abs(settings.sync) }) : "") + t("syncHelp");
}

$("fine").addEventListener("input", (e) => { settings.fine = Number(e.target.value); changed(); });
$("gate").addEventListener("input", (e) => { settings.gate = Number(e.target.value); changed(); });
$("sync").addEventListener("input", (e) => { settings.sync = Number(e.target.value); changed(); });

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
