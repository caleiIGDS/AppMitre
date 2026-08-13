"""Tablas propias del agente, dentro de gestion.db.

Son auditoría y sesión, no datos de dominio: por eso viven en la DB de recursos y no
tienen una propia. `agente_log` guarda cada escritura con su snapshot "antes";
`agente_conversaciones` guarda el chat; `agente_fotos_pendientes` guarda la foto de la
que salió una ficha hasta que alguien la confirma.
"""
import json
import os
import secrets
import sqlite3
from datetime import timedelta

from config import ahora
from flask import session

from .dominio import RAIZ

DB_PATH = os.path.join(RAIZ, 'gestion.db')

SCHEMA = """
CREATE TABLE IF NOT EXISTS agente_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    tool TEXT NOT NULL,
    entrada TEXT NOT NULL,
    antes TEXT,
    resultado TEXT NOT NULL,
    ok INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS agente_conversaciones (
    sid TEXT PRIMARY KEY,
    actualizado TEXT NOT NULL,
    historial TEXT NOT NULL,
    entidad_actual TEXT,
    fichas TEXT
);

CREATE TABLE IF NOT EXISTS agente_fotos_pendientes (
    token TEXT PRIMARY KEY,
    sid TEXT NOT NULL,
    b64 TEXT NOT NULL,
    tipo TEXT NOT NULL,
    fecha TEXT NOT NULL
);
"""

# La conversación vive acá y no en la sesión de Flask, que es una cookie firmada: los
# navegadores descartan cookies de más de ~4093 bytes, y con el historial adentro el peor
# caso medido daba ~3.5KB — al pasarse, el browser tira la cookie SIN AVISAR y el usuario
# se queda deslogueado y sin conversación. En la cookie queda solo `agente_sid`.
HISTORIAL_GUARDADO = 60    # mensajes que se conservan en la DB (30 turnos)
HISTORIAL_AL_MODELO = 24   # mensajes que se le mandan al LLM por turno (12 turnos)
FICHAS_MAX = 20            # altas sin confirmar que se recuerdan a la vez
CONVERSACION_DIAS = 30     # a los N días sin uso, la conversación se descarta

# Fotos por mensaje. Cada una cuesta una llamada de visión y ~300 KB de subida: ocho son
# ~2,4 MB por el wifi de la escuela, que es una tanda de estantería y entra cómodo. Más que
# eso el POST se hace largo y el turno se llena de lecturas. `chat()` recorta y avisa en vez
# de rechazar el mensaje entero: perder las ocho primeras por mandar diez es peor.
FOTOS_MAX = 8

def conectar():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = conectar()
    cur = con.cursor()
    cur.executescript(SCHEMA)
    con.commit()
    con.close()

def _ahora():
    return ahora().strftime('%Y-%m-%d %H:%M:%S')


# ============================================================================
# Conversación del chat (server-side, en gestion.db)
# ============================================================================

def _sid():
    """Id de conversación del navegador actual. Es lo ÚNICO que va en la cookie."""
    sid = session.get('agente_sid')
    if not sid:
        sid = secrets.token_urlsafe(16)
        session['agente_sid'] = sid
        session.modified = True
    return sid


def _conv_cargar():
    """Historial, entidad de contexto y fichas pendientes de esta conversación.

    Devuelve siempre un dict completo: si no hay fila todavía (o el JSON quedó corrupto
    por una escritura a medias), arranca vacío en vez de reventar el chat.
    """
    con = conectar()
    fila = con.execute(
        "SELECT historial, entidad_actual, fichas FROM agente_conversaciones WHERE sid = ?",
        (_sid(),)
    ).fetchone()
    con.close()

    if not fila:
        return {'historial': [], 'entidad_actual': None, 'fichas': {}}
    try:
        historial = json.loads(fila['historial'] or '[]')
        fichas = json.loads(fila['fichas'] or '{}')
    except ValueError:
        historial, fichas = [], {}
    return {'historial': historial,
            'entidad_actual': fila['entidad_actual'],
            'fichas': fichas}


def _conv_guardar(historial, entidad_actual, fichas):
    """Persiste la conversación y limpia las que quedaron abandonadas."""
    con = conectar()
    con.execute(
        "INSERT INTO agente_conversaciones (sid, actualizado, historial, entidad_actual, fichas) "
        "VALUES (?,?,?,?,?) "
        "ON CONFLICT(sid) DO UPDATE SET actualizado=excluded.actualizado, "
        "historial=excluded.historial, entidad_actual=excluded.entidad_actual, "
        "fichas=excluded.fichas",
        (_sid(), _ahora(),
         json.dumps(historial[-HISTORIAL_GUARDADO:], default=str, ensure_ascii=False),
         entidad_actual,
         json.dumps(dict(list(fichas.items())[-FICHAS_MAX:]), default=str, ensure_ascii=False))
    )
    # Barrido de conversaciones viejas. Va acá y no en init_db() porque el server puede
    # estar meses sin reiniciar; la tabla tiene una fila por navegador, no pesa.
    con.execute("DELETE FROM agente_conversaciones WHERE actualizado < ?",
                ((ahora() - timedelta(days=CONVERSACION_DIAS)).strftime('%Y-%m-%d %H:%M:%S'),))
    con.commit()
    con.close()


def _sin_imagenes(mensajes):
    """Copia del historial con los bloques de imagen de `content` reemplazados por una nota.

    El bloque `type: image` es lo que ve el LLM — una foto de etiqueta en base64 son varios
    MB, y volver a mandársela al modelo en cada turno siguiente no aporta nada porque ya la
    interpretó cuando llegó. Por eso se limpia siempre antes de armar el contexto que se le
    manda. La imagen que sí se guarda para repintar el chat viaja aparte, en la clave
    `imagen` del mensaje (`{'b64', 'tipo'}`, ver `chat()`), que esta función preserva tal
    cual: no es parte de `content` y el LLM nunca la ve.
    """
    limpios = []
    for msg in mensajes:
        contenido = msg.get('content')
        if not isinstance(contenido, list):
            limpios.append(msg)
            continue
        bloques = [b if not (isinstance(b, dict) and b.get('type') == 'image')
                   else {'type': 'text', 'text': '[el usuario adjuntó una imagen]'}
                   for b in contenido]
        limpios.append({**msg, 'content': bloques})
    return limpios


def _conv_borrar():
    con = conectar()
    con.execute("DELETE FROM agente_conversaciones WHERE sid = ?", (_sid(),))
    con.execute("DELETE FROM agente_fotos_pendientes WHERE sid = ?", (_sid(),))
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# Fotos del lote, esperando que se confirmen las altas
# ---------------------------------------------------------------------------
# La foto llega en un turno y el alta se confirma en otro (o desde otra página, después de
# repintar el historial), así que hay que guardarla en el medio atada a algo que atraviese
# esa distancia.
#
# Ese "algo" es el NÚMERO de la foto dentro de la conversación, no el token de la ficha.
# Antes era el token —el hash del contenido de la ficha— y funcionaba mientras la ficha se
# confirmaba tal cual salía: en cuanto el usuario pide un cambio y el modelo la rearma, el
# hash es otro y la foto quedaba huérfana. El número, en cambio, lo arrastra el modelo
# (`crear_entidad(foto=3)`) y sobrevive a cualquier corrección. Ver dev-log/DECISIONS.md.
#
# La columna se sigue llamando `token` (es la PK de la tabla y no hace falta migrar nada),
# pero ahora guarda `sid:n`. Va en tabla propia y no dentro del JSON de `fichas` porque esa
# columna se reescribe entera en cada turno; con hasta FOTOS_MAX fotos en base64 adentro,
# cada mensaje del chat pasaría a arrastrar varios MB de escritura.

def _clave_foto(n):
    return f'{_sid()}:{n}'


def _fotos_lote_guardar(fotos):
    """Guarda las fotos de este turno y devuelve el número que le tocó a cada una.

    La numeración NO arranca de 1 en cada turno: sigue desde la última foto que quedó
    pendiente en esta conversación. Si arrancara de cero, mandar dos fotos nuevas mientras
    hay un lote a medio revisar pisaría las de ese lote — y el modelo ya venía hablando de
    "la foto 2" en el historial.
    """
    if not fotos:
        return []
    con = conectar()
    fila = con.execute(
        "SELECT token FROM agente_fotos_pendientes WHERE sid = ?", (_sid(),)
    ).fetchall()
    usados = [int(f['token'].rsplit(':', 1)[-1]) for f in fila
              if f['token'].rsplit(':', 1)[-1].isdigit()]
    base = max(usados) if usados else 0

    numeros = []
    for i, (b64, tipo) in enumerate(fotos, start=1):
        n = base + i
        con.execute(
            "INSERT INTO agente_fotos_pendientes (token, sid, b64, tipo, fecha) "
            "VALUES (?,?,?,?,?) ON CONFLICT(token) DO UPDATE SET b64=excluded.b64, "
            "tipo=excluded.tipo, fecha=excluded.fecha",
            (_clave_foto(n), _sid(), b64, tipo, _ahora()))
        numeros.append(n)

    # Barrido de las que quedaron sin confirmar, con el mismo criterio que las
    # conversaciones abandonadas (ver _conv_guardar).
    con.execute("DELETE FROM agente_fotos_pendientes WHERE fecha < ?",
                ((ahora() - timedelta(days=CONVERSACION_DIAS)).strftime('%Y-%m-%d %H:%M:%S'),))
    con.commit()
    con.close()
    return numeros


def _foto_lote_tomar(n):
    """Devuelve (b64, tipo) de la foto N de esta conversación y la borra. None si no hay."""
    if not n:
        return None
    clave = _clave_foto(n)
    con = conectar()
    fila = con.execute(
        "SELECT b64, tipo FROM agente_fotos_pendientes WHERE token = ? AND sid = ?",
        (clave, _sid())
    ).fetchone()
    if fila:
        con.execute("DELETE FROM agente_fotos_pendientes WHERE token = ?", (clave,))
        con.commit()
    con.close()
    return (fila['b64'], fila['tipo']) if fila else None


def _fotos_lote_borrar():
    """Tira las fotos que quedaron sin usar. Se llama al cerrar el lote."""
    con = conectar()
    con.execute("DELETE FROM agente_fotos_pendientes WHERE sid = ?", (_sid(),))
    con.commit()
    con.close()
