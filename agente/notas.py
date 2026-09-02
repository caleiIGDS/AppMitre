"""`agente.md`: el archivo de notas del asistente, en la raíz del proyecto.

Es el equivalente de un CLAUDE.md / AGENTS.md para Emilio: un markdown suelto con lo que
tiene que saber ESTOS DÍAS — que el pañol está en el aula 12 mientras arreglan el techo,
que la máquina de café no se carga como recurso, quién coordina las salidas este año, la
lista que la administración quiere tener a mano un par de semanas. Si viviera en
`prompt.py`, cada aviso costaría un deploy.

QUÉ ENTRA lo decide quien escribe, no el modelo. Es la libreta del administrador: si le
piden anotar algo, se anota y no se discute dónde "corresponde" que vaya. Lo único que
Emilio no hace es anotar por su cuenta lo que nadie le pidió.

NO VA EN GIT (está en `.gitignore`, como los `.db`) y eso no es un detalle: el agente lo
ESCRIBE con la tool `escribir_notas`, así que la copia del servidor se separa de la del
repo desde la primera nota. Un archivo que escriben git y la app a la vez no tiene arreglo
bueno: el próximo `git pull` te lo pisa o te deja un conflicto en producción. Suelto en el
disco del server, en cambio, sobrevive a todos los deploys sin tocarlo nadie.

CÓMO SE EDITA: entero y de una, igual que un CLAUDE.md. Desde `/agente/notas` (un textarea
con el archivo) o por chat, donde el agente lo reescribe completo copiando lo que ya estaba
—lo tiene a la vista en su propio prompt— y agregando o sacando el renglón que le pidieron.
No hay ids ni renglones numerados: es texto.

LA RED DE SEGURIDAD ES `agente.md.bak`. Reescribir el archivo entero es lo que hace simple
todo lo demás y lo que puede salir mal: el modelo tiene que copiar lo que no tocó, y un
descuido borra una nota que nadie pidió borrar. Cada escritura guarda antes la versión
anterior, y la página ofrece deshacer. Además, la escritura por chat queda en `agente_log`
con el texto completo de ANTES (ver `TOOLS_AUDITADAS`), que es el segundo respaldo.

QUIÉN LO VE: sólo los accesos con `agente.notas`, un permiso de verbo 'admin' (ver
`agente/__init__.py`). Por defecto, sólo la administración. Un preceptor que chatea no lee
una sola línea.
"""
import os
from datetime import datetime, timezone

from config import ahora

from .dominio import RAIZ

# El nombre es el que se pidió y el que se lee en la raíz al lado de `app.py`. Que exista
# también el paquete `agente/` no molesta: son un archivo y un directorio distintos.
RUTA = os.path.join(RAIZ, 'agente.md')
RUTA_BAK = RUTA + '.bak'

# El archivo entero viaja en CADA turno de quien tenga el permiso: son tokens que se pagan
# siempre, no cuando hacen falta. 4.000 caracteres son ~1.000 tokens sobre los ~15.000 del
# prompt; bastante más que eso ya compite con las reglas del prompt por la atención del
# modelo, que es peor que el costo.
LARGO_MAX = 4000


def leer():
    """El contenido del archivo, o '' si todavía no existe.

    Nunca propaga: si el archivo no se puede leer (permisos, disco), el asistente tiene que
    seguir contestando horarios. Una libreta ilegible es una molestia; un chat caído por
    una libreta ilegible es un problema.
    """
    try:
        with open(RUTA, encoding='utf-8') as f:
            return f.read().strip()
    except OSError:
        return ''


def modificado():
    """Cuándo se tocó por última vez, 'YYYY-MM-DD HH:MM' en hora de la escuela.

    El mtime es epoch UTC y el server de producción corre en UTC: pasarlo por
    `fromtimestamp` a secas mostraría la hora 3 horas adelantada, que es exactamente el bug
    que `config.ahora()` existe para evitar. El desfasaje se saca de `ahora()` en vez de
    repetir acá la resolución de zona horaria: así sigue siendo config quien la decide.
    """
    try:
        marca = os.path.getmtime(RUTA)
    except OSError:
        return None
    utc = datetime.now(timezone.utc).replace(tzinfo=None)
    desfasaje = ahora() - utc
    fecha = datetime.fromtimestamp(marca, timezone.utc).replace(tzinfo=None) + desfasaje
    return fecha.strftime('%Y-%m-%d %H:%M')


def hay_deshacer():
    return os.path.exists(RUTA_BAK)


def escribir(contenido, autor='admin'):
    """Reemplaza el archivo entero. Devuelve {'ok': True, ...} o el motivo del rechazo.

    Guarda la versión anterior en `agente.md.bak` ANTES de escribir: es el único camino de
    vuelta si quien reescribió (persona o modelo) se comió un renglón que no le pidieron.

    Devuelve `antes` para que la auditoría de `ejecutar_tool` lo levante, y el conteo de
    renglones de las dos versiones — que es lo que le permite al modelo darse cuenta solo
    de que borró algo que no quería.
    """
    contenido = (contenido or '').strip()
    if len(contenido) > LARGO_MAX:
        return {'ok': False,
                'error': f'El archivo quedaría en {len(contenido)} caracteres y el máximo '
                         f'es {LARGO_MAX}. No se guardó nada: son notas de estos días, no '
                         f'un documento — sacá lo que ya no corre.'}

    previo = leer()
    if contenido == previo:
        return {'ok': False, 'error': 'El contenido es idéntico al que ya estaba. No se '
                                      'escribió nada.'}

    try:
        if previo:
            with open(RUTA_BAK, 'w', encoding='utf-8') as f:
                f.write(previo)
        with open(RUTA, 'w', encoding='utf-8') as f:
            f.write(contenido + '\n' if contenido else '')
    except OSError as e:
        return {'ok': False, 'error': f'No se pudo escribir el archivo: {e}'}

    return {'ok': True,
            'autor': autor,
            'antes': previo,
            'renglones_antes': len([l for l in previo.splitlines() if l.strip()]),
            'renglones_ahora': len([l for l in contenido.splitlines() if l.strip()]),
            'caracteres': len(contenido)}


def deshacer():
    """Vuelve a la versión anterior. True si había algo que restaurar.

    El `.bak` se consume: deshacer dos veces seguidas no existe, y encadenarlo sería
    prometer un historial que este archivo no tiene.
    """
    if not os.path.exists(RUTA_BAK):
        return False
    try:
        with open(RUTA_BAK, encoding='utf-8') as f:
            previo = f.read()
        with open(RUTA, 'w', encoding='utf-8') as f:
            f.write(previo)
        os.remove(RUTA_BAK)
        return True
    except OSError:
        return False
