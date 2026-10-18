// Starts the app and switches between the screens: #/ (home), #/live, #/song/<id>.

import * as home from "./home.js";
import * as live from "./live.js";
import * as song from "./song.js";
import { loadScales, settings } from "./settings.js";
import { openSettings } from "./sheet.js";
import { $ } from "./ui.js";

const screens = { home, live, song };
let current = null;

async function route() {
  const hash = location.hash || "#/";
  if (hash.startsWith("#/import-shared")) {
    history.replaceState(null, "", location.pathname + location.search + "#/");
    await route();
    await importShared();
    return;
  }
  const [, name = "", arg] = hash.split("/");
  const next = name === "live" ? "live" : name === "song" && arg ? "song" : "home";
  if (current) {
    screens[current].leave();
    $(current).hidden = true;
  }
  current = next;
  $(next).hidden = false;
  await screens[next].enter(arg && decodeURIComponent(arg));
}

/** A recording shared to the app (Android share sheet) waits in a cache; add it. */
async function importShared() {
  if (!("caches" in window)) return;
  const cache = await caches.open("avaz-share");
  const res = await cache.match("shared-file");
  if (!res) return;
  await cache.delete("shared-file");
  const name = decodeURIComponent(res.headers.get("x-file-name") || "shared recording");
  const blob = await res.blob();
  await home.addRecording(new File([blob], name, { type: blob.type }));
}

async function init() {
  await loadScales();
  window.addEventListener("hashchange", route);
  await route();
  if (!settings.configured) openSettings();
  if ("serviceWorker" in navigator && window.isSecureContext) {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }
}

init();

// For the browser console and tests.
window.avaz = { settings, addRecording: home.addRecording };
