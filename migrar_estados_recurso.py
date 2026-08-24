# migrar_estados_recurso.py
# Migración puntual: gestion.ESTADOS_RECURSO pasó de 6 valores libres a un vocabulario
# cerrado (Funcional, Dañado usable, Roto, Dado de baja). Este script pasa los recursos
# ya cargados en gestion.db del vocabulario viejo al nuevo.
#
# Uso:
#   python migrar_estados_recurso.py --dry-run   # solo informa, no escribe nada
#   python migrar_estados_recurso.py              # aplica

import argparse

import gestion
import respaldos

MAPEO = {
    'Disponible': 'Funcional',
    'Retirado': 'Funcional',
    'En uso': 'Funcional',
    'En reparación': 'Roto',
    'De baja': 'Dado de baja',
    'Sin revisar': '',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true',
                         help='Solo informa qué cambiaría, no escribe nada')
    args = parser.parse_args()

    respaldos.respaldar(gestion.DB_PATH, gestion.PREFIJO_BACKUP, gestion.TABLA_TESTIGO)

    con = gestion.conectar()
    cur = con.cursor()
    total = 0
    for viejo, nuevo in MAPEO.items():
        filas = cur.execute("SELECT id, nombre FROM recursos WHERE estado = ?", (viejo,)).fetchall()
        if not filas:
            continue
        etiqueta = nuevo or '(vacío)'
        print(f"{viejo!r} -> {etiqueta!r}: {len(filas)} recurso(s)")
        for f in filas:
            print(f"    #{f['id']} {f['nombre']}")
        total += len(filas)
        if not args.dry_run:
            cur.execute("UPDATE recursos SET estado = ? WHERE estado = ?", (nuevo, viejo))

    if args.dry_run:
        print(f"\nDRY-RUN: migraría {total} recurso(s). Volvé a correrlo sin --dry-run para aplicar.")
        con.close()
    else:
        con.commit()
        con.close()
        print(f"\nListo: {total} recurso(s) migrado(s).")


if __name__ == '__main__':
    main()
