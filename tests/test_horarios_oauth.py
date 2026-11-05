"""OAuth real con SQLite temporal: callbacks, PKCE, renovación y PDF por MCP."""
import base64
import hashlib
import html
import re
import sqlite3
import time
import unittest
from urllib.parse import urlencode, urlsplit, parse_qs
from unittest.mock import patch

import test_horarios_mcp as fixtures

oauth = fixtures.mcp.oauth


class OAuthHorarios(unittest.TestCase):
    parche = fixtures.MCPHorarios.parche
    insertar = fixtures.MCPHorarios.insertar
    clase = fixtures.MCPHorarios.clase
    personal = fixtures.MCPHorarios.personal
    preceptor = fixtures.MCPHorarios.preceptor
    consultar = fixtures.MCPHorarios.consultar
    rpc = fixtures.MCPHorarios.rpc
    llamar = fixtures.MCPHorarios.llamar
    setUp = fixtures.MCPHorarios.setUp
    callback = 'https://chatgpt.com/connector_platform_oauth_redirect'
    verifier = 'v' * 64

    def registrar(self, metodo='none'):
        r = self.client.post('/horarios/oauth/register', json={
            'client_name': 'Cliente de prueba', 'redirect_uris': [self.callback],
            'token_endpoint_auth_method': metodo})
        self.assertEqual(r.status_code, 201, r.data)
        return r.json

    def formulario(self, cliente, **cambios):
        challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).decode().rstrip('=')
        p = {'client_id': cliente['client_id'], 'redirect_uri': self.callback, 'state': 'estado-aleatorio',
             'response_type': 'code', 'resource': 'http://localhost/mcp',
             'scope': 'horarios:leer offline_access', 'code_challenge': challenge, 'code_challenge_method': 'S256', **cambios}
        return '/horarios/oauth/authorize?' + urlencode(p)

    def codigo(self, cliente):
        url = self.formulario(cliente)
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        csrf = html.unescape(re.search(r'name="csrf" value="([^"]+)"', r.text)[1])
        r = self.client.post(url, data={'csrf': csrf, 'clave': 'clave-sintética-ñ', 'decision': 'autorizar'})
        self.assertEqual(r.status_code, 302, r.data)
        q = parse_qs(urlsplit(r.location).query)
        self.assertEqual(q['state'], ['estado-aleatorio'])
        self.assertEqual(q['iss'], ['http://localhost'])
        return q['code'][0]

    def canjear(self, cliente, codigo, **cambios):
        return self.client.post('/horarios/oauth/token', data={
            'client_id': cliente['client_id'], 'grant_type': 'authorization_code', 'code': codigo,
            'code_verifier': self.verifier, 'redirect_uri': self.callback, 'resource': 'http://localhost/mcp',
            **({'client_secret': cliente['client_secret']} if 'client_secret' in cliente else {}), **cambios})

    def conectar(self):
        c = self.registrar()
        r = self.canjear(c, self.codigo(c))
        self.assertEqual(r.status_code, 200, r.data)
        return c, r.json

    def test_descubrimiento_y_desafio_para_herramientas_sin_clave(self):
        meta = self.client.get('/.well-known/oauth-authorization-server').json
        self.assertIn('refresh_token', meta['grant_types_supported'])
        self.assertEqual(meta['code_challenge_methods_supported'], ['S256'])
        self.assertTrue(meta['authorization_response_iss_parameter_supported'])
        for ruta in ('/.well-known/oauth-protected-resource', '/.well-known/oauth-protected-resource/mcp'):
            self.assertEqual(self.client.get(ruta).json['resource'], 'http://localhost/mcp')
        r = self.rpc('tools/call', {'name': 'listar_catalogos', 'arguments': {'consulta': {}}})
        self.assertEqual(r.status_code, 401)
        self.assertIn('resource_metadata=', r.headers['WWW-Authenticate'])

    def test_pkce_callback_csrf_y_codigo_de_un_uso(self):
        c = self.registrar()
        self.assertEqual(self.client.get(self.formulario(c, redirect_uri='https://intruso.example')).status_code, 400)
        r = self.client.get(self.formulario(c, code_challenge_method='plain'))
        self.assertEqual(parse_qs(urlsplit(r.location).query)['error'], ['invalid_request'])
        self.assertEqual(self.client.post(self.formulario(c), data={'clave': 'clave-sintética-ñ'}).status_code, 400)
        code = self.codigo(c)
        self.assertEqual(self.canjear(c, code, code_verifier='x'*64).status_code, 400)
        self.assertEqual(self.canjear(c, code, resource='https://otro.example/mcp').status_code, 400)
        self.assertEqual(self.canjear(c, code).status_code, 200)
        self.assertEqual(self.canjear(c, code).status_code, 400)

    def test_renovar_reconectar_y_rotar_contrasenia(self):
        c, tokens = self.conectar()
        def llamada(token):
            return self.rpc('tools/call', {'name': 'listar_catalogos', 'arguments': {'consulta': {}}},
                            Authorization='Bearer ' + token)
        self.assertFalse(llamada(tokens['access_token']).json['result']['isError'])
        # Nueva sesión de navegador: la autorización viaja en el cliente MCP, no en cookies.
        self.client = self.app.test_client()
        self.assertEqual(llamada(tokens['access_token']).status_code, 200)
        p = {'grant_type': 'refresh_token', 'refresh_token': tokens['refresh_token'], 'client_id': c['client_id']}
        renovado = self.client.post('/horarios/oauth/token', data=p)
        self.assertEqual(renovado.status_code, 200, renovado.data)
        self.assertNotEqual(renovado.json['refresh_token'], tokens['refresh_token'])
        self.assertEqual(self.client.post('/horarios/oauth/token', data=p).status_code, 400)
        with patch.object(time, 'time', return_value=time.time()+3700):
            self.assertEqual(llamada(tokens['access_token']).status_code, 401)
        with patch.object(fixtures.acceso, '_clave', return_value='rotada'):
            self.assertEqual(llamada(renovado.json['access_token']).status_code, 401)
        self.assertEqual(self.client.get('/app-horarios/api/datos',
                         headers={'Authorization': 'Bearer '+tokens['access_token']}).status_code, 401)

    def test_clientes_confidenciales_y_revocacion(self):
        for metodo in ('client_secret_post', 'client_secret_basic'):
            c = self.registrar(metodo)
            code = self.codigo(c)
            self.assertEqual(self.canjear(c, code, client_secret='otra').status_code, 401)
            if metodo == 'client_secret_post':
                r = self.canjear(c, code)
            else:
                basic = base64.b64encode(f"{c['client_id']}:{c['client_secret']}".encode()).decode()
                r = self.client.post('/horarios/oauth/token', data={
                    'grant_type': 'authorization_code', 'code': code, 'code_verifier': self.verifier,
                    'redirect_uri': self.callback, 'resource': 'http://localhost/mcp'},
                    headers={'Authorization': 'Basic '+basic})
            self.assertEqual(r.status_code, 200, r.data)
            valor = r.json['refresh_token']
            headers = {'Authorization': 'Basic '+base64.b64encode(
                       f"{c['client_id']}:{c['client_secret']}".encode()).decode()} if metodo.endswith('basic') else {}
            p = {'client_id': c['client_id'], 'token': valor}
            if not headers:
                p['client_secret'] = c['client_secret']
            self.assertEqual(self.client.post('/horarios/oauth/revoke', data=p, headers=headers).status_code, 200)
            with oauth.base() as con:
                self.assertIsNone(oauth.leer(con, valor, 'refresh'))

    def test_pdf_es_archivo_y_se_lee_desde_mcp_sin_http_externo(self):
        _, tokens = self.conectar()
        auth = {'Authorization': 'Bearer '+tokens['access_token']}
        r = self.rpc('tools/call', {'name': 'obtener_pdf', 'arguments': {'consulta': {'tipo': 'curso', 'valor': '3 A'}}}, **auth)
        resultado = r.json['result']
        self.assertFalse(resultado['isError'], resultado)
        recurso = resultado['content'][1]
        self.assertEqual(recurso['type'], 'resource_link')
        self.assertTrue(recurso['uri'].endswith('.pdf'))
        r = self.rpc('resources/read', {'uri': recurso['uri']}, **auth)
        self.assertTrue(base64.b64decode(r.json['result']['contents'][0]['blob']).startswith(b'%PDF-'))
        descarga = self.client.get(recurso['uri'])
        self.assertIn('attachment', descarga.headers['Content-Disposition'])
        self.assertEqual(self.client.head(recurso['uri']).status_code, 200)
        self.assertEqual(self.rpc('resources/read', {'uri': 'https://intruso.example/x'}, **auth).json['error']['code'], -32002)
        with patch('itsdangerous.timed.time.time', return_value=9999999999):
            self.assertEqual(self.client.get(recurso['uri']).status_code, 403)

    def test_registro_rechaza_callbacks_invalidos_y_no_guarda_credenciales_crudas(self):
        for uri in ('http://externo.example/cb', 'javascript:alert(1)', 'https://x.example/#x', 'https://u:p@x.example/cb'):
            r = self.client.post('/horarios/oauth/register', json={'redirect_uris': [uri]})
            self.assertEqual(r.status_code, 400)
        c, tokens = self.conectar()
        with oauth.base() as con:
            contenido = '\n'.join(con.iterdump())
        for secreto in ('clave-sintética-ñ', tokens['access_token'], tokens['refresh_token']):
            self.assertNotIn(secreto, contenido)


if __name__ == '__main__':
    unittest.main()
