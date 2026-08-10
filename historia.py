# historia.py
# Historia institucional de la escuela — módulo hermano de gestion.py, mismo patrón,
# DB propia (historia.db) y sin importar gestion.py (cero dependencia cruzada: se puede
# borrar uno de los dos módulos sin tocar el otro).
#
# Entidades: hitos (línea del tiempo institucional) y personas (quién hizo la escuela).
# Relación M2M: persona_hitos. No hay "proyectos": lo que antes era un proyecto es hoy
# un hito con 'Proyecto' en su campo etiquetas (ver dev-log/DECISIONS.md).
#
# Nota de naming: existe un sistema completamente distinto e independiente llamado
# "historias" (historias/*.json + historia_indice.json + HISTORIAS_PROCEDIMIENTO.md) —
# son las anécdotas que narra el personaje Emilio Mitre en el chat. Este módulo
# (historia.py, hitos/personas con ficha) no tiene relación con ese: ver
# agent_docs/historia-institucional.md.

import base64
import difflib
import glob
import hashlib
import json
import os
import sqlite3
import unicodedata
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, abort, session, jsonify

from config import ESCUELA_NOMBRE, ESCUELA_LOGO, ESCUELA_VERSION

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'historia.db')

# Respaldos rotativos de historia.db, mismo mecanismo que gestion.py (ver ahí el porqué:
# esta DB tampoco se regenera desde ninguna fuente externa y está en .gitignore).
BACKUP_DIR = os.path.join(os.path.dirname(DB_PATH), 'backups')
BACKUP_MAX = 20

bp = Blueprint('historia', __name__, url_prefix='/historia')

# --- Acceso con contraseña compartida (provisorio) ---------------------------
# Mismo env var y misma clave de sesión que gestion.py (GESTION_CLAVE / gestion_ok):
# una sola contraseña sirve para todas las áreas de gestión, aunque cada módulo tiene
# su propia copia del gate (sin importar gestion.py).
CLAVE = os.environ.get('GESTION_CLAVE', 'mitre2026')


@bp.before_request
def _requiere_clave():
    if request.endpoint == 'historia.login' or session.get('gestion_ok'):
        return
    return redirect(url_for('historia.login', next=request.path))


@bp.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form.get('clave', '') == CLAVE:
            session['gestion_ok'] = True
            destino = request.form.get('next', '')
            # Solo volver a rutas del propio módulo (evita open redirect).
            if not destino.startswith('/historia'):
                destino = url_for('historia.home')
            return redirect(destino)
        error = 'Contraseña incorrecta.'
    return render_template('historia/login.html', error=error,
                           next=request.values.get('next', ''), activo=None)


@bp.route('/salir')
def salir():
    session.pop('gestion_ok', None)
    return redirect(url_for('historia.login'))


TIPOS_HITO = ["Evento", "Logro", "Carrera nueva", "Construcción", "Participación", "Programa", "Otro"]
NIVELES_HITO = ["Básico", "Importante", "Crítico"]

# Configuración declarativa de cada entidad: campos del form, columnas del listado
# y relaciones M2M editables desde su formulario. Los campos de relación usan el
# prefijo "rel_" para no colisionar con nombres de columnas.
ENTIDADES = {
    'hitos': {
        'tabla': 'hitos',
        'singular': 'Hito',
        'plural': 'Hitos',
        # Única entidad cuya columna de nombre no se llama 'nombre' — ver _select().
        'campo_nombre': 'titulo',
        'descripcion': 'Línea del tiempo institucional: eventos, logros, creaciones, participaciones y cambios significativos de la escuela',
        'campos': [
            {'nombre': 'titulo', 'label': 'Título del hito', 'tipo': 'text', 'requerido': True},
            {'nombre': 'descripcion', 'label': 'Descripción', 'tipo': 'textarea'},
            {'nombre': 'fecha', 'label': 'Fecha', 'tipo': 'date', 'requerido': True},
            {'nombre': 'tipo', 'label': 'Tipo', 'tipo': 'select', 'opciones': TIPOS_HITO},
            {'nombre': 'nivel', 'label': 'Importancia', 'tipo': 'select', 'opciones': NIVELES_HITO,
             'ayuda': 'Básico: evento/actividad. Importante: logro, programa nuevo. Crítico: olimpiada, construcción significativa'},
            {'nombre': 'etiquetas', 'label': 'Etiquetas (separadas por coma)', 'tipo': 'text',
             'ayuda': 'Ej: Energías Renovables, Olimpiada, Matemática, Nacional, Proyecto'},
            {'nombre': 'protagonistas', 'label': 'Personas/cursos involucrados', 'tipo': 'text'},
            {'nombre': 'drive_url', 'label': 'Fotos, documentos (Drive)', 'tipo': 'url'},
        ],
        'columnas': [('fecha', 'FECHA'), ('titulo', 'HITO'), ('etiquetas', 'ETIQUETAS'), ('tipo', 'TIPO'), ('nivel', 'NIVEL')],
        'relaciones': [
            {'campo': 'rel_personas', 'label': 'Personas con ficha', 'tabla': 'persona_hitos',
             'col_propia': 'hito_id', 'col_ajena': 'persona_id', 'slug_ajeno': 'personas'},
        ],
    },
    'personas': {
        'tabla': 'personas',
        'singular': 'Persona',
        'plural': 'Personas',
        'descripcion': 'Quiénes hacen y hicieron la escuela: docentes, preceptores, no docentes. Una semblanza por persona y los hilos que la conectan con hitos.',
        'campos': [
            {'nombre': 'nombre', 'label': 'Nombre y apellido', 'tipo': 'text', 'requerido': True},
            {'nombre': 'descripcion', 'label': 'Semblanza', 'tipo': 'textarea',
             'ayuda': 'Quién es y qué aporta a la escuela, en prosa. Ej: "Ingeniero del INTI; sus prácticas de armado de colector solar son un clásico de 6°." El rol no es un campo aparte: si importa, va acá.'},
            {'nombre': 'drive_url', 'label': 'Carpeta de Drive (link)', 'tipo': 'url'},
        ],
        'columnas': [('nombre', 'NOMBRE'), ('fecha_actualizada', 'ACTUALIZADA')],
        'relaciones': [
            {'campo': 'rel_hitos', 'label': 'Hitos en los que aparece', 'tabla': 'persona_hitos',
             'col_propia': 'persona_id', 'col_ajena': 'hito_id', 'slug_ajeno': 'hitos'},
        ],
    },
}

# Tablas M2M a limpiar cuando se elimina una entidad de cada tipo.
LIMPIEZA_M2M = {
    'hitos': [('persona_hitos', 'hito_id')],
    'personas': [('persona_hitos', 'persona_id')],
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS hitos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo TEXT NOT NULL,
    descripcion TEXT DEFAULT '',
    fecha TEXT NOT NULL,
    tipo TEXT DEFAULT '',
    nivel TEXT DEFAULT 'Básico',
    etiquetas TEXT DEFAULT '',
    protagonistas TEXT DEFAULT '',
    drive_url TEXT DEFAULT '',
    fotos TEXT DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_hitos_fecha ON hitos(fecha DESC);
CREATE INDEX IF NOT EXISTS idx_hitos_nivel ON hitos(nivel);
CREATE TABLE IF NOT EXISTS personas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    nombre_norm TEXT NOT NULL DEFAULT '',
    descripcion TEXT DEFAULT '',
    fecha_actualizada TEXT DEFAULT '',
    drive_url TEXT DEFAULT '',
    fotos TEXT DEFAULT '[]'
);
-- La identidad de una persona es su nombre normalizado, no el que se tipeó: el mismo
-- docente entra como "Juan Pablo Crivari" desde el chat y como "CRIVARI JUAN PABLO"
-- desde los horarios. Sin este UNIQUE quedan dos nodos y los hilos M2M se reparten.
CREATE UNIQUE INDEX IF NOT EXISTS idx_personas_norm ON personas(nombre_norm);
CREATE TABLE IF NOT EXISTS persona_hitos (
    persona_id INTEGER NOT NULL,
    hito_id INTEGER NOT NULL,
    UNIQUE(persona_id, hito_id)
);
CREATE INDEX IF NOT EXISTS idx_persona_hitos ON persona_hitos(persona_id);
"""


def _norm(texto):
    """Minúsculas, sin acentos, espacios colapsados — para comparar nombres."""
    texto = unicodedata.normalize('NFD', texto)
    texto = ''.join(c for c in texto if unicodedata.category(c) != 'Mn')
    return ' '.join(texto.lower().split())


# Búsqueda "que perdona" — misma lógica y mismo umbral que gestion.py (duplicado a
# propósito, ver dev-log/DECISIONS.md: se prefirió independencia física a compartir
# el motor de búsqueda entre los dos módulos).
UMBRAL_SIMILITUD = 0.68


def _puntaje_busqueda(q_norm, *textos):
    """Qué tan bien `q_norm` (ya normalizado) matchea los textos dados.
    Devuelve un puntaje mayor = mejor, o None si no llega al umbral. Los que
    contienen la query como substring puntúan por encima de los difusos."""
    difuso = len(q_norm) >= 3
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
        return 1.0 + mejor
    if difuso and mejor >= UMBRAL_SIMILITUD:
        return mejor
    return None


def conectar():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _tiene_datos(ruta):
    """True si la DB de `ruta` existe y tiene al menos un hito cargado."""
    if not os.path.exists(ruta) or os.path.getsize(ruta) == 0:
        return False
    try:
        con = sqlite3.connect(f'file:{ruta}?mode=ro', uri=True)
        try:
            return con.execute("SELECT COUNT(*) FROM hitos").fetchone()[0] > 0
        finally:
            con.close()
    except sqlite3.Error:
        return False


def _hash_archivo(ruta):
    h = hashlib.sha256()
    with open(ruta, 'rb') as f:
        for bloque in iter(lambda: f.read(1 << 20), b''):
            h.update(bloque)
    return h.hexdigest()


def respaldos():
    """Respaldos existentes, del más viejo al más nuevo."""
    return sorted(glob.glob(os.path.join(BACKUP_DIR, 'historia-*.db')))


def respaldar_db(max_copias=BACKUP_MAX):
    """Copia historia.db a backups/ y conserva las últimas `max_copias` (mismo
    mecanismo que gestion.respaldar_db — ver ahí el detalle de cada decisión)."""
    if not _tiene_datos(DB_PATH):
        return None

    os.makedirs(BACKUP_DIR, exist_ok=True)
    destino = os.path.join(BACKUP_DIR, f"historia-{datetime.now():%Y%m%d-%H%M%S-%f}.db")

    origen = sqlite3.connect(DB_PATH)
    copia = sqlite3.connect(destino)
    try:
        origen.backup(copia)
    finally:
        copia.close()
        origen.close()

    previos = [r for r in respaldos() if r != destino]
    if previos and _hash_archivo(previos[-1]) == _hash_archivo(destino):
        os.remove(destino)
        return previos[-1]

    for viejo in _a_borrar(respaldos(), max_copias):
        os.remove(viejo)
    return destino


def _dia(ruta):
    return os.path.basename(ruta).split('-')[1]


def _a_borrar(existentes, max_copias):
    """Conserva los últimos `max_copias` MÁS el primero de cada día (ver gestion.py)."""
    recientes = set(existentes[-max_copias:])
    primero_del_dia = {}
    for r in existentes:
        primero_del_dia.setdefault(_dia(r), r)
    conservar = recientes | set(primero_del_dia.values())
    return [r for r in existentes if r not in conservar]


def init_db():
    """Crea las tablas si no existen, migra columnas nuevas y siembra la primera vez.
    Respalda antes de tocar nada (ver respaldar_db)."""
    respaldar_db()

    con = conectar()
    cur = con.cursor()
    cur.executescript(SCHEMA)
    _migrar(cur)
    if cur.execute("SELECT COUNT(*) FROM hitos").fetchone()[0] == 0:
        # Misma protección que gestion.py: una DB vacía con respaldos existentes es
        # sospechosa (se perdió el archivo), no una instalación nueva.
        if respaldos() and os.environ.get('GESTION_SEED') != '1':
            ultimo = respaldos()[-1]
            con.close()
            raise RuntimeError(
                f"historia.db está vacía pero hay {len(respaldos())} respaldo(s) en {BACKUP_DIR}.\n"
                f"Probablemente se perdió el archivo — NO se cargaron datos.\n\n"
                f"Para restaurar el más reciente:\n"
                f"    copy \"{ultimo}\" \"{DB_PATH}\"\n\n"
                f"Si de verdad querés empezar de cero:\n"
                f"    GESTION_SEED=1 python app.py"
            )
        _seed(cur)
    con.commit()
    con.close()


def _migrar(cur):
    """Adapta una historia.db creada con un schema anterior (ALTER aditivo)."""
    for tabla in ('hitos', 'personas'):
        cols = {c[1] for c in cur.execute(f"PRAGMA table_info({tabla})").fetchall()}
        if 'fotos' not in cols:
            cur.execute(f"ALTER TABLE {tabla} ADD COLUMN fotos TEXT DEFAULT '[]'")


def _seed(cur):
    """Sin datos de ejemplo: los datos reales vienen de migrar_proyecto_a_hito.py
    (migración desde gestion.db). Una instalación nueva arranca vacía."""
    pass


def _cfg(slug):
    if slug not in ENTIDADES:
        abort(404)
    return ENTIDADES[slug]


def _campo_nombre(cfg):
    """Columna que hace de nombre visible de la entidad (`hitos` la llama `titulo`)."""
    return cfg.get('campo_nombre', 'nombre')


def _select(cfg):
    """SELECT que SIEMPRE expone una columna `nombre`, se llame como se llame en la tabla."""
    campo = _campo_nombre(cfg)
    alias = '' if campo == 'nombre' else f", {campo} AS nombre"
    return f"SELECT *{alias} FROM {cfg['tabla']}"


def buscar_entidad_sin_request(slug, query, con=None):
    """Búsqueda de entidades reusable por el agente (no depende de Flask request)."""
    cfg = _cfg(slug) if slug in ENTIDADES else None
    if not cfg:
        return []

    debe_cerrar = con is None
    if con is None:
        con = conectar()
    cur = con.cursor()

    filas = cur.execute(f"{_select(cfg)} ORDER BY nombre COLLATE NOCASE").fetchall()
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
    """Versión de _guardar que recibe un dict de campos en vez de leer request.form."""
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
        for columna, valor in _derivados(slug, dict(zip(nombres, valores))).items():
            nombres.append(columna)
            valores.append(valor)

        if id is None:
            placeholders = ','.join('?' * len(nombres))
            cur.execute(f"INSERT INTO {cfg['tabla']} ({','.join(nombres)}) VALUES ({placeholders})", valores)
            id = cur.lastrowid
        else:
            sets = ','.join(f"{n} = ?" for n in nombres)
            cur.execute(f"UPDATE {cfg['tabla']} SET {sets} WHERE id = ?", valores + [id])

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
    except Exception:
        con.close() if debe_cerrar else None
        return None


def snapshot_entidad(slug, id, con=None):
    """Snapshot de una fila + sus relaciones M2M, para auditar antes de borrar."""
    cfg = _cfg(slug) if slug in ENTIDADES else None
    if not cfg:
        return None

    debe_cerrar = con is None
    if con is None:
        con = conectar()
    cur = con.cursor()

    fila = cur.execute(f"{_select(cfg)} WHERE id = ?", (id,)).fetchone()

    if fila is None:
        con.close() if debe_cerrar else None
        return None

    relaciones = {}
    for rel in cfg['relaciones']:
        ids = [r[0] for r in cur.execute(f"SELECT {rel['col_ajena']} FROM {rel['tabla']} WHERE {rel['col_propia']} = ?", (id,)).fetchall()]
        relaciones[rel['slug_ajeno']] = ids

    m2m = {}
    for tabla, columna in LIMPIEZA_M2M.get(slug, []):
        filas_m2m = cur.execute(f"SELECT * FROM {tabla} WHERE {columna} = ?", (id,)).fetchall()
        if filas_m2m:
            m2m[tabla] = [dict(f) for f in filas_m2m]

    con.close() if debe_cerrar else None
    return {'fila': dict(fila), 'relaciones': relaciones, 'm2m': m2m}


def agregar_relacion_m2m(tabla, col_propia, col_ajena, id_propio, id_ajeno, con=None):
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
    opciones = {}
    for rel in cfg['relaciones']:
        cfg_ajeno = ENTIDADES[rel['slug_ajeno']]
        opciones[rel['campo']] = cur.execute(
            f"SELECT id, {_campo_nombre(cfg_ajeno)} AS nombre FROM {cfg_ajeno['tabla']} "
            f"ORDER BY nombre COLLATE NOCASE").fetchall()
    return opciones


def _seleccion_relaciones(cfg, id, cur):
    seleccion = {}
    for rel in cfg['relaciones']:
        filas = cur.execute(f"SELECT {rel['col_ajena']} FROM {rel['tabla']} WHERE {rel['col_propia']} = ?", (id,)).fetchall()
        seleccion[rel['campo']] = {f[0] for f in filas}
    return seleccion


_ERROR_DUPLICADO = {
    'personas': 'Ya hay una persona cargada con ese nombre. Buscala en el listado y editala '
                'en vez de crear una segunda ficha.',
}


def clave_persona(nombre):
    """Identidad de una persona: sus palabras normalizadas y ordenadas alfabéticamente
    (ver gestion.clave_persona — misma lógica, mismo motivo)."""
    limpio = ''.join(c if (c.isalnum() or c.isspace()) else ' ' for c in nombre)
    return ' '.join(sorted(_norm(limpio).split()))


def _derivados(slug, valores):
    if slug != 'personas':
        return {}
    return {
        'nombre_norm': clave_persona(valores.get('nombre', '')),
        'fecha_actualizada': datetime.now().strftime(FORMATO_FECHA_REVISION),
    }


def _guardar(slug, cfg, cur, id=None):
    """Inserta o actualiza la fila y sincroniza sus relaciones M2M. Devuelve el id."""
    nombres = [c['nombre'] for c in cfg['campos']]
    valores = [request.form.get(n, '').strip() for n in nombres]
    for columna, valor in _derivados(slug, dict(zip(nombres, valores))).items():
        nombres.append(columna)
        valores.append(valor)
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

    if slug == 'hitos':
        agregar('Personas involucradas', 'personas',
                "SELECT p.id, p.nombre FROM personas p JOIN persona_hitos r ON r.persona_id = p.id WHERE r.hito_id = ? ORDER BY p.nombre COLLATE NOCASE")
    elif slug == 'personas':
        agregar('Hitos en los que aparece', 'hitos',
                "SELECT h.id, h.titulo AS nombre FROM hitos h JOIN persona_hitos r ON r.hito_id = h.id WHERE r.persona_id = ? ORDER BY h.fecha DESC")
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
    return render_template('historia/home.html', tarjetas=tarjetas, activo='home')


@bp.route('/<slug>')
def lista(slug):
    cfg = _cfg(slug)
    q = request.args.get('q', '').strip()
    con = conectar()
    cur = con.cursor()
    filas = cur.execute(f"{_select(cfg)} ORDER BY nombre COLLATE NOCASE").fetchall()
    con.close()
    if q:
        q_norm = _norm(q)
        puntuadas = []
        for fila in filas:
            puntaje = _puntaje_busqueda(q_norm, fila['nombre'], fila['descripcion'])
            if puntaje is not None:
                puntuadas.append((puntaje, fila))
        puntuadas.sort(key=lambda par: (-par[0], _norm(par[1]['nombre'])))
        filas = [fila for _, fila in puntuadas]
    buscar = {fila['id']: _norm(f"{fila['nombre']} {fila['descripcion'] or ''}") for fila in filas}
    return render_template('historia/lista.html', cfg=cfg, slug=slug, filas=filas, q=q,
                           activo=slug, buscar=buscar)


# Formato de personas.fecha_actualizada — mismo formato que gestion.FORMATO_FECHA_REVISION,
# duplicado a propósito (ver Contexto del módulo).
FORMATO_FECHA_REVISION = '%d/%m/%Y'


@bp.route('/<slug>/nuevo', methods=['GET', 'POST'])
def nuevo(slug):
    cfg = _cfg(slug)
    con = conectar()
    cur = con.cursor()
    error = None
    if request.method == 'POST':
        if not request.form.get(_campo_nombre(cfg), '').strip():
            error = 'El nombre es obligatorio.'
        else:
            try:
                id = _guardar(slug, cfg, cur)
            except sqlite3.IntegrityError:
                error = _ERROR_DUPLICADO.get(slug, 'Ya existe un registro igual.')
            else:
                con.commit()
                con.close()
                return redirect(url_for('historia.detalle', slug=slug, id=id))
    opciones = _opciones_relaciones(cfg, cur)
    con.close()
    seleccion = {rel['campo']: {int(v) for v in request.form.getlist(rel['campo'])} for rel in cfg['relaciones']}
    valores = request.form if request.method == 'POST' else {}
    return render_template('historia/form.html', cfg=cfg, slug=slug, fila=None, valores=valores,
                           opciones=opciones, seleccion=seleccion, error=error, activo=slug)


@bp.route('/<slug>/<int:id>')
def detalle(slug, id):
    cfg = _cfg(slug)
    con = conectar()
    cur = con.cursor()
    fila = cur.execute(f"{_select(cfg)} WHERE id = ?", (id,)).fetchone()
    if fila is None:
        con.close()
        abort(404)
    secciones = _secciones_detalle(slug, id, cur)
    con.close()
    fila_dict = dict(fila)
    fila_dict['fotos'] = json.loads(fila_dict.get('fotos', '[]'))
    return render_template('historia/detalle.html', cfg=cfg, slug=slug, fila=fila_dict,
                           secciones=secciones, activo=slug)


@bp.route('/<slug>/<int:id>/editar', methods=['GET', 'POST'])
def editar(slug, id):
    cfg = _cfg(slug)
    con = conectar()
    cur = con.cursor()
    fila = cur.execute(f"{_select(cfg)} WHERE id = ?", (id,)).fetchone()
    if fila is None:
        con.close()
        abort(404)
    error = None
    if request.method == 'POST':
        if not request.form.get(_campo_nombre(cfg), '').strip():
            error = 'El nombre es obligatorio.'
        else:
            try:
                _guardar(slug, cfg, cur, id)
            except sqlite3.IntegrityError:
                error = _ERROR_DUPLICADO.get(slug, 'Ya existe un registro igual.')
            else:
                con.commit()
                con.close()
                return redirect(url_for('historia.detalle', slug=slug, id=id))
    opciones = _opciones_relaciones(cfg, cur)
    seleccion = _seleccion_relaciones(cfg, id, cur)
    con.close()
    valores = request.form if request.method == 'POST' else fila
    return render_template('historia/form.html', cfg=cfg, slug=slug, fila=fila, valores=valores,
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
    return redirect(url_for('historia.lista', slug=slug))


def agregar_foto(slug, id, b64, tipo):
    """Agrega una foto ya en base64 a la galería de una entidad (mismo camino que
    usa el agente para fotos de datasheets — ver gestion.agregar_foto)."""
    cfg = _cfg(slug)
    con = conectar()
    cur = con.cursor()
    fila = cur.execute(f"SELECT fotos FROM {cfg['tabla']} WHERE id = ?", (id,)).fetchone()
    if fila is None:
        con.close()
        return False
    fotos = json.loads(fila['fotos'] or '[]')
    fotos.append({'b64': b64, 'tipo': tipo, 'fecha': datetime.now().isoformat()})
    cur.execute(f"UPDATE {cfg['tabla']} SET fotos = ? WHERE id = ?", (json.dumps(fotos), id))
    con.commit()
    con.close()
    return True


@bp.route('/<slug>/<int:id>/foto', methods=['POST'])
def subir_foto(slug, id):
    """Sube una foto, la convierte a base64 y la guarda en el JSON de fotos."""
    _cfg(slug)  # 404 temprano si el slug no existe

    if 'file' not in request.files:
        return jsonify({'ok': False, 'error': 'No hay archivo'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'ok': False, 'error': 'Archivo vacío'}), 400

    if not file.content_type.startswith('image/'):
        return jsonify({'ok': False, 'error': 'Solo se aceptan imágenes'}), 400

    try:
        b64 = base64.b64encode(file.read()).decode('utf-8')
        if not agregar_foto(slug, id, b64, file.content_type):
            return jsonify({'ok': False, 'error': 'No existe el registro'}), 404
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
