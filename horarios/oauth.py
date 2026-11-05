"""Adaptador de la autorización de Horarios para su MCP de lectura."""
from pathlib import Path

from flask import current_app, jsonify, render_template_string, request

from oauth_mcp import OAuthMCP

from . import acceso, datos

SCOPE = 'horarios:leer'
PAGINA = '''<!doctype html><html lang="es"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Conectar AppMitre</title><style>body{font:18px system-ui;background:#eef2f7;color:#1a365d;
max-width:440px;margin:10vh auto;padding:24px}input,button{box-sizing:border-box;width:100%;padding:14px;
font:inherit;margin:12px 0}button{background:#1a365d;color:white;border:0;cursor:pointer}</style>
<h1>Conectar AppMitre</h1><p><strong>{{ cliente }}</strong> podrá consultar horarios y descargar PDF.
El acceso es de solo lectura.</p><form method="post"><input type="hidden" name="csrf" value="{{ csrf }}">
<label>Contraseña de Horarios<input type="password" name="clave" required autocomplete="current-password"></label>
{% if error %}<p role="alert">{{ error }}</p>{% endif %}<button name="decision" value="autorizar">Conectar</button>
<button name="decision" value="cancelar" formnovalidate>Cancelar</button></form>
<p>La conexión recordará el acceso. No hace falta escribir la contraseña en el chat.</p></html>'''


def _consentir():
    resultado = acceso.verificar_clave(request.remote_addr, request.form.get('clave'))
    if resultado == 'ok':
        return {}, None, 200
    if resultado == 'bloqueado':
        return None, 'Esperá 15 minutos antes de reintentar.', 429
    return None, 'Contraseña incorrecta.', 401


_oauth = OAuthMCP(
    resource_path='/mcp', issuer_path='', oauth_path='/horarios/oauth', scope=SCOPE,
    nombre='Horarios AppMitre', db_path=lambda: Path(datos.DB_PATH).with_name('horarios_oauth.db'),
    generacion=lambda: acceso.clave_derivada(current_app.secret_key).hex(),
    pantalla=lambda cliente, csrf, error: render_template_string(PAGINA, cliente=cliente, csrf=csrf, error=error),
    consentir=_consentir, vigente=lambda identidad: True,
)
base = _oauth.base
leer = _oauth.leer
autorizado = _oauth.autorizado
registrar = _oauth.registrar


def desafio():
    r = jsonify(error='invalid_token', error_description='Conectá AppMitre para autorizar el acceso.')
    r.status_code = 401
    r.headers['WWW-Authenticate'] = _oauth.desafio()
    return r
