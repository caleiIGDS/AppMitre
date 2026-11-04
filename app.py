from flask import (Flask, Response, jsonify, redirect, render_template, request,
                   send_from_directory, url_for)
from werkzeug.security import safe_join
import os
from datetime import timedelta

# Carga el .env (API keys, secretos), acá y en el hosting: es el único lugar donde viven
# las variables de entorno. No falla si falta; las que son obligatorias en producción se
# exigen después, cada una en su módulo.
from dotenv import load_dotenv
load_dotenv()

import accesos
import gestion
import agente
import salidas
import horarios
from config import DIR_DATOS, PRODUCCION, RAIZ, SESION_DIAS


# ---------------------------------------------------------------------------
# Las bases están donde tienen que estar
# ---------------------------------------------------------------------------

# Dónde vivía cada cosa antes de que todas las bases se mudaran a `database/`.
_LAYOUT_VIEJO = (
    [os.path.join(RAIZ, os.path.basename(m.DB_PATH))
     for m in (gestion, accesos, salidas)]
    + [os.path.join(RAIZ, 'agente.db'),
       os.path.join(RAIZ, 'horarios', 'escuela.db'),
       os.path.join(RAIZ, 'inventarios'),
       os.path.join(RAIZ, 'backups')]
)


def _verificar_layout():
    """Frena el arranque si los datos quedaron en el lugar viejo.

    Sin esto, un deploy donde viaje el código pero no se corra `actualizar.py` sería
    silencioso y de la peor manera: la app no encontraría nada en `database/`, tampoco
    respaldos ahí (se mudan juntos), así que la guarda anti-pérdida de `crud.init_db` no
    saltaría y cada área arrancaría creando su base vacía — con los datos reales intactos
    tres carpetas más arriba, y la escuela cargando todo de nuevo encima. Mismo criterio
    que esa guarda: ante la duda, fallar ruidoso (ver dev-log/DECISIONS.md 2026-08-08).
    """
    quedaron = [r for r in _LAYOUT_VIEJO if os.path.exists(r)]
    if not quedaron:
        return
    lista = '\n'.join(f"    {os.path.relpath(r, RAIZ)}" for r in quedaron)
    raise RuntimeError(
        f"Los datos siguen en el lugar viejo: la app los buscaría en "
        f"{os.path.relpath(DIR_DATOS, RAIZ)}/ y arrancaría creándolos vacíos, mientras lo "
        f"bueno está en:\n{lista}\n\n"
        f"Correr la mudanza (no toca ninguna fila, sólo mueve archivos):\n"
        f"    python actualizar.py --dry-run\n"
        f"    python actualizar.py\n\n"
        f"Si esos archivos son sobras de una prueba y no datos reales, borralos.")


_verificar_layout()

app = Flask(__name__)

# Firma la cookie de sesión: es lo que sostiene todo el sistema de accesos. En producción
# se exige de verdad, porque con una clave conocida cualquiera se forja una sesión de admin.
_secret = os.environ.get('SECRET_KEY')
if not _secret:
    if PRODUCCION:
        raise RuntimeError(
            "Falta SECRET_KEY en el entorno. Sin ella la cookie de sesión es forjable "
            "y el gate de accesos no vale nada: no se arranca en producción.")
    # Estable a propósito y no aleatoria: si cambiara en cada arranque, el reloader de
    # Flask te desloguearía en cada Ctrl+S.
    _secret = 'appmitre-dev-inseguro'
    print("AVISO: SECRET_KEY no está seteada — usando la clave de desarrollo.")
app.secret_key = _secret

# Sin esto la cookie muere al cerrar el navegador y hay que re-tipear la clave cada vez.
# Con SESSION_REFRESH_EACH_REQUEST (default True) la expiración se corre en cada visita,
# así que quien usa la app no se desloguea nunca. Ver config.SESION_DIAS.
app.permanent_session_lifetime = timedelta(days=SESION_DIAS)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = PRODUCCION
if PRODUCCION:
    # Para que los links de invitación (url_for con _external) salgan en https.
    app.config['PREFERRED_URL_SCHEME'] = 'https'

# ---------------------------------------------------------------------------
# Estáticos: cachear un año y romper la caché por mtime
# ---------------------------------------------------------------------------
# El default de Flask manda `Cache-Control: no-cache`, que obliga al navegador a
# revalidar CADA archivo en CADA navegación. Medido contra el hosting: media docena de
# 304 de ~0.5s cada uno por página, sin que nada haya cambiado. Con un año de caché esos
# pedidos desaparecen y el botón Atrás vuelve a resolverse contra el disco.
#
# Lo que hace seguro el año es `static_v`: la URL lleva el mtime del archivo, así que
# guardar un .css cambia la URL y el navegador se baja la versión nueva sola. Antes esto
# se hacía a mano con `?v=N` y se había desincronizado — el MISMO gestion.css salía como
# v24, v25, v26 y v39 según el área, o sea cuatro copias del mismo archivo en la caché y
# una descarga nueva al saltar de /gestion a /agente.
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 31536000  # 1 año

_mtimes = {}


@app.template_global()
def static_v(filename):
    """URL de un estático con su mtime de cache-buster: `/static/gestion.css?v=1788377479`.

    En producción el resultado se memoriza: los archivos no cambian sin un Reload, que
    levanta un proceso nuevo igual. En desarrollo se mira el disco cada vez, o editar un
    .css no se vería hasta reiniciar (el reloader de Flask sólo vigila los .py).
    """
    if filename not in _mtimes or not PRODUCCION:
        ruta = os.path.join(app.static_folder, filename)
        try:
            _mtimes[filename] = int(os.path.getmtime(ruta))
        except OSError:
            # Un estático que falta no debería tumbar la página entera: se pide sin
            # versión y que el 404 aparezca en la consola del navegador, no acá.
            return url_for('static', filename=filename)
    return url_for('static', filename=filename, v=_mtimes[filename])


# Gestión de recursos — N inventarios estancos, cada uno con su .db, su clave y su
# encargado. Las pantallas son la app (/gestion, ver más abajo) y esto es su API JSON:
# `bp_api_registro` es la lista de inventarios y `bp_api` un inventario abierto.
# init_db() en import para que también corra bajo gunicorn/WSGI (no solo en __main__);
# pone al día el registro y cada inventario.
app.register_blueprint(gestion.bp_api_registro)
app.register_blueprint(gestion.bp_api)
gestion.init_db()

# Asistente conversacional (/agente) — blueprint independiente con su propio gate.
app.register_blueprint(agente.bp)
agente.init_db()

# Salidas educativas (/salidas) — módulo independiente con DB propia (salidas.db).
app.register_blueprint(salidas.bp)
# Blueprint aparte y SIN gate: el link público /salidas/completar/<token> para que
# familias y estudiantes completen su Anexo VI/VII solos (ver salidas.py).
app.register_blueprint(salidas.bp_publico)
salidas.init_db()

# Sistema de horarios — sitio aparte: clave propia (HORARIOS_CLAVE), config y datos
# propios, NO pasa por `accesos`. Las pantallas son la app (/horarios, ver más abajo); `bp`
# son los PDF (/horarios/export/...) y `bp_app` la API de la app. El paquete monta su gate
# al importarse; acá sólo se registran los blueprints y se crea el schema.
app.register_blueprint(horarios.bp)
app.register_blueprint(horarios.bp_app)
app.register_blueprint(horarios.bp_mcp)
horarios.init_db()

# Accesos y permisos (accesos.db) — junta el catálogo que declaró cada área, engancha los
# globals de Jinja y monta el canje de invitaciones + el panel /accesos. `horarios` NO
# está en la lista: tiene su propia contraseña, fuera de este sistema.
accesos.init_db()
accesos.registrar_app(app, [m for m in (gestion, agente, salidas)
                            if getattr(m, 'ACTIVA', True)])


@app.route('/salidas/normativa')
def normativa_visor():
	"""Visor público de la Resolución RESOC-2024-3871-GDEBA-DGCYE con todas las páginas
	y resaltado de frases específicas. Query params: ?pagina=N&buscar=frase (ambos opcionales)."""
	return render_template('salidas/normativa.html')


# ---------------------------------------------------------------------------
# Apps instalables (/gestion y /horarios)
# ---------------------------------------------------------------------------
# Las compila Vite desde frontend/ (ver agent_docs/app-instalable.md); Flask sólo las sirve.
# Cada una vive en su propia dirección para que el celular las instale como dos apps
# separadas, con su ícono y su memoria. Los archivos de assets/ llevan un hash en el
# nombre, así que se cachean un año; el resto (index.html, sw.js, manifest) se revalida
# siempre, que es lo que hace que una versión nueva llegue. Cualquier otra ruta es una
# pantalla de la app y devuelve index.html: la navegación la resuelve el router del navegador.
#
# Sus APIs siguen donde nacieron (/app/api y /app-horarios/api): son de la app, no se ven.
APP_DIST = os.path.join(RAIZ, 'app_dist')
APP_HORARIOS_DIST = os.path.join(RAIZ, 'app_horarios_dist')


def _servir_app(carpeta, ruta, como_compilar):
    if ruta.startswith('api/'):
        return jsonify({'error': 'No existe'}), 404
    archivo = safe_join(carpeta, ruta) if ruta else None
    if archivo and os.path.isfile(archivo):
        resp = send_from_directory(carpeta, ruta)
        resp.headers['Cache-Control'] = ('public, max-age=31536000, immutable'
                                         if ruta.startswith('assets/') else 'no-cache')
        return resp
    if not os.path.isfile(os.path.join(carpeta, 'index.html')):
        return f"La app todavía no está compilada: correr `{como_compilar}` en frontend/.", 503
    resp = send_from_directory(carpeta, 'index.html')
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


@app.route('/gestion')
def gestion_raiz():
    return redirect('/gestion/')


@app.route('/gestion/', defaults={'ruta': ''})
@app.route('/gestion/<path:ruta>')
def gestion_app(ruta):
    return _servir_app(APP_DIST, ruta, 'npm run build')


@app.route('/horarios')
def horarios_raiz():
    return redirect('/horarios/')


# Los PDF (/horarios/export/...) son rutas más específicas del blueprint `horarios`: Flask
# las prefiere a ésta, que se queda con todo lo demás.
@app.route('/horarios/', defaults={'ruta': ''})
@app.route('/horarios/<path:ruta>')
def horarios_app(ruta):
    return _servir_app(APP_HORARIOS_DIST, ruta, 'npm run build:horarios')


@app.get('/instructivo.md')
def instructivo_horarios():
    """Guía pública para consultar Horarios; no contiene credenciales ni datos."""
    respuesta = send_from_directory(app.root_path, 'instructivo-publico.md', mimetype='text/plain')
    respuesta.headers['Cache-Control'] = 'no-cache'
    return respuesta



@app.route('/')
def raiz():
    """La raíz manda a horarios, que tiene su propia clave."""
    return redirect('/horarios/')


# --- Las direcciones de antes: /app y /app-horarios -----------------------------------
# Hasta el 2026-10-05 las apps vivían ahí (y las páginas clásicas en /gestion y
# /horarios). Un link guardado o un acceso directo viejo llega a la pantalla equivalente.
#
# Un celular que ya tenía la app instalada trae además su service worker viejo, que
# contesta /app/... desde su caché sin preguntarle nada al servidor: el redirect no le
# llegaría nunca. Lo que sí pide siempre al servidor es su propio sw.js, para ver si hay
# versión nueva. Por eso en esa dirección va uno que se desinstala: borra su caché, se da
# de baja y recarga las pestañas, que ahora sí llegan al redirect.
SW_RETIRADO = """// Esta app se mudó (ver app.py): este service worker se desinstala solo.
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (evento) => evento.waitUntil((async () => {
  const alcance = self.registration.scope
  for (const nombre of await caches.keys()) {
    if (nombre.includes(alcance)) await caches.delete(nombre)
  }
  await self.registration.unregister()
  for (const cliente of await self.clients.matchAll({ type: 'window' })) cliente.navigate(cliente.url)
})()))
"""


def _sw_retirado():
    resp = Response(SW_RETIRADO, mimetype='text/javascript')
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


def _a_donde(destino):
    """El redirect con la misma query (los filtros de la lista, `volver`, `comparar`)."""
    query = request.query_string.decode()
    return redirect(destino + ('?' + query if query else ''))


@app.route('/app', defaults={'ruta': ''})
@app.route('/app/', defaults={'ruta': ''})
@app.route('/app/<path:ruta>')
def app_vieja(ruta):
    if ruta == 'sw.js':
        return _sw_retirado()
    if ruta.startswith('api/'):
        return jsonify({'error': 'No existe'}), 404
    if ruta == 'entrar':
        return _a_donde('/gestion/entrar')
    if ruta == 'gestion' or ruta == 'gestion/':
        return _a_donde('/gestion/inventarios')
    if ruta.startswith('gestion/'):
        return _a_donde('/' + ruta)
    return _a_donde('/gestion/')


@app.route('/app-horarios', defaults={'ruta': ''})
@app.route('/app-horarios/', defaults={'ruta': ''})
@app.route('/app-horarios/<path:ruta>')
def app_horarios_vieja(ruta):
    if ruta == 'sw.js':
        return _sw_retirado()
    if ruta.startswith('api/'):
        return jsonify({'error': 'No existe'}), 404
    return _a_donde('/horarios/' + ruta)


if __name__ == '__main__':
    # El arranque corre SOLO en el proceso padre. Con el reloader activo, Werkzeug levanta un
    # hijo (marcado con WERKZEUG_RUN_MAIN) que es el que sirve, y lo relanza entero cada vez
    # que se guarda un .py. `cargar_inicial` es idempotente, pero revisar la base y bajarla de
    # Sheets en cada Ctrl+S no tiene sentido. Sin reloader la variable no existe y el bloque
    # corre igual, así que la guarda no cambia nada en producción.
    if not os.environ.get('WERKZEUG_RUN_MAIN'):
        horarios.cargar_inicial()

    # use_reloader activo: al guardar un .py el server se recarga solo. Estuvo apagado un
    # tiempo y el costo fue real — se editaba el agente, el proceso viejo seguía sirviendo
    # el código anterior y parecía que el cambio no funcionaba. En Windows el problema se
    # disimula todavía más: Werkzeug abre el socket con SO_REUSEADDR, así que un segundo
    # `python app.py` arranca SIN error aunque el 5000 ya esté tomado, no recibe tráfico, y
    # quedan dos servers de los que contesta el más viejo.
    app.run(host='0.0.0.0', port=5000, debug=True)
