"""Clasificación de materias compartida por la app y las consultas externas."""
from . import config


TIPOS_MATERIA = {'te': config.TE, 'ct': config.CT, 'fg': config.TEO}


def especialidad(clase):
    return config.ESPECIALIDAD_CURSOS.get((str(clase['curso']), clase['division']), '')


def tipo_materia(clase):
    plan = config.MATERIAS_PLAN.get((str(clase['curso']), especialidad(clase)), {})
    return plan.get(clase['materia'], ('', ''))[1]


def clave_tipo(clase):
    tipo = tipo_materia(clase)
    return next((clave for clave, etiqueta in TIPOS_MATERIA.items() if etiqueta == tipo), '')
