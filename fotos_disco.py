"""Almacenamiento en disco de las fotos de las entidades — capa 0, no nombra ninguna tabla
ni entidad: sólo sabe escribir/leer/borrar un archivo a partir de un uuid hex y un tipo
MIME. La usan `crud.py` (agregar/servir/eliminar/rotar fotos, capa 1) y `actualizar.py`
(migración de fotos viejas en base64) — actualizar.py no puede pasar por crud.agregar_foto
porque ese migrador recorre CUALQUIER .db sin un objeto `area` por tabla.

Un archivo por foto, todos en un directorio plano (`database/fotos/`): el nombre ya es
único (uuid4 hex) así que subcarpetear por inventario no agrega nada y sólo complica el
borrado y la migración. A esta escala (algunos miles de fotos) no hay problema de límite
de archivos por carpeta.

Los archivos NO entran en la rotación de `respaldos.py` — ver dev-log/DECISIONS.md: son
inmutables por diseño (rotar reemplaza el archivo, no lo versiona) y esa rotación está
pensada para una DB que muta fila a fila.
"""
import base64
import os
import uuid

from config import DIR_DATOS

FOTOS_DIR = os.path.join(DIR_DATOS, 'fotos')

_EXTENSIONES = {
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'image/webp': '.webp',
    'image/gif': '.gif',
    'image/heic': '.heic',
    'image/heif': '.heif',
}


def _extension(tipo):
    return _EXTENSIONES.get((tipo or '').split(';')[0].strip().lower(), '.jpg')


def _ruta(foto_id, tipo):
    return os.path.join(FOTOS_DIR, f"{foto_id}{_extension(tipo)}")


def ruta(foto_id, tipo):
    """Ruta absoluta del archivo de una foto (no garantiza que exista)."""
    return _ruta(foto_id, tipo)


def guardar(b64, tipo):
    """Decodifica un base64 y lo escribe en un archivo NUEVO. Devuelve el `foto_id`
    (uuid4 hex) recién creado."""
    os.makedirs(FOTOS_DIR, exist_ok=True)
    foto_id = uuid.uuid4().hex
    with open(_ruta(foto_id, tipo), 'wb') as f:
        f.write(base64.b64decode(b64))
    return foto_id


def reemplazar(foto_id, tipo_viejo, crudo, tipo_nuevo):
    """Reescribe el archivo de una foto YA existente (rotar), con el mismo `foto_id`.
    Si la extensión cambia (el tipo mime cambió), borra el archivo con la extensión
    vieja para no dejar huérfanos."""
    os.makedirs(FOTOS_DIR, exist_ok=True)
    if _extension(tipo_nuevo) != _extension(tipo_viejo):
        eliminar(foto_id, tipo_viejo)
    with open(_ruta(foto_id, tipo_nuevo), 'wb') as f:
        f.write(crudo)


def eliminar(foto_id, tipo):
    """Borra el archivo de una foto. No es error si ya no está."""
    try:
        os.remove(_ruta(foto_id, tipo))
    except FileNotFoundError:
        pass
