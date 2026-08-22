# gestion.py
# Gestión de recursos — área de capa 2: declara sus entidades y sus reglas de negocio,
# y el CRUD se lo da el motor genérico (crud.py). Lo que NO es genérico y vive acá entero:
# el desglose de recursos por lugar, al final del archivo.
#
# Usa su propia DB (gestion.db): a diferencia de escuela.db, NO se regenera desde
# Google Sheets y /api/actualizar no la toca. Es la única DB con datos propios de la app
# (además de historia.db).
#
# Entidades: recursos.
#
# Hasta el 2026-08-21 el módulo también tenía conjuntos, actividades y préstamos/carrito
# (retiro interno de recursos). Se sacaron por decisión de producto, no por deuda técnica:
# ver dev-log/DECISIONS.md 2026-08-21 si se retoman.

import os
import sys

from config import ahora
from flask import Blueprint, redirect, render_template, request, url_for

import accesos
import crud
import texto

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gestion.db')

# Permisos que declara el área al catálogo de `accesos`. El VERBO es lo que hace que un
# perfil los agarre solo: 'leer' entra en interno-lectura, 'escribir' en interno-gestion.
PERMISOS = [
    ('gestion.leer', 'Ver el inventario', 'leer'),
    ('gestion.editar', 'Cargar, editar y eliminar recursos', 'escribir'),
    # Verbo 'admin' = no entra en ningún preset de interno (ver accesos.PERFILES, que los
    # arma por verbo): sólo lo tiene el admin, por el comodín '*'. El alias de un recurso
    # es un campo que ni el interno de lectura ni el de escritura deben poder ver/editar
    # desde ningún lado — lo completa el asistente solo (ver agent_docs/gestion-conocimiento.md).
    ('gestion.alias', 'Ver los alias ocultos de los recursos (solo consulta)', 'admin'),
]
GRUPO_PERMISOS = 'Gestión de recursos'
PERMISO_LECTURA = 'gestion.leer'
PERMISO_ESCRITURA = 'gestion.editar'
PERMISO_ALIAS = 'gestion.alias'

# Respaldos rotativos: la maquinaria vive en respaldos.py (capa 0). Acá sólo se declara
# con qué prefijo se guardan y qué tabla mirar para saber si la DB tiene datos de verdad
# (una DB vacía no se respalda: taparía los respaldos buenos).
PREFIJO_BACKUP = 'gestion'
TABLA_TESTIGO = 'recursos'

bp = Blueprint('gestion', __name__, url_prefix='/gestion')


def conectar():
    """Conexión a gestion.db — `crud.conectar` con esta área ya puesta. Las rutas propias
    (alias, desglose por ubicación, que no pasan por el motor genérico) la usan directo."""
    return crud.conectar(sys.modules[__name__])

ESTADOS_RECURSO = ["Disponible", "Retirado", "En uso", "En reparación", "De baja", "Sin revisar"]
# "" primero: permite dejar el valor sin definir (recursos previos al inventario).
VALORES_RECURSO = ["", "Básico", "Secundario", "Alto valor"]

# Configuración declarativa de cada entidad: campos del form, columnas del listado
# y relaciones M2M editables desde su formulario. Los campos de relación usan el
# prefijo "rel_" para no colisionar con nombres de columnas.
ENTIDADES = {
    'recursos': {
        'tabla': 'recursos',
        'singular': 'Recurso',
        'plural': 'Recursos',
        'descripcion': 'Objetos físicos o conceptuales: instrumentos, equipos, materiales, estructuras.',
        'campos': [
            {'nombre': 'nombre', 'label': 'Nombre', 'tipo': 'text', 'requerido': True},
            {'nombre': 'tipo', 'label': 'Tipo', 'tipo': 'text', 'ayuda': 'Ej: Instrumento, Equipo, Estructura, Material'},
            {'nombre': 'cantidad', 'label': 'Cantidad', 'tipo': 'number'},
            {'nombre': 'descripcion', 'label': 'Descripción', 'tipo': 'textarea'},
            {'nombre': 'ubicacion', 'label': 'Ubicación', 'tipo': 'text', 'ayuda': 'Ej: Taller de Electricidad, Pañol, A2'},
            {'nombre': 'estado', 'label': 'Estado', 'tipo': 'select', 'opciones': ESTADOS_RECURSO},
            {'nombre': 'valor', 'label': 'Valor', 'tipo': 'select', 'opciones': VALORES_RECURSO, 'ayuda': 'Importancia del recurso dentro del inventario'},
            {'nombre': 'fecha_revision', 'label': 'Última revisión', 'tipo': 'text', 'ayuda': 'Fecha del último control de inventario (día/mes/año). En un alta arranca en hoy'},
        ],
        'columnas': [('nombre', 'NOMBRE'), ('cantidad', 'CANT.'), ('ubicacion', 'UBICACIÓN'), ('estado', 'ESTADO'), ('valor', 'VALOR')],
        'relaciones': [],
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

# Tablas a limpiar cuando se elimina un recurso. `recurso_ubicaciones` no es una relación
# M2M de verdad (es el desglose por lugar, ver más abajo) pero el mecanismo de limpieza es
# idéntico: borrar filas por `recurso_id`.
LIMPIEZA_M2M = {
    'recursos': [('recurso_ubicaciones', 'recurso_id')],
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS recursos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    tipo TEXT DEFAULT '',
    descripcion TEXT DEFAULT '',
    ubicacion TEXT DEFAULT '',
    estado TEXT DEFAULT 'Disponible',
    cantidad TEXT DEFAULT '',
    valor TEXT DEFAULT '',
    fecha_revision TEXT DEFAULT '',
    fotos TEXT DEFAULT '[]',
    alias TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS recurso_ubicaciones (
    recurso_id INTEGER NOT NULL,
    ubicacion TEXT NOT NULL,
    cantidad TEXT DEFAULT '0',
    UNIQUE(recurso_id, ubicacion)
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


def seed(cur):
    """Datos de ejemplo: el banco de ensayo solar del documento de diseño."""
    recursos = [
        ("Panel solar 100W", "Equipo", "Panel fotovoltaico monocristalino de 100W usado para prácticas de energías renovables.", "Taller de Electricidad", "Disponible"),
        ("Estructura regulable", "Estructura", "Estructura metálica con ángulo de inclinación regulable, construida en la escuela.", "Taller de Electricidad", "Disponible"),
        ("Inclinómetro digital", "Instrumento", "Medidor digital de ángulo de inclinación.", "Pañol", "Disponible"),
        ("Multímetro", "Instrumento", "Multímetro digital para medición de tensión, corriente y resistencia.", "Pañol", "Disponible"),
        ("Pinza amperométrica", "Instrumento", "Pinza para medición de corriente sin abrir el circuito.", "Pañol", "Disponible"),
    ]
    cur.executemany("INSERT INTO recursos (nombre, tipo, descripcion, ubicacion, estado) VALUES (?,?,?,?,?)", recursos)


# Qué decir cuando un UNIQUE de la DB rechaza el guardado (si no, sale un 500 pelado).
# Vacío: ninguna entidad de este módulo tiene un UNIQUE de negocio (a diferencia de
# historia.personas, que sí lo necesita — ver historia.ERROR_DUPLICADO).
ERROR_DUPLICADO = {}


# Formato de `recursos.fecha_revision`. La columna es TEXT y el inventario importado del
# sheet trae fechas cortas sin año ("24/4"): conviven, pero lo que se carga de acá en más
# lleva el año. El agente importa esta constante para no tener dos formatos distintos.
FORMATO_FECHA_REVISION = '%d/%m/%Y'


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
        # Desglose por lugar: sólo si el recurso tiene más de una unidad (si no, no hay
        # nada que repartir) o si ya se lo desglosó alguna vez. La mayoría de los recursos
        # (una sola unidad) no la ven — ver agent_docs/gestion-conocimiento.md.
        fila_cant = cur.execute("SELECT cantidad FROM recursos WHERE id = ?", (id,)).fetchone()
        ubicaciones = ubicaciones_recurso(cur, id)
        if (fila_cant and _int(fila_cant['cantidad']) > 1) or ubicaciones:
            secciones.append({'titulo': 'Por ubicación', 'slug': None, 'items': ubicaciones, 'tipo': 'ubicaciones'})
    return secciones


def init_db():
    """Lo hace el motor; queda como nombre estable para app.py e init_gestion.py."""
    crud.init_db(sys.modules[__name__])


accesos.registrar_acceso(bp, PERMISO_LECTURA)
crud.registrar_rutas(bp, sys.modules[__name__])


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


# --- Desglose de recursos por lugar ------------------------------------------
# `recurso_ubicaciones` es OPCIONAL a propósito: la mayoría de los recursos tiene un solo
# lugar (el campo `ubicacion` de siempre) y nunca toca esta tabla. Sólo entra en juego
# cuando alguien reparte las unidades de un mismo recurso en más de un sitio. El desglose
# NUNCA tiene que estar completo ni sumar el total de `recursos.cantidad`: no hay concepto
# de "sin ubicar" que validar — cada fila es independiente. El pedido explícito fue que
# mover algo entre lugares no se bloquee por no tener el desglose previo cargado, mismo
# criterio de "avisar, no bloquear" que se usaba con el stock de los préstamos (ver
# dev-log/DECISIONS.md 2026-08-11 y 2026-08-21).

def _resolver_ubicacion_existente(cur, rid, nombre):
    """Si ya hay una fila de ESTE recurso cuyo lugar coincide sin importar mayúsculas ni
    acentos, devuelve el string tal como está guardado (para no fragmentar "Taller" y
    "taller " en dos filas distintas). Si no hay ninguna, devuelve `nombre` recortado."""
    nombre = (nombre or '').strip()
    if not nombre:
        return nombre
    objetivo = texto.norm(nombre)
    for fila in cur.execute("SELECT ubicacion FROM recurso_ubicaciones WHERE recurso_id = ?", (rid,)).fetchall():
        if texto.norm(fila['ubicacion']) == objetivo:
            return fila['ubicacion']
    return nombre


def ubicaciones_recurso(cur, rid):
    """Desglose por lugar de un recurso: [{'ubicacion':, 'cantidad':}], ordenado por lugar.
    Lista vacía = no se desglosó (el recurso sigue con el campo `ubicacion` simple)."""
    filas = cur.execute(
        "SELECT ubicacion, cantidad FROM recurso_ubicaciones WHERE recurso_id = ? "
        "ORDER BY ubicacion COLLATE NOCASE", (rid,)).fetchall()
    return [{'ubicacion': f['ubicacion'], 'cantidad': _int(f['cantidad'])} for f in filas
           if _int(f['cantidad']) > 0]


def _cantidad_en(cur, rid, ubicacion):
    fila = cur.execute("SELECT cantidad FROM recurso_ubicaciones WHERE recurso_id = ? AND ubicacion = ?",
                       (rid, ubicacion)).fetchone()
    return _int(fila['cantidad']) if fila else 0


def _set_ubicacion(cur, rid, ubicacion, cantidad):
    """Fija la cantidad de un recurso en un lugar. `cantidad` <= 0 saca la fila en vez de
    dejarla en 0: una fila en 0 no le dice nada a nadie y ensucia el desglose."""
    if cantidad <= 0:
        cur.execute("DELETE FROM recurso_ubicaciones WHERE recurso_id = ? AND ubicacion = ?", (rid, ubicacion))
    else:
        cur.execute(
            "INSERT INTO recurso_ubicaciones (recurso_id, ubicacion, cantidad) VALUES (?,?,?) "
            "ON CONFLICT(recurso_id, ubicacion) DO UPDATE SET cantidad = excluded.cantidad",
            (rid, ubicacion, str(cantidad)))


def mover_ubicacion(cur, rid, cantidad, origen, destino):
    """Mueve `cantidad` unidades de `origen` a `destino` en el desglose por lugar.

    NO exige que el desglose esté completo: si `origen` no tiene registradas tantas unidades
    como se pide mover (o directamente no tiene fila todavía), IGUAL se mueven las `cantidad`
    unidades a destino — se vacía lo que hubiera en origen y se avisa del faltante, en vez de
    rechazar el movimiento. `origen` vacío/None = no se resta de ningún lado (unidades que
    nunca tuvieron un lugar registrado), sólo se suman a destino.
    """
    destino = _resolver_ubicacion_existente(cur, rid, destino)
    if not destino:
        return {'ok': False, 'error': 'Falta el lugar de destino.', 'avisos': []}

    avisos = []
    origen = _resolver_ubicacion_existente(cur, rid, origen) if origen else ''
    if origen:
        registrado = _cantidad_en(cur, rid, origen)
        if registrado < cantidad:
            avisos.append(f'en "{origen}" había {registrado} registradas, no {cantidad}: '
                          f'se vació igual esa cantidad y se movieron las {cantidad} a "{destino}"')
        _set_ubicacion(cur, rid, origen, registrado - cantidad)

    _set_ubicacion(cur, rid, destino, _cantidad_en(cur, rid, destino) + cantidad)
    return {'ok': True, 'avisos': avisos}


# Rutas propias (no son una entidad de ENTIDADES): agregar/corregir o sacar un lugar del
# desglose desde la ficha del recurso. Sin tope contra `recursos.cantidad` a propósito,
# mismo criterio de no bloquear.
@bp.route('/recursos/<int:id>/ubicaciones', methods=['POST'])
@accesos.requiere(PERMISO_ESCRITURA)
def ubicacion_set(id):
    ubicacion = request.form.get('ubicacion', '').strip()
    if ubicacion:
        con = conectar()
        cur = con.cursor()
        cur.execute("SELECT 1 FROM recursos WHERE id = ?", (id,))
        if cur.fetchone():
            ubicacion = _resolver_ubicacion_existente(cur, id, ubicacion)
            _set_ubicacion(cur, id, ubicacion, _int(request.form.get('cantidad', '')))
            con.commit()
        con.close()
    return redirect(url_for('gestion.detalle', slug='recursos', id=id))


@bp.route('/recursos/<int:id>/ubicaciones/eliminar', methods=['POST'])
@accesos.requiere(PERMISO_ESCRITURA)
def ubicacion_eliminar(id):
    con = conectar()
    cur = con.cursor()
    cur.execute("DELETE FROM recurso_ubicaciones WHERE recurso_id = ? AND ubicacion = ?",
                (id, request.form.get('ubicacion', '')))
    con.commit()
    con.close()
    return redirect(url_for('gestion.detalle', slug='recursos', id=id))

