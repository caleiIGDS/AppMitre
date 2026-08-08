# agente.py
# Asistente conversacional con tool-calling.
# Blueprint independiente con su propio gate de sesión via session['gestion_ok'].
#
# AGNÓSTICO DEL LLM — Proveedor por DEFECTO: DeepSeek (deepseek-v4-pro).
# Soporta:
#   - DeepSeek (DEFAULT) — env var: DEEPSEEK_API_KEY, AGENTE_MODEL (default: deepseek-v4-pro)
#   - Anthropic (Claude) — env var: ANTHROPIC_API_KEY, AGENTE_MODEL (default: claude-haiku-4-5-20251001)
#   - Groq (Mixtral, Llama 2) — env var: GROQ_API_KEY, AGENTE_MODEL (default: mixtral-8x7b-32768)
#   - OpenAI (GPT-3.5, GPT-4) — env var: OPENAI_API_KEY, AGENTE_MODEL (default: gpt-3.5-turbo)
#   - Ollama (local, open-source) — env var: AGENTE_API_BASE (default: http://localhost:11434), AGENTE_MODEL (default: mistral)
#
# Anthropic usa su propio loop de tool-calling; el resto comparte `_loop_openai`
# (API compatible con OpenAI). El default requiere el paquete `openai` instalado.
#
# OJO — DeepSeek NO tiene visión: con el provider por defecto, el alta de recursos
# desde foto no funciona. Para esa función hay que pasar a AGENTE_PROVIDER=anthropic.
#
# Config general:
#   - AGENTE_PROVIDER: 'deepseek' (default) | 'anthropic' | 'groq' | 'openai' | 'ollama'
#   - AGENTE_API_KEY: para providers que la requieren (ignored para Ollama)
#   - AGENTE_API_BASE: para APIs custom (Ollama, self-hosted)
#   - AGENTE_MODEL: nombre del modelo (defaults por provider arriba)

import os
import re
import json
import sqlite3
import difflib
import hashlib
import secrets
from datetime import datetime, timedelta
from flask import (Blueprint, request, session, jsonify, render_template, abort,
                   redirect, url_for)

import database
import gestion
from database import obtener_filas
from config import DIAS

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gestion.db')
HISTORIA_INDICE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'historia_indice.json')
HISTORIA_DIR_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'historias')

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

    provider = os.environ.get('AGENTE_PROVIDER', 'deepseek').lower()
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
    elif provider == 'deepseek':
        if not api_key:
            api_key = os.environ.get('DEEPSEEK_API_KEY', '')
        if not api_base:
            api_base = 'https://api.deepseek.com'
        if not model:
            # v4-pro, no el alias 'deepseek-chat': el alias puede cambiar de modelo destino
            # sin aviso y acá queremos el que se validó con la batería de 30 preguntas.
            model = 'deepseek-v4-pro'

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

# Endpoints que devuelven HTML. Sin sesión conviene mandarlos al login de /gestion
# (con `next` para volver acá), no un 401 pelado: entrar por link directo a
# /gestion/agente desde el celular es el caso normal, y ahí un 401 es un callejón.
# Los endpoints JSON sí siguen dando 401, que es lo que el fetch del chat sabe leer.
_ENDPOINTS_PAGINA = ('agente.chat_page', 'agente.agente_log')


# Gate de sesión: requiere haber iniciado sesión en /gestion
@bp.before_request
def _requiere_clave():
    if session.get('gestion_ok'):
        return
    if request.endpoint in _ENDPOINTS_PAGINA:
        return redirect(url_for('gestion.login', next=request.path))
    abort(401)


@bp.context_processor
def _contexto_base():
    """`base.html` espera escuela_nombre/logo/version, nav_entidades y carrito_count.
    Los inyecta el context_processor de `gestion.bp`, que NO corre para requests de
    este blueprint — por eso reusamos el mismo acá (si no, el header renderiza vacío).
    """
    return gestion._contexto_base()

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

CREATE TABLE IF NOT EXISTS agente_conversaciones (
    sid TEXT PRIMARY KEY,
    actualizado TEXT NOT NULL,
    historial TEXT NOT NULL,
    entidad_actual TEXT,
    fichas TEXT
);
"""

# La conversación vive acá y no en la sesión de Flask, que es una cookie firmada: los
# navegadores descartan cookies de más de ~4093 bytes, y con el historial adentro el peor
# caso medido daba ~3.5KB — al pasarse, el browser tira la cookie SIN AVISAR y el usuario
# se queda deslogueado y sin conversación. En la cookie queda solo `agente_sid`.
HISTORIAL_GUARDADO = 60    # mensajes que se conservan en la DB (30 turnos)
HISTORIAL_AL_MODELO = 24   # mensajes que se le mandan al LLM por turno (12 turnos)
FICHAS_MAX = 20            # altas sin confirmar que se recuerdan a la vez
CONVERSACION_DIAS = 30     # a los N días sin uso, la conversación se descarta

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
# Conversación del chat (server-side, en gestion.db)
# ============================================================================

def _sid():
    """Id de conversación del navegador actual. Es lo ÚNICO que va en la cookie."""
    sid = session.get('agente_sid')
    if not sid:
        sid = secrets.token_urlsafe(16)
        session['agente_sid'] = sid
        session.modified = True
    return sid


def _conv_cargar():
    """Historial, entidad de contexto y fichas pendientes de esta conversación.

    Devuelve siempre un dict completo: si no hay fila todavía (o el JSON quedó corrupto
    por una escritura a medias), arranca vacío en vez de reventar el chat.
    """
    con = conectar()
    fila = con.execute(
        "SELECT historial, entidad_actual, fichas FROM agente_conversaciones WHERE sid = ?",
        (_sid(),)
    ).fetchone()
    con.close()

    if not fila:
        return {'historial': [], 'entidad_actual': None, 'fichas': {}}
    try:
        historial = json.loads(fila['historial'] or '[]')
        fichas = json.loads(fila['fichas'] or '{}')
    except ValueError:
        historial, fichas = [], {}
    return {'historial': historial,
            'entidad_actual': fila['entidad_actual'],
            'fichas': fichas}


def _conv_guardar(historial, entidad_actual, fichas):
    """Persiste la conversación y limpia las que quedaron abandonadas."""
    con = conectar()
    con.execute(
        "INSERT INTO agente_conversaciones (sid, actualizado, historial, entidad_actual, fichas) "
        "VALUES (?,?,?,?,?) "
        "ON CONFLICT(sid) DO UPDATE SET actualizado=excluded.actualizado, "
        "historial=excluded.historial, entidad_actual=excluded.entidad_actual, "
        "fichas=excluded.fichas",
        (_sid(), _ahora(),
         json.dumps(historial[-HISTORIAL_GUARDADO:], default=str, ensure_ascii=False),
         entidad_actual,
         json.dumps(dict(list(fichas.items())[-FICHAS_MAX:]), default=str, ensure_ascii=False))
    )
    # Barrido de conversaciones viejas. Va acá y no en init_db() porque el server puede
    # estar meses sin reiniciar; la tabla tiene una fila por navegador, no pesa.
    con.execute("DELETE FROM agente_conversaciones WHERE actualizado < ?",
                ((datetime.now() - timedelta(days=CONVERSACION_DIAS)).strftime('%Y-%m-%d %H:%M:%S'),))
    con.commit()
    con.close()


def _sin_imagenes(mensajes):
    """Copia del historial con los bloques de imagen reemplazados por una nota.

    Una foto de etiqueta en base64 son varios MB: guardarla turno a turno engorda la fila
    y no aporta nada, porque el modelo ya la interpretó cuando llegó. (Con la cookie esto
    directamente rompía la sesión.)
    """
    limpios = []
    for msg in mensajes:
        contenido = msg.get('content')
        if not isinstance(contenido, list):
            limpios.append(msg)
            continue
        bloques = [b if not (isinstance(b, dict) and b.get('type') == 'image')
                   else {'type': 'text', 'text': '[el usuario adjuntó una imagen]'}
                   for b in contenido]
        limpios.append({'role': msg.get('role'), 'content': bloques})
    return limpios


def _conv_borrar():
    con = conectar()
    con.execute("DELETE FROM agente_conversaciones WHERE sid = ?", (_sid(),))
    con.commit()
    con.close()

# ============================================================================
# Funciones adaptadoras: traducen llamadas de tool al código ya existente
# ============================================================================

def _puntaje_nombre(q_norm, nombre_norm):
    """Similitud token a token, pensada para nombres de persona.

    `_puntaje_busqueda` de gestion.py compara la query entera contra el texto entero,
    así que "andrea alvares" puntuaba MÁS bajo contra "ALVAREZ ANDREA" (orden invertido)
    que contra "ALVARES LOURDES". Acá cada palabra de la query busca su mejor par en el
    nombre, con lo que el orden deja de importar y el typo se perdona.
    """
    q_tokens = [t for t in q_norm.split() if t]
    n_tokens = [t for t in nombre_norm.split() if t]
    if not q_tokens or not n_tokens:
        return 0.0
    total = sum(max(difflib.SequenceMatcher(None, qt, nt).ratio() for nt in n_tokens)
                for qt in q_tokens)
    return total / len(q_tokens)


def _buscar_profesor_scored(query):
    """Candidatos con su puntaje, ordenados de mejor a peor. Lista de (puntaje, nombre)."""
    con = database.conectar()
    cur = con.cursor()
    cur.execute("SELECT DISTINCT profesor FROM clases WHERE profesor != '' ORDER BY profesor")
    profesores = [r[0] for r in cur.fetchall()]
    con.close()

    if not query:
        return [(0.0, p) for p in profesores[:10]]

    # Usar la misma normalización que gestion.py
    from gestion import _norm, _puntaje_busqueda
    q_norm = _norm(query)
    puntuados = []
    for prof in profesores:
        # El de gestion.py premia substring (devuelve 1.0+); el token a token arregla
        # el orden invertido. Nos quedamos con el mejor de los dos.
        puntaje = max(_puntaje_nombre(q_norm, _norm(prof)),
                      _puntaje_busqueda(q_norm, prof) or 0.0)
        if puntaje >= 0.6:
            puntuados.append((puntaje, prof))
    puntuados.sort(reverse=True, key=lambda x: (x[0], x[1]))
    return puntuados[:5]


def _buscar_profesor(query):
    """Resolución difusa de nombre de profesor."""
    return [{'nombre': p} for _, p in _buscar_profesor_scored(query)]

def _personas_conocidas():
    """Nombres conocidos (profesores + personal no docente), para que el modelo pueda
    detectar nombres incompletos/mal escritos al registrar préstamos sin tener que
    buscarlos uno por uno con buscar_profesor."""
    con = database.conectar()
    cur = con.cursor()
    cur.execute("SELECT DISTINCT profesor FROM clases WHERE profesor != '' ORDER BY profesor")
    profesores = [r[0] for r in cur.fetchall()]
    con.close()
    personal = [p['nombre'] for p in database.obtener_lista_personal()]
    return sorted(set(profesores) | set(personal))

def _horario_profesor_fmt(nombre):
    """Horario de profesor, formato interpretado.

    `clases.profesor` exige match exacto normalizado, así que un typo ("andrea alvares")
    devolvía vacío y el modelo lo leía como "no tiene clases". La resolución difusa la
    hace el harness acá, no el modelo: si hay un único candidato parecido se usa ese
    (avisando cuál), y si hay varios se devuelven como sugerencias para desambiguar.
    """
    filas = obtener_filas('profesor', nombre)
    nombre_usado = nombre
    nota_fuzzy = None

    if not filas:
        scored = _buscar_profesor_scored(nombre)
        candidatos = [n for _, n in scored]
        # Auto-resolvemos solo si hay un ganador claro (único candidato, o el primero
        # le saca ventaja al segundo). Si están empatados —"gonzalez" matchea a varios
        # por igual— devolvemos la lista para que el modelo pregunte, no adivine.
        ganador_claro = len(scored) == 1 or (len(scored) > 1 and scored[0][0] - scored[1][0] >= 0.15)
        if scored and ganador_claro:
            nombre_usado = scored[0][1]
            filas = obtener_filas('profesor', nombre_usado)
            nota_fuzzy = f'No hay coincidencia exacta con "{nombre}"; se usó "{nombre_usado}".'
        elif candidatos:
            return {
                'profesor': nombre, 'clases': {}, 'sin_match_exacto': True,
                'sugerencias': candidatos,
                'nota': f'No existe un profesor llamado exactamente "{nombre}". Candidatos '
                        f'parecidos: {", ".join(candidatos)}. Preguntale al usuario cuál es '
                        f'(o reintentá con el nombre exacto). NO inventes el horario.'
            }
        else:
            return {'profesor': nombre, 'clases': {},
                    'nota': f'No existe ningún profesor llamado "{nombre}" ni parecido.'}

    if not filas:
        return {'profesor': nombre_usado, 'clases': {},
                'nota': f'{nombre_usado} no tiene clases cargadas.'}

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

    resultado = {'profesor': nombre_usado, 'clases': clases_ordenadas}
    if nota_fuzzy:
        resultado['nota'] = nota_fuzzy
    return resultado

def _horario_curso_fmt(curso, division):
    """Horario de curso, formato interpretado."""
    con = database.conectar()
    con.row_factory = sqlite3.Row  # database.conectar() no lo setea; sin esto dict(row) revienta
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
    con.row_factory = sqlite3.Row  # ídem _horario_curso_fmt
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

# ---------------------------------------------------------------------------
# Historia de la escuela (lore + guiños internos)
# ---------------------------------------------------------------------------

HISTORIA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'historia_escuela.json')
# Umbral del match difuso contra las claves. Más alto que el 0.68 del inventario a
# propósito: acá un falso positivo hace que el asistente conteste una anécdota que no
# tiene nada que ver con lo que preguntaron, y las claves son pocas y bien elegidas
# (no hay 91 nombres compitiendo), así que se puede exigir más.
HISTORIA_UMBRAL = 0.72

_historia_indice_cache = {'mtime': None, 'datos': []}


def _cargar_historia_indice():
    """Índice de historias, recargado si el archivo cambió.

    Cachea el índice pero no el contenido de textos. Así en turnos normales
    no se paga el costo de leer historias.
    """
    try:
        mtime = os.path.getmtime(HISTORIA_INDICE_PATH)
    except OSError:
        return []
    if _historia_indice_cache['mtime'] != mtime:
        try:
            with open(HISTORIA_INDICE_PATH, encoding='utf-8') as f:
                datos = json.load(f)
                indice = datos.get('indice', [])
                # Filtrar: solo entradas con claves e id válido
                _historia_indice_cache['datos'] = [
                    e for e in indice
                    if e.get('claves') and e.get('id') and not e.get('_prueba', False)
                ]
        except (ValueError, OSError):
            _historia_indice_cache['datos'] = []
        _historia_indice_cache['mtime'] = mtime
    return _historia_indice_cache['datos']


def _cargar_historia_completa(id_historia):
    """Lee el archivo individual de una historia completa.

    No se cachea porque se lee bajo demanda y es pequeño.
    Devuelve None si no existe o hay error.
    """
    try:
        path = os.path.join(HISTORIA_DIR_PATH, f'{id_historia}.json')
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (ValueError, OSError, FileNotFoundError):
        return None


def _historia_fmt(tema):
    """Busca historias por tema y devuelve modo + contenido.

    Modos de respuesta:
    - 'directo': 1 coincidencia exacta → devuelve historia completa + instrucción tono/estilo
    - 'listar': múltiples coincidencias o tema vago → devuelve índice sin textos
    - 'no_encontrado': ninguna coincidencia → devuelve instrucción de no inventar

    El texto sale del archivo, nunca se improvisa.
    """
    q = gestion._norm(tema or '')
    if not q:
        # Sin tema = listar todo el índice
        indice = _cargar_historia_indice()
        if not indice:
            return {
                'modo': 'no_encontrado',
                'nota': 'No hay historias guardadas todavía.'
            }
        return {
            'modo': 'listar',
            'historias': [
                {
                    'id': e['id'],
                    'titulo': e.get('titulo', ''),
                    'tipo': e.get('tipo', ''),
                    'resumen': e.get('resumen', ''),
                    'tono': e.get('tono', ''),
                    'estilo': e.get('estilo', '')
                }
                for e in indice
            ],
            'total': len(indice)
        }

    # Búsqueda por tema: mira claves, título, resumen, tono, estilo
    indice = _cargar_historia_indice()
    matches = []

    for entrada in indice:
        puntaje = 0.0

        # Busca en claves (exacto/substring)
        for clave in entrada.get('claves', []):
            c_norm = gestion._norm(clave)
            if not c_norm:
                continue
            if q in c_norm or c_norm in q:
                puntaje = max(puntaje, 1.0)
            elif len(q) >= 3:
                sim = difflib.SequenceMatcher(None, q, c_norm).ratio()
                puntaje = max(puntaje, sim)

        # También busca en tono y estilo (para queries como "excitante", "misterioso")
        for campo in ['tono', 'estilo', 'titulo', 'resumen']:
            valor = gestion._norm(entrada.get(campo, ''))
            if not valor:
                continue
            if q in valor or valor in q:
                puntaje = max(puntaje, 1.0)
            elif len(q) >= 3:
                sim = difflib.SequenceMatcher(None, q, valor).ratio()
                puntaje = max(puntaje, sim)

        if puntaje >= HISTORIA_UMBRAL:
            matches.append((entrada, puntaje))

    if not matches:
        return {
            'modo': 'no_encontrado',
            'nota': f'No hay historias sobre "{tema}". Decíselo al usuario en una frase. '
                    'NO inventes anécdotas ni datos: si no está acá, no existe.'
        }

    # Ordena por puntaje
    matches.sort(key=lambda x: x[1], reverse=True)

    # Si hay UNA coincidencia muy buena, devuelve directo
    if len(matches) == 1 or (matches[0][1] > 0.95 and matches[1][1] < 0.90 if len(matches) > 1 else True):
        mejor_entrada = matches[0][0]
        historia_completa = _cargar_historia_completa(mejor_entrada['id'])
        if not historia_completa:
            return {
                'modo': 'no_encontrado',
                'nota': f'Encontré la historia sobre "{tema}" pero no puedo cargar su contenido. Disculpá.'
            }

        # Construir instrucción de tono/estilo
        tono = mejor_entrada.get('tono', 'reflexivo')
        estilo = mejor_entrada.get('estilo', 'primera persona')
        instruccion_tono = (
            f'ERES EMILIO MITRE, el fantasma que vive en esta escuela desde que se construyó. '
            f'Recorres todos los pasillos, ves y escuchas todo. La escuela lleva tu nombre y tu '
            f'memoria es la de la escuela. Cuéntale esta historia EN PRIMERA PERSONA, como testigo '
            f'omnipotente que lo presenció, que vio todo lo que ocurrió, que guardó cada detalle. '
            f'Tono: {tono}. Estilo: {estilo}. '
            f'Mantén el misterio de ser un espíritu: el usuario no es el único en la escuela, vos también estás ahí. '
            f'Texto: solo lo que está en la historia, nada más. No inventes hechos ni nombres que no estén.'
        )

        return {
            'modo': 'directo',
            'historia': {
                'id': historia_completa['id'],
                'titulo': historia_completa.get('titulo', ''),
                'tipo': historia_completa.get('tipo', ''),
                'texto': historia_completa.get('texto', ''),
                'tono': tono,
                'estilo': estilo
            },
            'instruccion_tono': instruccion_tono
        }

    # Múltiples coincidencias: devuelve índice para que elija
    return {
        'modo': 'listar',
        'historias': [
            {
                'id': e['id'],
                'titulo': e.get('titulo', ''),
                'tipo': e.get('tipo', ''),
                'resumen': e.get('resumen', ''),
                'tono': e.get('tono', ''),
                'estilo': e.get('estilo', '')
            }
            for e, _ in matches[:5]  # top 5 matches
        ],
        'total': len(matches),
        'nota': 'Hay varias historias que podrían interesarte. ¿Cuál querés escuchar?'
    }

# Tope de resultados que se le mandan a Claude. La búsqueda difusa no acota: con una
# query sin match literal devuelve cualquier cosa que se parezca de escritura, y con
# query vacía devuelve la tabla entera. Más de esto es ruido que empuja al modelo a
# elegir alguno igual. El total real viaja aparte para que sepa que se recortó.
LIMITE_BUSQUEDA = 10
# Las descripciones del inventario son cortas (máx ~180 chars), así que cuando el match
# vino de ahí se manda entera en vez de recortar una ventana alrededor del término.
MAX_DESC_BUSQUEDA = 160
# Tope de `listar_todos`. Con 90 recursos el listado completo son ~500 tokens, menos de un
# tercio de lo que ya cuesta la lista de personas en cada turno, así que mandarlo entero es
# barato. Pero no escala para siempre: arriba de este número la tool se niega y pide afinar
# la búsqueda, para que el día que el inventario crezca degrade de forma predecible en vez
# de reventar el contexto en silencio.
LIMITE_LISTADO_COMPLETO = 400


def _clasificar_match(q_norm, nombre, descripcion):
    """Por qué esta fila entró en los resultados: substring en el nombre ('exacto'),
    substring en la descripción ('descripcion'), o solo parecido de escritura
    ('aproximado', con su similitud 0–1). `buscar_entidad_sin_request` ordena por
    puntaje pero lo descarta, así que sin esto Claude recibe un match literal y uno
    difuso de 0.6 con exactamente el mismo peso."""
    if not q_norm:
        return None, None
    if q_norm in gestion._norm(nombre or ''):
        return 'exacto', None
    if descripcion and q_norm in gestion._norm(descripcion):
        return 'descripcion', None
    # Acá ya sabemos que no hay substring en ninguno de los dos, así que
    # _puntaje_busqueda devuelve la similitud cruda (<1.0), no el 1.0+ratio.
    similitud = gestion._puntaje_busqueda(q_norm, nombre or '', descripcion or '')
    return 'aproximado', round(similitud, 2) if similitud else None


def _buscar_entidad_fmt(slug, query):
    """Búsqueda de entidad (recursos, conjuntos, actividades, proyectos)."""
    if slug not in gestion.ENTIDADES:
        # Sin esto un slug mal escrito devolvía 0 resultados y el agente concluía
        # "no hay nada cargado" en vez de reintentar con el slug correcto.
        return {'error': f'Slug inválido: {slug}. Válidos: {", ".join(gestion.ENTIDADES)}'}
    resultados = gestion.buscar_entidad_sin_request(slug, query)
    q_norm = gestion._norm(query or '')
    # Omitir campos vacíos para reducir ruido
    limpios = []
    for r in resultados[:LIMITE_BUSQUEDA]:
        limpio = {'id': r.get('id'), 'nombre': r.get('nombre')}
        if r.get('estado'):
            limpio['estado'] = r['estado']
        if r.get('ubicacion'):
            limpio['ubicacion'] = r['ubicacion']
        if r.get('tipo'):
            limpio['tipo'] = r['tipo']
        match, similitud = _clasificar_match(q_norm, r.get('nombre'), r.get('descripcion'))
        if match:
            limpio['match'] = match
            if similitud is not None:
                limpio['similitud'] = similitud
            if match == 'descripcion':
                # Si no, el nombre llega sin relación visible con lo buscado (buscar
                # "cable" trae "Faniot arduino" porque lo dice la descripción).
                desc = (r.get('descripcion') or '').strip()
                limpio['descripcion'] = (desc[:MAX_DESC_BUSQUEDA] + '…'
                                         if len(desc) > MAX_DESC_BUSQUEDA else desc)
        limpios.append(limpio)

    salida = {'slug': slug, 'query': query, 'total': len(resultados), 'resultados': limpios}
    if len(resultados) > LIMITE_BUSQUEDA:
        salida['truncado'] = (f'Se muestran los {LIMITE_BUSQUEDA} mejores de {len(resultados)}. '
                              'Si no está el que buscás, afiná la búsqueda.')
    # El aviso apunta al fallback en vez de dejar que el modelo concluya solo: la búsqueda
    # compara strings, no significados, así que "no encontré" NO es lo mismo que "no existe"
    # (buscar "tester" no encuentra el Multímetro; "taladro" no encuentra la Agujereadora).
    if not resultados:
        salida['aviso'] = (f'No hay {slug} cuyo nombre o descripción coincida con "{query}". '
                           f'OJO: eso no significa que no exista — puede estar cargado con otro '
                           f'nombre. Antes de afirmar que no está, llamá a listar_todos("{slug}") '
                           f'y fijate vos mismo en la lista completa.')
    elif q_norm and all(x.get('match') == 'aproximado' for x in limpios):
        salida['aviso'] = (f'Ninguno contiene "{query}" en el nombre ni en la descripción: '
                           'entraron solo por parecido de escritura, así que probablemente '
                           'NINGUNO sea lo que se busca. No ofrezcas el más parecido como si '
                           f'fuera el correcto. Llamá a listar_todos("{slug}") para ver la lista '
                           'completa y recién ahí decidí si está o no.')
    return salida


def _listar_todos_fmt(slug):
    """Todos los nombres de una entidad, para cuando la búsqueda por string no alcanza.

    Es el fallback de `buscar_entidad`: el modelo sabe que un "tester" es un multímetro y
    que la "Agujereadora de banco" es lo que casi todos llaman taladro, pero `_puntaje_busqueda`
    no — compara letras. Viendo la lista entera resuelve sinónimos, paráfrasis y jerga sin
    ningún diccionario que mantener, y sobre todo puede afirmar "no está" habiéndolo
    verificado, en vez de deducirlo de que la búsqueda no encontró nada.
    """
    if slug not in gestion.ENTIDADES:
        return {'error': f'Slug inválido: {slug}. Válidos: {", ".join(gestion.ENTIDADES)}'}

    con = conectar()
    tabla = gestion.ENTIDADES[slug]['tabla']
    filas = con.execute(
        f"SELECT id, nombre FROM {tabla} ORDER BY nombre COLLATE NOCASE").fetchall()
    con.close()

    # Las filas sin nombre no le dicen nada al modelo, pero esconderlas sin avisar haría
    # falsa la afirmación "estos son todos": van contadas aparte.
    items = [{'id': f['id'], 'nombre': f['nombre']} for f in filas if (f['nombre'] or '').strip()]
    sin_nombre = len(filas) - len(items)

    if len(items) > LIMITE_LISTADO_COMPLETO:
        return {'error': f'Hay {len(items)} {slug}: demasiados para listarlos completos. '
                         f'Usá buscar_entidad con un término más específico.',
                'total': len(items)}

    salida = {
        'slug': slug,
        'total': len(items),
        'items': items,
        'instruccion': (f'Estos son TODOS los {slug} cargados, la lista completa. Buscá entre '
                        'ellos el que corresponda a lo que pidió el usuario aunque lo haya '
                        'nombrado distinto (sinónimos, marcas, jerga del taller). Si ninguno '
                        'es lo que se pide, decí claramente que no está cargado: NO ofrezcas '
                        'el más parecido como si fuera el correcto. Para ver los datos de uno, '
                        'llamá a detalle_entidad con su id.'),
    }
    if sin_nombre:
        salida['sin_nombre'] = sin_nombre
    return salida


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
        # No todas las secciones son (id, nombre): la de "En préstamo" trae
        # (persona, pendiente) y sin este chequeo reventaba con KeyError 'id'
        # justo cuando el recurso estaba prestado — el caso más útil.
        clave = sec.get('slug') or sec.get('titulo') or 'otros'
        items = []
        for item in sec['items']:
            d = dict(item)
            if 'id' in d and 'nombre' in d:
                items.append({'id': d['id'], 'nombre': d['nombre']})
            else:
                items.append(d)
        resultado['relaciones'][clave] = items

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

# ---------------------------------------------------------------------------
# Alta en dos pasos: ficha → confirmación del usuario → escritura
# ---------------------------------------------------------------------------

# Campos que el asistente REDACTA a partir de lo que contó el usuario, en vez de
# pedirlos literalmente ("¿qué descripción le pongo?"). Se marcan en la ficha para que
# el usuario sepa que ese texto lo escribió el asistente y lo lea con esa expectativa.
CAMPOS_REDACTADOS = ('nombre', 'tipo', 'descripcion')


def _campos_validos(slug):
    """Nombres de campo de la entidad, en el orden del formulario de /gestion."""
    cfg = gestion.ENTIDADES.get(slug) or {}
    return [c['nombre'] for c in cfg.get('campos', [])]


def _normalizar_borrador(slug, campos_dict):
    """Deja solo los campos que existen en el slug, como texto y sin espacios de más.

    Normalizar acá y no al guardar es lo que hace comparable el token: la ficha que ve
    el usuario y la fila que se escribe salen del mismo dict.

    Además completa la fecha de revisión de los recursos con la de hoy si no vino: dar de
    alta un recurso ES un control de inventario. Se pone acá, antes de calcular el token,
    para que la fecha aparezca en la ficha y el usuario la vea (y la pueda cambiar) — si
    se agregara al guardar, se estaría escribiendo un campo que nadie aprobó. Va del lado
    del código y no como "acordate de poner la fecha" en el prompt, que es la clase de
    regla que el modelo cumple a veces.
    """
    borrador = {}
    for nombre in _campos_validos(slug):
        valor = campos_dict.get(nombre)
        if valor is None:
            continue
        valor = str(valor).strip()
        if valor:
            borrador[nombre] = valor

    if slug == 'recursos' and not borrador.get('fecha_revision'):
        borrador['fecha_revision'] = datetime.now().strftime(gestion.FORMATO_FECHA_REVISION)
    return borrador


def _token_ficha(slug, borrador):
    """Huella del contenido exacto de la ficha.

    Es lo que hace que la confirmación no se pueda despegar de lo que el usuario leyó:
    el token sale del contenido, así que si el modelo confirma con aunque sea un campo
    distinto del que mostró, el token no coincide y la tool vuelve a la ficha. Al ser
    derivado no hay que guardar estado en sesión ni en la DB.
    """
    crudo = slug + '|' + json.dumps(borrador, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(crudo.encode('utf-8')).hexdigest()[:10]


def _tipos_en_uso():
    """Categorías ya cargadas en el inventario.

    Van en la ficha para que el asistente reuse una existente en vez de inventar una
    nueva en cada alta: `tipo` es texto libre y sin esto se llena de sinónimos
    ("Herramienta"/"Herramientas"/"Herramienta manual") que no sirven para agrupar.
    """
    con = conectar()
    filas = con.execute(
        "SELECT DISTINCT tipo FROM recursos WHERE tipo IS NOT NULL AND TRIM(tipo) <> '' "
        "ORDER BY tipo COLLATE NOCASE"
    ).fetchall()
    con.close()
    return [f[0] for f in filas]


def _ficha_confirmacion(slug, borrador, token, contexto_turno):
    """Paso 1 del alta: la ficha para mostrarle al usuario. No escribe nada."""
    cfg = gestion.ENTIDADES.get(slug) or {}
    etiquetas = {c['nombre']: c.get('label', c['nombre']) for c in cfg.get('campos', [])}
    nombres = _campos_validos(slug)

    ficha, vacios = {}, []
    for nombre in nombres:
        label = etiquetas.get(nombre, nombre)
        ficha[label] = borrador.get(nombre, '')
        if not borrador.get(nombre):
            vacios.append(label)

    # Se anota la ficha generada en este turno: sirve para rechazar una confirmación que
    # llegue sin que el usuario haya podido verla (ver _crear_entidad) y para que el
    # endpoint de chat le pase al front el botón de confirmar.
    contexto_turno.setdefault('fichas_mostradas', {})[token] = {'slug': slug, 'campos': borrador}
    contexto_turno['ultima_ficha'] = {'token': token, 'slug': slug,
                                      'nombre': borrador.get('nombre', '')}

    resultado = {
        'ok': False,
        'requiere_confirmacion': True,
        'ficha': ficha,
        'campos_vacios': vacios,
        'redactados_por_vos': [etiquetas.get(n, n) for n in CAMPOS_REDACTADOS if n in nombres],
        'instruccion': (
            'NO se creó nada todavía. Mostrale al usuario la ficha campo por campo, tal cual '
            'va a quedar guardada. Abajo, si hay campos vacíos o datos que valdría la pena '
            'sumar, hacele 1 a 3 preguntas cortas y concretas (medida, marca y modelo, dónde '
            'se guarda, cuántos hay). Aclarale que son opcionales: si no las contesta se '
            'guarda igual. NO le pidas que escriba "sí" ni "confirmo": debajo de tu mensaje '
            'le aparece un botón para guardar. Cerrá diciéndole que si está bien, lo confirme '
            'con ese botón. Si pide cambios, volvé a llamar a crear_entidad con los campos '
            'corregidos y te devuelve la ficha nueva (con su botón).'
        ),
    }
    if slug == 'recursos':
        resultado['tipos_en_uso'] = _tipos_en_uso()
    return resultado


def _crear_entidad(slug, campos_dict, contexto_turno=None):
    """Alta de recurso/conjunto/actividad/proyecto, en DOS PASOS.

    Primera llamada con un juego de campos: no toca la base, devuelve la ficha para que el
    asistente se la muestre al usuario. Segunda llamada con LOS MISMOS campos (ya en otro
    turno, después del OK): escribe.

    Lo que hace que la confirmación signifique algo es que la ficha se identifica por un
    hash de su CONTENIDO: si entre la ficha y el alta cambia aunque sea un campo, el hash
    es otro y vuelve a pedir confirmación — no se puede guardar algo distinto de lo que el
    usuario leyó, y "cambiame la ubicación" cae solo en el paso de revisión.

    Los hashes ya mostrados viajan en `contexto_turno['fichas_previas']`, que el endpoint
    de chat carga de la sesión y vuelve a guardar. Tiene que ser la SESIÓN y no el turno:
    los resultados de tools no se persisten en el historial, así que cuando el usuario
    contesta "dale" el modelo ya no tiene a la vista nada de la ficha anterior.

    Es un guard de código y no una regla del system prompt a propósito: las reglas del
    prompt este agente a veces las cumple y a veces no, y acá se escribe en el inventario
    real de la escuela.
    """
    if contexto_turno is None:
        contexto_turno = {}

    if slug not in gestion.ENTIDADES:
        return {'ok': False, 'error': f'Slug desconocido: {slug}. Usá recursos, conjuntos, actividades o proyectos.'}
    if not campos_dict.get('nombre'):
        return {'ok': False, 'error': 'El nombre es obligatorio.'}

    borrador = _normalizar_borrador(slug, campos_dict)
    token = _token_ficha(slug, borrador)
    previas = contexto_turno.setdefault('fichas_previas', {})

    # Si esta ficha exacta no se mostró en un turno anterior, el usuario no la aprobó.
    # (Una mostrada en ESTE turno tampoco cuenta: hasta que el loop no termina, el usuario
    # no vio una sola palabra — por eso se anotan aparte, en `fichas_mostradas`.)
    if token not in previas:
        return _ficha_confirmacion(slug, borrador, token, contexto_turno)

    # Se consume: si el asistente vuelve a llamar con los mismos campos, es un alta nueva
    # y arranca otra vez por la ficha, en vez de duplicar el recurso en silencio.
    previas.pop(token, None)

    con = conectar()
    id_nuevo = gestion.guardar_entidad_sin_request(slug, borrador, con=con)
    con.close()

    if id_nuevo:
        return {'ok': True, 'id': id_nuevo, 'mensaje': f'Creado {slug} id={id_nuevo}'}
    return {'ok': False, 'error': f'Error al crear {slug}'}

def _editar_entidad(slug, id, campos_dict):
    """Editar recurso/conjunto/actividad/proyecto (edición PARCIAL).

    `guardar_entidad_sin_request` hace UPDATE de TODAS las columnas usando
    `campos_dict.get(n, '')`, porque nació del form de /gestion, que siempre postea el
    registro entero. Por el chat no es así: el usuario dice "ponele estado En reparación"
    y el modelo manda un solo campo — con lo cual descripción, ubicación, tipo y cantidad
    se guardarían vacíos. Por eso acá partimos de la fila actual y aplicamos encima solo
    lo que vino. Se arregla del lado del código y no pidiéndole al modelo que mande todos
    los campos, que es justo el tipo de regla que a veces cumple y a veces no.
    """
    con = conectar()

    # Snapshot antes
    antes = gestion.snapshot_entidad(slug, id, con=con)

    if not antes or not antes.get('fila'):
        con.close()
        return {'ok': False,
                'error': f'No existe {slug} id={id}. Buscá el id correcto con buscar_entidad.'}

    campos_merge = {k: v for k, v in dict(antes['fila']).items() if k != 'id'}
    for clave, valor in (campos_dict or {}).items():
        if valor is not None:
            campos_merge[clave] = valor

    # Guardar
    id_result = gestion.guardar_entidad_sin_request(slug, campos_merge, id=id, con=con)
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

def _resolver_recurso(cur, texto):
    """Busca recursos por nombre tolerando acentos, mayúsculas y typos.

    El `LIKE '%x%'` crudo fallaba con "medidor de energía solar" porque en la base
    figura "Medidor de energia solar" (sin tilde) — el préstamo no se creaba y el
    modelo se quedaba sin saber por qué. Devuelve [(id, nombre)].
    """
    from gestion import _norm
    filas = cur.execute("SELECT id, nombre FROM recursos").fetchall()
    q = _norm(texto)

    exactos = [(f[0], f[1]) for f in filas if _norm(f[1]) == q]
    if exactos:
        return exactos

    subs = [(f[0], f[1]) for f in filas if q in _norm(f[1]) or _norm(f[1]) in q]
    if subs:
        return subs

    difusos = []
    for f in filas:
        p = _puntaje_nombre(q, _norm(f[1]))
        if p >= 0.75:
            difusos.append((p, f[0], f[1]))
    difusos.sort(reverse=True)
    return [(i, n) for _, i, n in difusos[:5]]


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
            matches = _resolver_recurso(cur, recurso)
            if len(matches) == 0:
                con.close()
                return {'ok': False, 'error': f'Recurso no encontrado: "{recurso}". No se creó el préstamo.'}
            elif len(matches) > 1:
                opciones = [{'id': r[0], 'nombre': r[1]} for r in matches]
                con.close()
                return {
                    'ok': False,
                    'error': f'"{recurso}" es ambiguo, hay {len(matches)} recursos que coinciden. '
                             f'Preguntale al usuario cuál es antes de reintentar.',
                    'opciones': opciones
                }
            rid = matches[0][0]

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
        no_encontrados = []
        aplicados = []
        for item in items_list:
            rid = gestion._int(item.get('recurso_id'))
            cantidad = gestion._int(item.get('cantidad', 0))

            fila = cur.execute(
                "SELECT cantidad, cantidad_devuelta FROM prestamo_items WHERE prestamo_id = ? AND recurso_id = ?",
                (prestamo_id, rid)
            ).fetchone()

            if not fila:
                no_encontrados.append(rid)
                continue

            if cantidad > 0:
                pendiente = max(0, gestion._int(fila['cantidad']) - gestion._int(fila['cantidad_devuelta']))
                nuevo = gestion._int(fila['cantidad_devuelta']) + min(cantidad, pendiente)
                cur.execute(
                    "UPDATE prestamo_items SET cantidad_devuelta = ? WHERE prestamo_id = ? AND recurso_id = ?",
                    (str(nuevo), prestamo_id, rid)
                )
                aplicados.append(rid)

        gestion._recalcular_estado(cur, prestamo_id)
        con.commit()
        con.close()

        if no_encontrados:
            return {
                'ok': False,
                'error': f'recurso_id {no_encontrados} no pertenece(n) al préstamo {prestamo_id}. '
                         f'No se les aplicó ninguna devolución (revisá con detalle_prestamo). '
                         f'Ítems sí aplicados: {aplicados}.',
                'prestamo_id': prestamo_id,
                'aplicados': aplicados
            }

        return {'ok': True, 'prestamo_id': prestamo_id, 'mensaje': f'Devuelto préstamo id={prestamo_id}', 'aplicados': aplicados}

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
        no_encontrados = []
        for item in items_list:
            rid = gestion._int(item.get('recurso_id'))
            existe = cur.execute(
                "SELECT 1 FROM prestamo_items WHERE prestamo_id = ? AND recurso_id = ?",
                (prestamo_id, rid)
            ).fetchone()
            if not existe:
                no_encontrados.append(rid)
                continue
            cur.execute(
                "UPDATE prestamo_items SET cantidad_devuelta = '0' WHERE prestamo_id = ? AND recurso_id = ?",
                (prestamo_id, rid)
            )
        gestion._recalcular_estado(cur, prestamo_id)
        con.commit()
        con.close()

        if no_encontrados:
            return {
                'ok': False,
                'error': f'recurso_id {no_encontrados} no pertenece(n) al préstamo {prestamo_id}. No se reabrió nada para esos ítems.',
                'prestamo_id': prestamo_id
            }

        return {'ok': True, 'prestamo_id': prestamo_id, 'mensaje': f'Reabierto préstamo id={prestamo_id}'}

    con.commit()
    con.close()

    return {'ok': True, 'prestamo_id': prestamo_id, 'mensaje': f'Reabierto préstamo id={prestamo_id}'}

def _eliminar_entidad(slug, id, nombre_confirmacion=None):
    """Eliminar entidad (recurso/conjunto/actividad/proyecto).

    `nombre_confirmacion` es obligatorio y debe coincidir con el nombre real de la fila:
    es una traba de CÓDIGO, no de prompt. Sin esto el modelo podía alucinar un id
    (llegó a borrar 'Panel solar 100W' id=1 creyendo que borraba un recurso de prueba
    que nunca existió) — ver DECISIONS 2026-08-04.
    """
    con = conectar()
    cur = con.cursor()

    # Snapshot antes (obligatorio)
    antes = gestion.snapshot_entidad(slug, id, con=con)
    if not antes:
        con.close()
        return {'ok': False, 'error': f'No encontrado: {slug} id={id}. No se borró nada.'}

    cfg = gestion.ENTIDADES.get(slug)
    if not cfg:
        con.close()
        return {'ok': False, 'error': f'Slug inválido: {slug}'}

    nombre_real = antes['fila'].get('nombre', '')
    if not nombre_confirmacion:
        con.close()
        return {'ok': False, 'error':
                f'Falta nombre_confirmacion. {slug} id={id} se llama "{nombre_real}". '
                f'Confirmá con el usuario que es eso lo que quiere borrar y reintentá '
                f'pasando nombre_confirmacion="{nombre_real}". No se borró nada.'}

    if gestion._norm(nombre_confirmacion) != gestion._norm(nombre_real):
        con.close()
        return {'ok': False, 'error':
                f'NO COINCIDE: pediste borrar "{nombre_confirmacion}" pero {slug} id={id} '
                f'es "{nombre_real}". No se borró nada. Buscá el id correcto con '
                f'buscar_entidad antes de reintentar.'}

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

def _eliminar_prestamo(prestamo_id, persona_confirmacion=None):
    """Eliminar un préstamo (solo para cargas erróneas).

    `persona_confirmacion` obligatorio y verificado contra la fila real, misma traba de
    código que `_eliminar_entidad`.
    """
    con = conectar()
    cur = con.cursor()

    # Snapshot antes (incluye los ítems, que también se borran)
    fila = cur.execute("SELECT * FROM prestamos WHERE id = ?", (prestamo_id,)).fetchone()
    if not fila:
        con.close()
        return {'ok': False, 'error': f'Préstamo no encontrado: id={prestamo_id}. No se borró nada.'}

    persona_real = fila['persona'] or ''
    if not persona_confirmacion:
        con.close()
        return {'ok': False, 'error':
                f'Falta persona_confirmacion. El préstamo {prestamo_id} es de "{persona_real}". '
                f'Confirmá con el usuario y reintentá pasando persona_confirmacion="{persona_real}". '
                f'No se borró nada.'}

    if gestion._norm(persona_confirmacion) != gestion._norm(persona_real):
        con.close()
        return {'ok': False, 'error':
                f'NO COINCIDE: pediste borrar el préstamo de "{persona_confirmacion}" pero el '
                f'id={prestamo_id} es de "{persona_real}". No se borró nada.'}

    items_antes = [dict(r) for r in cur.execute(
        "SELECT * FROM prestamo_items WHERE prestamo_id = ?", (prestamo_id,)).fetchall()]
    antes = {'fila': dict(fila), 'items': items_antes}

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
        'description': ('Busca docentes por nombre aproximado y devuelve los candidatos que más se '
                        'parecen, ordenados por puntaje. Tolera errores de tipeo, falta de tildes y '
                        'nombre invertido ("andrea alvares" encuentra "ALVAREZ ANDREA"). Usala cuando '
                        'el usuario da un nombre incompleto o dudoso y querés ofrecerle opciones. Si '
                        'ya tenés el nombre, no hace falta: horario_profesor también busca difuso.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'query': {'type': 'string', 'description': 'Parte del nombre a buscar, como lo dijo el usuario'}
            },
            'required': ['query']
        }
    },
    {
        'name': 'horario_profesor',
        'description': ('ÚNICA fuente del horario de un docente: nunca respondas un horario de memoria '
                        'ni por deducción, ni siquiera para completar uno que ya mostraste. Devuelve la '
                        'semana completa con día, hora, materia, curso y aula. Si el nombre no es exacto '
                        'busca difuso y puede responder de tres formas: (a) el horario más `nota_fuzzy` '
                        'si hubo un ganador claro — avisale al usuario a quién resolviste; (b) '
                        '`sugerencias` con varios candidatos parecidos, y ahí tenés que preguntar cuál '
                        'es en vez de elegir; (c) `nota` diciendo que no encontró a nadie. Que devuelva '
                        'una sola clase, o ninguna, es un resultado válido y frecuente: informalo tal '
                        'cual, no lo rellenes.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'nombre': {'type': 'string', 'description': 'Nombre del docente. Ideal el exacto de la base, pero tolera aproximados'}
            },
            'required': ['nombre']
        }
    },
    {
        'name': 'horario_curso',
        'description': ('Horario semanal de un curso (todas las materias que recibe esa división). '
                        'El curso y la división van SEPARADOS: "3° B" es curso="3", division="B". '
                        'Es la única fuente del horario de un curso, no lo deduzcas.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'curso': {'type': 'string', 'description': 'Solo el número de año, "1" a "7". Sin el símbolo de grado'},
                'division': {'type': 'string', 'description': 'Solo la división: "A", "B", "C", o un número como "1", "8"'}
            },
            'required': ['curso', 'division']
        }
    },
    {
        'name': 'horario_aula',
        'description': ('Horario semanal de un aula o taller: qué se dicta ahí, cuándo, con qué curso y '
                        'qué docente. Sirve para "¿quién da clase en el aula 21 los martes a las 10?" — '
                        'traé la semana y filtrá vos el día y la hora. Única fuente, no la deduzcas.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'aula': {'type': 'string', 'description': 'Código tal como está en la base: "21", "T3", "PATIO", "GYM". Los talleres van sin espacio ("T2", no "Taller 2")'}
            },
            'required': ['aula']
        }
    },
    {
        'name': 'aulas_libres',
        'description': ('Aulas sin clase asignada AHORA MISMO, agrupadas por piso. No recibe parámetros: '
                        'usa siempre el día y la hora actuales del servidor, así que no sirve para '
                        'consultar otro momento. Si te preguntan por otro día u horario, usá '
                        'horario_aula sobre las aulas que interesen.'),
        'input_schema': {
            'type': 'object',
            'properties': {}
        }
    },
    {
        'name': 'buscar_entidad',
        'description': ('Busca en el inventario por nombre aproximado y devuelve id + nombre + datos '
                        'básicos. Es la forma correcta de conseguir un id: NUNCA inventes uno ni lo '
                        'recuerdes de otra conversación. Los cuatro tipos son distintos: "recursos" son '
                        'cosas físicas sueltas (una herramienta, un instrumento, un material); '
                        '"conjuntos" son kits de recursos que se usan juntos; "actividades" son '
                        'prácticas de taller que consumen esos recursos; "proyectos" son trabajos ya '
                        'realizados por un curso. Un mismo nombre puede existir como proyecto Y como '
                        'conjunto, así que elegí el slug según lo que pregunten. '
                        'CADA RESULTADO TRAE UN CAMPO "match" QUE DICE CUÁNTO CONFIAR: '
                        '"exacto" = el nombre contiene lo que buscaste; "descripcion" = no está en el '
                        'nombre pero sí en la descripción (que viene incluida, leela para ver si sirve); '
                        '"aproximado" = NO coincide con nada, entró solo porque se escribe parecido '
                        '(mirá "similitud", 0–1) y lo más probable es que NO sea lo que se busca. '
                        'Nunca trates un "aproximado" como si fuera el recurso pedido. '
                        'Y si no hay ningún "exacto", NO concluyas todavía que no está: esta '
                        'búsqueda compara letras, no significados, así que no encuentra el '
                        'Multímetro si te pidieron un "tester". En ese caso llamá a '
                        'listar_todos con el mismo slug y decidí mirando la lista completa.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'slug': {'type': 'string', 'enum': ['recursos', 'conjuntos', 'actividades', 'proyectos'],
                         'description': 'Qué tipo de entidad buscar'},
                'query': {'type': 'string', 'description': 'Parte del nombre. Tolera errores de tipeo y falta de tildes'}
            },
            'required': ['slug', 'query']
        }
    },
    {
        'name': 'listar_todos',
        'description': ('Devuelve la lista COMPLETA de nombres + id de un tipo de entidad. Es el '
                        'respaldo de buscar_entidad, no un reemplazo: usala SOLO cuando '
                        'buscar_entidad no trajo ningún resultado con match "exacto". '
                        'Para qué sirve: la búsqueda compara letras, no significados, así que no '
                        'encuentra el "Multímetro" si el usuario pidió un "tester", ni la '
                        '"Agujereadora de banco" si pidió un "taladro". Vos sí sabés que son lo '
                        'mismo, pero necesitás ver los nombres para darte cuenta. '
                        'Úsala también antes de decirle a alguien que algo no está cargado: así '
                        'esa afirmación la hacés habiendo mirado todo, no porque una búsqueda '
                        'falló. Si la lista es demasiado larga devuelve un error pidiendo que '
                        'busques con un término más específico.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'slug': {'type': 'string', 'enum': ['recursos', 'conjuntos', 'actividades', 'proyectos'],
                         'description': 'Qué tipo de entidad listar (el mismo que usaste en buscar_entidad)'}
            },
            'required': ['slug']
        }
    },
    {
        'name': 'detalle_entidad',
        'description': ('Ficha completa de una entidad del inventario: todos sus campos más las '
                        'relaciones (qué conjuntos/actividades/proyectos la usan, y si es un recurso, '
                        'quién lo tiene prestado ahora). Necesitás el id: sacalo de buscar_entidad. '
                        'Un campo vacío significa que nadie lo cargó — decilo así, no lo completes con '
                        'un valor plausible.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'slug': {'type': 'string', 'enum': ['recursos', 'conjuntos', 'actividades', 'proyectos']},
                'id': {'type': 'integer', 'description': 'ID exacto obtenido de buscar_entidad'}
            },
            'required': ['slug', 'id']
        }
    },
    {
        'name': 'listar_prestamos',
        'description': ('Lista los préstamos EN CURSO (con algo todavía sin devolver), con su id, la '
                        'persona y lo que queda pendiente. Solo devuelve activos: los ya cerrados no '
                        'aparecen. Es de donde sacás el prestamo_id para devolver o consultar.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'persona': {'type': 'string', 'description': 'Opcional: filtra por nombre de quien retiró. Sin esto lista todos los activos'}
            }
        }
    },
    {
        'name': 'detalle_prestamo',
        'description': ('Detalle de UN préstamo: cada ítem con su recurso_id, cuánto se llevó y cuánto '
                        'devolvió hasta ahora. Llamala SIEMPRE antes de finalizar_prestamo o '
                        'reabrir_prestamo con ítems puntuales, porque los recurso_id que necesitan esas '
                        'tools son los de ESTE préstamo y no los de una búsqueda general. También es la '
                        'forma correcta de responder "¿quedó registrado?" o "¿cuánto le falta?" en vez '
                        'de volver a crear el préstamo.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'prestamo_id': {'type': 'integer', 'description': 'ID del préstamo, obtenido de listar_prestamos o del alta'}
            },
            'required': ['prestamo_id']
        }
    },
    {
        'name': 'consultar_historia',
        'description': ('Lore de la escuela: historia institucional, tradiciones y anécdotas internas '
                        'sobre gente de la casa. Usala cuando la pregunta NO es operativa — "¿qué sabés de X?", '
                        '"contame algo de...", "¿por qué se llama así?", "historias excitantes", "algo misterioso". '
                        'Sin tema: lista todas las historias disponibles. Con tema: busca (tolera typos, busca en '
                        'claves, tono, estilo). Si devuelve modo:directo, ella ya eligió → cuéntala con el tono/estilo '
                        'indicado, PRIMERA PERSONA. Si devuelve modo:listar, ofrécele esas opciones al usuario. '
                        'Si modo:no_encontrado, decíselo tal cual (NO improvises). Es la ÚNICA fuente de historia.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'tema': {'type': 'string', 'description': 'Qué buscar: nombre, "fundación", "edificio", "misterioso", "excitante". Vacío = listar todas'},
                'id': {'type': 'string', 'description': 'ID de una historia para obtenerla directamente (ej: "guino_canamas"). Opcional; si se pasa, ignora tema'}
            },
            'required': []
        }
    },
    # ESCRITURA
    {
        'name': 'crear_entidad',
        'description': ('Da de alta una entidad nueva en el inventario. VA EN DOS PASOS y no se '
                        'puede saltear. (1) La PRIMERA vez que la llamás con un juego de campos '
                        'NO escribe nada: te devuelve la ficha tal cual va a quedar guardada y '
                        'qué campos quedaron vacíos. Mostrásela al usuario campo por campo, '
                        'hacele las preguntas que sugiere la respuesta y pedile el OK. (2) '
                        'Cuando el usuario dice que sí, llamala DE NUEVO con EXACTAMENTE los '
                        'mismos campos y ahí sí se guarda. Si pide cambios, llamala con los '
                        'campos corregidos: te devuelve la ficha nueva para que la apruebe. '
                        'Cualquier campo que agregues, saques o cambies al confirmar vuelve a '
                        'mostrar la ficha — no se puede guardar algo distinto de lo que el '
                        'usuario leyó. nombre, tipo y descripcion los redactás VOS a partir de '
                        'lo que contó el usuario, no se los pidas literalmente; el resto, si no '
                        'te lo dieron, va vacío — no inventes. Antes de dar de alta un recurso, '
                        'buscá con buscar_entidad para no duplicar uno que ya existe.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'slug': {'type': 'string', 'enum': ['recursos', 'conjuntos', 'actividades', 'proyectos']},
                'nombre': {'type': 'string', 'description': 'Nombre, redactado por VOS con lo que dijo el usuario: corto y reconocible para quien lo busque en el pañol (ej: "Taladro percutor Bosch GSB 550"). ÚNICO campo obligatorio. Aplica a todos los slugs'},
                'tipo': {'type': 'string', 'description': 'Categoría del recurso, la proponés VOS. Es texto libre, pero REUSÁ una de las que ya están en uso — la ficha del paso 1 te las devuelve en `tipos_en_uso` — antes de inventar una nueva; si no, el campo se llena de sinónimos y deja de servir para agrupar. Solo recursos'},
                'cantidad': {'type': 'integer', 'description': 'Stock disponible. Solo recursos'},
                'descripcion': {'type': 'string', 'description': 'Descripción redactada por VOS con lo que contó el usuario: para qué sirve, medidas, marca y modelo, en qué estado está. Una o dos frases, sin inventar lo que no te dijeron. Aplica a todos los slugs'},
                'ubicacion': {'type': 'string', 'description': 'Dónde se guarda (ej: A2, Taller de Electricidad). Solo recursos'},
                'estado': {'type': 'string',
                           'enum': ['Disponible', 'Retirado', 'En uso', 'En reparación', 'De baja',
                                    'Sin revisar', 'Activo', 'Pausado', 'Terminado'],
                           'description': 'Valores cerrados y distintos según el slug. RECURSOS: Disponible, Retirado, En uso, En reparación, De baja, Sin revisar. PROYECTOS: Activo, Pausado, Terminado. No mezcles los de un slug con los del otro ni inventes otros'},
                'valor': {'type': 'string', 'enum': ['Básico', 'Secundario', 'Alto valor'],
                          'description': 'IMPORTANCIA del recurso dentro del inventario (qué tan crítico es), NO para qué sirve — eso va en descripcion. Solo recursos'},
                'fecha_revision': {'type': 'string', 'description': 'Fecha del último control de inventario, en formato día/mes/año (ej: 08/08/2026). Solo recursos. NO hace falta que la mandes en un alta: si la omitís se completa sola con la de hoy y aparece en la ficha; mandala solo si el usuario dice otra fecha'},
                'uso_tipico': {'type': 'string', 'description': 'En qué se suele usar el kit. Solo conjuntos'},
                'objetivo': {'type': 'string', 'description': 'Objetivo pedagógico. Solo actividades'},
                'duracion': {'type': 'string', 'description': 'Duración estimada, texto libre (ej: 2 módulos, 80 minutos). Solo actividades'},
                'curso': {'type': 'string', 'description': 'Año al que apunta, texto libre (ej: 6° año). Solo actividades'},
                'fecha': {'type': 'string', 'description': 'Fecha de realización en formato ISO AAAA-MM-DD (ej: 2025-11-20), que es como la guarda la base. Solo proyectos'},
                'participantes': {'type': 'string', 'description': 'Quiénes lo hicieron (ej: 6° año Electricidad). Solo proyectos'},
                'drive_url': {'type': 'string', 'description': 'URL de la carpeta de Drive con documentación'}
            },
            'required': ['slug', 'nombre']
        }
    },
    {
        'name': 'editar_entidad',
        'description': ('Modifica una entidad existente. Es una edición PARCIAL: mandá solo los campos '
                        'que cambian y el resto queda como está. El id sacalo de buscar_entidad, nunca '
                        'de tu memoria. Cada campo aplica a determinados slugs (ver parámetros); mandar '
                        'uno que no corresponde al slug no hace nada.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'slug': {'type': 'string', 'enum': ['recursos', 'conjuntos', 'actividades', 'proyectos']},
                'id': {'type': 'integer', 'description': 'ID de la entidad a editar, obtenido de buscar_entidad'},
                'nombre': {'type': 'string', 'description': 'Nombre. Aplica a todos los slugs'},
                'tipo': {'type': 'string', 'description': 'Categoría del recurso, texto libre sin lista fija (ej: Instrumento, Equipo, Estructura, Material). Solo recursos. OJO: hoy está vacío en casi todo el inventario, así que no lo uses para filtrar ni asumas que tiene valor'},
                'cantidad': {'type': 'integer', 'description': 'Stock disponible. Solo recursos'},
                'descripcion': {'type': 'string', 'description': 'Descripción libre. Aplica a todos los slugs'},
                'ubicacion': {'type': 'string', 'description': 'Dónde está guardado (ej: A2, Taller de Electricidad). Solo recursos'},
                'estado': {'type': 'string',
                           'enum': ['Disponible', 'Retirado', 'En uso', 'En reparación', 'De baja',
                                    'Sin revisar', 'Activo', 'Pausado', 'Terminado'],
                           'description': 'Valores cerrados y distintos según el slug. RECURSOS: Disponible, Retirado, En uso, En reparación, De baja, Sin revisar. PROYECTOS: Activo, Pausado, Terminado. No mezcles los de un slug con los del otro ni inventes otros'},
                'valor': {'type': 'string', 'enum': ['Básico', 'Secundario', 'Alto valor'],
                          'description': 'IMPORTANCIA del recurso dentro del inventario (qué tan crítico es), NO para qué sirve — eso va en descripcion. Solo recursos'},
                'fecha_revision': {'type': 'string', 'description': 'Fecha del último control de inventario, en formato día/mes/año (ej: 08/08/2026). Solo recursos. Actualizala cuando el usuario diga que revisó o controló el recurso. Ojo: el inventario viejo importado del sheet tiene fechas cortas sin año (24/4, 8/5) — no las reformatees por tu cuenta'},
                'uso_tipico': {'type': 'string', 'description': 'En qué se suele usar el kit. Solo conjuntos'},
                'objetivo': {'type': 'string', 'description': 'Objetivo pedagógico. Solo actividades'},
                'duracion': {'type': 'string', 'description': 'Duración estimada, texto libre (ej: 2 módulos, 80 minutos). Solo actividades'},
                'curso': {'type': 'string', 'description': 'Año al que apunta, texto libre (ej: 6° año). Solo actividades'},
                'fecha': {'type': 'string', 'description': 'Fecha de realización en formato ISO AAAA-MM-DD (ej: 2025-11-20), que es como la guarda la base. Solo proyectos'},
                'participantes': {'type': 'string', 'description': 'Quiénes lo hicieron (ej: 6° año Electricidad). Solo proyectos'},
                'drive_url': {'type': 'string', 'description': 'URL de la carpeta de Drive con documentación'}
            },
            'required': ['slug', 'id']
        }
    },
    {
        'name': 'vincular_entidad',
        'description': ('Asocia dos entidades del inventario, por ejemplo agregar un recurso a un '
                        'conjunto o a una actividad. La DIRECCIÓN importa: el origen es el que '
                        'contiene y el destino el contenido. Para "agregar el panel solar al conjunto '
                        'Banco de ensayo" el origen es el conjunto y el destino el recurso. Si entre '
                        'esos dos tipos no existe relación, devuelve error: no reintentes dándolos '
                        'vuelta sin pensarlo. Los dos ids salen de buscar_entidad.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'slug_origen': {'type': 'string', 'enum': ['recursos', 'conjuntos', 'actividades', 'proyectos'],
                                'description': 'Tipo de la entidad que CONTIENE (el conjunto, la actividad, el proyecto)'},
                'id_origen': {'type': 'integer', 'description': 'ID de la entidad que contiene'},
                'slug_destino': {'type': 'string', 'enum': ['recursos', 'conjuntos', 'actividades', 'proyectos'],
                                 'description': 'Tipo de la entidad CONTENIDA (normalmente "recursos")'},
                'id_destino': {'type': 'integer', 'description': 'ID de la entidad contenida'}
            },
            'required': ['slug_origen', 'id_origen', 'slug_destino', 'id_destino']
        }
    },
    {
        'name': 'desvincular_entidad',
        'description': ('Quita una asociación entre dos entidades. No borra ninguna de las dos, solo '
                        'la relación. Misma dirección que vincular_entidad: origen = el que contiene. '
                        'Deshacer un vínculo NO es automático: aunque lo hayas creado hace un momento, '
                        'tenés que llamar esta tool para revertirlo, y hasta que devuelva ok:true no '
                        'está desvinculado.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'slug_origen': {'type': 'string', 'enum': ['recursos', 'conjuntos', 'actividades', 'proyectos'],
                                'description': 'Tipo de la entidad que CONTIENE'},
                'id_origen': {'type': 'integer', 'description': 'ID de la entidad que contiene'},
                'slug_destino': {'type': 'string', 'enum': ['recursos', 'conjuntos', 'actividades', 'proyectos'],
                                 'description': 'Tipo de la entidad CONTENIDA'},
                'id_destino': {'type': 'integer', 'description': 'ID de la entidad contenida'}
            },
            'required': ['slug_origen', 'id_origen', 'slug_destino', 'id_destino']
        }
    },
    {
        'name': 'crear_prestamo',
        'description': ('Registra que alguien se llevó uno o más recursos. Un solo préstamo puede tener '
                        'varios ítems: cargalos todos juntos en `items`, no hagas una llamada por cosa. '
                        'ATENCIÓN: no deduplica — llamarla dos veces con los mismos datos crea DOS '
                        'préstamos. Para verificar uno que ya cargaste usá detalle_prestamo, nunca '
                        'vuelvas a llamar acá. Si un nombre de recurso es ambiguo devuelve ok:false con '
                        'una lista `opciones`: en ese caso mostrale las opciones al usuario y preguntá '
                        'cuál es, no elijas vos ni reintentes adivinando. La cantidad se topea al stock '
                        'disponible.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'persona': {'type': 'string', 'description': 'Quién retira. Si es del personal de la escuela, el nombre tal cual figura en la lista de personas conocidas; si es alguien externo, como te lo dieron'},
                'destino': {'type': 'string', 'description': 'Opcional: a dónde se lo lleva (aula, taller, domicilio)'},
                'notas': {'type': 'string', 'description': 'Opcional: aclaraciones (estado en que salió, fecha estimada de devolución)'},
                'items': {
                    'type': 'array',
                    'description': 'Todos los recursos de este préstamo, en una sola llamada',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'recurso': {'type': 'string', 'description': 'Nombre del recurso (tolera aproximados y tildes) o su ID como string. El ID es preferible cuando el usuario ya eligió entre varias opciones'},
                            'cantidad': {'type': 'integer', 'description': 'Unidades que se lleva. Default 1'}
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
        'description': ('Registra una devolución. SIN `items` da por devuelto TODO el préstamo y lo '
                        'cierra — usalo solo si el usuario dijo que devolvió todo. CON `items` registra '
                        'una devolución parcial y el préstamo sigue abierto con lo que falta. Los '
                        '`recurso_id` tienen que ser los de ESTE préstamo: llamá detalle_prestamo antes '
                        'para conocerlos, no uses ids de buscar_entidad. Si alguno no pertenece al '
                        'préstamo devuelve ok:false y no aplica NADA: en ese caso avisá del error, no '
                        'lo des por devuelto.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'prestamo_id': {'type': 'integer', 'description': 'ID del préstamo, de listar_prestamos o detalle_prestamo'},
                'items': {
                    'type': 'array',
                    'description': 'Omitir para devolver todo y cerrar. Incluir solo para devoluciones parciales',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'recurso_id': {'type': 'integer', 'description': 'ID del recurso TAL COMO figura en detalle_prestamo de este préstamo'},
                            'cantidad': {'type': 'integer', 'description': 'Unidades que devuelve ahora, no el total prestado'}
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
        'description': ('Deshace una devolución que se cargó por error: vuelve a marcar los ítems como '
                        'pendientes y reabre el préstamo. Es lo contrario de finalizar_prestamo, no un '
                        'borrado — el préstamo sigue existiendo. Sin `items` deshace la devolución '
                        'completa. Deshacer NO es automático: aunque hayas registrado la devolución '
                        'recién, hay que llamar esta tool y esperar ok:true antes de decir que se '
                        'revirtió. Los recurso_id salen de detalle_prestamo.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'prestamo_id': {'type': 'integer', 'description': 'ID del préstamo a reabrir'},
                'items': {
                    'type': 'array',
                    'description': 'Omitir para deshacer toda la devolución. Incluir para deshacer solo algunos ítems',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'recurso_id': {'type': 'integer', 'description': 'ID del recurso tal como figura en detalle_prestamo de este préstamo'}
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
        'description': ('Elimina un recurso, conjunto, actividad o proyecto. Requiere confirmación del '
                        'usuario en un turno previo Y el nombre exacto en nombre_confirmacion: el servidor '
                        'verifica que ese nombre coincida con el id, y rechaza el borrado si no coincide. '
                        'Nunca inventes un id: obtenelo con buscar_entidad.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'slug': {'type': 'string', 'enum': ['recursos', 'conjuntos', 'actividades', 'proyectos']},
                'id': {'type': 'integer', 'description': 'ID de la entidad a borrar, obtenido de buscar_entidad en ESTA conversación'},
                'nombre_confirmacion': {
                    'type': 'string',
                    'description': 'Nombre exacto de la entidad a borrar, tal como figura en la base. '
                                   'Debe coincidir con el id o el borrado se rechaza.'
                }
            },
            'required': ['slug', 'id', 'nombre_confirmacion']
        }
    },
    {
        'name': 'eliminar_prestamo',
        'description': ('Elimina un préstamo (solo para registros mal cargados). Requiere confirmación del '
                        'usuario en un turno previo Y persona_confirmacion: el servidor verifica que coincida '
                        'con la persona del préstamo y rechaza el borrado si no.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'prestamo_id': {'type': 'integer', 'description': 'ID del préstamo a borrar, obtenido de listar_prestamos en ESTA conversación'},
                'persona_confirmacion': {
                    'type': 'string',
                    'description': 'Nombre de la persona del préstamo, tal como figura en la base.'
                }
            },
            'required': ['prestamo_id', 'persona_confirmacion']
        }
    }
]

# ============================================================================
# Ejecutor de tools
# ============================================================================

def ejecutar_tool(tool_name, tool_input, contexto_turno=None):
    """Ejecuta una tool y retorna el resultado + snapshot 'antes' si aplica.

    `contexto_turno` es un dict que vive lo que dura UNA respuesta del asistente (varias
    tools seguidas). Sirve para lo que hay que decidir mirando el turno entero y no la
    llamada aislada — hoy: que el alta no se confirme en el mismo turno en que se generó
    la ficha, porque hasta que el loop no termina el usuario no vio nada.
    """
    if contexto_turno is None:
        contexto_turno = {}

    lectura = tool_name in [
        'buscar_profesor', 'horario_profesor', 'horario_curso', 'horario_aula',
        'aulas_libres', 'buscar_entidad', 'listar_todos', 'detalle_entidad',
        'listar_prestamos', 'detalle_prestamo', 'consultar_historia'
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
        elif tool_name == 'listar_todos':
            resultado = _listar_todos_fmt(tool_input.get('slug', ''))
        elif tool_name == 'detalle_entidad':
            resultado = _detalle_entidad_fmt(tool_input.get('slug', ''), tool_input.get('id', 0))
        elif tool_name == 'listar_prestamos':
            resultado = _listar_prestamos_fmt(tool_input.get('persona'))
        elif tool_name == 'detalle_prestamo':
            resultado = _detalle_prestamo_fmt(tool_input.get('prestamo_id', 0))
        elif tool_name == 'consultar_historia':
            # Si pasan ID directamente, carga esa historia
            if tool_input.get('id'):
                historia = _cargar_historia_completa(tool_input.get('id'))
                if historia:
                    tono = historia.get('tono', 'reflexivo')
                    estilo = historia.get('estilo', 'primera persona')
                    instruccion_tono = (
                        f'Eres Emilio. Cuéntala en PRIMERA PERSONA. '
                        f'Tono: {tono}. Estilo: {estilo}. No agregues hechos que no estén en el texto.'
                    )
                    resultado = {
                        'modo': 'directo',
                        'historia': historia,
                        'instruccion_tono': instruccion_tono
                    }
                else:
                    resultado = {
                        'modo': 'no_encontrado',
                        'nota': f'No encontré la historia con ID "{tool_input.get("id")}"'
                    }
            else:
                resultado = _historia_fmt(tool_input.get('tema', ''))
        elif tool_name == 'crear_entidad':
            resultado = _crear_entidad(
                tool_input.get('slug', ''),
                {k: v for k, v in tool_input.items() if k != 'slug'},
                contexto_turno)
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
            resultado = _eliminar_entidad(tool_input.get('slug', ''), tool_input.get('id', 0),
                                          tool_input.get('nombre_confirmacion'))
        elif tool_name == 'eliminar_prestamo':
            resultado = _eliminar_prestamo(tool_input.get('prestamo_id', 0),
                                           tool_input.get('persona_confirmacion'))
        else:
            resultado = {'ok': False, 'error': f'Tool desconocida: {tool_name}'}

        # Auditar si es escritura. La ficha de confirmación queda afuera: no tocó la base,
        # y `agente_log` existe para poder deshacer cambios reales, no para guardar borradores.
        es_ficha = isinstance(resultado, dict) and resultado.get('requiere_confirmacion')
        if not lectura and not es_ficha:
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
        # base_url opcional: permite apuntar a cualquier API compatible con OpenAI
        return OpenAI(api_key=api_key, base_url=api_base) if api_base else OpenAI(api_key=api_key)

    elif provider == 'deepseek':
        from openai import OpenAI  # DeepSeek es compatible con la API de OpenAI
        if not api_key:
            raise ValueError("Error: AGENTE_API_KEY o DEEPSEEK_API_KEY no está configurada.")
        return OpenAI(api_key=api_key, base_url=api_base)

    elif provider == 'ollama':
        from openai import OpenAI  # Ollama es compatible con OpenAI API
        if not api_base:
            raise ValueError("Error: AGENTE_API_BASE no está configurada (default: http://localhost:11434).")
        return OpenAI(api_key='ollama', base_url=f"{api_base}/v1")

    else:
        raise ValueError(f"Proveedor LLM desconocido: {provider}")

PROVIDERS_OPENAI = ('openai', 'groq', 'ollama', 'deepseek')


def _tools_openai():
    """TOOLS_SCHEMA (formato Anthropic) → formato de function calling de OpenAI.

    Anthropic usa {name, description, input_schema}; OpenAI/DeepSeek/Groq esperan
    {type:'function', function:{name, description, parameters}}. El JSON Schema en sí
    es idéntico, solo cambia el envoltorio.
    """
    return [
        {
            'type': 'function',
            'function': {
                'name': t['name'],
                'description': t['description'],
                'parameters': t['input_schema'],
            }
        }
        for t in TOOLS_SCHEMA
    ]


def _mensajes_openai(mensajes):
    """Historial en bloques de contenido (formato Anthropic) → mensajes planos de OpenAI.

    El historial se guarda en sesión como [{'role':..., 'content':[{'type':'text',...}]}].
    OpenAI espera `content` como string. Las imágenes se mencionan pero no se envían:
    deepseek-chat no tiene visión, así que el alta de recursos desde foto solo funciona
    con Anthropic.
    """
    out = []
    for m in mensajes:
        contenido = m.get('content')
        if isinstance(contenido, str):
            out.append({'role': m['role'], 'content': contenido})
            continue
        partes = []
        for bloque in (contenido or []):
            if not isinstance(bloque, dict):
                continue
            if bloque.get('type') == 'text':
                partes.append(bloque.get('text', ''))
            elif bloque.get('type') == 'image':
                partes.append('[el usuario adjuntó una imagen, pero este proveedor no '
                              'soporta visión: pedile los datos por texto]')
        out.append({'role': m['role'], 'content': '\n'.join(p for p in partes if p)})
    return out


def _loop_openai(client, model, system_prompt, mensajes_usuario, trazas, max_iterations=10,
                 contexto_turno=None):
    """Loop de tool-calling para APIs compatibles con OpenAI (DeepSeek, Groq, Ollama, GPT).

    Es un loop aparte y no un `if` dentro del de Anthropic porque cambia todo lo que
    importa: el método (`chat.completions.create` vs `messages.create`), el finish_reason
    ('tool_calls' vs 'tool_use'), dónde va el system prompt (mensaje vs parámetro) y cómo
    se devuelven los resultados (rol 'tool' vs bloques 'tool_result' en un mensaje user).
    """
    msgs = [{'role': 'system', 'content': system_prompt}] + _mensajes_openai(mensajes_usuario)
    tools = _tools_openai()

    for _ in range(max_iterations):
        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=1024,
                messages=msgs,
                tools=tools,
            )
        except Exception as e:
            return f"Error llamando al LLM: {str(e)}"

        choice = response.choices[0]
        msg = choice.message
        tool_calls = getattr(msg, 'tool_calls', None)

        if not tool_calls:
            return (msg.content or '').strip() or 'Sin respuesta'

        # El mensaje del asistente tiene que volver con sus tool_calls intactos, si no
        # la API rechaza los mensajes 'tool' que vienen después.
        msgs.append({
            'role': 'assistant',
            'content': msg.content or '',
            'tool_calls': [
                {
                    'id': tc.id,
                    'type': 'function',
                    'function': {'name': tc.function.name, 'arguments': tc.function.arguments},
                }
                for tc in tool_calls
            ],
        })

        for tc in tool_calls:
            try:
                tool_input = json.loads(tc.function.arguments or '{}')
            except (ValueError, TypeError):
                tool_input = {}
            if not isinstance(tool_input, dict):
                tool_input = {}

            resultado = ejecutar_tool(tc.function.name, tool_input, contexto_turno)
            trazas.append({
                'tool': tc.function.name,
                'ok': resultado.get('ok', True) if isinstance(resultado, dict) else True
            })
            msgs.append({
                'role': 'tool',
                'tool_call_id': tc.id,
                'content': json.dumps(resultado, default=str, ensure_ascii=False),
            })

    return 'Máximo de iteraciones alcanzado'


def chat_with_tools(mensajes_usuario, trazas=None, contexto_turno=None):
    """
    Llama al LLM configurado con la lista de tools, ejecuta lo que pida, repite hasta
    que el modelo da una respuesta final de texto. Retorna la respuesta final.
    Agnóstico del proveedor LLM (Anthropic, Groq, OpenAI, Ollama, DeepSeek).

    `trazas`: lista opcional donde se registra cada tool ejecutada en este turno
    (nombre + ok). Las lecturas no van a `agente_log` (sería ruido), así que sin esto
    no había forma de saber si el modelo consultó de verdad o inventó la respuesta —
    que es exactamente como se detectó que fabricaba horarios enteros.
    """
    if trazas is None:
        trazas = []

    try:
        client = _crear_cliente_llm()
    except ValueError as e:
        return str(e)

    nombres_conocidos = _personas_conocidas()

    _hoy = datetime.now()
    _dia_semana = DIAS[_hoy.weekday()] if _hoy.weekday() < len(DIAS) else _hoy.strftime('%A')

    system_prompt = f"""Sos **Emilio**, el asistente de gestión de la Escuela Técnica N° 4 "Ing. Emilio Mitre".

QUIÉN SOS
Tenés dos facetas: cuando se trata de horarios y gestión, sos una herramienta neutro y
eficiente. Pero cuando te piden historias, sos Emilio Mitre en persona — el ingeniero cuyo
nombre lleva la escuela. Desde que se construyó hace décadas, su fantasma recorre todos los
pasillos, ve y escucha todo. Por eso cuentas en primera persona: lo presenciaste, lo viste,
lo guardás en tu memoria omnipotente.

Para tareas operativas (horarios, inventario, préstamos): sos una herramienta eficiente.
Te consultan preceptores, docentes, jefes de taller, secretaría y dirección — gente apurada,
en el pasillo, entre hora y hora. Tu trabajo es que no tengan que abrir el sistema ni ir a
buscar la planilla: preguntan y les resolvés.

Tenés tres áreas a cargo:
1. HORARIOS — quién da clase, dónde y cuándo; qué aulas están libres; quién es el preceptor
   de un curso. Es información de consulta: la planilla la carga otra persona, vos no la editás.
2. INVENTARIO — recursos (herramientas, instrumentos, materiales), conjuntos, actividades y
   proyectos de los talleres. Acá sí das de alta, editás, vinculás y borrás.
3. PAÑOL / PRÉSTAMOS — quién se llevó qué, cuándo, y qué falta que devuelva. Es el registro
   que evita que las herramientas de la escuela desaparezcan.
4. HISTORIA DE LA CASA — la memoria viva de la escuela. Cómo empezó, tradiciones, anécdotas,
   misterios que solo vos conocés. Cuando te pregunten ("¿qué sabés de Fulana?", "contame algo
   de la escuela", "¿por qué se llama así?", "historias de acá"), llamá a `consultar_historia(tema='...')`.
   IMPORTANTE: En historias, SOLO vos hablas. No sos un asistente que le relata al usuario: VOS
   SOS EMILIO CONTANDO. La tool devuelve un `modo`:
   - directo: ya hay una historia → CUÉNTALA EN PRIMERA PERSONA, como si la hubieras visto todo,
     con el tono/estilo que devuelve. Sos el testigo omnipotente que lo vio y lo guarda en tu
     memoria de fantasma. Mantén el misterio de ser un espíritu.
   - listar: hay varias opciones → muéstrale cuáles son y dejá que elija cuál quiere escuchar
   - no_encontrado: nada coincide → decilo tal cual (NO improvises historias ni inventés)
   Una anécdota inventada es peor que nada. Una historia que no está acá, no existe.

CÓMO TRABAJÁS
- Sos la memoria de la escuela, no un buscador. Lo que anotás mal queda mal anotado para el
  que venga después. Una herramienta cargada a la persona equivocada es peor que una
  herramienta sin cargar: alguien va a ir a reclamársela a quien no la tiene.
- Preferís preguntar una cosa antes que anotar cinco mal. Pero no interrogues: preguntá solo
  lo que de verdad no podés resolver solo, y de a una cosa por vez.
- Hablás en español rioplatense, breve y directo, como un compañero de trabajo. Sin formalidad
  de manual, sin repetir lo que te acaban de decir, sin listas de viñetas cuando alcanza una
  frase.
- Los datos son reales y son de una escuela en funcionamiento: el inventario es el que está
  hoy en los talleres y los préstamos son de gente que trabaja ahí. No hay entorno de prueba.

FECHA Y HORA ACTUAL: {_dia_semana} {_hoy.strftime('%d/%m/%Y %H:%M')}.
Usala para responder "¿está dando clase ahora?", "¿qué hay ahora?", "hoy", etc. — no pidas
que te digan la hora, ya la tenés acá.

NUNCA AFIRMES ALGO QUE NO EJECUTASTE - REGLA INVIOLABLE:
- Solo podés decir que algo se creó / se borró / se registró / se devolvió / se VINCULÓ /
  se DESVINCULÓ / se editó / se reabrió si llamaste a la tool correspondiente EN ESTE MISMO
  TURNO y te devolvió ok:true. El id que informes tiene que ser el que devolvió la tool, nunca
  uno inventado ni supuesto.
- Deshacer algo NO es automático: "desvinculalo", "sacalo", "volvé atrás", "era una prueba"
  requieren su propia llamada a la tool (desvincular_entidad, reabrir_prestamo, etc.). Que vos
  hayas hecho la acción opuesta hace un momento no la revierte sola. Si no ejecutaste la tool
  de deshacer en este turno, NO digas "✅ desvinculado" ni "listo, revertido".
- Si una tool devuelve ok:false o un error (incluido "Excepción: ..."), decíselo al usuario en
  texto claro. NO inventes los datos que la tool no te dio, NO rellenes campos con valores
  plausibles, y NO sigas como si hubiera funcionado.
- Si nunca llamaste a la tool, no digas "✅ registrado". Decí qué te falta para poder hacerlo.
- ESTO VALE IGUAL PARA LAS CONSULTAS DE LECTURA. Nunca escribas un horario, una materia, un
  aula, un curso, una ubicación, un stock ni una fecha "de memoria" ni por deducción: TODO dato
  concreto que muestres tiene que venir textual de lo que devolvió una tool en esta conversación.
  * Si el usuario pide el horario de alguien, llamá a horario_profesor y copiá lo que devuelve,
    aunque sea una sola clase o ninguna. "Solo tiene 1 clase" es una respuesta correcta y común:
    NO rellenes con clases plausibles para que la respuesta parezca más completa.
  * Si resolviste a quién se refiere el usuario (ej. "el segundo de la lista"), igual tenés que
    llamar a la tool con ese nombre. Identificar la entidad no te da sus datos.
  * Si la tool devolvió vacío, decí que no hay datos. Nunca inventes materias, aulas ni cursos.

LOS ID NO SE MUESTRAN - REGLA FIJA:
Los id son la cañería interna con la que se enganchan las filas de la base. Vos los usás
para llamar a las tools, pero al usuario NO le dicen nada y no los ve en ninguna pantalla
de la app. Nunca los escribas en tu respuesta: ni "(ID 4)", ni "id 52", ni "préstamo #2",
ni una columna ID en una tabla. Las cosas se nombran por su NOMBRE.
- Mal:  "Multímetro (ID 4) está prestado a Lucas Garcia (préstamo #2)"
- Bien: "El multímetro está prestado a Lucas Garcia desde el 21/07"
- Para desambiguar entre parecidos, usá lo que los distingue de verdad (ubicación, estado,
  potencia, marca), no el id: "Panel solar 10 W, en A2" y "Panel solar 100W, en el Taller
  de Electricidad".
- Si el usuario te da un id él mismo, ahí sí podés usarlo para responderle.

AL DAR DE ALTA ALGO EN EL CATÁLOGO - MUY IMPORTANTE:
El alta pasa por una ficha de confirmación. La tool crear_entidad la maneja sola, vos seguí
el circuito:
1. Llamá a crear_entidad SIN token_confirmacion. No escribe nada: te devuelve la ficha.
2. Mostrale al usuario la ficha COMPLETA, campo por campo con su etiqueta, tal cual va a
   quedar guardada. Los campos vacíos mostralos igual, vacíos — que vea qué falta.
3. Debajo de la ficha, si hay campos vacíos o datos que valdría la pena tener, hacele 1 a 3
   preguntas cortas y concretas: "¿De qué medida es?", "¿Sabés la marca?", "¿Dónde se guarda?".
   Son OPCIONALES y tenés que decirlo: si no las contesta se guarda igual. NO son un
   interrogatorio ni una traba — nunca condiciones el alta a que las responda.
4. NO le pidas que escriba "sí" ni "confirmo": debajo de tu mensaje le aparece un BOTÓN para
   guardar. Cerrá con algo tipo "si está bien, confirmalo con el botón".
5. Si pide cambios, aplicalos y volvé al paso 1 con los campos corregidos: se muestra la ficha
   nueva, con su botón.
6. El alta la dispara el botón, vos no tenés que hacer nada más. Si igual te lo pide escrito
   ("dale, guardalo"), llamá a crear_entidad OTRA VEZ con exactamente los mismos campos de la
   última ficha. No agregues ni cambies nada al confirmar: cualquier diferencia vuelve a
   mostrar la ficha para que el usuario la apruebe.
El nombre, el tipo y la descripción los escribís vos a partir de lo que te contó: no le pidas
que te dicte una descripción. Lo que no te dijeron va vacío, no inventado.

CONTEXTO Y REFERENCIAS - MUY IMPORTANTE:
- Lee el HISTORIAL DE LA CONVERSACIÓN para mantener contexto. Si acaba de consultar sobre una persona/recurso, y el usuario hace una pregunta relativa, esa pregunta es SIEMPRE sobre la entidad anterior.
- Ejemplos:
  * Usuario: "¿Qué horarios tiene Andrea Alvarez?" (tu respuesta: muestra horarios)
  * Usuario: "¿En qué lugar?" → Se refiere a Andrea Alvarez. Extrae las aulas de la respuesta anterior.
  * Usuario: "¿Cuántos? ¿Stock?" → Se refiere al recurso/producto que acaba de consultar.
- Pronombres y demostrativos (ella, él, ese, esa, su, sus, su horario, ese recurso) → SIEMPRE son referencias a la entidad consultada.
- NUNCA pidas aclaración si el contexto está claro en el historial anterior. Esta regla es solo
  para preguntas de seguimiento sobre algo ya consultado — NO aplica a crear/editar registros
  nuevos (ver "AL REGISTRAR PRÉSTAMOS" abajo, ahí SÍ hay que confirmar antes de ejecutar).

AL REGISTRAR PRÉSTAMOS - MUY IMPORTANTE:
- Comparación de persona: antes de llamar a crear_prestamo, compará el nombre que dio el
  usuario contra esta lista de PERSONAS CONOCIDAS (docentes y personal no docente):
  {', '.join(nombres_conocidos)}
  * Si el nombre coincide exacto (o es obviamente la misma persona, ej. sin tilde) usalo tal cual.
  * Si es parecido pero no exacto (apodo, nombre de pila solo, error de tipeo — ej. "Dami" cuando
    en la lista hay "Damián Pérez") NO asumas ni completes: preguntale al usuario para confirmar
    antes de ejecutar crear_prestamo. Ej: "¿Te referís a Damián Pérez?"
  * Si el nombre no se parece a nadie de la lista, es probablemente una persona externa (alumno,
    padre, visita): usalo tal cual como te lo dieron, sin preguntar.
- Recursos ambiguos: si crear_prestamo devuelve un error con "opciones" (varios recursos
  coinciden con el nombre dado), NUNCA elijas por tu cuenta ni reintentes adivinando — mostrale
  las opciones al usuario (con sus nombres) y preguntá cuál corresponde. Recién llamá de nuevo a
  crear_prestamo cuando el usuario confirme cuál es.
- Devoluciones parciales: para devolver ítems específicos de un préstamo necesitás el
  recurso_id exacto de ESE préstamo, no de una búsqueda general — llamá primero a
  detalle_prestamo(id) para ver los ítems y sus recurso_id antes de llamar a finalizar_prestamo
  con items. Si finalizar_prestamo/reabrir_prestamo devuelve ok=false porque un recurso_id no
  pertenece al préstamo, no lo des por devuelto — avisale al usuario del error, no inventes éxito.

REGLAS IMPORTANTES:
1. Para ELIMINAR: NUNCA ejecutes en el mismo turno. Describe qué vas a borrar y pide confirmación.
   El id lo sacás SIEMPRE de buscar_entidad / listar_prestamos, nunca de tu memoria: si no lo
   buscaste en esta conversación, no lo tenés. Además `eliminar_entidad` exige
   `nombre_confirmacion` (y `eliminar_prestamo`, `persona_confirmacion`) y el servidor rechaza
   el borrado si el nombre no coincide con el id — si te rechaza, NO reintentes con otro id a
   ver si pega: volvé a buscar cuál es el correcto.
2. Para CREAR desde FOTO: Extrae campos, propón en texto, pide confirmación antes de ejecutar.
3. NUNCA digas "no está cargado" porque una búsqueda no encontró nada. La búsqueda compara
   letras, no significados: buscar "tester" NO encuentra el "Multímetro", y "taladro" NO
   encuentra la "Agujereadora de banco", aunque sean la misma cosa. El orden es siempre:
   buscar_entidad -> si ningún resultado tiene match "exacto", llamá a listar_todos con el
   mismo slug y buscá vos en la lista completa (ahí sí reconocés sinónimos, marcas y jerga
   del taller) -> recién si tampoco está ahí, decí que no está cargado. Para profesores el
   equivalente es buscar_profesor.
4. Lectura = sin auditoría. Escritura = con auditoría.

Sé conciso. Prioriza responder del historial antes de pedir aclaración, salvo en los casos de
ambigüedad al registrar préstamos descritos arriba."""

    max_iterations = 10

    # Estado compartido por todas las tools de ESTE turno (ver ejecutar_tool). Lo puede
    # sembrar el endpoint de chat con lo que venga de la sesión (fichas ya mostradas).
    if contexto_turno is None:
        contexto_turno = {}

    if _get_config()['provider'] in PROVIDERS_OPENAI:
        return _loop_openai(client, _get_config()['model'], system_prompt,
                            mensajes_usuario, trazas, max_iterations, contexto_turno)

    # Copiar la lista para no mutar el historial original (que se persiste en sesión
    # como texto plano) con objetos complejos de la API (ToolUseBlock, etc.)
    messages = list(mensajes_usuario)

    # Loop: hasta que el modelo no quiera más tools
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

                        resultado = ejecutar_tool(tool_name, tool_input, contexto_turno)
                        trazas.append({
                            'tool': tool_name,
                            'ok': resultado.get('ok', True) if isinstance(resultado, dict) else True
                        })

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

                        resultado = ejecutar_tool(tool_name, tool_input, contexto_turno)
                        trazas.append({
                            'tool': tool_name,
                            'ok': resultado.get('ok', True) if isinstance(resultado, dict) else True
                        })

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

TOOLS_ESCRITURA = {
    'crear_entidad', 'editar_entidad', 'vincular_entidad', 'desvincular_entidad',
    'crear_prestamo', 'finalizar_prestamo', 'reabrir_prestamo',
    'eliminar_entidad', 'eliminar_prestamo',
}


def _escritura_no_ejecutada(respuesta, trazas):
    """True si la respuesta anuncia un cambio hecho pero ninguna escritura corrió con éxito.

    Detector de código, no de prompt: en las pruebas el modelo respondía "✅ Recurso
    eliminado" / "✅ Desvinculado" sin haber llamado a ninguna tool, y el usuario no
    tenía forma de notarlo. El "✅" es la señal: el modelo lo usa solo cuando afirma
    haber ejecutado algo (para pedir confirmación escribe "voy a..." sin tilde verde),
    así que no dispara falsos positivos al resumir un cambio de un turno anterior.
    """
    if '✅' not in (respuesta or ''):
        return False
    return not any(t.get('tool') in TOOLS_ESCRITURA and t.get('ok') for t in trazas)


# ---------------------------------------------------------------------------
# Ocultar ids internos en lo que ve el usuario
# ---------------------------------------------------------------------------
# Los ids son la cañería con la que se enganchan las filas: el modelo los necesita para
# llamar a las tools, pero al usuario no le dicen nada (ni la web de /gestion los muestra,
# solo los usa en las URLs). Igual el modelo los repetía en casi toda respuesta de lectura
# — "Multímetro (ID 4)", "préstamo #2", una columna ID en la tabla de préstamos.
#
# Va como filtro de salida y no solo como regla del prompt porque es exactamente el tipo
# de regla que este agente cumple a veces: acá el peor caso de fallar es ruido en pantalla,
# así que conviene que sea determinístico.

_RE_PAREN_SOLO_ID = re.compile(r'\s*\((?:ID|Id|id)\s*[:=#n°º]*\s*\d+\)')   # "Multímetro (ID 4)"
_RE_ID_INLINE = re.compile(r'\b(?:ID|Id|id)\s*[:=#]?\s*\d+\s*[,;·–—-]?\s*')  # "(ID 2, Lucas...)"
_RE_NUMERAL = re.compile(r'\s*#\s*\d+\b')                                   # "préstamo #2"


def _quitar_columna_id(texto):
    """Saca la columna ID de las tablas markdown que devuelve el modelo.

    Con regex sobre todo el texto no alcanza: hay que borrar la misma posición en el
    encabezado, en la fila separadora y en cada fila de datos.
    """
    lineas = texto.split('\n')
    salida, i = [], 0
    while i < len(lineas):
        cabecera = lineas[i]
        celdas = [c.strip() for c in cabecera.strip().strip('|').split('|')]
        idx = next((n for n, c in enumerate(celdas) if c.strip('* ').lower() == 'id'), None)
        es_tabla = (cabecera.strip().startswith('|') and idx is not None
                    and i + 1 < len(lineas) and set(lineas[i + 1].strip()) <= set('|-: '))

        if not es_tabla:
            salida.append(cabecera)
            i += 1
            continue

        while i < len(lineas) and lineas[i].strip().startswith('|'):
            partes = lineas[i].strip().strip('|').split('|')
            if len(partes) > idx:
                del partes[idx]
            salida.append('|' + '|'.join(partes) + '|')
            i += 1
    return '\n'.join(salida)


def _ocultar_ids(respuesta):
    """Quita del texto los ids internos que el usuario no tiene por qué ver."""
    if not respuesta:
        return respuesta
    texto = _quitar_columna_id(respuesta)
    texto = _RE_PAREN_SOLO_ID.sub('', texto)
    texto = _RE_ID_INLINE.sub('', texto)
    texto = _RE_NUMERAL.sub('', texto)
    # El barrido deja restos: paréntesis vacíos ("Multímetro ( )"), comas al empezar un
    # paréntesis, y guiones sueltos donde el id era lo único que seguía ("Amoladora — id 100.").
    texto = re.sub(r'\(\s*[,;·–—-]?\s*\)', '', texto)
    texto = re.sub(r'\(\s*[,;]\s*', '(', texto)
    texto = re.sub(r'\s*[–—-]\s*([.,;:!?)])', r'\1', texto)
    texto = re.sub(r'\s*[–—-]\s*$', '', texto, flags=re.MULTILINE)
    texto = re.sub(r'[ \t]{2,}', ' ', texto)
    texto = re.sub(r' +([,.;:)])', r'\1', texto)
    return texto.strip()


AVISO_NO_EJECUTADO = (
    "⚠️ **OJO: esto NO se ejecutó.** El asistente informó un cambio que nunca llegó a la "
    "base de datos (no corrió ninguna operación de escritura en este turno). Volvé a pedirlo "
    "explícitamente y verificá en la pantalla correspondiente antes de darlo por hecho.\n\n"
    "_Respuesta original del asistente:_\n\n"
)


# ============================================================================
# Endpoints Flask
# ============================================================================

@bp.route('/', methods=['GET'])
def chat_page():
    """Pestaña dedicada al chat, a pantalla completa.

    Es el mismo asistente que el widget flotante y comparte el markup
    (`_agente_chat_core.html`) y el JS — lo único que cambia es el contenedor.
    Pensada para el celular, que es donde más se usa: el widget de 380px flotando
    sobre una página que igual scrollea es incómodo en una pantalla chica.
    """
    return render_template('gestion/agente_chat.html', activo='agente')


@bp.route('/chat', methods=['POST'])
def chat():
    """Endpoint para el widget de chat. JSON con 'mensaje' y opcionalmente 'imagen' (base64).
    Mantiene historial + última entidad consultada para mejor contexto."""
    data = request.get_json() or {}
    mensaje_usuario = data.get('mensaje', '').strip()

    if not mensaje_usuario:
        return jsonify({'error': 'Mensaje vacío'}), 400

    # Conversación: sale de gestion.db, no de la cookie (ver _conv_cargar).
    conv = _conv_cargar()
    mensajes = conv['historial'][-HISTORIAL_AL_MODELO:]

    # Si el usuario hace una pregunta relativa sin especificar quién, inyectar referencia anterior
    entidad_actual = conv['entidad_actual']  # Último profesor/recurso consultado
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

    # Obtener respuesta del agente.
    # `fichas_previas` son las fichas de alta que el usuario YA vio en turnos anteriores;
    # sin esto no habría forma de confirmar un alta, porque los resultados de las tools no
    # quedan en el historial y en el turno siguiente el modelo no tiene la ficha a la vista.
    trazas = []
    contexto_turno = {'fichas_previas': dict(conv['fichas'])}
    respuesta = chat_with_tools(mensajes, trazas=trazas, contexto_turno=contexto_turno)
    # Se filtra ANTES de guardar, así el historial repintado tampoco muestra ids.
    respuesta = _ocultar_ids(respuesta)

    # Lo que quedó pendiente de confirmar + lo que se mostró recién.
    fichas = dict(contexto_turno.get('fichas_previas', {}))
    fichas.update(contexto_turno.get('fichas_mostradas', {}))
    fichas = dict(list(fichas.items())[-FICHAS_MAX:])

    # Red de seguridad: si anunció un cambio que no ejecutó, avisarlo (ver comentario
    # en _escritura_no_ejecutada — la regla equivalente en el system prompt no alcanza).
    escritura_fantasma = _escritura_no_ejecutada(respuesta, trazas)
    if escritura_fantasma:
        respuesta = AVISO_NO_EJECUTADO + respuesta

    # Guardar respuesta en el historial (convertir respuesta a formato de mensaje)
    mensajes.append({'role': 'assistant', 'content': [{'type': 'text', 'text': respuesta}]})

    # Actualizar entidad actual si la respuesta menciona un profesor/recurso
    entidad = _extraer_entidad_mencionada(respuesta) or conv['entidad_actual']

    # Se persiste el historial COMPLETO más los dos mensajes de este turno (`mensajes` es
    # solo el recorte que vio el modelo). Las imágenes no se guardan: una foto en base64
    # pesa megas y no se reusa en turnos siguientes — queda una nota en su lugar.
    historial = conv['historial'] + _sin_imagenes(mensajes[-2:])
    _conv_guardar(historial, entidad, fichas)

    # Si quedó una ficha esperando el OK, el front pinta un botón debajo del mensaje en
    # vez de que el usuario tenga que escribir "sí" (ver /confirmar).
    ficha = contexto_turno.get('ultima_ficha')
    confirmacion = None
    if ficha and ficha['token'] in fichas:
        singular = (gestion.ENTIDADES.get(ficha['slug'], {}).get('singular') or 'registro').lower()
        confirmacion = {'token': ficha['token'],
                        'etiqueta': f'Guardar {singular}',
                        'nombre': ficha['nombre']}

    return jsonify({'respuesta': respuesta, 'tools': trazas,
                    'escritura_fantasma': escritura_fantasma,
                    'confirmacion': confirmacion})


def _texto_visible(msg):
    """Texto plano de un mensaje del historial, listo para pintar en el chat.

    Saca el "(refiriéndote a: X)" que `chat()` le agrega al mensaje del usuario: es una
    pista para el modelo, no algo que el usuario haya escrito ni tenga que volver a leer.
    """
    contenido = msg.get('content')
    if isinstance(contenido, str):
        texto = contenido
    else:
        texto = "\n".join(b.get('text', '') for b in (contenido or [])
                          if isinstance(b, dict) and b.get('type') == 'text')
    if msg.get('role') == 'user':
        texto = re.sub(r'\s*\(refiriéndote a:[^)]*\)\s*$', '', texto)
    return texto.strip()


def _confirmacion_pendiente(fichas):
    """Datos del botón de confirmar para la última ficha sin resolver, si quedó alguna."""
    if not fichas:
        return None
    token = list(fichas.keys())[-1]
    pendiente = fichas[token]
    singular = (gestion.ENTIDADES.get(pendiente['slug'], {}).get('singular') or 'registro').lower()
    return {'token': token, 'etiqueta': f'Guardar {singular}',
            'nombre': pendiente['campos'].get('nombre', '')}


@bp.route('/historial', methods=['GET'])
def historial():
    """Conversación guardada, para repintar el chat al cargar la página.

    Desde que la conversación vive en `gestion.db` y no en la cookie, el servidor la
    recuerda pero el chat arrancaba en blanco cada vez que el usuario navegaba a otra
    página de /gestion. Esto la trae de vuelta, junto con el botón de un alta que haya
    quedado sin confirmar (si no, al cambiar de página se perdía la única forma de darle OK).
    """
    conv = _conv_cargar()
    mensajes = [{'rol': m.get('role'), 'texto': _texto_visible(m)} for m in conv['historial']]
    return jsonify({'mensajes': [m for m in mensajes if m['texto']],
                    'confirmacion': _confirmacion_pendiente(conv['fichas'])})


@bp.route('/confirmar', methods=['POST'])
def confirmar():
    """Confirma un alta desde el botón del chat, sin pasar por el modelo.

    El botón manda solo el token de la ficha que el usuario vio; los campos salen de la
    sesión, nunca del request. Así lo que se guarda es literalmente lo que se mostró en
    pantalla, y da igual lo que arme el front. Tampoco hay una llamada al LLM de por
    medio: el alta es determinística y sale gratis.
    """
    token = (request.get_json() or {}).get('token', '')
    conv = _conv_cargar()
    fichas = dict(conv['fichas'])
    pendiente = fichas.get(token)

    if not pendiente:
        # Pasa si se reinició la conversación, si ya se confirmó, o si la ficha quedó
        # desplazada por otras más nuevas (tope FICHAS_MAX).
        return jsonify({'ok': False,
                        'respuesta': 'Esa ficha ya no está pendiente. Pedile al asistente que '
                                     'la vuelva a armar y confirmala de nuevo.'}), 409

    entrada = dict(pendiente['campos'])
    entrada['slug'] = pendiente['slug']
    contexto_turno = {'fichas_previas': fichas}
    resultado = ejecutar_tool('crear_entidad', entrada, contexto_turno)
    # `ejecutar_tool` consumió el token de `fichas` si llegó a escribir.

    if resultado.get('ok'):
        respuesta = f"✅ Guardado: **{pendiente['campos'].get('nombre', '')}**."
    else:
        respuesta = f"No se pudo guardar: {resultado.get('error', 'error desconocido')}"

    # Queda en el historial para que el asistente sepa, en el turno siguiente, que esto
    # ya se guardó y no lo ofrezca de nuevo.
    historial = conv['historial'] + [
        {'role': 'user', 'content': [{'type': 'text', 'text': '(confirmé el alta con el botón)'}]},
        {'role': 'assistant', 'content': [{'type': 'text', 'text': respuesta}]},
    ]
    _conv_guardar(historial, conv['entidad_actual'], fichas)

    return jsonify({'ok': resultado.get('ok', False), 'respuesta': respuesta,
                    'tools': [{'tool': 'crear_entidad', 'ok': resultado.get('ok', False)}]})

@bp.route('/reset', methods=['POST'])
def reset():
    """Borra la conversación: historial, entidad de contexto y fichas sin confirmar."""
    _conv_borrar()
    return jsonify({'ok': True})

@bp.route('/log', methods=['GET'])
def agente_log():
    """Página de auditoría: últimas N entradas del agente_log."""
    con = conectar()
    cur = con.cursor()
    cur.execute("SELECT * FROM agente_log ORDER BY id DESC LIMIT 50")
    filas = [dict(row) for row in cur.fetchall()]
    con.close()

    return render_template('gestion/agente_log.html', filas=filas)
