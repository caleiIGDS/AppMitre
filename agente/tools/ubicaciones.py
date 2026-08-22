"""Tool de desglose de recursos por lugar: mover unidades de un recurso entre lugares
("moví 3 destornilladores de laboratorio a taller").

Exclusivo del área de recursos, así que se importa `gestion` directo, mismo criterio que
`prestamos.py`.
"""
import gestion

from ..db import conectar
from .prestamos import _resolver_recurso


def _mover_ubicacion_fmt(recurso, cantidad, origen, destino):
    cantidad = gestion._int(cantidad)
    if cantidad <= 0:
        return {'ok': False, 'error': f'Cantidad inválida: {cantidad}. No se movió nada.'}

    destino = (destino or '').strip()
    if not destino:
        return {'ok': False, 'error': 'Falta el lugar de destino. No se movió nada.'}

    con = conectar()
    cur = con.cursor()

    recurso = str(recurso or '')
    if recurso.isdigit():
        rid = int(recurso)
    else:
        matches = _resolver_recurso(cur, recurso)
        if len(matches) == 0:
            con.close()
            return {'ok': False, 'error': f'Recurso no encontrado: "{recurso}". No se movió nada.'}
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

    if gestion._stock(cur, rid) is None:
        con.close()
        return {'ok': False, 'error': f'Recurso no existe: id={rid}. No se movió nada.'}

    antes = gestion.ubicaciones_recurso(cur, rid)
    resultado = gestion.mover_ubicacion(cur, rid, cantidad, origen, destino)
    if not resultado['ok']:
        con.close()
        return resultado

    con.commit()
    ubicaciones = gestion.ubicaciones_recurso(cur, rid)
    con.close()

    mensaje = f'Movidas {cantidad} unidades a "{destino}"' + (f' desde "{origen}"' if origen else '')
    if resultado['avisos']:
        mensaje += '. OJO: ' + '; '.join(resultado['avisos'])

    return {'ok': True, 'recurso_id': rid, 'mensaje': mensaje, 'ubicaciones': ubicaciones,
            'avisos': resultado['avisos'], 'antes': {'ubicaciones': antes}}
