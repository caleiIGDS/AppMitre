<script setup>
// El listado de un inventario: mismo markup que templates/gestion/lista.html y mismo
// filtrado que static/gestion.js. Los filtros viven en la URL
// (?q=…&lugar=…&estado=…&meses=…&baja=1): volver atrás, recargar o compartir el link deja
// la lista exactamente como estaba. Todo el filtrado es local, sobre la lista que ya está
// en el dispositivo.
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useRecursos, useMeta } from '@/gestion/datos'
import { norm, puntaje } from '@/texto'
import EstadoCarga from '@/componentes/EstadoCarga.vue'

const props = defineProps({ inv: { type: String, required: true } })
const route = useRoute()
const router = useRouter()
const recursos = useRecursos(() => props.inv)
const meta = useMeta(() => props.inv)

// --- Filtros ↔ URL -------------------------------------------------------------------
function filtro(clave) {
  return computed({
    get: () => (typeof route.query[clave] === 'string' ? route.query[clave] : ''),
    set: (valor) => router.replace({ query: { ...route.query, [clave]: valor || undefined } }),
  })
}
const lugar = filtro('lugar')
const estado = filtro('estado')
const baja = filtro('baja')
const meses = filtro('meses')

// El texto se escribe en local y llega a la URL con una pausa: si no, cada tecla sería
// una entrada nueva para el navegador.
const q = filtro('q')
const busqueda = ref(q.value)
let espera = null
watch(busqueda, (valor) => {
  clearTimeout(espera)
  espera = setTimeout(() => { q.value = valor.trim() }, 250)
})
watch(q, (valor) => { if (valor !== busqueda.value.trim()) busqueda.value = valor })

// El slider se mueve en local (fluido) y se anota en la URL al soltarlo.
const mesesVivo = ref(Number(meses.value) || 0)
watch(meses, (v) => { mesesVivo.value = Number(v) || 0 })

// --- Datos derivados -----------------------------------------------------------------
const m = computed(() => meta.data.value || {})
const ESTADO_BAJA = computed(() => m.value.estado_baja || 'Dado de baja')
const filas = computed(() => recursos.data.value || [])
const totalActivos = computed(() => filas.value.filter((r) => r.estado !== ESTADO_BAJA.value).length)

const lugares = computed(() => {
  const todos = new Set()
  for (const r of filas.value) for (const g of r.unidades) if (g.ubicacion !== 'Sin ubicar') todos.add(g.ubicacion)
  return [...todos].sort((a, b) => norm(a).localeCompare(norm(b)))
})

const qNorm = computed(() => norm(q.value))

// Misma jerarquía que crud.py::lista y gestion.js: primero lo que coincide por nombre o
// descripción (en orden alfabético), después lo que coincide sólo por el alias oculto.
const visibles = computed(() => {
  const porNombre = []
  const porAlias = []
  const umbral = mesesVivo.value * (m.value.dias_por_mes || 30.5)
  for (const r of filas.value) {
    let coincide = puntaje(qNorm.value, r._buscar) !== null
    let esAlias = false
    if (!coincide && r._buscar_alias && puntaje(qNorm.value, r._buscar_alias) !== null) { coincide = true; esAlias = true }
    if (coincide && lugar.value) coincide = r.unidades.some((g) => g.ubicacion === lugar.value)
    if (coincide && estado.value) coincide = r.estado === estado.value
    // dias_revision null = fecha corta sin año: nunca alcanza un umbral > 0.
    if (coincide && umbral > 0) coincide = (r.dias_revision ?? 0) >= umbral
    // "Sólo dados de baja" es excluyente; sin él, los dados de baja no aparecen.
    const deBaja = r.estado === ESTADO_BAJA.value
    coincide = coincide && (baja.value ? deBaja : !deBaja)
    if (coincide) (esAlias ? porAlias : porNombre).push(r)
  }
  return porNombre.concat(porAlias)
})

const subrecursos = computed(() => {
  if (!qNorm.value) return []
  const encontrados = []
  for (const r of filas.value) {
    for (const item of r.kit) {
      const p = puntaje(qNorm.value, norm(item.titulo))
      if (p !== null) encontrados.push({ item, kit: r, p })
    }
  }
  return encontrados.sort((a, b) => b.p - a.p)
})

const hayFiltroActivo = computed(() => !!(lugar.value || estado.value || mesesVivo.value > 0 || baja.value))
const hayFiltros = computed(() => !!(q.value || hayFiltroActivo.value))

// --- Panel de filtros en celular (mismo desplegable que gestion.js) -------------------
const filtrosAbiertos = ref(false)
const panel = ref(null)
const botonFiltros = ref(null)
function fueraDelPanel(e) {
  if (!filtrosAbiertos.value) return
  if (panel.value?.contains(e.target) || botonFiltros.value?.contains(e.target)) return
  filtrosAbiertos.value = false
}
onMounted(() => document.addEventListener('click', fueraDelPanel))
onUnmounted(() => document.removeEventListener('click', fueraDelPanel))

function limpiar() {
  busqueda.value = ''
  router.replace({ query: {} })
}

function abrir(r, evento) {
  if (evento.target.closest('a, button')) return
  router.push({ name: 'recurso', params: { inv: props.inv, id: r.id } })
}
</script>

<template>
  <div class="g-panel-top">
    <div class="g-toolbar">
      <div style="display: flex; align-items: baseline; gap: 12px;">
        <h2>INVENTARIO</h2>
        <span class="g-fichas-count">{{ hayFiltros ? visibles.length : totalActivos }} FICHAS</span>
        <span v-if="recursos.isFetching.value && recursos.data.value" class="a-actualizando" title="Buscando cambios en el servidor">●</span>
      </div>
      <div class="g-toolbar-actions">
        <form class="g-search g-search-mini" role="search" @submit.prevent>
          <span class="g-search-arrow" aria-hidden="true">&gt;</span>
          <input v-model="busqueda" type="search" name="q" placeholder="NOMBRE, TIPO O UBICACIÓN…" aria-label="Buscar recursos">
        </form>
        <button
          ref="botonFiltros" type="button" class="g-filtro-abrir" :class="{ 'g-filtro-activo': hayFiltroActivo }"
          :aria-expanded="filtrosAbiertos" aria-controls="panel-filtros" @click="filtrosAbiertos = !filtrosAbiertos"
        >
          <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true" focusable="false">
            <path d="M2.5 4h15M5.5 10h9M8.5 16h3" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
          </svg>
          <span class="g-sr-only">Filtros</span>
        </button>
        <RouterLink v-if="m.puede_escribir" class="g-btn" :to="{ name: 'recurso-nuevo', params: { inv } }">+ CREAR RECURSO</RouterLink>
      </div>
    </div>

    <div v-if="filas.length" id="panel-filtros" ref="panel" class="g-filtros" :class="{ 'g-filtros-abierta': filtrosAbiertos }">
      <span class="g-filtros-label">Filtros</span>
      <select v-if="lugares.length" v-model="lugar" class="g-filtro-select" aria-label="Filtrar por ubicación">
        <option value="">Ubicación: todas</option>
        <option v-for="l in lugares" :key="l" :value="l">{{ l }}</option>
      </select>
      <select v-if="m.estados" v-model="estado" class="g-filtro-select" aria-label="Filtrar por estado">
        <option value="">Estado: todos</option>
        <option v-for="e in m.estados" :key="e" :value="e">{{ e }}</option>
      </select>
      <span class="g-filtro-spacer" />
      <template v-if="m.puede_auditoria">
        <div class="g-filtro-fecha">
          <label for="filtro-fecha">Sin revisar hace +<span>{{ mesesVivo }}</span> meses</label>
          <input
            id="filtro-fecha" v-model.number="mesesVivo" type="range" min="0" max="24" step="0.5"
            @change="meses = mesesVivo ? String(mesesVivo) : ''"
          >
        </div>
        <button type="button" class="g-chip-vencidos" :aria-pressed="!!baja" @click="baja = baja ? '' : '1'">
          Sólo dados de baja
        </button>
      </template>
    </div>
  </div>

  <EstadoCarga :consulta="recursos" que="el inventario" />

  <template v-if="recursos.data.value">
    <div v-if="visibles.length" class="g-table-wrap">
      <table class="g-table">
        <thead>
          <tr><th>RECURSO</th><th>CANT.</th><th>LUGAR ASIGNADO</th><th>ESTADO</th></tr>
        </thead>
        <tbody>
          <tr
            v-for="r in visibles" :key="r.id" data-href
            :class="{ 'g-recurso-baja': r.estado === ESTADO_BAJA, 'g-recurso-roto': r.estado === 'Roto' }"
            @click="abrir(r, $event)"
          >
            <td data-label="RECURSO">
              <RouterLink class="g-item-link" :to="{ name: 'recurso', params: { inv, id: r.id } }">{{ r.nombre }}</RouterLink>
              <span v-if="r.tipo" class="g-recurso-sub">{{ r.tipo }}</span>
            </td>
            <td data-label="CANT.">{{ r.cantidad }}</td>
            <td data-label="LUGAR ASIGNADO">
              <div v-if="r.unidades.length > 1" class="g-lugares-multi">
                <span v-for="g in r.unidades" :key="g.ubicacion" class="g-lugar-item">{{ g.numeros.length }} x {{ g.ubicacion }}</span>
              </div>
              <template v-else-if="r.unidades.length">{{ r.unidades[0].ubicacion }}</template>
            </td>
            <td data-label="ESTADO" :data-estado="r.estado"><span v-if="r.estado" class="g-badge">{{ r.estado }}</span></td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-else-if="!subrecursos.length" class="g-empty">
      <template v-if="!filas.length">
        <p>Todavía no hay recursos cargados.</p>
        <RouterLink v-if="m.puede_escribir" class="g-btn" :to="{ name: 'recurso-nuevo', params: { inv } }">+ CREAR EL PRIMERO</RouterLink>
      </template>
      <template v-else>
        <p v-if="q">No se encontraron resultados para "{{ q }}".</p>
        <p v-else>No se encontraron recursos con ese filtro.</p>
        <button type="button" class="g-btn-outline-dark" @click="limpiar">LIMPIAR FILTROS</button>
      </template>
    </div>

    <template v-if="subrecursos.length">
      <div class="g-panel-top" style="margin-top: 24px;">
        <h3>SUB-RECURSOS DE KITS</h3>
      </div>
      <div class="g-table-wrap">
        <table class="g-table">
          <thead>
            <tr><th>SUB-RECURSO</th><th>CANT.</th><th>RECURSO ASIGNADO</th><th>KIT</th></tr>
          </thead>
          <tbody>
            <tr v-for="s in subrecursos" :key="s.item.id" data-href @click="abrir(s.kit, $event)">
              <td data-label="SUB-RECURSO">{{ s.item.titulo }}</td>
              <td data-label="CANT.">{{ s.item.cantidad }}</td>
              <td data-label="RECURSO ASIGNADO">{{ s.item.recurso_asignado }}</td>
              <td data-label="KIT">
                <RouterLink class="g-item-link" :to="{ name: 'recurso', params: { inv, id: s.kit.id } }">{{ s.kit.nombre }}</RouterLink>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </template>
</template>
