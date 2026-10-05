<script setup>
// Ficha de un recurso. Sale de la lista que ya está en el dispositivo: abre al instante.
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useRecurso, useMetaGestion, useEliminarRecurso, useSubirFoto, useEliminarFoto } from '@/gestion/datos'
import { volverA } from '@/navegacion'
import { avisar, avisarError } from '@/avisos'
import EstadoCarga from '@/componentes/EstadoCarga.vue'
import Galeria from '@/componentes/Galeria.vue'
import Unidades from './Unidades.vue'
import Kit from './Kit.vue'

const props = defineProps({ id: { type: String, required: true } })
const router = useRouter()
const { consulta, recurso } = useRecurso(() => props.id)
const meta = useMetaGestion()
const eliminar = useEliminarRecurso()
const subirFoto = useSubirFoto()
const borrarFoto = useEliminarFoto()

const puedeEditar = computed(() => !!meta.data.value?.puede_escribir)
const campos = computed(() => (meta.data.value?.entidades?.recursos?.campos || [])
  .filter((c) => c.nombre !== 'nombre' && recurso.value?.[c.nombre]))

const inventario = { name: 'inventario' }

async function borrarRecurso() {
  if (!confirm(`¿Eliminar "${recurso.value.nombre}"? Esta acción no se puede deshacer.`)) return
  try {
    await eliminar.mutateAsync(recurso.value.id)
    avisar('Recurso eliminado.')
    volverA(inventario)
  } catch (e) {
    avisarError(e, 'No se eliminó el recurso')
  }
}

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
</script>

<template>
  <EstadoCarga :consulta="consulta" que="el recurso" />

  <div v-if="consulta.data.value && !recurso" class="g-empty">
    <p>Este recurso ya no existe: puede que lo hayan eliminado.</p>
    <RouterLink class="g-btn" :to="inventario">VOLVER AL INVENTARIO</RouterLink>
  </div>

  <template v-else-if="recurso">
    <div class="g-toolbar">
      <div>
        <span class="g-breadcrumb">
          <a class="g-link" href="/app/gestion/inventario" @click.prevent="volverA(inventario)">INVENTARIO</a> /
        </span>
        <h2>{{ recurso.nombre }}</h2>
      </div>
      <div v-if="puedeEditar" class="g-toolbar-actions">
        <RouterLink class="g-btn-outline-dark" :to="{ name: 'recurso-editar', params: { id: recurso.id } }">EDITAR</RouterLink>
        <button type="button" class="g-btn-danger" :disabled="eliminar.isPending.value" @click="borrarRecurso">ELIMINAR</button>
      </div>
    </div>

    <div class="g-detail">
      <Galeria :fotos="recurso.fotos" :puede-editar="puedeEditar" :subiendo="subirFoto.isPending.value" @subir="subir" @borrar="borrar" />

      <dl class="g-props">
        <div v-for="c in campos" :key="c.nombre" class="g-prop">
          <dt>{{ c.label.toUpperCase() }}</dt>
          <dd v-if="c.nombre === 'estado'"><span class="g-badge">{{ recurso[c.nombre] }}</span></dd>
          <dd v-else :class="{ 'g-pre': c.tipo === 'textarea' }">{{ recurso[c.nombre] }}</dd>
        </div>
        <div v-if="recurso.vencido && recurso.estado !== 'Dado de baja'" class="g-prop">
          <dt>REVISIÓN</dt>
          <dd><span class="g-badge a-badge-alerta">Sin revisar hace más de 6 meses</span></dd>
        </div>
      </dl>

      <div class="g-relations">
        <div class="g-relation-box">
          <h4>UBICACIÓN</h4>
          <Unidades :recurso="recurso" :puede-editar="puedeEditar" :lugares="meta.data.value?.lugares_sugeridos || []" />
        </div>
        <div class="g-relation-box">
          <h4>SUB-RECURSOS (KIT)</h4>
          <Kit :recurso="recurso" :puede-editar="puedeEditar" />
        </div>
      </div>
    </div>
  </template>
</template>
