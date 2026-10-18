/* FitChat service worker. Deliberately minimal: it makes the app installable and never caches anything, so a new
   version of the app is always picked up and one person's data can never be served to another from a cache. */
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', () => { /* network only: let the browser handle every request normally */ });
