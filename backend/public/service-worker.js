// --- LinkiSend SW (cache statique minimal) ---
const CACHE_NAME = "linkisend-v1";
const ASSETS = [
  "/",
  "/index.html",
  "/countries.js",
  "/config.js",
  "/assets/branding/logo-word.svg",
  "/assets/branding/logo-arrow.svg"
];

// Installation: pré-cache
self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS)).then(() => self.skipWaiting())
  );
});

// Activation: nettoyage anciens caches
self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.map((k) => (k === CACHE_NAME ? null : caches.delete(k))))
    ).then(() => self.clients.claim())
  );
});

// Fetch: cache-first sur statiques / network-first pour le reste
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);

  // ne jamais mettre en cache l’API backend
  if (url.pathname.startsWith("/create-link")) return;

  // statiques connus -> cache d’abord
  if (ASSETS.includes(url.pathname)) {
    e.respondWith(
      caches.match(e.request).then((res) => res || fetch(e.request))
    );
    return;
  }

  // le reste -> réseau, fallback cache si offline
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request))
  );
});
