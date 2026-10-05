// Datos de UN inventario. Una sola fuente: la lista completa de recursos, que el servidor
// manda con todo lo que muestran el listado, la ficha y EDITAR (unidades, kit, fotos).
// Las tres pantallas leen de esa misma lista, así abrir un recurso no espera a la red.
//
// Cada cambio devuelve el recurso tal como quedó en el servidor y la app reemplaza SOLO
// esa fila en su copia: volver al inventario no vuelve a bajar nada.
//
// Todo va por inventario (`inv` = el slug de la URL): las claves de la memoria lo llevan,
// así lo bajado de un inventario nunca se muestra en otro.

import { computed, toValue } from 'vue'
import { useQuery, useMutation } from '@tanstack/vue-query'
import { api } from '@/api'
import { queryClient, avisarCambio } from '@/consultas'

const base = (inv) => `/gestion/${encodeURIComponent(inv)}`
export const claveInventario = (inv) => ['gestion', inv]
const claveRecursos = (inv) => ['gestion', inv, 'recursos']
const claveMeta = (inv) => ['gestion', inv, 'meta']

export function pedirMeta(inv) {
  return queryClient.ensureQueryData({ queryKey: claveMeta(inv), queryFn: () => api(`${base(inv)}/meta`) })
}

export function useInventarios() {
  return useQuery({
    queryKey: ['gestion', 'inventarios'],
    queryFn: () => api('/gestion/inventarios'),
    retry: false,
  })
}

export function useMeta(inv) {
  return useQuery({
    queryKey: computed(() => claveMeta(toValue(inv))),
    queryFn: () => api(`${base(toValue(inv))}/meta`),
    enabled: computed(() => !!toValue(inv)),
    staleTime: 5 * 60 * 1000,
    refetchInterval: false,
  })
}

export function useRecursos(inv) {
  return useQuery({
    queryKey: computed(() => claveRecursos(toValue(inv))),
    queryFn: () => api(`${base(toValue(inv))}/recursos`).then((d) => d.filas),
  })
}

export function useRecurso(inv, id) {
  const consulta = useRecursos(inv)
  const recurso = computed(() => {
    const filas = consulta.data.value
    return filas ? filas.find((r) => r.id === Number(toValue(id))) || null : undefined
  })
  return { consulta, recurso }
}

export function useEntrarInventario(inv) {
  return useMutation({
    mutationFn: (clave) => api(`${base(toValue(inv))}/entrar`, { metodo: 'POST', cuerpo: { clave } }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: claveInventario(toValue(inv)) })
      queryClient.invalidateQueries({ queryKey: ['gestion', 'inventarios'] })
    },
  })
}

export function useSalirInventario(inv) {
  return useMutation({
    mutationFn: () => api(`${base(toValue(inv))}/salir`, { metodo: 'POST' }),
    onSettled: () => {
      queryClient.removeQueries({ queryKey: claveInventario(toValue(inv)) })
      queryClient.invalidateQueries({ queryKey: ['gestion', 'inventarios'] })
    },
  })
}

// --- Escritura -----------------------------------------------------------------------

function ordenar(filas) {
  return [...filas].sort((a, b) => a.nombre.localeCompare(b.nombre, 'es', { sensitivity: 'base' }))
}

export function reemplazarRecurso(inv, fila) {
  queryClient.setQueryData(claveRecursos(inv), (filas) => {
    if (!filas) return filas
    return ordenar([...filas.filter((r) => r.id !== fila.id), fila])
  })
}

// Una mutación sobre UN recurso que devuelve el recurso actualizado (todas las rutas
// propias del inventario siguen ese contrato). `optimista(recurso, vars)`, si se pasa,
// devuelve cómo se ve el recurso ya cambiado: se muestra al instante y se deshace solo si
// el servidor rechaza el cambio.
function mutacionRecurso(inv, llamada, { optimista } = {}) {
  return useMutation({
    mutationFn: (vars) => llamada(base(toValue(inv)), vars),
    onMutate: async (vars) => {
      if (!optimista) return {}
      const clave = claveRecursos(toValue(inv))
      await queryClient.cancelQueries({ queryKey: clave })
      const previo = queryClient.getQueryData(clave)
      const actual = previo?.find((r) => r.id === vars.id)
      if (actual) reemplazarRecurso(toValue(inv), optimista(actual, vars))
      return { previo }
    },
    onError: (error, _vars, contexto) => {
      if (contexto?.previo) queryClient.setQueryData(claveRecursos(toValue(inv)), contexto.previo)
      // Un conflicto trae el recurso como está de verdad: mostrar ése, no el viejo.
      if (error?.datos?.actual) reemplazarRecurso(toValue(inv), error.datos.actual)
      if (error?.status === 404) queryClient.invalidateQueries({ queryKey: claveRecursos(toValue(inv)) })
    },
    onSuccess: (fila) => {
      if (fila?.id) reemplazarRecurso(toValue(inv), fila)
      avisarCambio(claveInventario(toValue(inv)))
    },
  })
}

const json = (cuerpo) => ({ metodo: 'POST', cuerpo })

export function useGuardarRecurso(inv) {
  return mutacionRecurso(inv, (b, { id, valores, version }) => id
    ? api(`${b}/recursos/${id}`, { metodo: 'PUT', cuerpo: { ...valores, version } })
    : api(`${b}/recursos`, json(valores)))
}

export const useBaja = (inv) => mutacionRecurso(inv, (b, { id, motivo, detalle }) =>
  api(`${b}/recursos/${id}/baja`, json({ motivo, detalle })))

export const useRevertirBaja = (inv) => mutacionRecurso(inv, (b, { id }) =>
  api(`${b}/recursos/${id}/baja/revertir`, { metodo: 'POST' }))

export const useAgregarUnidades = (inv) => mutacionRecurso(inv, (b, { id, numeros }) =>
  api(`${b}/recursos/${id}/unidades/agregar`, json({ numeros })))

export const useEliminarUnidades = (inv) => mutacionRecurso(inv, (b, { id, numeros, motivo, detalle }) =>
  api(`${b}/recursos/${id}/unidades/eliminar`, json({ numeros, motivo, detalle })))

export const useMoverUnidades = (inv) => mutacionRecurso(inv, (b, { id, numeros, ubicacion }) =>
  api(`${b}/recursos/${id}/unidades/mover`, json({ numeros, ubicacion })))

export const useQuitarUbicacion = (inv) => mutacionRecurso(
  inv,
  (b, { id, numeros }) => api(`${b}/recursos/${id}/unidades/quitar`, json({ numeros })),
  {
    optimista: (r, { numeros }) => {
      const sacadas = new Set(numeros)
      const grupos = r.unidades
        .map((g) => ({ ...g, numeros: g.numeros.filter((n) => !sacadas.has(n)) }))
        .filter((g) => g.numeros.length && g.ubicacion !== 'Sin ubicar')
      const sinUbicar = r.unidades.find((g) => g.ubicacion === 'Sin ubicar')?.numeros || []
      grupos.push({ ubicacion: 'Sin ubicar', numeros: [...new Set([...sinUbicar, ...numeros])].sort((a, b) => a - b) })
      return { ...r, unidades: grupos }
    },
  })

export const useAgregarKitItem = (inv) => mutacionRecurso(inv, (b, { id, item }) =>
  api(`${b}/recursos/${id}/kit`, json(item)))

export const useEditarKitItem = (inv) => mutacionRecurso(
  inv,
  (b, { id, item }) => api(`${b}/recursos/${id}/kit/${item.id}`, { metodo: 'PUT', cuerpo: item }),
  { optimista: (r, { item }) => ({ ...r, kit: r.kit.map((k) => (k.id === item.id ? { ...k, ...item } : k)) }) })

export const useEliminarKitItem = (inv) => mutacionRecurso(
  inv,
  (b, { id, itemId }) => api(`${b}/recursos/${id}/kit/${itemId}`, { metodo: 'DELETE' }),
  { optimista: (r, { itemId }) => ({ ...r, kit: r.kit.filter((k) => k.id !== itemId) }) })

export const useSubirFoto = (inv) => mutacionRecurso(inv, (b, { id, archivo }) =>
  api(`${b}/recursos/${id}/fotos`, { metodo: 'POST', archivo }))

export const useEliminarFoto = (inv) => mutacionRecurso(
  inv,
  (b, { id, foto }) => api(`${b}/recursos/${id}/fotos/${foto.id}`, { metodo: 'DELETE' }),
  { optimista: (r, { foto }) => ({ ...r, fotos: r.fotos.filter((f) => f.id !== foto.id) }) })

export const useRotarFoto = (inv) => mutacionRecurso(inv, (b, { id, foto, imagen }) =>
  api(`${b}/recursos/${id}/fotos/${foto.id}`, { metodo: 'PUT', crudo: imagen }))

// --- Alias y registro de bajas ---------------------------------------------------------

export function useAlias(inv) {
  return useQuery({
    queryKey: computed(() => ['gestion', toValue(inv), 'alias']),
    queryFn: () => api(`${base(toValue(inv))}/alias`).then((d) => d.filas),
  })
}

export function useGuardarAlias(inv) {
  return useMutation({
    mutationFn: ({ id, alias }) => api(`${base(toValue(inv))}/alias/${id}`, { metodo: 'PUT', cuerpo: { alias } }),
    onSuccess: (fila, { alias }) => {
      reemplazarRecurso(toValue(inv), fila)
      queryClient.setQueryData(['gestion', toValue(inv), 'alias'], (filas) =>
        filas && filas.map((f) => (f.id === fila.id ? { ...f, alias } : f)))
      avisarCambio(claveInventario(toValue(inv)))
    },
  })
}

export function useBajas(inv) {
  return useQuery({
    queryKey: computed(() => ['gestion', toValue(inv), 'bajas']),
    queryFn: () => api(`${base(toValue(inv))}/bajas`).then((d) => d.filas),
  })
}

export function useRevertirBajaUnidad(inv) {
  return useMutation({
    mutationFn: (bajaId) => api(`${base(toValue(inv))}/bajas/${bajaId}/revertir`, { metodo: 'POST' }),
    onSuccess: (fila) => {
      reemplazarRecurso(toValue(inv), fila)
      queryClient.invalidateQueries({ queryKey: ['gestion', toValue(inv), 'bajas'] })
      avisarCambio(claveInventario(toValue(inv)))
    },
  })
}

// Cualquier cambio a un recurso puede cambiar el registro de bajas: se marca viejo para
// que la próxima vez que se mire se pida de nuevo (barato: ETag/304 si no cambió).
queryClient.getMutationCache().subscribe((evento) => {
  if (evento.type !== 'updated' || evento.mutation.state.status !== 'success') return
  const fila = evento.mutation.state.data
  if (fila && fila.id && fila.estado !== undefined) {
    queryClient.invalidateQueries({ queryKey: ['gestion'], predicate: (q) => q.queryKey[2] === 'bajas', refetchType: 'none' })
  }
})

// --- La lista de inventarios (sólo administración) -----------------------------------

function useCambioLista(fn) {
  return useMutation({
    mutationFn: fn,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['gestion', 'inventarios'] }),
  })
}

export const useCrearInventario = () =>
  useCambioLista(({ nombre, clave }) => api('/gestion/inventarios', { metodo: 'POST', cuerpo: { nombre, clave } }))

// `cambios`: { nombre } y/o { clave }.
export const useCambiarInventario = () =>
  useCambioLista(({ id, ...cambios }) => api(`/gestion/inventarios/${id}`, { metodo: 'PATCH', cuerpo: cambios }))

export const useEliminarInventario = () =>
  useCambioLista(({ id, confirmar }) => api(`/gestion/inventarios/${id}`, { metodo: 'DELETE', cuerpo: { confirmar } }))

// --- Quién entra a un inventario (el panel del encargado) -----------------------------

const claveAccesos = (inv) => ['gestion', inv, 'accesos']

export function useAccesos(inv) {
  return useQuery({
    queryKey: computed(() => claveAccesos(toValue(inv))),
    queryFn: () => api(`${base(toValue(inv))}/accesos`),
  })
}

function useCambioAccesos(inv, fn) {
  return useMutation({
    mutationFn: fn,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: claveAccesos(toValue(inv)) }),
  })
}

export const useInvitar = (inv) =>
  useCambioAccesos(inv, (datos) => api(`${base(toValue(inv))}/accesos/invitaciones`, { metodo: 'POST', cuerpo: datos }))

export const useQuitarDispositivo = (inv) =>
  useCambioAccesos(inv, (id) => api(`${base(toValue(inv))}/accesos/dispositivos/${id}/quitar`, { metodo: 'POST' }))

export const useAnularInvitacion = (inv) =>
  useCambioAccesos(inv, (id) => api(`${base(toValue(inv))}/accesos/invitaciones/${id}`, { metodo: 'DELETE' }))
