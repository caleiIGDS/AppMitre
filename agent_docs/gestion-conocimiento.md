# Gestión de recursos (`/gestion`)

Una de las cinco áreas de la app. Son los **inventarios técnicos** de la escuela: recursos
(instrumentos, equipos, materiales, estructuras), con sus fotos y su desglose por ubicación.
**La base del inventario es la fuente de verdad**: lo que no está ahí, no está. Las fotos
viven en la propia base (columna `fotos`, ver abajo).

## No es un inventario: son varios, y son estancos

Desde el 2026-09-02 el área no tiene UNA base sino una por inventario. `gestion.db` quedó
como el **registro** (la tabla `inventarios`, más las tablas del asistente que siempre
vivieron ahí) y cada inventario es `database/inventarios/<slug>.db` con sus cuatro
tablas. Como todas las bases del proyecto, viven en `database/` (ver `database/LEEME.md`).

Todo se usa desde la app instalable (`/gestion/`, ver `agent_docs/app-instalable.md`);
el servidor sólo da la API JSON (`/app/api/gestion/…`). Las pantallas:

```
/gestion/                   inicio: las áreas
/gestion/inventarios        la lista de inventarios (administración: crear, renombrar, clave, eliminar)
/gestion/entrar             clave del ADMIN GENERAL (GESTION_CLAVE)
/gestion/<inv>/entrar       clave DE ESE INVENTARIO: entra el encargado
/gestion/<inv>/…            todo lo que este documento describe, adentro de uno
/gestion/<inv>/accesos      el encargado invita y revoca, sólo para su inventario
```

Lo que separa un inventario de otro **no es un filtro sino el archivo**: estando conectado a
uno es imposible leer el de al lado aunque a alguien se le olvide un `WHERE`. `crud.conectar`
pregunta por el hook `db_path()`, que resuelve el inventario del request (la URL) o el de la
sesión (`inv_activo`, que es de dónde lo saca el asistente).

**El admin general (GESTION_CLAVE) entra a todos y ve sus claves.** Desde 2026-10-05:
`_acceso_encargado` le suma el juego completo de `PERMISOS_AMBITO` en el inventario activo,
y la lista le muestra la clave de cada uno (`clave_ver`, cifrada con `SECRET_KEY`; las
puestas antes de esa fecha o con otra `SECRET_KEY` no se pueden mostrar: hay que volver a
ponerlas). El comodín `'*'` sigue sin alcanzar las claves de ámbito, así que un
*dispositivo* con perfil admin NO entra — ver `agent_docs/accesos.md`.

`bp_api` (`/app/api/gestion/<inv>`): un `url_value_preprocessor` guarda el `<inv>` en `g.inv`
y un `url_defaults` lo vuelve a poner al construir cualquier link.

> Hasta el 2026-08-10 el modelo era otro: los archivos reales vivían en Google Drive y cada
> entidad guardaba un link en `drive_url`. La escuela dejó de usar Drive y la columna se
> eliminó. Si ves `drive_url` en un respaldo viejo, es de antes de ese corte.

**Qué NO está acá**: hasta 2026-09 la línea del tiempo institucional (`hitos`) y las fichas de
personas vivían como área hermana en `/historia` + `historia.db`, separada el 2026-08-10 —
se extrajo del código, ver `dev-log/DECISIONS.md`. `gestion.py` sigue sin importar ningún
área de dominio, ni falta que hace: comparte el motor genérico `crud.py`, que tampoco importa
ninguna — ver `agent_docs/crud-motor.md`.

> Hasta el 2026-08-21 el módulo también tenía `conjuntos`, `actividades` y un bloque entero
> de préstamos/retiro interno con carrito en sesión. Se sacaron por decisión de producto
> (no se iban a seguir usando), no por deuda técnica — ver `dev-log/DECISIONS.md` 2026-08-21
> si alguna vez se retoman. Lo que sigue describe el módulo **después** de ese corte.

## Arquitectura

- **`gestion.py`** — el área: `ENTIDADES` (hoy solo `recursos`), `SCHEMA` (el de un
  inventario) y `SCHEMA_REGISTRO`, sus hooks (`migrar`, `db_path`, `prefijo_backup`,
  `secciones_detalle`) y **el desglose de recursos por ubicación**, que es lo único que no
  pasa por el motor. Expone dos blueprints de API JSON: `bp_api_registro`
  (`/app/api/gestion/inventarios`: la lista y su administración) y `bp_api`
  (`/app/api/gestion/<inv>/…`, con la clave del encargado). El CRUD genérico lo monta
  `crud.registrar_api(bp_api, ...)` y el gate `accesos.registrar_acceso_api` — ver
  `agent_docs/crud-motor.md`. Las acciones propias (bajas, unidades, kit, alias, quién
  entra) son funciones que usan la API y el asistente (`agregar_unidades`,
  `eliminar_unidades`, `revertir_baja_unidad`, `guardar_alias`, …). Las páginas clásicas
  (Jinja) se sacaron el 2026-10-05: ver `dev-log/DECISIONS.md`.
- **`gestion.db`** — el **registro**: la tabla `inventarios` (id, slug, nombre,
  `clave_hash`, creado) y nada de dominio. Alberga además las tablas del asistente
  (`agente_log`, `agente_conversaciones`, `agente_fotos_pendientes`), que son auditoría/
  sesión y nunca fueron de un inventario en particular.
- **`database/inventarios/<slug>.db`** — un archivo por inventario, con `recursos`,
  `recurso_unidades`, `kit_items` y `recurso_bajas`. **No** se regeneran desde Sheets y
  `/api/actualizar` no las toca. El `slug` sale del nombre y no se renombra nunca (es la
  URL); el ámbito de los permisos va por **id**, así que renombrar no rompe nada.
- **La interfaz** es la app: `frontend/src/vistas/gestion/` (listado, ficha, formulario,
  unidades, kit, bajas, alias, accesos). Ver `agent_docs/app-instalable.md`.
- **`static/gestion.css`** — hoja de estilos para gestión/agente/salidas/accesos (importa
  `global.css`). Sin modo oscuro. La comparten `/agente` y `/accesos`: la identidad
  visual sí es común, la lógica de dominio no. Completamente separada de `horarios.css`.
- **`static/mobile-nav.js`** — el ☰ y su panel lateral de las páginas Jinja
  (`/agente`, `/salidas`, `/accesos`); la app tiene el suyo (`Encabezado.vue`) (ver "Celular" abajo). No es lógica de dominio: solo mueve nodos
  del shell.
- Integración: `app.py` registra `gestion.bp_api_registro` y `gestion.bp_api` y sirve la app
  compilada en `/gestion/`; `gestion.init_db()` corre en import (funciona bajo gunicorn/WSGI).

## Celular

Todo el shell (header + nav + fichas) es **el mismo markup en celular y en escritorio** (páginas Jinja):
lo único que cambia es CSS, más un script que reubica bloques. Es común a las
áreas que comparten `gestion.css` (`/agente`, `/salidas`, `/accesos`; la app de Gestión importa la misma hoja).

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
| `recursos` | id, nombre, tipo, descripcion, estado, cantidad, valor, fecha_revision, **fotos**, **alias** |
| `recurso_unidades` | recurso_id, numero, ubicacion (`UNIQUE(recurso_id, numero)`) — **qué unidades existen** y dónde está cada una, ver abajo |
| `kit_items` | id, recurso_id, titulo, cantidad, recurso_asignado — los sub-recursos de un kit, ver abajo |
| `recurso_bajas` | id, recurso_id, recurso_nombre, motivo, detalle, fecha, numero, revertida — el registro de bajas; `numero` NULL = recurso entero, con valor = esa unidad puntual, ver abajo |

**Unidades y `cantidad`** (`recurso_unidades`): `recurso_unidades` es la **fuente de verdad de qué
unidades existen** (una fila por unidad, con su `numero` propio) y de dónde está cada una
(`ubicacion`, `''` = sin ubicar). **`recursos.cantidad` es su COUNT espejo**, no un valor
independiente: lo escribe sólo `_sincronizar_cantidad()` (y el alta). `recursos` no tiene columna
`ubicacion` — la ubicación de un recurso ES la lista de sus unidades, aunque tenga una sola, y
**nunca es obligatorio que esté completa**: una unidad sin ubicación no es un error, para no
bloquear un movimiento por no tener el desglose cargado.

Los números **pueden tener huecos a propósito**: si se rompe la pinza 2, se elimina la unidad #2 y
quedan 1, 3, 4, 5. `_asegurar_unidades()` sólo siembra `1..max(cantidad,1)` cuando el recurso
**todavía no tiene ninguna** unidad — una vez que tiene, no vuelve a fabricar (hasta el 2026-09-09
rellenaba cualquier hueco en cada lectura, con lo cual borrar una unidad puntual no servía).
Se agregan y eliminan **por número desde EDITAR** (`EditorUnidades.vue`, bloque
"UNIDADES"): `+` se tocan los números libres que se quieren (los huecos y los 10 siguientes al
más alto, "más…" suma de a 10; nada se escribe) y `unidad_agregar` rechaza igual un ID usado; `−` marca cuáles y
**exige motivo** (`MOTIVOS_BAJA`) — cada unidad eliminada va a `recurso_bajas` con su `numero`
(`unidad_eliminar`), y nunca se borra la última que queda (para sacar el recurso entero está la
baja de recurso). El agente no tiene tool por unidad, pero si cambia `cantidad` por el chat
(`editar_entidad`) `reconciliar_unidades()` ajusta las unidades para que el espejo no mienta
(agrega los libres más bajos / saca las de número más alto, sin registrar bajas).

Helpers en `gestion.py`: `unidades_recurso()` (unidades de un recurso, por número), `lugares_recurso_agrupado()`
(las mismas agrupadas por lugar, para la ficha y para el chat), `lugares_por_recurso()` (la misma
agrupación para TODOS los recursos de una, para el listado), `mover_unidades()` (mueve por número
puntual o por cantidad genérica, avisando si algo no coincidía con lo registrado), `_stock()`
(cantidad total del recurso, la usa además `agente/tools/ubicaciones.py` para chequear que el id
exista). Se edita desde la ficha de la app (`…/recursos/<id>/unidades/mover` y `/quitar` de la API,
sección "Ubicación" del detalle, siempre visible) y desde el chat (tool `mover_ubicacion` para un
recurso que ya existe; en el alta, el parámetro `ubicacion` de `crear_entidad` la deja fijada al
confirmar la ficha — ver `agent_docs/agente-asistente.md`). No hay `ubicacion` en `editar_entidad`. Hasta el 2026-08-22 existió un campo `ubicacion` simple en
`recursos`, con este desglose como algo opcional aparte; se unificó porque un valor y su desglose
podían quedar desincronizados. La migración de `gestion.migrar()` reparte el valor viejo entre las
unidades la primera vez que corre — ver `dev-log/DECISIONS.md`.

**Kits** (`kit_items`): un recurso es un "kit" (ej: Kit Arduino) en cuanto tiene sub-recursos
cargados acá — no hay tipo/flag aparte, mismo criterio orgánico que `recurso_unidades`. Cada
sub-recurso es sólo `titulo` + `cantidad` + `recurso_asignado` (texto libre e independiente,
**no** un link a otro recurso de `recursos`). Helpers en `gestion.py`: `kit_items_recurso()`
(sub-recursos de un kit, para la ficha) y `buscar_kit_items()` (los que matchean una búsqueda,
en cualquier kit, para el listado — ver "Búsqueda tolerante" abajo). Se agrega, edita y borra
por renglón **dentro de EDITAR** (`EditorKit.vue`; API `POST …/recursos/<id>/kit`,
`PUT`/`DELETE …/kit/<item_id>`) — ahí es donde se completa `recurso_asignado`, que el chat
nunca toca. **La ficha muestra el kit sólo de lectura**, y si está vacío no muestra la sección.

El chat arma un kit **al dar de alta** el recurso: `crear_entidad(..., sub_recursos=[{titulo,
cantidad}, ...])` (ver "Alta con ficha de confirmación" en `agent_docs/agente-asistente.md`) —
sólo título y cantidad, sin `recurso_asignado`. También puede sumar sub-recursos a un kit **ya
existente** con `editar_entidad(id, sub_recursos=[...])`: a diferencia del resto de esa tool, acá
es ADITIVO (agrega sin reemplazar ni pisar lo que ya tenía), pensado para cargar un kit en varias
tandas. Y puede corregir o sacar UN sub-recurso puntual con `editar_sub_recurso(id, item_id, ...)`
/ `eliminar_sub_recurso(id, item_id)` — el `item_id` (la fila de `kit_items`, no el id del kit)
sale de `detalle_entidad`. Las tres escriben directo, sin ficha de confirmación.

**Bajas** (`recurso_bajas`): **un recurso no se borra nunca**. `ENTIDADES['recursos']` declara
`sin_eliminar` (ver `agent_docs/crud-motor.md`), así que la ruta genérica de eliminar devuelve 404
y el chat tampoco puede: lo que se hace es **darlo de baja**, y la baja exige decir qué pasó. Se da
desde EDITAR (`BajaRecurso.vue`, un `<dialog>` con `motivo` + `detalle` libre) por
`POST …/recursos/<id>/baja`: `gestion.dar_de_baja()` inserta la fila del registro y deja el
recurso en `ESTADO_BAJA` (`"Dado de baja"`), que ya lo saca del listado salvo que se pida verlo.
`revertir_baja()` (botón REVERTIR BAJA, `POST .../baja/revertir`) devuelve el recurso al inventario
y marca esa fila como `revertida` — **no la borra**: el registro es el historial de lo que se
decidió, no la lista de lo que hoy está de baja. `recurso_nombre` es la foto del nombre al momento
de la baja, para que renombrar el recurso después no reescriba la historia. `MOTIVOS_BAJA` = Uso /
Desgaste / Extravío / Rotura / Otro, y el detalle libre es lo que la explica. El registro completo
se ve en `/gestion/<inv>/bajas` (`Bajas.vue`, API `GET …/bajas`), solo con `gestion.auditoria`.

**Baja de una unidad puntual**: eliminar la unidad #N de un recurso (bloque "UNIDADES" de EDITAR,
`unidad_eliminar`) también anota en `recurso_bajas`, una fila por unidad, con su `numero` — así
"se rompió la pinza 2" queda con motivo y fecha igual que la baja de un recurso entero. En
el registro de bajas esas filas dicen "unidad #N" y traen un botón **Revertir** (`POST …/bajas/<baja_id>/revertir`):
re-crea la fila de `recurso_unidades` si ese número quedó libre y marca la baja `revertida`. La
baja del recurso entero no toca `recurso_unidades` (sigue siendo sólo `estado = ESTADO_BAJA`).

**Galería de fotos** (`fotos`): array JSON con objetos `{id, tipo, fecha}`. La imagen en sí
NO vive en la fila: es un archivo en `database/fotos/<id><ext>` (ver `fotos_disco.py`,
capa 0).
- `id`: uuid4 hex, también es la base del nombre del archivo en disco
- `tipo`: content-type (ej: `image/png`), decide la extensión del archivo
- `fecha`: timestamp ISO de cuándo se subió
- Upload: botón en ficha de detalle → se comprime client-side (`window.ImgUtils.achicarImagen`,
  1568px/JPEG q0.85, mismo criterio que el chat) → POST `/<slug>/<id>/foto` → se decodifica y
  se escribe en disco (`crud.agregar_foto`)
- Servido: `GET /<slug>/<id>/foto/<foto_id>` (`crud.foto_archivo`) — no pasa por `/static`
  porque la galería es privada; valida que `foto_id` pertenezca a esa fila antes de mandar
  el archivo
- Renderizado: galería grid responsive (120px minmax) de miniaturas recortadas (`object-fit: cover`)
- **Visor**: click en una miniatura abre un lightbox a pantalla completa (`.g-lightbox`, CSS en
  `gestion.css`, componente `Galeria.vue`) con la foto
  entera, contador `n / total`, flechas
  ‹ › (y ← → del teclado), cierre con Esc o click en el fondo, y los botones **ROTAR** y
  **ELIMINAR**
- Borrado: `POST /<slug>/<id>/foto/<foto_id>/eliminar` (con `confirm()`) → saca la foto del
  array y borra el archivo, y redirige a la ficha. Un `foto_id` que no existe no es error,
  se ignora (dos pestañas borrando a la vez)
- Rotación: `POST /<slug>/<id>/foto/<foto_id>/rotar` con la imagen **cruda en el body** y su
  `Content-Type`. El giro de 90° lo hace un `<canvas>` en el navegador y al server llega la
  imagen ya girada (así no hace falta Pillow ni ninguna dependencia nueva); reemplaza el
  ARCHIVO de esa foto (mismo `id`) y conserva `fecha`. El visor muestra la foto girada apenas
  termina de codificarla y **guarda en segundo plano** (botón en `GUARDANDO…`): si el POST
  falla vuelve a la imagen que sigue en la DB. Pide `gestion.rotar` — **solo admin**, a
  diferencia de subir y borrar
- Las miniaturas son `<button>` (no `<img>` suelta) para que el visor se abra también con teclado

Estados (`ESTADOS_RECURSO`): recursos = Funcional / Dañado usable / Roto. `"Dado de baja"`
(`ESTADO_BAJA`) **no** está en esa lista a propósito: no se elige a mano ni desde el form ni desde
el chat (la lista es también el enum de las tools), lo pone sólo la baja — ver "Bajas" más arriba.
Valor (recursos): "" / Básico / Secundario / Alto valor — es la *importancia* del recurso
dentro del inventario, no su precio (se llamaba `utilidad`, renombrada 2026-08-08).
`cantidad` y `fecha_revision` son TEXT. **`cantidad` es `solo_alta`** (ver `agent_docs/crud-motor.md`):
se escribe en el alta y después NO se edita a mano — es el COUNT espejo de `recurso_unidades` y se
ajusta por unidades desde EDITAR (ver "Unidades y `cantidad`" más arriba). **`fecha_revision` se
precarga con la fecha de hoy en todo alta de recurso**, por los dos caminos: el form web (`valores_iniciales()` en el
GET de `/recursos/nuevo`, donde sí es un campo editable) y el chat (`_normalizar_borrador()` en
`agente/tools/fichas.py`, antes de calcular el token). En la ficha del chat **ya no se muestra**
(`CAMPOS_OCULTOS_FICHA`): siempre es hoy y no se pregunta. Dar de alta un recurso es un control de inventario; antes quedaba vacía y casi
ningún recurso terminaba con fecha. "Hoy" sale de `config.ahora()` (hora de Buenos Aires; el
server de producción corre en UTC — ver "El reloj" en `agent_docs/crud-motor.md`). Formato
`gestion.FORMATO_FECHA_REVISION` = `%d/%m/%Y` (ej `08/08/2026`) — **conviven** con las fechas
cortas sin año del inventario importado del sheet ("24/4", "8/5"), que no se reformatean.
Editar un recurso **no** toca la fecha: `_editar_entidad` (agente) parte de la fila actual y
no pasa por `_normalizar_borrador`.

**Inventario físico**: la carga inicial vino del sheet "Inventario renovable 2026" vía
`importar_inventario.py`, un script de root que se corrió una vez (81 insertados +
2 actualizados) y **se eliminó definitivamente el 2026-08-27**, ya cumplido su propósito
(había vuelto un tiempo como red secundaria, pero `gestion.db` tiene sus respaldos y el
sheet quedó desactualizado). `gestion.db` es la fuente de verdad y nunca hubo write-back
al sheet (ver DECISIONS 2026-07-19), así que la planilla quedó como material histórico.
Si alguna vez hay que volver a importar, el script está en el historial de git
(`git log --diff-filter=D -- importar_inventario.py` para el commit que lo borró) — ojo
que mapeaba los estados Funcional→Disponible, Reparar→En reparación, nc→Sin revisar
(vocabulario viejo, hoy sería Funcional/Roto/""), y que traía las fechas de revisión en
formato corto sin año, incompatible con `FORMATO_FECHA_REVISION`.

## Config declarativa (`ENTIDADES` en gestion.py)

Cada entidad define: `tabla`, `singular`/`plural`, `descripcion` (card del home),
`campos` (form: nombre, label, tipo `text|textarea|select|url|date|number`, opciones, ayuda),
`columnas` (listado) y `relaciones` (M2M editables desde su form — hoy vacía: `recursos` no
tiene ninguna relación propia). Los campos de relación usan el prefijo `rel_` para no
colisionar con nombres de columnas.

**`campo_nombre`** (opcional, default `'nombre'`): cómo se llama en la tabla la columna que
hace de nombre visible. `recursos` no la declara distinta — el mecanismo existe
para una entidad de dominio futura cuya columna se llame otra cosa (hasta 2026-09 fue el
caso de `historia.hitos`, con `titulo`). Todas las lecturas van por **`crud.select(cfg)`**,
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
`recursos` → `recurso_unidades` + `kit_items` (ninguna es M2M de verdad: son el desglose por
unidad y los sub-recursos de un kit, pero el mecanismo de limpieza es idéntico).

## API (`/app/api/gestion/…`)

Todas las de `bp_api` van **abajo de un inventario** (`/app/api/gestion/<inv>/…`); las de la
tabla se escriben cortas. El CRUD genérico lo pone `crud.registrar_api`; el resto es de
`gestion.py`. Escrituras con `X-Mitre: 1`.

| Ruta | Método | Descripción |
|------|--------|-------------|
| `/app/api/gestion/inventarios` | GET/POST | La lista (con `abre`, y la clave para el admin general) / crear (`inventarios.admin`) |
| `/app/api/gestion/inventarios/<id>` | PATCH/DELETE | Renombrar o re-fijar la clave / eliminar (exige escribir el nombre) |
| `/entrar` · `/salir` | POST | La clave DE ESE inventario / cerrar sólo ese inventario |
| `/meta` | GET | Config de las entidades y los permisos de la sesión en este inventario |
| `/<slug>` · `/<slug>/<id>` | GET | Todos los recursos (con ETag) / uno |
| `/<slug>` · `/<slug>/<id>` | POST/PUT/DELETE | Alta / edición con `version` (409 si cambió) / borrar (**404 en `recursos`**, que declara `sin_eliminar`) |
| `/<slug>/<id>/fotos[/<foto_id>]` | POST/GET/PUT/DELETE | Subir / servir / rotar (`gestion.rotar`) / borrar una foto |
| `/recursos/<id>/baja` · `/baja/revertir` | POST | Dar de baja (exige `motivo`) / devolverlo al inventario |
| `/recursos/<id>/unidades/agregar` · `/eliminar` | POST | Unidades por `numeros`; eliminar exige `motivo` y nunca borra la última |
| `/recursos/<id>/unidades/mover` · `/quitar` | POST | Fijar lugar de unidades / marcar "sin ubicar" |
| `/recursos/<id>/kit` · `/kit/<item_id>` | POST/PUT/DELETE | Sub-recursos del kit |
| `/alias` · `/alias/<id>` | GET/PUT | Tabla NOMBRE / ALIAS (`gestion.alias`) |
| `/bajas` · `/bajas/<baja_id>/revertir` | GET/POST | Registro de bajas (`gestion.auditoria`) / revertir la baja de una unidad |
| `/accesos` | GET | Panel del encargado (`gestion.accesos`): dispositivos, links activos, perfiles y permisos |
| `/accesos/invitaciones` · `/<id>` | POST/DELETE | Generar un link / anularlo |
| `/accesos/dispositivos/<id>/quitar` | POST | Sacarle a un dispositivo los permisos de ESTE inventario |

`slug` sólo puede ser `recursos`; otro valor → 404.

## Búsqueda tolerante

No es el `LIKE` literal de SQL: la app tiene todas las filas y las filtra/ordena en el
navegador con `frontend/src/texto.js`, puerto de `texto.puntaje_busqueda()` (el asistente usa
el de Python). Perdona **acentos y mayúsculas** (normaliza con `texto.norm`)
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
sin mostrar el alias (no se le muestra al humano), y nunca se mezclan con los matches normales. El mecanismo genérico (`crud.campo_alias(cfg_ent)`, análogo a
`campo_nombre`) vive en `agent_docs/crud-motor.md`; acá solo se declara `'campo_alias':
'alias'` en `ENTIDADES['recursos']`. Ver `dev-log/DECISIONS.md` 2026-08-08 y 2026-08-21
(cierra tarea #21 de `dev-log/tasks/DONE.md`).

**En vivo**: el listado (`Inventario.vue`) filtra mientras se escribe. La API manda por fila
el texto ya normalizado por Python (`_buscar` = nombre + descripción, `_buscar_alias` aparte)
y la app repite la jerarquía de arriba: primero lo que coincide por nombre/descripción (en
orden alfabético), después lo que coincide sólo por alias. **Van separados porque reordena**:
concatenados, buscar "pinza" dejaba "Alicate" (alias `pinza universal`) arriba de "Pinza de
fuerza". Decisión 2026-08-24, revierte la parte "solo substring" de 2026-07-21 (ver
`dev-log/DECISIONS.md`).

**Sub-recursos de kits en la búsqueda**: el listado principal nunca mezcla sub-recursos con
recursos — sólo con una búsqueda escrita, `Inventario.vue` busca también en el `kit` de cada
recurso y muestra los que matchean **al final de la misma tabla**, en un bloque que abre una
franja naranja ("SUB-RECURSOS DE KITS"): misma fila que un recurso, con un recuadro naranja
"KIT · <kit>", el estado del kit y el lugar vacío; el click abre la ficha del kit. Heredan los
filtros de su kit (ubicación, estado, revisión, baja): un kit dado de baja no muestra los suyos.

Secciones del detalle (`secciones_detalle`, las usa el asistente; la ficha de la app muestra lo mismo): recurso → **Ubicación** (la lista de
unidades, siempre presente) y **Sub-recursos (kit)** (los `kit_items` del recurso, sólo de
lectura y sólo si tiene alguno).

## Respaldos (`database/backups/`)

Las bases de los inventarios no se regeneran desde Sheets y están en `.gitignore`, así que
**si un archivo se pierde no hay commit ni fuente externa de la cual recuperarlo**. Por eso
`init_db()` recorre el registro y llama a `crud.init_db` por inventario, que arranca
respaldando.

- Copia a `database/backups/inv<id>-YYYYMMDD-HHMMSS-ffffff.db` con la **API `backup()` de
  sqlite3**, no `shutil.copy`: garantiza una copia consistente aunque otro proceso
  esté escribiendo. Los microsegundos evitan que dos respaldos del mismo segundo se
  pisen y mantienen el orden alfabético igual al cronológico.
- **No respalda una DB sin recursos.** Un respaldo vacío encima de los buenos sería
  justo lo que arruinaría la recuperación.
- **No duplica**: si el contenido no cambió desde el último respaldo, lo descarta.
- **Retención** (`respaldos._a_borrar`): los últimos `BACKUP_MAX` (20) **más el primero de cada
  día**. Sin la regla diaria, una tarde de reinicios depurando empuja fuera de la
  rotación todo lo viejo — que es exactamente lo que uno querría recuperar.
- **Un prefijo por inventario, y por id y no por slug** (`prefijo_backup()`): `respaldos.listar`
  globea `<prefijo>-*.db`, así que con slugs la rotación de "taller" se comería la de
  "taller-2". El registro usa `gestion-registro`. Eliminar un inventario respalda antes de
  borrar el archivo: un borrado por error no puede ser definitivo.

Los respaldos caen bajo `*.db` del `.gitignore`; no se versionan ni se pushean.

## Sin seed, pero con la guarda anti-pérdida

**No hay `seed`.** Los 5 recursos de ejemplo del documento de diseño tenían sentido cuando el
área era una sola base que se creaba una vez; ahora se crea una por inventario y sembrar el
banco de ensayo solar en cada uno sería ruido que después hay que borrar a mano. Un
inventario nuevo arranca vacío a propósito.

Lo que sí sigue es la guarda de `crud.init_db`: una DB vacía es ambigua —instalación nueva o
datos perdidos— y los respaldos desempatan. Si el archivo de un inventario está vacío y
**hay respaldos con su prefijo**, `init_db()` levanta `RuntimeError` con las instrucciones de
restauración en vez de seguir de largo (que es lo que pasó el 2026-08-08: se trabajó un día
entero contra los 5 de ejemplo sin notarlo). Un inventario recién creado no tiene respaldos
propios todavía, así que no dispara. Para pasar por encima: `GESTION_SEED=1`.

## Permisos

El área declara siete. Seis son **de ámbito**: valen sólo adentro del inventario abierto y el
comodín `'*'` no las alcanza (se guardan como `inv:<id>/gestion.editar`, ver
`agent_docs/accesos.md`). La séptima, `inventarios.admin`, es la única que tiene el admin
general y no abre ningún inventario.

| clave | verbo | qué habilita |
|---|---|---|
| `inventarios.admin` | admin | **sin ámbito**: crear, renombrar, re-fijar la clave y eliminar inventarios desde `/gestion/inventarios`. NO da acceso al contenido de ninguno |
| `gestion.leer` | leer | ver el inventario. Es el permiso base del blueprint |
| `gestion.editar` | escribir | `nuevo`/`editar`/fotos/desglose por ubicación + dar de baja un recurso y revertir la baja (borrar, no: ningún recurso se borra) |
| `gestion.alias` | admin | `/gestion/<inv>/alias`, editable, y la tool del agente `listar_alias`. Verbo `admin`: no entra en ningún preset de interno, solo lo tiene el comodín `'*'` |
| `gestion.auditoria` | admin | los chips de auditoría del listado (vencidos de revisión, dados de baja) y `/gestion/<inv>/bajas`, el registro de bajas |
| `gestion.rotar` | admin | el botón ROTAR del visor de fotos y su ruta. `crud.py` lo lee del hook opcional `PERMISO_ROTAR_FOTO`; un área que no lo declara cae en su permiso de escritura |
| `gestion.accesos` | admin | `/gestion/<inv>/accesos`: invitar y quitar gente DE ESE inventario. Lo tiene el encargado por haber entrado con la clave, y lo puede delegar |

`PERMISO_ESCRITURA` lo aplica `crud.registrar_api` a sus escrituras genéricas, y las rutas
propias de `bp_api` lo piden a mano con `@accesos.requiere(...)`.

Con `gestion.leer` a secas la UI queda en modo consulta: sin CREAR, sin Editar, sin DAR DE BAJA y
sin subida de fotos. El motor entero de accesos está en `agent_docs/accesos.md`.

**Cómo se entra a un inventario**, dos caminos que se suman: la **clave** del inventario
(`/gestion/<inv>/entrar` → `POST …/entrar`, la guarda `session['inv_claves']` como huella del hash, así que
re-fijarla corta esas sesiones en el request siguiente) da el juego completo; o un **link de
invitación** del encargado, que crea un dispositivo con las claves ya prefijadas. Una misma
persona puede ser encargada del taller y estar invitada al laboratorio, y en cada uno tiene
lo suyo. "QUITAR" desde el panel del encargado saca **sólo** las claves de ese inventario:
si esa persona además usa el asistente, eso no se toca.

Es una traba de desarrollo, no seguridad completa: sin usuarios ni auditoría, sin
CSRF, sin límite de intentos. Decisión 2026-07-19 (ver `dev-log/DECISIONS.md`).
Horarios tiene su propia clave, aparte (`horarios/acceso.py`).
