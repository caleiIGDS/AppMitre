# Motor de Calendario — AppMitre

> Complementa `CLAUDE.md`. Las reglas viven hoy en `frontend/horarios/src/calendario.js`
> (`aMinutos`, `rango`, `bloquesColumna`, `estilosBloques`) y el dibujo en
> `componentes/Calendario.vue` / `CalendarioComparacion.vue`. Hasta el 2026-10-05 estaban en
> `static/js/script.js` (borrado con la página clásica): los nombres de función de abajo son
> los de ese archivo, pero las reglas se portaron tal cual.

---

## Estructura del grid CSS

```css
.calendario-grid {
    display: grid;
    grid-template-columns: 60px repeat(5, 1fr);
}
```

- Primera columna (60px fija): etiquetas de hora (`.columna-horas`)
- Columnas 2–6: uno por día de la semana (`.columna-dia`)
- Cabecera (fila 1): `.cabecera-vacia` + 5 × `.cabecera-dia` con el nombre del día
- Los bloques de clase usan `position: absolute` dentro de su `.columna-dia`

### Cálculo de posición vertical

Todos los tiempos se convierten a minutos desde medianoche con `timeToMin(t)`.

```js
const HORA_MIN = Math.max(0, min de todos los horarios - 30)
const HORA_MAX = Math.min(1440, max de todos los horarios + 30)
const ALTURA_TOTAL = Math.max((HORA_MAX - HORA_MIN) * 1.05, 450)

getPosicionY(horaStr) = ((timeToMin(horaStr) - HORA_MIN) / (HORA_MAX - HORA_MIN)) * ALTURA_TOTAL
```

El grid es dinámico: solo muestra el rango horario real de los datos, con 30 minutos de padding arriba y abajo, y altura mínima de 450px. El factor `1.05` agrega un 5% extra para que el último bloque no quede pegado al borde.

Los bloques se posicionan con:
- `top = getPosicionY(hora_inicio) + 2` (2px de margin visual)
- `height = Math.max(getPosicionY(hora_fin) - 2 - top, 20)` (mínimo 20px para clases muy cortas)

---

## Algoritmo de clustering

El clustering detecta clases que se solapan en el tiempo para renderizarlas juntas.

```
Para cada columna-día:
  1. Ordenar clases del día por hora_inicio (ascendente)
  2. Greedy scan:
     - Tomar clase[i] como semilla del cluster
     - maxFin = hora_fin de clase[i]
     - Para j = i+1, i+2, ...:
         si hora_inicio[j] < maxFin → agregar al cluster, actualizar maxFin
         si no → break (las clases están ordenadas, no habrá más solapamientos)
  3. Marcar todos los índices del cluster como procesados
  4. Decidir cómo renderizar el cluster (ver abajo)
```

**Limitación conocida**: el `break` asume que al encontrar la primera clase que no solapa, ninguna posterior solapa tampoco. Esto es verdadero si las clases están ordenadas y el algoritmo rastrea el `maxFin` correcto (lo hace). En la práctica es correcto para los datos del Mitre.

### Filtrado de licenciadas en el cluster

Antes de procesar, se filtra el cluster:
```js
const sinLicenciadas = cluster.filter(c => c[16] != 1)
const clusterFinal = (cluster.length > 1 && sinLicenciadas.length > 0)
    ? sinLicenciadas
    : cluster
```

Si hay más de una clase y al menos una no es licenciada, se descarta la(s) licenciada(s) del cluster. Esto evita renderizar el bloque "LICENCIADA" en el mismo espacio que el suplente que la reemplaza.

---

## Decisión de renderizado por cluster

Un cluster de N clases puede renderizarse de tres maneras según `haySuperposicion`:

### ¿Cuándo hay superposición?

```js
const todosTienenGrupo = clusterFinal.every(c => c[14] && c[14].trim() !== "")
const haySuperposicion = clusterFinal.length > 1
    && (modo === 'aula' || modo === 'profesor' || !todosTienenGrupo)
```

- **Si todos los elementos del cluster tienen grupo (A o B)** en vista de curso → no hay superposición; son grupos paralelos esperados → se dividen lado a lado normalmente.
- **Si hay solapamiento en vista de aula o profesor** → siempre hay superposición (no se espera que dos cursos distintos estén en la misma aula al mismo tiempo, salvo `superposicion=1`).

### Caso 1: Cluster sin superposición (grupos A/B en vista de curso)

`calcularEstilosBloques(cluster)` asigna `left`/`width` a cada bloque:
- Para N ≤ 2: respeta el campo `grupo` (A → izquierda, B → derecha). Si no hay grupo explícito, llena de izquierda a derecha.
- Para N > 2: divide equitativamente el 100% del ancho entre N bloques.

### Caso 2: Cluster con superposición — todos permiten (`superposicion=1`)

Todos los elementos del cluster tienen `f[15] == 1`. Se renderizan lado a lado igual que el caso sin superposición, usando `calcularEstilosBloques`.

### Caso 3: Cluster con superposición — al menos uno no permite (`superposicion=0`)

Se renderiza un único bloque rojo `.bloque-superposicion`:
```html
<div class="bloque-superposicion" style="top:...px; height:...px;">
    ⚠️ Superposición (N)
</div>
```
Click en este bloque llama `verDetalleSuperposicion()` que abre un modal con los detalles de todas las clases en conflicto.

---

## Modo Comparación (`generarCalendarioComparacion`)

### Estructura del grid extendido

```js
const gridCols = `60px repeat(${N * 5}, ${COL_WIDTH}px)`
// N = cantidad de entidades, 5 días, COL_WIDTH = 200px por columna
```

El grid es horizontalmente scrollable (`.comparacion-scroll-wrapper`). Para N entidades y 5 días: `60 + N×5×200` px de ancho mínimo.

### Encabezados en 2 filas

- Fila 1: celda vacía + 5 `cabecera-dia-grupo` (cada una con `grid-column: span N`)
- Fila 2: placeholder + N×5 `cabecera-entidad` con punto de color y nombre de entidad

### Colores

```js
const COMPARACION_COLORS = ['#1a3a5c','#c0392b','#27ae60','#8e44ad','#e67e22','#16a085']
```

Se asignan en orden de entrada. Si hay más de 6 entidades, los colores se ciclan (`% COMPARACION_COLORS.length`). No hay límite hard de 6 — es solo cuántos colores distintos hay definidos.

### Estado global de comparación

```js
let isComparacionMode = false
let comparacionItems = []   // [{modo, valor, filas, color, label}]
let lastFilas = null        // filas de la última búsqueda fuera de comparación
```

Cuando se activa la comparación, la búsqueda actual se convierte en el primer item. Las búsquedas siguientes se agregan a `comparacionItems` en lugar de reemplazar la vista.

Los preceptores no se pueden agregar a comparación (verificado en `buscarEnServidor`).

---

## Dashboard En Vivo (`renderizarDashboard`)

### Filtrado por hora

```js
// "En Curso": clases donde inicio ≤ ahora ≤ fin
if (currentTime >= start && currentTime <= end) → inProgress

// "Próximas": clases que empiezan en los próximos HORAS_PROXIMAS (= 2h)
if (currentTime < start && start < currentTime + 120) → upcoming
```

Los datos vienen de `/api/dashboard` que devuelve TODAS las clases. El filtro por día y hora ocurre 100% en el cliente.

### Refresh

`iniciarDashboard()` llama `setInterval(fn, 1000)`. Cada segundo:
1. Actualiza el reloj en pantalla.
2. Si el tab En Vivo está visible y no está en modo manual → repinta con `renderizarDashboard(lastDashboardData)`, **desde memoria**.
3. Sólo si pasaron `REFRESCO_DATOS_MS` (10 min) desde la última descarga, llama `refrescarDatosDashboard()`, que tira `_datosPromise` y vuelve a bajar los tres endpoints del bootstrap.

El intervalo **no pega al servidor**. Lo que cambia cada segundo es la hora, no el horario: éste sólo se mueve cuando alguien reimporta desde Sheets, y para eso alcanza con mirar cada 10 minutos. Antes acá había un `fetch('/api/dashboard')` por segundo — 2.299 filas que tardaban ~0.9 s en responder, o sea más que el propio intervalo: los pedidos se encolaban y saturaban el único worker del hosting, frenando la navegación del resto de la app.

**Caché**: `lastDashboardData` guarda las filas vigentes (las pone `cargarDatosIniciales()`). `renderizarDashboard(filas)` se llama siempre contra esa caché, tanto para el tick del reloj como para refiltrar cuando el usuario escribe en el campo de filtro.

### Modo manual

El checkbox "MODO MANUAL" (en el slide panel del tab En Vivo) habilita los date/time pickers. Mientras está activo:
- El reloj no avanza (muestra `manualTime + ":00"` estático).
- La carga de datos no se dispara automáticamente — solo cuando el usuario cambia la fecha/hora.
- Permite simular el dashboard en cualquier momento/día para testing.

### Modo kiosco (F11)

`document.documentElement.requestFullscreen()` → dispara `fullscreenchange` event → el listener agrega/quita la clase `is-fullscreen` en `body`.

Efectos de `is-fullscreen`:
- Oculta: `.tech-header`, `footer`, `.tech-tags`, `#tab-profesor`, `#tab-aula`, `#tab-curso`
- `.dashboard-grid-light` pasa a `grid-template-columns: 1fr` (columna única)
- `.dashboard-column-light.upcoming` se oculta (solo muestra "En Curso")
- En pantallas anchas (>900px), `.class-list-light` pasa a grid de 2 columnas
- `.tech-container` pasa a `height: 100vh; display: flex; flex-direction: column`

---

## Planilla General (`generarPlanillaGeneral`)

### Diferencia con el calendario estándar

| Calendario estándar | Planilla General |
|---|---|
| Columnas = días de la semana | Columnas = aulas del piso seleccionado |
| Filas = horas | Filas = horas |
| Un día fijo como contexto del tab | Día seleccionable con botones |

### Fuente de datos

`allDataCache` — lo llena `cargarDatosIniciales()` en el bootstrap (todas las clases). Es el mismo array que `lastDashboardData`, no una segunda copia. Se renueva solo cada 10 min mientras el tab En Vivo está abierto (ver *Refresh*); en el resto de la app, si alguien actualiza la DB hay que hacer F5.

Las aulas del piso vienen de `window.APP_DATA.floorMapping[selectedFloor]` (lista de strings como `["11","12","13","14","15","16"]`). El filtro de filas es `f[9]` (campo `aula` del row).

### Clustering en planilla

Idéntico al del calendario estándar pero `haySuperposicion`:
```js
const haySuperposicion = clusterFinal.length > 1 && !todosTienenGrupo
```
(No chequea `modo === 'aula'` porque en planilla siempre estamos viendo por aula.)

Los bloques en planilla muestran `clase[0]° clase[1]` (curso y división) en lugar de materia/profesor.

---

## `calcularEstilosBloques(cluster)` — detalle

Para N = 1 o 2:
- Busca grupos A/B explícitos en `cluster[i][14]`.
- Grupo A → `left: 4px; width: calc(50% - 6px)` (mitad izquierda)
- Grupo B → `right: 4px; width: calc(50% - 6px)` (mitad derecha)
- Sin grupo o N=1 → full width (`left:4px; right:4px`)

Para N > 2:
- División equitativa: cada bloque ocupa `100/N %` del ancho, posicionado con `left: calc((100/N * idx)% + 4px)`.
