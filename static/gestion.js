// gestion.js — dos mejoras client-side de /gestion (progressive enhancement):
//   1) búsqueda en vivo del listado (filtra filas en el navegador al escribir);
//   2) agregar al carrito por AJAX (botón RETIRO sin recargar la página).
// Sin JS, ambas siguen funcionando con el comportamiento server-side clásico.
//
// (1) BÚSQUEDA EN VIVO: filtra las filas en el navegador mientras se escribe, sin ir
// al servidor (todos los recursos ya vienen en la página). Instantáneo y sin
// round-trips. Sin JS, el <form> hace la búsqueda difusa server-side (lista()). Con
// JS, el filtrado local es por substring sobre data-buscar (texto ya normalizado por
// Python) — perdona acentos y mayúsculas. No se filtra al cargar, para no pisar un
// aterrizaje con ?q= difuso.
(function () {
    'use strict';

    var input = document.querySelector('.g-search input[name="q"]');
    var tabla = document.querySelector('.g-table');
    if (!input || !tabla) return;  // no es una página de listado

    var form = input.closest('form');
    var filas = Array.prototype.slice.call(tabla.querySelectorAll('tbody tr'));
    var contador = document.querySelector('.g-toolbar .g-count');
    var boton = form ? form.querySelector('button[type="submit"]') : null;

    // Misma normalización que _norm() en gestion.py: minúsculas, sin acentos,
    // espacios colapsados. Así "multimetro" (sin tilde) matchea "Multímetro".
    function norm(texto) {
        return texto.normalize('NFD').replace(/[\u0300-\u036f]/g, '')
            .toLowerCase().replace(/\s+/g, ' ').trim();
    }

    // Mensaje de "sin resultados", oculto hasta que la búsqueda no encuentre nada.
    var vacio = document.createElement('p');
    vacio.className = 'g-help g-sin-resultados';
    vacio.hidden = true;
    var contenedorTabla = tabla.parentNode;  // .g-table-wrap
    contenedorTabla.parentNode.insertBefore(vacio, contenedorTabla.nextSibling);

    function filtrar() {
        var q = norm(input.value);
        var visibles = 0;
        for (var i = 0; i < filas.length; i++) {
            var texto = filas[i].getAttribute('data-buscar') || '';
            var coincide = q === '' || texto.indexOf(q) !== -1;
            filas[i].hidden = !coincide;
            if (coincide) visibles++;
        }
        if (contador) contador.textContent = visibles;
        if (q !== '' && visibles === 0) {
            vacio.textContent = 'No se encontraron resultados para "' + input.value.trim() + '".';
            vacio.hidden = false;
        } else {
            vacio.hidden = true;
        }
    }

    input.addEventListener('input', filtrar);
    // Con JS el filtrado es en vivo: que Enter no recargue, y el botón sobra.
    if (form) form.addEventListener('submit', function (e) { e.preventDefault(); });
    if (boton) boton.hidden = true;
})();


// (2) CARRITO tipo e-commerce, sin recargar la página. El botón RETIRAR de cada recurso
// lo agrega al carrito; al hacerlo, el botón se transforma en un stepper (−  N  +)
// que ajusta la cantidad hasta el stock disponible. Se puede decrementar a 0, y cuando
// llega a 0 el stepper se oculta y reaparece el botón RETIRAR. Todo es OPTIMISTA: la UI
// cambia al instante y el servidor se sincroniza en background (fetch).
// Sin JS, el <form> hace su POST + redirect normal; el stepper es una mejora con JS.
(function () {
    'use strict';

    var cartLink = document.querySelector('.g-cart-link');
    var SET_URL = cartLink && cartLink.getAttribute('data-set-url');

    function badgeActual() {
        var b = document.querySelector('[data-cart-count]');
        return b ? (parseInt(b.textContent, 10) || 0) : 0;
    }
    function setBadge(count) {
        var badges = document.querySelectorAll('[data-cart-count]');
        for (var i = 0; i < badges.length; i++) {
            badges[i].textContent = count;
            badges[i].hidden = !count;
        }
    }
    function stockDe(widget) {
        var s = parseInt(widget.getAttribute('data-stock'), 10);
        return (isNaN(s) || s <= 0) ? Infinity : s;  // sin stock definido => sin tope
    }
    function mostrarStepper(widget, cant) {
        widget.setAttribute('data-cant', cant);
        var form = widget.querySelector('.g-retiro-form');
        var stepper = widget.querySelector('.g-stepper');
        var num = widget.querySelector('.g-step-cant');
        var mas = widget.querySelector('.g-step-mas');
        if (form) form.hidden = true;
        if (stepper) stepper.hidden = false;
        if (num) num.textContent = cant;
        if (mas) mas.disabled = cant >= stockDe(widget);
    }
    function ocultarStepper(widget) {
        widget.setAttribute('data-cant', 0);
        var form = widget.querySelector('.g-retiro-form');
        var stepper = widget.querySelector('.g-stepper');
        if (stepper) stepper.hidden = true;
        if (form) form.hidden = false;
    }
    // Manda la cantidad actual del widget al server. Coalesce: si ya hay una en vuelo,
    // marca "sucio" y reenvía al terminar, así ráfagas de +/− no pisan el orden.
    function sincronizar(widget) {
        if (!SET_URL) return;
        if (widget._sending) { widget._dirty = true; return; }
        widget._sending = true;
        var body = new FormData();
        body.append('recurso_id', widget.getAttribute('data-recurso'));
        body.append('cantidad', widget.getAttribute('data-cant'));
        fetch(SET_URL, { method: 'POST', body: body, headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (r) { return r.ok ? r.json() : Promise.reject(); })
            .then(function (data) { setBadge(data.count); })
            .catch(function () {})
            .then(function () {
                widget._sending = false;
                if (widget._dirty) { widget._dirty = false; sincronizar(widget); }
            });
    }

    // Botón RETIRAR: agrega 1 (o +1 sobre lo que ya haya) y muestra el stepper al instante.
    document.addEventListener('submit', function (e) {
        var form = e.target.closest && e.target.closest('[data-add-carrito]');
        if (!form) return;
        e.preventDefault();
        var widget = form.closest('.g-retiro-widget');
        if (!widget || !SET_URL) {  // fallback: si no hay JS, usar form clásico
            fetch(form.action, { method: 'POST', body: new FormData(form), headers: { 'X-Requested-With': 'XMLHttpRequest' } })
                .then(function (r) { return r.json(); }).then(function (d) { setBadge(d.count); })
                .catch(function () { form.submit(); });
            return;
        }
        var actual = parseInt(widget.getAttribute('data-cant'), 10) || 0;
        var nuevo = Math.min(actual + 1, stockDe(widget));
        if (actual === 0) setBadge(badgeActual() + 1);  // ítem nuevo => sube el badge
        mostrarStepper(widget, nuevo);
        sincronizar(widget);
    });

    // + / − del stepper: ajusta la cantidad (0 => saca el ítem y vuelve al botón RETIRAR).
    document.addEventListener('click', function (e) {
        var boton = e.target.closest && e.target.closest('.g-step-mas, .g-step-menos');
        if (!boton) return;
        var widget = boton.closest('.g-retiro-widget');
        if (!widget) return;
        e.preventDefault();
        var actual = parseInt(widget.getAttribute('data-cant'), 10) || 0;
        var nuevo = Math.min(actual + (boton.classList.contains('g-step-mas') ? 1 : -1), stockDe(widget));
        if (nuevo <= 0) {
            ocultarStepper(widget);
            setBadge(Math.max(0, badgeActual() - 1));
        } else {
            mostrarStepper(widget, nuevo);
        }
        sincronizar(widget);
    });

    // Al cargar: los recursos que ya están en el carrito arrancan mostrando el stepper.
    var widgets = document.querySelectorAll('.g-retiro-widget');
    for (var i = 0; i < widgets.length; i++) {
        var c = parseInt(widgets[i].getAttribute('data-cant'), 10) || 0;
        if (c > 0) mostrarStepper(widgets[i], c);
    }
})();
