# Plan de Generalización Multi-Escuela

## Principio rector

**El Google Sheet no define la estructura de la escuela. La app sí.**

El sheet es un volcado de datos crudos (filas de horarios). La app tiene su propia
configuración que determina cuántos cursos existen, qué turnos hay, qué horarios,
qué pisos, etc. Esa configuración se gestiona desde una página de administración en
la propia UI — sin tocar código ni archivos del servidor.

**Decisión [2026-07-13]**: la **estructura** del sheet es **fija por contrato**,
documentada en `PLANTILLA_SHEET.md`. Una escuela nueva copia la plantilla estándar y
carga sus datos — la app no adapta su parser a sheets con otro formato. Los parsers
de `database.py` se mantienen tal cual: clases y personal leen por nombre de encabezado
(`csv.DictReader`), preceptores por posición. Ver `dev-log/DECISIONS.md`.

---

## Diagnóstico: qué está acoplado hoy y dónde

### Capa de datos (Google Sheets → BD)

**~~Problema 1 — Parser por índice de columna~~ (ya no existe — verificado 2026-07-13)**
`cargar_desde_sheets()` y `cargar_personal_no_docente()` ya usan `csv.DictReader` con
encabezados normalizados: el orden de columnas es libre, el contrato son los nombres
de encabezado (fijados en `PLANTILLA_SHEET.md`). Riesgo residual aceptado: un
encabezado renombrado carga esa columna vacía sin error.

**~~Problema 2 — Parser de preceptores acoplado al layout del sheet~~ (aceptado — decisión 2026-07-13)**
`cargar_horarios_preceptores()` asume el layout por bloques (MAÑANA/TARDE/VESPERTINO
por offset). Ese layout pasa a ser parte de la plantilla estándar que toda escuela
debe respetar tal cual.

**Problema 3 — Mapeos de nombres de profesores hardcodeados**
`limpiar_profesor()` en `database.py` tiene correcciones de typos específicas de
profesores del Mitre (ej: "CASALE SERVIN BETTINA" → "CASALE SERVINI BETTINA").
Estos mapeos deben poder cargarse/editarse desde la UI de configuración, o al menos
desde un archivo JSON por institución ignorado por git.

**Problema 4 — Horarios comunes hardcodeados en código**
`corregir_horarios()` usa 12 horarios fijos del Mitre para completar datos incompletos
del sheet (cuando hora_inicio == hora_fin). Esos horarios deben venir de la configuración
de la escuela, no del código fuente.

---

### Capa de configuración (config.py)

Todo lo que está en `config.py` hoy es específico del Mitre y no hay forma de cambiarlo
desde la UI:

| Dato | Estado actual | Lo que debería ser |
|------|--------------|-------------------|
| `SHEET_ID` | hardcodeado | configurable desde UI admin |
| `GIDS` (1ro–7mo) | hardcodeado, asume 7 años | configurable: el admin define cuántos años hay y qué GID tiene cada uno |
| `FLOOR_MAPPING` | hardcodeado (7 categorías de pisos) | configurable desde UI: el admin define los pisos y qué aulas pertenecen a cada uno |
| `HORARIOS_COMUNES` | hardcodeado en database.py | configurable desde UI admin |
| Umbrales de turno (13:00, 18:00) | hardcodeados en database.py | configurables desde UI admin |
| Nombres de turno (T.M, T.T, T.N) | hardcodeados en app.py y script.js | configurables desde UI: el admin define cuántos turnos hay y cómo se llaman |
| Branding (nombre, logo) | hardcodeado en index.html | configurable desde UI |

---

### Capa de frontend (script.js, index.html)

**Problema 5 — Días de la semana en 6+ lugares distintos**
`["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]` aparece hardcodeado en al
menos 6 funciones del JS. No hay fuente única. Si una escuela quisiera incluir sábado,
habría que cambiar 6 lugares. Solución: vienen de `window.APP_DATA.config` (que proviene
de la config guardada en BD/server).

**Problema 6 — Acceso a datos por índice numérico**
El frontend accede a cada campo de una clase como `c[0]` (curso), `c[5]` (profesor),
`c[9]` (aula), `c[11]` (día), etc. Hay decenas de estas referencias en script.js.
Si el esquema de la BD cambia aunque sea un campo, la UI rompe silenciosamente.
La API debe devolver objetos JSON con claves nombradas.

**Problema 7 — Turnos asumidos (solo MAÑANA/TARDE/VESPERTINO)**
`renderizarTablaPreceptor()` asume exactamente 3 turnos en ese orden. La lógica de
renderizado de preceptores debe ser dinámica, leyendo los turnos desde la configuración.

**Problema 8 — Solo soporta grupos A y B**
La lógica de superposición de clases divide el espacio 50/50 asumiendo exactamente
2 grupos (A y B). Escuelas con divisiones C, D, etc. no renderizan correctamente.
Debe dividirse equitativamente entre todos los grupos detectados en el cluster.

**Problema 9 — Branding hardcodeado en HTML**
"EMILIO MITRE V1.16" y "logoMitre.jpg" están hardcodeados en `index.html`. Deben
venir de la configuración servida por el backend.

---

## Cambios pequeños (bajo esfuerzo, sin rediseño)

### ✅ P1 — Branding desde config al template
`ESCUELA_NOMBRE`, `ESCUELA_LOGO`, `ESCUELA_VERSION` en `config.py`.
`app.py` los pasa al template; `index.html` los consume con `{{ escuela_nombre }}` etc.

### ✅ P4 — Mapeos de nombres a archivo JSON externo
`nombre_mapeos.json` en el root (ignorado por git). `database.py` lo carga al iniciar.
Cada escuela tiene su propio archivo sin tocar código.

### ✅ P5 — Días de la semana desde APP_DATA
`DIAS` en `config.py`. Se pasa al template y queda en `window.APP_DATA.dias`.
En `script.js` los 5 lugares hardcodeados ahora referencian `window.APP_DATA.dias`.

### ~~P2 — Horarios comunes~~ (eliminado)
La función `corregir_horarios()` fue removida. El horario debe venir correcto
desde la planilla. Si `hora_inicio == hora_fin` en el sheet, se carga así.

### ~~P3 — Umbrales de turno~~ (eliminado)
La inferencia de turno por hora fue removida de `obtener_preceptores_por_curso()`.
El turno de cada curso será un dato explícito de configuración (ver E5).

---

## Cambios estructurales (mayor esfuerzo, necesarios para multi-escuela)

### E1 — Página de administración en la UI

Es el cambio más importante. Sin ella, nada de lo demás escala.

La app necesita una ruta `/admin` (protegida con clave simple o token) donde
el administrador de cada escuela pueda configurar:

- Nombre de institución / logo
- Google Sheet ID
- GIDs por año (agregar/quitar años dinámicamente)
- Pisos y aulas que pertenecen a cada piso (FLOOR_MAPPING)
- Horarios de las franjas (para corregir datos incompletos del sheet)
- Definición de turnos: cuántos hay, cómo se llaman, qué rango horario abarca cada uno
- Mapeos de nombres de profesores (tabla editable)

Toda esta configuración se persiste en una tabla `config` en SQLite:
```sql
CREATE TABLE config (
    clave TEXT PRIMARY KEY,
    valor TEXT   -- JSON serializado para valores complejos
);
```

El backend lee de esta tabla al arrancar y expone un endpoint `GET /api/config` que
sirve la config al frontend como parte de `window.APP_DATA.config`.

### ~~E2 — Parser de CSV por nombre de columna~~ (ya implementado / descartado como tarea)

Verificado 2026-07-13: `cargar_desde_sheets()` ya usa `csv.DictReader` — el parsing de
clases y personal es por nombre de encabezado. No queda trabajo pendiente; el contrato
de encabezados está documentado en `PLANTILLA_SHEET.md`.

### E3 — API devuelve objetos en lugar de arrays

Actualmente la API devuelve cada clase como array de 20 elementos. El frontend los
accede por índice (`c[5]` = profesor). Si el esquema cambia, rompe silenciosamente.

La API debe devolver objetos:
```json
{
  "curso": "4", "division": "A", "materia": "MATEMATICA",
  "profesor": "GARCIA JUAN", "aula": "14", "dia": "Lunes",
  "hora_inicio": "07:40", "hora_fin": "09:40",
  "grupo": "A", "superposicion": 0, "suplente_activo": 0, "prof_suplente": ""
}
```

En `script.js` reemplazar `c[5]` → `c.profesor`, `c[9]` → `c.aula`, etc.
Es el refactor de mayor esfuerzo pero la mayor ganancia en robustez y legibilidad.

### ~~E4 — Parser de preceptores con formato estándar~~ (descartado — decisión 2026-07-13)

Ya no es necesario: el layout por bloques (MAÑANA/TARDE/VESPERTINO por offset) es
parte de la plantilla estándar. El parser actual se mantiene sin cambios.

### E5 — Turnos configurables y renderizado dinámico

Eliminar los arrays hardcodeados de turnos en `script.js` y `app.py`. El número de
turnos, sus nombres y sus rangos horarios vienen de la config (tabla `config` en BD).
El renderizado de la tabla de preceptores itera sobre `config.turnos` en lugar de
asumir MAÑANA/TARDE/VESPERTINO.


### E7 — Años escolares dinámicos desde config

La cantidad de años (hoy exactamente 7: 1ro–7mo) debe ser un dato de configuración.
Al cargar el sheet se itera sobre los GIDs definidos en la config de la escuela, no
sobre una lista fija. La UI de admin permite agregar o quitar años.

---

## Lo que NO necesita cambiar

- El flujo general CSV → SQLite → API → JS es sólido y portable.
- Las funciones `limpiar_aula()` y `limpiar_profesor()` son genéricas salvo por los
  mapeos manuales (que van a config, ver P4).
- El calendario, el dashboard "En Vivo", la exportación PDF y el modo comparación
  no asumen nada del Mitre en su lógica central.
- La detección de superposiciones es portable (solo necesita extenderse para E6).
- El mecanismo de carga desde Google Sheets es reutilizable; solo cambian los IDs.
- Los parsers de `database.py`: clases y personal ya leen por nombre de encabezado
  (`csv.DictReader`); el de preceptores queda posicional por decisión 2026-07-13
  (estructura fija por contrato — ver `PLANTILLA_SHEET.md`).

---

## Orden de ataque recomendado

### ✅ Fase 1 — Limpiar hardcodes evidentes (sin rediseño) — COMPLETADA
- P1: Branding desde config al template
- P4: Mapeos de nombres a JSON externo
- P5: Días desde APP_DATA (fuente única)
- Removida `corregir_horarios()` — datos de horario deben venir correctos del sheet
- Removida inferencia de turno por hora — el turno será config explícita (E5)

### Fase 2 — Contrato de datos
5. ✅ Plantilla estándar del sheet documentada → `PLANTILLA_SHEET.md` (2026-07-13):
   pestañas, encabezados de clases, layout posicional de preceptores y formato de
   personal no docente
6. E3: API devuelve objetos (requiere actualizar script.js en paralelo) — TODO #3
7. ~~E2 y E4~~ descartados (decisión 2026-07-13): estructura fija por contrato.
   E2 ya estaba implementado (DictReader); el parser posicional de preceptores queda

### Fase 3 — Configuración desde la UI
8. E1: Página de administración + tabla `config` en BD — TODO #9
9. E5: Turnos configurables y renderizado dinámico — TODO #11
10. E7: Años escolares dinámicos desde config — TODO #10

