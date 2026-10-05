<script setup>
// El horario de un preceptor: por turno, qué curso cubre cada día (renderizarTablaPreceptor).
import { computed } from 'vue'

const props = defineProps({
  filas: { type: Array, required: true },
  dias: { type: Array, required: true },
})

const DIAS = computed(() => props.dias.map((d) => d.normalize('NFD').replace(/[̀-ͯ]/g, '').toUpperCase()))
const turnos = computed(() => ['MAÑANA', 'TARDE', 'VESPERTINO'].map((turno) => {
  const filas = props.filas.filter((f) => (f.turno ? f.turno.toUpperCase() : 'MAÑANA') === turno)
  const porCurso = new Map()
  for (const f of filas) {
    const clave = `${f.preceptor}|${f.curso}|${f.division}|${f.estado}`
    if (!porCurso.has(clave)) porCurso.set(clave, { ...f, division: f.division || '', estado: f.estado || '-', dias: [] })
    porCurso.get(clave).dias.push(f.dia.toUpperCase())
  }
  return { turno, cursos: [...porCurso.values()] }
}).filter((t) => t.cursos.length))
</script>

<template>
  <div v-if="!filas.length" style="padding:20px; text-align:center; color:#70757a;">No hay horarios cargados para este preceptor.</div>
  <template v-for="t in turnos" :key="t.turno">
    <h3 style="margin-top: 30px; margin-bottom: 15px; color: var(--primary); border-bottom: 2px solid var(--secondary); padding-bottom: 5px;">TURNO {{ t.turno }}</h3>
    <table style="table-layout: fixed; margin-bottom: 30px; width: 100%;">
      <thead>
        <tr>
          <th style="width: 20%;">PRECEPTOR</th>
          <th style="width: 15%;">ESTADO</th>
          <th v-for="d in DIAS" :key="d">{{ d }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="c in t.cursos" :key="c.preceptor + c.curso + c.division + c.estado">
          <td style="padding: 10px; text-align: center;">{{ c.preceptor }}</td>
          <td style="padding: 10px; text-align: center;">{{ c.estado }}</td>
          <td v-for="d in DIAS" :key="d" style="padding: 10px; text-align: center; vertical-align: middle;">
            <div v-if="c.dias.includes(d)" class="preceptor-curso-item" style="margin: 0 auto;">{{ c.curso }}° {{ c.division }}</div>
            <span v-else style="opacity:0.3; font-style:italic;">-</span>
          </td>
        </tr>
      </tbody>
    </table>
  </template>
</template>
