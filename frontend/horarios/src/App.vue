<script setup>
// El armado de la app: header, pestañas, la pantalla de turno, la ventana de
// detalle y el pie.
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import Encabezado from './componentes/Encabezado.vue'
import Pestanas from './componentes/Pestanas.vue'
import Ventana from './componentes/Ventana.vue'
import Cartel from './componentes/Cartel.vue'
import AvisoVersion from './componentes/AvisoVersion.vue'
import Avisos from '@/componentes/Avisos.vue'
import EstadoRed from '@/componentes/EstadoRed.vue'

const route = useRoute()
const publica = computed(() => !!route.meta.publica)
</script>

<template>
  <div class="blueprint-bg">
    <Encabezado :con-acciones="!publica" />
    <EstadoRed />
    <div class="tech-container">
      <Pestanas v-if="!publica" />
      <RouterView v-slot="{ Component, route: r }">
        <component :is="Component" :key="r.name" />
      </RouterView>
    </div>
  </div>
  <Ventana />
  <Cartel />
  <footer>
    <p>Programa hecho por Calei | <a href="https://github.com/caleiIGDS/AppMitre" target="_blank" rel="noopener">Repositorio en GitHub</a></p>
  </footer>
  <Avisos />
  <AvisoVersion />
</template>
