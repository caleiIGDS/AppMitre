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
        async with streamable_http_client(self.url + '/mcp') as (read, write, _):
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
                    resultado = await session.call_tool(nombre, {'clave':clave,'consulta':consulta})
                    self.assertFalse(resultado.isError, resultado)
                    self.assertTrue(resultado.structuredContent)
                error = await session.call_tool('consultar_horarios',
                            {'clave':clave,'consulta':{'tipo':'persona','valores':['PEREZ']}})
                self.assertTrue(error.isError)
                self.assertEqual(error.structuredContent['error']['codigo'], 'persona_ambigua')
                error = await session.call_tool('listar_catalogos', {'clave':'incorrecta','consulta':{}})
                self.assertTrue(error.isError)
                self.assertEqual(error.structuredContent['error']['codigo'], 'no_autenticado')
                pdf = await session.call_tool('obtener_pdf', {'clave':clave,'consulta':{'tipo':'curso','valor':'3 A'}})
                self.assertFalse(pdf.isError)
                self.assertNotIn(clave, pdf.model_dump_json())
                async with httpx.AsyncClient() as cliente:
                    archivo = await cliente.get(pdf.structuredContent['url'])
                    self.assertEqual(archivo.status_code, 200)
                    self.assertTrue(archivo.content.startswith(b'%PDF-'))
                    self.assertEqual((await cliente.get(self.url+'/app-horarios/api/datos')).status_code, 401)

    async def test_oauth_oficial_registra_conecta_renueva_y_reutiliza_acceso(self):
        import html
        import re
        from urllib.parse import urlsplit, parse_qs
        import httpx
        from mcp import ClientSession
        from mcp.client.auth import OAuthClientProvider
        from mcp.shared.auth import OAuthClientMetadata
        from mcp.client.streamable_http import streamable_http_client
        from test_horarios_mcp import mcp

        class Almacen:
            tokens = None
            cliente = None
            async def get_tokens(self): return self.tokens
            async def set_tokens(self, v): self.tokens = v
            async def get_client_info(self): return self.cliente
            async def set_client_info(self, v): self.cliente = v

        almacen, callbacks = Almacen(), []
        async def abrir(url):
            async with httpx.AsyncClient() as browser:
                pagina = await browser.get(url)
                csrf = html.unescape(re.search(r'name="csrf" value="([^"]+)"', pagina.text)[1])
                respuesta = await browser.post(url, data={'csrf': csrf, 'clave': 'clave-sintética-ñ', 'decision': 'autorizar'})
                self.assertEqual(respuesta.status_code, 302, respuesta.text)
                q = parse_qs(urlsplit(respuesta.headers['location']).query)
                callbacks.append((q['code'][0], q['state'][0]))
        async def callback(): return callbacks[-1]
        def proveedor():
            return OAuthClientProvider(self.url+'/mcp', OAuthClientMetadata(
                redirect_uris=['http://127.0.0.1:8765/callback'], token_endpoint_auth_method='none',
                client_name='SDK oficial', scope='horarios:leer offline_access'), almacen, abrir, callback)

        for intento in range(2):
            auth = proveedor()
            async with httpx.AsyncClient(auth=auth) as cliente:
                async with streamable_http_client(self.url+'/mcp', http_client=cliente) as (read, write, _):
                    async with ClientSession(read, write) as sesion:
                        await sesion.initialize()
                        r = await sesion.call_tool('consultar_horarios', {'consulta': {'tipo': 'curso', 'valores': ['3 A']}})
                        self.assertFalse(r.isError, r)
                        pdf = await sesion.call_tool('obtener_pdf', {'consulta': {'tipo': 'curso', 'valor': '3 A'}})
                        recurso = await sesion.read_resource(pdf.structuredContent['url'])
                        self.assertEqual(recurso.contents[0].mimeType, 'application/pdf')
                        if intento == 0:
                            refresh_original = almacen.tokens.refresh_token
                            # Simula el vencimiento conocido por el cliente y por el servidor.
                            auth.context.token_expiry_time = 1
                            with self.fixture.app.test_request_context(self.url):
                                with mcp.oauth.base() as con:
                                    con.execute("DELETE FROM credenciales WHERE tipo='access'")
                            r = await sesion.call_tool('listar_catalogos', {'consulta': {}})
                            self.assertFalse(r.isError, r)
                            self.assertNotEqual(almacen.tokens.refresh_token, refresh_original)
            self.assertEqual(len(callbacks), 1)
