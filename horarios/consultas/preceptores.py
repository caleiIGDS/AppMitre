from .comun import (DIAS, TURNOS, VACANTES, MAX_PRECEPTORES, ErrorConsulta, compacto,
                    curso, dia, dias_pedidos, nombre, norm, paginar, resolver_persona, turno)


def ejecutar(s, p, clave):
    if 'cursos' in p and 'anio' in p:
        raise ErrorConsulta('parametros_invalidos', 'cursos y anio son alternativas.')
    explicitos = 'cursos' in p or 'anio' in p
    cursos = s.seleccionar_cursos(p, 'cursos') if explicitos else s.cursos
    # Una fila sin division sigue siendo una asignacion parcial, nunca otra division.
    parciales = {curso(r['curso'], '') for r in s.preceptores
                 if str(r['curso'] or '').strip() and not str(r['division'] or '').strip()}
    if 'cursos' not in p:
        cursos = set(cursos) | {c for c in parciales
                               if 'anio' not in p or int(c.split('°')[0]) == p['anio']}
    ds = dias_pedidos(p)
    ts = list(TURNOS)
    if 'turno' in p:
        t = norm(p['turno'])
        if t not in ('manana', 'tarde', 'vespertino'):
            raise ErrorConsulta('parametros_invalidos', 'Turno desconocido.', campo='turno')
        ts = [turno(t)]
    padron = {n: roles for n, roles in s.padron.items() if 'preceptor' in roles}
    nombres = {resolver_persona(n, padron) for n in p['nombres']} if 'nombres' in p else None
    grupos, registrados, avisos = {}, set(), set()
    for r in s.preceptores:
        c = curso(r['curso'], r['division'])
        if c not in cursos:
            continue
        d, t = dia(r['dia']), turno(r['turno'])
        if d not in ds or t not in ts:
            continue
        n = nombre(r['preceptor'])
        registrados.add((c, t, d))
        if nombres is not None and n not in nombres:
            continue
        nominal = s.nominales.get(c)
        if nominal is None:
            avisos.add(c)
        funcion = ('principal' if nominal == t else 'contraturno') if nominal else None
        grupos.setdefault((n, c, t, funcion), set()).add(d)
    personas, vacantes = {}, {}
    def asignacion(c, t, funcion, dias):
        return {'curso': c, 'turno': t, 'funcion': funcion, 'dias': sorted(dias, key=DIAS.index)}
    for (n, c, t, f), dias in sorted(grupos.items(), key=lambda x: compacto(x[0])):
        a = asignacion(c, t, f, dias)
        if n in VACANTES:
            vacantes.setdefault(c, []).append(a)
        else:
            personas.setdefault(n, []).append(a)
    ausentes = {}
    if explicitos and nombres is None:
        for c in sorted(set(cursos) - parciales):
            for t in ts:
                faltantes = [d for d in ds if (c, t, d) not in registrados]
                if faltantes:
                    nominal = s.nominales.get(c)
                    if nominal is None:
                        avisos.add(c)
                    f = ('principal' if nominal == t else 'contraturno') if nominal else None
                    ausentes.setdefault(c, []).append(asignacion(c, t, f, faltantes))
    unidades = [{'preceptores': [{'nombre': n, 'asignaciones': asignaciones}]}
                for n, asignaciones in sorted(personas.items())]
    # Vacantes/ausencias se agrupan por curso para que tampoco se partan sus días.
    for c in sorted(set(vacantes) | set(ausentes) | avisos):
        unidad = {}
        if c in vacantes:
            unidad['vacantes'] = vacantes[c]
        if c in ausentes:
            unidad['sin_registro'] = ausentes[c]
        if c in avisos:
            unidad['avisos'] = [{'curso': c, 'codigo': ('division_no_informada' if c in parciales
                                                      else 'turno_nominal_no_configurado')}]
        unidades.append(unidad)
    return paginar(unidades, ['preceptores'], p, s.revision, clave, 'preceptores', MAX_PRECEPTORES)
