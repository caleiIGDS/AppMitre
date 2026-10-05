import { createRouter, createWebHistory } from 'vue-router'
import { sesionActual, tienePermiso } from './sesion'

// Cada pantalla declara qué permiso necesita (meta.permiso). El servidor lo vuelve a
// controlar en cada pedido; esto sólo evita mostrar una pantalla que contestaría 403.
const routes = [
  { path: '/', name: 'inicio', component: () => import('./vistas/Inicio.vue') },
  { path: '/entrar', name: 'entrar', component: () => import('./vistas/Entrar.vue'), meta: { publica: true } },

  { path: '/gestion', redirect: { name: 'inventario' } },
  {
    path: '/gestion/inventario', name: 'inventario',
    component: () => import('./vistas/gestion/Inventario.vue'),
    meta: { area: 'gestion', permiso: 'gestion.leer', titulo: 'Inventario' },
  },
  {
    path: '/gestion/inventario/nuevo', name: 'recurso-nuevo',
    component: () => import('./vistas/gestion/RecursoFormulario.vue'),
    meta: { area: 'gestion', permiso: 'gestion.editar', titulo: 'Nuevo recurso' },
  },
  {
    path: '/gestion/inventario/:id(\\d+)', name: 'recurso',
    component: () => import('./vistas/gestion/Recurso.vue'), props: true,
    meta: { area: 'gestion', permiso: 'gestion.leer', titulo: 'Recurso' },
  },
  {
    path: '/gestion/inventario/:id(\\d+)/editar', name: 'recurso-editar',
    component: () => import('./vistas/gestion/RecursoFormulario.vue'), props: true,
    meta: { area: 'gestion', permiso: 'gestion.editar', titulo: 'Editar recurso' },
  },
  {
    path: '/gestion/alias', name: 'alias',
    component: () => import('./vistas/gestion/Alias.vue'),
    meta: { area: 'gestion', permiso: 'gestion.alias', titulo: 'Alias' },
  },

  { path: '/:resto(.*)*', name: 'no-encontrado', component: () => import('./vistas/NoEncontrado.vue'), meta: { publica: true } },
]

const router = createRouter({
  history: createWebHistory('/app/'),
  routes,
  scrollBehavior(to, from, guardada) {
    // Atrás/adelante: el scroll exacto donde estaba. Los datos salen de la memoria, así
    // que la pantalla ya está dibujada cuando se restaura.
    if (guardada) return guardada
    // Cambiar un filtro (sólo la query) no es otra pantalla: no saltar arriba.
    if (to.name === from.name && to.path === from.path) return false
    return { top: 0 }
  },
})

router.beforeEach(async (to) => {
  if (to.meta.publica) return true
  const acceso = await sesionActual()
  if (!acceso) return { name: 'entrar', query: { volver: to.fullPath } }
  if (to.meta.permiso && !tienePermiso(acceso, to.meta.permiso)) {
    return { name: 'no-encontrado', params: { resto: to.path.slice(1).split('/') }, query: { motivo: 'permiso' } }
  }
  return true
})

router.afterEach((to) => {
  document.title = to.meta.titulo ? `${to.meta.titulo} — Emilio Mitre` : 'Emilio Mitre'
})

export default router
