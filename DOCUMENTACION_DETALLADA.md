# Documentación Técnica Detallada - AppMitre

Este documento explica a fondo el funcionamiento interno del sistema AppMitre, desde la ingesta de datos hasta la generación de la interfaz de usuario y documentos PDF.

## 1. Arquitectura General
AppMitre sigue una arquitectura de aplicación web clásica con Flask en el backend y JavaScript Vanilla en el frontend. Utiliza SQLite como una base de datos de paso (caché) para normalizar y servir los datos que provienen de Google Sheets.

## 2. Base de Datos y Flujo de Datos

### Origen de Datos (Google Sheets)
El sistema no requiere una carga manual de archivos. Al iniciar, se conecta a un Google Sheet específico usando su `SHEET_ID` y varios `GIDs` (uno por cada hoja o nivel escolar).
- La URL de exportación es: `https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}`.

### Esquema de la Tabla `clases` (SQLite)
Los datos se almacenan en una única tabla llamada `clases` con las siguientes columnas:
1.  **curso:** Año (ej: 1, 4).
2.  **division:** División (ej: 1, A).
3.  **especialidad:** Orientación técnica.
4.  **materia:** Nombre de la asignatura.
5.  **tipo_materia:** Clasificación (Teórica, TPP, etc.).
6.  **profesor:** Nombre del docente (normalizado).
7.  **dni:** Documento del profesor.
8.  **telefono:** Contacto.
9.  **email:** Contacto.
10. **aula:** Identificador del aula (normalizado).
11. **tipo_aula:** Características del aula.
12. **dia:** Lunes a Viernes.
13. **hora_inicio:** Formato HH:MM.
14. **hora_fin:** Formato HH:MM.
15. **grupo:** Subgrupo (A, B o vacío).
16. **superposicion:** Flag entero (0 o 1) para permitir solapamientos visuales.

### Normalización y Corrección de Datos (`database.py`)
Para que las búsquedas funcionen correctamente a pesar de errores de carga en el Excel original, se aplican funciones críticas:
-   **`limpiar_profesor(nombre)`**: Elimina acentos, pasa a mayúsculas, quita puntos y comas, y aplica un mapeo manual para nombres con múltiples variantes (ej: "CASALE SERVINI" vs "CASALE CERVINI").
-   **`limpiar_aula(aula)`**: Extrae solo los números si el aula es numérica (ej: "B 12" -> "12") o limpia el texto si es una ubicación (ej: "PATIO").
-   **`corregir_horarios(inicio, fin)`**: Detecta casos anómalos donde la hora de inicio y fin son idénticas (un error muy común al cargar el CSV). Utiliza una lista de "horarios comunes" para inferir el fin del bloque, o por defecto suma 2 horas a la hora de inicio, garantizando que el bloque tenga altura y se pueda renderizar visualmente en el calendario.

## 3. Funcionalidades del Frontend (`script.js`)

### Gestión de Tabs y Estado Global
El sistema utiliza un sistema de navegación por pestañas (Cursos, Profesores, Aulas, Tiempo Real). Cada tab reinicia el estado de búsqueda y limpia el contenedor principal antes de mostrar los nuevos resultados. La comunicación entre el servidor y el cliente se realiza a través del objeto `window.APP_DATA`, el cual contiene:
- `rawData`: Listas de autocompletado para los buscadores.
- `floorMapping`: El mapa de aulas por piso (inyectado desde el backend).

### Planilla General (Modo Aeropuerto)
Dentro del tab de Aulas, se puede activar la "Planilla General". Esta vista organiza el calendario con las aulas en las columnas en lugar de los días, permitiendo ver la ocupación total de un piso para un día seleccionado.
- **Fuente Única de Verdad (`FLOOR_MAPPING`)**: El mapeo de aulas a pisos está centralizado en `app.py`. Al cargar la web, este mapa se envía al frontend. Esto garantiza que cualquier cambio en la estructura física de la escuela solo deba modificarse en un solo lugar en el código del servidor.

### Generación del Calendario Dinámico
El calendario se genera mediante la función `generarCalendario`, la cual:
1.  **Calcula el rango horario:** Identifica la hora más temprana y más tardía en los datos recibidos para ajustar el zoom vertical del calendario.
2.  **Agrupamiento por Clusters:** Si dos o más clases se solapan en tiempo dentro del mismo día, se agrupan en un "cluster".
3.  **Lógica de Superposición:**
    -   Si las clases en un cluster pertenecen a grupos diferentes (A/B), se dividen horizontalmente al 50%.
    -   Si son clases conflictivas (mismo grupo o sin grupo), el sistema verifica la columna `superposicion` de la BD.
    -   Si `superposicion == 1`, las divide lado a lado (side-by-side).
    -   Si `superposicion == 0`, muestra un bloque de advertencia gris llamado "⚠️ Superposición".

### Dashboard "En Vivo" (Tiempo Real)
Muestra qué está pasando en la escuela en este preciso momento.
-   **En Curso:** Clases donde `HoraInicio <= HoraActual <= HoraFin`.
-   **Próximas:** Clases que comienzan en las próximas 2 horas.
-   **Modo Manual:** Permite al usuario "viajar en el tiempo" cambiando la fecha y hora simulada para planificar o revisar horarios pasados.

### Interacción y Experiencia de Usuario (UX)
- **Tooltips Dinámicos**: Al posicionar el cursor sobre un bloque horario, un *tooltip* flotante revela rápidamente el resumen de la clase (materia, profesor, aula, horario) sin requerir un click.
- **Modo Quiosco / Pantalla Completa**: El frontend intercepta la tecla `F11` para forzar o salir del modo pantalla completa, lo cual es ideal si el sistema se está proyectando en un televisor pasillo o preceptoría.
- **Normalización de Búsqueda de Cursos**: Cuando un usuario busca un curso (ej. "4° 1°"), el sistema automáticamente limpia el símbolo de grado (`°`) antes de enviar la petición a la API (`/api/curso/4 1`) para evitar errores de codificación y asegurar que la base de datos encuentre el registro.

## 4. Exportación a PDF (`app.py`)

La generación de PDF es una de las partes más complejas del sistema debido a la necesidad de ajustar el texto al espacio disponible.

### Proceso de Generación:
1.  **Cálculo de Grid:** Se dibuja un grid basado en los mismos clusters del frontend.
2.  **Escalado de Fuente Dinámico:** Dependiendo del ancho del bloque (`materia_w`) y su altura (`h`), el sistema ajusta el tamaño de la letra.
3.  **Truncamiento Inteligente:** Si el nombre de la materia es muy largo para el bloque, se divide en múltiples líneas o se añade "..." al final para evitar que el texto se salga del recuadro.
4.  **Exportación a PDF:** Los PDF generados contienen la vista de calendario semanal optimizada. Se ha eliminado la segunda página de detalles para simplificar el documento.

### Casos Especiales en PDF:
-   **Aulas/Planilla:** El indicador lateral del bloque muestra el curso (ej: 4° 1°).
-   **Profesores/Cursos:** El indicador lateral muestra el aula o el curso respectivamente.

## 5. Script de Utilidad (`ordenar.py`)
Aunque el sistema principal usa Google Sheets, existe un script llamado `ordenar.py` que permite procesar un archivo `datos.csv` localmente. Utiliza la librería `difflib.get_close_matches` para detectar materias técnicas y asignarles automáticamente el grupo 'A', facilitando la limpieza de datos antes de subirlos a la nube.
