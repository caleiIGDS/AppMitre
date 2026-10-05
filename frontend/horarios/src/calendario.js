// Motor del calendario: dónde va cada bloque. Es el de static/js/script.js
// (generarCalendario, generarCalendarioComparacion, generarPlanillaGeneral y
// calcularEstilosBloques, ver agent_docs/calendar-engine.md) separado del dibujo: acá se
// calculan posiciones y tipos de bloque; los componentes sólo los pintan.

export function aMinutos(t) {
  if (!t || typeof t !== 'string' || !t.includes(':')) return 0
  const [h, m] = t.split(':').map(Number)
  return h * 60 + m
}

// El rango vertical: desde 30 min antes de la primera hora hasta 30 min después de la
// última, con un alto mínimo de 450 px.
export function rango(filas) {
  const tiempos = new Set()
  for (const f of filas) {
    if (f.hora_inicio) tiempos.add(f.hora_inicio)
    if (f.hora_fin) tiempos.add(f.hora_fin)
  }
  if (!tiempos.size) return null
  const horas = [...tiempos].sort((a, b) => aMinutos(a) - aMinutos(b))
  const min = Math.max(0, aMinutos(horas[0]) - 30)
  const max = Math.min(1440, aMinutos(horas[horas.length - 1]) + 30)
  const alto = Math.max((max - min) * 1.05, 450)
  const y = (hora) => (hora ? ((aMinutos(hora) - min) / (max - min)) * alto : 0)
  return { horas, alto, y }
}

// Clases que se pisan en el tiempo, en grupos (recorrido ordenado por hora de inicio).
function agrupar(clases) {
  const ordenadas = [...clases].sort((a, b) => aMinutos(a.hora_inicio) - aMinutos(b.hora_inicio))
  const grupos = []
  let i = 0
  while (i < ordenadas.length) {
    const grupo = [ordenadas[i]]
    let fin = aMinutos(ordenadas[i].hora_fin)
    let j = i + 1
    while (j < ordenadas.length && aMinutos(ordenadas[j].hora_inicio) < fin) {
      grupo.push(ordenadas[j])
      fin = Math.max(fin, aMinutos(ordenadas[j].hora_fin))
      j++
    }
    grupos.push(grupo)
    i = j
  }
  return grupos
}

// Cómo repartir el ancho dentro de un grupo: con dos o menos, grupo A a la izquierda y B a
// la derecha; con más, partes iguales.
export function estilosBloques(grupo) {
  const n = grupo.length
  if (n > 2) {
    const ancho = 100 / n
    return grupo.map((_, i) => `width: calc(${ancho}% - 6px); left: calc(${ancho * i}% + 4px); right: auto;`)
  }
  const lugar = new Array(n).fill(null)
  let izq = false
  let der = false
  grupo.forEach((c, i) => {
    const g = (c.grupo || '').trim().toUpperCase()
    if (g === 'A' && !izq) { lugar[i] = 'izq'; izq = true } else if (g === 'B' && !der) { lugar[i] = 'der'; der = true }
  })
  grupo.forEach((_, i) => {
    if (lugar[i]) return
    if (!izq && n > 1) { lugar[i] = 'izq'; izq = true } else if (!der && n > 1) { lugar[i] = 'der'; der = true } else lugar[i] = 'todo'
  })
  return lugar.map((l) => (l === 'izq'
    ? 'width: calc(50% - 6px); left: 4px; right: auto;'
    : l === 'der' ? 'width: calc(50% - 6px); right: 4px; left: auto;' : 'left: 4px; right: 4px; width: auto;'))
}

const tieneGrupo = (c) => c.grupo && String(c.grupo).trim() !== ''

// Los bloques de UNA columna (un día, o un aula en la planilla general).
//   variante 'horario' (curso/profesor/aula, también en la comparación) o 'planilla'.
//   `licenciadaDe`: en el horario de un profesor, sus clases con suplente se apartan del
//   grupo si hay otra en el mismo horario (la del suplente que lo reemplaza).
export function bloquesColumna(clases, r, { modo, variante = 'horario', licenciadaDe = null }) {
  const bloques = []
  const materia = (clase, estilo) => {
    const top = r.y(clase.hora_inicio) + 2
    return { tipo: 'materia', clase, estilo, top, alto: Math.max(r.y(clase.hora_fin) - 2 - top, 20) }
  }
  for (const grupo of agrupar(clases)) {
    const sinLicenciadas = variante === 'planilla'
      ? grupo.filter((c) => c.suplente_activo != 1)
      : grupo.filter((c) => !(c.suplente_activo == 1 && c.profesor === licenciadaDe))
    const final = grupo.length > 1 && sinLicenciadas.length ? sinLicenciadas : grupo
    const todosConGrupo = final.every(tieneGrupo)
    const haySuperposicion = final.length > 1 && (variante === 'planilla'
      ? !todosConGrupo
      : (modo === 'aula' || modo === 'profesor' || !todosConGrupo))

    if (haySuperposicion && !final.every((c) => c.superposicion == 1)) {
      const top = r.y(final[0].hora_inicio)
      const ultimo = final.reduce((m, c) => (aMinutos(c.hora_fin) > aMinutos(m.hora_fin) ? c : m))
      bloques.push({ tipo: 'superposicion', clases: final, top, alto: Math.max(r.y(ultimo.hora_fin) - top, 30) })
      continue
    }
    if (variante === 'planilla') {
      const ancho = 100 / final.length
      final.forEach((c, i) => bloques.push(materia(c, haySuperposicion
        ? `width: calc(${ancho}% - 6px); left: calc(${ancho * i}% + 4px);`
        : 'left: 4px; right: 4px;')))
    } else {
      const estilos = estilosBloques(final)
      final.forEach((c, i) => bloques.push(materia(c, estilos[i])))
    }
  }
  return bloques
}

// Lo que dice un bloque, según qué se está mirando: en el horario de un profesor importa
// el curso; en el de un aula o un curso, quién da la clase.
export function nombreProfesor(c) {
  return c.suplente_activo == 1 && c.prof_suplente ? 'SUPLENTE: ' + c.prof_suplente : (c.profesor || '-')
}

export function detalleBloque(c, modo) {
  return modo === 'profesor' ? `${c.curso}° ${c.division}` : nombreProfesor(c)
}

export function indicadorBloque(c, modo) {
  return modo === 'aula' ? `${c.curso}° ${c.division}` : (c.aula || '?')
}

export const COLORES_COMPARACION = ['#1a3a5c', '#c0392b', '#27ae60', '#8e44ad', '#e67e22', '#16a085']
