<script setup>
// El inventario. Los filtros viven en la URL (?q=…&lugar=…&vencidos=1&baja=1): volver
// atrás, recargar o compartir el link deja la lista exactamente como estaba. Todo el
// filtrado es local, sobre la lista que ya está en el dispositivo.
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useRecursos, useMetaGestion } from '@/gestion/datos'
import { norm, puntaje } from '@/texto'
import EstadoCarga from '@/componentes/EstadoCarga.vue'

const route = useRoute()
const router = useRouter()
const recursos = useRecursos()
const meta = useMetaGestion()

// --- Filtros ↔ URL -------------------------------------------------------------------
function filtro(clave) {
  return computed({
    get: () => (typeof route.query[clave] === 'string' ? route.query[clave] : ''),
    set: (valor) => {
      const query = { ...route.query, [clave]: valor || undefined }
      router.replace({ query })
    },
  })
}
const lugar = filtro('lugar')
const vencidos = filtro('vencidos')
const baja = filtro('baja')

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

// --- Datos derivados -----------------------------------------------------------------
const filas = computed(() => recursos.data.value || [])

const lugares = computed(() => {
  const todos = new Set()
  for (const r of filas.value) for (const g of r.unidades) if (g.ubicacion !== 'Sin ubicar') todos.add(g.ubicacion)
  return [...todos].sort((a, b) => norm(a).localeCompare(norm(b)))
})

const cantidadVencidos = computed(() =>
  filas.value.filter((r) => r.vencido && r.estado !== 'Dado de baja').length)
const totalActivos = computed(() => filas.value.filter((r) => r.estado !== 'Dado de baja').length)

const qNorm = computed(() => norm(q.value))

const visibles = computed(() => {
  const resultado = []
  for (const r of filas.value) {
    if (r.estado === 'Dado de baja' && !baja.value) continue
    if (vencidos.value && !r.vencido) continue
    if (lugar.value && !r.unidades.some((g) => g.ubicacion === lugar.value)) continue
    const p = puntaje(qNorm.value, r._buscar)
    if (p === null) continue
    resultado.push({ r, p })
  }
  if (qNorm.value) resultado.sort((a, b) => b.p - a.p)
  return resultado.map((x) => x.r)
})

// Sub-recursos de kits que coinciden con la búsqueda: el listado nunca los muestra
// sueltos sin buscar (mismo criterio que la versión clásica).
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

const hayFiltros = computed(() => !!(q.value || lugar.value || vencidos.value))

function limpiar() {
  busqueda.value = ''
  router.replace({ query: {} })
}

function abrir(r, evento) {
  if (evento.target.closest('a, button')) return
  router.push({ name: 'recurso', params: { id: r.id } })
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
        <RouterLink v-if="meta.data.value?.puede_escribir" class="g-btn" :to="{ name: 'recurso-nuevo' }">+ CREAR RECURSO</RouterLink>
      </div>
    </div>

    <div v-if="filas.length" class="g-filtros">
      <span class="g-filtros-label">Filtros</span>
      <select v-if="lugares.length" v-model="lugar" class="g-filtro-select" aria-label="Filtrar por ubicación">
        <option value="">Ubicación: todas</option>
        <option v-for="l in lugares" :key="l" :value="l">{{ l }}</option>
      </select>
      <span class="g-filtro-spacer" />
      <button type="button" class="g-chip-vencidos" :aria-pressed="!!vencidos" @click="vencidos = vencidos ? '' : '1'">
        Sin revisar hace +6 meses <span>{{ cantidadVencidos }}</span>
      </button>
      <button type="button" class="g-chip-vencidos" :aria-pressed="!!baja" @click="baja = baja ? '' : '1'">
        Mostrar dados de baja
      </button>
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
            :class="{ 'g-recurso-baja': r.estado === 'Dado de baja' }"
            @click="abrir(r, $event)"
          >
            <td data-label="RECURSO">
              <RouterLink class="g-item-link" :to="{ name: 'recurso', params: { id: r.id } }">{{ r.nombre }}</RouterLink>
              <span v-if="r.tipo" class="g-recurso-sub">{{ r.tipo }}</span>
            </td>
            <td data-label="CANT.">{{ r.cantidad }}</td>
            <td data-label="LUGAR ASIGNADO">
              <div v-if="r.unidades.length > 1" class="g-lugares-multi">
                <span v-for="g in r.unidades" :key="g.ubicacion" class="g-lugar-item">{{ g.numeros.length }} x {{ g.ubicacion }}</span>
              </div>
              <template v-else-if="r.unidades.length">{{ r.unidades[0].ubicacion }}</template>
            </td>
            <td data-label="ESTADO"><span v-if="r.estado" class="g-badge">{{ r.estado }}</span></td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-else-if="!subrecursos.length" class="g-empty">
      <template v-if="!filas.length">
        <p>Todavía no hay recursos cargados.</p>
        <RouterLink v-if="meta.data.value?.puede_escribir" class="g-btn" :to="{ name: 'recurso-nuevo' }">+ CREAR EL PRIMERO</RouterLink>
      </template>
      <template v-else>
        <p v-if="q">No se encontraron resultados para "{{ q }}".</p>
        <p v-else>No hay recursos con ese filtro.</p>
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
            <tr
              v-for="s in subrecursos" :key="s.item.id" data-href
              @click="abrir(s.kit, $event)"
            >
              <td data-label="SUB-RECURSO">{{ s.item.titulo }}</td>
              <td data-label="CANT.">{{ s.item.cantidad }}</td>
              <td data-label="RECURSO ASIGNADO">{{ s.item.recurso_asignado }}</td>
              <td data-label="KIT">
                <RouterLink class="g-item-link" :to="{ name: 'recurso', params: { id: s.kit.id } }">{{ s.kit.nombre }}</RouterLink>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </template>
</template>
