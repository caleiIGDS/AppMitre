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

- [ ] #21 — Búsqueda de recursos más flexible: columna `otros_nombres` + generación con IA — `gestion.py` / `static/gestion.css` / script nuevo  
  Muchas herramientas se conocen por varios nombres (Multímetro = tester = polímetro). Plan:
  1. Columna nueva `otros_nombres` (TEXT) en `recursos` — se edita en el form del recurso (no tabla aparte), migración vía `_migrar()`.
  2. Búsqueda (`lista()`) matchea nombre + descripcion + **otros_nombres**, y **normaliza acentos** (hoy `LIKE` es literal: "multimetro" sin tilde no encuentra "Multímetro"). Ver búsqueda más "perdonadora" abajo.
  3. Script offline `generar_alias.py` que llena `otros_nombres` con IA (Claude) una sola vez, corriendo en la PC del dev — producción **no** necesita API key. Salida editable a mano. Costo: centavos, una vez.
  4. Opcional a futuro: botón "sugerir otros nombres" por recurso (eso sí requeriría la key en el hosting).
  Búsqueda tolerante a typos (sin IA): normalizar acentos + comparar por similitud (`difflib.SequenceMatcher` o distancia de edición) además del substring. Ver notas de diseño en la conversación.

---

## Bloqueado

- [ ] #15 — Multi-escuela (Fase 2 y 3 de PLAN_ESCUELAS)  
  **Bloqueado por**: requiere #9 (página admin) completado primero. Pre-requisitos restantes: #11 (turnos configurables), #10 (años dinámicos). Ya completados: plantilla estándar (`PLANTILLA_SHEET.md`, ex #19) y API con objetos (ex #3, 2026-07-13). E2/E4 ya no aplican — la estructura del sheet es fija por contrato (decisión 2026-07-13).

---

_Último número usado: #21. Próxima tarea nueva: #22_

_#4 (parser de preceptores por nombre de columna) descartada el 2026-07-13 — ver `dev-log/DECISIONS.md`: estructura del sheet fija por contrato._
