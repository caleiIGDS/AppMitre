# Salidas educativas (`/salidas`)

Quinta área de la app (las otras: el SPA de horarios, `/gestion`, `/historia`, `/agente`).
Arma el legajo digital de una salida educativa/de representación institucional (Anexos III
a IX de la Resolución RESOC-2024-3871-GDEBA-DGCYE), lo guarda en el servidor con **vigencia
de 1 año**, y genera un PDF por anexo para previsualizar/imprimir. `salidas.db` es la fuente
de verdad de lo guardado.

**Qué NO es esta área**: no es una entidad de `crud.py`. Una salida es un blob con datos
comunes + una tabla de personas de largo variable + 7 anexos, cada uno con sus propios
campos (algunos con sub-tablas) — el motor genérico de `crud.py` asume filas planas de
campos escalares y no puede modelar eso. `salidas.py` sigue el molde de **préstamos** en
`gestion.py`: tabla y rutas propias, escritas a mano, reutilizando sólo lo compartido
(`accesos`, `crud.conectar`/`crud.init_db`, `respaldos`, layout de templates). Ver
`agent_docs/crud-motor.md` para el criterio de cuándo algo entra al motor y cuándo no.

## Arquitectura

- **`salidas.py`** — el área: blueprint Flask (`bp`, prefix `/salidas`), `SCHEMA`, `PERMISOS`,
  las rutas (`lista`, `nueva`, `api_guardar`, `detalle`, `ver_pdf`) y el **renderer de PDF
  genérico** (ver abajo). `ENTIDADES = {}` a propósito — no pasa por `crud.registrar_rutas`.
- **`salidas.db`** — SQLite propia. Igual que `gestion.db`/`historia.db`/`accesos.db`:
  **no** se regenera desde Sheets, **no** viaja por git (`.gitignore`) y persiste entre
  deploys — es fuente de verdad, con la diferencia de que sus filas **vencen solas**
  (ver "Vigencia y purga" abajo).
- **`salidas_pdfs/`** — carpeta junto al módulo (mismo patrón que `backups/` de
  `respaldos.py`: fuera de `static/`, no listable/adivinable por URL). Un PDF por anexo
  por salida: `salidas_pdfs/<id>/AnexoIII.pdf` … `AnexoIX.pdf`. En `.gitignore` porque
  contienen DNI y datos de salud. El Anexo IX puede tener copias extra
  (`AnexoIX_2.pdf`, `AnexoIX_3.pdf`, ...) — ver "Más de un seguro escolar" más abajo.
- **`Salidas/AnexoN.json`** (III a IX) — la referencia completa del formulario en papel
  (label, tipo, sección, condición, columnas de cada campo, **incluidos** los campos de
  firma y "lugar y fecha"). El renderer de PDF los lee en tiempo de request; no se
  duplican en Python.
- **`templates/salidas/`** — `base.html` (layout + nav, mismo patrón que `gestion/base.html`),
  `login.html` (extiende `crud/login.html`, igual que las otras áreas), `lista.html`
  (previsualización con nombre de proyecto, fechas y vigencia), `detalle.html` (resumen +
  links a los 7 PDF, cada uno `target="_blank"`) y **`formulario.html`**: el formulario
  grande de carga (`/salidas/nueva`). Es casi todo JS/CSS propio con su propia identidad
  visual (blueprint/industrial, no el tema `gestion.css`) — no extiende `salidas/base.html`,
  igual que `index.html` (el SPA de horarios) tampoco extiende ninguna de las otras áreas.
- Integración: `app.py` hace `app.register_blueprint(salidas.bp)` + `salidas.init_db()` en
  import, y `salidas` entra a la lista de `accesos.registrar_app(...)` — el único lugar
  central que hay que tocar al sumar un área nueva (ver `agent_docs/accesos.md`).

## El formulario (`/salidas/nueva` y `/salidas/<id>/editar`)

Hereda el diseño de la herramienta standalone original (ver `dev-log/DECISIONS.md`): todo
vive en memoria del navegador (`estado = {comunes, personas, anexos}`) mientras se completa.
Precarga datos fijos de la escuela (`DATOS_FIJOS`), replica los datos comunes de la salida
a los anexos que los piden (`COMUNES[].destino`), arma una tabla de Personas una sola vez
(de ahí salen las cantidades del Anexo IV y el listado del Anexo V), y calcula derivados
(`calculado()`) como fechas largas o el conteo de docentes/estudiantes.

**Para editar una salida guardada:** entrar a `/salidas/<id>/editar` carga el formulario
precargado con todos los datos originales (desde `datos_json` en la DB). El formulario se
renderiza con `idEditar` seteado y el botón dice "Guardar cambios" en lugar de "Guardar
salida". Al guardar, `datosActuales()` incluye `_id_editar` en el JSON, que `api_guardar`
detecta para hacer UPDATE en lugar de INSERT, regenerando también los 7 PDF.

**Dos botones de guardado, dos destinos:**
- **Guardar borrador** — arma el JSON y lo descarga (Blob) a la computadora. No toca el
  servidor. Sirve para pausar y retomar después con **Cargar borrador** (`FileReader`).
- **Guardar salida** (o **Guardar cambios** si se está editando) — `fetch POST /salidas/api/guardar`
  con el mismo JSON. Es la única acción que persiste algo fuera de la pestaña: inserta o
  actualiza la fila en `salidas.db`, genera/regenera los 7 PDF, y redirige a `/salidas/<id>` o
  `/salidas/<id>/editar` según corresponda.

Los campos de **firma** y de **"lugar y fecha" de la firma** no están en el formulario
digital (`ANEXOS` en `formulario.html`) a propósito: van a mano sobre el papel impreso,
nunca se tipean — ver la decisión del 2026-08-14/15 en `dev-log/DECISIONS.md`. Los
`AnexoN.json` sí los tienen (son la referencia completa), y por eso el PDF generado los
muestra en blanco, listos para completar a mano.

## Generación de PDF — un renderer genérico, calibrado contra el papel original

No hay 7 layouts escritos a mano, pero tampoco es un volcado genérico "label en negrita
arriba, valor en un box abajo": se revisó el PDF de la Resolución página por página (cada
Anexo ahí es una imagen distinta, texto corrido con blancos "________" para completar a
mano, no una grilla con bordes salvo en dos lugares puntuales) y `_generar_pdf_anexo`
imita esa estructura. `_generar_pdf_anexo(anexo, valores, destino)` recorre el
`Salidas/AnexoN.json` correspondiente en orden (`orden`), por campo:

- Si tiene `condicion` y no se cumple contra `valores`, se saltea (ej: `representante_legal`
  del Anexo IX sólo aparece si `tipo_gestion == "privada"`).
- **Caso general** (`_dibujar_campo`): una sola línea corrida `"{label}: {valor}"`, sin
  caja — así es como se ve el 90% del papel original. Usa `pdf.write()` (no `multi_cell`)
  para poder mezclar el label en negrita con el valor en peso normal en el mismo renglón,
  vía `_escribir_par`. El resto de las funciones siguen con `multi_cell`, **siempre con
  `new_x='LMARGIN', new_y='NEXT'`**: el default de fpdf2 es `new_x=XPos.RIGHT`, que deja el
  cursor pegado al margen derecho y hace reventar el siguiente `multi_cell` con
  `FPDFException: Not enough horizontal space`; verificado en runtime.
- **Negrita y mayúscula del label** (`ANEXOS_LABEL_NEGRITA`, `LABELS_MAYUSCULA`): el peso y
  la caja de los labels **no** son parejos entre anexos en el original — Anexo V los tiene
  en negrita (y varios, además, en mayúscula: los de identificación y "OBSERVACIONES", pero
  no "Lugar y fecha" ni "Firma de Autoridad..."), Anexo IX los tiene en mayúscula **sin**
  negrita (prácticamente todos, salvo `lugar_y_fecha` y los de firma — ver
  `CAMPOS_FIRMA_IX` más abajo), Anexo IV los tiene en peso normal y caja de oración. Van por
  permiso explícito por anexo/id, igual criterio que `NOTAS_A_IMPRIMIR` — nunca un default
  global, porque no lo es en el papel.
- **`tipo == "textarea"`** (`_dibujar_textarea`): con valor, se imprime el texto. Sin valor,
  se dibujan `RENGLONES_TEXTAREA` (5) renglones en blanco con borde inferior — en el papel
  estos campos (Observaciones, Itinerario, etc.) son varias líneas para escribir a mano, no
  una sola línea corta como firma/lugar-y-fecha; sin los renglones, un campo vacío se veía
  igual que uno que simplemente no aplica, y no comunicaba "esto se completa acá".
- **`tipo == "tabla"`** (`_dibujar_tabla`): sólo se usa para `V.listado_personas`, que en
  el original **sí** es una grilla con bordes, sin ningún título arriba (arranca directo
  después del último campo de identificación) — `_dibujar_tabla` no imprime `label`. Arma
  la tabla con `pdf.table()` (fpdf2 ≥ 2.7) a partir de `columnas` y de
  `valores[campo['id']]`; sin filas, muestra un placeholder (`-`, no `—`: el em dash no
  está en el charset de `helvetica` core y tira `FPDFUnicodeEncodingException`).
- **Campos que comparten renglón** (`CAMPOS_MISMA_LINEA`, por id): en el original varios
  grupos van en la misma línea — no siempre pares: Anexo V `"INSTITUCIÓN EDUCATIVA ___
  N°___"` son dos campos, Anexo IV `"Fecha de salida ___ Hora ___ Lugar ___"` son tres.
  Cada entrada es una tupla del grupo completo, en el orden real del renglón; el primer id
  arrastra al resto (`_dibujar_campo(..., extra=[...])`) y el resto se saltea en el loop
  principal (`ids_resto_linea`) para no imprimirse de nuevo suelto.
- **`tipo == "nota"`**: no es un campo a completar, es texto fijo del papel entre dos
  campos (ej. Anexo V: `"La presente planilla tendrá validez para toda tramitación oficial
  que se realice."`, entre `observaciones` y `lugar_y_fecha`) — `_dibujar_nota` imprime
  `label` tal cual, sin `"label: valor"`. También se usa para bloques legales de varios
  párrafos que no tienen ningún blanco para completar (ej. Anexo VI sección `salud`, VII e
  IX: los párrafos de "Autorizo..."/"Declaramos bajo juramento..." del original) — el
  `label` en el JSON junta los párrafos con `\n\n`, que `multi_cell` respeta como salto de
  línea real.
- **`notas` de un campo que sí van impresas** (`NOTAS_A_IMPRIMIR`, por id): `notas` en el
  JSON puede ser una aclaración real del papel (footnote pegada al label, ej. Anexo V
  `observaciones`: `"(Para ser completado ante cualquier eventualidad)"`, o Anexo IV
  `observaciones_fechas`/`itinerario`: `"(en caso de corresponder)"`/`"(detalle
  pormenorizado del mismo)"`) o un criterio mío sobre el schema que no está en el papel (ver
  `Salidas/README_campos.md`) — no se puede distinguir mecánicamente, así que sólo se
  imprimen las que ya se verificaron contra el original anexo por anexo. Imprimirlas todas
  de una hubiese repetido, en otro anexo, el mismo bug que motivó este mecanismo: texto en
  el PDF que no existe en el papel.
  **Dónde va la aclaración respecto de los `:`** tampoco es parejo: Anexo V la pone
  *después* (`"OBSERVACIONES:(Para ser completado...)"`), Anexo IV la pone *antes*
  (`"Itinerario (detalle pormenorizado del mismo):"`) — `NOTAS_ANTES_DE_DOSPUNTOS` (sólo
  afecta a `_dibujar_textarea`) marca los anexos que van antes; el resto usa el default
  (después).
  **Anexo IX es un caso distinto, no `NOTAS_A_IMPRIMIR`**: sus notas (1)/(2) no están
  pegadas al campo en el papel — son notas al pie de página de verdad, impresas juntas y
  aparte, después de la declaración jurada y antes de "Lugar y Fecha". El "(1)"/"(2)" quedó
  como texto literal del propio `label` en el JSON (`"Tipo de seguro (1)"`,
  `"Observaciones (2)"` — así se ve en el papel) y el texto de las notas es un campo
  `tipo: "nota"` aparte (`nota_pie_seguro`), en su lugar real. La primera versión de esto
  las pegaba inline junto al campo con `NOTAS_A_IMPRIMIR` (mal: ni el texto era el correcto
  — decía "Debe" en vez de "Deberá", y la nota (2) estaba truncada — ni el lugar).
- **Párrafos narrativos con blancos intercalados** (`PARRAFOS_NARRATIVA`, por anexo): en
  varios anexos el original **no abre** con una lista de "label: valor" — abre con una
  oración corrida con blancos para completar en el medio (ej. Anexo III: `"Por la presente
  autorizo a ____, DNI ____, estudiante de ____ Año, sección ____, a participar de..."`).
  Los datos se siguen pidiendo como campos sueltos en el JSON (los necesita el formulario
  HTML tal cual), pero `_dibujar_narrativa` los teje dentro de la oración real en vez de
  imprimirlos como líneas separadas. Cada bloque declara `ids` (los campos que consume, en
  el orden del `{...}` de la plantilla) y `texto` (la plantilla con `.format()`); el primer
  id dispara el render del bloque entero y el resto se saltea en el loop principal
  (`ids_narrativa_resto`) para no imprimirse de nuevo suelto. Un `select` cuyo valor
  guardado es un slug pero el papel espera texto (Anexo VII `tipo_salida`: `"educativa"` →
  `"salida educativa"`) usa `mapeos` en vez de `_texto_valor`. Confirmado contra el original
  para III, VI (sección `autorizacion`) y VII — los demás anexos van campo por campo, igual
  que antes, porque ninguno abre con un párrafo así.
  **`segmentos` en vez de `texto`** (sólo Anexo VII): dentro del párrafo, el original tiene
  `"salida educativa / de representación institucional"` en **negrita** y `"(tachar lo que
  no corresponda)"` en *itálica* — no es un bloque de un solo estilo como III y VI. Un
  bloque con `segmentos` es una lista de `(texto con placeholders, estilo)` — estilo vacío,
  `'B'` o `'I'` — que `_dibujar_narrativa` escribe con `pdf.write()` cambiando de fuente
  entre cada uno, en vez de un único `multi_cell`.
- **`notas_generales`** (párrafo de cierre del anexo, después de las firmas en el original)
  se imprime al final sólo para los anexos en `NOTAS_GENERALES_A_IMPRIMIR` — mismo criterio
  de "no imprimir sin haber comparado contra el original primero" que `NOTAS_A_IMPRIMIR`.
- **Las tablas de docentes del Anexo IV** (`docentes_responsables_titulares`,
  `docentes_reemplazantes`, detectadas por id — `CAMPOS_DOCENTES`) **no** usan
  `pdf.table()`: en el original son renglones repetidos "Apellido y Nombre ____ Cargo
  ____", uno por docente, sin bordes — `_dibujar_docentes` los imprime así.
- **El grupo "Tiene Obra Social/Prepaga"** (VI y VII, detectado por id —
  `CAMPOS_OBRA_SOCIAL`) sí es una cajita con bordes en el original (3 renglones: Sí/No ·
  Nombre · N° Socio) — `_dibujar_obra_social` la arma con `pdf.table()` y se saltea
  `nombre_obra_social`/`numero_socio` en el loop principal (van adentro de la cajita).
- **El bloque de firmas del Anexo IX** (`firma_sello_director`,
  `firma_sello_representante_legal`, detectados por id — `CAMPOS_FIRMA_IX`) es dos columnas
  lado a lado en el original ("FIRMA Y SELLO" / "DIRECTOR/A" a la izquierda, "FIRMA Y
  SELLO" / "REPRESENTANTE LEGAL" a la derecha, la segunda sólo si `tipo_gestion ==
  "privada"`), no dos líneas sueltas "Firma y sello del Director/a: ___" una debajo de la
  otra. `_dibujar_firmas_ix` usa `pdf.cell()` con ancho fijo para las dos columnas e ignora
  el `label` del JSON (que sigue describiendo el campo para el formulario HTML) — dibuja el
  texto fijo del papel directo.
- **Encabezados de sección**: `Salidas/AnexoN.json` agrupa campos con una clave corta
  (`seccion: "hospedaje_mas_24hs"`, `"informativa"`, etc.) que es un identificador interno,
  **no** el texto impreso. `SECCION_TITULOS` (en `salidas.py`) traduce cada slug al texto
  real del papel (ej. `"1- Planilla informativa para padres, madres, tutores o
  responsables (completa la Escuela)"` para el Anexo VI) — un slug ausente de esa tabla no
  imprime encabezado, que es lo correcto para los bloques que en el original no tienen
  título propio.
- Título centrado (`ANEXO {n}` + el `titulo` del JSON), no alineado a la izquierda — así
  encabeza cada Anexo en el papel. Varios `titulo` del JSON son en realidad dos líneas del
  papel unidas con `" — "` (ej. Anexo IV: "PRESENTACIÓN..." / "FORMULARIO DE
  ITINERARIO..."); `_generar_pdf_anexo` las vuelve a separar (`titulo.split(' — ')`, una
  `multi_cell` centrada por parte) en vez de imprimir una sola línea larga. Cada parte se
  imprime en **mayúscula** (`.upper()` al armar la `multi_cell`, no en el JSON): así está el
  título en los 7 anexos del original — verificado en los 7, no es un permiso por anexo
  como `ANEXOS_LABEL_NEGRITA`/`LABELS_MAYUSCULA`, es parejo siempre. El JSON guarda `titulo`
  en caja de oración porque es más legible como dato/en el panel de administración.
- **`V.listado_personas`** tiene anchos de columna fijos (`COL_WIDTHS`, en mm) en vez del
  reparto automático de `pdf.table()`: parejo, "Apellido y Nombre" queda tan angosta como
  "N°" y el nombre se corta en dos líneas — en el papel esa columna es, a ojo, ~5 veces más
  ancha. Es el único id con ancho fijado a mano; cualquier tabla nueva que se agregue sin
  entrada en `COL_WIDTHS` vuelve a repartirse sola.
- Un campo sin valor en `valores` (los 14 de firma/lugar-y-fecha, u otro que no se haya
  completado) se imprime **en blanco**: es el comportamiento correcto.

Esto sigue siendo "genérico" en el sentido que importa: agregar o cambiar un campo es
editar el JSON, no tocar `salidas.py`. Lo que hay de especial son puntos de anclaje por id
(`tiene_obra_social`, las dos tablas de docentes, los pares de `CAMPOS_MISMA_LINEA`, las
`notas` de `NOTAS_A_IMPRIMIR`) más dos tablas de traducción/permiso (`SECCION_TITULOS`,
`NOTAS_GENERALES_A_IMPRIMIR`) — no 7 funciones de layout distintas.

**Tipografía**: `helvetica` (fuente *core* de fpdf2, sin `add_font`) en vez de la
`RobotoMono` que usa el resto de la app. El original está tipeado en una sans-serif
proporcional (Arial/Helvetica); para estos PDF —que imitan un formulario oficial ajeno, no
la identidad visual de AppMitre— parecerse al papel pesa más que la consistencia con los
PDF de horarios. Ojo con esto si se agrega texto nuevo: el charset de `helvetica` core es
angosto (evitar em dash `—`, usar `-`; ver el punto de la tabla arriba). Tamaño de cuerpo
`TAM_TEXTO = 11` / alto de línea `ALTO_LINEA = 7` (antes 10/6 — se agrandó, quedaba chico
contra el papel real); las demás funciones escalan a partir de esas dos constantes en vez
de tener números sueltos.

Reusa la subclase `_PDFAnexo(FPDF)` propia (no la `PDF` de `app.py`, para no crear un
acoplamiento entre módulos). `pdf.output(destino)` escribe a disco directamente (a
diferencia de los PDF de horarios, que sólo se arman en memoria).

**Membrete**: `_PDFAnexo.header()` dibuja `static/images/escudo.svg` arriba a la
izquierda, y `_PDFAnexo.footer()` dibuja, abajo, en **todas** las páginas (fpdf2 los llama
solo en cada `add_page()`, incluidos los saltos de página automáticos): el número de
documento GEDO (`schema['fuente']`, ej. `"IF-2024-35029666-GDEBA-CGCYEDGCYE"`) **a la
derecha** (alineado con `"página N de {nb}"`, no a la izquierda — así se ve más ordenado
contra el logo grande de al lado; el original lo tiene más centrado, pero el pedido fue
puntual: todo lo que es texto de pie va a la derecha), `static/images/logo-pba.png` abajo a
la izquierda con `h=18` (antes `h=10` — se agrandó a pedido, es lo primero que se ve del
pie), y `"página N de {nb}"` a la derecha (`pdf.alias_nb_pages()` habilita el alias `{nb}` =
total de páginas del PDF).
**El número GEDO NO va bajo el título** — se probó ahí primero y no se parecía al original:
en el papel real ese número es pie de página, no subtítulo, así que `_generar_pdf_anexo` lo
guarda en `pdf.fuente_doc` antes de `add_page()` y es `footer()` quien lo dibuja.
`set_auto_page_break` usa `margin=22` (no el `15` de otros PDF de la app) para dejarle
lugar a las tres líneas del pie sin que la última línea de contenido de una página llena
las pise.

- `escudo.svg` se dibuja **directo** con `pdf.image()`: fpdf2 ≥ 2.7 soporta SVG nativo
  (`VectorImageInfo`) para paths/gradientes simples.
- `logo-pba.png` **no** es el `logo-pba.svg` del root: ese SVG es un `<rect>` con
  `fill: pattern` que envuelve un PNG embebido en base64 (`<pattern>`/`<image>` de SVG),
  algo que fpdf2 no soporta — lo dibuja en blanco, sin avisar con un error (sólo un
  "Ignoring unsupported SVG tag: `<pattern>`" en el log). El PNG real se extrajo una sola
  vez del `xlink:href` en base64 y quedó commiteado en `static/images/logo-pba.png`; si el
  logo cambia, hay que repetir esa extracción, no simplemente apuntar al `.svg` de nuevo.

## Más de un seguro escolar (Anexo IX)

La escuela puede tener más de una póliza de seguro escolar vigente a la vez (ej. una
Responsabilidad Civil para estudiantes menores de edad y otra para mayores, más una de
accidentes personales). El papel real del Anexo IX sólo tiene lugar para **una** póliza
por Declaración Jurada — no es una tabla — así que cada seguro adicional que se carga
genera su **propia copia completa** del Anexo IX (misma identificación/declaración, sólo
cambia el bloque "Datos del seguro escolar"), no una fila más en una lista.

- **`formulario.html`**: el bloque `compania_aseguradora`/`tipo_seguro`/`numero_poliza`/
  `vigencia_poliza` del Anexo IX ya no es `auto:true` (dejó de precargarse solo desde
  `DATOS_FIJOS` — ver por qué en el comentario de `SEGURO_A_FIJO`: si fuera `auto`,
  `refrescarDerivados()` pisaría cualquier edición manual apenas se tocara otro campo de
  Datos Comunes). En su lugar hay un selector de **preset** (`SEGUROS_PRESET`, 3 pólizas
  reales de la escuela — actualizar ahí cuando cambien) que copia sus 4 valores a los
  campos con `campoPresetSeguro()`/`copiarPreset()`; los campos quedan editables a mano
  después de elegir un preset, igual que si se hubiese completado todo a mano desde el
  principio. Debajo, **`segurosAdicionales()`** arma una lista repetible (mismo patrón
  visual que la tabla de Personas, pero más chica: sin tabla, una tarjeta por seguro) que
  guarda cada entrada en `estado.anexos.IX._seguros_adicionales` — un array plano, **no**
  un campo del schema de `Salidas/Anexo9.json` (`_generar_pdf_anexo` sólo itera
  `schema['campos']`, así que esta clave extra en `valores` no le afecta para nada al
  render del Anexo IX principal).
- **`salidas.py` — `_generar_pdfs`**: después de generar `AnexoIX.pdf` con el seguro
  principal, recorre `anexos['IX']['_seguros_adicionales']` y por cada uno arma una copia
  de `valores` con los 5 campos del seguro (`CAMPOS_SEGURO_IX`) pisados por esa entrada,
  y llama a `_generar_pdf_anexo('IX', ...)` de nuevo — mismo renderer, sin código nuevo de
  layout — guardando en `AnexoIX_2.pdf`, `AnexoIX_3.pdf`, etc. (`_ruta_pdf_ix_extra`).
  Antes de generar las copias, `_limpiar_pdfs_ix_extra` borra las que ya hubiera en la
  carpeta: si se edita una salida y se saca un seguro, no queda un PDF viejo huérfano.
- **`ver_pdf`**: además del allowlist exacto de `ANEXOS_NUMEROS`, acepta `anexo` con forma
  `IX_<n>` vía un regex (`_RE_ANEXO_IX_EXTRA`) — sigue siendo un allowlist estricto, no
  "cualquier cosa que no esté en la lista", porque `anexo` viene de la URL y arma una ruta
  de archivo en disco.
- **`detalle()`** detecta las copias extra **por archivo en disco** (`while
  os.path.exists(...)`), no releyendo `datos_json` — así la lista siempre refleja lo que
  hay realmente generado, incluso si el JSON guardado y los PDF quedaran desincronizados
  por algún motivo. Se muestran como "Anexo IX (seguro 2)", etc. (`etiquetas`, separado de
  `titulos` para no repetir el título completo en la columna del anexo).

## Vigencia y purga

Al guardar (`api_guardar`), `vigencia_hasta = fecha_creacion + 365 días` (`config.ahora()`).
`salidas.init_db()` llama primero a `crud.init_db()` (respalda, crea tablas, siembra) y
**recién después** corre `_purgar_vencidas()`: borra las filas de `salidas` con
`vigencia_hasta` pasada y su carpeta de `salidas_pdfs/<id>/`. Sin papelera ni tabla de
auditoría — se va del todo, sin vuelta atrás. Es una decisión explícita: se prioriza no
retener datos sensibles (DNI, salud) más de lo necesario, en línea con el mismo criterio
que ya regía el formulario standalone original ("no persistente en la compu que se esté
usando"). Ver `dev-log/DECISIONS.md`.

**Por qué el testigo de `crud.init_db` NO es la tabla `salidas`**: `crud.init_db` levanta
`RuntimeError` si la `TABLA_TESTIGO` está vacía pero existen respaldos previos (para
detectar un archivo perdido — ver el comentario de `gestion.py` sobre la pérdida del
2026-08-08). La tabla `salidas` queda **legítimamente vacía** cada vez que todas las
salidas guardadas vencen y se purgan solas: si fuera el testigo, el primer año sin salidas
activas tumbaría el arranque de la app entera. Por eso el testigo es `salidas_meta`, una
tabla de un solo renglón (`id=1`) sembrada una vez en el primer `init_db()` y nunca más
tocada — siempre tiene datos, así que nunca dispara el guard.

## Rutas

| Ruta | Método | Gate | Qué hace |
|---|---|---|---|
| `/salidas/` | GET | `salidas.leer` | Previsualización: nombre de proyecto, fecha de salida, guardada, vigente hasta |
| `/salidas/nueva` | GET | `salidas.editar` | El formulario grande de carga |
| `/salidas/<id>/editar` | GET | `salidas.editar` | El formulario precargado con datos de una salida existente para reeditar |
| `/salidas/api/guardar` | POST | `salidas.editar` | JSON del formulario → **inserta** la fila si es nueva, o **actualiza** si viene `_id_editar`; genera/regenera los 7 PDF, devuelve `{id}` |
| `/salidas/<id>` | GET | `salidas.leer` | Detalle: datos comunes + links a los PDF disponibles |
| `/salidas/<id>/pdf/<anexo>` | GET | `salidas.leer` | `send_file` del PDF guardado, `as_attachment=False` (se abre en el navegador, no se descarga solo) |

## Permisos

| clave | verbo | qué habilita |
|---|---|---|
| `salidas.leer` | leer | ver la lista de salidas guardadas y sus PDF. Permiso base del blueprint |
| `salidas.editar` | escribir | cargar el formulario y guardar salidas nuevas |

Dado que una salida guarda DNI y datos de salud, no hay ninguna ruta pública: todas piden
al menos `salidas.leer`. El motor entero de accesos está en `agent_docs/accesos.md`.

## PDF con referencias normativas

La Resolución 3871/24 (`static/salidas/resolucion-3871-24.pdf`) está integrada al módulo:

- **`GET /salidas/normativa`** (ruta nueva, sin gate): visor propio con pdf.js vendored
  (`static/vendor/pdfjs/`) que renderiza el PDF en canvas y resalta texto de búsqueda.
  Query params: `?pagina=N&buscar=<frase>`. El resaltado se dibuja en amarillo con borde oro
  — funciona igual en todos los navegadores (no depende del visor integrado).
- **Links en el formulario**: cada mensaje informativo (aviso general, notas de anexo, ayudas
  de campo, etc.) que cita un punto normativo concreto tiene un link "📄 Ver en la
  Resolución" que abre `/salidas/normativa?pagina=N&buscar=<frase>` en pestaña nueva. El
  mapeo se mantiene en `Salidas/advertencias_normativa.json` (24 mensajes, 18 con página
  específica).
- **Botón en header**: "📄 Ver Resolución" abre `/salidas/normativa` en pestaña nueva (página
  1).
- **Link en detalle**: la nota sobre firma original (línea 27 de `detalle.html`) apunta a
  `/salidas/normativa?pagina=16` (sección 10: "Instructivo para completar los anexos").

Todas las referencias están verificadas contra el texto real del PDF con `pypdf` (no de
memoria).
