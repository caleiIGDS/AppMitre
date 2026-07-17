# Decisiones de Arquitectura — AppMitre

Leer este archivo antes de "corregir" algo que parece raro. Muchas decisiones tienen contexto específico de la escuela o del despliegue.

---

## [2026-07-17] — Gestión de Conocimiento con el stack existente y DB separada (no Next.js/Supabase)

**Contexto**: El documento de diseño del Sistema de Gestión de Conocimiento venía con un prompt que pedía Next.js + Supabase + Tailwind. Pero el pedido real fue integrarlo **dentro de AppMitre** como módulo al mismo nivel que horarios, sin tocar lo existente.

**Decisión**:
- **Stack existente** (Flask + SQLite + Jinja): un solo deploy, cero build step, consistente con la decisión "Vanilla JS sin framework". El módulo es server-rendered clásico (forms + redirects, sin JS propio) en vez de SPA — para CRUD simple es menos código y menos superficie de bugs.
- **DB separada `gestion.db`**: `escuela.db` es un caché efímero que `/api/actualizar` borra y regenera desde Sheets; los datos de gestión son la única fuente de verdad propia de la app y no pueden vivir en una DB que se dropea. Blueprint aislado en `gestion.py` para que ambos sistemas no compartan nada más que `config.py` (branding).
- **Templates genéricos manejados por config** (`ENTIDADES` en `gestion.py`): un solo trío lista/form/detalle para las 4 entidades, en vez de 12 templates.

**Alternativas descartadas**:
- *Next.js + Supabase (el stack del prompt)*: segunda app, segundo deploy, dependencia de servicio externo — contradice el pedido de integrarlo en la app actual.
- *Tablas de gestión dentro de `escuela.db`*: `/api/actualizar` las borraría (o habría que hacer el drop selectivo, acoplando los módulos).
- *Modo oscuro / temas en gestión*: `gestion.css` es standalone y no participa del sistema `data-theme`; se puede sumar después si se usa.

**Consecuencia**: En hosting con filesystem efímero (Render) `gestion.db` se pierde en cada restart — en PythonAnywhere (hosting actual) persiste. Si el módulo prospera, evaluar backup del archivo o export a Sheets. Sin auth: cualquiera puede crear/editar/borrar (mismo riesgo aceptado que `/api/actualizar`).

**Contexto**: `PLAN_ESCUELAS.md` proponía parsers por nombre de encabezado (E2 para clases, E4 para preceptores) para tolerar sheets con columnas reordenadas o insertadas. Al revisar el plan multi-escuela se definió el alcance real: la app no va a soportar sheets con formatos variables.

**Decisión**: La web asume una **estructura fija** del Google Sheet, definida por contrato en `PLANTILLA_SHEET.md`: una escuela nueva **copia la plantilla estándar** y carga sus datos. Los parsers actuales de `database.py` se mantienen tal cual.

**Precisión (verificada en código el 2026-07-13)**: E2 ya estaba resuelto de facto — `cargar_desde_sheets()` y `cargar_personal_no_docente()` usan `csv.DictReader` con encabezados normalizados (el orden de columnas es libre; el contrato son los **nombres** de encabezado). El único parser posicional es el de preceptores (bloques por offset 0/9/18), y queda así.

**Alternativa descartada**: Validación de encabezados/estructura al cargar (error claro si falta una columna). Menos frágil ante ediciones accidentales del sheet, pero se prefirió no agregar complejidad: el formato queda fijado por plantilla documentada.

**Consecuencia**:
- E2 y E4 se eliminan de `PLAN_ESCUELAS.md`; la tarea #4 del backlog se descartó.
- La Fase 2 queda reducida a E3 (API con objetos, TODO #3) + la plantilla estándar documentada (`PLANTILLA_SHEET.md`, TODO #19 — hecha el 2026-07-13).
- **Riesgo aceptado**: mover columnas en el sheet de preceptores, o renombrar un encabezado en clases/personal, corrompe o vacía datos silenciosamente. La protección es la plantilla documentada, no el código.

---

## [2026-07-01] — Sistema de temas por CSS variables + tonos curados (no picker libre)

**Contexto**: El usuario no soportaba el naranja `#FF6B00` (demasiado chillón) y pidió 3 UIs seleccionables manteniendo la estética técnica.

**Decisión**:
- Theming por **atributos independientes en `<body>`**: `data-theme` (4 temas: blueprint/swiss/nocturno/hud, layout+claro/oscuro) y `data-tone` (6 acentos, color). Se eligió atributo sobre clase porque `data-theme` es un enum limpio y coexiste con `is-fullscreen` sin colisión.
- Todo el acento pasa por `--accent`; `--secondary` quedó como **alias** (`var(--accent)`) para no tocar los 36+ usos existentes.
- El naranja base se suavizó a ámbar `#D97A34` (tono "ambar", default).
- **Tonos curados** (6 presets sobrios) en vez de un color picker libre: el usuario pidió explícitamente nada de rojo/azul/verde clásicos ("si es azul, que sea marino").
- Persistencia en **`localStorage`** (primer uso en la app) + script inline anti-flash al inicio de `<body>`.
- Temas oscuros (nocturno/hud) comparten overrides vía flag `data-dark` (seteado por JS) para no duplicar las reglas de superficie.

**Gotcha resuelto (bug real del selector)**: `--secondary`/`--accent-soft` deben declararse en **`body`, no en `:root`**. Un `var()` dentro de una custom property se congela en el elemento donde se declara; en `:root` no seguía al `--accent` del tono, así que el selector "solo cambiaba los bloques personal" (que usaban `var(--accent)` directo). Movidas a `body` → se re-resuelven contra el tono activo.

**Iteración de scope**: el tema "Compacto" (sidebar) se descartó por pedido del usuario y se reemplazó por dos temas oscuros (Nocturno + HUD).

**Alternativas descartadas**: color picker libre (riesgo estético); themes como archivos CSS separados (más peso); tema Compacto/sidebar (descartado tras review del usuario).

**Consecuencia**: Reskin casi total desde variables. Dark mode requiere overrides puntuales de colores claros hardcodeados (no todo era variable). Pendiente: `COMPARACION_COLORS` en `script.js` (paleta fija, no sigue el tono). Ver `agent_docs/frontend-ui.md` → "Temas y tonos".

---

## [fecha desconocida] — Vanilla JS sin framework

**Contexto**: App de consulta de horarios para una escuela técnica. El desarrollador es solo uno. La app no tiene proceso de build.

**Decisión**: Vanilla JS + HTML directo. Sin React, Vue, Angular ni ningún framework.

**Alternativa descartada**: Cualquier framework SPA moderno. Requeriría `npm`, un build step, y un ciclo de desarrollo más lento.

**Consecuencia**: `script.js` ha crecido a ~1600 líneas con duplicación de lógica de rendering entre `generarCalendario`, `generarCalendarioComparacion` y `generarPlanillaGeneral`. La deuda es conocida y documentada en `PLAN_ESCUELAS.md` como E3.

---

## [fecha desconocida] — SQLite efímero en lugar de PostgreSQL persistente

**Contexto**: Render.com (free tier) borra el filesystem entre restarts. Render ofrece PostgreSQL gratuito como add-on, pero tiene límites de conexiones y agrega complejidad de setup.

**Decisión**: SQLite como caché efímero de los datos de Google Sheets. La DB se regenera automáticamente desde Sheets en cada arranque en frío.

**Alternativa descartada**: PostgreSQL en Render. Requiere gestionar cadenas de conexión, migraciones, y hace la app dependiente de un servicio adicional.

**Consecuencia**: Datos siempre frescos (se re-descargan de Sheets). Sin persistencia de ningún estado. El primer usuario tras un período de inactividad espera 30–50s mientras la app "despierta" y recarga la DB. Ver `dev-log/tasks/TODO.md` #1 — el mecanismo de auto-inicialización bajo gunicorn está pendiente.

---

## [fecha desconocida] — `window.APP_DATA` cargado en el page load

**Contexto**: El autocompletado necesita filtrar ~200–300 nombres de docentes con cada keystroke.

**Decisión**: Todo el catálogo (profesores, aulas, cursos, preceptores, personal) se serializa en el HTML inicial como `window.APP_DATA.rawData`.

**Alternativa descartada**: Endpoint de autocompletado con debounce. Introduciría latencia perceptible especialmente con Render free tier (que puede tardar en responder).

**Consecuencia**: El HTML inicial es algo más pesado (~50–100KB extra). Búsquedas instantáneas sin round-trip al servidor. Si la DB tiene miles de docentes (en otro contexto), esto escalaría mal.

---

## [fecha desconocida] — `nombre_mapeos.json` manual en lugar de fuzzy matching

**Contexto**: Los nombres de profesores en el Google Sheet tienen errores tipográficos inconsistentes entre hojas (ej: "CASALE SERVIN BETTINA" vs "CASALE SERVINI BETTINA" vs "CASALE CERVINI BETINA").

**Decisión**: Archivo JSON de mapeos manuales que el desarrollador mantiene.

**Alternativa descartada**: Fuzzy matching automático (ej: Levenshtein). Los falsos positivos son inaceptables — asignar el horario de un docente a otro silenciosamente sería un bug crítico invisible.

**Consecuencia**: Requiere intervención manual cuando aparece un nuevo typo. El archivo se carga una vez al iniciar; agregar un mapeo sin reiniciar no tiene efecto inmediato.

---

## [fecha desconocida] — Acceso a filas de DB por índice numérico en el frontend

**Contexto**: La API devuelve `SELECT *` y el JS accede como `f[0]`, `f[5]`, `f[9]`, etc.

**Decisión**: [inferido] Fue una decisión de velocidad de desarrollo inicial que nunca se refactorizó.

**Alternativa descartada**: La API debería devolver objetos con claves nombradas.

**Consecuencia**: Cambiar el orden de columnas en la tabla rompería todo el frontend silenciosamente. Documentado como E3 en `PLAN_ESCUELAS.md` y como TODO #3 en el backlog.

**Resuelto [2026-07-13]**: la API devuelve objetos con claves nombradas y el frontend accede por clave. Ver `dev-log/CHANGELOG.md` [2026-07-13].

---

## [fecha desconocida] — Layout de preceptores con bloques de columnas por offset

**Contexto**: El Google Sheet de preceptores tiene 3 "tablas" yuxtapuestas horizontalmente (MAÑANA, TARDE, VESPERTINO) en lugar de una tabla única con columna de turno.

**Decisión**: `cargar_horarios_preceptores()` asume offsets fijos: MAÑANA en columna 0, TARDE en columna 9, VESPERTINO en columna 18 (8 cols de datos + 1 col separadora vacía = paso de 9). La primera fila se ignora con `next(reader, None)`.

**Alternativa descartada**: Reestructurar el sheet. El sheet ya existe con datos y no se quiere modificar la planilla original de la escuela.

**Consecuencia**: El parser es muy frágil. Si la escuela agrega o mueve columnas en el sheet de preceptores, los datos se corrompen. Documentado como E4 en `PLAN_ESCUELAS.md`.

---

## [fecha desconocida] — `corregir_horarios()` eliminada

**Contexto**: Existía una función que intentaba inferir la `hora_fin` cuando `hora_inicio == hora_fin` en el sheet (error de carga). Usaba una lista hardcodeada de horarios comunes del Mitre.

**Decisión**: La función fue eliminada. La planilla debe tener datos correctos. Si hay una clase con `hora_inicio == hora_fin`, se carga tal cual y el frontend la renderiza como bloque de 0 altura.

**Alternativa descartada**: Mantener la corrección automática.

**Consecuencia**: Los datos deben estar bien en el sheet desde el origen. Errores en el sheet son visibles en la UI (bloques raros o ausentes) en lugar de silenciosos.

---

## [fecha desconocida] — `/api/actualizar` como GET en lugar de POST

**Contexto**: [inferido] Decisión de simplicidad. Los formularios HTML y los `fetch()` simples usan GET por default.

**Decisión**: La ruta que borra y recarga la DB completa es un GET.

**Alternativa descartada**: POST con CSRF protection.

**Consecuencia**: Cualquiera que conozca la URL puede triggear una recarga de la DB. No hay autenticación. En producción (Render), el Sheet es público de todas formas, así que el riesgo es bajo — lo peor que puede pasar es un re-download innecesario.

---

## [fecha desconocida] — `allDataCache` para la Planilla General sin invalidación

**Contexto**: La Planilla General necesita todas las clases de un piso para un día. Hacer un request a `/api/dashboard` por cada cambio de día o piso sería ineficiente.

**Decisión**: Los datos se cachean en `allDataCache` después del primer fetch y no se vuelven a cargar en la sesión.

**Alternativa descartada**: Refetch en cada cambio de selector.

**Consecuencia**: Si el usuario actualiza la DB (botón ACTUALIZAR HORARIOS) mientras tiene la planilla abierta, el caché queda obsoleto. Requiere F5 para ver los datos nuevos. Es un trade-off aceptado.

---

## [2026-06-25] — PythonAnywhere como hosting

**Contexto**: Necesidad de hosting gratuito con dominio personalizado y HTTPS para la escuela.

**Decisión**: PythonAnywhere (Flask/WSGI). La DB (`escuela.db`) persiste en el filesystem entre reinicios, a diferencia de Render donde era efímera.

**Alternativa descartada**: Render.com. Render borraba el filesystem entre cold starts, lo que requería re-descargar toda la DB desde Sheets cada vez que el servicio "despertaba".

**Consecuencia**: El bloque `if __name__ == '__main__'` en `app.py` no se ejecuta bajo WSGI — la inicialización de la DB debe hacerse manualmente (consola de PythonAnywhere o via `/api/actualizar`) en un deploy nuevo. Ver TODO #1.

---

## [2026-06-29] — Toda la data cacheada en memoria al cargar + hash routing

**Contexto**: Cada búsqueda (clases y preceptores) hacía un request al server. El dataset completo es chico (`/api/dashboard` = ~2.300 filas × 20 cols; personal ~cientos de filas; preceptores 47 horarios + 62 filas de planilla). En Render/PythonAnywhere free tier, los round-trips agregan latencia perceptible. El usuario pidió explícitamente que al abrir la web se descargue **toda** la info (clases, personal, preceptores) y de ahí en más no se toque la red.

**Decisión**: `cargarDatosIniciales()` descarga todo una sola vez al cargar (`/api/dashboard`, `/api/personal_todos`, `/api/preceptores_data`) y guarda en globals (`_allClases`, `_allPersonal`, `_horariosPreceptores`, `_planillaPreceptores`). Todas las búsquedas se resuelven client-side; solo PDF y `/api/actualizar` van a la red. Se mantiene fallback a los endpoints `/api/*` si los datos aún no cargaron. En paralelo, hash routing (`#/profesor/...`) para URLs compartibles.

**Para preceptores** (tabla `horarios_preceptores`): en vez de replicar las agregaciones SQL (GROUP_CONCAT, turnos) en JS, el endpoint `/api/preceptores_data` **reusa las funciones server existentes** (`obtener_horario_preceptor`, `_planilla_preceptores_con_turnos`) y devuelve todo pre-computado, para que el cliente solo haga lookups. Esto evita una cuarta fuente de verdad de lógica SQL.

**Alternativa descartada**:
- *Service Worker / offline real (PWA)*: descartado por complejidad — el usuario eligió "session cache". Si se refresca la página se necesita red de nuevo; suficiente para un kiosco siempre encendido.
- *Clean URLs (`/profesor/...`) con catch-all en Flask*: descartado para no tocar el backend. El hash no requiere cambios en Flask.
- *Cachear filas crudas de `horarios_preceptores` y replicar las agregaciones en JS*: descartado; se prefirió pre-computar en el server reusando funciones existentes.

**Consecuencia**:
- Hay **dos fuentes de verdad** para el filtrado de clases: `obtener_filas()` (Python) y `filtrarClasesLocal()` (JS). Si una cambia, la otra debe seguirla. Los preceptores NO tienen este problema (el server pre-computa, el cliente solo lookupea).
- El caché no se invalida tras `/api/actualizar` sin un F5 (mismo trade-off ya aceptado para `allDataCache`).
- **Cambio de comportamiento (mejora)**: `obtenerPreceptorLocal()` usa el turno correcto del curso (vía `_planillaPreceptores`), corrigiendo de facto el bug de la ruta `/api/preceptor/<valor>` que devolvía siempre `TURNO_DEFAULT` por buscar la clave con `°`. El "PRECEPTOR PRINCIPAL" ahora se marca según el turno real.
- Deep-link de `horario_preceptor`: para evitar la race en `contenedor-lista` (planilla vs tabla del preceptor), `cambiarTab()` omite `mostrarPlanillaCursos()` cuando `window.isProgrammaticNavigation` está activo.

---

## [fecha desconocida] — `personalToFila()` para fusionar personal con clases

**Contexto**: En la vista de profesor, se quieren mostrar los turnos del personal no docente (porteros, secretarias) junto con los horarios de clases en el mismo calendario.

**Decisión**: `personalToFila()` convierte el objeto `{nombre, rol, dia, hora_inicio, hora_fin}` en un array de 21 elementos que imita el formato de una fila de la tabla `clases`, con `row[20] = 'personal'` como marker de tipo.

**Alternativa descartada**: Cambiar la API para devolver objetos con claves nombradas (E3 en `PLAN_ESCUELAS.md`), que haría innecesario este workaround.

**Consecuencia**: El workaround funciona pero es frágil — si la tabla `clases` agrega columnas, el índice 20 de `personalToFila` puede colisionar.

**Resuelto [2026-07-13]**: con E3 completado, `personalToFila()` devuelve un objeto con claves nombradas y marker `tipo: 'personal'` — ya no hay índices que colisionen.
