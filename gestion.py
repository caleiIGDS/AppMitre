# gestion.py
# Gestión de recursos — área de capa 2: declara sus entidades y sus reglas de negocio,
# y el CRUD se lo da el motor genérico (crud.py). Lo que NO es genérico y vive acá entero:
# el desglose de recursos por lugar, al final del archivo.
#
# VARIOS INVENTARIOS, ESTANCOS. El área no es un inventario sino N: cada uno tiene su
# propio archivo (`inventarios/<slug>.db`), su encargado, su clave y su gente. Lo que
# separa a uno de otro no es un filtro sino el archivo: estando conectado a uno es
# imposible leer el de al lado aunque a alguien se le olvide un WHERE.
#
#   gestion.db              el REGISTRO (tabla `inventarios`) + las tablas del agente
#   inventarios/<slug>.db   recursos / recurso_unidades / kit_items / recurso_bajas
#
# QUIÉN PUEDE QUÉ. El admin general (`GESTION_CLAVE`) crea inventarios, les pone nombre y
# clave y los elimina — y NO ve el contenido de ninguno: sus claves están en
# `PERMISOS_AMBITO`, adonde el comodín '*' no llega (ver accesos.tiene). Adentro manda el
# encargado, que entra con la clave del inventario y desde ahí invita y revoca, sólo ahí.
# El encargado de un inventario es una persona cualquiera para el de al lado.
#
# Entidades: recursos.
#
# Hasta el 2026-08-21 el módulo también tenía conjuntos, actividades y préstamos/carrito
# (retiro interno de recursos). Se sacaron por decisión de producto, no por deuda técnica:
# ver dev-log/DECISIONS.md 2026-08-21 si se retoman.

import contextlib
import os
import re
import sqlite3
import sys
from datetime import datetime

from config import ahora
from flask import (Blueprint, abort, g, has_request_context, redirect,
                   render_template, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import accesos
import crud
import respaldos
import texto

RAIZ = os.path.dirname(os.path.abspath(__file__))
# El registro. Comparte archivo con las tablas del agente (ver agente/db.py), que nunca
# fueron de un inventario en particular.
DB_PATH = os.path.join(RAIZ, 'gestion.db')
DIR_INVENTARIOS = os.path.join(RAIZ, 'inventarios')

# Slugs que no puede tomar un inventario porque son rutas del registro (`/gestion/admin/…`,
# `/gestion/login`). Sin esto, un inventario llamado "admin" se comería el panel.
SLUGS_RESERVADOS = {'admin', 'login', 'salir', 'static'}

# Permisos que declara el área al catálogo de `accesos`. El VERBO es lo que hace que un
# perfil los agarre solo: 'leer' entra en interno-lectura, 'escribir' en interno-gestion.
PERMISOS = [
    # La ÚNICA clave del área sin ámbito, y la única que tiene el admin general: administrar
    # la LISTA de inventarios. No abre ninguno — ver PERMISOS_AMBITO más abajo.
    ('inventarios.admin', 'Crear, renombrar y eliminar inventarios (sin ver su contenido)', 'admin'),
    ('gestion.leer', 'Ver el inventario', 'leer'),
    ('gestion.editar', 'Cargar, editar y eliminar recursos', 'escribir'),
    # Verbo 'admin' = no entra en ningún preset de interno (ver accesos.PERFILES, que los
    # arma por verbo): sólo lo tiene el admin, por el comodín '*'. El alias de un recurso
    # es un campo que ni el interno de lectura ni el de escritura deben poder ver/editar
    # desde ningún lado — lo completa el asistente solo (ver agent_docs/gestion-conocimiento.md).
    ('gestion.alias', 'Ver los alias ocultos de los recursos (solo consulta)', 'admin'),
    # Mismo verbo 'admin' y mismo motivo que gestion.alias: son chips de auditoría del
    # inventario (qué está vencido de revisión, qué está dado de baja), no algo que un
    # interno de lectura/escritura necesite para su tarea del día a día.
    ('gestion.auditoria', 'Ver los filtros de auditoría del listado (vencidos y dados de baja)', 'admin'),
    # Mismo verbo 'admin', mismo motivo: girar una foto reescribe la imagen guardada (se
    # re-codifica), así que es una operación de mantenimiento del inventario y no parte de
    # cargar un recurso. Subir y borrar fotos siguen siendo de `gestion.editar`.
    ('gestion.rotar', 'Rotar las fotos de un recurso', 'admin'),
    # Quién reparte los permisos DE ESTE inventario. Lo tiene el encargado por haber
    # entrado con la clave, y lo puede delegar en alguien más desde su propio panel.
    ('gestion.accesos', 'Administrar quién entra a este inventario', 'admin'),
]
GRUPO_PERMISOS = 'Gestión de recursos'

# Las claves que valen SÓLO adentro de un inventario. Son las mismas de siempre —nada en
# crud.py, en los templates ni en las tools del agente cambió de nombre—, pero se guardan
# prefijadas (`inv:7/gestion.editar`) y el comodín '*' no las alcanza. Ese detalle es todo
# el aislamiento: tener `gestion.editar` en el taller no es tenerlo en el laboratorio, y
# ser el admin de la escuela no es ser el encargado de ningún inventario.
PERMISOS_AMBITO = frozenset({
    'gestion.leer', 'gestion.editar', 'gestion.alias', 'gestion.auditoria',
    'gestion.rotar', 'gestion.accesos',
})

PERMISO_LECTURA = 'gestion.leer'
PERMISO_ESCRITURA = 'gestion.editar'
PERMISO_ALIAS = 'gestion.alias'
PERMISO_AUDITORIA = 'gestion.auditoria'
PERMISO_ACCESOS = 'gestion.accesos'
PERMISO_REGISTRO = 'inventarios.admin'
# Hook opcional que lee crud.py: quién puede girar una foto ya cargada. Si un área no lo
# declara (historia), el botón pide el permiso de escritura de siempre.
PERMISO_ROTAR_FOTO = 'gestion.rotar'

# Respaldos rotativos: la maquinaria vive en respaldos.py (capa 0). Acá sólo se declara
# qué tabla mirar para saber si la DB tiene datos de verdad (una DB vacía no se respalda:
# taparía los respaldos buenos). El PREFIJO ya no es una constante: hay uno por inventario
# (ver `prefijo_backup`), o los respaldos de cada uno se comerían los del resto.
TABLA_TESTIGO = 'recursos'
PREFIJO_BACKUP_REGISTRO = 'gestion-registro'

bp = Blueprint('gestion', __name__, url_prefix='/gestion/<inv>')


def conectar():
    """Conexión al .db del inventario ACTIVO — `crud.conectar` con esta área ya puesta.
    Las rutas propias (alias, desglose por ubicación, que no pasan por el motor genérico)
    la usan directo."""
    return crud.conectar(sys.modules[__name__])


# ---------------------------------------------------------------------------
# El registro: qué inventarios hay
# ---------------------------------------------------------------------------
# Vive en `gestion.db`, que a partir de acá NO tiene recursos: sólo la lista y las tablas
# del agente. La clave va hasheada (werkzeug, que ya viene con Flask) y puede ser NULL —
# un inventario sin clave existe pero no lo abre nadie, que es como queda el que migró del
# inventario único hasta que el admin le pone la suya.

SCHEMA_REGISTRO = """
CREATE TABLE IF NOT EXISTS inventarios (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    slug       TEXT NOT NULL UNIQUE,
    nombre     TEXT NOT NULL,
    clave_hash TEXT,
    creado     TEXT NOT NULL
);
"""


def conectar_registro():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def slugificar(nombre, cur=None):
    """"Taller de Electrónica" -> "taller-de-electronica", único y sin pisar una ruta.

    El slug es la URL del inventario y NO se renombra nunca: los permisos guardados
    apuntan al id, pero los links que la gente tiene guardados apuntan al slug.
    """
    base = re.sub(r'[^a-z0-9]+', '-', texto.norm(nombre)).strip('-')[:40] or 'inventario'
    cerrar = cur is None
    con = conectar_registro() if cerrar else None
    cur = con.cursor() if cerrar else cur
    tomados = {f['slug'] for f in cur.execute("SELECT slug FROM inventarios").fetchall()}
    tomados |= SLUGS_RESERVADOS
    slug, n = base, 1
    while slug in tomados:
        n += 1
        slug = f'{base}-{n}'
    if cerrar:
        con.close()
    return slug


def listar_inventarios():
    """Todos, por nombre. Cada uno con `total` (cuántos recursos tiene) y `sin_clave`.

    El total es un agregado, no contenido: es lo único que el admin general ve de adentro,
    y es lo que hace que el panel del registro sirva para algo.
    """
    con = conectar_registro()
    filas = con.execute("SELECT * FROM inventarios ORDER BY nombre COLLATE NOCASE").fetchall()
    con.close()
    salida = []
    for fila in filas:
        d = dict(fila)
        d['total'] = total_recursos(d['slug'])
        d['sin_clave'] = not d['clave_hash']
        salida.append(d)
    return salida


def inventario(slug):
    """La fila de un inventario por slug, o None. Cacheada por request: la piden el gate,
    los permisos, la conexión y el header, todos en el mismo ciclo."""
    if not slug:
        return None
    cache = None
    if has_request_context():
        cache = g.setdefault('_inventarios', {})
        if slug in cache:
            return cache[slug]
    con = conectar_registro()
    fila = con.execute("SELECT * FROM inventarios WHERE slug = ?", (slug,)).fetchone()
    con.close()
    fila = dict(fila) if fila else None
    if cache is not None:
        cache[slug] = fila
    return fila


def inventario_por_id(inv_id):
    con = conectar_registro()
    fila = con.execute("SELECT * FROM inventarios WHERE id = ?", (inv_id,)).fetchone()
    con.close()
    return dict(fila) if fila else None


def crear_inventario(nombre, clave):
    """Crea la fila y el archivo. Devuelve la fila, o None si el nombre viene vacío.

    La clave la pone el admin general acá y es la del inventario: no hay cambio de clave
    desde adentro (si se pierde, se re-fija desde el mismo panel donde se puso).
    """
    nombre = ' '.join((nombre or '').split())[:80]
    if len(nombre) < 2:
        return None
    con = conectar_registro()
    cur = con.cursor()
    slug = slugificar(nombre, cur)
    cur.execute(
        "INSERT INTO inventarios (slug, nombre, clave_hash, creado) VALUES (?,?,?,?)",
        (slug, nombre, generate_password_hash(clave) if clave else None,
         ahora().strftime('%Y-%m-%d %H:%M:%S')))
    con.commit()
    con.close()
    init_inventario(slug)
    return inventario(slug)


def renombrar_inventario(inv_id, nombre):
    """Cambia el nombre visible. El slug NO se toca: es la URL que la gente ya tiene
    guardada, y el ámbito de los permisos apunta al id, así que nada se rompe."""
    nombre = ' '.join((nombre or '').split())[:80]
    if len(nombre) < 2:
        return False
    con = conectar_registro()
    con.execute("UPDATE inventarios SET nombre = ? WHERE id = ?", (nombre, inv_id))
    con.commit()
    con.close()
    return True


def fijar_clave(inv_id, clave):
    """Pone (o repone) la clave del inventario. Es el botón de pánico: cambia la huella,
    así que las sesiones de quien había entrado con la anterior dejan de valer en el
    request siguiente (ver `_acceso_encargado`)."""
    if not clave:
        return False
    con = conectar_registro()
    con.execute("UPDATE inventarios SET clave_hash = ? WHERE id = ?",
                (generate_password_hash(clave), inv_id))
    con.commit()
    con.close()
    return True


def eliminar_inventario(inv_id):
    """Borra el inventario entero: respalda el .db, lo borra, saca la fila del registro y
    limpia de `accesos.db` todo permiso que apuntara ahí.

    Sin ese último paso quedarían claves colgadas (`inv:7/gestion.editar`) que un id
    reciclado por AUTOINCREMENT podría llegar a revivir.
    """
    fila = inventario_por_id(inv_id)
    if fila is None:
        return False
    ruta = os.path.join(DIR_INVENTARIOS, f"{fila['slug']}.db")
    if os.path.exists(ruta):
        # El último respaldo queda: borrar un inventario por error no puede ser definitivo.
        respaldos.respaldar(ruta, f"inv{fila['id']}", TABLA_TESTIGO)
        os.remove(ruta)
    con = conectar_registro()
    con.execute("DELETE FROM inventarios WHERE id = ?", (inv_id,))
    con.commit()
    con.close()
    accesos.purgar_ambito(f"inv:{fila['id']}")
    return True


def total_recursos(slug):
    """Cuántos recursos tiene, sin abrir el inventario para escribir. -1 si el archivo no
    está (un inventario recién creado que todavía no se inicializó, o uno que perdió su
    .db): el panel lo muestra como un aviso y no como un cero, que mentiría."""
    ruta = os.path.join(DIR_INVENTARIOS, f'{slug}.db')
    if not os.path.exists(ruta):
        return -1
    try:
        con = sqlite3.connect(f'file:{ruta}?mode=ro', uri=True)
        try:
            return con.execute(f"SELECT COUNT(*) FROM {TABLA_TESTIGO}").fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error:
        return -1


# ---------------------------------------------------------------------------
# Cuál es el inventario de ESTE request
# ---------------------------------------------------------------------------
# Tres fuentes, en orden: el forzado (scripts de consola y el arranque, que corren sin
# request), la URL (`/gestion/<inv>/…`) y la sesión (`inv_activo`, que es lo que le
# permite al agente saber de qué inventario está hablando cuando el chat se abre en
# `/agente` y no adentro de una ficha).

_FORZADO = None


@contextlib.contextmanager
def usando(slug):
    """Fija el inventario activo a mano. Para el arranque, `actualizar.py` y cualquier
    cosa que corra fuera de un request."""
    global _FORZADO
    previo, _FORZADO = _FORZADO, slug
    try:
        yield
    finally:
        _FORZADO = previo


def slug_activo():
    if _FORZADO:
        return _FORZADO
    if not has_request_context():
        return None
    return getattr(g, 'inv', None) or session.get('inv_activo')


def inventario_activo():
    return inventario(slug_activo())


def db_path():
    """Hook de crud.py: el archivo del inventario activo.

    Revienta si no hay ninguno, y es a propósito: significa que algo llamó al CRUD de
    gestión fuera de un inventario, y devolver una base cualquiera sería peor. En la web no
    puede pasar (el blueprint lleva el `<inv>` en la URL); en el agente tampoco, porque sin
    inventario activo no hay `gestion.leer` y las tools ni se le ofrecen al modelo.
    """
    inv = inventario_activo()
    if inv is None:
        raise RuntimeError(
            "No hay inventario activo: se pidió la DB de gestión fuera de un inventario.")
    return os.path.join(DIR_INVENTARIOS, f"{inv['slug']}.db")


def prefijo_backup():
    """Hook de crud.py. Va por id y no por slug para que dos slugs parecidos ("taller" y
    "taller-2") no compartan rotación: `respaldos.listar` globea `<prefijo>-*.db`."""
    inv = inventario_activo()
    return f"inv{inv['id']}" if inv else PREFIJO_BACKUP_REGISTRO


def ambito():
    """El ámbito de `accesos` para el inventario activo: `inv:7`.

    Por id y no por slug para que el ámbito sobreviva a cualquier cosa que se le haga al
    nombre; el slug es de la URL, el id es de los permisos.
    """
    inv = inventario_activo()
    return f"inv:{inv['id']}" if inv else None


def init_inventario(slug):
    """Crea/migra/respalda el .db de UN inventario, con el motor de siempre."""
    os.makedirs(DIR_INVENTARIOS, exist_ok=True)
    with usando(slug):
        crud.init_db(sys.modules[__name__])

# Un recurso NUNCA se borra: se da de baja (ver `dar_de_baja` y la tabla `recurso_bajas`).
# Por eso "Dado de baja" NO está acá: no es un estado que se elija a mano en el formulario
# ni desde el chat (esta lista es también el enum de las tools, ver agente/tools/esquemas.py),
# lo pone sólo el alta de una baja, que exige decir qué le pasó.
ESTADO_BAJA = "Dado de baja"
ESTADOS_RECURSO = ["Funcional", "Dañado usable", "Roto"]
# Qué le pasó al recurso que se da de baja. "Otro" existe para no bloquear una baja rara:
# el detalle libre de al lado es lo que la explica.
MOTIVOS_BAJA = ["Uso", "Desgaste", "Extravío", "Rotura", "Otro"]
# "" primero: permite dejar el valor sin definir (recursos previos al inventario).
VALORES_RECURSO = ["", "Básico", "Secundario", "Alto valor"]
# Sugerencias de lugar para el desglose por unidad (templates/gestion/detalle.html): NUNCA
# restringen el valor, sólo aparecen como opciones de autocompletado — hace falta poder
# escribir excepciones como "panel solar instalado en el techo".
LUGARES_RECURSO = ["Laboratorio Armario 1", "Laboratorio Armario 2", "Laboratorio",
                    "Taller", "Taller Armario 3", "Taller Armario 4"]

# Formato de `recursos.fecha_revision`. La columna es TEXT y el inventario importado del
# sheet trae fechas cortas sin año ("24/4"): conviven, pero lo que se carga de acá en más
# lleva el año. El agente importa esta constante para no tener dos formatos distintos.
FORMATO_FECHA_REVISION = '%d/%m/%Y'

# Configuración declarativa de cada entidad: campos del form, columnas del listado
# y relaciones M2M editables desde su formulario. Los campos de relación usan el
# prefijo "rel_" para no colisionar con nombres de columnas.
ENTIDADES = {
    'recursos': {
        'tabla': 'recursos',
        'singular': 'Recurso',
        'plural': 'Inventario',
        'descripcion': '',
        'campos': [
            {'nombre': 'nombre', 'label': 'Nombre', 'tipo': 'text', 'requerido': True},
            {'nombre': 'tipo', 'label': 'Tipo', 'tipo': 'text', 'ayuda': 'Ej: Instrumento, Equipo, Estructura, Material'},
            {'nombre': 'cantidad', 'label': 'Cantidad', 'tipo': 'number'},
            {'nombre': 'descripcion', 'label': 'Descripción', 'tipo': 'textarea'},
            # No hay campo `ubicacion`: la ubicación de un recurso es siempre la lista de sus
            # unidades (recurso_unidades), incluso para uno con una sola unidad. Se carga desde
            # la ficha ("Ubicación", ver secciones_detalle), no desde este form — ver
            # agent_docs/gestion-conocimiento.md.
            {'nombre': 'estado', 'label': 'Estado', 'tipo': 'select', 'opciones': ESTADOS_RECURSO},
            {'nombre': 'valor', 'label': 'Valor', 'tipo': 'select', 'opciones': VALORES_RECURSO, 'ayuda': 'Importancia del recurso dentro del inventario'},
            # `boton_hoy` (el formato de la fecha) le pone al lado el botón HOY, ver
            # templates/crud/form.html.
            {'nombre': 'fecha_revision', 'label': 'Última revisión', 'tipo': 'text', 'boton_hoy': FORMATO_FECHA_REVISION, 'ayuda': 'Fecha del último control de inventario (día/mes/año). En un alta arranca en hoy'},
        ],
        # 'valor' no está acá a propósito: sigue siendo un campo real (se carga y edita
        # desde la ficha, y el asistente lo usa), pero no tiene columna propia en el
        # listado — se ve en el detalle de cada recurso.
        'columnas': [('nombre', 'NOMBRE'), ('cantidad', 'CANT.'), ('estado', 'ESTADO')],
        'relaciones': [],
        # Un recurso no se borra nunca: se da de baja (ver `dar_de_baja`). El flag lo lee
        # crud.py y cierra la ruta genérica de eliminar para este slug, así no queda una
        # puerta abierta por URL ni por el chat (agente/tools/entidades.py lo mira igual).
        'sin_eliminar': True,
        # Términos alternativos (no necesariamente sinónimos estrictos: "zapatilla" y
        # "alargue" son cosas distintas pero se confunden) que completa el asistente
        # (agente/tools/esquemas.py), nunca el humano: a propósito NO está en 'campos', así
        # que ni el form web (templates/crud/form.html) ni la ficha de detalle ni la ficha
        # de confirmación del chat (agente/tools/fichas.py::_campos_validos) la ven. crud.py
        # la usa para la segunda pasada de búsqueda y para el whitelist de escritura de
        # guardar_entidad(). Ver dev-log/DECISIONS.md 2026-08-08 y 2026-08-21: el
        # override consciente de por qué esta vez sí conviene una columna por fila.
        'campo_alias': 'alias',
    },
}

# Tablas a limpiar cuando se elimina un recurso. Hoy ningún recurso se elimina (ver
# `sin_eliminar` arriba), así que para 'recursos' esto no llega a correr nunca; queda
# declarado porque el motor lo exige y porque una entidad futura del área sí lo va a usar. `recurso_unidades` y `kit_items` no son
# relaciones M2M de verdad (son el desglose por unidad y los sub-recursos de un kit, ver
# más abajo) pero el mecanismo de limpieza es idéntico: borrar filas por `recurso_id`.
LIMPIEZA_M2M = {
    'recursos': [('recurso_unidades', 'recurso_id'), ('kit_items', 'recurso_id')],
}

# El schema de UN inventario (`inventarios/<slug>.db`). El del registro, que vive en
# gestion.db, es SCHEMA_REGISTRO — son dos bases distintas y ninguna referencia a la otra.
SCHEMA = """
CREATE TABLE IF NOT EXISTS recursos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    tipo TEXT DEFAULT '',
    descripcion TEXT DEFAULT '',
    estado TEXT DEFAULT 'Funcional',
    cantidad TEXT DEFAULT '',
    valor TEXT DEFAULT '',
    fecha_revision TEXT DEFAULT '',
    fotos TEXT DEFAULT '[]',
    alias TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS recurso_unidades (
    recurso_id INTEGER NOT NULL,
    numero INTEGER NOT NULL,
    ubicacion TEXT DEFAULT '',
    UNIQUE(recurso_id, numero)
);
CREATE TABLE IF NOT EXISTS kit_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recurso_id INTEGER NOT NULL,
    titulo TEXT NOT NULL,
    cantidad TEXT DEFAULT '',
    recurso_asignado TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS recurso_bajas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recurso_id INTEGER NOT NULL,
    recurso_nombre TEXT NOT NULL,
    motivo TEXT NOT NULL,
    detalle TEXT DEFAULT '',
    fecha TEXT DEFAULT '',
    revertida INTEGER DEFAULT 0
);
"""


# --- Reglas propias del área ------------------------------------------------
# El CRUD (rutas, búsqueda, fotos, respaldos) lo pone crud.py. Acá queda sólo lo que
# nombra tablas concretas de gestion.db, que es lo que el motor no puede saber.

def migrar(cur):
    """Adapta una gestion.db creada con un schema anterior (ALTER aditivo + renombres)."""
    existentes = {c[1] for c in cur.execute("PRAGMA table_info(recursos)").fetchall()}
    # 'utilidad' pasó a llamarse 'valor'. RENAME COLUMN conserva los datos ya cargados;
    # va antes del ALTER aditivo para no crear un 'valor' vacío al lado del viejo.
    if 'utilidad' in existentes and 'valor' not in existentes:
        cur.execute("ALTER TABLE recursos RENAME COLUMN utilidad TO valor")
        existentes = {c[1] for c in cur.execute("PRAGMA table_info(recursos)").fetchall()}
    for columna in ('cantidad', 'valor', 'fecha_revision', 'fotos', 'alias'):
        if columna not in existentes:
            default = '[]' if columna == 'fotos' else ''
            cur.execute(f"ALTER TABLE recursos ADD COLUMN {columna} TEXT DEFAULT '{default}'")

    # `drive_url` se eliminó: la escuela dejó de usar Drive y la fuente de verdad de gestión
    # pasó a ser esta DB. Es la primera migración DESTRUCTIVA del módulo, así que se corrió
    # habiendo verificado que la columna estaba vacía en las 89 filas de las tres tablas; el
    # respaldo previo de `respaldos.respaldar()` (que corre antes que esto, en init_db) es la red por
    # si alguna instalación tenía links cargados.
    if 'drive_url' in existentes:
        cur.execute("ALTER TABLE recursos DROP COLUMN drive_url")

    # `recurso_ubicaciones` (agregado por lugar, sin identidad de unidad) se reemplazó por
    # `recurso_unidades` (una fila por unidad física, con su propio número) el 2026-08-22:
    # ver dev-log/DECISIONS.md. Cada fila vieja (lugar, cantidad) se reparte en unidades
    # numeradas secuenciales por recurso, mismo orden que usaba `ubicaciones_recurso`.
    tablas = {r['name'] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if 'recurso_ubicaciones' in tablas:
        for fila_r in cur.execute("SELECT DISTINCT recurso_id FROM recurso_ubicaciones").fetchall():
            rid = fila_r['recurso_id']
            siguiente = 1
            filas = cur.execute(
                "SELECT ubicacion, cantidad FROM recurso_ubicaciones WHERE recurso_id = ? "
                "ORDER BY ubicacion COLLATE NOCASE", (rid,)).fetchall()
            for fila in filas:
                for _ in range(_int(fila['cantidad'])):
                    cur.execute(
                        "INSERT OR IGNORE INTO recurso_unidades (recurso_id, numero, ubicacion) VALUES (?,?,?)",
                        (rid, siguiente, fila['ubicacion']))
                    siguiente += 1
        cur.execute("DROP TABLE recurso_ubicaciones")

    # `ubicacion` de `recursos` (el campo simple de siempre) se reemplazó por la lista de
    # unidades: un recurso ya no tiene "un lugar" y aparte "el desglose", tiene sus unidades
    # (recurso_unidades) y nada más, aunque sea una sola. Antes de sacar la columna, cada
    # recurso que todavía no tenga ninguna unidad propia (la mayoría, que nunca tocó el
    # desglose) se siembra 1..cantidad (mínimo 1) con el valor que tenía `ubicacion`, para no
    # perder el dato ya cargado. 2026-08-22.
    if 'ubicacion' in existentes:
        sin_unidades = cur.execute(
            "SELECT id, cantidad, ubicacion FROM recursos WHERE id NOT IN "
            "(SELECT DISTINCT recurso_id FROM recurso_unidades)").fetchall()
        for r in sin_unidades:
            n = max(_int(r['cantidad']), 1)
            cur.executemany(
                "INSERT INTO recurso_unidades (recurso_id, numero, ubicacion) VALUES (?,?,?)",
                [(r['id'], i, r['ubicacion'] or '') for i in range(1, n + 1)])
        cur.execute("ALTER TABLE recursos DROP COLUMN ubicacion")

    # Hasta el 2026-09-02 "Dado de baja" era un estado más del desplegable y no dejaba
    # rastro de qué le había pasado al recurso. Los que ya estaban dados de baja entran al
    # registro nuevo con motivo "Otro" y el detalle diciendo que la baja es anterior: así
    # /gestion/bajas muestra el inventario completo y no arranca mintiendo por omisión.
    # Idempotente: sólo toma los que todavía no tienen ninguna fila propia.
    for r in cur.execute(
            "SELECT id, nombre FROM recursos WHERE estado = ? AND id NOT IN "
            "(SELECT recurso_id FROM recurso_bajas)", (ESTADO_BAJA,)).fetchall():
        cur.execute(
            "INSERT INTO recurso_bajas (recurso_id, recurso_nombre, motivo, detalle, fecha) "
            "VALUES (?,?,?,?,'')",
            (r['id'], r['nombre'], 'Otro', 'Baja anterior al registro: no se anotó el motivo.'))


# No hay `seed`: un inventario nuevo arranca VACÍO a propósito. Los datos de ejemplo
# tenían sentido cuando el área era una sola base que se creaba una vez; ahora se crea una
# por inventario y sembrar el banco de ensayo solar en cada uno sería ruido que después hay
# que borrar a mano.


# Qué decir cuando un UNIQUE de la DB rechaza el guardado (si no, sale un 500 pelado).
# Vacío: ninguna entidad de este módulo tiene un UNIQUE de negocio (a diferencia de
# historia.personas, que sí lo necesita — ver historia.ERROR_DUPLICADO).
ERROR_DUPLICADO = {}


# Umbral del chip "sin revisar hace +6 meses" del listado (rediseño de
# templates/gestion/lista.html). 183 días ~ 6 meses.
UMBRAL_SIN_REVISAR_DIAS = 183


def _revisado_vencido(fecha_texto):
    """True si `fecha_revision` está vacía o pasó el umbral de 6 meses.

    Las fechas cortas sin año que trae el inventario importado del sheet (ver
    FORMATO_FECHA_REVISION) no se pueden ubicar en el tiempo: no se marcan vencidas
    (mejor un falso negativo suelto que marcar vencido todo el inventario viejo)."""
    fecha_texto = (fecha_texto or '').strip()
    if not fecha_texto:
        return True
    try:
        fecha = datetime.strptime(fecha_texto, FORMATO_FECHA_REVISION)
    except ValueError:
        return False
    return (ahora() - fecha).days > UMBRAL_SIN_REVISAR_DIAS


def valores_iniciales(slug):
    """Con qué valores arranca el formulario de alta, antes de que el usuario escriba.

    Dar de alta un recurso ES un control de inventario, así que la fecha de revisión
    arranca en hoy. Antes quedaba vacía y casi ningún recurso terminaba con fecha.
    """
    if slug == 'recursos':
        return {'fecha_revision': ahora().strftime(FORMATO_FECHA_REVISION)}
    return {}


def secciones_detalle(slug, id, cur):
    """Relaciones a mostrar en la vista de detalle."""
    secciones = []
    if slug == 'recursos':
        # La ubicación de un recurso es siempre esta lista (recurso_unidades), aunque tenga
        # una sola unidad: no hay un campo aparte para "el lugar principal" — ver
        # agent_docs/gestion-conocimiento.md.
        secciones.append({'titulo': 'Ubicación', 'slug': None,
                          'items': lugares_recurso_agrupado(cur, id), 'tipo': 'ubicaciones'})
        # Un recurso es "kit" en cuanto tiene sub-recursos cargados acá, sin flag aparte
        # (mismo criterio orgánico que el desglose por ubicación). En la ficha la sección
        # es sólo de lectura y sin ítems no aparece: se carga y se edita desde EDITAR.
        secciones.append({'titulo': 'Sub-recursos (kit)', 'slug': None,
                          'items': kit_items_recurso(cur, id), 'tipo': 'kit_items',
                          'oculto_si_vacio': True})
    return secciones


def resultados_extra_busqueda(slug, q, cur):
    """Sub-recursos de un kit que matchean la búsqueda `q`, para mostrar aparte del
    listado principal de recursos (que nunca los muestra sueltos sin buscar)."""
    if slug == 'recursos' and q:
        return buscar_kit_items(cur, q)
    return []


def init_db():
    """Crea/actualiza el registro y pone al día el .db de cada inventario.

    El registro no pasa por `crud.init_db` por lo mismo que `accesos.db`: aquél hace
    `raise` si la tabla testigo está vacía y hay respaldos, y un registro sin inventarios
    es un estado legítimo (es como nace una instalación nueva). Los inventarios en cambio
    SÍ pasan por el motor, uno por uno: es lo que les hace el respaldo rotativo en cada
    arranque y lo que mantiene viva la guarda anti-pérdida de cada archivo.
    """
    os.makedirs(DIR_INVENTARIOS, exist_ok=True)
    respaldos.respaldar(DB_PATH, PREFIJO_BACKUP_REGISTRO, 'inventarios')
    con = conectar_registro()
    con.executescript(SCHEMA_REGISTRO)
    con.commit()
    con.close()
    for fila in listar_inventarios():
        init_inventario(fila['slug'])


def extras_template(vista, slug, id=None):
    """Kwargs extra para el render. En la ficha: la lista fija de lugares, para el datalist
    del mini form de mover/ubicar unidades (templates/gestion/detalle.html). En el listado:
    los lugares de cada recurso (para la columna y el filtro) y qué está vencido. En el
    formulario de edición: los sub-recursos del kit, que se cargan y se borran ahí y no en
    la ficha (templates/gestion/form.html)."""
    if slug == 'recursos' and vista == 'detalle':
        return {'lugares_recurso': LUGARES_RECURSO}
    if slug == 'recursos' and vista == 'editar':
        con = conectar()
        items = kit_items_recurso(con.cursor(), id)
        con.close()
        return {'kit_items': items}
    if slug == 'recursos' and vista == 'lista':
        con = conectar()
        cur = con.cursor()
        filas = cur.execute("SELECT id, fecha_revision FROM recursos").fetchall()
        vencidos = {f['id'] for f in filas if _revisado_vencido(f['fecha_revision'])}
        ubicaciones = lugares_por_recurso(cur)
        con.commit()  # lugares_por_recurso puede crear unidades que faltaban (_asegurar_unidades)
        con.close()
        lugares = sorted({g['ubicacion'] for lugs in ubicaciones.values() for g in lugs if g['ubicacion'] != 'Sin ubicar'},
                          key=texto.norm)
        return {'vencidos_recurso': vencidos, 'lugares_filtro': lugares, 'ubicaciones_recurso': ubicaciones}
    return {}


def contexto_extra():
    """Constantes que necesitan varios templates del área: el estado que marca una baja
    (para no repetir el string suelto en el listado y la ficha), los motivos del cuadro de
    baja del formulario, y cuál es el inventario abierto — que el header muestra al lado
    del título, porque con varios hay que saber en cuál se está escribiendo."""
    return {'estado_baja': ESTADO_BAJA, 'motivos_baja': MOTIVOS_BAJA,
            'inventario': inventario_activo(), 'permiso_accesos': PERMISO_ACCESOS}


# ---------------------------------------------------------------------------
# El gate de un inventario
# ---------------------------------------------------------------------------
# `bp` está montado en `/gestion/<inv>`, y el par preprocessor/url_defaults es lo que hace
# que ningún `url_for('gestion.…')` de los templates tenga que enterarse: el `<inv>` sale
# de la URL al entrar y se vuelve a poner solo al construir cualquier link del área.

@bp.url_value_preprocessor
def _tomar_inventario(endpoint, valores):
    g.inv = (valores or {}).pop('inv', None)
    if inventario(g.inv) is None:
        abort(404)


@bp.url_defaults
def _poner_inventario(endpoint, valores):
    if 'inv' not in valores and getattr(g, 'inv', None):
        valores['inv'] = g.inv


# La clave de un inventario en la sesión: {'<id>': '<huella del hash>'}. Se guarda la
# huella y no un booleano por lo mismo que la sesión de admin guarda la de GESTION_CLAVE
# (ver accesos.huella_clave): re-fijar la clave corta en el acto lo que abría la anterior.
CLAVES_SESION = 'inv_claves'


def _huella(clave_hash):
    return (clave_hash or '')[-12:]


def _acceso_encargado():
    """Hook de `accesos`: lo que aporta haber entrado con la clave del inventario activo.

    Es un acceso que se SUMA al que ya haya (o el único que hay: el encargado del taller no
    tiene por qué ser un dispositivo invitado de nada). Da el juego completo de ESE
    inventario y nada más — en el de al lado esta misma persona no tiene nada.
    """
    inv = inventario_activo()
    if inv is None or not inv['clave_hash']:
        return None
    guardada = (session.get(CLAVES_SESION) or {}).get(str(inv['id']))
    if not guardada or guardada != _huella(inv['clave_hash']):
        return None
    return {'tipo': 'inventario', 'nombre': f"Encargado · {inv['nombre']}",
            'permisos': PERMISOS_AMBITO}


def _entrar_inventario(clave):
    """Hook de `accesos.registrar_acceso`: qué valida `/gestion/<inv>/login`.

    NO hace `session.clear()`, a diferencia del login de admin: entrar al taller no puede
    echarte del laboratorio ni cortarte la conversación del agente.
    """
    inv = inventario_activo()
    if inv is None or not inv['clave_hash'] or not check_password_hash(inv['clave_hash'], clave):
        return False
    session.permanent = True
    claves = dict(session.get(CLAVES_SESION) or {})
    claves[str(inv['id'])] = _huella(inv['clave_hash'])
    session[CLAVES_SESION] = claves
    session['inv_activo'] = inv['slug']
    return True


def _salir_inventario():
    """Ídem para `/gestion/<inv>/salir`: cierra ESTE inventario, no la sesión entera."""
    inv = inventario_activo()
    if inv is not None:
        claves = dict(session.get(CLAVES_SESION) or {})
        claves.pop(str(inv['id']), None)
        session[CLAVES_SESION] = claves
    session.pop('inv_activo', None)


def _contexto_login():
    return {'inventario': inventario_activo()}


accesos.registrar_ambito(ambito)
accesos.registrar_acceso_extra(_acceso_encargado)
accesos.registrar_acceso(bp, PERMISO_LECTURA, entrar=_entrar_inventario,
                         al_salir=_salir_inventario, contexto_login=_contexto_login)
crud.registrar_rutas(bp, sys.modules[__name__])


@bp.before_request
def _recordar_inventario():
    """Deja anotado en la sesión en qué inventario se está trabajando.

    Corre después del gate, así que sólo se anota uno al que el acceso puede entrar. Es lo
    que le permite al asistente saber de qué inventario le están hablando cuando el chat se
    abre en `/agente` y no adentro de una ficha (ver `slug_activo`).
    """
    if g.inv and session.get('inv_activo') != g.inv:
        session['inv_activo'] = g.inv


# ---------------------------------------------------------------------------
# El panel del encargado: quién entra a ESTE inventario
# ---------------------------------------------------------------------------
# Es el panel de `/accesos` pero acotado: sólo reparte las claves del área, sólo ve los
# dispositivos que tienen alguna de este inventario, y su "quitar" saca las de acá y
# ninguna otra (ver accesos.quitar_ambito). El admin general no aparece por ningún lado —
# su comodín no llega a estas claves.

def _catalogo_inventario():
    return [e for e in accesos.CATALOGO_AMBITO if e[3] == GRUPO_PERMISOS]


def _perfiles_inventario():
    """Los presets de siempre menos 'admin': el comodín '*' no es de un encargado."""
    return [(p, accesos.ETIQUETA_PERFIL.get(p, p)) for p in accesos.PERFILES if p != 'admin']


def _render_accesos(link_nuevo=None, link_multiuso=False, error=None):
    catalogo = _catalogo_inventario()
    return render_template(
        'gestion/accesos.html', activo='accesos',
        dispositivos=accesos.listar_dispositivos(ambito()),
        invitaciones=accesos.listar_invitaciones(ambito()),
        grupos=accesos.catalogo_por_grupo(catalogo),
        perfiles=_perfiles_inventario(),
        preset={p: accesos.permisos_de_perfil(p, catalogo) for p, _e in _perfiles_inventario()},
        link_nuevo=link_nuevo, link_multiuso=link_multiuso, error=error)


@bp.route('/accesos')
@accesos.requiere(PERMISO_ACCESOS)
def accesos_panel():
    return _render_accesos()


@bp.route('/accesos/invitar', methods=['POST'])
@accesos.requiere(PERMISO_ACCESOS)
def accesos_invitar():
    etiqueta = ' '.join((request.form.get('etiqueta') or '').split())[:80]
    if len(etiqueta) < 2:
        return _render_accesos(error='Poné para quién es el link (te sirve a vos después).')

    perfil = request.form.get('perfil', 'interno-lectura')
    catalogo = _catalogo_inventario()
    validos = {c for c, _e, _v, _g in catalogo}
    if perfil not in dict(_perfiles_inventario()):
        perfil = 'interno-lectura'
    # La intersección con `validos` es el corte real: un POST a mano con
    # `permisos=accesos.admin` no puede sacar una clave de afuera del inventario.
    marcados = sorted(set(request.form.getlist('permisos')) & validos)
    if not marcados:
        return _render_accesos(error='Elegí al menos un permiso.')
    if marcados != sorted(accesos.permisos_de_perfil(perfil, catalogo)):
        perfil = 'custom'

    multiuso = request.form.get('multiuso') == 'on'
    token = accesos.crear_invitacion(etiqueta, perfil, marcados, multiuso=multiuso,
                                     ambito=ambito())
    return _render_accesos(link_nuevo=url_for('acceso_canjear_ver', token=token,
                                              _external=True),
                           link_multiuso=multiuso)


@bp.route('/accesos/quitar/<int:disp_id>', methods=['POST'])
@accesos.requiere(PERMISO_ACCESOS)
def accesos_quitar(disp_id):
    """Le saca a un dispositivo el acceso a ESTE inventario. Si no le quedaba nada más,
    `quitar_ambito` lo revoca entero; si tenía el agente o el inventario de al lado, eso
    sigue intacto — no es asunto de este panel."""
    accesos.quitar_ambito(disp_id, ambito())
    return redirect(url_for('gestion.accesos_panel'))


@bp.route('/accesos/invitacion/<int:invitacion_id>/borrar', methods=['POST'])
@accesos.requiere(PERMISO_ACCESOS)
def accesos_borrar_invitacion(invitacion_id):
    accesos.borrar_invitacion(invitacion_id, ambito())
    return redirect(url_for('gestion.accesos_panel'))


# ---------------------------------------------------------------------------
# El registro: /gestion, la lista de inventarios
# ---------------------------------------------------------------------------
# Blueprint aparte porque no cuelga de ningún inventario. Su permiso base es None: la
# lista la ve cualquiera que esté identificado —le muestra los que puede abrir— y lo que
# pide `inventarios.admin` son las acciones, marcadas una por una con `requiere()`.
#
# Las rutas de administración cuelgan de `/gestion/admin/...` y no de `/gestion/<id>/...`
# para no chocar con `/gestion/<inv>/<slug>` del área (ver SLUGS_RESERVADOS).

bp_inv = Blueprint('inventarios', __name__, url_prefix='/gestion')


@bp_inv.context_processor
def _contexto_registro():
    from config import ESCUELA_LOGO, ESCUELA_NOMBRE, ESCUELA_VERSION
    return {'escuela_nombre': ESCUELA_NOMBRE, 'escuela_logo': ESCUELA_LOGO,
            'escuela_version': ESCUELA_VERSION, 'area_nombre': 'inventarios',
            'base_template': 'inventarios/base.html'}


def _puede_abrir(fila):
    """¿Este acceso entra a este inventario sin tipear la clave?

    Se pregunta por el ámbito de ESA fila y no con `puede()`, porque `puede()` responde
    siempre sobre el inventario activo y acá se está listando otro. El admin general da que
    no, y es correcto: su comodín no llega a `gestion.leer` (ver PERMISOS_AMBITO).
    """
    if fila['clave_hash'] and (session.get(CLAVES_SESION) or {}).get(
            str(fila['id'])) == _huella(fila['clave_hash']):
        return True
    return accesos.tiene(accesos.permisos_en(f"inv:{fila['id']}"), PERMISO_LECTURA)


@bp_inv.route('/')
def panel():
    """La lista. Para el admin general es el tablero de altas y bajas; para el resto es
    nada más la puerta: los inventarios que puede abrir, y un candado en los otros."""
    filas = listar_inventarios()
    for f in filas:
        f['abre'] = _puede_abrir(f)
    return render_template('inventarios/panel.html', inventarios=filas, activo='inventarios',
                           error=request.args.get('error'))


@bp_inv.route('/admin/crear', methods=['POST'])
@accesos.requiere(PERMISO_REGISTRO)
def crear():
    fila = crear_inventario(request.form.get('nombre', ''), request.form.get('clave', ''))
    if fila is None:
        return redirect(url_for('inventarios.panel', error='Poné un nombre.'))
    return redirect(url_for('inventarios.panel'))


@bp_inv.route('/admin/<int:inv_id>/renombrar', methods=['POST'])
@accesos.requiere(PERMISO_REGISTRO)
def renombrar(inv_id):
    renombrar_inventario(inv_id, request.form.get('nombre', ''))
    return redirect(url_for('inventarios.panel'))


@bp_inv.route('/admin/<int:inv_id>/clave', methods=['POST'])
@accesos.requiere(PERMISO_REGISTRO)
def clave(inv_id):
    if not fijar_clave(inv_id, request.form.get('clave', '')):
        return redirect(url_for('inventarios.panel', error='La clave no puede quedar vacía.'))
    return redirect(url_for('inventarios.panel'))


@bp_inv.route('/admin/<int:inv_id>/eliminar', methods=['POST'])
@accesos.requiere(PERMISO_REGISTRO)
def eliminar(inv_id):
    """Borra el inventario entero. El formulario exige escribir el nombre: es lo único
    irreversible del panel (queda el último respaldo, ver `eliminar_inventario`)."""
    fila = inventario_por_id(inv_id)
    if fila is None:
        abort(404)
    if texto.norm(request.form.get('confirmar', '')) != texto.norm(fila['nombre']):
        return redirect(url_for('inventarios.panel',
                                error='Para eliminar hay que escribir el nombre exacto.'))
    eliminar_inventario(inv_id)
    return redirect(url_for('inventarios.panel'))


accesos.registrar_acceso(bp_inv, None, endpoint_default='panel')


def _int(texto):
    """Entero desde texto de la DB/form; 0 si está vacío o no es número."""
    try:
        return int(str(texto).strip())
    except (TypeError, ValueError):
        return 0


@bp.route('/alias')
@accesos.requiere(PERMISO_ALIAS)
def alias_lista():
    """Consulta de solo lectura: qué alias le completó el asistente a cada recurso.

    Es la única ventana al campo oculto (`recursos.alias`) — no hay edición acá ni en
    ningún otro lado de la web a propósito, ver `agent_docs/gestion-conocimiento.md`.
    """
    con = conectar()
    filas = con.execute(
        "SELECT nombre, alias FROM recursos ORDER BY nombre COLLATE NOCASE").fetchall()
    con.close()
    return render_template('gestion/alias_lista.html', filas=filas, activo='alias')


def _stock(cur, rid):
    """Stock del recurso (recursos.cantidad como entero); None si no existe la fila.
    0 = sin stock definido → sin tope (cantidad vacía o no numérica). La usa el agente
    (agente/tools/ubicaciones.py) para saber si un id de recurso existe de verdad."""
    row = cur.execute("SELECT cantidad FROM recursos WHERE id = ?", (rid,)).fetchone() if rid else None
    return None if row is None else _int(row['cantidad'])


# --- Bajas de recursos --------------------------------------------------------
# Un recurso NUNCA se borra del inventario: cuando deja de existir físicamente (se gastó,
# se rompió, se perdió) se le da de baja y queda en la ficha con estado ESTADO_BAJA, fuera
# del listado salvo que se pida verlo. Lo que se pierde al borrar una fila —qué era, cuántos
# había, dónde estaba, sus fotos— es justamente lo que hace falta para rendir cuentas
# después, y una escuela rinde cuentas de lo que se le rompe. La contracara es que la baja
# exige decir qué pasó: `recurso_bajas` es el registro, y sin motivo no hay baja.

def dar_de_baja(cur, rid, motivo, detalle=''):
    """Da de baja un recurso: lo deja en ESTADO_BAJA y anota la fila del registro.

    Devuelve el motivo guardado, o None si el recurso no existe o el motivo viene vacío
    (que es la única validación: el detalle es opcional, igual que la fecha exacta de lo
    que pasó, que nadie suele recordar). Un recurso ya dado de baja se puede volver a dar
    de baja sin romper nada: suma otra fila al registro, que es un historial, no un estado.
    """
    motivo = (motivo or '').strip()
    fila = cur.execute("SELECT nombre FROM recursos WHERE id = ?", (rid,)).fetchone()
    if fila is None or not motivo:
        return None
    cur.execute(
        "INSERT INTO recurso_bajas (recurso_id, recurso_nombre, motivo, detalle, fecha) VALUES (?,?,?,?,?)",
        (rid, fila['nombre'], motivo, (detalle or '').strip(),
         ahora().strftime(FORMATO_FECHA_REVISION)))
    cur.execute("UPDATE recursos SET estado = ? WHERE id = ?", (ESTADO_BAJA, rid))
    return motivo


def revertir_baja(cur, rid):
    """Deshace la última baja de un recurso (el error de dedo del que la dio).

    La fila del registro NO se borra: queda marcada como revertida, porque el registro es
    el historial de lo que se decidió y no la lista de lo que hoy está de baja. El estado
    vuelve al primero de ESTADOS_RECURSO ("Funcional"): cuál era antes de la baja no se
    guarda, y si estaba roto se corrige a mano desde el mismo formulario.
    """
    fila = cur.execute("SELECT estado FROM recursos WHERE id = ?", (rid,)).fetchone()
    if fila is None or fila['estado'] != ESTADO_BAJA:
        return False
    ultima = cur.execute(
        "SELECT id FROM recurso_bajas WHERE recurso_id = ? AND revertida = 0 ORDER BY id DESC LIMIT 1",
        (rid,)).fetchone()
    if ultima:
        cur.execute("UPDATE recurso_bajas SET revertida = 1 WHERE id = ?", (ultima['id'],))
    cur.execute("UPDATE recursos SET estado = ? WHERE id = ?", (ESTADOS_RECURSO[0], rid))
    return True


def bajas_registro(cur):
    """El registro completo, la última primero, para /gestion/bajas.

    `recurso_nombre` es la foto del nombre al momento de la baja y `nombre_actual` el de
    hoy: si alguien renombró el recurso después, el registro sigue diciendo qué se dio de
    baja. `existe` es False si la fila del recurso desapareció igual (una baja de antes de
    esta regla, o un borrado desde sqlite a mano): la entrada se muestra sin link."""
    filas = cur.execute(
        "SELECT b.id, b.recurso_id, b.recurso_nombre, b.motivo, b.detalle, b.fecha, b.revertida, "
        "r.nombre AS nombre_actual, r.estado AS estado_actual "
        "FROM recurso_bajas b LEFT JOIN recursos r ON r.id = b.recurso_id "
        "ORDER BY b.id DESC").fetchall()
    return [dict(f, existe=f['nombre_actual'] is not None) for f in filas]


@bp.route('/recursos/<int:id>/baja', methods=['POST'])
@accesos.requiere(PERMISO_ESCRITURA)
def recurso_baja(id):
    con = conectar()
    cur = con.cursor()
    hecho = dar_de_baja(cur, id, request.form.get('motivo', ''),
                        request.form.get('detalle', ''))
    con.commit()
    con.close()
    # Sin motivo se vuelve al formulario, que es donde está el cuadro de la baja; con la
    # baja hecha, a la ficha, que ya la muestra dada de baja.
    if not hecho:
        return redirect(url_for('gestion.editar', slug='recursos', id=id))
    return redirect(url_for('gestion.detalle', slug='recursos', id=id))


@bp.route('/recursos/<int:id>/baja/revertir', methods=['POST'])
@accesos.requiere(PERMISO_ESCRITURA)
def recurso_baja_revertir(id):
    con = conectar()
    revertir_baja(con.cursor(), id)
    con.commit()
    con.close()
    return redirect(url_for('gestion.detalle', slug='recursos', id=id))


@bp.route('/bajas')
@accesos.requiere(PERMISO_AUDITORIA)
def bajas_lista():
    """Registro de bajas. Mismo permiso que el chip "mostrar dados de baja" del listado
    (`gestion.auditoria`): lo que salió del inventario es información de auditoría, no
    parte de la consulta del día a día."""
    con = conectar()
    filas = bajas_registro(con.cursor())
    con.close()
    return render_template('gestion/bajas.html', filas=filas, activo='bajas')


# --- Desglose de recursos por unidad ------------------------------------------
# `recurso_unidades` es OPCIONAL a propósito: la mayoría de los recursos tiene un solo lugar
# (el campo `ubicacion` de siempre) y nunca toca esta tabla. Sólo entra en juego cuando
# alguien reparte las unidades de un mismo recurso en más de un sitio — y a diferencia del
# viejo desglose agregado (recurso_ubicaciones, hasta el 2026-08-21), cada unidad tiene su
# propio número: permite pedirle al agente cosas puntuales ("el destornillador 3 y el 5
# están en el taller"), no sólo cantidades sueltas. El desglose NUNCA tiene que estar
# completo: una unidad sin `ubicacion` es "sin ubicar", no un error. El pedido explícito fue
# que mover algo entre lugares no se bloquee por no tener el desglose previo cargado, mismo
# criterio de "avisar, no bloquear" que se usaba con el stock de los préstamos (ver
# dev-log/DECISIONS.md 2026-08-11, 2026-08-21 y 2026-08-22).

def _asegurar_unidades(cur, rid):
    """Crea las unidades 1..cantidad que todavía no existan (sin ubicación, `''`). Un recurso
    siempre tiene al menos la unidad 1, aunque `cantidad` esté vacía o en 0: sin esto no habría
    ninguna fila donde guardar su ubicación. No borra unidades de más si `cantidad` bajó
    después: mismo criterio de no perder datos. No hace nada si el recurso no existe."""
    fila = cur.execute("SELECT cantidad FROM recursos WHERE id = ?", (rid,)).fetchone()
    if fila is None:
        return
    cantidad = max(_int(fila['cantidad']), 1)
    existentes = {f['numero'] for f in
                  cur.execute("SELECT numero FROM recurso_unidades WHERE recurso_id = ?", (rid,)).fetchall()}
    faltantes = [n for n in range(1, cantidad + 1) if n not in existentes]
    if faltantes:
        cur.executemany("INSERT INTO recurso_unidades (recurso_id, numero, ubicacion) VALUES (?,?,'')",
                        [(rid, n) for n in faltantes])


def unidades_recurso(cur, rid):
    """Unidades individuales de un recurso: [{'numero':, 'ubicacion':}], por número.
    Auto-completa 1..cantidad si faltan filas (ver _asegurar_unidades)."""
    _asegurar_unidades(cur, rid)
    filas = cur.execute(
        "SELECT numero, ubicacion FROM recurso_unidades WHERE recurso_id = ? ORDER BY numero", (rid,)).fetchall()
    return [{'numero': f['numero'], 'ubicacion': f['ubicacion']} for f in filas]


def lugares_recurso_agrupado(cur, rid):
    """Unidades de un recurso agrupadas por lugar, para la vista de detalle y para
    contarle al agente cómo quedó el desglose: [{'ubicacion':, 'numeros': [..]}], ordenado
    por lugar con "Sin ubicar" al final. Nunca vacía para un recurso que existe (al menos
    la unidad 1, ver _asegurar_unidades); lista vacía = el id no corresponde a ningún recurso."""
    grupos = {}
    for u in unidades_recurso(cur, rid):
        grupos.setdefault(u['ubicacion'], []).append(u['numero'])
    resultado = [{'ubicacion': lugar, 'numeros': numeros}
                 for lugar, numeros in sorted(grupos.items(), key=lambda kv: texto.norm(kv[0])) if lugar]
    if grupos.get(''):
        resultado.append({'ubicacion': 'Sin ubicar', 'numeros': grupos['']})
    return resultado


def lugares_por_recurso(cur):
    """Lugares de cada recurso con cuántas unidades tiene en cada uno, para el listado:
    {id: [{'ubicacion': 'Taller', 'cantidad': 4}, ...]} o {id: [{'ubicacion': 'Sin ubicar', ...}]}.
    Reusa lugares_recurso_agrupado por id; con ~90 recursos el costo extra es despreciable
    (mismo criterio que la búsqueda, ver agent_docs/gestion-conocimiento.md)."""
    ids = [r['id'] for r in cur.execute("SELECT id FROM recursos").fetchall()]
    return {rid: [{'ubicacion': g['ubicacion'], 'cantidad': len(g['numeros'])}
                  for g in lugares_recurso_agrupado(cur, rid)] for rid in ids}


def _resolver_ubicacion_existente(cur, rid, nombre):
    """Si ya hay una unidad de ESTE recurso cuyo lugar coincide sin importar mayúsculas ni
    acentos, devuelve el string tal como está guardado (para no fragmentar "Taller" y
    "taller " en dos grupos distintos). Si no hay ninguna, devuelve `nombre` recortado."""
    nombre = (nombre or '').strip()
    if not nombre:
        return nombre
    objetivo = texto.norm(nombre)
    filas = cur.execute(
        "SELECT DISTINCT ubicacion FROM recurso_unidades WHERE recurso_id = ? AND ubicacion != ''", (rid,)).fetchall()
    for fila in filas:
        if texto.norm(fila['ubicacion']) == objetivo:
            return fila['ubicacion']
    return nombre


def mover_unidades(cur, rid, destino, numeros=None, cantidad=None, origen=None):
    """Fija `destino` como lugar de unidades puntuales de un recurso.

    Por número exacto (`numeros`): mueve esas unidades; las que no existan en el recurso
    quedan en `avisos` y se ignoran, sin bloquear el resto. Por `cantidad` (sin decir cuáles):
    elige esa cantidad de candidatas, primero las que están en `origen` si se indicó, después
    las "sin ubicar", después cualquiera — si no hay suficientes, mueve las que haya y avisa,
    nunca rechaza el movimiento.
    """
    destino = _resolver_ubicacion_existente(cur, rid, (destino or '').strip())
    if not destino:
        return {'ok': False, 'error': 'Falta el lugar de destino.', 'avisos': []}

    todas = unidades_recurso(cur, rid)
    avisos = []

    if numeros:
        existentes = {u['numero'] for u in todas}
        elegidas = [n for n in numeros if n in existentes]
        invalidas = [n for n in numeros if n not in existentes]
        if invalidas:
            avisos.append(f'no existen las unidades {", ".join(str(n) for n in invalidas)} de este recurso: '
                          f'se ignoraron')
    else:
        cantidad = cantidad or 0
        origen = _resolver_ubicacion_existente(cur, rid, origen) if origen else ''
        candidatas = [u['numero'] for u in todas if u['ubicacion'] == origen] if origen else []
        candidatas += [u['numero'] for u in todas if u['ubicacion'] == '' and u['numero'] not in candidatas]
        candidatas += [u['numero'] for u in todas if u['numero'] not in candidatas]
        elegidas = candidatas[:cantidad]
        if len(elegidas) < cantidad:
            avisos.append(f'sólo se encontraron {len(elegidas)} unidades para mover, no {cantidad}')

    if not elegidas:
        return {'ok': False, 'error': 'No hay unidades para mover.', 'avisos': avisos}

    cur.executemany("UPDATE recurso_unidades SET ubicacion = ? WHERE recurso_id = ? AND numero = ?",
                    [(destino, rid, n) for n in elegidas])
    return {'ok': True, 'movidas': elegidas, 'avisos': avisos}


# Rutas propias (no son una entidad de ENTIDADES): mover unidades puntuales o dejarlas sin
# ubicar desde la ficha del recurso. Sin tope contra `recursos.cantidad` a propósito, mismo
# criterio de no bloquear.
@bp.route('/recursos/<int:id>/unidades/mover', methods=['POST'])
@accesos.requiere(PERMISO_ESCRITURA)
def unidad_mover(id):
    numeros = [_int(n) for n in request.form.get('numeros', '').split(',') if n.strip()]
    ubicacion = request.form.get('ubicacion', '').strip()
    if numeros and ubicacion:
        con = conectar()
        cur = con.cursor()
        cur.execute("SELECT 1 FROM recursos WHERE id = ?", (id,))
        if cur.fetchone():
            mover_unidades(cur, id, ubicacion, numeros=numeros)
            con.commit()
        con.close()
    return redirect(url_for('gestion.detalle', slug='recursos', id=id))


@bp.route('/recursos/<int:id>/unidades/quitar', methods=['POST'])
@accesos.requiere(PERMISO_ESCRITURA)
def unidad_quitar(id):
    # `numeros` (CSV) para la selección múltiple de la ficha; `numero` suelto sigue andando.
    nums = [_int(n) for n in request.form.get('numeros', '').split(',') if n.strip()]
    uno = _int(request.form.get('numero', ''))
    if uno:
        nums.append(uno)
    if nums:
        con = conectar()
        cur = con.cursor()
        cur.executemany("UPDATE recurso_unidades SET ubicacion = '' WHERE recurso_id = ? AND numero = ?",
                        [(id, n) for n in nums])
        con.commit()
        con.close()
    return redirect(url_for('gestion.detalle', slug='recursos', id=id))


# --- Kits: sub-recursos de un recurso ------------------------------------------
# `kit_items` es OPCIONAL a propósito, mismo criterio que `recurso_unidades`: un recurso
# es un "kit" en cuanto tiene sub-recursos cargados, no hay tipo/flag aparte. Cada
# sub-recurso es sólo título + cantidad + "recurso asignado" (texto libre, independiente
# de la tabla `recursos` — no es un link a otro recurso).

def kit_items_recurso(cur, rid):
    """Sub-recursos de un kit: [{'id','titulo','cantidad','recurso_asignado'}], por id de carga."""
    filas = cur.execute(
        "SELECT id, titulo, cantidad, recurso_asignado FROM kit_items WHERE recurso_id = ? ORDER BY id",
        (rid,)).fetchall()
    return [dict(f) for f in filas]


def agregar_kit_items(cur, recurso_id, items):
    """Inserta sub-recursos en lote: los usa el alta desde el chat (ver
    `agente/tools/fichas.py::_crear_entidad`) y la suma a un kit ya existente (ver
    `agente/tools/entidades.py::_editar_entidad`), que sólo juntan título + cantidad — el
    `recurso_asignado` de cada uno queda vacío, es un campo que sólo se completa a mano
    desde la web."""
    cur.executemany(
        "INSERT INTO kit_items (recurso_id, titulo, cantidad, recurso_asignado) VALUES (?,?,?,'')",
        [(recurso_id, item['titulo'], item.get('cantidad', '')) for item in items if item.get('titulo')])


def obtener_kit_item(cur, recurso_id, item_id):
    """Un sub-recurso puntual, o None si no existe (o no es de ese kit). Para el snapshot
    "antes" de editar/borrar desde el chat (ver `agente/tools/fichas.py`)."""
    fila = cur.execute(
        "SELECT id, titulo, cantidad, recurso_asignado FROM kit_items WHERE id = ? AND recurso_id = ?",
        (item_id, recurso_id)).fetchone()
    return dict(fila) if fila else None


def editar_kit_item(cur, recurso_id, item_id, titulo=None, cantidad=None, recurso_asignado=None):
    """Actualiza SOLO los campos que vienen (no None) de un sub-recurso puntual — edición
    parcial, igual criterio que `agente/tools/entidades.py::_editar_entidad` con el resto de
    una entidad. La ruta web (`kit_item_editar`) manda los tres siempre; el chat puede mandar
    sólo el que cambió. Devuelve True si el ítem existía (y en ese caso, en ese kit) y se
    actualizó, False si no.
    """
    actual = obtener_kit_item(cur, recurso_id, item_id)
    if not actual:
        return False
    cur.execute(
        "UPDATE kit_items SET titulo = ?, cantidad = ?, recurso_asignado = ? WHERE id = ? AND recurso_id = ?",
        (titulo if titulo is not None else actual['titulo'],
         cantidad if cantidad is not None else actual['cantidad'],
         recurso_asignado if recurso_asignado is not None else actual['recurso_asignado'],
         item_id, recurso_id))
    return True


def eliminar_kit_item(cur, recurso_id, item_id):
    """Borra un sub-recurso puntual. Devuelve True si existía (y en ese kit) y se borró."""
    cur.execute("DELETE FROM kit_items WHERE id = ? AND recurso_id = ?", (item_id, recurso_id))
    return cur.rowcount > 0


def buscar_kit_items(cur, q):
    """Sub-recursos de cualquier kit cuyo título matchea `q` (fuzzy, ver texto.puntaje_busqueda),
    puntuados y ordenados igual que el listado principal. Cada resultado trae también
    `kit_id`/`kit_nombre` para poder linkear al recurso que lo contiene."""
    q_norm = texto.norm(q)
    filas = cur.execute(
        "SELECT ki.id, ki.titulo, ki.cantidad, ki.recurso_asignado, "
        "ki.recurso_id AS kit_id, r.nombre AS kit_nombre "
        "FROM kit_items ki JOIN recursos r ON r.id = ki.recurso_id").fetchall()
    puntuadas = []
    for f in filas:
        puntaje = texto.puntaje_busqueda(q_norm, f['titulo'])
        if puntaje is not None:
            puntuadas.append((puntaje, dict(f)))
    puntuadas.sort(key=lambda par: (-par[0], texto.norm(par[1]['titulo'])))
    return [item for _, item in puntuadas]


@bp.route('/recursos/<int:id>/kit/agregar', methods=['POST'])
@accesos.requiere(PERMISO_ESCRITURA)
def kit_item_agregar(id):
    titulo = request.form.get('titulo', '').strip()
    cantidad = request.form.get('cantidad', '').strip()
    recurso_asignado = request.form.get('recurso_asignado', '').strip()
    if titulo:
        con = conectar()
        cur = con.cursor()
        cur.execute("SELECT 1 FROM recursos WHERE id = ?", (id,))
        if cur.fetchone():
            cur.execute(
                "INSERT INTO kit_items (recurso_id, titulo, cantidad, recurso_asignado) VALUES (?,?,?,?)",
                (id, titulo, cantidad, recurso_asignado))
            con.commit()
        con.close()
    return redirect(url_for('gestion.editar', slug='recursos', id=id))


@bp.route('/recursos/<int:id>/kit/<int:item_id>/editar', methods=['POST'])
@accesos.requiere(PERMISO_ESCRITURA)
def kit_item_editar(id, item_id):
    titulo = request.form.get('titulo', '').strip()
    if titulo:
        con = conectar()
        editar_kit_item(con.cursor(), id, item_id, titulo,
                         request.form.get('cantidad', '').strip(),
                         request.form.get('recurso_asignado', '').strip())
        con.commit()
        con.close()
    return redirect(url_for('gestion.editar', slug='recursos', id=id))


@bp.route('/recursos/<int:id>/kit/<int:item_id>/eliminar', methods=['POST'])
@accesos.requiere(PERMISO_ESCRITURA)
def kit_item_eliminar(id, item_id):
    con = conectar()
    eliminar_kit_item(con.cursor(), id, item_id)
    con.commit()
    con.close()
    return redirect(url_for('gestion.editar', slug='recursos', id=id))

