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

- **`historia.py`** — todo el módulo: blueprint Flask (`bp`, prefix `/historia`), schema, y
  rutas. Server-rendered con Jinja, mismo patrón que `gestion.py`.
- **`historia.db`** — SQLite propia. No se regenera desde ninguna fuente externa y está en
  `.gitignore`: si se pierde el archivo no hay commit del cual recuperarla, por eso
  `init_db()` arranca respaldando (ver "Respaldos").
- **`templates/historia/`** — `base.html` (layout + nav propia: INICIO / HITOS / PERSONAS),
  `home.html`, `login.html`, y el trío genérico `lista.html` / `form.html` / `detalle.html`,
  que se renderizan desde la config declarativa de cada entidad.
- **No importa `gestion.py`.** El motor CRUD (conexión, búsqueda tolerante, `_select`,
  `_guardar`, respaldos, rutas genéricas) está **duplicado** en los dos archivos a propósito:
  se puede borrar uno entero sin tocar el otro ni una librería común. El costo aceptado es que
  un fix al motor hay que aplicarlo en los dos lugares. Ver `dev-log/DECISIONS.md` 2026-08-10.
- Sí comparte con `/gestion` lo que **no** es lógica de dominio: `static/gestion.css` (paleta),
  `static/gestion-agente.js` y el widget flotante del asistente
  (`templates/agente/_agente_widget.html`).
- Integración: `app.py` hace `app.register_blueprint(historia.bp)` + `historia.init_db()` en
  import (funciona bajo gunicorn/WSGI). El header linkea a las otras tres áreas.

## Modelo de datos (historia.db)

| Tabla | Campos |
|-------|--------|
| `hitos` | id, **titulo**, descripcion, fecha, tipo, nivel, etiquetas, protagonistas, drive_url, **fotos** |
| `personas` | id, nombre, **nombre_norm**, descripcion, fecha_actualizada, drive_url, **fotos** |
| `persona_hitos` | persona_id, hito_id (`UNIQUE` por par, índice por `persona_id`) |

Índices: `idx_hitos_fecha` (fecha DESC), `idx_hitos_nivel`, `idx_personas_norm` (UNIQUE).

Valores cerrados: `tipo` ∈ Evento / Logro / Carrera nueva / Construcción / Participación /
Programa / Otro. `nivel` ∈ Básico / Importante / Crítico.

**Galería de fotos** (`fotos`): array JSON con objetos `{b64, tipo, fecha}`, igual que en
`/gestion` — base64 embebido, upload por `POST /<slug>/<id>/foto`, grid responsive en el
detalle. `agregar_foto()` vive suelta porque el agente también escribe la galería.

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
`campos`, las agrega `_derivados()` en los dos caminos de guardado (`_guardar` y
`guardar_entidad_sin_request`).

**No hay campo `rol`**: una taxonomía fija se queda corta enseguida — alguien es docente y ex
alumno a la vez, o pasa de preceptor a directivo — y la semblanza ya lo dice mejor en prosa.
Queda como recordatorio que `descripcion` es un juicio sobre una persona real, y que esto vive
detrás de una clave compartida cuyo default está en un repo público: escribir semblanzas de
alumnos menores pide una auth de verdad primero.

## Config declarativa (`ENTIDADES` en historia.py)

Mismo contrato que `gestion.ENTIDADES`: cada entidad define `tabla`, `singular`/`plural`,
`descripcion` (card del home), `campos` (form), `columnas` (listado) y `relaciones` (M2M
editables desde su form, con prefijo `rel_`).

**`campo_nombre`** (opcional, default `'nombre'`): `hitos` la declara como `'titulo'`. Todas
las lecturas van por **`_select(cfg)`**, que agrega `titulo AS nombre`, así que templates,
`buscar_entidad_sin_request`, `snapshot_entidad` y `agente.py` leen siempre `fila['nombre']`.
Las escrituras y la validación de obligatorio usan `_campo_nombre(cfg)`.

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

`slug` ∈ {hitos, personas}; otro valor → 404.

## Auth

Misma env var (`GESTION_CLAVE`) y misma clave de sesión (`session['gestion_ok']`) que
`/gestion` y `/agente`: una contraseña abre las tres áreas. Pero el gate está **duplicado** en
`historia.py`, sin importar el de `gestion.py` — es lo que sostiene la independencia física.
Vale la misma advertencia: es una traba de desarrollo, no seguridad completa (sin usuarios,
sin CSRF, sin límite de intentos), y el default está en un repo público.

## Búsqueda tolerante (`?q=`)

Idéntica a la de `/gestion` (código duplicado): trae todas las filas y las filtra/ordena en
Python con `_puntaje_busqueda()`. Perdona acentos y mayúsculas (`_norm`) y typos (similitud
difusa con `difflib`, umbral `UMBRAL_SIMILITUD` = 0.68, solo para queries de 3+ caracteres).
El substring normalizado siempre puntúa por encima de los difusos. Con decenas de filas el
costo es despreciable.

Las filas emiten `data-buscar` con el texto ya normalizado, el hook del filtrado en vivo de
`static/gestion.js` — pero ese script **no** está incluido en `historia/base.html` hoy, así que
la búsqueda es solo server-side. Si se quiere el filtrado en vivo, alcanza con sumar el
`<script>`.

## Respaldos (`backups/`)

Mismo mecanismo que `gestion.db`, con prefijo propio para no mezclarse: copias a
`backups/historia-YYYYMMDD-HHMMSS-ffffff.db` con la API `backup()` de sqlite3 (copia
consistente aunque otro proceso esté escribiendo). No respalda una DB sin hitos, no duplica si
el contenido no cambió, y conserva los últimos `BACKUP_MAX` (20) más el primero de cada día.
`init_db()` respalda antes de tocar nada.

## Seed

**No hay datos de ejemplo**: una instalación nueva arranca vacía y se carga desde la web o el
chat. Igual que en `gestion.py`, si la DB está vacía **pero hay respaldos**, `init_db()` levanta
`RuntimeError` con las instrucciones de restauración en vez de seguir — una DB vacía con
respaldos es una pérdida de archivo, no una instalación nueva. Para forzarlo: `GESTION_SEED=1`.

## Qué ve el agente

`hitos` y `personas` entran en `agente.SLUGS_ENTIDAD` (que se deriva de las `ENTIDADES` de los
dos módulos) y se resuelven con `_modulo(slug)`. El agente puede buscarlas, listarlas, verlas en
detalle, crearlas con ficha de confirmación, editarlas, vincularlas y borrarlas — y tiene una
tool de lectura propia para la línea del tiempo, `buscar_hitos(etiqueta, desde_fecha,
hasta_fecha)`. Al confirmar un alta de hito, el servidor cruza `protagonistas` contra `personas`
y crea los vínculos solo. Ver `agent_docs/agente-asistente.md`.
