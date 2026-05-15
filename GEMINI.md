# AppMitre - School Schedule Management System

AppMitre is a Flask-based web application designed to manage and display school schedules for professors, classrooms (aulas), and courses (cursos). It features a dynamic weekly calendar view, "Planilla General" for floor-wide overviews, a real-time "En Vivo" dashboard, and PDF export capabilities.

## Project Overview

-   **Backend:** Python 3 with Flask
-   **Database:** SQLite (`escuela.db`) - used as a local cache for normalized data.
-   **Data Source:** Google Sheets (real-time fetch via CSV export URL).
-   **PDF Generation:** `fpdf2`
-   **Frontend:** HTML5, CSS3 (Custom Tech/Blueprint theme), and JavaScript (ES6+).

### Core Components

-   `app.py`: Main entry point. Handles routing, API endpoints for schedule data, and PDF export logic.
-   `database.py`: Manages SQLite database interactions, including table creation and data ingestion from Google Sheets. Includes normalization logic for professor names and classroom identifiers.
-   `templates/`: Contains `index.html`, the main interactive UI.
-   `static/`: Contains static assets like `style.css` and `js/script.js`.

## Technical Features

### Data Synchronization
- Data is pulled from a specific Google Sheet ID and multiple GIDs (representing different sheets/years).
- `database.cargar_desde_sheets` downloads these as CSVs, cleans them, and populates the local `clases` table.

### Dynamic Calendar Logic
- The calendar is rendered on the client side (`script.js`).
- **Clusters:** It groups overlapping classes into "clusters" to calculate positioning.
- **Superposition:** If multiple classes occupy the same slot and are not group-based (A/B), it either splits the column width or shows a "Superposición" warning block based on the `superposicion` flag in the DB.
- **Group A/B:** For courses with technical groups, it splits the block into 50% width columns automatically.

### "En Vivo" Dashboard
- Shows classes "In Progress" and "Upcoming" (within 2 hours).
- **Simulated Time:** Allows users to manually set a date and time to check future/past schedules.

### Planilla General
- A specialized view in the "Aulas" tab that shows all classrooms on a specific floor for a specific day.
- Useful for administrative overviews and physical verification.

## Development Conventions

### Backend
-   **Database Schema:** The `clases` table stores: `curso`, `division`, `especialidad`, `materia`, `tipo_materia`, `profesor`, `dni`, `telefono`, `email`, `aula`, `tipo_aula`, `dia`, `hora_inicio`, `hora_fin`, `grupo`, `superposicion`.
-   **API Endpoints:** 
    -   `/api/<tipo>/<valor>`: Returns JSON data for a specific professor, aula, or course.
    -   `/api/dashboard`: Returns all classes for the dashboard or planilla.
-   **PDF Export:** Uses `FPDF` in `app.py`. It includes complex logic for font scaling and text wrapping within limited block heights.

### Frontend
-   **Modular JS:** Logic resides in `static/js/script.js`.
-   **Styles:** CSS variables in `style.css` manage the color palette and typography.
-   **Full Screen:** Supports F11/fullscreen mode for kiosk-style displays.

### Data Normalization
- `database.py` includes `limpiar_profesor` (accents, formatting, manual mappings) and `limpiar_aula` (extracts numbers). This ensures search consistency.

