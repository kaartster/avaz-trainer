// Home: free singing, the teacher's recordings, and adding a new one.

import { importRecording } from "./library.js";
import { SOLFEGE, hzToNote } from "./notes.js";
import { myKey, scale, settings, titleCase } from "./settings.js";
import { openSettings, onSettingsChange } from "./sheet.js";
import { countAttempts, keepStorage, listSongs } from "./store.js";
import { $, clock, esc, toast } from "./ui.js";

export async function enter() {
  refreshHeader();
  await renderList();
}

export function leave() {}

function refreshHeader() {
  $("homeKey").textContent = SOLFEGE[settings.keyIndex];
  $("homeScale").textContent = titleCase(scale().name);
}

/** "Fa diez → you in Re" or "Re, the teacher's key". */
export function keyLine(song) {
  const teacher = SOLFEGE[hzToNote(song.teacherTonicHz).index];
  if (song.sameKey) return `${teacher}, the teacher's key`;
  return `Teacher in ${teacher}, you in ${SOLFEGE[song.myKey.keyIndex]}`;
}

async function renderList() {
  let songs = [];
  try {
    songs = await listSongs();
  } catch {
    toast("This browser does not allow storing recordings (private window?).");
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
        <span class="song-meta">${esc(keyLine(song))} · ${clock(song.duration)}${tries ? ` · ${tries} ${tries === 1 ? "try" : "tries"}` : ""}</span>
      </a>`;
    list.append(li);
  }
}

// ---------------------------------------------------------------- import

/** Import a file with a progress card, then open it. Used by the file picker and sharing. */
export async function addRecording(file) {
  keepStorage();
  const busy = $("busy");
  $("busyTitle").textContent = `Adding ${file.name}`;
  busy.hidden = false;
  try {
    const song = await importRecording(file, myKey(), (step, p) => {
      $("busyStep").textContent = p > 0 && p < 1 ? `${step}, ${Math.round(p * 100)}%` : step;
      $("busyFill").style.width = `${Math.round(p * 100)}%`;
    });
    if (song.tonicSource !== "name") {
      toast("The file name doesn't say the key. Check the teacher's key at the top of the song.", 7000);
    }
    location.hash = `#/song/${encodeURIComponent(song.id)}`;
  } catch (err) {
    toast(err.message || "Could not add this recording.", 6000);
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
onSettingsChange(refreshHeader);
