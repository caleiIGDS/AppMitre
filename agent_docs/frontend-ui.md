# Frontend y UI — AppMitre

> Complementa `CLAUDE.md`. Estilos en `static/style.css`, estructura en `templates/index.html`.

---

## Sistema de variables CSS

```css
:root {
    --primary:    #1A365D;   /* azul marino oscuro */
    --accent:     #D97A34;   /* acento default (ámbar apagado); los tonos lo sobrescriben */
    --alert:      #DC2626;   /* rojo */
    --tech-bg:    #F1F5F9;   /* gris muy claro, fondo general */
    --white:      #ffffff;
    --dark:       #0F172A;   /* casi negro, texto principal */
    --grid-color: rgba(26, 54, 93, 0.08);  /* azul muy transparente para grilla */
    --surface:    #ffffff;   /* superficies (los temas lo sobrescriben) */
    --border:     #cbd5e1;   /* bordes finos */
    --muted:      #70757a;   /* texto secundario */
    --radius:     0px;
    --font-ui:    'Roboto Mono', monospace;  /* fuente global (Swiss la cambia a sans) */
}
body {
    --secondary:  var(--accent);  /* ALIAS legacy: los ~36 usos de var(--secondary) pasan por --accent */
    --accent-soft: color-mix(in srgb, var(--accent) 12%, transparent);
}
```

> **El naranja chillón `#FF6B00` fue reemplazado** por un ámbar apagado (`--accent: #D97A34`,
> tono base "ambar"). Cambiar `--accent` re-skinea los 36+ usos de `var(--secondary)`.
>
> ⚠️ **Gotcha crítico**: `--secondary` y `--accent-soft` se declaran en **`body`, no en `:root`**.
> Un `var()` dentro de una custom property se resuelve en el elemento donde se **declara**. Si
> `--secondary: var(--accent)` viviera en `:root`, se congelaría con el `--accent` de `:root` y
> los tonos (que sobrescriben `--accent` en `body[data-tone]`) NO cambiarían el acento (bug real
> que tuvo el selector). Declararlas en `body` las hace re-resolverse contra el `--accent` del tono.
> Ver la sección **Temas y tonos** al final.

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

**Browser**: Roboto Mono cargada desde Google Fonts (`link` en `<head>` de `index.html`). Pesos: 300, 400, 600, 700.

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

## PDF (`/export/pdf/<tipo>/<valor>`)

### Características técnicas

- Orientación: landscape A4 (297×210mm, área útil ≈267×155mm)
- Fuente: Roboto Mono embedded (Regular, Bold, Italic)
- Sin header (`class PDF(FPDF): def header(self): pass`)
- Footer: "by Calei" en itálica

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

## Temas y tonos

Dos ejes **independientes** en `<body>`, persistidos en `localStorage` (primer uso de localStorage en la app):

| Atributo | Valores | Controla | localStorage |
|---|---|---|---|
| `data-theme` | `blueprint` (default) · `swiss` · `nocturno` · `soft` | layout / tipografía / forma / claro-oscuro | `appmitre-theme` |
| `data-dark` | presente / ausente | flag seteado por JS cuando el tema es oscuro (solo `nocturno`); agrupa los overrides de superficie | (derivado del tema) |
| `data-tone` | `ambar` (default) · `terracota` · `bronce` · `teal` · `marino` · `ciruela` | color de acento (`--accent`) | `appmitre-tone` |

Los **tonos aplican en cualquier tema** (solo cambian `--accent`). Definidos como `body[data-tone="..."] { --accent: ...; }`.

### Los 4 temas

- **Blueprint** (default): la estética industrial original con el acento suavizado.
- **Swiss**: fuente **sans** (`--font-ui` = system-ui/Segoe UI), sin grilla blueprint, tabs de texto con subrayado (sin clip-path), bordes finos (`--border`), sombras suaves, más aire.
- **Nocturno**: modo **oscuro** sofisticado. Fondos carbón/pizarra, texto claro, esquinas redondeadas, sombras profundas. `--primary` pasa a azul acero claro (legible como texto y como fondo en oscuro).
- **Soft**: **"friendly"** claro y cálido. Fondo off-white cálido (sin grilla), fuente sans redondeada (`ui-rounded`/Segoe UI), tabs y botones tipo **píldora** (sin clip-path), tarjetas flotantes con sombras suaves y esquinas bien redondeadas (`--radius: 16px`), bloques del calendario redondeados.

**Tema oscuro (nocturno)**: es el único con `data-dark`; usa los overrides de superficies claras hardcodeadas vía `body[data-dark] { ... }` (seteado por `applyTheme`, pensado para reusarse si se agrega otro tema oscuro). Define sus variables (`--tech-bg`, `--surface`/`--white`, `--primary`, `--border`, `--muted`, `--text`, `--panel`, `--block-bg`). Los tokens `--text` (texto claro), `--panel` (header/inputs) y `--block-bg` (bloques) son exclusivos de temas oscuros. **No se puede sobrescribir `--dark`** en oscuro porque también se usa como fondo (status bar, slide-panel, tooltip, dropdown, reloj); por eso los textos oscuros hardcodeados (`.info-valor`, etc.) se corrigen puntualmente en `body[data-dark]`.

### Flujo (JS en `script.js`)

- `applyTheme(nombre)` / `applyTone(nombre)`: setean el atributo en `<body>`, guardan en `localStorage` y sincronizan el UI del selector.
- `initTheme()`: lee `localStorage` (defaults `blueprint`/`ambar`), se llama en `DOMContentLoaded`.
- **Anti-flash**: un script inline al inicio de `<body>` (en `index.html`) aplica los atributos guardados antes de pintar el contenido.

### Selector

En el header (`.theme-switcher`, junto a `#btn-actualizar`): un `<select#theme-select>` para el tema + swatches circulares `.tone-swatch` para el tono. Se oculta en modo kiosko (`body.is-fullscreen .theme-switcher { display:none }`).

### Reglas para no romper el theming

- Usar **siempre** `var(--accent)` (o `var(--secondary)`) para el acento — nunca hex de naranja hardcodeado.
- Para tintes suaves del acento usar `var(--accent-soft)` o `color-mix(in srgb, var(--accent) N%, ...)`.
- Para agregar un tono: agregar `body[data-tone="nuevo"] { --accent: #...; }`, el `.tone-swatch[data-tone="nuevo"]`, sumar a `TONOS_VALIDOS` en `script.js` y un `<button class="tone-swatch">` en el header.
- Fuente: usar `var(--font-ui)`, no `'Roboto Mono'` literal.
- `data-theme` / `data-dark` y la clase `is-fullscreen` **coexisten** en `<body>` sin conflicto (ejes distintos).
- Para agregar un tema oscuro nuevo: sumarlo a `TEMAS_VALIDOS` **y** `TEMAS_OSCUROS` en `script.js`, definir sus variables en `body[data-theme="..."]`, y reusar los overrides compartidos de `body[data-dark]`.
- Pendiente conocido: `COMPARACION_COLORS` en `script.js` sigue siendo una paleta fija de 6 colores (no sigue el tono).
