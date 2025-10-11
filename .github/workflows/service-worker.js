const CACHE = "free-dash-v2";
const ASSETS = [
  "./",
  "./index.html",
  "./app.js",
  "./public/manifest.json",
  "./public/icons/icon-192.png",
  "./public/icons/icon-512.png"
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// 對 data/latest.json 用 network-first，其他檔案用 cache-first
self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);

  if (url.pathname.endsWith("/data/latest.json")) {
    e.respondWith(
      fetch(req).then(resp => {
        // 更新快取（背景）
        const copy = resp.clone();
        caches.open(CACHE).then(c => c.put(req, copy));
        return resp;
      }).catch(() => caches.match(req))
    );
    return;
  }

  e.respondWith(
    caches.match(req).then(resp => resp || fetch(req))
  );
});
