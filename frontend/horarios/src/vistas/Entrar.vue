<script setup>
// La clave de horarios (la misma de /horarios/login). Entrar una vez deja la sesión abierta.
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useEntrar } from '../sesion'

const route = useRoute()
const router = useRouter()
const entrar = useEntrar()
const clave = ref('')
const error = ref('')
const campo = ref(null)
onMounted(() => campo.value?.focus())

function enviar() {
  error.value = ''
  entrar.mutate(clave.value, {
    onSuccess: () => {
      const volver = typeof route.query.volver === 'string' && route.query.volver.startsWith('/') ? route.query.volver : '/'
      router.replace(volver)
    },
    onError: (e) => {
      error.value = e.message
      clave.value = ''
      campo.value?.focus()
    },
  })
}
</script>

<template>
  <div class="hz-main">
    <form class="hz-card" @submit.prevent="enviar">
      <h2>ACCESO A HORARIOS</h2>
      <div v-if="error" class="hz-error" role="alert">{{ error }}</div>
      <div class="hz-field">
        <label for="campo-clave">CONTRASEÑA</label>
        <input id="campo-clave" ref="campo" v-model="clave" type="password" autocomplete="current-password" required>
      </div>
      <button type="submit" class="hz-btn" :disabled="entrar.isPending.value">{{ entrar.isPending.value ? 'ENTRANDO…' : 'ENTRAR' }}</button>
    </form>
  </div>
</template>
