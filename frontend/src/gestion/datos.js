// Datos del inventario. Una sola fuente: la lista completa de recursos, que el servidor
// manda con todo lo que muestran el listado y la ficha (unidades, kit, fotos). La ficha y
// el formulario leen de esa misma lista, así abrir un recurso no espera a la red.
//
// Cada cambio devuelve el recurso tal como quedó en el servidor y la app reemplaza SOLO
// esa fila en su copia: volver al inventario no vuelve a bajar nada.

import { computed, toValue } from 'vue'
import { useQuery, useMutation } from '@tanstack/vue-query'
import { api } from '@/api'
import { queryClient, avisarCambio } from '@/consultas'

export const CLAVE_GESTION = ['gestion']
const CLAVE_RECURSOS = ['gestion', 'recursos']
const CLAVE_META = ['gestion', 'meta']

export function useMetaGestion() {
  return useQuery({
    queryKey: CLAVE_META,
    queryFn: () => api('/gestion/meta'),
    staleTime: 10 * 60 * 1000,
    refetchInterval: false,
  })
}

export function useRecursos() {
  return useQuery({
    queryKey: CLAVE_RECURSOS,
    queryFn: () => api('/gestion/recursos').then((d) => d.filas),
  })
}

export function useRecurso(id) {
  const consulta = useRecursos()
  const recurso = computed(() => {
    const filas = consulta.data.value
    return filas ? filas.find((r) => r.id === Number(toValue(id))) || null : undefined
  })
  return { consulta, recurso }
}

// --- Escritura -----------------------------------------------------------------------

function ordenar(filas) {
  return [...filas].sort((a, b) => a.nombre.localeCompare(b.nombre, 'es', { sensitivity: 'base' }))
}

export function reemplazarRecurso(fila) {
  queryClient.setQueryData(CLAVE_RECURSOS, (filas) => {
    if (!filas) return filas
    const resto = filas.filter((r) => r.id !== fila.id)
    return ordenar([...resto, fila])
  })
}

function quitarRecurso(id) {
  queryClient.setQueryData(CLAVE_RECURSOS, (filas) => filas && filas.filter((r) => r.id !== id))
}

// Mutación sobre UN recurso que devuelve el recurso actualizado. `optimista(recurso)`,
// si se pasa, devuelve cómo se ve el recurso ya cambiado: se muestra al instante y se
// deshace solo si el servidor rechaza el cambio.
function mutacionRecurso(llamada, { optimista } = {}) {
  return useMutation({
    mutationFn: llamada,
    onMutate: async (vars) => {
      if (!optimista) return {}
      await queryClient.cancelQueries({ queryKey: CLAVE_RECURSOS })
      const previo = queryClient.getQueryData(CLAVE_RECURSOS)
      const actual = previo?.find((r) => r.id === vars.id)
      if (actual) reemplazarRecurso(optimista(actual, vars))
      return { previo }
    },
    onError: (error, _vars, contexto) => {
      if (contexto?.previo) queryClient.setQueryData(CLAVE_RECURSOS, contexto.previo)
      // Un conflicto trae el recurso como está de verdad: mostrar ése, no el viejo.
      if (error?.datos?.actual) reemplazarRecurso(error.datos.actual)
      if (error?.status === 404) queryClient.invalidateQueries({ queryKey: CLAVE_RECURSOS })
    },
    onSuccess: (fila) => {
      if (fila?.id) reemplazarRecurso(fila)
      avisarCambio(CLAVE_GESTION)
    },
  })
}

export function useGuardarRecurso() {
  return useMutation({
    mutationFn: ({ id, valores, version }) => id
      ? api(`/gestion/recursos/${id}`, { metodo: 'PUT', cuerpo: { ...valores, version } })
      : api('/gestion/recursos', { metodo: 'POST', cuerpo: valores }),
    onSuccess: (fila) => {
      reemplazarRecurso(fila)
      avisarCambio(CLAVE_GESTION)
    },
  })
}

export function useEliminarRecurso() {
  return useMutation({
    mutationFn: (id) => api(`/gestion/recursos/${id}`, { metodo: 'DELETE' }),
    onSuccess: ({ id }) => {
      quitarRecurso(id)
      avisarCambio(CLAVE_GESTION)
    },
  })
}

export function useMoverUnidades() {
  return mutacionRecurso(({ id, numeros, ubicacion }) =>
    api(`/gestion/recursos/${id}/unidades/mover`, { metodo: 'POST', cuerpo: { numeros, ubicacion } }))
}

export function useQuitarUnidad() {
  return mutacionRecurso(
    ({ id, numero }) => api(`/gestion/recursos/${id}/unidades/quitar`, { metodo: 'POST', cuerpo: { numero } }),
    {
      optimista: (r, { numero }) => {
        const grupos = r.unidades
          .map((g) => ({ ...g, numeros: g.numeros.filter((n) => n !== numero) }))
          .filter((g) => g.numeros.length && g.ubicacion !== 'Sin ubicar')
        const sinUbicar = r.unidades.find((g) => g.ubicacion === 'Sin ubicar')?.numeros || []
        grupos.push({ ubicacion: 'Sin ubicar', numeros: [...sinUbicar, numero].sort((a, b) => a - b) })
        return { ...r, unidades: grupos }
      },
    })
}

export function useAgregarKitItem() {
  return mutacionRecurso(({ id, item }) =>
    api(`/gestion/recursos/${id}/kit`, { metodo: 'POST', cuerpo: item }))
}

export function useEditarKitItem() {
  return mutacionRecurso(
    ({ id, item }) => api(`/gestion/recursos/${id}/kit/${item.id}`, { metodo: 'PUT', cuerpo: item }),
    { optimista: (r, { item }) => ({ ...r, kit: r.kit.map((k) => (k.id === item.id ? { ...k, ...item } : k)) }) })
}

export function useEliminarKitItem() {
  return mutacionRecurso(
    ({ id, itemId }) => api(`/gestion/recursos/${id}/kit/${itemId}`, { metodo: 'DELETE' }),
    { optimista: (r, { itemId }) => ({ ...r, kit: r.kit.filter((k) => k.id !== itemId) }) })
}

export function useSubirFoto() {
  return mutacionRecurso(({ id, archivo }) =>
    api(`/gestion/recursos/${id}/fotos`, { metodo: 'POST', archivo }))
}

export function useEliminarFoto() {
  return mutacionRecurso(
    ({ id, foto }) => api(`/gestion/recursos/${id}/fotos/${foto.indice}`, {
      metodo: 'DELETE', consulta: { fecha: foto.fecha },
    }),
    { optimista: (r, { foto }) => ({ ...r, fotos: r.fotos.filter((f) => f.url !== foto.url) }) })
}

export function useAlias() {
  return useQuery({
    queryKey: ['gestion', 'alias'],
    queryFn: () => api('/gestion/alias').then((d) => d.filas),
  })
}
