# gestion.py
# Gestión de recursos — área de capa 2: declara sus entidades y sus reglas de negocio,
# y el CRUD se lo da el motor genérico (crud.py). Lo que NO es genérico y vive acá entero:
# el desglose de recursos por lugar, al final del archivo.
#
# Usa su propia DB (gestion.db): a diferencia de escuela.db, NO se regenera desde
# Google Sheets y /api/actualizar no la toca. Es la única DB con datos propios de la app
# (además de historia.db).
#
# Entidades: recursos.
#
# Hasta el 2026-08-21 el módulo también tenía conjuntos, actividades y préstamos/carrito
# (retiro interno de recursos). Se sacaron por decisión de producto, no por deuda técnica:
# ver dev-log/DECISIONS.md 2026-08-21 si se retoman.

import os
import sys
from datetime import datetime

from config import ahora
from flask import Blueprint, redirect, render_template, request, url_for

import accesos
import crud
import texto

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gestion.db')

# Permisos que declara el área al catálogo de `accesos`. El VERBO es lo que hace que un
# perfil los agarre solo: 'leer' entra en interno-lectura, 'escribir' en interno-gestion.
PERMISOS = [
    ('gestion.leer', 'Ver el inventario', 'leer'),
    ('gestion.editar', 'Cargar, editar y eliminar recursos', 'escribir'),
    # Verbo 'admin' = no entra en ningún preset de interno (ver accesos.PERFILES, que los
    # arma por verbo): sólo lo tiene el admin, por el comodín '*'. El alias de un recurso
    # es un campo que ni el interno de lectura ni el de escritura deben poder ver/editar
    # desde ningún lado — lo completa el asistente solo (ver agent_docs/gestion-conocimiento.md).
    ('gestion.alias', 'Ver los alias ocultos de los recursos (solo consulta)', 'admin'),
    # Mismo verbo 'admin' y mismo motivo que gestion.alias: son chips de auditoría del
    # inventario (qué está vencido de revisión, qué está dado de baja), no algo que un
    # interno de lectura/escritura necesite para su tarea del día a día.
    ('gestion.auditoria', 'Ver los filtros de auditoría del listado (vencidos y dados de baja)', 'admin'),
    # Mismo verbo 'admin', mismo motivo: girar una foto reescribe la imagen guardada (se
    # re-codifica), así que es una operación de mantenimiento del inventario y no parte de
    # cargar un recurso. Subir y borrar fotos siguen siendo de `gestion.editar`.
    ('gestion.rotar', 'Rotar las fotos de un recurso', 'admin'),
]
GRUPO_PERMISOS = 'Gestión de recursos'
PERMISO_LECTURA = 'gestion.leer'
PERMISO_ESCRITURA = 'gestion.editar'
PERMISO_ALIAS = 'gestion.alias'
PERMISO_AUDITORIA = 'gestion.auditoria'
# Hook opcional que lee crud.py: quién puede girar una foto ya cargada. Si un área no lo
# declara (historia), el botón pide el permiso de escritura de siempre.
PERMISO_ROTAR_FOTO = 'gestion.rotar'

# Respaldos rotativos: la maquinaria vive en respaldos.py (capa 0). Acá sólo se declara
# con qué prefijo se guardan y qué tabla mirar para saber si la DB tiene datos de verdad
# (una DB vacía no se respalda: taparía los respaldos buenos).
PREFIJO_BACKUP = 'gestion'
TABLA_TESTIGO = 'recursos'

bp = Blueprint('gestion', __name__, url_prefix='/gestion')


def conectar():
    """Conexión a gestion.db — `crud.conectar` con esta área ya puesta. Las rutas propias
    (alias, desglose por ubicación, que no pasan por el motor genérico) la usan directo."""
    return crud.conectar(sys.modules[__name__])

ESTADOS_RECURSO = ["Funcional", "Dañado usable", "Roto", "Dado de baja"]
# "" primero: permite dejar el valor sin definir (recursos previos al inventario).
VALORES_RECURSO = ["", "Básico", "Secundario", "Alto valor"]
# Sugerencias de lugar para el desglose por unidad (templates/gestion/detalle.html): NUNCA
# restringen el valor, sólo aparecen como opciones de autocompletado — hace falta poder
# escribir excepciones como "panel solar instalado en el techo".
LUGARES_RECURSO = ["Laboratorio Armario 1", "Laboratorio Armario 2", "Laboratorio",
                    "Taller", "Taller Armario 3", "Taller Armario 4"]

# Configuración declarativa de cada entidad: campos del form, columnas del listado
# y relaciones M2M editables desde su formulario. Los campos de relación usan el
# prefijo "rel_" para no colisionar con nombres de columnas.
ENTIDADES = {
    'recursos': {
        'tabla': 'recursos',
        'singular': 'Recurso',
        'plural': 'Inventario',
        'descripcion': '',
        'campos': [
            {'nombre': 'nombre', 'label': 'Nombre', 'tipo': 'text', 'requerido': True},
            {'nombre': 'tipo', 'label': 'Tipo', 'tipo': 'text', 'ayuda': 'Ej: Instrumento, Equipo, Estructura, Material'},
            {'nombre': 'cantidad', 'label': 'Cantidad', 'tipo': 'number'},
            {'nombre': 'descripcion', 'label': 'Descripción', 'tipo': 'textarea'},
            # No hay campo `ubicacion`: la ubicación de un recurso es siempre la lista de sus
            # unidades (recurso_unidades), incluso para uno con una sola unidad. Se carga desde
            # la ficha ("Ubicación", ver secciones_detalle), no desde este form — ver
            # agent_docs/gestion-conocimiento.md.
            {'nombre': 'estado', 'label': 'Estado', 'tipo': 'select', 'opciones': ESTADOS_RECURSO},
            {'nombre': 'valor', 'label': 'Valor', 'tipo': 'select', 'opciones': VALORES_RECURSO, 'ayuda': 'Importancia del recurso dentro del inventario'},
            {'nombre': 'fecha_revision', 'label': 'Última revisión', 'tipo': 'text', 'ayuda': 'Fecha del último control de inventario (día/mes/año). En un alta arranca en hoy'},
        ],
        # 'valor' no está acá a propósito: sigue siendo un campo real (se carga y edita
        # desde la ficha, y el asistente lo usa), pero no tiene columna propia en el
        # listado — se ve en el detalle de cada recurso.
        'columnas': [('nombre', 'NOMBRE'), ('cantidad', 'CANT.'), ('estado', 'ESTADO')],
        'relaciones': [],
        # Términos alternativos (no necesariamente sinónimos estrictos: "zapatilla" y
        # "alargue" son cosas distintas pero se confunden) que completa el asistente
        # (agente/tools/esquemas.py), nunca el humano: a propósito NO está en 'campos', así
        # que ni el form web (templates/crud/form.html) ni la ficha de detalle ni la ficha
        # de confirmación del chat (agente/tools/fichas.py::_campos_validos) la ven. crud.py
        # la usa para la segunda pasada de búsqueda y para el whitelist de escritura de
        # guardar_entidad(). Ver dev-log/DECISIONS.md 2026-08-08 y 2026-08-21: el
        # override consciente de por qué esta vez sí conviene una columna por fila.
        'campo_alias': 'alias',
    },
}

# Tablas a limpiar cuando se elimina un recurso. `recurso_unidades` y `kit_items` no son
# relaciones M2M de verdad (son el desglose por unidad y los sub-recursos de un kit, ver
# más abajo) pero el mecanismo de limpieza es idéntico: borrar filas por `recurso_id`.
LIMPIEZA_M2M = {
    'recursos': [('recurso_unidades', 'recurso_id'), ('kit_items', 'recurso_id')],
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS recursos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    tipo TEXT DEFAULT '',
    descripcion TEXT DEFAULT '',
    estado TEXT DEFAULT 'Funcional',
    cantidad TEXT DEFAULT '',
    valor TEXT DEFAULT '',
    fecha_revision TEXT DEFAULT '',
    fotos TEXT DEFAULT '[]',
    alias TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS recurso_unidades (
    recurso_id INTEGER NOT NULL,
    numero INTEGER NOT NULL,
    ubicacion TEXT DEFAULT '',
    UNIQUE(recurso_id, numero)
);
CREATE TABLE IF NOT EXISTS kit_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recurso_id INTEGER NOT NULL,
    titulo TEXT NOT NULL,
    cantidad TEXT DEFAULT '',
    recurso_asignado TEXT DEFAULT ''
);
"""


# --- Reglas propias del área ------------------------------------------------
# El CRUD (rutas, búsqueda, fotos, respaldos) lo pone crud.py. Acá queda sólo lo que
# nombra tablas concretas de gestion.db, que es lo que el motor no puede saber.

def migrar(cur):
    """Adapta una gestion.db creada con un schema anterior (ALTER aditivo + renombres)."""
    existentes = {c[1] for c in cur.execute("PRAGMA table_info(recursos)").fetchall()}
    # 'utilidad' pasó a llamarse 'valor'. RENAME COLUMN conserva los datos ya cargados;
    # va antes del ALTER aditivo para no crear un 'valor' vacío al lado del viejo.
    if 'utilidad' in existentes and 'valor' not in existentes:
        cur.execute("ALTER TABLE recursos RENAME COLUMN utilidad TO valor")
        existentes = {c[1] for c in cur.execute("PRAGMA table_info(recursos)").fetchall()}
    for columna in ('cantidad', 'valor', 'fecha_revision', 'fotos', 'alias'):
        if columna not in existentes:
            default = '[]' if columna == 'fotos' else ''
            cur.execute(f"ALTER TABLE recursos ADD COLUMN {columna} TEXT DEFAULT '{default}'")

    # `drive_url` se eliminó: la escuela dejó de usar Drive y la fuente de verdad de gestión
    # pasó a ser esta DB. Es la primera migración DESTRUCTIVA del módulo, así que se corrió
    # habiendo verificado que la columna estaba vacía en las 89 filas de las tres tablas; el
    # respaldo previo de `respaldos.respaldar()` (que corre antes que esto, en init_db) es la red por
    # si alguna instalación tenía links cargados.
    if 'drive_url' in existentes:
        cur.execute("ALTER TABLE recursos DROP COLUMN drive_url")

    # `recurso_ubicaciones` (agregado por lugar, sin identidad de unidad) se reemplazó por
    # `recurso_unidades` (una fila por unidad física, con su propio número) el 2026-08-22:
    # ver dev-log/DECISIONS.md. Cada fila vieja (lugar, cantidad) se reparte en unidades
    # numeradas secuenciales por recurso, mismo orden que usaba `ubicaciones_recurso`.
    tablas = {r['name'] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if 'recurso_ubicaciones' in tablas:
        for fila_r in cur.execute("SELECT DISTINCT recurso_id FROM recurso_ubicaciones").fetchall():
            rid = fila_r['recurso_id']
            siguiente = 1
            filas = cur.execute(
                "SELECT ubicacion, cantidad FROM recurso_ubicaciones WHERE recurso_id = ? "
                "ORDER BY ubicacion COLLATE NOCASE", (rid,)).fetchall()
            for fila in filas:
                for _ in range(_int(fila['cantidad'])):
                    cur.execute(
                        "INSERT OR IGNORE INTO recurso_unidades (recurso_id, numero, ubicacion) VALUES (?,?,?)",
                        (rid, siguiente, fila['ubicacion']))
                    siguiente += 1
        cur.execute("DROP TABLE recurso_ubicaciones")

    # `ubicacion` de `recursos` (el campo simple de siempre) se reemplazó por la lista de
    # unidades: un recurso ya no tiene "un lugar" y aparte "el desglose", tiene sus unidades
    # (recurso_unidades) y nada más, aunque sea una sola. Antes de sacar la columna, cada
    # recurso que todavía no tenga ninguna unidad propia (la mayoría, que nunca tocó el
    # desglose) se siembra 1..cantidad (mínimo 1) con el valor que tenía `ubicacion`, para no
    # perder el dato ya cargado. 2026-08-22.
    if 'ubicacion' in existentes:
        sin_unidades = cur.execute(
            "SELECT id, cantidad, ubicacion FROM recursos WHERE id NOT IN "
            "(SELECT DISTINCT recurso_id FROM recurso_unidades)").fetchall()
        for r in sin_unidades:
            n = max(_int(r['cantidad']), 1)
            cur.executemany(
                "INSERT INTO recurso_unidades (recurso_id, numero, ubicacion) VALUES (?,?,?)",
                [(r['id'], i, r['ubicacion'] or '') for i in range(1, n + 1)])
        cur.execute("ALTER TABLE recursos DROP COLUMN ubicacion")


def seed(cur):
    """Datos de ejemplo: el banco de ensayo solar del documento de diseño."""
    recursos = [
        ("Panel solar 100W", "Equipo", "Panel fotovoltaico monocristalino de 100W usado para prácticas de energías renovables.", "Funcional", "Taller de Electricidad"),
        ("Estructura regulable", "Estructura", "Estructura metálica con ángulo de inclinación regulable, construida en la escuela.", "Funcional", "Taller de Electricidad"),
        ("Inclinómetro digital", "Instrumento", "Medidor digital de ángulo de inclinación.", "Funcional", "Pañol"),
        ("Multímetro", "Instrumento", "Multímetro digital para medición de tensión, corriente y resistencia.", "Funcional", "Pañol"),
        ("Pinza amperométrica", "Instrumento", "Pinza para medición de corriente sin abrir el circuito.", "Funcional", "Pañol"),
    ]
    for nombre, tipo, descripcion, estado, lugar in recursos:
        cur.execute(
            "INSERT INTO recursos (nombre, tipo, descripcion, estado) VALUES (?,?,?,?)",
            (nombre, tipo, descripcion, estado))
        cur.execute(
            "INSERT INTO recurso_unidades (recurso_id, numero, ubicacion) VALUES (?,1,?)",
            (cur.lastrowid, lugar))


# Qué decir cuando un UNIQUE de la DB rechaza el guardado (si no, sale un 500 pelado).
# Vacío: ninguna entidad de este módulo tiene un UNIQUE de negocio (a diferencia de
# historia.personas, que sí lo necesita — ver historia.ERROR_DUPLICADO).
ERROR_DUPLICADO = {}


# Formato de `recursos.fecha_revision`. La columna es TEXT y el inventario importado del
# sheet trae fechas cortas sin año ("24/4"): conviven, pero lo que se carga de acá en más
# lleva el año. El agente importa esta constante para no tener dos formatos distintos.
FORMATO_FECHA_REVISION = '%d/%m/%Y'

# Umbral del chip "sin revisar hace +6 meses" del listado (rediseño de
# templates/gestion/lista.html). 183 días ~ 6 meses.
UMBRAL_SIN_REVISAR_DIAS = 183


def _revisado_vencido(fecha_texto):
    """True si `fecha_revision` está vacía o pasó el umbral de 6 meses.

    Las fechas cortas sin año que trae el inventario importado del sheet (ver
    FORMATO_FECHA_REVISION) no se pueden ubicar en el tiempo: no se marcan vencidas
    (mejor un falso negativo suelto que marcar vencido todo el inventario viejo)."""
    fecha_texto = (fecha_texto or '').strip()
    if not fecha_texto:
        return True
    try:
        fecha = datetime.strptime(fecha_texto, FORMATO_FECHA_REVISION)
    except ValueError:
        return False
    return (ahora() - fecha).days > UMBRAL_SIN_REVISAR_DIAS


def valores_iniciales(slug):
    """Con qué valores arranca el formulario de alta, antes de que el usuario escriba.

    Dar de alta un recurso ES un control de inventario, así que la fecha de revisión
    arranca en hoy. Antes quedaba vacía y casi ningún recurso terminaba con fecha.
    """
    if slug == 'recursos':
        return {'fecha_revision': ahora().strftime(FORMATO_FECHA_REVISION)}
    return {}


def secciones_detalle(slug, id, cur):
    """Relaciones a mostrar en la vista de detalle."""
    secciones = []
    if slug == 'recursos':
        # La ubicación de un recurso es siempre esta lista (recurso_unidades), aunque tenga
        # una sola unidad: no hay un campo aparte para "el lugar principal" — ver
        # agent_docs/gestion-conocimiento.md.
        secciones.append({'titulo': 'Ubicación', 'slug': None,
                          'items': lugares_recurso_agrupado(cur, id), 'tipo': 'ubicaciones'})
        # Un recurso es "kit" en cuanto tiene sub-recursos cargados acá, sin flag aparte
        # (mismo criterio orgánico que el desglose por ubicación). `oculto_si_vacio` para
        # que un recurso sin sub-recursos no muestre la sección a quien no puede escribir.
        secciones.append({'titulo': 'Sub-recursos (kit)', 'slug': None,
                          'items': kit_items_recurso(cur, id), 'tipo': 'kit_items',
                          'oculto_si_vacio': True})
    return secciones


def resultados_extra_busqueda(slug, q, cur):
    """Sub-recursos de un kit que matchean la búsqueda `q`, para mostrar aparte del
    listado principal de recursos (que nunca los muestra sueltos sin buscar)."""
    if slug == 'recursos' and q:
        return buscar_kit_items(cur, q)
    return []


def init_db():
    """Lo hace el motor; queda como nombre estable para app.py e init_gestion.py."""
    crud.init_db(sys.modules[__name__])


def extras_template(vista, slug):
    """Kwargs extra para el render. En la ficha: la lista fija de lugares, para el datalist
    del mini form de mover/ubicar unidades (templates/gestion/detalle.html). En el listado:
    los lugares de cada recurso (para la columna y el filtro) y qué está vencido."""
    if slug == 'recursos' and vista == 'detalle':
        return {'lugares_recurso': LUGARES_RECURSO}
    if slug == 'recursos' and vista == 'lista':
        con = conectar()
        cur = con.cursor()
        filas = cur.execute("SELECT id, fecha_revision FROM recursos").fetchall()
        vencidos = {f['id'] for f in filas if _revisado_vencido(f['fecha_revision'])}
        ubicaciones = lugares_por_recurso(cur)
        con.commit()  # lugares_por_recurso puede crear unidades que faltaban (_asegurar_unidades)
        con.close()
        lugares = sorted({g['ubicacion'] for lugs in ubicaciones.values() for g in lugs if g['ubicacion'] != 'Sin ubicar'},
                          key=texto.norm)
        return {'vencidos_recurso': vencidos, 'lugares_filtro': lugares, 'ubicaciones_recurso': ubicaciones}
    return {}


accesos.registrar_acceso(bp, PERMISO_LECTURA)
crud.registrar_rutas(bp, sys.modules[__name__])


def _int(texto):
    """Entero desde texto de la DB/form; 0 si está vacío o no es número."""
    try:
        return int(str(texto).strip())
    except (TypeError, ValueError):
        return 0


@bp.route('/alias')
@accesos.requiere(PERMISO_ALIAS)
def alias_lista():
    """Consulta de solo lectura: qué alias le completó el asistente a cada recurso.

    Es la única ventana al campo oculto (`recursos.alias`) — no hay edición acá ni en
    ningún otro lado de la web a propósito, ver `agent_docs/gestion-conocimiento.md`.
    """
    con = conectar()
    filas = con.execute(
        "SELECT nombre, alias FROM recursos ORDER BY nombre COLLATE NOCASE").fetchall()
    con.close()
    return render_template('gestion/alias_lista.html', filas=filas, activo='alias')


def _stock(cur, rid):
    """Stock del recurso (recursos.cantidad como entero); None si no existe la fila.
    0 = sin stock definido → sin tope (cantidad vacía o no numérica). La usa el agente
    (agente/tools/ubicaciones.py) para saber si un id de recurso existe de verdad."""
    row = cur.execute("SELECT cantidad FROM recursos WHERE id = ?", (rid,)).fetchone() if rid else None
    return None if row is None else _int(row['cantidad'])


# --- Desglose de recursos por unidad ------------------------------------------
# `recurso_unidades` es OPCIONAL a propósito: la mayoría de los recursos tiene un solo lugar
# (el campo `ubicacion` de siempre) y nunca toca esta tabla. Sólo entra en juego cuando
# alguien reparte las unidades de un mismo recurso en más de un sitio — y a diferencia del
# viejo desglose agregado (recurso_ubicaciones, hasta el 2026-08-21), cada unidad tiene su
# propio número: permite pedirle al agente cosas puntuales ("el destornillador 3 y el 5
# están en el taller"), no sólo cantidades sueltas. El desglose NUNCA tiene que estar
# completo: una unidad sin `ubicacion` es "sin ubicar", no un error. El pedido explícito fue
# que mover algo entre lugares no se bloquee por no tener el desglose previo cargado, mismo
# criterio de "avisar, no bloquear" que se usaba con el stock de los préstamos (ver
# dev-log/DECISIONS.md 2026-08-11, 2026-08-21 y 2026-08-22).

def _asegurar_unidades(cur, rid):
    """Crea las unidades 1..cantidad que todavía no existan (sin ubicación, `''`). Un recurso
    siempre tiene al menos la unidad 1, aunque `cantidad` esté vacía o en 0: sin esto no habría
    ninguna fila donde guardar su ubicación. No borra unidades de más si `cantidad` bajó
    después: mismo criterio de no perder datos. No hace nada si el recurso no existe."""
    fila = cur.execute("SELECT cantidad FROM recursos WHERE id = ?", (rid,)).fetchone()
    if fila is None:
        return
    cantidad = max(_int(fila['cantidad']), 1)
    existentes = {f['numero'] for f in
                  cur.execute("SELECT numero FROM recurso_unidades WHERE recurso_id = ?", (rid,)).fetchall()}
    faltantes = [n for n in range(1, cantidad + 1) if n not in existentes]
    if faltantes:
        cur.executemany("INSERT INTO recurso_unidades (recurso_id, numero, ubicacion) VALUES (?,?,'')",
                        [(rid, n) for n in faltantes])


def unidades_recurso(cur, rid):
    """Unidades individuales de un recurso: [{'numero':, 'ubicacion':}], por número.
    Auto-completa 1..cantidad si faltan filas (ver _asegurar_unidades)."""
    _asegurar_unidades(cur, rid)
    filas = cur.execute(
        "SELECT numero, ubicacion FROM recurso_unidades WHERE recurso_id = ? ORDER BY numero", (rid,)).fetchall()
    return [{'numero': f['numero'], 'ubicacion': f['ubicacion']} for f in filas]


def lugares_recurso_agrupado(cur, rid):
    """Unidades de un recurso agrupadas por lugar, para la vista de detalle y para
    contarle al agente cómo quedó el desglose: [{'ubicacion':, 'numeros': [..]}], ordenado
    por lugar con "Sin ubicar" al final. Nunca vacía para un recurso que existe (al menos
    la unidad 1, ver _asegurar_unidades); lista vacía = el id no corresponde a ningún recurso."""
    grupos = {}
    for u in unidades_recurso(cur, rid):
        grupos.setdefault(u['ubicacion'], []).append(u['numero'])
    resultado = [{'ubicacion': lugar, 'numeros': numeros}
                 for lugar, numeros in sorted(grupos.items(), key=lambda kv: texto.norm(kv[0])) if lugar]
    if grupos.get(''):
        resultado.append({'ubicacion': 'Sin ubicar', 'numeros': grupos['']})
    return resultado


def lugares_por_recurso(cur):
    """Lugares de cada recurso con cuántas unidades tiene en cada uno, para el listado:
    {id: [{'ubicacion': 'Taller', 'cantidad': 4}, ...]} o {id: [{'ubicacion': 'Sin ubicar', ...}]}.
    Reusa lugares_recurso_agrupado por id; con ~90 recursos el costo extra es despreciable
    (mismo criterio que la búsqueda, ver agent_docs/gestion-conocimiento.md)."""
    ids = [r['id'] for r in cur.execute("SELECT id FROM recursos").fetchall()]
    return {rid: [{'ubicacion': g['ubicacion'], 'cantidad': len(g['numeros'])}
                  for g in lugares_recurso_agrupado(cur, rid)] for rid in ids}


def _resolver_ubicacion_existente(cur, rid, nombre):
    """Si ya hay una unidad de ESTE recurso cuyo lugar coincide sin importar mayúsculas ni
    acentos, devuelve el string tal como está guardado (para no fragmentar "Taller" y
    "taller " en dos grupos distintos). Si no hay ninguna, devuelve `nombre` recortado."""
    nombre = (nombre or '').strip()
    if not nombre:
        return nombre
    objetivo = texto.norm(nombre)
    filas = cur.execute(
        "SELECT DISTINCT ubicacion FROM recurso_unidades WHERE recurso_id = ? AND ubicacion != ''", (rid,)).fetchall()
    for fila in filas:
        if texto.norm(fila['ubicacion']) == objetivo:
            return fila['ubicacion']
    return nombre


def mover_unidades(cur, rid, destino, numeros=None, cantidad=None, origen=None):
    """Fija `destino` como lugar de unidades puntuales de un recurso.

    Por número exacto (`numeros`): mueve esas unidades; las que no existan en el recurso
    quedan en `avisos` y se ignoran, sin bloquear el resto. Por `cantidad` (sin decir cuáles):
    elige esa cantidad de candidatas, primero las que están en `origen` si se indicó, después
    las "sin ubicar", después cualquiera — si no hay suficientes, mueve las que haya y avisa,
    nunca rechaza el movimiento.
    """
    destino = _resolver_ubicacion_existente(cur, rid, (destino or '').strip())
    if not destino:
        return {'ok': False, 'error': 'Falta el lugar de destino.', 'avisos': []}

    todas = unidades_recurso(cur, rid)
    avisos = []

    if numeros:
        existentes = {u['numero'] for u in todas}
        elegidas = [n for n in numeros if n in existentes]
        invalidas = [n for n in numeros if n not in existentes]
        if invalidas:
            avisos.append(f'no existen las unidades {", ".join(str(n) for n in invalidas)} de este recurso: '
                          f'se ignoraron')
    else:
        cantidad = cantidad or 0
        origen = _resolver_ubicacion_existente(cur, rid, origen) if origen else ''
        candidatas = [u['numero'] for u in todas if u['ubicacion'] == origen] if origen else []
        candidatas += [u['numero'] for u in todas if u['ubicacion'] == '' and u['numero'] not in candidatas]
        candidatas += [u['numero'] for u in todas if u['numero'] not in candidatas]
        elegidas = candidatas[:cantidad]
        if len(elegidas) < cantidad:
            avisos.append(f'sólo se encontraron {len(elegidas)} unidades para mover, no {cantidad}')

    if not elegidas:
        return {'ok': False, 'error': 'No hay unidades para mover.', 'avisos': avisos}

    cur.executemany("UPDATE recurso_unidades SET ubicacion = ? WHERE recurso_id = ? AND numero = ?",
                    [(destino, rid, n) for n in elegidas])
    return {'ok': True, 'movidas': elegidas, 'avisos': avisos}


# Rutas propias (no son una entidad de ENTIDADES): mover unidades puntuales o dejarlas sin
# ubicar desde la ficha del recurso. Sin tope contra `recursos.cantidad` a propósito, mismo
# criterio de no bloquear.
@bp.route('/recursos/<int:id>/unidades/mover', methods=['POST'])
@accesos.requiere(PERMISO_ESCRITURA)
def unidad_mover(id):
    numeros = [_int(n) for n in request.form.get('numeros', '').split(',') if n.strip()]
    ubicacion = request.form.get('ubicacion', '').strip()
    if numeros and ubicacion:
        con = conectar()
        cur = con.cursor()
        cur.execute("SELECT 1 FROM recursos WHERE id = ?", (id,))
        if cur.fetchone():
            mover_unidades(cur, id, ubicacion, numeros=numeros)
            con.commit()
        con.close()
    return redirect(url_for('gestion.detalle', slug='recursos', id=id))


@bp.route('/recursos/<int:id>/unidades/quitar', methods=['POST'])
@accesos.requiere(PERMISO_ESCRITURA)
def unidad_quitar(id):
    # `numeros` (CSV) para la selección múltiple de la ficha; `numero` suelto sigue andando.
    nums = [_int(n) for n in request.form.get('numeros', '').split(',') if n.strip()]
    uno = _int(request.form.get('numero', ''))
    if uno:
        nums.append(uno)
    if nums:
        con = conectar()
        cur = con.cursor()
        cur.executemany("UPDATE recurso_unidades SET ubicacion = '' WHERE recurso_id = ? AND numero = ?",
                        [(id, n) for n in nums])
        con.commit()
        con.close()
    return redirect(url_for('gestion.detalle', slug='recursos', id=id))


# --- Kits: sub-recursos de un recurso ------------------------------------------
# `kit_items` es OPCIONAL a propósito, mismo criterio que `recurso_unidades`: un recurso
# es un "kit" en cuanto tiene sub-recursos cargados, no hay tipo/flag aparte. Cada
# sub-recurso es sólo título + cantidad + "recurso asignado" (texto libre, independiente
# de la tabla `recursos` — no es un link a otro recurso).

def kit_items_recurso(cur, rid):
    """Sub-recursos de un kit: [{'id','titulo','cantidad','recurso_asignado'}], por id de carga."""
    filas = cur.execute(
        "SELECT id, titulo, cantidad, recurso_asignado FROM kit_items WHERE recurso_id = ? ORDER BY id",
        (rid,)).fetchall()
    return [dict(f) for f in filas]


def agregar_kit_items(cur, recurso_id, items):
    """Inserta sub-recursos en lote: los usa el alta desde el chat (ver
    `agente/tools/fichas.py::_crear_entidad`) y la suma a un kit ya existente (ver
    `agente/tools/entidades.py::_editar_entidad`), que sólo juntan título + cantidad — el
    `recurso_asignado` de cada uno queda vacío, es un campo que sólo se completa a mano
    desde la web."""
    cur.executemany(
        "INSERT INTO kit_items (recurso_id, titulo, cantidad, recurso_asignado) VALUES (?,?,?,'')",
        [(recurso_id, item['titulo'], item.get('cantidad', '')) for item in items if item.get('titulo')])


def obtener_kit_item(cur, recurso_id, item_id):
    """Un sub-recurso puntual, o None si no existe (o no es de ese kit). Para el snapshot
    "antes" de editar/borrar desde el chat (ver `agente/tools/fichas.py`)."""
    fila = cur.execute(
        "SELECT id, titulo, cantidad, recurso_asignado FROM kit_items WHERE id = ? AND recurso_id = ?",
        (item_id, recurso_id)).fetchone()
    return dict(fila) if fila else None


def editar_kit_item(cur, recurso_id, item_id, titulo=None, cantidad=None, recurso_asignado=None):
    """Actualiza SOLO los campos que vienen (no None) de un sub-recurso puntual — edición
    parcial, igual criterio que `agente/tools/entidades.py::_editar_entidad` con el resto de
    una entidad. La ruta web (`kit_item_editar`) manda los tres siempre; el chat puede mandar
    sólo el que cambió. Devuelve True si el ítem existía (y en ese caso, en ese kit) y se
    actualizó, False si no.
    """
    actual = obtener_kit_item(cur, recurso_id, item_id)
    if not actual:
        return False
    cur.execute(
        "UPDATE kit_items SET titulo = ?, cantidad = ?, recurso_asignado = ? WHERE id = ? AND recurso_id = ?",
        (titulo if titulo is not None else actual['titulo'],
         cantidad if cantidad is not None else actual['cantidad'],
         recurso_asignado if recurso_asignado is not None else actual['recurso_asignado'],
         item_id, recurso_id))
    return True


def eliminar_kit_item(cur, recurso_id, item_id):
    """Borra un sub-recurso puntual. Devuelve True si existía (y en ese kit) y se borró."""
    cur.execute("DELETE FROM kit_items WHERE id = ? AND recurso_id = ?", (item_id, recurso_id))
    return cur.rowcount > 0


def buscar_kit_items(cur, q):
    """Sub-recursos de cualquier kit cuyo título matchea `q` (fuzzy, ver texto.puntaje_busqueda),
    puntuados y ordenados igual que el listado principal. Cada resultado trae también
    `kit_id`/`kit_nombre` para poder linkear al recurso que lo contiene."""
    q_norm = texto.norm(q)
    filas = cur.execute(
        "SELECT ki.id, ki.titulo, ki.cantidad, ki.recurso_asignado, "
        "ki.recurso_id AS kit_id, r.nombre AS kit_nombre "
        "FROM kit_items ki JOIN recursos r ON r.id = ki.recurso_id").fetchall()
    puntuadas = []
    for f in filas:
        puntaje = texto.puntaje_busqueda(q_norm, f['titulo'])
        if puntaje is not None:
            puntuadas.append((puntaje, dict(f)))
    puntuadas.sort(key=lambda par: (-par[0], texto.norm(par[1]['titulo'])))
    return [item for _, item in puntuadas]


@bp.route('/recursos/<int:id>/kit/agregar', methods=['POST'])
@accesos.requiere(PERMISO_ESCRITURA)
def kit_item_agregar(id):
    titulo = request.form.get('titulo', '').strip()
    cantidad = request.form.get('cantidad', '').strip()
    recurso_asignado = request.form.get('recurso_asignado', '').strip()
    if titulo:
        con = conectar()
        cur = con.cursor()
        cur.execute("SELECT 1 FROM recursos WHERE id = ?", (id,))
        if cur.fetchone():
            cur.execute(
                "INSERT INTO kit_items (recurso_id, titulo, cantidad, recurso_asignado) VALUES (?,?,?,?)",
                (id, titulo, cantidad, recurso_asignado))
            con.commit()
        con.close()
    return redirect(url_for('gestion.detalle', slug='recursos', id=id))


@bp.route('/recursos/<int:id>/kit/<int:item_id>/editar', methods=['POST'])
@accesos.requiere(PERMISO_ESCRITURA)
def kit_item_editar(id, item_id):
    titulo = request.form.get('titulo', '').strip()
    if titulo:
        con = conectar()
        editar_kit_item(con.cursor(), id, item_id, titulo,
                         request.form.get('cantidad', '').strip(),
                         request.form.get('recurso_asignado', '').strip())
        con.commit()
        con.close()
    return redirect(url_for('gestion.detalle', slug='recursos', id=id))


@bp.route('/recursos/<int:id>/kit/<int:item_id>/eliminar', methods=['POST'])
@accesos.requiere(PERMISO_ESCRITURA)
def kit_item_eliminar(id, item_id):
    con = conectar()
    eliminar_kit_item(con.cursor(), id, item_id)
    con.commit()
    con.close()
    return redirect(url_for('gestion.detalle', slug='recursos', id=id))

