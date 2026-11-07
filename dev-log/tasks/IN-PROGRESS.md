# En Progreso

## #26 — PIN temporal para mover ubicaciones
**Desde**: 2026-11-04
**Archivos**: `gestion.py`, `frontend/src/gestion/`, `frontend/src/componentes/PinMovimientos.vue`, ficha de recurso, `app_dist/`.
**Estado**: implementada y compilada sobre el último scroll (`f1f98be`). 10 pruebas Flask/SQLite y 13 comprobaciones de navegador aprobaron: Shift+A, PIN de 4 dígitos (incluido cero inicial), alcance sólo movimientos, vencimiento fijo de 20 segundos, bloqueo, intentos, recarga y aislamiento.
**Próximo paso**: desplegar en PythonAnywhere con `git pull`, fijar `GESTION_PIN_MOVER` en el `.env` y Reload; la pantalla compartida debe usar un acceso de consulta.

## Simplificación de accesos MCP

OAuth reemplazado por tres tokens Bearer: Horarios, Gestión consulta sin ubicaciones y Gestión administración. Se retiraron la clave exclusiva de Salidas y el relleno por código de pestaña. No cambia el padrón local ni los legajos guardados.
Pendiente: configurar los tres tokens en el `.env` de PythonAnywhere y desplegar; después actualizar los plugins existentes con los paquetes 2.0.0 y verificar desde el cliente. El ID guardado de Gestión no se encontró en la cuenta; no crear un duplicado sin resolverlo.

<!-- 
Formato para agregar tareas:

## #N — [título]
**Desde**: [fecha]
**Archivos**: [lista de archivos involucrados]
**Estado**: [descripción del avance]
**Próximo paso**: [qué falta]
-->
