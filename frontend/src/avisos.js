// Mensajes cortos abajo de la pantalla ("Guardado", "No se pudo guardar: …").
import { reactive } from 'vue'

export const avisos = reactive([])
let siguiente = 1

export function avisar(texto, { tipo = 'ok', duracion = 3500, accion = null } = {}) {
  const id = siguiente++
  avisos.push({ id, texto, tipo, accion })
  if (duracion) setTimeout(() => cerrarAviso(id), duracion)
  return id
}

export function avisarError(error, prefijo = 'No se pudo completar') {
  const detalle = error?.sinConexion
    ? 'no hay conexión con el servidor. Probá de nuevo cuando vuelva la red.'
    : (error?.message || 'error inesperado.')
  return avisar(`${prefijo}: ${detalle}`, { tipo: 'error', duracion: 7000 })
}

export function cerrarAviso(id) {
  const i = avisos.findIndex((a) => a.id === id)
  if (i !== -1) avisos.splice(i, 1)
}
