"""Orden persistido, permisos y conflictos de fotos en un inventario aislado."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from flask import Flask
import accesos
import crud
import gestion


class OrdenFotos(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / '.cache'
        base.mkdir(exist_ok=True)
        tmp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(tmp.cleanup)
        raiz = Path(tmp.name)
        for parche in (patch.object(gestion, 'DB_PATH', str(raiz / 'registro.db')),
                       patch.object(gestion, 'DIR_INVENTARIOS', str(raiz)),
                       patch.object(accesos, 'DB_PATH', str(raiz / 'accesos.db'))):
            parche.start()
            self.addCleanup(parche.stop)
        with closing(gestion.conectar_registro()) as con, con:
            con.executescript(gestion.SCHEMA_REGISTRO)
            con.execute("INSERT INTO inventarios(id,slug,nombre,clave_hash,creado) VALUES(1,'prueba','Prueba','hash','')")
        self.ruta = raiz / 'prueba.db'
        with closing(sqlite3.connect(self.ruta)) as con, con:
            con.executescript(gestion.SCHEMA)
            crud.instalar_versionado(gestion, con.cursor())
            con.execute("INSERT INTO recursos(id,nombre,fotos) VALUES(1,'Equipo',?)",
                        (json.dumps([{'id': 'a', 'tipo': 'image/jpeg'}, {'id': 'b', 'tipo': 'image/png'}]),))
        with closing(accesos.conectar()) as con, con:
            con.executescript(accesos.SCHEMA)
            con.execute("INSERT INTO dispositivos(id,nombre,perfil,permisos,alta) VALUES(1,'Consulta','custom',?, '')",
                        (json.dumps(['inv:1/gestion.leer', 'inv:1/gestion.editar']),))
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY='prueba')
        self.app.register_blueprint(gestion.bp_api)
        self.admin = self.app.test_client()
        self.admin.environ_base['HTTP_X_MITRE'] = '1'
        with self.admin.session_transaction() as ses:
            ses['acceso'] = {'tipo': 'admin', 'clave': accesos.huella_clave()}
        self.lector = self.app.test_client()
        self.lector.environ_base['HTTP_X_MITRE'] = '1'
        with self.lector.session_transaction() as ses:
            ses['acceso'] = {'tipo': 'dispositivo', 'id': 1}
        self.url = '/app/api/gestion/prueba/recursos/1/fotos/orden'

    def fotos(self):
        with closing(sqlite3.connect(self.ruta)) as con:
            return json.loads(con.execute('SELECT fotos FROM recursos WHERE id=1').fetchone()[0])

    def test_persistencia_y_lectura_desde_otro_dispositivo(self):
        r = self.admin.put(self.url, json={'ids': ['b', 'a']})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([f['id'] for f in self.fotos()], ['b', 'a'])
        self.assertEqual(self.fotos()[0]['tipo'], 'image/png')
        lista = self.lector.get('/app/api/gestion/prueba/recursos')
        self.assertEqual(lista.status_code, 200, lista.text)
        self.assertEqual([f['id'] for f in lista.json['filas'][0]['fotos']], ['b', 'a'])

    def test_editar_no_autoriza_ordenar(self):
        self.assertEqual(self.lector.put(self.url, json={'ids': ['b', 'a']}).status_code, 403)
        self.assertEqual([f['id'] for f in self.fotos()], ['a', 'b'])

    def test_orden_invalido_y_fotos_cambiadas_no_pisan_datos(self):
        for ids, estado in [(['a', 'a'], 400), ([1], 400), (['b'], 409), (['a', 'b', 'c'], 409)]:
            self.assertEqual(self.admin.put(self.url, json={'ids': ids}).status_code, estado)
            self.assertEqual([f['id'] for f in self.fotos()], ['a', 'b'])
        self.assertEqual(self.admin.put(self.url.replace('/1/', '/999/'), json={'ids': []}).status_code, 404)

    def test_meta_solo_admin_puede_ordenar(self):
        url = '/app/api/gestion/prueba/meta'
        self.assertTrue(self.admin.get(url).json['puede_ordenar_fotos'])
        self.assertFalse(self.lector.get(url).json['puede_ordenar_fotos'])
