<script setup>
// Ficha de un recurso (cabecera con chips,
// fotos a la izquierda, ubicación + kit + detalle a la derecha). Sale de la lista que ya
// está en el dispositivo: abre al instante. La ficha no edita campos ni da de baja: eso
// vive en EDITAR.
import { computed } from 'vue'
import { useRecurso, useMeta, useSubirFoto, useEliminarFoto, useRotarFoto } from '@/gestion/datos'
import { volverA } from '@/navegacion'
import { norm } from '@/texto'
import { avisar, avisarError } from '@/avisos'
import EstadoCarga from '@/componentes/EstadoCarga.vue'
import Galeria from '@/componentes/Galeria.vue'
import UbicacionFicha from './UbicacionFicha.vue'

const props = defineProps({
  inv: { type: String, required: true },
  id: { type: String, required: true },
})
const { consulta, recurso } = useRecurso(() => props.inv, () => props.id)
const meta = useMeta(() => props.inv)
const subirFoto = useSubirFoto(() => props.inv)
const borrarFoto = useEliminarFoto(() => props.inv)
const rotarFoto = useRotarFoto(() => props.inv)

const m = computed(() => meta.data.value || {})
const campos = computed(() => m.value.entidades?.recursos?.campos || [])
const specs = computed(() => campos.value.filter((c) =>
  !['nombre', 'descripcion', 'tipo'].includes(c.nombre) && recurso.value?.[c.nombre]))
const listado = computed(() => ({ name: 'recursos', params: { inv: props.inv } }))

// Sugerencias para "Mover acá": los lugares habituales más todos los que ya se usan en
// este inventario, así un lugar nuevo aparece apenas se carga una vez.
const lugares = computed(() => {
  const todos = new Map()
  const sumar = (l) => { if (l && l !== 'Sin ubicar' && !todos.has(norm(l))) todos.set(norm(l), l) }
  for (const l of m.value.lugares_sugeridos || []) sumar(l)
  for (const r of consulta.data.value || []) for (const g of r.unidades) sumar(g.ubicacion)
  return [...todos.values()].sort((a, b) => norm(a).localeCompare(norm(b)))
})

function subir(archivo) {
  subirFoto.mutate({ id: recurso.value.id, archivo }, {
    onSuccess: () => avisar('Foto agregada.'),
    onError: (e) => avisarError(e, 'No se subió la foto'),
  })
}

function borrar(foto) {
  borrarFoto.mutate({ id: recurso.value.id, foto }, {
    onError: (e) => avisarError(e, 'No se eliminó la foto'),
  })
}

function rotar(foto, imagen) {
  return rotarFoto.mutateAsync({ id: recurso.value.id, foto, imagen })
}
</script>

<template>
  <EstadoCarga :consulta="consulta" que="el recurso" />

  <div v-if="consulta.data.value && !recurso" class="g-empty">
    <p>Este recurso ya no existe.</p>
    <RouterLink class="g-btn" :to="listado">VOLVER AL INVENTARIO</RouterLink>
  </div>

  <div v-else-if="recurso" class="g-ficha-body">
    <div class="g-ficha-col-media">
      <Galeria
        :fotos="recurso.fotos" :puede-editar="!!m.puede_escribir" :puede-rotar="!!m.puede_rotar"
        :subiendo="subirFoto.isPending.value" :rotar="rotar"
        @subir="subir" @borrar="borrar" @error="(e) => avisarError(e, 'No se pudo rotar')"
      />
    </div>

    <header class="g-ficha-head">
      <div class="g-ficha-id">
        <span class="g-ficha-crumb">
          <a :href="`/gestion/${inv}/recursos`" @click.prevent="volverA(listado)">INVENTARIO</a>
          <template v-if="recurso.tipo"> / {{ recurso.tipo }}</template>
        </span>
        <h2 class="g-ficha-title">{{ recurso.nombre }}</h2>
        <div class="g-ficha-chips">
          <span v-if="recurso.estado" class="g-badge">{{ recurso.estado }}</span>
          <span v-if="recurso.valor" class="g-ficha-chip is-valor">{{ recurso.valor }}</span>
          <span v-if="recurso.cantidad" class="g-ficha-chip">{{ recurso.cantidad }} unidades</span>
          <span v-if="recurso.fecha_revision" class="g-ficha-chip">Rev. {{ recurso.fecha_revision }}</span>
        </div>
      </div>
      <div v-if="m.puede_escribir" class="g-ficha-actions">
        <RouterLink class="g-btn" :to="{ name: 'recurso-editar', params: { inv, id: recurso.id } }">EDITAR</RouterLink>
      </div>
    </header>

    <div class="g-ficha-col-main">
      <UbicacionFicha :inv="inv" :recurso="recurso" :puede-editar="!!m.puede_escribir" :lugares="lugares" />

      <template v-if="recurso.kit.length">
        <div class="g-ficha-bar"><span>SUB-RECURSOS (KIT)</span></div>
        <div class="g-ficha-seccion">
          <div class="g-table-wrap">
            <table class="g-table">
              <thead><tr><th>TÍTULO</th><th>CANT.</th><th>RECURSO ASIGNADO</th></tr></thead>
              <tbody>
                <tr v-for="item in recurso.kit" :key="item.id">
                  <td data-label="TÍTULO">{{ item.titulo }}</td>
                  <td data-label="CANT.">{{ item.cantidad }}</td>
                  <td data-label="RECURSO ASIGNADO">{{ item.recurso_asignado }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>

      <div class="g-ficha-bar"><span>Detalle</span></div>
      <div class="g-ficha-detalle">
        <span v-if="recurso.descripcion">{{ recurso.descripcion }}</span>
        <dl class="g-ficha-specs">
          <template v-for="c in specs" :key="c.nombre">
            <dt>{{ c.label }}</dt>
            <dd :class="{ 'g-pre': c.tipo === 'textarea' }">{{ recurso[c.nombre] }}</dd>
          </template>
        </dl>
      </div>
    </div>
  </div>
</template>
