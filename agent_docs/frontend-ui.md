# Frontend y UI — AppMitre

> Complementa `CLAUDE.md`. Estilos en `static/horarios.css` (que importa `global.css`), estructura en `templates/index.html`.
> El escudo del header está en `static/global.css` (`.marca`), compartido con todas las áreas.

---

## Sistema de variables CSS

```css
:root {
    --primary:    #1A365D;   /* azul marino oscuro */
    --accent:     #D97A34;   /* acento único: naranja/ámbar apagado */
    --alert:      #DC2626;   /* rojo */
    --tech-bg:    #F1F5F9;   /* gris muy claro, fondo general */
    --white:      #ffffff;
    --dark:       #0F172A;   /* casi negro, texto principal */
    --grid-color: rgba(26, 54, 93, 0.08);  /* azul muy transparente para grilla */
    --surface:    #ffffff;   /* superficies (los temas lo sobrescriben) */
    --border:     #cbd5e1;   /* bordes finos */
    --muted:      #70757a;   /* texto secundario */
    --radius:     0px;
    --font-ui:    'Roboto Mono', monospace;  /* fuente global */
}
body {
    --secondary:  var(--accent);  /* ALIAS legacy: los ~36 usos de var(--secondary) pasan por --accent */
    --accent-soft: color-mix(in srgb, var(--accent) 12%, transparent);
}
```

> **El naranja chillón `#FF6B00` fue reemplazado** por un ámbar apagado (`--accent: #D97A34`).
> Cambiar `--accent` re-skinea los 36+ usos de `var(--secondary)`.
>
> `--secondary` y `--accent-soft` se declaran en **`body`** (derivan de `--accent`).
> Ver la sección **Tema (claro ↔ oscuro)** al final.

### Usos específicos por color

**`--primary` (#1A365D)**:
- Header y footer backgrounds
- Bordes del calendario y del search module
- Texto de títulos y labels
- Fondo de bloques de clase en el calendario
- Botón slide-trigger en hover
- Cabeceras de tabla

**`--secondary` (alias de `--accent`, default ámbar #D97A34)**:
- Botón "ACTUALIZAR HORARIOS" (borde y color)
- Tab activo
- Botón PDF (fondo)
- Borde inferior del header
- Borde de la barra de estado lateral
- Punto activo en el slide-panel cuando está abierto
- Scroll thumb en la comparación
- Badge de rol en el autocompletado
- Flecha del reloj digital

**`--alert` (#DC2626)**:
- Bloque `.bloque-superposicion` (fondo)
- Texto "LICENCIADA" en bloques del calendario
- El rojo en el modal de superposición

---

## Fondo blueprint

```css
.blueprint-bg {
    background-image:
        linear-gradient(var(--grid-color) 1px, transparent 1px),
        linear-gradient(90deg, var(--grid-color) 1px, transparent 1px);
    background-size: 20px 20px;
}
```

Grilla de 20×20px en azul muy transparente sobre el fondo `--tech-bg`. En modo fullscreen, el background se reemplaza por `--tech-bg` sólido (sin grilla) para reducir distracción visual.

---

## Tipografía

**Browser**: Roboto Mono **auto-hospedada** — `@font-face` en `static/global.css` apuntando a `static/fonts/robotomono-<peso>-<subset>.woff2` (pesos 400, 600, 700; subsets latin y latin-ext; `font-display: swap`). No hay ningún `<link>` a `fonts.googleapis.com`: eran dos orígenes extra con su propio DNS y TLS, los dos bloqueando el pintado.

**PDF (fpdf2)**: misma fuente pero desde archivos locales en `static/fonts/`:
- `RobotoMono-Regular.ttf`
- `RobotoMono-Bold.ttf`
- `RobotoMono-Italic.ttf`

Los archivos locales son necesarios porque fpdf2 no puede usar Google Fonts. El browser usa la CDN; el servidor usa los archivos locales. Son la misma fuente para consistencia visual entre pantalla y PDF.

---

## Patrones de componentes

### Tabs con clip-path

```css
.tech-tag {
    clip-path: polygon(10% 0%, 100% 0%, 90% 100%, 0% 100%);
}
```

Crea el efecto de pestaña inclinada (paralelogramo). El mismo `clip-path` se aplica al botón PDF (`.tech-btn-pdf`). **Para agregar una tab nueva**: copiar el patrón HTML existente en `index.html` con `onclick="cambiarTab(event, 'tab-nueva')"` y agregar el `<div id="tab-nueva" class="seccion-busqueda">` correspondiente.

### Modal de detalle

- Activado: `mostrarInfoClase(json, element)` → `abrirModal(titulo, html)`
- Estructura: `.modal-detalles` (overlay fijo, `z-index: 2000`) > `.modal-contenido` > `.modal-header` + `#modal-body`
- `box-shadow: 10px 10px 0 var(--secondary)` — sombra desplazada característica del estilo industrial
- Cierre: botón ×, click fuera del `.modal-contenido`, o `cerrarModal()`
- Los valores de profesor, aula y curso en el modal son clickeables (`.clickable-valor`) y navegan a ese horario via `navegarDesdeModal(modo, valor)`

### Panel lateral deslizable (slide-panel)

```css
.slide-panel {
    max-width: 0;
    opacity: 0;
    transition: max-width 0.3s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.15s, padding 0.3s;
}
.slide-panel.open {
    max-width: 600px;
    padding: 0 14px;
    opacity: 1;
}
```

Se expande horizontalmente desde la derecha del input. Contiene botones de opciones (COMPARAR, PLANILLA GENERAL). El trigger es el botón circular `‹` (`.btn-slide-trigger`). Solo un slide-panel puede estar abierto a la vez — `toggleSlidePanel` cierra todos los demás antes de abrir el solicitado.

Cuando se selecciona una opción del slide-panel, el botón se reemplaza por un "chip" (`.opcion-chip`) que muestra la opción activa con un botón de cierre ×. Para salir de esa opción, se hace click en el × del chip.

### Bloques del calendario

Clase base: `.materia-bloque`
- Fondo: `--primary` (azul marino)
- Texto blanco
- `position: absolute`
- Estructura interna:
  - `.materia-contenido` → materia + detalle (profesor o curso según modo)
  - `.aula-indicador` → banda inferior oscura con número de aula o curso

**Variantes de estado:**
- `.materia-bloque.selected` → `box-shadow: 0 0 0 3px var(--secondary)` (borde de acento cuando está seleccionado via click)
- `esPersonal`: agrega la clase `.personal-cargo-bloque` (estilo en CSS, **no** inline) → fondo tinte de acento + `border-left: 3px solid var(--accent)` + texto `--primary`. Antes tenía hex hardcodeado en el JS; se movió a CSS para que respete el tono activo.
- `suplente_activo=1` en vista de profesor: texto "LICENCIADA" en `var(--alert)` en lugar del nombre de la materia
- `.bloque-superposicion` → `background-color: var(--alert)` — ocupa todo el ancho de la columna, muestra `⚠️ Superposición (N)`
- `.aula-indicador.sin-numero` → para aulas sin número (ej: PATIO, GYM); mismo estilo pero texto más pequeño (font-size: 11px)

---

## El escudo del header (`.marca` en `static/global.css`)

El escudo, su bloque de título y el shell de página (`.g-bg` → `.g-shell` → `.g-footer`) están en
**`global.css`** (capa 0 — no nombra nada del dominio). Es compartido por todas las **siete**
pantallas con header — las seis del shell de áreas y el SPA de horarios. Cada área importa
`global.css` (directa o indirectamente via `gestion.css`/`horarios.css`); el login de horarios lo
carga **solo**, sin `horarios.css`, porque esa hoja es del SPA y su regla suelta sobre `footer` le
pisaría el pie de página.

```html
<link rel="stylesheet" href="…global.css">    <!-- primero: paleta, reset, escudo -->
<link rel="stylesheet" href="…gestion.css">   <!-- área específica (importa global.css) -->
…
<div class="marca">
  <img class="marca-escudo" src="…" alt="Escudo">
  <div class="g-titles">…</div>                <!-- la tipografía sigue siendo de cada área -->
</div>
```

`.marca` define dos reglas y expone **dos variables**, que son lo único que un área toca:

| variable | qué es |
|---|---|
| `--escudo` | alto del escudo (88px por defecto). De ahí salen el hueco que se le reserva a la izquierda (`padding-left: calc(var(--escudo) + 8px)`) y, por defecto, el alto de la fila |
| `--marca-alto` | alto de la fila de marca, sólo donde la barra del área es **más baja** que el escudo (celular) y por eso no puede derivarse de `--escudo` |

Un breakpoint de área queda así, sin tocar `global.css`:

```css
@media (max-width: 420px) { .marca { --escudo: 64px; --marca-alto: 36px; } }
```

Se overridea **por variables y no por reglas que pisen a `global.css`**, así que funciona sin
importar el orden de las hojas: el CSS en cascada lo resuelve todo.

Dos cosas que parecen raras y son a propósito:

- **El escudo está fuera del flujo** (`position: absolute` + centrado con `translateY(-50%)`), y su
  hueco lo reserva el `padding-left` de `.marca`. Así crece o se achica sin empujar el alto de la
  barra ni el ancho de la marca — que es lo que obliga a los botones del header a envolver en una
  segunda línea y estira la barra.
- **No lleva `border` ni `border-radius`.** Sobre un `<img>` el `border-radius` **recorta la
  imagen**: un `50%` heredado le comía las puntas al escudo y lo hacía ver más chico de lo que
  medía.

Las dos barras van ajustadas al escudo: 88px + 4px de aire arriba y abajo = **96px**, tanto en
horarios como en las áreas.

---

## Menú de áreas (☰) — en las cinco páginas del shell de `accesos`

Gestión, historia, agente, salidas y accesos tienen un **☰** que abre un panel lateral con las
otras áreas. Cada página omite la suya, y cada link va por su permiso (`{% if puede(...) %}`), así
que el admin las ve todas y un interno de consulta ve sólo las que puede abrir. El
`{% if acceso_actual() %}` que envuelve el panel sigue en los templates por las dudas.

**El SPA de horarios ya no participa.** Desde que `/horarios` es un sitio aparte (login propio,
sin `accesos`), su `index.html` no tiene ☰ ni `areas-nav.js`: sólo un botón **SALIR** →
`url_for('horarios.salir')`. Los `‹ SISTEMA DE HORARIOS` de las otras áreas siguen apuntando a
`/`, que redirige a `/horarios/` y cae en su login — un salto entre sitios, no un menú.

### Qué va dónde (shell de `accesos`)

| | contenido |
|---|---|
| `.g-nav` | las **entidades de esta área** (RECURSOS, HITOS…). El 🤖 ASISTENTE salió de acá: no era una entidad |
| `.g-header-actions` | acciones **de esta página**: el toggle del widget del asistente y `‹ SISTEMA DE HORARIOS` como salida |
| el ☰ | **saltar a otra área** + SALIR |

`SALIR` apunta a `url_for('salir_general')` — el logout de la app, que vuelve a `/`, y no al
`/salir` de un área, que devolvería a un login donde un interno no tiene contraseña que poner.

### `mobile-nav.js` (`gestion.css`)

El panel `.g-sidebar` entra desde la izquierda. `.g-areas` se renderiza server-side al final del
`<body>` y el JS lo **mueve** al panel a cualquier ancho; ≤900px además mueve `.g-nav` y
`.g-header-actions` y los devuelve al header al agrandar (para preservar los listeners de
`gestion-agente.js`). El ☰ se dibuja sólo si el panel tiene algo (`.g-visible`): en la pantalla de
login de escritorio no hay áreas que ofrecer. `.g-areas` está oculto fuera del panel
(`display: none`, `flex` sólo bajo `.g-sidebar`) para que no se vea suelto antes de que corra el JS.

**Clases** (`gestion.css`): `.g-menu-btn` (+ `.g-visible`), `.g-menu-bars`, `.g-sidebar*`,
`.g-areas` / `.g-areas-salir`; estado abierto `body.g-sidebar-abierto`. En `horarios.css` quedaron
`.tech-btn-menu` / `.areas-panel*` del ☰ viejo del SPA — **sin uso** desde que horarios se separó.

---

## Modo kiosco (fullscreen)

Activado con F11 via `document.documentElement.requestFullscreen()`. El event `fullscreenchange` agrega/quita la clase `is-fullscreen` en `body`.

### Qué se oculta con `is-fullscreen`:

```css
body.is-fullscreen .tech-header { display: none !important; }
body.is-fullscreen footer { display: none !important; }
body.is-fullscreen .tech-tags { display: none !important; }
body.is-fullscreen #tab-profesor { display: none !important; }
body.is-fullscreen #tab-aula { display: none !important; }
body.is-fullscreen #tab-curso { display: none !important; }
/* El ☰ se va con el header; el panel y su fondo se esconden aparte por si estaba
   abierto al entrar al modo kiosco. */
body.is-fullscreen .areas-panel,
body.is-fullscreen .areas-overlay { display: none; }
```

El tab "TIEMPO REAL" y su contenido sí son visibles (`.tech-live-module`, `.sys-clock`).

### Cambios de layout en fullscreen:

- `.blueprint-bg` → background plano sin grilla
- `.tech-container` → `max-width: 100%; height: 100vh; flex-direction: column`
- `.tech-workspace` → `flex: 1; overflow-y: auto`
- `.sys-clock` → baja de 40px a 32px
- `.dashboard-grid-light` → `grid-template-columns: 1fr` (columna única)
- `.dashboard-column-light.upcoming` → `display: none` (solo "En Curso")
- En pantallas ≥900px: `.class-list-light` pasa a `grid-template-columns: 1fr 1fr`

---

## PDF (`/export/pdf/<tipo>/<valor>` y `/export/pdf/cursos/<seleccion>`)

### Características técnicas

- Orientación: landscape A4 (297×210mm). Grid de 267mm de ancho; el alto es dinámico: arranca donde terminó el encabezado (`pdf.get_y()`, ~25mm con preceptores, ~17mm sin) y termina en y=199mm. `_crear_pdf_horario()` desactiva el auto page break de fpdf (el grid pasa el trigger de y=190 y fpdf insertaría páginas en blanco)
- Fuente: Roboto Mono embedded (Regular, Bold, Italic)
- Sin header (`class PDF(FPDF): def header(self): pass`)
- Footer: "by Calei" en itálica
- El dibujo de una página vive en `dibujar_pagina_horario(pdf, tipo, valor)` (`app.py`); `/export/pdf/cursos/<seleccion>` la llama en loop para generar un PDF multipágina (una página por curso)

### Selector de impresión múltiple (IMPRIMIR VARIOS)

Botón IMPRIMIR VARIOS en el slide-panel de CURSOS → `abrirModalImprimirCursos()` reusa el modal genérico (`abrirModal`) con clases `.print-cursos-*`: botón TODOS, una fila por año (botón-label `N°` que togglea el año entero + chips por división) y footer con contador + GENERAR PDF. Estado en el Set global `cursosSeleccionadosPDF` (se resetea al abrir); `actualizarSeleccionImpresion()` sincroniza clases `.selected` y el disabled del botón. Los estilos usan solo tokens (`--surface`, `--border`, `--secondary`, `--muted`) → tema nocturno sin reglas extra (solo `border-radius`).

### Diferencia por tipo

| Tipo | Título | Columnas | Indicador inferior de bloque |
|---|---|---|---|
| `profesor` | "Horario Semanal de Profesor: X" | Lunes–Viernes | Aula |
| `aula` | "Horario Semanal de Aula: X" | Lunes–Viernes | Curso° Div |
| `curso` | "Horario Semanal de Curso: X" | Lunes–Viernes | Aula + info preceptor bajo título |
| `planilla` | "Planilla General: Piso X - Día" | Aulas del piso | Curso° Div |

Para `tipo == 'curso'`, agrega una línea con preceptores (T.M / T.T / T.N) entre el título y el grid, alineados izquierda/centro/derecha.

### Truncado de texto en bloques PDF

El PDF usa columnas más angostas que la pantalla. Lógica de truncado:
1. Intentar renderizar el texto completo con `multi_cell(w, line_h, texto, split_only=True)`
2. Si `len(líneas) > max_permitido`: truncar la última línea carácter por carácter mientras `get_string_width(última) > ancho - margen`
3. El font-size y line-height cambian según el tamaño disponible:
   - `is_narrow` (ancho < 20mm): font 7.2/5.8, line_h 2.7
   - `is_short` (alto < 20mm): font 8.0/7.0, line_h 3.0
   - `is_tiny` (alto < 12mm): font 7.0/6.0, line_h 2.5
   - Normal: font 9.5/8.0, line_h 3.8

### Posicionamiento de texto en PDF

`obtener_datos_calendario()` en `app.py` preprocesa las filas del backend para el PDF (no reutiliza la lógica JS del frontend). Hace el mismo clustering que el JS pero con Python, devolviendo `bloques_por_columna` con campos `tipo`, `ancho`, `left`, `clase`.

**Nota**: hay código de ajuste anti-colisión de etiquetas de hora:
```python
for _ in range(2):  # 2 pasadas
    for i in range(len(text_positions) - 1):
        diff = text_positions[i+1]['text_y'] - text_positions[i]['text_y']
        if diff < 3.5:  # nudge si están muy juntas
            nudge = (3.5 - diff) / 2
            ...
```

---

## SPA y estado de navegación

La app es un SPA con un solo `templates/index.html`. La navegación entre tabs reinicia el estado de búsqueda pero no recarga la página.

`window.isProgrammaticNavigation = true` es una bandera que se setea cuando `navegarDesdeModal` simula un click de tab. Evita que el `cambiarTab()` borre el calendario y que el `setTimeout(() => activeInput.focus(), 50)` abra el dropdown del input (comportamiento indeseado en navegación programática).

La bandera se resetea a `false` después de 10ms vía `setTimeout(..., 10)`.

---

## Tema (claro ↔ oscuro)

Un solo eje en `<body>`, persistido en `localStorage`:

| Atributo | Valores | Controla | localStorage |
|---|---|---|---|
| `data-theme` | `blueprint` (default) · `nocturno` | claro / oscuro | `appmitre-theme` |
| `data-dark` | presente / ausente | flag seteado por JS cuando el tema es `nocturno`; agrupa los overrides de superficie | (derivado del tema) |

El acento es **único**: naranja (`--accent: #D97A34` en `:root`, alias `--secondary`). No hay sistema de tonos.

### Los 2 temas

- **Blueprint** (default): estética industrial, grilla blueprint, tabs con clip-path, acento naranja.
- **Nocturno**: modo **oscuro**. Fondos carbón/pizarra, texto claro, esquinas redondeadas, sombras profundas. `--primary` pasa a azul acero claro (legible como texto y como fondo en oscuro).

**Nocturno** es el único con `data-dark`; usa los overrides de superficies claras hardcodeadas vía `body[data-dark] { ... }` (seteado por `applyTheme`). Define sus variables (`--tech-bg`, `--surface`/`--white`, `--primary`, `--border`, `--muted`, `--text`, `--panel`, `--block-bg`). Los tokens `--text` (texto claro), `--panel` (header/inputs) y `--block-bg` (bloques) son exclusivos del tema oscuro. **No se puede sobrescribir `--dark`** en oscuro porque también se usa como fondo (status bar, slide-panel, tooltip, dropdown, reloj); por eso los textos oscuros hardcodeados (`.info-valor`, etc.) se corrigen puntualmente en `body[data-dark]`.

### Flujo (JS en `script.js`)

- `applyTheme(nombre)`: setea `data-theme` (y `data-dark` si es oscuro) en `<body>`, guarda en `localStorage`, y actualiza el ícono/título del botón (`#btn-tema`) — 🌙 luna en claro, ☀ sol en oscuro.
- `toggleTheme()`: alterna blueprint ↔ nocturno; es el `onclick` del botón del header.
- `initTheme()`: lee `localStorage` (default `blueprint`), se llama en `DOMContentLoaded`.
- **Anti-flash**: un script inline al inicio de `<body>` (en `index.html`) aplica el tema guardado antes de pintar el contenido.

### Botón de tema

En el header (`.header-actions`, junto a `#btn-actualizar`): un botón `#btn-tema` (`.tech-btn-tema`) con ícono SVG luna/sol que togglea el tema. Se oculta en modo kiosko (`body.is-fullscreen .header-actions { display:none }`).

### Reglas para no romper el theming

- Usar **siempre** `var(--accent)` (o `var(--secondary)`) para el acento — nunca hex de naranja hardcodeado.
- Para tintes suaves del acento usar `var(--accent-soft)` o `color-mix(in srgb, var(--accent) N%, ...)`.
- Fuente: usar `var(--font-ui)`, no `'Roboto Mono'` literal.
- `data-theme` / `data-dark` y la clase `is-fullscreen` **coexisten** en `<body>` sin conflicto (ejes distintos).
- Para agregar un tema oscuro nuevo: sumarlo a `TEMAS_VALIDOS` en `script.js`, marcarlo como oscuro (`data-dark`) en `applyTheme`, definir sus variables en `body[data-theme="..."]`, y reusar los overrides compartidos de `body[data-dark]`.
- Pendiente conocido: `COMPARACION_COLORS` en `script.js` es una paleta fija de 6 colores.
