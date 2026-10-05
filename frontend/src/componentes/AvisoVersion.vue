<script setup>
// Cuando hay una versión nueva de la app publicada, el service worker la baja en segundo
// plano y acá se ofrece activarla. No se activa sola: recargar en medio de una edición
// perdería lo que se estaba escribiendo.
import { useRegisterSW } from 'virtual:pwa-register/vue'

const { needRefresh, updateServiceWorker } = useRegisterSW({
  onRegisteredSW(_url, registro) {
    // Además del chequeo al abrir, buscar versión nueva cada hora con la app abierta.
    if (registro) setInterval(() => registro.update(), 60 * 60 * 1000)
  },
})
</script>

<template>
  <div v-if="needRefresh" class="a-version" role="alert">
    <span>Hay una versión nueva de la app.</span>
    <button type="button" class="g-btn" @click="updateServiceWorker(true)">ACTUALIZAR</button>
    <button type="button" class="g-btn-outline-dark" @click="needRefresh = false">DESPUÉS</button>
  </div>
</template>
