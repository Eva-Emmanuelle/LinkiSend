// --- LinkiSend SW (cache + offline) ---
const CACHE_NAME = "linkisend-v3";
const ASSETS = [
  "/",                     // app shell
  "/index.html",
  "/claim.html",
  "/confirmation.html",
  "/history.html",
  "/send.html",
  "/countries.js",
  "/config.js",
  "/assets/branding/logo-word.svg",
  "/assets/branding/logo-arrow.svg",
  "/assets/icons/icon-192.png",
  "/assets/icons/icon-512.png"
];

// Install: pré-cache des fichiers essentiels
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(ASSETS))
      .then(() => self.skipWaiting())
  );
});

// Activate: purge des anciens caches
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.map((k) => (k === CACHE_NAME ? null : caches.delete(k))))
    ).then(() => self.clients.claim())
  );
});

// Fetch: 
// - Navigation -> réseau d'abord, fallback offline vers index.html
// - Assets précachés -> cache d'abord
// - Autres -> réseau, fallback cache si offline
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // Ne jamais intercepter ton API backend
  if (url.pathname.endsWith('/manifest.json')) return;
  if (url.pathname.startsWith("/create-link")) return;

  // 1) Requêtes de navigation (tap sur liens / rechargement)
  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request).catch(() => caches.match("/index.html"))
    );
    return;
  }

  // 2) Fichiers connus (pré-cachés)
  if (ASSETS.includes(url.pathname)) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        if (cached) return cached;
        return fetch(event.request).then((resp) => {
          const copy = resp.clone();
          caches.open(CACHE_NAME).then((c) => c.put(event.request, copy));
          return resp;
        });
      })
    );
    return;
  }

  // 3) Par défaut
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request))
  );
});
