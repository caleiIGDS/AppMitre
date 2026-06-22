# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the app (dev server at http://localhost:5000)
python app.py

# Deploy (production)
gunicorn app:app

# Refresh the local DB from Google Sheets (via UI button or direct call)
# POST /api/actualizar
```

There are no tests, no linter config, and no build step — this is a single-process Flask app.

## Architecture

**Data flow:**

```
Google Sheets (CSV export URLs)
  → database.py: cargar_desde_sheets()  (download, clean, normalize)
  → escuela.db (SQLite: clases, preceptores, horarios_preceptores)
  → app.py: /api/<tipo>/<valor>          (query → JSON)
  → static/js/script.js                 (render calendar / dashboard / PDF export)
```

**Key files:**

| File | Role |
|------|------|
| `config.py` | Google Sheets ID + GIDs (one per year level 1ro–7mo, plus preceptores) |
| `database.py` | Table creation, CSV download/parse, data normalization |
| `app.py` | Flask routes: index, `/api/<tipo>/<valor>`, `/export/pdf/...`, `/api/dashboard`, `/api/actualizar` |
| `templates/index.html` | Single-page app shell |
| `static/js/script.js` | All frontend logic (1332 lines) |
| `static/style.css` | Blueprint/industrial theme with CSS variables |

**API routes in `app.py`:**
- `GET /` — main page
- `GET /api/<tipo>/<valor>` — schedule data (tipo: `docente`, `aula`, `curso`)
- `GET /api/preceptor?nombre=...` — preceptor schedule
- `GET /export/pdf/<tipo>/<valor>` — generates and streams a PDF
- `POST /api/actualizar` — re-downloads Google Sheets and rebuilds SQLite
- `GET /api/dashboard` — current + upcoming classes for "En Vivo" view
- `GET /api/horario_preceptor` — preceptor availability data

## Data Normalization (database.py)

Three normalization functions run on every import:
- `limpiar_profesor()` — strips accents, normalizes case, applies manual name-correction mappings
- `limpiar_aula()` — extracts room numbers, detects "Taller" (workshop), handles edge cases like "PATIO"
- `corregir_horarios()` — fills in missing end-times by matching known schedule patterns or defaulting to start+2h

The `superposicion` column (0 or 1) flags genuine scheduling conflicts vs. intentional parallel groups.

## Frontend Calendar Logic (script.js)

- **Clustering**: Groups overlapping time blocks.
- **Superposition handling**: If two classes share a slot, checks group labels (A/B). If different groups → split 50/50 width. If same/no group and `superposicion=1` → side-by-side; if `superposicion=0` → gray warning block.
- **Comparison mode**: Overlays up to 6 schedules with distinct colors.
- **Planilla General**: Floor-plan view using `FLOOR_MAPPING` dict with 5 floor levels.
- **En Vivo dashboard**: Shows current + upcoming (within 2h) classes; supports manual time simulation.
- **Fullscreen/kiosk**: F11 triggers CSS class swap for display-monitor layout.

## PDF Generation (app.py)

Uses `fpdf2`. Key behavior:
- Landscape A4, dynamic font sizing per block width/height.
- Text truncates with ellipsis when it won't fit; intelligently tries shorter substrings.
- Course PDFs optionally embed preceptor info.

## Theme

CSS variables in `static/style.css`: primary navy `#1A365D`, accent orange `#FF6B00`. Blueprint-grid background is a CSS `repeating-linear-gradient`. Font: Roboto Mono (local files in `static/fonts/`).

## Deployment Notes

- Hosting: Render.com (free tier) + Cloudflare DNS. See `PLAN_HOSTING_GRATIS.txt`.
- `escuela.db` is ephemeral on Render (deleted after inactivity). The `/api/actualizar` endpoint or app startup re-fetches from Google Sheets automatically.
- No `.env` file — the Google Sheets ID/GIDs are hardcoded in `config.py`.
