<script setup>
// Un campo de formulario a partir de la config declarativa de la entidad (los mismos
// `campos` de gestion.py que usa la versión clásica).
defineProps({
  campo: { type: Object, required: true },
  error: { type: String, default: '' },
})
const valor = defineModel({ type: String, default: '' })
</script>

<template>
  <div class="g-field" :class="{ 'a-field-error': error }">
    <label :for="'campo-' + campo.nombre">{{ campo.label.toUpperCase() }}<template v-if="campo.requerido"> *</template></label>
    <textarea
      v-if="campo.tipo === 'textarea'" :id="'campo-' + campo.nombre" v-model="valor" rows="4"
      :aria-invalid="!!error" :aria-describedby="error ? 'error-' + campo.nombre : undefined"
    />
    <select
      v-else-if="campo.tipo === 'select'" :id="'campo-' + campo.nombre" v-model="valor"
      :aria-invalid="!!error"
    >
      <option v-for="op in campo.opciones" :key="op" :value="op">{{ op || '(sin definir)' }}</option>
    </select>
    <template v-else-if="campo.tipo === 'text_datalist'">
      <input
        :id="'campo-' + campo.nombre" v-model="valor" type="text" :list="'datalist-' + campo.nombre"
        :required="campo.requerido" :aria-invalid="!!error"
      >
      <datalist :id="'datalist-' + campo.nombre">
        <option v-for="op in campo.opciones" :key="op" :value="op" />
      </datalist>
    </template>
    <div v-else class="a-campo-con-accion">
      <input
        :id="'campo-' + campo.nombre" v-model="valor"
        :type="campo.tipo === 'number' ? 'text' : campo.tipo"
        :inputmode="campo.tipo === 'number' ? 'decimal' : undefined"
        :required="campo.requerido" :aria-invalid="!!error"
        :aria-describedby="error ? 'error-' + campo.nombre : undefined"
      >
      <slot name="accion" />
    </div>
    <span v-if="error" :id="'error-' + campo.nombre" class="a-error-campo" role="alert">{{ error }}</span>
    <span v-else-if="campo.ayuda" class="g-help">{{ campo.ayuda }}</span>
  </div>
</template>
