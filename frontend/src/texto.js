// Búsqueda tolerante: el mismo criterio que texto.py::puntaje_busqueda del servidor
// (acentos y mayúsculas no importan, el substring siempre gana, y con 3+ letras se
// perdonan typos por similitud, umbral 0.68). Ver texto.py para cómo se midió el umbral.

export const UMBRAL_SIMILITUD = 0.68

export function norm(texto) {
  return String(texto || '').normalize('NFD').replace(/[̀-ͯ]/g, '')
    .toLowerCase().replace(/\s+/g, ' ').trim()
}

// Ratcliff/Obershelp, igual que difflib.SequenceMatcher.ratio. Corre por cada ficha en cada
// tecla del buscador en vivo: va con códigos de carácter y dos filas de Int32Array
// reusadas (con objetos como diccionario era ~10 veces más lento).
let filaA = new Int32Array(64)
let filaB = new Int32Array(64)

function bloqueMasLargo(a, b, alo, ahi, blo, bhi) {
  let mejorI = alo
  let mejorJ = blo
  let mejor = 0
  // anterior[j + 1] = largo del bloque que termina en a[i-1], b[j]; anterior[blo] = 0.
  let anterior = filaA
  let actual = filaB
  anterior.fill(0, blo, bhi + 1)
  actual[blo] = 0
  for (let i = alo; i < ahi; i++) {
    const ca = a[i]
    for (let j = blo; j < bhi; j++) {
      if (ca === b[j]) {
        const k = anterior[j] + 1
        actual[j + 1] = k
        if (k > mejor) { mejorI = i - k + 1; mejorJ = j - k + 1; mejor = k }
      } else {
        actual[j + 1] = 0
      }
    }
    const t = anterior; anterior = actual; actual = t
  }
  return [mejorI, mejorJ, mejor]
}

function coincidencias(a, b, alo, ahi, blo, bhi) {
  const [i, j, k] = bloqueMasLargo(a, b, alo, ahi, blo, bhi)
  if (k === 0) return 0
  let total = k
  if (alo < i && blo < j) total += coincidencias(a, b, alo, i, blo, j)
  if (i + k < ahi && j + k < bhi) total += coincidencias(a, b, i + k, ahi, j + k, bhi)
  return total
}

function codigos(s) {
  const c = new Int32Array(s.length)
  for (let i = 0; i < s.length; i++) c[i] = s.charCodeAt(i)
  return c
}

export function similitud(a, b) {
  if (!a.length && !b.length) return 1
  return similitudCodigos(codigos(a), codigos(b))
}

function similitudCodigos(a, b) {
  if (!a.length && !b.length) return 1
  if (filaA.length <= b.length) {
    filaA = new Int32Array(b.length * 2 + 1)
    filaB = new Int32Array(b.length * 2 + 1)
  }
  return (2 * coincidencias(a, b, 0, a.length, 0, b.length)) / (a.length + b.length)
}

// Lo máximo que puede dar `similitud` con esos largos (todo el más corto coincide). Si ni
// eso llega al umbral, no hace falta calcularla: el resultado es el mismo, null.
function alcanza(largoQ, largoTexto) {
  return (2 * Math.min(largoQ, largoTexto)) / (largoQ + largoTexto) >= UMBRAL_SIMILITUD
}

// El buscador en vivo compara la misma consulta contra los mismos textos tecla tras tecla:
// los códigos de cada texto y de cada una de sus palabras se calculan una vez. Con tope,
// por si la lista cambia mucho en una sesión larga.
const enCache = new Map()
function partes(texto) {
  let p = enCache.get(texto)
  if (!p) {
    if (enCache.size > 20000) enCache.clear()
    p = { todo: codigos(texto), palabras: texto.split(' ').map(codigos) }
    enCache.set(texto, p)
  }
  return p
}
let ultimaQ = null
let codigosQ = null

// Puntaje de `q` (ya normalizada) contra un texto ya normalizado: mayor = mejor,
// null = no coincide. El substring puntúa por encima de cualquier difuso.
export function puntaje(q, texto) {
  if (!q) return 1
  if (!texto) return null
  if (q !== ultimaQ) { ultimaQ = q; codigosQ = codigos(q) }
  if (texto.includes(q)) return 1 + similitudCodigos(codigosQ, partes(texto).todo)
  if (q.length < 3) return null
  const { todo, palabras } = partes(texto)
  let mejor = alcanza(q.length, texto.length) ? similitudCodigos(codigosQ, todo) : 0
  for (const palabra of palabras) {
    if (palabra.length < q.length) continue // palabra corta: ruido (ver texto.py)
    if (alcanza(q.length, palabra.length)) mejor = Math.max(mejor, similitudCodigos(codigosQ, palabra))
  }
  return mejor >= UMBRAL_SIMILITUD ? mejor : null
}

// Lo mismo que `puntaje(q, texto) !== null`, para cuando no importa el orden: el substring
// no necesita calcular la similitud.
export function coincide(q, texto) {
  if (!q) return true
  if (!texto) return false
  return texto.includes(q) || puntaje(q, texto) !== null
}
