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
import sqlite3
import unicodedata
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, abort, session, jsonify

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


ESTADOS_RECURSO = ["Disponible", "Retirado", "En uso", "En reparación", "De baja", "Sin revisar"]
ESTADOS_PROYECTO = ["Activo", "Pausado", "Terminado"]
# "" primero: permite dejar el valor sin definir (recursos previos al inventario).
VALORES_RECURSO = ["", "Básico", "Secundario", "Alto valor"]
TIPOS_HITO = ["Evento", "Logro", "Carrera nueva", "Construcción", "Participación", "Programa", "Otro"]
NIVELES_HITO = ["Básico", "Importante", "Crítico"]

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
            {'nombre': 'valor', 'label': 'Valor', 'tipo': 'select', 'opciones': VALORES_RECURSO, 'ayuda': 'Importancia del recurso dentro del inventario'},
            {'nombre': 'fecha_revision', 'label': 'Última revisión', 'tipo': 'text', 'ayuda': 'Fecha del último control de inventario (día/mes/año). En un alta arranca en hoy'},
            {'nombre': 'drive_url', 'label': 'Carpeta de Drive (link)', 'tipo': 'url', 'ayuda': 'Fotos, planos y documentos viven en Drive; acá solo va el link'},
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
    'hitos': {
        'tabla': 'hitos',
        'singular': 'Hito',
        'plural': 'Hitos',
        'descripcion': 'Línea del tiempo institucional: eventos, logros, creaciones, participaciones y cambios significativos de la escuela',
        'campos': [
            {'nombre': 'titulo', 'label': 'Título del hito', 'tipo': 'text', 'requerido': True},
            {'nombre': 'descripcion', 'label': 'Descripción', 'tipo': 'textarea'},
            {'nombre': 'fecha', 'label': 'Fecha', 'tipo': 'date', 'requerido': True},
            {'nombre': 'tipo', 'label': 'Tipo', 'tipo': 'select', 'opciones': TIPOS_HITO},
            {'nombre': 'nivel', 'label': 'Importancia', 'tipo': 'select', 'opciones': NIVELES_HITO,
             'ayuda': 'Básico: evento/actividad. Importante: logro, programa nuevo. Crítico: olimpiada, construcción significativa'},
            {'nombre': 'etiquetas', 'label': 'Etiquetas (separadas por coma)', 'tipo': 'text',
             'ayuda': 'Ej: Energías Renovables, Olimpiada, Matemática, Nacional'},
            {'nombre': 'protagonistas', 'label': 'Personas/cursos involucrados', 'tipo': 'text'},
            {'nombre': 'drive_url', 'label': 'Fotos, documentos (Drive)', 'tipo': 'url'},
        ],
        'columnas': [('fecha', 'FECHA'), ('titulo', 'HITO'), ('etiquetas', 'ETIQUETAS'), ('tipo', 'TIPO'), ('nivel', 'NIVEL')],
        'relaciones': [],
    },
}

# Tablas M2M a limpiar cuando se elimina una entidad de cada tipo.
LIMPIEZA_M2M = {
    'recursos': [('conjunto_recursos', 'recurso_id'), ('actividad_recursos', 'recurso_id'), ('proyecto_recursos', 'recurso_id')],
    'conjuntos': [('conjunto_recursos', 'conjunto_id'), ('actividad_conjuntos', 'conjunto_id')],
    'actividades': [('actividad_recursos', 'actividad_id'), ('actividad_conjuntos', 'actividad_id')],
    'proyectos': [('proyecto_recursos', 'proyecto_id')],
    'hitos': [],
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
    valor TEXT DEFAULT '',
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
    cantidad_devuelta TEXT DEFAULT '0',
    UNIQUE(prestamo_id, recurso_id)
);
CREATE TABLE IF NOT EXISTS hitos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo TEXT NOT NULL,
    descripcion TEXT DEFAULT '',
    fecha TEXT NOT NULL,
    tipo TEXT DEFAULT '',
    nivel TEXT DEFAULT 'Básico',
    etiquetas TEXT DEFAULT '',
    protagonistas TEXT DEFAULT '',
    drive_url TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_hitos_fecha ON hitos(fecha DESC);
CREATE INDEX IF NOT EXISTS idx_hitos_nivel ON hitos(nivel);
"""


def _norm(texto):
    """Minúsculas, sin acentos, espacios colapsados — para comparar nombres."""
    texto = unicodedata.normalize('NFD', texto)
    texto = ''.join(c for c in texto if unicodedata.category(c) != 'Mn')
    return ' '.join(texto.lower().split())


# Búsqueda "que perdona": en vez del LIKE literal, normaliza acentos/mayúsculas y
# tolera typos por similitud (difflib, sin dependencias). El substring normalizado
# siempre gana; la similitud difusa solo entra para queries de 3+ caracteres (con
# menos daría demasiado ruido). Subir = más estricto.
#
# 0.68 salió de medir contra el inventario real (91 recursos), no a ojo: con 0.6
# buscar "taladro" (que no existe) devolvía 4 recursos, "guantes" 7 y "multimetro"
# traía 8 con "Pintura marrón (tarro)" adentro. Para nombres cortos, 0.6 deja pasar
# casi cualquier cosa que comparta vocales. A 0.68 esos casos caen a 0/1/1 y el
# recall no se toca: todas las queries con typo probadas ("multimetr0", "alikate",
# "agujeradora", "anemometroo", "caladra") siguen encontrando su recurso en el
# puesto #1. Arriba de 0.68 se gana poco y se empieza a arriesgar recall.
UMBRAL_SIMILITUD = 0.68


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
    """Adapta una gestion.db creada con un schema anterior (ALTER aditivo + renombres)."""
    existentes = {c[1] for c in cur.execute("PRAGMA table_info(recursos)").fetchall()}
    # 'utilidad' pasó a llamarse 'valor'. RENAME COLUMN conserva los datos ya cargados;
    # va antes del ALTER aditivo para no crear un 'valor' vacío al lado del viejo.
    if 'utilidad' in existentes and 'valor' not in existentes:
        cur.execute("ALTER TABLE recursos RENAME COLUMN utilidad TO valor")
        existentes = {c[1] for c in cur.execute("PRAGMA table_info(recursos)").fetchall()}
    for columna in ('cantidad', 'valor', 'fecha_revision'):
        if columna not in existentes:
            cur.execute(f"ALTER TABLE recursos ADD COLUMN {columna} TEXT DEFAULT ''")
    # Devolución por ítem: cuánto de cada ítem ya volvió (0 = sigue afuera entero).
    cols_items = {c[1] for c in cur.execute("PRAGMA table_info(prestamo_items)").fetchall()}
    if 'cantidad_devuelta' not in cols_items:
        cur.execute("ALTER TABLE prestamo_items ADD COLUMN cantidad_devuelta TEXT DEFAULT '0'")


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


def buscar_entidad_sin_request(slug, query, con=None):
    """Búsqueda de entidades reusable por el agente (no depende de Flask request).
    Retorna lista de dicts {id, nombre, descripcion, ...} ya filtrados y ordenados."""
    cfg = _cfg(slug) if slug in ENTIDADES else None
    if not cfg:
        return []

    debe_cerrar = con is None
    if con is None:
        con = conectar()
    cur = con.cursor()

    filas = cur.execute(f"SELECT * FROM {cfg['tabla']} ORDER BY nombre COLLATE NOCASE").fetchall()
    con.close() if debe_cerrar else None

    if not query:
        return [dict(f) for f in filas]

    q_norm = _norm(query)
    puntuadas = []
    for fila in filas:
        puntaje = _puntaje_busqueda(q_norm, fila['nombre'], fila['descripcion'])
        if puntaje is not None:
            puntuadas.append((puntaje, fila))
    puntuadas.sort(key=lambda par: (-par[0], _norm(par[1]['nombre'])))
    return [dict(fila) for _, fila in puntuadas]


def guardar_entidad_sin_request(slug, campos_dict, id=None, con=None):
    """Versión de _guardar que recibe un dict de campos en vez de leer request.form.
    Retorna el id creado o actualizado, o None si error."""
    cfg = _cfg(slug) if slug in ENTIDADES else None
    if not cfg:
        return None

    debe_cerrar = con is None
    if con is None:
        con = conectar()
    cur = con.cursor()

    try:
        nombres = [c['nombre'] for c in cfg['campos']]
        valores = [str(campos_dict.get(n, '')).strip() for n in nombres]

        if id is None:
            placeholders = ','.join('?' * len(nombres))
            cur.execute(f"INSERT INTO {cfg['tabla']} ({','.join(nombres)}) VALUES ({placeholders})", valores)
            id = cur.lastrowid
        else:
            sets = ','.join(f"{n} = ?" for n in nombres)
            cur.execute(f"UPDATE {cfg['tabla']} SET {sets} WHERE id = ?", valores + [id])

        # Relaciones M2M: si vienen en campos_dict con clave 'rel_*', procesarlas
        for rel in cfg['relaciones']:
            campo = rel['campo']
            if campo in campos_dict:
                cur.execute(f"DELETE FROM {rel['tabla']} WHERE {rel['col_propia']} = ?", (id,))
                for rid_str in (campos_dict[campo] if isinstance(campos_dict[campo], list) else []):
                    try:
                        rid = int(rid_str)
                        cur.execute(
                            f"INSERT OR IGNORE INTO {rel['tabla']} ({rel['col_propia']}, {rel['col_ajena']}) VALUES (?,?)",
                            (id, rid),
                        )
                    except (ValueError, TypeError):
                        pass

        con.commit()
        con.close() if debe_cerrar else None
        return id
    except Exception as e:
        con.close() if debe_cerrar else None
        return None


def snapshot_entidad(slug, id, con=None):
    """Retorna un snapshot de una fila + sus relaciones M2M, para auditar antes de borrar.
    Retorna dict con 'fila' (dict) y 'relaciones' (dict de slug -> [ids])."""
    cfg = _cfg(slug) if slug in ENTIDADES else None
    if not cfg:
        return None

    debe_cerrar = con is None
    if con is None:
        con = conectar()
    cur = con.cursor()

    fila = cur.execute(f"SELECT * FROM {cfg['tabla']} WHERE id = ?", (id,)).fetchone()

    if fila is None:
        con.close() if debe_cerrar else None
        return None

    relaciones = {}
    for rel in cfg['relaciones']:
        ids = [r[0] for r in cur.execute(f"SELECT {rel['col_ajena']} FROM {rel['tabla']} WHERE {rel['col_propia']} = ?", (id,)).fetchall()]
        relaciones[rel['slug_ajeno']] = ids

    # Filas M2M crudas que un borrado destruiría. No alcanza con 'relaciones': esa recorre
    # cfg['relaciones'] (dirección "hacia afuera"), y para 'recursos' está vacía — pero
    # LIMPIEZA_M2M sí borra sus 3 tablas inversas. Sin esto el snapshot decía relaciones={}
    # y un borrado erróneo de un recurso no se podía restaurar completo.
    m2m = {}
    for tabla, columna in LIMPIEZA_M2M.get(slug, []):
        filas_m2m = cur.execute(f"SELECT * FROM {tabla} WHERE {columna} = ?", (id,)).fetchall()
        if filas_m2m:
            m2m[tabla] = [dict(f) for f in filas_m2m]

    con.close() if debe_cerrar else None
    return {'fila': dict(fila), 'relaciones': relaciones, 'm2m': m2m}


def agregar_relacion_m2m(tabla, col_propia, col_ajena, id_propio, id_ajeno, con=None):
    """Agregar una fila a una tabla M2M."""
    debe_cerrar = con is None
    if con is None:
        con = conectar()
    cur = con.cursor()

    try:
        cur.execute(
            f"INSERT OR IGNORE INTO {tabla} ({col_propia}, {col_ajena}) VALUES (?,?)",
            (id_propio, id_ajeno),
        )
        con.commit()
        con.close() if debe_cerrar else None
        return True
    except Exception:
        con.close() if debe_cerrar else None
        return False


def quitar_relacion_m2m(tabla, col_propia, col_ajena, id_propio, id_ajeno, con=None):
    """Quitar una fila de una tabla M2M."""
    debe_cerrar = con is None
    if con is None:
        con = conectar()
    cur = con.cursor()

    try:
        cur.execute(f"DELETE FROM {tabla} WHERE {col_propia} = ? AND {col_ajena} = ?", (id_propio, id_ajeno))
        con.commit()
        con.close() if debe_cerrar else None
        return True
    except Exception:
        con.close() if debe_cerrar else None
        return False


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
        'carrito_count': len(_carrito()),  # ítems distintos en el carrito, para el badge del nav
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
    # Texto de búsqueda ya normalizado por fila, para el filtrado en vivo del navegador
    # (data-buscar). Mismo alcance que la búsqueda del server: nombre + descripcion.
    buscar = {fila['id']: _norm(f"{fila['nombre']} {fila['descripcion'] or ''}") for fila in filas}
    # En recursos, cada fila muestra el botón RETIRO / stepper del carrito; pasamos las
    # cantidades ya en el carrito para renderizar el estado inicial correcto.
    carrito = _carrito() if slug == 'recursos' else {}
    return render_template('gestion/lista.html', cfg=cfg, slug=slug, filas=filas, q=q,
                           activo=slug, buscar=buscar, carrito=carrito)


# Formato de `recursos.fecha_revision`. La columna es TEXT y el inventario importado del
# sheet trae fechas cortas sin año ("24/4"): conviven, pero lo que se carga de acá en más
# lleva el año. `agente.py` importa esta constante para no tener dos formatos distintos.
FORMATO_FECHA_REVISION = '%d/%m/%Y'


def _valores_iniciales(slug):
    """Con qué valores arranca el formulario de alta, antes de que el usuario escriba.

    Dar de alta un recurso ES un control de inventario, así que la fecha de revisión
    arranca en hoy. Antes quedaba vacía y casi ningún recurso terminaba con fecha.
    """
    if slug == 'recursos':
        return {'fecha_revision': datetime.now().strftime(FORMATO_FECHA_REVISION)}
    return {}


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
    # En el GET el form arranca con los defaults; en un POST fallido se respeta lo tipeado.
    valores = request.form if request.method == 'POST' else _valores_iniciales(slug)
    return render_template('gestion/form.html', cfg=cfg, slug=slug, fila=None, valores=valores,
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
    carrito = _carrito() if slug == 'recursos' else {}
    return render_template('gestion/detalle.html', cfg=cfg, slug=slug, fila=fila,
                           secciones=secciones, activo=slug, carrito=carrito)


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
#
# ALTA TIPO CARRITO DE COMPRA: no hay form de alta con filas de ítems. Navegando recursos se
# van agregando al carrito (session['carrito'] = {recurso_id: cantidad}); al finalizar
# se pide quién retira y recién ahí se crea el préstamo. El carrito vive en la sesión
# (por navegador), igual que el login. Ver rutas /carrito* más abajo.


def _ahora():
    return datetime.now().strftime('%Y-%m-%d %H:%M')


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
    filas.sort(key=lambda f: _norm(f['nombre']))
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
