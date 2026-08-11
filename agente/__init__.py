"""Asistente conversacional con tool-calling (`/agente`).

Cuarta área de la app, al mismo nivel que horarios, `/gestion` e `/historia`, y la única
transversal: lee las tres y escribe en dos. Antes era un único `agente.py` de ~4.000
líneas; se abrió a paquete conservando el mismo blueprint y la misma superficie pública
(`bp` e `init_db`, que es todo lo que usa `app.py`).

Mapa del paquete:
    dominio.py      RAIZ del proyecto + qué módulo (gestion/historia) es dueño de cada slug
    proveedores.py  config del LLM del chat y del lector de imágenes (son independientes)
    db.py           tablas propias en gestion.db: auditoría, conversación, fotos pendientes
    padrones.py     los dos padrones de personas y el cruce entre ellos
    lore.py         la historia de la escuela contada por Emilio
    vision.py       el lector de etiquetas (una llamada suelta, sin tools)
    prompt.py       el system prompt
    llm.py          clientes por proveedor + los dos loops de tool-calling
    filtros.py      lo que se limpia de la respuesta antes de mostrarla y de guardarla
    rutas.py        los endpoints Flask
    tools/          lo que el agente sabe hacer (esquemas + ejecutores, juntos por área)

AGNÓSTICO DEL LLM — Proveedor por DEFECTO: DeepSeek (deepseek-v4-pro).
Soporta:
  - DeepSeek (DEFAULT) — env var: DEEPSEEK_API_KEY, AGENTE_MODEL (default: deepseek-v4-pro)
  - Anthropic (Claude) — env var: ANTHROPIC_API_KEY, AGENTE_MODEL (default: claude-haiku-4-5-20251001)
  - Groq (Mixtral, Llama 2) — env var: GROQ_API_KEY, AGENTE_MODEL (default: mixtral-8x7b-32768)
  - OpenAI (GPT-3.5, GPT-4) — env var: OPENAI_API_KEY, AGENTE_MODEL (default: gpt-3.5-turbo)
  - Ollama (local) — env var: AGENTE_API_BASE (default: http://localhost:11434), AGENTE_MODEL (default: mistral)

Anthropic usa su propio loop de tool-calling; el resto comparte `_loop_openai`
(API compatible con OpenAI). El default requiere el paquete `openai` instalado.

FOTOS — el lector de imágenes se configura APARTE del chat (ver `proveedores._get_vision_config`).
La foto no se le manda al agente: se lee en una llamada suelta, sin tools, y al chat le
entra el resultado como texto. Con eso el alta desde foto anda con cualquier provider,
incluido el default (DeepSeek no tiene visión), y una foto cuesta ~2.000 tokens en vez
de los ~15.000 que arrastra cada turno del agente.

Config general:
  - AGENTE_PROVIDER: 'deepseek' (default) | 'anthropic' | 'groq' | 'openai' | 'ollama'
  - AGENTE_API_KEY: para providers que la requieren (ignored para Ollama)
  - AGENTE_API_BASE: para APIs custom (Ollama, self-hosted)
  - AGENTE_MODEL: nombre del modelo (defaults por provider arriba)
  - AGENTE_VISION: '1' para declarar que el modelo del CHAT ve imágenes. Anthropic ya
    viene en 1; sirve para gpt-4o (openai) o llava (ollama), donde depende del modelo
    elegido y no del provider. Solo se usa si NO hay lector configurado.
  - AGENTE_VISION_API_KEY / _MODEL / _API_BASE: el lector de fotos (ver AGENTE_CONFIG.md)
"""
from flask import Blueprint

bp = Blueprint('agente', __name__, url_prefix='/agente')


# Al final: `rutas` hace `from . import bp`, así que `bp` tiene que existir antes.
# Importarlo es lo que registra los endpoints y el gate de acceso sobre el blueprint.
from . import rutas  # noqa: E402,F401
from .db import init_db  # noqa: E402,F401  — lo llama app.py al arrancar
