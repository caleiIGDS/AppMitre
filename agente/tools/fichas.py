"""El alta en dos pasos: ficha -> confirmación del usuario -> escritura.

Ningún alta se escribe sin que el usuario haya visto antes, campo por campo, lo que va a
quedar guardado. Lo que hace que la confirmación signifique algo es que la ficha se
identifica por un hash de su CONTENIDO: si entre la ficha y el alta cambia aunque sea un
campo, el hash es otro y vuelve a pedir confirmación.

Es un guard de código y no una regla del system prompt a propósito: las reglas del prompt
este agente a veces las cumple y a veces no, y acá se escribe en el inventario real.
"""
import hashlib
import json
import crud
import gestion
from config import ahora

from ..db import conectar
from ..dominio import SLUGS_ENTIDAD, _modulo, ve_entidad
from ..padrones import _personas_cargadas, _personas_nombradas_en
PADRON_EN_AVISO = 40       # personas con ficha que se listan enteras en un aviso de tool

# ============================================================================
# Ejecutores de tools de ESCRITURA (auditados en agente_log)
# ============================================================================

# ---------------------------------------------------------------------------
# Alta en dos pasos: ficha → confirmación del usuario → escritura
# ---------------------------------------------------------------------------

# SLUGS_ENTIDAD y _modulo() están definidos arriba, junto a los imports de gestion/historia.

# Campos que el asistente REDACTA a partir de lo que contó el usuario, en vez de
# pedirlos literalmente ("¿qué descripción le pongo?"). Se marcan en la ficha para que
# el usuario sepa que ese texto lo escribió el asistente y lo lea con esa expectativa.
# 'titulo' es el 'nombre' de los hitos (ver crud.campo_nombre).
CAMPOS_REDACTADOS = ('nombre', 'titulo', 'tipo', 'descripcion')


def _campos_validos(slug):
    """Nombres de campo de la entidad, en el orden del formulario de /gestion o /historia."""
    cfg = _modulo(slug).ENTIDADES.get(slug) or {}
    return [c['nombre'] for c in cfg.get('campos', [])]


def _nombre_de(slug, campos):
    """El nombre visible de una ficha de alta.

    `campos` es el dict que armó el modelo, no una fila de la DB, así que acá **no** llega
    el alias de `crud.select()`: en `hitos` la clave es 'titulo'. Sin esto el botón de
    confirmar y el "✅ Guardado" salían con el nombre en blanco.
    """
    modulo = _modulo(slug)
    return campos.get(crud.campo_nombre(modulo.ENTIDADES.get(slug, {})), '')


def _normalizar_borrador(slug, campos_dict):
    """Deja solo los campos que existen en el slug, como texto y sin espacios de más.

    Normalizar acá y no al guardar es lo que hace comparable el token: la ficha que ve
    el usuario y la fila que se escribe salen del mismo dict.

    Además completa la fecha de revisión de los recursos con la de hoy si no vino: dar de
    alta un recurso ES un control de inventario. Se pone acá, antes de calcular el token,
    para que la fecha aparezca en la ficha y el usuario la vea (y la pueda cambiar) — si
    se agregara al guardar, se estaría escribiendo un campo que nadie aprobó. Va del lado
    del código y no como "acordate de poner la fecha" en el prompt, que es la clase de
    regla que el modelo cumple a veces.
    """
    borrador = {}
    for nombre in _campos_validos(slug):
        valor = campos_dict.get(nombre)
        if valor is None:
            continue
        valor = str(valor).strip()
        if valor:
            borrador[nombre] = valor

    if slug == 'recursos' and not borrador.get('fecha_revision'):
        borrador['fecha_revision'] = ahora().strftime(gestion.FORMATO_FECHA_REVISION)
    return borrador


def _token_ficha(slug, borrador):
    """Huella del contenido exacto de la ficha.

    Es lo que hace que la confirmación no se pueda despegar de lo que el usuario leyó:
    el token sale del contenido, así que si el modelo confirma con aunque sea un campo
    distinto del que mostró, el token no coincide y la tool vuelve a la ficha. Al ser
    derivado no hay que guardar estado en sesión ni en la DB.
    """
    crudo = slug + '|' + json.dumps(borrador, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(crudo.encode('utf-8')).hexdigest()[:10]


def _tipos_en_uso():
    """Categorías ya cargadas en el inventario.

    Van en la ficha para que el asistente reuse una existente en vez de inventar una
    nueva en cada alta: `tipo` es texto libre y sin esto se llena de sinónimos
    ("Herramienta"/"Herramientas"/"Herramienta manual") que no sirven para agrupar.
    """
    con = conectar()
    filas = con.execute(
        "SELECT DISTINCT tipo FROM recursos WHERE tipo IS NOT NULL AND TRIM(tipo) <> '' "
        "ORDER BY tipo COLLATE NOCASE"
    ).fetchall()
    con.close()
    return [f[0] for f in filas]


def _recordatorio_hito(borrador, permisos):
    """Aviso para el modelo cuando una ficha de hito sale con agujeros evitables.

    Va acá y no (solo) en el system prompt porque llega como resultado de tool, en el
    mismo turno y con los nombres concretos: el modelo escribía "Pablo Errio y Ezequiel
    Toñanes" en el título y dejaba `protagonistas` vacío, y después le preguntaba al
    usuario la importancia que el usuario le acababa de decir.

    La mitad de `protagonistas` cruza el padrón de fichas, así que sale sólo con permiso
    para ver `personas`: si no, el aviso le pondría delante al modelo justo los nombres
    que el permiso esconde. El resto de los avisos (nivel, fecha, tipo) no depende de eso.
    """
    avisos = []

    if not borrador.get('protagonistas') and ve_entidad('personas', permisos):
        texto = (borrador.get('titulo', '') + ' ' + borrador.get('descripcion', ''))
        nombradas = _personas_nombradas_en(texto)
        if nombradas:
            avisos.append(
                'En el título/descripción de este hito nombrás a personas que YA están '
                'cargadas: ' + ', '.join(n for _, n in nombradas) + '. El campo '
                '`protagonistas` está VACÍO: completalo con esos nombres y volvé a llamar a '
                'crear_entidad. No se lo preguntes al usuario, ya te lo dijo.'
            )
        else:
            aviso = ('El campo `protagonistas` está vacío. Si el usuario nombró personas o '
                     'cursos (aunque los hayas puesto en el título), van ahí: completalo y '
                     'volvé a llamar a crear_entidad.')
            # El padrón completo, no una búsqueda: el usuario dice "nati" o "el Errio" y el
            # modelo no tiene con qué resolverlo. Teniendo los nombres a la vista, ata el
            # apodo solo, en vez de irse a buscar docentes a los horarios — que es otro
            # padrón y donde estas personas no están.
            cargadas = _personas_cargadas()
            if cargadas and len(cargadas) <= PADRON_EN_AVISO:
                aviso += (' Las personas CON FICHA hoy son: '
                          + ', '.join(n for _, n in cargadas) + '.')
            elif cargadas:
                aviso += (' Si nombró a alguien en particular, buscalo con '
                          "buscar_entidad('personas', ...).")
            if cargadas:
                aviso += (' Si el usuario nombró a una de ellas (aunque sea por apodo o solo '
                          'el nombre de pila), es esa: no la busques con buscar_profesor, que '
                          'son los docentes de los horarios y es otro padrón.')
            avisos.append(aviso)

    for campo, etiqueta in (('nivel', 'nivel'), ('fecha', 'fecha'), ('tipo', 'tipo')):
        if not borrador.get(campo):
            avisos.append(
                f'Falta `{etiqueta}`. Si el usuario ya lo dijo en la conversación, cargalo y '
                f'volvé a llamar a crear_entidad; recién si NO lo dijo, preguntáselo.'
            )
    return avisos


def _ficha_confirmacion(slug, borrador, token, contexto_turno, permisos):
    """Paso 1 del alta: la ficha para mostrarle al usuario. No escribe nada."""
    cfg = _modulo(slug).ENTIDADES.get(slug) or {}
    etiquetas = {c['nombre']: c.get('label', c['nombre']) for c in cfg.get('campos', [])}
    nombres = _campos_validos(slug)

    ficha, vacios = {}, []
    for nombre in nombres:
        label = etiquetas.get(nombre, nombre)
        ficha[label] = borrador.get(nombre, '')
        if not borrador.get(nombre):
            vacios.append(label)

    # Se anota la ficha generada en este turno: sirve para rechazar una confirmación que
    # llegue sin que el usuario haya podido verla (ver _crear_entidad) y para que el
    # endpoint de chat le pase al front el botón de confirmar.
    #
    # Es un dict con TODAS las del turno, no la última: "creá a Pablo y a Ezequiel" arma dos
    # fichas en un solo turno y las dos necesitan su botón (ver _confirmaciones).
    contexto_turno.setdefault('fichas_mostradas', {})[token] = {'slug': slug, 'campos': borrador}

    resultado = {
        'ok': False,
        'requiere_confirmacion': True,
        'ficha': ficha,
        'campos_vacios': vacios,
        'redactados_por_vos': [etiquetas.get(n, n) for n in CAMPOS_REDACTADOS if n in nombres],
        'instruccion': (
            'NO se creó nada todavía. Mostrale al usuario la ficha campo por campo, tal cual '
            'va a quedar guardada. Abajo, si hay campos vacíos o datos que valdría la pena '
            'sumar, hacele 1 a 3 preguntas cortas y concretas (medida, marca y modelo, dónde '
            'se guarda, cuántos hay). Aclarale que son opcionales: si no las contesta se '
            'guarda igual. NO le pidas que escriba "sí" ni "confirmo": debajo de tu mensaje '
            'le aparece un botón para guardar. Cerrá diciéndole que si está bien, lo confirme '
            'con ese botón. Si pide cambios, volvé a llamar a crear_entidad con los campos '
            'corregidos y te devuelve la ficha nueva (con su botón). '
            'Si te pidió dar de alta VARIAS cosas, llamá a crear_entidad una vez por cada una '
            'en este mismo turno y mostrá las fichas una abajo de la otra: cada una lleva su '
            'propio botón, así que el usuario las confirma por separado. Nunca dejes una sin '
            'armar "para el próximo turno".'
        ),
    }
    if slug == 'recursos':
        resultado['tipos_en_uso'] = _tipos_en_uso()
    if slug == 'hitos':
        avisos = _recordatorio_hito(borrador, permisos)
        if avisos:
            resultado['antes_de_mostrar'] = avisos
    return resultado


def _crear_entidad(slug, campos_dict, contexto_turno=None, permisos=frozenset()):
    """Alta de recurso/conjunto/actividad/hito/persona, en DOS PASOS.

    Primera llamada con un juego de campos: no toca la base, devuelve la ficha para que el
    asistente se la muestre al usuario. Segunda llamada con LOS MISMOS campos (ya en otro
    turno, después del OK): escribe.

    Lo que hace que la confirmación signifique algo es que la ficha se identifica por un
    hash de su CONTENIDO: si entre la ficha y el alta cambia aunque sea un campo, el hash
    es otro y vuelve a pedir confirmación — no se puede guardar algo distinto de lo que el
    usuario leyó, y "cambiame la ubicación" cae solo en el paso de revisión.

    Los hashes ya mostrados viajan en `contexto_turno['fichas_previas']`, que el endpoint
    de chat carga de la sesión y vuelve a guardar. Tiene que ser la SESIÓN y no el turno:
    los resultados de tools no se persisten en el historial, así que cuando el usuario
    contesta "dale" el modelo ya no tiene a la vista nada de la ficha anterior.

    Es un guard de código y no una regla del system prompt a propósito: las reglas del
    prompt este agente a veces las cumple y a veces no, y acá se escribe en el inventario
    real de la escuela.
    """
    if contexto_turno is None:
        contexto_turno = {}

    if slug not in SLUGS_ENTIDAD:
        return {'ok': False, 'error': f'Slug desconocido: {slug}. Usá {", ".join(SLUGS_ENTIDAD)}.'}
    modulo = _modulo(slug)
    # No es siempre 'nombre': en `hitos` el campo obligatorio se llama 'titulo'.
    campo_nombre = crud.campo_nombre(modulo.ENTIDADES[slug])
    if not campos_dict.get(campo_nombre):
        return {'ok': False, 'error': f'El campo "{campo_nombre}" es obligatorio.'}

    borrador = _normalizar_borrador(slug, campos_dict)
    token = _token_ficha(slug, borrador)
    previas = contexto_turno.setdefault('fichas_previas', {})

    # Si esta ficha exacta no se mostró en un turno anterior, el usuario no la aprobó.
    # (Una mostrada en ESTE turno tampoco cuenta: hasta que el loop no termina, el usuario
    # no vio una sola palabra — por eso se anotan aparte, en `fichas_mostradas`.)
    if token not in previas:
        return _ficha_confirmacion(slug, borrador, token, contexto_turno, permisos)

    # Se consume: si el asistente vuelve a llamar con los mismos campos, es un alta nueva
    # y arranca otra vez por la ficha, en vez de duplicar el recurso en silencio.
    previas.pop(token, None)

    con = crud.conectar(modulo)
    id_nuevo = crud.guardar_entidad(modulo, slug, borrador, con=con)
    con.close()

    if id_nuevo:
        return {'ok': True, 'id': id_nuevo, 'mensaje': f'Creado {slug} id={id_nuevo}'}
    return {'ok': False, 'error': f'Error al crear {slug}'}
