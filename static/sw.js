// Minimal service worker to make 4orm installable as a PWA.
// No caching — the site is server-rendered and needs network access.
self.addEventListener("fetch", function (event) {
  event.respondWith(fetch(event.request));
});
