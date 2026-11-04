import { onMounted, onUnmounted } from 'vue'

const UMBRAL = 3 // sólo tolerancia al pequeño temblor de un toque, sin espera por tiempo
const CONTROLES = 'input, textarea, select, option, label, code, [contenteditable], video, audio, iframe, object, embed, [data-sin-arrastre]'
export function useDesplazamiento() {
  let gesto = null
  let limpiarClick = () => {}

  function cancelar() {
    gesto = null
    document.body.classList.remove('a-desplazando')
  }

  function contenedor(el, eje) {
    const vertical = eje === 'y'
    const cabe = (n) => vertical ? n.scrollHeight > n.clientHeight : n.scrollWidth > n.clientWidth
    const desborde = (n) => getComputedStyle(n)[vertical ? 'overflowY' : 'overflowX']
    for (let n = el; n && n !== document.body && n !== document.documentElement; n = n.parentElement) {
      if (/(auto|scroll)/.test(desborde(n)) && cabe(n)) return n
      // Un modal no debe desplazar la página que tiene detrás.
      if (n.matches('dialog, [aria-modal="true"]')) return null
    }
    const raiz = document.scrollingElement
    if (!raiz || [document.body, document.documentElement].some((n) => /hidden|clip/.test(desborde(n)))) return null
    return cabe(raiz) ? raiz : null
  }

  function bajar(e) {
    limpiarClick()
    cancelar()
    if (e.pointerType !== 'mouse' || !e.isPrimary ||
        e.button !== 0 || e.ctrlKey || e.metaKey || e.altKey || e.shiftKey ||
        !(e.target instanceof Element) || e.target.closest(CONTROLES)) return
    // No tomar el arrastre de las barras de desplazamiento del navegador o de un panel.
    const raiz = document.documentElement
    if (e.clientX >= raiz.clientWidth || e.clientY >= raiz.clientHeight) return
    const r = e.target.getBoundingClientRect()
    if (e.target.clientWidth && e.target.offsetWidth > e.target.clientWidth &&
        e.clientX >= r.left + e.target.clientLeft + e.target.clientWidth) return
    gesto = { id: e.pointerId, el: e.target, x: e.clientX, y: e.clientY, activo: false }
  }

  function mover(e) {
    if (!gesto || e.pointerId !== gesto.id) return
    if (!(e.buttons & 1) || document.body.classList.contains('a-ordenando')) return cancelar()
    const dx = e.clientX - gesto.x
    const dy = e.clientY - gesto.y
    if (!gesto.activo) {
      if (Math.hypot(dx, dy) < UMBRAL) return
      // Aunque no haya más recorrido, un deslizamiento nunca debe abrir el elemento.
      gesto.activo = true
      gesto.eje = Math.abs(dx) > Math.abs(dy) ? 'x' : 'y'
      gesto.contenedor = contenedor(gesto.el, gesto.eje)
      gesto.inicio = gesto.contenedor?.[gesto.eje === 'y' ? 'scrollTop' : 'scrollLeft']
      document.body.classList.add('a-desplazando')
      window.getSelection()?.removeAllRanges()
    }
    e.preventDefault()
    if (gesto.contenedor) {
      gesto.contenedor[gesto.eje === 'y' ? 'scrollTop' : 'scrollLeft'] =
        gesto.inicio - (gesto.eje === 'y' ? dy : dx)
    }
  }

  function soltar(e) {
    if (!gesto || e.pointerId !== gesto.id) return
    // Algunos dispositivos entregan el último movimiento junto con la suelta.
    if (e.type === 'pointerup' && !gesto.activo) mover({
      pointerId: e.pointerId, buttons: 1, clientX: e.clientX, clientY: e.clientY,
      preventDefault: () => e.preventDefault(),
    })
    if (!gesto) return
    const bloquear = gesto.activo && e.type === 'pointerup'
    cancelar()
    if (!bloquear) return
    // Se descarta sólo el click del deslizamiento. Un nuevo pointerdown lo libera.
    const tragar = (click) => {
      if (click.detail === 0) return // activación por teclado
      click.preventDefault()
      click.stopImmediatePropagation()
      limpiarClick()
    }
    const tiempo = setTimeout(() => limpiarClick(), 500)
    limpiarClick = () => {
      clearTimeout(tiempo)
      window.removeEventListener('click', tragar, true)
      limpiarClick = () => {}
    }
    window.addEventListener('click', tragar, true)
  }

  const nativo = (e) => { if (gesto) e.preventDefault() }
  const clickPrematuro = (e) => {
    if (gesto && e.detail !== 0) {
      e.preventDefault()
      e.stopImmediatePropagation()
    }
  }
  const desenfocar = (e) => { if (e.target === window) cancelar() }
  const eventos = [
    ['pointerdown', bajar], ['pointermove', mover], ['pointerup', soltar],
    ['pointercancel', soltar], ['blur', desenfocar], ['dragstart', nativo], ['selectstart', nativo],
    ['click', clickPrematuro],
  ]
  onMounted(() => {
    for (const [tipo, fn] of eventos) window.addEventListener(tipo, fn, { capture: true, passive: false })
  })
  onUnmounted(() => {
    cancelar()
    limpiarClick()
    for (const [tipo, fn] of eventos) window.removeEventListener(tipo, fn, true)
  })
}
