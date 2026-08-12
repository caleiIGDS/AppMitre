# Accesos y permisos (`accesos.py`, `accesos.db`)

Quién puede entrar a qué. Es un motor de capa 1, hermano de `crud.py`: conoce el *concepto* de
permiso, perfil y dispositivo, pero **no sabe qué permisos existen** — los declara cada área, igual
que declara sus `ENTIDADES`.

## Los tres niveles

| Nivel | Cómo entra | Qué ve |
|---|---|---|
| **Público** | nada | El SPA de horarios (`/`, `/api/*`, `/export/*`). Sin el botón de actualizar |
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
    ('gestion.leer',   'Ver el inventario, actividades y préstamos', 'leer'),
    ('gestion.editar', 'Cargar, editar y eliminar recursos; registrar y cerrar préstamos',
     'escribir'),
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

### Catálogo actual

| clave | verbo | declarado en |
|---|---|---|
| `gestion.leer` / `gestion.editar` | leer / escribir | `gestion.py` |
| `historia.leer` / `historia.editar` | leer / escribir | `historia.py` |
| `agente.leer` / `agente.escribir` | leer / escribir | `agente/__init__.py` |
| `agente.auditar` | admin | `agente/__init__.py` |
| `horarios.actualizar` | admin | `app.py` |
| `accesos.admin` | admin | `accesos.py` |

`accesos.admin` es la única clave que nombra este archivo, y es correcta: es el permiso de su propia
funcionalidad, no el de un área.

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

**Un link = un dispositivo.** Para la persona con celular y notebook está el botón
`+ OTRO DISPOSITIVO`, que genera una invitación nueva con su nombre y permisos ya cargados. Quedan
dos filas separadas: si pierde el celular se revoca esa y la notebook sigue andando.

**No hay vencimiento automático**: el acceso dura hasta que el admin lo revoque. Lo que vence a los
7 días es el LINK sin usar. La columna "último uso" del panel es lo que permite limpiar la lista —
conviene repasarla a fin de año lectivo, cuando rotan los alumnos.

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
accesos.actual()        # dict del acceso vigente o None
accesos.permisos()      # frozenset
accesos.puede(permiso)  # también es global de Jinja
accesos.tiene(conjunto, permiso)   # puro: el agente lo usa fuera del request
```

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

## El agente: no tener la tool, no tenerla prohibida

`agente/tools/esquemas.py` declara `PERMISO_POR_TOOL` para las 25 tools (15 `agente.leer`, 10
`agente.escribir`) y expone `tools_permitidas(permisos)`, **la única puerta por la que los esquemas
salen hacia el modelo**. Los dos loops de `agente/llm.py` mandan sólo lo filtrado, así que un acceso
de consulta recibe 15 tools y el modelo ni se entera de que existen las otras diez. Eso es distinto
a prohibírselas: una tool que no está en la lista no se anuncia y no se alucina.

`ejecutar_tool(..., permisos=None)` chequea igual, como segunda línea: cubre `/agente/confirmar`
(que escribe **sin pasar por el LLM**) y el caso de que el modelo invente un nombre. El default
`None` es fail-closed. Un rechazo de escritura queda auditado en `agente_log`: si aparece ahí, o
alguien forjó el request o el filtrado tiene un agujero.

El system prompt también se recorta (`prompt.construir_system_prompt(..., escribe=)`): sin permiso
de escritura no se le manda el circuito de alta, las reglas de borrado ni el padrón de ~1.600
tokens, y sí un bloque que le dice explícitamente que no use "✅". `escribe` se deriva de las tools
que **efectivamente** se mandaron, no de los permisos, para que las dos mitades del mensaje no
puedan contradecirse. Detalle en `agent_docs/agente-asistente.md`.

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
invitaciones(id, token, etiqueta, perfil, permisos, creada, expira, usada, dispositivo_id)
```

`permisos` es JSON (`["gestion.leer"]` o `["*"]`). `revocado`/`usada` en NULL = activo.
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
