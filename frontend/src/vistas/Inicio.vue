<script setup>
import { computed } from 'vue'
import { useSesion } from '@/sesion'
import { areasVisibles } from '@/areas'

const { acceso, areas, puede } = useSesion()
const lista = computed(() => areasVisibles(areas.value, puede))
</script>

<template>
  <div class="g-toolbar">
    <h2>{{ acceso ? `HOLA, ${acceso.nombre.toUpperCase()}` : 'SISTEMA DE GESTIÓN' }}</h2>
  </div>
  <div class="g-cards">
    <div v-for="a in lista" :key="a.clave" class="g-card">
      <div class="g-card-head">
        <h3>{{ a.nombre.toUpperCase() }}</h3>
        <span v-if="!a.ruta" class="a-etiqueta" title="Todavía abre la versión de páginas clásicas">CLÁSICA</span>
      </div>
      <p class="g-card-desc">{{ a.descripcion }}</p>
      <div class="g-card-actions">
        <RouterLink v-if="a.ruta" class="g-btn" :to="a.ruta">ENTRAR</RouterLink>
        <a v-else class="g-btn-outline-dark" :href="a.href">ABRIR</a>
      </div>
    </div>
  </div>
  <p v-if="!acceso" class="g-help a-ayuda-inicio">
    Si te habilitaron por link, abrilo en este dispositivo. Si sos encargado de un inventario,
    entrá por la dirección de tu inventario y poné su clave. Administración:
    <RouterLink class="g-link" :to="{ name: 'entrar' }">entrar con la contraseña</RouterLink>.
  </p>
</template>
