<script setup>
// El calendario semanal (columnas = días) o la planilla general (columnas = aulas de un
// piso). Las posiciones salen de calendario.js; acá sólo se pintan, con el mismo markup
// que armaba script.js para que horarios.css lo vista igual.
import { computed } from 'vue'
import { rango, bloquesColumna, detalleBloque, indicadorBloque } from '../calendario'
import { esSeleccionada, verClase, verSuperposicion, mostrarCartel, ocultarCartel } from '../ventanas'

const props = defineProps({
  filas: { type: Array, required: true },
  columnas: { type: Array, required: true }, // valores de `campo` (días o aulas)
  campo: { type: String, default: 'dia' },
  modo: { type: String, default: '' },
  variante: { type: String, default: 'horario' }, // 'horario' | 'planilla'
  licenciadaDe: { type: String, default: null },
})

const r = computed(() => rango(props.filas))
const columnas = computed(() => props.columnas.map((col) => ({
  col,
  bloques: r.value
    ? bloquesColumna(props.filas.filter((f) => String(f[props.campo]) === String(col)), r.value, {
      modo: props.modo, variante: props.variante, licenciadaDe: props.licenciadaDe,
    })
    : [],
})))
const plantilla = computed(() => (props.variante === 'planilla'
  ? `grid-template-columns: 60px repeat(${props.columnas.length}, 1fr);`
  : ''))

const esPersonal = (c) => c.tipo === 'personal'
const licenciada = (c) => props.modo === 'profesor' && c.suplente_activo == 1 && c.profesor === props.licenciadaDe
const sinNumero = (c) => !/\d/.test(c.aula || '') && props.modo !== 'aula'
</script>

<template>
  <div v-if="!r" style="padding:20px; text-align:center; color:#70757a;">Los datos no contienen horarios válidos.</div>
  <div v-else class="calendario-grid" :style="plantilla">
    <div class="cabecera-vacia" />
    <div v-for="c in columnas" :key="'cab-' + c.col" class="cabecera-dia">
      <div class="dia-nombre">{{ variante === 'planilla' ? `Aula ${c.col}` : c.col }}</div>
    </div>

    <div class="columna-horas" :style="{ height: r.alto + 'px', position: 'relative' }">
      <div v-for="h in r.horas" :key="h" class="hora-label" :style="{ top: r.y(h) + 'px' }">{{ h }}</div>
    </div>

    <div v-for="c in columnas" :key="'col-' + c.col" class="columna-dia" :style="{ height: r.alto + 'px' }">
      <div v-for="h in r.horas" :key="h" class="grid-line-horizontal" :style="{ top: r.y(h) + 'px' }" />
      <template v-for="(b, i) in c.bloques" :key="i">
        <div
          v-if="b.tipo === 'superposicion'" class="bloque-superposicion"
          :style="{ top: b.top + 'px', height: b.alto + 'px' }" @click="verSuperposicion(b.clases)"
        >⚠️ Superposición ({{ b.clases.length }})</div>

        <div
          v-else-if="variante === 'planilla'" class="materia-bloque"
          :class="{ selected: esSeleccionada(b.clase) }"
          :style="`top: ${b.top}px; height: ${b.alto}px; ${b.estilo}`"
          @click="verClase(b.clase)" @pointerenter="mostrarCartel($event, b.clase)" @pointerleave="ocultarCartel"
        >
          <div class="materia-contenido" style="text-align:center;">
            <div class="materia-nombre" style="font-size:14px;">{{ b.clase.curso }}° {{ b.clase.division }}</div>
          </div>
          <div class="aula-indicador">{{ b.clase.curso }}° {{ b.clase.division }}</div>
        </div>

        <div
          v-else class="materia-bloque"
          :class="{ 'personal-cargo-bloque': esPersonal(b.clase), selected: esSeleccionada(b.clase) }"
          :style="`top: ${b.top}px; height: ${b.alto}px; ${b.estilo}${!esPersonal(b.clase) && licenciada(b.clase) ? ' opacity:0.28;' : ''}`"
          @click="verClase(b.clase)" @pointerenter="mostrarCartel($event, b.clase)" @pointerleave="ocultarCartel"
        >
          <div class="materia-contenido">
            <div class="materia-nombre">{{ b.clase.materia }}</div>
            <div class="materia-detalles">
              {{ esPersonal(b.clase) ? `${b.clase.hora_inicio} - ${b.clase.hora_fin}` : detalleBloque(b.clase, modo) }}
            </div>
          </div>
          <div v-if="!esPersonal(b.clase)" class="aula-indicador" :class="{ 'sin-numero': sinNumero(b.clase) }">
            {{ indicadorBloque(b.clase, modo) }}
          </div>
        </div>
      </template>
    </div>
  </div>
</template>
