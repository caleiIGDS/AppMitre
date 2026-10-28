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
// Cambiar sólo cuando cambie el formato de /datos, no con cada compilación.
const VERSION_DATOS = 'horarios-datos-v1'

export const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error) => {
      if (error?.status === 401) window.dispatchEvent(new CustomEvent('horarios:sin-sesion'))
    },
  }),
  defaultOptions: {
    queries: {
      staleTime: 10 * 60 * 1000,
      // Infinity y no UN_MES: gcTime es un setTimeout, y más de 2^31 ms (~24 días) el
      // navegador lo toma como 0. El horario restaurado se borraba de la memoria al
      // instante si ninguna pantalla lo estaba usando todavía (abrir con la red lenta), y
      // con él la copia del dispositivo.
      gcTime: Infinity,
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

// Devuelve cuándo terminó de cargar lo guardado: main.js espera eso para abrir la app.
export function activarPersistencia() {
  if (typeof indexedDB === 'undefined') return Promise.resolve()
  const persister = createAsyncStoragePersister({ storage: almacen, key: CLAVE_ALMACEN, throttleTime: 1000 })
  const restaurar = persister.restoreClient.bind(persister)
  persister.restoreClient = async () => {
    const guardado = await restaurar()
    // Las versiones anteriores usaban la fecha del build. Su formato sigue siendo
    // compatible: conservar esa copia al actualizar, también si no hay conexión.
    if (guardado && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(guardado.buster)) {
      guardado.buster = VERSION_DATOS
    }
    return guardado
  }
  const [, restaurado] = persistQueryClient({
    queryClient,
    persister,
    maxAge: UN_MES,
    buster: VERSION_DATOS,
    dehydrateOptions: {
      // Con datos, aunque la última actualización haya fallado (ver src/consultas.js).
      shouldDehydrateQuery: (q) => q.state.data !== undefined && q.queryKey[0] !== 'sesion',
    },
  })
  return restaurado
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
