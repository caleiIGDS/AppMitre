"""Adaptador Flask de las cuatro consultas de lectura. Bearer nunca abre una sesión."""
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
    token_url = request.args.getlist('token')
    if token_url and (request.method not in ('GET', 'HEAD') or len(token_url) != 1):
        return error('parametros_invalidos', 'Usá un solo token y únicamente en consultas GET.', 400)
    if autorizacion is not None or token_url:
        if autorizacion is not None:
            partes = autorizacion.split()
            credencial = partes[1] if len(partes) == 2 and partes[0].lower() == 'bearer' else ''
        else:
            credencial = token_url[0]
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
    respuesta.headers['Referrer-Policy'] = 'no-referrer'
    respuesta.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return respuesta


def parametros_url(operacion):
    """Mismos filtros del JSON: listas como parámetros repetidos, sin partir nombres."""
    propiedades = CONTRATOS[operacion]['entrada']['properties']
    parametros = {}
    for original in request.args:
        if original == 'token':
            continue
        campo = 'valores' if original == 'valor' and operacion == 'horarios' else original
        if campo not in propiedades or campo in parametros:
            raise ErrorConsulta('parametros_invalidos', 'Parámetro desconocido o repetido.', campo=original)
        valores = request.args.getlist(original)
        tipo = propiedades[campo].get('type')
        if tipo == 'array':
            parametros[campo] = valores
            continue
        if len(valores) != 1:
            raise ErrorConsulta('parametros_invalidos', 'El parámetro requiere un único valor.', campo=campo)
        valor = valores[0]
        if tipo == 'integer':
            if not valor.isascii() or not valor.isdecimal() or len(valor) > 9:
                raise ErrorConsulta('parametros_invalidos', 'Se requiere un año entero.', campo=campo)
            valor = int(valor)
        elif tipo == 'boolean':
            if valor not in ('true', 'false'):
                raise ErrorConsulta('parametros_invalidos', 'Usá true o false.', campo=campo)
            valor = valor == 'true'
        parametros[campo] = valor
    return parametros


def consultar(operacion):
    if request.content_length is not None and request.content_length > 16000:
        return error('parametros_invalidos', 'El cuerpo de la consulta excede el límite.', 400)
    try:
        parametros = parametros_url(operacion) if request.method in ('GET', 'HEAD') else request.get_json(silent=True)
        # Cambiar cualquiera de las claves invalida continuaciones previas.
        clave_cursor = acceso.clave_derivada(current_app.secret_key)
        salida = ejecutar(operacion, parametros, datos.DB_PATH, clave_cursor)
        return current_app.response_class(compacto(salida), mimetype='application/json')
    except ErrorConsulta as e:
        return jsonify({'error': e.detalle}), ESTADOS[e.codigo]
    except Exception:
        current_app.logger.exception('No se pudo ejecutar una consulta de Horarios')
        return error('servicio_no_disponible', 'No se pudo completar la consulta.', 503)


for _operacion in CONTRATOS:
    bp_consultas.add_url_rule('/' + _operacion, endpoint=_operacion,
                              view_func=lambda op=_operacion: consultar(op), methods=['GET', 'POST'])


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
        paths[PREFIJO + '/' + op]['get'] = {
            'operationId': contrato['nombre'] + '_url',
            'description': contrato['descripcion'] + ' Listas: repetir el parámetro. Mismas combinaciones que POST.',
            'security': [{'horariosTokenUrl': []}, {'horariosBearer': []}, {'horariosSesion': []}],
            'parameters': [{'in': 'query', 'name': campo,
                            'required': campo in contrato['entrada'].get('required', []),
                            'schema': esquema, 'style': 'form', 'explode': True}
                           for campo, esquema in contrato['entrada']['properties'].items()],
            'responses': respuestas}
    return jsonify({'openapi': '3.1.0', 'info': {'title': 'Consultas de Horarios', 'version': '1.0.0'},
                    'servers': [{'url': request.url_root.rstrip('/')}], 'paths': paths,
                    'security': [{'horariosBearer': []}, {'horariosSesion': []}],
                    'components': {'securitySchemes': {
                        'horariosTokenUrl': {'type': 'apiKey', 'in': 'query', 'name': 'token',
                                             'description': 'La misma clave de Horarios, solo para GET.'},
                        'horariosBearer': {'type': 'http', 'scheme': 'bearer',
                                           'description': 'HORARIOS_CLAVE, configurada como secreto de la integración.'},
                        'horariosSesion': {'type': 'apiKey', 'in': 'cookie',
                                           'name': current_app.config['SESSION_COOKIE_NAME']}}}})
