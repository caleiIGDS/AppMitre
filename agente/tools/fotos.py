"""Las dos cosas que se pueden hacer con una foto: leerla o adjuntarla.

Leer es una tool y no un paso automático: la primera versión leía toda foto al entrar al
chat, y pagaba una llamada de visión también cuando lo único que querían era adjuntar —
que es el caso más común y el que menos la necesita.

Las dos sacan las imágenes de `contexto_turno['fotos_turno']`, nunca de un parámetro: el
modelo no ve la foto, así que pedirle el base64 sería pedirle que lo invente. Lo único que
maneja es el NÚMERO de cada foto, que es lo que le permite decir de cuál salió cada ficha.
"""
import crud

from ..dominio import SLUGS_ENTIDAD, _modulo
from ..proveedores import _get_vision_config
from ..vision import MODO_DEFAULT, _leer_imagen


# ---------------------------------------------------------------------------
# Fotos: leer (opcional) y adjuntar
# ---------------------------------------------------------------------------
# La foto NO se lee sola al llegar. Leerla es una tool que el modelo llama solo cuando
# hace falta sacarle datos, porque el caso más común —"guardá esta foto en el taladro"—
# no necesita leer nada: necesita saber a qué recurso va, y eso lo dice el usuario.
# Leer por las dudas era pagar una llamada de visión en cada foto para tirarla a la basura.
#
# En los dos casos las imágenes salen de `contexto_turno['fotos_turno']` y no de un
# parámetro: el modelo nunca ve la foto (ve, como mucho, su lectura en texto), así que
# pedirle el base64 sería pedirle que lo invente.

SIN_FOTOS = ('En este turno el usuario no adjuntó ninguna foto. Si querés que te mande una, '
             'pedísela; no llames a esta tool de nuevo hasta que la mande.')


def _fotos_del_turno(contexto_turno, foto=None):
    """Las fotos de este turno, o sólo la número `foto` si la pidieron.

    Devuelve `(lista, error)`. Un número que no existe se cuenta con los que sí, en vez de
    fallar en seco: el modelo elige el número y una confusión no tiene por qué costar el turno.
    """
    fotos = (contexto_turno or {}).get('fotos_turno') or []
    if not fotos:
        return [], SIN_FOTOS
    if foto is None:
        return fotos, None
    try:
        n = int(foto)
    except (TypeError, ValueError):
        return fotos, None
    elegidas = [f for f in fotos if f['n'] == n]
    if not elegidas:
        disponibles = ', '.join(str(f['n']) for f in fotos)
        return [], (f'En este turno no hay ninguna foto número {n}. Las que mandó el usuario '
                    f'son la {disponibles}.')
    return elegidas, None


def _leer_foto_fmt(contexto_turno=None, modo=MODO_DEFAULT, foto=None):
    """Lee las fotos de ESTE turno con el modelo de visión. Solo lee: no escribe nada.

    Sin `foto` lee TODAS las del turno de una sola vez, y no es un detalle de comodidad: el
    loop de tool-calling tiene un tope de vueltas, así que una llamada por foto se comía el
    turno entero antes de llegar a armar las fichas.

    `modo` elige qué mirar, no si mirar: 'etiqueta' transcribe la chapa de un producto,
    'listado' transcribe una página/tabla con varios ítems distintos, 'analisis' describe el
    objeto. Los tres cuestan una llamada de visión igual, así que la regla de llamarla solo
    cuando hacen falta los datos no cambia — tener más modos no es una excusa para leer
    por las dudas.
    """
    fotos, error = _fotos_del_turno(contexto_turno, foto)
    if error:
        return {'error': error}

    # "No hay lector configurado" y "el lector falló" son cosas distintas para el usuario —
    # una se arregla cargando una API key y la otra se arregla esperando — pero `_leer_imagen`
    # devuelve None en los dos casos. El primero se detecta acá para que el aviso sea el que
    # corresponde. Ojo: adjuntar NO pasa por acá, así que sin lector sigue funcionando.
    if not _get_vision_config():
        return {'error': 'No hay ningún lector de imágenes configurado en el servidor, así que '
                         'no podés leer fotos ni saber qué muestran. Decíselo al usuario en una '
                         'línea y ofrecele las dos salidas: que te dicte por texto lo que dice la '
                         'etiqueta, o que te diga a qué ficha guardar la foto (adjuntar_foto sí '
                         'funciona, no necesita leerla). NO inventes lo que decía la foto.'}

    texto_usuario = (contexto_turno or {}).get('texto_usuario', '')
    lecturas = []
    for f in fotos:
        lectura = _leer_imagen(f['b64'], f['tipo'], texto_usuario, modo)
        if lectura:
            lecturas.append({'foto': f['n'], 'lectura': lectura})

    if not lecturas:
        return {'error': 'No se pudo leer la foto (el servicio que las lee no respondió). '
                         'Decíselo al usuario y ofrecele que te dicte los datos por texto o '
                         'que la mande de nuevo en un rato. NO inventes lo que decía.'}

    # El techo es el mismo en los tres modos —lo que no está en la foto no se sabe— pero se
    # dice distinto porque el riesgo es distinto: en `etiqueta`/`listado` es completar de
    # memoria, en `analisis` es opinar de lo que una foto no muestra (si anda, si sirve).
    if modo == 'analisis':
        instruccion = ('Esto es TODO lo que se ve en cada foto, y es una descripción, no una '
                       'ficha técnica: no salieron de acá la marca, el modelo ni las '
                       'especificaciones. No completes con lo que sepas de ese tipo de '
                       'máquina, y no afirmes que funciona ni en qué estado está más allá de '
                       'lo que dice la descripción. Si hace falta cargarlo al inventario, '
                       'pedile al usuario los datos que faltan o una foto de la etiqueta.')
    elif modo == 'listado':
        instruccion = ('Esto es TODO lo que se leyó en cada foto: un renglón por ítem, con '
                       'nombre y cantidad tal como estaban escritos. Lo que no está acá no lo '
                       'sabés: no inventes ítems ni cantidades. Si esta lista es el contenido '
                       'de un kit, proponé UN solo recurso con `sub_recursos` cargado con todos '
                       'estos renglones — no una ficha por ítem.')
    else:
        instruccion = ('Esto es TODO lo que se lee en cada foto. Lo que no está acá no lo sabés: '
                       'no lo completes con lo que sepas de esa marca o modelo. Si una lectura '
                       'dice que no se lee o pide otra foto, transmitíselo al usuario y no '
                       'armes la ficha de ESA.')
    if len(lecturas) > 1:
        instruccion += (' Cada lectura viene con el NÚMERO de su foto: son cosas distintas, una '
                        'ficha por cada una. Cuando llames a crear_entidad pasale ese mismo '
                        'número en `foto`, para que la imagen termine en la ficha correcta.')

    if len(lecturas) < len(fotos):
        instruccion += (f' Ojo: de las {len(fotos)} fotos sólo se pudieron leer {len(lecturas)}. '
                        'De las que faltan no sabés nada — decíselo al usuario, no las inventes.')

    # Las lecturas se dejan en el turno para que `rutas` las persista pegadas al mensaje. Los
    # resultados de las tools NO quedan en el historial, así que sin esto lo único que
    # sobrevive de las fotos es lo que el modelo haya repetido en su prosa: al turno
    # siguiente ("dale, creá") se quedaba sin marca, modelo ni specs, y volvía a llamar a
    # leer_foto sobre fotos que ya no existen.
    if contexto_turno is not None:
        contexto_turno.setdefault('lectura_foto', []).extend(lecturas)

    return {'lecturas': lecturas, 'modo': modo, 'instruccion': instruccion}


def _adjuntar_foto_entidad(slug, id, contexto_turno=None, foto=None):
    """Pega las fotos de ESTE turno a la galería de un registro que ya existe.

    Sin `foto` van TODAS las del turno: mandar cuatro fotos de la misma máquina y pedir que
    queden en su ficha es el caso normal. Con `foto` va sólo esa, para cuando cada una va a
    un registro distinto.

    Corre directo, sin ficha de confirmación: es aditivo (no pisa ni borra nada) y el listón
    lo marca `editar_entidad`, que sobrescribe campos y tampoco la pide. Queda auditada en
    `agente_log` como cualquier escritura.
    """
    fotos, error = _fotos_del_turno(contexto_turno, foto)
    if error:
        return {'ok': False,
                'error': error if foto is not None else
                         'En este turno el usuario no adjuntó ninguna foto. Esta tool guarda '
                         'las fotos que acaba de mandar; si quiere subir otra, que la adjunte y '
                         'te lo vuelva a pedir.'}

    if slug not in SLUGS_ENTIDAD:
        return {'ok': False, 'error': f'Slug inválido: {slug}. Válidos: {", ".join(SLUGS_ENTIDAD)}'}

    guardadas = 0
    try:
        for f in fotos:
            if not crud.agregar_foto(_modulo(slug), slug, id, f['b64'], f['tipo']):
                return {'ok': False,
                        'error': f'No existe {slug} id={id}. Buscalo con buscar_entidad.'}
            guardadas += 1
    except Exception as e:
        return {'ok': False, 'error': f'No se pudo guardar la foto: {e}'}

    return {'ok': True, 'id': id, 'fotos': guardadas,
            'mensaje': f'{guardadas} foto(s) agregada(s) a {slug} id={id}'}
