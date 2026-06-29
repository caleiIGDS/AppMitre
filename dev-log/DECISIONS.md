# Decisiones de Arquitectura — AppMitre

Leer este archivo antes de "corregir" algo que parece raro. Muchas decisiones tienen contexto específico de la escuela o del despliegue.

---

## [fecha desconocida] — Vanilla JS sin framework

**Contexto**: App de consulta de horarios para una escuela técnica. El desarrollador es solo uno. La app no tiene proceso de build.

**Decisión**: Vanilla JS + HTML directo. Sin React, Vue, Angular ni ningún framework.

**Alternativa descartada**: Cualquier framework SPA moderno. Requeriría `npm`, un build step, y un ciclo de desarrollo más lento.

**Consecuencia**: `script.js` ha crecido a ~1600 líneas con duplicación de lógica de rendering entre `generarCalendario`, `generarCalendarioComparacion` y `generarPlanillaGeneral`. La deuda es conocida y documentada en `PLAN_ESCUELAS.md` como E3.

---

## [fecha desconocida] — SQLite efímero en lugar de PostgreSQL persistente

**Contexto**: Render.com (free tier) borra el filesystem entre restarts. Render ofrece PostgreSQL gratuito como add-on, pero tiene límites de conexiones y agrega complejidad de setup.

**Decisión**: SQLite como caché efímero de los datos de Google Sheets. La DB se regenera automáticamente desde Sheets en cada arranque en frío.

**Alternativa descartada**: PostgreSQL en Render. Requiere gestionar cadenas de conexión, migraciones, y hace la app dependiente de un servicio adicional.

**Consecuencia**: Datos siempre frescos (se re-descargan de Sheets). Sin persistencia de ningún estado. El primer usuario tras un período de inactividad espera 30–50s mientras la app "despierta" y recarga la DB. Ver `dev-log/tasks/TODO.md` #1 — el mecanismo de auto-inicialización bajo gunicorn está pendiente.

---

## [fecha desconocida] — `window.APP_DATA` cargado en el page load

**Contexto**: El autocompletado necesita filtrar ~200–300 nombres de docentes con cada keystroke.

**Decisión**: Todo el catálogo (profesores, aulas, cursos, preceptores, personal) se serializa en el HTML inicial como `window.APP_DATA.rawData`.

**Alternativa descartada**: Endpoint de autocompletado con debounce. Introduciría latencia perceptible especialmente con Render free tier (que puede tardar en responder).

**Consecuencia**: El HTML inicial es algo más pesado (~50–100KB extra). Búsquedas instantáneas sin round-trip al servidor. Si la DB tiene miles de docentes (en otro contexto), esto escalaría mal.

---

## [fecha desconocida] — `nombre_mapeos.json` manual en lugar de fuzzy matching

**Contexto**: Los nombres de profesores en el Google Sheet tienen errores tipográficos inconsistentes entre hojas (ej: "CASALE SERVIN BETTINA" vs "CASALE SERVINI BETTINA" vs "CASALE CERVINI BETINA").

**Decisión**: Archivo JSON de mapeos manuales que el desarrollador mantiene.

**Alternativa descartada**: Fuzzy matching automático (ej: Levenshtein). Los falsos positivos son inaceptables — asignar el horario de un docente a otro silenciosamente sería un bug crítico invisible.

**Consecuencia**: Requiere intervención manual cuando aparece un nuevo typo. El archivo se carga una vez al iniciar; agregar un mapeo sin reiniciar no tiene efecto inmediato.

---

## [fecha desconocida] — Acceso a filas de DB por índice numérico en el frontend

**Contexto**: La API devuelve `SELECT *` y el JS accede como `f[0]`, `f[5]`, `f[9]`, etc.

**Decisión**: [inferido] Fue una decisión de velocidad de desarrollo inicial que nunca se refactorizó.

**Alternativa descartada**: La API debería devolver objetos con claves nombradas.

**Consecuencia**: Cambiar el orden de columnas en la tabla rompería todo el frontend silenciosamente. Documentado como E3 en `PLAN_ESCUELAS.md` y como TODO #3 en el backlog.

---

## [fecha desconocida] — Layout de preceptores con bloques de columnas por offset

**Contexto**: El Google Sheet de preceptores tiene 3 "tablas" yuxtapuestas horizontalmente (MAÑANA, TARDE, VESPERTINO) en lugar de una tabla única con columna de turno.

**Decisión**: `cargar_horarios_preceptores()` asume offsets fijos: MAÑANA en columna 0, TARDE en columna 9, VESPERTINO en columna 18 (8 cols de datos + 1 col separadora vacía = paso de 9). La primera fila se ignora con `next(reader, None)`.

**Alternativa descartada**: Reestructurar el sheet. El sheet ya existe con datos y no se quiere modificar la planilla original de la escuela.

**Consecuencia**: El parser es muy frágil. Si la escuela agrega o mueve columnas en el sheet de preceptores, los datos se corrompen. Documentado como E4 en `PLAN_ESCUELAS.md`.

---

## [fecha desconocida] — `corregir_horarios()` eliminada

**Contexto**: Existía una función que intentaba inferir la `hora_fin` cuando `hora_inicio == hora_fin` en el sheet (error de carga). Usaba una lista hardcodeada de horarios comunes del Mitre.

**Decisión**: La función fue eliminada. La planilla debe tener datos correctos. Si hay una clase con `hora_inicio == hora_fin`, se carga tal cual y el frontend la renderiza como bloque de 0 altura.

**Alternativa descartada**: Mantener la corrección automática.

**Consecuencia**: Los datos deben estar bien en el sheet desde el origen. Errores en el sheet son visibles en la UI (bloques raros o ausentes) en lugar de silenciosos.

---

## [fecha desconocida] — `/api/actualizar` como GET en lugar de POST

**Contexto**: [inferido] Decisión de simplicidad. Los formularios HTML y los `fetch()` simples usan GET por default.

**Decisión**: La ruta que borra y recarga la DB completa es un GET.

**Alternativa descartada**: POST con CSRF protection.

**Consecuencia**: Cualquiera que conozca la URL puede triggear una recarga de la DB. No hay autenticación. En producción (Render), el Sheet es público de todas formas, así que el riesgo es bajo — lo peor que puede pasar es un re-download innecesario.

---

## [fecha desconocida] — `allDataCache` para la Planilla General sin invalidación

**Contexto**: La Planilla General necesita todas las clases de un piso para un día. Hacer un request a `/api/dashboard` por cada cambio de día o piso sería ineficiente.

**Decisión**: Los datos se cachean en `allDataCache` después del primer fetch y no se vuelven a cargar en la sesión.

**Alternativa descartada**: Refetch en cada cambio de selector.

**Consecuencia**: Si el usuario actualiza la DB (botón ACTUALIZAR HORARIOS) mientras tiene la planilla abierta, el caché queda obsoleto. Requiere F5 para ver los datos nuevos. Es un trade-off aceptado.

---

## [2026-06-25] — PythonAnywhere como hosting

**Contexto**: Necesidad de hosting gratuito con dominio personalizado y HTTPS para la escuela.

**Decisión**: PythonAnywhere (Flask/WSGI). La DB (`escuela.db`) persiste en el filesystem entre reinicios, a diferencia de Render donde era efímera.

**Alternativa descartada**: Render.com. Render borraba el filesystem entre cold starts, lo que requería re-descargar toda la DB desde Sheets cada vez que el servicio "despertaba".

**Consecuencia**: El bloque `if __name__ == '__main__'` en `app.py` no se ejecuta bajo WSGI — la inicialización de la DB debe hacerse manualmente (consola de PythonAnywhere o via `/api/actualizar`) en un deploy nuevo. Ver TODO #1.

---

## [2026-06-29] — Búsqueda client-side desde caché en memoria + hash routing

**Contexto**: Cada búsqueda (profesor/aula/curso/planilla) hacía un request al server. El dataset completo es chico (`/api/dashboard` = ~2.300 filas × 20 cols, más ~pocos cientos de filas de personal). En Render/PythonAnywhere free tier, los round-trips agregan latencia perceptible.

**Decisión**: Descargar todo a memoria una sola vez al cargar la web (`cargarDatosIniciales()` → `_allClases` / `_allPersonal`) y resolver las búsquedas client-side con `filtrarClasesLocal()`, que **replica exactamente** la lógica de `obtener_filas()` de `app.py`. Se mantiene fallback a los endpoints `/api/*` si los datos aún no cargaron. En paralelo se agregó hash routing (`#/profesor/...`) para URLs compartibles.

**Alternativa descartada**:
- *Service Worker / offline real (PWA)*: descartado por complejidad (sincronización, invalidación) — el usuario eligió explícitamente "session cache". Si se refresca la página se necesita red de nuevo; suficiente para un kiosco siempre encendido.
- *Clean URLs (`/profesor/...`) con catch-all en Flask*: descartado para no tocar el backend ni agregar superficie de routing server-side. El hash no requiere cambios en Flask.

**Consecuencia**:
- Hay **dos fuentes de verdad** para la lógica de filtrado: `obtener_filas()` (Python) y `filtrarClasesLocal()` (JS). Si una cambia, la otra debe seguirla, o el fallback de red devolverá resultados distintos a la caché.
- El caché no se invalida tras `/api/actualizar` sin un F5 (mismo trade-off ya aceptado para `allDataCache`).
- `horario_preceptor` y `preceptor` siguen yendo al server (tabla distinta); `horario_preceptor` se excluyó del hash routing para evitar una race en `contenedor-lista`.

---

## [fecha desconocida] — `personalToFila()` para fusionar personal con clases

**Contexto**: En la vista de profesor, se quieren mostrar los turnos del personal no docente (porteros, secretarias) junto con los horarios de clases en el mismo calendario.

**Decisión**: `personalToFila()` convierte el objeto `{nombre, rol, dia, hora_inicio, hora_fin}` en un array de 21 elementos que imita el formato de una fila de la tabla `clases`, con `row[20] = 'personal'` como marker de tipo.

**Alternativa descartada**: Cambiar la API para devolver objetos con claves nombradas (E3 en `PLAN_ESCUELAS.md`), que haría innecesario este workaround.

**Consecuencia**: El workaround funciona pero es frágil — si la tabla `clases` agrega columnas, el índice 20 de `personalToFila` puede colisionar.
