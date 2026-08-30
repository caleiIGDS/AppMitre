/**
 * Web App proxy para las planillas privadas de horarios de la Escuela Técnica Emilio Mitre.
 *
 * El Drive de la escuela es privado. La app (database.descargar_sheet) ya no puede pegarle
 * a docs.google.com/.../export?format=csv. En su lugar le pega a este Web App, que corre
 * con los permisos del dueño, lee la planilla con el Servicio Avanzado de Sheets (API v4,
 * scope spreadsheets.readonly: sólo lectura, sin Drive ni permiso de escritura) y arma el
 * mismo CSV.
 *
 * Seguridad: cada request trae ?t=<timestamp_ms>&sig=<hex>&gid=<gid>. `sig` es
 * HMAC-SHA256(PROXY_SECRET, t) en hexadecimal. Se acepta sólo si la firma recalculada
 * coincide y si |Date.now() - t| <= VENTANA_MS, la ventana fija de más abajo (acota el
 * replay de una URL capturada).
 *
 * Deploy y Script Properties: ver apps_script/README.md.
 */

/**
 * Ventana de aceptación del timestamp, en ms. Es una decisión de seguridad, no de
 * operación: acota cuánto vale una URL capturada. Va fija en el código a propósito —
 * quien despliega el proxy no debería poder ensancharla desde una Script Property.
 */
var VENTANA_MS = 120000;

function doGet(e) {
  var props = PropertiesService.getScriptProperties();
  var secret = props.getProperty('PROXY_SECRET');
  var sheetId = props.getProperty('SHEET_ID');

  if (!secret || !sheetId) {
    return _error('proxy sin configurar (faltan Script Properties)');
  }

  var p = (e && e.parameter) || {};
  var t = p.t || '';
  var sig = p.sig || '';
  var gid = p.gid || '';
  var ts = Number(t);

  if (!t || !sig || !gid || !isFinite(ts) || Math.abs(Date.now() - ts) > VENTANA_MS) {
    return _error('parametros invalidos o timestamp fuera de ventana');
  }

  if (!_igualdadConstante(_hmacHex(secret, t), sig)) {
    return _error('firma invalida');
  }

  var titulo = null;
  try {
    var meta = Sheets.Spreadsheets.get(sheetId, { fields: 'sheets.properties(sheetId,title)' });
    var hojas = meta.sheets || [];
    for (var i = 0; i < hojas.length; i++) {
      if (String(hojas[i].properties.sheetId) === String(gid)) {
        titulo = hojas[i].properties.title;
        break;
      }
    }
  } catch (err) {
    return _error('no se pudo leer la planilla: ' + err);
  }
  if (!titulo) {
    return _error('gid inexistente en la planilla: ' + gid);
  }

  var resp = Sheets.Spreadsheets.Values.get(sheetId, "'" + titulo.replace(/'/g, "''") + "'", {
    valueRenderOption: 'FORMATTED_VALUE',
    dateTimeRenderOption: 'FORMATTED_STRING'
  });
  return ContentService.createTextOutput(_aCsv(resp.values || []))
                       .setMimeType(ContentService.MimeType.CSV);
}

/**
 * Matriz de valores -> CSV con el mismo entrecomillado y ancho que el export de Google:
 * toda fila se rellena hasta el ancho máximo (la API recorta las celdas vacías del
 * final, el export no), y se envuelve en comillas dobles la celda que tenga coma,
 * comilla o salto de línea, con las comillas internas duplicadas. Filas separadas por CRLF.
 */
function _aCsv(filas) {
  var ancho = 0;
  for (var i = 0; i < filas.length; i++) {
    if (filas[i].length > ancho) ancho = filas[i].length;
  }
  return filas.map(function (fila) {
    var celdas = [];
    for (var j = 0; j < ancho; j++) {
      var s = fila[j] == null ? '' : String(fila[j]);
      celdas.push(/[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s);
    }
    return celdas.join(',');
  }).join('\r\n');
}

/** HMAC-SHA256(key, value) en hex, con los bytes normalizados a 0..255. */
function _hmacHex(key, value) {
  var raw = Utilities.computeHmacSha256Signature(value, key);
  var out = '';
  for (var i = 0; i < raw.length; i++) {
    var b = raw[i] < 0 ? raw[i] + 256 : raw[i];
    var h = b.toString(16);
    out += h.length === 1 ? '0' + h : h;
  }
  return out;
}

/** Comparación en tiempo ~constante de dos strings hex. */
function _igualdadConstante(a, b) {
  if (a.length !== b.length) return false;
  var r = 0;
  for (var i = 0; i < a.length; i++) {
    r |= (a.charCodeAt(i) ^ b.charCodeAt(i));
  }
  return r === 0;
}

/**
 * Apps Script no deja setear el status HTTP desde ContentService, así que los errores
 * salen 200 con este sentinel en el cuerpo. database.descargar_sheet lo detecta por el
 * prefijo y lanza una excepción.
 */
function _error(motivo) {
  return ContentService.createTextOutput('MITRE_PROXY_ERROR: ' + motivo)
                       .setMimeType(ContentService.MimeType.TEXT);
}
