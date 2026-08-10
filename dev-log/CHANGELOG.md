# Changelog — AppMitre

Registra cambios que afectan contratos entre módulos (API, schema de DB, nombres de campos, estructura de `window.APP_DATA`). No registrar fixes menores de estilo o bugs internos.

---

## [2026-08-10] — `POST /agente/chat` con foto ya no corta el turno cuando no hay lector de imágenes

**Tipo**: cambio de comportamiento de un endpoint (misma forma de request y de response) + error nuevo de una tool
**Archivos**: `agente.py`, `agent_docs/agente-asistente.md`

**Contexto**: `chat()` tenía tres ramas para decidir qué hacer con una foto adjunta. La tercera —sin lector (`AGENTE_VISION_API_KEY`) **y** sin chat con visión— respondía un `AVISO_SIN_VISION` fijo **sin llegar a llamar al modelo**. Con el default del proyecto (`AGENTE_PROVIDER=deepseek`, sin key de visión) esa era la rama de *toda* foto: mandar una imagen al agente no servía para nada.

**Cambio de contrato:**

- **Con foto y sin visión, `/agente/chat` ahora ejecuta el turno completo** (llama al LLM, puede correr tools y devolver `tools` no vacío) en vez de devolver una respuesta fija con `tools: []`. La forma del request y de la response no cambió; sí cambia lo que un cliente puede esperar del turno, y que ese turno ahora **puede escribir en la base** (`adjuntar_foto`).
- **`adjuntar_foto` pasa a ser alcanzable sin ninguna API key de visión.** Guardar una foto en la galería de un registro nunca necesitó verla: el base64 va de `contexto_turno['foto_turno']` a `gestion.agregar_foto()` sin pasar por el modelo. Por lo mismo, el alta con foto pendiente (`agente_fotos_pendientes` → `_adjuntar_foto_pendiente` al confirmar) también funciona sin lector.
- **`leer_foto` devuelve un error nuevo** cuando `_get_vision_config()` es `None`: "no hay lector configurado", distinto del ya existente "el lector no respondió". Antes los dos caían en el mismo texto porque `_leer_imagen()` devuelve `None` en ambos casos. La tool **sigue en `TOOLS_SCHEMA` aunque no haya lector**: es lo que le permite al modelo detectar que le pidieron *analizar* y decirlo.
- **Se eliminó la constante `AVISO_SIN_VISION`.** Quien dependiera de ese texto exacto en la respuesta ya no lo recibe: el aviso ahora lo redacta el modelo.

**Rama que sí se conserva**: si el proveedor del chat ve imágenes (`AGENTE_PROVIDER=anthropic` o `AGENTE_VISION=1`) y no hay lector aparte, la imagen sigue viajando inline como bloque `image`.

---

## [2026-08-10] — La app se parte en 4 áreas físicas: `/historia` nuevo, `/agente` mudado, `proyectos` eliminado

**Tipo**: DB nueva + tablas movidas y eliminadas + prefijos de URL cambiados + templates movidos + entidad eliminada
**Archivos**: `historia.py` (nuevo), `gestion.py`, `agente.py`, `app.py`, `static/gestion-agente.js`, `templates/historia/` (nuevo), `templates/agente/` (nuevo), `templates/gestion/base.html`, `templates/gestion/home.html`, `init_historia.py` (nuevo), `agent_docs/*`

**Cambios que rompen contratos:**

- **`historia.db` es una DB nueva.** `hitos`, `personas` y `persona_hitos` **se movieron** de `gestion.db` a `historia.db` (mismo schema, ids preservados) y se borraron del origen. Cualquier query que las buscara en `gestion.db` ahora falla con `no such table`. `gestion.db` conserva recursos/conjuntos/actividades/préstamos **y** las tablas del agente (`agente_log`, `agente_conversaciones`, `agente_fotos_pendientes`), que no se movieron.
- **La entidad `proyectos` ya no existe.** Se eliminaron las tablas `proyectos`, `proyecto_recursos` y `persona_proyectos`. Las filas se migraron a `hitos` con `'Proyecto'` en `etiquetas` (el `estado` del proyecto quedó anexado a `descripcion`, `participantes` → `protagonistas`), y los vínculos de `persona_proyectos` se recrearon como `persona_hitos`. **No queda ninguna relación M2M que cruce las dos DBs.**
- **`/gestion/agente/*` → `/agente/*`.** Cambió el `url_prefix` del blueprint. Los cuatro `fetch` hardcodeados de `static/gestion-agente.js` se actualizaron (`/agente/chat`, `/agente/historial`, `/agente/confirmar`, `/agente/reset`). Cualquier link o bookmark a `/gestion/agente/` da 404.
- **`/gestion/proyectos`, `/gestion/hitos` y `/gestion/personas` dan 404.** Hitos y personas viven ahora en `/historia/hitos` y `/historia/personas`, con las mismas rutas bajo el nuevo prefijo.
- **Templates del agente movidos** de `templates/gestion/` a `templates/agente/` (`agente_chat.html`, `agente_log.html`, `_agente_chat_core.html`, `_agente_widget.html`), más `base.html` y `login.html` nuevos. `gestion/base.html` e `historia/base.html` incluyen el widget desde la ruta nueva.
- **`agente.SLUGS_ENTIDAD = list(gestion.ENTIDADES) + list(historia.ENTIDADES)`** y **`_modulo(slug)`** nuevo: todas las tools genéricas resuelven contra el módulo dueño del slug. Consecuencia para quien agregue un módulo de dominio: tiene que exponer la misma superficie (`ENTIDADES`, `conectar`, `_select`, `_campo_nombre`, `LIMPIEZA_M2M`, `buscar_entidad_sin_request`, `guardar_entidad_sin_request`, `snapshot_entidad`, `agregar_relacion_m2m`, `quitar_relacion_m2m`, `_secciones_detalle`, `agregar_foto`).
- **Cada área tiene su propio login**: `/gestion/login`, `/historia/login`, `/agente/login`. Comparten `GESTION_CLAVE` y `session['gestion_ok']` (una contraseña abre las tres), pero ningún módulo importa el gate del otro. `agente._contexto_base()` dejó de delegar en `gestion._contexto_base()`.
- **Esquemas de tools**: `crear_entidad`/`editar_entidad` ya no aceptan `participantes`, y el enum de `estado` perdió los valores de proyecto (`Activo`/`Pausado`/`Terminado`). `fecha` ahora es solo de hitos.

**Fixes que venían de arrastre** (aparecieron al verificar el agente contra `hitos`):
- `_listar_todos_fmt` hacía `SELECT id, nombre` → reventaba con `no such column: nombre` en hitos. Ahora usa el alias de `_campo_nombre`.
- `_detalle_entidad_fmt` hacía `SELECT *` → la ficha de un hito llegaba sin la clave `nombre` que el modelo lee en todos los slugs. Ahora usa `_select()`.

**Migración**: se corrió una vez con `migrar_proyecto_a_hito.py` (script de un solo uso, borrado después — está en el historial de git). Respaldos previos en `backups/`.

---

## [2026-08-09] — Buscar una persona mira los dos padrones (fichas + horarios), en las dos direcciones

**Tipo**: cambio de forma en la respuesta de dos tools de lectura (condicional) + funciones nuevas en `agente.py`
**Archivos**: `agente.py`, `agent_docs/gestion-conocimiento.md`, `dev-log/DECISIONS.md`
**Contexto**: son **dos padrones que no se superponen** — los docentes salen de `escuela.db` (horarios) y las fichas de `personas` de `gestion.db`. Ante "nati fue quien lo logró" el agente ofrecía tres docentes llamadas Natalia mientras "Natalia Boo Fiad" estaba cargada con ficha; y al revés, buscar a una docente en `personas` devolvía vacío y el agente concluía "no la tengo".
**Cambios**:
- **`buscar_profesor` puede devolver un dict en vez de una lista.** Si el query también coincide con una fila de `personas`, pasa de `[{nombre}, …]` a `{docentes: [{nombre}, …], personas_con_ficha: [{id, nombre}, …], aviso: str}`. Único consumidor: el dispatcher de `ejecutar_tool`, que solo la serializa a JSON.
- **`buscar_entidad` con `slug='personas'` puede sumar `en_horarios: [nombre, …]` y `aviso_horarios`.** Las claves de siempre (`slug`, `query`, `total`, `resultados`, `aviso`) no cambian. Cuando no hay ficha pero sí docentes, el aviso le prohíbe explícitamente responder "no la tengo" y le ofrece dos salidas: resolver el horario con ese nombre, o proponer crear la ficha.
- Las dos solo agregan la clave **cuando hay coincidencia real**, así que los turnos normales de horarios y de inventario no cambian ni suman ruido.
- **Funciones nuevas**: `_coincide_fuerte(q_norm, nombre)` (filtro de los cruces: substring o similitud palabra por palabra ≥ `gestion.UMBRAL_SIMILITUD`, más estricto que el 0.6 de `_buscar_profesor_scored`), `_personas_parecidas(query)` y `_docentes_parecidos(query)`. `_personas_nombradas_en()` no cambia: sigue exigiendo nombre completo y sigue siendo la única que decide los vínculos `persona_hitos` reales.
- **`_recordatorio_hito()`**: cuando `protagonistas` está vacío y no hubo match por nombre completo, el aviso ahora lista el padrón de personas con ficha (tope `PADRON_EN_AVISO` = 40; más que eso lo deriva a `buscar_entidad`).
- **Constante nueva** `PADRON_EN_AVISO = 40`.

---

## [2026-08-09] — Los hitos se llevan a su gente: `hitos.rel_personas` + vínculo automático al confirmar

**Tipo**: relación M2M nueva declarada en `gestion.ENTIDADES` (campo nuevo en el form y en el detalle de hitos) + clave nueva en la respuesta de `crear_entidad` + efecto nuevo de `POST /gestion/agente/confirmar`
**Archivos**: `gestion.py`, `agente.py`, `agent_docs/gestion-conocimiento.md`, `dev-log/DECISIONS.md`
**Cambios**:
- **`hitos` declara `rel_personas`** (`{campo: 'rel_personas', tabla: 'persona_hitos', col_propia: 'hito_id', col_ajena: 'persona_id', slug_ajeno: 'personas'}`), espejo de `personas.rel_hitos` sobre la **misma tabla**. Es la única relación simétrica del sistema. Consecuencias hacia afuera:
  - El formulario de alta/edición de `/gestion/hitos` gana un multi-select "Personas con ficha", y la ficha de detalle del hito lista a su gente. Antes el vínculo solo se veía desde la persona.
  - **`vincular_entidad` / `desvincular_entidad` ahora aceptan `hitos → personas`**, que antes devolvía `No hay relación entre hitos y personas`. Su descripción ya no dice que con personas el origen es *siempre* la persona: eso sigue valiendo para `proyectos` y ya no para `hitos`.
  - Sin riesgo para el agente: `guardar_entidad_sin_request` solo toca la M2M `if campo in campos_dict`, y ni `_crear_entidad` ni `_editar_entidad` mandan claves `rel_*`.
- **`crear_entidad` puede devolver `antes_de_mostrar: [str, …]`** cuando el slug es `hitos` y la ficha viene con `protagonistas`, `nivel`, `fecha` o `tipo` vacíos (`_recordatorio_hito()`). Son instrucciones para el modelo, no texto para el usuario: el prompt le manda resolverlas y volver a llamar antes de contestar. Si `protagonistas` está vacío, el aviso **nombra a las personas ya cargadas que aparecen en el título/descripción**.
- **`POST /gestion/agente/confirmar` ahora escribe en `persona_hitos`** al guardar un hito: cruza `protagonistas` contra `personas` (`_personas_nombradas_en()`, match por nombre completo normalizado, cualquier orden) y vincula los que existan. La respuesta suma " Lo vinculé con la ficha de X." — el front ya pinta ese texto tal cual. **Es el único momento posible**: el botón no pasa por el LLM, así que el agente no tiene turno para llamar a `vincular_entidad` cuando el hito se crea.
- **Funciones nuevas en `agente.py`**: `_personas_cargadas()`, `_personas_nombradas_en(texto)`, `_recordatorio_hito(borrador)`, `_enlazar_protagonistas(hito_id, protagonistas)`.

---

## [2026-08-09] — Un botón de confirmar por ficha: `confirmacion` → `confirmaciones` (lista)

**Tipo**: cambio incompatible en la respuesta JSON de dos endpoints del agente + campos nuevos en los esquemas de `crear_entidad` / `editar_entidad`
**Archivos**: `agente.py`, `static/gestion-agente.js`, `agent_docs/gestion-conocimiento.md`, `dev-log/DECISIONS.md`
**Cambios**:
- **`POST /gestion/agente/chat` y `GET /gestion/agente/historial` devuelven `confirmaciones: [{token, etiqueta, nombre}, …]`** en vez de `confirmacion: {…} | null`. Es incompatible: la clave vieja ya no existe y quien la lea recibe `undefined`. El único consumidor es `gestion-agente.js`, actualizado en el mismo commit (`agregarConfirmacion()` → `agregarConfirmaciones(lista)`).
  - La lista trae **todas las fichas pendientes**, no solo las del turno en curso, y viene deduplicada por entidad (`slug` + nombre normalizado): si el modelo rearmó una ficha porque el usuario pidió un cambio, gana la última.
  - Motivo: un turno puede armar varias fichas ("creá a Pablo y a Ezequiel") y se mandaba solo la última. Las otras quedaban vivas en `agente_conversaciones.fichas` **sin ningún botón que las guardara**, así que se perdían sin que nada avisara.
- **`crear_entidad` acepta `titulo`, `nivel`, `etiquetas` y `protagonistas`**, y `fecha` pasa a valer para proyectos **e** hitos. `required` baja de `['slug', 'nombre']` a `['slug']`: cuál de los dos campos de nombre hace falta lo decide `_crear_entidad` contra `gestion._campo_nombre`. Sin esto **ninguna alta de hito podía completarse** — el modelo no tenía forma de mandar `titulo` y el servidor lo exigía. `editar_entidad` recibe los mismos campos.
- **`/confirmar` cambia el texto que deja en el historial**: `(confirmé el alta con el botón)` → `(confirmé con el botón el alta de: <nombre>)`, y la respuesta suma "Quedan N sin confirmar." cuando corresponde. Con varios botones a la vez, la línea genérica no le decía al modelo cuál se guardó.

---

## [2026-08-09] — Lector de fotos aparte del chat + la foto queda en la ficha del recurso

**Tipo**: tabla nueva en `gestion.db` + env vars nuevas + función pública nueva en `gestion.py` + cambio en lo que se persiste del mensaje del usuario
**Archivos**: `agente.py`, `gestion.py`, `requirements.txt`, `AGENTE_CONFIG.md`, `agent_docs/gestion-conocimiento.md`, `dev-log/DECISIONS.md`
**Cambios**:
- **Tabla nueva** `agente_fotos_pendientes (token PK, sid, b64, tipo, fecha)`. Guarda la foto de la que salió una ficha hasta que el usuario confirma el alta. Se crea sola (`IF NOT EXISTS` en `SCHEMA`, y `agente.init_db()` corre en import desde `app.py`). Se barre a los `CONVERSACION_DIAS` días y en `/reset`.
- **`gestion.agregar_foto(slug, id, b64, tipo)`**: función pública nueva, extraída del cuerpo de `subir_foto()`. Devuelve `False` si no existe el registro. Ahora es el único lugar que escribe la columna `fotos`, lo use el form web o el agente. `subir_foto()` pasa a ser un wrapper de HTTP sobre ella.
- **Env vars nuevas**, independientes de `AGENTE_PROVIDER`: `AGENTE_VISION_API_KEY` (fallback `GEMINI_API_KEY`), `AGENTE_VISION_MODEL` (default `gemini-2.5-flash-lite`), `AGENTE_VISION_API_BASE` (default el endpoint OpenAI-compatible de Google). Sin la key, `_get_vision_config()` devuelve `None`.
- **Tools nuevas: `leer_foto()` y `adjuntar_foto(slug, id)`.** Las dos operan sobre la foto adjuntada en el turno, que viaja por `contexto_turno['foto_turno']` y **no** como parámetro (el modelo no ve la imagen; pedirle el base64 sería pedirle que lo invente). `adjuntar_foto` entra en `TOOLS_ESCRITURA` (se audita, cuenta para el detector de escritura fantasma); `leer_foto` es de lectura — no toca la base, lo que gasta es la API de visión.
- **`chat()` ya no le manda la imagen al agente ni la lee sola** cuando hay lector configurado: deja la foto en `contexto_turno` y le agrega al mensaje del usuario una nota de que está disponible. **Leer pasó a ser una decisión del modelo**, porque el caso más común —"guardá esta foto en el taladro"— no necesita leer nada, y leer por las dudas era pagar una llamada de visión por foto para tirarla.
  - **Esto cambia lo que se persiste en el historial**: donde antes iba `[el usuario adjuntó una imagen]` ahora va la nota con las instrucciones. `_texto_visible()` la reemplaza por `📷 (foto)` al repintar el chat, así que la UI no cambia.
  - Se conservan las otras dos ramas: proveedor con visión propia (`AGENTE_VISION=1` / Anthropic) sigue andando igual, y sin ninguno de los dos sigue cortando antes del modelo.
- **`AVISO_LECTURA_FALLIDA` se eliminó**: si la lectura falla, ahora el error vuelve como resultado de `leer_foto` y lo cuenta el modelo, en vez de cortar el turno con un texto fijo.
- **`/confirmar`** ahora puede sumarle a la respuesta " Le guardé también la foto." — el front ya pinta ese texto tal cual, no hace falta tocarlo.
- **`AGENTE_PROVIDER=anthropic` deja de ser necesario para el alta desde foto.** Es el contrato que más se rompe hacia afuera: cualquier doc o deploy que lo tuviera puesto *solo* por las fotos puede volver al default.

---

## [2026-08-09] — Emilio cuenta, no actúa: voz del personaje + instructivo positivo + filtro de acotaciones

**Tipo**: filtro de salida nuevo en `chat()` (afecta el texto que ve y que se persiste) + `instruccion_tono` unificada + voz del personaje en el circuito de historias
**Archivos**: `agente.py`, `historia_indice.json`, `HISTORIAS_PROCEDIMIENTO.md`, `agent_docs/gestion-conocimiento.md`, `dev-log/DECISIONS.md`
**Cambios**:
- **`COMO_CUENTA_EMILIO`**: constante compartida por el system prompt y `_instruccion_tono`. Es un **instructivo de qué hacer** ("escribís únicamente las palabras que Emilio dice en voz alta", cómo dar clima con lo dicho, y un test: *¿esta oración se puede pronunciar?*), no una lista de prohibiciones. Reemplaza a la primera versión, negativa, que enumeraba lo que no había que escribir — y por eso mismo **traía los ejemplos malos dentro del prompt**, que era lo que el modelo copiaba.
  - Va también en el **system prompt** (no solo en la instrucción de la tool): es lo que la hace valer en los turnos de seguimiento, donde los resultados de tools ya no están en contexto.
- **`_instruccion_tono(tono, estilo)`**: única fuente para las dos rutas de `consultar_historia`. Antes la ruta por `id` (la del `listar` → el usuario elige, o sea el camino más común) tenía una instrucción de dos líneas **sin** nada de esto, que sí tenía la ruta por `tema`.
- **`_quitar_acotaciones()`**: filtro de salida en `chat()`, aplicado después de `_ocultar_ids()` y también **antes de persistir** (si la acotación queda en el historial, el modelo la imita al turno siguiente). Cubre dos formas:
  - **Marcadas**: cursivas de una marca (nunca `**bold**`), corchetes, tramos entre rayas, y la etiqueta `EMILIO:` / `**Emilio:**` a principio de línea. Qué se borra lo decide `_parece_gesto()`: **nunca** un tramo con números (`*Panel solar 100 W*` es contenido, `—fundada en 1957—` es un paréntesis legítimo). Los verbos con imperativo quedan afuera: `*mirá*` no se toca.
  - **Sin marcar** (`_quitar_oraciones_gesto` / `_es_oracion_gesto`): el gesto escrito como prosa suelta ("Se encoge de hombros."), que es a lo que el modelo se pasa cuando le prohibís las marcas. Borra la oración solo si **todas** sus cláusulas son gesto, con los núcleos listados a mano en `_GESTO_NUCLEO`.
- **Campo `estilo`**: se le pasa literal al modelo, así que se saca el vocabulario de teatro de los ejemplos (`"diálogos"` en `historia_indice.json`, `"dramático"` en `HISTORIAS_PROCEDIMIENTO.md` → `"tenso"`). Los `estilo` de las 5 historias ya cargadas no usaban ninguno de los dos.
- **`QUIEN_ES_EMILIO`**: la voz del personaje, aparte de la forma. El que pregunta ya sabe quién es (no se presenta, no explica que es un fantasma), cuenta con orgullo de ser el único que vio todo, y **se nota que no es una persona sin que lo diga**: no tiene cuerpo ni lugar (está siempre y en todas partes a la vez), nada lo tapa, y el tiempo no le pesa. Va solo en el circuito de historias, no en las respuestas operativas.
  - De ahí sale el fundamento de la regla anti-acotaciones: no describe lo que hace con el cuerpo **porque no tiene cuerpo**. En `COMO_CUENTA_EMILIO` quedó escrito como consecuencia del personaje, no como prohibición de estilo suelta.
  - La sección QUIÉN SOS del system prompt también se reescribió: "no sos una persona que trabaja en el edificio: sos el edificio". Se sacaron las frases que le daban cuerpo sin querer ("su fantasma **recorre** los pasillos", "alguien que **te cruzás** en el pasillo").
- **`EXCUSA_SIN_HISTORIA`**: interpolada en las **tres** `nota` de `no_encontrado` (índice vacío, sin match por tema, id inexistente). Cuando no tiene la historia, zafa con una excusa absurda en vez de admitir el hueco — pero la excusa reemplaza el "no sé", **nunca los hechos**, y el system prompt acota que no vale para horarios, stock, préstamos ni personas ("DÓNDE TERMINA EL PERSONAJE"). Ver DECISIONS.

---

## [2026-08-08] — Entidad `personas` + el CRUD genérico deja de exigir una columna `nombre`

**Tipo**: schema nuevo en `gestion.db` + cambio de contrato en la config de `ENTIDADES`
**Archivos**: `gestion.py`, `templates/gestion/detalle.html`, `agent_docs/gestion-conocimiento.md`, `dev-log/DECISIONS.md`
**Cambios**:
- **Tablas nuevas**: `personas` (id, nombre, `nombre_norm`, descripcion, fecha_actualizada, drive_url, fotos), y las M2M `persona_proyectos` / `persona_hitos`, ambas con índice por `persona_id`.
  - `nombre_norm` tiene un **UNIQUE** y no se pide en el form: lo calcula `gestion.clave_persona()` (público). Ver DECISIONS.
  - `fecha_actualizada` también es derivada: se pisa sola en cada guardado, no es un campo del form.
- **`ENTIDADES` acepta `campo_nombre`** (default `'nombre'`) para entidades cuya columna de nombre se llama distinto. `hitos` la declara como `'titulo'`.
  - **Todas las lecturas del CRUD genérico pasan por `_select(cfg)`**, que agrega `titulo AS nombre`. El contrato para los consumidores (templates genéricos, `agente.py`, `buscar_entidad_sin_request`, `snapshot_entidad`) **no cambia**: siguen leyendo `fila['nombre']`.
  - Esto arregla `/gestion/hitos`, que estaba **roto desde que se agregó la entidad** (commit `829ea57`): `lista()` hacía `ORDER BY nombre` sobre una tabla sin esa columna → `OperationalError`, y el alta validaba `request.form.get('nombre')`, que en el form de hitos nunca llega → "El nombre es obligatorio" siempre.
- **`hitos` gana columna `fotos`** (aditiva vía `_migrar`): `detalle.html` muestra el botón 📷 para toda entidad, y sin la columna `subir_foto` tiraba 500.
- **`LIMPIEZA_M2M`** ahora cubre `personas`, y suma las inversas a `proyectos` (`persona_proyectos`) e `hitos` (`persona_hitos`).
- **`nuevo`/`editar` capturan `sqlite3.IntegrityError`** y muestran el mensaje de `_ERROR_DUPLICADO` en vez de un 500.
- **El agente ya alcanza las 6 entidades**: `agente.SLUGS_ENTIDAD = list(gestion.ENTIDADES)` reemplaza el enum hardcodeado que se repetía en **10** esquemas de tools. Agregar una entidad ya no requiere tocar `agente.py`.
  - `_crear_entidad` valida `gestion._campo_nombre(cfg)` en vez de `'nombre'`; `_nombre_de(slug, campos)` (nuevo) resuelve el nombre visible de una ficha, porque el dict del modelo no pasa por el alias de `_select()`; `CAMPOS_REDACTADOS` suma `'titulo'`.
  - System prompt: sección **PERSONAS** nueva (son seis áreas, no cuatro).

---

## [2026-08-08] — `gestion.init_db()` puede fallar: seed condicionado + respaldos automáticos

**Tipo**: cambio de contrato en el arranque (sin cambio de schema)
**Archivos**: `gestion.py`, `agent_docs/gestion-conocimiento.md`, `dev-log/DECISIONS.md`
**Cambios**:
- **`init_db()` ya no siembra incondicionalmente.** Si `recursos` está vacía **y** existe al menos un respaldo en `backups/`, levanta `RuntimeError` con las instrucciones de restauración. Antes cargaba los 5 de ejemplo, lo que convertía una pérdida de datos en algo silencioso (ver DECISIONS 2026-08-08).
  - **Quien llame a `init_db()` tiene que contar con que puede tirar excepción**: hoy son `app.py` (en el import, o sea afecta a gunicorn/WSGI) e `init_gestion.py`. Es intencional que la app no arranque en ese caso.
  - Escape hatch: `GESTION_SEED=1`. Un deploy limpio no tiene respaldos, así que sigue sembrando en el primer arranque sin necesidad del flag.
- **`init_db()` ahora respalda antes de tocar nada** vía `respaldar_db()`, que es público por si hace falta llamarlo a mano antes de una operación riesgosa.
- **Directorio nuevo `backups/`** al lado de `gestion.db`, con `gestion-YYYYMMDD-HHMMSS-ffffff.db`. Cae bajo `*.db` del `.gitignore`: no se versiona ni se pushea.
- **API pública nueva en `gestion.py`**: `respaldar_db(max_copias=20)` y `respaldos()` (lista ordenada del más viejo al más nuevo).
- `importar_inventario.py` vuelve al repo (se había borrado en `0dbfbee`) como fuente secundaria del inventario. **No es un backup** — no tiene relaciones, fotos ni préstamos.

---

## [2026-08-08] — Alta desde foto: contrato de `/chat` con imagen, flag de visión por proveedor

**Tipo**: cambio de contrato en `POST /gestion/agente/chat` + config nueva (sin cambio de schema)
**Archivos**: `agente.py`, `static/gestion-agente.js`, `agent_docs/gestion-conocimiento.md`
**Cambios**:
- **`mensaje` deja de ser obligatorio si viene `imagen`**: antes `{mensaje:'', imagen:'…'}` era `400`. Mandar solo la foto de una etiqueta es el caso normal en el taller; el backend completa el texto con "Te mando esta foto." y el front deja de bloquear el envío. Vacío **y** sin imagen sigue siendo `400`.
- **`_get_config()` devuelve una clave nueva `vision`** (bool). `true` siempre para `anthropic`; para el resto sale de la env var nueva **`AGENTE_VISION`** (`1`/`true`/`si`), porque ahí la visión depende del modelo y no del proveedor (gpt-4o sí, gpt-3.5 no).
- **Sin visión, `/chat` corta antes de llamar al modelo** y responde `AVISO_SIN_VISION` (`{respuesta, tools:[], escritura_fantasma:false, confirmacion:null}`, HTTP 200). Antes la imagen se reemplazaba por una nota y el modelo contestaba igual — con el default DeepSeek eso significaba inventar lo que "leyó" en la etiqueta. El turno se guarda en el historial como cualquier otro (sin la imagen).
- **`_mensajes_openai(mensajes, vision=False)` toma un parámetro nuevo**: con `vision=True` traduce el bloque `image`/`source` de Anthropic al `image_url` con data URI de OpenAI, en vez de aplanarlo a la nota de texto. Habilita el flujo con gpt-4o u ollama+llava.
- **El front achica la foto antes de mandarla** (canvas, 1568 px de lado largo, JPEG 0.85): una foto de celular en base64 no entraba en el límite de la API de visión. Si el navegador no puede decodificarla (HEIC), se manda el original.
- **System prompt**: sección nueva "FOTOS DE DATASHEETS, ETIQUETAS Y CHAPAS DE CARACTERÍSTICAS" con el circuito completo (no inventar lo ilegible, la cantidad la dice el usuario, N unidades = un recurso con `cantidad` N, buscar duplicados antes, specs en `descripcion`). La regla 2 de "REGLAS IMPORTANTES" ahora apunta ahí.

---

## [2026-08-08] — Tool nueva `listar_todos`: fallback de lectura completa para sinónimos

**Tipo**: tool nueva del agente (sin cambio de schema)
**Archivos**: `agente.py`
**Cambios**:
- **Tool nueva `listar_todos(slug)`** — devuelve la lista completa de `{id, nombre}` de una entidad. Es el **fallback** de `buscar_entidad`, no un reemplazo: se usa cuando ningún resultado trae `match: "exacto"`. Resuelve sinónimos y jerga (tester→*Multímetro*, taladro→*Agujereadora de banco*) sin diccionario que mantener, y convierte "no está cargado" de conjetura en afirmación verificada.
- **Contrato de la salida**: `{slug, total, items:[{id,nombre}], instruccion}` + `sin_nombre: N` si hay filas con nombre vacío (se filtran de `items` pero se cuentan, para que "estos son todos" sea cierto). Arriba de `LIMITE_LISTADO_COMPLETO` (400) devuelve `{'error', 'total'}` en vez de la lista.
- **Un solo punto de registro cubre los dos proveedores**: se agrega a `TOOLS_SCHEMA` (formato Anthropic) y `_tools_openai()` la convierte para DeepSeek/OpenAI/Groq. Registrada además en la lista de tools de lectura de `ejecutar_tool` (no se audita) y en el dispatch.
- **`buscar_entidad` cambia sus `aviso`**: donde antes decían "avisale que quizá no está cargado", ahora dicen "antes de afirmar que no está, llamá a `listar_todos(slug)`". Su `description` también deja de sugerir concluir que no existe.
- **Regla 3 del system prompt reescrita**: de "busca difuso" al orden explícito `buscar_entidad` → si no hay `exacto`, `listar_todos` → recién ahí "no está cargado".
- Costo medido: el listado completo de 91 recursos son ~1.190 tokens contra un piso de ~8.050 por round-trip. Ver `dev-log/DECISIONS.md` 2026-08-08 para las alternativas descartadas (columna `sinonimos`, JSON de grupos, tier de reintentos) y cuándo la decisión se da vuelta.

---

## [2026-08-08] — Historias: arquitectura de dos niveles con lazy-loading e instrucciones de tono

**Tipo**: refactor de estructura de archivos + cambio en tool `consultar_historia`
**Archivos**: `historia_indice.json` (nuevo), `historias/` (directorio nuevo), `agente.py`, `agent_docs/gestion-conocimiento.md`
**Cambios**:
- **Estructura anterior** (`historia_escuela.json` monolítico) → **nueva estructura**:
  - `historia_indice.json`: índice cachea (id, título, claves, tipo, resumen, tono, estilo, sin texto)
  - `historias/{id}.json`: archivos individuales con texto completo + metadata (lazy-load)
  - Beneficio: escalable a cientos de historias; índice pequeño, textos bajo demanda
- **Tool `consultar_historia(tema?, id?)`** devuelve tres modos:
  - `directo`: 1 coincidencia exacta → historia completa + `instruccion_tono` (cómo contar: tono, estilo, primera persona)
  - `listar`: múltiples opciones → índice sin textos, usuario elige
  - `no_encontrado`: nada coincide → instrucción de no inventar
- **Búsqueda** ampliada: antes solo en claves; ahora también en `tono`, `estilo`, permitiendo consultas como "historias misterosas" o "algo excitante"
- **Costo de tokens**: índice cachea (250/turno fijo); textos solo al leerlos (~200–500 según historia)

---

## [2026-08-08] — El agente deja de mostrar los id internos

**Tipo**: cambio en la salida del agente al usuario
**Archivos**: `agente.py`
**Cambios**:
- **`_ocultar_ids()`**: filtro de salida en `chat()`, aplicado **antes de persistir** (así el historial repintado tampoco los trae). Saca paréntesis que son solo un id, ids inline, `#N`, y la columna `ID` de las tablas markdown vía `_quitar_columna_id()`. Después limpia restos (paréntesis vacíos, guiones colgando).
- **Regla nueva en el system prompt** ("LOS ID NO SE MUESTRAN") con ejemplos, y la indicación de desambiguar por ubicación/marca/potencia en vez de por id.
- **`POST /confirmar` ya no devuelve el id** en su mensaje: `"✅ Guardado: **nombre**."`.
- Medición con la misma batería de 9 respuestas: **6 mencionaban id → 0**.

---

## [2026-08-08] — El chat repinta la conversación al cambiar de página

**Tipo**: endpoint nuevo (fix de un efecto del cambio anterior)
**Archivos**: `agente.py`, `static/gestion-agente.js`, `templates/gestion/base.html`
**Cambios**:
- **Endpoint nuevo** `GET /gestion/agente/historial` → `{mensajes: [{rol, texto}], confirmacion}`. `gestion-agente.js` lo llama en el `DOMContentLoaded` y repinta el chat.
- **Motivo**: al pasar la conversación a `gestion.db`, el servidor la recordaba (el agente la usaba de contexto) pero el chat se dibujaba vacío en cada navegación — parecía que se había perdido.
- Devuelve además el botón de un alta sin confirmar: navegar a otra página dejaba la ficha viva en el servidor y sin forma de darle OK.
- `_texto_visible()` saca el `(refiriéndote a: X)` que `chat()` agrega al mensaje del usuario: es una pista para el modelo, no algo que el usuario escribió.

---

## [2026-08-08] — Se elimina `importar_inventario.py`

**Tipo**: archivo eliminado
**Archivos**: `importar_inventario.py` (**eliminado**), `agent_docs/gestion-conocimiento.md`
**Cambios**:
- **`importar_inventario.py` borrado.** Era un script de root de carga puntual del sheet "Inventario renovable 2026"; ya se corrió (81 insertados + 2 actualizados) y `gestion.db` es la fuente de verdad desde entonces. No lo importaba ningún módulo — la app no se toca.
- Recuperable del historial: `git show 756a002:importar_inventario.py`. Al reusarlo, ojo con las fechas: traía `fecha_revision` en formato corto sin año, incompatible con `gestion.FORMATO_FECHA_REVISION` (`%d/%m/%Y`).

---

## [2026-08-08] — Conversación del agente server-side + fecha automática en el alta

**Tipo**: tabla nueva en `gestion.db` + cambio de dónde vive el estado del chat + default de campo
**Archivos**: `agente.py`, `gestion.py`
**Cambios**:
- **Tabla nueva `agente_conversaciones`** (`sid, actualizado, historial, entidad_actual, fichas`). El historial del chat, la entidad de contexto y las fichas pendientes **dejan de vivir en la cookie de sesión**: ahí queda solo `session['agente_sid']`, un id aleatorio. Medido: la cookie pasa de ~1700 B y creciendo a **111 B constantes**.
- **Motivo**: la sesión de Flask es una cookie firmada y los navegadores descartan las de más de 4093 B. El peor caso medido con el historial adentro daba ~3.5 KB, y al pasarse el browser tira la cookie **sin avisar** → usuario deslogueado y conversación perdida.
- **Bug arreglado de paso**: mandar una foto metía el base64 completo en la cookie (una imagen de 80 KB la reventaba). `_sin_imagenes()` reemplaza los bloques de imagen por una nota antes de persistir.
- **Topes nuevos** (constantes arriba de `agente.py`): `HISTORIAL_GUARDADO` 60 mensajes (era 20), `HISTORIAL_AL_MODELO` 24 (era 10 — **sube el costo por turno**), `FICHAS_MAX` 20 (era 3), `CONVERSACION_DIAS` 30 para el barrido de conversaciones abandonadas (corre en cada guardado, no en `init_db()`, porque el server puede estar meses sin reiniciar).
- **`recursos.fecha_revision` se precarga con la fecha de hoy en toda alta**, por los dos caminos: form web (`_valores_iniciales()` en el GET de `/recursos/nuevo`) y chat (`_normalizar_borrador()`, antes del token, para que salga en la ficha y el usuario la pueda cambiar). Formato nuevo **`gestion.FORMATO_FECHA_REVISION` = `%d/%m/%Y`** (`08/08/2026`), que `agente.py` importa. Conviven con las fechas cortas sin año del sheet ("24/4"); no se reformatean. Editar no toca la fecha.

---

## [2026-08-08] — `buscar_entidad` expone la calidad del match

**Tipo**: cambio de contrato de una tool del agente (sin cambio de schema)
**Archivos**: `agente.py`
**Cambios**:
- **Cada resultado trae `match`**: `exacto` (substring en el nombre) / `descripcion` (substring en la descripción) / `aproximado` (solo similitud difusa), más `similitud` (0–1) en los aproximados. Antes todos llegaban con el mismo peso: buscar "taladro" devolvía *Caladora* y el agente la ofrecía como si fuera el recurso pedido.
- **`descripcion` incluida** cuando el match vino de ahí (tope `MAX_DESC_BUSQUEDA` = 160). Antes la búsqueda matcheaba contra la descripción pero no la devolvía, así que el nombre llegaba sin relación visible con la query.
- **Tope de `LIMITE_BUSQUEDA` (10) resultados** + campos `total` y `truncado`. La búsqueda difusa no acota: con `query=''` devolvía la tabla entera (91 filas) al contexto.
- **Campo `aviso`** cuando no hay resultados, o cuando **todos** son `aproximado` (le indica que probablemente el recurso no esté cargado, en vez de ofrecer el más parecido).
- **Slug inválido** devuelve `{'error': ...}` con la lista de válidos en vez de `resultados: []`, que el agente leía como "no hay nada cargado".
- Todo lo anterior es capa de presentación en `_buscar_entidad_fmt`: la búsqueda compartida (`gestion.buscar_entidad_sin_request`) no cambió de firma ni de orden.
- **`UMBRAL_SIMILITUD` de 0.6 a 0.68** (`gestion.py`), medido contra el inventario real. Esto **sí** es compartido: aplica también a la búsqueda web `?q=`. Ruido de queries inexistentes: "taladro" 4→0 resultados, "guantes" 7→1. Recall de typos sin cambios (todos siguen #1). Ver `dev-log/DECISIONS.md` 2026-08-08.

---

## [2026-08-08] — Alta por chat: ficha de confirmación obligatoria (`crear_entidad`)

**Tipo**: cambio de contrato de una tool del agente + endpoint nuevo (sin cambio de schema)
**Archivos**: `agente.py`, `static/gestion-agente.js`, `static/gestion.css`, `templates/gestion/base.html`
**Cambios**:
- **`crear_entidad` ya no escribe en la primera llamada.** Devuelve `{ok:false, requiere_confirmacion:true, ficha, campos_vacios, redactados_por_vos, instruccion}` (+ `tipos_en_uso` en `recursos`). Escribe recién cuando se la vuelve a llamar con **exactamente los mismos campos**, en un turno posterior. Quien consuma la tool tiene que contemplar los dos resultados posibles.
- **Cómo se valida la confirmación**: SHA-1 del contenido de la ficha (`_token_ficha`). Escribe solo si ese hash se mostró en un turno **anterior**; cambiar un campo da otro hash y vuelve a la ficha, y el hash se consume al escribir (repetir la llamada no duplica). Es un guard de código, no una regla del system prompt.
- **Endpoint nuevo** `POST /gestion/agente/confirmar`: acepta `{token}` y guarda el alta **sin llamar al modelo** (los campos salen de la sesión, no del request). Devuelve `{ok, respuesta, tools}`, o `409` si el token ya se usó / se reinició la conversación. `/chat` devuelve ahora un campo más, `confirmacion: {token, etiqueta, nombre} | null`, y el front pinta con eso un botón verde debajo del mensaje en vez de pedir un "sí" escrito.
- **Estado nuevo en sesión**: `session['agente_fichas']`, dict `{token: {slug, campos}}` con tope 3 (la cookie de sesión es de ~4KB). El endpoint `/chat` la carga en `contexto_turno['fichas_previas']` y la reescribe al terminar; `/reset` la limpia. Hace falta porque los resultados de tools no se persisten en `agente_historial`.
- **Firma nueva**: `ejecutar_tool(tool_name, tool_input, contexto_turno=None)`, `chat_with_tools(mensajes, trazas=None, contexto_turno=None)` y `_loop_openai(..., contexto_turno=None)`. `contexto_turno` es estado compartido por las tools de un mismo turno.
- **Las fichas no se auditan** en `agente_log` (no tocan la base). Sí el alta efectiva y los intentos rechazados.
- **`nombre`, `tipo` y `descripcion` los redacta el asistente** a partir de lo que dijo el usuario (`CAMPOS_REDACTADOS`), no se piden literalmente. La ficha de `recursos` expone `tipos_en_uso` (`SELECT DISTINCT tipo`) para que reuse categorías en vez de inventar sinónimos.

---

## [2026-08-08] — `recursos.utilidad` pasa a llamarse `recursos.valor`

**Tipo**: rename de columna (schema `gestion.db`) + tool schemas del agente
**Archivos**: `gestion.py`, `agente.py`, `importar_inventario.py`
**Cambios**:
- **Columna renombrada** `recursos.utilidad` → `recursos.valor`. Las opciones no cambian (`""` / Básico / Secundario / Alto valor) y la constante pasa a llamarse `VALORES_RECURSO`. Label del form "Utilidad" → "Valor"; columna del listado "UTILIDAD" → "VALOR".
- **Migración con datos**: `_migrar()` hace `ALTER TABLE recursos RENAME COLUMN utilidad TO valor` en las DBs existentes (conserva lo cargado) antes del `ALTER` aditivo, que ahora pide `valor`. Es idempotente y **la primera migración no aditiva** de `_migrar()`.
- **Contrato con el agente**: el parámetro `utilidad` de las tools `crear_entidad` / `editar_entidad` pasa a llamarse `valor`. Conversaciones viejas que mandaran `utilidad` ya no escriben ese campo (se ignora, como cualquier campo fuera del slug).
- **Importador**: `importar_inventario.py` escribe en `recursos.valor`. **La columna del sheet sigue llamándose "Utilidad"** — no hace falta tocar la planilla.

---

## [2026-08-08] — Asistente: pestaña propia a pantalla completa (`/gestion/agente/`)

**Tipo**: endpoint nuevo + refactor de templates
**Archivos**: `agente.py`, `templates/gestion/agente_chat.html` (nuevo), `templates/gestion/_agente_chat_core.html` (nuevo), `templates/gestion/_agente_widget.html`, `templates/gestion/base.html`, `static/gestion.css`, `static/gestion-agente.js`
**Cambios**:
- **Endpoint nuevo** `GET /gestion/agente/` (`agente.chat_page`): el chat a pantalla completa, con pestaña propia en el nav de `/gestion`. Pensado para el celular, que es donde más se usa.
- **Markup del chat extraído** a `_agente_chat_core.html`, que ahora incluyen tanto el widget flotante como la pestaña. **Contrato**: los IDs del core (`agente-messages`, `agente-input`, …) son únicos y `gestion-agente.js` los busca con `getElementById` — las dos vistas **nunca** pueden renderizarse juntas. `base.html` omite el widget y el botón del header cuando `activo == 'agente'`.
- **Gate de sesión de `agente.bp` diferenciado**: los endpoints HTML (`_ENDPOINTS_PAGINA`: `chat_page`, `agente_log`) ahora **redirigen a `/gestion/login?next=...`** en vez de `abort(401)`. Los endpoints JSON (`/chat`, `/reset`) siguen devolviendo 401.
- **Fix**: `agente.bp` no tenía context processor, así que `GET /gestion/agente/log` renderizaba `base.html` sin `escuela_nombre`/`escuela_logo`/`nav_entidades` (header vacío). Ahora delega en `gestion._contexto_base()`.
- **`<meta viewport>` de `base.html`**: se agregó `viewport-fit=cover`, necesario para que `env(safe-area-inset-*)` tenga valor.
- **Enter envía el mensaje en todas las pantallas** (Shift+Enter hace salto de línea). En táctil (`pointer: coarse`) sigue sin autoenfocarse el input, para que abrir el chat no levante el teclado.

---

## [2026-08-04] — Asistente conversacional con tool-calling (agente.py)

**Tipo**: módulo nuevo + dependencia nueva + endpoints + DB nueva
**Archivos**: `agente.py` (nuevo), `requirements.txt`, `app.py`, `database.py`, `gestion.py`, `templates/gestion/_agente_widget.html` (nuevo), `templates/gestion/agente_log.html` (nuevo), `templates/gestion/base.html`, `static/gestion-agente.js` (nuevo)
**Cambios**:
- **Nueva dependencia**: `anthropic` (SDK de Anthropic para Claude API) en `requirements.txt`.
- **Nuevo blueprint** `agente` (`agente.py`, prefix `/gestion/agente`): chat conversacional via Claude. Gate de sesión reusa `session['gestion_ok']` (mismo que `/gestion`, no requiere usuarios nuevos). Expone **21 tools** (9 de lectura: horarios, aulas libres, búsqueda de entidades; 12 de escritura: crear/editar/vincular recursos, crear/cerrar/reapertura de préstamos, eliminar).
- **Endpoint nuevo** `POST /gestion/agente/chat`: acepta `{mensaje, imagen?}` (imagen en base64), retorna `{respuesta}`. El backend llama a Claude, ejecuta tools que Claude pida, repite hasta respuesta final.
- **Endpoint nuevo** `GET /gestion/agente/log`: tabla de auditoría (últimas 50 entradas), con snapshot "antes" para restauración manual.
- **Nueva tabla** `agente_log` en `gestion.db` (`fecha, tool, entrada, antes, resultado, ok`): cada tool de escritura se audita (no las lecturas).
- **Widget de chat** (`_agente_widget.html` + `gestion-agente.js`): panel flotante en bottom-right, visible tras login en `/gestion`. Incluido en `base.html`, Progressive enhancement (sin JS no aparece, pero backend sigue). Botón "🤖 ASISTENTE" en header.
- **Refactor en `gestion.py`**: funciones nuevas reusables sin dependencia de Flask `request`/`session`: `buscar_entidad_sin_request`, `guardar_entidad_sin_request`, `snapshot_entidad`, `agregar_relacion_m2m`, `quitar_relacion_m2m`. Usadas por `agente.py`.
- **Nueva función en `database.py`**: `aulas_libres(dia, hora)` — calcula aulas desocupadas ahora, agrupadas por piso de `FLOOR_MAPPING`.
- **Env vars nuevas**: `ANTHROPIC_API_KEY` (requerida; sin ella, chat devuelve error). `AGENTE_MODEL` (default `claude-haiku-4-5-20251001`).
- **Guardrails de prompt**: confirmación en dos turnos para eliminar (primero qué va a borrar, esperar "sí" explícito antes de ejecutar). Idem para crear desde foto.
- **Integración**: blueprint registrado en `app.py` + `agente.init_db()`. Reusan schemas/helpers de `/gestion` sin código duplicado.

---

## [2026-07-21] — Préstamos: alta rediseñada como carrito en sesión (reemplaza el form)

**Tipo**: rediseño del alta de préstamos (rutas nuevas, sin cambio de schema)
**Archivos**: `gestion.py`, `templates/gestion/carrito.html` (nuevo), `templates/gestion/carrito_finalizar.html` (nuevo), `templates/gestion/prestamos_form.html` (**eliminado**), `templates/gestion/base.html`, `templates/gestion/lista.html`, `templates/gestion/detalle.html`, `templates/gestion/home.html`, `templates/gestion/prestamos_lista.html`, `static/gestion.css`
**Cambios**:
- El préstamo se crea como **carrito de compra (e-commerce)**: cada recurso tiene un botón **RETIRO** (en el listado y en la ficha) que lo suma al carrito; arriba en el nav hay un **carrito 🛒** con contador que lleva directo al checkout (`/carrito/finalizar`). Recién al finalizar se pide quién retira. El carrito vive en `session['carrito']` = `{recurso_id: cantidad}`.
- **Agregar es AJAX con UI optimista** (`gestion.js`): al tocar RETIRO el botón se transforma al instante en un **stepper verde `− N +`** que ajusta la cantidad hasta el stock (`recursos.cantidad`); la UI cambia en el click y el server se sincroniza en segundo plano por `fetch` (no se siente el round-trip). `carrito_agregar` suma +1 y devuelve `{ok, count, cantidad}`; ruta nueva `carrito_set` fija la cantidad exacta (la usan el +/−, topeada al stock, `<=0` saca el ítem). Sin JS, el form hace POST + redirect. Hooks: `data-add-carrito`, `data-recurso`/`data-stock`/`data-cant` (stepper), `data-cart-count` (badge), `data-set-url`. Helper `_stock()`; `lista()`/`detalle()` pasan el dict `carrito` para el estado inicial del stepper.
- Rutas nuevas `/gestion/carrito`, `/carrito/agregar`, `/carrito/set`, `/carrito/actualizar`, `/carrito/quitar`, `/carrito/vaciar`, `/carrito/finalizar`. Badge del nav con `carrito_count` (ítems distintos).
- **Eliminado** el alta vieja: ruta `prestamo_nuevo`, `prestamos_form.html`, `_parsear_items_prestamo()`, `PRESTAMO_FILAS_FORM`, el `<datalist>` con `[#id]` y el `?recurso=<id>`. Se saca `import re` (ya no se usa). El botón "+ nuevo retiro" de la ficha/home/lista lleva al listado de recursos.
- Sin cambio de schema: `carrito_finalizar` inserta en `prestamos` + `prestamo_items` igual que antes (con `cantidad_devuelta = '0'`). La devolución por ítem y el detalle quedan intactos.
- Cache-buster: `gestion.css` `?v=5`→`?v=10`; `gestion.js` `?v=1`→`?v=3`.

---

## [2026-07-21] — Préstamos: devolución por ítem (parcial) + registrar retiro desde la ficha del recurso

**Tipo**: columna nueva en `gestion.db` + rutas nuevas (dentro del módulo gestión)
**Archivos**: `gestion.py`, `templates/gestion/prestamos_detalle.html`, `templates/gestion/detalle.html`, `static/gestion.css`, `templates/gestion/base.html`
**Cambios**:
- Columna nueva `prestamo_items.cantidad_devuelta` (`TEXT DEFAULT '0'`). Migración aditiva en `_migrar` (`ALTER TABLE`, no rompe DBs existentes; préstamos previos arrancan en `'0'`).
- Rutas nuevas `POST /gestion/prestamos/<id>/devolver_item` y `/reabrir_item`: devolver/deshacer por ítem, con cantidad parcial (ej: 1 de 3). `_recalcular_estado()` cierra o reabre el préstamo solo según el pendiente total — `fecha_devolucion` sigue siendo la fuente de verdad de "devuelto".
- `devolver` (existente) ahora es "devolver TODO": marca cada ítem entero además de setear `fecha_devolucion`. `reabrir` resetea todos los ítems a 0.
- `prestamo_nuevo` acepta `?recurso=<id>` (GET) para precargar la fila 1 — nuevo botón "REGISTRAR RETIRO" en la ficha del recurso (`detalle.html`, solo `slug == 'recursos'`).
- En la lista de préstamos, la columna "se llevó" de los activos muestra lo **pendiente** (no lo retirado). `_resumen_items(..., solo_pendiente=True)`.
- Cache-buster: `gestion.css` `?v=4`→`?v=5`.

---

## [2026-07-21] — Búsqueda en vivo en el listado de `/gestion`

**Tipo**: nuevo asset + comportamiento client-side (dentro del módulo gestión; sin cambios de contrato)
**Archivos**: `static/gestion.js` (nuevo), `templates/gestion/base.html`, `templates/gestion/lista.html`, `static/gestion.css`, `gestion.py`
**Cambios**:
- Primer JS propio de `/gestion`: `gestion.js` filtra el listado en el navegador mientras se escribe (local, sin recargar ni ir al server). Progressive enhancement — sin JS, el form sigue haciendo la búsqueda difusa server-side.
- `lista()` emite un atributo `data-buscar` por fila (texto normalizado por Python) para que el JS filtre por substring normalizado (perdona acentos/mayúsculas). Ver DECISIONS 2026-07-21 y `agent_docs/gestion-conocimiento.md`.
- Cache-buster: `gestion.css` `?v=3`→`?v=4`; `gestion.js` nuevo con `?v=1`.

---

## [2026-07-21] — Registro de préstamos/retiros internos de recursos

**Tipo**: tablas nuevas en `gestion.db` + rutas/templates nuevos (sin tocar `ENTIDADES`)
**Archivos**: `gestion.py`, `templates/gestion/prestamos_lista.html` (nuevo), `templates/gestion/prestamos_form.html` (nuevo), `templates/gestion/prestamos_detalle.html` (nuevo), `templates/gestion/base.html`, `templates/gestion/home.html`, `static/gestion.css`
**Cambios**:
- Tablas nuevas `prestamos` (persona, destino, notas, fecha_salida, fecha_devolucion) y `prestamo_items` (prestamo_id, recurso_id, cantidad). Se crean vía `SCHEMA` (`CREATE TABLE IF NOT EXISTS`, no rompe DBs existentes).
- Rutas nuevas bajo `/gestion/prestamos*` (fuera de la config declarativa `ENTIDADES`, porque el ciclo prestado→devuelto y los ítems con cantidad no encajan en el trío genérico lista/form/detalle): listado (activos + historial), alta con hasta 8 filas de ítems, detalle, devolver, reabrir, eliminar.
- **Devolver nunca borra la fila** — solo setea `fecha_devolucion`. El historial completo queda en `gestion.db` indefinidamente (pedido explícito: "que quede registro... por más que sea por el día").
- El detalle de cada recurso (`/gestion/recursos/<id>`) suma una sección "Historial de préstamos" con todos sus movimientos.
- `nav_entidades` y las cards del home tratan `slug == 'prestamos'` como caso especial (usan los endpoints propios `prestamos_lista`/`prestamo_nuevo`, no los genéricos `lista`/`nuevo`, porque `prestamos` no está en `ENTIDADES`).
- Cache-buster `gestion.css` `?v=2`→`?v=3`.

---

## [2026-07-19] — `recursos` con campos de inventario + import desde el sheet

**Tipo**: schema de `gestion.db` + script nuevo
**Archivos**: `gestion.py`, `importar_inventario.py` (nuevo)
**Cambios**:
- Tabla `recursos` suma 3 columnas: `cantidad` (TEXT), `utilidad` (TEXT: Básico/Secundario/Alto valor), `fecha_revision` (TEXT, fecha del último control, formato libre tipo "24/4").
- `init_db()` ahora migra DBs existentes (`_migrar()`: `ALTER TABLE` aditivo si faltan columnas) — corre solo al iniciar la app.
- `ESTADOS_RECURSO` suma `"Sin revisar"` (para ítems "nc" del inventario físico).
- Listado de recursos cambia columnas: NOMBRE, CANT., UBICACIÓN, ESTADO, UTILIDAD (TIPO sale del listado; sigue en form/detalle).
- `importar_inventario.py` (nuevo, root): importa el sheet "Inventario renovable 2026" a `recursos` vía CSV export público. Re-ejecutable sin duplicar (matchea por nombre normalizado). Se corrió una vez: 81 insertados + 2 actualizados (86 recursos totales).

---

## [2026-07-19] — Login provisorio con contraseña compartida en `/gestion`

**Tipo**: contrato app.py ↔ gestion.py + env vars nuevas
**Archivos**: `gestion.py`, `app.py`, `templates/gestion/login.html` (nuevo), `templates/gestion/base.html`, `static/gestion.css`
**Cambios**:
- `app.secret_key` ahora se setea en `app.py` (env var `SECRET_KEY`, con default de dev) — requerido por la sesión del login de gestión.
- Rutas nuevas `/gestion/login` (GET/POST) y `/gestion/salir`; el resto del blueprint redirige a login si no hay sesión (`bp.before_request`).
- Env var nueva `GESTION_CLAVE` (contraseña compartida; default público en `gestion.py` — setear en el hosting).

---

## [2026-07-17] — Nuevo módulo: Sistema de Gestión de Conocimiento (`/gestion`)

**Tipo**: módulo nuevo (blueprint + DB propia); sin cambios de contrato en horarios
**Archivos**: `gestion.py` (nuevo), `templates/gestion/*` (nuevos), `static/gestion.css` (nuevo), `app.py`, `templates/index.html`, `static/style.css`

- **Nuevo blueprint `gestion`** con prefix `/gestion`: CRUD server-rendered (Jinja, sin JS) para recursos, conjuntos, actividades y proyectos, con relaciones M2M navegables en ambas direcciones y búsqueda por `?q=`. Ver `agent_docs/gestion-conocimiento.md`.
- **Nueva DB `gestion.db`** (SQLite, separada de `escuela.db`): 4 tablas de entidades + 4 M2M. No la toca `/api/actualizar` ni la carga desde Sheets. Seed automático la primera vez (ejemplo del banco de ensayo solar).
- `app.py`: solo agrega `import gestion`, `app.register_blueprint(gestion.bp)` y `gestion.init_db()` en import (corre también bajo gunicorn). Nada del sistema de horarios cambió.
- `templates/index.html`: link `GESTIÓN ›` en `.header-actions` (clase nueva `a.tech-btn-gestion` al final de `style.css`); `base.html` de gestión tiene el link de vuelta `‹ SISTEMA DE HORARIOS`.
- Cache-buster: `style.css` `?v=11`→`?v=12`.

---

## [2026-07-13] — API devuelve objetos con claves nombradas (E3)

**Tipo**: cambio de contrato API ↔ frontend
**Archivos**: `app.py`, `static/js/script.js`, `templates/index.html`

- `/api/<tipo>/<valor>` y `/api/dashboard` devuelven cada clase como **objeto JSON** `{curso, division, especialidad, materia, tipo_materia, profesor, dni, telefono, email, aula, tipo_aula, dia, hora_inicio, hora_fin, grupo, superposicion, suplente_activo, prof_suplente, sup_ini, sup_fin}` (claves = columnas de la tabla `clases`, vía `sqlite3.Row`) en vez de array de 20 posiciones.
- `script.js`: todas las referencias `f[N]` migradas a `f.campo` (~99 en calendario, comparación, planilla, dashboard, modal, tooltip y `filtrarClasesLocal`). `personalToFila()` ahora devuelve un objeto que imita una fila de clases, con marker `tipo: 'personal'` (antes `row[20]`).
- `app.py`: `obtener_datos_calendario()` y `dibujar_pagina_horario()` (PDF) consumen el mismo formato de dicts.
- **Breaking para clientes cacheados**: JS viejo + API nueva no son compatibles → cache-buster `script.js` `?v=13`→`?v=14`.
- Sin cambios de comportamiento visible. Columnas nuevas en `clases` ahora se exponen automáticamente sin romper el frontend (era el objetivo de E3).

---

## [2026-07-11] — Impresión múltiple de cursos en un solo PDF

**Tipo**: feature + endpoint nuevo
**Archivos**: `app.py`, `static/js/script.js`, `static/style.css`, `templates/index.html`

- **Nuevo endpoint** `GET /export/pdf/cursos/<seleccion>`: genera un solo PDF con una página landscape A4 por curso. `seleccion` = `todos` | lista separada por comas de valores `"1° A"` (en el orden recibido). Selección vacía → 400. No colisiona con `/export/pdf/<tipo>/<valor>` (Werkzeug prioriza el segmento estático `cursos`).
- **Refactor en `app.py`**: el dibujo de una página se extrajo de `export_pdf` a `dibujar_pagina_horario(pdf, tipo, valor)` + `_crear_pdf_horario()` (creación del PDF + fuentes). `export_pdf` mantiene URL, filename y comportamiento idénticos.
- **UI nueva**: botón IMPRIMIR VARIOS en el slide-panel de CURSOS → modal selector (`abrirModalImprimirCursos()`, reusa `abrirModal`): botón TODOS, una fila por año (label `N°` togglea el año, chips por división), footer con contador + GENERAR PDF. Estado en Set global `cursosSeleccionadosPDF`. Si la selección está completa manda `todos`.
- Clases CSS nuevas `.print-cursos-*` (solo tokens → nocturno gratis).
- Cache-busters: `style.css` `?v=10`→`?v=11`, `script.js` `?v=12`→`?v=13`.

---

## [2026-07-02] — Solo blueprint + nocturno; toggle con botón (sin tonos)

**Tipo**: cambio de UI + contrato (CSS/JS)
**Archivos**: `static/style.css`, `static/js/script.js`, `templates/index.html`

- Se **eliminaron los temas `swiss` y `soft`** y **todo el sistema de tonos** (`data-tone`, presets `body[data-tone]`, `.tone-swatch`, `applyTone`, `TONOS_VALIDOS`, `appmitre-tone`). Quedan solo **`blueprint`** (claro, default) y **`nocturno`** (oscuro).
- Acento **único**: naranja/ámbar `--accent: #D97A34` en `:root` (alias `--secondary`). Ya no se sobrescribe por tono.
- El `<select#theme-select>` + swatches se reemplazaron por un **botón `#btn-tema`** (`.tech-btn-tema`) en `.header-actions`, junto a `#btn-actualizar`, con ícono SVG **luna/sol** que togglea claro↔oscuro. Se oculta en kiosko (`body.is-fullscreen .header-actions`).
- JS: `TEMAS_VALIDOS` = `['blueprint','nocturno']`; se quitó `TEMAS_OSCUROS` (nocturno es el único oscuro, chequeo inline). Nueva `toggleTheme()`; `applyTheme()` actualiza el ícono del botón. Se eliminaron `applyTone`/`TONOS_VALIDOS`.
- El wrapper del header pasó de `.theme-switcher` a `.header-actions`.
- Cache-busters: `style.css` `?v=9`→`?v=10`, `script.js` `?v=11`→`?v=12`.

---

## [2026-07-01] — Tema HUD reemplazado por Soft (friendly)

**Tipo**: cambio de UI
**Archivos**: `static/style.css`, `static/js/script.js`, `templates/index.html`

- Se **eliminó el tema HUD** (bloque de variables + reglas específicas + opción del select + entradas en `TEMAS_VALIDOS`/`TEMAS_OSCUROS`).
- Nuevo tema **`soft`** (claro/"friendly"): sans redondeada (`ui-rounded`/Segoe UI), fondo off-white cálido sin grilla, tabs/botones tipo píldora, tarjetas flotantes con sombras suaves, `--radius: 16px`, bloques del calendario redondeados. Es tema claro → **no** lleva `data-dark`.
- `TEMAS_VALIDOS` = `blueprint`/`swiss`/`nocturno`/`soft`; `TEMAS_OSCUROS` = `nocturno`.
- Cache-busters: `style.css` `?v=8`→`?v=9`, `script.js` `?v=10`→`?v=11`.

---

## [2026-07-01] — Sistema de temas + tonos (3 UIs seleccionables)

**Tipo**: feature + cambio de contrato (CSS/JS)
**Archivos**: `static/style.css`, `static/js/script.js`, `templates/index.html`

- **Nuevo contrato visual**: `<body>` lleva `data-theme` (`blueprint`|`swiss`|`nocturno`|`hud`), `data-tone` (`ambar`|`terracota`|`bronce`|`teal`|`marino`|`ciruela`) y `data-dark` (flag para temas oscuros, seteado por JS). Tema+tono persistidos en `localStorage` (`appmitre-theme`, `appmitre-tone`) — primer uso de localStorage en la app.
- **Nuevos tokens CSS**: en `:root` → `--accent` (default ámbar `#D97A34`), `--surface`, `--border`, `--muted`, `--radius`, `--font-ui`. En **`body`** (no `:root`, por resolución de `var()` en custom properties) → `--secondary` (alias de `--accent`) y `--accent-soft`. Tokens de temas oscuros: `--text`, `--panel`, `--block-bg`. El naranja `#FF6B00` fue reemplazado.
- El font hardcodeado `'Roboto Mono', monospace` se reemplazó por `var(--font-ui)` en todo `style.css` (Swiss lo cambia a sans).
- **Bloques personal**: el estilo inline con hex (`#FDE8D0`/`#FF6B00`/`#1A365D`) se movió del JS a la clase CSS `.personal-cargo-bloque` para que respete el tono activo.
- Nuevas funciones JS: `applyTheme()`, `applyTone()`, `initTheme()` (llamada en `DOMContentLoaded`); `TEMAS_VALIDOS`/`TEMAS_OSCUROS`/`TONOS_VALIDOS`.
- Selector en el header (`.theme-switcher`): `<select>` de tema + swatches de tono. Se oculta en kiosko.
- **Fix**: `--secondary`/`--accent-soft` movidas de `:root` a `body` — en `:root` se congelaban y el selector de tono no cambiaba el acento (solo los bloques personal).
- Temas: se descartó "Compacto" (sidebar) y se agregaron **Nocturno** (dark) y **HUD** (panel de instrumentos).
- Cache-busters: `style.css` `?v=6`→`?v=8`, `script.js` `?v=8`→`?v=10`.

---

## [2026-06-29] — Toda la data cacheada en memoria al cargar + hash routing

**Tipo**: feature + cambio de contrato (frontend)
**Archivos**: `static/js/script.js`, `app.py`, `database.py`, `templates/index.html`

- **Todo sin red tras la carga inicial**: `cargarDatosIniciales()` descarga en paralelo `/api/dashboard` (→ `_allClases`), `/api/personal_todos` (→ `_allPersonal`) y `/api/preceptores_data` (→ `_horariosPreceptores` + `_planillaPreceptores`). A partir de ahí **ninguna búsqueda pega al server**: profesor/aula/curso/planilla, horario de preceptor, preceptor-por-curso y planilla de preceptores se resuelven client-side. Solo van a la red: PDF export y `/api/actualizar`.
- Resolución client-side: `filtrarClasesLocal()` (clases, replica `obtener_filas()`), lookup `_horariosPreceptores[nombre]` (horario individual), `obtenerPreceptorLocal()` (preceptor-por-curso desde `_planillaPreceptores`), y `mostrarPlanillaCursos()` usa `_planillaPreceptores`. Todos con fallback a su endpoint `/api/*` si los datos no cargaron.
- `buscarEnServidor()` refactorizado: render extraído a `procesarResultadoBusqueda(modo, valor, filas)` (compartido caché/red) y `mostrarErrorBusqueda()`.
- `allDataCache` (planilla general) y `lastDashboardData` (dashboard) se inicializan desde el mismo `_allClases`.
- **Hash routing**: `profesor`/`aula`/`curso`/`horario_preceptor` actualizan `location.hash` (`#/profesor/MACIEL%20MARTIN`) → URLs compartibles. `init()` lee el hash al cargar y dispara la búsqueda; `cambiarTab()` lo limpia. Deep-link de preceptor: `cambiarTab()` omite `mostrarPlanillaCursos()` bajo `window.isProgrammaticNavigation` (evita race en `contenedor-lista`).
- **Nuevos endpoints**: `GET /api/personal_todos` (todo el personal no docente) y `GET /api/preceptores_data` (`{horarios: {nombre:[filas]}, planilla: [...]}`, reusa `obtener_horario_preceptor` + `_planilla_preceptores_con_turnos`).
- **Cambio de comportamiento (mejora)**: en el camino cacheado, el "PRECEPTOR PRINCIPAL" se marca según el turno real del curso. La ruta `/api/preceptor/<valor>` tenía un bug (lookup de turno con `°` → siempre `TURNO_DEFAULT`); `obtenerPreceptorLocal()` usa el turno correcto de la planilla. Ver `agent_docs/search-api.md`.
- `script.js` bumpeado a `?v=7` en `index.html`.

---

## [2026-06-27] — Renombrado noche→vespertino + fix parsing preceptor + PDF carta

**Tipo**: fix de contrato + bugfix  
**Archivos**: `database.py`, `app.py`, `static/js/script.js`

- Campo `preceptores_noche` renombrado a `preceptores_vespertino` en DB, API y JS. Etiqueta `T.N:` → `T.V:`.
- `obtener_planilla_preceptores_todos()` ahora devuelve `vespertino` en vez de `noche`.
- `api_preceptor` corregido: parsing cambiado a `split(' ', 1)` para no romper divisiones multi-parte ("6 4° C"); ahora incluye campo `turno` en el response.
- `renderizarPreceptor` en JS: mapping actualizado a nombres completos ("MAÑANA"/"TARDE"/"VESPERTINO"); ahora identifica correctamente el preceptor principal del turno.
- PDF planilla preceptores: cambiado a formato carta (LETTER), texto escalable, márgenes reducidos a 5mm.

---

## [2026-06-25] — Baseline inicial de documentación

**Tipo**: baseline  
**Estado actual del sistema**:

- Flask + SQLite + Vanilla JS, sin tests ni linter.
- DB schema: tablas `clases` (20 columnas), `horarios_preceptores`, `personal_no_docente`.
- API: rutas `/api/<tipo>/<valor>`, `/api/preceptor/`, `/api/horario_preceptor/`, `/api/personal/`, `/api/dashboard`, `/api/actualizar`, `/api/planilla_preceptores`, `/export/pdf/<tipo>/<valor>`.
- Frontend recibe `window.APP_DATA = {rawData, floorMapping, dias}`.
- Acceso a filas por índice numérico (f[0]–f[19] para clases, f[20] para marker personal).
- Versión de branding: V1.16.

---

## [fecha desconocida] — Fase 1 PLAN_ESCUELAS: limpieza de hardcodes

**Tipo**: refactor  
**Cambios**:
- `ESCUELA_NOMBRE`, `ESCUELA_LOGO`, `ESCUELA_VERSION` movidos a `config.py` y pasados al template por Flask.
- `nombre_mapeos.json` extraído a archivo externo (antes estaba inline en `database.py`).
- `DIAS` centralizado en `config.py`; en `script.js` se usa `window.APP_DATA.dias` en lugar de arrays hardcodeados.
- `corregir_horarios()` eliminada — los datos deben venir correctos del sheet.
- Inferencia de turno por hora eliminada de `obtener_preceptores_por_curso()` — turno es ahora config explícita via `TURNO_CURSOS` / `TURNO_DEFAULT`.
- `FLOOR_MAPPING` y `TURNO_CURSOS` / `TURNO_DEFAULT` agregados a `config.py`.

**Contrato afectado**: `window.APP_DATA` ahora incluye `dias` (antes hardcodeado en JS).

---

## [fecha desconocida] — Agregado tabla `horarios_preceptores`

**Tipo**: schema  
**Cambios**:
- Nueva tabla `horarios_preceptores` en DB.
- Nuevo GID `"horarios_preceptores"` en `config.py`.
- Nuevas rutas: `/api/preceptor/<valor>`, `/api/horario_preceptor/<nombre>`, `/api/planilla_preceptores`.
- `rawData` ahora incluye `horario_preceptor` (lista de nombres).
- Nuevo tab "PRECEPTORES" en la UI.

---

## [fecha desconocida] — Agregado tabla `personal_no_docente`

**Tipo**: schema  
**Cambios**:
- Nueva tabla `personal_no_docente` en DB.
- Nuevo GID `"personal_no_docente"` en `config.py`.
- Nueva ruta `/api/personal/<nombre>`.
- `rawData` ahora incluye `personal` (lista de `{nombre, rol}`).
- Búsqueda por profesor ahora hace dos requests paralelos (clases + personal).
- `personalToFila()` agrega índice [20] como marker `'personal'` — si la tabla `clases` agrega columnas, este índice puede colisionar.

---

## [fecha desconocida] — Agregado modo comparación

**Tipo**: feature  
**Cambios**:
- Nuevas variables globales: `isComparacionMode`, `comparacionItems`, `lastFilas`.
- Nueva función `generarCalendarioComparacion()`.
- Nuevo slide-panel con botón COMPARAR en tabs PROFESORES, AULAS, CURSOS.
- Nuevo banner de comparación en el HTML.

---

## [fecha desconocida] — Agregado modo Planilla General

**Tipo**: feature  
**Cambios**:
- Nueva función `generarPlanillaGeneral()`.
- `allDataCache` — caché de todas las clases.
- Nuevos controles de día y piso en el tab AULAS.
- Slide-panel en AULAS ahora tiene botón PLANILLA GENERAL.
- Ruta PDF soporta `tipo=planilla` con valor `"dia|piso"`.

---

## [fecha desconocida] — Modo kiosco (F11)

**Tipo**: feature  
**Cambios**:
- Listener `fullscreenchange` en `document`.
- Clase `is-fullscreen` en `body` controla visibilidad de header, footer, tabs.
- Filtro de texto en dashboard.

---

## [fecha desconocida] — Suplentes (suplente_activo / prof_suplente)

**Tipo**: schema  
**Cambios**:
- Columnas `suplente_activo`, `prof_suplente`, `sup_ini`, `sup_fin` agregadas a tabla `clases`.
- Rendering condicional de "LICENCIADA" en vista de profesor.
- Dashboard muestra "SUPLENTE: nombre" en lugar del titular.

---

_Para el próximo cambio, agregar una entrada aquí si afecta: el schema de DB, la estructura de `window.APP_DATA`, el contrato de la API, o el orden de columnas en los arrays de filas._
