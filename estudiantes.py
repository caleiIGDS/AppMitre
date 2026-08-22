# estudiantes.py
# Padrón de estudiantes — capa 2: nombra su propia tabla (`estudiantes`) y su propia DB
# (`estudiantes.db`). Es información sensible (DNI de menores) que sólo vive en la
# computadora de la escuela: la DB nunca viaja por git (*.db en .gitignore) y no se
# comparte con ninguna otra área.
#
# No es un área con blueprint/permiso propio en accesos.py — es una dependencia privada
# de salidas.py (autocompletar Apellido y Nombre + DNI al cargar la tabla de Personas),
# así que su ciclo de vida (init_db) lo maneja salidas.py, no app.py.

import csv
import io
import os
import sys

import crud
import texto

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'estudiantes.db')
PREFIJO_BACKUP = 'estudiantes'
TABLA_TESTIGO = 'estudiantes'

SCHEMA = """
CREATE TABLE IF NOT EXISTS estudiantes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    apellido_nombre TEXT NOT NULL,
    dni TEXT NOT NULL,
    curso TEXT NOT NULL,
    division TEXT NOT NULL
);
"""

# Alias que puede traer el encabezado de un CSV real (mayúsculas/tildes ya las saca
# texto.norm antes de comparar). Cualquier encabezado que CONTENGA uno de estos alias
# cuenta como esa columna — tolera "CURSO", "Año", "Apellido y Nombre del Estudiante", etc.
_ALIAS_COLUMNAS = {
    'curso': ['curso', 'ano', 'anio'],
    'nombre': ['apellido', 'nombre'],
    'dni': ['dni', 'documento'],
}


def conectar():
    return crud.conectar(sys.modules[__name__])


def init_db():
    crud.init_db(sys.modules[__name__])


def _detectar_columnas(headers):
    restantes = list(headers)
    encontradas = {}
    for clave, alias in _ALIAS_COLUMNAS.items():
        for h in restantes:
            if any(a in texto.norm(h) for a in alias):
                encontradas[clave] = h
                restantes.remove(h)
                break
    faltantes = set(_ALIAS_COLUMNAS) - set(encontradas)
    if faltantes:
        raise ValueError(
            f"El CSV no tiene columna para: {', '.join(sorted(faltantes))}. "
            f"Encabezados encontrados: {', '.join(headers)}"
        )
    return encontradas


def cargar_csv(file_stream):
    """Reemplaza TODO el padrón por el contenido de `file_stream` (un CSV con columnas de
    curso, apellido y nombre, y DNI, en cualquier orden). Devuelve la cantidad de filas
    cargadas. Lanza ValueError si el CSV no tiene las columnas esperadas o ninguna fila
    válida — nunca deja el padrón a medio reemplazar."""
    contenido = file_stream.read()
    if isinstance(contenido, bytes):
        contenido = contenido.decode('utf-8-sig')
    lector = csv.DictReader(io.StringIO(contenido))
    if not lector.fieldnames:
        raise ValueError("El CSV está vacío o no tiene fila de encabezados.")
    columnas = _detectar_columnas(lector.fieldnames)

    filas = []
    for i, fila in enumerate(lector, start=2):  # la fila 1 es el encabezado
        raw_curso = (fila.get(columnas['curso']) or '').strip().upper()
        nombre = ' '.join((fila.get(columnas['nombre']) or '').split())
        dni = (fila.get(columnas['dni']) or '').strip()
        if not raw_curso and not nombre and not dni:
            continue  # fila en blanco
        if len(raw_curso) < 2 or raw_curso[0] not in '1234567':
            raise ValueError(f"Fila {i}: curso inválido \"{raw_curso}\" (se espera algo como \"1A\" o \"4to 1\").")
        if not nombre or not dni:
            raise ValueError(f"Fila {i}: falta nombre o DNI.")
        filas.append((nombre, dni, raw_curso[0], raw_curso[1:]))

    if not filas:
        raise ValueError("El CSV no tiene ninguna fila válida.")

    con = conectar()
    cur = con.cursor()
    cur.execute("DELETE FROM estudiantes")
    cur.executemany(
        "INSERT INTO estudiantes (apellido_nombre, dni, curso, division) VALUES (?, ?, ?, ?)",
        filas)
    con.commit()
    con.close()
    return len(filas)


def listar_para_autocomplete():
    con = conectar()
    filas = con.execute(
        "SELECT apellido_nombre, dni, curso, division FROM estudiantes ORDER BY apellido_nombre"
    ).fetchall()
    con.close()
    return [dict(f) for f in filas]
