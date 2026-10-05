<script setup>
// Alta y edición de un recurso.
//
// Guardar espera la respuesta del servidor (para mostrar los errores en el campo que
// corresponde) y vuelve a la ficha con el cambio ya aplicado: no se vuelve a bajar nada.
//
// Si mientras se editaba alguien más cambió el mismo recurso, el servidor contesta 409
// con la versión actual. Si tocaron campos distintos se combinan los dos cambios solos;
// si tocaron el mismo campo, se muestra la diferencia y se elige.
import { computed, reactive, ref, watchEffect, onMounted, onUnmounted } from 'vue'
import { useRouter, onBeforeRouteLeave } from 'vue-router'
import { useRecurso, useMetaGestion, useGuardarRecurso } from '@/gestion/datos'
import { volverA } from '@/navegacion'
import { avisar, avisarError } from '@/avisos'
import EstadoCarga from '@/componentes/EstadoCarga.vue'
import CampoFormulario from '@/componentes/CampoFormulario.vue'

const props = defineProps({ id: { type: String, default: '' } })
const router = useRouter()
const esNuevo = !props.id
const { consulta, recurso } = useRecurso(() => props.id)
const meta = useMetaGestion()
const guardarRecurso = useGuardarRecurso()

const campos = computed(() => meta.data.value?.entidades?.recursos?.campos || [])
const valores = reactive({})
const base = reactive({}) // lo que había cuando se empezó a editar (o al último combinar)
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
    else if (c.nombre === 'fecha_revision') v = meta.data.value.fecha_revision_hoy
    else if (c.tipo === 'select') v = c.opciones[0]
    else v = ''
    valores[c.nombre] = v
    base[c.nombre] = v
  }
  version.value = esNuevo ? null : recurso.value.version
  listo.value = true
})

const cambiados = computed(() => campos.value.filter((c) => valores[c.nombre] !== base[c.nombre]).map((c) => c.nombre))
const sucio = computed(() => listo.value && (esNuevo ? campos.value.some((c) => valores[c.nombre] && c.nombre !== 'fecha_revision' && c.tipo !== 'select') : cambiados.value.length > 0))
const destinoVolver = computed(() => (esNuevo ? { name: 'inventario' } : { name: 'recurso', params: { id: props.id } }))

function hoy() {
  valores.fecha_revision = meta.data.value.fecha_revision_hoy
}

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
    if (esNuevo) router.replace({ name: 'recurso', params: { id: fila.id } })
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
    absorber(actual)
    avisar('Alguien más editó este recurso mientras tanto: se combinaron los dos cambios.', { tipo: 'alerta', duracion: 6000 })
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

function cancelar() {
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
    <p>Este recurso ya no existe: lo eliminaron mientras lo editabas.</p>
    <RouterLink class="g-btn" :to="{ name: 'inventario' }">VOLVER AL INVENTARIO</RouterLink>
  </div>

  <template v-else-if="listo">
    <div class="g-toolbar">
      <div>
        <span v-if="!esNuevo" class="g-breadcrumb">
          <RouterLink class="g-link" :to="{ name: 'inventario' }">INVENTARIO</RouterLink> /
          <RouterLink class="g-link" :to="destinoVolver">{{ recurso.nombre.toUpperCase() }}</RouterLink> /
        </span>
        <h2>{{ esNuevo ? 'CREAR RECURSO' : 'EDITAR RECURSO' }}</h2>
      </div>
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

    <form class="g-form" novalidate @submit.prevent="guardar">
      <CampoFormulario
        v-for="c in campos" :key="c.nombre" v-model="valores[c.nombre]"
        :campo="c" :error="errores[c.nombre] || ''"
      >
        <template v-if="c.nombre === 'fecha_revision'" #accion>
          <button type="button" class="g-btn-outline-dark a-btn-hoy" @click="hoy">HOY</button>
        </template>
      </CampoFormulario>

      <div class="g-form-actions">
        <button type="submit" class="g-btn" :disabled="guardarRecurso.isPending.value || !!conflicto">
          {{ guardarRecurso.isPending.value ? 'GUARDANDO…' : 'GUARDAR' }}
        </button>
        <button type="button" class="g-btn-outline-dark" @click="cancelar">CANCELAR</button>
      </div>
    </form>
  </template>
</template>
