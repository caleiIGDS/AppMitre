// Quién está usando la app y qué puede hacer. Los permisos los decide SIEMPRE el
// servidor; acá sólo se usan para no mostrar botones que igual contestarían 403.

import { computed } from 'vue'
import { useQuery, useMutation } from '@tanstack/vue-query'
import { api } from './api'
import { queryClient, olvidarTodo, avisarSesion } from './consultas'

const CLAVE = ['sesion']

function pedirSesion() {
  return api('/sesion')
}

export function useSesion() {
  const consulta = useQuery({ queryKey: CLAVE, queryFn: pedirSesion, staleTime: 5 * 60 * 1000, refetchInterval: false })
  const acceso = computed(() => consulta.data.value?.acceso || null)
  const escuela = computed(() => consulta.data.value?.escuela || { nombre: 'EMILIO MITRE', version: '' })
  return { consulta, acceso, escuela, puede: (permiso) => tienePermiso(acceso.value, permiso) }
}

export function tienePermiso(acceso, permiso) {
  if (!acceso) return false
  return acceso.permisos.includes('*') || acceso.permisos.includes(permiso)
}

// Para el router: la sesión que ya se conoce (aunque sea de la memoria del dispositivo,
// así la app abre sin red) o la que conteste el servidor.
export async function sesionActual() {
  try {
    const datos = await queryClient.ensureQueryData({ queryKey: CLAVE, queryFn: pedirSesion })
    return datos?.acceso || null
  } catch {
    return null
  }
}

export function useEntrar() {
  return useMutation({
    mutationFn: (clave) => api('/sesion', { metodo: 'POST', cuerpo: { clave } }),
    onSuccess: (datos) => {
      olvidarTodo() // nada de lo que vio otro acceso en este dispositivo
      queryClient.setQueryData(CLAVE, datos)
      avisarSesion()
    },
  })
}

export function useSalir() {
  return useMutation({
    mutationFn: () => api('/sesion', { metodo: 'DELETE' }),
    onSettled: () => {
      olvidarTodo()
      queryClient.setQueryData(CLAVE, { acceso: null })
      avisarSesion()
    },
  })
}
