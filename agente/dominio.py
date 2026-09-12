"""Raíz del proyecto y resolución de slug -> módulo de dominio.

El paquete llegó a soportar dos módulos de dominio (`gestion` e `historia`); desde que
`/historia` se extrajo del código, sólo queda `gestion`. `_modulo()` se conserva como
función (en vez de usar `gestion` directo en cada call site) para que un área de dominio
nueva, si aparece, entre sin tocar `tools/`, `fichas.py` ni `entidades.py`.
"""
import os

import accesos
import crud
import gestion

# El paquete vive en AppMitre/agente/, así que la raíz del proyecto —donde está `agente.md`—
# es el directorio de ARRIBA. Cuando esto era un módulo suelto alcanzaba con
# dirname(abspath(__file__)); al bajar un nivel hay que volver a subirlo, o las rutas
# apuntarían a AppMitre/agente/. Las bases NO salen de acá: van por `config.DIR_DATOS`, que
# es `database/` para todo el mundo.
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Slugs de entidad que el agente puede leer/escribir. Hoy es sólo `gestion.ENTIDADES`
# (`recursos`); queda como lista derivada y no como constante a mano para que una entidad
# nueva de `gestion.py` entre sola, sin tocar acá.
SLUGS_ENTIDAD = list(gestion.ENTIDADES)


def _modulo(slug):
    """Módulo de dominio dueño de `slug`. Hoy siempre `gestion`."""
    return gestion


def ve_entidad(slug, permisos):
    """¿Un acceso con estos `permisos` puede ver `slug`?

    Toma los permisos por parámetro y no de la sesión porque el agente los resuelve una vez
    por turno y los baja al ejecutor, fuera del ciclo request/response (igual que
    `accesos.tiene`).

    Un slug que no está en SLUGS_ENTIDAD es NO, y ahí no hay permiso que valga.

    Se pide el permiso de LECTURA del área además del propio de la entidad (si declaró uno,
    ver `crud.permiso_entidad`), y eso importa desde que gestión son varios inventarios:
    `gestion.leer` sólo vale adentro del que está abierto (ver gestion.PERMISOS_AMBITO), así
    que es lo que distingue "puede ver recursos" de "puede ver los recursos DE ESTE
    inventario". Sin inventario abierto no lo tiene nadie, y entonces no hay entidad de
    gestión que valga.
    """
    if slug and slug not in SLUGS_ENTIDAD:
        return False
    return all(accesos.tiene(permisos, p) for p in permisos_entidad(slug))


def permisos_entidad(slug):
    """Todo lo que hace falta para ver `slug`: el permiso base del área más el propio de la
    entidad, si declaró uno. Frozenset vacío para un slug vacío."""
    if not slug or slug not in SLUGS_ENTIDAD:
        return frozenset()
    modulo = _modulo(slug)
    propio = crud.permiso_entidad(modulo, slug)
    return frozenset([modulo.PERMISO_LECTURA] + ([propio] if propio else []))
