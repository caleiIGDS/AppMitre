"""Interoperabilidad HTTP con el SDK oficial (opcional: pip install 'mcp>=1.26,<2')."""
import importlib.util
import threading
import unittest

SDK = importlib.util.find_spec('mcp') is not None


@unittest.skipUnless(SDK, 'Prueba opcional: requiere el SDK oficial mcp.')
class ClienteOficialMCP(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import test_horarios_consultas as fixtures
        from test_horarios_mcp import mcp
        from werkzeug.serving import make_server, WSGIRequestHandler

        class SinLog(WSGIRequestHandler):
            def log(self, *args, **kwargs):
                pass

        self.fixture = fixtures.ConsultasHorarios('test_roles_multiples_y_alias_explicito_sin_fusion_aproximada')
        self.fixture.setUp()
        from unittest.mock import patch
        env = patch.dict('os.environ', {'HORARIOS_MCP_TOKEN':'token-sdk-sintetico'})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.app.register_blueprint(mcp.bp_mcp)
        self.server = make_server('127.0.0.1', 0, self.fixture.app, threaded=True, request_handler=SinLog)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.cerrar)
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def cerrar(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()

    async def test_cliente_oficial_descubre_consulta_errores_y_descarga_pdf(self):
        import httpx
        from jsonschema import Draft202012Validator
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        clave = 'clave-sintética-ñ'
        cliente = httpx.AsyncClient(headers={'Authorization':'Bearer token-sdk-sintetico'})
        self.addAsyncCleanup(cliente.aclose)
        async with streamable_http_client(self.url + '/mcp', http_client=cliente) as (read, write, _):
            async with ClientSession(read, write) as session:
                inicio = await session.initialize()
                self.assertTrue(inicio.capabilities.tools)
                self.assertIn('PROGRESO', inicio.instructions)
                herramientas = await session.list_tools()
                for tool in herramientas.tools:
                    Draft202012Validator.check_schema(tool.inputSchema)
                    Draft202012Validator.check_schema(tool.outputSchema)
                    self.assertNotIn(clave, tool.model_dump_json())
                ejemplos = {'listar_catalogos': {'incluir':['nombres','roles']},
                            'buscar_personas': {'multiples_roles':True},
                            'consultar_horarios': {'tipo':'curso','valores':['3 A']},
                            'consultar_preceptores': {}}
                for nombre, consulta in ejemplos.items():
                    resultado = await session.call_tool(nombre, {'consulta':consulta})
                    self.assertFalse(resultado.isError, resultado)
                    self.assertTrue(resultado.structuredContent)
                error = await session.call_tool('consultar_horarios',
                            {'consulta':{'tipo':'persona','valores':['PEREZ']}})
                self.assertTrue(error.isError)
                self.assertEqual(error.structuredContent['error']['codigo'], 'persona_ambigua')
                pdf = await session.call_tool('obtener_pdf', {'consulta':{'tipo':'curso','valor':'3 A'}})
                self.assertFalse(pdf.isError)
                self.assertNotIn(clave, pdf.model_dump_json())
                async with httpx.AsyncClient() as cliente:
                    archivo = await cliente.get(pdf.structuredContent['url'])
                    self.assertEqual(archivo.status_code, 200)
                    self.assertTrue(archivo.content.startswith(b'%PDF-'))
                    self.assertEqual((await cliente.get(self.url+'/app-horarios/api/datos')).status_code, 401)
