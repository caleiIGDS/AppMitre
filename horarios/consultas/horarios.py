from .. import config, datos
from .comun import (DIAS, ErrorConsulta, activo, curso, dia, dias_pedidos, intervalo,
                    nombre, norm, paginar, resolver_persona, turno, compacto)


def filtros(p):
    tipo = p['tipo']
    selectores = [c for c in ('valores', 'anio', 'piso') if c in p]
    if len(selectores) > 1 or ('anio' in p and tipo != 'curso') or ('piso' in p and tipo != 'aula'):
        raise ErrorConsulta('parametros_invalidos', 'Usá un único selector compatible con tipo.')
    if not selectores and tipo != 'aula':
        raise ErrorConsulta('parametros_invalidos', 'Falta un selector de entidades.')
    if 'roles' in p and tipo != 'persona':
        raise ErrorConsulta('parametros_invalidos', 'roles solo se admite para persona.')
    if ('desde' in p) != ('hasta' in p):
        raise ErrorConsulta('parametros_invalidos', 'desde y hasta se indican juntos.')
    if p.get('ahora') and any(c in p for c in ('dias', 'desde', 'hasta')):
        raise ErrorConsulta('parametros_invalidos', 'ahora es incompatible con días/rango.')
    if not selectores and not p.get('ahora') and not ('desde' in p and len(p.get('dias', [])) == 1):
        raise ErrorConsulta('parametros_invalidos', 'Todas las aulas requieren ahora, o un día y rango.')
    contexto = {}
    instante = None
    if p.get('ahora'):
        momento = config.ahora()
        dias = [DIAS[momento.weekday()]]
        instante = momento.hour * 60 + momento.minute
        contexto['momento'] = {'fecha': momento.strftime('%Y-%m-%d'), 'hora': momento.strftime('%H:%M')}
    else:
        dias = dias_pedidos(p)
    rango = None
    if 'desde' in p:
        rango = [datos._a_minutos(p[k]) for k in ('desde', 'hasta')]
        if rango[0] >= rango[1]:
            raise ErrorConsulta('parametros_invalidos', 'desde debe ser anterior a hasta.')
    return dias, rango, instante, contexto


def ejecutar(s, p, clave):
    dias, rango, instante, contexto = filtros(p)
    tipo = p['tipo']
    if tipo == 'curso':
        valores = s.seleccionar_cursos(p)
    elif tipo == 'persona':
        valores = list(dict.fromkeys(resolver_persona(v, s.padron) for v in p['valores']))
    elif 'piso' in p:
        pisos = [piso for piso in s.pisos if norm(piso) == norm(p['piso'])]
        if not pisos:
            raise ErrorConsulta('no_encontrado', 'Piso desconocido.', consulta=p['piso'])
        valores = s.pisos[pisos[0]]
    elif 'valores' in p:
        valores = list(dict.fromkeys(datos.limpiar_aula(v) for v in p['valores']))
        for v in valores:
            if v not in s.aulas:
                raise ErrorConsulta('no_encontrado', 'Aula desconocida.', consulta=v)
    else:
        valores = s.aulas
    roles = {norm(r) for r in p.get('roles', [])}
    if roles:
        conocidos = {norm(r) for rr in s.padron.values() for r in rr}
        if roles - conocidos:
            raise ErrorConsulta('no_encontrado', 'Rol desconocido.', consulta=sorted(roles - conocidos)[0])
    resultados = {v: {tipo: v, 'dias': {d: [] for d in dias}} for v in valores}
    def coincide_rol(rol):
        return not roles or norm(rol) in roles
    def agregar(valor, r, actividad):
        d = dia(r['dia'])
        if d not in dias:
            return
        ini, fin = intervalo(r)
        if rango and not (ini < rango[1] and fin > rango[0]):
            return
        if instante is not None and not ini <= instante < fin:
            return
        actividad.update(inicio=datos.a_hhmm(ini), fin=datos.a_hhmm(fin))
        resultados[valor]['dias'][d].append(actividad)
    for r in s.clases:
        c = curso(r['curso'], r['division']) if r['curso'] else None
        titular, suplente = nombre(r['profesor']), nombre(r['prof_suplente'])
        licencia = activo(r['suplente_activo'])
        profesor = (suplente if licencia else titular) or None
        aula = datos.limpiar_aula(r['aula']) or None
        comunes = {'materia': r['materia'] or None}
        if r['grupo']:
            comunes['grupo'] = r['grupo']
        if activo(r['superposicion']):
            comunes['superposicion_permitida'] = True
        if tipo in ('curso', 'aula'):
            valor = c if tipo == 'curso' else aula
            if valor in resultados:
                actividad = {**comunes, 'profesor': profesor,
                             **({'aula': aula} if tipo == 'curso' else {'curso': c})}
                if licencia:
                    actividad['titular_en_licencia'] = titular or None
                agregar(valor, r, actividad)
        elif coincide_rol('docente'):
            # El titular conserva la referencia de la clase, marcada en licencia.
            for n in {titular, suplente if licencia else ''} & resultados.keys():
                actividad = {**comunes, 'rol': 'docente', 'curso': c, 'aula': aula}
                if licencia and n == titular:
                    actividad['en_licencia'] = True
                    actividad['suplente'] = suplente or None
                agregar(n, r, actividad)
    if tipo == 'persona':
        for r in s.personal:
            n = nombre(r['nombre'])
            if n in resultados and coincide_rol(r['rol']):
                agregar(n, r, {'rol': r['rol']})
        agrupados = {}
        if coincide_rol('preceptor'):
            for r in s.preceptores:
                n = nombre(r['preceptor'])
                if n not in resultados:
                    continue
                d, t = dia(r['dia']), turno(r['turno'])
                if d in dias:
                    agrupados.setdefault((n, d, t), set()).add(curso(r['curso'], r['division']))
        for (n, d, t), cursos in agrupados.items():
            resultados[n]['dias'][d].append({'rol': 'preceptor', 'turno': t, 'cursos': sorted(cursos)})
    for entidad in resultados.values():
        for d in dias:
            unicos = {compacto(a): a for a in entidad['dias'][d]}.values()
            entidad['dias'][d] = sorted(unicos, key=lambda a: (
                a.get('inicio', '99:99'), a.get('fin', '99:99'), a.get('turno', ''), compacto(a)))
    return paginar([{'horarios': [entidad]} for entidad in resultados.values()], ['horarios'], p,
                   s.revision, clave, 'horarios', contexto=contexto)
