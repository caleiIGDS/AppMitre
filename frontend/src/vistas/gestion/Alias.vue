<script setup>
// Consulta de solo lectura (admin): qué alias le completó el asistente a cada recurso.
// No se editan desde ningún lado de la web: ver agent_docs/gestion-conocimiento.md.
import { useAlias } from '@/gestion/datos'
import EstadoCarga from '@/componentes/EstadoCarga.vue'

const alias = useAlias()
</script>

<template>
  <div class="g-toolbar">
    <h2>ALIAS DE RECURSOS <span v-if="alias.data.value" class="g-count">{{ alias.data.value.length }}</span></h2>
    <p class="g-help">Términos que el asistente completó para que la búsqueda encuentre un recurso
      aunque lo pidan con otro nombre. Solo lectura: se edita únicamente por chat.</p>
  </div>
  <EstadoCarga :consulta="alias" que="los alias" />
  <div v-if="alias.data.value?.length" class="g-table-wrap">
    <table class="g-table">
      <thead><tr><th>NOMBRE</th><th>ALIAS</th></tr></thead>
      <tbody>
        <tr v-for="f in alias.data.value" :key="f.id">
          <td data-label="NOMBRE">
            <RouterLink class="g-item-link" :to="{ name: 'recurso', params: { id: f.id } }">{{ f.nombre }}</RouterLink>
          </td>
          <td data-label="ALIAS">{{ f.alias }}</td>
        </tr>
      </tbody>
    </table>
  </div>
  <div v-else-if="alias.data.value" class="g-empty"><p>Todavía no hay recursos cargados.</p></div>
</template>
