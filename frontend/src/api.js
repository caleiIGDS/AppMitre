// Cliente de la API JSON de Flask (/app/api/...). Todo pedido al servidor pasa por acá.
//
// Contrato (ver crud.py, "API JSON"):
//   - 401 = sin acceso (sin sesión, o sin la clave del inventario), 403 = sin permiso,
//     404 = no existe, 409 = conflicto (trae `actual`: la fila como está en el servidor),
//     422 = datos inválidos (trae `errores`: {campo: mensaje}).
// Las escrituras llevan `X-Mitre: 1`, que es la defensa CSRF del servidor.

import { pedir } from './red'

const BASE = '/app/api'

export class ErrorApi extends Error {
  constructor(status, datos) {
    super((datos && datos.error) || (status === 0 ? 'Sin conexión con el servidor.' : `Error ${status}`))
    this.status = status
    this.datos = datos || {}
  }

  get sinConexion() { return this.status === 0 }
  get errores() { return this.datos.errores || {} }
}

// `cuerpo`: JSON. `archivo`: multipart con el campo `file`. `crudo`: un Blob tal cual, con
// su propio tipo (la foto girada).
export async function api(ruta, { metodo = 'GET', cuerpo, archivo, crudo } = {}) {
  const opciones = {
    method: metodo,
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
  }
  if (metodo !== 'GET') opciones.headers['X-Mitre'] = '1'
  if (archivo) {
    const datos = new FormData()
    datos.append('file', archivo, archivo.name || 'foto.jpg')
    opciones.body = datos
  } else if (crudo) {
    opciones.headers['Content-Type'] = crudo.type
    opciones.body = crudo
  } else if (cuerpo !== undefined) {
    opciones.headers['Content-Type'] = 'application/json'
    opciones.body = JSON.stringify(cuerpo)
  }

  const resp = await pedir(BASE + ruta, opciones)
  if (!resp) throw new ErrorApi(0, null)
  const datos = await resp.json().catch(() => null)
  if (!resp.ok) throw new ErrorApi(resp.status, datos)
  return datos
}
