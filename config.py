# config.py
# Configuración centralizada de AppMitre

from datetime import datetime, timedelta, timezone

# Zona horaria de la escuela. El servidor de producción (Render) corre en UTC, así que
# `datetime.now()` a secas daba la hora 3 horas adelantada: el agente contestaba "ahora
# son las 21:40" a las 18:40, y lo mismo se guardaba en préstamos y fechas de revisión.
# Toda la app pide la hora por `ahora()`, nunca por `datetime.now()`.
ZONA_HORARIA = "America/Argentina/Buenos_Aires"
UTC_OFFSET_HORAS = -3   # fallback si el sistema no tiene la base de zonas horarias


def ahora():
    """La hora de pared de la escuela, como datetime naive.

    Naive a propósito: todo el código (formatos, comparaciones con horas de la DB) trabaja
    sin tzinfo, y devolver un datetime consciente rompería las restas contra fechas
    guardadas. Argentina no aplica horario de verano desde 2009, por eso el fallback de
    offset fijo es equivalente cuando falta `tzdata` (Windows sin el paquete instalado).
    """
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(ZONA_HORARIA)
    except Exception:
        tz = timezone(timedelta(hours=UTC_OFFSET_HORAS))
    return datetime.now(tz).replace(tzinfo=None)

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
    "horarios_preceptores": "1249256665",

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
ESCUELA_LOGO = "images/escudo.svg"
ESCUELA_VERSION = "V1.16"

# Días laborales (en orden, título case con acentos)
DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]

# Mapeo de pisos a aulas para la Planilla General
FLOOR_MAPPING = {
    "Piso 1": ["11", "12", "13", "14", "15", "16"],
    "Piso 2": ["21", "22", "23", "24", "25", "26"],
    "Piso 3": ["31", "32", "33", "35", "36"],
    "Entrepiso 1": ["101","102", "103", "104", "105", "106", "107", "108"],
    "Entrepiso 2": ["201", "202","203"],
    "Entrepiso 3": ["301", "302", "303", "304", "305", "306"],
    "Electricidad": ["T106", "T107", "T108", "T109", "T110", "T111", "T112", "T113", "T114"],
    "Talleres": ["T1","T2","T3","T4","T5","T6","T7","T8","T9","T10","T11","T12","T13","T14","T15","T16","T17","T18","T24","T25","T26","T27","T101","T102","T103","T104","T105","T115","T116"]
}

# Turno por defecto para todos los cursos cuando no hay datos en la DB
TURNO_DEFAULT = "MAÑANA"

# Turno por curso/división — clave: (str(curso), str(division)) tal como viene de la DB
# Valores posibles: "MAÑANA" | "TARDE" | "VESPERTINO"
TURNO_CURSOS = {
    # 1° Año
    ("1", "A"): "MAÑANA",
    ("1", "B"): "MAÑANA",
    ("1", "C"): "MAÑANA",
    ("1", "D"): "MAÑANA",
    ("1", "E"): "TARDE",
    ("1", "F"): "TARDE",
    ("1", "G"): "TARDE",
    ("1", "H"): "TARDE",
    ("1", "I"): "MAÑANA",
    ("1", "J"): "MAÑANA",
    ("1", "K"): "TARDE",
    # 2° Año
    ("2", "A"): "MAÑANA",
    ("2", "B"): "MAÑANA",
    ("2", "C"): "MAÑANA",
    ("2", "D"): "MAÑANA",
    ("2", "E"): "TARDE",
    ("2", "F"): "TARDE",
    ("2", "G"): "TARDE",
    ("2", "H"): "TARDE",
    ("2", "I"): "MAÑANA",
    ("2", "J"): "MAÑANA",
    # 3° Año
    ("3", "A"): "MAÑANA",
    ("3", "B"): "MAÑANA",
    ("3", "C"): "TARDE",
    ("3", "D"): "TARDE",
    ("3", "E"): "TARDE",
    ("3", "F"): "MAÑANA",
    ("3", "G"): "MAÑANA",
    ("3", "H"): "MAÑANA",
    ("3", "I"): "MAÑANA",
    ("3", "K"): "TARDE",
    # 4° Año
    ("4", "1"): "MAÑANA",
    ("4", "2"): "MAÑANA",
    ("4", "3"): "TARDE",
    ("4", "4"): "MAÑANA",
    ("4", "5"): "MAÑANA",
    ("4", "6"): "TARDE",
    ("4", "7"): "TARDE",
    ("4", "8"): "TARDE",
    ("4", "9"): "TARDE",
    # 5° Año
    ("5", "1"): "MAÑANA",
    ("5", "2"): "TARDE",
    ("5", "3"): "MAÑANA",
    ("5", "4"): "TARDE",
    ("5", "5"): "TARDE",
    ("5", "6"): "TARDE",
    ("5", "7"): "TARDE",
    ("5", "8"): "TARDE",
    # 6° Año
    ("6", "1"): "TARDE",
    ("6", "2"): "TARDE",
    ("6", "3"): "TARDE",
    ("6", "4"): "VESPERTINO",
    ("6", "5"): "VESPERTINO",
    ("6", "6"): "VESPERTINO",
    ("6", "7"): "VESPERTINO",
    ("6", "8"): "VESPERTINO",
    # 7° Año
    ("7", "1"): "VESPERTINO",
    ("7", "2"): "VESPERTINO",
    ("7", "3"): "VESPERTINO",
    ("7", "4"): "VESPERTINO",
    ("7", "5"): "VESPERTINO",
    ("7", "6"): "VESPERTINO",
}
