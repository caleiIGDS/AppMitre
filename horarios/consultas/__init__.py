"""Cuatro consultas reutilizables; autenticación y transporte viven fuera del núcleo."""
from . import catalogos, horarios, personas, preceptores
from .comun import ErrorConsulta, Snapshot
from .contratos import CONTRATOS, validar

_OPERACIONES = {'catalogos': catalogos.ejecutar, 'personas': personas.ejecutar,
                'horarios': horarios.ejecutar, 'preceptores': preceptores.ejecutar}


def ejecutar(operacion, parametros, ruta, clave_cursor):
    contrato = CONTRATOS[operacion]
    validar(parametros, contrato['entrada'])
    snapshot = Snapshot(ruta)
    if operacion == 'catalogos':
        resultado = _OPERACIONES[operacion](snapshot, parametros)
    else:
        resultado = _OPERACIONES[operacion](snapshot, parametros, clave_cursor)
    try:
        validar(resultado, contrato['salida'], 'salida')
    except ErrorConsulta as e:
        raise ErrorConsulta('datos_inconsistentes', 'El resultado no cumple el contrato de Horarios.') from e
    return resultado
