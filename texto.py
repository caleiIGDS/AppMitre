"""Normalización de texto y búsqueda tolerante — capa 0, sin dominio.

No conoce ninguna tabla, ninguna entidad ni Flask: sólo stdlib. Lo usan `gestion`,
`historia` y el asistente. (El sistema de horarios es un paquete aparte y lleva su propia
copia de `sin_acentos` en `horarios/datos.py`.)

El nombre del archivo describe lo que hay adentro a propósito, en vez de `util.py`: un
archivo llamado "util" no tiene forma de decirte que algo no pertenece ahí, y termina
siendo el cajón donde vuelve a acumularse todo. Si hace falta compartir algo que no es
texto, va en su propio archivo (ver `respaldos.py`).
"""

import difflib
import unicodedata


def sin_acentos(texto):
    """Saca diacríticos, conserva mayúsculas y espacios tal como vienen.

    Está separada de `norm()` porque algunos pipelines la necesitan así: arman nombres en
    MAYÚSCULAS y dependen de que acá no se baje a minúsculas.
    """
    if not texto:
        return ""
    return "".join(c for c in unicodedata.normalize('NFD', texto)
                   if unicodedata.category(c) != 'Mn')


def norm(texto):
    """Minúsculas, sin acentos, espacios colapsados — para comparar nombres."""
    return ' '.join(sin_acentos(texto).lower().split())


# Búsqueda "que perdona": en vez del LIKE literal, normaliza acentos/mayúsculas y
# tolera typos por similitud (difflib, sin dependencias). El substring normalizado
# siempre gana; la similitud difusa solo entra para queries de 3+ caracteres (con
# menos daría demasiado ruido). Subir = más estricto.
#
# 0.68 salió de medir contra el inventario real (91 recursos), no a ojo: con 0.6
# buscar "taladro" (que no existe) devolvía 4 recursos, "guantes" 7 y "multimetro"
# traía 8 con "Pintura marrón (tarro)" adentro. Para nombres cortos, 0.6 deja pasar
# casi cualquier cosa que comparta vocales. A 0.68 esos casos caen a 0/1/1 y el
# recall no se toca: todas las queries con typo probadas ("multimetr0", "alikate",
# "agujeradora", "anemometroo", "caladra") siguen encontrando su recurso en el
# puesto #1. Arriba de 0.68 se gana poco y se empieza a arriesgar recall.
#
# El mismo 0.68 se revalidó sobre NOMBRES DE PERSONAS, que es texto bastante distinto
# del inventario, cuando se agregó el cruce entre los dos padrones
# (`agente._coincide_fuerte`): "nati" sigue trayendo Natalia (0.73), y con 0.6 entraban
# PETRATE MATIAS ("matias", 0.60) y PRIETO VALERIA. O sea que el número no está
# calibrado para un solo tipo de texto por casualidad — se midió en los dos.
UMBRAL_SIMILITUD = 0.68

# Guard del match palabra por palabra (ver abajo): una palabra candidata más CORTA que la
# query completa se descarta. Sin esto, "pelacable" (9) contra la palabra suelta "cable" (5,
# de un alias como "cable extension USB") da ratio 0.71 — arriba del umbral, puro ruido,
# porque una palabra corta CONTENIDA en una query larga infla el ratio (2*M/(len_a+len_b)
# con len_b chico) sin que tengan relación real. Medido sobre el inventario real: "pelacable"
# traía 7 resultados (3 de ellos sin ninguna relación) con el ítem correcto en el puesto #4;
# con el guard, 1 resultado, el correcto. No afecta ningún caso ya validado arriba —
# "nati"→Natalia sigue andando porque ahí la query ("nati", corta) es la que compara contra
# la palabra larga ("natalia"), no al revés; y los 7 casos de typo (`multimetr0`, `alikate`,
# etc.) dan exactamente los mismos resultados con o sin el guard.


def puntaje_busqueda(q_norm, *textos, umbral=UMBRAL_SIMILITUD):
    """Qué tan bien `q_norm` (ya normalizado) matchea los textos dados.

    Devuelve un puntaje mayor = mejor, o None si no llega al umbral. Los que
    contienen la query como substring puntúan por encima de los difusos.

    `umbral` es keyword-only y hoy no lo pasa nadie. Existe para que un área con texto
    muy distinto pueda ajustarlo **sin forkear la función**, que es exactamente la forma
    en que esto se volvería a duplicar.
    """
    difuso = len(q_norm) >= 3  # perdonar typos solo tiene sentido con 3+ caracteres
    substring = False
    mejor = 0.0
    for texto in textos:
        if not texto:
            continue
        t_norm = norm(texto)
        if q_norm in t_norm:
            substring = True
        if difuso:
            mejor = max(mejor, difflib.SequenceMatcher(None, q_norm, t_norm).ratio())
            for palabra in t_norm.split():
                if len(palabra) < len(q_norm):
                    continue  # ver el comentario de UMBRAL_SIMILITUD: palabra corta, ruido
                mejor = max(mejor, difflib.SequenceMatcher(None, q_norm, palabra).ratio())
    if substring:
        return 1.0 + mejor  # substring exacto siempre primero; desempata por similitud
    if difuso and mejor >= umbral:
        return mejor
    return None
