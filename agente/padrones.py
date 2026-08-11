"""Los padrones de personas de la escuela, y los cruces entre ellos.

Los docentes salen de `escuela.db` (los horarios) y las fichas de personas de
`historia.db`. NO se superponen: un alumno que ganó una olimpiada tiene ficha y no da
clases; una profesora que nadie cargó da clases y no tiene ficha. El modelo los mezcla,
así que buscar una persona mira siempre los dos lados — y el aviso viaja en el resultado
de la tool, no en el system prompt, porque para cuando el modelo llamó ya eligió.

Los PRECEPTORES son una tercera fuente (`horarios_preceptores`) y tienen un trato
distinto: sus nombres están cargados sin normalizar ("ANGELINA", "KARINA (M RIOS)",
"FALTA"), así que NO entran al padrón difuso —ensuciarían las sugerencias de
`buscar_profesor`— y se consultan por su propia tool, que los devuelve ya digeridos
(una fila por curso, con titular y contraturno separados).

Vive fuera de `tools/` porque lo usan tanto las tools (horarios, entidades, fichas,
préstamos) como el system prompt, que inyecta la lista de personas conocidas.
"""
import difflib

import config
import crud
import database
import historia
import texto
from config import DIAS


# ============================================================================
# Funciones adaptadoras: traducen llamadas de tool al código ya existente
# ============================================================================

def _puntaje_nombre(q_norm, nombre_norm):
    """Similitud token a token, pensada para nombres de persona.

    `texto.puntaje_busqueda` compara la query entera contra el texto entero,
    así que "andrea alvares" puntuaba MÁS bajo contra "ALVAREZ ANDREA" (orden invertido)
    que contra "ALVARES LOURDES". Acá cada palabra de la query busca su mejor par en el
    nombre, con lo que el orden deja de importar y el typo se perdona.
    """
    q_tokens = [t for t in q_norm.split() if t]
    n_tokens = [t for t in nombre_norm.split() if t]
    if not q_tokens or not n_tokens:
        return 0.0
    total = sum(max(difflib.SequenceMatcher(None, qt, nt).ratio() for nt in n_tokens)
                for qt in q_tokens)
    return total / len(q_tokens)


def _padron_horarios():
    """Nombres del padrón de horarios: docentes de `clases` + personal no docente.

    Son dos tablas distintas de `escuela.db` y el SPA ya las fusiona en el autocompletado
    (docente o rol con badge); el agente tenía cargado solo `clases`, así que un EMATP o
    una jefa de departamento no existía para él. Devuelve nombre → rol no docente (o None
    si solo da clases), para poder decir de dónde salió cada candidato.
    """
    con = database.conectar()
    cur = con.cursor()
    cur.execute("SELECT DISTINCT profesor FROM clases WHERE profesor != '' ORDER BY profesor")
    padron = {r[0]: None for r in cur.fetchall()}
    con.close()
    for p in database.obtener_lista_personal():
        # El rol pisa el None: alguien puede estar en las dos tablas (da clases Y es EMATP).
        padron[p['nombre']] = p['rol']
    return padron


def _buscar_profesor_scored(query):
    """Candidatos con su puntaje, de mejor a peor. Lista de (puntaje, nombre, rol).

    `rol` es el cargo no docente (EMATP, jefatura…) o None si la persona solo da clases.
    Viaja junto al nombre porque el padrón ya lo tiene a mano y perderlo acá era el bug:
    CALEI salía como un candidato más, sin nada que dijera que es la EMATP de renovables.
    """
    padron = _padron_horarios()
    profesores = sorted(padron)

    if not query:
        return [(0.0, p, padron[p]) for p in profesores[:10]]

    q_norm = texto.norm(query)
    puntuados = []
    for prof in profesores:
        # El de texto.py premia substring (devuelve 1.0+); el token a token arregla
        # el orden invertido. Nos quedamos con el mejor de los dos.
        puntaje = max(_puntaje_nombre(q_norm, texto.norm(prof)),
                      texto.puntaje_busqueda(q_norm, prof) or 0.0)
        if puntaje >= 0.6:
            puntuados.append((puntaje, prof, padron[prof]))
    puntuados.sort(reverse=True, key=lambda x: (x[0], x[1]))
    return puntuados[:5]

def _personas_conocidas():
    """Nombres conocidos (profesores + personal no docente), para que el modelo pueda
    detectar nombres incompletos/mal escritos al registrar préstamos sin tener que
    buscarlos uno por uno con buscar_profesor."""
    return sorted(_padron_horarios())


def _roles_no_docentes(query=None):
    """Personal no docente filtrado por CARGO, no por nombre. [{'nombre', 'rol'}].

    Sin `query` devuelve el padrón entero (hoy son cuatro cargos). Con `query` filtra el
    rol con `_coincide_fuerte`, que resuelve tanto "ematp" (substring de "EMATP EERR")
    como "ematp de biologia" (palabra por palabra). Las siglas de la escuela —"EERR" por
    energías renovables— NO se traducen acá: cuando no matchea nada, la tool devuelve el
    padrón completo y el modelo reconoce la sigla, que es más barato de mantener que un
    diccionario de abreviaturas.
    """
    personal = database.obtener_lista_personal()
    q = texto.norm(query or '')
    if not q:
        return personal
    filtrados = [p for p in personal if _coincide_fuerte(q, p['rol'])]
    filtrados.sort(key=lambda p: (-(texto.puntaje_busqueda(q, p['rol']) or 0.0), p['nombre']))
    return filtrados


# ============================================================================
# Preceptores: la tercera fuente, y la única que hay que digerir antes de mostrar
# ============================================================================

# La planilla usa estos textos donde todavía no hay nadie asignado. Devolverlos como si
# fueran un nombre hace que el agente le conteste a un alumno que su preceptora se llama
# "FALTA", así que se reportan como un hueco, no como una persona.
PRECEPTOR_SIN_ASIGNAR = {'FALTA', 'FALTAN', 'SIN ASIGNAR', ''}


def _etiqueta_curso(curso, division):
    """('1', 'A') → '1° A'. La división puede venir vacía o ser un número (4° 3)."""
    return f"{curso}° {division}".strip()


def _turno_titular(curso, division):
    """Turno en el que ese curso cursa; el resto de sus preceptores son de contraturno.

    Mismo criterio que `database.obtener_horario_preceptor()`, que ya marca cada fila como
    titular o contraturno con este mapa. Un curso que no esté en `TURNO_CURSOS` cae al
    default, igual que allá.
    """
    return config.TURNO_CURSOS.get((str(curso), str(division)), config.TURNO_DEFAULT)


def _filas_preceptores():
    """Las filas crudas de `horarios_preceptores`: una por curso × turno × día."""
    con = database.conectar()
    filas = con.execute(
        "SELECT curso, division, turno, preceptor, dia FROM horarios_preceptores"
    ).fetchall()
    con.close()
    return filas


def _preceptores_por_curso():
    """La planilla de preceptores ya digerida: {(curso, division): ficha}.

    De 595 filas crudas quedan 64 fichas, una por curso:
    `{'curso': '1° A', 'turno_del_curso': 'MAÑANA', 'titular': [entrada],
      'contraturno': [entrada]}`, donde cada entrada es `{'preceptor', 'turno'}` — más `dias`
    SOLO si esa persona no cubre la semana entera (pasa en los cursos donde dos preceptores
    se reparten los días), y `sin_asignar` en vez de `preceptor` cuando la planilla no tiene
    a nadie.

    Dos campos existen para que el modelo NO tenga que deducir nada:

    - `turno_del_curso`: antes el turno en que cursa el curso era sólo *inferible* leyendo el
      `turno` de lo que hubiera caído en `titular` — y en los 7 cursos donde `titular` viene
      vacío ni siquiera eso. Preguntado por 7° 6 (que cursa vespertino) el modelo contestó
      "cursa a la tarde"; ahora el dato viene escrito.
    - `turnos_sin_nadie`: los turnos que no tienen NINGUNA fila para ese curso. La ficha se
      arma sólo con las filas que existen, así que un turno vacío antes no aparecía por
      ningún lado y "¿y a la mañana?" era literalmente incontestable con este payload. No es
      lo mismo que `sin_asignar`: eso es la planilla diciendo FALTA, esto es no haber fila.
    """
    dia_por_norm = {texto.norm(d): d for d in DIAS}
    orden_dia = {d: i for i, d in enumerate(DIAS)}

    # (curso, division, turno, preceptor) → días
    dias_por_grupo = {}
    for curso, division, turno, preceptor, dia in _filas_preceptores():
        clave = (curso, division, turno, (preceptor or '').strip())
        dias_por_grupo.setdefault(clave, set()).add(dia_por_norm.get(texto.norm(dia), dia))

    fichas = {}
    turnos_con_gente = {}
    for (curso, division, turno, preceptor), dias in dias_por_grupo.items():
        ficha = fichas.setdefault((curso, division), {
            'curso': _etiqueta_curso(curso, division),
            'turno_del_curso': _turno_titular(curso, division),
            'titular': [], 'contraturno': []})
        turnos_con_gente.setdefault((curso, division), set()).add(turno)
        entrada = {'turno': turno}
        if preceptor.upper() in PRECEPTOR_SIN_ASIGNAR:
            entrada['sin_asignar'] = True
        else:
            entrada['preceptor'] = preceptor
        if len(dias) < len(DIAS):
            entrada['dias'] = sorted(dias, key=lambda d: orden_dia.get(d, 99))
        donde = 'titular' if turno == ficha['turno_del_curso'] else 'contraturno'
        ficha[donde].append(entrada)

    for clave, ficha in fichas.items():
        for donde in ('titular', 'contraturno'):
            ficha[donde].sort(key=lambda e: (e['turno'], e.get('preceptor', '')))
        # Sólo cuando hay huecos: en un curso con los tres turnos cubiertos el campo sería ruido.
        vacios = [t for t in database.TURNOS if t not in turnos_con_gente[clave]]
        if vacios:
            ficha['turnos_sin_nadie'] = vacios
    return fichas


def _lista_preceptores():
    """Nombres de preceptores cargados, sin los marcadores de vacante."""
    return [n for n in database.obtener_lista_preceptores_horario()
            if n.strip().upper() not in PRECEPTOR_SIN_ASIGNAR]


def _preceptores_parecidos(query):
    """Preceptores que coinciden fuerte con `query`. Para el cruce de `buscar_profesor`.

    Es el mismo criterio estricto que los otros cruces de padrón: un preceptor aparece
    como sugerencia lateral —"ese nombre es un preceptor, mirá la otra tool"— sin entrar
    al padrón difuso, donde sus nombres sin normalizar ensuciarían las sugerencias.
    """
    q = texto.norm(query or '')
    if not q:
        return []
    return [n for n in _lista_preceptores() if _coincide_fuerte(q, n)]


def _personas_cargadas():
    """[(id, nombre)] de todas las personas, para cruzar nombres contra texto libre.
    `personas` vive en historia.db (se separó de gestion.db) — ver dev-log/DECISIONS.md."""
    con = crud.conectar(historia)
    filas = con.execute("SELECT id, nombre FROM personas WHERE TRIM(nombre) <> ''").fetchall()
    con.close()
    return [(f[0], f[1]) for f in filas]


def _coincide_fuerte(q_norm, nombre):
    """¿`nombre` coincide con lo buscado lo bastante como para cruzarlo de padrón?

    Los cruces entre los dos padrones de personas (ver `_buscar_profesor` y
    `_buscar_entidad_fmt`) usan esto en vez del puntaje de las búsquedas normales. Un cruce
    es una sugerencia lateral: si no es fuerte, conviene callarse.

    Substring alcanza, pero no basta con eso: los apodos del castellano no son prefijos
    ("nati" no es substring de "natalia"), y ese era justo el caso que motivó todo esto. Así
    que se compara **palabra por palabra** con `texto.UMBRAL_SIMILITUD`, el mismo del resto del
    sistema — no con el 0.6 laxo de `_buscar_profesor_scored`, que ofrece candidatos a
    propósito. La diferencia se nota: con 0.6, "nati" traía PETRATE MATIAS (0.60 contra
    "matias") y "calei" traía PRIETO VALERIA; con 0.68, "nati" sigue trayendo Natalia (0.73)
    y esos dos se caen.
    """
    n = texto.norm(nombre or '')
    if not q_norm or not n:
        return False
    if q_norm in n:
        return True
    palabras = n.split()
    for parte in q_norm.split():
        if len(parte) < 3:
            continue
        if any(difflib.SequenceMatcher(None, parte, p).ratio() >= texto.UMBRAL_SIMILITUD
               for p in palabras):
            return True
    return False


def _personas_parecidas(query):
    """Personas con ficha que coinciden con `query`, de mejor a peor. [(id, nombre)].

    Es el complemento suelto de `_personas_nombradas_en`: acá alcanza con que matchee
    parcialmente ("nati" → "Natalia Boo Fiad"), porque el resultado es un AVISO para que el
    modelo pregunte, no un vínculo que se escriba solo. La regla estricta de nombre completo
    sigue siendo la que decide a quién se vincula de verdad.
    """
    q = texto.norm(query or '')
    if not q:
        return []
    puntuadas = []
    for pid, nombre in _personas_cargadas():
        if not _coincide_fuerte(q, nombre):
            continue
        puntuadas.append((texto.puntaje_busqueda(q, nombre) or 1.0, pid, nombre))
    puntuadas.sort(key=lambda x: (-x[0], x[2]))
    return [(pid, nombre) for _, pid, nombre in puntuadas]


def _gente_horarios_parecida(query):
    """Gente de los horarios que coincide con `query`. Espejo de `_personas_parecidas`.

    Devuelve [(nombre, rol)] — `rol` es el cargo no docente o None. No se llama
    `_docentes_parecidos` porque el padrón dejó de ser solo docentes cuando se le sumó
    `personal_no_docente`, y el nombre viejo empujaba a los avisos a decirle "docente" a
    un EMATP.
    """
    q = texto.norm(query or '')
    if not q:
        return []
    return [(n, rol) for _, n, rol in _buscar_profesor_scored(query) if _coincide_fuerte(q, n)]


def _personas_nombradas_en(frase):
    """Personas ya cargadas cuyo nombre aparece en `frase`.

    Compara normalizado (sin acentos ni mayúsculas) y acepta el orden dado vuelta
    ("Errio Pablo"), que es como aparece medio inventario. Devuelve [(id, nombre)].
    Solo matchea nombres COMPLETOS: un "Pablo" suelto no alcanza, porque puede haber
    dos y vincular a la persona equivocada es peor que no vincular.
    """
    t = texto.norm(frase or '')
    if not t:
        return []
    encontradas = []
    for pid, nombre in _personas_cargadas():
        partes = [p for p in texto.norm(nombre).split() if len(p) > 2]
        if partes and all(p in t for p in partes):
            encontradas.append((pid, nombre))
    return encontradas
