<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '@/api'
import { useMeta } from '@/gestion/datos'
import { sinConexion } from '@/red'
import { cabecerasMovimientos, cerrarMovimientos, habilitarMovimientos, relojMovimientos, segundosMovimientos } from '@/gestion/movimientos'

const ruta = useRoute()
const inv = computed(() => ruta.meta.inventario && !ruta.meta.abierta ? String(ruta.params.inv || '') : '')
const meta = useMeta(inv)
const dialogo = ref(null)
const campo = ref(null)
const pin = ref('')
const error = ref('')
const ocupado = ref(false)
const disponible = computed(() => inv.value && meta.data.value?.pin_movimientos && !meta.data.value?.puede_escribir)
const segundos = computed(() => segundosMovimientos(inv.value))
let temporizador
let apertura = 0

function cerrar() {
  apertura++
  dialogo.value?.close()
  pin.value = ''
  error.value = ''
}

async function teclado(e) {
  if (!e.shiftKey || e.ctrlKey || e.altKey || e.metaKey || e.code !== 'KeyA' || e.repeat || e.isComposing ||
      !disponible.value || dialogo.value?.open || document.querySelector('dialog[open], [aria-modal="true"]') ||
      e.target.closest?.('input, textarea, select, [contenteditable]')) return
  e.preventDefault()
  cerrar()
  dialogo.value.showModal()
  await nextTick()
  campo.value?.focus()
}

async function confirmar() {
  if (ocupado.value || !/^[0-9]{4}$/.test(pin.value)) return
  const inventario = inv.value
  const version = apertura
  const inicio = performance.now()
  ocupado.value = true
  error.value = ''
  try {
    const datos = await api(`/gestion/${encodeURIComponent(inventario)}/movimientos/autorizar`, {
      metodo: 'POST', cuerpo: { pin: pin.value },
    })
    if (version !== apertura || inv.value !== inventario || !dialogo.value?.open) return
    habilitarMovimientos(inventario, datos.token, datos.segundos, inicio)
    cerrar()
  } catch (e) {
    if (version === apertura) {
      pin.value = ''
      error.value = e.message
    }
  } finally {
    ocupado.value = false
    await nextTick()
    if (version === apertura && error.value && dialogo.value?.open) campo.value?.focus()
  }
}

watch(inv, () => { cerrar(); cerrarMovimientos() })
watch(sinConexion, (sinRed) => { if (sinRed) cerrarMovimientos() })
function actualizarReloj() {
  relojMovimientos.value = performance.now()
  // Evitar conservar un token vencido incluso con la pestaña en segundo plano.
  if (inv.value && !Object.keys(cabecerasMovimientos(inv.value)).length) cerrarMovimientos()
}
function ocultar() {
  cerrar()
  cerrarMovimientos()
}
onMounted(() => {
  document.addEventListener('keydown', teclado)
  document.addEventListener('visibilitychange', actualizarReloj)
  window.addEventListener('pagehide', ocultar)
  temporizador = setInterval(actualizarReloj, 100)
})
onUnmounted(() => {
  clearInterval(temporizador)
  document.removeEventListener('keydown', teclado)
  document.removeEventListener('visibilitychange', actualizarReloj)
  window.removeEventListener('pagehide', ocultar)
  cerrarMovimientos()
})
</script>

<template>
  <div v-if="disponible && segundos > 0" class="a-movimientos-activos" role="status">
    <span>Sólo mover ubicaciones · {{ segundos }} s</span>
    <button type="button" class="g-btn-outline-dark g-btn-mini" @click="cerrarMovimientos">BLOQUEAR</button>
  </div>
  <dialog ref="dialogo" class="g-modal a-pin-movimientos" aria-labelledby="pin-movimientos-titulo" @cancel.prevent="cerrar" @close="pin = ''">
    <form class="g-modal-form" @submit.prevent="confirmar">
      <h3 id="pin-movimientos-titulo">MOVER UBICACIONES</h3>
      <p class="g-help">Ingresá el PIN de 4 dígitos. Habilita sólo movimientos durante 20 segundos.</p>
      <div class="g-field">
        <label for="pin-movimientos">PIN</label>
        <input id="pin-movimientos" ref="campo" v-model="pin" type="password" inputmode="numeric"
          pattern="[0-9]{4}" minlength="4" maxlength="4" autocomplete="off" required
          :disabled="ocupado" :aria-invalid="!!error" aria-describedby="pin-movimientos-error">
      </div>
      <p v-if="error" id="pin-movimientos-error" class="a-pin-error" role="alert">{{ error }}</p>
      <div class="g-modal-actions">
        <button type="submit" class="g-btn" :disabled="ocupado || !/^[0-9]{4}$/.test(pin)">{{ ocupado ? 'VERIFICANDO…' : 'HABILITAR 20 S' }}</button>
        <button type="button" class="g-btn-outline-dark" @click="cerrar">CANCELAR</button>
      </div>
    </form>
  </dialog>
</template>

<style scoped>
.a-movimientos-activos {
  position: fixed; bottom: 18px; left: 50%; transform: translateX(-50%); z-index: 100;
  display: flex; align-items: center; gap: 12px; max-width: calc(100vw - 24px); width: max-content;
  padding: 12px 16px; background: var(--g-bg); border: 2px solid var(--secondary);
  box-shadow: 0 4px 16px #0002; font-size: 12px;
}
.a-pin-movimientos { max-width: min(420px, calc(100vw - 24px)); }
.a-pin-movimientos input { font-size: 28px; letter-spacing: .3em; text-align: center; }
.a-pin-error { color: var(--alert); font-size: 12px; }
</style>
