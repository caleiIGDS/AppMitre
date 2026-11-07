"""Autorización OAuth para MCP sobre Flask: DCR, código con PKCE y renovación."""
import base64
from contextlib import contextmanager, closing
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time
from urllib.parse import urlencode, urlsplit, unquote

from itsdangerous import BadData, URLSafeTimedSerializer

from flask import jsonify, redirect, request, session

ACCESS_SECONDS = 3600
REFRESH_SECONDS = 180 * 86400
CODE_SECONDS = 180


def origen():
    return request.host_url.rstrip('/')


def digest(valor):
    return hashlib.sha256(valor.encode('utf-8')).hexdigest()


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


class OAuthMCP:
    def __init__(self, *, resource_path, issuer_path, oauth_path, scope, nombre, db_path,
                 generacion, pantalla, consentir, vigente, resource_aliases=()):
        self.resource_path = resource_path
        self.resource_aliases = tuple(resource_aliases)
        self.issuer_path = issuer_path
        self.oauth_path = oauth_path
        self.scope = scope
        self.nombre = nombre
        self.db_path = db_path
        self.generacion = generacion
        self.pantalla = pantalla
        self.consentir = consentir
        self.vigente = vigente

    def recurso(self):
        return origen() + self.resource_path

    def recurso_valido(self, recurso):
        return recurso in [origen() + p for p in (self.resource_path, *self.resource_aliases)]

    def issuer(self):
        return origen() + self.issuer_path

    def metadata_recurso(self):
        return jsonify(resource=self.recurso(), authorization_servers=[self.issuer()],
                       scopes_supported=[self.scope], bearer_methods_supported=['header'],
                       resource_name=self.nombre)

    def desafio(self):
        return (f'Bearer resource_metadata="{origen()}/.well-known/oauth-protected-resource'
                f'{self.resource_path}", scope="{self.scope}"')

    @contextmanager
    def base(self):
        ruta = self.db_path()
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


    def guardar(self, con, tipo, cliente, payload, duracion):
        valor = secrets.token_urlsafe(40)
        con.execute('INSERT INTO credenciales VALUES (?,?,?,?,?,?)',
                    (digest(valor), tipo, cliente, time.time() + duracion,
                     self.generacion(), json.dumps(payload)))
        return valor


    def leer(self, con, valor, tipo, consumir=False):
        if not isinstance(valor, str) or len(valor) > 2048:
            return None
        fila = con.execute('SELECT * FROM credenciales WHERE hash=? AND tipo=?', (digest(valor), tipo)).fetchone()
        if not fila or fila['vence'] < time.time() or not hmac.compare_digest(fila['generacion'], self.generacion()):
            return None
        if consumir:
            con.execute('DELETE FROM credenciales WHERE hash=?', (fila['hash'],))
        return fila


    def autorizado(self):
        return self.identidad_autorizada() is not None

    def identidad_autorizada(self):
        cabecera = request.headers.get('Authorization', '')
        esquema, _, valor = cabecera.partition(' ')
        if esquema.lower() != 'bearer' or not valor:
            return None
        with self.base() as con:
            fila = self.leer(con, valor, 'access')
        if not fila:
            return None
        p = json.loads(fila['payload'])
        if (self.recurso_valido(p.get('resource')) and self.scope in p.get('scope', '').split()
                and self.vigente(p.get('identidad'))):
            return p.get('identidad')
        return None


    def emitir(self, con, id_cliente, payload):
        return {'access_token': self.guardar(con, 'access', id_cliente, payload, ACCESS_SECONDS),
                'token_type': 'Bearer', 'expires_in': ACCESS_SECONDS, 'scope': payload['scope'],
                'refresh_token': self.guardar(con, 'refresh', id_cliente, payload, REFRESH_SECONDS)}


    def registrar(self, bp):
        if self.resource_path == '/mcp':
            bp.add_url_rule('/.well-known/oauth-protected-resource', 'oauth_metadata_raiz',
                            lambda: self.metadata_recurso())
        bp.add_url_rule('/.well-known/oauth-protected-resource' + self.resource_path,
                        'oauth_metadata_recurso', self.metadata_recurso)
        for indice, ruta in enumerate(self.resource_aliases):
            def metadata_alias(ruta=ruta):
                return jsonify(resource=origen() + ruta, authorization_servers=[self.issuer()],
                               scopes_supported=[self.scope], bearer_methods_supported=['header'],
                               resource_name=self.nombre)
            bp.add_url_rule('/.well-known/oauth-protected-resource' + ruta,
                            f'oauth_metadata_alias_{indice}', metadata_alias)

        @bp.get('/.well-known/oauth-authorization-server' + self.issuer_path)
        def metadata_autorizacion():
            o = origen()
            return jsonify(issuer=self.issuer(), authorization_endpoint=o+self.oauth_path+'/authorize',
                           token_endpoint=o+self.oauth_path+'/token', registration_endpoint=o+self.oauth_path+'/register',
                           revocation_endpoint=o+self.oauth_path+'/revoke', response_types_supported=['code'],
                           grant_types_supported=['authorization_code', 'refresh_token'],
                           code_challenge_methods_supported=['S256'], scopes_supported=[self.scope, 'offline_access'],
                           token_endpoint_auth_methods_supported=['none', 'client_secret_basic', 'client_secret_post'],
                           authorization_response_iss_parameter_supported=True)

        @bp.post(self.oauth_path + '/register')
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
            with self.base() as con:
                con.execute('INSERT INTO clientes VALUES (?,?,?)',
                            (meta['client_id'], json.dumps(meta), digest(secreto) if secreto else None))
            return jsonify({**meta, **({'client_secret': secreto, 'client_secret_expires_at': 0} if secreto else {})}), 201

        @bp.route(self.oauth_path + '/authorize', methods=['GET', 'POST'])
        def autorizar():
            p = request.args
            with self.base() as con:
                _, meta = cliente(con, p.get('client_id', ''))
            # Nunca redirigir a una dirección no registrada, tampoco para informar errores.
            if not meta or p.get('redirect_uri') not in meta['redirect_uris']:
                return error('invalid_request', 'Cliente o callback desconocido.')

            def volver(**valores):
                q = urlencode({**valores, 'state': p.get('state', ''), 'iss': self.issuer()})
                return redirect(p['redirect_uri'] + ('&' if '?' in p['redirect_uri'] else '?') + q)

            scope = p.get('scope', self.scope).split()
            if (p.get('response_type') != 'code' or not self.recurso_valido(p.get('resource'))
                    or p.get('code_challenge_method') != 'S256'
                    or not re.fullmatch(r'[A-Za-z0-9_-]{43}', p.get('code_challenge', ''))):
                return volver(error='invalid_request', error_description='Se requiere código, recurso MCP y PKCE S256.')
            if self.scope not in scope or set(scope) - {self.scope, 'offline_access'}:
                return volver(error='invalid_scope')
            # Un desafío firmado por intento no invalida otras pestañas abiertas.
            firma = URLSafeTimedSerializer(self.generacion(), salt='oauth-form-v1')
            nonce = session.setdefault(bp.name + '_oauth_csrf', secrets.token_urlsafe(32))
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
                identidad, mensaje, estado = self.consentir()
                if identidad is not None:
                    payload = {'redirect_uri': p['redirect_uri'], 'challenge': p['code_challenge'],
                               'resource': p['resource'], 'scope': ' '.join(scope), 'identidad': identidad,
                               'autorizacion': secrets.token_urlsafe(24)}
                    with self.base() as con:
                        codigo = self.guardar(con, 'code', meta['client_id'], payload, CODE_SECONDS)
                    return volver(code=codigo)
            return self.pantalla(meta['client_name'], csrf, mensaje), estado

        @bp.post(self.oauth_path + '/token')
        def token():
            with self.base() as con:
                # Serializa el canje: dos workers no pueden consumir el mismo código/refresh.
                con.execute('BEGIN IMMEDIATE')
                id_cliente = autenticar_cliente(con)
                if not id_cliente:
                    return error('invalid_client', 'Cliente no válido.', 401)
                grant = request.form.get('grant_type')
                tipo, campo = ('code', 'code') if grant == 'authorization_code' else ('refresh', 'refresh_token')
                if grant not in ('authorization_code', 'refresh_token'):
                    return error('unsupported_grant_type', 'Tipo de canje no admitido.')
                fila = self.leer(con, request.form.get(campo, ''), tipo)
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
                if not self.vigente(payload.get('identidad')):
                    return error('invalid_grant', 'El permiso de la cuenta ya no está vigente.')
                if request.form.get('scope', payload['scope']) != payload['scope']:
                    return error('invalid_scope', 'No se pueden ampliar los permisos en el canje.')
                con.execute('DELETE FROM credenciales WHERE hash=?', (fila['hash'],))
                payload.pop('challenge', None)
                payload.pop('redirect_uri', None)
                return jsonify(self.emitir(con, id_cliente, payload))

        @bp.post(self.oauth_path + '/revoke')
        def revocar():
            with self.base() as con:
                con.execute('BEGIN IMMEDIATE')
                id_cliente = autenticar_cliente(con)
                if not id_cliente:
                    return error('invalid_client', 'Cliente no válido.', 401)
                valor = digest(request.form.get('token', ''))
                fila = con.execute('SELECT payload FROM credenciales WHERE hash=? AND cliente=?',
                                   (valor, id_cliente)).fetchone()
                autorizacion = json.loads(fila['payload']).get('autorizacion') if fila else None
                if autorizacion:
                    con.execute("DELETE FROM credenciales WHERE cliente=? AND json_extract(payload, '$.autorizacion')=?",
                                (id_cliente, autorizacion))
                else:
                    con.execute('DELETE FROM credenciales WHERE hash=? AND cliente=?', (valor, id_cliente))
            return '', 200
