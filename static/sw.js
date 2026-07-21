/// <reference lib="webworker" />

const CACHE = "alex-nexus-mark3-hardware-v3";
const APP_SHELL = [
  "/",
  "/static/styles.css?v=hardware-v3",
  "/static/styles/tokens.css?v=hardware-v3",
  "/static/styles/base.css?v=hardware-v3",
  "/static/styles/presence.css?v=hardware-v3",
  "/static/styles/command-center.css?v=hardware-v3",
  "/static/styles/responsive.css?v=hardware-v3",
  "/static/app.js?v=hardware-v3",
  "/static/core/audio-waveform.js",
  "/static/core/core-renderer.js",
  "/static/core/core-visuals.js",
  "/static/core/frame-loop.js",
  "/static/core/api.js",
  "/static/core/alex-state.js",
  "/static/core/command-lifecycle.js",
  "/static/core/realtime.js",
  "/static/core/quality.js",
  "/static/core/sound-engine.js",
  "/static/ui/elements-phase2.js",
  "/static/ui/presence-commands.js",
  "/static/ui/presence-view.js",
  "/static/ui/workspaces.js",
  "/static/icon.svg",
  "/manifest.webmanifest",
];

const serviceWorker = /** @type {ServiceWorkerGlobalScope} */ (/** @type {unknown} */ (globalThis));

serviceWorker.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(APP_SHELL)));
  serviceWorker.skipWaiting();
});

serviceWorker.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
      .then(() => serviceWorker.clients.claim())
  );
});

serviceWorker.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.pathname.startsWith("/api/") || url.pathname === "/health" || event.request.method !== "GET") return;

  if (event.request.mode === "navigate") {
    event.respondWith(fetch(event.request).catch(async () => (
      await caches.match("/") ?? new Response("ALEX app shell unavailable", { status: 503 })
    )));
    return;
  }

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response.ok && url.origin === serviceWorker.location.origin) {
          const clone = response.clone();
          void caches.open(CACHE).then((cache) => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(async () => await caches.match(event.request) ?? new Response("Asset unavailable", { status: 503 }))
  );
});
