# Gestión de recursos (`/gestion`)

Una de las cuatro áreas de la app (las otras: el SPA de horarios, `/historia` y `/agente`).
Es el **inventario técnico** de la escuela: recursos (instrumentos, equipos, materiales,
estructuras), con sus fotos y su desglose por ubicación. **`gestion.db` es la fuente de
verdad**: lo que no está acá, no está. Las fotos viven en la propia base (columna `fotos`,
ver abajo).

> Hasta el 2026-08-10 el modelo era otro: los archivos reales vivían en Google Drive y cada
> entidad guardaba un link en `drive_url`. La escuela dejó de usar Drive y la columna se
> eliminó. Si ves `drive_url` en un respaldo viejo de `backups/`, es de antes de ese corte.

**Qué NO está acá**: la línea del tiempo institucional (`hitos`) y las fichas de personas se
separaron a `/historia` + `historia.db` el 2026-08-10 — ver `agent_docs/historia-institucional.md`
y `dev-log/DECISIONS.md`. Los dos módulos son hermanos y **no se importan entre sí**: comparten
el motor genérico `crud.py`, que no importa a ninguno de los dos — ver `agent_docs/crud-motor.md`.

> Hasta el 2026-08-21 el módulo también tenía `conjuntos`, `actividades` y un bloque entero
> de préstamos/retiro interno con carrito en sesión. Se sacaron por decisión de producto
> (no se iban a seguir usando), no por deuda técnica — ver `dev-log/DECISIONS.md` 2026-08-21
> si alguna vez se retoman. Lo que sigue describe el módulo **después** de ese corte.

## Arquitectura

- **`gestion.py`** — el área: blueprint Flask (`bp`, prefix `/gestion`), `ENTIDADES` (hoy solo
  `recursos`), `SCHEMA`, sus hooks (`migrar`, `seed`, `secciones_detalle`, `valores_iniciales`)
  y **el desglose de recursos por ubicación**, que es lo único que no pasa por el motor. Las
  rutas CRUD las monta `crud.registrar_rutas(bp, ...)` y el gate `accesos.registrar_acceso(bp,
  ...)` — ver `agent_docs/crud-motor.md`. Server-rendered con Jinja. El JS propio es
  `static/gestion.js`: una sola mejora progressive-enhancement, la búsqueda en vivo del listado.
- **`gestion.db`** — SQLite propia, separada de `escuela.db`. **No** se regenera desde
  Sheets y `/api/actualizar` no la toca. Junto con `historia.db` son las DBs con datos
  propios de la app. Alberga además las tablas del asistente (`agente_log`,
  `agente_conversaciones`, `agente_fotos_pendientes`), que son auditoría/sesión y no datos
  de dominio.
- **`templates/gestion/`** — `base.html` (layout + nav), `home.html`, `lista.html`,
  `form.html`, `detalle.html`, `alias_lista.html`. `lista.html`/`form.html`/`detalle.html`
  son **genéricos**: se renderizan a partir de la config declarativa de la entidad; `detalle.html`
  sólo sobreescribe la sección "Por ubicación" (el desglose, que no es una relación M2M).
- **`static/gestion.css`** — hoja standalone (paleta blueprint copiada, no importa
  `style.css` para que los dos sistemas no se pisen). Sin modo oscuro. La comparten
  `/historia`, `/agente` y `/accesos`: la identidad visual sí es común, la lógica de dominio no.
- **`static/gestion.js`** — único JS del módulo: búsqueda en vivo del listado (vanilla, sin
  build step). Cargado en `base.html` con `defer`; no hace nada fuera de las páginas donde
  encuentra sus hooks (guarda por existencia de elementos).
- **`static/mobile-nav.js`** — el ☰ y su panel lateral, compartido con `/historia`,
  `/agente` y `/accesos` (ver "Celular" abajo). No es lógica de dominio: solo mueve nodos
  del shell.
- `base.html` incluye el widget flotante del asistente (`agente/_agente_widget.html`) y
  el bloque `.g-areas` con los links a las otras áreas, que van al ☰. El header queda
  para lo de esta página: el toggle del widget, el link a ALIAS (solo admin) y la vuelta al SPA.
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
  mueven** (no se clonan) por dos razones: los listeners ya enganchados por
  `gestion-agente.js` (botón del asistente) siguen funcionando en el nodo movido, y no se
  duplican IDs como `#agente-toggle-btn`. Cada bloque deja un comentario-marcador en su
  lugar original, así al agrandar la ventana vuelve exactamente ahí (se escucha
  `matchMedia`, no `resize`). El panel se cierra con ✕, Esc, tocando el fondo o cualquier
  link de adentro. Sin JS no hay panel: nav y acciones quedan en el header envolviendo en
  varias filas, como siempre, y el menú de áreas no se ve.
- **Listados como tarjetas (≤700px)** — una tabla de varias columnas en 360px obliga a
  scrollear de costado y deja Ver / Editar fuera de pantalla. Abajo de 700px cada `<tr>`
  de `.g-table` pasa a `display: block` y se ve como una tarjeta: el nombre de título, el
  resto como pares etiqueta/valor, los botones al pie. **La etiqueta sale del `data-label`
  de cada `<td>`**, que repite el encabezado de la columna — si agregás una columna a un
  listado, ponele `data-label` o en celular sale sin etiqueta. Los `<td>` llevan `{%- -%}`
  para quedar *realmente* vacíos cuando no hay dato y que `td:empty` los esconda (si no, se
  vería la etiqueta sola). Entre 700 y 900px sigue siendo tabla con scroll horizontal.
- **Táctil** — objetivos de 44px en botones y campos, y **16px exactos** de `font-size`
  en los inputs: con menos, iOS hace zoom al enfocar y descuadra el layout.
- El chat tiene además su propia capa mobile, ver `agent_docs/agente-asistente.md`.

## Modelo de datos (gestion.db)

| Tabla | Campos |
|-------|--------|
| `recursos` | id, nombre, tipo, descripcion, ubicacion, estado, cantidad, valor, fecha_revision, **fotos**, **alias** |
| `recurso_ubicaciones` | recurso_id, ubicacion, cantidad (`UNIQUE(recurso_id, ubicacion)`) — desglose OPCIONAL de dónde están las unidades de un recurso, ver abajo |

**Desglose por lugar** (`recurso_ubicaciones`): el campo `ubicacion` de `recursos` sigue siendo
el lugar único/principal de siempre — la mayoría de los recursos no toca esta tabla. Sólo entra
en juego cuando las unidades de un mismo recurso están repartidas en más de un sitio (10
destornilladores, 5 en el taller y 5 en el laboratorio). **Nunca es obligatorio ni tiene que
sumar el total de `recursos.cantidad`**: no hay concepto de "sin ubicar" que validar, cada fila
es independiente — a propósito, para no bloquear un movimiento por no tener el desglose previo
cargado. Helpers en `gestion.py`: `ubicaciones_recurso()` (el desglose de un recurso),
`mover_ubicacion()` (mueve cantidad de un lugar a otro, vaciando y avisando si el origen no
tenía tanto registrado), `_stock()` (cantidad total del recurso, la usa además `agente/tools/
ubicaciones.py` para chequear que el id exista). Se edita desde la ficha web (rutas
`/gestion/recursos/<id>/ubicaciones[/eliminar]`, sección "Por ubicación" del detalle, sólo
visible si el recurso tiene más de una unidad o ya tiene desglose) y desde el chat (tool
`mover_ubicacion`, ver `agent_docs/agente-asistente.md`).

**Galería de fotos** (`fotos`): array JSON con objetos `{b64, tipo, fecha}`.
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

Estados: recursos = Disponible / Retirado / En uso / En reparación / De baja / Sin revisar.
Valor (recursos): "" / Básico / Secundario / Alto valor — es la *importancia* del recurso
dentro del inventario, no su precio (se llamaba `utilidad`, renombrada 2026-08-08).
`cantidad` y `fecha_revision` son TEXT. **`fecha_revision` se precarga con la fecha de hoy
en todo alta de recurso**, por los dos caminos: el form web (`valores_iniciales()` en el
GET de `/recursos/nuevo`) y el chat (`_normalizar_borrador()` en `agente/tools/fichas.py`, antes de
calcular el token, para que la fecha aparezca en la ficha y el usuario la vea y la pueda
cambiar). Dar de alta un recurso es un control de inventario; antes quedaba vacía y casi
ningún recurso terminaba con fecha. "Hoy" sale de `config.ahora()` (hora de Buenos Aires; el
server de producción corre en UTC — ver "El reloj" en `agent_docs/crud-motor.md`). Formato
`gestion.FORMATO_FECHA_REVISION` = `%d/%m/%Y` (ej `08/08/2026`) — **conviven** con las fechas
cortas sin año del inventario importado del sheet ("24/4", "8/5"), que no se reformatean.
Editar un recurso **no** toca la fecha: `_editar_entidad` (agente) parte de la fila actual y
no pasa por `_normalizar_borrador`.

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
`columnas` (listado) y `relaciones` (M2M editables desde su form — hoy vacía: `recursos` no
tiene ninguna relación propia). Los campos de relación usan el prefijo `rel_` para no
colisionar con nombres de columnas.

**`campo_nombre`** (opcional, default `'nombre'`): cómo se llama en la tabla la columna que
hace de nombre visible. `recursos` no la declara distinta — el mecanismo existe
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

`LIMPIEZA_M2M` mapea qué tablas de relación limpiar al eliminar cada tipo de entidad — hoy
sólo `recursos` → `recurso_ubicaciones` (no es M2M de verdad, es el desglose por lugar, pero
el mecanismo de limpieza es idéntico).

## Rutas (todas server-rendered)

| Ruta | Método | Descripción |
|------|--------|-------------|
| `/gestion/login` | GET/POST | Form de acceso; con clave OK setea sesión y redirige a `?next=` (solo si empieza con `/gestion`, anti open-redirect) |
| `/gestion/salir` | GET | Borra la sesión y vuelve al login |
| `/gestion/` | GET | Home: cards con contadores |
| `/gestion/<slug>` | GET | Listado (`?q=` búsqueda tolerante en nombre + descripcion — ver abajo) |
| `/gestion/<slug>/nuevo` | GET/POST | Alta (valida nombre no vacío server-side) |
| `/gestion/<slug>/<id>` | GET | Detalle: campos + secciones (hoy sólo "Por ubicación" en recursos) |
| `/gestion/<slug>/<id>/editar` | GET/POST | Edición |
| `/gestion/<slug>/<id>/eliminar` | POST | Borra fila + sus filas de `LIMPIEZA_M2M` (confirm en el browser) |
| `/gestion/<slug>/<id>/foto` | POST | Sube una imagen a la galería (multipart → base64). Devuelve JSON |
| `/gestion/<slug>/<id>/foto/<indice>/eliminar` | POST | Borra la foto de esa posición y vuelve a la ficha |
| `/gestion/alias` | GET | Solo lectura, solo admin (`gestion.alias`): tabla NOMBRE / ALIAS de todos los recursos. Único lugar de la web donde se ve el alias oculto — no hay edición acá |
| `/gestion/recursos/<id>/ubicaciones` | POST | Agrega/actualiza una fila del desglose por lugar |
| `/gestion/recursos/<id>/ubicaciones/eliminar` | POST | Saca una fila del desglose |

`slug` sólo puede ser `recursos`; otro valor → 404. (`hitos` y `personas` viven en
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
reconsiderar (índice, FTS). Decisión 2026-07-21 (ver `dev-log/DECISIONS.md`).

**Segunda pasada por alias** (solo `recursos`): si una fila no matchea por
nombre/descripción, `crud.py` prueba además contra `recursos.alias` — una columna oculta
que **completa el agente, nunca el humano** (no está en `campos`, así que no aparece en el
form web ni en la ficha de confirmación del chat — ver `agent_docs/agente-asistente.md`). No
son sinónimos estrictos: "zapatilla" y "alargue" son cosas distintas que se confunden, y
también entran acá. Los que matchean solo por alias se muestran **al final** de la lista,
con la etiqueta "· por alias" (`templates/crud/lista.html`), y nunca se mezclan con los
matches normales. El mecanismo genérico (`crud.campo_alias(cfg_ent)`, análogo a
`campo_nombre`) vive en `agent_docs/crud-motor.md`; acá solo se declara `'campo_alias':
'alias'` en `ENTIDADES['recursos']`. Ver `dev-log/DECISIONS.md` 2026-08-08 y 2026-08-21
(cierra tarea #21 de `dev-log/tasks/DONE.md`).

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

Sección mostrada en detalle (`secciones_detalle`): recurso → **Por ubicación** (desglose,
solo si tiene más de una unidad o ya se desglosó alguna vez).

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
de diseño: 5 recursos (panel solar, estructura regulable, inclinómetro digital,
multímetro, pinza amperométrica).

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
| `gestion.leer` | leer | ver el inventario. Es el permiso base del blueprint |
| `gestion.editar` | escribir | `nuevo`/`editar`/`eliminar`/fotos/desglose por ubicación |
| `gestion.alias` | admin | `/gestion/alias`, la tabla de solo lectura con el alias oculto de cada recurso. Verbo `admin`: no entra en ningún preset de interno, solo lo tiene el comodín `'*'` (mismo criterio que `historia.personas`) |

`PERMISO_ESCRITURA` lo aplica `crud.registrar_rutas` a sus cinco rutas genéricas, y las dos
rutas propias del desglose por ubicación lo piden a mano con `@accesos.requiere(...)`.

Con `gestion.leer` a secas la UI queda en modo consulta: sin CREAR, sin Editar, sin ELIMINAR y
sin subida de fotos. El motor entero de accesos está en `agent_docs/accesos.md`.

Es una traba de desarrollo, no seguridad completa: sin usuarios ni auditoría, sin
CSRF, sin límite de intentos. Decisión 2026-07-19 (ver `dev-log/DECISIONS.md`).
El SPA de horarios y `/api/*` siguen sin auth.
