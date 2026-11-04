---
name: appmitre-horarios
description: Consulta horarios, cursos, aulas, docentes, otros cargos y preceptores de la EEST N.º 4 Emilio Mitre y obtiene sus calendarios PDF.
---

Usá las herramientas MCP de AppMitre para las preguntas de horarios de esta escuela. Consultá directamente la entidad conocida. El usuario trabaja allí como EMATP de Energías Renovables y coordina olimpíadas de matemática.

Cada herramienta recibe `clave` (la contraseña de Horarios) y `consulta` (los filtros; `{}` cuando no hagan falta). Pedí la contraseña al usuario si no la tenés. No la repitas ni la publiques. La conexión MCP no exige un login, pero ninguna herramienta entrega datos sin comprobar esa clave.

`listar_catalogos`, `buscar_personas`, `consultar_horarios` y `consultar_preceptores` describen sus filtros en el esquema. Usá las otras consultas que anuncie el servidor cuando correspondan. No necesitás buscar en la web ni abrir el instructivo para usar estas herramientas. Si no encontrás un cargo o persona, revisá una vez el catálogo de `roles` o `nombres`; preguntá si la identidad sigue siendo ambigua. `multiples_roles=true` evita recorrer todo el padrón para encontrar personas con varios cargos.

Conservá días, bloques originales, grupos A/B, suplencias, cargos múltiples y datos desconocidos. PROGRESO es una cancha externa a dos cuadras: no implica presencia dentro del edificio. Un hueco no demuestra disponibilidad. La copia semanal no confirma asistencia ni feriados. Compará intervalos, sin unir recreos, usando código para cruces extensos. Con `siguiente`, conservá filtros y continuá con `cursor` antes de afirmar que un listado está completo.

`obtener_pdf` entrega un enlace descargable válido por 10 minutos. Compartilo cuando el usuario pida el PDF; si vence, pedí otro. El PDF de persona contiene solamente sus clases docentes; los demás cargos se consultan como JSON.
