// areas-nav.js — El ☰ del SPA de horarios: abre el panel con las áreas internas.
//
// Es del SPA de horarios (`style.css`), NO de las tres áreas de `gestion.css` — ésas
// usan `mobile-nav.js`, que hace algo distinto: MUEVE el nav y las acciones al panel
// sólo por debajo de 900px, y las devuelve al header al agrandar. Acá el panel existe
// a cualquier ancho y su contenido ya viene renderizado por el server, así que no hay
// nada que mover ni listeners que preservar: sólo abrir y cerrar.
//
// El markup (botón y panel) lo pinta Jinja y sólo si hay sesión, con un link por
// permiso. Si no hay acceso, este archivo ni se carga.
(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', function () {
        var btn = document.getElementById('areas-btn');
        var panel = document.getElementById('areas-panel');
        var overlay = document.getElementById('areas-overlay');
        if (!btn || !panel || !overlay) return;

        var cerrarBtn = panel.querySelector('.areas-panel-close');

        function abierto() {
            return document.body.classList.contains('areas-abierto');
        }

        function abrir() {
            document.body.classList.add('areas-abierto');
            btn.setAttribute('aria-expanded', 'true');
            cerrarBtn.focus();
        }

        function cerrar(devolverFoco) {
            if (!abierto()) return;
            document.body.classList.remove('areas-abierto');
            btn.setAttribute('aria-expanded', 'false');
            if (devolverFoco) btn.focus();
        }

        btn.addEventListener('click', function () {
            if (abierto()) cerrar(true); else abrir();
        });
        cerrarBtn.addEventListener('click', function () { cerrar(true); });
        overlay.addEventListener('click', function () { cerrar(true); });

        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') cerrar(true);
        });
    });
})();
