"""Los dos padrones de personas de la escuela, y el cruce entre ellos.

Los docentes salen de `escuela.db` (los horarios) y las fichas de personas de
`historia.db`. NO se superponen: un alumno que ganó una olimpiada tiene ficha y no da
clases; una profesora que nadie cargó da clases y no tiene ficha. El modelo los mezcla,
así que buscar una persona mira siempre los dos lados — y el aviso viaja en el resultado
de la tool, no en el system prompt, porque para cuando el modelo llamó ya eligió.

Vive fuera de `tools/` porque lo usan tanto las tools (horarios, entidades, fichas,
préstamos) como el system prompt, que inyecta la lista de personas conocidas.
"""
import difflib

import crud
import database
import historia
import texto


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
    """Candidatos con su puntaje, ordenados de mejor a peor. Lista de (puntaje, nombre)."""
    profesores = sorted(_padron_horarios())

    if not query:
        return [(0.0, p) for p in profesores[:10]]

    q_norm = texto.norm(query)
    puntuados = []
    for prof in profesores:
        # El de texto.py premia substring (devuelve 1.0+); el token a token arregla
        # el orden invertido. Nos quedamos con el mejor de los dos.
        puntaje = max(_puntaje_nombre(q_norm, texto.norm(prof)),
                      texto.puntaje_busqueda(q_norm, prof) or 0.0)
        if puntaje >= 0.6:
            puntuados.append((puntaje, prof))
    puntuados.sort(reverse=True, key=lambda x: (x[0], x[1]))
    return puntuados[:5]

def _personas_conocidas():
    """Nombres conocidos (profesores + personal no docente), para que el modelo pueda
    detectar nombres incompletos/mal escritos al registrar préstamos sin tener que
    buscarlos uno por uno con buscar_profesor."""
    return sorted(_padron_horarios())


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


def _docentes_parecidos(query):
    """Docentes de los horarios que coinciden con `query`. Espejo de `_personas_parecidas`."""
    q = texto.norm(query or '')
    if not q:
        return []
    return [n for _, n in _buscar_profesor_scored(query) if _coincide_fuerte(q, n)]


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
