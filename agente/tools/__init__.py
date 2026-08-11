"""Las tools del agente: lo único que el modelo puede hacer.

Una tool vive en dos lugares que tienen que coincidir: su ESQUEMA (`esquemas.py`, lo
único que el modelo ve) y su EJECUTOR (el resto de los módulos de acá, agrupados por
área). `ejecutar_tool` es el puente entre los dos.

La descripción del esquema no es documentación para el que lee el código: es el manual
que el modelo lee en cada turno, y ahí está buena parte del comportamiento del agente.
"""
import json

from ..db import _ahora, conectar
from ..lore import (EXCUSA_SIN_HISTORIA, _cargar_historia_completa, _historia_fmt,
                    _instruccion_tono)
from .entidades import (_buscar_entidad_fmt, _desvincular_entidad, _detalle_entidad_fmt,
                        _editar_entidad, _eliminar_entidad, _listar_todos_fmt,
                        _vincular_entidad)
from .esquemas import TOOLS_SCHEMA
from .fichas import _crear_entidad
from .fotos import _adjuntar_foto_entidad, _leer_foto_fmt
from .hitos import _buscar_hitos_fmt
from .horarios import (_aulas_libres_fmt, _buscar_por_rol_fmt, _buscar_profesor,
                       _horario_aula_fmt, _horario_curso_fmt, _horario_profesor_fmt,
                       _preceptores_fmt)
from .prestamos import (_crear_prestamo, _detalle_prestamo_fmt, _eliminar_prestamo,
                        _finalizar_prestamo, _listar_prestamos_fmt, _reabrir_prestamo)

# ============================================================================
# Ejecutor de tools
# ============================================================================

def ejecutar_tool(tool_name, tool_input, contexto_turno=None):
    """Ejecuta una tool y retorna el resultado + snapshot 'antes' si aplica.

    `contexto_turno` es un dict que vive lo que dura UNA respuesta del asistente (varias
    tools seguidas). Sirve para lo que hay que decidir mirando el turno entero y no la
    llamada aislada — hoy: que el alta no se confirme en el mismo turno en que se generó
    la ficha, porque hasta que el loop no termina el usuario no vio nada.
    """
    if contexto_turno is None:
        contexto_turno = {}

    lectura = tool_name in [
        'buscar_profesor', 'buscar_por_rol', 'preceptores', 'horario_profesor',
        'horario_curso', 'horario_aula',
        'aulas_libres', 'buscar_entidad', 'listar_todos', 'detalle_entidad',
        'listar_prestamos', 'detalle_prestamo', 'consultar_historia', 'buscar_hitos',
        'leer_foto'   # no toca la base; lo que gasta es la API de visión, no el inventario
    ]

    try:
        if tool_name == 'buscar_profesor':
            resultado = _buscar_profesor(tool_input.get('query', ''))
        elif tool_name == 'buscar_por_rol':
            resultado = _buscar_por_rol_fmt(tool_input.get('rol'))
        elif tool_name == 'preceptores':
            resultado = _preceptores_fmt(tool_input.get('curso'), tool_input.get('division'),
                                         tool_input.get('preceptor'))
        elif tool_name == 'horario_profesor':
            resultado = _horario_profesor_fmt(tool_input.get('nombre', ''))
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
            resultado = _detalle_entidad_fmt(tool_input.get('slug', ''), tool_input.get('id', 0))
        elif tool_name == 'listar_prestamos':
            resultado = _listar_prestamos_fmt(tool_input.get('persona'))
        elif tool_name == 'detalle_prestamo':
            resultado = _detalle_prestamo_fmt(tool_input.get('prestamo_id', 0))
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
            resultado = _crear_entidad(
                tool_input.get('slug', ''),
                {k: v for k, v in tool_input.items() if k != 'slug'},
                contexto_turno)
        elif tool_name == 'leer_foto':
            resultado = _leer_foto_fmt(contexto_turno)
        elif tool_name == 'adjuntar_foto':
            resultado = _adjuntar_foto_entidad(
                tool_input.get('slug', ''), tool_input.get('id', 0), contexto_turno)
        elif tool_name == 'editar_entidad':
            resultado = _editar_entidad(tool_input.get('slug', ''), tool_input.get('id', 0), {k: v for k, v in tool_input.items() if k not in ['slug', 'id']})
        elif tool_name == 'vincular_entidad':
            resultado = _vincular_entidad(tool_input.get('slug_origen'), tool_input.get('id_origen'), tool_input.get('slug_destino'), tool_input.get('id_destino'))
        elif tool_name == 'desvincular_entidad':
            resultado = _desvincular_entidad(tool_input.get('slug_origen'), tool_input.get('id_origen'), tool_input.get('slug_destino'), tool_input.get('id_destino'))
        elif tool_name == 'crear_prestamo':
            resultado = _crear_prestamo(tool_input.get('persona', ''), tool_input.get('destino'), tool_input.get('notas'), tool_input.get('items', []))
        elif tool_name == 'finalizar_prestamo':
            resultado = _finalizar_prestamo(tool_input.get('prestamo_id', 0), tool_input.get('items'))
        elif tool_name == 'reabrir_prestamo':
            resultado = _reabrir_prestamo(tool_input.get('prestamo_id', 0), tool_input.get('items'))
        elif tool_name == 'eliminar_entidad':
            resultado = _eliminar_entidad(tool_input.get('slug', ''), tool_input.get('id', 0),
                                          tool_input.get('nombre_confirmacion'))
        elif tool_name == 'eliminar_prestamo':
            resultado = _eliminar_prestamo(tool_input.get('prestamo_id', 0),
                                           tool_input.get('persona_confirmacion'))
        else:
            resultado = {'ok': False, 'error': f'Tool desconocida: {tool_name}'}

        # Auditar si es escritura. La ficha de confirmación queda afuera: no tocó la base,
        # y `agente_log` existe para poder deshacer cambios reales, no para guardar borradores.
        es_ficha = isinstance(resultado, dict) and resultado.get('requiere_confirmacion')
        if not lectura and not es_ficha:
            con = conectar()
            cur = con.cursor()
            antes = resultado.pop('antes', None) if isinstance(resultado, dict) else None
            ok = resultado.get('ok', False) if isinstance(resultado, dict) else False

            cur.execute(
                "INSERT INTO agente_log (fecha, tool, entrada, antes, resultado, ok) VALUES (?,?,?,?,?,?)",
                (
                    _ahora(),
                    tool_name,
                    json.dumps(tool_input, default=str),
                    json.dumps(antes, default=str) if antes else None,
                    json.dumps(resultado, default=str),
                    1 if ok else 0
                )
            )
            con.commit()
            con.close()

        return resultado

    except Exception as e:
        resultado = {'ok': False, 'error': f'Excepción: {str(e)}'}
        if not lectura:
            con = conectar()
            cur = con.cursor()
            cur.execute(
                "INSERT INTO agente_log (fecha, tool, entrada, antes, resultado, ok) VALUES (?,?,?,?,?,?)",
                (_ahora(), tool_name, json.dumps(tool_input, default=str), None, json.dumps(resultado, default=str), 0)
            )
            con.commit()
            con.close()
        return resultado
