// Impresión local: los mismos filtros y componentes que la pantalla, sin pedir un PDF
// al servidor. El navegador conserva el texto y los bordes como vectores al guardar PDF.
import { createApp, h, nextTick } from 'vue'
import { clasesDe, clasesDePiso, horarioPreceptor, preceptoresDeCurso } from './datos'
import Calendario from './componentes/Calendario.vue'
import TablaPreceptor from './componentes/TablaPreceptor.vue'
import PlanillaPreceptores from './componentes/PlanillaPreceptores.vue'
import estilos from './impresion.css?inline'

export function paginasImpresion(d, { modo, valor, dia, piso, cursos } = {}) {
  if (!d) throw new Error('Primero descargá los horarios para poder imprimirlos.')
  if (cursos) return cursos.map((curso) => paginasImpresion(d, { modo: 'curso', valor: curso })[0])
  if (modo === 'planilla_preceptores') {
    // Partir la tabla mantiene una letra legible aunque haya muchos cursos.
    const filas = d.preceptores.planilla
    const partes = Math.max(1, Math.ceil(filas.length / 22))
    return Array.from({ length: partes }, (_, i) => ({
      titulo: `Planilla de preceptores (${i + 1}/${partes})`,
      componente: PlanillaPreceptores, props: { filas: filas.slice(i * 22, (i + 1) * 22) },
    }))
  }
  if (modo === 'horario_preceptor') return [{
    titulo: `Horario de preceptor: ${valor}`, componente: TablaPreceptor,
    props: { filas: horarioPreceptor(d, valor), dias: d.dias },
  }]
  const planilla = modo === 'planilla'
  const filas = planilla ? clasesDePiso(d, dia, piso) : clasesDe(d, modo, valor)
  return [{
    titulo: planilla ? `Planilla general: ${piso} - ${dia}` : `Horario de ${modo}: ${valor}`,
    preceptores: modo === 'curso' ? preceptoresDeCurso(d, valor) : null,
    componente: Calendario,
    props: { filas, columnas: planilla ? d.pisos[piso] : d.dias,
      campo: planilla ? 'aula' : 'dia', modo, variante: planilla ? 'planilla' : 'horario',
      licenciadaDe: valor },
  }]
}

export async function imprimirHorarios(d, seleccion) {
  const paginas = paginasImpresion(d, seleccion)
  if (!paginas.length) throw new Error('Seleccioná al menos un curso.')
  // Se abre durante el click para que el navegador permita la ventana, también offline.
  const ventana = window.open('', '_blank')
  if (!ventana) throw new Error('Permití las ventanas emergentes para imprimir el horario.')
  ventana.opener = null
  const doc = ventana.document
  doc.title = paginas.length === 1 ? paginas[0].titulo : 'Horarios de cursos'
  doc.documentElement.lang = 'es'
  const estilo = doc.createElement('style')
  estilo.textContent = estilos
  doc.head.append(estilo)
  const contenedor = doc.createElement('div')
  doc.body.append(contenedor)
  const app = createApp({ render: () => h('div', [
    h('aside', { class: 'controles' }, [
      h('span', 'Elegí “Guardar como PDF” o tu impresora. Formato A4 horizontal, sin encabezados ni pies del navegador.'),
      h('button', { onClick: () => ventana.print() }, 'IMPRIMIR / GUARDAR PDF'),
    ]),
    ...paginas.map((pagina) => h('section', { class: 'pagina' }, [
      h('div', { class: 'contenido' }, [
        h('h1', pagina.titulo),
        pagina.preceptores ? h('p', ['manana', 'tarde', 'vespertino']
          .filter((turno) => pagina.preceptores[turno])
          .map((turno) => `${({ manana: 'MAÑANA', tarde: 'TARDE', vespertino: 'VESPERTINO' })[turno]}: ${pagina.preceptores[turno]}`).join(' · ')) : null,
        h(pagina.componente, pagina.props),
      ]),
    ])),
  ]) })
  try {
    app.mount(contenedor)
    await nextTick()
    // A4 útil = 281 x 194 mm. Se ajusta cada calendario entero a su propia página.
    for (const pagina of doc.querySelectorAll('.pagina')) {
      const contenido = pagina.querySelector('.contenido')
      const escala = Math.min(1, pagina.clientHeight / contenido.scrollHeight)
      contenido.style.transform = `scale(${escala})`
      contenido.style.width = `${100 / escala}%`
    }
    ventana.addEventListener('beforeunload', () => app.unmount(), { once: true })
    ventana.focus()
    ventana.print()
  } catch (error) {
    app.unmount()
    ventana.close()
    throw error
  }
}
