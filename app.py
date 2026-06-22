from flask import Flask, render_template, jsonify, send_file
import database
from config import SHEET_ID, GIDS_CURSOS, GID_PRECEPTORES, GID_HORARIOS_PRECEPTORES
import sqlite3
from fpdf import FPDF
import io

app = Flask(__name__)

FLOOR_MAPPING = {
    "Piso 1": ["11", "12", "13", "14", "15", "16"],
    "Piso 2": ["21", "22", "23", "24", "25", "26"],
    "Piso 3": ["13", "14", "15", "16", "17", "18"],
    "Entrepiso 1": ["101","102", "103", "104", "105", "106", "107", "108"],
    "Entrepiso 2": ["301", "302", "303", "304", "305", "306"]
}

def obtener_filas(tipo, valor):
    try:
        con = database.conectar()
        cur = con.cursor()
        if tipo == 'profesor':
            cur.execute("SELECT * FROM clases WHERE profesor = ?", (valor,))
        elif tipo == 'aula':
            cur.execute("SELECT * FROM clases WHERE aula = ?", (valor,))
        elif tipo == 'curso':
            partes = valor.split(' ')
            if len(partes) >= 2:
                cur.execute("SELECT * FROM clases WHERE curso = ? AND division = ?", (partes[0], partes[1]))
            else:
                cur.execute("SELECT * FROM clases WHERE curso = ?", (partes[0],))
        elif tipo == 'planilla':
            if '|' in valor:
                dia, piso = valor.split('|')
                aulas = FLOOR_MAPPING.get(piso, [])
                if aulas:
                    placeholders = ','.join(['?'] * len(aulas))
                    query = f"SELECT * FROM clases WHERE dia = ? AND aula IN ({placeholders})"
                    cur.execute(query, [dia] + aulas)
            else:
                return []
        
        filas = [list(row) for row in cur.fetchall()]
        con.close()
        return filas
    except Exception as e:
        print(f"Error en busqueda: {e}")
        return []

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
    
    con.close()
    return render_template('index.html', datos={'profesor': profes, 'aula': aulas, 'curso': cursos, 'horario_preceptor': preceptores_horario}, floor_mapping=FLOOR_MAPPING)

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
        if f[12]: tiempos.add(f[12])
        if f[13]: tiempos.add(f[13])
    
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
            clases_col = sorted([f for f in filas if str(f[9]) == col], key=lambda x: time_to_min(x[12]))
        else:
            clases_col = sorted([f for f in filas if f[11] == col], key=lambda x: time_to_min(x[12]))
            
        bloques = []
        procesados = set()
        
        for i in range(len(clases_col)):
            if i in procesados: continue
            cluster = [clases_col[i]]; cluster_idx = [i]
            max_fin = time_to_min(clases_col[i][13])
            for j in range(i + 1, len(clases_col)):
                if time_to_min(clases_col[j][12]) < max_fin:
                    cluster.append(clases_col[j]); cluster_idx.append(j)
                    max_fin = max(max_fin, time_to_min(clases_col[j][13]))
                else: break
            
            todos_tienen_grupo = all(c[14] and str(c[14]).strip() != "" for c in cluster)
            hay_superposicion = len(cluster) > 1 and (tipo not in ['curso', 'planilla'] or not todos_tienen_grupo)

            if hay_superposicion:
                # Logic for superposition: only divide side-by-side if ALL classes allow it (F[15] == 1)
                todos_permiten = all(c[15] == 1 for c in cluster)
                if todos_permiten:
                    for idx, clase in enumerate(cluster):
                        bloques.append({'tipo': 'materia', 'ancho': 100/len(cluster), 'left': (100/len(cluster))*idx, 'clase': clase})
                else:
                    bloques.append({'tipo': 'superposicion', 'cantidad': len(cluster), 'clases': cluster})
            else:
                for idx, clase in enumerate(cluster):
                    ancho = 100/len(cluster); left = ancho*idx
                    if len(cluster) == 1:
                        grupo = str(clase[14]).strip().upper() if clase[14] else ""
                        if grupo == 'A': ancho = 50; left = 0
                        elif grupo == 'B': ancho = 50; left = 50
                    bloques.append({'tipo': 'materia', 'ancho': ancho, 'left': left, 'clase': clase})
            for idx in cluster_idx: procesados.add(idx)
        calendario['bloques_por_columna'][col] = bloques
    return calendario

class PDF(FPDF):
    def header(self):
        # Header removed as per user request
        pass

    def footer(self):
        self.set_y(-15)
        self.add_font('RobotoMono', 'I', 'static/fonts/RobotoMono-Italic.ttf')
        self.set_font('RobotoMono', 'I', 8)
        self.cell(0, 10, 'by Calei', 0, 0, 'L')

@app.route('/export/pdf/<tipo>/<valor>')
def export_pdf(tipo, valor):
    import time
    start_time = time.time()
    
    # Limpiar el valor si es curso para la búsqueda en BD
    search_valor = valor
    columnas = None
    if tipo == 'curso' and '°' in valor:
        search_valor = valor.replace('°', '')
        
    if tipo == 'planilla':
        if '|' in valor:
            _, piso = valor.split('|')
            columnas = FLOOR_MAPPING.get(piso, [])

    filas = obtener_filas(tipo, search_valor)
    cal = obtener_datos_calendario(filas, tipo, columnas)
    
    pdf = PDF(orientation='L', unit='mm', format='A4')
    pdf.add_font('RobotoMono', '', 'static/fonts/RobotoMono-Regular.ttf')
    pdf.add_font('RobotoMono', 'B', 'static/fonts/RobotoMono-Bold.ttf')
    pdf.add_font('RobotoMono', 'I', 'static/fonts/RobotoMono-Italic.ttf')
    pdf.add_page()
    
    # Nuevo Título simple y centrado
    pdf.set_font('RobotoMono', 'B', 16)
    pdf.set_text_color(0, 0, 0)
    
    titulo = f"Horario Semanal de {tipo.capitalize()}: {valor}"
    if tipo == 'planilla':
        dia, piso = valor.split('|')
        titulo = f"Planilla General: {piso} - {dia}"

    pdf.cell(0, 10, titulo, 0, 1, 'C')

    if tipo == 'curso':
        try:
            con = database.conectar()
            cur = con.cursor()
            search_valor_p = valor.replace('°', '')
            partes = search_valor_p.split(' ')
            curso = partes[0]
            division = partes[1] if len(partes) > 1 else ""
            cur.execute("SELECT * FROM preceptores WHERE curso = ? AND division = ?", (curso, division))
            row = cur.fetchone()
            con.close()
            if row:
                turno_curso = str(row[2] or "").strip().upper()
                labels = {3: "T.M:", 4: "T.T:", 5: "T.N:"}
                mapping = {"T.M": 3, "T.T": 4, "T.N": 5, "T.V": 5}
                
                key_principal = -1
                for k, v in mapping.items():
                    if turno_curso.startswith(k):
                        key_principal = v
                        break
                
                # Ancho total A4 Landscape es ~297mm. Margen aprox 15mm cada lado -> 267mm útiles.
                ancho_util = 267
                col_w = ancho_util / 3
                
                pdf.set_text_color(30, 50, 100)
                
                for idx in [3, 4, 5]:
                    es_principal = (idx == key_principal)
                    label = "PRECEPTOR PRINCIPAL" if es_principal else "Preceptor"
                    txt = f"{label} {labels[idx]} {str(row[idx] or '').strip()}" if row[idx] else ""
                    
                    if es_principal:
                        pdf.set_font('RobotoMono', 'B', 11)
                    else:
                        pdf.set_font('RobotoMono', 'B', 9)
                    
                    align = 'L' if idx == 3 else ('C' if idx == 4 else 'R')
                    # No saltar línea hasta el último
                    pdf.cell(col_w, 8, txt, 0, 0 if idx < 5 else 1, align)
        except Exception as e:
            print(f"Error PDF preceptor: {e}")

    pdf.ln(5)

    if cal:
        # Configuración del Grid
        margin_left = 15; margin_top = 30; width = 267; height = 140
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
                    y_ini = ((time_to_min(clase[12]) - cal['hora_min']) / duracion) * height
                    y_fin = ((time_to_min(clase[13]) - cal['hora_min']) / duracion) * height
                    
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
                    curso_num = str(clase[0])
                    division = str(clase[1])
                    try:
                        is_high_course = int(curso_num) >= 4
                    except:
                        is_high_course = False
                    
                    div_display = f"{division}°" if is_high_course else division
                    
                    ind_txt = str(clase[9] or '?')
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
                        is_licencia = tipo == 'profesor' and len(clase) > 16 and clase[16] == 1
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
                            materia_txt = "LICENCIADA" if is_licencia else clase[3]
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
                            prof_display = clase[5]
                            if len(clase) > 16 and clase[16] == 1:
                                prof_display = clase[17]
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
                                    pdf.cell(materia_w, line_h, f"{clase[12]} - {clase[13]}", 0, 1, 'C')
                        else:
                            is_short = materia_h_avail < 20; is_tiny = materia_h_avail < 12
                            font_size_mat = 9.5; font_size_det = 8.0; line_h = 3.8
                            if is_short: font_size_mat = 8.0; font_size_det = 7.0; line_h = 3.0
                            if is_tiny: font_size_mat = 7.0; font_size_det = 6.0; line_h = 2.5
                            
                            pdf.set_font('RobotoMono', 'B', font_size_mat)
                            materia_txt = "LICENCIADA" if is_licencia else clase[3]
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
                            prof_display = clase[5]
                            if len(clase) > 16 and clase[16] == 1:
                                prof_display = clase[17]
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
                                    pdf.cell(materia_w, line_h, f"{clase[12]} - {clase[13]}", 0, 1, 'C')
                elif b['tipo'] == 'superposicion':
                    y_ini = ((time_to_min(b['clases'][0][12]) - cal['hora_min']) / duracion) * height
                    latest = max(b['clases'], key=lambda x: time_to_min(x[13]))
                    y_fin = ((time_to_min(latest[13]) - cal['hora_min']) / duracion) * height
                    x = margin_left + col_hour_w + (d_idx * col_day_w) + 1
                    y = margin_top + 6 + y_ini + 1
                    w = col_day_w - 2; h = (y_fin - y_ini) - 2
                    pdf.set_fill_color(220, 220, 220); pdf.rect(x, y, w, h, 'FD')
                    pdf.set_text_color(0, 0, 0); pdf.set_font('RobotoMono', 'B', 8)
                    pdf.set_xy(x, y + (h/2) - 2)
                    pdf.cell(w, 4, f"SUPERPOSICION", 0, 0, 'C')

    output = io.BytesIO()
    pdf_content = pdf.output()
    output.write(pdf_content)
    output.seek(0)
    
    print(f"Total Export PDF (fpdf2): {time.time() - start_time:.4f}s")
    filename = f"{tipo}_{valor}.pdf".replace('|', '_')
    return send_file(output, mimetype='application/pdf', as_attachment=False, download_name=filename)

@app.route('/api/preceptor/<valor>')
def api_preceptor(valor):
    try:
        search_valor = valor
        if '°' in valor:
            search_valor = valor.replace('°', '')
        
        partes = search_valor.split(' ')
        curso = partes[0]
        division = partes[1] if len(partes) > 1 else ""
        
        con = database.conectar()
        cur = con.cursor()
        cur.execute("SELECT * FROM preceptores WHERE curso = ? AND division = ?", (curso, division))
        row = cur.fetchone()
        con.close()
        
        if row:
            cols = ["curso", "division", "turno", "preceptores_manana", "preceptores_tarde", "preceptores_noche"]
            return jsonify(dict(zip(cols, row)))
        return jsonify(None)
    except Exception as e:
        print(f"Error preceptor: {e}")
        return jsonify(None)

@app.route('/api/actualizar')
def api_actualizar():
    try:
        database.crear_tablas()
        database.cargar_desde_sheets(SHEET_ID, GIDS_CURSOS)
        database.cargar_preceptores(SHEET_ID, GID_PRECEPTORES)
        database.cargar_horarios_preceptores(SHEET_ID, GID_HORARIOS_PRECEPTORES)
        return jsonify({"status": "success", "message": "Datos actualizados correctamente"})
    except Exception as e:
        print(f"Error actualizando datos: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/dashboard')
def api_dashboard():
    try:
        con = database.conectar()
        cur = con.cursor()
        cur.execute("SELECT * FROM clases")
        filas = [list(row) for row in cur.fetchall()]
        con.close()
        return jsonify(filas)
    except Exception as e:
        print(f"Error en dashboard: {e}")
        return jsonify([])

@app.route('/api/horario_preceptor/<nombre>')
def api_horario_preceptor(nombre):
    """
    Endpoint para obtener el horario individual de un preceptor.
    """
    return jsonify(database.obtener_horario_preceptor(nombre))

if __name__ == '__main__':
    # Esto garantiza que si cambias el CSV, la web se actualiza al arrancar
    database.crear_tablas()
    database.cargar_desde_sheets(SHEET_ID, GIDS_CURSOS)
    database.cargar_preceptores(SHEET_ID, GID_PRECEPTORES)
    database.cargar_horarios_preceptores(SHEET_ID, GID_HORARIOS_PRECEPTORES)
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
