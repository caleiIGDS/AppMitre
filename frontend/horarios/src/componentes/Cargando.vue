<script setup>
// Mientras llega el horario por primera vez en este dispositivo, o si no se pudo bajar.
import { avisarError } from '@/avisos'
import { sinConexion } from '@/red'

const props = defineProps({ consulta: { type: Object, required: true } })
function reintentar() {
  props.consulta.refetch().then((r) => { if (r.error) avisarError(r.error, 'No se pudo bajar el horario') })
}
</script>

<template>
  <div v-if="sinConexion || (consulta.error.value && consulta.error.value.status !== 401)" class="h-estado">
    <p>{{ sinConexion || consulta.error.value?.sinConexion
      ? 'No hay conexión y este dispositivo todavía no tiene el horario guardado.'
      : 'No se pudo bajar el horario: ' + consulta.error.value.message }}</p>
    <button type="button" class="tech-btn-update" @click="reintentar">REINTENTAR</button>
  </div>
  <div v-else class="h-estado">
    <span class="a-cargando-barra" />
    <p>Bajando el horario…</p>
  </div>
</template>
