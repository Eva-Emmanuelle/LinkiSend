// service-worker.js — LinkiSend (version finale, sans cache réseau)

// Installe immédiatement la nouvelle version du SW
self.addEventListener("install", (event) => {
  self.skipWaiting();
});

// Active et prend le contrôle des pages ouvertes
self.addEventListener("activate", (event) => {
  event.waitUntil(
    // Supprime tous les anciens caches pour éviter les vieilles versions
    caches.keys().then(keys => Promise.all(keys.map(k => caches.delete(k))))
  );
  self.clients.claim();
});

// Permet à la page de forcer la mise à jour du SW si besoin
self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});

// ⚠️ Pas de 'fetch' handler : aucune interception réseau
