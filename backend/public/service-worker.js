// service-worker.js — LinkiSend (version minimale, sans cache ni fetch)

// Installe immédiatement la nouvelle version du SW
self.addEventListener("install", (event) => {
  self.skipWaiting();
});

// Prend le contrôle des pages ouvertes dès l’activation
self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

// Optionnel : permet à la page de forcer la mise à jour du SW
//   navigator.serviceWorker.controller?.postMessage({ type: "SKIP_WAITING" })
self.addEventListener("message", (event) => {
  if (event?.data && event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});

// IMPORTANT : pas de 'fetch' handler -> aucune interception réseau
