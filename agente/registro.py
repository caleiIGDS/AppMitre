"""Registro de uso del asistente: una fila por turno, en `agente.db`.

Qué se guarda: quién chateó, cuándo, con qué modelo, cuántos tokens costó (los del chat y
los del lector de fotos, que son dos APIs distintas), qué tools llamó, cuánto tardó, cómo
terminó, y el texto completo de la pregunta y la respuesta. Se guarda para siempre: el
material para corregir el prompt y las tools es justamente el histórico.

POR QUÉ UNA DB PROPIA Y NO `gestion.db`, donde están las otras tablas del agente: aquéllas
son efímeras (la conversación se barre a los 240 minutos, las fotos pendientes también) y
ésta crece sin techo. Dentro de `gestion.db` se la llevarían las 20 copias rotativas de
`respaldos.py`, multiplicando por veinte el peso del archivo de chats. Suelta, además, se
puede bajar sola para analizarla sin arrastrar el inventario. Ver dev-log/DECISIONS.md.

Esta DB NO tiene respaldo rotativo a propósito: es telemetría, perderla cuesta análisis y
no datos de la escuela. `actualizar.py` sí le hace la copia intocable del deploy, que es el
momento en que algo se puede romper.

`acceso_id` apunta a `dispositivos.id` de `accesos.db` pero es un entero suelto, SIN FK:
ninguna FK cruza de una DB a otra en esta app. Por eso se copia también `acceso_nombre` —
el dispositivo se puede renombrar o revocar y el registro tiene que seguir diciendo quién
era en ese momento.
"""
import json
import os
import sqlite3

import config as config_app
from config import ahora

from .dominio import RAIZ

DB_PATH = os.path.join(RAIZ, 'agente.db')

SCHEMA = """
CREATE TABLE IF NOT EXISTS agente_turnos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    sid TEXT NOT NULL,
    acceso_tipo TEXT,
    acceso_id INTEGER,
    acceso_nombre TEXT,
    origen TEXT NOT NULL,
    provider TEXT,
    modelo TEXT,
    vueltas INTEGER NOT NULL DEFAULT 0,
    tokens_entrada INTEGER NOT NULL DEFAULT 0,
    tokens_salida INTEGER NOT NULL DEFAULT 0,
    tokens_cache INTEGER NOT NULL DEFAULT 0,
    vision_llamadas INTEGER NOT NULL DEFAULT 0,
    vision_modelo TEXT,
    vision_entrada INTEGER NOT NULL DEFAULT 0,
    vision_salida INTEGER NOT NULL DEFAULT 0,
    ms INTEGER,
    pico INTEGER NOT NULL DEFAULT 0,
    fotos INTEGER NOT NULL DEFAULT 0,
    tools TEXT,
    estado TEXT NOT NULL DEFAULT 'ok',
    detalle_error TEXT,
    escritura_fantasma INTEGER NOT NULL DEFAULT 0,
    pregunta TEXT,
    respuesta TEXT
);

CREATE INDEX IF NOT EXISTS idx_turnos_fecha ON agente_turnos(fecha);
CREATE INDEX IF NOT EXISTS idx_turnos_sid ON agente_turnos(sid);
"""

# Los finales distintos que puede tener un turno (ver los `return` de llm.py). 'ok' es el
# único que no pide mirar nada: los otros cinco son las cinco formas de salir mal, y
# separarlas es la mitad del valor del registro — 'sin_tokens' se arregla recargando la
# cuenta, 'tope_salida' subiendo MAX_TOKENS_SALIDA, 'tope_iteraciones' es el modelo
# perdido en un loop de tools, y 'sin_respuesta' es el que hay que ir a leer.
ESTADOS = ('ok', 'error', 'sin_tokens', 'tope_iteraciones', 'tope_salida', 'sin_respuesta')


def conectar():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = conectar()
    con.executescript(SCHEMA)
    con.commit()
    con.close()


# Orden de las columnas del INSERT. Explícito y no un `**campos` suelto para que agregar una
# columna al SCHEMA sin sumarla acá se note al escribirlo, no al leer el panel vacío.
_COLUMNAS = (
    'fecha', 'sid', 'acceso_tipo', 'acceso_id', 'acceso_nombre', 'origen',
    'provider', 'modelo', 'vueltas',
    'tokens_entrada', 'tokens_salida', 'tokens_cache',
    'vision_llamadas', 'vision_modelo', 'vision_entrada', 'vision_salida',
    'ms', 'pico', 'fotos', 'tools', 'estado', 'detalle_error', 'escritura_fantasma',
    'pregunta', 'respuesta',
)

# Los contadores. Se normalizan a 0 antes de insertar y no se dejan en manos del
# `DEFAULT 0` del schema: como el INSERT nombra TODAS las columnas, un campo que no vino
# viaja como NULL explícito y el DEFAULT no llega a aplicarse — la fila reventaba contra el
# NOT NULL y se perdía entera.
_CONTADORES = ('vueltas', 'tokens_entrada', 'tokens_salida', 'tokens_cache',
               'vision_llamadas', 'vision_entrada', 'vision_salida',
               'pico', 'fotos', 'escritura_fantasma')


def registrar_turno(**campos):
    """Guarda un turno. NUNCA propaga: medir no puede voltear el chat.

    Un error acá (disco lleno, DB bloqueada, una columna que todavía no existe porque el
    server no reinició) tiene que costar una fila de telemetría, no el mensaje que la
    persona estaba escribiendo. Fuera de producción se imprime, que es la diferencia entre
    ver el problema y creer que el registro anda; en producción no, porque el texto de un
    error puede arrastrar contenido de la conversación al log del servidor.
    """
    try:
        campos.setdefault('fecha', ahora().strftime('%Y-%m-%d %H:%M:%S'))
        campos.setdefault('sid', '')
        campos.setdefault('origen', 'chat')
        campos.setdefault('estado', 'ok')
        for c in _CONTADORES:
            campos[c] = campos.get(c) or 0
        if isinstance(campos.get('tools'), (list, dict)):
            campos['tools'] = json.dumps(campos['tools'], default=str, ensure_ascii=False)
        valores = [campos.get(c) for c in _COLUMNAS]
        con = conectar()
        # El `finally` no es decorativo: sin él, un INSERT que falla deja la conexión
        # abierta con la transacción viva y SQLite le contesta "database is locked" a todo
        # el que venga después. Perder una fila de telemetría es aceptable; trabarle la DB
        # al resto de la app por perderla, no.
        try:
            con.execute(
                "INSERT INTO agente_turnos ({}) VALUES ({})".format(
                    ', '.join(_COLUMNAS), ', '.join('?' * len(_COLUMNAS))),
                valores)
            con.commit()
        finally:
            con.close()
    except Exception as e:
        if not config_app.PRODUCCION:
            print('[registro] no se pudo guardar el turno: '
                  '{}: {}'.format(type(e).__name__, e))


# ============================================================================
# Consultas del panel
# ============================================================================
# Todo se agrega con GROUP BY en SQL y no trayendo la tabla a Python (como hace
# `crud.lista`): ésta es la única tabla de la app que crece sin techo.
#
# Las cuatro agrupaciones que interesan salen de la MISMA consulta, cambiando la expresión
# del GROUP BY. El desglose baja siempre hasta `modelo`, `vision_modelo` y `pico` porque el
# costo depende de los tres (cada modelo tiene su precio y DeepSeek cobra el doble en
# horario pico) y recién después se pliega al grupo pedido: de eso se encarga quien llama,
# con los precios de `proveedores.py`. Agregar primero y cobrar después daría de menos.

_GRUPOS = {
    'dia': "substr(fecha, 1, 10)",
    'modelo': "COALESCE(provider, '?') || ' · ' || COALESCE(modelo, '?')",
    'acceso': "COALESCE(acceso_tipo, 'desconocido') || ':' || COALESCE(acceso_id, 0)",
    'total': "'todo'",
}


def agrupado(grupo='total', desde=None):
    """Turnos y tokens agrupados por día, modelo, acceso, o todo junto.

    `desde` es un 'YYYY-MM-DD' (o un timestamp entero): filtra por fecha. El grupo lo elige
    el código y nunca la URL — por eso un grupo desconocido revienta con KeyError en vez de
    caer a un default.
    """
    expr = _GRUPOS[grupo]
    donde, args = ('WHERE fecha >= ?', (desde,)) if desde else ('', ())
    con = conectar()
    filas = con.execute("""
        SELECT {} AS grupo,
               MAX(acceso_nombre) AS nombre,
               modelo, vision_modelo, pico,
               COUNT(*) AS turnos,
               SUM(tokens_entrada) AS entrada,
               SUM(tokens_salida) AS salida,
               SUM(tokens_cache) AS cache,
               SUM(vision_llamadas) AS vision_llamadas,
               SUM(vision_entrada) AS vision_entrada,
               SUM(vision_salida) AS vision_salida,
               SUM(CASE WHEN estado != 'ok' THEN 1 ELSE 0 END) AS fallidos,
               SUM(COALESCE(ms, 0)) AS ms,
               MAX(fecha) AS ultimo
        FROM agente_turnos
        {}
        GROUP BY grupo, modelo, vision_modelo, pico
    """.format(expr, donde), args).fetchall()
    con.close()
    return [dict(f) for f in filas]


def ultimos(limite=60, sid=None):
    """Los últimos turnos, o una conversación entera en orden cronológico.

    Con `sid` es "leer este chat de principio a fin", que es lo que se hace después de ver
    un turno raro en la lista; sin `sid` es la lista de novedades, más nuevo primero.
    """
    con = conectar()
    if sid:
        filas = con.execute(
            "SELECT * FROM agente_turnos WHERE sid = ? ORDER BY id ASC", (sid,)).fetchall()
    else:
        filas = con.execute(
            "SELECT * FROM agente_turnos ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
    con.close()
    return [dict(f) for f in filas]


def conversaciones(limite=40):
    """Una fila por chat, más reciente primero: para elegir cuál leer entero."""
    con = conectar()
    filas = con.execute("""
        SELECT sid,
               COUNT(*) AS turnos,
               MAX(acceso_nombre) AS nombre,
               MIN(fecha) AS inicio,
               MAX(fecha) AS fin,
               SUM(tokens_entrada + tokens_salida) AS tokens,
               SUM(CASE WHEN estado != 'ok' THEN 1 ELSE 0 END) AS fallidos
        FROM agente_turnos
        GROUP BY sid
        ORDER BY fin DESC
        LIMIT ?
    """, (limite,)).fetchall()
    con.close()
    return [dict(f) for f in filas]
