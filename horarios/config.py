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

# Dónde vive `escuela.db`: la carpeta de bases del proyecto, que es una sola para todas las
# áreas (ver `database/LEEME.md`). Es lo ÚNICO del paquete que sale de `horarios/`, y es una
# ruta, no un import: la config de la raíz sigue sin tocarse desde acá.
DIR_DATOS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'database')

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
    ("4", "5"): "MAESTRO MAYOR DE OBRA",
    ("4", "6"): "MAESTRO MAYOR DE OBRA",
    ("4", "7"): "MAESTRO MAYOR DE OBRA",
    ("4", "8"): "ENERGÍAS RENOVABLES",
    ("4", "9"): "ENERGÍAS RENOVABLES",
    # 5° Año
    ("5", "1"): "ELECTROMECÁNICA",
    ("5", "2"): "ELECTROMECÁNICA",
    ("5", "3"): "MAESTRO MAYOR DE OBRA",
    ("5", "4"): "MAESTRO MAYOR DE OBRA",
    ("5", "5"): "ENERGÍAS RENOVABLES",
    ("5", "6"): "ELECTROMECÁNICA",
    ("5", "7"): "MAESTRO MAYOR DE OBRA",
    ("5", "8"): "ENERGÍAS RENOVABLES",
    # 6° Año
    ("6", "1"): "ELECTROMECÁNICA",
    ("6", "2"): "ELECTROMECÁNICA",
    ("6", "3"): "MAESTRO MAYOR DE OBRA",
    ("6", "4"): "MAESTRO MAYOR DE OBRA",
    ("6", "5"): "ENERGÍAS RENOVABLES",
    ("6", "6"): "ELECTROMECÁNICA",
    ("6", "7"): "MAESTRO MAYOR DE OBRA",
    ("6", "8"): "ENERGÍAS RENOVABLES",
    # 7° Año
    ("7", "1"): "ELECTROMECÁNICA",
    ("7", "2"): "MAESTRO MAYOR DE OBRA",
    ("7", "3"): "ELECTROMECÁNICA",
    ("7", "4"): "ENERGÍAS RENOVABLES",
    ("7", "5"): "MAESTRO MAYOR DE OBRA",
    ("7", "6"): "ENERGÍAS RENOVABLES",
}

# Tipo y código de cada materia, por año y especialidad. Sale de los planes de estudio
# (Res. 88/09 ciclo básico, Res. 3828/09 MMO y Electromecánica, Res. 284/12 Energías Renovables)
# y cambia cada muchos años, así que va fijo acá y no en la planilla.
# Clave: la materia como la escribe la planilla (mayúsculas, sin acentos). Si la planilla la
# escribe de varias formas, va una línea por forma. Valor: (código del nomenclador, tipo).
# Código vacío = no lo encontramos en el nomenclador (no hace falta para filtrar).
# «¿tipo?» = tipo a confirmar contra el plan.
TEO, CT, TE = "TEÓRICA", "CIENTÍFICO-TECNOLÓGICA", "TÉCNICO-ESPECÍFICA"
MATERIAS_PLAN = {
    ("1", "CICLO BÁSICO"): {
        "CIENCIAS NATURALES": ("CNT", TEO),
        "CIENCIAS SOCIALES": ("CSC", TEO),
        "CIENCIAS SOCIALES (GEO)": ("GGF", TEO),  # Ciencias Sociales (Geografía)
        "CIENCIAS SOCIALES (HIS)": ("HTR", TEO),  # Ciencias Sociales (Historia)
        "CONSTRUCCION CIUDADANA": ("CCD", TEO),  # Construcción de Ciudadanía
        "CONSTRUCCION CIUDADANIA": ("CCD", TEO),
        "CONSTRUCCION DE CIUDADANIA": ("CCD", TEO),
        "EDUCACION ARTISTICA": ("", TEO),  # sin código
        "EDUCACION FISICA": ("EFC", TEO),
        "INGLES": ("IGS", TEO),
        "MATEMATICA": ("MTM", TEO),
        "PRACTICAS DEL LENGUAJE": ("PLG", TEO),
        "LENGUAJE TECNOLOGICO": ("LTS", TE),  # Lenguajes Tecnológicos (1° año)
        "PROCEDIMIENTOS TECNICOS": ("PCT", TE),  # Procedimientos Técnicos (1° año)
        "SISTEMAS TECNOLOGICOS": ("STS", TE),  # Sistemas Tecnológicos (1° año)
    },
    ("2", "CICLO BÁSICO"): {
        "CIENCIAS NATURALES": ("CNT", TEO),
        "CIECIAS NATURALE (BIOLOGIA)": ("BLG", TEO),  # Ciencias Naturales (Biología)
        "CIENCIAS NATURALES (BIOLOGIA)": ("BLG", TEO),
        "CIENCIAS NATURALES (FISICOQUIMICA)": ("FQA", TEO),
        "CIENCIAS SOCIALES (GEOGRAFIA)": ("GGF", TEO),
        "CIENCIAS SOCIALES (HISTORIA)": ("HTR", TEO),
        "CONSTRUCC. DE CIUDADANIA": ("CCD", TEO),  # Construcción de Ciudadanía
        "CONSTRUCCION DE CIUDADANIA": ("CCD", TEO),
        "COSTRUCCION DE CIUDADANIA": ("CCD", TEO),
        "EDUCACION ARTISTICA": ("", TEO),  # sin código
        "EDUCACION  FISICA": ("EFC", TEO),  # Educación Física
        "EDUCACION FISICA": ("EFC", TEO),
        "INGLES": ("IGS", TEO),
        "MATEMATICA": ("MTM", TEO),
        "PRACTICAS DEL LENGUAJE": ("PLG", TEO),
        "LEGUAJE TECNOLOGICO": ("LTE", TE),  # Lenguajes Tecnológicos (2° año)
        "LENGUAJE TECNOLOG.": ("LTE", TE),
        "LENGUAJE TECNOLOGICO": ("LTE", TE),
        "LENGUAJE TECNOLOGICOS": ("LTE", TE),
        "LENGUAJES TECNOLOGIC": ("LTE", TE),
        "PROCEDIMIENTOS TECNICOS": ("PCE", TE),  # Procedimientos Técnicos (2° año)
        "SISTEMAS TECNOLOGIC": ("ST2", TE),  # Sistemas Tecnológicos (2° año)
        "SISTEMAS TECNOLOGICOS": ("ST2", TE),
    },
    ("3", "CICLO BÁSICO"): {
        "BIOLOGIA": ("BLG", TEO),  # Ciencias Naturales (Biología)
        "FISICO QUIMICA": ("FQA", TEO),  # Ciencias Naturales (Fisicoquímica)
        "FISICOQUIMICA": ("FQA", TEO),
        "GEOGRAFIA": ("GGF", TEO),  # Ciencias Sociales (Geografía)
        "HISTORIA": ("HTR", TEO),  # Ciencias Sociales (Historia)
        "CONSTRUCCION DE CIUDADANIA": ("CCD", TEO),
        "CONSTRUCCION DE LA CIUDADANIA": ("CCD", TEO),
        "EDUCACION ARTISTICA": ("", TEO),  # sin código
        "EDUCACION FISICA": ("EFC", TEO),
        "INGLES": ("IGS", TEO),
        "MATEMATICA": ("MTM", TEO),
        "MATEMATICAS": ("MTM", TEO),
        "PRACTICAS DEL LENGUAJE": ("PLG", TEO),
        "LENGUAGE TECNOLOGICO": ("LT1", TE),  # Lenguajes Tecnológicos (3° año)
        "LENGUAJE TECNOLOGICO": ("LT1", TE),
        "PROCED TECNOLOGICO": ("PCS", TE),  # Procedimientos Técnicos (3° año)
        "PROCEDIMIENTOS TECNICOS": ("PCS", TE),
        "SISTEMAS TECNOLOGICOS": ("ST1", TE),  # Sistemas Tecnológicos (3° año)
        "SISTEMAS TENCOLOGICOS": ("ST1", TE),
    },
    ("4", "ELECTROMECÁNICA"): {
        "EDUCACION FISICA": ("EFC", TEO),
        "EDUCACION FISICA DOMINGUEZ, ANDREA": ("EFC", TEO),
        "GEOGRAFIA": ("GGF", TEO),
        "HISTORIA": ("HTR", TEO),
        "INGLES": ("IGS", TEO),
        "LITERATURA": ("LIT", TEO),
        "SALUD Y ADOLESCENCIA": ("SYA", TEO),
        "CONOCIMIENTO DE LOS MATERIALES": ("CME", CT),
        "FISICA": ("FIS", CT),
        "MATEMATICA CICLO SUP.": ("MCS", CT),  # Matemática - Ciclo Superior
        "MATEMATICA CICLO SUPERIOR": ("MCS", CT),
        "QUIMICA": ("QMC", CT),
        "DIBUJO TECNOLOGICO": ("DTE", TE),
        "DISENO Y PROC. MEC.": ("PRM", TE),  # Diseño y Procesamiento Mecánico
        "DISENO Y PROCESAMIENTO MECANICO": ("PRM", TE),
        "INST. Y AP. DE LA ENERG.": ("APE", TE),  # Instalaciones y Aplicaciones de la Energía
        "INSTALACION Y APLICACION DE LA ENERGIA": ("APE", TE),
        "MAQ. ELEC. Y AUTOMAT": ("MEA", TE),  # Máquinas Eléctricas y Automatismos
        "MAQUINAS ELECTRICAS Y AUTOMATISMOS": ("MEA", TE),
    },
    ("4", "MAESTRO MAYOR DE OBRA"): {
        "EDUCACION FISICA": ("EFC", TEO),
        "GEOGRAFIA": ("GGF", TEO),
        "HISTORIA": ("HTR", TEO),
        "INGLES": ("IGS", TEO),
        "LITERATURA": ("LIT", TEO),
        "SALUD Y ADOLESCENCIA": ("SYA", TEO),
        "CONOCIM. DE LOS MATERIALES": ("CMM", CT),  # Conocimiento de los Materiales
        "CONOCIMIENTO DE LOS MATERIALES": ("CMM", CT),
        "FISICA": ("FIS", CT),
        "MATEMATICA CICLO SUPERIOR": ("MCS", CT),  # Matemática - Ciclo Superior
        "QUIMICA": ("QMC", CT),
        "DIBUJO TEC.": ("DTM", TE),  # Dibujo Tecnológico
        "DIBUJO TECNOL.": ("DTM", TE),
        "DIBUJO TECNOLOGICO": ("DTM", TE),
        "INT. DE ANTEPR.": ("IAN", TE),  # Interpretación de Anteproyectos
        "INTERP. DE ANTEPR.": ("IAN", TE),
        "INTERP. DE ANTEPROYEC.": ("IAN", TE),
        "INTERPRET. DE ANTEPROY.": ("IAN", TE),
        "INTERPRET. DE ANTEPROYECTO": ("IAN", TE),
        "PLANIFIC. DE OBRA": ("POB", TE),  # Planificación de Obra
        "PROYECTO": ("ORP", TE),
        "SIST. CONSTRUC.": ("SCO", TE),  # Sistemas Constructivos
        "SISTEMAS CONSTRUCT.": ("SCO", TE),
        "SISTEMAS CONSTRUCTIVOS": ("SCO", TE),
    },
    ("4", "ENERGÍAS RENOVABLES"): {
        "EDUCACION FISICA": ("EFC", TEO),
        "GEOGRAFIA": ("GGF", TEO),
        "HISTORIA": ("HTR", TEO),
        "INGLES": ("IGS", TEO),
        "LITERATURA": ("LIT", TEO),
        "SALUD Y ADOLESCENCIA": ("SYA", TEO),
        "CONOCIMIENTO DE LOS MATERIALES": ("", CT),  # sin código
        "FISICA": ("FIS", CT),
        "MATEMATICA CICLO SUPERIOR": ("MCS", CT),  # Matemática - Ciclo Superior
        "QUIMICA": ("QMC", CT),
        "DIBUJO TECNOLOGICO": ("", TE),  # sin código
        "INTROD. A LA ELECTR. Y MEDIC.": ("IEM", TE),  # Introducción a la Electricidad y Mediciones
        "INTRODUCC. A LA ELECTR. Y MEDIC.": ("IEM", TE),
        "PROYECTO": ("PD4", TE),  # Proyecto, Diseño e Instalaciones de Energías Renovables
        "TECNOLOGIA": ("TER", TE),  # Tecnología de las Energías Renovables
    },
    ("5", "ELECTROMECÁNICA"): {
        "EDUCACION FISICA": ("EFC", TEO),
        "GEOGRAFIA": ("GGF", TEO),
        "HISTORIA": ("HTR", TEO),
        "INGLES": ("IGS", TEO),
        "LITERATURA": ("LIT", TEO),
        "POLITICA Y CIUDADANIA": ("PYC", TEO),
        "ANALISIS MATEMATICO": ("", CT),  # sin código
        "ELECTROTECNIA": ("NIA", CT),
        "MECANICA TECNICA": ("MOS", CT),  # Mecánica y Mecanismos
        "MECANICA Y MECANISMO": ("MOS", CT),
        "MECANICA Y MECANISMOS": ("MOS", CT),
        "RESIST. DE LOS MATERIALES": ("REM", CT),  # Resistencia y Ensayos de los Materiales
        "RESISTENCIA DE LOS MAT": ("REM", CT),
        "RESISTENCIA DE LOS MATERIALES": ("REM", CT),
        "DISENO Y PROC. MEC.": ("PRM", TE),  # Diseño y Procesamiento Mecánico
        "INST Y APLIC DE LA ENERGIA": ("APE", TE),  # Instalaciones y Aplicaciones de la Energía
        "INST. Y AP DE LA ENERG.": ("APE", TE),
        "INST. Y AP. DE LA ENERG.": ("APE", TE),
        "MAQ. ELEC. Y AUTOMAT": ("MEA", TE),  # Máquinas Eléctricas y Automatismos
    },
    ("5", "MAESTRO MAYOR DE OBRA"): {
        "EDUCACION FISICA": ("EFC", TEO),
        "GEOGRAFIA": ("GGF", TEO),
        "HISTORIA": ("HTR", TEO),
        "INGLES": ("IGS", TEO),
        "LITERATURA": ("LIT", TEO),
        "POLITICA Y CIUDADANIA": ("PYC", TEO),
        "ANALISIS MATEMATICO": ("", CT),  # sin código
        "INSTALACIONES ELECTRICAS": ("", CT),  # sin código · ¿tipo?
        "INSTALACIONES ELECTRICAS INVERNON, MARCELO": ("", CT),
        "RESIST. DE LOS MATERIALES": ("REM", CT),  # Resistencia y Ensayos de los Materiales
        "RESISTENCIA DE LOS MAT": ("REM", CT),
        "RESISTENCIA DE LOS MATERIALES": ("REM", CT),
        "DOCUM. TECNICA": ("DOT", TE),  # Documentación Técnica
        "DOCUMENTACION TECNICA": ("DOT", TE),
        "MATERIALES DE OBRA": ("MAO", TE),
        "PROYECTO": ("ORP", TE),
        "PROYECTO FLORENCIA MARIA R": ("ORP", TE),
        "SIST. CONSTR.": ("SCO", TE),  # Sistemas Constructivos
        "SIST. CONSTRUC.": ("SCO", TE),
        "SISTEMAS CONSTRUCT.": ("SCO", TE),
        "SISTEMAS CONSTRUCTIVOS": ("SCO", TE),
    },
    ("5", "ENERGÍAS RENOVABLES"): {
        "EDUCACION FISICA": ("EFC", TEO),
        "GEOGRAFIA": ("GGF", TEO),
        "HISTORIA": ("HTR", TEO),
        "INGLES": ("IGS", TEO),
        "LITERATURA": ("LIT", TEO),
        "POLITICA Y CIUDADANIA": ("PYC", TEO),
        "ANALISIS MATEMATICO": ("", CT),  # sin código
        "ELECTR. Y MAQ ELECT": ("EME", CT),  # Electrotecnia y Máquinas Eléctricas
        "ELECTROTEC. Y MAQ. ELEC.": ("EME", CT),
        "ELECTROTECNIA Y MAQUINAS ELECTRICAS": ("EME", CT),
        "MECANICA": ("MCA", CT),
        "QUIM. DEL AMBIENTE": ("QDA", CT),  # Química del Ambiente
        "QUIMICA DEL AMBIENTE": ("QDA", CT),
        "CONTROLES Y AUTOMATISMOS": ("CYA", TE),
        "PROYECTO": ("PD5", TE),  # Proyecto, Diseño e Instalaciones de Energías Renovables
        "TECNOLOGIA": ("TER", TE),  # Tecnología de las Energías Renovables
    },
    ("6", "ELECTROMECÁNICA"): {
        "ARTE": ("RTE", TEO),
        "EDUCACION FIDICA": ("EFC", TEO),  # Educación Física
        "EDUCACION FISICA": ("EFC", TEO),
        "FILOSOFIA": ("FIA", TEO),
        "INGLES": ("IGS", TEO),
        "LITERATURA": ("LIT", TEO),
        "DERECHO DEL TRABAJO": ("DET", CT),  # Derechos del Trabajo
        "DERECHOS DEL TRABAJO": ("DET", CT),
        "ELECTROTECNIA": ("NIA", CT),
        "MATEMATICA": ("MAP", CT),  # Matemática Aplicada
        "MATEMATICA APLICADA": ("MAP", CT),
        "SIST. MECANICOS": ("", CT),  # Sistemas Mecánicos · sin código · ¿tipo?
        "SISTEMAS MECANICOS": ("", CT),
        "TERMODINAMICA": ("TMT", CT),  # Termodinámica y Máquinas Térmicas
        "DISENO Y PROC. MEC,": ("PRM", TE),  # Diseño y Procesamiento Mecánico
        "DISENO Y PROC. MEC.": ("PRM", TE),
        "INST. Y AP. DE LA ENERG.": ("APE", TE),  # Instalaciones y Aplicaciones de la Energía
        "INSTAL. Y APLIC. DE LA ENERGIA": ("APE", TE),
        "LAB. DE MED ELECTR": ("LME", TE),  # Laboratorio de Mediciones Eléctricas
        "LABORAT. MED. ELECT.": ("LME", TE),
        "LAB. DE METROL. Y CONTROL DE CAL.": ("LCC", TE),  # Laboratorio de Metrología y Control de Calidad
        "MAQ. ELEC. Y AUTOMAT": ("MEA", TE),  # Máquinas Eléctricas y Automatismos
    },
    ("6", "MAESTRO MAYOR DE OBRA"): {
        "ARTE": ("RTE", TEO),
        "EDUCACION FISICA": ("EFC", TEO),
        "FILOSOFIA": ("FIA", TEO),
        "INGLES": ("IGS", TEO),
        "LITERATURA": ("LIT", TEO),
        "DERECHO DEL TRABAJO": ("DET", CT),  # Derechos del Trabajo
        "DERECHOS DEL TRABAJO": ("DET", CT),
        "ESTRUCTURAS": ("ESR", CT),
        "INST. SANITARIAS Y DE GAS": ("ISI", CT),  # Instalaciones Sanitarias y de Gas
        "INSTALACIONES SANITARIAS Y DE GAS": ("ISI", CT),
        "MATEMATICA APLICADA": ("MAP", CT),
        "DIR. Y EJEC. DE LAS INST.": ("DEJ", TE),  # Dirección de la Ejecución de Instalaciones
        "PROYECTO": ("ORP", TE),
        "PROYECTO DE LAS INST.": ("PIN", TE),  # Proyectos de Instalaciones
        "SISTEMAS CONSTRUCT.": ("SCO", TE),  # Sistemas Constructivos
        "SISTEMAS CONSTRUCTIVOS": ("SCO", TE),
        "SISTEMAS CONSTRUTIVOS": ("SCO", TE),
    },
    ("6", "ENERGÍAS RENOVABLES"): {
        "ARTE": ("RTE", TEO),
        "EDUCACION FISICA": ("EFC", TEO),
        "FILOSOFIA": ("FIA", TEO),
        "INGLES": ("IGS", TEO),
        "LITERATURA": ("LIT", TEO),
        "DERECHOS DEL TRABAJO": ("DET", CT),
        "ELECTRONICA": ("ECT", CT),
        "MANTENIMIENTO DE LAS INSTALACIONES": ("MIN", CT),  # Mantenimiento de Instalaciones
        "MATEMATICA": ("MAP", CT),  # Matemática Aplicada
        "MATEMATICA APLICADA": ("MAP", CT),
        "RELEVAMIENTO AMBIENTAL": ("REA", CT),
        "TERM. Y MAQ. TERM.": ("TMT", CT),  # Termodinámica y Máquinas Térmicas
        "TERMODINAMICA Y MAQ. TERM.": ("TMT", CT),
        "TERMODINAMICA Y MAQ. TERMICAS": ("TMT", CT),
        "TERMODINAMICA Y MAQUINAS TERMICAS": ("TMT", CT),
        "CONTROLES Y AUTOMATISMOS": ("CYA", TE),
        "PROYECTO": ("PD6", TE),  # Proyecto, Diseño e Instalaciones de Energías Renovables
        "TECNOLOGIA": ("TER", TE),  # Tecnología de las Energías Renovables
        "TECNOLOGIA D LAS ENERG. RENOV.": ("TER", TE),
    },
    ("7", "ELECTROMECÁNICA"): {
        "ELECTROTECNIA INDUSTRIAL": ("EIN", CT),  # Electrónica Industrial
        "EMPRENDIMIENTOS PROD. Y DESARR. LOCAL": ("EDL", CT),  # Emprendimientos Productivos y Desarrollo Local
        "MAQUINAS ELECTRICAS": ("MAQ", CT),
        "SEGURIDAD E HIGIENE": ("", CT),  # Seguridad, Higiene y Protección Ambiental · sin código · ¿tipo?
        "SISTEMAS MECANICOS": ("", CT),  # sin código · ¿tipo?
        "LAB. DE METROL. Y CONTROL DE CAL.": ("LCC", TE),  # Laboratorio de Metrología y Control de Calidad
        "MANTENIMIENTO Y MONTAJE ELECTROM.": ("MME", TE),  # Mantenimiento y Montaje Electromecánico
        "MANTENIMIENTO Y MONTAJE ELECTROMECANICO": ("MME", TE),
        "PROY. Y DISENO ELEC.": ("PDN", TE),  # Proyecto y Diseño Electromecánico
        "PROY. Y DISENO ELECTROMECANICO": ("PDN", TE),
        "PROY. Y DISENO INSTALAC. ELECTR.": ("", TE),  # Proyecto y Diseño de Instalaciones Eléctricas · sin código
        "PRACTICAS PROFESIONALIZANTES": ("", TE),  # sin código
    },
    ("7", "MAESTRO MAYOR DE OBRA"): {
        "EMPRENDIMIENTOS PROD. Y DESARR. LOCAL": ("EDL", CT),  # Emprendimientos Productivos y Desarrollo Local
        "ESTRUCTURAS": ("ESR", CT),
        "INST. DE AIRE ACONDICIONADO": ("", CT),  # Instalaciones de Acondicionamiento del Aire · sin código · ¿tipo?
        "DIRECC. DE OBRA": ("", TE),  # Dirección de Obra · sin código
        "DIRECCION DE OBRA": ("", TE),
        "EJER. PROF. CONST.": ("EPC", TE),  # Ejercicio Profesional de la Construcción
        "EJER. PROF. DE LA CONST.": ("EPC", TE),
        "PROYECTO FINAL": ("PRF", TE),
        "PRACTICAS PROFES.": ("", TE),  # Prácticas Profesionalizantes · sin código
        "PRACTICAS PROFESIONALIZANTES": ("", TE),
        "PRECTICAS PROFESIONALIZANTES": ("", TE),
    },
    ("7", "ENERGÍAS RENOVABLES"): {
        "EFICIENCIA ENERG. Y USO RACIONAL DE LA ENERGIA": ("EER", CT),  # Eficiencia Energética y Uso Racional de la Energía
        "EMPRENDIMIENTOS PRODUCTIVOS Y DESARROLLO LOCAL": ("EDL", CT),
        "GESTION DE LAS ENERGIAS RENOV": ("GER", CT),  # Gestión de las Energías Renovables
        "SEGURIDAD HIGIENE Y PROTECCION AMBIENTAL": ("", CT),  # Seguridad, Higiene y Protección Ambiental · sin código · ¿tipo?
        "SISTEMAS ELECTROENERGETICOS": ("SLE", CT),  # Sistema Electroenergético
        "EJECUCION DE PROY.": ("", TE),  # Ejecución de Proyectos · sin código
        "ELABORACION DE P.": ("", TE),  # Elaboración de Proyectos · sin código
        "PRACTICAS PROFES.": ("", TE),  # Prácticas Profesionalizantes · sin código
    },
}
