<script setup>
import { computed, ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useSesion, useSalir } from '@/sesion'
import { AREAS, areaPorClave } from '@/areas'

const route = useRoute()
const router = useRouter()
const { acceso, escuela, puede } = useSesion()
const salir = useSalir()

const area = computed(() => areaPorClave(route.meta.area))
const areasVisibles = computed(() =>
  AREAS.filter((a) => a.permiso === null || puede(a.permiso)))

// Panel lateral (☰): mismo markup y clases que static/mobile-nav.js, así gestion.css lo
// pinta igual que en las páginas clásicas.
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
  router.replace({ name: 'entrar' })
}
</script>

<template>
  <header class="g-header">
    <div class="g-container g-header-flex">
      <RouterLink :to="{ name: 'inicio' }" class="marca g-brand" style="text-decoration: none; color: inherit;">
        <img src="@static/images/escudo.svg" alt="Escudo" class="marca-escudo">
        <div class="g-titles">
          <h1>{{ escuela.nombre }} <span class="g-serial">{{ escuela.version }}</span></h1>
          <p>{{ area ? area.nombre : 'Sistema de Gestión de Conocimiento' }}</p>
        </div>
      </RouterLink>
      <!-- Con sesión, en celular estas acciones viven en el panel ☰ (ver app.css). -->
      <div class="g-header-actions" :class="{ 'a-solo-escritorio': acceso }">
        <a class="g-btn-outline" href="/">‹ SISTEMA DE HORARIOS</a>
        <a v-if="puede('agente.leer')" class="g-btn-outline" href="/agente/">🤖 ASISTENTE</a>
      </div>
      <button
        v-if="acceso" ref="botonMenu" type="button" class="g-menu-btn g-visible"
        aria-label="Abrir menú" aria-controls="a-menu" :aria-expanded="abierto"
        @click="abierto ? cerrar(true) : abrir()"
      >
        <span class="g-menu-bars" aria-hidden="true" />
      </button>
    </div>
  </header>

  <template v-if="acceso">
    <div class="g-sidebar-overlay" @click="cerrar(true)" />
    <aside id="a-menu" class="g-sidebar" aria-label="Menú" :inert="!abierto || undefined">
      <div class="g-sidebar-head">
        <span class="g-sidebar-title">MENÚ</span>
        <button ref="botonCerrar" type="button" class="g-sidebar-close" aria-label="Cerrar menú" @click="cerrar(true)">✕</button>
      </div>
      <div class="g-sidebar-body">
        <div class="g-header-actions a-solo-movil">
          <a class="g-btn-outline" href="/">‹ SISTEMA DE HORARIOS</a>
          <a v-if="puede('agente.leer')" class="g-btn-outline" href="/agente/">🤖 ASISTENTE</a>
        </div>
        <nav class="g-areas" aria-label="Áreas">
          <template v-for="a in areasVisibles" :key="a.clave">
            <RouterLink v-if="a.ruta" :to="a.ruta">{{ a.nombre.toUpperCase() }}</RouterLink>
            <a v-else :href="a.href">{{ a.nombre.toUpperCase() }}</a>
          </template>
          <a href="#" class="g-areas-salir" @click.prevent="cerrarSesion">SALIR · {{ acceso.nombre }}</a>
        </nav>
      </div>
    </aside>
  </template>
</template>
