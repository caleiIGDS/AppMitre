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
    """Copia del historial con los bloques de imagen reemplazados por una nota.

    Una foto de etiqueta en base64 son varios MB: guardarla turno a turno engorda la fila
    y no aporta nada, porque el modelo ya la interpretó cuando llegó. (Con la cookie esto
    directamente rompía la sesión.)
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
        limpios.append({'role': msg.get('role'), 'content': bloques})
    return limpios


def _conv_borrar():
    con = conectar()
    con.execute("DELETE FROM agente_conversaciones WHERE sid = ?", (_sid(),))
    con.execute("DELETE FROM agente_fotos_pendientes WHERE sid = ?", (_sid(),))
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# Fotos esperando que se confirme el alta
# ---------------------------------------------------------------------------
# La foto llega en un turno y el alta se confirma en otro (o desde otra página, después
# de repintar el historial), así que hay que guardarla en el medio atada a la ficha que
# el usuario vio: la clave es el mismo token de contenido que usa `_crear_entidad`.
#
# Va en tabla propia y no dentro del JSON de `fichas` porque esa columna se reescribe
# entera en cada turno; con hasta FICHAS_MAX fotos en base64 adentro, cada mensaje del
# chat pasaría a arrastrar varios MB de escritura.

def _foto_pendiente_guardar(token, b64, tipo):
    con = conectar()
    con.execute(
        "INSERT INTO agente_fotos_pendientes (token, sid, b64, tipo, fecha) VALUES (?,?,?,?,?) "
        "ON CONFLICT(token) DO UPDATE SET b64=excluded.b64, tipo=excluded.tipo, "
        "fecha=excluded.fecha",
        (token, _sid(), b64, tipo, _ahora())
    )
    # Barrido de las que quedaron sin confirmar, con el mismo criterio que las
    # conversaciones abandonadas (ver _conv_guardar).
    con.execute("DELETE FROM agente_fotos_pendientes WHERE fecha < ?",
                ((ahora() - timedelta(days=CONVERSACION_DIAS)).strftime('%Y-%m-%d %H:%M:%S'),))
    con.commit()
    con.close()


def _foto_pendiente_tomar(token):
    """Devuelve (b64, tipo) de la foto de esa ficha y la borra. None si no hay."""
    con = conectar()
    fila = con.execute(
        "SELECT b64, tipo FROM agente_fotos_pendientes WHERE token = ? AND sid = ?",
        (token, _sid())
    ).fetchone()
    if fila:
        con.execute("DELETE FROM agente_fotos_pendientes WHERE token = ?", (token,))
        con.commit()
    con.close()
    return (fila['b64'], fila['tipo']) if fila else None
