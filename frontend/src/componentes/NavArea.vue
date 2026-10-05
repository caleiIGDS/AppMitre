<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useSesion } from '@/sesion'
import { areaPorClave } from '@/areas'

const route = useRoute()
const { puede } = useSesion()

const pestanas = computed(() => {
  const area = areaPorClave(route.meta.area)
  if (!area?.pestanas) return []
  return area.pestanas.filter((p) => !p.permiso || puede(p.permiso))
})
</script>

<template>
  <nav v-if="pestanas.length" class="g-nav" aria-label="Secciones">
    <RouterLink
      v-for="p in pestanas" :key="p.nombre" :to="p.ruta"
      class="g-nav-tag" :class="{ active: p.activa.includes(route.name) }"
    >{{ p.nombre }}</RouterLink>
  </nav>
</template>
