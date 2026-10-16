// ¿Se llega al servidor? Lo comparten las dos apps: el api.js de cada una pide por acá y
// componentes/EstadoRed.vue muestra el aviso.
//
// `navigator.onLine` sólo sabe si el dispositivo tiene red, no si el servidor contesta: con
// un wifi sin internet o el servidor caído dice "en línea" igual. Por eso también cuenta
// cómo le fue al último pedido.

import { ref, computed } from 'vue'

const ESPERA_MAXIMA = 15 * 1000

const hayRed = ref(navigator.onLine)
const servidorContesta = ref(true)

window.addEventListener('online', () => { hayRed.value = true })
window.addEventListener('offline', () => { hayRed.value = false })

export const sinConexion = computed(() => !hayRed.value || !servidorContesta.value)

// fetch, o null si no se llegó al servidor.
//   - Una lectura que en 15 s no empezó a contestar cuenta como sin conexión (red colgada):
//     la app sigue con lo guardado y el aviso, en vez de quedarse esperando. Las escrituras
//     no tienen tope: subir una foto puede tardar.
//   - 502–504 y los 52x de Cloudflare los contesta el intermediario, no la app: para el
//     aviso, el servidor no está (la respuesta se devuelve igual, con su error).
export async function pedir(url, opciones) {
  const corte = opciones.method === 'GET' ? new AbortController() : null
  const reloj = corte && setTimeout(() => corte.abort(), ESPERA_MAXIMA)
  try {
    const resp = await fetch(url, corte ? { ...opciones, signal: corte.signal } : opciones)
    servidorContesta.value = resp.status < 502
    return resp
  } catch {
    servidorContesta.value = false
    return null
  } finally {
    clearTimeout(reloj)
  }
}
