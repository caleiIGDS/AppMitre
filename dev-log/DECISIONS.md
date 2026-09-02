# Decisiones de Arquitectura — AppMitre

Buscar acá con Grep (por archivo o símbolo) antes de "corregir" algo que parece raro — no leerlo entero. Muchas decisiones tienen contexto específico de la escuela o del despliegue.

**Qué entra: sólo lo que alguien sin el contexto revertiría por parecer un error.** Si se deduce del código, no entra. **Formato: máximo 6 líneas** — la decisión, por qué, y la alternativa descartada si la hubo. Sin `**Contexto**` / `**Decisión 1**` / `**Consecuencia**`. Las entradas viejas y largas son el formato anterior: no imitarlas.

---

## [2026-09-02] — Ningún recurso se borra: se da de baja diciendo qué pasó

Borrar la fila se lleva justo lo que después hace falta para rendir cuentas: qué era,
cuántos había, dónde estaba, las fotos. Así que el recurso queda con estado "Dado de baja"
(fuera del listado salvo que se pida verlo) y la baja anota en `recurso_bajas` el motivo y
el detalle — sin motivo no hay baja. "Dado de baja" salió de `ESTADOS_RECURSO` para que no
se pueda poner suelto y sin explicación desde el form o el chat. La baja se revierte, pero
la fila del registro no se borra: queda marcada `revertida`, porque es un historial.

## [2026-09-01] — El registro de uso del agente va a `agente.db`, y sin respaldo

Las otras tres tablas del agente viven en `gestion.db` porque son efímeras (se barren a
las 4 horas). `agente_turnos` es lo contrario: una fila por turno, con el texto del chat,
para siempre. En `gestion.db` se la llevarían los 20 respaldos rotativos de `respaldos.py`,
multiplicando por veinte el archivo de chats; suelta se puede bajar sola para analizarla.
Por lo mismo `agente.db` NO entra en `respaldos.py`: es telemetría — perderla cuesta
análisis, no datos de la escuela — y rotarle 20 copias deshace lo que se ganó al sacarla.

## [2026-09-01] — Cruzar horarios lo calcula Python, y por tramos, no por bandas

`coincidencias` no le pasa los horarios crudos al modelo para que los cruce. `deepseek-v4-pro`
puede hacerlo, pero medido sobre tres casos con `horario_curso` sueltos acertó 2 de 6, gastando
9.400–12.000 tokens de razonamiento y hasta 6 minutos; con cuatro cursos agotó el tope de salida
sin escribir nada las dos veces (el usuario lee "me quedé sin espacio"). Cuando falla, omite un
día entero. Con la grilla ya calculada: 3/3 en 15–28 s y ~1.100 tokens.
La presencia tampoco se modela como banda de la primera a la última clase: el 32% de los
días-curso tienen un pozo en el medio (máximo 480 min), y ningún umbral de corte los separa
de un cambio de turno porque hay huecos legítimos de más de 3 h. Por eso se corta el día en
cada frontera y cada tramo dice `materia` / `hueco` / `fuera`: el hueco no se modela, se ve.

## [2026-08-29] — El sistema de horarios es un sitio aparte, no un área de `accesos`

Pedido de la escuela: horarios y el resto, dos sitios sin relación. `horarios/` es un
paquete autónomo — su `config.py`, su gate (`acceso.py`: contraseña `HORARIOS_CLAVE`, sin
`accesos.db` ni invitaciones), sus datos. No importa `accesos`/`crud`/`config` global; la
dependencia va sólo `agente` → `horarios.datos`. A propósito, no descuidos: el `/` que
redirige, la config/branding/`ahora()` duplicados, que `horarios` no esté en `registrar_app`.
Antes (misma fecha) se probó como área de `accesos` con `horarios.ver`; descartado por el
pedido de separación total. `/horarios/api/actualizar` tras el login pero sin permiso extra
(la DB nace vacía en cada deploy y el que la puebla no siempre es admin).

---

## [2026-08-27] — Los horarios se leen por un Web App de Apps Script, no del Sheet público

El Drive de la escuela pasó a privado, así que `descargar_sheet()` ya no puede usar
`docs.google.com/.../export?format=csv`. En vez de meter credenciales de servicio de Google
en la app (otra key que rotar, otro scope que auditar), un Apps Script corre como el dueño
del documento y devuelve el mismo CSV. El endpoint queda sin auth de Google (`ANYONE_ANONYMOUS`),
así que la app firma cada request con `HMAC_SHA256(secreto, timestamp_ms)` y el script exige
que el timestamp esté dentro de ±120 s — el secreto nunca viaja, sólo su HMAC, y una URL
capturada deja de servir en dos minutos. Código y deploy del proxy: `apps_script/`.

Dentro del proxy: lee con el **Servicio Avanzado de Sheets** (`Sheets.Spreadsheets.Values.get`)
y arma el CSV a mano (`_aCsv`). No es `UrlFetchApp` al `/export?format=csv` con bearer token
—ese endpoint web devuelve 401 con el token de Apps Script— ni `SpreadsheetApp.openById`,
que exige el scope `.../auth/spreadsheets` completo (incluye editar y borrar). La API de
Sheets acepta `spreadsheets.readonly`: sólo lectura, sin Drive.

---

## [2026-08-24] — `puntaje_busqueda`: una palabra candidata más corta que la query no cuenta

Buscar "pelacable" traía 7 resultados con el correcto ("Pela cable Weidmuller", vía alias
"pelacables") en el puesto #4: palabras sueltas cortas de OTROS recursos ("cable", "placa",
de alias como "cable extension USB" o "placa arduino") daban ratio 0.71 contra la query
completa — arriba del umbral 0.68 — sin relación real, porque una palabra corta CONTENIDA en
una query larga infla artificialmente el ratio. Se agregó un guard en el loop palabra por
palabra de `texto.py::puntaje_busqueda`: si `len(palabra) < len(q_norm)`, no cuenta. No toca
los 9 casos ya validados en el comentario de `UMBRAL_SIMILITUD` (todos dan lo mismo con o sin
guard) porque ahí es la query la corta comparando contra una palabra larga, no al revés.
Portado también a los dos puertos JS del mismo algoritmo (`static/gestion.js`,
`templates/salidas/formulario.html`) para que sigan siendo un puerto fiel.

---

## [2026-08-24] — Búsqueda en vivo de `/gestion`: se revierte "solo substring" de 2026-07-21

Esa decisión rechazó portar `difflib` a JS por duplicar lógica, y dejó el fuzzy server-side
como respaldo vía "Enter con JS apagado, o URLs `?q=`". Pero con JS activo (el caso real,
casi siempre) el propio script bloquea el Enter y esconde el botón BUSCAR — ese respaldo
nunca fue alcanzable para un usuario tipeando. Se porta `texto.puntaje_busqueda` a JS
(`static/gestion.js`), mismo criterio que ya se aceptó para `formulario.html` (autocompletado
de estudiantes, 2026-08-08+): duplicar el algoritmo ya es un patrón usado, no algo a evitar.

---

## [2026-08-22] — Se elimina `recursos.ubicacion`: la ubicación es siempre la lista de unidades

Con `recurso_unidades` ya numerando cada unidad (ver el reemplazo de `recurso_ubicaciones`,
abajo), tener además un campo `ubicacion` simple en `recursos` dejaba dos fuentes de verdad que
podían desincronizarse (el campo decía un lugar, el desglose otro). Se saca el campo: un recurso
sin desglosar pasa a tener igual su unidad 1, y la ficha/listado siempre muestran la lista
agrupada por lugar, aunque sea de un solo ítem. `gestion.migrar()` reparte el valor viejo de
`ubicacion` entre las unidades antes de tirar la columna (`ALTER TABLE ... DROP COLUMN`); el
agente pierde `ubicacion` de `crear_entidad`/`editar_entidad` y la fija solo con `mover_ubicacion`.

---

## [2026-08-22] — `recurso_ubicaciones` (agregado, del 2026-08-21) se reemplaza por `recurso_unidades` (numerado)

No es un revert: el pedido pasó de "cuántas unidades hay en cada lugar" a poder direccionar
una unidad puntual ("el destornillador 3 y el 5 están en el taller"), algo que un contador
por lugar no puede expresar. Mantener las dos tablas hubiera significado sincronizar un
agregado con un detalle que ya lo contiene (divergencia garantizada), así que la tabla vieja
se migra a filas numeradas (1 unidad = 1 fila) y se borra; ver `migrar()` en `gestion.py`.

---

## [2026-08-21] — Se elimina `conjuntos`/`actividades`/préstamos de `/gestion`, no se archiva

Decisión de producto: la escuela no iba a seguir cargando kits ni prácticas de taller, y el
retiro interno (préstamos/carrito) tampoco se estaba usando. Se sacó el código entero en vez
de dejarlo apagado (permiso sin uso, rutas muertas) porque una feature sin usuarios cuesta
mantenimiento igual (migraciones, docs, tools del agente) sin dar nada a cambio. Si se
retoma, el diseño anterior está en el historial de git (commit previo a este) y en esta
misma entrada de CHANGELOG.

---

## [2026-08-21] — `salidas.leer`/`salidas.editar` con verbo `'admin'` mientras el área está en desarrollo

No es un typo: `PERFILES` en `accesos.py` arma `interno-lectura`/`interno-gestion` filtrando
por verbo `'leer'`/`'escribir'`, así que un permiso con verbo `'admin'` no entra en ningún
preset de invitación — sólo lo tiene quien entra con comodín `'*'` (mismo mecanismo que ya
usa `accesos.admin`). Efecto: nadie salvo admin ve ni puede abrir Salidas Educativas (el
link de nav ya está atrás de `puede('salidas.leer')`, se oculta solo). Volver a
`'leer'`/`'escribir'` cuando el área esté lista para el resto de los dispositivos internos.

---

## [2026-08-21] — Se retoma la columna `alias` por recurso, descartada el 2026-08-08 — cierra tarea #21

La decisión 2026-08-08 (ver abajo) rechazó una columna de sinónimos por recurso: la
evaluó **para la búsqueda del chat**, donde `listar_todos` ya resuelve lo mismo sin
diccionario, más barato. Lo que cambia ahora es el caso de uso: el buscador **web** de
`/gestion/recursos?q=` no tiene ningún modelo del otro lado — es texto plano — así que
`listar_todos` no le sirve a un preceptor tipeando en el navegador. El argumento de
cardinalidad de esa decisión (47% de filas comparten concepto, hay que acordarse en cada
alta) sigue siendo válido y se acepta a propósito: se resuelve dejando que **el asistente**
mantenga la columna, no una persona a mano — ver la entrada siguiente. Se llama `alias` y
no `sinonimos` (ni `otros_nombres`, como decía la tarea #21 original): "zapatilla" y
"alargue" no son sinónimos estrictos, son términos que la gente confunde.

---

## [2026-08-21] — `alias` de un recurso solo se escribe por `editar_entidad`, nunca por `crear_entidad`

El campo vive fuera de `ENTIDADES['recursos']['campos']` a propósito: esa lista es la
única fuente que usan el form web y la ficha de confirmación del chat (`fichas.py`), así
que agregar `alias` ahí lo mostraría en las dos, justo lo que se quiere evitar (es un
campo que completa el asistente y el usuario nunca debe ver ni editar). Por eso tampoco
está en el `input_schema` de `crear_entidad` (`esquemas.py`): si alguien lo agrega ahí para
"que se cargue de una vez" en el alta, hay que sumarlo también a `_normalizar_borrador` y
`_ficha_confirmacion`, y el campo terminaría visible en la ficha — el camino correcto es
que el asistente llame a `editar_entidad` (sin ficha, sin confirmación) después del alta.

---

## [2026-08-16] — Lo que completa una familia por el link público no se guarda

**Contexto**: el link público (`/salidas/completar/<token>`, ver
`agent_docs/salidas-educativas.md`) dejaba una fila en `salidas_familias` por cada
VI/VII completado, con su PDF cacheado en `salidas_pdfs/<id>/AnexoVI_familia<id>.pdf`, y
`detalle.html` los listaba para que la escuela los revisara ("Completados por familias y
estudiantes"). Se pidió sacar esa lista: "lo que hace el familiar muere en el momento que
se va de la pestaña".

**Por qué tiene sentido, no sólo "porque lo pidieron"**: `completar_listo.html` ya le decía
a la familia que el PDF generado es un **borrador para imprimir** — la firma va a mano
sobre el papel y ESE papel, físico, es lo que la escuela archiva y lleva el día de la
salida. El PDF digital nunca fue el documento legal. Guardar además una copia digital con
el DNI y los datos de salud de cada estudiante no respaldaba nada que el papel no
respaldara ya, y sí sumaba una superficie más con datos sensibles para filtrar o perder.

**Decisión**: se sacó la tabla `salidas_familias` y el cacheo en disco. Lo que completa la
familia vive sólo en la `session` de Flask de ese navegador (cookie firmada, sin
`session.permanent` — se pierde al cerrar el navegador) el tiempo justo para generar y
servir el PDF en memoria. Ver detalle técnico y las rutas que cambiaron de firma en
`dev-log/CHANGELOG.md` de la misma fecha.

**Cabo suelto**: una instalación que ya tenía el link público en uso conserva su
`salidas_familias` vieja (con datos reales) hasta que alguien corra
`python actualizar.py --limpiar` a propósito — no se dropea sola, mismo criterio que
cualquier tabla con filas que el código deja de declarar (ver "Paso 5" de `actualizar.py`).
Los PDF ya cacheados en `salidas_pdfs/<id>/Anexo*_familia*.pdf` de instalaciones viejas
tampoco se borran solos (ese paso no toca el filesystem) — quedan huérfanos hasta que esa
salida entera venza y se purgue.

---

## [2026-08-16] — Piloto: label destacado / valor plano, sólo Anexo VI

**Contexto**: la norma general del renderer de PDF (`_valor_destacado`, ver
`agent_docs/salidas-educativas.md`) es que el VALOR cargado por el usuario lleve el trazo de
semi-negrita y el label vaya en texto plano (salvo Anexo V, negrita real vía
`ANEXOS_LABEL_NEGRITA`). Se pidió invertirlo: que el LABEL sea el que se destaque y el valor
quede en texto plano.

**Decisión — piloto acotado a un solo anexo, no cambio global**: en vez de invertir la norma
en los 7 anexos de una, se agregó `ANEXOS_LABEL_DESTACADO = {'VI'}` (paralelo a
`ANEXOS_LABEL_NEGRITA`) y sólo el Anexo VI usa el criterio invertido, a pedido explícito
("aplicalo solo a anexo 6 para ver como queda"). Los otros 6 anexos no se tocaron.

**Decisión 2 — la narrativa de "Autorización" (VI) no se invirtió**: el párrafo corrido
("Por la presente autorizo a mi hijo/a ___, DNI ___...") no tiene labels sueltos — son
placeholders interpolados dentro de una oración, no pares "label: valor". No hay nada
simétrico para invertir ahí, así que `{tipo_salida}`, `{distrito}`, etc. dentro de ese
párrafo siguen destacándose igual que antes; sólo cambiaron los campos que sí son "label:
valor" (`_escribir_par`, `_dibujar_textarea`).

**Consecuencia**: si el resultado convence, lo esperable es reemplazar
`ANEXOS_LABEL_NEGRITA` por `ANEXOS_LABEL_DESTACADO` en el resto de los anexos en vez de
mantener ambos mecanismos en paralelo — todavía no se pidió ese paso.

---

## [2026-08-16] — Link público de familias: blueprint aparte + token propio por envío

**Contexto**: el VI (autoriza el padre/madre/tutor de un estudiante menor) y el VII
(declaración jurada del propio estudiante mayor de edad) son, en el papel, uno por
estudiante, pero el formulario digital sólo guardaba un VI y un VII por salida — el resto
de las familias completaba a mano sobre una fotocopia en blanco. Se pidió un link
compartible para que cada familia complete el suyo digitalmente y se lleve su PDF ya
armado para imprimir y hacer firmar.

**Decisión 1 — otro blueprint, no una excepción en el gate**: `bp` (el área) está gateado
con `accesos.registrar_acceso`, que exige `salidas.leer` en cualquier endpoint salvo
`/login` — no hay forma de marcar una sola ruta como pública ahí sin que `accesos.py`
(capa 1) tenga que aprender sobre una excepción de un área concreta. Se creó `bp_publico`,
un segundo `Blueprint` en `salidas.py` que **no** pasa por `registrar_acceso` y que
`app.py` registra aparte — mismo patrón que ya usa `accesos.py` para `/acceso/<token>`
(registrado sobre `app`, no dentro de un blueprint gateado).

**Alternativa descartada**: agregar un parámetro `endpoints_publicos` a
`accesos.registrar_acceso`. Se descartó porque le sumaría a capa 1 el concepto de "ruta sin
ningún permiso", que hoy no existe (todo lo gateado pide al menos algo), por un caso de uso
de una sola área.

**Decisión 2 — dos tokens, no uno**: el link de la salida (`salidas.token`) lo comparten
todas las familias de esa salida, así que no alcanza como única defensa — si el "ver tu PDF"
después de completar usara el `id` autoincremental de la fila, cualquier familia con el
link podría enumerar `id`s (1, 2, 3...) y abrir el PDF —con el DNI y los datos de salud— de
otra familia de la misma salida. Se agregó `salidas_familias.token`, generado por envío, y
`pdf_publico`/`listo` exigen los dos a la vez.

**Decisión 3 — un envío es una fila nueva, nunca pisa la salida**: `salidas_familias` es una
tabla aparte, no un UPDATE sobre `anexos.VI`/`anexos.VII` de la salida. Así el VI/VII "en
blanco" que la escuela ya veía en el detalle sigue existiendo como vista previa, y ninguna
familia puede pisar los datos de otra completando el formulario después.

**Consecuencia**: `salidas.py` gana una segunda superficie de rutas sin login. La única
protección ahí son los tokens (128 bits cada uno, sin rate limit ni CAPTCHA — mismo nivel de
seguridad "alcanza para que no entre el curioso" que ya documenta `agent_docs/accesos.md`
para las invitaciones). Cada familia que complete genera un PDF nuevo en disco
(`AnexoVI_familia<id>.pdf`); `_purgar_vencidas` los limpia junto con el resto de la salida
al año.

---

## [2026-08-15] — Más de un seguro escolar en el Anexo IX: copias completas, no una tabla

**Contexto**: al cargar los datos fijos de la escuela apareció un instructivo interno con
**tres** pólizas de seguro escolar vigentes a la vez (Responsabilidad Civil para
estudiantes menores de edad, para mayores, y un seguro de accidentes personales aparte).
El Anexo IX (`compania_aseguradora`/`tipo_seguro`/`numero_poliza`/`vigencia_poliza`) sólo
tenía lugar para una póliza — ni el JSON del anexo ni el renderer soportaban más de una.

**Decisión**: en el papel real, cada Declaración Jurada (Anexo IX) sólo declara una
póliza — no existe una versión del formulario con una tabla de seguros. Por eso un seguro
adicional **no** se modela como una fila más de una tabla (a diferencia de, por ejemplo,
`V.listado_personas`): genera una **copia completa del Anexo IX**, con los mismos datos de
identificación y declaración, y sólo el bloque de seguro distinto — tantas copias como
seguros haya. En el formulario, `estado.anexos.IX._seguros_adicionales` es un array plano
que vive fuera del schema de `Salidas/Anexo9.json` (el renderer sólo itera
`schema['campos']`, así que no le afecta); en `salidas.py`, `_generar_pdfs` llama al mismo
`_generar_pdf_anexo('IX', ...)` una vez por cada entrada, pisando sólo los 5 campos del
seguro, y guarda `AnexoIX_2.pdf`, `AnexoIX_3.pdf`, etc.

Se agregó además un selector de 3 **presets** conocidos (`SEGUROS_PRESET` en
`formulario.html`) que completa los 4 campos del seguro con un click, pero los deja
editables a mano después — no reemplaza la carga manual, la acelera. Esto obligó a sacarle
`auto:true` a esos 4 campos: estaban atados a `DATOS_FIJOS` vía `SEGURO_A_FIJO`, y
`refrescarDerivados()` los pisa con el valor "fijo" cada vez que se toca cualquier campo
de Datos Comunes — con un preset elegido a mano, eso hubiese descartado la elección en
cuanto el usuario tocara otra cosa. Los campos de identificación del Anexo IX que sí siguen
atados a un dato fijo real de la escuela (representante legal, entidad propietaria) quedan
como estaban.

**Alternativa descartada**: modelar `seguros` como `tipo: "tabla"` en el JSON, como
`listado_personas`. Se descartó porque en el papel real **no hay ninguna tabla** — cada
seguro es una hoja aparte con la declaración jurada completa repetida, y renderizar una
tabla ahí hubiera sido, otra vez, el mismo tipo de invención-de-formato-que-no-existe-en-
el-papel que ya se corrigió para otros anexos (ver la entrada de arriba).

**Consecuencia**: `ver_pdf` deja de aceptar sólo el allowlist fijo `ANEXOS_NUMEROS` — ahora
también matchea `IX_<n>` por regex (sigue siendo allowlist estricto, `anexo` arma una ruta
de archivo). `detalle()` detecta las copias extra por archivo en disco, no por releer
`datos_json`, para que la lista de PDF siempre refleje lo que hay generado de verdad.
Editar una salida y sacar un seguro borra las copias extra viejas antes de regenerar
(`_limpiar_pdfs_ix_extra`), para no dejar un `AnexoIX_3.pdf` huérfano de una versión
anterior de la salida.

---

## [2026-08-15] — Auditoría de texto impreso: notas al pie, mayúsculas y estilo inline que no se habían verificado

**Contexto**: se encontró que `notas_generales` del Anexo V, aunque marcada como "verificada
contra el original", en realidad era una paráfrasis mía, no el texto literal del papel. Ante
la pregunta directa de si ese mismo error estaba en otro lado, se repasó **todo el texto que
efectivamente se imprime** (labels, notas, títulos, párrafos narrativos) anexo por anexo
contra las imágenes reales de la Resolución, no sólo el que se había tocado en la sesión.

**Lo que apareció, todo en el Anexo IX** (el más auditado en detalle, por ser donde
`NOTAS_A_IMPRIMIR` ya tenía dos ids marcados como "verificados"):
1. El texto de las notas (1)/(2) estaba mal: decía "Debe constar..." cuando el original dice
   "Deberá constar...", y la nota (2) estaba truncada (le faltaba "En este rubro se dejará
   constancia de todas las...").
2. Encima, el *lugar* donde se imprimían estaba mal: iban pegadas inline junto al campo
   (`"Tipo de seguro: valor (Debe constar...)"`), pero en el papel real son notas al pie de
   página de verdad — separadas, después de la declaración jurada, antes de "Lugar y Fecha".
3. Casi todos los labels del Anexo IX están en mayúscula en el papel y no tenían el permiso
   en `LABELS_MAYUSCULA` (nunca se había revisado este anexo para eso, sólo V).
4. El bloque de firmas ("FIRMA Y SELLO" / "DIRECTOR/A" y "FIRMA Y SELLO" / "REPRESENTANTE
   LEGAL") es a dos columnas lado a lado en el papel; se imprimía como dos líneas sueltas.
5. Anexo VII: dentro del párrafo narrativo, "salida educativa / de representación
   institucional" va en negrita y "(tachar lo que no corresponda)" en itálica en el papel;
   se imprimía todo con el mismo estilo.

**Decisión**: corregir los cinco puntos (footnotes reales vía un campo `nota` en su lugar
correcto — `nota_pie_seguro` — en vez de `NOTAS_A_IMPRIMIR`; `LABELS_MAYUSCULA['IX']`;
`CAMPOS_FIRMA_IX`/`_dibujar_firmas_ix` para las dos columnas; `segmentos` en
`PARRAFOS_NARRATIVA` para mezclar negrita/itálica dentro de un párrafo). Además, el título de
cada anexo (`ANEXO {n}` + `titulo`) pasó a imprimirse siempre en mayúscula — se confirmó
visualmente que es así en los 7 anexos, así que no hizo falta un permiso por anexo ahí.

**Consecuencia**: no se encontraron más errores de este tipo en III, IV, V, VI, VIII (se
revisaron con el mismo método). El criterio general se mantiene: nada de esto se hubiera
encontrado sin comparar contra la imagen real, página por página — un `pdftotext` a veces
alcanza para el texto, pero no para saber si algo va en negrita, en mayúscula, o en qué
lugar exacto de la página.

---

## [2026-08-15] — Párrafos narrativos con blancos, no "label: valor", para lo que en el papel es una oración corrida

**Contexto**: revisando anexo por anexo contra el original (ver la entrada de abajo), quedó
un tipo de desvío que la recalibración anterior no cubría: los Anexos III, VI y VII no
abren con una lista de campos en el papel — abren con una oración corrida con blancos
intercalados ("Por la presente autorizo a ____, DNI ____, estudiante de ____ Año..."), y
VI (sección `salud`), VII e IX además tienen bloques legales de varios párrafos
("Autorizo...", "Declaramos bajo juramento...") que no corresponden a ningún campo — son
texto fijo, sin ningún blanco. El renderer venía imprimiendo esos datos como líneas sueltas
`"Nombre: ___"`, `"DNI: ___"`, uno debajo del otro, y directamente omitía los bloques
legales por no tener campo asociado.

**Decisión**: separar el problema en dos mecanismos, sin tocar el JSON existente para el
primer caso. Para las oraciones con blancos intercalados, `PARRAFOS_NARRATIVA` (en
`salidas.py`) declara, por anexo, qué ids de campo consume y una plantilla `.format()` que
los teje en el texto real; el JSON sigue pidiendo esos mismos campos sueltos (los sigue
necesitando el formulario HTML tal cual), sólo cambia cómo se imprimen en el PDF —
presentación, no esquema. Para los bloques legales fijos, que no tienen ningún dato
variable, se usaron campos `tipo: "nota"` nuevos agregados directo al JSON (mismo mecanismo
que ya existía para el "tendrá validez..." del Anexo V), con los párrafos unidos por `\n\n`
en el `label`.

**Alternativa descartada**: reescribir esos campos del JSON como un solo campo de texto
libre por bloque (ej. fusionar `nombre_estudiante`+`dni_estudiante`+`anio_curso`+
`seccion_curso` en un campo `autorizacion_texto`). Se descartó porque el formulario HTML
sigue necesitando esos datos como campos separados y validables (DNI, año, sección son
datos estructurados en otras partes del legajo) — mezclar la oración de papel con el dato
real le rompería la carga digital para ganar nada del lado del PDF.

**Consecuencia**: `_generar_pdf_anexo` ahora también hace un pase para saltear, en el loop
principal, los ids que un bloque narrativo ya va a imprimir (`ids_narrativa_resto`) —mismo
patrón que ya existía para `pares_segundo` de `CAMPOS_MISMA_LINEA`—, así que agregar un
campo nuevo a un bloque narrativo existente requiere tocar `PARRAFOS_NARRATIVA`, no sólo el
JSON. Verificado página por página contra el original para III, VI y VII (los únicos que
abren con un párrafo así) — los demás anexos siguen campo por campo, sin cambios.

---

## [2026-08-15] — El PDF de cada anexo se recalibró contra el papel real, no contra la lógica de un form

**Contexto**: la primera versión del renderer (ver la entrada de más abajo, "guardado en
servidor...") dibujaba cada campo como una tarjeta — label en negrita arriba, valor
subrayado abajo — que es el lenguaje visual de un formulario web moderno, no el del papel
oficial. El pedido fue puntual: sin cambiar ningún dato que se muestra, hacer que el PDF
generado se parezca al anexo real todo lo posible. Antes de tocar código se revisó el PDF
de la Resolución (`Resol 3871-24...pdf`) página por página, anexo por anexo, en vez de
asumir cómo se vería.

**Lo que el papel realmente hace, y que no era obvio sin mirarlo**: casi todo el contenido
de los Anexos III, IV, VI, VII, VIII y IX es texto corrido con blancos para completar a
mano ("Nombre y apellido …………………………. DNI ……………………"), **no** una grilla de
campo-por-caja. Sólo hay dos excepciones tabulares de verdad: el listado de personas del
Anexo V (una grilla con bordes, encabezados y ~18 filas) y una cajita chica de 3 renglones
que repiten el VI y el VII para "Tiene Obra Social/Prepaga · Sí/No · Nombre · N° Socio".
Las "tablas" de docentes del Anexo IV que el JSON modela como `tipo:"tabla"` **no** son una
grilla en el papel — son renglones de texto repetidos.

**La decisión fue ajustar el renderer a esa realidad, no genérica el problema al revés**:
en vez de un único modo de dibujo (campo → caja), quedaron tres, elegidos por lo que el
campo realmente es en el papel — línea corrida (`_dibujar_campo`, el caso general), grilla
con bordes (`_dibujar_tabla`, sólo para el listado de personas) y la cajita de obra social
(`_dibujar_obra_social`, detectada por id porque VI y VII repiten el mismo grupo de
campos). Sigue sin haber 7 layouts a mano: los tres modos son genéricos y los elige el
`tipo` del campo (o su `id`, para los dos casos puntuales que no se pueden inferir del
`tipo`), no el nombre del anexo.

**Los encabezados de sección resultaron ser otro punto de fricción**: `Salidas/AnexoN.json`
usa `seccion` como clave de agrupación interna (`"hospedaje_mas_24hs"`, `"informativa"`),
no como el texto que hay que imprimir — imprimirlo tal cual daba encabezados en
mayúsculas-de-slug, ilegibles y sin relación con lo que dice el papel. Se agregó
`SECCION_TITULOS` en `salidas.py` como tabla de traducción slug → texto real, en vez de
reescribir los JSON: el JSON es el esquema de datos, cómo se titula una sección en un PDF
es una decisión de presentación, y separarlas evita que un cambio de wording en el PDF
obligue a tocar el archivo que se usa como referencia del formulario completo.

**Se verificó visualmente, no sólo por ausencia de excepción.** Con `pdftoppm` (ya
disponible en el sistema, sin agregar una dependencia de Python) se rasterizó cada anexo
generado a PNG y se lo miró página por página contra las capturas del PDF original —
incluyendo casos límite (Anexo IX con `tipo_gestion=privada`, Anexo VI/VII con y sin obra
social, Anexo IV con y sin docentes reemplazantes). Es el mismo método que destapó el
problema del `logo-pba.svg` (ver la entrada de abajo): mirar el PDF, no asumir que el
código que "no tira error" hace lo que se pidió.

---

## [2026-08-15] — El logo-pba.svg no se puede dibujar directo en un PDF de fpdf2

**Contexto**: al agregar membrete a los PDF de Salidas (escudo en el header, logo de la
DGCyE en el footer — ver la entrada de más abajo), `logo-pba.svg` (en el root del repo) se
dibujaba en blanco: nada de error, sólo un aviso de log ("Ignoring unsupported SVG tag:
`<pattern>`") fácil de no ver entre los demás avisos inofensivos que ya tira fpdf2 con
`escudo.svg` (`<filter>`, `<stop>` sin offset). Se verificó rasterizando el PDF con
`pdftoppm` y mirando la página: el escudo del header salía bien, el logo del footer no
salía nada.

**La causa**: `logo-pba.svg` no es un SVG "de verdad" con paths vectoriales — es un
`<rect>` con `fill: url(#pattern0)`, y ese patrón envuelve un `<image>` con un PNG entero
codificado en base64 (`xlink:href="data:image/png;base64,..."`). Es una forma común de
exportar un SVG desde herramientas de diseño cuando el "vector" en realidad es una imagen
rasterizada. **fpdf2 no soporta `<pattern>`** (es una limitación conocida y documentada del
proyecto), así que ese `<rect>` — que es todo el contenido visible del archivo — no dibuja
nada.

**La decisión es extraer el PNG embebido una sola vez** (`base64.b64decode` del contenido
de `xlink:href`) y commitear el resultado como `static/images/logo-pba.png`, que es lo que
usa `salidas._PDFAnexo.footer()`. **No** apuntar de nuevo al `.svg` del root pensando que
"ya debería andar": si el logo se reemplaza más adelante, hay que repetir la extracción (o
conseguir directamente un PNG/JPG del logo). `escudo.svg` sí se puede seguir usando tal
cual porque tiene paths vectoriales de verdad además de algún filtro/gradiente que fpdf2
ignora sin perder la forma reconocible del escudo.

---

## [2026-08-15] — Salidas educativas: guardado en servidor, vigencia de 1 año, y por qué no es una `ENTIDAD` de crud.py

**Contexto**: `Salidas/formulario-salidas.html` (herramienta standalone del 2026-08-14) armaba
el legajo digital de una salida educativa enteramente en el navegador, sin servidor
involucrado — la única salida era descargar un JSON. El pedido siguiente fue guardar la
salida en el servidor con vigencia de 1 año, tener una previsualización de todas las
guardadas, y generar los PDF de cada anexo para verlos en el navegador sin descargarlos
solos. Eso obligaba a que dejara de ser un archivo aislado.

**Por qué no es una `ENTIDAD` de `crud.py`.** El motor genérico asume filas planas de
campos escalares: `_guardar_form` hace `INSERT`/`UPDATE` columna=valor desde
`request.form`, y `templates/crud/form.html` sólo sabe pintar `text/number/select/textarea`
sin arrays ni anidamiento. Una salida es un blob con datos comunes + una tabla de personas
de largo variable + 7 anexos, cada uno con sus propios campos (algunos con sub-tablas de
largo variable, como el listado de docentes o de personas). Forzarlo a `ENTIDADES` habría
significado escribir por fuera del motor de todos modos para las partes que no entran, y
mantener dos formas de completar lo mismo. El precedente correcto ya estaba en el propio
código: **préstamos**, en `gestion.py`, tampoco es una `ENTIDAD` — tiene ítems con cantidad
y un ciclo prestado→devuelto — y resuelve exactamente este tipo de caso con rutas y tabla
propias, reutilizando sólo lo compartido (`accesos`, `crud.conectar`/`crud.init_db`,
`respaldos`). `salidas.py` sigue ese mismo molde.

**La vigencia se borra sola y del todo, sin papelera.** Al año de guardada, una salida (fila
+ sus 7 PDF) se elimina automáticamente. Es una decisión explícita de minimizar datos
retenidos: una salida guarda DNI y datos de salud de estudiantes, y ese mismo criterio ya
había regido el diseño del formulario standalone ("no persistente en la compu que se esté
usando"). Se evaluaron alternativas menos agresivas (ocultar pasado el año pero conservar,
o sólo marcar como vencida) y se descartaron a propósito: cualquiera de las dos deja datos
sensibles viviendo en el servidor más tiempo del que hace falta.

**Por qué el testigo de `crud.init_db` no es la tabla `salidas`.** `crud.init_db` levanta
`RuntimeError` si la tabla testigo está vacía pero hay respaldos previos — es el guard que
evitó repetir la pérdida de datos del 2026-08-08 (ver la entrada de ese día). El problema es
que `salidas` queda **legítimamente vacía** cada vez que todas las salidas guardadas vencen
y se purgan solas: si esa fuera la tabla testigo, el primer año sin ninguna salida activa
tumbaría el arranque de la app entera confundiendo "vencieron todas" con "se perdió el
archivo". La solución fue separar las dos preguntas: `salidas_meta` es una tabla de un solo
renglón, sembrada una vez en el primer `init_db()` y nunca más tocada — sirve de testigo
("¿esta DB se inicializó alguna vez?") sin depender de si hay salidas activas ahora mismo.

**El PDF de cada anexo se genera con un renderer genérico, no 7 layouts a mano.** Recorre
`Salidas/AnexoN.json` (ya existente, la referencia completa del formulario en papel) en vez
de duplicar la lista de campos en Python. Como esos JSON incluyen los campos de firma y
"lugar y fecha" que el formulario digital dejó de tipear a propósito (ver la decisión del
2026-08-14), el PDF los imprime en blanco — que es exactamente lo que hace falta: se
completan a mano después de imprimir. Al escribirlo apareció un detalle no obvio de fpdf2:
`multi_cell()` por default deja el cursor pegado al margen derecho (`new_x=XPos.RIGHT`), así
que el siguiente `multi_cell()` revienta con `FPDFException: Not enough horizontal space to
render a single character` — hay que pasar `new_x='LMARGIN', new_y='NEXT'` en cada llamada.

---

## [2026-08-13] — La foto se ata al número, no a la ficha

**Contexto**: cargar una estantería entera obligaba a un mensaje por objeto, porque el chat aceptaba una foto por turno y cada ficha se guardaba con un botón que escribía al instante. Al pasar a tandas de ocho apareció el problema real, que no es el volumen sino la **corrección**: de ocho fichas, dos siempre salen mal, y pedir un cambio escribiendo se llevaba puesto lo ya revisado (`quitarConfirmaciones()` borra los botones apenas el usuario tipea).

**La foto pendiente se guardaba con el token de la ficha como clave** — el SHA-1 de su contenido. Funciona mientras la ficha se confirme tal cual salió; en cuanto el modelo la rearma con la corrección, el token es otro y **la foto queda huérfana**: el recurso se crea sin imagen y nadie se entera. No es un bug del lote, es un bug que el lote hace inevitable.

**La decisión es numerar las fotos y que el número sea lo que viaja.** `leer_foto` devuelve cada lectura con el número de su foto, `crear_entidad(foto=N)` lo recibe, y el prompt le insiste en volver a mandar el mismo al rearmar. La clave de `agente_fotos_pendientes` pasa a ser `sid:n`. La columna se sigue llamando `token` porque es la PK y no hacía falta migrar nada.

**Lo interesante es que ese número resolvió tres cosas de una**: la foto sobrevive a la corrección, `_fusionar_fichas()` sabe qué ficha nueva reemplaza a cuál vieja (sin eso quedaban dos botones para la misma alta, con contenidos distintos y el mismo nombre), y el chat puede numerar las miniaturas para que "la 3 no se lee" signifique algo. Buscamos lo primero; los otros dos salieron gratis.

**`foto` va al lado de los campos y no adentro.** Metido en el borrador cambiaría el token — que es el hash de **lo que el usuario leyó** — por un dato que no está en la ficha. Es la misma regla de siempre acá: el token identifica lo aprobado, nada más.

**La numeración no reinicia en cada turno**, sigue desde la última foto pendiente. Arrancando de 1, mandar dos fotos con un lote a medio revisar pisaba las de ese lote; y el modelo ya venía hablando de "la foto 2" en el historial.

---

## [2026-08-13] — Revisar no es guardar: el lote no escribe hasta el final

**Contexto**: el botón verde de una ficha guarda al toque, y eso está bien para una. Con ocho en pantalla obliga a decidir de a una y sin vuelta atrás — y la única forma de corregir era escribir, que borraba los botones de las otras siete.

**La decisión es separar marcar de escribir.** `POST /agente/revisar` guarda un estado por ficha (`ok` / `observada` / `descartada`) y **no toca el inventario ni llama al modelo**; `POST /agente/lote` es el único que escribe. Hasta ese click no hay una sola fila nueva en `gestion.db`, así que mirar las ocho fichas es gratis y reversible.

**El estado vive en la DB, no en el DOM.** Es lo que hace que la revisión sobreviva a recargar la página, a navegar a `/gestion` y a mandar otro mensaje en el medio — y por lo tanto lo que permite dejar de borrar los botones al escribir, que era el problema original. Un lote a medio revisar es un estado con valor: son ocho decisiones que el usuario ya tomó.

**Las acotadas NO se guardan.** Fue lo primero que se decidió y ordena todo lo demás: "corregir" significa que la ficha no va como está, y una ficha que el usuario marcó como mala no puede terminar escrita porque el modelo no haya entendido la corrección. Salen de las pendientes y vuelven rearmadas desde cero, con token nuevo; lo que sobrevive es la foto, que está atada al número.

**Todas las correcciones van en un solo mensaje al modelo**, no una llamada por ficha: ocho fichas serían ocho turnos y ocho respuestas para leer. Y **si no quedó ninguna observada, no se llama al modelo**: la respuesta se arma en Python, como `/confirmar`. Un lote todo aprobado es el caso más común y no tiene por qué costar un turno de LLM.

**El botón de cerrar se habilita recién cuando no queda ninguna pendiente.** La idea del lote es mirar las ocho antes de tocar nada; con el botón vivo desde el principio es fácil mandar media tanda sin querer, y lo que se manda ya está escrito.

**Con una sola ficha no hay lote.** Meterle dos pasos al caso de siempre sería un click de más para el 90% de los usos. El circuito de revisión se activa a partir de dos.

---

## [2026-08-12] — El primer permiso que protege una factura, no un dato

**Contexto**: mandar una foto estaba habilitado con `agente.leer`, o sea para cualquier dispositivo invitado — el mismo permiso que hace falta para escribir "¿a qué hora tiene clase Pérez?". Es la única cosa del chat que llama a una **API aparte** (~2.000 tokens por lectura, ver la entrada del 2026-08-09), y no tiene tope: nada impide sacar veinte fotos seguidas. El resto de las tools sólo leen SQLite.

**La decisión es `agente.vision` con verbo `admin`**, no con verbo `leer`. Los perfiles se arman por verbo, así que `admin` es exactamente "no entra en ningún preset de interno": los dispositivos ya invitados no lo tienen, no hubo que migrar a nadie, y el admin puede igual tildárselo a mano a alguien puntual (queda con perfil `custom`). Es el mismo mecanismo que `agente.auditar` y `historia.personas`.

**Lo que lo hace distinto de los permisos que ya había**: los demás protegen *datos* — quién ve las semblanzas de `personas`, quién puede borrar un préstamo. Este protege **gasto**. Vale la pena decirlo porque invita a un error de razonamiento: como no hay dato sensible atrás, es tentador implementarlo sólo escondiendo el botón. Esconder el botón no baja ninguna factura; el POST se arma en dos líneas.

**Por eso corta en tres capas y la del medio es la que vale**: el template no pinta el botón (cosmética, y es lo que el usuario pidió), `chat()` devuelve `403` si igual llega una `imagen` (**el corte real**), y `tools_permitidas()` no manda `leer_foto` ni `adjuntar_foto`. La tercera no es redundante: sin ella el modelo le ofrecería a un acceso sin visión que mande una foto que no tiene forma de mandar — es el mismo criterio de siempre acá, no prometer lo que no se puede hacer.

**El permiso extra se pide ADEMÁS del declarado, no en su lugar.** Mapear `adjuntar_foto` a `agente.vision` a secas era más corto y abría un agujero: un dispositivo con visión tildada a mano habría podido escribir en la galería de un recurso sin tener `agente.escribir`. `PERMISO_POR_TOOL` sigue siendo la fuente de verdad de qué hace cada tool; `TOOLS_FOTO` es una condición encima.

**El prompt se recorta con las tools, no con los permisos** — la regla que ya regía para `escribe` y `ve_personas`, ahora también para `ve_fotos`. Sin las tools de foto no van los bloques que explican qué hacer con una foto. No es sólo ahorro: dejarlos habría dejado al modelo describiendo un circuito que del otro lado no existe.

**Lo que queda afuera a propósito**: las fotos que un acceso mandó *antes* de este cambio se le siguen mostrando al repintar su historial. Es su propia conversación y ya está pagada; borrarlas sería tirar contexto que el usuario vio, para tapar un gasto que ya ocurrió.

---

## [2026-08-12] — La foto se guarda para mostrarla, no para volver a mandársela al modelo

**Contexto**: la burbuja del usuario mostraba `📷 nombre-del-archivo.jpg` y la foto no se veía nunca — ni recién mandada ni al volver al chat. El diseño original (2026-08-09, "La foto se lee en una llamada aparte") la descartaba a propósito en `_sin_imagenes()`, con un motivo que sigue siendo correcto: una foto de 1568 px son ~1.700 tokens y reenviarla en cada turno siguiente es pagar por algo que el modelo ya interpretó.

**La decisión es separar dos cosas que estaban pegadas**: lo que se persiste **para mostrar** y lo que se le manda **al modelo**. La imagen ahora vive en la clave `imagen` del mensaje, hermana de `content`; el bloque `type: image` de `content` se sigue limpiando igual que siempre, y `chat()` recorta a `role`+`content` antes de llamar al LLM. **El costo que motivó el diseño viejo no se paga**: la clave `imagen` no viaja a ninguna API. Lo único que crece es la fila de SQLite.

**Por qué la fila de SQLite no es un problema y la cookie sí lo era.** Es la misma distinción que ya se había hecho al mudar la conversación de la cookie a `gestion.db`: una cookie de más de ~4 KB el navegador **la descarta sin avisar** y el usuario se queda deslogueado; una columna JSON con unos MB no le molesta a nadie. Es exactamente el patrón que la galería de un recurso usa hace rato (`crud.agregar_foto`: array de `{b64, tipo, fecha}` en una columna). Y está acotado solo: `HISTORIAL_GUARDADO` (60 mensajes) rota el historial, así que las fotos viejas se van sin que nadie las barra.

**Se descartó una tabla `agente_fotos_chat`** simétrica con `agente_fotos_pendientes`. Esa tabla existe por una razón que acá no aplica: la foto pendiente tiene que sobrevivir *más allá* de la conversación (el alta se confirma después, desde otra página) y su clave es el token de la ficha, no el turno. La foto del chat tiene exactamente la vida del mensaje que la trajo: guardarla aparte sería inventar un ciclo de vida propio y con él el problema de mantener las dos cosas sincronizadas cuando el historial rota o entra `/reset`.

**El bug que casi se cuela: reconstruir un dict es tirar lo que no conocés.** `_sin_imagenes()` y `_foto_en_pasado()` armaban `{'role': …, 'content': …}` en vez de copiar el mensaje. Las dos corren en cadena antes de persistir, así que cualquiera de las dos borraba la clave nueva y la foto no llegaba nunca a la DB — sin error, sin log, simplemente no estaba. Cambiadas a `{**msg, 'content': …}`.

**Lo que el usuario no escribió no se muestra, y eso ahora incluye "Te mando esta foto."** (`TEXTO_FOTO_SOLA`). Es el texto que `chat()` inventa cuando mandan una imagen sin escribir, porque un mensaje vacío no es un turno válido — la misma familia que el `(refiriéndote a: X)` y el sello de hora, y se filtra en el mismo lugar. Sin esto había una inconsistencia visible: al mandar la foto la burbuja quedaba limpia, y al recargar aparecía una frase que el usuario nunca tipeó. La consecuencia es que `_texto_visible()` puede devolver `''` para un mensaje real, y por eso `historial()` filtra por `texto or imagen`: filtrar por texto solo hacía desaparecer del chat las fotos mandadas sin comentario.

---

## [2026-08-12] — El padrón de personas viaja inline, no por una segunda tool

**Contexto**: preguntando por una persona que la búsqueda difusa no puntuaba, el agente contestaba que no estaba en el sistema. `buscar_profesor` devolvía `[]` pelado y `horario_profesor` cerraba con `"No existe ningún docente ni personal no docente llamado X ni parecido"` — una afirmación categórica que el modelo repetía como un hecho. Era la única de las tres búsquedas de persona **sin segundo nivel**: `buscar_entidad` manda a `listar_todos`, `buscar_por_rol` devuelve el padrón de cargos, y `buscar_profesor` no tenía nada. Peor: la regla de sinónimos del system prompt prometía el paralelismo (*"Para profesores el equivalente es `buscar_profesor`"*) cuando `buscar_profesor` es el **primer** nivel, no el segundo.

**Se descartó una tool `listar_personal()`**, que era la opción simétrica con `listar_todos` y la primera que se consideró. Los números la matan: el padrón entero son 344 nombres = ~1.670 tokens, y el piso que se re-procesa en **cada** round-trip de tool es ~8.050 (medición de 2026-08-08). Pedir la lista cuesta ~5x mandarla.

**Por qué acá se inlinea y en `buscar_entidad` no**, si el argumento de costo es el mismo: porque el fracaso tiene otra forma. En `buscar_entidad` la difusa casi siempre devuelve *algo* (~0.6 de similitud), así que "falló" es el juicio blando "ninguno es `exacto`" — inlinear el catálogo ahí lo pagarían también los turnos que encontraron lo que buscaban. En el padrón de horarios el fracaso es un **binario limpio**: cero candidatos sobre el umbral. La rama cara existe sólo en el callejón sin salida y no se paga nunca en un turno normal. Es el mismo criterio que ya había elegido `buscar_por_rol` con sus cuatro cargos, ahora aplicado a una lista 85 veces más grande.

**Cuándo se da vuelta**: `LIMITE_PADRON = 400` (el mismo valor que `LIMITE_LISTADO_COMPLETO`, por la misma razón). Arriba de eso la nota va sin la lista, y el texto se adapta solo. Hoy son 344, así que el margen es de una jubilación y dos suplencias: si la escuela crece, esto se activa y habrá que decidir entre subir el tope o volver a la tool aparte — que a esa altura ya podría convenir, porque la lista se acercaría al costo del round-trip.

**El puntero a las fichas es condicional al permiso.** La nota del caso vacío recuerda que el de horarios es uno de tres padrones, pero sólo nombra `buscar_entidad('personas', …)` si `ve_entidad('personas', permisos)`: mandar al modelo a una tool que no se le entregó es peor que callarse, porque la intenta, se come el error y a veces igual contesta como si hubiera funcionado (es el mismo motivo por el que las tools de escritura no se prohíben sino que no se mandan). Por eso `_horario_profesor_fmt` recibe `permisos` sin que eso cambie qué horario devuelve.

---

## [2026-08-12] — El permiso puede colgar de una entidad, no sólo de un área

**Contexto**: había que dejar las fichas de `personas` sólo para el admin. El motivo no es nuevo, estaba escrito hace rato en `agent_docs/historia-institucional.md`: la `descripcion` de una persona es un juicio en prosa sobre alguien real de la escuela, y buena parte del padrón son alumnos. Eso no es información de consulta como un horario o el stock del pañol. Mientras `personas` se veía con `historia.leer`, cualquier dispositivo invitado a consultar el inventario leía las semblanzas.

**Se descartó partir `/historia` en dos áreas.** Era la opción obvia dado que hasta acá un permiso protegía un área entera, y es la peor: `personas` e `hitos` comparten `historia.db`, la M2M `persona_hitos` y el hook `secciones_detalle`, así que separarlas significaba dos blueprints sobre la misma DB, o una FK cruzando de un área a otra — justo lo que el proyecto no tiene en ningún lado. Además duplicaba `base.html`, `home.html` y el login para esconder una tabla.

**La clave `permiso` en la cfg de la entidad es el mismo mecanismo que `campo_nombre`.** Capa 1 aprende un concepto más ("una entidad puede pedir un permiso extra") y sigue sin conocer ninguna clave concreta; el área pone cuál. Ese es el criterio de siempre acá, y el precio fue bajo: tres funciones en `crud.py` y un `before_request`. El `before_request` en vez de un chequeo por vista no es ahorro de tipeo, es que **el slug está en la URL de las siete rutas**: una sola puerta no se puede olvidar en la ruta que se agregue mañana.

**El bug que casi se cuela: esconder un fieldset no es sacarlo del guardado.** El formulario postea la lista entera de cada relación M2M, y `_guardar_form` hace `DELETE` + `INSERT`. Un fieldset escondido sólo en el template hacía que guardar un hito desde un acceso sin el permiso le **borrara los vínculos con personas**, en silencio y sin que el que guardó supiera que existían. Por eso `relaciones_visibles` filtra las dos cosas a la vez y `form.html` itera la lista que le pasa la vista. (El camino del agente, `crud.guardar_entidad`, ya era seguro: sólo toca las relaciones que vengan explícitas.)

**Verbo `'admin'`, no un perfil nuevo.** `PERFILES` se define por verbos y sólo enumera `'leer'` y `'escribir'`, así que un permiso con verbo `'admin'` no entra en ningún preset de interno y lo tiene el admin por el comodín — como `accesos.admin` o `agente.auditar`. Nadie queda migrado y no hubo que tocar el gate. El admin igual puede tildarlo a mano para alguien puntual; ahí el acceso queda como perfil `custom`, que es el mecanismo que ya existía.

**Esconderlo sólo en la web no habría servido de nada.** El asistente lee las mismas tablas: sin el corte del lado del agente, alcanzaba con preguntarle a Emilio. Y hay dos formas de cortarlo — no darle la tool, o rechazarla — que este proyecto ya distinguió antes (ver 2026-08-11): acá el equivalente a "no darle la tool" es **sacar el slug de los enum** de los esquemas, porque las tools genéricas siguen haciendo falta para recursos e hitos. El modelo no se entera de que `personas` existe, y el prompt se recorta de lo mismo que las tools para que las dos mitades del mensaje no puedan contradecirse.

**Los cuatro cruces laterales fueron el trabajo real.** Bloquear el slug es una línea; lo que filtraba nombres eran los lugares que devuelven personas **sin recibir el slug**: el cruce de padrones de `buscar_profesor`, las relaciones de `detalle_entidad('hitos')`, el padrón completo que `_recordatorio_hito` le pone delante al modelo, y `_enlazar_protagonistas`, que además escribe el vínculo al confirmar un hito sin pasar por el LLM. Es el recordatorio de que un permiso se rompe por donde el dato sale de costado, no por la puerta principal.

---

## [2026-08-12] — El tope de salida es presupuesto de razonamiento, no de respuesta

**Contexto**: `max_tokens=1024` estuvo hardcodeado en los dos loops desde que existe el agente y parecía de sobra — ninguna respuesta del asistente se acerca a las 1000 palabras. La intuición era "es el largo máximo de lo que escribe". Con un modelo de razonamiento eso es falso: `deepseek-v4-pro` piensa antes de emitir y **ese pensamiento se cobra como tokens de salida**. Medido en el turno que fallaba, gastaba entre 700 y 1600 tokens antes de largar la primera tool call.

**Por qué costó tanto encontrarlo.** El corte no se veía como un error. La API devuelve `finish_reason='length'` con el contenido vacío y sin excepción, y el loop hacía `(msg.content or '').strip() or 'Sin respuesta'` — o sea, traducía una respuesta truncada al mismo literal que una respuesta genuinamente vacía. Y como el gasto de razonamiento depende de la dificultad del turno, fallaba de forma aparentemente intermitente: "¿qué preceptor tiene 1° C?" entraba holgado, armar la ficha de un alta no. El usuario lo vivía como "a veces el bot no contesta".

**La lección general, que vale para el próximo proveedor**: con modelos de razonamiento, `max_tokens` no es un tope de verbosidad sino un presupuesto que el modelo consume pensando. Ponerlo justo para la respuesta esperada garantiza que los turnos difíciles —los que más razonamiento piden— sean exactamente los que fallen. No es un tope de costo: solo se paga lo generado, así que dejarlo holgado no cuesta nada.

**Y ningún camino silencioso debe terminar en un literal ambiguo.** `'Sin respuesta'` era indistinguible entre tres causas distintas. Ahora el corte por tope tiene su propio mensaje. Es el mismo patrón que el `except` del lector de imágenes, que también se tragaba un 404 de modelo dado de baja: cuando una falla se colapsa en un mensaje genérico, deja de ser diagnosticable.

---

## [2026-08-12] — La foto dura un turno; la lectura tiene que durar la conversación

**Contexto**: los resultados de las tools no se persisten en el historial (es deliberado: son ruido y pesan). Pero la lectura de una etiqueta no es un resultado cualquiera — es el único registro de datos que **no están en ningún otro lado**, porque la imagen tampoco se guarda. Se perdía apenas terminaba el turno, y lo único que sobrevivía era lo que el modelo hubiera repetido en su prosa. En un alta que se confirma en el turno siguiente ("dale, creá"), eso significa quedarse sin marca, sin modelo y sin specs.

**El aviso de la foto además mentía.** Se guardaba en presente — "adjuntó una foto en este turno, todavía no la vio nadie, llamá a `leer_foto`" — y esa frase seguía ahí tres turnos después. El modelo obedecía: llamaba a `leer_foto`, la tool le decía que no hay ninguna foto, y la vuelta se perdía. Un aviso que era correcto cuando se escribió se volvió una instrucción falsa por el solo hecho de persistir.

**Por eso son dos textos y la sustitución ocurre al guardar, no al construir.** Durante el turno el presente es la verdad: la imagen está en `contexto_turno`. Lo que no puede quedar es esa misma frase en el historial. Se evaluó reescribir el aviso al leer el historial en vez de al guardarlo, y se descartó: hacerlo una vez al persistir es más barato y deja el dato ya correcto en la base, en vez de depender de que todos los lectores apliquen la misma transformación.

**Regla general**: cualquier texto que se le inyecta al modelo con deícticos —"este turno", "recién", "todavía"— tiene que tener una versión en pasado antes de entrar al historial, o va a mentir en el turno siguiente.

---

## [2026-08-12] — Dos prompts de visión, no uno que haga las dos cosas

**Contexto**: se quería que el asistente pudiera *analizar* una foto (qué objeto es, en qué estado está) y no solo transcribir etiquetas. La primera lectura del problema fue "hace falta otra IA": es falsa. `gemini-2.5-flash-lite` —y cualquier modelo que se ponga en `AGENTE_VISION_MODEL`— es multimodal y siempre pudo describir la imagen. Lo que lo acotaba a transcribir era `PROMPT_LECTOR_IMAGEN`, que dice "ÚNICAMENTE lo que se lee en ella". El cambio es de prompt, no de proveedor: misma key, mismo modelo, misma llamada.

**Por qué dos prompts y no uno solo que transcriba y además describa.** Porque son dos exigencias opuestas y fusionarlas rompe la que importa. En el modo etiqueta la regla que hace confiable el alta es "preferí quedarte corto antes que inventar": si en la chapa no dice la potencia, la potencia no va. Un prompt que en el mismo aliento pida describir el objeto le da permiso para hablar de lo que no está escrito, y de ahí a completar la chapa con lo que el modelo sabe de esa marca hay un paso — que es exactamente el error que no se puede tener en una ficha de inventario. Separados, cada modo tiene una sola instrucción y no hay tensión que negociar.

**El modo lo elige el modelo, no una heurística nuestra.** Se evaluó decidirlo en el server mirando el texto del usuario y se descartó: el modelo ya tiene que decidir *si* mirar la foto (caso A/B/C del system prompt), y esa decisión y la del modo son la misma. Un `modo` desconocido cae al default en vez de fallar, porque una alucinación en el nombre no tiene por qué costar la foto.

**Tener dos modos no relajó el gate.** El riesgo del cambio era ese: que "ahora también puede describir" se leyera como permiso para mirar toda foto que entra. Sigue valiendo lo de siempre —leer es una tool, no un paso automático— y se agregó una prohibición explícita de llamar dos veces con los dos modos a ver cuál sale mejor. Cada llamada cuesta igual en los dos modos.

**Una descripción no da de alta.** El resultado del modo análisis vuelve con una instrucción que se lo prohíbe al agente: ahí no hay marca ni modelo confiables, y una ficha armada sobre "me pareció que era una amoladora" contamina el inventario con datos que nadie escribió nunca. Para cargar hace falta la etiqueta o el dictado del usuario.

---

## [2026-08-11] — El acceso interno se da por dispositivo, no por contraseña

**Contexto**: hacía falta darle el asistente en modo consulta a gente que no es staff — el alumno encargado de un curso, por ejemplo. Con una contraseña compartida eso es imposible en la práctica: se propaga por WhatsApp en una tarde, y rotarla obliga a avisarle de nuevo a todos.

**Un link de invitación de un solo uso no es filtrable.** El admin genera la URL, la persona la abre en su celular, el server quema el token y le deja la cookie. Si lo reenvía, el segundo en abrirlo recibe "link inválido". No hay ningún secreto que se pueda pasar de mano en mano y siga sirviendo, que es exactamente lo que se buscaba.

**El GET no quema el token, el POST sí.** Parece ceremonia y no lo es: WhatsApp, Telegram y el prefetch del navegador hacen un GET al link para armar la vista previa. Con el canje en el GET, el link se consumiría **en el camino** y la persona recibiría un error sin haber tocado nada. La pantalla intermedia además pide el nombre, que es lo que hace útil la lista del panel.

**Se guardan dos identidades y no una**: el nombre lo escribe la persona al canjear, la etiqueta la escribió el admin al invitar. El nombre es autodeclarado y nadie lo verifica — la defensa no es verificarlo, es **mostrar los dos juntos**: que no coincidan es la señal de que el link se reenvió. Para el nivel de riesgo de una escuela alcanza, y verificarlo de verdad exigiría identidad real (Google Sign-In), que se descartó por el costo de setup. Las columnas `email`/`google_sub` quedaron reservadas en la tabla por si algún día se suma.

**Un link = un dispositivo, y el botón `+ OTRO DISPOSITIVO` para el resto.** La alternativa era un link con cupo para N canjes, pero eso reintroduce lo que se quería evitar: reenviado, los cupos se los lleva cualquiera y uno se entera después. El botón genera una invitación nueva con los mismos permisos, y quedan dos filas revocables por separado — si pierde el celular, la notebook sigue andando.

**Sin vencimiento automático, a pedido.** El acceso dura hasta que se revoque. Se evaluó vencer a fin de año lectivo (los alumnos rotan) y se descartó por simplicidad: la columna "último uso" del panel alcanza para repasar la lista una vez al año. Lo que sí vence a los 7 días es el LINK sin usar.

**`GESTION_CLAVE` no se elimina, y es deliberado.** Las `.db` no viajan por git, así que en cada instalación `accesos.db` nace vacía y no hay ningún dispositivo. Sin la clave nadie podría invitar al primero. Es el break-glass, y por eso la sesión de admin lleva la huella de la clave: cambiarla mata todas esas sesiones en el request siguiente.

---

## [2026-08-11] — Los permisos se declaran por área, con un verbo, y los perfiles se derivan

**Contexto**: se viene otro inventario para otra sección de la escuela. La pregunta al diseñar los permisos era qué hay que tocar el día que se sume.

**Con roles cerrados en el gate (`'interno'`, `'interno_gestion'`) la respuesta es "el gate"** — y encima cada persona con una combinación rara obliga a inventar un rol más. Por eso el acceso guarda un **conjunto de permisos** y los perfiles son sólo presets del formulario.

**El truco es que los presets se definen por VERBO, no enumerando claves.** Cada área declara `('laboratorio.leer', '...', 'leer')`, y `'interno-lectura' = ('leer',)` la agarra sola. El día que se sume la sección nueva hay que tocar **una línea** —la lista de `accesos.registrar_app`, que está pegada al `register_blueprint` que ya hay que tocar igual— y los dispositivos ya dados de alta no se migran: simplemente no tienen el permiso nuevo hasta que el admin lo tilde. El gate no se entera.

**`accesos.py` es un archivo nuevo y no un apéndice de `crud.py`** porque nombra otro concepto: `crud.py` es el motor de *entidades*, esto es el motor de *permisos*. Los dos son capa 1 y ninguno nombra un área. `crud.py` importa `accesos` (para decorar sus rutas de escritura), nunca al revés.

**`accesos.db` es una DB aparte y no una tabla en `gestion.db`** por tres razones, y la segunda es la que decide: `DUENOS` en `actualizar.py` **dropea toda tabla que el código no declare para esa DB**. Meter `accesos` en `gestion.db` sin tocar `DUENOS` habría hecho que el próximo `python actualizar.py` borrara todos los dispositivos, en silencio. Esa trampa ya mordió una vez (ver el comentario de `actualizar.py`). Las otras dos: capa 1 no debería conocer la ruta de la DB de un área, y los respaldos son por prefijo.

**`accesos.init_db()` no reusa `crud.init_db`**: aquél hace `raise` si la tabla testigo está vacía y hay respaldos, que es la guarda anti-pérdida del 2026-08-08. Para `accesos.db` una tabla vacía es un estado legítimo — es como nace.

**Los permisos no viajan en la cookie.** Se resuelven server-side con un `SELECT` por request. Si viajaran, revocar un dispositivo no haría nada hasta que la cookie expirara, y revocar en el acto es la única garantía real que da todo este sistema. De paso, el presupuesto de ~4KB ya está compartido con `agente_sid`.

**403 y no un redirect al login** para quien ya entró pero no tiene el permiso. Mandarlo al login es un bucle, y peor: si acierta la clave se convierte en admin. Le concederías todo justo por no tener nada.

---

## [2026-08-11] — Al agente no se le prohíben las tools: no se le mandan

**Contexto**: para el acceso de consulta el pedido fue textual — "que ni las tenga disponibles, no que las tenga prohibidas".

**No es una distinción cosmética, y este agente ya lo había demostrado.** Con una tool prohibida el modelo la intenta, se come el error y a veces igual contesta "✅ Recurso eliminado" — el mismo síntoma que motivó `_escritura_no_ejecutada` en `filtros.py`. Una tool que **no está en la lista** el modelo no la anuncia, no la promete y no alucina haberla usado. Por eso el filtro está en `tools_permitidas()`, antes de la llamada a la API, y no en un `if` dentro del ejecutor.

**El chequeo en `ejecutar_tool` existe igual, como segunda línea**, porque hay un camino que no pasa por el modelo: `/agente/confirmar` ejecuta `crear_entidad` directo desde el botón del chat. Filtrar esquemas no lo protege en absoluto. El default `permisos=None` es fail-closed a propósito: un call site nuevo que se olvide de pasarlo falla cerrado y ruidoso, no abierto y en silencio.

**El permiso de cada tool va en un dict aparte y no como clave dentro de su esquema.** La opción "natural" era `{'name': ..., 'permiso': ...}`, pero `TOOLS_SCHEMA` se manda tal cual a la API y **Anthropic rechaza con 400 cualquier clave de más**. Como el proveedor por defecto es DeepSeek —que traduce copiando tres claves explícitas— ese bug habría sido **invisible en desarrollo** y habría aparecido recién al cambiar de proveedor. Con el dict aparte, `TOOLS_SCHEMA` sigue siendo exactamente lo que las APIs esperan y no hay nada que limpiar. Se pierde la localidad (el permiso no está al lado de la tool) y se gana que las 25 se lean juntas en 25 líneas, más una verificación al importar que revienta si alguna quedó sin declarar.

**El system prompt también se recorta, y `escribe` se deriva de las tools que se mandaron, no de los permisos.** Si saliera de los permisos, un bug en el filtrado dejaría al prompt explicando el circuito de alta mientras las tools de alta no viajaron — el modelo describiría un procedimiento que no puede ejecutar, que es la receta de la alucinación que se está tratando de matar. Derivándolo de la lista real, las dos mitades del mensaje no pueden contradecirse.

**`prompt.py` se partió en bloques con un script, no a mano.** Son ~300 líneas afinadas donde una palabra cambiada degrada al agente sin que se note. La prueba de que salió bien es que `escribe=True` produce el prompt anterior **byte a byte**, incluido el orden de las secciones.

---

## [2026-08-11] — Un turno no se deduce: si el modelo lo va a decir, tiene que estar escrito

**Contexto**: un usuario preguntó por la preceptora de 7° 6 y el agente contestó bien — titular Magali Bruno (vespertino), contraturno Juan Pablo. Repreguntó "¿a la mañana?" y contestó "Juan Pablo. Es el contraturno de 7° 6, que cursa a la tarde". Dos errores en una línea: 7° 6 cursa **vespertino** (lo había dicho él mismo un mensaje antes) y Juan Pablo es el de **tarde**. La respuesta correcta era que a la mañana **no hay nadie cargado**.

**No fue una distracción del modelo: no tenía cómo contestar bien.** Los resultados de las tools no se persisten en el historial (`agente/rutas.py`: sólo se guarda el texto final del asistente). En el turno 2 el contexto era el system prompt, la pregunta original, la respuesta anterior —donde nunca se escribió que Juan Pablo fuera de tarde— y "¿a la mañana?". La palabra TARDE no existía en ninguna parte. Y como creía saber la respuesta, no volvió a llamar la tool.

**Lo que sí estaba en contexto era una regla falsa.** El system prompt decía "cada curso tiene un preceptor TITULAR (el de su turno) y **uno de CONTRATURNO**". Los turnos son tres, y hay **12 cursos de 64 con dos contraturnos a la vez**. Bajo la regla binaria, con "titular = vespertino" y "contraturno = Juan Pablo" en el historial, "Juan Pablo" era la única deducción consistente al preguntar por la mañana; después racionalizó hacia atrás ("que cursa a la tarde") para que cerrara. El mismo singular estaba en `NOTA_TURNOS` y en el esquema de la tool. **Una simplificación en el prompt no es inocua: el modelo la usa como premisa y deduce con ella.**

**Por qué el turno del curso va como campo y no inferido**: `turno_del_curso` se podía sacar leyendo el `turno` de lo que cayera en `titular` — salvo en los 7 cursos donde `titular` viene vacío, donde no se puede. Un dato que el modelo va a afirmar en voz alta no puede depender de una inferencia que a veces no tiene insumos. Cuesta un campo.

**Por qué `turnos_sin_nadie` existe**: la ficha se armaba recorriendo las filas que hay, así que un turno sin filas no aparecía. "A la mañana no hay nadie" era **incontestable** con ese payload: no había diferencia entre "no hay nadie" y "no te lo estoy diciendo". Es el mismo principio del bug de los préstamos de esta misma fecha — un dato negativo tiene que ocupar lugar—, y acá se ve más claro porque el SPA nunca tuvo el problema: `renderizarPreceptor` pinta las tres ranuras `T.M / T.T / T.V` y la vacía se ve vacía. La versión del agente había perdido justamente eso al colapsar tres turnos en dos baldes.

**Por qué la regla de re-llamar va en el prompt y no en la `instruccion` de la tool**: la `instruccion` viaja en el `tool_result`, que se descarta al terminar el turno. En la repregunta —el momento exacto en que falla— ya no está. El prompt es lo único que sobrevive, así que la regla "cualquier pregunta por un turno concreto obliga a volver a llamar `preceptores`" tiene que vivir ahí. Regla general para este agente: **lo que haga falta en el turno N+1 va en el prompt o queda escrito en la respuesta; en el resultado de una tool no queda nada.**

**Lo que se descartó**: hacer que el agente nombre siempre el turno al mencionar un preceptor ("Juan Pablo (tarde)"). Habría dejado el dato en el historial y arreglado este caso, pero atarle el formato de salida a una limitación del almacenamiento es frágil —y ensucia todas las respuestas para cubrir una repregunta que puede no llegar—. Forzar la re-llamada va al problema.

**Lo que no se cambió**: los 7 cursos donde `config.TURNO_CURSOS` nombra un turno que la planilla no tiene ninguna fila (3° B, 4° 6, 4° 7, 5° 2, 6° 3, 6° 7, 7° 5), que son los que devuelven `titular` vacío. No es un bug de código: hay que preguntar en la escuela si está viejo el config o falta cargar gente en el Sheet. Queda como tarea #23, con la lista.

---

## [2026-08-11] — `recursos.estado` es un derivado, y los derivados tienen un solo dueño

**Contexto**: al castigar el circuito de préstamos con casos parciales (prestar 4, devolver 1, reabrir, borrar) apareció que `recursos.estado` mentía en casi todos los caminos. Un recurso entero adentro del pañol figurando 'Retirado', y unidades afuera figurando 'Disponible'.

**Por qué pasaba**: 'Retirado'/'Disponible' es una función de los préstamos abiertos, pero se guarda en una columna, y cada camino de escritura tenía su propia versión de cómo mantenerla — cinco lugares, cinco criterios. El peor era el botón "devolvió" de la web: setea `fecha_devolucion` y recién después llama a `_recalcular_estado()`, que sólo marcaba 'Disponible' dentro de la rama "el préstamo pasa de abierto a cerrado". Como ya estaba cerrado, no entraba a ninguna rama y los recursos quedaban 'Retirado' para siempre. El alta del agente directamente no lo marcaba (la de la web sí), y borrar un préstamo abierto dejaba todo 'Retirado' sin ningún préstamo que lo justificara.

**La decisión**: una sola función, `sincronizar_estado(cur, rid)`, que no recibe "qué pasó" sino que **mira el estado actual** (`pendiente_afuera`) y escribe la conclusión. La llaman los cinco caminos. Un derivado con un solo dueño no se puede desincronizar por un camino nuevo que se olvide de actualizarlo; con cinco dueños, es cuestión de tiempo. La sincronización de recursos salió además de adentro de los `if` de `_recalcular_estado`: el estado del recurso **no depende de que el préstamo haya cambiado de estado** — devolver 1 de 4 cosas no cierra el préstamo, pero esa una ya volvió.

**Qué respeta**: sólo devuelve a 'Disponible' lo que él mismo puso en 'Retirado', así no pisa un 'En reparación' cargado a mano, y nunca toca 'De baja'.

**Sobre-préstamo: se avisa, no se bloquea**. El tope del alta compara contra el stock total, no contra lo disponible, así que se puede prestar dos veces la única caladora. No se bloqueó: el inventario de la escuela puede estar desactualizado y el pañol sabe mejor que la DB — negarse a registrar un préstamo que ya ocurrió en la vida real haría que la gente deje de cargarlos, que es peor. Lo que sí se agregó es que `crear_prestamo` devuelva `ajustes` con lo que salió distinto de lo pedido, para que el asistente lo diga en vez de confirmar en silencio.

---

## [2026-08-11] — Lo que el agente lee por JSON no puede depender de una marca por ausencia

**Contexto**: Emilio informó que un multímetro estaba prestado a Lucas Garcia "desde el 21 de julio" y, cuando le pidieron anotar la devolución, contestó que no existía ese préstamo. Las dos respuestas salieron de la misma base. El préstamo estaba cerrado hacía semanas; lo que falló fue cómo se lo contamos.

**Las dos causas, que son la misma**: la sección "Historial de préstamos" de `gestion.secciones_detalle()` marcaba con `· EN PRÉSTAMO` los abiertos y **no marcaba nada** en los cerrados, y `_detalle_entidad_fmt` la publicaba bajo la clave `prestamos`. En la página web eso se lee bien: el título dice "Historial" y las filas marcadas saltan a la vista. En el JSON que ve el modelo quedaba `"prestamos": [{"nombre": "Lucas Garcia — 2026-07-21 03:55"}]` — el título se pierde, la ausencia de marca no significa nada, y lo que queda es una lista de préstamos con el nombre de una persona y una fecha.

**Por qué el estado va escrito en las dos ramas del `CASE`**: un dato negativo tiene que ocupar lugar. "Sin marca = devuelto" es una convención que sólo existe en la cabeza de quien escribió el SQL y que se pierde en cuanto el dato cambia de medio. Cuesta seis palabras y sirve igual en la web (el historial ahora dice cuándo volvió cada cosa).

**Por qué la clave sale del título cuando el slug no es una entidad**: `prestamos` figura como `slug` de esa sección por una razón de routing — que el template genérico arme el link a `/gestion/prestamos/<id>` —, no porque sea una entidad de `ENTIDADES`. Ese detalle interno estaba decidiendo qué palabra leía el modelo. Ahora la clave es el slug sólo cuando es un slug de verdad (y el modelo puede pasarlo a otra tool); si no, manda el título, que dice qué es la sección.

**El daño colateral que apareció al mirar**: el `ALTER TABLE` que agregó `cantidad_devuelta` la dejó en `'0'` para todos los ítems, incluidos los de préstamos ya cerrados. Esas filas quedaron como "devuelto pero con todo pendiente" — una contradicción latente: al primer `_recalcular_estado()` el préstamo se reabría solo y el recurso volvía a figurar afuera. Se agregó a `migrar()` un `UPDATE` idempotente que empareja `cantidad_devuelta = cantidad` donde `fecha_devolucion <> ''`. **Una migración aditiva no termina en el `ALTER`**: si la columna nueva participa de un invariante, hay que backfillear las filas viejas o el invariante nace roto.

**Lo que no se cambió**: `listar_prestamos(persona)` sigue filtrando con `LIKE '%persona%'`, que es sensible a acentos ("García" ≠ "Garcia"). No fue la causa acá — el préstamo estaba cerrado y no tenía que aparecer —, pero es un pozo real; queda como tarea, no como parche apurado.

---

## [2026-08-11] — Los cargos y los preceptores entran por tools propias, no al padrón difuso

**Contexto**: el agente no podía contestar "¿qué EMATP hay?" ni "¿quién es el preceptor de 3° B?". Los datos estaban en `escuela.db` desde siempre: `personal_no_docente` tiene una columna `rol`, y `horarios_preceptores` tiene 595 filas con la planilla entera.

**Por qué la búsqueda por cargo es una tool aparte y no un parámetro de `buscar_profesor`**: son dos preguntas distintas. `buscar_profesor` resuelve *un nombre que el usuario dijo mal*; `buscar_por_rol` resuelve *una función dentro de la escuela*, donde el usuario no tiene ningún nombre. Meter las dos en la misma tool obliga a puntuar nombre y cargo en la misma escala, y entonces "ematp" empieza a traer docentes que se escriben parecido. Lo que sí se hizo es que el `rol` viaje pegado al nombre en todas las respuestas: el padrón ya lo tenía y tirarlo era el bug original.

**Por qué no hay diccionario de siglas**: el cargo dice `EMATP EERR` y el usuario dice "energías renovables"; ningún algoritmo que compare letras une esas dos cosas. La alternativa era un mapa `EERR → energías renovables` en el código, que hay que mantener cada vez que la escuela crea un cargo y que igual se queda corto ante la sigla siguiente. En vez de eso, cuando la búsqueda por rol falla la tool devuelve el padrón **completo** de cargos y deja que el modelo reconozca la sigla — que es exactamente lo que un LLM hace bien y una comparación de strings no. Es la misma decisión que `buscar_entidad` → `listar_todos` (2026-08-08), y acá sale aún más barata: son cuatro cargos, ~60 tokens.

**Por qué los preceptores no entran al padrón difuso**: sus nombres están cargados a mano y sin normalizar ("ANGELINA", "KARINA (M RIOS)", "PTRICIA MAGALLANES", "FALTA"). Sumarlos a `_padron_horarios()` habría degradado todas las sugerencias de `buscar_profesor`, que es la tool más usada, para arreglar una pregunta que se hace mucho menos. Entran por una tool propia, y para que igual se los **encuentre** por nombre, `buscar_profesor` y `horario_profesor` cruzan contra ellos y devuelven un aviso lateral que apunta a esa tool — el mismo patrón que ya existía para las personas con ficha.

**Por qué la tool de preceptores devuelve la planilla digerida y no las filas**: la tabla cruda es una fila por curso × turno × día. Mandársela al modelo es pedirle que agrupe 595 filas y que decida solo qué significan dos nombres en el mismo curso. En vez de eso se manda una ficha por curso con `titular` y `contraturno` ya separados (usando `config.TURNO_CURSOS`, el mismo criterio que el SPA), los días solo cuando no son los cinco, y `sin_asignar` donde la planilla dice "FALTA". La regla general: el agente decide con datos interpretados, no con SQL crudo.

**Por qué las grafías se agrupan por conjunto de palabras y no por parecido**: "ROMERO VANESA" y "VANESA ROMERO" son la misma persona cargada dos veces, y separadas hacían que la búsqueda pidiera desambiguar entre dos opciones idénticas y mostrara la mitad de sus cursos. Agrupar por *token set* las une sin riesgo. Agrupar por similitud habría unido también "DANIELA TRAJO" con "DANIELA TREJO" — que probablemente también sean la misma persona, pero fusionar por parecido puede unir a dos distintas, y ese error es mucho más caro que dejar un duplicado a la vista.

**Costo aceptado**: +643 tokens de esquemas en **cada** round-trip de tool (de ~7.250 a ~7.900). Se paga porque cierra dos agujeros que hoy se responden mal — y uno de ellos, el de preceptores, el system prompt ya lo prometía sin tener con qué cumplirlo.

---

## [2026-08-10] — Las migraciones que cruzan las dos DBs van a un script, no al hook `migrar()`

**Contexto**: el hosting (PythonAnywhere) conserva los `.db` entre deploys y los `.db` están en `.gitignore`. Eso es lo que salva los datos en cada `git pull`, pero también significa que el archivo puede venir de un schema de hace tres refactors. Al preparar el deploy del split en cuatro áreas apareció que dos migraciones ya hechas en desarrollo no tenían forma de llegar al servidor.

**Por qué no van en `migrar(cur)`**: el hook recibe un cursor de la DB del área y nada más. Mudar `hitos` de `gestion.db` a `historia.db` necesita las dos abiertas a la vez, y que un área abra la DB de la otra rompe justo la regla que sostiene la separación (`historia.py` no importa `gestion.py`, y viceversa). Meterlo igual habría convertido el hook en la primera excepción, que es como se empiezan a filtrar las demás.

**Por qué un script de consola y no un módulo de capa 0**: no es maquinaria reutilizable, es un procedimiento fechado — nombra `proyectos`, `persona_proyectos` y el mapeo exacto de sus columnas. Capa 0 es explícitamente lo que **no** nombra nada del dominio. Vive arriba de todo, como `init_gestion.py` / `init_historia.py`, y se corre a mano.

**Por qué se mantiene en vez de borrarlo como el anterior**: la migración `proyectos` → hito ya se había hecho una vez con `migrar_proyecto_a_hito.py`, borrado después "porque queda en el historial de git". No quedó: nunca se commiteó, y al preparar el deploy hubo que reconstruir el mapeo leyendo schemas viejos con `git show`. Un script de migración se conserva mientras pueda existir una instalación que no lo corrió, y eso no se sabe hasta que todas están al día.

**Por qué la limpieza compara contra el `SCHEMA` del código y no contra una lista**: una lista de "tablas que sobran" hay que acordarse de actualizarla, y el día que no pasa, la sobra queda. Ejecutar el `SCHEMA` en una DB en memoria y preguntarle con los mismos `PRAGMA` que a la DB real hace que la comparación sea exacta por construcción y no envejezca. El precio es que la referencia tiene que incluir **todos** los dueños de esa DB: `gestion.db` la comparten `gestion.SCHEMA` y `agente.db.SCHEMA`, y con uno solo la limpieza borraría las tablas del asistente.

**Por qué borrar lo vacío pero pedir `--limpiar` para lo que tiene datos**: es el mismo criterio con el que se eliminó `drive_url` (se verificó que estaba vacía en las 89 filas antes de tocarla). Una tabla que sobra pero tiene filas es casi siempre una migración que nadie corrió; borrarla en silencio sería exactamente el accidente que el script existe para evitar.

---

## [2026-08-10] — Un solo reloj (`config.ahora()`), y la hora también pegada a cada mensaje del chat

**Contexto**: el agente contestaba con la hora 3 horas adelantada. La causa no era el prompt: `datetime.now()` en Render devuelve UTC, y toda la app la usaba directo.

**Por qué el reloj va en `config.py` y no en un `reloj.py` nuevo**: no nombra ninguna tabla ni ruta, así que es capa 0; y la zona horaria es configuración de la institución, del mismo tipo que `DIAS` o el branding. Un archivo nuevo por una función de cuatro líneas es peor que la línea de más en el archivo que ya existe. Si algún día hay más lógica de calendario escolar (feriados, turnos), ahí sí conviene separarla.

**Por qué devuelve un datetime naive**: todo el código compara y formatea contra fechas guardadas en SQLite como texto sin tzinfo. Devolver un datetime consciente hace que cualquier resta contra una fecha de la DB tire `TypeError`, y el bug aparecería en un préstamo viejo, no al probar.

**Por qué hay fallback a offset fijo −3**: `zoneinfo` en Windows necesita el paquete `tzdata` y no está en `requirements.txt`. Antes que agregar una dependencia para el entorno de desarrollo, se cae a `-3`: Argentina no aplica horario de verano desde 2009, así que es el mismo valor. Si eso cambia, el fallback deja de servir y hay que instalar `tzdata`.

**Por qué la hora va TAMBIÉN pegada al mensaje y no solo en el system prompt**: el prompt ya la interpolaba y se rearma en cada turno, así que el dato estaba fresco. El problema es de atención: son ~15.000 tokens de prompt y la hora queda arriba de todo, lejos de lo último que el modelo lee. Con la conversación crecida contestaba "ahora" con la hora del primer mensaje. El sello al final del mensaje del usuario es lo último en el contexto y, como se persiste en el historial, además le da algo que el prompt no puede darle: **cuánto tiempo pasó entre un mensaje y otro**.

**Por qué el sello se filtra en `_texto_visible()` y no se guarda aparte**: la misma razón que el `(refiriéndote a: X)` — tiene que estar dentro del texto para que el modelo lo lea en su lugar, y afuera de lo que se repinta para que el usuario no vea algo que no escribió.

## [2026-08-10] — `agente.py` pasa a paquete `agente/`, cortado por cohesión y no por capa

**Contexto**: el asistente era un único archivo de ~4.000 líneas. No estaba desordenado —tenía secciones marcadas y naming consistente— pero encontrar algo requería grepear, y era 2× más grande que cualquier otro módulo del proyecto.

**Por qué NO se separó "un archivo de descripciones de tools" de "un archivo de código de tools"**, que era la propuesta inicial: una tool vive en dos lugares que tienen que coincidir (su esquema, que es lo único que el modelo ve, y su ejecutor). Mandarlos a archivos distintos convierte "agregar una tool" en tocar dos archivos en vez de uno: **empeora** justo el problema que el corte quiere resolver. Organizar por capa (schemas / código / prompts) maximiza cuántos archivos se tocan por cambio. Se cortó por **lo que cambia junto**: `tools/horarios.py`, `tools/prestamos.py`, etc. llevan esquema y ejecutor adentro.

**Por qué `padrones.py` está fuera de `tools/`**: los dos padrones de personas se usan desde las tools (horarios, entidades, fichas, préstamos) **y** desde el system prompt, que inyecta la lista de personas conocidas. Además `_docentes_parecidos` necesita `_buscar_profesor_scored` y `_buscar_profesor` necesita `_personas_parecidas`: dejarlos en dos módulos distintos crea un ciclo de imports. Juntos, el grafo queda en una sola dirección.

**Por qué el módulo de config se llama `proveedores.py`**: hay un `config.py` en la raíz del proyecto (SHEET_ID, DIAS, branding) que el paquete también importa. Con imports absolutos de Python 3 no se pisan, pero leer `from config import DIAS` al lado de `from .config import _get_config` es una trampa para el que viene después.

**Lo único que cambió de comportamiento**: nada. Se verificó que los 135 nombres top-level siguen existiendo, que ninguna de las 91 funciones referencia un global inexistente, que las rutas Flask son las mismas y que el system prompt renderiza **byte a byte idéntico**. Se eliminó una reasignación duplicada de `HISTORIA_UMBRAL` (mismo valor, código muerto).

**`RAIZ` (en `dominio.py`) es obligatorio**: las rutas a las DB y a `historias/` se calculaban con `dirname(abspath(__file__))`. Dentro del paquete eso apunta a `AppMitre/agente/`, y SQLite **no falla**: crea una `gestion.db` vacía ahí. Es el error que no se nota hasta que falta el inventario entero.

## [2026-08-10] — El horario no docente se **suma** al de clases, y los preceptores quedan afuera del padrón difuso

**Contexto**: `horario_profesor` leía solo `clases`. El personal de `personal_no_docente` (EMATP, jefaturas) quedaba invisible para el agente, aunque el SPA ya lo fusiona en su autocompletado.

**Por qué merge y no fallback**: la lectura fácil era "si no hay clases, buscá en no docentes". No alcanza: hay gente en las dos tablas (RODRIGUEZ VIRGINIA da física y es EMATP de biología, RAPP CARINA da sociales y es jefa de preceptores). Con fallback, esa gente seguía perdiendo la mitad de su agenda y encima de forma silenciosa. Por eso `_horario_no_docente()` se consulta **siempre** y sus claves van al lado de `clases`, nunca en lugar de ellas.

**Por qué van en claves separadas y no mezcladas por día**: son cosas distintas —una clase tiene materia, curso y aula; un turno no docente es presencia— y aplanarlas en el mismo `{día: [...]}` invita al modelo a inventar una materia. Separadas, más el `aviso_no_docente`, tiene que contar los dos horarios y no puede confundirlos.

**Por qué los preceptores (`horarios_preceptores`) NO entran al padrón**: sus nombres vienen del Sheet sin normalizar y a veces sin apellido — "ANGELINA", "KARINA (M RIOS)", "PTRICIA MAGALLANES", "FALTA". Metidos en `_padron_horarios()` contaminarían las sugerencias de `buscar_profesor` con entradas que no son personas identificables, y el umbral 0.6 las traería seguido. Si algún día se limpian en origen, entran sin más cambio que agregarlas ahí.

## [2026-08-10] — El celular no tiene un layout propio: el mismo HTML, con el nav movido a un panel

**Contexto**: el shell de `/gestion`, `/historia` y `/agente` estaba pensado para monitor: header con 5 botones, nav de hasta 8 pestañas, tablas de 5 columnas. En un teléfono eso son tres filas de botones antes de ver contenido, y listados que se leen scrolleando de costado con los botones de acción afuera de la pantalla. La escuela los usa mayormente desde el teléfono.

**Decisión**: **no** hay templates ni rutas para celular. Es el mismo HTML servido a todos, con dos capas encima que solo existen abajo de 900px: media queries en `gestion.css` y `static/mobile-nav.js`, que arma un menú lateral ocultable. Arriba de 900px el escritorio queda **exactamente** como estaba — era el requisito explícito del pedido.

**Por qué mover los nodos y no clonarlos**: la alternativa obvia (renderizar el nav dos veces, una visible en desktop y otra en el panel) duplica `#agente-toggle-btn` y el badge del carrito, y obliga a que `gestion.js` y `gestion-agente.js` sepan que ahora hay dos de cada cosa. Moviendo el nodo, los listeners que ya se engancharon viajan con él y no hay ningún id repetido. El costo es un acoplamiento de orden: `mobile-nav.js` tiene que cargar **después** de los scripts que enganchan cosas adentro de esos bloques (así está en los tres `base.html`), porque los `DOMContentLoaded` corren en orden de registro.

**Por qué un panel lateral y no un nav colapsable en su lugar**: en el chat (`/agente`) la pantalla es el recurso escaso — el nav en la página se comía una franja permanente aunque estuviera plegado. Sacándolo del flujo, el chat se queda con toda la altura. Y al ser un panel, entran también los botones del header (SALIR, PRÉSTAMO, cambiar de área), que es lo que antes envolvía en tres filas.

**Por qué los listados pasan a tarjetas abajo de 700px**: el scroll horizontal dentro de `.g-table-wrap` "funciona" pero esconde justo la última columna, que es la de acciones (RETIRAR, Ver, Editar). En una tarjeta entra todo sin scroll. Se implementó con `display: block` sobre la tabla y `content: attr(data-label)` — la tabla real no se toca, así que el escritorio, el `[hidden]` de la búsqueda en vivo y el HTML semántico siguen intactos. Entre 700 y 900px (tablet) sigue siendo tabla: ahí las columnas entran.

**Se mantiene el fallback sin JS**: sin `mobile-nav.js` no hay panel y el nav queda en la página envolviendo, que es el comportamiento de siempre. Por eso también sobrevive la regla vieja `body.g-chat-page .g-nav` que lo hacía scrollear en horizontal.

---

## [2026-08-10] — Las fotos de una ficha se miran en un visor y se borran por posición

**Contexto**: la galería del detalle era solo miniaturas recortadas (`object-fit: cover`) y nada más: no se podía ver la foto entera —justo lo que uno necesita cuando la foto es la etiqueta de un equipo o el número de serie— ni sacarla si se subió al recurso equivocado. Subir era un camino de una sola dirección.

**Decisión**: un lightbox en la propia ficha (click en la miniatura → foto completa, contador `n / total`, flechas ‹ ›/teclado, Esc o click en el fondo para cerrar) con el botón **ELIMINAR** adentro. Sin página aparte ni ruta nueva de lectura: la foto ya está en el HTML como data URI, así que abrirla no cuesta un request.

**Por qué borrar por índice y no por id de foto**: `fotos` es un array JSON dentro de la fila (`{b64, tipo, fecha}`), no una tabla — las fotos no tienen id. La alternativa era darles uno y migrar todas las galerías existentes, para resolver un solo caso: dos pestañas borrando a la vez sobre la misma ficha, que en una escuela con una persona cargando inventario no pasa. `POST /<slug>/<id>/foto/<indice>/eliminar` con índice fuera de rango **no es error**: ignora y vuelve a la ficha, que es el resultado correcto igual.

**Por qué el borrado es un `<form>` con redirect y no `fetch`**: el resto del módulo es server-rendered con forms + redirects; el `POST` → `redirect` al detalle deja la galería consistente sin tener que reindexar nada en el DOM. El único JS es el visor.

**El botón ELIMINAR vive solo adentro del visor**, no como una ✕ sobre cada miniatura: en un grid denso de fotos chicas, una cruz al lado del thumb se toca sin querer, y borrar sin haber visto la foto entera es exactamente cómo se borra la que no era.

**Duplicado en `/historia`**, como todo el motor CRUD (ver la entrada de las cuatro áreas): misma ruta, mismo JS inline en su `detalle.html`. El CSS sí es compartido (`gestion.css`).

---

## [2026-08-10] — Gestión e historia dejan Drive: la DB es la fuente de verdad. Horarios no cambia

**Contexto**: el diseño original repartía la verdad en dos lugares. Los archivos —fotos, planos, guías— vivían en Google Drive y cada entidad guardaba un `drive_url` apuntando a su carpeta; la DB era un índice de metadatos. La escuela dejó de usar Drive.

**Decisión**: **`gestion.db` e `historia.db` son la fuente de verdad de sus dominios.** Lo que no está en la base, no está. Se eliminó `drive_url` de las cinco tablas.

**Por qué eliminar la columna y no dejarla vacía**: un campo muerto en el formulario no es gratis. Alguien lo va a completar, y a partir de ahí hay datos que la app muestra pero que nadie mantiene ni respalda — exactamente el problema que se quería cerrar. Además la columna arrastraba una explicación en cada lugar donde aparecía (ayuda del form, botón de la ficha, texto del home, descripción de la tool del agente). Se verificó antes de correrla: **0 de 95 filas** tenían link cargado, así que el DROP no perdió nada. Es la primera migración destructiva del proyecto; se apoya en que `respaldar_db()` corre en `init_db()` **antes** de `_migrar()`, o sea que el respaldo con la columna queda hecho justo antes de eliminarla.

**Lo que NO cambia, a propósito: el sistema de horarios.** `escuela.db` se sigue generando desde Google Sheets con `/api/actualizar` y **Sheets sigue siendo su fuente de verdad**. Son dos modelos opuestos conviviendo en la misma app, y está bien: la planilla de horarios la cargan y editan varias personas fuera del sistema, con herramientas que ya usan, y la app es un visor; el inventario y la historia se cargan *desde* la app y no existen en ningún otro lado. Regenerar `escuela.db` desde cero es la operación normal; hacer lo mismo con `gestion.db` sería perder todo.

**Consecuencia a vigilar**: al pasar a ser la única copia, `gestion.db` e `historia.db` dejan de tener red externa. Ya estaban en `.gitignore` y se pierden en un hosting efímero (Render). Los respaldos rotativos de `backups/` (20 copias, con dedup por hash) pasan de ser una comodidad a ser lo único que hay — y ahora también cargan con las fotos en base64, que es lo que más pesa. Ver la discusión sobre el almacenamiento de fotos en `agent_docs/gestion-conocimiento.md`.

**Contexto**: `app.run(..., use_reloader=False)` obligaba a reiniciar a mano después de cada cambio en un `.py`, y el olvido no se manifiesta como un error sino como **"el cambio no funciona"**: el proceso viejo sigue sirviendo el código anterior. En Windows se disimula todavía más, porque Werkzeug abre el socket con `SO_REUSEADDR` y un segundo `python app.py` **arranca sin error** aunque el 5000 ya esté tomado — queda sin tráfico, y contesta el más viejo de los dos. Pasó de verdad al verificar el arreglo de fotos del agente: el código nuevo estaba en disco, el proceso de dos horas antes contestaba con una constante que ya no existía.

**Decisión**: `use_reloader=True`, y el bloque de arranque (`init_tablas` + carga desde Sheets) detrás de `if not os.environ.get('WERKZEUG_RUN_MAIN')`.

**Por qué la guarda**: con el reloader, Werkzeug corre el proceso padre y levanta un hijo —marcado con `WERKZEUG_RUN_MAIN`— que es el que sirve y el que se relanza entero en cada guardado. Sin la guarda, el bloque de arranque se ejecutaría en cada Ctrl+S. `init_tablas()` es idempotente y lo aguantaría, pero revisar la base y eventualmente **bajar todo de Google Sheets** en cada guardado no. Con la guarda corre una sola vez, en el padre. Sin reloader la variable no existe, así que el bloque corre igual y producción (gunicorn, que ni pasa por acá) no se entera.

**El costo aceptado**: si un `.py` queda guardado con un error de sintaxis, el reloader lo detecta, falla al importar y el server queda esperando el próximo guardado en vez de morir — pero si el error es en tiempo de import de un módulo pesado, hay que relanzarlo a mano. Es mucho más barato que depurar un cambio que "no aplica".

---

## [2026-08-10] — Quién decide qué hacer con una foto: el modelo, no un `if` en el backend

**Contexto**: `chat()` cortaba el turno con un aviso fijo cuando llegaba una foto y no había con qué leerla. El razonamiento original era sólido —sin visión el modelo contestaría igual, inventando lo que "leyó" en la etiqueta, que es el peor resultado posible para un inventario— pero descansaba en una premisa falsa: **que toda foto se manda para ser leída**. No es así. El caso más común en el taller es adjuntar una foto a la ficha de algo que ya existe, y para eso no hace falta ver la imagen: el base64 va del `contexto_turno` a la galería sin pasar por el modelo. El corte dejaba `adjuntar_foto` inalcanzable, y con el default del proyecto (DeepSeek, sin key de visión) eso significaba que mandar una foto no servía para nada.

**Decisión**: que el turno corra siempre y que la distinción "adjuntar" vs. "analizar" la haga el modelo, que es quien entiende la frase del usuario. El backend ya no adivina la intención a partir de la config.

**Por qué `leer_foto` sigue expuesta aunque no haya lector.** La alternativa era filtrarla del `TOOLS_SCHEMA` cuando `_get_vision_config()` es `None`. Se descartó: sin esa tool el modelo no tiene forma de *detectar* que le pidieron analizar, y el pedido de "¿qué dice esta etiqueta?" terminaría en una respuesta inventada o en un silencio raro. Dejándola, el modelo la llama, recibe un error que dice exactamente por qué no se puede y qué ofrecer a cambio, y lo cuenta con sus palabras. Cuesta una vuelta del loop —no una llamada de visión— y DeepSeek cachea el prefijo, así que es despreciable.

**Por qué el aviso lo redacta el modelo y no es un texto fijo.** El mismo motivo por el que leer es una tool y no un paso automático: un texto fijo no sabe si el usuario quería adjuntar o analizar, así que o corta de más (el bug que se arregló) o contesta al lado. El error de la tool le da al modelo el dato y las dos salidas posibles (que le dicten los datos, o que le digan a qué ficha guardarla) y él elige según lo que se venía hablando.

**Se distingue "no hay lector" de "el lector falló"** aunque `_leer_imagen()` devuelva `None` en los dos casos: para el usuario son cosas distintas —una se arregla cargando una API key en el servidor, la otra se arregla esperando un rato— y mandarle "el servicio no respondió" a alguien que nunca configuró un lector lo deja esperando algo que no va a pasar.

**El riesgo que queda**: una foto puede terminar en el recurso equivocado. Se mitiga en el prompt y en la descripción de `adjuntar_foto`, que insisten en preguntar cuando el destino es ambiguo, no en volver a poner un candado en el backend. Desde el visor de fotos de la ficha (ver la entrada del mismo día, más abajo) el error **se puede deshacer**: antes la foto quedaba pegada para siempre.

---

## [2026-08-10] — Cero duplicación, con un criterio de pertenencia por capas

**Reemplaza a la decisión de más abajo del mismo día** ("Cuatro áreas separadas físicamente, con el motor CRUD duplicado"). Aquella se implementó y funcionó; el requisito cambió el mismo día.

**Contexto**: la separación en cuatro áreas dejó ~378 líneas de Python repetidas entre `gestion.py` e `historia.py` (motor CRUD, respaldos, galería de fotos, gate de sesión, normalización) más ~270 de Jinja entre sus templates genéricos. Se aceptaba a cambio de que borrar un área no rompiera la otra.

Lo que hizo caer esa decisión no fue el volumen sino **un problema activo que la duplicación ya estaba causando**: `agente.py` llamaba 14 veces a `gestion._norm` y 1 vez a `historia._norm`, sin criterio — pedía la misma función privada a un módulo o al otro según cuál tuviera más a mano quien escribió la línea (`agente.py:791` usaba la de gestión sobre lore; `:1357` la usaba sobre nombres de personas, que son datos de historia). Funcionaba **sólo porque las dos copias eran idénticas carácter por carácter**. El día que alguien tocara una, el agente iba a devolver peores resultados de búsqueda en la mitad de los casos, sin tirar excepción. Eso no es duplicación prolija: es una dependencia compartida sin dueño declarado.

**Decisión**: eliminar la duplicación con tres capas y **una sola pregunta para ubicar cualquier función: ¿qué nombra?**

| Capa | Regla | Archivos |
|---|---|---|
| 0 | No nombra tablas, ni entidades, ni rutas, ni Flask | `config.py`, `texto.py`, `respaldos.py` |
| 1 | Conoce el *concepto* de entidad, ninguna concreta | `crud.py`, `templates/crud/` |
| 2 | Nombra tablas y entidades reales; sólo declara | `gestion.py`, `historia.py`, `database.py`+`app.py`, `agente.py` |

**Las tres DBs siguen separadas y sin FK cruzadas.** Lo que se comparte es el código, no los datos: el pedido fue explícito en que `escuela.db`, `gestion.db` e `historia.db` siguen siendo tres.

**Por qué un módulo hoja no viola el criterio anterior**: el criterio real nunca fue "cero archivos compartidos" sino "cero dependencias *entre áreas*". `config.py` ya era la prueba — lo importan los cinco archivos, no importa a nadie, y borrar `historia.py` no lo afecta. `crud.py` mantiene esa propiedad de la única forma que la sostiene: **no importa `gestion` ni `historia`, las recibe como argumento**. Si algún día `crud.py` necesita importar un área, la función que lo obligó está en la capa equivocada.

**Por qué los archivos se llaman `texto.py` y `respaldos.py` y no `util.py`**: un archivo llamado "util" no tiene forma de decirte que algo no pertenece ahí, y termina siendo el cajón donde vuelve a acumularse todo — que es exactamente el acoplamiento del que se venía. Con el nombre describiendo el contenido, nadie mete una función de backup en `texto.py`.

**Todo lo específico de un área entra por hooks declarados** (`migrar`, `seed`, `derivados`, `secciones_detalle`, `valores_iniciales`, `extras_template`, `tarjetas_extra`, `contexto_extra`, `NAV_EXTRA`, `ERROR_DUPLICADO`), nunca por un `if slug == '...'` dentro de `crud.py`. Esa lista **es** la frontera entre capa 1 y capa 2: si algo no entra por un hook, está mal ubicado.

**Lo que NO se movió, a propósito**: los ~380 renglones de préstamos/carrito se quedan enteros en `gestion.py`. No estaban duplicados —son dominio puro de gestión, con ítems por cantidad y ciclo prestado→devuelto que no entra en la config declarativa— así que no había nada que extraer. Sacarlos hubiera sido mover código por prolijidad, no por duplicación.

**El costo aceptado**: `historia.py` ya no funciona sin `crud.py`. Borrar un área dejó de ser borrar sus archivos. A cambio, un fix al motor se hace una vez y no dos, y desaparece la clase de bug que motivó el cambio.

**Se verificó por diff, no por inspección**: se capturó un snapshot en JSON del comportamiento observable (HTML de las 14 rutas, 115 búsquedas con typos, el contenido íntegro de las 6 tablas de dominio, la salida de 18 tools del agente y la normalización de horarios) **antes** de tocar nada, y se comparó después de cada etapa. El riesgo de este refactor nunca fue romper ruidosamente: era correr el orden de un listado, el ranking de una búsqueda o un `nombre_norm` sin que nadie se enterara.

---

## [2026-08-10] — ~~Cuatro áreas separadas físicamente, con el motor CRUD duplicado~~ (SUPERADA)

> **Superada el mismo día por la entrada de arriba** ("Cero duplicación, con un criterio de pertenencia por capas"). Se deja porque explica por qué las cuatro áreas tienen archivo, DB, prefijo y gate propios — eso **sigue vigente**. Lo que ya no vale es la parte del motor duplicado: hoy `gestion.py` e `historia.py` comparten `crud.py`. No "restaurar" la duplicación creyendo que es intencional.

**Contexto**: todo convivía en `gestion.py` (1509 líneas, una DB, un blueprint): el inventario del taller, la línea del tiempo institucional (hitos, personas, proyectos) y —adentro de su prefijo— el asistente. Querer tocar la parte de historia, que es más anecdótica y se retoca seguido, ponía en riesgo la gestión de inventario, que es la que la escuela usa todos los días.

**Decisión**: partir en cuatro áreas con frontera física — horarios (`app.py`), recursos (`/gestion`), historia institucional (`/historia`, `historia.py`, `historia.db`) y asistente (`/agente`) — cada una con su archivo, su prefijo, sus templates y su gate de sesión. **Ningún módulo de dominio importa a otro.**

**El motor CRUD se duplicó en vez de extraerse a una librería común.** El inventario completo de lo que quedó repetido —medido después, función por función, ignorando comentarios— era mayor de lo que decía esta entrada originalmente ("~350 líneas", que se leía como si fuera todo):

| Bloque duplicado | Líneas × 2 |
|---|---|
| Motor CRUD (`_cfg`, `_select`, `_guardar`, helpers `*_sin_request`, M2M, rutas genéricas) | ~200 |
| Respaldos (`_tiene_datos`, `_hash_archivo`, `respaldos`, `respaldar_db`, `_dia`, `_a_borrar`) | ~47 |
| **Galería de fotos** (`agregar_foto`, `subir_foto`, `eliminar_foto`) | ~45 |
| Gate de sesión | ~19 (×3, también en `agente.py`) |
| Normalización y búsqueda difusa | ~24 |
| **Templates genéricos** (`lista/form/detalle/login.html`) | ~270 de Jinja |

O sea ~378 líneas de Python (82% de `historia.py`) más ~270 de Jinja: unas 650 en total, no 350.

**Por qué duplicar y no compartir**: el criterio del pedido era "casi que borrás los archivos de una parte y todo el resto sigue funcionando". Un `entidad_crud.py` compartido cumple el DRY pero no ese criterio: los dos módulos pasarían a depender de un tercero que no se puede borrar ni tocar sin pensar en ambos, que es exactamente el acoplamiento del que se venía. El costo aceptado y conocido: **un bug en el motor (por ejemplo, el umbral de la búsqueda difusa) hay que arreglarlo en los dos archivos**. Con dos copias es manejable; si algún día hay una tercera, conviene revisar esta decisión.

**Lo que sí se comparte, a propósito**: `static/gestion.css` (paleta, identidad visual), `static/gestion-agente.js` y el widget del chat. Nada de eso es lógica de dominio — es cómo se ve la escuela y cómo se habla con el asistente, y ahí la duplicación sería el problema, no la solución.

**Los gates de sesión también están duplicados** (~15 líneas por módulo) y comparten `GESTION_CLAVE` + `session['gestion_ok']`: una sola contraseña abre las tres áreas (es el mismo staff), pero cada `before_request` y cada `/login` viven en su archivo. Si un día una necesita auth propia, se cambia sola.

---

## [2026-08-10] — `proyectos` deja de ser una entidad y pasa a ser una etiqueta de `hitos`

**Contexto**: `proyectos` era la única entidad que ataba las dos mitades del sistema — su tabla `proyecto_recursos` vinculaba un trabajo de un curso con recursos del inventario. Era también la relación que impedía separar las DBs, y la que el pedido marcó explícitamente para eliminar.

**Decisión**: eliminar la entidad. Un proyecto es un hecho de la línea del tiempo como cualquier otro, así que se carga como **hito con `Proyecto` en `etiquetas`**. Se eliminaron `proyectos`, `proyecto_recursos` y `persona_proyectos`; la única fila real se migró a hito conservando fecha, participantes (→ `protagonistas`) y estado (anexado a `descripcion`).

**Por qué `etiquetas` y no un valor de `tipo`**: `tipo` es una lista cerrada de siete valores que clasifica *qué clase de hecho* fue (Evento, Logro, Construcción…). "Proyecto" no es una clase de hecho paralela a esas: un proyecto puede ser una Construcción o un Logro. `etiquetas` es texto libre separado por comas y ya existía para agrupar la línea del tiempo (Olimpiada, Matemática, Nacional), que es exactamente el rol que cumple acá. Además no obliga a elegir: un hito puede ser `tipo: Construcción` **y** llevar la etiqueta Proyecto.

**Qué se pierde**: la navegación "este recurso salió de tal proyecto". Se aceptó a cambio de que las dos DBs queden sin ninguna FK cruzada — que era el punto del pedido. Si volviera a hacer falta, el camino no es reponer `proyecto_recursos` (vuelve a atar las DBs) sino nombrar el recurso en la descripción del hito.

---

## [2026-08-09] — Buscar una persona cruza los dos padrones, y el aviso va en la tool "equivocada"

**Contexto**: el agente maneja **dos padrones de personas que no se superponen**. Los
docentes salen de `escuela.db` (los horarios); las fichas con semblanza, de `personas` en
`gestion.db`. Un alumno que ganó una olimpiada, un egresado o un ex director tienen ficha y
no dan clases; una profesora que nadie cargó todavía da clases y no tiene ficha. **Quien
pregunta por alguien no sabe —ni tiene por qué saber— en cuál de los dos está.**

El usuario dijo "nati fue quien lo logró" mientras se armaba un hito, y el agente contestó
ofreciendo tres docentes —Natalia Suarez, Natalia Tosoroni, Natalia Vazquez— cuando la
persona que había cargado dos turnos antes era **Natalia Boo Fiad**, con ficha. No es que el
modelo buscara mal: buscó bien en el padrón equivocado. Y el prompt lo empuja para ese lado,
porque la sección de préstamos le **inyecta** la lista de docentes y personal no docente
(`_personas_conocidas()`) y nunca le muestra las fichas.

**Decisión**: buscar una persona mira **siempre los dos padrones**, entre por donde entre.
`buscar_profesor` suma `personas_con_ficha`; `buscar_entidad('personas', …)` suma
`en_horarios`. Las dos solo agregan la clave cuando hay coincidencia real, así que los
turnos normales no cambian ni suman ruido.

Lo no obvio es **dónde** vive el aviso: en el resultado de la tool que el modelo eligió
*mal*, no solo en el prompt. Para cuando llegó a `buscar_profesor` ya tomó la decisión; una
regla en el prompt sobre cuál padrón usar solo sirve si la recuerda **antes** de elegir la
herramienta, y este agente esas reglas las cumple a veces. Lo único que lo corrige a tiempo
es lo que la herramienta mal elegida le conteste. El prompt igual se tocó, pero como
refuerzo, no como mecanismo.

**La dirección inversa importa igual**: sin ficha pero con docentes que coinciden, el agente
respondía "no la tengo cargada" con la persona dando clases en la escuela. Ese aviso se lo
prohíbe explícitamente y le da dos salidas: resolver el horario con ese nombre, o proponer
crearle la ficha. Es la diferencia entre "no existe" y "todavía nadie la cargó".

**Tres umbrales distintos, a propósito**, porque son tres consecuencias distintas:
- `_personas_nombradas_en()` exige el **nombre completo**: de ahí salen los vínculos
  `persona_hitos` que se escriben solos, y vincular a la persona equivocada es peor que no
  vincular.
- `_coincide_fuerte()` (los cruces) pide substring **o** similitud palabra por palabra ≥
  `UMBRAL_SIMILITUD` (0.68). Lo peor que puede pasar es ofrecer un candidato de más, así que
  se permite el difuso — pero no el de las búsquedas normales.
- `_buscar_profesor_scored()` usa 0.6 y sigue igual: su trabajo *es* ofrecer candidatos.

Ese punto medio no es cosmético. Con 0.6, el cruce de "nati" traía PETRATE MATIAS (0.60
contra "matias") y el de "calei" traía PRIETO VALERIA — la misma clase de candidato absurdo
que el aviso existe para evitar. Y con substring solo, se perdía "nati" → "Natalia": los
apodos del castellano **no son prefijos**, y ése era justo el caso a resolver.

---

## [2026-08-09] — Los botones de confirmar vuelven todos, cada turno, deduplicados por entidad

**Contexto**: el alta en dos pasos ya guardaba **todas** las fichas del turno en
`agente_conversaciones.fichas`, pero `/chat` le mandaba al front una sola —`ultima_ficha`—.
Pedir "creá a Pablo y a Ezequiel" mostraba las dos fichas y **un** botón: la de Pablo quedaba
viva en el servidor, sin forma de guardarla, y nada lo avisaba. El usuario leyó dos fichas,
confirmó, y se dio de alta una. Es la peor forma de fallar que puede tener este circuito,
porque el síntoma es silencio.

**Decisión**: `/chat` y `/historial` devuelven `confirmaciones`, una **lista**, con tres
reglas que van juntas:

1. **Un botón por ficha del turno.** Es el arreglo directo del bug.
2. **Se devuelven todas las pendientes, no solo las del turno en curso.** El front borra los
   botones apenas el usuario escribe (`quitarConfirmaciones()`, que existe porque seguir
   escribiendo suele significar "cambiá algo"). Sin esta regla, confirmar una de tres y
   después escribir cualquier cosa hacía desaparecer las otras dos — el mismo bug otra vez,
   por otra puerta. Que reaparezcan no escribe nada: confirmar es siempre un click explícito
   y el token sigue siendo un hash del contenido.
3. **Deduplicadas por `slug` + nombre normalizado, gana la última.** Cuando el usuario pide
   un cambio, el modelo rearma la ficha y quedan dos tokens vivos de la *misma* alta. Dos
   botones con el mismo nombre y distinto contenido no hay forma de distinguirlos, y el
   viejo guardaría la versión que el usuario mandó corregir.

**Por qué no se resolvió pidiéndoselo al prompt**: la regla "acordate de ofrecer las dos
fichas" es exactamente el tipo de instrucción que este agente cumple a veces. El estado ya
estaba bien del lado del servidor; lo que faltaba era exponerlo. El prompt igual se tocó,
pero para lo que solo él puede hacer: que llame a `crear_entidad` una vez por cada cosa en el
mismo turno en vez de ir de a una.

**Consecuencia buscada**: el nombre va **dentro** del botón ("✅ Guardar persona: Pablo
Errio"). Con `etiqueta` sola, tres botones seguidos decían "Guardar persona" tres veces.

---

## [2026-08-09] — El vínculo persona↔hito lo hace el servidor al confirmar, no el modelo

**Contexto**: probando el alta de hitos, el agente armó la ficha de "Pablo Errio y Ezequiel
Toñanes — Certamen Nacional OMA" con **Personas/cursos involucrados vacío**. Los dos nombres
estaban escritos en el título y en la descripción, y las dos personas ya tenían ficha: el
modelo los tenía delante y no llenó el campo. En la misma ficha dejó `nivel` vacío y después
le preguntó al usuario una importancia que el usuario le acababa de decir ("crítico").

Las dos cosas son la misma falla: el modelo trata la ficha como prosa (el título "ya lo dice")
en vez de como un formulario, y las preguntas de cortesía del paso 3 del circuito de alta se
comen datos que ya estaban en la conversación.

Y aunque hubiera llenado `protagonistas`, el vínculo navegable no se creaba igual:
`protagonistas` es texto suelto, el que conecta con la ficha de la persona es `persona_hitos`,
y **el botón de confirmar no pasa por el LLM** (esa fue una decisión anterior, y buena: el
alta sale gratis y es determinística). En el instante en que el hito se escribe, el agente no
tiene ningún turno donde llamar a `vincular_entidad`. Nadie iba a crear ese vínculo nunca.

**Decisión**: tres capas, de la más blanda a la más dura.
1. **Prompt** — bloque "AL CARGAR UN HITO" y una regla en el paso 3 del circuito de alta: un
   dato que el usuario ya dio no puede quedar vacío en la ficha, y preguntar de nuevo por él
   es el peor error de esa pantalla.
2. **Aviso en el resultado de la tool** (`antes_de_mostrar`) — llega en el mismo turno, con
   los nombres concretos que se encontraron cruzando el título contra `personas`. Es mucho más
   efectivo que una regla lejana en el prompt porque es específico y llega justo cuando importa.
3. **Código en `/confirmar`** (`_enlazar_protagonistas`) — el vínculo se escribe solo. Esta es
   la única capa que no se puede saltear, y es la que garantiza que el hito quede conectado.

**Por qué no solo prompt**: es la regla que este agente cumple a veces (mismo criterio que
`_normalizar_borrador` con la fecha de revisión, y que `_ocultar_ids`). Lo que se puede hacer
determinístico se hace determinístico; el prompt queda para lo que el código no puede saber.

**Por qué el match exige el nombre completo**: `_personas_nombradas_en()` pide todas las
palabras del nombre (>2 letras) en cualquier orden. Un "Pablo" suelto no vincula. Con dos
Pablos en la escuela, colgarle un hito al que no fue es peor que dejarlo sin vincular — y se
descubre tarde, porque nadie revisa la ficha de alguien buscando logros ajenos.

**Se agregó además `hitos.rel_personas`**, espejo de `personas.rel_hitos` sobre la misma tabla:
sin eso el vínculo existía pero no se veía desde el hito, y el bug parecía seguir ahí. Es la
única relación declarada de los dos lados; `guardar_entidad_sin_request` solo la toca si le
mandan la clave `rel_*`, así que ningún camino del agente la pisa.

---

## [2026-08-09] — La foto se lee en una llamada aparte, no se le manda al agente

**Contexto**: el alta desde foto estaba escrita entera —resize en el front, bloques `image`,
una sección del system prompt sobre chapas de características— y no funcionaba, porque el
proveedor por defecto (DeepSeek) no tiene visión. La salida documentada era
`AGENTE_PROVIDER=anthropic`, o sea cambiarle el modelo a **todo** el chat para una función que
se usa en una fracción de los turnos.

Al medirlo, el costo estaba en otro lado del que parecía. El system prompt (~15K caracteres) más
`TOOLS_SCHEMA` (~40K) son **~15.000 tokens que viajan en cada turno**, tenga foto o no. Una
imagen de 1568 px son ~1.700 tokens: el 10% de un turno. La pregunta cara no era "¿cuánto sale
ver una foto?" sino "¿le paso la foto al agente completo o la leo aparte?".

**Decisión**: lector separado, y **leer es una tool que el modelo decide llamar**, no un paso
automático de `chat()`. La foto va a una llamada suelta —sin tools, con un prompt de ~600
tokens que solo sabe transcribir etiquetas— y el resultado entra al chat como texto.

Lo de la tool salió de una corrección al primer diseño, que leía **toda** foto al entrar:
el caso más común no es "cargá esto al inventario" sino "guardá esta foto en el taladro", y
para guardar una imagen no hace falta saber qué dice. Se estaba pagando una llamada de visión
por foto para tirar el resultado. Ahora el modelo elige: `leer_foto` si necesita los datos,
`adjuntar_foto` si solo va a una ficha, y **preguntar** si no está claro — leer "por las dudas"
está explícitamente desaconsejado en el prompt y en la descripción de la tool.

El costo de la vuelta extra del loop no lo cambia: DeepSeek cachea el prefijo (system prompt +
tools), y un cache hit sale US$0,003625/M contra US$0,435/M de un miss, o sea ~US$0,00005 por
iteración. Es un orden de magnitud menos que la lectura que se ahorra.

Tres cosas se ganan a la vez con el lector aparte:

1. **~7× más barato por foto** (~2.000 tokens contra ~15.000).
2. **El chat no cambia de proveedor.** DeepSeek es más barato y anda mejor con las 20 tools y
   el alta en dos pasos que un modelo chico con visión. Ya no hay que elegir entre "el que
   chatea bien" y "el que ve".
3. **Separa responsabilidades donde ya estaban separadas en el prompt**: leer la etiqueta
   (puntos 1–2 de la sección de datasheets) contra decidir qué hacer con lo leído (puntos 3–6:
   la cantidad la dice el usuario, buscar duplicados, el circuito de ficha). Lo primero se fue
   al lector; lo segundo se quedó con el agente, que es el que tiene las tools.

**Por qué Gemini 2.5 Flash-Lite de default**: se comparó contra GPT-5 Nano/Mini, Claude Haiku
4.5, Google Cloud Vision (OCR puro) y Qwen3-VL self-hosted. A la escala de la escuela la
diferencia de precio entre todos ellos es de centavos al año, así que no decidió el precio:
decidió que Flash-Lite tiene **1.000 requests/día gratis sin tarjeta** y que habla el protocolo
de OpenAI, con lo cual entra por el cliente `openai` que ya era dependencia obligatoria — cero
paquetes nuevos. El OCR puro se descartó aunque cueste parecido: devuelve texto crudo y no
interpreta (no distingue marca de modelo, ni entiende que cinco paneles iguales son un recurso
con `cantidad` 5), o sea que habría que escribir a mano justo lo que el prompt ya resuelve.
Qwen3-VL se descartó porque necesita GPU y el deploy es Render free tier.

**Contra asumido**: en el tier gratuito Google usa las imágenes para mejorar sus productos. Para
chapas de amoladoras es irrelevante; queda documentado en `AGENTE_CONFIG.md` con las variables
para cambiar de proveedor si algún día importa.

**Lo que NO se hizo**: no se sacó el camino viejo. Si hay un proveedor con visión configurado y
no hay lector, la imagen le sigue llegando al agente como antes. Son tres líneas y evita
romperle el chat a un deploy que ya tenga `AGENTE_PROVIDER=anthropic`.

---

## [2026-08-09] — La foto pendiente se ata al token de la ficha, en tabla propia

**Contexto**: la foto llega en un turno y el alta se confirma en otro — a veces desde otra
página, después de que el historial se repinta y el botón vuelve a aparecer. Hay que guardarla
en el medio, y la pregunta es contra qué se la ata.

**Decisión**: contra el **token de contenido de la ficha** (`_token_ficha()`), en una tabla
propia `agente_fotos_pendientes`.

- **Contra el token y no contra el turno o el `sid`**: el token es lo único que sobrevive la
  distancia entre "te muestro la ficha" y "confirmaste". Y como el token es un hash del
  contenido exacto que el usuario leyó, la foto queda atada a *esa* ficha: si el usuario pide
  cambios y se arma una ficha nueva, es otro token — la foto se vuelve a guardar contra el
  nuevo y la vieja se barre sola.
- **En tabla propia y no dentro del JSON de `fichas`**: esa columna se reescribe entera en cada
  turno de `_conv_guardar()`. Con hasta `FICHAS_MAX` (20) fotos en base64 adentro, cada mensaje
  del chat pasaría a arrastrar varios MB de escritura.

**Si `agregar_foto` falla, el alta igual se da por buena** y se avisa que la foto quedó afuera.
Para cuando se llama, el registro ya está creado y el token ya se consumió: revertir el alta por
una imagen sería peor que perder la imagen.

---

## [2026-08-09] — La excusa absurda de Emilio vive solo en las historias

**Contexto**: se pidió subirle el carácter al personaje — que hable como si el otro ya supiera
quién es (sin presentarse), con un tono leve de soberbia y orgullo de saber todo lo que pasa en
la escuela, y que **cuando no sabe algo invente una excusa obvia y absurda**, en tono cómico.
Las dos primeras son voz (`QUIEN_ES_EMILIO`); la tercera toca el guardrail más sensible del
agente.

**El riesgo**: "si no sabés, inventá una excusa" está a un paso de "si no sabés, inventá". Todo
el módulo de historias existe con la forma que tiene para evitar la fabricación de anécdotas
(ver la decisión de los textos literales), y el `no_encontrado` estaba escrito justamente para
cerrar esa puerta.

**Decisión**: se implementa, con dos límites explícitos en el prompt.

1. **La excusa reemplaza el "no sé", nunca los hechos.** La respuesta puede ser graciosa, pero
   tiene que seguir dejando clarísimo que esa historia no existe. `EXCUSA_SIN_HISTORIA` lo dice
   en la misma frase que pide el chiste, no como una aclaración aparte.
2. **Vale solo para historias y lore.** Un horario, un stock, un préstamo o una persona que no
   están cargados se contestan derecho: "no hay datos de eso". El que pregunta por una
   herramienta o corre a dar clase no está pidiendo un personaje, y una excusa graciosa ahí le
   cuesta una vuelta al pañol al vacío. Es el agente bifásico de siempre (decisión del
   2026-08-08), ahora con un borde más filoso: la gracia es un permiso de la faceta fantasma, y
   el system prompt lo dice con esas palabras ("DÓNDE TERMINA EL PERSONAJE").

**Por qué en las `nota` de la tool y además en el system prompt**: la excusa se dispara en un
`no_encontrado`, así que su lugar natural es la `nota` de las tres ramas que lo devuelven. Pero
el límite (para qué **no** vale) tiene que estar en el system prompt: si viviera solo en la
respuesta de `consultar_historia`, no estaría presente en el turno donde el usuario pregunta por
un préstamo que no existe, que es justo donde importa.

---

## [2026-08-09] — Al personaje se le da un instructivo de cómo hablar, no una lista de prohibiciones (y el resto lo saca código)

**Contexto**: Emilio cuenta las historias en primera persona como el fantasma de la escuela
(ver la decisión del 2026-08-08 sobre su personalidad). El costo de ese personaje es que le
activa al modelo el registro de roleplay, y en vez de contar **actúa**:
`*se acomoda los anteojos*`, `—mirando el patio—`, `EMILIO:` antes de hablar. La regla que lo
prohibía ya existía en `instruccion_tono`, y aun así seguía pasando, por tres razones:

1. Estaba en **una sola de las dos rutas** de `consultar_historia`. La ruta por `id` — la que se
   usa cuando el usuario elige una historia de un `listar`, o sea la más frecuente — tenía una
   instrucción de dos líneas sin la regla.
2. Viaja como **resultado de tool, y esos no se persisten en el historial** (decisión de
   2026-08-08 sobre tonos: la instrucción es contextual para no cargar peso en todos los turnos).
   En un turno de seguimiento ("¿y después qué pasó?") la regla ya no está, y lo único que el
   modelo tiene a la vista como modelo de respuesta es su propia respuesta actuada anterior.
3. El campo **`estilo` se interpola literal** en el prompt, y la doc recomendaba llenarlo con
   `"diálogos"` y `"dramático"`. Es decir: la regla decía "no actúes" y el mismo prompt, tres
   líneas más abajo, pedía teatro.

**Decisión**: mismo esquema de dos capas que los id (ver "Los id no se le muestran al usuario"):
prompt + **filtro de salida determinístico** `_quitar_acotaciones()`. La instrucción se extrae a
`COMO_CUENTA_EMILIO` y se interpola en el system prompt **y** en la `instruccion_tono` ahora
unificada en `_instruccion_tono()`.

**El prompt se escribe en positivo, y esto no es cosmético.** La primera versión era una lista de
prohibiciones ("no escribas acotaciones de gestos, no marcas de guion de teatro") y falló de dos
maneras distintas:

- Para nombrar lo prohibido hay que **escribir el ejemplo malo en el prompt**. O sea que la regla
  anti-`*se acomoda los anteojos*` metía `*se acomoda los anteojos*` en el contexto de todos los
  turnos. Es la peor forma posible de pedir algo a un modelo que completa por imitación.
- Decir qué no hacer le deja **deducir la forma correcta**, y la deduce mal. Probado: prohibidas
  las marcas, escribió los mismos gestos como prosa suelta ("Baja la voz, se acerca un poco." /
  "Se encoge de hombros."). Cumplió la letra y esquivó la intención, porque nunca se le dijo
  cuál era.

La versión que quedó describe el procedimiento — escribís solo lo que Emilio dice en voz alta;
el clima se transmite con lo dicho ("esto no lo repitas" en vez de contar que baja la voz) — y
cierra con un **test que el modelo aplica solo**: *¿esta oración se puede pronunciar?*. No hay ni
una acotación de muestra en el prompt.

**Por qué además filtro de código**: no alcanza con esperar que lo entienda del texto. El
provider por defecto (DeepSeek) imita el registro del contexto más de lo que razona sobre una
instrucción de estilo — el mismo motivo por el que existen `_escritura_no_ejecutada()` y
`_ocultar_ids()`. Y acá el prompt tiene una desventaja extra: el ejemplo malo se lo genera él
mismo y se lo persiste, así que la única forma de cortar el bucle es que la acotación **no llegue
al historial**. Por eso el filtro corre antes de guardar, no al pintar.

**Cómo se detecta un gesto sin marcas**: por gramática, no por lista de frases. Emilio habla en
primera persona y las historias están en pasado, así que una oración corta, entera en tercera
persona del presente y sin sujeto solo puede ser él describiéndose desde afuera. Se borra solo si
**todas** las cláusulas de la oración son gesto: "Baja la voz, se acerca un poco." se va entera,
"Sonríe y sigue la clase como si nada" se queda.

**Por qué el filtro es conservador**: falso positivo y falso negativo no cuestan lo mismo. Que se
escape una acotación es ruido; borrar `*Panel solar 100 W*` de una respuesta de inventario es
perder un dato. De ahí que nunca se toque un tramo con números, que los núcleos de gesto estén
listados a mano (`_GESTO_NUCLEO`) en vez de inferidos por conjugación, y que los verbos con
imperativo queden afuera de la lista de una palabra: `*mirá*` es una cursiva válida.

---

## [2026-08-08] — Personas: la identidad es el nombre con las palabras ordenadas, no el nombre

**Contexto**: la memoria de la escuela (quién es quién, qué proyectos e hitos protagonizó) se
modela como un grafo: una fila por persona y relaciones M2M hacia `proyectos` e `hitos` —
"cosas en la pared unidas con hilos". Todo el valor del modelo depende de que **una persona sea
un solo nodo**. Y el nombre entra por caminos que lo escriben distinto: el chat y el form
reciben "Juan Pablo Crivari"; los horarios lo tienen como "CRIVARI JUAN PABLO", porque
`limpiar_profesor()` (database.py) guarda apellido primero, en mayúsculas y sin acentos.

**Decisión**: `personas.nombre_norm` con un **UNIQUE**, calculado por `clave_persona()`:
descartar puntuación → `_norm` (minúsculas, sin acentos, espacios colapsados) → **ordenar las
palabras alfabéticamente** → volver a unir. `nombre` guarda la grafía linda para mostrar;
`nombre_norm` decide identidad. Verificado: las cinco formas que aparecen en la práctica
(incluida la que sale de `limpiar_profesor()`) colapsan en `crivari juan pablo`.

**Por qué ordenar las palabras y no sólo normalizar**: sin eso, "Juan Pablo Crivari" y
"CRIVARI JUAN PABLO" son claves distintas y quedan dos fichas de la misma persona con los
hilos repartidos entre ambas — exactamente la falla que el grafo existe para evitar, y la más
difícil de notar, porque las dos fichas se ven bien por separado.

**El costo, asumido a conciencia**: dos personas distintas cuyos nombres son la misma bolsa de
palabras ("María José Pérez" vs "José María Pérez") colisionan, y la segunda no se puede
cargar. Es raro; cuando pase, el usuario ve el mensaje de `_ERROR_DUPLICADO` y puede
desambiguar. Se eligió ese modo de falla — **ruidoso y recuperable** — sobre el contrario
(duplicados silenciosos que corrompen el grafo sin que nadie se entere). Si algún día molesta,
lo que hay que cambiar es `clave_persona()`, no el schema.

**No se sincroniza con `escuela.db`**: los horarios son datos operativos que se regeneran desde
Sheets cada año; `personas` es memoria permanente. Un docente que deja la escuela desaparece de
Sheets y **debe** seguir en la memoria — que sobreviva al padrón es el punto. Por eso no hay FK
entre ambas: el puente, cuando haga falta, es `clave_persona()` sobre el nombre.

**Sin campo `rol`**: se probó con una lista fija de roles y se sacó el mismo día. Una taxonomía
cerrada se queda corta enseguida (alguien es docente y ex alumno a la vez, o pasa de preceptor a
directivo) y la semblanza en prosa lo dice mejor. La columna se elimina en `_migrar` con
`DROP COLUMN` (SQLite 3.35+). Queda en pie la cautela que motivaba el rol: `descripcion` es un
juicio sobre una persona real y `/gestion` está detrás de una clave compartida cuyo default
está hardcodeado en un repo público — semblanzas de alumnos menores piden auth de verdad
primero.

---

## [2026-08-08] — `gestion.db`: respaldo automático y seed condicionado (a raíz de una pérdida real)

**Contexto**: se perdió el inventario completo — 87 recursos, 7 préstamos, 26 ítems y las relaciones. El archivo `gestion.db` fue **borrado del disco**, no vaciado: `sqlite_sequence` de `recursos` había vuelto a 5 (ese contador no baja con `DELETE` ni con `VACUUM`), un escaneo de bytes crudos no encontró rastros de los nombres reales en páginas liberadas, y la `CreationTime` seguía siendo la vieja porque NTFS la reusa al recrear un archivo con el mismo nombre en el mismo directorio. **No se determinó qué lo borró**: no hay `os.remove`/`shutil`/`DROP TABLE` sobre esa DB en el repo, ni hooks en `.claude/settings.json`, ni scripts de sesión destructivos; el reflog muestra un `reset: moving to HEAD` a las 18:33 pero `git reset --hard` no toca archivos ignorados (sí lo haría un `git clean -xdf`, que no deja rastro). Se recuperó de casualidad, desde un `.bak` que una sesión había dejado en `%TEMP%` horas antes.

**Dos fallas se combinaron**, y ninguna era el borrado en sí:

1. **`gestion.db` no tenía ninguna red.** Está en `.gitignore` (`*.db`) y no se regenera desde ninguna fuente — a diferencia de `escuela.db`, que se reconstruye desde Sheets. Un `.gitignore` no protege de un `rm`; git no es backup.
2. **El seed convertía la pérdida en algo silencioso.** `init_db()` sembraba siempre que `recursos` estuviera vacía, así que un archivo faltante se volvía "base nueva" en vez de error. Se trabajó un día entero contra los 5 recursos de ejemplo sin notar nada.

**Decisión**:

- **Respaldo rotativo en `init_db()`**, o sea en cada arranque, antes de cualquier migración de schema. Con la **API `backup()` de sqlite3** y no `shutil.copy`, para que la copia sea consistente aunque otro proceso esté escribiendo.
- **Nunca respaldar una DB sin recursos.** Es la regla que hace que el sistema no se autodestruya: si el archivo se perdió, respaldar el vacío encima de los buenos sería peor que no tener respaldos.
- **Retención = últimos 20 + el primero de cada día.** La regla diaria no es adorno: cada arranque escribe en la DB (`_migrar()`, el barrido de conversaciones de `agente.init_db()`), así que cada arranque genera un respaldo nuevo y la deduplicación por hash no alcanza. Sin retención diaria, una tarde de reinicios depurando empuja fuera de la rotación justo lo que uno querría recuperar.
- **El seed pasa a ser condicional**: si la DB está vacía **y existen respaldos**, `init_db()` levanta `RuntimeError` con el comando de restauración en vez de sembrar. Los respaldos son el desempate entre "instalación nueva" y "perdí datos" — la señal más barata y confiable disponible. `GESTION_SEED=1` fuerza el seed a propósito; un deploy limpio no tiene respaldos, así que sigue sembrando solo.

**Consecuencia**: la app **no arranca** con la DB vacía si hay respaldos. Es deliberado — fallar ruidoso es el punto, y el mensaje trae la ruta exacta a copiar. Queda un `gestion.db` vacío en disco cuando el guard dispara (`conectar()` lo crea antes del raise); no molesta porque el guard vuelve a disparar en el arranque siguiente y la restauración lo pisa.

**Nota**: `importar_inventario.py` (borrado en `0dbfbee`) se recuperó del historial como red secundaria. **No reemplaza al respaldo**: el Sheet no guarda relaciones, fotos, préstamos ni las ediciones hechas en la app, y hoy tiene menos filas que recursos hay en la DB. Correrlo sin comparar antes pisa datos.

---

## [2026-08-08] — Foto sin visión: cortar antes del modelo, no degradar a texto

**Contexto**: el alta desde foto (sacar la etiqueta de un panel solar, decir "tenemos 5", que quede en el inventario) estaba a medio camino: el front subía la imagen y el loop de Anthropic la pasaba, pero el proveedor por defecto es **DeepSeek, que no tiene visión**. En ese caso `_mensajes_openai` reemplazaba la imagen por la nota "[el usuario adjuntó una imagen, pero este proveedor no soporta visión]" y **le mandaba el turno igual al modelo**.

**Decisión**: si llega una imagen y `_get_config()['vision']` es falso, `chat()` responde `AVISO_SIN_VISION` **sin llamar al modelo**.

**Por qué**: el modelo con la nota igual contestaba, y no siempre decía "no la veo" — con la frase "tenemos 5 de estos" al lado, lo más probable es que arme una ficha con las especificaciones típicas de un panel solar cualquiera. Un dato inventado en el inventario es peor que no cargar nada: nadie lo vuelve a verificar y queda como verdad para el que venga después (misma lógica que la regla "nunca afirmes algo que no ejecutaste"). Cortar antes además no gasta tokens y le dice al usuario qué hacer en su lugar (dictar los datos por texto).

**Alternativa descartada — pasar el default a Anthropic para que funcione siempre**: el default DeepSeek se eligió con una batería de 30 preguntas y por costo; cambiarlo para habilitar un flujo es una decisión de despliegue, no de código. Queda como una env var (`AGENTE_PROVIDER=anthropic`) documentada en `agent_docs/gestion-conocimiento.md`.

**Por qué `AGENTE_VISION` es una env var y no una tabla de modelos con visión**: la lista de modelos que ven imágenes cambia todo el tiempo y `AGENTE_MODEL` es texto libre (incluye self-hosted). Una tabla hardcodeada envejece mal y falla justo al revés de lo que conviene: negándole visión a un modelo que sí la tiene. El que configura el servidor sabe qué modelo puso.

**Achicar la foto en el navegador y no en el servidor**: el cuello de botella es la subida (wifi de la escuela, datos del celular), así que comprimir después de subir no ahorra lo que importa. Además evita meter Pillow en el request de chat. 1568 px de lado largo es el tope que el modelo aprovecha; más grande se paga el envío para nada.

---

## [2026-08-08] — Personalidad de Emilio: fantasma omnipotente en historias, herramienta neutral en tareas

**Contexto**: El agente se llamaba "Emilio" por el nombre de la escuela, pero sin identidad — respondía todo con el mismo tono neutral. Se pidió darle **personaje**: que cuando cuente historias sea Emilio Mitre en persona, el ingeniero cuyo nombre lleva la escuela, un fantasma que habita desde su construcción y vio todo lo que pasó. Pero solo en historias — para horarios y búsquedas operativas, debe seguir siendo una herramienta eficiente.

**Decisión**:
- **Emilio cobra vida solo en historias** (`consultar_historia`). Cuando el usuario pide un horario, aulas libres o un inventario, responde como herramienta neutral (no cambia). Es así porque alguien que consulta horarios en medio de la jornada quiere info rápida, sin storytelling.
- **Personalidad activada por `instruccion_tono`**: cuando hay una historia en modo `directo`, la tool devuelve una instrucción que le dice a Claude:
  > "ERES EMILIO MITRE, el fantasma que vive en esta escuela desde que se construyó. Recorres todos los pasillos, ves y escuchas todo. Cuéntale esta historia EN PRIMERA PERSONA, como testigo omnipotente que lo presenció."
  - La instrucción no carga en system prompt, viaja en la respuesta de la tool. Así es contextual a esa historia específica.
  - Incluye el `tono` emocional específico (nervioso, reflexivo, misterioso, etc.) y el `estilo` narrativo (primera persona, íntimo, como confesando, etc.).
- **Por qué `instruccion_tono` en la respuesta y no en system prompt dinámico**: 
  - Las instrucciones por historia viajan con la tool de lectura (modo `directo` le pasa la instrucción al texto).
  - Si fueran dinámicas en el loop, tendrían que inyectarse en el system prompt a cada turno (cargo fijo). Viajando en la tool, no pesan si no se consultan historias.
  - Conceptualmente: Emilio es el resultado de la lectura, no un personaje que espera en el background.
  - Auditoría: la instrucción está en el JSON que la tool retorna, no es magia del prompt.

**Consecuencia**: el agente es "bifásico" — dos caras de la misma entidad. Tareas operativas: máquina eficiente. Historias: fantasma omnipotente que cuenta lo que vio. El usuario interactúa con Emilio siempre, pero él solo "despierta" en las historias.

---

## [2026-08-08] — Historias: arquitectura de dos niveles (índice + archivos) + tonos/estilos

**Contexto**: Se pidió escalar el sistema de historias para cientos de anécdotas, permitiendo búsquedas por atmósfera ("algo misterioso", "historias excitantes") y que el agente las cuente **con emoción real** (primera persona, tono nervioso/reflexivo/etc.), no como texto plano de "dos puntos y listar".

**Decisión**:
- **Arquitectura de dos niveles (lazy-loading)**:
  - `historia_indice.json`: índice cachea siempre (id, título, claves, tipo, resumen, tono, estilo, **sin texto**)
  - `historias/{id}.json`: archivos individuales, un por historia, con texto completo + metadata. Se cargan **bajo demanda**.
  - **Beneficio**: escalable a 1000+ historias. Índice pequeño (~20KB, 250 tokens/turno), textos solo al leerlos (~200-500 tokens variando por historia).
  - **vs alternativas consideradas**: base de datos SQLite (overkill, menos editables a mano), un JSON gigante (no escalable), archivos `.md` (Markdown headers no son index-friendly).

- **Búsqueda expandida**: antes solo en `claves`; ahora también en `tono` y `estilo`. Permite "algo misterioso" matchear historias con `tono: misterioso` sin necesidad de esa palabra en las claves. El umbral sigue siendo 0.72.

- **Tonos + estilos como instrucciones para el agente**: cada historia devuelve `instruccion_tono` que le dice cómo contar: qué emoción sentir, qué perspectiva (primera persona, testigo, etc.), cómo mantener el misterio de ser Emilio. El modelo lo recibe como **respuesta de la tool**, no como system prompt, así que la instrucción es contextual a esa historia específica y no carga peso en todos los turnos.

- **Tool devuelve tres modos** (no dos como se esperaría):
  - `directo`: 1 coincidencia exacta → historia completa + `instruccion_tono` (el agente la cuenta sin preguntar)
  - `listar`: múltiples opciones o búsqueda vaga → índice sin textos (el agente ofrece opciones, usuario elige)
  - `no_encontrado`: nada coincide → instrucción de no inventar
  - **Beneficio**: el flujo es inteligente — "cuéntame de Cañamas" es directo, "historias" ofrece opciones, "algo misterioso" busca por atmósfera.

- **Por qué no un sistema de prompts dinámicos o sub-prompts**: las instrucciones de tono viajan en la respuesta de la tool (JSON), no inyectadas en el loop de tool-calling del modelo. Más simple, más auditable, y el modelo las ve de forma natural como parte de su respuesta de lectura.

**Consecuencia**: el sistema es ahora ansatz para cientos de historias sin problema de tokens. Agregar una anécdota es: (1) crear `historias/nuevo_id.json`, (2) agregar entrada al `indice` de `historia_indice.json`. Sin tocar código. El editor de historias no necesita saber de programación.

---

## [2026-08-08] — Sinónimos del inventario: que el modelo lea la lista completa, no un diccionario

**Contexto**: La búsqueda del inventario (`_puntaje_busqueda`) compara **letras, no significados**. Buscar "tester" no encuentra el *Multímetro*; "taladro" no encuentra la *Agujereadora de banco*, que es exactamente eso. El agente respondía "no está cargado", que era una **conjetura** derivada de que la búsqueda falló, no un hecho verificado. Subir el umbral a 0.68 el mismo día empeoró el síntoma: "taladro" pasó de 4 falsos positivos a 0 resultados.

**Decisión**: tool nueva `listar_todos(slug)` que devuelve **todos** los nombres + id, usada como **fallback** cuando `buscar_entidad` no trae ningún `match: "exacto"`. El modelo reconoce el sinónimo mirando la lista; no hay diccionario que mantener.

**Alternativas descartadas** (las tres son diccionarios curados a mano):
- *Columna `sinonimos` por recurso* — **47% de las filas comparten concepto** (medido: 4 paneles solares, 5 pinzas, 5 kits, 4 destornilladores). El sinónimo pertenece al *concepto*, no a la *fila*: habría que repetir "módulo fotovoltaico" en los 4 paneles y acordarse en cada alta nueva. A favor tenía que se edita desde la UI sin deploy.
- *`sinonimos.json` por concepto* — arregla la cardinalidad, pero sigue siendo curaduría manual perpetua y no cubre paráfrasis ("lo que mide tensión").
- *Regla de prompt: reintentar con 1–2 sinónimos antes de listar* — **cuesta más, no menos**. En tool-calling cada round-trip re-envía todo el contexto: medido, el piso es **~8.050 tokens** (esquemas de 20 tools ~6.420 + lista de personas ~1.625, sin contar el system prompt ni el historial) contra **~1.190 tokens** del listado completo de 91 recursos. Un intento de sinónimo de más cuesta **~6,7x** lo que cuesta mandar el inventario entero. Y puede *acertar mal*: adivinar "voltímetro" para "tester", encontrar un voltímetro real y detenerse ahí con confianza. La lectura completa ve todo y decide una sola vez.

**Por qué el costo es aceptable**: el agente ya inyecta ~1.625 tokens en **cada turno** con `_personas_conocidas()` (decisión 2026-08-04). El listado completo cuesta menos que eso y solo se paga cuando la búsqueda falla.

**Consecuencia**:
- "No está cargado" pasa de conjetura a afirmación verificada. Ese es el beneficio principal, más que el recall.
- **No escala para siempre**: `LIMITE_LISTADO_COMPLETO = 400`. Arriba de eso la tool se niega y pide afinar la búsqueda. **Si el inventario supera ese tope, el tier de sinónimos descartado arriba vuelve a ser la respuesta correcta** — la aritmética se da vuelta cuando el listado deja de caber.
- El guardrail es de prompt, en tres lugares que se refuerzan: el `aviso` de `buscar_entidad` nombra la tool, la `instruccion` del resultado dice "si ninguno es, decilo — no ofrezcas el más parecido", y la regla 3 del system prompt fija el orden. Al ser de prompt y no de código, es más frágil con modelos que siguen instrucciones peor; si alguna vez sobre-matchea, la salida es endurecer el guardrail, no volver al diccionario.
- **Verificado end-to-end contra `deepseek-v4-pro`** (2026-08-08), 6/6 casos. Sinónimos: "tester" → *Multímetro* y "taladro" → *Agujereadora de banco*, ambos vía `buscar_entidad` → `listar_todos`. Eficiencia: "osciloscopio" (match exacto) se resolvió con `buscar_entidad` sola, **sin** gastar el fallback — los dos niveles funcionan como se diseñaron. Negativos: "torno" y "soldadora inverter" se reportaron como no cargados. **El caso trampa**: preguntando por un "microscopio" la búsqueda difusa devuelve *Osciloscopio*, y el modelo respondió "no tenemos microscopio; lo más parecido es el Osciloscopio, pero es otra cosa — mide señales eléctricas, no amplía imágenes". Es exactamente el comportamiento que el guardrail busca: menciona el parecido marcándolo como distinto, en vez de ofrecerlo como el pedido.
- **No agregar una columna de sinónimos "para mejorar la búsqueda del chat"** sin releer esto: para ESE caso se evaluó y se descartó con datos. La búsqueda **web** (sin modelo del otro lado) es un caso distinto — ver el override en 2026-08-21, columna `recursos.alias`.

---

## [2026-08-08] — Historia de la escuela: contenido guardado en un JSON, nunca generado por el modelo

**Contexto**: Se pidió que el agente pudiera contar la historia del colegio y tener guiños internos (anécdotas sobre gente de la casa) como easter egg, con la condición explícita de que no comprometiera el funcionamiento ni el costo.

**Decisión**:
- **Tool `consultar_historia(tema)` + `historia_escuela.json`**, no texto en el system prompt. El prompt se paga en cada turno; el esquema de una tool son ~200 tokens fijos y el contenido solo se paga cuando alguien pregunta, que es casi nunca. Con contenido en el prompt, cada anécdota nueva encarece todos los turnos.
- **JSON en la raíz, no tabla en `gestion.db`**: es lore que se edita a mano y versiona en git, no dato de usuario. Una tabla obligaba a migración + ABM + template para algo que se toca dos veces por año.
- **El texto se devuelve LITERAL del archivo; el modelo no inventa anécdotas nunca.** Es la parte que protege el resto del sistema: el prompt tiene una regla marcada como inviolable de que ningún dato salga de memoria (existe porque el modelo llegó a fabricar horarios enteros, ver 2026-08-04). Un permiso de "inventá algo gracioso" no tiene borde que el modelo pueda reconocer — no sabe que el permiso terminaba en las anécdotas y no llegaba al inventario. Por eso `encontrado:false` devuelve una instrucción explícita de no inventar en vez de una lista vacía (que invita a rellenar), el hit trae una `nota` que prohíbe agregar hechos/nombres/fechas que no estén en `texto`, y la descripción de la tool acota el dominio ("no la uses para horarios, inventario ni préstamos").
- **Umbral de match 0.72, más alto que el 0.68 del inventario**: las claves son pocas y elegidas a mano, no 91 nombres compitiendo, así que se puede exigir más; y un falso positivo acá contesta una anécdota que no tiene nada que ver con lo preguntado.

**Consecuencia**: agregar lore es editar un JSON — no toca código ni requiere reiniciar (la carga se cachea por mtime). El agente pasó de tres áreas a cuatro en el system prompt.

---

## [2026-08-08] — `UMBRAL_SIMILITUD` de 0.6 a 0.68, elegido midiendo y no a ojo

**Contexto**: El umbral difuso de `_puntaje_busqueda` estaba en 0.6 "a ojo" desde 2026-07-21. Con el inventario real cargado (91 recursos, nombres cortos de una o dos palabras) resultó demasiado permisivo: buscar **"taladro"** —que no existe en el inventario— devolvía 4 recursos (*Caladora*, *Sierra de calar manual*, *Cinta de aisladora*, *Agujereadora de banco*), "guantes" devolvía 7 y "multimetro" traía 8 con *Pintura marrón (tarro)* adentro. Para nombres cortos, 0.6 deja pasar casi cualquier cosa que comparta vocales. Con el agente esto pasó de molesto a peligroso: Claude recibía esos candidatos y ofrecía el primero como si fuera el recurso pedido.

**Decisión**: subir a **0.68**, valor elegido con un barrido medido sobre la base real (0.60 → 0.80), no estimado.

- **Ruido** (queries de cosas inexistentes): "taladro" 4→0, "guantes" 7→1, "multimetro" 8→1, "alicate" 6→2.
- **Recall intacto**: todas las queries con typo probadas (`multimetr0`, `alikate`, `agujeradora`, `anemometroo`, `caladra`, `termometro infrarrojo`, `pinza amperometrica`) siguen encontrando su recurso en el **puesto #1**, incluso a 0.80. Subir el umbral no costó tolerancia a typos en ningún caso medido.
- **Por qué 0.68 y no más**: arriba de 0.68 la mejora de ruido es marginal (amoladora 4→2 recién a 0.72) y se empieza a arriesgar recall sin evidencia que lo justifique.

**Consecuencia**: la constante es **compartida** por la búsqueda web (`?q=` en `lista()`) y por `buscar_entidad` del agente — el cambio aplica a las dos, que es lo deseado (el mismo ruido existía en la web). Verificado en runtime que la web sigue resolviendo typos y que "taladro" ahora devuelve 0 filas en vez de 4 falsos positivos.

**Nota para el futuro**: si el inventario crece mucho o aparecen nombres largos, el umbral fijo puede volver a quedar mal calibrado — un umbral que escale con la longitud de la query sería más robusto, pero no se implementó porque con los datos actuales no hacía falta. **No revertir a 0.6 sin volver a medir.**

---

## [2026-08-04] — Asistente conversacional: tool-calling contra Claude, no embeddings ni agentes full-autonomous

**Contexto**: El usuario pidió un "agente" para la app que pueda: preguntar cuándo está un profesor, añadir material nuevo, crear y cerrar préstamos. El pedido explícitamente menciona "con alguna capa de seguridad para que no todos puedan hacer todo, pero sí preguntar distintas cosas".

**Decisión**:
- **Tool-calling contra Claude (Anthropic API)**: el agente es un **loop de tool-use**, no un modelo fine-tuned ni un agente "full-autonomous" con reflexión continua. Cada mensaje del usuario se procesa como: (1) Claude recibe el mensaje + la lista tipada de tools disponibles, (2) Claude elige qué tools ejecutar (puede ser varias), (3) el servidor ejecuta las functions Python reales (reads en DB/API, o writes con auditoría), (4) Claude recibe el resultado, (5) repite hasta dar una respuesta en texto. Es **sincrónico, acotado y verificable** — cada tool conocido existe en el código con validación y logs.
- **Reusar autenticación existente**: no se crea un sistema de usuarios con roles nuevos. El agente hereda `session['gestion_ok']` (la sesión del login de `/gestion` con la contraseña compartida). La capa de "quién puede hacer qué" es el mismo gate que ya protege el módulo entero.
- **Formato de salida interpretado en las tools**: cada tool de lectura devuelve datos ya procesados (horarios agrupados por día, aulas libres agrupadas por piso, búsquedas con solo campos relevantes sin vacíos) en vez de filas SQL crudas. Reduce tokens enviados a Claude y reduce errores de interpretación del modelo.
- **Auditoría obligatoria para escrituras**: tabla nueva `agente_log` registra quién pidió qué (`entrada` = parámetros JSON), qué había antes (`antes` = snapshot de la fila/relaciones para poder restaurar) y qué pasó (`resultado` = JSON de lo que se creó/modificó/error). Lecturas **no** se auditan para no llenar la tabla de ruido. Permite "si el agente se equivocó, reconstruir manualmente".
- **Confirmación en dos turnos para operaciones de riesgo**: el system prompt instruye a Claude a NUNCA ejecutar `eliminar_*` en el mismo turno en que se pide el borrado. Primero responde qué va a borrar, pide confirmación explícita, y recién en el turno siguiente ejecuta. Idem para crear desde foto — primero propone los campos, espera confirmación. Es una guardrail de **prompt**, coherente con "es una traba de desarrollo, no seguridad completa" (heredada de DECISIONS 2026-07-19), **no** un bloqueo hard en el código.

**Alternativas descartadas**:
- *Agentes full-autonomous (ReAct, loops de reflexión)* — más pesado, más tokens, más difícil de debuggear y más impredecible. El tool-calling simple ya da el comportamiento que se pidió.
- *Sistema de usuarios con roles granulares (`admin`, `profesor`, `alumno`)* — se descartó explícitamente en la entrevista inicial para mantener la "traba provisoria" existente (DECISIONS 2026-07-19). Si en el futuro se necesitan roles de verdad, será una decisión separada de migrar a Flask-Login.
- *Buscar semántica para recursos (embeddings)* — descartado por costo y complejidad. La búsqueda fuzzy existente (`_puntaje_busqueda`) es suficiente y se reusan las funciones existentes sin duplicar lógica.

**Consecuencia**:
- El costo de la API de Anthropic es externo al hosting gratuito de Render — correrá si `ANTHROPIC_API_KEY` está configurada, pero cada mensaje consume tokens pagos. El usuario debe estar consciente.
- El modelo por defecto es `claude-haiku-4-5-20251001` (soporta visión para fotos de etiquetas, costo muy bajo). Se puede cambiar por env var `AGENTE_MODEL`.
- Las funciones reusables en `gestion.py` se extraen para que no dependan de Flask `request`/`session` — ahora `agente.py` y los tests pueden usarlas sin necesidad de contexto HTTP.
- La auditoría cubre **todas** las escrituras, pero es responsabilidad del staff revisar `GET /gestion/agente/log` y restaurar manualmente si hay un error — el agente no tiene rollback automático.

---

## [2026-08-04] — Tool-calling output: datos interpretados, no filas crudas

**Contexto**: Al diseñar las tools, la pregunta fue: ¿le paso a Claude un array de filas SQL crudas o datos ya procesados? Ej: `horario_profesor` devuelve crudo `[{profesor, materia, aula, dia, hora_inicio, hora_fin, ...}]` vs interpretado `{profesor, clases: {Lunes: ["08:00–09:40 · Matemática · 3°B · aula 21"], ...}}`.

**Decisión**: Salida **interpretada**. Cada tool devuelve datos ya formateados según el dominio:
- Horarios agrupados por día, líneas legibles tipo "08:00–09:40 · Matemática · 3°B · aula 21" (sin repetir el profesor si fue buscado por profesor).
- Aulas libres agrupadas por piso (así piensa el staff), no una lista plana de códigos.
- Búsquedas de entidades omitiendo campos vacíos (la mayoría de `drive_url`, `fecha_revision` están en blanco), solo mostrando id, nombre, estado, ubicación.
- Pendiente de préstamos ya calculado (`cantidad − cantidad_devuelta`) en la salida, no crudos.

**Por qué**: (1) Reduce tokens enviados a Claude (menos JSON en ida y vuelta); (2) reduce errores de interpretación (Claude no tiene que agradecer por filas, parseándolas en su cabeza); (3) coincide con cómo **el staff piensa** los datos (por piso, por día, agrupado) — el modelo entiende más rápido. Es aplicar el principio de "no pasar ruido" que ya se usa en las queries de la app.

**Alternativa descartada**: Filas SQL crudas. Habría sido más "puro" (así vienen de la BD), pero el extra de tokens y el parsing que Claude tiene que hacer no vale la pena.

**Consecuencia**: Las tools son "opinadas" sobre el formato — si en el futuro otra interfaz necesita los datos en otro formato, habrá que agregar tools nuevas o parámetros. Es un trade-off de claridad sobre flexibilidad.

---

## [2026-08-04] — Harness del agente para préstamos: la ambigüedad la resuelve el código, no el modelo

**Contexto**: En uso real, el agente creaba préstamos "a ciegas" con datos ambiguos en vez de preguntar: `crear_prestamo('Erika Schneider', ..., 'panel solar')` se ejecutaba directo aunque el nombre de recurso fuera parcial, y `crear_prestamo('Dami', ...)` guardaba "Dami" tal cual como persona en vez de reconocer que probablemente se refería a un docente real con nombre completo distinto. Además, `finalizar_prestamo`/`reabrir_prestamo` con `items` ignoraban en silencio un `recurso_id` que no pertenecía al préstamo (ni error ni log) y devolvían `ok:true` igual — una devolución parcial podía "no pasar nada" sin que nadie se enterara.

**Decisión**:
- **Ambigüedad de recursos ya se resolvía en el código** (`_crear_prestamo` cuenta matches por `LIKE`), pero el error solo traía IDs crudos. Se cambió para que devuelva `opciones: [{id, nombre}]`, así el agente no necesita una tool extra para poder mostrárselo al usuario en texto.
- **Lista completa de personas conocidas en el system prompt**, no una tool de "comparar nombre" dedicada. Se evaluaron las dos: una tool tipo `buscar_persona_similar` hubiera sido casi idéntica a la `buscar_profesor` que ya existe (mismo `_puntaje_busqueda`), y depende de que el modelo *decida* llamarla — si no la llama, el bug original persiste. Poniendo la lista completa (~340 nombres, ~1500 tokens) directo en el prompt de cada turno, la verificación deja de ser opcional: siempre está a la vista. El costo en tokens es despreciable para este volumen de uso.
- **No se creó una tabla de "personas" en `gestion.db`** ni se migró `prestamos.persona` a una FK. Sería sobre-ingeniería: buena parte de quien retira material no es docente ni personal (alumnos, visitas, padres) así que el campo tiene que seguir aceptando texto libre; la lista sirve solo como referencia para detectar *"esto se parece a alguien real, confirmá"*, no como catálogo cerrado.
- **`finalizar_prestamo`/`reabrir_prestamo` ya no fallan en silencio**: si un `recurso_id` no pertenece al préstamo, la tool devuelve `ok:false` con el detalle en vez de reportar éxito sin haber cambiado nada. El system prompt le indica al agente llamar primero a `detalle_prestamo(id)` para conseguir los `recurso_id` reales antes de una devolución parcial, en vez de adivinarlos.
- **La regla vieja "nunca pidas aclaración si el contexto está claro"** (agregada para el bug de contexto conversacional) se acotó explícitamente a preguntas de seguimiento sobre algo ya consultado — no aplica a crear/editar registros nuevos, donde sí debe preguntar ante ambigüedad. Sin esta aclaración el prompt empujaba al modelo a **no** preguntar en ningún caso, lo cual empeoraba el problema original.

**Alternativas descartadas**:
- *Tool de comparación de nombres (`comparar_nombre`/fuzzy match como tool call)* — redundante con `buscar_profesor` existente y no garantiza que el modelo la invoque.
- *Validación server-side dura del nombre de persona* (bloquear `crear_prestamo` si no matchea la lista con cierto umbral) — se descartó: haría fallar préstamos legítimos a alumnos/visitas que nunca van a estar en la lista de docentes/personal.

**Consecuencia**: El prompt de sistema crece ~1500 tokens por turno (lista de nombres). Si la planta docente crece mucho en el futuro, reevaluar (paginar la lista o filtrar por relevancia) — hoy con ~340 nombres no es un problema.

---

## [2026-07-21] — Alta de préstamos como carrito en sesión (reemplaza el form de filas)

**Contexto**: El alta era un form con hasta 8 filas `recurso_N`/`cantidad_N`, cada una con un `<datalist>` donde había que tipear/elegir el recurso (desambiguando por sufijo `[#id]`). El usuario lo consideró "todo mal" y pidió **borrón y cuenta nueva**: que funcione como un carrito de compra — estando en recursos ir agregando, al final poner OK, y **recién ahí** cargar quién se lo llevó. (Reemplaza la decisión previa del mismo día de "registrar retiro desde la ficha vía `?recurso=<id>`", que quedó obsoleta.)

**Decisión**:
- **Carrito en la sesión de Flask** (`session['carrito']` = `{recurso_id: cantidad}`), no en localStorage ni en una tabla de "borrador". Es el mismo mecanismo que ya usa el login del módulo, sobrevive la navegación sin JS, y se serializa solo (dict chico). Cada "agregar" es un POST que actualiza la sesión y redirige de vuelta a donde se estaba. No hay estado de borrador en la DB que limpiar.
- **El préstamo se crea recién en el checkout** (`/carrito/finalizar`): mientras tanto no hay fila en `prestamos`. Así "quién se lo llevó" se pide al final (como pidió el usuario) y un carrito abandonado no deja basura en la DB — se descarta con la sesión.
- **Sin JS**: el carrito, agregar, editar cantidades y quitar son forms HTML + redirects, igual que el resto del módulo. El único JS del módulo sigue siendo la búsqueda en vivo. Para no anidar forms (quitar dentro del de cantidades) se usa el atributo HTML `form=`.
- **Se elimina el matching por nombre/`[#id]`**: al agregar por `recurso_id` (viene del botón de cada recurso, no de texto tipeado), desaparece toda la ambigüedad de nombres duplicados que resolvía `_parsear_items_prestamo()`. Menos código y sin errores de "elegí de la lista".
- **No se cambia el schema ni la devolución**: `prestamos`/`prestamo_items`/`cantidad_devuelta` y las rutas de devolución quedan igual; solo cambió cómo se arma el alta.

**Alternativa descartada**: carrito en el cliente (localStorage + JS). Evitaría los round-trips por cada "agregar", pero obligaba a serializar datos de recursos en el navegador y a más JS, contra el patrón "forms + redirects" del módulo. Con inventarios de decenas de ítems el POST por agregado es imperceptible.

**Consecuencia**: el carrito es por navegador/sesión — si se cierra sesión (`/salir` limpia toda la sesión) o expira la cookie, se pierde lo que no se finalizó. Aceptable: es un borrador efímero, no un registro. Con la clave compartida, dos personas en el mismo navegador comparten carrito (mismo caso que ya pasa con el login).

---

## [2026-07-21] — Préstamos: devolución por ítem con `cantidad_devuelta`, y `fecha_devolucion` derivada

**Contexto**: La devolución era todo-o-nada a nivel préstamo (`fecha_devolucion` en la fila `prestamos`). El usuario quiere devolver de a partes: marcar que volvió un ítem puntual, e incluso una fracción de su cantidad (ej: se llevó 3 multímetros, devuelve 1). También poder arrancar un retiro desde la ficha del recurso, no solo desde el form vacío.

**Decisión**:
- **Cantidad devuelta por ítem, no una tabla de eventos**: se suma una columna `cantidad_devuelta` a `prestamo_items` (acumulado devuelto por ítem). Un ítem está devuelto cuando `cantidad_devuelta == cantidad`. Más simple que un log de movimientos de devolución (que daría historial fino pero es sobre-ingeniería para el caso: "cuánto falta" es lo único que se consulta).
- **`fecha_devolucion` sigue siendo la fuente de verdad de "cerrado", pero derivada**: en vez de que el usuario la setee, `_recalcular_estado()` la pone sola cuando el pendiente total llega a 0 y la limpia si vuelve a haber algo afuera. Así la lista (activos/historial), el contador del home y el badge no cambian de lógica — todo lo que ya leía `fecha_devolucion` sigue igual. Se evita un segundo indicador de estado que se pueda desincronizar del detalle por ítem.
- **`devolver` (todo) se mantiene como atajo**: marca cada ítem entero + cierra. Es el flujo más común (se devuelve todo junto) y es el botón de la lista. La devolución parcial vive en el detalle.
- **Registrar retiro desde la ficha del recurso vía `?recurso=<id>`**: en vez de un endpoint nuevo, `prestamo_nuevo` acepta un query param que precarga la fila 1 del form existente (reusa el sufijo `[#id]` del datalist). Un solo lugar donde se crea el préstamo.

**Alternativa descartada**: tabla `prestamo_devoluciones` (una fila por evento de devolución, con fecha y cantidad). Daría un historial de devoluciones parciales con timestamps, pero nadie pidió ese detalle y complica todas las consultas de "cuánto falta". Si en el futuro se necesita auditar cada devolución parcial, es el camino a retomar.

**Consecuencia**: `cantidad_devuelta` arranca en `'0'` para préstamos previos (migración aditiva) — quedan consistentes: 0 devuelto, `fecha_devolucion` intacta. `reabrir` (todo) y `reabrir_item` resetean a 0; una devolución parcial marcada por error se deshace por ítem sin perder el resto.

---

## [2026-07-21] — Búsqueda en vivo en `/gestion`: filtrado local en el navegador (primer JS del módulo)

**Contexto**: La búsqueda recargaba la página entera contra el servidor en cada consulta. El usuario preguntó si conviene "descargar todo y buscar local para evitar tiempos innecesarios". `/gestion` se había hecho a propósito sin JS propio (decisión 2026-07-17).

**Decisión**: Búsqueda en vivo del lado del cliente (`static/gestion.js`, ~35 líneas vanilla, sin build step). El listado ya trae todas las filas; la ruta emite `data-buscar` por fila (texto normalizado por Python) y el JS filtra por substring mientras se escribe. Instantáneo, sin round-trips. Esto **introduce el primer JS propio de `/gestion`**, revisando el "sin JS" de 2026-07-17: pedir búsqueda en vivo implica JS sí o sí (Python no corre en el navegador), y es el mismo patrón que ya usa el SPA de horarios (backend Python + JS vanilla). No es migrar de stack.

**Alternativas descartadas**:
- *Servir un fragmento HTML por fetch (server-side en vivo)*: mantendría la lógica difusa exacta, pero suma un round-trip por tecla — más notorio en hosting lento, justo lo que se quería evitar.
- *Portar la búsqueda difusa (difflib) a JS*: duplicaría lógica (dos implementaciones a mantener) para tolerar typos, cosa que el filtrado en vivo compensa solo (ves los resultados achicarse y corregís el typo).

**Consecuencia**: Progressive enhancement — sin JS, el form sigue haciendo la búsqueda difusa server-side de `lista()`; con JS, filtra local, oculta el botón BUSCAR y evita la recarga. La capa en vivo perdona acentos/mayúsculas (misma normalización que Python) pero **no** typos (solo substring); el fuzzy server-side queda de respaldo (Enter con JS apagado, o URLs `?q=`). La normalización se hace una vez en Python (`data-buscar`), así el JS no duplica las reglas de acentos, solo las aplica a la query.

---

## [2026-07-21] — Búsqueda de `/gestion` tolerante con `difflib`, no FTS ni embeddings

**Contexto**: El `LIKE` literal de `lista()` no perdonaba acentos ("multimetro" no encontraba "Multímetro"), typos ("destronillador"), ni mayúsculas. El usuario pidió una búsqueda "que perdone un poco".

**Decisión**: Filtrar en Python en vez de en SQL. `lista()` trae todas las filas y las puntúa con `_puntaje_busqueda()`: normaliza acentos/mayúsculas (`_norm`) y tolera typos por similitud (`difflib.SequenceMatcher`, librería estándar). Substring normalizado gana siempre; la similitud difusa entra solo con 3+ caracteres y umbral 0.6. Es el "nivel 1 + 2" de las tres opciones que se evaluaron.

**Alternativas descartadas**:
- *SQLite FTS5 / trigramas*: más maquinaria (tabla virtual, sincronización) para un beneficio que `difflib` ya da con las decenas de filas actuales.
- *Búsqueda semántica (embeddings)*: resuelve sinónimos que no se parecen ("tester" = multímetro), pero es sobre-ingeniería acá — necesita dependencia pesada o llamada por búsqueda, y ese caso lo cubre mejor la futura columna `otros_nombres` (tarea #21) sin costo por query.

**Consecuencia**: El filtrado en Python es O(filas) por búsqueda — despreciable con ~decenas de recursos, pero si alguna entidad creciera a miles habría que pasar a un índice o FTS. Aplica a las 4 entidades genéricas; los préstamos siguen con `LIKE` en SQL (buscan en persona/destino/notas, otro caso). La similitud difusa puede meter algo de ruido en la cola de resultados (queda siempre después de las coincidencias exactas) — es el precio de "que perdone".

---

## [2026-07-21] — Préstamos: nunca se borra al devolver; ruta propia en vez de sumar a `ENTIDADES`

**Contexto**: El usuario quiere anotar fácilmente quién se lleva qué recursos (y cuántos) y poder marcarlos como devueltos, pero que la devolución **no borre el registro** — el historial de movimientos internos debe quedar permanente en la base, aunque sea "por el día".

**Decisión**:
- **`prestamos` con `fecha_devolucion` en vez de borrar o mover a otra tabla**: devolver es un `UPDATE`, no un `DELETE`. `fecha_devolucion = ''` = sigue afuera; con fecha = devuelto. Un solo lugar de verdad, sin tabla de "historial" separada que sincronizar.
- **Ruta propia (`/gestion/prestamos*`), no una entidad más en `ENTIDADES`**: el trío genérico lista/form/detalle asume una fila = un registro con campos planos. Préstamos tiene una relación 1-a-N con cantidad (`prestamo_items`) y un ciclo de estado (prestado→devuelto→reabrir) que el genérico no contempla — forzarlo ahí habría complicado el config declarativo para un solo caso especial.
- **No se descuenta stock de `recursos.cantidad`**: cantidad sigue siendo "cuánto hay en total"; "cuánto está afuera ahora" se calcula por consulta sobre `prestamo_items` sin devolver. Evita mantener dos números que se pueden desincronizar (stock físico vs. contador de préstamos).
- **Desambiguación por `[#id]` en el datalist del form**: el inventario real importado tiene nombres repetidos (dos "Formon", dos "Medidor de energia solar" — sets físicos distintos). El form muestra `"Nombre [#id]"` en las opciones; si se tipea el nombre a mano sin el sufijo y hay más de un candidato, error pidiendo elegir de la lista en vez de adivinar cuál.
- **`eliminar` (borra la fila entera) se mantiene solo como escape hatch** para cargas mal hechas, no es el flujo normal — el flujo normal siempre es devolver, nunca eliminar.

**Alternativa descartada**: sumar `prestamos` a `ENTIDADES` reusando `lista.html`/`form.html`/`detalle.html`. Habría requerido meter ítems-con-cantidad y el estado prestado/devuelto dentro de una config pensada para entidades planas — más complejidad en el genérico que las 3 vistas específicas que se hicieron.

**Consecuencia**: `/gestion/prestamos/<id>` y `/gestion/<slug>/<id>` compiten por la misma forma de URL; se depende de que Werkzeug prioriza rutas estáticas sobre el converter `<slug>` (verificado en runtime, ver `agent_docs/gestion-conocimiento.md`). Si en el futuro se agrega alguna entidad nueva a `ENTIDADES` con slug `"prestamos"`, colisionaría — no hacerlo.

---

## [2026-07-19] — Inventario físico: el sheet es carga inicial, `gestion.db` sigue siendo la fuente de verdad

**Contexto**: El usuario quiso volcar el inventario físico del laboratorio de renovables (sheet "Inventario renovable 2026", de caleiescuela@gmail.com) a `/gestion/recursos`, partiendo de un prompt de MVP que proponía Next.js + Google Sheets API con el sheet como fuente de verdad editable desde la web. El write-back web→sheet quedó explícitamente diferido.

**Decisión**:
- Sin write-back no se puede tener "sheet como fuente de verdad" + edición web a la vez (cada re-import pisaría las ediciones). Se eligió: **el sheet es carga de datos puntual** (`importar_inventario.py`, re-ejecutable, upsert por nombre normalizado) y `gestion.db` sigue siendo la fuente de verdad.
- Se mantuvo el stack Flask (misma lógica que la decisión 2026-07-17 "no Next.js"): los campos nuevos (`cantidad`, `utilidad`, `fecha_revision`) entraron por la config declarativa sin tocar templates.
- **Mapeo de estados** del sheet al vocabulario de la app: `Funcional`/`Funcional -` → `Disponible`, `Reparar` → `En reparación`, `nc` → `Sin revisar` (estado nuevo). Las observaciones ("Desafilada", "1 bien 1 muy mal") quedan en `descripcion`.
- Filas duplicadas del sheet (dos "Formon", dos "Medidor de energia solar") se importan como recursos separados: representan sets físicos distintos.
- `fecha_revision` guarda la fecha textual del sheet ("24/4") sin inventarle año.

**Consecuencia**: El import matchea contra las filas preexistentes (actualizó Multímetro y Pinza amperométrica del seed conservando sus id y relaciones M2M). El sheet del link que pasó el usuario (`1KGmaWiLMO...`) no era accesible (401); se usó "Inventario renovable 2026" (`12dNx9m9UCzP...`), encontrado por Drive y con las columnas exactas descritas — si el del link difiere, re-correr el script apuntando al otro ID. Cuando se implemente el write-back habrá que revisar esta decisión.

---

## [2026-07-19] — Contraseña compartida provisoria para todo `/gestion`

**Contexto**: `/gestion` estaba "oculto por URL, riesgo aceptado" (decisión 2026-07-17, abajo). El usuario pidió una traba mínima para que nadie entre mientras desarrolla el módulo, explícitamente sin buscar seguridad completa todavía.

**Decisión**: Login con contraseña compartida para todo el blueprint: `bp.before_request` exige `session['gestion_ok']` y redirige a `/gestion/login`. La clave viene de la env var `GESTION_CLAVE` (default público en `gestion.py`); `app.secret_key` viene de `SECRET_KEY` (default de dev en `app.py`). Se protege el módulo entero, no solo `/recursos` — mismo mecanismo, menos código.

**Alternativa descartada**: Flask-Login con tabla de usuarios — sobredimensionado para el objetivo, y `gestion.db` es efímera en Render (los usuarios se perderían en cada restart; la env var no depende del disco).

**Consecuencia**: Cubre curiosos con la URL. Pendiente para "hacerlo 100% seguro": setear `GESTION_CLAVE` y `SECRET_KEY` en el hosting (con los defaults públicos cualquiera que lea el repo conoce la clave y puede forjar la cookie), CSRF en los forms, límite de intentos. El resto de la app (horarios, `/api/actualizar`) sigue sin auth. Esto reemplaza el "sin auth, riesgo aceptado" de la decisión 2026-07-17; el ocultamiento del link se mantiene.

---

## [2026-07-17] — `/gestion` sin link visible en el SPA (acceso solo por URL)

**Contexto**: El header del SPA tenía un botón `GESTIÓN ›` junto a "ACTUALIZAR HORARIOS". El usuario pidió ocultarlo: gestión es una herramienta interna, no para alumnos/docentes que consultan horarios.

**Decisión**: Se eliminó el link del header (`index.html`) y su CSS (`a.tech-btn-gestion`). `/gestion` queda accesible únicamente escribiendo la URL. No re-agregar un acceso visible sin consultar.

**Consecuencia**: Es ocultamiento, no seguridad — quien conozca la URL entra igual (sin auth, riesgo ya aceptado). El link de vuelta al SPA desde gestión (`base.html`) se mantiene.

---

## [2026-07-17] — Gestión de Conocimiento con el stack existente y DB separada (no Next.js/Supabase)

**Contexto**: El documento de diseño del Sistema de Gestión de Conocimiento venía con un prompt que pedía Next.js + Supabase + Tailwind. Pero el pedido real fue integrarlo **dentro de AppMitre** como módulo al mismo nivel que horarios, sin tocar lo existente.

**Decisión**:
- **Stack existente** (Flask + SQLite + Jinja): un solo deploy, cero build step, consistente con la decisión "Vanilla JS sin framework". El módulo es server-rendered clásico (forms + redirects, sin JS propio) en vez de SPA — para CRUD simple es menos código y menos superficie de bugs.
- **DB separada `gestion.db`**: `escuela.db` es un caché efímero que `/api/actualizar` borra y regenera desde Sheets; los datos de gestión son la única fuente de verdad propia de la app y no pueden vivir en una DB que se dropea. Blueprint aislado en `gestion.py` para que ambos sistemas no compartan nada más que `config.py` (branding).
- **Templates genéricos manejados por config** (`ENTIDADES` en `gestion.py`): un solo trío lista/form/detalle para las 4 entidades, en vez de 12 templates.

**Alternativas descartadas**:
- *Next.js + Supabase (el stack del prompt)*: segunda app, segundo deploy, dependencia de servicio externo — contradice el pedido de integrarlo en la app actual.
- *Tablas de gestión dentro de `escuela.db`*: `/api/actualizar` las borraría (o habría que hacer el drop selectivo, acoplando los módulos).
- *Modo oscuro / temas en gestión*: `gestion.css` es standalone y no participa del sistema `data-theme`; se puede sumar después si se usa.

**Consecuencia**: En hosting con filesystem efímero (Render) `gestion.db` se pierde en cada restart — en PythonAnywhere (hosting actual) persiste. Si el módulo prospera, evaluar backup del archivo o export a Sheets. Sin auth: cualquiera puede crear/editar/borrar (mismo riesgo aceptado que `/api/actualizar`).

**Contexto**: `PLAN_ESCUELAS.md` proponía parsers por nombre de encabezado (E2 para clases, E4 para preceptores) para tolerar sheets con columnas reordenadas o insertadas. Al revisar el plan multi-escuela se definió el alcance real: la app no va a soportar sheets con formatos variables.

**Decisión**: La web asume una **estructura fija** del Google Sheet, definida por contrato en `PLANTILLA_SHEET.md`: una escuela nueva **copia la plantilla estándar** y carga sus datos. Los parsers actuales de `database.py` se mantienen tal cual.

**Precisión (verificada en código el 2026-07-13)**: E2 ya estaba resuelto de facto — `cargar_desde_sheets()` y `cargar_personal_no_docente()` usan `csv.DictReader` con encabezados normalizados (el orden de columnas es libre; el contrato son los **nombres** de encabezado). El único parser posicional es el de preceptores (bloques por offset 0/9/18), y queda así.

**Alternativa descartada**: Validación de encabezados/estructura al cargar (error claro si falta una columna). Menos frágil ante ediciones accidentales del sheet, pero se prefirió no agregar complejidad: el formato queda fijado por plantilla documentada.

**Consecuencia**:
- E2 y E4 se eliminan de `PLAN_ESCUELAS.md`; la tarea #4 del backlog se descartó.
- La Fase 2 queda reducida a E3 (API con objetos, TODO #3) + la plantilla estándar documentada (`PLANTILLA_SHEET.md`, TODO #19 — hecha el 2026-07-13).
- **Riesgo aceptado**: mover columnas en el sheet de preceptores, o renombrar un encabezado en clases/personal, corrompe o vacía datos silenciosamente. La protección es la plantilla documentada, no el código.

---

## [2026-07-01] — Sistema de temas por CSS variables + tonos curados (no picker libre)

**Contexto**: El usuario no soportaba el naranja `#FF6B00` (demasiado chillón) y pidió 3 UIs seleccionables manteniendo la estética técnica.

**Decisión**:
- Theming por **atributos independientes en `<body>`**: `data-theme` (4 temas: blueprint/swiss/nocturno/hud, layout+claro/oscuro) y `data-tone` (6 acentos, color). Se eligió atributo sobre clase porque `data-theme` es un enum limpio y coexiste con `is-fullscreen` sin colisión.
- Todo el acento pasa por `--accent`; `--secondary` quedó como **alias** (`var(--accent)`) para no tocar los 36+ usos existentes.
- El naranja base se suavizó a ámbar `#D97A34` (tono "ambar", default).
- **Tonos curados** (6 presets sobrios) en vez de un color picker libre: el usuario pidió explícitamente nada de rojo/azul/verde clásicos ("si es azul, que sea marino").
- Persistencia en **`localStorage`** (primer uso en la app) + script inline anti-flash al inicio de `<body>`.
- Temas oscuros (nocturno/hud) comparten overrides vía flag `data-dark` (seteado por JS) para no duplicar las reglas de superficie.

**Gotcha resuelto (bug real del selector)**: `--secondary`/`--accent-soft` deben declararse en **`body`, no en `:root`**. Un `var()` dentro de una custom property se congela en el elemento donde se declara; en `:root` no seguía al `--accent` del tono, así que el selector "solo cambiaba los bloques personal" (que usaban `var(--accent)` directo). Movidas a `body` → se re-resuelven contra el tono activo.

**Iteración de scope**: el tema "Compacto" (sidebar) se descartó por pedido del usuario y se reemplazó por dos temas oscuros (Nocturno + HUD).

**Alternativas descartadas**: color picker libre (riesgo estético); themes como archivos CSS separados (más peso); tema Compacto/sidebar (descartado tras review del usuario).

**Consecuencia**: Reskin casi total desde variables. Dark mode requiere overrides puntuales de colores claros hardcodeados (no todo era variable). Pendiente: `COMPARACION_COLORS` en `script.js` (paleta fija, no sigue el tono). Ver `agent_docs/frontend-ui.md` → "Temas y tonos".

---

## [fecha desconocida] — Vanilla JS sin framework

**Contexto**: App de consulta de horarios para una escuela técnica. El desarrollador es solo uno. La app no tiene proceso de build.

**Decisión**: Vanilla JS + HTML directo. Sin React, Vue, Angular ni ningún framework.

**Alternativa descartada**: Cualquier framework SPA moderno. Requeriría `npm`, un build step, y un ciclo de desarrollo más lento.

**Consecuencia**: `script.js` ha crecido a ~1600 líneas con duplicación de lógica de rendering entre `generarCalendario`, `generarCalendarioComparacion` y `generarPlanillaGeneral`. La deuda es conocida y documentada en `PLAN_ESCUELAS.md` como E3.

---

## [fecha desconocida] — SQLite efímero en lugar de PostgreSQL persistente

**Contexto**: Render.com (free tier) borra el filesystem entre restarts. Render ofrece PostgreSQL gratuito como add-on, pero tiene límites de conexiones y agrega complejidad de setup.

**Decisión**: SQLite como caché efímero de los datos de Google Sheets. La DB se regenera automáticamente desde Sheets en cada arranque en frío.

**Alternativa descartada**: PostgreSQL en Render. Requiere gestionar cadenas de conexión, migraciones, y hace la app dependiente de un servicio adicional.

**Consecuencia**: Datos siempre frescos (se re-descargan de Sheets). Sin persistencia de ningún estado. El primer usuario tras un período de inactividad espera 30–50s mientras la app "despierta" y recarga la DB. Ver `dev-log/tasks/TODO.md` #1 — el mecanismo de auto-inicialización bajo gunicorn está pendiente.

---

## [fecha desconocida] — `window.APP_DATA` cargado en el page load

**Contexto**: El autocompletado necesita filtrar ~200–300 nombres de docentes con cada keystroke.

**Decisión**: Todo el catálogo (profesores, aulas, cursos, preceptores, personal) se serializa en el HTML inicial como `window.APP_DATA.rawData`.

**Alternativa descartada**: Endpoint de autocompletado con debounce. Introduciría latencia perceptible especialmente con Render free tier (que puede tardar en responder).

**Consecuencia**: El HTML inicial es algo más pesado (~50–100KB extra). Búsquedas instantáneas sin round-trip al servidor. Si la DB tiene miles de docentes (en otro contexto), esto escalaría mal.

---

## [fecha desconocida] — `nombre_mapeos.json` manual en lugar de fuzzy matching

**Contexto**: Los nombres de profesores en el Google Sheet tienen errores tipográficos inconsistentes entre hojas (ej: "CASALE SERVIN BETTINA" vs "CASALE SERVINI BETTINA" vs "CASALE CERVINI BETINA").

**Decisión**: Archivo JSON de mapeos manuales que el desarrollador mantiene.

**Alternativa descartada**: Fuzzy matching automático (ej: Levenshtein). Los falsos positivos son inaceptables — asignar el horario de un docente a otro silenciosamente sería un bug crítico invisible.

**Consecuencia**: Requiere intervención manual cuando aparece un nuevo typo. El archivo se carga una vez al iniciar; agregar un mapeo sin reiniciar no tiene efecto inmediato.

---

## [fecha desconocida] — Acceso a filas de DB por índice numérico en el frontend

**Contexto**: La API devuelve `SELECT *` y el JS accede como `f[0]`, `f[5]`, `f[9]`, etc.

**Decisión**: [inferido] Fue una decisión de velocidad de desarrollo inicial que nunca se refactorizó.

**Alternativa descartada**: La API debería devolver objetos con claves nombradas.

**Consecuencia**: Cambiar el orden de columnas en la tabla rompería todo el frontend silenciosamente. Documentado como E3 en `PLAN_ESCUELAS.md` y como TODO #3 en el backlog.

**Resuelto [2026-07-13]**: la API devuelve objetos con claves nombradas y el frontend accede por clave. Ver `dev-log/CHANGELOG.md` [2026-07-13].

---

## [fecha desconocida] — Layout de preceptores con bloques de columnas por offset

**Contexto**: El Google Sheet de preceptores tiene 3 "tablas" yuxtapuestas horizontalmente (MAÑANA, TARDE, VESPERTINO) en lugar de una tabla única con columna de turno.

**Decisión**: `cargar_horarios_preceptores()` asume offsets fijos: MAÑANA en columna 0, TARDE en columna 9, VESPERTINO en columna 18 (8 cols de datos + 1 col separadora vacía = paso de 9). La primera fila se ignora con `next(reader, None)`.

**Alternativa descartada**: Reestructurar el sheet. El sheet ya existe con datos y no se quiere modificar la planilla original de la escuela.

**Consecuencia**: El parser es muy frágil. Si la escuela agrega o mueve columnas en el sheet de preceptores, los datos se corrompen. Documentado como E4 en `PLAN_ESCUELAS.md`.

---

## [fecha desconocida] — `corregir_horarios()` eliminada

**Contexto**: Existía una función que intentaba inferir la `hora_fin` cuando `hora_inicio == hora_fin` en el sheet (error de carga). Usaba una lista hardcodeada de horarios comunes del Mitre.

**Decisión**: La función fue eliminada. La planilla debe tener datos correctos. Si hay una clase con `hora_inicio == hora_fin`, se carga tal cual y el frontend la renderiza como bloque de 0 altura.

**Alternativa descartada**: Mantener la corrección automática.

**Consecuencia**: Los datos deben estar bien en el sheet desde el origen. Errores en el sheet son visibles en la UI (bloques raros o ausentes) en lugar de silenciosos.

---

## [fecha desconocida] — `/api/actualizar` como GET en lugar de POST

**Contexto**: [inferido] Decisión de simplicidad. Los formularios HTML y los `fetch()` simples usan GET por default.

**Decisión**: La ruta que borra y recarga la DB completa es un GET.

**Alternativa descartada**: POST con CSRF protection.

**Consecuencia**: Cualquiera que conozca la URL puede triggear una recarga de la DB. No hay autenticación. En producción (Render), el Sheet es público de todas formas, así que el riesgo es bajo — lo peor que puede pasar es un re-download innecesario.

---

## [fecha desconocida] — `allDataCache` para la Planilla General sin invalidación

**Contexto**: La Planilla General necesita todas las clases de un piso para un día. Hacer un request a `/api/dashboard` por cada cambio de día o piso sería ineficiente.

**Decisión**: Los datos se cachean en `allDataCache` después del primer fetch y no se vuelven a cargar en la sesión.

**Alternativa descartada**: Refetch en cada cambio de selector.

**Consecuencia**: Si el usuario actualiza la DB (botón ACTUALIZAR HORARIOS) mientras tiene la planilla abierta, el caché queda obsoleto. Requiere F5 para ver los datos nuevos. Es un trade-off aceptado.

---

## [2026-06-25] — PythonAnywhere como hosting

**Contexto**: Necesidad de hosting gratuito con dominio personalizado y HTTPS para la escuela.

**Decisión**: PythonAnywhere (Flask/WSGI). La DB (`escuela.db`) persiste en el filesystem entre reinicios, a diferencia de Render donde era efímera.

**Alternativa descartada**: Render.com. Render borraba el filesystem entre cold starts, lo que requería re-descargar toda la DB desde Sheets cada vez que el servicio "despertaba".

**Consecuencia**: El bloque `if __name__ == '__main__'` en `app.py` no se ejecuta bajo WSGI — la inicialización de la DB debe hacerse manualmente (consola de PythonAnywhere o via `/api/actualizar`) en un deploy nuevo. Ver TODO #1.

---

## [2026-06-29] — Toda la data cacheada en memoria al cargar + hash routing

**Contexto**: Cada búsqueda (clases y preceptores) hacía un request al server. El dataset completo es chico (`/api/dashboard` = ~2.300 filas × 20 cols; personal ~cientos de filas; preceptores 47 horarios + 62 filas de planilla). En Render/PythonAnywhere free tier, los round-trips agregan latencia perceptible. El usuario pidió explícitamente que al abrir la web se descargue **toda** la info (clases, personal, preceptores) y de ahí en más no se toque la red.

**Decisión**: `cargarDatosIniciales()` descarga todo una sola vez al cargar (`/api/dashboard`, `/api/personal_todos`, `/api/preceptores_data`) y guarda en globals (`_allClases`, `_allPersonal`, `_horariosPreceptores`, `_planillaPreceptores`). Todas las búsquedas se resuelven client-side; solo PDF y `/api/actualizar` van a la red. Se mantiene fallback a los endpoints `/api/*` si los datos aún no cargaron. En paralelo, hash routing (`#/profesor/...`) para URLs compartibles.

**Para preceptores** (tabla `horarios_preceptores`): en vez de replicar las agregaciones SQL (GROUP_CONCAT, turnos) en JS, el endpoint `/api/preceptores_data` **reusa las funciones server existentes** (`obtener_horario_preceptor`, `_planilla_preceptores_con_turnos`) y devuelve todo pre-computado, para que el cliente solo haga lookups. Esto evita una cuarta fuente de verdad de lógica SQL.

**Alternativa descartada**:
- *Service Worker / offline real (PWA)*: descartado por complejidad — el usuario eligió "session cache". Si se refresca la página se necesita red de nuevo; suficiente para un kiosco siempre encendido.
- *Clean URLs (`/profesor/...`) con catch-all en Flask*: descartado para no tocar el backend. El hash no requiere cambios en Flask.
- *Cachear filas crudas de `horarios_preceptores` y replicar las agregaciones en JS*: descartado; se prefirió pre-computar en el server reusando funciones existentes.

**Consecuencia**:
- Hay **dos fuentes de verdad** para el filtrado de clases: `obtener_filas()` (Python) y `filtrarClasesLocal()` (JS). Si una cambia, la otra debe seguirla. Los preceptores NO tienen este problema (el server pre-computa, el cliente solo lookupea).
- El caché no se invalida tras `/api/actualizar` sin un F5 (mismo trade-off ya aceptado para `allDataCache`).
- **Cambio de comportamiento (mejora)**: `obtenerPreceptorLocal()` usa el turno correcto del curso (vía `_planillaPreceptores`), corrigiendo de facto el bug de la ruta `/api/preceptor/<valor>` que devolvía siempre `TURNO_DEFAULT` por buscar la clave con `°`. El "PRECEPTOR PRINCIPAL" ahora se marca según el turno real.
- Deep-link de `horario_preceptor`: para evitar la race en `contenedor-lista` (planilla vs tabla del preceptor), `cambiarTab()` omite `mostrarPlanillaCursos()` cuando `window.isProgrammaticNavigation` está activo.

---

## [fecha desconocida] — `personalToFila()` para fusionar personal con clases

**Contexto**: En la vista de profesor, se quieren mostrar los turnos del personal no docente (porteros, secretarias) junto con los horarios de clases en el mismo calendario.

**Decisión**: `personalToFila()` convierte el objeto `{nombre, rol, dia, hora_inicio, hora_fin}` en un array de 21 elementos que imita el formato de una fila de la tabla `clases`, con `row[20] = 'personal'` como marker de tipo.

**Alternativa descartada**: Cambiar la API para devolver objetos con claves nombradas (E3 en `PLAN_ESCUELAS.md`), que haría innecesario este workaround.

**Consecuencia**: El workaround funciona pero es frágil — si la tabla `clases` agrega columnas, el índice 20 de `personalToFila` puede colisionar.

**Resuelto [2026-07-13]**: con E3 completado, `personalToFila()` devuelve un objeto con claves nombradas y marker `tipo: 'personal'` — ya no hay índices que colisionen.
