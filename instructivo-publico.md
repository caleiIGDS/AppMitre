# AppMitre: consultar horarios

Leé esta guía cuando el usuario pida horarios de la E.E.S.T. N.º 4 Emilio Mitre. Si tenés MCP conectado, usalo según la sección siguiente, sin pedir la contraseña en el chat. **Solo para consultas por enlaces HTTP:** pedile al usuario la misma contraseña que usa para entrar a la aplicación de Horarios si aún no te la dio. Esa contraseña es el valor de `token`: no hay otra clave que generar y no está en este documento público. Con ella podés abrir enlaces HTTPS y leer JSON sin cabeceras ni cuerpos POST. Necesitás que tu herramienta permita abrir estas URL: si lo impide, explicá esa limitación sin afirmar que el servidor está caído.

## Si el agente tiene conexión MCP

El servidor MCP está en `https://calei.pythonanywhere.com/mcp` (Streamable HTTP), con **OAuth**. Al conectar, se abre la pantalla de AppMitre: allí se escribe la misma contraseña de Horarios y se autoriza consultar horarios y PDF. El cliente guarda y renueva el acceso, sin repetir la contraseña en cada chat. Cada herramienta recibe solo los filtros en `consulta`: `{"consulta":{"tipo":"curso","valores":["3 K"]}}` para `consultar_horarios`. Si necesita autorización, indicá conectar/reconectar AppMitre; no pidas la contraseña en el chat para MCP.

Usá las herramientas MCP ya conectadas en vez del lector web. Se anuncian las consultas del registro de la API y `obtener_pdf`; sus resultados escolares son los mismos JSON. `obtener_pdf` devuelve una referencia de archivo y un enlace descargable válido por una hora, sin la contraseña en la URL: mostrale al usuario `[Descargar PDF](url)` con la URL exacta recibida. `resources/read` con esa URL permite leer el PDF en base64 desde el MCP si el cliente no puede descargarlo por HTTP. No afirmes que se adjuntó al chat salvo que el cliente lo haya adjuntado. Para conectarlo en ChatGPT: Plugins → + → Add custom MCP server, indicar esa dirección y elegir OAuth con registro dinámico (DCR). También puede configurarse en otros clientes MCP compatibles; cada servicio guarda su propia autorización. Agregar la dirección al texto de un chat no instala la conexión.

## Enlaces de consulta

Base: `https://calei.pythonanywhere.com/app-horarios/api/v1/consultas`.
En los ejemplos, reemplazá `TU_CLAVE` por la contraseña **codificada como componente de URL** (también espacios, &, +, #, ?, etc.). Codificá los valores de los filtros igual; `%20` representa un espacio. No publiques ni repitas el token en tu respuesta.

Ejemplo completo para la semana de 3.º K:

`https://calei.pythonanywhere.com/app-horarios/api/v1/consultas/horarios?token=TU_CLAVE&tipo=curso&valor=3%20K`

Agregá a la base uno de estos caminos:

| Pregunta | Camino y parámetros |
| --- | --- |
| Semana de un curso | `/horarios?token=TU_CLAVE&tipo=curso&valor=3%20K` |
| Varios cursos | `/horarios?token=TU_CLAVE&tipo=curso&valores=3%20K&valores=3%20B` |
| Todas las divisiones de un año | `/horarios?token=TU_CLAVE&tipo=curso&anio=3` |
| Solo martes de un curso | `/horarios?token=TU_CLAVE&tipo=curso&valor=3%20K&dias=martes` |
| Buscar persona y sus cargos | `/personas?token=TU_CLAVE&nombre=calei` |
| Personas con un cargo | `/personas?token=TU_CLAVE&rol=preceptor` |
| Todos los cargos, como respaldo de un rol que no coincide | `/catalogos?token=TU_CLAVE&incluir=roles` |
| Personas con más de un cargo | `/personas?token=TU_CLAVE&multiples_roles=true` |
| Semana de una persona, todos sus cargos | `/horarios?token=TU_CLAVE&tipo=persona&valor=CALEI` |
| Semana de un aula | `/horarios?token=TU_CLAVE&tipo=aula&valor=33` |
| Actividades en aulas el lunes de 08 a 10 | `/horarios?token=TU_CLAVE&tipo=aula&dias=lunes&desde=08:00&hasta=10:00` |
| Curso ahora | `/horarios?token=TU_CLAVE&tipo=curso&valor=3%20K&ahora=true` |
| Preceptores de un curso, todos los turnos y días | `/preceptores?token=TU_CLAVE&cursos=3%20B` |
| Todos los preceptores con sus asignaciones | `/preceptores?token=TU_CLAVE` |
| Preceptores del turno mañana | `/preceptores?token=TU_CLAVE&turno=ma%C3%B1ana` |
| Cursos disponibles | `/catalogos?token=TU_CLAVE&incluir=cursos` |
| Todos los nombres, como respaldo de una búsqueda fallida | `/catalogos?token=TU_CLAVE&incluir=nombres` |
| Aulas por piso y cargos | `/catalogos?token=TU_CLAVE&incluir=aulas&incluir=roles` |
| Materias técnico-específicas de tercero | `/materias?token=TU_CLAVE&tipos=te&anios=3` |
| Buscar una materia o docente en la tabla de materias | `/materias?token=TU_CLAVE&texto=matematica` |
| Especialidades de los cursos y tipos de materia | `/catalogos?token=TU_CLAVE&incluir=especialidades&incluir=tipos_materia` |

Las divisiones, nombres y aulas deben corresponder a los datos reales. Consultá directamente una entidad conocida; buscá por nombre si necesitás resolver una persona, sin descargar todos los catálogos antes de cada pregunta. Para encontrar cargos múltiples usá `multiples_roles=true`, solo o junto con `nombre`/`rol`; no recorras todo el padrón para filtrarlo localmente. Para varias personas o aulas repetí `valores`, hasta 20 entidades por consulta. `valor` es alias de `valores`; no combines ambos. Para varios días repetí `dias`. No separes nombres por comas. Usá un solo selector: `valor`/`valores`, `anio` (cursos) o `piso` (aulas). `desde` y `hasta` van juntos; `ahora=true` no se combina con días/rango. Los filtros se intersectan.

## Respuestas JSON

- Horarios: `horarios` contiene entidades con `curso`, `persona` o `aula`, y `dias` con listas de actividades. La semana por defecto es lunes a viernes. Las actividades incluyen horas y los campos pertinentes (materia, profesor, curso, aula, grupo); en personas cada actividad indica su `rol`. Una persona puede tener varios cargos.
- Personas: `personas` contiene `nombre` y `roles` (lista completa de cargos).
- Preceptores: `preceptores` contiene `nombre` y `asignaciones` por curso, turno, función principal/contraturno y días. Se pueden pedir todos juntos. `vacantes`, `sin_registro` y `avisos` son cosas distintas.
- Catálogos: cursos, aulas agrupadas por piso, roles, `nombres`, `especialidades` y/o `tipos_materia`, según lo solicitado. `nombres` es una lista compacta de nombres completos, sin horarios ni fichas.
- Materias: `materias` contiene los cupos y `resumen` los totales de toda la selección, repetidos en cada página; no sumes los resúmenes entre páginas. Cada cupo incluye curso, grupo, materia, tipo, especialidad, docente efectivo y minutos semanales; con suplencia activa agrega `titular_en_licencia`.
- Si aparece `siguiente`, repetí exactamente la consulta agregando `&cursor=VALOR_CODIFICADO`. Continuá hasta que no aparezca antes de afirmar que un listado está completo. Si solo se piden algunos ejemplos y ya los encontraste, detenete y no presentes esa selección como listado completo. Con `consulta_vencida`, reiniciá; no mezcles páginas de copias distintas.
- Error: `{"error":{"codigo":"...","mensaje":"..."}}`. Con `persona_ambigua`, revisá los candidatos, sin fusionarlos ni elegir arbitrariamente. Con `consulta_demasiado_amplia`, dividí por entidades/días. Con 401 revisá la clave; con 429 detené los reintentos. No inventes un horario si una consulta falla.

Los esquemas completos están en `/contratos?token=TU_CLAVE` y `/openapi.json?token=TU_CLAVE`, bajo la misma base; son referencias técnicas opcionales, no un paso obligatorio.

## Explorar materias y especialidades

`/materias` es la tabla de la pestaña MATERIAS, con todas sus combinaciones de filtros. Lista lo que figura en los horarios cargados, no todas las materias previstas en los planes de estudio. Sin filtros devuelve todos los cupos, con paginación.

Un curso combina **año y división** (por ejemplo, `3° K`); cada curso tiene una **especialidad** configurada. Primero a tercero pertenecen al **CICLO BÁSICO**; después están las especialidades **ELECTROMECÁNICA**, **MAESTRO MAYOR DE OBRA** y **ENERGÍAS RENOVABLES**. No deduzcas la especialidad por una letra o número de división: `/catalogos?token=TU_CLAVE&incluir=especialidades` devuelve un mapa de curso a especialidad para los cursos cargados. `null` significa sin especialidad configurada.

El **tipo de materia** es otra clasificación, independiente de la especialidad: una carrera tiene materias de varios tipos y una misma materia puede aparecer en distintos cursos. Se obtiene del plan correspondiente al año y especialidad, igual que en la app; no lo deduzcas del nombre ni de quién la dicta.

| Parámetro de `/materias` | Qué selecciona | Ejemplo |
| --- | --- | --- |
| `tipos` | `te`: TÉCNICO-ESPECÍFICA; `ct`: CIENTÍFICO-TECNOLÓGICA; `fg`: TEÓRICA | `tipos=te` |
| `anios` | Años del 1 al 7 | `anios=3` |
| `divisiones` | División, sin el año | `divisiones=K` |
| `especialidades` | Nombre completo, sin distinguir tildes, espacios o mayúsculas | `especialidades=energias%20renovables` |
| `texto` | Parte del nombre de la materia, del titular o del suplente; ignora tildes, espacios y mayúsculas | `texto=matematica` |

Para varias opciones repetí el parámetro: `anios=4&anios=5&divisiones=2&divisiones=3` selecciona 4° 2, 4° 3, 5° 2 y 5° 3, si existen. **Dentro de un filtro las opciones se suman; entre filtros se cruzan.** Un filtro omitido admite todas las opciones; no envíes listas vacías. Para un curso exacto combiná su año y división. `anios` es plural en `/materias`; `anio` sigue siendo singular en `/horarios`, `/preceptores` y `/catalogos`. En POST, `anios` es una lista de cadenas, por ejemplo `["3", "4"]`.

Ejemplos (agregar a la misma base de consultas):

- Técnico-específicas de tercero: `/materias?token=TU_CLAVE&tipos=te&anios=3`.
- Teóricas y científico-tecnológicas de 4° y 5° de Energías Renovables: `/materias?token=TU_CLAVE&tipos=fg&tipos=ct&anios=4&anios=5&especialidades=energias%20renovables`.
- Matemática de 3° K: `/materias?token=TU_CLAVE&anios=3&divisiones=K&texto=matematica`.

Cada fila es un **cupo**: materia de un curso y grupo, con su docente y eventual suplencia. No confundas cupos con materias distintas: la misma materia en dos cursos produce dos cupos; los grupos A/B también pueden producir filas distintas. `tipo_materia` devuelve `te`, `ct`, `fg` o `null` si no está clasificada; `profesor` es quien la dicta según la suplencia activa, o `null` si no está informado. `minutos_semanales` suma la duración de sus bloques: dividí por 60 para expresar horas reloj, no horas cátedra. Los bloques sin un intervalo válido no se suman y aparecen contados en `bloques_sin_duracion`; si es mayor que cero, la carga calculada está incompleta. Sumar cupos de grupos paralelos no equivale a la duración del calendario de todo el curso.

`resumen` contiene `materias_distintas` (por nombre), `cupos`, `divisiones`, `minutos_semanales` y `bloques_sin_duracion` de toda la selección. Para revisar o enumerar todas las filas consumí `siguiente`. Un resultado vacío significa que no hay cupos con esa combinación en la copia cargada; no prueba que una materia no exista en el plan. Si la especialidad es desconocida, revisá su nombre en el catálogo.

## Cómo encadenar las consultas

- **Qué materias y quiénes las dictan:** consultá `/materias` con los filtros pedidos. Si también preguntan cuándo o dónde, tomá el `curso` o el `profesor` devuelto y consultá `/horarios`; seleccioná allí los bloques de esa materia y grupo. Si hay varias filas del mismo curso, reutilizá su horario.
- **Horario de alguien:** usá `/personas` para resolver el nombre cuando haga falta y luego `/horarios?tipo=persona&valor=...`. Para encontrar docentes de un tipo de materia o especialidad, empezá por `/materias`, reuní sus nombres sin duplicarlos y después pedí sus horarios. El horario personal puede incluir otras materias y cargos: conservá el alcance del pedido.
- **Cruzar docente, curso y lugar:** pedí los horarios de cada entidad y compará los bloques por día. Para una planilla de piso, usá `/horarios?tipo=aula&piso=...&dias=...`. Para saber los preceptores del curso, usá `/preceptores?cursos=...`; sus asignaciones por turno no son horas exactas de presencia.
- **Descubrir opciones:** usá `/catalogos` para las opciones que desconozcas, por ejemplo `incluir=especialidades&incluir=tipos_materia`. No hace falta pedir catálogos antes de cada consulta ni descargar todos los horarios para buscar una materia.

Si un cargo no coincide, la búsqueda queda vacía o el usuario usa un sinónimo/abreviatura que no reconocés, pedí una vez `/catalogos?token=TU_CLAVE&incluir=roles`. Revisá los cargos reales y repetí la consulta con el rol correspondiente, conservando los demás filtros. `rol=?` busca literalmente ese texto; no lista cargos ni funciona como comodín. Una equivalencia clara permite continuar e indicar cómo interpretaste el pedido; si el término es ambiguo, preguntá. Si el pedido engloba varios cargos, consultá los pertinentes y reuní las personas sin duplicarlas. Una persona puede tener varios roles: no los equipares ni descartes los otros. Si se enviaron nombre y rol juntos, un resultado vacío también puede deberse al cargo; revisá primero este catálogo pequeño antes de descargar todos los nombres. Reutilizá el catálogo en la conversación y no lo pidas antes de cada consulta.

Si no encontrás una persona o los candidatos no son convincentes, pedí una vez `/catalogos?token=TU_CLAVE&incluir=nombres` y revisá los nombres completos buscando errores de escritura, abreviaturas u orden de nombre/apellido. Este respaldo incluye docentes, preceptores y otros cargos, sin descargar sus horarios. Con una coincidencia clara, consultá el nombre exacto e indicá a quién interpretaste; si hay varias posibilidades razonables, pedí al usuario que precise. Si ninguna encaja, informá que no pudiste identificarla. Conservá los filtros de cargo que haya pedido el usuario. No listes todos los nombres en la respuesta ni los descargues antes de cada consulta; reutilizá la lista en esa conversación. Este respaldo sirve para identificar personas, no para resolver errores de autenticación o de conexión.

## Si una herramienta no puede abrir la URL

Un error del lector web o de DNS de su entorno no prueba que el servidor esté caído. Si disponés de un cliente HTTP con acceso a Internet (por ejemplo, Python o una terminal), usalo directamente; seguí los permisos de ese entorno. No repitas el mismo intento fallido sin que cambien las condiciones. Si solo disponés del lector web y no permite estas URL, explicá que no pudiste consultar y pedí que el usuario te acerque el JSON o PDF; no inventes datos. Este instructivo no le agrega herramientas ni acceso de red a un chat.

## Descargar un PDF

Para obtener un archivo PDF en lugar de JSON, abrí estos enlaces GET con la misma clave codificada en `token`. No hace falta iniciar sesión:

| PDF | URL |
| --- | --- |
| Curso | `https://calei.pythonanywhere.com/horarios/export/pdf/curso/3%20K?token=TU_CLAVE` |
| Persona (clases docentes) | `https://calei.pythonanywhere.com/horarios/export/pdf/profesor/CALEI?token=TU_CLAVE` |
| Aula | `https://calei.pythonanywhere.com/horarios/export/pdf/aula/33?token=TU_CLAVE` |
| Varios cursos (una página por curso) | `https://calei.pythonanywhere.com/horarios/export/pdf/cursos/3%20K,3%20B?token=TU_CLAVE` |
| Todos los cursos | `https://calei.pythonanywhere.com/horarios/export/pdf/cursos/todos?token=TU_CLAVE` |
| Planilla de preceptores | `https://calei.pythonanywhere.com/horarios/export/pdf/planilla_preceptores?token=TU_CLAVE` |

El resultado es `application/pdf`, no JSON; necesitás una herramienta que permita descargar archivos si querés adjuntarlo. El PDF de profesor muestra sus clases, no todos sus cargos: para el horario completo de una persona usá la consulta JSON. Los nombres de ejemplo deben existir en los datos reales. La app sigue imprimiendo localmente con sus datos descargados.

## Contexto y reglas para interpretar

- Es una secundaria técnica. El usuario trabaja como EMATP de Energías Renovables y coordina olimpíadas de matemática. Los turnos son mañana, tarde y vespertino (noche).
- Grupos A/B son partes de una división, no otras divisiones. Conservá esa distinción.
- **PROGRESO es una cancha a dos cuadras de la escuela, fuera del edificio.** Coincidir allí en horario no significa coincidir en la escuela. No inventes tiempos de traslado.
- La información es la semana de la última copia cargada desde la planilla, no una confirmación de asistencia, feriados, suspensiones o excepciones por fecha. Describí «empieza/termina su actividad registrada», no «entra/sale del edificio»: la hora de una clase no informa cuándo llega o se va una persona.
- Preceptores: asignaciones por turno/día, sin horas exactas de presencia. Puede haber distintos principales según el día y varios contraturnos. Una asignación sin división no corresponde automáticamente a todas las divisiones del año.
- Respetá las suplencias: `titular_en_licencia`, `en_licencia` y `suplente`. No cuentes al titular en licencia como quien da esa clase ni deduzcas vigencia por fechas.
- Un recreo o hueco no demuestra disponibilidad ni presencia. Para comparar curso, persona y aula, consultá cada tipo y cruzá los bloques: `max(inicios) < min(finales)`. Terminar justo cuando otro empieza no es solaparse.
- Conservá los horarios recibidos. Si fin es anterior o igual al inicio, señalá la anomalía de la fuente y no afirmes una coincidencia calculada con ese bloque. Null significa dato no informado.
- Respondé solo lo pedido, con días, horas y lugares relevantes. No descargues toda la escuela si alcanza con consultas puntuales. No uses `/actualizar` para responder.

El token es la contraseña actual de Horarios y habilita únicamente estas consultas de lectura por URL. Puede quedar en el historial y los registros de acceso; cualquiera con ese enlace puede consultar. Este documento público no contiene la contraseña ni horarios.
