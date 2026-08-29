# La firma de las peticiones al proxy (HMAC sobre el timestamp)

Cómo y por qué la app le prueba al Web App de Apps Script que la petición es legítima,
sin mandar ningún secreto por la red. Para los pasos de deploy ver
[README.md](README.md); acá está sólo el mecanismo.

---

## El problema

El Drive de la escuela pasa a **privado**. Hasta ahora `database.descargar_sheet()`
bajaba cada planilla pegándole a la URL pública
`https://docs.google.com/spreadsheets/d/<id>/export?format=csv&gid=<gid>`, que exige
que el documento sea "cualquiera con el link puede ver".

La solución es un **Web App de Apps Script** (`proxy_horarios.gs`) que corre con los
permisos del dueño de la planilla, la lee aunque esté privada, y devuelve el mismo CSV
byte a byte. Pero ese Web App se publica con acceso **"cualquier usuario"** (Apps
Script no ofrece autenticación de Google para un endpoint que un script tiene que
poder llamar sin intervención humana). Entonces cualquiera que descubra la URL `/exec`
podría bajarse las planillas.

Hace falta que el proxy distinga una petición de la app de una de un tercero, y que
**el mecanismo no dependa de mandar una clave** que quede escrita en logs, historiales
de URL o capturas de tráfico.

---

## La idea: firmar el momento, no mandar la clave

App y proxy comparten un secreto (`SHEETS_PROXY_SECRET` en el `.env` de la app,
`PROXY_SECRET` como Script Property del proxy — **el mismo valor**). Ese secreto
**nunca viaja**. Lo único que viaja es una firma que sólo se puede generar teniéndolo.

Cada petición lleva tres parámetros en la query string:

| Param | Qué es |
|---|---|
| `t`   | El instante actual en milisegundos: `str(int(time.time() * 1000))` |
| `sig` | `HMAC-SHA256(secreto, t)` en hexadecimal minúsculas |
| `gid` | El GID de la hoja a bajar |

El proxy:

1. Recalcula `HMAC-SHA256(PROXY_SECRET, t)` con **su** copia del secreto y lo compara
   con `sig`. Si no coinciden, la petición no la generó quien tiene el secreto → se
   rechaza.
2. Comprueba que `t` esté **fresco**: `|Date.now() - t| <= 120000` (2 minutos). Una
   URL ya firmada que alguien haya capturado deja de servir a los ~2 minutos.

`HMAC` (no un hash pelado de `secreto + t`) porque es la construcción diseñada para
esto: no es vulnerable a extensión de longitud y su seguridad está demostrada
asumiendo sólo que SHA-256 es una PRF.

---

## Lado app — `database._url_firmada(gid)`

```python
def _url_firmada(gid):
    if not APPSCRIPT_URL or not APPSCRIPT_SECRET:
        raise RuntimeError("Faltan SHEETS_PROXY_URL / SHEETS_PROXY_SECRET: ...")
    ms = str(int(time.time() * 1000))
    sig = hmac.new(APPSCRIPT_SECRET.encode(), ms.encode(), hashlib.sha256).hexdigest()
    return f"{APPSCRIPT_URL}?gid={gid}&t={ms}&sig={sig}"
```

- **Sin config no hay fallback.** Si faltan la URL o el secreto, `RuntimeError` con
  texto claro; no se intenta la URL pública (decisión explícita: mejor que la carga
  falle a que baje datos por un canal que se suponía cerrado). En producción
  `app.py` ni siquiera arranca sin las dos variables.
- **`descargar_sheet` re-firma en cada reintento.** El armado de la URL está *dentro*
  del `for intento`. Si el primer intento tarda y se reintenta 2 s después, el
  segundo lleva un `t` nuevo; si la URL se firmara una sola vez arriba del loop, un
  retry lento podría caer fuera de la ventana de 120 s y fallar por reloj, no por el
  problema real.
- El parámetro `sheet_id` de `descargar_sheet(sheet_id, gid, ...)` **se ignora**: qué
  spreadsheet leer lo sabe el proxy (Script Property `SHEET_ID`). Se dejó en la firma
  para no tocar los tres call sites ni las firmas de los `cargar_*`.

---

## Lado proxy — `proxy_horarios.gs`

```javascript
var VENTANA_MS = 120000;   // fijo en el código, ver más abajo

function doGet(e) {
  var props   = PropertiesService.getScriptProperties();
  var secret  = props.getProperty('PROXY_SECRET');
  var sheetId = props.getProperty('SHEET_ID');
  if (!secret || !sheetId) return _error('proxy sin configurar (faltan Script Properties)');

  var p   = (e && e.parameter) || {};
  var t   = p.t   || '';
  var sig = p.sig || '';
  var gid = p.gid || '';
  var ts  = Number(t);

  if (!t || !sig || !gid || !isFinite(ts) || Math.abs(Date.now() - ts) > VENTANA_MS)
    return _error('parametros invalidos o timestamp fuera de ventana');

  if (!_igualdadConstante(_hmacHex(secret, t), sig))
    return _error('firma invalida');

  var url = 'https://docs.google.com/spreadsheets/d/' + sheetId +
            '/export?format=csv&gid=' + encodeURIComponent(gid);
  var res = UrlFetchApp.fetch(url, {
    headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() },
    muteHttpExceptions: true
  });
  if (res.getResponseCode() !== 200) return _error('sheets respondio ' + res.getResponseCode());

  return ContentService.createTextOutput(res.getContentText())
                       .setMimeType(ContentService.MimeType.CSV);
}
```

Orden de las comprobaciones a propósito: primero lo barato (parámetros presentes,
`t` numérico y fresco), y **recién si pasa eso** se calcula el HMAC. La lectura de la
planilla (`UrlFetchApp.fetch`, que consume cuota) es lo último: una firma inválida
nunca llega a tocar Google.

### La ventana va fija en el código

`VENTANA_MS = 120000` no es una Script Property. Es una **decisión de seguridad, no de
operación**: define cuánto vale una URL capturada. Si fuera configurable, quien
despliega el proxy podría ensancharla a un día sin darse cuenta de que está anulando
la protección anti-replay. 2 minutos alcanza para cualquier reloj razonablemente
sincronizado (los servidores corren NTP) y deja el replay acotado.

### `_hmacHex` — la paridad de bytes con Python

```javascript
function _hmacHex(key, value) {
  var raw = Utilities.computeHmacSha256Signature(value, key);  // bytes CON SIGNO
  var out = '';
  for (var i = 0; i < raw.length; i++) {
    var b = raw[i] < 0 ? raw[i] + 256 : raw[i];   // -1 -> 255
    var h = b.toString(16);
    out += h.length === 1 ? '0' + h : h;          // 'f' -> '0f'
  }
  return out;
}
```

`Utilities.computeHmacSha256Signature` devuelve un array de bytes **con signo**
(`-128..127`), no `0..255`. Sin normalizar, `(-1).toString(16)` da `"-1"` y el hex
sale cualquier cosa. Los dos ajustes — sumar 256 a los negativos y padear a 2
dígitos — son lo que hace que el resultado sea idéntico, carácter por carácter, al
`hmac.new(...).hexdigest()` de Python.

### `_igualdadConstante` — comparación en tiempo ~constante

```javascript
function _igualdadConstante(a, b) {
  if (a.length !== b.length) return false;
  var r = 0;
  for (var i = 0; i < a.length; i++) r |= (a.charCodeAt(i) ^ b.charCodeAt(i));
  return r === 0;
}
```

No corta en la primera diferencia: recorre todo y acumula con XOR. Así el tiempo de
respuesta no filtra *cuántos* caracteres del `sig` acertó un atacante que lo esté
tanteando byte a byte. El chequeo de longitud previo no filtra nada útil: un HMAC-SHA256
en hex siempre mide 64.

---

## Errores: Apps Script siempre responde HTTP 200

`ContentService` no deja setear el status HTTP. **Todo** sale 200, incluido:

- Nuestros rechazos: cuerpo `MITRE_PROXY_ERROR: <motivo>` como texto plano (`_error`).
- Las excepciones no capturadas del propio script (falta de permisos, deploy viejo,
  Sheet inaccesible): Google las devuelve como una **página HTML** con el detalle
  adentro (`Exception: ...`), también con 200.

Como `urllib` ve un 200, no levanta nada. Por eso el lado app tiene
`database._verificar_csv(contenido, ctype, gid)`, que corre **antes** de pasarle nada
a `csv.DictReader`:

- Si el cuerpo empieza con `MITRE_PROXY_ERROR` → `ProxyError` con el motivo.
- Si el `Content-Type` es `text/html` o el cuerpo arranca con `<!doctype` / `<html`
  → extrae el `Exception: ...` de Google y lo mete en un `ProxyError`.

`ProxyError` hereda de `RuntimeError` y **no se reintenta**: firma inválida, sin
permisos o deploy viejo no se arreglan repitiendo la petición. Los tres
`cargar_*` propagan el fallo nombrando la hoja (`"Falló la descarga de la hoja '3ro'
(gid ...): ..."`) en vez de tragárselo con un `print`, y `/api/actualizar` lo
devuelve como `{"status":"error","message": <motivo>}` con HTTP 500.

---

## Qué protege y qué no

**Protege contra:**

- Un tercero que descubre la URL `/exec` y quiere bajarse las planillas: sin el
  secreto no puede generar un `sig` válido.
- Replay de una URL completa capturada (en un log, un historial, tráfico): sirve sólo
  ~2 minutos.
- El secreto quedando en algún registro: nunca se transmite, sólo su HMAC.

**No protege contra** (limitaciones conocidas, asumidas para el valor del dato):

- **El `gid` no está firmado.** `sig` cubre sólo `t`. Con un par `t`+`sig` válido y
  fresco se puede cambiar el `gid` por el de otra hoja del mismo spreadsheet durante
  esos 2 minutos. Hoy da igual (todas las hojas son horarios). Fix si se quiere
  cerrar: firmar `f"{ms}|{gid}"` en los dos lados.
- **Replay dentro de la ventana.** No hay nonce ni uso único: la misma URL firmada
  sirve varias veces mientras `t` siga fresco. Además la ventana es simétrica: acepta
  `t` hasta 2 min en el futuro.
- **Agotamiento de cuota.** El endpoint es anónimo; cualquiera puede dispararle
  `doGet` sin firma válida. No llega a `UrlFetchApp` (bien), pero suma invocaciones y
  tiempo de ejecución contra la cuota diaria de Apps Script. No hay rate-limiting
  posible ahí.
- **El secreto es simétrico, compartido y sin rotación con key-id.** Cambiarlo obliga
  a tocar los dos lados a la vez; no hay período de gracia.
