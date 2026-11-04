<script setup>
// Fotos de una ficha: miniaturas, visor a pantalla
// completa (flechas, Esc), y con permiso subir, borrar y ROTAR. Las imágenes se piden por
// URL: el dispositivo las guarda y no las vuelve a bajar. La grilla ofrece las dos
// (`mini` y `url`, por srcset) y el navegador elige según lo que mide en pantalla: en PC la
// columna supera la miniatura y va la entera. El visor usa siempre `url`. Las dos las
// precarga gestion/precarga.js.
//
// Subir: se achica antes de mandarla (window.ImgUtils, el mismo criterio que el chat).
// Rotar: el giro lo hace un canvas acá y al servidor va la imagen ya girada; se muestra
// girada apenas se codifica, y se guarda en segundo plano.
// Ordenar: se arrastra desde ↕ (orden.js, de cada dispositivo).
// La primera es la portada de la tarjeta en la vista galería del inventario.
import { ref, computed, watch, nextTick, onUnmounted } from 'vue'
import { useOrdenable } from '@/orden'

const props = defineProps({
  fotos: { type: Array, required: true },
  puedeEditar: { type: Boolean, default: false },
  puedeRotar: { type: Boolean, default: false },
  subiendo: { type: Boolean, default: false },
  rotar: { type: Function, default: null }, // (foto, blob) => Promise
  claveOrden: { type: String, default: '' }, // dónde guarda el orden (orden.js)
})
const emit = defineEmits(['subir', 'borrar', 'error'])

const entrada = ref(null)
const abierta = ref(-1)
const botonCerrar = ref(null)
const girando = ref(false)
// Vista previa de una foto recién girada mientras se guarda: id → objectURL.
const previas = ref({})
let foco = null

const grilla = ref(null)
const { items: ordenadas, arrastrando } = useOrdenable(
  computed(() => props.claveOrden), grilla, computed(() => props.fotos), (f) => f.id)

const actual = computed(() => ordenadas.value[abierta.value] || null)
const src = (f) => previas.value[f.id] || f.url
// Anchos que el navegador usa para elegir en la grilla: la miniatura mide MINI_LADO
// (fotos_disco.py) y la entera hasta ImgUtils.IMAGEN_LADO_MAX. Lo que ocupa cada foto
// sale de gestion.css: una sola llena la columna (420 px, o la pantalla en celular) y
// con dos o más van de a dos por fila.
const srcset = (f) => (previas.value[f.id] || !f.mini ? null : `${f.mini} 320w, ${f.url} 1568w`)
const sizes = computed(() => (ordenadas.value.length > 1
  ? '(max-width: 800px) 50vw, 210px'
  : '(max-width: 800px) 100vw, 420px'))

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
  const n = ordenadas.value.length
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
// Si la foto abierta desaparece (se borró acá o en otro dispositivo), acomodar el visor.
watch(() => props.fotos.length, (n) => {
  if (abierta.value >= n) n ? (abierta.value = n - 1) : cerrar()
})
// Cuando llega la URL nueva de una foto girada, la vista previa ya no hace falta.
watch(() => props.fotos.map((f) => f.url).join(), () => {
  for (const [id, url] of Object.entries(previas.value)) {
    URL.revokeObjectURL(url)
    delete previas.value[id]
  }
})
onUnmounted(() => {
  document.removeEventListener('keydown', teclado)
  document.body.classList.remove('g-sin-scroll')
  Object.values(previas.value).forEach((u) => URL.revokeObjectURL(u))
})

async function elegido(e) {
  const archivo = e.target.files?.[0]
  e.target.value = ''
  if (!archivo) return
  try {
    const dataUrl = await window.ImgUtils.achicarImagen(archivo)
    const blob = window.ImgUtils.dataURLaBlob(dataUrl)
    emit('subir', new File([blob], 'foto.jpg', { type: blob.type }))
  } catch {
    emit('subir', archivo) // si no se puede achicar, que decida el servidor
  }
}

function borrar() {
  if (!actual.value) return
  if (!confirm('¿Eliminar esta foto? Esta acción no se puede deshacer.')) return
  emit('borrar', actual.value)
}

async function girar() {
  const foto = actual.value
  if (!foto || !props.rotar) return
  girando.value = true
  try {
    const original = await (await fetch(src(foto))).blob()
    const salida = ['image/jpeg', 'image/png', 'image/webp'].includes(original.type) ? original.type : 'image/png'
    const bitmap = await createImageBitmap(original)
    const canvas = document.createElement('canvas')
    canvas.width = bitmap.height
    canvas.height = bitmap.width
    const ctx = canvas.getContext('2d')
    ctx.translate(canvas.width, 0)
    ctx.rotate(Math.PI / 2)
    ctx.drawImage(bitmap, 0, 0)
    bitmap.close?.()
    const girada = await new Promise((ok) => canvas.toBlob(ok, salida, 0.92))
    if (!girada) throw new Error('No se pudo generar la imagen girada')
    previas.value = { ...previas.value, [foto.id]: URL.createObjectURL(girada) }
    await props.rotar(foto, girada)
  } catch (e) {
    const previa = previas.value[foto.id]
    if (previa) {
      URL.revokeObjectURL(previa)
      const resto = { ...previas.value }
      delete resto[foto.id]
      previas.value = resto
    }
    emit('error', e)
  } finally {
    girando.value = false
  }
}
</script>

<template>
  <div class="g-foto-section">
    <div v-if="ordenadas.length" class="g-galeria">
      <div ref="grilla" class="g-galeria-grid">
        <div
          v-for="(f, i) in ordenadas" :key="f.id" class="a-foto-ordenable a-ordenable"
          :class="{ 'a-levantado': arrastrando === String(f.id) }" :data-orden="f.id"
        >
          <button type="button" class="g-foto-thumb"
            :aria-label="`Ver foto ${i + 1} de ${ordenadas.length}`" @click="abrir(i, $event)">
            <img :src="previas[f.id] || f.mini || f.url" :srcset="srcset(f)" :sizes="sizes" :alt="`Foto ${i + 1}`" class="g-foto" loading="lazy" decoding="async">
          </button>
          <button v-if="ordenadas.length > 1" type="button" class="a-orden-agarre"
            data-sin-arrastre :aria-label="`Cambiar orden de foto ${i + 1}`" title="Arrastrar para ordenar">↕</button>
        </div>
      </div>
      <p v-if="ordenadas.length > 1" class="a-orden-ayuda">Arrastrá desde ↕ para cambiar el orden de las fotos (en este dispositivo).</p>
    </div>
    <div v-if="puedeEditar" class="g-foto-toolbar">
      <input ref="entrada" type="file" accept="image/*" hidden @change="elegido">
      <button type="button" class="g-foto-btn" :title="subiendo ? 'Subiendo…' : 'Agregar foto'" :disabled="subiendo" @click="entrada.click()">
        {{ subiendo ? '⏳' : '📷' }}
      </button>
    </div>
  </div>

  <Teleport to="body">
    <div v-if="actual" class="g-lightbox" role="dialog" aria-modal="true" aria-label="Foto ampliada" @click.self="cerrar">
      <div class="g-lightbox-barra">
        <span class="g-lightbox-contador">{{ abierta + 1 }} / {{ ordenadas.length }}</span>
        <span class="g-lightbox-acciones">
          <button v-if="puedeRotar" type="button" class="g-lightbox-btn" title="Rotar 90°" :disabled="girando" @click="girar">
            {{ girando ? 'GUARDANDO…' : '⟳ ROTAR' }}
          </button>
          <button v-if="puedeEditar" type="button" class="g-lightbox-btn g-lightbox-btn-danger" title="Eliminar foto" @click="borrar">🗑 ELIMINAR</button>
          <button ref="botonCerrar" type="button" class="g-lightbox-btn" title="Cerrar (Esc)" @click="cerrar">✕</button>
        </span>
      </div>
      <button v-if="ordenadas.length > 1" type="button" class="g-lightbox-nav g-lightbox-prev" aria-label="Foto anterior" @click="mover(-1)">‹</button>
      <img class="g-lightbox-img" :src="src(actual)" alt="Foto ampliada">
      <button v-if="ordenadas.length > 1" type="button" class="g-lightbox-nav g-lightbox-next" aria-label="Foto siguiente" @click="mover(1)">›</button>
    </div>
  </Teleport>
</template>
