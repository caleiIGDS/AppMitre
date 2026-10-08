// El horario entero, bajado de una vez (GET /datos) y guardado en el dispositivo. Todas
// las búsquedas salen de acá, sin red, en funciones puras.

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
// Sin mayúsculas, acentos, espacios ni "°".
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
// horario de personal no docente con ese nombre.
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

// --- Materias (pestaña MATERIAS) ------------------------------------------------------
// El tipo de materia viene escrito a mano en la planilla: se lo lleva a una de tres claves.
export const TIPOS_MATERIA = [
  ['te', 'TÉCNICO-ESPECÍFICA'],
  ['ct', 'CIENTÍFICO-TECNOLÓGICA'],
  ['fg', 'TEÓRICA'],
]
export function claveTipo(tipo) {
  const t = normalizar(tipo).replace(/[-_]/g, '')
  if (t.startsWith('tecnic')) return 'te'
  if (t.startsWith('cientif')) return 'ct'
  if (t.startsWith('teoric') || t.startsWith('formaciongeneral') || t === 'normal') return 'fg'
  return ''
}

// La especialidad de una división: fija por curso (ESPECIALIDAD_CURSOS de config.py).
export function especialidadDe(d, curso, division) {
  return d?.especialidades?.[`${curso} ${division}`] || ''
}

// La sigla de la especialidad, para la tabla (si no es ninguna conocida, el nombre entero).
const SIGLAS = { electromecanica: 'ELEC', maestromayordeobra: 'MMO', maestromayordeobras: 'MMO',
  energiasrenovables: 'EERR', ciclobasico: 'CB' }
export const siglaEspecialidad = (e) => SIGLAS[normalizar(e)] || e

// Las divisiones (sólo la división: "2", "A") de los años y especialidades dados (vacío =
// todos), para el filtro de división: primero los números, después las letras.
export function divisionesDe(d, anios = [], esps = []) {
  const vistas = new Set()
  for (const f of d?.clases || []) {
    if (!f.curso || !f.division) continue
    if (anios.length && !anios.includes(String(f.curso))) continue
    if (esps.length && !esps.includes(normalizar(especialidadDe(d, f.curso, f.division)))) continue
    vistas.add(String(f.division))
  }
  return [...vistas].sort((a, b) => a.localeCompare(b, 'es', { numeric: true }))
}

// Las especialidades de config, para los filtros: [[clave, nombre]], en el orden de config.
export function especialidades(d) {
  const vistas = new Map()
  for (const e of Object.values(d?.especialidades || {})) {
    if (e && !vistas.has(normalizar(e))) vistas.set(normalizar(e), e)
  }
  return [...vistas.entries()]
}

const minutos = (h) => { const [hh, mm] = String(h || '').split(':').map(Number); return hh * 60 + (mm || 0) }

// Una fila por materia y división (y grupo, si cada grupo tiene su docente) con sus horas
// semanales, filtrada por tipo, año, división y especialidad (vacío = todos) y por texto
// (materia o docente). Dentro de cada filtro las opciones se suman; entre filtros, se cruzan:
// años 4 y 5 con la división 2 es 4° 2 y 5° 2.
export function materiasFiltradas(d, { tipos = [], anios = [], divs = [], esps = [], texto = '' } = {}) {
  if (!d) return []
  const q = normalizar(texto)
  const grupos = new Map()
  for (const f of d.clases) {
    if (!f.materia || !f.curso) continue
    const tipo = claveTipo(f.tipo_materia)
    const esp = especialidadDe(d, f.curso, f.division)
    if (tipos.length && !tipos.includes(tipo)) continue
    if (anios.length && !anios.includes(String(f.curso))) continue
    if (divs.length && !divs.includes(String(f.division))) continue
    if (esps.length && !esps.includes(normalizar(esp))) continue
    const docente = f.suplente_activo == 1 && f.prof_suplente ? f.prof_suplente : f.profesor
    if (q && !normalizar(f.materia).includes(q) && !normalizar(f.profesor).includes(q)
        && !normalizar(f.prof_suplente).includes(q)) continue
    const clave = [f.curso, f.division, f.grupo, f.materia, f.profesor, docente].join('|')
    if (!grupos.has(clave)) {
      grupos.set(clave, {
        clave, curso: String(f.curso), division: f.division, grupo: f.grupo || '', materia: f.materia,
        tipo, especialidad: esp, profesor: f.profesor,
        suplente: docente !== f.profesor ? docente : '', minutos: 0,
      })
    }
    const fin = minutos(f.hora_fin) - minutos(f.hora_inicio)
    if (fin > 0) grupos.get(clave).minutos += fin
  }
  const orden = (a, b) => a.localeCompare(b, 'es', { numeric: true })
  return [...grupos.values()].sort((a, b) => orden(a.curso, b.curso) || orden(a.division, b.division)
    || orden(a.materia, b.materia) || orden(a.grupo, b.grupo))
}

export function horasTexto(min) {
  const h = Math.floor(min / 60); const m = min % 60
  return m ? `${h} h ${m}'` : `${h} h`
}

export const useDatos = () => {
  const consulta = useHorarios()
  return { consulta, d: computed(() => consulta.data.value) }
}
