# agente.py
# Asistente conversacional con tool-calling.
# Blueprint independiente con su propio gate de sesión via session['gestion_ok'].
#
# AGNÓSTICO DEL LLM — Soporta:
#   - Anthropic (Claude) — env var: ANTHROPIC_API_KEY, AGENTE_MODEL (default: claude-haiku-4-5-20251001)
#   - Groq (Mixtral, Llama 2) — env var: GROQ_API_KEY, AGENTE_MODEL (default: mixtral-8x7b-32768)
#   - OpenAI (GPT-3.5, GPT-4) — env var: OPENAI_API_KEY, AGENTE_MODEL (default: gpt-3.5-turbo)
#   - Ollama (local, open-source) — env var: AGENTE_API_BASE (default: http://localhost:11434), AGENTE_MODEL (default: mistral)
#
# Config general:
#   - AGENTE_PROVIDER: 'anthropic' | 'groq' | 'openai' | 'ollama' (default: anthropic)
#   - AGENTE_API_KEY: para providers que la requieren (ignored para Ollama)
#   - AGENTE_API_BASE: para APIs custom (Ollama, self-hosted)
#   - AGENTE_MODEL: nombre del modelo (defaults por provider arriba)

import os
import json
import sqlite3
from datetime import datetime
from flask import Blueprint, request, session, jsonify, render_template, abort

import database
import gestion
from database import obtener_filas
from config import DIAS

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gestion.db')

bp = Blueprint('agente', __name__, url_prefix='/gestion/agente')

# ============================================================================
# Configuración del LLM (agnóstico del proveedor) — Lee en tiempo de request
# ============================================================================

_config_cache = None

def _get_config():
    """Lee la configuración del LLM en tiempo de request (lazy loading)."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    provider = os.environ.get('AGENTE_PROVIDER', 'anthropic').lower()
    model = os.environ.get('AGENTE_MODEL', '')
    api_key = os.environ.get('AGENTE_API_KEY', '')
    api_base = os.environ.get('AGENTE_API_BASE', '')

    # Defaults por proveedor
    if provider == 'anthropic':
        if not api_key:
            api_key = os.environ.get('ANTHROPIC_API_KEY', '')
        if not model:
            model = 'claude-haiku-4-5-20251001'
    elif provider == 'groq':
        if not api_key:
            api_key = os.environ.get('GROQ_API_KEY', '')
        if not model:
            model = 'mixtral-8x7b-32768'
    elif provider == 'ollama':
        if not api_base:
            api_base = 'http://localhost:11434'
        if not model:
            model = 'mistral'
    elif provider == 'openai':
        if not api_key:
            api_key = os.environ.get('OPENAI_API_KEY', '')
        if not model:
            model = 'gpt-3.5-turbo'

    _config_cache = {
        'provider': provider,
        'model': model,
        'api_key': api_key,
        'api_base': api_base
    }
    return _config_cache

# Variables globales por compatibilidad
def _get_agente_provider():
    return _get_config()['provider']

def _get_agente_model():
    return _get_config()['model']

def _get_agente_api_key():
    return _get_config()['api_key']

def _get_agente_api_base():
    return _get_config()['api_base']

# Gate de sesión: requiere haber iniciado sesión en /gestion
@bp.before_request
def _requiere_clave():
    if not session.get('gestion_ok'):
        abort(401)

SCHEMA = """
CREATE TABLE IF NOT EXISTS agente_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    tool TEXT NOT NULL,
    entrada TEXT NOT NULL,
    antes TEXT,
    resultado TEXT NOT NULL,
    ok INTEGER NOT NULL
);
"""

def conectar():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = conectar()
    cur = con.cursor()
    cur.executescript(SCHEMA)
    con.commit()
    con.close()

def _ahora():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# ============================================================================
# Funciones adaptadoras: traducen llamadas de tool al código ya existente
# ============================================================================

def _buscar_profesor(query):
    """Resolución difusa de nombre de profesor."""
    con = database.conectar()
    cur = con.cursor()
    cur.execute("SELECT DISTINCT profesor FROM clases WHERE profesor != '' ORDER BY profesor")
    profesores = [r[0] for r in cur.fetchall()]
    con.close()

    if not query:
        return [{'nombre': p} for p in profesores[:10]]

    # Usar la misma normalización que gestion.py
    from gestion import _norm, _puntaje_busqueda
    q_norm = _norm(query)
    puntuados = []
    for prof in profesores:
        puntaje = _puntaje_busqueda(q_norm, prof)
        if puntaje is not None:
            puntuados.append((puntaje, prof))
    puntuados.sort(reverse=True, key=lambda x: x[0])
    return [{'nombre': p} for _, p in puntuados[:5]]

def _horario_profesor_fmt(nombre):
    """Horario de profesor, formato interpretado."""
    filas = obtener_filas('profesor', nombre)

    if not filas:
        return {'profesor': nombre, 'clases': {}, 'nota': f'No se encontraron clases para {nombre}.'}

    # Agrupar por día
    por_dia = {}
    for f in filas:
        dia = f['dia']
        if dia not in por_dia:
            por_dia[dia] = []
        linea = f"{f['hora_inicio']}–{f['hora_fin']} · {f['materia']} · {f['curso']}°{f['division']} · {f['aula']}"
        if f.get('suplente_activo') == 1:
            linea += f" (suplente: {f['prof_suplente']})"
        por_dia[dia].append(linea)

    # Ordenar por día de la semana
    clases_ordenadas = {}
    for dia in DIAS:
        if dia in por_dia:
            clases_ordenadas[dia] = por_dia[dia]

    return {'profesor': nombre, 'clases': clases_ordenadas}

def _horario_curso_fmt(curso, division):
    """Horario de curso, formato interpretado."""
    con = database.conectar()
    cur = con.cursor()
    cur.execute("SELECT * FROM clases WHERE curso = ? AND division = ?", (curso, division))
    filas = [dict(row) for row in cur.fetchall()]
    con.close()

    if not filas:
        return {'curso': f'{curso}° {division}', 'clases': {}, 'nota': f'No se encontraron clases.'}

    por_dia = {}
    for f in filas:
        dia = f['dia']
        if dia not in por_dia:
            por_dia[dia] = []
        linea = f"{f['hora_inicio']}–{f['hora_fin']} · {f['materia']} · {f['profesor']} · {f['aula']}"
        por_dia[dia].append(linea)

    clases_ordenadas = {}
    for dia in DIAS:
        if dia in por_dia:
            clases_ordenadas[dia] = por_dia[dia]

    return {'curso': f'{curso}° {division}', 'clases': clases_ordenadas}

def _horario_aula_fmt(aula):
    """Horario de aula, formato interpretado."""
    con = database.conectar()
    cur = con.cursor()
    cur.execute("SELECT * FROM clases WHERE aula = ?", (aula,))
    filas = [dict(row) for row in cur.fetchall()]
    con.close()

    if not filas:
        return {'aula': aula, 'clases': {}, 'nota': f'No hay clases en {aula}.'}

    por_dia = {}
    for f in filas:
        dia = f['dia']
        if dia not in por_dia:
            por_dia[dia] = []
        linea = f"{f['hora_inicio']}–{f['hora_fin']} · {f['materia']} · {f['curso']}°{f['division']} · {f['profesor']}"
        por_dia[dia].append(linea)

    clases_ordenadas = {}
    for dia in DIAS:
        if dia in por_dia:
            clases_ordenadas[dia] = por_dia[dia]

    return {'aula': aula, 'clases': clases_ordenadas}

def _aulas_libres_fmt():
    """Aulas libres ahora."""
    return database.aulas_libres()

def _buscar_entidad_fmt(slug, query):
    """Búsqueda de entidad (recursos, conjuntos, actividades, proyectos)."""
    resultados = gestion.buscar_entidad_sin_request(slug, query)
    # Omitir campos vacíos para reducir ruido
    limpios = []
    for r in resultados:
        limpio = {'id': r.get('id'), 'nombre': r.get('nombre')}
        if r.get('estado'):
            limpio['estado'] = r['estado']
        if r.get('ubicacion'):
            limpio['ubicacion'] = r['ubicacion']
        if r.get('tipo'):
            limpio['tipo'] = r['tipo']
        limpios.append(limpio)
    return {'slug': slug, 'resultados': limpios}

def _detalle_entidad_fmt(slug, id):
    """Detalle completo de una entidad."""
    con = conectar()
    cur = con.cursor()
    cfg = gestion.ENTIDADES.get(slug)
    if not cfg:
        return {'error': f'Slug inválido: {slug}'}

    fila = cur.execute(f"SELECT * FROM {cfg['tabla']} WHERE id = ?", (id,)).fetchone()
    if not fila:
        con.close()
        return {'error': f'No encontrado: {slug} id={id}'}

    # Relaciones
    secciones = gestion._secciones_detalle(slug, id, cur)
    con.close()

    resultado = dict(fila)
    resultado['relaciones'] = {}
    for sec in secciones:
        resultado['relaciones'][sec['slug']] = [{'id': item['id'], 'nombre': item['nombre']} for item in sec['items']]

    return resultado

def _listar_prestamos_fmt(persona=None, solo_activos=True):
    """Lista de préstamos."""
    con = conectar()
    cur = con.cursor()
    sql = "SELECT * FROM prestamos"
    params = []
    if persona:
        sql += " WHERE persona LIKE ?"
        params = [f"%{persona}%"]
    sql += " ORDER BY fecha_salida DESC, id DESC"

    filas = cur.execute(sql, params).fetchall()

    activos = [f for f in filas if not f['fecha_devolucion']]
    devueltos = [f for f in filas if f['fecha_devolucion']]

    resumen = gestion._resumen_items(cur, [f['id'] for f in activos], solo_pendiente=True)
    resumen.update(gestion._resumen_items(cur, [f['id'] for f in devueltos]))

    con.close()

    resultado = []
    for f in (activos if solo_activos else filas):
        estado = 'EN PRÉSTAMO' if not f['fecha_devolucion'] else 'DEVUELTO'
        resultado.append({
            'id': f['id'],
            'persona': f['persona'],
            'destino': f['destino'],
            'fecha_salida': f['fecha_salida'],
            'estado': estado,
            'pendiente': resumen.get(f['id'], '')
        })

    return {'prestamos': resultado}

def _detalle_prestamo_fmt(prestamo_id):
    """Detalle de un préstamo con pendiente por ítem."""
    con = conectar()
    cur = con.cursor()

    fila = cur.execute("SELECT * FROM prestamos WHERE id = ?", (prestamo_id,)).fetchone()
    if not fila:
        con.close()
        return {'error': f'Préstamo no encontrado: id={prestamo_id}'}

    items_filas = cur.execute(
        "SELECT i.cantidad, i.cantidad_devuelta, i.recurso_id, r.nombre FROM prestamo_items i "
        "LEFT JOIN recursos r ON r.id = i.recurso_id WHERE i.prestamo_id = ? ORDER BY r.nombre COLLATE NOCASE",
        (prestamo_id,)
    ).fetchall()

    con.close()

    items = []
    pendiente_total = 0
    for it in items_filas:
        cant = gestion._int(it['cantidad'])
        devuelta = gestion._int(it['cantidad_devuelta'])
        pendiente = max(0, cant - devuelta)
        pendiente_total += pendiente
        items.append({
            'recurso_id': it['recurso_id'],
            'nombre': it['nombre'] or '(recurso eliminado)',
            'cantidad': cant,
            'devuelta': devuelta,
            'pendiente': pendiente
        })

    return {
        'id': prestamo_id,
        'persona': fila['persona'],
        'destino': fila['destino'],
        'notas': fila['notas'],
        'fecha_salida': fila['fecha_salida'],
        'fecha_devolucion': fila['fecha_devolucion'],
        'items': items,
        'pendiente_total': pendiente_total,
        'estado': 'EN PRÉSTAMO' if not fila['fecha_devolucion'] else 'DEVUELTO'
    }

# ============================================================================
# Ejecutores de tools de ESCRITURA (auditados en agente_log)
# ============================================================================

def _crear_entidad(slug, campos_dict):
    """Crear recurso/conjunto/actividad/proyecto."""
    if not campos_dict.get('nombre'):
        return {'ok': False, 'error': 'El nombre es obligatorio.'}

    con = conectar()
    id_nuevo = gestion.guardar_entidad_sin_request(slug, campos_dict, con=con)
    con.close()

    if id_nuevo:
        return {'ok': True, 'id': id_nuevo, 'mensaje': f'Creado {slug} id={id_nuevo}'}
    else:
        return {'ok': False, 'error': f'Error al crear {slug}'}

def _editar_entidad(slug, id, campos_dict):
    """Editar recurso/conjunto/actividad/proyecto."""
    con = conectar()

    # Snapshot antes
    antes = gestion.snapshot_entidad(slug, id, con=con)

    # Guardar
    id_result = gestion.guardar_entidad_sin_request(slug, campos_dict, id=id, con=con)
    con.close()

    if id_result:
        return {'ok': True, 'id': id_result, 'antes': antes, 'mensaje': f'Editado {slug} id={id}'}
    else:
        return {'ok': False, 'error': f'Error al editar {slug} id={id}'}

def _vincular_entidad(slug_origen, id_origen, slug_destino, id_destino):
    """Vincular dos entidades vía relación M2M."""
    cfg_origen = gestion.ENTIDADES.get(slug_origen)
    if not cfg_origen:
        return {'ok': False, 'error': f'Slug inválido: {slug_origen}'}

    # Encontrar la relación M2M
    rel_config = None
    for rel in cfg_origen.get('relaciones', []):
        if rel['slug_ajeno'] == slug_destino:
            rel_config = rel
            break

    if not rel_config:
        return {'ok': False, 'error': f'No hay relación entre {slug_origen} y {slug_destino}'}

    tabla = rel_config['tabla']
    col_propia = rel_config['col_propia']
    col_ajena = rel_config['col_ajena']

    con = conectar()
    resultado = gestion.agregar_relacion_m2m(tabla, col_propia, col_ajena, id_origen, id_destino, con=con)
    con.close()

    if resultado:
        return {'ok': True, 'mensaje': f'Vinculado {slug_origen}[{id_origen}] ← {slug_destino}[{id_destino}]'}
    else:
        return {'ok': False, 'error': 'Error al vincular'}

def _desvincular_entidad(slug_origen, id_origen, slug_destino, id_destino):
    """Desvincular dos entidades."""
    cfg_origen = gestion.ENTIDADES.get(slug_origen)
    if not cfg_origen:
        return {'ok': False, 'error': f'Slug inválido: {slug_origen}'}

    rel_config = None
    for rel in cfg_origen.get('relaciones', []):
        if rel['slug_ajeno'] == slug_destino:
            rel_config = rel
            break

    if not rel_config:
        return {'ok': False, 'error': f'No hay relación entre {slug_origen} y {slug_destino}'}

    tabla = rel_config['tabla']
    col_propia = rel_config['col_propia']
    col_ajena = rel_config['col_ajena']

    con = conectar()
    resultado = gestion.quitar_relacion_m2m(tabla, col_propia, col_ajena, id_origen, id_destino, con=con)
    con.close()

    if resultado:
        return {'ok': True, 'mensaje': f'Desvinculado {slug_origen}[{id_origen}] ↛ {slug_destino}[{id_destino}]'}
    else:
        return {'ok': False, 'error': 'Error al desvincular'}

def _crear_prestamo(persona, destino, notas, items_list):
    """Crear préstamo con ítems."""
    if not persona:
        return {'ok': False, 'error': 'Falta la persona que retira.'}

    if not items_list:
        return {'ok': False, 'error': 'Falta agregar ítems al préstamo.'}

    # Resolver nombres de recursos a ids
    con = conectar()
    cur = con.cursor()
    items_resueltos = []

    for item in items_list:
        recurso = item.get('recurso', '')
        cantidad = gestion._int(item.get('cantidad', 1)) or 1

        # Si es un número, asumir es id
        if recurso.isdigit():
            rid = int(recurso)
        else:
            # Buscar por nombre (match exacto o LIKE)
            cur.execute("SELECT id FROM recursos WHERE nombre LIKE ?", (f"%{recurso}%",))
            matches = [r[0] for r in cur.fetchall()]
            if len(matches) == 0:
                con.close()
                return {'ok': False, 'error': f'Recurso no encontrado: {recurso}'}
            elif len(matches) > 1:
                con.close()
                return {'ok': False, 'error': f'Recurso ambiguo: {recurso} (matches: {matches})'}
            rid = matches[0]

        # Validar stock
        stock = gestion._stock(cur, rid)
        if stock is None:
            con.close()
            return {'ok': False, 'error': f'Recurso no existe: id={rid}'}
        if stock > 0:
            cantidad = min(cantidad, stock)

        items_resueltos.append((rid, cantidad))

    # Crear préstamo
    try:
        cur.execute(
            "INSERT INTO prestamos (persona, destino, notas, fecha_salida, fecha_devolucion) VALUES (?,?,?,?,'')",
            (persona, destino or '', notas or '', gestion._ahora())
        )
        pid = cur.lastrowid

        for rid, cant in items_resueltos:
            cur.execute(
                "INSERT INTO prestamo_items (prestamo_id, recurso_id, cantidad, cantidad_devuelta) VALUES (?,?,?, '0')",
                (pid, rid, str(cant))
            )

        con.commit()
        con.close()

        return {'ok': True, 'prestamo_id': pid, 'mensaje': f'Préstamo creado id={pid}'}

    except Exception as e:
        con.rollback()
        con.close()
        return {'ok': False, 'error': f'Error al crear préstamo: {str(e)}'}

def _finalizar_prestamo(prestamo_id, items_list=None):
    """Devolver préstamo (todo o parcial)."""
    con = conectar()
    cur = con.cursor()

    if not items_list:
        # Devolver todo
        cur.execute("UPDATE prestamo_items SET cantidad_devuelta = cantidad WHERE prestamo_id = ?", (prestamo_id,))
        cur.execute(
            "UPDATE prestamos SET fecha_devolucion = ? WHERE id = ? AND fecha_devolucion = ''",
            (gestion._ahora(), prestamo_id)
        )
    else:
        # Devoluciones parciales
        for item in items_list:
            rid = gestion._int(item.get('recurso_id'))
            cantidad = gestion._int(item.get('cantidad', 0))

            if cantidad > 0:
                fila = cur.execute(
                    "SELECT cantidad, cantidad_devuelta FROM prestamo_items WHERE prestamo_id = ? AND recurso_id = ?",
                    (prestamo_id, rid)
                ).fetchone()

                if fila:
                    pendiente = max(0, gestion._int(fila['cantidad']) - gestion._int(fila['cantidad_devuelta']))
                    nuevo = gestion._int(fila['cantidad_devuelta']) + min(cantidad, pendiente)
                    cur.execute(
                        "UPDATE prestamo_items SET cantidad_devuelta = ? WHERE prestamo_id = ? AND recurso_id = ?",
                        (str(nuevo), prestamo_id, rid)
                    )

        gestion._recalcular_estado(cur, prestamo_id)

    con.commit()
    con.close()

    return {'ok': True, 'prestamo_id': prestamo_id, 'mensaje': f'Devuelto préstamo id={prestamo_id}'}

def _reabrir_prestamo(prestamo_id, items_list=None):
    """Deshacer una devolución."""
    con = conectar()
    cur = con.cursor()

    if not items_list:
        # Reabrir todo
        cur.execute("UPDATE prestamo_items SET cantidad_devuelta = '0' WHERE prestamo_id = ?", (prestamo_id,))
        cur.execute("UPDATE prestamos SET fecha_devolucion = '' WHERE id = ?", (prestamo_id,))
    else:
        # Reabrir ítems específicos
        for item in items_list:
            rid = gestion._int(item.get('recurso_id'))
            cur.execute(
                "UPDATE prestamo_items SET cantidad_devuelta = '0' WHERE prestamo_id = ? AND recurso_id = ?",
                (prestamo_id, rid)
            )
        gestion._recalcular_estado(cur, prestamo_id)

    con.commit()
    con.close()

    return {'ok': True, 'prestamo_id': prestamo_id, 'mensaje': f'Reabierto préstamo id={prestamo_id}'}

def _eliminar_entidad(slug, id):
    """Eliminar entidad (recurso/conjunto/actividad/proyecto)."""
    con = conectar()
    cur = con.cursor()

    # Snapshot antes (obligatorio)
    antes = gestion.snapshot_entidad(slug, id, con=con)
    if not antes:
        con.close()
        return {'ok': False, 'error': f'No encontrado: {slug} id={id}'}

    cfg = gestion.ENTIDADES.get(slug)
    if not cfg:
        con.close()
        return {'ok': False, 'error': f'Slug inválido: {slug}'}

    try:
        # Borrar relaciones M2M
        for tabla, columna in gestion.LIMPIEZA_M2M.get(slug, []):
            cur.execute(f"DELETE FROM {tabla} WHERE {columna} = ?", (id,))

        # Borrar la fila
        cur.execute(f"DELETE FROM {cfg['tabla']} WHERE id = ?", (id,))

        con.commit()
        con.close()

        return {'ok': True, 'mensaje': f'Eliminado {slug} id={id}', 'antes': antes}

    except Exception as e:
        con.rollback()
        con.close()
        return {'ok': False, 'error': f'Error al eliminar: {str(e)}', 'antes': antes}

def _eliminar_prestamo(prestamo_id):
    """Eliminar un préstamo (solo para cargas erróneas)."""
    con = conectar()
    cur = con.cursor()

    # Snapshot antes
    fila = cur.execute("SELECT * FROM prestamos WHERE id = ?", (prestamo_id,)).fetchone()
    if not fila:
        con.close()
        return {'ok': False, 'error': f'Préstamo no encontrado: id={prestamo_id}'}

    antes = {'fila': dict(fila)}

    try:
        cur.execute("DELETE FROM prestamos WHERE id = ?", (prestamo_id,))
        cur.execute("DELETE FROM prestamo_items WHERE prestamo_id = ?", (prestamo_id,))

        con.commit()
        con.close()

        return {'ok': True, 'mensaje': f'Eliminado préstamo id={prestamo_id}', 'antes': antes}

    except Exception as e:
        con.rollback()
        con.close()
        return {'ok': False, 'error': f'Error al eliminar: {str(e)}', 'antes': antes}

# ============================================================================
# Esquemas de tools para Claude
# ============================================================================

TOOLS_SCHEMA = [
    # LECTURA
    {
        'name': 'buscar_profesor',
        'description': 'Busca profesores por nombre, devuelve candidatos para desambiguar.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'query': {'type': 'string', 'description': 'Parte del nombre a buscar'}
            },
            'required': ['query']
        }
    },
    {
        'name': 'horario_profesor',
        'description': 'Obtiene el horario semanal completo de un profesor.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'nombre': {'type': 'string', 'description': 'Nombre exacto del profesor'}
            },
            'required': ['nombre']
        }
    },
    {
        'name': 'horario_curso',
        'description': 'Obtiene el horario semanal de un curso.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'curso': {'type': 'string', 'description': 'Número del curso (1-7)'},
                'division': {'type': 'string', 'description': 'División (A, B, C, 1, 2, etc.)'}
            },
            'required': ['curso', 'division']
        }
    },
    {
        'name': 'horario_aula',
        'description': 'Obtiene el horario semanal de un aula.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'aula': {'type': 'string', 'description': 'Código del aula (ej: 21, T3, P, GYM)'}
            },
            'required': ['aula']
        }
    },
    {
        'name': 'aulas_libres',
        'description': 'Obtiene las aulas libres en este momento, agrupadas por piso.',
        'input_schema': {
            'type': 'object',
            'properties': {}
        }
    },
    {
        'name': 'buscar_entidad',
        'description': 'Busca recursos, conjuntos, actividades o proyectos por nombre.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'slug': {'type': 'string', 'enum': ['recursos', 'conjuntos', 'actividades', 'proyectos']},
                'query': {'type': 'string', 'description': 'Parte del nombre a buscar'}
            },
            'required': ['slug', 'query']
        }
    },
    {
        'name': 'detalle_entidad',
        'description': 'Obtiene el detalle completo de un recurso, conjunto, actividad o proyecto.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'slug': {'type': 'string', 'enum': ['recursos', 'conjuntos', 'actividades', 'proyectos']},
                'id': {'type': 'integer', 'description': 'ID de la entidad'}
            },
            'required': ['slug', 'id']
        }
    },
    {
        'name': 'listar_prestamos',
        'description': 'Lista los préstamos activos (en curso).',
        'input_schema': {
            'type': 'object',
            'properties': {
                'persona': {'type': 'string', 'description': 'Filtrar por persona (opcional)'}
            }
        }
    },
    {
        'name': 'detalle_prestamo',
        'description': 'Obtiene el detalle de un préstamo con el estado de cada ítem.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'prestamo_id': {'type': 'integer', 'description': 'ID del préstamo'}
            },
            'required': ['prestamo_id']
        }
    },
    # ESCRITURA
    {
        'name': 'crear_entidad',
        'description': 'Crea un nuevo recurso, conjunto, actividad o proyecto.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'slug': {'type': 'string', 'enum': ['recursos', 'conjuntos', 'actividades', 'proyectos']},
                'nombre': {'type': 'string', 'description': 'Nombre (obligatorio)'},
                'tipo': {'type': 'string', 'description': 'Tipo (para recursos)'},
                'cantidad': {'type': 'integer', 'description': 'Cantidad (para recursos)'},
                'descripcion': {'type': 'string'},
                'ubicacion': {'type': 'string', 'description': 'Ubicación (para recursos)'},
                'estado': {'type': 'string', 'description': 'Estado (para recursos y proyectos)'},
                'utilidad': {'type': 'string', 'description': 'Utilidad (para recursos)'},
                'fecha_revision': {'type': 'string', 'description': 'Fecha de última revisión (para recursos)'},
                'uso_tipico': {'type': 'string', 'description': 'Uso típico (para conjuntos)'},
                'objetivo': {'type': 'string', 'description': 'Objetivo (para actividades)'},
                'duracion': {'type': 'string', 'description': 'Duración (para actividades)'},
                'curso': {'type': 'string', 'description': 'Curso (para actividades)'},
                'fecha': {'type': 'string', 'description': 'Fecha (para proyectos)'},
                'participantes': {'type': 'string', 'description': 'Participantes (para proyectos)'},
                'drive_url': {'type': 'string', 'description': 'URL de carpeta Drive'}
            },
            'required': ['slug', 'nombre']
        }
    },
    {
        'name': 'editar_entidad',
        'description': 'Edita un recurso, conjunto, actividad o proyecto existente.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'slug': {'type': 'string', 'enum': ['recursos', 'conjuntos', 'actividades', 'proyectos']},
                'id': {'type': 'integer'},
                'nombre': {'type': 'string'},
                'tipo': {'type': 'string'},
                'cantidad': {'type': 'integer'},
                'descripcion': {'type': 'string'},
                'ubicacion': {'type': 'string'},
                'estado': {'type': 'string'},
                'utilidad': {'type': 'string'},
                'fecha_revision': {'type': 'string'},
                'uso_tipico': {'type': 'string'},
                'objetivo': {'type': 'string'},
                'duracion': {'type': 'string'},
                'curso': {'type': 'string'},
                'fecha': {'type': 'string'},
                'participantes': {'type': 'string'},
                'drive_url': {'type': 'string'}
            },
            'required': ['slug', 'id']
        }
    },
    {
        'name': 'vincular_entidad',
        'description': 'Vincula dos entidades via relación M2M (ej: agregar recurso a conjunto).',
        'input_schema': {
            'type': 'object',
            'properties': {
                'slug_origen': {'type': 'string', 'description': 'Slug de la entidad que contiene'},
                'id_origen': {'type': 'integer'},
                'slug_destino': {'type': 'string', 'description': 'Slug de la entidad a vincular'},
                'id_destino': {'type': 'integer'}
            },
            'required': ['slug_origen', 'id_origen', 'slug_destino', 'id_destino']
        }
    },
    {
        'name': 'desvincular_entidad',
        'description': 'Desvincula dos entidades.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'slug_origen': {'type': 'string'},
                'id_origen': {'type': 'integer'},
                'slug_destino': {'type': 'string'},
                'id_destino': {'type': 'integer'}
            },
            'required': ['slug_origen', 'id_origen', 'slug_destino', 'id_destino']
        }
    },
    {
        'name': 'crear_prestamo',
        'description': 'Crea un nuevo préstamo de recursos.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'persona': {'type': 'string', 'description': 'Nombre de quien retira'},
                'destino': {'type': 'string', 'description': 'Destino (opcional)'},
                'notas': {'type': 'string', 'description': 'Notas (opcional)'},
                'items': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'recurso': {'type': 'string', 'description': 'Nombre o ID del recurso'},
                            'cantidad': {'type': 'integer'}
                        },
                        'required': ['recurso']
                    }
                }
            },
            'required': ['persona', 'items']
        }
    },
    {
        'name': 'finalizar_prestamo',
        'description': 'Registra la devolución de un préstamo (todo o parcial).',
        'input_schema': {
            'type': 'object',
            'properties': {
                'prestamo_id': {'type': 'integer'},
                'items': {
                    'type': 'array',
                    'description': 'Si no se especifica, devuelve todo. Si se especifica, devoluciones parciales por ítem.',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'recurso_id': {'type': 'integer'},
                            'cantidad': {'type': 'integer', 'description': 'Cantidad a devolver'}
                        },
                        'required': ['recurso_id', 'cantidad']
                    }
                }
            },
            'required': ['prestamo_id']
        }
    },
    {
        'name': 'reabrir_prestamo',
        'description': 'Deshace una devolución cargada por error.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'prestamo_id': {'type': 'integer'},
                'items': {
                    'type': 'array',
                    'description': 'Si no se especifica, reabre todo. Si se especifica, deshacer devoluciones específicas.',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'recurso_id': {'type': 'integer'}
                        },
                        'required': ['recurso_id']
                    }
                }
            },
            'required': ['prestamo_id']
        }
    },
    {
        'name': 'eliminar_entidad',
        'description': 'Elimina un recurso, conjunto, actividad o proyecto (requiere confirmación previa).',
        'input_schema': {
            'type': 'object',
            'properties': {
                'slug': {'type': 'string', 'enum': ['recursos', 'conjuntos', 'actividades', 'proyectos']},
                'id': {'type': 'integer'}
            },
            'required': ['slug', 'id']
        }
    },
    {
        'name': 'eliminar_prestamo',
        'description': 'Elimina un préstamo (solo para registros mal cargados, requiere confirmación previa).',
        'input_schema': {
            'type': 'object',
            'properties': {
                'prestamo_id': {'type': 'integer'}
            },
            'required': ['prestamo_id']
        }
    }
]

# ============================================================================
# Ejecutor de tools
# ============================================================================

def ejecutar_tool(tool_name, tool_input):
    """Ejecuta una tool y retorna el resultado + snapshot 'antes' si aplica."""
    lectura = tool_name in [
        'buscar_profesor', 'horario_profesor', 'horario_curso', 'horario_aula',
        'aulas_libres', 'buscar_entidad', 'detalle_entidad', 'listar_prestamos', 'detalle_prestamo'
    ]

    try:
        if tool_name == 'buscar_profesor':
            resultado = _buscar_profesor(tool_input.get('query', ''))
        elif tool_name == 'horario_profesor':
            resultado = _horario_profesor_fmt(tool_input.get('nombre', ''))
        elif tool_name == 'horario_curso':
            resultado = _horario_curso_fmt(tool_input.get('curso', ''), tool_input.get('division', ''))
        elif tool_name == 'horario_aula':
            resultado = _horario_aula_fmt(tool_input.get('aula', ''))
        elif tool_name == 'aulas_libres':
            resultado = _aulas_libres_fmt()
        elif tool_name == 'buscar_entidad':
            resultado = _buscar_entidad_fmt(tool_input.get('slug', ''), tool_input.get('query', ''))
        elif tool_name == 'detalle_entidad':
            resultado = _detalle_entidad_fmt(tool_input.get('slug', ''), tool_input.get('id', 0))
        elif tool_name == 'listar_prestamos':
            resultado = _listar_prestamos_fmt(tool_input.get('persona'))
        elif tool_name == 'detalle_prestamo':
            resultado = _detalle_prestamo_fmt(tool_input.get('prestamo_id', 0))
        elif tool_name == 'crear_entidad':
            resultado = _crear_entidad(tool_input.get('slug', ''), {k: v for k, v in tool_input.items() if k != 'slug'})
        elif tool_name == 'editar_entidad':
            resultado = _editar_entidad(tool_input.get('slug', ''), tool_input.get('id', 0), {k: v for k, v in tool_input.items() if k not in ['slug', 'id']})
        elif tool_name == 'vincular_entidad':
            resultado = _vincular_entidad(tool_input.get('slug_origen'), tool_input.get('id_origen'), tool_input.get('slug_destino'), tool_input.get('id_destino'))
        elif tool_name == 'desvincular_entidad':
            resultado = _desvincular_entidad(tool_input.get('slug_origen'), tool_input.get('id_origen'), tool_input.get('slug_destino'), tool_input.get('id_destino'))
        elif tool_name == 'crear_prestamo':
            resultado = _crear_prestamo(tool_input.get('persona', ''), tool_input.get('destino'), tool_input.get('notas'), tool_input.get('items', []))
        elif tool_name == 'finalizar_prestamo':
            resultado = _finalizar_prestamo(tool_input.get('prestamo_id', 0), tool_input.get('items'))
        elif tool_name == 'reabrir_prestamo':
            resultado = _reabrir_prestamo(tool_input.get('prestamo_id', 0), tool_input.get('items'))
        elif tool_name == 'eliminar_entidad':
            resultado = _eliminar_entidad(tool_input.get('slug', ''), tool_input.get('id', 0))
        elif tool_name == 'eliminar_prestamo':
            resultado = _eliminar_prestamo(tool_input.get('prestamo_id', 0))
        else:
            resultado = {'ok': False, 'error': f'Tool desconocida: {tool_name}'}

        # Auditar si es escritura
        if not lectura:
            con = conectar()
            cur = con.cursor()
            antes = resultado.pop('antes', None) if isinstance(resultado, dict) else None
            ok = resultado.get('ok', False) if isinstance(resultado, dict) else False

            cur.execute(
                "INSERT INTO agente_log (fecha, tool, entrada, antes, resultado, ok) VALUES (?,?,?,?,?,?)",
                (
                    _ahora(),
                    tool_name,
                    json.dumps(tool_input, default=str),
                    json.dumps(antes, default=str) if antes else None,
                    json.dumps(resultado, default=str),
                    1 if ok else 0
                )
            )
            con.commit()
            con.close()

        return resultado

    except Exception as e:
        resultado = {'ok': False, 'error': f'Excepción: {str(e)}'}
        if not lectura:
            con = conectar()
            cur = con.cursor()
            cur.execute(
                "INSERT INTO agente_log (fecha, tool, entrada, antes, resultado, ok) VALUES (?,?,?,?,?,?)",
                (_ahora(), tool_name, json.dumps(tool_input, default=str), None, json.dumps(resultado, default=str), 0)
            )
            con.commit()
            con.close()
        return resultado

# ============================================================================
# Loop de tool-calling agnóstico del LLM
# ============================================================================

def _crear_cliente_llm():
    """Crea un cliente para el LLM configurado."""
    config = _get_config()
    provider = config['provider']
    api_key = config['api_key']
    api_base = config['api_base']

    if provider == 'anthropic':
        from anthropic import Anthropic
        if not api_key:
            raise ValueError("Error: AGENTE_API_KEY o ANTHROPIC_API_KEY no está configurada.")
        return Anthropic(api_key=api_key)

    elif provider == 'groq':
        from groq import Groq
        if not api_key:
            raise ValueError("Error: AGENTE_API_KEY o GROQ_API_KEY no está configurada.")
        return Groq(api_key=api_key)

    elif provider == 'openai':
        from openai import OpenAI
        if not api_key:
            raise ValueError("Error: AGENTE_API_KEY o OPENAI_API_KEY no está configurada.")
        return OpenAI(api_key=api_key)

    elif provider == 'ollama':
        from openai import OpenAI  # Ollama es compatible con OpenAI API
        if not api_base:
            raise ValueError("Error: AGENTE_API_BASE no está configurada (default: http://localhost:11434).")
        return OpenAI(api_key='ollama', base_url=f"{api_base}/v1")

    else:
        raise ValueError(f"Proveedor LLM desconocido: {provider}")

def chat_with_tools(mensajes_usuario):
    """
    Llama al LLM configurado con la lista de tools, ejecuta lo que pida, repite hasta
    que el modelo da una respuesta final de texto. Retorna la respuesta final.
    Agnóstico del proveedor LLM (Anthropic, Groq, OpenAI, Ollama).
    """
    try:
        client = _crear_cliente_llm()
    except ValueError as e:
        return str(e)

    system_prompt = """Eres un asistente para el Sistema de Gestión de Conocimiento de la Escuela Técnica Emilio Mitre.
Tu tarea es ayudar al staff con:
- Consultas sobre horarios (profesores, cursos, aulas)
- Gestión del inventario (recursos, conjuntos, actividades, proyectos)
- Gestión de préstamos internos

CONTEXTO Y REFERENCIAS - MUY IMPORTANTE:
- Lee el HISTORIAL DE LA CONVERSACIÓN para mantener contexto. Si acaba de consultar sobre una persona/recurso, y el usuario hace una pregunta relativa, esa pregunta es SIEMPRE sobre la entidad anterior.
- Ejemplos:
  * Usuario: "¿Qué horarios tiene Andrea Alvarez?" (tu respuesta: muestra horarios)
  * Usuario: "¿En qué lugar?" → Se refiere a Andrea Alvarez. Extrae las aulas de la respuesta anterior.
  * Usuario: "¿Cuántos? ¿Stock?" → Se refiere al recurso/producto que acaba de consultar.
- Pronombres y demostrativos (ella, él, ese, esa, su, sus, su horario, ese recurso) → SIEMPRE son referencias a la entidad consultada.
- NUNCA pidas aclaración si el contexto está claro en el historial anterior.

REGLAS IMPORTANTES:
1. Para ELIMINAR: NUNCA ejecutes en el mismo turno. Describe qué vas a borrar y pide confirmación.
2. Para CREAR desde FOTO: Extrae campos, propón en texto, pide confirmación antes de ejecutar.
3. Busca difuso: si no hay match exacto, intenta buscar_profesor o buscar_entidad.
4. Lectura = sin auditoría. Escritura = con auditoría.

Sé conciso. Prioriza responder del historial antes de pedir aclaración."""

    # Copiar la lista para no mutar el historial original (que se persiste en sesión
    # como texto plano) con objetos complejos de la API (ToolUseBlock, etc.)
    messages = list(mensajes_usuario)

    # Loop: hasta que el modelo no quiera más tools
    max_iterations = 10
    iteration = 0

    while iteration < max_iterations:
        iteration += 1

        try:
            response = client.messages.create(
                model=_get_config()['model'],
                max_tokens=1024,
                system=system_prompt,
                tools=TOOLS_SCHEMA,
                messages=messages
            )
        except Exception as e:
            return f"Error llamando al LLM: {str(e)}"

        # Determinar stop reason (compatible con Anthropic, Groq, OpenAI, Ollama)
        stop_reason = getattr(response, 'stop_reason', None)
        if not stop_reason and hasattr(response, 'choices') and response.choices:
            # OpenAI/Groq/Ollama
            stop_reason = response.choices[0].finish_reason

        # Si el modelo dice "stop" o "end_turn", se acabó
        if stop_reason in ['end_turn', 'stop']:
            # Extraer el texto final
            texto_final = ''
            if hasattr(response, 'content'):
                # Anthropic
                for block in response.content:
                    if hasattr(block, 'text'):
                        texto_final = block.text
                        break
            elif hasattr(response, 'choices') and response.choices:
                # OpenAI/Groq/Ollama
                texto_final = response.choices[0].message.content or ''
            return texto_final or 'Sin respuesta'

        # Si quiere usar tools (Anthropic: 'tool_use')
        if stop_reason == 'tool_use':
            # Agregar la respuesta del asistente al historial
            if hasattr(response, 'content'):
                # Anthropic
                messages.append({'role': 'assistant', 'content': response.content})
            else:
                # OpenAI/Groq/Ollama
                messages.append({'role': 'assistant', 'content': response.choices[0].message.content})

            # Ejecutar cada tool que pidió
            tool_results = []

            if hasattr(response, 'content'):
                # Anthropic: response.content es una lista de bloques
                for block in response.content:
                    if hasattr(block, 'type') and block.type == 'tool_use':
                        tool_name = block.name
                        tool_input = block.input
                        tool_use_id = block.id

                        resultado = ejecutar_tool(tool_name, tool_input)

                        tool_results.append({
                            'type': 'tool_result',
                            'tool_use_id': tool_use_id,
                            'content': json.dumps(resultado, default=str, ensure_ascii=False)
                        })
            else:
                # OpenAI/Groq/Ollama: revisar tool_calls en la respuesta
                if hasattr(response.choices[0].message, 'tool_calls') and response.choices[0].message.tool_calls:
                    for tool_call in response.choices[0].message.tool_calls:
                        tool_name = tool_call.function.name
                        try:
                            tool_input = json.loads(tool_call.function.arguments)
                        except:
                            tool_input = tool_call.function.arguments

                        resultado = ejecutar_tool(tool_name, tool_input)

                        tool_results.append({
                            'type': 'tool_result',
                            'tool_use_id': tool_call.id,
                            'content': json.dumps(resultado, default=str, ensure_ascii=False)
                        })

            # Agregar los resultados al historial
            if tool_results:
                messages.append({'role': 'user', 'content': tool_results})

        else:
            # Otro stop_reason o llegamos al max de iteraciones
            texto_final = ''
            if hasattr(response, 'content'):
                # Anthropic
                for block in response.content:
                    if hasattr(block, 'text'):
                        texto_final = block.text
                        break
            elif hasattr(response, 'choices') and response.choices:
                # OpenAI/Groq/Ollama
                texto_final = response.choices[0].message.content or ''
            return texto_final or 'Sin respuesta'

    return 'Máximo de iteraciones alcanzado'

# ============================================================================
# Utilidades para mantener contexto
# ============================================================================

def _es_pregunta_relativa(pregunta):
    """Detecta si la pregunta es relativa (se refiere a algo mencionado antes)."""
    patrones = [
        'qué lugar', 'dónde', 'aula', 'piso',  # ubicación
        'cuántos', 'cantidad', 'stock',  # cantidad
        'cuándo', 'horario', 'clase',  # horario
        'estado', 'ubicación',  # estado del recurso
        'en qué', 'en dónde', 'en donde',
        'dónde tiene', 'ubicado', 'está en',
    ]
    p_lower = pregunta.lower()
    return any(patron in p_lower for patron in patrones) and len(pregunta.split()) <= 8

def _extraer_entidad_mencionada(respuesta_anterior, tipo='profesor'):
    """Extrae el nombre de la entidad de una respuesta anterior."""
    # Buscar patrones como "Horario de NOMBRE:" o "**NOMBRE**"
    import re
    # Patrón 1: "Horario de NOMBRE:" o "**Horario de NOMBRE:**"
    match = re.search(r'(?:de|del)\s+(?:\*{1,2})?(\w+(?:\s+\w+)?)\*{0,2}[:\s]', respuesta_anterior, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    # Patrón 2: "**NOMBRE**:"
    match = re.search(r'\*\*([A-Z\s]+)\*\*:', respuesta_anterior)
    if match:
        return match.group(1).strip()
    return None

# ============================================================================
# Endpoints Flask
# ============================================================================

@bp.route('/chat', methods=['POST'])
def chat():
    """Endpoint para el widget de chat. JSON con 'mensaje' y opcionalmente 'imagen' (base64).
    Mantiene historial + última entidad consultada para mejor contexto."""
    data = request.get_json() or {}
    mensaje_usuario = data.get('mensaje', '').strip()

    if not mensaje_usuario:
        return jsonify({'error': 'Mensaje vacío'}), 400

    # Recuperar historial de la sesión
    if 'agente_historial' not in session:
        session['agente_historial'] = []
    mensajes = session.get('agente_historial', [])[-10:]  # Últimos 10

    # Si el usuario hace una pregunta relativa sin especificar quién, inyectar referencia anterior
    entidad_actual = session.get('agente_entidad_actual')  # Último profesor/recurso consultado
    msg_procesado = mensaje_usuario

    if entidad_actual and _es_pregunta_relativa(mensaje_usuario):
        # Agregar contexto: "¿En qué lugar?" → "¿En qué lugar tiene clases [entidad]?"
        msg_procesado = f"{mensaje_usuario} (refiriéndote a: {entidad_actual})"

    # Construir el contenido del mensaje del usuario (con imagen si viene)
    contenido = [{'type': 'text', 'text': msg_procesado}]

    imagen_base64 = data.get('imagen')
    if imagen_base64:
        # Esperar formato: data:image/jpeg;base64,xxxxx o solo base64
        if imagen_base64.startswith('data:'):
            imagen_base64 = imagen_base64.split(',')[1]

        # Detectar tipo de imagen
        media_type = 'image/jpeg'  # default
        if imagen_base64.startswith('/9j/'):  # JPEG magic
            media_type = 'image/jpeg'
        elif imagen_base64.startswith('iVBO'):  # PNG magic
            media_type = 'image/png'

        contenido.append({
            'type': 'image',
            'source': {
                'type': 'base64',
                'media_type': media_type,
                'data': imagen_base64
            }
        })

    # Agregar mensaje del usuario al historial
    mensajes.append({'role': 'user', 'content': contenido})

    # Obtener respuesta del agente
    respuesta = chat_with_tools(mensajes)

    # Guardar respuesta en el historial (convertir respuesta a formato de mensaje)
    mensajes.append({'role': 'assistant', 'content': [{'type': 'text', 'text': respuesta}]})

    # Actualizar entidad actual si la respuesta menciona un profesor/recurso
    entidad = _extraer_entidad_mencionada(respuesta)
    if entidad:
        session['agente_entidad_actual'] = entidad

    # Guardar historial en sesión (max 20 mensajes = 10 turnos)
    session['agente_historial'] = mensajes[-20:]
    session.modified = True

    return jsonify({'respuesta': respuesta})

@bp.route('/log', methods=['GET'])
def agente_log():
    """Página de auditoría: últimas N entradas del agente_log."""
    con = conectar()
    cur = con.cursor()
    cur.execute("SELECT * FROM agente_log ORDER BY id DESC LIMIT 50")
    filas = [dict(row) for row in cur.fetchall()]
    con.close()

    return render_template('gestion/agente_log.html', filas=filas)
