<script setup>
// La clave de ADMINISTRACIÓN (GESTION_CLAVE), o la de Salidas educativas (SALIDAS_CLAVE),
// que abre sólo esa área: el servidor prueba las dos (accesos.app_sesion_entrar). Los internos no
// pasan por acá: entran por su link de invitación; los encargados, con la clave de su
// inventario (InventarioEntrar.vue).
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useEntrar } from '@/sesion'

const route = useRoute()
const router = useRouter()
const entrar = useEntrar()
const clave = ref('')
const error = ref('')

function destino() {
  const volver = route.query.volver
  // Sólo rutas de la propia app: nada de redirigir a otro sitio.
  return typeof volver === 'string' && volver.startsWith('/') && !volver.startsWith('//') ? volver : { name: 'inicio' }
}

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
      <label for="campo-clave">CONTRASEÑA</label>
      <input id="campo-clave" v-model="clave" type="password" required autofocus autocomplete="current-password">
      <span class="g-help">La de administración, o la de Salidas educativas. Si te habilitaron
        el acceso por link, no necesitás contraseña: entrá con el link que te mandaron.</span>
    </div>
    <div class="g-form-actions">
      <button type="submit" class="g-btn" :disabled="entrar.isPending.value">
        {{ entrar.isPending.value ? 'ENTRANDO…' : 'ENTRAR' }}
      </button>
    </div>
  </form>
</template>
