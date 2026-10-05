// ¿Hay sesión de horarios? La misma que abre /horarios/login (HORARIOS_CLAVE).
import { useQuery, useMutation } from '@tanstack/vue-query'
import { api } from './api'
import { queryClient, olvidarTodo, avisarOtrasPestanas } from './consultas'

const CLAVE = ['sesion']
const pedir = () => api('/sesion')

export function useSesion() {
  return useQuery({ queryKey: CLAVE, queryFn: pedir, staleTime: 60 * 1000 })
}

// Para el router. Sin red no se sabe: se deja pasar, y la app muestra lo que tenga
// guardado. Si después el servidor dice 401, se pide la clave.
export async function hayAcceso() {
  if (!navigator.onLine) return true
  try {
    // Sin reintentos: con la red caída a medias, el reintento de la consulta dejaría
    // la pantalla esperando en vez de abrir con lo guardado.
    const s = await queryClient.fetchQuery({ queryKey: CLAVE, queryFn: pedir, staleTime: 60 * 1000, retry: false })
    return s.autenticado
  } catch {
    return true
  }
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
