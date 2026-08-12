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

## Fotos: etiquetas y descripción (lector de imágenes)

Sacar una foto de la chapa de características es la forma más rápida de cargar algo al
inventario. **El lector se configura aparte del chat**: no hace falta que el proveedor del
chat tenga visión, y de hecho el default (DeepSeek) no la tiene.

```bash
export AGENTE_VISION_API_KEY=...   # API key de Google AI Studio
```

Con eso alcanza. La key se saca gratis y sin tarjeta en https://aistudio.google.com/apikey.
El formato varía según cómo la generes (las clásicas empiezan con `AIza`, las nuevas con
`AQ.`): las dos sirven, no uses el prefijo para decidir si una key es válida.

> ⚠️ **Si una instalación nueva no lee fotos, sospechá del MODELO antes que de la key.**
> Google saca de circulación los modelos viejos para las keys nuevas antes de apagarlos
> para las que ya los venían usando, y devuelve un 404 *"no longer available to new
> users"*. Pasó con `gemini-2.5-flash-lite`, que fue el default hasta el 2026-08-12.
> Fuera de producción el error del proveedor ahora se imprime por consola con el prefijo
> `[vision]`; en producción se sigue tragando (puede traer la key en el texto).

**Por qué va separado del chat**: la foto no se le manda al agente, se lee en una llamada
suelta sin tools y con un prompt corto, y al chat le entra el resultado como texto. El
system prompt más el esquema de tools son ~15.000 tokens que viajan en cada turno del
agente; la llamada del lector son ~2.000. Además el chat sigue en su proveedor de siempre,
sin cambiarle el modelo a las otras 20 tools.

**Solo mira cuando hace falta.** Una foto puede venir por tres motivos, y el asistente los
distingue:

| Le decís… | Qué hace | ¿Consume lectura? |
|---|---|---|
| "guardá esta foto en el taladro" | Busca el taladro y le pega la foto a la ficha | **No** |
| "cargá esto al inventario" | Lee la etiqueta y arma la ficha del recurso | Sí |
| "¿qué es esto?" / "¿en qué estado está?" | Describe el objeto: qué es, qué se ve, cuántos hay | Sí |
| (mandás la foto sin decir nada) | **Pregunta** cuál de las tres querés | No |

Adjuntar no cuesta nada porque para guardar una imagen no hace falta saber qué dice. Si no
tiene claro a qué recurso va, pregunta en vez de adivinar — una foto guardada en la ficha
equivocada no se puede sacar desde la app.

**Leer la etiqueta y describir el objeto son dos modos del mismo lector**, misma key y mismo
modelo: lo único que cambia es el prompt. El modo etiqueta transcribe lo que está escrito y es
el que alimenta las altas; el modo análisis describe lo que se ve y sirve para lo que no tiene
etiqueta legible. Los dos tienen prohibido completar con lo que el modelo sepa del producto.

> **Una descripción no da de alta nada.** De "parece una amoladora angular, sin daños
> visibles" no sale una ficha de inventario: no hay marca ni modelo confiables. Si querés
> cargarlo, el asistente te va a pedir una foto de la etiqueta o que le dictes los datos.
> El modo análisis contesta preguntas, no llena fichas.

**Costo**: el default es `gemini-3.5-flash-lite`, que **tiene tier gratuito** y a una
escuela le sobra. Pasado el tier gratuito son ~US$0,0014 por foto **mirada**, en cualquiera
de los dos modos — las que solo se adjuntan no cuentan. El asistente tiene prohibido llamar
al lector dos veces sobre la misma foto para probar los dos modos.

Referencia rápida, calculada sobre la llamada real del lector (~2.000 tokens de entrada,
~300 de salida). A 300 fotos por mes —un mes movido de inventario— la diferencia entre el
más barato y el más caro es de un café:

| Modelo | Entrada / Salida $/M | Por foto | 300 fotos |
|---|---|---|---|
| `gemini-3.5-flash-lite` (default) | 0,30 / 2,50 | US$0,00135 | US$0,40 |
| `gemini-3.1-flash-lite` | 0,25 / 1,50 | US$0,00095 | US$0,29 |
| `gemini-3.5-flash` | 1,50 / 9,00 | US$0,0057 | US$1,71 |

**El precio no es la variable a optimizar acá**: a este volumen todo es ruido. Lo que
decide es la calidad leyendo texto chico sobre metal sucio (ahí un modelo mejor evita una
carga mal hecha) y la privacidad del tier gratuito. Si las chapas feas se leen bien con el
default, no hay razón para subir.

> ⚠️ En el tier gratuito **Google usa las imágenes para mejorar sus productos**. Para chapas
> de amoladoras da igual; si en alguna foto pudiera salir un alumno, pasá a tier pago (misma
> key, agregando facturación) o cambiá de proveedor con las variables de abajo.

**Cambiar de proveedor de visión** — el lector habla el protocolo de OpenAI, así que sirve
cualquier API compatible:

```bash
# OpenAI (no entrena con tus datos, ~US$0,0014/foto)
export AGENTE_VISION_API_KEY=sk-...
export AGENTE_VISION_MODEL=gpt-5-mini
export AGENTE_VISION_API_BASE=https://api.openai.com/v1

# Ollama local con llava (gratis, necesita GPU decente)
export AGENTE_VISION_API_KEY=ollama
export AGENTE_VISION_MODEL=llava
export AGENTE_VISION_API_BASE=http://localhost:11434/v1
```

**Si el alta salió de una foto, la foto queda guardada** en la galería del recurso cuando el
usuario confirma con el botón. No hay que subirla aparte, ni pedirle al asistente que la
adjunte.

**Sin `AGENTE_VISION_API_KEY`**: si el proveedor del chat tiene visión propia
(`AGENTE_PROVIDER=anthropic`, o `AGENTE_VISION=1` con un modelo que la tenga) la foto se le
manda al agente como antes. Si no, el asistente avisa que no puede ver la foto y pide los
datos por texto — nunca inventa lo que "vio".

---

## Variables de entorno

| Variable | Default | Descripción |
|---|---|---|
| `AGENTE_PROVIDER` | `deepseek` | Proveedor del chat: `deepseek`, `anthropic`, `groq`, `openai`, `ollama` |
| `AGENTE_MODEL` | Depende del provider (ver arriba) | Nombre del modelo |
| `AGENTE_API_KEY` | (vacío) | API key si el provider la requiere |
| `AGENTE_API_BASE` | Para Ollama: `http://localhost:11434` | URL base de la API (para APIs custom o Ollama) |
| `AGENTE_VISION` | (vacío) | `1` para declarar que el modelo del **chat** ve imágenes (gpt-4o, llava). Anthropic ya viene en 1 |
| `AGENTE_VISION_API_KEY` | (vacío) | API key del **lector de fotos**. Sin esto no hay lectura de etiquetas ni descripción de fotos. Fallback: `GEMINI_API_KEY` |
| `AGENTE_VISION_MODEL` | `gemini-3.5-flash-lite` | Modelo del lector |
| `AGENTE_VISION_API_BASE` | `https://generativelanguage.googleapis.com/v1beta/openai/` | URL base del lector (cualquier API compatible con OpenAI) |

---

## Comparativa rápida

La columna **Fotos** es del chat en sí. Con `AGENTE_VISION_API_KEY` configurada, las fotos
andan con cualquier proveedor de la tabla, porque se leen aparte.

| Provider | Costo | Velocidad | Calidad | Fotos sin lector | Setup |
|---|---|---|---|---|---|
| **DeepSeek** (default) | 💰 Muy bajo | ⚡ Media | ⭐⭐⭐⭐ | ❌ | API key |
| **Anthropic** | 💰 Bajo | ⚡ Media | ⭐⭐⭐⭐⭐ | ✅ | API key |
| **Groq** | 💰 Gratis | ⚡⚡⚡ Rápido | ⭐⭐⭐ | ❌ | API key |
| **OpenAI** | 💰💰 Medio | ⚡ Media | ⭐⭐⭐⭐ | ✅ (gpt-4o) | API key |
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

**"📷 No puedo ver la foto: no tengo configurado un lector de imágenes"**  
→ Falta `AGENTE_VISION_API_KEY`. Ver la sección de fotos más arriba.

**El asistente dice que no pudo leer la foto**  
→ El lector está configurado pero la llamada falló. Casi siempre es el rate limit del tier
gratuito de Gemini (15 requests por minuto): esperá un momento y mandala de nuevo. Si pasa
siempre, la key puede estar vencida o el modelo de `AGENTE_VISION_MODEL` no existe.

**Adjunta la foto al recurso equivocado**  
→ No hay forma de borrar una foto de una galería desde la app. Se saca editando `gestion.db`
(la columna `fotos` de la tabla, que es un JSON). Para que no pase, el asistente tiene
instrucción de preguntar cuando no está seguro del destino: si igual se manda solo, decíselo
más explícito ("guardala en el taladro Makita del pañol").

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
