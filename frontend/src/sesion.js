// Quién está usando la app. Los permisos los decide SIEMPRE el servidor; acá sólo se usan
// para no mostrar botones que igual contestarían 403.
//
// Dos niveles, igual que en el servidor (ver accesos.py):
//   - La sesión: el admin (GESTION_CLAVE) o un dispositivo invitado. Sus permisos SIN
//     ámbito (agente, salidas, accesos, administrar la lista de inventarios) vienen de
//     /app/api/sesion.
//   - Lo de cada inventario: lo contesta el /meta de ese inventario (gestion/datos.js),
//     porque depende de la clave del encargado o de una invitación a ESE inventario.

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
  const areas = computed(() => consulta.data.value?.areas || [])
  const escuela = computed(() => consulta.data.value?.escuela || { nombre: 'EMILIO MITRE', version: '' })
  return { consulta, acceso, areas, escuela, puede: (permiso) => tienePermiso(acceso.value, permiso) }
}

// El comodín '*' del admin vale para los permisos de la sesión. Los de un inventario
// nunca se preguntan acá (el comodín no les llega, y eso lo resuelve el servidor).
export function tienePermiso(acceso, permiso) {
  if (!acceso) return false
  return acceso.permisos.includes('*') || acceso.permisos.includes(permiso)
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
    onSettled: (datos) => {
      olvidarTodo()
      queryClient.setQueryData(CLAVE, datos || { acceso: null, areas: [] })
      avisarSesion()
    },
  })
}
