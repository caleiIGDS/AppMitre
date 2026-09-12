"""Tools de lectura de los horarios (escuela.db).

Es la única área que el agente NO puede escribir: la planilla se carga desde Google
Sheets con un botón aparte del SPA.
"""
import json
import re
import sqlite3

import texto
from config import DIAS
from horarios import datos as database
from horarios.datos import obtener_filas

from ..padrones import (_buscar_profesor_scored, _etiqueta_curso, _personas_conocidas,
                        _preceptores_parecidos, _preceptores_por_curso,
                        _puntaje_nombre, _lista_preceptores, _roles_no_docentes)

# Arriba de esto el padrón deja de ser un dato y pasa a ser una pared de texto que come
# contexto sin que el modelo pueda leerla de verdad. Es el mismo tope que
# `LIMITE_LISTADO_COMPLETO` en `entidades.py`, y por la misma razón; hoy el padrón son ~344
# nombres, así que el margen es chico y esto se va a activar antes de lo que parece.
LIMITE_PADRON = 400

# Tope de la `grilla` de `coincidencias`, medido sobre el JSON serializado y no sobre la
# cantidad de entidades: la cantidad es mal proxy, porque "todos los 1ros" son 11 cursos pero
# pesan 5.000 tokens (comparten horario, hay pocas fronteras distintas) y 10 cursos al azar
# pesan 7.700. 20.000 chars son ~6.600 tokens y caen entre 10 y 15 entidades, así que todo lo
# que alguien pregunta de verdad conserva el detalle. Sin esto, cruzar los 62 cursos manda
# 62.000 tokens al historial para que el modelo lea "no coinciden nunca".
LIMITE_GRILLA_CHARS = 20000

# Hasta acá un pozo entre dos clases es un recreo o un cambio de hora y la entidad sigue en la
# escuela; más que eso ya es un hueco en el que se pudo ir a la casa y no se cuenta como
# presente. El umbral existe para poder dar UNA sola respuesta: mientras hubo dos resúmenes
# —"todos con clase" y "todos en el edificio"— el modelo daba los dos y el usuario elegía.
HUECO_MAXIMO_MIN = 40

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

# Las clases de taller parten el curso en dos mitades que van a la misma hora con docentes y
# talleres distintos. Sin esto el modelo veía dos clases simultáneas del mismo curso y las
# leía como un error de la planilla o elegía una sola.
NOTA_GRUPOS = ('Las clases que dicen "Grupo A" o "Grupo B" son de MEDIA división: en talleres '
               'el curso se parte en dos mitades, cada una con su docente y su taller. Lo más '
               'común es que las dos vayan a la misma hora, y entonces dos clases simultáneas del '
               'mismo curso con grupos distintos NO son un error ni una superposición: son las dos '
               'mitades, y las dos van. Pero NO siempre es así: hay horarios donde figura un solo '
               'grupo, y ahí la otra mitad cursa en otro momento o no tiene nada cargado. Contá lo '
               'que dice la planilla: no des por hecho que a cada grupo le corresponde otro a la '
               'misma hora, ni completes el que falta. Las clases sin grupo las cursa la división '
               'entera. Si te preguntan por un alumno concreto no adivines de qué grupo es: mostrá '
               'los dos y aclaralo.')


def _sufijo_grupo(fila):
    """` · Grupo A` cuando la clase es de media división, o vacío cuando es de todo el curso."""
    grupo = (fila.get('grupo') or '').strip()
    return f' · Grupo {grupo.upper()}' if grupo else ''


def _hay_grupos(filas):
    return any((f.get('grupo') or '').strip() for f in filas)



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


def _otros_padrones():
    """El recordatorio de que el de horarios es UNO de dos padrones.

    Va al final de las notas del caso vacío: decir "no está" habiendo mirado sólo los
    horarios repite el mismo error un escalón más arriba.
    """
    return ('Y acordate de que este es UNO de dos padrones: los PRECEPTORES no están acá '
            '(van por `preceptores`).')


def _sin_nadie_parecido(query):
    """Respuesta de `buscar_profesor` cuando el padrón difuso no puntuó a NADIE.

    Antes esta rama devolvía `[]` pelado —sin nota y sin listado—, y el modelo lo leía como
    un hecho: "esa persona no está en el sistema". Era la única de las búsquedas de
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
        + _otros_padrones())
    return salida


def _buscar_profesor(query, permisos=frozenset()):
    """Resolución difusa de nombre de profesor.

    Cada candidato lleva su `rol` cuando tiene cargo no docente, y los PRECEPTORES que
    coinciden se devuelven aparte: no están en el padrón difuso (nombres sin normalizar),
    así que sin este cruce alguien como "NOELIA" no existía para el agente.

    `permisos` no se usa hoy (no hay ningún cruce que dependa de un permiso propio de
    entidad); queda en la firma porque `ejecutar_tool` se lo pasa a todas las tools de
    lectura de personas por igual.

    Si no coincide NADIE por ningún lado, ver `_sin_nadie_parecido`: no se devuelve la lista
    vacía sino el padrón entero, porque una lista vacía el modelo la lee como "no existe".
    """
    docentes = []
    for _, nombre, rol in _buscar_profesor_scored(query):
        candidato = {'nombre': nombre}
        if rol:
            candidato['rol'] = rol
        docentes.append(candidato)

    preceptores = _preceptores_parecidos(query)
    if not docentes and not preceptores:
        return _sin_nadie_parecido(query)
    if not preceptores:
        return docentes

    salida = {'docentes': docentes}
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

    `permisos` no se usa hoy; queda en la firma porque `ejecutor_tool` se lo pasa a todas
    las tools de lectura de personas por igual.
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
                + _otros_padrones())
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
        # `clases.dia` viene del Sheet sin normalizar: hay filas con "Miercoles" sin tilde, que
        # comparadas contra DIAS no matcheaban y desaparecían del horario sin aviso. También
        # hay "Sábado" y filas en blanco, que no son días de cursada y sí se descartan.
        dia = database._dia_canonico(f['dia'])
        if not dia:
            continue
        if dia not in por_dia:
            por_dia[dia] = []
        linea = f"{f['hora_inicio']}–{f['hora_fin']} · {f['materia']} · {f['curso']}°{f['division']} · {f['aula']}"
        linea += _sufijo_grupo(f)
        if f.get('suplente_activo') == 1:
            linea += f" (suplente: {f['prof_suplente']})"
        por_dia[dia].append(linea)

    # Ordenar por día de la semana
    clases_ordenadas = {}
    for dia in DIAS:
        if dia in por_dia:
            clases_ordenadas[dia] = por_dia[dia]

    resultado = {'profesor': nombre_usado, 'clases': clases_ordenadas}
    if _hay_grupos(filas):
        resultado['nota_grupos'] = NOTA_GRUPOS
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
    """Horario de curso, formato interpretado.

    Normaliza antes de consultar: el modelo manda la división como la dijo el usuario, y las de
    4° a 7° son números que en castellano se escriben "5ta"/"9na". Con el string crudo la query
    daba cero filas y la respuesta era "no se encontraron clases", que es indistinguible de un
    curso que de verdad no tiene ninguna. Mismo criterio que `preceptores`.
    """
    par = _parsear_curso(f'{curso} {division}')
    if par:
        curso, division = par
    else:
        curso = database._extraer_num_curso(curso)
        division = database._extraer_num_curso(division).strip().upper()

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
        # `clases.dia` viene del Sheet sin normalizar: hay filas con "Miercoles" sin tilde, que
        # comparadas contra DIAS no matcheaban y desaparecían del horario sin aviso. También
        # hay "Sábado" y filas en blanco, que no son días de cursada y sí se descartan.
        dia = database._dia_canonico(f['dia'])
        if not dia:
            continue
        if dia not in por_dia:
            por_dia[dia] = []
        linea = f"{f['hora_inicio']}–{f['hora_fin']} · {f['materia']} · {f['profesor']} · {f['aula']}"
        linea += _sufijo_grupo(f)
        por_dia[dia].append(linea)

    clases_ordenadas = {}
    for dia in DIAS:
        if dia in por_dia:
            clases_ordenadas[dia] = por_dia[dia]

    resultado = {'curso': f'{curso}° {division}', 'clases': clases_ordenadas}
    if _hay_grupos(filas):
        resultado['nota_grupos'] = NOTA_GRUPOS
    return resultado

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
        # `clases.dia` viene del Sheet sin normalizar: hay filas con "Miercoles" sin tilde, que
        # comparadas contra DIAS no matcheaban y desaparecían del horario sin aviso. También
        # hay "Sábado" y filas en blanco, que no son días de cursada y sí se descartan.
        dia = database._dia_canonico(f['dia'])
        if not dia:
            continue
        if dia not in por_dia:
            por_dia[dia] = []
        linea = f"{f['hora_inicio']}–{f['hora_fin']} · {f['materia']} · {f['curso']}°{f['division']} · {f['profesor']}"
        linea += _sufijo_grupo(f)
        por_dia[dia].append(linea)

    clases_ordenadas = {}
    for dia in DIAS:
        if dia in por_dia:
            clases_ordenadas[dia] = por_dia[dia]

    resultado = {'aula': aula, 'clases': clases_ordenadas}
    if _hay_grupos(filas):
        resultado['nota_grupos'] = NOTA_GRUPOS
    return resultado

def _aulas_libres_fmt():
    """Aulas libres ahora."""
    return database.aulas_libres()


# ---------------------------------------------------------------------------
# coincidencias: cuándo varias entidades están en la escuela al mismo tiempo.
#
# La cuenta la hace Python, no el modelo. `deepseek-v4-pro` SÍ puede cruzarlos solo, pero con
# el payload viejo —tres `horario_curso` sueltos— acertó 2 de 6 sobre tres casos, quemando
# 9.400 a 12.000 tokens de razonamiento y hasta 6 minutos por respuesta; con cuatro cursos se
# comió el tope de salida sin escribir nada las dos veces. Y cuando falla, falla omitiendo un
# día entero, que es el lado que nadie audita. Con la grilla ya calculada: 3/3 en 15-28 s.
# Ver `dev-log/DECISIONS.md`.
# ---------------------------------------------------------------------------

INSTRUCCION_GRILLA = (
    'La respuesta es `tramos_coincidentes`: los días y horarios en que están todos a la vez, ya '
    'calculados. Leelos y contestá con eso, NO los recalcules. '
    'La grilla es el respaldo: cada tramo dice qué hace cada entidad en esa franja. El nombre de '
    'una materia (o de un curso, para un preceptor) es que está EN CLASE; "hueco" es un pozo '
    f'corto (hasta {HUECO_MAXIMO_MIN} min) entre dos clases, que cuenta como que sigue en la '
    'escuela; "hueco largo" es un pozo grande, que NO cuenta; "fuera" es que todavía no llegó o '
    'ya se fue. Los tramos coincidentes son los marcados `todos: true`. '
    'NO expliques nada de esto en la respuesta: no definas qué es coincidir, no cuentes cómo se '
    'calculó ni con qué criterio, no aclares que el dato no dice si se quedaron. Los horarios y '
    'listo. '
    'Si no coinciden, mirá la grilla y explicá por qué (quién se va antes, quién llega después).')

# La que va cuando la grilla no viajó. `INSTRUCCION_GRILLA` termina mandando a "mirar la
# grilla": con el detalle omitido eso es mandarlo a mirar algo que no está, que es pedirle que
# lo invente. Los tramos siguen siendo exactos —se calcularon sobre la grilla completa, antes
# de descartarla—; lo único que falta es el desglose entidad por entidad.
INSTRUCCION_SIN_GRILLA = (
    'Son muchas entidades y el detalle tramo por tramo se omitió por tamaño; te queda '
    '`tramos_coincidentes`, que son los días y horarios en que están todas a la vez. SON '
    'EXACTOS: se calcularon con todos los datos, no son una aproximación. Contestá con eso. '
    'NO expliques quién entra o se va a cada hora ni armes un desglose por entidad: ese dato no '
    'te llegó y no lo podés deducir. Tampoco cuentes cómo se calculó ni definas qué es '
    'coincidir. Si el usuario quiere el detalle, pedile menos cursos o un día concreto y volvé '
    'a llamar la tool.')

# El aviso que faltaba: un curso puede coincidir con alguien sólo porque tiene taller, y al
# taller va media división. Decir "está 7° 6ta" cuando está el Grupo A es contar el doble de
# gente de la que hay. Va con `medio_curso`, que trae los tramos exactos ya calculados.
NOTA_MEDIO_CURSO = (
    'OJO con `medio_curso`: en esos tramos el curso NO está entero, está sólo el grupo que dice '
    '(taller, media división). Avisalo en la respuesta, aclarando qué grupo es. Donde no figura '
    'en `medio_curso` está el curso completo: ahí no aclares nada.')

NOTA_PRECEPTORES_COINCIDENCIA = (
    'La ocupación de un preceptor es APROXIMADA y va por arriba: `horarios_preceptores` no '
    'guarda horas, así que se toman las clases de los cursos que tiene a cargo ese día. Si '
    'cubre un curso sólo en un turno, acá figura ocupado todas las horas de ese curso. Decilo '
    'como "está con tal curso", no como un horario exacto.')


def _parsear_curso(txt):
    """'2do C' → ('2', 'C'); '6to 5ta' → ('6', '5'); '4° 9na' → ('4', '9'). None si no se entiende.

    Los cursos de 4° a 7° tienen la división numerada, y en castellano eso se dice y se escribe
    "6ta"/"9na" — tal cual lo tipea el usuario y tal cual se lo pasa el modelo. En la base la
    división de esos años es un dígito pelado, así que sin esto la consulta daba cero filas y la
    respuesta era "no se encontraron clases", indistinguible de un curso que de verdad no tiene
    ninguna. Por eso las DOS partes pasan por `_extraer_num_curso`, no sólo el año.
    """
    s = database.eliminar_acentos(str(txt or '')).upper().replace('°', ' ')
    s = re.sub(r'\s+', ' ', s).strip()
    if not s:
        return None

    m = re.match(r'^(\d+)\s*(?:RO|DO|ER|TO|MO|MA|NO|VO)?\s+(.+)$', s)
    if m:
        curso, division = m.group(1), m.group(2)
    else:
        # "3B" todo pegado. Sólo con letra: "45" sería ambiguo entre año y división.
        m = re.match(r'^(\d)\s*([A-Z])$', s)
        if not m:
            return None
        curso, division = m.group(1), m.group(2)

    division = database._extraer_num_curso(division).strip().upper()
    return (curso, division) if curso and division else None


def _cursos_disponibles():
    """'1° A', '1° B', … tal como están en la base. Para el caso de curso inexistente."""
    con = database.conectar()
    cur = con.cursor()
    cur.execute("SELECT DISTINCT curso, division FROM clases WHERE curso != '' AND division != '' "
                "ORDER BY CAST(curso AS INTEGER), division")
    disponibles = [_etiqueta_curso(c, d) for c, d in cur.fetchall()]
    con.close()
    return disponibles


def _unir_ocupaciones(a, b):
    """Dos {dia: [(ini, fin, etiqueta, grupo)]} en uno. Para quien está en dos padrones a la vez."""
    unida = {dia: list(tramos) for dia, tramos in a.items()}
    for dia, tramos in b.items():
        ya = unida.setdefault(dia, [])
        ya.extend(t for t in tramos if t not in ya)
    for dia in unida:
        unida[dia].sort()
    return unida


def _candidatos_persona(nombre):
    """Candidatos de LOS DOS padrones juntos, de mejor a peor: (puntaje, tipo, etiqueta, extra).

    Docentes/no docentes y preceptores viven en tablas distintas y se buscan por separado en el
    resto del módulo. Acá van al mismo ranking a propósito: si un nombre puntúa parecido en los
    dos, eso es una ambigüedad real y hay que preguntar, no quedarse con el padrón que se miró
    primero.
    """
    q_norm = texto.norm(nombre or '')
    candidatos = [(puntaje, 'docente', n, rol)
                  for puntaje, n, rol in _buscar_profesor_scored(nombre)]

    for grupo in _alias_preceptores(_lista_preceptores()):
        puntaje = max(max(_puntaje_nombre(q_norm, texto.norm(v)),
                          texto.puntaje_busqueda(q_norm, v) or 0.0) for v in grupo)
        if puntaje >= 0.6:
            candidatos.append((puntaje, 'preceptor', grupo[0], grupo))

    candidatos.sort(reverse=True, key=lambda x: (x[0], x[2]))
    return candidatos[:5]


def _resolver_persona(nombre, permisos=frozenset()):
    """Nombre suelto → {'etiqueta', 'ocupacion', 'es_preceptor', 'comparable', 'nota'}, o {'error': {...}}.

    `comparable` es si esta persona se puede abrir en el modo comparación del calendario, que
    pinta bloques de `clases` y nada más: un preceptor no entra (su horario es una tabla, no un
    calendario) y un no docente puro tampoco (no tiene una sola fila en `clases`). Sale de acá
    porque es el único punto donde se sabe de qué padrón salió el nombre.
    """
    candidatos = _candidatos_persona(nombre)

    if not candidatos:
        error = {'error': f'No hay nadie parecido a "{nombre}" en los horarios.',
                 'nota': 'NO afirmes que no existe: se comparan letras, no personas. '
                         + _otros_padrones()}
        padron = _padron_completo_horarios()
        if padron:
            error['padron_completo'] = padron
        error['preceptores'] = sorted(_lista_preceptores())
        return {'error': error}

    # Mismo criterio que `horario_profesor` y `preceptores`: se auto-resuelve sólo si hay un
    # ganador claro; si están empatados se pregunta, no se elige.
    ganador_claro = len(candidatos) == 1 or candidatos[0][0] - candidatos[1][0] >= 0.15
    if not ganador_claro:
        return {'error': {
            'error': f'Hay varias personas parecidas a "{nombre}".',
            'sugerencias': [c[2] for c in candidatos],
            'nota': 'Preguntale al usuario cuál es en vez de elegir vos. NO inventes el horario.'}}

    _puntaje, tipo, nombre_usado, extra = candidatos[0]
    nota = None
    if texto.norm(nombre_usado) != texto.norm(nombre):
        nota = f'No hay coincidencia exacta con "{nombre}"; se usó "{nombre_usado}".'

    if tipo == 'preceptor':
        return {'etiqueta': nombre_usado, 'ocupacion': database.ocupacion_preceptor(extra),
                'es_preceptor': True, 'comparable': False, 'nota': nota}

    ocupacion = database.ocupacion_profesor(nombre_usado)
    da_clases = bool(ocupacion)
    if extra:
        # `extra` es el cargo no docente: da clases Y tiene un cargo, y está ocupada en los dos.
        # Quedarse con uno solo era perderle media agenda (RODRIGUEZ VIRGINIA, CALEI).
        ocupacion = _unir_ocupaciones(ocupacion, database.ocupacion_no_docente(nombre_usado))
    return {'etiqueta': nombre_usado, 'ocupacion': ocupacion, 'es_preceptor': False,
            'comparable': da_clases, 'nota': nota}


def _presencia(del_dia):
    """Las clases de un día → los bloques en que la entidad está EN LA ESCUELA.

    Dos clases separadas por `HUECO_MAXIMO_MIN` o menos son un mismo bloque: entre medio hay un
    recreo o un cambio de hora, no un viaje a la casa. No es una banda de la primera a la última
    clase: el 32% de los días-curso tienen un pozo en el medio (mediana 90 min, máximo 480), y
    esos pozos son irse y volver.
    """
    bloques = []
    for ini, fin, _lab, _g in sorted(del_dia):
        if bloques and ini - bloques[-1][1] <= HUECO_MAXIMO_MIN:
            bloques[-1][1] = max(bloques[-1][1], fin)
        else:
            bloques.append([ini, fin])
    return bloques


def _grilla(ocupaciones, dias):
    """{etiqueta: ocupacion} → ({dia: [tramo, ...]}, medio_curso), alineadas en el mismo eje.

    Se corta el día en cada frontera horaria de CUALQUIER entidad y se mira tramo por tramo, así
    los huecos no hay que modelarlos: se ven. Cada tramo dice, por entidad, la materia (está en
    clase), `hueco` / `hueco largo` (sin clase, dentro o fuera de su bloque de presencia) o
    `fuera` (no llegó todavía o ya se fue). `todos: true` es que ninguna está afuera ni en un
    hueco largo.

    `medio_curso` sale de la misma pasada: {etiqueta: {dia: [(de, a, grupo)]}} con los tramos
    coincidentes en que un curso entra con una sola de sus mitades (taller).
    """
    etiquetas = list(ocupaciones)
    grilla = {}
    medio_curso = {}

    for dia in dias:
        bordes = sorted({t for ocup in ocupaciones.values()
                         for ini, fin, _lab, _g in ocup.get(dia, []) for t in (ini, fin)})
        presencias = {e: _presencia(ocupaciones[e].get(dia, [])) for e in etiquetas}
        tramos = []
        for inicio, fin in zip(bordes, bordes[1:]):
            estados, mitades = {}, {}
            for etiqueta in etiquetas:
                del_dia = ocupaciones[etiqueta].get(dia, [])
                bloques = presencias[etiqueta]
                encima = sorted({(lab, g) for a, b, lab, g in del_dia if a <= inicio and b >= fin})
                if encima:
                    # Puede haber más de uno: media división en talleres (Grupo A y B), o un
                    # preceptor con dos cursos a cargo en la misma franja.
                    estados[etiqueta] = ' + '.join(f'{lab} · Grupo {g}' if g else lab
                                                   for lab, g in encima)
                    grupos = {g for _lab, g in encima}
                    if len(grupos) == 1 and '' not in grupos:
                        # Todo lo que cubre el tramo es del mismo grupo: está media división.
                        mitades[etiqueta] = grupos.pop()
                elif any(a <= inicio and b >= fin for a, b in bloques):
                    estados[etiqueta] = 'hueco'
                elif bloques and bloques[0][0] <= inicio and bloques[-1][1] >= fin:
                    estados[etiqueta] = 'hueco largo'
                else:
                    estados[etiqueta] = 'fuera'

            if all(e == 'fuera' for e in estados.values()):
                continue
            tramo = {'de': database.a_hhmm(inicio), 'a': database.a_hhmm(fin)}
            tramo.update(estados)
            if not any(e in ('fuera', 'hueco largo') for e in estados.values()):
                tramo['todos'] = True
                for etiqueta, grupo in mitades.items():
                    franjas = medio_curso.setdefault(etiqueta, {}).setdefault(dia, [])
                    if franjas and franjas[-1][1] == tramo['de'] and franjas[-1][2] == grupo:
                        franjas[-1][1] = tramo['a']
                    else:
                        franjas.append([tramo['de'], tramo['a'], grupo])
            tramos.append(tramo)

        if tramos:
            grilla[dia] = tramos
    return grilla, medio_curso


def _resumir(tramos):
    """Franjas de un día en que están todos, pegando las contiguas: ['10:00–13:00', …]."""
    juntos = []
    for tramo in tramos:
        if not tramo.get('todos'):
            continue
        if juntos and juntos[-1][1] == tramo['de']:
            juntos[-1][1] = tramo['a']
        else:
            juntos.append([tramo['de'], tramo['a']])
    return [f'{ini}–{fin}' for ini, fin in juntos]


def _coincidencias_fmt(cursos=None, personas=None, dia=None, contexto_turno=None):
    """Cuándo están varias entidades en la escuela a la vez, en una grilla alineada.

    Deja además en `contexto_turno['comparacion']` las entidades que el modo comparación del
    calendario sabe dibujar, para que la respuesta salga con el link que las abre superpuestas
    (lo arma `enlaces.enlace_comparacion`). Va por `contexto_turno` y no en lo que se devuelve
    porque es para el usuario, no para el modelo: un link en el resultado de la tool termina
    copiado a mano —y mal— en la respuesta.
    """
    cursos = [c for c in (cursos or []) if str(c).strip()]
    personas = [p for p in (personas or []) if str(p).strip()]

    ocupaciones = {}
    notas = []
    hay_preceptor = False
    comparables, sin_calendario = [], []

    for crudo in cursos:
        par = _parsear_curso(crudo)
        if not par:
            return {'error': f'No entendí qué curso es "{crudo}".',
                    'cursos_disponibles': _cursos_disponibles(),
                    'nota': 'Pasá el curso como lo dijo el usuario ("2do C", "6to 5ta") o como '
                            'figura en la lista. No inventes el horario.'}
        num, division = par
        etiqueta = _etiqueta_curso(num, division)
        ocupacion = database.ocupacion_curso(num, division)
        if not ocupacion:
            return {'error': f'No hay clases cargadas para {etiqueta} (pedido como "{crudo}").',
                    'cursos_disponibles': _cursos_disponibles(),
                    'nota': 'Fijate si el curso es alguno de la lista antes de decir que no '
                            'existe. Si está en la lista y no tiene clases, decilo así.'}
        ocupaciones[etiqueta] = ocupacion
        comparables.append(('curso', etiqueta))

    for crudo in personas:
        resuelta = _resolver_persona(crudo)
        if 'error' in resuelta:
            return resuelta['error']
        if not resuelta['ocupacion']:
            return {'error': f'{resuelta["etiqueta"]} no tiene horario cargado, así que no se '
                             'puede cruzar con nadie.',
                    'nota': 'Decilo tal cual: no es que no coincidan, es que falta el dato.'}
        ocupaciones[resuelta['etiqueta']] = resuelta['ocupacion']
        if resuelta.get('comparable'):
            comparables.append(('profesor', resuelta['etiqueta']))
        else:
            sin_calendario.append(resuelta['etiqueta'])
        hay_preceptor = hay_preceptor or resuelta['es_preceptor']
        if resuelta['nota']:
            notas.append(resuelta['nota'])

    if len(ocupaciones) < 2:
        # Distinguir "me pasaste una sola" de "me pasaste dos que son la misma": `"2do C"` y
        # `"2° C"` resuelven a la misma clave y colapsan, y decirle "hacen falta dos" cuando
        # dio dos lo deja dando vueltas sin entender qué le falta.
        if len(cursos) + len(personas) > 1:
            unica = next(iter(ocupaciones), None)
            return {'error': f'Todo lo que pasaste es la misma entidad ({unica}), escrita de '
                             'formas distintas. No hay nada que cruzar.',
                    'nota': 'Decíselo al usuario así. Si quería otra, pedile cuál.'}
        return {'error': 'Hacen falta al menos DOS entidades para cruzar horarios.',
                'nota': 'Pasá los cursos en `cursos` y las personas en `personas`. Para el '
                        'horario de una sola, usá `horario_curso` o `horario_profesor`.'}

    if dia:
        dia_pedido = database._dia_canonico(dia)
        if not dia_pedido:
            return {'error': f'"{dia}" no es un día de cursada.', 'dias_validos': list(DIAS)}
        dias = [dia_pedido]
    else:
        dias = list(DIAS)

    entidades = list(ocupaciones)
    grilla, medio_curso = _grilla(ocupaciones, dias)
    # Un solo resumen, y el hueco decide qué entra: 6°5 los miércoles tiene clase 07:40-09:40 y
    # vuelve 13:30, así que ahí no está aunque el día siga. Hasta `HUECO_MAXIMO_MIN` se cuenta
    # como que se quedó; más que eso, no.
    tramos_coincidentes = {d: _resumir(t) for d, t in grilla.items()}

    resultado = {
        'entidades': entidades,
        'tramos_coincidentes': tramos_coincidentes,
    }
    if medio_curso:
        resultado['medio_curso'] = {
            etiqueta: {dia: [f'{de}–{a} · Grupo {g}' for de, a, g in franjas]
                       for dia, franjas in por_dia.items()}
            for etiqueta, por_dia in medio_curso.items()}
        resultado['nota_grupos'] = NOTA_MEDIO_CURSO
    # La grilla se calcula siempre —los resúmenes salen de ella— pero no siempre viaja. Es el
    # 86% del payload con cuatro cursos y el 99% con sesenta, y ahí ya no explica nada: nadie
    # lee una tabla de 62 columnas para que le confirmen que no coinciden nunca. Los resúmenes
    # pesan ~500 tokens tenga 8 entidades o 62.
    cabe = len(json.dumps(grilla, ensure_ascii=False)) <= LIMITE_GRILLA_CHARS
    if cabe:
        resultado['grilla'] = grilla
    else:
        resultado['grilla_omitida'] = True
    resultado['instruccion'] = INSTRUCCION_GRILLA if cabe else INSTRUCCION_SIN_GRILLA
    if not any(tramos_coincidentes.values()):
        resultado['sin_coincidencias'] = True
        resultado['aviso'] = ('No hay ni un tramo con todos a la vez en los días consultados. '
                              'Es un resultado válido, no un error: '
                              + ('explicá con la grilla qué horarios se cruzan de a dos y cuál '
                                 'queda afuera.' if cabe else
                                 'decilo tal cual, sin inventar cuál es el que no encaja.'))
    if hay_preceptor:
        resultado['nota_preceptores'] = NOTA_PRECEPTORES_COINCIDENCIA
    if notas:
        resultado['nota'] = ' '.join(notas)

    # Con una sola entidad dibujable no hay nada que superponer y el link sobra.
    if contexto_turno is not None and len(comparables) >= 2:
        # Sin `dia`: el calendario comparado siempre muestra la semana entera, y filtrarlo
        # por un día sería prometer algo que la vista no hace.
        contexto_turno['comparacion'] = {'items': comparables, 'afuera': sin_calendario}
    return resultado
