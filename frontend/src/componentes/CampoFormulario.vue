<script setup>
// Un campo del formulario a partir de la config declarativa de la entidad (los mismos
// `campos` de gestion.py), con las clases de formulario de gestion.css.
import { computed } from 'vue'

const props = defineProps({
  campo: { type: Object, required: true },
  error: { type: String, default: '' },
  hoy: { type: String, default: '' }, // la fecha de hoy ya formateada por el servidor
})
const valor = defineModel({ type: String, default: '' })
const id = computed(() => `campo-${props.campo.nombre}`)
// Un valor guardado que ya no figura entre las opciones (el "Dado de baja", que pone sólo
// la baja): se muestra fijo y se conserva. Un <select> sin él mostraría la primera opción
// y GUARDAR lo pisaría en silencio.
const fijo = computed(() => props.campo.tipo === 'select' && valor.value && !props.campo.opciones.includes(valor.value))
</script>

<template>
  <div class="g-field" :class="{ 'g-campo-ancho': campo.tipo === 'textarea', 'a-field-error': error }">
    <label :for="id">{{ campo.label.toUpperCase() }}<template v-if="campo.requerido"> *</template></label>
    <textarea
      v-if="campo.tipo === 'textarea'" :id="id" v-model="valor" rows="4"
      :aria-invalid="!!error" :aria-describedby="error ? `error-${campo.nombre}` : undefined"
    />
    <p v-else-if="fijo" :id="id" class="g-campo-fijo">{{ valor }}</p>
    <select v-else-if="campo.tipo === 'select'" :id="id" v-model="valor" :aria-invalid="!!error">
      <option v-for="op in campo.opciones" :key="op" :value="op">{{ op }}</option>
    </select>
    <template v-else-if="campo.tipo === 'text_datalist'">
      <input :id="id" v-model="valor" type="text" :list="`datalist-${campo.nombre}`" :required="campo.requerido" :aria-invalid="!!error">
      <datalist :id="`datalist-${campo.nombre}`">
        <option v-for="op in campo.opciones" :key="op" :value="op" />
      </datalist>
    </template>
    <div v-else-if="campo.boton_hoy" class="g-field-hoy">
      <input :id="id" v-model="valor" :type="campo.tipo" :required="campo.requerido" :aria-invalid="!!error">
      <button type="button" class="g-btn-outline-dark g-btn-mini" @click="valor = hoy">HOY</button>
    </div>
    <input
      v-else :id="id" v-model="valor"
      :type="campo.tipo === 'number' ? 'text' : campo.tipo"
      :inputmode="campo.tipo === 'number' ? 'numeric' : undefined"
      :required="campo.requerido" :aria-invalid="!!error"
      :aria-describedby="error ? `error-${campo.nombre}` : undefined"
    >
    <span v-if="error" :id="`error-${campo.nombre}`" class="a-error-campo" role="alert">{{ error }}</span>
    <span v-else-if="campo.ayuda" class="g-help">{{ campo.ayuda }}</span>
  </div>
</template>
