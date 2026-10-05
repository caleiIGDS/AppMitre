# CLAUDE.md

## Qué es esta app

**AppMitre** son **cuatro áreas** sobre el mismo Flask, para la **Escuela Técnica Emilio Mitre**. Cada una tiene su archivo, su prefijo de URL y (las que tienen datos propios) **su propia DB, sin FK que crucen de una a otra**.

| Área | URL | Archivo | DB | Qué es |
|---|---|---|---|---|
| **Horarios** | `/horarios` | `horarios/` (paquete) | `database/escuela.db` | Consulta de horarios por curso (1°–7°), profesor, aula y preceptor; dashboard "En Vivo" para kiosco; export a PDF. Se regenera desde Google Sheets. **Sitio aparte**: login propio (`HORARIOS_CLAVE`), config y datos propios, **no pasa por `accesos`**. `/` sólo redirige acá. |
| **Gestión de recursos** | `/gestion` | `gestion.py` | `gestion.db` (registro) + `inventarios/<slug>.db` | **Varios inventarios estancos**: `/gestion` es la lista y `/gestion/<inv>/…` uno abierto. Cada uno tiene su archivo, su clave y su encargado, que adentro reparte los permisos. El admin general (`GESTION_CLAVE`) los crea, nombra y elimina, **entra a todos y ve sus claves**. |
| **Asistente** | `/agente` | `agente/` (paquete) | `agente.db` (+ las de arriba) | Chat con tool-calling. Único transversal: **lee horarios** y escribe en recursos. `agente.db` es sólo el registro de uso y de chats (`/agente/uso`). |
| **Salidas educativas** | `/salidas` | `salidas.py` | `salidas.db` | Legajo digital de una salida (Anexos III–IX, Res. 3871/24): formulario de carga, guardado con vigencia de 1 año y generación de PDF por anexo. |

> Hasta 2026-09 hubo una quinta área, **Historia institucional** (`/historia`, hitos y
> personas) más un lore de la escuela narrado por un personaje dentro del agente. Se
> extrajeron del código — ver `dev-log/DECISIONS.md` — y el material archivado queda fuera
> del repo, con una guía para reimplementarlos si hiciera falta.

**Quién entra a qué.** El sistema de horarios es un **sitio aparte** con su propia contraseña (`HORARIOS_CLAVE`, ver `horarios/acceso.py`): no usa nada de lo de abajo. El resto (gestión, agente, salidas, accesos) pasa por `accesos.py` — **tres niveles** (detalle en `agent_docs/accesos.md`): **Público** ya casi no ve nada, sólo el canje de invitación y el link de familias de salidas. **Interno** son dispositivos habilitados por un link de invitación de un solo uso, cada uno con su conjunto de permisos (`agente.escribir`, `salidas.leer`, …). **Admin** entra con `GESTION_CLAVE` y tiene el comodín `'*'`. Aparte, **`SALIDAS_CLAVE`** (opcional, en el `.env`) da todo Salidas y nada más, en `/salidas/login` o en el login de la app. Un área declara sus `PERMISOS` y entra sola al catálogo y a los perfiles: agregar un área nueva **no toca el gate ni migra los accesos ya dados**.

**El comodín tiene un límite, y es a propósito.** Un permiso puede declararse **con ámbito** (`PERMISOS_AMBITO`): se guarda prefijado (`inv:7/gestion.editar`) y vale sólo adentro de ese compartimento — a esas claves `'*'` **no llega**. Hoy las usa gestión: un dispositivo con perfil admin no abre ningún inventario (la sesión de `GESTION_CLAVE` sí, por `gestion._acceso_encargado`), y adentro manda el encargado, que entra con la clave de SU inventario y reparte permisos sólo ahí. Ser encargado de uno no da nada en el de al lado.

### Dónde va cada cosa: tres capas

Las áreas **no duplican código**: comparten un motor. Las dependencias van siempre hacia arriba y **la capa 1 nunca importa un área** — las recibe como argumento.

```
capa 2   gestion.py   agente/                                          ← nombran tablas reales
capa 1      crud.py + templates/crud/   ·   accesos.py                 ← saben "entidad" y "permiso",
                                                                         no cuáles
capa 0        config.py    texto.py    respaldos.py    fotos_disco.py  ← no nombran nada del dominio
```

El sistema de horarios (`horarios/`) queda **fuera de este esquema**: es un paquete
autónomo con su propia config, su propio gate y sus propios datos. No importa `crud`,
`accesos` ni el `config.py` global. La dependencia va en un solo sentido: `agente/` importa
`horarios.datos` para leer; horarios no importa nada del resto.

**La pregunta para ubicar cualquier función es una sola: ¿qué nombra?** Si nombra una tabla, un slug o una ruta, es del área y quien la necesite la importa de ahí. Si no nombra nada del dominio, sube. Lo específico de un área entra al motor por **hooks declarados** (`migrar`, `seed`, `derivados`, `secciones_detalle`, …), nunca por un `if slug == '...'` dentro de `crud.py`. Detalle completo en `agent_docs/crud-motor.md`.

También se comparte lo que no es lógica de dominio: `static/global.css` (paleta, reset y escudo del header), `static/gestion.css` (estilos específicos de gestión/agente/salidas), `static/img-utils.js` (compresión de imágenes client-side, la usan el chat y la galería de fotos), `static/gestion-agente.js`, `static/mobile-nav.js` (menú lateral de celular) y el widget del chat.

**Usuarios principales:** alumnos, docentes, preceptores y administración.  
**Stack:** Flask + SQLite. Gestión y Horarios son **apps instalables** (Vue 3 + Vite + PWA, carpeta `frontend/`) que le piden al servidor sólo datos: Gestión en `/gestion/` (API en `/app/api/`), Horarios en `/horarios/` (API en `/app-horarios/api/`). Las APIs conservan el prefijo viejo a propósito; las direcciones `/app/...` y `/app-horarios/...` redirigen a las nuevas. Agente, salidas y `/accesos` siguen siendo páginas Jinja sin build. Los compilados (`app_dist/`, `app_horarios_dist/`) se commitean. Sin tests, sin linter.

---

## Commands

```bash
pip install -r requirements.txt   # instalar dependencias
python app.py                      # dev en http://localhost:5000
gunicorn app:app                   # producción
# POST /app-horarios/api/actualizar # regenerar DB desde Google Sheets

python actualizar.py --dry-run     # deploy: qué le falta a las DB del server (no escribe)
python actualizar.py               # aplicarlo, antes del Reload del web app

cd frontend && npm install         # apps instalables: una vez
npm run dev                        # dev en http://localhost:5173/gestion/ (con Flask en :5000)
npm run build                      # compila a app_dist/ — correrlo y commitearlo antes de subir
npm run build:horarios             # la app de horarios: compila a app_horarios_dist/ (ídem)
```

---

## Arquitectura

```
Google Sheets (CSV export por año: 1ro–7mo + preceptores + personal)
  → horarios/datos.py: descargar_sheet() + cargar_desde_sheets()
  → escuela.db (SQLite: clases | horarios_preceptores | personal_no_docente)
  → horarios/app_api.py: /app-horarios/api/* (datos, sesión, actualizar)
  → horarios/rutas.py: /horarios/export/* (PDF)
  → frontend/horarios/: la app (calendario, dashboard, comparación)
```

**Archivos clave:**

| Archivo | Rol |
|---------|-----|
| `config.py` | Branding, `ahora()` (el reloj de la escuela), `PRODUCCION`, `SESION_DIAS` (capa 0). Compartido por gestión/agente/salidas/accesos. **No lo usa horarios** (tiene `horarios/config.py`). Nadie llama a `datetime.now()`: el server de producción corre en UTC |
| `texto.py` | Normalización de texto y búsqueda difusa (capa 0). Único dueño de `UMBRAL_SIMILITUD` |
| `respaldos.py` | Respaldos rotativos de SQLite, parametrizados por área (capa 0) |
| `fotos_disco.py` | Archivo en disco de cada foto de entidad (`database/fotos/<uuid><ext>`), capa 0: no nombra ninguna tabla, sólo guarda/sirve/borra por uuid. No entra en la rotación de `respaldos.py` (son inmutables) |
| `crud.py` | Motor CRUD genérico + su API JSON (`registrar_api`, capa 1). No importa ningún área |
| `accesos.py` | Motor de accesos y permisos (capa 1), hermano de `crud.py`: gate, catálogo de permisos, perfiles, links de invitación y panel `/accesos`. DB propia `accesos.db`. No nombra ningún permiso de área. **Horarios no pasa por acá** |
| `actualizar.py` | Script de consola para el deploy: pone al día una `gestion.db` vieja. Hace lo que `migrar()` no puede porque cruza DBs (permisos `gestion.*` al pasar a varios inventarios) y limpia tablas y columnas que el código ya no declara. Idempotente, con `--dry-run`. No toca `escuela.db` |
| `app.py` | Bootstrap Flask: crea la app, `SECRET_KEY`, config de sesión, registra los blueprints de las áreas, sirve las dos apps compiladas (`/gestion/`, `/horarios/`), redirige las direcciones viejas `/app/...` y `/app-horarios/...` (con un service worker que se da de baja solo en `/app/sw.js` y `/app-horarios/sw.js`), `/` → `/horarios/` |
| `horarios/` | Sistema de horarios (`/horarios`): paquete autónomo. `__init__.py` (blueprint + guards), `config.py` (SHEET_ID, GIDs, FLOOR_MAPPING, branding propio), `acceso.py` (sesión con `HORARIOS_CLAVE`), `datos.py` (schema `escuela.db`, descarga CSV, normalización), `app_api.py` (la API de la app: datos, entrar/salir, actualizar), `rutas.py` (sólo los PDF). Expone `bp`, `bp_app`, `init_db`, `cargar_inicial`. Su DB es lo único que no vive adentro del paquete: está en `database/`, como todas |
| `static/global.css` | Paleta compartida, reset base, escudo (`.marca`), header genérico y el `@font-face` de Roboto Mono auto-hospedada (capa 0). Va como `<link>` propio en cada plantilla, **antes** de `gestion.css`/`horarios.css` |
| `static/gestion.css` | Estilos específicos de gestión/agente/salidas (tablas, fichas, widget del agente, galería, etc). No importa `global.css`: la plantilla carga las dos hojas en paralelo |
| `static/horarios.css` | Estilos del sistema de horarios (calendario, dashboard, tema oscuro, etc). Hoy lo importa la app de horarios (`frontend/horarios/src/main.js`) |
| `horarios/nombre_mapeos.json` | Correcciones manuales de nombres de docentes (lo lee `horarios/datos.py`; opcional — si no está, no se aplica ningún mapeo) |
| `gestion.py` | Gestión de recursos: la API del registro de inventarios (`bp_api_registro`, `/app/api/gestion/inventarios`) y la de un inventario abierto (`bp_api`, `/app/api/gestion/<inv>/…`, incluido su "quién entra"), sus entidades y hooks (incluidos `db_path`/`prefijo_backup`, que resuelven el archivo por request) + el desglose de recursos por ubicación |
| `agente/` | Asistente conversacional (`/agente`): paquete con blueprint, tools, prompt y loop + templates en `templates/agente/`. Expone `bp` e `init_db`; el mapa de los módulos está en `agente/__init__.py` |
| `templates/crud/` | `login.html` y `403.html` genéricos, los usa el gate de `accesos` para agente/salidas/`/accesos` |
| `static/mobile-nav.js` | Menú lateral ocultable de celular para las páginas Jinja (agente, salidas, accesos). No toca escritorio |
| `frontend/` | Las apps instalables: Vue 3 + Vite + PWA. Gestión (`/gestion/`): fuente en `frontend/src/`, compila a `app_dist/`. Horarios (`/horarios/`): fuente en `frontend/horarios/`, compila a `app_horarios_dist/`. Los dos compilados se commitean y los sirve `app.py` |

---

## Rutas de horarios

La app vive en `/horarios/` (la sirve `app.py` desde `app_horarios_dist/`). Los datos los da
`horarios/app_api.py` (`/app-horarios/api`) y los PDF `horarios/rutas.py` (`/horarios/export`).
Las dos van detrás del gate propio del área (`horarios/acceso.py`: sesión con
`HORARIOS_CLAVE`, sin relación con `accesos`; sin sesión, 401). `/` sólo redirige a `/horarios/`.

| Ruta | Método | Descripción |
|------|--------|-------------|
| `/app-horarios/api/sesion` | GET | Si hay sesión de horarios |
| `/app-horarios/api/entrar` · `/salir` | POST | Entrar con `HORARIOS_CLAVE` / salir |
| `/app-horarios/api/datos` | GET | El horario entero (clases, preceptores, personal); con ETag |
| `/app-horarios/api/actualizar` | POST | Borra y reconstruye `escuela.db` desde Sheets |
| `/horarios/export/pdf/<tipo>/<valor>` | GET | Genera y devuelve PDF (landscape A4, fpdf2) |
| `/horarios/export/pdf/cursos/<seleccion>` | GET | PDF multipágina de cursos: `todos` o lista `1° A,2° B` |
| `/horarios/export/pdf/planilla_preceptores` | GET | PDF de la planilla de preceptores |

Las búsquedas (por profesor, aula, curso, preceptor) se hacen en el navegador sobre `/datos`.

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

## Frontend de horarios (`frontend/horarios/src/`)

Todo el horario baja de una vez (`datos.js` → `useHorarios()`, con vue-query y caché en el
dispositivo) y las búsquedas se resuelven en el navegador (`clasesDe`, `clasesDePiso`,
`horarioPreceptor`, `opcionesBuscador`).

### Calendario (`componentes/Calendario.vue` + `calendario.js`)
- Grid CSS: columna de horas + 5 columnas de días (o aulas, en la planilla general)
- Bloques con `position: absolute`, top/height calculados desde minutos (`aMinutos`, `rango`)
- Clustering: `bloquesColumna` agrupa bloques solapados y divide el ancho según grupos y `superposicion`
- Click → `Ventana.vue` con el detalle de la clase + links para navegar al docente/aula

### Modo Comparación (`componentes/CalendarioComparacion.vue`)
- Hasta 6 entidades en el mismo grid (docentes, aulas o cursos), un color de `COLORES_COMPARACION` cada una
- Va en la URL: `?comparar=modo:valor,…`

### Dashboard En Vivo (`vistas/TiempoReal.vue`)
- "En Curso" (inicio ≤ ahora ≤ fin) y "Próximas" (inicio dentro de 2h); modo manual con date/time pickers
- F11 activa modo kiosco (clase `is-fullscreen` en `body`, en `main.js`)

### Planilla General
- Tab AULAS → "PLANILLA GENERAL": horas en filas, aulas del piso en columnas (`Calendario.vue` con `variante: 'planilla'`)

### Autocompletado (`componentes/Buscador.vue`)
- `opcionesBuscador()`: normaliza (sin acentos ni espacios) y busca por substring
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

- **`config.py`** (raíz): sólo lo compartido por gestión/agente/salidas/accesos —
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
- **Producción está en uso, esta máquina no.** Lo que corre en PythonAnywhere es la instalación real de la escuela: datos vivos y gente usándola. El ciclo es siempre el mismo — se codea acá, se prueba en `localhost:5000`, se pushea, y en PythonAnywhere `git pull` + Reload. **Lo único que viaja es código**: las `.db` de `database/` acá son de desarrollo (`inventarios/general.db`, `prueba.db`) y los inventarios de verdad, más cargados y más al día, están sólo allá. Nunca subir una `.db` local, y nunca sacar conclusiones sobre producción contando filas en una base de acá: lo que tenga que cambiar datos del server llega por `migrar()` o por `actualizar.py`, no por el repo
- **Todas las bases viven en `database/`** (`gestion.db`, `accesos.db`, `salidas.db`, `agente.db`, `escuela.db`, más `inventarios/<slug>.db` y la rotación de `backups/`). Qué guarda cada una y qué pasa si se pierde: `database/LEEME.md`, que es lo único de esa carpeta que va a git. **Persisten entre deploys** y están en `.gitignore`: `git pull` nunca las pisa. Son la fuente de verdad y sólo tienen los respaldos de `respaldos.py`, con dos excepciones a propósito: `escuela.db` se regenera desde Sheets y `agente.db` es telemetría que crece sin techo (ver `dev-log/DECISIONS.md`). `salidas_pdfs/` (también en `.gitignore`, contiene DNI y datos de salud) no tiene respaldo propio: se regenera solo la próxima vez que se guarda esa salida, y se purga junto con su fila al año. `agente.md` (las notas del asistente, ver `agent_docs/agente-asistente.md`) también está en `.gitignore` y por la misma razón que los `.db`: lo escriben la app y el agente, así que un archivo versionado se pisaría en cada `git pull`
- **Apps instalables:** el server no tiene Node, así que `app_dist/` y `app_horarios_dist/` viajan compilados por git: un cambio en `frontend/` sin `npm run build` / `npm run build:horarios` antes del commit no llega a producción
- **Deploy:** `git pull` → `pip install -r requirements.txt` → `python actualizar.py --dry-run` → `python actualizar.py` → Reload del web app. Las variables de entorno (`SECRET_KEY`, `GESTION_CLAVE`, `HORARIOS_CLAVE`, `SALIDAS_CLAVE` (opcional), `SHEETS_PROXY_URL`, `SHEETS_PROXY_SECRET`, las API keys del agente) van en el `.env` del servidor, que tampoco viaja por git
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
- Apps instalables (`/gestion/` y `/horarios/`, `frontend/`, `app_dist/`, `app_horarios_dist/`): API JSON, versionado por triggers, conflictos, caché, service worker, build y deploy → leer `agent_docs/app-instalable.md`
- Salidas educativas (`/salidas`, `salidas.py`, `salidas.db`, `salidas_pdfs/`, generación de PDF por anexo, vigencia y purga) → leer `agent_docs/salidas-educativas.md`
- Asistente conversacional (`/agente`, paquete `agente/`, tools, fichas de confirmación, fotos) → leer `agent_docs/agente-asistente.md`
- Qué guarda cada `.db`, qué se regenera y qué no, y cómo restaurar un respaldo → leer `database/LEEME.md`
- Historia institucional y el lore de Emilio (`/historia`, hitos, personas, `historias/*.json`) — **extraídos del código en 2026-09**, ver `dev-log/DECISIONS.md`

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