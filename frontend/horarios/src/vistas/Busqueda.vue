<script setup>
// Las pestañas CURSOS, PROFESORES, AULAS y PRECEPTORES de /horarios. Qué se muestra sale
// entero de la dirección (ver router.js): el horario buscado, la planilla general de un
// piso o la comparación de varios horarios.
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  useHorarios, clasesDe, clasesDePiso, horarioPreceptor, preceptoresDeCurso, COMPARABLES,
} from '../datos'
import { COLORES_COMPARACION } from '../calendario'
import { leerComparacion, escribirComparacion } from '../router'
import { useIrA } from '../navegar'
import { abrirPdf } from '../api'
import { verImprimirCursos } from '../ventanas'
import { avisar } from '@/avisos'
import Buscador from '../componentes/Buscador.vue'
import MenuOpciones from '../componentes/MenuOpciones.vue'
import Calendario from '../componentes/Calendario.vue'
import CalendarioComparacion from '../componentes/CalendarioComparacion.vue'
import TablaPreceptor from '../componentes/TablaPreceptor.vue'
import PlanillaPreceptores from '../componentes/PlanillaPreceptores.vue'
import Cargando from '../componentes/Cargando.vue'

const props = defineProps({
  modo: { type: String, required: true },
  valor: { type: String, default: '' },
})
const route = useRoute()
const router = useRouter()
const irA = useIrA()
const datos = useHorarios()
const d = computed(() => datos.data.value)
const dias = computed(() => d.value?.dias || [])

const PLACEHOLDER = {
  curso: 'INGRESE GRADO...',
  profesor: 'INGRESE NOMBRE...',
  aula: 'INGRESE UBICACIÓN...',
  horario_preceptor: 'INGRESE PRECEPTOR...',
}
const comparable = COMPARABLES.includes(props.modo)

// --- Comparación ---------------------------------------------------------------------
const comparando = computed(() => route.query.comparar !== undefined)
const enComparacion = computed(() => leerComparacion(route.query.comparar))
const itemsComparacion = computed(() => enComparacion.value.map((it, i) => ({
  ...it,
  color: COLORES_COMPARACION[i % COLORES_COMPARACION.length],
  filas: clasesDe(d.value, it.modo, it.valor, { conPersonal: false }),
})))

function compararDesdeAca(cerrar) {
  cerrar()
  if (!props.valor) {
    avisar('Primero buscá un horario para poder comparar.', { tipo: 'alerta' })
    return
  }
  router.replace({ name: props.modo, query: { comparar: escribirComparacion([{ modo: props.modo, valor: props.valor }]) } })
}

function quitarDeComparacion(i) {
  const items = enComparacion.value.filter((_, k) => k !== i)
  router.replace({ name: props.modo, query: { comparar: escribirComparacion(items) } })
}

function salirDeComparacion() {
  router.replace({ name: props.modo, params: props.valor ? { valor: props.valor } : {} })
}

// --- Planilla general (sólo AULAS) ---------------------------------------------------
const enPlanilla = computed(() => props.modo === 'aula' && route.query.planilla !== undefined && !comparando.value)
const pisos = computed(() => Object.keys(d.value?.pisos || {}))
const dia = computed(() => (dias.value.includes(route.query.dia) ? route.query.dia : dias.value[0]))
const piso = computed(() => (pisos.value.includes(route.query.piso) ? route.query.piso : (pisos.value[0] || '')))
const filasPlanilla = computed(() => (enPlanilla.value ? clasesDePiso(d.value, dia.value, piso.value) : []))

function planilla(cambios) {
  router.replace({ name: 'aula', query: { planilla: '1', dia: dia.value, piso: piso.value, ...cambios } })
}
function abrirPlanilla(cerrar) {
  cerrar()
  router.push({ name: 'aula', query: { planilla: '1', dia: dia.value, piso: piso.value } })
}
const cerrarPlanilla = () => router.replace({ name: 'aula', params: props.valor ? { valor: props.valor } : {} })

// --- Lo buscado ----------------------------------------------------------------------
const filas = computed(() => (props.valor && props.modo !== 'horario_preceptor' ? clasesDe(d.value, props.modo, props.valor) : []))
const filasPreceptor = computed(() => (props.modo === 'horario_preceptor' && props.valor ? horarioPreceptor(d.value, props.valor) : []))
const preceptores = computed(() => (props.modo === 'curso' && props.valor ? preceptoresDeCurso(d.value, props.valor) : null))
const ROTULOS = [['manana', 'MAÑANA', 'T.M:'], ['tarde', 'TARDE', 'T.T:'], ['vespertino', 'VESPERTINO', 'T.V:']]

const titulo = computed(() => {
  if (comparando.value) return ''
  if (enPlanilla.value) return `Planilla General: ${piso.value} - ${dia.value}`
  if (!props.valor) return ''
  if (props.modo !== 'horario_preceptor' && !filas.value.length) return ''
  return `Horario de ${props.modo.replace('_', ' ')}: ${props.valor}`
})

function pdf(cerrar) {
  cerrar()
  if (enPlanilla.value) abrirPdf(`planilla/${encodeURIComponent(`${dia.value}|${piso.value}`)}`)
  else if (props.valor) abrirPdf(`${props.modo}/${encodeURIComponent(props.valor)}`)
  else avisar('Primero buscá un horario.', { tipo: 'alerta' })
}
</script>

<template>
  <section class="tech-search-module">
    <div :id="'tab-' + modo" class="seccion-busqueda active">
      <div class="tech-field-group">
        <Buscador
          :key="modo" :modo="modo" :valor="comparando ? '' : valor" :placeholder="PLACEHOLDER[modo]" enfocar
          :style="enPlanilla ? 'opacity: 0.5; pointer-events: none;' : ''" @elegir="(v) => irA(modo, v)"
        />
        <div class="opciones-chips">
          <div v-if="comparando && comparable" class="opcion-chip comparar-chip">
            COMPARAR <button type="button" class="chip-close" aria-label="Salir de la comparación" @click="salirDeComparacion">✕</button>
          </div>
          <div v-if="enPlanilla" class="opcion-chip planilla-chip">
            PLANILLA <button type="button" class="chip-close" aria-label="Cerrar la planilla" @click="cerrarPlanilla">✕</button>
          </div>
        </div>
        <MenuOpciones v-slot="{ cerrar }">
          <template v-if="modo === 'horario_preceptor'">
            <button type="button" class="slide-opcion" @click="cerrar(); abrirPdf('planilla_preceptores')">IMPRIMIR TODOS</button>
          </template>
          <template v-else>
            <button v-if="!comparando" type="button" class="slide-opcion" @click="compararDesdeAca(cerrar)">COMPARAR</button>
            <button v-if="modo === 'aula' && !enPlanilla && !comparando" type="button" class="slide-opcion" @click="abrirPlanilla(cerrar)">PLANILLA GENERAL</button>
            <button v-if="!comparando" type="button" class="slide-opcion" @click="pdf(cerrar)">GENERAR PDF</button>
            <button v-if="modo === 'curso'" type="button" class="slide-opcion" @click="cerrar(); verImprimirCursos()">IMPRIMIR VARIOS</button>
          </template>
        </MenuOpciones>
      </div>

      <div v-if="enPlanilla" class="planilla-controls">
        <div class="planilla-section">
          <span class="planilla-label">DÍA:</span>
          <div class="planilla-tabs dias">
            <button
              v-for="x in dias" :key="x" type="button" class="planilla-tab-btn"
              :class="{ active: x === dia }" @click="planilla({ dia: x })"
            >{{ x.slice(0, 2) }}</button>
          </div>
        </div>
        <div class="planilla-section">
          <span class="planilla-label">UBICACIÓN:</span>
          <div class="planilla-tabs pisos">
            <button
              v-for="x in pisos" :key="x" type="button" class="planilla-tab-btn"
              :class="{ active: x === piso }" @click="planilla({ piso: x })"
            >{{ x }}</button>
          </div>
        </div>
      </div>
    </div>
  </section>

  <div v-if="comparando" class="modo-comparacion-banner" style="display: flex;">
    <div class="comp-banner-left">
      <span class="comp-banner-label">⚡ MODO COMPARACIÓN</span>
      <div class="comp-banner-items">
        <span v-for="(it, i) in itemsComparacion" :key="it.modo + it.valor" class="comp-chip" :style="{ background: it.color }">
          {{ it.valor }}<button type="button" class="comp-chip-close" :aria-label="'Quitar ' + it.valor" @click="quitarDeComparacion(i)">✕</button>
        </span>
      </div>
    </div>
    <button type="button" class="btn-salir-comparacion" @click="salirDeComparacion">✕ SALIR</button>
  </div>

  <div v-if="titulo" class="workspace-header" style="display: flex;">
    <h2 class="tech-title-center">{{ titulo }}</h2>
    <div v-if="preceptores" class="preceptor-info-container">
      <template v-for="[clave, turno, rotulo] in ROTULOS" :key="clave">
        <span v-if="preceptores[clave]" :class="{ principal: (preceptores.turno || '').toUpperCase() === turno }">
          {{ (preceptores.turno || '').toUpperCase() === turno ? 'PRECEPTOR PRINCIPAL' : 'Preceptor' }} {{ rotulo }} <b>{{ preceptores[clave].trim() }}</b>
        </span>
        <span v-else />
      </template>
    </div>
  </div>

  <main class="tech-workspace">
    <Cargando v-if="!d" :consulta="datos" />

    <template v-else-if="comparando">
      <div class="tech-grid-container">
        <CalendarioComparacion v-if="itemsComparacion.length" :items="itemsComparacion" :dias="dias" />
        <div v-else style="padding:60px; text-align:center; color:#70757a; letter-spacing:1px; font-size:14px;">Seleccioná un calendario para comparar.</div>
      </div>
    </template>

    <div v-else-if="enPlanilla" class="tech-grid-container">
      <Calendario
        v-if="filasPlanilla.length" :filas="filasPlanilla" :columnas="d.pisos[piso]" campo="aula" variante="planilla"
      />
      <div v-else style="padding:20px; text-align:center; color:#70757a;">No hay clases para {{ piso }} el {{ dia }}.</div>
    </div>

    <div v-else-if="modo === 'horario_preceptor'" class="tech-data-table">
      <TablaPreceptor v-if="valor" :filas="filasPreceptor" :dias="dias" />
      <PlanillaPreceptores v-else :filas="d.preceptores.planilla" />
    </div>

    <div v-else-if="valor" class="tech-grid-container">
      <Calendario v-if="filas.length" :filas="filas" :columnas="dias" :modo="modo" :licenciada-de="valor" />
      <div v-else style="padding:20px; text-align:center; color:#70757a;">No hay clases para mostrar.</div>
    </div>
  </main>
</template>
