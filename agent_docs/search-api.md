# Sistema de Búsqueda y API — AppMitre

> Complementa `CLAUDE.md`. Backend en `horarios/rutas.py`, frontend en `script.js`.

---

## ⚡ Resolución client-side (desde [2026-06-29])

**Ninguna búsqueda pega al servidor** en el caso normal. Al cargar la web, `cargarDatosIniciales()` descarga **todo** a memoria con 3 requests en paralelo:
- `GET /horarios/api/dashboard` → `_allClases` (todas las filas de `clases`, ~2.300, con las columnas de `COLUMNAS_DASHBOARD`)
- `GET /horarios/api/personal_todos` → `_allPersonal` (todo el personal no docente)
- `GET /horarios/api/preceptores_data` → `_horariosPreceptores` (`{nombre: [filas]}`) + `_planillaPreceptores` (lista por curso con turnos)

A partir de ahí, profesor/aula/curso/planilla, horario individual de preceptor, preceptor-por-curso y la planilla de preceptores se resuelven **client-side**. Solo siguen yendo a la red: PDF export y `/horarios/api/actualizar`.

Resolución client-side por modo:
- `profesor`/`aula`/`curso`/`planilla` → `filtrarClasesLocal(modo, valor)`, que **replica la lógica de `obtener_filas()`** (ver queries abajo).
- `horario_preceptor` → lookup directo `_horariosPreceptores[nombre]`.
- preceptor-por-curso (tras buscar curso) → `obtenerPreceptorLocal(valor)`, que busca en `_planillaPreceptores`.

Si los datos aún no cargaron, cada camino hace **fallback** a su endpoint `/horarios/api/*` original.

⚠️ **Dos fuentes de verdad**: `obtener_filas()` (Python) y `filtrarClasesLocal()` (JS) deben mantenerse en sync. Si cambiás el parsing/filtrado de un lado, cambialo del otro. Ver `dev-log/DECISIONS.md` [2026-06-29].

`buscarEnServidor()` delega el render en `procesarResultadoBusqueda(modo, valor, filas)` (compartido entre caché y red). `allDataCache` (planilla general) y `lastDashboardData` (dashboard) se inicializan desde el mismo `_allClases`.

### Hash routing (URLs compartibles)

Las búsquedas `profesor`/`aula`/`curso`/`horario_preceptor` setean `location.hash` (ej: `#/profesor/MACIEL%20MARTIN`, `#/horario_preceptor/PEREZ%20JUAN`) via `history.replaceState`. El bloque `init()` al final de `script.js` lee el hash al cargar (tras `cargarDatosIniciales()`) y dispara la búsqueda. `cambiarTab()` limpia el hash.

**`#/comparar/...` — el modo comparación por URL**: `#/comparar/curso:1%C2%B0%20A,profesor:MACIEL%20MARTIN` abre el calendario con todo eso superpuesto (`abrirComparacionDesdeHash()`). Lo genera el asistente cuando corre `coincidencias` (ver `agente/enlaces.py`), y nada lo escribe de vuelta: en modo comparación `buscarEnServidor()` no toca el hash. Los pares van separados por `,` y cada valor va percent-encoded con `,` y `:` incluidos, así que `init()` lo desvía **antes** del `decodeURIComponent` general — decodificar primero rompería el split. Sólo `profesor`/`curso`/`aula` (los preceptores no son comparables) y hace falta un mínimo de dos.

**Deep-link de preceptor — cuidado con la race**: `tab-horario_preceptor` normalmente dispara `mostrarPlanillaCursos()` (fetch async que escribe en `contenedor-lista`), igual que `renderizarTablaPreceptor`. Para evitar que la planilla pise la tabla del preceptor en un deep-link, `cambiarTab()` **omite** `mostrarPlanillaCursos()` cuando `window.isProgrammaticNavigation` está activo (lo setea el `init()`): así `buscarEnServidor` renderiza directo la tabla del preceptor.

---

## Tipos de búsqueda y sus queries SQL

Todos los tipos pasan por `obtener_filas(tipo, valor)` en `horarios/rutas.py` **cuando van al server** (fallback). En el camino normal los resuelve `filtrarClasesLocal()` con la misma lógica.

### `profesor`

```sql
SELECT * FROM clases WHERE profesor = ?
```
El valor llega ya normalizado (sin acentos, mayúsculas) porque el autocompletado muestra los nombres tal como están en DB.

**Caso especial en el frontend**: buscar por profesor hace **dos requests en paralelo**:
1. `GET /horarios/api/profesor/{valor}` → clases de docentes
2. `GET /horarios/api/personal/{valor}` → filas de personal no docente

Los resultados se fusionan en el cliente. Las filas de personal se convierten al formato de objeto de clases mediante `personalToFila()`:
```js
{
  materia: p.rol,          // ej: "PORTERO"
  profesor: p.nombre,
  dia,                     // mapeado a title case
  hora_inicio: p.hora_inicio,
  hora_fin: p.hora_fin,
  tipo: 'personal'         // marker para distinguirlos en el renderizado
  // resto de claves de una fila de clases: vacías / 0
}
```
El marker `clase.tipo === 'personal'` se usa en `generarCalendario` para aplicar estilos distintos (fondo naranja claro).

### `aula`

```sql
SELECT * FROM clases WHERE aula = ?
```
Las aulas están normalizadas en DB (`limpiar_aula()`), así que la búsqueda es exacta.

### `curso`

```sql
-- Con división:
SELECT * FROM clases WHERE curso = ? AND division = ?
-- Sin división:
SELECT * FROM clases WHERE curso = ?
```

**Parsing del valor**: `valor.split(' ')` donde el valor viene como `"1 A"` (sin el símbolo °). La ruta `/horarios/api/<tipo>/<valor>` quita el `°` antes de llamar a `obtener_filas`:
```python
if tipo == 'curso' and '°' in valor:
    search_valor = valor.replace('°', '')
```
Entonces `"1° A"` → `search_valor = "1 A"` → `partes = ["1", "A"]` → `curso='1', division='A'`.

En el frontend, `seleccionarOpcion` pasa el valor sin transformar (ej: `"1° A"`) y la API limpia el `°`.

### `planilla`

```sql
SELECT * FROM clases WHERE dia = ? AND aula IN (?, ?, ...)
```

El valor tiene formato `"Lunes|Piso 1"`. Parsing:
```python
dia, piso = valor.split('|')
aulas = FLOOR_MAPPING.get(piso, [])
placeholders = ','.join(['?'] * len(aulas))
query = f"SELECT * FROM clases WHERE dia = ? AND aula IN ({placeholders})"
cur.execute(query, [dia] + aulas)
```

Si el piso no existe en `FLOOR_MAPPING` → `aulas = []` → la query nunca se ejecuta → devuelve `[]`.

### `preceptor` (`/horarios/api/preceptor/<valor>`)

No pasa por `obtener_filas`. Consulta directa a `horarios.datos.obtener_preceptores_por_curso`:
```sql
SELECT turno, GROUP_CONCAT(DISTINCT preceptor) AS nombres
FROM horarios_preceptores
WHERE curso = ? AND UPPER(division) = ?
GROUP BY turno
```

Devuelve `{curso, division, preceptores_manana, preceptores_tarde, preceptores_vespertino, turno}` o `null`. El campo `turno` ("MAÑANA"/"TARDE"/"VESPERTINO") se agrega en la ruta desde `TURNO_CURSOS`. Se llama automáticamente después de una búsqueda por curso para mostrar el info de preceptores en el header del calendario.

**Parsing del valor**: usa `split(' ', 1)` para soportar divisiones multi-parte (ej: "6 4° C" → curso='6', division='4° C'). No eliminar el símbolo `°` porque es parte de la clave en `TURNO_CURSOS` y en la DB.

⚠️ **Bug preexistente del campo `turno`**: la ruta hace `data['turno'] = TURNO_CURSOS.get((curso, division))` con `curso` **conservando el `°`** (ej: `"1°"`), pero las claves de `TURNO_CURSOS` NO tienen `°` (`('1','A')`) → el lookup nunca matchea y devuelve siempre `TURNO_DEFAULT` ("MAÑANA"). Desde [2026-06-29] el frontend usa `obtenerPreceptorLocal()` (deriva el turno de `_planillaPreceptores`, que sí computa el turno correcto con `curso` sin `°`), así que en el camino cacheado el "PRECEPTOR PRINCIPAL" se marca según el turno real del curso. El endpoint sigue con el bug (solo se usa como fallback).

### `horario_preceptor` (`/horarios/api/horario_preceptor/<nombre>`)

```sql
SELECT turno, preceptor, tipo, curso, dia
FROM horarios_preceptores
WHERE preceptor LIKE ?
ORDER BY turno, tipo, curso, CASE dia WHEN 'LUNES' THEN 1 ... END
```
Usa `LIKE %nombre%` (fuzzy, no exacto). El resultado se renderiza como tabla (`renderizarTablaPreceptor`), no como calendario.

### `personal` (`/horarios/api/personal/<nombre>`)

```sql
SELECT nombre, rol, dia, hora_inicio, hora_fin
FROM personal_no_docente WHERE nombre = ?
```
Exacto. Solo se usa como **fallback** cuando el modo es `profesor` y los datos aún no se cachearon. En el camino normal, el personal sale de `_allPersonal` (cacheado).

### `personal_todos` (`/horarios/api/personal_todos`)

```sql
SELECT nombre, rol, dia, hora_inicio, hora_fin
FROM personal_no_docente ORDER BY nombre, dia
```
Devuelve **todo** el personal no docente (mismo formato de objeto que `/horarios/api/personal/<nombre>`). Se llama una vez al cargar la web desde `cargarDatosIniciales()` para poblar `_allPersonal`.

### `cursos` — PDF múltiple (`/horarios/export/pdf/cursos/<seleccion>`)

Genera **un solo PDF con una página landscape A4 por curso**. `seleccion` puede ser:
- `todos` → todos los cursos (`SELECT DISTINCT curso, division FROM clases WHERE curso != '' ORDER BY curso, division`, misma query que `index()`).
- Lista separada por comas de valores estilo `"1° A"` (ej: `1° A,2° B`), en el orden recibido. Cada valor pasa por el mismo camino que `/horarios/export/pdf/curso/<valor>`.
- Vacía/solo espacios → `400`.

No colisiona con `/horarios/export/pdf/<tipo>/<valor>`: Werkzeug prioriza el segmento estático `cursos` sobre el convertidor `<tipo>`.

**Refactor asociado**: el dibujo de una página de calendario se extrajo de `export_pdf` a `dibujar_pagina_horario(pdf, tipo, valor)` (+ `_crear_pdf_horario()` que crea el PDF y registra las fuentes). Ambas rutas de export lo reusan.

En el frontend, el selector es un modal (botón IMPRIMIR VARIOS en el slide-panel de CURSOS → `abrirModalImprimirCursos()`); si la selección está completa manda `todos`, si no la lista en el orden de `rawData['curso']`.

---

## `window.APP_DATA` — contrato entre Flask y el JS

Inyectado en el template como:
```html
<script>
window.APP_DATA = {
    rawData: {{ datos | tojson | safe }},
    floorMapping: {{ floor_mapping | tojson | safe }},
    dias: {{ dias | tojson | safe }},
};
</script>
```

### `rawData` — estructura

```js
{
    "profesor": ["APELLIDO NOMBRE", ...],          // distinct, ordenado
    "aula": ["101", "102", "T1", "PATIO", ...],    // distinct, ordenado
    "curso": ["1° A", "1° B", "2° A", ...],        // con ° y espacio
    "horario_preceptor": ["Pérez Juan", ...],       // nombres raw de la tabla
    "personal": [{"nombre": "...", "rol": "..."}, ...]
}
```

**Por qué todo junto al cargar la página en lugar de requests por demanda:**
El autocompletado requiere filtrado en el cliente con cada keystroke. Hacer un request al servidor por cada tecla introduciría latencia perceptible. Con ~200–300 profesores, el payload es pequeño (<50KB JSON). Ver decisión en `dev-log/DECISIONS.md`.

### `floorMapping` — origen

Viene directamente de `FLOOR_MAPPING` en `config.py`. Es el contrato entre el selector de piso en la Planilla General y las queries SQL.

### `dias` — fuente única

Viene de `DIAS` en `config.py` (`["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]`). Todos los calendarios itaran sobre `window.APP_DATA.dias` — no hay días hardcodeados en el JS (fue corregido en Fase 1 de `PLAN_ESCUELAS.md`).

---

## Autocompletado — `filtrarOpciones(input, modo)`

### Función `normalize(text)` del frontend

```js
normalize(text) → lowercase → NFD decompose → quitar diacríticos → quitar espacios → quitar °
```

Ejemplo: `"1° A"` → `"1a"`, `"García"` → `"garcia"`, `"Miércoles"` → `"miercoles"`.

### Lógica de filtrado

Para todos los modos excepto `profesor`:
1. Si query vacía → mostrar todos.
2. Si hay query → filtrar con `normalize(item).includes(normalizedQuery)`.
3. Ordenar: primeros los que empiezan con el query, después los que contienen.
4. Enter → selecciona el primer resultado.

Para `profesor` (modo especial):
1. Combina la lista `rawData.profesor` con `rawData.personal` en un map por nombre normalizado.
2. Si un nombre aparece en ambas listas (docente que también es personal no docente), se fusiona en un solo item con badge de rol.
3. Muestra el badge `<span class="rol-badge">ROL</span>` junto al nombre cuando es personal.
4. Filtra por nombre O por rol (ej: buscar "portero" encuentra al portero).

### Casos edge del autocompletado

- **Nombres con acentos en el input**: funcionan porque tanto la query como los items se normalizan.
- **Buscar "1 A" vs "1° A"**: `normalize("1° A") = "1a"` y `normalize("1 A") = "1a"` → ambos matchean.
- **El dropdown cierra** al hacer click fuera (listener global en `document`). Un click dentro del input que ya tiene el dropdown abierto intenta reabrirlo via `dispatchEvent(new Event('focus'))` — esto puede causar flickers en algunos browsers.
- **El autocompletado para `horario_preceptor`** usa la misma función `filtrarOpciones` pero con datos de `rawData.horario_preceptor` (lista de strings de nombres de preceptores).

---

## `/horarios/api/actualizar` — POST, sin permiso extra

```python
@bp.route('/api/actualizar', methods=['POST'])   # bp con url_prefix='/horarios'
def api_actualizar():
```

Borra y reconstruye `escuela.db` entera desde Google Sheets. Detrás del login de horarios
(como todo `/horarios/*`), pero sin permiso extra: en un deploy nuevo la DB nace vacía y el
que la puebla no siempre es admin. Lo único que la separa de un GET es que es **POST**, para
que no la dispare un crawler ni el prefetch del navegador. El `fetch` de `script.js` manda
`{ method: 'POST' }` y el `.then` lee la respuesta JSON (`status: success|error`).

---

## Ruta `/horarios/api/planilla_preceptores`

Devuelve la tabla completa de preceptores por curso para la pestaña PRECEPTORES:
```python
for f in filas:
    f['turno'] = TURNO_CURSOS.get((str(f['curso']), str(f['division'])), TURNO_DEFAULT)
```

`TURNO_CURSOS` en `config.py` está poblado con todos los cursos de 1° a 7°. Los valores posibles son `"MAÑANA"`, `"TARDE"`, `"VESPERTINO"`. Los cursos de 6° y 7° son mayormente vespertinos. La planilla JSON devuelve `{curso, division, turno, manana, tarde, vespertino}` — **el campo es `vespertino`, no `noche`**.

---

## Formato de fila: objetos con claves nombradas (desde [2026-07-13])

La API devuelve cada clase como **objeto JSON** con claves nombradas (`sqlite3.Row` → `dict`). `obtener_filas()` expone la tabla `clases` entera:

```
{curso, division, especialidad, materia, tipo_materia, profesor, dni, telefono, email,
 aula, tipo_aula, dia, hora_inicio, hora_fin, grupo, superposicion, suplente_activo,
 prof_suplente, sup_ini, sup_fin}
```

`/horarios/api/dashboard` devuelve **un subconjunto**, el declarado en `COLUMNAS_DASHBOARD` (`horarios/rutas.py`) — las 14 que el frontend realmente lee:

```
{curso, division, materia, profesor, aula, dia, hora_inicio, hora_fin, grupo,
 superposicion, suplente_activo, prof_suplente, sup_ini, sup_fin}
```

Quedan afuera `especialidad`, `tipo_materia` y `tipo_aula` (nadie las usa) y `dni`, `telefono` y `email` (datos personales de los docentes que no tienen por qué viajar al navegador). Este endpoint manda las 2.300 filas de una, así que cada columna de más se paga entera: recortarlo bajó el JSON de 804 KB a 586 KB. **Si el frontend empieza a usar otra columna, hay que sumarla a `COLUMNAS_DASHBOARD`.**

- El frontend accede por clave (`f.profesor`, `f.aula`, `f.hora_inicio`, ...). No queda ningún acceso por índice a filas de clases.
- El código del PDF en `horarios/rutas.py` (`obtener_datos_calendario`, `dibujar_pagina_horario`) consume el mismo formato.
- Las filas sintéticas de `personalToFila()` agregan la clave extra `tipo: 'personal'`.
- Agregar una columna a la tabla `clases` la expone automáticamente en `obtener_filas()` sin romper el frontend (E3 de `PLAN_ESCUELAS.md`, completado 2026-07-13). En `/api/dashboard` no: ahí hay que sumarla a `COLUMNAS_DASHBOARD`.
