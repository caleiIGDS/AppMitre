"""Registro único de contratos JSON Schema y validación del subconjunto utilizado."""
import re

from .comun import DIAS, ErrorConsulta


def objeto(propiedades, requeridos=()):
    return {'type': 'object', 'properties': propiedades, 'required': list(requeridos),
            'additionalProperties': False}


TEXTO = {'type': 'string', 'minLength': 1, 'maxLength': 200, 'pattern': r'\S'}
NULO_TEXTO = {'anyOf': [TEXTO, {'type': 'null'}]}
ANIO = {'type': 'integer', 'minimum': 1}
HORA = {'type': 'string', 'pattern': r'^(?:[01]\d|2[0-3]):[0-5]\d$|^24:00$'}
DIA = {'type': 'string', 'enum': list(DIAS)}
TURNO = {'type': 'string', 'enum': ['mañana', 'tarde', 'vespertino']}
FUNCION = {'type': ['string', 'null'], 'enum': ['principal', 'contraturno', None]}
TIPO_MATERIA = {'enum': ['te', 'ct', 'fg', None]}
CUPO_MATERIA = objeto({
    'curso': TEXTO, 'grupo': NULO_TEXTO, 'materia': TEXTO,
    'tipo_materia': TIPO_MATERIA, 'especialidad': NULO_TEXTO, 'profesor': NULO_TEXTO,
    'titular_en_licencia': NULO_TEXTO,
    'minutos_semanales': {'type': 'integer', 'minimum': 0},
    'bloques_sin_duracion': {'type': 'integer', 'minimum': 0}},
    ('curso', 'grupo', 'materia', 'tipo_materia', 'especialidad', 'profesor',
     'minutos_semanales', 'bloques_sin_duracion'))


def lista(items=TEXTO, maximo=None):
    return {'type': 'array', 'items': items, **({'maxItems': maximo} if maximo else {})}


def filtro_lista(maximo=20):
    return {**lista(TEXTO, maximo), 'minItems': 1, 'uniqueItems': True}


CURSOR = {'type': 'string', 'minLength': 1, 'maxLength': 4096,
          'description': 'Cursor firmado. Repetir los mismos filtros; si cambia la copia, reiniciar.'}
FILTRO_DIAS = {**filtro_lista(7),
               'description': 'Días de la semana; admite mayúsculas/tildes. Por defecto lunes a viernes.'}
PERSONA = objeto({'nombre': TEXTO, 'roles': {**lista(TEXTO), 'minItems': 1, 'uniqueItems': True}},
                 ('nombre', 'roles'))
ERROR = objeto({'error': objeto({'codigo': {'type': 'string', 'enum': [
    'parametros_invalidos', 'no_encontrado', 'persona_ambigua', 'consulta_vencida',
    'consulta_demasiado_amplia', 'datos_no_disponibles', 'datos_inconsistentes',
    'servicio_no_disponible', 'no_autenticado', 'no_permitido', 'demasiados_intentos']},
    'mensaje': TEXTO, 'campo': TEXTO, 'consulta': TEXTO, 'anio': ANIO,
    'candidatos': lista(PERSONA)}, ('codigo',))}, ('error',))
ASIGNACION = objeto({'curso': TEXTO, 'turno': TURNO, 'funcion': FUNCION,
                     'dias': {**lista(DIA), 'minItems': 1, 'uniqueItems': True}},
                    ('curso', 'turno', 'funcion', 'dias'))
AVISO = objeto({'curso': TEXTO, 'codigo': {'enum': ['turno_nominal_no_configurado', 'division_no_informada']}},
               ('curso', 'codigo'))
TIEMPO = {'inicio': HORA, 'fin': HORA}
CLASE = {'materia': NULO_TEXTO, 'profesor': NULO_TEXTO, 'grupo': TEXTO,
         'titular_en_licencia': NULO_TEXTO, 'superposicion_permitida': {'const': True}}
ACTIVIDAD_CURSO = objeto({**TIEMPO, **CLASE, 'aula': NULO_TEXTO},
                         ('inicio', 'fin', 'materia', 'profesor', 'aula'))
ACTIVIDAD_AULA = objeto({**TIEMPO, **CLASE, 'curso': NULO_TEXTO},
                        ('inicio', 'fin', 'materia', 'profesor', 'curso'))
ACTIVIDAD_PERSONA = {'anyOf': [
    objeto({**TIEMPO, 'rol': TEXTO, 'curso': NULO_TEXTO, 'materia': NULO_TEXTO,
            'aula': NULO_TEXTO, 'grupo': TEXTO, 'superposicion_permitida': {'const': True},
            'en_licencia': {'const': True}, 'suplente': NULO_TEXTO}, ('rol', 'inicio', 'fin')),
    objeto({'rol': {'const': 'preceptor'}, 'turno': TURNO, 'cursos': lista(TEXTO)},
            ('rol', 'turno', 'cursos'))]}


def horario(identidad, actividad):
    return objeto({identidad: TEXTO, 'dias': {'type': 'object',
                  'properties': {d: lista(actividad) for d in DIAS}, 'additionalProperties': False}},
                  (identidad, 'dias'))


COMUN = ('Datos de la última semana cargada en Horarios; no prueban asistencia ni excepciones '
         'por fecha. Una persona puede tener varios cargos. Preceptores: turno/día, sin horas '
         'exactas. Grupos A/B son partes de una división. Un hueco no prueba disponibilidad. '
         'Una asignación de preceptor sin división conserva solo el año; no abarca todas sus divisiones. '
         'Las horas con fin menor o igual al inicio se entregan como estan, incluso con rango/ahora; interpretar el error de la fuente. '
         'Consumir siguiente antes de afirmar que un listado está completo.')


def resultado(propiedades, requeridos):
    return {'anyOf': [objeto({**propiedades, 'siguiente': CURSOR}, requeridos), ERROR]}


CONTRATOS = {
    'catalogos': {
        'nombre': 'listar_catalogos',
        'descripcion': 'Lista cursos, aulas por piso, cargos, nombres, especialidades por curso o tipos_materia (clave y nombre). nombres devuelve solo los nombres completos para revisar una identificación que no se pudo resolver; no descarga horarios ni fichas. Especialidades corresponde a cursos cargados; null significa no configurada. No es requisito previo para consultar una entidad conocida. ' + COMUN,
        'entrada': objeto({'incluir': {**lista({'enum': ['cursos', 'aulas', 'roles', 'nombres',
                                                      'especialidades', 'tipos_materia']}, 6),
                                       'minItems': 1, 'uniqueItems': True, 'default': ['cursos']},
                           'anio': ANIO}),
        'salida': resultado({'cursos': {'type': 'object', 'additionalProperties': lista(TEXTO)},
                             'aulas': {'type': 'object', 'additionalProperties': lista(TEXTO)},
                             'roles': lista(TEXTO), 'nombres': lista(TEXTO),
                             'especialidades': {'type': 'object', 'additionalProperties': NULO_TEXTO},
                             'tipos_materia': lista(objeto({'clave': TEXTO, 'nombre': TEXTO},
                                                          ('clave', 'nombre')))}, ())},
    'personas': {
        'nombre': 'buscar_personas',
        'descripcion': 'Busca nombre o cargo y devuelve todos los roles de cada persona. multiples_roles=true selecciona personas con más de un cargo, sin recorrer todo el padrón. Los filtros se intersectan. Coincidencias aproximadas son candidatos; nunca fusiona personas por parecido. Sin coincidencias: personas vacía. ' + COMUN,
        'entrada': {**objeto({'nombre': TEXTO, 'rol': TEXTO,
                              'multiples_roles': {'type': 'boolean'}, 'cursor': CURSOR}),
                    'anyOf': [{'required': ['nombre']}, {'required': ['rol']},
                              {'required': ['multiples_roles'],
                               'properties': {'multiples_roles': {'const': True}}}]},
        'salida': resultado({'personas': lista(PERSONA)}, ('personas',))},
    'horarios': {
        'nombre': 'consultar_horarios',
        'descripcion': 'Actividades de cursos, personas o aulas; admite un año completo. Exactamente un selector valores/anio/piso. Aula sin selector requiere ahora, o un día y rango. Resolver nombres aproximados mediante candidatos. Asignaciones de preceptor se conservan por turno aun con rango/ahora: no indican presencia exacta. ' + COMUN,
        'entrada': objeto({'tipo': {'enum': ['curso', 'persona', 'aula']},
                           'valores': filtro_lista(), 'anio': ANIO, 'piso': TEXTO,
                           'dias': FILTRO_DIAS, 'desde': HORA, 'hasta': HORA,
                           'ahora': {'type': 'boolean', 'default': False},
                           'roles': filtro_lista(), 'cursor': CURSOR}, ('tipo',)),
        'salida': resultado({'horarios': lista({'anyOf': [horario('curso', ACTIVIDAD_CURSO),
                             horario('aula', ACTIVIDAD_AULA), horario('persona', ACTIVIDAD_PERSONA)]}),
                             'momento': objeto({'fecha': {'type': 'string', 'pattern': r'^\d{4}-\d{2}-\d{2}$'},
                                                'hora': HORA}, ('fecha', 'hora'))}, ('horarios',))},
    'materias': {
        'nombre': 'consultar_materias',
        'descripcion': 'Explora la pestaña MATERIAS. Sin filtros lista todos los cupos cargados, no el plan completo. '
                       'Filtra por tipos te (técnico-específica), ct (científico-tecnológica), fg (teórica); '
                       'anios, divisiones, especialidades y texto (materia, titular o suplente; ignora espacios/tildes). '
                       'Las opciones de un filtro se suman y los distintos filtros se intersectan. '
                       'anios son cadenas como "3". especialidades acepta nombres completos del catálogo. '
                       'Una fila por curso, grupo, materia y docente; profesor es el efectivo según suplencia activa. '
                       'minutos_semanales suma duraciones positivas de bloques, no horas cátedra ni horas únicas del curso. '
                       'Si bloques_sin_duracion > 0, la carga está incompleta. tipo_materia null significa sin clasificación. '
                       'resumen contiene totales globales de toda la selección y se repite en cada página: no sumarlo entre páginas. '
                       'Para días, horas y aulas, consultar luego horarios del curso o docente. ' + COMUN,
        'entrada': objeto({
            'tipos': {**filtro_lista(3), 'items': {'enum': ['te', 'ct', 'fg']}},
            'anios': {**filtro_lista(7), 'items': {'type': 'string', 'enum': list('1234567')}},
            'divisiones': filtro_lista(), 'especialidades': filtro_lista(),
            'texto': TEXTO, 'cursor': CURSOR}),
        'salida': resultado({'materias': lista(CUPO_MATERIA), 'resumen': objeto({
            k: {'type': 'integer', 'minimum': 0} for k in
            ('materias_distintas', 'cupos', 'divisiones', 'minutos_semanales', 'bloques_sin_duracion')},
            ('materias_distintas', 'cupos', 'divisiones', 'minutos_semanales', 'bloques_sin_duracion'))},
            ('materias', 'resumen'))},
    'preceptores': {
        'nombre': 'consultar_preceptores',
        'descripcion': 'Sin filtros lista todos con asignaciones por curso, turno y días. Principal según turno nominal; admite dos contraturnos. Vacante explícita y falta de registro son distintas. Sin registro solo para cursos/año pedidos, sin filtro de nombres. Sin horas exactas. ' + COMUN,
        'entrada': objeto({'cursos': filtro_lista(), 'anio': ANIO, 'nombres': filtro_lista(),
                           'turno': TEXTO, 'dias': FILTRO_DIAS, 'cursor': CURSOR}),
        'salida': resultado({'preceptores': lista(objeto({'nombre': TEXTO, 'asignaciones': lista(ASIGNACION)},
                                                        ('nombre', 'asignaciones'))),
                             'vacantes': lista(ASIGNACION), 'sin_registro': lista(ASIGNACION),
                             'avisos': lista(AVISO)}, ('preceptores',))},
}

# Las combinaciones también viajan en OpenAPI; no dependen solo de la descripción.
def presentes(*campos):
    return {'anyOf': [{'required': [c]} for c in campos]}


selectores = ('valores', 'anio', 'piso')
CONTRATOS['horarios']['entrada'].update(
    anyOf=[
        {'required': ['valores'], 'not': presentes('anio', 'piso')},
        {'required': ['anio'], 'properties': {'tipo': {'const': 'curso'}},
         'not': presentes('valores', 'piso')},
        {'required': ['piso'], 'properties': {'tipo': {'const': 'aula'}},
         'not': presentes('valores', 'anio')},
        {'properties': {'tipo': {'const': 'aula'}}, 'not': presentes(*selectores),
         'anyOf': [
             {'required': ['ahora'], 'properties': {'ahora': {'const': True}}},
             {'required': ['dias', 'desde', 'hasta'], 'properties': {'dias': {'maxItems': 1}}}]}],
    allOf=[
        {'if': {'required': ['roles']}, 'then': {'properties': {'tipo': {'const': 'persona'}}}},
        {'if': {'required': ['desde']}, 'then': {'required': ['hasta']}},
        {'if': {'required': ['hasta']}, 'then': {'required': ['desde']}},
        {'if': {'required': ['ahora'], 'properties': {'ahora': {'const': True}}},
         'then': {'not': presentes('dias', 'desde', 'hasta')}}])
CONTRATOS['catalogos']['entrada']['allOf'] = [
    {'if': {'required': ['anio']}, 'then': {'properties': {
        'incluir': {'contains': {'const': 'cursos'}}}}}]
CONTRATOS['preceptores']['entrada']['not'] = {'required': ['cursos', 'anio']}


def validar(valor, esquema, ruta='entrada'):
    """Valida exclusivamente las palabras de JSON Schema que utiliza este registro."""
    def falla():
        raise ErrorConsulta('parametros_invalidos', 'Valor incompatible con el contrato.', campo=ruta)
    def acepta(subesquema):
        try:
            validar(valor, subesquema, ruta)
            return True
        except ErrorConsulta:
            return False
    tipos = {'object': dict, 'array': list, 'string': str, 'integer': int,
             'boolean': bool, 'null': type(None)}
    if 'type' in esquema:
        esperados = esquema['type'] if isinstance(esquema['type'], list) else [esquema['type']]
        if not any(type(valor) is tipos[t] for t in esperados):
            falla()
    if 'enum' in esquema and valor not in esquema['enum']:
        falla()
    if 'const' in esquema and valor != esquema['const']:
        falla()
    if 'not' in esquema and acepta(esquema['not']):
        falla()
    for alternativa in esquema.get('allOf', []):
        validar(valor, alternativa, ruta)
    if 'if' in esquema and acepta(esquema['if']):
        validar(valor, esquema.get('then', {}), ruta)
    if 'anyOf' in esquema:
        for alternativa in esquema['anyOf']:
            try:
                validar(valor, alternativa, ruta)
                break
            except ErrorConsulta:
                pass
        else:
            falla()
    if isinstance(valor, str):
        if not esquema.get('minLength', 0) <= len(valor) <= esquema.get('maxLength', float('inf')):
            falla()
        if 'pattern' in esquema and not re.search(esquema['pattern'], valor):
            falla()
    if type(valor) is int and valor < esquema.get('minimum', -float('inf')):
        falla()
    if isinstance(valor, list):
        if not esquema.get('minItems', 0) <= len(valor) <= esquema.get('maxItems', float('inf')):
            falla()
        if esquema.get('uniqueItems') and any(v in valor[:i] for i, v in enumerate(valor)):
            falla()
        for i, v in enumerate(valor):
            validar(v, esquema.get('items', {}), f'{ruta}[{i}]')
        if 'contains' in esquema:
            for v in valor:
                try:
                    validar(v, esquema['contains'], ruta)
                    break
                except ErrorConsulta:
                    pass
            else:
                falla()
    if isinstance(valor, dict):
        if any(k not in valor for k in esquema.get('required', [])):
            falla()
        propiedades = esquema.get('properties', {})
        for k, v in valor.items():
            if k in propiedades:
                validar(v, propiedades[k], f'{ruta}.{k}')
            elif esquema.get('additionalProperties') is False:
                falla()
            elif isinstance(esquema.get('additionalProperties'), dict):
                validar(v, esquema['additionalProperties'], f'{ruta}.{k}')
