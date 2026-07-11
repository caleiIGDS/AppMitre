# Backlog — AppMitre

---

## Media prioridad

- [ ] #3 — API devuelve objetos con claves nombradas (E3 PLAN_ESCUELAS) — `app.py` + `script.js`  
  Actualmente el frontend accede a `f[0]`, `f[5]`, `f[9]`, etc. (índice numérico). Cambiar la API para devolver `{curso, division, materia, profesor, aula, ...}` y actualizar las ~60+ referencias en `script.js`. Es el mayor refactor pendiente. Ver `agent_docs/search-api.md` para la tabla de índices.

- [ ] #4 — Parser de preceptores por nombre de columna (E4 PLAN_ESCUELAS) — `database.py`  
  `cargar_horarios_preceptores()` asume offsets fijos 0/10/20. Si el sheet cambia, los datos se corrompen silenciosamente. Definir un formato estándar con encabezados y parsear por nombre.

- [ ] #5 — `TURNO_CURSOS` en config: poblar con datos reales — `config.py`  
  Actualmente vacío `{}`. Todos los cursos muestran turno "MAÑANA" por default en la planilla de preceptores. Necesita configuración real.

- [ ] #6 — Invalidar `allDataCache` al actualizar la DB — `script.js`  
  Cuando el usuario hace "ACTUALIZAR HORARIOS", `allDataCache` queda obsoleto pero no se limpia. La Planilla General mostraría datos viejos hasta F5. Solución: `allDataCache = null` en el callback de éxito de `actualizarDatos()`.

- [ ] #7 — `FLOOR_MAPPING` tiene aulas solapadas entre pisos — `config.py`  
  "Piso 1" y "Piso 3" comparten aulas "13","14","15","16". Verificar con la escuela si es intencional (ej: el "Piso 3" es en realidad un tercer sector del piso 1) o si es un error de configuración.

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

- [ ] #14 — `DOCUMENTACION_DETALLADA.md` desactualizada — root  
  Menciona `corregir_horarios()` que ya no existe. Considerar fusionarla con los `agent_docs/` o eliminarla para evitar documentación contradictoria.

- [ ] #16 — Título del calendario no se ve al generarse — `script.js` / `style.css`  
  El título que debería aparecer encima del calendario no es visible cuando se genera el resultado.

- [ ] #17 — Reducir margen entre `.tech-search-module` y el calendario — `style.css`  
  Hay demasiado espacio visual entre el módulo de búsqueda y el calendario generado. Ajustar `margin-bottom` de `.tech-search-module` y/o `margin-top` del contenedor del calendario.

- [ ] #18 — Íconos de UI como imágenes locales en vez de SVG/emoji inline — `static/js/script.js` + `templates/index.html` (+ `static/images/`)  
  Poner el ícono del **botón de tema** (`#btn-tema`) en una imagen local (ej: `static/images/luna.svg` / `sol.svg`) en vez de las constantes SVG inline `ICONO_LUNA` / `ICONO_SOL` en `script.js`. Revisar y aplicar lo mismo a los otros íconos inline/emoji del proyecto:
  - `script.js`: `⚠️` de superposición (líneas ~420, ~708, ~1366, ~1705), `✕` de cierre de chips (~161, ~246).
  - `index.html`: `⚡` del banner MODO COMPARACIÓN (~155), `✕ SALIR` (~158), `‹` de los `.btn-slide-trigger` (5 usos).
  - El logo ya es imagen local (`escuela_logo`) — usar ese patrón (`url_for('static', ...)`). Definir tamaño/color vía CSS y contemplar el tema oscuro (los SVG actuales usan `currentColor`).

---

## Bloqueado

- [ ] #15 — Multi-escuela (Fase 2 y 3 de PLAN_ESCUELAS)  
  **Bloqueado por**: requiere #9 (página admin) completado primero. Las fases 2 y 3 de `PLAN_ESCUELAS.md` (parser por nombre de columna, API con objetos, turnos configurables) son pre-requisitos.

---

_Último número usado: #18. Próxima tarea nueva: #19_
