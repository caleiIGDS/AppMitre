<script setup>
// La clave DE ESTE INVENTARIO (templates/gestion/login.html), no la de la escuela.
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useEntrarInventario } from '@/gestion/datos'

const props = defineProps({ inv: { type: String, required: true } })
const route = useRoute()
const router = useRouter()
const entrar = useEntrarInventario(() => props.inv)
const clave = ref('')
const error = ref('')
const sinClave = ref(false)

function destino() {
  const volver = route.query.volver
  const propio = `/gestion/${props.inv}/`
  return typeof volver === 'string' && volver.startsWith(propio) ? volver : { name: 'recursos', params: { inv: props.inv } }
}

async function enviar() {
  error.value = ''
  try {
    await entrar.mutateAsync(clave.value)
    router.replace(destino())
  } catch (e) {
    if (e.status === 409) sinClave.value = true
    error.value = e.sinConexion ? 'No hay conexión con el servidor.'
      : e.status === 404 ? 'Ese inventario no existe.' : e.message
    clave.value = ''
  }
}
</script>

<template>
  <div class="g-toolbar">
    <h2>{{ inv.replace(/-/g, ' ').toUpperCase() }}</h2>
  </div>
  <div v-if="error" class="g-error" role="alert">{{ error }}</div>
  <form v-if="!sinClave" class="g-form" @submit.prevent="enviar">
    <div class="g-field">
      <label for="campo-clave">CLAVE DE ESTE INVENTARIO</label>
      <input id="campo-clave" v-model="clave" type="password" required autofocus autocomplete="current-password">
      <span class="g-help">Es la clave del encargado de este inventario y no sirve para
        ningún otro. Si te habilitaron por link, no necesitás clave: entrá con el link que te
        mandaron.</span>
    </div>
    <div class="g-form-actions">
      <button type="submit" class="g-btn" :disabled="entrar.isPending.value">
        {{ entrar.isPending.value ? 'ENTRANDO…' : 'ENTRAR' }}
      </button>
    </div>
  </form>
  <div class="g-form-actions">
    <RouterLink class="g-btn-outline-dark" :to="{ name: 'inventarios' }">‹ TODOS LOS INVENTARIOS</RouterLink>
  </div>
</template>
