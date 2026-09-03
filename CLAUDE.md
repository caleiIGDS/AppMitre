# CLAUDE.md

## Qué es esta app

**AppMitre** son **cinco áreas** sobre el mismo Flask, para la **Escuela Técnica Emilio Mitre**. Cada una tiene su archivo, su prefijo de URL y (las que tienen datos propios) **su propia DB, sin FK que crucen de una a otra**.

| Área | URL | Archivo | DB | Qué es |
|---|---|---|---|---|
| **Horarios** | `/horarios` | `horarios/` (paquete) | `escuela.db` | Consulta de horarios por curso (1°–7°), profesor, aula y preceptor; dashboard "En Vivo" para kiosco; export a PDF. Se regenera desde Google Sheets. **Sitio aparte**: login propio (`HORARIOS_CLAVE`), config y datos propios, **no pasa por `accesos`**. `/` sólo redirige acá. |
| **Gestión de recursos** | `/gestion` | `gestion.py` | `gestion.db` (registro) + `inventarios/<slug>.db` | **Varios inventarios estancos**: `/gestion` es la lista y `/gestion/<inv>/…` uno abierto. Cada uno tiene su archivo, su clave y su encargado, que adentro reparte los permisos. El admin general los crea, nombra y elimina, y **no ve el contenido**. |
| **Historia institucional** ⏸ | `/historia` | `historia.py` | `historia.db` | **APAGADA** (`historia.ACTIVA = False`): hitos y personas no se montan — sin rutas, sin permisos en el catálogo, sin tools ni una línea de prompt en el agente. La DB queda intacta; se prende poniendo el flag en `True`. |
| **Asistente** | `/agente` | `agente/` (paquete) | `agente.db` (+ las de arriba) | Chat con tool-calling. Único transversal: **lee las áreas prendidas** y escribe en recursos. `agente.db` es sólo el registro de uso y de chats (`/agente/uso`). |
| **Salidas educativas** | `/salidas` | `salidas.py` | `salidas.db` | Legajo digital de una salida (Anexos III–IX, Res. 3871/24): formulario de carga, guardado con vigencia de 1 año y generación de PDF por anexo. |

**Quién entra a qué.** El sistema de horarios es un **sitio aparte** con su propia contraseña (`HORARIOS_CLAVE`, ver `horarios/acceso.py`): no usa nada de lo de abajo. El resto (gestión, historia, agente, salidas, accesos) pasa por `accesos.py` — **tres niveles** (detalle en `agent_docs/accesos.md`): **Público** ya casi no ve nada, sólo el canje de invitación y el link de familias de salidas. **Interno** son dispositivos habilitados por un link de invitación de un solo uso, cada uno con su conjunto de permisos (`agente.escribir`, `salidas.leer`, …). **Admin** entra con `GESTION_CLAVE` y tiene el comodín `'*'`. Un área declara sus `PERMISOS` y entra sola al catálogo y a los perfiles: agregar un área nueva **no toca el gate ni migra los accesos ya dados**.

**El comodín tiene un límite, y es a propósito.** Un permiso puede declararse **con ámbito** (`PERMISOS_AMBITO`): se guarda prefijado (`inv:7/gestion.editar`) y vale sólo adentro de ese compartimento — a esas claves `'*'` **no llega**. Hoy las usa gestión: el admin general administra la lista de inventarios sin poder abrir ninguno, y adentro manda el encargado, que entra con la clave de SU inventario y reparte permisos sólo ahí. Ser encargado de uno no da nada en el de al lado.

### Dónde va cada cosa: tres capas

Las áreas **no duplican código**: comparten un motor. Las dependencias van siempre hacia arriba y **la capa 1 nunca importa un área** — las recibe como argumento.

```
capa 2   gestion.py   historia.py   agente/                            ← nombran tablas reales
capa 1      crud.py + templates/crud/   ·   accesos.py                 ← saben "entidad" y "permiso",
                                                                         no cuáles
capa 0        config.py    texto.py    respaldos.py                    ← no nombran nada del dominio
```

El sistema de horarios (`horarios/`) queda **fuera de este esquema**: es un paquete
autónomo con su propia config, su propio gate y sus propios datos. No importa `crud`,
`accesos` ni el `config.py` global. La dependencia va en un solo sentido: `agente/` importa
`horarios.datos` para leer; horarios no importa nada del resto.

**La pregunta para ubicar cualquier función es una sola: ¿qué nombra?** Si nombra una tabla, un slug o una ruta, es del área y quien la necesite la importa de ahí. Si no nombra nada del dominio, sube. Lo específico de un área entra al motor por **hooks declarados** (`migrar`, `seed`, `derivados`, `secciones_detalle`, …), nunca por un `if slug == '...'` dentro de `crud.py`. Detalle completo en `agent_docs/crud-motor.md`.

También se comparte lo que no es lógica de dominio: `static/global.css` (paleta, reset y escudo del header), `static/gestion.css` (estilos específicos de gestión/historia/agente/salidas), `static/gestion-agente.js`, `static/mobile-nav.js` (menú lateral de celular) y el widget del chat.

**Usuarios principales:** alumnos, docentes, preceptores y administración.  
**Stack:** Flask + SQLite + Vanilla JS (sin frameworks). Sin tests, sin linter, sin build step.

---

## Commands

```bash
pip install -r requirements.txt   # instalar dependencias
python app.py                      # dev en http://localhost:5000
gunicorn app:app                   # producción
# POST /horarios/api/actualizar    # regenerar DB desde Google Sheets

python actualizar.py --dry-run     # deploy: qué le falta a las DB del server (no escribe)
python actualizar.py               # aplicarlo, antes del Reload del web app
```

---

## Arquitectura

```
Google Sheets (CSV export por año: 1ro–7mo + preceptores + personal)
  → horarios/datos.py: descargar_sheet() + cargar_desde_sheets()
  → escuela.db (SQLite: clases | horarios_preceptores | personal_no_docente)
  → horarios/rutas.py: rutas /horarios/api/* y /horarios/export/*
  → static/js/script.js: calendario, dashboard, PDF, comparación
```

**Archivos clave:**

| Archivo | Rol |
|---------|-----|
| `config.py` | Branding, `ahora()` (el reloj de la escuela), `PRODUCCION`, `SESION_DIAS` (capa 0). Compartido por gestión/historia/agente/salidas/accesos. **No lo usa horarios** (tiene `horarios/config.py`). Nadie llama a `datetime.now()`: el server de producción corre en UTC |
| `texto.py` | Normalización de texto y búsqueda difusa (capa 0). Único dueño de `UMBRAL_SIMILITUD` |
| `respaldos.py` | Respaldos rotativos de SQLite, parametrizados por área (capa 0) |
| `crud.py` | Motor CRUD genérico + rutas (capa 1). No importa ningún área |
| `accesos.py` | Motor de accesos y permisos (capa 1), hermano de `crud.py`: gate, catálogo de permisos, perfiles, links de invitación y panel `/accesos`. DB propia `accesos.db`. No nombra ningún permiso de área. **Horarios no pasa por acá** |
| `actualizar.py` | Script de consola para el deploy: pone al día una `gestion.db`/`historia.db` vieja. Hace lo que `migrar()` no puede porque cruza las dos DBs (mudanza de hitos/personas, `proyectos` → hitos) y limpia tablas y columnas que el código ya no declara. Idempotente, con `--dry-run`. No toca `escuela.db` |
| `app.py` | Bootstrap Flask: crea la app, `SECRET_KEY`, config de sesión, registra los blueprints de las áreas, `/` → redirect a `/horarios/` |
| `horarios/` | Sistema de horarios (`/horarios`): paquete autónomo. `__init__.py` (blueprint + guards), `config.py` (SHEET_ID, GIDs, FLOOR_MAPPING, branding propio), `acceso.py` (login con `HORARIOS_CLAVE`), `datos.py` (schema `escuela.db`, descarga CSV, normalización), `rutas.py` (SPA + API + PDF). Expone `bp`, `init_db`, `cargar_inicial` |
| `templates/index.html` | Shell SPA — pasa `window.APP_DATA` al JS |
| `static/js/script.js` | Toda la lógica frontend (~1500 líneas) |
| `static/global.css` | Paleta compartida, reset base, escudo (`.marca`), header genérico (capa 0). Lo cargan todas las áreas. Importan este archivo: `gestion.css` y `horarios.css` |
| `static/gestion.css` | Estilos específicos de gestión/historia/agente/salidas (tablas, fichas, widget del agente, galería, etc). Importa `global.css` |
| `static/horarios.css` | Estilos específicos del sistema de horarios (calendario, dashboard, tema oscuro, etc). Importa `global.css` |
| `horarios/nombre_mapeos.json` | Correcciones manuales de nombres de docentes (lo lee `horarios/datos.py`; opcional — si no está, no se aplica ningún mapeo) |
| `gestion.py` | Gestión de recursos: el registro de inventarios (`bp_inv`, `/gestion`) y un inventario abierto (`bp`, `/gestion/<inv>`), sus entidades y hooks (incluidos `db_path`/`prefijo_backup`, que resuelven el archivo por request) + el desglose de recursos por ubicación |
| `historia.py` | Historia institucional (`/historia`): declara sus entidades y hooks (`derivados`, `clave_persona`) |
| `agente/` | Asistente conversacional (`/agente`): paquete con blueprint, tools, prompt y loop + templates en `templates/agente/`. Expone `bp` e `init_db`; el mapa de los módulos está en `agente/__init__.py` |
| `templates/crud/` | `lista/form/detalle/login.html` genéricos; cada área deja un stub que los extiende |
| `static/mobile-nav.js` | Menú lateral ocultable de celular para `/gestion`, `/historia` y `/agente` (≤900px). No toca escritorio |

---

## API routes (horarios/rutas.py)

Todas cuelgan del blueprint `horarios` (en `horarios/__init__.py`) con prefijo **`/horarios`**
y detrás del gate propio del área (`horarios/acceso.py`: sesión con `HORARIOS_CLAVE`, sin
relación con `accesos`). El `fetch`/`window.open` del front usa `API_BASE = '/horarios'`.
`/` (a nivel app) sólo redirige a `/horarios/`.

| Ruta | Método | Descripción |
|------|--------|-------------|
| `/horarios/` | GET | Sirve el SPA; pasa `datos`, `floor_mapping`, `dias`, branding |
| `/horarios/api/<tipo>/<valor>` | GET | Horario por `tipo` = `profesor\|aula\|curso\|planilla` |
| `/horarios/api/preceptor/<valor>` | GET | Preceptor asignado a un curso (T.M / T.T / T.N) |
| `/horarios/api/horario_preceptor/<nombre>` | GET | Horario personal de un preceptor |
| `/horarios/api/personal/<nombre>` | GET | Horario de personal no docente |
| `/horarios/api/dashboard` | GET | Todas las clases (el JS filtra por hora actual) |
| `/horarios/api/actualizar` | POST | Borra y reconstruye `escuela.db` desde Sheets |
| `/horarios/export/pdf/<tipo>/<valor>` | GET | Genera y devuelve PDF (landscape A4, fpdf2) |
| `/horarios/export/pdf/cursos/<seleccion>` | GET | PDF multipágina de cursos: `todos` o lista `1° A,2° B` |

**Lógica de búsqueda en `/api/<tipo>/<valor>`:**
- `profesor` → `WHERE profesor = ?`
- `aula` → `WHERE aula = ?`
- `curso` → parsea "1° A" → `WHERE curso='1' AND division='A'`
- `planilla` → parsea "Lunes|Piso 1" → `WHERE dia=? AND aula IN (rooms del floor)`

---

## Base de datos (horarios/datos.py)

### Tabla `clases` (columnas clave)

| Columna | Tipo | Notas |
|---------|------|-------|
| `curso` | TEXT | "1"–"7" |
| `division` | TEXT | "A", "B", "C"... |
| `materia` | TEXT | Nombre de materia (normalizado) |
| `profesor` | TEXT | Nombre limpio vía `limpiar_profesor()` |
| `aula` | TEXT | Número o código limpio vía `limpiar_aula()` |
| `dia` | TEXT | "Lunes"–"Viernes" |
| `hora_inicio` / `hora_fin` | TEXT | "HH:MM" |
| `grupo` | TEXT | "A"/"B" para divisiones paralelas, o vacío |
| `superposicion` | INT | 1 = solapamiento permitido; 0 = conflicto real |
| `suplente_activo` | INT | 1 = docente en licencia, usar suplente |
| `prof_suplente` | TEXT | Nombre del suplente |

### Tabla `horarios_preceptores`
Turno, preceptor, tipo, curso, division, dia. Usada para asignar preceptores a cursos y mostrar su horario personal.

### Tabla `personal_no_docente`
Nombre, rol, dia, hora_inicio, hora_fin. Para porteros, secretarias, etc.

---

## Normalización de datos (horarios/datos.py)

**`limpiar_profesor(nombre)`**
1. Quita acentos (NFD decomposition)
2. Mayúsculas, elimina comas/puntos, normaliza espacios
3. Aplica mapeos manuales de `nombre_mapeos.json`

**`limpiar_aula(aula)`**
- `"P"` → `"PATIO"`
- `"Taller 2"` / `"T 2"` → `"T2"`
- `"Aula 101"` → `"101"`
- Sin número → devuelve nombre en mayúsculas (ej: `"GYM"`)

**`corregir_horarios()`**
Completa `hora_fin` faltante buscando el patrón horario conocido más cercano; si no encuentra, suma 2h al inicio.

**`superposicion`**
- `1`: solapamiento intencional (ej: mismo aula, grupos A/B distintos) → renderizar lado a lado
- `0`: conflicto real → bloque gris de advertencia en el calendario

---

## Frontend (script.js)

### Calendario (`generarCalendario`)
- Grid CSS: columna de horas (60px) + 5 columnas de días
- Bloques con `position: absolute`, top/height calculados desde minutos
- Clustering: agrupa bloques solapados, divide ancho según grupos y `superposicion`
- Click → modal con detalle de clase + links para navegar al docente/aula

### Modo Comparación (`generarCalendarioComparacion`)
- Agrega hasta 6 entidades al grid (docentes, aulas o cursos)
- Cada una recibe un color distinto de `COMPARACION_COLORS`
- Grid se expande: `60px + (días × entidades × 200px)`

### Dashboard En Vivo (`renderizarDashboard`)
- Filtra `clases` por día actual y hora
- Columna izquierda: "En Curso" (inicio ≤ ahora ≤ fin)
- Columna derecha: "Próximas" (inicio dentro de 2h)
- Refresca cada 1 segundo; soporta modo manual con date/time pickers
- F11 activa modo kiosco (CSS class `is-fullscreen` en `body`, oculta header/footer)

### Planilla General
- Activa desde tab AULAS → panel lateral → "PLANILLA GENERAL"
- Grid: horas en filas, aulas del piso seleccionado en columnas
- Tipo de búsqueda `planilla` en el backend

### Autocompletado
- `filtrarOpciones()`: normaliza query (sin acentos, sin espacios), substring match
- En modo "profesor" fusiona docentes + personal no docente con badge de rol

---

## PDF (horarios/rutas.py + fpdf2)

- Landscape A4, fuente Roboto Mono embedded
- Encabezado: nombre de búsqueda + info de preceptor (si es curso)
- Grid con horas a la izquierda y días (o aulas) como columnas
- Texto se trunca con ellipsis cuando no entra; prueba substrings más cortos
- Responde con MIME `application/pdf`; el browser lo abre en nueva pestaña

---

## Config

- **`config.py`** (raíz): sólo lo compartido por gestión/historia/agente/salidas/accesos —
  branding (`ESCUELA_NOMBRE/LOGO/VERSION`), `DIAS`, `ahora()`, `PRODUCCION`, `SESION_DIAS`.
- **`horarios/config.py`**: todo lo del sistema de horarios — `SHEET_ID`, `GIDS`,
  `FLOOR_MAPPING`, `TURNO_CURSOS`, `TURNO_DEFAULT`, `ESPECIALIDAD_CURSOS`, `APPSCRIPT_URL/SECRET`,
  + su copia propia de branding/`DIAS`/`ahora()`/`PRODUCCION` (no importa la global a propósito).

```python
# horarios/config.py
SHEET_ID = "1GJxwpxXfLosqKxgIa6zyZhwjDK-89ZDavLi6nouWTsw"
GIDS = { "1ro": "...", ..., "7mo": "...", "horarios_preceptores": "...", "personal_no_docente": "..." }
FLOOR_MAPPING = { "Piso 1": ["11","12",...], "Talleres": ["T1","T2",...], ... }
```

Para cambiar la fuente de datos, editar `SHEET_ID` y/o los `GIDS` en `horarios/config.py`. No hay `.env`.

---

## Tema CSS

Variables principales:
- `--primary: #1A365D` (azul marino — headers, bordes)
- `--secondary: #FF6B00` (naranja — acento, estado activo)
- `--alert: #DC2626` (rojo — conflictos, suplentes)

Fondo blueprint: `repeating-linear-gradient` de 20px de grilla.  
Font: Roboto Mono (archivos locales en `static/fonts/`).  
Tabs con `clip-path: polygon(...)` para bordes angulados.

---

## Deployment

- **Hosting:** PythonAnywhere (WSGI) + Cloudflare DNS. Antes fue Render.com — ver `dev-log/DECISIONS.md` 2026-06-25
- **Los `.db` persisten entre deploys** y están en `.gitignore`: `git pull` nunca los pisa. `horarios/escuela.db` es la excepción que no importa (se regenera desde Sheets al iniciar o via `/horarios/api/actualizar`); `gestion.db`, `historia.db`, `accesos.db` y `salidas.db` viven en la raíz, y los inventarios en `inventarios/<slug>.db` (uno por inventario, con prefijo de respaldo `inv<id>`); son la fuente de verdad y sólo tienen los respaldos de `respaldos.py`; `agente.db` (registro de uso del asistente) también vive en la raíz pero **no** tiene respaldo rotativo a propósito — es telemetría, ver `dev-log/DECISIONS.md`. `salidas_pdfs/` (también en `.gitignore`, contiene DNI y datos de salud) no tiene respaldo propio: se regenera solo la próxima vez que se guarda esa salida, y se purga junto con su fila al año. `agente.md` (las notas del asistente, ver `agent_docs/agente-asistente.md`) también está en `.gitignore` y por la misma razón que los `.db`: lo escriben la app y el agente, así que un archivo versionado se pisaría en cada `git pull`
- **Deploy:** `git pull` → `pip install -r requirements.txt` → `python actualizar.py --dry-run` → `python actualizar.py` → Reload del web app. Las variables de entorno (`SECRET_KEY`, `GESTION_CLAVE`, `HORARIOS_CLAVE`, `SHEETS_PROXY_URL`, `SHEETS_PROXY_SECRET`, las API keys del agente) van en el `.env` del servidor, que tampoco viaja por git
- **`SECRET_KEY`, `GESTION_CLAVE` y `HORARIOS_CLAVE` son obligatorias en producción**: sin ellas la app no arranca (se exigen cuando detectan `PYTHONANYWHERE_DOMAIN`). En local caen a un default de desarrollo con un aviso por consola. `HORARIOS_CLAVE` es la contraseña del sistema de horarios (`/horarios`), independiente de `GESTION_CLAVE`. Lo mismo `SHEETS_PROXY_URL` y `SHEETS_PROXY_SECRET`: el Drive de horarios es privado y sólo se lee vía el Web App de Apps Script (`apps_script/`), firmando cada request con HMAC sobre el timestamp; sin ellas no arranca en producción y en local `descargar_sheet()` lanza `RuntimeError`. Ojo: **cambiar `GESTION_CLAVE` cierra todas las sesiones de admin** (es el botón de pánico) y **rotar `SECRET_KEY` desloguea también a todos los dispositivos**, que hay que volver a invitar
- **La primera vez, `accesos.db` nace vacía**: no hay ningún dispositivo habilitado y el único acceso es el de administración con `GESTION_CLAVE`. Desde `/accesos` se invita al resto. La crea sola `accesos.init_db()`, tanto al arrancar como desde `actualizar.py`
- `gunicorn app:app` para producción en hostings que no sean PythonAnywhere
- Ver `PLAN_ESCUELAS.md` y `AGENTE_CONFIG.md` para más detalles

---

## Flujos principales

1. **Consultar horario de curso:** Tab CURSOS → "1° A" → calendario semanal → click en bloque → modal con detalles
2. **Planilla de piso:** Tab AULAS → panel lateral → Planilla General → elegir piso + día → grid de aulas
3. **Actualizar datos:** Botón "ACTUALIZAR HORARIOS" → POST `/horarios/api/actualizar` → recarga página
4. **Comparar docentes:** Buscar docente → panel lateral → COMPARAR → buscar otro → grid multicolor
5. **Kiosco tiempo real:** Tab TIEMPO REAL → F11 → dashboard auto-actualizado cada 1s

---

## Context Rules

- Formato/contrato del Google Sheet (encabezados, layout de preceptores, plantilla para otras escuelas) → leer `PLANTILLA_SHEET.md`
- Sistema de horarios como sitio aparte (`horarios/`: `config.py`, `acceso.py` con `HORARIOS_CLAVE`, `datos.py`, `rutas.py`) → esta sección + `dev-log/DECISIONS.md` (buscar "horarios")
- Lógica de normalización / pipeline de datos → leer `agent_docs/data-pipeline.md`
- Renderizado del calendario, clustering, superposición → leer `agent_docs/calendar-engine.md`
- Sistema de búsqueda y parsing de queries → leer `agent_docs/search-api.md`
- Estilos, variables CSS, patrones visuales → leer `agent_docs/frontend-ui.md`
- Motor CRUD compartido, criterio de capas, contrato de área, hooks, templates genéricos (`crud.py`, `texto.py`, `respaldos.py`, `templates/crud/`) → leer `agent_docs/crud-motor.md`
- Quién puede entrar a qué: los tres niveles (público/interno/admin), permisos por área, **permisos con ámbito** (el comodín que no llega), links de invitación y dispositivos (`accesos.py`, `accesos.db`, `/accesos`) → leer `agent_docs/accesos.md`
- Gestión de recursos: varios inventarios estancos, uno por archivo (`/gestion`, `gestion.py`, `gestion.db` + `inventarios/<slug>.db`) → leer `agent_docs/gestion-conocimiento.md`
- Historia institucional (`/historia`, `historia.py`, `historia.db`: hitos y personas) — **área apagada**, ver `historia.ACTIVA` → leer `agent_docs/historia-institucional.md`
- Salidas educativas (`/salidas`, `salidas.py`, `salidas.db`, `salidas_pdfs/`, generación de PDF por anexo, vigencia y purga) → leer `agent_docs/salidas-educativas.md`
- Asistente conversacional (`/agente`, paquete `agente/`, tools, fichas de confirmación, fotos) → leer `agent_docs/agente-asistente.md`
- Historias narradas por Emilio (`historias/*.json`, lore — NO confundir con `/historia`): cómo agregar, campos, tonos y estilos → leer `HISTORIAS_PROCEDIMIENTO.md`

## Dev Log

- `dev-log/DECISIONS.md` — por qué algo está hecho así. Antes de "corregir" algo que parece raro, buscarlo acá **con Grep** por el archivo o el símbolo. Son 1600 líneas: nunca leerlo entero.
- `dev-log/CHANGELOG.md` — cambios que afectan contratos entre módulos. Mismo criterio: Grep, no lectura completa.
- `dev-log/tasks/IN-PROGRESS.md` — leer al iniciar cualquier sesión.
- `dev-log/tasks/TODO.md` — backlog priorizado.
- `dev-log/tasks/DONE.md` — solo leer si se pide explícitamente.

**Agregar tarea:** Si el usuario pide agregar una tarea al backlog, editar directamente `dev-log/tasks/TODO.md` — leerlo, agregar la entrada con el siguiente número (#N+1), y actualizar la última línea `_Último número usado_`. Sin exploración previa, sin skills.

## Docs Maintenance

Anotar **cuesta**: lo que se escribe acá se lee (y se paga) en todas las sesiones que vienen. Por eso el default es **no anotar nada**, y lo que se anota va a **un solo archivo**, corto, antes de terminar y antes de commitear.

**Dónde va — una pregunta, un solo destino:**

| Qué pasó | Dónde | Cuánto |
|---|---|---|
| El código quedó distinto de lo que **afirma** un `agent_docs/*.md` (el mapa de cuál es cuál está en **Context Rules**) | ese `.md` | corregir la línea que quedó falsa: Grep al párrafo → Edit. **Reemplazar, no agregar sección nueva** |
| Cambió un contrato que otro módulo consume: ruta, schema, nombre de campo, hook, forma de `window.APP_DATA` | `dev-log/CHANGELOG.md` | **≤4 líneas**: qué cambió, archivos, qué se rompe si no te enterás |
| Alguien sin el contexto lo revertiría porque parece un error | `dev-log/DECISIONS.md` | **≤6 líneas**: la decisión, por qué, y la alternativa descartada si la hubo |
| Cualquier otra cosa | ningún lado | — |

**Un cambio va a un archivo, no a los tres.** Si ya quedó explicado en `agent_docs/`, el CHANGELOG lo menciona en una línea o directamente no existe. Nunca repetir el mismo relato en dos lugares.

**No se anota**: fixes de estilo, bugs internos, ajustes de UI, renombres, nada que se lea del código o del `git log`, ni cómo se llegó a la solución.

**Cómo escribir**: prosa directa, sin plantilla de secciones (`**Contexto**` / `**Decisión 1**` / `**Consecuencia**`), sin narrar en palabras el código que está al lado. Si una decisión no entra en 6 líneas, va corta y el detalle técnico al `agent_docs/` del área. Los `agent_docs/` describen **cómo funciona hoy**, no cómo se fue haciendo.

Dos reglas que no son de doc pero viven acá: **¿código compartido entre áreas?** → pasarlo por el filtro de capas de `agent_docs/crud-motor.md` (si nombra una tabla o un slug, no es compartido). **¿Creaste, moviste o borraste un `.md`?** → actualizar su referencia en `CLAUDE.md`.

## Fin de sesión

Si el usuario pide "terminar/cerrar la sesión", con lo que ya está en contexto — sin re-leer archivos ni repasar el diff entero:
1. Pasar la tabla de **Docs Maintenance** sobre lo hecho. Si nada cae en las tres primeras filas, no se escribe nada y se avisa.
2. Mover lo terminado a `dev-log/tasks/DONE.md` (newest-first): **una línea por tarea**.
3. Pendientes nuevos → `TODO.md` (numerados, actualizar `_Último número usado_`).
4. Algo a medias → `IN-PROGRESS.md` con estado y próximo paso; si no, verificar que quede vacío.
5. No commitear salvo pedido explícito.