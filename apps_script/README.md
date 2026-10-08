# Proxy de horarios (Google Apps Script)

Web App que le sirve a AppMitre el CSV de las planillas de horarios cuando el Drive
de la escuela está en **privado**. Reemplaza el viejo
`https://docs.google.com/spreadsheets/d/<id>/export?format=csv&gid=<gid>` que exigía
el documento público.

`database.descargar_sheet()` le pega con la request firmada; el script valida la firma,
lee la planilla privada con los permisos del dueño y devuelve el mismo CSV.

## Cómo funciona la firma

Cada request lleva tres query params:

| Param | Valor |
|---|---|
| `t`   | timestamp actual en milisegundos (`int(time.time() * 1000)`) |
| `sig` | `HMAC_SHA256(PROXY_SECRET, t)` en hexadecimal |
| `gid` | GID de la hoja a bajar |

El script acepta la request sólo si:

1. Recalcula `HMAC_SHA256(PROXY_SECRET, t)` y coincide con `sig` (comparación en tiempo constante).
2. `|Date.now() - t| <= VENTANA_MS` — 120 000 ms, fijo en `proxy_horarios.gs` (es una
   decisión de seguridad, no una Script Property configurable). Acota el replay: una URL
   capturada deja de servir a los ~2 minutos.

El secreto **nunca viaja** por la red, sólo su HMAC. Cualquier fallo devuelve HTTP 200
con el cuerpo `MITRE_PROXY_ERROR: <motivo>` (Apps Script no deja setear otro status);
la app lo detecta por el prefijo y lanza excepción.

## Deploy

1. **Crear el proyecto**: [script.google.com](https://script.google.com) → Nuevo proyecto.
   Con la cuenta que es **dueña de la planilla de horarios**.
2. Pegar `proxy_horarios.gs` como archivo de código. Si el editor muestra
   `appsscript.json` (Configuración del proyecto → "Mostrar archivo de manifiesto"),
   reemplazarlo por el de esta carpeta.
3. **Servicio avanzado**: en el editor, panel izquierdo → "Servicios" (+) → **Google
   Sheets API** → Agregar (queda como `Sheets`). Esto habilita la API en el proyecto de
   Cloud además de declararla en el manifiesto.
4. **Script Properties** (Configuración del proyecto → Propiedades de la secuencia de comandos):

   | Propiedad | Valor |
   |---|---|
   | `PROXY_SECRET` | el mismo hex que `SHEETS_PROXY_SECRET` del `.env` de la app |
   | `SHEET_ID` | `1GJxwpxXfLosqKxgIa6zyZhwjDK-89ZDavLi6nouWTsw` |

   Generar el secreto: `python -c "import secrets; print(secrets.token_hex(32))"`

5. **Implementar** → Nueva implementación → tipo **Aplicación web**:
   - Ejecutar como: **Yo**
   - Quién tiene acceso: **Cualquier usuario**

   Autorizar el único permiso que pide: *"Ver todas tus hojas de cálculo de Google"*
   (`spreadsheets.readonly`). El script lee vía la API de Sheets — sólo lectura, sin
   Drive ni permiso de escritura/borrado.
6. Copiar la **URL de la aplicación web** (`.../macros/s/AKfy.../exec`) y ponerla en
   `SHEETS_PROXY_URL` (en el `.env`, el local y el del servidor).
7. **Recién ahora** pasar el documento de Google Sheets a privado.

> Al editar `proxy_horarios.gs` hay que crear una **implementación nueva** (o "Administrar
> implementaciones" → editar → Versión: Nueva) para que los cambios tomen efecto en la
> URL `/exec`.

## Variables de entorno de la app

```
SHEETS_PROXY_URL=https://script.google.com/macros/s/AKfy.../exec
SHEETS_PROXY_SECRET=<mismo valor que PROXY_SECRET>
```

En producción (`config.PRODUCCION`) ambas son obligatorias: sin ellas la app no arranca.
En local, si faltan, `descargar_sheet()` lanza un `RuntimeError` explicativo.
