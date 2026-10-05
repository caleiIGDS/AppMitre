<script setup>
// Alta y edición de un recurso: la pantalla de templates/crud/form.html + gestion/form.html.
// Arriba los campos (GUARDAR); en edición, abajo, lo que se guarda por su cuenta: unidades,
// kit y la baja.
//
// Guardar espera la respuesta del servidor (para marcar el error en el campo que
// corresponde) y vuelve a la ficha con el cambio ya aplicado: no se vuelve a bajar nada.
//
// Si mientras se editaba alguien más cambió el mismo recurso, el servidor contesta 409 con
// la versión actual. Si tocaron campos distintos se combinan solos; si tocaron el mismo, se
// muestra la diferencia y se elige. Lo que se hace abajo (unidades, kit) también sube la
// versión del recurso, pero no toca ningún campo del formulario: esa versión se adopta sola.
import { computed, reactive, ref, watch, watchEffect, onMounted, onUnmounted } from 'vue'
import { useRouter, onBeforeRouteLeave } from 'vue-router'
import { useRecurso, useMeta, useGuardarRecurso } from '@/gestion/datos'
import { volverA } from '@/navegacion'
import { avisar, avisarError } from '@/avisos'
import EstadoCarga from '@/componentes/EstadoCarga.vue'
import CampoFormulario from '@/componentes/CampoFormulario.vue'
import EditorUnidades from './EditorUnidades.vue'
import EditorKit from './EditorKit.vue'
import BajaRecurso from './BajaRecurso.vue'

const props = defineProps({
  inv: { type: String, required: true },
  id: { type: String, default: '' },
})
const router = useRouter()
const esNuevo = !props.id
const { consulta, recurso } = useRecurso(() => props.inv, () => props.id)
const meta = useMeta(() => props.inv)
const guardarRecurso = useGuardarRecurso(() => props.inv)

const m = computed(() => meta.data.value || {})
const entidad = computed(() => m.value.entidades?.recursos)
// `solo_alta` (cantidad): en edición no se muestra ni se manda; se maneja por unidades.
const campos = computed(() => (entidad.value?.campos || []).filter((c) => esNuevo || !c.solo_alta))
const valores = reactive({})
const base = reactive({}) // lo que había al empezar a editar (o al último combinar)
const version = ref(null)
const listo = ref(false)
const errores = ref({})
const errorGeneral = ref('')
const conflicto = ref(null)
const eliminado = ref(false)
let guardado = false

const texto = (v) => (v === null || v === undefined ? '' : String(v))

// Se completa UNA vez, cuando están la config y (si es edición) el recurso. Después el
// formulario es de quien lo está llenando: un refresco de fondo no le pisa lo escrito.
watchEffect(() => {
  if (listo.value || !campos.value.length) return
  if (!esNuevo && !recurso.value) return
  for (const c of campos.value) {
    let v
    if (!esNuevo) v = texto(recurso.value[c.nombre])
    else if (c.boton_hoy) v = m.value.hoy || ''
    else if (c.tipo === 'select') v = c.opciones[0]
    else v = ''
    valores[c.nombre] = v
    base[c.nombre] = v
  }
  version.value = esNuevo ? null : recurso.value.version
  listo.value = true
})

const cambiados = computed(() => campos.value.filter((c) => valores[c.nombre] !== base[c.nombre]).map((c) => c.nombre))
const sucio = computed(() => listo.value && (esNuevo
  ? campos.value.some((c) => !c.boton_hoy && c.tipo !== 'select' && valores[c.nombre])
  : cambiados.value.length > 0))
const destinoVolver = computed(() => (esNuevo
  ? { name: 'recursos', params: { inv: props.inv } }
  : { name: 'recurso', params: { inv: props.inv, id: props.id } }))

// Una versión nueva del recurso que no cambió ningún campo del formulario (fue una unidad,
// un ítem del kit, una foto) se adopta sin avisar: no hay nada que combinar.
watch(() => recurso.value?.version, (nueva) => {
  if (!listo.value || esNuevo || !nueva || nueva === version.value || conflicto.value) return
  if (campos.value.every((c) => texto(recurso.value[c.nombre]) === base[c.nombre])) version.value = nueva
})

async function guardar() {
  errores.value = {}
  errorGeneral.value = ''
  try {
    const fila = await guardarRecurso.mutateAsync({
      id: esNuevo ? null : Number(props.id),
      valores: { ...valores },
      version: version.value,
    })
    guardado = true
    avisar(esNuevo ? 'Recurso creado.' : 'Cambios guardados.')
    if (esNuevo) router.replace({ name: 'recurso', params: { inv: props.inv, id: fila.id } })
    else volverA(destinoVolver.value)
  } catch (e) {
    if (e.status === 422) {
      errores.value = e.errores
      errorGeneral.value = e.message
    } else if (e.status === 409) {
      resolverConflicto(e.datos.actual)
    } else if (e.status === 404) {
      eliminado.value = true
    } else {
      avisarError(e, 'No se guardó')
    }
  }
}

// Trae al formulario lo que otro guardó en los campos que esta persona no tocó, y deja
// `base` en la versión actual del servidor para esos campos.
function absorber(actual, salvo = []) {
  for (const c of campos.value) {
    if (salvo.includes(c.nombre)) continue
    const suyo = texto(actual[c.nombre])
    if (!cambiados.value.includes(c.nombre)) valores[c.nombre] = suyo
    base[c.nombre] = suyo
  }
  version.value = actual.version
}

function resolverConflicto(actual) {
  if (!actual) { eliminado.value = true; return }
  const mios = [...cambiados.value]
  const choque = mios.filter((k) => texto(actual[k]) !== base[k] && texto(actual[k]) !== valores[k])
  if (!choque.length) {
    const ajenos = campos.value.some((c) => texto(actual[c.nombre]) !== base[c.nombre])
    absorber(actual)
    if (ajenos) avisar('Alguien más editó este recurso mientras tanto: se combinaron los dos cambios.', { tipo: 'alerta', duracion: 6000 })
    guardar()
    return
  }
  absorber(actual, choque)
  conflicto.value = {
    actual,
    campos: choque.map((k) => {
      const c = campos.value.find((x) => x.nombre === k)
      return { nombre: k, label: c.label, mio: valores[k], suyo: texto(actual[k]) }
    }),
  }
}

function quedarmeConLoMio() {
  for (const c of conflicto.value.campos) base[c.nombre] = c.suyo
  version.value = conflicto.value.actual.version
  conflicto.value = null
  guardar()
}

function quedarmeConLoGuardado() {
  for (const c of conflicto.value.campos) {
    valores[c.nombre] = c.suyo
    base[c.nombre] = c.suyo
  }
  version.value = conflicto.value.actual.version
  conflicto.value = null
  if (!cambiados.value.length) {
    guardado = true
    volverA(destinoVolver.value)
  }
}

function despuesDeLaBaja() {
  guardado = true // la baja ya se guardó; lo que quedara escrito arriba se descarta a propósito
  volverA(destinoVolver.value)
}

// --- No perder lo escrito ------------------------------------------------------------
onBeforeRouteLeave(() => {
  if (sucio.value && !guardado) return confirm('Hay cambios sin guardar. ¿Salir igual y perderlos?')
  return true
})
function antesDeCerrar(e) {
  if (sucio.value && !guardado) { e.preventDefault(); e.returnValue = '' }
}
onMounted(() => window.addEventListener('beforeunload', antesDeCerrar))
onUnmounted(() => window.removeEventListener('beforeunload', antesDeCerrar))
</script>

<template>
  <EstadoCarga v-if="!esNuevo" :consulta="consulta" que="el recurso" />
  <EstadoCarga :consulta="meta" que="el formulario" />

  <div v-if="eliminado || (!esNuevo && consulta.data.value && !recurso)" class="g-empty">
    <p>Este recurso ya no existe.</p>
    <RouterLink class="g-btn" :to="{ name: 'recursos', params: { inv } }">VOLVER AL INVENTARIO</RouterLink>
  </div>

  <template v-else-if="listo">
    <div class="g-toolbar">
      <h2>{{ esNuevo ? 'CREAR' : 'EDITAR' }} {{ (entidad?.singular || 'Recurso').toUpperCase() }}</h2>
    </div>

    <div v-if="errorGeneral" class="g-error" role="alert">{{ errorGeneral }}</div>

    <div v-if="conflicto" class="a-conflicto" role="alert">
      <h3>ALGUIEN MÁS CAMBIÓ ESTE RECURSO MIENTRAS LO EDITABAS</h3>
      <p class="g-help">Estos campos los cambiaron los dos. Lo demás ya se combinó.</p>
      <table class="g-tabla-detalle">
        <thead><tr><th>CAMPO</th><th>LO TUYO</th><th>LO QUE QUEDÓ GUARDADO</th></tr></thead>
        <tbody>
          <tr v-for="c in conflicto.campos" :key="c.nombre">
            <td>{{ c.label }}</td>
            <td class="g-pre">{{ c.mio || '(vacío)' }}</td>
            <td class="g-pre">{{ c.suyo || '(vacío)' }}</td>
          </tr>
        </tbody>
      </table>
      <div class="g-form-actions">
        <button type="button" class="g-btn" @click="quedarmeConLoMio">GUARDAR LO MÍO</button>
        <button type="button" class="g-btn-outline-dark" @click="quedarmeConLoGuardado">QUEDARME CON LO GUARDADO</button>
      </div>
    </div>

    <div class="g-editor">
      <form class="g-form" novalidate @submit.prevent="guardar">
        <div class="g-campos">
          <CampoFormulario
            v-for="c in campos" :key="c.nombre" v-model="valores[c.nombre]"
            :campo="c" :error="errores[c.nombre] || ''" :hoy="m.hoy || ''"
          />
        </div>
        <div class="g-form-actions">
          <button type="submit" class="g-btn" :disabled="guardarRecurso.isPending.value || !!conflicto">
            {{ guardarRecurso.isPending.value ? 'GUARDANDO…' : 'GUARDAR' }}
          </button>
          <button type="button" class="g-btn-outline-dark" @click="volverA(destinoVolver)">CANCELAR</button>
        </div>
      </form>

      <template v-if="!esNuevo && recurso && m.puede_escribir">
        <EditorUnidades :inv="inv" :recurso="recurso" :motivos="m.motivos_baja || []" />
        <EditorKit :inv="inv" :recurso="recurso" />
        <BajaRecurso
          :inv="inv" :recurso="recurso" :singular="entidad?.singular" :estado-baja="m.estado_baja"
          :motivos="m.motivos_baja || []" @hecho="despuesDeLaBaja"
        />
      </template>
    </div>
  </template>
</template>
