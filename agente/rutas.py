"""Los endpoints Flask de /agente.

El gate de acceso es el mismo motor que /gestion e /historia (misma GESTION_CLAVE, misma
marca `gestion_ok`), pero acá el blueprint mezcla páginas HTML con endpoints JSON: sólo
las páginas redirigen al login y el resto contesta 401, que es lo que el fetch del chat
sabe leer.
"""
import re

from flask import jsonify, render_template, request

import crud
import texto
from config import DIAS, ESCUELA_LOGO, ESCUELA_NOMBRE, ESCUELA_VERSION, ahora

from . import bp
from .db import (FICHAS_MAX, HISTORIAL_AL_MODELO, _conv_borrar, _conv_cargar,
                 _conv_guardar, _foto_pendiente_guardar, _foto_pendiente_tomar,
                 _sin_imagenes, conectar)
from .dominio import _modulo
from .filtros import (AVISO_NO_EJECUTADO, _es_pregunta_relativa, _escritura_no_ejecutada,
                      _extraer_entidad_mencionada, _ocultar_ids, _quitar_acotaciones)
from .llm import chat_with_tools
from .padrones import _personas_nombradas_en
from .proveedores import _get_config, _get_vision_config
from .tools import ejecutar_tool
from .tools.entidades import _vincular_entidad
from .tools.fichas import _nombre_de

# Endpoints que devuelven HTML. Sin sesión conviene mandarlos al login propio de /agente
# (con `next` para volver acá), no un 401 pelado: entrar por link directo a /agente
# desde el celular es el caso normal, y ahí un 401 es un callejón.
# Los endpoints JSON sí siguen dando 401, que es lo que el fetch del chat sabe leer.
_ENDPOINTS_PAGINA = ('agente.chat_page', 'agente.agente_log')

# Gate de sesión: el mismo motor que /gestion y /historia (misma GESTION_CLAVE, misma
# marca de sesión `gestion_ok`), pero acá el blueprint mezcla páginas HTML con endpoints
# JSON, así que sólo las páginas redirigen al login y el resto contesta 401 — que es lo
# que el fetch del chat sabe leer.
crud.registrar_acceso(bp, endpoints_pagina=_ENDPOINTS_PAGINA,
                      endpoint_default='chat_page')


@bp.context_processor
def _contexto_base():
    """`agente/base.html` espera escuela_nombre/logo/version. No usa el context processor
    de `crud.registrar_rutas` porque /agente no es un área CRUD: no tiene ENTIDADES
    propias ni nav de entidades.
    """
    return {
        'escuela_nombre': ESCUELA_NOMBRE,
        'escuela_logo': ESCUELA_LOGO,
        'escuela_version': ESCUELA_VERSION,
    }

# Los avisos de foto ya no se resuelven acá con un texto fijo. Como leer es una tool, tanto
# "no hay lector configurado" como "el lector no respondió" vuelven como resultado de
# `leer_foto` y los cuenta el modelo con sus palabras (ver `_leer_foto_fmt`). La ventaja no
# es solo de tono: el corte fijo se disparaba ANTES de llamar al modelo, así que también
# bloqueaba adjuntar, que no necesita lector.



# El sello de hora que se le pega a CADA mensaje del usuario. El system prompt ya trae la
# fecha y la hora del turno, pero es un bloque largo y lejano: cuando la conversación
# crece, el modelo contesta "ahora" con la hora del primer mensaje o directamente inventa
# una. Pegada al mensaje, la hora es lo último que leyó. Además queda en el historial, así
# que en un turno de seguimiento se ve cuánto pasó entre un mensaje y otro.
# `_texto_visible` lo saca antes de repintar el chat: el usuario no lo escribió.
_SELLO_HORA = re.compile(r'\s*\[Hora de este mensaje:[^\]]*\]')


def _sello_hora():
    hoy = ahora()
    dia = DIAS[hoy.weekday()] if hoy.weekday() < len(DIAS) else hoy.strftime('%A')
    return f"[Hora de este mensaje: {dia} {hoy:%d/%m/%Y %H:%M}]"


# ============================================================================
# Endpoints Flask
# ============================================================================

@bp.route('/', methods=['GET'])
def chat_page():
    """Pestaña dedicada al chat, a pantalla completa.

    Es el mismo asistente que el widget flotante y comparte el markup
    (`_agente_chat_core.html`) y el JS — lo único que cambia es el contenedor.
    Pensada para el celular, que es donde más se usa: el widget de 380px flotando
    sobre una página que igual scrollea es incómodo en una pantalla chica.
    """
    return render_template('agente/agente_chat.html', activo='agente')


@bp.route('/chat', methods=['POST'])
def chat():
    """Endpoint para el widget de chat. JSON con 'mensaje' y opcionalmente 'imagen' (base64).
    Mantiene historial + última entidad consultada para mejor contexto."""
    data = request.get_json() or {}
    mensaje_usuario = data.get('mensaje', '').strip()

    # Una foto sola es un mensaje válido: sacan la etiqueta y la mandan sin escribir nada.
    if not mensaje_usuario and data.get('imagen'):
        mensaje_usuario = 'Te mando esta foto.'

    if not mensaje_usuario:
        return jsonify({'error': 'Mensaje vacío'}), 400

    # Conversación: sale de gestion.db, no de la cookie (ver _conv_cargar).
    conv = _conv_cargar()
    mensajes = conv['historial'][-HISTORIAL_AL_MODELO:]

    # Si el usuario hace una pregunta relativa sin especificar quién, inyectar referencia anterior
    entidad_actual = conv['entidad_actual']  # Último profesor/recurso consultado
    msg_procesado = mensaje_usuario

    if entidad_actual and _es_pregunta_relativa(mensaje_usuario):
        # Agregar contexto: "¿En qué lugar?" → "¿En qué lugar tiene clases [entidad]?"
        msg_procesado = f"{mensaje_usuario} (refiriéndote a: {entidad_actual})"

    # La hora va con el mensaje, no sólo en el system prompt (ver _sello_hora).
    msg_procesado = f"{msg_procesado}\n{_sello_hora()}"

    # Construir el contenido del mensaje del usuario (con imagen si viene)
    contenido = [{'type': 'text', 'text': msg_procesado}]

    imagen_base64 = data.get('imagen')
    media_type = 'image/jpeg'
    if imagen_base64:
        # Esperar formato: data:image/jpeg;base64,xxxxx o solo base64
        if imagen_base64.startswith('data:'):
            imagen_base64 = imagen_base64.split(',')[1]
        if imagen_base64.startswith('iVBO'):     # PNG magic ('/9j/' es JPEG, el default)
            media_type = 'image/png'

    # Qué se hace con la foto:
    #  - Si el proveedor del chat ve imágenes (AGENTE_PROVIDER=anthropic o AGENTE_VISION=1) y
    #    NO hay lector aparte, se le manda la imagen al agente directamente: es el único caso
    #    donde el que razona puede mirarla.
    #  - Si no, la foto no viaja: se le avisa al modelo que la tiene disponible y él decide
    #    qué hacer con ella — `leer_foto` si necesita los datos de la etiqueta, `adjuntar_foto`
    #    si solo hay que guardarla en una ficha, preguntar si no está claro. La foto sale de
    #    `contexto_turno['foto_turno']` (ver más abajo), no de un parámetro.
    #
    # Antes, no tener lector cortaba el turno acá con un aviso fijo y el modelo no llegaba a
    # correr. El razonamiento era "sin visión contestaría inventando lo que vio", pero se
    # comía el caso más común: ADJUNTAR una foto no necesita verla, y con el corte
    # `adjuntar_foto` era inalcanzable. Ahora el turno corre siempre y la distinción la hace
    # el modelo; si pide leer sin lector, se lo dice el error de `leer_foto`.
    if imagen_base64 and _get_config()['vision'] and not _get_vision_config():
        contenido.append({
            'type': 'image',
            'source': {
                'type': 'base64',
                'media_type': media_type,
                'data': imagen_base64
            }
        })

    elif imagen_base64:
        contenido[0]['text'] = (
            f"{msg_procesado}\n\n[El usuario adjuntó una foto en este turno. Todavía no la vio "
            "nadie: si necesitás lo que dice, llamá a leer_foto; si solo hay que guardarla en "
            "una ficha, llamá a adjuntar_foto. Si no sabés para qué te la mandaron o a qué "
            "registro va, preguntale.]")

    # Agregar mensaje del usuario al historial
    mensajes.append({'role': 'user', 'content': contenido})

    # Obtener respuesta del agente.
    # `fichas_previas` son las fichas de alta que el usuario YA vio en turnos anteriores;
    # sin esto no habría forma de confirmar un alta, porque los resultados de las tools no
    # quedan en el historial y en el turno siguiente el modelo no tiene la ficha a la vista.
    trazas = []
    contexto_turno = {'fichas_previas': dict(conv['fichas'])}
    if imagen_base64:
        # `leer_foto` y `adjuntar_foto` la sacan de acá: el modelo nunca ve la imagen, así
        # que no puede pasarla como parámetro.
        contexto_turno['foto_turno'] = (imagen_base64, media_type)
        contexto_turno['texto_usuario'] = mensaje_usuario
    respuesta = chat_with_tools(mensajes, trazas=trazas, contexto_turno=contexto_turno)
    # Se filtra ANTES de guardar, así el historial repintado tampoco muestra ids — y, en el
    # caso de las acotaciones, el modelo no las tiene como ejemplo a imitar en el turno que viene.
    respuesta = _ocultar_ids(respuesta)
    respuesta = _quitar_acotaciones(respuesta)

    # Lo que quedó pendiente de confirmar + lo que se mostró recién.
    fichas = dict(contexto_turno.get('fichas_previas', {}))
    fichas.update(contexto_turno.get('fichas_mostradas', {}))
    fichas = dict(list(fichas.items())[-FICHAS_MAX:])

    # Si de esta foto salió una ficha, la foto queda esperando: si el usuario confirma el
    # alta, termina en la galería del recurso nuevo (ver /confirmar). Se ata al token de la
    # ficha y no al turno porque la confirmación puede llegar mucho después, incluso desde
    # otra página.
    if imagen_base64:
        for token in contexto_turno.get('fichas_mostradas', {}):
            _foto_pendiente_guardar(token, imagen_base64, media_type)

    # Red de seguridad: si anunció un cambio que no ejecutó, avisarlo (ver comentario
    # en _escritura_no_ejecutada — la regla equivalente en el system prompt no alcanza).
    escritura_fantasma = _escritura_no_ejecutada(respuesta, trazas)
    if escritura_fantasma:
        respuesta = AVISO_NO_EJECUTADO + respuesta

    # Guardar respuesta en el historial (convertir respuesta a formato de mensaje)
    mensajes.append({'role': 'assistant', 'content': [{'type': 'text', 'text': respuesta}]})

    # Actualizar entidad actual si la respuesta menciona un profesor/recurso
    entidad = _extraer_entidad_mencionada(respuesta) or conv['entidad_actual']

    # Se persiste el historial COMPLETO más los dos mensajes de este turno (`mensajes` es
    # solo el recorte que vio el modelo). Las imágenes no se guardan: una foto en base64
    # pesa megas y no se reusa en turnos siguientes — queda una nota en su lugar.
    historial = conv['historial'] + _sin_imagenes(mensajes[-2:])
    _conv_guardar(historial, entidad, fichas)

    # Si quedaron fichas esperando el OK, el front pinta un botón por cada una debajo del
    # mensaje, en vez de que el usuario tenga que escribir "sí" (ver /confirmar).
    return jsonify({'respuesta': respuesta, 'tools': trazas,
                    'escritura_fantasma': escritura_fantasma,
                    'confirmaciones': _confirmaciones(fichas)})


def _texto_visible(msg):
    """Texto plano de un mensaje del historial, listo para pintar en el chat.

    Saca lo que `chat()` le agrega al mensaje del usuario para el modelo y que el usuario
    nunca escribió: el "(refiriéndote a: X)" y el aviso de que adjuntó una foto. Los dos son
    instrucciones para el modelo — el de la foto además ocupa varias líneas, y al repintar el
    chat aparecería como si las hubiera tipeado él. En su lugar queda un "📷 (foto)".
    """
    contenido = msg.get('content')
    if isinstance(contenido, str):
        salida = contenido
    else:
        salida = "\n".join(b.get('text', '') for b in (contenido or [])
                          if isinstance(b, dict) and b.get('type') == 'text')
    if msg.get('role') == 'user':
        salida = _SELLO_HORA.sub('', salida)
        salida = re.sub(r'\s*\(refiriéndote a:[^)]*\)\s*$', '', salida)
        salida = re.sub(r'\s*\[El usuario adjuntó una foto en este turno\.[\s\S]*$',
                       '\n📷 (foto)', salida)
    return salida.strip()


def _confirmaciones(fichas):
    """Un botón de confirmar por cada ficha de alta que sigue pendiente.

    Es una LISTA y no una sola ficha porque un mismo turno puede dar de alta varias cosas
    ("creá a Pablo y a Ezequiel"). Antes se mandaba únicamente la última: las anteriores
    quedaban vivas en la sesión pero sin ningún botón que las guardara, así que el usuario
    veía las dos fichas y solo se daba de alta una. Se perdían en silencio.

    Se devuelven TODAS las pendientes y no solo las de este turno: el front borra los
    botones apenas el usuario escribe (ver quitarConfirmaciones), con lo cual una ficha que
    quedó sin confirmar tiene que volver a aparecer debajo de la respuesta siguiente o se
    pierde igual. Como confirmar es siempre un click explícito, que reaparezcan no escribe
    nada de más.

    Cuando dos fichas pendientes son de la misma entidad — el usuario pidió un cambio y el
    modelo rearmó la ficha — se muestra solo la última: son la misma alta, no dos, y dos
    botones con el mismo nombre y distinto contenido no hay forma de distinguirlos.
    """
    por_entidad = {}
    for token, pendiente in (fichas or {}).items():
        slug = pendiente['slug']
        nombre = _nombre_de(slug, pendiente['campos'])
        singular = (_modulo(slug).ENTIDADES.get(slug, {}).get('singular') or 'registro').lower()
        por_entidad[(slug, texto.norm(nombre))] = {
            'token': token, 'etiqueta': f'Guardar {singular}', 'nombre': nombre}
    return list(por_entidad.values())


@bp.route('/historial', methods=['GET'])
def historial():
    """Conversación guardada, para repintar el chat al cargar la página.

    Desde que la conversación vive en `gestion.db` y no en la cookie, el servidor la
    recuerda pero el chat arrancaba en blanco cada vez que el usuario navegaba a otra
    página de /gestion. Esto la trae de vuelta, junto con los botones de las altas que hayan
    quedado sin confirmar (si no, al cambiar de página se perdía la única forma de darles OK).
    """
    conv = _conv_cargar()
    mensajes = [{'rol': m.get('role'), 'texto': _texto_visible(m)} for m in conv['historial']]
    return jsonify({'mensajes': [m for m in mensajes if m['texto']],
                    'confirmaciones': _confirmaciones(conv['fichas'])})


def _adjuntar_foto_pendiente(token, slug, id_nuevo):
    """Pasa la foto de la que salió el alta a la galería del registro recién creado.

    Devuelve el texto a sumarle al "✅ Guardado" (vacío si no había foto). Si la escritura
    falla no se toca el alta: el registro ya está creado y el token ya se consumió, así que
    lo único razonable es avisar que la foto quedó afuera.
    """
    if not id_nuevo:
        return ''
    foto = _foto_pendiente_tomar(token)
    if not foto:
        return ''
    b64, tipo = foto
    try:
        if crud.agregar_foto(_modulo(slug), slug, id_nuevo, b64, tipo):
            return ' Le guardé también la foto.'
    except Exception:
        pass
    return ' (La foto no se pudo adjuntar; podés subirla desde la ficha.)'


def _enlazar_protagonistas(hito_id, protagonistas):
    """Vincula el hito recién creado con las personas nombradas en `protagonistas`.

    Devuelve el texto a sumarle al "✅ Guardado" (vacío si no vinculó a nadie).

    Va del lado del código y no como instrucción al modelo porque el botón de confirmar
    NO pasa por el LLM: cuando el hito se escribe, el agente no tiene ningún turno para
    llamar a vincular_entidad, y el vínculo navegable (el que hace que el hito aparezca en
    la ficha de la persona) no lo creaba nadie. `protagonistas` seguía siendo texto suelto.

    Solo vincula personas YA cargadas y con el nombre completo: no crea personas nuevas ni
    adivina con un nombre de pila suelto.
    """
    if not hito_id or not (protagonistas or '').strip():
        return ''
    try:
        nombradas = _personas_nombradas_en(protagonistas)
        enlazadas = []
        for pid, nombre in nombradas:
            # La relación está declarada del lado de personas (ver historia.ENTIDADES).
            if _vincular_entidad('personas', pid, 'hitos', hito_id).get('ok'):
                enlazadas.append(nombre)
    except Exception:
        return ''
    if not enlazadas:
        return ''
    if len(enlazadas) == 1:
        return f' Lo vinculé con la ficha de {enlazadas[0]}.'
    return ' Lo vinculé con las fichas de ' + ', '.join(enlazadas[:-1]) + f' y {enlazadas[-1]}.'


@bp.route('/confirmar', methods=['POST'])
def confirmar():
    """Confirma un alta desde el botón del chat, sin pasar por el modelo.

    El botón manda solo el token de la ficha que el usuario vio; los campos salen de la
    sesión, nunca del request. Así lo que se guarda es literalmente lo que se mostró en
    pantalla, y da igual lo que arme el front. Tampoco hay una llamada al LLM de por
    medio: el alta es determinística y sale gratis.
    """
    token = (request.get_json() or {}).get('token', '')
    conv = _conv_cargar()
    fichas = dict(conv['fichas'])
    pendiente = fichas.get(token)

    if not pendiente:
        # Pasa si se reinició la conversación, si ya se confirmó, o si la ficha quedó
        # desplazada por otras más nuevas (tope FICHAS_MAX).
        return jsonify({'ok': False,
                        'respuesta': 'Esa ficha ya no está pendiente. Pedile al asistente que '
                                     'la vuelva a armar y confirmala de nuevo.'}), 409

    entrada = dict(pendiente['campos'])
    entrada['slug'] = pendiente['slug']
    contexto_turno = {'fichas_previas': fichas}
    resultado = ejecutar_tool('crear_entidad', entrada, contexto_turno)
    # `ejecutar_tool` consumió el token de `fichas` si llegó a escribir.

    if resultado.get('ok'):
        respuesta = f"✅ Guardado: **{_nombre_de(pendiente['slug'], pendiente['campos'])}**."
        respuesta += _adjuntar_foto_pendiente(token, pendiente['slug'], resultado.get('id'))
        if pendiente['slug'] == 'hitos':
            respuesta += _enlazar_protagonistas(resultado.get('id'),
                                                pendiente['campos'].get('protagonistas'))
        restantes = len(_confirmaciones(fichas))
        if restantes:
            respuesta += (f"\n\nQuedan {restantes} sin confirmar." if restantes > 1
                          else "\n\nQueda 1 sin confirmar.")
    else:
        respuesta = f"No se pudo guardar: {resultado.get('error', 'error desconocido')}"

    # Queda en el historial para que el asistente sepa, en el turno siguiente, que esto
    # ya se guardó y no lo ofrezca de nuevo. Va con nombre porque puede haber varios
    # botones a la vez: sin él, confirmar uno de tres se leía como "confirmó el alta" a
    # secas y el modelo no tenía forma de saber cuáles siguen pendientes.
    nombre_ficha = _nombre_de(pendiente['slug'], pendiente['campos'])
    historial = conv['historial'] + [
        {'role': 'user',
         'content': [{'type': 'text', 'text': f'(confirmé con el botón el alta de: {nombre_ficha})'}]},
        {'role': 'assistant', 'content': [{'type': 'text', 'text': respuesta}]},
    ]
    _conv_guardar(historial, conv['entidad_actual'], fichas)

    return jsonify({'ok': resultado.get('ok', False), 'respuesta': respuesta,
                    'tools': [{'tool': 'crear_entidad', 'ok': resultado.get('ok', False)}]})

@bp.route('/reset', methods=['POST'])
def reset():
    """Borra la conversación: historial, entidad de contexto y fichas sin confirmar."""
    _conv_borrar()
    return jsonify({'ok': True})

@bp.route('/log', methods=['GET'])
def agente_log():
    """Página de auditoría: últimas N entradas del agente_log."""
    con = conectar()
    cur = con.cursor()
    cur.execute("SELECT * FROM agente_log ORDER BY id DESC LIMIT 50")
    filas = [dict(row) for row in cur.fetchall()]
    con.close()

    return render_template('agente/agente_log.html', filas=filas)
