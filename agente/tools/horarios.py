"""Tools de lectura de los horarios (escuela.db).

Es la única área que el agente NO puede escribir: la planilla se carga desde Google
Sheets con un botón aparte del SPA.
"""
import sqlite3

import texto
from config import DIAS
from horarios import datos as database
from horarios.datos import obtener_filas

from ..dominio import ve_entidad
from ..padrones import (_buscar_profesor_scored, _etiqueta_curso, _personas_conocidas,
                        _personas_parecidas, _preceptores_parecidos, _preceptores_por_curso,
                        _puntaje_nombre, _lista_preceptores, _roles_no_docentes)

# Arriba de esto el padrón deja de ser un dato y pasa a ser una pared de texto que come
# contexto sin que el modelo pueda leerla de verdad. Es el mismo tope que
# `LIMITE_LISTADO_COMPLETO` en `entidades.py`, y por la misma razón; hoy el padrón son ~344
# nombres, así que el margen es chico y esto se va a activar antes de lo que parece.
LIMITE_PADRON = 400

# Explicación de titular/contraturno que acompaña a todas las respuestas de preceptores:
# sin esto el modelo lee dos nombres y no sabe cuál dar cuando le preguntan "el preceptor"
# de un curso a secas.
#
# Decía "`contraturno` es el del otro turno", en singular. Los turnos son TRES y hay 12 cursos
# de 64 con dos contraturnos a la vez, así que "el otro" no existe: leyendo eso, preguntado por
# la mañana de un curso cuyo contraturno era de tarde, el modelo daba al de tarde — porque bajo
# la regla binaria era la única respuesta posible.
NOTA_TURNOS = ('Los turnos de la escuela son TRES: MAÑANA, TARDE y VESPERTINO. `turno_del_curso` '
               'es el turno en que ese curso cursa: ese dato es este campo y no se deduce de '
               'ningún otro. `titular` es el preceptor de ese turno; `contraturno` es TODO el '
               'resto, y es una LISTA que puede tener más de una persona, en turnos distintos. '
               'Si te preguntan "el preceptor" sin aclarar, es el titular — mencioná el de '
               'contraturno como dato adicional. '
               'SI TE PREGUNTAN POR UN TURNO CONCRETO ("¿y a la mañana?", "¿el de la tarde?"), '
               'buscá ese turno en el campo `turno` de cada entrada y contestá con esa: NUNCA '
               'asumas que "contraturno" significa el turno que te preguntaron. Si el turno que '
               'te preguntan está en `turnos_sin_nadie`, la respuesta es que la planilla no tiene '
               'a nadie cargado en ese turno para ese curso — decilo así, no ofrezcas al de otro '
               'turno en su lugar (podés mencionarlo aparte, aclarando de qué turno es). '
               '`turnos_sin_nadie` es para CONTESTAR, no para recitar: si no te preguntaron por '
               'ese turno, no lo enumeres. Las dos excepciones en que sí conviene decirlo solo son '
               'que el turno vacío sea `turno_del_curso` (o sea, `titular` vacío) o que el curso '
               'no tenga a nadie en ningún turno. '
               'Si `titular` viene VACÍO, la planilla no tiene a nadie cargado en el turno del '
               'curso: contá el de contraturno aclarando eso, no lo presentes como si fuera el '
               'titular ni digas que el curso no tiene preceptor. `dias` aparece solo cuando esa '
               'persona no cubre la semana entera. `sin_asignar` significa que la planilla dice '
               'FALTA ahí, no que haya alguien llamado así (distinto de `turnos_sin_nadie`, que '
               'es no haber ninguna fila).')


def _padron_completo_horarios():
    """El padrón entero de los horarios, o None si es tan grande que mandarlo no ayudaría.

    Es el SEGUNDO NIVEL de las búsquedas de persona: el equivalente de `listar_todos` para
    `escuela.db`. Cuando la difusa no puntúa a nadie, "no encontré" NO es "no existe" —se
    comparan letras, no personas— y el modelo necesita la lista a la vista para reconocer un
    apodo, un nombre dado vuelta o una errata grande.

    Viaja en la MISMA respuesta y no por una tool aparte, igual que el `padron_completo` de
    `_buscar_por_rol_fmt`: un round-trip extra re-procesa ~8.050 tokens de piso contra los
    ~1.670 que cuesta la lista. Ver `dev-log/DECISIONS.md`.
    """
    padron = _personas_conocidas()
    return padron if len(padron) <= LIMITE_PADRON else None


def _otros_padrones(permisos):
    """El recordatorio de que el de horarios es UNO de tres padrones.

    Va al final de las notas del caso vacío: decir "no está" habiendo mirado sólo los
    horarios repite el mismo error un escalón más arriba. El puntero a las fichas sale sólo
    con permiso para verlas — mandar a una tool que no se le entregó es peor que callarse.
    """
    fichas = ('y la gente CON FICHA que no da clases tampoco (va por '
              '`buscar_entidad("personas", ...)`)' if ve_entidad('personas', permisos)
              else 'y tampoco está la gente que no da clases')
    return ('Y acordate de que este es UNO de tres padrones: los PRECEPTORES no están acá '
            '(van por `preceptores`) ' + fichas + '.')


def _sin_nadie_parecido(query, permisos):
    """Respuesta de `buscar_profesor` cuando el padrón difuso no puntuó a NADIE.

    Antes esta rama devolvía `[]` pelado —sin nota y sin listado—, y el modelo lo leía como
    un hecho: "esa persona no está en el sistema". Era la única de las tres búsquedas de
    persona sin segundo nivel (`buscar_entidad` manda a `listar_todos`, `buscar_por_rol`
    devuelve el padrón de cargos en la misma respuesta).
    """
    padron = _padron_completo_horarios()
    salida = {'docentes': []}
    if padron:
        salida['padron_completo'] = padron
    salida['nota'] = (
        f'Nadie del padrón de horarios se parece a "{query}". OJO: la búsqueda compara '
        'LETRAS, no personas — un apodo, un nombre al revés o una errata grande no matchean, '
        'así que NO afirmes todavía que no está. '
        + ('En `padron_completo` tenés los nombres de TODA la gente de los horarios (docentes '
           'y no docentes): fijate vos si alguno es. Si ninguno lo es, decilo — no ofrezcas el '
           'más parecido como si fuera el correcto. ' if padron else '')
        + _otros_padrones(permisos))
    return salida


def _buscar_profesor(query, permisos=frozenset()):
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

    Cada candidato lleva su `rol` cuando tiene cargo no docente, y los PRECEPTORES que
    coinciden se devuelven aparte: no están en el padrón difuso (nombres sin normalizar),
    así que sin este cruce alguien como "NOELIA" no existía para el agente.

    El cruce con las fichas sale sólo con permiso para ver `personas`: los horarios son
    consulta abierta, las semblanzas no. Sin el permiso la tool devuelve los docentes y
    nada más, que es exactamente lo que era antes de que existiera el cruce.

    Si no coincide NADIE por ningún lado, ver `_sin_nadie_parecido`: no se devuelve la lista
    vacía sino el padrón entero, porque una lista vacía el modelo la lee como "no existe".
    """
    docentes = []
    for _, nombre, rol in _buscar_profesor_scored(query):
        candidato = {'nombre': nombre}
        if rol:
            candidato['rol'] = rol
        docentes.append(candidato)

    con_ficha = _personas_parecidas(query) if ve_entidad('personas', permisos) else []
    preceptores = _preceptores_parecidos(query)
    if not docentes and not con_ficha and not preceptores:
        return _sin_nadie_parecido(query, permisos)
    if not con_ficha and not preceptores:
        return docentes

    salida = {'docentes': docentes}
    if con_ficha:
        salida['personas_con_ficha'] = [{'id': pid, 'nombre': n} for pid, n in con_ficha]
        salida['aviso'] = (
            'OJO: "' + query + '" también se parece a personas que tienen FICHA propia en la '
            'memoria de la escuela (' + ', '.join(n for _, n in con_ficha) + '). Son dos '
            'padrones distintos: `docentes` sale de los horarios, `personas_con_ficha` de las '
            'semblanzas. Si estás hablando de un hito o la historia de alguien, '
            'casi seguro te referís a una de `personas_con_ficha` — usá esa y NO ofrezcas solo '
            'la lista de docentes. Si no estás seguro, mostrale las dos y preguntá.'
        )
    if preceptores:
        salida['preceptores'] = preceptores
        salida['aviso_preceptores'] = (
            '"' + query + '" también coincide con PRECEPTORES de la planilla: '
            + ', '.join(preceptores) + '. Ellos no dan clases, así que horario_profesor no '
            'sabe nada de esta gente: para saber qué cursos tienen, llamá a '
            'preceptores(preceptor="...").'
        )
    return salida


def _buscar_por_rol_fmt(rol=None):
    """Personal no docente buscado por CARGO (EMATP, jefaturas), no por nombre.

    Sin `rol` devuelve el padrón entero. Con `rol` que no matchea, devuelve igual el padrón
    entero en `padron_completo`: los cargos están escritos con las siglas de la escuela
    ("EMATP EERR" por energías renovables) y la búsqueda compara letras, no significados —
    el que reconoce la sigla es el modelo, mirando la lista. Es el mismo camino de dos
    niveles que `buscar_entidad` → `listar_todos`, sin diccionario de abreviaturas que
    mantener cada vez que la escuela crea un cargo.
    """
    todos = _roles_no_docentes()
    if not todos:
        return {'total': 0, 'resultados': [],
                'nota': 'No hay personal no docente cargado en los horarios.'}

    if not rol:
        return {'total': len(todos), 'resultados': todos,
                'instruccion': ('Este es el padrón COMPLETO de cargos no docentes de la escuela. '
                                'El horario de cualquiera de ellos se pide con horario_profesor.')}

    encontrados = _roles_no_docentes(rol)
    if encontrados:
        return {'rol_buscado': rol, 'total': len(encontrados), 'resultados': encontrados,
                'instruccion': ('El cargo está escrito tal como lo cargó la escuela. Para el '
                                'horario de presencia de alguno de ellos, llamá a horario_profesor.')}

    return {
        'rol_buscado': rol, 'total': 0, 'resultados': [], 'padron_completo': todos,
        'nota': (f'Ningún cargo coincide LITERALMENTE con "{rol}", pero la planilla usa las '
                 'siglas de la escuela, así que puede estar igual con otro nombre. Ahí tenés el '
                 'padrón completo de cargos no docentes en `padron_completo`: fijate vos si '
                 'alguno es el que te piden. Si ninguno lo es, decilo — no ofrezcas el más '
                 'parecido como si fuera el correcto.')
    }


def _fichas_ordenadas(fichas):
    """Las fichas de preceptores ordenadas por año y división, para que se lean como la planilla."""
    def clave(item):
        (curso, division), _ficha = item
        return (int(curso) if str(curso).isdigit() else 99, str(division))
    return [ficha for _, ficha in sorted(fichas.items(), key=clave)]


def _preceptores_fmt(curso=None, division=None, preceptor=None):
    """Preceptor ↔ curso, ya digerido: qué preceptor tiene cada curso, y al revés.

    La tabla cruda son 595 filas (una por curso × turno × día) con los nombres sin
    normalizar; acá sale una ficha por curso, con el titular y el contraturno separados.
    Tres modos, según lo que venga: un curso, un preceptor, o nada (la planilla entera).
    """
    fichas = _preceptores_por_curso()
    if not fichas:
        return {'total': 0, 'cursos': [],
                'nota': 'No hay planilla de preceptores cargada.'}

    if preceptor:
        return _cursos_de_preceptor_fmt(preceptor, fichas)

    if curso:
        num = database._extraer_num_curso(curso)
        # La división pasa por lo mismo que el curso: las de 4°–7° son números y en castellano
        # se escriben "6ta"/"3ra" — tal cual las tipea el usuario. Sin esto "6ta" quedaba "6TA",
        # no matcheaba nada y la tool devolvía error con los 64 cursos. `_extraer_num_curso`
        # devuelve el string tal cual si no empieza con dígito, así que "A"/"B" no se tocan.
        div = database._extraer_num_curso(division).strip().upper() if division else ''
        elegidas = {k: v for k, v in fichas.items()
                    if k[0] == num and (not div or k[1] == div)}
        if not elegidas:
            pedido = _etiqueta_curso(num, div)
            return {'error': f'No hay preceptores cargados para {pedido}.',
                    'cursos_disponibles': [f['curso'] for f in _fichas_ordenadas(fichas)],
                    'nota': 'Fijate en `cursos_disponibles` si el curso está escrito de otra '
                            'forma. Si no está en esa lista, no hay planilla para ese curso.'}
        return {'total': len(elegidas), 'cursos': _fichas_ordenadas(elegidas),
                'instruccion': NOTA_TURNOS}

    return {'total': len(fichas), 'cursos': _fichas_ordenadas(fichas),
            'instruccion': ('Esta es la planilla COMPLETA de preceptores, un curso por fila. '
                            + NOTA_TURNOS)}


def _alias_preceptores(padron):
    """Agrupa las grafías del mismo nombre: [['ROMERO VANESA', 'VANESA ROMERO'], ['NOELIA'], …].

    La planilla carga el nombre a mano y a veces con el orden dado vuelta, así que la misma
    preceptora entra dos veces. Sin agrupar pasaban dos cosas: la búsqueda por nombre
    quedaba empatada entre sus dos grafías y pedía desambiguar entre dos opciones idénticas,
    y la que se eligiera mostraba solo la mitad de sus cursos. Se agrupa por conjunto de
    palabras —no por parecido— para no fusionar a dos personas distintas: "DANIELA TRAJO" y
    "DANIELA TREJO" (que son un typo) quedan separadas a propósito.
    """
    grupos = {}
    for nombre in padron:
        grupos.setdefault(frozenset(texto.norm(nombre).split()), []).append(nombre)
    return list(grupos.values())


def _cursos_de_preceptor_fmt(nombre, fichas):
    """Los cursos que tiene un preceptor, separados en titulares y de contraturno.

    Resuelve el nombre igual que `_horario_profesor_fmt`: difuso, auto-resolviendo solo si
    hay un ganador claro y devolviendo `sugerencias` si están empatados. Hace más falta que
    allá, porque esta planilla tiene el nombre a veces dado vuelta ("VANESA ROMERO" y
    "ROMERO VANESA") y con erratas.
    """
    grupos = _alias_preceptores(_lista_preceptores())
    q_norm = texto.norm(nombre)

    def puntaje(variantes):
        return max(max(_puntaje_nombre(q_norm, texto.norm(v)),
                       texto.puntaje_busqueda(q_norm, v) or 0.0) for v in variantes)

    puntuados = sorted(((puntaje(g), g) for g in grupos), reverse=True, key=lambda x: x[0])
    puntuados = [(s, g) for s, g in puntuados if s >= 0.6][:5]

    if not puntuados:
        # Mismo segundo nivel que el padrón de horarios, y acá sale casi gratis: son 46
        # nombres (~210 tokens). Es además coherente con el modo por curso, que ya devuelve
        # `cursos_disponibles` cuando el curso no matchea.
        return {'preceptor': nombre, 'cursos': [],
                'padron_completo': sorted(_lista_preceptores()),
                'nota': f'Ningún preceptor se parece a "{nombre}". NO afirmes todavía que no '
                        'está: en `padron_completo` tenés a todos los de la planilla, fijate '
                        'vos. Ojo que están cargados a mano, sin normalizar y a veces dados '
                        'vuelta ("VANESA ROMERO" / "ROMERO VANESA"). Si es alguien que da '
                        'clases, no es preceptor: eso va por `horario_profesor`.'}

    ganador_claro = len(puntuados) == 1 or puntuados[0][0] - puntuados[1][0] >= 0.15
    if not ganador_claro:
        return {'preceptor': nombre, 'sin_match_exacto': True,
                'sugerencias': [g[0] for _, g in puntuados],
                'nota': f'Hay varios preceptores parecidos a "{nombre}". Preguntale al usuario '
                        'cuál es en vez de elegir vos. NO inventes los cursos.'}

    variantes = puntuados[0][1]
    como_titular, como_contraturno = [], []
    for ficha in _fichas_ordenadas(fichas):
        for donde, destino in (('titular', como_titular), ('contraturno', como_contraturno)):
            for entrada in ficha[donde]:
                if entrada.get('preceptor') in variantes:
                    item = {'curso': ficha['curso'], 'turno': entrada['turno']}
                    if entrada.get('dias'):
                        item['dias'] = entrada['dias']
                    destino.append(item)

    elegido = max(variantes, key=lambda v: (
        sum(1 for f in fichas.values() for d in ('titular', 'contraturno')
            for e in f[d] if e.get('preceptor') == v), v))
    salida = {'preceptor': elegido,
              'como_titular': como_titular, 'como_contraturno': como_contraturno,
              'total_cursos': len(como_titular) + len(como_contraturno),
              'instruccion': NOTA_TURNOS}
    if len(variantes) > 1:
        salida['nota_variantes'] = ('La planilla tiene a esta persona escrita de más de una forma ('
                                    + ', '.join(sorted(variantes)) + '); los cursos de todas esas '
                                    'grafías están sumados acá.')
    elif texto.norm(elegido) != q_norm:
        salida['nota_fuzzy'] = f'No hay coincidencia exacta con "{nombre}"; se usó "{elegido}".'
    return salida

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


def _horario_profesor_fmt(nombre, permisos=frozenset()):
    """Horario de una persona del padrón de horarios, formato interpretado.

    `clases.profesor` exige match exacto normalizado, así que un typo ("andrea alvares")
    devolvía vacío y el modelo lo leía como "no tiene clases". La resolución difusa la
    hace el harness acá, no el modelo: si hay un único candidato parecido se usa ese
    (avisando cuál), y si hay varios se devuelven como sugerencias para desambiguar.

    Devuelve además el horario de personal NO DOCENTE cuando lo hay, y por eso no corta
    apenas encuentra clases: hay gente que está en las dos tablas (RODRIGUEZ VIRGINIA da
    clases y es EMATP de biología), y devolviendo solo `clases` se perdía media agenda.

    `permisos` es sólo para redactar la nota del caso vacío: no cambia qué horario se
    devuelve (los horarios son consulta abierta), decide si tiene sentido mandar al modelo a
    `buscar_entidad("personas", ...)` o si esa tool ni siquiera se le entregó.
    """
    filas = obtener_filas('profesor', nombre)
    nombre_usado = nombre
    nota_fuzzy = None
    no_docente = _horario_no_docente(nombre)

    if not filas and not no_docente:
        scored = _buscar_profesor_scored(nombre)
        candidatos = [n for _, n, _rol in scored]
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
            resultado = {
                'profesor': nombre, 'clases': {}, 'sin_match_exacto': True,
                'sugerencias': candidatos,
                'nota': f'No existe nadie llamado exactamente "{nombre}". Candidatos '
                        f'parecidos: {", ".join(candidatos)}. Preguntale al usuario cuál es '
                        f'(o reintentá con el nombre exacto). NO inventes el horario.'
            }
            # El nombre puede ser el de un preceptor y estos candidatos, docentes que se
            # llaman parecido: ofrecer solo los docentes manda al usuario a elegir entre
            # gente que no es la que buscaba.
            preceptores = _preceptores_parecidos(nombre)
            if preceptores:
                resultado['preceptores'] = preceptores
                resultado['aviso_preceptores'] = (
                    f'"{nombre}" también coincide con preceptores de la planilla: '
                    + ', '.join(preceptores) + '. Los preceptores no tienen horario de clases; '
                    'sus cursos se consultan con preceptores(preceptor="...").')
            return resultado
        else:
            # Último cruce antes de decir que no existe: los preceptores no están en este
            # padrón y tampoco tienen clases, así que su horario no se responde acá.
            preceptores = _preceptores_parecidos(nombre)
            if preceptores:
                return {'profesor': nombre, 'clases': {}, 'preceptores': preceptores,
                        'nota': f'"{nombre}" no da clases ni figura como personal no docente, '
                                f'pero SÍ es preceptor/a de la planilla ({", ".join(preceptores)}). '
                                'Los preceptores no tienen horario de clases: para saber qué '
                                'cursos tiene, llamá a preceptores(preceptor="...").'}
            # Acá terminaba con "No existe ningún docente ni personal no docente llamado X
            # ni parecido": una afirmación cerrada, que el modelo repetía como un hecho. Es
            # justo el punto donde hace falta el segundo nivel — mismo criterio que
            # `_sin_nadie_parecido`.
            padron = _padron_completo_horarios()
            resultado = {'profesor': nombre, 'clases': {}}
            if padron:
                resultado['padron_completo'] = padron
            resultado['nota'] = (
                f'Nadie del padrón se llama "{nombre}" ni parecido. NO afirmes todavía que no '
                'existe: la búsqueda compara letras, no personas. '
                + ('Mirá `padron_completo` —todos los nombres de los horarios, docentes y no '
                   'docentes— y fijate si alguno es. Si ninguno lo es, ahí sí decilo. '
                   if padron else '')
                + _otros_padrones(permisos))
            return resultado

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
