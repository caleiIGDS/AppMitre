# Sistema de Gestión de Conocimiento (`/gestion`)

Módulo independiente del sistema de horarios: la "memoria técnica viva" de la escuela.
Registra recursos, conjuntos, actividades y proyectos, y los conecta entre sí (red de
conocimiento, no carpetas aisladas). Los archivos reales (fotos, planos, guías) viven
en Google Drive; acá solo se guardan links (`drive_url`).

## Arquitectura

- **`gestion.py`** — todo el módulo: blueprint Flask (`bp`, prefix `/gestion`), schema,
  seed y rutas. Server-rendered con Jinja (sin JS propio), a diferencia del SPA de horarios.
- **`gestion.db`** — SQLite propia, separada de `escuela.db`. **No** se regenera desde
  Sheets y `/api/actualizar` no la toca. Es la única DB con datos propios de la app
  (en hosting efímero tipo Render se pierde en cada restart; en PythonAnywhere persiste).
- **`templates/gestion/`** — `base.html` (layout + nav), `home.html`, `lista.html`,
  `form.html`, `detalle.html`. Los tres últimos son **genéricos**: se renderizan a partir
  de la config declarativa de cada entidad.
- **`static/gestion.css`** — hoja standalone (paleta blueprint copiada, no importa
  `style.css` para que los dos sistemas no se pisen). Sin modo oscuro.
- Integración: `app.py` hace `app.register_blueprint(gestion.bp)` + `gestion.init_db()`
  en import (funciona bajo gunicorn/WSGI). `templates/index.html` tiene el link
  `GESTIÓN ›` en el header (`a.tech-btn-gestion`), y `base.html` el link de vuelta.

## Modelo de datos (gestion.db)

| Tabla | Campos |
|-------|--------|
| `recursos` | id, nombre, tipo, descripcion, ubicacion, estado, drive_url |
| `conjuntos` | id, nombre, descripcion, uso_tipico, drive_url |
| `actividades` | id, nombre, objetivo, descripcion, duracion, curso, drive_url |
| `proyectos` | id, nombre, descripcion, fecha, participantes, estado, drive_url |

M2M (con `UNIQUE` por par): `conjunto_recursos`, `actividad_recursos`,
`actividad_conjuntos`, `proyecto_recursos`.

Estados: recursos = Disponible / En uso / En reparación / De baja;
proyectos = Activo / Pausado / Terminado.

## Config declarativa (`ENTIDADES` en gestion.py)

Cada entidad define: `tabla`, `singular`/`plural`, `descripcion` (card del home),
`campos` (form: nombre, label, tipo `text|textarea|select|url|date`, opciones, ayuda),
`columnas` (listado) y `relaciones` (M2M editables desde su form, campos con prefijo
`rel_` para no colisionar con columnas). Para agregar un campo: sumarlo al `SCHEMA`
y a `campos` — pero SQLite no migra solo: si `gestion.db` ya existe hay que hacer
`ALTER TABLE` a mano o borrar la DB (pierde datos).

`LIMPIEZA_M2M` mapea qué tablas de relación limpiar al eliminar cada tipo de entidad.

## Rutas (todas server-rendered)

| Ruta | Método | Descripción |
|------|--------|-------------|
| `/gestion/` | GET | Home: cards con contadores + explicación de relaciones |
| `/gestion/<slug>` | GET | Listado (`?q=` busca en nombre + descripcion, LIKE) |
| `/gestion/<slug>/nuevo` | GET/POST | Alta (valida nombre no vacío server-side) |
| `/gestion/<slug>/<id>` | GET | Detalle: campos + relaciones en ambas direcciones |
| `/gestion/<slug>/<id>/editar` | GET/POST | Edición (sincroniza M2M: delete + insert) |
| `/gestion/<slug>/<id>/eliminar` | POST | Borra fila + sus filas M2M (confirm en el browser) |

`slug` ∈ {recursos, conjuntos, actividades, proyectos}; otro valor → 404.

Relaciones mostradas en detalle (`_secciones_detalle`): recurso → conjuntos que lo
incluyen / actividades que lo usan / proyectos relacionados; conjunto → recursos
incluidos / actividades que lo usan; actividad → conjuntos + recursos utilizados;
proyecto → recursos generados.

## Seed

`init_db()` crea las tablas y, si `recursos` está vacía, carga el ejemplo del documento
de diseño: 5 recursos, conjunto "Banco de ensayo solar" (panel + estructura +
inclinómetro), actividad "Medición de panel solar según inclinación" (usa el conjunto +
multímetro + pinza) y proyecto "Construcción del banco de ensayo solar".

## Sin auth

Como el resto de la app, no hay autenticación: cualquiera con la URL puede crear,
editar o borrar. Riesgo aceptado al mismo nivel que `/api/actualizar`.
