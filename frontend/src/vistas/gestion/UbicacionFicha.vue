<script setup>
// "Ubicación" de la ficha: las unidades agrupadas por
// lugar. Con permiso, se tocan los números para elegir cuáles mover o dejar sin ubicar;
// el cambio se aplica en la ficha, sin navegar.
import { computed, ref, watch } from 'vue'
import { useMoverUnidades, useQuitarUbicacion } from '@/gestion/datos'
import { avisar, avisarError } from '@/avisos'

const props = defineProps({
  inv: { type: String, required: true },
  recurso: { type: Object, required: true },
  puedeEditar: { type: Boolean, default: false },
  lugares: { type: Array, default: () => [] },
})

const mover = useMoverUnidades(() => props.inv)
const quitar = useQuitarUbicacion(() => props.inv)
const elegidas = ref(new Set())
const lugar = ref('')
const campoLugar = ref(null)

// Si la misma pantalla pasa a mostrar otro recurso, lo elegido era del anterior.
watch(() => props.recurso.id, () => { elegidas.value = new Set(); lugar.value = '' })
watch(() => props.puedeEditar, (puede) => {
  if (!puede) { elegidas.value = new Set(); lugar.value = '' }
})

const lista = computed(() => [...elegidas.value].sort((a, b) => a - b))
const ocupado = computed(() => mover.isPending.value || quitar.isPending.value)

function alternar(n) {
  const s = new Set(elegidas.value)
  s.has(n) ? s.delete(n) : s.add(n)
  elegidas.value = s
}

async function moverAca() {
  if (!lugar.value.trim()) { campoLugar.value?.focus(); return }
  try {
    const fila = await mover.mutateAsync({ id: props.recurso.id, numeros: lista.value, ubicacion: lugar.value.trim() })
    elegidas.value = new Set()
    lugar.value = ''
    for (const aviso of fila._avisos || []) avisar(aviso, { tipo: 'alerta', duracion: 6000 })
  } catch (e) {
    avisarError(e, 'No se movieron las unidades')
  }
}

function sinUbicar() {
  const numeros = lista.value
  elegidas.value = new Set()
  quitar.mutate({ id: props.recurso.id, numeros }, {
    onError: (e) => avisarError(e, 'No se pudo marcar sin ubicar'),
  })
}
</script>

<template>
  <div class="g-ficha-bar g-ficha-ubic-head">
    <span>UBICACIÓN</span>
    <span v-if="puedeEditar" class="g-ficha-mover-ayuda">Elegí una unidad para moverla.</span>
  </div>
  <div v-if="recurso.unidades.length" class="g-ficha-ubic">
    <div v-for="g in recurso.unidades" :key="g.ubicacion" class="g-ficha-ubic-row">
      <div class="g-ficha-ubic-datos">
        <span class="g-ficha-ubic-lugar">{{ g.ubicacion }}</span>
        <div class="g-ficha-unidades">
          <template v-for="n in g.numeros" :key="n">
            <button
              v-if="puedeEditar" type="button" class="g-ficha-unidad"
              :aria-pressed="elegidas.has(n)" @click="alternar(n)"
            >#{{ n }}</button>
            <span v-else class="g-ficha-unidad is-lectura">#{{ n }}</span>
          </template>
        </div>
      </div>
      <div class="g-ficha-ubic-count">{{ g.numeros.length }}</div>
    </div>
  </div>
  <p v-else class="g-ficha-vacio">Todavía no hay unidades cargadas.</p>

  <template v-if="puedeEditar">
    <form v-if="lista.length" class="g-ficha-mover" @submit.prevent="moverAca">
      <span class="g-ficha-mover-count">{{ lista.length === 1 ? '1 unidad elegida' : `${lista.length} unidades elegidas` }}</span>
      <input ref="campoLugar" v-model="lugar" type="text" list="datalist-lugar-desglose" placeholder="Lugar" aria-label="Lugar">
      <datalist id="datalist-lugar-desglose">
        <option v-for="l in lugares" :key="l" :value="l" />
      </datalist>
      <button type="submit" class="g-btn g-btn-mini" :disabled="ocupado">{{ mover.isPending.value ? 'Moviendo…' : 'Mover acá' }}</button>
      <button type="button" class="g-btn-mini g-btn-outline-dark" :disabled="ocupado" @click="sinUbicar">Marcar sin ubicar</button>
    </form>
  </template>
</template>
