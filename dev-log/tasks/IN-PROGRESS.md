# En Progreso

## #26 — PIN temporal para mover ubicaciones
**Desde**: 2026-11-04
**Archivos**: `gestion.py`, `frontend/src/gestion/`, `frontend/src/componentes/PinMovimientos.vue`, ficha de recurso, `app_dist/`.
**Estado**: implementada y compilada sobre el último scroll (`f1f98be`). 10 pruebas Flask/SQLite y 13 comprobaciones de navegador aprobaron: Shift+A, PIN de 4 dígitos (incluido cero inicial), alcance sólo movimientos, vencimiento fijo de 20 segundos, bloqueo, intentos, recarga y aislamiento.
**Próximo paso**: desplegar en PythonAnywhere con `git pull`, fijar `GESTION_PIN_MOVER` en el `.env` y Reload; la pantalla compartida debe usar un acceso de consulta.

<!-- 
Formato para agregar tareas:

## #N — [título]
**Desde**: [fecha]
**Archivos**: [lista de archivos involucrados]
**Estado**: [descripción del avance]
**Próximo paso**: [qué falta]
-->
