<script setup>
// DAR DE BAJA / REVERTIR BAJA dentro de EDITAR. Un recurso no
// se borra nunca: sale del inventario dándolo de baja, y la baja exige decir qué le pasó.
import { ref } from 'vue'
import { useBaja, useRevertirBaja } from '@/gestion/datos'
import { avisar, avisarError } from '@/avisos'

const props = defineProps({
  inv: { type: String, required: true },
  recurso: { type: Object, required: true },
  singular: { type: String, default: 'Recurso' },
  estadoBaja: { type: String, required: true },
  motivos: { type: Array, required: true },
})
const emit = defineEmits(['hecho'])

const baja = useBaja(() => props.inv)
const revertir = useRevertirBaja(() => props.inv)
const dialogo = ref(null)
const motivo = ref(props.motivos[0] || '')
const detalle = ref('')

async function confirmar() {
  try {
    await baja.mutateAsync({ id: props.recurso.id, motivo: motivo.value, detalle: detalle.value })
    dialogo.value?.close()
    avisar('Recurso dado de baja.')
    emit('hecho')
  } catch (e) {
    avisarError(e, 'No se dio de baja')
  }
}

async function deshacer() {
  if (!confirm('¿Volver a poner este recurso en el inventario? La baja queda marcada como revertida en el registro.')) return
  try {
    await revertir.mutateAsync({ id: props.recurso.id })
    avisar('El recurso volvió al inventario.')
    emit('hecho')
  } catch (e) {
    avisarError(e, 'No se revirtió la baja')
  }
}
</script>

<template>
  <div v-if="recurso.estado === estadoBaja" class="g-form-peligro">
    <div>
      <strong>{{ singular.toUpperCase() }} DADO DE BAJA</strong>
      <span class="g-help">
        Está fuera del inventario y no aparece en el listado. Queda anotado en el registro de
        bajas junto con el motivo.
      </span>
    </div>
    <button type="button" class="g-btn-outline-dark" :disabled="revertir.isPending.value" @click="deshacer">REVERTIR BAJA</button>
  </div>

  <template v-else>
    <div class="g-form-peligro">
      <div>
        <strong>DAR DE BAJA {{ singular.toUpperCase() }}</strong>
        <span class="g-help">
          El recurso no se borra: sale del inventario y queda en el registro de bajas con lo
          que le pasó. Se puede revertir.
        </span>
      </div>
      <button type="button" class="g-btn-danger" @click="dialogo.showModal()">DAR DE BAJA</button>
    </div>

    <dialog ref="dialogo" class="g-modal">
      <form class="g-modal-form" @submit.prevent="confirmar">
        <h3>DAR DE BAJA: {{ recurso.nombre }}</h3>
        <p class="g-help">Contá qué le pasó. Queda en el registro de bajas con la fecha de hoy.</p>
        <div class="g-field">
          <label for="baja-motivo">QUÉ LE PASÓ *</label>
          <select id="baja-motivo" v-model="motivo" required>
            <option v-for="op in motivos" :key="op" :value="op">{{ op }}</option>
          </select>
        </div>
        <div class="g-field">
          <label for="baja-detalle">DETALLE</label>
          <textarea id="baja-detalle" v-model="detalle" rows="3" placeholder="Ej: se quemó el regulador en la práctica del 3° B" />
          <span class="g-help">Opcional, pero es lo que hace útil al registro dentro de un año.</span>
        </div>
        <div class="g-modal-actions">
          <button type="submit" class="g-btn-danger" :disabled="baja.isPending.value">{{ baja.isPending.value ? 'DANDO DE BAJA…' : 'CONFIRMAR BAJA' }}</button>
          <button type="button" class="g-btn-outline-dark" @click="dialogo.close()">CANCELAR</button>
        </div>
      </form>
    </dialog>
  </template>
</template>
