"""Los nombres del calendario, enlazados a su horario, en lo que muestra el chat.

Cuando la respuesta nombra a un docente, a un preceptor o a un curso, ese nombre pasa a
ser un link markdown a su pantalla en la app de horarios (`/horarios/profesores/...`): cada
búsqueda de la app es una dirección propia, justamente para poder compartirla. El chat lo pinta como `<a>` (ver
`inlineMarkdown` en `static/gestion-agente.js`, que sólo acepta destinos internos).

Es un filtro de PRESENTACIÓN y no uno de salida como los de `filtros.py`: se aplica a lo
que sale por la API —el payload del turno y el historial repintado— y NUNCA a lo que se
guarda. Si los links quedaran en el historial, el modelo los tendría a la vista como
ejemplo en el turno siguiente y empezaría a escribirlos él, inventando destinos.

El texto se compara contra el padrón real, así que un nombre que no está en la planilla no
se enlaza: no hay forma de que el link apunte a una búsqueda vacía. Cada destino se enlaza
UNA vez por mensaje — la primera —, porque una tabla de veinte clases con el mismo docente
en cada fila queda ilegible si se subraya veinte veces.

`enlace_comparacion` es el otro lado de lo mismo para la tool `coincidencias`: en vez de un
nombre suelto, el link abre el modo comparación del calendario con TODAS las entidades que se
cruzaron, superpuestas. Como el resto de este módulo, se pega al salir y no se guarda.
"""
import os
import re
from urllib.parse import quote

import texto
from horarios import datos as database

from .padrones import _etiqueta_curso, _lista_preceptores, _padron_horarios

# Las pantallas de la app de horarios (frontend/horarios/src/router.js): cada modo de
# búsqueda tiene su segmento, y el valor va como último tramo de la dirección.
BASE = '/horarios/'
SEGMENTO = {'curso': 'cursos', 'profesor': 'profesores', 'aula': 'aulas',
            'horario_preceptor': 'preceptores'}

# Un apellido suelto de cuatro letras ("LEON", "CRUZ") aparece en el medio de una frase por
# casualidad; uno de cinco o más, casi nunca. Sólo aplica a los nombres de una palabra: con
# dos o más el falso positivo deja de ser un riesgo.
LARGO_MINIMO_SUELTO = 5

_RE_CURSO = re.compile(r'([1-7])\s*[°º]\s*([A-Za-z0-9]{1,2})')

_cache = {'firma': None, 'nombres': None, 'cursos': None, 'regex': None}


def _cursos_validos():
    """{('1', 'A'): '1° A'} — las divisiones que existen, con la etiqueta que espera el SPA."""
    con = database.conectar()
    cur = con.cursor()
    cur.execute("SELECT DISTINCT curso, division FROM clases "
                "WHERE curso != '' AND division != ''")
    cursos = {(str(c).strip(), str(d).strip().upper()): _etiqueta_curso(c, d)
              for c, d in cur.fetchall()}
    con.close()
    return cursos


def _enlazable(nombre):
    tokens = nombre.split()
    return len(tokens) > 1 or (len(tokens) == 1 and len(tokens[0]) >= LARGO_MINIMO_SUELTO)


def _patron_nombre(nombre):
    """El nombre como patrón: literal, salvo los espacios, que aceptan cualquier blanco.

    `re.escape` escapa el espacio en algunas versiones de Python y en otras no, así que se
    contemplan las dos formas — con una sola, media alternancia quedaba rota en silencio.
    """
    return re.escape(nombre).replace('\\ ', r'\s+').replace(' ', r'\s+')


def _construir(firma):
    """Arma el índice de nombre normalizado → (modo, valor) y el regex que los busca.

    Los preceptores van primero y los docentes los pisan: quien esté en las dos tablas se
    enlaza a su horario de clases, que es el que tiene calendario propio.
    """
    nombres = {}
    for lista, modo in ((_lista_preceptores(), 'horario_preceptor'),
                        (_padron_horarios(), 'profesor')):
        for n in lista:
            n = (n or '').strip()
            if _enlazable(n):
                nombres[texto.norm(n)] = (modo, n)

    # Orden por largo: sin esto "MACIEL" (si existiera suelto) le ganaría a "MACIEL MARTIN",
    # porque la alternancia de un regex se queda con la primera que matchea, no con la mejor.
    alternativas = sorted(nombres, key=len, reverse=True)
    partes = [r'(?P<enlace>\[[^\]\n]*\]\([^)\n]*\))',   # ya es un link: no se toca
              r'(?P<codigo>`[^`\n]*`)',                  # ni lo que va en code
              r'(?<![A-Za-z0-9])(?P<curso>[1-7]\s*[°º]\s*[A-Za-z0-9]{1,2})(?![A-Za-z0-9])']
    if alternativas:
        # El espacio pasa a `\s+` porque `texto.norm` colapsa los espacios del padrón y el
        # texto del modelo puede traer dos, o un salto de línea en el medio de una celda.
        cuerpo = '|'.join(_patron_nombre(a) for a in alternativas)
        partes.append(r'(?<![A-Za-z0-9])(?P<nombre>' + cuerpo + r')(?![A-Za-z0-9])')

    _cache.update(firma=firma, nombres=nombres, cursos=_cursos_validos(),
                  regex=re.compile('|'.join(partes), re.IGNORECASE))


def _indice():
    """El índice al día. Se rearma cuando `escuela.db` cambió (la regenera el botón de Sheets)."""
    try:
        firma = os.path.getmtime(database.DB_PATH)
    except OSError:
        firma = None
    if _cache['regex'] is None or _cache['firma'] != firma:
        _construir(firma)
    return _cache


def _destino(m, idx):
    """(modo, valor) al que apunta esta coincidencia, o None si no es nadie del padrón."""
    if m.group('enlace') or m.group('codigo'):
        return None
    curso = m.group('curso')
    if curso:
        partes = _RE_CURSO.match(curso)
        etiqueta = idx['cursos'].get((partes.group(1), partes.group(2).upper()))
        return ('curso', etiqueta) if etiqueta else None
    nombre = m.groupdict().get('nombre')
    return idx['nombres'].get(texto.norm(nombre)) if nombre else None


def enlace_comparacion(comparacion):
    """El link que abre el modo comparación con todo lo que se cruzó, o '' si no aplica.

    Lo llena `_coincidencias_fmt` en `contexto_turno` (ver allá). Se devuelve como un párrafo
    aparte para pegar al final de la respuesta: es una acción, no un nombre en el medio de una
    frase, y el modelo no escribe ninguna — la pone el server o no está.
    """
    items = (comparacion or {}).get('items') or []
    if len(items) < 2:
        return ''
    # `safe=''` también escapa la coma y los dos puntos, que acá son separadores de la lista
    # (el formato que lee `leerComparacion` de la app). Se abre en la pestaña del primero.
    partes = ','.join('{}:{}'.format(modo, quote(valor, safe='')) for modo, valor in items)
    afuera = (comparacion or {}).get('afuera') or []
    aclaracion = ''
    if afuera:
        # El modo comparación dibuja bloques de `clases`: quien no tiene ninguna no entra, y
        # callarlo dejaría al usuario buscando en el calendario una columna que no está.
        quienes = ', '.join(afuera)
        aclaracion = (' (sin {}: el calendario comparado sólo superpone horarios de clase)'
                      .format(quienes))
    return '\n\n[Ver los horarios superpuestos en el calendario]({}{}?comparar={}){}'.format(
        BASE, SEGMENTO[items[0][0]], quote(partes, safe=':,'), aclaracion)


def enlazar(respuesta):
    """El mismo texto con los nombres del calendario convertidos en links markdown."""
    if not respuesta:
        return respuesta
    try:
        idx = _indice()
    except Exception:
        # Es decoración: si los horarios no se pueden leer, el mensaje sale igual.
        return respuesta

    # Se busca sobre una copia SIN ACENTOS para que "Martín" matchee al "MARTIN" del padrón.
    # Char por char en vez de sobre el texto entero para no perder el alineamiento de los
    # índices: los tramos se cortan del original, no de esta copia.
    plano = ''.join(texto.sin_acentos(c) or c for c in respuesta)

    usados = set()
    piezas, fin = [], 0
    for m in idx['regex'].finditer(plano):
        destino = _destino(m, idx)
        if not destino or destino in usados:
            continue
        usados.add(destino)
        modo, valor = destino
        piezas.append(respuesta[fin:m.start()])
        piezas.append('[{}]({}{}/{})'.format(respuesta[m.start():m.end()],
                                             BASE, SEGMENTO[modo], quote(valor, safe='')))
        fin = m.end()
    piezas.append(respuesta[fin:])
    return ''.join(piezas)
