import { createApp } from 'vue'
import { VueQueryPlugin } from '@tanstack/vue-query'

import '@static/marca.css'
import '@static/gestion.css'
import './estilos/app.css'

import App from './App.vue'
import router from './router'
import { queryClient, activarPersistencia, olvidarTodo } from './consultas'

activarPersistencia()

// La sesión se cortó (venció o la revocaron) en medio del uso: fuera los datos del
// dispositivo y a la pantalla de entrada, con vuelta a donde estaba.
window.addEventListener('mitre:sin-sesion', () => {
  olvidarTodo()
  queryClient.setQueryData(['sesion'], { acceso: null })
  const actual = router.currentRoute.value
  if (!actual.meta.publica) router.replace({ name: 'entrar', query: { volver: actual.fullPath } })
})

createApp(App)
  .use(router)
  .use(VueQueryPlugin, { queryClient })
  .mount('#app')
