# Sistema de Gestión de Conocimiento (`/gestion`)

Módulo independiente del sistema de horarios: la "memoria técnica viva" de la escuela.
Registra recursos, conjuntos, actividades y proyectos, y los conecta entre sí (red de
conocimiento, no carpetas aisladas). Los archivos reales (fotos, planos, guías) viven
en Google Drive; acá solo se guardan links (`drive_url`).

## Arquitectura

- **`gestion.py`** — todo el módulo: blueprint Flask (`bp`, prefix `/gestion`), schema,
  seed y rutas. Server-rendered con Jinja. El JS propio es `static/gestion.js`, con dos
  mejoras progressive-enhancement: búsqueda en vivo del listado y agregar al carrito por
  AJAX (ver abajo); el resto es HTML puro con forms + redirects.
- **`gestion.db`** — SQLite propia, separada de `escuela.db`. **No** se regenera desde
  Sheets y `/api/actualizar` no la toca. Es la única DB con datos propios de la app
  (en hosting efímero tipo Render se pierde en cada restart; en PythonAnywhere persiste).
- **`templates/gestion/`** — `base.html` (layout + nav), `home.html`, `lista.html`,
  `form.html`, `detalle.html`. Los tres últimos son **genéricos**: se renderizan a partir
  de la config declarativa de cada entidad. `prestamos_lista.html`, `prestamos_detalle.html`,
  `carrito.html`, `carrito_finalizar.html` son específicos (préstamos no entra en `ENTIDADES`:
  tiene ítems con cantidad y un ciclo prestado→devuelto que el trío genérico no modela, y el
  alta usa un carrito en sesión que el usuario ve como "PRÉSTAMO" en la UI).
- **`static/gestion.css`** — hoja standalone (paleta blueprint copiada, no importa
  `style.css` para que los dos sistemas no se pisen). Sin modo oscuro.
- **`static/gestion.js`** — único JS del módulo: búsqueda en vivo del listado (filtrado
  local, ~35 líneas vanilla, sin build step). Cargado en `base.html` con `defer`;
  no hace nada fuera de las páginas de listado (guarda por existencia de elementos).
- Integración: `app.py` hace `app.register_blueprint(gestion.bp)` + `gestion.init_db()`
  en import (funciona bajo gunicorn/WSGI). No hay link visible desde el SPA principal:
  `/gestion` es deliberadamente "oculto", se accede escribiendo la URL (decisión
  2026-07-17, ver `dev-log/DECISIONS.md`). `base.html` sí tiene el link de vuelta al SPA.

## Modelo de datos (gestion.db)

| Tabla | Campos |
|-------|--------|
| `recursos` | id, nombre, tipo, descripcion, ubicacion, estado, drive_url, cantidad, valor, fecha_revision, **fotos** |
| `conjuntos` | id, nombre, descripcion, uso_tipico, drive_url, **fotos** |
| `actividades` | id, nombre, objetivo, descripcion, duracion, curso, drive_url, **fotos** |
| `proyectos` | id, nombre, descripcion, fecha, participantes, estado, drive_url, **fotos** |
| `hitos` | id, **titulo**, descripcion, fecha, tipo, nivel, etiquetas, protagonistas, drive_url, **fotos** |
| `personas` | id, nombre, **nombre_norm**, descripcion, fecha_actualizada, drive_url, **fotos** |

**Galería de fotos** (`fotos` en cada tabla): array JSON con objetos `{b64, tipo, fecha}`.
- `b64`: imagen codificada en base64 (embedded, sin servicios externos)
- `tipo`: content-type (ej: `image/png`)
- `fecha`: timestamp ISO de cuándo se subió
- Upload: botón en ficha de detalle → POST `/<slug>/<id>/foto` → sube imagen, convierte a base64, guarda en DB
- Renderizado: galería grid responsive (150px minmax) con preview nativo en el HTML

M2M (con `UNIQUE` por par): `conjunto_recursos`, `actividad_recursos`,
`actividad_conjuntos`, `proyecto_recursos`, `persona_proyectos`, `persona_hitos`.
Las dos últimas llevan además índice por `persona_id`.

### Personas — la memoria de quién hizo la escuela

`personas` es un grafo, no una lista: una fila por persona (con una **semblanza** en prosa en
`descripcion`) y los hilos M2M que la unen a `proyectos` e `hitos`. La ficha de detalle muestra
esos hilos en las dos direcciones, y `proyectos`/`hitos` muestran la inversa ("Personas que
participaron" / "Personas involucradas").

**`hitos` declara `rel_personas` además del texto libre `protagonistas`** — son dos cosas
distintas y conviven a propósito: `protagonistas` es una línea de texto que admite cursos
("6° B") y gente que no tiene ficha, y `rel_personas` es el vínculo navegable con la fila de
`personas`. La relación está declarada **de los dos lados** sobre la misma tabla
`persona_hitos` (`personas.rel_hitos` y `hitos.rel_personas`); es la única del sistema que es
simétrica, y por eso el hito se puede editar desde su propio formulario y `vincular_entidad`
acepta cualquiera de las dos direcciones.

**La identidad es `nombre_norm`, no `nombre`** — columna derivada con un `UNIQUE` encima, que
calcula `gestion.clave_persona()` (público): saca puntuación, normaliza con `_norm` y **ordena
las palabras alfabéticamente**. Sin ese orden, "Juan Pablo Crivari" (como lo tipea una persona)
y "CRIVARI JUAN PABLO" (como sale de `limpiar_profesor()` en los horarios) serían dos fichas de
la misma persona con los hilos repartidos. `nombre` guarda la grafía para mostrar. El precio es
que dos nombres que son la misma bolsa de palabras chocan; se prefirió ese error visible al
duplicado silencioso — ver `dev-log/DECISIONS.md` 2026-08-08.

**No hay sincronización con `escuela.db`.** Los horarios se regeneran desde Sheets; `personas`
es memoria permanente y **tiene que sobrevivir** a que alguien salga del padrón. No hay FK entre
las dos DBs: el puente es `clave_persona()` sobre el nombre.

`fecha_actualizada` también es derivada (se pisa en cada guardado) — ninguna de las dos está en
`campos`, las agrega `_derivados()` en los dos caminos de guardado (`_guardar` y
`guardar_entidad_sin_request`).

**No hay campo `rol`** (existió un rato y se sacó el 2026-08-08, con `DROP COLUMN` en
`_migrar`): una taxonomía fija se queda corta enseguida — alguien es docente y ex alumno a la
vez, o pasa de preceptor a directivo — y la semblanza ya lo dice mejor en prosa. Queda como
recordatorio que `descripcion` es un juicio sobre una persona real, y que esto vive detrás de
una clave compartida cuyo default está en un repo público: escribir semblanzas de alumnos
menores pide una auth de verdad primero.

| `prestamos` | id, persona, destino, notas, fecha_salida, fecha_devolucion |
| `prestamo_items` | prestamo_id, recurso_id, cantidad, cantidad_devuelta (M2M con cantidad, `UNIQUE(prestamo_id, recurso_id)`) |

Estados: recursos = Disponible / En uso / En reparación / De baja / Sin revisar;
proyectos = Activo / Pausado / Terminado.
Valor (recursos): "" / Básico / Secundario / Alto valor — es la *importancia* del recurso
dentro del inventario, no su precio (se llamaba `utilidad`, renombrada 2026-08-08).
`cantidad` y `fecha_revision` son TEXT. **`fecha_revision` se precarga con la fecha de hoy
en todo alta de recurso**, por los dos caminos: el form web (`_valores_iniciales()` en el
GET de `/recursos/nuevo`) y el chat (`_normalizar_borrador()` en `agente.py`, antes de
calcular el token, para que la fecha aparezca en la ficha y el usuario la vea y la pueda
cambiar). Dar de alta un recurso es un control de inventario; antes quedaba vacía y casi
ningún recurso terminaba con fecha. Formato `gestion.FORMATO_FECHA_REVISION` = `%d/%m/%Y`
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
hace de nombre visible. Sólo `hitos` la declara distinta (`'titulo'`). Todas las lecturas del
CRUD genérico van por **`_select(cfg)`**, que agrega `titulo AS nombre` al `SELECT`, así que
templates, `buscar_entidad_sin_request`, `snapshot_entidad` y `agente.py` siguen leyendo
`fila['nombre']` sin enterarse. Las escrituras y la validación de obligatorio usan
`_campo_nombre(cfg)`. Sin este mecanismo `/gestion/hitos` tiraba `no such column: nombre` y su
alta fallaba siempre con "El nombre es obligatorio" (roto desde `829ea57`, arreglado 2026-08-08).

Columnas **derivadas** (calculadas por la app, fuera de `campos` y del form): las agrega
`_derivados(slug, valores)` en los dos caminos de guardado. Hoy sólo `personas`
(`nombre_norm`, `fecha_actualizada`).

Para agregar un campo: sumarlo al `SCHEMA`,
a `campos` y a la lista de `_migrar()` — `init_db()` hace el `ALTER TABLE` aditivo
automáticamente en DBs existentes (así entraron cantidad/valor/fecha_revision).
Para **renombrar** uno, además del `SCHEMA` y `campos` va un `ALTER TABLE ... RENAME COLUMN`
guardado por `PRAGMA table_info` en `_migrar()`, **antes** del loop aditivo (si no, el aditivo
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

`slug` ∈ {recursos, conjuntos, actividades, proyectos, hitos, personas}; otro valor → 404.
(El agente, en cambio, sólo llega a los cuatro primeros — ver "Entidades que el agente no ve".)

## Búsqueda tolerante (`?q=` en `lista()`)

No es el `LIKE` literal de SQL: `lista()` trae todas las filas y las filtra/ordena en
Python con `_puntaje_busqueda()`. Perdona **acentos y mayúsculas** (normaliza con `_norm`)
y **typos** (similitud difusa vía `difflib.SequenceMatcher`, sin dependencias). Reglas:
substring normalizado siempre puntúa por encima de los difusos; la similitud difusa solo
entra para queries de 3+ caracteres, con umbral `UMBRAL_SIMILITUD` (**0.68**, medido contra
el inventario real — ver `dev-log/DECISIONS.md` 2026-08-08). Compara la query
contra el nombre, cada palabra del nombre, y la descripción. Con ~decenas de filas por
entidad el filtrado en Python es despreciable; si alguna tabla creciera a miles habría que
reconsiderar (índice, FTS). Aplica a las 4 entidades genéricas; los préstamos usan su propio
`LIKE` en SQL. Decisión 2026-07-21 (ver `dev-log/DECISIONS.md`).

**Búsqueda en vivo (client-side, `static/gestion.js`)**: además del filtrado server-side,
el listado filtra en el navegador mientras se escribe, sin recargar ni ir al servidor. La
ruta emite por fila un atributo `data-buscar` con el texto ya normalizado por Python
(`_norm(nombre + descripcion)`), y el JS filtra por substring normalizado (repite la misma
normalización de acentos/mayúsculas). Es progressive enhancement: sin JS, el form sigue
haciendo la búsqueda difusa server-side. Con JS, el botón BUSCAR se oculta y Enter no recarga.
La capa en vivo **no** tiene la tolerancia difusa a typos (solo substring) — a propósito: al
ver los resultados achicarse letra por letra uno corrige el typo solo; el fuzzy server-side
queda como respaldo. Decisión 2026-07-21 (ver `dev-log/DECISIONS.md`).

Relaciones mostradas en detalle (`_secciones_detalle`): recurso → conjuntos que lo
incluyen / actividades que lo usan / proyectos relacionados / **historial de préstamos**;
conjunto → recursos incluidos / actividades que lo usan; actividad → conjuntos + recursos
utilizados; proyecto → recursos generados.

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
sin tope). Arriba de todo, en el nav, hay un **PRÉSTAMO 📋** con el contador que lleva directo al
checkout (`/carrito/finalizar`). Recién al finalizar se pide quién retira y **ahí** se crea el
préstamo.

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
consulta (`cantidad − cantidad_devuelta` sobre `prestamo_items`), no se mantiene como
contador aparte.

**Devolución por ítem (parcial en cantidad)**: cada `prestamo_items` guarda cuánto se
devolvió en `cantidad_devuelta` (0 = sigue afuera entero). Un ítem está devuelto cuando
`cantidad_devuelta == cantidad`; se puede devolver de a partes (ej: 1 de 3). `fecha_devolucion`
del préstamo **sigue siendo la fuente de verdad de "cerrado"**: `_recalcular_estado()` la
setea sola cuando no queda nada pendiente en ningún ítem, y la limpia si vuelve a haber algo
afuera (por un `reabrir_item`). Así la lista (activos/historial) y el contador del home no
cambian de lógica. Un préstamo con algo devuelto pero no todo figura como "EN PRÉSTAMO ·
parcial". La migración `cantidad_devuelta` es aditiva (`ALTER TABLE` en `_migrar`, arranca en
`'0'` para préstamos previos).

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
cual recuperarla**. Por eso `init_db()` arranca llamando a `respaldar_db()`.

- Copia a `backups/gestion-YYYYMMDD-HHMMSS-ffffff.db` con la **API `backup()` de
  sqlite3**, no `shutil.copy`: garantiza una copia consistente aunque otro proceso
  esté escribiendo. Los microsegundos evitan que dos respaldos del mismo segundo se
  pisen y mantienen el orden alfabético igual al cronológico.
- **No respalda una DB sin recursos.** Un respaldo vacío encima de los buenos sería
  justo lo que arruinaría la recuperación.
- **No duplica**: si el contenido no cambió desde el último respaldo, lo descarta.
- **Retención** (`_a_borrar`): los últimos `BACKUP_MAX` (20) **más el primero de cada
  día**. Sin la regla diaria, una tarde de reinicios depurando empuja fuera de la
  rotación todo lo viejo — que es exactamente lo que uno querría recuperar.

Los respaldos caen bajo `*.db` del `.gitignore`; no se versionan ni se pushean.

## Seed

`init_db()` crea las tablas y, si `recursos` está vacía, carga el ejemplo del documento
de diseño: 5 recursos, conjunto "Banco de ensayo solar" (panel + estructura +
inclinómetro), actividad "Medición de panel solar según inclinación" (usa el conjunto +
multímetro + pinza) y proyecto "Construcción del banco de ensayo solar".

**El seed no es incondicional.** Una DB vacía es ambigua: puede ser una instalación
nueva o datos perdidos. Los respaldos desempatan — si `respaldos()` devuelve algo,
`init_db()` **levanta `RuntimeError` con las instrucciones de restauración en vez de
sembrar**, porque sembrar taparía la pérdida en silencio (que es lo que pasó el
2026-08-08: se trabajó un día entero contra los 5 de ejemplo sin notarlo).

Para empezar de cero a propósito: `GESTION_SEED=1`. En un deploy limpio (Render,
PythonAnywhere) no hay respaldos, así que el primer arranque siembra normalmente.

## Auth provisoria (contraseña compartida)

Todo `/gestion` está detrás de una contraseña compartida: `bp.before_request` exige
`session['gestion_ok']` y redirige a `/gestion/login` (excepto el propio login).
La clave sale de la env var `GESTION_CLAVE`; **el default hardcodeado en `gestion.py`
es público** (el repo lo es) — en el hosting hay que setear `GESTION_CLAVE` y
`SECRET_KEY` (firma de la cookie de sesión, se setea en `app.py`) como env vars.

Es una traba de desarrollo, no seguridad completa: sin usuarios ni auditoría, sin
CSRF, sin límite de intentos. Decisión 2026-07-19 (ver `dev-log/DECISIONS.md`).
El SPA de horarios y `/api/*` siguen sin auth.

## Asistente conversacional con tool-calling (agente.py)

Módulo independiente (`agente.py`, blueprint `/gestion/agente`) que expone un chat
conversacional contra el LLM configurado (DeepSeek por defecto, Anthropic/OpenAI/Groq/Ollama
según `AGENTE_PROVIDER` — ver "Configuración"). El usuario puede hablar con la app en lenguaje
natural en vez de hacer click en formularios: consultar horarios, crear recursos, fotografiar
etiquetas y cargarlas, gestionar préstamos. Todo con auditoría de escrituras en `agente_log`.

**Acceso**: dos vistas del mismo chat, ambas visibles solo tras iniciar sesión en
`/gestion` (reusan `session['gestion_ok']`):
- Botón "🤖 ASISTENTE" en el header → widget flotante, para consultar sin salir de la
  página en la que se está.
- Pestaña "🤖 ASISTENTE" en el nav → `/gestion/agente/`, el chat a pantalla completa.
  Es la vista pensada para el celular, que es donde más se usa el asistente.

### Arquitectura

- **`agente.py`** — blueprint completo: gate de sesión, esquemas de tools JSON, ejecutores,
  loop de tool-calling contra Anthropic con manejo de tool use, endpoints Flask.
- **`POST /gestion/agente/chat`** — acepta `{mensaje, imagen?}` (imagen en base64 o data URL);
  retorna `{respuesta}`. El backend llama al modelo con el mensaje + tools disponibles, ejecuta
  lo que pida (tools de lectura y escritura), repite hasta respuesta final, audita
  escrituras en `agente_log`. `mensaje` puede venir vacío **si viene `imagen`** (mandar solo
  la foto de una etiqueta es un caso normal); vacío y sin foto es `400`. Ver "Alta desde foto".
- **`GET /gestion/agente/historial`** — devuelve `{mensajes: [{rol, texto}], confirmaciones}`
  para repintar el chat al cargar la página. `gestion-agente.js` lo llama en el
  `DOMContentLoaded` (`cargarHistorial()`). **Hace falta desde que la conversación pasó a
  `gestion.db`**: el servidor la recuerda entre páginas, pero el chat se dibuja de cero en
  cada carga, así que el historial existía y no se veía. Devuelve también los botones de las
  altas que hayan quedado sin confirmar — si no, navegar a otra página dejaba las fichas
  vivas en el servidor y sin forma de darles OK. `_texto_visible()` aplana los bloques de
  contenido y saca el `(refiriéndote a: X)` que `chat()` le agrega al mensaje del usuario,
  que es una pista para el modelo y no algo que el usuario escribió.
- **`POST /gestion/agente/confirmar`** — acepta `{token}` de una ficha de alta pendiente y
  la guarda sin pasar por el modelo. `409` si el token ya se usó, se reinició la
  conversación, o quedó desplazado por fichas más nuevas. Ver "Alta con ficha de
  confirmación".
- **`POST /gestion/agente/reset`** — limpia `session['agente_historial']` y
  `session['agente_entidad_actual']`; usado por el botón ↺ del widget para arrancar una
  conversación nueva sin arrastrar contexto viejo.
- **`GET /gestion/agente/`** (`chat_page`) — la pestaña del chat a pantalla completa
  (`templates/gestion/agente_chat.html`, extiende `base.html`).
- **`GET /gestion/agente/log`** — tabla de auditoría (últimas 50 escrituras), con snapshot
  "antes" visible para poder restaurar manualmente si el agente cometió un error.

**Gate de sesión** (`_requiere_clave`): los endpoints JSON (`/chat`, `/reset`) devuelven
`401` sin sesión, que es lo que el `fetch` del frontend sabe manejar. Los endpoints que
devuelven HTML —listados en `_ENDPOINTS_PAGINA`— redirigen a `/gestion/login?next=...`,
porque entrar por link directo a `/gestion/agente/` desde el celular es el caso normal y
un 401 pelado ahí es un callejón sin salida.

**Context processor**: `agente.bp` registra su propio `_contexto_base()` que delega en el
de `gestion.bp`. Los context processors de un blueprint no corren para requests de otro,
y `base.html` necesita `escuela_nombre`/`escuela_logo`/`escuela_version`/`nav_entidades`/
`carrito_count` — sin esto el header de las páginas del agente renderiza vacío.

### Las dos vistas del chat

Comparten markup y JS; lo único que cambia es el contenedor.

| Archivo | Rol |
|---|---|
| `templates/gestion/_agente_chat_core.html` | El chat en sí: `#agente-messages` + área de input (texto, 📷 imagen, enviar, link a auditoría). **Único lugar donde se edita el markup del chat.** |
| `templates/gestion/_agente_widget.html` | Widget flotante = header propio (↺ reiniciar, ⤢ abrir a pantalla completa, ✕ cerrar) + el core. |
| `templates/gestion/agente_chat.html` | Pestaña = barra de título + el core, dentro de `base.html`. |
| `static/gestion-agente.js` | Sirve a las dos. |

Los IDs del core (`agente-messages`, `agente-input`, `agente-send-btn`, `agente-reset-btn`…)
son únicos y el JS los busca con `getElementById` — por eso **las dos vistas nunca se
renderizan juntas**: `base.html` omite el include del widget (y el botón del header) cuando
`activo == 'agente'`. Si se agrega otra vista del chat, mantener esa invariante.

Progressive enhancement: con JS es fluido, sin JS el chat no funciona pero el resto del
servidor sigue andando. Las respuestas se renderizan como markdown liviano
(`renderMarkdown()` en `gestion-agente.js`: negrita, listas, tablas) — el modelo devuelve
Markdown y sin esto se veía como un bloque de texto con `**`/`|` crudos.

### Diseño para celular

El asistente se usa mayormente desde el teléfono, en el pasillo. Lo que eso impone
(estilos en `gestion.css`, sección "PESTAÑA DEDICADA AL CHAT" y las media queries de
`max-width: 700px`):

- **`body.g-chat-page`** (la clase la pone `base.html` cuando `activo == 'agente'`) arma
  una cadena flex `.g-bg → .g-shell → .g-main → .agente-page` con `min-height: 0`, de modo
  que **scrollea solo el historial y nunca la página**. Si scrolleara el body, al abrir el
  teclado el input se iría abajo del fold y habría que ir a buscarlo.
- **`100dvh`, no `100vh`** — en iOS/Chrome mobile `100vh` incluye la barra del navegador
  que en realidad tapa la pantalla, y el input quedaba cortado abajo.
- **`.agente-input { font-size: 16px }` en mobile es obligatorio.** Con menos, iOS hace
  zoom al enfocar el campo, descuadra el layout y no vuelve solo. No bajar ese valor.
- **Enter envía el mensaje en todas las pantallas**, táctiles incluidas (Shift+Enter hace
  salto de línea; el `<textarea>` lleva `enterkeyhint="send"`). Se descarta el Enter con
  `isComposing` (IME). Antes en táctil Enter insertaba salto y se enviaba solo con el botón,
  para evitar mandar a medio escribir con el teclado virtual; se revirtió a pedido — el
  botón de enviar sigue estando.
- **No se autoenfoca el input en táctil**, para que abrir el chat no abra el teclado.
- **`visualViewport.resize`** vuelve a scrollear al final cuando sube el teclado
  (`window.onresize` no dispara en iOS).
- `env(safe-area-inset-bottom)` en el área de input (requiere el `viewport-fit=cover` que
  agrega el `<meta viewport>` de `base.html`) para no quedar abajo de la barra gestual.
- Objetivos táctiles de 44px, header comprimido, footer oculto, y el nav de 8 pestañas
  scrollea horizontalmente en vez de envolver en tres filas.

### Tools

**Lectura** (no se auditan, siempre disponibles):
- `buscar_profesor(query)` — resolución difusa de nombre, **sobre los docentes de los
  horarios**. Si el nombre también coincide con una persona con ficha, devuelve
  `{docentes, personas_con_ficha, aviso}` en vez de la lista pelada (ver "Dos padrones")
- `horario_profesor(nombre)` / `horario_curso(curso, division)` / `horario_aula(aula)`
  — horarios agrupados por día
- `aulas_libres()` — aulas desocupadas ahora, agrupadas por piso
- `buscar_entidad(slug, query)` — búsqueda de recursos/conjuntos/actividades/proyectos
  (calidad del match explícita, ver abajo)
- `listar_todos(slug)` — lista completa de nombres + id; **fallback** de `buscar_entidad`
  cuando no hay ningún match `exacto`, ver abajo
- `detalle_entidad(slug, id)` — detalle completo + relaciones
- `listar_prestamos(persona?)` / `detalle_prestamo(id)` — estados de préstamos
- `consultar_historia(tema)` — lore de la escuela y guiños internos, ver abajo
- `leer_foto()` — lee la foto adjuntada en ESTE turno y devuelve lo que dice, en texto. No
  toca la base (por eso está acá) pero **sí gasta la API de visión**, así que el prompt le
  pide llamarla solo cuando necesita los datos, nunca para adjuntar. Ver "Alta desde foto"

**Escritura** (se auditan, requieren `session['gestion_ok']`, guardan snapshot "antes"):
- `crear_entidad(slug, campos)` — alta **en dos pasos con ficha de confirmación**, ver abajo
- `editar_entidad(slug, id, campos)` — update
- `adjuntar_foto(slug, id)` — guarda la foto de ESTE turno en la galería de un registro que ya
  existe. Sin ficha de confirmación (es aditivo); la imagen sale de `contexto_turno`, no de un
  parámetro
- `vincular_entidad` / `desvincular_entidad` — gestionar M2M
- `crear_prestamo(persona, destino?, notas?, items)` — crear préstamo (cantidad topeada
  a stock, recurso por nombre o id con resolución ambigua)
- `finalizar_prestamo(id, items?)` — devolución total o parcial (calcula estado automáticamente)
- `reabrir_prestamo(id, items?)` — deshace una devolución
- `eliminar_entidad` / `eliminar_prestamo` — **requieren confirmación en turno separado** (el
  system prompt instruye a Claude a no ejecutar en el mismo turno en que se solicita, sino
  responder primero qué va a borrar y esperar confirmación)

### Alta con ficha de confirmación (`crear_entidad`)

Ningún alta se escribe sin que el usuario haya visto antes, campo por campo, lo que va a
quedar guardado. Circuito:

1. El asistente llama a `crear_entidad`. **La primera llamada con un juego de campos no
   escribe nada**: devuelve `{requiere_confirmacion: true, ficha, campos_vacios,
   redactados_por_vos, instruccion}` (y `tipos_en_uso` si el slug es `recursos`, o
   `antes_de_mostrar` si es `hitos` y la ficha salió con agujeros evitables).
2. El asistente muestra la ficha y, debajo, 1 a 3 preguntas cortas por lo que falta
   ("¿de qué medida es?", "¿sabés la marca?"). **No son bloqueantes**: si el usuario no
   contesta, se guarda igual — está en el prompt y en el `instruccion` de la ficha.
3. Si el usuario pide cambios, el asistente vuelve a llamar con los campos corregidos y
   sale otra ficha (con su botón). Se repite hasta el OK.
4. **El OK es un botón, no una respuesta escrita.** `/chat` devuelve además
   `confirmaciones: [{token, etiqueta, nombre}, …]` con las fichas pendientes, y
   `gestion-agente.js` pinta un botón verde por ficha debajo del mensaje
   (`agregarConfirmaciones()`). El botón pega en **`POST /gestion/agente/confirmar`** con
   su token: el alta se resuelve ahí, en Python, **sin llamar al modelo** — instantánea,
   gratis, y sin margen para que el modelo escriba otra cosa. Los campos salen de la
   sesión, nunca del request. El resultado se agrega al `agente_historial` como un turno
   más, con el nombre de lo que se guardó, para que el asistente sepa después que eso ya
   está y qué sigue pendiente.
5. Escribir "dale, guardalo" también funciona: el modelo llama **otra vez con exactamente
   los mismos campos** y el hash coincide. Los dos caminos terminan en el mismo lugar.

**Varias altas en un turno** (`_confirmaciones`). "Creá a Pablo y a Ezequiel" son dos
llamadas a `crear_entidad` en la misma respuesta y **dos fichas con dos botones**. Antes se
mandaba una sola confirmación —la última— y las anteriores quedaban vivas en la sesión sin
ningún botón que las guardara: el usuario veía las dos fichas, confirmaba, y se daba de alta
una sola sin que nada avisara. Tres reglas sostienen el caso:
- `contexto_turno['fichas_mostradas']` es un dict con **todas** las del turno, y `/chat`
  arma un botón por cada una.
- Se devuelven **todas las pendientes, no solo las de este turno**: el front borra los
  botones apenas el usuario escribe (`quitarConfirmaciones()`), así que una ficha sin
  confirmar tiene que reaparecer debajo de la respuesta siguiente o se pierde igual.
  Reaparecer no escribe nada: confirmar es siempre un click explícito.
- Si dos fichas pendientes son de la **misma entidad** (el usuario pidió un cambio y el
  modelo la rearmó), se muestra solo la última: son la misma alta, y dos botones con el
  mismo nombre y distinto contenido no hay forma de distinguirlos.

El nombre va **dentro** del botón ("✅ Guardar persona: Pablo Errio"): con dos o tres
seguidos, "Guardar persona" repetido no dice cuál es cuál.

**Cómo se sabe que el usuario aprobó** (`_token_ficha`): cada ficha se identifica por un
SHA-1 de su contenido (`slug` + los campos normalizados). Una llamada escribe solo si su
hash ya se mostró en un turno **anterior**. Consecuencias buscadas:
- Cambiar un solo campo entre la ficha y el alta da otro hash → vuelve a la ficha. No se
  puede guardar algo distinto de lo que el usuario leyó.
- Una ficha mostrada en el turno en curso no habilita nada: el loop ejecuta todas las
  tools antes de devolver una palabra, así que el usuario todavía no la vio.
- El hash se **consume** al escribir; repetir la llamada arranca de nuevo por la ficha en
  vez de duplicar el recurso.

Los hashes viven en `session['agente_fichas']` — un dict `{token: {slug, campos}}`, tope 3
porque la sesión de Flask es una cookie firmada de ~4KB y el historial ya ocupa lo suyo.
El endpoint `/chat` lo carga en `contexto_turno['fichas_previas']` antes de llamar al modelo
y lo vuelve a guardar después; `/confirmar` lee de ahí los campos a escribir.
**Tiene que ser la sesión y no el turno**: los resultados de tools no se persisten en
`agente_historial`, así que en el turno siguiente el modelo no tiene la ficha a la vista —
un token que tuviera que repetir de memoria no le llega, y el alta quedaba trabada en un
bucle de fichas (así falló el primer diseño). `/reset` limpia `agente_fichas`.

Las fichas **no se auditan** en `agente_log`: no tocaron la base, y esa tabla existe para
deshacer cambios reales. Sí se audita el alta efectiva.

`contexto_turno` es el dict que `chat_with_tools()` pasa a todas las tools de un mismo
turno (`ejecutar_tool(tool, input, contexto_turno)`), para lo que hay que decidir mirando
el turno entero y no la llamada aislada.

**Campos que redacta el asistente** (`CAMPOS_REDACTADOS`): `nombre`, `tipo` y `descripcion`
los escribe él a partir de lo que contó el usuario — no se los pide literalmente ("¿qué
descripción le pongo?"). Van marcados en la ficha como `redactados_por_vos` para que el
usuario los lea sabiendo que son propuestos. `tipo` es texto libre, así que la ficha de
`recursos` incluye `tipos_en_uso` (`SELECT DISTINCT tipo`) para que reuse una categoría
existente en vez de inventar un sinónimo nuevo por cada alta.

**`antes_de_mostrar` — la ficha de hito que se revisa sola.** La ficha de `hitos` puede
volver con una lista extra de avisos dirigidos al modelo (`_recordatorio_hito()`), que el
prompt le manda resolver **antes** de escribirle nada al usuario. Existe porque el modelo
armaba el hito "Pablo Errio y Ezequiel Toñanes — Certamen Nacional OMA" con
`protagonistas` **vacío** (los nombres quedaban solo en el título, así que el vínculo con
las personas no lo creaba nadie) y con `nivel` vacío pese a que el usuario acababa de decir
"crítico" — y encima se lo volvía a preguntar. Los avisos son dos:
- Si `protagonistas` está vacío, se cruzan `titulo` + `descripcion` contra la tabla
  `personas` (`_personas_nombradas_en()`, ver abajo) y el aviso **nombra a las que
  encontró**: es un dato concreto, no un "acordate de completar".
- Si ese cruce no encuentra a nadie, el aviso lista **el padrón entero de personas con
  ficha** (hasta `PADRON_EN_AVISO` = 40; más que eso lo manda a `buscar_entidad`). Es para
  que un "nati" o un "el Errio" lo resuelva con los nombres a la vista en vez de irse a
  buscar docentes a los horarios, que es otro padrón.
- Si falta `nivel`, `fecha` o `tipo`, el aviso le recuerda cargarlo si el usuario ya lo dijo
  y preguntar solo si no.

**`_personas_nombradas_en(texto)`** compara con `gestion._norm` y exige que estén **todas**
las palabras del nombre (>2 letras), en cualquier orden — matchea "Errio Pablo" pero un
"Pablo" suelto no alcanza: con dos Pablos, vincular al equivocado es peor que no vincular.
**`_personas_parecidas(query)`** es su complemento suelto: acepta coincidencia parcial
("nati" → "Natalia Boo Fiad"). Se puede permitir porque su resultado es un **aviso para que
el modelo pregunte**, no un vínculo que se escriba solo — quien decide a quién se vincula
sigue siendo la regla estricta.

### Dos padrones de personas, y el cruce en las dos direcciones

Los docentes salen de **`escuela.db`** (los horarios) y las fichas de personas de
**`gestion.db`**. Son padrones que **no se superponen**: un alumno que ganó una olimpiada, un
egresado o un ex director tienen ficha y no dan clases; una profesora que nadie cargó todavía
da clases y no tiene ficha. El modelo los mezclaba, y el prompt empujaba para el lado de los
horarios — la sección de préstamos le **inyecta** la lista de PERSONAS CONOCIDAS
(`_personas_conocidas()`, docentes + no docentes) y nunca le mostraba las fichas. Ante "nati
fue quien lo logró" llamaba a `buscar_profesor`, veía tres docentes llamadas Natalia y
ofrecía esas tres, mientras "Natalia Boo Fiad" estaba cargada con ficha.

**Buscar una persona mira siempre los dos padrones**, entre por donde entre:

| Se llama | Busca en | Cruza y agrega |
|---|---|---|
| `buscar_profesor(query)` | horarios | `personas_con_ficha` + `aviso` (la respuesta pasa de lista a dict) |
| `buscar_entidad('personas', query)` | fichas | `en_horarios` + `aviso_horarios` |

Las dos solo agregan la clave **cuando hay coincidencia real**, así que los turnos normales
—horarios por un lado, inventario por el otro— no cambian ni suman ruido. Y los dos avisos
son distintos según el caso: si `personas` no encontró nada pero los horarios sí, el aviso le
prohíbe explícitamente decir "no la tengo" y le ofrece dos salidas (resolver el horario con
ese nombre, o proponer crearle la ficha).

Va en el resultado de las tools y no (solo) en el system prompt porque para cuando el modelo
llamó **ya eligió**: lo único que lo corrige a tiempo es lo que la herramienta le conteste.

**`_coincide_fuerte(q_norm, nombre)`** es el filtro de los dos cruces, y es más estricto que
las búsquedas normales: substring, o similitud **palabra por palabra** ≥ `UMBRAL_SIMILITUD`
(0.68). No usa el 0.6 de `_buscar_profesor_scored`, que ofrece candidatos a propósito: con
0.6 el cruce de "nati" traía PETRATE MATIAS (0.60 contra "matias") y el de "calei" traía
PRIETO VALERIA. Tampoco alcanza con substring solo — los apodos del castellano no son
prefijos: "nati" **no** es substring de "natalia" (0.73 de similitud, sí pasa el umbral), y
ése era justo el caso a resolver.

**`/confirmar` crea el vínculo persona↔hito solo** (`_enlazar_protagonistas()`): al guardar
un hito cruza su `protagonistas` contra `personas` con la misma función y escribe
`persona_hitos` para cada match, sumándole al mensaje " Lo vinculé con la ficha de X.".
**Tiene que ser código y no una instrucción al modelo**: el botón de confirmar no pasa por
el LLM, así que en el momento en que el hito se escribe el agente no tiene ningún turno para
llamar a `vincular_entidad`, y el vínculo no lo creaba nadie. Solo vincula personas ya
cargadas; nunca crea una ficha de persona nueva.

### Los id no se le muestran al usuario

Los id son plumbing: enganchan filas entre tablas y le sirven al modelo para llamar a las
tools, pero al usuario no le dicen nada — ni la web de `/gestion` los muestra, solo los usa
en las URLs. Aun así el modelo los repetía en casi toda respuesta de lectura (medido: 6 de
9 respuestas — "Multímetro (ID 4)", "préstamo #2", una columna `ID` en la tabla de préstamos).

Se ataca por dos lados:
- **Regla en el system prompt** ("LOS ID NO SE MUESTRAN"), con ejemplos de mal/bien y la
  indicación de desambiguar por lo que distingue de verdad (ubicación, potencia, marca) en
  vez de por el id.
- **`_ocultar_ids()`, filtro de salida en `chat()`**, que corre **antes de persistir** la
  respuesta — así el historial repintado tampoco los trae. Saca paréntesis que son solo un
  id, ids inline, `#N`, y la columna `ID` de las tablas markdown (`_quitar_columna_id()`,
  que borra la misma posición en encabezado, separador y filas — con regex plana no alcanza).
  Después limpia los restos: paréntesis vacíos, comas al abrir paréntesis, guiones colgando.

Es filtro de código y no solo prompt por lo mismo de siempre; acá el costo de que el modelo
se olvide es bajo (ruido en pantalla), pero sale gratis hacerlo determinístico. Medición
después del cambio: **0 de 9**. Los mensajes que arma el servidor tampoco los incluyen
(`/confirmar` responde "✅ Guardado: **nombre**." sin id).

### Salida interpretada

Las tools de lectura retornan datos ya procesados, no filas SQL crudas: horarios agrupados
por día, aulas libres agrupadas por piso, búsquedas con solo campos relevantes (omitiendo
vacíos), pendientes de préstamos ya calculados. Reduce tokens de API y errores de interpretación.

### Calidad del match en `buscar_entidad`

La búsqueda es la misma de la web (`buscar_entidad_sin_request` → `_puntaje_busqueda`), que
ordena por puntaje pero **lo descarta al devolver**. Para el agente eso era un problema real:
buscar "taladro" (que no existe en el inventario) devolvía *Caladora*, *Sierra de calar
manual* y *Cinta de aisladora* — todos difusos de ~0.6 — y Claude los recibía con el mismo
peso que un match literal, así que ofrecía el primero como si fuera el pedido. Por eso
`_buscar_entidad_fmt` (en `agente.py`, capa de presentación, no toca la búsqueda compartida)
agrega por resultado:

- **`match`**: `exacto` (substring en el nombre) · `descripcion` (substring en la descripción,
  no en el nombre) · `aproximado` (solo similitud difusa).
- **`similitud`** (0–1) cuando es `aproximado`, recalculada con `_puntaje_busqueda`.
- **`descripcion`** cuando `match == 'descripcion'`: sin esto el nombre llega sin relación
  visible con lo buscado (buscar "cable" trae *Faniot arduino*, cuya descripción dice
  "Falta un cable usb a mini usb"). Se manda entera hasta `MAX_DESC_BUSQUEDA` (160) porque
  las descripciones del inventario son cortas (máx ~180 chars).

Y a nivel respuesta: `total` real, tope de `LIMITE_BUSQUEDA` (10) con campo `truncado`
(la difusa no acota: con query vacía devolvía la tabla entera), y un `aviso` cuando **todos**
los resultados son `aproximado` que le dice explícitamente que probablemente no exista y no
ofrezca el más parecido como correcto. La descripción de la tool documenta los tres valores
de `match`; sin eso el campo llega y el modelo lo ignora.

Slug inválido devuelve `{'error': ...}` con los válidos, no una lista vacía (que el agente
leía como "no hay nada cargado").

### Búsqueda en dos niveles: `buscar_entidad` → `listar_todos`

`_puntaje_busqueda` compara **letras, no significados**: buscar "tester" no encuentra el
*Multímetro*, y "taladro" no encuentra la *Agujereadora de banco*, que es exactamente eso.
Por eso "no encontré" **no** equivale a "no existe", y el agente no debe concluir lo segundo
desde lo primero. El orden es:

1. `buscar_entidad(slug, query)` — barata y precisa.
2. Si ningún resultado trae `match: "exacto"` → `listar_todos(slug)`, que devuelve **todos**
   los nombres + id. El modelo reconoce ahí el sinónimo, la marca o la jerga del taller.
3. Recién entonces afirmar que no está cargado — habiéndolo verificado, no deducido.

`_listar_todos_fmt` devuelve `{slug, total, items:[{id,nombre}], instruccion}` y, si hay filas
con el nombre vacío, las cuenta aparte en `sin_nombre` (esconderlas sin avisar haría falsa la
afirmación "estos son todos"). Tope `LIMITE_LISTADO_COMPLETO` (400): arriba de eso devuelve
`error` pidiendo afinar la búsqueda, en vez de reventar el contexto en silencio.

**Costo medido** (91 recursos): el listado completo son ~1.190 tokens. El piso que se
re-procesa en **cada** round-trip de tool es ~8.050 (esquemas de las 20 tools ~6.420 + lista
de personas ~1.625, sin contar system prompt ni historial), así que un intento extra de
búsqueda cuesta ~6,7x lo que cuesta mandar el inventario entero. Por eso se eligió esto sobre
un diccionario de sinónimos o un tier intermedio de reintentos — ver `dev-log/DECISIONS.md`
2026-08-08, que además documenta cuándo esta decisión se da vuelta (si el inventario supera
el tope).

**El guardrail vive en tres lugares que se refuerzan** — es de prompt, no de código, y con
DeepSeek (proveedor por defecto) es más frágil que con Claude:
- el `aviso` de `buscar_entidad` nombra la tool cuando la búsqueda falla;
- la `instruccion` del resultado dice "estos son TODOS; si ninguno es, decilo — no ofrezcas
  el más parecido como si fuera el correcto";
- la regla 3 del system prompt fija el orden de los tres pasos.

### Historia de la escuela (`consultar_historia`)

Cuarta área del agente: lore institucional (fundación, nombre de la escuela, edificio) y
guiños internos sobre gente de la casa. **Cuando se piden historias, no es el agente quien
responde: es Emilio Mitre, el fantasma que habita la escuela desde su construcción.** Recorre
todos los pasillos, ve y escucha todo. Por eso cuenta en primera persona con autoridad omnipotente.
Las historias son literales del archivo — nunca improvisadas.

**Estructura de archivos**:
- **`historia_indice.json`** — índice comprimido: id, título, claves, tipo, resumen, tono, estilo.
  Se cachea por mtime (pequeño, ~20KB). Recarga sola cuando cambia sin reiniciar.
- **`historias/`** — directorio con un archivo JSON por historia (ej: `guino_canamas.json`).
  Contiene: id, título, claves, tipo, resumen, tono, estilo, **texto completo**.
  Se cargan bajo demanda (lazy-loading), no se cachean.

Estructura por historia:
```json
{
  "id": "guino_canamas",
  "titulo": "Miriam Cañamas: el multímetro fallado",
  "claves": ["cañamas", "miriam", "multimetro"],
  "tipo": "guiño",
  "fecha": "2008",
  "resumen": "La anécdota de tercero que culpó al instrumento",
  "tono": "nervioso",
  "estilo": "primera persona, cómplice, como confesando",
  "texto": "Miriam Cañamas tiene fama de escuchar todo..."
}
```

**Campo `fecha`** (crítico): año o período aproximado. Determina el tono nostálgico de la historia.
Una historia de 2005 + tono reflexivo = profundamente nostálgica. Sin fecha, es solo una anécdota.

**Búsqueda** (`_historia_fmt`): sin tema devuelve índice completo. Con tema:
- Busca en `claves`, `tono`, `estilo`, `titulo`, `resumen` (substring + difuso con umbral 0.72)
- Devuelve tres modos:
  * **directo**: 1 coincidencia exacta → devuelve historia completa + `instruccion_tono` (instrucciones para Emilio)
  * **listar**: múltiples opciones → devuelve índice sin textos, usuario elige cuál historia quiere escuchar
  * **no_encontrado**: nada coincide → instrucción de no inventar

**Personalidad de Emilio**: en modo `directo`, la `instruccion_tono` le recordar a Claude que es
Emilio Mitre, el fantasma omnipotente, contando desde su perspectiva de siglos. Cada historia
especifica un `tono` (emociones: nervioso, reflexivo, misterioso, conmocionado, nostálgico) y
un `estilo` (narrativa: primera persona, íntimo, cómplice, como confesando, etc.). El modelo
respeta estas instrucciones y cuenta la historia con la voz de Emilio, no como un asistente
que relata.

La instrucción la arma **`_instruccion_tono(tono, estilo)`**, una sola fuente para las dos rutas
de `consultar_historia` (por `tema` y por `id`). Es una función y no texto inline porque estuvo
duplicada: la ruta por `id` — la que se usa cuando el usuario elige de un `listar`, o sea el
camino más común — tenía una versión de dos líneas sin la regla anti-acotaciones.

### La voz del personaje (`QUIEN_ES_EMILIO`, `EXCUSA_SIN_HISTORIA`)

Con solo pedirle primera persona, las historias salían correctas pero **anónimas**: se presentaba,
explicaba que era un fantasma, aclaraba que la escuela lleva su nombre y pedía permiso para
empezar. Leídas seguidas parecían el conserje contando una anécdota, no el dueño del edificio.
Dos constantes arreglan eso, y van **solo en el circuito de historias** (`_instruccion_tono` + la
sección HISTORIA DE LA CASA del system prompt), no en las respuestas operativas:

- **`QUIEN_ES_EMILIO`** — tres cosas juntas. *Con quién habla*: el otro ya sabe quién es, así que
  no se presenta ni se explica; entra directo, con la familiaridad del que es dueño de la casa y
  sabe que el otro está de visita. *Su orgullo*: sabe todo lo que pasa en la escuela y le encanta
  que se note, cuenta como el único que estuvo ahí y deja caer que nadie más lo vio. La soberbia
  es parte del personaje; maltratar al que pregunta, no — le halaga que le vengan a preguntar,
  porque confirma que es el que sabe. *Y que no es una persona*, sin decirlo nunca: con solo
  pedirle primera persona hablaba como un empleado con cuerpo ("yo estaba ahí parado"), que fue
  el segundo problema reportado. Tres señales lo delatan y el prompt las nombra — no tiene cuerpo
  ni lugar (no entró ni se acercó: **estaba**, porque está siempre y en todas partes a la vez),
  nada lo tapa (escuchó lo que se dijo en voz baja, con la puerta cerrada, y no aclara cómo), y
  el tiempo no le pesa (veinte años son "el otro día"; los que estaban ya no están y él sigue).

  **De acá sale, además, el fundamento de la regla anti-acotaciones**: no describe lo que hace
  con el cuerpo porque **no tiene cuerpo**. Las dos reglas dejaron de ser independientes, y en
  `COMO_CUENTA_EMILIO` está escrito así — es una consecuencia del personaje, no una prohibición
  de estilo caída del cielo.
- **`EXCUSA_SIN_HISTORIA`** — qué hace cuando no tiene la historia: no admite un agujero en su
  memoria de un siglo, zafa con una excusa obvia y absurda dicha con naturalidad ("justo esa
  semana estaba en el subsuelo peleándome con la caldera"). Se interpola en las **tres** `nota`
  de `no_encontrado` (índice vacío, sin coincidencias por tema, id inexistente). El chiste se
  apoya en el punto anterior: la excusa **se contradice con el personaje** —está en todos lados
  al mismo tiempo, así que "estaba ocupado en otra parte" no se lo cree nadie— y la dice igual,
  sin inmutarse. Ahí está la gracia, y por eso el prompt le pide que no se haga cargo del chiste.

**Dónde termina el personaje** — es el límite que sostiene todo lo demás, y está escrito en el
system prompt además de acá:

- La excusa **reemplaza el "no sé", nunca los hechos**. Es un chiste de personaje, no un permiso
  para inventar: la respuesta tiene que seguir dejando clarísimo que esa historia no existe. Sin
  esta línea, la excusa absurda es exactamente el borde por el que se cuela la fabricación de
  anécdotas que el resto del prompt trabaja para evitar.
- Y vale **solo para historias y lore**. Un horario, un stock, un préstamo o una persona que no
  están cargados se contestan derecho: "no hay datos de eso". Al que busca una herramienta o va
  corriendo a dar clase, un chiste le cuesta una vuelta al pañol al vacío. Ahí sigue valiendo el
  agente bifásico de siempre (DECISIONS 2026-08-08): fantasma orgulloso en las historias,
  herramienta neutra en lo operativo.

### Emilio cuenta, no actúa (`_quitar_acotaciones`)

Decirle al modelo que hable en primera persona como un fantasma le activa el registro de
roleplay, y empieza a **actuar** el personaje: `*se acomoda los anteojos*`, `—mirando el
patio—`, `EMILIO:` antes de hablar. Mismo esquema de defensa que los id — prompt **y** filtro
de salida:

- **`COMO_CUENTA_EMILIO`** (constante en `agente.py`): se interpola en el **system prompt** y en
  cada `instruccion_tono`. Va en el system prompt porque **los resultados de tools no se
  persisten en el historial**: en un turno de seguimiento ("¿y después qué pasó?") la
  `instruccion_tono` ya no está en contexto y lo único que el modelo tiene a la vista es su
  propia respuesta actuada del turno anterior, que imita.

  Está redactada como **instructivo de qué hacer**, no como lista de prohibiciones: "escribís
  únicamente las palabras que Emilio dice en voz alta", cómo transmitir el clima con lo dicho
  (si es un secreto, "esto no lo repitas"; si da para resignarse, "y bueno, así es acá") y un
  **test** que el modelo aplica solo — *¿esta oración se puede pronunciar?*. La primera versión
  era negativa ("no escribas acotaciones de gestos, no marcas de guion") y funcionó peor por dos
  razones: le dejaba al modelo deducir la forma correcta, y para nombrar lo prohibido había que
  escribir el ejemplo malo en el prompt, que es justo lo que después copiaba. Hoy **no hay ni
  una acotación de muestra** en el prompt.
- **`_quitar_acotaciones()`**: filtro de salida en `chat()`, junto a `_ocultar_ids()` y también
  **antes de persistir**, así el turno siguiente no arranca con el ejemplo malo en el historial.
  Barre cursivas de una sola marca (`*...*`, no `**bold**`), corchetes, tramos entre rayas
  (`—...—`) y la etiqueta `EMILIO:` / `**Emilio:**` al principio de línea.
- **`_quitar_oraciones_gesto()` / `_es_oracion_gesto()`**: las acotaciones **sin marcar**.
  Prohibirle las marcas no le quita la costumbre de actuar — encuentra la vuelta y escribe el
  mismo gesto como prosa suelta ("Baja la voz, se acerca un poco." / "Se encoge de hombros."),
  que fue exactamente lo que pasó al probar la primera versión. La señal que las delata es
  gramatical: Emilio habla en primera persona y las historias están en pasado, así que una
  oración corta, entera en tercera del presente y sin sujeto solo puede ser él describiéndose
  desde afuera. Se borra la oración **solo si todas sus cláusulas son gesto**: "Baja la voz, se
  acerca un poco." se va entera, pero "Sonríe y sigue la clase como si nada" se queda porque la
  segunda mitad dice algo. Los núcleos de gesto están **listados a mano** (`_GESTO_NUCLEO`) en
  vez de inferidos por conjugación: la lista se queda corta ante un gesto nuevo, pero no se come
  una oración real, que es el error caro.
- **`_parece_gesto()`** decide qué se borra, y es deliberadamente conservador: nunca toca un
  tramo con números (los datos técnicos y las fechas los tienen: `*Panel solar 100 W*` es
  contenido, y `—fundada en 1957—` es un paréntesis legítimo), y de ahí pide o una frase con
  señal de gesto (reflexivo inicial, gerundio, palabra de la lista) o una sola palabra que ya
  sea un gesto (`*suspira*`, `*riéndose*`). Se preferió que se escape una acotación rara antes
  que borrar contenido real. Los verbos que existen en imperativo quedaron **fuera** de la
  lista de una palabra: `*mirá*` es una cursiva válida.

También se sacó el vocabulario de teatro de la doc de historias: el `estilo` se le pasa
**literal** al modelo, así que `"diálogos"` o `"dramático"` en ese campo son un pedido de
guion. Ver `HISTORIAS_PROCEDIMIENTO.md`.

**Gatillo de personalidad**: Emilio solo cobra vida cuando se consultan historias. Para tareas
prácticas (horarios, inventario, préstamos), sigue siendo una herramienta eficiente sin personaje.
Así alguien que consulta un horario en medio de la jornada obtiene info rápida, sin interrupciones
de lore.

**Por qué textos literales**: dejarlo improvisar anécdotas dispara la conducta que el prompt desactiva
(fabricación de historias), y el modelo no sabe que el permiso termina en anécdotas. Por eso textos
vienen del JSON siempre, jamás generados. `no_encontrado` devuelve instrucción explícita de no inventar,
no lista vacía que invita a rellenar.

**Costo**: índice cachea siempre (~250 tokens por turno). Historias completas se pagan solo cuando se
leen (varían, típicamente 200–500 tokens por historia).

### Alta desde foto (datasheets, etiquetas, chapas de características)

Caso de uso central del asistente en el taller: sacan la foto de la etiqueta de un panel
solar, escriben "tenemos 5" y el recurso queda cargado sin tipear especificaciones.

**Recorrido de la foto**:
1. `gestion-agente.js` la lee con `FileReader`, la **achica en un canvas** a 1568 px de lado
   largo / JPEG calidad 0.85 y la deja en `imagenSeleccionada` como data URL. Sin ese paso
   una foto de celular (3–8 MB, ~11 MB en base64) no entra en el límite de la API de visión
   y tarda una eternidad por el wifi de la escuela. 1568 px es lo que el modelo llega a
   aprovechar y alcanza para leer la letra chica de un datasheet. Si el navegador no puede
   decodificar el archivo (HEIC de iPhone), se manda tal cual en vez de perder la foto.
2. `POST /chat` con `{mensaje, imagen}`. **La foto sola es un mensaje válido**: si no
   escribieron nada, el front igual envía y el backend pone "Te mando esta foto." como texto.
3. `chat()` **no le manda la foto al agente ni la lee**: la deja en
   `contexto_turno['foto_turno']` y le agrega al mensaje del usuario una nota diciendo que hay
   una foto disponible. El agente nunca ve un píxel.
4. **El agente decide qué hacer con ella**, y ahí se abren los dos caminos (ver abajo): leerla
   con `leer_foto` si necesita los datos, o guardarla con `adjuntar_foto` si va a una ficha que
   ya existe. Si no está claro, pregunta.
5. En el camino de alta, el modelo arma la ficha con `crear_entidad` → botón de confirmar, y la
   foto queda en `agente_fotos_pendientes` atada al **token de la ficha**. Al confirmar,
   `_adjuntar_foto_pendiente()` la pasa a la galería del registro nuevo con
   `gestion.agregar_foto()` — el mismo camino que usa la subida manual desde el detalle.

#### Los dos caminos de una foto

| El usuario quiere… | Tool | ¿Cuesta visión? |
|---|---|---|
| Guardarla en una ficha que ya existe ("guardá esta foto en el taladro") | `adjuntar_foto(slug, id)` | **No** |
| Cargar o actualizar el inventario con lo que dice la etiqueta | `leer_foto()` → `crear_entidad` / `editar_entidad` | Sí (~US$0,0004) |
| No se entiende | — | No: el prompt le pide **preguntar**, no leer por las dudas |

**Leer es una tool, no un paso automático.** La primera versión leía toda foto al entrar a
`chat()`, y eso pagaba una llamada de visión también cuando lo único que querían era adjuntar —
que es el caso más común y el que menos la necesita: para guardar una imagen no hace falta
saber qué dice. El costo de la vuelta extra del loop es despreciable al lado de eso, porque
DeepSeek cachea el prefijo (system prompt + tools): los cache hits salen US$0,003625/M contra
US$0,435/M de un miss.

Las dos tools sacan la imagen de `contexto_turno['foto_turno']`, nunca de un parámetro: el
modelo no ve la foto, así que pedirle el base64 sería pedirle que lo invente. Si en el turno no
vino ninguna, las dos devuelven un error que se lo explica en vez de fallar en silencio.

`adjuntar_foto` **corre directo, sin ficha de confirmación**: es aditivo (no pisa ni borra
nada) y el listón lo marca `editar_entidad`, que sobrescribe campos y tampoco la pide. Queda
auditada en `agente_log`. `leer_foto` no se audita: no toca la base — lo que gasta es la API de
visión, no el inventario.

> **Ojo**: no hay forma de borrar una foto de una galería desde la app (`subir_foto` agrega,
> nada saca). Por eso el prompt y la descripción de `adjuntar_foto` insisten en preguntar
> cuando el destino es ambiguo: una foto en el recurso equivocado se saca editando la base.

**Por qué la foto se guarda por token y no por turno**: la confirmación puede llegar mucho
después, incluso desde otra página (el historial se repinta y el botón sigue ahí). El token
de `_token_ficha()` es lo único que atraviesa esa distancia. Va en tabla propia y no dentro
del JSON de `fichas` porque esa columna se reescribe entera en cada turno: con hasta
`FICHAS_MAX` fotos en base64 adentro, cada mensaje del chat arrastraría varios MB de
escritura. Las filas sin confirmar se barren a los `CONVERSACION_DIAS` días, y `/reset` las
borra junto con la conversación.

La imagen **sigue sin persistirse en el historial** (`_sin_imagenes`) — lo que queda ahí es
la lectura en texto, que sí sirve en los turnos siguientes ("sí, tenemos 3"). Al repintar el
chat, `_texto_visible()` reemplaza ese bloque por "📷 (foto)": es una pista para el modelo,
no algo que el usuario haya tipeado.

**Reglas en el system prompt** (sección "FOTOS DE DATASHEETS…"): el agente trabaja **solo con
lo que dice la lectura**, nunca completando con lo que sabe de esa marca/modelo; la cantidad
no sale nunca de la foto sino de lo que dice el usuario (si no la dijo, se pregunta antes de
la ficha, junto con la ubicación); cinco unidades iguales son **un** recurso con `cantidad` 5,
no cinco altas; antes de la ficha se busca por marca/modelo y por nombre genérico, porque con
una foto lo más común es que el recurso ya exista y corresponda sumar stock con
`editar_entidad`; las especificaciones van en `descripcion`, no amontonadas en el `nombre`.
Si la lectura describe algo que no es una etiqueta (una máquina, un tablero, una planilla en
papel), se cuenta qué se ve y se pregunta qué hacer, no se da de alta sola.

#### El lector de imágenes (`_get_vision_config`, `_leer_imagen`)

Config **aparte de la del chat**: `AGENTE_VISION_API_KEY` (fallback `GEMINI_API_KEY`),
`AGENTE_VISION_MODEL` (default `gemini-2.5-flash-lite`), `AGENTE_VISION_API_BASE` (default
el endpoint OpenAI-compatible de Google). Sin API key, `_get_vision_config()` devuelve `None`
= no hay lector.

Es una llamada suelta, **sin tools**, con `PROMPT_LECTOR_IMAGEN` (solo lectura: transcribir lo
que se lee, no completar con conocimiento del producto, avisar si no se lee) y `max_tokens`
500. Todo lo que viene *después* de leer —cantidad, buscar duplicados, circuito de ficha—
sigue en el system prompt del agente, que es quien tiene las tools. **Solo se dispara desde la
tool `leer_foto`**: nunca automáticamente al llegar una foto.

**Por qué separado y no `AGENTE_PROVIDER=anthropic`**: el system prompt más `TOOLS_SCHEMA` son
~15.000 tokens que viajan en **cada** turno del agente; la llamada del lector son ~2.000. Con
el lector aparte una foto cuesta ~7× menos, el chat sigue en DeepSeek (más barato y mejor en
el tool-calling de 20 tools que un modelo chico con visión), y no hay que elegir entre
"proveedor bueno para chatear" y "proveedor que ve".

Ante cualquier falla —cuota, 429 del tier gratuito, red— `_leer_imagen()` devuelve `None` y
`leer_foto` le devuelve al modelo un error que le pide avisarle al usuario y **no inventar** lo
que decía la etiqueta. No corta el turno: es una tool que falló, no el chat.

**Las tres ramas de `chat()`**, por orden:
1. Hay lector → la foto queda en `contexto_turno['foto_turno']` y el mensaje del usuario lleva
   una nota diciendo que está disponible. **No se lee acá**: decide el modelo. Anda con
   cualquier `AGENTE_PROVIDER`.
2. No hay lector pero el chat ve imágenes (`_get_config()['vision']`: Anthropic siempre, el
   resto con `AGENTE_VISION=1`) → camino viejo, el bloque `image` viaja al agente y
   `_mensajes_openai(..., vision=True)` lo traduce a `image_url` si el proveedor es
   OpenAI-compatible. En esta rama `leer_foto` no hace falta: el modelo ya la ve.
3. Ninguno → `chat()` **corta antes de llamar al modelo** y responde `AVISO_SIN_VISION`. Es
   deliberado: mandarle el turno igual hacía que contestara sobre una imagen que nunca vio,
   inventando lo que "leyó" en la etiqueta — el peor resultado posible para un inventario. El
   turno igual se guarda en el historial.

### Auditoría (agente_log)

Tabla nueva en `gestion.db`:
```sql
agente_log (
  id, fecha, tool, entrada (JSON de parámetros),
  antes (JSON: snapshot de fila + relaciones M2M, NULL en alta, obligatorio en editar/eliminar),
  resultado (JSON), ok
)
```
Se inserta una fila **por cada tool de escritura ejecutada** (no por lecturas, para no llenar
la tabla de ruido). El snapshot "antes" permite restaurar a mano si el agente se equivocó en
una devolución de préstamo o un borrado.

### Otras tablas del agente en `gestion.db`

```sql
agente_conversaciones (sid PK, actualizado, historial JSON, entidad_actual, fichas JSON)
agente_fotos_pendientes (token PK, sid, b64, tipo, fecha)
```

`agente_conversaciones`: una fila por navegador. La conversación vive acá y no en la cookie
de Flask porque el historial la pasaba de los ~4 KB que aguanta un navegador y la cookie se
descartaba **sin avisar**, dejando al usuario deslogueado y sin conversación. En la cookie
queda solo `agente_sid`.

`agente_fotos_pendientes`: la foto de la que salió una ficha, esperando que se confirme el
alta (ver "Alta desde foto"). La clave es el token de contenido de `_token_ficha()`, no el
turno, porque la confirmación puede llegar desde otra página o mucho después.

Las dos se barren a los `CONVERSACION_DIAS` (30) días de inactividad, en la misma escritura
que las usa — no en `init_db()`, porque el server puede estar meses sin reiniciar.

### Guardias de seguridad / guardrails de prompt

- **Confirmación en dos turnos para eliminar**: el *system prompt* instruye a Claude a nunca
  ejecutar `eliminar_entidad` / `eliminar_prestamo` en el mismo turno en que se pide el borrado.
  Primero debe responder qué va a borrar y esperar una confirmación explícita del usuario en el
  turno siguiente. Es una guardrail de prompt (coherente con "/gestion" siendo "traba de
  desarrollo, no seguridad completa"), reforzada por la auditoría.
- **Confirmación de alta con ficha**: a diferencia del borrado, el alta **no** depende del
  prompt — `crear_entidad` no escribe hasta que el hash de la ficha coincida con uno mostrado
  en un turno anterior (ver "Alta con ficha de confirmación"). Vale también para las altas
  desde foto: la foto llena la ficha, no la base.
- **Resolución de ambigüedad en recursos**: si `crear_prestamo` busca un nombre de recurso
  que matchea más de una fila, la tool devuelve `ok:false` con `opciones` (id + nombre de cada
  candidato) en vez de adivinar. El system prompt instruye a mostrarle esas opciones al usuario
  y preguntar, nunca elegir por su cuenta ni reintentar adivinando.
- **Resolución de persona por lista conocida**: `chat_with_tools()` arma en cada turno la lista
  de "personas conocidas" (`_personas_conocidas()`: profesores de `clases` + personal no docente,
  ~340 nombres) y la inyecta completa en el system prompt. Regla: si el nombre que dio el usuario
  no es un match exacto/obvio contra la lista (apodo, nombre incompleto, typo — ej. "Dami"),
  el agente debe preguntar antes de crear el préstamo en vez de guardar el nombre tal cual; si no
  se parece a nadie de la lista, se asume persona externa (alumno/visita) y se usa tal cual sin
  preguntar. Se evaluó dar la lista completa en el prompt vs. una tool de "comparar nombre"
  dedicada — se descartó la tool porque ya existe `buscar_profesor` con la misma lógica de
  scoring y agregar una segunda ruta hubiera sido redundante; la lista en el prompt evita además
  que el agente decida "no hace falta buscar" y se salte la verificación. El costo en tokens es
  chico (~1500 tokens por turno) y no justificó una tabla de "personas" nueva en `gestion.db`
  (los préstamos son a veces gente que no está en ninguna lista — alumnos, visitas — así que
  seguir aceptando texto libre es correcto).
- **Devoluciones parciales no fallan en silencio**: `finalizar_prestamo`/`reabrir_prestamo` con
  `items` verifican que cada `recurso_id` pertenezca al préstamo antes de tocarlo; si no
  pertenece, la tool devuelve `ok:false` con el detalle en vez de reportar éxito sin haber
  cambiado nada (bug real: antes un `recurso_id` inválido se ignoraba silenciosamente y la tool
  igual respondía `ok:true`). El system prompt le pide al agente llamar primero a
  `detalle_prestamo(id)` para obtener los `recurso_id` reales de ese préstamo antes de devolver
  ítems puntuales, en vez de adivinarlos.

### Configuración

- **Env var** `AGENTE_PROVIDER` — `deepseek` (default) | `anthropic` | `groq` | `openai` |
  `ollama`. Define también qué loop de tool-calling corre: Anthropic tiene el suyo, el resto
  comparte `_loop_openai`.
- **Env var** de API key — `AGENTE_API_KEY`, o la del proveedor (`DEEPSEEK_API_KEY`,
  `ANTHROPIC_API_KEY`, `GROQ_API_KEY`, `OPENAI_API_KEY`). Sin ella el chat devuelve un error
  claro en vez de fallar en silencio. Ollama no la usa.
- **Env var** `AGENTE_MODEL` — modelo a usar. Defaults por proveedor: `deepseek-v4-pro`,
  `claude-haiku-4-5-20251001`, `mixtral-8x7b-32768`, `gpt-3.5-turbo`, `mistral`.
- **Env var** `AGENTE_VISION` — `1` para declarar que el modelo del **chat** lee imágenes.
  Anthropic ya viene en `1`; esto es para gpt-4o u ollama+llava, donde depende del modelo.
  Solo se consulta si **no** hay lector configurado (rama 2 de `chat()`).
- **Env vars del lector de fotos**, independientes de todo lo anterior:
  `AGENTE_VISION_API_KEY` (fallback `GEMINI_API_KEY`) — sin ella no hay lectura de etiquetas;
  `AGENTE_VISION_MODEL` (default `gemini-2.5-flash-lite`);
  `AGENTE_VISION_API_BASE` (default el endpoint OpenAI-compatible de Google). Con la key
  puesta, el alta desde foto anda con **cualquier** `AGENTE_PROVIDER`, incluido el default.
- **Env var** `AGENTE_API_BASE` — para APIs custom (Ollama, self-hosted).
- **Costo**: cada mensaje del chat arrastra el system prompt + `TOOLS_SCHEMA`, ~15.000 tokens
  de entrada, tenga foto o no — eso domina la factura, no las respuestas. Por eso el lector de
  fotos va aparte (~2.000 tokens por foto) en vez de mandarle la imagen al agente. Las
  lecturas (búsquedas, horarios) agregan poco (~100–500 tokens); las escrituras
  (create/edit/préstamos) más, porque la salida de la tool vuelve a entrar al modelo. El
  lector en su default (Gemini Flash-Lite) entra en el tier gratuito de 1.000 requests/día.

### Qué entidades alcanza el agente (`SLUGS_ENTIDAD`)

**`agente.SLUGS_ENTIDAD = list(gestion.ENTIDADES)`** — el enum de `slug` de los esquemas de
tools se **deriva**, no se escribe. Antes estaba hardcodeado como
`['recursos', 'conjuntos', 'actividades', 'proyectos']` repetido en **10 lugares**
(`buscar_entidad`, `listar_todos`, `detalle_entidad`, `crear_entidad`, `editar_entidad`,
`eliminar_entidad`, `vincular_entidad`/`desvincular_entidad` con sus dos slugs cada una), y
cuando se creó `hitos` nadie los actualizó: la entidad quedó invisible para el chat sin que
nada fallara ni avisara. Agregar una entidad ahora es un cambio en `gestion.ENTIDADES` y nada
más.

Lo que hubo que destrabar además, porque el circuito de alta asumía una columna `nombre`:
- **`_crear_entidad`** valida `gestion._campo_nombre(cfg)`, no `'nombre'` (en `hitos` es `titulo`).
- **`_nombre_de(slug, campos)`** resuelve el nombre visible de una ficha. Hace falta porque
  `campos` es el dict que armó el modelo, no una fila de la DB: ahí **no** llega el alias de
  `_select()`. Sin esto el botón de confirmar y el "✅ Guardado" salían en blanco para `hitos`.
- **`CAMPOS_REDACTADOS`** incluye `'titulo'` además de `'nombre'`.
- **Los esquemas de `crear_entidad` / `editar_entidad` exponen `titulo`** (más `nivel`,
  `etiquetas` y `protagonistas`, y `fecha` vale para proyectos **e** hitos). Derivar el enum
  de `slug` hizo `hitos` elegible, pero los *campos* seguían siendo los de recursos: el
  modelo solo podía mandar `nombre`, `_normalizar_borrador` lo descartaba por no existir en
  el slug, y `_crear_entidad` cortaba con `El campo "titulo" es obligatorio` en **todas** las
  altas de hito. El agente no podía crear ni un solo hito, y el error se leía como un bug
  interno de la tool. `required` es `['slug']` a secas: si hace falta `nombre` o `titulo` lo
  decide `_crear_entidad` contra `gestion._campo_nombre`, que es la única fuente.
- **`vincular_entidad`** avisa en su descripción que con `proyectos` el origen es **siempre la
  persona** (`personas → proyectos`), porque la relación está declarada de ese lado y del otro
  falla. Con `hitos` ya no: desde 2026-08-09 `hitos` declara `rel_personas` (espejo de
  `personas.rel_hitos`, misma tabla `persona_hitos`), así que la relación anda en las dos
  direcciones y "sumá a Pablo al hito" tomado literal también funciona.

Las lecturas ya funcionaban solas gracias al alias de `_select()`: `_buscar_entidad_fmt`,
`_listar_todos_fmt` y `snapshot_entidad` devuelven `nombre` también para `hitos`.

`hitos` tiene además una tool de lectura propia, **`buscar_hitos(etiqueta, desde_fecha,
hasta_fecha)`**, que ordena por nivel y fecha — el CRUD genérico cubre la escritura, ésa cubre
la consulta de la línea del tiempo.

El system prompt describe **seis áreas** (horarios, inventario, préstamos, historia, línea del
tiempo, personas). La sección de PERSONAS le marca dos cosas que el código no puede forzar:
que la semblanza institucional **no** se mezcla con las anécdotas literales de
`consultar_historia`, y que antes de crear una persona hay que buscarla, porque una segunda
ficha del mismo docente le parte la historia en dos.

### Integración con módulo de /gestion

- Reusan `gestion.ENTIDADES` (config declarativa de recursos/conjuntos/actividades/proyectos).
- Reusan helpers de `gestion.py` ya refactorizados:
  `buscar_entidad_sin_request`, `guardar_entidad_sin_request`, `snapshot_entidad`,
  `agregar_relacion_m2m`, `quitar_relacion_m2m`, `_puntaje_busqueda`, `_carrito_filas`,
  `_recalcular_estado`, etc. (todas sin dependencia de Flask `request`/`session`).
- Reusan queries de `database.py`: `aulas_libres()` nueva (calcula libres vs ocupadas en
  `clases` a tiempo real, agrupadas por piso de `FLOOR_MAPPING`).
- El agente **no tiene acceso a escribir en `escuela.db`** (horarios) — solo lectura;
  actualizar desde Sheets sigue siendo un botón aparte del SPA.
