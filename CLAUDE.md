# CLAUDE.md

## Qué es esta app

**AppMitre** son **cuatro áreas** sobre el mismo Flask, para la **Escuela Técnica Emilio Mitre**. Cada una tiene su archivo, su prefijo de URL y (las que tienen datos propios) **su propia DB, sin FK que crucen de una a otra**.

| Área | URL | Archivo | DB | Qué es |
|---|---|---|---|---|
| **Horarios** | `/` | `app.py` + `database.py` | `escuela.db` | Consulta de horarios por curso (1°–7°), profesor, aula y preceptor; dashboard "En Vivo" para kiosco; export a PDF. Se regenera desde Google Sheets. |
| **Gestión de recursos** | `/gestion` | `gestion.py` | `gestion.db` | Inventario técnico: recursos, conjuntos, actividades y préstamos. |
| **Historia institucional** | `/historia` | `historia.py` | `historia.db` | Línea del tiempo: hitos y las personas que hicieron la escuela. |
| **Asistente** | `/agente` | `agente/` (paquete) | (usa las de arriba) | Chat con tool-calling. Único transversal: **lee las tres** y escribe en recursos e historia. |

**Quién entra a qué — tres niveles** (detalle en `agent_docs/accesos.md`): **Público** es el SPA de horarios, abierto. **Interno** son dispositivos habilitados por un link de invitación de un solo uso, cada uno con su conjunto de permisos (`gestion.leer`, `agente.escribir`, …). **Admin** entra con `GESTION_CLAVE` y tiene el comodín `'*'`. Un área declara sus `PERMISOS` y entra sola al catálogo y a los perfiles: agregar un área nueva **no toca el gate ni migra los accesos ya dados**.

### Dónde va cada cosa: tres capas

Las áreas **no duplican código**: comparten un motor. Las dependencias van siempre hacia arriba y **la capa 1 nunca importa un área** — las recibe como argumento.

```
capa 2   gestion.py   historia.py   database.py+app.py   agente/       ← nombran tablas reales
capa 1      crud.py + templates/crud/   ·   accesos.py                 ← saben "entidad" y "permiso",
                                                                         no cuáles
capa 0        config.py    texto.py    respaldos.py                    ← no nombran nada del dominio
```

**La pregunta para ubicar cualquier función es una sola: ¿qué nombra?** Si nombra una tabla, un slug o una ruta, es del área y quien la necesite la importa de ahí. Si no nombra nada del dominio, sube. Lo específico de un área entra al motor por **hooks declarados** (`migrar`, `seed`, `derivados`, `secciones_detalle`, …), nunca por un `if slug == '...'` dentro de `crud.py`. Detalle completo en `agent_docs/crud-motor.md`.

También se comparte lo que no es lógica de dominio: `static/gestion.css` (paleta), `static/gestion-agente.js`, `static/mobile-nav.js` (menú lateral de celular) y el widget del chat.

**Usuarios principales:** alumnos, docentes, preceptores y administración.  
**Stack:** Flask + SQLite + Vanilla JS (sin frameworks). Sin tests, sin linter, sin build step.

---

## Commands

```bash
pip install -r requirements.txt   # instalar dependencias
python app.py                      # dev en http://localhost:5000
gunicorn app:app                   # producción
# POST /api/actualizar             # regenerar DB desde Google Sheets

python actualizar.py --dry-run     # deploy: qué le falta a las DB del server (no escribe)
python actualizar.py               # aplicarlo, antes del Reload del web app
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
| `config.py` | SHEET_ID, GIDs por año, FLOOR_MAPPING, branding y `ahora()` — el reloj de la escuela (capa 0). Nadie llama a `datetime.now()`: el server de producción corre en UTC |
| `texto.py` | Normalización de texto y búsqueda difusa (capa 0). Único dueño de `UMBRAL_SIMILITUD` |
| `respaldos.py` | Respaldos rotativos de SQLite, parametrizados por área (capa 0) |
| `crud.py` | Motor CRUD genérico + rutas (capa 1). No importa ningún área |
| `accesos.py` | Motor de accesos y permisos (capa 1), hermano de `crud.py`: gate, catálogo de permisos, perfiles, links de invitación y panel `/accesos`. DB propia `accesos.db`. No nombra ningún permiso de área |
| `actualizar.py` | Script de consola para el deploy: pone al día una `gestion.db`/`historia.db` vieja. Hace lo que `migrar()` no puede porque cruza las dos DBs (mudanza de hitos/personas, `proyectos` → hitos) y limpia tablas y columnas que el código ya no declara. Idempotente, con `--dry-run` |
| `database.py` | Creación de tablas, descarga CSV, normalización |
| `app.py` | Rutas Flask |
| `templates/index.html` | Shell SPA — pasa `window.APP_DATA` al JS |
| `static/js/script.js` | Toda la lógica frontend (~1500 líneas) |
| `static/style.css` | Tema blueprint/industrial con CSS variables |
| `nombre_mapeos.json` | Correcciones manuales de nombres de docentes |
| `gestion.py` | Gestión de recursos (`/gestion`): declara sus entidades y hooks + préstamos/carrito propio |
| `historia.py` | Historia institucional (`/historia`): declara sus entidades y hooks (`derivados`, `clave_persona`) |
| `agente/` | Asistente conversacional (`/agente`): paquete con blueprint, tools, prompt y loop + templates en `templates/agente/`. Expone `bp` e `init_db`; el mapa de los módulos está en `agente/__init__.py` |
| `templates/crud/` | `lista/form/detalle/login.html` genéricos; cada área deja un stub que los extiende |
| `static/mobile-nav.js` | Menú lateral ocultable de celular para `/gestion`, `/historia` y `/agente` (≤900px). No toca escritorio |

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

- **Hosting:** PythonAnywhere (WSGI) + Cloudflare DNS. Antes fue Render.com — ver `dev-log/DECISIONS.md` 2026-06-25
- **Los `.db` persisten entre deploys** y están en `.gitignore`: `git pull` nunca los pisa. `escuela.db` es la excepción que no importa (se regenera desde Sheets al iniciar o via `/api/actualizar`); `gestion.db`, `historia.db` y `accesos.db` son la fuente de verdad y sólo tienen los respaldos de `respaldos.py`
- **Deploy:** `git pull` → `pip install -r requirements.txt` → `python actualizar.py --dry-run` → `python actualizar.py` → Reload del web app. Las variables de entorno (`SECRET_KEY`, `GESTION_CLAVE`, las API keys del agente) van en el `.env` del servidor, que tampoco viaja por git
- **`SECRET_KEY` y `GESTION_CLAVE` son obligatorias en producción**: sin ellas la app no arranca (`config.PRODUCCION` las exige cuando detecta `PYTHONANYWHERE_DOMAIN`). En local caen a un default de desarrollo con un aviso por consola. Ojo: **cambiar `GESTION_CLAVE` cierra todas las sesiones de admin** (es el botón de pánico) y **rotar `SECRET_KEY` desloguea también a todos los dispositivos**, que hay que volver a invitar
- **La primera vez, `accesos.db` nace vacía**: no hay ningún dispositivo habilitado y el único acceso es el de administración con `GESTION_CLAVE`. Desde `/accesos` se invita al resto. La crea sola `accesos.init_db()`, tanto al arrancar como desde `actualizar.py`
- `gunicorn app:app` para producción en hostings que no sean PythonAnywhere
- Ver `PLAN_ESCUELAS.md` y `AGENTE_CONFIG.md` para más detalles

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
- Motor CRUD compartido, criterio de capas, contrato de área, hooks, templates genéricos (`crud.py`, `texto.py`, `respaldos.py`, `templates/crud/`) → leer `agent_docs/crud-motor.md`
- Quién puede entrar a qué: los tres niveles (público/interno/admin), permisos por área, links de invitación y dispositivos (`accesos.py`, `accesos.db`, `/accesos`) → leer `agent_docs/accesos.md`
- Gestión de recursos (`/gestion`, `gestion.py`, `gestion.db`) → leer `agent_docs/gestion-conocimiento.md`
- Historia institucional (`/historia`, `historia.py`, `historia.db`: hitos y personas) → leer `agent_docs/historia-institucional.md`
- Asistente conversacional (`/agente`, paquete `agente/`, tools, fichas de confirmación, fotos) → leer `agent_docs/agente-asistente.md`
- Historias narradas por Emilio (`historias/*.json`, lore — NO confundir con `/historia`): cómo agregar, campos, tonos y estilos → leer `HISTORIAS_PROCEDIMIENTO.md`

## Dev Log

- `dev-log/DECISIONS.md` — decisiones de arquitectura. Leer antes de "corregir" algo que parece raro.
- `dev-log/CHANGELOG.md` — cambios que afectan contratos entre módulos.
- `dev-log/tasks/IN-PROGRESS.md` — leer al iniciar cualquier sesión.
- `dev-log/tasks/TODO.md` — backlog priorizado.
- `dev-log/tasks/DONE.md` — solo leer si se pide explícitamente.

**Agregar tarea:** Si el usuario pide agregar una tarea al backlog, editar directamente `dev-log/tasks/TODO.md` — leerlo, agregar la entrada con el siguiente número (#N+1), y actualizar la última línea `_Último número usado_`. Sin exploración previa, sin skills.

## Docs Maintenance

Actualizar la doc **es parte de la tarea, no un paso opcional**: siempre que un cambio caiga en alguno de estos casos, reflejalo en el `.md` que corresponde **antes de terminar y antes de commitear** (no lo dejes para después). Si tocaste código de un módulo que tiene doc en `agent_docs/`, esa doc se actualiza sí o sí.
- ¿Cambié el pipeline de datos, normalización o schema de `escuela.db`? → actualizar `agent_docs/data-pipeline.md`
- ¿Cambié lógica del calendario o clustering? → actualizar `agent_docs/calendar-engine.md`
- ¿Cambié rutas, búsqueda o parsing del SPA de horarios (`app.py` / `script.js`)? → actualizar `agent_docs/search-api.md`
- ¿Cambié estilos o variables CSS del SPA? → actualizar `agent_docs/frontend-ui.md`
- ¿Cambié algo de Gestión de recursos (`/gestion`, `gestion.py`, rutas/búsqueda/schema de `gestion.db`, templates de `gestion/`, `gestion.css`, o JS propio del módulo)? → actualizar `agent_docs/gestion-conocimiento.md`
- ¿Cambié algo de Historia institucional (`/historia`, `historia.py`, schema de `historia.db`, templates de `historia/`)? → actualizar `agent_docs/historia-institucional.md`
- ¿Cambié algo del Asistente (paquete `agente/`, tools, prompts, `templates/agente/`, `gestion-agente.js`)? → actualizar `agent_docs/agente-asistente.md`
- ¿Cambié el motor compartido (`crud.py`, `texto.py`, `respaldos.py`, `templates/crud/`), el contrato de área o sus hooks? → actualizar `agent_docs/crud-motor.md`
- ¿Cambié quién puede entrar a qué (`accesos.py`, permisos de un área, el panel `/accesos`, el canje de invitaciones)? → actualizar `agent_docs/accesos.md`
- ¿Agregué código compartido entre áreas? → pasarlo antes por el filtro de capas de `agent_docs/crud-motor.md`: si nombra una tabla o un slug, no es compartido
- ¿Cambió un contrato entre módulos? → agregar entrada en `dev-log/CHANGELOG.md`
- ¿Tomaste una decisión no obvia? → agregar entrada en `dev-log/DECISIONS.md`
- ¿Creaste, moviste o eliminaste un documento (`.md` de referencia)? → actualizar la referencia en `CLAUDE.md` (Context Rules o la sección que corresponda)
- Fixes menores de estilo o bugs internos → no registrar nada

## Fin de sesión

Si el usuario pide "terminar/cerrar la sesión": repasar todo lo hecho en la sesión y guardar lo que falte en los `.md` antes de despedirse:
1. Pasar el checklist de **Docs Maintenance** (arriba) sobre los cambios de la sesión.
2. Mover el trabajo terminado a `dev-log/tasks/DONE.md` (newest-first, arriba).
3. Registrar pendientes nuevos que hayan surgido como tareas en `TODO.md` (numeradas, actualizar `_Último número usado_`).
4. Si quedó algo a medias, dejarlo asentado en `IN-PROGRESS.md` con estado y próximo paso; si no, verificar que quede vacío.
5. No commitear salvo pedido explícito.