<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useEntrar, sesionActual } from '@/sesion'

const route = useRoute()
const router = useRouter()
const entrar = useEntrar()
const clave = ref('')
const error = ref('')

function destino() {
  const volver = route.query.volver
  // Sólo rutas de la propia app: nada de redirigir a otro sitio.
  return typeof volver === 'string' && volver.startsWith('/') && !volver.startsWith('//') ? volver : '/'
}

onMounted(async () => {
  if (await sesionActual()) router.replace(destino())
})

async function enviar() {
  error.value = ''
  try {
    await entrar.mutateAsync(clave.value)
    router.replace(destino())
  } catch (e) {
    error.value = e.sinConexion ? 'No hay conexión con el servidor.' : e.message
    clave.value = ''
  }
}
</script>

<template>
  <div class="g-toolbar">
    <h2>ACCESO RESTRINGIDO</h2>
  </div>
  <div v-if="error" class="g-error" role="alert">{{ error }}</div>
  <form class="g-form" @submit.prevent="enviar">
    <div class="g-field">
      <label for="campo-clave">CONTRASEÑA DE ADMINISTRACIÓN</label>
      <input id="campo-clave" v-model="clave" type="password" required autofocus autocomplete="current-password">
      <span class="g-help">Si te habilitaron el acceso por link, no necesitás contraseña: abrí el
        link que te mandaron en este dispositivo y después volvé a la app.</span>
    </div>
    <div class="g-form-actions">
      <button type="submit" class="g-btn" :disabled="entrar.isPending.value">
        {{ entrar.isPending.value ? 'ENTRANDO…' : 'ENTRAR' }}
      </button>
    </div>
  </form>
</template>
