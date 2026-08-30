"""Los endpoints Flask de /agente.

El gate de acceso es el mismo motor que /gestion e /historia (`accesos.registrar_acceso`),
pero acá el blueprint mezcla páginas HTML con endpoints JSON: sólo las páginas redirigen
al login y el resto contesta 401, que es lo que el fetch del chat sabe leer.
"""
import json
import re

from flask import Response, jsonify, render_template, request, stream_with_context

import accesos
import crud
import texto
from config import DIAS, ESCUELA_LOGO, ESCUELA_NOMBRE, ESCUELA_VERSION, ahora

from . import PERMISO_ESCRITURA, PERMISO_LECTURA, PERMISO_VISION, bp
from .db import (FICHAS_MAX, FOTOS_MAX, HISTORIAL_AL_MODELO, _conv_borrar, _conv_cargar,
                 _conv_guardar, _foto_lote_tomar, _fotos_lote_borrar, _fotos_lote_guardar,
                 _sid, _sin_imagenes, conectar)
from .dominio import _modulo, ve_entidad
from .filtros import (AVISO_NO_EJECUTADO, _es_pregunta_relativa, _escritura_no_ejecutada,
                      _extraer_entidad_mencionada, _ocultar_ids, _quitar_acotaciones)
from .llm import chat_with_tools_stream
from .padrones import _personas_nombradas_en
from .proveedores import _get_config, _get_vision_config
from .tools import ejecutar_tool
from .tools.entidades import _vincular_entidad
from .tools.fichas import (_campos_para_editar, _campos_validos, _nombre_de,
                           _normalizar_borrador, _token_ficha)

# Endpoints que devuelven HTML. Sin sesión conviene mandarlos al login propio de /agente
# (con `next` para volver acá), no un 401 pelado: entrar por link directo a /agente
# desde el celular es el caso normal, y ahí un 401 es un callejón.
# Los endpoints JSON sí siguen dando 401, que es lo que el fetch del chat sabe leer.
_ENDPOINTS_PAGINA = ('agente.chat_page', 'agente.agente_log')

# Gate de acceso: el mismo motor que /gestion y /historia, pero acá el blueprint mezcla
# páginas HTML con endpoints JSON, así que sólo las páginas redirigen al login y el resto
# contesta 401 — que es lo que el fetch del chat sabe leer.
#
# `agente.leer` es el piso: alcanza para chatear y consultar. Las rutas que escriben
# (`/confirmar`) o auditan (`/log`) piden más, marcadas con `accesos.requiere`.
accesos.registrar_acceso(bp, PERMISO_LECTURA, endpoints_pagina=_ENDPOINTS_PAGINA,
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

# El aviso de que hay fotos viaja pegado al mensaje del usuario, y son DOS textos porque
# la foto dura un solo turno. El primero es el que ve el modelo mientras las imágenes están
# en `contexto_turno`; el segundo es el que queda GUARDADO en el historial.
#
# Sin esa distinción el aviso quedaba en presente para siempre: en el turno siguiente el
# modelo leía "adjuntó una foto en este turno, todavía no la vio nadie, llamá a leer_foto",
# llamaba, y `leer_foto` le contestaba que no hay ninguna foto — porque efectivamente ya no
# estaba. Un "crea" después de una ficha se iba en esa vuelta perdida en vez de dar el alta.
#
# Los dos llevan los NÚMEROS de las fotos, que es lo que el modelo arrastra después en
# `crear_entidad(foto=N)` para que cada imagen termine en su ficha (ver db._fotos_lote_guardar).
# Los prefijos son los que busca `_texto_visible` para no mostrarlos en el chat: si cambian,
# cambiar allá también.

def _aviso_foto_actual(numeros):
    """Lo que el modelo lee mientras las fotos están disponibles, en el turno en que llegaron."""
    if len(numeros) == 1:
        return ("[El usuario adjuntó una foto en este turno (es la número "
                f"{numeros[0]}). Todavía no la vio nadie: si necesitás lo que dice, llamá a "
                "leer_foto; si solo hay que guardarla en una ficha que ya existe, llamá a "
                "adjuntar_foto. Si no sabés para qué te la mandaron o a qué registro va, "
                "preguntale.]")
    lista = ', '.join(str(n) for n in numeros)
    return (f"[El usuario adjuntó {len(numeros)} fotos en este turno, numeradas {lista}. "
            "Todavía no las vio nadie: si necesitás lo que dicen, llamá a leer_foto UNA SOLA "
            "VEZ y te devuelve las lecturas de todas juntas, cada una con su número; si solo "
            "hay que guardarlas en una ficha que ya existe, llamá a adjuntar_foto. Son cosas "
            "distintas salvo que el usuario diga lo contrario: una ficha por foto, y en cada "
            "crear_entidad pasá el número de la foto de la que salió. Si no sabés para qué te "
            "las mandaron, preguntale.]")


def _aviso_foto_vieja(numeros, lecturas=None):
    """El aviso en pasado, con las lecturas pegadas si esas fotos llegaron a leerse.

    Guardar la lectura es lo que permite terminar un alta en el turno siguiente: los
    resultados de las tools no se persisten, así que sin esto los datos de la etiqueta se
    perdían apenas el modelo terminaba de contestar.
    """
    cuantas = ('una foto' if len(numeros) == 1
               else f"{len(numeros)} fotos (números {', '.join(str(n) for n in numeros)})")
    aviso = (f"[En ese turno el usuario adjuntó {cuantas}, que YA NO ESTÁ disponible para "
             "mirar: las fotos duran un solo turno. No llames a leer_foto ni a adjuntar_foto "
             "por esto — te van a decir que no hay ninguna. Si necesitás datos que estaban ahí "
             "y no los tenés escritos más abajo en esta conversación, pedile al usuario que las "
             "mande de nuevo. El NÚMERO de cada foto sí sigue valiendo: si rearmás una ficha "
             "que salió de una de ellas, seguí pasando su número en crear_entidad.]")
    if not lecturas:
        return aviso
    detalle = '\n'.join(f"- Foto {l['foto']}: {l['lectura']}" for l in lecturas)
    return (f"{aviso}\n[Esto es lo que se leyó, y es TODO lo que se sabe de esas fotos — "
            f"usalo en vez de pedirlas de nuevo:\n{detalle}]")


# Lo que se le pone al modelo cuando mandan fotos sin escribir nada: un mensaje vacío no
# es un turno válido. `_texto_visible` lo saca al repintar, igual que el resto de lo que
# agrega el server — el usuario no lo escribió, y en el chat ya se ven las fotos.
TEXTO_FOTO_SOLA = 'Te mando esta foto.'

# Con qué arranca el mensaje que `/lote` manda en nombre del usuario al cerrar la revisión.
# `_texto_visible` lo usa para no pintarlo en el chat: el usuario tocó un botón, y el resto
# de ese texto son instrucciones para el modelo.
MARCA_LOTE = '(revisé las fichas con los botones)'

# Cuando mandan más de las que entran (ver db.FOTOS_MAX). Se recorta y se avisa en vez de
# rechazar el mensaje: perder las ocho primeras por haber mandado diez es peor.
def _aviso_recorte(mandadas):
    return (f"\n[El usuario mandó {mandadas} fotos y solo entran {FOTOS_MAX} por mensaje: las "
            f"que ves son las primeras {FOTOS_MAX}. Decíselo y pedile que mande el resto en "
            "otro mensaje cuando terminemos con estas.]")



# El sello de hora que se le pega a CADA mensaje del usuario. El system prompt ya trae la
# fecha y la hora del turno, pero es un bloque largo y lejano: cuando la conversación
# crece, el modelo contesta "ahora" con la hora del primer mensaje o directamente inventa
# una. Pegada al mensaje, la hora es lo último que leyó. Además queda en el historial, así
# que en un turno de seguimiento se ve cuánto pasó entre un mensaje y otro.
# `_texto_visible` lo saca antes de repintar el chat: el usuario no lo escribió.
_SELLO_HORA = re.compile(r'\s*\[Hora de este mensaje:[^\]]*\]')


def _foto_en_pasado(mensajes, aviso_actual, numeros, lecturas=None):
    """Cambia el aviso de fotos por su versión en pasado, justo antes de persistir.

    Se hace al guardar y no al construir el mensaje porque durante el turno el aviso en
    presente es correcto: las fotos SÍ están en `contexto_turno`. Lo que no puede quedar es
    esa misma frase en el historial del turno siguiente.

    Recibe `aviso_actual` en vez de mirar una constante porque el texto ahora lleva los
    números de las fotos del turno: hay que reemplazar exactamente el que se armó.
    """
    if not aviso_actual:
        return mensajes
    reemplazo = _aviso_foto_vieja(numeros, lecturas)
    limpios = []
    for msg in mensajes:
        contenido = msg.get('content')
        if not isinstance(contenido, list):
            limpios.append(msg)
            continue
        bloques = [
            {'type': 'text', 'text': b['text'].replace(aviso_actual, reemplazo)}
            if isinstance(b, dict) and b.get('type') == 'text' and aviso_actual in b.get('text', '')
            else b
            for b in contenido
        ]
        limpios.append({**msg, 'content': bloques})
    return limpios


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


def _normalizar_imagenes(data):
    """Las imágenes del request, como lista de `(b64, media_type)`, recortada a FOTOS_MAX.

    Acepta `imagenes` (lista, lo que manda el front) y `imagen` (una sola), que es el
    contrato viejo: no hay clientes afuera del repo, pero mantenerlo cuesta una línea y
    evita que una pestaña abierta de antes del deploy pierda la foto.

    Devuelve `(fotos, mandadas)`, donde `mandadas` es cuántas llegaron — se usa para avisar
    cuando hubo recorte.
    """
    crudas = data.get('imagenes')
    if not isinstance(crudas, list):
        crudas = [data['imagen']] if data.get('imagen') else []
    crudas = [c for c in crudas if c]

    fotos = []
    for cruda in crudas[:FOTOS_MAX]:
        b64 = cruda
        # Esperar formato: data:image/jpeg;base64,xxxxx o solo base64
        if b64.startswith('data:'):
            b64 = b64.split(',')[1]
        tipo = 'image/png' if b64.startswith('iVBO') else 'image/jpeg'  # '/9j/' es JPEG
        fotos.append((b64, tipo))
    return fotos, len(crudas)


def _turno(mensaje_usuario, fotos=(), mandadas=0):
    """El turno completo, de una. Devuelve el payload; los eventos de progreso se descartan."""
    gen = _turno_stream(mensaje_usuario, fotos, mandadas)
    while True:
        try:
            next(gen)
        except StopIteration as fin:
            return fin.value


def _turno_stream(mensaje_usuario, fotos=(), mandadas=0):
    """Un turno completo del chat: historial → modelo → filtros → persistencia.

    Lo usan `/chat` y `/chat/stream` (con lo que escribió el usuario) y `/lote` (con el
    mensaje que arma el servidor cuando quedaron fichas para corregir). Está afuera del
    endpoint porque son las mismas quince decisiones —el sello de hora, el aviso de fotos,
    los filtros de salida, el recorte del historial, qué fichas quedan pendientes— y
    tenerlas dos veces era garantía de que se fueran separando.

    Es un GENERADOR: larga los eventos de progreso de `chat_with_tools_stream` y devuelve
    el payload del turno como valor de retorno. Todo lo de antes y lo de después del modelo
    (guardar las fotos, persistir el historial) corre igual que siempre — lo único que se
    intercala es quién pide la próxima vuelta. `_turno` es el envoltorio que lo drena.

    `fotos` es una lista de `(b64, tipo)`; ya viene recortada a FOTOS_MAX.
    """
    # Conversación: sale de gestion.db, no de la cookie (ver _conv_cargar).
    conv = _conv_cargar()
    # Si venía vencida, lo que el front tiene pintado de antes ya no es lo que el agente
    # recuerda (ver _conv_cargar). Viaja en la respuesta para que limpie la vista vieja.
    reiniciada = conv['vencida']
    mensajes = conv['historial'][-HISTORIAL_AL_MODELO:]

    # Si el usuario hace una pregunta relativa sin especificar quién, inyectar referencia anterior
    entidad_actual = conv['entidad_actual']  # Último profesor/recurso consultado
    msg_procesado = mensaje_usuario

    if entidad_actual and _es_pregunta_relativa(mensaje_usuario):
        # Agregar contexto: "¿En qué lugar?" → "¿En qué lugar tiene clases [entidad]?"
        msg_procesado = f"{mensaje_usuario} (refiriéndote a: {entidad_actual})"

    # La hora va con el mensaje, no sólo en el system prompt (ver _sello_hora).
    msg_procesado = f"{msg_procesado}\n{_sello_hora()}"

    # Las fotos se numeran y se guardan ANTES de llamar al modelo: el número es lo que él va
    # a arrastrar en `crear_entidad(foto=N)` para que cada imagen termine en su ficha, y
    # tiene que estar disponible cuando confirme, que puede ser mucho después.
    numeros = _fotos_lote_guardar(fotos)
    aviso_actual = _aviso_foto_actual(numeros) if numeros else ''
    if aviso_actual and mandadas > len(fotos):
        aviso_actual += _aviso_recorte(mandadas)

    # Construir el contenido del mensaje del usuario (con las imágenes si vienen)
    contenido = [{'type': 'text', 'text': msg_procesado}]

    # Qué se hace con las fotos:
    #  - Si el proveedor del chat ve imágenes (AGENTE_PROVIDER=anthropic o AGENTE_VISION=1) y
    #    NO hay lector aparte, se le mandan al agente directamente: es el único caso
    #    donde el que razona puede mirarlas.
    #  - Si no, las fotos no viajan: se le avisa al modelo que las tiene disponibles y él
    #    decide qué hacer — `leer_foto` si necesita los datos de la etiqueta, `adjuntar_foto`
    #    si solo hay que guardarlas en una ficha, preguntar si no está claro. Salen de
    #    `contexto_turno['fotos_turno']` (ver más abajo), no de un parámetro.
    #
    # Antes, no tener lector cortaba el turno acá con un aviso fijo y el modelo no llegaba a
    # correr. El razonamiento era "sin visión contestaría inventando lo que vio", pero se
    # comía el caso más común: ADJUNTAR una foto no necesita verla, y con el corte
    # `adjuntar_foto` era inalcanzable. Ahora el turno corre siempre y la distinción la hace
    # el modelo; si pide leer sin lector, se lo dice el error de `leer_foto`.
    if fotos and _get_config()['vision'] and not _get_vision_config():
        for b64, tipo in fotos:
            contenido.append({
                'type': 'image',
                'source': {'type': 'base64', 'media_type': tipo, 'data': b64}
            })

    elif fotos:
        contenido[0]['text'] = f"{msg_procesado}\n\n{aviso_actual}"

    # Agregar mensaje del usuario al historial. Las imágenes van en una clave aparte de
    # `content` (no las ve el LLM, ver `_sin_imagenes`): es lo que permite repintarlas en el
    # chat sin volver a mandarlas al modelo en los turnos siguientes.
    mensaje_usuario_msg = {'role': 'user', 'content': contenido}
    if fotos:
        mensaje_usuario_msg['imagenes'] = [{'b64': b64, 'tipo': tipo} for b64, tipo in fotos]
    mensajes.append(mensaje_usuario_msg)

    # Obtener respuesta del agente.
    # `fichas_previas` son las fichas de alta que el usuario YA vio en turnos anteriores;
    # sin esto no habría forma de confirmar un alta, porque los resultados de las tools no
    # quedan en el historial y en el turno siguiente el modelo no tiene la ficha a la vista.
    trazas = []
    contexto_turno = {'fichas_previas': dict(conv['fichas'])}
    if fotos:
        # `leer_foto` y `adjuntar_foto` las sacan de acá: el modelo nunca ve la imagen, así
        # que no puede pasarla como parámetro. Va con el número, que es lo único de la foto
        # que él maneja.
        contexto_turno['fotos_turno'] = [{'n': n, 'b64': b64, 'tipo': tipo}
                                         for n, (b64, tipo) in zip(numeros, fotos)]
        contexto_turno['texto_usuario'] = mensaje_usuario
    # Sólo `role`+`content` viajan al LLM: la API rechaza claves que no reconoce, y la
    # clave `imagenes` de arriba es puramente para la UI.
    mensajes_llm = [{'role': m['role'], 'content': m['content']} for m in mensajes]
    respuesta = yield from chat_with_tools_stream(
        mensajes_llm, trazas=trazas, contexto_turno=contexto_turno,
        permisos=accesos.permisos())
    # Se filtra ANTES de guardar, así el historial repintado tampoco muestra ids — y, en el
    # caso de las acotaciones, el modelo no las tiene como ejemplo a imitar en el turno que viene.
    respuesta = _ocultar_ids(respuesta)
    respuesta = _quitar_acotaciones(respuesta)

    # Lo que quedó pendiente de revisar + lo que se mostró recién.
    fichas = _fusionar_fichas(contexto_turno.get('fichas_previas', {}),
                              contexto_turno.get('fichas_mostradas', {}))

    # Las fotos de este turno que no terminaron en ninguna ficha se tiran acá mismo. La
    # mayoría de las fotos no son un alta —"¿qué es esto?", "guardala en el taladro"— y sin
    # esto cada una de esas dejaría cientos de KB esperando en la DB una confirmación que no
    # va a llegar nunca, hasta el barrido de los CONVERSACION_MINUTOS.
    reclamadas = {f.get('foto') for f in fichas.values() if f.get('foto')}
    for n in numeros:
        if n not in reclamadas:
            _foto_lote_tomar(n)

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
    # solo el recorte que vio el modelo). Las imágenes no se guardan dentro de `content`: una
    # foto en base64 pesa megas y no se reusa en turnos siguientes — queda una nota en su
    # lugar, y el aviso pasa a su versión en pasado (`_foto_en_pasado`) porque las fotos
    # mueren con el turno aunque su número siga valiendo.
    historial = conv['historial'] + _foto_en_pasado(
        _sin_imagenes(mensajes[-2:]), aviso_actual, numeros,
        contexto_turno.get('lectura_foto'))
    _conv_guardar(historial, entidad, fichas)

    # Si quedaron fichas esperando revisión, el front pinta sus botones debajo del mensaje,
    # en vez de que el usuario tenga que escribir "sí" (ver /revisar y /lote).
    return {'respuesta': respuesta, 'tools': trazas,
            'escritura_fantasma': escritura_fantasma,
            'confirmaciones': _confirmaciones(fichas),
            'reiniciada': reiniciada}


def _identidad_ficha(pendiente):
    """Qué hace que dos fichas sean la MISMA alta y no dos.

    El token es el hash del CONTENIDO, así que rearmar una ficha con un campo corregido da
    otro token: sin una identidad aparte, la vieja y la nueva quedan las dos vivas. La foto
    de la que salió es la identidad confiable cuando la hay; para las altas de texto queda
    el nombre, que es lo único que las distingue.
    """
    if pendiente.get('foto'):
        return ('foto', pendiente['foto'])
    slug = pendiente['slug']
    return (slug, texto.norm(_nombre_de(slug, pendiente['campos'])))


def _fusionar_fichas(previas, mostradas):
    """Las fichas pendientes después de un turno: las que ya estaban + las nuevas.

    Una ficha nueva REEMPLAZA a la anterior de su misma identidad. Es el caso de "esa está
    mal, la marca es Makita": el modelo rearma la ficha, el token cambia y sin esto quedan
    las dos vivas. Y no alcanza con esconder la vieja al mostrar los botones: al guardar la
    nueva, la vieja —con los datos que el usuario ya rechazó— volvía a aparecer sola en el
    turno siguiente, y un segundo click daba de alta el mismo recurso dos veces.

    Se colapsa el dict entero y no solo lo que pisan las nuevas, para que una sesión que ya
    venía con la ficha repetida se limpie en el próximo turno.
    """
    fichas = dict(previas)
    fichas.update(mostradas)
    ultimo = {_identidad_ficha(f): t for t, f in fichas.items()}
    vivos = set(ultimo.values())
    fichas = {t: f for t, f in fichas.items() if t in vivos}
    return dict(list(fichas.items())[-FICHAS_MAX:])


def _pedido_de_chat():
    """Lo que mandó el navegador, validado. Devuelve `(mensaje, fotos, mandadas, error)`.

    Lo comparten `/chat` y `/chat/stream`: los dos hacen el mismo turno y sólo se
    diferencian en cómo lo devuelven. `error` es el `(json, status)` listo para retornar, o
    None si está todo bien.
    """
    data = request.get_json() or {}
    mensaje_usuario = data.get('mensaje', '').strip()
    fotos, mandadas = _normalizar_imagenes(data)

    # Mandar fotos pide `agente.vision`. El front ni siquiera le muestra el botón a quien
    # no lo tiene, pero eso es cosmética: el corte que vale es éste, porque el POST se arma
    # a mano en dos líneas. Es un 403 y no un silencio para que el chat lo diga (el fetch ya
    # traduce el 403 a "Este acceso no puede hacer eso") en vez de tragarse la imagen y
    # contestar como si el usuario no hubiera mandado nada.
    if fotos and not accesos.puede(PERMISO_VISION):
        return None, (), 0, (jsonify({'error': 'Este acceso no puede mandar imágenes.'}), 403)

    # Una foto sola es un mensaje válido: sacan la etiqueta y la mandan sin escribir nada.
    if not mensaje_usuario and fotos:
        mensaje_usuario = TEXTO_FOTO_SOLA

    if not mensaje_usuario:
        return None, (), 0, (jsonify({'error': 'Mensaje vacío'}), 400)

    return mensaje_usuario, fotos, mandadas, None


@bp.route('/chat', methods=['POST'])
def chat():
    """Endpoint para el widget de chat. JSON con 'mensaje' y opcionalmente 'imagenes'
    (lista de base64). Mantiene historial + última entidad consultada para mejor contexto.

    Contesta de una, con el turno ya terminado. Sigue existiendo porque es el contrato que
    conocen las pestañas abiertas desde antes del deploy; el front nuevo usa `/chat/stream`.
    """
    mensaje_usuario, fotos, mandadas, error = _pedido_de_chat()
    if error:
        return error

    return jsonify(_turno(mensaje_usuario, fotos, mandadas))


# Cómo se llama, en castellano y para el que espera, lo que el modelo pidió. Es copy de la
# pantalla y no un atributo de la tool: el esquema de `tools/esquemas.py` es lo único que ve
# el MODELO, y esto es lo único que ve el USUARIO. Una tool sin entrada acá cae en el default,
# así que agregar una tool no rompe nada — sólo se ve más genérico.
ETIQUETA_TOOL = {
    'buscar_profesor': 'buscando a la persona',
    'buscar_por_rol': 'buscando por cargo',
    'preceptores': 'viendo preceptores',
    'horario_profesor': 'buscando el horario',
    'horario_curso': 'buscando el horario del curso',
    'horario_aula': 'buscando el horario del aula',
    'aulas_libres': 'viendo qué aulas hay libres',
    'buscar_entidad': 'buscando en el inventario',
    'listar_todos': 'revisando el inventario',
    'listar_alias': 'revisando los alias',
    'detalle_entidad': 'leyendo la ficha',
    'consultar_historia': 'buscando en la memoria de la casa',
    'buscar_hitos': 'revisando la línea del tiempo',
    'crear_entidad': 'armando la ficha',
    'leer_foto': 'leyendo las fotos',
    'adjuntar_foto': 'guardando la foto',
    'editar_entidad': 'guardando los cambios',
    'vincular_entidad': 'vinculando',
    'desvincular_entidad': 'desvinculando',
    'mover_ubicacion': 'moviendo el recurso',
    'eliminar_entidad': 'eliminando',
}

ETIQUETA_PENSANDO = 'pensando'
ETIQUETA_TOOL_DEFAULT = 'consultando'


def _sse(tipo, **datos):
    """Un evento en formato Server-Sent Events.

    Un solo tipo de evento SSE con un campo `tipo` adentro, en vez de varios `event:`: del
    lado del navegador es un `switch` sobre una línea de JSON y no hay que registrar un
    listener por cada clase de evento.
    """
    return 'data: ' + json.dumps({'tipo': tipo, **datos}, ensure_ascii=False) + '\n\n'


@bp.route('/chat/stream', methods=['POST'])
def chat_stream():
    """El mismo turno que `/chat`, pero contando en qué anda mientras lo hace.

    Un turno con varias tools son varias llamadas al modelo, una atrás de la otra, y cada
    una tarda lo suyo — el modelo razona antes de pedir la primera tool. Con la respuesta de
    una sola pieza el usuario miraba tres puntitos quietos durante casi un minuto sin forma
    de saber si estaba pasando algo. Acá va largando `paso` a medida que avanza y termina
    con un `fin` que trae exactamente el mismo payload que devuelve `/chat`.

    El otro motivo es la conexión: PythonAnywhere corta las requests que se quedan calladas,
    y un turno largo se moría entero sin devolver nada. Un evento cada pocos segundos la
    mantiene viva.
    """
    mensaje_usuario, fotos, mandadas, error = _pedido_de_chat()
    if error:
        return error

    # El id de conversación se toca ACÁ y no adentro del generador. Vive en la cookie, y la
    # cookie viaja en los headers — que Flask ya mandó cuando el cuerpo empieza a streamear.
    # Un visitante nuevo que arranca mandando un mensaje se quedaba sin sid persistido y cada
    # mensaje suyo abría una conversación nueva.
    _sid()

    def eventos():
        gen = _turno_stream(mensaje_usuario, fotos, mandadas)
        while True:
            try:
                paso = next(gen)
            except StopIteration as fin:
                yield _sse('fin', **fin.value)
                return
            except Exception as e:
                # El turno ya arrancó, así que no hay forma de contestar un 500: los headers
                # se mandaron con el primer evento. Va como evento de error y el chat lo pinta.
                yield _sse('error', error=str(e))
                return

            if paso.get('paso') == 'tool':
                yield _sse('paso', texto=ETIQUETA_TOOL.get(paso['tool'], ETIQUETA_TOOL_DEFAULT))
            else:
                yield _sse('paso', texto=ETIQUETA_PENSANDO)

    return Response(stream_with_context(eventos()), mimetype='text/event-stream',
                    # Sin esto Nginx bufferea el stream entero y lo entrega junto al final,
                    # que es exactamente lo que este endpoint viene a evitar.
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


def _texto_visible(msg):
    """Texto plano de un mensaje del historial, listo para pintar en el chat.

    Saca lo que `chat()` le agrega al mensaje del usuario para el modelo y que el usuario
    nunca escribió: el "(refiriéndote a: X)" y el aviso de que adjuntó una foto. Los dos son
    instrucciones para el modelo — el de la foto además ocupa varias líneas, y al repintar el
    chat aparecería como si las hubiera tipeado él. No queda nada en su lugar: la foto se
    repinta de verdad, desde `msg['imagen']` (ver `historial()`).
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
        # Los dos avisos: el del turno en curso y el que queda guardado en pasado (que
        # además arrastra las lecturas de las etiquetas). Desde el aviso hasta el final del
        # mensaje es todo texto para el modelo, así que se corta entero. No queda ningún
        # "(foto)" en su lugar: las fotos se repintan de verdad (ver `_mensaje_visible`).
        # El prefijo se corta antes del número de fotos, así que sirve igual para los
        # mensajes viejos ("una foto") y los nuevos ("3 fotos").
        salida = re.sub(r'\s*\[(?:El usuario adjuntó '
                        r'|En ese turno el usuario adjuntó )[\s\S]*$',
                        '', salida)
        if salida.strip() == TEXTO_FOTO_SOLA:
            salida = ''
        # El mensaje que arma `/lote` en nombre del usuario: son instrucciones para el
        # modelo ("rearmá cada una, llamá a crear_entidad…") y el resumen de lo guardado ya
        # se lo dijo la respuesta de abajo. El usuario tocó un botón, no escribió esto.
        if salida.startswith(MARCA_LOTE):
            salida = ''
    return salida.strip()


def _confirmaciones(fichas):
    """Una fila de revisión por cada ficha de alta que sigue pendiente.

    Es una LISTA y no una sola ficha porque un mismo turno puede dar de alta varias cosas
    ("creá a Pablo y a Ezequiel", u ocho fotos de etiquetas). Antes se mandaba únicamente la
    última: las anteriores quedaban vivas en la sesión pero sin ningún botón que las
    guardara, así que el usuario veía las dos fichas y solo se daba de alta una. Se perdían
    en silencio.

    Se devuelven TODAS las pendientes y no solo las de este turno: una ficha sin revisar
    tiene que volver a aparecer debajo de la respuesta siguiente o se pierde igual. Que
    reaparezcan no escribe nada de más — guardar es siempre un click explícito.

    Cada fila lleva su `estado` (lo que el usuario marcó en `/revisar`) y, si la acotó, la
    `nota`. Sin eso, cambiar de página o mandar otro mensaje borraba la revisión hecha hasta
    ahí y había que empezar de nuevo con las ocho.

    Cuando dos fichas pendientes son la misma alta — el usuario pidió un cambio y el modelo
    rearmó la ficha — se muestra solo la última: dos botones con el mismo nombre y distinto
    contenido no hay forma de distinguirlos. `_fusionar_fichas` ya las colapsa en la sesión;
    esto es la red por si la sesión venía con una repetida de antes. La identidad es la
    misma en los dos lados (`_identidad_ficha`).
    """
    por_entidad = {}
    for token, pendiente in (fichas or {}).items():
        slug = pendiente['slug']
        nombre = _nombre_de(slug, pendiente['campos'])
        singular = (_modulo(slug).ENTIDADES.get(slug, {}).get('singular') or 'registro').lower()
        fila = {'token': token, 'etiqueta': f'Guardar {singular}', 'nombre': nombre,
                'estado': pendiente.get('estado', 'pendiente'),
                'campos': _campos_para_editar(slug, pendiente['campos'])}
        if pendiente.get('nota'):
            fila['nota'] = pendiente['nota']
        if pendiente.get('foto'):
            fila['foto'] = pendiente['foto']
        if pendiente['campos'].get('_sub_recursos'):
            fila['sub_recursos'] = pendiente['campos']['_sub_recursos']
        por_entidad[_identidad_ficha(pendiente)] = fila
    # Ordenadas por número de foto: el usuario las mandó en ese orden y las revisa mirando
    # el chat, donde las miniaturas están en esa misma secuencia.
    return sorted(por_entidad.values(), key=lambda f: f.get('foto') or 0)


def _mensaje_visible(msg):
    """Un mensaje del historial en la forma que espera el chat: texto + fotos si tenía.

    `imagenes` es lo que guarda `_turno`; `imagen` (singular) es el formato viejo, que sigue
    en las conversaciones de antes del deploy — se lee igual para que no queden mensajes
    mancos al repintar.
    """
    item = {'rol': msg.get('role'), 'texto': _texto_visible(msg)}
    guardadas = msg.get('imagenes') or ([msg['imagen']] if msg.get('imagen') else [])
    if guardadas:
        item['imagenes'] = ['data:{};base64,{}'.format(i.get('tipo', 'image/jpeg'),
                                                       i.get('b64', ''))
                            for i in guardadas]
    return item


@bp.route('/historial', methods=['GET'])
def historial():
    """Conversación guardada, para repintar el chat al cargar la página.

    Desde que la conversación vive en `gestion.db` y no en la cookie, el servidor la
    recuerda pero el chat arrancaba en blanco cada vez que el usuario navegaba a otra
    página de /gestion. Esto la trae de vuelta, junto con las fichas que hayan quedado sin
    guardar y el estado de revisión de cada una (si no, al cambiar de página se perdía la
    única forma de darles OK, y con el lote se perdía además la revisión ya hecha).
    """
    conv = _conv_cargar()
    mensajes = [_mensaje_visible(m) for m in conv['historial']]
    return jsonify({'mensajes': [m for m in mensajes if m['texto'] or m.get('imagenes')],
                    'confirmaciones': _confirmaciones(conv['fichas'])})


def _adjuntar_foto_pendiente(pendiente, slug, id_nuevo):
    """Pasa la foto de la que salió el alta a la galería del registro recién creado.

    La foto se busca por el NÚMERO que la ficha trae en `foto` (el que el modelo arrastró
    desde `leer_foto`), no por el token: el token cambia en cuanto la ficha se rearma con
    una corrección, y ahí la imagen se perdía. Ver `db._fotos_lote_guardar`.

    Devuelve el texto a sumarle al "✅ Guardado" (vacío si no había foto). Si la escritura
    falla no se toca el alta: el registro ya está creado y el token ya se consumió, así que
    lo único razonable es avisar que la foto quedó afuera.
    """
    if not id_nuevo:
        return ''
    foto = _foto_lote_tomar(pendiente.get('foto'))
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

    Y sólo con permiso para ver `personas`: el vínculo se escribe mirando el padrón de
    fichas, y el texto que devuelve nombra a quién se enlazó. Sin el permiso, el hito se
    guarda igual con sus `protagonistas` en texto — lo que no se crea es el vínculo.
    """
    if not hito_id or not (protagonistas or '').strip():
        return ''
    if not ve_entidad('personas', accesos.permisos()):
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


def _guardar_ficha(token, fichas):
    """Escribe una ficha aprobada. Devuelve `(ok, nombre, detalle)`.

    Es el alta de verdad: `ejecutar_tool` consume el token de `fichas` al escribir, y
    después se le cuelgan las dos cosas que no puede hacer el modelo porque acá no hay
    ningún turno suyo — la foto de la que salió y el vínculo con las personas del hito.

    Está afuera de `/confirmar` porque `/lote` hace exactamente esto N veces. `detalle` es
    lo que se le suma a la línea de esa ficha ("Le guardé también la foto.").
    """
    pendiente = fichas[token]
    slug = pendiente['slug']
    nombre = _nombre_de(slug, pendiente['campos'])

    entrada = dict(pendiente['campos'])
    entrada['slug'] = slug
    resultado = ejecutar_tool('crear_entidad', entrada, {'fichas_previas': fichas},
                              permisos=accesos.permisos())

    if not resultado.get('ok'):
        return False, nombre, resultado.get('error', 'error desconocido')

    detalle = _adjuntar_foto_pendiente(pendiente, slug, resultado.get('id'))
    if slug == 'hitos':
        detalle += _enlazar_protagonistas(resultado.get('id'),
                                          pendiente['campos'].get('protagonistas'))
    return True, nombre, detalle


def _cerrar_lote(fichas):
    """Tira las fotos que no fue a buscar nadie, cuando ya no queda ninguna ficha viva.

    Una foto pendiente pesa cientos de KB y no tiene ningún uso una vez que su ficha se
    guardó o se descartó. Mientras quede una ficha con número de foto no se toca nada: esa
    imagen es justamente la que va a necesitar cuando la confirme.
    """
    if not any(f.get('foto') for f in fichas.values()):
        _fotos_lote_borrar()


def _turno_de_botones(conv, texto_usuario, respuesta, fichas):
    """Deja en el historial lo que se hizo con los botones, como un turno más.

    El asistente no ve los clicks: sin esto, en el turno siguiente sigue creyendo que esas
    altas están pendientes y las vuelve a ofrecer. Va con los nombres porque puede haber
    varias fichas a la vez — "confirmó el alta" a secas no dice cuál de las ocho.
    """
    historial = conv['historial'] + [
        {'role': 'user', 'content': [{'type': 'text', 'text': texto_usuario}]},
        {'role': 'assistant', 'content': [{'type': 'text', 'text': respuesta}]},
    ]
    _conv_guardar(historial, conv['entidad_actual'], fichas)


@bp.route('/confirmar', methods=['POST'])
@accesos.requiere(PERMISO_ESCRITURA, como_json=True)
def confirmar():
    """Guarda UNA ficha desde su botón, sin pasar por el modelo.

    Es el camino corto, el de la ficha sola: cuando el turno dejó una única alta, meterle un
    circuito de revisión de dos pasos sería un click de más para el caso de siempre. Con
    varias fichas el front no usa esta ruta sino `/revisar` + `/lote`.

    El botón manda solo el token de la ficha que el usuario vio; los campos salen de la
    sesión, nunca del request. Así lo que se guarda es literalmente lo que se mostró en
    pantalla, y da igual lo que arme el front. Tampoco hay una llamada al LLM de por
    medio: el alta es determinística y sale gratis.

    El permiso va explícito porque esta ruta ESCRIBE sin pasar por el LLM: recortar las
    tools que ve el modelo no la protege en absoluto. Sin este decorador, un acceso de
    lectura que forjara el POST con un token de ficha escribiría en el inventario.
    """
    token = (request.get_json() or {}).get('token', '')
    conv = _conv_cargar()
    fichas = dict(conv['fichas'])

    if token not in fichas:
        # Pasa si se reinició la conversación, si ya se confirmó, o si la ficha quedó
        # desplazada por otras más nuevas (tope FICHAS_MAX).
        return jsonify({'ok': False,
                        'respuesta': 'Esa ficha ya no está pendiente. Pedile al asistente que '
                                     'la vuelva a armar y confirmala de nuevo.'}), 409

    ok, nombre, detalle = _guardar_ficha(token, fichas)

    if ok:
        respuesta = f"✅ Guardado: **{nombre}**.{detalle}"
        restantes = len(_confirmaciones(fichas))
        if restantes:
            respuesta += (f"\n\nQuedan {restantes} sin confirmar." if restantes > 1
                          else "\n\nQueda 1 sin confirmar.")
    else:
        respuesta = f"No se pudo guardar: {detalle}"

    _cerrar_lote(fichas)
    _turno_de_botones(conv, f'(confirmé con el botón el alta de: {nombre})', respuesta, fichas)

    return jsonify({'ok': ok, 'respuesta': respuesta,
                    'confirmaciones': _confirmaciones(fichas),
                    'tools': [{'tool': 'crear_entidad', 'ok': ok}]})


@bp.route('/descartar', methods=['POST'])
@accesos.requiere(PERMISO_ESCRITURA, como_json=True)
def descartar():
    """Descarta UNA ficha pendiente desde su botón. No guarda nada ni pasa por el modelo.

    Es el "cancelar" del circuito de una sola ficha: `/lote` ya tiene su "✕ no va" por fila,
    pero acá no hay lote que cerrar — sin esto la única forma de bajar una ficha que no se
    quiere era dejarla pendiente para siempre (hasta que la desplazara el tope FICHAS_MAX).

    Mismo permiso que `/confirmar`: no escribe en el inventario, pero sí borra la foto
    pendiente si la ficha tenía una.
    """
    token = (request.get_json() or {}).get('token', '')
    conv = _conv_cargar()
    fichas = dict(conv['fichas'])

    if token not in fichas:
        return jsonify({'ok': False,
                        'respuesta': 'Esa ficha ya no está pendiente.'}), 409

    pendiente = fichas.pop(token)
    slug = pendiente['slug']
    nombre = _nombre_de(slug, pendiente['campos'])
    _foto_lote_tomar(pendiente.get('foto'))
    _cerrar_lote(fichas)

    respuesta = f"🗑️ Descarté: **{nombre}**. No se guardó nada."
    _turno_de_botones(conv, f'(cancelé con el botón el alta de: {nombre})', respuesta, fichas)

    return jsonify({'ok': True, 'respuesta': respuesta, 'confirmaciones': _confirmaciones(fichas)})


ESTADOS_REVISION = ('pendiente', 'ok', 'observada', 'descartada')


@bp.route('/revisar', methods=['POST'])
@accesos.requiere(PERMISO_ESCRITURA, como_json=True)
def revisar():
    """Marca una ficha del lote como aprobada, observada o descartada. NO escribe nada.

    Es el paso que faltaba para poder cargar de a muchas: con ocho fichas en pantalla, el
    botón que guarda al toque obliga a decidir de a una y sin vuelta atrás, y cualquier
    corrección se llevaba puesto lo ya revisado. Acá la marca es reversible y no cuesta
    nada — ni una escritura en el inventario ni una llamada al modelo.

    Pide `agente.escribir` igual que `/confirmar`: no toca el dominio, pero es el circuito
    de alta, y quien no puede escribir no tiene fichas que revisar.
    """
    data = request.get_json() or {}
    token = data.get('token', '')
    estado = data.get('estado', '')
    nota = (data.get('nota') or '').strip()

    if estado not in ESTADOS_REVISION:
        return jsonify({'ok': False, 'error': f'Estado inválido: {estado}'}), 400

    conv = _conv_cargar()
    fichas = dict(conv['fichas'])
    if token not in fichas:
        return jsonify({'ok': False,
                        'respuesta': 'Esa ficha ya no está pendiente. Pedile al asistente que '
                                     'la vuelva a armar.'}), 409

    ficha = dict(fichas[token])
    ficha['estado'] = estado
    # La nota solo tiene sentido en una ficha observada: si el usuario la aprueba después de
    # haberla acotado, el texto viejo no tiene que quedar dando vueltas ni terminar en el
    # mensaje que se le manda al modelo.
    if estado == 'observada' and nota:
        ficha['nota'] = nota
    else:
        ficha.pop('nota', None)
    fichas[token] = ficha

    # No se persiste ningún turno: los clicks de revisión no son conversación, y meter ocho
    # mensajes de "marqué esta" en el historial le costaría contexto al modelo sin decirle
    # nada que no vaya a leer después, ya resumido, en el mensaje de /lote.
    _conv_guardar(conv['historial'], conv['entidad_actual'], fichas)
    return jsonify({'ok': True, 'confirmaciones': _confirmaciones(fichas)})


@bp.route('/editar_ficha', methods=['POST'])
@accesos.requiere(PERMISO_ESCRITURA, como_json=True)
def editar_ficha():
    """Aplica en la tarjeta del chat una edición manual de una ficha pendiente. NO escribe nada.

    El usuario corrige el campo ahí mismo en vez de pedírselo al asistente por chat. El token
    es un hash del CONTENIDO de la ficha (ver fichas._token_ficha): cambiar un campo cambia el
    token, así que acá se recalcula y la entrada vieja se reemplaza por la nueva bajo su token
    nuevo — lo mismo que pasa cuando el modelo rearma una ficha, pero sin pasar por el LLM. Es
    lo que hace que `/confirmar` siga guardando exactamente lo que el usuario tiene en pantalla.

    El estado de revisión del lote vuelve a 'pendiente': el contenido cambió, así que una ficha
    que ya estaba marcada ✅ tiene que volver a aprobarse.

    Mismo permiso que `/revisar`: no toca el dominio, pero es el circuito de alta.
    """
    data = request.get_json() or {}
    token = data.get('token', '')
    campos_editados = data.get('campos') or {}

    conv = _conv_cargar()
    fichas = dict(conv['fichas'])
    if token not in fichas:
        return jsonify({'ok': False,
                        'respuesta': 'Esa ficha ya no está pendiente. Pedile al asistente que '
                                     'la vuelva a armar.'}), 409

    pendiente = dict(fichas[token])
    slug = pendiente['slug']
    validos = set(_campos_validos(slug))
    # `_lugar` no es un campo de la entidad pero sí una fila editable de la tarjeta de
    # `recursos` (ver fichas._campos_para_editar): dejalo pasar para que la corrección de
    # la ubicación desde el chat entre al borrador y recalcule el token.
    if slug == 'recursos':
        validos.add('_lugar')
    nuevos = dict(pendiente['campos'])
    for nombre, valor in campos_editados.items():
        if nombre in validos:
            nuevos[nombre] = valor
    borrador = _normalizar_borrador(slug, nuevos)

    campo_nombre = crud.campo_nombre(_modulo(slug).ENTIDADES[slug])
    if not borrador.get(campo_nombre):
        return jsonify({'ok': False, 'error': f'El campo "{campo_nombre}" no puede quedar '
                                              'vacío.'}), 400

    nuevo_token = _token_ficha(slug, borrador)
    pendiente['campos'] = borrador
    pendiente['estado'] = 'pendiente'
    pendiente.pop('nota', None)

    if nuevo_token != token:
        fichas.pop(token, None)
    fichas[nuevo_token] = pendiente

    _conv_guardar(conv['historial'], conv['entidad_actual'], fichas)
    return jsonify({'ok': True, 'token': nuevo_token, 'confirmaciones': _confirmaciones(fichas)})


def _mensaje_correcciones(guardados, descartados, observadas):
    """El mensaje que el servidor manda en nombre del usuario al cerrar el lote.

    Lleva las tres listas porque las tres le dicen algo distinto al modelo: lo guardado para
    que no lo vuelva a ofrecer, lo descartado para que no insista, y lo acotado para que lo
    rearme. Es un solo mensaje para todo el lote y no uno por corrección: ocho fichas serían
    ocho llamadas al modelo y ocho respuestas que el usuario tendría que leer.

    Sin fichas observadas queda como puro registro de lo que pasó — es lo que se guarda en
    el historial cuando el lote se cierra sin llamar al modelo.
    """
    partes = [MARCA_LOTE]
    if guardados:
        partes.append('Guardé: ' + ', '.join(guardados) + '.')
    if descartados:
        partes.append('Descarté: ' + ', '.join(descartados) + '.')

    if observadas:
        partes.append(
            'Estas NO se guardaron. Rearmá cada una con la corrección que te digo y volvé a '
            'mostrar la ficha (llamá a crear_entidad una vez por cada una, en este mismo '
            'turno, con el MISMO número de foto para que no se pierda la imagen):')
        for ficha in observadas:
            origen = f" (foto {ficha['foto']})" if ficha.get('foto') else ''
            nota = ficha.get('nota') or 'está mal, revisala conmigo'
            partes.append(f"- \"{ficha['nombre']}\"{origen}: {nota}")
    return '\n'.join(partes)


@bp.route('/lote', methods=['POST'])
@accesos.requiere(PERMISO_ESCRITURA, como_json=True)
def lote():
    """Cierra la revisión: guarda las aprobadas y manda las acotadas a una segunda vuelta.

    Es el "recién ahora se envía todo". Hasta este click no se escribió una sola fila: el
    usuario pudo mirar las ocho fichas, aprobar cinco, acotar dos y tachar una sin que nada
    quedara a medio hacer en el inventario.

    Las acotadas NO se guardan y salen de las pendientes: vuelven al modelo dentro de un
    único mensaje con todas las correcciones juntas, y él las rearma. Las que no salieron de
    una foto se pierden si el modelo no las rearma, pero el texto de la corrección queda en
    el historial y la foto sobrevive igual, atada a su número.

    Si no quedó nada que corregir NO se llama al modelo: la respuesta se arma acá, como en
    `/confirmar`. Un lote todo aprobado es el caso más común y no tiene por qué costar un
    turno de LLM.
    """
    conv = _conv_cargar()
    fichas = dict(conv['fichas'])
    filas = {f['token']: f for f in _confirmaciones(fichas)}

    guardados, lineas_ok, fallados, descartados, observadas = [], [], [], [], []

    for token, fila in filas.items():
        estado = fila.get('estado', 'pendiente')
        if estado == 'ok':
            ok, nombre, detalle = _guardar_ficha(token, fichas)
            if ok:
                guardados.append(nombre)
                lineas_ok.append(f'- **{nombre}**{detalle}')
            else:
                fallados.append(f'- {nombre} ({detalle})')
        elif estado == 'descartada':
            descartados.append(fila['nombre'])
            _foto_lote_tomar(fichas[token].get('foto'))   # la imagen tampoco hace falta ya
            fichas.pop(token, None)
        elif estado == 'observada':
            observadas.append(fila)
            fichas.pop(token, None)

    if not lineas_ok and not fallados and not descartados and not observadas:
        return jsonify({'ok': False,
                        'respuesta': 'No hay ninguna ficha revisada todavía.'}), 409

    # Resumen de lo que se hizo, que es lo que el usuario ve arriba de todo.
    bloques = []
    if lineas_ok:
        bloques.append(f"✅ Guardé {len(lineas_ok)}:\n" + '\n'.join(lineas_ok))
    if fallados:
        bloques.append(f"⚠️ No se pudieron guardar {len(fallados)}:\n" + '\n'.join(fallados))
    if descartados:
        bloques.append('🗑️ Descarté: ' + ', '.join(descartados) + '.')
    respuesta = '\n\n'.join(bloques)

    mensaje_modelo = _mensaje_correcciones(guardados, descartados, observadas)

    if not observadas:
        _cerrar_lote(fichas)
        _turno_de_botones(conv, mensaje_modelo, respuesta, fichas)
        return jsonify({'ok': True, 'respuesta': respuesta,
                        'confirmaciones': _confirmaciones(fichas)})

    # Segunda vuelta. Se persiste ANTES de llamar al modelo porque `_turno` vuelve a cargar
    # la conversación de la DB: si no, las fichas que se acaban de guardar seguirían ahí y
    # el modelo las vería como pendientes.
    _conv_guardar(conv['historial'], conv['entidad_actual'], fichas)
    salida = _turno(mensaje_modelo)
    # El resumen de lo guardado va primero: es lo que el usuario acaba de pedir, y la
    # respuesta del modelo abajo son las fichas nuevas para revisar.
    if respuesta:
        salida['respuesta'] = f"{respuesta}\n\n{salida['respuesta']}"
    salida['ok'] = True
    return jsonify(salida)



@bp.route('/reset', methods=['POST'])
def reset():
    """Borra la conversación: historial, entidad de contexto y fichas sin confirmar."""
    _conv_borrar()
    return jsonify({'ok': True})

@bp.route('/log', methods=['GET'])
@accesos.requiere('agente.auditar')
def agente_log():
    """Página de auditoría: últimas N entradas del agente_log."""
    con = conectar()
    cur = con.cursor()
    cur.execute("SELECT * FROM agente_log ORDER BY id DESC LIMIT 50")
    filas = [dict(row) for row in cur.fetchall()]
    con.close()

    return render_template('agente/agente_log.html', filas=filas)
