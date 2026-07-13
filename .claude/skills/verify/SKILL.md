---
name: verify
description: Receta para verificar cambios de AppMitre en runtime (Flask + SPA vanilla JS). Usar al verificar cambios en app.py, database.py, script.js o templates.
---

# Verificar AppMitre en runtime

## Levantar

```powershell
python app.py   # background; sirve en http://127.0.0.1:5000
```

- Requiere `escuela.db` con datos en el root (si existe, NO descarga de Google Sheets al arrancar).
- ⚠️ Usar `127.0.0.1`, no `localhost` — en Windows `localhost` puede resolver a IPv6 (`::1`) y Flask escucha solo IPv4 → "server no responde" falso.
- El server loguea cada request en stdout — útil como evidencia.

## Superficies y cómo manejarlas

**API (JSON de clases como objetos con claves):**
```powershell
Invoke-RestMethod "http://127.0.0.1:5000/api/dashboard"              # todas las clases
Invoke-RestMethod "http://127.0.0.1:5000/api/curso/1%C2%B0%20A"      # %C2%B0 = °
Invoke-RestMethod "http://127.0.0.1:5000/api/profesor/APELLIDO%20NOMBRE"
Invoke-RestMethod "http://127.0.0.1:5000/api/planilla/Lunes%7CPiso%201"  # %7C = |
```
Para un caso de suplente: filtrar dashboard por `suplente_activo -eq 1`.

**PDF:** descargar y chequear magic bytes `%PDF-`:
`/export/pdf/curso/1%C2%B0%20A`, `/export/pdf/profesor/<con licencia>`, `/export/pdf/planilla/Lunes%7CPiso%201`, `/export/pdf/cursos/todos`.

**Frontend (SPA, render 100% client-side):** Edge headless + hash routing:
```powershell
& "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --headless=new --disable-gpu --no-first-run --virtual-time-budget=10000 --dump-dom "http://127.0.0.1:5000/#/curso/1%C2%B0%20A" > dom.html
```
- `--virtual-time-budget=10000` es clave: espera los fetch iniciales (`cargarDatosIniciales`) y el render.
- Qué buscar en el DOM: `materia-bloque` (bloques de clase; la cantidad debe coincidir con las filas de la API), `personal-cargo-bloque` (personal no docente en vista profesor), `opacity:0.28` (docente en licencia), `class-item-light` (items del dashboard `#/envivo`), `id="calendar-title"`.

## Gotchas

- Los flujos de click (modo comparación, Planilla General, modal) no se llegan con `--dump-dom`; requieren Playwright o prueba manual — reportarlos como no manejados si aplica.
- `/api/actualizar` borra y recarga la DB desde Google Sheets — no dispararlo como parte de una verificación.
- Deprecation warnings de fpdf2 en stdout son preexistentes, no errores.
