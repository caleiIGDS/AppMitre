<script setup>
import Encabezado from './componentes/Encabezado.vue'
import NavArea from './componentes/NavArea.vue'
import Avisos from './componentes/Avisos.vue'
import AvisoVersion from './componentes/AvisoVersion.vue'
import EstadoRed from './componentes/EstadoRed.vue'
</script>

<template>
  <div class="g-bg">
    <Encabezado />
    <EstadoRed />
    <div class="g-container g-shell">
      <NavArea />
      <main class="g-main">
        <RouterView v-slot="{ Component, route }">
          <component :is="Component" :key="route.name + ':' + (route.params.id || '')" />
        </RouterView>
      </main>
    </div>
    <footer class="g-footer">
      <p>Programa hecho por Calei | <a href="https://github.com/caleiIGDS/AppMitre" target="_blank" rel="noopener">Repositorio en GitHub</a></p>
    </footer>
  </div>
  <Avisos />
  <AvisoVersion />
</template>
