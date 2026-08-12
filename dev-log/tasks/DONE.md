# Completado — AppMitre

_Solo leer si se pide explícitamente._

---

## [2026-08-11] — #20 Accesos por niveles: público / interno / admin (cierra #20)
Motor nuevo `accesos.py` (capa 1, hermano de `crud.py`) + `accesos.db` + panel `/accesos`. Reemplaza la contraseña compartida única por tres niveles: **público** (el SPA de horarios), **interno** (dispositivos habilitados por link de invitación de un solo uso, con permisos sueltos) y **admin** (`GESTION_CLAVE`, comodín `*`). Cada área declara sus `PERMISOS` con un verbo y entra sola al catálogo y a los perfiles: sumar un área nueva no toca el gate ni migra los accesos ya dados. El asistente **no recibe** las tools de escritura si el acceso no las tiene (filtrado en `tools_permitidas`, antes de la llamada a la API) y su system prompt se recorta en consecuencia; con permiso de escritura el prompt es byte a byte el de antes. Se sacaron los defaults públicos de `SECRET_KEY`/`GESTION_CLAVE` (obligatorias en producción), la sesión pasó a ser permanente y deslizante (se acabó re-tipear la clave en cada visita), y `/api/actualizar` dejó de ser GET público y destructivo. Verificado en runtime (49 casos: los tres niveles, canje, reuso del link, revocación instantánea, multi-dispositivo, filtrado de tools). Ver CHANGELOG y DECISIONS 2026-08-11, y `agent_docs/accesos.md`. Lo que quedó fuera a propósito → TODO #24.

## [2026-07-21] — Préstamos: devolución parcial por ítem + retiro desde la ficha del recurso
Columna `prestamo_items.cantidad_devuelta` (migración aditiva). Rutas `devolver_item`/`reabrir_item`: devolver/deshacer de a partes (ej: 1 de 3); `_recalcular_estado()` cierra o reabre el préstamo según el pendiente total, con `fecha_devolucion` como fuente de verdad de "cerrado". `devolver`/`reabrir` pasan a ser "todo". `prestamo_nuevo?recurso=<id>` precarga la fila 1 desde la ficha del recurso. Ver CHANGELOG y DECISIONS 2026-07-21.

## [2026-07-21] — Búsqueda en vivo (client-side) del listado de `/gestion`
`static/gestion.js` (nuevo, primer JS del módulo): filtra el listado en el navegador mientras se escribe, sin recargar ni ir al server. Progressive enhancement — sin JS, el form sigue con la búsqueda difusa server-side. La ruta emite `data-buscar` normalizado por Python por fila; el JS filtra por substring (perdona acentos/mayúsculas, no typos: eso lo compensa el ver los resultados al escribir). Verificado: server-side con test_client + lógica del JS real en Node (11/11). Ver CHANGELOG/DECISIONS 2026-07-21.

## [2026-07-21] — Búsqueda de recursos tolerante (acentos + typos)
`lista()` filtra en Python con `_puntaje_busqueda()`: normaliza acentos/mayúsculas y perdona typos por similitud (`difflib`, sin dependencias). Substring gana siempre; el difuso entra con 3+ caracteres y umbral 0.6. Verificado en runtime (9 casos). Es el "nivel 1+2" de la tarea #21 — falta la columna `otros_nombres` + IA para sinónimos que no se parecen. Ver DECISIONS 2026-07-21.

## [2026-07-21] — Préstamos / retiros internos de recursos
Tablas `prestamos` + `prestamo_items`: registro de quién se lleva qué recursos y cuánto; devolver marca fecha sin borrar el historial. Rutas y templates propios (fuera de `ENTIDADES`), sección "historial de préstamos" en la ficha del recurso, desambiguación de nombres duplicados por `[#id]`. Verificado en runtime (13 casos). Ver CHANGELOG/DECISIONS 2026-07-21.

## [2026-07-19] — Login provisorio con contraseña compartida en `/gestion`
Todo el blueprint detrás de `bp.before_request` + sesión Flask: rutas `/gestion/login` y `/gestion/salir`, template `login.html`, botón SALIR en el header. Clave vía env var `GESTION_CLAVE` (default público `mitre2026`), `SECRET_KEY` en `app.py`. Verificado en runtime (redirects con `next`, clave incorrecta/correcta, anti open-redirect, salir, SPA y API intactos). Seguridad completa diferida → TODO #20.

## [2026-07-19] — Inventario físico de renovables importado a `/gestion/recursos`
`importar_inventario.py` (nuevo): sheet "Inventario renovable 2026" → tabla `recursos` (81 insertados + 2 actualizados, upsert por nombre normalizado). Columnas nuevas `cantidad`/`utilidad`/`fecha_revision` con migración aditiva en `init_db()`; estado nuevo "Sin revisar". Ver CHANGELOG y DECISIONS 2026-07-19.

## [2026-07-17] — Módulo Sistema de Gestión de Conocimiento (`/gestion`)
Blueprint server-rendered (Jinja, sin JS propio) con DB propia `gestion.db`: CRUD de recursos, conjuntos, actividades y proyectos con relaciones M2M navegables, búsqueda `?q=`, seed de ejemplo. Ver `agent_docs/gestion-conocimiento.md`.

## [2026-07-17] — #5: `TURNO_CURSOS` poblado con datos reales
`config.py` tiene el turno de todos los cursos 1°–7° (MAÑANA/TARDE/VESPERTINO); 6° 4-8 y todo 7° son vespertinos. Verificado y movido de TODO en esta fecha (ya estaba completo de antes).

## [2026-07-17] — #6: cache obsoleto tras "ACTUALIZAR HORARIOS" (obsoleta)
El escenario descripto ya no puede ocurrir: `actualizarDatos()` hace `location.reload()` en el callback de éxito, lo que reconstruye `allDataCache` completo. No hizo falta el `allDataCache = null` propuesto.

## [2026-07-17] — #7: aulas solapadas en `FLOOR_MAPPING` (resuelta)
"Piso 3" ahora tiene aulas propias ("31","32","33","35","36"); ya no comparte "13"–"16" con "Piso 1". Verificado en `config.py` y movido de TODO.

## [2026-07-17] — #14: `DOCUMENTACION_DETALLADA.md` desactualizada (resuelta)
El archivo ya no existe en el repo — se eliminó, que era una de las dos opciones de la tarea. Los `agent_docs/` quedan como única documentación técnica.

## [fecha desconocida] — Calendario semanal por curso / profesor / aula
Generación de grid CSS con bloques absolutos. Clustering de solapamientos. Modal de detalle con navegación interna. Tooltip en hover.

## [fecha desconocida] — Dashboard "En Vivo" / Kiosco
Filtrado por hora actual, columnas "En Curso" / "Próximas", refresh 1s, modo manual con date/time pickers, modo kiosco con F11.

## [fecha desconocida] — Exportación a PDF
PDF A4 landscape con fpdf2, Roboto Mono embedded, grid de horas, truncado de texto adaptativo, soporte para curso/profesor/aula/planilla.

## [fecha desconocida] — Sistema de búsqueda con autocompletado
Filtrado client-side con normalización (sin acentos, sin espacios), priorización de prefijos, fusión de docentes + personal en modo profesor, badge de rol.

## [fecha desconocida] — Modo comparación de horarios
Grid expandido horizontalmente, hasta 6 colores distintos, chips con cierre individual, banner de modo activo.

## [fecha desconocida] — Planilla General (vista aeropuerto)
Grid con aulas como columnas para un día seleccionable. Cache en sesión. Integrado en slide-panel del tab AULAS.

## [fecha desconocida] — Pipeline de datos Google Sheets → SQLite
`descargar_sheet()` con reintentos, `cargar_desde_sheets()`, `cargar_horarios_preceptores()`, `cargar_personal_no_docente()`.

## [fecha desconocida] — Normalización de nombres y aulas
`limpiar_profesor()` con `nombre_mapeos.json`, `limpiar_aula()` con detección de talleres y mapeos especiales.

## [fecha desconocida] — Tab PRECEPTORES con planilla de cursos
Vista de tabla de cursos por turno + vista de horario individual de preceptor.

## [fecha desconocida] — Soporte de suplentes (suplente_activo)
Rendering de "LICENCIADA" en vista de profesor, suplente mostrado en demás vistas, soporte en PDF y dashboard.

## [2026-06-08] — Setup hosting Render + Cloudflare
Documentado en `PLAN_HOSTING_GRATIS.txt`. Gunicorn configurado como start command. Cloudflare DNS con CNAME a Render. (Nota: la auto-inicialización de DB bajo gunicorn está pendiente — ver TODO #1.)

## [fecha desconocida] — Fase 1 PLAN_ESCUELAS: eliminar hardcodes evidentes
`config.py` centraliza branding, días y FLOOR_MAPPING. `nombre_mapeos.json` externo. `window.APP_DATA.dias` como fuente única. Eliminación de `corregir_horarios()` e inferencia de turno por hora.

## [2026-07-13] — #3 API devuelve objetos con claves nombradas (E3 PLAN_ESCUELAS)
`obtener_filas()` y `/api/dashboard` devuelven dicts (`sqlite3.Row`); `script.js` migrado completo (~99 refs `f[N]` → `f.campo` en calendario, comparación, planilla, dashboard, modal, tooltip y `filtrarClasesLocal`); `personalToFila()` devuelve objeto con marker `tipo: 'personal'`; código PDF de `app.py` (`obtener_datos_calendario` + `dibujar_pagina_horario`) actualizado. Cache-buster `script.js` `?v=13`→`?v=14`. Verificado en runtime: API (curso/profesor/planilla/suplente/casos vacíos), 4 PDFs, y render client-side (calendario, licencia, personal, dashboard) vía Edge headless.

## [2026-07-13] — #19 Plantilla estándar del Google Sheet documentada
`PLANTILLA_SHEET.md` en el root: pestañas requeridas, encabezados de clases (parsing por nombre, orden libre), layout posicional de preceptores (bloques offset 0/9/18), formato de personal no docente, config del lado de la app y checklist para una escuela nueva. Derivado del código real de `database.py`. Al escribirla se detectó que E2 (parser por nombre de columna) ya estaba implementado con `csv.DictReader` — el plan estaba desactualizado; se corrigieron `PLAN_ESCUELAS.md`, `dev-log/DECISIONS.md` y `agent_docs/data-pipeline.md` (offsets y regla de marca de día).
