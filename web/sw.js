// Service worker: lets the app open without a network connection, and receives
// recordings shared to the app from other apps (WhatsApp, Files) on Android.
// Network first, so a new version shows up as soon as it is online; the cache is
// the fallback when offline.

const CACHE = "avaz-v3";
const SHELL = [
  "./", "index.html", "css/app.css", "scales.json", "manifest.webmanifest",
  "icons/icon.svg", "icons/icon-192.png", "icons/icon-512.png",
  "js/analyze-worker.js", "js/app.js", "js/audio.js", "js/capture-worklet.js", "js/cents.js",
  "js/chart.js", "js/demo.js", "js/feedback.js", "js/home.js", "js/library.js", "js/live.js",
  "js/notes.js", "js/offline.js", "js/player.js", "js/scales.js", "js/settings.js", "js/sheet.js",
  "js/song.js", "js/store.js", "js/stream.js", "js/turns.js", "js/ui.js", "js/yin.js", "js/zoom.js",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE && k !== "avaz-share").map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

/** The share sheet posts the file here (see share_target in the manifest). */
async function receiveShare(request) {
  const form = await request.formData();
  const file = form.getAll("audio").find((f) => f && typeof f !== "string");
  if (file) {
    const cache = await caches.open("avaz-share");
    await cache.put("shared-file", new Response(file, {
      headers: { "content-type": file.type || "audio/*", "x-file-name": encodeURIComponent(file.name || "shared recording") },
    }));
  }
  return Response.redirect(new URL("./#/import-shared", self.registration.scope).href, 303);
}

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method === "POST" && url.pathname.endsWith("/share")) {
    e.respondWith(receiveShare(e.request));
    return;
  }
  if (e.request.method !== "GET") return;
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        if (res.ok && url.origin === location.origin) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
        }
        return res;
      })
      .catch(() => caches.match(e.request, { ignoreSearch: true })),
  );
});
