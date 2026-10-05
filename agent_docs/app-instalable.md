# La app instalable (`/app`, carpeta `frontend/`)

La versión nueva de las áreas internas: una app de una sola página (Vue 3 + Vite) que se
instala en el celular o la compu (PWA), abre desde el dispositivo y le pide al servidor sólo
datos. **Convive con las páginas clásicas**: mismas direcciones debajo de `/app`
(`/gestion/<inv>/recursos/12` → `/app/gestion/<inv>/recursos/12`), mismo look (importa
`static/global.css` y `static/gestion.css`), misma cookie de sesión. Hoy cubre el uso diario
de **Gestión**: lista de inventarios, entrar con la clave del inventario, listado con filtros,
ficha, alta, EDITAR (unidades +/−, kit, baja), fotos (subir, rotar, borrar), alias y registro
de bajas. Siguen clásicas, con link desde la app: administrar la lista de inventarios
(`/gestion/`) y el panel del encargado (`/gestion/<inv>/accesos`); y las otras áreas
(asistente, salidas, accesos) desde el ☰. Horarios es un sitio aparte y no entra.

## Piezas

```
frontend/src/            ← código de la app (se edita acá)
  main.js, App.vue       arranque y armazón (encabezado, pestañas, avisos)
  router.js              pantallas; las de un inventario piden su /meta antes de abrir
  api.js                 único cliente HTTP: ErrorApi tipado, X-Mitre en escrituras
  consultas.js           TanStack Query: memoria de datos, persistencia, aviso entre pestañas
  sesion.js              /app/api/sesion: quién soy, admin entrar/salir
  gestion/datos.js       consultas y mutaciones de un inventario (todo con `inv` en la clave)
  texto.js               puerto de texto.py::puntaje_busqueda (mismo umbral 0.68)
  navegacion.js          volverA(): "atrás" si la pantalla destino es la anterior
  vistas/, componentes/  pantallas y piezas; cada vista dice qué template clásico replica
app_dist/                ← lo que compila `npm run build` y sirve Flask. SE COMMITEA
```

## Cómo se mantiene al día sin re-bajar todo

- **Una consulta por inventario.** `GET /app/api/gestion/<inv>/recursos` trae todos los
  recursos con lo que muestran el listado, la ficha y EDITAR (unidades agrupadas, kit, días
  sin revisar, URLs de fotos). Abrir una ficha o EDITAR no pide nada.
- **ETag = `_revision`.** Cada DB del motor tiene un contador que suben triggers ante
  cualquier cambio (`crud.instalar_versionado`); el ETag lleva además el id del inventario
  (`api_etag`). Si nada cambió, 304 sin cuerpo. La app pregunta al volver a la pestaña, al
  recuperar la red y cada 60 s.
- **Cada escritura devuelve el recurso completo** y la app reemplaza sólo esa fila.
- **Persistencia:** lo bajado queda en `localStorage` (`mitre-datos`, una semana) y se borra
  al salir. Una versión nueva de la app lo descarta (`buster`).
- **Entre pestañas:** `BroadcastChannel('mitre')`.
- **Fotos:** siguen en `database/fotos/` (`fotos_disco.py`); la API las sirve por
  `…/fotos/<foto_id>?v=<fecha o girada>-<tipo>` con caché de un año. Rotar marca `girada` en
  la fila (también desde la página clásica), y con eso cambia la URL.

## Conflictos

Cada recurso tiene `version`, que suben los triggers con cualquier cambio de la fila **o de
sus tablas hijas** (`LIMPIEZA_M2M`: unidades, kit). `PUT` exige la versión que vio la app; si
no coincide, 409 con la fila actual. El formulario combina solo si se tocaron campos distintos
y muestra la diferencia si se tocó el mismo. Una versión nueva que no cambió ningún campo del
formulario (unidades, kit, fotos tocados desde la misma pantalla) se adopta sin avisar.

## Acceso

- `/app/api/sesion` (GET/POST/DELETE): sesión de admin o dispositivo, con sus permisos SIN
  ámbito (`accesos.registrar_app`).
- Un inventario: `POST /app/api/gestion/<inv>/entrar {clave}` llama al mismo
  `gestion._entrar_inventario` que el login clásico. Los permisos del ámbito los contesta su
  `/meta` (`puede_escribir`, `puede_alias`, `puede_auditoria`, `puede_rotar`,
  `puede_accesos`). Sin acceso al inventario (401, o 403 del admin general, cuyo comodín no
  llega adentro) el router lleva a la pantalla de la clave.
- El gate de la API es `accesos.registrar_acceso_api`: todo JSON, y las escrituras exigen
  `X-Mitre: 1` (defensa CSRF).

## Service worker

Lo genera `vite-plugin-pwa` (Workbox). Precachea la app; cualquier ruta `/app/...` abre desde
el dispositivo, salvo `/app/api/`. Fotos: `CacheFirst`. Una versión nueva se baja sola pero
se activa cuando la persona toca **Actualizar** (`AvisoVersion.vue`). Flask (`app.py`) sirve
`assets/` con caché de un año (llevan hash) y el resto con `no-cache`.

## Desarrollo y deploy

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173/app/, con Flask corriendo en :5000
npm run build    # compila a ../app_dist (commitear el resultado)
```

El servidor de producción no tiene Node: **antes de commitear un cambio de `frontend/`, correr
`npm run build`** y commitear `app_dist/` junto con el código. En el server no hay nada nuevo
que hacer: `git pull` + `actualizar.py` + Reload, como siempre; el versionado lo crea
`init_db` en el arranque.
