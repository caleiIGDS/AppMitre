# Gestión de recursos (`/gestion`)

Una de las cuatro áreas de la app (las otras: el SPA de horarios, `/historia` y `/agente`).
Es el **inventario técnico** de la escuela: recursos, conjuntos y actividades, conectados entre
sí, más el registro de préstamos. **`gestion.db` es la fuente de verdad**: lo que no está acá,
no está. Las fotos viven en la propia base (columna `fotos`, ver abajo).

> Hasta el 2026-08-10 el modelo era otro: los archivos reales vivían en Google Drive y cada
> entidad guardaba un link en `drive_url`. La escuela dejó de usar Drive y la columna se
> eliminó de las tres tablas. Si ves `drive_url` en un respaldo viejo de `backups/`, es de
> antes de ese corte.

**Qué NO está acá**: la línea del tiempo institucional (`hitos`) y las fichas de personas se
separaron a `/historia` + `historia.db` el 2026-08-10 — ver `agent_docs/historia-institucional.md`
y `dev-log/DECISIONS.md`. Los dos módulos son hermanos y **no se importan entre sí**: comparten
el motor genérico `crud.py`, que no importa a ninguno de los dos — ver `agent_docs/crud-motor.md`.

## Arquitectura

- **`gestion.py`** — el área: blueprint Flask (`bp`, prefix `/gestion`), `ENTIDADES`, `SCHEMA`,
  sus hooks (`migrar`, `seed`, `secciones_detalle`, `valores_iniciales`, `tarjetas_extra`,
  `contexto_extra`, `extras_template`, `NAV_EXTRA`) y **el bloque entero de préstamos/carrito**,
  que es lo único que no pasa por el motor. Las rutas CRUD las monta `crud.registrar_rutas(bp,
  ...)` y el gate `crud.registrar_acceso(bp)` — ver `agent_docs/crud-motor.md`.
  Server-rendered con Jinja. El JS propio es `static/gestion.js`, con dos
  mejoras progressive-enhancement: búsqueda en vivo del listado y agregar al carrito por
  AJAX (ver abajo); el resto es HTML puro con forms + redirects.
- **`gestion.db`** — SQLite propia, separada de `escuela.db`. **No** se regenera desde
  Sheets y `/api/actualizar` no la toca. Junto con `historia.db` son las DBs con datos
  propios de la app (en hosting efímero tipo Render se pierden en cada restart; en
  PythonAnywhere persisten). Alberga además las tablas del asistente (`agente_log`,
  `agente_conversaciones`, `agente_fotos_pendientes`), que son auditoría/sesión y no datos
  de dominio.
- **`templates/gestion/`** — `base.html` (layout + nav), `home.html`, `lista.html`,
  `form.html`, `detalle.html`. Los tres últimos son **genéricos**: se renderizan a partir
  de la config declarativa de cada entidad. `prestamos_lista.html`, `prestamos_detalle.html`,
  `carrito.html`, `carrito_finalizar.html` son específicos (préstamos no entra en `ENTIDADES`:
  tiene ítems con cantidad y un ciclo prestado→devuelto que el trío genérico no modela, y el
  alta usa un carrito en sesión que el usuario ve como "PRÉSTAMO" en la UI).
- **`static/gestion.css`** — hoja standalone (paleta blueprint copiada, no importa
  `style.css` para que los dos sistemas no se pisen). Sin modo oscuro. La comparten
  `/historia` y `/agente`: la identidad visual sí es común, la lógica de dominio no.
- **`static/gestion.js`** — único JS del módulo: búsqueda en vivo del listado + el stepper
  del carrito (vanilla, sin build step). Cargado en `base.html` con `defer`; no hace nada
  fuera de las páginas donde encuentra sus hooks (guarda por existencia de elementos).
- **`static/mobile-nav.js`** — el ☰ y su panel lateral, compartido con `/historia`,
  `/agente` y `/accesos` (ver "Celular" abajo). No es lógica de dominio: solo mueve nodos
  del shell.
- `base.html` incluye el widget flotante del asistente (`agente/_agente_widget.html`) y
  el bloque `.g-areas` con los links a las otras áreas, que van al ☰. El header queda
  para lo de esta página: el toggle del widget, el carrito y la vuelta al SPA.
- Integración: `app.py` hace `app.register_blueprint(gestion.bp)` + `gestion.init_db()`
  en import (funciona bajo gunicorn/WSGI). Desde el SPA principal ya no se entra sólo por
  URL: si hay sesión y el permiso, aparece en su ☰ (ver `agent_docs/accesos.md`). Para el
  público el SPA no muestra nada — el "oculto" de la decisión 2026-07-17 lo sostiene ahora
  el gate de accesos, no la ausencia de links.

## Celular

Todo el shell (header + nav + fichas) es **el mismo markup en celular y en escritorio**:
lo único que cambia es CSS, más un script que reubica bloques. Es común a las cuatro
áreas que comparten `gestion.css` (`/gestion`, `/historia`, `/agente`, `/accesos`).

- **El ☰ y su panel (`static/mobile-nav.js`)** — el panel existe **a cualquier ancho** y
  lleva el menú de áreas (`.g-areas`, ver `agent_docs/frontend-ui.md`). **Abajo de 900px**
  se le suman el `.g-nav` de pestañas y el `.g-header-actions` del header, que **se
  mueven** (no se clonan) por dos razones: los listeners ya enganchados por `gestion.js`
  (carrito) y `gestion-agente.js` (botón del asistente) siguen funcionando en el nodo
  movido, y no se duplican IDs como `#agente-toggle-btn`. Cada bloque deja un
  comentario-marcador en su lugar original, así al agrandar la ventana vuelve exactamente
  ahí (se escucha `matchMedia`, no `resize`). El panel se cierra con ✕, Esc, tocando el
  fondo o cualquier link de adentro. Sin JS no hay panel: nav y acciones quedan en el
  header envolviendo en varias filas, como siempre, y el menú de áreas no se ve.
- **Listados como tarjetas (≤700px)** — una tabla de 5 columnas en 360px obliga a
  scrollear de costado y deja RETIRAR / Ver / Editar fuera de pantalla. Abajo de 700px
  cada `<tr>` de `.g-table` pasa a `display: block` y se ve como una tarjeta: el nombre
  de título, el resto como pares etiqueta/valor, los botones al pie. **La etiqueta sale
  del `data-label` de cada `<td>`**, que repite el encabezado de la columna — si agregás
  una columna a un listado, ponele `data-label` o en celular sale sin etiqueta. Los `<td>`
  llevan `{%- -%}` para quedar *realmente* vacíos cuando no hay dato y que `td:empty` los
  esconda (si no, se vería la etiqueta sola). Entre 700 y 900px sigue siendo tabla con
  scroll horizontal.
- **Táctil** — objetivos de 44px en botones y campos, y **16px exactos** de `font-size`
  en los inputs: con menos, iOS hace zoom al enfocar y descuadra el layout.
- El chat tiene además su propia capa mobile, ver `agent_docs/agente-asistente.md`.

## Modelo de datos (gestion.db)

| Tabla | Campos |
|-------|--------|
| `recursos` | id, nombre, tipo, descripcion, ubicacion, estado, cantidad, valor, fecha_revision, **fotos**, **alias** |
| `conjuntos` | id, nombre, descripcion, uso_tipico, **fotos** |
| `actividades` | id, nombre, objetivo, descripcion, duracion, curso, **fotos** |
| `prestamos` | id, persona, destino, notas, fecha_salida, fecha_devolucion |
| `prestamo_items` | prestamo_id, recurso_id, cantidad, cantidad_devuelta (M2M con cantidad, `UNIQUE(prestamo_id, recurso_id)`) |
| `recurso_ubicaciones` | recurso_id, ubicacion, cantidad (`UNIQUE(recurso_id, ubicacion)`) — desglose OPCIONAL de dónde están las unidades de un recurso, ver abajo |

**Desglose por lugar** (`recurso_ubicaciones`): el campo `ubicacion` de `recursos` sigue siendo
el lugar único/principal de siempre — la mayoría de los recursos no toca esta tabla. Sólo entra
en juego cuando las unidades de un mismo recurso están repartidas en más de un sitio (10
destornilladores, 5 en el taller y 5 en el laboratorio). **Nunca es obligatorio ni tiene que
sumar el total de `recursos.cantidad`**: no hay concepto de "sin ubicar" que validar, cada fila
es independiente — a propósito, para no bloquear un movimiento por no tener el desglose previo
cargado (mismo criterio de avisar-no-bloquear que `crear_prestamo` con el stock, ver
`dev-log/DECISIONS.md` 2026-08-11). Helpers en `gestion.py`: `ubicaciones_recurso()` (el
desglose de un recurso), `mover_ubicacion()` (mueve cantidad de un lugar a otro, vaciando y
avisando si el origen no tenía tanto registrado). Se edita desde la ficha web (rutas
`/gestion/recursos/<id>/ubicaciones[/eliminar]`, sección "Por ubicación" del detalle, sólo
visible si el recurso tiene más de una unidad o ya tiene desglose) y desde el chat (tool
`mover_ubicacion`, ver `agent_docs/agente-asistente.md`).

**Galería de fotos** (`fotos` en cada tabla): array JSON con objetos `{b64, tipo, fecha}`.
- `b64`: imagen codificada en base64 (embedded, sin servicios externos)
- `tipo`: content-type (ej: `image/png`)
- `fecha`: timestamp ISO de cuándo se subió
- Upload: botón en ficha de detalle → POST `/<slug>/<id>/foto` → sube imagen, convierte a base64, guarda en DB
- Renderizado: galería grid responsive (120px minmax) de miniaturas recortadas (`object-fit: cover`)
- **Visor**: click en una miniatura abre un lightbox a pantalla completa (`.g-lightbox`, CSS en
  `gestion.css`, JS inline en `detalle.html`) con la foto entera, contador `n / total`, flechas
  ‹ › (y ← → del teclado), cierre con Esc o click en el fondo, y el botón **ELIMINAR**
- Borrado: `POST /<slug>/<id>/foto/<indice>/eliminar` (con `confirm()`) → saca la foto del array
  y redirige a la ficha. **La referencia es la posición en el array**: las fotos no tienen id
  propio. Un índice fuera de rango no es error, se ignora (dos pestañas borrando a la vez)
- Las miniaturas son `<button>` (no `<img>` suelta) para que el visor se abra también con teclado

M2M (con `UNIQUE` por par): `conjunto_recursos`, `actividad_recursos`, `actividad_conjuntos`.
**No hay ninguna relación que cruce a `historia.db`**: `proyecto_recursos` (lo único que ataba
el inventario con la memoria institucional) se eliminó con la tabla `proyectos`.

Estados: recursos = Disponible / Retirado / En uso / En reparación / De baja / Sin revisar.
Valor (recursos): "" / Básico / Secundario / Alto valor — es la *importancia* del recurso
dentro del inventario, no su precio (se llamaba `utilidad`, renombrada 2026-08-08).
`cantidad` y `fecha_revision` son TEXT. **`fecha_revision` se precarga con la fecha de hoy
en todo alta de recurso**, por los dos caminos: el form web (`_valores_iniciales()` en el
GET de `/recursos/nuevo`) y el chat (`_normalizar_borrador()` en `agente/tools/fichas.py`, antes de
calcular el token, para que la fecha aparezca en la ficha y el usuario la vea y la pueda
cambiar). Dar de alta un recurso es un control de inventario; antes quedaba vacía y casi
ningún recurso terminaba con fecha. "Hoy" sale de `config.ahora()` (hora de Buenos Aires; el
server de producción corre en UTC — ver "El reloj" en `agent_docs/crud-motor.md`), igual que la
fecha/hora de los préstamos (`gestion._ahora()`). Formato `gestion.FORMATO_FECHA_REVISION` = `%d/%m/%Y`
(ej `08/08/2026`) — **conviven** con las fechas cortas sin año del inventario importado del
sheet ("24/4", "8/5"), que no se reformatean. Editar un recurso **no** toca la fecha:
`_editar_entidad` parte de la fila actual y no pasa por `_normalizar_borrador`.

**Inventario físico**: la carga inicial vino del sheet "Inventario renovable 2026" vía
`importar_inventario.py`, un script de root que se corrió una vez (81 insertados +
2 actualizados) y **se eliminó el 2026-08-08**, ya cumplido su propósito. `gestion.db` es
la fuente de verdad y nunca hubo write-back al sheet (ver DECISIONS 2026-07-19), así que
la planilla quedó como material histórico. Si alguna vez hay que volver a importar, el
script está en el historial de git (`git show 756a002:importar_inventario.py`) — ojo que
mapeaba los estados Funcional→Disponible, Reparar→En reparación, nc→Sin revisar, y que
traía las fechas de revisión en formato corto sin año, incompatible con
`FORMATO_FECHA_REVISION`.

## Config declarativa (`ENTIDADES` en gestion.py)

Cada entidad define: `tabla`, `singular`/`plural`, `descripcion` (card del home),
`campos` (form: nombre, label, tipo `text|textarea|select|url|date|number`, opciones, ayuda),
`columnas` (listado) y `relaciones` (M2M editables desde su form, campos con prefijo
`rel_` para no colisionar con columnas).

**`campo_nombre`** (opcional, default `'nombre'`): cómo se llama en la tabla la columna que
hace de nombre visible. Ninguna entidad de este módulo la declara distinta — el mecanismo existe
porque `historia.hitos` sí la necesita (`titulo`). Todas las lecturas van por **`crud.select(cfg)`**,
que agrega el alias `AS nombre`, así que templates, `crud.buscar_entidad`, `crud.snapshot_entidad`
y el agente leen siempre `fila['nombre']`. Las escrituras usan `crud.campo_nombre(cfg)`.

El contrato completo de la config y de los hooks está en `agent_docs/crud-motor.md`; acá sólo se
documenta lo que es propio de gestión.

Para agregar un campo: sumarlo al `SCHEMA`,
a `campos` y a la lista de `migrar()` — `init_db()` hace el `ALTER TABLE` aditivo
automáticamente en DBs existentes (así entraron cantidad/valor/fecha_revision).
Para **renombrar** uno, además del `SCHEMA` y `campos` va un `ALTER TABLE ... RENAME COLUMN`
guardado por `PRAGMA table_info` en `migrar()`, **antes** del loop aditivo (si no, el aditivo
crea la columna nueva vacía al lado de la vieja y se pierde el dato). Ver `utilidad`→`valor`.

`LIMPIEZA_M2M` mapea qué tablas de relación limpiar al eliminar cada tipo de entidad.

## Rutas (todas server-rendered)

| Ruta | Método | Descripción |
|------|--------|-------------|
| `/gestion/login` | GET/POST | Form de contraseña; con clave OK setea `session['gestion_ok']` y redirige a `?next=` (solo si empieza con `/gestion`, anti open-redirect) |
| `/gestion/salir` | GET | Borra la sesión y vuelve al login (botón SALIR en el header) |
| `/gestion/` | GET | Home: cards con contadores + explicación de relaciones |
| `/gestion/<slug>` | GET | Listado (`?q=` búsqueda tolerante en nombre + descripcion — ver abajo) |
| `/gestion/<slug>/nuevo` | GET/POST | Alta (valida nombre no vacío server-side) |
| `/gestion/<slug>/<id>` | GET | Detalle: campos + relaciones en ambas direcciones |
| `/gestion/<slug>/<id>/editar` | GET/POST | Edición (sincroniza M2M: delete + insert) |
| `/gestion/<slug>/<id>/eliminar` | POST | Borra fila + sus filas M2M (confirm en el browser) |
| `/gestion/<slug>/<id>/foto` | POST | Sube una imagen a la galería (multipart → base64). Devuelve JSON |
| `/gestion/<slug>/<id>/foto/<indice>/eliminar` | POST | Borra la foto de esa posición y vuelve a la ficha |
| `/gestion/alias` | GET | Solo lectura, solo admin (`gestion.alias`): tabla NOMBRE / ALIAS de todos los recursos. Único lugar de la web donde se ve el alias oculto — no hay edición acá |

`slug` ∈ {recursos, conjuntos, actividades}; otro valor → 404. (`hitos` y `personas` viven en
`/historia`, con las mismas rutas bajo su propio prefijo.)

## Búsqueda tolerante (`?q=` en `lista()`)

No es el `LIKE` literal de SQL: `lista()` trae todas las filas y las filtra/ordena en
Python con `texto.puntaje_busqueda()`. Perdona **acentos y mayúsculas** (normaliza con `texto.norm`)
y **typos** (similitud difusa vía `difflib.SequenceMatcher`, sin dependencias). Reglas:
substring normalizado siempre puntúa por encima de los difusos; la similitud difusa solo
entra para queries de 3+ caracteres, con umbral `texto.UMBRAL_SIMILITUD` (**0.68**, medido contra
el inventario real — ver `dev-log/DECISIONS.md` 2026-08-08). Compara la query
contra el nombre, cada palabra del nombre, y la descripción. Con ~decenas de filas por
entidad el filtrado en Python es despreciable; si alguna tabla creciera a miles habría que
reconsiderar (índice, FTS). Aplica a las 4 entidades genéricas; los préstamos usan su propio
`LIKE` en SQL. Decisión 2026-07-21 (ver `dev-log/DECISIONS.md`).

**Segunda pasada por alias** (solo `recursos`): si una fila no matchea por
nombre/descripción, `crud.py` prueba además contra `recursos.alias` — una columna oculta
que **completa el agente, nunca el humano** (no está en `campos`, así que no aparece en el
form web ni en la ficha de confirmación del chat — ver `agent_docs/agente-asistente.md`). No
son sinónimos estrictos: "zapatilla" y "alargue" son cosas distintas que se confunden, y
también entran acá. Los que matchean solo por alias se muestran **al final** de la lista,
con la etiqueta "· por alias" (`templates/crud/lista.html`), y nunca se mezclan con los
matches normales. El mecanismo genérico (`crud.campo_alias(cfg_ent)`, análogo a
`campo_nombre`) vive en `agent_docs/crud-motor.md`; acá solo se declara `'campo_alias':
'alias'` en `ENTIDADES['recursos']`. Retoma la columna que la decisión 2026-08-08 había
descartado para la búsqueda del chat — el override y por qué esta vez aplica distinto están
en `dev-log/DECISIONS.md` 2026-08-21 (cierra tarea #21 de `dev-log/tasks/DONE.md`).

**Búsqueda en vivo (client-side, `static/gestion.js`)**: además del filtrado server-side,
el listado filtra en el navegador mientras se escribe, sin recargar ni ir al servidor. La
ruta emite por fila un atributo `data-buscar` con el texto ya normalizado por Python
(`texto.norm(nombre + descripcion)`, más el alias si la entidad lo declara), y el JS
filtra por substring normalizado (repite la misma normalización de acentos/mayúsculas). Es
progressive enhancement: sin JS, el form sigue haciendo la búsqueda difusa server-side. Con
JS, el botón BUSCAR se oculta y Enter no recarga. La capa en vivo **no** tiene la tolerancia
difusa a typos (solo substring) — a propósito: al ver los resultados achicarse letra por
letra uno corrige el typo solo; el fuzzy server-side queda como respaldo. Decisión
2026-07-21 (ver `dev-log/DECISIONS.md`).

Relaciones mostradas en detalle (`_secciones_detalle`): recurso → conjuntos que lo
incluyen / actividades que lo usan / **quién lo tiene ahora** / **historial de préstamos**;
conjunto → recursos incluidos / actividades que lo usan; actividad → conjuntos + recursos
utilizados.

En "historial de préstamos" cada fila **dice su estado en las dos ramas** (`· EN PRÉSTAMO`
o `· DEVUELTO <fecha>`), nunca por ausencia de marca: esta misma sección la lee el agente
como JSON por `detalle_entidad`, donde una fila sin marca se leía como préstamo abierto.

## Préstamos / retiros internos

Registro de quién se lleva qué recursos, cuánto y cuándo lo devuelve. Rutas propias
(fuera de `ENTIDADES`, no genéricas):

| Ruta | Método | Descripción |
|------|--------|-------------|
| `/gestion/prestamos` | GET | Listado dividido en "en préstamo" (`fecha_devolucion=''`) e "historial" (`?q=` busca en persona/destino/notas). En activos la columna "se llevó" muestra lo **pendiente**, no lo retirado |
| `/gestion/prestamos/<id>` | GET | Detalle: persona, destino, notas, fechas, e ítems con prestado/devuelto/pendiente y controles de devolución por ítem |
| `/gestion/prestamos/<id>/devolver` | POST | **Devolver TODO**: marca cada ítem entero (`cantidad_devuelta = cantidad`) y setea `fecha_devolucion`. Atajo — **nunca borra la fila** |
| `/gestion/prestamos/<id>/devolver_item` | POST | Devuelve parte (o el resto) de un ítem (`recurso_id` + `cantidad` opcional; vacía = todo lo pendiente). Al cubrirse todo lo pendiente, el préstamo se cierra solo |
| `/gestion/prestamos/<id>/reabrir` | POST | Deshace la devolución completa: resetea todos los ítems a 0 y limpia `fecha_devolucion` |
| `/gestion/prestamos/<id>/reabrir_item` | POST | Deshace la devolución de un ítem puntual (vuelve a 0); si eso deja algo pendiente, reabre el préstamo |
| `/gestion/prestamos/<id>/eliminar` | POST | Borra el registro entero — solo para cargas mal hechas, no es el flujo normal |

### Alta como carrito (en sesión)

No hay form de alta con filas de ítems. El préstamo se arma como un **carrito de compra
tipo e-commerce**: en cada recurso hay un botón **RETIRAR** que lo suma al carrito. Al
agregarlo, el botón se transforma en un **stepper verde `−  N  +`** (en la misma fila / ficha)
que ajusta la cantidad **hasta el stock disponible** (`recursos.cantidad`; sin stock definido =
sin tope). Arriba de todo, en el nav, aparece un **PRÉSTAMO 📋** con el contador que lleva directo al
checkout (`/carrito/finalizar`). Recién al finalizar se pide quién retira y **ahí** se crea el
préstamo.

El link **PRÉSTAMO 📋 sólo se ve con el carrito cargado**: el header lo renderiza con `hidden` si
`carrito_count` es 0, `setBadge()` de `gestion.js` lo muestra con el primer RETIRAR y lo vuelve a
esconder cuando el carrito baja a 0. Se oculta (no se saca del DOM) porque de su `data-set-url` sale
la URL que usa el stepper. Hace falta `.g-cart-link[hidden] { display: none; }` en `gestion.css`
porque `.g-btn-outline` fuerza `display: inline-block` y pisaría el `[hidden]` del navegador.

**UI optimista, sin delay**: `gestion.js` cambia la interfaz al instante en el click (muestra el
stepper, ajusta el badge) y sincroniza con el server en segundo plano por `fetch` — no se espera
el round-trip. `carrito_agregar` agrega +1; el `+`/`−` mandan la cantidad exacta a `carrito_set`
(coalesce por widget para no pisar el orden en ráfagas). Sin JS, el `<form>` del botón RETIRAR
hace su POST + redirect normal; el stepper es una mejora que solo aparece con JS. Hooks del JS:
`data-add-carrito` (form RETIRAR), `data-recurso` / `data-stock` / `data-cant` (widget/stepper),
`data-cart-count` (badge), `data-set-url` (URL de `carrito_set`, en el link del PRÉSTAMO 📋).

El carrito vive en `session['carrito']` = `{recurso_id: cantidad}` (por navegador, igual que el
login; claves string al serializar). Helpers: `_carrito()` / `_carrito_guardar()` /
`_carrito_filas()` / `_stock()`. El badge del nav (`carrito_count` en el context processor) cuenta
**ítems distintos** (no unidades). `lista()` y `detalle()` pasan el dict `carrito` para renderizar
el estado inicial del stepper de los recursos ya agregados.

| Ruta | Método | Descripción |
|------|--------|-------------|
| `/gestion/carrito/agregar` | POST | Suma un recurso (`recurso_id` + `cantidad`, default 1) al carrito, topeado al stock. **Con AJAX** (`X-Requested-With: XMLHttpRequest`) devuelve JSON `{ok, count, cantidad}` y no recarga; sin JS redirige a `volver` (si empieza con `/gestion`, si no al listado — evita open redirect) |
| `/gestion/carrito/set` | POST | Fija la cantidad exacta (`recurso_id` + `cantidad`) — la usan el `+`/`−` del stepper. `cantidad<=0` saca el ítem; topea al stock. Devuelve JSON `{ok, count, cantidad}` |
| `/gestion/carrito` | GET | Ver/editar el carrito (UI: "PRÉSTAMO"): cambiar cantidades / quitar. Se llega por el link "editar el préstamo" del checkout. Botón "finalizar préstamo" |
| `/gestion/carrito/actualizar` | POST | Guarda los cambios del préstamo (`cantidad_<id>`; 0 = quitar). Con `accion=finalizar` sigue al checkout |
| `/gestion/carrito/quitar` | POST | Saca un ítem del carrito (`recurso_id`) |
| `/gestion/carrito/vaciar` | POST | Vacía el carrito |
| `/gestion/carrito/finalizar` | GET/POST | Checkout — **destino del PRÉSTAMO 📋 del nav**. GET muestra resumen + form de persona/destino/notas; POST valida persona, crea el préstamo con los ítems, lo vacía y va al detalle. Carrito vacío → redirige a `/carrito` |

El listado de recursos y la ficha usan el atributo HTML `form=` para asociar inputs a un
`<form>` vacío y así no anidar el form de "quitar" dentro del de cantidades (los forms no se
pueden anidar). Recursos borrados que quedaron en el carrito se muestran como "(recurso
eliminado)" y se pueden quitar.

**No se descuenta stock**: `recursos.cantidad` no cambia al prestar/devolver — es
"cuánto hay en total", no "cuánto está libre ahora mismo". Lo prestado se calcula por
consulta con **`pendiente_afuera(cur, rid)`** (suma `cantidad − cantidad_devuelta` de todos los
préstamos abiertos de ese recurso), no se mantiene como contador aparte. El tope del alta mira
`_stock` (el total), así que **se puede prestar más de lo que hay**: el inventario puede estar
desactualizado y el pañol sabe mejor que la DB, así que eso se **avisa y no se bloquea** —
`crear_prestamo` devuelve `ajustes` cuando lo guardado salió distinto de lo pedido. Ver
`dev-log/DECISIONS.md` 2026-08-11.

**`recursos.estado` es un derivado**: 'Retirado' mientras haya algo afuera, 'Disponible' cuando
volvió todo. Lo mantiene **`sincronizar_estado(cur, rid)`, la única función que lo escribe**, y la
llaman todos los caminos: alta (web y agente), devolución total y por ítem, reapertura y borrado
del préstamo. Antes cada camino tenía su versión y el estado quedaba mintiendo — el caso peor era
el botón "devolvió" de la web, que cerraba el préstamo antes de recalcular y dejaba los recursos
'Retirado' para siempre. Respeta lo cargado a mano: sólo devuelve a 'Disponible' lo que él mismo
puso en 'Retirado' (no pisa 'En reparación' ni 'Sin revisar') y nunca toca 'De baja'. `migrar()`
lo corre sobre todos los recursos al arrancar, para emparejar las filas que quedaron desfasadas.

**Devolución por ítem (parcial en cantidad)**: cada `prestamo_items` guarda cuánto se
devolvió en `cantidad_devuelta` (0 = sigue afuera entero). Un ítem está devuelto cuando
`cantidad_devuelta == cantidad`; se puede devolver de a partes (ej: 1 de 3). `fecha_devolucion`
del préstamo **sigue siendo la fuente de verdad de "cerrado"**: `_recalcular_estado()` la
setea sola cuando no queda nada pendiente en ningún ítem, y la limpia si vuelve a haber algo
afuera (por un `reabrir_item`). Así la lista (activos/historial) y el contador del home no
cambian de lógica. Un préstamo con algo devuelto pero no todo figura como "EN PRÉSTAMO ·
parcial". La migración `cantidad_devuelta` es aditiva (`ALTER TABLE` en `migrar()`, arranca en
`'0'`), y **arranca en `'0'` también para los préstamos que ya estaban cerrados**: eso los dejaba
como "devuelto pero con todo pendiente", y al primer `_recalcular_estado()` se reabrían solos.
Por eso `migrar()` corre después un `UPDATE` idempotente que empareja
`cantidad_devuelta = cantidad` en todo ítem de un préstamo con `fecha_devolucion <> ''`.
**Invariante: un préstamo cerrado no tiene pendientes.**

**Un préstamo abierto no significa que todo siga afuera.** Devolver 1 de 4 cosas deja el préstamo
abierto y esa una ya volvió al pañol: lo que manda siempre es el pendiente **por ítem**. De ahí
salen dos reglas que hay que sostener en cualquier vista nueva:
- La sección "quién lo tiene ahora" filtra `pendiente > 0`, no "préstamo abierto" (si no, el
  devuelto sigue figurando prestado con un `0` al lado que nadie lee).
- `devolver_item` con el campo `cantidad` vacío devuelve todo lo pendiente de ese ítem; con un
  número, se topea a lo pendiente; **con basura ("abc", "-5") no se toca nada**. El `max(1, …)`
  que había convertía cualquier entrada inválida en una devolución de 1 unidad que nadie pidió.

**Routing de `/gestion/prestamos*` vs `/gestion/<slug>*`**: son rutas estáticas
(`/gestion/prestamos`, `/gestion/prestamos/<id>`, etc.) que compiten con las dinámicas
del CRUD genérico (`/gestion/<slug>`, `/gestion/<slug>/<id>`) sobre las mismas URLs.
Werkzeug prioriza las rutas más específicas (estáticas) sobre el converter `<slug>`,
así que `/gestion/prestamos/5` siempre despacha a `prestamo_detalle`, nunca a `detalle`
con `slug='prestamos'` — verificado en runtime. Por eso `nav_entidades` y las cards del
home tratan `slug == 'prestamos'` como caso especial al construir los links (usan
`gestion.prestamos_lista`, no `gestion.lista`). El "+ nuevo retiro" del home y de la lista de
préstamos apunta al **listado de recursos** (ahí arranca el carrito), no a un form de alta.

## Respaldos (`backups/`)

`gestion.db` es la única DB con datos propios: no se regenera desde Sheets y está en
`.gitignore`, así que **si el archivo se pierde no hay commit ni fuente externa de la
cual recuperarla**. Por eso `init_db()` arranca llamando a `respaldos.respaldar()`.

- Copia a `backups/gestion-YYYYMMDD-HHMMSS-ffffff.db` con la **API `backup()` de
  sqlite3**, no `shutil.copy`: garantiza una copia consistente aunque otro proceso
  esté escribiendo. Los microsegundos evitan que dos respaldos del mismo segundo se
  pisen y mantienen el orden alfabético igual al cronológico.
- **No respalda una DB sin recursos.** Un respaldo vacío encima de los buenos sería
  justo lo que arruinaría la recuperación.
- **No duplica**: si el contenido no cambió desde el último respaldo, lo descarta.
- **Retención** (`respaldos._a_borrar`): los últimos `BACKUP_MAX` (20) **más el primero de cada
  día**. Sin la regla diaria, una tarde de reinicios depurando empuja fuera de la
  rotación todo lo viejo — que es exactamente lo que uno querría recuperar.

Los respaldos caen bajo `*.db` del `.gitignore`; no se versionan ni se pushean.

## Seed

`init_db()` crea las tablas y, si `recursos` está vacía, carga el ejemplo del documento
de diseño: 5 recursos, conjunto "Banco de ensayo solar" (panel + estructura +
inclinómetro) y actividad "Medición de panel solar según inclinación" (usa el conjunto +
multímetro + pinza).

**El seed no es incondicional.** Una DB vacía es ambigua: puede ser una instalación
nueva o datos perdidos. Los respaldos desempatan — si `respaldos()` devuelve algo,
`init_db()` **levanta `RuntimeError` con las instrucciones de restauración en vez de
sembrar**, porque sembrar taparía la pérdida en silencio (que es lo que pasó el
2026-08-08: se trabajó un día entero contra los 5 de ejemplo sin notarlo).

Para empezar de cero a propósito: `GESTION_SEED=1`. En un deploy limpio (Render,
PythonAnywhere) no hay respaldos, así que el primer arranque siembra normalmente.

## Permisos

El área declara tres, y el verbo es lo que los hace entrar solos en los perfiles:

| clave | verbo | qué habilita |
|---|---|---|
| `gestion.leer` | leer | ver inventario, actividades y préstamos. Es el permiso base del blueprint |
| `gestion.editar` | escribir | `nuevo`/`editar`/`eliminar`/fotos, **todo el carrito** y las mutaciones de préstamos |
| `gestion.alias` | admin | `/gestion/alias`, la tabla de solo lectura con el alias oculto de cada recurso. Verbo `admin`: no entra en ningún preset de interno, solo lo tiene el comodín `'*'` (mismo criterio que `historia.personas`) |

`PERMISO_ESCRITURA` lo aplica solo `crud.registrar_rutas` a sus cinco rutas. **El bloque de
préstamos/carrito no pasa por el motor**, así que sus rutas llevan `@accesos.requiere(...)` a mano,
una por una: `carrito`, `carrito_agregar`, `carrito_set`, `carrito_quitar`, `carrito_vaciar`,
`carrito_actualizar`, `carrito_finalizar`, `prestamo_devolver`, `prestamo_devolver_item`,
`prestamo_reabrir`, `prestamo_reabrir_item`, `prestamo_eliminar`. Las dos que consultan
(`prestamos_lista`, `prestamo_detalle`) se quedan con el permiso base. Las dos AJAX
(`carrito_agregar`, `carrito_set`) piden el 403 en JSON, que es lo que el `fetch` de `gestion.js`
sabe leer.

Con `gestion.leer` a secas la UI queda en modo consulta: sin CREAR, sin Editar, sin ELIMINAR, sin
subida de fotos y sin el link del carrito. El motor entero de accesos está en
`agent_docs/accesos.md`.

Es una traba de desarrollo, no seguridad completa: sin usuarios ni auditoría, sin
CSRF, sin límite de intentos. Decisión 2026-07-19 (ver `dev-log/DECISIONS.md`).
El SPA de horarios y `/api/*` siguen sin auth.

