#!/usr/bin/env python3
"""Script de un solo uso: sube a gestion.db (servidor) los alias que ya se completaron
en la gestion.db de desarrollo, sin tocar ningún otro dato.

    python actualizar_alias.py --dry-run    # solo informa: no escribe nada
    python actualizar_alias.py              # aplica

Lee `alias_datos.json` (nombre → alias, exportado de la gestion.db local) y por cada
nombre que matchea en el servidor (comparación normalizada: sin acentos, sin mayúsculas,
ver texto.norm) **reemplaza entero** el `alias` de esa fila. Un nombre que no matchea
ninguna fila del servidor se reporta y no rompe nada. Un recurso del servidor que no está
en el JSON queda con su alias tal cual estaba: esto nunca vacía ni borra alias existentes,
sólo escribe donde el JSON trae un valor.

Uso previsto: correr una vez en la consola del hosting después del `git pull` que trae
este archivo y `alias_datos.json`, y borrar los dos al terminar (mismo criterio que las
migraciones de un solo uso descriptas en actualizar.py).
"""

import argparse
import json
import os
import sqlite3
import sys

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(errors='replace')

import gestion
import texto
from config import ahora

JSON_PATH = os.path.join(RAIZ, 'alias_datos.json')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help="Informa qué haría, sin escribir.")
    args = parser.parse_args()

    if not os.path.exists(JSON_PATH):
        print(f"✗ No está {os.path.basename(JSON_PATH)} al lado de este script.")
        return 1
    with open(JSON_PATH, encoding='utf-8') as f:
        datos = json.load(f)
    print(f"{len(datos)} alias en {os.path.basename(JSON_PATH)}.")

    if not os.path.exists(gestion.DB_PATH):
        print("✗ No existe gestion.db en el servidor todavía.")
        return 1

    con = sqlite3.connect(gestion.DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        filas = con.execute("SELECT id, nombre, alias FROM recursos").fetchall()
        por_nombre = {}
        for f in filas:
            por_nombre.setdefault(texto.norm(f['nombre']), []).append(f)

        if not args.dry_run:
            destino = f"{gestion.DB_PATH}.pre-alias-{ahora().strftime('%Y%m%d-%H%M%S')}"
            origen, copia = sqlite3.connect(gestion.DB_PATH), sqlite3.connect(destino)
            try:
                origen.backup(copia)
            finally:
                copia.close()
                origen.close()
            print(f"✓ Copia de seguridad: {os.path.basename(destino)}")

        actualizados, sin_cambio, no_encontrados = 0, 0, []
        for nombre, alias_nuevo in datos.items():
            candidatas = por_nombre.get(texto.norm(nombre))
            if not candidatas:
                no_encontrados.append(nombre)
                continue
            for fila in candidatas:
                if fila['alias'] == alias_nuevo:
                    sin_cambio += 1
                    continue
                if args.dry_run:
                    print(f"  [dry-run] '{fila['nombre']}' (id {fila['id']}): "
                          f"'{fila['alias']}' → '{alias_nuevo}'")
                else:
                    con.execute("UPDATE recursos SET alias = ? WHERE id = ?",
                                (alias_nuevo, fila['id']))
                actualizados += 1

        if not args.dry_run:
            con.commit()

        print(f"\n{actualizados} fila(s) actualizada(s), {sin_cambio} ya coincidían.")
        if no_encontrados:
            print(f"{len(no_encontrados)} nombre(s) del JSON sin match en el servidor "
                  "(no se tocó nada por esos):")
            for n in no_encontrados:
                print(f"  · {n}")
    finally:
        con.close()

    print("\nLISTO." if not args.dry_run else "\nDRY-RUN terminado. Sin --dry-run para aplicar.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
