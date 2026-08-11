"""Las dos cosas que se pueden hacer con una foto: leerla o adjuntarla.

Leer es una tool y no un paso automático: la primera versión leía toda foto al entrar al
chat, y pagaba una llamada de visión también cuando lo único que querían era adjuntar —
que es el caso más común y el que menos la necesita.

Las dos sacan la imagen de `contexto_turno['foto_turno']`, nunca de un parámetro: el
modelo no ve la foto, así que pedirle el base64 sería pedirle que lo invente.
"""
import crud

from ..dominio import SLUGS_ENTIDAD, _modulo
from ..proveedores import _get_vision_config
from ..vision import _leer_imagen


# ---------------------------------------------------------------------------
# Fotos: leer (opcional) y adjuntar
# ---------------------------------------------------------------------------
# La foto NO se lee sola al llegar. Leerla es una tool que el modelo llama solo cuando
# hace falta sacarle datos, porque el caso más común —"guardá esta foto en el taladro"—
# no necesita leer nada: necesita saber a qué recurso va, y eso lo dice el usuario.
# Leer por las dudas era pagar una llamada de visión en cada foto para tirarla a la basura.
#
# En los dos casos la imagen sale de `contexto_turno['foto_turno']` y no de un parámetro:
# el modelo nunca ve la foto (ve, como mucho, su lectura en texto), así que pedirle el
# base64 sería pedirle que lo invente.

def _leer_foto_fmt(contexto_turno=None):
    """Lee la foto de ESTE turno con el modelo de visión. Solo lee: no escribe nada."""
    foto = (contexto_turno or {}).get('foto_turno')
    if not foto:
        return {'error': 'En este turno el usuario no adjuntó ninguna foto. Si querés que te '
                         'mande una, pedísela; no llames a esta tool de nuevo hasta que la mande.'}

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

    b64, tipo = foto
    lectura = _leer_imagen(b64, tipo, (contexto_turno or {}).get('texto_usuario', ''))
    if not lectura:
        return {'error': 'No se pudo leer la foto (el servicio que las lee no respondió). '
                         'Decíselo al usuario y ofrecele que te dicte los datos por texto o '
                         'que la mande de nuevo en un rato. NO inventes lo que decía.'}

    return {
        'lectura': lectura,
        'instruccion': ('Esto es TODO lo que se lee en la foto. Lo que no está acá no lo sabés: '
                        'no lo completes con lo que sepas de esa marca o modelo. Si la lectura '
                        'dice que no se lee o pide otra foto, transmitíselo al usuario y no '
                        'armes ninguna ficha.')
    }


def _adjuntar_foto_entidad(slug, id, contexto_turno=None):
    """Pega la foto de ESTE turno a la galería de un registro que ya existe.

    Corre directo, sin ficha de confirmación: es aditivo (no pisa ni borra nada) y el listón
    lo marca `editar_entidad`, que sobrescribe campos y tampoco la pide. Queda auditada en
    `agente_log` como cualquier escritura.
    """
    foto = (contexto_turno or {}).get('foto_turno')
    if not foto:
        return {'ok': False,
                'error': 'En este turno el usuario no adjuntó ninguna foto. Esta tool guarda '
                         'la foto que acaba de mandar; si quiere subir otra, que la adjunte y '
                         'te lo vuelva a pedir.'}

    if slug not in SLUGS_ENTIDAD:
        return {'ok': False, 'error': f'Slug inválido: {slug}. Válidos: {", ".join(SLUGS_ENTIDAD)}'}

    b64, tipo = foto
    try:
        if not crud.agregar_foto(_modulo(slug), slug, id, b64, tipo):
            return {'ok': False,
                    'error': f'No existe {slug} id={id}. Buscalo con buscar_entidad.'}
    except Exception as e:
        return {'ok': False, 'error': f'No se pudo guardar la foto: {e}'}

    return {'ok': True, 'id': id, 'mensaje': f'Foto agregada a {slug} id={id}'}
