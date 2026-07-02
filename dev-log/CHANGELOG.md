# Changelog — AppMitre

Registra cambios que afectan contratos entre módulos (API, schema de DB, nombres de campos, estructura de `window.APP_DATA`). No registrar fixes menores de estilo o bugs internos.

---

## [2026-07-01] — Tema HUD reemplazado por Soft (friendly)

**Tipo**: cambio de UI
**Archivos**: `static/style.css`, `static/js/script.js`, `templates/index.html`

- Se **eliminó el tema HUD** (bloque de variables + reglas específicas + opción del select + entradas en `TEMAS_VALIDOS`/`TEMAS_OSCUROS`).
- Nuevo tema **`soft`** (claro/"friendly"): sans redondeada (`ui-rounded`/Segoe UI), fondo off-white cálido sin grilla, tabs/botones tipo píldora, tarjetas flotantes con sombras suaves, `--radius: 16px`, bloques del calendario redondeados. Es tema claro → **no** lleva `data-dark`.
- `TEMAS_VALIDOS` = `blueprint`/`swiss`/`nocturno`/`soft`; `TEMAS_OSCUROS` = `nocturno`.
- Cache-busters: `style.css` `?v=8`→`?v=9`, `script.js` `?v=10`→`?v=11`.

---

## [2026-07-01] — Sistema de temas + tonos (3 UIs seleccionables)

**Tipo**: feature + cambio de contrato (CSS/JS)
**Archivos**: `static/style.css`, `static/js/script.js`, `templates/index.html`

- **Nuevo contrato visual**: `<body>` lleva `data-theme` (`blueprint`|`swiss`|`nocturno`|`hud`), `data-tone` (`ambar`|`terracota`|`bronce`|`teal`|`marino`|`ciruela`) y `data-dark` (flag para temas oscuros, seteado por JS). Tema+tono persistidos en `localStorage` (`appmitre-theme`, `appmitre-tone`) — primer uso de localStorage en la app.
- **Nuevos tokens CSS**: en `:root` → `--accent` (default ámbar `#D97A34`), `--surface`, `--border`, `--muted`, `--radius`, `--font-ui`. En **`body`** (no `:root`, por resolución de `var()` en custom properties) → `--secondary` (alias de `--accent`) y `--accent-soft`. Tokens de temas oscuros: `--text`, `--panel`, `--block-bg`. El naranja `#FF6B00` fue reemplazado.
- El font hardcodeado `'Roboto Mono', monospace` se reemplazó por `var(--font-ui)` en todo `style.css` (Swiss lo cambia a sans).
- **Bloques personal**: el estilo inline con hex (`#FDE8D0`/`#FF6B00`/`#1A365D`) se movió del JS a la clase CSS `.personal-cargo-bloque` para que respete el tono activo.
- Nuevas funciones JS: `applyTheme()`, `applyTone()`, `initTheme()` (llamada en `DOMContentLoaded`); `TEMAS_VALIDOS`/`TEMAS_OSCUROS`/`TONOS_VALIDOS`.
- Selector en el header (`.theme-switcher`): `<select>` de tema + swatches de tono. Se oculta en kiosko.
- **Fix**: `--secondary`/`--accent-soft` movidas de `:root` a `body` — en `:root` se congelaban y el selector de tono no cambiaba el acento (solo los bloques personal).
- Temas: se descartó "Compacto" (sidebar) y se agregaron **Nocturno** (dark) y **HUD** (panel de instrumentos).
- Cache-busters: `style.css` `?v=6`→`?v=8`, `script.js` `?v=8`→`?v=10`.

---

## [2026-06-29] — Toda la data cacheada en memoria al cargar + hash routing

**Tipo**: feature + cambio de contrato (frontend)
**Archivos**: `static/js/script.js`, `app.py`, `database.py`, `templates/index.html`

- **Todo sin red tras la carga inicial**: `cargarDatosIniciales()` descarga en paralelo `/api/dashboard` (→ `_allClases`), `/api/personal_todos` (→ `_allPersonal`) y `/api/preceptores_data` (→ `_horariosPreceptores` + `_planillaPreceptores`). A partir de ahí **ninguna búsqueda pega al server**: profesor/aula/curso/planilla, horario de preceptor, preceptor-por-curso y planilla de preceptores se resuelven client-side. Solo van a la red: PDF export y `/api/actualizar`.
- Resolución client-side: `filtrarClasesLocal()` (clases, replica `obtener_filas()`), lookup `_horariosPreceptores[nombre]` (horario individual), `obtenerPreceptorLocal()` (preceptor-por-curso desde `_planillaPreceptores`), y `mostrarPlanillaCursos()` usa `_planillaPreceptores`. Todos con fallback a su endpoint `/api/*` si los datos no cargaron.
- `buscarEnServidor()` refactorizado: render extraído a `procesarResultadoBusqueda(modo, valor, filas)` (compartido caché/red) y `mostrarErrorBusqueda()`.
- `allDataCache` (planilla general) y `lastDashboardData` (dashboard) se inicializan desde el mismo `_allClases`.
- **Hash routing**: `profesor`/`aula`/`curso`/`horario_preceptor` actualizan `location.hash` (`#/profesor/MACIEL%20MARTIN`) → URLs compartibles. `init()` lee el hash al cargar y dispara la búsqueda; `cambiarTab()` lo limpia. Deep-link de preceptor: `cambiarTab()` omite `mostrarPlanillaCursos()` bajo `window.isProgrammaticNavigation` (evita race en `contenedor-lista`).
- **Nuevos endpoints**: `GET /api/personal_todos` (todo el personal no docente) y `GET /api/preceptores_data` (`{horarios: {nombre:[filas]}, planilla: [...]}`, reusa `obtener_horario_preceptor` + `_planilla_preceptores_con_turnos`).
- **Cambio de comportamiento (mejora)**: en el camino cacheado, el "PRECEPTOR PRINCIPAL" se marca según el turno real del curso. La ruta `/api/preceptor/<valor>` tenía un bug (lookup de turno con `°` → siempre `TURNO_DEFAULT`); `obtenerPreceptorLocal()` usa el turno correcto de la planilla. Ver `agent_docs/search-api.md`.
- `script.js` bumpeado a `?v=7` en `index.html`.

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
