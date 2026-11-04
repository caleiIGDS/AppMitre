"""Referencias PDF de lectura, firmadas y efímeras; reutilizan el render existente."""
from flask import current_app, url_for
from itsdangerous import URLSafeTimedSerializer

from . import acceso, datos, rutas
from .consultas.comun import ErrorConsulta, Snapshot, activo, nombre, resolver_persona
from .consultas.contratos import TEXTO, filtro_lista, objeto, validar

VIGENCIA = 600
ENTRADA = objeto({'tipo': {'enum': ['curso', 'persona', 'aula', 'cursos', 'preceptores']},
                  'valor': TEXTO, 'cursos': filtro_lista(), 'todos': {'type': 'boolean'}}, ('tipo',))
SALIDA = objeto({'url': {'type': 'string'}, 'nombre': TEXTO,
                 'mime_type': {'const': 'application/pdf'},
                 'vence_en_segundos': {'type': 'integer'}},
                ('url', 'nombre', 'mime_type', 'vence_en_segundos'))
DESCRIPCION = ('Obtiene un enlace PDF válido por 10 minutos, sin exponer la contraseña. '
               'tipo curso/persona/aula requiere valor; cursos requiere cursos o todos=true; '
               'preceptores no lleva selector. Persona exporta solo clases docentes, no otros cargos. '
               'El archivo se genera al descargarlo; no es un horario JSON.')


def firmador():
    return URLSafeTimedSerializer(acceso.clave_derivada(current_app.secret_key), salt='horarios-pdf-mcp-v1')


def obtener(p):
    validar(p, ENTRADA)
    tipo = p['tipo']
    campos = set(p) - {'tipo'}
    if tipo in ('curso', 'persona', 'aula'):
        if campos != {'valor'}:
            raise ErrorConsulta('parametros_invalidos', 'Este PDF requiere solo tipo y valor.')
    elif tipo == 'cursos':
        if not (campos == {'cursos'} or (campos == {'todos'} and p['todos'] is True)):
            raise ErrorConsulta('parametros_invalidos', 'Pedí cursos o todos=true, sin combinarlos.')
    elif campos:
        raise ErrorConsulta('parametros_invalidos', 'La planilla de preceptores no lleva selector.')
    s = Snapshot(datos.DB_PATH)
    if tipo == 'curso':
        p = {'tipo': tipo, 'valor': s.seleccionar_cursos({'valores': [p['valor']]})[0]}
    elif tipo == 'cursos' and 'cursos' in p:
        p = {'tipo': tipo, 'cursos': s.seleccionar_cursos({'valores': p['cursos']})}
    elif tipo == 'persona':
        n = resolver_persona(p['valor'], s.padron)
        if not any(nombre(r['profesor']) == n or (activo(r['suplente_activo']) and nombre(r['prof_suplente']) == n)
                   for r in s.clases):
            raise ErrorConsulta('no_encontrado', 'Esta persona no tiene clases docentes para exportar; consultá sus cargos con consultar_horarios.')
        p = {'tipo': tipo, 'valor': n}
    elif tipo == 'aula':
        aula = datos.limpiar_aula(p['valor'])
        if aula not in s.aulas:
            raise ErrorConsulta('no_encontrado', 'Aula desconocida.')
        p = {'tipo': tipo, 'valor': aula}
    referencia = firmador().dumps(p)
    return {'url': url_for('horarios_mcp.descargar_pdf', referencia=referencia, _external=True),
            'nombre': 'horario.pdf' if tipo != 'preceptores' else 'preceptores.pdf',
            'mime_type': 'application/pdf', 'vence_en_segundos': VIGENCIA}


def descargar(p):
    """Solo se llama después de comprobar la firma y vencimiento de la referencia."""
    tipo = p['tipo']
    if tipo == 'preceptores':
        return rutas.export_pdf_planilla_preceptores()
    if tipo == 'cursos':
        return rutas.export_pdf_cursos('todos' if p.get('todos') else ','.join(p['cursos']))
    return rutas.export_pdf('profesor' if tipo == 'persona' else tipo, p['valor'])
