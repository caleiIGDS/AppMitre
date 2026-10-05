// El horario entero, bajado de una vez (GET /datos) y guardado en el dispositivo. Todas
// las búsquedas salen de acá, sin red: es la misma lógica que static/js/script.js
// (filtrarClasesLocal, personalToFila, obtenerPreceptorLocal, filtrarOpciones), ahora en
// funciones puras.

import { computed } from 'vue'
import { useQuery, useMutation } from '@tanstack/vue-query'
import { api } from './api'
import { queryClient, avisarOtrasPestanas } from './consultas'

export const CLAVE_DATOS = ['horarios', 'datos']

export function useHorarios() {
  return useQuery({ queryKey: CLAVE_DATOS, queryFn: () => api('/datos') })
}

export function useActualizarDesdePlanilla() {
  return useMutation({
    mutationFn: () => api('/actualizar', { metodo: 'POST' }),
    onSuccess: async () => {
      await queryClient.refetchQueries({ queryKey: CLAVE_DATOS })
      avisarOtrasPestanas('datos')
    },
  })
}

// --- Texto ---------------------------------------------------------------------------
// Igual que `normalize` de script.js: sin mayúsculas, acentos, espacios ni "°".
export function normalizar(texto) {
  if (!texto) return ''
  return String(texto).toLowerCase()
    .normalize('NFD').replace(/[̀-ͯ]/g, '')
    .replace(/\s+/g, '').replace(/°/g, '')
}

const sinAcentosMayus = (d) => d.normalize('NFD').replace(/[̀-ͯ]/g, '').toUpperCase()

// --- Búsquedas -------------------------------------------------------------------------
export const MODOS = ['curso', 'profesor', 'aula', 'horario_preceptor']
export const COMPARABLES = ['curso', 'profesor', 'aula']

// Una fila de personal no docente con forma de clase, para dibujarla en el calendario.
export function personalAFila(p, dias) {
  const porDia = Object.fromEntries(dias.map((d) => [sinAcentosMayus(d), d]))
  return {
    curso: '', division: '', materia: p.rol, profesor: p.nombre, aula: '',
    dia: porDia[p.dia] || p.dia, hora_inicio: p.hora_inicio, hora_fin: p.hora_fin,
    grupo: '', superposicion: 0, suplente_activo: 0, prof_suplente: '', sup_ini: '', sup_fin: '',
    tipo: 'personal',
  }
}

// Las clases de un curso, profesor o aula. En profesor (fuera de la comparación) suma el
// horario de personal no docente con ese nombre, como hace la página clásica.
export function clasesDe(d, modo, valor, { conPersonal = true } = {}) {
  if (!d) return []
  const clases = d.clases
  let filas
  if (modo === 'profesor') {
    filas = clases.filter((f) => f.profesor === valor || (f.suplente_activo == 1 && f.prof_suplente === valor))
    if (conPersonal) filas = filas.concat(d.personal.filter((p) => p.nombre === valor).map((p) => personalAFila(p, d.dias)))
  } else if (modo === 'aula') {
    filas = clases.filter((f) => String(f.aula) === String(valor))
  } else if (modo === 'curso') {
    const partes = valor.replace(/°/g, '').trim().split(/\s+/)
    filas = partes.length >= 2
      ? clases.filter((f) => String(f.curso) === partes[0] && f.division === partes[1])
      : clases.filter((f) => String(f.curso) === partes[0])
  } else {
    filas = []
  }
  return filas
}

// Las clases de un piso en un día, para la planilla general.
export function clasesDePiso(d, dia, piso) {
  const aulas = d?.pisos[piso] || []
  return d ? d.clases.filter((f) => f.dia === dia && aulas.includes(String(f.aula))) : []
}

// El horario de un preceptor (tabla horarios_preceptores), por nombre exacto.
export function horarioPreceptor(d, nombre) {
  return d?.preceptores.horarios[nombre] || []
}

// Los preceptores de un curso, por turno. null si no hay ninguno cargado.
export function preceptoresDeCurso(d, valorCurso) {
  if (!d) return null
  const v = String(valorCurso).replace(/°/g, '').trim()
  const i = v.indexOf(' ')
  const curso = i === -1 ? v : v.slice(0, i)
  const num = (curso.match(/\d+/) || [curso])[0]
  const div = (i === -1 ? '' : v.slice(i + 1).trim()).toUpperCase()
  const fila = d.preceptores.planilla.find((p) => String(p.curso) === num && String(p.division).toUpperCase() === div)
  if (!fila || (!fila.manana && !fila.tarde && !fila.vespertino)) return null
  return fila
}

// Las opciones del buscador para lo que se va escribiendo: primero las que empiezan con
// el texto, después el resto, en orden alfabético. En profesores se suman los no docentes
// (con su rol, y también se los encuentra por el rol).
export function opcionesBuscador(d, modo, texto) {
  if (!d) return []
  const q = normalizar(texto)
  const ordenar = (lista) => lista.sort((a, b) => {
    const na = normalizar(a.display); const nb = normalizar(b.display)
    const sa = na.startsWith(q); const sb = nb.startsWith(q)
    if (sa !== sb) return sa ? -1 : 1
    return a.display.localeCompare(b.display)
  })

  if (modo === 'profesor') {
    const items = new Map()
    for (const nombre of d.listas.profesor) {
      if (!q || normalizar(nombre).includes(q)) items.set(normalizar(nombre), { valor: nombre, display: nombre })
    }
    for (const p of d.listas.personal) {
      if (q && !normalizar(p.nombre).includes(q) && !normalizar(p.rol).includes(q)) continue
      const k = normalizar(p.nombre)
      if (items.has(k)) items.get(k).rol = p.rol
      else items.set(k, { valor: p.nombre, display: p.nombre, rol: p.rol })
    }
    return ordenar([...items.values()])
  }
  const lista = modo === 'curso'
    ? d.listas.curso
    : (d.listas[modo] || []).map((v) => ({ valor: v, display: v }))
  if (!q) return lista
  return ordenar(lista.filter((o) => normalizar(o.display).includes(q)))
}

export const useDatos = () => {
  const consulta = useHorarios()
  return { consulta, d: computed(() => consulta.data.value) }
}
