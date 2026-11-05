"""Consentimiento y permisos de la conexión de Salidas."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import re

from flask import abort, current_app, redirect, render_template_string, request, session, url_for
from itsdangerous import BadData, URLSafeTimedSerializer

import accesos
from oauth_mcp import OAuthMCP
import salidas

SCOPE = 'salidas:editar'
RUTA_OAUTH = '/salidas/oauth'


def autorizado():
    """Codex puede usar una clave propia de Salidas; los clientes OAuth conservan su flujo."""
    esquema, _, token = request.headers.get('Authorization', '').partition(' ')
    if esquema.lower() == 'bearer' and token.startswith('mitre_salidas_'):
        huella = os.environ.get('SALIDAS_MCP_TOKEN_SHA256', '').strip().lower()
        if not re.fullmatch(r'[0-9a-f]{64}', huella) or not re.fullmatch(r'mitre_salidas_[A-Za-z0-9_-]{43}', token):
            return False
        return hmac.compare_digest(hashlib.sha256(token.encode('ascii')).hexdigest(), huella)
    return oauth.autorizado()


def _generacion():
    return hmac.new(current_app.secret_key.encode(), b'salidas-mcp-oauth-v1', hashlib.sha256).hexdigest()


def _vigente(identidad):
    if not identidad:
        return False
    tipo, valor = identidad
    if tipo == 'admin':
        return hmac.compare_digest(valor, accesos.huella_clave())
    if tipo == 'salidas':
        clave = salidas._clave_propia()
        return bool(clave and hmac.compare_digest(valor, salidas._huella(clave)))
    if tipo == 'dispositivo':
        fila = accesos._dispositivo(valor)
        return bool(fila and accesos.tiene(json.loads(fila['permisos']), salidas.PERMISO_ESCRITURA))
    return False


def _identidad():
    if not accesos.puede(salidas.PERMISO_ESCRITURA):
        return None
    dato = session.get('acceso') or {}
    candidatos = {
        'admin': dato.get('clave'),
        'dispositivo': dato.get('id'),
    }
    tipo = dato.get('tipo')
    valor = candidatos.get(tipo)
    if valor and _vigente((tipo, valor)):
        return [tipo, valor]
    valor = session.get(salidas.SESION_CLAVE)
    if isinstance(valor, str) and _vigente(('salidas', valor)):
        return ['salidas', valor]
    return None


def _consentir():
    identidad = _identidad()
    if identidad is None:
        return None, 'Necesitás una sesión con permiso de edición de Salidas.', 403
    return identidad, None, 200


def _firma_continuar():
    return URLSafeTimedSerializer(_generacion(), salt='salidas-mcp-continuar')


@salidas.bp.get('/mcp-continuar')
@accesos.requiere(salidas.PERMISO_ESCRITURA)
def mcp_continuar():
    try:
        query = _firma_continuar().loads(request.args.get('solicitud', ''), max_age=600)
    except BadData:
        abort(400)
    return redirect(RUTA_OAUTH + '/authorize?' + query)


def _pantalla(cliente, csrf, error):
    autorizado = _identidad() is not None
    volver = url_for('salidas.mcp_continuar', solicitud=_firma_continuar().dumps(
        request.query_string.decode('ascii')))
    return render_template_string('''<!doctype html><html lang="es"><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>Conectar AppMitre Salidas</title>
        <style>body{font:18px system-ui;max-width:480px;margin:10vh auto;padding:24px;color:#1a365d}
        button{font:inherit;padding:10px;margin:8px 8px 0 0}</style>
        <h1>Conectar AppMitre Salidas</h1>
        <p><strong>{{ cliente }}</strong> podrá consultar, crear y editar las salidas guardadas.
        La conexión conserva el acceso mientras siga vigente tu permiso de edición.</p>
        {% if error %}<p role="alert">{{ error }}</p>{% endif %}
        {% if not autorizado %}<p><a href="{{ login }}">Iniciar sesión en Salidas</a></p>{% endif %}
        <form method="post"><input type="hidden" name="csrf" value="{{ csrf }}">
        {% if autorizado %}<button name="decision" value="autorizar">Autorizar</button>{% endif %}
        <button name="decision" value="cancelar">Cancelar</button></form></html>''',
        cliente=cliente, csrf=csrf, error=error, autorizado=autorizado,
        login=url_for('salidas.login', next=volver))


oauth = OAuthMCP(
    resource_path='/mcp/salidas', issuer_path=RUTA_OAUTH, oauth_path=RUTA_OAUTH, scope=SCOPE,
    nombre='AppMitre Salidas', db_path=lambda: Path(salidas.DB_PATH).with_name('salidas_oauth.db'),
    generacion=_generacion, pantalla=_pantalla, consentir=_consentir, vigente=_vigente,
)
