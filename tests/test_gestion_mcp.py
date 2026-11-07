"""Contrato MCP de Recursos: lectura aislada, concesión explícita y todas las fotos."""
import base64
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from unittest.mock import patch

import gestion
import gestion_mcp
import fotos_disco
from test_salidas_mcp import SalidasMCP


class GestionMCP(SalidasMCP):
    def setUp(self):
        super().setUp()
        import salidas
        raiz = Path(salidas.DB_PATH).parent
        for parche in (patch.object(gestion, 'DB_PATH', str(raiz / 'gestion.db')),
                       patch.object(gestion, 'DIR_INVENTARIOS', str(raiz)),
                       patch.object(fotos_disco, 'FOTOS_DIR', str(raiz))):
            parche.start()
            self.addCleanup(parche.stop)
        with closing(gestion.conectar_registro()) as con, con:
            con.executescript(gestion.SCHEMA_REGISTRO)
            con.executemany('INSERT INTO inventarios (id,slug,nombre,clave_hash,creado) VALUES (?,?,?,?,?)',
                            [(1, 'taller', 'Taller', 'hash-1', ''), (2, 'otro', 'Otro', 'hash-2', '')])
        with closing(sqlite3.connect(raiz / 'taller.db')) as con, con:
            con.executescript(gestion.SCHEMA)
            con.execute("INSERT INTO recursos (id,nombre,tipo,descripcion,estado,cantidad,fotos,alias) VALUES (1,'Pinzas','Instrumento','Descripción original','Funcional','3',?,'secreto')",
                        (json.dumps([{'id': 'a' * 32, 'tipo': 'image/png'}, {'id': 'b' * 32, 'tipo': 'image/png'}]),))
            con.execute("INSERT INTO recursos (id,nombre,estado) VALUES (2,'Viejo',?)", (gestion.ESTADO_BAJA,))
            con.executemany('INSERT INTO recurso_unidades(recurso_id,numero,ubicacion) VALUES (1,?,?)',
                            [(1, 'Armario'), (3, 'Armario'), (4, '')])
            con.execute("INSERT INTO kit_items (recurso_id,titulo,cantidad) VALUES (1,'Cable','2')")
        self.foto = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1sAAAAASUVORK5CYII=')
        for fid in ('a' * 32, 'b' * 32):
            (raiz / (fid + '.png')).write_bytes(self.foto)
        import accesos
        with closing(accesos.conectar()) as con, con:
            con.execute('UPDATE dispositivos SET permisos=? WHERE id=1',
                        (json.dumps(['salidas.leer', 'salidas.editar', 'inv:1/gestion.leer']),))

    def conectar_recursos(self):
        tokens, _ = self.oauth(inventarios=True)
        self.assertEqual(tokens.status_code, 200, tokens.text)
        return {'Authorization': 'Bearer ' + tokens.json['access_token']}

    def recurso(self, nombre, cabecera, **args):
        return self.mcp('tools/call', {'name': nombre, 'arguments': args}, headers=cabecera).json['result']

    def test_inventario_completo_y_fotos(self):
        headers = self.conectar_recursos()
        lista = self.recurso('listar_inventarios', headers)['structuredContent']
        self.assertEqual(lista['inventarios'], [{'slug': 'taller', 'nombre': 'Taller'}])
        inventario = self.recurso('consultar_inventario', headers, inventario='taller')['structuredContent']
        self.assertEqual(len(inventario['recursos']), 1)
        recurso = inventario['recursos'][0]
        self.assertEqual(recurso['cantidad'], 3)
        self.assertEqual(recurso['descripcion'], 'Descripción original')
        self.assertEqual(recurso['ubicaciones'], {'Armario': 2, 'Sin ubicación registrada': 1})
        self.assertEqual(recurso['kit'][0]['titulo'], 'Cable')
        self.assertNotIn('alias', recurso)
        self.assertNotIn('fotos', recurso)
        detalle = self.recurso('consultar_recurso', headers, inventario='taller', id=1)['structuredContent']
        self.assertEqual([u['numero'] for u in detalle['recursos'][0]['unidades']], [1, 3, 4])
        fotos = self.recurso('pedir_fotos_recursos', headers, inventario='taller', ids=[1])
        imagenes = [c for c in fotos['content'] if c['type'] == 'image']
        self.assertEqual(len(imagenes), 2)
        self.assertTrue(all(base64.b64decode(i['data']) == self.foto for i in imagenes))

    def test_aislamiento_y_revocacion(self):
        headers = self.conectar_recursos()
        for inv in ('otro', '../otro'):
            self.assertTrue(self.recurso('pedir_fotos_recursos', headers, inventario=inv, ids=[1])['isError'])
        for ids in ([True], [0], [], [1, 1], [999]):
            self.assertTrue(self.recurso('pedir_fotos_recursos', headers, inventario='taller', ids=ids)['isError'])
        import accesos
        with closing(accesos.conectar()) as con, con:
            con.execute("UPDATE dispositivos SET permisos='[\"salidas.editar\"]' WHERE id=1")
        self.assertTrue(self.recurso('consultar_inventario', headers, inventario='taller')['isError'])

    def test_conexion_anterior_no_gana_inventarios(self):
        tokens, _ = self.oauth()
        headers = {'Authorization': 'Bearer ' + tokens.json['access_token']}
        self.assertEqual(self.recurso('listar_inventarios', headers)['structuredContent']['inventarios'], [])
        self.assertTrue(self.recurso('consultar_inventario', headers, inventario='taller')['isError'])

    def test_solo_recursos_no_da_salidas_y_sin_fotos_responde(self):
        import accesos
        with closing(accesos.conectar()) as con, con:
            con.execute('UPDATE dispositivos SET permisos=? WHERE id=1', ('["inv:1/gestion.leer"]',))
        headers = self.conectar_recursos()
        self.assertEqual(self.mcp('tools/call', {'name': 'buscar_salidas', 'arguments': {}}, headers=headers).status_code, 401)
        with closing(sqlite3.connect(Path(gestion.DIR_INVENTARIOS) / 'taller.db')) as con, con:
            con.execute("UPDATE recursos SET fotos='[]' WHERE id=1")
        respuesta = self.recurso('pedir_fotos_recursos', headers, inventario='taller', ids=[1])
        self.assertFalse(respuesta['isError'])
        self.assertEqual(respuesta['structuredContent']['recursos'][0]['fotos'], [])

    def test_solo_recursos_exige_consentimiento_y_explica_como_conectar(self):
        import accesos
        with closing(accesos.conectar()) as con, con:
            con.execute('UPDATE dispositivos SET permisos=? WHERE id=1', ('["inv:1/gestion.leer"]',))
        respuesta, _ = self.oauth()
        self.assertEqual(respuesta.status_code, 403)
        self.assertIn('marcá «Autorizar consulta de recursos»', respuesta.text)
        self.assertRegex(respuesta.text, r'name="inventarios"[^>]+required')
        self.assertIn('formnovalidate', respuesta.text)
        self.conectar_recursos()

    def test_consentimiento_recursos_sin_inventarios_no_concede_salidas(self):
        respuesta, _ = self.oauth(self.cliente(2), inventarios=True)
        self.assertEqual(respuesta.status_code, 403)
        self.assertIn('No hay inventarios accesibles', respuesta.text)

    def test_visitante_sin_sesion_recibe_pasos_de_acceso_sin_nombres_privados(self):
        respuesta, _ = self.oauth(self.anonimo)
        self.assertEqual(respuesta.status_code, 403)
        self.assertIn('Primero necesitás entrar a AppMitre', respuesta.text)
        self.assertIn('/gestion/entrar?volver=/inventarios', respuesta.text)
        self.assertIn('enlace de invitación', respuesta.text)
        self.assertIn('comprobá tu acceso', respuesta.text)
        self.assertNotIn('name="inventarios"', respuesta.text)
        self.assertNotIn('value="autorizar">Autorizar', respuesta.text)
        self.assertNotIn('Taller', respuesta.text)

    def test_500_recursos_sin_recorte_y_revision_actualizada(self):
        headers = self.conectar_recursos()
        anterior = self.recurso('consultar_inventario', headers, inventario='taller')['structuredContent']
        with closing(sqlite3.connect(Path(gestion.DIR_INVENTARIOS) / 'taller.db')) as con, con:
            con.executemany("INSERT INTO recursos (id,nombre,estado) VALUES (?,?,'Funcional')",
                            [(i, f'Recurso {i}') for i in range(3, 502)])
        actual = self.recurso('consultar_inventario', headers, inventario='taller')['structuredContent']
        self.assertEqual(len(actual['recursos']), 500)
        self.assertNotEqual(actual['revision'], anterior['revision'])

    def test_alias_segun_permiso_y_foto_faltante(self):
        headers = self.conectar_recursos()
        import accesos
        with closing(accesos.conectar()) as con, con:
            con.execute('UPDATE dispositivos SET permisos=? WHERE id=1',
                        ('["inv:1/gestion.leer", "inv:1/gestion.alias"]',))
        recurso = self.recurso('consultar_recurso', headers, inventario='taller', id=1)['structuredContent']['recursos'][0]
        self.assertEqual(recurso['alias'], 'secreto')
        Path(fotos_disco.ruta('a' * 32, 'image/png')).unlink()
        resultado = self.recurso('pedir_fotos_recursos', headers, inventario='taller', ids=[1])
        self.assertEqual(len([c for c in resultado['content'] if c['type'] == 'image']), 1)
        self.assertEqual(resultado['structuredContent']['recursos'][0]['fotos'][0]['estado'], 'archivo no disponible')

    def test_clave_de_inventario_y_rotacion(self):
        import accesos
        with closing(accesos.conectar()) as con, con:
            con.execute("UPDATE dispositivos SET permisos='[]' WHERE id=1")
        with self.editor.session_transaction() as ses:
            ses[gestion.CLAVES_SESION] = {'1': gestion._huella('hash-1')}
        headers = self.conectar_recursos()
        self.assertFalse(self.recurso('consultar_inventario', headers, inventario='taller')['isError'])
        with closing(gestion.conectar_registro()) as con, con:
            con.execute("UPDATE inventarios SET clave_hash='rotada' WHERE id=1")
        respuesta = self.mcp('tools/call', {'name': 'consultar_inventario', 'arguments': {'inventario': 'taller'}}, headers=headers)
        self.assertEqual(respuesta.status_code, 401)

    def test_comodin_dispositivo_no_abre_inventarios(self):
        import accesos
        with closing(accesos.conectar()) as con, con:
            con.execute('UPDATE dispositivos SET permisos=? WHERE id=1', ('["*"]',))
        headers = self.conectar_recursos()
        self.assertEqual(self.recurso('listar_inventarios', headers)['structuredContent']['inventarios'], [])
