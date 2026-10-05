# La app instalable (`/app`, carpeta `frontend/`)

La versión nueva de las áreas internas: una app de una sola página (Vue 3 + Vite) que se
instala en el celular o la compu (PWA), abre desde el dispositivo y le pide al servidor sólo
datos. Convive con las páginas clásicas (`/gestion`, `/historia`, …) mientras dura la
migración: cada área pasa a la app cuando está completa y probada. Hoy está **Gestión**; las
demás se abren en su versión clásica desde el menú (`frontend/src/areas.js`).

## Piezas

```
frontend/src/            ← código de la app (se edita acá)
  main.js, App.vue       arranque y armazón (encabezado, nav del área, avisos)
  router.js              pantallas y permiso de cada una (meta.permiso)
  api.js                 único cliente HTTP: errores tipados (ErrorApi), X-Mitre en escrituras
  consultas.js           TanStack Query: memoria de datos, persistencia y aviso entre pestañas
  sesion.js              quién soy / entrar / salir (/app/api/sesion)
  texto.js               puerto de texto.py::puntaje_busqueda (mismo umbral 0.68)
  navegacion.js          volverA(): "atrás" si la pantalla destino es la anterior
  gestion/datos.js       consultas y mutaciones del inventario
  vistas/, componentes/  pantallas y piezas
app_dist/                ← lo que compila `npm run build` y sirve Flask. SE COMMITEA
```

Estilos: la app importa `static/marca.css` y `static/gestion.css` (los mismos que las páginas
clásicas) y agrega `frontend/src/estilos/app.css` con prefijo `a-`. Las fuentes salen de
`static/fonts/` empaquetadas: la app se ve bien sin red.

## Cómo se mantiene al día sin re-bajar todo

- **Una consulta por colección.** `GET /app/api/gestion/recursos` trae el inventario entero
  con todo lo que muestran el listado y la ficha. La ficha y el formulario leen de esa misma
  lista: abrir un recurso no pide nada.
- **ETag = `_revision`.** Cada DB del motor tiene un contador que suben triggers ante cualquier
  alta, baja o cambio (`crud.instalar_versionado`). Si no cambió, el servidor contesta 304 sin
  cuerpo. La app pregunta al volver a la pestaña, al recuperar la red y cada 60 s.
- **Cada escritura devuelve la fila completa** como quedó, y la app reemplaza sólo esa fila.
- **Persistencia:** lo bajado queda en `localStorage` (`mitre-datos`, una semana). Al salir o
  si la sesión se corta, se borra. Una versión nueva de la app lo descarta (`buster`).
- **Entre pestañas:** `BroadcastChannel('mitre')` avisa los cambios a las otras pestañas.

## Conflictos

Cada fila tiene `version` (la suben los triggers con cualquier cambio de la fila **o de sus
tablas hijas**: las de `LIMPIEZA_M2M`). `PUT` exige la versión que la app vio; si no coincide
contesta 409 con la fila actual. El formulario combina solo si se tocaron campos distintos y
muestra la diferencia si se tocó el mismo (`RecursoFormulario.vue`). Los triggers son la única
forma de que el asistente, las rutas propias y los scripts también suban la versión sin
acordarse.

## API JSON

Montada por `crud.registrar_api(bp_api, area)` sobre un blueprint con
`accesos.registrar_acceso_api` (todo JSON: 401 sin sesión, 403 sin permiso, escrituras con
`X-Mitre: 1` como defensa CSRF). Convenciones en el comentario de cabecera de esa sección de
`crud.py`. Lo propio de un área (unidades, kits) va en su archivo con el mismo contrato: cada
escritura devuelve el recurso serializado. La sesión: `GET/POST/DELETE /app/api/sesion`
(`accesos.registrar_app`). Los internos siguen entrando por `/acceso/<token>`: la cookie es la
misma.

Fotos: siguen guardadas en base64 dentro de la fila, pero la API las sirve por URL
(`…/fotos/<i>?v=<fecha>`, cacheable para siempre) y el listado no las incluye.

## Service worker

Lo genera `vite-plugin-pwa` (Workbox). Precachea la app; cualquier ruta `/app/...` abre
desde el dispositivo (`navigateFallback`), salvo `/app/api/`. Fotos: `CacheFirst`. Una versión
nueva se baja sola pero se activa cuando la persona toca **Actualizar**
(`AvisoVersion.vue`), para no recargar en medio de una edición. Flask sirve `assets/` con
caché de un año (llevan hash) y el resto (`index.html`, `sw.js`) con `no-cache`.

## Desarrollo y deploy

```bash
cd frontend
npm install
npm run dev      # app en http://localhost:5173/app/, con python app.py corriendo en :5000
npm run build    # compila a ../app_dist (commitear el resultado)
```

El servidor de producción no tiene Node: **antes de commitear un cambio de `frontend/`, correr
`npm run build`** y commitear `app_dist/` junto con el código.
