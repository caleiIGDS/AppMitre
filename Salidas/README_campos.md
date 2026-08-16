# Campos de los Anexos — convención de los JSON

Cada `AnexoN.json` (N = 3 a 9) lista los campos a completar de ese formulario, en el mismo orden en que aparecen en el original. **Los Anexos I y II no tienen JSON**: el I es texto normativo (instructivo) y el II es una tabla de referencia (plazos); ninguno de los dos lo completa una persona.

## Forma de cada archivo

```json
{
  "anexo": "IV",
  "numero": 4,
  "titulo": "...",
  "fuente": "IF-2024-...-GDEBA-CGCYEDGCYE",
  "completa_general": "equipo_directivo",
  "notas_generales": "...",
  "campos": [ { ...campo... }, ... ]
}
```

- `numero`: versión entera de `anexo`, para ordenar/indexar en código sin parsear el numeral romano.
- `completa_general`: quién llena el anexo en general. Si varía por sección (como el Anexo VI), cada campo trae su propio `completa` y este queda como referencia laxa.

## Forma de cada campo

```json
{
  "id": "fecha_salida",
  "orden": 9,
  "label": "Fecha de salida",
  "tipo": "fecha",
  "requerido": true,
  "completa": "escuela",
  "seccion": "salida",
  "opciones": null,
  "columnas": null,
  "condicion": null,
  "notas": null
}
```

| Clave | Significado |
|---|---|
| `id` | Clave estable en snake_case, **única dentro del archivo** (no global — si se necesita un id global, prefijar con el anexo: `IV.fecha_salida`). |
| `orden` | Entero secuencial, posición en el formulario original. Sirve para renderizar en el mismo orden sin depender del orden de las claves del JSON. |
| `label` | Texto tal como aparece en el anexo. |
| `tipo` | Uno de: `text`, `textarea`, `fecha`, `hora`, `number`, `bool`, `select`, `tabla`, `archivo`, `nota`. |
| `requerido` | Mismo nombre de clave que usa `gestion.py` en sus `CAMPOS` (`'requerido': True`), a propósito — si esto se vuelve una entidad real del motor CRUD, el mapeo es casi directo. |
| `completa` | Quién llena el campo: `escuela` (equipo directivo/preceptoría), `familia`, `estudiante` (mayor de 18 o emancipado/a), `empresa_transporte`, `director`, `representante_legal`. |
| `seccion` | Agrupador opcional dentro del anexo (ej. Anexo VI tiene `informativa` / `autorizacion` / `salud`). `null` si el anexo no tiene subdivisiones. |
| `opciones` | Solo si `tipo: "select"` — lista de valores válidos. |
| `columnas` | Solo si `tipo: "tabla"` — lista de campos (misma forma que un campo normal) que son las columnas de esa tabla repetible. |
| `condicion` | `{"campo": "<id>", "valor": <valor>}` si el campo solo aplica cuando otro campo del mismo anexo tiene cierto valor (ej. los datos de obra social solo si `tiene_obra_social: true`). `null` si no depende de nada. |
| `notas` | Aclaraciones tomadas del propio anexo (texto en cursiva/aclaración al pie) o, cuando no hay aclaración explícita en la fuente, un criterio mío marcado como tal. |

## Criterio aplicado para `requerido`

La Resolución no marca los campos con asteriscos ni dice explícitamente "opcional" en la mayoría de los casos. Apliqué esta regla, pensada para ser corregida campo por campo si no coincide con el criterio real de la escuela:

- **`requerido: true`** por default.
- **`requerido: false`** solo cuando el propio texto dice "en caso de corresponder", "sólo para..." (ej. hospedaje en salidas de +24hs), o cuando el campo es estructuralmente un catch-all ("Observaciones", "Otros datos de interés") o secundario (docentes reemplazantes).

`tipo: "nota"` es distinto del resto: no es un dato a completar, es texto fijo impreso en
el original entre dos campos (ej. "La presente planilla tendrá validez para toda
tramitación oficial que se realice." en el Anexo V, entre `observaciones` y
`lugar_y_fecha`). Su `label` es el texto completo a imprimir tal cual, sin "label: valor" —
`id`/`orden` sirven igual que en cualquier otro campo para intercalarlo en su lugar exacto.

## Campos que no vienen del formulario, agregados para poder condicionar

- **Anexo IX → `tipo_gestion`**: el formulario no lo pide como campo, pero el propio Anexo I dice que el Representante Legal solo firma "en el caso de las Escuelas Públicas de Gestión Privada". Sin este dato no se puede decidir programáticamente si pedir `representante_legal`, `entidad_propietaria` y su firma. Está marcado en sus `notas`.

## Archivo de advertencias y referencias normativas

**`advertencias_normativa.json`** — mapeo de todos los mensajes informativos/advertencias del
formulario con sus referencias normativas (Resolución 3871/24). Se carga en `formulario.html`
y se usa para generar links al visor de la Resolución. Cada objeto del array tiene:

```json
{
  "clave": "IV.itinerario",
  "anexo": "IV",
  "tipo": "ayuda_campo",
  "mensaje": "Detalle pormenorizado del recorrido...",
  "razon": "Explicación extendida de por qué existe este mensaje...",
  "referencia_normativa": "Resolución RESOC-2024-3871-GDEBA-DGCYE, Anexo I, punto 8.5.1",
  "pagina_pdf": 13,
  "frase_resaltar": "8.5.1 Para ello debe contar con un informe detallado de"
}
```

- `clave`: identificador único (ej. `"IV.itinerario"`, `"ANEXO_III.NOTA"`, `"PERSONAS.RATIO"`,
  `"AVISO_GENERAL"`).
- `tipo`: `aviso_general | nota_anexo | ayuda_campo | nota_seccion | alerta_dinamica`.
- `mensaje`: el texto exacto tal como aparece en la UI del formulario.
- `razon`: explicación más desarrollada, redactada a partir del texto real de la Resolución
  cuando se cita normativa.
- `referencia_normativa` / `pagina_pdf` / `frase_resaltar`: `null` para mensajes sin cita
  normativa explícita. Cuando existen, se arma un link al visor: `/salidas/normativa?pagina=13&buscar=8.5.1`
  que renderiza todas las páginas del PDF y resalta la frase buscada.

**Nota**: el `mensaje` es una copia manual del texto de `formulario.html`; si se edita una
ayuda ahí, debe actualizarse también en este JSON para mantener sincronía.

## Auditoría de referencias normativas (2026-08-15)

Se realizó una auditoría exhaustiva de todos los ~135 campos del formulario de salidas educativas
para verificar que cada mensaje informativo/advertencia tuviera una referencia normativa explícita
o fuera categorizado como operacional. **Resultados:**

- **45 campos CON referencia normativa** (notas de anexos, avisos generales, campos exigidos
  por la Resolución 3871/24 o normas correlacionadas). Cada uno lista la página del PDF y la
  frase exacta a resaltar.
- **89 campos operacionales SIN referencia normativa** (datos personales de estudiantes, datos
  administrativos de institución, contactos, campos descriptivos/informativos). Estos llevan
  `referencia_normativa: null` — no necesitan sustento normativo porque son instrucciones
  operacionales para el usuario.
- **1 campo FUERA DE ALCANCE**: `VI.hospitales_cercanos` — existe en el formulario pero no se
  encontró cita explícita en el texto de la Resolución. Está anotado con ⚠️ en el JSON.

La búsqueda fue manual + automatizada usando el PDF. **Ver `advertencias_normativa.json`
para el listado completo con páginas y frases de resaltado.**

## Archivos

| Archivo | Anexo | Quién lo completa (general) |
|---|---|---|
| `Anexo3.json` | III — Autorización general (barrio, sin transporte) | Familia |
| `Anexo4.json` | IV — Itinerario, actividades, objetivos y cronograma | Equipo directivo |
| `Anexo5.json` | V — Planilla de estudiantes y acompañantes | Equipo directivo |
| `Anexo6.json` | VI — Planilla informativa y autorización | Escuela (sección 1) + Familia (secciones 2 y 3) |
| `Anexo7.json` | VII — Declaración jurada estudiante mayor de 18 | Estudiante |
| `Anexo8.json` | VIII — Informe de transporte a contratar | Empresa de transporte / escuela |
| `Anexo9.json` | IX — Declaración jurada de directivos | Director/a (+ Representante Legal si es gestión privada) |
| `advertencias_normativa.json` | Ref. — Referencias a la Resolución 3871/24 para cada mensaje | (datos) |
