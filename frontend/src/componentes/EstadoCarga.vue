<script setup>
// Lo que se muestra mientras una consulta no tiene datos todavía (primera vez en este
// dispositivo) o si falló sin nada guardado para mostrar.
defineProps({ consulta: { type: Object, required: true }, que: { type: String, default: 'los datos' } })
</script>

<template>
  <div v-if="consulta.isError.value && !consulta.data.value" class="g-empty" role="alert">
    <p>No se pudieron cargar {{ que }}: {{ consulta.error.value?.message }}</p>
    <button type="button" class="g-btn" @click="consulta.refetch()">REINTENTAR</button>
  </div>
  <div v-else-if="!consulta.data.value" class="a-cargando" aria-busy="true">
    <span class="a-cargando-barra" />
    <span>Cargando {{ que }}…</span>
  </div>
</template>
