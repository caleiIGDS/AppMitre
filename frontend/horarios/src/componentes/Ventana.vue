<script setup>
// La ventana de detalle de /horarios (#modal-detalles): una clase, una superposición o
// elegir cursos para imprimir. Tocar un profesor, curso o aula lleva a su horario.
import { computed, onMounted, onUnmounted } from 'vue'
import { ventana, cerrarVentana } from '../ventanas'
import { useIrA } from '../navegar'
import { nombreProfesor } from '../calendario'
import ImprimirCursos from './ImprimirCursos.vue'

const irA = useIrA()
const titulo = computed(() => ({
  clase: 'Información de la Clase',
  superposicion: '⚠️ Superposición Detectada',
  imprimir: 'IMPRIMIR HORARIOS',
}[ventana.tipo] || ''))

const c = computed(() => ventana.clase)
const suplente = computed(() => c.value?.suplente_activo == 1)
const cursoTexto = computed(() => {
  if (!c.value) return ''
  const g = c.value.grupo && String(c.value.grupo).trim()
  return `${c.value.curso}° ${c.value.division}${g ? ` (Grupo: ${g})` : ''}`
})

function ir(modo, valor) {
  cerrarVentana()
  irA(modo, valor)
}

const alTeclear = (e) => { if (e.key === 'Escape' && ventana.tipo) cerrarVentana() }
onMounted(() => document.addEventListener('keydown', alTeclear))
onUnmounted(() => document.removeEventListener('keydown', alTeclear))
</script>

<template>
  <div v-if="ventana.tipo" class="modal-detalles" style="display: flex;" @click.self="cerrarVentana">
    <div class="modal-contenido" role="dialog" aria-modal="true" :aria-label="titulo">
      <div class="modal-header">
        <span>{{ titulo }}</span>
        <button type="button" class="btn-cerrar-modal" aria-label="Cerrar" @click="cerrarVentana">&times;</button>
      </div>

      <div v-if="ventana.tipo === 'clase' && c" class="info-card">
        <div class="info-label">Materia</div>
        <div class="info-valor">{{ c.materia }}</div>
        <template v-if="c.tipo !== 'personal'">
          <div class="info-label">{{ suplente ? 'Suplente' : 'Profesor' }}</div>
          <div class="clickable-valor" @click="ir('profesor', suplente ? c.prof_suplente : c.profesor)">
            {{ suplente ? `${c.prof_suplente} (desde ${c.sup_ini} hasta ${c.sup_fin})` : c.profesor }}
          </div>
          <div class="info-label">Curso</div>
          <div class="clickable-valor" @click="ir('curso', `${c.curso}° ${c.division}`)">{{ cursoTexto }}</div>
          <div class="info-label">Aula</div>
          <div class="clickable-valor" @click="ir('aula', c.aula)">{{ c.aula || '-' }}</div>
        </template>
        <template v-else>
          <div class="info-label">Nombre</div>
          <div class="info-valor">{{ c.profesor }}</div>
        </template>
        <div class="info-label">Horario</div>
        <div class="info-valor">{{ c.hora_inicio }} - {{ c.hora_fin }} ({{ c.dia }})</div>
      </div>

      <template v-else-if="ventana.tipo === 'superposicion'">
        <p style="margin-bottom:15px; color:#5f6368;">Se han detectado las siguientes clases en el mismo horario:</p>
        <div v-for="(s, i) in ventana.clases" :key="i" class="info-card overlap">
          <div class="info-label">Materia</div>
          <div class="info-valor">{{ s.materia }}</div>
          <div class="info-label">Profesor</div>
          <div class="clickable-valor" @click="ir('profesor', s.suplente_activo == 1 ? s.prof_suplente : s.profesor)">{{ nombreProfesor(s) }}</div>
          <div class="info-label">Curso</div>
          <div class="clickable-valor" @click="ir('curso', `${s.curso}° ${s.division}`)">{{ s.curso }}° {{ s.division }}</div>
          <div class="info-label">Aula</div>
          <div class="clickable-valor" @click="ir('aula', s.aula)">{{ s.aula || '-' }}</div>
          <div class="info-label">Horario</div>
          <div class="info-valor">{{ s.hora_inicio }} - {{ s.hora_fin }}</div>
        </div>
      </template>

      <ImprimirCursos v-else-if="ventana.tipo === 'imprimir'" />
    </div>
  </div>
</template>
