<script setup>
import { computed } from 'vue'
import { useSesion } from '@/sesion'
import { AREAS } from '@/areas'

const { acceso, puede } = useSesion()
const areas = computed(() => AREAS.filter((a) => a.permiso === null || puede(a.permiso)))
</script>

<template>
  <div class="g-toolbar">
    <h2>HOLA, {{ (acceso?.nombre || '').toUpperCase() }}</h2>
  </div>
  <div class="g-cards">
    <div v-for="a in areas" :key="a.clave" class="g-card">
      <div class="g-card-head">
        <h3>{{ a.nombre.toUpperCase() }}</h3>
        <span v-if="!a.ruta" class="a-etiqueta" title="Todavía abre la versión de páginas clásicas">CLÁSICA</span>
      </div>
      <p class="g-card-desc">{{ a.descripcion }}</p>
      <div class="g-card-actions">
        <RouterLink v-if="a.ruta" class="g-btn" :to="a.ruta">ENTRAR</RouterLink>
        <a v-else class="g-btn-outline-dark" :href="a.href">ABRIR</a>
      </div>
    </div>
  </div>
</template>
