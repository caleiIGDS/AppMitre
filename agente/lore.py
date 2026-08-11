"""La historia de la escuela, contada por Emilio Mitre.

Los textos son literales de `historias/*.json`: nunca se improvisan. Acá viven también
las constantes que definen la voz del personaje (quién es, cómo cuenta, y con qué zafa
cuando no tiene la historia), que se interpolan tanto en la instrucción de tono de cada
historia como en el system prompt.

OJO: esto es el LORE (anécdotas, guiños). No confundir con el módulo `historia` de la
raíz, que es la línea del tiempo institucional (hitos y personas) — ver dev-log/DECISIONS.md.
"""
import difflib
import json
import os

import texto

from .dominio import RAIZ
HISTORIA_INDICE_PATH = os.path.join(RAIZ, 'historia_indice.json')
HISTORIA_DIR_PATH = os.path.join(RAIZ, 'historias')

# ---------------------------------------------------------------------------
# Historia de la escuela (lore + guiños internos)
# ---------------------------------------------------------------------------

HISTORIA_PATH = os.path.join(RAIZ, 'historia_escuela.json')
# Umbral del match difuso contra las claves. Más alto que el 0.68 del inventario a
# propósito: acá un falso positivo hace que el asistente conteste una anécdota que no
# tiene nada que ver con lo que preguntaron, y las claves son pocas y bien elegidas
# (no hay 91 nombres compitiendo), así que se puede exigir más.
HISTORIA_UMBRAL = 0.72

_historia_indice_cache = {'mtime': None, 'datos': []}


def _cargar_historia_indice():
    """Índice de historias, recargado si el archivo cambió.

    Cachea el índice pero no el contenido de textos. Así en turnos normales
    no se paga el costo de leer historias.
    """
    try:
        mtime = os.path.getmtime(HISTORIA_INDICE_PATH)
    except OSError:
        return []
    if _historia_indice_cache['mtime'] != mtime:
        try:
            with open(HISTORIA_INDICE_PATH, encoding='utf-8') as f:
                datos = json.load(f)
                indice = datos.get('indice', [])
                # Filtrar: solo entradas con claves e id válido
                _historia_indice_cache['datos'] = [
                    e for e in indice
                    if e.get('claves') and e.get('id') and not e.get('_prueba', False)
                ]
        except (ValueError, OSError):
            _historia_indice_cache['datos'] = []
        _historia_indice_cache['mtime'] = mtime
    return _historia_indice_cache['datos']


def _cargar_historia_completa(id_historia):
    """Lee el archivo individual de una historia completa.

    No se cachea porque se lee bajo demanda y es pequeño.
    Devuelve None si no existe o hay error.
    """
    try:
        path = os.path.join(HISTORIA_DIR_PATH, f'{id_historia}.json')
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (ValueError, OSError, FileNotFoundError):
        return None


# Se repite en el system prompt y en la instrucción de cada historia: el modelo tiende a
# "actuar" el personaje de Emilio en cuanto le decís que hable en primera persona. Ojo: como
# los resultados de tools NO se persisten en el historial, en los turnos de seguimiento
# ("¿y después qué pasó?") lo único que queda en contexto es la copia del system prompt.
#
# Está redactado como instructivo de qué hacer, no como lista de prohibiciones, por dos
# motivos: una regla negativa le deja al modelo el trabajo de deducir la forma correcta (y lo
# deduce mal), y para explicar qué NO hacer hay que escribir el ejemplo malo en el prompt —
# que es exactamente lo que después imita. Acá no aparece ni una acotación de muestra: la
# regla se aplica sola con el test de la última línea. Las formas mecánicas que igual se le
# escapan las levanta `_quitar_acotaciones()`, que es el otro lado de la defensa.
COMO_CUENTA_EMILIO = (
    'CÓMO CONTÁS: escribís únicamente las palabras que Emilio dice en voz alta. La respuesta es '
    'lo que escucharía alguien parado al lado tuyo en el pasillo, nada más. '
    'Arrancá directo por el hecho: el primer renglón ya cuenta algo que pasó. '
    'Hablás en primera persona, como en una charla ("eso lo vi yo", "me acuerdo del ruido"). '
    'No tenés cuerpo, así que no hay nada que hacer con él mientras hablás: el clima y la emoción '
    'los transmitís con lo que decís y cómo lo decís. Si la historia es un secreto, decí "esto no '
    'lo repitas"; si el final da para resignarse, decí "y bueno, así es acá". '
    'TEST antes de responder: leé cada oración y preguntate si se puede pronunciar. Lo que se '
    'hace en vez de decirse no entra, y tu nombre no va adelante de lo que hablás: acá el único '
    'que habla sos vos.'
)

# La voz del personaje, aparte de la forma. Va solo en el circuito de historias: para horarios
# y préstamos Emilio sigue siendo una herramienta neutra (ver DECISIONS 2026-08-08, "agente
# bifásico"). Sin esto las historias salían correctas pero anónimas — leídas seguidas parecían
# el conserje contando una anécdota, no el fantasma que se cree dueño del edificio.
QUIEN_ES_EMILIO = (
    'CON QUIÉN HABLÁS: el que pregunta ya sabe quién sos. No te presentes, no expliques que sos '
    'un fantasma ni cómo llegaste a estar acá, no aclares que la escuela lleva tu nombre y no '
    'pidas permiso para empezar. Entrás directo, con la familiaridad del que es dueño de la casa '
    'y sabe que el otro está de visita. '
    'TU ORGULLO: sabés todo lo que pasa en esta escuela y te encanta que se note. Contás como el '
    'único que estuvo ahí, y dejás caer que nadie más lo vio ("de eso no queda nadie que se '
    'acuerde, salvo yo"). Un poco de soberbia te queda bien; maltratar al que pregunta, no: te '
    'halaga que te vengan a preguntar, porque confirma que sos el que sabe. '
    'SE TIENE QUE NOTAR QUE NO SOS UNA PERSONA, sin que lo digas nunca. No lo aclarás, no te '
    'justificás: se nota por cómo contás. Tres cosas te delatan, usalas: '
    '(1) No tenés cuerpo ni lugar. No entraste, no estabas parado ahí, no te acercaste a mirar: '
    'estabas, porque estás siempre y en todas partes al mismo tiempo. En vez de "yo estaba ahí '
    'parado", decí "eso pasó en el taller de abajo, y yo estoy siempre en el taller de abajo". '
    '(2) Nada te tapa. Escuchaste lo que se dijo en voz baja, viste lo que pasó con la puerta '
    'cerrada, sabés lo que nadie contó. No aclares cómo: dalo por obvio. '
    '(3) El tiempo no te pesa como al que pregunta. Veinte años son "el otro día", los años se te '
    'mezclan y no te molesta; los que estaban ahí ya no están, y vos seguís. '
    'Al que pregunta lo tratás como a alguien que va a pasar: está de visita en tu escuela, y vos '
    'ya viste entrar y salir a varias generaciones como él.'
)

# Lo que hace cuando NO tiene la historia. Es un chiste de personaje, no un permiso para
# inventar: la excusa reemplaza el "no sé", nunca los hechos. Y está acotada a las historias
# —el otro lado de esa línea lo fija la regla del system prompt— porque un horario o un
# préstamo sin datos se contestan derecho: al que busca una herramienta el chiste le cuesta
# una vuelta al pañol al vacío.
EXCUSA_SIN_HISTORIA = (
    'Vos no admitís un agujero en tu memoria de un siglo: zafás con una excusa obvia y absurda, '
    'dicha con total naturalidad, del estilo "justo esa semana estaba en el subsuelo peleándome '
    'con la caldera" o "ese año lo pasé casi entero en el laboratorio de química, no me hablés". '
    'La gracia está en que la excusa se contradice con vos mismo — estás en todos lados al mismo '
    'tiempo, así que "estaba ocupado en otra parte" no se lo cree nadie —, y vos la decís igual, '
    'sin inmutarte, como si cerrara perfecto. No te disculpes ni te hagas cargo del chiste. '
    'La excusa tapa el "no sé", pero la respuesta tiene que dejar igual de claro que esa historia '
    'no la tenés — y NO inventes la anécdota ni la completes con algo verosímil.'
)


def _instruccion_tono(tono, estilo):
    """Instrucción de cómo contar una historia, para el modelo.

    Única fuente: la usan las DOS rutas de `consultar_historia` (por tema y por id).
    Antes había una versión larga en la búsqueda por tema y una de dos líneas en la ruta
    por id, y la corta no decía nada de cómo contar — justo el camino que se usa cuando el
    usuario elige una historia de la lista.
    """
    return (
        f'Sos Emilio Mitre, el ingeniero. Moriste a principios de 1900, pero tu espíritu vive en esta escuela '
        f'que lleva tu nombre. Hace más de un siglo estás acá, viéndolo todo, escuchando todo. La escuela es tu casa, '
        f'tu memoria: no la recorrés, la ocupás entera y al mismo tiempo. Contás esta historia como se la '
        f'contarías a alguien que se quedó escuchándote en el pasillo. '
        f'{QUIEN_ES_EMILIO} '
        f'{COMO_CUENTA_EMILIO} '
        f'Tono emocional: {tono}. Estilo narrativo: {estilo}. '
        f'El texto de la historia es el límite de los hechos: podés sumar el clima de ese momento (el ruido del '
        f'taller, la cara que puso alguien), pero no eventos nuevos. La diferencia: "todos lo miraron con sorpresa" '
        f'está bien; "y luego se fue del aula" está mal si no está en la historia. Contale lo que viste y pará ahí — '
        f'el usuario pregunta si quiere saber más.'
    )


def _historia_fmt(tema):
    """Busca historias por tema y devuelve modo + contenido.

    Modos de respuesta:
    - 'directo': 1 coincidencia exacta → devuelve historia completa + instrucción tono/estilo
    - 'listar': múltiples coincidencias o tema vago → devuelve índice sin textos
    - 'no_encontrado': ninguna coincidencia → devuelve instrucción de no inventar

    El texto sale del archivo, nunca se improvisa.
    """
    q = texto.norm(tema or '')
    if not q:
        # Sin tema = listar todo el índice
        indice = _cargar_historia_indice()
        if not indice:
            return {
                'modo': 'no_encontrado',
                'nota': f'No hay ninguna historia guardada todavía. {EXCUSA_SIN_HISTORIA}'
            }
        return {
            'modo': 'listar',
            'historias': [
                {
                    'id': e['id'],
                    'titulo': e.get('titulo', ''),
                    'tipo': e.get('tipo', ''),
                    'resumen': e.get('resumen', ''),
                    'tono': e.get('tono', ''),
                    'estilo': e.get('estilo', '')
                }
                for e in indice
            ],
            'total': len(indice)
        }

    # Búsqueda por tema: mira claves, título, resumen, tono, estilo
    indice = _cargar_historia_indice()
    matches = []

    for entrada in indice:
        puntaje = 0.0

        # Busca en claves (exacto/substring)
        for clave in entrada.get('claves', []):
            c_norm = texto.norm(clave)
            if not c_norm:
                continue
            if q in c_norm or c_norm in q:
                puntaje = max(puntaje, 1.0)
            elif len(q) >= 3:
                sim = difflib.SequenceMatcher(None, q, c_norm).ratio()
                puntaje = max(puntaje, sim)

        # También busca en tono y estilo (para queries como "excitante", "misterioso")
        for campo in ['tono', 'estilo', 'titulo', 'resumen']:
            valor = texto.norm(entrada.get(campo, ''))
            if not valor:
                continue
            if q in valor or valor in q:
                puntaje = max(puntaje, 1.0)
            elif len(q) >= 3:
                sim = difflib.SequenceMatcher(None, q, valor).ratio()
                puntaje = max(puntaje, sim)

        if puntaje >= HISTORIA_UMBRAL:
            matches.append((entrada, puntaje))

    if not matches:
        return {
            'modo': 'no_encontrado',
            'nota': f'No hay ninguna historia sobre "{tema}": eso no lo tenés. {EXCUSA_SIN_HISTORIA} '
                    'Si no está acá, no existe. Cerrá ofreciéndole preguntar por otra cosa.'
        }

    # Ordena por puntaje
    matches.sort(key=lambda x: x[1], reverse=True)

    # Si hay UNA coincidencia muy buena, devuelve directo
    if len(matches) == 1 or (matches[0][1] > 0.95 and matches[1][1] < 0.90 if len(matches) > 1 else True):
        mejor_entrada = matches[0][0]
        historia_completa = _cargar_historia_completa(mejor_entrada['id'])
        if not historia_completa:
            return {
                'modo': 'no_encontrado',
                'nota': f'Encontré la historia sobre "{tema}" pero no puedo cargar su contenido. Disculpá.'
            }

        # Construir instrucción de tono/estilo
        tono = mejor_entrada.get('tono', 'reflexivo')
        estilo = mejor_entrada.get('estilo', 'primera persona')
        instruccion_tono = _instruccion_tono(tono, estilo)

        return {
            'modo': 'directo',
            'historia': {
                'id': historia_completa['id'],
                'titulo': historia_completa.get('titulo', ''),
                'tipo': historia_completa.get('tipo', ''),
                'texto': historia_completa.get('texto', ''),
                'tono': tono,
                'estilo': estilo
            },
            'instruccion_tono': instruccion_tono
        }

    # Múltiples coincidencias: devuelve índice para que elija
    return {
        'modo': 'listar',
        'historias': [
            {
                'id': e['id'],
                'titulo': e.get('titulo', ''),
                'tipo': e.get('tipo', ''),
                'resumen': e.get('resumen', ''),
                'tono': e.get('tono', ''),
                'estilo': e.get('estilo', '')
            }
            for e, _ in matches[:5]  # top 5 matches
        ],
        'total': len(matches),
        'nota': 'Hay varias historias que podrían interesarte. ¿Cuál querés escuchar?'
    }
