<script setup>
// Registro de bajas: qué salió del inventario y por qué. Es
// un historial: una baja revertida sigue figurando, tachada.
import { computed } from 'vue'
import { useBajas, useMeta, useRevertirBajaUnidad } from '@/gestion/datos'
import { avisar, avisarError } from '@/avisos'
import EstadoCarga from '@/componentes/EstadoCarga.vue'

const props = defineProps({ inv: { type: String, required: true } })
const bajas = useBajas(() => props.inv)
const meta = useMeta(() => props.inv)
const revertir = useRevertirBajaUnidad(() => props.inv)
const vigentes = computed(() => (bajas.data.value || []).filter((f) => !f.revertida).length)

function deshacer(f) {
  revertir.mutate(f.id, {
    onSuccess: () => avisar(`Volvió la unidad #${f.numero} de "${f.recurso_nombre}".`),
    onError: (e) => avisarError(e, 'No se revirtió'),
  })
}
</script>

<template>
  <div class="g-panel-top">
    <div class="g-toolbar">
      <div style="display: flex; align-items: baseline; gap: 12px;">
        <h2>REGISTRO DE BAJAS</h2>
        <span class="g-fichas-count">{{ vigentes }} BAJAS</span>
      </div>
      <div class="g-toolbar-actions">
        <RouterLink class="g-btn-outline-dark" :to="{ name: 'recursos', params: { inv } }">‹ INVENTARIO</RouterLink>
      </div>
    </div>
    <p class="g-help">
      Los recursos no se borran: se dan de baja desde EDITAR, diciendo qué les pasó. Una baja
      de <strong>unidad #N</strong> es una unidad puntual que se sacó del inventario. Acá
      queda cada baja con su motivo y su fecha.
    </p>
  </div>

  <EstadoCarga :consulta="bajas" que="el registro" />

  <div v-if="bajas.data.value?.length" class="g-table-wrap">
    <table class="g-table">
      <thead><tr><th>RECURSO</th><th>MOTIVO</th><th>DETALLE</th><th>FECHA</th><th /></tr></thead>
      <tbody>
        <tr v-for="f in bajas.data.value" :key="f.id" :class="{ 'g-baja-revertida': f.revertida }">
          <td data-label="RECURSO">
            <RouterLink v-if="f.existe" class="g-item-link" :to="{ name: 'recurso', params: { inv, id: f.recurso_id } }">{{ f.recurso_nombre }}</RouterLink>
            <template v-else>{{ f.recurso_nombre }}</template>
            <span v-if="f.numero" class="g-recurso-sub">unidad #{{ f.numero }}</span>
            <span v-if="f.existe && f.nombre_actual !== f.recurso_nombre" class="g-recurso-sub">hoy: {{ f.nombre_actual }}</span>
            <span v-if="f.revertida" class="g-recurso-sub">baja revertida</span>
          </td>
          <td data-label="MOTIVO"><span class="g-badge">{{ f.motivo }}</span></td>
          <td data-label="DETALLE">{{ f.detalle }}</td>
          <td data-label="FECHA">{{ f.fecha }}</td>
          <td>
            <button
              v-if="f.numero && !f.revertida && f.existe && meta.data.value?.puede_escribir"
              type="button" class="g-btn-mini g-btn-outline-dark" :disabled="revertir.isPending.value" @click="deshacer(f)"
            >Revertir</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
  <div v-else-if="bajas.data.value" class="g-empty">
    <p>Todavía no se dio de baja ningún recurso.</p>
  </div>
</template>
