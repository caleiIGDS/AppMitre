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

- [ ] #20 — Seguridad completa de `/gestion` (hoy: contraseña compartida provisoria) — `gestion.py` / `app.py` / hosting  
  Setear `GESTION_CLAVE` y `SECRET_KEY` como env vars en el hosting (los defaults del repo son públicos: clave conocida y cookie forjable), agregar CSRF a los forms, límite de intentos de login, y evaluar usuarios individuales con auditoría. Ver DECISIONS 2026-07-19.

- [ ] #21 — Búsqueda de recursos por sinónimos: columna `otros_nombres` + generación con IA — `gestion.py` / `static/gestion.css` / script nuevo  
  Muchas herramientas se conocen por varios nombres (Multímetro = tester = polímetro). Falta:
  1. Columna nueva `otros_nombres` (TEXT) en `recursos` — se edita en el form del recurso (no tabla aparte), migración vía `_migrar()`. Sumarla también a `_puntaje_busqueda()`.
  2. Script offline `generar_alias.py` que llena `otros_nombres` con IA (Claude) una sola vez, corriendo en la PC del dev — producción **no** necesita API key. Salida editable a mano. Costo: centavos, una vez.
  3. Opcional a futuro: botón "sugerir otros nombres" por recurso (eso sí requeriría la key en el hosting).
  **Ya hecho (2026-07-21)**: búsqueda tolerante sin IA — `_puntaje_busqueda()` normaliza acentos/mayúsculas y perdona typos por similitud (`difflib`). Resuelve acentos y typos; falta solo la parte de sinónimos que no se parecen ("tester"), que es lo que aporta `otros_nombres`.

- [ ] #22 — `listar_prestamos(persona)` filtra con `LIKE` crudo: no perdona acentos ni typos — `agente/tools/prestamos.py`  
  `persona LIKE '%x%'` es sensible a acentos, así que buscar "Damian Planes" no encuentra el préstamo de "Damián Planes" y el agente contesta "no hay préstamos a esa persona" — indistinguible de que no exista. La búsqueda de recursos ya resolvió esto en el mismo archivo (`_resolver_recurso`: exacto → substring normalizado → difuso con `texto.norm` y `_puntaje_nombre`); falta aplicar el mismo criterio a la persona. Ojo con el caso "no hay match": tiene que decir explícitamente que buscó y no encontró, no devolver `[]` a secas. Salió al investigar el reporte del 2026-08-11 (ver `dev-log/DECISIONS.md`), aunque no fue la causa de ese bug. Lo mismo aplica al `?q=` de `/gestion/prestamos`, que busca con `LIKE` en persona/destino/notas.

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

_Último número usado: #23. Próxima tarea nueva: #24_

_#4 (parser de preceptores por nombre de columna) descartada el 2026-07-13 — ver `dev-log/DECISIONS.md`: estructura del sheet fija por contrato._
