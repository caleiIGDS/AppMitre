import re
import unicodedata

def eliminar_acentos(texto):
    if not texto: return ""
    return "".join(c for c in unicodedata.normalize('NFD', texto)
                  if unicodedata.category(c) != 'Mn')

def limpiar_aula(aula):
    if not aula: return ""
    aula_limpia = eliminar_acentos(aula).upper().strip()
    
    # Mapeos específicos
    if aula_limpia == 'P':
        return 'PATIO'
    
    # Detectar si es un Taller (ej: "T1", "T 1", "TALLER 1")
    es_taller = bool(re.search(r'\b(TALLER|T)\s*\d+', aula_limpia))
    
    numeros = re.findall(r'\d+', aula_limpia)
    if numeros:
        numero_aula = "".join(numeros)
        if es_taller:
            return f"T{numero_aula}"
        return numero_aula
        
    # Si no tiene números, mantenemos el nombre limpio (ej: "PATIO")
    return aula_limpia

# Test cases
tests = [
    ("AULA 1", "1"),
    ("B 2", "2"),
    ("T1", "T1"),
    ("T 2", "T2"),
    ("TALLER 3", "T3"),
    ("PATIO", "PATIO"),
    ("SUM", "SUM"),
    ("P", "PATIO"),
    ("p ", "PATIO"),
    ("Aula T1", "T1"), # Should probably be T1
    ("Laboratorio 1", "1"), # As per user choice, only 'T' for talleres
]

for input_aula, expected in tests:
    result = limpiar_aula(input_aula)
    status = "PASS" if result == expected else f"FAIL (got {result})"
    print(f"'{input_aula}' -> '{result}' : {status}")
