---
name: nueva-tarea
description: Flujo para definir, planificar y registrar una nueva tarea de desarrollo.
Activar cuando el usuario diga "nueva tarea", "vamos a hacer una nueva tarea",
"quiero agregar una feature", "tengo una tarea nueva" o cualquier variante que indique
inicio de trabajo planificado. NO activar para pedidos directos de código sin planificación previa.
---

# Nueva Tarea

Antes de escribir cualquier código, asegurate de entender bien qué hay que hacer.

## Antes de responder
`CLAUDE.md` ya está en contexto. Leé `dev-log/tasks/IN-PROGRESS.md` y `TODO.md`.
De los `agent_docs/` leé **sólo la sección que toca la tarea** (Grep por el archivo o
el símbolo): varios pasan las 40 KB y leerlos enteros se paga en cada mensaje que sigue.

## Flujo
1. Si la descripción tiene ambigüedades que cambiarían la implementación,
   preguntale al usuario todo junto en un solo mensaje — no de a una por vez.
2. Presentá la definición completa: qué se hace, qué NO se hace,
   archivos involucrados, y criterios de aceptación verificables.
3. Preguntá: **¿Arrancamos ahora o lo guardamos en el backlog?**
   - Ahora → agregá a `IN-PROGRESS.md` y empezá
   - Backlog → agregá a `TODO.md` con la prioridad que indique el usuario

## Reglas
- No escribir código hasta que el usuario confirme
- El "qué NO incluye" es obligatorio — evita scope creep
- Los criterios de aceptación deben ser verificables con sí/no
