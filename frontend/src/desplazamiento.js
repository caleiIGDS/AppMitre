import { ref, watch, onMounted, onUnmounted } from 'vue'

const CLAVE = 'mitre-desplazar-arrastrando'
const UMBRAL = 8
const CONTROLES = 'input, textarea, select, option, label, code, [contenteditable], video, audio, iframe, object, embed, [data-sin-arrastre]'
function leer() {
  try { return localStorage.getItem(CLAVE) === '1' } catch { return false }
}

// Preferencia de este navegador: algunas pantallas entregan eventos de mouse, no touch.
export const desplazarArrastrando = ref(leer())

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
    if (!desplazarArrastrando.value || e.pointerType !== 'mouse' || !e.isPrimary ||
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
      gesto.eje = Math.abs(dx) > Math.abs(dy) ? 'x' : 'y'
      gesto.contenedor = contenedor(gesto.el, gesto.eje)
      if (!gesto.contenedor) return cancelar()
      gesto.inicio = gesto.contenedor[gesto.eje === 'y' ? 'scrollTop' : 'scrollLeft']
      gesto.activo = true
      document.body.classList.add('a-desplazando')
      window.getSelection()?.removeAllRanges()
    }
    e.preventDefault()
    gesto.contenedor[gesto.eje === 'y' ? 'scrollTop' : 'scrollLeft'] =
      gesto.inicio - (gesto.eje === 'y' ? dy : dx)
  }

  function soltar(e) {
    if (!gesto || e.pointerId !== gesto.id) return
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
  const desenfocar = (e) => { if (e.target === window) cancelar() }
  const eventos = [
    ['pointerdown', bajar], ['pointermove', mover], ['pointerup', soltar],
    ['pointercancel', soltar], ['blur', desenfocar], ['dragstart', nativo], ['selectstart', nativo],
  ]
  const dejarDeObservar = watch(desplazarArrastrando, (valor) => {
    cancelar()
    limpiarClick()
    try { localStorage.setItem(CLAVE, valor ? '1' : '0') } catch { /* dura hasta recargar */ }
  }, { flush: 'sync' })
  onMounted(() => {
    for (const [tipo, fn] of eventos) window.addEventListener(tipo, fn, { capture: true, passive: false })
  })
  onUnmounted(() => {
    cancelar()
    limpiarClick()
    dejarDeObservar()
    for (const [tipo, fn] of eventos) window.removeEventListener(tipo, fn, true)
  })
}
