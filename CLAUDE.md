# CLAUDE.md

## Qué es esta app

**AppMitre** es un sistema de gestión y visualización de horarios para la **Escuela Técnica Emilio Mitre**. Permite consultar los horarios de clases organizados por curso (1°–7°), profesor, aula y preceptor. Incluye un dashboard en tiempo real ("En Vivo") para uso en pantallas de kiosco y exportación a PDF.

**Usuarios principales:** alumnos, docentes, preceptores y administración.  
**Stack:** Flask + SQLite + Vanilla JS (sin frameworks). Sin tests, sin linter, sin build step.

---

## Commands

```bash
pip install -r requirements.txt   # instalar dependencias
python app.py                      # dev en http://localhost:5000
gunicorn app:app                   # producción
# POST /api/actualizar             # regenerar DB desde Google Sheets
```

---

## Arquitectura

```
Google Sheets (CSV export por año: 1ro–7mo + preceptores + personal)
  → database.py: descargar_sheet() + cargar_desde_sheets()
  → escuela.db (SQLite: clases | horarios_preceptores | personal_no_docente)
  → app.py: rutas /api/* y /export/*
  → static/js/script.js: calendario, dashboard, PDF, comparación
```

**Archivos clave:**

| Archivo | Rol |
|---------|-----|
| `config.py` | SHEET_ID, GIDs por año, FLOOR_MAPPING, branding |
| `database.py` | Creación de tablas, descarga CSV, normalización |
| `app.py` | Rutas Flask |
| `templates/index.html` | Shell SPA — pasa `window.APP_DATA` al JS |
| `static/js/script.js` | Toda la lógica frontend (~1500 líneas) |
| `static/style.css` | Tema blueprint/industrial con CSS variables |
| `nombre_mapeos.json` | Correcciones manuales de nombres de docentes |

---

## API routes (app.py)

| Ruta | Método | Descripción |
|------|--------|-------------|
| `/` | GET | Sirve el SPA; pasa `datos`, `floor_mapping`, `dias`, branding |
| `/api/<tipo>/<valor>` | GET | Horario por `tipo` = `profesor\|aula\|curso\|planilla` |
| `/api/preceptor/<valor>` | GET | Preceptor asignado a un curso (T.M / T.T / T.N) |
| `/api/horario_preceptor/<nombre>` | GET | Horario personal de un preceptor |
| `/api/personal/<nombre>` | GET | Horario de personal no docente |
| `/api/dashboard` | GET | Todas las clases (el JS filtra por hora actual) |
| `/api/actualizar` | POST | Borra y reconstruye `escuela.db` desde Sheets |
| `/export/pdf/<tipo>/<valor>` | GET | Genera y devuelve PDF (landscape A4, fpdf2) |
| `/export/pdf/cursos/<seleccion>` | GET | PDF multipágina de cursos: `todos` o lista `1° A,2° B` |

**Lógica de búsqueda en `/api/<tipo>/<valor>`:**
- `profesor` → `WHERE profesor = ?`
- `aula` → `WHERE aula = ?`
- `curso` → parsea "1° A" → `WHERE curso='1' AND division='A'`
- `planilla` → parsea "Lunes|Piso 1" → `WHERE dia=? AND aula IN (rooms del floor)`

---

## Base de datos (database.py)

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

## Normalización de datos (database.py)

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

## PDF (app.py + fpdf2)

- Landscape A4, fuente Roboto Mono embedded
- Encabezado: nombre de búsqueda + info de preceptor (si es curso)
- Grid con horas a la izquierda y días (o aulas) como columnas
- Texto se trunca con ellipsis cuando no entra; prueba substrings más cortos
- Responde con MIME `application/pdf`; el browser lo abre en nueva pestaña

---

## Config (config.py)

```python
SHEET_ID = "1GJxwpxXfLosqKxgIa6zyZhwjDK-89ZDavLi6nouWTsw"
GIDS = {
    "1ro": "...", "2do": "...", ..., "7mo": "...",
    "horarios_preceptores": "...", "personal_no_docente": "..."
}
ESCUELA_NOMBRE = "EMILIO MITRE"
ESCUELA_LOGO   = "images/logoMitre.svg"
ESCUELA_VERSION = "V1.16"
DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
FLOOR_MAPPING = {
    "Piso 1": ["11","12",...],
    "Talleres": ["T1","T2",...],
    ...
}
```

Para cambiar la fuente de datos, editar `SHEET_ID` y/o los `GIDS`. No hay `.env`.

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

- **Hosting:** Render.com (free tier) + Cloudflare DNS
- `escuela.db` es efímero en Render; se regenera automáticamente al iniciar o via `/api/actualizar`
- `gunicorn app:app` para producción
- Ver `PLAN_HOSTING_GRATIS.txt` y `PLAN_ESCUELAS.md` para más detalles

---

## Flujos principales

1. **Consultar horario de curso:** Tab CURSOS → "1° A" → calendario semanal → click en bloque → modal con detalles
2. **Planilla de piso:** Tab AULAS → panel lateral → Planilla General → elegir piso + día → grid de aulas
3. **Actualizar datos:** Botón "ACTUALIZAR HORARIOS" → POST `/api/actualizar` → recarga página
4. **Comparar docentes:** Buscar docente → panel lateral → COMPARAR → buscar otro → grid multicolor
5. **Kiosco tiempo real:** Tab TIEMPO REAL → F11 → dashboard auto-actualizado cada 1s

---

## Context Rules

- Formato/contrato del Google Sheet (encabezados, layout de preceptores, plantilla para otras escuelas) → leer `PLANTILLA_SHEET.md`
- Lógica de normalización / pipeline de datos → leer `agent_docs/data-pipeline.md`
- Renderizado del calendario, clustering, superposición → leer `agent_docs/calendar-engine.md`
- Sistema de búsqueda y parsing de queries → leer `agent_docs/search-api.md`
- Estilos, variables CSS, patrones visuales → leer `agent_docs/frontend-ui.md`

## Dev Log

- `dev-log/DECISIONS.md` — decisiones de arquitectura. Leer antes de "corregir" algo que parece raro.
- `dev-log/CHANGELOG.md` — cambios que afectan contratos entre módulos.
- `dev-log/tasks/IN-PROGRESS.md` — leer al iniciar cualquier sesión.
- `dev-log/tasks/TODO.md` — backlog priorizado.
- `dev-log/tasks/DONE.md` — solo leer si se pide explícitamente.

**Agregar tarea:** Si el usuario pide agregar una tarea al backlog, editar directamente `dev-log/tasks/TODO.md` — leerlo, agregar la entrada con el siguiente número (#N+1), y actualizar la última línea `_Último número usado_`. Sin exploración previa, sin skills.

## Docs Maintenance

Después de cada modificación, antes de terminar la tarea, revisá:
- ¿Cambié el pipeline de datos, normalización o schema? → actualizar `agent_docs/data-pipeline.md`
- ¿Cambié lógica del calendario o clustering? → actualizar `agent_docs/calendar-engine.md`
- ¿Cambié rutas, búsqueda o parsing? → actualizar `agent_docs/search-api.md`
- ¿Cambié estilos o variables CSS? → actualizar `agent_docs/frontend-ui.md`
- ¿Cambió un contrato entre módulos? → agregar entrada en `dev-log/CHANGELOG.md`
- ¿Tomaste una decisión no obvia? → agregar entrada en `dev-log/DECISIONS.md`
- ¿Creaste, moviste o eliminaste un documento (`.md` de referencia)? → actualizar la referencia en `CLAUDE.md` (Context Rules o la sección que corresponda)
- Fixes menores de estilo o bugs internos → no registrar nada