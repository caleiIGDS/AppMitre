# Asistente conversacional con tool-calling (`/agente`)

Área de la app al mismo nivel que horarios y `/gestion` (recursos) — y la única
transversal: lee horarios y escribe en gestión (los horarios son solo de consulta). Vive en
su propio paquete (`agente/`), su propio prefijo (`/agente`) y su propia carpeta de
templates (`templates/agente/`).

> Hasta 2026-09 también leía y escribía `/historia` (hitos y personas) y tenía un lore de
> la escuela narrado por un personaje (`consultar_historia`). Se extrajo del código junto
> con esa área — ver `dev-log/DECISIONS.md` — así que lo que sigue ya no lo menciona.

Es **un solo asistente** para todas las áreas, no uno por área: en la misma conversación se
pregunta un horario y se da de alta un recurso. Separarlo en varios rompería justamente eso.

Expone un chat conversacional contra el LLM configurado (DeepSeek por defecto,
Anthropic/OpenAI/Groq/Ollama según `AGENTE_PROVIDER` — ver "Configuración"). El usuario puede
hablar con la app en lenguaje natural en vez de hacer click en formularios: consultar
horarios, crear recursos, fotografiar etiquetas y cargarlas. Todo con auditoría de
escrituras en `agente_log`.

**Acceso**: dos vistas del mismo chat, ambas detrás del gate de `accesos.py`
(`accesos.registrar_acceso(bp, 'agente.leer', ...)`). El asistente declara **cuatro permisos
propios** —`agente.leer`, `agente.escribir`, `agente.vision`, `agente.auditar`— y **con cuáles tenga
cambia lo que el agente es**: con solo `agente.leer` las tools de escritura ni se le mandan al
modelo, y sin `agente.vision` no hay botón para adjuntar fotos ni tools que las miren. Ver
"Permisos" más abajo y `agent_docs/accesos.md`.
- Widget flotante, incluido en `/salidas` — para consultar sin salir de la
  página en la que se está. Hoy no hay ningún botón que lo abra en la UI (se sacó del header
  por duplicar el ☰, ver `dev-log/DECISIONS.md`): el markup y el JS quedan listos por si se
  reactiva.
- `/agente/`, el chat a pantalla completa, alcanzable desde el ☰. Es la vista pensada para el
  celular, que es donde más se usa el asistente.

## A qué datos llega (`SLUGS_ENTIDAD` y `_modulo`)

El agente cruza **`gestion.db`** más los horarios:

| Fuente | Slugs / datos | Acceso |
|---|---|---|
| `escuela.db` (horarios) | profesores, cursos, aulas | solo lectura |
| `gestion.db` (recursos) | `recursos` | lectura y escritura |

- **`SLUGS_ENTIDAD = list(gestion.ENTIDADES)`** — se deriva, no se escribe a mano. Es el enum
  de `slug` de todos los esquemas de tools; cuando estaba hardcodeado, agregar una entidad la
  dejaba invisible para el chat sin que nada fallara.
- **`_modulo(slug)`** devuelve el módulo de dominio dueño del slug — hoy siempre `gestion`.
  Todas las tools genéricas (`buscar_entidad`, `listar_todos`, `detalle_entidad`,
  `crear_entidad`, `editar_entidad`, `adjuntar_foto`) pasan por ahí y le entregan ese módulo
  al motor: `crud.buscar_entidad(_modulo(slug), slug, q)`, `crud.guardar_entidad(...)`, etc.
  **El área es siempre el primer argumento de `crud`.** Se conserva como función (en vez de
  usar `gestion` directo) para que un área de dominio nueva entre sin tocar acá.
- **`agente.DB_PATH` sigue siendo `gestion.db`**: las tablas propias del agente
  (`agente_log`, `agente_conversaciones`, `agente_fotos_pendientes`) viven ahí — son
  auditoría y sesión, no datos de dominio. La excepción es el **registro de uso**, que
  sí tiene DB propia (`agente.db`, `registro.py`) porque crece sin techo y no puede
  viajar en los respaldos rotativos de gestión.

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
| `registro.py` | El registro de uso y de chats, en `agente.db` (DB propia). Un INSERT por turno + las consultas del panel `/agente/uso`. |
| `padrones.py` | El padrón de gente de los horarios (docentes + no docentes) y los preceptores. Fuera de `tools/` porque lo usan las tools **y** el system prompt. |
| `vision.py` | El lector de etiquetas y listas: una llamada suelta, sin tools. |
| `prompt.py` | `construir_system_prompt()` — ~200 líneas de contenido, aparte del motor. Lo que cambia en cada turno va al **final** (ver "El orden de los bloques es el cache"). |
| `llm.py` | Clientes por proveedor y los **dos** loops de tool-calling. `chat_with_tools_stream()` es un **generador**: larga el progreso y devuelve la respuesta. |
| `filtros.py` | `_ocultar_ids` y las utilidades de contexto. |
| `enlaces.py` | Convierte en link al calendario los docentes, preceptores y cursos que la respuesta nombra, y le pega el link de la comparación cuando corrió `coincidencias`. Es filtro de **presentación**: se aplica al salir por la API (payload del turno + historial repintado), nunca a lo que se guarda. El de la comparación es el único que no vuelve al repintar: se arma con lo que cruzó la tool en ese turno. |
| `rutas.py` | Los endpoints Flask + el gate de acceso + el context processor. |
| `tools/` | Lo que el agente sabe hacer: `esquemas.py` (lo único que el modelo ve) y un módulo por área con los ejecutores. `tools/__init__.py` tiene `ejecutar_tool`, el dispatch. |

**El criterio del corte es la cohesión, no la capa**: el esquema de una tool y su ejecutor
quedan en el mismo módulo de área siempre que se pueda, porque son lo que cambia junto. Por
eso no hay un "archivo de descripciones" separado de un "archivo de código" — eso obligaría a
tocar dos archivos para agregar una tool en vez de uno. Ver `dev-log/DECISIONS.md` 2026-08-10.

Las dependencias van en una sola dirección y **no hay ciclos**:
`dominio → proveedores/db → padrones/vision → tools → prompt/llm → rutas`.
- **`POST /agente/chat`** — acepta `{mensaje, imagenes?}` (lista de hasta `FOTOS_MAX`=10 fotos
  en base64 o data URL; también acepta `imagen` singular, el contrato viejo);
  retorna `{respuesta, confirmaciones, reiniciada}`. `reiniciada` es `true` cuando la
  conversación había vencido por inactividad y este turno arrancó de cero (ver
  `_conv_cargar`) — es lo que usa `gestion-agente.js` para borrar del chat lo que quedó
  pintado de una charla que el servidor ya olvidó. El backend llama al modelo con el mensaje + tools
  disponibles, ejecuta lo que pida (tools de lectura y escritura), repite hasta respuesta final,
  audita escrituras en `agente_log`. `mensaje` puede venir vacío **si vienen `imagenes`** (mandar
  solo la foto de una etiqueta es un caso normal); vacío y sin fotos es `400`. El cuerpo del turno
  vive en **`_turno()`**, no en el endpoint, porque `/lote` lo usa igual. Ver "Alta desde foto".
  **El front ya no lo usa** — usa `/chat/stream`, que hace el mismo turno. Queda porque es el
  contrato que conocen las pestañas abiertas de antes del deploy.
- **`POST /agente/chat/stream`** — el mismo turno que `/chat` y el mismo body, pero la respuesta
  es **Server-Sent Events**: va largando `{tipo:'paso', texto}` mientras trabaja y termina con
  `{tipo:'fin', ...}`, cuyo contenido es **exactamente** el payload de `/chat`. Si algo revienta
  con el turno ya empezado sale `{tipo:'error', error}`, porque a esa altura los headers ya se
  mandaron y no hay forma de contestar un `500`. Ver "Contar en qué anda mientras tarda".
- **`GET /agente/historial`** — devuelve `{mensajes: [{rol, texto, imagenes?}], confirmaciones}`
  para repintar el chat al cargar la página. `gestion-agente.js` lo llama en el
  `DOMContentLoaded` (`cargarHistorial()`). **Hace falta desde que la conversación pasó a
  `gestion.db`**: el servidor la recuerda entre páginas, pero el chat se dibuja de cero en
  cada carga, así que el historial existía y no se veía. Devuelve también las fichas que hayan
  quedado sin guardar **con su estado de revisión** — si no, navegar a otra página dejaba las
  fichas vivas en el servidor y sin forma de darles OK, y con un lote a medio revisar había que
  revisarlo entero de nuevo. `_texto_visible()` aplana los bloques de
  contenido y saca lo que `chat()` le agrega al mensaje del usuario y él no escribió: el
  `(refiriéndote a: X)` y el `[Hora de este mensaje: ...]` (ver "La hora en cada mensaje").
  `imagenes` son las fotos adjuntas de ese turno como data URLs, y sólo vienen si el mensaje las
  tenía: las arma `_mensaje_visible()` (ver "Las fotos se ven en el chat").
- **`POST /agente/confirmar`** — acepta `{token}` de una ficha de alta pendiente y
  la guarda sin pasar por el modelo. Es el camino de **una sola ficha**. `409` si el token ya se
  usó, se reinició la conversación, o quedó desplazado por fichas más nuevas. Ver "Alta con ficha
  de confirmación".
- **`POST /agente/revisar`** — acepta `{token, estado, nota?}` o `{tokens: [...], estado}` y
  marca una o varias fichas del lote como `ok` / `observada` / `descartada`. **No escribe en el
  inventario ni llama al modelo.** `400` si el estado no existe; `409` si la ficha ya no está,
  sólo en la forma de a una — en la masiva un token caducado se saltea, para que una de sesenta
  no invalide las otras. Ver "Cargar de a muchas: el lote".
- **`POST /agente/editar_ficha`** — acepta `{token, campos}` y aplica una edición manual desde
  la tarjeta del chat. **No escribe en el inventario ni llama al modelo**: recalcula el token
  (es el hash del contenido) y reemplaza la ficha en la sesión bajo el token nuevo, con el
  `estado` de revisión vuelto a `pendiente`. `400` si el campo-nombre queda vacío, `409` si el
  token ya no está pendiente. Ver "Alta con ficha de confirmación".
- **`POST /agente/descartar`** — acepta `{token}` y baja UNA ficha pendiente sin guardar nada
  (el "✕ Cancelar" al lado del botón verde, en el circuito de una sola ficha). Saca la ficha
  de la sesión, tira su foto pendiente si tenía, y agrega el resultado al historial como un
  turno más (mismo patrón que `/confirmar`). `409` si el token ya no está pendiente.
- **`POST /agente/lote`** — cierra la revisión: escribe las aprobadas y manda las acotadas a una
  segunda vuelta con el modelo. `409` si no hay ninguna ficha revisada.
- **`POST /agente/reset`** — limpia `session['agente_historial']` y
  `session['agente_entidad_actual']`; usado por el botón ↺ del widget para arrancar una
  conversación nueva sin arrastrar contexto viejo.
- **`POST /agente/inventario`** — acepta `{inventario: '<slug>'}` y cambia en cuál de los
  inventarios trabaja el chat (el selector de la barra, ver "En qué inventario trabaja").
  `403` si no es uno de los que este acceso abre. **Reinicia la conversación** (`_conv_borrar`).
- **`GET /agente/`** (`chat_page`) — la pestaña del chat a pantalla completa
  (`templates/agente/agente_chat.html`, extiende `base.html`).
- **`GET /agente/log`** — tabla de auditoría (últimas 50 escrituras), con snapshot
  "antes" visible para poder restaurar manualmente si el agente cometió un error.
- **`GET /agente/uso`** — panel de consumo y de chats: quién, cuándo, cuántos tokens,
  cuánta plata y qué se preguntó. `?sid=` lee una conversación entera.

**Gate de sesión**: lo monta el motor compartido, en una línea al final del módulo —

```python
crud.registrar_acceso(bp, endpoints_pagina=_ENDPOINTS_PAGINA, endpoint_default='chat_page')
```

`/agente` es el único blueprint que **mezcla páginas HTML con endpoints JSON**, y por eso pasa
`endpoints_pagina`: los endpoints JSON (`/chat`, `/chat/stream`, `/reset`, `/confirmar`,
`/historial`) devuelven
`401` sin sesión, que es lo que el `fetch` del frontend sabe manejar; un redirect a HTML le
llegaría como un 200 sin sentido. Los que devuelven HTML —los de `_ENDPOINTS_PAGINA`— redirigen
a `/agente/login?next=...`, porque entrar por link directo a `/agente` desde el celular es el
caso normal y un 401 pelado ahí es un callejón sin salida.

Mismo motor de accesos y mismo `next` scopeado al prefijo propio (contra open redirect) que
`/gestion`. Con acceso pero **sin** el permiso de la ruta la respuesta es **403**, no
el login. Siete casos piden más que el permiso base:

| ruta | permiso | por qué |
|---|---|---|
| `/agente/confirmar` | `agente.escribir` | **escribe sin pasar por el LLM**: filtrar las tools no la protege en absoluto |
| `/agente/lote` | `agente.escribir` | ídem: escribe todas las fichas aprobadas de una |
| `/agente/revisar` | `agente.escribir` | no toca el dominio, pero es el circuito de alta: quien no puede escribir no tiene fichas que revisar |
| `/agente/editar_ficha` | `agente.escribir` | ídem: tampoco toca el dominio, pero es el circuito de alta |
| `/agente/log` | `agente.auditar` | la auditoría es de administración |
| `/agente/uso` | `agente.auditar` | ídem, y además se lee el texto de lo que escribió cada persona |
| `/agente/chat` y `/agente/chat/stream` **con `imagenes`** | `agente.vision` | gasta la API de visión; sin el permiso devuelve `403` |

El de `/chat` es un chequeo dentro de la vista y no un decorador porque la ruta **sí** está
permitida — lo que no está permitido es un campo del body. Un acceso sin `agente.vision` chatea
normalmente; sólo mandar una imagen le da `403`, que el front ya traduce a un mensaje legible.

### En qué inventario trabaja el chat

Gestión son **varios inventarios estancos** (`agent_docs/gestion-conocimiento.md`), y el
asistente trabaja en UNO: el de `session['inv_activo']`, que es lo que resuelve `db_path()` y
lo que hace que `gestion.leer` valga (sin inventario abierto, `recursos` se cae de los enum y
las siete tools de entidades no viajan).

El mismo `<select>` va en las dos vistas — la pestaña `/agente` y el widget flotante (ver
`_agente_widget.html`, `.agente-widget-invbar` en `gestion.css`) — con los inventarios que
este acceso abre (`gestion.abribles()`, la misma lista del panel del registro), aunque el
widget se abra adentro de `/gestion/<inv>/…` (donde la URL ya "sugiere" uno) o de `/salidas`
(donde no hay ningún `<inv>` en la URL). `POST /agente/inventario` lo cambia
(`gestion.activar()` revalida el slug: uno ajeno da `403`). Si no hay ninguno abierto el
selector arranca en un placeholder, y con cero inventarios abribles no se pinta.

**Cambiar de inventario reinicia la conversación**, y no es prolijidad: en el historial quedan
ids de recursos y fichas sin confirmar del inventario anterior, y un id no significa lo mismo
en el archivo de al lado — confirmar una ficha armada en el taller después de cambiar al
laboratorio daría de alta el recurso en el laboratorio. El front avisa antes de cambiar.

El prompt además **nombra el inventario abierto** (`_areas()` en `prompt.py`, con el nombre que
le pasa `llm.py` si el slug `recursos` sobrevivió en los enum): "el inventario" a secas invita
a contestar por uno cuando le preguntaron por otro. Cada inventario tiene entonces su propio
prefijo cacheado en el proveedor — es lo que se paga por que no los mezcle.

**Context processor propio**: `agente.bp` construye su `_contexto_base()` localmente
(`escuela_nombre`/`escuela_logo`/`escuela_version` salen de `config.py`). El motor CRUD ya
no tiene context processor (sus páginas se sacaron el 2026-10-05) y `/agente` tampoco es un
área CRUD. Los context processors de un blueprint no corren
para requests de otro, así que sin esto el header renderiza vacío.

### Contar en qué anda mientras tarda (`/chat/stream`)

**El costo de un turno no es una llamada al modelo, son varias.** Cada vuelta del loop es un
viaje completo: se manda el prompt entero, el modelo **razona antes de pedir la primera tool**
(con `deepseek-v4-pro` son entre 700 y 1.600 tokens de razonamiento, ver el comentario de
`MAX_TOKENS_SALIDA`), pide las tools, se ejecutan —eso es SQLite local, milisegundos— y se
vuelve a empezar. Las tools no son el problema: **el tiempo se va en el razonamiento,
multiplicado por la cantidad de vueltas**. Un turno de cuatro vueltas puede ser un minuto.

Con la respuesta de una sola pieza eso eran tres puntitos quietos y ninguna señal de si estaba
pasando algo o se había colgado. Ahora el turno se streamea:

```
data: {"tipo":"paso","texto":"pensando"}
data: {"tipo":"paso","texto":"leyendo las fotos"}
data: {"tipo":"paso","texto":"armando la ficha"}
data: {"tipo":"fin","respuesta":"...","tools":[...],"confirmaciones":{...}}
```

**Es un generador, no un hilo con una cola.** `chat_with_tools_stream()` hace `yield` de cada
paso y **devuelve** la respuesta final como valor de retorno (`StopIteration.value`);
`_turno_stream()` lo encadena con `yield from` y agrega su propio payload. Con un callback
`on_evento` habría que correr el turno en un hilo aparte para poder ir escribiendo la respuesta,
y ese hilo **se queda sin el request context de Flask** — de donde sale el id de conversación.
Como generador todo corre en el hilo de siempre y lo único que cambia es quién pide la próxima
vuelta. Los dos call sites que no tienen a nadie esperando (`/chat` y `/lote`) usan `_turno()`,
que es un `while` de tres líneas que drena el generador y se queda con el valor.

Dos detalles que no se ven:

- **El `_sid()` se toca ANTES de devolver la `Response`.** El id de conversación vive en la
  cookie, y la cookie viaja en los headers — que ya salieron cuando el cuerpo empieza a
  streamear. Sin esa línea, un visitante nuevo que arranca mandando un mensaje abría una
  conversación nueva en cada mensaje.
- **`X-Accel-Buffering: no`**, porque si no Nginx bufferea el stream entero y lo entrega junto
  al final, que es exactamente lo que este endpoint viene a evitar.

Lo otro que resuelve es la conexión: PythonAnywhere corta las requests que se quedan calladas, y
un turno largo se moría entero sin devolver nada. Un evento cada pocos segundos la mantiene viva.

Las etiquetas en castellano (`rutas.ETIQUETA_TOOL`) son **copy de pantalla, no un atributo de la
tool**: el esquema de `tools/esquemas.py` es lo único que ve el modelo y esto es lo único que ve
el usuario. Una tool sin entrada en el mapa cae en `'consultando'`, así que agregar una tool no
rompe nada.

Del lado del navegador se parsea a mano (`leerStream()` en `gestion-agente.js`) y no con
`EventSource`, porque `EventSource` sólo hace GET y acá hay que mandar el mensaje —y hasta ocho
fotos en base64— en el body de un POST. Si el stream se corta antes del `fin`, el chat lo dice:
pintar un mensaje vacío se lee como si el asistente no hubiera tenido nada que contestar.

### Las dos vistas del chat

Comparten markup y JS; lo único que cambia es el contenedor.

| Archivo | Rol |
|---|---|
| `templates/agente/base.html` | Layout propio del área: header propio (sin links cruzados: saltar de área es el ☰), nav ASISTENTE + AUDITORÍA. No incluye el widget flotante. |
| `templates/agente/_agente_chat_core.html` | El chat en sí: `#agente-messages` + área de input (texto, 📷 imagen, enviar, link a auditoría). **Único lugar donde se edita el markup del chat.** |
| `templates/agente/_agente_widget.html` | Widget flotante = header propio (↺ reiniciar, ⤢ abrir a pantalla completa, ✕ cerrar) + selector de inventario + el core. Lo incluyen `gestion/base.html` y `salidas/base.html`. |
| `templates/agente/agente_chat.html` | Pestaña = barra de título + selector de inventario + el core, dentro de `agente/base.html`. |
| `templates/agente/agente_log.html` | Auditoría, dentro de `agente/base.html`. |
| `templates/agente/login.html` | Login del área. |
| `static/gestion-agente.js` | Sirve a las dos vistas. Las URLs (`/agente/chat`, `/agente/historial`, `/agente/confirmar`, `/agente/reset`, `/agente/inventario`) están hardcodeadas ahí: si cambia el prefijo del blueprint, hay que tocarlas. |

Los IDs del core (`agente-messages`, `agente-input`, `agente-send-btn`, `agente-reset-btn`,
`agente-inv-select`…) son únicos y el JS los busca con `getElementById` — por eso **las dos
vistas nunca se renderizan juntas**. Hoy la invariante se cumple sola porque viven en layouts
distintos: el widget lo incluyen `gestion/base.html` y `salidas/base.html`, y
`agente/base.html` (el de la pestaña) no lo incluye. Si se agrega otra vista del chat,
mantener esa invariante.

Progressive enhancement: con JS es fluido, sin JS el chat no funciona pero el resto del
servidor sigue andando. Las respuestas se renderizan como markdown liviano
(`renderMarkdown()` en `gestion-agente.js`: negrita, listas, tablas y links) — el modelo
devuelve Markdown y sin esto se veía como un bloque de texto con `**`/`|` crudos. Los
links son los que pone `enlaces.py` sobre los nombres del calendario, y el renderer solo
acepta destinos internos (los que arrancan con `/`): el href viene de texto de un LLM.

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
  mueve —junto con los botones del header— al panel que se abre con ☰, así el chat se
  queda con toda la altura. (En escritorio ese mismo panel existe igual, pero sólo con el
  menú de áreas.) Ver la sección "Celular" de `agent_docs/gestion-conocimiento.md`. La regla vieja que lo hacía scrollear en
  horizontal (`body.g-chat-page .g-nav`) sigue en `gestion.css` como fallback para cuando
  no hay JS y el nav se queda en su lugar.

### Tools

Qué permiso pide cada una está en **`PERMISO_POR_TOOL`** (`agente/tools/esquemas.py`), que es la
**única fuente de verdad**: `TOOLS_ESCRITURA`, la decisión de auditar y el filtrado por acceso se
derivan de ahí. Antes esa clasificación estaba copiada a mano en tres lugares. Una tool nueva sin
entrada en el dict hace fallar el import, a propósito.

Las dos de foto (`TOOLS_FOTO` = `leer_foto` + `adjuntar_foto`) piden **además** `agente.vision`, que
es de administración: sin él no viajan, y el usuario tampoco tiene botón para mandar una foto. El
permiso extra se pide *además* y no *en lugar del* declarado, para que `adjuntar_foto` no pueda
escribir en una galería sin `agente.escribir`. Ver `agent_docs/accesos.md`.

**Lectura** — `agente.leer` (no se auditan):
- `buscar_profesor(query)` — resolución difusa de nombre, **sobre el padrón de los
  horarios**: docentes de `clases` **y personal no docente** (ver abajo). Cada candidato lleva
  su `rol` si tiene cargo no docente. Si
  coincide con un preceptor, agrega `preceptores` + `aviso_preceptores`. Si **no** coincide
  nadie devuelve `padron_completo`, ver "Cuando no coincide nadie"
- `buscar_por_rol(rol?)` — personal no docente **por cargo**, no por nombre ("¿qué EMATP hay?").
  Sin `rol` devuelve el padrón entero; con un `rol` que no matchea lo devuelve igual en
  `padron_completo`, ver "Buscar por cargo"
- `preceptores(curso?, division?, preceptor?)` — preceptor ↔ curso, ya digerido: titular y
  contraturno separados, ver "Los preceptores entran por su propia tool". Un `preceptor` que no
  matchea también devuelve `padron_completo`
- `horario_profesor(nombre)` / `horario_curso(curso, division)` / `horario_aula(aula)`
  — horarios agrupados por día. `horario_profesor` cubre también al personal no docente, y
  devuelve `padron_completo` cuando no encuentra a nadie. Las clases de media división llevan
  ` · Grupo A`/` · Grupo B` al final de la línea y las tres suman `nota_grupos` cuando aparece
  alguna: sin eso el modelo leía las dos mitades de un taller como una superposición. La nota
  aclara que lo habitual —no la regla— es que ambas mitades vayan a la misma hora
- `aulas_libres()` — aulas desocupadas ahora, agrupadas por piso
- `coincidencias(cursos?, personas?, dia?)` — cuándo dos o más entidades están en la escuela
  a la vez, mezclando cursos con docentes, preceptores y no docentes. Corta el día en cada
  frontera horaria y devuelve **una sola** lista de tramos ya calculados,
  `tramos_coincidentes`, más —si entra en `LIMITE_GRILLA_CHARS`— una `grilla` alineada donde
  cada tramo dice, por entidad, la materia / `hueco` / `hueco largo` / `fuera`. Un pozo de
  hasta `HUECO_MAXIMO_MIN` (40 min) entre dos clases cuenta como que la entidad sigue en la
  escuela; más largo que eso es `hueco largo` y ahí no coincide. Cuando un curso entra a un
  tramo coincidente con una sola de sus mitades (taller) eso va en `medio_curso`, con la
  `nota_grupos` que le pide avisar que está media división. La `instruccion` le prohíbe
  explicar el criterio: la respuesta son los horarios, no cómo se calcularon. Con muchas
  entidades la grilla es el 99% del payload y no explica nada, así que se omite: llega
  `grilla_omitida: true` y otra `instruccion`, y los tramos siguen siendo exactos porque se
  calculan antes de descartarla.
  La cuenta la hace Python a propósito: ver `dev-log/DECISIONS.md`.
  Además deja en `contexto_turno['comparacion']` las entidades que el modo comparación del
  calendario sabe dibujar —cursos y docentes con clases; preceptores y no docentes puros
  quedan afuera y se aclaran en el texto—, y con eso `enlaces.enlace_comparacion` le pega a
  la respuesta el link que las abre superpuestas en `/horarios`
- `buscar_entidad(slug, query)` — búsqueda de recursos (gestion.db); el módulo lo resuelve
  `_modulo(slug)` (calidad del match explícita, ver abajo)
- `listar_todos(slug, con_descripcion?)` — lista completa de nombres + id, y en `recursos`
  también `ubicacion` (cada lugar con cuántas unidades hay ahí). **Fallback** de
  `buscar_entidad` cuando no hay ningún match `exacto`, y la **única** entrada por ubicación
  que tiene el agente, ver abajo
- `detalle_entidad(slug, id)` — detalle completo + relaciones (ver "Claves de `relaciones`")
- `listar_alias(slug)` — **solo admin** (`gestion.alias`, igual que `/gestion/<inv>/alias`): todos los
  recursos con su alias en texto, para que el asistente los audite/mejore. Es la única tool que
  expone ese texto — `buscar_entidad` sólo marca `match:"alias"` sin mostrarlo
- `leer_foto(modo?, foto?)` — mira las fotos adjuntadas en ESTE turno y las devuelve en texto,
  cada lectura con el número de su foto. **Sin `foto` lee todas de una sola llamada**, que es
  como hay que usarla. `modo`
  `etiqueta` (default) transcribe la chapa de un producto; `listado` transcribe una página o
  tabla con varios ítems distintos (contenido de un kit, remito) como un renglón por ítem —
  alimenta el alta de un kit vía `sub_recursos`; `analisis` describe qué se ve. No
  toca la base (por eso está acá) pero **sí gasta la API de visión** (una por foto), así que el
  prompt le pide llamarla solo cuando necesita los datos, nunca para adjuntar. Ver "Alta desde
  foto"

**Escritura** — `agente.escribir` (se auditan, guardan snapshot "antes"):
- `crear_entidad(slug, campos, foto?, sub_recursos?, ubicacion?)` — alta **en dos pasos con ficha de
  confirmación**, ver abajo. `foto` es de qué foto del turno salió la ficha, y es lo que hace que
  la imagen termine en el registro correcto. `ubicacion` (solo `recursos`) es dónde se guarda: va
  como pseudo-campo `_lugar` del borrador —entra al token, se ve y se edita en la tarjeta como
  "Ubicación"— y al confirmar se aplica con `gestion.mover_unidades` sobre todas las unidades del
  recurso recién creado. `fecha_revision` **ya no se muestra en la ficha de alta**: se completa
  sola con la fecha de hoy (`CAMPOS_OCULTOS_FICHA` en `agente/tools/fichas.py`). `sub_recursos`
  (solo `recursos`) convierte el alta en
  un KIT: lista de `{titulo, cantidad}` — nada más, sin descripción ni estado propios — que se
  escribe en `gestion.kit_items` recién al confirmar, junto con el recurso. Se muestra al final de
  la tarjeta del chat como lista de solo lectura (una línea por item); el `recurso_asignado` de
  cada sub-recurso queda vacío, sólo se completa a mano desde la web. Hay que reenviarla completa
  en cada llamada, igual que el resto de la ficha — si se omite en una corrección, se pierde. Ver
  "Kits" en `agent_docs/gestion-conocimiento.md`
- `editar_entidad(slug, id, campos, sub_recursos?)` — update. `sub_recursos` (solo `recursos`) es
  la excepción a "update parcial de columnas": es ADITIVO, suma sub-recursos al kit que YA existe
  sin tocar los que ya tiene ni pisar el `recurso_asignado` que se haya cargado a mano — es lo que
  permite mandar el contenido de un kit en varias tandas (dos fotos en turnos distintos) sin tener
  que repetir la primera
- `editar_sub_recurso(id, item_id, titulo?, cantidad?, recurso_asignado?)` / `eliminar_sub_recurso
  (id, item_id)` — corrigen o borran UN renglón puntual de `kit_items`. `item_id` es la fila del
  sub-recurso (no el id del kit): el modelo lo saca de `detalle_entidad`, nunca lo inventa. Sin
  ficha de confirmación (mismo criterio que `mover_ubicacion`: corrección puntual, fácil de
  rehacer). Ejecutan `gestion.editar_kit_item` / `gestion.eliminar_kit_item`, los mismos helpers
  que usan las rutas web `kit_item_editar` / `kit_item_eliminar`
- `adjuntar_foto(slug, id, foto?)` — guarda las fotos de ESTE turno en la galería de un registro
  que ya existe (sin `foto` van todas, con `foto` sólo esa). Sin ficha de confirmación (es
  aditivo); las imágenes salen de `contexto_turno`, no de un parámetro
- `mover_ubicacion(recurso, destino, numeros?, cantidad?, origen?)` — la forma de mover un recurso
  que **ya existe** (en el alta, la ubicación va por el parámetro `ubicacion` de `crear_entidad`).
  No hay un campo `ubicacion` en `editar_entidad`: la ubicación es siempre la lista de unidades en
  `gestion.recurso_unidades`, aunque el recurso tenga una sola. Cada unidad tiene su propio número: `numeros` mueve unidades
  puntuales ("el destornillador 3 y el 5"), `cantidad` mueve N unidades sin importar cuáles
  (incluida la única unidad de un recurso sin desglosar) — hace falta uno de los dos. **Nunca
  bloquea** por falta de desglose previo: números que no existen, o (con `cantidad`) un `origen`
  con menos registrado, igual mueve lo que se puede y avisa (`avisos`) — ver
  `agent_docs/gestion-conocimiento.md`. `origen` sólo aplica junto con `cantidad` y es opcional
  (unidades sin lugar registrado antes)

No hay tool que elimine una entidad: un recurso no se borra nunca, sale del inventario
dándolo de baja desde la web (ver `agent_docs/gestion-conocimiento.md`).

### Permisos: no tener la tool, no tenerla prohibida

Un acceso de consulta **no recibe** los esquemas de las tools de escritura. La diferencia con
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

1. **Filtrado del esquema** — `tools_permitidas()`. El modelo ve entre menos de 10 tools (sólo
   lectura, sin inventario abierto) y las 20 (admin, con inventario abierto y visión).
2. **`ejecutar_tool(..., permisos=None)`** — chequea igual. Cubre `/agente/confirmar`, que escribe
   sin pasar por el LLM, y el caso de que el modelo invente un nombre de tool. El default `None` es
   **fail-closed**: un call site nuevo que se olvide de pasar permisos falla cerrado y ruidoso, no
   abierto y en silencio. Un rechazo de escritura **se audita**: si aparece en `/agente/log`, o
   alguien forjó el request o el filtrado tiene un agujero.
3. **El system prompt** — `construir_system_prompt(..., escribe=, ve_fotos=)`, ver abajo.

Los cuatro call sites de `ejecutar_tool` pasan permisos: los dos del loop Anthropic, el de
`_loop_openai` y el de `rutas.confirmar`.

Las tools genéricas por slug (`crear_entidad`, `buscar_entidad`…) están escritas para poder
cruzar varias áreas de dominio, así que **no** se pueden mapear a `gestion.editar` desde el
esquema — de ahí que el agente tenga permisos propios.

El mecanismo de permiso-por-entidad (`agente.dominio.ve_entidad(slug, permisos)`, vía
`crud.permiso_entidad`) sigue existiendo por si una entidad futura pide un permiso propio
además del área — hoy ninguna lo hace. Se aplica en las mismas capas: `tools_permitidas()`
recorta el slug de los enum, y `ejecutar_tool` rechaza `slug`/`slug_origen`/`slug_destino`
prohibidos antes del `try`.

### El system prompt se recorta con las tools (`prompt.py`)

`prompt.py` está partido en bloques y `construir_system_prompt(..., escribe=)` arma la lista.
Con `escribe=False` no van el circuito de alta, el de carga desde etiqueta ni las reglas de
borrado; sí va `_SOLO_LECTURA`, que le dice explícitamente que esas herramientas **no
existen** para él y que no escriba "✅". Las reglas numeradas se renumeran solas: saltar del 1
al 3 le marcaría al modelo que hay reglas que no está viendo.

`escribe` lo decide `llm.chat_with_tools_stream` mirando **las tools que efectivamente se
mandaron**, no los permisos del usuario: así es imposible que el prompt hable de dar de alta
mientras las tools de alta no viajaron.

`ve_fotos` sale del mismo lugar y por la misma razón, de `TOOLS_FOTO & {las tools que se
mandaron}`: sin `agente.vision` no van `_FOTOS`, `_ETIQUETA`, `_FOTOS_SOLO_LECTURA` ni
`_REGLA_FOTO`. No es sólo ahorro de tokens — explicarle qué hacer con una foto a un acceso
que **no tiene el botón para mandarla** lo llevaría a ofrecer algo imposible. Las reglas se
renumeran solas también acá.

`ve_notas` sale de `TOOLS_NOTAS & {las tools que se mandaron}`: sin `agente.notas` el prompt
no nombra el archivo de notas ni muestra una sola línea (ver "`agente.md`").

Esto también apaga un problema conocido: `_escritura_no_ejecutada` (`filtros.py`) marca cualquier
"✅" sin escritura exitosa. Para un acceso de consulta **ninguna** escritura corre nunca, así que
cualquier ✅ decorativo dispararía el banner — por eso el bloque le prohíbe el símbolo de entrada.

#### El orden de los bloques es el cache

**Lo que cambia en cada turno va al final del prompt.** Los proveedores cachean el prefijo del
pedido: reaprovechan todo lo que va antes del primer carácter distinto y reprocesan de cero lo
que viene después. El bloque de fecha trae la hora **con minutos**, así que es lo único que
cambia turno a turno — y estaba cuarto de doce, a unos 3.000 tokens del arranque. Los ~7.000
tokens que le seguían se reprocesaban en frío cada vez.

Movido al fondo, el prefijo estable de un acceso de escritura pasa de ~3.000 a **~10.000 tokens**
(el prompt entero), más los ~10.000 de los esquemas de tools, que viajan antes. No cambia lo que
el modelo lee: la hora que manda es el sello `[Hora de este mensaje: ...]` que lleva cada mensaje
del usuario, y el propio bloque lo dice.

Hoy no queda ningún bloque intermedio que interpole datos del turno: los dos que interpolan van
al fondo, y en ese orden — primero `_notas()`, que cambia sólo cuando alguien anota o borra algo,
y último `_fecha()`, que cambia a cada minuto. Para una misma combinación de
`escribe`/`ve_fotos`/`ve_notas`, todo lo que va antes de las notas es idéntico byte
a byte entre turnos. **La regla para cualquier bloque nuevo que interpole algo del turno es la
misma: al final**, o rompe el cache de todo lo que tenga debajo.

La otra mitad del mismo problema es la **cantidad de vueltas**, y esa se ataca en el contenido:
`_COMO_TRABAJAS` le pide explícitamente que mande juntas todas las tools que no dependan una de
otra (tres horarios son tres `horario_profesor` en la misma vuelta, ocho fichas son ocho
`crear_entidad` juntas) y que encadene sólo cuando el segundo llamado necesita el resultado del
primero. Cada vuelta que se ahorra es todo el razonamiento de esa vuelta.

### `agente.md`: las notas del asistente (`notas.py`, `/agente/notas`)

El CLAUDE.md del agente: un markdown suelto en la raíz del proyecto con lo que tiene que saber
**estos días** — "el pañol está en el aula 12 hasta que arreglen el techo", "las salidas de este
año las coordina Vanesa", "no cargues la máquina de café como recurso", la lista que la
administración quiere tener a mano un par de semanas. Si viviera en `prompt.py`, cada aviso
costaría un deploy.

**Qué entra lo decide quien escribe, no el modelo.** Es la libreta del administrador: si le
piden anotar algo, el agente lo anota y no discute si "corresponde" que vaya a una ficha; si el
dato además tendría lugar en el inventario, lo ofrece después y en una línea. Lo único que no
hace es anotar por su cuenta lo que nadie le pidió. La regla vive en la descripción de
`escribir_notas` y en `_NOTAS_VACIA` / `_notas()` de `prompt.py`.

**No va en git** (`.gitignore`, como los `.db`), y eso es lo que hace que la idea funcione: el
agente lo escribe, así que la copia del servidor se separa de la del repo desde la primera nota.
Un archivo que escriben git y la app a la vez no tiene arreglo bueno — el próximo `git pull` lo
pisa o deja un conflicto en producción. Suelto en el disco del server, sobrevive a todos los
deploys sin que nadie lo toque.

**Se edita entero**, igual que un CLAUDE.md: desde `/agente/notas` (un textarea con el archivo) o
por chat con `escribir_notas`, donde el modelo manda el contenido COMPLETO — lo tiene a la vista en
su propio prompt — con el renglón agregado, sacado o corregido. No hay ids ni renglones numerados:
es texto. Lo que no copia, se pierde, y por eso el esquema de la tool insiste en eso más que en
ninguna otra cosa.

**La red de seguridad es `agente.md.bak`.** Cada escritura guarda antes la versión anterior y la
página ofrece DESHACER (de una sola vez, el `.bak` se consume). El segundo camino de vuelta es
`agente_log`: `escribir_notas` está en `TOOLS_AUDITADAS` aunque no sea `agente.escribir`, y su
`antes` es el archivo completo previo. Meterla en `TOOLS_ESCRITURA` habría sido más corto y estaba
mal: ese conjunto es lo que enciende `escribe` en el system prompt, y un acceso con notas y sin
carga se habría llevado el circuito de alta entero.

`LARGO_MAX` (4.000 caracteres, ~1.000 tokens) es lo único que lo mantiene barato: el archivo entero
viaja en **cada turno** de quien tenga el permiso, así que son tokens que se pagan siempre. Pasado
ese tope no se guarda y hay que sacar lo que ya no corre — no vence nada solo, a propósito: una
nota no sabe cuándo dejó de ser cierta.

Quién lo ve: sólo los accesos con `agente.notas`, verbo `admin` (ver `agent_docs/accesos.md`). El
bloque `_notas()` va anteúltimo en el prompt, justo antes de la fecha, con el contenido entre
delimitadores explícitos (`--- empieza agente.md ---`) para que el modelo sepa exactamente qué
copiar al reescribirlo. Le dice además dos cosas que no son obvias: que **no lo recite** si no
viene al caso, y que una nota **no es un dato de la base** — si contradice lo que devolvió una
tool, dice las dos cosas y no corrige nada.

### Alta con ficha de confirmación (`crear_entidad`)

Ningún alta se escribe sin que el usuario haya visto antes, campo por campo, lo que va a
quedar guardado. Circuito:

1. El asistente llama a `crear_entidad`. **La primera llamada con un juego de campos no
   escribe nada**: devuelve `{requiere_confirmacion: true, ficha, campos_vacios,
   redactados_por_vos, instruccion}` (y `tipos_en_uso`, que es de `recursos`).
2. El asistente **no repite la ficha en el texto**: `gestion-agente.js` la pinta debajo del
   mensaje como una **tarjeta editable** (`tarjetaFicha()`), un input por campo, con
   `confirmaciones[].campos` (`[{nombre, label, tipo, valor, opciones?, redactado?}, …]`,
   armado por `fichas._campos_para_editar()` reusando el mismo `tipo`/`opciones` que declara
   `ENTIDADES` para el formulario de la app de Gestión). El asistente sólo agrega, debajo, 1 a 3
   preguntas cortas por lo que falta ("¿de qué medida es?", "¿sabés la marca?"). **No son
   bloqueantes**: si el usuario no contesta, se guarda igual — está en el prompt y en el
   `instruccion` de la ficha.
3. **Si algo no le gusta, el usuario lo edita ahí mismo** — no hace falta pedírselo al
   asistente por chat. Cada campo postea a **`POST /agente/editar_ficha`** (`{token,
   campos}`) al perder el foco: como el token es el hash del contenido, la edición recalcula
   uno nuevo y reemplaza la entrada vieja en la sesión — mismo mecanismo que cuando el
   modelo rearma la ficha, pero sin pasar por el LLM ni escribir en el inventario. Si el
   usuario **sí** le pide el cambio por chat, el asistente vuelve a llamar a `crear_entidad`
   con los campos corregidos y sale otra ficha (con su tarjeta). Se repite hasta el OK.
4. **El OK es un botón, no una respuesta escrita.** `/chat` devuelve además
   `confirmaciones: [{token, etiqueta, nombre, estado, campos, nota?, foto?, sub_recursos?}, …]` con las
   fichas pendientes, y `gestion-agente.js` las pinta debajo del mensaje
   (`agregarConfirmaciones()`). **Con una sola ficha** es el botón verde de siempre, que pega
   en **`POST /agente/confirmar`** con su token: el alta se resuelve ahí, en Python, **sin
   llamar al modelo** — instantánea, gratis, y sin margen para que el modelo escriba otra
   cosa. Los campos salen de la sesión, nunca del request (los edite o no el usuario en la
   tarjeta). **Con dos o más** entra el circuito de revisión en lote (ver abajo). El
   resultado se agrega al historial como un turno más, con el nombre de lo que se guardó,
   para que el asistente sepa después que eso ya está y qué sigue pendiente.
5. **El modelo nunca guarda un alta**: mostrar la ficha es lo último que hace con ella. Si el
   usuario escribe "dale, guardalo", `crear_entidad` vuelve a devolver la ficha y no escribe.
   Lo único que escribe es `rutas._guardar_ficha()` —o sea `/confirmar` y `/lote`—, que pasa
   `contexto_turno['confirmado_por_usuario']`; el modelo no puede ponerla porque no es un
   parámetro de la tool.

**Varias altas en un turno** (`_confirmaciones`). "Creá a Pablo y a Ezequiel" son dos
llamadas a `crear_entidad` en la misma respuesta y **dos fichas con dos juegos de botones**.
Antes se mandaba una sola confirmación —la última— y las anteriores quedaban vivas en la
sesión sin ningún botón que las guardara: el usuario veía las dos fichas, confirmaba, y se
daba de alta una sola sin que nada avisara. Tres reglas sostienen el caso:
- `contexto_turno['fichas_mostradas']` es un dict con **todas** las del turno, y `/chat`
  arma una fila por cada una.
- Se devuelven **todas las pendientes, no solo las de este turno**: una ficha sin guardar
  tiene que reaparecer debajo de la respuesta siguiente o se pierde igual. Reaparecer no
  escribe nada: guardar es siempre un click explícito.
- Si dos fichas pendientes son la **misma alta** (el usuario pidió un cambio y el modelo la
  rearmó), la nueva **reemplaza** a la vieja en la sesión, en `_fusionar_fichas()`. La
  identidad es el nombre, más el número de foto cuando salió de una (`_identidad_ficha()`, que
  usan también los botones): el nombre va siempre porque **una foto puede ser N altas** —el
  índice de una colección, un remito— y con la identidad puesta sólo en el número, esas N
  colapsaban a una. El caso que cubría —la corrección que le cambia el nombre a la única ficha
  de una etiqueta— lo sostiene el reemplazo 1-a-1 de `_reemplazo_uno_a_uno()`: si la foto tenía
  UNA ficha viva y vuelve con UNA sola, la nueva pisa a la vieja aunque cambie el nombre. No alcanza con esconder la vieja al mostrar: si sigue viva en
  la sesión, al guardar la nueva reaparece sola en el turno siguiente y un segundo click da de
  alta el mismo recurso dos veces.

El nombre va **dentro** del botón ("✅ Guardar recurso: Multímetro Fluke 117"): con dos o
tres seguidos, "Guardar recurso" repetido no dice cuál es cuál.

### Cargar de a muchas: el lote

Es el flujo de vaciar una estantería en el inventario: se mandan hasta ocho fotos y sale una
ficha por foto —o decenas de una sola, si la foto es una lista de ítems sueltos—, **se revisan
todas antes de que se escriba nada**, y un botón al final guarda las aprobadas y manda las
acotadas de vuelta al asistente.

El botón que guardaba al toque no servía para esto por dos razones concretas: obligaba a
decidir de a una y sin vuelta atrás, y pedir una corrección escribiendo se llevaba puesto lo
ya revisado (`quitarConfirmaciones()` borraba los botones apenas el usuario tipeaba algo).

**Cuándo se activa**: cuando quedan **dos o más** fichas pendientes. Con una sola sigue el
botón verde directo — meterle dos pasos al caso de siempre sería un click de más.

**Los tres estados** (`ESTADOS_REVISION`, en `conv['fichas'][token]['estado']`):

| botón | estado | qué pasa al cerrar el lote |
|---|---|---|
| ✅ está bien | `ok` | se escribe, con su foto y sus vínculos |
| ✏️ corregir + qué está mal | `observada` | **no se escribe**: vuelve al modelo para que la rearme |
| ✕ no va | `descartada` | se tira, y con ella la foto si no queda otra ficha que la use |

Marcar pega en **`POST /agente/revisar`**, que no toca el inventario ni llama al modelo. El
estado vive en la DB y no en el DOM: por eso sobrevive a recargar la página, a navegar a
`/gestion` y a mandar otro mensaje en el medio — `/historial` lo devuelve y el front repinta
la revisión tal cual estaba. Es también lo que permite que **escribir no borre el lote**: con
dos o más fichas el front ya no las quita al enviar un mensaje, las repinta con la respuesta.

**El botón de cerrar se habilita recién cuando no queda ninguna pendiente.** La idea del lote
es mirar las ocho antes de tocar nada; con el botón vivo desde el principio es fácil mandar
media tanda sin querer. Mientras falten, dice "faltan 3 por revisar".

Al lado hay un **"✅ las N"** que aprueba de una las que siguen pendientes, en un solo
`/revisar` con la lista de tokens. No es un atajo de comodidad: con sesenta fichas —una foto
de una lista— la regla de arriba pide sesenta clicks para poder cerrar. Marcar no escribe
nada, así que aprobarlas todas y después bajar las tres que no van sigue siendo reversible.

**`POST /agente/lote`** hace las tres cosas en una: escribe las `ok` (con `_guardar_ficha()`,
el mismo camino que `/confirmar`), borra las `descartada` con su foto, y arma **un solo
mensaje** con todas las correcciones para el modelo (`_mensaje_correcciones()`):

```
(revisé las fichas con los botones)
Guardé: Panel solar 250W, Inversor Growatt 3kW.
Descarté: Cargador viejo.
Estas NO se guardaron. Rearmá cada una con la corrección que te digo […]:
- "Taladro Bosch" (foto 3): la marca está mal, es Makita
```

Es **un turno para todo el lote y no uno por corrección**: ocho fichas serían ocho llamadas al
modelo y ocho respuestas para leer. Y **si no quedó ninguna observada no se llama al modelo**:
la respuesta se arma en Python, como `/confirmar`. Un lote todo aprobado es el caso más común
y no tiene por qué costar un turno de LLM.

Tres detalles que no son obvios:
- **Las observadas salen de `fichas` antes de la segunda vuelta.** El modelo las rearma desde
  cero, con token nuevo; dejar la vieja viva daría dos botones para la misma alta. Lo que
  sobrevive es la **foto**, que está atada al número y no al token.
- **Se persiste antes de llamar al modelo**, porque `_turno()` recarga la conversación de la
  DB: si no, las fichas recién guardadas seguirían ahí y el modelo las vería como pendientes.
- **El mensaje sintético no se le muestra al usuario**: `_texto_visible()` lo corta entero por
  su prefijo (`MARCA_LOTE`). Son instrucciones para el modelo, y el resumen de lo guardado ya
  se lo dice la respuesta de abajo.

**Cómo se sabe que el usuario aprobó** (`_token_ficha`): cada ficha se identifica por un
SHA-1 de su contenido (`slug` + los campos normalizados). Una llamada escribe solo si su
hash ya se mostró en un turno **anterior**. Consecuencias buscadas:
- Cambiar un solo campo entre la ficha y el alta da otro hash → vuelve a la ficha. No se
  puede guardar algo distinto de lo que el usuario leyó.
- Una ficha mostrada en el turno en curso no habilita nada: el loop ejecuta todas las
  tools antes de devolver una palabra, así que el usuario todavía no la vio.
- El hash se **consume** al escribir; repetir la llamada arranca de nuevo por la ficha en
  vez de duplicar el recurso.

Los hashes viven en la columna `fichas` de `agente_conversaciones` — un dict
`{token: {slug, campos, estado, nota?, foto?}}`, tope `FICHAS_MAX` = 100: no alcanza con el
lote de ocho más su segunda vuelta, porque una sola foto de una lista son decenas de altas y
el recorte se lleva las últimas **sin avisar**. `_turno()` lo carga en
`contexto_turno['fichas_previas']` antes de llamar al modelo y lo vuelve a guardar después;
`/confirmar`, `/revisar` y `/lote` leen de ahí.
**Tiene que ser la conversación y no el turno**: los resultados de tools no se persisten en
el historial, así que en el turno siguiente el modelo no tiene la ficha a la vista —
un token que tuviera que repetir de memoria no le llega, y el alta quedaba trabada en un
bucle de fichas (así falló el primer diseño). `/reset` limpia las fichas y sus fotos.

`foto` va **al lado** de los campos y no adentro: no es un campo de la entidad, y metido en
el borrador cambiaría el token —que es el hash de lo que el usuario leyó— por un dato que no
está en la ficha.

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
`buscar_profesor` marca a cada candidato con su `rol` (así lo nombra el aviso: "CALEI (EMATP
EERR)").

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

### Cuando no coincide nadie: `padron_completo`

Las búsquedas de persona **no pueden terminar en una lista vacía**. Una lista vacía el modelo la
lee como un hecho y le contesta al usuario que la persona no está en el sistema — que es
exactamente lo que "no encontré" no significa, porque `_puntaje_nombre` compara **letras**: un
apodo, un nombre dado vuelta o una errata grande no matchean.

`buscar_profesor` devolvía `[]` pelado, sin nota ni listado, y `horario_profesor` cerraba con
`"No existe ningún docente ni personal no docente llamado X ni parecido"` — una afirmación
categórica, en la única de las tres búsquedas de persona que no tenía segundo nivel. Ahora las
tres devuelven el padrón entero en la **misma respuesta**:

| tool | qué lista | tamaño |
|---|---|---|
| `buscar_profesor` (cero candidatos, cero cruces) | los 344 nombres de los horarios | ~1.670 tokens |
| `horario_profesor` (rama final, la que afirmaba que no existe) | ídem | ~1.670 tokens |
| `preceptores(preceptor=…)` sin match | los 46 de la planilla | ~210 tokens |

Tres cosas que sostienen el caso:

- **Va inline, no por una tool aparte.** Mismo criterio que `buscar_por_rol` y contrario a
  `buscar_entidad` → `listar_todos`: un round-trip extra re-procesa ~8.050 tokens de piso, así
  que pedir la lista cuesta ~5x mandarla. La diferencia con `buscar_entidad` es que acá el
  fracaso es un **binario limpio** (cero candidatos), no un "ninguno es exacto" — así que la
  rama cara no se paga nunca en un turno que encuentra algo. Ver `dev-log/DECISIONS.md`
  2026-08-12.
- **Tope `LIMITE_PADRON` (400)**, el mismo de `LIMITE_LISTADO_COMPLETO`: arriba de eso va la
  `nota` sin la lista, y el texto se adapta (`if padron else ''`). Hoy son 344 y el margen es
  chico.
- **La nota nombra el otro padrón** (`_otros_padrones`). El de horarios es uno de dos, y
  decir "no está" habiendo mirado solo éste repite el mismo error un escalón más arriba.

El guardrail es de prompt y por eso vive en tres lugares que se refuerzan, igual que el de
`listar_todos`: la `nota` de cada tool, la descripción del esquema (un campo que llega sin estar
anunciado el modelo lo ignora) y la regla de sinónimos del system prompt. Esa regla terminaba en
*"Para profesores el equivalente es `buscar_profesor`"* — un paralelismo que no existía, porque
`buscar_profesor` es el **primer** nivel. Ahora dice que el segundo llega solo.

### Los preceptores entran por su propia tool (`preceptores`)

Sus nombres siguen **fuera del padrón difuso** —están cargados sin normalizar ("ANGELINA",
"KARINA (M RIOS)", "FALTA") y ensuciarían las sugerencias de `buscar_profesor`—, pero ya no son
invisibles: `preceptores(curso?, division?, preceptor?)` los devuelve **digeridos**, que es la única
forma en que esa tabla sirve. De 595 filas crudas (curso × turno × día) salen 64 fichas, una por
curso:

- **Titular vs contraturno.** El turno en que el curso cursa sale de `config.TURNO_CURSOS`
  (fallback `TURNO_DEFAULT`), el mismo criterio que ya usa `horarios.datos.obtener_horario_preceptor()`;
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
  válidos es `horarios.datos.TURNOS`, la misma de la que salen los bloques del Sheet.
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
con `sugerencias` si empata y con `padron_completo` si no matchea nadie — igual protocolo que
`_horario_profesor_fmt`, ver "Cuando no coincide nadie"), o **nada**, que devuelve
la planilla entera (~4.000 tokens; la descripción del esquema pide usarlo solo si la pregunta es
realmente sobre todos). Los campos de turno le sumaron ~29% a ese modo — 55 de los 64 cursos tienen
algún turno vacío, así que `turnos_sin_nadie` aparece en casi todos. Se paga igual: una ficha que
cambia de forma según cómo se llamó la tool es peor que una ficha grande, y el modo caro ya está
desaconsejado en el esquema. En el modo normal (un curso) la ficha entera son ~1,6 KB.

**La división pasa por `horarios.datos._extraer_num_curso`, igual que el curso.** Las divisiones de 4°–7°
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

**`_coincide_fuerte(q_norm, nombre)`** es el filtro de los cruces laterales de horarios —el
de preceptores y el de cargos de `buscar_por_rol`—, y es más estricto que las búsquedas
normales: substring, o similitud **palabra por palabra** ≥ `UMBRAL_SIMILITUD` (0.68). No usa
el 0.6 de `_buscar_profesor_scored`, que ofrece candidatos a propósito: con 0.6 el cruce de
"nati" traía PETRATE MATIAS (0.60 contra "matias") y el de "calei" traía PRIETO VALERIA.
Tampoco alcanza con substring solo — los apodos del castellano no son prefijos: "nati" **no**
es substring de "natalia" (0.73 de similitud, sí pasa el umbral), y ése era justo el caso a
resolver.

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
9 respuestas — "Multímetro (ID 4)", una columna `ID` en la tabla de resultados).

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
vacíos). Reduce tokens de API y errores de interpretación.

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

En `recursos` cada item trae además `ubicacion`, una línea con cada lugar y cuántas unidades
hay ahí (`"Taller (4), Sin ubicar (1)"`), que sale de `gestion.lugares_por_recurso`. Es la
**segunda razón de existir de esta tool**: ninguna lectura entra por lugar (`buscar_entidad`
busca por nombre), así que "qué hay en el taller" o "movés todo lo que está en A" se contestan
leyendo esta lista — el nombre del lugar y el número entre paréntesis son el `origen` y la
`cantidad` de `mover_ubicacion`, uno por recurso y todos en la misma vuelta. La `descripcion`
de cada fila, en cambio, sólo viaja con `con_descripcion: true`: es la parte que multiplica el
costo y casi nunca hace falta. Ojo con el efecto de borde: `lugares_por_recurso` crea las
unidades que faltaban (`_asegurar_unidades`), así que esta tool de lectura **commitea** ese
backfill, igual que el listado web.

**Costo medido** (91 recursos): el listado completo son ~1.190 tokens de nombres. Sumarle la
ubicación de cada uno lo multiplica por 1,8, y pedirlo con `con_descripcion` por 2,4 (medido
en caracteres del JSON, no en tokens). El piso
que se re-procesa en **cada** round-trip de tool es ~6.420 (los esquemas de las 20 tools, sin
contar system prompt ni historial), así que un intento extra de búsqueda sigue costando
bastante más que mandar el inventario entero. Por eso se eligió esto sobre
un diccionario de sinónimos o un tier intermedio de reintentos — ver `dev-log/DECISIONS.md`
2026-08-08, que además documenta cuándo esta decisión se da vuelta (si el inventario supera
el tope).

**El guardrail vive en tres lugares que se refuerzan** — es de prompt, no de código, y con
DeepSeek (proveedor por defecto) es más frágil que con Claude:
- el `aviso` de `buscar_entidad` nombra la tool cuando la búsqueda falla;
- la `instruccion` del resultado dice "estos son TODOS; si ninguno es, decilo — no ofrezcas
  el más parecido como si fuera el correcto";
- la regla 3 del system prompt fija el orden de los tres pasos.

### Alta desde foto (datasheets, etiquetas, chapas de características)

Caso de uso central del asistente en el taller: sacan la foto de la etiqueta de un panel
solar, escriben "tenemos 5" y el recurso queda cargado sin tipear especificaciones. Y en
tandas: **hasta `FOTOS_MAX` = 10 fotos por mensaje**, una ficha por foto (ver "Cargar de a
muchas: el lote").

**Recorrido de las fotos**:
1. `gestion-agente.js` las lee con `FileReader`, las **achica en un canvas** a 1568 px de lado
   largo / JPEG calidad 0.85 —todas en paralelo, que con diez se nota— y las deja en
   `imagenesSeleccionadas` como data URLs. Sin ese paso
   una foto de celular (3–8 MB, ~11 MB en base64) no entra en el límite de la API de visión
   y tarda una eternidad por el wifi de la escuela. 1568 px es lo que el modelo llega a
   aprovechar y alcanza para leer la letra chica de un datasheet. Si el navegador no puede
   decodificar el archivo (HEIC de iPhone), se manda tal cual en vez de perder la foto.
2. `POST /chat` con `{mensaje, imagenes}`. **Las fotos solas son un mensaje válido**: si no
   escribieron nada, el front igual envía y el backend pone "Te mando esta foto." como texto.
   Si mandan más de diez, el server **recorta y avisa** en vez de rechazar el mensaje: perder
   las diez primeras por haber mandado doce es peor.
3. `_turno()` **no le manda las fotos al agente ni las lee**: las numera con
   `_fotos_lote_guardar()`, las deja en `contexto_turno['fotos_turno']` y le agrega al mensaje
   del usuario una nota diciendo cuántas hay **y con qué números**. El agente nunca ve un píxel:
   lo único que maneja de una foto es su número.
4. **El agente decide qué hacer con ellas**, y ahí se abren los caminos (ver abajo): leerlas
   con `leer_foto` si necesita los datos, o guardarlas con `adjuntar_foto` si van a una ficha
   que ya existe. Si no está claro, pregunta.
5. En el camino de alta, el modelo arma una ficha por foto con `crear_entidad(foto=N)` → fila
   de revisión. La imagen quedó en `agente_fotos_pendientes` atada al **número**, no a la
   ficha. Al aprobarla, `_adjuntar_foto_pendiente()` la pasa a la galería del registro nuevo
   con `crud.agregar_foto()` — el mismo camino que usa la subida manual desde el detalle.

#### La foto se ata al NÚMERO, no al token de la ficha

Es lo que hace posible corregir una ficha sin perder su imagen, y por lo tanto lo que hace
posible el lote entero.

Antes la foto pendiente se guardaba con el **token de la ficha** como clave, que es el SHA-1
de su contenido. Funcionaba mientras la ficha se confirmara tal cual salió: en cuanto el
usuario pedía un cambio y el modelo la rearmaba, el token era otro y **la foto quedaba
huérfana** — el recurso se creaba sin imagen y nadie se enteraba.

Ahora las fotos se numeran por conversación (`_fotos_lote_guardar()` devuelve los números) y
se guardan con clave `sid:n`. El número es lo que el modelo arrastra: `leer_foto` se lo
devuelve en cada lectura, `crear_entidad(foto=N)` lo recibe, y el prompt le insiste en volver
a mandar **el mismo** al rearmar una ficha corregida. La columna sigue llamándose `token`
—es la PK de la tabla y no hacía falta migrar nada— pero ahora guarda esa clave.

**La numeración no arranca de 1 en cada turno**: sigue desde la última foto pendiente de esa
conversación. Si arrancara de cero, mandar dos fotos nuevas con un lote a medio revisar
pisaría las de ese lote — y el modelo ya venía hablando de "la foto 2" en el historial.

El mismo número es además la **identidad de la ficha dentro del lote**: `_fusionar_fichas()`
hace que una ficha nueva con `foto: 3` reemplace a la vieja con `foto: 3`, así el usuario no
ve dos botones para la misma alta con contenidos distintos.

#### Los caminos de una foto

| El usuario quiere… | Tool | ¿Cuesta visión? |
|---|---|---|
| Guardarlas en una ficha que ya existe ("guardá estas fotos en el taladro") | `adjuntar_foto(slug, id)` — sin `foto` van todas | **No** |
| Cargar o actualizar el inventario con lo que dice la chapa de un producto | `leer_foto()` → `crear_entidad(foto=N)` / `editar_entidad` | Sí (~US$0,0004 por foto) |
| Cargar un KIT desde una página/tabla con varios ítems distintos | `leer_foto(modo='listado')` → `crear_entidad(foto=N, sub_recursos=[…])` | Sí (misma llamada, tope más alto) |
| Saber qué es o cómo está algo sin etiqueta legible | `leer_foto(modo='analisis')` | Sí (misma llamada, tope más alto) |
| No se entiende | — | No: el prompt le pide **preguntar**, no leer por las dudas |

**`leer_foto` se llama UNA VEZ para todas.** Sin el parámetro `foto` lee todas las del turno y
devuelve `{lecturas: [{foto, lectura}, …]}`. No es comodidad: el loop de tool-calling tiene un
tope de vueltas (`max_iterations`, 16) y una llamada por foto se comía el turno antes de llegar
a armar las fichas. El esquema y el prompt se lo dicen en esos términos.

**Leer es una tool, no un paso automático.** La primera versión leía toda foto al entrar a
`chat()`, y eso pagaba una llamada de visión también cuando lo único que querían era adjuntar —
que es el caso más común y el que menos la necesita: para guardar una imagen no hace falta
saber qué dice. El costo de la vuelta extra del loop es despreciable al lado de eso, porque
DeepSeek cachea el prefijo (system prompt + tools): los cache hits salen US$0,003625/M contra
US$0,435/M de un miss.

Las dos tools sacan las imágenes de `contexto_turno['fotos_turno']` (vía `_fotos_del_turno()`),
nunca de un parámetro: el modelo no ve la foto, así que pedirle el base64 sería pedirle que lo
invente. Si en el turno no vino ninguna, las dos devuelven un error que se lo explica en vez de
fallar en silencio; y un **número que no existe** se contesta listando los que sí, en vez de
fallar en seco — el número lo elige el modelo y una confusión no tiene por qué costar el turno.

`adjuntar_foto` **corre directo, sin ficha de confirmación**: es aditivo (no pisa ni borra
nada) y el listón lo marca `editar_entidad`, que sobrescribe campos y tampoco la pide. Queda
auditada en `agente_log`. `leer_foto` no se audita: no toca la base — lo que gasta es la API de
visión, no el inventario.

> **Ojo**: no hay forma de borrar una foto de una galería desde la app (`subir_foto` agrega,
> nada saca). Por eso el prompt y la descripción de `adjuntar_foto` insisten en preguntar
> cuando el destino es ambiguo: una foto en el recurso equivocado se saca editando la base.

**Por qué la foto se guarda en la DB y no en el turno**: la confirmación puede llegar después,
incluso desde otra página (el historial se repinta y los botones siguen ahí), aunque no más
tarde que el timeout de la conversación. Va en tabla propia y no dentro del JSON de `fichas`
porque esa columna se reescribe entera en cada turno: con hasta ocho fotos en base64 adentro,
cada mensaje del chat arrastraría varios MB de escritura. Las que quedan sin usar se barren a
los `CONVERSACION_MINUTOS` (240, 4 horas), al cerrar el lote (`_cerrar_lote()`, cuando ya no
queda ninguna ficha que las necesite) y con `/reset`.

#### Las fotos se ven en el chat

Las imágenes se guardan **fuera de `content`**, en la clave `imagenes` del mensaje
(lista de `{'b64', 'tipo'}`). Es la separación que importa: lo que se persiste **para
mostrar** no es lo mismo que lo que se le manda **al modelo**.

| | Dónde vive | Quién lo ve |
|---|---|---|
| Bloques `type: image` | dentro de `content` | el LLM, y **sólo en el turno en que llegaron** |
| Clave `imagenes` | al lado de `content` | el chat, para siempre |

`_sin_imagenes()` limpia lo primero antes de persistir y preserva lo segundo (`{**msg, ...}`),
igual que `_foto_en_pasado()`. Y `_turno()` le pasa al LLM `[{'role', 'content'}]` recortado,
así que la clave `imagenes` **nunca** viaja a la API: el costo que motivó el diseño original —
reenviar ~1.700 tokens por foto en cada turno siguiente— sigue sin pagarse. Lo que cambia es
sólo la fila de SQLite, que es el mismo patrón que ya usa la galería de un recurso
(`crud.agregar_foto`) y está acotado por `HISTORIAL_GUARDADO`: al rotar el historial las
fotos viejas se van solas.

Del lado del front, `agregarMensaje(texto, tipo, imagenes)` pinta cada miniatura dentro de un
`<a target="_blank">` (click → foto entera) y el texto debajo. Antes de esto la burbuja decía
`📷 nombre-del-archivo.jpg` y la foto no se veía nunca. **Con varias van en grilla y
numeradas** (`.agente-message-fotos.is-multiple`): el asistente las nombra por número ("la 3
no se lee"), así que sin el número visible no hay forma de saber a cuál se refiere.

`_mensaje_visible()` sigue leyendo la clave `imagen` **singular** de las conversaciones
anteriores al lote, para que no queden mensajes mancos al repintar un historial viejo.

**Lo que el usuario no escribió no se muestra**: `_texto_visible()` corta el aviso de fotos
entero (con las lecturas de las etiquetas pegadas, si las hubo), `TEXTO_FOTO_SOLA` —el
"Te mando esta foto." que `chat()` inventa cuando mandan una imagen sin texto, porque un
mensaje vacío no es un turno válido para el modelo— y el mensaje que arma `/lote`
(`MARCA_LOTE`). Una foto sola queda como una foto sola.
Por eso `historial()` filtra por `texto or imagenes` y no sólo por `texto`: si filtrara por
texto, ese mensaje desaparecería del chat.

#### La foto no vuelve a aparecer arriba, pero se puede releer por número

**Son dos avisos, no uno**, y esto es lo que hace que un alta se pueda terminar en el turno
siguiente:

| Función | Cuándo | Qué dice |
|---|---|---|
| `_aviso_foto_actual(numeros)` | Durante el turno, con las imágenes en `contexto_turno` | "hay N fotos, numeradas X, Y, Z, todavía no las vio nadie, llamá a `leer_foto` UNA vez" |
| `_aviso_foto_vieja(numeros, lecturas)` | Al **persistir**, vía `_foto_en_pasado()` | "esas fotos ya no están arriba, pero seguís pudiendo llamar a `leer_foto`/`adjuntar_foto` con su NÚMERO" + **las lecturas completas**, si las hubo |

El aviso en presente quedaba guardado tal cual, y en el turno siguiente el modelo leía "hay
una foto sin ver, llamá a `leer_foto`" como si la tuviera arriba del mensaje. Por eso el
segundo aviso reemplaza al primero al persistir: aclara que ya no está en el mensaje, pero
que el NÚMERO se puede seguir pasando.

**La foto en sí sobrevive a su turno.** `agente_fotos_pendientes` la guarda por conversación
(`sid:n`), no por turno, y `_fotos_del_turno()` (en `agente/tools/fotos.py`) cae a esa tabla
cuando piden un número puntual (`foto=N`) que no es de este turno. Así que `leer_foto` y
`adjuntar_foto` siguen funcionando sobre una foto de varios mensajes atrás, mientras la
conversación no haya vencido (`CONVERSACION_MINUTOS`) y nadie la haya confirmado/descartado
ya (`_soltar_foto`/`_cerrar_lote` la liberan en ese momento). Sin un número explícito
(`leer_foto()` a secas) sigue mirando SOLO las de este turno — no hay relectura automática
del historial completo.

Son **funciones y no constantes** desde el lote: el texto lleva los números de las fotos de
ese turno. Por eso `_foto_en_pasado()` recibe el aviso que se armó, en vez de mirar una
constante global — tiene que reemplazar exactamente ese string.

**Y la lectura se persiste.** `_leer_foto_fmt()` deja las lecturas numeradas en
`contexto_turno['lectura_foto']` y `_turno()` las pega al mensaje guardado. Hacía falta porque
**los resultados de las tools no quedan en el historial**: sin esto, lo único que sobrevivía
de la etiqueta era lo que el modelo hubiera repetido en su prosa, y al turno siguiente se
quedaba sin marca, sin modelo y sin specs para armar la ficha. Con el lote pasó a ser todavía
más importante: la segunda vuelta de correcciones ocurre cuando las fotos ya no están, y el
modelo rearma esas fichas **sólo** con lo que quedó escrito acá.

`_texto_visible()` corta desde cualquiera de los dos avisos hasta el final del mensaje, así
que la lectura pegada tampoco se le muestra al usuario como si la hubiera escrito él.

**Reglas en el system prompt** (sección "FOTOS DE DATASHEETS…"): el agente trabaja **solo con
lo que dice la lectura**, nunca completando con lo que sabe de esa marca/modelo; la cantidad
no sale nunca de la foto sino de lo que dice el usuario (si no la dijo, se pregunta antes de
la ficha); la ubicación de un recurso sí va en la ficha de alta (parámetro `ubicacion` de
`crear_entidad` → pseudo-campo `_lugar` del borrador; al confirmar se aplica con `mover_unidades`
sobre todas las unidades del recurso nuevo), pero mover un recurso que **ya existe** sigue siendo
sólo `mover_ubicacion`;
cinco unidades iguales son **un** recurso con `cantidad` 5,
no cinco altas; antes de la ficha se busca por marca/modelo y por nombre genérico, porque con
una foto lo más común es que el recurso ya exista y corresponda sumar stock con
`editar_entidad`; las especificaciones van en `descripcion`, no amontonadas en el `nombre`.
Si la lectura describe algo que no es la chapa de un producto (una máquina entera, un tablero),
se cuenta qué se ve y se pregunta qué hacer, no se da de alta sola. Una página o tabla con
varios ítems (una lista de materiales, el contenido de un kit) no cae acá: para eso está el
modo `listado` (ver abajo), no `etiqueta` — con `etiqueta` esa clase de foto se leía como "no es
una etiqueta" y sólo se describía en una frase, sin transcribir la lista.

#### El lector de imágenes (`_get_vision_config`, `_leer_imagen`)

Config **aparte de la del chat**: `AGENTE_VISION_API_KEY` (fallback `GEMINI_API_KEY`),
`AGENTE_VISION_MODEL` (default `gemini-3.5-flash-lite`), `AGENTE_VISION_API_BASE` (default
el endpoint OpenAI-compatible de Google). Sin API key, `_get_vision_config()` devuelve `None`
= no hay lector.

Es una llamada suelta, **sin tools**. Todo lo que viene *después* de leer —cantidad, buscar
duplicados, circuito de ficha— sigue en el system prompt del agente, que es quien tiene las
tools. **Solo se dispara desde la tool `leer_foto`**: nunca automáticamente al llegar una foto.

**Tres modos, que son tres prompts sobre la misma llamada y el mismo modelo** (`MODOS` en
`vision.py`, elegidos con el parámetro `modo` de `leer_foto`):

| Modo | Prompt | `max_tokens` | Para qué |
|---|---|---|---|
| `etiqueta` (default) | `PROMPT_LECTOR_IMAGEN` | 500 | Transcribir la chapa de UN producto. Es el que alimenta el alta simple |
| `listado` | `PROMPT_LISTADO_IMAGEN` | 1600 | Transcribir una página/tabla con VARIOS ítems distintos, uno por renglón. Alimenta el alta de un kit vía `sub_recursos` (ver "CARGAR UN KIT DESDE UNA LISTA" en `prompt.py`) |
| `analisis` | `PROMPT_ANALISIS_IMAGEN` | 900 | Describir qué objeto es, su estado visible y cuántos hay |

Los tres comparten las mismas anclas —solo lo que se ve, la duda explícita, nunca completar con
lo que el modelo sepa del producto— pero **se mantienen separados a propósito**: en `etiqueta` y
`listado` la regla "quedate corto antes que inventar" es lo que hace confiable el alta, y un
prompt que además pidiera describir le abriría la puerta a completar de memoria. `listado` tiene
un `max_tokens` más alto porque una tabla de veinte ítems no entra en el tope pensado para la
chapa de un solo producto. Un `modo` desconocido cae al default en vez de fallar: lo elige el
modelo, y una alucinación en el nombre del modo no tiene por qué costar la foto.

**Tener dos modos no relaja el gate**: `leer_foto` se sigue llamando solo cuando hace falta la
imagen, una vez por foto. El prompt le prohíbe explícitamente probar los dos modos a ver cuál
sale mejor — cada llamada cuesta igual.

**Una descripción no es un alta.** El resultado de `analisis` vuelve con una `instruccion`
distinta a la de `etiqueta`: sirve para contestar qué es o cómo está algo, no para llenar una
ficha (ahí no hay marca ni modelo confiables). Si el usuario quiere cargarlo igual, el prompt
le pide una foto de la etiqueta o los datos dictados.

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

**Las dos ramas de `_turno()`**:
1. El chat ve imágenes (`_get_config()['vision']`: Anthropic siempre, el resto con
   `AGENTE_VISION=1`) **y no hay lector aparte** → un bloque `image` por foto viaja al agente y
   `_mensajes_openai(..., vision=True)` los traduce a `image_url` si el proveedor es
   OpenAI-compatible. Es el único caso donde el que razona mira las fotos, así que acá
   `leer_foto` no hace falta.
2. En cualquier otro caso —haya lector o no— las fotos quedan en
   `contexto_turno['fotos_turno']` (con su número) y el mensaje del usuario lleva una nota
   diciendo cuántas hay y cuáles son. **No se leen acá**: decide el modelo. Anda con cualquier
   `AGENTE_PROVIDER`.

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
una edición o un borrado.

### Otras tablas del agente en `gestion.db`

```sql
agente_conversaciones (sid PK, actualizado, historial JSON, entidad_actual, fichas JSON)
agente_fotos_pendientes (token PK, sid, b64, tipo, fecha)
```

`agente_conversaciones`: una fila por navegador. La conversación vive acá y no en la cookie
de Flask porque el historial la pasaba de los ~4 KB que aguanta un navegador y la cookie se
descartaba **sin avisar**, dejando al usuario deslogueado y sin conversación. En la cookie
queda solo `agente_sid`. Los mensajes que traían fotos las guardan en su clave `imagenes`
(lista de `{'b64', 'tipo'}`), fuera de `content` — ver "Las fotos se ven en el chat". La
columna `fichas` guarda las altas sin confirmar **con su estado de revisión** (ver "Cargar de
a muchas: el lote").

`agente_fotos_pendientes`: las fotos del lote, esperando que se apruebe la ficha que las
usa (ver "Alta desde foto"). La clave (columna `token`) es **`sid:n`**, el número de la foto
dentro de la conversación — no el turno, porque la confirmación puede llegar desde otra
página o mucho después, y no el token de la ficha, porque ese cambia en cuanto la ficha se
rearma con una corrección. Ver "La foto se ata al NÚMERO, no al token de la ficha".

Las dos se barren a los `CONVERSACION_MINUTOS` (240, 4 horas) de inactividad: al leer (si la fila
está vencida, `_conv_cargar`/`_foto_lote_tomar` la tratan como si no existiera) y también en la
misma escritura que las usa — no en `init_db()`, porque el server puede estar meses sin
reiniciar.

### Registro de uso y de chats (`agente.db`)

`registro.py`, DB **propia** — no `gestion.db`, porque las tablas de arriba son efímeras y
ésta crece sin techo: dentro de `gestion.db` se la llevarían los 20 respaldos rotativos.
No tiene respaldo propio (es telemetría); `actualizar.py` sí le hace la copia del deploy.

```sql
agente_turnos (
  id, fecha, sid, acceso_tipo, acceso_id, acceso_nombre, origen,
  provider, modelo, vueltas, tokens_entrada, tokens_salida, tokens_cache,
  vision_llamadas, vision_modelo, vision_entrada, vision_salida,
  ms, pico, fotos, tools JSON, estado, detalle_error, escritura_fantasma,
  pregunta, respuesta
)
```

Una fila por turno, **para siempre**, con el texto completo de la pregunta y la respuesta:
el material para corregir el prompt y las tools es el histórico. `sid` es el mismo de
`agente_conversaciones`, así que un chat se reconstruye con `WHERE sid=? ORDER BY id` aunque
la conversación ya se haya barrido. `acceso_id` apunta a `dispositivos.id` de `accesos.db`
pero es un entero suelto, **sin FK** (ninguna cruza de una DB a otra); por eso se copia
`acceso_nombre`, que el dispositivo se renombra o se revoca y el registro tiene que seguir
diciendo quién era.

Se escribe en `_turno_stream`, pegado a `_conv_guardar`: es el embudo por el que pasan
`/chat`, `/chat/stream` y `/lote` (`origen` los distingue), y el único punto donde el turno
está cerrado y todavía hay request context. Todo el registro va bajo `try`, dos veces
(`_registrar_uso` y `registrar_turno`): **medir no puede voltear el chat**.

Los tokens salen por `contexto_turno['uso']`, que `llm._uso` llena con **una entrada por
vuelta** del loop de tool-calling — hay que sumarlas, no quedarse con la última. `_uso`
normaliza las tres formas de `usage` que existen (DeepSeek pone la cache suelta, OpenAI la
anida en `prompt_tokens_details`, Anthropic tiene la suya) y devuelve ceros si el proveedor
no la manda. El lector de fotos se mide aparte, por `contexto_turno['uso_vision']`
(`vision._leer_imagen(uso=...)`): es otra API, con otra cuenta y otro precio.

`estado` distingue los finales del loop —`ok`, `error`, `sin_tokens`, `tope_iteraciones`,
`tope_salida`, `sin_respuesta`— y lo setea `llm.py` en cada `return`. Sin eso, el turno que
muere por cuota (el que más interesa contar) no dejaba rastro.

**Precios y costo.** `proveedores.PRECIOS` (USD por millón de tokens) + `costo()`. Se aplica
**al mostrar**, nunca se guarda: corregir un precio arregla el histórico entero. Un modelo
que no está en la tabla no inventa un número — suma aparte y el panel lo muestra como
"+N sin tarifa". `cache` se cobra a su tarifa (en DeepSeek, 30× más barata), y `pico` se
guarda **en la fila** porque DeepSeek cobra el doble en su franja pico (01-04 y 06-10 UTC,
lun-vie) y en un total agrupado por día ya no hay hora que mirar.

**`GET /agente/uso`** (`agente.auditar`, verbo `admin` → sólo administración): totales de
hoy / últimos 30 días / histórico, desglose por día, por dispositivo y por modelo, la lista
de conversaciones y los últimos 60 turnos con su texto. `?sid=` muestra una conversación
entera en orden — es cómo se pasa de "este turno salió mal" a "qué venía pasando antes".

### Guardias de seguridad / guardrails de prompt

- **No hay tool que elimine una entidad**: un recurso no se borra nunca, sale del inventario
  dándolo de baja desde la web (ver `agent_docs/gestion-conocimiento.md`). El *system prompt*
  se lo dice así al agente cuando le piden "borrar algo", en vez de dejarlo inventar un
  camino que no existe.
- **Confirmación de alta con ficha**: el alta **no** depende del
  prompt — `crear_entidad` no escribe hasta que el hash de la ficha coincida con uno mostrado
  en un turno anterior (ver "Alta con ficha de confirmación"). Vale también para las altas
  desde foto: la foto llena la ficha, no la base.
- **Resolución de ambigüedad en recursos**: si `mover_ubicacion` busca un nombre de recurso
  que matchea más de una fila, la tool devuelve `ok:false` con `opciones` (id + nombre de cada
  candidato) en vez de adivinar. El system prompt instruye a mostrarle esas opciones al usuario
  y preguntar, nunca elegir por su cuenta ni reintentar adivinando.

### Configuración

- **Env var** `AGENTE_PROVIDER` — `deepseek` (default) | `anthropic` | `groq` | `openai` |
  `ollama`. Define también qué loop de tool-calling corre: Anthropic tiene el suyo, el resto
  comparte `_loop_openai`.
- **Env var** de API key — `AGENTE_API_KEY`, o la del proveedor (`DEEPSEEK_API_KEY`,
  `ANTHROPIC_API_KEY`, `GROQ_API_KEY`, `OPENAI_API_KEY`). Sin ella el chat devuelve un error
  claro en vez de fallar en silencio. Ollama no la usa.
- **Env var** `AGENTE_MODEL` — modelo a usar. Defaults por proveedor: `deepseek-v4-pro`,
  `claude-haiku-4-5-20251001`, `mixtral-8x7b-32768`, `gpt-3.5-turbo`, `mistral`.
- **`llm.MAX_TOKENS_SALIDA` = 16000** — tope de salida por vuelta del loop, en los dos loops.
  **No lo bajes.** El default es un modelo de razonamiento (`deepseek-v4-pro`) y ese
  razonamiento se cobra como tokens de salida: medido, gasta 700–1600 antes de emitir la
  primera tool call. Estuvo en 1024 y el síntoma era **"Sin respuesta"** — `finish_reason`
  volvía `'length'` con el contenido vacío y el loop lo traducía a ese literal. Después subió
  a 4096, pero el prompt le pide mandar TODAS las `crear_entidad` de un lote de fotos en la
  MISMA vuelta (ver "Cargar de a muchas: el lote"), y con varias fotos (probado con 5) el
  razonamiento más varias tool calls completas volvía a pasarse del tope. Cuando se corta,
  `_loop_openai` distingue el caso (`finish_reason == 'length'` sin tool_calls ni texto) y
  devuelve un aviso legible en vez de "Sin respuesta". No es un tope de costo: solo se paga
  lo generado.
- **Env var** `AGENTE_VISION` — `1` para declarar que el modelo del **chat** lee imágenes.
  Anthropic ya viene en `1`; esto es para gpt-4o u ollama+llava, donde depende del modelo.
  Solo se consulta si **no** hay lector configurado (rama 2 de `chat()`).
- **Env vars del lector de fotos**, independientes de todo lo anterior:
  `AGENTE_VISION_API_KEY` (fallback `GEMINI_API_KEY`) — sin ella no hay lectura de etiquetas;
  `AGENTE_VISION_MODEL` (default `gemini-3.5-flash-lite`);
  `AGENTE_VISION_API_BASE` (default el endpoint OpenAI-compatible de Google). Con la key
  puesta, el alta desde foto anda con **cualquier** `AGENTE_PROVIDER`, incluido el default.
- **Env var** `AGENTE_API_BASE` — para APIs custom (Ollama, self-hosted).
- **Costo**: cada mensaje del chat arrastra el system prompt + los esquemas de las tools, ~10.000
  tokens de entrada, tenga foto o no — eso domina la factura, no las respuestas. **Un acceso de
  solo consulta paga bastante menos**: menos de 10 esquemas en vez de 20, y un prompt más corto
  (sin el circuito de alta ni el bloque de fotos). Por eso el lector de
  fotos va aparte (~2.000 tokens por foto) en vez de mandarle la imagen al agente. Las
  lecturas (búsquedas, horarios) agregan poco (~100–500 tokens); las escrituras
  (create/edit) más, porque la salida de la tool vuelve a entrar al modelo. El
  lector en su default (Gemini Flash-Lite) entra en el tier gratuito de 1.000 requests/día.

### La columna de nombre no siempre se llama `nombre`

Hoy `recursos` es la única entidad y su columna de nombre se llama `nombre`, pero el circuito
de alta no lo asume: valida `crud.campo_nombre(cfg)` de la entidad, no el string `'nombre'`
a mano, precisamente para que una entidad de dominio futura con otra columna (como fue
`hitos`, que la llamaba `titulo`, antes de que `/historia` se extrajera del código) entre sin
tocar `_crear_entidad`, `_nombre_de` ni las lecturas (`crud.select()`, que arma el alias).

### Claves de `relaciones` en `detalle_entidad`

`_detalle_entidad_fmt` arma `resultado['relaciones']` desde
`modulo.secciones_detalle()`, y **la clave que elige cambia lo que el modelo entiende**:

- Si el `slug` de la sección es una entidad real (está en `modulo.ENTIDADES`), la clave **es
  el slug**: así el modelo puede pasarla tal cual a `buscar_entidad` / `detalle_entidad`.
- Si no lo es, manda el **título** (hoy, sólo `"Ubicación"` en recursos: el desglose por
  lugar no es una entidad y no tiene id que pasarle a ninguna tool).

Regla general, con un bug real de origen (2026-08-11: una sección de préstamos usaba un slug
que no era una entidad de verdad, y el historial completo le llegaba al modelo indistinguible
de "lo que está afuera ahora" — ver `dev-log/DECISIONS.md`): **una clave que el modelo lee
como prosa no puede depender de un detalle de routing.**

### Integración con los módulos de dominio

- Reusa `ENTIDADES` de `gestion.py` (config declarativa), resuelto por `_modulo(slug)` — que
  queda como función (no `gestion` directo) para que un área de dominio nueva entre sin tocar
  `tools/`.
- **Toda la lectura/escritura genérica pasa por `crud.py`** (capa 1), con el área como primer
  argumento: `crud.conectar`, `crud.buscar_entidad`, `crud.guardar_entidad`,
  `crud.snapshot_entidad`, `crud.agregar_relacion_m2m`, `crud.quitar_relacion_m2m`,
  `crud.agregar_foto`, `crud.select`, `crud.campo_nombre`. Del módulo de área sólo se leen
  `ENTIDADES`, `LIMPIEZA_M2M` y el hook `secciones_detalle`. **Un área nueva tiene que cumplir el
  contrato de `agent_docs/crud-motor.md`** para que el agente la vea.
- De `gestion.py` (y solo de ahí) salen además `_stock`, `_int` y `FORMATO_FECHA_REVISION`. El
  desglose de recursos por unidad (`mover_unidades`, `lugares_recurso_agrupado`) es exclusivo
  del área de recursos y no pasa por el motor.
- **`texto.norm` / `texto.puntaje_busqueda` / `texto.UMBRAL_SIMILITUD`** son la única fuente de
  normalización y búsqueda difusa del archivo, para las dos fuentes de datos (horarios y
  gestión).
- Reusan queries de `horarios/datos.py`: `aulas_libres()` (calcula libres vs ocupadas en `clases` a
  tiempo real, agrupadas por piso de `FLOOR_MAPPING`) y la familia `ocupacion_curso` /
  `ocupacion_profesor` / `ocupacion_no_docente` / `ocupacion_preceptor`, que devuelven todas
  `{dia: [(inicio_min, fin_min, etiqueta, grupo)]}` — mismo shape para las tres tablas, ya limpio
  de días torcidos y horas rotas, para que `coincidencias` las cruce sin saber de dónde salió
  cada una. `grupo` sólo lo llena `ocupacion_curso`: ahí es media división, y para un docente o
  un preceptor no significa nada.
- El agente **no tiene acceso a escribir en `escuela.db`** (horarios) — solo lectura;
  actualizar desde Sheets sigue siendo un botón aparte del SPA.
