// img-utils.js — Utilidades de imagen compartidas, capa 0: no nombra ningún dominio, no
// sabe qué es una "foto de recurso" ni un "chat". Se carga ANTES que gestion-agente.js
// (mismas plantillas base) porque ese archivo consume `window.ImgUtils.achicarImagen`
// desde adentro de su propio DOMContentLoaded; y `crud/_detalle_fotos.html` la consume
// recién en el submit del formulario de subida manual (bien después de que el DOM
// terminó de cargar), así que el orden de <script defer> alcanza sin más coordinación.
(function () {
    'use strict';

    // La foto se achica ANTES de mandarla. Una foto de celular sale de 3-8 MB y en
    // base64 pesa un tercio más. 1568 px de lado largo es lo que el modelo de visión
    // del agente llega a aprovechar; el mismo criterio vale para la galería manual, que
    // no tiene motivo para guardar más resolución que la que ya se manda por el chat.
    var IMAGEN_LADO_MAX = 1568;
    var IMAGEN_CALIDAD = 0.85;

    function achicarImagen(file) {
        return new Promise(function (resolve, reject) {
            var reader = new FileReader();
            reader.onerror = reject;
            reader.onload = function (evt) {
                var dataUrl = evt.target.result;
                var img = new Image();
                // Si el navegador no puede decodificarla (HEIC de iPhone, formato raro),
                // se manda tal cual: que decida el servidor, mejor que perder la foto.
                img.onerror = function () { resolve(dataUrl); };
                img.onload = function () {
                    var lado = Math.max(img.width, img.height);
                    if (lado <= IMAGEN_LADO_MAX) {
                        resolve(dataUrl);
                        return;
                    }
                    var escala = IMAGEN_LADO_MAX / lado;
                    var canvas = document.createElement('canvas');
                    canvas.width = Math.round(img.width * escala);
                    canvas.height = Math.round(img.height * escala);
                    canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
                    try {
                        resolve(canvas.toDataURL('image/jpeg', IMAGEN_CALIDAD));
                    } catch (e) {
                        resolve(dataUrl);
                    }
                };
                img.src = dataUrl;
            };
            reader.readAsDataURL(file);
        });
    }

    // "data:image/jpeg;base64,AAAA..." -> Blob. La necesita quien tiene una data URL (el
    // resultado de achicarImagen) y tiene que mandarla como multipart/form-data en vez
    // de JSON — el chat manda la data URL entera; la subida manual de la ficha arma un
    // FormData con esto.
    function dataURLaBlob(dataUrl) {
        var partes = dataUrl.split(',');
        var tipo = (partes[0].match(/data:(.*?);base64/) || [, 'image/jpeg'])[1];
        var bin = atob(partes[1]);
        var bytes = new Uint8Array(bin.length);
        for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
        return new Blob([bytes], { type: tipo });
    }

    window.ImgUtils = {
        IMAGEN_LADO_MAX: IMAGEN_LADO_MAX,
        IMAGEN_CALIDAD: IMAGEN_CALIDAD,
        achicarImagen: achicarImagen,
        dataURLaBlob: dataURLaBlob
    };
})();
