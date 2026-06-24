# config.py
# Configuración centralizada de AppMitre

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
    
    # Hoja de horarios detallados de Preceptores
    "horarios_preceptores": "576226512",

    # Hoja de horarios de Personal No Docente
    "personal_no_docente": "1094234359"
}

# Selección de GIDs específicos para la carga de horarios de clases
GIDS_CURSOS = {k: v for k, v in GIDS.items() if k not in ["horarios_preceptores", "personal_no_docente"]}

# GID específico para los horarios de preceptores
GID_HORARIOS_PRECEPTORES = GIDS["horarios_preceptores"]

# GID específico para el personal no docente
GID_PERSONAL_NO_DOCENTE = GIDS["personal_no_docente"]

# Branding de la institución
ESCUELA_NOMBRE = "EMILIO MITRE"
ESCUELA_LOGO = "images/logoMitre.jpg"
ESCUELA_VERSION = "V1.16"

# Días laborales (en orden, título case con acentos)
DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]

# Mapeo de pisos a aulas para la Planilla General
FLOOR_MAPPING = {
    "Piso 1": ["11", "12", "13", "14", "15", "16"],
    "Piso 2": ["21", "22", "23", "24", "25", "26"],
    "Piso 3": ["13", "14", "15", "16", "17", "18"],
    "Entrepiso 1": ["101","102", "103", "104", "105", "106", "107", "108"],
    "Entrepiso 2": ["201", "202"],
    "Entrepiso 3": ["301", "302", "303", "304", "305", "306"],
    "Talleres": ["T1","T2","T3","T4","T5","T6","T7","T8","T9","T10","T11","T12","T13","T14","T15","T16","T17","T18","T24","T25","T26","T27","T101","T102","T103","T104","T105","T106","T107","T108","T109","T110","T111","T112","T113","T114","T115","T116"]
}
