"""MCP Streamable HTTP, modo JSON sin sesiones, sobre WSGI/Flask.

Subconjunto de lectura de la especificación 2025-11-25: initialize, ping y tools.
No ofrece SSE, tareas ni notificaciones del servidor. No precisa otro proceso.
Los contratos escolares son los mismos de la API; la contraseña es un argumento
de cada herramienta y nunca aparece en descubrimiento ni en enlaces de descarga.
"""
from copy import deepcopy
from urllib.parse import urlsplit

from flask import Blueprint, abort, current_app, jsonify, request
from itsdangerous import BadData

from . import acceso, datos, pdf_agentes
from .consultas import CONTRATOS, ErrorConsulta, ejecutar
from .consultas.comun import compacto
from .consultas.contratos import TEXTO, objeto, validar

bp_mcp = Blueprint('horarios_mcp', __name__)
VERSIONES = ('2025-03-26', '2025-06-18', '2025-11-25')
INSTRUCCIONES = (
    'Horarios de la EEST N.º 4 Emilio Mitre, secundaria técnica. Consultas de solo lectura. '
    'Pedí la contraseña de Horarios si no la tenés y usala en clave en cada herramienta; no la repitas. '
    'consulta lleva los filtros; {} pide los valores por defecto. JSON de la última copia semanal, '
    'sin confirmar asistencia ni feriados. Conservá grupos A/B, cargos múltiples, suplencias y anomalías. '
    'No deduzcas disponibilidad o presencia en huecos ni unas recreos. PROGRESO es una cancha a dos cuadras, '
    'fuera del edificio. Comparar días e intervalos es tarea del agente, usando código si hace falta. '
    'Si siguiente está presente, continuá con los mismos filtros y cursor antes de afirmar que un listado '
    'está completo; para ejemplos alcanzan los pedidos. Para varios cargos usá multiples_roles=true. '
    'Si no identificás un cargo/persona, listar_catalogos con incluir=[roles] o [nombres] permite revisar '
    'equivalencias; preguntá si hay ambigüedad. obtener_pdf da un enlace temporal descargable.'
)
OPERACIONES = {c['nombre']: op for op, c in CONTRATOS.items()}
CLAVE = {**TEXTO, 'maxLength': 4096, 'description': 'La contraseña de Horarios proporcionada por el usuario. No mostrarla.'}
PARAMETROS_LLAMADA = objeto({'name': TEXTO, 'arguments': {'type': 'object'}, '_meta': {'type': 'object'}}, ('name',))


def herramienta(n, descripcion, entrada, salida):
    return {'name': n, 'description': descripcion,
            'inputSchema': objeto({'clave': deepcopy(CLAVE), 'consulta': deepcopy(entrada)}, ('clave', 'consulta')),
            'outputSchema': {'type': 'object', **deepcopy(salida)},
            'annotations': {'readOnlyHint': True, 'destructiveHint': False,
                            'idempotentHint': True, 'openWorldHint': False}}


def herramientas():
    return [herramienta(c['nombre'], c['descripcion'], c['entrada'], c['salida']) for c in CONTRATOS.values()] + [
        herramienta('obtener_pdf', pdf_agentes.DESCRIPCION, pdf_agentes.ENTRADA, pdf_agentes.SALIDA)]


def respuesta(i, resultado=None, codigo=None, mensaje=None, estado=200):
    contenido = {'jsonrpc': '2.0', 'id': i}
    if codigo is not None:
        contenido['error'] = {'code': codigo, 'message': mensaje}
    else:
        contenido['result'] = resultado
    return current_app.response_class(compacto(contenido), status=estado, mimetype='application/json')


def resultado_tool(salida, error=False):
    return {'content': [{'type': 'text', 'text': compacto(salida)}],
            'structuredContent': salida, 'isError': error}


def llamar(p):
    validar(p, PARAMETROS_LLAMADA)
    n = p['name']
    op = OPERACIONES.get(n)
    if op is None and n != 'obtener_pdf':
        raise ErrorConsulta('parametros_invalidos', 'Herramienta desconocida.')
    argumentos = p.get('arguments', {})
    clave = argumentos.get('clave')
    # Se autentica antes de leer cualquier dato. No se acepta la cookie de la app.
    resultado = acceso.verificar_clave(request.remote_addr, clave)
    if resultado != 'ok':
        codigo = 'demasiados_intentos' if resultado == 'bloqueado' else 'no_autenticado'
        mensaje = 'Esperá 15 minutos antes de reintentar.' if resultado == 'bloqueado' else 'Hace falta la contraseña de Horarios correcta.'
        raise ErrorConsulta(codigo, mensaje)
    entrada = pdf_agentes.ENTRADA if n == 'obtener_pdf' else CONTRATOS[op]['entrada']
    # Nombre del campo, nunca su contenido, es lo único que aparece en errores de validación.
    validar(argumentos, objeto({'clave': CLAVE, 'consulta': entrada}, ('clave', 'consulta')))
    consulta = argumentos['consulta']
    if n == 'obtener_pdf':
        return pdf_agentes.obtener(consulta)
    return ejecutar(op, consulta, datos.DB_PATH, acceso.clave_derivada(current_app.secret_key))


@bp_mcp.before_request
def proteger():
    origin = request.headers.get('Origin')
    if origin:
        # Los clientes remotos no suelen enviar Origin; lectores de navegador sí.
        permitidos = {request.host_url.rstrip('/'), 'https://chatgpt.com', 'https://claude.ai'}
        if origin not in permitidos or urlsplit(origin).path:
            abort(403)
    if request.endpoint == 'horarios_mcp.endpoint':
        version = request.headers.get('MCP-Protocol-Version')
        if version and version not in VERSIONES:
            return respuesta(None, codigo=-32600, mensaje='Versión MCP no admitida.', estado=400)


@bp_mcp.after_request
def privada(r):
    r.headers['Cache-Control'] = 'no-store'
    r.headers['Referrer-Policy'] = 'no-referrer'
    r.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return r


@bp_mcp.route('/mcp', methods=['GET', 'POST', 'DELETE'], strict_slashes=False)
def endpoint():
    if request.method != 'POST':
        # Streamable HTTP permite 405 para GET cuando no se ofrece SSE.
        return '', 405, {'Allow': 'POST'}
    if not request.is_json:
        return respuesta(None, codigo=-32600, mensaje='Se requiere application/json.', estado=415)
    if not request.accept_mimetypes['application/json']:
        return respuesta(None, codigo=-32600, mensaje='El cliente debe aceptar application/json.', estado=406)
    # Leer con límite aunque no haya Content-Length (por ejemplo, transferencia chunked).
    cuerpo = request.stream.read(65537)
    if len(cuerpo) > 65536:
        return respuesta(None, codigo=-32600, mensaje='Pedido demasiado grande.', estado=413)
    import json
    try:
        p = json.loads(cuerpo)
    except (ValueError, UnicodeError):
        return respuesta(None, codigo=-32700, mensaje='JSON no válido.', estado=400)
    if (not isinstance(p, dict) or p.get('jsonrpc') != '2.0'
            or not isinstance(p.get('method'), str)
            or ('id' in p and type(p['id']) not in (int, str))
            or not isinstance(p.get('params', {}), dict)):
        return respuesta(None, codigo=-32600, mensaje='Mensaje JSON-RPC no válido.', estado=400)
    i, metodo, params = p.get('id'), p['method'], p.get('params', {})
    if 'id' not in p:
        if metodo.startswith('notifications/'):
            return '', 202
        return respuesta(None, codigo=-32600, mensaje='La petición requiere id.', estado=400)
    if metodo == 'initialize':
        if (not isinstance(params.get('protocolVersion'), str)
                or not isinstance(params.get('capabilities'), dict)
                or not isinstance(params.get('clientInfo'), dict)):
            return respuesta(i, codigo=-32602, mensaje='Inicialización no válida.')
        version = params['protocolVersion']
        return respuesta(i, {'protocolVersion': version if version in VERSIONES else VERSIONES[-1],
                             'capabilities': {'tools': {'listChanged': False}},
                             'serverInfo': {'name': 'appmitre-horarios', 'version': '1.0.0'},
                             'instructions': INSTRUCCIONES})
    if metodo == 'ping':
        return respuesta(i, {})
    if metodo == 'tools/list':
        if params.get('cursor'):
            return respuesta(i, codigo=-32602, mensaje='La lista de herramientas no está paginada.')
        return respuesta(i, {'tools': herramientas()})
    if metodo == 'tools/call':
        try:
            return respuesta(i, resultado_tool(llamar(params)))
        except ErrorConsulta as e:
            return respuesta(i, resultado_tool({'error': e.detalle}, error=True))
        except Exception:
            # No registrar cuerpos, argumentos ni tracebacks que puedan contener la clave.
            current_app.logger.error('Falló una consulta MCP de Horarios.')
            return respuesta(i, resultado_tool({'error': {'codigo': 'servicio_no_disponible',
                                            'mensaje': 'No se pudo completar la consulta.'}}, error=True))
    return respuesta(i, codigo=-32601, mensaje='Método no disponible.')


@bp_mcp.get('/horarios/mcp-pdf/<referencia>')
def descargar_pdf(referencia):
    try:
        parametros = pdf_agentes.firmador().loads(referencia, max_age=pdf_agentes.VIGENCIA)
    except BadData:
        abort(403, description='El enlace PDF venció o no es válido. Pedí otro al asistente.')
    return pdf_agentes.descargar(parametros)
