"""Respaldos rotativos de bases SQLite — capa 0, sin dominio.

Existen porque casi ninguna base se regenera desde una fuente externa y ninguna viaja
por git: si el archivo se pierde, no hay commit ni Sheet del que recuperarlo (ver
`dev-log/DECISIONS.md` 2026-08-08, que es la pérdida real que motivó todo esto). Las dos
excepciones —`escuela.db`, que se rearma desde Sheets, y `agente.db`, telemetría que crece
sin techo— no llaman a `respaldar`. Quién es quién: `database/LEEME.md`.

No conoce ninguna tabla concreta — el área le pasa cuál mirar para decidir si su DB
"tiene datos".
"""

import glob
import hashlib
import os
import sqlite3
from datetime import timedelta
from config import DIR_DATOS, ahora

BACKUP_DIR = os.path.join(DIR_DATOS, 'backups')
BACKUP_MAX = 20
# Sin techo de antigüedad: el "primero de cada día" se conserva para siempre. Un área
# puede pedir lo contrario declarando su propio `BACKUP_MAX_DIAS` (ver `_a_borrar`), que
# es lo que hace salidas.py porque sus datos vencen.
BACKUP_MAX_DIAS = None


def tiene_datos(ruta, tabla):
    """True si la DB de `ruta` existe y tiene al menos una fila en `tabla`.
    Tolera archivos a medio crear (sin tablas todavía): eso cuenta como 'sin datos'."""
    if not os.path.exists(ruta) or os.path.getsize(ruta) == 0:
        return False
    try:
        con = sqlite3.connect(f'file:{ruta}?mode=ro', uri=True)
        try:
            return con.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0] > 0
        finally:
            con.close()
    except sqlite3.Error:
        return False


def hash_archivo(ruta):
    h = hashlib.sha256()
    with open(ruta, 'rb') as f:
        for bloque in iter(lambda: f.read(1 << 20), b''):
            h.update(bloque)
    return h.hexdigest()


def listar(prefijo):
    """Respaldos existentes de `prefijo`, del más viejo al más nuevo. El nombre lleva la
    fecha, así que el orden alfabético ya es el cronológico.

    El prefijo separa los respaldos de cada área dentro de la misma carpeta
    (`gestion-*.db` / `salidas-*.db`): sin él, la rotación de una se comería a la otra.
    """
    return sorted(glob.glob(os.path.join(BACKUP_DIR, f'{prefijo}-*.db')))


def respaldar(db_path, prefijo, tabla_testigo, max_copias=BACKUP_MAX, max_dias=BACKUP_MAX_DIAS):
    """Copia `db_path` a backups/ y conserva las últimas `max_copias`.

    Se llama desde el init_db de cada área, o sea en cada arranque de la app: el respaldo
    queda hecho ANTES de cualquier migración de schema. Usa la API de backup de sqlite3
    en vez de copiar el archivo porque garantiza una copia consistente aunque otro
    proceso esté escribiendo.

    No respalda una DB sin datos en `tabla_testigo`: si el archivo se perdió, un respaldo
    vacío encima de los buenos sería justamente lo que arruinaría la recuperación.
    """
    if not tiene_datos(db_path, tabla_testigo):
        return None

    os.makedirs(BACKUP_DIR, exist_ok=True)
    # Los microsegundos van en el nombre para que dos respaldos del mismo segundo no
    # se pisen (pasa si la app reinicia en loop). Al ser de ancho fijo, el orden
    # alfabético de listar() sigue siendo el cronológico.
    destino = os.path.join(BACKUP_DIR, f"{prefijo}-{ahora():%Y%m%d-%H%M%S-%f}.db")

    origen = sqlite3.connect(db_path)
    copia = sqlite3.connect(destino)
    try:
        origen.backup(copia)
    finally:
        copia.close()
        origen.close()

    # Si no cambió nada desde el último respaldo, no acumular duplicados.
    previos = [r for r in listar(prefijo) if r != destino]
    if previos and hash_archivo(previos[-1]) == hash_archivo(destino):
        os.remove(destino)
        return previos[-1]

    podar(prefijo, max_copias, max_dias)
    return destino


def podar(prefijo, max_copias=BACKUP_MAX, max_dias=BACKUP_MAX_DIAS, dry=False):
    """Borra los respaldos de `prefijo` que ya no hay que conservar y devuelve cuáles.

    La usa `respaldar` en cada arranque, pero también `actualizar.py`: con `dry=True`
    devuelve los que borraría sin tocar nada, que es lo que permite previsualizar en el
    `--dry-run` un cambio de retención antes de aplicarlo.
    """
    sobran = _a_borrar(listar(prefijo), max_copias, max_dias)
    if not dry:
        for viejo in sobran:
            os.remove(viejo)
    return sobran


def _dia(ruta):
    """'gestion-20260808-231729-300184.db' -> '20260808'."""
    return os.path.basename(ruta).split('-')[1]


def _a_borrar(existentes, max_copias, max_dias=None):
    """Qué respaldos sobran.

    Conserva los últimos `max_copias` MÁS el primero de cada día anterior. Sin esa
    segunda regla, una tarde de reinicios depurando (cada arranque escribe en la DB,
    así que cada arranque genera un respaldo nuevo) alcanzaba para empujar fuera de
    la rotación todo lo viejo, que es justo lo que uno querría recuperar.

    Con `max_dias`, el "primero de cada día" deja de conservarse pasado ese plazo: sirve
    para un área cuyos datos vencen, donde guardar el respaldo para siempre haría que
    purgar la fila no purgara nada. Los últimos `max_copias` NO caducan nunca, pase el
    tiempo que pase — si no, una base que no se escribe hace un año se quedaría sin
    ningún respaldo, que es exactamente lo contrario de para lo que existe este archivo.
    """
    recientes = set(existentes[-max_copias:])
    primero_del_dia = {}
    for r in existentes:
        primero_del_dia.setdefault(_dia(r), r)
    if max_dias is not None:
        # `_dia` devuelve 'YYYYMMDD', de ancho fijo: comparar como string ya es comparar
        # cronológicamente, sin parsear ninguna fecha.
        corte = (ahora() - timedelta(days=max_dias)).strftime('%Y%m%d')
        primero_del_dia = {d: r for d, r in primero_del_dia.items() if d >= corte}
    conservar = recientes | set(primero_del_dia.values())
    return [r for r in existentes if r not in conservar]
