# historia.py
# Historia institucional de la escuela — área de capa 2: declara sus entidades y sus
# reglas de negocio, y el CRUD se lo da el motor genérico (crud.py). DB propia:
# historia.db. No importa gestion.py.
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

import os
import sys

from config import ahora
from flask import Blueprint

import accesos
import crud
import texto

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'historia.db')

# Permisos que declara el área al catálogo de `accesos`. Ver gestion.py para el criterio
# del verbo.
PERMISOS = [
    ('historia.leer', 'Ver la línea del tiempo de hitos', 'leer'),
    ('historia.editar', 'Cargar, editar y eliminar hitos', 'escribir'),
    # Verbo 'admin' = no entra en ningún preset de interno (ver accesos.PERFILES, que los
    # arma por verbo): sólo lo tiene el admin, por el comodín '*'. Las semblanzas son
    # sobre personas concretas de la escuela y no son para el que consulta el inventario.
    # El permiso lo cuelga la entidad `personas` con la clave `permiso` de su cfg, así que
    # cubre de una vez ver el listado, la ficha, el formulario y la sección de personas
    # dentro de un hito — ver crud.permiso_entidad.
    ('historia.personas', 'Ver y editar las fichas de personas', 'admin'),
]
GRUPO_PERMISOS = 'Historia institucional'
PERMISO_LECTURA = 'historia.leer'
PERMISO_ESCRITURA = 'historia.editar'

# Respaldos rotativos: la maquinaria vive en respaldos.py (capa 0). Acá sólo se declara
# con qué prefijo se guardan y qué tabla mirar para saber si la DB tiene datos de verdad
# (una DB vacía no se respalda: taparía los respaldos buenos).
PREFIJO_BACKUP = 'historia'
TABLA_TESTIGO = 'hitos'

bp = Blueprint('historia', __name__, url_prefix='/historia')

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
        # Entidad con permiso propio: sin `historia.personas` no se ve ni el listado, ni
        # una ficha, ni el bloque de personas de un hito. Ver crud.permiso_entidad.
        'permiso': 'historia.personas',
        'descripcion':'Quiénes hacen y hicieron la escuela: docentes, preceptores, no docentes. Una semblanza por persona y los hilos que la conectan con hitos.',
        'campos': [
            {'nombre': 'nombre', 'label': 'Nombre y apellido', 'tipo': 'text', 'requerido': True},
            {'nombre': 'descripcion', 'label': 'Semblanza', 'tipo': 'textarea',
             'ayuda': 'Quién es y qué aporta a la escuela, en prosa. Ej: "Ingeniero del INTI; sus prácticas de armado de colector solar son un clásico de 6°." El rol no es un campo aparte: si importa, va acá.'},
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


def migrar(cur):
    """Adapta una historia.db creada con un schema anterior (ALTER aditivo)."""
    for tabla in ('hitos', 'personas'):
        cols = {c[1] for c in cur.execute(f"PRAGMA table_info({tabla})").fetchall()}
        if 'fotos' not in cols:
            cur.execute(f"ALTER TABLE {tabla} ADD COLUMN fotos TEXT DEFAULT '[]'")

    # `drive_url` se eliminó junto con el de gestion.py: la escuela dejó de usar Drive y la
    # fuente de verdad pasó a ser la DB. Migración destructiva, corrida con la columna vacía
    # en las 6 filas de las dos tablas; el respaldo previo de `respaldos.respaldar()` es la red.
    for tabla in ('hitos', 'personas'):
        cols = {c[1] for c in cur.execute(f"PRAGMA table_info({tabla})").fetchall()}
        if 'drive_url' in cols:
            cur.execute(f"ALTER TABLE {tabla} DROP COLUMN drive_url")


# No hay hook `seed`: una instalación nueva de historia.db arranca vacía y se carga desde
# la web o el chat. (crud.init_db igual protege el caso "DB vacía pero con respaldos".)


# Qué decir cuando un UNIQUE de la DB rechaza el guardado (si no, sale un 500 pelado).
ERROR_DUPLICADO = {
    'personas': 'Ya hay una persona cargada con ese nombre. Buscala en el listado y editala '
                'en vez de crear una segunda ficha.',
}

# Formato de `personas.fecha_actualizada`.
FORMATO_FECHA_REVISION = '%d/%m/%Y'


def clave_persona(nombre):
    """Identidad de una persona: sus palabras normalizadas y ordenadas alfabéticamente.

    El orden alfabético no es capricho: la misma persona entra como "Juan Pablo Crivari"
    desde el chat y como "CRIVARI JUAN PABLO" desde los horarios (así la deja
    `horarios.datos.limpiar_profesor`). Sin ordenar, serían dos fichas de la misma persona con
    los hilos M2M repartidos. El precio es que dos nombres que son la misma bolsa de
    palabras chocan contra el UNIQUE; se prefirió ese error visible al duplicado
    silencioso (ver dev-log/DECISIONS.md 2026-08-08).
    """
    limpio = ''.join(c if (c.isalnum() or c.isspace()) else ' ' for c in nombre)
    return ' '.join(sorted(texto.norm(limpio).split()))


def derivados(slug, valores):
    """Columnas que se calculan solas al guardar — no están en `campos` del formulario."""
    if slug != 'personas':
        return {}
    return {
        'nombre_norm': clave_persona(valores.get('nombre', '')),
        'fecha_actualizada': ahora().strftime(FORMATO_FECHA_REVISION),
    }


def secciones_detalle(slug, id, cur):
    """Relaciones a mostrar en la vista de detalle, en ambas direcciones."""
    secciones = []

    def agregar(titulo, slug_destino, sql):
        secciones.append({'titulo': titulo, 'slug': slug_destino,
                          'items': cur.execute(sql, (id,)).fetchall()})

    if slug == 'hitos':
        agregar('Personas involucradas', 'personas',
                "SELECT p.id, p.nombre FROM personas p JOIN persona_hitos r ON r.persona_id = p.id WHERE r.hito_id = ? ORDER BY p.nombre COLLATE NOCASE")
    elif slug == 'personas':
        agregar('Hitos en los que aparece', 'hitos',
                "SELECT h.id, h.titulo AS nombre FROM hitos h JOIN persona_hitos r ON r.hito_id = h.id WHERE r.persona_id = ? ORDER BY h.fecha DESC")
    return secciones


def init_db():
    """Lo hace el motor; queda como nombre estable para app.py e init_historia.py."""
    crud.init_db(sys.modules[__name__])


accesos.registrar_acceso(bp, PERMISO_LECTURA)
crud.registrar_rutas(bp, sys.modules[__name__])
