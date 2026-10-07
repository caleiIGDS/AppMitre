<script setup>
// El campo de búsqueda con su lista desplegable: al
// enfocarlo muestra todo, al escribir filtra, Enter elige la primera.
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'
import { useHorarios, opcionesBuscador } from '../datos'

const props = defineProps({
  modo: { type: String, required: true },
  valor: { type: String, default: '' },
  placeholder: { type: String, default: '' },
  enfocar: { type: Boolean, default: false },
})
const emit = defineEmits(['elegir'])

const datos = useHorarios()
const texto = ref(props.valor)
const abierto = ref(false)
const campo = ref(null)
const caja = ref(null)
// El foco que pone la pantalla al abrirse deja el cursor listo pero no despliega la lista:
// se despliega cuando la persona toca el campo o escribe.
let silencioso = false

watch(() => props.valor, (v) => { texto.value = v })

const opciones = computed(() => (abierto.value ? opcionesBuscador(datos.data.value, props.modo, texto.value) : []))

function elegir(o) {
  texto.value = o.valor
  abierto.value = false
  campo.value?.blur()
  emit('elegir', o.valor)
}

// Sin v-model a propósito: v-model no actualiza mientras el teclado del celular está
// "componiendo" la palabra (Android), y la lista recién filtraba al terminarla.
function alEscribir(e) {
  texto.value = e.target.value
  abierto.value = true
}

function alTeclear(e) {
  if (e.key === 'Enter' && opciones.value.length) elegir(opciones.value[0])
  if (e.key === 'Escape') abierto.value = false
}

const fuera = (e) => { if (!caja.value?.contains(e.target)) abierto.value = false }
onMounted(() => {
  document.addEventListener('pointerdown', fuera)
  if (props.enfocar && !props.valor && window.matchMedia('(pointer: fine)').matches) {
    silencioso = true
    campo.value?.focus()
    silencioso = false
  }
})
onUnmounted(() => document.removeEventListener('pointerdown', fuera))
</script>

<template>
  <div ref="caja" class="tech-field">
    <input
      ref="campo" :value="texto" type="text" class="tech-input" :placeholder="placeholder"
      autocomplete="off" @focus="abierto = !silencioso" @click="abierto = true" @input="alEscribir" @keydown="alTeclear"
    >
    <div v-if="opciones.length" class="tech-dropdown" style="display: block;" role="listbox">
      <div
        v-for="o in opciones" :key="o.valor" class="dropdown-item" role="option"
        @click="elegir(o)"
      >{{ o.display }}<span v-if="o.rol" class="rol-badge">{{ o.rol }}</span></div>
    </div>
  </div>
</template>
