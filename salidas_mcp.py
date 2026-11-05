"""Herramientas MCP de Salidas y entrega opcional a una pestaña."""
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
from salidas_mcp_acceso import RUTA_OAUTH, SCOPE, oauth
from texto import norm


bp = Blueprint('salidas_mcp', __name__)
VERSIONES = ('2025-03-26', '2025-06-18', '2025-11-25')
VIGENCIA = 600
MAX_BYTES = 96 * 1024
ANEXOS = ('I', 'II', *salidas.ANEXOS_NUMEROS)
TIPOS = {'text', 'textarea', 'date', 'time', 'select', 'bool', 'number', 'personas', 'telefonos'}
ROLES = ('estudiante', 'docente_titular', 'docente_reemplazante', 'no_docente')
INSTRUCCIONES = (
    'Consultá los anexos de Salidas Educativas. Conectá AppMitre para consultar, crear o editar '
    'legajos. Usá solo datos aportados o confirmados. Para editar buscá y consultá primero la salida '
    'para obtener su revisión. Crear y editar guardan directamente en AppMitre. Las firmas, '
    'autorizaciones y declaraciones quedan a cargo de sus responsables.'
)
oauth.registrar(bp)


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


def _objeto(propiedades, opcionales=()):
    return {'type': 'object', 'properties': propiedades, 'required': [k for k in propiedades if k not in opcionales],
            'additionalProperties': False}


def _tool(nombre, descripcion, propiedades, lectura=True, opcionales=(), protegido=False):
    esquema = {'type': 'oauth2', 'scopes': [SCOPE]} if protegido else {'type': 'noauth'}
    return {'name': nombre, 'description': descripcion, 'inputSchema': _objeto(propiedades, opcionales),
            'securitySchemes': [esquema],
            '_meta': {'securitySchemes': [esquema]},
            'annotations': {'readOnlyHint': lectura, 'destructiveHint': nombre == 'editar_salida',
                            'idempotentHint': lectura, 'openWorldHint': False}}


CODIGO = {'type': 'string', 'description': 'Código temporal que muestra la pestaña de edición.'}
ID = {'type': 'integer', 'minimum': 1}
CAMPOS = {'type': 'object', 'additionalProperties': True,
          'description': 'Mapa de campos. Ejemplo: {"comunes.denominacion_proyecto":"Visita","IV.actividades":"Recorrido"}. '
                         'Usá esquema_legajo para conocer las claves y los tipos.'}
PROTEGIDAS = {'buscar_salidas', 'consultar_salida', 'esquema_legajo', 'crear_salida', 'editar_salida'}
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
    _tool('buscar_salidas', 'Busca legajos vigentes por nombre del proyecto y devuelve sus IDs.',
          {'consulta': {'type': 'string'}}, opcionales=('consulta',), protegido=True),
    _tool('consultar_salida', 'Lee los campos editables de un legajo y la revisión para editarlo.',
          {'id': ID}, protegido=True),
    _tool('esquema_legajo', 'Devuelve los campos digitales que se pueden escribir y sus tipos.',
          {}, protegido=True),
    _tool('crear_salida', 'Crea y guarda un legajo con los datos confirmados. Reutilizá la misma '
          'operación al reintentar. El nombre del proyecto es obligatorio.',
          {'operacion': {'type': 'string', 'description': 'Identificador único de esta creación, por ejemplo un UUID.'},
           'campos': CAMPOS}, lectura=False, protegido=True),
    _tool('editar_salida', 'Guarda cambios en los campos indicados de un legajo vigente. Conserva el resto. '
          'Para borrar un valor usá null. Si enviás personas, incluí la nómina completa.',
          {'id': ID, 'revision': {'type': 'string'}, 'campos': CAMPOS}, lectura=False, protegido=True),
]


def _campos_legajo():
    esquema = salidas.esquema_formulario()
    campos = {f'comunes.{c["id"]}': c for grupo in esquema['comunes'] for c in grupo['campos'] if not c.get('fijo')}
    for anexo in esquema['anexos']:
        for campo in anexo['campos']:
            if not (campo.get('auto') or campo.get('calc')):
                clave = f'{anexo["n"]}.{campo["id"]}'
                campos[clave] = campo
                if campo['tipo'] == 'acompañantes_telefonos':
                    campos[clave] = {**campo, 'tipo': 'telefonos'}
    campos['personas'] = {'tipo': 'personas', 'label': 'Nómina completa de estudiantes y acompañantes'}
    return campos


def _leer_campo(datos, clave):
    grupo, _, campo = clave.partition('.')
    if grupo == 'personas':
        return datos.get('personas') or []
    if grupo == 'comunes':
        return (datos.get('datos_comunes') or {}).get(campo)
    return ((datos.get('anexos') or {}).get(grupo) or {}).get(campo)


def _personas_directas(valores):
    if not isinstance(valores, list) or len(valores) > 300:
        return False
    for p in valores:
        if not isinstance(p, dict) or p.get('grupo_edad') not in (None, '+16', '+18'):
            return False
        normalizada = {k: v for k, v in p.items()
                       if k != 'grupo_edad' and not (k in ('documento', 'cargo', 'fecha_nacimiento') and v == '')}
        if not _persona(normalizada):
            return False
    return True


def _aplicar_campos(datos, campos):
    for clave, valor in campos.items():
        grupo, _, campo = clave.partition('.')
        if grupo == 'personas':
            datos['personas'] = []
            hoy = ahora().date()
            for p in valor or []:
                persona = {'documento': '', 'cargo': '', 'fecha_nacimiento': '', **p}
                if 'grupo_edad' not in persona:
                    fecha = persona['fecha_nacimiento']
                    grupo_edad = None
                    if persona['rol'] == 'estudiante' and fecha:
                        nac = date.fromisoformat(fecha)
                        edad = hoy.year - nac.year - ((hoy.month, hoy.day) < (nac.month, nac.day))
                        grupo_edad = '+18' if edad >= 18 else '+16' if edad >= 16 else None
                    persona['grupo_edad'] = grupo_edad
                datos['personas'].append(persona)
            continue
        destino = datos['datos_comunes'] if grupo == 'comunes' else datos['anexos'].setdefault(grupo, {})
        if valor is None:
            destino.pop(campo, None)
        else:
            destino[campo] = valor
        if clave == 'VI.lugares_estadia':
            destino['_lugares_estadia_manual'] = valor is not None


def _fecha_larga(valor):
    if not _fecha(valor):
        return ''
    f = date.fromisoformat(valor)
    mes = ('enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre'
           .split())[f.month - 1]
    return f'{f.day} de {mes} de {f.year}'


def _derivados(datos):
    comunes, anexos = datos['datos_comunes'], datos['anexos']
    for n in salidas.ANEXOS_NUMEROS:
        anexos.setdefault(n, {})
    for grupo in salidas.esquema_formulario()['comunes']:
        for campo in grupo['campos']:
            for destino in campo.get('destino', ()):
                n, clave = destino.split('.')
                anexos[n][clave] = comunes.get(campo['id'], '')
    roles = ('estudiante', 'no_docente', 'docente_titular', 'docente_reemplazante')
    personas = sorted(datos.get('personas') or [], key=lambda p: (
        roles.index(p['rol']) if p['rol'] in roles else len(roles), norm(p.get('apellido_nombre', ''))))
    iv, v, vi, vii, ix = (anexos[n] for n in ('IV', 'V', 'VI', 'VII', 'IX'))
    iv.update(cantidad_alumnos=sum(p['rol'] == 'estudiante' for p in personas),
              cantidad_docentes_acompanantes=sum(p['rol'].startswith('docente') for p in personas),
              cantidad_no_docentes_acompanantes=sum(p['rol'] == 'no_docente' for p in personas),
              total_personas=len(personas))
    for rol, tabla in [('docente_titular', 'docentes_responsables_titulares'),
                       ('docente_reemplazante', 'docentes_reemplazantes')]:
        iv[tabla] = [{'apellido_nombre': p['apellido_nombre'], 'cargo': p.get('cargo', '')}
                     for p in personas if p['rol'] == rol and p.get('apellido_nombre')]
    v['listado_personas'] = [
        {'numero': i, 'apellido_nombre': p.get('apellido_nombre', ''), 'documento': p.get('documento', ''),
         'estudiante': p['rol'] == 'estudiante', 'docente': p['rol'].startswith('docente'),
         'no_docente': p['rol'] == 'no_docente', 'asistencia': ''}
        for i, p in enumerate(personas, 1)
    ]
    for tramo in ('salida', 'regreso'):
        hora = comunes.get(f'hora_{tramo}')
        vi[f'lugar_dia_hora_{tramo}'] = ' — '.join(filter(None, (
            comunes.get(f'lugar_{tramo}'), _fecha_larga(comunes.get(f'fecha_{tramo}')), f'{hora} hs' if hora else '')))
    inicio = _fecha_larga(comunes.get('fecha_salida'))
    fin = _fecha_larga(comunes.get('fecha_regreso')) or inicio
    periodo = f'del {inicio} al {fin}' if inicio and fin != inicio else inicio
    fin_partes = fin.split(' de ') if fin else ['', '', '']
    inicio_dia = inicio.rsplit(' de ', 1)[0]
    fin_dia = fin.rsplit(' de ', 1)[0]
    dias = f'{inicio_dia} al {fin_dia}' if inicio and fin != inicio else inicio_dia
    for anexo in (vi, vii):
        anexo.update(dias_salida=dias, mes_salida=fin_partes[1])
    vii['anio_salida'] = fin_partes[2]
    ix.update(tipo_gestion='estatal', fecha_lugar_realizacion=' — '.join(
        filter(None, (periodo, comunes.get('lugar_a_visitar')))))
    if not vi.get('_lugares_estadia_manual'):
        vi['lugares_estadia'] = ', '.join(iv[k] for k in ('hospedaje_nombre', 'hospedaje_domicilio', 'hospedaje_localidad')
                                        if iv.get(k))
        if iv.get('hospedaje_telefono'):
            vi['lugares_estadia'] = ' — '.join(filter(None, (vi['lugares_estadia'], 'Tel: ' + iv['hospedaje_telefono'])))
    telefonos = vi.get('nombres_telefonos_acompanantes') or {}
    vi['nombres_telefonos_acompanantes_texto'] = '\n'.join(
        ' - '.join(filter(None, (p['apellido_nombre'], telefonos.get(p['apellido_nombre']))))
        for p in personas if p['rol'] != 'estudiante' and p.get('apellido_nombre'))


def _resumen(fila):
    return {'id': fila['id'], 'proyecto': fila['nombre_proyecto'], 'fecha_salida': fila['fecha_salida'],
            'url': url_for('salidas.detalle', id=fila['id'], _external=True)}


def _legajo(nombre, args):
    campos = _campos_legajo()
    if nombre == 'esquema_legajo' and not args:
        return {'campos': {k: {a: c[a] for a in ('tipo', 'label', 'opciones') if a in c} for k, c in campos.items()},
                'roles_personas': ROLES,
                'forma_persona': ['rol', 'apellido_nombre', 'documento', 'cargo', 'fecha_nacimiento', 'grupo_edad']}
    if nombre == 'buscar_salidas' and set(args) <= {'consulta'} and isinstance(args.get('consulta', ''), str):
        consulta = norm(args.get('consulta', ''))
        with closing(salidas.conectar()) as con:
            filas = con.execute('SELECT id,nombre_proyecto,fecha_salida FROM salidas WHERE archivado=0 '
                                'AND vigencia_hasta>? ORDER BY id DESC', (ahora().isoformat(),))
            resultados = [_resumen(f) for f in filas if consulta in norm(f['nombre_proyecto'])]
        return {'salidas': resultados[:40], 'total': len(resultados)}
    id = args.get('id')
    if nombre == 'consultar_salida' and set(args) == {'id'} and type(id) is int and 0 < id < 2**63:
        with closing(salidas.conectar()) as con:
            fila = con.execute('SELECT * FROM salidas WHERE id=? AND archivado=0 AND vigencia_hasta>?',
                               (id, ahora().isoformat())).fetchone()
        if fila is None:
            return {'error': 'Salida activa no encontrada.'}
        datos = json.loads(fila['datos_json'])
        valores = {k: _leer_campo(datos, k) for k in campos}
        return {**_resumen(fila), 'revision': salidas.revision_legajo(fila['datos_json']),
                'campos': {k: v for k, v in valores.items() if v is not None}}
    crear = nombre == 'crear_salida'
    if (not crear and nombre != 'editar_salida') or set(args) != (
            {'operacion', 'campos'} if crear else {'id', 'revision', 'campos'}):
        raise ValueError('Herramienta o argumentos inválidos.')
    valores = args['campos']
    if not isinstance(valores, dict) or not valores or any(
            k not in campos or (v is not None and not (
                _personas_directas(v) if k == 'personas' else _valor_valido(campos[k], v)))
            for k, v in valores.items()):
        raise ValueError('Los cambios deben usar campos editables y valores del tipo indicado en esquema_legajo.')
    return _guardar_directo(crear, args, valores)


def _guardar_directo(crear, args, valores):
    id = args.get('id')
    if crear:
        operacion = args['operacion']
        if not isinstance(operacion, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}', operacion):
            raise ValueError('La operación debe ser un identificador único de 16 a 80 caracteres.')
        if not _texto(valores.get('comunes.denominacion_proyecto'), 250):
            raise ValueError('La salida nueva necesita un nombre de proyecto.')
        pedido = _huella(json.dumps(valores, sort_keys=True))
    elif type(id) is not int or not 0 < id < 2**63 or not isinstance(args['revision'], str):
        raise ValueError('Se requiere el ID y la revisión del legajo consultado.')
    with closing(salidas.conectar()) as con, con:
        con.execute('BEGIN IMMEDIATE')
        if crear:
            anterior = con.execute('SELECT * FROM salidas_mcp_creaciones WHERE operacion=?', (operacion,)).fetchone()
            if anterior:
                if anterior['pedido'] != pedido:
                    raise ValueError('La operación ya se usó para otro contenido.')
                fila = con.execute('SELECT * FROM salidas WHERE id=?', (anterior['salida'],)).fetchone()
                return {**_resumen(fila), 'estado': 'ya_creada'} if fila else {'error': 'La salida ya no está disponible.'}
            datos = {'formato': 'appmitre.salidas.v1', 'resolucion': 'RESOC-2024-3871-GDEBA-DGCYE',
                     'datos_comunes': dict(salidas.esquema_formulario()['fijos']), 'personas': [], 'anexos': {}}
        else:
            fila = con.execute('SELECT * FROM salidas WHERE id=? AND archivado=0 AND vigencia_hasta>?',
                               (id, ahora().isoformat())).fetchone()
            if fila is None:
                raise ValueError('Salida activa no encontrada.')
            if salidas.revision_legajo(fila['datos_json']) != args['revision']:
                raise ValueError('La salida cambió. Volvé a consultarla antes de editar.')
            datos = json.loads(fila['datos_json'])
            datos['datos_comunes'] = datos.get('datos_comunes') or {}
            datos['anexos'] = datos.get('anexos') or {}
            vi = datos['anexos'].get('VI') or {}
            if vi.get('lugares_estadia'):
                vi.setdefault('_lugares_estadia_manual', True)
        _aplicar_campos(datos, valores)
        comunes = datos['datos_comunes']
        if comunes.get('fecha_salida') and comunes.get('fecha_regreso') and comunes['fecha_regreso'] < comunes['fecha_salida']:
            raise ValueError('La fecha de regreso debe ser igual o posterior a la salida.')
        _derivados(datos)
        id = salidas.guardar_legajo(con, datos, id)
        if crear:
            con.execute('INSERT INTO salidas_mcp_creaciones VALUES (?,?,?)', (operacion, pedido, id))
        fila = con.execute('SELECT * FROM salidas WHERE id=?', (id,)).fetchone()
        return {**_resumen(fila), 'estado': 'creada' if crear else 'editada'}


def _referencias():
    return {
        'resolucion': url_for('normativa_visor', _external=True),
        'resolucion_pdf': url_for('static', filename='salidas/resolucion-3871-24.pdf', _external=True),
        'instructivo': url_for('salidas.instructivo', _external=True),
    }


def _llamar(nombre, args):
    if nombre in PROTEGIDAS:
        return _legajo(nombre, args)
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
    if request.path == RUTA_OAUTH + '/authorize':
        r.headers['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
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
                          'serverInfo': {'name': 'appmitre-salidas', 'version': '1.1.0'},
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
    if params['name'] in PROTEGIDAS and not oauth.autorizado():
        desafio = oauth.desafio()
        r = responder({'isError': True, 'content': [{'type': 'text', 'text': 'Autorizá AppMitre Salidas.'}],
                       '_meta': {'mcp/www_authenticate': [desafio]}})
        r.headers['WWW-Authenticate'] = desafio
        r.status_code = 401
        return r
    try:
        salida = _llamar(params['name'], args)
    except ValueError as error:
        salida = {'error': str(error)}
    return responder({'content': [{'type': 'text', 'text': json.dumps(salida, ensure_ascii=False)}],
                      'structuredContent': salida, 'isError': 'error' in salida})
