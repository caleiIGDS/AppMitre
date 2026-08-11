// mobile-nav.js — Menú lateral ocultable para celular.
// Lo usan las tres áreas que comparten el shell de gestion.css: /gestion, /historia
// y /agente.
//
// En celular (≤900px) las pestañas del nav y los botones del header no entran en
// una fila: se MUEVEN a un panel lateral que se abre con el botón ☰. En escritorio
// (>900px) el script no toca nada — header y nav quedan exactamente como estaban, y
// si la pantalla se agranda los bloques vuelven a su lugar original.
//
// MUEVE los nodos, no los clona: así los listeners ya enganchados por gestion.js
// (carrito) y gestion-agente.js (botón del asistente) siguen funcionando, y no se
// duplican los IDs del markup original.
//
// Sin JS no hay sidebar: el nav y las acciones quedan en el header envolviendo en
// varias filas, que es el comportamiento de siempre.
(function () {
    'use strict';

    var MOBILE = '(max-width: 900px)';

    document.addEventListener('DOMContentLoaded', function () {
        var header = document.querySelector('.g-header .g-header-flex');
        var nav = document.querySelector('.g-nav');
        var acciones = document.querySelector('.g-header-actions');
        if (!header || (!nav && !acciones)) return;

        // ---- Botón hamburguesa (solo visible en celular, ver gestion.css) ----
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'g-menu-btn';
        btn.id = 'g-menu-btn';
        btn.setAttribute('aria-label', 'Abrir menú');
        btn.setAttribute('aria-controls', 'g-sidebar');
        btn.setAttribute('aria-expanded', 'false');
        btn.innerHTML = '<span class="g-menu-bars" aria-hidden="true"></span>';
        header.appendChild(btn);

        // ---- Panel lateral + fondo oscuro ----
        var overlay = document.createElement('div');
        overlay.className = 'g-sidebar-overlay';

        var panel = document.createElement('aside');
        panel.className = 'g-sidebar';
        panel.id = 'g-sidebar';
        panel.setAttribute('aria-label', 'Menú');
        panel.innerHTML =
            '<div class="g-sidebar-head">' +
            '<span class="g-sidebar-title">MENÚ</span>' +
            '<button type="button" class="g-sidebar-close" aria-label="Cerrar menú">✕</button>' +
            '</div>' +
            '<div class="g-sidebar-body"></div>';

        var cuerpo = panel.querySelector('.g-sidebar-body');
        var cerrarBtn = panel.querySelector('.g-sidebar-close');
        document.body.appendChild(overlay);
        document.body.appendChild(panel);

        // Marcador (comentario) en el lugar original de cada bloque, para poder
        // devolverlo exactamente ahí cuando se vuelve a escritorio.
        function recordar(el) {
            if (!el) return null;
            var marca = document.createComment('g-sidebar');
            el.parentNode.insertBefore(marca, el);
            return { el: el, marca: marca };
        }

        var bloques = [recordar(nav), recordar(acciones)].filter(Boolean);
        var enPanel = false;

        function aPanel() {
            if (enPanel) return;
            bloques.forEach(function (b) { cuerpo.appendChild(b.el); });
            enPanel = true;
        }

        function aHeader() {
            if (!enPanel) return;
            cerrar();
            bloques.forEach(function (b) { b.marca.parentNode.insertBefore(b.el, b.marca); });
            enPanel = false;
        }

        function abierto() {
            return document.body.classList.contains('g-sidebar-abierto');
        }

        function abrir() {
            document.body.classList.add('g-sidebar-abierto');
            btn.setAttribute('aria-expanded', 'true');
            cerrarBtn.focus();
        }

        function cerrar(devolverFoco) {
            if (!abierto()) return;
            document.body.classList.remove('g-sidebar-abierto');
            btn.setAttribute('aria-expanded', 'false');
            if (devolverFoco) btn.focus();
        }

        btn.addEventListener('click', function () {
            if (abierto()) cerrar(true); else abrir();
        });
        cerrarBtn.addEventListener('click', function () { cerrar(true); });
        overlay.addEventListener('click', function () { cerrar(true); });

        // Cualquier link o botón del panel (incluido el que abre el asistente)
        // cierra el menú: si no, el panel tapa la pantalla a la que se navegó.
        cuerpo.addEventListener('click', function (e) {
            if (e.target.closest('a, button')) cerrar();
        });

        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') cerrar(true);
        });

        // ---- Cambio de tamaño: mover al panel o devolver al header ----
        var mq = window.matchMedia(MOBILE);
        function aplicar() { if (mq.matches) aPanel(); else aHeader(); }

        if (mq.addEventListener) mq.addEventListener('change', aplicar);
        else if (mq.addListener) mq.addListener(aplicar);  // Safari viejo
        aplicar();
    });
})();
