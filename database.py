import sqlite3
import csv
import json
import os
import re
import hmac
import hashlib
import time
import urllib.request
import io
import texto
from config import TURNO_CURSOS, TURNO_DEFAULT, APPSCRIPT_URL, APPSCRIPT_SECRET

def _cargar_nombre_mapeos():
    ruta = os.path.join(os.path.dirname(__file__), 'nombre_mapeos.json')
    if os.path.exists(ruta):
        with open(ruta, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

_NOMBRE_MAPEOS = _cargar_nombre_mapeos()

# Los turnos de la escuela, en orden. Es la lista de la que salen los bloques de la planilla
# de preceptores (`cargar_horarios_preceptores`) y contra la que el agente calcula qué turnos
# de un curso NO tienen a nadie cargado. Una sola lista: si acá dice tres y allá dos, un turno
# entero desaparece sin que nada falle.
TURNOS = ("MAÑANA", "TARDE", "VESPERTINO")


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
    # Nueva tabla para horarios individuales de preceptores
    cur.execute('DROP TABLE IF EXISTS horarios_preceptores')
    cur.execute('''
        CREATE TABLE horarios_preceptores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            turno TEXT NOT NULL,
            preceptor TEXT NOT NULL,
            tipo TEXT NOT NULL,
            curso TEXT NOT NULL,
            division TEXT NOT NULL DEFAULT '',
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

def init_tablas():
    """Crea las tablas solo si no existen. No borra datos existentes."""
    con = conectar()
    cur = con.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS clases (
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
    cur.execute('''
        CREATE TABLE IF NOT EXISTS horarios_preceptores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            turno TEXT NOT NULL,
            preceptor TEXT NOT NULL,
            tipo TEXT NOT NULL,
            curso TEXT NOT NULL,
            division TEXT NOT NULL DEFAULT '',
            dia TEXT NOT NULL
        )
    ''')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_horario_preceptor ON horarios_preceptores(preceptor)')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS personal_no_docente (
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

def tiene_datos():
    try:
        con = conectar()
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM clases")
        count = cur.fetchone()[0]
        con.close()
        return count > 0
    except Exception:
        return False

# Alias local: la implementación vive en texto.py (capa 0, compartida con el resto de las
# áreas). Se conserva el nombre porque es el que se lee bien en este pipeline, y porque
# `limpiar_profesor`/`limpiar_aula` dependen de que NO baje a minúsculas — que es justo la
# diferencia entre `texto.sin_acentos` y `texto.norm`.
eliminar_acentos = texto.sin_acentos

def limpiar_profesor(nombre):
    if not nombre: return ""
    # Eliminar acentos, pasar a mayúsculas, quitar comas
    n = eliminar_acentos(nombre).upper().replace(',', ' ')
    # Quitar puntos (ej: J.PABLO -> J PABLO)
    n = n.replace('.', ' ')
    # Normalizar espacios
    n = re.sub(r'\s+', ' ', n).strip()
    
    return _NOMBRE_MAPEOS.get(n, n)

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




def _url_firmada(gid):
    """URL del Web App de Apps Script con la petición firmada.

    El Drive es privado: no se puede pegar más a docs.google.com/export. El proxy sabe
    qué spreadsheet leer (Script Property `SHEET_ID`), así que sólo hace falta pasarle
    el `gid`. La firma es HMAC-SHA256(secreto, timestamp_en_ms) en hex; el proxy la
    recalcula y además exige que el timestamp esté dentro de su ventana.
    """
    if not APPSCRIPT_URL or not APPSCRIPT_SECRET:
        raise RuntimeError(
            "Faltan SHEETS_PROXY_URL / SHEETS_PROXY_SECRET: la planilla es privada y "
            "sólo se baja por el Web App de Apps Script (ver apps_script/README.md)."
        )
    ms = str(int(time.time() * 1000))
    sig = hmac.new(APPSCRIPT_SECRET.encode(), ms.encode(), hashlib.sha256).hexdigest()
    return f"{APPSCRIPT_URL}?gid={gid}&t={ms}&sig={sig}"


class ProxyError(RuntimeError):
    """El proxy de Apps Script no devolvió un CSV. No es transitorio: no se reintenta.

    Lleva el motivo concreto (firma inválida, sin permisos, Sheet inaccesible, deploy
    viejo, gid inexistente) para que llegue tal cual a quien disparó la carga.
    """


def _verificar_csv(contenido, ctype, gid):
    """Corta con un mensaje claro si lo que volvió del proxy no es el CSV esperado.

    Apps Script sirve TODO con HTTP 200, así que un fallo del script no se ve como
    error de red: llega como texto sentinel (`MITRE_PROXY_ERROR: ...`, nuestro) o como
    una página HTML de Google con la excepción adentro. Sin este chequeo, ese HTML se
    le pasaría a `csv.DictReader` y la carga metería basura (o nada) sin avisar.
    """
    if contenido.startswith('MITRE_PROXY_ERROR'):
        raise ProxyError(f"El proxy rechazó la petición (gid {gid}): {contenido[:300].strip()}")

    principio = contenido.lstrip()[:60].lower()
    if 'text/html' in ctype.lower() or principio.startswith(('<!doctype', '<html')):
        m = re.search(r'Exception:[^<]*', contenido)
        detalle = (m.group(0) if m else ' '.join(contenido.split())[:300]).replace('&quot;', '"').strip()
        raise ProxyError(
            f"El proxy de Sheets no devolvió CSV para el gid {gid}. "
            f"Respuesta de Google: {detalle}"
        )


def descargar_sheet(sheet_id, gid=0, skip_rows=0, intentos=3, demora=2):
    # `sheet_id` se ignora: el spreadsheet lo resuelve el proxy de Apps Script. Se
    # conserva el parámetro para no tocar los call sites ni las firmas de los cargar_*.
    for intento in range(intentos):
        try:
            time.sleep(demora if intento > 0 else 0.5)
            url = _url_firmada(gid)  # re-firma en cada intento: un retry lento no puede quedar fuera de la ventana
            with urllib.request.urlopen(url, timeout=15) as response:
                ctype = response.headers.get('Content-Type', '')
                contenido = response.read().decode('utf-8')

            _verificar_csv(contenido, ctype, gid)

            lineas = contenido.splitlines()
            if skip_rows > 0:
                lineas = lineas[skip_rows:]

            # Normalizar encabezados: minúsculas, sin acentos, espacios a _
            encabezados = lineas[0].lower().replace(' ', '_')
            encabezados = eliminar_acentos(encabezados)
            lineas[0] = encabezados
            return io.StringIO('\n'.join(lineas))
        except (ProxyError, RuntimeError):
            raise  # fallo determinístico del proxy o de config: reintentar no cambia nada
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
        try:
            archivo = descargar_sheet(sheet_id, gid)
        except Exception as e:
            con.close()
            raise RuntimeError(f"Falló la descarga de la hoja '{nombre}' (gid {gid}): {e}") from e
        reader = csv.DictReader(archivo)
        
        for row in reader:
            profesor = limpiar_profesor(row.get('profesor', ''))
            aula = limpiar_aula(row.get('aula', ''))
            inicio = row.get('hora_inicio', '')
            fin = row.get('hora_fin', '')
            
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

def cargar_horarios_preceptores(sheet_id, gid):
    """
    Descarga e importa los horarios individuales de los preceptores desde Google Sheets.
    La hoja tiene 3 bloques (MAÑANA, TARDE, VESPERTINO) en columnas separadas por una col vacía.
    Columnas por bloque: Preceptor | Curso | Division | LUNES | MARTES | MIERCOLES | JUEVES | VIERNES
    Cualquier valor que no sea vacío ni "FALSO" en una celda de día cuenta como presente.
    """
    con = conectar()
    cur = con.cursor()
    print(f"Cargando horarios detallados de preceptores (GID {gid})...")
    try:
        cur.execute("DELETE FROM horarios_preceptores")
        archivo = descargar_sheet(sheet_id, gid, skip_rows=0)
        reader = csv.reader(archivo)

        # Saltamos la fila de encabezados (Preceptor, Curso, Division, LUNES, ...)
        next(reader, None)

        to_insert = []
        dias_nombres = ['LUNES', 'MARTES', 'MIERCOLES', 'JUEVES', 'VIERNES']

        # Estructura por bloque: Preceptor | Curso | Division | LUN | MAR | MIE | JUE | VIE
        # + 1 columna vacía separadora → offset entre bloques = 9
        bloques = [{"turno": turno, "offset": i * 9} for i, turno in enumerate(TURNOS)]

        for row in reader:
            for bloque in bloques:
                off = bloque["offset"]
                if len(row) > off + 2:
                    preceptor = row[off].strip()
                    curso     = row[off+1].strip()
                    division  = row[off+2].strip().upper()

                    if preceptor and preceptor.upper() != "PRECEPTOR":
                        for i, dia_nombre in enumerate(dias_nombres):
                            dia_idx = off + 3 + i
                            if len(row) > dia_idx:
                                marca = row[dia_idx].strip().upper()
                                if marca and marca != 'FALSO':
                                    to_insert.append((
                                        bloque["turno"],
                                        preceptor,
                                        '',
                                        curso,
                                        division,
                                        dia_nombre,
                                    ))

        if to_insert:
            cur.executemany(
                "INSERT INTO horarios_preceptores (turno, preceptor, tipo, curso, division, dia) VALUES (?, ?, ?, ?, ?, ?)",
                to_insert
            )
        con.commit()
        print("Listo horarios preceptores")
    except Exception as e:
        if 'con' in locals():
            con.rollback()
        print(f"Error cargando horarios de preceptores desde Sheets: {e}")
        raise RuntimeError(f"Falló la carga de horarios de preceptores: {e}") from e
    finally:
        if 'con' in locals():
            con.close()

def obtener_horario_preceptor(nombre_buscado):
    con = conectar()
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    query = """
        SELECT turno, preceptor, tipo, curso, division, dia
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

    for row in rows:
        turno_curso = TURNO_CURSOS.get((row['curso'], row['division']), TURNO_DEFAULT)
        row['estado'] = 'titular' if row['turno'] == turno_curso else 'contraturno'

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

def _extraer_num_curso(s):
    """'1ro', '1°', '1er', '2do', '7mo' → '1', '2', '7'"""
    m = re.match(r'(\d+)', str(s).strip())
    return m.group(1) if m else str(s).strip()

def obtener_preceptores_por_curso(curso_raw, division_raw):
    """
    Busca en horarios_preceptores las filas que coinciden con curso y division.
    Agrupa por turno (MAÑANA/TARDE/VESPERTINO) y devuelve un preceptor por turno.
    """
    num = _extraer_num_curso(curso_raw)   # "1ro" / "1°" / "1er" → "1"
    div = division_raw.strip().upper()     # "b" → "B"

    con = conectar()
    cur = con.cursor()

    cur.execute("""
        SELECT turno, GROUP_CONCAT(DISTINCT preceptor) AS nombres
        FROM horarios_preceptores
        WHERE curso = ? AND UPPER(division) = ?
        GROUP BY turno
    """, (num, div))
    turno_map = {row[0]: row[1] for row in cur.fetchall()}

    con.close()

    manana     = turno_map.get("MAÑANA", "")
    tarde      = turno_map.get("TARDE", "")
    vespertino = turno_map.get("VESPERTINO", "")

    if not any([manana, tarde, vespertino]):
        return None

    return {
        "curso": num,
        "division": div,
        "preceptores_manana": manana,
        "preceptores_tarde": tarde,
        "preceptores_vespertino": vespertino,
    }

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
        raise RuntimeError(f"Falló la carga de personal no docente: {e}") from e
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


def obtener_personal_todos():
    con = conectar()
    cur = con.cursor()
    cur.execute(
        "SELECT nombre, rol, dia, hora_inicio, hora_fin FROM personal_no_docente ORDER BY nombre, dia"
    )
    rows = [{'nombre': r[0], 'rol': r[1], 'dia': r[2], 'hora_inicio': r[3], 'hora_fin': r[4]} for r in cur.fetchall()]
    con.close()
    return rows


def obtener_planilla_preceptores_todos():
    con = conectar()
    cur = con.cursor()

    cur.execute("""
        SELECT DISTINCT curso, division FROM clases
        WHERE curso != '' AND division != ''
        ORDER BY CAST(curso AS INTEGER), division
    """)
    cursos = cur.fetchall()

    resultado = []
    for (curso, division) in cursos:
        cur.execute("""
            SELECT turno, GROUP_CONCAT(DISTINCT preceptor) as precs
            FROM horarios_preceptores
            WHERE curso = ? AND division = ?
            GROUP BY turno
        """, (curso, division))
        turnos = {row[0].upper(): row[1] for row in cur.fetchall()}

        resultado.append({
            'curso': curso,
            'division': division,
            'manana': turnos.get('MAÑANA', ''),
            'tarde': turnos.get('TARDE', ''),
            'vespertino': turnos.get('VESPERTINO', '')
        })

    con.close()
    return resultado


def obtener_filas(tipo, valor):
    """Obtiene filas de clases según tipo (profesor, aula, curso, planilla)."""
    try:
        con = conectar()
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        if tipo == 'profesor':
            cur.execute("SELECT * FROM clases WHERE profesor = ? OR (prof_suplente = ? AND suplente_activo = 1)", (valor, valor))
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
                from config import FLOOR_MAPPING
                dia_pl, piso = valor.split('|')
                aulas = FLOOR_MAPPING.get(piso, [])
                if aulas:
                    placeholders = ','.join(['?'] * len(aulas))
                    query = f"SELECT * FROM clases WHERE dia = ? AND aula IN ({placeholders})"
                    cur.execute(query, [dia_pl] + aulas)
            else:
                con.close()
                return []

        filas = [dict(row) for row in cur.fetchall()]
        con.close()
        return filas
    except Exception as e:
        print(f"Error en obtener_filas: {e}")
        return []

def aulas_libres(dia=None, hora=None):
    """Retorna aulas libres en un día/hora dados, agrupadas por piso.
    Si día/hora no se especifican, usa el actual (si es un día laborable).
    Retorna dict con 'dia', 'hora', 'libres_por_piso' (dict piso -> lista de aulas),
    'total_libres' y 'nota' si aplica."""
    from config import DIAS, FLOOR_MAPPING, ahora

    # Resolver día
    if dia is None:
        hoy = ahora()
        dia_semana = hoy.weekday()  # 0=lunes, 4=viernes, 5+=sábado/domingo
        if dia_semana >= 5:
            return {'dia': None, 'hora': None, 'libres_por_piso': {}, 'total_libres': 0,
                    'nota': 'Hoy es fin de semana.'}
        dia = DIAS[dia_semana]

    if dia not in DIAS:
        return {'dia': dia, 'hora': hora, 'libres_por_piso': {}, 'total_libres': 0,
                'nota': f'Día inválido: {dia}'}

    # Resolver hora
    if hora is None:
        hora = ahora().strftime('%H:%M')

    # Universo de aulas: todas las del FLOOR_MAPPING
    todas_aulas = {}
    for piso, aulas in FLOOR_MAPPING.items():
        todas_aulas[piso] = set(aulas)

    # Ocupadas en este día/hora
    con = conectar()
    cur = con.cursor()
    cur.execute("""
        SELECT DISTINCT aula FROM clases
        WHERE dia = ? AND hora_inicio <= ? AND hora_fin > ?
    """, (dia, hora, hora))
    ocupadas = {row[0] for row in cur.fetchall()}
    con.close()

    # Libres por piso
    libres_por_piso = {}
    total_libres = 0
    for piso, aulas_set in todas_aulas.items():
        libres = sorted([a for a in aulas_set if a not in ocupadas])
        libres_por_piso[piso] = libres
        total_libres += len(libres)

    return {
        'dia': dia,
        'hora': hora,
        'libres_por_piso': libres_por_piso,
        'total_libres': total_libres
    }
