<script setup>
// El aviso de sin conexión, arriba de todo. Lo usan las dos apps. Dice de cuándo son los
// datos a la vista: los de las consultas que alguna pantalla está mostrando, el más viejo.
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { sinConexion } from '../red'

const cache = useQueryClient().getQueryCache()
const desde = ref(0)

function calcular() {
  const fechas = cache.getAll()
    .filter((q) => q.queryKey[0] !== 'sesion' && q.getObserversCount() > 0 && q.state.data !== undefined)
    .map((q) => q.state.dataUpdatedAt)
  desde.value = fechas.length ? Math.min(...fechas) : 0
}

let soltar
onMounted(() => { calcular(); soltar = cache.subscribe(calcular) })
onUnmounted(() => soltar?.())

const cuando = computed(() => {
  if (!desde.value) return ''
  const f = new Date(desde.value)
  const hora = f.toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit', hour12: false })
  if (f.toDateString() === new Date().toDateString()) return `de hoy a las ${hora}`
  return `del ${f.toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit' })} a las ${hora}`
})
</script>

<template>
  <div v-if="sinConexion" class="a-sin-red" role="status">
    <strong>SIN CONEXIÓN</strong>
    <span>
      Se muestra lo guardado en este dispositivo<template v-if="cuando"> (datos {{ cuando }})</template>.
      Hasta que vuelva, no se puede guardar ni actualizar nada.
    </span>
  </div>
</template>
