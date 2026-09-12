"""Los esquemas de las tools: lo único que el modelo ve de cada herramienta.

Data pura, sin lógica. Está escrito en el formato de Anthropic ({name, description,
input_schema}); `llm._tools_openai` lo traduce al vuelo para los proveedores compatibles
con OpenAI, donde el JSON Schema es idéntico y sólo cambia el envoltorio.

Las descripciones son largas a propósito: no describen qué hace la función, le dicen al
modelo cómo comportarse ("nunca respondas un horario de memoria", "que devuelva una sola
clase es un resultado válido, no lo rellenes"). Acortarlas degrada al agente.

Al final del archivo está `PERMISO_POR_TOOL`, que dice qué permiso pide cada una, y
`tools_permitidas()`, la única puerta por la que estos esquemas salen hacia el modelo.
"""
import accesos
import crud
import gestion

from .. import PERMISO_NOTAS, PERMISO_VISION
from ..dominio import SLUGS_ENTIDAD, _modulo, permisos_entidad

# Slugs cuya entidad declaró `campo_alias` (hoy sólo `recursos`, ver gestion.py). Calculado
# y no a mano, mismo criterio que SLUGS_ENTIDAD: una entidad nueva con alias entra sola.
SLUGS_CON_ALIAS = [s for s in SLUGS_ENTIDAD if crud.campo_alias(_modulo(s).ENTIDADES[s])]

# ============================================================================
# Esquemas de tools para Claude
# ============================================================================

TOOLS_SCHEMA = [
    # LECTURA
    {
        'name': 'buscar_profesor',
        'description': ('Busca GENTE DE LOS HORARIOS por nombre aproximado —docentes y también '
                        'personal NO DOCENTE (EMATP, jefaturas de departamento, porteros)— y devuelve los '
                        'candidatos que más se parecen, ordenados por puntaje. Tolera errores de '
                        'tipeo, falta de tildes y nombre invertido ("andrea alvares" encuentra '
                        '"ALVAREZ ANDREA"). Usala cuando el usuario da un nombre incompleto o dudoso '
                        'y querés ofrecerle opciones. Si ya tenés el nombre, no hace falta: '
                        'horario_profesor también busca difuso. '
                        'Los que tienen cargo no '
                        'docente vienen con su `rol` al lado del nombre. Los PRECEPTORES no están '
                        'en este padrón: si el nombre coincide con alguno, te lo devuelve aparte '
                        'en `preceptores` y ahí seguís con la tool `preceptores`. '
                        'SI NO COINCIDE NADIE te devuelve `padron_completo` con los nombres de '
                        'toda la gente de los horarios: revisalo vos antes de decir que la '
                        'persona no está — la búsqueda compara letras y un apodo o una errata '
                        'grande no matchean. '
                        'Buscar por CARGO ("¿qué EMATP hay?") no es esta tool: es buscar_por_rol.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'query': {'type': 'string', 'description': 'Parte del nombre a buscar, como lo dijo el usuario'}
            },
            'required': ['query']
        }
    },
    {
        'name': 'buscar_por_rol',
        'description': ('Busca personal NO DOCENTE por su CARGO, no por su nombre: EMATP, '
                        'jefaturas de departamento, porteros. Es la tool de "¿qué EMATP hay?", '
                        '"¿quién es el EMATP de energías renovables?", "¿quién es la jefa de '
                        'exactas?". SIN parámetro devuelve el padrón completo de cargos, que es '
                        'corto. OJO CON LAS SIGLAS: los cargos están escritos como los cargó la '
                        'escuela ("EMATP EERR" es el EMATP de energías renovables), y esta '
                        'búsqueda compara letras, no significados. Si no encuentra el cargo por '
                        'el nombre que te dieron, te devuelve igual `padron_completo` con TODOS '
                        'los cargos: leelo y reconocé vos la sigla. Si ahí tampoco está, decí '
                        'que no está cargado — no ofrezcas el más parecido. Esta tool NO da '
                        'horarios (eso es horario_profesor) ni sabe de preceptores por curso '
                        '(eso es la tool preceptores).'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'rol': {'type': 'string', 'description': 'Cargo a buscar, como lo dijo el usuario ("ematp", "jefa de exactas"). Vacío = todos los cargos'}
            },
            'required': []
        }
    },
    {
        'name': 'preceptores',
        'description': ('Qué preceptor tiene cada curso, y qué cursos tiene cada preceptor. '
                        'Es la ÚNICA fuente de esto: los preceptores no dan clases, así que '
                        'horario_profesor no sabe nada de ellos. Los turnos son TRES (MAÑANA, '
                        'TARDE, VESPERTINO): cada curso viene con `turno_del_curso`, con '
                        '`titular` (el preceptor de ese turno) y con `contraturno`, que es una '
                        'LISTA con todos los demás y puede traer más de uno, en turnos distintos. '
                        'Si te preguntan "el preceptor" a secas, es el titular; si te preguntan '
                        'por un turno, mirá el campo `turno` de cada entrada en vez de suponer. '
                        'Tres formas de llamarla: (a) con `curso` y `division` para un curso '
                        '("¿quién es el preceptor de 3° B?"); (b) con `curso` solo, para todas '
                        'las divisiones de ese año; (c) con `preceptor` para dar vuelta la '
                        'pregunta ("¿qué cursos tiene Vanesa Romero?"), que resuelve el nombre '
                        'difuso y puede pedirte que desambigües con `sugerencias`. Sin ningún '
                        'parámetro devuelve la planilla ENTERA (64 cursos): usala así solo si la '
                        'pregunta es realmente sobre todos. `sin_asignar: true` significa que la '
                        'planilla no tiene preceptor cargado ahí — decilo así, no inventes un '
                        'nombre; `turnos_sin_nadie` lista los turnos que ese curso no tiene '
                        'cubiertos. Si el `preceptor` que buscás no coincide con nadie, te '
                        'devuelve `padron_completo` con todos los de la planilla: revisalo antes '
                        'de decir que no está (los nombres están cargados a mano y a veces dados '
                        'vuelta). Los cursos van como "3° B": el año y la división por separado.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'curso': {'type': 'string', 'description': 'Solo el número de año, "1" a "7". Sin el símbolo de grado'},
                'division': {'type': 'string', 'description': 'Solo la división: "A", "B", o un número como "1", "9". Opcional: sin esto trae todas las divisiones del año'},
                'preceptor': {'type': 'string', 'description': 'Nombre del preceptor, para preguntar al revés qué cursos tiene. Tolera aproximados y nombre invertido'}
            },
            'required': []
        }
    },
    {
        'name': 'horario_profesor',
        'description': ('ÚNICA fuente del horario de alguien que trabaja en la escuela: nunca respondas '
                        'un horario de memoria ni por deducción, ni siquiera para completar uno que ya '
                        'mostraste. Devuelve la '
                        'semana completa con día, hora, materia, curso y aula. Sirve igual para el '
                        'personal NO DOCENTE (EMATP, jefaturas, porteros): esa gente no tiene `clases` '
                        'sino `horario_no_docente` (franja de presencia por día) más `rol_no_docente`. '
                        'Hay quien tiene las dos cosas — da clases Y tiene un cargo no docente —; en ese '
                        'caso vienen los dos campos y un `aviso_no_docente`: contá los dos horarios, no '
                        'uno solo. Si el nombre no es exacto '
                        'busca difuso y puede responder de tres formas: (a) el horario más `nota_fuzzy` '
                        'si hubo un ganador claro — avisale al usuario a quién resolviste; (b) '
                        '`sugerencias` con varios candidatos parecidos, y ahí tenés que preguntar cuál '
                        'es en vez de elegir; (c) `padron_completo` con TODOS los nombres de los '
                        'horarios cuando no coincide nadie — revisalo vos ahí mismo antes de decirle '
                        'al usuario que la persona no está. Que devuelva '
                        'una sola clase, o ninguna, es un resultado válido y frecuente: informalo tal '
                        'cual, no lo rellenes. Las líneas que terminan en "Grupo A"/"Grupo B" son '
                        'clases de media división (talleres): el docente tiene a la mitad del curso.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'nombre': {'type': 'string', 'description': 'Nombre del docente o del no docente. Ideal el exacto de la base, pero tolera aproximados'}
            },
            'required': ['nombre']
        }
    },
    {
        'name': 'horario_curso',
        'description': ('Horario semanal de un curso (todas las materias que recibe esa división). '
                        'El curso y la división van SEPARADOS: "3° B" es curso="3", division="B". '
                        'Es la única fuente del horario de un curso, no lo deduzcas. Las líneas que '
                        'terminan en "Grupo A"/"Grupo B" son de media división: en talleres el curso '
                        'se parte en dos mitades con distinto docente y taller. Casi siempre van a la '
                        'misma hora (dos clases simultáneas con grupos distintos son correctas), pero '
                        'no siempre: a veces en ese horario hay un solo grupo.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'curso': {'type': 'string', 'description': 'Solo el número de año, "1" a "7". Sin el símbolo de grado'},
                'division': {'type': 'string', 'description': 'Solo la división: "A", "B", "C", o un número como "1", "8"'}
            },
            'required': ['curso', 'division']
        }
    },
    {
        'name': 'horario_aula',
        'description': ('Horario semanal de un aula o taller: qué se dicta ahí, cuándo, con qué curso y '
                        'qué docente. Sirve para "¿quién da clase en el aula 21 los martes a las 10?" — '
                        'traé la semana y filtrá vos el día y la hora. Única fuente, no la deduzcas. '
                        'Si una línea dice "Grupo A"/"Grupo B", ese taller lo cursa media división.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'aula': {'type': 'string', 'description': 'Código tal como está en la base: "21", "T3", "PATIO", "GYM". Los talleres van sin espacio ("T2", no "Taller 2")'}
            },
            'required': ['aula']
        }
    },
    {
        'name': 'coincidencias',
        'description': ('Cuándo varias entidades coinciden en la escuela: la ÚNICA fuente para '
                        '"en qué horario coinciden", "cuándo están juntos", "cuándo se cruzan", '
                        '"comparar los horarios de". Mezcla cursos y personas (docentes, '
                        'preceptores, no docentes) en la misma consulta, desde DOS entidades en '
                        'adelante. Devuelve una grilla con todos los horarios alineados en el '
                        'mismo eje y los tramos coincidentes YA CALCULADOS: no cruces vos los '
                        'horarios sacando dos o tres `horario_curso` sueltos, que es lo que hay '
                        'que evitar. Si te preguntan por una sola entidad, esa va por '
                        '`horario_curso` o `horario_profesor`.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'cursos': {'type': 'array', 'items': {'type': 'string'},
                           'description': 'Cursos como los dijo el usuario: "2do C", "6to 5ta", "4to 9na", "1° A". Tolera ordinales, no hace falta traducirlos'},
                'personas': {'type': 'array', 'items': {'type': 'string'},
                             'description': 'Docentes, preceptores o personal no docente. Tolera aproximados y el nombre dado vuelta'},
                'dia': {'type': 'string', 'description': 'Opcional: limitar a un día ("Martes"). Sin esto trae la semana entera'}
            },
            'required': []
        }
    },
    {
        'name': 'aulas_libres',
        'description': ('Aulas sin clase asignada AHORA MISMO, agrupadas por piso. No recibe parámetros: '
                        'usa siempre el día y la hora actuales del servidor, así que no sirve para '
                        'consultar otro momento. Si te preguntan por otro día u horario, usá '
                        'horario_aula sobre las aulas que interesen.'),
        'input_schema': {
            'type': 'object',
            'properties': {}
        }
    },
    {
        'name': 'buscar_entidad',
        'description': ('Busca en el inventario por nombre '
                        'aproximado y devuelve id + nombre + datos básicos. Es la forma correcta de '
                        'conseguir un id: NUNCA inventes uno ni lo recuerdes de otra conversación. '
                        'CADA RESULTADO TRAE UN CAMPO "match" QUE DICE CUÁNTO CONFIAR: '
                        '"exacto" = el nombre contiene lo que buscaste; "descripcion" = no está en el '
                        'nombre pero sí en la descripción (que viene incluida, leela para ver si sirve); '
                        '"aproximado" = NO coincide con nada, entró solo porque se escribe parecido '
                        '(mirá "similitud", 0–1) y lo más probable es que NO sea lo que se busca. '
                        'Nunca trates un "aproximado" como si fuera el recurso pedido. '
                        'Y si no hay ningún "exacto", NO concluyas todavía que no está: esta '
                        'búsqueda compara letras, no significados, así que no encuentra el '
                        'Multímetro si te pidieron un "tester". En ese caso llamá a '
                        'listar_todos con el mismo slug y decidí mirando la lista completa.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'slug': {'type': 'string', 'enum': SLUGS_ENTIDAD,
                         'description': 'Qué tipo de entidad buscar'},
                'query': {'type': 'string', 'description': 'Parte del nombre. Tolera errores de tipeo y falta de tildes'}
            },
            'required': ['slug', 'query']
        }
    },
    {
        'name': 'listar_todos',
        'description': ('Devuelve la lista COMPLETA de un tipo de entidad: nombre + id, y en '
                        'recursos también DÓNDE ESTÁ cada uno. Tiene dos usos. '
                        'UNO, el respaldo de buscar_entidad cuando no trajo ningún resultado con '
                        'match "exacto": la búsqueda compara letras, no significados, así que no '
                        'encuentra el "Multímetro" si el usuario pidió un "tester", ni la '
                        '"Agujereadora de banco" si pidió un "taladro". Vos sí sabés que son lo '
                        'mismo, pero necesitás ver los nombres para darte cuenta. Úsala también '
                        'antes de decirle a alguien que algo no está cargado: así esa afirmación '
                        'la hacés habiendo mirado todo, no porque una búsqueda falló. '
                        'DOS, y para esto es la ÚNICA tool que tenés: cualquier pregunta por '
                        'UBICACIÓN. No existe una búsqueda por lugar — "qué hay en el taller", '
                        '"todo lo que está en el armario 2", "qué quedó sin ubicar" se contestan '
                        'pidiendo esta lista y leyendo el campo `ubicacion`, que trae cada lugar '
                        'con cuántas unidades hay ahí ("Taller (4), Sin ubicar (1)"). Ese lugar y '
                        'ese número son el `origen` y la `cantidad` de mover_ubicacion, así que '
                        'con esta lista podés mover de una todo lo que está en un sitio, sin '
                        'pedirle a nadie que te dicte qué hay. '
                        'Si la lista es demasiado larga devuelve un error pidiendo que '
                        'busques con un término más específico.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'slug': {'type': 'string', 'enum': SLUGS_ENTIDAD,
                         'description': 'Qué tipo de entidad listar (el mismo que usaste en buscar_entidad)'},
                'con_descripcion': {'type': 'boolean',
                                    'description': 'Suma la descripción de cada fila. Por defecto '
                                                   'false, y así está bien casi siempre: pedila sólo '
                                                   'cuando los nombres solos no te alcanzan para '
                                                   'decidir cuál es (varios parecidos, o un pedido '
                                                   'por una característica técnica que el nombre no '
                                                   'dice). Encarece bastante la lista'}
            },
            'required': ['slug']
        }
    },
    {
        'name': 'listar_alias',
        'description': ('SOLO ADMIN. Lista todos los recursos con su alias oculto (los '
                        'términos alternativos de búsqueda que vos mismo completás con '
                        'editar_entidad) para auditarlos: detectá cuáles quedaron vacíos, '
                        'cuáles quedaron cortos o disparejos entre filas que son la misma '
                        'cosa o que se sustituyen entre sí, proponé términos mejores, sacá '
                        'redundancias. Es la única tool que '
                        'te devuelve el TEXTO del alias — nunca lo repitas ni lo menciones '
                        'frente al usuario, tratalo como un dato interno de mantenimiento '
                        'aunque quien te lo pida sea el propio administrador. Para saber '
                        'si UN resultado de búsqueda matcheó por alias sin pedir toda la '
                        'lista, mirá el campo "match" de buscar_entidad.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'slug': {'type': 'string', 'enum': SLUGS_CON_ALIAS,
                         'description': 'Qué entidad auditar (hoy sólo "recursos" tiene alias)'}
            },
            'required': ['slug']
        }
    },
    {
        'name': 'detalle_entidad',
        'description': ('Ficha completa de una entidad: todos sus campos más las relaciones '
                        '(si es un recurso, cómo está desglosado '
                        'por ubicación). Necesitás el id: sacalo de buscar_entidad. '
                        'Un campo vacío significa que nadie lo cargó — decilo así, no lo completes con '
                        'un valor plausible.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'slug': {'type': 'string', 'enum': SLUGS_ENTIDAD},
                'id': {'type': 'integer', 'description': 'ID exacto obtenido de buscar_entidad'}
            },
            'required': ['slug', 'id']
        }
    },
    {
        'name': 'leer_foto',
        'description': ('Mira las fotos que el usuario adjuntó EN ESTE TURNO y te las devuelve en '
                        'texto. Puede haber VARIAS: llamala UNA SOLA VEZ, sin el parámetro '
                        '`foto`, y te devuelve todas las lecturas juntas, cada una con el número '
                        'de su foto. NO la llames una vez por foto: el turno tiene un tope de '
                        'vueltas y te quedás sin ninguna para armar las fichas. '
                        'Tiene tres modos, elegí según qué necesitás saber: '
                        '"etiqueta" (el habitual) transcribe la chapa de UN producto —marca, '
                        'modelo, potencia, tensión, medidas— y es el que usás para cargar o '
                        'actualizar un recurso suelto; "listado" transcribe una PÁGINA O TABLA '
                        'con VARIOS ítems distintos (el contenido de un kit, un remito, una '
                        'lista de materiales) como un renglón por ítem con su cantidad, y es el '
                        'que usás para cargar un kit vía `sub_recursos` de crear_entidad — NO '
                        'uses "etiqueta" para esto, está pensado para un solo producto y con una '
                        'tabla de muchos ítems se queda corto; "analisis" describe QUÉ SE VE '
                        '—qué objeto es, en qué estado visible está, cuántos hay— y sirve cuando '
                        'la foto no tiene texto legible o el usuario pregunta qué es o cómo está '
                        'algo. '
                        'Llamala SOLO cuando necesites datos de la imagen. Si el usuario solo '
                        'quiere GUARDAR las fotos en una ficha, NO la llames: no hace falta '
                        'leerlas para adjuntarlas, usá adjuntar_foto. Tampoco la llames "por las '
                        'dudas" ni la llames varias veces con distintos modos a ver cuál sale '
                        'mejor: cada foto cuesta, en cualquier modo. '
                        'Si no tenés claro para qué te mandaron las fotos, preguntale al usuario '
                        'antes de leer nada.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'modo': {'type': 'string', 'enum': ['etiqueta', 'listado', 'analisis'],
                         'description': 'Default "etiqueta": chapa de UN producto, alimenta el '
                                        'alta simple. "listado": página o tabla con VARIOS '
                                        'ítems (contenido de un kit, remito), alimenta el alta '
                                        'de un kit vía `sub_recursos`. "analisis" solo si lo que '
                                        'hace falta es saber qué es o cómo está el objeto.'},
                'foto': {'type': 'integer',
                         'description': 'Número de UNA foto puntual. Casi nunca hace falta: sin '
                                        'esto se leen todas las del turno de una sola vez, que '
                                        'es lo que querés. Usalo solo para releer una que ya '
                                        'leíste en otro modo.'}
            }
        }
    },
    # ESCRITURA
    {
        'name': 'crear_entidad',
        'description': ('Da de alta una entidad nueva en el inventario. VA EN DOS PASOS y no se '
                        'puede saltear. (1) La PRIMERA vez que la llamás con un juego de campos '
                        'NO escribe nada: te devuelve la ficha tal cual va a quedar guardada y '
                        'qué campos quedaron vacíos. Mostrásela al usuario campo por campo, '
                        'hacele las preguntas que sugiere la respuesta y pedile el OK. (2) '
                        'Cuando el usuario dice que sí, llamala DE NUEVO con EXACTAMENTE los '
                        'mismos campos y ahí sí se guarda. Si pide cambios, llamala con los '
                        'campos corregidos: te devuelve la ficha nueva para que la apruebe. '
                        'Cualquier campo que agregues, saques o cambies al confirmar vuelve a '
                        'mostrar la ficha — no se puede guardar algo distinto de lo que el '
                        'usuario leyó. nombre, tipo y descripcion los redactás VOS a partir '
                        'de lo que contó el usuario, no se los pidas literalmente; el resto, si no '
                        'te lo dieron, va vacío — no inventes. Antes de dar de alta un recurso, '
                        'buscá con buscar_entidad para no duplicar uno que ya existe. Si te piden '
                        'dar de alta varias cosas de una, llamala una vez por cada una en el mismo '
                        'turno: cada ficha sale con sus propios botones y el usuario las revisa por '
                        'separado. RECURSOS: si el usuario dijo dónde se guarda, mandá `ubicacion` '
                        '— aparece en la ficha y se fija sola al confirmar. Para mover un recurso '
                        'que YA existe es otra cosa: mover_ubicacion.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'slug': {'type': 'string', 'enum': SLUGS_ENTIDAD},
                'foto': {'type': 'integer',
                         'description': 'Número de la foto de la que salió esta ficha, el mismo '
                                        'que te devolvió leer_foto. Mandalo SIEMPRE que el alta '
                                        'venga de una foto: es lo que hace que la imagen termine '
                                        'en la ficha correcta y no en otra. Si rearmás una ficha '
                                        'porque el usuario pidió un cambio, volvé a mandar el '
                                        'MISMO número — si no, la foto se pierde. Para un alta '
                                        'que no salió de ninguna foto, omitilo'},
                'nombre': {'type': 'string', 'description': 'Nombre, redactado por VOS con lo que dijo el usuario: corto y reconocible para quien lo busque en el pañol (ej: "Taladro percutor Bosch GSB 550"). OBLIGATORIO'},
                'tipo': {'type': 'string', 'description': 'Categoría que proponés VOS, texto libre, pero REUSÁ una de las que ya están en uso — la ficha del paso 1 te las devuelve en `tipos_en_uso` — antes de inventar una nueva; si no, el campo se llena de sinónimos y deja de servir para agrupar.'},
                'cantidad': {'type': 'integer', 'description': 'Stock disponible'},
                'descripcion': {'type': 'string', 'description': 'Descripción redactada por VOS con lo que contó el usuario: para qué sirve, medidas, marca y modelo, en qué estado está. Una o dos frases, sin inventar lo que no te dijeron'},
                'estado': {'type': 'string',
                           'enum': gestion.ESTADOS_RECURSO,
                           'description': 'Estado del recurso en el inventario'},
                'valor': {'type': 'string', 'enum': ['Básico', 'Secundario', 'Alto valor'],
                          'description': 'IMPORTANCIA del recurso dentro del inventario (qué tan crítico es), NO para qué sirve — eso va en descripcion'},
                'fecha_revision': {'type': 'string', 'description': 'Fecha del último control de inventario, en formato día/mes/año (ej: 08/08/2026). EN UN ALTA no la mandes ni la preguntes: se completa sola con la fecha de hoy y NO aparece en la ficha (dar de alta ya es el control). Sí se usa en editar_entidad cuando el usuario revisa un recurso viejo'},
                'ubicacion': {'type': 'string', 'description': 'Dónde se guarda el recurso (ej: "Taller Armario 3"). Sólo en el alta: aparece en la ficha como un campo más y al confirmar se fija sola (por dentro es lo mismo que mover_ubicacion). Si el usuario no dijo dónde va, dejala vacía y preguntale — es opcional, se guarda igual'},
                'sub_recursos': {
                    'type': 'array',
                    'description': ('Convierte este recurso en un KIT que agrupa sub-recursos '
                                    '(ej: "Kit Arduino" con la lista de sensores que trae). Cada '
                                    'item es SOLO título + cantidad, nada más: no tienen '
                                    'descripción, estado ni ubicación propios. Mandala COMPLETA '
                                    'en cada llamada, igual que el resto de la ficha: si '
                                    'rearmás la ficha por un cambio y omitís esta lista, se '
                                    'borra.'),
                    'items': {
                        'type': 'object',
                        'properties': {
                            'titulo': {'type': 'string', 'description': 'Nombre del sub-recurso, ej: "Sensor ultrasónico HC-SR04"'},
                            'cantidad': {'type': 'string', 'description': 'Cuántos trae, como texto (ej: "2")'}
                        },
                        'required': ['titulo']
                    }
                }
            },
            'required': ['slug']
        }
    },
    {
        'name': 'editar_entidad',
        'description': ('Modifica una entidad existente. Es una edición PARCIAL: mandá solo los campos '
                        'que cambian y el resto queda como está. El id sacalo de buscar_entidad, nunca '
                        'de tu memoria. Cada campo aplica a determinados slugs (ver parámetros); mandar '
                        'uno que no corresponde al slug no hace nada. RECURSOS no tiene `ubicacion` acá: '
                        'para mover un recurso de lugar usá mover_ubicacion.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'slug': {'type': 'string', 'enum': SLUGS_ENTIDAD},
                'id': {'type': 'integer', 'description': 'ID de la entidad a editar, obtenido de buscar_entidad'},
                'nombre': {'type': 'string', 'description': 'Nombre'},
                'tipo': {'type': 'string', 'description': 'Categoría, texto libre sin lista fija (ej: Instrumento, Equipo, Estructura, Material). OJO: hoy está vacío en casi todo el inventario, así que no lo uses para filtrar ni asumas que tiene valor.'},
                'cantidad': {'type': 'integer', 'description': 'Stock disponible'},
                'descripcion': {'type': 'string', 'description': 'Descripción libre'},
                'estado': {'type': 'string',
                           'enum': gestion.ESTADOS_RECURSO,
                           'description': 'Estado del recurso en el inventario'},
                'valor': {'type': 'string', 'enum': ['Básico', 'Secundario', 'Alto valor'],
                          'description': 'IMPORTANCIA del recurso dentro del inventario (qué tan crítico es), NO para qué sirve — eso va en descripcion'},
                'fecha_revision': {'type': 'string', 'description': 'Fecha del último control de inventario, en formato día/mes/año (ej: 08/08/2026). Actualizala cuando el usuario diga que revisó o controló el recurso. Ojo: el inventario viejo importado del sheet tiene fechas cortas sin año (24/4, 8/5) — no las reformatees por tu cuenta'},
                'alias': {'type': 'string',
                          'description': ('Términos alternativos de búsqueda, separados por coma, que NO '
                                          'aparecen en el nombre ni la descripción. Cada término entra por una '
                                          'de dos razones: (1) MISMA COSA, OTRO NOMBRE: cómo la llaman distintas '
                                          'personas — nombre técnico, jerga de taller, abreviatura, sigla, marca '
                                          'usada como genérico (ej: nombre="Multímetro" → "tester, multitester, '
                                          'voltimetro, amperimetro, medidor de tension"). Si el inventario tiene '
                                          'otras filas que son la misma cosa, todas llevan el MISMO conjunto de '
                                          'nombres. (2) SIRVE PARA LO MISMO: no es la misma cosa pero alguien '
                                          'que busca OTRO recurso se conformaría con este — poné el nombre de '
                                          'ese otro (ej: una zapatilla de 2-3 m tapa un alargue corto → la '
                                          'zapatilla lleva "alargue"). Es direccional: la inversa solo si '
                                          'también aplica. No repitas lo que ya está en el nombre/descripción ni '
                                          'metas typos (la búsqueda perdona errores de tipeo). Es un campo '
                                          'INTERNO: NUNCA se lo muestres al usuario, nunca se lo preguntes, no '
                                          'aparece en ninguna ficha ni en el form web. Solo recursos. '
                                          'Completalo SIEMPRE que des de alta un recurso: apenas crear_entidad '
                                          'te devuelva el id, llamá a editar_entidad con los términos que hagan '
                                          'falta para cubrir las dos razones, normalmente 3 a 8. Si en cualquier '
                                          'momento el usuario nombra un recurso ya cargado con un término '
                                          'distinto al que tiene guardado, sumalo acá también.')},
                'sub_recursos': {
                    'type': 'array',
                    'description': ('SUMA sub-recursos a un kit que YA EXISTE — a diferencia de todo lo demás '
                                    'en esta tool, esto NO reemplaza nada: se agregan a los que el kit ya '
                                    'tiene, nunca se borran ni se pisan. Es para cargar el contenido de un kit '
                                    'en varias tandas (ej: te mandaron la mitad de la lista, la cargaste, y '
                                    'después llega el resto — cada tanda es una llamada a editar_entidad con '
                                    'estos ítems nuevos, NO tenés que volver a mandar los que ya están). Cada '
                                    'item es SOLO título + cantidad. Para corregir o borrar un sub-recurso que '
                                    'ya está cargado no hay tool: decile al usuario que lo haga desde la ficha '
                                    'del recurso en /gestion. Solo recursos.'),
                    'items': {
                        'type': 'object',
                        'properties': {
                            'titulo': {'type': 'string', 'description': 'Nombre del sub-recurso, ej: "Sensor ultrasónico HC-SR04"'},
                            'cantidad': {'type': 'string', 'description': 'Cuántos trae, como texto (ej: "2")'}
                        },
                        'required': ['titulo']
                    }
                }
            },
            'required': ['slug', 'id']
        }
    },
    {
        'name': 'editar_sub_recurso',
        'description': ('Corrige título, cantidad y/o recurso asignado de UN sub-recurso puntual '
                        'de un kit que ya existe (ej: el usuario dice "el joystick en realidad son '
                        '2, no 1" o "ese ítem se llama distinto"). Edición PARCIAL: mandá solo lo '
                        'que cambia. El `item_id` es el id de ESE renglón dentro de `kit_items`, '
                        'NUNCA el id del recurso/kit — sacalo de detalle_entidad(slug="recursos", '
                        'id=<el kit>), sección "Sub-recursos (kit)" de `relaciones`, y nunca lo '
                        'inventes ni lo confundas con el id del kit. Si hay varios sub-recursos '
                        'parecidos, confirmá con el usuario cuál es antes de llamar. Escribe '
                        'directo, sin ficha de confirmación — avisale al usuario qué corregiste. '
                        'Para agregar un sub-recurso nuevo NO es esta tool: es editar_entidad con '
                        '`sub_recursos`. Solo recursos.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'id': {'type': 'integer', 'description': 'ID del recurso/kit dueño del sub-recurso, obtenido de buscar_entidad o detalle_entidad'},
                'item_id': {'type': 'integer', 'description': 'ID del RENGLÓN puntual dentro de ese kit (columna `id` de `kit_items`), obtenido de detalle_entidad. No es el id del recurso'},
                'titulo': {'type': 'string', 'description': 'Nuevo título del sub-recurso. Omitilo si no cambia'},
                'cantidad': {'type': 'string', 'description': 'Nueva cantidad, como texto. Omitilo si no cambia'},
                'recurso_asignado': {'type': 'string', 'description': 'Texto libre (no es un link a otro recurso). Omitilo si no cambia'}
            },
            'required': ['id', 'item_id']
        }
    },
    {
        'name': 'eliminar_sub_recurso',
        'description': ('Borra UN sub-recurso puntual de un kit que ya existe (ej: "sacá el '
                        'joystick del kit, no venía"). El `item_id` es el id de ESE renglón '
                        'dentro de `kit_items`, sacalo de detalle_entidad igual que en '
                        'editar_sub_recurso — nunca lo inventes. Esto NO borra el recurso/kit '
                        'entero (un recurso no se elimina nunca: sale del inventario dándolo de '
                        'baja desde la web), solo ese renglón. Si el usuario '
                        'no fue específico sobre cuál sub-recurso o hay varios parecidos, '
                        'preguntale cuál antes de llamar: no se puede deshacer desde el chat. '
                        'Escribe directo, sin ficha de confirmación. Solo recursos.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'id': {'type': 'integer', 'description': 'ID del recurso/kit dueño del sub-recurso'},
                'item_id': {'type': 'integer', 'description': 'ID del RENGLÓN puntual a borrar (columna `id` de `kit_items`), obtenido de detalle_entidad'}
            },
            'required': ['id', 'item_id']
        }
    },
    {
        'name': 'adjuntar_foto',
        'description': ('Guarda las fotos que el usuario adjuntó EN ESTE TURNO en la galería de un '
                        'registro que YA existe. Es lo que hay que usar cuando mandan una foto para '
                        'que quede en la ficha de algo ("guardá esta foto en el taladro"). '
                        'Sin el parámetro `foto` '
                        'van TODAS las del turno al '
                        'mismo registro, que es el caso normal cuando mandan varias de la misma '
                        'cosa; si cada foto va a un registro distinto, llamala una vez por cada una '
                        'con su número. '
                        'NO necesitás leer la foto para adjuntarla: no llames a leer_foto para esto. '
                        'El id sale de buscar_entidad, nunca de tu memoria. '
                        'IMPORTANTE: si no tenés claro a qué registro va, o la búsqueda devuelve '
                        'varios parecidos, PREGUNTALE al usuario cuál es. No elijas por tu cuenta: '
                        'una foto guardada en el recurso equivocado no se puede sacar desde la app. '
                        'Para un alta nueva no la uses: la foto de un alta se guarda sola cuando el '
                        'usuario confirma la ficha (para eso está el parámetro `foto` de '
                        'crear_entidad).'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'slug': {'type': 'string', 'enum': SLUGS_ENTIDAD,
                         'description': 'Tipo de registro al que va la foto'},
                'id': {'type': 'integer', 'description': 'ID exacto obtenido de buscar_entidad'},
                'foto': {'type': 'integer',
                         'description': 'Número de UNA foto puntual del turno. Omitilo para '
                                        'adjuntar todas las que mandó al mismo registro'}
            },
            'required': ['slug', 'id']
        }
    },
    {
        'name': 'mover_ubicacion',
        'description': ('Mueve unidades de un recurso de un lugar a otro dentro del pañol. Es la '
                        'ÚNICA forma de fijar dónde está un recurso: no hay un campo `ubicacion` '
                        'aparte en la ficha (ni en crear_entidad ni en editar_entidad) — un recurso '
                        'recién dado de alta queda "sin ubicar" hasta que llamás a esta tool, aunque '
                        'tenga una sola unidad. Cada unidad de un recurso tiene su propio número '
                        '(1, 2, 3...) — usá `numeros` cuando el pedido menciona unidades puntuales '
                        '("el destornillador 3 y el 5 están en el taller"), y `cantidad` cuando el '
                        'pedido es genérico y no dice cuáles ("moví 3 destornilladores de laboratorio '
                        'a taller", o simplemente "el multímetro está en el pañol" para un recurso de '
                        'una sola unidad): hace falta uno de los dos. '
                        'NO HACE FALTA que el desglose esté cargado de antes: números que no existan '
                        'en el recurso, o (con `cantidad`) un origen con menos unidades registradas '
                        'de las pedidas, IGUAL se mueve lo que se puede — nunca se bloquea por eso, '
                        'la respuesta trae `avisos` con la diferencia: contáselos al usuario. '
                        '`origen` sólo se usa junto con `cantidad` (no con `numeros`) y es opcional: '
                        'si no se sabía de dónde salían, omitilo. `destino` es obligatorio. Si el '
                        'nombre del recurso es ambiguo devuelve ok:false con `opciones`: mostráselas '
                        'al usuario y preguntá cuál es, no elijas vos. Después de mover, contale al '
                        'usuario cómo quedó el desglose ENTERO (`ubicaciones` en la respuesta, '
                        'agrupado por lugar con los números de cada uno), no sólo lo que acaba de '
                        'pedir.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'recurso': {'type': 'string', 'description': 'Nombre del recurso (tolera aproximados y tildes) o su ID como string'},
                'numeros': {'type': 'array', 'items': {'type': 'integer'},
                            'description': 'Números puntuales de las unidades a mover, ej: [3, 5]. Usalo cuando el '
                                           'usuario menciona unidades concretas. No lo combines con `cantidad`.'},
                'cantidad': {'type': 'integer', 'description': 'Cantidad de unidades a mover, sin importar cuáles '
                             '(el sistema elige). Usalo cuando el pedido es genérico, sin números puntuales.'},
                'origen': {'type': 'string', 'description': 'Lugar de donde salen (sólo tiene efecto junto con '
                           '`cantidad`, no con `numeros`). Opcional: si no se sabía dónde estaban, se omite. '
                           f'Lugares habituales (usalos tal cual si el pedido no da un detalle distinto): {", ".join(gestion.LUGARES_RECURSO)}'},
                'destino': {'type': 'string', 'description': 'Lugar al que llegan. Obligatorio. '
                            f'Lugares habituales (usalos tal cual si el pedido no da un detalle distinto): {", ".join(gestion.LUGARES_RECURSO)}. '
                            'Si el usuario menciona algo que no es uno de estos lugares (una excepción real, ej: '
                            '"el techo", "panel solar instalado afuera"), escribilo tal cual lo dijo: no está limitado a esta lista.'}
            },
            'required': ['recurso', 'destino']
        }
    },
    # --- NOTAS: el archivo `agente.md`, ni lectura ni dominio ---
    {
        'name': 'escribir_notas',
        'description': ('Reescribe `agente.md`, la libreta de quien está chateando: lo que te '
                        'pidan que tengas presente estos días. Es la tool de '
                        '"anotá que...", "acordate de que...", "de ahora en más...", "ojo '
                        'que...", y también la de "eso ya no corre, borralo". Ejemplos de nota: '
                        '"el pañol está en el aula 12 hasta que arreglen el techo", "las salidas '
                        'de este año las coordina Vanesa", "no cargues la máquina de café como '
                        'recurso", "los que pasaron al provincial son Fulano y Mengana". '
                        'ESCRIBÍS EL ARCHIVO ENTERO, NO UN RENGLÓN: tenés el contenido actual a '
                        'la vista en tus instrucciones, así que `contenido` es ESE TEXTO COMPLETO '
                        'con tu cambio aplicado — una línea más, una menos, una corregida. Todo '
                        'lo que no copies SE PIERDE, así que copiá tal cual lo que no te '
                        'pidieron tocar: no lo resumas, no lo reordenes, no lo "mejores". Si '
                        'estás agregando algo, el archivo tiene que quedar con todas las notas '
                        'viejas MÁS la nueva. '
                        'QUÉ VA: lo que te pidan que vaya, y eso lo decide el usuario, no vos. '
                        'Si te dicen "anotá esto", se anota — sea una consigna, un aviso, una '
                        'lista de nombres o algo que se quieren acordar la semana que viene. NO '
                        'discutas si "va acá o va en una ficha", no lo mandes a otro lado y no '
                        'pidas permiso: anotalo y decí que quedó anotado. Si además ese dato '
                        'tendría lugar en el inventario, ofrecé cargarlo DESPUÉS, en una línea. '
                        'Por tu cuenta no anotes nada: ni lo que sirve sólo para este chat, ni '
                        'lo que dedujiste vos, ni un horario o un stock que ya se consultan con '
                        'su tool. Redactalo para que se entienda dentro de un mes sin esta '
                        'conversación a la vista. '
                        'La tool te devuelve cuántos renglones había antes y cuántos quedaron: '
                        'si bajó y vos estabas agregando algo, te comiste una nota — avisale al '
                        'usuario y arreglalo.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'contenido': {'type': 'string',
                              'description': 'El archivo COMPLETO como tiene que quedar: lo '
                                             'que ya estaba, tal cual, más tu cambio'}
            },
            'required': ['contenido']
        }
    }
]

# ============================================================================
# Qué permiso pide cada tool — la fuente de verdad
# ============================================================================

# Antes esta clasificación estaba en TRES lugares que había que mantener a mano: los
# comentarios `# LECTURA` / `# ESCRITURA` de arriba, una lista `lectura` en
# `tools/__init__.py` y un `TOOLS_ESCRITURA` en `filtros.py`. Ahora los otros dos se
# derivan de acá.
#
# Va como dict aparte y no como una clave dentro de cada esquema a propósito: así
# TOOLS_SCHEMA sigue siendo exactamente lo que las APIs esperan y no hay que acordarse de
# limpiarlo antes de mandarlo (Anthropic rechaza con 400 cualquier clave de más, y el
# proveedor por defecto es DeepSeek, así que ese bug sería invisible en desarrollo).
# De paso, se leen todas juntas de un vistazo.
PERMISO_POR_TOOL = {
    # --- LECTURA: no tocan ninguna base ---
    'buscar_profesor': 'agente.leer',
    'buscar_por_rol': 'agente.leer',
    'preceptores': 'agente.leer',
    'horario_profesor': 'agente.leer',
    'horario_curso': 'agente.leer',
    'horario_aula': 'agente.leer',
    'aulas_libres': 'agente.leer',
    'coincidencias': 'agente.leer',
    'buscar_entidad': 'agente.leer',
    'listar_todos': 'agente.leer',
    'detalle_entidad': 'agente.leer',
    # Admin puro y no 'agente.leer': es la única tool que expone el TEXTO del alias, mismo
    # gate que la web (/gestion/alias, permiso gestion.alias) — ver entidades._listar_alias_fmt.
    'listar_alias': gestion.PERMISO_ALIAS,
    # No toca la base: lo que gasta es la API de visión, no el inventario.
    'leer_foto': 'agente.leer',

    # --- ESCRITURA: modifican gestion.db ---
    'crear_entidad': 'agente.escribir',
    'editar_entidad': 'agente.escribir',
    'editar_sub_recurso': 'agente.escribir',
    'eliminar_sub_recurso': 'agente.escribir',
    'adjuntar_foto': 'agente.escribir',
    'mover_ubicacion': 'agente.escribir',

    # --- NOTAS: permiso propio, verbo 'admin' (ver agente/__init__.py) ---
    # No es 'agente.escribir': no toca ningún dato de la escuela, y al revés, un acceso que
    # carga inventario no tiene por qué reescribir el archivo de notas del administrador.
    'escribir_notas': PERMISO_NOTAS,
}

# Una tool sin permiso declarado sería una tool que nadie puede ejecutar (fail-closed) y
# que encima desaparecería del listado sin avisar. Que reviente al importar, no en
# producción a mitad de una conversación.
_sin_permiso = {t['name'] for t in TOOLS_SCHEMA} - set(PERMISO_POR_TOOL)
if _sin_permiso:
    raise RuntimeError(
        f"Estas tools no declaran permiso en PERMISO_POR_TOOL: {sorted(_sin_permiso)}. "
        f"Agregalas en agente/tools/esquemas.py.")

TOOLS_ESCRITURA = frozenset(n for n, p in PERMISO_POR_TOOL.items() if p == 'agente.escribir')
TOOLS_LECTURA = frozenset(PERMISO_POR_TOOL) - TOOLS_ESCRITURA

# Las dos que sólo tienen sentido si en el turno hay una foto. Piden `agente.vision`
# ADEMÁS del permiso que declaran arriba, no en su lugar: si `adjuntar_foto` cambiara su
# permiso por `agente.vision` a secas, un dispositivo al que le tildaran visión a mano
# podría escribir en la galería sin tener `agente.escribir`. Las dos condiciones se piden
# juntas en `tools_permitidas`.
TOOLS_FOTO = frozenset(['leer_foto', 'adjuntar_foto'])

# Las que dejan rastro en `agente_log`. NO es lo mismo que TOOLS_ESCRITURA: `escribir_notas`
# escribe —y pisa el archivo ENTERO, que es lo que puede salir mal— pero no toca el dominio.
# Meterla en TOOLS_ESCRITURA le encendería a un acceso de sólo notas todo el circuito de alta
# en el system prompt, que es lo que `escribe` decide en llm.py. El `antes` que audita es el
# contenido completo previo: el segundo camino de vuelta, además de `agente.md.bak`.
TOOLS_AUDITADAS = TOOLS_ESCRITURA | frozenset(['escribir_notas'])

# La que sólo tiene sentido con el archivo a la vista: viaja con `agente.notas` por
# PERMISO_POR_TOOL, y su presencia es lo que le dice al prompt que hay notas que mostrar.
TOOLS_NOTAS = frozenset(['escribir_notas'])


# Qué permisos pide cada slug: el de lectura de su área más el propio de la entidad, si
# declaró uno. Sale de las `ENTIDADES` de cada área y no de una lista a mano,
# igual que SLUGS_ENTIDAD.
#
# Que el permiso del ÁREA entre acá es lo que ata el asistente al inventario abierto: desde
# que gestión son varios, `gestion.leer` sólo vale adentro de uno (ver PERMISOS_AMBITO), y
# `agente.leer` por sí solo ya no alcanza para pedirle recursos a nadie. Sin inventario
# abierto, `recursos` se cae de todos los enum y las tools que se quedan sin ningún slug
# directamente no viajan.
PERMISO_POR_SLUG = {s: permisos_entidad(s) for s in SLUGS_ENTIDAD}

# Tools que tocan una entidad SIN recibir el slug (los sub-recursos de un kit y las
# unidades son siempre de `recursos`). No pueden pasar por PERMISO_POR_SLUG, así que
# declaran a mano qué ámbito necesitan. Se pide ADEMÁS del permiso de PERMISO_POR_TOOL, no
# en su lugar: el asistente sigue teniendo permisos propios para escribir (ver
# agente/__init__.py), lo que esto agrega es "y adentro de un inventario que puedas ver".
PERMISO_EXTRA_POR_TOOL = {
    'editar_sub_recurso': gestion.PERMISO_LECTURA,
    'eliminar_sub_recurso': gestion.PERMISO_LECTURA,
    'mover_ubicacion': gestion.PERMISO_LECTURA,
}


def _sin_slugs(esquema, prohibidos):
    """Copia del esquema con `prohibidos` afuera de los enum de slug.

    Copia y no muta: TOOLS_SCHEMA es global y lo comparten todos los turnos de todos los
    accesos. Un slug que no está en el enum no se le ofrece al modelo, que es la misma
    idea que `tools_permitidas` una escala más abajo — el ejecutor rechaza igual, pero acá
    el modelo directamente no se entera de que la entidad existe.
    """
    props = esquema['input_schema'].get('properties', {})
    a_recortar = [nombre for nombre, prop in props.items()
                  if prohibidos & set(prop.get('enum') or ())]
    if not a_recortar:
        return esquema
    copia = dict(esquema)
    copia['input_schema'] = dict(esquema['input_schema'])
    copia['input_schema']['properties'] = dict(props)
    for nombre in a_recortar:
        prop = dict(props[nombre])
        prop['enum'] = [v for v in prop['enum'] if v not in prohibidos]
        copia['input_schema']['properties'][nombre] = prop
    return copia


def tools_permitidas(permisos):
    """Los esquemas que este acceso puede ver.

    Es la única puerta por la que los esquemas salen hacia el modelo. Filtrar acá y no
    rechazar en el ejecutor es la diferencia entre "no tenés esa herramienta" y "tenés esa
    herramienta pero no te dejo": en el primer caso el modelo ni sabe que existe, no la
    anuncia y no inventa que la usó.

    Lo mismo vale para las ENTIDADES: si una entidad pidiera un permiso propio (hoy
    ninguna lo hace), las tools que toman un slug viajarían sin ese valor en su enum.

    Y lo mismo con las FOTOS: sin `agente.vision` el acceso no puede ni mandar una imagen
    (el front no le ofrece el botón y `chat()` la rechaza), así que `leer_foto` y
    `adjuntar_foto` no viajan. Si viajaran, el modelo ofrecería leer una foto que el
    usuario no tiene forma de mandarle.
    """
    prohibidos = {s for s, ps in PERMISO_POR_SLUG.items()
                  if not all(accesos.tiene(permisos, p) for p in ps)}
    ve_fotos = accesos.tiene(permisos, PERMISO_VISION)

    def pasa(t):
        extra = PERMISO_EXTRA_POR_TOOL.get(t['name'])
        return (accesos.tiene(permisos, PERMISO_POR_TOOL[t['name']])
                and (extra is None or accesos.tiene(permisos, extra))
                and (ve_fotos or t['name'] not in TOOLS_FOTO))

    salida = []
    for t in TOOLS_SCHEMA:
        if not pasa(t):
            continue
        recortada = _sin_slugs(t, prohibidos) if prohibidos else t
        # Una tool que se quedó sin ningún slug no se manda: un enum vacío no es una
        # herramienta más chica, es una que el modelo no puede llamar de ninguna forma
        # válida. Sin inventario abierto es lo que hace desaparecer las siete tools de
        # entidades en vez de ofrecerlas rotas.
        if _sin_opciones(recortada):
            continue
        salida.append(recortada)
    return salida


def _sin_opciones(esquema):
    """True si alguna propiedad del esquema quedó con el enum vacío."""
    return any(prop.get('enum') == []
               for prop in esquema['input_schema'].get('properties', {}).values())


def slug_visible(tools, slug):
    """¿`slug` sobrevivió en los esquemas que EFECTIVAMENTE se le mandan al modelo?

    Lo usa `llm.chat_with_tools_stream` para armar el system prompt con la misma fuente que las
    tools, igual que hace con `escribe`: así las dos mitades del mensaje no se pueden
    contradecir.
    """
    return any(slug in (prop.get('enum') or ())
               for t in tools
               for prop in t['input_schema'].get('properties', {}).values())
