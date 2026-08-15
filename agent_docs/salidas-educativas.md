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
  contienen DNI y datos de salud.
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

## El formulario (`/salidas/nueva`)

Hereda el diseño de la herramienta standalone original (ver `dev-log/DECISIONS.md`): todo
vive en memoria del navegador (`estado = {comunes, personas, anexos}`) mientras se completa.
Precarga datos fijos de la escuela (`DATOS_FIJOS`), replica los datos comunes de la salida
a los anexos que los piden (`COMUNES[].destino`), arma una tabla de Personas una sola vez
(de ahí salen las cantidades del Anexo IV y el listado del Anexo V), y calcula derivados
(`calculado()`) como fechas largas o el conteo de docentes/estudiantes.

**Dos botones de guardado, dos destinos:**
- **Guardar borrador** — arma el JSON y lo descarga (Blob) a la computadora. No toca el
  servidor. Sirve para pausar y retomar después con **Cargar borrador** (`FileReader`).
- **Guardar salida** — `fetch POST /salidas/api/guardar` con el mismo JSON. Es la única
  acción que persiste algo fuera de la pestaña: crea la fila en `salidas.db`, genera los 7
  PDF y redirige a `/salidas/<id>`.

Los campos de **firma** y de **"lugar y fecha" de la firma** no están en el formulario
digital (`ANEXOS` en `formulario.html`) a propósito: van a mano sobre el papel impreso,
nunca se tipean — ver la decisión del 2026-08-14/15 en `dev-log/DECISIONS.md`. Los
`AnexoN.json` sí los tienen (son la referencia completa), y por eso el PDF generado los
muestra en blanco, listos para completar a mano.

## Generación de PDF — un renderer genérico

No hay 7 layouts escritos a mano. `_generar_pdf_anexo(anexo, valores, destino)` recorre el
`Salidas/AnexoN.json` correspondiente en orden (`orden`), por campo:

- Si tiene `condicion` y no se cumple contra `valores`, se saltea (ej: `representante_legal`
  del Anexo IX sólo aparece si `tipo_gestion == "privada"`).
- Si `tipo == "tabla"`, arma la tabla con `pdf.table()` (fpdf2 ≥ 2.7) a partir de
  `columnas` y de `valores[campo['id']]` (lista de dicts); sin filas, muestra un placeholder.
- Si no, imprime label + valor con `multi_cell` (**siempre con `new_x='LMARGIN',
  new_y='NEXT'`** — el default de fpdf2 es `new_x=XPos.RIGHT`, que hace que el cursor
  quede pegado al margen derecho y el siguiente `multi_cell` reviente con
  `FPDFException: Not enough horizontal space`; verificado en runtime).
- Un campo sin valor en `valores` (los 14 de firma/lugar-y-fecha, u otro que no se haya
  completado) se imprime **en blanco**: es el comportamiento correcto.

Reusa el registro de fuentes (`static/fonts/RobotoMono-*.ttf`) con el mismo patrón que
`app.py` usa para los PDF de horarios — pero con su propia subclase `_PDFAnexo(FPDF)` (no
la `PDF` de `app.py`, para no crear un acoplamiento entre módulos). `pdf.output(destino)`
escribe a disco directamente (a diferencia de los PDF de horarios, que sólo se arman en
memoria).

**Membrete**: `_PDFAnexo.header()` dibuja `static/images/escudo.svg` arriba a la
izquierda, y `_PDFAnexo.footer()` dibuja `static/images/logo-pba.png` abajo a la
izquierda, en **todas** las páginas (fpdf2 los llama solo en cada `add_page()`, incluidos
los saltos de página automáticos). `set_auto_page_break` usa `margin=22` (no el `15` de
otros PDF de la app) para dejarle lugar al logo del footer sin que la última línea de
contenido de una página llena lo pise.

- `escudo.svg` se dibuja **directo** con `pdf.image()`: fpdf2 ≥ 2.7 soporta SVG nativo
  (`VectorImageInfo`) para paths/gradientes simples.
- `logo-pba.png` **no** es el `logo-pba.svg` del root: ese SVG es un `<rect>` con
  `fill: pattern` que envuelve un PNG embebido en base64 (`<pattern>`/`<image>` de SVG),
  algo que fpdf2 no soporta — lo dibuja en blanco, sin avisar con un error (sólo un
  "Ignoring unsupported SVG tag: `<pattern>`" en el log). El PNG real se extrajo una sola
  vez del `xlink:href` en base64 y quedó commiteado en `static/images/logo-pba.png`; si el
  logo cambia, hay que repetir esa extracción, no simplemente apuntar al `.svg` de nuevo.

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
| `/salidas/api/guardar` | POST | `salidas.editar` | JSON del formulario → inserta la fila, genera los 7 PDF, `{id}` |
| `/salidas/<id>` | GET | `salidas.leer` | Detalle: datos comunes + links a los PDF disponibles |
| `/salidas/<id>/pdf/<anexo>` | GET | `salidas.leer` | `send_file` del PDF guardado, `as_attachment=False` (se abre en el navegador, no se descarga solo) |

## Permisos

| clave | verbo | qué habilita |
|---|---|---|
| `salidas.leer` | leer | ver la lista de salidas guardadas y sus PDF. Permiso base del blueprint |
| `salidas.editar` | escribir | cargar el formulario y guardar salidas nuevas |

Dado que una salida guarda DNI y datos de salud, no hay ninguna ruta pública: todas piden
al menos `salidas.leer`. El motor entero de accesos está en `agent_docs/accesos.md`.
