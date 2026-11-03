# Las apps instalables (`/gestion/` y `/horarios/`, carpeta `frontend/`)

Gestión y Horarios son apps de una sola página (Vue 3 + Vite) que se instalan en el celular
o la compu (PWA), abren desde el dispositivo y le piden al servidor sólo datos. **Ya no hay
páginas clásicas de esas dos áreas**: la app de Gestión vive en `/gestion/` y la de Horarios
en `/horarios/` (esta al final: "La app de horarios"). Mismo look que el resto (importan
`static/global.css` y `static/gestion.css`/`horarios.css`), misma cookie de sesión.

La app de Gestión cubre todo el área: lista de inventarios (y, para administración, crear,
renombrar, clave y eliminar), entrar con la clave del inventario, listado con filtros, ficha,
alta, EDITAR (unidades +/−, kit, baja), fotos (subir, rotar, borrar), alias, registro de
bajas y el panel del encargado "quién entra" (`/gestion/<inv>/accesos`). Las otras áreas
(asistente, salidas, accesos) siguen siendo páginas Jinja, con link desde el ☰.

### Direcciones

- **Las APIs conservan el prefijo viejo:** `/app/api/...` (Gestión) y `/app-horarios/api/...`
  (Horarios). Mover la página no obligaba a mover la API, y así nada de lo que ya la llama cambia.
- **Las direcciones viejas redirigen** (`app.py`, 302 con la query): `/app/gestion/<inv>/…` →
  `/gestion/<inv>/…`, `/app/gestion` → `/gestion/inventarios`, `/app/entrar` →
  `/gestion/entrar`, `/app-horarios/<ruta>` → `/horarios/<ruta>`.
- **`/app/sw.js` y `/app-horarios/sw.js`** sirven un service worker "de retiro"
  (`SW_RETIRADO`): borra sus cachés, se da de baja y recarga sus pestañas, que caen en la
  redirección. Así un celular con la app vieja instalada no queda abriendo la copia
  precacheada para siempre. El ícono instalado puede quedar apuntando a la dirección vieja
  (anda, por la redirección); reinstalar lo deja limpio.
- Los manifests conservan el `id` viejo (`/app/`, `/app-horarios/`) para que el navegador los
  reconozca como la misma app.

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
  vistas/, componentes/  pantallas y piezas
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
  `…/fotos/<foto_id>?v=<fecha o girada>-<tipo>` con caché de un año, y cada foto trae además
  `mini` (`&t=mini`, JPEG de 320 px que se genera la primera vez en `fotos/mini/`) para las
  grillas (en la ficha va por `srcset` junto a `url`: en PC elige la entera). Rotar marca `girada` en la fila (también el asistente), y con eso
  cambian las dos URLs. Al llegar la lista de un inventario, `gestion/precarga.js` baja en
  segundo plano todas las que el dispositivo no tiene (primero las miniaturas).
- **Orden a mano** (`orden.js`): las fotos de una ficha y las tarjetas de `/gestion/inventarios`
  se ordenan arrastrando (con el mouse, o con el dedo tras un toque largo de 350 ms). El orden
  es **de cada dispositivo**: va a localStorage (`mitre-orden`), el servidor no lo conoce. La
  primera foto de la ficha es la portada de la tarjeta en la vista galería (`portada()`).

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
  `gestion._entrar_inventario`. Los permisos del ámbito los contesta su
  `/meta` (`puede_escribir`, `puede_alias`, `puede_auditoria`, `puede_rotar`,
  `puede_accesos`). Sin acceso al inventario (401, o 403 del admin general, cuyo comodín no
  llega adentro) el router lleva a la pantalla de la clave.
- El gate de la API es `accesos.registrar_acceso_api`: todo JSON, y las escrituras exigen
  `X-Mitre: 1` (defensa CSRF).
- Administración de la lista (`POST/PATCH/DELETE /app/api/gestion/inventarios`) exige
  `inventarios.admin`; el panel del encargado (`/app/api/gestion/<inv>/accesos`,
  invitaciones y dispositivos) exige el permiso de accesos del inventario.

## Service worker

Lo genera `vite-plugin-pwa` (Workbox). Precachea la app; cualquier ruta `/gestion/...` abre desde
el dispositivo (`navigateFallbackAllowlist`). Scope `/` para que también pueda pedir `/app/api/`. Fotos: `CacheFirst` (`mitre-fotos`, hasta 5000: cada foto son dos entradas). Una versión nueva se baja sola pero
se activa cuando la persona toca **Actualizar** (`AvisoVersion.vue`). Flask (`app.py`) sirve
`assets/` con caché de un año (llevan hash) y el resto con `no-cache`.

## Desarrollo y deploy

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173/gestion/, con Flask corriendo en :5000
npm run build    # compila a ../app_dist (commitear el resultado)
```

El servidor de producción no tiene Node: **antes de commitear un cambio de `frontend/`, correr
`npm run build`** y commitear `app_dist/` junto con el código. En el server no hay nada nuevo
que hacer: `git pull` + `actualizar.py` + Reload, como siempre; el versionado lo crea
`init_db` en el arranque.

## La app de horarios (`/horarios/`, carpeta `frontend/horarios/`)

Otra app instalable, **separada** de la de Gestión: otra dirección (`/horarios/`), otro
manifest, otro service worker y otra memoria, para que el celular la instale como una app
distinta (ícono con un reloj). Es todo el sistema de horarios: las cinco pestañas, comparar,
planilla general, PDF, imprimir varios, ACTUALIZAR HORARIOS, tema nocturno y modo manual.
`/` redirige acá.

- **Datos:** `GET /app-horarios/api/datos` (`horarios/app_api.py`) manda el horario entero
  de una vez (~600 KB) con ETag (mtime de `escuela.db` + huella de `horarios/config.py`). La
  app lo guarda en **IndexedDB** (no localStorage: es grande y localStorage lo comparte con
  la app de Gestión) y todo se resuelve en el dispositivo: buscar, comparar, planilla,
  TIEMPO REAL. Se conserva hasta un mes, incluso al actualizar la app (sólo se invalida
  si cambia el formato de los datos). Se vuelve a preguntar cada 10 minutos (304 si nada cambió).
- **Sesión:** `HORARIOS_CLAVE`, con el flag de sesión de `horarios/acceso.py`;
  `acceso.comprobar_clave` hace el chequeo (con límite de intentos). No usa
  `accesos`. Escrituras con `X-Mitre`, igual que `/app/api`.
- **PDF:** `impresion.js` abre una vista local con los mismos filtros y componentes del calendario y los datos descargados, sin red; el diálogo del navegador permite imprimir o guardar como PDF vectorial, A4 horizontal y una página por calendario, también varios cursos y planillas. La planilla de preceptores se divide en páginas legibles. `/horarios/export/pdf/...` (`horarios/rutas.py`) sigue disponible por compatibilidad y el service worker deja pasar esas rutas.
- **Direcciones:** cada búsqueda es una URL (`/cursos/3° B`, `/aulas?planilla=1&dia=…&piso=…`,
  `?comparar=curso:…,profesor:…` con el mismo formato que el link del asistente).
- **Motor del calendario:** `frontend/horarios/src/calendario.js` (ver `calendar-engine.md`),
  separado del dibujo (`Calendario.vue`).
- **Look:** importa `static/global.css` + `static/horarios.css` (las clases vienen de la
  página clásica que reemplazó). Lo propio está en `frontend/horarios/src/estilos.css`,
  incluido el diseño para celular.

```bash
cd frontend
npm run dev:horarios     # http://localhost:5174/horarios/, con Flask en :5000
npm run build:horarios   # compila a ../app_horarios_dist (commitear el resultado)
npm run build:todo       # las dos apps
```
