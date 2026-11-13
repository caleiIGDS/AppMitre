from .comun import ErrorConsulta
from ..materias import especialidad, TIPOS_MATERIA


def ejecutar(s, p):
    incluir = p.get('incluir', ['cursos'])
    if 'anio' in p and 'cursos' not in incluir:
        raise ErrorConsulta('parametros_invalidos', 'anio requiere incluir cursos.')
    salida = {}
    if 'cursos' in incluir:
        cursos = s.seleccionar_cursos(p) if 'anio' in p else s.cursos
        salida['cursos'] = {}
        for c in cursos:
            anio, division = c.split('°', 1)
            salida['cursos'].setdefault(anio, []).append(division.strip())
    if 'aulas' in incluir:
        salida['aulas'] = dict(s.pisos)
        ubicadas = {a for aulas in s.pisos.values() for a in aulas}
        otras = [a for a in s.aulas if a not in ubicadas]
        if otras:
            salida['aulas']['sin_piso'] = otras
    if 'roles' in incluir:
        salida['roles'] = sorted({r for roles in s.padron.values() for r in roles})
    if 'especialidades' in incluir:
        # Solo cursos presentes en la copia; no anuncia divisiones sin datos.
        salida['especialidades'] = {}
        for c in s.cursos:
            anio, division = c.split('°', 1)
            salida['especialidades'][c] = especialidad({'curso': anio, 'division': division.strip()}) or None
    if 'tipos_materia' in incluir:
        salida['tipos_materia'] = [{'clave': c, 'nombre': n} for c, n in TIPOS_MATERIA.items()]
    if 'nombres' in incluir:
        salida['nombres'] = sorted(s.padron)
    return salida
