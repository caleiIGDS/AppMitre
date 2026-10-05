<script setup>
// Los alias de los recursos: tira de tags editable por
// fila. Enter o coma agrega, × saca, borrar con el campo vacío saca el último. "Guardar"
// aparece sólo en la fila que cambió. Mismo formato CSV que escribe el asistente.
import { reactive, watch } from 'vue'
import { useAlias, useGuardarAlias } from '@/gestion/datos'
import { avisar, avisarError } from '@/avisos'
import EstadoCarga from '@/componentes/EstadoCarga.vue'

const props = defineProps({ inv: { type: String, required: true } })
const alias = useAlias(() => props.inv)
const guardarAlias = useGuardarAlias(() => props.inv)

const partir = (csv) => (csv || '').split(',').map((t) => t.trim()).filter(Boolean)
const borradores = reactive({}) // id → { tags: [], texto: '' }
watch(() => alias.data.value, (filas) => {
  for (const f of filas || []) {
    const b = borradores[f.id]
    if (!b || !b.tocado) borradores[f.id] = { tags: partir(f.alias), texto: '', tocado: false }
  }
}, { immediate: true })

const csv = (b) => b.tags.join(', ')
const cambiado = (f) => borradores[f.id] && csv(borradores[f.id]) !== partir(f.alias).join(', ')

function agregar(f) {
  const b = borradores[f.id]
  const t = b.texto.trim().replace(/,+$/, '').trim()
  if (t) { b.tags.push(t); b.tocado = true }
  b.texto = ''
}

function tecla(f, e) {
  const b = borradores[f.id]
  if (e.key === 'Enter' || e.key === ',') {
    e.preventDefault()
    agregar(f)
  } else if (e.key === 'Backspace' && !b.texto && b.tags.length) {
    b.tags.pop()
    b.tocado = true
  }
}

function quitar(f, i) {
  borradores[f.id].tags.splice(i, 1)
  borradores[f.id].tocado = true
}

async function guardar(f) {
  agregar(f)
  try {
    await guardarAlias.mutateAsync({ id: f.id, alias: csv(borradores[f.id]) })
    borradores[f.id].tocado = false
    avisar(`Alias de "${f.nombre}" guardados.`)
  } catch (e) {
    avisarError(e, 'No se guardaron los alias')
  }
}
</script>

<template>
  <div class="g-toolbar">
    <h2>ALIAS DE RECURSOS <span v-if="alias.data.value" class="g-count">{{ alias.data.value.length }}</span></h2>
    <p class="g-help">Términos alternativos para que la búsqueda encuentre un recurso aunque lo
      pidan con otro nombre. Los completa el asistente por chat, pero acá los podés agregar,
      corregir o sacar a mano.</p>
  </div>
  <EstadoCarga :consulta="alias" que="los alias" />
  <div v-if="alias.data.value?.length" class="g-table-wrap">
    <table class="g-table g-table-alias">
      <thead><tr><th>NOMBRE</th><th>ALIAS</th></tr></thead>
      <tbody>
        <tr v-for="f in alias.data.value" :key="f.id">
          <td data-label="NOMBRE">{{ f.nombre }}</td>
          <td data-label="ALIAS">
            <form v-if="borradores[f.id]" class="g-alias-form" @submit.prevent="guardar(f)">
              <div class="g-tags">
                <span v-for="(t, i) in borradores[f.id].tags" :key="i" class="g-tag">
                  <span class="g-tag-texto">{{ t }}</span>
                  <button type="button" class="g-tag-quitar" :aria-label="`Quitar «${t}»`" @click="quitar(f, i)">×</button>
                </span>
                <input
                  v-model="borradores[f.id].texto" type="text" class="g-tag-input" placeholder="+ agregar…"
                  :aria-label="`Agregar alias a ${f.nombre}`" @keydown="tecla(f, $event)" @blur="agregar(f)"
                >
              </div>
              <button v-if="cambiado(f)" type="submit" class="g-btn-mini g-tag-guardar" :disabled="guardarAlias.isPending.value">Guardar</button>
            </form>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
  <div v-else-if="alias.data.value" class="g-empty"><p>Todavía no hay recursos cargados.</p></div>
</template>
