import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { VitePWA } from 'vite-plugin-pwa'

// La app vive en /app/ del mismo Flask: mismo dominio, misma cookie de sesión, sin CORS.
// `npm run build` compila a ../app_dist, que es lo que sirve app.py (y lo que se sube con
// git: el servidor de producción no tiene Node).
export default defineConfig({
  base: '/app/',
  define: {
    __VERSION_APP__: JSON.stringify(new Date().toISOString().slice(0, 16)),
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
      // Las hojas compartidas con las páginas viejas (marca.css, gestion.css) y las
      // fuentes tienen un solo dueño: static/. La app las importa de ahí.
      '@static': fileURLToPath(new URL('../static', import.meta.url)),
    },
  },
  build: {
    outDir: '../app_dist',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    fs: { allow: ['..'] },
    // En desarrollo, Vite sirve la app y le pasa a Flask (python app.py) todo lo demás.
    proxy: {
      '/app/api': 'http://127.0.0.1:5000',
      '/acceso': 'http://127.0.0.1:5000',
      '/static': 'http://127.0.0.1:5000',
    },
  },
  plugins: [
    vue(),
    VitePWA({
      // 'prompt': la versión nueva se descarga sola pero no se activa hasta que la
      // persona toca "Actualizar" (ver componentes/AvisoVersion.vue). Activarla sola en
      // medio de una edición recargaría la pantalla con el formulario a medio llenar.
      registerType: 'prompt',
      injectRegister: false,
      includeAssets: ['escudo.svg'],
      manifest: {
        name: 'Emilio Mitre — Sistema de Gestión',
        short_name: 'Mitre',
        description: 'Inventario, historia y salidas educativas de la Escuela Técnica Emilio Mitre.',
        lang: 'es-AR',
        start_url: '/app/',
        scope: '/app/',
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
        // Cualquier pantalla de la app abre desde el dispositivo, con o sin red.
        navigateFallback: '/app/index.html',
        navigateFallbackAllowlist: [/^\/app\//],
        navigateFallbackDenylist: [/^\/app\/api\//],
        globPatterns: ['**/*.{js,css,html,svg,png,ttf,woff2}'],
        runtimeCaching: [
          {
            // Las fotos tienen la fecha en la URL: misma URL, misma imagen para siempre.
            urlPattern: ({ url }) => url.pathname.startsWith('/app/api/') && url.pathname.includes('/fotos/'),
            handler: 'CacheFirst',
            options: {
              cacheName: 'mitre-fotos',
              expiration: { maxEntries: 600, maxAgeSeconds: 60 * 60 * 24 * 365 },
              cacheableResponse: { statuses: [200] },
            },
          },
        ],
      },
    }),
  ],
})
