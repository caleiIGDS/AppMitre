<script setup>
// Versión nueva de la app: se ofrece activarla, no se activa sola (igual que la de Gestión).
import { useRegisterSW } from 'virtual:pwa-register/vue'

const { needRefresh, updateServiceWorker } = useRegisterSW({
  onRegisteredSW(_url, registro) {
    if (registro) setInterval(() => registro.update(), 60 * 60 * 1000)
  },
})
</script>

<template>
  <div v-if="needRefresh" class="a-version" role="alert">
    <span>Hay una versión nueva de la app.</span>
    <button type="button" class="h-btn" @click="updateServiceWorker(true)">ACTUALIZAR</button>
    <button type="button" class="h-btn h-btn-claro" @click="needRefresh = false">DESPUÉS</button>
  </div>
</template>
