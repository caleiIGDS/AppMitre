# Backlog — AppMitre

---

## Baja prioridad / ideas

- [ ] #8 — Refactorizar `script.js` en módulos separados — `static/js/`  
  ~1600 líneas en un solo archivo. Candidatos naturales: `calendar.js`, `dashboard.js`, `planilla.js`, `comparison.js`, `ui.js`, `api.js`. Sin build step, usar `<script type="module">`.

- [ ] #9 — Página de administración `/admin` (E1 PLAN_ESCUELAS) — `app.py` + new template  
  UI para editar `SHEET_ID`, `GIDS`, `FLOOR_MAPPING`, mapeos de nombres, y turnos sin tocar código. Requiere tabla `config` en SQLite y protección básica con contraseña.

- [ ] #10 — Años escolares dinámicos desde config (E7 PLAN_ESCUELAS) — `database.py` + `config.py`  
  Hoy son exactamente 7 años fijos (1ro–7mo). Hacerlo configurable desde la UI admin.

- [ ] #11 — Turnos configurables y renderizado dinámico (E5 PLAN_ESCUELAS) — `app.py` + `script.js`  
  Eliminar los arrays hardcodeados MAÑANA/TARDE/VESPERTINO. Los turnos deben venir de config.

- [ ] #12 — Autenticación básica para `/api/actualizar` — `app.py`  
  Al menos un token simple o clave en header para evitar recargas de DB no autorizadas.

- [ ] #13 — Tooltip en modo comparación — `script.js`  
  El tooltip (`showTooltip`) en modo comparación pasa algunos valores hardcodeados (`'-'` para aula y curso). Mejorar para que muestre info correcta según el modo de comparación.

- [ ] #16 — Título del calendario no se ve al generarse — `script.js` / `style.css`  
  El título que debería aparecer encima del calendario no es visible cuando se genera el resultado.

- [ ] #17 — Reducir margen entre `.tech-search-module` y el calendario — `style.css`  
  Hay demasiado espacio visual entre el módulo de búsqueda y el calendario generado. Ajustar `margin-bottom` de `.tech-search-module` y/o `margin-top` del contenedor del calendario.

- [ ] #18 — Íconos de UI como imágenes locales en vez de SVG/emoji inline — `static/js/script.js` + `templates/index.html` (+ `static/images/`)  
  Poner el ícono del **botón de tema** (`#btn-tema`) en una imagen local (ej: `static/images/luna.svg` / `sol.svg`) en vez de las constantes SVG inline `ICONO_LUNA` / `ICONO_SOL` en `script.js`. Revisar y aplicar lo mismo a los otros íconos inline/emoji del proyecto:
  - `script.js`: `⚠️` de superposición (líneas ~420, ~708, ~1366, ~1705), `✕` de cierre de chips (~161, ~246).
  - `index.html`: `⚡` del banner MODO COMPARACIÓN (~155), `✕ SALIR` (~158), `‹` de los `.btn-slide-trigger` (5 usos).
  - El logo ya es imagen local (`escuela_logo`) — usar ese patrón (`url_for('static', ...)`). Definir tamaño/color vía CSS y contemplar el tema oscuro (los SVG actuales usan `currentColor`).

- [ ] #24 — Endurecer los accesos si algún día hace falta — `accesos.py` / hosting  
  Lo que quedó explícitamente fuera del sistema de accesos del 2026-08-11 por estar sobredimensionado para una escuela (ver `agent_docs/accesos.md`, última sección). Sólo abordar si aparece un motivo real:
  - **CSRF** en los forms que escriben (hoy no hay; la cookie es `SameSite=Lax`, que cubre el caso común).
  - **Límite de intentos** en el login de admin — es la única puerta que sigue siendo una contraseña.
  - **Google Sign-In** como segunda puerta: las columnas `email` / `google_sub` de `dispositivos` ya están reservadas y el gate lee "identidad" en abstracto, así que se suma sin migrar nada ni tocar los permisos.
  - **Corte fino por área en el agente**: hoy `agente.escribir` habilita escribir en gestión **y** en historia, porque las tools genéricas por slug cruzan las dos. Si hiciera falta separarlas, el lugar es `ejecutar_tool` mirando `_modulo(slug)`, no el esquema.

- [ ] #23 — `config.TURNO_CURSOS` desfasado contra la planilla de preceptores — `config.py` (+ confirmar con la escuela)  
  Hay **7 cursos** donde el turno que dice `config.TURNO_CURSOS` no tiene **ninguna fila** en `horarios_preceptores`. Consecuencia: el agente devuelve `titular` vacío (hay una rama en `NOTA_TURNOS` que lo explica, pero es un parche sobre datos mal) y el SPA no marca ningún "PRECEPTOR PRINCIPAL" en la vista de curso.

  | curso | config dice | la planilla tiene |
  |---|---|---|
  | 3° B | MAÑANA | TARDE |
  | 4° 6 | TARDE | MAÑANA + VESPERTINO |
  | 4° 7 | TARDE | MAÑANA + VESPERTINO |
  | 5° 2 | TARDE | MAÑANA |
  | 6° 3 | TARDE | VESPERTINO |
  | 6° 7 | VESPERTINO | MAÑANA + TARDE |
  | 7° 5 | VESPERTINO | TARDE |

  Además `("3", "")` y `("4", "G")` no están en el mapa y caen silenciosamente a `TURNO_DEFAULT` ("MAÑANA"). **Antes de tocar nada hay que preguntar en la escuela cuál de los dos está bien**: puede ser config viejo, o puede ser que falte cargar gente en el Sheet. No es un bug de código. Salió al arreglar el bug de turnos del agente el 2026-08-11 (ver `dev-log/DECISIONS.md`).

---

## Bloqueado

- [ ] #15 — Multi-escuela (Fase 2 y 3 de PLAN_ESCUELAS)  
  **Bloqueado por**: requiere #9 (página admin) completado primero. Pre-requisitos restantes: #11 (turnos configurables), #10 (años dinámicos). Ya completados: plantilla estándar (`PLANTILLA_SHEET.md`, ex #19) y API con objetos (ex #3, 2026-07-13). E2/E4 ya no aplican — la estructura del sheet es fija por contrato (decisión 2026-07-13).

---

_Último número usado: #24. Próxima tarea nueva: #25_

_#4 (parser de preceptores por nombre de columna) descartada el 2026-07-13 — ver `dev-log/DECISIONS.md`: estructura del sheet fija por contrato._
