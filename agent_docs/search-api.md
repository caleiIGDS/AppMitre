# Sistema de Búsqueda y API — AppMitre

La app Vue sigue descargando `GET /app-horarios/api/datos` y buscando localmente
(`frontend/horarios/src/datos.js`, `Buscador.vue`). La API de consultas estructuradas,
independiente del navegador, vive en `horarios/consultas/` y `horarios/api_consultas.py`.
El agente interno conserva sus herramientas anteriores. `horarios/mcp.py` expone `/mcp`
con Streamable HTTP en modo JSON sin sesiones/SSE, compatible con WSGI y sin otro proceso.
El cliente oficial se verifica en `tests/test_horarios_mcp_cliente.py` (SDK opcional).
La conexión en ChatGPT sigue siendo un paso de cuenta posterior al despliegue.

El MCP anuncia las herramientas del registro y `obtener_pdf`; reciben `{consulta}`. Todas las llamadas, incluido el descubrimiento, exigen `Authorization: Bearer <HORARIOS_MCP_TOKEN>`, configurado en el `.env` y en el cliente MCP. No hay OAuth, sesiones MCP ni clave en los argumentos; sin token configurado o con token incorrecto devuelve 401. La cookie y la contraseña de la web no autorizan MCP, y el token MCP no autoriza la API web. Rotar el token corta el acceso inmediatamente. Los resultados escolares siguen siendo los mismos JSON, con errores de dominio en `isError` y `structuredContent`; no se registran argumentos.
`horarios/pdf_agentes.py` reutiliza los exports. `obtener_pdf` devuelve `resource_link` y enlace con nombre `.pdf` en `/horarios/mcp-pdf/<referencia>/<nombre>`, firmado por una hora y descargable sin cookies ni cabeceras, con `Content-Disposition: attachment`. `resources/read` acepta solo esas URL propias firmadas y devuelve el PDF como recurso binario base64, sin llamadas HTTP. Se conserva la ruta antigua sin nombre para enlaces ya emitidos. Rotar las claves invalida los enlaces. El PDF de persona solo tiene clases; devolver un archivo MCP no garantiza que el cliente cree un adjunto nativo.

## Consultas estructuradas de lectura

Un único prefijo efectivo: `/app-horarios/api/v1/consultas`. Conserva el prefijo API
existente para montarse en el mismo Flask; no existe un alias `/horarios/api/v1`.
Las cinco operaciones aceptan POST con JSON o GET con filtros en la URL; no escriben ni consultan Sheets. GET admite `token` con la misma clave de Horarios, sin abrir sesión; listas como parámetros repetidos, `valor` como alias de `valores`, año entero y `ahora=true/false`. Mismo motor, validación, JSON y paginación. Guía pública: `/instructivo.md` (archivo `instructivo-publico.md`); la copia local `instructivo.md` contiene la clave, se excluye de Git y no se sirve por HTTP.

| Ruta bajo ese prefijo | Contrato | Filtros |
| --- | --- | --- |
| `POST /catalogos` | `listar_catalogos` | `incluir`: cursos/aulas/roles/nombres (por defecto cursos); `nombres` devuelve solo nombres canónicos únicos, sin fichas ni horarios, para revisar identificaciones sin coincidencia convincente; `anio` solo con cursos. |
| `POST /materias` | `consultar_materias` | `tipos` (te/ct/fg), `anios` (cadenas 1–7), `divisiones`, `especialidades`, `texto` (materia/titular/suplente), `cursor`. OR dentro de cada lista, AND entre filtros. Clasificación compartida con `/datos` en `horarios/materias.py`, desde `MATERIAS_PLAN` y `ESPECIALIDAD_CURSOS`. Cupos por curso/grupo/materia/docente, con minutos semanales positivos y contador de bloques sin duración válida; `resumen` global repetido en cada página (no sumarlo). Hasta 50 cupos por página. Catálogos admite también `especialidades` (curso → nombre o null) y `tipos_materia` (clave/nombre). |
| `POST /personas` | `buscar_personas` | `nombre`, `rol` o `multiples_roles=true` (más de un cargo); los filtros se intersectan antes de paginar y devuelve todos los roles. `multiples_roles=false` no restringe cargos y requiere nombre o rol. |
| `POST /horarios` | `consultar_horarios` | `tipo`: curso/persona/aula; selector `valores`, `anio` (curso) o `piso` (aula); `dias`, pareja `desde`/`hasta`, `ahora`, `roles` (persona). |
| `POST /preceptores` | `consultar_preceptores` | Sin filtros: toda la planilla. `cursos` o `anio`, `nombres`, `turno`, `dias`; filtros de distinta clase se intersectan. |
| `GET /contratos` | Registro y esquemas | Nombres, descripciones, entrada/salida y límites del mismo registro que valida las consultas. |
| `GET /openapi.json` | OpenAPI 3.1 | Las cinco consultas, sus esquemas compartidos y la autenticación; listo para configurar una conexión posterior. |

Todas esas rutas exigen sesión de Horarios, `Authorization: Bearer <HORARIOS_CLAVE>` o, únicamente para GET/HEAD, `?token=<HORARIOS_CLAVE>` codificado como componente de URL.
La clave se compara en tiempo constante sobre UTF-8; login y Bearer comparten el límite
de cinco intentos fallidos por IP en quince minutos (memoria del proceso, no distribuido).
Bearer solo permite estas lecturas: no crea sesión ni habilita `/datos`, PDF,
`/actualizar` u otras áreas. Las consultas POST con cookie exigen `X-Mitre`; con Bearer
no necesitan esa defensa CSRF. Las respuestas nuevas llevan `Cache-Control: no-store`.
El token en URL puede quedar en historiales y registros del hosting; no incluirlo en documentación pública ni resultados. Las respuestas agregan `Referrer-Policy: no-referrer` y `X-Robots-Tag: noindex, nofollow`.
OpenAPI usa el origen de la petición como servidor; descargarlo desde el dominio HTTPS
real al configurar el cliente. Esto no configura Actions ni despliega la aplicación.

Ejemplos: `POST /horarios` con `{"tipo":"curso","anio":3}` devuelve todas las divisiones
registradas, con lunes a viernes; `{"tipo":"persona","valores":["PEREZ ANA"],"dias":["lunes"]}`
devuelve sus actividades con `rol` en cada una. Los días pedidos siempre están presentes,
incluidos los vacíos. Fin de semana solo al pedirlo, o con `ahora: true`; el reloj es el
de `horarios.config.ahora()` y agrega `momento: {fecha,hora}`. Aula sin selector exige
`ahora`, o un único día y un rango. No se aceptan fechas de calendario como si la copia
semanal contemplara feriados, asistencia o suspensiones.

La identidad usa normalización exacta y los alias explícitos de `nombre_mapeos.json`.
No fusiona abreviaturas o nombres parecidos. `/personas` devuelve candidatos sin horarios;
un selector personal aproximado devuelve `persona_ambigua`, incluso si hay un solo
candidato, para que el cliente confirme el nombre. El lote se resuelve antes de producir
actividades. Una búsqueda sin coincidencias devuelve `personas: []`; entidad desconocida
da `no_encontrado`. No devuelve contactos ni el padrón completo como fallback.

Se conservan grupos A/B y `superposicion_permitida` sin diagnosticar conflictos.
Con suplencia activa, curso/aula muestra al suplente o `profesor: null` si falta, y
`titular_en_licencia`; el horario del titular conserva la referencia con `en_licencia`
y `suplente` nullable. No se infiere vigencia por fechas. Horas legacy se interpretan
con el motor de minutos existente (`7:40`, `19:00:00`, `16:60`) y salen como `HH:MM`,
sin modificar la fuente. Rango: `inicio < hasta` y `fin > desde`; ahora: `inicio <= hora < fin`.
Los bloques mantienen sus extremos originales. Fin anterior o igual al inicio se entrega como figura en la fuente, sin rechazar la consulta ni agregar un juicio calculado; el agente lo interpreta. Con rango/ahora esos bloques se conservan en los días solicitados, porque no se puede determinar su intersección. Un valor horario que no se puede leer sigue dando error de datos. En horarios de persona/aula, una clase sin curso informado conserva `curso: null`.

Preceptores solo tiene asignaciones por turno/día: nunca horas supuestas. En una persona,
agrupa cursos por turno y día y conserva esas asignaciones aun con rango/ahora, sin
afirmar presencia exacta. `/preceptores` devuelve personas con todas sus asignaciones,
incluidos varios principales por días y ambos contraturnos. `principal` se determina
con `TURNO_CURSOS`; si no hay turno nominal, `funcion: null` y aviso puntual, sin default.
`vacantes` representa FALTA/FALTAN/SIN ASIGNAR/fila explícita sin nombre; `sin_registro`
solo se genera para cursos/año solicitados, respetando turno/días, sin filtro de nombres.
La consulta global no genera una matriz de ausencias. Falta de registro no prueba vacante. Una asignación de preceptor sin división se conserva como `3°` con aviso `division_no_informada`, sin asignarla a todas las divisiones del año ni generar ausencias supuestas. Solo las divisiones identificadas forman el catálogo y los horarios de cursos por año.

Cada operación abre una conexión SQLite `mode=ro` con `query_only` y una transacción;
lee las tres tablas con columnas permitidas. La revisión se calcula sobre ese contenido
y la configuración/alias (incluidos especialidades y planes de materias), sin depender del mtime fuera de la transacción. No hay caché
de consultas ni marca inventada de sincronización. Base ausente/vacía/ilegible devuelve
`datos_no_disponibles`, no un horario vacío; una consulta válida sin actividades sí lo hace.

Resultados compactos, sin envoltorios rutinarios de estado o zona. Hasta 40.000 caracteres
por página, 20 entidades completas para horarios y 50 personas para búsquedas. Preceptores
admite específicamente 50 personas por página para que el listado escolar normal pueda
caber en una llamada; sus vacantes/avisos no consumen cupos de persona, sí caracteres.
No es una medición de la base de producción. Los catálogos pequeños salen completos.
`siguiente` aparece solo si hay otra página: repetir exactamente los filtros y añadir
`cursor`. Está firmado con las claves de la aplicación y Horarios, ligado a revisión,
filtros y momento si corresponde. Cambio de copia/configuración/clave, o de minuto en
`ahora`, da `consulta_vencida`; reiniciar para no combinar snapshots. Una entidad que
no cabe da `consulta_demasiado_amplia`, sin partir días ni truncar datos.

Entradas y salidas se validan contra el registro de JSON Schema, incluidas combinaciones
de selectores. Error: `{"error":{"codigo":"…",…}}`; parámetros 400, desconocido 404,
ambigüedad/continuación vencida 409, datos inconsistentes/consulta amplia 422, base o
servicio no disponibles 503; autenticación 401/403 e intentos 429. No se exponen SQL,
trazas ni secretos. Regresiones: `python -m unittest discover -s tests -p 'test_horarios*.py'`
(SQLite temporal y cliente Flask; sin importar `app.py`, cargar `.env` o abrir bases reales).

## Antecedentes de la página clásica

Lo que sigue describe `static/js/script.js` y `/horarios/api/*`, retirados el
2026-10-05. Es historia de reglas portadas; esas rutas y sus fallbacks no existen hoy.

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
