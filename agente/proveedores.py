"""Configuración del LLM del chat y del lector de imágenes.

Son DOS configuraciones independientes a propósito: el chat puede estar en DeepSeek (que
no ve imágenes) y el lector de etiquetas en Gemini, sin que una decisión condicione la
otra. Ver `vision.py`.

Se llama `proveedores` y no `config` para no confundirse con el `config.py` de la raíz
del proyecto (SHEET_ID, DIAS, branding), que es otra cosa y también se importa acá.
"""
import os

# ============================================================================
# Configuración del LLM (agnóstico del proveedor) — Lee en tiempo de request
# ============================================================================

_config_cache = None

def _get_config():
    """Lee la configuración del LLM en tiempo de request (lazy loading)."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    provider = os.environ.get('AGENTE_PROVIDER', 'deepseek').lower()
    model = os.environ.get('AGENTE_MODEL', '')
    api_key = os.environ.get('AGENTE_API_KEY', '')
    api_base = os.environ.get('AGENTE_API_BASE', '')

    # Defaults por proveedor
    if provider == 'anthropic':
        if not api_key:
            api_key = os.environ.get('ANTHROPIC_API_KEY', '')
        if not model:
            model = 'claude-haiku-4-5-20251001'
    elif provider == 'groq':
        if not api_key:
            api_key = os.environ.get('GROQ_API_KEY', '')
        if not model:
            model = 'mixtral-8x7b-32768'
    elif provider == 'ollama':
        if not api_base:
            api_base = 'http://localhost:11434'
        if not model:
            model = 'mistral'
    elif provider == 'openai':
        if not api_key:
            api_key = os.environ.get('OPENAI_API_KEY', '')
        if not model:
            model = 'gpt-3.5-turbo'
    elif provider == 'deepseek':
        if not api_key:
            api_key = os.environ.get('DEEPSEEK_API_KEY', '')
        if not api_base:
            api_base = 'https://api.deepseek.com'
        if not model:
            # v4-pro, no el alias 'deepseek-chat': el alias puede cambiar de modelo destino
            # sin aviso y acá queremos el que se validó con la batería de 30 preguntas.
            model = 'deepseek-v4-pro'

    # Visión: Anthropic la tiene siempre; en el resto depende del modelo (gpt-4o sí,
    # gpt-3.5 no; llava sí, mistral no), así que se declara a mano con AGENTE_VISION.
    vision = provider == 'anthropic' or _es_verdadero(os.environ.get('AGENTE_VISION', ''))

    _config_cache = {
        'provider': provider,
        'model': model,
        'api_key': api_key,
        'api_base': api_base,
        'vision': vision
    }
    return _config_cache


def _es_verdadero(valor):
    return str(valor).strip().lower() in ('1', 'true', 'si', 'sí', 'yes', 'on')


# ============================================================================
# Lector de imágenes (config aparte de la del chat)
# ============================================================================
# La foto NO se le manda al agente: se lee en una llamada suelta, sin tools y con un
# prompt corto, y al chat le entra el resultado como texto. El motivo es el costo — el
# system prompt más TOOLS_SCHEMA son ~15.000 tokens que viajan en cada turno del agente,
# contra ~2.000 de la llamada del lector — y de paso el chat sigue en su proveedor de
# siempre, sin degradar el tool-calling ni obligar a que tenga visión.
#
# Default: el Flash-Lite de Gemini, por su tier gratuito. Se habla por el endpoint
# compatible con OpenAI, así que alcanza el paquete `openai` que ya es dependencia
# obligatoria, y cambiando las tres variables se apunta a OpenAI, Groq o un Ollama local
# sin tocar código.
#
# OJO AL ACTUALIZAR ESTE DEFAULT: Google saca de circulación los modelos viejos para las
# keys NUEVAS antes de apagarlos para las que ya los venían usando. `gemini-2.5-flash-lite`
# —el default hasta 2026-08-12— siguió andando acá mientras devolvía 404 "no longer
# available to new users" en cualquier instalación nueva. Y como `_leer_imagen` se traga
# toda excepción, eso se veía como "no se pudo leer la foto", nunca como un modelo muerto.
# Si una instalación nueva no lee fotos, lo primero a descartar es este string.

VISION_MODEL_DEFAULT = 'gemini-3.5-flash-lite'
VISION_API_BASE_DEFAULT = 'https://generativelanguage.googleapis.com/v1beta/openai/'

_vision_config_cache = False  # False = sin leer todavía; None = no hay lector configurado


def _get_vision_config():
    """Config del lector de imágenes, o None si no hay API key (= no hay lector)."""
    global _vision_config_cache
    if _vision_config_cache is not False:
        return _vision_config_cache

    api_key = (os.environ.get('AGENTE_VISION_API_KEY', '')
               or os.environ.get('GEMINI_API_KEY', ''))
    if not api_key:
        _vision_config_cache = None
        return None

    _vision_config_cache = {
        'model': os.environ.get('AGENTE_VISION_MODEL', '') or VISION_MODEL_DEFAULT,
        'api_key': api_key,
        'api_base': os.environ.get('AGENTE_VISION_API_BASE', '') or VISION_API_BASE_DEFAULT,
    }
    return _vision_config_cache


# ============================================================================
# Precios: tokens → dólares
# ============================================================================
# USD por MILLÓN de tokens. Se aplican AL MOSTRAR y el costo NO se guarda en la fila del
# registro: si un precio estaba mal o el proveedor lo cambia, corregirlo acá arregla también
# todo el histórico. Un modelo que no esté en la tabla muestra '—', nunca un número
# inventado — un costo mal calculado es peor que ninguno.
#
# `cache` es el precio de los tokens de entrada que llegaron cacheados (van descontados de
# `entrada`, no se suman aparte). `pico` es el multiplicador en horario pico; si el modelo
# no tiene esa distinción, no lleva la clave.
#
# Precios verificados el 2026-09-01 contra la página oficial de cada proveedor. Al tocar
# esta tabla, actualizar la fecha: es lo único que dice si el número sigue valiendo.
PRECIOS = {
    # api-docs.deepseek.com/quick_start/pricing
    'deepseek-v4-pro': {'entrada': 0.66, 'salida': 1.98, 'cache': 0.022, 'pico': 2.0},
    'deepseek-v4-flash': {'entrada': 0.22, 'salida': 0.66, 'cache': 0.007, 'pico': 2.0},
    # ai.google.dev/gemini-api/docs/pricing — el lector de fotos corre en el TIER GRATUITO,
    # así que en la práctica hoy no se paga. El precio del tier pago igual sirve: es lo que
    # costaría el día que el volumen se pase del free tier, que es justo lo que hay que ver
    # venir.
    'gemini-3.5-flash-lite': {'entrada': 0.30, 'salida': 2.50, 'cache': 0.30},
}

# Horario pico de DeepSeek: 01:00-04:00 y 06:00-10:00 UTC, de lunes a viernes; el resto
# vale la mitad. Las fechas del registro están en hora de la escuela (`config.ahora()`,
# Argentina UTC-3 sin horario de verano desde 2009), así que alcanza con sumarle 3 horas.
#
# En la práctica el turno mañana y el tarde caen enteros en off-peak (07:30 ART son las
# 10:30 UTC, justo después de que termina el pico) y sólo la última hora del turno noche
# entra en pico. Sale más caro de lo que parece a simple vista sólo esa franja.
_PICO_UTC_HORAS = frozenset((1, 2, 3, 6, 7, 8, 9))


def _es_pico(fecha):
    """¿Ese turno cayó en horario pico? `fecha` es 'YYYY-MM-DD HH:MM:SS' hora de escuela."""
    from datetime import datetime, timedelta
    try:
        utc = datetime.strptime(str(fecha)[:19], '%Y-%m-%d %H:%M:%S') + timedelta(hours=3)
    except (ValueError, TypeError):
        return False
    return utc.weekday() < 5 and utc.hour in _PICO_UTC_HORAS


def costo(modelo, entrada=0, salida=0, cache=0, pico=False):
    """USD de un consumo. None si no sabemos cuánto vale ese modelo.

    `cache` son tokens de entrada que ya venían cacheados: están DENTRO de `entrada` y acá
    se separan para cobrarlos a su precio, que en DeepSeek es 30 veces más barato. Sin esa
    resta, un turno con mucho contexto repetido se ve carísimo cuando en realidad es casi
    gratis, que es lo contrario de lo que el panel tiene que mostrar.

    `pico` viene guardado en la fila del turno (lo resuelve `_es_pico` cuando se registra),
    no se deduce acá: en un total agrupado ya no hay hora que mirar.
    """
    p = PRECIOS.get((modelo or '').strip())
    if not p:
        return None
    entrada, salida, cache = entrada or 0, salida or 0, cache or 0
    sin_cache = max(entrada - cache, 0)
    bruto = (sin_cache * p['entrada'] + cache * p['cache'] + salida * p['salida']) / 1_000_000
    return bruto * (p.get('pico', 1.0) if pico else 1.0)


# Variables globales por compatibilidad
def _get_agente_provider():
    return _get_config()['provider']

def _get_agente_model():
    return _get_config()['model']

def _get_agente_api_key():
    return _get_config()['api_key']

def _get_agente_api_base():
    return _get_config()['api_base']
