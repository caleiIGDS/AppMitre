<script setup>
// La pestaña MATERIAS: qué materias se dan, filtradas por tipo (técnico-específica,
// científico-tecnológica, teórica), año, división y especialidad, en cualquier combinación.
// Los filtros viven en la dirección (?tipo=te&anio=4,5&div=2,3&esp=...), así que se pueden
// compartir.
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  useHorarios, materiasFiltradas, especialidades, divisionesDe, siglaEspecialidad,
  TIPOS_MATERIA, horasTexto,
} from '../datos'
import { useIrA } from '../navegar'
import Cargando from '../componentes/Cargando.vue'

const route = useRoute()
const router = useRouter()
const irA = useIrA()
const datos = useHorarios()
const d = computed(() => datos.data.value)

const lista = (v) => String(v || '').split(',').filter(Boolean)
const tipos = computed(() => lista(route.query.tipo))
const anios = computed(() => lista(route.query.anio))
const divs = computed(() => lista(route.query.div))
const esps = computed(() => lista(route.query.esp))
const texto = computed(() => String(route.query.q || ''))

const ANIOS = ['1', '2', '3', '4', '5', '6', '7']
const opcionesEsp = computed(() => especialidades(d.value))
// Las divisiones que existen en los años y especialidades marcados.
const opcionesDiv = computed(() => divisionesDe(d.value, anios.value, esps.value))
// Una división marcada que ya no está entre las opciones (se cambió de año) no filtra.
const divsActivas = computed(() => divs.value.filter((x) => opcionesDiv.value.includes(x)))
const NOMBRE_TIPO = Object.fromEntries(TIPOS_MATERIA)

function cambiar(cambios) {
  const query = { ...route.query, ...cambios }
  for (const k of Object.keys(query)) if (!query[k]) delete query[k]
  router.replace({ name: 'materia', query })
}
function alternar(campo, actuales, valor) {
  const nuevos = actuales.includes(valor) ? actuales.filter((x) => x !== valor) : [...actuales, valor]
  cambiar({ [campo]: nuevos.join(',') })
}
const hayFiltros = computed(() => tipos.value.length || anios.value.length || divs.value.length
  || esps.value.length || texto.value)
const limpiar = () => router.replace({ name: 'materia' })

const filas = computed(() => materiasFiltradas(d.value, {
  tipos: tipos.value, anios: anios.value, divs: divsActivas.value, esps: esps.value, texto: texto.value,
}))
const resumen = computed(() => {
  const divisiones = new Set(filas.value.map((f) => `${f.curso} ${f.division}`)).size
  const materias = new Set(filas.value.map((f) => f.materia)).size
  const min = filas.value.reduce((s, f) => s + f.minutos, 0)
  return `${materias} materia${materias === 1 ? '' : 's'} · ${filas.value.length} cupo${filas.value.length === 1 ? '' : 's'}`
    + ` · ${divisiones} ${divisiones === 1 ? 'división' : 'divisiones'} · ${horasTexto(min)} semanales`
})
const sinTipo = computed(() => d.value && !d.value.clases.some((f) => f.tipo_materia))
</script>

<template>
  <section class="tech-search-module">
    <div class="tech-field-group">
      <div class="tech-field">
        <input
          :value="texto" type="text" class="tech-input" placeholder="MATERIA O PROFESOR..."
          autocomplete="off" @input="cambiar({ q: $event.target.value })"
        >
      </div>
      <button v-if="hayFiltros" type="button" class="h-btn h-btn-claro" @click="limpiar">LIMPIAR</button>
    </div>
    <div class="planilla-controls">
      <div class="planilla-section">
        <span class="planilla-label">TIPO:</span>
        <div class="planilla-tabs">
          <button
            v-for="[clave, nombre] in TIPOS_MATERIA" :key="clave" type="button" class="planilla-tab-btn"
            :class="{ active: tipos.includes(clave) }" @click="alternar('tipo', tipos, clave)"
          >{{ nombre }}</button>
        </div>
      </div>
      <div class="planilla-section">
        <span class="planilla-label">AÑO:</span>
        <div class="planilla-tabs">
          <button
            v-for="a in ANIOS" :key="a" type="button" class="planilla-tab-btn"
            :class="{ active: anios.includes(a) }" @click="alternar('anio', anios, a)"
          >{{ a }}°</button>
        </div>
      </div>
      <div v-if="opcionesDiv.length" class="planilla-section">
        <span class="planilla-label">DIVISIÓN:</span>
        <div class="planilla-tabs">
          <button
            v-for="x in opcionesDiv" :key="x" type="button" class="planilla-tab-btn"
            :class="{ active: divs.includes(x) }" @click="alternar('div', divs, x)"
          >{{ x }}</button>
        </div>
      </div>
      <div class="planilla-section">
        <span class="planilla-label">ESPECIALIDAD:</span>
        <div class="planilla-tabs">
          <button
            v-for="[clave, nombre] in opcionesEsp" :key="clave" type="button" class="planilla-tab-btn"
            :class="{ active: esps.includes(clave) }" @click="alternar('esp', esps, clave)"
          >{{ nombre }}</button>
        </div>
      </div>
    </div>
  </section>

  <div v-if="d" class="workspace-header" style="display: flex;">
    <h2 class="tech-title-center">{{ resumen }}</h2>
  </div>
  <main class="tech-workspace">
    <Cargando v-if="!d" :consulta="datos" />
    <div v-else class="tech-data-table">
      <p v-if="sinTipo" class="h-aviso-materias">
        La planilla todavía no trae el tipo de cada materia: el filtro por tipo no va a encontrar nada.
      </p>
      <table v-if="filas.length" class="h-tabla-materias">
        <thead>
          <tr>
            <th>CURSO</th>
            <th>ESP.</th>
            <th>MATERIA</th>
            <th>TIPO</th>
            <th>PROFESOR</th>
            <th>HS. SEM.</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="f in filas" :key="f.clave">
            <td class="h-celda-centro">
              <a href="#" @click.prevent="irA('curso', `${f.curso}° ${f.division}`)">{{ f.curso }}° {{ f.division }}</a>
              <span v-if="f.grupo" class="h-grupo">GR. {{ f.grupo }}</span>
            </td>
            <td class="h-celda-centro" :title="f.especialidad">{{ siglaEspecialidad(f.especialidad) || '-' }}</td>
            <td>{{ f.materia }}</td>
            <td>{{ NOMBRE_TIPO[f.tipo] || '-' }}</td>
            <td>
              <template v-if="f.suplente">
                <a href="#" @click.prevent="irA('profesor', f.suplente)">{{ f.suplente }}</a>
                <span class="h-suplencia">suplente de
                  <a href="#" @click.prevent="irA('profesor', f.profesor)">{{ f.profesor }}</a></span>
              </template>
              <a v-else-if="f.profesor" href="#" @click.prevent="irA('profesor', f.profesor)">{{ f.profesor }}</a>
              <span v-else class="h-vacante">SIN CUBRIR</span>
            </td>
            <td class="h-celda-centro">{{ horasTexto(f.minutos) }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else style="padding:20px; text-align:center; color:#70757a;">No hay materias con esos filtros.</div>
    </div>
  </main>
</template>
