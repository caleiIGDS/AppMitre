<script setup>
import { useRoute } from 'vue-router'
const route = useRoute()
</script>

<template>
  <div class="g-empty">
    <template v-if="route.query.motivo === 'permiso'">
      <p>Este acceso no tiene permiso para ver esta sección.</p>
      <p class="g-help">Si te hace falta, pedile a quien administra el sistema que te habilite.</p>
    </template>
    <p v-else>No existe esta pantalla.</p>
    <RouterLink class="g-btn" :to="{ name: 'inicio' }">IR AL INICIO</RouterLink>
  </div>
</template>
