import sqlite3
import csv
import os

def conectar():
    return sqlite3.connect('escuela.db')

def crear_tablas():
    con = conectar()
    cur = con.cursor()
    cur.execute('DROP TABLE IF EXISTS horarios')
    cur.execute('''
        CREATE TABLE horarios (
            curso TEXT, division TEXT, especialidad TEXT,
            materia TEXT, tipo_materia TEXT,
            profesor TEXT, dni TEXT, telefono TEXT, email TEXT,
            aula TEXT, tipo_aula TEXT,
            dia TEXT, hora_inicio TEXT, hora_fin TEXT, grupo TEXT
        )
    ''')
    con.commit()
    con.close()

def cargar_csv(archivo_csv):
    if not os.path.exists(archivo_csv): return
    con = conectar()
    cur = con.cursor()
    
    with open(archivo_csv, 'r', encoding='utf-8') as f:
        # DictReader es la clave: lee por nombre de cabecera, no por posicion
        reader = csv.DictReader(f)
        for row in reader:
            # row.get('columna', '') intenta buscar el dato. Si no existe, pone vacío.
            # Esto evita que la app explote si borras una columna o le cambias el nombre.
            datos = (
                row.get('curso', ''), row.get('division', ''), row.get('especialidad', ''),
                row.get('materia', ''), row.get('tipo_materia', ''),
                row.get('profesor', ''), row.get('dni', ''), row.get('telefono', ''), row.get('email', ''),
                row.get('aula', ''), row.get('tipo_aula', ''),
                row.get('dia', ''), row.get('hora_inicio', ''), row.get('hora_fin', ''), row.get('grupo', '')
            )
            cur.execute('INSERT INTO horarios VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', datos)
            
    con.commit()
    con.close()