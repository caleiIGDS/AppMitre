# Decisiones de Arquitectura — AppMitre

Leer este archivo antes de "corregir" algo que parece raro. Muchas decisiones tienen contexto específico de la escuela o del despliegue.

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
