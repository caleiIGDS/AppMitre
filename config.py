# config.py
# Configuración centralizada de Google Sheets para AppMitre

# ID del documento de Google Sheets (común para todas las hojas)
SHEET_ID = "1GJxwpxXfLosqKxgIa6zyZhwjDK-89ZDavLi6nouWTsw"

# Diccionario unificado de GIDs (IDs de las hojas individuales)
# Los números del 1 al 7 corresponden a los horarios de cada año escolar.
GIDS = {
    # Horarios por Año (1ro a 7mo)
    1: "1041328323",
    2: "1960185081",
    3: "576881307",
    4: "1940684424",
    5: "310218861",
    6: "618740516",
    7: "15078021",
    
    # Hoja de datos de Preceptores
    "preceptores": "813054425"
}

# Selección de GIDs específicos para la carga de horarios de clases
GIDS_CURSOS = {k: v for k, v in GIDS.items() if isinstance(k, int)}

# GID específico para preceptores
GID_PRECEPTORES = GIDS["preceptores"]
