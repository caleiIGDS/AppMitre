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
    cur.execute('DROP TABLE IF EXISTS preceptores')
    cur.execute('''
        CREATE TABLE preceptores (
            curso TEXT, division TEXT, turno TEXT,
            preceptores_manana TEXT, preceptores_tarde TEXT, preceptores_noche TEXT
        )
    ''')
    
    # Nueva tabla para horarios individuales de preceptores
    cur.execute('DROP TABLE IF EXISTS horarios_preceptores')
    cur.execute('''
        CREATE TABLE horarios_preceptores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            turno TEXT NOT NULL,
            preceptor TEXT NOT NULL,
            tipo TEXT NOT NULL,
            curso TEXT NOT NULL,
            dia TEXT NOT NULL
        )
    ''')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_horario_preceptor ON horarios_preceptores(preceptor)')

    cur.execute('DROP TABLE IF EXISTS personal_no_docente')
    cur.execute('''
        CREATE TABLE personal_no_docente (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            rol TEXT NOT NULL,
            dia TEXT NOT NULL,
            hora_inicio TEXT,
            hora_fin TEXT
        )
    ''')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_personal_no_docente ON personal_no_docente(nombre)')

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
    aula_limpia = eliminar_acentos(aula).upper().strip()
    
    # Mapeos específicos
    if aula_limpia == 'P':
        return 'PATIO'
    
    # Detectar si es un Taller (ej: "T1", "T 1", "TALLER 1")
    es_taller = bool(re.search(r'\b(TALLER|T)\s*\d+', aula_limpia))
    
    numeros = re.findall(r'\d+', aula_limpia)
    if numeros:
        numero_aula = "".join(numeros)
        if es_taller:
            return f"T{numero_aula}"
        return numero_aula
        
    # Si no tiene números, mantenemos el nombre limpio (ej: "PATIO")
    return aula_limpia

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



def descargar_sheet(sheet_id, gid=0, skip_rows=0, intentos=3, demora=2):
    import time
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
    for intento in range(intentos):
        try:
            time.sleep(demora if intento > 0 else 0.5)
            with urllib.request.urlopen(url, timeout=15) as response:
                contenido = response.read().decode('utf-8')
                lineas = contenido.splitlines()

                if skip_rows > 0:
                    lineas = lineas[skip_rows:]

                # Normalizar encabezados: minúsculas, sin acentos, espacios a _
                encabezados = lineas[0].lower().replace(' ', '_')
                encabezados = eliminar_acentos(encabezados)
                lineas[0] = encabezados
                return io.StringIO('\n'.join(lineas))
        except Exception as e:
            print(f"  Intento {intento + 1}/{intentos} fallido: {e}")
            if intento == intentos - 1:
                raise
    return None

def cargar_desde_sheets(sheet_id, gids):
    con = conectar()
    cur = con.cursor()
    
    for nombre, gid in gids.items():
        print(f"Cargando {nombre} (GID {gid})...")
        archivo = descargar_sheet(sheet_id, gid)
        reader = csv.DictReader(archivo)
        
        for row in reader:
            profesor = limpiar_profesor(row.get('profesor', ''))
            aula = limpiar_aula(row.get('aula', ''))
            inicio, fin = corregir_horarios(row.get('hora_inicio', ''), row.get('hora_fin', ''))
            
            superposicion_raw = row.get('superposicion', '0')
            try:
                # Manejar valores tipo checkbox de Google Sheets (TRUE/FALSE, 1/0, VERDADERO/FALSO)
                if str(superposicion_raw).strip().upper() in ['TRUE', '1', 'VERDADERO']:
                    superposicion_val = 1
                else:
                    superposicion_val = 0
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

def cargar_preceptores(sheet_id, gid):
    con = conectar()
    cur = con.cursor()
    print(f"Cargando preceptores con GID {gid}...")
    try:
        # Saltamos 1 fila porque la primera es el título "LISTADO GENERAL..."
        archivo = descargar_sheet(sheet_id, gid, skip_rows=1)
        reader = csv.DictReader(archivo)
        for row in reader:
            div_raw = str(row.get('division', '')).strip()
            div_clean = div_raw[0] if div_raw else ""
            datos = (
                row.get('curso', ''), div_clean, row.get('turno', ''),
                row.get('preceptores_manana', ''), row.get('preceptores_tarde', ''),
                row.get('preceptores_noche', '')
            )
            cur.execute('INSERT INTO preceptores VALUES (?,?,?,?,?,?)', datos)
        print("Listo preceptores")
        con.commit()
    except Exception as e:
        print(f"Error cargando preceptores: {e}")
        con.rollback()
    finally:
        con.close()

def cargar_horarios_preceptores(sheet_id, gid):
    """
    Descarga e importa los horarios individuales de los preceptores desde Google Sheets.
    La hoja tiene 3 bloques (MAÑANA, TARDE, VESPERTINO) en distintas columnas.
    """
    con = conectar()
    cur = con.cursor()
    print(f"Cargando horarios detallados de preceptores (GID {gid})...")
    try:
        cur.execute("DELETE FROM horarios_preceptores")
        # Saltamos 1 fila porque la primera es la que dice "MAÑANA,,,,,,TARDE..."
        archivo = descargar_sheet(sheet_id, gid, skip_rows=1)
        reader = csv.reader(archivo)
        
        # Saltamos la fila de encabezados (preceptor, estado, curso, etc.)
        next(reader, None)
        
        to_insert = []
        dias_nombres = ['LUNES', 'MARTES', 'MIERCOLES', 'JUEVES', 'VIERNES']
        
        # Definición de los bloques y sus columnas iniciales
        # MAÑANA: A=0, TARDE: J=9, VESPERTINO: S=18
        bloques = [
            {"turno": "MAÑANA", "offset": 0},
            {"turno": "TARDE", "offset": 9},
            {"turno": "VESPERTINO", "offset": 18}
        ]
        
        for row in reader:
            for bloque in bloques:
                off = bloque["offset"]
                # Validar que la fila tenga suficientes columnas para este bloque
                if len(row) > off + 2:
                    preceptor = row[off].strip()
                    tipo = row[off+1].strip()
                    curso = row[off+2].strip()
                    
                    if preceptor and preceptor.upper() != "PRECEPTOR": # Solo si hay un nombre real
                        for i, dia_nombre in enumerate(dias_nombres):
                            dia_idx = off + 3 + i
                            if len(row) > dia_idx:
                                marca = row[dia_idx].strip().upper()
                                if marca in ['X', 'TRUE', 'VERDADERO']:
                                    to_insert.append((
                                        bloque["turno"],
                                        preceptor,
                                        tipo,
                                        curso,
                                        dia_nombre
                                    ))
        
        if to_insert:
            cur.executemany(
                "INSERT INTO horarios_preceptores (turno, preceptor, tipo, curso, dia) VALUES (?, ?, ?, ?, ?)",
                to_insert
            )
        con.commit()
        print("Listo horarios preceptores")
    except Exception as e:
        if 'con' in locals():
            con.rollback()
        print(f"Error cargando horarios de preceptores desde Sheets: {e}")
    finally:
        if 'con' in locals():
            con.close()

def obtener_horario_preceptor(nombre_buscado):
    """
    Busca el horario de un preceptor por nombre y lo ordena por turno, tipo, curso y día.
    """
    con = conectar()
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    query = """
        SELECT turno, preceptor, tipo, curso, dia 
        FROM horarios_preceptores 
        WHERE preceptor LIKE ?
        ORDER BY turno, tipo, curso, 
            CASE dia 
                WHEN 'LUNES' THEN 1 
                WHEN 'MARTES' THEN 2 
                WHEN 'MIERCOLES' THEN 3 
                WHEN 'JUEVES' THEN 4 
                WHEN 'VIERNES' THEN 5 
                ELSE 6 
            END
    """
    cur.execute(query, (f"%{nombre_buscado}%",))
    rows = [dict(row) for row in cur.fetchall()]
    con.close()
    return rows

def obtener_lista_preceptores_horario():
    """
    Retorna una lista única de nombres de preceptores que tienen horarios cargados.
    """
    con = conectar()
    cur = con.cursor()
    cur.execute("SELECT DISTINCT preceptor FROM horarios_preceptores WHERE preceptor != '' ORDER BY preceptor")
    preceptores = [r[0] for r in cur.fetchall()]
    con.close()
    return preceptores

def cargar_personal_no_docente(sheet_id, gid):
    con = conectar()
    cur = con.cursor()
    print(f"Cargando personal no docente (GID {gid})...")
    try:
        cur.execute("DELETE FROM personal_no_docente")
        archivo = descargar_sheet(sheet_id, gid)
        reader = csv.DictReader(archivo)
        dias = [
            ("LUNES",     "lunes_inicio",     "lunes_fin"),
            ("MARTES",    "martes_inicio",    "martes_fin"),
            ("MIERCOLES", "miercoles_inicio", "miercoles_fin"),
            ("JUEVES",    "jueves_inicio",    "jueves_fin"),
            ("VIERNES",   "viernes_inicio",   "viernes_fin"),
        ]
        to_insert = []
        for row in reader:
            nombre = limpiar_profesor(row.get('nombre', ''))
            rol = eliminar_acentos(row.get('rol', '')).upper().strip()
            if not nombre or not rol:
                continue
            for dia_nombre, col_ini, col_fin in dias:
                inicio = row.get(col_ini, '').strip()
                fin = row.get(col_fin, '').strip()
                if inicio and fin:
                    to_insert.append((nombre, rol, dia_nombre, inicio, fin))
        if to_insert:
            cur.executemany(
                "INSERT INTO personal_no_docente (nombre, rol, dia, hora_inicio, hora_fin) VALUES (?,?,?,?,?)",
                to_insert
            )
        con.commit()
        print("Listo personal no docente")
    except Exception as e:
        con.rollback()
        print(f"Error cargando personal no docente: {e}")
    finally:
        con.close()

def obtener_personal_por_nombre(nombre):
    con = conectar()
    cur = con.cursor()
    cur.execute(
        "SELECT nombre, rol, dia, hora_inicio, hora_fin FROM personal_no_docente WHERE nombre = ? ORDER BY dia",
        (nombre,)
    )
    rows = [{'nombre': r[0], 'rol': r[1], 'dia': r[2], 'hora_inicio': r[3], 'hora_fin': r[4]} for r in cur.fetchall()]
    con.close()
    return rows

def obtener_lista_personal():
    con = conectar()
    cur = con.cursor()
    cur.execute("SELECT DISTINCT nombre, rol FROM personal_no_docente WHERE nombre != '' ORDER BY nombre")
    personal = [{'nombre': r[0], 'rol': r[1]} for r in cur.fetchall()]
    con.close()
    return personal
