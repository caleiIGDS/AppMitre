// Búsqueda tolerante: el mismo criterio que texto.py::puntaje_busqueda del servidor
// (acentos y mayúsculas no importan, el substring siempre gana, y con 3+ letras se
// perdonan typos por similitud, umbral 0.68). Ver texto.py para cómo se midió el umbral.

export const UMBRAL_SIMILITUD = 0.68

export function norm(texto) {
  return String(texto || '').normalize('NFD').replace(/[̀-ͯ]/g, '')
    .toLowerCase().replace(/\s+/g, ' ').trim()
}

// Ratcliff/Obershelp, igual que difflib.SequenceMatcher.ratio.
function bloqueMasLargo(a, b, alo, ahi, blo, bhi) {
  let mejorI = alo
  let mejorJ = blo
  let mejor = 0
  let anterior = {}
  for (let i = alo; i < ahi; i++) {
    const actual = {}
    for (let j = blo; j < bhi; j++) {
      if (a[i] === b[j]) {
        const k = (anterior[j - 1] || 0) + 1
        actual[j] = k
        if (k > mejor) { mejorI = i - k + 1; mejorJ = j - k + 1; mejor = k }
      }
    }
    anterior = actual
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

export function similitud(a, b) {
  if (!a.length && !b.length) return 1
  return (2 * coincidencias(a, b, 0, a.length, 0, b.length)) / (a.length + b.length)
}

// Puntaje de `q` (ya normalizada) contra un texto ya normalizado: mayor = mejor,
// null = no coincide. El substring puntúa por encima de cualquier difuso.
export function puntaje(q, texto) {
  if (!q) return 1
  if (!texto) return null
  if (texto.includes(q)) return 1 + similitud(q, texto)
  if (q.length < 3) return null
  let mejor = similitud(q, texto)
  for (const palabra of texto.split(' ')) {
    if (palabra.length < q.length) continue // palabra corta: ruido (ver texto.py)
    mejor = Math.max(mejor, similitud(q, palabra))
  }
  return mejor >= UMBRAL_SIMILITUD ? mejor : null
}
