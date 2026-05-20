import sqlite3
import csv
import os
import re
import unicodedata
import urllib.request
import io
def conectar():
    return sqlite3.connect('escuela.db')

def crear_tablas():
    con = conectar()
    cur = con.cursor()
    cur.execute('DROP TABLE IF EXISTS clases')
    cur.execute('''
        CREATE TABLE clases (
            curso TEXT, division TEXT, especialidad TEXT,
            materia TEXT, tipo_materia TEXT,
            profesor TEXT, dni TEXT, telefono TEXT, email TEXT,
            aula TEXT, tipo_aula TEXT,
            dia TEXT, hora_inicio TEXT, hora_fin TEXT, grupo TEXT,
            superposicion INTEGER DEFAULT 0,
            suplente_activo INTEGER DEFAULT 0,
            prof_suplente TEXT, sup_ini TEXT, sup_fin TEXT
        )
    ''')
    con.commit()
    con.close()

def eliminar_acentos(texto):
    if not texto: return ""
    return "".join(c for c in unicodedata.normalize('NFD', texto)
                  if unicodedata.category(c) != 'Mn')

def limpiar_profesor(nombre):
    if not nombre: return ""
    # Eliminar acentos, pasar a mayúsculas, quitar comas
    n = eliminar_acentos(nombre).upper().replace(',', ' ')
    # Quitar puntos (ej: J.PABLO -> J PABLO)
    n = n.replace('.', ' ')
    # Normalizar espacios
    n = re.sub(r'\s+', ' ', n).strip()
    
    # Mapeos manuales para casos muy obvios que el algoritmo no pesca
    mapeos = {
        "CASALE SERVIN BETTINA": "CASALE SERVINI BETTINA",
        "CASALLE SERVINI BETINA": "CASALE SERVINI BETINA",
        "CASALE CERVINI": "CASALE SERVINI BETINA",
        "CASALE CERVINI BETINA": "CASALE SERVINI BETINA",
        "CASALLE SERVINI": "CASALE SERVINI BETINA",
        "ALONSO EVELYN": "ALONSO EVELIN",
        "PEREYRA JESSICA": "PEREYRA JESICA",
        "RODRIGUEZ VIRGINA": "RODRIGUEZ VIRGINIA",
        "ZULAICA EMILSE": "ZULAICA EMILCE",
        "SCHNEIDER ERICA": "SCHNEIDER ERIKA"
    }
    return mapeos.get(n, n)

def limpiar_aula(aula):
    if not aula: return ""
    # Si tiene números, nos quedamos solo con los números (ej: "B 2" -> "2")
    numeros = re.findall(r'\d+', aula)
    if numeros:
        return "".join(numeros)
    # Si no tiene números, mantenemos el nombre limpio (ej: "PATIO")
    return eliminar_acentos(aula).upper().strip()

def corregir_horarios(inicio, fin):
    horarios_comunes = ["07:40", "09:40", "10:00", "12:00", "13:30", "15:30", "15:50", "17:50", "18:00", "20:00", "20:10", "22:10"]
    if inicio == fin:
        try:
            idx = horarios_comunes.index(inicio)
            if idx + 1 < len(horarios_comunes):
                return inicio, horarios_comunes[idx+1]
        except ValueError:
            pass
        try:
            h, m = map(int, inicio.split(':'))
            h_fin = (h + 2) % 24
            return inicio, f"{h_fin:02d}:{m:02d}"
        except:
            return inicio, fin
    return inicio, fin



def descargar_sheet(sheet_id, gid=0):
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
    with urllib.request.urlopen(url) as response:
        contenido = response.read().decode('utf-8')
        lineas = contenido.splitlines()
        # Normalizar encabezados: minúsculas, sin acentos, espacios a _
        encabezados = lineas[0].lower().replace(' ', '_')
        encabezados = eliminar_acentos(encabezados)
        lineas[0] = encabezados
        return io.StringIO('\n'.join(lineas))

def cargar_desde_sheets(sheet_id, gids):
    con = conectar()
    cur = con.cursor()
    
    for gid in gids.values():
        print(f"Cargando curso con GID {gid}...")
        archivo = descargar_sheet(sheet_id, gid)
        reader = csv.DictReader(archivo)
        
        for row in reader:
            profesor = limpiar_profesor(row.get('profesor', ''))
            aula = limpiar_aula(row.get('aula', ''))
            inicio, fin = corregir_horarios(row.get('hora_inicio', ''), row.get('hora_fin', ''))
            
            superposicion_raw = row.get('superposicion', '0')
            try:
                superposicion_val = int(superposicion_raw) if superposicion_raw and superposicion_raw.strip() != '' else 0
            except (ValueError, TypeError):
                superposicion_val = 0

            suplente_activo_raw = row.get('suplente_activo', '0')
            try:
                # Handle boolean-like values (TRUE/FALSE, 1/0)
                if str(suplente_activo_raw).strip().upper() in ['TRUE', '1', 'VERDADERO']:
                    suplente_activo_val = 1
                else:
                    suplente_activo_val = 0
            except (ValueError, TypeError):
                suplente_activo_val = 0
                
            datos = (
                row.get('curso', ''), row.get('division', ''), row.get('especialidad', ''),
                eliminar_acentos(row.get('materia', '')).upper().strip(), row.get('tipo_materia', ''),
                profesor, row.get('dni', ''), row.get('telefono', ''), row.get('email', ''),
                aula, row.get('tipo_aula', ''),
                row.get('dia', ''), inicio, fin, row.get('grupo', ''),
                superposicion_val, suplente_activo_val,
                limpiar_profesor(row.get('prof_suplente', '')),
                row.get('sup_ini', ''), row.get('sup_fin', '')
            )
            cur.execute('INSERT INTO clases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', datos)
        print("Listo")
    con.commit()
    con.close()
    print("Listo.")