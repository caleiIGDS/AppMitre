<script setup>
import { ref, onMounted, onUnmounted } from 'vue'

const enLinea = ref(navigator.onLine)
const actualizar = () => { enLinea.value = navigator.onLine }
onMounted(() => {
  window.addEventListener('online', actualizar)
  window.addEventListener('offline', actualizar)
})
onUnmounted(() => {
  window.removeEventListener('online', actualizar)
  window.removeEventListener('offline', actualizar)
})
</script>

<template>
  <div v-if="!enLinea" class="a-sin-red" role="status">
    Sin conexión: se muestra lo último que se descargó. Los cambios no se pueden guardar hasta que vuelva la red.
  </div>
</template>
