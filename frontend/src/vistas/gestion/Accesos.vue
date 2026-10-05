<script setup>
// Panel del ENCARGADO: quién entra a ESTE inventario. Es el hermano acotado de /accesos:
// todo lleva el ámbito del inventario (ver gestion.py, "Quién entra a ESTE inventario").
// Los permisos que reparte son los de este inventario, los dispositivos que lista son los
// que tienen alguno, y QUITAR saca los de acá y ninguno más.
import { reactive, ref, watch } from 'vue'
import { useAccesos, useInvitar, useQuitarDispositivo, useAnularInvitacion, useMeta } from '@/gestion/datos'
import { avisar, avisarError } from '@/avisos'
import EstadoCarga from '@/componentes/EstadoCarga.vue'

const props = defineProps({ inv: { type: String, required: true } })
const consulta = useAccesos(() => props.inv)
const meta = useMeta(() => props.inv)
const invitar = useInvitar(() => props.inv)
const quitar = useQuitarDispositivo(() => props.inv)
const anular = useAnularInvitacion(() => props.inv)

const form = reactive({ etiqueta: '', perfil: 'interno-lectura', permisos: [], multiuso: false })
const nuevo = ref(null) // { link, multiuso }
const copiado = ref(false)

// Los niveles son atajos: marcan los permisos. Si se toca uno a mano, el servidor lo guarda
// como "a medida".
function aplicarPerfil(clave) {
  const p = consulta.data.value?.perfiles.find((x) => x.clave === clave)
  form.permisos = p ? [...p.permisos] : []
}
watch(() => consulta.data.value, (d) => { if (d && !form.permisos.length) aplicarPerfil(form.perfil) }, { immediate: true })

function generar() {
  invitar.mutate({ ...form }, {
    onSuccess: (r) => {
      nuevo.value = r
      copiado.value = false
      form.etiqueta = ''
    },
    onError: (e) => avisarError(e, 'No se generó el link'),
  })
}

async function copiar() {
  try {
    await navigator.clipboard.writeText(nuevo.value.link)
    copiado.value = true
  } catch {
    avisar('No se pudo copiar: mantené apretado el link para copiarlo.', { tipo: 'error' })
  }
}

function quitarA(d) {
  if (!confirm(`¿Sacarle a ${d.nombre} el acceso a este inventario? Deja de entrar en el acto.`)) return
  quitar.mutate(d.id, {
    onSuccess: () => avisar(`${d.nombre} ya no entra a este inventario.`),
    onError: (e) => avisarError(e, 'No se quitó'),
  })
}

function anularLink(i) {
  if (i.multiuso && !confirm('¿Anular este link público? Nadie más va a poder entrar con él; los que ya entraron siguen.')) return
  anular.mutate(i.id, { onError: (e) => avisarError(e, 'No se anuló') })
}
</script>

<template>
  <div class="g-toolbar">
    <h2>QUIÉN ENTRA A {{ (meta.data.value?.inventario?.nombre || '').toUpperCase() }}</h2>
    <div class="g-toolbar-actions">
      <RouterLink class="g-btn-outline-dark" :to="{ name: 'recursos', params: { inv } }">‹ INVENTARIO</RouterLink>
    </div>
  </div>

  <EstadoCarga :consulta="consulta" que="los accesos" />

  <template v-if="consulta.data.value">
    <div v-if="nuevo" class="g-card a-link-nuevo">
      <template v-if="nuevo.multiuso">
        <h3>LINK PÚBLICO LISTO — COMPARTILO DONDE HAGA FALTA</h3>
        <p class="g-help">Lo puede abrir <strong>cualquiera</strong>, todas las veces que quiera:
          no se quema. Cada uno escribe su nombre y queda un acceso nuevo a este inventario. Para
          anularlo, "ANULAR" en la lista de abajo.</p>
      </template>
      <template v-else>
        <h3>LINK LISTO — MANDÁSELO A LA PERSONA</h3>
        <p class="g-help">Sirve <strong>una sola vez</strong> y vence en 7 días. Al abrirlo va a
          escribir su nombre y queda habilitado ese dispositivo, sólo para este inventario.</p>
      </template>
      <div class="g-field">
        <input type="text" readonly :value="nuevo.link" style="width: 100%;" @focus="$event.target.select()">
      </div>
      <button class="g-btn" type="button" @click="copiar">{{ copiado ? 'COPIADO ✓' : 'COPIAR LINK' }}</button>
    </div>

    <div class="g-table-wrap">
      <table class="g-table">
        <thead>
          <tr><th>QUIÉN DIJO SER</th><th>ETIQUETA</th><th>ACCESO ACÁ</th><th>DISPOSITIVO</th><th>ÚLTIMO USO</th><th /></tr>
        </thead>
        <tbody>
          <tr v-for="d in consulta.data.value.dispositivos" :key="d.id" :style="d.revocado ? 'opacity: .5' : ''">
            <td data-label="QUIÉN">{{ d.nombre }}</td>
            <td data-label="ETIQUETA">{{ d.etiqueta || '—' }}</td>
            <td data-label="ACCESO">{{ d.perfil_etiqueta }}<template v-if="d.revocado"> · REVOCADO</template></td>
            <td data-label="DISPOSITIVO">{{ d.dispositivo }}</td>
            <td data-label="ÚLTIMO USO">{{ d.ultimo_uso ? d.ultimo_uso.slice(0, 16) : 'nunca' }}</td>
            <td>
              <button v-if="!d.revocado" class="g-btn-outline" type="button" :disabled="quitar.isPending.value" @click="quitarA(d)">QUITAR</button>
            </td>
          </tr>
          <tr v-if="!consulta.data.value.dispositivos.length">
            <td colspan="6" class="g-help">Todavía no habilitaste a nadie. Los únicos que entran son
              los que tienen la clave de este inventario.</td>
          </tr>
        </tbody>
      </table>
    </div>

    <template v-if="consulta.data.value.invitaciones.length">
      <div class="g-toolbar a-seccion"><h2>LINKS ACTIVOS</h2></div>
      <div class="g-table-wrap">
        <table class="g-table">
          <thead><tr><th>PARA QUIÉN</th><th>ACCESO</th><th>TIPO</th><th>VENCE</th><th /></tr></thead>
          <tbody>
            <tr v-for="i in consulta.data.value.invitaciones" :key="i.id">
              <td data-label="PARA QUIÉN">{{ i.etiqueta }}</td>
              <td data-label="ACCESO">{{ i.perfil_etiqueta }}</td>
              <td data-label="TIPO">
                <template v-if="i.multiuso">Público · {{ i.usos }} dispositivo{{ i.usos !== 1 ? 's' : '' }}</template>
                <template v-else>Un solo uso, sin usar</template>
              </td>
              <td data-label="VENCE">{{ (i.expira || '').slice(0, 10) }}</td>
              <td><button class="g-btn-outline" type="button" :disabled="anular.isPending.value" @click="anularLink(i)">ANULAR</button></td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <div class="g-toolbar a-seccion"><h2>HABILITAR A ALGUIEN NUEVO</h2></div>
    <form class="g-form" @submit.prevent="generar">
      <div class="g-field">
        <label for="campo-etiqueta">PARA QUIÉN ES</label>
        <input id="campo-etiqueta" v-model="form.etiqueta" type="text" required placeholder="alumna 5°B, pañol, profe de taller…">
        <span class="g-help">Es tu nota, no la ve la persona. Ella escribe su nombre al abrir el
          link, y acá vas a ver los dos: si no coinciden, el link se reenvió.</span>
      </div>
      <div class="g-field">
        <label>NIVEL DE ACCESO</label>
        <label v-for="p in consulta.data.value.perfiles" :key="p.clave" style="display: block; font-weight: normal;">
          <input v-model="form.perfil" type="radio" :value="p.clave" @change="aplicarPerfil(p.clave)">
          {{ p.etiqueta }}
        </label>
        <span class="g-help">Son atajos: marcan los permisos de abajo. Si tocás alguno a mano, el
          acceso queda "a medida".</span>
      </div>
      <div class="g-field">
        <label>PERMISOS EN ESTE INVENTARIO</label>
        <label v-for="p in consulta.data.value.permisos" :key="p.clave" style="display: block; font-weight: normal;">
          <input v-model="form.permisos" type="checkbox" :value="p.clave"> {{ p.etiqueta }}
        </label>
      </div>
      <div class="g-field">
        <label style="display: block; font-weight: normal;">
          <input v-model="form.multiuso" type="checkbox">
          SIN LÍMITE DE USOS — cualquiera que abra el link entra, no sólo la primera persona
        </label>
        <span class="g-help">Para un cartel o un grupo, no para una persona puntual: no se quema
          al usarlo y no vence a los 7 días.</span>
      </div>
      <div class="g-form-actions">
        <button type="submit" class="g-btn" :disabled="invitar.isPending.value">GENERAR LINK</button>
      </div>
    </form>
  </template>
</template>
