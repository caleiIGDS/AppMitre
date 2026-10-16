import { createApp } from 'vue'
import { VueQueryPlugin } from '@tanstack/vue-query'

// Las mismas hojas que las páginas del servidor (global.css trae la paleta, el escudo y la
// Roboto Mono auto-hospedada), más lo propio de la app.
import '@static/global.css'
import '@static/gestion.css'
import './estilos/app.css'
// window.ImgUtils: la misma compresión de fotos que usa el chat.
import '@static/img-utils.js'

import App from './App.vue'
import router from './router'
import { queryClient, activarPersistencia } from './consultas'

// Se perdió el acceso a un inventario mientras se lo usaba: lo que quedó de él en el
// dispositivo se descarta y se pide la clave, con vuelta a donde se estaba.
window.addEventListener('mitre:sin-acceso', ({ detail }) => {
  queryClient.removeQueries({ queryKey: ['gestion', detail.inv] })
  const actual = router.currentRoute.value
  if (actual.params.inv === detail.inv && actual.name !== 'inventario-entrar') {
    router.replace({ name: 'inventario-entrar', params: { inv: detail.inv }, query: { volver: actual.fullPath } })
  }
})

// La app abre recién con lo guardado ya en memoria (unos milisegundos): si no, la primera
// pantalla lo pediría a la red, y sin red se quedaría esperando. Si lo guardado no se pudo
// leer, abre igual.
activarPersistencia().catch(() => {}).then(() => {
  createApp(App)
    .use(router)
    .use(VueQueryPlugin, { queryClient })
    .mount('#app')
})
