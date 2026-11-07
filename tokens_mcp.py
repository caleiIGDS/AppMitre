"""Claves Bearer de integraciones, independientes de las sesiones web."""
import hashlib
import hmac
import os

from flask import jsonify, request


def coincide(variable):
    esquema, _, token = request.headers.get('Authorization', '').partition(' ')
    esperado = os.environ.get(variable, '').strip()
    return bool(esquema.lower() == 'bearer' and token and esperado and
                hmac.compare_digest(hashlib.sha256(token.encode()).digest(),
                                    hashlib.sha256(esperado.encode()).digest()))


def rechazar(admin=False):
    r = jsonify(error='forbidden' if admin else 'invalid_token',
                error_description='Esta funcion requiere el token de administracion.' if admin else
                'Configura el token del MCP en Authorization: Bearer <token>.')
    r.status_code = 403 if admin else 401
    if not admin:
        r.headers['WWW-Authenticate'] = 'Bearer realm="AppMitre MCP"'
    return r
