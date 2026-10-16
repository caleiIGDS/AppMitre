import { createApp } from 'vue'
import { VueQueryPlugin } from '@tanstack/vue-query'

// Las mismas hojas que /horarios: global.css (paleta, fuente) + horarios.css (calendario,
// tablero, tema nocturno). Más los avisos compartidos con la app de Gestión y lo propio.
import '@static/global.css'
import '@static/horarios.css'
import '@/estilos/app.css'
import './estilos.css'

import App from './App.vue'
import router from './router'
import { queryClient, activarPersistencia } from './consultas'

// El servidor dijo 401 (se cerró la sesión, cambió la clave): pedir la clave y volver.
window.addEventListener('horarios:sin-sesion', () => {
  const actual = router.currentRoute.value
  queryClient.setQueryData(['sesion'], { autenticado: false })
  if (actual.name !== 'entrar') router.replace({ name: 'entrar', query: { volver: actual.fullPath } })
})

// Pantalla completa (F11), para el tablero en un televisor: igual que /horarios.
document.addEventListener('fullscreenchange', () => {
  document.body.classList.toggle('is-fullscreen', !!document.fullscreenElement)
})
document.addEventListener('keydown', (e) => {
  if (e.key !== 'F11') return
  e.preventDefault()
  if (!document.fullscreenElement) document.documentElement.requestFullscreen().catch(() => {})
  else document.exitFullscreen?.()
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
