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
# Usa su propia DB (salidas.db). A diferencia de gestion.db, sus filas tienen
# vigencia: al año de guardadas se borran solas (fila + PDFs) — ver _purgar_vencidas().
#
# El PDF de cada anexo NO se arma con un layout a mano por anexo: un solo renderer
# genérico recorre el Anexo<N>.json correspondiente (la carpeta Salidas/, que es la
# referencia completa y fiel del formulario en papel — incluye los campos de firma y de
# "lugar y fecha" que el formulario digital dejó de tipear a propósito). Los campos que
# no vinieron en lo que se guardó quedan en blanco en la hoja: es lo correcto, porque son
# justamente los que se completan a mano después de imprimir.

import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import sys
from contextlib import closing
from datetime import timedelta
from functools import lru_cache
from tempfile import TemporaryDirectory

from contextlib import contextmanager
from io import BytesIO
from flask import Blueprint, abort, jsonify, redirect, render_template, request, send_file, session, url_for
from fpdf import FPDF, FontFace

import accesos
import crud
import gestion
from config import DIR_DATOS, ESCUELA_LOGO, ESCUELA_NOMBRE, ESCUELA_VERSION, ahora

_AQUI = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DIR_DATOS, 'salidas.db')
PDF_DIR = os.path.join(_AQUI, 'salidas_pdfs')
ANEXOS_JSON_DIR = os.path.join(_AQUI, 'Salidas')

# Piloto: verbo 'admin' (no 'leer'/'escribir') mientras el área está en desarrollo — ese
# verbo no entra en ningún preset de invitación (ver PERFILES en accesos.py), así que sólo
# lo tiene quien entra con comodín '*' (admin real o dispositivo con perfil 'admin'). El
# link de nav ya está atrás de `puede('salidas.leer')`, así que se oculta solo. Volver a
# 'leer'/'escribir' cuando el área esté lista para el resto de los dispositivos internos.
PERMISOS = [
    ('salidas.leer', 'Ver las salidas guardadas y sus PDF', 'admin'),
    ('salidas.editar', 'Cargar y guardar salidas nuevas', 'admin'),
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

# Los respaldos de esta área CADUCAN, a diferencia de los del resto. Una salida vencida se
# borra de salidas.db a los 365 días, pero seguía viva para siempre en el "primero de cada
# día" que conserva respaldos.py: purgar la fila y dejar el respaldo es teatro. 60 días es
# lo que un respaldo sirve de verdad acá — restaurar un salidas.db de hace un año recupera
# lo viejo y pierde todo lo cargado desde entonces, así que nadie lo haría. Los últimos
# respaldos.BACKUP_MAX se conservan igual aunque sean más viejos (ver respaldos._a_borrar).
BACKUP_MAX_DIAS = 60

# Cada cuánto se purgan las vencidas. `_purgar_vencidas` corría sólo desde `init_db()`, o
# sea una vez por arranque del proceso: en un hosting donde el web app puede no reciclarse
# en meses, eso es "nunca".
INTERVALO_PURGA_HORAS = 24

ENTIDADES = {}  # no es una entidad de crud.py — ver el comentario de arriba del archivo

ANEXOS_NUMEROS = {'III': 3, 'IV': 4, 'V': 5, 'VI': 6, 'VII': 7, 'VIII': 8, 'IX': 9}

# El III (autorización general, sin transporte) y el VIII (informe del transporte) sólo
# tienen sentido para un subconjunto de salidas — uno u otro, según haya transporte
# contratado o no. Si la escuela no cargó ningún dato ahí, ni se genera el PDF: así no
# aparece listado en el detalle (que filtra por archivo existente en disco).
ANEXOS_OPCIONALES_SI_VACIOS = {'III', 'VIII'}

bp = Blueprint('salidas', __name__, url_prefix='/salidas')


def conectar():
    return crud.conectar(sys.modules[__name__])


def _generar_token():
    """Token del link público de una salida (`/salidas/completar/<token>`) — mismo
    generador que las invitaciones de accesos.py, pero sin tabla de canje: no se quema
    con el uso, porque lo abre una familia distinta por cada estudiante."""
    return secrets.token_urlsafe(16)


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
    datos_json TEXT NOT NULL,
    token TEXT DEFAULT '',
    archivado INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS salidas_mcp_creaciones (
    operacion TEXT PRIMARY KEY,
    pedido TEXT NOT NULL,
    salida INTEGER NOT NULL
);
"""


def seed(cur):
    """Sólo siembra el testigo — no hay datos de ejemplo con sentido para una salida real."""
    cur.execute("INSERT OR IGNORE INTO salidas_meta (id, creado) VALUES (1, ?)", (ahora().isoformat(),))


def migrar(cur):
    """Adapta una salidas.db creada antes del link público (ALTER aditivo + backfill)."""
    existentes = {c[1] for c in cur.execute("PRAGMA table_info(salidas)").fetchall()}
    if 'token' not in existentes:
        cur.execute("ALTER TABLE salidas ADD COLUMN token TEXT DEFAULT ''")
    if 'archivado' not in existentes:
        cur.execute("ALTER TABLE salidas ADD COLUMN archivado INTEGER NOT NULL DEFAULT 0")
    # Las salidas guardadas antes de este cambio no tienen token — se les genera uno acá,
    # una sola vez, para que el link público funcione también para ellas.
    sin_token = cur.execute("SELECT id FROM salidas WHERE token IS NULL OR token = ''").fetchall()
    for fila in sin_token:
        cur.execute("UPDATE salidas SET token = ? WHERE id = ?", (_generar_token(), fila['id']))
    # `salidas_familias` (lo que completaba cada familia por el link público) se retiró:
    # ahora ese formulario no persiste nada del lado de la escuela (ver dev-log/DECISIONS.md
    # 2026-08-16). La tabla vieja, si existe, la borra `retirar_datos_sensibles` (PASO 4.7
    # de actualizar.py): no se hace acá porque `migrar` corre en cada arranque y tirar filas
    # con datos de salud sin preview y sin que nadie lo pida es lo que ese script evita.


def init_db():
    """Crea/migra la DB (crud.init_db: respalda, crea tablas, siembra el testigo la
    primera vez) y recién después purga las salidas vencidas — en ese orden, para que
    un año sin salidas activas nunca se confunda con un archivo perdido."""
    crud.init_db(sys.modules[__name__])
    _purgar_vencidas()


def _purgar_vencidas():
    con = conectar()
    cur = con.cursor()
    cur.execute('BEGIN IMMEDIATE')
    ahora_iso = ahora().isoformat()
    vencidas = cur.execute("SELECT id FROM salidas WHERE vigencia_hasta < ?", (ahora_iso,)).fetchall()
    for fila in vencidas:
        _borrar_pdfs(fila['id'])
    cur.execute("DELETE FROM salidas WHERE vigencia_hasta < ?", (ahora_iso,))
    cur.execute("DELETE FROM salidas_mcp_creaciones WHERE salida NOT IN (SELECT id FROM salidas)")
    con.commit()
    con.close()


# Última vez que este proceso purgó. Sin persistir a propósito: es una optimización para
# no releer la tabla en cada request, no un registro de nada. Un reinicio purga de nuevo,
# que es justo lo que queremos.
_ultima_purga = None


def _purgar_si_toca():
    """Purga las vencidas a lo sumo una vez cada INTERVALO_PURGA_HORAS.

    Va como before_request de los DOS blueprints del área: si sólo estuviera en `bp`, un
    año en que nadie de la escuela abre /salidas no purgaría nada, y el link público es
    justamente la ruta que más se visita desde afuera. `_purgar_vencidas` es idempotente,
    así que dos workers purgando el mismo día no molestan.
    """
    global _ultima_purga
    if _ultima_purga and (ahora() - _ultima_purga) < timedelta(hours=INTERVALO_PURGA_HORAS):
        return
    _ultima_purga = ahora()
    _purgar_vencidas()


bp.before_request(_purgar_si_toca)


def _carpeta_pdfs(id):
    return os.path.join(PDF_DIR, str(id))


def _ruta_pdf(id, anexo):
    return os.path.join(_carpeta_pdfs(id), f'Anexo{anexo}.pdf')


# Hasta 2026-09-09 cada seguro escolar adicional del Anexo IX generaba su propia copia
# completa, `AnexoIX_2.pdf` en adelante; ahora todos van en el mismo PDF. El patrón queda
# para poder limpiar las copias que hayan quedado en disco (ver _limpiar_pdfs_ix_extra).
_RE_PDF_IX_EXTRA = re.compile(r'^AnexoIX_(\d+)\.pdf$')


def _borrar_pdfs(id):
    carpeta = _carpeta_pdfs(id)
    if os.path.isdir(carpeta):
        shutil.rmtree(carpeta)


# --- Generación de PDF --------------------------------------------------------
# Un renderer genérico por anexo, dirigido por Salidas/Anexo<N>.json — no hay 7 layouts
# a mano. Ver el comentario de cabecera del archivo.

class _PDFAnexo(FPDF):
    # Fijado por _generar_pdf_anexo antes de add_page(): en el original, el número de
    # documento GEDO (IF-2024-...) va como pie de página en cada hoja, no como subtítulo
    # bajo el título — se dibuja acá, no arriba.
    fuente_doc = ''

    def header(self):
        # Sin escudo de la escuela: estos PDF imitan un formulario oficial de la provincia
        # (el único logo es el de PBA, en el pie). El set_y deja el mismo margen superior.
        self.set_y(28)

    def footer(self):
        self.set_y(-24)
        self.set_font('helvetica', '', 9)
        self.set_text_color(80, 80, 80)
        self.cell(0, 4, self.fuente_doc, align='R')
        self.set_text_color(0, 0, 0)
        # logo-pba.svg (el del root) es un <rect> con fill:pattern envolviendo un PNG
        # embebido en base64 — fpdf2 no soporta <pattern>/<image> de SVG y lo dibuja en
        # blanco. Por eso se usa la extracción ya hecha una vez a static/images/logo-pba.png
        # (ver dev-log/DECISIONS.md), no el SVG original.
        self.set_y(-22)
        self.image('static/images/logo-pba.png', x=10, y=self.get_y(), h=18)
        self.set_y(-14)
        self.set_font('helvetica', '', 8)
        self.cell(0, 6, f'página {self.page_no()} de {{nb}}', align='R')


def _crear_pdf():
    pdf = _PDFAnexo(orientation='P', unit='mm', format='A4')
    # margin=22 (no el 15 de siempre): dejarle lugar al pie (fuente + logo + paginado) sin
    # que el auto page break deje la última línea de contenido pisándolo.
    pdf.set_auto_page_break(True, margin=22)
    pdf.alias_nb_pages()  # {nb} en el footer -> total de páginas, como "página 1 de 2" del original
    # helvetica: fuente core de fpdf2 (no hace falta add_font/embeber archivo). El original
    # está tipeado en una sans-serif proporcional (Arial/Helvetica), no en la monoespaciada
    # RobotoMono que usa el resto de la app — para estos PDF, que imitan un formulario
    # oficial ajeno, se prioriza parecerse al papel por sobre la identidad visual de AppMitre.
    return pdf


def _cargar_schema(anexo):
    ruta = os.path.join(ANEXOS_JSON_DIR, f'Anexo{ANEXOS_NUMEROS[anexo]}.json')
    with open(ruta, encoding='utf-8') as f:
        return json.load(f)


_normativa_cache = None
@lru_cache(maxsize=1)
def esquema_formulario():
    with open(os.path.join(ANEXOS_JSON_DIR, 'formulario.json'), encoding='utf-8') as f:
        return json.load(f)


def _cargar_normativa():
    global _normativa_cache
    if _normativa_cache is None:
        ruta = os.path.join(ANEXOS_JSON_DIR, 'advertencias_normativa.json')
        with open(ruta, encoding='utf-8') as f:
            lista = json.load(f)
        _normativa_cache = {n['clave']: n for n in lista}
    return _normativa_cache


def _condicion_cumple(campo, valores):
    cond = campo.get('condicion')
    return not cond or valores.get(cond['campo']) == cond['valor']


# Campos de un anexo que casualmente comparten id con uno de Datos Comunes pero tienen
# un significado propio — no deben pisarse con el dato de la escuela: VIII.telefono lo
# completa la empresa de transporte (colisiona con el "Teléfono de la escuela" común) y
# VII.domicilio es el domicilio particular del/la estudiante (colisiona con el "Domicilio
# de la escuela" común). Sin esta exclusión, _replicar_comunes los pisaba en cada guardado
# y no había forma de cargarlos ni editarlos.
_REPLICA_COMUNES_EXCLUIR = {
    'VII': {'domicilio'},
    'VIII': {'telefono'},
}


def _replicar_comunes(anexos, comunes):
    """Copia cada campo de Datos Comunes dentro de los anexos que comparten su id (ver
    comentario en api_guardar), salvo los de _REPLICA_COMUNES_EXCLUIR."""
    for anexo_id, anexo in anexos.items():
        if not isinstance(anexo, dict):
            continue
        excluir = _REPLICA_COMUNES_EXCLUIR.get(anexo_id, ())
        for clave, valor in comunes.items():
            if clave not in excluir:
                anexo[clave] = valor
            elif valor and anexo.get(clave) == valor:
                # Salidas guardadas antes de la exclusión traen el dato de la escuela
                # persistido en el anexo: se vacía para que no siga apareciendo.
                anexo[clave] = ''


def _iso_a_dd_mm_yyyy(iso_fecha):
    """Convierte fecha ISO (YYYY-MM-DD) a formato dd/mm/yyyy"""
    if not iso_fecha or not isinstance(iso_fecha, str):
        return ''
    try:
        partes = iso_fecha.split('-')
        if len(partes) != 3:
            return iso_fecha
        a, m, d = partes
        return f"{d.zfill(2)}/{m.zfill(2)}/{a}"
    except:
        return iso_fecha

# La fuente de los PDF ("helvetica") es un core font: sólo soporta latin-1. Cualquier
# usuario puede pegar texto copiado de Word/Docs con viñetas, comillas tipográficas o rayas,
# y sin sanear eso fpdf2 tira FPDFUnicodeEncodingException — no sólo sale mal el PDF, se
# cae api_guardar entero (500) y la salida no queda guardada. Reemplazos legibles para los
# casos comunes, y un fallback (encode/decode) para que ningún otro carácter vuelva a romper
# el guardado.
_REEMPLAZOS_LATIN1 = {
    '—': ' - ', '–': '-', '•': '-', '…': '...',
    '‘': "'", '’': "'", '“': '"', '”': '"',
}

def _sanear_latin1(text):
    for original, nuevo in _REEMPLAZOS_LATIN1.items():
        text = text.replace(original, nuevo)
    return text.encode('latin-1', 'replace').decode('latin-1')


def _texto_valor(campo, valor):
    if valor is None or valor == '':
        return ''
    if campo['tipo'] == 'bool':
        return 'X' if valor else ''
    # Los dos nombres del mismo tipo: 'fecha' es el de los AnexoN.json (el que llega acá) y
    # 'date' el del formulario HTML. Se aceptan los dos porque las dos listas de campos se
    # sincronizan a mano y ya se desfasaron una vez — con sólo 'date' esta rama era código
    # muerto y las fechas auto del IV y del V salían en ISO.
    if campo['tipo'] in ('fecha', 'date'):
        return _iso_a_dd_mm_yyyy(str(valor))
    return _sanear_latin1(str(valor))


# Los AnexoN.json agrupan campos con una clave corta (`seccion`) para uso interno del
# propio JSON — no es el texto que aparece impreso en el formulario original (compárese
# "hospedaje_mas_24hs" con lo que dice el papel: "Sólo para salidas de más de 24 horas").
# Esta tabla traduce uno al otro. Un slug ausente acá (o `seccion` en null) no imprime
# ningún encabezado — es lo correcto para los bloques que en el original no tienen
# título propio, como los de identificación del Anexo IV.
SECCION_TITULOS = {
    'IV': {'hospedaje_mas_24hs': 'Sólo para salidas de más de 24 horas'},
    'VI': {
        'informativa': '1- Planilla informativa para padres, madres, tutores o responsables (completa la Escuela)',
        'autorizacion': '2- Autorización (completa el padre/madre, tutor o responsable)',
        'salud': '3- Salud (completa el padre/madre, tutor o responsable)',
    },
    'VIII': {'adjuntos': 'Adjuntos (fotocopias)'},
    'IX': {'seguro_escolar': 'Datos del seguro escolar'},
}

# Secciones que en el papel arrancan hoja nueva. En el VI, "3- Salud" abre la página 2: sin
# esto el título quedaba huérfano al pie de la página 1 y el resto de la sección en la 2.
SECCIONES_PAGINA_NUEVA = {'VI': {'salud'}}
# Ídem por campo, para anexos sin secciones: en el VII la cajita de obra social abre la página 2
# (así teléfonos y firma quedan juntos con ella, en vez de partirse entre las dos hojas).
CAMPOS_PAGINA_NUEVA = {'VII': {'tiene_obra_social'}}

# El original agrupa estos tres campos en una cajita de 3 renglones (Tiene Obra
# Social/Prepaga · Sí-No · Nombre · N° Socio) en vez de listarlos sueltos — VI y VII
# repiten la misma cajita, así que alcanza con detectar el id.
CAMPOS_OBRA_SOCIAL = ('tiene_obra_social', 'nombre_obra_social', 'numero_socio')

# Las dos tablas de docentes del Anexo IV no son una grilla con bordes en el original:
# son renglones repetidos "Apellido y Nombre ____ Cargo ____", uno por docente.
CAMPOS_DOCENTES = ('docentes_responsables_titulares', 'docentes_reemplazantes')

# El bloque de firmas del Anexo IX es un caso propio: en el original son dos columnas
# lado a lado, "FIRMA Y SELLO" / "DIRECTOR/A" a la izquierda y "FIRMA Y SELLO" /
# "REPRESENTANTE LEGAL" a la derecha (la segunda sólo si es gestión privada) — no dos
# líneas sueltas "Firma y sello del Director/a: ___" una debajo de la otra como el resto
# de los campos de texto. `_dibujar_firmas_ix` ignora el `label` del JSON (que sigue
# siendo el texto legible para el formulario HTML) y dibuja el texto fijo del papel.
CAMPOS_FIRMA_IX = ('firma_sello_director', 'firma_sello_representante_legal')

# `tipo_gestion` (Anexo IX) no es un campo del papel original — lo dice su propia
# `notas` en el JSON: existe sólo para que el código decida si corresponde pedir
# representante_legal/entidad_propietaria y la segunda columna de CAMPOS_FIRMA_IX. Por
# eso nunca se dibuja como "label: valor" suelto, aunque sí se sigue usando su valor
# (siempre 'estatal' para esta escuela) para esas decisiones.
CAMPOS_SIN_IMPRIMIR = {
    'IX': {'tipo_gestion'},
}

# El original mete dos (o hasta tres) campos en el mismo renglón en varios lugares (ej.
# Anexo V: "INSTITUCIÓN EDUCATIVA ____ N°____" es una sola línea, no dos; Anexo IV: "Fecha
# de salida ____ Hora ____ Lugar ____" son tres). Cada tupla es un grupo completo, en el
# orden real del renglón. `_dibujar_campo` arma el grupo cuando aparece el primer id; el
# resto se saltea en el loop principal (`ids_resto_linea`, más abajo) para no imprimirse
# de nuevo suelto.
CAMPOS_MISMA_LINEA = {
    'IV': [
        ('institucion_educativa', 'numero_institucion'),
        ('domicilio', 'telefono'),
        ('fecha_salida', 'hora_salida', 'lugar_salida'),
        ('fecha_regreso', 'hora_regreso', 'lugar_regreso'),
        ('hospedaje_nombre', 'hospedaje_telefono'),
        ('hospedaje_domicilio', 'hospedaje_localidad'),
    ],
    'V': [('institucion_educativa', 'numero_institucion'), ('lugar_a_visitar', 'fecha')],
    'VII': [('firma', 'dni_firma')],  # "Firma: ____ DNI: ____" es un solo renglón en el papel
    'IX': [
        ('numero_establecimiento', 'cue'),  # "N°____ CUE____", debajo del nombre del establecimiento
        ('domicilio', 'distrito'),
    ],
}

# `notas` de un campo (ver Salidas/README_campos.md) puede ser una aclaración real del
# papel (footnote entre paréntesis junto al label) o un criterio interno mío sobre el
# schema — no hay forma de distinguirlas mecánicamente, así que sólo se imprimen las que se
# verificaron contra el original. Confirmado por ahora: Anexo V → `observaciones`
# ("Para ser completado ante cualquier eventualidad", pegado al label en el papel); Anexo
# IV → `observaciones_fechas`/`itinerario` ("(en caso de corresponder)"/"(detalle
# pormenorizado del mismo)", entre el label y los ":" — ver NOTAS_ANTES_DE_DOSPUNTOS).
# Anexo IX es distinto: sus notas (1)/(2) NO van pegadas al label como acá — son notas al
# pie de página de verdad, separadas del campo. Por eso el "(1)"/"(2)" quedó en el propio
# `label` del JSON (se ve igual en el papel) y el texto de la nota va en un campo `nota`
# aparte (`nota_pie_seguro`), no por este mecanismo.
NOTAS_A_IMPRIMIR = {
    'IV': {'observaciones_fechas', 'itinerario'},
    'V': {'observaciones'},
    # Anexo VIII: "Titularidad del vehículo (Micro, ómnibus...)" y "Habilitación del/los
    # vehículos (número de registro...)" — verificado contra Salidas/Anexo8.md.
    'VIII': {'titularidad_vehiculo', 'habilitacion_vehiculo'},
    # "Teléfonos de contacto en caso de urgencia: (Consignar varios)" — igual en VI y VII.
    'VI': {'telefonos_urgencia'},
    'VII': {'telefonos_urgencia'},
}

# Dónde va la aclaración entre paréntesis respecto de los ":" tampoco es parejo: el Anexo V
# la pone DESPUÉS ("OBSERVACIONES:(Para ser completado...)"), el Anexo IV y el VIII la ponen
# ANTES ("Itinerario (detalle pormenorizado del mismo):", "Titularidad del vehículo (Micro,
# ómnibus...):") — verificado en el original de los tres. Afecta a `_dibujar_textarea` y a
# `_dibujar_campo`; el default (después de los ":") es el de más anexos.
NOTAS_ANTES_DE_DOSPUNTOS = {'IV', 'VIII'}

# Varios anexos NO son, en el original, una lista de "label: valor": arrancan con un
# párrafo corrido con blancos intercalados (ej. Anexo III: "Por la presente autorizo a
# ____, DNI ____, estudiante de ____ Año..."). Los datos se siguen pidiendo como campos
# sueltos en el JSON —los necesita el formulario HTML tal cual—, pero acá, en vez de
# imprimirlos como líneas "Label: valor" (que el papel real nunca fue), se tejen dentro de
# la oración real. Verificado página por página contra el original para III, VI y VII —
# los otros anexos no abren con un párrafo así, van campo por campo igual que hoy.
PARRAFOS_NARRATIVA = {
    'III': [{
        'ids': ('nombre_estudiante', 'dni_estudiante', 'anio_curso', 'seccion_curso'),
        'texto': ("Por la presente autorizo a {nombre_estudiante}, DNI {dni_estudiante}, estudiante de "
                  "{anio_curso} Año, sección {seccion_curso}, a participar de las Salidas Educativas o de "
                  "Representación Institucional que se lleven a cabo en el barrio o área geográfica "
                  "inmediata o próxima al establecimiento educativo, sin necesidad de utilizar un medio de "
                  "transporte, en el marco de la normativa vigente."),
    }],
    'VI': [{
        'ids': ('nombre_estudiante', 'dni_estudiante', 'tipo_salida', 'establecimiento_educativo',
                'numero_establecimiento', 'distrito', 'localidad_salida', 'dias_salida', 'mes_salida'),
        'texto': ("Por la presente autorizo a mi hijo/a {nombre_estudiante}, DNI {dni_estudiante}, que "
                  "concurre al Establecimiento Educativo {establecimiento_educativo} N° {numero_establecimiento} "
                  "del distrito {distrito}, a participar de la {tipo_salida} a realizarse en la localidad de "
                  "{localidad_salida} {dia_articulo} {dias_salida} del mes de {mes_salida} del presente ciclo "
                  "lectivo."),
        # tipo_salida se elige una sola vez en Datos Comunes y se replica acá y en el VII
        # (destino en formulario.html) — en el original en papel se tacha lo que no
        # corresponde, acá se resuelve solo con el valor elegido.
        'mapeos': {'tipo_salida': {'educativa': 'Salida Educativa',
                                    'representacion_institucional': 'Salida de Representación Institucional'}},
        # En el original el blanco de "mi hijo/a ____" ocupa toda la línea (sólo deja lugar a la
        # coma): es el único dato de la parte 2 que necesita ese lugar. Los demás
        # blancos del párrafo se quedan con el ancho fijo de ANCHOS_BLANCO_NARRATIVA.
        'anchos_resto_linea': {'nombre_estudiante'},
        # Sin tipo_salida elegido (formulario en blanco para completar a mano), mismo
        # criterio que LABELS_SEGUN_TIPO_SALIDA en el IX: en vez de un blanco, cae el texto
        # con las dos opciones para tachar la que no corresponda.
        'sin_dato': {'tipo_salida': 'Salida educativa/ de representación institucional'},
    }],
    'VII': [{
        'ids': ('nombre_estudiante', 'dni_estudiante', 'domicilio', 'localidad', 'institucion', 'tipo_salida',
                'localidad_salida', 'dias_salida', 'mes_salida', 'anio_salida'),
        # `segmentos`: en el original "salida educativa / de representación institucional"
        # va en NEGRITA dentro del mismo párrafo — no es texto corrido de un solo estilo
        # como III. Cada tupla es (texto con placeholders `.format()`, estilo de fpdf2:
        # '' | 'B' | 'I'). El original tiene además "(tachar lo que no corresponda)" en
        # itálica, que acá se omite: como tipo_salida ya viene resuelto, no hay nada que tachar.
        'segmentos': [
            ("Quien suscribe, {nombre_estudiante}, DNI {dni_estudiante}, domiciliada/o en la calle "
             "{domicilio} de la localidad de {localidad}, que concurre a la institución {institucion}, "
             "participará de la ", ''),
            ("{tipo_salida}", 'B'),
            (" a realizarse en la localidad de {localidad_salida} {dia_articulo} {dias_salida} del mes de "
             "{mes_salida} del año {anio_salida}.", ''),
        ],
        # tipo_salida se guarda como slug de <select> — el papel espera el texto tachable.
        'mapeos': {'tipo_salida': {'educativa': 'salida educativa',
                                    'representacion_institucional': 'salida de representación institucional'}},
        # Sin tipo_salida (VII en blanco): las dos opciones en negrita + la indicación en
        # itálica, como en el papel.
        'sin_dato': {'tipo_salida': [('salida educativa / de representación institucional', 'B'),
                                     (' (tachar lo que no corresponda)', 'I')]},
        # En blanco, el nombre completo a mano necesita todo el renglón.
        'anchos_resto_linea': ('nombre_estudiante',),
    }],
}

# El ancho automático de fpdf2 reparte las columnas por igual, pero en el original
# "Apellido y Nombre" es, a ojo, casi 5 veces más ancha que "N°" — con reparto parejo el
# nombre se corta en dos líneas y la tabla no se parece a la del papel. Únicos anchos (mm)
# fijados a mano, calibrados contra la proporción real del Anexo V.
COL_WIDTHS = {
    'listado_personas': (12, 60, 33, 23, 21, 19, 21),
}

# El peso/caja de los labels varía de anexo a anexo en el original (V: negrita; IV, por
# ejemplo, no — verificado visualmente en ambos), así que van por permiso explícito, igual
# que NOTAS_A_IMPRIMIR/SECCION_TITULOS, no como default global.
ANEXOS_LABEL_NEGRITA = {'V'}

# Ídem para mayúsculas: en el papel del Anexo V los campos de identificación y
# "OBSERVACIONES" están en mayúscula, pero "Lugar y fecha"/"Firma de Autoridad..." no —
# es la tipografía real del formulario, no un criterio parejo por anexo.
LABELS_MAYUSCULA = {
    'V': {'institucion_educativa', 'numero_institucion', 'distrito', 'lugar_a_visitar', 'fecha', 'observaciones'},
    # Anexo IX: prácticamente todos los labels de identificación/seguro están en mayúscula
    # en el papel — verificado visualmente. Las dos excepciones confirmadas (tampoco
    # mayúscula en el original): `lugar_y_fecha` y los de firma (ver CAMPOS_FIRMA_IX, que
    # además van con su propio texto fijo, no el `label` del JSON).
    'IX': {'nombre_establecimiento', 'numero_establecimiento', 'cue', 'domicilio', 'distrito', 'director',
           'representante_legal', 'entidad_propietaria', 'fecha_lugar_realizacion', 'compania_aseguradora',
           'tipo_seguro', 'numero_poliza', 'vigencia_poliza', 'observaciones'},
}

TAM_TEXTO = 11
ALTO_LINEA = 7
RENGLONES_TEXTAREA = 5  # renglones en blanco para completar a mano cuando el campo no vino con valor
# Campos que se apartan de ese default, por id. Además de fijar la cantidad de renglones,
# estar acá alcanza para que un campo `text` se dibuje como bloque (label arriba, renglones
# abajo) en vez de "label: ____" en un solo renglón: es lo que necesita
# `autoridad_que_completo`, cuyo label es tan largo que la línea de _escribir_par arrancaba
# pasado el margen derecho y se salía de la hoja.
RENGLONES_BLANCO = {
    'observaciones_fechas': 4,
    'gastos_estimativos': 4,
    'autoridad_que_completo': 1,
    # Salud del VI/VII: dos renglones punteados para las indicaciones y varios para teléfonos.
    'indicaciones_salud': 2,
    'telefonos_urgencia': 4,
    'VII.indicaciones_salud': 3,
    'VII.telefonos_urgencia': 3,  # "anexo.id" pisa al id solo: el VII trae uno menos que el VI
}
GROSOR_TRAZO_VALOR = 0.25  # mm — trazo fino sobre el relleno de valores destacados
ANCHO_BLANCO_PAR = 70  # mm — línea en blanco para completar a mano, campo solo en su renglón
ANCHO_BLANCO_PAR_EXTRA = 35  # mm — ídem, cuando comparte renglón con otro campo (CAMPOS_MISMA_LINEA)
# Anchos por id que se apartan de esos dos defaults. El bloque de hospedaje del Anexo IV
# ("sólo para salidas de más de 24 horas") va de a dos campos por renglón, y con los 35mm
# parejos no entraba a mano ni el nombre de un hotel ni una dirección; el renglón tiene lugar
# de sobra hasta el margen derecho, así que se los ensancha.
# Los renglones de tres campos ("Fecha de regreso ___ Hora ___ Lugar ___") no entran con los
# 35mm parejos: la última línea arrancaba pasada la margen derecha y se cortaba fuera de la
# hoja. Se reparten según lo que hay que escribir — una fecha y una hora son cortas, el lugar no.
ANCHOS_BLANCO_PAR = {
    'hospedaje_nombre': 45, 'hospedaje_telefono': 45,
    'hospedaje_domicilio': 45, 'hospedaje_localidad': 45,
    'fecha_salida': 24, 'hora_salida': 16, 'lugar_salida': 38,
    'fecha_regreso': 24, 'hora_regreso': 16, 'lugar_regreso': 38,
    # Anexo VII: "Firma: ______ DNI: ______" ocupa todo el renglón en el papel.
    'firma': 65, 'dni_firma': 55,
}
ANCHO_BLANCO_NARRATIVA = 45  # mm — ídem, para un placeholder {id} vacío dentro del párrafo corrido
# Nombre completo y domicilio necesitan más lugar que un DNI o un distrito para escribir a mano.
ANCHOS_BLANCO_NARRATIVA = {
    'nombre_estudiante': 65, 'domicilio': 55, 'institucion': 55, 'establecimiento_educativo': 55,
}


# Labels que en el papel traen las dos variantes juntas para tachar la que no corresponde
# ("... de la Salida Educativa/Salida de Representación Institucional"). Como `tipo_salida`
# ya se eligió una sola vez en Datos Comunes, se imprime sólo la que va — mismo criterio que
# los `mapeos` de PARRAFOS_NARRATIVA en el VI/VII. El `label` del JSON queda como está en el
# papel: el que elige es el renderer. Sin `tipo_salida` cargado (formulario en blanco para
# completar a mano) cae al label completo, que es justamente el que se tacha.
LABELS_SEGUN_TIPO_SALIDA = {
    'IX': {
        'fecha_lugar_realizacion': {
            'educativa': 'Fecha y lugar de realización de la Salida Educativa',
            'representacion_institucional':
                'Fecha y lugar de realización de la Salida de Representación Institucional',
        },
    },
}


def _label_campo(campo, anexo, valores=None):
    variantes = LABELS_SEGUN_TIPO_SALIDA.get(anexo, {}).get(campo['id'])
    label = (variantes or {}).get((valores or {}).get('tipo_salida')) or campo['label']
    return label.upper() if campo['id'] in LABELS_MAYUSCULA.get(anexo, ()) else label


# El valor destacado va +1pt respecto del label en todos los anexos. El IX lo tuvo en -1
# (valor más chico) y el VI invertido (label destacado, valor en Roboto Light, títulos de
# sección +2pt); los dos terminaban leyéndose distinto al lado del resto y se unificaron.
DELTA_VALOR = 1


@contextmanager
def _trazo_valor(pdf):
    """Trazo fino (fill+stroke) sobre el texto, sin tocar la fuente.

    Va por `local_context` (q/Q en el stream) y no asignando `pdf.text_mode`: fpdf2 emite
    el operador `Tr` sólo cuando el modo no es FILL, pero nunca emite el `2 Tr` -> `0 Tr` de
    vuelta. Como `Tr` es estado gráfico y persiste entre BT/ET, el trazo quedaba pegado y
    todo lo que se dibujaba después salía semi-negrita (los labels incluidos)."""
    with pdf.local_context(text_mode="FILL_STROKE", line_width=GROSOR_TRAZO_VALOR):
        yield


@contextmanager
def _valor_destacado(pdf, tam_base=TAM_TEXTO, delta=1):
    """Contexto para dibujar un valor cargado por el usuario: `delta` puntos de diferencia
    respecto de `tam_base` y con un trazo fino (fill+stroke) que da un efecto de
    semi-negrita, sin depender de una fuente Bold real."""
    with pdf.local_context(text_mode="FILL_STROKE", line_width=GROSOR_TRAZO_VALOR,
                           font_family='helvetica', font_style='', font_size_pt=tam_base + delta):
        yield


def _write(pdf, texto):
    """pdf.write() sin partir la primera palabra: si no entra en lo que queda del renglón,
    fpdf2 la corta letra por letra ("M" / "ar del Plata") en vez de pasarla entera abajo."""
    if texto and not texto[0].isspace() and pdf.get_x() > pdf.l_margin + 0.01:
        libre = pdf.w - pdf.r_margin - pdf.get_x() - 2 * pdf.c_margin  # write() descuenta c_margin a cada lado
        if pdf.get_string_width(texto.split(None, 1)[0]) > libre:
            pdf.ln(ALTO_LINEA)
    pdf.write(ALTO_LINEA, texto)


def _cell_resto_linea(pdf, siguiente):
    """Blanco hasta el margen derecho, dejando lugar para `siguiente` (la puntuación que
    le sigue en el párrafo, así la coma no arranca sola el renglón de abajo)."""
    reservado = pdf.get_string_width(siguiente.split(' ', 1)[0] + ' ') + 2 * pdf.c_margin + 0.5 if siguiente[:1] not in ('', ' ') else 0
    pdf.cell(pdf.w - pdf.r_margin - pdf.get_x() - reservado, ALTO_LINEA, '', border='B')


def _cell_blanco(pdf, ancho, alto=ALTO_LINEA, border='B'):
    """Línea en blanco para completar a mano ("label: ____"). A diferencia de `write()`,
    `cell()` no hace salto de línea automático: si el ancho no entra en lo que queda del
    renglón, seguía de largo pasando el margen derecho. Acá baja al renglón siguiente, y
    sólo se parte si el ancho pedido es mayor a un renglón entero."""
    disponible = pdf.w - pdf.r_margin - pdf.get_x()
    if ancho <= disponible:
        # Entra entero donde está: nada que partir.
        pdf.cell(ancho, alto, '', border=border)
        return
    ancho_restante = ancho
    ancho_linea = pdf.w - pdf.l_margin - pdf.r_margin
    # Partido en dos parece otro blanco más: si entra en un renglón, baja entero.
    if ancho > ancho_linea and disponible > 0:
        pdf.cell(disponible, alto, '', border=border)
        ancho_restante -= disponible
    while ancho_restante > 0:
        pdf.ln(alto)
        ancho_tramo = min(ancho_restante, ancho_linea)
        pdf.cell(ancho_tramo, alto, '', border=border)
        ancho_restante -= ancho_tramo


def _escribir_par(pdf, label, valor, negrita, anexo, ancho_blanco=ANCHO_BLANCO_PAR):
    pdf.set_font('helvetica', 'B' if negrita else '', TAM_TEXTO)
    _write(pdf, f"{label}: ")
    pdf.set_font('helvetica', '', TAM_TEXTO)
    if valor:
        with _valor_destacado(pdf, TAM_TEXTO, DELTA_VALOR):
            _write(pdf, valor)
    else:
        # Sin valor: línea en blanco para completar a mano después de imprimir — firma,
        # "lugar y fecha", nombre del hijo/a en la autorización, etc.
        _cell_blanco(pdf, ancho_blanco)


def _dibujar_campo(pdf, campo, valores, anexo, extra=()):
    # `extra`: los demás campos del mismo renglón (ver CAMPOS_MISMA_LINEA), en orden,
    # después del primero — comparten el ancho de línea en blanco más angosto.
    negrita = anexo in ANEXOS_LABEL_NEGRITA
    texto_valor = _texto_valor(campo, valores.get(campo['id']))
    nota = campo.get('notas') if campo['id'] in NOTAS_A_IMPRIMIR.get(anexo, ()) else None
    nota_antes = bool(nota) and anexo in NOTAS_ANTES_DE_DOSPUNTOS
    label = _label_campo(campo, anexo, valores)
    if nota_antes:
        label = f"{label} ({nota})"
    ancho_blanco = ANCHOS_BLANCO_PAR.get(campo['id'], ANCHO_BLANCO_PAR_EXTRA if extra else ANCHO_BLANCO_PAR)
    _escribir_par(pdf, label, texto_valor, negrita, anexo, ancho_blanco)
    if nota and not nota_antes:
        _write(pdf, f" ({nota})")
    for campo_extra in extra:
        texto_extra = _texto_valor(campo_extra, valores.get(campo_extra['id']))
        _write(pdf, '     ')
        _escribir_par(pdf, _label_campo(campo_extra, anexo, valores), texto_extra, negrita, anexo,
                      ANCHOS_BLANCO_PAR.get(campo_extra['id'], ANCHO_BLANCO_PAR_EXTRA))
    pdf.ln(ALTO_LINEA)
    pdf.ln(2)


def _dibujar_textarea(pdf, campo, valores, anexo):
    # Con valor: se imprime. Sin valor: renglones en blanco con línea de base — es "para
    # completar en ese lugar" a mano, no un campo que simplemente queda vacío como los de
    # firma/lugar-y-fecha (ahí no hace falta renglón porque son una sola línea corta).
    negrita = anexo in ANEXOS_LABEL_NEGRITA
    # Caso especial: nombres_telefonos_acompanantes tiene versión "texto" generada en el frontend
    valor_raw = valores.get(campo['id'])
    if campo['id'] == 'nombres_telefonos_acompanantes':
        if campo['id'] + '_texto' in valores:
            # Versión "texto" generada en el frontend — no pasa por _texto_valor porque no
            # es el valor de `campo`, así que el saneo para la fuente se hace acá aparte.
            texto_valor = _sanear_latin1(valores.get(campo['id'] + '_texto', '') or '')
        elif isinstance(valor_raw, dict):
            # Versión diccionario — convertir a formato texto (compatibilidad)
            lineas = [f"{k} - {v}" if v else k for k, v in valor_raw.items()]
            texto_valor = '\n'.join(lineas)
        else:
            texto_valor = _texto_valor(campo, valor_raw)
    else:
        texto_valor = _texto_valor(campo, valor_raw)
    nota = campo.get('notas') if campo['id'] in NOTAS_A_IMPRIMIR.get(anexo, ()) else None
    label = _label_campo(campo, anexo, valores)
    if nota and anexo in NOTAS_ANTES_DE_DOSPUNTOS:
        encabezado = f"{label} ({nota}):"
    else:
        encabezado = f"{label}:" + (f" ({nota})" if nota else '')
    pdf.set_font('helvetica', 'B' if negrita else '', TAM_TEXTO)
    pdf.multi_cell(0, ALTO_LINEA, encabezado, align='L', new_x='LMARGIN', new_y='NEXT')
    pdf.set_font('helvetica', '', TAM_TEXTO)
    if texto_valor:
        with _valor_destacado(pdf, TAM_TEXTO, DELTA_VALOR):
            pdf.multi_cell(0, ALTO_LINEA, texto_valor, align='L', new_x='LMARGIN', new_y='NEXT')
    else:
        renglones = RENGLONES_BLANCO.get(f"{anexo}.{campo['id']}",
                                         RENGLONES_BLANCO.get(campo['id'], 1 if anexo == 'VI' else RENGLONES_TEXTAREA))
        for _ in range(renglones):
            pdf.cell(0, ALTO_LINEA, '', border='B', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(2)


def _dibujar_nota(pdf, campo):
    # tipo "nota": texto fijo del papel (no un campo a completar) — sin "label: valor".
    pdf.set_font('helvetica', '', TAM_TEXTO)
    pdf.multi_cell(0, ALTO_LINEA, campo['label'], align='L', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(2)


def _valor_narrativa(campo, valor, mapeo):
    if mapeo:
        return mapeo.get(valor, '')
    return _texto_valor(campo, valor)


# Sin días cargados (anexo en blanco para completar a mano) va el texto tachable del papel,
# que no es igual en los dos anexos.
ARTICULO_DIAS_TACHABLE = {'VI': 'el/los día/días', 'VII': 'el día/ los días'}


def _articulo_dias(dias_texto, anexo):
    """"el día"/"los días" según `dias_salida` tenga uno o varios días — reemplaza el
    "el/los día/días" tachable del papel, ya que acá se resuelve solo con el dato cargado."""
    if not dias_texto:
        return ARTICULO_DIAS_TACHABLE.get(anexo, '')
    return 'los días' if re.search(r'[,\-]|\b(y|al)\b', dias_texto) else 'el día'


_DEL_MES = ' del mes de {mes_salida}'


def _dibujar_narrativa(pdf, bloque, valores, campos_por_id, anexo):
    mapeos = bloque.get('mapeos', {})
    valores_texto = {id: _valor_narrativa(campos_por_id[id], valores.get(id), mapeos.get(id))
                      for id in bloque['ids']}
    # Los días ya traen el mes ("28 al 30 de septiembre"): el "del mes de ___" del papel
    # quedaría repetido. Salidas guardadas antes traen sólo "28 al 30" y lo conservan.
    mes = valores_texto.get('mes_salida')
    if mes and mes in valores_texto.get('dias_salida', ''):
        bloque = dict(bloque)
        if 'segmentos' in bloque:
            bloque['segmentos'] = [(t.replace(_DEL_MES, ''), e) for t, e in bloque['segmentos']]
        else:
            bloque['texto'] = bloque['texto'].replace(_DEL_MES, '')
    sin_dato_bloque = dict(bloque.get('sin_dato', {}))
    if 'dias_salida' in valores_texto:
        articulo = _articulo_dias(valores_texto['dias_salida'], anexo)
        if valores_texto['dias_salida']:
            valores_texto['dia_articulo'] = articulo
        else:
            # Sin días es el "el/los día/días" tachable del papel: texto fijo, no un dato
            # cargado, así que va sin destacar (por `sin_dato`, no como valor).
            sin_dato_bloque['dia_articulo'] = [(articulo, '')] if 'segmentos' in bloque else articulo
    if 'segmentos' in bloque:
        # Párrafo con partes en negrita/itálica (ver Anexo VII) — pdf.write() para poder
        # cambiar de estilo sin forzar un salto de línea entre segmentos, igual que
        # _escribir_par con label/valor.
        for texto, estilo in bloque['segmentos']:
            pdf.set_font('helvetica', estilo, TAM_TEXTO)
            # Partir el texto por placeholders {id} y destacar solo los valores interpolados
            partes = re.split(r'\{(\w+)\}', texto)
            for i, parte in enumerate(partes):
                if i % 2 == 0:
                    # Texto literal (no es placeholder)
                    _write(pdf, parte)
                else:
                    # Es un placeholder {id} — escribir el valor destacado, pero sin cambiar el estilo
                    # (esto es, un {tipo_salida} en negrita se queda en negrita, con el trazo agregado).
                    # Sin valor: línea en blanco para completar a mano, igual que _escribir_par.
                    valor = valores_texto.get(parte, '')
                    sin_dato = sin_dato_bloque.get(parte)
                    if valor:
                        with _trazo_valor(pdf):  # sin cambiar la fuente: conserva `estilo`
                            _write(pdf, valor)
                    elif sin_dato:
                        # Texto fijo del papel en vez de blanco, con sus propios estilos:
                        # lista de (texto, estilo) como `segmentos`.
                        for texto_fijo, estilo_fijo in sin_dato:
                            pdf.set_font('helvetica', estilo_fijo, TAM_TEXTO)
                            _write(pdf, texto_fijo)
                    elif parte in bloque.get('anchos_resto_linea', ()):
                        _cell_resto_linea(pdf, partes[i + 1] if i + 1 < len(partes) else '')
                    else:
                        _cell_blanco(pdf, ANCHOS_BLANCO_NARRATIVA.get(parte, ANCHO_BLANCO_NARRATIVA))
                    pdf.set_font('helvetica', estilo, TAM_TEXTO)
        pdf.ln(ALTO_LINEA)
    else:
        # Rama sin segmentos (Anexos III, VI): un solo texto corrido, sin estilos internos
        # Partir por placeholders y escribir en secuencia con pdf.write()
        partes = re.split(r'\{(\w+)\}', bloque['texto'])
        pdf.set_font('helvetica', '', TAM_TEXTO)
        for i, parte in enumerate(partes):
            if i % 2 == 0:
                # Texto literal (no es placeholder)
                _write(pdf, parte)
            else:
                # Es un placeholder {id} — escribir el valor destacado, o una línea en
                # blanco para completar a mano si no vino cargado.
                valor = valores_texto.get(parte, '')
                sin_dato = sin_dato_bloque.get(parte)
                if valor:
                    with _valor_destacado(pdf, TAM_TEXTO):
                        _write(pdf, valor)
                elif sin_dato:
                    _write(pdf, sin_dato)
                elif parte in bloque.get('anchos_resto_linea', ()):
                    _cell_resto_linea(pdf, partes[i + 1] if i + 1 < len(partes) else '')
                else:
                    _cell_blanco(pdf, ANCHOS_BLANCO_NARRATIVA.get(parte, ANCHO_BLANCO_NARRATIVA))
        pdf.ln(ALTO_LINEA)
    pdf.ln(2)


# Proporción de las 5 columnas de la cajita de obra social, medida sobre el original (VI y
# VII son iguales): "Tiene Obra Social/Prepaga" | Sí | No | Nombre/N° Socio | valor.
OBRA_SOCIAL_PROPORCION = (126, 38, 38, 141, 202)
OBRA_SOCIAL_ALTOS = (12, 10)  # mm — fila "Nombre de la Obra Social/Prepaga", fila "N° Socio"


def _texto_en_caja(pdf, x, y, ancho, alto, texto, arriba=False):
    """Texto centrado en una celda ya dibujada, partido en renglones si no entra."""
    lineas = pdf.multi_cell(ancho - 2, 4.5, texto, align='C', dry_run=True, output='LINES')
    alto_texto = 4.5 * len(lineas)
    pdf.set_xy(x + 1, y + (1.5 if arriba else (alto - alto_texto) / 2))
    pdf.multi_cell(ancho - 2, 4.5, texto, align='C')


def _dibujar_obra_social(pdf, valores):
    # En el papel no es una lista "label: valor": "Tiene Obra Social/Prepaga" ocupa las dos
    # filas, Sí y No son dos columnas para marcar con una X, y a la derecha van nombre y N° de
    # socio uno arriba del otro. Sin respuesta (el VI/VII en blanco que imprime la escuela) no
    # se marca ninguna: sólo True/False de la familia es una respuesta.
    tiene_obra = valores.get('tiene_obra_social')
    alto1, alto2 = OBRA_SOCIAL_ALTOS
    alto = alto1 + alto2
    if pdf.get_y() + alto > pdf.page_break_trigger:
        pdf.add_page()
    total = sum(OBRA_SOCIAL_PROPORCION)
    w_tiene, w_si, w_no, w_label, w_valor = (pdf.epw * p / total for p in OBRA_SOCIAL_PROPORCION)
    x0, y0 = pdf.l_margin, pdf.get_y() + 2
    x_si, x_no = x0 + w_tiene, x0 + w_tiene + w_si
    x_label = x_no + w_no
    x_valor = x_label + w_label

    pdf.set_font('helvetica', '', TAM_TEXTO - 1)
    for x, w in ((x0, w_tiene), (x_si, w_si), (x_no, w_no)):
        pdf.rect(x, y0, w, alto)
    for x, w in ((x_label, w_label), (x_valor, w_valor)):
        pdf.rect(x, y0, w, alto1)
        pdf.rect(x, y0 + alto1, w, alto2)
    _texto_en_caja(pdf, x0, y0, w_tiene, alto, 'Tiene Obra Social/Prepaga')
    _texto_en_caja(pdf, x_si, y0, w_si, alto, 'Sí', arriba=True)
    _texto_en_caja(pdf, x_no, y0, w_no, alto, 'No', arriba=True)
    _texto_en_caja(pdf, x_label, y0, w_label, alto1, 'Nombre de la Obra Social/Prepaga')
    _texto_en_caja(pdf, x_label, y0 + alto1, w_label, alto2, 'N° Socio')

    if tiene_obra is True or tiene_obra is False:
        x_marca = x_si if tiene_obra else x_no
        with _valor_destacado(pdf, TAM_TEXTO, 2):
            _texto_en_caja(pdf, x_marca, y0 + 5, w_si, alto - 5, 'X')

    for y, a, clave in ((y0, alto1, 'nombre_obra_social'), (y0 + alto1, alto2, 'numero_socio')):
        texto = _sanear_latin1(str(valores.get(clave) or '')) if tiene_obra else ''
        if not texto:
            continue
        with _valor_destacado(pdf, TAM_TEXTO, DELTA_VALOR):
            # Una sola línea: si el nombre es largo se achica la letra antes que desbordar la celda.
            tam = TAM_TEXTO + DELTA_VALOR
            while tam > 7 and pdf.get_string_width(texto) > w_valor - 3:
                tam -= 0.5
                pdf.set_font_size(tam)
            pdf.set_xy(x_valor + 1.5, y)
            pdf.cell(w_valor - 3, a, texto, align='L')

    pdf.set_font('helvetica', '', TAM_TEXTO)
    pdf.set_xy(pdf.l_margin, y0 + alto + 4)


def _dibujar_titulo_seccion(pdf, anexo, titulo):
    pdf.set_font('helvetica', 'B', TAM_TEXTO)
    pdf.ln(2)
    pdf.multi_cell(0, ALTO_LINEA, titulo, align='L', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(1)
    pdf.set_font('helvetica', '', TAM_TEXTO)


# Los 4 campos de póliza del bloque "Datos del seguro escolar" del Anexo IX. Son los que se
# repiten cuando la escuela tiene más de un seguro vigente (ver `_seguros_adicionales` en
# formulario.html): el bloque entero, con su título, una vez por póliza. `observaciones`
# queda afuera a propósito — es del anexo, no de la póliza, y va una sola vez al final.
CAMPOS_SEGURO_IX = ('compania_aseguradora', 'tipo_seguro', 'numero_poliza', 'vigencia_poliza')


def _dibujar_seguros_ix(pdf, valores, campos_por_id):
    # El primer seguro son los campos sueltos del anexo; los demás, cada entrada de
    # `_seguros_adicionales`, que trae esas mismas 4 claves.
    for i, seguro in enumerate([valores] + list(valores.get('_seguros_adicionales') or [])):
        if i:  # el título de la primera repetición ya lo puso el loop general
            _dibujar_titulo_seccion(pdf, 'IX', SECCION_TITULOS['IX']['seguro_escolar'])
        for id_campo in CAMPOS_SEGURO_IX:
            _dibujar_campo(pdf, campos_por_id[id_campo], seguro, 'IX')


# Anchos (mm) de las dos líneas en blanco del renglón de un docente. Sobra hoja hasta el margen,
# así que en vez del ANCHO_BLANCO_PAR_EXTRA parejo van con la proporción del papel: el nombre
# completo escrito a mano necesita bastante más lugar que "Preceptor" o "Prof. de Historia".
# El papel además deja debajo dos renglones anchos más para los titulares y uno para los
# reemplazantes; acá no se dibujan porque el Anexo IV en blanco ya termina a 3mm del pie de la
# página 2 y cualquiera de ellos lo empuja a una tercera hoja con un solo campo.
ANCHO_BLANCO_DOCENTE = {'apellido_nombre': 60, 'cargo': 40}


def _dibujar_docentes(pdf, campo, valores, anexo):
    negrita = anexo in ANEXOS_LABEL_NEGRITA
    pdf.set_font('helvetica', '', TAM_TEXTO)
    pdf.multi_cell(0, ALTO_LINEA, f"{campo['label']}:", align='L', new_x='LMARGIN', new_y='NEXT')
    filas = valores.get(campo['id']) or [{}]  # sin docentes, el original igual deja el renglón para completar
    for fila in filas:
        # Por `_escribir_par` y no escribiendo el valor derecho: sin dato, deja la línea en
        # blanco donde anotarlo. Antes se escribía la cadena vacía y el renglón salía
        # "Apellido y Nombre:     Cargo:", todo junto y sin lugar para completar a mano.
        _escribir_par(pdf, 'Apellido y Nombre', fila.get('apellido_nombre', ''), negrita, anexo,
                      ANCHO_BLANCO_DOCENTE['apellido_nombre'])
        _write(pdf, '     ')
        _escribir_par(pdf, 'Cargo', fila.get('cargo', ''), negrita, anexo,
                      ANCHO_BLANCO_DOCENTE['cargo'])
        pdf.ln(ALTO_LINEA)
    pdf.ln(1)


def _dibujar_firmas_ix(pdf, valores):
    # Dos columnas lado a lado; la de la derecha sólo si es gestión privada (mismo criterio
    # que la `condicion` de `firma_sello_representante_legal` en el JSON, pero acá no se
    # puede usar esa `condicion` porque las dos columnas se dibujan juntas.
    privada = valores.get('tipo_gestion') == 'privada'
    ancho = 95
    pdf.ln(10)  # espacio en blanco para firmar a mano, como en el original
    pdf.set_font('helvetica', '', TAM_TEXTO)
    pdf.set_x(pdf.l_margin)
    pdf.cell(ancho, ALTO_LINEA, 'FIRMA Y SELLO', align='C')
    if privada:
        pdf.cell(0, ALTO_LINEA, 'FIRMA Y SELLO', align='C')
    pdf.ln(ALTO_LINEA)
    pdf.set_x(pdf.l_margin)
    pdf.cell(ancho, ALTO_LINEA, 'DIRECTOR/A', align='C')
    if privada:
        pdf.cell(0, ALTO_LINEA, 'REPRESENTANTE LEGAL', align='C')
    pdf.ln(ALTO_LINEA)
    pdf.ln(2)


def _dibujar_tabla(pdf, campo, valores):
    # Sin título arriba: en el original (Anexo V es el único caso) la grilla arranca
    # directo después del último campo de identificación, sin un encabezado propio.
    columnas = campo['columnas']
    filas_datos = valores.get(campo['id']) or []
    col_widths = COL_WIDTHS.get(campo['id'])

    with pdf.table(text_align='LEFT', col_widths=col_widths) as table:
        # Encabezado (labels de las columnas)
        row = table.row()
        for c in columnas:
            row.cell(c['label'], style=FontFace(size_pt=TAM_TEXTO - 2))

        # Filas de datos
        if filas_datos:
            for fila in filas_datos:
                row = table.row()
                for c in columnas:
                    valor_celda = _texto_valor(c, fila.get(c['id']))
                    row.cell(valor_celda, style=FontFace(size_pt=TAM_TEXTO - 1))
        else:
            # Sin datos: fila con dashes, pero con tamaño destacado
            row = table.row()
            for _ in columnas:
                row.cell('-', style=FontFace(size_pt=TAM_TEXTO - 1))
    pdf.ln(3)


# Anexos donde `notas_generales` (Salidas/AnexoN.json) se verificó contra el original: en
# el papel es el párrafo de cierre, después de las firmas ("El presente formulario puede
# ser completado de forma digital..."). No se imprime para el resto hasta revisarlos uno
# por uno — imprimirla sin verificar arriesgaría meter, en otro anexo, exactamente el tipo
# de texto-que-no-existe-en-el-papel que este mecanismo busca evitar.
NOTAS_GENERALES_A_IMPRIMIR = {'V', 'VIII'}

# El párrafo de `notas_generales` no siempre va suelto: el VIII lo encabeza con "Aclaración:"
# en negrita (ver Salidas/Anexo8.md), el V no trae ningún título. Por anexo, no default global.
NOTAS_GENERALES_TITULO = {'VIII': 'Aclaración:'}


def _generar_pdf_anexo(anexo, valores, destino):
    schema = _cargar_schema(anexo)
    pdf = _crear_pdf()
    pdf.fuente_doc = schema['fuente']  # va en el pie de cada página (ver _PDFAnexo.footer), no bajo el título
    pdf.add_page()

    # Título centrado y subrayado, como en el original. Varios títulos del JSON son en
    # realidad dos líneas del papel unidas con " — " (ej. Anexo IV: "PRESENTACIÓN..." /
    # "FORMULARIO DE ITINERARIO..."); separarlas de nuevo en el render se acerca más a la
    # hoja real que una sola línea larga centrada.
    pdf.set_font('helvetica', 'BU', 14)
    pdf.multi_cell(0, 8, f"ANEXO {anexo}", align='C', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(6)
    pdf.set_font('helvetica', 'B', TAM_TEXTO)
    for i, parte in enumerate(schema['titulo'].split(' — ')):
        # En mayúscula: así está el título en todos los anexos del original (verificado en
        # los 7) — el JSON lo guarda en caja de oración porque es más legible como dato.
        if i:
            pdf.ln(6)  # renglón en blanco entre las dos líneas del título, como en el papel
        pdf.multi_cell(0, 6, parte.upper(), align='C', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(6)

    titulos_seccion = SECCION_TITULOS.get(anexo, {})
    campos_por_id = {c['id']: c for c in schema['campos']}
    grupos_linea = CAMPOS_MISMA_LINEA.get(anexo, [])
    grupo_por_disparador = {g[0]: g[1:] for g in grupos_linea}  # primer id -> resto del renglón
    ids_resto_linea = {id for g in grupos_linea for id in g[1:]}  # se dibujan junto al primero
    narrativas = PARRAFOS_NARRATIVA.get(anexo, [])
    narrativa_por_disparador = {b['ids'][0]: b for b in narrativas}  # primer id -> bloque
    ids_narrativa_resto = {id for b in narrativas for id in b['ids'][1:]}  # el resto no se dibuja solo
    procesados = set()  # ids ya dibujados por un caso especial (obra social) — no se repiten
    seccion_actual = object()  # distinto de cualquier valor real, para forzar el primer título
    sin_imprimir = CAMPOS_SIN_IMPRIMIR.get(anexo, ())
    for campo in sorted(schema['campos'], key=lambda c: c['orden']):
        if (campo['id'] in procesados or campo['id'] in ids_resto_linea or campo['id'] in ids_narrativa_resto
                or campo['id'] in sin_imprimir or not _condicion_cumple(campo, valores)):
            continue
        if campo.get('seccion') != seccion_actual:
            seccion_actual = campo.get('seccion')
            titulo = titulos_seccion.get(seccion_actual)
            if seccion_actual in SECCIONES_PAGINA_NUEVA.get(anexo, ()) and pdf.get_y() > 40:  # 28 = donde header() deja el cursor
                pdf.add_page()
            if titulo:
                _dibujar_titulo_seccion(pdf, anexo, titulo)

        if campo['id'] in CAMPOS_PAGINA_NUEVA.get(anexo, ()) and pdf.get_y() > 40:
            pdf.add_page()

        if campo['id'] in narrativa_por_disparador:
            _dibujar_narrativa(pdf, narrativa_por_disparador[campo['id']], valores, campos_por_id, anexo)
        elif campo['id'] == 'tiene_obra_social':
            _dibujar_obra_social(pdf, valores)
            procesados.update(CAMPOS_OBRA_SOCIAL)
        elif anexo == 'IX' and campo['id'] == CAMPOS_SEGURO_IX[0]:
            _dibujar_seguros_ix(pdf, valores, campos_por_id)
            procesados.update(CAMPOS_SEGURO_IX)
        elif campo['id'] in CAMPOS_DOCENTES:
            _dibujar_docentes(pdf, campo, valores, anexo)
        elif campo['id'] in CAMPOS_FIRMA_IX:
            _dibujar_firmas_ix(pdf, valores)
            procesados.update(CAMPOS_FIRMA_IX)
        elif campo['tipo'] == 'tabla':
            _dibujar_tabla(pdf, campo, valores)
        elif campo['tipo'] == 'nota':
            _dibujar_nota(pdf, campo)
        elif campo['tipo'] == 'textarea' or campo['id'] in RENGLONES_BLANCO:
            _dibujar_textarea(pdf, campo, valores, anexo)
        elif campo['id'] in grupo_por_disparador:
            _dibujar_campo(pdf, campo, valores, anexo,
                           extra=[campos_por_id[i] for i in grupo_por_disparador[campo['id']]])
        else:
            _dibujar_campo(pdf, campo, valores, anexo)

    if anexo in NOTAS_GENERALES_A_IMPRIMIR and schema.get('notas_generales'):
        pdf.ln(2)
        titulo = NOTAS_GENERALES_TITULO.get(anexo)
        if titulo:
            pdf.set_font('helvetica', 'B', TAM_TEXTO)
            pdf.multi_cell(0, ALTO_LINEA, titulo, align='L', new_x='LMARGIN', new_y='NEXT')
        # Mismo cuerpo e interlineado que una nota del cuerpo (_dibujar_nota): en el papel
        # es un párrafo más del formulario, no una letra chica al pie.
        pdf.set_font('helvetica', '', TAM_TEXTO)
        pdf.multi_cell(0, ALTO_LINEA, schema['notas_generales'], align='L', new_x='LMARGIN', new_y='NEXT')

    if destino is None:
        # El PDF de una familia por el link público no se cachea en disco (ver
        # completar()/pdf_publico) — se devuelve en memoria para mandarlo directo en la
        # respuesta.
        return bytes(pdf.output())
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    pdf.output(destino)


def _limpiar_pdfs_ix_extra(id):
    carpeta = _carpeta_pdfs(id)
    if not os.path.isdir(carpeta):
        return
    for nombre in os.listdir(carpeta):
        if _RE_PDF_IX_EXTRA.match(nombre):
            os.remove(os.path.join(carpeta, nombre))


def _anexo_vacio(valores):
    """True si no hay ningún valor cargado (ignora claves internas como `_seguros_adicionales`)."""
    return not any(v for clave, v in valores.items() if not clave.startswith('_'))


def _generar_pdfs(id, anexos):
    """Un PDF por anexo (III a IX), guardado en disco — nunca se descargan solos.

    Los seguros escolares adicionales del Anexo IX (ver `_seguros_adicionales` en
    formulario.html) van todos en ese mismo PDF, repitiendo el bloque "Datos del seguro
    escolar" una vez por póliza (`_dibujar_seguros_ix`). Hasta 2026-09-09 cada uno generaba
    una copia completa aparte (`AnexoIX_2.pdf`, ...); se siguen borrando las que hayan
    quedado en disco de salidas guardadas antes de ese cambio.
    """
    os.makedirs(PDF_DIR, exist_ok=True)
    with TemporaryDirectory(dir=PDF_DIR) as temporal:
        preparados = {}
        for n in ANEXOS_NUMEROS:
            valores = anexos.get(n) or {}
            if n in ANEXOS_OPCIONALES_SI_VACIOS and _anexo_vacio(valores):
                continue
            destino = os.path.join(temporal, f'Anexo{n}.pdf')
            _generar_pdf_anexo(n, valores, destino)
            preparados[n] = destino
        os.makedirs(_carpeta_pdfs(id), exist_ok=True)
        for n in ANEXOS_NUMEROS:
            ruta = _ruta_pdf(id, n)
            if n in preparados:
                os.replace(preparados[n], ruta)
            elif os.path.exists(ruta):
                os.remove(ruta)
        _limpiar_pdfs_ix_extra(id)


# --- Link público: familias/estudiantes completan el VI/VII solos -------------
#
# El VI (autoriza el padre/madre/tutor de un estudiante menor de edad) y el VII
# (declaración jurada del propio estudiante mayor de edad) son, en el papel, uno por
# estudiante — no uno por salida. Hasta acá la única forma de completarlos era que la
# escuela cargue UN estudiante en el formulario general y el resto de las familias
# complete a mano sobre una fotocopia en blanco (de ahí el mecanismo de líneas en blanco
# de `_escribir_par`/`_dibujar_narrativa`). El link público reemplaza esa fotocopia:
# cada familia entra con el mismo link, ve los datos que la escuela ya cargó (destino,
# fechas, establecimiento — los mismos campos `auto`/`calc` de formulario.html), completa
# SOLO lo suyo (identidad del estudiante, salud, contacto de urgencia) y se lleva su propio
# PDF ya completado para imprimir y hacer firmar. Nada de esto se guarda del lado de la
# escuela: lo que completa la familia vive sólo en su sesión de navegador (session de Flask,
# cookie firmada, se pierde al cerrar el navegador) el tiempo justo para generar y servir su
# PDF — ver dev-log/DECISIONS.md 2026-08-16. El PDF real (firmado a mano) se devuelve en
# papel a la escuela; no hace falta ni conviene guardar una copia digital con DNI y datos de
# salud de cada estudiante. Nunca pisa el `datos_json` de la salida ni el VI/VII "en blanco"
# que ya se genera siempre (ese sigue sirviendo de vista previa para la escuela).
#
# Campos editables por anexo: el mismo subconjunto de formulario.html (ANEXOS VI/VII) que
# NO tiene `auto`/`calc` (lo que la escuela ya sabe no se vuelve a pedir) y que NO es de
# firma (`firma_papel`: esos van a mano sobre el papel impreso, nunca se tipean — ver
# dev-log/DECISIONS.md 2026-08-14/15). Sincronizado a mano con formulario.html: si se
# agrega o saca un campo family/estudiante ahí, replicar acá.
CAMPOS_FAMILIA = {
    'VI': [
        {'id': 'nombre_estudiante', 'label': 'Nombre del hijo/a', 'tipo': 'text', 'req': True},
        {'id': 'dni_estudiante', 'label': 'DNI del hijo/a', 'tipo': 'text', 'req': True},
        {'id': 'indicaciones_salud',
         'label': 'Dejar aquí constancia de cualquier indicación necesaria que deba conocer el '
                  'docente a cargo y personal médico',
         'tipo': 'textarea', 'req': False,
         'ayuda': 'Alergias, medicación, tratamientos o condiciones que el/la docente a cargo '
                  'tenga que conocer ante una urgencia. Si no hay nada para informar, se deja en blanco.'},
        {'id': 'tiene_obra_social', 'label': '¿Tiene obra social o prepaga?', 'tipo': 'bool', 'req': True},
        {'id': 'nombre_obra_social', 'label': 'Nombre de la obra social/prepaga', 'tipo': 'text',
         'req': False, 'cond': 'tiene_obra_social'},
        {'id': 'numero_socio', 'label': 'N° de socio', 'tipo': 'text', 'req': False, 'cond': 'tiene_obra_social'},
        {'id': 'telefonos_urgencia', 'label': 'Teléfonos de contacto en caso de urgencia', 'tipo': 'textarea',
         'req': True, 'ayuda': 'Consignar varios, de personas distintas.'},
    ],
    'VII': [
        {'id': 'nombre_estudiante', 'label': 'Nombre y apellido', 'tipo': 'text', 'req': True},
        {'id': 'dni_estudiante', 'label': 'DNI', 'tipo': 'text', 'req': True},
        {'id': 'domicilio', 'label': 'Domicilio', 'tipo': 'text', 'req': True,
         'ayuda': 'Domicilio particular, no el de la escuela.'},
        {'id': 'localidad', 'label': 'Localidad de domicilio', 'tipo': 'text', 'req': True},
        {'id': 'indicaciones_salud',
         'label': 'Dejar aquí constancia de cualquier indicación necesaria que deba conocer el '
                  'docente a cargo y personal médico',
         'tipo': 'textarea', 'req': False,
         'ayuda': 'Alergias, medicación o condiciones que el/la docente a cargo deba conocer ante una urgencia.'},
        {'id': 'tiene_obra_social', 'label': '¿Tiene obra social o prepaga?', 'tipo': 'bool', 'req': True},
        {'id': 'nombre_obra_social', 'label': 'Nombre de la obra social/prepaga', 'tipo': 'text',
         'req': False, 'cond': 'tiene_obra_social'},
        {'id': 'numero_socio', 'label': 'N° de socio', 'tipo': 'text', 'req': False, 'cond': 'tiene_obra_social'},
        {'id': 'telefonos_urgencia', 'label': 'Teléfonos de contacto en caso de urgencia', 'tipo': 'textarea',
         'req': True, 'ayuda': 'Consignar varios, de personas distintas.'},
    ],
}

TITULOS_ANEXO_FAMILIA = {
    'VI': 'Autorización familiar — estudiante menor de edad',
    'VII': 'Declaración jurada — estudiante mayor de edad o emancipado/a',
}


def _procesar_form_familia(anexo, form):
    """Valida y arma el dict de campos que completó la familia/estudiante. Devuelve
    (datos, errores) — `errores` es la lista de labels que faltaron."""
    datos = {}
    errores = []
    for campo in CAMPOS_FAMILIA[anexo]:
        if campo['tipo'] == 'bool':
            valor = form.get(campo['id']) == 'true'
        else:
            valor = (form.get(campo['id']) or '').strip()
        aplica = not campo.get('cond') or datos.get(campo['cond']) is True
        if not aplica:
            valor = '' if campo['tipo'] != 'bool' else False
        # Un booleano nunca está "vacío" (tildado/destildado son las dos respuestas
        # válidas) — `req` en un bool sólo tiene sentido para forzar el resto de la
        # validación (los campos que dependen de él vía `cond`), no acá.
        elif campo.get('req') and campo['tipo'] != 'bool' and not valor:
            errores.append(campo['label'])
        datos[campo['id']] = valor
    return datos, errores


# --- Acceso y contexto compartido ---------------------------------------------

# Clave propia del área: `SALIDAS_CLAVE` en el .env. Quien la pone tiene todo Salidas
# (ver y cargar) y nada más. Se SUMA a la sesión que haya —no la limpia— y en la cookie
# va su huella, no un booleano: cambiar la clave en el .env corta en el acto a todos los
# que entraron con la anterior. Sin la variable, esta puerta no existe y sólo entra el
# admin o un dispositivo con permiso de salidas.
SESION_CLAVE = 'salidas_clave'


def _clave_propia():
    return os.environ.get('SALIDAS_CLAVE') or None


def _huella(clave):
    return hashlib.sha256(('salidas:' + clave).encode('utf-8')).hexdigest()[:12]


def _acceso_con_clave():
    """Hook de `accesos`: lo que da haber entrado con SALIDAS_CLAVE."""
    clave = _clave_propia()
    if not clave or session.get(SESION_CLAVE) != _huella(clave):
        return None
    return {'tipo': 'salidas', 'nombre': 'Salidas educativas',
            'permisos': [PERMISO_LECTURA, PERMISO_ESCRITURA]}


def _entrar_con_clave(clave):
    propia = _clave_propia()
    if not propia or not hmac.compare_digest(clave.encode('utf-8'), propia.encode('utf-8')):
        return False
    session.permanent = True
    session[SESION_CLAVE] = _huella(propia)
    return True


def _entrar(clave):
    """`/salidas/login`: la de admin de siempre o la del área."""
    return accesos.entrar_admin(clave) or _entrar_con_clave(clave)


accesos.registrar_acceso_extra(_acceso_con_clave, en_sesion=True)
accesos.registrar_entrada(_entrar_con_clave)
accesos.registrar_acceso(bp, PERMISO_LECTURA, endpoint_default='lista', entrar=_entrar)


@bp.context_processor
def _contexto():
    # inventarios/inv_activo: los pide el widget del asistente (ver _agente_widget.html),
    # que acá no tiene un `<inv>` en la URL que se lo fije como en la app de Gestión — el
    # selector es la única forma de ver o cambiar en cuál está trabajando.
    inventarios = gestion.abribles()
    inv_activo = gestion.slug_activo()
    if inv_activo not in [f['slug'] for f in inventarios]:
        inv_activo = None
    return {
        'escuela_nombre': ESCUELA_NOMBRE,
        'escuela_logo': ESCUELA_LOGO,
        'escuela_version': ESCUELA_VERSION,
        'inventarios': inventarios,
        'inv_activo': inv_activo,
    }


# --- Rutas ----------------------------------------------------------------

@bp.route('/')
def lista():
    ver_archivadas = request.args.get('archivadas') == '1'
    con = conectar()
    cur = con.cursor()
    filas = cur.execute(
        "SELECT id, nombre_proyecto, fecha_salida, fecha_creacion, vigencia_hasta "
        "FROM salidas WHERE archivado = ? ORDER BY fecha_creacion DESC", (1 if ver_archivadas else 0,)).fetchall()
    cantidad_archivadas = cur.execute("SELECT COUNT(*) AS n FROM salidas WHERE archivado = 1").fetchone()['n']
    con.close()
    return render_template('salidas/lista.html', filas=filas, activo='lista',
                           ver_archivadas=ver_archivadas, cantidad_archivadas=cantidad_archivadas)


@bp.route('/nueva')
@accesos.requiere(PERMISO_ESCRITURA)
def nueva():
    normativa = _cargar_normativa()
    return render_template('salidas/formulario.html', activo='nueva', datos_precargar=None, id_editar=None,
                           normativa=normativa, esquema_formulario=esquema_formulario())


@bp.route('/padron')
@accesos.requiere(PERMISO_ESCRITURA)
def padron():
    """Alta/edición manual y carga por CSV del padrón de alumnos y profesores. Todo vive en
    localStorage del navegador (static/salidas-padron.js): esta ruta sólo sirve la plantilla,
    no hay ningún dato de personas en salidas.db ni en ningún otro lado del server."""
    return render_template('salidas/padron.html', activo='padron')


@bp.route('/nueva-tabs')
@accesos.requiere(PERMISO_ESCRITURA)
def nueva_tabs():
    """SANDBOX de diseño: /nueva con los PDF como pestañas en el header.

    Misma pantalla que `nueva()` — de hecho el template extiende el de ella y
    sólo pisa el bloque de acciones del header. Existe para probar el diseño
    sin tocar /salidas/nueva, que sigue igual. Cuando se decida, o se lleva el
    diseño al formulario y se borra esta ruta, o se borra todo.

    `?v=1|2|3` elige qué hace la línea naranja con la pestaña activa (ver el
    comentario de las variantes en el template).
    """
    variante = request.args.get('v', '1')
    if variante not in ('1', '2', '3'):
        variante = '1'
    normativa = _cargar_normativa()
    return render_template('salidas/formulario_tabs.html', activo='nueva', datos_precargar=None,
                           id_editar=None, normativa=normativa, variante=variante, esquema_formulario=esquema_formulario())


@bp.route('/<int:id>/editar')
@accesos.requiere(PERMISO_ESCRITURA)
def editar(id):
    con = conectar()
    cur = con.cursor()
    fila = cur.execute("SELECT datos_json, archivado, vigencia_hasta FROM salidas WHERE id = ?", (id,)).fetchone()
    con.close()
    if fila is None:
        abort(404)
    datos_precargar = json.loads(fila['datos_json'])
    _replicar_comunes(datos_precargar.get('anexos') or {}, datos_precargar.get('datos_comunes') or {})
    normativa = _cargar_normativa()
    return render_template('salidas/formulario.html', activo='nueva', id_editar=id, datos_precargar=datos_precargar,
                           normativa=normativa, archivado=bool(fila['archivado']),
                           esquema_formulario=esquema_formulario(),
                           revision_editar=revision_legajo(fila['datos_json']),
                           agente_habilitado=not fila['archivado'] and fila['vigencia_hasta'] > ahora().isoformat())


@bp.route('/api/guardar', methods=['POST'])
@accesos.requiere(PERMISO_ESCRITURA, como_json=True)
def api_guardar():
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return jsonify({'error': 'JSON inválido.'}), 400

    id = datos.get('_id_editar') or None
    revision = datos.pop('_revision_editar', None)
    with closing(conectar()) as con, con:
        con.execute('BEGIN IMMEDIATE')
        if id is not None and revision is not None:
            fila = con.execute('SELECT datos_json FROM salidas WHERE id=?', (id,)).fetchone()
            if fila is None:
                return jsonify({'error': 'Salida no encontrada.'}), 404
            if revision != revision_legajo(fila['datos_json']):
                return jsonify({'error': 'La salida cambió desde que la abriste. Revisá la versión actual antes de guardar.'}), 409
        id = guardar_legajo(con, datos, id)
    if id is None:
        return jsonify({'error': 'Salida no encontrada.'}), 404
    return jsonify({'id': id})


def revision_legajo(datos_json):
    return hashlib.sha256(datos_json.encode('utf-8')).hexdigest()


def guardar_legajo(con, datos, id=None):
    """Persiste datos y PDF con el bloqueo de escritura tomado por el llamador."""
    comunes = datos.get('datos_comunes') or {}
    anexos = datos.get('anexos') or {}
    # Replicar datos_comunes en cada anexo ANTES de guardar y de generar el PDF — si no,
    # los campos que sólo se cargan una vez en "Datos Comunes" (tipo_salida, distrito,
    # establecimiento_educativo, localidad_salida...) quedan en blanco en el PDF hasta que
    # alguien aprieta "Regenerar PDF" a mano (regenerar_pdfs sí hace este merge, pero desde
    # datos_json ya guardado — acá hace falta antes de guardar por primera vez).
    _replicar_comunes(anexos, comunes)

    if id is not None:
        actualizado = con.execute(
            "UPDATE salidas SET nombre_proyecto = ?, fecha_salida = ?, datos_json = ? WHERE id = ?",
            (comunes.get('denominacion_proyecto', '') or '', comunes.get('fecha_salida', '') or '',
             json.dumps(datos), id)).rowcount
        if not actualizado:
            return None
    else:
        # Inserción de nueva salida
        creado = ahora()
        vigencia = creado + timedelta(days=VIGENCIA_DIAS)
        id = con.execute(
            "INSERT INTO salidas (nombre_proyecto, fecha_salida, fecha_creacion, vigencia_hasta, "
            "datos_json, token) VALUES (?,?,?,?,?,?)",
            (comunes.get('denominacion_proyecto', '') or '', comunes.get('fecha_salida', '') or '',
             creado.isoformat(), vigencia.isoformat(), json.dumps(datos), _generar_token())).lastrowid

    _generar_pdfs(id, anexos)
    return id


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
    etiquetas = {n: n for n in disponibles}

    # Token de respaldo por si la migración todavía no corrió en este arranque (no debería
    # pasar: init_db migra antes de servir el primer request) — no deja el link roto.
    token = fila['token'] or _generar_token()

    return render_template('salidas/detalle.html', fila=fila,
                           datos_comunes=json.loads(fila['datos_json']).get('datos_comunes') or {},
                           anexos=disponibles, titulos=titulos, etiquetas=etiquetas,
                           link_familia=url_for('salidas_familia.landing', token=token, _external=True),
                           activo='lista')


@bp.route('/<int:id>/regenerar', methods=['POST'])
@accesos.requiere(PERMISO_ESCRITURA)
def regenerar_pdfs(id):
    """Rehace los 7 PDF de una salida ya guardada, a partir del `datos_json` que quedó en
    la fila — no hay otra forma de traerlos al día: se generan una sola vez al guardar
    (`api_guardar`) y quedan cacheados en disco, así que un cambio en el renderer (esta
    función, `_generar_pdf_anexo`) no toca los PDF de las salidas guardadas antes."""
    with closing(conectar()) as con, con:
        con.execute('BEGIN IMMEDIATE')
        fila = con.execute("SELECT datos_json FROM salidas WHERE id = ?", (id,)).fetchone()
        if fila is None:
            abort(404)
        datos = json.loads(fila['datos_json'])
        anexos = datos.get('anexos') or {}
        _replicar_comunes(anexos, datos.get('datos_comunes') or {})
        _generar_pdfs(id, anexos)
    return redirect(url_for('salidas.detalle', id=id))


@bp.route('/<int:id>/archivar', methods=['POST'])
@accesos.requiere(PERMISO_ESCRITURA)
def archivar(id):
    """Archiva una salida guardada: sale del listado por default (que se llena con los
    años) pero sigue existiendo igual — no toca la vigencia ni el borrado automático de
    _purgar_vencidas, es sólo una cuestión de qué se ve en /salidas."""
    con = conectar()
    cur = con.cursor()
    if cur.execute("UPDATE salidas SET archivado = 1 WHERE id = ?", (id,)).rowcount == 0:
        con.close()
        abort(404)
    con.commit()
    con.close()
    return redirect(url_for('salidas.lista'))


@bp.route('/<int:id>/archivar/revertir', methods=['POST'])
@accesos.requiere(PERMISO_ESCRITURA)
def archivar_revertir(id):
    con = conectar()
    cur = con.cursor()
    if cur.execute("UPDATE salidas SET archivado = 0 WHERE id = ?", (id,)).rowcount == 0:
        con.close()
        abort(404)
    con.commit()
    con.close()
    # Desarchivar desde /salidas (lista de archivadas) vuelve ahí; desde el formulario
    # (donde ya se está viendo la salida) se queda en el editar, como antes.
    if request.form.get('volver') == 'lista':
        return redirect(url_for('salidas.lista'))
    return redirect(url_for('salidas.editar', id=id))


@bp.route('/<int:id>/pdf/<anexo>')
def ver_pdf(id, anexo):
    con = conectar()
    cur = con.cursor()
    fila = cur.execute("SELECT nombre_proyecto FROM salidas WHERE id = ?", (id,)).fetchone()
    con.close()
    if fila is None:
        abort(404)

    # Allowlist explícita: `anexo` viene de la URL y arma una ruta de archivo.
    if anexo not in ANEXOS_NUMEROS:
        abort(404)
    ruta = _ruta_pdf(id, anexo)
    if not os.path.exists(ruta):
        abort(404)

    nombre_proyecto = fila['nombre_proyecto'] or 'Salida'
    nombre_archivo = f'{nombre_proyecto} - Anexo {anexo}.pdf'
    return send_file(ruta, mimetype='application/pdf', as_attachment=False,
                     download_name=nombre_archivo)




@bp.route('/instructivo')
def instructivo():
	"""Sirve el instructivo de salidas educativas."""
	ruta = os.path.join(_AQUI, 'INSTRUCTIVO SALIDAS EDUCATIVAS.pdf')
	if not os.path.exists(ruta):
		abort(404)
	return send_file(ruta, mimetype='application/pdf', as_attachment=False,
	                 download_name='Instructivo_Salidas_Educativas.pdf')


# --- Blueprint público: /salidas/completar/<token> -----------------------------
#
# A propósito OTRO blueprint, sin pasar por accesos.registrar_acceso: `bp` gatea TODO lo
# que registra (before_request exige salidas.leer en cualquier endpoint que no sea el
# login), así que la única forma de dejar una URL abierta sin tocar el gate de capa 1 es
# que no viva en ese blueprint. Mismo criterio que accesos.py usa para /acceso/<token>:
# registrado aparte, no dentro de un blueprint gateado. Comparte url_prefix con `bp`
# (/salidas) porque es la misma área — Flask no tiene problema con dos blueprints en el
# mismo prefijo mientras las rutas no choquen.
bp_publico = Blueprint('salidas_familia', __name__, url_prefix='/salidas')
bp_publico.before_request(_purgar_si_toca)


def _salida_por_token(token):
    con = conectar()
    fila = con.execute("SELECT * FROM salidas WHERE token = ?", (token,)).fetchone()
    con.close()
    return fila


@bp_publico.context_processor
def _contexto_publico():
    return {
        'escuela_nombre': ESCUELA_NOMBRE,
        'escuela_logo': ESCUELA_LOGO,
        'escuela_version': ESCUELA_VERSION,
    }


@bp_publico.route('/completar/<token>')
def landing(token):
    fila = _salida_por_token(token)
    if fila is None:
        abort(404)
    datos_comunes = json.loads(fila['datos_json']).get('datos_comunes') or {}
    return render_template('salidas/completar_landing.html', token=token,
                           nombre_proyecto=fila['nombre_proyecto'], datos_comunes=datos_comunes)


def _clave_sesion_familia(token, anexo):
    # Namespaced por token+anexo: en la misma sesión de navegador puede haber más de un
    # hijo/a completado (ver "¿Tenés más de un/a hijo/a?" en completar_listo.html), cada
    # uno con su propia entrada, sin pisarse.
    return f'familia_{token}_{anexo}'


@bp_publico.route('/completar/<token>/<anexo>', methods=['GET', 'POST'])
def completar(token, anexo):
    if anexo not in CAMPOS_FAMILIA:
        abort(404)
    fila = _salida_por_token(token)
    if fila is None:
        abort(404)
    datos = json.loads(fila['datos_json'])
    valores_base = (datos.get('anexos') or {}).get(anexo) or {}
    error = None
    valores_form = {}

    if request.method == 'POST':
        datos_familia, errores = _procesar_form_familia(anexo, request.form)
        if errores:
            error = 'Faltó completar: ' + ', '.join(errores) + '.'
            valores_form = datos_familia
        else:
            # No se guarda en ninguna DB ni se cachea el PDF en disco — vive sólo en la
            # sesión de este navegador (cookie firmada, se borra sola al cerrarlo) el
            # tiempo justo para que la familia vea/imprima su PDF. Ver dev-log/DECISIONS.md
            # 2026-08-16.
            session[_clave_sesion_familia(token, anexo)] = datos_familia
            return redirect(url_for('salidas_familia.listo', token=token, anexo=anexo))

    campos_familia = CAMPOS_FAMILIA[anexo]
    ids_familia = {c['id'] for c in campos_familia}
    schema = _cargar_schema(anexo)
    # Resumen de sólo lectura: lo que la escuela ya cargó (destino, fechas,
    # establecimiento...) para que la familia lo revise antes de completar lo suyo —
    # cualquier campo del schema que no sea editable acá y que ya tenga valor.
    campos_por_id = {c['id']: c for c in schema['campos']}

    def _texto_resumen(cid):
        # nombres_telefonos_acompanantes guarda un dict {nombre: teléfono} + una versión
        # "_texto" ya armada para mostrar (mismo caso especial que _dibujar_textarea).
        if cid + '_texto' in valores_base:
            return valores_base.get(cid + '_texto', '')
        return _texto_valor(campos_por_id[cid], valores_base.get(cid))

    resumen = [(_label_campo(campos_por_id[cid], anexo, valores_base), _texto_resumen(cid))
              for cid in sorted((c['id'] for c in schema['campos']), key=lambda cid: campos_por_id[cid]['orden'])
              if cid not in ids_familia and campos_por_id[cid]['tipo'] != 'nota' and valores_base.get(cid)]

    return render_template('salidas/completar.html', token=token, anexo=anexo,
                           titulo_anexo=TITULOS_ANEXO_FAMILIA[anexo], campos=campos_familia,
                           resumen=resumen, valores_base=valores_base, valores_form=valores_form,
                           error=error, nombre_proyecto=fila['nombre_proyecto'])


@bp_publico.route('/completar/<token>/<anexo>/listo')
def listo(token, anexo):
    fila = _salida_por_token(token)
    if fila is None:
        abort(404)
    if _clave_sesion_familia(token, anexo) not in session:
        abort(404)
    return render_template('salidas/completar_listo.html', token=token, anexo=anexo)


@bp_publico.route('/completar/<token>/<anexo>/pdf')
def pdf_publico(token, anexo):
    fila = _salida_por_token(token)
    if fila is None:
        abort(404)
    datos_familia = session.get(_clave_sesion_familia(token, anexo))
    if datos_familia is None:
        abort(404)
    datos = json.loads(fila['datos_json'])
    valores_base = (datos.get('anexos') or {}).get(anexo) or {}
    valores = dict(valores_base, **datos_familia)
    pdf_bytes = _generar_pdf_anexo(anexo, valores, None)
    return send_file(BytesIO(pdf_bytes), mimetype='application/pdf', as_attachment=False,
                     download_name=f'Anexo {anexo}.pdf')
