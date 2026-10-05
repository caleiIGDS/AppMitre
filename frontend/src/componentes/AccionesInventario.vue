<script setup>
// Las acciones del header de un inventario abierto.
defineProps({
  inv: { type: String, required: true },
  meta: { type: Object, required: true },
})
</script>

<template>
  <RouterLink class="g-btn-outline" :to="{ name: 'inventarios' }">‹ INVENTARIOS</RouterLink>
  <RouterLink v-if="meta.puede_accesos" class="g-btn-outline" :to="{ name: 'accesos', params: { inv } }">🔑 QUIÉN ENTRA</RouterLink>
  <RouterLink v-if="meta.puede_alias" class="g-btn-outline" :to="{ name: 'alias', params: { inv } }">ALIAS</RouterLink>
  <RouterLink v-if="meta.puede_auditoria" class="g-btn-outline" :to="{ name: 'bajas', params: { inv } }">BAJAS</RouterLink>
</template>
