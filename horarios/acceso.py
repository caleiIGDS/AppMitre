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

from flask import abort, redirect, render_template, request, session, url_for

from .config import PRODUCCION

SESSION_FLAG = 'horarios_ok'

# Sólo estos endpoints redirigen al login cuando no hay sesión. El resto (los `/api/*` y
# los `/export/*`) contesta 401 pelado, que es lo que el `fetch` del SPA sabe leer.
PAGINAS = {'horarios.index'}

# Rate limiting: máximo 5 intentos fallidos por IP en 15 minutos
MAX_INTENTOS = 5
VENTANA_MINUTOS = 15
_INTENTOS_FALLIDOS = {}  # {ip: [(timestamp, _), ...]}


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


def registrar(bp):
    """Monta el gate + /horarios/login + /horarios/salir sobre el blueprint."""

    @bp.before_request
    def _gate():
        if request.endpoint in ('horarios.login', 'horarios.salir'):
            return
        if not autenticado():
            if request.endpoint in PAGINAS:
                return redirect(url_for('horarios.login', next=request.path))
            abort(401)

    @bp.route('/login', methods=['GET', 'POST'])
    def login():
        error = None
        if request.method == 'POST':
            ip = request.remote_addr
            _limpiar_intentos_expirados(ip)
            # Chequear si ya superó el límite
            if ip in _INTENTOS_FALLIDOS and len(_INTENTOS_FALLIDOS[ip]) >= MAX_INTENTOS:
                abort(429)  # Too Many Requests
            if request.form.get('clave', '') == _clave():
                _INTENTOS_FALLIDOS.pop(ip, None)  # Limpiar intentos fallidos tras login exitoso
                session.permanent = True
                session[SESSION_FLAG] = True
                volver = request.form.get('next', '')
                if not volver.startswith('/horarios'):
                    volver = url_for('horarios.index')
                return redirect(volver)
            # Contraseña incorrecta: registrar intento fallido
            _registrar_intento_fallido(ip)
            error = 'Contraseña incorrecta.'
        return render_template('horarios/login.html', error=error,
                               next=request.values.get('next', ''))

    @bp.route('/salir')
    def salir():
        session.pop(SESSION_FLAG, None)
        return redirect(url_for('horarios.login'))
