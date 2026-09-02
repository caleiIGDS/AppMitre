"""El motor: clientes por proveedor y los dos loops de tool-calling.

Son dos loops y no un `if` adentro de uno porque entre Anthropic y las APIs compatibles
con OpenAI cambia todo lo que importa: el método, el finish_reason, dónde va el system
prompt y cómo se devuelven los resultados de las tools.
"""
import json

from config import DIAS, ahora

from .notas import leer as _notas_del_admin
from .prompt import construir_system_prompt
from .proveedores import _get_config
from .tools import (TOOLS_ESCRITURA, TOOLS_FOTO, TOOLS_NOTAS, ejecutar_tool, slug_visible,
                    tools_permitidas)


# ============================================================================
# Loop de tool-calling agnóstico del LLM
# ============================================================================

def _crear_cliente_llm():
    """Crea un cliente para el LLM configurado."""
    config = _get_config()
    provider = config['provider']
    api_key = config['api_key']
    api_base = config['api_base']

    if provider == 'anthropic':
        from anthropic import Anthropic
        if not api_key:
            raise ValueError("Error: AGENTE_API_KEY o ANTHROPIC_API_KEY no está configurada.")
        return Anthropic(api_key=api_key)

    elif provider == 'groq':
        from groq import Groq
        if not api_key:
            raise ValueError("Error: AGENTE_API_KEY o GROQ_API_KEY no está configurada.")
        return Groq(api_key=api_key)

    elif provider == 'openai':
        from openai import OpenAI
        if not api_key:
            raise ValueError("Error: AGENTE_API_KEY o OPENAI_API_KEY no está configurada.")
        # base_url opcional: permite apuntar a cualquier API compatible con OpenAI
        return OpenAI(api_key=api_key, base_url=api_base) if api_base else OpenAI(api_key=api_key)

    elif provider == 'deepseek':
        from openai import OpenAI  # DeepSeek es compatible con la API de OpenAI
        if not api_key:
            raise ValueError("Error: AGENTE_API_KEY o DEEPSEEK_API_KEY no está configurada.")
        return OpenAI(api_key=api_key, base_url=api_base)

    elif provider == 'ollama':
        from openai import OpenAI  # Ollama es compatible con OpenAI API
        if not api_base:
            raise ValueError("Error: AGENTE_API_BASE no está configurada (default: http://localhost:11434).")
        return OpenAI(api_key='ollama', base_url=f"{api_base}/v1")

    else:
        raise ValueError(f"Proveedor LLM desconocido: {provider}")

PROVIDERS_OPENAI = ('openai', 'groq', 'ollama', 'deepseek')

MSG_SIN_TOKENS = ('Me quedé sin tokens: la cuenta del proveedor del LLM se quedó sin '
                 'crédito o cuota disponible. Avisale a un administrador para recargarla.')


def _es_error_sin_tokens(e):
    """Detecta si la excepción es por falta de crédito/cuota, no un error cualquiera.

    Anthropic y OpenAI (y las compatibles: Groq, DeepSeek) usan códigos distintos para
    lo mismo: 429 (rate/quota) o un 400 con 'credit balance too low'. Se mira el
    status_code y el texto del mensaje en vez de importar las clases de excepción de
    cada SDK, porque Groq es opcional y puede no estar instalado.
    """
    if getattr(e, 'status_code', None) == 429:
        return True
    texto = str(e).lower()
    return 'credit balance' in texto or 'insufficient_quota' in texto or 'quota' in texto

# Tope de salida por vuelta del loop. Estaba en 1024 y era MUY poco: `deepseek-v4-pro`
# razona antes de emitir, y ese razonamiento se cobra como tokens de salida — medido,
# gasta entre 700 y 1600 sólo en pensar antes de largar la primera tool call. Con 1024 se
# quedaba sin presupuesto a mitad de camino y devolvía `finish_reason='length'` con el
# contenido vacío, que el loop traducía a "Sin respuesta". El síntoma era peor cuanto más
# difícil el turno: contestar "¿qué preceptor tiene 1° C?" entraba, armar la ficha de un
# alta no.
#
# Se subió de nuevo a 16000 porque el prompt le pide al modelo mandar TODAS las
# `crear_entidad` de un lote de fotos en la MISMA vuelta (ver "Cargar de a muchas: el
# lote" en agent_docs/agente-asistente.md) — con FOTOS_MAX=10 eso es razonamiento + hasta
# diez tool calls completas en una sola respuesta, y 4096 se quedaba corto a mitad de
# camino igual que antes. No es un tope de costo (sólo se cobra lo generado), así que se
# deja holgado.
MAX_TOKENS_SALIDA = 16000


def _uso(response, provider, modelo):
    """Tokens de UNA llamada al modelo, normalizados. Nunca lanza.

    Cada API los nombra distinto y ninguna garantiza que vengan: un Ollama local no manda
    `usage` en absoluto, y los nombres de la cache son de cada proveedor —DeepSeek los pone
    sueltos en `usage`, OpenAI los anida en `prompt_tokens_details`, Anthropic tiene los
    suyos—. Un proveedor que no los mande da ceros; medir mal no puede costar el turno.

    `cache` son tokens de ENTRADA que ya estaban cacheados: no se suman aparte (ya están
    dentro de `entrada`), se guardan para poder cobrarlos a su precio, que es más barato.
    """
    vacio = {'provider': provider, 'modelo': modelo,
             'entrada': 0, 'salida': 0, 'cache': 0}
    try:
        u = getattr(response, 'usage', None)
        if u is None:
            return vacio

        # Anthropic
        if getattr(u, 'input_tokens', None) is not None:
            return {'provider': provider, 'modelo': modelo,
                    'entrada': (getattr(u, 'input_tokens', 0) or 0)
                               + (getattr(u, 'cache_read_input_tokens', 0) or 0)
                               + (getattr(u, 'cache_creation_input_tokens', 0) or 0),
                    'salida': getattr(u, 'output_tokens', 0) or 0,
                    'cache': getattr(u, 'cache_read_input_tokens', 0) or 0}

        # OpenAI y compatibles (DeepSeek, Groq, Ollama)
        detalle = getattr(u, 'prompt_tokens_details', None)
        cache = (getattr(u, 'prompt_cache_hit_tokens', None)          # DeepSeek
                 or getattr(detalle, 'cached_tokens', None)           # OpenAI
                 or 0)
        return {'provider': provider, 'modelo': modelo,
                'entrada': getattr(u, 'prompt_tokens', 0) or 0,
                'salida': getattr(u, 'completion_tokens', 0) or 0,
                'cache': cache}
    except Exception:
        return vacio


def _tools_openai(tools):
    """Esquemas (formato Anthropic) → formato de function calling de OpenAI.

    Anthropic usa {name, description, input_schema}; OpenAI/DeepSeek/Groq esperan
    {type:'function', function:{name, description, parameters}}. El JSON Schema en sí
    es idéntico, solo cambia el envoltorio.

    Recibe la lista ya filtrada por permisos: acá no se decide nada, sólo se traduce.
    """
    return [
        {
            'type': 'function',
            'function': {
                'name': t['name'],
                'description': t['description'],
                'parameters': t['input_schema'],
            }
        }
        for t in tools
    ]


def _mensajes_openai(mensajes, vision=False):
    """Historial en bloques de contenido (formato Anthropic) → mensajes de OpenAI.

    El historial se guarda en sesión como [{'role':..., 'content':[{'type':'text',...}]}].
    Sin visión se aplana todo a un string y las imágenes quedan como una nota: el default
    (deepseek) no las ve. Con visión (`AGENTE_VISION=1`, ej. gpt-4o o llava) se manda el
    formato multimodal de OpenAI, que es `image_url` con un data URI — no el bloque
    `image`/`source` de Anthropic.
    """
    out = []
    for m in mensajes:
        contenido = m.get('content')
        if isinstance(contenido, str):
            out.append({'role': m['role'], 'content': contenido})
            continue

        if vision and any(isinstance(b, dict) and b.get('type') == 'image'
                          for b in (contenido or [])):
            partes = []
            for bloque in contenido:
                if not isinstance(bloque, dict):
                    continue
                if bloque.get('type') == 'text':
                    partes.append({'type': 'text', 'text': bloque.get('text', '')})
                elif bloque.get('type') == 'image':
                    src = bloque.get('source') or {}
                    partes.append({
                        'type': 'image_url',
                        'image_url': {'url': 'data:{};base64,{}'.format(
                            src.get('media_type', 'image/jpeg'), src.get('data', ''))}
                    })
            out.append({'role': m['role'], 'content': partes})
            continue

        partes = []
        for bloque in (contenido or []):
            if not isinstance(bloque, dict):
                continue
            if bloque.get('type') == 'text':
                partes.append(bloque.get('text', ''))
            elif bloque.get('type') == 'image':
                partes.append('[el usuario adjuntó una imagen, pero este proveedor no '
                              'soporta visión: pedile los datos por texto]')
        out.append({'role': m['role'], 'content': '\n'.join(p for p in partes if p)})
    return out


def _loop_openai(client, model, system_prompt, mensajes_usuario, trazas, max_iterations=10,
                 contexto_turno=None, permisos=frozenset(), tools_disponibles=()):
    """Loop de tool-calling para APIs compatibles con OpenAI (DeepSeek, Groq, Ollama, GPT).

    Es un loop aparte y no un `if` dentro del de Anthropic porque cambia todo lo que
    importa: el método (`chat.completions.create` vs `messages.create`), el finish_reason
    ('tool_calls' vs 'tool_use'), dónde va el system prompt (mensaje vs parámetro) y cómo
    se devuelven los resultados (rol 'tool' vs bloques 'tool_result' en un mensaje user).

    Es un GENERADOR: va largando eventos de progreso (ver `chat_with_tools_stream`) y
    devuelve la respuesta final como valor de retorno.
    """
    # `contexto_turno` es también por dónde sale la medición del turno (ver `_uso`): el
    # default None existe para llamarlo suelto desde una consola, no en el camino normal.
    if contexto_turno is None:
        contexto_turno = {}
    provider = _get_config()['provider']

    msgs = ([{'role': 'system', 'content': system_prompt}]
            + _mensajes_openai(mensajes_usuario, vision=_get_config()['vision']))
    tools = _tools_openai(tools_disponibles)

    for vuelta in range(max_iterations):
        yield {'paso': 'pensando', 'vuelta': vuelta + 1}
        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=MAX_TOKENS_SALIDA,
                messages=msgs,
                tools=tools,
            )
        except Exception as e:
            # El turno que muere por cuota es justo el que más interesa contar, y es el que
            # no deja ni una vuelta medida: el estado es todo lo que queda de él.
            sin_tokens = _es_error_sin_tokens(e)
            contexto_turno['estado'] = 'sin_tokens' if sin_tokens else 'error'
            contexto_turno['detalle_error'] = f'{type(e).__name__}: {e}'
            if sin_tokens:
                return MSG_SIN_TOKENS
            return f"Error llamando al LLM: {str(e)}"

        # Una entrada por VUELTA, no por turno: el loop llama al modelo hasta
        # `max_iterations` veces y cada llamada se cobra aparte.
        contexto_turno.setdefault('uso', []).append(_uso(response, provider, model))

        choice = response.choices[0]
        msg = choice.message
        tool_calls = getattr(msg, 'tool_calls', None)

        if not tool_calls:
            texto = (msg.content or '').strip()
            if texto:
                return texto
            # Sin tools y sin texto: casi siempre es el tope de salida cortando el
            # razonamiento antes de que el modelo escriba nada. Devolver "Sin respuesta"
            # a secas mandaba al usuario a adivinar —y encima quedaba guardado en el
            # historial, envenenando los turnos siguientes—, así que se distingue.
            if choice.finish_reason == 'length':
                contexto_turno['estado'] = 'tope_salida'
                return ('Me quedé sin espacio para responder a mitad de camino. '
                        'Probá de nuevo, o pedímelo en dos partes más chicas.')
            contexto_turno['estado'] = 'sin_respuesta'
            return 'Sin respuesta'

        # El mensaje del asistente tiene que volver con sus tool_calls intactos, si no
        # la API rechaza los mensajes 'tool' que vienen después.
        msgs.append({
            'role': 'assistant',
            'content': msg.content or '',
            'tool_calls': [
                {
                    'id': tc.id,
                    'type': 'function',
                    'function': {'name': tc.function.name, 'arguments': tc.function.arguments},
                }
                for tc in tool_calls
            ],
        })

        for tc in tool_calls:
            try:
                tool_input = json.loads(tc.function.arguments or '{}')
            except (ValueError, TypeError):
                tool_input = {}
            if not isinstance(tool_input, dict):
                tool_input = {}

            yield {'paso': 'tool', 'tool': tc.function.name}
            resultado = ejecutar_tool(tc.function.name, tool_input, contexto_turno,
                                      permisos=permisos)
            trazas.append({
                'tool': tc.function.name,
                'ok': resultado.get('ok', True) if isinstance(resultado, dict) else True
            })
            msgs.append({
                'role': 'tool',
                'tool_call_id': tc.id,
                'content': json.dumps(resultado, default=str, ensure_ascii=False),
            })

    contexto_turno['estado'] = 'tope_iteraciones'
    return 'Máximo de iteraciones alcanzado'


def chat_with_tools_stream(mensajes_usuario, trazas=None, contexto_turno=None,
                           permisos=frozenset()):
    """
    Llama al LLM configurado con la lista de tools, ejecuta lo que pida, repite hasta
    que el modelo da una respuesta final de texto. Retorna la respuesta final.
    Agnóstico del proveedor LLM (Anthropic, Groq, OpenAI, Ollama, DeepSeek).

    Es un GENERADOR. Va largando eventos de progreso — `{'paso': 'pensando', 'vuelta': n}`
    antes de cada llamada al modelo y `{'paso': 'tool', 'tool': nombre}` antes de cada
    tool — y la respuesta final es el valor de retorno (`StopIteration.value`). Quien no
    tenga a nadie mirando la pantalla lo drena con un `while` y se queda con ese valor:
    eso es `rutas._turno`.

    Generador y no un callback `on_evento` porque el consumidor es una respuesta HTTP que
    va streameando: con callback habría que correr el turno en un hilo aparte y pasarle los
    eventos por una cola, y ese hilo se queda sin el request context de Flask (la sesión, de
    donde sale el id de conversación). Como generador el turno corre en el mismo hilo de
    siempre y lo único que cambia es quién pide la próxima vuelta.

    `trazas`: lista opcional donde se registra cada tool ejecutada en este turno
    (nombre + ok). Las lecturas no van a `agente_log` (sería ruido), así que sin esto
    no había forma de saber si el modelo consultó de verdad o inventó la respuesta —
    que es exactamente como se detectó que fabricaba horarios enteros.

    `permisos`: los del acceso que está chateando. Recortan las tools ANTES de mandarlas,
    así que el modelo ni se entera de que existen las que no le corresponden. Es distinto
    a prohibírselas: una tool que no está en la lista no se anuncia ni se alucina. El
    default vacío es fail-closed.
    """
    if trazas is None:
        trazas = []
    # Estado compartido por todas las tools de ESTE turno (ver ejecutar_tool) y, de paso,
    # por donde sale la medición de tokens. Se resuelve acá arriba y no más abajo porque el
    # error de configuración de las próximas líneas también tiene que quedar registrado.
    if contexto_turno is None:
        contexto_turno = {}

    try:
        client = _crear_cliente_llm()
    except ValueError as e:
        contexto_turno['estado'] = 'error'
        contexto_turno['detalle_error'] = f'{type(e).__name__}: {e}'
        return str(e)

    # La hora se resuelve acá, al empezar el turno, y no una vez al arrancar el server:
    # el prompt se arma de nuevo en cada mensaje justamente para que no se quede vieja.
    hoy = ahora()
    dia_semana = DIAS[hoy.weekday()] if hoy.weekday() < len(DIAS) else hoy.strftime('%A')

    tools = tools_permitidas(permisos)
    # El prompt se deriva de las tools que EFECTIVAMENTE se mandan, no del set de permisos:
    # así es imposible que el prompt hable de dar de alta mientras las tools de alta no
    # viajaron. Una sola fuente para las dos mitades del mismo mensaje.
    nombres = {t['name'] for t in tools}
    escribe = bool(TOOLS_ESCRITURA & nombres)
    # Mismo criterio para las fichas de personas: si `personas` no sobrevivió en los enum
    # de slug, el prompt tampoco describe el área ni ofrece darlas de alta.
    ve_personas = slug_visible(tools, 'personas')
    # Y para las fotos: sin `agente.vision` no viajan `leer_foto` ni `adjuntar_foto`, así que
    # el prompt tampoco explica qué hacer con una foto — que además el usuario no puede mandar.
    ve_fotos = bool(TOOLS_FOTO & nombres)
    # Y para `agente.md`: sin `agente.notas` no viaja `escribir_notas`, así que el prompt no
    # nombra el archivo y este acceso no lee una sola línea. Se lee del disco una vez por
    # turno — es la única parte del prompt que no está en el código.
    ve_notas = bool(TOOLS_NOTAS & nombres)
    system_prompt = construir_system_prompt(hoy, dia_semana,
                                            escribe=escribe, ve_personas=ve_personas,
                                            ve_fotos=ve_fotos, ve_notas=ve_notas,
                                            notas=_notas_del_admin() if ve_notas else '')

    # Una tanda de fotos es el turno más largo que existe: leer todas (1 vuelta) + una
    # `crear_entidad` por foto. Si el modelo no las paraleliza, diez fichas (FOTOS_MAX) son
    # diez vueltas, y con el tope corto el turno se cortaba en "Máximo de iteraciones
    # alcanzado" — con las fichas a medio armar y el usuario sin nada que revisar.
    max_iterations = 16

    if _get_config()['provider'] in PROVIDERS_OPENAI:
        return (yield from _loop_openai(
            client, _get_config()['model'], system_prompt, mensajes_usuario, trazas,
            max_iterations, contexto_turno, permisos=permisos, tools_disponibles=tools))

    # Copiar la lista para no mutar el historial original (que se persiste en sesión
    # como texto plano) con objetos complejos de la API (ToolUseBlock, etc.)
    messages = list(mensajes_usuario)

    # Loop: hasta que el modelo no quiera más tools
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        yield {'paso': 'pensando', 'vuelta': iteration}

        try:
            response = client.messages.create(
                model=_get_config()['model'],
                max_tokens=MAX_TOKENS_SALIDA,
                system=system_prompt,
                tools=tools,
                messages=messages
            )
        except Exception as e:
            sin_tokens = _es_error_sin_tokens(e)
            contexto_turno['estado'] = 'sin_tokens' if sin_tokens else 'error'
            contexto_turno['detalle_error'] = f'{type(e).__name__}: {e}'
            if sin_tokens:
                return MSG_SIN_TOKENS
            return f"Error llamando al LLM: {str(e)}"

        # Una entrada por vuelta del while, igual que en `_loop_openai`.
        contexto_turno.setdefault('uso', []).append(
            _uso(response, _get_config()['provider'], _get_config()['model']))

        # Determinar stop reason (compatible con Anthropic, Groq, OpenAI, Ollama)
        stop_reason = getattr(response, 'stop_reason', None)
        if not stop_reason and hasattr(response, 'choices') and response.choices:
            # OpenAI/Groq/Ollama
            stop_reason = response.choices[0].finish_reason

        # Si el modelo dice "stop" o "end_turn", se acabó
        if stop_reason in ['end_turn', 'stop']:
            # Extraer el texto final
            texto_final = ''
            if hasattr(response, 'content'):
                # Anthropic
                for block in response.content:
                    if hasattr(block, 'text'):
                        texto_final = block.text
                        break
            elif hasattr(response, 'choices') and response.choices:
                # OpenAI/Groq/Ollama
                texto_final = response.choices[0].message.content or ''
            if not texto_final:
                contexto_turno['estado'] = 'sin_respuesta'
            return texto_final or 'Sin respuesta'

        # Si quiere usar tools (Anthropic: 'tool_use')
        if stop_reason == 'tool_use':
            # Agregar la respuesta del asistente al historial
            if hasattr(response, 'content'):
                # Anthropic
                messages.append({'role': 'assistant', 'content': response.content})
            else:
                # OpenAI/Groq/Ollama
                messages.append({'role': 'assistant', 'content': response.choices[0].message.content})

            # Ejecutar cada tool que pidió
            tool_results = []

            if hasattr(response, 'content'):
                # Anthropic: response.content es una lista de bloques
                for block in response.content:
                    if hasattr(block, 'type') and block.type == 'tool_use':
                        tool_name = block.name
                        tool_input = block.input
                        tool_use_id = block.id

                        yield {'paso': 'tool', 'tool': tool_name}
                        resultado = ejecutar_tool(tool_name, tool_input, contexto_turno,
                                                  permisos=permisos)
                        trazas.append({
                            'tool': tool_name,
                            'ok': resultado.get('ok', True) if isinstance(resultado, dict) else True
                        })

                        tool_results.append({
                            'type': 'tool_result',
                            'tool_use_id': tool_use_id,
                            'content': json.dumps(resultado, default=str, ensure_ascii=False)
                        })
            else:
                # OpenAI/Groq/Ollama: revisar tool_calls en la respuesta
                if hasattr(response.choices[0].message, 'tool_calls') and response.choices[0].message.tool_calls:
                    for tool_call in response.choices[0].message.tool_calls:
                        tool_name = tool_call.function.name
                        try:
                            tool_input = json.loads(tool_call.function.arguments)
                        except:
                            tool_input = tool_call.function.arguments

                        yield {'paso': 'tool', 'tool': tool_name}
                        resultado = ejecutar_tool(tool_name, tool_input, contexto_turno,
                                                  permisos=permisos)
                        trazas.append({
                            'tool': tool_name,
                            'ok': resultado.get('ok', True) if isinstance(resultado, dict) else True
                        })

                        tool_results.append({
                            'type': 'tool_result',
                            'tool_use_id': tool_call.id,
                            'content': json.dumps(resultado, default=str, ensure_ascii=False)
                        })

            # Agregar los resultados al historial
            if tool_results:
                messages.append({'role': 'user', 'content': tool_results})

        else:
            # Otro stop_reason o llegamos al max de iteraciones
            texto_final = ''
            if hasattr(response, 'content'):
                # Anthropic
                for block in response.content:
                    if hasattr(block, 'text'):
                        texto_final = block.text
                        break
            elif hasattr(response, 'choices') and response.choices:
                # OpenAI/Groq/Ollama
                texto_final = response.choices[0].message.content or ''
            if not texto_final:
                contexto_turno['estado'] = 'sin_respuesta'
            return texto_final or 'Sin respuesta'

    contexto_turno['estado'] = 'tope_iteraciones'
    return 'Máximo de iteraciones alcanzado'
