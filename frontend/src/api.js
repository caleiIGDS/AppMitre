// Cliente de la API JSON de Flask (/app/api/...). Todo pedido al servidor pasa por acá.
//
// Contrato (ver crud.py, "API JSON"):
//   - 401 = sin sesión, 403 = sin permiso, 404 = no existe,
//   - 409 = conflicto (trae `actual`: la fila como está en el servidor),
//   - 422 = datos inválidos (trae `errores`: {campo: mensaje}).
// Las escrituras llevan `X-Mitre: 1`, que es la defensa CSRF del servidor.

const BASE = '/app/api'

export class ErrorApi extends Error {
  constructor(status, datos) {
    super((datos && datos.error) || (status === 0 ? 'Sin conexión con el servidor.' : `Error ${status}`))
    this.status = status
    this.datos = datos || {}
  }

  get sinConexion() { return this.status === 0 }
  get conflicto() { return this.status === 409 }
  get errores() { return this.datos.errores || {} }
}

export async function api(ruta, { metodo = 'GET', cuerpo, archivo, consulta } = {}) {
  const opciones = {
    method: metodo,
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
  }
  if (metodo !== 'GET') opciones.headers['X-Mitre'] = '1'
  if (archivo) {
    const datos = new FormData()
    datos.append('file', archivo)
    opciones.body = datos
  } else if (cuerpo !== undefined) {
    opciones.headers['Content-Type'] = 'application/json'
    opciones.body = JSON.stringify(cuerpo)
  }

  let url = BASE + ruta
  if (consulta) url += '?' + new URLSearchParams(consulta)

  let resp
  try {
    resp = await fetch(url, opciones)
  } catch {
    throw new ErrorApi(0, null)
  }
  const datos = await resp.json().catch(() => null)
  if (!resp.ok) {
    // La sesión se venció o la revocaron: lo escucha consultas.js para mandar al login.
    if (resp.status === 401) window.dispatchEvent(new CustomEvent('mitre:sin-sesion'))
    throw new ErrorApi(resp.status, datos)
  }
  return datos
}
