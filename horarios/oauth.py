"""Autorización MCP: código + PKCE, registro de clientes y acceso renovable.

La contraseña se escribe únicamente en la pantalla del servidor. SQLite guarda
clientes y hashes de credenciales; no depende de la DB que se regenera desde Sheets.
"""
import base64
from contextlib import contextmanager, closing
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import sqlite3
import time
from urllib.parse import urlencode, urlsplit, unquote

from flask import current_app, jsonify, redirect, render_template_string, request, session

from . import acceso, datos

SCOPE = 'horarios:leer'
ACCESS_SECONDS = 3600
REFRESH_SECONDS = 180 * 86400
CODE_SECONDS = 180
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


def origen():
    return request.host_url.rstrip('/')


def recurso():
    return origen() + '/mcp'


def digest(valor):
    return hashlib.sha256(valor.encode('utf-8')).hexdigest()


def generacion():
    return acceso.clave_derivada(current_app.secret_key).hex()


@contextmanager
def base():
    ruta = Path(datos.DB_PATH).with_name('horarios_oauth.db')
    with closing(sqlite3.connect(ruta, timeout=15)) as con, con:
        con.row_factory = sqlite3.Row
        con.executescript('''
          CREATE TABLE IF NOT EXISTS clientes (
            id TEXT PRIMARY KEY, metadata TEXT NOT NULL, secreto TEXT);
          CREATE TABLE IF NOT EXISTS credenciales (
            hash TEXT PRIMARY KEY, tipo TEXT NOT NULL, cliente TEXT NOT NULL,
            vence REAL NOT NULL, generacion TEXT NOT NULL, payload TEXT NOT NULL);
        ''')
        con.execute('DELETE FROM credenciales WHERE vence < ?', (time.time(),))
        con.commit()
        yield con


def guardar(con, tipo, cliente, payload, duracion):
    valor = secrets.token_urlsafe(40)
    con.execute('INSERT INTO credenciales VALUES (?,?,?,?,?,?)',
                (digest(valor), tipo, cliente, time.time() + duracion,
                 generacion(), json.dumps(payload)))
    return valor


def leer(con, valor, tipo, consumir=False):
    if not isinstance(valor, str) or len(valor) > 2048:
        return None
    fila = con.execute('SELECT * FROM credenciales WHERE hash=? AND tipo=?', (digest(valor), tipo)).fetchone()
    if not fila or fila['vence'] < time.time() or not hmac.compare_digest(fila['generacion'], generacion()):
        return None
    if consumir:
        con.execute('DELETE FROM credenciales WHERE hash=?', (fila['hash'],))
    return fila


def autorizado():
    cabecera = request.headers.get('Authorization', '')
    esquema, _, valor = cabecera.partition(' ')
    if esquema.lower() != 'bearer' or not valor:
        return False
    with base() as con:
        fila = leer(con, valor, 'access')
    if not fila:
        return False
    p = json.loads(fila['payload'])
    return p.get('resource') == recurso() and SCOPE in p.get('scope', '').split()


def desafio():
    r = jsonify(error='invalid_token', error_description='Conectá AppMitre para autorizar el acceso.')
    r.status_code = 401
    r.headers['WWW-Authenticate'] = (
        f'Bearer resource_metadata="{origen()}/.well-known/oauth-protected-resource/mcp", scope="{SCOPE}"')
    return r


def error(codigo, mensaje, estado=400):
    return jsonify(error=codigo, error_description=mensaje), estado


def uri_valida(uri):
    if not isinstance(uri, str) or len(uri) > 2048:
        return False
    try:
        u = urlsplit(uri)
        return bool(u.hostname and not u.username and not u.password and not u.fragment and
                    (u.scheme == 'https' or (u.scheme == 'http' and u.hostname in ('127.0.0.1', 'localhost', '::1'))))
    except ValueError:
        return False


def cliente(con, id_cliente):
    fila = con.execute('SELECT * FROM clientes WHERE id=?', (id_cliente,)).fetchone()
    return fila, json.loads(fila['metadata']) if fila else {}


def autenticar_cliente(con):
    id_cliente = request.form.get('client_id', '')
    secreto = request.form.get('client_secret', '')
    metodo = 'client_secret_post' if secreto else 'none'
    auth = request.authorization
    if auth and auth.type.lower() == 'basic':
        id_cliente, secreto = unquote(auth.username or ''), unquote(auth.password or '')
        metodo = 'client_secret_basic'
    fila, meta = cliente(con, id_cliente)
    if not fila or metodo != meta['token_endpoint_auth_method']:
        return None
    if fila['secreto'] and not hmac.compare_digest(fila['secreto'], digest(secreto)):
        return None
    return id_cliente


def emitir(con, id_cliente, payload):
    return {'access_token': guardar(con, 'access', id_cliente, payload, ACCESS_SECONDS),
            'token_type': 'Bearer', 'expires_in': ACCESS_SECONDS, 'scope': payload['scope'],
            'refresh_token': guardar(con, 'refresh', id_cliente, payload, REFRESH_SECONDS)}


def registrar(bp):
    @bp.get('/.well-known/oauth-protected-resource')
    @bp.get('/.well-known/oauth-protected-resource/mcp')
    def metadata_recurso():
        return jsonify(resource=recurso(), authorization_servers=[origen()], scopes_supported=[SCOPE],
                       bearer_methods_supported=['header'], resource_name='Horarios AppMitre')

    @bp.get('/.well-known/oauth-authorization-server')
    def metadata_autorizacion():
        o = origen()
        return jsonify(issuer=o, authorization_endpoint=o+'/horarios/oauth/authorize',
                       token_endpoint=o+'/horarios/oauth/token', registration_endpoint=o+'/horarios/oauth/register',
                       revocation_endpoint=o+'/horarios/oauth/revoke', response_types_supported=['code'],
                       grant_types_supported=['authorization_code', 'refresh_token'],
                       code_challenge_methods_supported=['S256'], scopes_supported=[SCOPE, 'offline_access'],
                       token_endpoint_auth_methods_supported=['none', 'client_secret_basic', 'client_secret_post'],
                       authorization_response_iss_parameter_supported=True)

    @bp.post('/horarios/oauth/register')
    def registro():
        if request.content_length and request.content_length > 16384:
            return error('invalid_client_metadata', 'Registro demasiado grande.', 413)
        p = request.get_json(silent=True)
        if not isinstance(p, dict):
            return error('invalid_client_metadata', 'Se requiere un objeto JSON.')
        uris = p.get('redirect_uris')
        metodo = p.get('token_endpoint_auth_method', 'client_secret_basic')
        if (not isinstance(uris, list) or not 1 <= len(uris) <= 10 or not all(uri_valida(u) for u in uris)
                or metodo not in ('none', 'client_secret_basic', 'client_secret_post')
                or p.get('response_types', ['code']) != ['code']
                or not isinstance(p.get('grant_types', []), list)
                or any(g not in ('authorization_code', 'refresh_token') for g in p.get('grant_types', []))):
            return error('invalid_client_metadata', 'Callbacks o método de autenticación no válidos.')
        nombre = p.get('client_name', 'Asistente de IA')
        if not isinstance(nombre, str) or not 1 <= len(nombre) <= 160:
            return error('invalid_client_metadata', 'Nombre de cliente no válido.')
        meta = {'client_id': secrets.token_urlsafe(24), 'client_name': nombre, 'redirect_uris': uris,
                'token_endpoint_auth_method': metodo, 'response_types': ['code'],
                'grant_types': ['authorization_code', 'refresh_token']}
        secreto = secrets.token_urlsafe(40) if metodo != 'none' else None
        with base() as con:
            con.execute('INSERT INTO clientes VALUES (?,?,?)',
                        (meta['client_id'], json.dumps(meta), digest(secreto) if secreto else None))
        return jsonify({**meta, **({'client_secret': secreto, 'client_secret_expires_at': 0} if secreto else {})}), 201

    @bp.route('/horarios/oauth/authorize', methods=['GET', 'POST'])
    def autorizar():
        p = request.args
        with base() as con:
            _, meta = cliente(con, p.get('client_id', ''))
        # Nunca redirigir a una dirección no registrada, tampoco para informar errores.
        if not meta or p.get('redirect_uri') not in meta['redirect_uris']:
            return error('invalid_request', 'Cliente o callback desconocido.')

        def volver(**valores):
            q = urlencode({**valores, 'state': p.get('state', ''), 'iss': origen()})
            return redirect(p['redirect_uri'] + ('&' if '?' in p['redirect_uri'] else '?') + q)

        scope = p.get('scope', SCOPE).split()
        if (p.get('response_type') != 'code' or p.get('resource') != recurso()
                or p.get('code_challenge_method') != 'S256'
                or not re.fullmatch(r'[A-Za-z0-9_-]{43}', p.get('code_challenge', ''))):
            return volver(error='invalid_request', error_description='Se requiere código, recurso MCP y PKCE S256.')
        if SCOPE not in scope or set(scope) - {SCOPE, 'offline_access'}:
            return volver(error='invalid_scope')
        # Un desafío firmado por intento no invalida otras pestañas abiertas.
        from itsdangerous import URLSafeTimedSerializer, BadData
        firma = URLSafeTimedSerializer(acceso.clave_derivada(current_app.secret_key), salt='oauth-form-v1')
        nonce = session.setdefault('horarios_oauth_csrf', secrets.token_urlsafe(32))
        contexto = digest(request.query_string.decode('ascii'))
        csrf = firma.dumps([nonce, contexto])
        mensaje, estado = None, 200
        if request.method == 'POST':
            try:
                if firma.loads(request.form.get('csrf', ''), max_age=600) != [nonce, contexto]:
                    raise BadData('csrf')
            except BadData:
                return error('invalid_request', 'La pantalla venció. Volvé a conectar AppMitre.')
            if request.form.get('decision') == 'cancelar':
                return volver(error='access_denied')
            resultado = acceso.verificar_clave(request.remote_addr, request.form.get('clave'))
            if resultado == 'ok':
                payload = {'redirect_uri': p['redirect_uri'], 'challenge': p['code_challenge'],
                           'resource': recurso(), 'scope': ' '.join(scope)}
                with base() as con:
                    codigo = guardar(con, 'code', meta['client_id'], payload, CODE_SECONDS)
                return volver(code=codigo)
            mensaje = 'Esperá 15 minutos antes de reintentar.' if resultado == 'bloqueado' else 'Contraseña incorrecta.'
            estado = 429 if resultado == 'bloqueado' else 401
        return render_template_string(PAGINA, cliente=meta['client_name'], csrf=csrf, error=mensaje), estado

    @bp.post('/horarios/oauth/token')
    def token():
        with base() as con:
            # Serializa el canje: dos workers no pueden consumir el mismo código/refresh.
            con.execute('BEGIN IMMEDIATE')
            id_cliente = autenticar_cliente(con)
            if not id_cliente:
                return error('invalid_client', 'Cliente no válido.', 401)
            grant = request.form.get('grant_type')
            tipo, campo = ('code', 'code') if grant == 'authorization_code' else ('refresh', 'refresh_token')
            if grant not in ('authorization_code', 'refresh_token'):
                return error('unsupported_grant_type', 'Tipo de canje no admitido.')
            fila = leer(con, request.form.get(campo, ''), tipo)
            if not fila or fila['cliente'] != id_cliente:
                return error('invalid_grant', 'Autorización vencida o no válida.')
            payload = json.loads(fila['payload'])
            if request.form.get('resource', payload['resource']) != payload['resource']:
                return error('invalid_target', 'Recurso no válido.')
            if tipo == 'code':
                verifier = request.form.get('code_verifier', '')
                challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
                if (request.form.get('redirect_uri') != payload['redirect_uri']
                        or not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}', verifier)
                        or not hmac.compare_digest(challenge, payload['challenge'])):
                    return error('invalid_grant', 'Callback o PKCE no válido.')
            if request.form.get('scope', payload['scope']) != payload['scope']:
                return error('invalid_scope', 'No se pueden ampliar los permisos en el canje.')
            con.execute('DELETE FROM credenciales WHERE hash=?', (fila['hash'],))
            payload = {k: payload[k] for k in ('resource', 'scope')}
            return jsonify(emitir(con, id_cliente, payload))

    @bp.post('/horarios/oauth/revoke')
    def revocar():
        with base() as con:
            id_cliente = autenticar_cliente(con)
            if not id_cliente:
                return error('invalid_client', 'Cliente no válido.', 401)
            con.execute('DELETE FROM credenciales WHERE hash=? AND cliente=?',
                        (digest(request.form.get('token', '')), id_cliente))
        return '', 200
