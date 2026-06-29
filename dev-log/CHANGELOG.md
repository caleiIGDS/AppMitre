# Changelog — AppMitre

Registra cambios que afectan contratos entre módulos (API, schema de DB, nombres de campos, estructura de `window.APP_DATA`). No registrar fixes menores de estilo o bugs internos.

---

## [2026-06-29] — Búsqueda client-side desde caché en memoria + hash routing

**Tipo**: feature + cambio de contrato (frontend)
**Archivos**: `static/js/script.js`, `app.py`, `database.py`, `templates/index.html`

- **Búsqueda sin red**: al cargar la web, `cargarDatosIniciales()` descarga todo (`/api/dashboard` + nuevo `/api/personal_todos`) y lo guarda en `_allClases` / `_allPersonal`. Las búsquedas de `profesor`/`aula`/`curso`/`planilla` se resuelven 100% client-side via `filtrarClasesLocal()`, que replica la lógica de `obtener_filas()` de `app.py`. Si los datos aún no cargaron, hace fallback a los endpoints `/api/*` de siempre.
- `buscarEnServidor()` refactorizado: la lógica de render se extrajo a `procesarResultadoBusqueda(modo, valor, filas)` (compartida entre el camino local y el de red) y `mostrarErrorBusqueda()`.
- `allDataCache` (planilla general) y `lastDashboardData` (dashboard) ahora se inicializan desde el mismo `_allClases` para no duplicar descargas.
- **Hash routing**: las búsquedas de `profesor`/`aula`/`curso` actualizan `location.hash` (`#/profesor/MACIEL%20MARTIN`) → URLs compartibles/bookmarkeables. Un bloque `init()` al final del script lee el hash al cargar y dispara la búsqueda. `cambiarTab()` limpia el hash. `horario_preceptor` queda excluido del routing (evita race en `contenedor-lista` con la planilla de preceptores).
- **Nuevo endpoint** `GET /api/personal_todos` → `database.obtener_personal_todos()` (todo el personal no docente, mismo formato que `/api/personal/<nombre>`).
- `script.js` bumpeado a `?v=6` en `index.html`.
- **Modos que siguen yendo al server**: `preceptor`, `horario_preceptor` (tabla `horarios_preceptores`), PDF export, `/api/actualizar`.

---

## [2026-06-27] — Renombrado noche→vespertino + fix parsing preceptor + PDF carta

**Tipo**: fix de contrato + bugfix  
**Archivos**: `database.py`, `app.py`, `static/js/script.js`

- Campo `preceptores_noche` renombrado a `preceptores_vespertino` en DB, API y JS. Etiqueta `T.N:` → `T.V:`.
- `obtener_planilla_preceptores_todos()` ahora devuelve `vespertino` en vez de `noche`.
- `api_preceptor` corregido: parsing cambiado a `split(' ', 1)` para no romper divisiones multi-parte ("6 4° C"); ahora incluye campo `turno` en el response.
- `renderizarPreceptor` en JS: mapping actualizado a nombres completos ("MAÑANA"/"TARDE"/"VESPERTINO"); ahora identifica correctamente el preceptor principal del turno.
- PDF planilla preceptores: cambiado a formato carta (LETTER), texto escalable, márgenes reducidos a 5mm.

---

## [2026-06-25] — Baseline inicial de documentación

**Tipo**: baseline  
**Estado actual del sistema**:

- Flask + SQLite + Vanilla JS, sin tests ni linter.
- DB schema: tablas `clases` (20 columnas), `horarios_preceptores`, `personal_no_docente`.
- API: rutas `/api/<tipo>/<valor>`, `/api/preceptor/`, `/api/horario_preceptor/`, `/api/personal/`, `/api/dashboard`, `/api/actualizar`, `/api/planilla_preceptores`, `/export/pdf/<tipo>/<valor>`.
- Frontend recibe `window.APP_DATA = {rawData, floorMapping, dias}`.
- Acceso a filas por índice numérico (f[0]–f[19] para clases, f[20] para marker personal).
- Versión de branding: V1.16.

---

## [fecha desconocida] — Fase 1 PLAN_ESCUELAS: limpieza de hardcodes

**Tipo**: refactor  
**Cambios**:
- `ESCUELA_NOMBRE`, `ESCUELA_LOGO`, `ESCUELA_VERSION` movidos a `config.py` y pasados al template por Flask.
- `nombre_mapeos.json` extraído a archivo externo (antes estaba inline en `database.py`).
- `DIAS` centralizado en `config.py`; en `script.js` se usa `window.APP_DATA.dias` en lugar de arrays hardcodeados.
- `corregir_horarios()` eliminada — los datos deben venir correctos del sheet.
- Inferencia de turno por hora eliminada de `obtener_preceptores_por_curso()` — turno es ahora config explícita via `TURNO_CURSOS` / `TURNO_DEFAULT`.
- `FLOOR_MAPPING` y `TURNO_CURSOS` / `TURNO_DEFAULT` agregados a `config.py`.

**Contrato afectado**: `window.APP_DATA` ahora incluye `dias` (antes hardcodeado en JS).

---

## [fecha desconocida] — Agregado tabla `horarios_preceptores`

**Tipo**: schema  
**Cambios**:
- Nueva tabla `horarios_preceptores` en DB.
- Nuevo GID `"horarios_preceptores"` en `config.py`.
- Nuevas rutas: `/api/preceptor/<valor>`, `/api/horario_preceptor/<nombre>`, `/api/planilla_preceptores`.
- `rawData` ahora incluye `horario_preceptor` (lista de nombres).
- Nuevo tab "PRECEPTORES" en la UI.

---

## [fecha desconocida] — Agregado tabla `personal_no_docente`

**Tipo**: schema  
**Cambios**:
- Nueva tabla `personal_no_docente` en DB.
- Nuevo GID `"personal_no_docente"` en `config.py`.
- Nueva ruta `/api/personal/<nombre>`.
- `rawData` ahora incluye `personal` (lista de `{nombre, rol}`).
- Búsqueda por profesor ahora hace dos requests paralelos (clases + personal).
- `personalToFila()` agrega índice [20] como marker `'personal'` — si la tabla `clases` agrega columnas, este índice puede colisionar.

---

## [fecha desconocida] — Agregado modo comparación

**Tipo**: feature  
**Cambios**:
- Nuevas variables globales: `isComparacionMode`, `comparacionItems`, `lastFilas`.
- Nueva función `generarCalendarioComparacion()`.
- Nuevo slide-panel con botón COMPARAR en tabs PROFESORES, AULAS, CURSOS.
- Nuevo banner de comparación en el HTML.

---

## [fecha desconocida] — Agregado modo Planilla General

**Tipo**: feature  
**Cambios**:
- Nueva función `generarPlanillaGeneral()`.
- `allDataCache` — caché de todas las clases.
- Nuevos controles de día y piso en el tab AULAS.
- Slide-panel en AULAS ahora tiene botón PLANILLA GENERAL.
- Ruta PDF soporta `tipo=planilla` con valor `"dia|piso"`.

---

## [fecha desconocida] — Modo kiosco (F11)

**Tipo**: feature  
**Cambios**:
- Listener `fullscreenchange` en `document`.
- Clase `is-fullscreen` en `body` controla visibilidad de header, footer, tabs.
- Filtro de texto en dashboard.

---

## [fecha desconocida] — Suplentes (suplente_activo / prof_suplente)

**Tipo**: schema  
**Cambios**:
- Columnas `suplente_activo`, `prof_suplente`, `sup_ini`, `sup_fin` agregadas a tabla `clases`.
- Rendering condicional de "LICENCIADA" en vista de profesor.
- Dashboard muestra "SUPLENTE: nombre" en lugar del titular.

---

_Para el próximo cambio, agregar una entrada aquí si afecta: el schema de DB, la estructura de `window.APP_DATA`, el contrato de la API, o el orden de columnas en los arrays de filas._
