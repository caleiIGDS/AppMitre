"""Regresiones con CSV sintéticos y SQLite temporal; nunca importa app.py ni abre DB reales.

python -m unittest discover -s tests -p test_horarios_actualizacion.py
"""
import csv
from contextlib import closing
import importlib.util
import io
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from flask import Blueprint, Flask

RAIZ = Path(__file__).resolve().parents[1]
PAQUETE = '_horarios_prueba_aislada'
paquete = types.ModuleType(PAQUETE)
paquete.__path__ = [str(RAIZ / 'horarios')]
paquete.bp = Blueprint('horarios', __name__, url_prefix='/horarios')
sys.modules[PAQUETE] = paquete


def cargar(nombre):
    spec = importlib.util.spec_from_file_location(f'{PAQUETE}.{nombre}', RAIZ / 'horarios' / f'{nombre}.py')
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    setattr(paquete, nombre, modulo)
    return modulo


cargar('config')  # Sólo constantes/entorno: no carga .env ni abre una base.
datos = cargar('datos')
acceso = cargar('acceso')
cargar('rutas')
api = cargar('app_api')


def csv_texto(filas):
    archivo = io.StringIO()
    csv.writer(archivo).writerows(filas)
    return archivo.getvalue()


CLASES = ['curso', 'division', 'materia', 'profesor', 'aula', 'dia', 'hora_inicio', 'hora_fin']
PERSONAL = ['nombre', 'rol'] + [f'{dia}_{extremo}'
    for dia in ('lunes', 'martes', 'miercoles', 'jueves', 'viernes') for extremo in ('inicio', 'fin')]
CAB_PRECEPTORES = ['Preceptor', 'Curso', 'División', 'Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes']


def hojas(marca):
    return {
        '1': csv_texto([CLASES, ['1', 'A', f'MATERIA {marca}', f'DOCENTE {marca}', '11', 'Lunes', '07:40', '09:40']]),
        '2': csv_texto([CLASES, ['2', 'B', f'OTRA {marca}', f'DOCENTE {marca}', '12', 'Martes', '10:00', '12:00']]),
        'p': csv_texto([['MAÑANA'] + [''] * 8 + ['TARDE'] + [''] * 8 + ['VESPERTINO'],
            CAB_PRECEPTORES + [''] + CAB_PRECEPTORES + [''] + CAB_PRECEPTORES,
            [f'PRECEPTOR {marca}', '1', 'A', 'VERDADERO', '', '', '', ''] + [''] * 18]),
        'n': csv_texto([PERSONAL, [f'PERSONAL {marca}', 'PORTERIA', '08:00', '12:00'] + [''] * 8]),
    }


class ActualizacionSegura(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'sintetica.db'
        self.parche_db = patch.object(datos, 'DB_PATH', str(self.db))
        self.parche_db.start()
        self.addCleanup(self.parche_db.stop)
        silencio = patch.object(datos, 'print', create=True)
        silencio.start()
        self.addCleanup(silencio.stop)
        datos.init_tablas()
        self.publicar(hojas('ANTERIOR'))
        self.anterior = self.snapshot()

    def publicar(self, contenido, fallar=None):
        def descargar(_sheet, gid, **_kwargs):
            # Durante TODAS las descargas, el servidor todavía expone el snapshot previo.
            if hasattr(self, 'anterior'):
                self.assertEqual(self.snapshot(), self.anterior)
            if gid == fallar:
                raise OSError('descarga interrumpida')
            return io.StringIO(contenido[gid])
        with patch.object(datos, 'descargar_sheet', side_effect=descargar):
            datos.actualizar_desde_sheets('sintetico', {'primero': '1', 'segundo': '2'}, 'p', 'n')

    def snapshot(self):
        with closing(sqlite3.connect(self.db)) as con, con:
            return {tabla: con.execute(f'SELECT * FROM {tabla}').fetchall()
                for tabla in ('clases', 'horarios_preceptores', 'personal_no_docente')}

    def test_descarga_fallida_en_cualquier_hoja_conserva_las_tres_tablas(self):
        for gid in ('1', '2', 'p', 'n'):
            with self.subTest(gid=gid), self.assertRaises(RuntimeError):
                self.publicar(hojas('NUEVO'), fallar=gid)
            self.assertEqual(self.snapshot(), self.anterior)

    def test_csv_invalidos_y_carga_vacia_conservan_el_snapshot(self):
        malos = [
            ('1', 'curso,materia\n1,INCOMPLETA\n'),
            ('2', hojas('NUEVO')['2'].replace('12:00', '10:00')),
            ('2', hojas('NUEVO')['2'].replace('10:00', '16:60')),
            ('p', 'respuesta inesperada\n'),
            ('n', hojas('NUEVO')['n'].replace('08:00', '')),
        ]
        vacias = hojas('NUEVO')
        vacias['1'] = vacias['2'] = csv_texto([CLASES])
        casos = [dict(hojas('NUEVO'), **{gid: texto}) for gid, texto in malos] + [vacias]
        for i, contenido in enumerate(casos):
            with self.subTest(caso=i), self.assertRaises((ValueError, RuntimeError)):
                self.publicar(contenido)
            self.assertEqual(self.snapshot(), self.anterior)

    def test_formato_legacy_aceptado_no_bloquea_actualizaciones(self):
        contenido = hojas('NUEVO')
        contenido['2'] = contenido['2'].replace('Martes', 'Sábado').replace('10:00', '16:60').replace('12:00', '18:00:00')
        contenido['1'] += '\n'  # Las filas vacías siguen ignorándose.
        self.publicar(contenido)
        actual = self.snapshot()
        self.assertIn('Sábado', str(actual))
        self.assertIn('16:60', str(actual))
        self.assertIn('18:00:00', str(actual))

    def test_error_al_publicar_revierte_tambien_las_tablas_ya_reemplazadas(self):
        with closing(sqlite3.connect(self.db)) as con, con:
            con.execute("CREATE TRIGGER fallo BEFORE INSERT ON personal_no_docente BEGIN SELECT RAISE(ABORT, 'fallo simulado'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.publicar(hojas('NUEVO'))
        self.assertEqual(self.snapshot(), self.anterior)

    def test_exito_reemplaza_las_tres_tablas_sin_acumular_filas(self):
        self.publicar(hojas('NUEVO'))
        actual = self.snapshot()
        self.assertEqual([len(actual[t]) for t in actual], [2, 1, 1])
        self.assertIn('MATERIA NUEVO', str(actual))
        self.assertIn('PRECEPTOR NUEVO', str(actual))
        self.assertIn('PERSONAL NUEVO', str(actual))
        self.assertNotIn('ANTERIOR', str(actual))

    def test_api_lee_un_snapshot_aunque_otro_proceso_publique_en_medio(self):
        # WAL permite que la publicación termine durante una lectura abierta.
        with closing(sqlite3.connect(self.db)) as con, con:
            con.execute('PRAGMA journal_mode=WAL')
        app = Flask(__name__)
        app.secret_key = 'solo-test'
        app.register_blueprint(api.bp_app)
        listar = datos.obtener_lista_preceptores_horario
        def publicar_durante_lectura(con=None):
            self.publicar(hojas('NUEVO'))
            return listar(con)
        with patch.object(acceso, 'autenticado', return_value=True), patch.object(
                datos, 'obtener_lista_preceptores_horario', side_effect=publicar_durante_lectura):
            respuesta = app.test_client().get('/app-horarios/api/datos')
        self.assertEqual(respuesta.status_code, 200)
        cuerpo = respuesta.get_json()
        self.assertIn('ANTERIOR', cuerpo['clases'][0]['materia'])
        self.assertEqual(cuerpo['personal'][0]['nombre'], 'PERSONAL ANTERIOR')
        self.assertIn('PRECEPTOR ANTERIOR', cuerpo['preceptores']['horarios'])
        self.assertIn('NUEVO', str(self.snapshot()))


if __name__ == '__main__':
    unittest.main()
