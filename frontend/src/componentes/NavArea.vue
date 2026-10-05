<script setup>
// Las pestañas de un inventario abierto (hoy una sola entidad: el inventario de recursos).
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const mostrar = computed(() => route.meta.inventario && route.name !== 'inventario-entrar')
const activa = computed(() => ['recursos', 'recurso', 'recurso-nuevo', 'recurso-editar'].includes(route.name))
</script>

<template>
  <nav v-if="mostrar" class="g-nav" aria-label="Secciones">
    <RouterLink :to="{ name: 'recursos', params: { inv: route.params.inv } }" class="g-nav-tag" :class="{ active: activa }">INVENTARIO</RouterLink>
    <!-- Lo que la pantalla abierta quiera poner en esta fila (Inventario.vue: QUITAR FILTROS). -->
    <span id="nav-acciones" class="a-nav-acciones" />
  </nav>
</template>
