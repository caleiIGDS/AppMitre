<script setup>
// El cartelito al pasar el mouse por un bloque del calendario (#calendar-tooltip).
import { cartel } from '../ventanas'
import { nombreProfesor } from '../calendario'
</script>

<template>
  <div
    v-if="cartel.visible && cartel.clase" class="calendar-tooltip"
    :style="{ display: 'block', left: cartel.x + 'px', top: cartel.y + 'px' }"
  >
    <div class="tooltip-header">{{ cartel.clase.materia }}</div>
    <div class="tooltip-item"><b>Curso:</b> {{ cartel.clase.curso ? `${cartel.clase.curso}° ${cartel.clase.division}` : '-' }}</div>
    <div class="tooltip-item"><b>Prof:</b> {{ nombreProfesor(cartel.clase) }}</div>
    <div class="tooltip-item"><b>Aula:</b> {{ cartel.clase.aula || '-' }}</div>
    <div class="tooltip-item"><b>Horario:</b> {{ cartel.clase.hora_inicio }} - {{ cartel.clase.hora_fin }}</div>
  </div>
</template>
