<script setup>
// El header de la app: escudo, nombre, tema claro/oscuro, ACTUALIZAR HORARIOS y SALIR.
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useSesion, useSalir } from '../sesion'
import { useActualizarDesdePlanilla } from '../datos'
import { avisar, avisarError } from '@/avisos'

defineProps({ conAcciones: { type: Boolean, default: true } })

const ESCUDO = import.meta.env.BASE_URL + 'escudo.svg'
const router = useRouter()
const sesion = useSesion()
const salir = useSalir()
const actualizar = useActualizarDesdePlanilla()
const exito = ref(false)

// --- Tema: blueprint (claro) ↔ nocturno. ---------------------------------------------
const TEMA = 'appmitre-theme'
const oscuro = ref(document.body.getAttribute('data-theme') === 'nocturno')
function cambiarTema() {
  oscuro.value = !oscuro.value
  const nombre = oscuro.value ? 'nocturno' : 'blueprint'
  document.body.setAttribute('data-theme', nombre)
  document.body.toggleAttribute('data-dark', oscuro.value)
  try { localStorage.setItem(TEMA, nombre) } catch { /* sin almacenamiento */ }
}

// Rearmar el horario desde la planilla de Google tarda: el botón lo dice mientras tanto.
function actualizarHorarios() {
  actualizar.mutate(undefined, {
    onSuccess: () => {
      exito.value = true
      avisar('Horarios actualizados desde la planilla.')
      setTimeout(() => { exito.value = false }, 2000)
    },
    onError: (e) => avisarError(e, 'No se actualizaron los horarios'),
  })
}

function cerrarSesion() {
  salir.mutate(undefined, { onSettled: () => router.replace({ name: 'entrar' }) })
}
</script>

<template>
  <header class="tech-header">
    <div class="tech-container header-flex">
      <div class="marca">
        <img :src="ESCUDO" alt="Escudo" class="marca-escudo">
        <div class="tech-titles">
          <h1>{{ sesion.data.value?.escuela?.nombre || 'EMILIO MITRE' }} <span class="serial">{{ sesion.data.value?.escuela?.version || '' }}</span></h1>
          <p class="institution">Sistema de Horarios</p>
        </div>
      </div>
      <div class="header-actions">
        <button
          type="button" class="tech-btn-tema" :title="oscuro ? 'Modo claro' : 'Modo nocturno'"
          aria-label="Cambiar tema" @click="cambiarTema"
        >
          <svg v-if="oscuro" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5" /><line x1="12" y1="1" x2="12" y2="3" /><line x1="12" y1="21" x2="12" y2="23" /><line x1="4.22" y1="4.22" x2="5.64" y2="5.64" /><line x1="18.36" y1="18.36" x2="19.78" y2="19.78" /><line x1="1" y1="12" x2="3" y2="12" /><line x1="21" y1="12" x2="23" y2="12" /><line x1="4.22" y1="19.78" x2="5.64" y2="18.36" /><line x1="18.36" y1="5.64" x2="19.78" y2="4.22" /></svg>
          <svg v-else viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" /></svg>
        </button>
        <template v-if="conAcciones">
          <button
            type="button" class="tech-btn-update" :class="{ loading: actualizar.isPending.value }"
            :style="exito ? 'background-color: #28a745; color: #fff;' : ''"
            :disabled="actualizar.isPending.value" @click="actualizarHorarios"
          >
            {{ actualizar.isPending.value ? 'ACTUALIZANDO...' : exito ? '¡ÉXITO!' : 'ACTUALIZAR HORARIOS' }}
          </button>
          <button type="button" class="tech-btn-update" @click="cerrarSesion">SALIR</button>
        </template>
      </div>
    </div>
  </header>
</template>
