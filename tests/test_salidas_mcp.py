"""El MCP puede entregar valores, con la base de legajos aislada de sus escrituras."""
from contextlib import closing
from datetime import timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask

import accesos
from config import ahora
import salidas
import salidas_mcp


class SalidasMCP(unittest.TestCase):
    ruta = '/gestion/areas/salidas'
    ADMIN = 'admin-sintetico-' + 'a' * 43
    LECTURA = 'lectura-sintetica-' + 'b' * 43
    HORARIOS = 'horarios-sintetico-' + 'c' * 43

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
        env = patch.dict('os.environ', {'GESTION_MCP_TOKEN_ADMIN': self.ADMIN, 'GESTION_MCP_TOKEN_LECTURA': self.LECTURA, 'HORARIOS_MCP_TOKEN': self.HORARIOS})
        env.start()
        self.addCleanup(env.stop)
        self.editor = self.cliente(1)
        self.anonimo = self.app.test_client()

    def cliente(self, id):
        cliente = self.app.test_client()
        with cliente.session_transaction() as ses:
            ses['acceso'] = {'tipo': 'dispositivo', 'id': id}
        return cliente

    def mcp(self, metodo, params=None, **kwargs):
        return self.app.test_client().post('/mcp/gestion', json={
            'jsonrpc': '2.0', 'id': 1, 'method': metodo, 'params': params or {}}, **kwargs)

    def tool_con_token(self, token, nombre, **args):
        return self.mcp('tools/call', {'name': nombre, 'arguments': args},
                        headers={'Authorization': 'Bearer ' + token})

    def test_sin_token_sesion_y_claves_anteriores_no_autorizan(self):
        for cliente in (self.anonimo, self.editor):
            for token in ('', 'incorrecto', self.HORARIOS, 'mitre_salidas_' + 'a' * 43):
                r = cliente.post('/mcp/gestion', json={'jsonrpc':'2.0','id':1,'method':'tools/list'},
                                 headers={'Authorization':'Bearer ' + token})
                self.assertEqual(r.status_code, 401)
                self.assertNotIn('resource_metadata', r.headers['WWW-Authenticate'])
        with patch.dict('os.environ', {'GESTION_MCP_TOKEN_ADMIN':'', 'GESTION_MCP_TOKEN_LECTURA':''}):
            self.assertEqual(self.tool_con_token(self.ADMIN, 'buscar_salidas').status_code, 401)

    def test_lectura_no_accede_a_legajos_ni_escrituras(self):
        for nombre, args in [('buscar_salidas', {}), ('consultar_salida', {'id':1}),
                             ('esquema_legajo', {}), ('crear_salida', {}), ('editar_salida', {})]:
            self.assertEqual(self.tool_con_token(self.LECTURA, nombre, **args).status_code, 403)
        r = self.mcp('tools/list', headers={'Authorization':'Bearer ' + self.LECTURA})
        nombres = {t['name'] for t in r.json['result']['tools']}
        self.assertNotIn('buscar_salidas', nombres)
        self.assertNotIn('crear_salida', nombres)
        self.assertNotIn('pedir_fotos_recursos', nombres)
        self.assertIn('consultar_inventario', nombres)
        r = self.mcp('tools/list', headers={'Authorization':'Bearer ' + self.ADMIN})
        self.assertIn('crear_salida', {t['name'] for t in r.json['result']['tools']})

    def test_dos_rutas_sin_oauth_y_sin_relleno_de_pestanas(self):
        for ruta in ('/mcp/gestion', '/mcp/salidas'):
            r = self.anonimo.post(ruta, json={'jsonrpc':'2.0','id':1,'method':'tools/list'},
                                  headers={'Authorization':'Bearer ' + self.ADMIN})
            self.assertEqual(r.status_code, 200)
            nombres = {t['name'] for t in r.json['result']['tools']}
            self.assertNotIn('consultar_campos', nombres)
            self.assertNotIn('rellenar_formulario', nombres)
        for ruta in ('/salidas/oauth/authorize', '/salidas/oauth/token',
                     '/.well-known/oauth-protected-resource/mcp/gestion',
                     self.ruta + '/1/agente-formulario'):
            self.assertEqual(self.anonimo.post(ruta).status_code, 404)

    def test_instructivos_no_incluyen_datos_de_legajos(self):
        r = self.tool_con_token(self.LECTURA, 'listar_anexos')
        self.assertEqual(len(r.json['result']['structuredContent']['anexos']), 9)
        for n in salidas_mcp.ANEXOS:
            r = self.tool_con_token(self.LECTURA, 'leer_anexo', anexo=n)
            self.assertGreater(len(r.json['result']['structuredContent']['formulario']), 500)
        r = self.mcp('tools/list', headers={'Origin':'https://otro.example', 'Authorization':'Bearer '+self.ADMIN})
        self.assertEqual(r.status_code, 403)

    def test_salidas_web_requiere_permiso_no_cualquier_acceso_de_gestion(self):
        self.assertEqual(self.anonimo.get(self.ruta + '/').status_code, 302)
        lector = self.cliente(2)
        self.assertEqual(lector.post(self.ruta + '/api/guardar', json={}).status_code, 403)
        with self.anonimo.session_transaction() as s:
            s['salidas_clave'] = 'vieja-sesion'
        with patch.dict('os.environ', {'SALIDAS_CLAVE':'anterior'}):
            self.assertEqual(self.anonimo.get(self.ruta + '/').status_code, 302)

    def test_crear_reintentar_editar_y_rechazar_revision_anterior(self):
        token = self.ADMIN

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
        with patch.dict('os.environ', {'GESTION_MCP_TOKEN_ADMIN': 'otra-clave'}):
            self.assertEqual(self.tool_con_token(token, 'consultar_salida', id=id).status_code, 401)
