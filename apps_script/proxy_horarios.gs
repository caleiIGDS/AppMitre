/**
 * Web App proxy para las planillas privadas de horarios de la Escuela Técnica Emilio Mitre.
 *
 * El Drive de la escuela es privado. La app (database.descargar_sheet) ya no puede pegarle
 * a docs.google.com/.../export?format=csv. En su lugar le pega a este Web App, que corre
 * con los permisos del dueño, lee la planilla privada y devuelve el mismo CSV byte a byte.
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

  var url = 'https://docs.google.com/spreadsheets/d/' + sheetId +
            '/export?format=csv&gid=' + encodeURIComponent(gid);
  var res = UrlFetchApp.fetch(url, {
    headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() },
    muteHttpExceptions: true
  });
  if (res.getResponseCode() !== 200) {
    return _error('sheets respondio ' + res.getResponseCode());
  }

  return ContentService.createTextOutput(res.getContentText())
                       .setMimeType(ContentService.MimeType.CSV);
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
