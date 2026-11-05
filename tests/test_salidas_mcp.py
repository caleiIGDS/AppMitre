"""El MCP puede entregar valores, con la base de legajos aislada de sus escrituras."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import timedelta
from pathlib import Path
import sqlite3
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
                         {'listar_anexos', 'leer_anexo', 'consultar_campos', 'rellenar_formulario'})
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
        self.assertIn('error', self.tool('crear_salida'))

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
