// La memoria de datos de la app: qué se bajó del servidor, cuándo, y cómo se mantiene al
// día. La maneja TanStack Query; acá se configura una sola vez.
//
//   - Todo lo que se bajó queda en memoria y en el dispositivo (localStorage): la app
//     abre mostrando lo último que vio, sin esperar a la red, y después lo actualiza.
//   - "Actualizar" es barato: el servidor contesta 304 sin datos si nada cambió (ETag).
//   - Se vuelve a preguntar al volver a la pestaña, al recuperar la conexión y cada
//     minuto mientras la pestaña está a la vista, para enterarse de cambios ajenos
//     (otro dispositivo, el asistente).
//   - Un cambio hecho en una pestaña avisa a las demás del mismo navegador.

import { QueryCache, QueryClient } from '@tanstack/vue-query'
import { persistQueryClient } from '@tanstack/query-persist-client-core'
import { createSyncStoragePersister } from '@tanstack/query-sync-storage-persister'

const UNA_SEMANA = 1000 * 60 * 60 * 24 * 7
const CLAVE_ALMACEN = 'mitre-datos'

export const queryClient = new QueryClient({
  // Un 401 en algo de un inventario quiere decir que se perdió el acceso a ESE inventario
  // (le cambiaron la clave, quitaron la invitación). Lo escucha main.js para llevar a la
  // pantalla de la clave, sin que cada pantalla tenga que acordarse.
  queryCache: new QueryCache({
    onError: (error, consulta) => {
      const [area, inv] = consulta.queryKey
      if (error?.status === 401 && area === 'gestion' && inv && inv !== 'inventarios') {
        window.dispatchEvent(new CustomEvent('mitre:sin-acceso', { detail: { inv } }))
      }
    },
  }),
  defaultOptions: {
    queries: {
      staleTime: 30 * 1000,
      gcTime: UNA_SEMANA,
      refetchOnWindowFocus: true,
      refetchOnReconnect: true,
      refetchInterval: 60 * 1000,
      refetchIntervalInBackground: false,
      // Sin red, mostrar lo guardado en vez de quedarse esperando.
      networkMode: 'offlineFirst',
      retry: (intentos, error) => (error?.status === 0 || error?.status >= 500) && intentos < 2,
    },
    mutations: {
      // 'always': sin red, guardar falla enseguida con un aviso claro. Con 'online'
      // quedaría en "GUARDANDO…" hasta que vuelva la conexión, que es peor.
      networkMode: 'always',
      retry: false,
    },
  },
})

// Devuelve cuándo terminó de cargar lo guardado: main.js espera eso para abrir la app,
// así la primera pantalla (y el router, que pregunta por el /meta) ya lo encuentran.
export function activarPersistencia() {
  let almacen
  try {
    almacen = window.localStorage
    almacen.setItem('mitre-prueba', '1')
    almacen.removeItem('mitre-prueba')
  } catch {
    return Promise.resolve() // ventana privada estricta o almacenamiento bloqueado: la app anda igual, sin memoria
  }
  const [, restaurado] = persistQueryClient({
    queryClient,
    persister: createSyncStoragePersister({ storage: almacen, key: CLAVE_ALMACEN, throttleTime: 1000 }),
    maxAge: UNA_SEMANA,
    // Una versión nueva de la app descarta lo guardado por la anterior: el formato de los
    // datos puede haber cambiado.
    buster: __VERSION_APP__,
    dehydrateOptions: {
      // Con datos, aunque la última actualización haya fallado (status 'error'): si no, un
      // pedido sin red borraba del dispositivo justo lo que hacía falta para usarla sin red.
      shouldDehydrateQuery: (q) => q.state.data !== undefined && q.meta?.guardar !== false,
    },
  })
  return restaurado
}

// Al salir (o si la sesión se corta) no queda nada de los datos en el dispositivo.
// La consulta de la sesión se conserva (quien la cambia la reescribe enseguida): si se
// borrara, los componentes ya montados que la observan quedarían mirando una consulta
// huérfana y no se enterarían del cambio de sesión.
export function olvidarTodo() {
  queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== 'sesion' })
  try { window.localStorage.removeItem(CLAVE_ALMACEN) } catch { /* sin almacenamiento */ }
}

// --- Aviso entre pestañas ------------------------------------------------------------
const canal = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel('mitre') : null

export function avisarCambio(clave) {
  canal?.postMessage({ tipo: 'cambio', clave })
}

export function avisarSesion() {
  canal?.postMessage({ tipo: 'sesion' })
}

canal?.addEventListener('message', ({ data }) => {
  if (data?.tipo === 'cambio') queryClient.invalidateQueries({ queryKey: data.clave })
  if (data?.tipo === 'sesion') queryClient.invalidateQueries({ queryKey: ['sesion'] })
})
