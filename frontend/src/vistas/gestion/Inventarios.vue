<script setup>
// La lista de inventarios: los que esta sesión abre, y para los otros, entrar con su clave.
// Para administración (`inventarios.admin`) además es el tablero de la lista: crear,
// renombrar, ver y cambiar la clave, y eliminar. El orden de las tarjetas se elige
// arrastrándolas (orden.js, de cada dispositivo).
import { ref, reactive, computed } from 'vue'
import { useRouter } from 'vue-router'
import {
  useInventarios, useCrearInventario, useCambiarInventario, useEliminarInventario,
} from '@/gestion/datos'
import { avisar, avisarError } from '@/avisos'
import EstadoCarga from '@/componentes/EstadoCarga.vue'
import { useOrdenable } from '@/orden'

const router = useRouter()
const consulta = useInventarios()
const crear = useCrearInventario()
const cambiar = useCambiarInventario()
const eliminar = useEliminarInventario()

const tarjetas = ref(null)
const { items: inventarios, arrastrando } = useOrdenable(
  computed(() => 'inventarios'), tarjetas,
  computed(() => consulta.data.value?.inventarios || []), (i) => i.slug)

// --- Nuevo inventario: un <dialog>, lo de todos los días acá es mirar la lista. ---------
const dialogo = ref(null)
const nuevo = reactive({ nombre: '', clave: '' })
function abrirNuevo() {
  nuevo.nombre = ''
  nuevo.clave = ''
  dialogo.value?.showModal()
}
function crearInventario() {
  crear.mutate({ ...nuevo }, {
    onSuccess: (r) => {
      dialogo.value?.close()
      avisar(`Inventario "${nuevo.nombre}" creado.`)
      router.push({ name: 'recursos', params: { inv: r.slug } })
    },
    onError: (e) => avisarError(e, 'No se creó'),
  })
}

// --- Administrar uno: los campos de cada tarjeta, por id. ------------------------------
const campos = reactive({})
const de = (i) => (campos[i.id] ||= { nombre: i.nombre, clave: '', confirmar: '' })

function renombrar(i) {
  cambiar.mutate({ id: i.id, nombre: de(i).nombre }, {
    onSuccess: () => avisar('Nombre guardado.'),
    onError: (e) => avisarError(e, 'No se guardó el nombre'),
  })
}

function ponerClave(i) {
  cambiar.mutate({ id: i.id, clave: de(i).clave }, {
    onSuccess: () => { de(i).clave = ''; avisar('Clave guardada. Quien entró con la anterior queda afuera.') },
    onError: (e) => avisarError(e, 'No se guardó la clave'),
  })
}

function eliminarInventario(i) {
  if (!confirm(`¿Eliminar ${i.nombre}? Se borran sus recursos, sus fotos y los accesos que daba.`)) return
  eliminar.mutate({ id: i.id, confirmar: de(i).confirmar }, {
    onSuccess: () => avisar(`"${i.nombre}" eliminado (queda su último respaldo).`),
    onError: (e) => avisarError(e, 'No se eliminó'),
  })
}
</script>

<template>
  <div class="g-toolbar">
    <h2>INVENTARIOS</h2>
  </div>

  <div v-if="consulta.error.value?.status === 401" class="g-empty">
    <p>Para ver la lista de inventarios hace falta entrar.</p>
    <p class="g-help">Si sos encargado de un inventario, entrá por la dirección de tu
      inventario y poné su clave. Si te habilitaron por link, abrilo en este dispositivo.</p>
    <RouterLink class="g-btn" :to="{ name: 'entrar', query: { volver: '/inventarios' } }">ENTRAR COMO ADMINISTRACIÓN</RouterLink>
  </div>

  <template v-else>
    <EstadoCarga :consulta="consulta" que="los inventarios" />

    <template v-if="consulta.data.value">
      <p class="g-help">Cada inventario es independiente: tiene su propia gente y su propia
        clave. Tener acceso a uno no da acceso a ninguno de los otros.</p>
      <p v-if="inventarios.length > 1" class="a-orden-ayuda">Mantené apretado un inventario y
        arrastralo para cambiar el orden (en este dispositivo).</p>

      <div v-if="consulta.data.value.puede_administrar" class="g-nuevo-inv">
        <button type="button" class="g-btn" @click="abrirNuevo">+ NUEVO INVENTARIO</button>
      </div>

      <div ref="tarjetas" class="g-cards">
        <div
          v-for="i in inventarios" :key="i.slug" class="g-card a-ordenable"
          :class="{ 'a-levantado': arrastrando === i.slug }" :data-orden="i.slug"
        >
          <div class="g-card-head">
            <h3>{{ i.nombre.toUpperCase() }}</h3>
            <span class="g-count">{{ i.total < 0 ? '—' : i.total }}</span>
          </div>
          <p v-if="i.sin_clave" class="g-error">Todavía no tiene clave: sólo entra administración.</p>
          <!-- `clave` sólo viene para el admin general. -->
          <p v-else-if="'clave' in i" class="g-help">
            CLAVE: <code v-if="i.clave">{{ i.clave }}</code>
            <template v-else>no se puede mostrar (se puso antes de que se guardaran visibles):
              volvé a ponerla en ADMINISTRAR, puede ser la misma.</template>
          </p>
          <div class="g-card-actions">
            <RouterLink v-if="i.abre" class="g-btn" :to="{ name: 'recursos', params: { inv: i.slug } }">ABRIR</RouterLink>
            <RouterLink v-else-if="!i.sin_clave" class="g-btn-outline-dark" :to="{ name: 'inventario-entrar', params: { inv: i.slug } }">ENTRAR CON CLAVE</RouterLink>
          </div>

          <details v-if="consulta.data.value.puede_administrar" class="g-card-desc">
            <summary>ADMINISTRAR</summary>

            <form class="g-form" @submit.prevent="renombrar(i)">
              <div class="g-field">
                <label :for="`nombre-${i.id}`">NOMBRE</label>
                <input :id="`nombre-${i.id}`" v-model="de(i).nombre" type="text" required>
                <span class="g-help">La dirección (<code>/gestion/{{ i.slug }}</code>) no cambia:
                  los links que ya circulan siguen andando.</span>
              </div>
              <div class="g-form-actions">
                <button type="submit" class="g-btn-outline" :disabled="cambiar.isPending.value">GUARDAR NOMBRE</button>
              </div>
            </form>

            <form class="g-form" @submit.prevent="ponerClave(i)">
              <div class="g-field">
                <label :for="`clave-${i.id}`">CLAVE DEL INVENTARIO</label>
                <input :id="`clave-${i.id}`" v-model="de(i).clave" type="text" required placeholder="la clave del encargado">
                <span class="g-help">Se la pasás al encargado y con eso entra. Ponerle una nueva
                  deja afuera a quien haya entrado con la anterior.</span>
              </div>
              <div class="g-form-actions">
                <button type="submit" class="g-btn-outline" :disabled="cambiar.isPending.value">
                  {{ i.sin_clave ? 'PONER CLAVE' : 'CAMBIAR CLAVE' }}
                </button>
              </div>
            </form>

            <form class="g-form" @submit.prevent="eliminarInventario(i)">
              <div class="g-field">
                <label :for="`borrar-${i.id}`">ELIMINAR</label>
                <input :id="`borrar-${i.id}`" v-model="de(i).confirmar" type="text" required :placeholder="`escribí: ${i.nombre}`">
                <span class="g-help">Para eliminarlo, escribí su nombre tal cual. Se borra todo lo
                  de adentro; queda el último respaldo.</span>
              </div>
              <div class="g-form-actions">
                <button type="submit" class="g-btn-outline-dark" :disabled="eliminar.isPending.value">ELIMINAR INVENTARIO</button>
              </div>
            </form>
          </details>
        </div>
        <p v-if="!consulta.data.value.inventarios.length" class="g-help">Todavía no hay ningún inventario.</p>
      </div>
    </template>
  </template>

  <dialog ref="dialogo" class="g-modal">
    <form class="g-modal-form" @submit.prevent="crearInventario">
      <div class="g-modal-head">
        <h3>NUEVO INVENTARIO</h3>
        <button type="button" class="g-modal-close" aria-label="Cerrar" @click="dialogo.close()">&times;</button>
      </div>
      <div class="g-field">
        <label for="campo-nombre-nuevo">NOMBRE</label>
        <input id="campo-nombre-nuevo" v-model="nuevo.nombre" type="text" required placeholder="Taller de Electrónica, Laboratorio, Pañol…">
      </div>
      <div class="g-field">
        <label for="campo-clave-nuevo">CLAVE PARA EL ENCARGADO</label>
        <input id="campo-clave-nuevo" v-model="nuevo.clave" type="text" required>
        <span class="g-help">Con esta clave el encargado entra al inventario y decide quién más entra.</span>
      </div>
      <div class="g-modal-actions">
        <button type="submit" class="g-btn" :disabled="crear.isPending.value">CREAR INVENTARIO</button>
      </div>
    </form>
  </dialog>
</template>
