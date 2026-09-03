#!/usr/bin/env python3
"""Pone al día una instalación vieja de AppMitre — ejecutar en la consola del hosting:

    python actualizar.py --dry-run    # solo informa: no escribe nada
    python actualizar.py              # aplica

Existe porque no todo lo que cambió en las DBs entra por el hook `migrar()` de cada área.
Los `ALTER` aditivos sí (los corre `crud.init_db` sola en cada arranque), pero dos
migraciones **cruzan las dos DBs** y por eso no pueden vivir adentro de un área — ninguna
importa a la otra (ver CLAUDE.md, criterio de capas):

  1. `hitos` / `personas` / `persona_hitos` se mudaron de `gestion.db` a `historia.db`.
  2. La entidad `proyectos` se eliminó: sus filas son hoy hitos con 'Proyecto' en
     `etiquetas`, y viven en la otra DB.
  3. Gestión dejó de ser UN inventario y pasó a ser varios, uno por archivo: `recursos` y
     sus tres tablas se van de `gestion.db` a `inventarios/<slug>.db`, y los permisos
     `gestion.*` que había en `accesos.db` pasan a llevar el ámbito de ese inventario.

En el equipo de desarrollo eso se corrió una vez con un script de un solo uso y se borró;
una instalación que venga de un deploy anterior nunca lo vio. Sin esto, un `git pull` deja
esas filas huérfanas: no se pierden, pero dejan de aparecer en la web.

Es idempotente: cada paso mira el estado real y se saltea solo si ya está hecho. Correrlo
dos veces no rompe nada.
"""

import argparse
import os
import sqlite3
import sys

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)

# El destino es la consola del hosting (Linux, UTF-8), pero esto también se corre en
# Windows para probarlo, donde la consola es cp1252 y las flechas/tildes revientan el
# print. Que un carácter no mapeable salga como '?' es mucho mejor que abortar a mitad
# de una migración por un UnicodeEncodeError.
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(errors='replace')

import accesos
import gestion
import historia
import agente
import salidas
import respaldos
from config import ahora  # el reloj de la escuela; nunca datetime.now() (ver crud-motor.md)
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
# Paso 0 — diagnóstico
# ---------------------------------------------------------------------------

def diagnostico():
    """Informa qué hay instalado. Devuelve False si algo impide seguir."""
    print("=" * 70)
    print("DIAGNÓSTICO")
    print("=" * 70)
    print(f"Python {sys.version.split()[0]}  ·  SQLite {sqlite3.sqlite_version}")

    for ruta in (gestion.DB_PATH, historia.DB_PATH, salidas.DB_PATH,
                 agente_registro.DB_PATH):
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

    for fila in (gestion.listar_inventarios() if os.path.exists(gestion.DB_PATH)
                 and 'inventarios' in _tablas_de(gestion.DB_PATH) else []):
        marca = ' · SIN CLAVE' if fila['sin_clave'] else ''
        print(f"\ninventarios/{fila['slug']}.db: {fila['total']} recursos{marca}")

    escuela = os.path.join(RAIZ, 'horarios', 'escuela.db')
    print(f"\nhorarios/escuela.db: {'presente' if os.path.exists(escuela) else 'ausente'} "
          "(se regenera desde Google Sheets con POST /horarios/api/actualizar, no se toca acá)")

    # El único bloqueo posible: la migración destructiva de `drive_url` necesita un SQLite
    # que sepa DROP COLUMN. Avisar acá y no en medio de un traceback del servidor web.
    if sqlite3.sqlite_version_info < SQLITE_MINIMO_DROP_COLUMN:
        pendiente = False
        for ruta, tablas in ((gestion.DB_PATH, ('recursos',)),
                             (historia.DB_PATH, ('hitos', 'personas'))):
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
            print("    import de app.py. Hay que poner un guard en gestion.migrar() e")
            print("    historia.migrar() antes de subir esto.")
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
    for ruta in (gestion.DB_PATH, historia.DB_PATH, accesos.DB_PATH, salidas.DB_PATH,
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
# Paso 2 — hitos/personas: de gestion.db a historia.db
# ---------------------------------------------------------------------------

# Tablas que se mudaron, en orden: las personas antes que la M2M que las referencia.
TABLAS_MUDADAS = ('hitos', 'personas', 'persona_hitos')


def _copiar_filas(origen, destino, tabla):
    """Copia `tabla` de una DB a la otra conservando los ids, fila por fila.

    Sólo las columnas que existen en las dos: la tabla vieja trae `drive_url`, que en el
    schema nuevo ya no está. Fila por fila y no `executemany` para poder decir cuál falló
    si choca contra un UNIQUE (el de `personas.nombre_norm` es el candidato real).
    """
    comunes = set(_columnas(origen, tabla))
    cols = [c for c in _columnas(destino, tabla) if c in comunes]
    marcadores = ', '.join('?' * len(cols))
    sql = f"INSERT INTO {tabla} ({', '.join(cols)}) VALUES ({marcadores})"

    copiadas, rechazadas = 0, []
    for fila in origen.execute(f"SELECT {', '.join(cols)} FROM {tabla}").fetchall():
        valores = list(fila)
        # `personas.nombre_norm` tiene un UNIQUE encima y es la identidad de la fila. Si
        # viene vacía de una DB muy vieja, recalcularla con la regla del área.
        if tabla == 'personas' and 'nombre_norm' in cols and not valores[cols.index('nombre_norm')]:
            valores[cols.index('nombre_norm')] = historia.clave_persona(
                valores[cols.index('nombre')])
        try:
            destino.execute(sql, valores)
            copiadas += 1
        except sqlite3.IntegrityError as e:
            etiqueta = valores[cols.index('nombre')] if 'nombre' in cols else (
                valores[cols.index('titulo')] if 'titulo' in cols else str(valores))
            rechazadas.append(f"{etiqueta} ({e})")
    return copiadas, rechazadas


def mudar_a_historia(dry):
    """Mueve hitos/personas/persona_hitos a historia.db si todavía están en gestion.db."""
    print("\n" + "=" * 70)
    print("PASO 2 · hitos y personas → historia.db")
    print("=" * 70)

    con_g = _conectar(gestion.DB_PATH) if os.path.exists(gestion.DB_PATH) else None
    if con_g is None or 'hitos' not in _tablas(con_g):
        if con_g:
            con_g.close()
        print("  · Nada que mudar: gestion.db ya no tiene `hitos` (instalación al día).")
        return True

    try:
        pendientes = {t: _filas(con_g, t) for t in TABLAS_MUDADAS if t in _tablas(con_g)}
        print("  Encontrado en gestion.db: " +
              ", ".join(f"{t} ({n})" for t, n in pendientes.items()))

        # Caso típico de una instalación que ya corrió el código post-split: las tablas
        # quedaron físicamente en gestion.db pero vacías, porque el área dejó de escribir
        # ahí antes de que hubiera datos. No hay nada que mudar; las borra el paso 5.
        if not any(pendientes.values()):
            print("  · Están todas vacías: no hay datos que mudar (las elimina el paso 5).")
            return True

        con_h = _conectar(historia.DB_PATH)
        try:
            con_h.executescript(historia.SCHEMA)  # crea las tablas destino si faltan

            # Las dos con datos es ambiguo (¿cuál manda? ¿los ids chocan?). Antes que
            # elegir por el usuario, frenar: la copia de seguridad ya está hecha.
            if _filas(con_h, 'hitos') or _filas(con_h, 'personas'):
                print("  ✗ historia.db YA tiene datos y gestion.db también. No se toca nada:")
                print("    hay que decidir a mano cuál de las dos manda.")
                return False

            if dry:
                print("  [dry-run] copiaría esas filas a historia.db y las borraría de gestion.db")
                return True

            problemas = []
            for tabla, esperadas in pendientes.items():
                copiadas, rechazadas = _copiar_filas(con_g, con_h, tabla)
                print(f"    {tabla}: {copiadas}/{esperadas} copiadas")
                for r in rechazadas:
                    print(f"      ✗ rechazada: {r}")
                problemas.extend(rechazadas)
            con_h.commit()

            # El origen se borra sólo si TODO llegó. Ante la duda quedan las dos copias:
            # nada se pierde, sobra.
            if problemas:
                print("  ✗ Quedaron filas sin copiar — NO se borran las tablas de gestion.db.")
                return False
            for tabla in reversed(TABLAS_MUDADAS):
                if tabla in pendientes:
                    con_g.execute(f"DROP TABLE {tabla}")
            con_g.commit()
            print("  ✓ Mudanza completa; las tablas viejas se eliminaron de gestion.db.")
            return True
        finally:
            con_h.close()
    finally:
        con_g.close()


# ---------------------------------------------------------------------------
# Paso 3 — proyectos → hitos
# ---------------------------------------------------------------------------

TABLAS_PROYECTO = ('persona_proyectos', 'proyecto_recursos', 'proyectos')


def migrar_proyectos(dry):
    """Convierte cada fila de `proyectos` (gestion.db) en un hito de historia.db.

    Mapeo (el mismo que se aplicó en desarrollo, ver dev-log/CHANGELOG.md 2026-08-10):
    `nombre`→`titulo`, `participantes`→`protagonistas`, `'Proyecto'` en `etiquetas`, y el
    `estado` anexado a `descripcion` porque los hitos no tienen esa columna.

    `proyecto_recursos` cruzaba a la otra DB y no puede sobrevivir como relación — esos
    vínculos se anexan a la descripción en texto para no perder el dato.
    """
    print("\n" + "=" * 70)
    print("PASO 3 · proyectos → hitos")
    print("=" * 70)

    con_g = _conectar(gestion.DB_PATH) if os.path.exists(gestion.DB_PATH) else None
    if con_g is None or 'proyectos' not in _tablas(con_g):
        if con_g:
            con_g.close()
        print("  · Nada que migrar: no existe la tabla `proyectos`.")
        return True

    try:
        tablas_g = _tablas(con_g)
        proyectos = con_g.execute("SELECT * FROM proyectos ORDER BY id").fetchall()
        print(f"  Encontrados {len(proyectos)} proyecto(s).")
        if not proyectos:
            if not dry:
                for tabla in TABLAS_PROYECTO:
                    if tabla in tablas_g:
                        con_g.execute(f"DROP TABLE {tabla}")
                con_g.commit()
                print("  ✓ Tablas vacías eliminadas.")
            return True

        con_h = _conectar(historia.DB_PATH)
        try:
            con_h.executescript(historia.SCHEMA)

            for p in proyectos:
                partes = [p['descripcion'] or '']
                if p['estado']:
                    partes.append(f"Estado del proyecto al migrarlo: {p['estado']}.")
                if 'proyecto_recursos' in tablas_g:
                    usados = [f['nombre'] for f in con_g.execute(
                        "SELECT r.nombre FROM recursos r JOIN proyecto_recursos pr "
                        "ON pr.recurso_id = r.id WHERE pr.proyecto_id = ? "
                        "ORDER BY r.nombre COLLATE NOCASE", (p['id'],)).fetchall()]
                    if usados:
                        partes.append("Recursos que usaba: " + ", ".join(usados) + ".")
                descripcion = "\n\n".join(t for t in partes if t)

                vinculos = 0
                if 'persona_proyectos' in tablas_g:
                    vinculos = con_g.execute(
                        "SELECT COUNT(*) FROM persona_proyectos WHERE proyecto_id = ?",
                        (p['id'],)).fetchone()[0]

                if dry:
                    print(f"    [dry-run] '{p['nombre']}' → hito "
                          f"(etiqueta 'Proyecto', {vinculos} persona(s) vinculada(s))")
                    continue

                cur = con_h.execute(
                    "INSERT INTO hitos (titulo, descripcion, fecha, tipo, nivel, etiquetas, "
                    "protagonistas, fotos) VALUES (?,?,?,?,?,?,?,?)",
                    (p['nombre'], descripcion, p['fecha'] or '', '', 'Básico', 'Proyecto',
                     p['participantes'] or '', '[]'))
                hito_id = cur.lastrowid

                # Los ids de persona se conservaron en la mudanza del paso 2, así que los de
                # persona_proyectos siguen apuntando a la persona correcta. Igual se verifica
                # una por una: si la instalación mudó las personas por otro camino, los ids
                # pueden no coincidir, y un vínculo a una persona inexistente ensucia la ficha
                # del hito sin que nadie lo note.
                huerfanos = []
                if 'persona_proyectos' in tablas_g:
                    for f in con_g.execute(
                            "SELECT persona_id FROM persona_proyectos WHERE proyecto_id = ?",
                            (p['id'],)).fetchall():
                        existe = con_h.execute("SELECT 1 FROM personas WHERE id = ?",
                                               (f['persona_id'],)).fetchone()
                        if existe:
                            con_h.execute("INSERT OR IGNORE INTO persona_hitos "
                                          "(persona_id, hito_id) VALUES (?, ?)",
                                          (f['persona_id'], hito_id))
                        else:
                            huerfanos.append(f['persona_id'])
                print(f"    ✓ '{p['nombre']}' → hito #{hito_id} "
                      f"({vinculos - len(huerfanos)} vínculo(s))")
                if huerfanos:
                    print(f"      ! {len(huerfanos)} vínculo(s) a persona(s) inexistente(s) "
                          f"(ids {huerfanos}) — se descartan.")
                    AVISOS.append(f"El hito #{hito_id} ('{p['nombre']}') perdió {len(huerfanos)} "
                                  f"vínculo(s) a personas que no están en historia.db.")

            if dry:
                return True
            con_h.commit()

            for tabla in TABLAS_PROYECTO:
                if tabla in tablas_g:
                    con_g.execute(f"DROP TABLE {tabla}")
            con_g.commit()
            print("  ✓ Migración completa; las tablas de proyectos se eliminaron.")
            return True
        finally:
            con_h.close()
    finally:
        con_g.close()


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
        print("  [dry-run] correría gestion.init_db(), historia.init_db(), agente.init_db(),")
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
                         ('historia', historia.init_db),
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
# Paso 5 — limpieza de sobras (tablas y columnas que el código ya no declara)
# ---------------------------------------------------------------------------

# Qué SQL describe a cada DB. `gestion.db` tiene dos dueños: el REGISTRO de inventarios y
# el asistente, que guarda ahí sus tablas de auditoría y sesión. Sin sumar las dos, la
# limpieza se comería `agente_log` y compañía por creerlas sobras. Ojo: desde la mudanza,
# `gestion.SCHEMA` NO describe gestion.db sino cada `inventarios/<slug>.db`.
DUENOS_FIJOS = (
    (lambda: gestion.DB_PATH, lambda: (gestion.SCHEMA_REGISTRO, agente_db.SCHEMA)),
    (lambda: historia.DB_PATH, lambda: (historia.SCHEMA,)),
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
        (lambda slug=f['slug']: os.path.join(gestion.DIR_INVENTARIOS, f'{slug}.db'),
         lambda: (gestion.SCHEMA,))
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

    if not diagnostico():
        print("\nAbortado en el diagnóstico. No se tocó ninguna DB.")
        return 1

    copia_de_seguridad(args.dry_run)

    pasos = (mudar_a_historia, migrar_proyectos, mudar_a_inventarios,
             migraciones_de_schema, lambda dry: limpiar_sobras(dry, args.limpiar))
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
