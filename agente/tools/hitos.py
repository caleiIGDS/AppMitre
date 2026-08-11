"""Tool de lectura de la línea del tiempo institucional (historia.db).

El CRUD genérico de `entidades.py` cubre la escritura de hitos; ésta cubre la consulta,
que necesita ordenar por nivel y filtrar por fecha.
"""
import crud
import historia
import texto
NIVEL_ORDEN = {'Crítico': 3, 'Importante': 2, 'Básico': 1}

def _buscar_hitos_fmt(etiqueta=None, desde_fecha=None, hasta_fecha=None, limite=50):
    """Busca hitos en la línea del tiempo institucional.

    Devuelve hitos ordenados por nivel (Crítico > Importante > Básico) y fecha (reciente primero).
    El agente puede filtrar según el contexto de la pregunta.
    """
    con = crud.conectar(historia)
    cur = con.cursor()

    query = "SELECT id, titulo, descripcion, fecha, tipo, nivel, etiquetas FROM hitos WHERE 1=1"
    params = []

    # Filtro por etiqueta (búsqueda en el campo etiquetas que es comma-separated)
    if etiqueta:
        etiqueta_norm = texto.norm(etiqueta)
        # Busca la etiqueta en el campo etiquetas (tolerando espacios)
        query += " AND (etiquetas LIKE ? OR etiquetas LIKE ?)"
        params.extend([f'%{etiqueta}%', f'%{etiqueta_norm}%'])

    # Filtro por rango de fechas
    if desde_fecha:
        query += " AND fecha >= ?"
        params.append(desde_fecha)
    if hasta_fecha:
        query += " AND fecha <= ?"
        params.append(hasta_fecha)

    # Ordenar: nivel DESC (Crítico > Importante > Básico), fecha DESC (reciente primero)
    query += " ORDER BY CASE nivel WHEN 'Crítico' THEN 3 WHEN 'Importante' THEN 2 ELSE 1 END DESC, fecha DESC LIMIT ?"
    params.append(limite + 1)  # +1 para detectar truncado

    filas = cur.execute(query, params).fetchall()
    con.close()

    truncado = len(filas) > limite
    hitos = []

    for fila in filas[:limite]:
        hito = dict(fila)
        # Parsear etiquetas (separated by comma)
        etiquetas_str = hito.get('etiquetas', '')
        hito['etiquetas'] = [e.strip() for e in etiquetas_str.split(',') if e.strip()]
        hitos.append(hito)

    resultado = {
        'total': len(hitos),
        'hitos': hitos,
        'instruccion': (
            'Estos hitos ya están ordenados por relevancia (nivel + fecha). '
            'Selecciona los más significativos según lo que preguntó el usuario. '
            'Evita abrumar: máximo 3-5 si es una pregunta casual, hasta 10 si es '
            'una búsqueda específica sobre logros.'
        )
    }

    if truncado:
        resultado['truncado'] = f'Se muestran los primeros {limite} de {len(filas)} totales.'

    return resultado
