# Sistema de Gestión de Conocimiento (`/gestion`)

Módulo independiente del sistema de horarios: la "memoria técnica viva" de la escuela.
Registra recursos, conjuntos, actividades y proyectos, y los conecta entre sí (red de
conocimiento, no carpetas aisladas). Los archivos reales (fotos, planos, guías) viven
en Google Drive; acá solo se guardan links (`drive_url`).

## Arquitectura

- **`gestion.py`** — todo el módulo: blueprint Flask (`bp`, prefix `/gestion`), schema,
  seed y rutas. Server-rendered con Jinja. El único JS propio es `static/gestion.js`
  (búsqueda en vivo del listado — ver abajo); el resto es HTML puro con forms + redirects.
- **`gestion.db`** — SQLite propia, separada de `escuela.db`. **No** se regenera desde
  Sheets y `/api/actualizar` no la toca. Es la única DB con datos propios de la app
  (en hosting efímero tipo Render se pierde en cada restart; en PythonAnywhere persiste).
- **`templates/gestion/`** — `base.html` (layout + nav), `home.html`, `lista.html`,
  `form.html`, `detalle.html`. Los tres últimos son **genéricos**: se renderizan a partir
  de la config declarativa de cada entidad. `prestamos_lista.html`, `prestamos_form.html`,
  `prestamos_detalle.html` son específicos (préstamos no entra en `ENTIDADES`: tiene
  ítems con cantidad y un ciclo prestado→devuelto que el trío genérico no modela).
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
| `/gestion/prestamos/nuevo` | GET/POST | Form con hasta `PRESTAMO_FILAS_FORM` (8) filas de ítems (`recurso_N` + `cantidad_N`). `?recurso=<id>` (GET) precarga la fila 1 — lo usa el botón "REGISTRAR RETIRO" de la ficha del recurso |
| `/gestion/prestamos/<id>` | GET | Detalle: persona, destino, notas, fechas, e ítems con prestado/devuelto/pendiente y controles de devolución por ítem |
| `/gestion/prestamos/<id>/devolver` | POST | **Devolver TODO**: marca cada ítem entero (`cantidad_devuelta = cantidad`) y setea `fecha_devolucion`. Atajo — **nunca borra la fila** |
| `/gestion/prestamos/<id>/devolver_item` | POST | Devuelve parte (o el resto) de un ítem (`recurso_id` + `cantidad` opcional; vacía = todo lo pendiente). Al cubrirse todo lo pendiente, el préstamo se cierra solo |
| `/gestion/prestamos/<id>/reabrir` | POST | Deshace la devolución completa: resetea todos los ítems a 0 y limpia `fecha_devolucion` |
| `/gestion/prestamos/<id>/reabrir_item` | POST | Deshace la devolución de un ítem puntual (vuelve a 0); si eso deja algo pendiente, reabre el préstamo |
| `/gestion/prestamos/<id>/eliminar` | POST | Borra el registro entero — solo para cargas mal hechas, no es el flujo normal |

**Resolución de recursos en el form**: el `<input>` de cada fila usa un `<datalist>` con
todos los recursos como `"Nombre [#id]"` — el sufijo `[#id]` desambigua nombres
duplicados (el inventario real tiene "Formon" x2, "Medidor de energia solar" x2).
`_parsear_items_prestamo()` primero busca el sufijo `[#N]`; si no está, matchea por
nombre normalizado y solo acepta si hay un único candidato (si no, error pidiendo elegir
de la lista). Filas repetidas para el mismo recurso suman cantidades.

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
`gestion.prestamos_lista` / `gestion.prestamo_nuevo`, no `gestion.lista` / `gestion.nuevo`).

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
