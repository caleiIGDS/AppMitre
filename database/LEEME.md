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
| `fotos/` | Los archivos de las fotos de recursos (`fotos/<uuid>.<ext>`, uno por foto), referenciados por `id` desde la columna `fotos` de cada inventario — ver `fotos_disco.py`. `fotos/mini/` son sus miniaturas: se regeneran solas | Las fichas quedan sin sus fotos (404 al servir), pero el resto del recurso sigue intacto | **ninguno, a propósito** — no rota con `respaldos.py`: son archivos inmutables (rotar reemplaza, no versiona), pensada para una DB que muta fila a fila, ver `dev-log/DECISIONS.md` |
| `accesos.db` | Dispositivos habilitados, invitaciones y los permisos de cada uno | Hay que volver a invitar a todo el mundo. El admin sigue entrando con `GESTION_CLAVE`, que no está acá sino en el entorno | `accesos-*` |
| `salidas.db` | Los legajos de salidas educativas (Anexos III–IX), con vigencia de un año | Se pierden los legajos cargados. Los PDF de `salidas_pdfs/` quedan sin su fila y no se regeneran solos | `salidas-*` |
| `agente.db` | Telemetría del asistente: una fila por turno (`/agente/uso`) | Se pierde el historial de uso y nada más | **ninguno, a propósito** — crece sin techo y 20 copias rotativas se comerían el disco |
| `escuela.db` | Los horarios: clases, preceptores y personal no docente | Nada permanente: se regenera desde Google Sheets, sola al arrancar o con `POST /horarios/api/actualizar` | **ninguno, a propósito** — la fuente de verdad es la planilla |
| `horarios_oauth.db` | Clientes OAuth y hashes de autorizaciones del MCP | Hay que volver a conectar los clientes de IA; los horarios siguen intactos. Se crea sola, separada de la regeneración desde Sheets | Ninguno: se recupera reconectando |

## `backups/`

La rotación de `respaldos.py`: **las últimas 20 copias de cada base, más la primera de cada
día**. Se escribe una en cada arranque de la app, antes de cualquier migración de schema, y
sólo si la base tiene datos — un respaldo vacío encima de los buenos sería justo lo que
arruinaría la recuperación.

"La primera de cada día" no caduca nunca, **salvo que el área le ponga un techo**: hoy sólo
lo hace `salidas.db` (`BACKUP_MAX_DIAS = 60`), porque sus filas vencen al año y se purgan
solas — sin ese techo, una salida purgada seguiría viva para siempre en `salidas-*.db` y la
purga no purgaría nada. Las últimas 20 se conservan igual, por viejas que sean.

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
