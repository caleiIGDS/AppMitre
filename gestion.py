# gestion.py
# Gestión de recursos — área de capa 2: declara sus entidades y sus reglas de negocio,
# y el CRUD se lo da el motor genérico (crud.py). Lo que NO es genérico y vive acá entero:
# préstamos/carrito, al final del archivo.
#
# Usa su propia DB (gestion.db): a diferencia de escuela.db, NO se regenera desde
# Google Sheets y /api/actualizar no la toca. Es la única DB con datos propios de la app
# (además de historia.db).
#
# Entidades: recursos, conjuntos (agrupaciones de recursos), actividades.
# Relaciones M2M: conjunto_recursos, actividad_recursos, actividad_conjuntos.

import json
import os
import sys

from config import ahora
from flask import (Blueprint, abort, jsonify, redirect, render_template, request,
                   session, url_for)

import crud
import texto

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gestion.db')

# Respaldos rotativos: la maquinaria vive en respaldos.py (capa 0). Acá sólo se declara
# con qué prefijo se guardan y qué tabla mirar para saber si la DB tiene datos de verdad
# (una DB vacía no se respalda: taparía los respaldos buenos).
PREFIJO_BACKUP = 'gestion'
TABLA_TESTIGO = 'recursos'

bp = Blueprint('gestion', __name__, url_prefix='/gestion')


def conectar():
    """Conexión a gestion.db — `crud.conectar` con esta área ya puesta. El bloque de
    préstamos (que no pasa por el motor genérico) la usa en casi todas sus rutas."""
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
        'descripcion': 'Objetos físicos o conceptuales: instrumentos, equipos, materiales, estructuras. Se definen una sola vez y se reutilizan en conjuntos y actividades.',
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
    },
    'conjuntos': {
        'tabla': 'conjuntos',
        'singular': 'Conjunto',
        'plural': 'Conjuntos',
        'descripcion': 'Agrupaciones de recursos que forman una unidad funcional: un banco de ensayo, una estación de trabajo, un sistema.',
        'campos': [
            {'nombre': 'nombre', 'label': 'Nombre', 'tipo': 'text', 'requerido': True},
            {'nombre': 'descripcion', 'label': 'Descripción', 'tipo': 'textarea'},
            {'nombre': 'uso_tipico', 'label': 'Uso típico', 'tipo': 'textarea', 'ayuda': 'Para qué se usa habitualmente este conjunto'},
        ],
        'columnas': [('nombre', 'NOMBRE'), ('uso_tipico', 'USO TÍPICO')],
        'relaciones': [
            {'campo': 'rel_recursos', 'label': 'Recursos incluidos', 'tabla': 'conjunto_recursos',
             'col_propia': 'conjunto_id', 'col_ajena': 'recurso_id', 'slug_ajeno': 'recursos'},
        ],
    },
    'actividades': {
        'tabla': 'actividades',
        'singular': 'Actividad',
        'plural': 'Actividades',
        'descripcion': 'Prácticas educativas concretas: qué se hace, con qué recursos y conjuntos, y para qué curso.',
        'campos': [
            {'nombre': 'nombre', 'label': 'Nombre', 'tipo': 'text', 'requerido': True},
            {'nombre': 'objetivo', 'label': 'Objetivo', 'tipo': 'text'},
            {'nombre': 'descripcion', 'label': 'Descripción / pasos', 'tipo': 'textarea'},
            {'nombre': 'duracion', 'label': 'Duración', 'tipo': 'text', 'ayuda': 'Ej: 2 módulos, 80 minutos'},
            {'nombre': 'curso', 'label': 'Curso / año', 'tipo': 'text', 'ayuda': 'Ej: 6° año'},
        ],
        'columnas': [('nombre', 'NOMBRE'), ('curso', 'CURSO'), ('duracion', 'DURACIÓN')],
        'relaciones': [
            {'campo': 'rel_conjuntos', 'label': 'Conjuntos utilizados', 'tabla': 'actividad_conjuntos',
             'col_propia': 'actividad_id', 'col_ajena': 'conjunto_id', 'slug_ajeno': 'conjuntos'},
            {'campo': 'rel_recursos', 'label': 'Recursos utilizados', 'tabla': 'actividad_recursos',
             'col_propia': 'actividad_id', 'col_ajena': 'recurso_id', 'slug_ajeno': 'recursos'},
        ],
    },
}

# Tablas M2M a limpiar cuando se elimina una entidad de cada tipo.
LIMPIEZA_M2M = {
    'recursos': [('conjunto_recursos', 'recurso_id'), ('actividad_recursos', 'recurso_id')],
    'conjuntos': [('conjunto_recursos', 'conjunto_id'), ('actividad_conjuntos', 'conjunto_id')],
    'actividades': [('actividad_recursos', 'actividad_id'), ('actividad_conjuntos', 'actividad_id')],
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
    fotos TEXT DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS conjuntos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    descripcion TEXT DEFAULT '',
    uso_tipico TEXT DEFAULT '',
    fotos TEXT DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS actividades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    objetivo TEXT DEFAULT '',
    descripcion TEXT DEFAULT '',
    duracion TEXT DEFAULT '',
    curso TEXT DEFAULT '',
    fotos TEXT DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS conjunto_recursos (
    conjunto_id INTEGER NOT NULL,
    recurso_id INTEGER NOT NULL,
    UNIQUE(conjunto_id, recurso_id)
);
CREATE TABLE IF NOT EXISTS actividad_recursos (
    actividad_id INTEGER NOT NULL,
    recurso_id INTEGER NOT NULL,
    UNIQUE(actividad_id, recurso_id)
);
CREATE TABLE IF NOT EXISTS actividad_conjuntos (
    actividad_id INTEGER NOT NULL,
    conjunto_id INTEGER NOT NULL,
    UNIQUE(actividad_id, conjunto_id)
);
CREATE TABLE IF NOT EXISTS prestamos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    persona TEXT NOT NULL,
    destino TEXT DEFAULT '',
    notas TEXT DEFAULT '',
    fecha_salida TEXT NOT NULL,
    fecha_devolucion TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS prestamo_items (
    prestamo_id INTEGER NOT NULL,
    recurso_id INTEGER NOT NULL,
    cantidad TEXT DEFAULT '1',
    cantidad_devuelta TEXT DEFAULT '0',
    UNIQUE(prestamo_id, recurso_id)
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
    for columna in ('cantidad', 'valor', 'fecha_revision', 'fotos'):
        if columna not in existentes:
            default = '[]' if columna == 'fotos' else ''
            cur.execute(f"ALTER TABLE recursos ADD COLUMN {columna} TEXT DEFAULT '{default}'")
    # Devolución por ítem: cuánto de cada ítem ya volvió (0 = sigue afuera entero).
    cols_items = {c[1] for c in cur.execute("PRAGMA table_info(prestamo_items)").fetchall()}
    if 'cantidad_devuelta' not in cols_items:
        cur.execute("ALTER TABLE prestamo_items ADD COLUMN cantidad_devuelta TEXT DEFAULT '0'")
    # Agregar columna fotos a las demás tablas si no existe
    for tabla in ('conjuntos', 'actividades'):
        cols = {c[1] for c in cur.execute(f"PRAGMA table_info({tabla})").fetchall()}
        if 'fotos' not in cols:
            cur.execute(f"ALTER TABLE {tabla} ADD COLUMN fotos TEXT DEFAULT '[]'")

    # `drive_url` se eliminó: la escuela dejó de usar Drive y la fuente de verdad de gestión
    # pasó a ser esta DB. Es la primera migración DESTRUCTIVA del módulo, así que se corrió
    # habiendo verificado que la columna estaba vacía en las 89 filas de las tres tablas; el
    # respaldo previo de `respaldos.respaldar()` (que corre antes que esto, en init_db) es la red por
    # si alguna instalación tenía links cargados.
    for tabla in ('recursos', 'conjuntos', 'actividades'):
        cols = {c[1] for c in cur.execute(f"PRAGMA table_info({tabla})").fetchall()}
        if 'drive_url' in cols:
            cur.execute(f"ALTER TABLE {tabla} DROP COLUMN drive_url")


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
    ids = {r['nombre']: r['id'] for r in cur.execute("SELECT id, nombre FROM recursos").fetchall()}

    cur.execute("INSERT INTO conjuntos (nombre, descripcion, uso_tipico) VALUES (?,?,?)", (
        "Banco de ensayo solar",
        "Banco para ensayar paneles solares variando el ángulo de inclinación. Compuesto por la estructura regulable, el panel y el inclinómetro.",
        "Prácticas de energías renovables: medición de rendimiento de paneles según inclinación.",
    ))
    conjunto_id = cur.lastrowid
    for nombre in ("Panel solar 100W", "Estructura regulable", "Inclinómetro digital"):
        cur.execute("INSERT INTO conjunto_recursos (conjunto_id, recurso_id) VALUES (?,?)", (conjunto_id, ids[nombre]))

    cur.execute("INSERT INTO actividades (nombre, objetivo, descripcion, duracion, curso) VALUES (?,?,?,?,?)", (
        "Medición de panel solar según inclinación",
        "Medir el rendimiento de un panel solar variando el ángulo de inclinación.",
        "Se monta el panel en el banco de ensayo, se varía la inclinación en pasos de 15° y se registran tensión y corriente en cada posición. Con los datos se grafica rendimiento vs. ángulo.",
        "2 módulos",
        "6° año",
    ))
    actividad_id = cur.lastrowid
    for nombre in ("Multímetro", "Pinza amperométrica"):
        cur.execute("INSERT INTO actividad_recursos (actividad_id, recurso_id) VALUES (?,?)", (actividad_id, ids[nombre]))
    cur.execute("INSERT INTO actividad_conjuntos (actividad_id, conjunto_id) VALUES (?,?)", (actividad_id, conjunto_id))


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
    """Relaciones a mostrar en la vista de detalle, en ambas direcciones."""
    secciones = []

    def agregar(titulo, slug_destino, sql):
        secciones.append({'titulo': titulo, 'slug': slug_destino, 'items': cur.execute(sql, (id,)).fetchall()})

    if slug == 'recursos':
        agregar('Conjuntos que lo incluyen', 'conjuntos',
                "SELECT c.id, c.nombre FROM conjuntos c JOIN conjunto_recursos r ON r.conjunto_id = c.id WHERE r.recurso_id = ? ORDER BY c.nombre COLLATE NOCASE")
        agregar('Actividades que lo usan', 'actividades',
                "SELECT a.id, a.nombre FROM actividades a JOIN actividad_recursos r ON r.actividad_id = a.id WHERE r.recurso_id = ? ORDER BY a.nombre COLLATE NOCASE")
        # Sección especial: quien lo tiene ahora (préstamos activos)
        en_prestamo = cur.execute(
            "SELECT p.persona, i.cantidad, i.cantidad_devuelta "
            "FROM prestamos p JOIN prestamo_items i ON i.prestamo_id = p.id "
            "WHERE i.recurso_id = ? AND p.fecha_devolucion = '' "
            "ORDER BY p.fecha_salida DESC", (id,)).fetchall()
        prestamo_activo = []
        for row in en_prestamo:
            pendiente = max(0, _int(row['cantidad']) - _int(row['cantidad_devuelta']))
            prestamo_activo.append({'persona': row['persona'], 'pendiente': pendiente})
        if prestamo_activo:
            secciones.append({'titulo': 'En préstamo', 'slug': None, 'items': prestamo_activo, 'tipo': 'prestamo_activo'})
        # slug 'prestamos' no está en ENTIDADES, pero url_for('gestion.detalle', slug='prestamos', id=N)
        # genera /gestion/prestamos/N, que el routing despacha a prestamo_detalle (la ruta
        # estática tiene prioridad sobre /<slug>/<id>) — el template genérico no cambia.
        agregar('Historial de préstamos', 'prestamos',
                "SELECT p.id, p.persona || ' — ' || p.fecha_salida || "
                "(CASE WHEN p.fecha_devolucion = '' THEN ' · EN PRÉSTAMO' ELSE '' END) AS nombre "
                "FROM prestamos p JOIN prestamo_items i ON i.prestamo_id = p.id "
                "WHERE i.recurso_id = ? ORDER BY p.fecha_salida DESC, p.id DESC")
    elif slug == 'conjuntos':
        agregar('Recursos incluidos', 'recursos',
                "SELECT x.id, x.nombre FROM recursos x JOIN conjunto_recursos r ON r.recurso_id = x.id WHERE r.conjunto_id = ? ORDER BY x.nombre COLLATE NOCASE")
        agregar('Actividades que lo usan', 'actividades',
                "SELECT a.id, a.nombre FROM actividades a JOIN actividad_conjuntos r ON r.actividad_id = a.id WHERE r.conjunto_id = ? ORDER BY a.nombre COLLATE NOCASE")
    elif slug == 'actividades':
        agregar('Conjuntos utilizados', 'conjuntos',
                "SELECT c.id, c.nombre FROM conjuntos c JOIN actividad_conjuntos r ON r.conjunto_id = c.id WHERE r.actividad_id = ? ORDER BY c.nombre COLLATE NOCASE")
        agregar('Recursos utilizados', 'recursos',
                "SELECT x.id, x.nombre FROM recursos x JOIN actividad_recursos r ON r.recurso_id = x.id WHERE r.actividad_id = ? ORDER BY x.nombre COLLATE NOCASE")
    return secciones


# --- Enganches del motor -----------------------------------------------------
# Préstamos no es una entidad de ENTIDADES (tiene ítems con cantidad y un ciclo
# prestado→devuelto), así que entra al nav y al home por estos hooks.

NAV_EXTRA = [('prestamos', 'Préstamos')]


def tarjetas_extra(cur):
    activos = cur.execute("SELECT COUNT(*) FROM prestamos WHERE fecha_devolucion = ''").fetchone()[0]
    return [{'slug': 'prestamos', 'plural': 'Préstamos', 'singular': 'Préstamo',
             'descripcion': 'Retiros internos de recursos: quién se llevó qué, cuánto y cuándo lo devolvió. Todo queda en el historial. El contador muestra lo que sigue afuera.',
             'total': activos}]


def contexto_extra():
    return {'carrito_count': len(_carrito())}  # ítems distintos, para el badge del nav


def extras_template(vista, slug):
    """En recursos, el listado y la ficha muestran el botón RETIRO / stepper del carrito;
    hay que pasarles las cantidades ya en el carrito para pintar el estado inicial."""
    if slug == 'recursos' and vista in ('lista', 'detalle'):
        return {'carrito': _carrito()}
    return {}


def init_db():
    """Lo hace el motor; queda como nombre estable para app.py e init_gestion.py."""
    crud.init_db(sys.modules[__name__])


crud.registrar_acceso(bp)
crud.registrar_rutas(bp, sys.modules[__name__])


# --- Préstamos / retiros internos --------------------------------------------
# Registro de movimientos: quién se lleva qué recursos, en qué cantidad, y cuándo
# los devuelve. La devolución NO borra nada: fecha_devolucion vacía = sigue afuera.
# Rutas propias (no entran en la config declarativa: tienen ítems con cantidad y
# ciclo prestado→devuelto). Las URLs /gestion/prestamos* son estáticas y tienen
# prioridad sobre /<slug>, así nav/home pueden seguir usando url_for genérico.
# No se descuenta stock de recursos.cantidad: lo prestado se calcula por consulta.
#
# ALTA TIPO CARRITO DE COMPRA: no hay form de alta con filas de ítems. Navegando recursos se
# van agregando al carrito (session['carrito'] = {recurso_id: cantidad}); al finalizar
# se pide quién retira y recién ahí se crea el préstamo. El carrito vive en la sesión
# (por navegador), igual que el login. Ver rutas /carrito* más abajo.


def _ahora():
    return ahora().strftime('%Y-%m-%d %H:%M')


def _int(texto):
    """Entero desde texto de la DB/form; 0 si está vacío o no es número."""
    try:
        return int(str(texto).strip())
    except (TypeError, ValueError):
        return 0


def _recalcular_estado(cur, id):
    """Cierra el préstamo (setea fecha_devolucion) cuando no queda nada pendiente, y lo
    reabre (la limpia) si vuelve a haber algo afuera. fecha_devolucion sigue siendo la
    fuente de verdad de 'devuelto' para la lista y el contador del home.
    También actualiza el estado de recursos: 'Retirado' mientras haya afuera, 'Disponible' cuando vuelve todo."""
    filas = cur.execute(
        "SELECT cantidad, cantidad_devuelta, recurso_id FROM prestamo_items WHERE prestamo_id = ?", (id,)).fetchall()
    pendiente = sum(max(0, _int(f['cantidad']) - _int(f['cantidad_devuelta'])) for f in filas)
    actual = cur.execute("SELECT fecha_devolucion FROM prestamos WHERE id = ?", (id,)).fetchone()
    if actual is None:
        return
    cerrado = bool(actual['fecha_devolucion'])
    if filas and pendiente == 0 and not cerrado:
        cur.execute("UPDATE prestamos SET fecha_devolucion = ? WHERE id = ?", (_ahora(), id))
        # Marcar recursos como Disponible si no hay más préstamos activos
        for f in filas:
            rid = f['recurso_id']
            tiene_prestamos = cur.execute(
                "SELECT 1 FROM prestamo_items i JOIN prestamos p ON p.id = i.prestamo_id "
                "WHERE i.recurso_id = ? AND p.fecha_devolucion = '' LIMIT 1", (rid,)).fetchone()
            if not tiene_prestamos:
                cur.execute("UPDATE recursos SET estado = 'Disponible' WHERE id = ? AND estado = 'Retirado'", (rid,))
    elif pendiente > 0 and cerrado:
        cur.execute("UPDATE prestamos SET fecha_devolucion = '' WHERE id = ?", (id,))
        # Marcar recursos como Retirado nuevamente
        for f in filas:
            rid = f['recurso_id']
            cur.execute("UPDATE recursos SET estado = 'Retirado' WHERE id = ? AND estado != 'De baja'", (rid,))


def _resumen_items(cur, ids, solo_pendiente=False):
    """prestamo_id → '2× Multímetro, 1× Caladora' (para el listado).
    Con solo_pendiente=True muestra sólo lo que falta devolver (cantidad − devuelta),
    útil en la lista de préstamos activos; si no, muestra lo retirado tal cual."""
    if not ids:
        return {}
    marcas = ','.join('?' * len(ids))
    resumen = {}
    filas = cur.execute(
        f"SELECT i.prestamo_id, i.cantidad, i.cantidad_devuelta, COALESCE(r.nombre, '(recurso eliminado)') AS nombre "
        f"FROM prestamo_items i LEFT JOIN recursos r ON r.id = i.recurso_id "
        f"WHERE i.prestamo_id IN ({marcas}) ORDER BY nombre COLLATE NOCASE", list(ids)).fetchall()
    for f in filas:
        cant = _int(f['cantidad'])
        if solo_pendiente:
            cant -= _int(f['cantidad_devuelta'])
            if cant <= 0:
                continue
        resumen.setdefault(f['prestamo_id'], []).append(f"{cant}× {f['nombre']}")
    return {pid: ', '.join(partes) for pid, partes in resumen.items()}


def _carrito():
    """Carrito actual como dict {recurso_id(int): cantidad(int)}. Descarta basura."""
    items = {}
    for k, v in session.get('carrito', {}).items():
        rid, cant = _int(k), _int(v)
        if rid and cant > 0:
            items[rid] = cant
    return items


def _carrito_guardar(items):
    """Persiste el carrito en la sesión (claves string; descarta cantidades <= 0)."""
    session['carrito'] = {str(rid): cant for rid, cant in items.items() if cant > 0}
    session.modified = True


def _carrito_filas(cur, items):
    """Ítems del carrito enriquecidos con nombre/ubicación, ordenados por nombre.
    Tolera recursos borrados (quedan como '(recurso eliminado)')."""
    if not items:
        return []
    marcas = ','.join('?' * len(items))
    por_id = {r['id']: r for r in cur.execute(
        f"SELECT id, nombre, ubicacion FROM recursos WHERE id IN ({marcas})", list(items)).fetchall()}
    filas = []
    for rid, cant in items.items():
        r = por_id.get(rid)
        filas.append({'id': rid, 'cantidad': cant,
                      'nombre': r['nombre'] if r else '(recurso eliminado)',
                      'ubicacion': r['ubicacion'] if r else ''})
    filas.sort(key=lambda f: texto.norm(f['nombre']))
    return filas


@bp.route('/prestamos')
def prestamos_lista():
    q = request.args.get('q', '').strip()
    con = conectar()
    cur = con.cursor()
    sql = "SELECT * FROM prestamos"
    params = []
    if q:
        like = f"%{q}%"
        sql += " WHERE persona LIKE ? OR destino LIKE ? OR notas LIKE ?"
        params = [like, like, like]
    sql += " ORDER BY fecha_salida DESC, id DESC"
    filas = cur.execute(sql, params).fetchall()
    activos = [f for f in filas if not f['fecha_devolucion']]
    devueltos = [f for f in filas if f['fecha_devolucion']]
    # Activos: mostramos lo que falta devolver; historial: lo retirado tal cual.
    resumen = _resumen_items(cur, [f['id'] for f in activos], solo_pendiente=True)
    resumen.update(_resumen_items(cur, [f['id'] for f in devueltos]))
    con.close()
    return render_template('gestion/prestamos_lista.html', activos=activos, devueltos=devueltos,
                           resumen=resumen, q=q, activo='prestamos')


def _volver_recursos():
    """URL a la que volver tras agregar al carrito: la que mandó el form si es de
    /gestion (evita open redirect), o el listado de recursos por defecto."""
    destino = request.form.get('volver', '')
    return destino if destino.startswith('/gestion') else url_for('gestion.lista', slug='recursos')


def _stock(cur, rid):
    """Stock del recurso (recursos.cantidad como entero); None si no existe la fila.
    0 = sin stock definido → sin tope (cantidad vacía o no numérica)."""
    row = cur.execute("SELECT cantidad FROM recursos WHERE id = ?", (rid,)).fetchone() if rid else None
    return None if row is None else _int(row['cantidad'])


@bp.route('/carrito/agregar', methods=['POST'])
def carrito_agregar():
    """Suma un recurso al carrito (topeado al stock). Con JS (fetch) devuelve JSON
    {ok, count, cantidad} para actualizar el badge y el stepper sin recargar; sin JS,
    redirige a donde se estaba. Progressive enhancement — ver static/gestion.js."""
    rid = _int(request.form.get('recurso_id', ''))
    con = conectar()
    cur = con.cursor()
    stock = _stock(cur, rid)
    con.close()
    if stock is not None:
        pedido = _int(request.form.get('cantidad', '')) or 1
        items = _carrito()
        nuevo = items.get(rid, 0) + max(1, pedido)
        if stock > 0:
            nuevo = min(nuevo, stock)
        items[rid] = nuevo
        _carrito_guardar(items)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'ok': stock is not None, 'count': len(_carrito()), 'cantidad': _carrito().get(rid, 0)})
    return redirect(_volver_recursos())


@bp.route('/carrito/set', methods=['POST'])
def carrito_set():
    """Fija la cantidad exacta de un recurso en el carrito — la usan el + y el − del
    stepper (AJAX). `cantidad` <= 0 lo saca; se topea al stock (`recursos.cantidad`) si
    está definido. Devuelve JSON {ok, count, cantidad}."""
    rid = _int(request.form.get('recurso_id', ''))
    con = conectar()
    cur = con.cursor()
    stock = _stock(cur, rid)
    con.close()
    items = _carrito()
    if stock is None:
        items.pop(rid, None)
    else:
        cant = _int(request.form.get('cantidad', ''))
        if stock > 0:
            cant = min(cant, stock)
        if cant <= 0:
            items.pop(rid, None)
        else:
            items[rid] = cant
    _carrito_guardar(items)
    return jsonify({'ok': stock is not None, 'count': len(_carrito()), 'cantidad': _carrito().get(rid, 0)})


@bp.route('/carrito/quitar', methods=['POST'])
def carrito_quitar():
    items = _carrito()
    items.pop(_int(request.form.get('recurso_id', '')), None)
    _carrito_guardar(items)
    return redirect(url_for('gestion.carrito'))


@bp.route('/carrito/vaciar', methods=['POST'])
def carrito_vaciar():
    session.pop('carrito', None)
    return redirect(url_for('gestion.carrito'))


@bp.route('/carrito/actualizar', methods=['POST'])
def carrito_actualizar():
    """Guarda las cantidades editadas en la página del carrito. Con accion=finalizar
    sigue al checkout (pedir quién retira); si no, vuelve al carrito."""
    nuevos = {}
    for rid in _carrito():
        cant = _int(request.form.get(f'cantidad_{rid}', ''))
        if cant > 0:
            nuevos[rid] = cant  # cant <= 0 => se descarta (equivale a quitarlo)
    _carrito_guardar(nuevos)
    if request.form.get('accion') == 'finalizar' and nuevos:
        return redirect(url_for('gestion.carrito_finalizar'))
    return redirect(url_for('gestion.carrito'))


@bp.route('/carrito')
def carrito():
    """Carrito de retiro: revisar ítems, editar cantidades, quitar. De acá se finaliza."""
    con = conectar()
    cur = con.cursor()
    filas = _carrito_filas(cur, _carrito())
    con.close()
    return render_template('gestion/carrito.html', items=filas, activo='prestamos')


@bp.route('/carrito/finalizar', methods=['GET', 'POST'])
def carrito_finalizar():
    """Checkout: recién acá se pide quién retira / destino / notas y se crea el
    préstamo con lo que haya en el carrito. Al confirmar, vacía el carrito."""
    items = _carrito()
    if not items:
        return redirect(url_for('gestion.carrito'))
    con = conectar()
    cur = con.cursor()
    error = None
    if request.method == 'POST':
        persona = request.form.get('persona', '').strip()
        if not persona:
            error = 'Falta quién retira.'
        else:
            cur.execute("INSERT INTO prestamos (persona, destino, notas, fecha_salida, fecha_devolucion) VALUES (?,?,?,?,'')",
                        (persona, request.form.get('destino', '').strip(),
                         request.form.get('notas', '').strip(), _ahora()))
            pid = cur.lastrowid
            for rid, cant in items.items():
                cur.execute("INSERT INTO prestamo_items (prestamo_id, recurso_id, cantidad, cantidad_devuelta) VALUES (?,?,?, '0')",
                            (pid, rid, str(cant)))
                cur.execute("UPDATE recursos SET estado = 'Retirado' WHERE id = ?", (rid,))
            con.commit()
            con.close()
            session.pop('carrito', None)
            return redirect(url_for('gestion.prestamo_detalle', id=pid))
    filas = _carrito_filas(cur, items)
    con.close()
    return render_template('gestion/carrito_finalizar.html', items=filas,
                           valores=request.form, error=error, activo='prestamos')


@bp.route('/prestamos/<int:id>')
def prestamo_detalle(id):
    con = conectar()
    cur = con.cursor()
    fila = cur.execute("SELECT * FROM prestamos WHERE id = ?", (id,)).fetchone()
    if fila is None:
        con.close()
        abort(404)
    filas_items = cur.execute(
        "SELECT i.cantidad, i.cantidad_devuelta, i.recurso_id, r.nombre, r.ubicacion FROM prestamo_items i "
        "LEFT JOIN recursos r ON r.id = i.recurso_id WHERE i.prestamo_id = ? "
        "ORDER BY r.nombre COLLATE NOCASE", (id,)).fetchall()
    con.close()
    items = []
    for it in filas_items:
        cantidad, devuelta = _int(it['cantidad']), _int(it['cantidad_devuelta'])
        items.append({'recurso_id': it['recurso_id'], 'nombre': it['nombre'], 'ubicacion': it['ubicacion'],
                      'cantidad': cantidad, 'devuelta': devuelta, 'pendiente': max(0, cantidad - devuelta)})
    pendiente_total = sum(it['pendiente'] for it in items)
    return render_template('gestion/prestamos_detalle.html', fila=fila, items=items,
                           pendiente_total=pendiente_total, activo='prestamos')


@bp.route('/prestamos/<int:id>/devolver', methods=['POST'])
def prestamo_devolver(id):
    """Devolver TODO de una: marca cada ítem entero y cierra el préstamo. Atajo del
    botón 'devolvió' de la lista y de 'devolver todo' del detalle. Las devoluciones
    parciales por ítem van por /devolver_item."""
    con = conectar()
    cur = con.cursor()
    cur.execute("UPDATE prestamo_items SET cantidad_devuelta = cantidad WHERE prestamo_id = ?", (id,))
    cur.execute("UPDATE prestamos SET fecha_devolucion = ? WHERE id = ? AND fecha_devolucion = ''",
                (_ahora(), id))
    _recalcular_estado(cur, id)
    con.commit()
    con.close()
    if request.form.get('volver') == 'detalle':
        return redirect(url_for('gestion.prestamo_detalle', id=id))
    return redirect(url_for('gestion.prestamos_lista'))


@bp.route('/prestamos/<int:id>/devolver_item', methods=['POST'])
def prestamo_devolver_item(id):
    """Devuelve parte (o el resto) de un ítem del préstamo. `cantidad` vacía = todo lo
    pendiente de ese ítem. Al cubrirse todo lo pendiente del préstamo, se cierra solo."""
    con = conectar()
    cur = con.cursor()
    recurso_id = request.form.get('recurso_id', '')
    item = cur.execute(
        "SELECT cantidad, cantidad_devuelta FROM prestamo_items WHERE prestamo_id = ? AND recurso_id = ?",
        (id, recurso_id)).fetchone()
    if item is not None:
        pendiente = max(0, _int(item['cantidad']) - _int(item['cantidad_devuelta']))
        pedido = request.form.get('cantidad', '').strip()
        cuanto = _int(pedido) if pedido else pendiente
        cuanto = max(1, min(cuanto, pendiente)) if pendiente else 0
        if cuanto:
            nueva = _int(item['cantidad_devuelta']) + cuanto
            cur.execute("UPDATE prestamo_items SET cantidad_devuelta = ? WHERE prestamo_id = ? AND recurso_id = ?",
                        (str(nueva), id, recurso_id))
            _recalcular_estado(cur, id)
            con.commit()
    con.close()
    return redirect(url_for('gestion.prestamo_detalle', id=id))


@bp.route('/prestamos/<int:id>/reabrir', methods=['POST'])
def prestamo_reabrir(id):
    """Deshace una devolución marcada por error (todo el préstamo vuelve a figurar afuera)."""
    con = conectar()
    cur = con.cursor()
    cur.execute("UPDATE prestamo_items SET cantidad_devuelta = '0' WHERE prestamo_id = ?", (id,))
    cur.execute("UPDATE prestamos SET fecha_devolucion = '' WHERE id = ?", (id,))
    _recalcular_estado(cur, id)
    con.commit()
    con.close()
    return redirect(url_for('gestion.prestamo_detalle', id=id))


@bp.route('/prestamos/<int:id>/reabrir_item', methods=['POST'])
def prestamo_reabrir_item(id):
    """Deshace la devolución de un ítem puntual: vuelve a figurar afuera entero. Si con
    eso el préstamo vuelve a tener algo pendiente, se reabre (se limpia fecha_devolucion)."""
    con = conectar()
    cur = con.cursor()
    recurso_id = request.form.get('recurso_id', '')
    cur.execute("UPDATE prestamo_items SET cantidad_devuelta = '0' WHERE prestamo_id = ? AND recurso_id = ?",
                (id, recurso_id))
    _recalcular_estado(cur, id)
    con.commit()
    con.close()
    return redirect(url_for('gestion.prestamo_detalle', id=id))


@bp.route('/prestamos/<int:id>/eliminar', methods=['POST'])
def prestamo_eliminar(id):
    """Solo para registros mal cargados — la devolución normal usa /devolver."""
    con = conectar()
    cur = con.cursor()
    # Obtener recursos antes de eliminar para actualizar su estado
    filas = cur.execute("SELECT recurso_id FROM prestamo_items WHERE prestamo_id = ?", (id,)).fetchall()
    cur.execute("DELETE FROM prestamos WHERE id = ?", (id,))
    cur.execute("DELETE FROM prestamo_items WHERE prestamo_id = ?", (id,))
    # Actualizar estado de recursos: si no hay más préstamos activos, marcar como Disponible
    for f in filas:
        rid = f['recurso_id']
        tiene_prestamos = cur.execute(
            "SELECT 1 FROM prestamo_items i JOIN prestamos p ON p.id = i.prestamo_id "
            "WHERE i.recurso_id = ? AND p.fecha_devolucion = '' LIMIT 1", (rid,)).fetchone()
        if not tiene_prestamos:
            cur.execute("UPDATE recursos SET estado = 'Disponible' WHERE id = ? AND estado = 'Retirado'", (rid,))
    con.commit()
    con.close()
    return redirect(url_for('gestion.prestamos_lista'))
