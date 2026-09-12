"""Lo que se limpia de la respuesta antes de mostrarla y ANTES de persistirla.

  _ocultar_ids  los id son cañería: el modelo los necesita, el usuario no.

Va como filtro de salida y no solo como regla del prompt porque es exactamente el tipo de
regla que este agente cumple a veces: acá el peor caso de fallar es ruido en pantalla, así
que conviene que sea determinístico. Se aplica antes de guardar para que el historial
repintado tampoco lo traiga.

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


AVISO_NO_EJECUTADO = (
    "⚠️ **OJO: esto NO se ejecutó.** El asistente informó un cambio que nunca llegó a la "
    "base de datos (no corrió ninguna operación de escritura en este turno). Volvé a pedirlo "
    "explícitamente y verificá en la pantalla correspondiente antes de darlo por hecho.\n\n"
    "_Respuesta original del asistente:_\n\n"
)
