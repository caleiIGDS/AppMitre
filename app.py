from flask import Flask, render_template, redirect, url_for
import os
from datetime import timedelta

# Carga .env en desarrollo local (API keys, secretos). En el hosting las env vars se setean
# aparte y este archivo ni existe, así que no falla si falta.
from dotenv import load_dotenv
load_dotenv()

import accesos
import gestion
import historia
import agente
import salidas
import horarios
from config import PRODUCCION, SESION_DIAS

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

# Gestión de recursos (/gestion) — módulo independiente con DB propia (gestion.db).
# init_db() en import para que también corra bajo gunicorn/WSGI (no solo en __main__).
app.register_blueprint(gestion.bp)
gestion.init_db()

# Historia institucional (/historia) — módulo hermano de gestion, DB propia (historia.db).
app.register_blueprint(historia.bp)
historia.init_db()

# Asistente conversacional (/agente) — blueprint independiente con su propio gate.
app.register_blueprint(agente.bp)
agente.init_db()

# Salidas educativas (/salidas) — módulo independiente con DB propia (salidas.db).
app.register_blueprint(salidas.bp)
# Blueprint aparte y SIN gate: el link público /salidas/completar/<token> para que
# familias y estudiantes completen su Anexo VI/VII solos (ver salidas.py).
app.register_blueprint(salidas.bp_publico)
salidas.init_db()

# Sistema de horarios (/horarios) — sitio aparte: login propio (HORARIOS_CLAVE), config y
# datos propios, NO pasa por `accesos`. El paquete monta su gate al importarse; acá sólo
# se registra el blueprint y se crea el schema.
app.register_blueprint(horarios.bp)
horarios.init_db()

# Accesos y permisos (accesos.db) — junta el catálogo que declaró cada área, engancha los
# globals de Jinja y monta el canje de invitaciones + el panel /accesos. `horarios` NO
# está en la lista: tiene su propia contraseña, fuera de este sistema.
accesos.init_db()
accesos.registrar_app(app, [gestion, historia, agente, salidas])


@app.route('/salidas/normativa')
def normativa_visor():
	"""Visor público de la Resolución RESOC-2024-3871-GDEBA-DGCYE con todas las páginas
	y resaltado de frases específicas. Query params: ?pagina=N&buscar=frase (ambos opcionales)."""
	return render_template('salidas/normativa.html')


@app.route('/')
def raiz():
    """La raíz manda al sistema de horarios, que tiene su propio gate."""
    return redirect(url_for('horarios.index'))


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
