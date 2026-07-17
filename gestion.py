# gestion.py
# Sistema de Gestión de Conocimiento — módulo independiente del sistema de horarios.
#
# Usa su propia DB (gestion.db): a diferencia de escuela.db, NO se regenera desde
# Google Sheets y /api/actualizar no la toca. Es la única DB con datos propios de la app.
#
# Entidades: recursos, conjuntos (agrupaciones de recursos), actividades, proyectos.
# Relaciones M2M: conjunto_recursos, actividad_recursos, actividad_conjuntos, proyecto_recursos.

import os
import sqlite3
from flask import Blueprint, render_template, request, redirect, url_for, abort

from config import ESCUELA_NOMBRE, ESCUELA_LOGO, ESCUELA_VERSION

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gestion.db')

bp = Blueprint('gestion', __name__, url_prefix='/gestion')

ESTADOS_RECURSO = ["Disponible", "En uso", "En reparación", "De baja"]
ESTADOS_PROYECTO = ["Activo", "Pausado", "Terminado"]

# Configuración declarativa de cada entidad: campos del form, columnas del listado
# y relaciones M2M editables desde su formulario. Los campos de relación usan el
# prefijo "rel_" para no colisionar con nombres de columnas.
ENTIDADES = {
    'recursos': {
        'tabla': 'recursos',
        'singular': 'Recurso',
        'plural': 'Recursos',
        'descripcion': 'Objetos físicos o conceptuales: instrumentos, equipos, materiales, estructuras. Se definen una sola vez y se reutilizan en conjuntos, actividades y proyectos.',
        'campos': [
            {'nombre': 'nombre', 'label': 'Nombre', 'tipo': 'text', 'requerido': True},
            {'nombre': 'tipo', 'label': 'Tipo', 'tipo': 'text', 'ayuda': 'Ej: Instrumento, Equipo, Estructura, Material'},
            {'nombre': 'descripcion', 'label': 'Descripción', 'tipo': 'textarea'},
            {'nombre': 'ubicacion', 'label': 'Ubicación', 'tipo': 'text', 'ayuda': 'Ej: Taller de Electricidad, Pañol'},
            {'nombre': 'estado', 'label': 'Estado', 'tipo': 'select', 'opciones': ESTADOS_RECURSO},
            {'nombre': 'drive_url', 'label': 'Carpeta de Drive (link)', 'tipo': 'url', 'ayuda': 'Fotos, planos y documentos viven en Drive; acá solo va el link'},
        ],
        'columnas': [('nombre', 'NOMBRE'), ('tipo', 'TIPO'), ('ubicacion', 'UBICACIÓN'), ('estado', 'ESTADO')],
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
            {'nombre': 'drive_url', 'label': 'Carpeta de Drive (link)', 'tipo': 'url'},
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
            {'nombre': 'drive_url', 'label': 'Carpeta de Drive (link)', 'tipo': 'url', 'ayuda': 'Guías, planillas y material de la actividad'},
        ],
        'columnas': [('nombre', 'NOMBRE'), ('curso', 'CURSO'), ('duracion', 'DURACIÓN')],
        'relaciones': [
            {'campo': 'rel_conjuntos', 'label': 'Conjuntos utilizados', 'tabla': 'actividad_conjuntos',
             'col_propia': 'actividad_id', 'col_ajena': 'conjunto_id', 'slug_ajeno': 'conjuntos'},
            {'campo': 'rel_recursos', 'label': 'Recursos utilizados', 'tabla': 'actividad_recursos',
             'col_propia': 'actividad_id', 'col_ajena': 'recurso_id', 'slug_ajeno': 'recursos'},
        ],
    },
    'proyectos': {
        'tabla': 'proyectos',
        'singular': 'Proyecto',
        'plural': 'Proyectos',
        'descripcion': 'Procesos de construcción o desarrollo que crean o modifican recursos de la escuela.',
        'campos': [
            {'nombre': 'nombre', 'label': 'Nombre', 'tipo': 'text', 'requerido': True},
            {'nombre': 'descripcion', 'label': 'Descripción / resultados', 'tipo': 'textarea'},
            {'nombre': 'fecha', 'label': 'Fecha', 'tipo': 'date'},
            {'nombre': 'participantes', 'label': 'Participantes', 'tipo': 'text', 'ayuda': 'Cursos, docentes o grupos que participaron'},
            {'nombre': 'estado', 'label': 'Estado', 'tipo': 'select', 'opciones': ESTADOS_PROYECTO},
            {'nombre': 'drive_url', 'label': 'Carpeta de Drive (link)', 'tipo': 'url'},
        ],
        'columnas': [('nombre', 'NOMBRE'), ('fecha', 'FECHA'), ('estado', 'ESTADO')],
        'relaciones': [
            {'campo': 'rel_recursos', 'label': 'Recursos generados o involucrados', 'tabla': 'proyecto_recursos',
             'col_propia': 'proyecto_id', 'col_ajena': 'recurso_id', 'slug_ajeno': 'recursos'},
        ],
    },
}

# Tablas M2M a limpiar cuando se elimina una entidad de cada tipo.
LIMPIEZA_M2M = {
    'recursos': [('conjunto_recursos', 'recurso_id'), ('actividad_recursos', 'recurso_id'), ('proyecto_recursos', 'recurso_id')],
    'conjuntos': [('conjunto_recursos', 'conjunto_id'), ('actividad_conjuntos', 'conjunto_id')],
    'actividades': [('actividad_recursos', 'actividad_id'), ('actividad_conjuntos', 'actividad_id')],
    'proyectos': [('proyecto_recursos', 'proyecto_id')],
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS recursos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    tipo TEXT DEFAULT '',
    descripcion TEXT DEFAULT '',
    ubicacion TEXT DEFAULT '',
    estado TEXT DEFAULT 'Disponible',
    drive_url TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS conjuntos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    descripcion TEXT DEFAULT '',
    uso_tipico TEXT DEFAULT '',
    drive_url TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS actividades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    objetivo TEXT DEFAULT '',
    descripcion TEXT DEFAULT '',
    duracion TEXT DEFAULT '',
    curso TEXT DEFAULT '',
    drive_url TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS proyectos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    descripcion TEXT DEFAULT '',
    fecha TEXT DEFAULT '',
    participantes TEXT DEFAULT '',
    estado TEXT DEFAULT 'Activo',
    drive_url TEXT DEFAULT ''
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
CREATE TABLE IF NOT EXISTS proyecto_recursos (
    proyecto_id INTEGER NOT NULL,
    recurso_id INTEGER NOT NULL,
    UNIQUE(proyecto_id, recurso_id)
);
"""


def conectar():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    """Crea las tablas si no existen y carga datos de ejemplo la primera vez."""
    con = conectar()
    cur = con.cursor()
    cur.executescript(SCHEMA)
    if cur.execute("SELECT COUNT(*) FROM recursos").fetchone()[0] == 0:
        _seed(cur)
    con.commit()
    con.close()


def _seed(cur):
    """Datos de ejemplo: el banco de ensayo solar del documento de diseño."""
    recursos = [
        ("Panel solar 100W", "Equipo", "Panel fotovoltaico monocristalino de 100W usado para prácticas de energías renovables.", "Taller de Electricidad", "Disponible", ""),
        ("Estructura regulable", "Estructura", "Estructura metálica con ángulo de inclinación regulable, construida en la escuela.", "Taller de Electricidad", "Disponible", ""),
        ("Inclinómetro digital", "Instrumento", "Medidor digital de ángulo de inclinación.", "Pañol", "Disponible", ""),
        ("Multímetro", "Instrumento", "Multímetro digital para medición de tensión, corriente y resistencia.", "Pañol", "Disponible", ""),
        ("Pinza amperométrica", "Instrumento", "Pinza para medición de corriente sin abrir el circuito.", "Pañol", "Disponible", ""),
    ]
    cur.executemany("INSERT INTO recursos (nombre, tipo, descripcion, ubicacion, estado, drive_url) VALUES (?,?,?,?,?,?)", recursos)
    ids = {r['nombre']: r['id'] for r in cur.execute("SELECT id, nombre FROM recursos").fetchall()}

    cur.execute("INSERT INTO conjuntos (nombre, descripcion, uso_tipico, drive_url) VALUES (?,?,?,?)", (
        "Banco de ensayo solar",
        "Banco para ensayar paneles solares variando el ángulo de inclinación. Compuesto por la estructura regulable, el panel y el inclinómetro.",
        "Prácticas de energías renovables: medición de rendimiento de paneles según inclinación.",
        "",
    ))
    conjunto_id = cur.lastrowid
    for nombre in ("Panel solar 100W", "Estructura regulable", "Inclinómetro digital"):
        cur.execute("INSERT INTO conjunto_recursos (conjunto_id, recurso_id) VALUES (?,?)", (conjunto_id, ids[nombre]))

    cur.execute("INSERT INTO actividades (nombre, objetivo, descripcion, duracion, curso, drive_url) VALUES (?,?,?,?,?,?)", (
        "Medición de panel solar según inclinación",
        "Medir el rendimiento de un panel solar variando el ángulo de inclinación.",
        "Se monta el panel en el banco de ensayo, se varía la inclinación en pasos de 15° y se registran tensión y corriente en cada posición. Con los datos se grafica rendimiento vs. ángulo.",
        "2 módulos",
        "6° año",
        "",
    ))
    actividad_id = cur.lastrowid
    for nombre in ("Multímetro", "Pinza amperométrica"):
        cur.execute("INSERT INTO actividad_recursos (actividad_id, recurso_id) VALUES (?,?)", (actividad_id, ids[nombre]))
    cur.execute("INSERT INTO actividad_conjuntos (actividad_id, conjunto_id) VALUES (?,?)", (actividad_id, conjunto_id))

    cur.execute("INSERT INTO proyectos (nombre, descripcion, fecha, participantes, estado, drive_url) VALUES (?,?,?,?,?,?)", (
        "Construcción del banco de ensayo solar",
        "Diseño y construcción del banco de ensayo con estructura de inclinación regulable. Resultado: banco operativo usado en las prácticas de energías renovables.",
        "2025-11-20",
        "6° año Electricidad",
        "Terminado",
        "",
    ))
    proyecto_id = cur.lastrowid
    for nombre in ("Panel solar 100W", "Estructura regulable", "Inclinómetro digital"):
        cur.execute("INSERT INTO proyecto_recursos (proyecto_id, recurso_id) VALUES (?,?)", (proyecto_id, ids[nombre]))


def _cfg(slug):
    if slug not in ENTIDADES:
        abort(404)
    return ENTIDADES[slug]


def _opciones_relaciones(cfg, cur):
    """Opciones disponibles para cada relación M2M del formulario."""
    opciones = {}
    for rel in cfg['relaciones']:
        tabla = ENTIDADES[rel['slug_ajeno']]['tabla']
        opciones[rel['campo']] = cur.execute(f"SELECT id, nombre FROM {tabla} ORDER BY nombre COLLATE NOCASE").fetchall()
    return opciones


def _seleccion_relaciones(cfg, id, cur):
    """IDs actualmente vinculados, por campo de relación."""
    seleccion = {}
    for rel in cfg['relaciones']:
        filas = cur.execute(f"SELECT {rel['col_ajena']} FROM {rel['tabla']} WHERE {rel['col_propia']} = ?", (id,)).fetchall()
        seleccion[rel['campo']] = {f[0] for f in filas}
    return seleccion


def _guardar(slug, cfg, cur, id=None):
    """Inserta o actualiza la fila y sincroniza sus relaciones M2M. Devuelve el id."""
    nombres = [c['nombre'] for c in cfg['campos']]
    valores = [request.form.get(n, '').strip() for n in nombres]
    if id is None:
        placeholders = ','.join('?' * len(nombres))
        cur.execute(f"INSERT INTO {cfg['tabla']} ({','.join(nombres)}) VALUES ({placeholders})", valores)
        id = cur.lastrowid
    else:
        sets = ','.join(f"{n} = ?" for n in nombres)
        cur.execute(f"UPDATE {cfg['tabla']} SET {sets} WHERE id = ?", valores + [id])
    for rel in cfg['relaciones']:
        cur.execute(f"DELETE FROM {rel['tabla']} WHERE {rel['col_propia']} = ?", (id,))
        for rid in request.form.getlist(rel['campo']):
            try:
                rid = int(rid)
            except ValueError:
                continue
            cur.execute(
                f"INSERT OR IGNORE INTO {rel['tabla']} ({rel['col_propia']}, {rel['col_ajena']}) VALUES (?,?)",
                (id, rid),
            )
    return id


def _secciones_detalle(slug, id, cur):
    """Relaciones a mostrar en la vista de detalle, en ambas direcciones."""
    secciones = []

    def agregar(titulo, slug_destino, sql):
        secciones.append({'titulo': titulo, 'slug': slug_destino, 'items': cur.execute(sql, (id,)).fetchall()})

    if slug == 'recursos':
        agregar('Conjuntos que lo incluyen', 'conjuntos',
                "SELECT c.id, c.nombre FROM conjuntos c JOIN conjunto_recursos r ON r.conjunto_id = c.id WHERE r.recurso_id = ? ORDER BY c.nombre COLLATE NOCASE")
        agregar('Actividades que lo usan', 'actividades',
                "SELECT a.id, a.nombre FROM actividades a JOIN actividad_recursos r ON r.actividad_id = a.id WHERE r.recurso_id = ? ORDER BY a.nombre COLLATE NOCASE")
        agregar('Proyectos relacionados', 'proyectos',
                "SELECT p.id, p.nombre FROM proyectos p JOIN proyecto_recursos r ON r.proyecto_id = p.id WHERE r.recurso_id = ? ORDER BY p.nombre COLLATE NOCASE")
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
    elif slug == 'proyectos':
        agregar('Recursos generados o involucrados', 'recursos',
                "SELECT x.id, x.nombre FROM recursos x JOIN proyecto_recursos r ON r.recurso_id = x.id WHERE r.proyecto_id = ? ORDER BY x.nombre COLLATE NOCASE")
    return secciones


@bp.context_processor
def _contexto_base():
    return {
        'escuela_nombre': ESCUELA_NOMBRE,
        'escuela_logo': ESCUELA_LOGO,
        'escuela_version': ESCUELA_VERSION,
        'nav_entidades': [(slug, e['plural']) for slug, e in ENTIDADES.items()],
    }


@bp.route('/')
def home():
    con = conectar()
    cur = con.cursor()
    tarjetas = []
    for slug, e in ENTIDADES.items():
        total = cur.execute(f"SELECT COUNT(*) FROM {e['tabla']}").fetchone()[0]
        tarjetas.append({'slug': slug, 'plural': e['plural'], 'singular': e['singular'],
                         'descripcion': e['descripcion'], 'total': total})
    con.close()
    return render_template('gestion/home.html', tarjetas=tarjetas, activo='home')


@bp.route('/<slug>')
def lista(slug):
    cfg = _cfg(slug)
    q = request.args.get('q', '').strip()
    con = conectar()
    cur = con.cursor()
    if q:
        like = f"%{q}%"
        filas = cur.execute(
            f"SELECT * FROM {cfg['tabla']} WHERE nombre LIKE ? OR descripcion LIKE ? ORDER BY nombre COLLATE NOCASE",
            (like, like)).fetchall()
    else:
        filas = cur.execute(f"SELECT * FROM {cfg['tabla']} ORDER BY nombre COLLATE NOCASE").fetchall()
    con.close()
    return render_template('gestion/lista.html', cfg=cfg, slug=slug, filas=filas, q=q, activo=slug)


@bp.route('/<slug>/nuevo', methods=['GET', 'POST'])
def nuevo(slug):
    cfg = _cfg(slug)
    con = conectar()
    cur = con.cursor()
    error = None
    if request.method == 'POST':
        if not request.form.get('nombre', '').strip():
            error = 'El nombre es obligatorio.'
        else:
            id = _guardar(slug, cfg, cur)
            con.commit()
            con.close()
            return redirect(url_for('gestion.detalle', slug=slug, id=id))
    opciones = _opciones_relaciones(cfg, cur)
    con.close()
    seleccion = {rel['campo']: {int(v) for v in request.form.getlist(rel['campo'])} for rel in cfg['relaciones']}
    return render_template('gestion/form.html', cfg=cfg, slug=slug, fila=None, valores=request.form,
                           opciones=opciones, seleccion=seleccion, error=error, activo=slug)


@bp.route('/<slug>/<int:id>')
def detalle(slug, id):
    cfg = _cfg(slug)
    con = conectar()
    cur = con.cursor()
    fila = cur.execute(f"SELECT * FROM {cfg['tabla']} WHERE id = ?", (id,)).fetchone()
    if fila is None:
        con.close()
        abort(404)
    secciones = _secciones_detalle(slug, id, cur)
    con.close()
    return render_template('gestion/detalle.html', cfg=cfg, slug=slug, fila=fila, secciones=secciones, activo=slug)


@bp.route('/<slug>/<int:id>/editar', methods=['GET', 'POST'])
def editar(slug, id):
    cfg = _cfg(slug)
    con = conectar()
    cur = con.cursor()
    fila = cur.execute(f"SELECT * FROM {cfg['tabla']} WHERE id = ?", (id,)).fetchone()
    if fila is None:
        con.close()
        abort(404)
    error = None
    if request.method == 'POST':
        if not request.form.get('nombre', '').strip():
            error = 'El nombre es obligatorio.'
        else:
            _guardar(slug, cfg, cur, id)
            con.commit()
            con.close()
            return redirect(url_for('gestion.detalle', slug=slug, id=id))
    opciones = _opciones_relaciones(cfg, cur)
    seleccion = _seleccion_relaciones(cfg, id, cur)
    con.close()
    valores = request.form if request.method == 'POST' else fila
    return render_template('gestion/form.html', cfg=cfg, slug=slug, fila=fila, valores=valores,
                           opciones=opciones, seleccion=seleccion, error=error, activo=slug)


@bp.route('/<slug>/<int:id>/eliminar', methods=['POST'])
def eliminar(slug, id):
    cfg = _cfg(slug)
    con = conectar()
    cur = con.cursor()
    cur.execute(f"DELETE FROM {cfg['tabla']} WHERE id = ?", (id,))
    for tabla, columna in LIMPIEZA_M2M[slug]:
        cur.execute(f"DELETE FROM {tabla} WHERE {columna} = ?", (id,))
    con.commit()
    con.close()
    return redirect(url_for('gestion.lista', slug=slug))
