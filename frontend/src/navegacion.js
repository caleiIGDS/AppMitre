// Volver como lo haría una app: si la pantalla a la que hay que volver es justo la
// anterior en el historial, se va "atrás" (y el navegador devuelve el scroll y los
// filtros tal como estaban). Si se llegó por un link directo, se reemplaza la pantalla
// actual por la de destino, para que el historial no acumule pasos de más.

import router from './router'

export function volverA(destino) {
  const resuelto = router.resolve(destino)
  const anterior = window.history.state?.back
  if (anterior && router.resolve(anterior).name === resuelto.name &&
      sameParams(router.resolve(anterior).params, resuelto.params)) {
    router.back()
  } else {
    router.replace(destino)
  }
}

function sameParams(a, b) {
  const claves = new Set([...Object.keys(a), ...Object.keys(b)])
  for (const k of claves) if (String(a[k]) !== String(b[k])) return false
  return true
}
