<script setup>
// Fotos de una ficha: miniaturas, visor a pantalla completa (flechas, Esc) y, con
// permiso, subir y borrar. Las imágenes se piden por URL: el dispositivo las guarda y no
// las vuelve a bajar (ver crud.py::api_foto y el service worker).
import { ref, computed, watch, nextTick, onUnmounted } from 'vue'

const props = defineProps({
  fotos: { type: Array, required: true },
  puedeEditar: { type: Boolean, default: false },
  subiendo: { type: Boolean, default: false },
})
const emit = defineEmits(['subir', 'borrar'])

const entrada = ref(null)
const abierta = ref(-1)
const botonCerrar = ref(null)
let foco = null

const actual = computed(() => props.fotos[abierta.value] || null)

function abrir(i, evento) {
  foco = evento?.currentTarget || null
  abierta.value = i
  document.body.classList.add('g-sin-scroll')
  nextTick(() => botonCerrar.value?.focus())
}
function cerrar() {
  abierta.value = -1
  document.body.classList.remove('g-sin-scroll')
  foco?.focus()
}
function mover(paso) {
  const n = props.fotos.length
  abierta.value = (abierta.value + paso + n) % n
}
function teclado(e) {
  if (abierta.value < 0) return
  if (e.key === 'Escape') cerrar()
  else if (e.key === 'ArrowLeft') mover(-1)
  else if (e.key === 'ArrowRight') mover(1)
}
watch(abierta, (i) => {
  if (i >= 0) document.addEventListener('keydown', teclado)
  else document.removeEventListener('keydown', teclado)
})
// Si la foto abierta desaparece (se borró acá o en otro dispositivo), cerrar el visor.
watch(() => props.fotos.length, (n) => {
  if (abierta.value >= n) n ? (abierta.value = n - 1) : cerrar()
})
onUnmounted(() => {
  document.removeEventListener('keydown', teclado)
  document.body.classList.remove('g-sin-scroll')
})

function elegido(e) {
  const archivo = e.target.files?.[0]
  e.target.value = ''
  if (archivo) emit('subir', archivo)
}

function borrar() {
  if (!actual.value) return
  if (!confirm('¿Eliminar esta foto? Esta acción no se puede deshacer.')) return
  emit('borrar', actual.value)
}
</script>

<template>
  <div class="g-foto-section">
    <div v-if="fotos.length" class="g-galeria">
      <div class="g-galeria-grid">
        <button
          v-for="(f, i) in fotos" :key="f.url" type="button" class="g-foto-thumb"
          :aria-label="`Ver foto ${i + 1} de ${fotos.length}`" @click="abrir(i, $event)"
        >
          <img :src="f.url" :alt="`Foto ${i + 1}`" class="g-foto" loading="lazy" decoding="async">
        </button>
      </div>
    </div>
    <div v-if="puedeEditar" class="g-foto-toolbar">
      <input ref="entrada" type="file" accept="image/*" hidden @change="elegido">
      <button type="button" class="g-foto-btn" :title="subiendo ? 'Subiendo…' : 'Agregar foto'" :disabled="subiendo" @click="entrada.click()">
        {{ subiendo ? '⏳' : '📷' }}
      </button>
    </div>
  </div>

  <Teleport to="body">
    <div
      v-if="actual" class="g-lightbox" role="dialog" aria-modal="true" aria-label="Foto ampliada"
      @click.self="cerrar"
    >
      <div class="g-lightbox-barra">
        <span class="g-lightbox-contador">{{ abierta + 1 }} / {{ fotos.length }}</span>
        <span class="g-lightbox-acciones">
          <button v-if="puedeEditar" type="button" class="g-lightbox-btn g-lightbox-btn-danger" title="Eliminar foto" @click="borrar">🗑 ELIMINAR</button>
          <button ref="botonCerrar" type="button" class="g-lightbox-btn" title="Cerrar (Esc)" @click="cerrar">✕</button>
        </span>
      </div>
      <button v-if="fotos.length > 1" type="button" class="g-lightbox-nav g-lightbox-prev" aria-label="Foto anterior" @click="mover(-1)">‹</button>
      <img class="g-lightbox-img" :src="actual.url" alt="Foto ampliada">
      <button v-if="fotos.length > 1" type="button" class="g-lightbox-nav g-lightbox-next" aria-label="Foto siguiente" @click="mover(1)">›</button>
    </div>
  </Teleport>
</template>
