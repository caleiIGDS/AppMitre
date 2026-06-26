# Sistema de Búsqueda y API — AppMitre

> Complementa `CLAUDE.md`. Backend en `app.py`, frontend en `script.js`.

---

## Tipos de búsqueda y sus queries SQL

Todos los tipos pasan por `obtener_filas(tipo, valor)` en `app.py`.

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

Devuelve `{curso, division, preceptores_manana, preceptores_tarde, preceptores_noche}` o `null`. Se llama automáticamente después de una búsqueda por curso para mostrar el info de preceptores en el header del calendario.

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
Exacto. Solo se llama desde `buscarEnServidor` cuando el modo es `profesor` (en paralelo con la búsqueda de clases).

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

`TURNO_CURSOS` en `config.py` está actualmente vacío `{}`. Todos los cursos reciben `TURNO_DEFAULT = "MAÑANA"`. Para configurar turnos por curso habría que poblarlo:
```python
TURNO_CURSOS = {
    ("1", "A"): "MAÑANA",
    ("5", "A"): "TARDE",
}
```

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
