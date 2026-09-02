# Accesos y permisos (`accesos.py`, `accesos.db`)

Quién puede entrar a qué. Es un motor de capa 1, hermano de `crud.py`: conoce el *concepto* de
permiso, perfil y dispositivo, pero **no sabe qué permisos existen** — los declara cada área, igual
que declara sus `ENTIDADES`.

## Los tres niveles

| Nivel | Cómo entra | Qué ve |
|---|---|---|
| **Público** | nada | Casi nada: el canje de invitación (`/acceso/<token>`), el link de familias de salidas (`/salidas/completar/<token>`) y el visor `/salidas/normativa`. `/` redirige a `/horarios`, que tiene su propia contraseña (`HORARIOS_CLAVE`, fuera de este sistema) |
| **Interno** | link de invitación de un solo uso → **dispositivo habilitado** | Lo que digan sus permisos |
| **Admin** | `GESTION_CLAVE` en `/gestion/login` (o el de cualquier área) | Todo: tiene el comodín `'*'` |

La clave sigue existiendo **sólo** para el admin, y es a propósito: es el break-glass. Las `.db` no
viajan por git, así que en una instalación nueva `accesos.db` nace vacía y no hay ningún dispositivo
— sin la clave nadie podría invitar al primero.

## Permisos sueltos, perfiles como preset

El acceso guarda un **conjunto de permisos**, no un rol. Los perfiles son atajos del formulario.

Cada área declara los suyos como `(clave, etiqueta, verbo)`:

```python
# gestion.py
PERMISOS = [
    ('gestion.leer',   'Ver el inventario', 'leer'),
    ('gestion.editar', 'Cargar, editar y eliminar recursos', 'escribir'),
]
GRUPO_PERMISOS    = 'Gestión de recursos'   # título bajo el que se agrupan en el panel
PERMISO_LECTURA   = 'gestion.leer'          # el piso del área
PERMISO_ESCRITURA = 'gestion.editar'        # lo que piden nuevo/editar/eliminar/fotos
```

El **verbo** es lo que hace que capa 1 arme los perfiles sin nombrar ningún área:

```python
PERFILES = {'interno-lectura': ('leer',),
            'interno-gestion': ('leer', 'escribir'),
            'admin': None}      # None = comodín '*'
```

**Por eso agregar un área nueva no toca el gate ni migra a nadie:** declara `PERMISOS` con sus
verbos, se suma a la lista de `accesos.registrar_app(app, [...])` en `app.py` (la misma línea donde
ya hay que tocar el `register_blueprint`) y listo. `laboratorio.leer` entra solo en
`interno-lectura`, el admin la ve por el comodín, y los dispositivos ya dados de alta simplemente no
tienen ese permiso hasta que el admin lo tilde.

**`areas`, el otro global de Jinja.** Junto a `puede`/`acceso_actual`, `registrar_app` deja
el conjunto de nombres de blueprint que quedaron montados. Los headers preguntan
`{% if 'historia' in areas and puede('historia.leer') %}` y no sólo por el permiso, porque el
admin tiene el comodín `'*'`: le diría que sí a un permiso que ya no está en el catálogo y el
`url_for` de un blueprint que nadie registró reventaría la página entera.

### Catálogo actual

| clave | verbo | declarado en |
|---|---|---|
| `gestion.leer` / `gestion.editar` | leer / escribir | `gestion.py` |
| ~~`historia.leer` / `historia.editar`~~ | leer / escribir | `historia.py` — **fuera del catálogo**: el área está apagada (`historia.ACTIVA = False`) y `app.py` no la pasa a `registrar_app` |
| ~~`historia.personas`~~ | admin | ídem |
| `agente.leer` / `agente.escribir` | leer / escribir | `agente/__init__.py` |
| `agente.vision` | admin | `agente/__init__.py` |
| `agente.auditar` | admin | `agente/__init__.py` |
| `agente.notas` | admin | `agente/__init__.py` |
| `accesos.admin` | admin | `accesos.py` |

`accesos.admin` es la única clave que nombra este archivo, y es correcta: es el permiso de su propia
funcionalidad, no el de un área.

**El verbo `'admin'` no es un cuarto perfil**: es lo que hace que un permiso NO entre en ningún
preset de interno, porque `PERFILES` sólo enumera `'leer'` y `'escribir'`. Quien lo tiene es el admin
por el comodín `'*'`. El admin igual puede tildarlo a mano en el formulario de invitación, y ahí el
acceso queda como perfil `custom` — el conjunto de permisos es la verdad, el perfil es la etiqueta.

### Permisos de una entidad sola

`historia.personas` es el primero que no protege un área entera sino **una entidad**: `/historia` se
sigue viendo con `historia.leer`, pero `personas` desaparece para quien no tenga ese permiso.

No hace falta partir el área en dos ni escribir rutas nuevas: la entidad lo declara con la clave
`permiso` de su cfg y el motor CRUD hace el resto — tarjeta del home, nav, listado, ficha, formularios,
fotos y el bloque de personas dentro de un hito. El detalle del mecanismo (y por qué el guardado del
formulario también tiene que saberlo) está en `agent_docs/crud-motor.md`. El asistente respeta lo
mismo con `agente.dominio.ve_entidad`: lee las mismas tablas, así que esconderlo sólo en la web no
serviría de nada.

## Cómo entra un interno: link → dispositivo

1. El admin va a `/accesos`, escribe **para quién es** (su nota interna: "alumna 5°B", "pañol"),
   elige el nivel y aprieta GENERAR LINK. Sale una URL con `secrets.token_urlsafe(32)`.
2. La persona abre el link **en el dispositivo que quiere habilitar**, escribe **su nombre y
   apellido** y aprieta el botón.
3. El server quema el token y le deja la cookie de sesión. Desde ahí entra directo.

**El GET no quema el token, el POST sí**, y no es ceremonia: WhatsApp, Telegram y el prefetch del
navegador hacen un GET al link para armar la vista previa. Con el canje en el GET, el link se
consumiría solo en el camino. Un nombre vacío tampoco lo quema: vuelve al formulario con el error.

Se guardan **las dos identidades**: `nombre` (lo escribió la persona) y `etiqueta` (lo escribió el
admin). El panel muestra las dos, y que no coincidan es la señal de que el link se reenvió.

**Un link = un dispositivo**, salvo que se tilde **SIN LÍMITE DE USOS** al generarlo: ese link queda
`multiuso` y no se quema en `canjear()` — cualquiera que lo abra escribe su nombre y se crea un
dispositivo nuevo, todas las veces que haga falta. Sirve para un cartel o un grupo, no para una
persona puntual. Para la persona con celular y notebook (link normal) está el botón
`+ OTRO DISPOSITIVO`, que genera una invitación nueva con su nombre y permisos ya cargados. Quedan
dos filas separadas: si pierde el celular se revoca esa y la notebook sigue andando.

**No hay vencimiento automático**: el acceso dura hasta que el admin lo revoque. Lo que vence a los
7 días es el LINK sin usar (`INVITACION_DIAS`); uno `multiuso` vence a los 3650
(`INVITACION_DIAS_MULTIUSO`), que en la práctica es "no vence". "ANULAR" en el panel borra la
invitación (para que nadie más entre por ese link) sin tocar los dispositivos que ya canjearon —
esos se revocan aparte. La columna "último uso" del panel es lo que permite limpiar la lista de
dispositivos — conviene repasarla a fin de año lectivo, cuando rotan los alumnos.

## Qué va en la cookie

Sólo esto:

```python
session['acceso'] = {'tipo': 'dispositivo', 'id': 17}
session['acceso'] = {'tipo': 'admin', 'clave': '<sha256(GESTION_CLAVE)[:12]>'}
```

Los permisos **no** viajan en la cookie, por dos razones: revocar tiene que cortar en el request
siguiente (si viajaran, revocar no haría nada hasta que expirara), y el presupuesto de ~4KB ya está
compartido con `session['agente_sid']`. Se resuelven con un `SELECT` por request, cacheado en
`flask.g`; el `UPDATE` de `ultimo_uso` va con throttle de una hora.

La huella de la clave en la sesión de admin es el botón de pánico: **cambiar `GESTION_CLAVE` mata
todas las sesiones de admin** en el request siguiente.

La cookie dura `config.SESION_DIAS` (730) y es deslizante (`SESSION_REFRESH_EACH_REQUEST`): quien
usa la app no se desloguea nunca. Eso **no es la política de acceso** — es cuánto puede quedar un
dispositivo sin usarse antes de necesitar un link nuevo.

> Rotar `SECRET_KEY` desloguea a todos, incluidos los dispositivos: las filas sobreviven pero hay
> que reinvitar. No la rotes "por las dudas".

## La API

```python
accesos.registrar_acceso(bp, permiso, endpoints_pagina=None, endpoint_default='home')
accesos.requiere(permiso, como_json=False)   # decorador para rutas que exigen más que el base
accesos.denegar(permiso, como_json=False)    # la respuesta 403/401, para permisos que no se
                                             # pueden marcar de antemano (dependen de la URL)
accesos.actual()        # dict del acceso vigente o None
accesos.permisos()      # frozenset
accesos.puede(permiso)  # también es global de Jinja
accesos.tiene(conjunto, permiso)   # puro: el agente lo usa fuera del request
```

`denegar` es lo que usa `crud.registrar_rutas` para las entidades con permiso propio: el decorador
`requiere()` no sirve ahí porque el permiso sale del slug de la URL, que recién existe en el request.

`registrar_acceso` reemplaza al viejo `crud.registrar_acceso`. Mantiene `endpoints_pagina` y
`endpoint_default` con la misma semántica, y suma el permiso base del área.

**Sin acceso** → redirect al login (páginas) o **401** (endpoints JSON).
**Con acceso pero sin el permiso** → **403**, nunca el login: mandar al login a quien ya entró es un
bucle, y si acierta la clave se convertiría en admin — se le concedería de más justo por no tener
permiso. La página es `templates/crud/403.html`.

En los templates:

```jinja
{% if puede('gestion.editar') %}...{% endif %}
{% if acceso_actual() %}...{% endif %}
{% if puede(permiso_escritura) %}...{% endif %}   {# lo inyecta crud.contexto_base #}
```

`templates/crud/lista.html` y `detalle.html` usan `permiso_escritura` para que el motor siga sin
nombrar ningún permiso concreto: la clave la pone el área.

### El sistema de horarios NO pasa por acá

`/horarios` es un sitio aparte con su propio gate (`horarios/acceso.py`): contraseña
`HORARIOS_CLAVE`, flag de sesión `horarios_ok`, sin catálogo, sin perfiles, sin
`accesos.db`. No declara `PERMISOS` y no está en la lista de `registrar_app`. Entrar a
`/horarios` no da acceso a las áreas de acá y viceversa; `/horarios/salir` no toca la
sesión de `accesos`. `/` (a nivel app) sólo redirige a `/horarios/`.

### Cómo se llega a las áreas internas

Cada área (gestión, historia, agente, salidas, accesos) tiene su `/salir` que vuelve a su
propio login, y `/salir` a nivel app (`salir_general` en `accesos.py`) que cierra todo y
vuelve a `/`. El menú ☰ que salta entre estas áreas vive en sus `base.html` (no en el SPA
de horarios, que ya no tiene puente al resto). Detalle en `agent_docs/frontend-ui.md`.

## El agente: no tener la tool, no tenerla prohibida

`agente/tools/esquemas.py` declara `PERMISO_POR_TOOL` para las 25 tools (14 `agente.leer`, 9
`agente.escribir`, `escribir_notas` con `agente.notas` y `listar_alias` con el permiso de gestión)
y expone `tools_permitidas(permisos)`, **la única puerta por la que los esquemas
salen hacia el modelo**. Los dos loops de `agente/llm.py` mandan sólo lo filtrado, así que un acceso
de consulta recibe 13 tools y el modelo ni se entera de que existen las otras doce. Eso es distinto
a prohibírselas: una tool que no está en la lista no se anuncia y no se alucina. Sobre ese filtro
hay dos ejes más: `PERMISO_POR_SLUG` (una entidad puede pedir un permiso extra, hoy `personas`) y
`TOOLS_FOTO` (ver `agente.vision`, más abajo).

`ejecutar_tool(..., permisos=None)` chequea igual, como segunda línea: cubre `/agente/confirmar`
(que escribe **sin pasar por el LLM**) y el caso de que el modelo invente un nombre. El default
`None` es fail-closed. Un rechazo de escritura queda auditado en `agente_log`: si aparece ahí, o
alguien forjó el request o el filtrado tiene un agujero.

El system prompt también se recorta (`prompt.construir_system_prompt(..., escribe=)`): sin permiso
de escritura no se le manda el circuito de alta, las reglas de borrado ni el padrón de ~1.600
tokens, y sí un bloque que le dice explícitamente que no use "✅". `escribe` se deriva de las tools
que **efectivamente** se mandaron, no de los permisos, para que las dos mitades del mensaje no
puedan contradecirse. Lo mismo hacen `ve_personas`, `ve_fotos` y `ve_notas`. Detalle en
`agent_docs/agente-asistente.md`.

### `agente.vision`: el permiso que corta un gasto, no una tabla

Es el único permiso del proyecto que no protege un dato sino una **factura**: mandar una foto es lo
único del chat que llama a una API aparte (~2.000 tokens por lectura). Va con verbo `admin` —como
`agente.auditar`— así que **no entra en ningún preset de interno** y por defecto lo tiene sólo la
administración, por el comodín. El admin igual puede tildárselo a mano a un dispositivo puntual
desde `/accesos`, y ese acceso queda con perfil `custom`.

Corta en tres capas, y las tres importan:

| Capa | Qué hace | Por qué no alcanza sola |
|---|---|---|
| `_agente_chat_core.html` | no pinta el botón 📷, el input ni el chip | es cosmética: el POST se arma a mano |
| `agente/rutas.py` (`chat()`) | `403` si viene `imagen` sin el permiso | **es el corte real** |
| `tools_permitidas()` | `leer_foto` y `adjuntar_foto` no viajan | evita que el modelo ofrezca leer una foto que el usuario no puede mandar |

Las dos tools de foto piden `agente.vision` **además** del permiso que declaran en
`PERMISO_POR_TOOL`, no en su lugar: si `adjuntar_foto` cambiara su permiso por `agente.vision` a
secas, un dispositivo con visión tildada a mano escribiría en la galería sin tener
`agente.escribir`.

### `agente.notas`: el permiso que elige un destinatario

El archivo `agente.md` (`/agente/notas`, ver `agent_docs/agente-asistente.md`) va al system prompt
de **todos los turnos de quien tenga este permiso**, y de nadie más. Por eso es verbo `admin` y no
`leer`: son las notas de quien administra el sistema —"el pañol está en el aula 12 hasta que
arreglen el techo"— y no un tablón de anuncios para la escuela. Un preceptor que chatea no recibe
una sola línea, ni sabe que el archivo existe.

Es el mismo permiso para leerlo y para escribirlo, en la página y por chat (`escribir_notas`):
partirlo en lectura y escritura inventaría un rol —alguien que ve las notas pero no las toca— que
no existe. La tool se audita en `agente_log` aunque no sea `agente.escribir` (ver
`TOOLS_AUDITADAS`), y lo que guarda como `antes` es el **contenido completo previo**: reescribe el
archivo entero, así que el rastro tiene que serlo también.

## `accesos.db`

DB propia, no una tabla en `gestion.db`. Tres razones:

1. **Capas**: si viviera en `gestion.db`, capa 1 tendría que conocer la ruta de la DB de un área.
2. **`actualizar.py` paso 5**: `DUENOS` dropea toda tabla que el código no declare. Meter `accesos`
   en `gestion.db` sin tocar `DUENOS` = el próximo `python actualizar.py` borra los dispositivos.
3. **Respaldos**: entra sola en la rotación con `PREFIJO_BACKUP='accesos'`.

`accesos.init_db()` **no** usa `crud.init_db`: aquél hace `raise` si la tabla testigo está vacía y
hay respaldos (guarda anti-pérdida), y una `accesos.db` vacía es un estado legítimo.

```sql
dispositivos(id, nombre, etiqueta, perfil, permisos, alta, ultimo_uso, user_agent,
             revocado, invitacion_id, email, google_sub)
invitaciones(id, token, etiqueta, perfil, permisos, creada, expira, usada, dispositivo_id,
             multiuso)
```

`permisos` es JSON (`["gestion.leer"]` o `["*"]`). `revocado`/`usada` en NULL = activo. Un link
`multiuso` (1) se queda con `usada` en NULL para siempre — es lo que lo mantiene vigente en
`listar_invitaciones()` sin que esa query tenga que saber nada de multiuso.
`email`/`google_sub` están reservados para sumar Google Sign-In sin migrar nada; hoy nadie los lee.
El token va **en claro**: hashearlo sólo protegería contra la fuga del `.db`, que está en el mismo
servidor que el `.env`, y a cambio se perdería poder re-copiar un link todavía sin usar. Las
defensas que valen acá son un solo uso, vencimiento a 7 días y lista revocable.

## Hasta dónde llega esto

Es una escuela, no un banco, y está dimensionado para eso: alcanza para que el alumno curioso no
entre y para cortarle el acceso a alguien en un click. **No hay** CSRF, ni límite de intentos, ni
verificación de que el nombre que escribe la persona sea el suyo (para eso está la etiqueta del
admin al lado). Lo que sí hay y es lo que importa: nada que se pueda reenviar por WhatsApp da
acceso, y revocar corta en el acto.
