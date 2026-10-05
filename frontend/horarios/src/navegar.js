// Ir al horario de algo (un curso, un profesor, un aula, un preceptor), desde el buscador o
// desde la ventana de una clase. Comparando, en vez de abrirlo se suma a la comparación.
import { useRoute, useRouter } from 'vue-router'
import { leerComparacion, escribirComparacion } from './router'
import { COMPARABLES } from './datos'
import { avisar } from '@/avisos'

export function useIrA() {
  const route = useRoute()
  const router = useRouter()

  return function irA(modo, valor) {
    if (!valor || valor === '-' || valor === '?') return
    const comparar = route.query.comparar
    if (comparar === undefined) {
      router.push({ name: modo, params: { valor } })
      return
    }
    if (!COMPARABLES.includes(modo)) {
      avisar('Los horarios de preceptores no se pueden agregar al modo comparación.', { tipo: 'alerta' })
      return
    }
    const items = leerComparacion(comparar)
    if (items.some((i) => i.modo === modo && i.valor === valor)) {
      avisar(`"${valor}" ya está en la comparación.`, { tipo: 'alerta' })
      return
    }
    router.push({ name: modo, query: { comparar: escribirComparacion([...items, { modo, valor }]) } })
  }
}
