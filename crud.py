"""Motor CRUD genérico — capa 1.

Conoce el *concepto* de entidad (una config declarativa, un slug, relaciones M2M) pero
**ninguna entidad concreta**: no sabe qué es un recurso ni un hito. Por eso **no importa
`gestion` ni `historia`** — las recibe como argumento (`area`). Esa es la regla que evita
el import circular y la que mantiene legible el criterio de pertenencia:

    capa 2 (gestion, historia)  ->  capa 1 (crud)  ->  capa 0 (texto, respaldos, config)

Un "área" es simplemente un módulo que expone lo de abajo. Todo lo que nombre una tabla
concreta entra por un **hook opcional**, nunca por un `if slug == '...'` acá adentro.

    OBLIGATORIO
      DB_PATH          ruta al archivo .db
      PREFIJO_BACKUP   prefijo de sus respaldos ('gestion' -> backups/gestion-*.db)
      TABLA_TESTIGO    tabla que se mira para saber si la DB "tiene datos"
      ENTIDADES        {slug: cfg}  — ver abajo
      SCHEMA           script SQL de creación (idempotente, CREATE TABLE IF NOT EXISTS)
      LIMPIEZA_M2M     {slug: [(tabla, columna), ...]} a limpiar al eliminar
      PERMISOS         [(clave, etiqueta, verbo)] que declara al catálogo de `accesos`
      GRUPO_PERMISOS   título bajo el que se agrupan en el panel de accesos
      PERMISO_LECTURA  el que hace falta para ver cualquier cosa del área
      PERMISO_ESCRITURA  el que piden nuevo/editar/eliminar/fotos

    HOOKS OPCIONALES (se leen con getattr; si no están, no pasa nada)
      migrar(cur)                     ALTERs aditivos para DBs viejas
      seed(cur)                       datos de ejemplo en instalación nueva
      secciones_detalle(slug, id, cur)  relaciones a mostrar en el detalle
      resultados_extra_busqueda(slug, q, cur)  filas extra para el listado cuando hay `q`
      derivados(slug, valores)        columnas calculadas al guardar (no van en 'campos')
      valores_iniciales(slug)         defaults del form de alta
      extras_template(vista, slug)    kwargs extra para render_template
      tarjetas_extra(cur)             tarjetas del home que no salen de ENTIDADES
      contexto_extra()                claves extra del context processor
      NAV_EXTRA                       [(slug, label)] extra para la nav
      ERROR_DUPLICADO                 {slug: mensaje} cuando un UNIQUE rechaza el guardado
      api_serializar(slug, filas, cur)  completa las filas que devuelve la API JSON (/app)
      api_meta()                      claves extra del GET /meta de la API

Cada cfg de ENTIDADES: tabla, singular, plural, descripcion, campos, columnas,
relaciones y (opcional) campo_nombre y permiso.
"""

import base64
import json
import os
import sqlite3

from flask import abort, jsonify, make_response, redirect, render_template, request, url_for

import accesos
import respaldos
import texto
from config import ESCUELA_NOMBRE, ESCUELA_LOGO, ESCUELA_VERSION, ahora


# ---------------------------------------------------------------------------
# Conexión y config declarativa
# ---------------------------------------------------------------------------

def conectar(area):
    con = sqlite3.connect(area.DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def cfg(area, slug):
    """Config de un slug, o 404 si no existe en esta área."""
    if slug not in area.ENTIDADES:
        abort(404)
    return area.ENTIDADES[slug]


def campo_nombre(cfg_ent):
    """Columna que hace de nombre visible de la entidad.

    Casi todas usan 'nombre'; `historia.hitos` la llama 'titulo'. El mecanismo existe para
    que el resto del sistema no tenga que enterarse (ver `select`).
    """
    return cfg_ent.get('campo_nombre', 'nombre')


def campo_alias(cfg_ent):
    """Columna de términos alternativos para la búsqueda, si la entidad la declaró.

    No necesariamente sinónimos estrictos ("zapatilla" y "alargue" son cosas distintas
    que se confunden) — de ahí el nombre `alias` y no `sinonimos`. `None` por defecto: hoy
    solo la declara `gestion.recursos`. Mismo criterio que `campo_nombre` — capa 1 no sabe
    qué es un alias, solo que hay una columna extra que entra en la segunda pasada de
    `buscar_entidad`/`lista()` y en el whitelist de `guardar_entidad`, sin pasar por
    `cfg.campos` (que es lo que la mantiene fuera del form web y de la ficha de
    confirmación del agente).
    """
    return cfg_ent.get('campo_alias')


def permiso_entidad(area, slug):
    """Permiso EXTRA que pide UNA entidad, si su área lo declaró en su cfg (`permiso`).

    Es lo que permite esconder una sola entidad sin partir el área en dos: `/historia`
    sigue siendo una para todo el mundo, pero `personas` pide `historia.personas`, que
    sólo tiene el admin. Capa 1 conoce la clave `permiso`; CUÁL permiso es lo dice el
    área, igual que con `campo_nombre` o `PERMISO_ESCRITURA`.

    Sin la clave no hay permiso extra: la entidad se ve con el permiso base del área.
    """
    return area.ENTIDADES.get(slug, {}).get('permiso')


def ve_entidad(area, slug):
    """¿El acceso de ESTE request puede ver `slug`?"""
    permiso = permiso_entidad(area, slug)
    return not permiso or accesos.puede(permiso)


def relaciones_visibles(area, cfg_ent):
    """Las relaciones M2M del formulario cuya entidad ajena este acceso puede ver.

    Las que no, quedan afuera del form Y de `_guardar_form`: si sólo desaparecieran del
    HTML, guardar un hito desde un acceso sin `historia.personas` borraría sus vínculos
    con personas, porque el form postea la lista entera de cada relación.
    """
    return [rel for rel in cfg_ent['relaciones'] if ve_entidad(area, rel['slug_ajeno'])]


def select(cfg_ent):
    """SELECT que SIEMPRE expone una columna `nombre`, se llame como se llame en la tabla.

    Todo lo que consume filas (templates genéricos, búsqueda, el agente) lee
    `fila['nombre']`. Con el alias, una entidad puede tener su columna con otro nombre sin
    que ninguno de esos consumidores se entere.
    """
    campo = campo_nombre(cfg_ent)
    alias = '' if campo == 'nombre' else f", {campo} AS nombre"
    return f"SELECT *{alias} FROM {cfg_ent['tabla']}"


def _hook(area, nombre, default=None):
    return getattr(area, nombre, default)


# ---------------------------------------------------------------------------
# Creación / migración de la DB
# ---------------------------------------------------------------------------

def init_db(area):
    """Crea las tablas si no existen, migra columnas nuevas y siembra la primera vez.

    Respalda antes de tocar nada (ver `respaldos.respaldar`).
    """
    respaldos.respaldar(area.DB_PATH, area.PREFIJO_BACKUP, area.TABLA_TESTIGO)

    con = conectar(area)
    cur = con.cursor()
    cur.executescript(area.SCHEMA)

    migrar = _hook(area, 'migrar')
    if migrar:
        migrar(cur)
    instalar_versionado(area, cur)

    sembrar = _hook(area, 'seed')
    if cur.execute(f"SELECT COUNT(*) FROM {area.TABLA_TESTIGO}").fetchone()[0] == 0:
        # Una DB vacía es ambigua: puede ser una instalación nueva o datos perdidos.
        # Los respaldos desempatan — si existen, esto ya estuvo cargado alguna vez y
        # seguir de largo taparía la pérdida en silencio (que es exactamente lo que pasó
        # el 2026-08-08). Ante la duda, fallar ruidoso.
        previos = respaldos.listar(area.PREFIJO_BACKUP)
        if previos and os.environ.get('GESTION_SEED') != '1':
            nombre_db = os.path.basename(area.DB_PATH)
            ultimo = previos[-1]
            con.close()
            aviso = ("NO se cargaron los datos de ejemplo." if sembrar
                     else "NO se cargó nada.")
            raise RuntimeError(
                f"{nombre_db} está vacía pero hay {len(previos)} respaldo(s) en "
                f"{respaldos.BACKUP_DIR}.\n"
                f"Probablemente se perdió el archivo — {aviso}\n\n"
                f"Para restaurar el más reciente:\n"
                f"    copy \"{ultimo}\" \"{area.DB_PATH}\"\n\n"
                f"Si de verdad querés empezar de cero:\n"
                f"    GESTION_SEED=1 python app.py"
            )
        if sembrar:
            sembrar(cur)
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# Versionado: lo que usa la app (/app) para no pisar cambios ajenos ni re-bajar datos
# ---------------------------------------------------------------------------
# Dos contadores, los dos mantenidos por TRIGGERS de SQLite y no por el código Python:
#
#   <tabla>.version   uno por fila. Sube con cualquier cambio de la fila o de sus tablas
#                     hijas (las de LIMPIEZA_M2M: unidades, ítems de kit, vínculos M2M).
#                     La app lo manda al guardar; si no coincide, alguien cambió la fila
#                     mientras se editaba y el guardado contesta 409 en vez de pisar.
#   _revision.n       uno por DB. Sube con cualquier alta, baja o cambio. Es el ETag de
#                     los listados: si no cambió, el servidor contesta 304 sin datos.
#
# Por qué triggers: a estas tablas escriben el motor, las rutas propias de cada área, el
# asistente (agente/tools) y scripts sueltos. Un contador mantenido a mano en Python se
# olvidaría en alguno de esos caminos; el trigger no se puede saltear.

def _tablas_hijas(area, slug):
    return list(getattr(area, 'LIMPIEZA_M2M', {}).get(slug, []))


def instalar_versionado(area, cur):
    """Columna `version` + triggers. Idempotente: los triggers se recrean en cada
    arranque, así un cambio acá (o en LIMPIEZA_M2M) entra sin migración aparte.

    Un módulo que usa `init_db` sin declarar ENTIDADES (estudiantes.py: sólo quiere el
    respaldo y la guarda anti-pérdida) no tiene nada que versionar."""
    if not getattr(area, 'ENTIDADES', None):
        return
    cur.execute("CREATE TABLE IF NOT EXISTS _revision "
                "(id INTEGER PRIMARY KEY CHECK (id = 1), n INTEGER NOT NULL)")
    cur.execute("INSERT OR IGNORE INTO _revision (id, n) VALUES (1, 0)")
    sube_revision = "UPDATE _revision SET n = n + 1 WHERE id = 1;"

    for slug, cfg_ent in area.ENTIDADES.items():
        tabla = cfg_ent['tabla']
        columnas = {c[1] for c in cur.execute(f"PRAGMA table_info({tabla})").fetchall()}
        if 'version' not in columnas:
            cur.execute(f"ALTER TABLE {tabla} ADD COLUMN version INTEGER NOT NULL DEFAULT 1")

        cur.executescript(f"""
            DROP TRIGGER IF EXISTS _v_{tabla}_upd;
            DROP TRIGGER IF EXISTS _v_{tabla}_ins;
            DROP TRIGGER IF EXISTS _v_{tabla}_del;
            CREATE TRIGGER _v_{tabla}_upd AFTER UPDATE ON {tabla}
            WHEN NEW.version = OLD.version
            BEGIN
                UPDATE {tabla} SET version = OLD.version + 1 WHERE id = NEW.id;
                {sube_revision}
            END;
            CREATE TRIGGER _v_{tabla}_ins AFTER INSERT ON {tabla}
            BEGIN {sube_revision} END;
            CREATE TRIGGER _v_{tabla}_del AFTER DELETE ON {tabla}
            BEGIN {sube_revision} END;
        """)

        # Un cambio en una tabla hija es un cambio de la fila madre: mover una unidad de
        # lugar cambia lo que muestra la ficha del recurso.
        for hija, col in _tablas_hijas(area, slug):
            for evento, ref in (('INSERT', 'NEW'), ('UPDATE', 'NEW'), ('DELETE', 'OLD')):
                nombre = f"_v_{hija}_{col}_{evento.lower()}"
                cur.executescript(f"""
                    DROP TRIGGER IF EXISTS {nombre};
                    CREATE TRIGGER {nombre} AFTER {evento} ON {hija}
                    BEGIN
                        UPDATE {tabla} SET version = version + 1 WHERE id = {ref}.{col};
                        {sube_revision}
                    END;
                """)


def revision(con):
    """Contador de cambios de toda la DB (ver `instalar_versionado`)."""
    fila = con.execute("SELECT n FROM _revision WHERE id = 1").fetchone()
    return fila[0] if fila else 0


# ---------------------------------------------------------------------------
# Lectura y escritura sin Flask request (lo que usa el agente)
# ---------------------------------------------------------------------------

def buscar_entidad(area, slug, query, con=None):
    """Búsqueda de entidades que no depende de Flask request.
    Devuelve lista de dicts {id, nombre, descripcion, ...} ya filtrados y ordenados."""
    if slug not in area.ENTIDADES:
        return []
    cfg_ent = area.ENTIDADES[slug]

    debe_cerrar = con is None
    if con is None:
        con = conectar(area)
    cur = con.cursor()

    filas = cur.execute(f"{select(cfg_ent)} ORDER BY nombre COLLATE NOCASE").fetchall()
    if debe_cerrar:
        con.close()

    if not query:
        return [dict(f) for f in filas]

    q_norm = texto.norm(query)
    campo_al = campo_alias(cfg_ent)
    puntuadas, por_alias = [], []
    for fila in filas:
        puntaje = texto.puntaje_busqueda(q_norm, fila['nombre'], fila['descripcion'])
        if puntaje is not None:
            puntuadas.append((puntaje, fila))
        elif campo_al:
            # Segunda pasada: solo si NO matcheó por nombre/descripcion. Va a una lista
            # aparte que se concatena al final, nunca mezclada con los matches normales
            # (ver agent_docs/gestion-conocimiento.md).
            puntaje_al = texto.puntaje_busqueda(q_norm, fila[campo_al])
            if puntaje_al is not None:
                por_alias.append((puntaje_al, fila))
    puntuadas.sort(key=lambda par: (-par[0], texto.norm(par[1]['nombre'])))
    por_alias.sort(key=lambda par: (-par[0], texto.norm(par[1]['nombre'])))
    resultado = [dict(fila) for _, fila in puntuadas]
    for _, fila in por_alias:
        d = dict(fila)
        d['_via_alias'] = True
        resultado.append(d)
    return resultado


def guardar_entidad(area, slug, campos_dict, id=None, con=None):
    """Alta o edición a partir de un dict (no lee request.form).
    Devuelve el id creado o actualizado, o None si hubo error."""
    if slug not in area.ENTIDADES:
        return None
    cfg_ent = area.ENTIDADES[slug]

    debe_cerrar = con is None
    if con is None:
        con = conectar(area)
    cur = con.cursor()

    try:
        nombres = [c['nombre'] for c in cfg_ent['campos']]
        # El campo de alias (si la entidad lo declaró) se escribe sin estar en 'campos':
        # es lo que lo mantiene fuera del form web y de la ficha del agente (ver
        # campo_alias()). Solo entra si vino explícito en campos_dict.
        campo_al = campo_alias(cfg_ent)
        if campo_al and campo_al not in nombres and campo_al in campos_dict:
            nombres = nombres + [campo_al]
        valores = {n: str(campos_dict.get(n, '')).strip() for n in nombres}

        derivados = _hook(area, 'derivados')
        if derivados:
            valores.update(derivados(slug, valores))

        cols = list(valores)
        datos = [valores[c] for c in cols]
        if id is None:
            placeholders = ','.join('?' * len(cols))
            cur.execute(
                f"INSERT INTO {cfg_ent['tabla']} ({','.join(cols)}) VALUES ({placeholders})",
                datos)
            id = cur.lastrowid
        else:
            sets = ','.join(f"{c} = ?" for c in cols)
            cur.execute(f"UPDATE {cfg_ent['tabla']} SET {sets} WHERE id = ?", datos + [id])

        # Relaciones M2M: sólo se tocan las que vengan explícitas en campos_dict.
        for rel in cfg_ent['relaciones']:
            campo = rel['campo']
            if campo in campos_dict:
                cur.execute(f"DELETE FROM {rel['tabla']} WHERE {rel['col_propia']} = ?", (id,))
                for rid_str in (campos_dict[campo] if isinstance(campos_dict[campo], list) else []):
                    try:
                        rid = int(rid_str)
                        cur.execute(
                            f"INSERT OR IGNORE INTO {rel['tabla']} "
                            f"({rel['col_propia']}, {rel['col_ajena']}) VALUES (?,?)",
                            (id, rid),
                        )
                    except (ValueError, TypeError):
                        pass

        con.commit()
        if debe_cerrar:
            con.close()
        return id
    except Exception:
        if debe_cerrar:
            con.close()
        return None


def snapshot_entidad(area, slug, id, con=None):
    """Foto de una fila + sus relaciones M2M, para auditar antes de borrar.
    Devuelve dict con 'fila', 'relaciones' (slug -> [ids]) y 'm2m' (filas crudas)."""
    if slug not in area.ENTIDADES:
        return None
    cfg_ent = area.ENTIDADES[slug]

    debe_cerrar = con is None
    if con is None:
        con = conectar(area)
    cur = con.cursor()

    fila = cur.execute(f"{select(cfg_ent)} WHERE id = ?", (id,)).fetchone()
    if fila is None:
        if debe_cerrar:
            con.close()
        return None

    relaciones = {}
    for rel in cfg_ent['relaciones']:
        ids = [r[0] for r in cur.execute(
            f"SELECT {rel['col_ajena']} FROM {rel['tabla']} WHERE {rel['col_propia']} = ?",
            (id,)).fetchall()]
        relaciones[rel['slug_ajeno']] = ids

    # Filas M2M crudas que un borrado destruiría. No alcanza con 'relaciones': esa recorre
    # cfg['relaciones'] (dirección "hacia afuera"), y para 'recursos' está vacía — pero
    # LIMPIEZA_M2M sí borra sus 3 tablas inversas. Sin esto el snapshot decía relaciones={}
    # y un borrado erróneo de un recurso no se podía restaurar completo.
    m2m = {}
    for tabla, columna in area.LIMPIEZA_M2M.get(slug, []):
        filas_m2m = cur.execute(f"SELECT * FROM {tabla} WHERE {columna} = ?", (id,)).fetchall()
        if filas_m2m:
            m2m[tabla] = [dict(f) for f in filas_m2m]

    if debe_cerrar:
        con.close()
    return {'fila': dict(fila), 'relaciones': relaciones, 'm2m': m2m}


def agregar_relacion_m2m(area, tabla, col_propia, col_ajena, id_propio, id_ajeno, con=None):
    """Agregar una fila a una tabla M2M."""
    debe_cerrar = con is None
    if con is None:
        con = conectar(area)
    try:
        con.execute(f"INSERT OR IGNORE INTO {tabla} ({col_propia}, {col_ajena}) VALUES (?,?)",
                    (id_propio, id_ajeno))
        con.commit()
        return True
    except Exception:
        return False
    finally:
        if debe_cerrar:
            con.close()


def quitar_relacion_m2m(area, tabla, col_propia, col_ajena, id_propio, id_ajeno, con=None):
    """Quitar una fila de una tabla M2M."""
    debe_cerrar = con is None
    if con is None:
        con = conectar(area)
    try:
        con.execute(f"DELETE FROM {tabla} WHERE {col_propia} = ? AND {col_ajena} = ?",
                    (id_propio, id_ajeno))
        con.commit()
        return True
    except Exception:
        return False
    finally:
        if debe_cerrar:
            con.close()


def agregar_foto(area, slug, id, b64, tipo):
    """Agrega una foto ya en base64 a la galería de una entidad.

    Vive suelta y no dentro de `subir_foto` porque el agente también escribe la galería:
    cuando el alta de un recurso salió de una foto del chat, esa foto termina acá por el
    mismo camino que la que se sube desde el detalle (ver `agente.confirmar`).
    """
    cfg_ent = cfg(area, slug)
    con = conectar(area)
    cur = con.cursor()
    fila = cur.execute(f"SELECT fotos FROM {cfg_ent['tabla']} WHERE id = ?", (id,)).fetchone()
    if fila is None:
        con.close()
        return False
    fotos = json.loads(fila['fotos'] or '[]')
    fotos.append({'b64': b64, 'tipo': tipo, 'fecha': ahora().isoformat()})
    cur.execute(f"UPDATE {cfg_ent['tabla']} SET fotos = ? WHERE id = ?", (json.dumps(fotos), id))
    con.commit()
    con.close()
    return True


# ---------------------------------------------------------------------------
# Helpers de formulario
# ---------------------------------------------------------------------------

def _opciones_relaciones(area, relaciones, cur):
    """Opciones disponibles para cada relación M2M del formulario."""
    opciones = {}
    for rel in relaciones:
        cfg_ajeno = area.ENTIDADES[rel['slug_ajeno']]
        opciones[rel['campo']] = cur.execute(
            f"SELECT id, {campo_nombre(cfg_ajeno)} AS nombre FROM {cfg_ajeno['tabla']} "
            f"ORDER BY nombre COLLATE NOCASE").fetchall()
    return opciones


def _seleccion_relaciones(relaciones, id, cur):
    """IDs actualmente vinculados, por campo de relación."""
    seleccion = {}
    for rel in relaciones:
        filas = cur.execute(
            f"SELECT {rel['col_ajena']} FROM {rel['tabla']} WHERE {rel['col_propia']} = ?",
            (id,)).fetchall()
        seleccion[rel['campo']] = {f[0] for f in filas}
    return seleccion


def _guardar_form(area, slug, cfg_ent, cur, id=None):
    """Inserta o actualiza desde request.form y sincroniza las M2M. Devuelve el id."""
    nombres = [c['nombre'] for c in cfg_ent['campos']]
    valores = {n: request.form.get(n, '').strip() for n in nombres}
    seleccion = {rel['campo']: request.form.getlist(rel['campo'])
                 for rel in relaciones_visibles(area, cfg_ent)}
    return _guardar(area, slug, cfg_ent, cur, valores, seleccion, id)


def _guardar(area, slug, cfg_ent, cur, valores, seleccion, id=None):
    """Lo común al form web y a la API: `valores` {campo: texto} y `seleccion`
    {campo_rel: [ids]} con SOLO las relaciones visibles para este acceso."""
    derivados = _hook(area, 'derivados')
    if derivados:
        valores.update(derivados(slug, valores))

    cols = list(valores)
    datos = [valores[c] for c in cols]
    if id is None:
        placeholders = ','.join('?' * len(cols))
        cur.execute(f"INSERT INTO {cfg_ent['tabla']} ({','.join(cols)}) VALUES ({placeholders})",
                    datos)
        id = cur.lastrowid
    else:
        sets = ','.join(f"{c} = ?" for c in cols)
        cur.execute(f"UPDATE {cfg_ent['tabla']} SET {sets} WHERE id = ?", datos + [id])

    # Sólo las visibles: una relación que el form no mostró tampoco se pisa (ver
    # `relaciones_visibles`).
    for rel in relaciones_visibles(area, cfg_ent):
        if rel['campo'] not in seleccion:
            continue
        cur.execute(f"DELETE FROM {rel['tabla']} WHERE {rel['col_propia']} = ?", (id,))
        for rid in seleccion[rel['campo']]:
            try:
                rid = int(rid)
            except ValueError:
                continue
            cur.execute(
                f"INSERT OR IGNORE INTO {rel['tabla']} "
                f"({rel['col_propia']}, {rel['col_ajena']}) VALUES (?,?)",
                (id, rid),
            )
    return id


# El gate de sesión vive en `accesos.py` (capa 1, hermano de este archivo): dejó de ser
# "una clave y un booleano" para ser catálogo de permisos, perfiles, dispositivos y panel,
# que es un motor aparte. Las áreas llaman a `accesos.registrar_acceso(bp, permiso)`.


# ---------------------------------------------------------------------------
# Rutas genéricas
# ---------------------------------------------------------------------------

def contexto_base(bp, area):
    """Lo que todo template del área necesita. `area_nombre` y `base_template` son lo que
    permite que los templates de `templates/crud/` sirvan para cualquier área sin saber
    de cuál son."""
    nav = [(slug, e['plural']) for slug, e in area.ENTIDADES.items()
           if ve_entidad(area, slug)]
    nav += list(_hook(area, 'NAV_EXTRA', []))
    ctx = {
        'escuela_nombre': ESCUELA_NOMBRE,
        'escuela_logo': ESCUELA_LOGO,
        'escuela_version': ESCUELA_VERSION,
        'nav_entidades': nav,
        'area_nombre': bp.name,
        'base_template': f'{bp.name}/base.html',
        # Para que `lista.html`/`detalle.html` escondan los botones de escritura sin que
        # este archivo nombre ningún permiso: la clave la pone el área.
        'permiso_escritura': _hook(area, 'PERMISO_ESCRITURA'),
    }
    extra = _hook(area, 'contexto_extra')
    if extra:
        ctx.update(extra())
    return ctx


def registrar_rutas(bp, area):
    """Monta home / lista / nuevo / detalle / editar / eliminar / fotos sobre `bp`.

    Los endpoints y las carpetas de templates salen de `bp.name`, que ya coincide con el
    nombre de la carpeta en `templates/` — así esto no necesita configuración extra.
    """
    nombre = bp.name
    # Qué permiso pide una ruta que escribe. Lo nombra el área; este archivo sólo lo
    # pasa, igual que hace con `campo_nombre`.
    escritura = _hook(area, 'PERMISO_ESCRITURA')

    def _extras(vista, slug):
        hook = _hook(area, 'extras_template')
        return hook(vista, slug) if hook else {}

    @bp.context_processor
    def _contexto():
        return contexto_base(bp, area)

    @bp.before_request
    def _gate_entidad():
        """La entidad de la URL, si pide un permiso propio (ver `permiso_entidad`).

        Va acá y no en cada vista porque el slug está en la URL de TODAS: una sola puerta
        para lista, detalle, nuevo, editar, eliminar y las dos de fotos. Corre después del
        gate de sesión de `accesos.registrar_acceso`, que el área monta primero.
        """
        slug = (request.view_args or {}).get('slug')
        permiso = permiso_entidad(area, slug) if slug else None
        if permiso and not accesos.puede(permiso):
            return accesos.denegar(permiso)

    @bp.route('/')
    def home():
        con = conectar(area)
        cur = con.cursor()
        tarjetas = []
        for slug, e in area.ENTIDADES.items():
            if not ve_entidad(area, slug):
                continue
            total = cur.execute(f"SELECT COUNT(*) FROM {e['tabla']}").fetchone()[0]
            tarjetas.append({'slug': slug, 'plural': e['plural'], 'singular': e['singular'],
                             'descripcion': e['descripcion'], 'total': total})
        extra = _hook(area, 'tarjetas_extra')
        if extra:
            tarjetas.extend(extra(cur))
        con.close()
        return render_template(f'{nombre}/home.html', tarjetas=tarjetas, activo='home')

    @bp.route('/<slug>')
    def lista(slug):
        cfg_ent = cfg(area, slug)
        q = request.args.get('q', '').strip()
        con = conectar(area)
        cur = con.cursor()
        filas = cur.execute(f"{select(cfg_ent)} ORDER BY nombre COLLATE NOCASE").fetchall()
        campo_al = campo_alias(cfg_ent)
        via_alias = set()
        if q:
            # Búsqueda tolerante (ver texto.puntaje_busqueda): acentos/mayúsculas no
            # importan y se perdonan typos. Se filtra y ordena en Python — con esta
            # cantidad de filas el costo es despreciable frente a que "perdone".
            q_norm = texto.norm(q)
            puntuadas, por_alias = [], []
            for fila in filas:
                puntaje = texto.puntaje_busqueda(q_norm, fila['nombre'], fila['descripcion'])
                if puntaje is not None:
                    puntuadas.append((puntaje, fila))
                elif campo_al:
                    # Segunda pasada, solo si no matcheó por nombre/descripcion: los que
                    # entran acá se muestran al final, marcados aparte (ver
                    # agent_docs/gestion-conocimiento.md).
                    puntaje_al = texto.puntaje_busqueda(q_norm, fila[campo_al])
                    if puntaje_al is not None:
                        por_alias.append((puntaje_al, fila))
            puntuadas.sort(key=lambda par: (-par[0], texto.norm(par[1]['nombre'])))
            por_alias.sort(key=lambda par: (-par[0], texto.norm(par[1]['nombre'])))
            via_alias = {fila['id'] for _, fila in por_alias}
            filas = [fila for _, fila in puntuadas] + [fila for _, fila in por_alias]
        # Texto ya normalizado por fila, para el filtrado en vivo del navegador
        # (data-buscar). Incluye el alias cuando la entidad lo declara, para que el
        # filtrado en vivo (solo substring, sin fuzzy) también lo encuentre.
        def _texto_buscar(fila):
            base = f"{fila['nombre']} {fila['descripcion'] or ''}"
            if campo_al and fila[campo_al]:
                base += f" {fila[campo_al]}"
            return texto.norm(base)
        buscar = {fila['id']: _texto_buscar(fila) for fila in filas}
        # Filas que no son de esta entidad pero matchean la búsqueda (ej: sub-recursos de
        # un kit): el hook decide qué son, el motor sólo las reenvía a la plantilla.
        extra_filas = []
        if q:
            extra_hook = _hook(area, 'resultados_extra_busqueda')
            if extra_hook:
                extra_filas = extra_hook(slug, q, cur)
        con.close()
        return render_template(f'{nombre}/lista.html', cfg=cfg_ent, slug=slug, filas=filas,
                               q=q, activo=slug, buscar=buscar, via_alias=via_alias,
                               extra_filas=extra_filas, **_extras('lista', slug))

    @bp.route('/<slug>/nuevo', methods=['GET', 'POST'])
    @accesos.requiere(escritura)
    def nuevo(slug):
        cfg_ent = cfg(area, slug)
        con = conectar(area)
        cur = con.cursor()
        error = None
        if request.method == 'POST':
            if not request.form.get(campo_nombre(cfg_ent), '').strip():
                error = 'El nombre es obligatorio.'
            else:
                try:
                    id = _guardar_form(area, slug, cfg_ent, cur)
                except sqlite3.IntegrityError:
                    error = _hook(area, 'ERROR_DUPLICADO', {}).get(
                        slug, 'Ya existe un registro igual.')
                else:
                    con.commit()
                    con.close()
                    return redirect(url_for(f'{nombre}.detalle', slug=slug, id=id))
        relaciones = relaciones_visibles(area, cfg_ent)
        opciones = _opciones_relaciones(area, relaciones, cur)
        con.close()
        seleccion = {rel['campo']: {int(v) for v in request.form.getlist(rel['campo'])}
                     for rel in relaciones}
        # En el GET el form arranca con los defaults; en un POST fallido se respeta lo tipeado.
        iniciales = _hook(area, 'valores_iniciales')
        valores = request.form if request.method == 'POST' else (
            iniciales(slug) if iniciales else {})
        return render_template(f'{nombre}/form.html', cfg=cfg_ent, slug=slug, fila=None,
                               valores=valores, opciones=opciones, seleccion=seleccion,
                               relaciones=relaciones, error=error, activo=slug,
                               **_extras('nuevo', slug))

    @bp.route('/<slug>/<int:id>')
    def detalle(slug, id):
        cfg_ent = cfg(area, slug)
        con = conectar(area)
        cur = con.cursor()
        fila = cur.execute(f"{select(cfg_ent)} WHERE id = ?", (id,)).fetchone()
        if fila is None:
            con.close()
            abort(404)
        secciones_hook = _hook(area, 'secciones_detalle')
        secciones = secciones_hook(slug, id, cur) if secciones_hook else []
        # Una sección que apunta a una entidad con permiso propio no se muestra: la ficha
        # de un hito lista sus personas, y esos nombres son justamente lo que el permiso
        # esconde. Las que no apuntan a una entidad (gestion: "Por ubicación") pasan.
        secciones = [s for s in secciones if ve_entidad(area, s.get('slug'))]
        con.close()
        fila_dict = dict(fila)
        fila_dict['fotos'] = json.loads(fila_dict.get('fotos', '[]'))
        return render_template(f'{nombre}/detalle.html', cfg=cfg_ent, slug=slug,
                               fila=fila_dict, secciones=secciones, activo=slug,
                               **_extras('detalle', slug))

    @bp.route('/<slug>/<int:id>/editar', methods=['GET', 'POST'])
    @accesos.requiere(escritura)
    def editar(slug, id):
        cfg_ent = cfg(area, slug)
        con = conectar(area)
        cur = con.cursor()
        fila = cur.execute(f"{select(cfg_ent)} WHERE id = ?", (id,)).fetchone()
        if fila is None:
            con.close()
            abort(404)
        error = None
        if request.method == 'POST':
            if not request.form.get(campo_nombre(cfg_ent), '').strip():
                error = 'El nombre es obligatorio.'
            else:
                try:
                    _guardar_form(area, slug, cfg_ent, cur, id)
                except sqlite3.IntegrityError:
                    error = _hook(area, 'ERROR_DUPLICADO', {}).get(
                        slug, 'Ya existe un registro igual.')
                else:
                    con.commit()
                    con.close()
                    return redirect(url_for(f'{nombre}.detalle', slug=slug, id=id))
        relaciones = relaciones_visibles(area, cfg_ent)
        opciones = _opciones_relaciones(area, relaciones, cur)
        seleccion = _seleccion_relaciones(relaciones, id, cur)
        con.close()
        valores = request.form if request.method == 'POST' else fila
        return render_template(f'{nombre}/form.html', cfg=cfg_ent, slug=slug, fila=fila,
                               valores=valores, opciones=opciones, seleccion=seleccion,
                               relaciones=relaciones, error=error, activo=slug,
                               **_extras('editar', slug))

    @bp.route('/<slug>/<int:id>/eliminar', methods=['POST'])
    @accesos.requiere(escritura)
    def eliminar(slug, id):
        cfg_ent = cfg(area, slug)
        con = conectar(area)
        cur = con.cursor()
        cur.execute(f"DELETE FROM {cfg_ent['tabla']} WHERE id = ?", (id,))
        for tabla, columna in area.LIMPIEZA_M2M[slug]:
            cur.execute(f"DELETE FROM {tabla} WHERE {columna} = ?", (id,))
        con.commit()
        con.close()
        return redirect(url_for(f'{nombre}.lista', slug=slug))

    @bp.route('/<slug>/<int:id>/foto', methods=['POST'])
    @accesos.requiere(escritura)
    def subir_foto(slug, id):
        """Sube una foto, la convierte a base64 y la guarda en el JSON de fotos."""
        cfg(area, slug)  # 404 temprano si el slug no existe

        if 'file' not in request.files:
            return jsonify({'ok': False, 'error': 'No hay archivo'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'ok': False, 'error': 'Archivo vacío'}), 400

        if not file.content_type.startswith('image/'):
            return jsonify({'ok': False, 'error': 'Solo se aceptan imágenes'}), 400

        try:
            b64 = base64.b64encode(file.read()).decode('utf-8')
            if not agregar_foto(area, slug, id, b64, file.content_type):
                return jsonify({'ok': False, 'error': 'No existe el registro'}), 404
            return jsonify({'ok': True})
        except Exception as e:
            return jsonify({'ok': False, 'error': str(e)}), 500

    @bp.route('/<slug>/<int:id>/foto/<int:indice>/eliminar', methods=['POST'])
    @accesos.requiere(escritura)
    def eliminar_foto(slug, id, indice):
        """Borra una foto de la galería por su posición en el array JSON.

        Las fotos no tienen id propio (son objetos dentro de un array), así que la
        posición es la única referencia posible. Un índice fuera de rango no es error:
        se ignora y se vuelve a la ficha (pasa si dos pestañas borran a la vez).
        """
        cfg_ent = cfg(area, slug)
        con = conectar(area)
        cur = con.cursor()
        fila = cur.execute(f"SELECT fotos FROM {cfg_ent['tabla']} WHERE id = ?", (id,)).fetchone()
        if fila is None:
            con.close()
            abort(404)
        fotos = json.loads(fila['fotos'] or '[]')
        if 0 <= indice < len(fotos):
            fotos.pop(indice)
            cur.execute(f"UPDATE {cfg_ent['tabla']} SET fotos = ? WHERE id = ?",
                        (json.dumps(fotos), id))
            con.commit()
        con.close()
        return redirect(url_for(f'{nombre}.detalle', slug=slug, id=id))


# ---------------------------------------------------------------------------
# API JSON — lo que consume la app instalable (/app, carpeta frontend/)
# ---------------------------------------------------------------------------
# Mismas reglas que las rutas HTML de arriba (permisos, relaciones visibles, hooks), pero
# devolviendo datos. Convenciones, iguales para todas las áreas:
#
#   GET    /meta                    campos, relaciones y qué puede este acceso
#   GET    /<slug>                  todas las filas, ya serializadas. ETag = _revision.n
#   GET    /<slug>/<id>             una fila
#   POST   /<slug>                  alta        → 201 + fila
#   PUT    /<slug>/<id>             edición     → fila | 409 {actual} | 422 {errores}
#   DELETE /<slug>/<id>             baja        → {id}
#   POST   /<slug>/<id>/fotos       subir foto (multipart, campo `file`) → fila
#   DELETE /<slug>/<id>/fotos/<i>?fecha=…       → fila
#   GET    /<slug>/<id>/fotos/<i>?v=<fecha>     la imagen, cacheable para siempre
#
# Toda escritura devuelve la fila COMPLETA tal como quedó: la app la usa para reemplazar
# su copia local, así lo que calcula el servidor (derivados, desglose, vencimientos) nunca
# se tiene que adivinar del lado del navegador.

def _validar(cfg_ent, valores):
    """{campo: mensaje} con lo que no se puede guardar. Vacío = válido."""
    errores = {}
    for c in cfg_ent['campos']:
        valor = valores.get(c['nombre'], '')
        if c.get('requerido') and not valor:
            errores[c['nombre']] = f"{c['label']} es obligatorio."
        elif valor and c['tipo'] == 'number':
            try:
                float(valor.replace(',', '.'))
            except ValueError:
                errores[c['nombre']] = f"{c['label']} tiene que ser un número."
        elif valor and c['tipo'] == 'select' and valor not in c['opciones']:
            errores[c['nombre']] = f"{c['label']}: '{valor}' no es una opción válida."
    return errores


def serializar(area, slug, filas, cur, bp_name):
    """Filas de la DB → dicts para la API.

    Las fotos salen como URLs y no como base64: así el navegador baja cada imagen una sola
    vez y la guarda (la URL lleva la fecha de la foto, que nunca cambia). El alias, que es
    un campo oculto (ver `campo_alias`), no viaja: sólo entra al texto de búsqueda ya
    normalizado, igual que en el listado HTML.
    """
    cfg_ent = area.ENTIDADES[slug]
    campo_al = campo_alias(cfg_ent)
    relaciones = relaciones_visibles(area, cfg_ent)
    salida = []
    for fila in filas:
        d = dict(fila)
        fotos = json.loads(d.pop('fotos', None) or '[]')
        d['fotos'] = [{
            'indice': i, 'tipo': f.get('tipo', ''), 'fecha': f.get('fecha', ''),
            'url': url_for(f'{bp_name}.api_foto', slug=slug, id=d['id'], indice=i,
                           v=f.get('fecha', '') or str(i)),
        } for i, f in enumerate(fotos)]
        alias = d.pop(campo_al, '') if campo_al else ''
        d['_buscar'] = texto.norm(
            f"{d.get('nombre', '')} {d.get('descripcion') or ''} {alias or ''}")
        d['relaciones'] = {
            rel['campo']: [r[0] for r in cur.execute(
                f"SELECT {rel['col_ajena']} FROM {rel['tabla']} WHERE {rel['col_propia']} = ?",
                (d['id'],)).fetchall()]
            for rel in relaciones}
        salida.append(d)
    extra = _hook(area, 'api_serializar')
    if extra:
        extra(slug, salida, cur)
        # El hook puede escribir (gestion completa unidades faltantes) y eso, por los
        # triggers, sube la versión: se relee para no devolver una que ya quedó vieja y
        # que haría fallar con 409 el próximo guardado de la app.
        versiones = dict(cur.execute(f"SELECT id, version FROM {cfg_ent['tabla']}").fetchall()) \
            if len(salida) > 1 else {}
        for d in salida:
            if d['id'] in versiones:
                d['version'] = versiones[d['id']]
            elif len(salida) == 1:
                fila = cur.execute(f"SELECT version FROM {cfg_ent['tabla']} WHERE id = ?",
                                   (d['id'],)).fetchone()
                if fila:
                    d['version'] = fila[0]
    return salida


def registrar_api(bp, area):
    """Monta la API JSON de un área sobre `bp`, que ya tiene que traer el gate de
    `accesos.registrar_acceso_api` (sesión + permiso base, todo en JSON)."""
    escritura = _hook(area, 'PERMISO_ESCRITURA')

    def _una(cur, slug, id):
        cfg_ent = area.ENTIDADES[slug]
        fila = cur.execute(f"{select(cfg_ent)} WHERE id = ?", (id,)).fetchone()
        if fila is None:
            return None
        return serializar(area, slug, [fila], cur, bp.name)[0]

    def _cuerpo():
        datos = request.get_json(silent=True)
        if not isinstance(datos, dict):
            abort(400)
        return datos

    def _valores(cfg_ent, datos):
        valores = {}
        for c in cfg_ent['campos']:
            v = datos.get(c['nombre'])
            valores[c['nombre']] = '' if v is None else str(v).strip()
        return valores

    def _seleccion(cfg_ent, datos):
        rels = datos.get('relaciones') or {}
        return {rel['campo']: [i for i in rels[rel['campo']] if isinstance(i, int)]
                for rel in relaciones_visibles(area, cfg_ent)
                if isinstance(rels.get(rel['campo']), list)}

    def _duplicado(slug):
        return jsonify({'error': _hook(area, 'ERROR_DUPLICADO', {}).get(
            slug, 'Ya existe un registro igual.')}), 422

    @bp.before_request
    def _gate_entidad_api():
        slug = (request.view_args or {}).get('slug')
        if slug is not None and slug not in area.ENTIDADES:
            return jsonify({'error': 'No existe'}), 404
        permiso = permiso_entidad(area, slug) if slug else None
        if permiso and not accesos.puede(permiso):
            return accesos.denegar(permiso, como_json=True)

    @bp.get('/meta')
    def api_meta():
        """Lo que la app necesita para dibujar formularios y decidir qué botones mostrar."""
        entidades = {}
        for slug, e in area.ENTIDADES.items():
            if not ve_entidad(area, slug):
                continue
            entidades[slug] = {
                'singular': e['singular'], 'plural': e['plural'],
                'descripcion': e['descripcion'], 'campos': e['campos'],
                'columnas': e['columnas'],
                'relaciones': [{'campo': r['campo'], 'label': r['label'],
                                'slug': r['slug_ajeno']}
                               for r in relaciones_visibles(area, e)],
            }
        meta = {'entidades': entidades, 'puede_escribir': accesos.puede(escritura)}
        extra = _hook(area, 'api_meta')
        if extra:
            meta.update(extra())
        return jsonify(meta)

    @bp.get('/<slug>')
    def api_lista(slug):
        cfg_ent = area.ENTIDADES[slug]
        con = conectar(area)
        cur = con.cursor()
        filas = cur.execute(f"{select(cfg_ent)} ORDER BY nombre COLLATE NOCASE").fetchall()
        datos = serializar(area, slug, filas, cur, bp.name)
        # Los hooks de serialización pueden completar filas que faltaban (gestion crea las
        # unidades 1..cantidad la primera vez que se miran): se commitea y RECIÉN AHÍ se
        # lee la revisión, para que el ETag ya incluya ese cambio.
        con.commit()
        etag = f"{slug}-{revision(con)}"
        con.close()
        resp = jsonify({'filas': datos})
        resp.set_etag(etag)
        # no-cache = "guardala, pero preguntá antes de usarla": con el ETag, la pregunta
        # se contesta 304 sin cuerpo cuando nada cambió.
        resp.headers['Cache-Control'] = 'private, no-cache'
        return resp.make_conditional(request)

    @bp.get('/<slug>/<int:id>')
    def api_detalle(slug, id):
        con = conectar(area)
        fila = _una(con.cursor(), slug, id)
        con.commit()
        con.close()
        if fila is None:
            return jsonify({'error': 'Este registro ya no existe.'}), 404
        return jsonify(fila)

    @bp.post('/<slug>')
    @accesos.requiere(escritura)
    def api_crear(slug):
        cfg_ent = area.ENTIDADES[slug]
        datos = _cuerpo()
        valores = _valores(cfg_ent, datos)
        errores = _validar(cfg_ent, valores)
        if errores:
            return jsonify({'error': 'Revisá los campos marcados.', 'errores': errores}), 422
        con = conectar(area)
        cur = con.cursor()
        try:
            id = _guardar(area, slug, cfg_ent, cur, valores, _seleccion(cfg_ent, datos))
        except sqlite3.IntegrityError:
            con.close()
            return _duplicado(slug)
        fila = _una(cur, slug, id)
        con.commit()
        con.close()
        return jsonify(fila), 201

    @bp.put('/<slug>/<int:id>')
    @accesos.requiere(escritura)
    def api_editar(slug, id):
        cfg_ent = area.ENTIDADES[slug]
        datos = _cuerpo()
        valores = _valores(cfg_ent, datos)
        errores = _validar(cfg_ent, valores)
        if errores:
            return jsonify({'error': 'Revisá los campos marcados.', 'errores': errores}), 422
        con = conectar(area)
        # IMMEDIATE toma el lock de escritura antes de leer la versión: entre la
        # comparación y el UPDATE no puede colarse otro guardado.
        con.execute('BEGIN IMMEDIATE')
        cur = con.cursor()
        actual = cur.execute(f"SELECT version FROM {cfg_ent['tabla']} WHERE id = ?",
                             (id,)).fetchone()
        if actual is None:
            con.rollback()
            con.close()
            return jsonify({'error': 'Este registro ya no existe.'}), 404
        if datos.get('version') != actual['version']:
            fila = _una(cur, slug, id)
            con.rollback()
            con.close()
            return jsonify({'error': 'conflicto', 'actual': fila}), 409
        try:
            _guardar(area, slug, cfg_ent, cur, valores, _seleccion(cfg_ent, datos), id)
        except sqlite3.IntegrityError:
            con.rollback()
            con.close()
            return _duplicado(slug)
        fila = _una(cur, slug, id)
        con.commit()
        con.close()
        return jsonify(fila)

    @bp.delete('/<slug>/<int:id>')
    @accesos.requiere(escritura)
    def api_eliminar(slug, id):
        cfg_ent = area.ENTIDADES[slug]
        con = conectar(area)
        cur = con.cursor()
        cur.execute(f"DELETE FROM {cfg_ent['tabla']} WHERE id = ?", (id,))
        for tabla, columna in area.LIMPIEZA_M2M[slug]:
            cur.execute(f"DELETE FROM {tabla} WHERE {columna} = ?", (id,))
        con.commit()
        con.close()
        return jsonify({'id': id})

    @bp.post('/<slug>/<int:id>/fotos')
    @accesos.requiere(escritura)
    def api_subir_foto(slug, id):
        archivo = request.files.get('file')
        if archivo is None or not archivo.filename:
            return jsonify({'error': 'No llegó ninguna imagen.'}), 400
        if not (archivo.content_type or '').startswith('image/'):
            return jsonify({'error': 'Solo se aceptan imágenes.'}), 400
        b64 = base64.b64encode(archivo.read()).decode('utf-8')
        if not agregar_foto(area, slug, id, b64, archivo.content_type):
            return jsonify({'error': 'Este registro ya no existe.'}), 404
        con = conectar(area)
        fila = _una(con.cursor(), slug, id)
        con.commit()
        con.close()
        return jsonify(fila)

    @bp.delete('/<slug>/<int:id>/fotos/<int:indice>')
    @accesos.requiere(escritura)
    def api_eliminar_foto(slug, id, indice):
        """Borra por posición, pero sólo si la foto en esa posición es la que la app vio
        (`?fecha=`): si otra pestaña borró una antes, el índice ya apunta a otra foto."""
        cfg_ent = area.ENTIDADES[slug]
        con = conectar(area)
        cur = con.cursor()
        fila = cur.execute(f"SELECT fotos FROM {cfg_ent['tabla']} WHERE id = ?", (id,)).fetchone()
        if fila is None:
            con.close()
            return jsonify({'error': 'Este registro ya no existe.'}), 404
        fotos = json.loads(fila['fotos'] or '[]')
        if not (0 <= indice < len(fotos)) or fotos[indice].get('fecha', '') != request.args.get('fecha', ''):
            actual = _una(cur, slug, id)
            con.close()
            return jsonify({'error': 'Esa foto cambió mientras la mirabas.', 'actual': actual}), 409
        fotos.pop(indice)
        cur.execute(f"UPDATE {cfg_ent['tabla']} SET fotos = ? WHERE id = ?",
                    (json.dumps(fotos), id))
        resultado = _una(cur, slug, id)
        con.commit()
        con.close()
        return jsonify(resultado)

    @bp.get('/<slug>/<int:id>/fotos/<int:indice>')
    def api_foto(slug, id, indice):
        cfg_ent = area.ENTIDADES[slug]
        con = conectar(area)
        fila = con.execute(f"SELECT fotos FROM {cfg_ent['tabla']} WHERE id = ?", (id,)).fetchone()
        con.close()
        fotos = json.loads(fila['fotos'] or '[]') if fila else []
        if not (0 <= indice < len(fotos)):
            abort(404)
        foto = fotos[indice]
        resp = make_response(base64.b64decode(foto['b64']))
        resp.headers['Content-Type'] = foto.get('tipo') or 'image/jpeg'
        # La URL lleva ?v=<fecha de la foto>: misma URL = misma imagen, para siempre.
        resp.headers['Cache-Control'] = 'private, max-age=31536000, immutable'
        return resp
