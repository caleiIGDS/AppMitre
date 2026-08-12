"""Verificacion end-to-end de los tres niveles de acceso. No deja datos en accesos.db."""
import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import accesos
import app as appmod

app = appmod.app
fallos = []


def chk(etiqueta, obtenido, esperado):
    ok = obtenido == esperado
    if not ok:
        fallos.append(f'{etiqueta}: esperaba {esperado}, dio {obtenido}')
    print(f'  {"OK " if ok else "MAL"} {etiqueta:<42} {obtenido}')


def invitar(adm, etiqueta, perfil, permisos=None):
    r = adm.post('/accesos/invitar', data={
        'etiqueta': etiqueta, 'perfil': perfil,
        'permisos': permisos if permisos is not None else accesos.permisos_de_perfil(perfil)})
    return re.search(r'/acceso/([A-Za-z0-9_-]{20,})', r.get_data(as_text=True)).group(1)


print('\n=== 1. PUBLICO (sin sesion) ===')
pub = app.test_client()
chk('GET /  (SPA de horarios)', pub.get('/').status_code, 200)
chk('boton ACTUALIZAR oculto', 'btn-actualizar' in pub.get('/').get_data(as_text=True), False)
chk('POST /api/actualizar', pub.post('/api/actualizar').status_code, 401)
chk('GET /api/actualizar (ya no existe)', pub.get('/api/actualizar').status_code, 405)
chk('GET /gestion/  -> login', pub.get('/gestion/').status_code, 302)
chk('POST /agente/chat -> 401', pub.post('/agente/chat', json={'mensaje': 'hola'}).status_code, 401)

print('\n=== 2. ADMIN (clave) ===')
adm = app.test_client()
chk('login con la clave', adm.post('/gestion/login', data={'clave': 'MitreLLM'}).status_code, 302)
chk('cookie permanente', 'Expires=' in adm.post('/gestion/login', data={'clave': 'MitreLLM'}).headers.get('Set-Cookie', ''), True)
chk('GET /accesos/', adm.get('/accesos/').status_code, 200)
chk('GET /gestion/recursos/nuevo', adm.get('/gestion/recursos/nuevo').status_code, 200)
chk('GET /agente/log', adm.get('/agente/log').status_code, 200)
chk('boton ACTUALIZAR visible', 'btn-actualizar' in adm.get('/').get_data(as_text=True), True)

print('\n=== 3. INTERNO DE CONSULTA (link -> dispositivo) ===')
tok = invitar(adm, 'alumna 5B', 'interno-lectura')
lec = app.test_client()
chk('GET del link no lo quema', lec.get('/acceso/' + tok).status_code, 200)
chk('POST sin nombre -> 400', lec.post('/acceso/' + tok, data={'nombre': ''}).status_code, 400)
chk('el link sigue vivo', lec.get('/acceso/' + tok).status_code, 200)
chk('POST con nombre -> habilitado', lec.post('/acceso/' + tok, data={'nombre': 'Sofia Pereyra'}).status_code, 200)
chk('link reusado -> 410', app.test_client().get('/acceso/' + tok).status_code, 410)

print('  -- lectura --')
for ruta in ['/gestion/', '/gestion/recursos', '/gestion/prestamos', '/historia/', '/agente/']:
    chk(f'GET {ruta}', lec.get(ruta).status_code, 200)
print('  -- escritura: 403 --')
for ruta in ['/gestion/recursos/nuevo', '/gestion/carrito', '/historia/hitos/nuevo',
             '/agente/log', '/accesos/']:
    chk(f'GET {ruta}', lec.get(ruta).status_code, 403)
chk('POST /agente/confirmar', lec.post('/agente/confirmar', json={'token': 'x'}).status_code, 403)
chk('POST /gestion/recursos/1/eliminar', lec.post('/gestion/recursos/1/eliminar').status_code, 403)
chk('POST /api/actualizar', lec.post('/api/actualizar').status_code, 403)

print('  -- la UI no ofrece lo que no puede --')
h = lec.get('/gestion/recursos').get_data(as_text=True)
chk('sin boton CREAR', 'CREAR' in h, False)
chk('sin link Editar', '>Editar</a>' in h, False)
chk('widget del agente presente', 'agente-widget' in h, True)

print('\n=== 4. TOOLS QUE VE EL MODELO ===')
from agente.tools.esquemas import TOOLS_SCHEMA, tools_permitidas
lect = frozenset(accesos.permisos_de_perfil('interno-lectura'))
gest = frozenset(accesos.permisos_de_perfil('interno-gestion'))
chk('total declaradas', len(TOOLS_SCHEMA), 25)
chk('las que ve consulta', len(tools_permitidas(lect)), 15)
chk('las que ve gestion', len(tools_permitidas(gest)), 25)
chk('las que ve sin permisos', len(tools_permitidas(frozenset())), 0)
chk('eliminar_entidad NO viaja a consulta',
    'eliminar_entidad' in {t['name'] for t in tools_permitidas(lect)}, False)
chk('esquema en formato API puro',
    sorted({k for t in tools_permitidas(lect) for k in t}),
    ['description', 'input_schema', 'name'])

print('\n=== 5. + OTRO DISPOSITIVO Y REVOCACION ===')
disp = [d for d in accesos.listar_dispositivos() if d['nombre'] == 'Sofia Pereyra'][0]
r = adm.post('/accesos/otro/%d' % disp['id'])
tok2 = re.search(r'/acceso/([A-Za-z0-9_-]{20,})', r.get_data(as_text=True)).group(1)
lec2 = app.test_client()
lec2.post('/acceso/' + tok2, data={'nombre': 'Sofia Pereyra'})
chk('2do dispositivo entra', lec2.get('/agente/').status_code, 200)
adm.post('/accesos/revocar/%d' % disp['id'])
chk('revocado #1 -> fuera en el acto', lec.get('/agente/').status_code, 302)
chk('el #2 sigue adentro', lec2.get('/agente/').status_code, 200)
panel = adm.get('/accesos/').get_data(as_text=True)
chk('el panel muestra el nombre declarado', 'Sofia Pereyra' in panel, True)
chk('el panel muestra la etiqueta del admin', 'alumna 5B' in panel, True)

print('\n=== LIMPIEZA ===')
con = accesos.conectar()
con.execute('DELETE FROM dispositivos')
con.execute('DELETE FROM invitaciones')
con.execute("DELETE FROM sqlite_sequence WHERE name IN ('dispositivos','invitaciones')")
con.commit()
con.close()
print('  accesos.db vacia:', len(accesos.listar_dispositivos()) == 0)

print('\n' + '=' * 60)
if fallos:
    print(f'{len(fallos)} FALLO(S):')
    for f in fallos:
        print('  -', f)
    sys.exit(1)
print('TODO VERDE')
