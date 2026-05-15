# Sistema de Horarios - Escuela Técnica Emilio Mitre

Aplicación web interactiva para la gestión y visualización de horarios escolares de la Escuela Técnica N° 1 "Ing. Emilio Mitre".

## Propósito
Este sistema centraliza la información de horarios para facilitar la consulta dinámica de:
- **Disponibilidad de aulas:** Visualización por aula individual o planilla general por piso.
- **Horarios de profesores:** Cronograma semanal detallado para cada docente.
- **Horarios por curso y división:** Calendario específico para cada grupo de alumnos.

## Características Principales
- **Dashboard "En Vivo":** Visualización en tiempo real de las clases actuales y próximas, con soporte para modo de simulación manual.
- **Planilla General:** Vista tipo "Aeropuerto" para ver el estado de todas las aulas de un piso específico en un día determinado.
- **Calendario Dinámico:** Generación automática de bloques horarios con detección inteligente de superposiciones y divisiones de grupo (A/B).
- **Exportación a PDF:** Generación de documentos PDF optimizados para impresión de cualquier vista (individual o general).
- **Sincronización en la Nube:** Los datos se obtienen directamente de Google Sheets, permitiendo actualizaciones rápidas sin modificar el código.

## Tecnologías Utilizadas
- **Backend:** Flask (Python)
- **Base de Datos:** SQLite (Caché local de datos normalizados)
- **PDF:** FPDF2
- **Frontend:** HTML5, CSS3 (Diseño "Blueprint/Tech"), JavaScript Vanilla (ES6+)

## Instalación y Uso
1. Instalar dependencias:
   ```bash
   pip install -r requirements.txt
   ```
2. Ejecutar la aplicación:
   ```bash
   python app.py
   ```
3. Acceder en el navegador a: `http://localhost:5000`

---
*Desarrollado por Calei*
