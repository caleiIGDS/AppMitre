# Asistente conversacional con tool-calling (`/agente`)

Cuarta área de la app, al mismo nivel que horarios, `/gestion` (recursos) e `/historia`
(línea del tiempo institucional) — y la única transversal: **lee las tres y escribe en dos**
(recursos e historia institucional; los horarios son solo de consulta). Vive en su propio
paquete (`agente/`), su propio prefijo (`/agente`) y su propia carpeta de templates
(`templates/agente/`).

Es **un solo asistente** para todas las áreas, no uno por área: en la misma conversación se
pregunta un horario, se da de alta un recurso y se carga un hito. Separarlo en varios
rompería justamente eso.

Expone un chat conversacional contra el LLM configurado (DeepSeek por defecto,
Anthropic/OpenAI/Groq/Ollama según `AGENTE_PROVIDER` — ver "Configuración"). El usuario puede
hablar con la app en lenguaje natural en vez de hacer click en formularios: consultar
horarios, crear recursos, fotografiar etiquetas y cargarlas, gestionar préstamos, cargar
hitos y personas. Todo con auditoría de escrituras en `agente_log`.

**Acceso**: dos vistas del mismo chat, ambas detrás del gate de `accesos.py`
(`accesos.registrar_acceso(bp, 'agente.leer', ...)`). El asistente declara **tres permisos
propios** —`agente.leer`, `agente.escribir`, `agente.auditar`— y **con cuáles tenga cambia lo que el
agente es**: con solo `agente.leer` las diez tools de escritura ni se le mandan al modelo. Ver
"Permisos" más abajo y `agent_docs/accesos.md`.
- Botón "🤖 ASISTENTE" en el header de `/gestion` y `/historia` → widget flotante, para
  consultar sin salir de la página en la que se está.
- `/agente/`, el chat a pantalla completa. Es la vista pensada para el celular, que es donde
  más se usa el asistente.

## A qué datos llega (`SLUGS_ENTIDAD` y `_modulo`)

El agente cruza **dos DBs de dominio** más los horarios:

| Fuente | Slugs / datos | Acceso |
|---|---|---|
| `escuela.db` (horarios) | profesores, cursos, aulas | solo lectura |
| `gestion.db` (recursos) | `recursos`, `conjuntos`, `actividades` + préstamos | lectura y escritura |
| `historia.db` (institucional) | `hitos`, `personas` | lectura y escritura |
| `historias/*.json` (lore) | anécdotas de Emilio Mitre | solo lectura |

- **`SLUGS_ENTIDAD = list(gestion.ENTIDADES) + list(historia.ENTIDADES)`** — se deriva, no se
  escribe a mano. Es el enum de `slug` de todos los esquemas de tools; cuando estaba
  hardcodeado, agregar una entidad la dejaba invisible para el chat sin que nada fallara.
- **`_modulo(slug)`** devuelve `gestion` o `historia` según en cuál `ENTIDADES` está el slug.
  Todas las tools genéricas (`buscar_entidad`, `listar_todos`, `detalle_entidad`,
  `crear_entidad`, `editar_entidad`, `eliminar_entidad`, `vincular_entidad`,
  `desvincular_entidad`, `adjuntar_foto`) pasan por ahí y le entregan ese módulo al motor:
  `crud.buscar_entidad(_modulo(slug), slug, q)`, `crud.guardar_entidad(...)`, etc. **El área es
  siempre el primer argumento de `crud`.** Los dos módulos cumplen el mismo contrato de área
  (ver `agent_docs/crud-motor.md`), así que el agente los trata igual sin saber en cuál está
  parado.
- **Las relaciones M2M son siempre intra-módulo**: desde que se eliminó `proyecto_recursos` no
  hay ninguna que cruce recursos ↔ historia, así que `_vincular_entidad` resuelve todo con el
  módulo del slug de origen.
- **`agente.DB_PATH` sigue siendo `gestion.db`**: las tablas propias del agente
  (`agente_log`, `agente_conversaciones`, `agente_fotos_pendientes`) viven ahí — son
  auditoría y sesión, no datos de dominio.

### Arquitectura

El área es un **paquete** (`agente/`), no un módulo suelto. Hacia afuera no cambia nada:
`app.py` sigue haciendo `import agente` y usando `agente.bp` e `agente.init_db()`, que es
toda la superficie pública.

| Módulo | Rol |
|---|---|
| `agente/__init__.py` | Crea el `bp` e importa `rutas` (que lo registra). El mapa del paquete y la config por env var están documentados acá. |
| `dominio.py` | `RAIZ` del proyecto + `_modulo(slug)` y `SLUGS_ENTIDAD`. Lo importa casi todo. |
| `proveedores.py` | Config del LLM del chat **y** del lector de imágenes, que son independientes. Se llama así y no `config` para no confundirse con el `config.py` de la raíz. |
| `db.py` | Las tres tablas propias en `gestion.db`: auditoría, conversación, fotos pendientes. |
| `padrones.py` | Los dos padrones de personas y el cruce entre ellos. Fuera de `tools/` porque lo usan las tools **y** el system prompt. |
| `lore.py` | La historia de la escuela y la voz de Emilio (`QUIEN_ES_EMILIO`, `COMO_CUENTA_EMILIO`, `EXCUSA_SIN_HISTORIA`). |
| `vision.py` | El lector de etiquetas: una llamada suelta, sin tools. |
| `prompt.py` | `construir_system_prompt()` — ~280 líneas de contenido, aparte del motor. |
| `llm.py` | Clientes por proveedor y los **dos** loops de tool-calling. |
| `filtros.py` | `_ocultar_ids`, `_quitar_acotaciones` y las utilidades de contexto. |
| `rutas.py` | Los endpoints Flask + el gate de acceso + el context processor. |
| `tools/` | Lo que el agente sabe hacer: `esquemas.py` (lo único que el modelo ve) y un módulo por área con los ejecutores. `tools/__init__.py` tiene `ejecutar_tool`, el dispatch. |

**El criterio del corte es la cohesión, no la capa**: el esquema de una tool y su ejecutor
quedan en el mismo módulo de área siempre que se pueda, porque son lo que cambia junto. Por
eso no hay un "archivo de descripciones" separado de un "archivo de código" — eso obligaría a
tocar dos archivos para agregar una tool en vez de uno. Ver `dev-log/DECISIONS.md` 2026-08-10.

Las dependencias van en una sola dirección y **no hay ciclos**:
`dominio → proveedores/db → padrones/lore/vision → tools → prompt/llm → rutas`.
- **`POST /agente/chat`** — acepta `{mensaje, imagen?}` (imagen en base64 o data URL);
  retorna `{respuesta}`. El backend llama al modelo con el mensaje + tools disponibles, ejecuta
  lo que pida (tools de lectura y escritura), repite hasta respuesta final, audita
  escrituras en `agente_log`. `mensaje` puede venir vacío **si viene `imagen`** (mandar solo
  la foto de una etiqueta es un caso normal); vacío y sin foto es `400`. Ver "Alta desde foto".
- **`GET /agente/historial`** — devuelve `{mensajes: [{rol, texto}], confirmaciones}`
  para repintar el chat al cargar la página. `gestion-agente.js` lo llama en el
  `DOMContentLoaded` (`cargarHistorial()`). **Hace falta desde que la conversación pasó a
  `gestion.db`**: el servidor la recuerda entre páginas, pero el chat se dibuja de cero en
  cada carga, así que el historial existía y no se veía. Devuelve también los botones de las
  altas que hayan quedado sin confirmar — si no, navegar a otra página dejaba las fichas
  vivas en el servidor y sin forma de darles OK. `_texto_visible()` aplana los bloques de
  contenido y saca lo que `chat()` le agrega al mensaje del usuario y él no escribió: el
  `(refiriéndote a: X)` y el `[Hora de este mensaje: ...]` (ver "La hora en cada mensaje").
- **`POST /agente/confirmar`** — acepta `{token}` de una ficha de alta pendiente y
  la guarda sin pasar por el modelo. `409` si el token ya se usó, se reinició la
  conversación, o quedó desplazado por fichas más nuevas. Ver "Alta con ficha de
  confirmación".
- **`POST /agente/reset`** — limpia `session['agente_historial']` y
  `session['agente_entidad_actual']`; usado por el botón ↺ del widget para arrancar una
  conversación nueva sin arrastrar contexto viejo.
- **`GET /agente/`** (`chat_page`) — la pestaña del chat a pantalla completa
  (`templates/agente/agente_chat.html`, extiende `base.html`).
- **`GET /agente/log`** — tabla de auditoría (últimas 50 escrituras), con snapshot
  "antes" visible para poder restaurar manualmente si el agente cometió un error.

**Gate de sesión**: lo monta el motor compartido, en una línea al final del módulo —

```python
crud.registrar_acceso(bp, endpoints_pagina=_ENDPOINTS_PAGINA, endpoint_default='chat_page')
```

`/agente` es el único blueprint que **mezcla páginas HTML con endpoints JSON**, y por eso pasa
`endpoints_pagina`: los endpoints JSON (`/chat`, `/reset`, `/confirmar`, `/historial`) devuelven
`401` sin sesión, que es lo que el `fetch` del frontend sabe manejar; un redirect a HTML le
llegaría como un 200 sin sentido. Los que devuelven HTML —los de `_ENDPOINTS_PAGINA`— redirigen
a `/agente/login?next=...`, porque entrar por link directo a `/agente` desde el celular es el
caso normal y un 401 pelado ahí es un callejón sin salida.

Mismo motor de accesos y mismo `next` scopeado al prefijo propio (contra open redirect) que
`/gestion` e `/historia`. Con acceso pero **sin** el permiso de la ruta la respuesta es **403**, no
el login. Dos rutas piden más que el permiso base:

| ruta | permiso | por qué |
|---|---|---|
| `/agente/confirmar` | `agente.escribir` | **escribe sin pasar por el LLM**: filtrar las tools no la protege en absoluto |
| `/agente/log` | `agente.auditar` | la auditoría es de administración |

**Context processor propio**: `agente.bp` construye su `_contexto_base()` localmente
(`escuela_nombre`/`escuela_logo`/`escuela_version` salen de `config.py`). Antes delegaba en
`gestion._contexto_base()`; ya no, porque `nav_entidades`/`carrito_count` son del layout de
recursos y no de este. Los context processors de un blueprint no corren para requests de otro,
así que sin esto el header renderiza vacío.

### Las dos vistas del chat

Comparten markup y JS; lo único que cambia es el contenedor.

| Archivo | Rol |
|---|---|
| `templates/agente/base.html` | Layout propio del área: header con links cruzados a horarios / `/gestion` / `/historia`, nav ASISTENTE + AUDITORÍA. No incluye el widget flotante. |
| `templates/agente/_agente_chat_core.html` | El chat en sí: `#agente-messages` + área de input (texto, 📷 imagen, enviar, link a auditoría). **Único lugar donde se edita el markup del chat.** |
| `templates/agente/_agente_widget.html` | Widget flotante = header propio (↺ reiniciar, ⤢ abrir a pantalla completa, ✕ cerrar) + el core. Lo incluyen `gestion/base.html` e `historia/base.html`. |
| `templates/agente/agente_chat.html` | Pestaña = barra de título + el core, dentro de `agente/base.html`. |
| `templates/agente/agente_log.html` | Auditoría, dentro de `agente/base.html`. |
| `templates/agente/login.html` | Login del área. |
| `static/gestion-agente.js` | Sirve a las dos vistas. Las URLs (`/agente/chat`, `/agente/historial`, `/agente/confirmar`, `/agente/reset`) están hardcodeadas ahí: si cambia el prefijo del blueprint, hay que tocarlas. |

Los IDs del core (`agente-messages`, `agente-input`, `agente-send-btn`, `agente-reset-btn`…)
son únicos y el JS los busca con `getElementById` — por eso **las dos vistas nunca se
renderizan juntas**. Hoy la invariante se cumple sola porque viven en layouts distintos: el
widget solo lo incluyen `gestion/base.html` e `historia/base.html`, y `agente/base.html` (el
de la pestaña) no lo incluye. Si se agrega otra vista del chat, mantener esa invariante.

Progressive enhancement: con JS es fluido, sin JS el chat no funciona pero el resto del
servidor sigue andando. Las respuestas se renderizan como markdown liviano
(`renderMarkdown()` en `gestion-agente.js`: negrita, listas, tablas) — el modelo devuelve
Markdown y sin esto se veía como un bloque de texto con `**`/`|` crudos.

### Diseño para celular

El asistente se usa mayormente desde el teléfono, en el pasillo. Lo que eso impone
(estilos en `gestion.css`, sección "PESTAÑA DEDICADA AL CHAT" y las media queries de
`max-width: 700px`):

- **`body.g-chat-page`** (la clase la pone `base.html` cuando `activo == 'agente'`) arma
  una cadena flex `.g-bg → .g-shell → .g-main → .agente-page` con `min-height: 0`, de modo
  que **scrollea solo el historial y nunca la página**. Si scrolleara el body, al abrir el
  teclado el input se iría abajo del fold y habría que ir a buscarlo.
- **`100dvh`, no `100vh`** — en iOS/Chrome mobile `100vh` incluye la barra del navegador
  que en realidad tapa la pantalla, y el input quedaba cortado abajo.
- **`.agente-input { font-size: 16px }` en mobile es obligatorio.** Con menos, iOS hace
  zoom al enfocar el campo, descuadra el layout y no vuelve solo. No bajar ese valor.
- **Enter envía el mensaje en todas las pantallas**, táctiles incluidas (Shift+Enter hace
  salto de línea; el `<textarea>` lleva `enterkeyhint="send"`). Se descarta el Enter con
  `isComposing` (IME). Antes en táctil Enter insertaba salto y se enviaba solo con el botón,
  para evitar mandar a medio escribir con el teclado virtual; se revirtió a pedido — el
  botón de enviar sigue estando.
- **No se autoenfoca el input en táctil**, para que abrir el chat no abra el teclado.
- **`visualViewport.resize`** vuelve a scrollear al final cuando sube el teclado
  (`window.onresize` no dispara en iOS).
- `env(safe-area-inset-bottom)` en el área de input (requiere el `viewport-fit=cover` que
  agrega el `<meta viewport>` de `base.html`) para no quedar abajo de la barra gestual.
- Objetivos táctiles de 44px, header comprimido y footer oculto.
- **El nav ya no está en la página en celular**: abajo de 900px `static/mobile-nav.js` lo
  mueve —junto con los botones del header— al menú lateral que se abre con ☰, así el chat
  se queda con toda la altura. Ver la sección "Celular" de
  `agent_docs/gestion-conocimiento.md`. La regla vieja que lo hacía scrollear en
  horizontal (`body.g-chat-page .g-nav`) sigue en `gestion.css` como fallback para cuando
  no hay JS y el nav se queda en su lugar.

### Tools

Qué permiso pide cada una está en **`PERMISO_POR_TOOL`** (`agente/tools/esquemas.py`), que es la
**única fuente de verdad**: `TOOLS_ESCRITURA`, la decisión de auditar y el filtrado por acceso se
derivan de ahí. Antes esa clasificación estaba copiada a mano en tres lugares. Una tool nueva sin
entrada en el dict hace fallar el import, a propósito.

**Lectura** — `agente.leer` (no se auditan):
- `buscar_profesor(query)` — resolución difusa de nombre, **sobre el padrón de los
  horarios**: docentes de `clases` **y personal no docente** (ver abajo). Cada candidato lleva
  su `rol` si tiene cargo no docente. Si el nombre también
  coincide con una persona con ficha, devuelve
  `{docentes, personas_con_ficha, aviso}` en vez de la lista pelada (ver "Dos padrones"); si
  coincide con un preceptor, agrega `preceptores` + `aviso_preceptores`
- `buscar_por_rol(rol?)` — personal no docente **por cargo**, no por nombre ("¿qué EMATP hay?").
  Sin `rol` devuelve el padrón entero; con un `rol` que no matchea lo devuelve igual en
  `padron_completo`, ver "Buscar por cargo"
- `preceptores(curso?, division?, preceptor?)` — preceptor ↔ curso, ya digerido: titular y
  contraturno separados, ver "Los preceptores entran por su propia tool"
- `horario_profesor(nombre)` / `horario_curso(curso, division)` / `horario_aula(aula)`
  — horarios agrupados por día. `horario_profesor` cubre también al personal no docente
- `aulas_libres()` — aulas desocupadas ahora, agrupadas por piso
- `buscar_entidad(slug, query)` — búsqueda de recursos/conjuntos/actividades (gestion.db) y
  de hitos/personas (historia.db); el módulo lo resuelve `_modulo(slug)`
  (calidad del match explícita, ver abajo)
- `listar_todos(slug)` — lista completa de nombres + id; **fallback** de `buscar_entidad`
  cuando no hay ningún match `exacto`, ver abajo
- `detalle_entidad(slug, id)` — detalle completo + relaciones (ver "Claves de `relaciones`")
- `listar_prestamos(persona?)` / `detalle_prestamo(id)` — estados de préstamos
- `consultar_historia(tema)` — lore de la escuela y guiños internos, ver abajo
- `leer_foto()` — lee la foto adjuntada en ESTE turno y devuelve lo que dice, en texto. No
  toca la base (por eso está acá) pero **sí gasta la API de visión**, así que el prompt le
  pide llamarla solo cuando necesita los datos, nunca para adjuntar. Ver "Alta desde foto"

**Escritura** — `agente.escribir` (se auditan, guardan snapshot "antes"):
- `crear_entidad(slug, campos)` — alta **en dos pasos con ficha de confirmación**, ver abajo
- `editar_entidad(slug, id, campos)` — update
- `adjuntar_foto(slug, id)` — guarda la foto de ESTE turno en la galería de un registro que ya
  existe. Sin ficha de confirmación (es aditivo); la imagen sale de `contexto_turno`, no de un
  parámetro
- `vincular_entidad` / `desvincular_entidad` — gestionar M2M
- `crear_prestamo(persona, destino?, notas?, items)` — crear préstamo (cantidad topeada
  a stock, recurso por nombre o id con resolución ambigua). Devuelve `ajustes` si lo guardado
  salió distinto de lo pedido, ver "Las tools de préstamo cuentan cómo quedó" abajo
- `finalizar_prestamo(id, items?)` — devolución total (sin `items`) o parcial (con `items`)
- `reabrir_prestamo(id, items?)` — deshace una devolución
- `eliminar_entidad` / `eliminar_prestamo` — **requieren confirmación en turno separado** (el
  system prompt instruye a Claude a no ejecutar en el mismo turno en que se solicita, sino
  responder primero qué va a borrar y esperar confirmación)

### Permisos: no tener la tool, no tenerla prohibida

Un acceso de consulta **no recibe** los esquemas de las diez tools de escritura. La diferencia con
prohibírselas no es cosmética: una tool que no está en la lista el modelo no la anuncia, no la
promete y no alucina haberla usado. Prohibida, en cambio, la intenta, se come el error y a veces
igual contesta "✅ listo".

`tools_permitidas(permisos)` (en `esquemas.py`) es **la única puerta** por la que los esquemas salen
hacia el modelo. Los dos loops de `llm.py` la usan; `TOOLS_SCHEMA` ya no se pasa crudo a ninguna
API. Por eso `PERMISO_POR_TOOL` es un dict aparte y no una clave `'permiso'` dentro de cada esquema:
así `TOOLS_SCHEMA` sigue siendo exactamente lo que las APIs esperan y no hay que acordarse de
limpiarlo antes de mandarlo — Anthropic rechaza con `400` cualquier clave de más, y como el
proveedor por defecto es DeepSeek (que traduce copiando tres claves), ese bug sería **invisible en
desarrollo**.

Tres capas, de afuera hacia adentro:

1. **Filtrado del esquema** — `tools_permitidas()`. El modelo ve 15 tools o 25.
2. **`ejecutar_tool(..., permisos=None)`** — chequea igual. Cubre `/agente/confirmar`, que escribe
   sin pasar por el LLM, y el caso de que el modelo invente un nombre de tool. El default `None` es
   **fail-closed**: un call site nuevo que se olvide de pasar permisos falla cerrado y ruidoso, no
   abierto y en silencio. Un rechazo de escritura **se audita**: si aparece en `/agente/log`, o
   alguien forjó el request o el filtrado tiene un agujero.
3. **El system prompt** — `construir_system_prompt(..., escribe=)`, ver abajo.

Los cuatro call sites de `ejecutar_tool` pasan permisos: los dos del loop Anthropic, el de
`_loop_openai` y el de `rutas.confirmar`.

Las tools genéricas por slug (`crear_entidad`, `eliminar_entidad`, `buscar_entidad`…) cruzan gestión
e historia, así que **no** se pueden mapear a `gestion.editar`/`historia.editar` desde el esquema —
de ahí que el agente tenga permisos propios. Si algún día hace falta el corte fino por área, el
lugar es `ejecutar_tool` mirando `_modulo(slug)`, no el esquema.

### El system prompt se recorta con las tools (`prompt.py`)

`prompt.py` está partido en bloques y `construir_system_prompt(..., escribe=)` arma la lista.
Con `escribe=False` no van el circuito de alta, el bloque de hitos, el de carga desde etiqueta, el
de préstamos (con su padrón de ~1.600 tokens) ni las reglas de borrado; sí va `_SOLO_LECTURA`, que
le dice explícitamente que esas herramientas **no existen** para él y que no escriba "✅". Las
reglas numeradas se renumeran solas: saltar del 1 al 3 le marcaría al modelo que hay reglas que no
está viendo. El prompt de un acceso de consulta queda en ~55% del otro.

`escribe` lo decide `llm.chat_with_tools` mirando **las tools que efectivamente se mandaron**, no
los permisos del usuario: así es imposible que el prompt hable de dar de alta mientras las tools de
alta no viajaron. Con `escribe=True` el resultado es byte a byte el prompt de antes de partirlo.

Esto también apaga un problema conocido: `_escritura_no_ejecutada` (`filtros.py`) marca cualquier
"✅" sin escritura exitosa. Para un acceso de consulta **ninguna** escritura corre nunca, así que
cualquier ✅ decorativo dispararía el banner — por eso el bloque le prohíbe el símbolo de entrada.

### Alta con ficha de confirmación (`crear_entidad`)

Ningún alta se escribe sin que el usuario haya visto antes, campo por campo, lo que va a
quedar guardado. Circuito:

1. El asistente llama a `crear_entidad`. **La primera llamada con un juego de campos no
   escribe nada**: devuelve `{requiere_confirmacion: true, ficha, campos_vacios,
   redactados_por_vos, instruccion}` (y `tipos_en_uso` si el slug es `recursos`, o
   `antes_de_mostrar` si es `hitos` y la ficha salió con agujeros evitables).
2. El asistente muestra la ficha y, debajo, 1 a 3 preguntas cortas por lo que falta
   ("¿de qué medida es?", "¿sabés la marca?"). **No son bloqueantes**: si el usuario no
   contesta, se guarda igual — está en el prompt y en el `instruccion` de la ficha.
3. Si el usuario pide cambios, el asistente vuelve a llamar con los campos corregidos y
   sale otra ficha (con su botón). Se repite hasta el OK.
4. **El OK es un botón, no una respuesta escrita.** `/chat` devuelve además
   `confirmaciones: [{token, etiqueta, nombre}, …]` con las fichas pendientes, y
   `gestion-agente.js` pinta un botón verde por ficha debajo del mensaje
   (`agregarConfirmaciones()`). El botón pega en **`POST /agente/confirmar`** con
   su token: el alta se resuelve ahí, en Python, **sin llamar al modelo** — instantánea,
   gratis, y sin margen para que el modelo escriba otra cosa. Los campos salen de la
   sesión, nunca del request. El resultado se agrega al `agente_historial` como un turno
   más, con el nombre de lo que se guardó, para que el asistente sepa después que eso ya
   está y qué sigue pendiente.
5. Escribir "dale, guardalo" también funciona: el modelo llama **otra vez con exactamente
   los mismos campos** y el hash coincide. Los dos caminos terminan en el mismo lugar.

**Varias altas en un turno** (`_confirmaciones`). "Creá a Pablo y a Ezequiel" son dos
llamadas a `crear_entidad` en la misma respuesta y **dos fichas con dos botones**. Antes se
mandaba una sola confirmación —la última— y las anteriores quedaban vivas en la sesión sin
ningún botón que las guardara: el usuario veía las dos fichas, confirmaba, y se daba de alta
una sola sin que nada avisara. Tres reglas sostienen el caso:
- `contexto_turno['fichas_mostradas']` es un dict con **todas** las del turno, y `/chat`
  arma un botón por cada una.
- Se devuelven **todas las pendientes, no solo las de este turno**: el front borra los
  botones apenas el usuario escribe (`quitarConfirmaciones()`), así que una ficha sin
  confirmar tiene que reaparecer debajo de la respuesta siguiente o se pierde igual.
  Reaparecer no escribe nada: confirmar es siempre un click explícito.
- Si dos fichas pendientes son de la **misma entidad** (el usuario pidió un cambio y el
  modelo la rearmó), se muestra solo la última: son la misma alta, y dos botones con el
  mismo nombre y distinto contenido no hay forma de distinguirlos.

El nombre va **dentro** del botón ("✅ Guardar persona: Pablo Errio"): con dos o tres
seguidos, "Guardar persona" repetido no dice cuál es cuál.

**Cómo se sabe que el usuario aprobó** (`_token_ficha`): cada ficha se identifica por un
SHA-1 de su contenido (`slug` + los campos normalizados). Una llamada escribe solo si su
hash ya se mostró en un turno **anterior**. Consecuencias buscadas:
- Cambiar un solo campo entre la ficha y el alta da otro hash → vuelve a la ficha. No se
  puede guardar algo distinto de lo que el usuario leyó.
- Una ficha mostrada en el turno en curso no habilita nada: el loop ejecuta todas las
  tools antes de devolver una palabra, así que el usuario todavía no la vio.
- El hash se **consume** al escribir; repetir la llamada arranca de nuevo por la ficha en
  vez de duplicar el recurso.

Los hashes viven en `session['agente_fichas']` — un dict `{token: {slug, campos}}`, tope 3
porque la sesión de Flask es una cookie firmada de ~4KB y el historial ya ocupa lo suyo.
El endpoint `/chat` lo carga en `contexto_turno['fichas_previas']` antes de llamar al modelo
y lo vuelve a guardar después; `/confirmar` lee de ahí los campos a escribir.
**Tiene que ser la sesión y no el turno**: los resultados de tools no se persisten en
`agente_historial`, así que en el turno siguiente el modelo no tiene la ficha a la vista —
un token que tuviera que repetir de memoria no le llega, y el alta quedaba trabada en un
bucle de fichas (así falló el primer diseño). `/reset` limpia `agente_fichas`.

Las fichas **no se auditan** en `agente_log`: no tocaron la base, y esa tabla existe para
deshacer cambios reales. Sí se audita el alta efectiva.

`contexto_turno` es el dict que `chat_with_tools()` pasa a todas las tools de un mismo
turno (`ejecutar_tool(tool, input, contexto_turno)`), para lo que hay que decidir mirando
el turno entero y no la llamada aislada.

**Campos que redacta el asistente** (`CAMPOS_REDACTADOS`): `nombre`, `tipo` y `descripcion`
los escribe él a partir de lo que contó el usuario — no se los pide literalmente ("¿qué
descripción le pongo?"). Van marcados en la ficha como `redactados_por_vos` para que el
usuario los lea sabiendo que son propuestos. `tipo` es texto libre, así que la ficha de
`recursos` incluye `tipos_en_uso` (`SELECT DISTINCT tipo`) para que reuse una categoría
existente en vez de inventar un sinónimo nuevo por cada alta.

**`antes_de_mostrar` — la ficha de hito que se revisa sola.** La ficha de `hitos` puede
volver con una lista extra de avisos dirigidos al modelo (`_recordatorio_hito()`), que el
prompt le manda resolver **antes** de escribirle nada al usuario. Existe porque el modelo
armaba el hito "Pablo Errio y Ezequiel Toñanes — Certamen Nacional OMA" con
`protagonistas` **vacío** (los nombres quedaban solo en el título, así que el vínculo con
las personas no lo creaba nadie) y con `nivel` vacío pese a que el usuario acababa de decir
"crítico" — y encima se lo volvía a preguntar. Los avisos son dos:
- Si `protagonistas` está vacío, se cruzan `titulo` + `descripcion` contra la tabla
  `personas` (`_personas_nombradas_en()`, ver abajo) y el aviso **nombra a las que
  encontró**: es un dato concreto, no un "acordate de completar".
- Si ese cruce no encuentra a nadie, el aviso lista **el padrón entero de personas con
  ficha** (hasta `PADRON_EN_AVISO` = 40; más que eso lo manda a `buscar_entidad`). Es para
  que un "nati" o un "el Errio" lo resuelva con los nombres a la vista en vez de irse a
  buscar docentes a los horarios, que es otro padrón.
- Si falta `nivel`, `fecha` o `tipo`, el aviso le recuerda cargarlo si el usuario ya lo dijo
  y preguntar solo si no.

**`_personas_nombradas_en(frase)`** compara con `texto.norm` y exige que estén **todas**
las palabras del nombre (>2 letras), en cualquier orden — matchea "Errio Pablo" pero un
"Pablo" suelto no alcanza: con dos Pablos, vincular al equivocado es peor que no vincular.
**`_personas_parecidas(query)`** es su complemento suelto: acepta coincidencia parcial
("nati" → "Natalia Boo Fiad"). Se puede permitir porque su resultado es un **aviso para que
el modelo pregunte**, no un vínculo que se escriba solo — quien decide a quién se vincula
sigue siendo la regla estricta.

### El padrón de horarios son dos tablas: docentes y no docentes

`escuela.db` guarda a la gente de los horarios en tablas distintas: los que dan clase en
`clases.profesor`, y los EMATP, jefaturas de departamento y demás en `personal_no_docente`
(nombre, rol y una franja de presencia por día, sin materia ni curso). El agente miraba
**solo `clases`**, así que CALEI (EMATP EERR) simplemente no existía para él, y de RODRIGUEZ
VIRGINIA —que da física **y** es EMATP de biología— contaba únicamente las clases.

**`_padron_horarios()`** (en `agente/padrones.py`) es ahora la única fuente del
padrón: devuelve `nombre → rol no docente` (o `None` si solo da clases) fusionando las dos
tablas, igual que ya hacía el autocompletado del SPA. De ahí comen `_buscar_profesor_scored`
(y por lo tanto `buscar_profesor` y la resolución difusa de `horario_profesor`) y
`_personas_conocidas()`.

**El rol viaja con el nombre.** `_buscar_profesor_scored` devuelve `(puntaje, nombre, rol)` y
no `(puntaje, nombre)`: el padrón ya tenía el cargo y tirarlo era el bug — CALEI aparecía como
un candidato más entre los docentes, sin nada que dijera que es la EMATP de renovables. Por eso
`buscar_profesor` marca a cada candidato con su `rol`, y `buscar_entidad('personas', …)` lo pone
en `en_horarios` y lo nombra en el aviso ("CALEI (EMATP EERR)"). Por lo mismo
`_docentes_parecidos` pasó a llamarse **`_gente_horarios_parecida`** y devuelve `[(nombre, rol)]`:
el nombre viejo empujaba a los avisos a decirle "docente" a un EMATP.

**`horario_profesor` devuelve los dos horarios, no uno u otro**, porque los cargos conviven:

| Caso | Qué devuelve |
|---|---|
| Solo da clases | `clases` |
| Solo no docente | `clases: {}` + `rol_no_docente` + `horario_no_docente` + `nota` explicando que no da clases |
| Las dos cosas | `clases` + `rol_no_docente` + `horario_no_docente` + `aviso_no_docente` |

El `aviso_no_docente` existe porque el riesgo es que el modelo lea el segundo horario como
una corrección del primero y muestre uno solo: le dice explícitamente que es **además** de
las clases. Y en el caso "solo no docente" el early return viejo (`"no tiene clases
cargadas"`) llevaba al modelo a darlo por inexistente, que es exactamente el bug: ahora esa
rama responde el horario de presencia.

### Buscar por cargo (`buscar_por_rol`)

Los nombres se encontraban; los **cargos** no existían: buscar "ematp" devolvía `[]`, porque el
padrón difuso compara nombres de persona. `buscar_por_rol(rol?)` filtra `personal_no_docente` por
la columna `rol` con `_coincide_fuerte` —el mismo filtro estricto de los cruces de padrón, que
resuelve tanto "ematp" (substring) como "ematp de biologia" (palabra por palabra)—.

**Las siglas de la escuela no se traducen en el código.** El cargo está escrito como lo cargó la
escuela: `EMATP EERR` es el EMATP de energías renovables, y "energías renovables" no matchea con
"EERR" por letras. Cuando no hay match, la tool devuelve igual **`padron_completo`** con los cuatro
cargos y le pide al modelo reconocer la sigla ahí. Es el mismo camino de dos niveles que
`buscar_entidad` → `listar_todos` (ver `dev-log/DECISIONS.md` 2026-08-08): un diccionario de
abreviaturas habría que mantenerlo cada vez que la escuela crea un cargo, y el padrón entero cuesta
~60 tokens.

### Los preceptores entran por su propia tool (`preceptores`)

Sus nombres siguen **fuera del padrón difuso** —están cargados sin normalizar ("ANGELINA",
"KARINA (M RIOS)", "FALTA") y ensuciarían las sugerencias de `buscar_profesor`—, pero ya no son
invisibles: `preceptores(curso?, division?, preceptor?)` los devuelve **digeridos**, que es la única
forma en que esa tabla sirve. De 595 filas crudas (curso × turno × día) salen 64 fichas, una por
curso:

- **Titular vs contraturno.** El turno en que el curso cursa sale de `config.TURNO_CURSOS`
  (fallback `TURNO_DEFAULT`), el mismo criterio que ya usa `database.obtener_horario_preceptor()`;
  todo lo que no es ese turno es contraturno. Sin esa distinción, un curso devuelve dos nombres y
  no hay forma de saber cuál contestar cuando preguntan "el preceptor" a secas.
- **`contraturno` es una LISTA y "el otro turno" no existe.** Los turnos son tres, así que
  **12 de los 64 cursos tienen dos contraturnos a la vez**, en dos turnos distintos (4° 5, 4° 6,
  4° 7, 5° 4, 5° 5, 5° 6, 6° 5, 6° 7, 6° 8, 7° 1, 7° 2, 7° 3). Los textos que ve el modelo decían
  "el del otro turno", en singular, y eso se cobró un bug real — ver `dev-log/DECISIONS.md`
  2026-08-11 ("Un turno no se deduce…").
- **`turno_del_curso` viene escrito en cada ficha.** Antes el turno en que cursa el curso era sólo
  *inferible* leyendo el `turno` de lo que hubiera caído en `titular` — y en los 7 cursos con
  `titular` vacío ni siquiera eso. Es el campo, no una deducción.
- **`turnos_sin_nadie`** — los turnos que no tienen **ninguna fila** para ese curso (se omite si no
  hay ninguno). La ficha se arma sólo con las filas que existen, así que un turno vacío no aparecía
  por ningún lado y "¿y a la mañana?" era literalmente incontestable con este payload. Distinto de
  `sin_asignar`: eso es la planilla diciendo `FALTA`, esto es no haber fila. La lista de turnos
  válidos es `database.TURNOS`, la misma de la que salen los bloques del Sheet.
- **`dias` solo cuando no cubre la semana entera** (hay cursos donde dos preceptores se reparten
  los días); si cubre los cinco, el detalle es ruido.
- **`titular` vacío es un caso real** (7 de 64 cursos): la planilla tiene gente en el contraturno y
  a nadie en el turno del curso. La `instruccion` se lo dice explícitamente al modelo, porque las
  dos salidas fáciles son erróneas: decir que el curso no tiene preceptor, o pasar el de
  contraturno por titular. Son datos desfasados, no un caso de diseño: la lista de los 7 y qué
  hacer con ellos está en `dev-log/tasks/TODO.md` #23.
- **`sin_asignar: true` en vez del nombre** cuando la planilla dice `FALTA` — si no, el agente le
  contesta a alguien que su preceptora se llama FALTA.
- **Las grafías del mismo nombre se agrupan** (`_alias_preceptores`): la planilla tiene "ROMERO
  VANESA" **y** "VANESA ROMERO". Sin agrupar, preguntar por ella empataba entre dos opciones
  idénticas y la que se eligiera mostraba la mitad de sus cursos. Se agrupa por **conjunto de
  palabras**, no por parecido: "DANIELA TRAJO" y "DANIELA TREJO" son un typo y quedan separadas a
  propósito, porque fusionar a dos personas distintas es el error caro.

Tres modos: un curso (`curso` + `division`, o `curso` solo para todo el año), un preceptor (difuso,
con `sugerencias` si empata — igual protocolo que `_horario_profesor_fmt`), o **nada**, que devuelve
la planilla entera (~4.000 tokens; la descripción del esquema pide usarlo solo si la pregunta es
realmente sobre todos). Los campos de turno le sumaron ~29% a ese modo — 55 de los 64 cursos tienen
algún turno vacío, así que `turnos_sin_nadie` aparece en casi todos. Se paga igual: una ficha que
cambia de forma según cómo se llamó la tool es peor que una ficha grande, y el modo caro ya está
desaconsejado en el esquema. En el modo normal (un curso) la ficha entera son ~1,6 KB.

**La división pasa por `database._extraer_num_curso`, igual que el curso.** Las divisiones de 4°–7°
son números y en castellano se escriben "6ta"/"3ra" — tal cual las tipea el usuario. Sin eso "6ta"
quedaba `"6TA"`, no matcheaba y la tool devolvía `error` con los 64 cursos. La función devuelve el
string tal cual si no empieza con dígito, así que `"A"`/`"B"` no se tocan.

**Las repreguntas de turno obligan a volver a llamar la tool.** Está en el system prompt, no en la
`instruccion`, y por una razón concreta: los resultados de las tools **no quedan en el historial**
(`rutas.py`, ver "La conversación"), así que en el turno siguiente la `instruccion` ya no está en
contexto — el prompt sí. "¿Y a la mañana?" después de una respuesta de preceptores parece
contestable de memoria y no lo es: el turno de cada persona no quedó escrito en ningún lado.

Y para que la gente se **encuentre** sin entrar al padrón difuso, `buscar_profesor` y
`horario_profesor` cruzan contra los preceptores y devuelven `preceptores` + un aviso que apunta a
esta tool. Los preceptores siguen sin tener horario de clases: eso no se responde con
`horario_profesor`.

### Dos padrones de personas, y el cruce en las dos direcciones

Los docentes salen de **`escuela.db`** (los horarios) y las fichas de personas de
**`gestion.db`**. Son padrones que **no se superponen**: un alumno que ganó una olimpiada, un
egresado o un ex director tienen ficha y no dan clases; una profesora que nadie cargó todavía
da clases y no tiene ficha. El modelo los mezclaba, y el prompt empujaba para el lado de los
horarios — la sección de préstamos le **inyecta** la lista de PERSONAS CONOCIDAS
(`_personas_conocidas()`, docentes + no docentes) y nunca le mostraba las fichas. Ante "nati
fue quien lo logró" llamaba a `buscar_profesor`, veía tres docentes llamadas Natalia y
ofrecía esas tres, mientras "Natalia Boo Fiad" estaba cargada con ficha.

**Buscar una persona mira siempre los dos padrones**, entre por donde entre:

| Se llama | Busca en | Cruza y agrega |
|---|---|---|
| `buscar_profesor(query)` | horarios | `personas_con_ficha` + `aviso` (la respuesta pasa de lista a dict) |
| `buscar_entidad('personas', query)` | fichas | `en_horarios` + `aviso_horarios` |

Las dos solo agregan la clave **cuando hay coincidencia real**, así que los turnos normales
—horarios por un lado, inventario por el otro— no cambian ni suman ruido. Y los dos avisos
son distintos según el caso: si `personas` no encontró nada pero los horarios sí, el aviso le
prohíbe explícitamente decir "no la tengo" y le ofrece dos salidas (resolver el horario con
ese nombre, o proponer crearle la ficha).

Va en el resultado de las tools y no (solo) en el system prompt porque para cuando el modelo
llamó **ya eligió**: lo único que lo corrige a tiempo es lo que la herramienta le conteste.

**`_coincide_fuerte(q_norm, nombre)`** es el filtro de todos los cruces laterales —los dos de
persona, el de preceptores y el de cargos de `buscar_por_rol`—, y es más estricto que
las búsquedas normales: substring, o similitud **palabra por palabra** ≥ `UMBRAL_SIMILITUD`
(0.68). No usa el 0.6 de `_buscar_profesor_scored`, que ofrece candidatos a propósito: con
0.6 el cruce de "nati" traía PETRATE MATIAS (0.60 contra "matias") y el de "calei" traía
PRIETO VALERIA. Tampoco alcanza con substring solo — los apodos del castellano no son
prefijos: "nati" **no** es substring de "natalia" (0.73 de similitud, sí pasa el umbral), y
ése era justo el caso a resolver.

**`/confirmar` crea el vínculo persona↔hito solo** (`_enlazar_protagonistas()`): al guardar
un hito cruza su `protagonistas` contra `personas` con la misma función y escribe
`persona_hitos` para cada match, sumándole al mensaje " Lo vinculé con la ficha de X.".
**Tiene que ser código y no una instrucción al modelo**: el botón de confirmar no pasa por
el LLM, así que en el momento en que el hito se escribe el agente no tiene ningún turno para
llamar a `vincular_entidad`, y el vínculo no lo creaba nadie. Solo vincula personas ya
cargadas; nunca crea una ficha de persona nueva.

### La hora en cada mensaje

El agente sabe qué hora es por **dos vías, y las dos hacen falta**:

1. **En el system prompt** (`prompt.py`, bloque `FECHA Y HORA ACTUAL`). Se arma de nuevo en cada
   turno: `llm.chat_with_tools()` pide `config.ahora()` al empezar, no al arrancar el server.
2. **Pegado a cada mensaje del usuario** (`rutas._sello_hora()`): `chat()` le agrega
   `[Hora de este mensaje: Lunes 10/08/2026 18:40]` al texto antes de mandarlo.

El sello existe porque el system prompt es largo y queda lejos: con la conversación crecida, el
modelo contestaba "ahora" con la hora del primer mensaje del chat. Pegada al final del mensaje, la
hora es lo último que leyó, y como el historial se persiste con el sello, en un turno de
seguimiento se ve cuánto pasó entre un mensaje y otro. La regla del prompt dice explícitamente que
el sello del **último** mensaje manda sobre cualquier otra hora de la conversación y que no se
repite ni se comenta (lo pone el sistema, no el usuario). `_texto_visible()` lo saca antes de
repintar el chat, igual que el `(refiriéndote a: X)`.

Las dos vías salen de `config.ahora()`, no de `datetime.now()`: en Render el server corre en UTC y
la hora venía 3 horas adelantada. Ver "El reloj" en `agent_docs/crud-motor.md`.

### Los id no se le muestran al usuario

Los id son plumbing: enganchan filas entre tablas y le sirven al modelo para llamar a las
tools, pero al usuario no le dicen nada — ni la web de `/gestion` los muestra, solo los usa
en las URLs. Aun así el modelo los repetía en casi toda respuesta de lectura (medido: 6 de
9 respuestas — "Multímetro (ID 4)", "préstamo #2", una columna `ID` en la tabla de préstamos).

Se ataca por dos lados:
- **Regla en el system prompt** ("LOS ID NO SE MUESTRAN"), con ejemplos de mal/bien y la
  indicación de desambiguar por lo que distingue de verdad (ubicación, potencia, marca) en
  vez de por el id.
- **`_ocultar_ids()`, filtro de salida en `chat()`**, que corre **antes de persistir** la
  respuesta — así el historial repintado tampoco los trae. Saca paréntesis que son solo un
  id, ids inline, `#N`, y la columna `ID` de las tablas markdown (`_quitar_columna_id()`,
  que borra la misma posición en encabezado, separador y filas — con regex plana no alcanza).
  Después limpia los restos: paréntesis vacíos, comas al abrir paréntesis, guiones colgando.

Es filtro de código y no solo prompt por lo mismo de siempre; acá el costo de que el modelo
se olvide es bajo (ruido en pantalla), pero sale gratis hacerlo determinístico. Medición
después del cambio: **0 de 9**. Los mensajes que arma el servidor tampoco los incluyen
(`/confirmar` responde "✅ Guardado: **nombre**." sin id).

### Salida interpretada

Las tools de lectura retornan datos ya procesados, no filas SQL crudas: horarios agrupados
por día, aulas libres agrupadas por piso, búsquedas con solo campos relevantes (omitiendo
vacíos), pendientes de préstamos ya calculados. Reduce tokens de API y errores de interpretación.

### Calidad del match en `buscar_entidad`

La búsqueda es la misma de la web (`crud.buscar_entidad` → `texto.puntaje_busqueda`), que
ordena por puntaje pero **lo descarta al devolver**. Para el agente eso era un problema real:
buscar "taladro" (que no existe en el inventario) devolvía *Caladora*, *Sierra de calar
manual* y *Cinta de aisladora* — todos difusos de ~0.6 — y Claude los recibía con el mismo
peso que un match literal, así que ofrecía el primero como si fuera el pedido. Por eso
`_buscar_entidad_fmt` (en `agente/tools/entidades.py`, capa de presentación: no toca la búsqueda compartida)
agrega por resultado:

- **`match`**: `exacto` (substring en el nombre) · `descripcion` (substring en la descripción,
  no en el nombre) · `aproximado` (solo similitud difusa).
- **`similitud`** (0–1) cuando es `aproximado`, recalculada con `_puntaje_busqueda`.
- **`descripcion`** cuando `match == 'descripcion'`: sin esto el nombre llega sin relación
  visible con lo buscado (buscar "cable" trae *Faniot arduino*, cuya descripción dice
  "Falta un cable usb a mini usb"). Se manda entera hasta `MAX_DESC_BUSQUEDA` (160) porque
  las descripciones del inventario son cortas (máx ~180 chars).

Y a nivel respuesta: `total` real, tope de `LIMITE_BUSQUEDA` (10) con campo `truncado`
(la difusa no acota: con query vacía devolvía la tabla entera), y un `aviso` cuando **todos**
los resultados son `aproximado` que le dice explícitamente que probablemente no exista y no
ofrezca el más parecido como correcto. La descripción de la tool documenta los tres valores
de `match`; sin eso el campo llega y el modelo lo ignora.

Slug inválido devuelve `{'error': ...}` con los válidos, no una lista vacía (que el agente
leía como "no hay nada cargado").

### Búsqueda en dos niveles: `buscar_entidad` → `listar_todos`

`_puntaje_busqueda` compara **letras, no significados**: buscar "tester" no encuentra el
*Multímetro*, y "taladro" no encuentra la *Agujereadora de banco*, que es exactamente eso.
Por eso "no encontré" **no** equivale a "no existe", y el agente no debe concluir lo segundo
desde lo primero. El orden es:

1. `buscar_entidad(slug, query)` — barata y precisa.
2. Si ningún resultado trae `match: "exacto"` → `listar_todos(slug)`, que devuelve **todos**
   los nombres + id. El modelo reconoce ahí el sinónimo, la marca o la jerga del taller.
3. Recién entonces afirmar que no está cargado — habiéndolo verificado, no deducido.

`_listar_todos_fmt` devuelve `{slug, total, items:[{id,nombre}], instruccion}` y, si hay filas
con el nombre vacío, las cuenta aparte en `sin_nombre` (esconderlas sin avisar haría falsa la
afirmación "estos son todos"). Tope `LIMITE_LISTADO_COMPLETO` (400): arriba de eso devuelve
`error` pidiendo afinar la búsqueda, en vez de reventar el contexto en silencio.

**Costo medido** (91 recursos): el listado completo son ~1.190 tokens. El piso que se
re-procesa en **cada** round-trip de tool es ~8.050 (esquemas de las 20 tools ~6.420 + lista
de personas ~1.625, sin contar system prompt ni historial), así que un intento extra de
búsqueda cuesta ~6,7x lo que cuesta mandar el inventario entero. Por eso se eligió esto sobre
un diccionario de sinónimos o un tier intermedio de reintentos — ver `dev-log/DECISIONS.md`
2026-08-08, que además documenta cuándo esta decisión se da vuelta (si el inventario supera
el tope).

**El guardrail vive en tres lugares que se refuerzan** — es de prompt, no de código, y con
DeepSeek (proveedor por defecto) es más frágil que con Claude:
- el `aviso` de `buscar_entidad` nombra la tool cuando la búsqueda falla;
- la `instruccion` del resultado dice "estos son TODOS; si ninguno es, decilo — no ofrezcas
  el más parecido como si fuera el correcto";
- la regla 3 del system prompt fija el orden de los tres pasos.

### Historia de la escuela (`consultar_historia`)

Cuarta área del agente: lore institucional (fundación, nombre de la escuela, edificio) y
guiños internos sobre gente de la casa. **Cuando se piden historias, no es el agente quien
responde: es Emilio Mitre, el fantasma que habita la escuela desde su construcción.** Recorre
todos los pasillos, ve y escucha todo. Por eso cuenta en primera persona con autoridad omnipotente.
Las historias son literales del archivo — nunca improvisadas.

**Estructura de archivos**:
- **`historia_indice.json`** — índice comprimido: id, título, claves, tipo, resumen, tono, estilo.
  Se cachea por mtime (pequeño, ~20KB). Recarga sola cuando cambia sin reiniciar.
- **`historias/`** — directorio con un archivo JSON por historia (ej: `guino_canamas.json`).
  Contiene: id, título, claves, tipo, resumen, tono, estilo, **texto completo**.
  Se cargan bajo demanda (lazy-loading), no se cachean.

Estructura por historia:
```json
{
  "id": "guino_canamas",
  "titulo": "Miriam Cañamas: el multímetro fallado",
  "claves": ["cañamas", "miriam", "multimetro"],
  "tipo": "guiño",
  "fecha": "2008",
  "resumen": "La anécdota de tercero que culpó al instrumento",
  "tono": "nervioso",
  "estilo": "primera persona, cómplice, como confesando",
  "texto": "Miriam Cañamas tiene fama de escuchar todo..."
}
```

**Campo `fecha`** (crítico): año o período aproximado. Determina el tono nostálgico de la historia.
Una historia de 2005 + tono reflexivo = profundamente nostálgica. Sin fecha, es solo una anécdota.

**Búsqueda** (`_historia_fmt`): sin tema devuelve índice completo. Con tema:
- Busca en `claves`, `tono`, `estilo`, `titulo`, `resumen` (substring + difuso con umbral 0.72)
- Devuelve tres modos:
  * **directo**: 1 coincidencia exacta → devuelve historia completa + `instruccion_tono` (instrucciones para Emilio)
  * **listar**: múltiples opciones → devuelve índice sin textos, usuario elige cuál historia quiere escuchar
  * **no_encontrado**: nada coincide → instrucción de no inventar

**Personalidad de Emilio**: en modo `directo`, la `instruccion_tono` le recordar a Claude que es
Emilio Mitre, el fantasma omnipotente, contando desde su perspectiva de siglos. Cada historia
especifica un `tono` (emociones: nervioso, reflexivo, misterioso, conmocionado, nostálgico) y
un `estilo` (narrativa: primera persona, íntimo, cómplice, como confesando, etc.). El modelo
respeta estas instrucciones y cuenta la historia con la voz de Emilio, no como un asistente
que relata.

La instrucción la arma **`_instruccion_tono(tono, estilo)`**, una sola fuente para las dos rutas
de `consultar_historia` (por `tema` y por `id`). Es una función y no texto inline porque estuvo
duplicada: la ruta por `id` — la que se usa cuando el usuario elige de un `listar`, o sea el
camino más común — tenía una versión de dos líneas sin la regla anti-acotaciones.

### La voz del personaje (`QUIEN_ES_EMILIO`, `EXCUSA_SIN_HISTORIA`)

Con solo pedirle primera persona, las historias salían correctas pero **anónimas**: se presentaba,
explicaba que era un fantasma, aclaraba que la escuela lleva su nombre y pedía permiso para
empezar. Leídas seguidas parecían el conserje contando una anécdota, no el dueño del edificio.
Dos constantes arreglan eso, y van **solo en el circuito de historias** (`_instruccion_tono` + la
sección HISTORIA DE LA CASA del system prompt), no en las respuestas operativas:

- **`QUIEN_ES_EMILIO`** — tres cosas juntas. *Con quién habla*: el otro ya sabe quién es, así que
  no se presenta ni se explica; entra directo, con la familiaridad del que es dueño de la casa y
  sabe que el otro está de visita. *Su orgullo*: sabe todo lo que pasa en la escuela y le encanta
  que se note, cuenta como el único que estuvo ahí y deja caer que nadie más lo vio. La soberbia
  es parte del personaje; maltratar al que pregunta, no — le halaga que le vengan a preguntar,
  porque confirma que es el que sabe. *Y que no es una persona*, sin decirlo nunca: con solo
  pedirle primera persona hablaba como un empleado con cuerpo ("yo estaba ahí parado"), que fue
  el segundo problema reportado. Tres señales lo delatan y el prompt las nombra — no tiene cuerpo
  ni lugar (no entró ni se acercó: **estaba**, porque está siempre y en todas partes a la vez),
  nada lo tapa (escuchó lo que se dijo en voz baja, con la puerta cerrada, y no aclara cómo), y
  el tiempo no le pesa (veinte años son "el otro día"; los que estaban ya no están y él sigue).

  **De acá sale, además, el fundamento de la regla anti-acotaciones**: no describe lo que hace
  con el cuerpo porque **no tiene cuerpo**. Las dos reglas dejaron de ser independientes, y en
  `COMO_CUENTA_EMILIO` está escrito así — es una consecuencia del personaje, no una prohibición
  de estilo caída del cielo.
- **`EXCUSA_SIN_HISTORIA`** — qué hace cuando no tiene la historia: no admite un agujero en su
  memoria de un siglo, zafa con una excusa obvia y absurda dicha con naturalidad ("justo esa
  semana estaba en el subsuelo peleándome con la caldera"). Se interpola en las **tres** `nota`
  de `no_encontrado` (índice vacío, sin coincidencias por tema, id inexistente). El chiste se
  apoya en el punto anterior: la excusa **se contradice con el personaje** —está en todos lados
  al mismo tiempo, así que "estaba ocupado en otra parte" no se lo cree nadie— y la dice igual,
  sin inmutarse. Ahí está la gracia, y por eso el prompt le pide que no se haga cargo del chiste.

**Dónde termina el personaje** — es el límite que sostiene todo lo demás, y está escrito en el
system prompt además de acá:

- La excusa **reemplaza el "no sé", nunca los hechos**. Es un chiste de personaje, no un permiso
  para inventar: la respuesta tiene que seguir dejando clarísimo que esa historia no existe. Sin
  esta línea, la excusa absurda es exactamente el borde por el que se cuela la fabricación de
  anécdotas que el resto del prompt trabaja para evitar.
- Y vale **solo para historias y lore**. Un horario, un stock, un préstamo o una persona que no
  están cargados se contestan derecho: "no hay datos de eso". Al que busca una herramienta o va
  corriendo a dar clase, un chiste le cuesta una vuelta al pañol al vacío. Ahí sigue valiendo el
  agente bifásico de siempre (DECISIONS 2026-08-08): fantasma orgulloso en las historias,
  herramienta neutra en lo operativo.

### Emilio cuenta, no actúa (`_quitar_acotaciones`)

Decirle al modelo que hable en primera persona como un fantasma le activa el registro de
roleplay, y empieza a **actuar** el personaje: `*se acomoda los anteojos*`, `—mirando el
patio—`, `EMILIO:` antes de hablar. Mismo esquema de defensa que los id — prompt **y** filtro
de salida:

- **`COMO_CUENTA_EMILIO`** (constante en `agente/lore.py`): se interpola en el **system prompt** y en
  cada `instruccion_tono`. Va en el system prompt porque **los resultados de tools no se
  persisten en el historial**: en un turno de seguimiento ("¿y después qué pasó?") la
  `instruccion_tono` ya no está en contexto y lo único que el modelo tiene a la vista es su
  propia respuesta actuada del turno anterior, que imita.

  Está redactada como **instructivo de qué hacer**, no como lista de prohibiciones: "escribís
  únicamente las palabras que Emilio dice en voz alta", cómo transmitir el clima con lo dicho
  (si es un secreto, "esto no lo repitas"; si da para resignarse, "y bueno, así es acá") y un
  **test** que el modelo aplica solo — *¿esta oración se puede pronunciar?*. La primera versión
  era negativa ("no escribas acotaciones de gestos, no marcas de guion") y funcionó peor por dos
  razones: le dejaba al modelo deducir la forma correcta, y para nombrar lo prohibido había que
  escribir el ejemplo malo en el prompt, que es justo lo que después copiaba. Hoy **no hay ni
  una acotación de muestra** en el prompt.
- **`_quitar_acotaciones()`**: filtro de salida en `chat()`, junto a `_ocultar_ids()` y también
  **antes de persistir**, así el turno siguiente no arranca con el ejemplo malo en el historial.
  Barre cursivas de una sola marca (`*...*`, no `**bold**`), corchetes, tramos entre rayas
  (`—...—`) y la etiqueta `EMILIO:` / `**Emilio:**` al principio de línea.
- **`_quitar_oraciones_gesto()` / `_es_oracion_gesto()`**: las acotaciones **sin marcar**.
  Prohibirle las marcas no le quita la costumbre de actuar — encuentra la vuelta y escribe el
  mismo gesto como prosa suelta ("Baja la voz, se acerca un poco." / "Se encoge de hombros."),
  que fue exactamente lo que pasó al probar la primera versión. La señal que las delata es
  gramatical: Emilio habla en primera persona y las historias están en pasado, así que una
  oración corta, entera en tercera del presente y sin sujeto solo puede ser él describiéndose
  desde afuera. Se borra la oración **solo si todas sus cláusulas son gesto**: "Baja la voz, se
  acerca un poco." se va entera, pero "Sonríe y sigue la clase como si nada" se queda porque la
  segunda mitad dice algo. Los núcleos de gesto están **listados a mano** (`_GESTO_NUCLEO`) en
  vez de inferidos por conjugación: la lista se queda corta ante un gesto nuevo, pero no se come
  una oración real, que es el error caro.
- **`_parece_gesto()`** decide qué se borra, y es deliberadamente conservador: nunca toca un
  tramo con números (los datos técnicos y las fechas los tienen: `*Panel solar 100 W*` es
  contenido, y `—fundada en 1957—` es un paréntesis legítimo), y de ahí pide o una frase con
  señal de gesto (reflexivo inicial, gerundio, palabra de la lista) o una sola palabra que ya
  sea un gesto (`*suspira*`, `*riéndose*`). Se preferió que se escape una acotación rara antes
  que borrar contenido real. Los verbos que existen en imperativo quedaron **fuera** de la
  lista de una palabra: `*mirá*` es una cursiva válida.

También se sacó el vocabulario de teatro de la doc de historias: el `estilo` se le pasa
**literal** al modelo, así que `"diálogos"` o `"dramático"` en ese campo son un pedido de
guion. Ver `HISTORIAS_PROCEDIMIENTO.md`.

**Gatillo de personalidad**: Emilio solo cobra vida cuando se consultan historias. Para tareas
prácticas (horarios, inventario, préstamos), sigue siendo una herramienta eficiente sin personaje.
Así alguien que consulta un horario en medio de la jornada obtiene info rápida, sin interrupciones
de lore.

**Por qué textos literales**: dejarlo improvisar anécdotas dispara la conducta que el prompt desactiva
(fabricación de historias), y el modelo no sabe que el permiso termina en anécdotas. Por eso textos
vienen del JSON siempre, jamás generados. `no_encontrado` devuelve instrucción explícita de no inventar,
no lista vacía que invita a rellenar.

**Costo**: índice cachea siempre (~250 tokens por turno). Historias completas se pagan solo cuando se
leen (varían, típicamente 200–500 tokens por historia).

### Alta desde foto (datasheets, etiquetas, chapas de características)

Caso de uso central del asistente en el taller: sacan la foto de la etiqueta de un panel
solar, escriben "tenemos 5" y el recurso queda cargado sin tipear especificaciones.

**Recorrido de la foto**:
1. `gestion-agente.js` la lee con `FileReader`, la **achica en un canvas** a 1568 px de lado
   largo / JPEG calidad 0.85 y la deja en `imagenSeleccionada` como data URL. Sin ese paso
   una foto de celular (3–8 MB, ~11 MB en base64) no entra en el límite de la API de visión
   y tarda una eternidad por el wifi de la escuela. 1568 px es lo que el modelo llega a
   aprovechar y alcanza para leer la letra chica de un datasheet. Si el navegador no puede
   decodificar el archivo (HEIC de iPhone), se manda tal cual en vez de perder la foto.
2. `POST /chat` con `{mensaje, imagen}`. **La foto sola es un mensaje válido**: si no
   escribieron nada, el front igual envía y el backend pone "Te mando esta foto." como texto.
3. `chat()` **no le manda la foto al agente ni la lee**: la deja en
   `contexto_turno['foto_turno']` y le agrega al mensaje del usuario una nota diciendo que hay
   una foto disponible. El agente nunca ve un píxel.
4. **El agente decide qué hacer con ella**, y ahí se abren los dos caminos (ver abajo): leerla
   con `leer_foto` si necesita los datos, o guardarla con `adjuntar_foto` si va a una ficha que
   ya existe. Si no está claro, pregunta.
5. En el camino de alta, el modelo arma la ficha con `crear_entidad` → botón de confirmar, y la
   foto queda en `agente_fotos_pendientes` atada al **token de la ficha**. Al confirmar,
   `_adjuntar_foto_pendiente()` la pasa a la galería del registro nuevo con
   `crud.agregar_foto()` — el mismo camino que usa la subida manual desde el detalle.

#### Los dos caminos de una foto

| El usuario quiere… | Tool | ¿Cuesta visión? |
|---|---|---|
| Guardarla en una ficha que ya existe ("guardá esta foto en el taladro") | `adjuntar_foto(slug, id)` | **No** |
| Cargar o actualizar el inventario con lo que dice la etiqueta | `leer_foto()` → `crear_entidad` / `editar_entidad` | Sí (~US$0,0004) |
| No se entiende | — | No: el prompt le pide **preguntar**, no leer por las dudas |

**Leer es una tool, no un paso automático.** La primera versión leía toda foto al entrar a
`chat()`, y eso pagaba una llamada de visión también cuando lo único que querían era adjuntar —
que es el caso más común y el que menos la necesita: para guardar una imagen no hace falta
saber qué dice. El costo de la vuelta extra del loop es despreciable al lado de eso, porque
DeepSeek cachea el prefijo (system prompt + tools): los cache hits salen US$0,003625/M contra
US$0,435/M de un miss.

Las dos tools sacan la imagen de `contexto_turno['foto_turno']`, nunca de un parámetro: el
modelo no ve la foto, así que pedirle el base64 sería pedirle que lo invente. Si en el turno no
vino ninguna, las dos devuelven un error que se lo explica en vez de fallar en silencio.

`adjuntar_foto` **corre directo, sin ficha de confirmación**: es aditivo (no pisa ni borra
nada) y el listón lo marca `editar_entidad`, que sobrescribe campos y tampoco la pide. Queda
auditada en `agente_log`. `leer_foto` no se audita: no toca la base — lo que gasta es la API de
visión, no el inventario.

> **Ojo**: no hay forma de borrar una foto de una galería desde la app (`subir_foto` agrega,
> nada saca). Por eso el prompt y la descripción de `adjuntar_foto` insisten en preguntar
> cuando el destino es ambiguo: una foto en el recurso equivocado se saca editando la base.

**Por qué la foto se guarda por token y no por turno**: la confirmación puede llegar mucho
después, incluso desde otra página (el historial se repinta y el botón sigue ahí). El token
de `_token_ficha()` es lo único que atraviesa esa distancia. Va en tabla propia y no dentro
del JSON de `fichas` porque esa columna se reescribe entera en cada turno: con hasta
`FICHAS_MAX` fotos en base64 adentro, cada mensaje del chat arrastraría varios MB de
escritura. Las filas sin confirmar se barren a los `CONVERSACION_DIAS` días, y `/reset` las
borra junto con la conversación.

La imagen **sigue sin persistirse en el historial** (`_sin_imagenes`) — lo que queda ahí es
la lectura en texto, que sí sirve en los turnos siguientes ("sí, tenemos 3"). Al repintar el
chat, `_texto_visible()` reemplaza ese bloque por "📷 (foto)": es una pista para el modelo,
no algo que el usuario haya tipeado.

**Reglas en el system prompt** (sección "FOTOS DE DATASHEETS…"): el agente trabaja **solo con
lo que dice la lectura**, nunca completando con lo que sabe de esa marca/modelo; la cantidad
no sale nunca de la foto sino de lo que dice el usuario (si no la dijo, se pregunta antes de
la ficha, junto con la ubicación); cinco unidades iguales son **un** recurso con `cantidad` 5,
no cinco altas; antes de la ficha se busca por marca/modelo y por nombre genérico, porque con
una foto lo más común es que el recurso ya exista y corresponda sumar stock con
`editar_entidad`; las especificaciones van en `descripcion`, no amontonadas en el `nombre`.
Si la lectura describe algo que no es una etiqueta (una máquina, un tablero, una planilla en
papel), se cuenta qué se ve y se pregunta qué hacer, no se da de alta sola.

#### El lector de imágenes (`_get_vision_config`, `_leer_imagen`)

Config **aparte de la del chat**: `AGENTE_VISION_API_KEY` (fallback `GEMINI_API_KEY`),
`AGENTE_VISION_MODEL` (default `gemini-2.5-flash-lite`), `AGENTE_VISION_API_BASE` (default
el endpoint OpenAI-compatible de Google). Sin API key, `_get_vision_config()` devuelve `None`
= no hay lector.

Es una llamada suelta, **sin tools**, con `PROMPT_LECTOR_IMAGEN` (solo lectura: transcribir lo
que se lee, no completar con conocimiento del producto, avisar si no se lee) y `max_tokens`
500. Todo lo que viene *después* de leer —cantidad, buscar duplicados, circuito de ficha—
sigue en el system prompt del agente, que es quien tiene las tools. **Solo se dispara desde la
tool `leer_foto`**: nunca automáticamente al llegar una foto.

**Por qué separado y no `AGENTE_PROVIDER=anthropic`**: el system prompt más `TOOLS_SCHEMA` son
~15.000 tokens que viajan en **cada** turno del agente; la llamada del lector son ~2.000. Con
el lector aparte una foto cuesta ~7× menos, el chat sigue en DeepSeek (más barato y mejor en
el tool-calling de 20 tools que un modelo chico con visión), y no hay que elegir entre
"proveedor bueno para chatear" y "proveedor que ve".

Ante cualquier falla —cuota, 429 del tier gratuito, red— `_leer_imagen()` devuelve `None` y
`leer_foto` le devuelve al modelo un error que le pide avisarle al usuario y **no inventar** lo
que decía la etiqueta. No corta el turno: es una tool que falló, no el chat.

`_leer_imagen()` devuelve `None` **también cuando no hay lector configurado**, que para el
usuario es otra cosa —una se arregla cargando una API key, la otra se arregla esperando—, así
que `_leer_foto_fmt()` chequea `_get_vision_config()` *antes* de llamarlo y devuelve un error
propio que dice justamente eso y ofrece adjuntar. Ver "Sin lector, adjuntar sigue funcionando"
abajo.

**Las dos ramas de `chat()`**:
1. El chat ve imágenes (`_get_config()['vision']`: Anthropic siempre, el resto con
   `AGENTE_VISION=1`) **y no hay lector aparte** → el bloque `image` viaja al agente y
   `_mensajes_openai(..., vision=True)` lo traduce a `image_url` si el proveedor es
   OpenAI-compatible. Es el único caso donde el que razona mira la foto, así que acá
   `leer_foto` no hace falta.
2. En cualquier otro caso —haya lector o no— la foto queda en `contexto_turno['foto_turno']` y
   el mensaje del usuario lleva una nota diciendo que está disponible. **No se lee acá**:
   decide el modelo. Anda con cualquier `AGENTE_PROVIDER`.

**Sin lector, adjuntar sigue funcionando.** Antes había una tercera rama: sin lector y sin
chat con visión, `chat()` cortaba antes de llamar al modelo con un `AVISO_SIN_VISION` fijo. La
intención era buena —evitar que contestara sobre una imagen que nunca vio, inventando lo que
"leyó" en la etiqueta— pero asumía que **toda** foto se manda para ser leída, y se comía el
caso más común: `adjuntar_foto` no necesita visión, y con el corte quedaba inalcanzable. Con
el default del proyecto (`AGENTE_PROVIDER=deepseek`, sin `AGENTE_VISION_API_KEY`) eso era
*toda* foto: mandar una imagen no servía absolutamente para nada.

Ahora el turno corre siempre y **la distinción la hace el modelo**, que es quien entiende qué
le están pidiendo:
- *"guardá esta foto en el taladro"* → `buscar_entidad` + `adjuntar_foto`. Sin leer nada, sin
  API key extra.
- *"¿qué dice esta etiqueta?"* → llama a `leer_foto`, que detecta que `_get_vision_config()`
  es `None` y le devuelve un error explicando que no hay lector configurado y que ofrezca las
  dos salidas (que le dicten los datos, o que le digan a qué ficha guardarla). El aviso lo da
  el modelo con contexto, en vez de un texto fijo que corta la conversación.

Por eso `leer_foto` **sigue expuesta en `TOOLS_SCHEMA` aunque no haya lector**: es lo que le
permite al modelo detectar la intención "analizar" y contarla. Cuesta una vuelta del loop, no
una llamada de visión.

### Auditoría (agente_log)

Tabla nueva en `gestion.db`:
```sql
agente_log (
  id, fecha, tool, entrada (JSON de parámetros),
  antes (JSON: snapshot de fila + relaciones M2M, NULL en alta, obligatorio en editar/eliminar),
  resultado (JSON), ok
)
```
Se inserta una fila **por cada tool de escritura ejecutada** (no por lecturas, para no llenar
la tabla de ruido). El snapshot "antes" permite restaurar a mano si el agente se equivocó en
una devolución de préstamo o un borrado.

### Otras tablas del agente en `gestion.db`

```sql
agente_conversaciones (sid PK, actualizado, historial JSON, entidad_actual, fichas JSON)
agente_fotos_pendientes (token PK, sid, b64, tipo, fecha)
```

`agente_conversaciones`: una fila por navegador. La conversación vive acá y no en la cookie
de Flask porque el historial la pasaba de los ~4 KB que aguanta un navegador y la cookie se
descartaba **sin avisar**, dejando al usuario deslogueado y sin conversación. En la cookie
queda solo `agente_sid`.

`agente_fotos_pendientes`: la foto de la que salió una ficha, esperando que se confirme el
alta (ver "Alta desde foto"). La clave es el token de contenido de `_token_ficha()`, no el
turno, porque la confirmación puede llegar desde otra página o mucho después.

Las dos se barren a los `CONVERSACION_DIAS` (30) días de inactividad, en la misma escritura
que las usa — no en `init_db()`, porque el server puede estar meses sin reiniciar.

### Guardias de seguridad / guardrails de prompt

- **Confirmación en dos turnos para eliminar**: el *system prompt* instruye a Claude a nunca
  ejecutar `eliminar_entidad` / `eliminar_prestamo` en el mismo turno en que se pide el borrado.
  Primero debe responder qué va a borrar y esperar una confirmación explícita del usuario en el
  turno siguiente. Es una guardrail de prompt (coherente con "/gestion" siendo "traba de
  desarrollo, no seguridad completa"), reforzada por la auditoría.
- **Confirmación de alta con ficha**: a diferencia del borrado, el alta **no** depende del
  prompt — `crear_entidad` no escribe hasta que el hash de la ficha coincida con uno mostrado
  en un turno anterior (ver "Alta con ficha de confirmación"). Vale también para las altas
  desde foto: la foto llena la ficha, no la base.
- **Resolución de ambigüedad en recursos**: si `crear_prestamo` busca un nombre de recurso
  que matchea más de una fila, la tool devuelve `ok:false` con `opciones` (id + nombre de cada
  candidato) en vez de adivinar. El system prompt instruye a mostrarle esas opciones al usuario
  y preguntar, nunca elegir por su cuenta ni reintentar adivinando.
- **Resolución de persona por lista conocida**: `chat_with_tools()` arma en cada turno la lista
  de "personas conocidas" (`_personas_conocidas()`: profesores de `clases` + personal no docente,
  ~340 nombres) y la inyecta completa en el system prompt. Regla: si el nombre que dio el usuario
  no es un match exacto/obvio contra la lista (apodo, nombre incompleto, typo — ej. "Dami"),
  el agente debe preguntar antes de crear el préstamo en vez de guardar el nombre tal cual; si no
  se parece a nadie de la lista, se asume persona externa (alumno/visita) y se usa tal cual sin
  preguntar. Se evaluó dar la lista completa en el prompt vs. una tool de "comparar nombre"
  dedicada — se descartó la tool porque ya existe `buscar_profesor` con la misma lógica de
  scoring y agregar una segunda ruta hubiera sido redundante; la lista en el prompt evita además
  que el agente decida "no hace falta buscar" y se salte la verificación. El costo en tokens es
  chico (~1500 tokens por turno) y no justificó una tabla de "personas" nueva en `gestion.db`
  (los préstamos son a veces gente que no está en ninguna lista — alumnos, visitas — así que
  seguir aceptando texto libre es correcto).
- **Devoluciones parciales no fallan en silencio**: `finalizar_prestamo`/`reabrir_prestamo` con
  `items` verifican que cada `recurso_id` pertenezca al préstamo antes de tocarlo; si no
  pertenece, la tool devuelve `ok:false` con el detalle en vez de reportar éxito sin haber
  cambiado nada (bug real: antes un `recurso_id` inválido se ignoraba silenciosamente y la tool
  igual respondía `ok:true`). El system prompt le pide al agente llamar primero a
  `detalle_prestamo(id)` para obtener los `recurso_id` reales de ese préstamo antes de devolver
  ítems puntuales, en vez de adivinarlos.

### Configuración

- **Env var** `AGENTE_PROVIDER` — `deepseek` (default) | `anthropic` | `groq` | `openai` |
  `ollama`. Define también qué loop de tool-calling corre: Anthropic tiene el suyo, el resto
  comparte `_loop_openai`.
- **Env var** de API key — `AGENTE_API_KEY`, o la del proveedor (`DEEPSEEK_API_KEY`,
  `ANTHROPIC_API_KEY`, `GROQ_API_KEY`, `OPENAI_API_KEY`). Sin ella el chat devuelve un error
  claro en vez de fallar en silencio. Ollama no la usa.
- **Env var** `AGENTE_MODEL` — modelo a usar. Defaults por proveedor: `deepseek-v4-pro`,
  `claude-haiku-4-5-20251001`, `mixtral-8x7b-32768`, `gpt-3.5-turbo`, `mistral`.
- **Env var** `AGENTE_VISION` — `1` para declarar que el modelo del **chat** lee imágenes.
  Anthropic ya viene en `1`; esto es para gpt-4o u ollama+llava, donde depende del modelo.
  Solo se consulta si **no** hay lector configurado (rama 2 de `chat()`).
- **Env vars del lector de fotos**, independientes de todo lo anterior:
  `AGENTE_VISION_API_KEY` (fallback `GEMINI_API_KEY`) — sin ella no hay lectura de etiquetas;
  `AGENTE_VISION_MODEL` (default `gemini-2.5-flash-lite`);
  `AGENTE_VISION_API_BASE` (default el endpoint OpenAI-compatible de Google). Con la key
  puesta, el alta desde foto anda con **cualquier** `AGENTE_PROVIDER`, incluido el default.
- **Env var** `AGENTE_API_BASE` — para APIs custom (Ollama, self-hosted).
- **Costo**: cada mensaje del chat arrastra el system prompt + los esquemas de las tools, ~15.000
  tokens de entrada, tenga foto o no — eso domina la factura, no las respuestas. **Un acceso de
  solo consulta paga bastante menos**: 15 esquemas en vez de 25, y un prompt de ~55% (sin el
  circuito de alta ni el padrón de ~1.600 tokens). Por eso el lector de
  fotos va aparte (~2.000 tokens por foto) en vez de mandarle la imagen al agente. Las
  lecturas (búsquedas, horarios) agregan poco (~100–500 tokens); las escrituras
  (create/edit/préstamos) más, porque la salida de la tool vuelve a entrar al modelo. El
  lector en su default (Gemini Flash-Lite) entra en el tier gratuito de 1.000 requests/día.

### La columna de nombre no siempre se llama `nombre`

El circuito de alta asumía una columna `nombre`, y `hitos` la llama `titulo`. Lo que sostiene
que el agente trate a todas las entidades igual:
- **`_crear_entidad`** valida `crud.campo_nombre(cfg)` de la entidad, no `'nombre'`.
- **`_nombre_de(slug, campos)`** resuelve el nombre visible de una ficha. Hace falta porque
  `campos` es el dict que armó el modelo, no una fila de la DB: ahí **no** llega el alias de
  `crud.select()`. Sin esto el botón de confirmar y el "✅ Guardado" salían en blanco para `hitos`.
- **`CAMPOS_REDACTADOS`** incluye `'titulo'` además de `'nombre'`.
- **Los esquemas de `crear_entidad` / `editar_entidad` exponen `titulo`**, más `nivel`,
  `etiquetas`, `protagonistas` y `fecha`. `required` es `['slug']` a secas: si hace falta
  `nombre` o `titulo` lo decide `_crear_entidad` contra `crud.campo_nombre`, la única fuente.
- **Las lecturas van por `crud.select()`**, que agrega `titulo AS nombre`: `_buscar_entidad_fmt`,
  `_listar_todos_fmt`, `_detalle_entidad_fmt` y `crud.snapshot_entidad` devuelven `nombre` en todos
  los slugs. `_listar_todos_fmt` y `_detalle_entidad_fmt` tenían la query cruda
  (`SELECT id, nombre …` / `SELECT * …`) y con `hitos` daban `no such column: nombre` y una
  ficha sin `nombre` respectivamente — arreglado 2026-08-10 al separar los módulos.
- **`vincular_entidad`** con `personas ↔ hitos` anda en las dos direcciones: `hitos` declara
  `rel_personas` como espejo de `personas.rel_hitos` sobre la misma tabla `persona_hitos`.

`hitos` tiene además una tool de lectura propia, **`buscar_hitos(etiqueta, desde_fecha,
hasta_fecha)`**, que ordena por nivel y fecha — el CRUD genérico cubre la escritura, ésa cubre
la consulta de la línea del tiempo. Lee de `historia.db`.

El system prompt describe **seis áreas** (horarios, inventario, préstamos, historia/lore, línea
del tiempo, personas). La sección de PERSONAS le marca dos cosas que el código no puede forzar:
que la semblanza institucional **no** se mezcla con las anécdotas literales de
`consultar_historia`, y que antes de crear una persona hay que buscarla, porque una segunda
ficha del mismo docente le parte la historia en dos.

### Las tools de préstamo cuentan cómo quedó, no lo que se pidió

Un préstamo puede terminar distinto de lo que se pidió (se devolvió parte, se topeó al stock, el
id no existía), y el modelo sólo tiene el JSON de la tool para saberlo. Contrato, desde 2026-08-11
(salió de romper a mano el circuito completo, ver `dev-log/DECISIONS.md`):

- **`finalizar_prestamo` y `reabrir_prestamo` devuelven `estado` y `pendiente_total` releídos
  después del commit**, más un `mensaje` que dice si el préstamo quedó abierto y qué falta. El
  mensaje viejo era `Devuelto préstamo id=N` para todos los casos: después de devolver 1 de 4, el
  modelo lo leía como que había vuelto todo.
- **Un id que no existe es un error.** Los `UPDATE … WHERE id = ?` no fallan cuando no matchean
  nada, así que `finalizar_prestamo(99999)` contestaba `ok: true` y el asistente daba por
  registrada una devolución que nunca ocurrió. Ahora se chequea la existencia primero
  (`_existe_prestamo`).
- **`items: []` es un error, no "devolvé todo".** `None` (la tool llamada sin `items`) significa
  todo; una lista vacía es un armado fallido, y tratarla como `None` cerraba el préstamo entero.
- **Lo que no se pudo aplicar se enumera**: ítems que no pertenecen al préstamo, cantidades ≤ 0 y
  ítems que ya estaban devueltos enteros vuelven en el `error`, separados de los que sí se
  aplicaron (`aplicados`).
- **`crear_prestamo` devuelve `ajustes`** cuando topeó al stock, sumó un recurso repetido (el
  `UNIQUE(prestamo_id, recurso_id)` antes reventaba con el error crudo de SQLite) o detectó que
  ya hay unidades afuera en otros préstamos. Una cantidad negativa se rechaza de plano.

### Claves de `relaciones` en `detalle_entidad`

`_detalle_entidad_fmt` arma `resultado['relaciones']` desde
`modulo.secciones_detalle()`, y **la clave que elige cambia lo que el modelo entiende**:

- Si el `slug` de la sección es una entidad real (está en `modulo.ENTIDADES`), la clave **es
  el slug** (`conjuntos`, `actividades`, `hitos`): así el modelo puede pasarla tal cual a
  `buscar_entidad` / `detalle_entidad`.
- Si no lo es, manda el **título** (`"En préstamo"`, `"Historial de préstamos"`).

El motivo es un bug real (2026-08-11): `prestamos` **no** es una entidad de `ENTIDADES`, pero
la sección "Historial de préstamos" la declara como `slug` para que el template genérico arme
el link a `/gestion/prestamos/<id>`. Con la clave cruda, el historial completo le llegaba al
modelo como `"prestamos": [...]` — o sea, indistinguible de "lo que está afuera ahora" — y
Emilio informaba como préstamo abierto uno cerrado hacía semanas. Regla general: **una clave
que el modelo lee como prosa no puede depender de un detalle de routing.**

### Integración con los módulos de dominio

- Reusan `ENTIDADES` de los dos módulos (config declarativa), resueltos por `_modulo(slug)`.
- **Toda la lectura/escritura genérica pasa por `crud.py`** (capa 1), con el área como primer
  argumento: `crud.conectar`, `crud.buscar_entidad`, `crud.guardar_entidad`,
  `crud.snapshot_entidad`, `crud.agregar_relacion_m2m`, `crud.quitar_relacion_m2m`,
  `crud.agregar_foto`, `crud.select`, `crud.campo_nombre`. Del módulo de área sólo se leen
  `ENTIDADES`, `LIMPIEZA_M2M` y el hook `secciones_detalle`. **Un área nueva tiene que cumplir el
  contrato de `agent_docs/crud-motor.md`** para que el agente la vea.
- De `gestion.py` (y solo de ahí) salen además los helpers de préstamos y carrito:
  `_resumen_items`, `_recalcular_estado`, `_stock`, `_int`, `_ahora`, `FORMATO_FECHA_REVISION`.
  Los préstamos son exclusivos del área de recursos y no pasan por el motor.
- **`texto.norm` / `texto.puntaje_busqueda` / `texto.UMBRAL_SIMILITUD`** son la única fuente de
  normalización y búsqueda difusa del archivo, para las tres fuentes de datos. Antes esto se le
  pedía a `gestion._norm` o a `historia._norm` según el call site, sin criterio — funcionaba sólo
  porque las dos copias eran idénticas (ver `dev-log/DECISIONS.md` 2026-08-10).
- Reusan queries de `database.py`: `aulas_libres()` (calcula libres vs ocupadas en `clases` a
  tiempo real, agrupadas por piso de `FLOOR_MAPPING`).
- El agente **no tiene acceso a escribir en `escuela.db`** (horarios) — solo lectura;
  actualizar desde Sheets sigue siendo un botón aparte del SPA.
