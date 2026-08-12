"""Lo que se limpia de la respuesta antes de mostrarla y ANTES de persistirla.

Dos filtros, misma lógica de fondo: la regla está en el system prompt, pero va también
como filtro de salida porque el prompt el modelo lo cumple a veces. Se aplican antes de
guardar para que el historial repintado tampoco los traiga — y, en el caso de las
acotaciones, para que el turno siguiente no arranque con el ejemplo malo a la vista.

  _ocultar_ids         los id son cañería: el modelo los necesita, el usuario no.
  _quitar_acotaciones  Emilio cuenta, no actúa: no tiene cuerpo con el que gesticular.

Acá viven también las utilidades de contexto (pregunta relativa, entidad mencionada) y
la red de seguridad que detecta cuando el modelo anuncia una escritura que no ejecutó.
"""
import re

# ============================================================================
# Utilidades para mantener contexto
# ============================================================================

def _es_pregunta_relativa(pregunta):
    """Detecta si la pregunta es relativa (se refiere a algo mencionado antes)."""
    patrones = [
        'qué lugar', 'dónde', 'aula', 'piso',  # ubicación
        'cuántos', 'cantidad', 'stock',  # cantidad
        'cuándo', 'horario', 'clase',  # horario
        'estado', 'ubicación',  # estado del recurso
        'en qué', 'en dónde', 'en donde',
        'dónde tiene', 'ubicado', 'está en',
    ]
    p_lower = pregunta.lower()
    return any(patron in p_lower for patron in patrones) and len(pregunta.split()) <= 8

def _extraer_entidad_mencionada(respuesta_anterior, tipo='profesor'):
    """Extrae el nombre de la entidad de una respuesta anterior."""
    # Buscar patrones como "Horario de NOMBRE:" o "**NOMBRE**"
    import re
    # Patrón 1: "Horario de NOMBRE:" o "**Horario de NOMBRE:**"
    match = re.search(r'(?:de|del)\s+(?:\*{1,2})?(\w+(?:\s+\w+)?)\*{0,2}[:\s]', respuesta_anterior, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    # Patrón 2: "**NOMBRE**:"
    match = re.search(r'\*\*([A-Z\s]+)\*\*:', respuesta_anterior)
    if match:
        return match.group(1).strip()
    return None

# Se deriva de PERMISO_POR_TOOL, que es la única fuente de verdad: antes esta lista era
# una copia a mano y había que acordarse de tocarla al sumar una tool de escritura.
from .tools.esquemas import TOOLS_ESCRITURA  # noqa: E402,F401


def _escritura_no_ejecutada(respuesta, trazas):
    """True si la respuesta anuncia un cambio hecho pero ninguna escritura corrió con éxito.

    Detector de código, no de prompt: en las pruebas el modelo respondía "✅ Recurso
    eliminado" / "✅ Desvinculado" sin haber llamado a ninguna tool, y el usuario no
    tenía forma de notarlo. El "✅" es la señal: el modelo lo usa solo cuando afirma
    haber ejecutado algo (para pedir confirmación escribe "voy a..." sin tilde verde),
    así que no dispara falsos positivos al resumir un cambio de un turno anterior.
    """
    if '✅' not in (respuesta or ''):
        return False
    return not any(t.get('tool') in TOOLS_ESCRITURA and t.get('ok') for t in trazas)


# ---------------------------------------------------------------------------
# Ocultar ids internos en lo que ve el usuario
# ---------------------------------------------------------------------------
# Los ids son la cañería con la que se enganchan las filas: el modelo los necesita para
# llamar a las tools, pero al usuario no le dicen nada (ni la web de /gestion los muestra,
# solo los usa en las URLs). Igual el modelo los repetía en casi toda respuesta de lectura
# — "Multímetro (ID 4)", "préstamo #2", una columna ID en la tabla de préstamos.
#
# Va como filtro de salida y no solo como regla del prompt porque es exactamente el tipo
# de regla que este agente cumple a veces: acá el peor caso de fallar es ruido en pantalla,
# así que conviene que sea determinístico.

_RE_PAREN_SOLO_ID = re.compile(r'\s*\((?:ID|Id|id)\s*[:=#n°º]*\s*\d+\)')   # "Multímetro (ID 4)"
_RE_ID_INLINE = re.compile(r'\b(?:ID|Id|id)\s*[:=#]?\s*\d+\s*[,;·–—-]?\s*')  # "(ID 2, Lucas...)"
_RE_NUMERAL = re.compile(r'\s*#\s*\d+\b')                                   # "préstamo #2"


def _quitar_columna_id(cadena):
    """Saca la columna ID de las tablas markdown que devuelve el modelo.

    Con regex sobre todo el cadena no alcanza: hay que borrar la misma posición en el
    encabezado, en la fila separadora y en cada fila de datos.
    """
    lineas = cadena.split('\n')
    salida, i = [], 0
    while i < len(lineas):
        cabecera = lineas[i]
        celdas = [c.strip() for c in cabecera.strip().strip('|').split('|')]
        idx = next((n for n, c in enumerate(celdas) if c.strip('* ').lower() == 'id'), None)
        es_tabla = (cabecera.strip().startswith('|') and idx is not None
                    and i + 1 < len(lineas) and set(lineas[i + 1].strip()) <= set('|-: '))

        if not es_tabla:
            salida.append(cabecera)
            i += 1
            continue

        while i < len(lineas) and lineas[i].strip().startswith('|'):
            partes = lineas[i].strip().strip('|').split('|')
            if len(partes) > idx:
                del partes[idx]
            salida.append('|' + '|'.join(partes) + '|')
            i += 1
    return '\n'.join(salida)


def _ocultar_ids(respuesta):
    """Quita del salida los ids internos que el usuario no tiene por qué ver."""
    if not respuesta:
        return respuesta
    salida = _quitar_columna_id(respuesta)
    salida = _RE_PAREN_SOLO_ID.sub('', salida)
    salida = _RE_ID_INLINE.sub('', salida)
    salida = _RE_NUMERAL.sub('', salida)
    # El barrido deja restos: paréntesis vacíos ("Multímetro ( )"), comas al empezar un
    # paréntesis, y guiones sueltos donde el id era lo único que seguía ("Amoladora — id 100.").
    salida = re.sub(r'\(\s*[,;·–—-]?\s*\)', '', salida)
    salida = re.sub(r'\(\s*[,;]\s*', '(', salida)
    salida = re.sub(r'\s*[–—-]\s*([.,;:!?)])', r'\1', salida)
    salida = re.sub(r'\s*[–—-]\s*$', '', salida, flags=re.MULTILINE)
    salida = re.sub(r'[ \t]{2,}', ' ', salida)
    salida = re.sub(r' +([,.;:)])', r'\1', salida)
    return salida.strip()


# ---------------------------------------------------------------------------
# Quitar acotaciones de guion
# ---------------------------------------------------------------------------
# Mismo criterio que _ocultar_ids: la regla está en el prompt, pero va TAMBIÉN como filtro
# de salida. En cuanto se activa el personaje de Emilio el modelo pasa a actuarlo —
# "*se acomoda los anteojos*", "—mirando el patio—", "EMILIO:" antes de hablar — y pedirle
# por texto que no lo haga es de las reglas que cumple a veces: el provider por default
# (DeepSeek, ver cabecera) imita del contexto más de lo que razona sobre una regla de estilo,
# y encima los resultados de tools no se persisten, así que en los turnos de seguimiento el
# único ejemplo que tiene a la vista es su propia respuesta actuada del turno anterior.
#
# El filtro es a propósito conservador: borra el tramo solo si parece un gesto de verdad
# (reflexivo, gerundio o una palabra de la lista) y no tiene números. Preferimos que se
# escape una acotación rara antes que borrar contenido real — "*Panel solar 100 W*" en
# cursiva es un dato del inventario, no una acotación.

# Palabras que solas ya son un gesto: "*sonríe*", "*pausa*". Van aparte de _RE_GESTO_CUE
# porque para el resto de los casos exigimos una frase (una cursiva de una palabra suele ser
# énfasis). Ojo con agregar verbos que existan en imperativo — "mirá" es una cursiva legítima.
_RE_GESTO_PALABRA = re.compile(
    r'(?:pausa|silencio|suspir[ao]|risas?|r[íi]e|sonr[íi]e|carraspea|asiente|susurra'
    r'|\w{2,}(?:ando|[eé]ndo)(?:se)?)')             # "*riéndose*", "*mirando*"

_RE_GESTO_CUE = re.compile(
    r'^(?:se|me|te|le|nos)\s'                        # "se acomoda los anteojos"
    r'|\b\w{2,}(?:ando|[eé]ndo)(?:se)?\b'            # gerundios: "mirando", "riéndose"
    r'|\b(?:pausa|silencio|suspir\w*|risas?|r[íi]e|sonr\w*|carraspe\w*|asiente|susurr\w*|'
    r'mira\w*|se[ñn]al\w*|voz\s+baja|baja\s+la\s+voz|aclara\s+la\s+garganta)\b'
)

_RE_CURSIVA = re.compile(r'(?<!\*)\*(?!\*)([^*\n]{3,140})\*(?!\*)')   # *se acomoda los anteojos*
_RE_CORCHETE = re.compile(r'\[([^\]\n]{3,140})\]')                    # [mirando por la ventana]
_RE_RAYA = re.compile(r'\s*[—–]\s*([^—–\n]{3,140}?)\s*[—–]')          # —mirando el patio—
_RE_ETIQUETA_GUION = re.compile(                                      # "EMILIO:" / "**Emilio:**"
    r'^\s*\**\s*(?:EMILIO|Emilio)(?:\s+MITRE|\s+Mitre)?\s*\**\s*:\s*\**\s*', re.MULTILINE)


def _parece_gesto(txt):
    """True si el tramo entre marcas es una acotación y no contenido real.

    Nunca borra un tramo con números: los datos técnicos y las fechas los tienen, las
    acotaciones no. De ahí en más pide una frase con señal de gesto, o una sola palabra que
    ya sea un gesto por sí misma.
    """
    t = txt.strip().lower()
    if any(c.isdigit() for c in t):
        return False
    if ' ' not in t:
        return bool(_RE_GESTO_PALABRA.fullmatch(t.strip('.…!')))
    return bool(_RE_GESTO_CUE.search(t))


# Acotaciones SIN marcar. Prohibirle las marcas no le quita la costumbre de actuar: encuentra
# la vuelta y escribe el mismo gesto como prosa suelta ("Baja la voz, se acerca un poco." /
# "Se encoge de hombros."). La señal que las delata es gramatical: Emilio cuenta en primera
# persona y las historias están en pasado, así que una oración corta, entera en tercera persona
# del presente y sin sujeto solo puede ser él describiéndose desde afuera.
#
# Se listan los núcleos a mano en vez de inferir la conjugación: la lista se queda corta ante
# un gesto nuevo, pero no se come una oración real, que es el error caro.
_GESTO_NUCLEO = r'''(?:
      (?:se\s+)?(?:baja|sube|levanta)\s+(?:un\s+poco\s+)?la\s+(?:voz|vista|mirada)
    | se\s+encoge\s+de\s+hombros | encoge\s+los\s+hombros
    | se\s+(?:acerca|aleja|inclina|endereza|detiene|acomoda|aparta|frota|persigna)\w*
    | se\s+queda\s+(?:un\s+rato\s+)?(?:en\s+silencio|callad\w+|pensand\w+|mirand\w+)
    | se\s+r[íi]e(?:\s+por\s+lo\s+bajo)? | r[íi]e\s+por\s+lo\s+bajo
    | se\s+pasa\s+la\s+mano | se\s+seca\s+\w+
    | hace\s+(?:una\s+)?(?:pausa|silencio)
    | sonr[íi]e(?:\s+de\s+costado)? | suspira | asiente | carraspea | tose
    | (?:niega|asiente)\s+con\s+la\s+cabeza | aclara\s+la\s+garganta
    | mira\s+(?:alrededor|hacia\s+\w+|para\s+otro\s+lado|al?\s+\w+|el\s+\w+|la\s+\w+)
    | entrecierra\s+los\s+ojos | gui[ñn]a\s+un\s+ojo
    | pausa(?:\s+larga)? | silencio\s+largo
)'''

# Cada cláusula: conector opcional + núcleo de gesto + hasta 3 palabras de coletilla
# ("un poco", "los anteojos", "de nuevo").
_RE_CLAUSULA_GESTO = re.compile(
    r'^(?:y|pero|entonces|ah[íi]|acá|aca)?\s*' + _GESTO_NUCLEO + r'(?:\s+\w+){0,3}[.…!]?$',
    re.VERBOSE | re.IGNORECASE)

# Parte el texto en oraciones conservando el separador, para poder rearmarlo idéntico.
_RE_ORACION = re.compile(r'[^.!?…\n]+[.!?…]*')


def _es_oracion_gesto(oracion):
    """True si la oración entera es una acotación en prosa, sin marcas.

    Exige que TODAS sus cláusulas sean gestos: "Baja la voz, se acerca un poco." se va
    completa, pero "Sonríe y sigue la clase como si nada" se queda, porque la segunda mitad
    dice algo. Con números no se toca nada, igual que en `_parece_gesto`.
    """
    t = oracion.strip()
    if not t or any(c.isdigit() for c in t):
        return False
    if len(t.split()) > 12:
        return False
    clausulas = [c for c in re.split(r'\s*[,;]\s*|\s+y\s+', t) if c.strip()]
    if not clausulas:
        return False
    return all(_RE_CLAUSULA_GESTO.match(c.strip()) for c in clausulas)


def _quitar_oraciones_gesto(cadena):
    """Borra las oraciones que son puramente acotación, dejando el resto intacto."""
    salida = []
    for linea in cadena.split('\n'):
        oraciones = _RE_ORACION.findall(linea)
        if not oraciones:
            salida.append(linea)
            continue
        quedan = [o for o in oraciones if not _es_oracion_gesto(o)]
        if len(quedan) == len(oraciones):
            salida.append(linea)          # sin cambios: se conserva la línea original tal cual
        else:
            salida.append(' '.join(o.strip() for o in quedan))
    return '\n'.join(salida)


def _quitar_acotaciones(respuesta):
    """Saca del salida las acotaciones de gestos y las marcas de guion de teatro."""
    if not respuesta:
        return respuesta

    def _sub(m):
        return '' if _parece_gesto(m.group(1)) else m.group(0)

    salida = _RE_ETIQUETA_GUION.sub('', respuesta)
    salida = _RE_CURSIVA.sub(_sub, salida)
    salida = _RE_CORCHETE.sub(_sub, salida)
    salida = _RE_RAYA.sub(_sub, salida)
    salida = _quitar_oraciones_gesto(salida)
    # Restos del barrido: espacios dobles, espacio antes de puntuación y líneas que
    # quedaron vacías porque no tenían más que la acotación.
    salida = re.sub(r'[ \t]{2,}', ' ', salida)
    salida = re.sub(r' +([,.;:!?)])', r'\1', salida)
    salida = re.sub(r'^[ \t]+$', '', salida, flags=re.MULTILINE)
    salida = re.sub(r'\n{3,}', '\n\n', salida)
    return salida.strip()


AVISO_NO_EJECUTADO = (
    "⚠️ **OJO: esto NO se ejecutó.** El asistente informó un cambio que nunca llegó a la "
    "base de datos (no corrió ninguna operación de escritura en este turno). Volvé a pedirlo "
    "explícitamente y verificá en la pantalla correspondiente antes de darlo por hecho.\n\n"
    "_Respuesta original del asistente:_\n\n"
)
