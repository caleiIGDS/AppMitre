<script setup>
// La lista de inventarios (templates/inventarios/panel.html): los que esta sesión abre, y
// para los otros, entrar con su clave. Crear, renombrar, poner clave y eliminar siguen en
// la página clásica (/gestion/), sólo para administración.
import { useInventarios } from '@/gestion/datos'
import EstadoCarga from '@/componentes/EstadoCarga.vue'

const consulta = useInventarios()
</script>

<template>
  <div class="g-toolbar">
    <h2>INVENTARIOS</h2>
  </div>

  <div v-if="consulta.error.value?.status === 401" class="g-empty">
    <p>Para ver la lista de inventarios hace falta entrar.</p>
    <p class="g-help">Si sos encargado de un inventario, entrá por la dirección de tu
      inventario y poné su clave. Si te habilitaron por link, abrilo en este dispositivo.</p>
    <RouterLink class="g-btn" :to="{ name: 'entrar', query: { volver: '/gestion' } }">ENTRAR COMO ADMINISTRACIÓN</RouterLink>
  </div>

  <template v-else>
    <EstadoCarga :consulta="consulta" que="los inventarios" />

    <template v-if="consulta.data.value">
      <p class="g-help">Cada inventario es independiente: tiene su propia gente y su propia
        clave. Tener acceso a uno no da acceso a ninguno de los otros.</p>

      <div v-if="consulta.data.value.puede_administrar" class="g-nuevo-inv">
        <a class="g-btn-outline-dark" href="/gestion/">ADMINISTRAR INVENTARIOS ›</a>
      </div>

      <div class="g-cards">
        <div v-for="i in consulta.data.value.inventarios" :key="i.slug" class="g-card">
          <div class="g-card-head">
            <h3>{{ i.nombre.toUpperCase() }}</h3>
            <span class="g-count">{{ i.total < 0 ? '—' : i.total }}</span>
          </div>
          <p v-if="i.sin_clave" class="g-error">Todavía no tiene clave: sólo entra administración.</p>
          <!-- `clave` sólo viene para el admin general. -->
          <p v-else-if="'clave' in i" class="g-help">
            CLAVE: <code v-if="i.clave">{{ i.clave }}</code>
            <template v-else>no se puede mostrar (se puso antes de que se guardaran visibles):
              volvé a ponerla en ADMINISTRAR INVENTARIOS, puede ser la misma.</template>
          </p>
          <div class="g-card-actions">
            <RouterLink v-if="i.abre" class="g-btn" :to="{ name: 'recursos', params: { inv: i.slug } }">ABRIR</RouterLink>
            <RouterLink v-else-if="!i.sin_clave" class="g-btn-outline-dark" :to="{ name: 'inventario-entrar', params: { inv: i.slug } }">ENTRAR CON CLAVE</RouterLink>
          </div>
        </div>
        <p v-if="!consulta.data.value.inventarios.length" class="g-help">Todavía no hay ningún inventario.</p>
      </div>
    </template>
  </template>
</template>
