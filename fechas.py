#!/usr/bin/env python3
"""Le pone el año actual a las `fecha_revision` cortas ("24/4") de todos los inventarios.

    python fechas.py --dry-run    # solo informa: no escribe nada
    python fechas.py              # aplica

El inventario importado del sheet trae fechas sin año, y `gestion._dias_sin_revisar()` no
las puede ubicar en el tiempo: el slider de "sin revisar hace +N meses" las deja afuera
siempre. Esto las reescribe en el formato de `gestion.FORMATO_FECHA_REVISION` (dd/mm/aaaa),
con el año en curso. Antes de tocar cada base deja un respaldo `fechas-<slug>-*.db` en
`database/backups/`, aparte de la rotación de cada inventario.

Es de un solo uso pero idempotente: una fecha que ya tiene año no matchea y se saltea.
"""

import argparse
import glob
import os
import re
import sqlite3
import sys
from datetime import date

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)

# Misma razón que en actualizar.py: en Windows la consola es cp1252.
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(errors='replace')

import respaldos
from config import DIR_DATOS, ahora

DIR_INVENTARIOS = os.path.join(DIR_DATOS, 'inventarios')
FECHA_CORTA = re.compile(r'(\d{1,2})/(\d{1,2})')


def procesar(ruta, anio, dry):
    slug = os.path.splitext(os.path.basename(ruta))[0]
    con = sqlite3.connect(ruta)
    try:
        filas = con.execute("SELECT id, fecha_revision FROM recursos").fetchall()
    except sqlite3.OperationalError as e:
        print(f"\n{slug}: se saltea ({e})")
        con.close()
        return 0

    cambios, invalidas, futuras = [], [], []
    hoy = ahora().date()
    for rid, texto in filas:
        m = FECHA_CORTA.fullmatch((texto or '').strip())
        if not m:
            continue
        dia, mes = int(m.group(1)), int(m.group(2))
        try:
            fecha = date(anio, mes, dia)
        except ValueError:
            invalidas.append((rid, texto))
            continue
        nueva = fecha.strftime('%d/%m/%Y')
        cambios.append((nueva, rid))
        if fecha > hoy:
            futuras.append((rid, texto, nueva))

    print(f"\n{slug}: {len(filas)} recursos, {len(cambios)} fecha(s) sin año")
    for rid, texto, nueva in futuras:
        print(f"  ! id {rid}: '{texto}' -> {nueva} queda en el futuro")
    for rid, texto in invalidas:
        print(f"  ! id {rid}: '{texto}' no es una fecha válida, no se toca")

    if cambios and not dry:
        respaldos.respaldar(ruta, f'fechas-{slug}', 'recursos')
        with con:
            con.executemany("UPDATE recursos SET fecha_revision = ? WHERE id = ?", cambios)
        print(f"  ✓ {len(cambios)} actualizada(s)")
    elif cambios:
        print(f"  [dry-run] se actualizarían {len(cambios)} (ej: id {cambios[0][1]} -> {cambios[0][0]})")
    con.close()
    return len(cambios)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--dry-run', action='store_true', help='solo informa, no escribe')
    args = parser.parse_args()

    anio = ahora().year
    rutas = sorted(glob.glob(os.path.join(DIR_INVENTARIOS, '*.db')))
    if not rutas:
        print(f"No hay inventarios en {DIR_INVENTARIOS}")
        return
    print(f"Año a asignar: {anio}{'  (dry-run)' if args.dry_run else ''}")
    total = sum(procesar(r, anio, args.dry_run) for r in rutas)
    print(f"\nTotal: {total} fecha(s) {'a actualizar' if args.dry_run else 'actualizadas'}.")


if __name__ == '__main__':
    main()
