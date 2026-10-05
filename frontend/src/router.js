import { createRouter, createWebHistory } from 'vue-router'
import { pedirMeta } from './gestion/datos'

// Todo cuelga de /gestion/: el inicio (las áreas) es /gestion/, la lista de inventarios
// /gestion/inventarios y cada inventario /gestion/<inv>/… Los nombres fijos de este nivel
// (entrar, inventarios, assets) no los puede tomar un inventario: gestion.SLUGS_RESERVADOS.
//
// Las pantallas de un inventario declaran qué necesitan (meta.requiere: una bandera del
// /meta del inventario, ej. 'puede_escribir'). El servidor lo vuelve a controlar en cada
// pedido; esto sólo evita mostrar una pantalla que contestaría 403.
const routes = [
  { path: '/', name: 'inicio', component: () => import('./vistas/Inicio.vue') },
  { path: '/entrar', name: 'entrar', component: () => import('./vistas/Entrar.vue'), meta: { titulo: 'Entrar' } },

  { path: '/inventarios', name: 'inventarios', component: () => import('./vistas/gestion/Inventarios.vue'), meta: { titulo: 'Inventarios' } },
  { path: '/:inv', redirect: (to) => ({ name: 'recursos', params: to.params }) },
  {
    path: '/:inv/entrar', name: 'inventario-entrar', props: true,
    component: () => import('./vistas/gestion/InventarioEntrar.vue'),
    meta: { inventario: true, abierta: true, titulo: 'Entrar al inventario' },
  },
  {
    path: '/:inv/recursos', name: 'recursos', props: true,
    component: () => import('./vistas/gestion/Inventario.vue'),
    meta: { inventario: true, titulo: 'Inventario' },
  },
  {
    path: '/:inv/recursos/nuevo', name: 'recurso-nuevo', props: true,
    component: () => import('./vistas/gestion/RecursoFormulario.vue'),
    meta: { inventario: true, requiere: 'puede_escribir', titulo: 'Crear recurso' },
  },
  {
    path: '/:inv/recursos/:id(\\d+)', name: 'recurso', props: true,
    component: () => import('./vistas/gestion/Recurso.vue'),
    meta: { inventario: true, titulo: 'Recurso' },
  },
  {
    path: '/:inv/recursos/:id(\\d+)/editar', name: 'recurso-editar', props: true,
    component: () => import('./vistas/gestion/RecursoFormulario.vue'),
    meta: { inventario: true, requiere: 'puede_escribir', titulo: 'Editar recurso' },
  },
  {
    path: '/:inv/alias', name: 'alias', props: true,
    component: () => import('./vistas/gestion/Alias.vue'),
    meta: { inventario: true, requiere: 'puede_alias', titulo: 'Alias' },
  },
  {
    path: '/:inv/accesos', name: 'accesos', props: true,
    component: () => import('./vistas/gestion/Accesos.vue'),
    meta: { inventario: true, requiere: 'puede_accesos', titulo: 'Quién entra' },
  },
  {
    path: '/:inv/bajas', name: 'bajas', props: true,
    component: () => import('./vistas/gestion/Bajas.vue'),
    meta: { inventario: true, requiere: 'puede_auditoria', titulo: 'Registro de bajas' },
  },

  { path: '/:resto(.*)*', name: 'no-encontrado', component: () => import('./vistas/NoEncontrado.vue') },
]

const router = createRouter({
  history: createWebHistory('/gestion/'),
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

const noEncontrado = (to, motivo) => ({
  name: 'no-encontrado', params: { resto: to.path.slice(1).split('/') }, query: motivo ? { motivo } : {},
})

router.beforeEach(async (to) => {
  if (!to.meta.inventario || to.meta.abierta) return true
  // ¿Este acceso entra a este inventario? Lo contesta su /meta (de la memoria si ya se
  // pidió, así la app abre sin red).
  try {
    const meta = await pedirMeta(to.params.inv)
    if (to.meta.requiere && !meta[to.meta.requiere]) return noEncontrado(to, 'permiso')
    return true
  } catch (error) {
    // Sin acceso a ESTE inventario (no haber entrado, o ser el admin general, cuyo comodín
    // no llega adentro): la puerta es la clave del inventario, que se suma a lo que haya.
    if (error.status === 401 || error.status === 403) {
      return { name: 'inventario-entrar', params: { inv: to.params.inv }, query: { volver: to.fullPath } }
    }
    if (error.status === 404) return noEncontrado(to)
    return true // sin red y sin nada guardado: la pantalla muestra el error y "reintentar"
  }
})

router.afterEach((to) => {
  document.title = to.meta.titulo ? `${to.meta.titulo} — Emilio Mitre` : 'Emilio Mitre'
})

export default router
