"""El lector de imágenes: una llamada suelta al modelo de visión, sin tools.

Va aparte del chat porque el system prompt más TOOLS_SCHEMA son ~15.000 tokens que
viajan en cada turno del agente, contra ~2.000 de esta llamada. Con el lector separado
una foto cuesta ~7x menos y el chat sigue en su proveedor de siempre, sin tener que
elegir entre "bueno para razonar" y "ve imágenes".

Sólo se dispara desde la tool `leer_foto`: nunca automáticamente al llegar una foto.

Tiene dos modos, que son dos prompts sobre la misma llamada y el mismo modelo. El modelo
de visión siempre pudo mirar la imagen entera; lo que lo acota a transcribir es el prompt,
así que agregar "que además describa" no es cambiar de proveedor, es elegir cuál mandar:

- `etiqueta` (default): transcribe lo que está escrito. Es el que alimenta el alta.
- `analisis`: describe lo que se ve cuando no hay nada escrito que sirva.

Se mantienen separados en vez de fusionarlos en un prompt que haga las dos cosas porque
son dos exigencias opuestas. En `etiqueta` "quedate corto antes que inventar" es la regla
que hace confiable el alta; un prompt que además pida describir le abre la puerta a
completar la chapa con lo que el modelo sabe de esa marca, que es exactamente el error
que no queremos en una ficha de inventario.
"""
import config as config_app

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

# El otro modo: cuando en la foto no hay nada escrito que sirva y lo que se necesita saber
# es QUÉ ES. Mismas anclas que el lector de etiquetas —solo lo que se ve, la duda explícita,
# nada de completar con lo que el modelo sepa— pero aplicadas al objeto en vez de al texto.
PROMPT_ANALISIS_IMAGEN = """Sos el ojo de un asistente de inventario de una escuela técnica.
Te llega una foto de algo del taller y describís, en texto plano y en castellano, ÚNICAMENTE
lo que se ve en ella.

Reglas:
1. Empezá diciendo qué objeto es, con el nombre que usaría un docente de taller ("amoladora
   angular", "fuente de banco", "motor trifásico"). Si no estás seguro de qué es, decí a qué
   se parece y que no es seguro.
2. Después, lo que se distingue a simple vista: tamaño aparente, color, material, partes que
   se reconocen, si está montado o suelto. Si se lee alguna marca o número, transcribilo tal
   cual, pero NO es el foco de este modo.
3. Estado visible, y solo el visible: óxido, cables pelados, carcasa rota, piezas que faltan,
   suciedad. Si no se ve ningún problema, decí "sin daños visibles en la foto" — NO digas que
   está en buen estado ni que funciona: eso no se ve en una foto.
4. Si hay varias unidades del mismo objeto, decí cuántas se cuentan y si son todas iguales.
5. NUNCA completes con lo que sepas de ese producto, de esa marca o de ese tipo de máquina
   por fuera de la foto. Nada de potencias, tensiones ni años que no estén a la vista.
   Preferí quedarte corto antes que inventar.
6. Si la foto está oscura, movida o muy lejos, decilo en una línea y pedí otra.
7. No saludes, no expliques lo que vas a hacer, no cierres con preguntas de cortesía."""

# Tope de la respuesta, por modo. Una etiqueta bien leída son ~150 tokens; con 500 entra
# holgada y se acota lo que puede llegar a costar una foto rara. La descripción de un objeto
# es más larga por naturaleza, pero tampoco queremos un ensayo: 900 alcanza para las cuatro
# o cinco frases que pide el prompt.
VISION_MAX_TOKENS = 500
VISION_MAX_TOKENS_ANALISIS = 900

# El default es `etiqueta` en todos lados: es el caso que alimenta el alta, y si el modelo
# llama a la tool sin elegir modo, el que no inventa es el que queremos.
MODOS = {
    'etiqueta': (PROMPT_LECTOR_IMAGEN, VISION_MAX_TOKENS),
    'analisis': (PROMPT_ANALISIS_IMAGEN, VISION_MAX_TOKENS_ANALISIS),
}
MODO_DEFAULT = 'etiqueta'


def _leer_imagen(imagen_base64, media_type, texto_usuario='', modo=MODO_DEFAULT):
    """Lee una foto con el modelo de visión configurado. Devuelve el texto, o None.

    `modo` elige el prompt: 'etiqueta' transcribe lo escrito, 'analisis' describe el objeto.
    Un modo desconocido cae al default en vez de fallar — lo elige el modelo llamando a la
    tool, y una alucinación en el nombre del modo no tiene por qué costar la foto.

    Devuelve None ante cualquier falla (sin API key, cuota agotada, 429 del tier gratuito,
    red caída) en vez de propagar: que no se pueda leer una foto no tiene por qué voltear
    el turno del chat — el que llama muestra el aviso y sigue.
    """
    config = _get_vision_config()
    if not config:
        return None

    prompt, max_tokens = MODOS.get(modo, MODOS[MODO_DEFAULT])

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
            max_tokens=max_tokens,
            messages=[
                {'role': 'system', 'content': prompt},
                {'role': 'user', 'content': contenido},
            ],
        )
        return (respuesta.choices[0].message.content or '').strip() or None
    except Exception as e:
        # Tragarse el error es lo correcto para el usuario, pero deja ciego al que está
        # configurando: key inválida, modelo dado de baja, cuota agotada y red caída se
        # ven todos como "no se pudo leer la foto". Fuera de producción se imprime, que es
        # la diferencia entre leer el 404 y adivinarlo. Nunca en producción: el error del
        # proveedor puede traer la key en el texto.
        if not config_app.PRODUCCION:
            print(f'[vision] falló la lectura ({modo}) con {config["model"]}: '
                  f'{type(e).__name__}: {e}')
        return None
