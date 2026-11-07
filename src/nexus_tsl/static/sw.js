// Service worker aplikacji kierowcy: powłoka aplikacji działa offline,
// dane (API) zawsze z sieci - kierowca widzi aktualny stan zlecenia.
const CACHE = "nexus-driver-v1";
const SHELL = ["/driver", "/driver/manifest.webmanifest", "/driver/icon.svg"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || !SHELL.includes(url.pathname)) return;
  // network-first: nowa wersja, gdy jest sieć; kopia z cache, gdy jej brak
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});
