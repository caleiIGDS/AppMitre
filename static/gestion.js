// gestion.js — mejora client-side de /gestion (progressive enhancement):
// búsqueda en vivo del listado (filtra filas en el navegador al escribir).
// Sin JS, sigue funcionando con la búsqueda server-side clásica.
//
// BÚSQUEDA EN VIVO: filtra las filas en el navegador mientras se escribe, sin ir
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
