"""Raíz del proyecto y resolución de slug -> módulo de dominio.

Lo más chico del paquete y de lo que más se importa: casi todo lo que toca una entidad
necesita saber si vive en `gestion` o en `historia`.
"""
import os

import accesos
import crud
import gestion
import historia

# El paquete vive en AppMitre/agente/, así que la raíz del proyecto —donde están los JSON
# de historias y `agente.md`— es el directorio de ARRIBA. Cuando esto era un módulo suelto
# alcanzaba con dirname(abspath(__file__)); al bajar un nivel hay que volver a subirlo, o
# las rutas apuntarían a AppMitre/agente/. Las bases NO salen de acá: van por
# `config.DIR_DATOS`, que es `database/` para todo el mundo.
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Módulos de dominio que el agente puede leer/escribir, por slug de entidad. Antes todo
# vivía en gestion.db; ahora recursos sigue en gestion.py y hitos/personas se separaron
# a historia.py (DB propia). SLUGS_ENTIDAD y _modulo()
# abajo son lo que le permite al agente seguir tratando ambos grupos de forma uniforme.
#
# Un área apagada (`ACTIVA = False`, hoy historia) no aporta ningún slug: es de acá que
# sale el enum de las tools, así que sus entidades dejan de existir para el modelo.
SLUGS_ENTIDAD = list(gestion.ENTIDADES) + (list(historia.ENTIDADES) if historia.ACTIVA else [])


def _modulo(slug):
    """Módulo (gestion o historia) dueño de `slug`, para resolver conexión/ENTIDADES."""
    return historia if slug in historia.ENTIDADES else gestion


def ve_entidad(slug, permisos):
    """¿Un acceso con estos `permisos` puede ver `slug`?

    Una entidad puede pedir un permiso propio además del del área (hoy `personas`, que es
    sólo del admin — ver `crud.permiso_entidad`). El agente lee las mismas tablas que la
    web, así que tiene que respetar lo mismo: si no, esconder `personas` de `/historia` no
    serviría de nada, alcanzaría con preguntárselo a Emilio.

    Toma los permisos por parámetro y no de la sesión porque el agente los resuelve una vez
    por turno y los baja al ejecutor, fuera del ciclo request/response (igual que
    `accesos.tiene`).

    Un slug que no está en SLUGS_ENTIDAD es NO, y ahí no hay permiso que valga: es el caso
    de un área apagada. Sin esto, el admin —que tiene el comodín '*'— seguiría cruzando
    nombres contra `personas` (ver tools/horarios.py) de un área que ya no existe.

    Se pide el permiso de LECTURA del área además del propio de la entidad, y eso importa
    desde que gestión son varios inventarios: `gestion.leer` sólo vale adentro del que está
    abierto (ver gestion.PERMISOS_AMBITO), así que es lo que distingue "puede ver recursos"
    de "puede ver los recursos DE ESTE inventario". Sin inventario abierto no lo tiene
    nadie, y entonces no hay entidad de gestión que valga.
    """
    if slug and slug not in SLUGS_ENTIDAD:
        return False
    return all(accesos.tiene(permisos, p) for p in permisos_entidad(slug))


def permisos_entidad(slug):
    """Todo lo que hace falta para ver `slug`: el permiso base del área más el propio de la
    entidad, si declaró uno (`personas`). Frozenset vacío para un slug vacío."""
    if not slug or slug not in SLUGS_ENTIDAD:
        return frozenset()
    modulo = _modulo(slug)
    propio = crud.permiso_entidad(modulo, slug)
    return frozenset([modulo.PERMISO_LECTURA] + ([propio] if propio else []))
