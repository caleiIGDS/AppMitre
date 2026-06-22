# config.py
# Configuración centralizada de Google Sheets para AppMitre

# ID del documento de Google Sheets (común para todas las hojas)
SHEET_ID = "1GJxwpxXfLosqKxgIa6zyZhwjDK-89ZDavLi6nouWTsw"

# Diccionario unificado de GIDs (IDs de las hojas individuales)
# Los números del 1 al 7 corresponden a los horarios de cada año escolar.
GIDS = {
    # Horarios por Año (1ro a 7mo)
    "1ro": "1041328323",
    "2do": "1960185081",
    "3ro": "576881307",
    "4to": "1940684424",
    "5to": "310218861",
    "6to": "618740516",
    "7mo": "15078021",
    
    # Hoja de datos de Preceptores (Asignación de cursos)
    "preceptores": "813054425",
    
    # Hoja de horarios detallados de Preceptores
    "horarios_preceptores": "576226512",

    # Hoja de horarios de Personal No Docente
    "personal_no_docente": "1094234359"
}

# Selección de GIDs específicos para la carga de horarios de clases
GIDS_CURSOS = {k: v for k, v in GIDS.items() if k not in ["preceptores", "horarios_preceptores", "personal_no_docente"]}

# GID específico para preceptores
GID_PRECEPTORES = GIDS["preceptores"]

# GID específico para los horarios de preceptores
GID_HORARIOS_PRECEPTORES = GIDS["horarios_preceptores"]

# GID específico para el personal no docente
GID_PERSONAL_NO_DOCENTE = GIDS["personal_no_docente"]
