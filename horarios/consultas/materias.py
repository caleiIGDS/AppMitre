"""La exploración de MATERIAS: filtros combinables y carga semanal por cupo."""
from ..materias import clave_tipo, especialidad
from .. import config
from .comun import (ErrorConsulta, activo, compacto, curso, intervalo, nombre, norm,
                    paginar, MAX_PERSONAS)


def normalizar(valor):
    # Igual que la búsqueda de la pestaña MATERIAS: ignora espacios y tildes.
    return norm(valor).replace(' ', '').replace('°', '')


def ejecutar(s, p, clave):
    tipos = set(p.get('tipos', []))
    anios = set(p.get('anios', []))
    divisiones = {norm(d) for d in p.get('divisiones', [])}
    especialidades = {normalizar(e) for e in p.get('especialidades', [])}
    conocidas = {normalizar(e) for e in config.ESPECIALIDAD_CURSOS.values()}
    if especialidades - conocidas:
        raise ErrorConsulta('no_encontrado', 'Especialidad desconocida.',
                            consulta=sorted(especialidades - conocidas)[0])
    texto = normalizar(p.get('texto', ''))
    grupos = {}
    for r in s.clases:
        if not r['materia'] or not r['curso']:
            continue
        tipo, esp = clave_tipo(r), especialidad(r)
        if tipos and tipo not in tipos:
            continue
        if anios and str(r['curso']) not in anios:
            continue
        if divisiones and norm(r['division']) not in divisiones:
            continue
        if especialidades and normalizar(esp) not in especialidades:
            continue
        if texto and not any(texto in normalizar(r[c])
                             for c in ('materia', 'profesor', 'prof_suplente')):
            continue
        titular = nombre(r['profesor']) or None
        licencia = activo(r['suplente_activo'])
        docente = (nombre(r['prof_suplente']) if licencia else titular) or None
        c = curso(r['curso'], r['division'])
        grupo = str(r['grupo'] or '').strip() or None
        identidad = compacto([c, grupo, r['materia'], titular, docente, licencia])
        if identidad not in grupos:
            fila = {'curso': c, 'grupo': grupo, 'materia': r['materia'],
                    'tipo_materia': tipo or None, 'especialidad': esp or None,
                    'profesor': docente, 'minutos_semanales': 0, 'bloques_sin_duracion': 0}
            if licencia:
                fila['titular_en_licencia'] = titular
            grupos[identidad] = fila
        fila = grupos[identidad]
        try:
            inicio, fin = intervalo(r)
            if fin <= inicio:
                raise ValueError()
        except (ErrorConsulta, ValueError):
            fila['bloques_sin_duracion'] += 1
        else:
            fila['minutos_semanales'] += fin - inicio
    filas = sorted(grupos.values(), key=lambda f: (
        int(f['curso'].split('°')[0]), f['curso'], f['materia'], f['grupo'] or '', compacto(f)))
    resumen = {'materias_distintas': len({f['materia'] for f in filas}),
               'cupos': len(filas), 'divisiones': len({f['curso'] for f in filas}),
               'minutos_semanales': sum(f['minutos_semanales'] for f in filas),
               'bloques_sin_duracion': sum(f['bloques_sin_duracion'] for f in filas)}
    return paginar([{'materias': [f]} for f in filas], ['materias'], p,
                   s.revision, clave, 'materias', MAX_PERSONAS, contexto={'resumen': resumen})
