"""El MCP puede entregar valores, con la base de legajos aislada de sus escrituras."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import timedelta
import base64
import hashlib
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from flask import Flask

import accesos
from config import ahora
import salidas
import salidas_mcp


class SalidasMCP(unittest.TestCase):
    ruta = '/gestion/areas/salidas'
    campos = {
        'comunes.fecha_salida': {'tipo': 'date', 'label': 'Fecha de salida'},
        'IV.actividades': {'tipo': 'textarea', 'label': 'Actividades'},
        'personas': {'tipo': 'personas', 'label': 'Nómina'},
    }

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        raiz = Path(tmp.name)
        for parche in (
            patch.object(salidas, 'DB_PATH', str(raiz / 'salidas.db')),
            patch.object(salidas, 'PDF_DIR', str(raiz / 'pdf')),
            patch.object(accesos, 'DB_PATH', str(raiz / 'accesos.db')),
        ):
            parche.start()
            self.addCleanup(parche.stop)
        hoy = ahora()
        with closing(salidas.conectar()) as con, con:
            con.executescript(salidas.SCHEMA)
            con.executemany('''INSERT INTO salidas
                (id, fecha_creacion, vigencia_hasta, datos_json, token, archivado)
                VALUES (?, ?, ?, '{}', ?, ?)''',
                [(1, hoy.isoformat(), (hoy + timedelta(days=1)).isoformat(), 'privado', 0),
                 (2, hoy.isoformat(), (hoy + timedelta(days=1)).isoformat(), 'privado-2', 0),
                 (3, hoy.isoformat(), (hoy + timedelta(days=1)).isoformat(), 'archivada', 1)])
        with closing(accesos.conectar()) as con, con:
            con.executescript(accesos.SCHEMA)
            con.executemany('INSERT INTO dispositivos (id, nombre, perfil, permisos, alta) VALUES (?,?,?,?,?)',
                            [(1, 'Edición', 'custom', '["salidas.leer","salidas.editar"]', hoy.isoformat()),
                             (2, 'Lectura', 'custom', '["salidas.leer"]', hoy.isoformat())])
        self.app = Flask(__name__, root_path=str(Path(salidas.__file__).parent))
        self.app.config.update(TESTING=True, SECRET_KEY='secreto-de-prueba')
        self.app.register_blueprint(salidas.bp, url_prefix=self.ruta)
        self.app.register_blueprint(salidas_mcp.bp)
        self.app.add_url_rule(self.ruta + '/normativa', 'normativa_visor', lambda: '')
        self.editor = self.cliente(1)
        self.anonimo = self.app.test_client()

    def cliente(self, id):
        cliente = self.app.test_client()
        with cliente.session_transaction() as ses:
            ses['acceso'] = {'tipo': 'dispositivo', 'id': id}
        return cliente

    def mcp(self, metodo, params=None, **kwargs):
        return self.app.test_client().post('/mcp/salidas', json={
            'jsonrpc': '2.0', 'id': 1, 'method': metodo, 'params': params or {}}, **kwargs)

    def tool(self, nombre, **args):
        return self.mcp('tools/call', {'name': nombre, 'arguments': args}).json['result']['structuredContent']

    def oauth(self, cliente=None, inventarios=False, recurso='/mcp/gestion', origen='http://localhost'):
        raiz = '/salidas/oauth'
        app = self.anonimo
        callback = 'https://cliente.example/callback'
        registro = app.post(raiz + '/register', json={'redirect_uris': [callback],
                            'token_endpoint_auth_method': 'none'})
        self.assertEqual(registro.status_code, 201)
        cliente_id = registro.json['client_id']
        verificador = 'v' * 43
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verificador.encode()).digest()).decode().rstrip('=')
        navegador = cliente or self.editor
        args = {'client_id': cliente_id, 'redirect_uri': callback, 'response_type': 'code',
                'resource': 'http://localhost' + recurso, 'scope': 'salidas:editar offline_access',
                'code_challenge': challenge, 'code_challenge_method': 'S256'}
        consentimiento = navegador.get(raiz + '/authorize', query_string=args)
        self.assertEqual(consentimiento.headers['Referrer-Policy'], 'same-origin')
        csrf = re.search(r'name="csrf" value="([^"]+)"', consentimiento.text)[1]
        autorizado = navegador.post(raiz + '/authorize', query_string=args,
                                     headers={'Origin': origen},
                                     data={'csrf': csrf, 'decision': 'autorizar', **({'inventarios': 'autorizar'} if inventarios else {})})
        if autorizado.status_code != 302:
            return autorizado, cliente_id
        codigo = parse_qs(urlsplit(autorizado.location).query)['code'][0]
        tokens = app.post(raiz + '/token', data={'client_id': cliente_id, 'grant_type': 'authorization_code',
                          'redirect_uri': callback, 'code_verifier': verificador, 'code': codigo,
                          'resource': args['resource']})
        return tokens, cliente_id

    def test_formulario_oauth_conserva_origen_y_rechaza_origen_opaco_o_ajeno(self):
        tokens, _ = self.oauth()
        self.assertEqual(tokens.status_code, 200)
        for origen in ('null', 'https://otro.example'):
            respuesta, _ = self.oauth(origen=origen)
            self.assertEqual(respuesta.status_code, 403)
        respuesta = self.mcp('tools/list')
        self.assertEqual(respuesta.headers['Referrer-Policy'], 'no-referrer')

    def tool_con_token(self, token, nombre, **args):
        return self.mcp('tools/call', {'name': nombre, 'arguments': args},
                        headers={'Authorization': 'Bearer ' + token})

    def pestana(self, datos, id=1, cliente=None, cabeceras=None):
        return (cliente or self.editor).post(f'{self.ruta}/{id}/agente-formulario', json=datos,
                                            headers={'X-Mitre': '1'} if cabeceras is None else cabeceras)

    def iniciar(self):
        r = self.pestana({'campos': self.campos})
        self.assertEqual(r.status_code, 200)
        return r.json

    def legajos(self):
        with closing(salidas.conectar()) as con:
            return [tuple(f) for f in con.execute('SELECT * FROM salidas ORDER BY id')]

    def test_descubrimiento_y_nueve_anexos(self):
        tools = self.mcp('tools/list').json['result']['tools']
        self.assertEqual({t['name'] for t in tools},
                         {'listar_anexos', 'leer_anexo', 'consultar_campos', 'rellenar_formulario',
                          'buscar_salidas', 'consultar_salida', 'esquema_legajo', 'crear_salida', 'editar_salida',
                          'listar_inventarios', 'consultar_inventario', 'consultar_recurso', 'pedir_fotos_recursos'})
        listado = self.tool('listar_anexos')['anexos']
        self.assertEqual([a['anexo'] for a in listado], list(salidas_mcp.ANEXOS))
        for anexo in salidas_mcp.ANEXOS:
            with self.subTest(anexo=anexo):
                r = self.tool('leer_anexo', anexo=anexo)
                self.assertGreater(len(r['formulario']), 500)
                self.assertEqual('esquema_papel' in r, anexo in salidas.ANEXOS_NUMEROS)
        self.assertEqual(self.mcp('tools/list', headers={'Origin': 'https://otro.example'}).status_code, 403)

    def test_permisos_y_salida_activa(self):
        self.assertEqual(self.pestana({'campos': self.campos}, cliente=self.anonimo).status_code, 302)
        self.assertEqual(self.pestana({'campos': self.campos}, cliente=self.cliente(2)).status_code, 403)
        self.assertEqual(self.pestana({'campos': self.campos}, cabeceras={}).status_code, 400)
        self.assertEqual(self.pestana({'campos': self.campos}, id=3).status_code, 404)
        self.assertEqual(self.pestana({'campos': self.campos}, id=999).status_code, 404)
        self.assertEqual(self.anonimo.post(self.ruta + '/api/guardar', json={}).status_code, 302)
        r = self.mcp('tools/call', {'name': 'crear_salida'})
        self.assertEqual(r.status_code, 401)
        self.assertIn('/.well-known/oauth-protected-resource/mcp/gestion', r.headers['WWW-Authenticate'])

    def test_ruta_gestion_y_compatibilidad_salidas(self):
        for ruta in ('/mcp/gestion', '/mcp/salidas'):
            metadata = self.anonimo.get('/.well-known/oauth-protected-resource' + ruta)
            self.assertEqual(metadata.json['resource'], 'http://localhost' + ruta)
            tokens, _ = self.oauth(recurso=ruta)
            self.assertEqual(tokens.status_code, 200, tokens.json)
            for destino in ('/mcp/gestion', '/mcp/salidas'):
                respuesta = self.anonimo.post(destino, json={
                    'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                    'params': {'name': 'buscar_salidas', 'arguments': {}}},
                    headers={'Authorization': 'Bearer ' + tokens.json['access_token']})
                self.assertEqual(respuesta.status_code, 200)
                self.assertFalse(respuesta.json['result'].get('isError', False))

    def test_clave_exclusiva_solo_por_encabezado_y_si_esta_configurada(self):
        clave = 'mitre_salidas_' + 'a' * 43
        with patch.dict('os.environ', {'SALIDAS_MCP_TOKEN_SHA256': ''}):
            self.assertEqual(self.tool_con_token(clave, 'esquema_legajo').status_code, 401)
        huella = hashlib.sha256(clave.encode('ascii')).hexdigest()
        with patch.dict('os.environ', {'SALIDAS_MCP_TOKEN_SHA256': huella}):
            self.assertEqual(self.tool_con_token(clave, 'esquema_legajo').status_code, 200)
            self.assertEqual(self.tool_con_token(clave[:-1] + 'b', 'esquema_legajo').status_code, 401)
            r = self.mcp('tools/call', {'name': 'esquema_legajo'}, query_string={'token': clave})
            self.assertEqual(r.status_code, 401)

    def test_oauth_revoca_permiso_del_dispositivo_y_limita_lectura(self):
        tokens, _ = self.oauth(self.cliente(2))
        self.assertEqual(tokens.status_code, 403)
        tokens, cliente = self.oauth()
        self.assertEqual(tokens.status_code, 200, tokens.json)
        token = tokens.json['access_token']
        self.assertEqual(self.tool_con_token(token, 'buscar_salidas').status_code, 200)
        with closing(accesos.conectar()) as con, con:
            con.execute("UPDATE dispositivos SET permisos='[\"salidas.leer\"]' WHERE id=1")
        self.assertEqual(self.tool_con_token(token, 'buscar_salidas').status_code, 401)
        refresh = self.anonimo.post('/salidas/oauth/token', data={'client_id': cliente,
            'grant_type': 'refresh_token', 'refresh_token': tokens.json['refresh_token']})
        self.assertEqual(refresh.json['error'], 'invalid_grant')

    def test_crear_reintentar_editar_y_rechazar_revision_anterior(self):
        tokens, cliente = self.oauth()
        token = tokens.json['access_token']

        def llamar(nombre, **args):
            r = self.tool_con_token(token, nombre, **args)
            self.assertEqual(r.status_code, 200, r.text)
            return r.json['result']['structuredContent']

        campos = {'comunes.denominacion_proyecto': 'Olimpíada de prueba',
                  'comunes.fecha_salida': '2026-11-15', 'IV.actividades': 'Acreditación',
                  'personas': [{'rol': 'estudiante', 'apellido_nombre': 'Persona sintética'}]}
        operacion = 'un-id-estable-de-prueba'
        alta = llamar('crear_salida', operacion=operacion, campos=campos)
        self.assertEqual(alta['estado'], 'creada', alta)
        id = alta['id']
        self.assertEqual(llamar('crear_salida', operacion=operacion, campos=campos)['id'], id)
        self.assertEqual(llamar('buscar_salidas', consulta='olimpiada')['total'], 1)
        original = llamar('consultar_salida', id=id)
        self.assertTrue(Path(salidas._ruta_pdf(id, 'V')).read_bytes().startswith(b'%PDF-'))
        cambios = {'IV.actividades': 'Prueba escrita', 'personas': original['campos']['personas']}
        self.assertEqual(llamar('editar_salida', id=id, revision=original['revision'], campos=cambios)['estado'], 'editada')
        self.assertIn('error', llamar('editar_salida', id=id, revision=original['revision'], campos=cambios))
        web = self.editor.post(self.ruta + '/api/guardar', json={
            '_id_editar': id, '_revision_editar': original['revision']})
        self.assertEqual(web.status_code, 409)
        actual = llamar('consultar_salida', id=id)
        self.assertEqual(actual['campos']['comunes.fecha_salida'], '2026-11-15')
        self.assertEqual(actual['campos']['IV.actividades'], 'Prueba escrita')
        self.assertIn('error', llamar('editar_salida', id=id, revision=actual['revision'],
                                      campos={'IX.firma_sello_director': 'No corresponde'}))
        r = self.anonimo.post('/salidas/oauth/revoke', data={'client_id': cliente,
                               'token': tokens.json['refresh_token']})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.tool_con_token(token, 'consultar_salida', id=id).status_code, 401)

    def test_entrega_vinculada_al_receptor_sin_guardado(self):
        antes = self.legajos()
        par = self.iniciar()
        codigo, receptor = par['codigo'], par['receptor']
        recibir = {'accion': 'recibir', 'receptor': receptor}
        self.assertEqual(self.pestana(recibir).json, {'estado': 'esperando'})
        self.assertEqual(self.tool('consultar_campos', codigo=codigo)['campos'], self.campos)
        self.assertIn('error', self.tool('consultar_campos', codigo=receptor))
        self.assertIn('error', self.tool('rellenar_formulario', codigo=codigo, campos={'_id_editar': 2}))
        self.assertIn('error', self.tool('rellenar_formulario', codigo=codigo, campos={'comunes.fecha_salida': '2026-02-30'}))
        valores = {'IV.actividades': 'Visita guiada', 'comunes.fecha_salida': '2026-11-25',
                   'personas': [{'rol': 'docente_titular', 'apellido_nombre': 'Persona de prueba'}]}
        with ThreadPoolExecutor(max_workers=2) as pool:
            resultados = list(pool.map(lambda _: self.tool('rellenar_formulario', codigo=codigo, campos=valores), range(2)))
        self.assertEqual(sum(r.get('estado') == 'enviado_para_revision' for r in resultados), 1)
        self.assertEqual(self.pestana(recibir, id=2).json, {'estado': 'vencido'})
        self.assertEqual(self.pestana({**recibir, 'receptor': codigo}).json, {'estado': 'vencido'})
        self.assertEqual(self.pestana(recibir).json, {'estado': 'recibido', 'valores': valores})
        self.assertEqual(self.pestana(recibir).json, {'estado': 'vencido'})
        self.assertEqual(self.legajos(), antes)
        self.assertFalse(Path(salidas.PDF_DIR).exists())

    def test_vencimiento_y_cancelacion(self):
        par = self.iniciar()
        self.assertEqual(self.pestana({'accion': 'cancelar', 'receptor': par['receptor']}).json,
                         {'estado': 'cancelado'})
        self.assertIn('error', self.tool('consultar_campos', codigo=par['codigo']))
        par = self.iniciar()
        ruta = Path(salidas.DB_PATH).with_name('salidas_entregas_mcp.db')
        with closing(sqlite3.connect(ruta)) as con, con:
            con.execute('UPDATE entregas SET vence=0')
        self.assertIn('error', self.tool('consultar_campos', codigo=par['codigo']))
        with closing(sqlite3.connect(ruta)) as con:
            self.assertEqual(con.execute('SELECT count(*) FROM entregas').fetchone()[0], 0)
