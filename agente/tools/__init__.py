"""Las tools del agente: lo único que el modelo puede hacer.

Una tool vive en dos lugares que tienen que coincidir: su ESQUEMA (`esquemas.py`, lo
único que el modelo ve) y su EJECUTOR (el resto de los módulos de acá, agrupados por
área). `ejecutar_tool` es el puente entre los dos.

La descripción del esquema no es documentación para el que lee el código: es el manual
que el modelo lee en cada turno, y ahí está buena parte del comportamiento del agente.
"""
import json

import accesos

from ..db import _ahora, conectar
from ..dominio import ve_entidad
from ..lore import (EXCUSA_SIN_HISTORIA, _cargar_historia_completa, _historia_fmt,
                    _instruccion_tono)
from ..vision import MODO_DEFAULT
from .entidades import (_buscar_entidad_fmt, _desvincular_entidad, _detalle_entidad_fmt,
                        _editar_entidad, _eliminar_entidad, _listar_todos_fmt,
                        _vincular_entidad)
from .esquemas import (PERMISO_POR_TOOL, TOOLS_ESCRITURA, TOOLS_FOTO, TOOLS_SCHEMA,
                       slug_visible, tools_permitidas)
from .fichas import _crear_entidad
from .fotos import _adjuntar_foto_entidad, _leer_foto_fmt
from .hitos import _buscar_hitos_fmt
from .horarios import (_aulas_libres_fmt, _buscar_por_rol_fmt, _buscar_profesor,
                       _horario_aula_fmt, _horario_curso_fmt, _horario_profesor_fmt,
                       _preceptores_fmt)
from .ubicaciones import _mover_ubicacion_fmt

# ============================================================================
# Ejecutor de tools
# ============================================================================

def _auditar(tool_name, tool_input, antes, resultado, ok):
    """Deja el rastro en `agente_log`, que es lo que permite deshacer un cambio."""
    con = conectar()
    con.execute(
        "INSERT INTO agente_log (fecha, tool, entrada, antes, resultado, ok) VALUES (?,?,?,?,?,?)",
        (_ahora(), tool_name, json.dumps(tool_input, default=str),
         json.dumps(antes, default=str) if antes else None,
         json.dumps(resultado, default=str), 1 if ok else 0))
    con.commit()
    con.close()


def ejecutar_tool(tool_name, tool_input, contexto_turno=None, permisos=None):
    """Ejecuta una tool y retorna el resultado + snapshot 'antes' si aplica.

    `contexto_turno` es un dict que vive lo que dura UNA respuesta del asistente (varias
    tools seguidas). Sirve para lo que hay que decidir mirando el turno entero y no la
    llamada aislada — hoy: que el alta no se confirme en el mismo turno en que se generó
    la ficha, porque hasta que el loop no termina el usuario no vio nada.

    `permisos` son los de QUIEN está pidiendo. Va como parámetro explícito y no adentro de
    `contexto_turno` porque ese dict es estado del turno, y una identidad ahí se lee como
    un dato más que cualquiera puede pisar sin darse cuenta.

    El chequeo de permiso acá es la segunda línea: la primera es no mandarle siquiera el
    esquema al modelo (`esquemas.tools_permitidas`). Esta cubre lo que no pasa por el
    modelo — `/agente/confirmar` — y el caso de que el modelo invente un nombre de tool.
    El default `None` es fail-closed: un call site nuevo que se olvide de pasar permisos
    falla cerrado y ruidoso, no abierto y en silencio.
    """
    if contexto_turno is None:
        contexto_turno = {}

    permisos = permisos or frozenset()
    permiso = PERMISO_POR_TOOL.get(tool_name)
    if permiso is None:
        return {'ok': False, 'error': f'Tool desconocida: {tool_name}'}

    lectura = tool_name not in TOOLS_ESCRITURA

    if not accesos.tiene(permisos, permiso):
        resultado = {'ok': False, 'error': 'Este acceso no tiene permiso para esa '
                                           'operación. No se ejecutó nada.'}
        # Un rechazo de escritura queda auditado: si aparece en /agente/log es que alguien
        # forjó el request o que el filtrado de esquemas tiene un agujero.
        if not lectura:
            _auditar(tool_name, tool_input, None, resultado, ok=False)
        return resultado

    # Segundo eje: la tool puede estar permitida y la ENTIDAD que le pasan no. `personas`
    # pide `historia.personas` (ver crud.permiso_entidad), y eso no se puede resolver con
    # PERMISO_POR_TOOL porque no depende de la tool sino del slug que venga en el input.
    for clave in ('slug', 'slug_origen', 'slug_destino'):
        slug = tool_input.get(clave)
        if slug and not ve_entidad(slug, permisos):
            resultado = {'ok': False,
                         'error': f'Este acceso no puede ver ni tocar "{slug}". No se '
                                  f'ejecutó nada: decíselo al usuario y no lo reintentes.'}
            if not lectura:
                _auditar(tool_name, tool_input, None, resultado, ok=False)
            return resultado

    try:
        if tool_name == 'buscar_profesor':
            resultado = _buscar_profesor(tool_input.get('query', ''), permisos)
        elif tool_name == 'buscar_por_rol':
            resultado = _buscar_por_rol_fmt(tool_input.get('rol'))
        elif tool_name == 'preceptores':
            resultado = _preceptores_fmt(tool_input.get('curso'), tool_input.get('division'),
                                         tool_input.get('preceptor'))
        elif tool_name == 'horario_profesor':
            resultado = _horario_profesor_fmt(tool_input.get('nombre', ''), permisos)
        elif tool_name == 'horario_curso':
            resultado = _horario_curso_fmt(tool_input.get('curso', ''), tool_input.get('division', ''))
        elif tool_name == 'horario_aula':
            resultado = _horario_aula_fmt(tool_input.get('aula', ''))
        elif tool_name == 'aulas_libres':
            resultado = _aulas_libres_fmt()
        elif tool_name == 'buscar_entidad':
            resultado = _buscar_entidad_fmt(tool_input.get('slug', ''), tool_input.get('query', ''))
        elif tool_name == 'listar_todos':
            resultado = _listar_todos_fmt(tool_input.get('slug', ''))
        elif tool_name == 'detalle_entidad':
            resultado = _detalle_entidad_fmt(tool_input.get('slug', ''),
                                             tool_input.get('id', 0), permisos)
        elif tool_name == 'consultar_historia':
            # Si pasan ID directamente, carga esa historia (de historias/*.json — lore, no
            # confundir con el módulo `historia` de hitos/personas, ver dev-log/DECISIONS.md)
            if tool_input.get('id'):
                historia_lore = _cargar_historia_completa(tool_input.get('id'))
                if historia_lore:
                    instruccion_tono = _instruccion_tono(
                        historia_lore.get('tono', 'reflexivo'),
                        historia_lore.get('estilo', 'primera persona'))
                    resultado = {
                        'modo': 'directo',
                        'historia': historia_lore,
                        'instruccion_tono': instruccion_tono
                    }
                else:
                    resultado = {
                        'modo': 'no_encontrado',
                        'nota': f'No existe la historia con ID "{tool_input.get("id")}". '
                                f'{EXCUSA_SIN_HISTORIA}'
                    }
            else:
                resultado = _historia_fmt(tool_input.get('tema', ''))
        elif tool_name == 'buscar_hitos':
            resultado = _buscar_hitos_fmt(
                etiqueta=tool_input.get('etiqueta'),
                desde_fecha=tool_input.get('desde_fecha'),
                hasta_fecha=tool_input.get('hasta_fecha'),
                limite=tool_input.get('limite', 50)
            )
        elif tool_name == 'crear_entidad':
            # `foto` y `sub_recursos` quedan AFUERA de los campos: no son columnas de la
            # entidad — `foto` es de qué imagen salió la ficha, `sub_recursos` son los
            # items del kit (ver fichas._ficha_confirmacion / fichas._crear_entidad).
            resultado = _crear_entidad(
                tool_input.get('slug', ''),
                {k: v for k, v in tool_input.items() if k not in ('slug', 'foto', 'sub_recursos')},
                contexto_turno, permisos, tool_input.get('foto'), tool_input.get('sub_recursos'))
        elif tool_name == 'leer_foto':
            resultado = _leer_foto_fmt(contexto_turno, tool_input.get('modo', MODO_DEFAULT),
                                       tool_input.get('foto'))
        elif tool_name == 'adjuntar_foto':
            resultado = _adjuntar_foto_entidad(
                tool_input.get('slug', ''), tool_input.get('id', 0), contexto_turno,
                tool_input.get('foto'))
        elif tool_name == 'editar_entidad':
            resultado = _editar_entidad(tool_input.get('slug', ''), tool_input.get('id', 0), {k: v for k, v in tool_input.items() if k not in ['slug', 'id']})
        elif tool_name == 'vincular_entidad':
            resultado = _vincular_entidad(tool_input.get('slug_origen'), tool_input.get('id_origen'), tool_input.get('slug_destino'), tool_input.get('id_destino'))
        elif tool_name == 'desvincular_entidad':
            resultado = _desvincular_entidad(tool_input.get('slug_origen'), tool_input.get('id_origen'), tool_input.get('slug_destino'), tool_input.get('id_destino'))
        elif tool_name == 'mover_ubicacion':
            resultado = _mover_ubicacion_fmt(tool_input.get('recurso', ''), tool_input.get('destino'),
                                             numeros=tool_input.get('numeros'), cantidad=tool_input.get('cantidad'),
                                             origen=tool_input.get('origen'))
        elif tool_name == 'eliminar_entidad':
            resultado = _eliminar_entidad(tool_input.get('slug', ''), tool_input.get('id', 0),
                                          tool_input.get('nombre_confirmacion'))
        else:
            resultado = {'ok': False, 'error': f'Tool desconocida: {tool_name}'}

        # Auditar si es escritura. La ficha de confirmación queda afuera: no tocó la base,
        # y `agente_log` existe para poder deshacer cambios reales, no para guardar borradores.
        es_ficha = isinstance(resultado, dict) and resultado.get('requiere_confirmacion')
        if not lectura and not es_ficha:
            antes = resultado.pop('antes', None) if isinstance(resultado, dict) else None
            ok = resultado.get('ok', False) if isinstance(resultado, dict) else False
            _auditar(tool_name, tool_input, antes, resultado, ok)

        return resultado

    except Exception as e:
        resultado = {'ok': False, 'error': f'Excepción: {str(e)}'}
        if not lectura:
            _auditar(tool_name, tool_input, None, resultado, ok=False)
        return resultado
