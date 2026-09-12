# config.py
# Configuración compartida por el resto de la app (gestión, agente, salidas,
# accesos). El sistema de horarios NO usa este archivo — tiene su propia config en
# `horarios/config.py` (ver el plan de separación en dev-log/DECISIONS.md).

import os
from datetime import datetime, timedelta, timezone

RAIZ = os.path.dirname(os.path.abspath(__file__))

# Dónde viven TODAS las bases: una sola carpeta, para que "qué hay que respaldar" tenga una
# respuesta corta y para que en la raíz no se confunda un archivo vivo con una sobra. Cada
# área arma su ruta desde acá (`os.path.join(DIR_DATOS, 'x.db')`); qué hay en cada archivo lo
# cuenta `database/LEEME.md`. El sistema de horarios tiene su propia copia de esta constante
# en `horarios/config.py`, como el resto de lo que duplica a propósito.
DIR_DATOS = os.path.join(RAIZ, 'database')

# ¿Estamos en el hosting? PythonAnywhere exporta PYTHONANYWHERE_DOMAIN en el entorno del
# web app. Separa las dos cosas que tienen que diferir entre local y producción: el flag
# Secure de la cookie (en localhost es http y con Secure no viajaría) y fallar al arrancar
# si faltan los secretos, que en desarrollo sería un estorbo.
PRODUCCION = bool(os.environ.get('PYTHONANYWHERE_DOMAIN'))

# Cuánto vive la cookie de sesión. NO es la política de acceso: esa vive en la tabla
# `dispositivos` de accesos.db, y revocar corta en el request siguiente. Esto es sólo
# cuánto puede quedar un dispositivo sin usarse antes de necesitar un link nuevo; la
# expiración se corre sola en cada visita (SESSION_REFRESH_EACH_REQUEST).
SESION_DIAS = 60

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


# Branding de la institución
ESCUELA_NOMBRE = "EMILIO MITRE"
ESCUELA_LOGO = "images/escudo.svg"
ESCUELA_VERSION = "V1.16"

# Días laborales (en orden, título case con acentos)
DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
