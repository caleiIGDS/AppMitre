"""Gate de sesión propio del sistema de horarios.

Horarios es un sitio aparte: NO usa `accesos.py` (el motor de permisos del resto de la
app), ni `accesos.db`, ni los links de invitación, ni `GESTION_CLAVE`. Una sola
contraseña, `HORARIOS_CLAVE`, y un flag propio en la cookie de sesión. Entrar acá no da
acceso a `/gestion` y viceversa.

La cookie firmada es la misma del proceso Flask (un solo `secret_key`), pero la clave que
se escribe (`horarios_ok`) es distinta de la de `accesos` (`acceso`): los dos sistemas no
se leen entre sí. Cookies 100% separadas recién si algún día horarios se parte en su
propia app Flask.
"""

import os
import time
import hmac
from threading import Lock

from flask import abort, session

from .config import PRODUCCION

SESSION_FLAG = 'horarios_ok'

# Rate limiting: máximo 5 intentos fallidos por IP en 15 minutos
MAX_INTENTOS = 5
VENTANA_MINUTOS = 15
_INTENTOS_FALLIDOS = {}  # {ip: [(timestamp, _), ...]}
_LOCK_INTENTOS = Lock()


def _limpiar_intentos_expirados(ip):
    """Quita intentos que ya expiraron (>15 minutos)."""
    if ip not in _INTENTOS_FALLIDOS:
        return
    ahora = time.time()
    _INTENTOS_FALLIDOS[ip] = [
        t for t in _INTENTOS_FALLIDOS[ip]
        if ahora - t < VENTANA_MINUTOS * 60
    ]
    if not _INTENTOS_FALLIDOS[ip]:
        del _INTENTOS_FALLIDOS[ip]


def _registrar_intento_fallido(ip):
    """Registra un intento fallido y devuelve True si superó el límite."""
    _limpiar_intentos_expirados(ip)
    if ip not in _INTENTOS_FALLIDOS:
        _INTENTOS_FALLIDOS[ip] = []
    _INTENTOS_FALLIDOS[ip].append(time.time())
    return len(_INTENTOS_FALLIDOS[ip]) > MAX_INTENTOS


def _clave():
    """La contraseña de horarios. Obligatoria en producción; en dev cae a 'dev'."""
    clave = os.environ.get('HORARIOS_CLAVE')
    if clave:
        return clave
    if PRODUCCION:
        raise RuntimeError(
            "Falta HORARIOS_CLAVE en el entorno. El sistema de horarios pide contraseña "
            "propia: no se arranca en producción sin ella.")
    print("AVISO: HORARIOS_CLAVE no está seteada — usando la contraseña de desarrollo 'dev'.")
    return 'dev'


def autenticado():
    return bool(session.get(SESSION_FLAG))


def verificar_clave(ip, clave):
    """Verificador común a login y Bearer; no crea sesión ni concede permisos."""
    with _LOCK_INTENTOS:
        _limpiar_intentos_expirados(ip)
        if len(_INTENTOS_FALLIDOS.get(ip, [])) >= MAX_INTENTOS:
            return 'bloqueado'
        proporcionada = clave.encode('utf-8') if isinstance(clave, str) else b''
        if hmac.compare_digest(proporcionada, _clave().encode('utf-8')):
            _INTENTOS_FALLIDOS.pop(ip, None)
            return 'ok'
        _registrar_intento_fallido(ip)
        return 'mal'


def comprobar_clave(ip, clave):
    """El login abre sesión solo después de pasar el verificador compartido."""
    resultado = verificar_clave(ip, clave)
    if resultado == 'ok':
        session.permanent = True
        session[SESSION_FLAG] = True
    return resultado


def registrar(bp):
    """Monta el gate sobre el blueprint de los PDF (`/horarios/export/...`).

    Sin sesión contesta 401: a los PDF se llega desde la app, que es la que pide la clave
    (`app_api.py`, POST /entrar). No hay página de login propia.
    """

    @bp.before_request
    def _gate():
        if not autenticado():
            abort(401)
