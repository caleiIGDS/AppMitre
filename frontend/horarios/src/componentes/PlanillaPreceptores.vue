<script setup>
// Todos los cursos con sus preceptores por turno; en negrita, el del turno del curso
// (renderizarPlanillaCursos).
defineProps({ filas: { type: Array, required: true } })
const ABREV = { MAÑANA: 'M', TARDE: 'T', VESPERTINO: 'V' }
const turno = (f) => (f.turno || '').toUpperCase()
</script>

<template>
  <div v-if="!filas.length" style="padding:20px;text-align:center;">No hay datos disponibles.</div>
  <table v-else style="width:100%;table-layout:auto;">
    <thead>
      <tr><th>CURSO Y DIVISIÓN</th><th>TURNO</th><th>MAÑANA</th><th>TARDE</th><th>VESPERTINO</th></tr>
    </thead>
    <tbody>
      <tr v-for="f in filas" :key="f.curso + f.division">
        <td>{{ f.curso }}° {{ f.division }}</td>
        <td>{{ ABREV[turno(f)] || f.turno || '' }}</td>
        <td><strong v-if="turno(f) === 'MAÑANA'">{{ f.manana }}</strong><template v-else>{{ f.manana }}</template></td>
        <td><strong v-if="turno(f) === 'TARDE'">{{ f.tarde }}</strong><template v-else>{{ f.tarde }}</template></td>
        <td><strong v-if="turno(f) === 'VESPERTINO'">{{ f.vespertino }}</strong><template v-else>{{ f.vespertino }}</template></td>
      </tr>
    </tbody>
  </table>
</template>
