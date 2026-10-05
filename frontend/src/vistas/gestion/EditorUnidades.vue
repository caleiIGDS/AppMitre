<script setup>
// UNIDADES dentro de EDITAR (bloque de templates/gestion/form.html). `cantidad` es el COUNT
// de las unidades y no se edita a mano: se agregan tocando qué números libres van a tener,
// y se eliminan tocando cuáles y diciendo qué les pasó (cada una va al registro de bajas).
// Nunca se elimina la última: para sacar el recurso entero está DAR DE BAJA.
import { computed, ref, watch } from 'vue'
import { useAgregarUnidades, useEliminarUnidades } from '@/gestion/datos'
import { avisar, avisarError } from '@/avisos'

const props = defineProps({
  inv: { type: String, required: true },
  recurso: { type: Object, required: true },
  motivos: { type: Array, required: true },
})

const agregar = useAgregarUnidades(() => props.inv)
const eliminar = useEliminarUnidades(() => props.inv)

const usados = computed(() => props.recurso.unidades.flatMap((g) => g.numeros))
const total = computed(() => usados.value.length)

// --- Eliminar --------------------------------------------------------------------------
const aEliminar = ref(new Set())
const motivo = ref(props.motivos[0] || '')
const detalle = ref('')
const listaEliminar = computed(() => [...aEliminar.value].sort((a, b) => a - b))
const todas = computed(() => listaEliminar.value.length >= total.value)
// Si cambian las unidades (las eliminé, o las cambió otro), lo elegido que ya no existe se suelta.
watch(usados, (u) => {
  const existentes = new Set(u)
  aEliminar.value = new Set([...aEliminar.value].filter((n) => existentes.has(n)))
  aAgregar.value = new Set([...aAgregar.value].filter((n) => !existentes.has(n)))
})

function rotulo(verbo, nums) {
  return nums.length > 1 ? `${verbo} ${nums.length} unidades` : nums.length === 1 ? `${verbo} #${nums[0]}` : verbo
}

// Por nombre y no pasando el ref: en el template los refs llegan ya desenvueltos.
function alternar(cual, n) {
  const conjunto = cual === 'eliminar' ? aEliminar : aAgregar
  const s = new Set(conjunto.value)
  s.has(n) ? s.delete(n) : s.add(n)
  conjunto.value = s
}

async function enviarEliminar() {
  if (todas.value) return
  if (!confirm('¿Eliminar las unidades marcadas? Queda anotado en el registro de bajas.')) return
  try {
    const fila = await eliminar.mutateAsync({ id: props.recurso.id, numeros: listaEliminar.value, motivo: motivo.value, detalle: detalle.value })
    aEliminar.value = new Set()
    detalle.value = ''
    const n = (fila._eliminadas || []).length
    avisar(n === 1 ? 'Se eliminó 1 unidad.' : `Se eliminaron ${n} unidades.`)
  } catch (e) {
    avisarError(e, 'No se eliminaron las unidades')
  }
}

// --- Agregar ---------------------------------------------------------------------------
const aAgregar = ref(new Set())
const extra = ref(0) // "más…" suma de a 10
const libres = computed(() => {
  const ocupados = new Set(usados.value)
  const tope = Math.max(0, ...usados.value) + 10 + extra.value
  const salida = []
  for (let n = 1; n <= tope; n++) if (!ocupados.has(n)) salida.push(n)
  return salida
})
const listaAgregar = computed(() => [...aAgregar.value].sort((a, b) => a - b))

async function enviarAgregar() {
  try {
    await agregar.mutateAsync({ id: props.recurso.id, numeros: listaAgregar.value })
    aAgregar.value = new Set()
    extra.value = 0
  } catch (e) {
    avisarError(e, 'No se agregaron las unidades')
  }
}
</script>

<template>
  <section class="g-form-kit g-form-unidades">
    <h3>UNIDADES · <span>{{ total }}</span></h3>
    <p class="g-help">
      Cada unidad tiene su número propio. La cantidad del recurso es cuántas unidades hay
      — se ajusta acá, no en el campo de arriba.
    </p>

    <div class="g-uni-chips">
      <div v-for="g in recurso.unidades" :key="g.ubicacion" class="g-uni-grupo">
        <span class="g-uni-lugar">{{ g.ubicacion }}</span>
        <div class="g-ficha-unidades">
          <button
            v-for="n in g.numeros" :key="n" type="button" class="g-ficha-unidad"
            :aria-pressed="aEliminar.has(n)" @click="alternar('eliminar', n)"
          >#{{ n }}</button>
        </div>
      </div>
    </div>
    <p class="g-help g-uni-ayuda">Tocá una unidad para eliminarla (se rompió, se perdió).</p>

    <form v-if="listaEliminar.length" class="g-uni-eliminar" @submit.prevent="enviarEliminar">
      <div class="g-uni-motivo">
        <div class="g-field">
          <label for="uni-motivo">QUÉ LES PASÓ *</label>
          <select id="uni-motivo" v-model="motivo">
            <option v-for="op in motivos" :key="op" :value="op">{{ op }}</option>
          </select>
        </div>
        <div class="g-field">
          <label for="uni-detalle">DETALLE</label>
          <textarea id="uni-detalle" v-model="detalle" rows="2" placeholder="Ej: se quemó en la práctica del 3° B" />
        </div>
      </div>
      <button type="submit" class="g-btn-mini g-btn-danger" :disabled="todas || eliminar.isPending.value">
        {{ eliminar.isPending.value ? 'Eliminando…' : rotulo('− Eliminar', listaEliminar) }}
      </button>
      <span v-if="todas" class="g-help g-uni-ultima">Tiene que quedar al menos una unidad: para
        sacar el recurso entero está DAR DE BAJA, abajo.</span>
    </form>

    <form class="g-uni-agregar" @submit.prevent="enviarAgregar">
      <p class="g-help">Agregar unidades: tocá los números libres que van a tener.</p>
      <div class="g-uni-libres">
        <button
          v-for="n in libres" :key="n" type="button" class="g-ficha-unidad is-libre"
          :aria-pressed="aAgregar.has(n)" @click="alternar('agregar', n)"
        >#{{ n }}</button>
        <button type="button" class="g-uni-mas" @click="extra += 10">más…</button>
      </div>
      <button type="submit" class="g-btn-mini" :disabled="!listaAgregar.length || agregar.isPending.value">
        {{ agregar.isPending.value ? 'Agregando…' : rotulo('+ Agregar', listaAgregar) }}
      </button>
    </form>
  </section>
</template>
