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
import re
import shutil
import sys
from datetime import timedelta

from flask import Blueprint, abort, jsonify, redirect, render_template, request, send_file, url_for
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


# El Anexo IX es el único con copias extra: si la escuela carga más de un seguro escolar
# (ver `_seguros_adicionales` en formulario.html), cada uno genera su propia Declaración
# Jurada completa — en el papel real no hay lugar para más de una póliza por copia. La
# primera sigue siendo `_ruta_pdf(id, 'IX')`; ésta es para la 2ª en adelante.
def _ruta_pdf_ix_extra(id, indice):
    return os.path.join(_carpeta_pdfs(id), f'AnexoIX_{indice}.pdf')


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
        # fpdf2 dibuja SVG directo (VectorImageInfo) — no hace falta rasterizar el escudo.
        self.image('static/images/escudo.svg', x=10, y=8, h=14)
        self.set_y(28)

    def footer(self):
        self.set_y(-24)
        self.set_font('helvetica', '', 7)
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


def _texto_valor(campo, valor):
    if valor is None or valor == '':
        return ''
    if campo['tipo'] == 'bool':
        return 'Sí' if valor else 'No'
    return str(valor)


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
}

# Dónde va la aclaración entre paréntesis respecto de los ":" tampoco es parejo: el Anexo V
# la pone DESPUÉS ("OBSERVACIONES:(Para ser completado...)"), el Anexo IV la pone ANTES
# ("Itinerario (detalle pormenorizado del mismo):") — verificado en el original de los dos.
# Sólo afecta a `_dibujar_textarea`; el default (después de los ":") es el de más anexos.
NOTAS_ANTES_DE_DOSPUNTOS = {'IV'}

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
        'ids': ('nombre_estudiante', 'dni_estudiante', 'establecimiento_educativo', 'numero_establecimiento',
                'distrito', 'localidad_salida', 'dias_salida', 'mes_salida'),
        'texto': ("Por la presente autorizo a mi hijo/a {nombre_estudiante}, DNI {dni_estudiante}, que "
                  "concurre al Establecimiento Educativo {establecimiento_educativo} N° {numero_establecimiento} "
                  "del distrito {distrito}, a participar de la Salida Educativa / Salida de Representación "
                  "Institucional a realizarse en la localidad de {localidad_salida} el/los día/días "
                  "{dias_salida} del mes de {mes_salida} del presente ciclo lectivo."),
    }],
    'VII': [{
        'ids': ('nombre_estudiante', 'dni_estudiante', 'domicilio', 'localidad', 'institucion', 'tipo_salida',
                'localidad_salida', 'dias_salida', 'mes_salida', 'anio_salida'),
        # `segmentos`: en el original "salida educativa / de representación institucional"
        # va en NEGRITA y "(tachar lo que no corresponda)" en ITÁLICA, dentro del mismo
        # párrafo — no es texto corrido de un solo estilo como III y VI. Cada tupla es
        # (texto con placeholders `.format()`, estilo de fpdf2: '' | 'B' | 'I').
        'segmentos': [
            ("Quien suscribe, {nombre_estudiante}, DNI {dni_estudiante}, domiciliada/o en la calle "
             "{domicilio} de la localidad de {localidad}, que concurre a la institución {institucion}, "
             "participará de la ", ''),
            ("{tipo_salida}", 'B'),
            (" ", ''),
            ("(tachar lo que no corresponda)", 'I'),
            (" a realizarse en la localidad de {localidad_salida} el día/los días {dias_salida} del mes de "
             "{mes_salida} del año {anio_salida}.", ''),
        ],
        # tipo_salida se guarda como slug de <select> — el papel espera el texto tachable.
        'mapeos': {'tipo_salida': {'educativa': 'salida educativa',
                                    'representacion_institucional': 'salida de representación institucional'}},
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


def _label_campo(campo, anexo):
    label = campo['label']
    return label.upper() if campo['id'] in LABELS_MAYUSCULA.get(anexo, ()) else label


def _escribir_par(pdf, label, valor, negrita):
    pdf.set_font('helvetica', 'B' if negrita else '', TAM_TEXTO)
    pdf.write(ALTO_LINEA, f"{label}: ")
    pdf.set_font('helvetica', '', TAM_TEXTO)
    pdf.write(ALTO_LINEA, valor)


def _dibujar_campo(pdf, campo, valores, anexo, extra=()):
    # En blanco a propósito cuando el campo no vino en lo guardado: son los de firma y
    # "lugar y fecha", que se completan a mano después de imprimir — igual que en el
    # papel, "Label: ________________" para completar. `extra`: los demás campos del mismo
    # renglón (ver CAMPOS_MISMA_LINEA), en orden, después del primero.
    negrita = anexo in ANEXOS_LABEL_NEGRITA
    texto_valor = _texto_valor(campo, valores.get(campo['id']))
    nota = campo.get('notas') if campo['id'] in NOTAS_A_IMPRIMIR.get(anexo, ()) else None
    _escribir_par(pdf, _label_campo(campo, anexo), texto_valor, negrita)
    if nota:
        pdf.write(ALTO_LINEA, f" ({nota})")
    for campo_extra in extra:
        texto_extra = _texto_valor(campo_extra, valores.get(campo_extra['id']))
        pdf.write(ALTO_LINEA, '     ')
        _escribir_par(pdf, _label_campo(campo_extra, anexo), texto_extra, negrita)
    pdf.ln(ALTO_LINEA)
    pdf.ln(2)


def _dibujar_textarea(pdf, campo, valores, anexo):
    # Con valor: se imprime. Sin valor: renglones en blanco con línea de base — es "para
    # completar en ese lugar" a mano, no un campo que simplemente queda vacío como los de
    # firma/lugar-y-fecha (ahí no hace falta renglón porque son una sola línea corta).
    negrita = anexo in ANEXOS_LABEL_NEGRITA
    texto_valor = _texto_valor(campo, valores.get(campo['id']))
    nota = campo.get('notas') if campo['id'] in NOTAS_A_IMPRIMIR.get(anexo, ()) else None
    label = _label_campo(campo, anexo)
    if nota and anexo in NOTAS_ANTES_DE_DOSPUNTOS:
        encabezado = f"{label} ({nota}):"
    else:
        encabezado = f"{label}:" + (f" ({nota})" if nota else '')
    pdf.set_font('helvetica', 'B' if negrita else '', TAM_TEXTO)
    pdf.multi_cell(0, ALTO_LINEA, encabezado, align='L', new_x='LMARGIN', new_y='NEXT')
    pdf.set_font('helvetica', '', TAM_TEXTO)
    if texto_valor:
        pdf.multi_cell(0, ALTO_LINEA, texto_valor, align='L', new_x='LMARGIN', new_y='NEXT')
    else:
        for _ in range(RENGLONES_TEXTAREA):
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


def _dibujar_narrativa(pdf, bloque, valores, campos_por_id):
    mapeos = bloque.get('mapeos', {})
    valores_texto = {id: _valor_narrativa(campos_por_id[id], valores.get(id), mapeos.get(id))
                      for id in bloque['ids']}
    if 'segmentos' in bloque:
        # Párrafo con partes en negrita/itálica (ver Anexo VII) — pdf.write() para poder
        # cambiar de estilo sin forzar un salto de línea entre segmentos, igual que
        # _escribir_par con label/valor.
        for texto, estilo in bloque['segmentos']:
            pdf.set_font('helvetica', estilo, TAM_TEXTO)
            pdf.write(ALTO_LINEA, texto.format(**valores_texto))
        pdf.ln(ALTO_LINEA)
    else:
        pdf.set_font('helvetica', '', TAM_TEXTO)
        pdf.multi_cell(0, ALTO_LINEA, bloque['texto'].format(**valores_texto), align='L',
                       new_x='LMARGIN', new_y='NEXT')
    pdf.ln(2)


def _dibujar_obra_social(pdf, valores):
    filas = [
        ['Tiene Obra Social / Prepaga', 'Sí' if valores.get('tiene_obra_social') else 'No'],
        ['Nombre de la Obra Social/Prepaga', valores.get('nombre_obra_social') or '-'],
        ['N° Socio', valores.get('numero_socio') or '-'],
    ]
    pdf.set_font('helvetica', '', TAM_TEXTO - 1)
    with pdf.table(filas, first_row_as_headings=False, text_align='LEFT', col_widths=(70, 30)):
        pass
    pdf.ln(2)


def _dibujar_docentes(pdf, campo, valores):
    pdf.set_font('helvetica', '', TAM_TEXTO)
    pdf.multi_cell(0, ALTO_LINEA, f"{campo['label']}:", align='L', new_x='LMARGIN', new_y='NEXT')
    filas = valores.get(campo['id']) or [{}]  # sin docentes, el original igual deja un renglón para completar
    for fila in filas:
        pdf.multi_cell(0, ALTO_LINEA, f"Apellido y Nombre: {fila.get('apellido_nombre', '')}    "
                              f"Cargo: {fila.get('cargo', '')}", align='L', new_x='LMARGIN', new_y='NEXT')
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
    filas = [[c['label'] for c in columnas]]
    if filas_datos:
        filas += [[_texto_valor(c, fila.get(c['id'])) for c in columnas] for fila in filas_datos]
    else:
        filas.append(['-'] * len(columnas))
    pdf.set_font('helvetica', '', TAM_TEXTO - 2)
    with pdf.table(filas, text_align='LEFT', col_widths=COL_WIDTHS.get(campo['id'])):
        pass
    pdf.ln(3)


# Anexos donde `notas_generales` (Salidas/AnexoN.json) se verificó contra el original: en
# el papel es el párrafo de cierre, después de las firmas ("El presente formulario puede
# ser completado de forma digital..."). No se imprime para el resto hasta revisarlos uno
# por uno — imprimirla sin verificar arriesgaría meter, en otro anexo, exactamente el tipo
# de texto-que-no-existe-en-el-papel que este mecanismo busca evitar.
NOTAS_GENERALES_A_IMPRIMIR = {'V'}


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
    pdf.ln(2)
    pdf.set_font('helvetica', 'B', TAM_TEXTO)
    for parte in schema['titulo'].split(' — '):
        # En mayúscula: así está el título en todos los anexos del original (verificado en
        # los 7) — el JSON lo guarda en caja de oración porque es más legible como dato.
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
    for campo in sorted(schema['campos'], key=lambda c: c['orden']):
        if (campo['id'] in procesados or campo['id'] in ids_resto_linea or campo['id'] in ids_narrativa_resto
                or not _condicion_cumple(campo, valores)):
            continue
        if campo.get('seccion') != seccion_actual:
            seccion_actual = campo.get('seccion')
            titulo = titulos_seccion.get(seccion_actual)
            if titulo:
                pdf.set_font('helvetica', 'B', TAM_TEXTO)
                pdf.ln(2)
                pdf.multi_cell(0, ALTO_LINEA, titulo, align='L', new_x='LMARGIN', new_y='NEXT')
                pdf.ln(1)

        if campo['id'] in narrativa_por_disparador:
            _dibujar_narrativa(pdf, narrativa_por_disparador[campo['id']], valores, campos_por_id)
        elif campo['id'] == 'tiene_obra_social':
            _dibujar_obra_social(pdf, valores)
            procesados.update(CAMPOS_OBRA_SOCIAL)
        elif campo['id'] in CAMPOS_DOCENTES:
            _dibujar_docentes(pdf, campo, valores)
        elif campo['id'] in CAMPOS_FIRMA_IX:
            _dibujar_firmas_ix(pdf, valores)
            procesados.update(CAMPOS_FIRMA_IX)
        elif campo['tipo'] == 'tabla':
            _dibujar_tabla(pdf, campo, valores)
        elif campo['tipo'] == 'nota':
            _dibujar_nota(pdf, campo)
        elif campo['tipo'] == 'textarea':
            _dibujar_textarea(pdf, campo, valores, anexo)
        elif campo['id'] in grupo_por_disparador:
            _dibujar_campo(pdf, campo, valores, anexo,
                           extra=[campos_por_id[i] for i in grupo_por_disparador[campo['id']]])
        else:
            _dibujar_campo(pdf, campo, valores, anexo)

    if anexo in NOTAS_GENERALES_A_IMPRIMIR and schema.get('notas_generales'):
        pdf.ln(2)
        pdf.set_font('helvetica', '', TAM_TEXTO - 2)
        pdf.multi_cell(0, ALTO_LINEA - 2, schema['notas_generales'], align='L', new_x='LMARGIN', new_y='NEXT')

    os.makedirs(os.path.dirname(destino), exist_ok=True)
    pdf.output(destino)


# Los 5 campos del bloque "Seguro escolar" del Anexo IX — los que pisa cada entrada de
# `_seguros_adicionales` para generar su propia copia (ver _generar_pdfs).
CAMPOS_SEGURO_IX = ('compania_aseguradora', 'tipo_seguro', 'numero_poliza', 'vigencia_poliza', 'observaciones')


def _limpiar_pdfs_ix_extra(id):
    carpeta = _carpeta_pdfs(id)
    if not os.path.isdir(carpeta):
        return
    for nombre in os.listdir(carpeta):
        if _RE_PDF_IX_EXTRA.match(nombre):
            os.remove(os.path.join(carpeta, nombre))


def _generar_pdfs(id, anexos):
    """Un PDF por anexo (III a IX), guardado en disco — nunca se descargan solos.

    El Anexo IX es especial: la escuela puede cargar más de un seguro escolar (distinto
    para estudiantes menores/mayores de edad, por ejemplo — ver `_seguros_adicionales` en
    formulario.html). El papel real sólo tiene lugar para una póliza por Declaración
    Jurada, así que cada seguro adicional genera su propia copia completa del Anexo IX
    (mismos datos de identificación, sólo cambia el bloque de seguro), no una fila más en
    una tabla. Se borran las copias extra viejas antes de regenerar, para que editar una
    salida y sacar un seguro no deje un PDF viejo huérfano dando vueltas.
    """
    for n in ANEXOS_NUMEROS:
        valores = anexos.get(n) or {}
        _generar_pdf_anexo(n, valores, _ruta_pdf(id, n))
        if n == 'IX':
            _limpiar_pdfs_ix_extra(id)
            for indice, seguro in enumerate(valores.get('_seguros_adicionales') or [], start=2):
                valores_extra = dict(valores, **{campo: seguro.get(campo, '') for campo in CAMPOS_SEGURO_IX})
                _generar_pdf_anexo('IX', valores_extra, _ruta_pdf_ix_extra(id, indice))


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
    normativa = _cargar_normativa()
    return render_template('salidas/formulario.html', activo='nueva', datos_precargar=None, id_editar=None, normativa=normativa)


@bp.route('/<int:id>/editar')
@accesos.requiere(PERMISO_ESCRITURA)
def editar(id):
    con = conectar()
    cur = con.cursor()
    fila = cur.execute("SELECT datos_json FROM salidas WHERE id = ?", (id,)).fetchone()
    con.close()
    if fila is None:
        abort(404)
    datos_precargar = json.loads(fila['datos_json'])
    normativa = _cargar_normativa()
    return render_template('salidas/formulario.html', activo='nueva', id_editar=id, datos_precargar=datos_precargar, normativa=normativa)


@bp.route('/api/guardar', methods=['POST'])
@accesos.requiere(PERMISO_ESCRITURA, como_json=True)
def api_guardar():
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return jsonify({'error': 'JSON inválido.'}), 400

    comunes = datos.get('datos_comunes') or {}
    anexos = datos.get('anexos') or {}
    id_editar = datos.get('_id_editar')

    con = conectar()
    cur = con.cursor()

    if id_editar:
        # Actualización de salida existente
        cur.execute("SELECT vigencia_hasta FROM salidas WHERE id = ?", (id_editar,))
        fila = cur.fetchone()
        if fila is None:
            con.close()
            return jsonify({'error': 'Salida no encontrada.'}), 404
        vigencia_hasta = fila['vigencia_hasta']
        cur.execute(
            "UPDATE salidas SET nombre_proyecto = ?, fecha_salida = ?, datos_json = ? WHERE id = ?",
            (comunes.get('denominacion_proyecto', '') or '', comunes.get('fecha_salida', '') or '',
             json.dumps(datos), id_editar))
        id = id_editar
    else:
        # Inserción de nueva salida
        creado = ahora()
        vigencia = creado + timedelta(days=VIGENCIA_DIAS)
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
    etiquetas = {n: n for n in disponibles}
    # Copias extra del Anexo IX, una por seguro escolar adicional (ver _generar_pdfs) —
    # se detectan por archivo en disco, no por releer datos_json, para mostrar siempre lo
    # que hay realmente generado.
    indice = 2
    while os.path.exists(_ruta_pdf_ix_extra(id, indice)):
        clave = f'IX_{indice}'
        disponibles.append(clave)
        titulos[clave] = titulos['IX']
        etiquetas[clave] = f'IX (seguro {indice})'
        indice += 1
    return render_template('salidas/detalle.html', fila=fila,
                           datos_comunes=json.loads(fila['datos_json']).get('datos_comunes') or {},
                           anexos=disponibles, titulos=titulos, etiquetas=etiquetas, activo='lista')


@bp.route('/<int:id>/regenerar', methods=['POST'])
@accesos.requiere(PERMISO_ESCRITURA)
def regenerar_pdfs(id):
    """Rehace los 7 PDF de una salida ya guardada, a partir del `datos_json` que quedó en
    la fila — no hay otra forma de traerlos al día: se generan una sola vez al guardar
    (`api_guardar`) y quedan cacheados en disco, así que un cambio en el renderer (esta
    función, `_generar_pdf_anexo`) no toca los PDF de las salidas guardadas antes."""
    con = conectar()
    cur = con.cursor()
    fila = cur.execute("SELECT datos_json FROM salidas WHERE id = ?", (id,)).fetchone()
    con.close()
    if fila is None:
        abort(404)
    anexos = json.loads(fila['datos_json']).get('anexos') or {}
    _generar_pdfs(id, anexos)
    return redirect(url_for('salidas.detalle', id=id))


_RE_ANEXO_IX_EXTRA = re.compile(r'^IX_(\d+)$')


@bp.route('/normativa')
def normativa():
    return render_template('salidas/normativa.html')


@bp.route('/<int:id>/pdf/<anexo>')
def ver_pdf(id, anexo):
    if anexo in ANEXOS_NUMEROS:
        ruta = _ruta_pdf(id, anexo)
    else:
        # 'IX_2', 'IX_3', ... — copias extra por seguro escolar adicional. Allowlist
        # explícita por regex, no simplemente "no está en ANEXOS_NUMEROS": `anexo` viene
        # de la URL y arma una ruta de archivo, no puede aceptar cualquier cosa.
        m = _RE_ANEXO_IX_EXTRA.match(anexo)
        if not m:
            abort(404)
        ruta = _ruta_pdf_ix_extra(id, int(m.group(1)))
    if not os.path.exists(ruta):
        abort(404)
    return send_file(ruta, mimetype='application/pdf', as_attachment=False,
                     download_name=f'Anexo{anexo}_salida{id}.pdf')
