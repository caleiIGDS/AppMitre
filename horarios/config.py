# horarios/config.py
# Configuración del sistema de horarios.
#
# A propósito NO importa el `config.py` de la raíz: el paquete `horarios/` es un sistema
# aparte, sin dependencias de entrada del resto de la app (ver el plan de separación /
# dev-log/DECISIONS.md). Por eso las constantes compartidas (branding, DIAS, el reloj,
# PRODUCCION) están duplicadas acá — es el precio de la independencia.

import os
from datetime import datetime, timedelta, timezone

# ¿Estamos en el hosting? PythonAnywhere exporta PYTHONANYWHERE_DOMAIN en el entorno.
PRODUCCION = bool(os.environ.get('PYTHONANYWHERE_DOMAIN'))

# Zona horaria de la escuela. El servidor de producción corre en UTC; toda la app pide la
# hora por `ahora()`, nunca por `datetime.now()`.
ZONA_HORARIA = "America/Argentina/Buenos_Aires"
UTC_OFFSET_HORAS = -3   # fallback si el sistema no tiene la base de zonas horarias


def ahora():
    """La hora de pared de la escuela, como datetime naive.

    Naive a propósito: todo el código trabaja sin tzinfo. Argentina no aplica horario de
    verano desde 2009, así que el fallback de offset fijo es equivalente cuando falta
    `tzdata` (Windows sin el paquete).
    """
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(ZONA_HORARIA)
    except Exception:
        tz = timezone(timedelta(hours=UTC_OFFSET_HORAS))
    return datetime.now(tz).replace(tzinfo=None)


# Branding de la institución (copia local — ver el docstring de arriba).
ESCUELA_NOMBRE = "EMILIO MITRE"
ESCUELA_LOGO = "images/escudo.svg"
ESCUELA_VERSION = "V1.16"

# Días laborales (en orden, título case con acentos).
DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]

# ---------------------------------------------------------------------------
# Fuente de datos: Google Sheets vía el Web App de Apps Script
# ---------------------------------------------------------------------------

# ID del documento de Google Sheets (común para todas las hojas).
SHEET_ID = "1GJxwpxXfLosqKxgIa6zyZhwjDK-89ZDavLi6nouWTsw"

# El Drive de la escuela es privado: las planillas se bajan por un Web App de Apps Script
# que corre como el dueño y devuelve el mismo CSV. Cada request se firma con HMAC-SHA256
# sobre el timestamp en ms. Ver apps_script/.
APPSCRIPT_URL = os.environ.get('SHEETS_PROXY_URL', '')        # .../macros/s/AKfy.../exec
APPSCRIPT_SECRET = os.environ.get('SHEETS_PROXY_SECRET', '')  # = Script Property PROXY_SECRET

# Diccionario unificado de GIDs (IDs de las hojas individuales).
# Los números del 1 al 7 corresponden a los horarios de cada año escolar.
GIDS = {
    "1ro": "1041328323",
    "2do": "1960185081",
    "3ro": "576881307",
    "4to": "1940684424",
    "5to": "310218861",
    "6to": "618740516",
    "7mo": "15078021",
    "horarios_preceptores": "1249256665",
    "personal_no_docente": "1094234359",
}

# GIDs para la carga de horarios de clases (todos menos preceptores y personal).
GIDS_CURSOS = {k: v for k, v in GIDS.items() if k not in ["horarios_preceptores", "personal_no_docente"]}

GID_HORARIOS_PRECEPTORES = GIDS["horarios_preceptores"]
GID_PERSONAL_NO_DOCENTE = GIDS["personal_no_docente"]

# ---------------------------------------------------------------------------
# Mapeos del edificio y de los cursos
# ---------------------------------------------------------------------------

# Mapeo de pisos a aulas para la Planilla General.
FLOOR_MAPPING = {
    "Piso 1": ["11", "12", "13", "14", "15", "16"],
    "Piso 2": ["21", "22", "23", "24", "25", "26"],
    "Piso 3": ["31", "32", "33", "35", "36"],
    "Entrepiso 1": ["101", "102", "103", "104", "105", "106", "107", "108"],
    "Entrepiso 2": ["201", "202", "203"],
    "Entrepiso 3": ["301", "302", "303", "304", "305", "306"],
    "Electricidad": ["T106", "T107", "T108", "T109", "T110", "T111", "T112", "T113", "T114"],
    "Talleres": ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9", "T10", "T11", "T12", "T13", "T14", "T15", "T16", "T17", "T18", "T24", "T25", "T26", "T27", "T101", "T102", "T103", "T104", "T105", "T115", "T116"],
}

# Turno por defecto para todos los cursos cuando no hay datos en la DB.
TURNO_DEFAULT = "MAÑANA"

# Turno por curso/división — clave: (str(curso), str(division)) tal como viene de la DB.
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

# Especialidad por curso/división — clave: (str(curso), str(division)).
# CICLO BÁSICO: 1ro–3ro; luego especialidades según la carrera.
ESPECIALIDAD_CURSOS = {
    # 1° Año — CICLO BÁSICO
    ("1", "A"): "CICLO BÁSICO",
    ("1", "B"): "CICLO BÁSICO",
    ("1", "C"): "CICLO BÁSICO",
    ("1", "D"): "CICLO BÁSICO",
    ("1", "E"): "CICLO BÁSICO",
    ("1", "F"): "CICLO BÁSICO",
    ("1", "G"): "CICLO BÁSICO",
    ("1", "H"): "CICLO BÁSICO",
    ("1", "I"): "CICLO BÁSICO",
    ("1", "J"): "CICLO BÁSICO",
    ("1", "K"): "CICLO BÁSICO",
    # 2° Año — CICLO BÁSICO
    ("2", "A"): "CICLO BÁSICO",
    ("2", "B"): "CICLO BÁSICO",
    ("2", "C"): "CICLO BÁSICO",
    ("2", "D"): "CICLO BÁSICO",
    ("2", "E"): "CICLO BÁSICO",
    ("2", "F"): "CICLO BÁSICO",
    ("2", "G"): "CICLO BÁSICO",
    ("2", "H"): "CICLO BÁSICO",
    ("2", "I"): "CICLO BÁSICO",
    ("2", "J"): "CICLO BÁSICO",
    # 3° Año — CICLO BÁSICO
    ("3", "A"): "CICLO BÁSICO",
    ("3", "B"): "CICLO BÁSICO",
    ("3", "C"): "CICLO BÁSICO",
    ("3", "D"): "CICLO BÁSICO",
    ("3", "E"): "CICLO BÁSICO",
    ("3", "F"): "CICLO BÁSICO",
    ("3", "G"): "CICLO BÁSICO",
    ("3", "H"): "CICLO BÁSICO",
    ("3", "I"): "CICLO BÁSICO",
    ("3", "K"): "CICLO BÁSICO",
    # 4° Año
    ("4", "1"): "ELECTROMECÁNICA",
    ("4", "2"): "ELECTROMECÁNICA",
    ("4", "3"): "ELECTROMECÁNICA",
    ("4", "4"): "ELECTROMECÁNICA",
    ("4", "5"): "ELECTROMECÁNICA",
    ("4", "6"): "ELECTROMECÁNICA",
    ("4", "7"): "ELECTROMECÁNICA",
    ("4", "8"): "ENERGÍAS RENOVABLES",
    ("4", "9"): "ENERGÍAS RENOVABLES",
    # 5° Año
    ("5", "1"): "MAESTRO MAYOR DE OBRA",
    ("5", "2"): "MAESTRO MAYOR DE OBRA",
    ("5", "3"): "MAESTRO MAYOR DE OBRA",
    ("5", "4"): "MAESTRO MAYOR DE OBRA",
    ("5", "5"): "ENERGÍAS RENOVABLES",
    ("5", "6"): "MAESTRO MAYOR DE OBRA",
    ("5", "7"): "MAESTRO MAYOR DE OBRA",
    ("5", "8"): "ENERGÍAS RENOVABLES",
    # 6° Año
    ("6", "1"): "MAESTRO MAYOR DE OBRA",
    ("6", "2"): "MAESTRO MAYOR DE OBRA",
    ("6", "3"): "MAESTRO MAYOR DE OBRA",
    ("6", "4"): "MAESTRO MAYOR DE OBRA",
    ("6", "5"): "ENERGÍAS RENOVABLES",
    ("6", "6"): "MAESTRO MAYOR DE OBRA",
    ("6", "7"): "MAESTRO MAYOR DE OBRA",
    ("6", "8"): "ENERGÍAS RENOVABLES",
    # 7° Año
    ("7", "1"): "MAESTRO MAYOR DE OBRA",
    ("7", "2"): "MAESTRO MAYOR DE OBRA",
    ("7", "3"): "MAESTRO MAYOR DE OBRA",
    ("7", "4"): "ENERGÍAS RENOVABLES",
    ("7", "5"): "MAESTRO MAYOR DE OBRA",
    ("7", "6"): "ENERGÍAS RENOVABLES",
}
