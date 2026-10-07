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

Cada foto tiene además una miniatura (`fotos/mini/<uuid>.jpg`) para las grillas, que se
genera la primera vez que se pide y se borra junto con la foto (o al rotarla). Es
regenerable: perder la carpeta entera no pierde nada.
"""
import base64
import os
import uuid

from config import DIR_DATOS

FOTOS_DIR = os.path.join(DIR_DATOS, 'fotos')
MINI_DIR = os.path.join(FOTOS_DIR, 'mini')
MINI_LADO = 320

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
    _borrar(_ruta_mini(foto_id))


def eliminar(foto_id, tipo):
    """Borra el archivo de una foto (y su miniatura). No es error si ya no está."""
    _borrar(_ruta(foto_id, tipo))
    _borrar(_ruta_mini(foto_id))


def _borrar(archivo):
    try:
        os.remove(archivo)
    except FileNotFoundError:
        pass


def _ruta_mini(foto_id):
    return os.path.join(MINI_DIR, f"{foto_id}.jpg")


def ruta_mini(foto_id, tipo):
    """Ruta de la miniatura JPEG de una foto, generándola si todavía no existe. `None` si
    no se puede (no está la original, o Pillow no sabe abrirla, p. ej. HEIC): quien la
    pide sirve la original."""
    destino = _ruta_mini(foto_id)
    if os.path.exists(destino):
        return destino
    original = _ruta(foto_id, tipo)
    if not os.path.exists(original):
        return None
    try:
        from PIL import Image, ImageOps
        with Image.open(original) as img:
            img = ImageOps.exif_transpose(img)
            img.thumbnail((MINI_LADO, MINI_LADO))
            if img.mode != 'RGB':
                fondo = Image.new('RGB', img.size, 'white')
                fondo.paste(img, mask=img.convert('RGBA').split()[-1])
                img = fondo
            os.makedirs(MINI_DIR, exist_ok=True)
            # A un temporal y después rename: dos pedidos a la vez no dejan un JPEG a medias.
            temporal = f"{destino}.{uuid.uuid4().hex}.tmp"
            img.save(temporal, 'JPEG', quality=72, optimize=True)
        os.replace(temporal, destino)
        return destino
    except Exception:
        return None
