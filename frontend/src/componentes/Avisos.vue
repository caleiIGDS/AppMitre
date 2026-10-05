<script setup>
import { avisos, cerrarAviso } from '@/avisos'
</script>

<template>
  <div class="a-avisos" role="status" aria-live="polite">
    <TransitionGroup name="a-aviso">
      <div v-for="a in avisos" :key="a.id" class="a-aviso" :class="'a-aviso-' + a.tipo">
        <span>{{ a.texto }}</span>
        <button v-if="a.accion" type="button" class="a-aviso-accion" @click="a.accion.hacer(); cerrarAviso(a.id)">
          {{ a.accion.texto }}
        </button>
        <button type="button" class="a-aviso-cerrar" aria-label="Cerrar" @click="cerrarAviso(a.id)">✕</button>
      </div>
    </TransitionGroup>
  </div>
</template>
