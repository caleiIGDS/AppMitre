# Configuración del Agente Conversacional

El asistente de `/gestion` es **agnóstico del LLM** — puede usar cualquier proveedor según tu preferencia y presupuesto.

## Proveedores soportados

### 1. **Anthropic (Claude)** — Recomendado, mejor calidad
```bash
# Instalar
pip install anthropic

# Configurar env vars
export AGENTE_PROVIDER=anthropic
export ANTHROPIC_API_KEY=sk-ant-...
export AGENTE_MODEL=claude-haiku-4-5-20251001  # (opcional, es el default)
```
**Ventajas**: mejor reasoning, multimodal (fotos), confiable  
**Desventajas**: requiere pago (pero Haiku es muy barato)  
**Costo estimado**: ~$0.001–$0.01 por mensaje típico

---

### 2. **Groq** — Gratis, muy rápido ⭐
```bash
# Instalar
pip install groq

# Configurar env vars
export AGENTE_PROVIDER=groq
export GROQ_API_KEY=gsk_...
export AGENTE_MODEL=mixtral-8x7b-32768  # (optional)
```
**Ventajas**: gratis, rapidísimo, sin tarjeta requerida, rate limits generosos  
**Desventajas**: menos inteligente que Claude, sin visión de fotos (aún)  
**Registro**: https://console.groq.com (instant API key)

---

### 3. **OpenAI** — GPT-3.5/GPT-4, pagado
```bash
# Instalar
pip install openai

# Configurar env vars
export AGENTE_PROVIDER=openai
export OPENAI_API_KEY=sk-...
export AGENTE_MODEL=gpt-3.5-turbo  # o gpt-4
```
**Ventajas**: familiar, GPT-4 disponible, buena calidad  
**Desventajas**: requiere pago, más caro que Claude Haiku  
**Costo estimado**: ~$0.002–$0.03 por mensaje

---

### 4. **Ollama** — Local, completamente gratis, sin API key 🚀
```bash
# 1. Descargar Ollama desde https://ollama.ai
# 2. Descargar modelo: ollama pull mistral (o neural-chat, openhermes, etc.)
# 3. Correr: ollama serve (deja corriendo en background)
# 4. Instalar cliente Python
pip install openai

# Configurar env vars
export AGENTE_PROVIDER=ollama
export AGENTE_MODEL=mistral  # (o neural-chat, openhermes, llama2)
export AGENTE_API_BASE=http://localhost:11434  # (optional, es el default)
```
**Ventajas**: gratis, offline, sin API key, no hay rate limits  
**Desventajas**: lento (depende de tu máquina), menos inteligente que Claude  
**Modelos recomendados**:
- `mistral` — rápido, buen balance
- `neural-chat` — optimizado para chat
- `openhermes` — reasoning mejor
- `llama2` — más capaz pero más lento (13B)

---

## Ejemplos de uso

### Usar Groq (recomendado gratis)
```bash
# Linux/Mac
export AGENTE_PROVIDER=groq
export GROQ_API_KEY=gsk_...
python app.py

# Windows PowerShell
$env:AGENTE_PROVIDER="groq"
$env:GROQ_API_KEY="gsk_..."
python app.py
```

### Usar Ollama local
```bash
# Terminal 1: iniciar Ollama
ollama serve

# Terminal 2: la app
export AGENTE_PROVIDER=ollama
export AGENTE_MODEL=mistral
python app.py
```

### Usar Claude (default)
```bash
export AGENTE_PROVIDER=anthropic
export ANTHROPIC_API_KEY=sk-ant-...
python app.py
```

---

## Variables de entorno

| Variable | Default | Descripción |
|---|---|---|
| `AGENTE_PROVIDER` | `anthropic` | Proveedor: `anthropic`, `groq`, `openai`, `ollama` |
| `AGENTE_MODEL` | Depende del provider (ver arriba) | Nombre del modelo |
| `AGENTE_API_KEY` | (vacío) | API key si el provider la requiere |
| `AGENTE_API_BASE` | Para Ollama: `http://localhost:11434` | URL base de la API (para APIs custom o Ollama) |

---

## Comparativa rápida

| Provider | Costo | Velocidad | Calidad | Fotos | Setup |
|---|---|---|---|---|---|
| **Anthropic** | 💰 Bajo | ⚡ Media | ⭐⭐⭐⭐⭐ | ✅ | API key |
| **Groq** | 💰 Gratis | ⚡⚡⚡ Rápido | ⭐⭐⭐ | ❌ | API key |
| **OpenAI** | 💰💰 Medio | ⚡ Media | ⭐⭐⭐⭐ | ✅ | API key |
| **Ollama** | 💰 Gratis | ⚡ Lento | ⭐⭐ | ❌ | Local setup |

---

## Troubleshooting

**Error: "Error: AGENTE_API_KEY ... no está configurada"**  
→ Falta la env var para el provider. Chequea el nombre (ej: `GROQ_API_KEY` para Groq, no `AGENTE_API_KEY`).

**Error: "Proveedor LLM desconocido: xyz"**  
→ `AGENTE_PROVIDER` tiene un valor inválido. Usa: `anthropic`, `groq`, `openai` u `ollama`.

**Ollama: "Error llamando al LLM: Connection refused"**  
→ Ollama no está corriendo. Ejecuta `ollama serve` en otra terminal.

**Groq: "Error: Could not verify API key"**  
→ La API key es inválida. Regenerala desde https://console.groq.com.

---

## Migrrar entre providers

Solo necesitas cambiar env vars. El código no cambia. El historial de mensajes y la auditoría siguen funcionando igual.

```bash
# Pasar de Claude a Groq
export AGENTE_PROVIDER=groq
export GROQ_API_KEY=gsk_...
# Reiniciar la app
```

---

## Para producción (Render.com, PythonAnywhere, etc.)

Setea las env vars en el dashboard del hosting:
- `AGENTE_PROVIDER=groq` (o tu proveedor)
- `GROQ_API_KEY=gsk_...` (o `ANTHROPIC_API_KEY`, etc. según el provider)
- `AGENTE_MODEL=mixtral-8x7b-32768` (opcional)

La app arrancará y usará el provider configurado automáticamente.
