# Procedimiento para Agregar Historias

**Responsable**: Usuario proporciona título + texto. Claude genera campos restantes.

## Flujo

### 1. Usuario proporciona
```
Título: "Miriam Cañamas: el multímetro fallado"
Texto: "Miriam Cañamas tiene fama de escuchar todo..."
```

### 2. Claude completa
- **id**: slug único, `guion_bajo`, de 2-3 palabras (ej: `guino_canamas`)
- **claves**: palabras-clave para búsqueda (5-10), sin acentos, en minúsculas
  - Incluye: nombre/tema principal, palabras que aparecen en el texto, sinónimos
  - Ejemplo: `["cañamas", "miriam", "multimetro", "fallado", "taller", "tercero"]`
- **tipo**: `historia` (dato institucional) o `guiño` (humor interno)
- **resumen**: una línea (~10 palabras) describiendo de qué trata
- **fecha**: año o período aproximado (ej: "2011", "mediados de 2010s", "principios de los 2000s")
  - **MUY IMPORTANTE**: aunque sea aproximada, determina el tono nostálgico. Una historia de 2005
    tiene resonancia emocional diferente a una de 2020. El usuario que pregunta "algo nostálgico"
    espera historias de hace años, no de hace meses.
  - Si no se sabe, usar "s/f" (sin fecha)
- **tono**: emoción al contar (nervioso, reflexivo, misterioso, conmocionado, nostálgico)
  - El tono se ancliza en la fecha: si es historia de hace 15 años + tono reflexivo → claramente nostálgico
- **estilo**: forma narrativa
  - Ejemplos: "primera persona, nervioso, como confesando un secreto"
  - "nostálgico, como recordando tu propia época"
  - "misterioso, como mostrando lugares que solo vos conocés"

### 3. Claude crea dos archivos

**A) `historias/{id}.json`**
```json
{
  "id": "guino_canamas",
  "titulo": "Miriam Cañamas: el multímetro fallado",
  "claves": ["cañamas", "miriam", "multimetro", "fallado", "taller"],
  "tipo": "guiño",
  "fecha": "2008",
  "resumen": "La anécdota de tercero que culpó al instrumento",
  "tono": "nervioso",
  "estilo": "primera persona, cómplice, como confesando",
  "texto": "[TEXTO COMPLETO, TEXTUAL DEL USUARIO]"
}
```

**B) Agrega entrada a `historia_indice.json`**
En el array `indice`, agregar:
```json
{
  "id": "guino_canamas",
  "titulo": "Miriam Cañamas: el multímetro fallado",
  "claves": ["cañamas", "miriam", "multimetro", "fallado", "taller"],
  "tipo": "guiño",
  "fecha": "2008",
  "resumen": "La anécdota de tercero que culpó al instrumento",
  "tono": "nervioso",
  "estilo": "primera persona, cómplice, como confesando"
}
```

### 4. Verificar
```bash
python -c "import json; json.load(open('historias/guino_canamas.json', encoding='utf-8'))" && echo "OK"
```

### 5. Commit
```bash
git add historias/guino_canamas.json historia_indice.json
git commit -m "Historia: Miriam Cañamas"
```

---

## Notas de diseño

### Claves
- **Tolerancia**: se busca sin acentos, sin mayúsculas, admite typos hasta 0.72 similitud
- **Cobertura**: incluir nombre, tema principal, palabras del texto, sinónimos comunes
- **Evitar**: palabras genéricas ("historia", "escuela") que macheen todo

### Tono y Fecha (crítico para nostalgia)
Elige según la narrativa, pero **ancla el tono en la fecha**:
- `reflexivo`: recordando, pensativo. Una historia de 2005 + reflexivo = profundamente nostálgico
- `nervioso`: incómodo, como confesando secreto, admiración incómoda
- `misterioso`: enigmático, como mostrando secretos, suspensivo
- `conmocionado`: admiración, sorpresa, emoción fuerte
- `nostálgico`: recordando tiempos pasados con cariño. Más poderoso si la fecha es lejana (15+ años)

**Ejemplo**: la historia de Kaypacha (2011) con tono "misterioso" = nostalgia por una época que se fue.
Sin la fecha, sería un misterio sin peso emocional. Con la fecha, es "ese misterio sin resolver de hace años".

### Estilo
Describe cómo Emilio cuenta la historia:
- Perspectiva: "primera persona" (testigo directo), "testigo presencial", "guardián de"
- Atmósfera: "íntimo", "dramático", "conversacional", "solemne"
- Relación con lo narrado: "como confesando", "como mostrando", "como revelando"
- Ejemplo completo: "primera persona, íntimo, como confesando un secreto en el pasillo"

### Tipo
- `historia`: hechos institucionales verificables (fundación, edificios, personas)
- `guiño`: anécdotas internas, humor, easter eggs (solo para gente de la escuela)

---

## Búsqueda

Cuando el usuario pregunta, la tool busca en:
1. **Claves** (substring exacto o difuso)
2. **Tono** (permite "algo misterioso" → matchea `tono: misterioso`)
3. **Estilo** (permite "íntimo" → matchea `estilo: "...íntimo..."`)

Si hay **1 match exacto/bueno**: devuelve directo con `instruccion_tono`.  
Si hay **varias**: lista opciones.  
Si **ninguna**: "no sé de eso".

---

## Archivo JSON: estructura completa

```json
{
  "id": "hist_ejemplo",                      // slug único, snake_case
  "titulo": "Título de la historia",         // público, aparece en listados
  "claves": [                                // búsqueda: 5-10 palabras
    "palabra1",
    "palabra2",
    "sinonimo",
    "nombre_persona"
  ],
  "tipo": "historia|guiño",                  // dato real vs humor
  "fecha": "2011",                           // año/período (muy importante para tono nostálgico)
  "resumen": "Una línea breve",              // ~10 palabras, qué trata
  "tono": "reflexivo|nervioso|misterioso|...", // emoción al contar
  "estilo": "primera persona, íntimo...",    // cómo cuenta Emilio
  "texto": "El texto completo de la historia. Puede tener varias líneas."
}
```

---

## Ejemplo: agregar una historia

**Usuario dice**: "Hay una anécdota sobre que una vez el taller se inundó. Fue en 2015, en febrero."

**Claude hace**:
1. Genera `id: "anecdota_inundacion_taller"` (o más corto: `hist_inundacion`)
2. Genera `claves: ["inundacion", "taller", "agua", "desastre", "accidente", "2015"]`
3. Propone `tipo: "historia"` (es un evento real)
4. Propone `fecha: "2015"` (precisión completa, pero también acepta "mediados de 2010s")
5. Propone `tono: "nervioso"` (un desastre es emocionante, pero hace años es nostálgico también)
6. Propone `estilo: "primera persona, dramático, como revelando un caos que ya pasó"` (lo vivió, lo recuerda)
7. Propone `resumen: "El día que el taller se inundó sin aviso"`
8. Crea `historias/hist_inundacion.json` con el texto + fecha
9. Actualiza `historia_indice.json` con la entrada + fecha
10. Commitea

Listo. El agente puede consultarla inmediatamente con `consultar_historia(tema='inundacion')`. Si alguien 
pregunta "algo nostálgico", la fecha 2015 ayuda a Emilio a contar con la emoción correcta: "hace años 
que pasó eso".