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

@app.route('/export/pdf/<tipo>/<valor>')
def export_pdf(tipo, valor):
    filas = obtener_filas(tipo, valor)
    
    rendered_html = render_template('pdf_template.html', tipo=tipo, valor=valor, filas=filas)
    pdf = HTML(string=rendered_html).write_pdf()
    
    return Response(pdf, mimetype='application/pdf', headers={'Content-Disposition': f'inline; filename={tipo}_{valor}.pdf'})

if __name__ == '__main__':
    # Esto garantiza que si cambias el CSV, la web se actualiza al arrancar
    database.crear_tablas()
    database.cargar_csv('datos.csv')
    app.run(host='0.0.0.0', port=5000, debug=True)