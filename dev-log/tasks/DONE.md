# Completado — AppMitre

_Solo leer si se pide explícitamente._

---

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
