"""Tools del pañol: quién se llevó qué, cuándo, y qué falta que devuelva.

Los préstamos son exclusivos del área de recursos, así que acá se importa `gestion`
directo y no se pasa por `_modulo`.
"""
import gestion
import texto

from ..db import conectar
from ..padrones import _puntaje_nombre

def _listar_prestamos_fmt(persona=None, solo_activos=True):
    """Lista de préstamos."""
    con = conectar()
    cur = con.cursor()
    sql = "SELECT * FROM prestamos"
    params = []
    if persona:
        sql += " WHERE persona LIKE ?"
        params = [f"%{persona}%"]
    sql += " ORDER BY fecha_salida DESC, id DESC"

    filas = cur.execute(sql, params).fetchall()

    activos = [f for f in filas if not f['fecha_devolucion']]
    devueltos = [f for f in filas if f['fecha_devolucion']]

    resumen = gestion._resumen_items(cur, [f['id'] for f in activos], solo_pendiente=True)
    resumen.update(gestion._resumen_items(cur, [f['id'] for f in devueltos]))

    con.close()

    resultado = []
    for f in (activos if solo_activos else filas):
        estado = 'EN PRÉSTAMO' if not f['fecha_devolucion'] else 'DEVUELTO'
        resultado.append({
            'id': f['id'],
            'persona': f['persona'],
            'destino': f['destino'],
            'fecha_salida': f['fecha_salida'],
            'estado': estado,
            'pendiente': resumen.get(f['id'], '')
        })

    return {'prestamos': resultado}

def _detalle_prestamo_fmt(prestamo_id):
    """Detalle de un préstamo con pendiente por ítem."""
    con = conectar()
    cur = con.cursor()

    fila = cur.execute("SELECT * FROM prestamos WHERE id = ?", (prestamo_id,)).fetchone()
    if not fila:
        con.close()
        return {'error': f'Préstamo no encontrado: id={prestamo_id}'}

    items_filas = cur.execute(
        "SELECT i.cantidad, i.cantidad_devuelta, i.recurso_id, r.nombre FROM prestamo_items i "
        "LEFT JOIN recursos r ON r.id = i.recurso_id WHERE i.prestamo_id = ? ORDER BY r.nombre COLLATE NOCASE",
        (prestamo_id,)
    ).fetchall()

    con.close()

    items = []
    pendiente_total = 0
    for it in items_filas:
        cant = gestion._int(it['cantidad'])
        devuelta = gestion._int(it['cantidad_devuelta'])
        pendiente = max(0, cant - devuelta)
        pendiente_total += pendiente
        items.append({
            'recurso_id': it['recurso_id'],
            'nombre': it['nombre'] or '(recurso eliminado)',
            'cantidad': cant,
            'devuelta': devuelta,
            'pendiente': pendiente
        })

    return {
        'id': prestamo_id,
        'persona': fila['persona'],
        'destino': fila['destino'],
        'notas': fila['notas'],
        'fecha_salida': fila['fecha_salida'],
        'fecha_devolucion': fila['fecha_devolucion'],
        'items': items,
        'pendiente_total': pendiente_total,
        'estado': 'EN PRÉSTAMO' if not fila['fecha_devolucion'] else 'DEVUELTO'
    }

def _resolver_recurso(cur, consulta):
    """Busca recursos por nombre tolerando acentos, mayúsculas y typos.

    El `LIKE '%x%'` crudo fallaba con "medidor de energía solar" porque en la base
    figura "Medidor de energia solar" (sin tilde) — el préstamo no se creaba y el
    modelo se quedaba sin saber por qué. Devuelve [(id, nombre)].
    """
    filas = cur.execute("SELECT id, nombre FROM recursos").fetchall()
    q = texto.norm(consulta)

    exactos = [(f[0], f[1]) for f in filas if texto.norm(f[1]) == q]
    if exactos:
        return exactos

    subs = [(f[0], f[1]) for f in filas if q in texto.norm(f[1]) or texto.norm(f[1]) in q]
    if subs:
        return subs

    difusos = []
    for f in filas:
        p = _puntaje_nombre(q, texto.norm(f[1]))
        if p >= 0.75:
            difusos.append((p, f[0], f[1]))
    difusos.sort(reverse=True)
    return [(i, n) for _, i, n in difusos[:5]]


def _crear_prestamo(persona, destino, notas, items_list):
    """Crear préstamo con ítems."""
    if not persona:
        return {'ok': False, 'error': 'Falta la persona que retira.'}

    if not items_list:
        return {'ok': False, 'error': 'Falta agregar ítems al préstamo.'}

    # Resolver nombres de recursos a ids
    con = conectar()
    cur = con.cursor()
    items_resueltos = {}   # rid -> cantidad. Dict y no lista: ver la consolidación de abajo
    avisos = []

    for item in items_list:
        recurso = item.get('recurso', '')
        pedido = item.get('cantidad', 1)
        cantidad = gestion._int(pedido)
        if cantidad < 0:
            # Una cantidad negativa entraba tal cual y dejaba un ítem con pendiente 0 en un
            # préstamo abierto: figuraba prestado sin nada que devolver.
            con.close()
            return {'ok': False, 'error': f'Cantidad inválida para "{recurso}": {pedido}. '
                                          f'No se creó el préstamo.'}
        cantidad = cantidad or 1

        # Si es un número, asumir es id
        if recurso.isdigit():
            rid = int(recurso)
        else:
            # Buscar por nombre (match exacto o LIKE)
            matches = _resolver_recurso(cur, recurso)
            if len(matches) == 0:
                con.close()
                return {'ok': False, 'error': f'Recurso no encontrado: "{recurso}". No se creó el préstamo.'}
            elif len(matches) > 1:
                opciones = [{'id': r[0], 'nombre': r[1]} for r in matches]
                con.close()
                return {
                    'ok': False,
                    'error': f'"{recurso}" es ambiguo, hay {len(matches)} recursos que coinciden. '
                             f'Preguntale al usuario cuál es antes de reintentar.',
                    'opciones': opciones
                }
            rid = matches[0][0]

        # Validar stock
        stock = gestion._stock(cur, rid)
        if stock is None:
            con.close()
            return {'ok': False, 'error': f'Recurso no existe: id={rid}'}

        # El mismo recurso puede venir repetido (el usuario lo nombró dos veces, o dos nombres
        # distintos cayeron en el mismo id). `prestamo_items` tiene UNIQUE(prestamo_id,
        # recurso_id): antes reventaba con el error crudo de SQLite. Se suman, que es lo que
        # el usuario quiso decir.
        if rid in items_resueltos:
            cantidad += items_resueltos[rid]
            avisos.append(f'el recurso {rid} venía repetido en la lista: se sumaron las cantidades')

        if stock > 0 and cantidad > stock:
            avisos.append(f'del recurso {rid} pediste {cantidad} pero hay {stock} en total: '
                          f'se prestaron {stock}')
            cantidad = stock

        # Aviso, no bloqueo: el stock del inventario puede estar desactualizado y el pañol
        # sabe mejor que la DB. Pero prestar la misma unidad dos veces tiene que decirse,
        # porque es la diferencia entre "quedan 5" y "quedan 5 en el papel".
        afuera = gestion.pendiente_afuera(cur, rid)
        if stock > 0 and afuera + cantidad > stock:
            avisos.append(f'OJO: del recurso {rid} ya hay {afuera} afuera en otros préstamos '
                          f'abiertos y el inventario dice {stock} en total — con este préstamo '
                          f'quedan {stock - afuera - cantidad} en el pañol. Avisale al usuario')

        items_resueltos[rid] = cantidad

    # Crear préstamo
    try:
        cur.execute(
            "INSERT INTO prestamos (persona, destino, notas, fecha_salida, fecha_devolucion) VALUES (?,?,?,?,'')",
            (persona, destino or '', notas or '', gestion._ahora())
        )
        pid = cur.lastrowid

        for rid, cant in items_resueltos.items():
            cur.execute(
                "INSERT INTO prestamo_items (prestamo_id, recurso_id, cantidad, cantidad_devuelta) VALUES (?,?,?, '0')",
                (pid, rid, str(cant))
            )
            # Paridad con el alta por web (`carrito_finalizar`): sin esto la ficha del recurso
            # decía "Disponible" y "En préstamo: Fulano" al mismo tiempo.
            gestion.sincronizar_estado(cur, rid)

        con.commit()
        con.close()

        mensaje = f'Préstamo creado id={pid}'
        if avisos:
            # Todo lo que salió distinto de lo pedido se avisa: si el modelo cantó "presté 10"
            # y salieron 4, el usuario tiene que enterarse ahora y no cuando falte material.
            mensaje += '. OJO: ' + '; '.join(avisos)
        return {'ok': True, 'prestamo_id': pid, 'mensaje': mensaje, 'ajustes': avisos}

    except Exception as e:
        con.rollback()
        con.close()
        return {'ok': False, 'error': f'Error al crear préstamo: {str(e)}'}

def _existe_prestamo(cur, prestamo_id):
    """El id existe? Los UPDATE de abajo no fallan cuando el WHERE no matchea nada, así que
    sin este chequeo un id inventado devolvía 'ok: devuelto' y el modelo lo cantaba como
    hecho. Un id que no existe es un error, no una devolución silenciosa."""
    return cur.execute("SELECT 1 FROM prestamos WHERE id = ?", (prestamo_id,)).fetchone() is not None


def _cierre(prestamo_id, mensaje_base):
    """Resultado de una devolución/reapertura contado como quedó, no como se pidió.
    Se llama SIEMPRE después del commit: relee el préstamo ya escrito.

    `_recalcular_estado` puede dejar el préstamo abierto (quedaba algo) o cerrarlo, y el
    mensaje tiene que decir cuál de las dos pasó: 'Devuelto préstamo id=N' a secas, después
    de devolver 1 de 4, se lee como que volvió todo.
    """
    detalle = _detalle_prestamo_fmt(prestamo_id)
    pendiente = detalle.get('pendiente_total', 0)
    estado = detalle.get('estado', '')
    if pendiente:
        faltan = ', '.join(f"{it['pendiente']}× {it['nombre']}" for it in detalle['items'] if it['pendiente'])
        mensaje = f'{mensaje_base}. SIGUE ABIERTO: falta que devuelvan {faltan}'
    else:
        mensaje = f'{mensaje_base}. No queda nada pendiente, el préstamo se cerró'
    return {'estado': estado, 'pendiente_total': pendiente, 'mensaje': mensaje}


def _finalizar_prestamo(prestamo_id, items_list=None):
    """Devolver préstamo (todo o parcial)."""
    con = conectar()
    cur = con.cursor()

    if not _existe_prestamo(cur, prestamo_id):
        con.close()
        return {'ok': False, 'error': f'No existe el préstamo id={prestamo_id}. No se registró '
                                      f'ninguna devolución. Buscá el id con listar_prestamos.'}

    if items_list is not None and not items_list:
        # None = "devolvé todo" (la tool se llamó sin `items`). [] = el modelo mandó una lista
        # y quedó vacía: eso NO es un pedido de devolver todo, y tratarlo como tal cerraba el
        # préstamo entero por un error de armado.
        con.close()
        return {'ok': False, 'error': f'Mandaste `items` vacío en el préstamo {prestamo_id}: no se '
                                      f'devolvió nada. Si querían devolver TODO, llamá sin `items`; '
                                      f'si es parcial, mandá los recurso_id de detalle_prestamo.'}

    if not items_list:
        # Devolver todo
        cur.execute("UPDATE prestamo_items SET cantidad_devuelta = cantidad WHERE prestamo_id = ?", (prestamo_id,))
        cur.execute(
            "UPDATE prestamos SET fecha_devolucion = ? WHERE id = ? AND fecha_devolucion = ''",
            (gestion._ahora(), prestamo_id)
        )
    else:
        # Devoluciones parciales
        no_encontrados = []
        sin_cantidad = []
        ya_estaban = []
        ajustados = []
        aplicados = []
        for item in items_list:
            rid = gestion._int(item.get('recurso_id'))
            cantidad = gestion._int(item.get('cantidad', 0))

            fila = cur.execute(
                "SELECT cantidad, cantidad_devuelta FROM prestamo_items WHERE prestamo_id = ? AND recurso_id = ?",
                (prestamo_id, rid)
            ).fetchone()

            if not fila:
                no_encontrados.append(rid)
                continue

            if cantidad <= 0:
                # 0, negativo o no numérico. Antes caía en el `else` mudo: la tool contestaba
                # "devuelto" con `aplicados: []` y nadie se enteraba de que no pasó nada.
                sin_cantidad.append(rid)
                continue

            pendiente = max(0, gestion._int(fila['cantidad']) - gestion._int(fila['cantidad_devuelta']))
            if not pendiente:
                # De este ítem ya había vuelto todo. Marcarlo "aplicado" hacía que devolver dos
                # veces lo mismo contestara ok las dos, y la segunda no cambiaba nada.
                ya_estaban.append(rid)
                continue
            if cantidad > pendiente:
                ajustados.append(f'de {rid} pediste {cantidad} pero sólo faltaban {pendiente}')
            nuevo = gestion._int(fila['cantidad_devuelta']) + min(cantidad, pendiente)
            cur.execute(
                "UPDATE prestamo_items SET cantidad_devuelta = ? WHERE prestamo_id = ? AND recurso_id = ?",
                (str(nuevo), prestamo_id, rid)
            )
            aplicados.append(rid)

        gestion._recalcular_estado(cur, prestamo_id)
        con.commit()
        con.close()

        cierre = _cierre(prestamo_id, f'Devolución parcial en el préstamo {prestamo_id}')
        problemas = []
        if no_encontrados:
            problemas.append(f'recurso_id {no_encontrados} no pertenece(n) a este préstamo')
        if sin_cantidad:
            problemas.append(f'recurso_id {sin_cantidad} vino(eron) sin cantidad válida (0 o negativa)')
        if ya_estaban:
            problemas.append(f'recurso_id {ya_estaban} ya estaba(n) devuelto(s) entero(s)')

        if problemas:
            return {
                'ok': False,
                'error': '; '.join(problemas) + f'. A esos NO se les aplicó nada (revisá con '
                         f'detalle_prestamo). Sí se aplicó a: {aplicados}. {cierre["mensaje"]}',
                'prestamo_id': prestamo_id,
                'aplicados': aplicados,
                **cierre
            }

        return {'ok': True, 'prestamo_id': prestamo_id, 'aplicados': aplicados,
                'ajustes': ajustados, **cierre}

    gestion._recalcular_estado(cur, prestamo_id)
    con.commit()
    con.close()

    return {'ok': True, 'prestamo_id': prestamo_id,
            **_cierre(prestamo_id, f'Devuelto entero el préstamo {prestamo_id}')}

def _reabrir_prestamo(prestamo_id, items_list=None):
    """Deshacer una devolución."""
    con = conectar()
    cur = con.cursor()

    if not _existe_prestamo(cur, prestamo_id):
        con.close()
        return {'ok': False, 'error': f'No existe el préstamo id={prestamo_id}. No se reabrió nada. '
                                      f'Buscá el id con listar_prestamos.'}

    if items_list is not None and not items_list:
        con.close()
        return {'ok': False, 'error': f'Mandaste `items` vacío en el préstamo {prestamo_id}: no se '
                                      f'reabrió nada. Si querías reabrirlo ENTERO, llamá sin `items`.'}

    if not items_list:
        # Reabrir todo
        cur.execute("UPDATE prestamo_items SET cantidad_devuelta = '0' WHERE prestamo_id = ?", (prestamo_id,))
        cur.execute("UPDATE prestamos SET fecha_devolucion = '' WHERE id = ?", (prestamo_id,))
    else:
        # Reabrir ítems específicos
        no_encontrados = []
        for item in items_list:
            rid = gestion._int(item.get('recurso_id'))
            existe = cur.execute(
                "SELECT 1 FROM prestamo_items WHERE prestamo_id = ? AND recurso_id = ?",
                (prestamo_id, rid)
            ).fetchone()
            if not existe:
                no_encontrados.append(rid)
                continue
            cur.execute(
                "UPDATE prestamo_items SET cantidad_devuelta = '0' WHERE prestamo_id = ? AND recurso_id = ?",
                (prestamo_id, rid)
            )
        gestion._recalcular_estado(cur, prestamo_id)
        con.commit()
        con.close()

        cierre = _cierre(prestamo_id, f'Reapertura parcial del préstamo {prestamo_id}')
        if no_encontrados:
            return {
                'ok': False,
                'error': f'recurso_id {no_encontrados} no pertenece(n) al préstamo {prestamo_id}. '
                         f'No se reabrió nada para esos ítems. {cierre["mensaje"]}',
                'prestamo_id': prestamo_id,
                **cierre
            }

        return {'ok': True, 'prestamo_id': prestamo_id, **cierre}

    gestion._recalcular_estado(cur, prestamo_id)
    con.commit()
    con.close()

    return {'ok': True, 'prestamo_id': prestamo_id,
            **_cierre(prestamo_id, f'Reabierto entero el préstamo {prestamo_id}')}

def _eliminar_prestamo(prestamo_id, persona_confirmacion=None):
    """Eliminar un préstamo (solo para cargas erróneas).

    `persona_confirmacion` obligatorio y verificado contra la fila real, misma traba de
    código que `_eliminar_entidad`.
    """
    con = conectar()
    cur = con.cursor()

    # Snapshot antes (incluye los ítems, que también se borran)
    fila = cur.execute("SELECT * FROM prestamos WHERE id = ?", (prestamo_id,)).fetchone()
    if not fila:
        con.close()
        return {'ok': False, 'error': f'Préstamo no encontrado: id={prestamo_id}. No se borró nada.'}

    persona_real = fila['persona'] or ''
    if not persona_confirmacion:
        con.close()
        return {'ok': False, 'error':
                f'Falta persona_confirmacion. El préstamo {prestamo_id} es de "{persona_real}". '
                f'Confirmá con el usuario y reintentá pasando persona_confirmacion="{persona_real}". '
                f'No se borró nada.'}

    if texto.norm(persona_confirmacion) != texto.norm(persona_real):
        con.close()
        return {'ok': False, 'error':
                f'NO COINCIDE: pediste borrar el préstamo de "{persona_confirmacion}" pero el '
                f'id={prestamo_id} es de "{persona_real}". No se borró nada.'}

    items_antes = [dict(r) for r in cur.execute(
        "SELECT * FROM prestamo_items WHERE prestamo_id = ?", (prestamo_id,)).fetchall()]
    antes = {'fila': dict(fila), 'items': items_antes}

    try:
        cur.execute("DELETE FROM prestamos WHERE id = ?", (prestamo_id,))
        cur.execute("DELETE FROM prestamo_items WHERE prestamo_id = ?", (prestamo_id,))

        # Borrar un préstamo abierto devuelve sus recursos al pañol de hecho; sin esto
        # quedaban 'Retirado' sin ningún préstamo que lo justificara.
        for it in items_antes:
            gestion.sincronizar_estado(cur, it['recurso_id'])

        con.commit()
        con.close()

        return {'ok': True, 'mensaje': f'Eliminado préstamo id={prestamo_id}', 'antes': antes}

    except Exception as e:
        con.rollback()
        con.close()
        return {'ok': False, 'error': f'Error al eliminar: {str(e)}', 'antes': antes}
