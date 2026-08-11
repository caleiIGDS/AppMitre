"""El lector de etiquetas: una llamada suelta al modelo de visión, sin tools.

Va aparte del chat porque el system prompt más TOOLS_SCHEMA son ~15.000 tokens que
viajan en cada turno del agente, contra ~2.000 de esta llamada. Con el lector separado
una foto cuesta ~7x menos y el chat sigue en su proveedor de siempre, sin tener que
elegir entre "bueno para razonar" y "ve imágenes".

Sólo se dispara desde la tool `leer_foto`: nunca automáticamente al llegar una foto.
"""
from .proveedores import _get_vision_config

# ============================================================================
# Lector de imágenes: una llamada suelta, sin tools
# ============================================================================

# Este prompt es a propósito solo de LECTURA. Todo lo que viene después de leer la
# etiqueta —que la cantidad la dice el usuario, que conviene fijarse si el recurso ya
# está cargado, el circuito de ficha y botón— sigue viviendo en el system prompt del
# agente, que es quien tiene las tools para hacerlo.
PROMPT_LECTOR_IMAGEN = """Sos un lector de etiquetas para el inventario de una escuela técnica.
Te llega una foto y devolvés, en texto plano y en castellano, ÚNICAMENTE lo que se lee en ella.

Reglas:
1. Transcribí lo que se lee de verdad: marca, modelo, potencia, tensión, corriente, capacidad,
   medidas, número de serie, año. Un dato por línea, con el nombre del campo adelante.
2. NUNCA completes con lo que sepas de ese producto o de esa marca por fuera de la foto. Si en
   la chapa no dice la potencia, la potencia no va. Preferí quedarte corto antes que inventar.
3. Si algo se lee a medias, ponelo con la duda explícita (ej: "Modelo: GA5030 (¿o GA5D30?)").
4. Si casi no se lee nada, decilo en una línea y pedí otra foto más cerca o con mejor luz.
5. Si la foto NO es una etiqueta (una máquina entera, un tablero, un cartel, una herramienta
   suelta), describí en una o dos frases qué se ve y qué objeto parece ser.
6. No saludes, no expliques lo que vas a hacer, no cierres con preguntas de cortesía. Solo la
   lectura."""

# Tope de la respuesta del lector. Una etiqueta bien leída son ~150 tokens; con 500 entra
# holgada y se acota lo que puede llegar a costar una foto rara.
VISION_MAX_TOKENS = 500


def _leer_imagen(imagen_base64, media_type, texto_usuario=''):
    """Lee una foto con el modelo de visión configurado. Devuelve el texto, o None.

    Devuelve None ante cualquier falla (sin API key, cuota agotada, 429 del tier gratuito,
    red caída) en vez de propagar: que no se pueda leer una foto no tiene por qué voltear
    el turno del chat — el que llama muestra el aviso y sigue.
    """
    config = _get_vision_config()
    if not config:
        return None

    contenido = [{'type': 'image_url',
                  'image_url': {'url': f'data:{media_type};base64,{imagen_base64}'}}]
    # Lo que escribió el usuario al mandar la foto ("esta es la amoladora del taller") ayuda
    # a desambiguar qué está mirando, pero no lo autoriza a inventar: el prompt manda.
    if texto_usuario:
        contenido.append({'type': 'text',
                          'text': f'El usuario escribió al mandarla: {texto_usuario}'})

    try:
        from openai import OpenAI
        cliente = OpenAI(api_key=config['api_key'], base_url=config['api_base'])
        respuesta = cliente.chat.completions.create(
            model=config['model'],
            max_tokens=VISION_MAX_TOKENS,
            messages=[
                {'role': 'system', 'content': PROMPT_LECTOR_IMAGEN},
                {'role': 'user', 'content': contenido},
            ],
        )
        return (respuesta.choices[0].message.content or '').strip() or None
    except Exception:
        return None
