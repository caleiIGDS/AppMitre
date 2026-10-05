<script setup>
// El botón ‹ que despliega las opciones de la pestaña (COMPARAR, GENERAR PDF, ...).
// Se cierra al tocar afuera o al elegir una opción.
import { ref, onMounted, onUnmounted } from 'vue'

const abierto = ref(false)
const caja = ref(null)
const fuera = (e) => { if (!caja.value?.contains(e.target)) abierto.value = false }
onMounted(() => document.addEventListener('pointerdown', fuera))
onUnmounted(() => document.removeEventListener('pointerdown', fuera))
const cerrar = () => { abierto.value = false }
</script>

<template>
  <div ref="caja" class="h-menu">
    <div class="slide-panel" :class="{ open: abierto }">
      <slot :cerrar="cerrar" />
    </div>
    <button
      type="button" class="btn-slide-trigger" :class="{ 'panel-open': abierto }"
      :aria-expanded="abierto" aria-label="Opciones" @click="abierto = !abierto"
    >‹</button>
  </div>
</template>
