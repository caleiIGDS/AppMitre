<script setup>
// El header de la app, con las mismas clases que el de las páginas del servidor
// (salidas, agente, accesos): gestion.css los pinta igual. El panel ☰ es el de static/mobile-nav.js:
// lleva el menú de áreas a cualquier ancho y, en celular, las acciones del header (acá hay
// una copia en cada lugar y app.css muestra una sola, en vez de mover nodos).
import { computed, ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useSesion, useSalir } from '@/sesion'
import { areasVisibles } from '@/areas'
import { useMeta } from '@/gestion/datos'
import AccionesInventario from './AccionesInventario.vue'

const route = useRoute()
const router = useRouter()
const { acceso, areas, escuela, puede } = useSesion()
const salir = useSalir()

const inv = computed(() => (route.meta.inventario ? route.params.inv : null))
const meta = useMeta(inv)
const inventario = computed(() => (inv.value ? meta.data.value?.inventario : null))
const enInventario = computed(() => !!(inv.value && meta.data.value && route.name !== 'inventario-entrar'))
const menu = computed(() => areasVisibles(areas.value, puede))
const hayMenu = computed(() => !!acceso.value || enInventario.value)

const abierto = ref(false)
const botonMenu = ref(null)
const botonCerrar = ref(null)

function abrir() {
  abierto.value = true
  nextTick(() => botonCerrar.value?.focus())
}
function cerrar(devolverFoco = false) {
  abierto.value = false
  if (devolverFoco) botonMenu.value?.focus()
}
watch(abierto, (v) => document.body.classList.toggle('g-sidebar-abierto', v))
watch(() => route.fullPath, () => cerrar())

function teclado(e) { if (e.key === 'Escape' && abierto.value) cerrar(true) }
onMounted(() => document.addEventListener('keydown', teclado))
onUnmounted(() => document.removeEventListener('keydown', teclado))

async function cerrarSesion() {
  cerrar()
  await salir.mutateAsync().catch(() => {})
  router.replace({ name: 'inicio' })
}
</script>

<template>
  <header class="g-header">
    <div class="g-container g-header-flex">
      <RouterLink :to="{ name: 'inicio' }" class="marca g-brand a-marca-link">
        <img src="@static/images/escudo.svg" alt="Escudo" class="marca-escudo">
        <div class="g-titles">
          <h1>{{ escuela.nombre }} <span class="g-serial">{{ escuela.version }}</span></h1>
          <p>{{ inventario ? `Inventario · ${inventario.nombre}` : 'Sistema de Gestión de Conocimiento' }}</p>
        </div>
      </RouterLink>
      <div v-if="enInventario" class="g-header-actions a-solo-escritorio">
        <AccionesInventario :inv="inv" :meta="meta.data.value" />
      </div>
      <button
        v-if="hayMenu" ref="botonMenu" type="button" class="g-menu-btn g-visible"
        aria-label="Abrir menú" aria-controls="a-menu" :aria-expanded="abierto"
        @click="abierto ? cerrar(true) : abrir()"
      >
        <span class="g-menu-bars" aria-hidden="true" />
      </button>
    </div>
  </header>

  <template v-if="hayMenu">
    <div class="g-sidebar-overlay" @click="cerrar(true)" />
    <aside id="a-menu" class="g-sidebar" aria-label="Menú" :inert="!abierto || undefined">
      <div class="g-sidebar-head">
        <span class="g-sidebar-title">MENÚ</span>
        <button ref="botonCerrar" type="button" class="g-sidebar-close" aria-label="Cerrar menú" @click="cerrar(true)">✕</button>
      </div>
      <div class="g-sidebar-body" @click="$event.target.closest('a, button') && cerrar()">
        <div v-if="enInventario" class="g-header-actions a-solo-movil">
          <AccionesInventario :inv="inv" :meta="meta.data.value" />
        </div>
        <nav class="g-areas" aria-label="Áreas">
          <RouterLink :to="{ name: 'inicio' }">⌂ MENÚ PRINCIPAL</RouterLink>
          <template v-for="a in menu" :key="a.clave">
            <RouterLink v-if="a.ruta" :to="a.ruta">{{ a.nombre.toUpperCase() }}</RouterLink>
            <a v-else :href="a.href">{{ a.nombre.toUpperCase() }}</a>
          </template>
          <a v-if="acceso" href="/salir" class="g-areas-salir" @click.prevent="cerrarSesion">SALIR</a>
        </nav>
      </div>
    </aside>
  </template>
</template>
