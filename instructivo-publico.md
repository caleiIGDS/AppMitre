# AppMitre: consultar horarios

Leé esta guía cuando el usuario pida horarios de la E.E.S.T. N.º 4 Emilio Mitre. **Pedile al usuario la misma contraseña que usa para entrar a la aplicación de Horarios**, si aún no te la dio en esta conversación. Esa contraseña es el valor de `token`: no hay una clave diferente ni tenés que generar un token. La contraseña no está en este documento público. Con ella podés abrir enlaces HTTPS y leer las respuestas JSON; no necesitás instalar un MCP ni enviar cabeceras o cuerpos POST. Necesitás que tu herramienta permita abrir estas URL: si lo impide, explicá esa limitación sin afirmar que el servidor está caído.

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
| Semana de una persona, todos sus cargos | `/horarios?token=TU_CLAVE&tipo=persona&valor=CALEI` |
| Semana de un aula | `/horarios?token=TU_CLAVE&tipo=aula&valor=33` |
| Actividades en aulas el lunes de 08 a 10 | `/horarios?token=TU_CLAVE&tipo=aula&dias=lunes&desde=08:00&hasta=10:00` |
| Curso ahora | `/horarios?token=TU_CLAVE&tipo=curso&valor=3%20K&ahora=true` |
| Preceptores de un curso, todos los turnos y días | `/preceptores?token=TU_CLAVE&cursos=3%20B` |
| Todos los preceptores con sus asignaciones | `/preceptores?token=TU_CLAVE` |
| Preceptores del turno mañana | `/preceptores?token=TU_CLAVE&turno=ma%C3%B1ana` |
| Cursos disponibles | `/catalogos?token=TU_CLAVE&incluir=cursos` |
| Aulas por piso y cargos | `/catalogos?token=TU_CLAVE&incluir=aulas&incluir=roles` |

Las divisiones, nombres y aulas deben corresponder a los datos reales. Consultá directamente una entidad conocida; buscá por nombre si necesitás resolver una persona, sin descargar todos los catálogos antes de cada pregunta. Para varias personas o aulas repetí `valores`, hasta 20 entidades por consulta. `valor` es alias de `valores`; no combines ambos. Para varios días repetí `dias`. No separes nombres por comas. Usá un solo selector: `valor`/`valores`, `anio` (cursos) o `piso` (aulas). `desde` y `hasta` van juntos; `ahora=true` no se combina con días/rango. Los filtros se intersectan.

## Respuestas JSON

- Horarios: `horarios` contiene entidades con `curso`, `persona` o `aula`, y `dias` con listas de actividades. La semana por defecto es lunes a viernes. Las actividades incluyen horas y los campos pertinentes (materia, profesor, curso, aula, grupo); en personas cada actividad indica su `rol`. Una persona puede tener varios cargos.
- Personas: `personas` contiene `nombre` y `roles` (lista completa de cargos).
- Preceptores: `preceptores` contiene `nombre` y `asignaciones` por curso, turno, función principal/contraturno y días. Se pueden pedir todos juntos. `vacantes`, `sin_registro` y `avisos` son cosas distintas.
- Catálogos: cursos, aulas agrupadas por piso y/o roles, según lo solicitado.
- Si aparece `siguiente`, repetí exactamente la consulta agregando `&cursor=VALOR_CODIFICADO`. Continuá hasta que no aparezca antes de afirmar que un listado está completo. Con `consulta_vencida`, reiniciá; no mezcles páginas de copias distintas.
- Error: `{"error":{"codigo":"...","mensaje":"..."}}`. Con `persona_ambigua`, revisá los candidatos, sin fusionarlos ni elegir arbitrariamente. Con `consulta_demasiado_amplia`, dividí por entidades/días. Con 401 revisá la clave; con 429 detené los reintentos. No inventes un horario si una consulta falla.

Los esquemas completos están en `/contratos?token=TU_CLAVE` y `/openapi.json?token=TU_CLAVE`, bajo la misma base; son referencias técnicas opcionales, no un paso obligatorio.

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
- La información es la semana de la última copia cargada desde la planilla, no una confirmación de asistencia, feriados, suspensiones o excepciones por fecha.
- Preceptores: asignaciones por turno/día, sin horas exactas de presencia. Puede haber distintos principales según el día y varios contraturnos. Una asignación sin división no corresponde automáticamente a todas las divisiones del año.
- Respetá las suplencias: `titular_en_licencia`, `en_licencia` y `suplente`. No cuentes al titular en licencia como quien da esa clase ni deduzcas vigencia por fechas.
- Un recreo o hueco no demuestra disponibilidad ni presencia. Para comparar curso, persona y aula, consultá cada tipo y cruzá los bloques: `max(inicios) < min(finales)`. Terminar justo cuando otro empieza no es solaparse.
- Conservá los horarios recibidos. Si fin es anterior o igual al inicio, señalá la anomalía de la fuente y no afirmes una coincidencia calculada con ese bloque. Null significa dato no informado.
- Respondé solo lo pedido, con días, horas y lugares relevantes. No descargues toda la escuela si alcanza con consultas puntuales. No uses `/actualizar` para responder.

El token es la contraseña actual de Horarios y habilita únicamente estas consultas de lectura por URL. Puede quedar en el historial y los registros de acceso; cualquiera con ese enlace puede consultar. Este documento público no contiene la contraseña ni horarios.
