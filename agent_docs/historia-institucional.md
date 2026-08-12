# Historia institucional (`/historia`)

Una de las cuatro áreas de la app (las otras: el SPA de horarios, `/gestion` y `/agente`).
Es la **línea del tiempo de la escuela** — qué pasó, cuándo y quién estuvo — más las fichas de
las personas que la hicieron.

## Ojo con el nombre: `historia.py` ≠ `historias/`

Conviven dos cosas con nombre parecido y propósito distinto. No mezclarlas:

| | `historia.py` / `historia.db` / `/historia` | `historias/*.json` + `historia_indice.json` |
|---|---|---|
| Qué es | Hechos institucionales con ficha: hitos y personas | Anécdotas y lore narrados por el personaje Emilio Mitre |
| Formato | SQLite, CRUD web | Archivos JSON, solo lectura |
| Quién lo usa | La web de `/historia` y el agente (`buscar_hitos`, CRUD genérico) | Solo el agente, vía `consultar_historia` |
| Se inventa | El usuario lo redacta | **Nunca**: los textos son literales del archivo |
| Doc | este archivo | `HISTORIAS_PROCEDIMIENTO.md` y `agent_docs/agente-asistente.md` |

Una semblanza institucional (acá) y una anécdota de Emilio (allá) son cosas distintas, y el
system prompt del agente le pide explícitamente no mezclarlas.

## Arquitectura

- **`historia.py`** — el área, en ~200 líneas de pura declaración: blueprint Flask (`bp`, prefix
  `/historia`), `ENTIDADES`, `SCHEMA` y sus hooks (`migrar`, `derivados`, `secciones_detalle`,
  `ERROR_DUPLICADO`) más `clave_persona`. Las rutas CRUD las monta `crud.registrar_rutas(bp, ...)`
  y el gate `crud.registrar_acceso(bp)` — ver `agent_docs/crud-motor.md`.
- **`historia.db`** — SQLite propia. No se regenera desde ninguna fuente externa y está en
  `.gitignore`: si se pierde el archivo no hay commit del cual recuperarla, por eso
  `init_db()` arranca respaldando (ver "Respaldos").
- **`templates/historia/`** — `base.html` (layout + nav propia: INICIO / HITOS / PERSONAS) y
  `home.html`, que son lo propio del área. `lista.html`, `form.html`, `detalle.html` y
  `login.html` son stubs de dos líneas que extienden los genéricos de `templates/crud/`:
  historia no necesita sobreescribir ningún bloque.
- **No importa `gestion.py`.** El motor CRUD (conexión, búsqueda tolerante, `select`, guardado,
  respaldos, rutas genéricas) es **compartido**: vive en `crud.py`, que a su vez **no importa
  ninguna área** — las recibe como argumento. Todo lo que nombra una tabla de `historia.db` entra
  por un hook declarado, nunca por un `if` dentro del motor. Ver `agent_docs/crud-motor.md` y
  `dev-log/DECISIONS.md` 2026-08-10 ("Cero duplicación, con un criterio de pertenencia por capas").
- Sí comparte con `/gestion` lo que **no** es lógica de dominio: `static/gestion.css` (paleta),
  `static/gestion-agente.js`, `static/mobile-nav.js` y el widget flotante del asistente
  (`templates/agente/_agente_widget.html`).
- Integración: `app.py` hace `app.register_blueprint(historia.bp)` + `historia.init_db()` en
  import (funciona bajo gunicorn/WSGI). El header linkea a las otras tres áreas.

**Celular**: el shell mobile (menú lateral ocultable con ☰, listados como tarjetas, objetivos
táctiles) es el mismo de `/gestion` y está documentado allá, en la sección "Celular" de
`agent_docs/gestion-conocimiento.md`. Lo único que hay que recordar acá: los `<td>` de
`lista.html` llevan **`data-label`** con el nombre de la columna, que es lo que la vista de
tarjetas muestra como etiqueta. Si agregás una columna, ponele `data-label`. Escritorio no
cambia: todo vive en media queries de ≤900px / ≤700px.

## Modelo de datos (historia.db)

| Tabla | Campos |
|-------|--------|
| `hitos` | id, **titulo**, descripcion, fecha, tipo, nivel, etiquetas, protagonistas, **fotos** |
| `personas` | id, nombre, **nombre_norm**, descripcion, fecha_actualizada, **fotos** |
| `persona_hitos` | persona_id, hito_id (`UNIQUE` por par, índice por `persona_id`) |

Índices: `idx_hitos_fecha` (fecha DESC), `idx_hitos_nivel`, `idx_personas_norm` (UNIQUE).

`historia.db` es la fuente de verdad: no hay archivos afuera. La columna `drive_url` que tenían
las dos tablas se eliminó el 2026-08-10, junto con la de `gestion.db` — la escuela dejó de usar
Google Drive (ver `dev-log/DECISIONS.md`).

Valores cerrados: `tipo` ∈ Evento / Logro / Carrera nueva / Construcción / Participación /
Programa / Otro. `nivel` ∈ Básico / Importante / Crítico.

**Galería de fotos** (`fotos`): array JSON con objetos `{b64, tipo, fecha}`, igual que en
`/gestion` — base64 embebido, upload por `POST /<slug>/<id>/foto`, grid responsive en el
detalle. `crud.agregar_foto()` vive suelta (fuera de la ruta) porque el agente también escribe la galería.
Click en una miniatura abre el **visor** (lightbox: foto entera, contador, flechas ‹ ›/teclado,
Esc para cerrar) y desde ahí se borra con `POST /<slug>/<id>/foto/<indice>/eliminar`. Igual que
el resto del motor, es una copia de lo de `/gestion`: mismo CSS (`gestion.css`), JS inline
duplicado en cada `detalle.html`, y el borrado referencia la **posición en el array** porque
las fotos no tienen id propio.

**No hay relaciones que crucen a `gestion.db`.** Las había (`proyecto_recursos` ataba proyectos
con recursos) y se eliminaron: hoy las dos DBs son independientes.

### No existe la entidad `proyectos`: es una etiqueta de `hitos`

Un "proyecto" (un trabajo construido por un curso) es un hecho de la línea del tiempo como
cualquier otro, así que se carga como **hito con `Proyecto` en `etiquetas`** — no como un tipo
aparte ni como valor de `tipo` (que es una clasificación cerrada y distinta). La entidad
`proyectos` y su tabla `proyecto_recursos` se eliminaron el 2026-08-10; las filas existentes se
migraron a hitos con esa etiqueta, conservando el estado del proyecto dentro de `descripcion`.
Ver `dev-log/DECISIONS.md`.

### Personas — la memoria de quién hizo la escuela

`personas` es un grafo, no una lista: una fila por persona (con una **semblanza** en prosa en
`descripcion`) y los hilos M2M que la unen a `hitos`. La ficha muestra los hitos en los que
aparece, y el hito muestra la inversa ("Personas involucradas").

**`hitos` declara `rel_personas` además del texto libre `protagonistas`** — son dos cosas
distintas y conviven a propósito: `protagonistas` es una línea de texto que admite cursos
("6° B") y gente que no tiene ficha, y `rel_personas` es el vínculo navegable con la fila de
`personas`. La relación está declarada **de los dos lados** sobre la misma tabla
`persona_hitos` (`personas.rel_hitos` y `hitos.rel_personas`); es simétrica, y por eso el hito
se puede editar desde su propio formulario y `vincular_entidad` acepta cualquiera de las dos
direcciones.

**La identidad es `nombre_norm`, no `nombre`** — columna derivada con un `UNIQUE` encima, que
calcula `historia.clave_persona()` (público): saca puntuación, normaliza con `_norm` y **ordena
las palabras alfabéticamente**. Sin ese orden, "Juan Pablo Crivari" (como lo tipea una persona)
y "CRIVARI JUAN PABLO" (como sale de `limpiar_profesor()` en los horarios) serían dos fichas de
la misma persona con los hilos repartidos. `nombre` guarda la grafía para mostrar. El precio es
que dos nombres que son la misma bolsa de palabras chocan; se prefirió ese error visible al
duplicado silencioso — ver `dev-log/DECISIONS.md` 2026-08-08.

**No hay sincronización con `escuela.db`.** Los horarios se regeneran desde Sheets; `personas`
es memoria permanente y **tiene que sobrevivir** a que alguien salga del padrón. No hay FK entre
las DBs: el puente es `clave_persona()` sobre el nombre. Son **dos padrones distintos** y el
agente tiene reglas específicas para no confundirlos (ver `agent_docs/agente-asistente.md`).

`fecha_actualizada` también es derivada (se pisa en cada guardado) — ninguna de las dos está en
`campos`, las agrega el hook `derivados()`, que `crud` aplica en los dos caminos de guardado (el
formulario web y el del agente). La fecha sale de `config.ahora()`, no de `datetime.now()`: el
server de producción corre en UTC (ver "El reloj" en `agent_docs/crud-motor.md`).

**No hay campo `rol`**: una taxonomía fija se queda corta enseguida — alguien es docente y ex
alumno a la vez, o pasa de preceptor a directivo — y la semblanza ya lo dice mejor en prosa.
Queda como recordatorio que `descripcion` es un juicio sobre una persona real, y que esto vive
detrás de una clave compartida cuyo default está en un repo público: escribir semblanzas de
alumnos menores pide una auth de verdad primero.

## Config declarativa (`ENTIDADES` en historia.py)

Mismo contrato que `gestion.ENTIDADES` — está documentado una sola vez, en
`agent_docs/crud-motor.md`: cada entidad define `tabla`, `singular`/`plural`, `descripcion`
(card del home), `campos` (form), `columnas` (listado) y `relaciones` (M2M editables desde su
form, con prefijo `rel_`).

**`campo_nombre`** (opcional, default `'nombre'`): `hitos` la declara como `'titulo'`. Todas
las lecturas van por **`crud.select(cfg)`**, que agrega `titulo AS nombre`, así que templates,
`crud.buscar_entidad`, `crud.snapshot_entidad` y el agente leen siempre `fila['nombre']`.
Las escrituras y la validación de obligatorio usan `crud.campo_nombre(cfg)`.

`LIMPIEZA_M2M` mapea qué tablas de relación limpiar al eliminar cada tipo de entidad.

Para agregar un campo: sumarlo al `SCHEMA`, a `campos` y al loop aditivo de `_migrar()` —
`init_db()` hace el `ALTER TABLE` automáticamente en DBs existentes.

## Rutas (todas server-rendered)

| Ruta | Método | Descripción |
|------|--------|-------------|
| `/historia/login` | GET/POST | Form de contraseña; setea `session['gestion_ok']` y redirige a `?next=` (solo si empieza con `/historia`, anti open-redirect) |
| `/historia/salir` | GET | Borra la sesión y vuelve al login |
| `/historia/` | GET | Home: cards con contadores |
| `/historia/<slug>` | GET | Listado (`?q=` búsqueda tolerante en nombre + descripcion) |
| `/historia/<slug>/nuevo` | GET/POST | Alta (valida nombre/título no vacío server-side) |
| `/historia/<slug>/<id>` | GET | Detalle: campos + galería + relaciones |
| `/historia/<slug>/<id>/editar` | GET/POST | Edición (sincroniza M2M: delete + insert) |
| `/historia/<slug>/<id>/eliminar` | POST | Borra fila + sus filas M2M (confirm en el browser) |
| `/historia/<slug>/<id>/foto` | POST | Sube una imagen a la galería (base64) |
| `/historia/<slug>/<id>/foto/<indice>/eliminar` | POST | Borra la foto de esa posición y vuelve a la ficha |

`slug` ∈ {hitos, personas}; otro valor → 404.

## Permisos

Tres, declarados en `historia.py` y montados con `accesos.registrar_acceso(bp, PERMISO_LECTURA)`,
una línea al final del módulo:

| clave | verbo | qué habilita |
|---|---|---|
| `historia.leer` | leer | ver la línea del tiempo de hitos. Permiso base del blueprint |
| `historia.editar` | escribir | `nuevo`/`editar`/`eliminar`/fotos, que decora `crud.registrar_rutas` |
| `historia.personas` | admin | **todo lo de la entidad `personas`** — ver abajo |

A diferencia de `/gestion`, acá **no hay rutas fuera del motor**: el área es CRUD puro, así que con
declarar `PERMISO_ESCRITURA` queda todo cubierto. Motor completo en `agent_docs/accesos.md`.

### `personas` es sólo del admin

La entidad lo declara en su propia cfg y el motor CRUD hace todo lo demás:

```python
'personas': {..., 'permiso': 'historia.personas'},
```

Sin ese permiso, `/historia` se ve igual pero **sin personas por ningún lado**: no está la tarjeta
del home, ni la entrada de la nav, ni el listado, ni una ficha, ni los formularios, ni las rutas de
fotos (todo 403), y la ficha de un hito no muestra su bloque "Personas involucradas". Editar un hito
desde ahí **no le borra** los vínculos con personas: el fieldset que no se muestra tampoco se
guarda (ver `crud.relaciones_visibles`).

El verbo es `'admin'`, así que no entra en ningún preset de interno: sólo lo tiene el admin, por el
comodín `'*'`. Se puede tildar a mano en el formulario de invitación si algún día hace falta
dárselo a alguien puntual.

**El motivo es el que ya estaba escrito en este documento**: `descripcion` es un juicio en prosa
sobre una persona real de la escuela, y buena parte del padrón son alumnos. Eso no es información de
consulta como los horarios o el stock del pañol. Mientras `personas` era visible con
`historia.leer`, cualquier dispositivo invitado a consultar el inventario leía las semblanzas.

El asistente respeta lo mismo: lee estas tablas, así que esconderlo sólo en la web no serviría de
nada (ver `agent_docs/agente-asistente.md`).

## Búsqueda tolerante (`?q=`)

Idéntica a la de `/gestion` porque es literalmente la misma función (`crud.lista` +
`texto.puntaje_busqueda`): trae todas las filas y las filtra/ordena en Python. Perdona acentos y
mayúsculas (`texto.norm`) y typos (similitud difusa con `difflib`, umbral
`texto.UMBRAL_SIMILITUD` = 0.68, solo para queries de 3+ caracteres).
El substring normalizado siempre puntúa por encima de los difusos. Con decenas de filas el
costo es despreciable.

Las filas emiten `data-buscar` con el texto ya normalizado, el hook del filtrado en vivo de
`static/gestion.js` — pero ese script **no** está incluido en `historia/base.html` hoy, así que
la búsqueda es solo server-side. Si se quiere el filtrado en vivo, alcanza con sumar el
`<script>`.

## Respaldos (`backups/`)

Mismo mecanismo que `gestion.db` porque es el mismo código (`respaldos.py`), con prefijo propio
(`PREFIJO_BACKUP = 'historia'`) para no mezclarse: copias a
`backups/historia-YYYYMMDD-HHMMSS-ffffff.db` con la API `backup()` de sqlite3 (copia
consistente aunque otro proceso esté escribiendo). No respalda una DB sin hitos, no duplica si
el contenido no cambió, y conserva los últimos `BACKUP_MAX` (20) más el primero de cada día.
`crud.init_db()` respalda antes de tocar nada.

## Seed

**No hay datos de ejemplo**: una instalación nueva arranca vacía y se carga desde la web o el
chat. Igual que en `gestion.py`, si la DB está vacía **pero hay respaldos**, `crud.init_db()` levanta
`RuntimeError` con las instrucciones de restauración en vez de seguir — una DB vacía con
respaldos es una pérdida de archivo, no una instalación nueva. Para forzarlo: `GESTION_SEED=1`.

## Qué ve el agente

`hitos` y `personas` entran en `agente.SLUGS_ENTIDAD` (que se deriva de las `ENTIDADES` de los
dos módulos) y se resuelven con `_modulo(slug)`. El agente puede buscarlas, listarlas, verlas en
detalle, crearlas con ficha de confirmación, editarlas, vincularlas y borrarlas — y tiene una
tool de lectura propia para la línea del tiempo, `buscar_hitos(etiqueta, desde_fecha,
hasta_fecha)`. Al confirmar un alta de hito, el servidor cruza `protagonistas` contra `personas`
y crea los vínculos solo. Ver `agent_docs/agente-asistente.md`.
