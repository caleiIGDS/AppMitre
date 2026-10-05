<script setup>
// "Ubicación" de un recurso: sus unidades numeradas, agrupadas por lugar. Mover unidades
// o dejarlas sin ubicar no navega a ningún lado: cambia la ficha en el lugar.
import { ref } from 'vue'
import { useMoverUnidades, useQuitarUnidad } from '@/gestion/datos'
import { avisar, avisarError } from '@/avisos'

const props = defineProps({
  recurso: { type: Object, required: true },
  puedeEditar: { type: Boolean, default: false },
  lugares: { type: Array, default: () => [] },
})

const mover = useMoverUnidades()
const quitar = useQuitarUnidad()
const numeros = ref('')
const lugar = ref('')
const error = ref('')

function leerNumeros(texto) {
  const lista = []
  for (const parte of texto.split(/[,\s]+/).filter(Boolean)) {
    const rango = parte.match(/^(\d+)-(\d+)$/)
    if (rango) {
      const [a, b] = [Number(rango[1]), Number(rango[2])].sort((x, y) => x - y)
      for (let n = a; n <= b && lista.length < 500; n++) lista.push(n)
    } else if (/^\d+$/.test(parte)) {
      lista.push(Number(parte))
    } else {
      return null
    }
  }
  return lista
}

async function enviarMover() {
  error.value = ''
  const lista = leerNumeros(numeros.value)
  if (!lista || !lista.length) {
    error.value = 'Escribí números de unidad: 1,3,5 o un rango como 2-6.'
    return
  }
  try {
    const fila = await mover.mutateAsync({ id: props.recurso.id, numeros: lista, ubicacion: lugar.value.trim() })
    numeros.value = ''
    lugar.value = ''
    for (const aviso of fila._avisos || []) avisar(aviso, { tipo: 'alerta', duracion: 6000 })
  } catch (e) {
    error.value = e.message
  }
}

function sacar(numero) {
  quitar.mutate({ id: props.recurso.id, numero }, {
    onError: (e) => avisarError(e, `No se pudo dejar sin ubicar la unidad #${numero}`),
  })
}
</script>

<template>
  <div v-if="recurso.unidades.length" class="g-unidades">
    <div v-for="g in recurso.unidades" :key="g.ubicacion" class="g-unidad-grupo">
      <strong>{{ g.ubicacion }}:</strong>
      <span v-for="n in g.numeros" :key="n" class="g-unidad-chip">
        #{{ n }}
        <button
          v-if="puedeEditar && g.ubicacion !== 'Sin ubicar'" type="button"
          class="g-btn-mini g-btn-danger" :title="`Dejar la unidad #${n} sin ubicar`" @click="sacar(n)"
        >×</button>
      </span>
    </div>
  </div>
  <p v-else class="g-help">Todavía no hay unidades cargadas.</p>

  <form v-if="puedeEditar" class="g-inline-form a-form-unidades" @submit.prevent="enviarMover">
    <input v-model="numeros" type="text" placeholder="Unidades (ej: 1,3,5 o 2-6)" required aria-label="Números de unidad" inputmode="numeric">
    <input v-model="lugar" type="text" list="a-lugares-sugeridos" placeholder="Lugar" required aria-label="Lugar">
    <datalist id="a-lugares-sugeridos">
      <option v-for="l in lugares" :key="l" :value="l" />
    </datalist>
    <button type="submit" class="g-btn-mini" :disabled="mover.isPending.value">{{ mover.isPending.value ? 'Moviendo…' : 'Mover' }}</button>
  </form>
  <p v-if="error" class="a-error-campo" role="alert">{{ error }}</p>
</template>
