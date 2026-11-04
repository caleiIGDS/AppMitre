from .comun import ErrorConsulta


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
    if 'nombres' in incluir:
        salida['nombres'] = sorted(s.padron)
    return salida
