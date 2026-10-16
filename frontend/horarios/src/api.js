// Cliente de la API de horarios (/app-horarios/api, ver horarios/app_api.py).
// 401 = hace falta la clave. Las escrituras llevan `X-Mitre: 1` (defensa CSRF).

import { pedir } from '@/red'

const BASE = '/app-horarios/api'

export class ErrorApi extends Error {
  constructor(status, datos) {
    super((datos && datos.error) || (status === 0 ? 'Sin conexión con el servidor.' : `Error ${status}`))
    this.status = status
    this.datos = datos || {}
  }

  get sinConexion() { return this.status === 0 }
}

export async function api(ruta, { metodo = 'GET', cuerpo } = {}) {
  const opciones = {
    method: metodo,
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
  }
  if (metodo !== 'GET') opciones.headers['X-Mitre'] = '1'
  if (cuerpo !== undefined) {
    opciones.headers['Content-Type'] = 'application/json'
    opciones.body = JSON.stringify(cuerpo)
  }
  const resp = await pedir(BASE + ruta, opciones)
  if (!resp) throw new ErrorApi(0, null)
  const datos = await resp.json().catch(() => null)
  if (!resp.ok) throw new ErrorApi(resp.status, datos)
  return datos
}

// Los PDF los hace el servidor (/horarios/export/..., horarios/rutas.py), que reconoce la
// misma sesión. Se abren en otra pestaña.
export function abrirPdf(ruta) {
  window.open('/horarios/export/pdf/' + ruta, '_blank', 'noopener')
}
