#!/usr/bin/env python3
"""Pone al día una instalación vieja de AppMitre — ejecutar en la consola del hosting:

    python actualizar.py --dry-run    # solo informa: no escribe nada
    python actualizar.py              # aplica

Existe porque no todo lo que cambió en las DBs entra por el hook `migrar()` de cada área.
Los `ALTER` aditivos sí (los corre `crud.init_db` sola en cada arranque), pero algunas
migraciones **cruzan DBs** y por eso no pueden vivir adentro de un área — ninguna importa
a la otra (ver CLAUDE.md, criterio de capas):

  1. Gestión dejó de ser UN inventario y pasó a ser varios, uno por archivo: `recursos` y
     sus tres tablas se van de `gestion.db` a `inventarios/<slug>.db`, y los permisos
     `gestion.*` que había en `accesos.db` pasan a llevar el ámbito de ese inventario.
  2. Todas las bases se mudaron a `database/`. Esa no es una migración de datos sino de
     archivos, y es la única que hay que correr sí o sí: sin ella la app se niega a
     arrancar (ver la guarda de `app.py`), porque los datos quedaron en el lugar viejo.

(El área `/historia` — hitos y personas — se extrajo del código; su migración vieja
`gestion.db → historia.db` y la de `proyectos → hitos` se sacaron de acá con ella. Ver
`dev-log/DECISIONS.md`.)

En el equipo de desarrollo eso se corrió una vez con un script de un solo uso y se borró;
una instalación que venga de un deploy anterior nunca lo vio. Sin esto, un `git pull` deja
esas filas huérfanas: no se pierden, pero dejan de aparecer en la web.

Es idempotente: cada paso mira el estado real y se saltea solo si ya está hecho. Correrlo
dos veces no rompe nada.
"""

import argparse
import glob
import os
import sqlite3
import sys

from dotenv import load_dotenv

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)

# El destino es la consola del hosting (Linux, UTF-8), pero esto también se corre en
# Windows para probarlo, donde la consola es cp1252 y las flechas/tildes revientan el
# print. Que un carácter no mapeable salga como '?' es mucho mejor que abortar a mitad
# de una migración por un UnicodeEncodeError.
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(errors='replace')

# El `.env` lo carga `app.py` al arrancar el web app, pero esto corre en una consola donde
# nadie lo hizo. Sin esto, importar un área que exige variables en producción (horarios
# pide SHEETS_PROXY_*) revienta antes de llegar a la primera migración. Va antes de los
# imports de área, que es cuando se leen esas variables.
load_dotenv(os.path.join(RAIZ, '.env'))

import accesos
import crud
import fotos_disco
import gestion
import agente
import salidas
import respaldos
from config import DIR_DATOS, ahora  # `ahora`: el reloj de la escuela, nunca datetime.now()
from agente import db as agente_db  # su SCHEMA vive dentro de gestion.db
from agente import registro as agente_registro  # el registro de uso, en agente.db

# Avisos que no frenan la corrida pero el usuario tiene que ver al final.
AVISOS = []

# `ALTER TABLE ... DROP COLUMN` (el que borra `drive_url`) recién existe acá. En un SQLite
# más viejo no es que falle el script: falla el import de app.py, o sea el sitio entero.
SQLITE_MINIMO_DROP_COLUMN = (3, 35, 0)


# ---------------------------------------------------------------------------
# Utilidades de inspección
# ---------------------------------------------------------------------------

def _conectar(ruta):
    con = sqlite3.connect(ruta)
    con.row_factory = sqlite3.Row
    return con


def _tablas(con):
    return {f[0] for f in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _columnas(con, tabla):
    """Columnas de `tabla`, en el orden en que están declaradas."""
    return [f[1] for f in con.execute(f"PRAGMA table_info({tabla})").fetchall()]


def _filas(con, tabla):
    return con.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]


def _tiene_columna(con, tabla, columna):
    return tabla in _tablas(con) and columna in _columnas(con, tabla)


def _donde_esta(ruta):
    """La ruta real de una base: la nueva si ya está mudada, la vieja si todavía no.

    Sólo para INFORMAR. Después del paso 0 las dos son la misma, así que esto únicamente
    cambia algo en `--dry-run`, donde el diagnóstico tiene que poder leer bases que
    todavía están en la raíz.
    """
    for origen, destino in _mudanzas():
        if destino == ruta:
            return origen
    return ruta


def _tablas_de(ruta):
    """Las tablas de una DB por ruta, abriéndola y cerrándola. Para los chequeos sueltos
    del diagnóstico, donde no vale la pena arrastrar una conexión."""
    if not os.path.exists(ruta):
        return set()
    con = _conectar(ruta)
    try:
        return _tablas(con)
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Paso 0 — todas las bases se mudan a database/
# ---------------------------------------------------------------------------

# Lo que SQLite deja al lado de la base y tiene que viajar con ella: si un `-wal` se
# quedara atrás, se perderían las últimas transacciones confirmadas.
SIDECARS = ('-wal', '-shm', '-journal')


def _mudanzas():
    """`(origen, destino)` de cada cosa que cambió de lugar, si el origen todavía existe.

    El destino es lo que HOY declara cada módulo (ya apunta a `database/`); el origen es
    donde estaba antes — la raíz para casi todas, `horarios/` para `escuela.db`. En una
    instalación ya mudada ninguno de esos orígenes existe y la lista queda vacía.

    Sólo entran las bases que el código declara. Cualquier otro `.db` suelto en la raíz es
    una sobra (una prueba, una restauración vieja) y se reporta sin tocarlo: mezclarlo con
    las buenas es justamente lo que la carpeta nueva viene a evitar.
    """
    bases = (gestion.DB_PATH, accesos.DB_PATH, salidas.DB_PATH,
             agente_registro.DB_PATH)
    pares = [(os.path.join(RAIZ, os.path.basename(d)), d) for d in bases]
    pares.append((os.path.join(RAIZ, 'horarios', 'escuela.db'),
                  os.path.join(DIR_DATOS, 'escuela.db')))

    # Las copias .pre-actualizacion-* de corridas anteriores viajan con su base: restaurar
    # una es copiarla encima del destino, así que tienen que quedar en la misma carpeta.
    for origen, destino in list(pares):
        for sufijo in SIDECARS:
            pares.append((origen + sufijo, destino + sufijo))
        for copia in sorted(glob.glob(origen + '.pre-actualizacion-*')):
            pares.append((copia, destino + copia[len(origen):]))

    pares.append((os.path.join(RAIZ, 'inventarios'), gestion.DIR_INVENTARIOS))
    pares.append((os.path.join(RAIZ, 'backups'), respaldos.BACKUP_DIR))
    return [(o, d) for o, d in pares if os.path.exists(o)]


def mudar_a_database(dry):
    """Mueve las bases del layout viejo a `database/`.

    Antes cada área dejaba su `.db` donde le quedaba cómodo: seis sueltas en la raíz,
    `escuela.db` adentro del paquete de horarios, más `inventarios/` y `backups/`. El
    código nuevo las busca todas en `database/`.

    Mueve con `os.replace` y no con una copia: es un rename dentro del mismo filesystem,
    instantáneo y sin estados a medias. Nunca pisa un destino que ya exista — si el mismo
    archivo aparece de los dos lados no hay forma de saber cuál es el bueno, así que se
    frena y lo decide una persona.
    """
    print("\n" + "=" * 70)
    print("PASO 0 · Todas las bases a database/")
    print("=" * 70)

    pendientes = _mudanzas()
    if not pendientes:
        print("  · Nada que mudar: no quedó ninguna base en el lugar viejo.")
    else:
        choques = [(o, d) for o, d in pendientes if os.path.exists(d)]
        if choques:
            print("  ✗ El mismo archivo está de los dos lados y no se puede saber cuál vale:")
            for origen, destino in choques:
                print(f"      {os.path.relpath(origen, RAIZ)}  ya existe en  "
                      f"{os.path.relpath(destino, RAIZ)}")
            print("    No se movió nada. Comparalos a mano, dejá uno solo y volvé a correr.")
            return False

        for origen, destino in pendientes:
            if dry:
                print(f"  [dry-run] movería {os.path.relpath(origen, RAIZ)} → "
                      f"{os.path.relpath(destino, RAIZ)}")
                continue
            os.makedirs(DIR_DATOS, exist_ok=True)
            os.replace(origen, destino)
            print(f"  ✓ {os.path.relpath(origen, RAIZ)} → {os.path.relpath(destino, RAIZ)}")

    # Lo que quede suelto en la raíz no lo toca nadie, pero conviene que se vea: son
    # sobras, y la única forma de que sigan siendo sobras es nombrarlas.
    sobras = [os.path.basename(f) for f in sorted(glob.glob(os.path.join(RAIZ, '*.db')))]
    if sobras and not dry:
        AVISOS.append(f"Quedaron {len(sobras)} .db sueltos en la raíz que no son de "
                      f"ningún área ({', '.join(sobras)}). Revisalos y borralos.")
    return True


# ---------------------------------------------------------------------------
# Paso 0.5 — diagnóstico
# ---------------------------------------------------------------------------

def diagnostico():
    """Informa qué hay instalado. Devuelve False si algo impide seguir."""
    print("=" * 70)
    print("DIAGNÓSTICO")
    print("=" * 70)
    print(f"Python {sys.version.split()[0]}  ·  SQLite {sqlite3.sqlite_version}")

    for declarada in (gestion.DB_PATH, salidas.DB_PATH, agente_registro.DB_PATH):
        # `_donde_esta`: en --dry-run la mudanza no se hizo y las bases siguen en la raíz.
        ruta = _donde_esta(declarada)
        nombre = os.path.basename(ruta)
        if not os.path.exists(ruta):
            print(f"\n{nombre}: no existe todavía (se va a crear vacía)")
            continue
        con = _conectar(ruta)
        try:
            tablas = sorted(_tablas(con) - {'sqlite_sequence'})
            print(f"\n{nombre}:")
            for tabla in tablas:
                print(f"    {tabla:<26} {_filas(con, tabla):>5} filas")
        finally:
            con.close()

    if 'inventarios' in _tablas_de(gestion.DB_PATH):
        for fila in gestion.listar_inventarios():
            marca = ' · SIN CLAVE' if fila['sin_clave'] else ''
            print(f"\ndatabase/inventarios/{fila['slug']}.db: {fila['total']} recursos{marca}")
    else:
        print("\n(el detalle de cada inventario se ve una vez hecha la mudanza)")

    escuela = _donde_esta(os.path.join(DIR_DATOS, 'escuela.db'))
    print(f"\nescuela.db: {'presente' if os.path.exists(escuela) else 'ausente'} "
          "(se regenera desde Google Sheets con POST /horarios/api/actualizar, no se toca acá)")

    # El único bloqueo posible: la migración destructiva de `drive_url` necesita un SQLite
    # que sepa DROP COLUMN. Avisar acá y no en medio de un traceback del servidor web.
    if sqlite3.sqlite_version_info < SQLITE_MINIMO_DROP_COLUMN:
        pendiente = False
        for ruta, tablas in ((gestion.DB_PATH, ('recursos',)),):
            if not os.path.exists(ruta):
                continue
            con = _conectar(ruta)
            try:
                pendiente = pendiente or any(_tiene_columna(con, t, 'drive_url') for t in tablas)
            finally:
                con.close()
        if pendiente:
            minimo = '.'.join(str(n) for n in SQLITE_MINIMO_DROP_COLUMN)
            print(f"\n  ✗ BLOQUEO: este SQLite ({sqlite3.sqlite_version}) no soporta "
                  f"ALTER TABLE ... DROP COLUMN (necesita {minimo}+),")
            print("    y las DBs todavía tienen la columna `drive_url` que hay que eliminar.")
            print("    Tal como está, el sitio entero va a dar 500: `migrar()` corre en el")
            print("    import de app.py. Hay que poner un guard en gestion.migrar()")
            print("    antes de subir esto.")
            return False
    return True


# ---------------------------------------------------------------------------
# Paso 1 — copia de seguridad fuera de la rotación
# ---------------------------------------------------------------------------

def copia_de_seguridad(dry):
    """Copia intocable de cada DB, aparte de los respaldos rotativos de `respaldos.py`.

    La rotación conserva 20 copias y este script (más los arranques del día) puede
    empujar afuera justo la de antes del cambio. Esta copia no rota y no la borra nadie.
    """
    print("\n" + "=" * 70)
    print("PASO 1 · Copia de seguridad")
    print("=" * 70)

    sello = ahora().strftime('%Y%m%d-%H%M%S')
    for ruta in (gestion.DB_PATH, accesos.DB_PATH, salidas.DB_PATH,
                 agente_registro.DB_PATH):
        if not os.path.exists(ruta):
            continue
        destino = f"{ruta}.pre-actualizacion-{sello}"
        if dry:
            print(f"  [dry-run] copiaría {os.path.basename(ruta)} → {os.path.basename(destino)}")
            continue
        # La API de backup de sqlite3 y no una copia de archivo: garantiza una copia
        # consistente aunque el servidor web esté escribiendo en este momento.
        origen, copia = sqlite3.connect(ruta), sqlite3.connect(destino)
        try:
            origen.backup(copia)
        finally:
            copia.close()
            origen.close()
        print(f"  ✓ {os.path.basename(destino)}")


# ---------------------------------------------------------------------------
# Paso 3.5 — el inventario único se convierte en el primero de varios
# ---------------------------------------------------------------------------

# Las tablas que dejan de ser de `gestion.db` y pasan a ser de cada inventario.
TABLAS_INVENTARIO = ('recursos', 'recurso_unidades', 'kit_items', 'recurso_bajas')

# Cómo se va a llamar el inventario que sale del que ya existía. Se le pone la clave desde
# /gestion cuando el admin entra: hasta entonces no lo abre nadie, que es lo correcto —
# nadie eligió todavía quién lo maneja.
NOMBRE_INVENTARIO_INICIAL = 'General'


def _permisos_sueltos(con, tabla):
    """Filas de accesos.db con alguna clave `gestion.*` SIN ámbito: las que quedaron del
    inventario único y hay que reapuntar."""
    import json
    pendientes = []
    for fila in con.execute(f"SELECT id, permisos FROM {tabla}").fetchall():
        claves = json.loads(fila['permisos'])
        if any(c.startswith('gestion.') and '/' not in c for c in claves):
            pendientes.append((fila['id'], claves))
    return pendientes


def mudar_a_inventarios(dry):
    """Saca `recursos` y compañía de `gestion.db` y las pone en su propio inventario.

    Dos mitades, cada una idempotente por su cuenta: mover las tablas (se saltea si
    `gestion.db` ya no las tiene) y reapuntar los permisos de `accesos.db` (se saltea si ya
    no queda ninguna clave `gestion.*` suelta). Sin la segunda, todos los dispositivos que
    ya estaban habilitados se quedarían afuera del único inventario que existe.
    """
    import json

    print("\n" + "=" * 70)
    print("PASO 3.5 · El inventario único pasa a ser uno de varios")
    print("=" * 70)

    if not os.path.exists(gestion.DB_PATH):
        print("  · gestion.db no existe todavía: no hay nada que mudar.")
        return True

    con_g = _conectar(gestion.DB_PATH)
    try:
        tablas_g = _tablas(con_g)
        hay_que_mudar = 'recursos' in tablas_g
        if hay_que_mudar:
            filas = {t: _filas(con_g, t) for t in TABLAS_INVENTARIO if t in tablas_g}
            detalle = ', '.join(f"{t} ({n})" for t, n in filas.items())
            if dry:
                print(f"  [dry-run] crearía el inventario «{NOMBRE_INVENTARIO_INICIAL}» "
                      f"(sin clave, para que se la ponga el admin)")
                print(f"  [dry-run] movería a inventarios/<slug>.db: {detalle}")
                print("  [dry-run] y borraría esas tablas de gestion.db")
            else:
                gestion.init_db()   # crea la tabla `inventarios` y la carpeta
                fila = gestion.crear_inventario(NOMBRE_INVENTARIO_INICIAL, None)
                if fila is None:
                    print("  ✗ no se pudo crear el inventario inicial.")
                    return False
                destino = os.path.join(gestion.DIR_INVENTARIOS, f"{fila['slug']}.db")
                con_i = _conectar(destino)
                try:
                    for tabla in TABLAS_INVENTARIO:
                        if tabla not in tablas_g:
                            continue
                        datos = con_g.execute(f"SELECT * FROM {tabla}").fetchall()
                        if not datos:
                            continue
                        cols = list(datos[0].keys())
                        marcas = ','.join('?' * len(cols))
                        con_i.executemany(
                            f"INSERT INTO {tabla} ({','.join(cols)}) VALUES ({marcas})",
                            [tuple(d[c] for c in cols) for d in datos])
                    con_i.commit()
                finally:
                    con_i.close()
                for tabla in TABLAS_INVENTARIO:
                    if tabla in tablas_g:
                        con_g.execute(f"DROP TABLE {tabla}")
                con_g.commit()
                print(f"  ✓ inventario «{fila['nombre']}» (/gestion/{fila['slug']}): {detalle}")
                print("    Todavía NO tiene clave: ponésela desde /gestion o no entra nadie.")
        else:
            print("  · gestion.db ya no tiene `recursos`: la mudanza ya estaba hecha.")
    finally:
        con_g.close()

    # --- Los permisos de accesos.db ----------------------------------------
    if not os.path.exists(accesos.DB_PATH):
        return True
    inventarios = gestion.listar_inventarios()
    con_a = _conectar(accesos.DB_PATH)
    try:
        pendientes = {t: _permisos_sueltos(con_a, t)
                      for t in ('dispositivos', 'invitaciones') if t in _tablas(con_a)}
        total = sum(len(v) for v in pendientes.values())
        if not total:
            print("  · accesos.db: no quedan permisos `gestion.*` sin inventario.")
            return True
        if dry and hay_que_mudar and not inventarios:
            # En dry-run el inventario todavía no existe: el reapunte iría a ése.
            print(f"  [dry-run] reapuntaría {total} acceso(s) al inventario nuevo "
                  f"«{NOMBRE_INVENTARIO_INICIAL}»")
            return True
        if len(inventarios) != 1:
            AVISOS.append(
                f"accesos.db tiene {total} acceso(s) con permisos `gestion.*` viejos y hay "
                f"{len(inventarios)} inventarios: no se puede adivinar a cuál apuntan. "
                f"Reasignalos a mano desde el panel de cada inventario.")
            print(f"  ! {total} acceso(s) con permisos viejos y {len(inventarios)} "
                  f"inventarios: no se tocan (ver avisos al final).")
            return True
        marca = f"inv:{inventarios[0]['id']}"
        if dry:
            print(f"  [dry-run] reapuntaría {total} acceso(s) a {marca} "
                  f"(«{inventarios[0]['nombre']}»)")
            return True
        for tabla, filas in pendientes.items():
            for fila_id, claves in filas:
                nuevas = [f'{marca}/{c}' if c.startswith('gestion.') and '/' not in c else c
                          for c in claves]
                con_a.execute(f"UPDATE {tabla} SET permisos = ? WHERE id = ?",
                              (json.dumps(sorted(set(nuevas))), fila_id))
        con_a.commit()
        print(f"  ✓ {total} acceso(s) reapuntados a «{inventarios[0]['nombre']}»")
    finally:
        con_a.close()
    return True


# ---------------------------------------------------------------------------
# Paso 4 — migraciones de schema de cada área
# ---------------------------------------------------------------------------

def migraciones_de_schema(dry):
    """Corre el `init_db()` de cada área: crea tablas nuevas y aplica los ALTER.

    Es lo mismo que pasa solo al arrancar la app (app.py lo llama en el import). Hacerlo
    acá deja el error a la vista en la consola en vez de en el log del servidor web.
    """
    print("\n" + "=" * 70)
    print("PASO 4 · Migraciones de schema (init_db de cada área)")
    print("=" * 70)

    if dry:
        print("  [dry-run] correría gestion.init_db(), agente.init_db(),")
        print("            salidas.init_db() y accesos.init_db()")
        print("            (ALTER aditivos, rename utilidad→valor, DROP de drive_url,")
        print("             las tablas agente_* dentro de gestion.db, agente.db con el")
        print("             registro de uso del asistente, y la purga de")
        print("             salidas.db vencidas hace más de 1 año)")
        if not os.path.exists(accesos.DB_PATH):
            print("            accesos.db no existe todavía: se va a crear VACÍA. Hasta que")
            print("            invites al primer dispositivo, el único acceso es el de")
            print("            administración con GESTION_CLAVE.")
        return True

    for nombre, init in (('gestion', gestion.init_db),
                         ('agente', agente.init_db),
                         ('salidas', salidas.init_db),
                         ('accesos', accesos.init_db)):
        try:
            init()
            print(f"  ✓ {nombre}")
        except Exception as e:
            print(f"  ✗ {nombre}: {type(e).__name__}: {e}")
            return False
    return True


# ---------------------------------------------------------------------------
# Paso 4.5 — fotos: de base64 en la columna a archivos en database/fotos/
# ---------------------------------------------------------------------------

def _dbs_bajo_database():
    """Todas las .db bajo database/ (recursivo), salvo `backups/` — ahí viven copias
    históricas de la rotación de `respaldos.py`, no algo que migrar. Genérico a
    propósito: no nombra `gestion` ni `historia`, así alcanza también
    `inventarios/*.db` y cualquier .db que se agregue en el futuro sin tocar este
    archivo."""
    encontradas = []
    for raiz, dirs, archivos in os.walk(DIR_DATOS):
        dirs[:] = [d for d in dirs if d != 'backups']
        encontradas.extend(os.path.join(raiz, a) for a in archivos if a.endswith('.db'))
    return sorted(encontradas)


def migrar_fotos_a_disco(dry):
    """Decodifica las fotos guardadas como base64 en la columna `fotos` (formato viejo:
    {'b64', 'tipo', 'fecha'}) y las escribe en database/fotos/, dejando en la fila sólo
    {'id', 'tipo', 'fecha'} (ver fotos_disco.py). Genérico: recorre CUALQUIER .db bajo
    database/ buscando tablas con columna `fotos`, así que un área nueva con fotos no
    necesita un paso aparte acá. Idempotente: una fila sin ningún elemento con `b64` no
    se reescribe.
    """
    import json

    print("\n" + "=" * 70)
    print("PASO 4.5 · Fotos: de base64 en la DB a archivos en database/fotos/")
    print("=" * 70)

    total_filas = total_fotos = 0
    for db_ruta in _dbs_bajo_database():
        con = _conectar(db_ruta)
        try:
            tablas = [t for t in _tablas(con) if _tiene_columna(con, t, 'fotos')]
            if not tablas:
                continue
            nombre_db = os.path.relpath(db_ruta, DIR_DATOS)
            for tabla in tablas:
                filas = con.execute(
                    f'SELECT id, fotos FROM "{tabla}" WHERE fotos IS NOT NULL').fetchall()
                for fila in filas:
                    try:
                        fotos = json.loads(fila['fotos'] or '[]')
                    except (TypeError, ValueError):
                        continue
                    if not any('b64' in f for f in fotos):
                        continue
                    total_filas += 1
                    if dry:
                        print(f"  [dry-run] {nombre_db}: {tabla}.id={fila['id']} — "
                              f"{sum('b64' in f for f in fotos)} foto(s) en base64 a migrar")
                        continue
                    nuevas = []
                    for f in fotos:
                        if 'b64' in f:
                            foto_id = fotos_disco.guardar(f['b64'], f.get('tipo', 'image/jpeg'))
                            nuevas.append({'id': foto_id, 'tipo': f.get('tipo', 'image/jpeg'),
                                           'fecha': f.get('fecha', ahora().isoformat())})
                            total_fotos += 1
                        else:
                            nuevas.append(f)
                    con.execute(f'UPDATE "{tabla}" SET fotos = ? WHERE id = ?',
                                (json.dumps(nuevas), fila['id']))
            if not dry:
                con.commit()
        finally:
            con.close()

    if total_filas == 0:
        print("  · No hay fotos en formato viejo (base64) en ninguna DB. Nada que hacer.")
    elif dry:
        print(f"  [dry-run] migraría {total_filas} fila(s) con fotos en base64.")
    else:
        print(f"  ✓ {total_filas} fila(s) migradas, {total_fotos} archivo(s) escritos en "
              f"database/fotos/.")
    return True


# ---------------------------------------------------------------------------
# Paso 4.7 — datos sensibles que ya no tienen dueño en el código
# ---------------------------------------------------------------------------

# El padrón (DNI de menores) dejó de vivir en el servidor: se carga en el navegador y no
# sale de ahí (ver agent_docs/salidas-educativas.md). `estudiantes.py` ya no existe, así
# que nadie vuelve a abrir estos archivos: no hay nada que migrar, sólo que borrar.
NOMBRES_PADRON = ('estudiantes.db', 'estudiantes.db-wal', 'estudiantes.db-shm',
                  'estudiantes.db-journal')
GLOBS_PADRON = ('estudiantes.db.pre-actualizacion-*',)
PREFIJO_BACKUP_PADRON = 'estudiantes'

# `salidas_familias` guardaba lo que completaba cada familia por el link público (DNI,
# salud, obra social, teléfonos, domicilio). Dejó de escribirse el 2026-08-16 y
# `salidas.migrar()` prometía desde entonces que "la limpia actualizar.py": esto es esa
# limpieza. No entra por el PASO 5 porque ahí una tabla con filas exige `--limpiar`, que
# es global y forzaría también cualquier otra sobra con datos de cualquier otra base.
TABLA_FAMILIAS = 'salidas_familias'


def _archivos_del_padron():
    """Todo lo que quedó del padrón, en `database/` y en la raíz (layout viejo), más sus
    respaldos rotativos. Se busca en los dos lados porque `estudiantes` ya no está en la
    lista de mudanzas: un archivo que quedó arriba no lo movería nadie."""
    encontrados = []
    for carpeta in (DIR_DATOS, RAIZ):
        for nombre in NOMBRES_PADRON:
            ruta = os.path.join(carpeta, nombre)
            if os.path.exists(ruta):
                encontrados.append(ruta)
        for patron in GLOBS_PADRON:
            encontrados.extend(sorted(glob.glob(os.path.join(carpeta, patron))))
    encontrados.extend(respaldos.listar(PREFIJO_BACKUP_PADRON))
    return encontrados


def retirar_datos_sensibles(dry):
    """Saca del servidor lo que ya no tiene dueño en el código: el padrón entero y la
    tabla `salidas_familias`, incluidas las copias de esa tabla que quedaron DENTRO de
    los respaldos, y recorta los respaldos de salidas fuera de la retención nueva.

    Idempotente: en la segunda corrida no queda nada que borrar. El criterio es borrar
    sólo artefactos de un módulo que ya no existe — nunca una copia manual de una base
    que sigue viva, que es lo que hace el bloque de avisos del final.
    """
    print("\n" + "=" * 70)
    print("PASO 4.7 · Datos sensibles que el código ya no lee")
    print("=" * 70)

    # 1. El padrón
    archivos = _archivos_del_padron()
    if not archivos:
        print("  · No quedó ningún archivo del padrón: ya estaba retirado.")
    for ruta in archivos:
        rel = os.path.relpath(ruta, RAIZ)
        kb = os.path.getsize(ruta) // 1024
        if dry:
            print(f"  [dry-run] borraría {rel} ({kb} KB)")
        else:
            os.remove(ruta)
            print(f"  ✓ {rel} borrado ({kb} KB)")

    # 2. salidas_familias
    if os.path.exists(salidas.DB_PATH):
        con = _conectar(salidas.DB_PATH)
        try:
            if TABLA_FAMILIAS in _tablas(con):
                n = _filas(con, TABLA_FAMILIAS)
                if dry:
                    print(f"  [dry-run] borraría la tabla '{TABLA_FAMILIAS}' de salidas.db ({n} fila(s))")
                else:
                    con.execute(f'DROP TABLE "{TABLA_FAMILIAS}"')
                    con.commit()
                    print(f"  ✓ tabla '{TABLA_FAMILIAS}' borrada de salidas.db ({n} fila(s))")
            else:
                print(f"  · salidas.db ya no tiene '{TABLA_FAMILIAS}'.")
        finally:
            con.close()

    # 3. Respaldos de salidas fuera de la retención nueva (salidas.BACKUP_MAX_DIAS).
    #    La app lo aplicaría sola en el próximo arranque; acá se hace para que se vea en
    #    el --dry-run antes de aplicarlo.
    sobran = respaldos.podar(salidas.PREFIJO_BACKUP, max_dias=salidas.BACKUP_MAX_DIAS, dry=dry)
    if sobran:
        desde = os.path.basename(sobran[0])
        verbo = "podaría" if dry else "✓ podados"
        print(f"  {'[dry-run] ' if dry else ''}{verbo} {len(sobran)} respaldo(s) de salidas "
              f"de más de {salidas.BACKUP_MAX_DIAS} días (el más viejo: {desde})")
    else:
        print(f"  · Respaldos de salidas: ninguno excede los {salidas.BACKUP_MAX_DIAS} días.")

    # 3.5. Los respaldos que SÍ se conservan siguen teniendo la tabla adentro: son copias
    #      del archivo entero tomadas antes del DROP, y podar por antigüedad sólo alcanza a
    #      los viejos. Borrar el respaldo entero tiraría la red de recuperación de salidas,
    #      que es para lo que existe; así que se le saca la tabla a cada uno y se deja el
    #      resto intacto. El VACUUM no es opcional: sin él el DROP deja las filas en páginas
    #      libres del archivo y los datos se siguen leyendo con un editor hexadecimal.
    limpiados = filas_limpiadas = 0
    for ruta in respaldos.listar(salidas.PREFIJO_BACKUP):
        if ruta in sobran:
            continue  # ya se fue entero en la poda
        con = _conectar(ruta)
        try:
            if TABLA_FAMILIAS not in _tablas(con):
                continue
            n = _filas(con, TABLA_FAMILIAS)
            limpiados += 1
            filas_limpiadas += n
            if not dry:
                con.execute(f'DROP TABLE "{TABLA_FAMILIAS}"')
                con.commit()
                con.execute("VACUUM")
        finally:
            con.close()
    if limpiados:
        print(f"  {'[dry-run] sacaría' if dry else '✓ sacada'} la tabla '{TABLA_FAMILIAS}' "
              f"de {limpiados} respaldo(s) de salidas ({filas_limpiadas} fila(s) en total)")
    else:
        print(f"  · Ningún respaldo de salidas conserva '{TABLA_FAMILIAS}'.")

    # 4. Las copias manuales NO se tocan: son la red de seguridad de deploys anteriores y
    #    database/LEEME.md dice que se borran a mano cuando el deploy se verificó. Pero
    #    tienen adentro las filas que acabamos de borrar, así que hay que nombrarlas.
    viejas = sorted(glob.glob(os.path.join(DIR_DATOS, 'salidas.db.pre-actualizacion-*')))
    if viejas:
        nombres = ', '.join(os.path.basename(v) for v in viejas)
        AVISOS.append(
            f"Quedan {len(viejas)} copias manuales de salidas.db con los datos que este paso "
            f"borró ({nombres}). No se tocan a propósito (son la red de este deploy). "
            f"Cuando verifiques que todo anda: rm database/salidas.db.pre-actualizacion-*")

    return True


# ---------------------------------------------------------------------------
# Paso 5 — limpieza de sobras (tablas y columnas que el código ya no declara)
# ---------------------------------------------------------------------------

# Qué SQL describe a cada DB. `gestion.db` tiene dos dueños: el REGISTRO de inventarios y
# el asistente, que guarda ahí sus tablas de auditoría y sesión. Sin sumar las dos, la
# limpieza se comería `agente_log` y compañía por creerlas sobras. Ojo: desde la mudanza,
# `gestion.SCHEMA` NO describe gestion.db sino cada `inventarios/<slug>.db`.
DUENOS_FIJOS = (
    (lambda: gestion.DB_PATH, lambda: (gestion.SCHEMA_REGISTRO, agente_db.SCHEMA)),
    (lambda: accesos.DB_PATH, lambda: (accesos.SCHEMA,)),
    (lambda: salidas.DB_PATH, lambda: (salidas.SCHEMA,)),
    (lambda: agente_registro.DB_PATH, lambda: (agente_registro.SCHEMA,)),
)


def _duenos():
    """Los dueños fijos más UNO POR INVENTARIO, que se resuelven al vuelo porque la lista
    depende de la DB y no del código. Es lo que hace que la limpieza de sobras siga
    alcanzando a `recurso_ubicaciones` y compañía adentro de cada inventario."""
    inventarios = gestion.listar_inventarios() if os.path.exists(gestion.DB_PATH) else []
    return list(DUENOS_FIJOS) + [
        # Más el versionado que el motor le agrega a cada inventario (`_revision` y
        # `recursos.version`, ver crud.instalar_versionado): sin sumarlo, la limpieza los
        # tomaría por sobras y `--limpiar` los borraría.
        (lambda slug=f['slug']: os.path.join(gestion.DIR_INVENTARIOS, f'{slug}.db'),
         lambda: (gestion.SCHEMA, crud.schema_versionado(gestion)))
        for f in inventarios]


def _schema_de_referencia(*schemas):
    """{tabla: {columnas}} según el SQL declarado en el código, sin tocar disco.

    En vez de parsear el SQL a mano, se ejecuta en una DB en memoria y se le pregunta con
    los mismos PRAGMA que a la DB real: si el motor lo entiende igual, la comparación es
    exacta por construcción.
    """
    ref = sqlite3.connect(':memory:')
    try:
        for sql in schemas:
            ref.executescript(sql)
        return {t: set(_columnas(ref, t))
                for (t,) in ref.execute("SELECT name FROM sqlite_master WHERE type='table'")
                if t != 'sqlite_sequence'}
    finally:
        ref.close()


def _columna_sin_datos(con, tabla, columna):
    """True si la columna no tiene ni un valor cargado en ninguna fila."""
    return con.execute(
        f'SELECT COUNT(*) FROM "{tabla}" '
        f'WHERE "{columna}" IS NOT NULL AND TRIM(CAST("{columna}" AS TEXT)) != ""'
    ).fetchone()[0] == 0


def limpiar_sobras(dry, forzar):
    """Elimina de las DBs lo que el código ya no declara.

    Los `.db` no viajan por git: una instalación vieja arrastra tablas y columnas de
    schemas anteriores que ninguna consulta vuelve a mirar. No rompen nada, pero ensucian
    el archivo, confunden al que lo inspecciona y hacen más pesados los respaldos.

    El criterio para borrar es el mismo que se usó para `drive_url` (ver `gestion.migrar`):
    **si está vacío se va solo; si tiene datos cargados hay que pedirlo con `--limpiar`.**
    Una tabla que sobra pero tiene filas es casi siempre una migración que nadie corrió,
    no basura — borrarla en silencio sería exactamente el accidente que este script
    intenta evitar.
    """
    print("\n" + "=" * 70)
    print("PASO 5 · Limpieza de sobras" + (" (--limpiar: borra aunque tengan datos)" if forzar else ""))
    print("=" * 70)

    puede_drop_columna = sqlite3.sqlite_version_info >= SQLITE_MINIMO_DROP_COLUMN

    for get_ruta, get_schemas in _duenos():
        ruta = get_ruta()
        if not os.path.exists(ruta):
            continue
        nombre_db = os.path.basename(ruta)
        referencia = _schema_de_referencia(*get_schemas())

        con = _conectar(ruta)
        try:
            sobran_tablas = sorted(_tablas(con) - set(referencia) - {'sqlite_sequence'})
            sobran_columnas = [
                (t, c) for t in sorted(set(referencia) & _tablas(con))
                for c in _columnas(con, t) if c not in referencia[t]
            ]
            if not sobran_tablas and not sobran_columnas:
                print(f"  · {nombre_db}: sin sobras, coincide con el schema del código.")
                continue

            for tabla in sobran_tablas:
                n = _filas(con, tabla)
                if n and not forzar:
                    print(f"  ! {nombre_db}: tabla `{tabla}` sobra y tiene {n} fila(s) — NO se borra.")
                    AVISOS.append(f"{nombre_db}: la tabla `{tabla}` ({n} filas) quedó sin migrar. "
                                  f"Revisala y, si es descartable, corré con --limpiar.")
                    continue
                detalle = f"{n} fila(s), forzado" if n else "vacía"
                if dry:
                    print(f"  [dry-run] borraría la tabla `{tabla}` de {nombre_db} ({detalle})")
                    continue
                con.execute(f'DROP TABLE "{tabla}"')
                print(f"  ✓ {nombre_db}: tabla `{tabla}` eliminada ({detalle})")

            for tabla, columna in sobran_columnas:
                vacia = _columna_sin_datos(con, tabla, columna)
                if not vacia and not forzar:
                    print(f"  ! {nombre_db}: `{tabla}.{columna}` sobra pero tiene datos — NO se borra.")
                    AVISOS.append(f"{nombre_db}: la columna `{tabla}.{columna}` tiene datos que el "
                                  f"código ya no lee. Si son descartables, corré con --limpiar.")
                    continue
                if not puede_drop_columna:
                    minimo = '.'.join(str(n) for n in SQLITE_MINIMO_DROP_COLUMN)
                    print(f"  ! {nombre_db}: `{tabla}.{columna}` no se puede borrar "
                          f"(SQLite {sqlite3.sqlite_version} < {minimo}). Se deja; es inofensiva.")
                    continue
                detalle = "vacía" if vacia else "con datos, forzado"
                if dry:
                    print(f"  [dry-run] borraría la columna `{tabla}.{columna}` de {nombre_db} ({detalle})")
                    continue
                try:
                    con.execute(f'ALTER TABLE "{tabla}" DROP COLUMN "{columna}"')
                    print(f"  ✓ {nombre_db}: columna `{tabla}.{columna}` eliminada ({detalle})")
                except sqlite3.OperationalError as e:
                    # Pasa si la columna está adentro de un índice o de un UNIQUE.
                    print(f"  ! {nombre_db}: no se pudo borrar `{tabla}.{columna}`: {e}")
            con.commit()
        finally:
            con.close()

    # Compactar: los DROP dejan páginas libres adentro del archivo, no lo achican.
    if not dry:
        for get_ruta, _ in _duenos():
            if os.path.exists(get_ruta()):
                con = sqlite3.connect(get_ruta())
                try:
                    con.execute("VACUUM")
                finally:
                    con.close()
        print("  ✓ VACUUM: los archivos quedaron compactados.")
    return True


# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Pone al día las DBs de una instalación vieja de AppMitre.")
    parser.add_argument('--dry-run', action='store_true',
                        help="Informa qué haría, sin escribir nada.")
    parser.add_argument('--limpiar', action='store_true',
                        help="En el paso 5, borra también las tablas y columnas que sobran "
                             "aunque tengan datos cargados. Sin esto, sólo se van las vacías.")
    args = parser.parse_args()

    if args.dry_run:
        print("\n*** MODO DRY-RUN: no se escribe nada ***")

    # Antes que nada: si los archivos siguen en el lugar viejo, todo lo que viene leería
    # rutas vacías (y peor, las crearía). Es un rename, no toca una sola fila.
    if not mudar_a_database(args.dry_run):
        print("\nAbortado en la mudanza. No se movió nada ni se tocó ninguna DB.")
        return 1

    if not diagnostico():
        print("\nAbortado en el diagnóstico. No se tocó ninguna DB.")
        return 1

    copia_de_seguridad(args.dry_run)

    pasos = (mudar_a_inventarios,
             migraciones_de_schema, migrar_fotos_a_disco, retirar_datos_sensibles,
             lambda dry: limpiar_sobras(dry, args.limpiar))
    for paso in pasos:
        if not paso(args.dry_run):
            print("\n" + "=" * 70)
            print("ACTUALIZACIÓN INCOMPLETA — revisá el mensaje de arriba.")
            print("Las copias .pre-actualizacion-* quedaron intactas.")
            print("=" * 70)
            return 1

    if AVISOS:
        print("\n" + "-" * 70)
        print("AVISOS (no frenan nada, pero conviene mirarlos):")
        for aviso in AVISOS:
            print(f"  · {aviso}")
        print("-" * 70)

    print("\n" + "=" * 70)
    if args.dry_run:
        print("DRY-RUN terminado. Volvé a correrlo sin --dry-run para aplicar.")
    else:
        print("LISTO. Último paso: Reload del web app en el panel del hosting.")
        print("Los respaldos rotativos quedan en backups/ y las copias de esta corrida")
        print("en *.pre-actualizacion-*; borralas a mano cuando verifiques que anda.")
    print("=" * 70)
    return 0


if __name__ == '__main__':
    sys.exit(main())
