// Orden a mano: se arrastra la agarradera del elemento a su lugar. El orden es de cada
// dispositivo (localStorage, una sola clave con
// todas las listas): no cambia lo que ven los demás. Hoy lo usan la lista de inventarios y
// las listas con orden local; las fotos usan el callback de guardado en servidor.
import { reactive, ref, computed, nextTick, watch, onUnmounted } from 'vue'

const CLAVE_ALMACEN = 'mitre-orden'

function leer() {
  try { return JSON.parse(window.localStorage.getItem(CLAVE_ALMACEN)) || {} } catch { return {} }
}
const ordenes = reactive(leer())

// `items` en el orden guardado bajo `clave`. Lo que no figura (lo nuevo) va al final, en su
// orden de siempre.
export function ordenado(clave, items, idDe) {
  const ids = ordenes[clave]
  if (!ids?.length || items.length < 2) return items
  const pos = new Map(ids.map((id, i) => [id, i]))
  const lugar = (it, i) => pos.get(String(idDe(it))) ?? ids.length + i
  return items.map((it, i) => [it, lugar(it, i)]).sort((a, b) => a[1] - b[1]).map(([it]) => it)
}

export function guardarOrden(clave, ids) {
  ordenes[clave] = ids.map(String)
  try { window.localStorage.setItem(CLAVE_ALMACEN, JSON.stringify(ordenes)) } catch { /* sin almacenamiento: dura hasta recargar */ }
}

const UMBRAL = 3 // px de tolerancia al tocar la agarradera
const BORDE = 70 // px del borde de la pantalla donde el arrastre hace scroll
const IGNORAR = 'input, textarea, select, option, code, [contenteditable]'

// Arrastrar para ordenar dentro de `contenedor` (un ref al elemento). Cada elemento lleva
// `data-orden="<id>"`. `lista` es un computed con los items; devuelve `items`, la lista a
// dibujar (durante el arrastre, el orden provisorio) y `arrastrando` (el id levantado).
export function useOrdenable(clave, contenedor, lista, idDe, guardar = null) {
  let guardando = false
  const provisoria = ref(null)
  const arrastrando = ref(null)
  const enOrden = computed(() => guardar ? lista.value : ordenado(clave.value, lista.value, idDe))
  const items = computed(() => {
    if (!provisoria.value) return enOrden.value
    const porId = new Map(enOrden.value.map((it) => [String(idDe(it)), it]))
    return provisoria.value.map((id) => porId.get(id)).filter(Boolean)
  })

  let p = null // el gesto en curso
  let rafScroll = 0

  const elementos = () => [...contenedor.value.querySelectorAll(':scope [data-orden]')]
  const elDe = (id) => elementos().find((el) => el.dataset.orden === id)

  // El elemento levantado sigue al puntero desde el lugar que ocupa en la lista.
  function seguir() {
    const el = elDe(p.id)
    if (!el) return
    el.style.transform = ''
    const r = el.getBoundingClientRect()
    el.style.transform = `translate(${p.x - p.agarreX - r.left}px, ${p.y - p.agarreY - r.top}px)`
  }

  // Si el puntero está sobre otro elemento, el levantado pasa a ese lugar. Los demás se
  // corren con una animación corta (FLIP). `ultimo` evita que dos de distinto tamaño se
  // intercambien una y otra vez sin que el puntero se mueva.
  function buscarLugar() {
    const sobre = elementos().find((el) => {
      if (el.dataset.orden === p.id) return false
      const r = el.getBoundingClientRect()
      return p.x >= r.left && p.x <= r.right && p.y >= r.top && p.y <= r.bottom
    })
    const id = sobre?.dataset.orden || null
    if (id !== p.ultimo) p.ultimo = null
    if (!id || id === p.ultimo) return
    p.ultimo = id
    const antes = new Map(elementos().map((el) => [el, el.getBoundingClientRect()]))
    const ids = provisoria.value.filter((x) => x !== p.id)
    ids.splice(provisoria.value.indexOf(id), 0, p.id)
    provisoria.value = ids
    nextTick(() => {
      if (!p) return
      for (const [el, r] of antes) {
        if (el.dataset.orden === p.id || !el.isConnected) continue
        const n = el.getBoundingClientRect()
        const dx = r.left - n.left
        const dy = r.top - n.top
        if (!dx && !dy) continue
        el.style.transition = 'none'
        el.style.transform = `translate(${dx}px, ${dy}px)`
        el.getBoundingClientRect() // aplicar antes de animar
        el.style.transition = 'transform .15s ease'
        el.style.transform = ''
      }
      seguir()
    })
  }

  function autoScroll() {
    if (!p?.activo) return
    const paso = p.y < BORDE ? -12 : p.y > window.innerHeight - BORDE ? 12 : 0
    if (paso) {
      window.scrollBy(0, paso)
      seguir()
      buscarLugar()
    }
    rafScroll = requestAnimationFrame(autoScroll)
  }

  function empezar() {
    const el = elDe(p.id)
    if (!el) return soltar()
    const r = el.getBoundingClientRect()
    p.activo = true
    p.agarreX = p.x0 - r.left
    p.agarreY = p.y0 - r.top
    provisoria.value = enOrden.value.map((it) => String(idDe(it)))
    p.inicial = provisoria.value.join()
    arrastrando.value = p.id
    el.style.transition = 'none'
    document.body.classList.add('a-ordenando')
    if (p.tactil) navigator.vibrate?.(15)
    seguir()
    rafScroll = requestAnimationFrame(autoScroll)
  }

  function bajar(e) {
    if (guardando || p || e.button !== 0 || !e.isPrimary || e.target.closest(IGNORAR)) return
    const agarre = e.target.closest('.a-orden-agarre')
    if (!agarre) return
    const el = e.target.closest('[data-orden]')
    if (!el || !contenedor.value.contains(el) || lista.value.length < 2) return
    p = {
      id: el.dataset.orden, tactil: e.pointerType !== 'mouse', puntero: e.pointerId,
      agarre,
      x0: e.clientX, y0: e.clientY, x: e.clientX, y: e.clientY, activo: false, ultimo: null,
    }
    agarre.setPointerCapture(e.pointerId)
    window.addEventListener('pointermove', mover)
    window.addEventListener('pointerup', soltar)
    window.addEventListener('pointercancel', soltar)
  }

  function mover(e) {
    if (!p || e.pointerId !== p.puntero) return
    p.x = e.clientX
    p.y = e.clientY
    if (!p.activo) {
      if (Math.hypot(p.x - p.x0, p.y - p.y0) < UMBRAL) return
      empezar()
    }
    seguir()
    buscarLugar()
  }

  function soltar(e) {
    if (!p || (e?.pointerId != null && e.pointerId !== p.puntero)) return
    const g = p
    p = null
    if (g.agarre.hasPointerCapture(g.puntero)) g.agarre.releasePointerCapture(g.puntero)
    cancelAnimationFrame(rafScroll)
    window.removeEventListener('pointermove', mover)
    window.removeEventListener('pointerup', soltar)
    window.removeEventListener('pointercancel', soltar)
    if (!g.activo) return
    // El click que sigue al soltar no tiene que abrir lo que se arrastró.
    const tragar = (e) => { e.preventDefault(); e.stopPropagation() }
    window.addEventListener('click', tragar, { capture: true, once: true })
    setTimeout(() => window.removeEventListener('click', tragar, { capture: true }), 0)
    if (provisoria.value.join() !== g.inicial) {
      if (guardar) {
        guardando = true
        Promise.resolve().then(() => guardar([...provisoria.value]))
          .catch(() => {}).finally(() => { guardando = false; provisoria.value = null })
      } else guardarOrden(clave.value, provisoria.value)
    }
    document.body.classList.remove('a-ordenando')
    const el = elDe(g.id)
    if (!guardando) provisoria.value = null
    if (el) {
      el.style.transition = 'transform .15s ease'
      el.style.transform = ''
    }
    setTimeout(() => { if (arrastrando.value === g.id) arrastrando.value = null }, 150)
  }

  // Con el dedo: mientras se arrastra, que la página no scrollee ni abra el menú del
  // navegador (el de "guardar imagen" o "abrir link", que sale con el toque largo).
  const tocar = (e) => { if (p?.activo) e.preventDefault() }
  const menu = (e) => { if (p) e.preventDefault() }
  const arrastreNativo = (e) => { if (e.target.closest?.('[data-orden]')) e.preventDefault() }

  // El contenedor puede aparecer después (cuando llegan los datos o la primera foto).
  const eventos = [
    ['pointerdown', bajar], ['touchmove', tocar, { passive: false }],
    ['contextmenu', menu], ['dragstart', arrastreNativo],
  ]
  watch(contenedor, (nuevo, viejo) => {
    for (const [tipo, fn] of eventos) viejo?.removeEventListener(tipo, fn)
    for (const [tipo, fn, op] of eventos) nuevo?.addEventListener(tipo, fn, op)
  }, { flush: 'post', immediate: true })
  onUnmounted(() => {
    soltar()
    document.body.classList.remove('a-ordenando')
    for (const [tipo, fn] of eventos) contenedor.value?.removeEventListener(tipo, fn)
  })

  return { items, arrastrando }
}

// La primera foto guardada en el servidor es la portada compartida.
export const portada = (inv, r) => r.fotos[0] || null
