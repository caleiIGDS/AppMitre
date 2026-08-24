// gestion.js — mejora client-side de /gestion (progressive enhancement):
// búsqueda en vivo del listado (filtra filas en el navegador al escribir).
// Sin JS, sigue funcionando con la búsqueda server-side clásica.
//
// BÚSQUEDA EN VIVO: filtra las filas en el navegador mientras se escribe, sin ir
// al servidor (todos los recursos ya vienen en la página). Instantáneo y sin
// round-trips. Sin JS, el <form> hace la búsqueda difusa server-side (lista()). Con
// JS, el filtrado local es sobre data-buscar (texto ya normalizado por Python) y usa
// el mismo criterio que el backend (texto.puntaje_busqueda, puerto de abajo): substring
// normalizado siempre gana, y perdona typos por similitud a partir de 3 caracteres —
// con JS activo, Enter no recarga y el botón BUSCAR se oculta (ver más abajo), así que
// éste es el único camino de búsqueda que un usuario real recorre. No se filtra al
// cargar, para no pisar un aterrizaje con ?q= difuso.
(function () {
    'use strict';

    var input = document.querySelector('.g-search input[name="q"]');
    var tabla = document.querySelector('.g-table');
    if (!input || !tabla) return;  // no es una página de listado

    var form = input.closest('form');
    var filas = Array.prototype.slice.call(tabla.querySelectorAll('tbody tr'));
    var contador = document.querySelector('.g-toolbar .g-count, .g-toolbar .g-fichas-count');
    var boton = form ? form.querySelector('button[type="submit"]') : null;

    // Filtros propios del listado de recursos (templates/gestion/lista.html): pueden no
    // existir (cualquier otro listado del área) — se combinan con la búsqueda de arriba.
    var selectUbicacion = document.getElementById('filtro-ubicacion');
    var chipVencidos = document.getElementById('filtro-vencidos');
    var chipBaja = document.getElementById('filtro-baja');
    var esFichas = !!(contador && contador.className.indexOf('g-fichas-count') !== -1);

    // Misma normalización que _norm() en gestion.py: minúsculas, sin acentos,
    // espacios colapsados. Así "multimetro" (sin tilde) matchea "Multímetro".
    function norm(texto) {
        return texto.normalize('NFD').replace(/[\u0300-\u036f]/g, '')
            .toLowerCase().replace(/\s+/g, ' ').trim();
    }

    // Puerto de texto.py::puntaje_busqueda (Ratcliff/Obershelp, mismo algoritmo que
    // difflib.SequenceMatcher.ratio del backend), ya usado igual en
    // templates/salidas/formulario.html para el autocompletado de estudiantes. Mismo
    // umbral 0.68 que el backend, medido contra el inventario real (ver texto.py).
    var UMBRAL_SIMILITUD = 0.68;

    function longestMatch(a, b, alo, ahi, blo, bhi) {
        var besti = alo, bestj = blo, bestsize = 0, j2len = {};
        for (var i = alo; i < ahi; i++) {
            var newj2len = {};
            for (var j = blo; j < bhi; j++) {
                if (a[i] === b[j]) {
                    var k = (j2len[j - 1] || 0) + 1;
                    newj2len[j] = k;
                    if (k > bestsize) { besti = i - k + 1; bestj = j - k + 1; bestsize = k; }
                }
            }
            j2len = newj2len;
        }
        return [besti, bestj, bestsize];
    }

    function totalMatches(a, b, alo, ahi, blo, bhi) {
        var m = longestMatch(a, b, alo, ahi, blo, bhi);
        var i = m[0], j = m[1], k = m[2];
        if (k === 0) return 0;
        var total = k;
        if (alo < i && blo < j) total += totalMatches(a, b, alo, i, blo, j);
        if (i + k < ahi && j + k < bhi) total += totalMatches(a, b, i + k, ahi, j + k, bhi);
        return total;
    }

    function ratioTexto(a, b) {
        if (!a.length && !b.length) return 1.0;
        return (2.0 * totalMatches(a, b, 0, a.length, 0, b.length)) / (a.length + b.length);
    }

    // Igual criterio que texto.puntaje_busqueda: substring normalizado siempre gana (y
    // desempata por similitud); si no hay substring, el difuso solo entra con 3+
    // caracteres y por encima del umbral. Devuelve true si matchea.
    function coincideTexto(qNorm, tNorm) {
        if (qNorm === '') return true;
        if (tNorm.indexOf(qNorm) !== -1) return true;
        if (qNorm.length < 3) return false;
        var mejor = ratioTexto(qNorm, tNorm);
        var palabras = tNorm.split(' ');
        for (var i = 0; i < palabras.length; i++) {
            if (palabras[i].length < qNorm.length) continue;  // palabra corta, ruido (ver texto.py)
            mejor = Math.max(mejor, ratioTexto(qNorm, palabras[i]));
        }
        return mejor >= UMBRAL_SIMILITUD;
    }

    // Mensaje de "sin resultados", oculto hasta que la búsqueda no encuentre nada.
    var vacio = document.createElement('p');
    vacio.className = 'g-help g-sin-resultados';
    vacio.hidden = true;
    var contenedorTabla = tabla.parentNode;  // .g-table-wrap
    contenedorTabla.parentNode.insertBefore(vacio, contenedorTabla.nextSibling);

    function filtrar() {
        var q = norm(input.value);
        var ubicacion = selectUbicacion ? selectUbicacion.value : '';
        var soloVencidos = !!(chipVencidos && chipVencidos.getAttribute('aria-pressed') === 'true');
        var mostrarBaja = !!(chipBaja && chipBaja.getAttribute('aria-pressed') === 'true');
        var visibles = 0;
        for (var i = 0; i < filas.length; i++) {
            var fila = filas[i];
            var texto = fila.getAttribute('data-buscar') || '';
            var coincide = coincideTexto(q, texto);
            // data-ubicacion trae TODOS los lugares del recurso, delimitados por "|"
            // (un recurso puede estar repartido en más de uno): substring, no igualdad.
            if (coincide && ubicacion) coincide = (fila.getAttribute('data-ubicacion') || '').indexOf('|' + ubicacion + '|') !== -1;
            if (coincide && soloVencidos) coincide = fila.getAttribute('data-vencido') === '1';
            // Los dados de baja quedan afuera salvo que se pida verlos explícitamente
            // (arrancan con `hidden` puesto por el propio servidor, ver lista.html).
            if (coincide && !mostrarBaja && fila.classList.contains('g-recurso-baja')) coincide = false;
            fila.hidden = !coincide;
            if (coincide) visibles++;
        }
        if (contador) contador.textContent = esFichas ? (visibles + ' FICHAS') : visibles;
        if ((q !== '' || ubicacion || soloVencidos) && visibles === 0) {
            vacio.textContent = q !== ''
                ? 'No se encontraron resultados para "' + input.value.trim() + '".'
                : 'No se encontraron recursos con ese filtro.';
            vacio.hidden = false;
        } else {
            vacio.hidden = true;
        }
    }

    input.addEventListener('input', filtrar);
    if (selectUbicacion) selectUbicacion.addEventListener('change', filtrar);
    if (chipVencidos) {
        chipVencidos.addEventListener('click', function () {
            var activo = chipVencidos.getAttribute('aria-pressed') === 'true';
            chipVencidos.setAttribute('aria-pressed', activo ? 'false' : 'true');
            filtrar();
        });
    }
    if (chipBaja) {
        chipBaja.addEventListener('click', function () {
            var activo = chipBaja.getAttribute('aria-pressed') === 'true';
            chipBaja.setAttribute('aria-pressed', activo ? 'false' : 'true');
            filtrar();
        });
    }
    // Con JS el filtrado es en vivo: que Enter no recargue, y el botón sobra.
    if (form) form.addEventListener('submit', function (e) { e.preventDefault(); });
    if (boton) boton.hidden = true;
})();

// Fila entera clickable en listados con `data-href` (ver .g-table tr[data-href] en
// gestion.css): un solo blanco grande en vez de un link chico. Delegado en document
// porque hay varios listados y las filas las arma Jinja (no cambian después de cargar).
// Si el click cayó sobre un <a> o un control de formulario, gana ese elemento.
document.addEventListener('click', function (e) {
    if (!e.target.closest) return;
    var fila = e.target.closest('tr[data-href]');
    if (!fila || e.target.closest('a, button, input, select, textarea, label')) return;
    window.location = fila.getAttribute('data-href');
});
