"""Tools de lectura de los horarios (escuela.db).

Es la única área que el agente NO puede escribir: la planilla se carga desde Google
Sheets con un botón aparte del SPA.
"""
import sqlite3

import database
import texto
from config import DIAS
from database import obtener_filas

from ..padrones import _buscar_profesor_scored, _personas_parecidas


def _buscar_profesor(query):
    """Resolución difusa de nombre de profesor.

    Devuelve además las personas CON FICHA (`historia.db`) que se parecen al nombre, cuando
    las hay. Son dos padrones distintos y el modelo tiende a olvidarlo: los docentes salen
    de los horarios (`escuela.db`) y ahí no está el alumno que ganó una olimpiada ni el
    ex director. Pidiendo "el hito lo logró nati" el modelo llamaba acá, veía tres docentes
    llamadas Natalia y ofrecía esas tres — mientras "Natalia Boo Fiad" estaba cargada como
    persona y no aparecía por ningún lado.

    El aviso va en el resultado de la tool y no en el system prompt porque el fallo pasa
    JUSTO acá: el modelo ya eligió mal la herramienta, y lo único que lo puede corregir a
    tiempo es lo que esta herramienta le conteste.
    """
    docentes = [{'nombre': p} for _, p in _buscar_profesor_scored(query)]
    con_ficha = _personas_parecidas(query)
    if not con_ficha:
        return docentes

    return {
        'docentes': docentes,
        'personas_con_ficha': [{'id': pid, 'nombre': n} for pid, n in con_ficha],
        'aviso': (
            'OJO: "' + query + '" también se parece a personas que tienen FICHA propia en la '
            'memoria de la escuela (' + ', '.join(n for _, n in con_ficha) + '). Son dos '
            'padrones distintos: `docentes` sale de los horarios, `personas_con_ficha` de las '
            'semblanzas. Si estás hablando de un hito o la historia de alguien, '
            'casi seguro te referís a una de `personas_con_ficha` — usá esa y NO ofrezcas solo '
            'la lista de docentes. Si no estás seguro, mostrale las dos y preguntá.'
        ),
    }

def _horario_no_docente(nombre):
    """Horario de personal no docente (EMATP, jefaturas, porteros…), o None si no está.

    Vive en otra tabla que `clases` y son turnos de presencia, no clases: por día una
    franja horaria y un rol, sin materia ni curso.
    """
    filas = database.obtener_personal_por_nombre(nombre)
    if not filas:
        return None
    # La tabla guarda los días en mayúscula y sin tilde ("MIERCOLES"); DIAS los tiene
    # como se muestran. Normalizamos para ordenar sin depender de la grafía.
    por_dia = {texto.norm(f['dia']): f"{f['hora_inicio']}–{f['hora_fin']}" for f in filas}
    horario = {dia: por_dia[texto.norm(dia)] for dia in DIAS if texto.norm(dia) in por_dia}
    return {'rol': filas[0]['rol'], 'horario': horario}


def _horario_profesor_fmt(nombre):
    """Horario de una persona del padrón de horarios, formato interpretado.

    `clases.profesor` exige match exacto normalizado, así que un typo ("andrea alvares")
    devolvía vacío y el modelo lo leía como "no tiene clases". La resolución difusa la
    hace el harness acá, no el modelo: si hay un único candidato parecido se usa ese
    (avisando cuál), y si hay varios se devuelven como sugerencias para desambiguar.

    Devuelve además el horario de personal NO DOCENTE cuando lo hay, y por eso no corta
    apenas encuentra clases: hay gente que está en las dos tablas (RODRIGUEZ VIRGINIA da
    clases y es EMATP de biología), y devolviendo solo `clases` se perdía media agenda.
    """
    filas = obtener_filas('profesor', nombre)
    nombre_usado = nombre
    nota_fuzzy = None
    no_docente = _horario_no_docente(nombre)

    if not filas and not no_docente:
        scored = _buscar_profesor_scored(nombre)
        candidatos = [n for _, n in scored]
        # Auto-resolvemos solo si hay un ganador claro (único candidato, o el primero
        # le saca ventaja al segundo). Si están empatados —"gonzalez" matchea a varios
        # por igual— devolvemos la lista para que el modelo pregunte, no adivine.
        ganador_claro = len(scored) == 1 or (len(scored) > 1 and scored[0][0] - scored[1][0] >= 0.15)
        if scored and ganador_claro:
            nombre_usado = scored[0][1]
            filas = obtener_filas('profesor', nombre_usado)
            no_docente = _horario_no_docente(nombre_usado)
            nota_fuzzy = f'No hay coincidencia exacta con "{nombre}"; se usó "{nombre_usado}".'
        elif candidatos:
            return {
                'profesor': nombre, 'clases': {}, 'sin_match_exacto': True,
                'sugerencias': candidatos,
                'nota': f'No existe nadie llamado exactamente "{nombre}". Candidatos '
                        f'parecidos: {", ".join(candidatos)}. Preguntale al usuario cuál es '
                        f'(o reintentá con el nombre exacto). NO inventes el horario.'
            }
        else:
            return {'profesor': nombre, 'clases': {},
                    'nota': f'No existe ningún docente ni personal no docente llamado "{nombre}" ni parecido.'}

    if not filas:
        # Sin clases pero con horario no docente: es el caso de un EMATP o un portero,
        # y devolver "no tiene clases" a secas hacía que el modelo lo diera por inexistente.
        resultado = {'profesor': nombre_usado, 'clases': {},
                     'rol_no_docente': no_docente['rol'],
                     'horario_no_docente': no_docente['horario'],
                     'nota': f'{nombre_usado} no da clases: es personal NO DOCENTE '
                             f'({no_docente["rol"]}). `horario_no_docente` es su horario de '
                             f'presencia en la escuela, día por día.'}
        if nota_fuzzy:
            resultado['nota_fuzzy'] = nota_fuzzy
        return resultado

    # Agrupar por día
    por_dia = {}
    for f in filas:
        dia = f['dia']
        if dia not in por_dia:
            por_dia[dia] = []
        linea = f"{f['hora_inicio']}–{f['hora_fin']} · {f['materia']} · {f['curso']}°{f['division']} · {f['aula']}"
        if f.get('suplente_activo') == 1:
            linea += f" (suplente: {f['prof_suplente']})"
        por_dia[dia].append(linea)

    # Ordenar por día de la semana
    clases_ordenadas = {}
    for dia in DIAS:
        if dia in por_dia:
            clases_ordenadas[dia] = por_dia[dia]

    resultado = {'profesor': nombre_usado, 'clases': clases_ordenadas}
    if no_docente:
        # Da clases Y tiene cargo no docente: son dos horarios que conviven, no uno que
        # reemplaza al otro. Van separados para que el modelo no los mezcle en un mismo día.
        resultado['rol_no_docente'] = no_docente['rol']
        resultado['horario_no_docente'] = no_docente['horario']
        resultado['aviso_no_docente'] = (
            f'{nombre_usado} además es {no_docente["rol"]} (personal no docente). '
            f'`horario_no_docente` es su horario de presencia por ese cargo y es ADEMÁS de '
            f'sus clases, no en vez de ellas: si te preguntan por su horario, contá los dos.'
        )
    if nota_fuzzy:
        resultado['nota'] = nota_fuzzy
    return resultado

def _horario_curso_fmt(curso, division):
    """Horario de curso, formato interpretado."""
    con = database.conectar()
    con.row_factory = sqlite3.Row  # database.conectar() no lo setea; sin esto dict(row) revienta
    cur = con.cursor()
    cur.execute("SELECT * FROM clases WHERE curso = ? AND division = ?", (curso, division))
    filas = [dict(row) for row in cur.fetchall()]
    con.close()

    if not filas:
        return {'curso': f'{curso}° {division}', 'clases': {}, 'nota': f'No se encontraron clases.'}

    por_dia = {}
    for f in filas:
        dia = f['dia']
        if dia not in por_dia:
            por_dia[dia] = []
        linea = f"{f['hora_inicio']}–{f['hora_fin']} · {f['materia']} · {f['profesor']} · {f['aula']}"
        por_dia[dia].append(linea)

    clases_ordenadas = {}
    for dia in DIAS:
        if dia in por_dia:
            clases_ordenadas[dia] = por_dia[dia]

    return {'curso': f'{curso}° {division}', 'clases': clases_ordenadas}

def _horario_aula_fmt(aula):
    """Horario de aula, formato interpretado."""
    con = database.conectar()
    con.row_factory = sqlite3.Row  # ídem _horario_curso_fmt
    cur = con.cursor()
    cur.execute("SELECT * FROM clases WHERE aula = ?", (aula,))
    filas = [dict(row) for row in cur.fetchall()]
    con.close()

    if not filas:
        return {'aula': aula, 'clases': {}, 'nota': f'No hay clases en {aula}.'}

    por_dia = {}
    for f in filas:
        dia = f['dia']
        if dia not in por_dia:
            por_dia[dia] = []
        linea = f"{f['hora_inicio']}–{f['hora_fin']} · {f['materia']} · {f['curso']}°{f['division']} · {f['profesor']}"
        por_dia[dia].append(linea)

    clases_ordenadas = {}
    for dia in DIAS:
        if dia in por_dia:
            clases_ordenadas[dia] = por_dia[dia]

    return {'aula': aula, 'clases': clases_ordenadas}

def _aulas_libres_fmt():
    """Aulas libres ahora."""
    return database.aulas_libres()
