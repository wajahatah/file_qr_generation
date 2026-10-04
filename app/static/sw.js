// Present so Edge and Chrome offer "Install app". It deliberately caches nothing:
// every request goes to the network, so the app can never show a stale QR code or
// an out-of-date limit.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
