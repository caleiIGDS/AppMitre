# salidas.py
# Salidas educativas — área de capa 2: guarda el legajo digital de cada salida (Anexos
# III a IX de la Resolución RESOC-2024-3871-GDEBA-DGCYE) y genera sus PDF.
#
# No pasa por el motor genérico de crud.py: una salida es un blob multi-anexo (datos
# comunes + personas + 7 anexos, cada uno con sus propios campos y hasta tablas de largo
# variable), no una fila plana de campos escalares. Sigue el mismo molde que gestion.py
# usa para préstamos: tabla y rutas propias, escritas a mano, reutilizando sólo lo
# compartido (accesos, crud.conectar/init_db, respaldos, layout de templates).
#
# Usa su propia DB (salidas.db). A diferencia de gestion.db/historia.db, sus filas tienen
# vigencia: al año de guardadas se borran solas (fila + PDFs) — ver _purgar_vencidas().
#
# El PDF de cada anexo NO se arma con un layout a mano por anexo: un solo renderer
# genérico recorre el Anexo<N>.json correspondiente (la carpeta Salidas/, que es la
# referencia completa y fiel del formulario en papel — incluye los campos de firma y de
# "lugar y fecha" que el formulario digital dejó de tipear a propósito). Los campos que
# no vinieron en lo que se guardó quedan en blanco en la hoja: es lo correcto, porque son
# justamente los que se completan a mano después de imprimir.

import json
import os
import shutil
import sys
from datetime import timedelta

from flask import Blueprint, abort, jsonify, render_template, request, send_file
from fpdf import FPDF

import accesos
import crud
from config import ESCUELA_LOGO, ESCUELA_NOMBRE, ESCUELA_VERSION, ahora

_AQUI = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_AQUI, 'salidas.db')
PDF_DIR = os.path.join(_AQUI, 'salidas_pdfs')
ANEXOS_JSON_DIR = os.path.join(_AQUI, 'Salidas')

PERMISOS = [
    ('salidas.leer', 'Ver las salidas guardadas y sus PDF', 'leer'),
    ('salidas.editar', 'Cargar y guardar salidas nuevas', 'escribir'),
]
GRUPO_PERMISOS = 'Salidas educativas'
PERMISO_LECTURA = 'salidas.leer'
PERMISO_ESCRITURA = 'salidas.editar'

# El testigo NO es la tabla `salidas`: esa queda vacía, legítimamente, cada vez que todas
# las salidas guardadas vencen y se purgan solas. crud.init_db trata una tabla testigo
# vacía con respaldos previos como señal de pérdida de datos (ver dev-log/DECISIONS.md,
# la pérdida real de 2026-08-08 que motivó ese chequeo) — con `salidas` como testigo, el
# primer año sin salidas activas tumbaría el arranque de la app. Por eso el testigo es
# esta tabla de un solo renglón, sembrada una vez y nunca tocada de nuevo.
PREFIJO_BACKUP = 'salidas'
TABLA_TESTIGO = 'salidas_meta'

# Vigencia de cada salida guardada: al año exacto se borra sola (fila + PDFs), sin
# papelera ni tabla de auditoría — confirmado con la dirección: se prioriza no retener
# datos sensibles (DNI, salud) más de lo necesario, en línea con el mismo criterio que ya
# se usó para el formulario ("no persistente en la compu que se esté usando").
VIGENCIA_DIAS = 365

ENTIDADES = {}  # no es una entidad de crud.py — ver el comentario de arriba del archivo

ANEXOS_NUMEROS = {'III': 3, 'IV': 4, 'V': 5, 'VI': 6, 'VII': 7, 'VIII': 8, 'IX': 9}

bp = Blueprint('salidas', __name__, url_prefix='/salidas')


def conectar():
    return crud.conectar(sys.modules[__name__])


SCHEMA = """
CREATE TABLE IF NOT EXISTS salidas_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    creado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS salidas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre_proyecto TEXT DEFAULT '',
    fecha_salida TEXT DEFAULT '',
    fecha_creacion TEXT NOT NULL,
    vigencia_hasta TEXT NOT NULL,
    datos_json TEXT NOT NULL
);
"""


def seed(cur):
    """Sólo siembra el testigo — no hay datos de ejemplo con sentido para una salida real."""
    cur.execute("INSERT OR IGNORE INTO salidas_meta (id, creado) VALUES (1, ?)", (ahora().isoformat(),))


def init_db():
    """Crea/migra la DB (crud.init_db: respalda, crea tablas, siembra el testigo la
    primera vez) y recién después purga las salidas vencidas — en ese orden, para que
    un año sin salidas activas nunca se confunda con un archivo perdido."""
    crud.init_db(sys.modules[__name__])
    _purgar_vencidas()


def _purgar_vencidas():
    con = conectar()
    cur = con.cursor()
    ahora_iso = ahora().isoformat()
    vencidas = cur.execute("SELECT id FROM salidas WHERE vigencia_hasta < ?", (ahora_iso,)).fetchall()
    for fila in vencidas:
        _borrar_pdfs(fila['id'])
    cur.execute("DELETE FROM salidas WHERE vigencia_hasta < ?", (ahora_iso,))
    con.commit()
    con.close()


def _carpeta_pdfs(id):
    return os.path.join(PDF_DIR, str(id))


def _ruta_pdf(id, anexo):
    return os.path.join(_carpeta_pdfs(id), f'Anexo{anexo}.pdf')


def _borrar_pdfs(id):
    carpeta = _carpeta_pdfs(id)
    if os.path.isdir(carpeta):
        shutil.rmtree(carpeta)


# --- Generación de PDF --------------------------------------------------------
# Un renderer genérico por anexo, dirigido por Salidas/Anexo<N>.json — no hay 7 layouts
# a mano. Ver el comentario de cabecera del archivo.

class _PDFAnexo(FPDF):
    def header(self):
        # fpdf2 dibuja SVG directo (VectorImageInfo) — no hace falta rasterizar el escudo.
        self.image('static/images/escudo.svg', x=10, y=8, h=14)
        self.set_y(28)

    def footer(self):
        # logo-pba.svg (el del root) es un <rect> con fill:pattern envolviendo un PNG
        # embebido en base64 — fpdf2 no soporta <pattern>/<image> de SVG y lo dibuja en
        # blanco. Por eso se usa la extracción ya hecha una vez a static/images/logo-pba.png
        # (ver dev-log/DECISIONS.md), no el SVG original.
        self.set_y(-20)
        self.image('static/images/logo-pba.png', x=10, y=self.get_y(), h=10)


def _crear_pdf():
    pdf = _PDFAnexo(orientation='P', unit='mm', format='A4')
    # margin=22 (no el 15 de siempre): dejarle lugar al logo-pba del footer sin que el
    # auto page break deje la última línea de contenido pisándolo.
    pdf.set_auto_page_break(True, margin=22)
    # Mismas 3 fuentes que ya usa app.py para los PDF de horarios.
    pdf.add_font('RobotoMono', '', 'static/fonts/RobotoMono-Regular.ttf')
    pdf.add_font('RobotoMono', 'B', 'static/fonts/RobotoMono-Bold.ttf')
    pdf.add_font('RobotoMono', 'I', 'static/fonts/RobotoMono-Italic.ttf')
    return pdf


def _cargar_schema(anexo):
    ruta = os.path.join(ANEXOS_JSON_DIR, f'Anexo{ANEXOS_NUMEROS[anexo]}.json')
    with open(ruta, encoding='utf-8') as f:
        return json.load(f)


def _condicion_cumple(campo, valores):
    cond = campo.get('condicion')
    return not cond or valores.get(cond['campo']) == cond['valor']


def _texto_valor(campo, valor):
    if valor is None or valor == '':
        return ''
    if campo['tipo'] == 'bool':
        return 'Sí' if valor else 'No'
    return str(valor)


def _dibujar_campo(pdf, campo, valores):
    pdf.set_font('RobotoMono', 'B', 9)
    pdf.multi_cell(0, 5, campo['label'], align='L', new_x='LMARGIN', new_y='NEXT')
    pdf.set_font('RobotoMono', '', 10)
    # En blanco a propósito cuando el campo no vino en lo guardado: son los de firma y
    # "lugar y fecha", que se completan a mano después de imprimir.
    texto_valor = _texto_valor(campo, valores.get(campo['id']))
    pdf.multi_cell(0, 6, texto_valor or ' ', align='L', border='B', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(3)


def _dibujar_tabla(pdf, campo, valores):
    pdf.set_font('RobotoMono', 'B', 9)
    pdf.multi_cell(0, 5, campo['label'], align='L', new_x='LMARGIN', new_y='NEXT')
    columnas = campo['columnas']
    filas_datos = valores.get(campo['id']) or []
    filas = [[c['label'] for c in columnas]]
    if filas_datos:
        filas += [[_texto_valor(c, fila.get(c['id'])) for c in columnas] for fila in filas_datos]
    else:
        filas.append(['—'] * len(columnas))
    pdf.set_font('RobotoMono', '', 8)
    with pdf.table(filas, text_align='LEFT'):
        pass
    pdf.ln(3)


def _generar_pdf_anexo(anexo, valores, destino):
    schema = _cargar_schema(anexo)
    pdf = _crear_pdf()
    pdf.add_page()
    pdf.set_font('RobotoMono', 'B', 13)
    pdf.multi_cell(0, 8, f"ANEXO {anexo} — {schema['titulo']}", align='L', new_x='LMARGIN', new_y='NEXT')
    pdf.set_font('RobotoMono', 'I', 8)
    pdf.multi_cell(0, 5, schema['fuente'], align='L', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(4)

    seccion_actual = object()  # distinto de cualquier valor real, para forzar el primer título
    for campo in sorted(schema['campos'], key=lambda c: c['orden']):
        if not _condicion_cumple(campo, valores):
            continue
        if campo.get('seccion') != seccion_actual:
            seccion_actual = campo.get('seccion')
            if seccion_actual:
                pdf.set_font('RobotoMono', 'B', 11)
                pdf.ln(2)
                pdf.multi_cell(0, 6, str(seccion_actual).upper(), align='L', new_x='LMARGIN', new_y='NEXT')
                pdf.ln(1)
        if campo['tipo'] == 'tabla':
            _dibujar_tabla(pdf, campo, valores)
        else:
            _dibujar_campo(pdf, campo, valores)

    os.makedirs(os.path.dirname(destino), exist_ok=True)
    pdf.output(destino)


def _generar_pdfs(id, anexos):
    """Un PDF por anexo (III a IX), guardado en disco — nunca se descargan solos."""
    for n in ANEXOS_NUMEROS:
        _generar_pdf_anexo(n, anexos.get(n) or {}, _ruta_pdf(id, n))


# --- Acceso y contexto compartido ---------------------------------------------

accesos.registrar_acceso(bp, PERMISO_LECTURA, endpoint_default='lista')


@bp.context_processor
def _contexto():
    return {
        'escuela_nombre': ESCUELA_NOMBRE,
        'escuela_logo': ESCUELA_LOGO,
        'escuela_version': ESCUELA_VERSION,
    }


# --- Rutas ----------------------------------------------------------------

@bp.route('/')
def lista():
    con = conectar()
    cur = con.cursor()
    filas = cur.execute(
        "SELECT id, nombre_proyecto, fecha_salida, fecha_creacion, vigencia_hasta "
        "FROM salidas ORDER BY fecha_creacion DESC").fetchall()
    con.close()
    return render_template('salidas/lista.html', filas=filas, activo='lista')


@bp.route('/nueva')
@accesos.requiere(PERMISO_ESCRITURA)
def nueva():
    return render_template('salidas/formulario.html', activo='nueva')


@bp.route('/api/guardar', methods=['POST'])
@accesos.requiere(PERMISO_ESCRITURA, como_json=True)
def api_guardar():
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return jsonify({'error': 'JSON inválido.'}), 400

    comunes = datos.get('datos_comunes') or {}
    anexos = datos.get('anexos') or {}
    creado = ahora()
    vigencia = creado + timedelta(days=VIGENCIA_DIAS)

    con = conectar()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO salidas (nombre_proyecto, fecha_salida, fecha_creacion, vigencia_hasta, datos_json) "
        "VALUES (?,?,?,?,?)",
        (comunes.get('denominacion_proyecto', '') or '', comunes.get('fecha_salida', '') or '',
         creado.isoformat(), vigencia.isoformat(), json.dumps(datos)))
    id = cur.lastrowid
    con.commit()
    con.close()

    _generar_pdfs(id, anexos)
    return jsonify({'id': id})


@bp.route('/<int:id>')
def detalle(id):
    con = conectar()
    cur = con.cursor()
    fila = cur.execute("SELECT * FROM salidas WHERE id = ?", (id,)).fetchone()
    con.close()
    if fila is None:
        abort(404)
    disponibles = [n for n in ANEXOS_NUMEROS if os.path.exists(_ruta_pdf(id, n))]
    titulos = {n: _cargar_schema(n)['titulo'] for n in disponibles}
    return render_template('salidas/detalle.html', fila=fila,
                           datos_comunes=json.loads(fila['datos_json']).get('datos_comunes') or {},
                           anexos=disponibles, titulos=titulos, activo='lista')


@bp.route('/<int:id>/pdf/<anexo>')
def ver_pdf(id, anexo):
    if anexo not in ANEXOS_NUMEROS:
        abort(404)
    ruta = _ruta_pdf(id, anexo)
    if not os.path.exists(ruta):
        abort(404)
    return send_file(ruta, mimetype='application/pdf', as_attachment=False,
                     download_name=f'Anexo{anexo}_salida{id}.pdf')
