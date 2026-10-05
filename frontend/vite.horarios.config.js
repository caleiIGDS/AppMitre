import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { VitePWA } from 'vite-plugin-pwa'

// La app de HORARIOS: otra app instalable, aparte de la de Gestión (vite.config.js).
// Vive en /app-horarios/ para que el celular la instale como una app distinta, con su
// ícono, su service worker y su memoria. Comparte con la otra sólo piezas sueltas de
// src/ (avisos, aviso de sin conexión) y las hojas de static/.
// `npm run build:horarios` compila a ../app_horarios_dist, que sirve app.py.
export default defineConfig({
  root: fileURLToPath(new URL('./horarios', import.meta.url)),
  base: '/app-horarios/',
  define: {
    __VERSION_APP__: JSON.stringify(new Date().toISOString().slice(0, 16)),
  },
  resolve: {
    alias: {
      '@horarios': fileURLToPath(new URL('./horarios/src', import.meta.url)),
      '@': fileURLToPath(new URL('./src', import.meta.url)),
      '@static': fileURLToPath(new URL('../static', import.meta.url)),
    },
  },
  build: {
    outDir: fileURLToPath(new URL('../app_horarios_dist', import.meta.url)),
    emptyOutDir: true,
  },
  server: {
    port: 5174,
    fs: { allow: ['..'] },
    proxy: {
      '/app-horarios/api': 'http://127.0.0.1:5000',
      '/horarios': 'http://127.0.0.1:5000',
      '/static': 'http://127.0.0.1:5000',
    },
  },
  plugins: [
    vue(),
    VitePWA({
      // Igual que la de Gestión: la versión nueva se baja sola y se activa cuando la
      // persona toca "Actualizar".
      registerType: 'prompt',
      injectRegister: false,
      includeAssets: ['escudo.svg'],
      manifest: {
        id: '/app-horarios/',
        name: 'Emilio Mitre — Horarios',
        short_name: 'Horarios',
        description: 'Horarios de cursos, profesores, aulas y preceptores de la Escuela Técnica Emilio Mitre.',
        lang: 'es-AR',
        start_url: '/app-horarios/',
        scope: '/app-horarios/',
        display: 'standalone',
        background_color: '#F1F5F9',
        theme_color: '#1A365D',
        icons: [
          { src: 'icono-192.png', sizes: '192x192', type: 'image/png' },
          { src: 'icono-512.png', sizes: '512x512', type: 'image/png' },
          { src: 'icono-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        navigateFallback: '/app-horarios/index.html',
        navigateFallbackAllowlist: [/^\/app-horarios\//],
        navigateFallbackDenylist: [/^\/app-horarios\/api\//],
        globPatterns: ['**/*.{js,css,html,svg,png,ttf,woff2}'],
      },
    }),
  ],
})
