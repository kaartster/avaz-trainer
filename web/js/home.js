// Home: free singing, the teacher's recordings, and adding a new one.

import { importRecording } from "./library.js";
import { dastgahName, noteName, t } from "./i18n.js";
import { hzToNote } from "./notes.js";
import { myKey, scale, settings } from "./settings.js";
import { openSettings, onSettingsChange } from "./sheet.js";
import { countAttempts, keepStorage, listSongs } from "./store.js";
import { $, clock, esc, toast } from "./ui.js";

export async function enter() {
  refreshHeader();
  await renderList();
}

export function leave() {}

function refreshHeader() {
  $("homeKey").textContent = noteName(settings.keyIndex);
  $("homeScale").textContent = dastgahName(scale().name);
}

/** "Fa diez → you in Re" or "Re, the teacher's key". */
export function keyLine(song) {
  const teacher = noteName(hzToNote(song.teacherTonicHz).index);
  if (song.sameKey) return t("keyLineSame", { teacher });
  return t("keyLineOther", { teacher, mine: noteName(song.myKey.keyIndex) });
}

async function renderList() {
  let songs = [];
  try {
    songs = await listSongs();
  } catch {
    toast(t("noStorage"));
  }
  const list = $("songList");
  list.innerHTML = "";
  $("emptySongs").hidden = songs.length > 0;
  for (const song of songs) {
    const li = document.createElement("li");
    const tries = await countAttempts(song.id).catch(() => 0);
    li.innerHTML = `
      <a class="song-row" href="#/song/${encodeURIComponent(song.id)}">
        <span class="song-name" dir="auto">${esc(song.name)}</span>
        <span class="song-meta">${esc(keyLine(song))} · ${clock(song.duration)}${tries ? ` · ${esc(t("tries", { n: tries }))}` : ""}</span>
      </a>`;
    list.append(li);
  }
}

// ---------------------------------------------------------------- import

/** Import a file with a progress card, then open it. Used by the file picker and sharing. */
export async function addRecording(file) {
  keepStorage();
  const busy = $("busy");
  $("busyTitle").textContent = t("adding", { name: file.name });
  busy.hidden = false;
  try {
    const song = await importRecording(file, myKey(), (step, p) => {
      $("busyStep").textContent = p > 0 && p < 1 ? t("progress", { step, p: Math.round(p * 100) }) : step;
      $("busyFill").style.width = `${Math.round(p * 100)}%`;
    });
    if (song.tonicSource !== "name") {
      toast(t("noKeyInName"), 7000);
    }
    location.hash = `#/song/${encodeURIComponent(song.id)}`;
  } catch (err) {
    toast(err.message || t("addFailed"), 6000);
  } finally {
    busy.hidden = true;
    $("busyFill").style.width = "0";
  }
}

$("fileInput").addEventListener("change", (e) => {
  const file = e.target.files && e.target.files[0];
  e.target.value = "";
  if (file) addRecording(file);
});

$("homeSettings").addEventListener("click", openSettings);
onSettingsChange(() => {
  refreshHeader();
  if (!$("home").hidden) renderList();   // the language may have changed
});
