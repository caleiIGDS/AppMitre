// ¿Hay sesión de horarios? La misma que abre /horarios/login (HORARIOS_CLAVE).
import { useQuery, useMutation } from '@tanstack/vue-query'
import { api } from './api'
import { queryClient, olvidarTodo, avisarOtrasPestanas } from './consultas'
import { CLAVE_DATOS } from './datos'

const CLAVE = ['sesion']
const pedir = () => api('/sesion')
// El encabezado y el router comparten la consulta. Si uno permite reintentos, el
// otro puede heredar su promesa pausada sin red y bloquear la primera navegación.
const opcionesSesion = {
  queryKey: CLAVE, queryFn: pedir, staleTime: 60 * 1000,
  networkMode: 'always', retry: false,
}

export function useSesion() {
  return useQuery(opcionesSesion)
}

// Para el router. Sin red no se sabe: se deja pasar, y la app muestra lo que tenga
// guardado. Con el horario ya guardado tampoco se espera al servidor (la red puede estar
// colgada): se abre con eso y, si resulta que la sesión se cerró, se pide la clave.
export async function hayAcceso() {
  if (!navigator.onLine) return true
  // Sin reintentos: con la red caída a medias, el reintento de la consulta dejaría
  // la pantalla esperando en vez de abrir con lo guardado.
  const respuesta = queryClient.fetchQuery(opcionesSesion)
    .then((s) => s.autenticado, () => true)
  if (queryClient.getQueryData(CLAVE_DATOS) === undefined) return respuesta
  respuesta.then((ok) => { if (!ok) window.dispatchEvent(new CustomEvent('horarios:sin-sesion')) })
  return true
}

export function useEntrar() {
  return useMutation({
    mutationFn: (clave) => api('/entrar', { metodo: 'POST', cuerpo: { clave } }),
    onSuccess: (s) => {
      queryClient.setQueryData(CLAVE, s)
      avisarOtrasPestanas('sesion')
    },
  })
}

export function useSalir() {
  return useMutation({
    mutationFn: () => api('/salir', { metodo: 'POST' }),
    onSettled: () => {
      olvidarTodo()
      queryClient.setQueryData(CLAVE, { autenticado: false })
      avisarOtrasPestanas('sesion')
    },
  })
}
