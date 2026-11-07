"""Acceso Bearer y PDF por HTTP real contra bases sintéticas."""
import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from werkzeug.serving import WSGIRequestHandler, make_server

import test_gestion_mcp
import test_horarios_mcp


class TokensHTTP(unittest.TestCase):
    def servir(self, fixture):
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)

        class SinLog(WSGIRequestHandler):
            def log(self, *args, **kwargs):
                pass

        server = make_server('127.0.0.1', 0, fixture.app, threaded=True, request_handler=SinLog)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def cerrar():
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

        self.addCleanup(cerrar)
        return f'http://127.0.0.1:{server.server_port}'

    def rpc(self, url, token, metodo, params=None):
        r = Request(url, data=json.dumps({'jsonrpc':'2.0', 'id':1, 'method':metodo,
                                         'params':params or {}}).encode(),
                    headers={'Authorization':'Bearer ' + token, 'Content-Type':'application/json',
                             'Accept':'application/json'})
        try:
            with urlopen(r, timeout=10) as respuesta:
                return respuesta.status, json.load(respuesta)
        except HTTPError as error:
            return error.code, json.load(error)

    def test_gestion_consulta_admin_y_rechazo(self):
        fixture = test_gestion_mcp.GestionMCP('test_token_consulta_oculta_ubicaciones_textos_fotos_y_personas')
        url = self.servir(fixture) + '/mcp/gestion'
        self.assertEqual(self.rpc(url, '', 'tools/list')[0], 401)
        params = {'name':'consultar_inventario', 'arguments':{'inventario':'taller'}}
        status, data = self.rpc(url, fixture.LECTURA, 'tools/call', params)
        self.assertEqual(status, 200)
        self.assertNotIn('Armario', json.dumps(data))
        status, data = self.rpc(url, fixture.ADMIN, 'tools/call', params)
        self.assertEqual(status, 200)
        self.assertIn('Armario', json.dumps(data))
        self.assertEqual(self.rpc(url, fixture.LECTURA, 'tools/call',
                                 {'name':'consultar_salida', 'arguments':{'id':1}})[0], 403)
        self.assertEqual(self.rpc(url, fixture.ADMIN, 'tools/call',
                                 {'name':'consultar_salida', 'arguments':{'id':1}})[0], 200)

    def test_horarios_token_y_pdf_descargable(self):
        fixture = test_horarios_mcp.MCPHorarios('test_token_obligatorio_independiente_de_sesion_web')
        url = self.servir(fixture)
        self.assertEqual(self.rpc(url+'/mcp', '', 'tools/list')[0], 401)
        status, data = self.rpc(url+'/mcp', 'token-horarios-sintetico', 'tools/call',
                               {'name':'obtener_pdf', 'arguments':{'consulta':{'tipo':'curso','valor':'3 A'}}})
        self.assertEqual(status, 200)
        self.assertFalse(data['result']['isError'])
        enlace = data['result']['structuredContent']['url']
        with urlopen(enlace, timeout=10) as archivo:
            self.assertEqual(archivo.status, 200)
            self.assertTrue(archivo.read().startswith(b'%PDF-'))
        status, data = self.rpc(url+'/mcp', 'token-horarios-sintetico', 'resources/read', {'uri':enlace})
        self.assertEqual(status, 200)
        self.assertEqual(data['result']['contents'][0]['mimeType'], 'application/pdf')
