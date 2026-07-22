/* Onboarder service worker — caches only the static app shell so the UI loads
   offline and installs as a PWA. It NEVER caches API/SSE traffic: those are
   dynamic, per-workspace, and often streaming, so they always hit the network. */
const CACHE = "onboarder-shell-v1";

// Same-origin static build assets that are safe to cache.
const STATIC_RE = /\/assets\/|\.(?:js|css|svg|png|ico|webmanifest|woff2?)$/;

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(["./", "./index.html"]).catch(() => undefined)),
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;                         // never touch writes
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;          // let cross-origin (CDN fonts, API) pass

  // App navigations: network-first, fall back to the cached shell when offline.
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put("./index.html", copy)).catch(() => undefined);
          return res;
        })
        .catch(() => caches.match("./index.html").then((r) => r || caches.match("./"))),
    );
    return;
  }

  // Static build assets: cache-first with background refresh. Everything else
  // (API calls, /events SSE — no file extension) is left to the network.
  if (STATIC_RE.test(url.pathname)) {
    event.respondWith(
      caches.match(req).then((cached) => {
        const network = fetch(req)
          .then((res) => {
            if (res.ok) {
              const copy = res.clone();
              caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => undefined);
            }
            return res;
          })
          .catch(() => cached);
        return cached || network;
      }),
    );
  }
});
