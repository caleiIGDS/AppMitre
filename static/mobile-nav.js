// mobile-nav.js — El panel lateral (☰) de las áreas que comparten el shell de
// gestion.css: /gestion, /historia, /agente y /accesos.
//
// Mueve DOS clases de bloque al panel, con reglas distintas:
//
//   .g-areas    — el menú para saltar de área (server-rendered, un link por permiso).
//                 Va al panel SIEMPRE, a cualquier ancho: es lo que hace que el ☰
//                 exista también en escritorio. Sin sesión el server no lo renderiza.
//   .g-nav      — las pestañas de las entidades del área.
//   .g-header-actions — las acciones de la página (widget del asistente, carrito).
//                 Estos dos van al panel SÓLO en celular (≤900px), porque ahí no
//                 entran en una fila; al agrandar la pantalla vuelven al header, a su
//                 lugar exacto.
//
// MUEVE los nodos, no los clona: así los listeners ya enganchados por gestion.js
// (carrito) y gestion-agente.js (botón del asistente) siguen funcionando, y no se
// duplican los IDs del markup original.
//
// El botón ☰ sólo se muestra si el panel tiene algo adentro: en escritorio sin sesión
// (la pantalla de login, por ejemplo) no hay áreas que ofrecer y no aparece.
//
// El SPA de horarios (`/`) NO usa este archivo: tiene otro shell y otra hoja de
// estilos, y su panel es `areas-nav.js` — ahí el contenido es sólo links, no hay nada
// que mover. Ver agent_docs/frontend-ui.md.
(function () {
    'use strict';

    var MOBILE = '(max-width: 900px)';

    document.addEventListener('DOMContentLoaded', function () {
        var header = document.querySelector('.g-header .g-header-flex');
        var areas = document.querySelector('.g-areas');
        var nav = document.querySelector('.g-nav');
        var acciones = document.querySelector('.g-header-actions');
        if (!header || (!areas && !nav && !acciones)) return;

        // ---- Botón hamburguesa ----
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

        // Las áreas se mudan una sola vez y se quedan; el nav y las acciones van y vienen.
        // El orden importa: las áreas primero, que es lo que se ve al abrir en escritorio.
        var fijo = recordar(areas);
        if (fijo) cuerpo.appendChild(fijo.el);

        var moviles = [recordar(nav), recordar(acciones)].filter(Boolean);
        var enPanel = false;

        function aPanel() {
            if (enPanel) return;
            moviles.forEach(function (b) { cuerpo.appendChild(b.el); });
            enPanel = true;
        }

        function aHeader() {
            if (!enPanel) return;
            cerrar();
            moviles.forEach(function (b) { b.marca.parentNode.insertBefore(b.el, b.marca); });
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

        function aplicar() {
            if (mq.matches) aPanel(); else aHeader();
            // Un panel vacío no merece botón. En celular siempre hay algo (el nav o las
            // acciones); en escritorio, sólo si el server renderizó el bloque de áreas.
            btn.classList.toggle('g-visible', cuerpo.children.length > 0);
            if (!cuerpo.children.length) cerrar();
        }

        if (mq.addEventListener) mq.addEventListener('change', aplicar);
        else if (mq.addListener) mq.addListener(aplicar);  // Safari viejo
        aplicar();
    });
})();
