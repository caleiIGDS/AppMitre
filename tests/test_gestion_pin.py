"""PIN de movimientos contra Flask y SQLite temporales, sin cargar app.py ni .env."""
from contextlib import closing
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask

import accesos
import crud
import gestion


class PinMovimientos(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.raiz = Path(tmp.name)
        self.reloj = datetime(2026, 11, 4, 12, 0, 0)
        for parche in (
            patch.object(gestion, 'DB_PATH', str(self.raiz / 'registro.db')),
            patch.object(gestion, 'DIR_INVENTARIOS', str(self.raiz)),
            patch.object(accesos, 'DB_PATH', str(self.raiz / 'accesos.db')),
            patch.object(gestion, 'ahora', side_effect=lambda: self.reloj),
            patch.dict(os.environ, {'GESTION_PIN_MOVER': '0472'}),
        ):
            parche.start()
            self.addCleanup(parche.stop)
        with closing(gestion.conectar_registro()) as con:
            con.executescript(gestion.SCHEMA_REGISTRO)
            for n, slug in enumerate(('laboratorio', 'taller'), 1):
                con.execute('INSERT INTO inventarios (id, slug, nombre, creado) VALUES (?, ?, ?, ?)',
                            (n, slug, slug, self.reloj.isoformat()))
            con.commit()
        for slug in ('laboratorio', 'taller'):
            with closing(sqlite3.connect(self.raiz / f'{slug}.db')) as con:
                con.executescript(gestion.SCHEMA)
                crud.instalar_versionado(gestion, con.cursor())
                con.execute("INSERT INTO recursos (id, nombre, cantidad) VALUES (1, 'Recurso de prueba', '2')")
                con.executemany('INSERT INTO recurso_unidades VALUES (1, ?, ?)', [(1, 'Armario'), (2, 'Armario')])
                con.commit()
        with closing(accesos.conectar()) as con:
            con.executescript(accesos.SCHEMA)
            con.execute('INSERT INTO dispositivos (id, nombre, perfil, permisos, alta) VALUES (1, ?, ?, ?, ?)',
                        ('Pantalla compartida', 'custom', json.dumps(['inv:1/gestion.leer', 'inv:2/gestion.leer']),
                         self.reloj.isoformat()))
            con.commit()
        accesos.declarar(gestion.GRUPO_PERMISOS, gestion.PERMISOS, gestion.PERMISOS_AMBITO)
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY='secreto-exclusivo-de-la-prueba')
        self.app.register_blueprint(gestion.bp_api)
        self.client = self.app.test_client()
        with self.client.session_transaction() as ses:
            ses['acceso'] = {'tipo': 'dispositivo', 'id': 1}

    def post(self, ruta, datos=None, token=None, client=None):
        cabeceras = {'X-Mitre': '1'}
        if token:
            cabeceras['X-Mitre-Movimientos'] = token
        return (client or self.client).post('/app/api/gestion/' + ruta, json=datos or {}, headers=cabeceras)

    def autorizar(self, inv='laboratorio'):
        r = self.post(f'{inv}/movimientos/autorizar', {'pin': '0472'})
        self.assertEqual(r.status_code, 200, r.json)
        self.assertEqual(r.json['segundos'], 20)
        self.assertEqual(r.headers['Cache-Control'], 'no-store')
        return r.json['token']

    def mover(self, token=None, inv='laboratorio'):
        return self.post(f'{inv}/recursos/1/unidades/mover', {'numeros': [1], 'ubicacion': 'Mesa'}, token)

    def test_lectura_y_pin_no_dan_edicion_general(self):
        self.assertEqual(self.mover().status_code, 403)
        token = self.autorizar()
        for ruta in ('unidades/agregar', 'unidades/eliminar', 'baja', 'kit'):
            with self.subTest(ruta=ruta):
                r = self.post('laboratorio/recursos/1/' + ruta, {'numeros': [3], 'motivo': 'Otro'}, token)
                self.assertEqual(r.status_code, 403)
        meta = self.client.get('/app/api/gestion/laboratorio/meta').json
        self.assertFalse(meta['puede_escribir'])
        self.assertFalse(meta['puede_accesos'])
        self.assertTrue(meta['pin_movimientos'])

    def test_mueve_solo_unidades_elegidas_y_permite_sin_ubicar(self):
        token = self.autorizar()
        self.assertEqual(self.mover(token).status_code, 200)
        with closing(sqlite3.connect(self.raiz / 'laboratorio.db')) as con:
            self.assertEqual(con.execute('SELECT numero, ubicacion FROM recurso_unidades ORDER BY numero').fetchall(),
                             [(1, 'Mesa'), (2, 'Armario')])
        self.assertEqual(self.post('laboratorio/recursos/1/unidades/quitar', {'numeros': [1]}, token).status_code, 200)

    def test_vence_a_los_20_segundos_sin_renovarse_por_usarlo(self):
        token = self.autorizar()
        self.reloj += timedelta(seconds=19, milliseconds=999)
        self.assertEqual(self.mover(token).status_code, 200)
        self.reloj += timedelta(milliseconds=1)
        self.assertEqual(self.mover(token).status_code, 403)
        self.assertEqual(self.post('laboratorio/recursos/1/unidades/quitar', {'numeros': [1]}, token).status_code, 403)

    def test_token_no_cruza_inventarios_ni_sesiones(self):
        token = self.autorizar()
        self.assertEqual(self.mover(token, 'taller').status_code, 403)
        otro = self.app.test_client()
        with otro.session_transaction() as ses:
            ses['acceso'] = {'tipo': 'dispositivo', 'id': 1}
        self.assertEqual(self.post('laboratorio/recursos/1/unidades/mover',
                                  {'numeros': [1], 'ubicacion': 'Mesa'}, token, otro).status_code, 403)

    def test_pin_no_abre_un_inventario_sin_permiso_de_lectura(self):
        with closing(accesos.conectar()) as con:
            con.execute("UPDATE dispositivos SET permisos = '[]'")
            con.commit()
        self.assertEqual(self.post('laboratorio/movimientos/autorizar', {'pin': '0472'}).status_code, 403)
        self.assertEqual(self.post('laboratorio/movimientos/autorizar', {'pin': '0472'},
                                  client=self.app.test_client()).status_code, 401)

    def test_pin_apagado_mal_formado_o_rotado_invalida_token(self):
        token = self.autorizar()
        for valor in ('', '123', '12345', 'abcd', '１２３４', '1234'):
            with self.subTest(valor=valor), patch.dict(os.environ, {'GESTION_PIN_MOVER': valor}):
                self.assertEqual(self.mover(token).status_code, 403)
                if valor != '1234':
                    self.assertEqual(self.post('laboratorio/movimientos/autorizar', {'pin': '0472'}).status_code, 503)

    def test_cinco_fallos_bloquean_por_ip_aunque_cambie_sesion_o_inventario(self):
        for _ in range(5):
            self.assertEqual(self.post('laboratorio/movimientos/autorizar', {'pin': '0000'}).status_code, 403)
        with self.client.session_transaction() as ses:
            ses.pop('pin_movimientos_sid', None)
        r = self.post('taller/movimientos/autorizar', {'pin': '0472'})
        self.assertEqual(r.status_code, 429)
        self.assertIn('Retry-After', r.headers)
        self.reloj += timedelta(seconds=60)
        self.autorizar('taller')

    def test_no_guarda_pin_y_rechaza_token_modificado(self):
        token = self.autorizar()
        with self.app.app_context():
            carga = gestion._serializador_movimientos().loads(token)
        self.assertNotIn('0472', json.dumps(carga))
        self.assertEqual(self.mover(token + 'x').status_code, 403)
        self.assertEqual(self.post('laboratorio/movimientos/autorizar', {'pin': 472}).status_code, 403)
        self.assertEqual(self.post('laboratorio/movimientos/autorizar', {'pin': '\ud800'}).status_code, 403)

    def test_salir_y_revocar_cortan_la_autorizacion(self):
        token = self.autorizar()
        self.assertEqual(self.post('laboratorio/salir').status_code, 200)
        self.assertEqual(self.mover(token).status_code, 403)
        token = self.autorizar()
        with closing(accesos.conectar()) as con:
            con.execute("UPDATE dispositivos SET revocado = '2026-11-04'")
            con.commit()
        self.assertEqual(self.mover(token).status_code, 401)

    def test_escritor_conserva_acceso_y_csrf_sigue_vigente(self):
        with closing(accesos.conectar()) as con:
            con.execute('UPDATE dispositivos SET permisos = ?',
                        (json.dumps(['inv:1/gestion.leer', 'inv:1/gestion.editar']),))
            con.commit()
        self.assertEqual(self.mover().status_code, 200)
        self.assertEqual(self.client.post('/app/api/gestion/laboratorio/movimientos/autorizar',
                                         json={'pin': '0472'}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
