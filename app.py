from flask import Flask, render_template, jsonify, send_file
import os
import sqlite3
from datetime import timedelta

# Carga .env en desarrollo local (DEEPSEEK_API_KEY, etc.). En Render las env vars se
# setean en el dashboard y este archivo ni existe, así que no falla si falta.
from dotenv import load_dotenv
load_dotenv()

import accesos
import database
import gestion
import historia
import agente
import sys

# El SPA de horarios es público: lo único que declara es quién puede regenerar la DB
# desde Google Sheets, que borra y reconstruye escuela.db.
PERMISOS = [
    ('horarios.actualizar', 'Regenerar los horarios desde Google Sheets', 'admin'),
]
GRUPO_PERMISOS = 'Horarios'
from config import SHEET_ID, GIDS_CURSOS, GID_HORARIOS_PRECEPTORES, GID_PERSONAL_NO_DOCENTE, FLOOR_MAPPING, ESCUELA_NOMBRE, ESCUELA_LOGO, ESCUELA_VERSION, DIAS, TURNO_CURSOS, TURNO_DEFAULT, ahora, PRODUCCION, SESION_DIAS
from fpdf import FPDF
import io
from database import obtener_filas

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

# Accesos y permisos (accesos.db) — junta el catálogo que declaró cada área, engancha los
# globals de Jinja y monta el canje de invitaciones + el panel /accesos. Esta lista es lo
# único que hay que tocar al sumar un área nueva, y está al lado del register_blueprint
# que ya hay que tocar igual.
accesos.init_db()
accesos.registrar_app(app, [gestion, historia, agente, sys.modules[__name__]])

# obtener_filas se importa desde database (ver database.py)

@app.route('/')
def index():
    con = database.conectar()
    cur = con.cursor()
    cur.execute("SELECT DISTINCT profesor FROM clases WHERE profesor != '' ORDER BY profesor")
    profes = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT DISTINCT aula FROM clases WHERE aula != '' ORDER BY aula")
    aulas = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT DISTINCT curso, division FROM clases WHERE curso != '' ORDER BY curso, division")
    cursos = [f"{r[0]}° {r[1]}" for r in cur.fetchall()]
    
    preceptores_horario = database.obtener_lista_preceptores_horario()
    personal = database.obtener_lista_personal()

    con.close()
    return render_template('index.html',
        datos={'profesor': profes, 'aula': aulas, 'curso': cursos, 'horario_preceptor': preceptores_horario, 'personal': personal},
        floor_mapping=FLOOR_MAPPING,
        dias=DIAS,
        escuela_nombre=ESCUELA_NOMBRE,
        escuela_logo=ESCUELA_LOGO,
        escuela_version=ESCUELA_VERSION,
    )

@app.route('/api/<tipo>/<valor>')
def api(tipo, valor):
    # Remove the degree symbol from the search value if searching by course
    search_valor = valor
    if tipo == 'curso' and '°' in valor:
        search_valor = valor.replace('°', '')
    return jsonify(obtener_filas(tipo, search_valor))

def time_to_min(t):
    if not t or not isinstance(t, str) or ':' not in t:
        return 0
    try:
        h, m = map(int, t.split(':'))
        return h * 60 + m
    except:
        return 0

def obtener_datos_calendario(filas, tipo, columnas=None):
    if not filas:
        return None
    
    if columnas is None:
        columnas = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
    
    tiempos = set()
    for f in filas:
        if f['hora_inicio']: tiempos.add(f['hora_inicio'])
        if f['hora_fin']: tiempos.add(f['hora_fin'])
    
    if not tiempos:
        return None
        
    horarios_ordenados = sorted(list(tiempos), key=time_to_min)
    min_mins = time_to_min(horarios_ordenados[0]) - 30
    max_mins = time_to_min(horarios_ordenados[-1]) + 30
    hora_min = max(0, min_mins)
    hora_max = min(1440, max_mins)
    
    calendario = {
        'columnas': columnas,
        'horarios': horarios_ordenados,
        'hora_min': hora_min,
        'hora_max': hora_max,
        'bloques_por_columna': {}
    }

    for col in columnas:
        if tipo == 'planilla':
            clases_col = sorted([f for f in filas if str(f['aula']) == col], key=lambda x: time_to_min(x['hora_inicio']))
        else:
            clases_col = sorted([f for f in filas if f['dia'] == col], key=lambda x: time_to_min(x['hora_inicio']))
            
        bloques = []
        procesados = set()
        
        for i in range(len(clases_col)):
            if i in procesados: continue
            cluster = [clases_col[i]]; cluster_idx = [i]
            max_fin = time_to_min(clases_col[i]['hora_fin'])
            for j in range(i + 1, len(clases_col)):
                if time_to_min(clases_col[j]['hora_inicio']) < max_fin:
                    cluster.append(clases_col[j]); cluster_idx.append(j)
                    max_fin = max(max_fin, time_to_min(clases_col[j]['hora_fin']))
                else: break

            todos_tienen_grupo = all(c['grupo'] and str(c['grupo']).strip() != "" for c in cluster)
            hay_superposicion = len(cluster) > 1 and (tipo not in ['curso', 'planilla'] or not todos_tienen_grupo)

            if hay_superposicion:
                # Logic for superposition: only divide side-by-side if ALL classes allow it (superposicion == 1)
                todos_permiten = all(c['superposicion'] == 1 for c in cluster)
                if todos_permiten:
                    for idx, clase in enumerate(cluster):
                        bloques.append({'tipo': 'materia', 'ancho': 100/len(cluster), 'left': (100/len(cluster))*idx, 'clase': clase})
                else:
                    bloques.append({'tipo': 'superposicion', 'cantidad': len(cluster), 'clases': cluster})
            else:
                for idx, clase in enumerate(cluster):
                    ancho = 100/len(cluster); left = ancho*idx
                    if len(cluster) == 1:
                        grupo = str(clase['grupo']).strip().upper() if clase['grupo'] else ""
                        if grupo == 'A': ancho = 50; left = 0
                        elif grupo == 'B': ancho = 50; left = 50
                    bloques.append({'tipo': 'materia', 'ancho': ancho, 'left': left, 'clase': clase})
            for idx in cluster_idx: procesados.add(idx)
        calendario['bloques_por_columna'][col] = bloques
    return calendario

class PDF(FPDF):
    def header(self):
        pass

    def footer(self):
        pass

def _crear_pdf_horario():
    pdf = PDF(orientation='L', unit='mm', format='A4')
    # El grid llega hasta y=199, pasando el trigger del auto page break (190):
    # sin esto fpdf insertaría páginas en blanco al dibujar los bloques de abajo
    pdf.set_auto_page_break(False)
    pdf.add_font('RobotoMono', '', 'static/fonts/RobotoMono-Regular.ttf')
    pdf.add_font('RobotoMono', 'B', 'static/fonts/RobotoMono-Bold.ttf')
    pdf.add_font('RobotoMono', 'I', 'static/fonts/RobotoMono-Italic.ttf')
    return pdf

def dibujar_pagina_horario(pdf, tipo, valor):
    search_valor = valor
    columnas = None
    if tipo == 'curso' and '°' in valor:
        search_valor = valor.replace('°', '')
        
    filas = obtener_filas(tipo, search_valor)

    if tipo == 'planilla':
        if '|' in valor:
            _, piso = valor.split('|')
            columnas = FLOOR_MAPPING.get(piso, [])

    cal = obtener_datos_calendario(filas, tipo, columnas)

    pdf.add_page()
    
    # Fecha arriba a la izquierda
    pdf.set_font('RobotoMono', '', 8)
    pdf.set_text_color(120, 120, 120)
    pdf.set_xy(15, 5)
    pdf.cell(0, 5, ahora().strftime("%d/%m/%Y"), 0, 0, 'L')

    # Nuevo Título simple y centrado
    pdf.set_font('RobotoMono', 'B', 16)
    pdf.set_text_color(0, 0, 0)

    titulo = f"Horario Semanal de {tipo.capitalize()}: {valor}"
    if tipo == 'planilla':
        dia, piso = valor.split('|')
        titulo = f"Planilla General: {piso} - {dia}"

    # La celda de la fecha (w=0, ln=0) deja el cursor en el margen derecho;
    # volver al margen izquierdo para que el título se centre en la página
    pdf.set_x(pdf.l_margin)
    pdf.cell(0, 10, titulo, 0, 1, 'C')

    if tipo == 'curso':
        try:
            partes = valor.replace('°', '').strip().split(' ')
            curso = partes[0]
            division = partes[1] if len(partes) > 1 else ""
            data = database.obtener_preceptores_por_curso(curso, division)
            if data:
                slots = [
                    ("T.M:", data["preceptores_manana"]),
                    ("T.T:", data["preceptores_tarde"]),
                    ("T.V:", data["preceptores_vespertino"]),
                ]

                ancho_util = 267
                col_w = ancho_util / 3
                pdf.set_text_color(30, 50, 100)

                for idx, (label_turno, nombre) in enumerate(slots):
                    txt = f"Preceptor {label_turno} {nombre}" if nombre else ""
                    pdf.set_font('RobotoMono', 'B', 9)
                    align = 'L' if idx == 0 else ('C' if idx == 1 else 'R')
                    pdf.cell(col_w, 8, txt, 0, 0 if idx < 2 else 1, align)
        except Exception as e:
            print(f"Error PDF preceptor: {e}")

    pdf.ln(2)

    if cal:
        # Configuración del Grid: arranca donde terminó el encabezado y
        # se extiende hasta y=199 (borde inferior con ~11mm de margen)
        margin_left = 15; margin_top = pdf.get_y(); width = 267
        height = 199 - (margin_top + 6)
        col_hour_w = 15; col_day_w = (width - col_hour_w) / len(cal['columnas'])
        
        # Dibujar Cabecera Días / Aulas
        pdf.set_fill_color(240, 240, 240); pdf.set_font('RobotoMono', 'B', 10)
        pdf.set_xy(margin_left + col_hour_w, margin_top)
        for col_name in cal['columnas']:
            display_name = col_name if tipo != 'planilla' else f"A {col_name}"
            if tipo == 'planilla' and len(cal['columnas']) > 6:
                pdf.set_font('RobotoMono', 'B', 8)
            pdf.cell(col_day_w, 6, display_name, 1, 0, 'C', True)
        
        # Dibujar Horas y Grid
        pdf.set_font('RobotoMono', '', 10); pdf.set_text_color(100, 100, 100)
        duracion = cal['hora_max'] - cal['hora_min']
        
        # Pre-calcular posiciones de texto para evitar solapamientos
        text_positions = []
        for hora_str in cal['horarios']:
            m = time_to_min(hora_str)
            y_rel = ((m - cal['hora_min']) / duracion) * height
            y_line = margin_top + 6 + y_rel
            text_positions.append({'txt': hora_str, 'line_y': y_line, 'text_y': y_line - 2})
            
        # Ajustar si hay colisiones (nudge up/down)
        for _ in range(2): 
            for i in range(len(text_positions) - 1):
                diff = text_positions[i+1]['text_y'] - text_positions[i]['text_y']
                if diff < 3.5:
                    nudge = (3.5 - diff) / 2
                    text_positions[i]['text_y'] -= nudge
                    text_positions[i+1]['text_y'] += nudge

        for tp in text_positions:
            pdf.set_draw_color(220, 220, 220)
            pdf.line(margin_left + col_hour_w, tp['line_y'], margin_left + width, tp['line_y'])
            pdf.set_xy(margin_left, tp['text_y'])
            pdf.cell(col_hour_w - 2, 4, tp['txt'], 0, 0, 'R')

        # Dibujar Bloques
        pdf.set_draw_color(0, 0, 0)
        for d_idx, col_name in enumerate(cal['columnas']):
            for b in cal['bloques_por_columna'][col_name]:
                if b['tipo'] == 'materia':
                    clase = b['clase']
                    y_ini = ((time_to_min(clase['hora_inicio']) - cal['hora_min']) / duracion) * height
                    y_fin = ((time_to_min(clase['hora_fin']) - cal['hora_min']) / duracion) * height
                    
                    x = margin_left + col_hour_w + (d_idx * col_day_w) + (b['left'] * col_day_w / 100) + 0.5
                    y = margin_top + 6 + y_ini + 0.5
                    w = (b['ancho'] * col_day_w / 100) - 1
                    h = (y_fin - y_ini) - 1
                    
                    # Bloque principal
                    pdf.set_fill_color(255, 255, 255)
                    pdf.rect(x, y, w, h, 'FD')
                    
                    # Indicador inferior (Aula)
                    ind_h = 7
                    if h < 15: ind_h = h * 0.4
                    
                    pdf.set_fill_color(245, 245, 245)
                    pdf.rect(x, y + h - ind_h, w, ind_h, 'FD')
                    
                    # Formatear curso y división
                    curso_num = str(clase['curso'])
                    division = str(clase['division'])
                    try:
                        is_high_course = int(curso_num) >= 4
                    except:
                        is_high_course = False
                    
                    div_display = f"{division}°" if is_high_course else division
                    
                    ind_txt = str(clase['aula'] or '?')
                    if tipo == 'aula' or tipo == 'planilla': ind_txt = f"{curso_num}° {div_display}"
                    
                    pdf.set_text_color(0, 0, 0)
                    pdf.set_font('RobotoMono', 'B', 9)
                    pdf.set_xy(x, y + h - ind_h)
                    pdf.cell(w, ind_h, ind_txt, 0, 0, 'C')
                    
                    # Contenido Materia Centrado
                    txt_x = x + 0.3
                    materia_w = w - 0.6
                    materia_h_avail = h - ind_h
                    
                    if materia_w > 2:
                        is_licencia = tipo == 'profesor' and clase.get('suplente_activo') == 1
                        is_narrow = materia_w < 20
                        
                        if is_narrow:
                            font_size_mat = 7.2
                            font_size_det = 5.8
                            line_h = 2.7
                            is_short = materia_h_avail < 15
                            is_tiny = materia_h_avail < 10

                            if is_tiny:
                                font_size_mat = 6.0; font_size_det = 5.0; line_h = 2.2

                            pdf.set_font('RobotoMono', 'B', font_size_mat)
                            materia_txt = "LICENCIADA" if is_licencia else clase['materia']
                            lines_mat_full = pdf.multi_cell(materia_w, line_h, materia_txt, split_only=True)
                            
                            max_lines_mat_allowed = 1 if is_short else 3
                            if len(lines_mat_full) > max_lines_mat_allowed:
                                materia_display = ""
                                for k in range(max_lines_mat_allowed - 1):
                                    materia_display += lines_mat_full[k].strip() + "\n"
                                last_l = lines_mat_full[max_lines_mat_allowed - 1].strip()
                                while pdf.get_string_width(last_l) > materia_w - 1.0 and len(last_l) > 5:
                                    last_l = last_l[:-1]
                                materia_display += last_l
                                actual_lines_mat = max_lines_mat_allowed
                            else:
                                materia_display = materia_txt
                                actual_lines_mat = len(lines_mat_full)
                            
                            pdf.set_font('RobotoMono', '', font_size_det)
                            # Mostrar suplente si esta activo
                            prof_display = clase['profesor']
                            if clase.get('suplente_activo') == 1:
                                prof_display = clase['prof_suplente']
                            det_raw = f"{prof_display}" if tipo != 'profesor' else f"Curso: {curso_num}° {div_display}"
                            lines_det = pdf.multi_cell(materia_w, line_h, det_raw, split_only=True)
                            
                            show_det = (actual_lines_mat + 1) * line_h <= materia_h_avail - 0.3 and not is_licencia
                            show_time = show_det and (actual_lines_mat + len(lines_det) + 1) * line_h <= materia_h_avail - 0.3
                            
                            total_h = actual_lines_mat * line_h
                            if show_det: total_h += min(len(lines_det), 2) * line_h
                            if show_time: total_h += line_h
                            
                            y_start = max(y + 0.2, y + (materia_h_avail - total_h) / 2)
                            pdf.set_xy(txt_x, y_start)
                            pdf.set_font('RobotoMono', 'B', font_size_mat)
                            if is_licencia: pdf.set_text_color(220, 38, 38)
                            pdf.multi_cell(materia_w, line_h, materia_display, 0, 'C')
                            pdf.set_text_color(0, 0, 0)
                            
                            if show_det:
                                pdf.set_font('RobotoMono', 'I', font_size_det)
                                space_for_prof = materia_h_avail - (actual_lines_mat * line_h) - 0.5
                                if show_time: space_for_prof -= line_h
                                max_lines_prof = int(space_for_prof / line_h)
                                if max_lines_prof > 0:
                                    display_det = det_raw
                                    if len(lines_det) > max_lines_prof:
                                        d_lines = [lines_det[k].strip() for k in range(max_lines_prof - 1)]
                                        last_dl = lines_det[max_lines_prof-1].strip()
                                        while pdf.get_string_width(last_dl) > materia_w - 0.8 and len(last_dl) > 5:
                                            last_dl = last_dl[:-1]
                                        d_lines.append(last_dl)
                                        display_det = "\n".join(d_lines)
                                    pdf.set_x(txt_x)
                                    pdf.multi_cell(materia_w, line_h, display_det, 0, 'C')
                            
                            if show_time:
                                pdf.set_font('RobotoMono', '', font_size_det)
                                if pdf.get_y() - y + line_h <= materia_h_avail:
                                    pdf.set_x(txt_x)
                                    pdf.cell(materia_w, line_h, f"{clase['hora_inicio']} - {clase['hora_fin']}", 0, 1, 'C')
                        else:
                            is_short = materia_h_avail < 20; is_tiny = materia_h_avail < 12
                            font_size_mat = 9.5; font_size_det = 8.0; line_h = 3.8
                            if is_short: font_size_mat = 8.0; font_size_det = 7.0; line_h = 3.0
                            if is_tiny: font_size_mat = 7.0; font_size_det = 6.0; line_h = 2.5
                            
                            pdf.set_font('RobotoMono', 'B', font_size_mat)
                            materia_txt = "LICENCIADA" if is_licencia else clase['materia']
                            lines_mat_full = pdf.multi_cell(materia_w, line_h, materia_txt, split_only=True)
                            max_lines_mat_allowed = 1 if is_short else 4
                            
                            if len(lines_mat_full) > max_lines_mat_allowed:
                                materia_display = ""
                                for k in range(max_lines_mat_allowed - 1):
                                    materia_display += lines_mat_full[k].strip() + "\n"
                                last_l = lines_mat_full[max_lines_mat_allowed - 1].strip()
                                while pdf.get_string_width(last_l) > materia_w - 1.2 and len(last_l) > 5:
                                    last_l = last_l[:-1]
                                materia_display += last_l
                                actual_lines_mat = max_lines_mat_allowed
                            else:
                                materia_display = materia_txt
                                actual_lines_mat = len(lines_mat_full)
                            
                            pdf.set_font('RobotoMono', '', font_size_det)
                            # Mostrar suplente si esta activo
                            prof_display = clase['profesor']
                            if clase.get('suplente_activo') == 1:
                                prof_display = clase['prof_suplente']
                            det_raw = f"{prof_display}" if tipo != 'profesor' else f"Curso: {curso_num}° {div_display}"
                            lines_det = pdf.multi_cell(materia_w, line_h, det_raw, split_only=True)
                            show_det = (actual_lines_mat + 1) * line_h <= materia_h_avail - 0.8 and not is_licencia
                            show_time = show_det and (actual_lines_mat + len(lines_det) + 1) * line_h <= materia_h_avail - 0.8
                            
                            final_lines = actual_lines_mat
                            if show_det: final_lines += min(len(lines_det), 2)
                            if show_time: final_lines += 1
                            
                            y_start = max(y + 0.4, y + (materia_h_avail - (final_lines * line_h)) / 2)
                            pdf.set_xy(txt_x, y_start)
                            pdf.set_font('RobotoMono', 'B', font_size_mat)
                            if is_licencia: pdf.set_text_color(220, 38, 38)
                            pdf.multi_cell(materia_w, line_h, materia_display, 0, 'C')
                            pdf.set_text_color(0, 0, 0)
                            
                            if show_det:
                                pdf.set_font('RobotoMono', 'I', font_size_det)
                                space_for_prof = materia_h_avail - (actual_lines_mat * line_h) - 0.8
                                max_lines_prof = max(1, int(space_for_prof / line_h))
                                display_det = det_raw
                                if len(lines_det) > max_lines_prof:
                                    d_lines = [lines_det[k].strip() for k in range(max_lines_prof-1)]
                                    last_dl = lines_det[max_lines_prof-1].strip()
                                    while pdf.get_string_width(last_dl) > materia_w - 1.2 and len(last_dl) > 5:
                                        last_dl = last_dl[:-1]
                                    d_lines.append(last_dl)
                                    display_det = "\n".join(d_lines)
                                pdf.set_x(txt_x); pdf.multi_cell(materia_w, line_h, display_det, 0, 'C')

                            if show_time:
                                pdf.set_font('RobotoMono', '', font_size_det)
                                if pdf.get_y() - y + line_h <= materia_h_avail:
                                    pdf.set_x(txt_x)
                                    pdf.cell(materia_w, line_h, f"{clase['hora_inicio']} - {clase['hora_fin']}", 0, 1, 'C')
                elif b['tipo'] == 'superposicion':
                    y_ini = ((time_to_min(b['clases'][0]['hora_inicio']) - cal['hora_min']) / duracion) * height
                    latest = max(b['clases'], key=lambda x: time_to_min(x['hora_fin']))
                    y_fin = ((time_to_min(latest['hora_fin']) - cal['hora_min']) / duracion) * height
                    x = margin_left + col_hour_w + (d_idx * col_day_w) + 1
                    y = margin_top + 6 + y_ini + 1
                    w = col_day_w - 2; h = (y_fin - y_ini) - 2
                    pdf.set_fill_color(220, 220, 220); pdf.rect(x, y, w, h, 'FD')
                    pdf.set_text_color(0, 0, 0); pdf.set_font('RobotoMono', 'B', 8)
                    pdf.set_xy(x, y + (h/2) - 2)
                    pdf.cell(w, 4, f"SUPERPOSICION", 0, 0, 'C')

@app.route('/export/pdf/<tipo>/<valor>')
def export_pdf(tipo, valor):
    pdf = _crear_pdf_horario()
    dibujar_pagina_horario(pdf, tipo, valor)

    output = io.BytesIO()
    output.write(pdf.output())
    output.seek(0)
    filename = f"{tipo}_{valor}.pdf".replace('|', '_')
    return send_file(output, mimetype='application/pdf', as_attachment=False, download_name=filename)

@app.route('/export/pdf/cursos/<seleccion>')
def export_pdf_cursos(seleccion):
    if seleccion == 'todos':
        con = database.conectar()
        cur = con.cursor()
        cur.execute("SELECT DISTINCT curso, division FROM clases WHERE curso != '' ORDER BY curso, division")
        cursos = [f"{r[0]}° {r[1]}" for r in cur.fetchall()]
        con.close()
    else:
        cursos = [c.strip() for c in seleccion.split(',') if c.strip()]

    if not cursos:
        return "Sin cursos seleccionados", 400

    pdf = _crear_pdf_horario()
    for valor in cursos:
        dibujar_pagina_horario(pdf, 'curso', valor)

    output = io.BytesIO()
    output.write(pdf.output())
    output.seek(0)
    return send_file(output, mimetype='application/pdf', as_attachment=False, download_name="horarios_cursos.pdf")

@app.route('/api/preceptor/<valor>')
def api_preceptor(valor):
    try:
        partes = valor.strip().split(' ', 1)
        curso = partes[0]
        division = partes[1].strip() if len(partes) > 1 else ""
        data = database.obtener_preceptores_por_curso(curso, division)
        if data:
            data['turno'] = TURNO_CURSOS.get((str(curso), str(division)), TURNO_DEFAULT)
        return jsonify(data)
    except Exception as e:
        print(f"Error preceptor: {e}")
        return jsonify(None)

@app.route('/api/actualizar', methods=['POST'])
@accesos.requiere('horarios.actualizar', como_json=True)
def api_actualizar():
    """Borra y reconstruye escuela.db desde Google Sheets.

    Era GET y sin permiso: cualquier crawler, prefetch o alumno que leyera el HTML podía
    dispararla, y si Sheets no responde la escuela se queda sin horarios en plena jornada.
    POST + permiso de admin + botón oculto alcanza para el nivel de riesgo de una escuela.
    """
    try:
        database.crear_tablas()
        database.cargar_desde_sheets(SHEET_ID, GIDS_CURSOS)
        database.cargar_horarios_preceptores(SHEET_ID, GID_HORARIOS_PRECEPTORES)
        database.cargar_personal_no_docente(SHEET_ID, GID_PERSONAL_NO_DOCENTE)
        return jsonify({"status": "success", "message": "Datos actualizados correctamente"})
    except Exception as e:
        print(f"Error actualizando datos: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/dashboard')
def api_dashboard():
    try:
        con = database.conectar()
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute("SELECT * FROM clases")
        filas = [dict(row) for row in cur.fetchall()]
        con.close()
        return jsonify(filas)
    except Exception as e:
        print(f"Error en dashboard: {e}")
        return jsonify([])

@app.route('/api/personal/<nombre>')
def api_personal(nombre):
    return jsonify(database.obtener_personal_por_nombre(nombre))

@app.route('/api/personal_todos')
def api_personal_todos():
    return jsonify(database.obtener_personal_todos())

@app.route('/api/horario_preceptor/<nombre>')
def api_horario_preceptor(nombre):
    """
    Endpoint para obtener el horario individual de un preceptor.
    """
    return jsonify(database.obtener_horario_preceptor(nombre))

def _planilla_preceptores_con_turnos():
    filas = database.obtener_planilla_preceptores_todos()
    for f in filas:
        f['turno'] = TURNO_CURSOS.get((str(f['curso']), str(f['division'])), TURNO_DEFAULT)
    return filas

@app.route('/api/planilla_preceptores')
def api_planilla_preceptores():
    return jsonify(_planilla_preceptores_con_turnos())

@app.route('/api/preceptores_data')
def api_preceptores_data():
    # Todo lo de preceptores en una sola respuesta para cachear en el cliente:
    # - horarios: {nombre: horario individual} (reusa la lógica LIKE + estado/turno)
    # - planilla: lista por curso con turnos (sirve también para el preceptor-por-curso)
    nombres = database.obtener_lista_preceptores_horario()
    horarios = {n: database.obtener_horario_preceptor(n) for n in nombres}
    return jsonify({
        'horarios': horarios,
        'planilla': _planilla_preceptores_con_turnos(),
    })

@app.route('/export/pdf/planilla_preceptores')
def export_pdf_planilla_preceptores():
    filas = _planilla_preceptores_con_turnos()

    pdf = PDF(orientation='P', unit='mm', format='LETTER')
    pdf.add_font('RobotoMono', '', 'static/fonts/RobotoMono-Regular.ttf')
    pdf.add_font('RobotoMono', 'B', 'static/fonts/RobotoMono-Bold.ttf')
    pdf.add_page()

    margin = 5
    pdf.set_font('RobotoMono', '', 8)
    pdf.set_text_color(120, 120, 120)
    pdf.set_xy(margin, 3)
    pdf.cell(0, 5, ahora().strftime("%d/%m/%Y"), 0, 0, 'L')

    pdf.set_font('RobotoMono', 'B', 15)
    pdf.set_text_color(0, 0, 0)
    pdf.set_xy(margin, 8)
    pdf.cell(0, 9, 'Planilla de Preceptores', 0, 1, 'C')
    pdf.ln(2)

    abrev = {'MAÑANA': 'M', 'TARDE': 'T', 'VESPERTINO': 'V'}
    # ancho útil carta portrait: 215.9 - 2*5 = 205.9mm
    col_w = [32, 13, 53, 53, 54]
    headers = ['CURSO', 'TURNO', 'MAÑANA', 'TARDE', 'VESPERTINO']
    header_h = 7
    # title area ≈ 3+5+8+9+2 = 27mm; header = 7mm → datos desde y≈34
    # llenar hasta 279.4-5 = 274.4 → alto disponible = 274.4 - 34 = 240.4mm
    row_h = (279.4 - margin - 34) / len(filas) if filas else 5.0
    font_size = max(6, min(9, int(row_h * 2.0)))

    pdf.set_font('RobotoMono', 'B', font_size + 1)
    pdf.set_fill_color(220, 230, 245)
    pdf.set_text_color(26, 54, 93)
    pdf.set_x(margin)
    for i, h in enumerate(headers):
        pdf.cell(col_w[i], header_h, h, 1, 0, 'C', True)
    pdf.ln()

    for idx, f in enumerate(filas):
        turno_raw = (f.get('turno') or '').upper()
        turno_abrev = abrev.get(turno_raw, turno_raw)
        row_fill = idx % 2 == 0
        row = [
            f"{f['curso']}° {f['division']}",
            turno_abrev,
            f.get('manana') or '',
            f.get('tarde') or '',
            f.get('vespertino') or '',
        ]
        pdf.set_x(margin)
        for i, val in enumerate(row):
            is_active = (i == 2 and turno_raw == 'MAÑANA') or \
                        (i == 3 and turno_raw == 'TARDE') or \
                        (i == 4 and turno_raw == 'VESPERTINO')
            if is_active:
                pdf.set_fill_color(245, 248, 252) if row_fill else pdf.set_fill_color(255, 255, 255)
                pdf.set_text_color(26, 54, 93)
                pdf.set_font('RobotoMono', 'B', font_size + 1)
            else:
                pdf.set_fill_color(245, 248, 252) if row_fill else pdf.set_fill_color(255, 255, 255)
                pdf.set_text_color(100, 100, 100)
                pdf.set_font('RobotoMono', '', font_size)
            pdf.cell(col_w[i], row_h, val, 1, 0, 'C', row_fill)
        pdf.ln()

    output = io.BytesIO()
    output.write(pdf.output())
    output.seek(0)
    return send_file(output, mimetype='application/pdf', as_attachment=False, download_name='planilla_preceptores.pdf')

if __name__ == '__main__':
    # El arranque corre SOLO en el proceso padre. Con el reloader activo, Werkzeug levanta un
    # hijo (marcado con WERKZEUG_RUN_MAIN) que es el que sirve, y lo relanza entero cada vez
    # que se guarda un .py — o sea que este bloque se ejecutaría de nuevo en cada guardado.
    # `init_tablas` es idempotente y aguanta, pero revisar la base y eventualmente bajarla de
    # Google Sheets en cada Ctrl+S no tiene sentido. Sin reloader la variable no existe y el
    # bloque corre igual, así que la guarda no cambia nada en producción.
    if not os.environ.get('WERKZEUG_RUN_MAIN'):
        database.init_tablas()
        if not database.tiene_datos():
            print("Base vacía, cargando datos desde Google Sheets...")
            database.crear_tablas()
            database.cargar_desde_sheets(SHEET_ID, GIDS_CURSOS)
            database.cargar_horarios_preceptores(SHEET_ID, GID_HORARIOS_PRECEPTORES)
            database.cargar_personal_no_docente(SHEET_ID, GID_PERSONAL_NO_DOCENTE)

    # use_reloader activo: al guardar un .py el server se recarga solo. Estuvo apagado un
    # tiempo y el costo fue real — se editaba el agente, el proceso viejo seguía sirviendo
    # el código anterior y parecía que el cambio no funcionaba. En Windows el problema se
    # disimula todavía más: Werkzeug abre el socket con SO_REUSEADDR, así que un segundo
    # `python app.py` arranca SIN error aunque el 5000 ya esté tomado, no recibe tráfico, y
    # quedan dos servers de los que contesta el más viejo.
    app.run(host='0.0.0.0', port=5000, debug=True)
