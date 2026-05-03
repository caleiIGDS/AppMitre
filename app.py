from flask import Flask, render_template, jsonify, Response
import database
import sqlite3
from fpdf import FPDF

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

class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, 'Horario', 0, 1, 'C')

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Pagina {self.page_no()}', 0, 0, 'C')

    def chapter_title(self, title):
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, title, 0, 1, 'L')
        self.ln(10)

    def chapter_body(self, data):
        self.set_font('Arial', '', 10)
        # Header
        self.cell(40, 10, 'Dia', 1)
        self.cell(40, 10, 'Inicio', 1)
        self.cell(40, 10, 'Fin', 1)
        self.cell(60, 10, 'Materia', 1)
        self.cell(60, 10, 'Profesor', 1)
        self.cell(40, 10, 'Aula', 1)
        self.cell(40, 10, 'Grupo', 1)
        self.ln()
        # Data
        for row in data:
            self.cell(40, 10, str(row[11]), 1)
            self.cell(40, 10, str(row[12]), 1)
            self.cell(40, 10, str(row[13]), 1)
            self.cell(60, 10, str(row[3]), 1)
            self.cell(60, 10, str(row[5]), 1)
            self.cell(40, 10, str(row[9]), 1)
            self.cell(40, 10, str(row[14]), 1)
            self.ln()

@app.route('/export/pdf/<tipo>/<valor>')
def export_pdf(tipo, valor):
    filas = obtener_filas(tipo, valor)
    pdf = PDF(orientation='L', unit='mm', format='A4')
    pdf.add_page()
    pdf.chapter_title(f'Horario para {tipo}: {valor}')
    pdf.chapter_body(filas)
    
    return Response(pdf.output(dest='S'),
                    mimetype='application/pdf',
                    headers={'Content-Disposition': f'inline; filename={tipo}_{valor}.pdf'})

if __name__ == '__main__':
    # Esto garantiza que si cambias el CSV, la web se actualiza al arrancar
    database.crear_tablas()
    database.cargar_csv('datos.csv')
    app.run(host='0.0.0.0', port=5000, debug=True)