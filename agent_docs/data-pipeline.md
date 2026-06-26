# Pipeline de Datos — AppMitre

> Complementa `CLAUDE.md`. Leer ese primero para contexto general.

---

## Flujo completo: Sheets → SQLite

```
Google Sheets (CSV export)
  → descargar_sheet()        # urllib, reintentos, normaliza headers
  → cargar_desde_sheets()    # una hoja por año (1ro–7mo)
  → cargar_horarios_preceptores()
  → cargar_personal_no_docente()
  → escuela.db (SQLite)
```

El pipeline se dispara en dos situaciones:
1. **Arranque directo** (`python app.py`): el bloque `__main__` llama `init_tablas()` + `tiene_datos()` + carga si está vacío.
2. **Petición manual**: `GET /api/actualizar` llama `crear_tablas()` (borra todo) + carga completa.

**Importante — producción (PythonAnywhere/WSGI):** el bloque `__main__` no se ejecuta cuando el servidor WSGI importa el módulo. En PythonAnywhere el `escuela.db` persiste entre reinicios, pero en un deploy nuevo la DB está vacía y todas las rutas fallan. En ese caso hay que disparar `/api/actualizar` desde la consola o el navegador. Solución estructural pendiente: ver `dev-log/tasks/TODO.md` #1.

---

## `descargar_sheet(sheet_id, gid, skip_rows, intentos, demora)`

- **URL construida**: `https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}`
- Requiere que el sheet sea público o compartido con "cualquiera con el link".
- `skip_rows`: salta N filas antes de procesar. Actualmente se llama con `skip_rows=0` en todos los casos. En `cargar_horarios_preceptores` la fila de labels ("MAÑANA/TARDE/VESPERTINO") se descarta con `next(reader, None)`, y la fila de cabecera real (Preceptor|Curso|...) se filtra con el guard `preceptor.upper() != "PRECEPTOR"`.
- **Reintentos**: 3 intentos con `time.sleep(2)` entre fallidos (0.5s antes del primer intento). Si el tercer intento falla, propaga la excepción.
- **Normalización de headers**: la primera línea se convierte a minúsculas, sin acentos, con espacios → `_`. Esto permite que `csv.DictReader` use claves predecibles independientemente de mayúsculas en la planilla.

---

## `cargar_desde_sheets(sheet_id, gids)`

Itera sobre `GIDS_CURSOS` (las hojas de 1ro a 7mo) y por cada hoja:
1. Descarga el CSV.
2. Lee con `csv.DictReader` (acceso por nombre de columna, no por índice).
3. Por cada fila aplica normalización y hace `INSERT INTO clases`.

### Columnas esperadas en el CSV de clases

| Columna en sheet | Columna en DB | Procesamiento |
|---|---|---|
| `curso` | `curso` | directo |
| `division` | `division` | directo |
| `especialidad` | `especialidad` | directo |
| `materia` | `materia` | `eliminar_acentos().upper().strip()` |
| `tipo_materia` | `tipo_materia` | directo |
| `profesor` | `profesor` | `limpiar_profesor()` |
| `dni`, `telefono`, `email` | ídem | directos |
| `aula` | `aula` | `limpiar_aula()` |
| `tipo_aula` | `tipo_aula` | directo |
| `dia` | `dia` | directo (ej: "Lunes") |
| `hora_inicio`, `hora_fin` | ídem | directos (formato "HH:MM") |
| `grupo` | `grupo` | directo ("A", "B", o vacío) |
| `superposicion` | `superposicion` INTEGER | ver abajo |
| `suplente_activo` | `suplente_activo` INTEGER | ver abajo |
| `prof_suplente` | `prof_suplente` | `limpiar_profesor()` |
| `sup_ini`, `sup_fin` | ídem | directos |

---

## Normalización de datos

### `limpiar_profesor(nombre)`

Pasos en orden:
1. `unicodedata.normalize('NFD', nombre)` → descompone caracteres acentuados
2. Filtra caracteres de categoría `Mn` (marcas diacríticas) → elimina tildes
3. `.upper()` → todo mayúsculas
4. `.replace(',', ' ')` → quita comas (formato "Apellido, Nombre" → "Apellido  Nombre")
5. `.replace('.', ' ')` → quita puntos (iniciales "J.PABLO" → "J PABLO")
6. `re.sub(r'\s+', ' ', n).strip()` → colapsa espacios múltiples
7. Lookup en `_NOMBRE_MAPEOS` (cargado desde `nombre_mapeos.json` al importar el módulo)

**Resultado**: nombre canónico en mayúsculas sin acentos, usado como clave de búsqueda en DB y como display en el frontend.

### `nombre_mapeos.json`

Archivo JSON `{nombre_sucio: nombre_canónico}`. Ambas claves ya deben estar en el formato post-normalización de los pasos 1–6 (sin acentos, mayúsculas, sin comas/puntos, espacios simples).

```json
{
    "CASALE SERVIN BETTINA": "CASALE SERVINI BETTINA",
    "ALONSO EVELYN": "ALONSO EVELIN"
}
```

**Para agregar un nuevo mapeo:**
1. Determinar cómo llega el nombre desde Sheets (aplicar los pasos 1–6 mentalmente).
2. Agregar la entrada en `nombre_mapeos.json`.
3. Hacer `POST /api/actualizar` (o reiniciar) — el archivo se recarga al importar el módulo, por lo que requiere restart o recarga de la DB.

**Limitación**: `_NOMBRE_MAPEOS` se carga una vez al iniciar. Editar el JSON sin reiniciar o sin disparar `/api/actualizar` no tiene efecto.

### `limpiar_aula(aula)`

1. `eliminar_acentos(aula).upper().strip()`
2. Si el resultado es `'P'` → devuelve `'PATIO'`
3. Detecta si es taller: `re.search(r'\b(TALLER|T)\s*\d+', aula_limpia)` → True para "T1", "T 1", "Taller 1"
4. Extrae todos los dígitos con `re.findall(r'\d+', aula_limpia)` → los une en string
5. Si es taller → devuelve `"T{numero}"` (ej: "T12")
6. Si tiene números pero no es taller → devuelve solo el número (ej: "Aula 101" → "101", "B 12" → "12")
7. Sin números → devuelve el nombre limpio en mayúsculas (ej: "GYM", "PATIO")

**Casos edge conocidos:**
- `"P"` → `"PATIO"` (único mapeo hardcodeado por nombre)
- El regex `\b(TALLER|T)\s*\d+` puede matchear "T" solo si va seguido de espacios+dígito. "T12" matchea. "T sin número" no matchea y el aula se devuelve sin cambios.

---

## Detección de `superposicion` y `suplente_activo`

Ambos campos llegan del CSV como strings y pueden tener valores tipo checkbox de Google Sheets:
- Verdadero: `"TRUE"`, `"1"`, `"VERDADERO"` (case-insensitive)
- Falso: cualquier otra cosa → `0`

**`superposicion`**:
- `0` = conflicto real: dos clases en el mismo aula/horario que no deberían estar juntas → bloque rojo de advertencia en el calendario.
- `1` = solapamiento permitido: mismo espacio, grupos A/B distintos → se renderizan lado a lado.

**`suplente_activo`**:
- `0` = el profesor titular está activo.
- `1` = el titular está en licencia; usar `prof_suplente` como nombre del docente. El bloque se renderiza con estilo "LICENCIADA" (texto rojo) en la vista del profesor titular, y muestra al suplente en las demás vistas.

---

## `cargar_horarios_preceptores(sheet_id, gid)`

La hoja tiene un layout en 3 bloques horizontales yuxtapuestos (no una tabla estándar):

```
[fila ignorada: "MAÑANA,,,,,,,,,,TARDE,,,,,,,,,,VESPERTINO..."]
[headers: Preceptor|Estado|Curso|Div|Lun|Mar|Mie|Jue|Vie | <sep> | Preceptor|Estado|Curso|Div|Lun|Mar|Mie|Jue|Vie | ...]
[datos fila 1 ...]
```

- `skip_rows=0` (default). `next(reader, None)` descarta la fila de labels ("MAÑANA/TARDE/VESPERTINO").
- La fila de cabecera (Preceptor|Curso|...) se filtra con el guard `preceptor.upper() != "PRECEPTOR"`.
- Bloques: `MAÑANA` en offset 0, `TARDE` en offset 9, `VESPERTINO` en offset 18 (8 cols de datos + 1 col separadora vacía = paso 9).
- Una celda con `"X"`, `"TRUE"` o `"VERDADERO"` en la columna de día marca que el preceptor está presente ese día.

**Fragilidad**: si el sheet de preceptores agrega o mueve columnas, los offsets 0/10/20 quedan mal. Documentado en `PLAN_ESCUELAS.md` como E4.

---

## `cargar_personal_no_docente(sheet_id, gid)`

Hoja tabular estándar. Columnas esperadas:
- `nombre` → `limpiar_profesor()`
- `rol` → `eliminar_acentos().upper().strip()`
- `lunes_inicio`, `lunes_fin`, `martes_inicio`, `martes_fin`, ... (una par por día)

Solo se inserta una fila en DB por cada día donde `inicio` y `fin` estén presentes y no vacíos.

---

## Agregar un año nuevo o hoja nueva

1. Crear la hoja en el Google Sheet con el mismo formato de columnas que las demás.
2. Obtener el GID de la nueva hoja (visible en la URL de Google Sheets: `?gid=XXXXXXXXX`).
3. En `config.py`, agregar la entrada en `GIDS`:
   ```python
   GIDS = {
       ...
       "8vo": "NUEVO_GID_AQUI",
   }
   ```
4. `GIDS_CURSOS` se genera automáticamente excluyendo `horarios_preceptores` y `personal_no_docente`, así que el nuevo año se incluirá en la próxima carga.
5. Disparar `GET /api/actualizar`.

No hay nada más que cambiar en el código para un año adicional.

---

## Comportamiento ante errores

- **Google Sheets caído o sin acceso**: `descargar_sheet()` lanza excepción después de 3 reintentos. `cargar_desde_sheets()` no maneja esa excepción → `/api/actualizar` devuelve HTTP 500. Los datos existentes en DB NO se borran porque `crear_tablas()` ya corrió antes. Resultado: DB vacía con tablas existentes, todo devuelve sin resultados hasta el próximo `/api/actualizar` exitoso.
- **CSV malformado**: `csv.DictReader` accede por nombre; columnas faltantes devuelven `None` → `limpiar_profesor(None)` devuelve `""` sin error. Filas parciales se insertan con campos vacíos.
- **Campos `hora_inicio`/`hora_fin` vacíos**: se insertan tal cual. El frontend ignora clases sin horario válido (`timeToMin` devuelve 0 para strings inválidos). Esto puede causar bloques en posición 0 del calendario.
- **Producción (PythonAnywhere/WSGI)**: el bloque `__main__` no corre al importar el módulo. En un deploy nuevo la DB está vacía → primera petición falla. Disparar `/api/actualizar` para inicializar. Solución estructural pendiente: ver `dev-log/tasks/TODO.md` #1.
