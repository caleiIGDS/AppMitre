"""Motor de accesos y permisos — capa 1.

Hermano de `crud.py`: igual que aquél conoce el *concepto* de entidad pero ninguna
entidad concreta, éste conoce el concepto de **permiso**, **perfil** y **dispositivo**,
pero **no sabe qué permisos existen**. Los declara cada área, como declara sus
`ENTIDADES`, y acá se agregan en un catálogo:

    capa 2 (gestion, historia, agente, app)  ->  capa 1 (accesos, crud)  ->  capa 0

Eso es lo que hace que sumar un área nueva mañana no obligue a tocar nada de acá: declara
sus `PERMISOS` con su verbo y entra sola en los perfiles.

TRES NIVELES
    Público   el SPA de horarios (`/`): sin sesión, abierto.
    Interno   dispositivos habilitados por link de invitación, con permisos sueltos.
    Admin     la clave `GESTION_CLAVE`; tiene el comodín '*'.

CÓMO ENTRA UN INTERNO
    El admin genera en `/accesos` un link de un solo uso. La persona lo abre en SU
    dispositivo, escribe su nombre, y el server quema el token y le deja la cookie de
    sesión. No hay clave que filtrar: reenviar un link ya usado no sirve de nada.

QUÉ VA EN LA COOKIE
    Sólo `{'tipo': 'dispositivo', 'id': 17}` o `{'tipo': 'admin', 'clave': <huella>}`.
    Los permisos NO viajan en la cookie por dos razones: revocar tiene que cortar en el
    request siguiente (si viajaran, revocar no haría nada hasta que expire), y el
    presupuesto de ~4KB de la cookie ya está compartido con `agente_sid`.
"""

import functools
import hashlib
import json
import os
import secrets
import sqlite3
import sys
from datetime import timedelta

from flask import (Blueprint, abort, g, jsonify, redirect, render_template, request,
                   session, url_for)

import respaldos
from config import (ESCUELA_LOGO, ESCUELA_NOMBRE, ESCUELA_VERSION, PRODUCCION, ahora)

RAIZ = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(RAIZ, 'accesos.db')

# Respaldos rotativos, igual que las otras áreas con datos propios: accesos.db no se
# regenera desde ninguna fuente y no viaja por git.
PREFIJO_BACKUP = 'accesos'
TABLA_TESTIGO = 'dispositivos'

# Cuánto vive un LINK de invitación sin canjear. No confundir con la duración del acceso:
# una vez canjeado, el dispositivo entra hasta que el admin lo revoque.
INVITACION_DIAS = 7

SCHEMA = """
CREATE TABLE IF NOT EXISTS dispositivos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre        TEXT NOT NULL,
    etiqueta      TEXT,
    perfil        TEXT NOT NULL,
    permisos      TEXT NOT NULL,
    alta          TEXT NOT NULL,
    ultimo_uso    TEXT,
    user_agent    TEXT,
    revocado      TEXT,
    invitacion_id INTEGER,
    email         TEXT,
    google_sub    TEXT
);

CREATE TABLE IF NOT EXISTS invitaciones (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    token          TEXT NOT NULL UNIQUE,
    etiqueta       TEXT NOT NULL,
    perfil         TEXT NOT NULL,
    permisos       TEXT NOT NULL,
    creada         TEXT NOT NULL,
    expira         TEXT NOT NULL,
    usada          TEXT,
    dispositivo_id INTEGER
);
"""
# `dispositivos.nombre` lo escribe LA PERSONA al canjear; `etiqueta` la escribió el ADMIN
# al invitar. Se guardan las dos a propósito: si no coinciden, el link se reenvió.
# `email`/`google_sub` quedan reservados para sumar Google Sign-In sin migrar nada; hoy
# nadie los lee. Sin FK declaradas, como el resto del proyecto.


def conectar():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    """Crea/actualiza accesos.db.

    No usa `crud.init_db` a propósito: aquél hace `raise` si la tabla testigo está vacía
    y hay respaldos (guarda anti-pérdida de datos), y una accesos.db vacía es un estado
    perfectamente legítimo — es como nace en cada instalación nueva, donde el único
    acceso es el admin por clave.
    """
    respaldos.respaldar(DB_PATH, PREFIJO_BACKUP, TABLA_TESTIGO)
    con = conectar()
    con.executescript(SCHEMA)
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# Catálogo de permisos y perfiles
# ---------------------------------------------------------------------------

# [(clave, etiqueta, verbo, grupo)]. Lo llenan las áreas vía `declarar`; este archivo no
# conoce ninguna clave concreta salvo la suya (`accesos.admin`, que es de su propia
# funcionalidad, no de un área).
CATALOGO = []

PERMISOS = [
    ('accesos.admin', 'Administrar accesos: invitar y revocar dispositivos', 'admin'),
]
GRUPO_PERMISOS = 'Accesos'

# Presets del formulario de invitación. Se definen por VERBO y no enumerando permisos:
# así un área nueva que declare `laboratorio.leer` con verbo 'leer' entra sola en
# 'interno-lectura', sin tocar el gate ni migrar los dispositivos ya dados de alta.
PERFILES = {
    'interno-lectura': ('leer',),
    'interno-gestion': ('leer', 'escribir'),
    'admin': None,   # None = comodín '*'
}

ETIQUETA_PERFIL = {
    'interno-lectura': 'Consulta',
    'interno-gestion': 'Gestión',
    'admin': 'Administración',
    'custom': 'A medida',
}


def declarar(grupo, permisos):
    """Suma los permisos de un área al catálogo. Idempotente por clave."""
    ya = {c for c, _e, _v, _g in CATALOGO}
    for clave, etiqueta, verbo in permisos:
        if clave not in ya:
            CATALOGO.append((clave, etiqueta, verbo, grupo))


def permisos_de_perfil(perfil):
    """Las claves que le tocan a un perfil, resueltas contra el catálogo del momento."""
    if perfil not in PERFILES:
        return []
    if PERFILES[perfil] is None:
        return ['*']
    verbos = PERFILES[perfil]
    return [clave for clave, _e, verbo, _g in CATALOGO if verbo in verbos]


def catalogo_por_grupo():
    """El catálogo agrupado, para pintar los checkboxes del panel."""
    grupos = {}
    for clave, etiqueta, verbo, grupo in CATALOGO:
        grupos.setdefault(grupo, []).append((clave, etiqueta, verbo))
    return grupos


def tiene(permisos, permiso):
    """Función pura: ¿este conjunto de permisos habilita `permiso`?

    Se expone aparte de `puede()` porque el agente la necesita con un conjunto que recibe
    por parámetro, fuera del ciclo request/response de Flask.
    """
    return '*' in permisos or permiso in permisos


# ---------------------------------------------------------------------------
# Quién está del otro lado
# ---------------------------------------------------------------------------

def _clave():
    """La clave de admin. Se lee en cada request y no al importar, para que cambiarla en
    el hosting no exija reiniciar.

    Sin default público: el que había estuvo versionado en un repo público, así que valía
    exactamente cero. En producción que falte es error; en local cae a 'dev' para no
    dejarte afuera de tu propio entorno.
    """
    clave = os.environ.get('GESTION_CLAVE')
    if clave:
        return clave
    if PRODUCCION:
        raise RuntimeError("Falta GESTION_CLAVE en el entorno del hosting.")
    return 'dev'


def huella_clave():
    """Marca de qué clave se usó para entrar.

    Va en la sesión de admin para que cambiar `GESTION_CLAVE` mate todas las sesiones de
    admin en el request siguiente. Es el botón de pánico, y sale gratis.
    """
    return hashlib.sha256(_clave().encode('utf-8')).hexdigest()[:12]


def _dispositivo(disp_id):
    if not isinstance(disp_id, int):
        return None
    con = conectar()
    fila = con.execute(
        "SELECT * FROM dispositivos WHERE id = ? AND revocado IS NULL", (disp_id,)
    ).fetchone()
    con.close()
    return fila


def _tocar(fila):
    """Actualiza `ultimo_uso`, como mucho una vez por hora.

    Sin el throttle sería un INSERT a SQLite en cada carga de página, y el dato sólo se
    usa para que el admin vea en el panel qué dispositivos quedaron abandonados: la
    precisión al minuto no le aporta nada.
    """
    ahora_txt = ahora().strftime('%Y-%m-%d %H:%M:%S')
    previo = fila['ultimo_uso'] or ''
    if previo and previo[:13] == ahora_txt[:13]:
        return
    con = conectar()
    con.execute("UPDATE dispositivos SET ultimo_uso = ? WHERE id = ?",
                (ahora_txt, fila['id']))
    con.commit()
    con.close()


def _resolver():
    dato = session.get('acceso')
    if not isinstance(dato, dict):
        return None

    if dato.get('tipo') == 'admin':
        if dato.get('clave') != huella_clave():
            return None
        return {'tipo': 'admin', 'id': None, 'nombre': 'Administración',
                'permisos': frozenset(['*'])}

    if dato.get('tipo') == 'dispositivo':
        fila = _dispositivo(dato.get('id'))
        if fila is None:
            # Revocado o borrado: deja de entrar en el acto, sin esperar a que la cookie
            # expire. Por eso los permisos no viajan en la cookie.
            return None
        _tocar(fila)
        return {'tipo': 'dispositivo', 'id': fila['id'], 'nombre': fila['nombre'],
                'permisos': frozenset(json.loads(fila['permisos']))}

    return None


def actual():
    """El acceso vigente, o None. Se resuelve una sola vez por request."""
    if 'acceso_mitre' not in g:
        g.acceso_mitre = _resolver()
    return g.acceso_mitre


def permisos():
    acc = actual()
    return acc['permisos'] if acc else frozenset()


def puede(permiso):
    return tiene(permisos(), permiso)


# ---------------------------------------------------------------------------
# El gate
# ---------------------------------------------------------------------------

# {nombre_blueprint: endpoints_pagina}. Lo llena `registrar_acceso` y lo consulta
# `_denegar` para saber si contestar HTML o JSON sin que cada llamador se lo repita.
_PAGINAS = {}


def _es_pagina():
    """¿Esta ruta devuelve HTML? Fuera de un blueprint con gate no hay página que mostrar
    (las rutas sueltas de `app` que piden permiso son endpoints de fetch)."""
    if request.blueprint not in _PAGINAS:
        return False
    paginas = _PAGINAS[request.blueprint]
    return paginas is None or request.endpoint in paginas


def denegar(permiso, como_json=False):
    """403 para alguien YA identificado al que le falta un permiso.

    Es pública porque no todo permiso se puede marcar de antemano con `requiere()`: el de
    una entidad con permiso propio depende del slug de la URL, y quien lo resuelve es
    `crud.registrar_rutas` en tiempo de request.

    403 y no un redirect al login a propósito: mandar al login a quien ya entró es un
    bucle, y encima si acierta la clave se convierte en admin — se le concedería de más
    justo por no tener permiso.

    Sin ningún acceso la respuesta es 401 y no 403: "no dijiste quién sos" y "no te
    alcanza" son cosas distintas, y el que llama tiene que poder distinguirlas para saber
    si ofrecer el login. Dentro de un blueprint con gate esto no se alcanza nunca (el
    `before_request` ya cortó antes); importa en las rutas sueltas de `app` que usan
    `requiere()`, como `/api/actualizar`.
    """
    codigo = 403 if actual() else 401
    if como_json or not _es_pagina():
        return jsonify({'error': 'Sin permiso', 'permiso': permiso}), codigo
    # `base_template` va explícito, igual que en el login: /agente no monta rutas CRUD y
    # por lo tanto su context processor no lo trae.
    return render_template('crud/403.html', permiso=permiso, acceso=actual(),
                           activo=None, area_nombre=request.blueprint,
                           base_template=f'{request.blueprint}/base.html'), codigo


def registrar_acceso(bp, permiso, endpoints_pagina=None, endpoint_default='home'):
    """Monta el gate de un blueprint: before_request + /login + /salir.

    `permiso` es el permiso BASE, el que hace falta para ver cualquier cosa del área — lo
    nombra el área, no este archivo. Los endpoints que exigen más (los de escritura) se
    marcan aparte con `requiere()`.

    `endpoints_pagina`: si el blueprint mezcla páginas HTML con endpoints JSON (el caso de
    `/agente`), acá van los que devuelven HTML. Sólo esos redirigen al login; el resto
    contesta 401, que es lo que un `fetch` sabe leer — un redirect a HTML le llega como
    una respuesta 200 sin sentido. Si es None, todo redirige (áreas 100% server-rendered).

    `endpoint_default`: a dónde volver después de loguearse si no hay `next` válido.
    """
    prefijo = bp.url_prefix or f'/{bp.name}'
    _PAGINAS[bp.name] = endpoints_pagina

    @bp.before_request
    def _gate():
        if request.endpoint == f'{bp.name}.login':
            return
        if actual() is None:
            if endpoints_pagina is None or request.endpoint in endpoints_pagina:
                return redirect(url_for(f'{bp.name}.login', next=request.path))
            abort(401)
        # El permiso de esta ruta puntual si `requiere()` la marcó; si no, el base.
        necesario = getattr(request.url_rule, 'mitre_permiso', None) or permiso
        if not puede(necesario):
            return denegar(necesario)

    @bp.route('/login', methods=['GET', 'POST'])
    def login():
        error = None
        if request.method == 'POST':
            if request.form.get('clave', '') == _clave():
                # clear() antes de escribir: si el navegador traía una conversación del
                # agente o una sesión de dispositivo, se arranca limpio.
                session.clear()
                session.permanent = True
                session['acceso'] = {'tipo': 'admin', 'clave': huella_clave()}
                volver = request.form.get('next', '')
                # Solo volver a rutas del propio blueprint (evita open redirect).
                if not volver.startswith(prefijo):
                    volver = url_for(f'{bp.name}.{endpoint_default}')
                return redirect(volver)
            error = 'Contraseña incorrecta.'
        # `area_nombre`/`base_template` van explícitos y no por el context processor:
        # `registrar_acceso` también la usa `/agente`, que no monta rutas CRUD y por lo
        # tanto no tiene el context processor de `registrar_rutas`.
        return render_template(f'{bp.name}/login.html', error=error,
                               next=request.values.get('next', ''), activo=None,
                               area_nombre=bp.name, base_template=f'{bp.name}/base.html')

    @bp.route('/salir')
    def salir():
        session.clear()
        return redirect(url_for(f'{bp.name}.login'))


def requiere(permiso, como_json=False):
    """Marca una ruta como más exigente que el permiso base de su blueprint.

    Chequea dos veces a propósito: deja la marca en la url_rule (que es lo que lee el
    `before_request` del gate) y además verifica al entrar, para que la ruta siga
    protegida si algún día se monta fuera de un blueprint con gate.
    """
    def deco(f):
        @functools.wraps(f)
        def wrap(*args, **kwargs):
            if not puede(permiso):
                return denegar(permiso, como_json)
            return f(*args, **kwargs)
        wrap.mitre_permiso = permiso
        return wrap
    return deco


# ---------------------------------------------------------------------------
# Invitaciones y dispositivos
# ---------------------------------------------------------------------------

def _ahora_txt():
    return ahora().strftime('%Y-%m-%d %H:%M:%S')


def crear_invitacion(etiqueta, perfil, permisos_lista):
    """Un link de un solo uso. Devuelve el token.

    Los permisos se congelan acá: si mañana cambia el preset del perfil, este link sigue
    dando lo que el admin vio cuando lo generó.
    """
    token = secrets.token_urlsafe(32)
    creada = ahora()
    con = conectar()
    con.execute(
        "INSERT INTO invitaciones (token, etiqueta, perfil, permisos, creada, expira) "
        "VALUES (?,?,?,?,?,?)",
        (token, etiqueta, perfil, json.dumps(sorted(set(permisos_lista))),
         creada.strftime('%Y-%m-%d %H:%M:%S'),
         (creada + timedelta(days=INVITACION_DIAS)).strftime('%Y-%m-%d %H:%M:%S')))
    con.commit()
    con.close()
    return token


def invitacion_valida(token):
    """La invitación si todavía sirve: existe, no se canjeó y no venció."""
    if not token:
        return None
    con = conectar()
    fila = con.execute(
        "SELECT * FROM invitaciones WHERE token = ? AND usada IS NULL AND expira >= ?",
        (token, _ahora_txt())).fetchone()
    con.close()
    return fila


def canjear(token, nombre, user_agent):
    """Crea el dispositivo y QUEMA el token. Devuelve el dispositivo, o None si no sirve."""
    con = conectar()
    cur = con.cursor()
    inv = cur.execute(
        "SELECT * FROM invitaciones WHERE token = ? AND usada IS NULL AND expira >= ?",
        (token, _ahora_txt())).fetchone()
    if inv is None:
        con.close()
        return None

    cur.execute(
        "INSERT INTO dispositivos (nombre, etiqueta, perfil, permisos, alta, user_agent, "
        "invitacion_id) VALUES (?,?,?,?,?,?,?)",
        (nombre, inv['etiqueta'], inv['perfil'], inv['permisos'], _ahora_txt(),
         user_agent, inv['id']))
    disp_id = cur.lastrowid

    # El `AND usada IS NULL` es lo que hace el un-solo-uso atómico: si dos clicks entran
    # a la vez, el segundo UPDATE afecta 0 filas y ese canje se deshace.
    cur.execute("UPDATE invitaciones SET usada = ?, dispositivo_id = ? "
                "WHERE id = ? AND usada IS NULL", (_ahora_txt(), disp_id, inv['id']))
    if cur.rowcount == 0:
        con.rollback()
        con.close()
        return None

    con.commit()
    fila = cur.execute("SELECT * FROM dispositivos WHERE id = ?", (disp_id,)).fetchone()
    resultado = dict(fila)
    con.close()
    return resultado


def _dispositivo_legible(user_agent):
    """'Android · Chrome' a partir del User-Agent crudo.

    No pretende ser un parser de UA: alcanza con distinguir el celular de la notebook,
    que es todo lo que el admin necesita para saber cuál de los dos está revocando.
    """
    ua = user_agent or ''
    sistema = next((s for clave, s in (
        ('Android', 'Android'), ('iPhone', 'iPhone'), ('iPad', 'iPad'),
        ('Windows', 'Windows'), ('Mac OS', 'Mac'), ('Linux', 'Linux'),
    ) if clave in ua), 'Desconocido')
    # Edg y OPR antes que Chrome: los dos se declaran Chrome también.
    navegador = next((n for clave, n in (
        ('Edg/', 'Edge'), ('OPR/', 'Opera'), ('Firefox', 'Firefox'),
        ('Chrome', 'Chrome'), ('Safari', 'Safari'),
    ) if clave in ua), '')
    return f'{sistema} · {navegador}' if navegador else sistema


def listar_dispositivos():
    con = conectar()
    filas = con.execute(
        "SELECT * FROM dispositivos ORDER BY revocado IS NOT NULL, id DESC").fetchall()
    con.close()
    salida = []
    for fila in filas:
        d = dict(fila)
        d['permisos_lista'] = json.loads(d['permisos'])
        d['dispositivo'] = _dispositivo_legible(d['user_agent'])
        d['perfil_etiqueta'] = ETIQUETA_PERFIL.get(d['perfil'], d['perfil'])
        salida.append(d)
    return salida


def listar_invitaciones():
    """Sólo las que todavía sirven: las usadas ya figuran como dispositivo."""
    con = conectar()
    filas = con.execute(
        "SELECT * FROM invitaciones WHERE usada IS NULL AND expira >= ? ORDER BY id DESC",
        (_ahora_txt(),)).fetchall()
    con.close()
    salida = []
    for fila in filas:
        d = dict(fila)
        d['perfil_etiqueta'] = ETIQUETA_PERFIL.get(d['perfil'], d['perfil'])
        salida.append(d)
    return salida


def revocar(disp_id, revocar_ahora=True):
    con = conectar()
    con.execute("UPDATE dispositivos SET revocado = ? WHERE id = ?",
                (_ahora_txt() if revocar_ahora else None, disp_id))
    con.commit()
    con.close()


def borrar_invitacion(inv_id):
    con = conectar()
    con.execute("DELETE FROM invitaciones WHERE id = ? AND usada IS NULL", (inv_id,))
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# El panel /accesos
# ---------------------------------------------------------------------------

bp = Blueprint('accesos', __name__, url_prefix='/accesos')


@bp.context_processor
def _contexto():
    return {
        'escuela_nombre': ESCUELA_NOMBRE,
        'escuela_logo': ESCUELA_LOGO,
        'escuela_version': ESCUELA_VERSION,
        'area_nombre': 'accesos',
        'base_template': 'accesos/base.html',
    }


def _link_de(token):
    return url_for('acceso_canjear_ver', token=token, _external=True)


def _render_panel(link_nuevo=None, error=None):
    return render_template(
        'accesos/panel.html', dispositivos=listar_dispositivos(),
        invitaciones=listar_invitaciones(), grupos=catalogo_por_grupo(),
        perfiles=[(p, ETIQUETA_PERFIL.get(p, p)) for p in PERFILES],
        preset={p: permisos_de_perfil(p) for p in PERFILES},
        link_nuevo=link_nuevo, error=error, activo='accesos')


@bp.route('/')
def panel():
    return _render_panel()


@bp.route('/invitar', methods=['POST'])
def invitar():
    etiqueta = ' '.join((request.form.get('etiqueta') or '').split())[:80]
    if len(etiqueta) < 2:
        return _render_panel(error='Poné para quién es el link (te sirve a vos después).')

    perfil = request.form.get('perfil', 'interno-lectura')
    if perfil not in PERFILES:
        perfil = 'interno-lectura'

    # Los checkboxes mandan permisos concretos. Si lo que llega no coincide con el preset
    # del perfil, el perfil pasa a 'custom': el conjunto de permisos es la verdad, el
    # perfil es sólo la etiqueta de cómo se armó.
    validos = {c for c, _e, _v, _g in CATALOGO}
    marcados = sorted(set(request.form.getlist('permisos')) & validos)
    if perfil == 'admin':
        marcados = ['*']
    elif not marcados:
        return _render_panel(error='Elegí al menos un permiso.')
    elif marcados != sorted(permisos_de_perfil(perfil)):
        perfil = 'custom'

    token = crear_invitacion(etiqueta, perfil, marcados)
    return _render_panel(link_nuevo=_link_de(token))


@bp.route('/otro/<int:disp_id>', methods=['POST'])
def otro_dispositivo(disp_id):
    """Un link nuevo con la misma configuración de un dispositivo ya habilitado.

    Es la respuesta a "tengo celular y notebook" sin aflojar el link: sigue siendo de un
    solo uso, y quedan dos filas que se revocan por separado.
    """
    con = conectar()
    fila = con.execute("SELECT * FROM dispositivos WHERE id = ?", (disp_id,)).fetchone()
    con.close()
    if fila is None:
        abort(404)
    token = crear_invitacion(fila['etiqueta'] or fila['nombre'], fila['perfil'],
                             json.loads(fila['permisos']))
    return _render_panel(link_nuevo=_link_de(token))


@bp.route('/revocar/<int:disp_id>', methods=['POST'])
def revocar_dispositivo(disp_id):
    revocar(disp_id, True)
    return redirect(url_for('accesos.panel'))


@bp.route('/reactivar/<int:disp_id>', methods=['POST'])
def reactivar_dispositivo(disp_id):
    revocar(disp_id, False)
    return redirect(url_for('accesos.panel'))


@bp.route('/invitacion/<int:inv_id>/borrar', methods=['POST'])
def borrar_inv(inv_id):
    borrar_invitacion(inv_id)
    return redirect(url_for('accesos.panel'))


registrar_acceso(bp, 'accesos.admin', endpoint_default='panel')


def registrar_app(app, modulos):
    """Junta el catálogo de todas las áreas y engancha lo que es de la app entera.

    `modulos` son los módulos de área que declaran `PERMISOS` (+ `GRUPO_PERMISOS`). Es la
    única línea que hay que tocar al sumar un área nueva, y está al lado del
    `register_blueprint` que ya hay que tocar igual.
    """
    for modulo in list(modulos) + [sys.modules[__name__]]:
        declarados = getattr(modulo, 'PERMISOS', None)
        if declarados:
            declarar(getattr(modulo, 'GRUPO_PERMISOS', modulo.__name__), declarados)

    # `puede`/`actual` como globals de Jinja: los templates preguntan por permiso en vez
    # de por la vieja marca binaria `session.gestion_ok`.
    app.jinja_env.globals['puede'] = puede
    app.jinja_env.globals['acceso_actual'] = actual

    app.register_blueprint(bp)

    @app.route('/salir')
    def salir_general():
        """Cerrar sesión y volver a la home pública.

        Cada área tiene su `/salir`, que devuelve a SU login — bien para el staff que se
        va a volver a loguear ahí. Éste es para el menú del SPA de horarios: mandar a
        `/gestion/login` a alguien que entró por link y no tiene ninguna contraseña sería
        un callejón.
        """
        session.clear()
        return redirect('/')

    # El canje va sobre `app` y no sobre un blueprint con gate: es justamente la puerta
    # por la que entra alguien que todavía no tiene ningún acceso.
    @app.route('/acceso/<token>', methods=['GET'])
    def acceso_canjear_ver(token):
        inv = invitacion_valida(token)
        if inv is None:
            return render_template('accesos/invalido.html'), 410
        return render_template('accesos/canjear.html', inv=inv, token=token, error=None)

    @app.route('/acceso/<token>', methods=['POST'])
    def acceso_canjear(token):
        # El GET NO quema el token y el POST sí, y no es ceremonia: WhatsApp, Telegram y
        # el prefetch del navegador hacen un GET al link para armar la vista previa. Con
        # el canje en el GET, el link se consumiría solo en el camino y la persona
        # recibiría "link inválido" sin haber hecho nada.
        inv = invitacion_valida(token)
        if inv is None:
            return render_template('accesos/invalido.html'), 410

        nombre = ' '.join((request.form.get('nombre') or '').split())[:80]
        if len(nombre) < 3:
            # Vuelve al formulario SIN quemar el token: mandar el campo vacío no puede
            # costarle el acceso a nadie.
            return render_template('accesos/canjear.html', inv=inv, token=token,
                                   error='Escribí tu nombre y apellido.'), 400

        disp = canjear(token, nombre, (request.headers.get('User-Agent') or '')[:300])
        if disp is None:
            return render_template('accesos/invalido.html'), 410

        session.clear()
        session.permanent = True
        session['acceso'] = {'tipo': 'dispositivo', 'id': disp['id']}
        return render_template('accesos/listo.html', disp=disp,
                               perfil_etiqueta=ETIQUETA_PERFIL.get(disp['perfil'],
                                                                   disp['perfil']))
