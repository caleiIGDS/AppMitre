"""Sistema de horarios (`/horarios`) — un sitio aparte.

Consulta de horarios por curso, profesor, aula y preceptor; dashboard "En Vivo" para
kiosco; export a PDF. Se regenera desde Google Sheets.

Es independiente del resto de la app: **clave propia** (`HORARIOS_CLAVE`, ver
`acceso.py`), config propia (`config.py`), datos propios (`datos.py` → `escuela.db`). No
importa `accesos`, ni el `config.py` de la raíz, ni `crud`, ni las otras áreas. La
dependencia va en un solo sentido: el agente importa `horarios.datos` para leer, nunca al
revés.

La interfaz es la app instalable (`frontend/horarios/`, servida en `/horarios/` por
`app.py`). Expone la API (`bp_app`), los exports PDF (`bp`), `init_db` y `cargar_inicial`.
"""
import os

from flask import Blueprint

from .config import PRODUCCION

bp = Blueprint('horarios', __name__, url_prefix='/horarios')

# El Drive de la escuela es privado: la planilla se baja por el Web App de Apps Script
# (ver apps_script/). Sin URL ni secreto no se puede regenerar escuela.db; en producción
# eso deja la escuela sin horarios, así que se exige de una — igual que HORARIOS_CLAVE
# (ese chequeo vive en acceso._clave()).
if PRODUCCION and not (os.environ.get('SHEETS_PROXY_URL') and os.environ.get('SHEETS_PROXY_SECRET')):
    raise RuntimeError(
        "Faltan SHEETS_PROXY_URL / SHEETS_PROXY_SECRET en el entorno. Sin ellas no se "
        "puede bajar la planilla privada de horarios: no se arranca en producción.")

# Los PDF del servidor complementan la impresión local de la app.
from . import rutas  # noqa: E402,F401
from .datos import init_db, cargar_inicial  # noqa: E402,F401
# La API de la app instalable de horarios (/app-horarios/api). Mismo gate de sesión.
from .app_api import bp_app  # noqa: E402,F401
from .mcp import bp_mcp  # noqa: E402,F401
