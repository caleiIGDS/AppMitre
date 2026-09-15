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
// cargar, para no pisar un aterrizaje con ?q= difuso. También reordena: las filas que
// coinciden por nombre/descripción (data-buscar) primero, y las que sólo coinciden por el
// alias oculto (data-alias) al final, misma jerarquía que la segunda pasada de crud.py.
(function () {
    'use strict';

    var input = document.querySelector('.g-search input[name="q"]');
    var tabla = document.querySelector('.g-table');
    if (!input || !tabla) return;  // no es una página de listado

    var form = input.closest('form');
    var cuerpo = tabla.querySelector('tbody');
    // Orden original de las filas (el `ORDER BY nombre` del servidor). Se captura una sola
    // vez: `filtrar()` reordena el DOM, así que este array es la única referencia estable.
    var filas = Array.prototype.slice.call(cuerpo.querySelectorAll('tr'));
    var contador = document.querySelector('.g-toolbar .g-count, .g-toolbar .g-fichas-count');
    var boton = form ? form.querySelector('button[type="submit"]') : null;

    // Filtros propios del listado de recursos (templates/gestion/lista.html): pueden no
    // existir (cualquier otro listado del área) — se combinan con la búsqueda de arriba.
    var selectUbicacion = document.getElementById('filtro-ubicacion');
    var selectEstado = document.getElementById('filtro-estado');
    var sliderFecha = document.getElementById('filtro-fecha');
    var sliderFechaValor = document.getElementById('filtro-fecha-valor');
    var chipBaja = document.getElementById('filtro-baja');
    var btnAbrirFiltros = document.getElementById('btn-abrir-filtros');
    var panelFiltros = document.getElementById('panel-filtros');
    var esFichas = !!(contador && contador.className.indexOf('g-fichas-count') !== -1);

    // Mismo factor que gestion.py::DIAS_POR_MES, para convertir el valor del slider
    // (meses, pasos de 0.5) a los días que trae cada fila en data-dias-revision.
    var DIAS_POR_MES = 30.5;

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
    var etiquetasFuera = false;
    var vacio = document.createElement('p');
    vacio.className = 'g-help g-sin-resultados';
    vacio.hidden = true;
    var contenedorTabla = tabla.parentNode;  // .g-table-wrap
    contenedorTabla.parentNode.insertBefore(vacio, contenedorTabla.nextSibling);

    function filtrar() {
        var q = norm(input.value);
        var ubicacion = selectUbicacion ? selectUbicacion.value : '';
        var estado = selectEstado ? selectEstado.value : '';
        var umbralMeses = sliderFecha ? parseFloat(sliderFecha.value) : 0;
        var umbralDias = umbralMeses * DIAS_POR_MES;
        var mostrarBaja = !!(chipBaja && chipBaja.getAttribute('aria-pressed') === 'true');
        var visibles = 0;
        var porNombre = [], porAlias = [], ocultas = [];
        for (var i = 0; i < filas.length; i++) {
            var fila = filas[i];
            var texto = fila.getAttribute('data-buscar') || '';
            var alias = fila.getAttribute('data-alias') || '';
            var coincide = coincideTexto(q, texto);
            // Segunda pasada por el alias oculto, igual que crud.py::lista(): solo si NO
            // matcheó por nombre/descripción, y a un grupo aparte que va al final. Sin esto
            // buscar "pinza" dejaba "Alicate" (alias "pinza universal") arriba de "Pinza de
            // fuerza", porque el filtro sólo ocultaba filas y respetaba el orden alfabético.
            var esAlias = false;
            if (!coincide && alias && coincideTexto(q, alias)) { coincide = true; esAlias = true; }
            // data-ubicacion trae TODOS los lugares del recurso, delimitados por "|"
            // (un recurso puede estar repartido en más de uno): substring, no igualdad.
            if (coincide && ubicacion) coincide = (fila.getAttribute('data-ubicacion') || '').indexOf('|' + ubicacion + '|') !== -1;
            if (coincide && estado) coincide = fila.getAttribute('data-estado') === estado;
            // data-dias-revision viene vacío para una fecha corta sin año (no se puede
            // ubicar en el tiempo, ver gestion.py::_dias_sin_revisar): Number('') es 0, así
            // que nunca alcanza un umbral > 0 y la fila queda afuera del filtro, igual que
            // con el chip fijo que reemplaza este slider.
            if (coincide && umbralMeses > 0) {
                coincide = Number(fila.getAttribute('data-dias-revision') || 0) >= umbralDias;
            }
            // El chip ahora es excluyente: activado, muestra SOLO los dados de baja (no los
            // suma a la vista de siempre); desactivado, los sigue dejando afuera como antes
            // (arrancan con `hidden` puesto por el propio servidor, ver lista.html).
            if (mostrarBaja) coincide = coincide && fila.classList.contains('g-recurso-baja');
            else if (fila.classList.contains('g-recurso-baja')) coincide = false;
            fila.hidden = !coincide;
            if (!coincide) ocultas.push(fila);
            else { visibles++; (esAlias ? porAlias : porNombre).push(fila); }
        }
        // El "· por alias" que pudo dejar el render server-side (aterrizaje con ?q=) queda
        // mintiendo apenas el JS decide el orden, y acá el alias no se muestra: se saca.
        if (!etiquetasFuera) {
            var tags = tabla.querySelectorAll('.g-tag-alias');
            for (var t = 0; t < tags.length; t++) tags[t].hidden = true;
            etiquetasFuera = true;
        }
        // Un solo appendChild del fragment = un solo reflow. Las ocultas van al final para
        // no dejar huecos en el medio del orden visible.
        var frag = document.createDocumentFragment();
        var orden = porNombre.concat(porAlias, ocultas);
        for (var j = 0; j < orden.length; j++) frag.appendChild(orden[j]);
        cuerpo.appendChild(frag);
        if (contador) contador.textContent = esFichas ? (visibles + ' FICHAS') : visibles;
        if ((q !== '' || ubicacion || estado || umbralMeses > 0 || mostrarBaja) && visibles === 0) {
            vacio.textContent = q !== ''
                ? 'No se encontraron resultados para "' + input.value.trim() + '".'
                : 'No se encontraron recursos con ese filtro.';
            vacio.hidden = false;
        } else {
            vacio.hidden = true;
        }
        // El símbolo de filtro (celular) marca si hay algo activo, para que cerrar el
        // panel no borre el rastro de que la lista está filtrada.
        if (btnAbrirFiltros) {
            btnAbrirFiltros.classList.toggle('g-filtro-activo', !!(ubicacion || estado || umbralMeses > 0 || mostrarBaja));
        }
    }

    input.addEventListener('input', filtrar);
    if (selectUbicacion) selectUbicacion.addEventListener('change', filtrar);
    if (selectEstado) selectEstado.addEventListener('change', filtrar);
    if (sliderFecha) {
        sliderFecha.addEventListener('input', function () {
            if (sliderFechaValor) sliderFechaValor.textContent = sliderFecha.value;
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

    // Símbolo de filtro (celular, ver gestion.css): abre/cierra el panel de filtros como
    // un desplegable en vez de tenerlo siempre visible ocupando la franja de búsqueda.
    // En escritorio el botón queda oculto por CSS y el panel siempre visible: este código
    // no tiene efecto ahí.
    if (btnAbrirFiltros && panelFiltros) {
        btnAbrirFiltros.addEventListener('click', function () {
            var abierto = panelFiltros.classList.toggle('g-filtros-abierta');
            btnAbrirFiltros.setAttribute('aria-expanded', abierto ? 'true' : 'false');
        });
        document.addEventListener('click', function (e) {
            if (!panelFiltros.classList.contains('g-filtros-abierta')) return;
            if (e.target.closest('#panel-filtros') || e.target.closest('#btn-abrir-filtros')) return;
            panelFiltros.classList.remove('g-filtros-abierta');
            btnAbrirFiltros.setAttribute('aria-expanded', 'false');
        });
    }
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
