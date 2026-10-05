// Todo cuelga de /horarios/. Cada pantalla y cada búsqueda es una dirección propia: atrás
// y adelante andan como en cualquier app, y un horario se puede compartir con el link.
//
//   /tiempo-real                       el tablero en vivo (la pantalla de inicio)
//   /cursos/1° A, /profesores/NOMBRE, /aulas/12, /preceptores/NOMBRE
//   /aulas?planilla=1&dia=Lunes&piso=Piso 1        la planilla general por piso
//   ...?comparar=curso:1° A,profesor:NOMBRE        el modo comparación, en cualquier pestaña
import { createRouter, createWebHistory } from 'vue-router'
import { hayAcceso } from './sesion'

const busqueda = (modo, segmento) => ({
  path: `/${segmento}/:valor?`,
  name: modo,
  component: () => import('./vistas/Busqueda.vue'),
  props: (r) => ({ modo, valor: r.params.valor || '' }),
})

const router = createRouter({
  history: createWebHistory('/horarios/'),
  routes: [
    { path: '/', redirect: { name: 'envivo' } },
    { path: '/entrar', name: 'entrar', component: () => import('./vistas/Entrar.vue'), meta: { publica: true } },
    { path: '/tiempo-real', name: 'envivo', component: () => import('./vistas/TiempoReal.vue') },
    busqueda('curso', 'cursos'),
    busqueda('profesor', 'profesores'),
    busqueda('aula', 'aulas'),
    busqueda('horario_preceptor', 'preceptores'),
    { path: '/:resto(.*)*', redirect: { name: 'envivo' } },
  ],
  scrollBehavior(to, from, guardada) {
    if (guardada) return guardada
    // Cambiar de búsqueda dentro de la misma pestaña no salta arriba de todo.
    if (to.name === from.name) return false
    return { top: 0 }
  },
})

router.beforeEach(async (to) => {
  if (to.meta.publica) return true
  if (await hayAcceso()) return true
  return { name: 'entrar', query: { volver: to.fullPath } }
})

export default router

// Lista de comparación <-> texto de la URL. Mismo formato que el link que arma el asistente
// en el chat (agente/enlaces.py): "curso:1%C2%B0%20A,profesor:MACIEL%20MARTIN".
export function leerComparacion(texto) {
  return String(texto || '').split(',').map((parte) => {
    const corte = parte.indexOf(':')
    if (corte < 1) return null
    return { modo: parte.slice(0, corte), valor: decodeURIComponent(parte.slice(corte + 1)) }
  }).filter((i) => i && ['curso', 'profesor', 'aula'].includes(i.modo) && i.valor)
}

export function escribirComparacion(items) {
  return items.map((i) => `${i.modo}:${encodeURIComponent(i.valor)}`).join(',')
}

