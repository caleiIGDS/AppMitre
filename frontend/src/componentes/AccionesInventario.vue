<script setup>
// Las acciones del header de un inventario abierto, las mismas que templates/gestion/base.html.
// "Quién entra" es el panel del encargado, que sigue siendo página clásica.
defineProps({
  inv: { type: String, required: true },
  meta: { type: Object, required: true },
})
</script>

<template>
  <RouterLink class="g-btn-outline" :to="{ name: 'inventarios' }">‹ INVENTARIOS</RouterLink>
  <a v-if="meta.puede_accesos" class="g-btn-outline" :href="`/gestion/${inv}/accesos`">🔑 QUIÉN ENTRA</a>
  <RouterLink v-if="meta.puede_alias" class="g-btn-outline" :to="{ name: 'alias', params: { inv } }">ALIAS</RouterLink>
  <RouterLink v-if="meta.puede_auditoria" class="g-btn-outline" :to="{ name: 'bajas', params: { inv } }">BAJAS</RouterLink>
</template>
