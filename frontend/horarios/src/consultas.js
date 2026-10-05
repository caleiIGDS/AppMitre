// La memoria de la app de horarios. Igual que la de Gestión (src/consultas.js), con dos
// diferencias:
//   - Lo bajado se guarda en IndexedDB y no en localStorage: el horario entero pesa más
//     de medio mega, y localStorage es chico y lo comparte con la app de Gestión.
//   - El horario cambia poco (sólo cuando alguien lo rearma desde la planilla): se vuelve
//     a preguntar cada 10 minutos y al volver a la app, no cada minuto. Preguntar es
//     barato igual: si no cambió, el servidor contesta 304 sin datos.

import { QueryCache, QueryClient } from '@tanstack/vue-query'
import { persistQueryClient } from '@tanstack/query-persist-client-core'
import { createAsyncStoragePersister } from '@tanstack/query-async-storage-persister'
import { get, set, del } from 'idb-keyval'

const UN_MES = 1000 * 60 * 60 * 24 * 30
const CLAVE_ALMACEN = 'mitre-horarios'

export const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error) => {
      if (error?.status === 401) window.dispatchEvent(new CustomEvent('horarios:sin-sesion'))
    },
  }),
  defaultOptions: {
    queries: {
      staleTime: 10 * 60 * 1000,
      gcTime: UN_MES,
      refetchOnWindowFocus: true,
      refetchOnReconnect: true,
      refetchInterval: 10 * 60 * 1000,
      refetchIntervalInBackground: false,
      networkMode: 'offlineFirst',
      retry: (intentos, error) => (error?.status === 0 || error?.status >= 500) && intentos < 2,
    },
    mutations: { networkMode: 'always', retry: false },
  },
})

const almacen = {
  getItem: (k) => get(k),
  setItem: (k, v) => set(k, v),
  removeItem: (k) => del(k),
}

export function activarPersistencia() {
  if (typeof indexedDB === 'undefined') return
  persistQueryClient({
    queryClient,
    persister: createAsyncStoragePersister({ storage: almacen, key: CLAVE_ALMACEN, throttleTime: 1000 }),
    maxAge: UN_MES,
    buster: __VERSION_APP__,
    dehydrateOptions: {
      shouldDehydrateQuery: (q) => q.state.status === 'success' && q.queryKey[0] !== 'sesion',
    },
  })
}

// Al salir no queda nada del horario en el dispositivo.
export function olvidarTodo() {
  queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== 'sesion' })
  del(CLAVE_ALMACEN).catch(() => {})
}

// Otra pestaña de la app entró, salió o rearmó el horario.
const canal = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel('mitre-horarios') : null

export function avisarOtrasPestanas(tipo) {
  canal?.postMessage({ tipo })
}

canal?.addEventListener('message', ({ data }) => {
  if (data?.tipo === 'datos') queryClient.invalidateQueries({ queryKey: ['horarios'] })
  if (data?.tipo === 'sesion') queryClient.invalidateQueries({ queryKey: ['sesion'] })
})
