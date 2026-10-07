# Plantilla estándar del Google Sheet — AppMitre

Formato **fijo por contrato** que debe respetar el Google Sheet de cualquier escuela
(decisión 2026-07-13, ver `dev-log/DECISIONS.md`). La app no adapta su parser a sheets
con otro formato: la escuela copia esta plantilla y carga sus datos.

Derivado directamente del código de carga (`database.py`). Si el parser cambia,
actualizar este documento.

---

## Requisitos generales

- **Un solo documento** de Google Sheets con varias pestañas. Su ID va en `SHEET_ID` (`config.py`).
- El documento debe estar compartido como **"Cualquier persona con el enlace puede ver"**
  (la app lo descarga vía export CSV público, sin autenticación).
- El GID de cada pestaña (visible en la URL como `?gid=XXXXXXXXX`) va en `GIDS` (`config.py`).

### Pestañas requeridas

| Pestaña | Cantidad | Formato de parsing |
|---|---|---|
| Clases (una por año escolar) | 1 o más | Por **nombre de encabezado** — orden de columnas libre |
| Horarios de preceptores | 1 | **Posicional estricto** — no mover ni insertar columnas |
| Personal no docente | 1 | Por **nombre de encabezado** — orden de columnas libre |

En `GIDS`, las claves `"horarios_preceptores"` y `"personal_no_docente"` son reservadas
(deben llamarse exactamente así). Cualquier otra clave se trata como pestaña de clases
de un año (ej: `"1ro"`, `"2do"`, ... — el nombre de la clave es libre).

---

## 1. Pestañas de clases (una por año)

**Fila 1: encabezados.** La app los normaliza antes de leer: minúsculas, sin acentos,
espacios → `_`. Ej: en el sheet puede decir `"Hora Inicio"` o `"División"` — la app los
lee como `hora_inicio` y `division`. Lo que **no** puede cambiar es el nombre resultante.

El **orden de columnas es libre**. Columnas extra se ignoran. Columna faltante o
renombrada → ese campo se carga **vacío, sin error** (revisar en la UI tras cargar).

### Columnas

| Encabezado (normalizado) | Obligatoria | Formato / valores | Notas |
|---|---|---|---|
| `curso` | sí | Número solo: `1`…`7` | Sin `°` ni sufijo ("1ro" ❌) |
| `division` | sí | `A`, `B`, … o `1`, `2`, … | Letra o número según ciclo |
| `especialidad` | no | Texto libre | |
| `materia` | sí | Texto | Se guarda en MAYÚSCULAS sin acentos |
| `tipo_materia` | no | Texto | |
| `profesor` | sí | `APELLIDO NOMBRE` | Se normaliza (sin acentos, mayúsculas, sin puntos/comas). Typos se corrigen en `nombre_mapeos.json` |
| `dni`, `telefono`, `email` | no | Texto | Datos de contacto del docente |
| `aula` | sí | Ver abajo | Pasa por `limpiar_aula()` |
| `tipo_aula` | no | Texto | |
| `dia` | sí | `Lunes`, `Martes`, `Miércoles`, `Jueves`, `Viernes` | **Exacto**, con tilde en Miércoles, formato título. Debe coincidir con `DIAS` de `config.py` |
| `hora_inicio`, `hora_fin` | sí | `HH:MM` (24 h) | Deben ser distintas — no hay corrección automática si son iguales |
| `grupo` | no | `A`, `B` o vacío | Para divisiones en grupos paralelos. Solo se soportan 2 grupos |
| `superposicion` | no | Checkbox (`VERDADERO`/`TRUE`/`1` = sí) | `1` = solapamiento intencional (grupos A/B); otro valor o vacío = 0 |
| `suplente_activo` | no | Checkbox | `1` = titular en licencia, se muestra el suplente |
| `prof_suplente` | no | `APELLIDO NOMBRE` | Misma normalización que `profesor` |
| `sup_ini`, `sup_fin` | no | Texto | Vigencia de la suplencia (informativo) |

### Formato de `aula`

`limpiar_aula()` acepta estas formas y las normaliza:

| En el sheet | Queda como |
|---|---|
| `11`, `Aula 101`, `B 12` | `11`, `101`, `12` (solo el número) |
| `T2`, `T 2`, `Taller 2` | `T2` |
| `P` | `PATIO` |
| `GYM`, `PATIO` (sin números) | igual, en mayúsculas |

Las aulas resultantes deben coincidir con las listadas en `FLOOR_MAPPING` (`config.py`)
para aparecer en la Planilla General.

---

## 1b. Formato con cupos (rama `horarios-cupos`, en preparación)

Se activa cargando los GIDs en `GIDS_CUPOS` (`horarios/config.py`). Mientras esté vacío,
todo funciona con el formato de arriba.

**Pestañas de cada año:** siguen con una fila por bloque de clase (día, hora, aula, grupo…),
pero sin el docente: se van `profesor`, `dni`, `telefono`, `email`, `tipo_materia`,
`suplente_activo`, `prof_suplente`, `sup_ini` y `sup_fin`, y se agrega **`codigo`**: el
código de horario del cupo (uno por materia y división; distinto si cada grupo tiene su
docente). Todas las filas de un mismo cupo llevan el mismo código. Una fila sin código se
sigue leyendo con las columnas viejas (sirve para pasar de a poco).

**Pestañas de cupos (una por año, nuevas):** una fila por cupo.

| Encabezado (normalizado) | Obligatoria | Valores | Notas |
|---|---|---|---|
| `codigo` | sí | El código de horario | Sin distinguir mayúsculas. Fila sin código → se ignora; código repetido → vale la primera fila |
| `codigo_materia` | no | Código de la materia (nomenclador DGCyE, ej. `MCS`) | Igual para todas las divisiones del año |
| `curso`, `division`, `especialidad`, `materia` | no | | Informativas: manda lo de la pestaña de horario |
| `tipo_materia` | no | `Técnico-específica`, `Científico-tecnológica`, `Teórica` | Pasa a la columna `tipo_materia` de cada clase |
| `profesor` | sí | `APELLIDO NOMBRE` | Vacío = cupo sin cubrir |
| `situacion_de_revista` | sí | `Titular`, `Provisional`, `Suplente` | La del profesor |
| `suplente` | no | `APELLIDO NOMBRE` | Con nombre = suplencia activa (se muestra el suplente); vacía = no hay |
| `desde`, `hasta` | no | Texto | Vigencia de la suplencia (informativo, como `sup_ini`/`sup_fin`) |
| `dni`, `telefono`, `email` | no | Texto | Contacto del profesor |

No hay checkbox de suplente activo: lo decide si `suplente` tiene nombre. La carga no se
corta por errores de datos: devuelve **avisos** (código sin cupo, código repetido, revista
o tipo desconocidos, suplente sin profesor, cupo que ninguna clase usa). Los cupos quedan
además en la tabla `cupos` de `escuela.db`.

---

## 2. Pestaña de preceptores (`horarios_preceptores`)

⚠️ **Estructura posicional estricta.** Esta pestaña se lee por posición de columna,
no por encabezado. **No insertar, mover ni eliminar columnas.** Un corrimiento corrompe
los datos silenciosamente (riesgo aceptado por decisión 2026-07-13).

Son 3 bloques horizontales yuxtapuestos — uno por turno — de 8 columnas cada uno,
separados por **una columna vacía**:

| Columnas | Contenido |
|---|---|
| `A`–`H` | Bloque **MAÑANA** |
| `I` | (vacía, separadora) |
| `J`–`Q` | Bloque **TARDE** |
| `R` | (vacía, separadora) |
| `S`–`Z` | Bloque **VESPERTINO** |

### Estructura de cada bloque (8 columnas)

```
Preceptor | Curso | División | LUNES | MARTES | MIÉRCOLES | JUEVES | VIERNES
```

### Filas

- **Fila 1**: etiquetas de turno ("MAÑANA", "TARDE", "VESPERTINO") — se descarta siempre.
- **Fila 2**: encabezados — la primera celda de cada bloque debe decir `Preceptor`
  (así el parser la reconoce y la salta). Los nombres de los días son decorativos:
  el día lo determina la **posición** (4.ª columna del bloque = Lunes, … 8.ª = Viernes).
- **Filas 3+**: datos. Una fila por preceptor+curso; un preceptor puede aparecer en
  varias filas (varios cursos) y en varios bloques (contraturno).

### Valores

- `Curso`: número solo (`1`…`7`), igual que en las pestañas de clases.
- `División`: letra o número (la app la pasa a mayúsculas).
- Celdas de día: **cualquier valor no vacío distinto de `FALSO`** marca presencia
  (sirven checkboxes de Google Sheets: `VERDADERO`/`FALSO`). Vacío o `FALSO` = ausente.
- Los turnos son fijos: MAÑANA / TARDE / VESPERTINO, determinados por el bloque.

---

## 3. Pestaña de personal no docente (`personal_no_docente`)

**Fila 1: encabezados** (misma normalización que clases — orden libre):

```
nombre | rol | lunes_inicio | lunes_fin | martes_inicio | martes_fin |
miercoles_inicio | miercoles_fin | jueves_inicio | jueves_fin |
viernes_inicio | viernes_fin
```

En el sheet pueden escribirse como `"Miércoles inicio"` etc. — la normalización quita
tildes y reemplaza espacios por `_`.

- `nombre`: misma normalización que `profesor`. `rol`: ej. "PORTERO", "SECRETARIA"
  (se guarda en mayúsculas, aparece como badge en el buscador).
- Fila sin `nombre` o sin `rol` → se ignora completa.
- Un día se carga **solo si tiene inicio y fin** (`HH:MM`). Un solo horario por día.

---

## 4. Configuración del lado de la app (`config.py`)

Además del sheet, la escuela configura (hoy editando `config.py`; a futuro vía `/admin`, ver PLAN_ESCUELAS E1):

| Qué | Dónde |
|---|---|
| ID del documento | `SHEET_ID` |
| GID de cada pestaña | `GIDS` |
| Turno de cada curso/división | `TURNO_CURSOS` (`("1","A"): "MAÑANA"`) + `TURNO_DEFAULT` |
| Pisos y sus aulas | `FLOOR_MAPPING` (aulas ya normalizadas por `limpiar_aula`) |
| Días laborales | `DIAS` (deben coincidir con la columna `dia` del sheet) |
| Branding | `ESCUELA_NOMBRE`, `ESCUELA_LOGO`, `ESCUELA_VERSION` |
| Correcciones de nombres | `nombre_mapeos.json` (root, por institución) |

### Checklist para una escuela nueva

1. Clonar el Google Sheet del Mitre (o crear uno con este formato) y cargar los datos.
2. Compartirlo como "cualquiera con el enlace puede ver".
3. Copiar `SHEET_ID` y los GIDs de cada pestaña a `config.py`.
4. Completar `TURNO_CURSOS`, `FLOOR_MAPPING`, `DIAS` y branding en `config.py`.
5. Crear `nombre_mapeos.json` (puede arrancar como `{}`).
6. Deployar y disparar `/api/actualizar`.
7. Verificar en la UI: cursos completos, sin bloques en hora 0 (horarios vacíos),
   nombres de docentes sin duplicados por typo, aulas presentes en la Planilla General.
