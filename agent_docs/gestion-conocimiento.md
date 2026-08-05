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
| `recursos` | id, nombre, tipo, descripcion, ubicacion, estado, drive_url, cantidad, utilidad, fecha_revision |
| `conjuntos` | id, nombre, descripcion, uso_tipico, drive_url |
| `actividades` | id, nombre, objetivo, descripcion, duracion, curso, drive_url |
| `proyectos` | id, nombre, descripcion, fecha, participantes, estado, drive_url |

M2M (con `UNIQUE` por par): `conjunto_recursos`, `actividad_recursos`,
`actividad_conjuntos`, `proyecto_recursos`.

| `prestamos` | id, persona, destino, notas, fecha_salida, fecha_devolucion |
| `prestamo_items` | prestamo_id, recurso_id, cantidad, cantidad_devuelta (M2M con cantidad, `UNIQUE(prestamo_id, recurso_id)`) |

Estados: recursos = Disponible / En uso / En reparación / De baja / Sin revisar;
proyectos = Activo / Pausado / Terminado.
Utilidad (recursos): "" / Básico / Secundario / Alto valor.
`cantidad` y `fecha_revision` son TEXT (fecha en formato libre del inventario, ej "24/4").

**Inventario físico**: `importar_inventario.py` (root) importa el sheet "Inventario renovable
2026" a `recursos` vía CSV export público (mismo patrón que `database.py`, sin API key).
Es carga puntual re-ejecutable (upsert por nombre normalizado, no duplica); `gestion.db`
sigue siendo la fuente de verdad — no hay write-back al sheet (ver DECISIONS 2026-07-19).
Mapeo de estados del sheet: Funcional→Disponible, Reparar→En reparación, nc→Sin revisar.

## Config declarativa (`ENTIDADES` en gestion.py)

Cada entidad define: `tabla`, `singular`/`plural`, `descripcion` (card del home),
`campos` (form: nombre, label, tipo `text|textarea|select|url|date|number`, opciones, ayuda),
`columnas` (listado) y `relaciones` (M2M editables desde su form, campos con prefijo
`rel_` para no colisionar con columnas). Para agregar un campo: sumarlo al `SCHEMA`,
a `campos` y a la lista de `_migrar()` — `init_db()` hace el `ALTER TABLE` aditivo
automáticamente en DBs existentes (así entraron cantidad/utilidad/fecha_revision).

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

`slug` ∈ {recursos, conjuntos, actividades, proyectos}; otro valor → 404.

## Búsqueda tolerante (`?q=` en `lista()`)

No es el `LIKE` literal de SQL: `lista()` trae todas las filas y las filtra/ordena en
Python con `_puntaje_busqueda()`. Perdona **acentos y mayúsculas** (normaliza con `_norm`)
y **typos** (similitud difusa vía `difflib.SequenceMatcher`, sin dependencias). Reglas:
substring normalizado siempre puntúa por encima de los difusos; la similitud difusa solo
entra para queries de 3+ caracteres, con umbral `UMBRAL_SIMILITUD` (0.6). Compara la query
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

## Seed

`init_db()` crea las tablas y, si `recursos` está vacía, carga el ejemplo del documento
de diseño: 5 recursos, conjunto "Banco de ensayo solar" (panel + estructura +
inclinómetro), actividad "Medición de panel solar según inclinación" (usa el conjunto +
multímetro + pinza) y proyecto "Construcción del banco de ensayo solar".

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
conversacional via Claude (Anthropic API). El usuario puede hablar con la app en lenguaje
natural en vez de hacer click en formularios: consultar horarios, crear recursos, fotografiar
etiquetas y cargarlas, gestionar préstamos. Todo con auditoría de escrituras en `agente_log`.

**Acceso**: botón "🤖 ASISTENTE" en el header, visible solo tras iniciar sesión en
`/gestion` (reusan `session['gestion_ok']`). Abre un widget flotante de chat.

### Arquitectura

- **`agente.py`** — blueprint completo: gate de sesión, esquemas de tools JSON, ejecutores,
  loop de tool-calling contra Anthropic con manejo de tool use, endpoints Flask.
- **`POST /gestion/agente/chat`** — acepta `{mensaje, imagen?}` (imagen en base64 o data URL);
  retorna `{respuesta}`. El backend llama a Claude con el mensaje + tools disponibles, ejecuta
  lo que Claude pida (tools de lectura y escritura), repite hasta respuesta final, audita
  escrituras en `agente_log`.
- **`POST /gestion/agente/reset`** — limpia `session['agente_historial']` y
  `session['agente_entidad_actual']`; usado por el botón ↺ del widget para arrancar una
  conversación nueva sin arrastrar contexto viejo.
- **`GET /gestion/agente/log`** — tabla de auditoría (últimas 50 escrituras), con snapshot
  "antes" visible para poder restaurar manualmente si el agente cometió un error.
- **Widget** (`templates/gestion/_agente_widget.html` + `static/gestion-agente.js`) —
  panel flotante de chat con historial de mensajes, input de texto, opción de adjuntar imagen,
  botón ↺ para reiniciar la conversación, link a la auditoría. Incluido desde `base.html`.
  Progressive enhancement: con JS es fluido, sin JS no aparece pero el servidor sigue
  funcionando. Las respuestas del asistente se renderizan como markdown liviano
  (`renderMarkdown()` en `gestion-agente.js`: negrita, listas, tablas) — Claude devuelve
  texto en Markdown y sin esto se veía como un bloque de texto con `**`/`|` crudos.

### Tools

**Lectura** (no se auditan, siempre disponibles):
- `buscar_profesor(query)` — resolución difusa de nombre
- `horario_profesor(nombre)` / `horario_curso(curso, division)` / `horario_aula(aula)`
  — horarios agrupados por día
- `aulas_libres()` — aulas desocupadas ahora, agrupadas por piso
- `buscar_entidad(slug, query)` — búsqueda de recursos/conjuntos/actividades/proyectos
- `detalle_entidad(slug, id)` — detalle completo + relaciones
- `listar_prestamos(persona?)` / `detalle_prestamo(id)` — estados de préstamos

**Escritura** (se auditan, requieren `session['gestion_ok']`, guardan snapshot "antes"):
- `crear_entidad(slug, campos)` — create (valida nombre no vacío)
- `editar_entidad(slug, id, campos)` — update
- `vincular_entidad` / `desvincular_entidad` — gestionar M2M
- `crear_prestamo(persona, destino?, notas?, items)` — crear préstamo (cantidad topeada
  a stock, recurso por nombre o id con resolución ambigua)
- `finalizar_prestamo(id, items?)` — devolución total o parcial (calcula estado automáticamente)
- `reabrir_prestamo(id, items?)` — deshace una devolución
- `eliminar_entidad` / `eliminar_prestamo` — **requieren confirmación en turno separado** (el
  system prompt instruye a Claude a no ejecutar en el mismo turno en que se solicita, sino
  responder primero qué va a borrar y esperar confirmación)

### Salida interpretada

Las tools de lectura retornan datos ya procesados, no filas SQL crudas: horarios agrupados
por día, aulas libres agrupadas por piso, búsquedas con solo campos relevantes (omitiendo
vacíos), pendientes de préstamos ya calculados. Reduce tokens de API y errores de interpretación.

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

### Guardias de seguridad / guardrails de prompt

- **Confirmación en dos turnos para eliminar**: el *system prompt* instruye a Claude a nunca
  ejecutar `eliminar_entidad` / `eliminar_prestamo` en el mismo turno en que se pide el borrado.
  Primero debe responder qué va a borrar y esperar una confirmación explícita del usuario en el
  turno siguiente. Es una guardrail de prompt (coherente con "/gestion" siendo "traba de
  desarrollo, no seguridad completa"), reforzada por la auditoría.
- **Confirmación para crear desde foto**: igual criterio: si el usuario manda una foto, el
  agente propone los campos extraídos en texto y pide confirmación antes de llamar a
  `crear_entidad`.
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

- **Env var** `ANTHROPIC_API_KEY` — necesaria para llamar a la API de Anthropic. Sin ella,
  el chat devuelve un error claro ("ANTHROPIC_API_KEY no está configurada").
- **Env var** `AGENTE_MODEL` — modelo a usar (default `claude-haiku-4-5-20251001`, que
  soporta visión para fotografiar etiquetas y es costo bajo). Configurable igual que
  `GESTION_CLAVE`.
- **Costo**: cada mensaje del chat consume tokens de la API de Anthropic (aparte de Render
  gratuito). Las lecturas (búsquedas, horarios) suelen ser baratas (~100–500 tokens). Las
  escrituras (create/edit/préstamos) más caras porque la salida de la tool puede ser larga
  y Claude la procesa de vuelta.

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
