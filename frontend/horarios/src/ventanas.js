// Lo que flota sobre la pantalla: la ventana de detalle (una clase, una superposición,
// imprimir varios cursos) y el cartelito al pasar el mouse por un bloque.
import { shallowReactive, toRaw } from 'vue'

export const ventana = shallowReactive({ tipo: null, clase: null, clases: [], seleccionada: null })

export function verClase(clase) {
  Object.assign(ventana, { tipo: 'clase', clase, clases: [], seleccionada: clase })
}

export function verSuperposicion(clases) {
  Object.assign(ventana, { tipo: 'superposicion', clase: null, clases, seleccionada: null })
}

export function verImprimirCursos() {
  Object.assign(ventana, { tipo: 'imprimir', clase: null, clases: [], seleccionada: null })
}

export function cerrarVentana() {
  Object.assign(ventana, { tipo: null, clase: null, clases: [], seleccionada: null })
}

export const cartel = shallowReactive({ visible: false, x: 0, y: 0, clase: null })

export function mostrarCartel(evento, clase) {
  // Sólo con mouse: en una pantalla táctil el toque abre la ventana de detalle.
  if (evento.pointerType && evento.pointerType !== 'mouse') return
  Object.assign(cartel, { visible: true, x: evento.clientX + 15, y: evento.clientY + 15, clase })
}

export function ocultarCartel() {
  cartel.visible = false
}

// El bloque cuya ventana está abierta se marca (`.selected`).
export function esSeleccionada(clase) {
  return !!ventana.seleccionada && toRaw(ventana.seleccionada) === toRaw(clase)
}
