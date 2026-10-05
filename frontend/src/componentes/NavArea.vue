<script setup>
// La fila de arriba de un inventario abierto. Sin pestañas (hay una sola entidad, y el
// escudo ya lleva al inicio): sólo lo que ponga la pantalla, como QUITAR FILTROS de
// Inventario.vue. Vacía no ocupa lugar (ver .a-nav-vacia en app.css).
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const mostrar = computed(() => route.meta.inventario && route.name !== 'inventario-entrar')
</script>

<template>
  <nav v-if="mostrar" class="g-nav a-nav-vacia" aria-label="Acciones">
    <span id="nav-acciones" class="a-nav-acciones" />
  </nav>
</template>
