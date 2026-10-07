import sqlite3
import csv
import json
import os
import re
import hmac
import hashlib
import time
import unicodedata
import urllib.request
import io
from .config import (DIAS, DIR_DATOS, TURNO_CURSOS, TURNO_DEFAULT, APPSCRIPT_URL,
                     APPSCRIPT_SECRET, SHEET_ID, GIDS_CURSOS, GIDS_CUPOS,
                     GID_HORARIOS_PRECEPTORES, GID_PERSONAL_NO_DOCENTE)

# El código del sistema de horarios vive todo dentro del paquete; sus datos, no:
# `escuela.db` está en la carpeta de bases del proyecto (`database/`, ver DIR_DATOS en
# horarios/config.py), junto a las del resto. `nombre_mapeos.json` sí sigue acá.
AQUI = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DIR_DATOS, 'escuela.db')


def _cargar_nombre_mapeos():
    ruta = os.path.join(AQUI, 'nombre_mapeos.json')
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
    return sqlite3.connect(DB_PATH)

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

    cur.execute('DROP TABLE IF EXISTS cupos')
    cur.execute(SQL_CUPOS)

    con.commit()
    con.close()

# Una fila por docente de cada cupo, tal cual las pestañas de cupos (ver `cargar_cupos`).
SQL_CUPOS = '''
    CREATE TABLE IF NOT EXISTS cupos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        codigo TEXT NOT NULL, codigo_materia TEXT,
        curso TEXT, division TEXT, materia TEXT, tipo_materia TEXT,
        profesor TEXT, situacion_revista TEXT, activo INTEGER DEFAULT 0,
        desde TEXT, hasta TEXT, dni TEXT, telefono TEXT, email TEXT
    )
'''

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
    cur.execute(SQL_CUPOS)
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

# Vendorizada de la vieja `texto.sin_acentos` (capa 0 compartida): el paquete de horarios
# no importa nada del dominio, y esto es lo único que usaba de `texto.py`. Saca diacríticos
# pero NO baja a minúsculas — `limpiar_profesor`/`limpiar_aula` arman en MAYÚSCULAS.
def eliminar_acentos(s):
    if not s:
        return ""
    return "".join(c for c in unicodedata.normalize('NFD', s)
                   if unicodedata.category(c) != 'Mn')

# Las tres tablas escriben el día distinto: `clases` guarda "Lunes"/"Miércoles" (título, con
# tilde) porque viene del Sheet tal cual, mientras `personal_no_docente` y
# `horarios_preceptores` guardan "LUNES"/"MIERCOLES" (mayúscula, sin tilde) porque las arma el
# loader. Además `clases` tiene 7 filas con "Miercoles" sin tilde y algunas con "Sábado", que
# no es un día de cursada. Este es el único lugar que decide qué día es cuál.
_DIA_POR_NORM = {eliminar_acentos(d).lower(): d for d in DIAS}

def _dia_canonico(dia):
    """'LUNES', 'Miercoles', 'miércoles' → el día tal como está en DIAS. None si no es de cursada."""
    return _DIA_POR_NORM.get(eliminar_acentos(str(dia or '')).lower().strip())

def _a_minutos(hhmm):
    """'07:40' → 460. None si no se puede leer.

    No usar comparación de strings sobre las horas: la base tiene '7:40' y '8:40' sin cero a la
    izquierda (que ordenan mal lexicográficamente), '19:00:00' con segundos y un '16:60' que como
    string no es nada pero como minutos es las 17:00. Sumar h*60+m absorbe los tres casos.
    """
    partes = str(hhmm or '').strip().split(':')
    if len(partes) < 2:
        return None
    try:
        return int(partes[0]) * 60 + int(partes[1])
    except (ValueError, TypeError):
        return None

def a_hhmm(minutos):
    """460 → '07:40'. La vuelta de `_a_minutos`, para formatear al final."""
    return f'{minutos // 60:02d}:{minutos % 60:02d}'

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

def _tildado(valor):
    """Checkbox de Google Sheets (VERDADERO/TRUE/1) → 1; cualquier otra cosa → 0."""
    return 1 if str(valor or '').strip().upper() in ('TRUE', '1', 'VERDADERO') else 0


def _codigo(valor):
    return str(valor or '').strip().upper()


# --- Cupos -----------------------------------------------------------------------------
# Formato nuevo de la planilla (rama horarios-cupos). Las pestañas de cada año dejan de
# traer al docente: cada fila de horario lleva el `codigo` de su cupo (uno por materia y
# división, o por grupo), y siete pestañas nuevas, una por año, dicen quién tiene cada cupo.
# Un cupo puede tener varias filas: la del titular o provisional, y la del suplente que lo
# cubre. Al cargar, cada fila de horario se completa con el docente de su cupo y la tabla
# `clases` queda igual que con el formato viejo: el resto de la app no se entera.

REVISTAS = ('TITULAR', 'PROVISIONAL', 'SUPLENTE')
TIPOS_MATERIA = ('TECNICO-ESPECIFICA', 'CIENTIFICO-TECNOLOGICA', 'TEORICA')


def _normalizar_tipo(valor):
    """'Técnico específica' / 'tecnico-especifica' → 'TECNICO-ESPECIFICA' (para comparar)."""
    return re.sub(r'[\s_-]+', '-', eliminar_acentos(str(valor or '')).upper().strip())


def _resolver_cupo(codigo, filas, avisos):
    """De las filas de un cupo, quién da la clase: devuelve un dict con las columnas de
    docente de `clases` (profesor, contacto, suplente_activo, prof_suplente, sup_ini/fin)."""
    titulares = [f for f in filas if f['situacion_revista'] != 'SUPLENTE']
    suplentes = [f for f in filas if f['situacion_revista'] == 'SUPLENTE']
    activos = [f for f in suplentes if f['activo']]
    if len(titulares) > 1:
        avisos.append(f"Cupo {codigo}: {len(titulares)} titulares/provisionales, se toma {titulares[0]['profesor']}.")
    if len(activos) > 1:
        avisos.append(f"Cupo {codigo}: {len(activos)} suplentes activos, se toma {activos[0]['profesor']}.")
    titular = titulares[0] if titulares else None
    # Sin suplente activo, igual se guarda el último cargado (como hoy, que la columna
    # prof_suplente puede tener nombre con el checkbox apagado).
    suplente = activos[0] if activos else (suplentes[-1] if suplentes else None)
    if not titular and not activos:
        avisos.append(f"Cupo {codigo}: no tiene titular, provisional ni suplente activo.")
    base = titular or suplente or {}
    return {
        'tipo_materia': next((f['tipo_materia'] for f in filas if f['tipo_materia']), ''),
        # Un cupo cubierto solo por un suplente: el suplente queda como profesor.
        'profesor': titular['profesor'] if titular else (suplente['profesor'] if activos else ''),
        'dni': base.get('dni', ''), 'telefono': base.get('telefono', ''), 'email': base.get('email', ''),
        'suplente_activo': 1 if (activos and titular) else 0,
        'prof_suplente': suplente['profesor'] if (suplente and titular) else '',
        'sup_ini': suplente['desde'] if (suplente and titular) else '',
        'sup_fin': suplente['hasta'] if (suplente and titular) else '',
    }


def cargar_cupos(sheet_id, gids, con=None):
    """Baja las pestañas de cupos, las guarda en la tabla `cupos` y devuelve
    ({codigo: columnas de docente}, avisos).

    Columnas de cada pestaña (fila 1, normalizada como las de clases, orden libre):
    codigo | codigo_materia | curso | division | materia | tipo_materia | profesor |
    situacion_de_revista | activo | desde | hasta | dni | telefono | email
    """
    avisos = []
    por_codigo = {}
    propia = con is None
    con = con or conectar()
    cur = con.cursor()
    for nombre, gid in gids.items():
        print(f"Cargando cupos {nombre} (GID {gid})...")
        try:
            archivo = descargar_sheet(sheet_id, gid)
        except Exception as e:
            if propia:
                con.close()
            raise RuntimeError(f"Falló la descarga de la hoja de cupos '{nombre}' (gid {gid}): {e}") from e
        for n, row in enumerate(csv.DictReader(archivo), start=2):
            codigo = _codigo(row.get('codigo'))
            profesor = limpiar_profesor(row.get('profesor', ''))
            if not codigo:
                if profesor:
                    avisos.append(f"Cupos {nombre}, fila {n}: {profesor} sin código, se ignora.")
                continue
            revista = eliminar_acentos(row.get('situacion_de_revista') or row.get('situacion_revista') or '').upper().strip()
            if revista and revista not in REVISTAS:
                avisos.append(f"Cupos {nombre}, fila {n}: situación de revista '{revista}' desconocida.")
            tipo = (row.get('tipo_materia') or '').strip()
            if tipo and _normalizar_tipo(tipo) not in TIPOS_MATERIA:
                avisos.append(f"Cupos {nombre}, fila {n}: tipo de materia '{tipo}' desconocido.")
            fila = {
                'codigo': codigo, 'codigo_materia': _codigo(row.get('codigo_materia')),
                'curso': (row.get('curso') or '').strip(), 'division': (row.get('division') or '').strip(),
                'materia': eliminar_acentos(row.get('materia', '')).upper().strip(),
                'tipo_materia': tipo, 'profesor': profesor, 'situacion_revista': revista,
                'activo': _tildado(row.get('activo')),
                'desde': (row.get('desde') or '').strip(), 'hasta': (row.get('hasta') or '').strip(),
                'dni': row.get('dni', ''), 'telefono': row.get('telefono', ''), 'email': row.get('email', ''),
            }
            if not profesor:
                continue  # cupo todavía sin docente asignado: la fila de horario sale sin profesor
            por_codigo.setdefault(codigo, []).append(fila)
            cur.execute(
                'INSERT INTO cupos (codigo, codigo_materia, curso, division, materia, tipo_materia, '
                'profesor, situacion_revista, activo, desde, hasta, dni, telefono, email) '
                'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                tuple(fila[k] for k in ('codigo', 'codigo_materia', 'curso', 'division', 'materia',
                                        'tipo_materia', 'profesor', 'situacion_revista', 'activo',
                                        'desde', 'hasta', 'dni', 'telefono', 'email')))
    if propia:
        con.commit()
        con.close()
    return {c: _resolver_cupo(c, filas, avisos) for c, filas in por_codigo.items()}, avisos


def cargar_desde_sheets(sheet_id, gids, gids_cupos=None):
    """Carga las pestañas de horarios de cada año en `clases`. Devuelve la lista de avisos.

    Con `gids_cupos`, el docente de cada fila sale de su cupo (columna `codigo`). Una fila
    sin código, o una pestaña todavía en el formato viejo, se lee como antes: con las
    columnas profesor / suplente_activo / prof_suplente / sup_ini / sup_fin.
    """
    con = conectar()
    cur = con.cursor()
    cupos, avisos = cargar_cupos(sheet_id, gids_cupos, con) if gids_cupos else ({}, [])
    usados = set()
    sin_cupo = {}  # código → hojas donde aparece sin docente (un aviso por código, no por fila)

    for nombre, gid in gids.items():
        print(f"Cargando {nombre} (GID {gid})...")
        try:
            archivo = descargar_sheet(sheet_id, gid)
        except Exception as e:
            con.close()
            raise RuntimeError(f"Falló la descarga de la hoja '{nombre}' (gid {gid}): {e}") from e
        reader = csv.DictReader(archivo)

        for n, row in enumerate(reader, start=2):  # n: fila en la planilla (la 1 es el encabezado)
            codigo = _codigo(row.get('codigo'))
            if gids_cupos and codigo:
                usados.add(codigo)
                docente = cupos.get(codigo)
                if docente is None:
                    sin_cupo.setdefault(codigo, []).append(f"{nombre} fila {n}")
                    docente = dict.fromkeys(('profesor', 'dni', 'telefono', 'email', 'prof_suplente',
                                             'sup_ini', 'sup_fin'), '')
                    docente.update(suplente_activo=0, tipo_materia='')
            else:
                docente = {
                    'tipo_materia': row.get('tipo_materia', ''),
                    'profesor': limpiar_profesor(row.get('profesor', '')),
                    'dni': row.get('dni', ''), 'telefono': row.get('telefono', ''), 'email': row.get('email', ''),
                    'suplente_activo': _tildado(row.get('suplente_activo')),
                    'prof_suplente': limpiar_profesor(row.get('prof_suplente', '')),
                    'sup_ini': row.get('sup_ini', ''), 'sup_fin': row.get('sup_fin', ''),
                }

            datos = (
                row.get('curso', ''), row.get('division', ''), row.get('especialidad', ''),
                eliminar_acentos(row.get('materia', '')).upper().strip(),
                docente['tipo_materia'] or row.get('tipo_materia', ''),
                docente['profesor'], docente['dni'], docente['telefono'], docente['email'],
                limpiar_aula(row.get('aula', '')), row.get('tipo_aula', ''),
                row.get('dia', ''), row.get('hora_inicio', ''), row.get('hora_fin', ''), row.get('grupo', ''),
                _tildado(row.get('superposicion')), docente['suplente_activo'],
                docente['prof_suplente'], docente['sup_ini'], docente['sup_fin'],
            )
            cur.execute('INSERT INTO clases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', datos)
        print("Listo")
    for codigo, donde in sorted(sin_cupo.items()):
        avisos.append(f"Código {codigo}: no está en los cupos o no tiene docente ({', '.join(donde[:3])}"
                      f"{f' y {len(donde) - 3} más' if len(donde) > 3 else ''}).")
    for codigo in sorted(set(cupos) - usados):
        avisos.append(f"Cupo {codigo}: tiene docente pero ninguna fila de horario lo usa.")
    con.commit()
    con.close()
    for a in avisos:
        print(f"  AVISO: {a}")
    print("Listo.")
    return avisos

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
                from .config import FLOOR_MAPPING
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
    from .config import DIAS, FLOOR_MAPPING, ahora

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


# ---------------------------------------------------------------------------
# Ocupación: cuándo está ocupada una entidad, en minutos y con el día canónico.
#
# Es la materia prima de la tool `coincidencias` del agente. Todas devuelven la misma forma
# —{dia: [(inicio_min, fin_min, etiqueta, grupo), ...]}— para que quien las cruza no tenga que
# saber de qué tabla salió cada una. La limpieza (días torcidos, horas rotas, filas vacías)
# pasa acá y una sola vez: arriba ya llega sano.
#
# `grupo` ("A"/"B") sólo lo llena `ocupacion_curso`: ahí significa que en esa clase está media
# división y no el curso entero, que es lo que hay que avisar al cruzar horarios. Para un
# docente o un preceptor el dato no dice nada —está entero igual— y va vacío.
# ---------------------------------------------------------------------------

def _ocupacion_desde_clases(where, params, etiqueta, con_grupo=False):
    """Filas de `clases` → {dia: [(ini, fin, etiqueta, grupo)]}. `etiqueta` recibe la fila."""
    con = conectar()
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(f"SELECT * FROM clases WHERE {where}", params)
    filas = [dict(r) for r in cur.fetchall()]
    con.close()

    ocup = {}
    for f in filas:
        dia = _dia_canonico(f['dia'])
        ini, fin = _a_minutos(f['hora_inicio']), _a_minutos(f['hora_fin'])
        # Descarta de un saque las ~864 filas en blanco del CSV, los días que no son de cursada
        # y cualquier hora ilegible. Sin esto un bloque roto se planta en el minuto 0.
        if not dia or ini is None or fin is None or fin <= ini:
            continue
        grupo = (f.get('grupo') or '').strip().upper() if con_grupo else ''
        ocup.setdefault(dia, []).append((ini, fin, etiqueta(f), grupo))
    for dia in ocup:
        ocup[dia].sort()
    return ocup

def ocupacion_curso(curso, division):
    return _ocupacion_desde_clases(
        "curso = ? AND division = ?", (curso, division),
        lambda f: f['materia'] or 'CLASE', con_grupo=True)

def ocupacion_profesor(nombre):
    # Mismo WHERE que `obtener_filas('profesor', ...)`: cuando hay suplencia activa la clase
    # aparece tanto para el titular como para quien lo cubre, porque los dos están ocupados.
    return _ocupacion_desde_clases(
        "profesor = ? OR (prof_suplente = ? AND suplente_activo = 1)", (nombre, nombre),
        lambda f: f"{f['materia'] or 'CLASE'} ({f['curso']}°{f['division']})")

def ocupacion_no_docente(nombre):
    con = conectar()
    cur = con.cursor()
    cur.execute("SELECT rol, dia, hora_inicio, hora_fin FROM personal_no_docente WHERE nombre = ?",
                (nombre,))
    filas = cur.fetchall()
    con.close()

    ocup = {}
    for rol, dia_raw, hi, hf in filas:
        dia = _dia_canonico(dia_raw)
        ini, fin = _a_minutos(hi), _a_minutos(hf)
        if not dia or ini is None or fin is None or fin <= ini:
            continue
        ocup.setdefault(dia, []).append((ini, fin, rol or 'EN LA ESCUELA', ''))
    for dia in ocup:
        ocup[dia].sort()
    return ocup

def ocupacion_preceptor(nombres):
    """Ocupación de un preceptor: los cursos que cubre, cuando esos cursos tienen clase.

    `horarios_preceptores` no guarda horas — sólo qué preceptor cubre qué curso y qué día — así
    que las horas salen de las clases de esos cursos. NO se usa la columna `turno` para acotar:
    el turno de un curso es su turno nominal, y los contraturnos hacen que un curso "de mañana"
    tenga clase hasta las 17:50, con lo cual la franja de cada turno termina siendo el día
    entero y no acota nada. Contra eso, los cursos a cargo son un dato real.

    Es una cota superior: si el preceptor cubre un curso sólo en un turno, acá figura ocupado
    todas las horas de ese curso ese día. Por eso el resultado se marca como aproximado.
    `nombres` acepta varias grafías del mismo nombre, que es como vienen del padrón.
    """
    if isinstance(nombres, str):
        nombres = [nombres]
    if not nombres:
        return {}

    con = conectar()
    cur = con.cursor()
    marcas = ','.join('?' * len(nombres))
    cur.execute(
        f"SELECT DISTINCT curso, UPPER(division), dia FROM horarios_preceptores WHERE preceptor IN ({marcas})",
        tuple(nombres))
    a_cargo = cur.fetchall()

    # Días de cursada en que este preceptor tiene cada curso: {(curso, division): {dias}}
    dias_por_curso = {}
    for curso, division, dia_raw in a_cargo:
        dia = _dia_canonico(dia_raw)
        if dia:
            dias_por_curso.setdefault((curso, division), set()).add(dia)
    if not dias_por_curso:
        con.close()
        return {}

    ocup = {}
    for (curso, division), dias in dias_por_curso.items():
        cur.execute("SELECT dia, hora_inicio, hora_fin FROM clases WHERE curso = ? AND UPPER(division) = ?",
                    (curso, division))
        for dia_raw, hi, hf in cur.fetchall():
            dia = _dia_canonico(dia_raw)
            ini, fin = _a_minutos(hi), _a_minutos(hf)
            if not dia or dia not in dias or ini is None or fin is None or fin <= ini:
                continue
            entrada = (ini, fin, f'{curso}°{division}', '')
            if entrada not in ocup.setdefault(dia, []):
                ocup[dia].append(entrada)
    con.close()

    for dia in ocup:
        ocup[dia].sort()
    return ocup


def init_db():
    """Crea el schema si falta. Idempotente — la llama `app.py` al arrancar, como el
    `init_db()` de las otras áreas. NO baja datos de Sheets (eso es `cargar_inicial`)."""
    init_tablas()


def cargar_inicial():
    """Primer arranque en dev: si `escuela.db` está vacía, la reconstruye desde Sheets.

    Es lo que antes vivía en el bloque `if __name__ == '__main__'` de `app.py`. Bajo
    gunicorn/WSGI no corre (igual que antes): en un deploy nuevo la base nace vacía y se
    puebla con el botón ACTUALIZAR (POST /horarios/api/actualizar).
    """
    init_tablas()
    if not tiene_datos():
        print("Base de horarios vacía, cargando desde Google Sheets...")
        crear_tablas()
        cargar_desde_sheets(SHEET_ID, GIDS_CURSOS, GIDS_CUPOS)
        cargar_horarios_preceptores(SHEET_ID, GID_HORARIOS_PRECEPTORES)
        cargar_personal_no_docente(SHEET_ID, GID_PERSONAL_NO_DOCENTE)
