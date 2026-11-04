"""MCP/JSON-RPC y referencias PDF sobre la misma base sintética de las consultas."""
import json
import unittest
from unittest.mock import patch

import test_horarios_consultas as fixtures

mcp = fixtures.cargar('mcp')
acceso = fixtures.acceso


class MCPHorarios(unittest.TestCase):
    parche = fixtures.ConsultasHorarios.parche
    insertar = fixtures.ConsultasHorarios.insertar
    clase = fixtures.ConsultasHorarios.clase
    personal = fixtures.ConsultasHorarios.personal
    preceptor = fixtures.ConsultasHorarios.preceptor
    consultar = fixtures.ConsultasHorarios.consultar

    def setUp(self):
        fixtures.ConsultasHorarios.setUp(self)
        self.app.register_blueprint(mcp.bp_mcp)

    def rpc(self, metodo, params=None, **otros):
        return self.client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': metodo,
                                             'params': params or {}},
                                headers={'Accept': 'application/json, text/event-stream', **otros})

    def llamar(self, nombre, filtros=None, clave='clave-sintética-ñ'):
        return self.rpc('tools/call', {'name': nombre, 'arguments': {'clave': clave, 'consulta': filtros or {}}}).get_json()['result']

    def test_descubrimiento_publico_y_negociacion_no_exponen_datos_ni_clave(self):
        for version in (*mcp.VERSIONES, '2099-01-01'):
            r = self.rpc('initialize', {'protocolVersion': version, 'capabilities': {},
                                       'clientInfo': {'name': 'prueba', 'version': '1'}})
            self.assertEqual(r.status_code, 200)
            contenido = r.get_json()['result']
            self.assertEqual(contenido['protocolVersion'], version if version in mcp.VERSIONES else mcp.VERSIONES[-1])
            self.assertEqual(contenido['capabilities'], {'tools': {'listChanged': False}})
        r = self.rpc('tools/list')
        tools = r.get_json()['result']['tools']
        self.assertEqual({t['name'] for t in tools},
                         {c['nombre'] for c in mcp.CONTRATOS.values()} | {'obtener_pdf'})
        for tool in tools:
            self.assertEqual(tool['inputSchema']['required'], ['clave', 'consulta'])
            self.assertTrue(tool['annotations']['readOnlyHint'])
            self.assertNotIn('anyOf', tool['inputSchema'])  # Compatibilidad con clientes de varios proveedores.
        self.assertNotIn('PEREZ ANA', r.get_data(as_text=True))
        self.assertNotIn('clave-sintética-ñ', r.get_data(as_text=True))
        self.assertEqual(self.client.get('/app-horarios/api/datos').status_code, 401)

    def test_transporte_json_sin_sesiones_y_limites(self):
        self.assertEqual(self.client.get('/mcp').status_code, 405)
        self.assertEqual(self.client.delete('/mcp').status_code, 405)
        self.assertEqual(self.rpc('ping').get_json()['result'], {})
        self.assertEqual(self.rpc('desconocido').get_json()['error']['code'], -32601)
        self.assertEqual(self.rpc('tools/list', **{'MCP-Protocol-Version': '2099'}).status_code, 400)
        self.assertEqual(self.rpc('tools/list', Origin='https://otro.example').status_code, 403)
        self.assertEqual(self.rpc('tools/list', Origin='https://chatgpt.com').status_code, 200)
        self.assertEqual(self.rpc('tools/list', Origin='https://claude.ai').status_code, 200)
        self.assertEqual(self.client.post('/mcp', data='{}').status_code, 415)
        self.assertEqual(self.client.post('/mcp', json={}, headers={'Accept': 'text/plain'}).status_code, 406)
        r = self.client.post('/mcp', data='{', content_type='application/json', headers={'Accept': 'application/json'})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()['error']['code'], -32700)
        for mensaje in ([], {'jsonrpc': '2.0', 'id': True, 'method': 'ping'},
                        {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': []}):
            self.assertEqual(self.client.post('/mcp', json=mensaje, headers={'Accept': 'application/json'}).status_code, 400)
        self.assertEqual(self.client.post('/mcp', json={'jsonrpc':'2.0', 'method':'notifications/initialized'},
                                        headers={'Accept':'application/json'}).status_code, 202)
        self.assertEqual(self.client.post('/mcp', data=' '*65537, content_type='application/json',
                                        headers={'Accept':'application/json'}).status_code, 413)
        self.assertEqual(self.rpc('initialize').get_json()['error']['code'], -32602)

    def test_mismos_json_que_api_y_paginacion(self):
        ejemplos = [('catalogos', 'listar_catalogos', {'incluir':['nombres','roles']}),
                    ('personas', 'buscar_personas', {'multiples_roles':True}),
                    ('horarios', 'consultar_horarios', {'tipo':'curso','valores':['3 A']}),
                    ('preceptores', 'consultar_preceptores', {})]
        for operacion, tool, filtros in ejemplos:
            resultado = self.llamar(tool, filtros)
            self.assertFalse(resultado['isError'])
            self.assertEqual(resultado['structuredContent'], self.consultar(operacion, filtros))
            self.assertEqual(json.loads(resultado['content'][0]['text']), resultado['structuredContent'])
        import sys
        from test_horarios_consultas import PAQUETE
        self.parche(sys.modules[f'{PAQUETE}.consultas.personas'], 'MAX_PERSONAS', 1)
        p = {'nombre':'PEREZ'}
        primera = self.llamar('buscar_personas', p)['structuredContent']
        segunda = self.llamar('buscar_personas', {**p, 'cursor':primera['siguiente']})['structuredContent']
        self.assertEqual(segunda['personas'][0]['nombre'], 'PEREZ JUAN')
        self.assertNotIn('siguiente', segunda)

    def test_clave_en_cada_llamada_sin_sesion_y_limite_compartido(self):
        with self.client.session_transaction() as s:
            s[acceso.SESSION_FLAG] = True
        self.assertEqual(self.llamar('listar_catalogos', clave=None)['structuredContent']['error']['codigo'], 'no_autenticado')
        with self.client.session_transaction() as s:
            s.clear()
        acceso._INTENTOS_FALLIDOS.clear()
        for _ in range(acceso.MAX_INTENTOS):
            r = self.llamar('listar_catalogos', clave='mala')
            self.assertTrue(r['isError'])
            self.assertEqual(r['structuredContent']['error']['codigo'], 'no_autenticado')
        self.assertEqual(self.llamar('listar_catalogos')['structuredContent']['error']['codigo'], 'demasiados_intentos')
        acceso._INTENTOS_FALLIDOS.clear()
        self.assertFalse(self.llamar('listar_catalogos')['isError'])
        self.assertEqual(self.client.get('/app-horarios/api/datos').status_code, 401)
        self.assertEqual(self.client.post('/app-horarios/api/actualizar', headers={'X-Mitre':'1'}).status_code, 401)
        self.assertEqual(self.rpc('tools/call', {'name':'actualizar','arguments':{}}).get_json()['result']['structuredContent']['error']['codigo'], 'parametros_invalidos')

    def test_errores_escolares_y_argumentos_no_se_ocultan(self):
        r = self.llamar('consultar_horarios', {'tipo':'persona','valores':['PEREZ']})
        self.assertTrue(r['isError'])
        self.assertEqual(r['structuredContent']['error']['codigo'], 'persona_ambigua')
        self.assertEqual(len(r['structuredContent']['error']['candidatos']), 2)
        self.assertEqual(self.llamar('buscar_personas', {'nombre':'ZZZZZZZZ'})['structuredContent'], {'personas':[]})
        self.assertEqual(self.llamar('consultar_horarios', {'tipo':'curso','valor':'3 A'})['structuredContent']['error']['codigo'], 'parametros_invalidos')

    def test_pdf_reales_firmados_sin_contrasenia_y_rotacion(self):
        casos = [{'tipo':'curso','valor':'3 A'}, {'tipo':'persona','valor':'PEREZ ANA'},
                 {'tipo':'aula','valor':'11'}, {'tipo':'cursos','cursos':['3 A','3 B']},
                 {'tipo':'cursos','todos':True}, {'tipo':'preceptores'}]
        for filtros in casos:
            with self.subTest(filtros=filtros):
                resultado = self.llamar('obtener_pdf', filtros)
                self.assertFalse(resultado['isError'], resultado)
                contenido = resultado['structuredContent']
                self.assertEqual(contenido['vence_en_segundos'], 600)
                self.assertNotIn('clave-sintética', json.dumps(resultado))
                url = contenido['url']
                r = self.client.get(url)
                self.assertEqual(r.status_code, 200)
                self.assertTrue(r.data.startswith(b'%PDF-'))
                self.assertEqual(r.mimetype, 'application/pdf')
                self.assertEqual(r.headers['Cache-Control'], 'no-store')
                self.assertEqual(self.client.get(url+'x').status_code, 403)
                with patch('itsdangerous.timed.time.time', return_value=9999999999):
                    self.assertEqual(self.client.get(url).status_code, 403)
                with patch.object(acceso, '_clave', return_value='otra'):
                    self.assertEqual(self.client.get(url).status_code, 403)
        for filtros in ({'tipo':'curso'}, {'tipo':'cursos','todos':False},
                        {'tipo':'preceptores','valor':'otro'}, {'tipo':'aula','valor':'99999'}):
            self.assertTrue(self.llamar('obtener_pdf', filtros)['isError'])


if __name__ == '__main__':
    unittest.main()
