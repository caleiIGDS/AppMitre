# Decisiones de Arquitectura — AppMitre

Leer este archivo antes de "corregir" algo que parece raro. Muchas decisiones tienen contexto específico de la escuela o del despliegue.

---

## [2026-08-10] — Quién decide qué hacer con una foto: el modelo, no un `if` en el backend

**Contexto**: `chat()` cortaba el turno con un aviso fijo cuando llegaba una foto y no había con qué leerla. El razonamiento original era sólido —sin visión el modelo contestaría igual, inventando lo que "leyó" en la etiqueta, que es el peor resultado posible para un inventario— pero descansaba en una premisa falsa: **que toda foto se manda para ser leída**. No es así. El caso más común en el taller es adjuntar una foto a la ficha de algo que ya existe, y para eso no hace falta ver la imagen: el base64 va del `contexto_turno` a la galería sin pasar por el modelo. El corte dejaba `adjuntar_foto` inalcanzable, y con el default del proyecto (DeepSeek, sin key de visión) eso significaba que mandar una foto no servía para nada.

**Decisión**: que el turno corra siempre y que la distinción "adjuntar" vs. "analizar" la haga el modelo, que es quien entiende la frase del usuario. El backend ya no adivina la intención a partir de la config.

**Por qué `leer_foto` sigue expuesta aunque no haya lector.** La alternativa era filtrarla del `TOOLS_SCHEMA` cuando `_get_vision_config()` es `None`. Se descartó: sin esa tool el modelo no tiene forma de *detectar* que le pidieron analizar, y el pedido de "¿qué dice esta etiqueta?" terminaría en una respuesta inventada o en un silencio raro. Dejándola, el modelo la llama, recibe un error que dice exactamente por qué no se puede y qué ofrecer a cambio, y lo cuenta con sus palabras. Cuesta una vuelta del loop —no una llamada de visión— y DeepSeek cachea el prefijo, así que es despreciable.

**Por qué el aviso lo redacta el modelo y no es un texto fijo.** El mismo motivo por el que leer es una tool y no un paso automático: un texto fijo no sabe si el usuario quería adjuntar o analizar, así que o corta de más (el bug que se arregló) o contesta al lado. El error de la tool le da al modelo el dato y las dos salidas posibles (que le dicten los datos, o que le digan a qué ficha guardarla) y él elige según lo que se venía hablando.

**Se distingue "no hay lector" de "el lector falló"** aunque `_leer_imagen()` devuelva `None` en los dos casos: para el usuario son cosas distintas —una se arregla cargando una API key en el servidor, la otra se arregla esperando un rato— y mandarle "el servicio no respondió" a alguien que nunca configuró un lector lo deja esperando algo que no va a pasar.

**El riesgo que queda**: una foto adjuntada al recurso equivocado no se puede sacar desde la app. Se mitiga en el prompt y en la descripción de `adjuntar_foto`, que insisten en preguntar cuando el destino es ambiguo, no en volver a poner un candado en el backend.

---

## [2026-08-10] — Cuatro áreas separadas físicamente, con el motor CRUD duplicado

**Contexto**: todo convivía en `gestion.py` (1509 líneas, una DB, un blueprint): el inventario del taller, la línea del tiempo institucional (hitos, personas, proyectos) y —adentro de su prefijo— el asistente. Querer tocar la parte de historia, que es más anecdótica y se retoca seguido, ponía en riesgo la gestión de inventario, que es la que la escuela usa todos los días.

**Decisión**: partir en cuatro áreas con frontera física — horarios (`app.py`), recursos (`/gestion`), historia institucional (`/historia`, `historia.py`, `historia.db`) y asistente (`/agente`) — cada una con su archivo, su prefijo, sus templates y su gate de sesión. **Ningún módulo de dominio importa a otro.**

**El motor CRUD se duplicó en vez de extraerse a una librería común.** `gestion.py` e `historia.py` tienen cada uno su copia completa de: `conectar`, `_norm`/`_puntaje_busqueda`, respaldos, `init_db`/`_migrar`, `_cfg`/`_campo_nombre`/`_select`, `_guardar`, los helpers `*_sin_request`, y las rutas genéricas. Son ~350 líneas repetidas.

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
- **No agregar una columna `sinonimos` "para mejorar la búsqueda"** sin releer esto: se evaluó y se descartó con datos.

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
