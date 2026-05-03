# AppMitre - School Schedule Management System

AppMitre is a Flask-based web application designed to manage and display school schedules (clases) for professors, classrooms (aulas), and courses (cursos). It features a dynamic weekly calendar view, PDF export capabilities, and automated data cleaning/preprocessing.

## Project Overview

-   **Backend:** Python 3 with Flask
-   **Database:** SQLite (`escuela.db`)
-   **PDF Generation:** `fpdf2`
-   **Data Processing:** `pandas` (for CSV preprocessing)
-   **Frontend:** HTML5, Vanilla CSS, and JavaScript (ES6+)

### Core Components

-   `app.py`: The main entry point. Handles routing, API endpoints for schedule data, and PDF export logic.
-   `database.py`: Manages SQLite database interactions, including table creation and CSV data ingestion. It includes normalization logic for professor names and classroom identifiers.
-   `ordenar.py`: A utility script that uses `pandas` and fuzzy matching (`get_close_matches`) to automatically assign groups (e.g., 'A' for technical subjects) to classes based on predefined criteria.
-   `datos.csv`: The source of truth for schedule data, which is imported into the SQLite database.
-   `templates/`: Contains HTML templates (`index.html` for the main UI, `pdf_template.html` - though `fpdf2` is used programmatically in `app.py`).
-   `static/`: Contains static assets like CSS (`style.css`), JavaScript (`js/script.js`), and images.

## Getting Started

### Prerequisites

-   Python 3.x
-   Pip (Python package manager)

### Installation

1.  Install the required dependencies:
    ```bash
    pip install -r requirements.txt
    ```

### Running the Application

1.  Execute the main application script:
    ```bash
    python app.py
    ```
    The application will automatically:
    -   Create/reset the SQLite tables.
    -   Load data from `datos.csv` into `escuela.db`.
    -   Start the Flask development server at `http://localhost:5000`.

### Data Preprocessing

If you need to update the group assignments in your CSV before running the app:
```bash
python ordenar.py
```
This script reads `datos.csv` and outputs `horarios_actualizados.csv` with assigned groups for technical subjects.

## Development Conventions

### Backend
-   **Database Schema:** The `clases` table stores all schedule information. New columns should be added to both `crear_tablas` and `cargar_csv` in `database.py`.
-   **API Endpoints:** `/api/<tipo>/<valor>` returns JSON data for the frontend calendar.
-   **PDF Export:** Located in `app.py`, use the `FPDF` class to customize the exported schedule's layout and style.

### Frontend
-   **Separation of Concerns:** JavaScript logic is separated from HTML templates. Logic resides in `static/js/script.js`, while `index.html` only contains a minimal initialization script to pass data via `window.APP_DATA`.
-   **Dynamic Calendar:** The calendar in `index.html` is generated on the fly via JavaScript in `script.js`. It calculates overlaps and positions blocks based on start/end times.
-   **Styling:** Follow the CSS variables defined in `:root` in `style.css` to maintain visual consistency (Google/Material-inspired aesthetic).
-   **Modals:** Used for displaying detailed class information and handling overlaps.

### Data Normalization
-   `database.py` contains `limpiar_profesor` and `limpiar_aula` functions. These are critical for ensuring that searches work correctly despite variations in the input CSV data (e.g., "J.PABLO" vs "J PABLO").

## Key Files Summary

| File | Purpose |
| :--- | :--- |
| `app.py` | Main Flask app, routing, and PDF generation. |
| `database.py` | SQLite DB management and CSV import logic. |
| `ordenar.py` | Data cleaning and technical group assignment script. |
| `requirements.txt` | Project dependencies. |
| `datos.csv` | Input data for schedules. |
| `static/style.css` | UI styling. |
| `static/js/script.js` | Main frontend logic (calendar generation, search, etc.). |
| `templates/index.html` | Main interactive user interface. |
