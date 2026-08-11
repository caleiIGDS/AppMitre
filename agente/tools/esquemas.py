"""Los esquemas de las tools: lo único que el modelo ve de cada herramienta.

Data pura, sin lógica. Está escrito en el formato de Anthropic ({name, description,
input_schema}); `llm._tools_openai` lo traduce al vuelo para los proveedores compatibles
con OpenAI, donde el JSON Schema es idéntico y sólo cambia el envoltorio.

Las descripciones son largas a propósito: no describen qué hace la función, le dicen al
modelo cómo comportarse ("nunca respondas un horario de memoria", "que devuelva una sola
clase es un resultado válido, no lo rellenes"). Acortarlas degrada al agente.
"""
import historia

from ..dominio import SLUGS_ENTIDAD

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
                        'horario_profesor también busca difuso. OJO: es el padrón de los HORARIOS, '
                        'no el de las personas con ficha (alumnos, ex docentes, gente de la memoria '
                        'institucional). Si el tema es un hito o la semblanza de '
                        "alguien, la persona se busca con buscar_entidad('personas', ...). Cuando el "
                        'nombre coincide con las dos cosas, esta tool te devuelve además '
                        '`personas_con_ficha` y un `aviso`: hacele caso. Los que tienen cargo no '
                        'docente vienen con su `rol` al lado del nombre. Los PRECEPTORES no están '
                        'en este padrón: si el nombre coincide con alguno, te lo devuelve aparte '
                        'en `preceptores` y ahí seguís con la tool `preceptores`. '
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
                        'cubiertos. Los cursos van como "3° B": el año y la división por separado.'),
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
                        'es en vez de elegir; (c) `nota` diciendo que no encontró a nadie. Que devuelva '
                        'una sola clase, o ninguna, es un resultado válido y frecuente: informalo tal '
                        'cual, no lo rellenes.'),
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
                        'Es la única fuente del horario de un curso, no lo deduzcas.'),
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
                        'traé la semana y filtrá vos el día y la hora. Única fuente, no la deduzcas.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'aula': {'type': 'string', 'description': 'Código tal como está en la base: "21", "T3", "PATIO", "GYM". Los talleres van sin espacio ("T2", no "Taller 2")'}
            },
            'required': ['aula']
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
        'description': ('Busca en el inventario o en la línea del tiempo institucional por nombre '
                        'aproximado y devuelve id + nombre + datos básicos. Es la forma correcta de '
                        'conseguir un id: NUNCA inventes uno ni lo recuerdes de otra conversación. Los '
                        'tipos son distintos: "recursos" son cosas físicas sueltas (una herramienta, un '
                        'instrumento, un material); "conjuntos" son kits de recursos que se usan '
                        'juntos; "actividades" son prácticas de taller que consumen esos recursos; '
                        '"hitos" son eventos de la línea del tiempo institucional (incluye lo que antes '
                        'se llamaba "proyecto": hoy es un hito con "Proyecto" en sus etiquetas); '
                        '"personas" son fichas de quién hizo la escuela. Un mismo nombre puede existir '
                        'como hito Y como conjunto, así que elegí el slug según lo que pregunten. '
                        'CADA RESULTADO TRAE UN CAMPO "match" QUE DICE CUÁNTO CONFIAR: '
                        '"exacto" = el nombre contiene lo que buscaste; "descripcion" = no está en el '
                        'nombre pero sí en la descripción (que viene incluida, leela para ver si sirve); '
                        '"aproximado" = NO coincide con nada, entró solo porque se escribe parecido '
                        '(mirá "similitud", 0–1) y lo más probable es que NO sea lo que se busca. '
                        'Nunca trates un "aproximado" como si fuera el recurso pedido. '
                        'Y si no hay ningún "exacto", NO concluyas todavía que no está: esta '
                        'búsqueda compara letras, no significados, así que no encuentra el '
                        'Multímetro si te pidieron un "tester". En ese caso llamá a '
                        'listar_todos con el mismo slug y decidí mirando la lista completa. '
                        'CON slug="personas" mira TAMBIÉN el padrón de los horarios: si hay '
                        'gente que coincide te la devuelve en `en_horarios` (con su `rol` si es '
                        'personal no docente) y un `aviso_horarios`. Que no haya ficha NO '
                        'significa que la persona no exista en la escuela — puede estar dando '
                        'clases o tener un cargo y no tener ficha todavía.'),
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
        'description': ('Devuelve la lista COMPLETA de nombres + id de un tipo de entidad. Es el '
                        'respaldo de buscar_entidad, no un reemplazo: usala SOLO cuando '
                        'buscar_entidad no trajo ningún resultado con match "exacto". '
                        'Para qué sirve: la búsqueda compara letras, no significados, así que no '
                        'encuentra el "Multímetro" si el usuario pidió un "tester", ni la '
                        '"Agujereadora de banco" si pidió un "taladro". Vos sí sabés que son lo '
                        'mismo, pero necesitás ver los nombres para darte cuenta. '
                        'Úsala también antes de decirle a alguien que algo no está cargado: así '
                        'esa afirmación la hacés habiendo mirado todo, no porque una búsqueda '
                        'falló. Si la lista es demasiado larga devuelve un error pidiendo que '
                        'busques con un término más específico.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'slug': {'type': 'string', 'enum': SLUGS_ENTIDAD,
                         'description': 'Qué tipo de entidad listar (el mismo que usaste en buscar_entidad)'}
            },
            'required': ['slug']
        }
    },
    {
        'name': 'detalle_entidad',
        'description': ('Ficha completa de una entidad: todos sus campos más las relaciones (qué '
                        'conjuntos/actividades la usan si es un recurso, qué personas aparecen si es '
                        'un hito, y si es un recurso, quién lo tiene prestado ahora). Necesitás el id: '
                        'sacalo de buscar_entidad. '
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
        'description': ('Lee la foto que el usuario adjuntó EN ESTE TURNO y te devuelve, en texto, '
                        'lo que dice: marca, modelo, potencia, tensión, medidas. Para etiquetas, '
                        'chapas de características y datasheets. '
                        'Llamala SOLO cuando necesites datos de la imagen para cargar o actualizar '
                        'algo. Si el usuario solo quiere GUARDAR la foto en una ficha, NO la '
                        'llames: no hace falta leerla para adjuntarla, usá adjuntar_foto. '
                        'Tampoco la llames "por las dudas": cada lectura cuesta. '
                        'Si no tenés claro para qué te mandaron la foto, preguntale al usuario '
                        'antes de leer nada.'),
        'input_schema': {'type': 'object', 'properties': {}}
    },
    {
        'name': 'listar_prestamos',
        'description': ('Lista los préstamos EN CURSO (con algo todavía sin devolver), con su id, la '
                        'persona y lo que queda pendiente. Solo devuelve activos: los ya cerrados no '
                        'aparecen. Es de donde sacás el prestamo_id para devolver o consultar.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'persona': {'type': 'string', 'description': 'Opcional: filtra por nombre de quien retiró. Sin esto lista todos los activos'}
            }
        }
    },
    {
        'name': 'detalle_prestamo',
        'description': ('Detalle de UN préstamo: cada ítem con su recurso_id, cuánto se llevó y cuánto '
                        'devolvió hasta ahora. Llamala SIEMPRE antes de finalizar_prestamo o '
                        'reabrir_prestamo con ítems puntuales, porque los recurso_id que necesitan esas '
                        'tools son los de ESTE préstamo y no los de una búsqueda general. También es la '
                        'forma correcta de responder "¿quedó registrado?" o "¿cuánto le falta?" en vez '
                        'de volver a crear el préstamo.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'prestamo_id': {'type': 'integer', 'description': 'ID del préstamo, obtenido de listar_prestamos o del alta'}
            },
            'required': ['prestamo_id']
        }
    },
    {
        'name': 'consultar_historia',
        'description': ('Lore de la escuela: historia institucional, tradiciones y anécdotas internas '
                        'sobre gente de la casa. Usala cuando la pregunta NO es operativa — "¿qué sabés de X?", '
                        '"contame algo de...", "¿por qué se llama así?", "historias excitantes", "algo misterioso". '
                        'Sin tema: lista todas las historias disponibles. Con tema: busca (tolera typos, busca en '
                        'claves, tono, estilo). Si devuelve modo:directo, ella ya eligió → cuéntala con el tono/estilo '
                        'indicado, PRIMERA PERSONA. Si devuelve modo:listar, ofrécele esas opciones al usuario. '
                        'Si modo:no_encontrado, decíselo tal cual (NO improvises). Es la ÚNICA fuente de historia.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'tema': {'type': 'string', 'description': 'Qué buscar: nombre, "fundación", "edificio", "misterioso", "excitante". Vacío = listar todas'},
                'id': {'type': 'string', 'description': 'ID de una historia para obtenerla directamente (ej: "guino_canamas"). Opcional; si se pasa, ignora tema'}
            },
            'required': []
        }
    },
    {
        'name': 'buscar_hitos',
        'description': ('Línea del tiempo institucional: logros, eventos, construcciones, participaciones y cambios de la escuela. '
                        'Devuelve hitos ordenados por relevancia (Crítico > Importante > Básico) y fecha (reciente primero). '
                        'El agente SELECCIONA según el contexto: pregunta casual → 3-5 hitos Críticos/Importantes recientes; '
                        'búsqueda específica sobre logros → todos los Críticos; pregunta por año → todo lo de ese año ordenado por nivel. '
                        'Úsala para enriquecer respuestas con contexto institucional: "¿qué pasó en Renovables?" → busca_hitos(etiqueta="Renovables") '
                        'y luego selecciona los más relevantes para la pregunta.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'etiqueta': {'type': 'string', 'description': 'Filtra por etiqueta: "Renovables", "Olimpiada", "Electromecánica", "Matemática", etc. Tolera typos'},
                'desde_fecha': {'type': 'string', 'description': 'Rango desde (YYYY-MM-DD). Ej: "2024-01-01"'},
                'hasta_fecha': {'type': 'string', 'description': 'Rango hasta (YYYY-MM-DD). Ej: "2024-12-31"'},
                'limite': {'type': 'integer', 'description': 'Cuántos hitos traer máximo (default 50). Acá vienen muchos; el agente elige cuántos mostrar'}
            },
            'required': []
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
                        'usuario leyó. nombre/titulo, tipo y descripcion los redactás VOS a partir '
                        'de lo que contó el usuario, no se los pidas literalmente; el resto, si no '
                        'te lo dieron, va vacío — no inventes. Antes de dar de alta un recurso, '
                        'buscá con buscar_entidad para no duplicar uno que ya existe. Si te piden '
                        'dar de alta varias cosas de una, llamala una vez por cada una en el mismo '
                        'turno: cada ficha sale con su propio botón y el usuario las confirma por '
                        'separado.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'slug': {'type': 'string', 'enum': SLUGS_ENTIDAD},
                'nombre': {'type': 'string', 'description': 'Nombre, redactado por VOS con lo que dijo el usuario: corto y reconocible para quien lo busque en el pañol (ej: "Taladro percutor Bosch GSB 550"). OBLIGATORIO en todos los slugs MENOS hitos, que usa `titulo` en su lugar'},
                'titulo': {'type': 'string', 'description': 'Título del hito, redactado por VOS: qué pasó, corto y reconocible en una línea de tiempo (ej: "Olimpiada Matemática Argentina — Certamen Nacional"). OBLIGATORIO en hitos, y solo aplica a hitos: es el campo que en el resto de los slugs se llama `nombre`'},
                'tipo': {'type': 'string', 'description': ('RECURSOS: categoría que proponés VOS, texto libre, pero REUSÁ una de las que ya están en uso — la ficha del paso 1 te las devuelve en `tipos_en_uso` — antes de inventar una nueva; si no, el campo se llena de sinónimos y deja de servir para agrupar. HITOS: elegí uno de estos valores cerrados (si lo que estás cargando es lo que antes se llamaba "proyecto", va como hito con "Proyecto" en `etiquetas`, no acá): '
                                                          + ', '.join(historia.TIPOS_HITO))},
                'cantidad': {'type': 'integer', 'description': 'Stock disponible. Solo recursos'},
                'descripcion': {'type': 'string', 'description': 'Descripción redactada por VOS con lo que contó el usuario: para qué sirve, medidas, marca y modelo, en qué estado está. Una o dos frases, sin inventar lo que no te dijeron. Aplica a todos los slugs'},
                'ubicacion': {'type': 'string', 'description': 'Dónde se guarda (ej: A2, Taller de Electricidad). Solo recursos'},
                'estado': {'type': 'string',
                           'enum': ['Disponible', 'Retirado', 'En uso', 'En reparación', 'De baja', 'Sin revisar'],
                           'description': 'Estado del recurso en el inventario. Solo recursos'},
                'valor': {'type': 'string', 'enum': ['Básico', 'Secundario', 'Alto valor'],
                          'description': 'IMPORTANCIA del recurso dentro del inventario (qué tan crítico es), NO para qué sirve — eso va en descripcion. Solo recursos'},
                'fecha_revision': {'type': 'string', 'description': 'Fecha del último control de inventario, en formato día/mes/año (ej: 08/08/2026). Solo recursos. NO hace falta que la mandes en un alta: si la omitís se completa sola con la de hoy y aparece en la ficha; mandala solo si el usuario dice otra fecha'},
                'uso_tipico': {'type': 'string', 'description': 'En qué se suele usar el kit. Solo conjuntos'},
                'objetivo': {'type': 'string', 'description': 'Objetivo pedagógico. Solo actividades'},
                'duracion': {'type': 'string', 'description': 'Duración estimada, texto libre (ej: 2 módulos, 80 minutos). Solo actividades'},
                'curso': {'type': 'string', 'description': 'Año al que apunta, texto libre (ej: 6° año). Solo actividades'},
                'fecha': {'type': 'string', 'description': 'Fecha del hito en formato ISO AAAA-MM-DD (ej: 2025-11-20), que es como la guarda la base. Solo hitos, y ahí es OBLIGATORIA: si el usuario no la dijo, preguntásela — un hito sin fecha no entra en la línea del tiempo'},
                'nivel': {'type': 'string', 'enum': historia.NIVELES_HITO,
                          'description': 'Importancia del hito en la línea del tiempo. Básico: evento o actividad común. Importante: logro, programa nuevo. Crítico: olimpiada, construcción significativa. Solo hitos'},
                'etiquetas': {'type': 'string', 'description': 'Temas del hito separados por coma, para agrupar la línea del tiempo (ej: "Olimpiada, Matemática, Nacional"; para lo que antes era un "proyecto", agregá "Proyecto"). REUSÁ las que ya existen — mirá las de otros hitos con buscar_hitos antes de inventar una nueva. Solo hitos'},
                'protagonistas': {'type': 'string', 'description': 'Personas o cursos involucrados, en texto (ej: "Pablo Errio, Ezequiel Toñanes"). Es un campo de texto suelto: para dejar el vínculo navegable entre una persona ya cargada y el hito, además usá vincular_entidad. Solo hitos'}
            },
            # `nombre` no puede ir acá: hitos usa `titulo`. Cuál de los dos hace falta lo
            # valida _crear_entidad contra crud.campo_nombre() de la entidad.
            'required': ['slug']
        }
    },
    {
        'name': 'editar_entidad',
        'description': ('Modifica una entidad existente. Es una edición PARCIAL: mandá solo los campos '
                        'que cambian y el resto queda como está. El id sacalo de buscar_entidad, nunca '
                        'de tu memoria. Cada campo aplica a determinados slugs (ver parámetros); mandar '
                        'uno que no corresponde al slug no hace nada.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'slug': {'type': 'string', 'enum': SLUGS_ENTIDAD},
                'id': {'type': 'integer', 'description': 'ID de la entidad a editar, obtenido de buscar_entidad'},
                'nombre': {'type': 'string', 'description': 'Nombre. Todos los slugs MENOS hitos, que usa `titulo`: mandar `nombre` en un hito no cambia nada'},
                'titulo': {'type': 'string', 'description': 'Título del hito. Es el campo que en el resto de los slugs se llama `nombre`. Solo hitos'},
                'tipo': {'type': 'string', 'description': ('RECURSOS: categoría, texto libre sin lista fija (ej: Instrumento, Equipo, Estructura, Material). OJO: hoy está vacío en casi todo el inventario, así que no lo uses para filtrar ni asumas que tiene valor. HITOS: valores cerrados: '
                                                          + ', '.join(historia.TIPOS_HITO))},
                'cantidad': {'type': 'integer', 'description': 'Stock disponible. Solo recursos'},
                'descripcion': {'type': 'string', 'description': 'Descripción libre. Aplica a todos los slugs'},
                'ubicacion': {'type': 'string', 'description': 'Dónde está guardado (ej: A2, Taller de Electricidad). Solo recursos'},
                'estado': {'type': 'string',
                           'enum': ['Disponible', 'Retirado', 'En uso', 'En reparación', 'De baja', 'Sin revisar'],
                           'description': 'Estado del recurso en el inventario. Solo recursos'},
                'valor': {'type': 'string', 'enum': ['Básico', 'Secundario', 'Alto valor'],
                          'description': 'IMPORTANCIA del recurso dentro del inventario (qué tan crítico es), NO para qué sirve — eso va en descripcion. Solo recursos'},
                'fecha_revision': {'type': 'string', 'description': 'Fecha del último control de inventario, en formato día/mes/año (ej: 08/08/2026). Solo recursos. Actualizala cuando el usuario diga que revisó o controló el recurso. Ojo: el inventario viejo importado del sheet tiene fechas cortas sin año (24/4, 8/5) — no las reformatees por tu cuenta'},
                'uso_tipico': {'type': 'string', 'description': 'En qué se suele usar el kit. Solo conjuntos'},
                'objetivo': {'type': 'string', 'description': 'Objetivo pedagógico. Solo actividades'},
                'duracion': {'type': 'string', 'description': 'Duración estimada, texto libre (ej: 2 módulos, 80 minutos). Solo actividades'},
                'curso': {'type': 'string', 'description': 'Año al que apunta, texto libre (ej: 6° año). Solo actividades'},
                'fecha': {'type': 'string', 'description': 'Fecha del hito en formato ISO AAAA-MM-DD (ej: 2025-11-20), que es como la guarda la base. Solo hitos'},
                'nivel': {'type': 'string', 'enum': historia.NIVELES_HITO,
                          'description': 'Importancia del hito en la línea del tiempo. Básico: evento o actividad común. Importante: logro, programa nuevo. Crítico: olimpiada, construcción significativa. Solo hitos'},
                'etiquetas': {'type': 'string', 'description': 'Temas del hito separados por coma (ej: "Olimpiada, Matemática, Nacional"). Solo hitos'},
                'protagonistas': {'type': 'string', 'description': 'Personas o cursos involucrados, en texto. Solo hitos'}
            },
            'required': ['slug', 'id']
        }
    },
    {
        'name': 'adjuntar_foto',
        'description': ('Guarda la foto que el usuario adjuntó EN ESTE TURNO en la galería de un '
                        'registro que YA existe. Es lo que hay que usar cuando mandan una foto para '
                        'que quede en la ficha de algo ("guardá esta foto en el taladro", "esta es '
                        'la foto del hito"). '
                        'NO necesitás leer la foto para adjuntarla: no llames a leer_foto para esto. '
                        'El id sale de buscar_entidad, nunca de tu memoria. '
                        'IMPORTANTE: si no tenés claro a qué registro va, o la búsqueda devuelve '
                        'varios parecidos, PREGUNTALE al usuario cuál es. No elijas por tu cuenta: '
                        'una foto guardada en el recurso equivocado no se puede sacar desde la app. '
                        'Para un alta nueva no la uses: la foto de un alta se guarda sola cuando el '
                        'usuario confirma la ficha.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'slug': {'type': 'string', 'enum': SLUGS_ENTIDAD,
                         'description': 'Tipo de registro al que va la foto'},
                'id': {'type': 'integer', 'description': 'ID exacto obtenido de buscar_entidad'}
            },
            'required': ['slug', 'id']
        }
    },
    {
        'name': 'vincular_entidad',
        'description': ('Asocia dos entidades, por ejemplo agregar un recurso a un conjunto o a una '
                        'actividad, o una persona a un hito. La DIRECCIÓN importa: el origen es el que '
                        'contiene y el destino el contenido. Para "agregar el panel solar al conjunto '
                        'Banco de ensayo" el origen es el conjunto y el destino el recurso. Si entre '
                        'esos dos tipos no existe relación, devuelve error: no reintentes dándolos '
                        'vuelta sin pensarlo. Los dos ids salen de buscar_entidad. EXCEPCIÓN: '
                        'personas ↔ hitos anda en las dos direcciones, dan lo mismo. Ojo: vincular '
                        'a alguien a un hito NO le escribe el nombre en `protagonistas` — si el '
                        'usuario quiere que figure en la ficha, editá también ese campo.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'slug_origen': {'type': 'string', 'enum': SLUGS_ENTIDAD,
                                'description': 'Tipo de la entidad que CONTIENE (el conjunto, la actividad, el hito)'},
                'id_origen': {'type': 'integer', 'description': 'ID de la entidad que contiene'},
                'slug_destino': {'type': 'string', 'enum': SLUGS_ENTIDAD,
                                 'description': 'Tipo de la entidad CONTENIDA (normalmente "recursos")'},
                'id_destino': {'type': 'integer', 'description': 'ID de la entidad contenida'}
            },
            'required': ['slug_origen', 'id_origen', 'slug_destino', 'id_destino']
        }
    },
    {
        'name': 'desvincular_entidad',
        'description': ('Quita una asociación entre dos entidades. No borra ninguna de las dos, solo '
                        'la relación. Misma dirección que vincular_entidad: origen = el que contiene. '
                        'Deshacer un vínculo NO es automático: aunque lo hayas creado hace un momento, '
                        'tenés que llamar esta tool para revertirlo, y hasta que devuelva ok:true no '
                        'está desvinculado.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'slug_origen': {'type': 'string', 'enum': SLUGS_ENTIDAD,
                                'description': 'Tipo de la entidad que CONTIENE'},
                'id_origen': {'type': 'integer', 'description': 'ID de la entidad que contiene'},
                'slug_destino': {'type': 'string', 'enum': SLUGS_ENTIDAD,
                                 'description': 'Tipo de la entidad CONTENIDA'},
                'id_destino': {'type': 'integer', 'description': 'ID de la entidad contenida'}
            },
            'required': ['slug_origen', 'id_origen', 'slug_destino', 'id_destino']
        }
    },
    {
        'name': 'crear_prestamo',
        'description': ('Registra que alguien se llevó uno o más recursos. Un solo préstamo puede tener '
                        'varios ítems: cargalos todos juntos en `items`, no hagas una llamada por cosa. '
                        'ATENCIÓN: no deduplica — llamarla dos veces con los mismos datos crea DOS '
                        'préstamos. Para verificar uno que ya cargaste usá detalle_prestamo, nunca '
                        'vuelvas a llamar acá. Si un nombre de recurso es ambiguo devuelve ok:false con '
                        'una lista `opciones`: en ese caso mostrale las opciones al usuario y preguntá '
                        'cuál es, no elijas vos ni reintentes adivinando. La cantidad se topea al stock '
                        'del inventario. Si lo que se guardó salió distinto de lo pedido (se topeó al '
                        'stock, se sumaron repetidos, o ya había unidades afuera en otros préstamos), '
                        'la respuesta trae `ajustes`: decíselos al usuario, no des por hecho lo pedido.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'persona': {'type': 'string', 'description': 'Quién retira. Si es del personal de la escuela, el nombre tal cual figura en la lista de personas conocidas; si es alguien externo, como te lo dieron'},
                'destino': {'type': 'string', 'description': 'Opcional: a dónde se lo lleva (aula, taller, domicilio)'},
                'notas': {'type': 'string', 'description': 'Opcional: aclaraciones (estado en que salió, fecha estimada de devolución)'},
                'items': {
                    'type': 'array',
                    'description': 'Todos los recursos de este préstamo, en una sola llamada',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'recurso': {'type': 'string', 'description': 'Nombre del recurso (tolera aproximados y tildes) o su ID como string. El ID es preferible cuando el usuario ya eligió entre varias opciones'},
                            'cantidad': {'type': 'integer', 'description': 'Unidades que se lleva. Default 1'}
                        },
                        'required': ['recurso']
                    }
                }
            },
            'required': ['persona', 'items']
        }
    },
    {
        'name': 'finalizar_prestamo',
        'description': ('Registra una devolución. SIN `items` da por devuelto TODO el préstamo y lo '
                        'cierra — usalo solo si el usuario dijo que devolvió todo. CON `items` registra '
                        'una devolución parcial y el préstamo sigue abierto con lo que falta. Los '
                        '`recurso_id` tienen que ser los de ESTE préstamo: llamá detalle_prestamo antes '
                        'para conocerlos, no uses ids de buscar_entidad. Si alguno no pertenece al '
                        'préstamo devuelve ok:false y no aplica NADA: en ese caso avisá del error, no '
                        'lo des por devuelto. La respuesta trae `estado` y `pendiente_total` de cómo '
                        'quedó el préstamo DESPUÉS de la devolución: contale eso al usuario, no lo que '
                        'pediste. Nunca mandes `items` vacío: si devolvieron todo, omitilo.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'prestamo_id': {'type': 'integer', 'description': 'ID del préstamo, de listar_prestamos o detalle_prestamo'},
                'items': {
                    'type': 'array',
                    'description': 'Omitir para devolver todo y cerrar. Incluir solo para devoluciones parciales',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'recurso_id': {'type': 'integer', 'description': 'ID del recurso TAL COMO figura en detalle_prestamo de este préstamo'},
                            'cantidad': {'type': 'integer', 'description': 'Unidades que devuelve ahora, no el total prestado'}
                        },
                        'required': ['recurso_id', 'cantidad']
                    }
                }
            },
            'required': ['prestamo_id']
        }
    },
    {
        'name': 'reabrir_prestamo',
        'description': ('Deshace una devolución que se cargó por error: vuelve a marcar los ítems como '
                        'pendientes y reabre el préstamo. Es lo contrario de finalizar_prestamo, no un '
                        'borrado — el préstamo sigue existiendo. Sin `items` deshace la devolución '
                        'completa. Deshacer NO es automático: aunque hayas registrado la devolución '
                        'recién, hay que llamar esta tool y esperar ok:true antes de decir que se '
                        'revirtió. Los recurso_id salen de detalle_prestamo.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'prestamo_id': {'type': 'integer', 'description': 'ID del préstamo a reabrir'},
                'items': {
                    'type': 'array',
                    'description': 'Omitir para deshacer toda la devolución. Incluir para deshacer solo algunos ítems',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'recurso_id': {'type': 'integer', 'description': 'ID del recurso tal como figura en detalle_prestamo de este préstamo'}
                        },
                        'required': ['recurso_id']
                    }
                }
            },
            'required': ['prestamo_id']
        }
    },
    {
        'name': 'eliminar_entidad',
        'description': ('Elimina un recurso, conjunto, actividad, hito o persona. Requiere confirmación del '
                        'usuario en un turno previo Y el nombre exacto en nombre_confirmacion: el servidor '
                        'verifica que ese nombre coincida con el id, y rechaza el borrado si no coincide. '
                        'Nunca inventes un id: obtenelo con buscar_entidad.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'slug': {'type': 'string', 'enum': SLUGS_ENTIDAD},
                'id': {'type': 'integer', 'description': 'ID de la entidad a borrar, obtenido de buscar_entidad en ESTA conversación'},
                'nombre_confirmacion': {
                    'type': 'string',
                    'description': 'Nombre exacto de la entidad a borrar, tal como figura en la base. '
                                   'Debe coincidir con el id o el borrado se rechaza.'
                }
            },
            'required': ['slug', 'id', 'nombre_confirmacion']
        }
    },
    {
        'name': 'eliminar_prestamo',
        'description': ('Elimina un préstamo (solo para registros mal cargados). Requiere confirmación del '
                        'usuario en un turno previo Y persona_confirmacion: el servidor verifica que coincida '
                        'con la persona del préstamo y rechaza el borrado si no.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'prestamo_id': {'type': 'integer', 'description': 'ID del préstamo a borrar, obtenido de listar_prestamos en ESTA conversación'},
                'persona_confirmacion': {
                    'type': 'string',
                    'description': 'Nombre de la persona del préstamo, tal como figura en la base.'
                }
            },
            'required': ['prestamo_id', 'persona_confirmacion']
        }
    }
]
