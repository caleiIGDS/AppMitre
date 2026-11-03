"""Adaptador Flask de las cuatro consultas de lectura. Bearer nunca abre una sesión."""
import hashlib
import hmac
from flask import Blueprint, current_app, jsonify, request

from . import acceso, datos
from .consultas import CONTRATOS, ErrorConsulta, ejecutar
from .consultas.comun import compacto, MAX_CARACTERES, MAX_ENTIDADES, MAX_PERSONAS, MAX_PRECEPTORES
from .consultas.contratos import ERROR

PREFIJO = '/app-horarios/api/v1/consultas'
bp_consultas = Blueprint('consultas', __name__, url_prefix='/v1/consultas')
ESTADOS = {'parametros_invalidos': 400, 'no_encontrado': 404, 'persona_ambigua': 409,
           'consulta_vencida': 409, 'consulta_demasiado_amplia': 422,
           'datos_no_disponibles': 503, 'datos_inconsistentes': 422, 'servicio_no_disponible': 503}


def error(codigo, mensaje, estado):
    return jsonify({'error': {'codigo': codigo, 'mensaje': mensaje}}), estado


@bp_consultas.before_request
def autenticar():
    autorizacion = request.headers.get('Authorization')
    if autorizacion is not None:
        partes = autorizacion.split()
        credencial = partes[1] if len(partes) == 2 and partes[0].lower() == 'bearer' else ''
        resultado = acceso.verificar_clave(request.remote_addr, credencial)
        if resultado == 'bloqueado':
            return error('demasiados_intentos', 'Demasiados intentos; esperá 15 minutos.', 429)
        if resultado != 'ok':
            return error('no_autenticado', 'Credencial de Horarios inválida.', 401)
        return None
    if not acceso.autenticado():
        return error('no_autenticado', 'Hace falta la clave de Horarios.', 401)
    if request.method not in ('GET', 'HEAD') and not request.headers.get('X-Mitre'):
        return error('no_permitido', 'La sesión requiere la cabecera X-Mitre.', 403)


@bp_consultas.after_request
def privada(respuesta):
    respuesta.headers['Cache-Control'] = 'no-store'
    respuesta.headers['Vary'] = 'Authorization, Cookie'
    return respuesta


def consultar(operacion):
    if request.content_length is not None and request.content_length > 16000:
        return error('parametros_invalidos', 'El cuerpo de la consulta excede el límite.', 400)
    parametros = request.get_json(silent=True)
    try:
        # Cambiar cualquiera de las claves invalida continuaciones previas.
        secreto = current_app.secret_key
        if isinstance(secreto, str):
            secreto = secreto.encode('utf-8')
        clave_cursor = hmac.new(secreto, acceso._clave().encode('utf-8'), hashlib.sha256).digest()
        salida = ejecutar(operacion, parametros, datos.DB_PATH, clave_cursor)
        return current_app.response_class(compacto(salida), mimetype='application/json')
    except ErrorConsulta as e:
        return jsonify({'error': e.detalle}), ESTADOS[e.codigo]
    except Exception:
        current_app.logger.exception('No se pudo ejecutar una consulta de Horarios')
        return error('servicio_no_disponible', 'No se pudo completar la consulta.', 503)


for _operacion in CONTRATOS:
    bp_consultas.add_url_rule('/' + _operacion, endpoint=_operacion,
                              view_func=lambda op=_operacion: consultar(op), methods=['POST'])


@bp_consultas.get('/contratos')
def contratos():
    return jsonify({'version': '1', 'limites': {'caracteres': MAX_CARACTERES,
                    'entidades': MAX_ENTIDADES, 'personas': MAX_PERSONAS, 'preceptores': MAX_PRECEPTORES},
                    'herramientas': [{'ruta': PREFIJO + '/' + op, **contrato}
                                     for op, contrato in CONTRATOS.items()]})


@bp_consultas.get('/openapi.json')
def openapi():
    paths = {}
    for op, contrato in CONTRATOS.items():
        respuestas = {'200': {'description': 'Resultado; consumir siguiente si aparece.',
                              'content': {'application/json': {'schema': contrato['salida']}}}}
        for estado in (400, 401, 403, 404, 409, 422, 429, 503):
            respuestas[str(estado)] = {'description': 'Error estructurado.',
                                      'content': {'application/json': {'schema': ERROR}}}
        paths[PREFIJO + '/' + op] = {'post': {
            'operationId': contrato['nombre'], 'description': contrato['descripcion'],
            'x-openai-isConsequential': False,
            'parameters': [{'in': 'header', 'name': 'X-Mitre', 'required': False,
                            'description': 'Requerida si se autentica mediante cookie de sesión.',
                            'schema': {'type': 'string'}}],
            'requestBody': {'required': True, 'content': {'application/json': {'schema': contrato['entrada']}}},
            'responses': respuestas}}
    return jsonify({'openapi': '3.1.0', 'info': {'title': 'Consultas de Horarios', 'version': '1.0.0'},
                    'servers': [{'url': request.url_root.rstrip('/')}], 'paths': paths,
                    'security': [{'horariosBearer': []}, {'horariosSesion': []}],
                    'components': {'securitySchemes': {
                        'horariosBearer': {'type': 'http', 'scheme': 'bearer',
                                           'description': 'HORARIOS_CLAVE, configurada como secreto de la integración.'},
                        'horariosSesion': {'type': 'apiKey', 'in': 'cookie',
                                           'name': current_app.config['SESSION_COOKIE_NAME']}}}})
