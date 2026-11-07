"""Consentimiento y permisos de la conexión de Salidas."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import re

from flask import abort, current_app, redirect, render_template_string, request, session, url_for
from itsdangerous import BadData, URLSafeTimedSerializer

import accesos
from oauth_mcp import OAuthMCP
import salidas

SCOPE = 'salidas:editar'
RUTA_OAUTH = '/salidas/oauth'


def autorizado():
    """Codex puede usar una clave propia de Salidas; los clientes OAuth conservan su flujo."""
    esquema, _, token = request.headers.get('Authorization', '').partition(' ')
    if esquema.lower() == 'bearer' and token.startswith('mitre_salidas_'):
        huella = os.environ.get('SALIDAS_MCP_TOKEN_SHA256', '').strip().lower()
        if not re.fullmatch(r'[0-9a-f]{64}', huella) or not re.fullmatch(r'mitre_salidas_[A-Za-z0-9_-]{43}', token):
            return False
        return hmac.compare_digest(hashlib.sha256(token.encode('ascii')).hexdigest(), huella)
    identidad = oauth.identidad_autorizada()
    if identidad and identidad[0] == 'gestion':
        return _vigente(identidad[1].get('salidas'))
    return identidad is not None


def _generacion():
    return hmac.new(current_app.secret_key.encode(), b'salidas-mcp-oauth-v1', hashlib.sha256).hexdigest()


def _vigente(identidad):
    if not identidad:
        return False
    tipo, valor = identidad
    if tipo == 'gestion':
        import gestion_mcp
        return bool(_vigente(valor.get('salidas')) or any(gestion_mcp.vigente(c) for c in valor['inventarios']))
    if tipo == 'admin':
        return hmac.compare_digest(valor, accesos.huella_clave())
    if tipo == 'salidas':
        clave = salidas._clave_propia()
        return bool(clave and hmac.compare_digest(valor, salidas._huella(clave)))
    if tipo == 'dispositivo':
        fila = accesos._dispositivo(valor)
        return bool(fila and accesos.tiene(json.loads(fila['permisos']), salidas.PERMISO_ESCRITURA))
    return False


def _identidad():
    if not accesos.puede(salidas.PERMISO_ESCRITURA):
        return None
    dato = session.get('acceso') or {}
    candidatos = {
        'admin': dato.get('clave'),
        'dispositivo': dato.get('id'),
    }
    tipo = dato.get('tipo')
    valor = candidatos.get(tipo)
    if valor and _vigente((tipo, valor)):
        return [tipo, valor]
    valor = session.get(salidas.SESION_CLAVE)
    if isinstance(valor, str) and _vigente(('salidas', valor)):
        return ['salidas', valor]
    return None


def _consentir():
    identidad = _identidad()
    if request.form.get('inventarios') == 'autorizar':
        import gestion_mcp
        inventarios = gestion_mcp.concesiones()
        if inventarios:
            return ['gestion', {'salidas': identidad, 'inventarios': inventarios}], None, 200
        return None, 'No hay inventarios accesibles en esta sesión. Abrí tu inventario en Gestión y recargá esta pantalla.', 403
    if identidad is None:
        return None, 'Para conectar Recursos, abrí tu inventario en Gestión y marcá «Autorizar consulta de recursos». Para conectar Salidas, iniciá sesión con permiso de edición de Salidas.', 403
    return identidad, None, 200


def _firma_continuar():
    return URLSafeTimedSerializer(_generacion(), salt='salidas-mcp-continuar')


@salidas.bp.get('/mcp-continuar')
@accesos.requiere(salidas.PERMISO_ESCRITURA)
def mcp_continuar():
    try:
        query = _firma_continuar().loads(request.args.get('solicitud', ''), max_age=600)
    except BadData:
        abort(400)
    return redirect(RUTA_OAUTH + '/authorize?' + query)


def _pantalla(cliente, csrf, error):
    import gestion_mcp
    inventarios = gestion_mcp.concesiones()
    salidas_autorizadas = _identidad() is not None
    autorizado = salidas_autorizadas or bool(inventarios)
    volver = url_for('salidas.mcp_continuar', solicitud=_firma_continuar().dumps(
        request.query_string.decode('ascii')))
    return render_template_string('''<!doctype html><html lang="es"><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>Conectar AppMitre Gestión</title>
        <style>body{font:18px system-ui;max-width:480px;margin:10vh auto;padding:24px;color:#1a365d}
        button{font:inherit;padding:10px;margin:8px 8px 0 0}
        .pasos{padding:18px;background:#eef2f7;border-radius:8px}li{margin:12px 0}</style>
        <h1>Conectar AppMitre Gestión</h1>
        <p><strong>{{ cliente }}</strong> podrá usar tus permisos autorizados de Salidas y consultar los inventarios que autorices.
        La conexión conserva cada acceso mientras siga vigente el permiso correspondiente.</p>
        {% if error %}<p role="alert">{{ error }}</p>{% endif %}
        {% if not autorizado %}
        <div class="pasos">
        <h2>Primero necesitás entrar a AppMitre</h2>
        <p>Compartir este enlace no da acceso a los datos. En este navegador todavía no hay un acceso habilitado para conectar.</p>
        <ol>
        <li>Para Recursos, <a href="/gestion/inventarios" target="_blank" rel="noopener">abrí Gestión en otra pestaña</a>
        y entrá a tu inventario con su clave. Si tenés la clave de administración,
        <a href="/gestion/entrar?volver=/inventarios" target="_blank" rel="noopener">iniciá sesión como administrador</a>.
        Si te invitaron, abrí tu enlace de invitación en este mismo navegador.</li>
        <li>Volvé a esta pestaña y <a href="{{ recargar }}">comprobá tu acceso</a>.</li>
        <li>Marcá la consulta de recursos y tocá Autorizar.</li>
        </ol>
        <p>Si no tenés una clave ni una invitación, pedile acceso al encargado de tu inventario.</p>
        <p>Para Salidas Educativas, <a href="{{ login }}">iniciá sesión en Salidas</a> con permiso de edición.</p>
        </div>
        {% elif not inventarios %}
        <p>Ya podés conectar Salidas. Para sumar Recursos, <a href="/gestion/inventarios" target="_blank" rel="noopener">abrí Gestión y entrá a tu inventario</a>;
        después volvé y <a href="{{ recargar }}">comprobá tu acceso</a>.</p>
        {% endif %}
        <form method="post"><input type="hidden" name="csrf" value="{{ csrf }}">
        {% if inventarios %}<label><input type="checkbox" name="inventarios" value="autorizar" {% if not salidas_autorizadas %}required{% endif %} {% if recursos_marcados %}checked{% endif %}> Autorizar consulta de recursos y todas sus fotos en: {{ nombres_inventarios }}</label>{% endif %}
        {% if inventarios and not salidas_autorizadas %}<p>Marcá la casilla para conectar Recursos. No necesitás permisos de Salidas.</p>{% endif %}
        {% if autorizado %}<button name="decision" value="autorizar">Autorizar</button>{% endif %}
        <button name="decision" value="cancelar" formnovalidate>Cancelar</button></form></html>''',
        cliente=cliente, csrf=csrf, error=error, autorizado=autorizado, inventarios=inventarios,
        salidas_autorizadas=salidas_autorizadas, recursos_marcados=request.form.get('inventarios') == 'autorizar',
        recargar=request.url,
        nombres_inventarios=', '.join(gestion_mcp.gestion.inventario_por_id(c['id'])['nombre'] for c in inventarios),
        login=url_for('salidas.login', next=volver))


oauth = OAuthMCP(
    resource_path='/mcp/gestion', resource_aliases=('/mcp/salidas',),
    issuer_path=RUTA_OAUTH, oauth_path=RUTA_OAUTH, scope=SCOPE,
    nombre='AppMitre Gestión', db_path=lambda: Path(salidas.DB_PATH).with_name('salidas_oauth.db'),
    generacion=_generacion, pantalla=_pantalla, consentir=_consentir, vigente=_vigente,
)
