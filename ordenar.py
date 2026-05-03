import pandas as pd
from difflib import get_close_matches

# 1. Definimos la lista de materias técnicas
MATERIAS_TECNICAS = [
    "Sistemas Tecnologicos", "Lenguaje Tecnologico", "Procedimientos Tecnicos",
    "MAQ. ELEC. Y AUTOMAT", "DIBUJO TECNOLOGICO", 
    "PROY., DISEÑO E INST. DE ENERGIAS RENOV.", "INTROD. A LA ELECTR. Y MEDIC",
    "TECNOLOGIA DE LAS ENERG. RENOV.", "DOCUMENTACION TECNICA", "PROYECTO",
    "CONTROLES Y AUTOMATISMOS", "ELECTROTEC. Y MAQ. ELEC."
]

def limpiar_y_asignar_grupo(archivo_input, archivo_output):
    try:
        # Cargamos el dataframe
        df = pd.read_csv(archivo_input)
        
        # Normalizamos la lista de referencia a mayúsculas para comparar mejor
        objetivos = [m.upper().strip() for m in MATERIAS_TECNICAS]

        def es_materia_tecnica(valor_celda):
            if pd.isna(valor_celda):
                return False
            
            # Limpiamos el texto de la celda (Mayúsculas y sin espacios extra)
            texto = str(valor_celda).upper().strip()
            
            # Caso 1: Coincidencia exacta
            if texto in objetivos:
                return True
            
            # Caso 2: Manejo de errores de tipeo (Fuzzy match)
            # cutoff 0.75 permite un margen de error razonable
            coincidencias = get_close_matches(texto, objetivos, n=1, cutoff=0.75)
            if coincidencias:
                return True
                
            return False

        # Aplicamos la lógica: si es técnica, ponemos 'A'. 
        # Si no, conservamos el valor que ya tenía la columna 'grupo'
        df['grupo'] = df.apply(
            lambda row: 'A' if es_materia_tecnica(row['materia']) else row['grupo'], 
            axis=1
        )

        # Guardamos el resultado
        df.to_csv(archivo_output, index=False)
        print(f"✅ Proceso exitoso. Archivo guardado como: {archivo_output}")
        
    except FileNotFoundError:
        print("❌ Error: No se encontró el archivo 'datos.csv'.")
    except Exception as e:
        print(f"❌ Ocurrió un error: {e}")

# --- EJECUCIÓN ---
# Cambia 'datos.csv' por el nombre real de tu archivo
limpiar_y_asignar_grupo('datos.csv', 'horarios_actualizados.csv')