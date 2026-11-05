"""Entrega campos a una pestaña autorizada. El legajo se guarda desde el formulario."""
from contextlib import closing, contextmanager
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import secrets
import sqlite3
import time
from urllib.parse import urlsplit

from flask import Blueprint, abort, jsonify, request, url_for

import accesos
from config import ahora
import salidas


bp = Blueprint('salidas_mcp', __name__)
VERSIONES = ('2025-03-26', '2025-06-18', '2025-11-25')
VIGENCIA = 600
MAX_BYTES = 96 * 1024
ANEXOS = ('I', 'II', *salidas.ANEXOS_NUMEROS)
TIPOS = {'text', 'textarea', 'date', 'time', 'select', 'bool', 'number', 'personas', 'telefonos'}
ROLES = ('estudiante', 'docente_titular', 'docente_reemplazante', 'no_docente')
INSTRUCCIONES = (
    'Salidas Educativas de la Técnica Emilio Mitre. Consultá los anexos I y II para los requisitos '
    'y plazos, y los anexos III a IX para cada formulario. Para rellenar, la persona abre Editar '
    'en una salida existente y genera un código en Rellenar con agente. Consultá los campos de esa '
    'pestaña y enviá solo datos aportados o confirmados por la persona. No inventes datos, firmas, '
    'autorizaciones, declaraciones ni constancias. El envío deja campos listos para revisar en la '
    'pestaña. Solo la persona puede aplicarlos y guardar desde AppMitre.'
)


def _huella(valor):
    return hashlib.sha256(valor.encode('utf-8')).hexdigest()


def _secreto(valor):
    return isinstance(valor, str) and re.fullmatch(r'[A-Za-z0-9_-]{32}', valor)


def _activa(id):
    with closing(salidas.conectar()) as con:
        return con.execute(
            'SELECT 1 FROM salidas WHERE id = ? AND archivado = 0 AND vigencia_hasta > ?',
            (id, ahora().isoformat())).fetchone() is not None


@contextmanager
def _entregas():
    # Fuera de salidas.db para que las propuestas nunca entren en sus respaldos.
    ruta = Path(salidas.DB_PATH).with_name('salidas_entregas_mcp.db')
    with closing(sqlite3.connect(ruta, timeout=10)) as con, con:
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA secure_delete = ON')
        con.execute('''CREATE TABLE IF NOT EXISTS entregas (
            codigo TEXT PRIMARY KEY, receptor TEXT UNIQUE NOT NULL, salida INTEGER NOT NULL,
            vence REAL NOT NULL, campos TEXT NOT NULL, valores TEXT)''')
        con.execute('BEGIN IMMEDIATE')
        con.execute('DELETE FROM entregas WHERE vence <= ?', (time.time(),))
        yield con


def _json_limitado():
    if not request.is_json:
        abort(415)
    cuerpo = request.stream.read(MAX_BYTES + 1)
    if len(cuerpo) > MAX_BYTES:
        abort(413)
    try:
        return json.loads(cuerpo)
    except (ValueError, RecursionError):
        abort(400)


def _campos_validos(campos):
    if not isinstance(campos, dict) or not 1 <= len(campos) <= 160:
        return False
    for clave, campo in campos.items():
        if not (clave == 'personas' or re.fullmatch(r'(?:comunes|III|IV|V|VI|VII|VIII|IX)\.[a-z0-9_]{1,80}', clave)):
            return False
        if not isinstance(campo, dict) or set(campo) - {'tipo', 'label', 'opciones'}:
            return False
        tipo, label = campo.get('tipo'), campo.get('label')
        if not isinstance(tipo, str) or tipo not in TIPOS or not isinstance(label, str) or len(label) > 250:
            return False
        if (clave == 'personas') != (tipo == 'personas'):
            return False
        if tipo == 'select':
            opciones = campo.get('opciones')
            if not isinstance(opciones, list) or not 1 <= len(opciones) <= 20 or not all(
                    isinstance(v, str) and 0 < len(v) <= 100 for v in opciones):
                return False
        elif 'opciones' in campo:
            return False
    return True


def _texto(v, limite=12000):
    return isinstance(v, str) and 0 < len(v) <= limite and bool(v.strip()) and '\x00' not in v


def _fecha(v):
    if not isinstance(v, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', v):
        return False
    try:
        date.fromisoformat(v)
    except ValueError:
        return False
    return True


def _persona(p):
    return (isinstance(p, dict) and not set(p) - {
                'rol', 'apellido_nombre', 'documento', 'cargo', 'fecha_nacimiento'}
            and p.get('rol') in ROLES and _texto(p.get('apellido_nombre'), 200)
            and all(_texto(p[k], 200) for k in ('documento', 'cargo') if k in p)
            and ('fecha_nacimiento' not in p or _fecha(p['fecha_nacimiento'])))


def _valor_valido(campo, valor):
    tipo = campo['tipo']
    if tipo == 'personas':
        return isinstance(valor, list) and 1 <= len(valor) <= 300 and all(map(_persona, valor))
    if tipo == 'telefonos':
        return isinstance(valor, dict) and 1 <= len(valor) <= 100 and all(
            _texto(nombre, 200) and _texto(telefono, 100) for nombre, telefono in valor.items())
    if tipo == 'bool':
        return type(valor) is bool
    if tipo == 'date':
        return _fecha(valor)
    if tipo == 'time':
        return isinstance(valor, str) and bool(re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', valor))
    if tipo == 'select':
        return valor in campo['opciones']
    if tipo == 'number':
        return type(valor) is int and 0 <= valor <= 100000
    return _texto(valor)


@salidas.bp.post('/<int:id>/agente-formulario')
@accesos.requiere(salidas.PERMISO_ESCRITURA, como_json=True)
def agente_formulario(id):
    if request.headers.get('X-Mitre') != '1':
        abort(400)
    if not _activa(id):
        abort(404)
    datos = _json_limitado()
    if not isinstance(datos, dict):
        abort(400)
    r = _operacion_pestana(id, datos)
    r.headers['Cache-Control'] = 'no-store'
    return r


def _operacion_pestana(id, datos):
    if set(datos) == {'campos'} and _campos_validos(datos['campos']):
        codigo, receptor = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        with _entregas() as con:
            con.execute('INSERT INTO entregas VALUES (?,?,?,?,?,NULL)',
                        (_huella(codigo), _huella(receptor), id, time.time() + VIGENCIA,
                         json.dumps(datos['campos'])))
        return jsonify(codigo=codigo, receptor=receptor, vence_en=VIGENCIA)
    if set(datos) != {'receptor', 'accion'} or not _secreto(datos['receptor']):
        abort(400)
    receptor = _huella(datos['receptor'])
    accion = datos['accion']
    if accion not in ('recibir', 'cancelar'):
        abort(400)
    with _entregas() as con:
        entrega = con.execute('SELECT valores FROM entregas WHERE receptor=? AND salida=?',
                              (receptor, id)).fetchone()
        if entrega is None:
            return jsonify(estado='vencido')
        if accion == 'recibir' and entrega['valores'] is None:
            return jsonify(estado='esperando')
        con.execute('DELETE FROM entregas WHERE receptor=?', (receptor,))
        if accion == 'cancelar':
            return jsonify(estado='cancelado')
        return jsonify(estado='recibido', valores=json.loads(entrega['valores']))


def _objeto(propiedades):
    return {'type': 'object', 'properties': propiedades, 'required': list(propiedades),
            'additionalProperties': False}


def _tool(nombre, descripcion, propiedades, lectura=True):
    return {'name': nombre, 'description': descripcion, 'inputSchema': _objeto(propiedades),
            'annotations': {'readOnlyHint': lectura, 'destructiveHint': False,
                            'idempotentHint': lectura, 'openWorldHint': False}}


CODIGO = {'type': 'string', 'description': 'Código temporal que muestra la pestaña de edición.'}
TOOLS = [
    _tool('listar_anexos', 'Lista los Anexos I a IX y las referencias de Salidas Educativas.', {}),
    _tool('leer_anexo', 'Lee el instructivo (I), los plazos (II) o un formulario oficial (III a IX).',
          {'anexo': {'type': 'string', 'enum': ANEXOS}}),
    _tool('consultar_campos', 'Consulta los campos disponibles en la pestaña autorizada por el código. '
          'Devuelve tipos y opciones, sin valores guardados.', {'codigo': CODIGO}),
    _tool('rellenar_formulario', 'Envía una única propuesta de campos a la pestaña autorizada. '
          'Usá consultar_campos primero. Las fechas van AAAA-MM-DD y las horas HH:MM. '
          'Para personas, enviá una lista con rol, apellido_nombre y los datos opcionales confirmados '
          'documento, cargo y fecha_nacimiento. Para teléfonos de acompañantes, usá un objeto nombre a teléfono.',
          {'codigo': CODIGO, 'campos': {'type': 'object', 'additionalProperties': True}}, lectura=False),
]


def _referencias():
    return {
        'resolucion': url_for('normativa_visor', _external=True),
        'resolucion_pdf': url_for('static', filename='salidas/resolucion-3871-24.pdf', _external=True),
        'instructivo': url_for('salidas.instructivo', _external=True),
    }


def _llamar(nombre, args):
    if nombre == 'listar_anexos' and not args:
        titulos = {'I': 'Requisitos e instructivo', 'II': 'Plazos y responsables'}
        titulos.update({anexo: salidas._cargar_schema(anexo)['titulo'] for anexo in ANEXOS[2:]})
        return {'anexos': [{'anexo': n, 'titulo': titulos[n]} for n in ANEXOS],
                'referencias': _referencias()}
    if nombre == 'leer_anexo' and set(args) == {'anexo'} and args['anexo'] in ANEXOS:
        anexo = args['anexo']
        ruta = Path(salidas.ANEXOS_JSON_DIR) / f'Anexo{ANEXOS.index(anexo) + 1}.md'
        r = {'anexo': anexo, 'formulario': ruta.read_text(encoding='utf-8'), 'referencias': _referencias()}
        if anexo in salidas.ANEXOS_NUMEROS:
            r['esquema_papel'] = salidas._cargar_schema(anexo)
        return r
    if nombre not in ('consultar_campos', 'rellenar_formulario'):
        raise ValueError('Herramienta o argumentos inválidos.')
    escritura = nombre == 'rellenar_formulario'
    if set(args) != ({'codigo', 'campos'} if escritura else {'codigo'}) or not _secreto(args.get('codigo')):
        raise ValueError('Se requiere el código temporal y los argumentos de la herramienta.')
    codigo = _huella(args['codigo'])
    with _entregas() as con:
        entrega = con.execute('SELECT * FROM entregas WHERE codigo=?', (codigo,)).fetchone()
        if entrega is None or entrega['valores'] is not None or not _activa(entrega['salida']):
            return {'error': 'Código inválido, vencido o ya utilizado. Pedí otro en la salida abierta.'}
        campos = json.loads(entrega['campos'])
        if not escritura:
            return {'campos': campos, 'roles_personas': ROLES}
        valores = args['campos']
        if not isinstance(valores, dict) or not valores:
            return {'error': 'Enviá al menos un campo.'}
        invalidos = [k for k, v in valores.items() if k not in campos or not _valor_valido(campos[k], v)]
        if invalidos:
            return {'error': 'Hay campos no disponibles o con valores inválidos.', 'campos_invalidos': invalidos}
        con.execute('UPDATE entregas SET valores=? WHERE codigo=?', (json.dumps(valores), codigo))
        return {'estado': 'enviado_para_revision', 'campos_enviados': len(valores)}


@bp.before_request
def _proteger():
    origin = request.headers.get('Origin')
    if origin and (origin not in {request.host_url.rstrip('/'), 'https://chatgpt.com', 'https://claude.ai'}
                   or urlsplit(origin).path):
        abort(403)


@bp.after_request
def _privada(r):
    r.headers['Cache-Control'] = 'no-store'
    r.headers['Referrer-Policy'] = 'no-referrer'
    return r


@bp.route('/mcp/salidas', methods=['GET', 'POST', 'DELETE'], strict_slashes=False)
def endpoint():
    if request.method != 'POST':
        return '', 405, {'Allow': 'POST'}
    if request.headers.get('Accept') and not request.accept_mimetypes['application/json']:
        abort(406)
    p = _json_limitado()
    i = p.get('id') if isinstance(p, dict) else None

    def responder(resultado=None, error=None):
        respuesta = {'jsonrpc': '2.0', 'id': i}
        if error:
            respuesta['error'] = {'code': error[0], 'message': error[1]}
        else:
            respuesta['result'] = resultado
        return jsonify(respuesta)

    version = request.headers.get('MCP-Protocol-Version')
    if version and version not in VERSIONES:
        return responder(error=(-32600, 'Versión MCP no admitida.')), 400
    if (not isinstance(p, dict) or p.get('jsonrpc') != '2.0' or not isinstance(p.get('method'), str)
            or not isinstance(p.get('params', {}), dict) or ('id' in p and type(i) not in (int, str))):
        return responder(error=(-32600, 'Mensaje JSON-RPC no válido.')), 400
    metodo, params = p['method'], p.get('params', {})
    if 'id' not in p:
        return ('', 202) if metodo.startswith('notifications/') else (
            responder(error=(-32600, 'La petición requiere id.')), 400)
    if metodo == 'initialize':
        solicitada = params.get('protocolVersion')
        return responder({'protocolVersion': solicitada if solicitada in VERSIONES else VERSIONES[-1],
                          'capabilities': {'tools': {'listChanged': False}},
                          'serverInfo': {'name': 'appmitre-salidas', 'version': '1.0.0'},
                          'instructions': INSTRUCCIONES})
    if metodo == 'ping':
        return responder({})
    if metodo == 'tools/list':
        return responder({'tools': TOOLS})
    if metodo != 'tools/call':
        return responder(error=(-32601, 'Método no disponible.'))
    args = params.get('arguments', {})
    if not isinstance(args, dict) or not isinstance(params.get('name'), str):
        return responder(error=(-32602, 'Argumentos no válidos.'))
    try:
        salida = _llamar(params['name'], args)
    except ValueError as error:
        salida = {'error': str(error)}
    return responder({'content': [{'type': 'text', 'text': json.dumps(salida, ensure_ascii=False)}],
                      'structuredContent': salida, 'isError': 'error' in salida})
