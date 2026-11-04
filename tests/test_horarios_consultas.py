"""Contrato escolar y seguridad con SQLite temporal; sin app.py, .env ni bases reales.

python -m unittest discover -s tests -p 'test_horarios*.py'
"""
from contextlib import closing
from datetime import datetime
import importlib.util
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from flask import Blueprint, Flask

RAIZ = Path(__file__).resolve().parents[1]
PAQUETE = '_horarios_consultas_aislado'
paquete = types.ModuleType(PAQUETE)
paquete.__path__ = [str(RAIZ / 'horarios')]
paquete.bp = Blueprint('horarios', __name__, url_prefix='/horarios')
sys.modules[PAQUETE] = paquete


def cargar(n):
    spec = importlib.util.spec_from_file_location(f'{PAQUETE}.{n}', RAIZ / 'horarios' / f'{n}.py')
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    setattr(paquete, n, m)
    return m


config = cargar('config')
datos = cargar('datos')
acceso = cargar('acceso')
cargar('rutas')
api = cargar('app_api')
consultas = sys.modules[f'{PAQUETE}.consultas']
comun = sys.modules[f'{PAQUETE}.consultas.comun']
contratos = sys.modules[f'{PAQUETE}.consultas.contratos']
PREFIJO = '/app-horarios/api/v1/consultas'


class ConsultasHorarios(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'sintetica.db'
        self.parche(datos, 'DB_PATH', str(self.db))
        self.parche(config, 'FLOOR_MAPPING', {'Piso 1': ['11', '12', '13']})
        self.parche(config, 'TURNO_CURSOS', {('3', 'A'): 'TARDE', ('3', 'B'): 'MAÑANA'})
        self.parche(datos, '_NOMBRE_MAPEOS', {'PEREZ A': 'PEREZ ANA'})
        self.parche(acceso, '_clave', lambda: 'clave-sintética-ñ')
        acceso._INTENTOS_FALLIDOS.clear()
        self.addCleanup(acceso._INTENTOS_FALLIDOS.clear)
        datos.init_tablas()
        self.clase('3', 'A', 'MATEMATICA', 'PÉREZ ANA', '11', 'Lunes', '7:40', '09:20', grupo='A', superposicion=1)
        self.clase('3', 'A', 'TALLER', 'PEREZ ANA', '12', 'LUNES', '07:40', '09:20', grupo='B', superposicion=1)
        self.clase('3', 'B', 'FISICA', 'TITULAR UNO', '11', 'Miércoles', '16:60', '19:00:00',
                   suplente_activo=1, prof_suplente='REEMPLAZO DOS')
        self.clase('3', 'B', 'QUIMICA', 'TITULAR DOS', '12', 'VIERNES', '10:00', '11:00', suplente_activo=1)
        self.clase('4', '3', 'OTRA', 'PEREZ JUAN', '11', 'Sábado', '09:00', '10:00')
        self.personal('PEREZ ANA', 'EMATP EERR', 'LUNES', '10:00', '12:00')
        self.personal('PEREZ ANA', 'Jefatura', 'martes', '09:00', '10:00')
        self.preceptor('3', 'A', 'TARDE', 'PEREZ ANA', 'LUNES')
        self.preceptor('3', 'A', 'TARDE', 'OTRA', 'MARTES')
        self.preceptor('3', 'A', 'MAÑANA', 'ROMERO', 'LUNES')
        self.preceptor('3', 'A', 'VESPERTINO', 'LOPEZ', 'LUNES')
        self.preceptor('3', 'B', 'MAÑANA', 'FALTA', 'LUNES')
        self.app = Flask(__name__)
        self.app.secret_key = 'firma-sintetica'
        self.app.testing = True
        self.app.register_blueprint(api.bp_app)
        self.app.register_blueprint(paquete.bp)
        self.client = self.app.test_client()
        self.bearer = {'Authorization': 'Bearer clave-sintética-ñ'}

    def parche(self, objeto, campo, valor):
        p = patch.object(objeto, campo, valor)
        p.start()
        self.addCleanup(p.stop)

    def insertar(self, tabla, valores):
        with closing(sqlite3.connect(self.db)) as con, con:
            con.execute(f"INSERT INTO {tabla} ({','.join(valores)}) VALUES ({','.join('?' for _ in valores)})",
                        list(valores.values()))

    def clase(self, curso, division, materia, profesor, aula, dia, inicio, fin, **otros):
        self.insertar('clases', dict(curso=curso, division=division, materia=materia, profesor=profesor,
                      aula=aula, dia=dia, hora_inicio=inicio, hora_fin=fin, **otros))

    def personal(self, nombre, rol, dia, inicio, fin):
        self.insertar('personal_no_docente', dict(nombre=nombre, rol=rol, dia=dia,
                                                hora_inicio=inicio, hora_fin=fin))

    def preceptor(self, curso, division, turno, nombre, dia):
        self.insertar('horarios_preceptores', dict(curso=curso, division=division, turno=turno,
                                                  preceptor=nombre, dia=dia, tipo='TITULAR'))

    def consultar(self, op, p, estado=200, cabeceras=None):
        r = self.client.post(PREFIJO + '/' + op, json=p, headers=cabeceras or self.bearer)
        self.assertEqual(r.status_code, estado, r.get_data(as_text=True))
        salida = r.get_json()
        contratos.validar(salida, consultas.CONTRATOS[op]['salida'], 'salida')
        return salida

    def test_roles_multiples_y_alias_explicito_sin_fusion_aproximada(self):
        salida = self.consultar('personas', {'nombre': 'pérez a'})
        self.assertEqual(salida['personas'], [{'nombre': 'PEREZ ANA',
                          'roles': ['EMATP EERR', 'Jefatura', 'docente', 'preceptor']}])
        lista = self.consultar('personas', {'rol': 'preceptor'})['personas']
        self.assertNotIn('FALTA', [p['nombre'] for p in lista])
        self.assertEqual(len(lista), 4)
        self.assertEqual(self.consultar('personas', {'nombre': 'ZZZZZZZZZZ'})['personas'], [])

    def test_multiples_roles_filtra_antes_de_paginar_y_conserva_roles(self):
        self.personal('PEREZ JUAN', 'EMATP', 'LUNES', '10:00', '12:00')
        self.personal('A MONOROL', 'OTRO', 'LUNES', '08:00', '09:00')
        self.parche(sys.modules[f'{PAQUETE}.consultas.personas'], 'MAX_PERSONAS', 1)
        filtros = {'multiples_roles': True}
        primera = self.consultar('personas', filtros)
        self.assertEqual(primera['personas'][0]['nombre'], 'PEREZ ANA')
        self.assertEqual(len(primera['personas'][0]['roles']), 4)
        segunda = self.consultar('personas', {**filtros, 'cursor': primera['siguiente']})
        self.assertEqual(segunda['personas'], [{'nombre': 'PEREZ JUAN', 'roles': ['EMATP', 'docente']}])
        self.assertNotIn('siguiente', segunda)
        cruzada = self.consultar('personas', {**filtros, 'rol': 'preceptor'})
        self.assertEqual([p['nombre'] for p in cruzada['personas']], ['PEREZ ANA'])
        self.assertNotIn('siguiente', cruzada)
        self.assertEqual(self.consultar('personas', {**filtros, 'nombre': 'ROMERO'})['personas'], [])
        self.assertEqual(self.consultar('personas', {'nombre': 'ROMERO', 'multiples_roles': False})['personas'][0]['nombre'], 'ROMERO')
        self.consultar('personas', {'multiples_roles': False}, 400)
        self.consultar('personas', {'multiples_roles': 'true'}, 400)
        error = self.consultar('personas', {'rol': 'docente', 'cursor': primera['siguiente']}, 409)
        self.assertEqual(error['error']['codigo'], 'consulta_vencida')

    def test_get_multiples_roles_y_esquemas_comparten_filtro(self):
        url = PREFIJO + '/personas'
        for filtros in ({'multiples_roles': 'true'}, {'multiples_roles': 'true', 'rol': 'preceptor'}):
            r = self.client.get(url, query_string={'token': 'clave-sintética-ñ', **filtros})
            self.assertEqual(r.status_code, 200)
            self.assertEqual([p['nombre'] for p in r.get_json()['personas']], ['PEREZ ANA'])
        r = self.client.get(url, query_string={'token': 'clave-sintética-ñ', 'multiples_roles': 'false'})
        self.assertEqual(r.status_code, 400)
        schema = self.client.get(PREFIJO + '/openapi.json', headers=self.bearer).get_json()
        parametros = schema['paths'][url]['get']['parameters']
        self.assertEqual(next(p for p in parametros if p['name'] == 'multiples_roles')['schema']['type'], 'boolean')

    def test_nombres_aproximados_son_candidatos_y_no_horarios(self):
        candidatos = self.consultar('personas', {'nombre': 'PEREZ'})['personas']
        self.assertEqual({p['nombre'] for p in candidatos}, {'PEREZ ANA', 'PEREZ JUAN'})
        r = self.consultar('horarios', {'tipo': 'persona', 'valores': ['ROMERO', 'PEREZ']}, 409)
        self.assertEqual(r['error']['codigo'], 'persona_ambigua')
        self.assertNotIn('horarios', r)
        self.personal('ANA', 'OTRO', 'LUNES', '08:00', '09:00')
        r = self.consultar('personas', {'nombre': 'ANA'})
        self.assertEqual([p['nombre'] for p in r['personas']], ['ANA'])

    def test_anio_semana_agrupaciones_y_dias_vacios(self):
        r = self.consultar('horarios', {'tipo': 'curso', 'anio': 3})
        self.assertEqual([h['curso'] for h in r['horarios']], ['3° A', '3° B'])
        self.assertEqual(set(r['horarios'][0]['dias']), set(comun.DIAS[:5]))
        self.assertEqual(r['horarios'][0]['dias']['martes'], [])
        bloques = r['horarios'][0]['dias']['lunes']
        self.assertEqual({b['grupo'] for b in bloques}, {'A', 'B'})
        self.assertTrue(all(b['superposicion_permitida'] for b in bloques))
        self.assertEqual(bloques[0]['inicio'], '07:40')

    def test_suplente_activo_titular_licencia_y_falta_suplente(self):
        r = self.consultar('horarios', {'tipo': 'curso', 'valores': ['3 b'], 'dias': ['MIÉRCOLES', 'viernes']})
        bloques = r['horarios'][0]['dias']
        self.assertEqual(bloques['miercoles'][0]['profesor'], 'REEMPLAZO DOS')
        self.assertEqual(bloques['miercoles'][0]['titular_en_licencia'], 'TITULAR UNO')
        self.assertEqual((bloques['miercoles'][0]['inicio'], bloques['miercoles'][0]['fin']), ('17:00', '19:00'))
        self.assertIsNone(bloques['viernes'][0]['profesor'])
        r = self.consultar('horarios', {'tipo': 'persona', 'valores': ['TITULAR UNO', 'REEMPLAZO DOS']})
        self.assertTrue(r['horarios'][0]['dias']['miercoles'][0]['en_licencia'])
        self.assertEqual(r['horarios'][0]['dias']['miercoles'][0]['suplente'], 'REEMPLAZO DOS')
        self.assertNotIn('en_licencia', r['horarios'][1]['dias']['miercoles'][0])

    def test_persona_roles_actividad_y_turno_sin_horas_incluso_con_rango(self):
        r = self.consultar('horarios', {'tipo': 'persona', 'valores': ['PEREZ ANA'],
                                      'dias': ['lunes'], 'desde': '10:00', 'hasta': '11:00'})
        a = r['horarios'][0]['dias']['lunes']
        self.assertEqual([b['rol'] for b in a], ['EMATP EERR', 'preceptor'])
        self.assertEqual(a[0]['fin'], '12:00')
        self.assertEqual(a[1], {'rol': 'preceptor', 'turno': 'tarde', 'cursos': ['3° A']})
        solo = self.consultar('horarios', {'tipo': 'persona', 'valores': ['PEREZ ANA'],
                                          'roles': ['docente'], 'dias': ['lunes']})
        self.assertEqual(len(solo['horarios'][0]['dias']['lunes']), 2)

    def test_preceptores_todos_y_dos_contraturnos_y_dias(self):
        r = self.consultar('preceptores', {})
        self.assertNotIn('sin_registro', r)
        self.assertNotIn('siguiente', r)
        self.assertEqual(len(r['preceptores']), 4)
        por_nombre = {p['nombre']: p for p in r['preceptores']}
        self.assertEqual(por_nombre['PEREZ ANA']['asignaciones'][0]['funcion'], 'principal')
        self.assertEqual(por_nombre['PEREZ ANA']['asignaciones'][0]['dias'], ['lunes'])
        for n in ('ROMERO', 'LOPEZ'):
            self.assertEqual(por_nombre[n]['asignaciones'][0]['funcion'], 'contraturno')
        self.assertEqual(r['vacantes'][0]['curso'], '3° B')
        self.assertEqual(self.consultar('preceptores', {'nombres': ['ROMERO'], 'turno': 'tarde'})['preceptores'], [])

    def test_vacante_distinta_sin_registro_y_turno_nominal_no_inventado(self):
        r = self.consultar('preceptores', {'cursos': ['3º B'], 'turno': 'MAÑANA', 'dias': ['lunes', 'martes']})
        self.assertEqual(r['vacantes'][0]['dias'], ['lunes'])
        self.assertEqual(r['sin_registro'][0]['dias'], ['martes'])
        self.preceptor('4', '3', 'VESPERTINO', 'ROMERO', 'LUNES')
        r = self.consultar('preceptores', {'cursos': ['4° 3'], 'dias': ['lunes']})
        self.assertIsNone(r['preceptores'][0]['asignaciones'][0]['funcion'])
        self.assertEqual(r['avisos'], [{'curso': '4° 3', 'codigo': 'turno_nominal_no_configurado'}])

    def test_preceptores_mas_de_veinte_caben_en_una_pagina_normal(self):
        for i in range(46):
            self.preceptor('3', 'A', 'TARDE', f'NOMBRE {i:02}', 'LUNES')
        r = self.consultar('preceptores', {})
        self.assertEqual(len(r['preceptores']), 50)
        self.assertIn('vacantes', r)  # Los metadatos no ocupan cupos de persona.
        self.assertNotIn('siguiente', r)

    def test_catalogos_fuentes_aula_conocida_vacia_y_piso(self):
        r = self.consultar('catalogos', {'incluir': ['cursos', 'aulas', 'roles']})
        self.assertEqual(r['cursos'], {'3': ['A', 'B'], '4': ['3']})
        self.assertEqual(r['aulas']['Piso 1'], ['11', '12', '13'])
        h = self.consultar('horarios', {'tipo': 'aula', 'valores': ['Aula 13'], 'dias': ['lunes']})
        self.assertEqual(h['horarios'], [{'aula': '13', 'dias': {'lunes': []}}])
        h = self.consultar('horarios', {'tipo': 'aula', 'piso': 'piso 1', 'dias': ['lunes']})
        self.assertEqual(len(h['horarios']), 3)
        self.consultar('horarios', {'tipo': 'aula', 'valores': ['9999']}, 404)

    def test_catalogo_nombres_completo_y_compacto_solo_cuando_se_pide(self):
        self.assertEqual(self.consultar('personas', {'nombre': 'ZZZZZZZZZZ'})['personas'], [])
        self.assertNotIn('nombres', self.consultar('catalogos', {}))
        esperados = {'PEREZ ANA', 'PEREZ JUAN', 'TITULAR UNO', 'TITULAR DOS',
                     'REEMPLAZO DOS', 'OTRA', 'ROMERO', 'LOPEZ'}
        for i in range(60):
            n = f'PERSONA {i:02}'
            self.personal(n, 'OTRO', 'LUNES', '08:00', '09:00')
            esperados.add(n)
        salida = self.consultar('catalogos', {'incluir': ['nombres']})
        self.assertEqual(salida, {'nombres': sorted(esperados)})
        # Los nombres salen completos en una llamada, sin fichas ni paginación de personas.
        self.assertNotIn('FALTA', salida['nombres'])
        self.assertEqual(salida['nombres'].count('PEREZ ANA'), 1)
        url = PREFIJO + '/catalogos'
        respuesta = self.client.get(url, query_string={'token': 'clave-sintética-ñ', 'incluir': 'nombres'})
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.get_json(), salida)
        self.assertEqual(self.client.get(url, query_string={'incluir': 'nombres'}).status_code, 401)
        juntos = self.consultar('catalogos', {'incluir': ['cursos', 'aulas', 'roles', 'nombres']})
        self.assertEqual(set(juntos), {'cursos', 'aulas', 'roles', 'nombres'})

    def test_preceptor_sin_division_no_inventa_curso_y_conserva_asignacion(self):
        self.preceptor('3', '', 'MAÑANA', 'SIN DIVISION', 'LUNES')
        self.assertEqual(self.consultar('catalogos', {})['cursos'], {'3': ['A', 'B'], '4': ['3']})
        self.assertEqual([h['curso'] for h in self.consultar('horarios',
                         {'tipo': 'curso', 'anio': 3})['horarios']], ['3° A', '3° B'])
        for filtros in ({}, {'anio': 3}):
            with self.subTest(filtros=filtros):
                r = self.consultar('preceptores', filtros)
                parcial = next(p for p in r['preceptores'] if p['nombre'] == 'SIN DIVISION')
                self.assertEqual(parcial['asignaciones'], [{'curso': '3°', 'turno': 'mañana',
                                  'funcion': None, 'dias': ['lunes']}])
                self.assertIn({'curso': '3°', 'codigo': 'division_no_informada'}, r['avisos'])
                self.assertFalse(any(a['curso'] == '3°' for a in r.get('sin_registro', [])))
        r = self.consultar('preceptores', {'cursos': ['3 A']})
        self.assertNotIn('SIN DIVISION', [p['nombre'] for p in r['preceptores']])
        r = self.consultar('horarios', {'tipo': 'persona', 'valores': ['SIN DIVISION']})
        self.assertEqual(r['horarios'][0]['dias']['lunes'][0]['cursos'], ['3°'])
        self.consultar('horarios', {'tipo': 'curso', 'valores': ['3']}, 404)

    def test_rango_invertido_o_vacio_se_envia_original_sin_bloquear_consulta(self):
        self.clase('3', 'A', 'INVERTIDO', 'PEREZ ANA', '13', 'Martes', '12:30', '12:00')
        self.clase('3', 'A', 'VACIO', 'PEREZ ANA', '13', 'Martes', '12:30', '12:30')
        for tipo, valor in (('curso', '3 A'), ('persona', 'PEREZ ANA'), ('aula', '13')):
            for extra in ({}, {'desde': '07:00', 'hasta': '08:00'}):
                with self.subTest(tipo=tipo, extra=extra):
                    h = self.consultar('horarios', {'tipo': tipo, 'valores': [valor],
                                                  'dias': ['martes'], **extra})['horarios'][0]
                    bloques = [b for b in h['dias']['martes'] if b.get('materia') in ('INVERTIDO', 'VACIO')]
                    self.assertEqual([(b['inicio'], b['fin']) for b in bloques],
                                     [('12:30', '12:00'), ('12:30', '12:30')])
                    self.assertTrue(all('horario_inconsistente' not in b for b in bloques))
        with patch.object(config, 'ahora', return_value=datetime(2026, 11, 3, 9, 0)):
            r = self.consultar('horarios', {'tipo': 'aula', 'valores': ['13'], 'ahora': True})
            self.assertEqual(len(r['horarios'][0]['dias']['martes']), 2)
        self.personal('PERSONAL', 'EMATP', 'MARTES', '12:30', '12:00')
        h = self.consultar('horarios', {'tipo': 'persona', 'valores': ['PERSONAL']})['horarios'][0]
        self.assertEqual(h['dias']['martes'][0], {'rol': 'EMATP', 'inicio': '12:30', 'fin': '12:00'})

    def test_clase_sin_curso_conserva_horario_personal_y_aula_con_null(self):
        self.clase('', '', 'MATERIA', 'SIN CURSO', '13', 'Lunes', '10:00', '12:00')
        for tipo, valor in (('persona', 'SIN CURSO'), ('aula', '13')):
            with self.subTest(tipo=tipo):
                h = self.consultar('horarios', {'tipo': tipo, 'valores': [valor]})['horarios'][0]
                self.assertIsNone(h['dias']['lunes'][0]['curso'])
                self.assertEqual(h['dias']['lunes'][0]['inicio'], '10:00')

    def test_limites_rango_estricto_y_ahora_reloj_escolar_fin_semana(self):
        r = self.consultar('horarios', {'tipo': 'curso', 'valores': ['3 A'], 'dias': ['lunes'],
                                       'desde': '09:20', 'hasta': '10:00'})
        self.assertEqual(r['horarios'][0]['dias']['lunes'], [])
        with patch.object(config, 'ahora', return_value=datetime(2026, 11, 2, 9, 20)):
            r = self.consultar('horarios', {'tipo': 'curso', 'valores': ['3 A'], 'ahora': True})
            self.assertEqual(r['horarios'][0]['dias']['lunes'], [])
            self.assertEqual(r['momento'], {'fecha': '2026-11-02', 'hora': '09:20'})
        with patch.object(config, 'ahora', return_value=datetime(2026, 11, 7, 9, 0)):
            r = self.consultar('horarios', {'tipo': 'aula', 'ahora': True})
            self.assertEqual(r['horarios'][0]['dias']['sabado'][0]['inicio'], '09:00')

    def test_errores_de_parametros_no_horarios_vacios(self):
        casos = [None, [], {}, {'tipo': 'persona'}, {'tipo': 'curso', 'anio': True},
                 {'tipo': 'curso', 'anio': 3, 'valores': ['3 A']},
                 {'tipo': 'curso', 'anio': 3, 'ahora': True, 'dias': ['lunes']},
                 {'tipo': 'curso', 'anio': 3, 'desde': '09:20'},
                 {'tipo': 'curso', 'anio': 3, 'desde': '10:00', 'hasta': '09:00'},
                 {'tipo': 'aula'}, {'tipo': 'aula', 'anio': 3},
                 {'tipo': 'curso', 'anio': 3, 'roles': ['docente']},
                 {'tipo': 'curso', 'anio': 3, 'dias': ['inventado']},
                 {'tipo': 'curso', 'anio': 3, 'sql': 'SELECT *'},
                 {'tipo': 'persona', 'valores': ['PEREZ ANA'] * 21}]
        for p in casos:
            with self.subTest(p=p):
                self.consultar('horarios', p, 400)
        self.consultar('catalogos', {'incluir': ['roles'], 'anio': 3}, 400)
        self.consultar('preceptores', {'cursos': ['3 A'], 'anio': 3}, 400)
        self.consultar('personas', {}, 400)

    def test_base_inexistente_vacia_corrupta_e_intervalo_invalido(self):
        with patch.object(datos, 'DB_PATH', str(self.db.with_name('ausente.db'))):
            self.consultar('personas', {'rol': 'docente'}, 503)
        self.assertFalse(self.db.with_name('ausente.db').exists())
        with closing(sqlite3.connect(self.db)) as con, con:
            con.execute("UPDATE clases SET hora_fin='imposible' WHERE materia='MATEMATICA'")
        self.consultar('horarios', {'tipo': 'curso', 'valores': ['3 A']}, 422)
        with closing(sqlite3.connect(self.db)) as con, con:
            for tabla in ('clases', 'personal_no_docente', 'horarios_preceptores'):
                con.execute(f'DELETE FROM {tabla}')
        self.consultar('catalogos', {}, 503)
        self.db.write_bytes(b'archivo corrupto')
        self.consultar('catalogos', {}, 503)

    def test_autenticacion_bearer_sesion_csrf_y_aislamiento_actualizar(self):
        r = self.client.post(PREFIJO + '/catalogos', json={})
        self.assertEqual(r.status_code, 401)
        self.consultar('catalogos', {})
        with self.client.session_transaction() as sesion:
            self.assertNotIn(acceso.SESSION_FLAG, sesion)
        self.assertFalse(self.client.get('/app-horarios/api/sesion').get_json()['autenticado'])
        with patch.object(datos, 'actualizar_desde_sheets') as actualizar:
            r = self.client.post('/app-horarios/api/actualizar', json={}, headers={**self.bearer, 'X-Mitre': '1'})
            self.assertEqual(r.status_code, 401)
            actualizar.assert_not_called()
        r = self.client.post('/app-horarios/api/entrar', json={'clave': 'clave-sintética-ñ'}, headers={'X-Mitre': '1'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.post(PREFIJO + '/catalogos', json={}).status_code, 403)
        self.consultar('catalogos', {}, cabeceras={'X-Mitre': '1'})
        self.assertEqual(self.client.post(PREFIJO + '/catalogos', json={},
                                         headers={'Authorization': 'Bearer invalida'}).status_code, 401)

    def test_limite_intentos_compartido_y_clave_rotada(self):
        for _ in range(acceso.MAX_INTENTOS - 1):
            self.client.post(PREFIJO + '/catalogos', json={}, headers={'Authorization': 'Bearer mala'})
        r = self.client.post('/app-horarios/api/entrar', json={'clave': 'mala'}, headers={'X-Mitre': '1'})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.client.post(PREFIJO + '/catalogos', json={}, headers=self.bearer).status_code, 429)
        acceso._INTENTOS_FALLIDOS.clear()
        with patch.object(acceso, '_clave', return_value='otra-clave'):
            self.assertEqual(self.client.post(PREFIJO + '/catalogos', json={}, headers=self.bearer).status_code, 401)

    def test_contratos_y_openapi_autenticados_comparten_esquemas(self):
        self.assertEqual(self.client.get(PREFIJO + '/contratos').status_code, 401)
        r = self.client.get(PREFIJO + '/contratos', headers=self.bearer)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.get_json()['herramientas']), 4)
        r = self.client.get(PREFIJO + '/openapi.json', headers=self.bearer)
        self.assertEqual(r.status_code, 200)
        documento = r.get_json()
        self.assertEqual(len(documento['paths']), 4)
        for op, c in consultas.CONTRATOS.items():
            schema = documento['paths'][PREFIJO + '/' + op]['post']['requestBody']['content']['application/json']['schema']
            self.assertEqual(schema, c['entrada'])

    def test_paginacion_entidades_completas_firma_y_cambio_snapshot(self):
        p = {'tipo': 'curso', 'anio': 3}
        limite = len(comun.compacto(self.consultar('horarios', p))) - 1
        with patch.object(comun, 'MAX_CARACTERES', limite):
            primera = self.consultar('horarios', p)
            self.assertIn('siguiente', primera)
            self.assertEqual(len(primera['horarios']), 1)
            segunda = self.consultar('horarios', dict(p, cursor=primera['siguiente']))
            self.assertEqual(segunda['horarios'][0]['curso'], '3° B')
            self.assertNotIn('siguiente', segunda)
            self.consultar('horarios', dict(p, cursor=primera['siguiente'] + 'x'), 409)
            self.consultar('horarios', dict(p, dias=['lunes'], cursor=primera['siguiente']), 409)
            self.personal('NUEVA PERSONA', 'CARGO', 'LUNES', '08:00', '09:00')
            self.consultar('horarios', dict(p, cursor=primera['siguiente']), 409)
        with patch.object(comun, 'MAX_CARACTERES', 150):
            self.consultar('horarios', {'tipo': 'curso', 'anio': 3}, 422)

    def test_transaccion_unica_impide_mezclar_datos_durante_actualizacion(self):
        with closing(sqlite3.connect(self.db)) as con:
            con.execute('PRAGMA journal_mode=WAL')
        conectar = sqlite3.connect
        lecturas = []
        class Conexion(sqlite3.Connection):
            def execute(con, sql, *args):
                lecturas.append(sql)
                resultado = super().execute(sql, *args)
                if sql.startswith('SELECT curso, division, turno'):
                    with closing(conectar(self.db)) as escritor, escritor:
                        escritor.execute("UPDATE clases SET profesor='CAMBIO'")
                        escritor.execute("UPDATE personal_no_docente SET nombre='CAMBIO'")
                return resultado
        def conexion(*args, **kwargs):
            self.assertIn('mode=ro', args[0])
            return conectar(*args, **kwargs, factory=Conexion)
        with patch.object(sqlite3, 'connect', side_effect=conexion):
            s = comun.Snapshot(self.db)
        self.assertEqual(lecturas.count('BEGIN'), 1)
        self.assertNotIn('CAMBIO', s.padron)
        self.assertIn('PEREZ ANA', s.padron)
        self.assertNotEqual(s.revision, comun.Snapshot(self.db).revision)

    def test_mas_de_cincuenta_coincidencias_se_paginan_sin_perder_personas(self):
        for i in range(65):
            self.personal(f'COINCIDENCIA {i:02}', 'CARGO', 'LUNES', '08:00', '09:00')
        p = {'nombre': 'COINCIDENCIA'}
        primera = self.consultar('personas', p)
        segunda = self.consultar('personas', dict(p, cursor=primera['siguiente']))
        self.assertEqual(len(primera['personas']), 50)
        self.assertEqual(len(segunda['personas']), 15)
        self.assertNotIn('siguiente', segunda)

    def test_salida_invalida_falla_como_datos_y_no_parametros_del_usuario(self):
        self.personal('PERSONA', 'X' * 201, 'LUNES', '08:00', '09:00')
        r = self.consultar('personas', {'nombre': 'PERSONA'}, 422)
        self.assertEqual(r['error']['codigo'], 'datos_inconsistentes')

    def test_paginas_por_anio_respetan_veinte_cursos_y_revision_configuracion(self):
        for i in range(24):
            self.clase('5', str(i), 'MATERIA', 'DOCENTE', '13', 'Lunes', '08:00', '09:00')
        p = {'tipo': 'curso', 'anio': 5}
        primera = self.consultar('horarios', p)
        segunda = self.consultar('horarios', dict(p, cursor=primera['siguiente']))
        self.assertEqual(len(primera['horarios']), 20)
        self.assertEqual(len(segunda['horarios']), 4)
        with patch.object(config, 'FLOOR_MAPPING', {'Piso 2': ['13']}):
            self.consultar('horarios', dict(p, cursor=primera['siguiente']), 409)

    def test_agrupar_cursos_por_turno_y_persona_y_no_reescribir_fuente_legacy(self):
        self.preceptor('3', 'B', 'TARDE', 'PEREZ ANA', 'LUNES')
        r = self.consultar('horarios', {'tipo': 'persona', 'valores': ['PEREZ ANA'],
                                       'roles': ['preceptor'], 'dias': ['lunes']})
        self.assertEqual(r['horarios'][0]['dias']['lunes'][0]['cursos'], ['3° A', '3° B'])
        self.consultar('horarios', {'tipo': 'curso', 'valores': ['3 B']})
        with closing(sqlite3.connect(self.db)) as con:
            self.assertEqual(con.execute("SELECT hora_inicio FROM clases WHERE materia='FISICA'").fetchone()[0], '16:60')


    def test_get_token_mismos_json_que_post_para_las_cuatro_operaciones(self):
        casos = [('catalogos', {'incluir': ['cursos', 'aulas', 'roles']}),
                 ('personas', {'nombre': 'pérez a'}),
                 ('horarios', {'tipo': 'curso', 'valores': ['3 A', '3 B'], 'dias': ['lunes', 'miercoles']}),
                 ('horarios', {'tipo': 'curso', 'anio': 3}),
                 ('horarios', {'tipo': 'persona', 'valores': ['PEREZ ANA'], 'roles': ['preceptor']}),
                 ('horarios', {'tipo': 'aula', 'dias': ['lunes'], 'desde': '08:00', 'hasta': '09:00'}),
                 ('preceptores', {}), ('preceptores', {'turno': 'mañana'})]
        for op, parametros in casos:
            with self.subTest(op=op, parametros=parametros):
                esperado = self.consultar(op, parametros)
                pares = [('token', 'clave-sintética-ñ')]
                for campo, valor in parametros.items():
                    pares.extend((campo, v) for v in valor) if isinstance(valor, list) else pares.append((campo, valor))
                r = self.client.get(PREFIJO + '/' + op, query_string=pares)
                self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
                self.assertEqual(r.get_json(), esperado)
                self.assertEqual(r.headers['Cache-Control'], 'no-store')
                self.assertEqual(r.headers['Referrer-Policy'], 'no-referrer')
                self.assertEqual(r.headers['X-Robots-Tag'], 'noindex, nofollow')

    def test_get_alias_valor_ahora_y_caracteres_reservados_en_clave(self):
        clave = 'espacio + & # ? / ñ'
        with patch.object(acceso, '_clave', return_value=clave):
            with patch.object(config, 'ahora', return_value=datetime(2026, 11, 2, 8, 0)):
                r = self.client.get(PREFIJO + '/horarios', query_string={
                    'token': clave, 'tipo': 'curso', 'valor': '3 A', 'ahora': 'true'})
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.get_json()['momento'], {'fecha': '2026-11-02', 'hora': '08:00'})
                self.assertEqual(len(r.get_json()['horarios'][0]['dias']['lunes']), 2)
        r = self.client.get(PREFIJO + '/horarios', query_string={
            'token': 'clave-sintética-ñ', 'tipo': 'curso', 'valor': '3 A', 'ahora': 'false'})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('momento', r.get_json())

    def test_get_rechaza_filtros_invalidos_repetidos_y_token_en_post(self):
        casos = [[('tipo', 'curso'), ('anio', 'tres')],
                 [('tipo', 'curso'), ('anio', '3.0')],
                 [('tipo', 'curso'), ('anio', '3'), ('anio', '4')],
                 [('tipo', 'curso'), ('valor', '3 A'), ('valores', '3 B')],
                 [('tipo', 'curso'), ('valor', '3 A'), ('ahora', '1')],
                 [('tipo', 'curso'), ('anio', '3'), ('sql', 'SELECT *')],
                 [('tipo', 'curso'), ('anio', '3'), ('desde', '08:00')]]
        for pares in casos:
            with self.subTest(pares=pares):
                r = self.client.get(PREFIJO + '/horarios', query_string=[('token', 'clave-sintética-ñ')] + pares)
                self.assertEqual(r.status_code, 400)
                self.assertEqual(r.get_json()['error']['codigo'], 'parametros_invalidos')
        self.assertEqual(self.client.get(PREFIJO + '/catalogos', query_string=[
            ('token', 'clave-sintética-ñ'), ('token', 'otra')]).status_code, 400)
        self.assertEqual(self.client.post(PREFIJO + '/catalogos', json={}, query_string={
            'token': 'clave-sintética-ñ'}).status_code, 400)

    def test_get_token_no_abre_sesion_ni_da_acceso_a_datos_y_actualizar(self):
        q = {'token': 'clave-sintética-ñ'}
        self.assertEqual(self.client.get(PREFIJO + '/catalogos', query_string=q).status_code, 200)
        with self.client.session_transaction() as sesion:
            self.assertNotIn(acceso.SESSION_FLAG, sesion)
        self.assertEqual(self.client.get('/app-horarios/api/datos', query_string=q).status_code, 401)
        with patch.object(datos, 'actualizar_desde_sheets') as actualizar:
            self.assertEqual(self.client.post('/app-horarios/api/actualizar', query_string=q,
                                             headers={'X-Mitre': '1'}).status_code, 401)
            actualizar.assert_not_called()
        self.assertEqual(self.client.get(PREFIJO + '/catalogos').status_code, 401)
        self.assertEqual(self.client.get(PREFIJO + '/catalogos', query_string={'token': 'mala'}).status_code, 401)
        with self.client.session_transaction() as sesion:
            sesion[acceso.SESSION_FLAG] = True
        self.assertEqual(self.client.get(PREFIJO + '/catalogos', query_string={'token': 'mala'}).status_code, 401)
        for _ in range(acceso.MAX_INTENTOS - 2):
            self.client.get(PREFIJO + '/catalogos', query_string={'token': 'mala'})
        self.assertEqual(self.client.get(PREFIJO + '/catalogos', query_string=q).status_code, 429)

    def test_get_paginacion_igual_a_post_y_documentacion_del_transporte(self):
        q = {'token': 'clave-sintética-ñ', 'tipo': 'curso', 'anio': 3}
        limite = len(comun.compacto(self.consultar('horarios', {'tipo': 'curso', 'anio': 3}))) - 1
        with patch.object(comun, 'MAX_CARACTERES', limite):
            r = self.client.get(PREFIJO + '/horarios', query_string=q)
            primera = r.get_json()
            self.assertEqual(len(primera['horarios']), 1)
            r = self.client.get(PREFIJO + '/horarios', query_string={**q, 'cursor': primera['siguiente']})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.get_json()['horarios'][0]['curso'], '3° B')
            self.assertNotIn('siguiente', r.get_json())
        for ruta in ('contratos', 'openapi.json'):
            r = self.client.get(PREFIJO + '/' + ruta, query_string={'token': 'clave-sintética-ñ'})
            self.assertEqual(r.status_code, 200)
        doc = r.get_json()
        self.assertEqual(doc['components']['securitySchemes']['horariosTokenUrl']['in'], 'query')
        for operacion in consultas.CONTRATOS:
            self.assertIn('get', doc['paths'][PREFIJO + '/' + operacion])



    def test_pdf_token_descarga_real_sin_sesion_y_no_acepta_clave_invalida(self):
        ruta = '/horarios/export/pdf/curso/3%20A'
        self.assertEqual(self.client.get(ruta).status_code, 401)
        self.assertEqual(self.client.get(ruta, query_string={'token': 'mala'}).status_code, 401)
        for camino in (ruta, '/horarios/export/pdf/cursos/3%20A,3%20B',
                       '/horarios/export/pdf/cursos/todos',
                       '/horarios/export/pdf/planilla_preceptores'):
            r = self.client.get(camino, query_string={'token': 'clave-sintética-ñ'})
            self.assertEqual(r.status_code, 200, r.get_data(as_text=True) if r.status_code != 200 else '')
            self.assertEqual(r.mimetype, 'application/pdf')
            self.assertTrue(r.data.startswith(b'%PDF-'))
            self.assertEqual(r.headers['Cache-Control'], 'no-store')
            self.assertEqual(r.headers['Referrer-Policy'], 'no-referrer')
            self.assertNotIn('clave-sint', r.headers.get('Content-Disposition', ''))
            r.close()
        with self.client.session_transaction() as sesion:
            self.assertNotIn(acceso.SESSION_FLAG, sesion)
            sesion[acceso.SESSION_FLAG] = True
        self.assertEqual(self.client.get(ruta, query_string={'token': 'mala'}).status_code, 401)
        self.assertEqual(self.client.get(ruta, query_string=[('token', 'a'), ('token', 'b')]).status_code, 400)
        acceso._INTENTOS_FALLIDOS.clear()
        for _ in range(acceso.MAX_INTENTOS):
            self.client.get(ruta, query_string={'token': 'mala'})
        self.assertEqual(self.client.get(ruta, query_string={'token': 'clave-sintética-ñ'}).status_code, 429)


if __name__ == '__main__':
    unittest.main()
