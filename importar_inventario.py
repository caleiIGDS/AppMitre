# importar_inventario.py
# Import puntual del inventario físico (sheet "Inventario renovable 2026") a la tabla
# recursos de gestion.db.
#
# gestion.db sigue siendo la fuente de verdad: esto es una carga de datos, no una
# sincronización. Correrlo de nuevo actualiza por nombre (no duplica); las filas
# repetidas dentro del sheet (ej: dos "Formon") se mantienen como recursos separados.
#
# Uso:
#   python importar_inventario.py            # descarga el CSV del sheet
#   python importar_inventario.py datos.csv  # usa un CSV local ya descargado

import csv
import io
import sys
import urllib.request

import gestion
import texto

SHEET_ID = "12dNx9m9UCzP6nrWkd93BN5k38-hKcLp3YzF3koy7CEE"
GID = "0"
CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={GID}"

# Columnas del sheet: Material, Fecha, Estado, Utilidad, Descripcion-observaciones,
# Cantidad, Ubicación. La columna "Utilidad" del sheet entra en recursos.valor
# (el sheet conserva el nombre viejo; la app la renombró a "Valor").
COLUMNAS = 7

# Estados del sheet → vocabulario de la app (gestion.ESTADOS_RECURSO).
# "nc" = no controlado. "Funcional -" = funciona con observaciones (quedan en descripción).
MAPEO_ESTADOS = {
    'funcional': 'Disponible',
    'funcional -': 'Disponible',
    'reparar': 'En reparación',
    'nc': 'Sin revisar',
}


def obtener_filas(ruta_csv=None):
    if ruta_csv:
        with open(ruta_csv, encoding='utf-8') as f:
            contenido = f.read()
    else:
        with urllib.request.urlopen(CSV_URL, timeout=30) as resp:
            contenido = resp.read().decode('utf-8')
    return list(csv.reader(io.StringIO(contenido)))


def importar(ruta_csv=None):
    filas = obtener_filas(ruta_csv)
    if not filas or texto.norm(filas[0][0]) != 'material':
        raise SystemExit(f"Encabezado inesperado: {filas[:1]} — ¿cambió el formato del sheet?")

    gestion.init_db()  # asegura tablas y columnas nuevas antes de insertar
    con = gestion.conectar()
    cur = con.cursor()

    # Filas preexistentes, matcheables una sola vez cada una (por nombre normalizado).
    existentes = {}
    for fila in cur.execute("SELECT id, nombre, descripcion FROM recursos ORDER BY id").fetchall():
        existentes.setdefault(texto.norm(fila['nombre']), []).append(dict(fila))

    insertados = actualizados = 0
    for fila in filas[1:]:
        fila = (fila + [''] * COLUMNAS)[:COLUMNAS]
        material, fecha, estado, valor, obs, cantidad, ubicacion = (c.strip() for c in fila)
        if not material:
            continue
        estado_app = MAPEO_ESTADOS.get(estado.lower())
        if estado_app is None:
            print(f"  aviso: estado desconocido {estado!r} en {material!r} -> 'Sin revisar'")
            estado_app = 'Sin revisar'

        candidatos = existentes.get(texto.norm(material), [])
        if candidatos:
            previo = candidatos.pop(0)
            descripcion = previo['descripcion'] or ''
            if obs and obs not in descripcion:
                descripcion = f"{descripcion}\n{obs}".strip()
            cur.execute(
                "UPDATE recursos SET fecha_revision=?, estado=?, valor=?, descripcion=?, cantidad=?, ubicacion=? WHERE id=?",
                (fecha, estado_app, valor, descripcion, cantidad, ubicacion, previo['id']))
            actualizados += 1
        else:
            cur.execute(
                "INSERT INTO recursos (nombre, tipo, descripcion, ubicacion, estado, cantidad, valor, fecha_revision) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (material, '', obs, ubicacion, estado_app, cantidad, valor, fecha))
            insertados += 1

    con.commit()
    total = cur.execute("SELECT COUNT(*) FROM recursos").fetchone()[0]
    con.close()
    print(f"Importación lista: {insertados} recursos nuevos, {actualizados} actualizados, {total} en total.")


if __name__ == '__main__':
    importar(sys.argv[1] if len(sys.argv) > 1 else None)
