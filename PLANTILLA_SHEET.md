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

El **orden de columnas es libre**. Columnas extra se ignoran. Si falta o se renombra
un encabezado obligatorio, la actualización falla y conserva el último horario completo.

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
