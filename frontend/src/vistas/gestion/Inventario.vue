<script setup>
// El listado de un inventario. Los filtros viven en la URL
// (?q=…&lugar=…&estado=…&meses=…&baja=1): volver atrás, recargar o compartir el link deja
// la lista exactamente como estaba. Todo el filtrado es local, sobre la lista que ya está
// en el dispositivo.
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useRecursos, useMeta } from '@/gestion/datos'
import { norm, puntaje, coincide } from '@/texto'
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

// La búsqueda filtra en vivo, pero a la URL llega con una pausa: si no, cada tecla sería
// una entrada nueva para el navegador. Y el filtro corre a lo sumo una vez por cuadro
// (requestAnimationFrame): si se tipea más rápido que la pantalla, las teclas del medio no
// filtran de más y el campo nunca se traba.
const q = filtro('q')
const busqueda = ref(q.value)
const textoFiltro = ref(q.value.trim())
let espera = null
let cuadro = 0
watch(busqueda, (valor) => {
  clearTimeout(espera)
  espera = setTimeout(() => { q.value = valor.trim() }, 400)
  if (!cuadro) {
    cuadro = requestAnimationFrame(() => {
      cuadro = 0
      textoFiltro.value = busqueda.value.trim()
    })
  }
})
watch(q, (valor) => { if (valor !== busqueda.value.trim()) busqueda.value = valor })
onUnmounted(() => { clearTimeout(espera); cancelAnimationFrame(cuadro) })

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

const qNorm = computed(() => norm(textoFiltro.value))

// Misma jerarquía que la búsqueda del asistente: primero lo que coincide por nombre o
// descripción (en orden alfabético), después lo que coincide sólo por el alias oculto.
const visibles = computed(() => {
  const porNombre = []
  const porAlias = []
  for (const r of pasanFiltros.value) {
    if (coincide(qNorm.value, r._buscar)) porNombre.push(r)
    else if (r._buscar_alias && coincide(qNorm.value, r._buscar_alias)) porAlias.push(r)
  }
  return porNombre.concat(porAlias)
})

// Las fichas que pasan los filtros que no son el texto (ubicación, estado, revisión, baja).
// Los sub-recursos los heredan de su kit: un kit dado de baja no muestra los suyos.
const pasanFiltros = computed(() => {
  const umbral = mesesVivo.value * (m.value.dias_por_mes || 30.5)
  return filas.value.filter((r) => {
    // "Sólo dados de baja" es excluyente; sin él, los dados de baja no aparecen.
    const deBaja = r.estado === ESTADO_BAJA.value
    if (baja.value ? !deBaja : deBaja) return false
    if (lugar.value && !r.unidades.some((g) => g.ubicacion === lugar.value)) return false
    if (estado.value && r.estado !== estado.value) return false
    // dias_revision null = fecha corta sin año: nunca alcanza un umbral > 0.
    return !(umbral > 0 && (r.dias_revision ?? 0) < umbral)
  })
})

// Los títulos de los kits normalizados una vez por lista, no en cada tecla.
const titulosKit = computed(() => {
  const t = new Map()
  for (const r of filas.value) for (const item of r.kit) t.set(item, norm(item.titulo))
  return t
})

// Sólo con una búsqueda escrita: los sub-recursos que coinciden, los mejores primero.
const subrecursos = computed(() => {
  if (!qNorm.value) return []
  const encontrados = []
  for (const kit of pasanFiltros.value) {
    for (const item of kit.kit) {
      const p = puntaje(qNorm.value, titulosKit.value.get(item))
      if (p !== null) encontrados.push({ item, kit, p })
    }
  }
  return encontrados.sort((a, b) => b.p - a.p)
})

// Una sola lista para la tabla: los recursos y, después, los sub-recursos (que abren la
// ficha de su kit: el sub-recurso no tiene una propia).
const lista = computed(() => [
  ...visibles.value.map((r) => ({ clave: `r${r.id}`, r, nombre: r.nombre, cantidad: r.cantidad, tipo: r.tipo, item: null })),
  ...subrecursos.value.map((s, i) => ({ clave: `k${s.item.id}`, r: s.kit, nombre: s.item.titulo, cantidad: s.item.cantidad, tipo: '', item: s.item, primera: i === 0 })),
])

const hayFiltroActivo = computed(() => !!(lugar.value || estado.value || mesesVivo.value > 0 || baja.value))
const hayFiltros = computed(() => !!(qNorm.value || hayFiltroActivo.value))

// --- Panel de filtros en celular ---------------------------------------------------
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
  textoFiltro.value = ''
  router.replace({ query: {} })
}

// --- Dibujar de a tandas -----------------------------------------------------------
// Dibujar cientos de filas de una vez trababa la pantalla un segundo o más en un celular
// (al abrir, o al borrar la búsqueda). Se dibujan las primeras y el resto a medida que el
// centinela del final se acerca a la vista. Un filtro nuevo vuelve a la primera tanda; una
// actualización de los datos no (no le achica la lista a quien ya bajó).
const TANDA = 40
const limite = ref(TANDA)
const mostradas = computed(() => lista.value.slice(0, limite.value))
watch([qNorm, lugar, estado, mesesVivo, baja], () => { limite.value = TANDA })

// El centinela cambia de `key` con cada tanda: el elemento nuevo se observa de cero, así que
// si después de crecer sigue cerca de la vista (pantalla alta), avisa de nuevo y sigue.
let observador = null
function centinela(el) {
  if (!el) return
  observador ||= new IntersectionObserver((entradas) => {
    if (entradas.some((e) => e.isIntersecting)) limite.value += TANDA
  }, { rootMargin: '1200px 0px' })
  observador.disconnect()
  observador.observe(el)
}
onUnmounted(() => observador?.disconnect())

// El link de cada fila es un <a> común, no un RouterLink: con cientos de filas, un
// componente por fila era la mitad del costo de dibujarlas.
const hrefRecurso = (r) => router.resolve({ name: 'recurso', params: { inv: props.inv, id: r.id } }).href

function abrir(r, evento) {
  if (evento.target.closest('button')) return
  const link = evento.target.closest('a')
  // Ctrl/⌘/Shift-click en el nombre: que el navegador lo abra aparte, como cualquier link.
  if (link && (evento.ctrlKey || evento.metaKey || evento.shiftKey || evento.altKey)) return
  if (link) evento.preventDefault()
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

  <!-- En la fila de las pestañas, al lado de INVENTARIO: abajo de la franja lo tapaba el
       desplegable de filtros abierto. Y nada entre la franja y la tabla: en celular el
       listado compacto cuelga de `.g-panel-top + .g-table-wrap`. -->
  <Teleport v-if="hayFiltros" defer to="#nav-acciones">
    <button type="button" class="g-nav-tag a-quitar-filtros" @click="limpiar">✕ QUITAR FILTROS</button>
    <span v-if="recursos.data.value" class="a-filtros-activos">{{ visibles.length }} de {{ totalActivos }}</span>
  </Teleport>

  <EstadoCarga :consulta="recursos" que="el inventario" />

  <template v-if="recursos.data.value">
    <div v-if="lista.length" class="g-table-wrap">
      <table class="g-table">
        <thead>
          <tr><th>RECURSO</th><th>CANT.</th><th>LUGAR ASIGNADO</th><th>ESTADO</th></tr>
        </thead>
        <tbody>
          <!-- Los sub-recursos van al final, en un bloque aparte que abre un divisor naranja.
               Cada uno es la misma fila, con el lugar vacío y, donde va el estado, el recuadro
               naranja con el nombre de su kit; el click abre la ficha del kit. -->
          <template v-for="f in mostradas" :key="f.clave">
          <tr v-if="f.primera" class="a-sep-kits">
            <td colspan="4"><span>SUB-RECURSOS DE KITS</span></td>
          </tr>
          <tr
            data-href
            :class="f.item ? 'a-fila-kit' : { 'g-recurso-baja': f.r.estado === ESTADO_BAJA, 'g-recurso-roto': f.r.estado === 'Roto' }"
            @click="abrir(f.r, $event)"
          >
            <td data-label="RECURSO">
              <a class="g-item-link" :href="hrefRecurso(f.r)">{{ f.nombre }}</a>
              <span v-if="f.tipo" class="g-recurso-sub">{{ f.tipo }}</span>
            </td>
            <td data-label="CANT.">{{ f.cantidad }}</td>
            <!-- Un sub-recurso no muestra lugar: el del kit confundía (no es dónde está él). -->
            <td data-label="LUGAR ASIGNADO">
              <template v-if="f.item" />
              <div v-else-if="f.r.unidades.length > 1" class="g-lugares-multi">
                <span v-for="g in f.r.unidades" :key="g.ubicacion" class="g-lugar-item">{{ g.numeros.length }} x {{ g.ubicacion }}</span>
              </div>
              <template v-else-if="f.r.unidades.length">{{ f.r.unidades[0].ubicacion }}</template>
            </td>
            <!-- En la columna del estado, un sub-recurso lleva de qué kit es (su estado no se muestra). -->
            <td v-if="f.item" data-label="ESTADO"><span class="a-chip-kit" :title="`Es parte del kit ${f.r.nombre}`">{{ f.r.nombre }}</span></td>
            <td v-else data-label="ESTADO" :data-estado="f.r.estado"><span v-if="f.r.estado" class="g-badge">{{ f.r.estado }}</span></td>
          </tr>
          </template>
        </tbody>
      </table>
      <div v-if="mostradas.length < lista.length" :key="limite" :ref="centinela" class="a-centinela" aria-hidden="true" />
    </div>

    <div v-else class="g-empty">
      <template v-if="!filas.length">
        <p>Todavía no hay recursos cargados.</p>
        <RouterLink v-if="m.puede_escribir" class="g-btn" :to="{ name: 'recurso-nuevo', params: { inv } }">+ CREAR EL PRIMERO</RouterLink>
      </template>
      <template v-else>
        <p v-if="textoFiltro">No se encontraron resultados para "{{ textoFiltro }}".</p>
        <p v-else>No se encontraron recursos con ese filtro.</p>
        <button type="button" class="g-btn-outline-dark" @click="limpiar">LIMPIAR FILTROS</button>
      </template>
    </div>
  </template>
</template>
