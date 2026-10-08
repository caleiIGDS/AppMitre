<script setup>
// CURSOS · PROFESORES · AULAS · PRECEPTORES · MATERIAS · TIEMPO REAL. Cada pestaña recuerda
// lo último que se buscó en ella (MATERIAS, sus filtros); en modo comparación, la comparación viaja con la pestaña.
import { computed, reactive, watch } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const ultima = reactive({})
watch(() => route.fullPath, () => {
  if (route.name === 'materia') ultima.materia = { ...route.query }
  else if (route.name && route.name !== 'envivo') ultima[route.name] = route.params.valor || ''
}, { immediate: true })

const comparar = computed(() => route.query.comparar)
const destino = (name) => {
  if (name === 'envivo') return { name }
  if (name === 'materia') return { name, query: ultima.materia || {} }
  const query = comparar.value !== undefined ? { comparar: comparar.value } : {}
  // Comparando, la pestaña abre vacía: lo que se busque se suma a la comparación.
  const valor = comparar.value !== undefined ? '' : (ultima[name] || '')
  return { name, params: valor ? { valor } : {}, query }
}

const PESTANAS = [
  ['curso', 'CURSOS'],
  ['profesor', 'PROFESORES'],
  ['aula', 'AULAS'],
  ['horario_preceptor', 'PRECEPTORES'],
  ['materia', 'MATERIAS'],
  ['envivo', 'TIEMPO REAL'],
]
</script>

<template>
  <nav class="tech-tags">
    <RouterLink
      v-for="[name, texto] in PESTANAS" :key="name" :to="destino(name)" replace
      class="tech-tag" :class="{ active: route.name === name }"
    >{{ texto }}</RouterLink>
  </nav>
</template>
