"""API JSON de la app instalable de horarios (`/app-horarios/api`).

La app (frontend/horarios/, compilada a app_horarios_dist/) baja TODO el horario de una
vez y lo guarda en el dispositivo: buscar, comparar, la planilla general y TIEMPO REAL se
resuelven ahí, sin red. Al servidor sólo le pide:

  GET  /sesion      ¿hay sesión de horarios?
  POST /entrar      {clave} → abre la sesión (misma clave y mismo límite de intentos que
                    los PDF, ver `acceso.comprobar_clave`)
  POST /salir
  GET  /datos       todo el horario, con ETag: si nada cambió contesta 304 sin cuerpo
  POST /actualizar  rearma escuela.db desde la planilla

La app imprime localmente. Los exports PDF del servidor siguen disponibles para agentes externos con sesión o token en URL.

Mismo aislamiento que el resto del paquete: no importa `accesos` ni nada de afuera. Los
pedidos que escriben exigen la cabecera `X-Mitre` (defensa CSRF, igual que /app/api).
"""
import hashlib
import json
import os
import sqlite3

from flask import Blueprint, jsonify, request, session

from . import acceso, datos
from .materias import tipo_materia as _tipo_materia
from .rutas import _planilla_preceptores_con_turnos
from .config import (DIAS, ESCUELA_NOMBRE, ESCUELA_VERSION, ESPECIALIDAD_CURSOS, MATERIAS_PLAN,
                     FLOOR_MAPPING, GID_HORARIOS_PRECEPTORES, GID_PERSONAL_NO_DOCENTE,
                     GIDS_CURSOS, SHEET_ID, TURNO_CURSOS, TURNO_DEFAULT)

# Las columnas de `clases` que el front realmente lee. La lista es explícita y no un
# `SELECT *` por dos motivos: la tabla guarda `dni`, `telefono` y `email` de cada docente
# —que no tienen por qué viajar al navegador de cualquiera que abra el horario— y /datos
# devuelve las 2.299 filas de una, así que cada columna de más se paga entera.
# Al recortarlo el JSON pasó de 804 KB a 586 KB. Si el front empieza a usar otra
# columna (`tipo_aula`), hay que sumarla acá. `tipo_materia` la usa la pestaña MATERIAS
# (sale de MATERIAS_PLAN, no de la planilla);
# la especialidad no va por clase: es fija por división (`especialidades`, de config).
COLUMNAS_DASHBOARD = (
    'curso', 'division', 'materia', 'tipo_materia', 'profesor', 'aula', 'dia',
    'hora_inicio', 'hora_fin', 'grupo', 'superposicion',
    'suplente_activo', 'prof_suplente', 'sup_ini', 'sup_fin',
)

bp_app = Blueprint('horarios_app', __name__, url_prefix='/app-horarios/api')

ABIERTOS = {'horarios_app.sesion', 'horarios_app.entrar', 'horarios_app.salir'}

# Lo que sale de config.py también es parte de los datos (pisos, turnos, especialidades):
# si cambia con un deploy, el ETag tiene que cambiar aunque escuela.db sea la misma.
_HUELLA_CONFIG = hashlib.sha1(json.dumps(
    [DIAS, FLOOR_MAPPING, sorted(map(list, TURNO_CURSOS.items())), TURNO_DEFAULT,
     sorted(map(list, ESPECIALIDAD_CURSOS.items())), sorted(map(list, MATERIAS_PLAN.items())),
     ESCUELA_NOMBRE, ESCUELA_VERSION],
    ensure_ascii=False, default=str).encode()).hexdigest()[:12]


@bp_app.before_request
def _gate():
    # El adaptador nuevo tiene su propio gate: Bearer solo de lectura o sesión + CSRF.
    if request.blueprint == 'horarios_app.consultas':
        return None
    if request.method not in ('GET', 'HEAD') and not request.headers.get('X-Mitre'):
        return jsonify({'error': 'Pedido no permitido.'}), 403
    if request.endpoint not in ABIERTOS and not acceso.autenticado():
        return jsonify({'error': 'Hace falta la clave de horarios.'}), 401


@bp_app.get('/sesion')
def sesion():
    return jsonify({'autenticado': acceso.autenticado(),
                    'escuela': {'nombre': ESCUELA_NOMBRE, 'version': ESCUELA_VERSION}})


@bp_app.post('/entrar')
def entrar():
    cuerpo = request.get_json(silent=True) or {}
    resultado = acceso.comprobar_clave(request.remote_addr, str(cuerpo.get('clave') or ''))
    if resultado == 'bloqueado':
        return jsonify({'error': 'Demasiados intentos. Esperá 15 minutos y probá de nuevo.'}), 429
    if resultado == 'mal':
        return jsonify({'error': 'Contraseña incorrecta.'}), 422
    return sesion()


@bp_app.post('/salir')
def salir():
    session.pop(acceso.SESSION_FLAG, None)
    return jsonify({'autenticado': False})


def _etag():
    try:
        st = os.stat(datos.DB_PATH)
        marca = f'{st.st_mtime_ns}-{st.st_size}'
    except OSError:
        marca = 'sin-db'
    return f'"h-{marca}-{_HUELLA_CONFIG}"'


def _cursos(cur):
    """La lista de cursos del buscador, igual que la arma `rutas.index`."""
    cur.execute("SELECT DISTINCT curso, division FROM clases WHERE curso != '' ORDER BY curso, division")
    cursos = []
    for curso, division in cur.fetchall():
        valor = f"{curso}° {division}"
        especialidad = ESPECIALIDAD_CURSOS.get((curso, division), "ESPECIALIDAD")
        cursos.append({'valor': valor, 'display': f"{valor} ({especialidad})"})
    return cursos


@bp_app.get('/datos')
def todo():
    etag = _etag()
    if request.headers.get('If-None-Match') == etag:
        resp = jsonify()
        resp.status_code = 304
    else:
        con = datos.conectar()
        try:
            con.row_factory = sqlite3.Row
            cur = con.cursor()
            cur.execute('BEGIN')
            cur.execute(f"SELECT {', '.join(COLUMNAS_DASHBOARD)} FROM clases")
            clases = [dict(r) for r in cur.fetchall()]
            for c in clases:
                c['tipo_materia'] = _tipo_materia(c)
            cur.execute("SELECT DISTINCT profesor FROM clases WHERE profesor != '' ORDER BY profesor")
            profesores = [r[0] for r in cur.fetchall()]
            cur.execute("SELECT DISTINCT aula FROM clases WHERE aula != '' ORDER BY aula")
            aulas = [r[0] for r in cur.fetchall()]
            cursos = _cursos(cur)
            nombres = datos.obtener_lista_preceptores_horario(con)
            resp = jsonify({
                'clases': clases,
                'personal': datos.obtener_personal_todos(con),
                'preceptores': {
                    'horarios': {n: datos.obtener_horario_preceptor(n, con) for n in nombres},
                    'planilla': _planilla_preceptores_con_turnos(con),
                },
                'listas': {
                    'profesor': profesores,
                    'aula': aulas,
                    'curso': cursos,
                    'horario_preceptor': nombres,
                    'personal': datos.obtener_lista_personal(con),
                },
                # La especialidad de cada división es fija (config), no viene de la planilla.
                'especialidades': {f"{c} {d}": e for (c, d), e in ESPECIALIDAD_CURSOS.items()},
                'pisos': FLOOR_MAPPING,
                'dias': DIAS,
            })
        finally:
            con.close()
    resp.headers['ETag'] = etag
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


@bp_app.post('/actualizar')
def actualizar():
    """Publica la carga completa de Sheets o conserva el último horario válido."""
    try:
        datos.actualizar_desde_sheets(SHEET_ID, GIDS_CURSOS, GID_HORARIOS_PRECEPTORES,
                                     GID_PERSONAL_NO_DOCENTE)
    except Exception as e:
        print(f"Error actualizando datos: {e}")
        return jsonify({'error': str(e)}), 500
    return jsonify({'ok': True})


# Se monta una sola URL efectiva, dentro del prefijo API que ya sirve la aplicación.
from .api_consultas import bp_consultas  # noqa: E402
bp_app.register_blueprint(bp_consultas)
