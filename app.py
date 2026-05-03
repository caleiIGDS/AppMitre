from flask import Flask, render_template, jsonify, Response
import database
import sqlite3
from weasyprint import HTML

app = Flask(__name__)

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
    # Usamos DISTINCT para que el buscador no tenga nombres repetidos
    cur.execute("SELECT DISTINCT profesor FROM clases WHERE profesor != '' ORDER BY profesor")
    profes = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT DISTINCT aula FROM clases WHERE aula != '' ORDER BY aula")
    aulas = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT DISTINCT curso, division FROM clases WHERE curso != '' ORDER BY curso, division")
    cursos = [f"{r[0]} {r[1]}" for r in cur.fetchall()]
    con.close()
    return render_template('index.html', datos={'profesor': profes, 'aula': aulas, 'curso': cursos})

@app.route('/api/<tipo>/<valor>')
def api(tipo, valor):
    return jsonify(obtener_filas(tipo, valor))

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
    duracion_total = hora_max - hora_min
    altura_total = max(duracion_total * 1.05, 450)

    def get_posicion_y(hora_str):
        m = time_to_min(hora_str)
        porcentaje = (m - hora_min) / (hora_max - hora_min)
        return porcentaje * altura_total

    calendario = {
        'dias': dias,
        'horarios': horarios_ordenados,
        'altura_total': altura_total,
        'hora_min': hora_min,
        'hora_max': hora_max,
        'bloques_por_dia': {},
        'posiciones_h': {h: get_posicion_y(h) for h in horarios_ordenados}
    }

    for dia in dias:
        clases_dia = sorted([f for f in filas if f[11] == dia], key=lambda x: time_to_min(x[12]))
        bloques = []
        procesados = set()
        
        for i in range(len(clases_dia)):
            if i in procesados: continue
            
            cluster = [clases_dia[i]]
            cluster_idx = [i]
            max_fin = time_to_min(clases_dia[i][13])
            
            for j in range(i + 1, len(clases_dia)):
                if time_to_min(clases_dia[j][12]) < max_fin:
                    cluster.append(clases_dia[j])
                    cluster_idx.append(j)
                    max_fin = max(max_fin, time_to_min(clases_dia[j][13]))
                else:
                    break
            
            todos_tienen_grupo = all(c[14] and str(c[14]).strip() != "" for c in cluster)
            
            if len(cluster) > 1 and not todos_tienen_grupo:
                # Es una superposición
                if cluster[0][15] == 1: # Superposición dividida
                    for idx, clase in enumerate(cluster):
                        top = get_posicion_y(clase[12]) + 2
                        bottom = get_posicion_y(clase[13]) - 2
                        ancho = 100 / len(cluster)
                        left = ancho * idx
                        bloques.append({
                            'tipo': 'materia',
                            'top': top,
                            'alto': max(bottom - top, 20),
                            'ancho': ancho,
                            'left': left,
                            'clase': clase
                        })
                else: # Superposición bloque único
                    top = get_posicion_y(cluster[0][12])
                    latest = max(cluster, key=lambda x: time_to_min(x[13]))
                    bottom = get_posicion_y(latest[13])
                    bloques.append({
                        'tipo': 'superposicion',
                        'top': top,
                        'alto': max(bottom - top, 30),
                        'cantidad': len(cluster),
                        'clases': cluster
                    })
            else:
                # Bloques normales o con grupo
                for idx, clase in enumerate(cluster):
                    top = get_posicion_y(clase[12]) + 2
                    bottom = get_posicion_y(clase[13]) - 2
                    
                    ancho = 100 / len(cluster)
                    left = ancho * idx
                    
                    # Manejo especial de grupos A/B si solo hay uno
                    if len(cluster) == 1:
                        grupo = str(clase[14]).strip().upper() if clase[14] else ""
                        if grupo == 'A':
                            ancho = 50
                            left = 0
                        elif grupo == 'B':
                            ancho = 50
                            left = 50
                        else:
                            ancho = 100
                            left = 0
                            
                    bloques.append({
                        'tipo': 'materia',
                        'top': top,
                        'alto': max(bottom - top, 20),
                        'ancho': ancho,
                        'left': left,
                        'clase': clase
                    })
            
            for idx in cluster_idx: procesados.add(idx)
        
        calendario['bloques_por_dia'][dia] = bloques

    return calendario

@app.route('/export/pdf/<tipo>/<valor>')
def export_pdf(tipo, valor):
    filas = obtener_filas(tipo, valor)
    calendario = obtener_datos_calendario(filas)
    
    rendered_html = render_template('pdf_template.html', 
                                   tipo=tipo, 
                                   valor=valor, 
                                   filas=filas, 
                                   cal=calendario)
    pdf = HTML(string=rendered_html).write_pdf()
    
    return Response(pdf, mimetype='application/pdf', headers={'Content-Disposition': f'inline; filename={tipo}_{valor}.pdf'})

if __name__ == '__main__':
    # Esto garantiza que si cambias el CSV, la web se actualiza al arrancar
    database.crear_tablas()
    database.cargar_csv('datos.csv')
    app.run(host='0.0.0.0', port=5000, debug=True)