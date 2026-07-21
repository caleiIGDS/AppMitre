# gestion.py
# Sistema de Gestión de Conocimiento — módulo independiente del sistema de horarios.
#
# Usa su propia DB (gestion.db): a diferencia de escuela.db, NO se regenera desde
# Google Sheets y /api/actualizar no la toca. Es la única DB con datos propios de la app.
#
# Entidades: recursos, conjuntos (agrupaciones de recursos), actividades, proyectos.
# Relaciones M2M: conjunto_recursos, actividad_recursos, actividad_conjuntos, proyecto_recursos.

import difflib
import os
import re
import sqlite3
import unicodedata
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, abort, session

from config import ESCUELA_NOMBRE, ESCUELA_LOGO, ESCUELA_VERSION

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gestion.db')

bp = Blueprint('gestion', __name__, url_prefix='/gestion')

# --- Acceso con contraseña compartida (provisorio) ---------------------------
# Traba mínima mientras el módulo está en desarrollo: una sola clave para todo
# /gestion, guardada en la sesión. En el hosting se cambia con la env var
# GESTION_CLAVE; el default de abajo es público (el repo lo es), así que solo
# frena curiosos. Sin usuarios, sin CSRF, sin límite de intentos.
CLAVE = os.environ.get('GESTION_CLAVE', 'mitre2026')


@bp.before_request
def _requiere_clave():
    if request.endpoint == 'gestion.login' or session.get('gestion_ok'):
        return
    return redirect(url_for('gestion.login', next=request.path))


@bp.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form.get('clave', '') == CLAVE:
            session['gestion_ok'] = True
            destino = request.form.get('next', '')
            # Solo volver a rutas del propio módulo (evita open redirect).
            if not destino.startswith('/gestion'):
                destino = url_for('gestion.home')
            return redirect(destino)
        error = 'Contraseña incorrecta.'
    return render_template('gestion/login.html', error=error,
                           next=request.values.get('next', ''), activo=None)


@bp.route('/salir')
def salir():
    session.pop('gestion_ok', None)
    return redirect(url_for('gestion.login'))


ESTADOS_RECURSO = ["Disponible", "En uso", "En reparación", "De baja", "Sin revisar"]
ESTADOS_PROYECTO = ["Activo", "Pausado", "Terminado"]
# "" primero: permite dejar la utilidad sin definir (recursos previos al inventario).
UTILIDADES_RECURSO = ["", "Básico", "Secundario", "Alto valor"]

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
            {'nombre': 'cantidad', 'label': 'Cantidad', 'tipo': 'number'},
            {'nombre': 'descripcion', 'label': 'Descripción', 'tipo': 'textarea'},
            {'nombre': 'ubicacion', 'label': 'Ubicación', 'tipo': 'text', 'ayuda': 'Ej: Taller de Electricidad, Pañol, A2'},
            {'nombre': 'estado', 'label': 'Estado', 'tipo': 'select', 'opciones': ESTADOS_RECURSO},
            {'nombre': 'utilidad', 'label': 'Utilidad', 'tipo': 'select', 'opciones': UTILIDADES_RECURSO, 'ayuda': 'Importancia del recurso dentro del inventario'},
            {'nombre': 'fecha_revision', 'label': 'Última revisión', 'tipo': 'text', 'ayuda': 'Fecha del último control de inventario (ej: 24/4)'},
            {'nombre': 'drive_url', 'label': 'Carpeta de Drive (link)', 'tipo': 'url', 'ayuda': 'Fotos, planos y documentos viven en Drive; acá solo va el link'},
        ],
        'columnas': [('nombre', 'NOMBRE'), ('cantidad', 'CANT.'), ('ubicacion', 'UBICACIÓN'), ('estado', 'ESTADO'), ('utilidad', 'UTILIDAD')],
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
    drive_url TEXT DEFAULT '',
    cantidad TEXT DEFAULT '',
    utilidad TEXT DEFAULT '',
    fecha_revision TEXT DEFAULT ''
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
    UNIQUE(prestamo_id, recurso_id)
);
"""


def _norm(texto):
    """Minúsculas, sin acentos, espacios colapsados — para comparar nombres."""
    texto = unicodedata.normalize('NFD', texto)
    texto = ''.join(c for c in texto if unicodedata.category(c) != 'Mn')
    return ' '.join(texto.lower().split())


# Búsqueda "que perdona": en vez del LIKE literal, normaliza acentos/mayúsculas y
# tolera typos por similitud (difflib, sin dependencias). El substring normalizado
# siempre gana; la similitud difusa solo entra para queries de 3+ caracteres (con
# menos daría demasiado ruido). Umbral elegido a ojo — subir = más estricto.
UMBRAL_SIMILITUD = 0.6


def _puntaje_busqueda(q_norm, *textos):
    """Qué tan bien `q_norm` (ya normalizado) matchea los textos dados.
    Devuelve un puntaje mayor = mejor, o None si no llega al umbral. Los que
    contienen la query como substring puntúan por encima de los difusos."""
    difuso = len(q_norm) >= 3  # perdonar typos solo tiene sentido con 3+ caracteres
    substring = False
    mejor = 0.0
    for texto in textos:
        if not texto:
            continue
        t_norm = _norm(texto)
        if q_norm in t_norm:
            substring = True
        if difuso:
            mejor = max(mejor, difflib.SequenceMatcher(None, q_norm, t_norm).ratio())
            for palabra in t_norm.split():
                mejor = max(mejor, difflib.SequenceMatcher(None, q_norm, palabra).ratio())
    if substring:
        return 1.0 + mejor  # substring exacto siempre primero; desempata por similitud
    if difuso and mejor >= UMBRAL_SIMILITUD:
        return mejor
    return None


def conectar():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    """Crea las tablas si no existen, migra columnas nuevas y carga datos de ejemplo la primera vez."""
    con = conectar()
    cur = con.cursor()
    cur.executescript(SCHEMA)
    _migrar(cur)
    if cur.execute("SELECT COUNT(*) FROM recursos").fetchone()[0] == 0:
        _seed(cur)
    con.commit()
    con.close()


def _migrar(cur):
    """Suma columnas nuevas a una gestion.db creada con un schema anterior (solo ALTER aditivo)."""
    existentes = {c[1] for c in cur.execute("PRAGMA table_info(recursos)").fetchall()}
    for columna in ('cantidad', 'utilidad', 'fecha_revision'):
        if columna not in existentes:
            cur.execute(f"ALTER TABLE recursos ADD COLUMN {columna} TEXT DEFAULT ''")


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
        'nav_entidades': [(slug, e['plural']) for slug, e in ENTIDADES.items()] + [('prestamos', 'Préstamos')],
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
    activos = cur.execute("SELECT COUNT(*) FROM prestamos WHERE fecha_devolucion = ''").fetchone()[0]
    tarjetas.append({'slug': 'prestamos', 'plural': 'Préstamos', 'singular': 'Préstamo',
                     'descripcion': 'Retiros internos de recursos: quién se llevó qué, cuánto y cuándo lo devolvió. Todo queda en el historial. El contador muestra lo que sigue afuera.',
                     'total': activos})
    con.close()
    return render_template('gestion/home.html', tarjetas=tarjetas, activo='home')


@bp.route('/<slug>')
def lista(slug):
    cfg = _cfg(slug)
    q = request.args.get('q', '').strip()
    con = conectar()
    cur = con.cursor()
    filas = cur.execute(f"SELECT * FROM {cfg['tabla']} ORDER BY nombre COLLATE NOCASE").fetchall()
    con.close()
    if q:
        # Búsqueda tolerante (ver _puntaje_busqueda): acentos/mayúsculas no importan
        # y se perdonan typos. Se filtra y ordena en Python — con esta cantidad de
        # filas el costo es despreciable frente a la comodidad de que "perdone".
        q_norm = _norm(q)
        puntuadas = []
        for fila in filas:
            puntaje = _puntaje_busqueda(q_norm, fila['nombre'], fila['descripcion'])
            if puntaje is not None:
                puntuadas.append((puntaje, fila))
        puntuadas.sort(key=lambda par: (-par[0], _norm(par[1]['nombre'])))
        filas = [fila for _, fila in puntuadas]
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


# --- Préstamos / retiros internos --------------------------------------------
# Registro de movimientos: quién se lleva qué recursos, en qué cantidad, y cuándo
# los devuelve. La devolución NO borra nada: fecha_devolucion vacía = sigue afuera.
# Rutas propias (no entran en la config declarativa: tienen ítems con cantidad y
# ciclo prestado→devuelto). Las URLs /gestion/prestamos* son estáticas y tienen
# prioridad sobre /<slug>, así nav/home pueden seguir usando url_for genérico.
# No se descuenta stock de recursos.cantidad: lo prestado se calcula por consulta.

PRESTAMO_FILAS_FORM = 8  # filas de ítems disponibles en el form de retiro


def _ahora():
    return datetime.now().strftime('%Y-%m-%d %H:%M')


def _resumen_items(cur, ids):
    """prestamo_id → '2× Multímetro, 1× Caladora' (para el listado)."""
    if not ids:
        return {}
    marcas = ','.join('?' * len(ids))
    resumen = {}
    filas = cur.execute(
        f"SELECT i.prestamo_id, i.cantidad, COALESCE(r.nombre, '(recurso eliminado)') AS nombre "
        f"FROM prestamo_items i LEFT JOIN recursos r ON r.id = i.recurso_id "
        f"WHERE i.prestamo_id IN ({marcas}) ORDER BY nombre COLLATE NOCASE", list(ids)).fetchall()
    for f in filas:
        resumen.setdefault(f['prestamo_id'], []).append(f"{f['cantidad']}× {f['nombre']}")
    return {pid: ', '.join(partes) for pid, partes in resumen.items()}


def _parsear_items_prestamo(recursos):
    """Lee las filas recurso_N/cantidad_N del form. Devuelve ([(recurso_id, cantidad)], errores).
    El recurso se resuelve por el sufijo "[#id]" que agrega el datalist, o por nombre
    exacto (sin acentos) si lo tipearon a mano. Filas repetidas suman cantidades."""
    por_id = {r['id'] for r in recursos}
    por_nombre = {}
    for r in recursos:
        por_nombre.setdefault(_norm(r['nombre']), []).append(r['id'])
    items, errores = {}, []
    for n in range(1, PRESTAMO_FILAS_FORM + 1):
        texto = request.form.get(f'recurso_{n}', '').strip()
        if not texto:
            continue
        cantidad = request.form.get(f'cantidad_{n}', '').strip() or '1'
        if not cantidad.isdigit() or int(cantidad) < 1:
            errores.append(f'Cantidad inválida para "{texto}".')
            continue
        m = re.search(r'\[#(\d+)\]\s*$', texto)
        if m and int(m.group(1)) in por_id:
            rid = int(m.group(1))
        else:
            candidatos = por_nombre.get(_norm(re.sub(r'\[#\d+\]\s*$', '', texto)), [])
            if len(candidatos) == 1:
                rid = candidatos[0]
            elif not candidatos:
                errores.append(f'No existe el recurso "{texto}" — elegilo de la lista.')
                continue
            else:
                errores.append(f'Hay varios recursos llamados "{texto}" — elegilo de la lista, que incluye el número.')
                continue
        items[rid] = items.get(rid, 0) + int(cantidad)
    return list(items.items()), errores


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
    resumen = _resumen_items(cur, [f['id'] for f in filas])
    con.close()
    activos = [f for f in filas if not f['fecha_devolucion']]
    devueltos = [f for f in filas if f['fecha_devolucion']]
    return render_template('gestion/prestamos_lista.html', activos=activos, devueltos=devueltos,
                           resumen=resumen, q=q, activo='prestamos')


@bp.route('/prestamos/nuevo', methods=['GET', 'POST'])
def prestamo_nuevo():
    con = conectar()
    cur = con.cursor()
    recursos = cur.execute("SELECT id, nombre, ubicacion FROM recursos ORDER BY nombre COLLATE NOCASE").fetchall()
    error = None
    if request.method == 'POST':
        persona = request.form.get('persona', '').strip()
        items, errores = _parsear_items_prestamo(recursos)
        if not persona:
            error = 'Falta quién retira.'
        elif errores:
            error = ' '.join(errores)
        elif not items:
            error = 'Cargá al menos un recurso.'
        else:
            cur.execute("INSERT INTO prestamos (persona, destino, notas, fecha_salida, fecha_devolucion) VALUES (?,?,?,?,'')",
                        (persona, request.form.get('destino', '').strip(),
                         request.form.get('notas', '').strip(), _ahora()))
            pid = cur.lastrowid
            for rid, cantidad in items:
                cur.execute("INSERT INTO prestamo_items (prestamo_id, recurso_id, cantidad) VALUES (?,?,?)",
                            (pid, rid, str(cantidad)))
            con.commit()
            con.close()
            return redirect(url_for('gestion.prestamo_detalle', id=pid))
    con.close()
    return render_template('gestion/prestamos_form.html', recursos=recursos,
                           filas=range(1, PRESTAMO_FILAS_FORM + 1), valores=request.form,
                           error=error, activo='prestamos')


@bp.route('/prestamos/<int:id>')
def prestamo_detalle(id):
    con = conectar()
    cur = con.cursor()
    fila = cur.execute("SELECT * FROM prestamos WHERE id = ?", (id,)).fetchone()
    if fila is None:
        con.close()
        abort(404)
    items = cur.execute(
        "SELECT i.cantidad, i.recurso_id, r.nombre, r.ubicacion FROM prestamo_items i "
        "LEFT JOIN recursos r ON r.id = i.recurso_id WHERE i.prestamo_id = ? "
        "ORDER BY r.nombre COLLATE NOCASE", (id,)).fetchall()
    con.close()
    return render_template('gestion/prestamos_detalle.html', fila=fila, items=items, activo='prestamos')


@bp.route('/prestamos/<int:id>/devolver', methods=['POST'])
def prestamo_devolver(id):
    con = conectar()
    cur = con.cursor()
    cur.execute("UPDATE prestamos SET fecha_devolucion = ? WHERE id = ? AND fecha_devolucion = ''",
                (_ahora(), id))
    con.commit()
    con.close()
    if request.form.get('volver') == 'detalle':
        return redirect(url_for('gestion.prestamo_detalle', id=id))
    return redirect(url_for('gestion.prestamos_lista'))


@bp.route('/prestamos/<int:id>/reabrir', methods=['POST'])
def prestamo_reabrir(id):
    """Deshace una devolución marcada por error (vuelve a figurar como prestado)."""
    con = conectar()
    cur = con.cursor()
    cur.execute("UPDATE prestamos SET fecha_devolucion = '' WHERE id = ?", (id,))
    con.commit()
    con.close()
    return redirect(url_for('gestion.prestamo_detalle', id=id))


@bp.route('/prestamos/<int:id>/eliminar', methods=['POST'])
def prestamo_eliminar(id):
    """Solo para registros mal cargados — la devolución normal usa /devolver."""
    con = conectar()
    cur = con.cursor()
    cur.execute("DELETE FROM prestamos WHERE id = ?", (id,))
    cur.execute("DELETE FROM prestamo_items WHERE prestamo_id = ?", (id,))
    con.commit()
    con.close()
    return redirect(url_for('gestion.prestamos_lista'))
