<script setup>
// Sub-recursos de un kit. Cada fila se edita en el lugar; "Guardar" sólo se habilita si
// la fila cambió, y el cambio se ve al instante (si el servidor lo rechaza, vuelve atrás).
import { reactive, ref, watch } from 'vue'
import { useAgregarKitItem, useEditarKitItem, useEliminarKitItem } from '@/gestion/datos'
import { avisar, avisarError } from '@/avisos'

const props = defineProps({
  recurso: { type: Object, required: true },
  puedeEditar: { type: Boolean, default: false },
})

const agregar = useAgregarKitItem()
const editar = useEditarKitItem()
const eliminar = useEliminarKitItem()

// Borradores por ítem: lo que se está escribiendo, separado de lo guardado.
const borradores = reactive({})
watch(() => props.recurso.kit, (items) => {
  for (const item of items) {
    const b = borradores[item.id]
    // Un borrador que nadie tocó sigue al dato guardado (p. ej. si lo cambió otro).
    if (!b || !b.tocado) borradores[item.id] = { ...item, tocado: false }
  }
}, { immediate: true, deep: true })

const nuevo = ref({ titulo: '', cantidad: '', recurso_asignado: '' })

function cambiado(item) {
  const b = borradores[item.id]
  return b && (b.titulo !== item.titulo || b.cantidad !== item.cantidad || b.recurso_asignado !== item.recurso_asignado)
}

function guardar(item) {
  const b = borradores[item.id]
  if (!b.titulo.trim()) return avisar('El título no puede quedar vacío.', { tipo: 'error' })
  const datos = { id: item.id, titulo: b.titulo.trim(), cantidad: b.cantidad.trim(), recurso_asignado: b.recurso_asignado.trim() }
  editar.mutate({ id: props.recurso.id, item: datos }, {
    onSuccess: () => { borradores[item.id].tocado = false },
    onError: (e) => avisarError(e, 'No se guardó el sub-recurso'),
  })
}

function quitar(item) {
  if (!confirm(`¿Quitar "${item.titulo}" del kit?`)) return
  eliminar.mutate({ id: props.recurso.id, itemId: item.id }, {
    onError: (e) => avisarError(e, 'No se quitó el sub-recurso'),
  })
}

async function sumar() {
  try {
    await agregar.mutateAsync({ id: props.recurso.id, item: { ...nuevo.value } })
    nuevo.value = { titulo: '', cantidad: '', recurso_asignado: '' }
  } catch (e) {
    avisarError(e, 'No se agregó el sub-recurso')
  }
}
</script>

<template>
  <div v-if="recurso.kit.length" class="g-table-wrap">
    <table class="g-table a-tabla-kit">
      <thead>
        <tr><th>TÍTULO</th><th>CANT.</th><th>RECURSO ASIGNADO</th><th v-if="puedeEditar" /></tr>
      </thead>
      <tbody>
        <tr v-for="item in recurso.kit" :key="item.id">
          <template v-if="puedeEditar && borradores[item.id]">
            <td data-label="TÍTULO"><input v-model="borradores[item.id].titulo" type="text" aria-label="Título" required @input="borradores[item.id].tocado = true"></td>
            <td data-label="CANT."><input v-model="borradores[item.id].cantidad" type="text" aria-label="Cantidad" style="width: 6em" @input="borradores[item.id].tocado = true"></td>
            <td data-label="RECURSO ASIGNADO"><input v-model="borradores[item.id].recurso_asignado" type="text" aria-label="Recurso asignado" @input="borradores[item.id].tocado = true"></td>
            <td class="g-td-actions">
              <button type="button" class="g-btn-mini" :disabled="!cambiado(item)" @click="guardar(item)">Guardar</button>
              <button type="button" class="g-btn-mini g-btn-danger" title="Quitar" @click="quitar(item)">×</button>
            </td>
          </template>
          <template v-else>
            <td data-label="TÍTULO">{{ item.titulo }}</td>
            <td data-label="CANT.">{{ item.cantidad }}</td>
            <td data-label="RECURSO ASIGNADO">{{ item.recurso_asignado }}</td>
          </template>
        </tr>
      </tbody>
    </table>
  </div>
  <p v-else class="g-help">Todavía no hay sub-recursos cargados.</p>

  <form v-if="puedeEditar" class="g-inline-form a-form-kit" @submit.prevent="sumar">
    <input v-model="nuevo.titulo" type="text" placeholder="Título" required aria-label="Título del sub-recurso nuevo">
    <input v-model="nuevo.cantidad" type="text" placeholder="Cantidad" style="width: 6em" aria-label="Cantidad">
    <input v-model="nuevo.recurso_asignado" type="text" placeholder="Recurso asignado" aria-label="Recurso asignado">
    <button type="submit" class="g-btn-mini" :disabled="agregar.isPending.value">{{ agregar.isPending.value ? 'Agregando…' : 'Agregar' }}</button>
  </form>
</template>
