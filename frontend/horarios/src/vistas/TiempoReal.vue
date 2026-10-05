<script setup>
// TIEMPO REAL: qué clases están en curso y cuáles empiezan en las próximas 2 horas
// (renderizarDashboard de script.js). Se repinta cada segundo desde lo que ya está en el
// dispositivo; el horario en sí se vuelve a pedir cada 10 minutos (consultas.js).
// MODO MANUAL fija otro día y otra hora, para ver cómo va a estar la escuela.
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useHorarios, normalizar } from '../datos'
import { aMinutos, nombreProfesor } from '../calendario'
import { verClase } from '../ventanas'
import MenuOpciones from '../componentes/MenuOpciones.vue'
import Cargando from '../componentes/Cargando.vue'

const HORAS_PROXIMAS = 2
const NOMBRES_DIA = ['Domingo', 'Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado']

const datos = useHorarios()
const ahora = ref(new Date())
const filtro = ref('')
const manual = ref(false)
const fechaManual = ref('')
const horaManual = ref('')

let reloj = null
onMounted(() => { reloj = setInterval(() => { ahora.value = new Date() }, 1000) })
onUnmounted(() => clearInterval(reloj))

function alternarManual(e) {
  manual.value = e.target.checked
  if (manual.value) {
    const n = new Date()
    horaManual.value = n.toTimeString().slice(0, 5)
    fechaManual.value = `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, '0')}-${String(n.getDate()).padStart(2, '0')}`
  }
}

const usaManual = computed(() => manual.value && fechaManual.value && horaManual.value)
const textoReloj = computed(() => (manual.value && horaManual.value
  ? horaManual.value + ':00'
  : ahora.value.toLocaleTimeString('es-AR', { hour12: false })))

const momento = computed(() => {
  if (usaManual.value) {
    const [a, m, d] = fechaManual.value.split('-').map(Number)
    return { dia: NOMBRES_DIA[new Date(a, m - 1, d).getDay()], minutos: aMinutos(horaManual.value) }
  }
  const n = ahora.value
  return { dia: NOMBRES_DIA[n.getDay()], minutos: n.getHours() * 60 + n.getMinutes() }
})

const tablero = computed(() => {
  const clases = datos.data.value?.clases || []
  const q = normalizar(filtro.value)
  const { dia, minutos } = momento.value
  const enCurso = []
  const proximas = []
  for (const f of clases) {
    if (f.dia !== dia) continue
    if (q) {
      const curso = normalizar(`${f.curso} ${f.division}`)
      const prof = normalizar(f.suplente_activo == 1 ? f.prof_suplente : f.profesor)
      if (!curso.includes(q) && !prof.includes(q)) continue
    }
    const ini = aMinutos(f.hora_inicio)
    const fin = aMinutos(f.hora_fin)
    if (minutos >= ini && minutos <= fin) enCurso.push(f)
    else if (minutos < ini && ini < minutos + HORAS_PROXIMAS * 60) proximas.push(f)
  }
  const orden = (a, b) => aMinutos(a.hora_inicio) - aMinutos(b.hora_inicio)
  return { enCurso: enCurso.sort(orden), proximas: proximas.sort(orden) }
})
</script>

<template>
  <section class="tech-search-module">
    <div id="tab-envivo" class="seccion-busqueda active">
      <div class="tech-live-module">
        <div class="sys-clock-container">
          <div class="sys-clock">{{ textoReloj }}</div>
        </div>
        <div class="sys-inputs" style="margin-left: 20px;">
          <input
            v-model="filtro" type="text" class="tech-input-sm" placeholder="FILTRAR CURSO O PROF..."
            aria-label="Filtrar por curso o profesor"
            style="width: 200px; text-transform: uppercase; height: 35px; border: 1px solid var(--secondary); padding: 0 10px; font-weight: bold;"
          >
        </div>
        <MenuOpciones class="menu-global">
          <label class="slide-opcion" style="display:flex; align-items:center; gap:8px; cursor:pointer; user-select:none;">
            <input type="checkbox" :checked="manual" style="accent-color:var(--secondary);" @change="alternarManual">
            MODO MANUAL
          </label>
        </MenuOpciones>
        <div v-if="manual" class="sys-controls" style="display: flex;">
          <div class="sys-inputs">
            <input v-model="fechaManual" type="date" class="tech-input-sm" aria-label="Día">
            <input v-model="horaManual" type="time" class="tech-input-sm" aria-label="Hora">
          </div>
        </div>
      </div>
    </div>
  </section>

  <main class="tech-workspace">
    <Cargando v-if="!datos.data.value" :consulta="datos" />
    <div v-else class="dashboard-grid-light">
      <div v-for="[lista, nombre, clase] in [[tablero.enCurso, 'En Curso', 'in-progress'], [tablero.proximas, 'Próximas', 'upcoming']]" :key="clase" class="dashboard-column-light" :class="clase">
        <h2>{{ nombre }} {{ filtro ? '(Filtrado)' : '' }}</h2>
        <div class="class-list-light">
          <div v-if="!lista.length" style="text-align:center; padding:20px; color:#5f6368;">{{ filtro ? 'SIN COINCIDENCIAS' : 'SIN ACTIVIDAD' }}</div>
          <div
            v-for="(f, i) in lista" :key="i" class="class-item-light" style="cursor:pointer;"
            role="button" tabindex="0" @click="verClase(f)" @keydown.enter="verClase(f)"
          >
            <div class="class-time-light">{{ f.hora_inicio }} - {{ f.hora_fin }}</div>
            <div class="class-info-light">
              <span class="class-materia-light">{{ f.curso }}° {{ f.division }} | {{ f.suplente_activo == 1 ? nombreProfesor(f) : f.profesor }}</span>
              <span class="class-meta-light">{{ f.materia }}</span>
            </div>
            <div class="class-room-light">{{ f.aula || '-' }}</div>
          </div>
        </div>
      </div>
    </div>
  </main>
</template>
