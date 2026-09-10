"""Motor CRUD genérico — capa 1.

Conoce el *concepto* de entidad (una config declarativa, un slug, relaciones M2M) pero
**ninguna entidad concreta**: no sabe qué es un recurso ni un hito. Por eso **no importa
`gestion` ni `historia`** — las recibe como argumento (`area`). Esa es la regla que evita
el import circular y la que mantiene legible el criterio de pertenencia:

    capa 2 (gestion, historia)  ->  capa 1 (crud)  ->  capa 0 (texto, respaldos, config)

Un "área" es simplemente un módulo que expone lo de abajo. Todo lo que nombre una tabla
concreta entra por un **hook opcional**, nunca por un `if slug == '...'` acá adentro.

    OBLIGATORIO
      DB_PATH          ruta al archivo .db (o el hook `db_path()`, si el área tiene más
                       de una y elige por request — ver `db_path`)
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
      db_path()                       la .db de ESTE request, si no es una sola fija
      prefijo_backup()                el prefijo de respaldo que le corresponde
      migrar(cur)                     ALTERs aditivos para DBs viejas
      seed(cur)                       datos de ejemplo en instalación nueva
      secciones_detalle(slug, id, cur)  relaciones a mostrar en el detalle
      resultados_extra_busqueda(slug, q, cur)  filas extra para el listado cuando hay `q`
      derivados(slug, valores)        columnas calculadas al guardar (no van en 'campos')
      valores_iniciales(slug)         defaults del form de alta
      extras_template(vista, slug, id)  kwargs extra para render_template (`id` sólo en
                                      las vistas de una fila: detalle y editar; si no, None)
      tarjetas_extra(cur)             tarjetas del home que no salen de ENTIDADES
      contexto_extra()                claves extra del context processor
      NAV_EXTRA                       [(slug, label)] extra para la nav
      ERROR_DUPLICADO                 {slug: mensaje} cuando un UNIQUE rechaza el guardado

Cada cfg de ENTIDADES: tabla, singular, plural, descripcion, campos, columnas,
relaciones y (opcional) campo_nombre, permiso y `sin_eliminar` (la entidad no se borra
nunca: la ruta de eliminar devuelve 404 y los templates no ofrecen el botón — lo usa
`gestion.recursos`, que en vez de borrarse se da de baja).
"""

import base64
import json
import os
import sqlite3

from flask import abort, jsonify, redirect, render_template, request, send_file, url_for

import accesos
import fotos_disco
import respaldos
import texto
from config import ESCUELA_NOMBRE, ESCUELA_LOGO, ESCUELA_VERSION, ahora


# ---------------------------------------------------------------------------
# Conexión y config declarativa
# ---------------------------------------------------------------------------

def db_path(area):
    """El archivo .db del área. Casi siempre es una constante (`DB_PATH`), pero un área
    puede tener MÁS DE UNA base y elegir por request: gestión declara `db_path()` porque
    cada inventario es un archivo aparte. Capa 1 no sabe cuál ni por qué — nada más
    pregunta."""
    dinamico = _hook(area, 'db_path')
    return dinamico() if dinamico else area.DB_PATH


def prefijo_backup(area):
    """Ídem para el prefijo de sus respaldos: si la DB cambia por request, la rotación de
    respaldos tiene que cambiar con ella o cada base se comería la del resto."""
    dinamico = _hook(area, 'prefijo_backup')
    return dinamico() if dinamico else area.PREFIJO_BACKUP


def conectar(area):
    con = sqlite3.connect(db_path(area))
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
    ruta, prefijo = db_path(area), prefijo_backup(area)
    respaldos.respaldar(ruta, prefijo, area.TABLA_TESTIGO)

    con = conectar(area)
    cur = con.cursor()
    cur.executescript(area.SCHEMA)

    migrar = _hook(area, 'migrar')
    if migrar:
        migrar(cur)

    sembrar = _hook(area, 'seed')
    if cur.execute(f"SELECT COUNT(*) FROM {area.TABLA_TESTIGO}").fetchone()[0] == 0:
        # Una DB vacía es ambigua: puede ser una instalación nueva o datos perdidos.
        # Los respaldos desempatan — si existen, esto ya estuvo cargado alguna vez y
        # seguir de largo taparía la pérdida en silencio (que es exactamente lo que pasó
        # el 2026-08-08). Ante la duda, fallar ruidoso.
        previos = respaldos.listar(prefijo)
        if previos and os.environ.get('GESTION_SEED') != '1':
            nombre_db = os.path.basename(ruta)
            ultimo = previos[-1]
            con.close()
            aviso = ("NO se cargaron los datos de ejemplo." if sembrar
                     else "NO se cargó nada.")
            raise RuntimeError(
                f"{nombre_db} está vacía pero hay {len(previos)} respaldo(s) en "
                f"{respaldos.BACKUP_DIR}.\n"
                f"Probablemente se perdió el archivo — {aviso}\n\n"
                f"Para restaurar el más reciente:\n"
                f"    copy \"{ultimo}\" \"{ruta}\"\n\n"
                f"Si de verdad querés empezar de cero:\n"
                f"    GESTION_SEED=1 python app.py"
            )
        if sembrar:
            sembrar(cur)
    con.commit()
    con.close()


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
    """Agrega una foto ya en base64 a la galería de una entidad: la decodifica y la
    escribe en `database/fotos/` (ver `fotos_disco.py`) — en la fila sólo queda
    {id, tipo, fecha}, nunca el base64.

    Vive suelta y no dentro de `subir_foto` porque el agente también escribe la galería:
    cuando el alta de un recurso salió de una foto del chat, esa foto termina acá por el
    mismo camino que la que se sube desde el detalle (ver `agente.confirmar`). La firma
    no cambia aunque adentro sí: quien la llama sigue mandando b64 + tipo, y no necesita
    saber que ahora eso termina en disco.
    """
    cfg_ent = cfg(area, slug)
    con = conectar(area)
    cur = con.cursor()
    fila = cur.execute(f"SELECT fotos FROM {cfg_ent['tabla']} WHERE id = ?", (id,)).fetchone()
    if fila is None:
        con.close()
        return False
    foto_id = fotos_disco.guardar(b64, tipo)
    fotos = json.loads(fila['fotos'] or '[]')
    fotos.append({'id': foto_id, 'tipo': tipo, 'fecha': ahora().isoformat()})
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
        cur.execute(f"DELETE FROM {rel['tabla']} WHERE {rel['col_propia']} = ?", (id,))
        for rid in request.form.getlist(rel['campo']):
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
        # Girar una foto puede pedir un permiso más alto que el resto de la escritura
        # (en gestión lo pide: `PERMISO_ROTAR_FOTO`). El área que no lo declara cae en
        # el de escritura y no cambia nada.
        'permiso_rotar_foto': _hook(area, 'PERMISO_ROTAR_FOTO')
                              or _hook(area, 'PERMISO_ESCRITURA'),
        # Para el botón "HOY" de un campo de fecha de texto libre (`boton_hoy` en el cfg
        # del campo): el formato lo pone el área, la fecha sale del reloj de la escuela.
        'hoy': lambda formato: ahora().strftime(formato),
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
    rotar = _hook(area, 'PERMISO_ROTAR_FOTO') or escritura

    def _extras(vista, slug, id=None):
        hook = _hook(area, 'extras_template')
        return hook(vista, slug, id) if hook else {}

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
        # (data-buscar / data-alias). El alias viaja APARTE, no concatenado al nombre: si
        # va todo junto, el filtro en vivo no puede saber de dónde vino el match y una fila
        # que sólo coincide por alias queda mezclada entre las que coinciden por nombre
        # (buscar "pinza" ponía "Alicate" arriba de "Pinza de fuerza", por orden alfabético).
        # Con los dos campos separados, gestion.js puede repetir la misma jerarquía que la
        # segunda pasada de acá arriba: los de alias, al final.
        def _texto_buscar(fila):
            return texto.norm(f"{fila['nombre']} {fila['descripcion'] or ''}")
        buscar = {fila['id']: _texto_buscar(fila) for fila in filas}
        buscar_alias = {fila['id']: texto.norm(fila[campo_al] or '') if campo_al else ''
                        for fila in filas}
        # Filas que no son de esta entidad pero matchean la búsqueda (ej: sub-recursos de
        # un kit): el hook decide qué son, el motor sólo las reenvía a la plantilla.
        extra_filas = []
        if q:
            extra_hook = _hook(area, 'resultados_extra_busqueda')
            if extra_hook:
                extra_filas = extra_hook(slug, q, cur)
        con.close()
        return render_template(f'{nombre}/lista.html', cfg=cfg_ent, slug=slug, filas=filas,
                               q=q, activo=slug, buscar=buscar, buscar_alias=buscar_alias,
                               via_alias=via_alias, extra_filas=extra_filas,
                               **_extras('lista', slug))

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
                               **_extras('detalle', slug, id))

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
                               **_extras('editar', slug, id))

    @bp.route('/<slug>/<int:id>/eliminar', methods=['POST'])
    @accesos.requiere(escritura)
    def eliminar(slug, id):
        cfg_ent = cfg(area, slug)
        # Entidad que no se borra nunca (`sin_eliminar`): la ruta ni existe para ese slug.
        # Los templates ya no muestran el botón, pero esto es lo que cierra la URL a mano.
        if cfg_ent.get('sin_eliminar'):
            abort(404)
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
        """Sube una foto (ya comprimida client-side, ver `_detalle_fotos.html`), la
        convierte a base64 y la manda a `agregar_foto`, que la escribe en disco."""
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

    @bp.route('/<slug>/<int:id>/foto/<foto_id>')
    def foto_archivo(slug, id, foto_id):
        """Sirve el archivo de una foto (ver `fotos_disco.py`).

        No usa `/static` porque la galería es privada: no lleva su propio decorador de
        permiso, cae bajo el mismo `_gate_entidad` (`before_request`, filtra por `slug`)
        que `detalle`/`lista` — mismo nivel de acceso. Además valida acá que `foto_id`
        pertenezca a ESTA fila: el uuid random no alcanza solo como control de acceso,
        porque no es secreto frente a alguien que ya tiene lectura de otra entidad del
        área.
        """
        cfg_ent = cfg(area, slug)
        con = conectar(area)
        cur = con.cursor()
        fila = cur.execute(f"SELECT fotos FROM {cfg_ent['tabla']} WHERE id = ?", (id,)).fetchone()
        con.close()
        if fila is None:
            abort(404)
        fotos = json.loads(fila['fotos'] or '[]')
        foto = next((f for f in fotos if f.get('id') == foto_id), None)
        if foto is None:
            abort(404)
        archivo = fotos_disco.ruta(foto['id'], foto['tipo'])
        if not os.path.exists(archivo):
            abort(404)
        return send_file(archivo, mimetype=foto['tipo'])

    @bp.route('/<slug>/<int:id>/foto/<foto_id>/eliminar', methods=['POST'])
    @accesos.requiere(escritura)
    def eliminar_foto(slug, id, foto_id):
        """Borra una foto de la galería (fila + archivo en disco) por su `id` (uuid).

        Un `foto_id` que no está no es error: se ignora y se vuelve a la ficha (pasa si
        dos pestañas borran a la vez, o un doble click).
        """
        cfg_ent = cfg(area, slug)
        con = conectar(area)
        cur = con.cursor()
        fila = cur.execute(f"SELECT fotos FROM {cfg_ent['tabla']} WHERE id = ?", (id,)).fetchone()
        if fila is None:
            con.close()
            abort(404)
        fotos = json.loads(fila['fotos'] or '[]')
        borrada = next((f for f in fotos if f.get('id') == foto_id), None)
        if borrada is not None:
            fotos_disco.eliminar(borrada['id'], borrada['tipo'])
            restantes = [f for f in fotos if f.get('id') != foto_id]
            cur.execute(f"UPDATE {cfg_ent['tabla']} SET fotos = ? WHERE id = ?",
                        (json.dumps(restantes), id))
            con.commit()
        con.close()
        return redirect(url_for(f'{nombre}.detalle', slug=slug, id=id))

    @bp.route('/<slug>/<int:id>/foto/<foto_id>/rotar', methods=['POST'])
    @accesos.requiere(rotar)
    def rotar_foto(slug, id, foto_id):
        """Reemplaza el ARCHIVO de una foto por la misma imagen girada, conservando su
        `id` (y su `fecha`).

        El giro lo hace el navegador (un canvas en `crud/_detalle_fotos.html`) y acá llega
        la imagen ya girada, cruda en el body con su `Content-Type`: así no hace falta
        Pillow ni ninguna dependencia nueva en el server. Como la ruta acepta el contenido
        que le mandan, pide el permiso que declaró el área (`PERMISO_ROTAR_FOTO`), que
        puede ser más alto que el de escritura.
        """
        cfg_ent = cfg(area, slug)
        tipo = (request.content_type or '').split(';')[0].strip()
        crudo = request.get_data()
        if not tipo.startswith('image/'):
            return jsonify({'ok': False, 'error': 'Tipo de imagen inválido'}), 400
        if not crudo:
            return jsonify({'ok': False, 'error': 'Imagen vacía'}), 400
        if len(crudo) > 24 * 1024 * 1024:
            return jsonify({'ok': False, 'error': 'Imagen demasiado grande'}), 400

        con = conectar(area)
        cur = con.cursor()
        fila = cur.execute(f"SELECT fotos FROM {cfg_ent['tabla']} WHERE id = ?", (id,)).fetchone()
        if fila is None:
            con.close()
            abort(404)
        fotos = json.loads(fila['fotos'] or '[]')
        foto = next((f for f in fotos if f.get('id') == foto_id), None)
        if foto is None:
            con.close()
            return jsonify({'ok': False, 'error': 'No existe esa foto'}), 404
        fotos_disco.reemplazar(foto['id'], foto['tipo'], crudo, tipo)
        foto['tipo'] = tipo
        cur.execute(f"UPDATE {cfg_ent['tabla']} SET fotos = ? WHERE id = ?",
                    (json.dumps(fotos), id))
        con.commit()
        con.close()
        return jsonify({'ok': True})
