"""Raíz del proyecto y resolución de slug -> módulo de dominio.

Lo más chico del paquete y de lo que más se importa: casi todo lo que toca una entidad
necesita saber si vive en `gestion` o en `historia`.
"""
import os

import accesos
import crud
import gestion
import historia

# El paquete vive en AppMitre/agente/, así que la raíz del proyecto —donde están las DB
# y los JSON de historias— es el directorio de ARRIBA. Cuando esto era un módulo suelto
# alcanzaba con dirname(abspath(__file__)); al bajar un nivel hay que volver a subirlo, o
# las rutas apuntarían a AppMitre/agente/ y SQLite crearía ahí una gestion.db vacía en vez
# de fallar, que es la clase de error que no se nota hasta que falta el inventario entero.
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Módulos de dominio que el agente puede leer/escribir, por slug de entidad. Antes todo
# vivía en gestion.db; ahora recursos/conjuntos/actividades siguen en gestion.py y
# hitos/personas se separaron a historia.py (DB propia). SLUGS_ENTIDAD y _modulo()
# abajo son lo que le permite al agente seguir tratando ambos grupos de forma uniforme.
SLUGS_ENTIDAD = list(gestion.ENTIDADES) + list(historia.ENTIDADES)


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
    `accesos.tiene`). Un slug desconocido no pide nada: quien lo valida es cada tool.
    """
    permiso = crud.permiso_entidad(_modulo(slug), slug) if slug else None
    return not permiso or accesos.tiene(permisos, permiso)
