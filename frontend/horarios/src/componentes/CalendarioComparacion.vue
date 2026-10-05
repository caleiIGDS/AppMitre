<script setup>
// Varios horarios superpuestos: cada día se parte en una sub-columna por horario, cada uno
// con su color.
import { computed } from 'vue'
import { rango, bloquesColumna, nombreProfesor, indicadorBloque } from '../calendario'
import { esSeleccionada, verClase, verSuperposicion, mostrarCartel, ocultarCartel } from '../ventanas'

const props = defineProps({
  items: { type: Array, required: true }, // [{modo, valor, filas, color}]
  dias: { type: Array, required: true },
})

const ANCHO = 200
const r = computed(() => rango(props.items.flatMap((i) => i.filas)))
const n = computed(() => props.items.length)
const columnas = computed(() => props.dias.flatMap((dia) => props.items.map((item, k) => ({
  clave: `${dia}-${k}`,
  item,
  ultima: k === n.value - 1,
  bloques: bloquesColumna(item.filas.filter((f) => f.dia === dia), r.value, { modo: item.modo, licenciadaDe: item.valor }),
}))))

const detalle = (c, modo) => (modo === 'profesor' ? `${c.curso}° ${c.division}` : nombreProfesor(c))
const sinNumero = (c, modo) => !/\d/.test(c.aula || '') && modo !== 'aula'
</script>

<template>
  <div v-if="!r" style="padding:20px; text-align:center; color:#70757a;">Sin horarios.</div>
  <div v-else class="comparacion-scroll-wrapper">
    <div
      class="calendario-grid"
      :style="{ gridTemplateColumns: `60px repeat(${n * dias.length}, ${ANCHO}px)`, minWidth: `${60 + n * dias.length * ANCHO}px` }"
    >
      <div class="cabecera-vacia" />
      <div v-for="dia in dias" :key="'d-' + dia" class="cabecera-dia cabecera-dia-grupo" :style="{ gridColumn: `span ${n}` }">{{ dia }}</div>

      <div class="cabecera-entidad-placeholder" />
      <template v-for="dia in dias" :key="'e-' + dia">
        <div v-for="item in items" :key="item.modo + item.valor" class="cabecera-entidad">
          <span class="comp-color-dot" :style="{ background: item.color }" />
          <span class="comp-entity-name" :style="{ color: item.color }">{{ item.valor }}</span>
        </div>
      </template>

      <div class="columna-horas" :style="{ height: r.alto + 'px', position: 'relative' }">
        <div v-for="h in r.horas" :key="h" class="hora-label" :style="{ top: r.y(h) + 'px' }">{{ h }}</div>
      </div>

      <div
        v-for="col in columnas" :key="col.clave" class="columna-dia"
        :style="`height: ${r.alto}px; ${col.ultima ? 'border-right: 2px solid var(--primary);' : 'border-right: 1px dashed rgba(0,0,0,0.15);'}`"
      >
        <div v-for="h in r.horas" :key="h" class="grid-line-horizontal" :style="{ top: r.y(h) + 'px' }" />
        <template v-for="(b, i) in col.bloques" :key="i">
          <div
            v-if="b.tipo === 'superposicion'" class="bloque-superposicion"
            :style="{ top: b.top + 'px', height: b.alto + 'px' }" @click="verSuperposicion(b.clases)"
          >⚠️ Superposición ({{ b.clases.length }})</div>
          <div
            v-else class="materia-bloque" :class="{ selected: esSeleccionada(b.clase) }"
            :style="`top: ${b.top}px; height: ${b.alto}px; ${b.estilo} background-color: ${col.item.color};`"
            @click="verClase(b.clase)" @pointerenter="mostrarCartel($event, b.clase)" @pointerleave="ocultarCartel"
          >
            <div class="materia-contenido">
              <div
                v-if="col.item.modo === 'profesor' && b.clase.suplente_activo == 1" class="materia-nombre"
                style="color:var(--alert);font-weight:bold;display:flex;align-items:center;justify-content:center;height:100%;"
              >LICENCIADA</div>
              <template v-else>
                <div class="materia-nombre">{{ b.clase.materia }}</div>
                <div class="materia-detalles">{{ detalle(b.clase, col.item.modo) }}</div>
              </template>
            </div>
            <div class="aula-indicador" :class="{ 'sin-numero': sinNumero(b.clase, col.item.modo) }">{{ indicadorBloque(b.clase, col.item.modo) }}</div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>
