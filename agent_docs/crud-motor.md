# El motor CRUD y el criterio de capas (`crud.py`, `texto.py`, `respaldos.py`)

Cómo está organizado el código compartido entre áreas, y **dónde va cada cosa nueva**.

## Las tres capas

La app tiene tres áreas que pasan por acá (`/gestion`, `/agente`, y horarios sólo de lectura)
más **varias bases de datos independientes**, que siguen siéndolo: no se fusionaron ni hay FK
que crucen de una a otra. Lo que se comparte es el **código**, no los datos, y está ordenado
en capas donde las dependencias van siempre hacia arriba:

El sistema de horarios (`horarios/`) queda **fuera** de este esquema: paquete autónomo, no
usa `crud` ni `accesos`. `agente/` lo importa para leer (`horarios.datos`); nunca al revés.

```
capa 2   gestion.py   agente/                                        ← nombran tablas reales
              │            │
capa 1   crud.py + templates/crud/  ·  accesos.py + templates/accesos/
              │                                    │                   ← saben "entidad" y "permiso",
              └────────────────┬───────────────────┘                     no cuáles
capa 0        config.py    texto.py    respaldos.py                    ← no nombran nada del dominio
```

> Hasta 2026-09 había una segunda área de dominio, `historia.py` (hitos y personas), que
> ejercitaba el motor como segundo usuario real. Se extrajo del código — ver
> `dev-log/DECISIONS.md` — así que varios hooks de acá quedaron sin un consumidor actual;
> se documentan igual porque el motor sigue soportándolos para la próxima área que aparezca.

`accesos.py` es el hermano de `crud.py`: mismo criterio, otro concepto. `crud.py` lo importa (para
decorar sus rutas de escritura), nunca al revés. Ver `agent_docs/accesos.md`.

**La pregunta para ubicar cualquier función es una sola: ¿qué nombra?**

| Si… | va en | ejemplo |
|---|---|---|
| No nombra tablas, ni entidades, ni rutas, ni Flask | **capa 0** | `texto.norm`, `respaldos.respaldar` |
| Nombra el *concepto* de entidad (slug, `ENTIDADES`, relación M2M) pero ninguna concreta | **capa 1** | `crud.select`, `crud.registrar_rutas` |
| Nombra una tabla, un slug o una ruta reales | **capa 2** | `gestion.secciones_detalle`, `gestion.mover_unidades` |

`crud.py` **nunca importa un área**: la recibe como argumento (`area`). Eso es lo
que evita el import circular y lo que mantiene el criterio legible — si algún día `crud.py` necesita
importar un área, la función que lo obligó está en la capa equivocada.

### El reloj: `config.ahora()`

Nadie llama a `datetime.now()`. La hora sale siempre de `config.ahora()`, que devuelve la hora de
pared de la escuela (`ZONA_HORARIA = "America/Argentina/Buenos_Aires"`) como **datetime naive**.

- **Por qué**: en producción (Render) el server corre en UTC, así que `datetime.now()` daba todo
  3 horas adelantado — el agente contestaba con la hora equivocada y lo mismo se guardaba en
  préstamos, fechas de revisión y nombres de respaldo.
- **Por qué naive**: todo el código formatea y compara contra fechas de la DB, que no tienen
  tzinfo. Devolver un datetime consciente rompería esas restas.
- **Fallback**: si falta la base de zonas horarias (`zoneinfo` sin `tzdata`, típico en Windows),
  cae a un offset fijo `-3`. Argentina no aplica horario de verano desde 2009, así que da igual.

Consumidores: `agente/llm.py` (hora del system prompt), `agente/rutas.py` (sello de hora por
mensaje), `agente/db.py`, `gestion._ahora` y `valores_iniciales`,
`crud.py` (fecha de foto) y `respaldos.py` (nombre del archivo). El sistema de horarios
tiene su propia `ahora()` en `horarios/config.py` (no importa este `config.py`).

Los archivos de capa 0 se llaman por lo que contienen (`texto.py`, `respaldos.py`) y **no `util.py`**
a propósito: un archivo llamado "util" no tiene forma de decirte que algo no pertenece ahí, y termina
siendo el cajón donde vuelve a acumularse todo. Si hace falta compartir algo que no es texto ni
respaldos, va en un archivo nuevo con nombre propio.

## El contrato de "área"

Un área es un módulo Python que expone esto. `crud` lo lee con `getattr`, así que lo opcional que no
esté simplemente no se usa.

### Obligatorio

| | qué es |
|---|---|
| `DB_PATH` | ruta a su `.db` |
| `PREFIJO_BACKUP` | prefijo de sus respaldos (`'gestion'` → `database/backups/gestion-*.db`) |
| `TABLA_TESTIGO` | tabla que se mira para saber si la DB "tiene datos" |
| `ENTIDADES` | `{slug: cfg}` — la config declarativa |
| `SCHEMA` | script SQL idempotente (`CREATE TABLE IF NOT EXISTS`) |
| `LIMPIEZA_M2M` | `{slug: [(tabla, columna)]}` a limpiar al eliminar una fila |
| `PERMISOS` | `[(clave, etiqueta, verbo)]` que declara al catálogo de `accesos` |
| `GRUPO_PERMISOS` | título bajo el que se agrupan en el panel `/accesos` |
| `PERMISO_LECTURA` | el permiso base: hace falta para ver cualquier cosa del área |
| `PERMISO_ESCRITURA` | el que piden `nuevo`/`editar`/`eliminar`/fotos y los botones que los muestran |

### Hooks opcionales

**Son la frontera exacta entre capa 1 y capa 2**: todo lo que nombra una tabla concreta entra por
acá, nunca por un `if slug == '...'` dentro de `crud.py`.

| hook | cuándo se llama | quién lo usa hoy |
|---|---|---|
| `BACKUP_MAX_DIAS` | atributo, no función: techo de antigüedad de sus respaldos. Sin él, el "primero de cada día" de `respaldos.py` no caduca nunca — lo declara un área cuyos datos vencen, para que purgar la fila purgue de verdad | `salidas` (60 días, su vigencia es de 365) |
| `PERMISO_ROTAR_FOTO` | atributo, no función: quién puede girar una foto ya cargada (`rotar_foto` y el botón del visor). Si el área no lo declara, es `PERMISO_ESCRITURA` | `gestion` (`gestion.rotar`, solo admin) |
| `migrar(cur)` | en cada `init_db`, después del SCHEMA | `gestion` |
| `seed(cur)` | sólo si la DB arranca vacía | ninguna hoy (`gestion` arranca vacía a propósito) |
| `secciones_detalle(slug, id, cur)` | al armar la ficha de detalle | `gestion` |
| `derivados(slug, valores)` | antes de cada INSERT/UPDATE; devuelve columnas calculadas | ninguna hoy |
| `valores_iniciales(slug)` | defaults del form de alta | `gestion` (`fecha_revision` = hoy) |
| `extras_template(vista, slug, id)` | kwargs extra para `render_template`; `id` sólo en `detalle` y `editar`, si no `None` | `gestion`: lugares, estados y días de revisión del listado, y los sub-recursos del kit en `editar` |
| `tarjetas_extra(cur)` | tarjetas del home que no salen de `ENTIDADES` | ninguna hoy (ídem, la tarjeta de Préstamos) |
| `inicio()` | URL a la que redirige la raíz del área en vez de renderizar el home de tarjetas; el área no necesita `home.html` | `gestion` (la raíz de un inventario va a la lista de recursos) |
| `contexto_extra()` | claves extra del context processor | ninguna hoy (ídem, `carrito_count`) |
| `NAV_EXTRA` | `[(slug, label)]` extra para la nav | ninguna hoy (ídem, el ítem "Préstamos") |
| `ERROR_DUPLICADO` | `{slug: mensaje}` cuando un UNIQUE rechaza el guardado | ninguna hoy (`gestion.ERROR_DUPLICADO = {}`) |

#### Lo que NO entra por `migrar(cur)`

`migrar` recibe un cursor de **una sola** DB, la del área. Sirve para los `ALTER` aditivos y los
renombres puertas adentro, y con eso alcanza para casi todo: corre en cada `init_db`, o sea en cada
arranque, así que una instalación vieja se pone al día sola con un `git pull` + reload.

Una migración que **cruza DBs** no cabe ahí, porque ningún área importa a la otra. Esas van a
`actualizar.py`, un script de consola que sí puede mirar varias a la vez (hoy: separar
`recursos` en un archivo por inventario). Mismo criterio para la limpieza de tablas y columnas
que el código ya no declara: `migrar` no puede saber qué sobra en la DB de al lado.

### Config de cada entidad (`ENTIDADES[slug]`)

`tabla`, `singular`, `plural`, `descripcion` (card del home), `campos` (form), `columnas` (listado),
`relaciones` (M2M editables desde el form, con prefijo `rel_`) y, opcionales, **`campo_nombre`**,
**`campo_alias`**, **`permiso`** y **`sin_eliminar`**.

Cada campo de `campos` declara `nombre`, `label`, `tipo` (`text`, `number`, `textarea`, `select`
con `opciones`, `text_datalist`), y opcionales `requerido`, `ayuda`, **`boton_hoy`** y
**`solo_alta`**. `boton_hoy` es el formato strftime de una fecha guardada como texto libre:
`templates/crud/form.html` le pone al lado un botón **HOY** que la completa con la fecha del día
(la calcula el server con `config.ahora()` y llega al template por el helper `hoy(formato)` de
`crud.contexto_base`, así el motor no conoce ni el campo ni el formato). Hoy la declara
`gestion.recursos.fecha_revision`.

`solo_alta`: un campo así se muestra y se escribe **sólo al crear**. En edición
`templates/crud/form.html` no lo renderiza y `_guardar_form` lo saca de las columnas del UPDATE,
para que el input ausente no vacíe la columna. Es para un valor que después del alta lo maneja
otra cosa: hoy `gestion.recursos.cantidad`, que pasa a ser el COUNT espejo de `recurso_unidades`
y se ajusta por unidades desde EDITAR (ver `agent_docs/gestion-conocimiento.md`). `crud.guardar_entidad`
(el camino del agente) **sí** lo escribe: el agente puede cambiar `cantidad` por el chat.

`campo_nombre` (default `'nombre'`) existe para una entidad cuya columna de nombre se llame
distinto (hasta 2026-09 fue el caso de `historia.hitos`, que la llamaba `titulo`). **Todas las
lecturas van por `crud.select(cfg)`**, que agregaría `titulo AS nombre`, así que templates,
búsqueda y el agente leerían siempre `fila['nombre']` sin enterarse. Las escrituras y la
validación de obligatorio usan `crud.campo_nombre(cfg)`.

`campo_alias` (default `None`, mismo criterio que `campo_nombre`) declara una columna extra de
texto libre — no necesariamente sinónimos estrictos, alcanza con que la gente confunda dos cosas
("zapatilla"/"alargue") — que `crud.buscar_entidad()`/`lista()` prueban en una segunda pasada
cuando nombre/descripcion no matchean; los que entran solo por ahí se muestran al final, marcados
aparte, nunca mezclados con los matches normales. `crud.guardar_entidad()` la agrega a su
whitelist de escritura **sin** que esté en `campos`, que es justo lo que la mantiene fuera del
form web y de la ficha de confirmación del agente (los dos leen `cfg.campos`, nunca esta clave).
Hoy solo la declara `gestion.ENTIDADES['recursos']` (`'campo_alias': 'alias'`): un campo que
completa el asistente y el humano nunca ve ni edita — ver `agent_docs/gestion-conocimiento.md`,
`agent_docs/agente-asistente.md` y `dev-log/DECISIONS.md` 2026-08-08/2026-08-21 (por qué se
había descartado y por qué el override).

`sin_eliminar` (default `False`) marca la entidad que **no se borra nunca**: la ruta `eliminar`
devuelve 404 para ese slug y `templates/crud/detalle.html` no dibuja el botón. El agente ni
siquiera tiene una tool que borre entidades — no hace falta que rechace nada del lado del
chat. Lo declara `gestion.recursos`, que en vez de borrarse se **da de baja** (ver
`agent_docs/gestion-conocimiento.md`). Una entidad así necesita su propia salida del listado:
el flag sólo cierra la puerta, no la reemplaza.

### `permiso`: una entidad que pide más que el área

`permiso` es un permiso **extra**, además del base del área, para ver esa entidad y nada más.
Ninguna entidad lo usa hoy (hasta 2026-09 lo usaba `historia.personas`, que pedía
`historia.personas` — sólo lo tenía el admin), pero el mecanismo se conserva para la próxima
que lo necesite:

```python
'una_entidad': {..., 'permiso': 'area.algo'},
```

Con eso, sin ese permiso desaparecen de una vez **la tarjeta del home, la entrada de la nav, el
listado, la ficha, los dos formularios, las dos rutas de fotos y el bloque de esa entidad dentro de
la ficha de otra** (una entidad relacionada deja de listarla). El motor lo resuelve en tres lugares:

| función | qué corta |
|---|---|
| `permiso_entidad(area, slug)` / `ve_entidad(area, slug)` | la pregunta, en un solo lado |
| un `before_request` de `registrar_rutas` | **todas** las rutas: el slug está en la URL de las siete |
| `relaciones_visibles(area, cfg)` | el fieldset del form **y** el `_guardar_form` |

Lo del `before_request` es lo que evita repetir el chequeo en cada vista, y corre después del gate
de sesión porque el área monta `registrar_acceso` primero. Devuelve `accesos.denegar(permiso)` →
**403**, igual que `accesos.requiere()`; no se puede usar el decorador porque el permiso depende del
slug de la URL, que recién existe en tiempo de request.

Lo de `relaciones_visibles` **no es cosmético**: el form postea la lista entera de cada relación, así
que un fieldset que se esconde y no se saca también de `_guardar_form` haría que guardar una
entidad desde un acceso sin el permiso le borrara los vínculos con la relacionada. Por eso
`form.html` itera `relaciones` (la lista ya filtrada que pasa la vista) y no `cfg.relaciones`.

`crud.guardar_entidad` — el camino del agente, sin `request.form` — ya era seguro: sólo toca las
relaciones que vengan explícitas en el dict.

El motor sigue sin nombrar ninguna clave: la pone el área, igual que con `PERMISO_ESCRITURA`. Del
lado del asistente el mismo dato se respeta con `agente.dominio.ve_entidad` (ver
`agent_docs/agente-asistente.md`), porque lee las mismas tablas que la web.

## Cómo se monta un área

Al final del módulo, dos líneas:

```python
accesos.registrar_acceso(bp, PERMISO_LECTURA)
crud.registrar_rutas(bp, sys.modules[__name__])
```

`registrar_rutas` monta `home`, `lista`, `nuevo`, `detalle`, `editar`, `eliminar`, `subir_foto`,
`foto_archivo` (sirve el archivo de una foto, sin permiso propio: cae bajo el mismo
`_gate_entidad` que `detalle`), `eliminar_foto` y `rotar_foto`, más el context processor. **Los endpoints y las carpetas de templates salen de
`bp.name`** (`url_for(f'{bp.name}.detalle')`, `render_template(f'{bp.name}/lista.html')`), que ya
coincide con el nombre de la carpeta en `templates/` — no hay nada que configurar. Las rutas
que escriben las decora con `accesos.requiere(area.PERMISO_ESCRITURA)` (salvo `rotar_foto`, que usa
`PERMISO_ROTAR_FOTO`): el motor no nombra ningún permiso, lee la clave que declaró el área (mismo
criterio que `campo_nombre`).

`registrar_acceso` vive en **`accesos.py`**, no acá: el gate dejó de ser "una clave y un booleano" y
es un motor aparte, con catálogo de permisos, perfiles, dispositivos y panel. Ver
`agent_docs/accesos.md`. Lo que hay que saber para montar un área:

- El primer argumento es el **permiso base**: el que hace falta para ver cualquier cosa del área.
- `endpoints_pagina`: si el blueprint mezcla páginas HTML con endpoints JSON (el caso de `/agente`),
  acá van los que devuelven HTML. Sólo esos redirigen al login; el resto contesta **401**, que es lo
  que un `fetch` sabe leer — un redirect a HTML le llega como un 200 sin sentido. Si es `None`, todo
  redirige (áreas 100% server-rendered).
- `endpoint_default`: a dónde volver tras loguearse sin `next` válido (`home`, o `chat_page` en el
  agente).

Sin acceso → login o 401. Con acceso pero sin el permiso → **403** (`templates/crud/403.html`),
nunca el login: mandar al login a quien ya entró es un bucle, y si acierta la clave se convertiría
en admin.

## Templates

`templates/crud/` tiene `lista.html`, `form.html`, `detalle.html` y `login.html` genéricos, más
el partial `_detalle_fotos.html` (galería + visor de fotos, que `detalle.html` y la ficha
propia de `gestion` comparten). Se adaptan a cualquier área con dos variables que inyecta
`crud.contexto_base()`:

- `base_template` → `{% extends base_template %}`, así cada área conserva su layout y su nav
- `area_nombre` → `url_for(area_nombre ~ '.detalle', ...)`

**Cada área conserva un stub con el mismo nombre**, para que `render_template(f'{bp.name}/lista.html')`
siga funcionando y para que cualquier excepción sea explícita:

```jinja
{# templates/gestion/lista.html — usa el genérico tal cual #}
{% extends 'crud/lista.html' %}
```

Cuando un área necesita un retoque puntual, llena un bloque en vez de forkear el template:
`acciones_fila` (celda de acciones de cada fila del listado), `acciones` (toolbar del detalle)
y `seccion` (cada bloque de relaciones del detalle). `acciones_fila` y `seccion` están
declarados **`scoped`** en el genérico: están dentro de un `for` y quien los sobreescriba
necesita ver `fila` / `s`. Sin `scoped` esas variables no llegan al override.

Cuando la maqueta cambia de raíz —no un botón de más— el área reescribe entero el bloque
`contenido`: lo hace `gestion/detalle.html` para la ficha de recurso (ver
`agent_docs/gestion-conocimiento.md`), reusando el partial `crud/_detalle_fotos.html` para
la galería y su visor.

`base.html` y `home.html` **no** son genéricos: son la identidad visual y el texto de cada área.

## Cómo agregar…

**…un campo a una entidad**: sumarlo al `SCHEMA` del área, a su `campos`, y al loop aditivo de
`migrar()` — `init_db()` hace el `ALTER TABLE` solo en las DBs existentes.

**…una entidad a un área**: una entrada en `ENTIDADES`, su tabla en `SCHEMA`, su fila en
`LIMPIEZA_M2M`, y si tiene relaciones que mostrar, una rama en `secciones_detalle`. Las rutas salen
solas. Si la entidad debe ser visible para el asistente, no hay nada más que hacer:
`agente.dominio.SLUGS_ENTIDAD` se deriva de `gestion.ENTIDADES`.

**…una entidad que no vea todo el mundo**: declarar el permiso en los `PERMISOS` del área (con el
verbo que corresponda — `'admin'` si es sólo del admin) y colgárselo a la entidad con la clave
`permiso` de su cfg. Web y asistente quedan cubiertos por ese único dato; no hay que tocar ninguna
ruta, ningún template ni el gate.

**…un área nueva**: un archivo con el contrato de arriba, `templates/<area>/` con `base.html`,
`home.html`, `login.html` y los cuatro stubs, las dos líneas de registro, y
`app.register_blueprint(...)` + `init_db()` en `app.py`. Sumarla también a la lista de
`accesos.registrar_app(app, [...])`, que está ahí al lado: con eso sus `PERMISOS` entran solos al
catálogo y a los perfiles, **sin tocar el gate ni migrar los accesos ya dados**. Si además tiene que
entrar al asistente, sumarla a `agente.dominio._modulo()` (hoy devuelve siempre `gestion`;
con una segunda área de dominio vuelve a resolver por `ENTIDADES`, como antes de 2026-09) y a
`SLUGS_ENTIDAD`.

**…algo compartido**: pasarlo por el filtro de la primera sección. Si nombra una tabla, no es
compartido — es del área, y quien lo necesite lo importa de ahí (como el paquete `agente/` importa
`horarios.datos` del sistema de horarios).

## Qué NO está en el motor

`gestion.py` conserva entero su **desglose de recursos por unidad** (`recurso_unidades`):
reparte las unidades de un mismo recurso en más de un lugar, algo que no entra en la config
declarativa (no es una relación M2M entre dos entidades, es una tabla auxiliar de una sola).
No está duplicado en ningún lado, así que no hay nada que extraer — es dominio puro de gestión,
y vive con su área. (Hasta el 2026-08-21 acá también vivía el bloque de préstamos/carrito —
retiro interno de recursos con ítems y un ciclo prestado→devuelto — que se sacó del todo; ver
`dev-log/DECISIONS.md` 2026-08-21.)

Ver también: `agent_docs/gestion-conocimiento.md`, `agent_docs/agente-asistente.md`, y
`dev-log/DECISIONS.md` 2026-08-10 (por qué capas y no duplicación).
