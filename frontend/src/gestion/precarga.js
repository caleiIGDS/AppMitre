// Baja de antemano las fotos de un inventario, para que una ficha nunca tenga que esperar
// la red: primero todas las miniaturas (lo que se ve al abrir una ficha) y después las
// imágenes enteras (el visor). Quien las guarda es el service worker (caché `mitre-fotos`,
// CacheFirst en vite.config.js): acá sólo se piden las que todavía no están.
//
// De a pocas y en segundo plano, para no competir con lo que la persona está haciendo. Una
// llamada nueva reemplaza la cola anterior (cambiar de inventario no deja dos corriendo),
// y lo que falle se reintenta la próxima vez que llegue la lista.

const CACHE = 'mitre-fotos'
const EN_PARALELO = 2

let ronda = 0
let persistenciaPedida = false

export function precargarFotos(recursos) {
  const sw = navigator.serviceWorker
  // Sin service worker (npm run dev, o la primera carga de todas) no habría dónde guardarlas.
  if (!sw?.controller || !('caches' in window) || navigator.connection?.saveData) return
  if (!persistenciaPedida) {
    persistenciaPedida = true
    // Que el navegador no desaloje las fotos cuando le falta espacio.
    navigator.storage?.persist?.().catch(() => {})
  }
  const fotos = (recursos || []).flatMap((r) => r.fotos || [])
  const urls = [...fotos.map((f) => f.mini).filter(Boolean), ...fotos.map((f) => f.url)]
  const esta = ++ronda
  const enCola = () => esta === ronda
  const arrancar = window.requestIdleCallback || ((fn) => setTimeout(fn, 1500))
  arrancar(() => bajar(urls, enCola))
}

async function bajar(urls, enCola) {
  let cache
  try {
    cache = await caches.open(CACHE)
  } catch {
    return
  }
  const faltan = []
  for (const url of urls) {
    if (!enCola()) return
    if (!(await cache.match(url))) faltan.push(url)
  }
  let i = 0
  let cortado = false
  const trabajador = async () => {
    while (!cortado && enCola() && i < faltan.length) {
      const url = faltan[i++]
      try {
        const resp = await fetch(url, { credentials: 'same-origin' })
        // Sin sesión (se salió del inventario) no tiene sentido seguir pidiendo.
        if (resp.status === 401 || resp.status === 403) cortado = true
        await resp.blob()
      } catch {
        // sin red o se cortó: queda para la próxima
      }
    }
  }
  await Promise.all(Array.from({ length: EN_PARALELO }, trabajador))
}
