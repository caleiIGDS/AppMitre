"""CRUD genérico sobre las entidades de los dos módulos de dominio.

Todo pasa por `_modulo(slug)`, que resuelve si el slug vive en `gestion` o en `historia`.
Los dos exponen la misma superficie a propósito, así que el agente los trata igual sin
saber en cuál está parado.

El alta NO está acá: vive en `fichas.py`, porque es el único camino de escritura que se
hace en dos pasos.
"""
import crud
import texto

from ..dominio import SLUGS_ENTIDAD, _modulo, ve_entidad
from ..padrones import _gente_horarios_parecida

# Tope de resultados que se le mandan a Claude. La búsqueda difusa no acota: con una
# query sin match literal devuelve cualquier cosa que se parezca de escritura, y con
# query vacía devuelve la tabla entera. Más de esto es ruido que empuja al modelo a
# elegir alguno igual. El total real viaja aparte para que sepa que se recortó.
LIMITE_BUSQUEDA = 10
# Las descripciones del inventario son cortas (máx ~180 chars), así que cuando el match
# vino de ahí se manda entera en vez de recortar una ventana alrededor del término.
MAX_DESC_BUSQUEDA = 160
# Tope de `listar_todos`. Con 90 recursos el listado completo son ~500 tokens, menos de un
# tercio de lo que ya cuesta la lista de personas en cada turno, así que mandarlo entero es
# barato. Pero no escala para siempre: arriba de este número la tool se niega y pide afinar
# la búsqueda, para que el día que el inventario crezca degrade de forma predecible en vez
# de reventar el contexto en silencio.
LIMITE_LISTADO_COMPLETO = 400


def _clasificar_match(q_norm, nombre, descripcion):
    """Por qué esta fila entró en los resultados: substring en el nombre ('exacto'),
    substring en la descripción ('descripcion'), o solo parecido de escritura
    ('aproximado', con su similitud 0–1). `crud.buscar_entidad` ordena por
    puntaje pero lo descarta, así que sin esto Claude recibe un match literal y uno
    difuso de 0.6 con exactamente el mismo peso."""
    if not q_norm:
        return None, None
    if q_norm in texto.norm(nombre or ''):
        return 'exacto', None
    if descripcion and q_norm in texto.norm(descripcion):
        return 'descripcion', None
    # Acá ya sabemos que no hay substring en ninguno de los dos, así que
    # texto.puntaje_busqueda devuelve la similitud cruda (<1.0), no el 1.0+ratio.
    similitud = texto.puntaje_busqueda(q_norm, nombre or '', descripcion or '')
    return 'aproximado', round(similitud, 2) if similitud else None


def _buscar_entidad_fmt(slug, query):
    """Búsqueda de entidad (recursos, hitos, personas)."""
    if slug not in SLUGS_ENTIDAD:
        # Sin esto un slug mal escrito devolvía 0 resultados y el agente concluía
        # "no hay nada cargado" en vez de reintentar con el slug correcto.
        return {'error': f'Slug inválido: {slug}. Válidos: {", ".join(SLUGS_ENTIDAD)}'}
    resultados = crud.buscar_entidad(_modulo(slug), slug, query)
    q_norm = texto.norm(query or '')
    # Omitir campos vacíos para reducir ruido
    limpios = []
    for r in resultados[:LIMITE_BUSQUEDA]:
        limpio = {'id': r.get('id'), 'nombre': r.get('nombre')}
        if r.get('estado'):
            limpio['estado'] = r['estado']
        if r.get('ubicacion'):
            limpio['ubicacion'] = r['ubicacion']
        if r.get('tipo'):
            limpio['tipo'] = r['tipo']
        if r.get('_via_alias'):
            # Puesto por crud.buscar_entidad: no matcheó nombre ni descripción, solo el
            # campo oculto de alias (recursos). Se marca aparte para que el asistente sepa
            # que no es un match "aproximado" (typo) sino uno curado a propósito.
            match, similitud = 'alias', None
        else:
            match, similitud = _clasificar_match(q_norm, r.get('nombre'), r.get('descripcion'))
        if match:
            limpio['match'] = match
            if similitud is not None:
                limpio['similitud'] = similitud
            if match == 'descripcion':
                # Si no, el nombre llega sin relación visible con lo buscado (buscar
                # "cable" trae "Faniot arduino" porque lo dice la descripción).
                desc = (r.get('descripcion') or '').strip()
                limpio['descripcion'] = (desc[:MAX_DESC_BUSQUEDA] + '…'
                                         if len(desc) > MAX_DESC_BUSQUEDA else desc)
        limpios.append(limpio)

    salida = {'slug': slug, 'query': query, 'total': len(resultados), 'resultados': limpios}
    if len(resultados) > LIMITE_BUSQUEDA:
        salida['truncado'] = (f'Se muestran los {LIMITE_BUSQUEDA} mejores de {len(resultados)}. '
                              'Si no está el que buscás, afiná la búsqueda.')
    # El aviso apunta al fallback en vez de dejar que el modelo concluya solo: la búsqueda
    # compara strings, no significados, así que "no encontré" NO es lo mismo que "no existe"
    # (buscar "tester" no encuentra el Multímetro; "taladro" no encuentra la Agujereadora).
    if not resultados:
        salida['aviso'] = (f'No hay {slug} cuyo nombre o descripción coincida con "{query}". '
                           f'OJO: eso no significa que no exista — puede estar cargado con otro '
                           f'nombre. Antes de afirmar que no está, llamá a listar_todos("{slug}") '
                           f'y fijate vos mismo en la lista completa.')
    elif q_norm and all(x.get('match') == 'aproximado' for x in limpios):
        salida['aviso'] = (f'Ninguno contiene "{query}" en el nombre ni en la descripción: '
                           'entraron solo por parecido de escritura, así que probablemente '
                           'NINGUNO sea lo que se busca. No ofrezcas el más parecido como si '
                           f'fuera el correcto. Llamá a listar_todos("{slug}") para ver la lista '
                           'completa y recién ahí decidí si está o no.')

    # Buscar una persona mira SIEMPRE los dos padrones, en las dos direcciones. Este es el
    # espejo del cruce que hace `buscar_profesor`: quien pregunta por alguien no sabe —ni
    # tiene por qué saber— si esa persona tiene ficha propia o si solo figura en los
    # horarios. Sin esto, buscar "vazquez" en `personas` no devolvía nada y el modelo
    # concluía "no la tengo cargada", con VAZQUEZ NATALIA dando clases en la escuela.
    if slug == 'personas' and query:
        # El padrón de horarios no es solo docentes: incluye a los EMATP y las jefaturas,
        # y su cargo viaja con el nombre para que el aviso diga "CALEI (EMATP EERR)" en vez
        # de presentarlo como un docente más.
        gente = _gente_horarios_parecida(query)
        if gente:
            salida['en_horarios'] = [
                {'nombre': n, 'rol': rol} if rol else {'nombre': n} for n, rol in gente]
            listado = ', '.join(f'{n} ({rol})' if rol else n for n, rol in gente)
            if resultados:
                salida['aviso_horarios'] = (
                    'Además, en los HORARIOS hay gente que coincide con "' + query + '": '
                    + listado + '. Son otro padrón: pueden ser la misma persona '
                    'o no. Si de cuál se trata cambia lo que vas a hacer, preguntale al usuario.'
                )
            else:
                salida['aviso_horarios'] = (
                    'NO hay ficha de persona que coincida, pero en los HORARIOS sí hay: '
                    + listado + '. O sea que existe en la escuela, solo que sin '
                    'ficha propia. NO le digas al usuario que no la tenés. Si te está hablando '
                    'de horarios, resolvelo con esos nombres; si está armando un hito o una '
                    'semblanza, avisale que todavía no tiene ficha y ofrecé '
                    'crearla con crear_entidad.'
                )
    return salida


def _listar_todos_fmt(slug):
    """Todos los nombres de una entidad, para cuando la búsqueda por string no alcanza.

    Es el fallback de `buscar_entidad`: el modelo sabe que un "tester" es un multímetro y
    que la "Agujereadora de banco" es lo que casi todos llaman taladro, pero `texto.puntaje_busqueda`
    no — compara letras. Viendo la lista entera resuelve sinónimos, paráfrasis y jerga sin
    ningún diccionario que mantener, y sobre todo puede afirmar "no está" habiéndolo
    verificado, en vez de deducirlo de que la búsqueda no encontró nada.
    """
    if slug not in SLUGS_ENTIDAD:
        return {'error': f'Slug inválido: {slug}. Válidos: {", ".join(SLUGS_ENTIDAD)}'}

    modulo = _modulo(slug)
    con = crud.conectar(modulo)
    # Por crud.select(), no `SELECT id, nombre`: en `hitos` la columna se llama `titulo` y la
    # query cruda reventaba con "no such column: nombre".
    cfg = modulo.ENTIDADES[slug]
    campo = crud.campo_nombre(cfg)
    filas = con.execute(
        f"SELECT id, {campo} AS nombre FROM {cfg['tabla']} ORDER BY nombre COLLATE NOCASE").fetchall()
    con.close()

    # Las filas sin nombre no le dicen nada al modelo, pero esconderlas sin avisar haría
    # falsa la afirmación "estos son todos": van contadas aparte.
    items = [{'id': f['id'], 'nombre': f['nombre']} for f in filas if (f['nombre'] or '').strip()]
    sin_nombre = len(filas) - len(items)

    if len(items) > LIMITE_LISTADO_COMPLETO:
        return {'error': f'Hay {len(items)} {slug}: demasiados para listarlos completos. '
                         f'Usá buscar_entidad con un término más específico.',
                'total': len(items)}

    salida = {
        'slug': slug,
        'total': len(items),
        'items': items,
        'instruccion': (f'Estos son TODOS los {slug} cargados, la lista completa. Buscá entre '
                        'ellos el que corresponda a lo que pidió el usuario aunque lo haya '
                        'nombrado distinto (sinónimos, marcas, jerga del taller). Si ninguno '
                        'es lo que se pide, decí claramente que no está cargado: NO ofrezcas '
                        'el más parecido como si fuera el correcto. Para ver los datos de uno, '
                        'llamá a detalle_entidad con su id.'),
    }
    if sin_nombre:
        salida['sin_nombre'] = sin_nombre
    return salida


def _detalle_entidad_fmt(slug, id, permisos=frozenset()):
    """Detalle completo de una entidad.

    `permisos` filtra las RELACIONES: el slug propio ya lo chequeó `ejecutar_tool`, pero un
    hito que se puede ver lista igual las personas que participaron, y esos nombres son lo
    que esconde `historia.personas`. Mismo criterio que la ficha web (ver crud.detalle).
    """
    modulo = _modulo(slug)
    con = crud.conectar(modulo)
    cur = con.cursor()
    cfg = modulo.ENTIDADES.get(slug)
    if not cfg:
        return {'error': f'Slug inválido: {slug}'}

    # Por crud.select() para que la ficha siempre traiga `nombre`, se llame como se llame la
    # columna (en `hitos` es `titulo`): el modelo lee esa clave en todos los slugs.
    fila = cur.execute(f"{crud.select(cfg)} WHERE id = ?", (id,)).fetchone()
    if not fila:
        con.close()
        return {'error': f'No encontrado: {slug} id={id}'}

    # Relaciones
    secciones = modulo.secciones_detalle(slug, id, cur)
    secciones = [s for s in secciones if ve_entidad(s.get('slug'), permisos)]
    con.close()

    resultado = dict(fila)
    resultado['relaciones'] = {}
    for sec in secciones:
        # No todas las secciones son (id, nombre): la de "Por ubicación" trae
        # (ubicacion, cantidad) y sin este chequeo reventaba con KeyError 'id'.
        # La clave es el slug sólo si es una entidad real (así el modelo puede pasarla a
        # buscar_entidad/detalle_entidad). El desglose por ubicación no lo es: para esas
        # secciones manda el título, que dice qué son.
        clave = sec.get('slug') if sec.get('slug') in modulo.ENTIDADES else None
        clave = clave or sec.get('titulo') or 'otros'
        items = []
        for item in sec['items']:
            d = dict(item)
            if 'id' in d and 'nombre' in d:
                items.append({'id': d['id'], 'nombre': d['nombre']})
            else:
                items.append(d)
        resultado['relaciones'][clave] = items

    return resultado


def _editar_entidad(slug, id, campos_dict):
    """Editar recurso/hito/persona (edición PARCIAL).

    `crud.guardar_entidad` hace UPDATE de TODAS las columnas usando
    `campos_dict.get(n, '')`, porque nació del form de /gestion, que siempre postea el
    registro entero. Por el chat no es así: el usuario dice "ponele estado En reparación"
    y el modelo manda un solo campo — con lo cual descripción, ubicación, tipo y cantidad
    se guardarían vacíos. Por eso acá partimos de la fila actual y aplicamos encima solo
    lo que vino. Se arregla del lado del código y no pidiéndole al modelo que mande todos
    los campos, que es justo el tipo de regla que a veces cumple y a veces no.
    """
    modulo = _modulo(slug)
    con = crud.conectar(modulo)

    # Snapshot antes
    antes = crud.snapshot_entidad(modulo, slug, id, con=con)

    if not antes or not antes.get('fila'):
        con.close()
        return {'ok': False,
                'error': f'No existe {slug} id={id}. Buscá el id correcto con buscar_entidad.'}

    campos_merge = {k: v for k, v in dict(antes['fila']).items() if k != 'id'}
    for clave, valor in (campos_dict or {}).items():
        if valor is not None:
            campos_merge[clave] = valor

    # Guardar
    id_result = crud.guardar_entidad(modulo, slug, campos_merge, id=id, con=con)
    con.close()

    if id_result:
        return {'ok': True, 'id': id_result, 'antes': antes, 'mensaje': f'Editado {slug} id={id}'}
    else:
        return {'ok': False, 'error': f'Error al editar {slug} id={id}'}

def _vincular_entidad(slug_origen, id_origen, slug_destino, id_destino):
    """Vincular dos entidades vía relación M2M. Las relaciones son siempre intra-módulo
    (no hay ninguna cruzada entre gestion/recursos e historia/hitos-personas desde que se
    sacó `proyecto_recursos` — ver dev-log/DECISIONS.md), así que alcanza con el módulo
    del slug de origen para conectar."""
    modulo = _modulo(slug_origen)
    cfg_origen = modulo.ENTIDADES.get(slug_origen)
    if not cfg_origen:
        return {'ok': False, 'error': f'Slug inválido: {slug_origen}'}

    # Encontrar la relación M2M
    rel_config = None
    for rel in cfg_origen.get('relaciones', []):
        if rel['slug_ajeno'] == slug_destino:
            rel_config = rel
            break

    if not rel_config:
        return {'ok': False, 'error': f'No hay relación entre {slug_origen} y {slug_destino}'}

    tabla = rel_config['tabla']
    col_propia = rel_config['col_propia']
    col_ajena = rel_config['col_ajena']

    con = crud.conectar(modulo)
    resultado = crud.agregar_relacion_m2m(modulo, tabla, col_propia, col_ajena, id_origen, id_destino, con=con)
    con.close()

    if resultado:
        return {'ok': True, 'mensaje': f'Vinculado {slug_origen}[{id_origen}] ← {slug_destino}[{id_destino}]'}
    else:
        return {'ok': False, 'error': 'Error al vincular'}

def _desvincular_entidad(slug_origen, id_origen, slug_destino, id_destino):
    """Desvincular dos entidades (siempre intra-módulo, ver _vincular_entidad)."""
    modulo = _modulo(slug_origen)
    cfg_origen = modulo.ENTIDADES.get(slug_origen)
    if not cfg_origen:
        return {'ok': False, 'error': f'Slug inválido: {slug_origen}'}

    rel_config = None
    for rel in cfg_origen.get('relaciones', []):
        if rel['slug_ajeno'] == slug_destino:
            rel_config = rel
            break

    if not rel_config:
        return {'ok': False, 'error': f'No hay relación entre {slug_origen} y {slug_destino}'}

    tabla = rel_config['tabla']
    col_propia = rel_config['col_propia']
    col_ajena = rel_config['col_ajena']

    con = crud.conectar(modulo)
    resultado = crud.quitar_relacion_m2m(modulo, tabla, col_propia, col_ajena, id_origen, id_destino, con=con)
    con.close()

    if resultado:
        return {'ok': True, 'mensaje': f'Desvinculado {slug_origen}[{id_origen}] ↛ {slug_destino}[{id_destino}]'}
    else:
        return {'ok': False, 'error': 'Error al desvincular'}

def _eliminar_entidad(slug, id, nombre_confirmacion=None):
    """Eliminar entidad (recurso/hito/persona).

    `nombre_confirmacion` es obligatorio y debe coincidir con el nombre real de la fila:
    es una traba de CÓDIGO, no de prompt. Sin esto el modelo podía alucinar un id
    (llegó a borrar 'Panel solar 100W' id=1 creyendo que borraba un recurso de prueba
    que nunca existió) — ver DECISIONS 2026-08-04.
    """
    modulo = _modulo(slug)
    con = crud.conectar(modulo)
    cur = con.cursor()

    # Snapshot antes (obligatorio)
    antes = crud.snapshot_entidad(modulo, slug, id, con=con)
    if not antes:
        con.close()
        return {'ok': False, 'error': f'No encontrado: {slug} id={id}. No se borró nada.'}

    cfg = modulo.ENTIDADES.get(slug)
    if not cfg:
        con.close()
        return {'ok': False, 'error': f'Slug inválido: {slug}'}

    nombre_real = antes['fila'].get('nombre', '')
    if not nombre_confirmacion:
        con.close()
        return {'ok': False, 'error':
                f'Falta nombre_confirmacion. {slug} id={id} se llama "{nombre_real}". '
                f'Confirmá con el usuario que es eso lo que quiere borrar y reintentá '
                f'pasando nombre_confirmacion="{nombre_real}". No se borró nada.'}

    if texto.norm(nombre_confirmacion) != texto.norm(nombre_real):
        con.close()
        return {'ok': False, 'error':
                f'NO COINCIDE: pediste borrar "{nombre_confirmacion}" pero {slug} id={id} '
                f'es "{nombre_real}". No se borró nada. Buscá el id correcto con '
                f'buscar_entidad antes de reintentar.'}

    try:
        # Borrar relaciones M2M
        for tabla, columna in modulo.LIMPIEZA_M2M.get(slug, []):
            cur.execute(f"DELETE FROM {tabla} WHERE {columna} = ?", (id,))

        # Borrar la fila
        cur.execute(f"DELETE FROM {cfg['tabla']} WHERE id = ?", (id,))

        con.commit()
        con.close()

        return {'ok': True, 'mensaje': f'Eliminado {slug} id={id}', 'antes': antes}

    except Exception as e:
        con.rollback()
        con.close()
        return {'ok': False, 'error': f'Error al eliminar: {str(e)}', 'antes': antes}
