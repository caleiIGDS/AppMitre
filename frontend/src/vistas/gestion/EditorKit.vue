<script setup>
// SUB-RECURSOS (KIT) dentro de EDITAR: cada renglón se edita
// y se guarda por su cuenta; el cambio se ve al instante y vuelve atrás si el servidor lo
// rechaza.
import { reactive, ref, watch } from 'vue'
import { useAgregarKitItem, useEditarKitItem, useEliminarKitItem } from '@/gestion/datos'
import { avisar, avisarError } from '@/avisos'

const props = defineProps({
  inv: { type: String, required: true },
  recurso: { type: Object, required: true },
})

const agregar = useAgregarKitItem(() => props.inv)
const editar = useEditarKitItem(() => props.inv)
const eliminar = useEliminarKitItem(() => props.inv)

// Borradores por ítem: lo que se está escribiendo, separado de lo guardado. Uno que nadie
// tocó sigue al dato guardado (por ejemplo, si lo cambió otro dispositivo).
const borradores = reactive({})
watch(() => props.recurso.kit, (items) => {
  for (const item of items) {
    const b = borradores[item.id]
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
  <section class="g-form-kit">
    <h3>SUB-RECURSOS (KIT)</h3>
    <p class="g-help">
      Lo que viene adentro de este recurso. Se guarda por separado del formulario de
      arriba: cada Agregar, Guardar o × se aplica al toque.
    </p>

    <div v-if="recurso.kit.length" class="g-table-wrap">
      <table class="g-table">
        <thead><tr><th>TÍTULO</th><th>CANT.</th><th>RECURSO ASIGNADO</th><th /></tr></thead>
        <tbody>
          <tr v-for="item in recurso.kit" :key="item.id">
            <td colspan="3">
              <form v-if="borradores[item.id]" class="g-inline-form" @submit.prevent="guardar(item)">
                <input v-model="borradores[item.id].titulo" type="text" placeholder="Título" required aria-label="Título" @input="borradores[item.id].tocado = true">
                <input v-model="borradores[item.id].cantidad" type="text" placeholder="Cantidad" style="width:6em" aria-label="Cantidad" @input="borradores[item.id].tocado = true">
                <input v-model="borradores[item.id].recurso_asignado" type="text" placeholder="Recurso asignado" aria-label="Recurso asignado" @input="borradores[item.id].tocado = true">
                <button type="submit" class="g-btn g-btn-mini" title="Guardar" :disabled="!cambiado(item)">Guardar</button>
              </form>
            </td>
            <td>
              <button type="button" class="g-btn-mini g-btn-danger" title="Quitar" @click="quitar(item)">×</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <form class="g-inline-form" @submit.prevent="sumar">
      <input v-model="nuevo.titulo" type="text" placeholder="Título" required aria-label="Título del sub-recurso nuevo">
      <input v-model="nuevo.cantidad" type="text" placeholder="Cantidad" style="width:6em" aria-label="Cantidad">
      <input v-model="nuevo.recurso_asignado" type="text" placeholder="Recurso asignado" aria-label="Recurso asignado">
      <button type="submit" class="g-btn g-btn-mini" :disabled="agregar.isPending.value">{{ agregar.isPending.value ? 'Agregando…' : 'Agregar' }}</button>
    </form>
  </section>
</template>
