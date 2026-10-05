<script setup>
// IMPRIMIR VARIOS: elegir cursos sueltos, un año entero o todos, y pedir un solo PDF.
import { computed, ref } from 'vue'
import { useHorarios } from '../datos'
import { abrirPdf } from '../api'
import { cerrarVentana } from '../ventanas'

const datos = useHorarios()
const elegidos = ref(new Set())

const cursos = computed(() => (datos.data.value?.listas.curso || []).map((c) => c.valor))
const porAnio = computed(() => {
  const grupos = {}
  for (const v of cursos.value) (grupos[v.split('°')[0].trim()] ||= []).push(v)
  return grupos
})
const todos = computed(() => cursos.value.length > 0 && elegidos.value.size === cursos.value.length)
const anioCompleto = (anio) => porAnio.value[anio].every((c) => elegidos.value.has(c))

function cambiar(fn) {
  const s = new Set(elegidos.value)
  fn(s)
  elegidos.value = s
}
const alternarCurso = (v) => cambiar((s) => (s.has(v) ? s.delete(v) : s.add(v)))
const alternarAnio = (anio) => {
  const lleno = anioCompleto(anio)
  cambiar((s) => porAnio.value[anio].forEach((c) => (lleno ? s.delete(c) : s.add(c))))
}
const alternarTodos = () => cambiar((s) => (todos.value ? s.clear() : cursos.value.forEach((c) => s.add(c))))

function generar() {
  if (!elegidos.value.size) return
  abrirPdf('cursos/' + (todos.value ? 'todos' : encodeURIComponent([...elegidos.value].join(','))))
  cerrarVentana()
}
</script>

<template>
  <div class="print-cursos-selector">
    <button type="button" class="print-todos-btn" :class="{ selected: todos }" @click="alternarTodos">SELECCIONAR TODOS</button>
    <div class="print-cursos-filas">
      <div v-for="(lista, anio) in porAnio" :key="anio" class="print-cursos-fila">
        <button type="button" class="print-anio-btn" :class="{ selected: anioCompleto(anio) }" @click="alternarAnio(anio)">TODO {{ anio }}°</button>
        <div class="print-cursos-chips">
          <button
            v-for="c in lista" :key="c" type="button" class="print-curso-chip"
            :class="{ selected: elegidos.has(c) }" @click="alternarCurso(c)"
          >{{ c.replace('° ', '°') }}</button>
        </div>
      </div>
    </div>
    <div class="print-cursos-footer">
      <span class="print-contador">Seleccionados: {{ elegidos.size }}</span>
      <button type="button" class="print-generar-btn" :disabled="!elegidos.size" @click="generar">GENERAR PDF</button>
    </div>
  </div>
</template>
