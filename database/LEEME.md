# Las bases de AppMitre

Todas las bases del proyecto viven acá. Son SQLite, **ninguna viaja por git** (`*.db` está
en `.gitignore`) y **no hay una sola FK que cruce de un archivo a otro**: cada área es dueña
de la suya y las referencias entre bases son enteros sueltos, a propósito.

Este archivo contesta una sola pregunta, que es la que importa parado en esta carpeta:
**si este archivo se pierde, ¿qué pasa?** Qué área usa cada base está en `CLAUDE.md`.

| Archivo | Qué guarda | Si se pierde | Respaldo |
|---|---|---|---|
| `gestion.db` | El **registro** de inventarios (nombre, slug, clave hasheada) + las tablas del asistente: auditoría, conversaciones y fotos pendientes | Se pierde la lista de inventarios y sus claves: los `inventarios/*.db` quedan huérfanos, con sus datos pero sin nadie que sepa abrirlos | `gestion-registro-*` |
| `inventarios/<slug>.db` | Los recursos de **un** inventario: unidades, kits y bajas. Un archivo por inventario, sin nada en común | Se pierde ese inventario y ningún otro. El registro lo sigue listando, y `total_recursos` avisa que el archivo no está | `inv<id>-*` (por id, no por slug: `taller` y `taller-2` no comparten rotación) |
| `accesos.db` | Dispositivos habilitados, invitaciones y los permisos de cada uno | Hay que volver a invitar a todo el mundo. El admin sigue entrando con `GESTION_CLAVE`, que no está acá sino en el entorno | `accesos-*` |
| `salidas.db` | Los legajos de salidas educativas (Anexos III–IX), con vigencia de un año | Se pierden los legajos cargados. Los PDF de `salidas_pdfs/` quedan sin su fila y no se regeneran solos | `salidas-*` |
| `estudiantes.db` | El padrón, con DNI de menores. **Es el archivo más sensible de la carpeta** | Se recarga entero desde el CSV del padrón, que no vive acá | `estudiantes-*` |
| `historia.db` | Hitos y personas. El área está **apagada** (`historia.ACTIVA = False`): nadie escribe acá hoy | Nada, mientras siga apagada. Se conserva porque prenderla es cambiar un flag | `historia-*` |
| `agente.db` | Telemetría del asistente: una fila por turno (`/agente/uso`) | Se pierde el historial de uso y nada más | **ninguno, a propósito** — crece sin techo y 20 copias rotativas se comerían el disco |
| `escuela.db` | Los horarios: clases, preceptores y personal no docente | Nada permanente: se regenera desde Google Sheets, sola al arrancar o con `POST /horarios/api/actualizar` | **ninguno, a propósito** — la fuente de verdad es la planilla |

## `backups/`

La rotación de `respaldos.py`: **las últimas 20 copias de cada base, más la primera de cada
día**. Se escribe una en cada arranque de la app, antes de cualquier migración de schema, y
sólo si la base tiene datos — un respaldo vacío encima de los buenos sería justo lo que
arruinaría la recuperación.

Restaurar es copiar el archivo encima del original y reiniciar. El prefijo dice de quién es
cada copia; los `gestion-*.db` viejos (sin `-registro`) son de cuando gestión era **un** solo
inventario, antes de que se partiera en varios.

Aparte de la rotación pueden aparecer archivos `*.pre-actualizacion-<fecha>`: los deja
`actualizar.py` antes de migrar y **no los borra nadie**. Se borran a mano cuando se verificó
que el deploy anda.

## Si la carpeta se vacía

La app **no arranca**, y es a propósito. Una base vacía es ambigua —instalación nueva o datos
perdidos— y los respaldos desempatan: si existen, esto ya estuvo cargado alguna vez y seguir
de largo taparía la pérdida en silencio (pasó el 2026-08-08, ver `dev-log/DECISIONS.md`). La
guarda está en `crud.init_db`, y `app.py` tiene otra que frena si los archivos quedaron en el
layout viejo, desparramados por la raíz.
