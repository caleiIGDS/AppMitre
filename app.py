from flask import Flask, render_template, jsonify, Response, send_file
import database
import sqlite3
from fpdf import FPDF
import io

app = Flask(__name__)

# ... (keep obtener_filas and index functions same)

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
    con.close()
    return render_template('index.html', datos={'profesor': profes, 'aula': aulas, 'curso': cursos})

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

def obtener_datos_calendario(filas):
    if not filas:
        return None
    
    dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
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
        'dias': dias,
        'horarios': horarios_ordenados,
        'hora_min': hora_min,
        'hora_max': hora_max,
        'bloques_por_dia': {}
    }

    for dia in dias:
        clases_dia = sorted([f for f in filas if f[11] == dia], key=lambda x: time_to_min(x[12]))
        bloques = []
        procesados = set()
        
        for i in range(len(clases_dia)):
            if i in procesados: continue
            cluster = [clases_dia[i]]; cluster_idx = [i]
            max_fin = time_to_min(clases_dia[i][13])
            for j in range(i + 1, len(clases_dia)):
                if time_to_min(clases_dia[j][12]) < max_fin:
                    cluster.append(clases_dia[j]); cluster_idx.append(j)
                    max_fin = max(max_fin, time_to_min(clases_dia[j][13]))
                else: break
            
            todos_tienen_grupo = all(c[14] and str(c[14]).strip() != "" for c in cluster)
            if len(cluster) > 1 and not todos_tienen_grupo:
                if cluster[0][15] == 1:
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
        calendario['bloques_por_dia'][dia] = bloques
    return calendario

class PDF(FPDF):
    def header(self):
        # Header removed as per user request
        pass

@app.route('/export/pdf/<tipo>/<valor>')
def export_pdf(tipo, valor):
    import time
    start_time = time.time()
    
    # Limpiar el valor si es curso para la búsqueda en BD
    search_valor = valor
    if tipo == 'curso' and '°' in valor:
        search_valor = valor.replace('°', '')
        
    filas = obtener_filas(tipo, search_valor)
    cal = obtener_datos_calendario(filas)
    
    pdf = PDF(orientation='L', unit='mm', format='A4')
    pdf.add_page()
    
    # Nuevo Título simple y centrado
    pdf.set_font('Arial', 'B', 16)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 10, f"Horario Semanal de {tipo.capitalize()}: {valor}", 0, 1, 'C')
    pdf.ln(5)

    if cal:
        # Configuración del Grid
        margin_left = 15; margin_top = 30; width = 267; height = 140
        col_hour_w = 15; col_day_w = (width - col_hour_w) / 5
        
        # Dibujar Cabecera Días
        pdf.set_fill_color(240, 240, 240); pdf.set_font('Arial', 'B', 10)
        pdf.set_xy(margin_left + col_hour_w, margin_top)
        for dia in cal['dias']:
            pdf.cell(col_day_w, 8, dia, 1, 0, 'C', True)
        
        # Dibujar Horas y Grid
        pdf.set_font('Arial', '', 10); pdf.set_text_color(100, 100, 100) # Tamaño horario agrandado a 10
        duracion = cal['hora_max'] - cal['hora_min']
        
        # Pre-calcular posiciones de texto para evitar solapamientos
        text_positions = []
        for hora_str in cal['horarios']:
            m = time_to_min(hora_str)
            y_rel = ((m - cal['hora_min']) / duracion) * height
            y_line = margin_top + 8 + y_rel
            text_positions.append({'txt': hora_str, 'line_y': y_line, 'text_y': y_line - 2})
            
        # Ajustar si hay colisiones (nudge up/down)
        for _ in range(2): # Dos pasadas para estabilizar clusters
            for i in range(len(text_positions) - 1):
                diff = text_positions[i+1]['text_y'] - text_positions[i]['text_y']
                if diff < 3.5: # Aumentado ligeramente para fuentes más grandes
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
        for d_idx, dia in enumerate(cal['dias']):
            for b in cal['bloques_por_dia'][dia]:
                if b['tipo'] == 'materia':
                    clase = b['clase']
                    y_ini = ((time_to_min(clase[12]) - cal['hora_min']) / duracion) * height
                    y_fin = ((time_to_min(clase[13]) - cal['hora_min']) / duracion) * height
                    
                    x = margin_left + col_hour_w + (d_idx * col_day_w) + (b['left'] * col_day_w / 100) + 0.5
                    y = margin_top + 8 + y_ini + 0.5
                    w = (b['ancho'] * col_day_w / 100) - 1
                    h = (y_fin - y_ini) - 1
                    
                    # Bloque principal
                    pdf.set_fill_color(255, 255, 255)
                    pdf.rect(x, y, w, h, 'FD')
                    
                    # Indicador lateral (Vertical si el nombre es largo o el ancho es poco)
                    ind_w = 7
                    if w < 15: ind_w = w * 0.4
                    
                    pdf.set_fill_color(245, 245, 245)
                    pdf.rect(x, y, ind_w, h, 'FD')
                    
                    # Formatear curso y división con grado selectivo
                    curso_num = str(clase[0])
                    division = str(clase[1])
                    try:
                        is_high_course = int(curso_num) >= 4
                    except:
                        is_high_course = False
                    
                    div_display = f"{division}°" if is_high_course else division
                    
                    ind_txt = str(clase[9] or '?')
                    if tipo == 'aula': ind_txt = f"{curso_num}° {div_display}"
                    
                    pdf.set_text_color(0, 0, 0)
                    contiene_letras = any(c.isalpha() for c in ind_txt)
                    if tipo != 'aula' and contiene_letras and (len(ind_txt) > 4 or h > ind_w * 2):
                        pdf.set_font('Arial', 'B', 5)
                        # Dibujar letra por letra verticalmente
                        char_h = 2.5
                        # Truncar si el texto es muy largo para la altura h
                        max_chars = int((h - 2) / char_h)
                        display_txt = ind_txt[:max_chars]

                        start_y = y + (h - (len(display_txt) * char_h)) / 2
                        for i, char in enumerate(display_txt):
                            pdf.set_xy(x, max(y, start_y + (i * char_h)))
                            pdf.cell(ind_w, char_h, char, 0, 0, 'C')
                    else:
                        pdf.set_font('Arial', 'B', 6)
                        pdf.set_xy(x, y)
                        pdf.cell(ind_w, h, ind_txt, 0, 0, 'C')
                    
                    # Contenido Materia Centrado
                    txt_x = x + ind_w + 0.5
                    materia_w = w - ind_w - 1
                    
                    if materia_w > 2:
                        # Ajuste de tamaño de fuente agrandado (si no es división angosta)
                        is_narrow = materia_w < 15
                        font_size_mat = 8.5 if not is_narrow else 6.5
                        font_size_det = 7.5 if not is_narrow else 5.5
                        line_h = 3.5 if not is_narrow else 2.6
                        
                        pdf.set_font('Arial', 'B', font_size_mat)
                        materia_txt = clase[3] # Eliminada función wrap_with_hyphen
                        lines_mat = pdf.multi_cell(materia_w, line_h, materia_txt, split_only=True)
                        
                        pdf.set_font('Arial', '', font_size_det)
                        # Prof: en lugar de P:
                        det_raw = f"Prof: {clase[5]}" if tipo != 'profesor' else f"C: {curso_num}° {div_display}"
                        lines_det = pdf.multi_cell(materia_w, line_h, det_raw, split_only=True)
                        
                        # Altura total estimada
                        actual_lines = len(lines_mat)
                        show_det = False
                        show_time = False
                        
                        if (actual_lines + len(lines_det)) * line_h <= h - 1:
                            actual_lines += len(lines_det)
                            show_det = True
                            
                        if (actual_lines + 1) * line_h <= h - 1:
                            actual_lines += 1
                            show_time = True
                            
                        total_content_h = actual_lines * line_h
                        y_start = max(y + 0.5, y + (h - total_content_h) / 2)
                        
                        pdf.set_xy(txt_x, y_start)
                        
                        pdf.set_font('Arial', 'B', font_size_mat)
                        pdf.multi_cell(materia_w, line_h, materia_txt, 0, 'C')
                        
                        if show_det:
                            pdf.set_font('Arial', '', font_size_det)
                            pdf.set_x(txt_x)
                            pdf.multi_cell(materia_w, line_h, det_raw, 0, 'C')
                            
                        if show_time:
                            pdf.set_font('Arial', '', font_size_det)
                            pdf.set_x(txt_x)
                            pdf.cell(materia_w, line_h, f"{clase[12]} - {clase[13]}", 0, 1, 'C')
                    
                elif b['tipo'] == 'superposicion':
                    y_ini = ((time_to_min(b['clases'][0][12]) - cal['hora_min']) / duracion) * height
                    latest = max(b['clases'], key=lambda x: time_to_min(x[13]))
                    y_fin = ((time_to_min(latest[13]) - cal['hora_min']) / duracion) * height
                    x = margin_left + col_hour_w + (d_idx * col_day_w) + 1
                    y = margin_top + 8 + y_ini + 1
                    w = col_day_w - 2; h = (y_fin - y_ini) - 2
                    pdf.set_fill_color(220, 220, 220); pdf.rect(x, y, w, h, 'FD')
                    pdf.set_text_color(0, 0, 0); pdf.set_font('Arial', 'B', 8)
                    pdf.set_xy(x, y + (h/2) - 2)
                    pdf.cell(w, 4, f"SUPERPOSICION", 0, 0, 'C')

    # Segunda Página: Detalles
    pdf.add_page()
    pdf.set_font('Arial', 'B', 12); pdf.set_text_color(60, 64, 67)
    pdf.cell(0, 10, 'Detalle de Clases', 0, 1, 'L')
    pdf.ln(2)
    
    # Tabla de detalles
    pdf.set_font('Arial', 'B', 9); pdf.set_fill_color(241, 243, 244)
    cols = [('Día', 20), ('Inicio', 15), ('Fin', 15), ('Materia', 70), ('Profesor', 60), ('Aula', 20), ('Curso', 40), ('G', 10)]
    for txt, w in cols: pdf.cell(w, 7, txt, 1, 0, 'C', True)
    pdf.ln()
    
    pdf.set_font('Arial', '', 8)
    for f in filas:
        pdf.cell(20, 6, str(f[11]), 1)
        pdf.cell(15, 6, str(f[12]), 1, 0, 'C')
        pdf.cell(15, 6, str(f[13]), 1, 0, 'C')
        pdf.cell(70, 6, str(f[3])[:40], 1)
        pdf.cell(60, 6, str(f[5])[:35], 1)
        pdf.cell(20, 6, str(f[9]), 1, 0, 'C')
        
        # Formato de curso y división selectivo en tabla
        c_num = str(f[0])
        div = str(f[1])
        try:
            is_high = int(c_num) >= 4
        except:
            is_high = False
        div_txt = f"{div}°" if is_high else div
        
        pdf.cell(40, 6, f"{c_num}° {div_txt}", 1)
        pdf.cell(10, 6, str(f[14] or '-'), 1, 0, 'C')
        pdf.ln()

    output = io.BytesIO()
    pdf_content = pdf.output()
    output.write(pdf_content)
    output.seek(0)
    
    print(f"Total Export PDF (fpdf2): {time.time() - start_time:.4f}s")
    return send_file(output, mimetype='application/pdf', as_attachment=False, download_name=f"{tipo}_{valor}.pdf")

if __name__ == '__main__':
    # Esto garantiza que si cambias el CSV, la web se actualiza al arrancar
    database.crear_tablas()
    database.cargar_csv('datos.csv')
    app.run(host='0.0.0.0', port=5000, debug=True)