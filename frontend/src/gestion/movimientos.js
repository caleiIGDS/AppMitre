import { ref } from 'vue'

// Sólo en memoria de esta pestaña. El PIN y la autorización nunca van a la caché.
const permiso = ref(null)
export const relojMovimientos = ref(performance.now())

export function cerrarMovimientos() {
  permiso.value = null
}

export function habilitarMovimientos(inv, token, segundos, inicio) {
  permiso.value = { inv, token, vence: inicio + segundos * 1000 }
  relojMovimientos.value = performance.now()
}

export function segundosMovimientos(inv) {
  return permiso.value?.inv === inv
    ? Math.max(0, Math.ceil((permiso.value.vence - relojMovimientos.value) / 1000)) : 0
}

export function cabecerasMovimientos(inv) {
  const p = permiso.value
  return p?.inv === inv && p.vence > performance.now()
    ? { 'X-Mitre-Movimientos': p.token } : {}
}
