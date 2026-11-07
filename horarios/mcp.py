"""MCP Streamable HTTP, modo JSON sin sesiones, sobre WSGI/Flask.

Subconjunto de lectura de la especificación 2025-11-25: initialize, ping y tools.
No ofrece SSE, tareas ni notificaciones del servidor. No precisa otro proceso.
Los contratos escolares son los mismos de la API; OAuth conserva el acceso en el
cliente. La clave por llamada se acepta solo para clientes anteriores.
"""
from copy import deepcopy
from urllib.parse import urlsplit

from flask import Blueprint, abort, current_app, jsonify, request
from itsdangerous import BadData

from . import acceso, datos, oauth, pdf_agentes
from .consultas import CONTRATOS, ErrorConsulta, ejecutar
from .consultas.comun import compacto
from .consultas.contratos import TEXTO, objeto, validar

bp_mcp = Blueprint('horarios_mcp', __name__)
VERSIONES = ('2025-03-26', '2025-06-18', '2025-11-25')
INSTRUCCIONES = (
    'Horarios de la EEST N.º 4 Emilio Mitre, secundaria técnica. Consultas de solo lectura. '
    'Usá la conexión OAuth; si necesita acceso, indicá conectar AppMitre. No pidas la contraseña en el chat. '
    'consulta lleva los filtros; {} pide los valores por defecto. JSON de la última copia semanal, '
    'sin confirmar asistencia ni feriados. Conservá grupos A/B, cargos múltiples, suplencias y anomalías. '
    'No deduzcas disponibilidad o presencia en huecos ni unas recreos. PROGRESO es una cancha a dos cuadras, '
    'fuera del edificio. Comparar días e intervalos es tarea del agente, usando código si hace falta. '
    'Si siguiente está presente, continuá con los mismos filtros y cursor antes de afirmar que un listado '
    'está completo; para ejemplos alcanzan los pedidos. Para varios cargos usá multiples_roles=true. '
    'Si no identificás un cargo/persona, listar_catalogos con incluir=[roles] o [nombres] permite revisar '
    'equivalencias; preguntá si hay ambigüedad. obtener_pdf entrega una referencia de archivo y un enlace '
    'descargable. Compartí el enlace exacto como Markdown, sin reconstruirlo. resources/read permite '
    'leer el PDF desde el MCP si el cliente no puede descargarlo por HTTP.'
)
OPERACIONES = {c['nombre']: op for op, c in CONTRATOS.items()}
CLAVE = {**TEXTO, 'maxLength': 4096, 'description': 'La contraseña de Horarios proporcionada por el usuario. No mostrarla.'}
PARAMETROS_LLAMADA = objeto({'name': TEXTO, 'arguments': {'type': 'object'}, '_meta': {'type': 'object'}}, ('name',))


def herramienta(n, descripcion, entrada, salida):
    return {'name': n, 'description': descripcion,
            'inputSchema': objeto({'consulta': deepcopy(entrada)}, ('consulta',)),
            'outputSchema': {'type': 'object', **deepcopy(salida)},
            'securitySchemes': [{'type': 'oauth2', 'scopes': [oauth.SCOPE]}],
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
    contenido = [{'type': 'text', 'text': compacto(salida)}]
    if not error and salida.get('mime_type') == 'application/pdf':
        contenido.append({'type': 'resource_link', 'uri': salida['url'], 'name': salida['nombre'],
                          'mimeType': 'application/pdf', 'description': 'Calendario PDF descargable.'})
    return {'content': contenido,
            'structuredContent': salida, 'isError': error}


def llamar(p):
    validar(p, PARAMETROS_LLAMADA)
    n = p['name']
    op = OPERACIONES.get(n)
    if op is None and n != 'obtener_pdf':
        raise ErrorConsulta('parametros_invalidos', 'Herramienta desconocida.')
    argumentos = p.get('arguments', {})
    clave = argumentos.get('clave')
    # OAuth se comprueba antes de entrar. Compatibilidad con llamadas antiguas.
    resultado = 'ok' if oauth.autorizado() else acceso.verificar_clave(request.remote_addr, clave)
    if resultado != 'ok':
        codigo = 'demasiados_intentos' if resultado == 'bloqueado' else 'no_autenticado'
        mensaje = 'Esperá 15 minutos antes de reintentar.' if resultado == 'bloqueado' else 'Hace falta la contraseña de Horarios correcta.'
        raise ErrorConsulta(codigo, mensaje)
    entrada = pdf_agentes.ENTRADA if n == 'obtener_pdf' else CONTRATOS[op]['entrada']
    # Nombre del campo, nunca su contenido, es lo único que aparece en errores de validación.
    validar(argumentos, objeto({'clave': CLAVE, 'consulta': entrada}, ('consulta',)))
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
    if request.path.startswith('/horarios/oauth/authorize'):
        # El formulario nativo necesita conservar Origin al enviar el POST.
        r.headers['Referrer-Policy'] = 'same-origin'
        r.headers['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
        r.headers['X-Frame-Options'] = 'DENY'
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
    # Un Bearer vencido siempre provoca reautorización; no cae a otra credencial.
    if request.headers.get('Authorization') and not oauth.autorizado():
        return oauth.desafio()
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
    argumentos = params.get('arguments', {})
    legado = (metodo == 'tools/call' and isinstance(argumentos, dict) and 'clave' in argumentos)
    if metodo in ('tools/call', 'resources/read') and not legado and not oauth.autorizado():
        return oauth.desafio()
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
                             'capabilities': {'tools': {'listChanged': False}, 'resources': {'listChanged': False}},
                             'serverInfo': {'name': 'appmitre-horarios', 'version': '1.1.0'},
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
    if metodo in ('resources/list', 'resources/templates/list'):
        return respuesta(i, {'resources' if metodo == 'resources/list' else 'resourceTemplates': []})
    if metodo == 'resources/read':
        try:
            return respuesta(i, {'contents': [pdf_agentes.leer_recurso(params.get('uri'))]})
        except (BadData, ErrorConsulta, ValueError):
            return respuesta(i, codigo=-32002, mensaje='PDF desconocido o vencido. Pedí otro con obtener_pdf.')
    return respuesta(i, codigo=-32601, mensaje='Método no disponible.')


@bp_mcp.get('/horarios/mcp-pdf/<referencia>')
@bp_mcp.get('/horarios/mcp-pdf/<referencia>/<nombre>')
def descargar_pdf(referencia, nombre=None):
    try:
        parametros = pdf_agentes.firmador().loads(referencia, max_age=pdf_agentes.VIGENCIA)
    except BadData:
        abort(403, description='El enlace PDF venció o no es válido. Pedí otro al asistente.')
    if nombre is not None and nombre != pdf_agentes.nombre_archivo(parametros):
        abort(403)
    r = pdf_agentes.descargar(parametros)
    r.headers.set('Content-Disposition', 'attachment', filename=pdf_agentes.nombre_archivo(parametros))
    return r


oauth.registrar(bp_mcp)
