// OneFlow Service Worker — PWA 安装支持 + 静态资源缓存
// 策略：导航请求走网络（保证 SPA 路由与登录态实时），静态资源缓存优先。
const CACHE = 'oneflow-static-v1'

self.addEventListener('install', (event) => {
  self.skipWaiting()
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(['/icon.svg'])))
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))),
  )
  self.clients.claim()
})

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url)
  // API / SSE / TTS 一律走网络，不缓存
  if (url.pathname.startsWith('/api/')) return
  if (event.request.method !== 'GET') return
  // 同源静态资源：网络优先，成功后入缓存，离线时回退缓存
  if (url.origin !== self.location.origin) return
  event.respondWith(
    fetch(event.request)
      .then((resp) => {
        if (resp.ok) {
          const copy = resp.clone()
          caches.open(CACHE).then((cache) => cache.put(event.request, copy))
        }
        return resp
      })
      .catch(() => caches.match(event.request)),
  )
})
