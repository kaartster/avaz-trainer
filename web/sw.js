// Service worker: lets the app open without a network connection.
// Network first, so a new version shows up as soon as it is online; the cache is
// the fallback when offline.

const CACHE = "avaz-v1";
const SHELL = [
  "./", "index.html", "css/app.css", "scales.json", "manifest.webmanifest",
  "icons/icon.svg", "icons/icon-192.png", "icons/icon-512.png",
  "js/app.js", "js/audio.js", "js/capture-worklet.js", "js/cents.js", "js/chart.js",
  "js/demo.js", "js/feedback.js", "js/notes.js", "js/scales.js", "js/stream.js", "js/yin.js",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        if (res.ok && new URL(e.request.url).origin === location.origin) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
        }
        return res;
      })
      .catch(() => caches.match(e.request, { ignoreSearch: true })),
  );
});
