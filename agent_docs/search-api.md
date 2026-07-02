# Sistema de Búsqueda y API — AppMitre

> Complementa `CLAUDE.md`. Backend en `app.py`, frontend en `script.js`.

---

## ⚡ Resolución client-side (desde [2026-06-29])

**Ninguna búsqueda pega al servidor** en el caso normal. Al cargar la web, `cargarDatosIniciales()` descarga **todo** a memoria con 3 requests en paralelo:
- `GET /api/dashboard` → `_allClases` (todas las filas de `clases`, ~2.300)
- `GET /api/personal_todos` → `_allPersonal` (todo el personal no docente)
- `GET /api/preceptores_data` → `_horariosPreceptores` (`{nombre: [filas]}`) + `_planillaPreceptores` (lista por curso con turnos)

A partir de ahí, profesor/aula/curso/planilla, horario individual de preceptor, preceptor-por-curso y la planilla de preceptores se resuelven **client-side**. Solo siguen yendo a la red: PDF export y `/api/actualizar`.

Resolución client-side por modo:
- `profesor`/`aula`/`curso`/`planilla` → `filtrarClasesLocal(modo, valor)`, que **replica la lógica de `obtener_filas()`** (ver queries abajo).
- `horario_preceptor` → lookup directo `_horariosPreceptores[nombre]`.
- preceptor-por-curso (tras buscar curso) → `obtenerPreceptorLocal(valor)`, que busca en `_planillaPreceptores`.

Si los datos aún no cargaron, cada camino hace **fallback** a su endpoint `/api/*` original.

⚠️ **Dos fuentes de verdad**: `obtener_filas()` (Python) y `filtrarClasesLocal()` (JS) deben mantenerse en sync. Si cambiás el parsing/filtrado de un lado, cambialo del otro. Ver `dev-log/DECISIONS.md` [2026-06-29].

`buscarEnServidor()` delega el render en `procesarResultadoBusqueda(modo, valor, filas)` (compartido entre caché y red). `allDataCache` (planilla general) y `lastDashboardData` (dashboard) se inicializan desde el mismo `_allClases`.

### Hash routing (URLs compartibles)

Las búsquedas `profesor`/`aula`/`curso`/`horario_preceptor` setean `location.hash` (ej: `#/profesor/MACIEL%20MARTIN`, `#/horario_preceptor/PEREZ%20JUAN`) via `history.replaceState`. El bloque `init()` al final de `script.js` lee el hash al cargar (tras `cargarDatosIniciales()`) y dispara la búsqueda. `cambiarTab()` limpia el hash.

**Deep-link de preceptor — cuidado con la race**: `tab-horario_preceptor` normalmente dispara `mostrarPlanillaCursos()` (fetch async que escribe en `contenedor-lista`), igual que `renderizarTablaPreceptor`. Para evitar que la planilla pise la tabla del preceptor en un deep-link, `cambiarTab()` **omite** `mostrarPlanillaCursos()` cuando `window.isProgrammaticNavigation` está activo (lo setea el `init()`): así `buscarEnServidor` renderiza directo la tabla del preceptor.

---

## Tipos de búsqueda y sus queries SQL

Todos los tipos pasan por `obtener_filas(tipo, valor)` en `app.py` **cuando van al server** (fallback). En el camino normal los resuelve `filtrarClasesLocal()` con la misma lógica.

### `profesor`

```sql
SELECT * FROM clases WHERE profesor = ?
```
El valor llega ya normalizado (sin acentos, mayúsculas) porque el autocompletado muestra los nombres tal como están en DB.

**Caso especial en el frontend**: buscar por profesor hace **dos requests en paralelo**:
1. `GET /api/profesor/{valor}` → clases de docentes
2. `GET /api/personal/{valor}` → filas de personal no docente

Los resultados se fusionan en el cliente. Las filas de personal se convierten al formato de array-21 de clases mediante `personalToFila()`:
```js
row[3]  = p.rol         // "materia" = rol (ej: "PORTERO")
row[5]  = p.nombre      // "profesor" = nombre
row[11] = dia (mapeado a title case)
row[12] = hora_inicio
row[13] = hora_fin
row[20] = 'personal'    // marker para distinguirlos en el renderizado
```
El marker `row[20] === 'personal'` se usa en `generarCalendario` para aplicar estilos distintos (fondo naranja claro).

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

**Parsing del valor**: `valor.split(' ')` donde el valor viene como `"1 A"` (sin el símbolo °). La ruta `/api/<tipo>/<valor>` quita el `°` antes de llamar a `obtener_filas`:
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

### `preceptor` (`/api/preceptor/<valor>`)

No pasa por `obtener_filas`. Consulta directa a `database.obtener_preceptores_por_curso`:
```sql
SELECT turno, GROUP_CONCAT(DISTINCT preceptor) AS nombres
FROM horarios_preceptores
WHERE curso = ? AND UPPER(division) = ?
GROUP BY turno
```

Devuelve `{curso, division, preceptores_manana, preceptores_tarde, preceptores_vespertino, turno}` o `null`. El campo `turno` ("MAÑANA"/"TARDE"/"VESPERTINO") se agrega en la ruta desde `TURNO_CURSOS`. Se llama automáticamente después de una búsqueda por curso para mostrar el info de preceptores en el header del calendario.

**Parsing del valor**: usa `split(' ', 1)` para soportar divisiones multi-parte (ej: "6 4° C" → curso='6', division='4° C'). No eliminar el símbolo `°` porque es parte de la clave en `TURNO_CURSOS` y en la DB.

⚠️ **Bug preexistente del campo `turno`**: la ruta hace `data['turno'] = TURNO_CURSOS.get((curso, division))` con `curso` **conservando el `°`** (ej: `"1°"`), pero las claves de `TURNO_CURSOS` NO tienen `°` (`('1','A')`) → el lookup nunca matchea y devuelve siempre `TURNO_DEFAULT` ("MAÑANA"). Desde [2026-06-29] el frontend usa `obtenerPreceptorLocal()` (deriva el turno de `_planillaPreceptores`, que sí computa el turno correcto con `curso` sin `°`), así que en el camino cacheado el "PRECEPTOR PRINCIPAL" se marca según el turno real del curso. El endpoint sigue con el bug (solo se usa como fallback).

### `horario_preceptor` (`/api/horario_preceptor/<nombre>`)

```sql
SELECT turno, preceptor, tipo, curso, dia
FROM horarios_preceptores
WHERE preceptor LIKE ?
ORDER BY turno, tipo, curso, CASE dia WHEN 'LUNES' THEN 1 ... END
```
Usa `LIKE %nombre%` (fuzzy, no exacto). El resultado se renderiza como tabla (`renderizarTablaPreceptor`), no como calendario.

### `personal` (`/api/personal/<nombre>`)

```sql
SELECT nombre, rol, dia, hora_inicio, hora_fin
FROM personal_no_docente WHERE nombre = ?
```
Exacto. Solo se usa como **fallback** cuando el modo es `profesor` y los datos aún no se cachearon. En el camino normal, el personal sale de `_allPersonal` (cacheado).

### `personal_todos` (`/api/personal_todos`)

```sql
SELECT nombre, rol, dia, hora_inicio, hora_fin
FROM personal_no_docente ORDER BY nombre, dia
```
Devuelve **todo** el personal no docente (mismo formato de objeto que `/api/personal/<nombre>`). Se llama una vez al cargar la web desde `cargarDatosIniciales()` para poblar `_allPersonal`.

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

## `/api/actualizar` — nota importante

La ruta está decorada sin `methods` explícitos:
```python
@app.route('/api/actualizar')
def api_actualizar():
```

Flask por default acepta solo GET para rutas sin `methods`. El botón en el frontend usa `fetch('/api/actualizar')` sin `method: 'POST'`. Por lo tanto esta ruta es **GET**, no POST como dice el `CLAUDE.md`.

Semánticamente debería ser POST (es una operación con efecto secundario), pero cambiar a POST requeriría actualizar tanto el backend como el fetch en el JS.

---

## Ruta `/api/planilla_preceptores`

Devuelve la tabla completa de preceptores por curso para la pestaña PRECEPTORES:
```python
for f in filas:
    f['turno'] = TURNO_CURSOS.get((str(f['curso']), str(f['division'])), TURNO_DEFAULT)
```

`TURNO_CURSOS` en `config.py` está poblado con todos los cursos de 1° a 7°. Los valores posibles son `"MAÑANA"`, `"TARDE"`, `"VESPERTINO"`. Los cursos de 6° y 7° son mayormente vespertinos. La planilla JSON devuelve `{curso, division, turno, manana, tarde, vespertino}` — **el campo es `vespertino`, no `noche`**.

---

## Acceso a filas por índice numérico (deuda técnica)

El frontend accede a todos los campos de una clase como `f[N]` donde N es la posición en el SELECT *:

| Índice | Campo |
|---|---|
| 0 | curso |
| 1 | division |
| 2 | especialidad |
| 3 | materia |
| 4 | tipo_materia |
| 5 | profesor |
| 6 | dni |
| 7 | telefono |
| 8 | email |
| 9 | aula |
| 10 | tipo_aula |
| 11 | dia |
| 12 | hora_inicio |
| 13 | hora_fin |
| 14 | grupo |
| 15 | superposicion |
| 16 | suplente_activo |
| 17 | prof_suplente |
| 18 | sup_ini |
| 19 | sup_fin |
| 20 | (solo en personalToFila) marker 'personal' |

Cambiar el orden de columnas en la tabla o el SELECT rompe todo el frontend silenciosamente. Documentado como E3 en `PLAN_ESCUELAS.md`.
