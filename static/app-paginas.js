// Las pantallas servidas por Flask pertenecen a la misma PWA que el inventario.
// Una actualización sólo se activa al pedirla: puede haber un formulario sin guardar.
(() => {
  const olvidarSesion = () => {
    try { localStorage.removeItem('mitre-datos'); } catch { /* almacenamiento bloqueado */ }
  };
  if (document.currentScript.dataset.autenticado === 'no') olvidarSesion();
  document.addEventListener('submit', evento => {
    if (new URL(evento.target.action).pathname.endsWith('/login')) olvidarSesion();
  });
  if ('serviceWorker' in navigator) {
    let activando = false;
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (activando) location.reload();
    });
    navigator.serviceWorker.register('/gestion/sw.js', { scope: '/gestion/' }).then(registro => {
      let aviso;
      const ofrecer = () => {
        if (!registro.waiting || aviso) return;
        aviso = document.createElement('aside');
        aviso.className = 'g-app-version';
        aviso.setAttribute('role', 'status');
        aviso.innerHTML = '<span>Hay una versión nueva. Guardá lo que estés editando antes de actualizar.</span>' +
          '<button type="button" class="g-btn">ACTUALIZAR</button>' +
          '<button type="button" class="g-btn-outline-dark">DESPUÉS</button>';
        const [actualizar, despues] = aviso.querySelectorAll('button');
        actualizar.addEventListener('click', () => {
          if (!registro.waiting) return;
          activando = true;
          registro.waiting.postMessage({ type: 'SKIP_WAITING' });
        });
        despues.addEventListener('click', () => aviso.remove());
        document.body.append(aviso);
      };
      ofrecer();
      registro.addEventListener('updatefound', () => {
        const nuevo = registro.installing;
        nuevo?.addEventListener('statechange', () => {
          if (nuevo.state === 'installed') ofrecer();
        });
      });
      const revisar = () => registro.update().catch(() => {});
      window.addEventListener('online', revisar);
      setInterval(revisar, 60 * 60 * 1000);
    }).catch(() => {}); // Sin red puede seguir abierta una página ya cargada.
  }

  // Documentos sobre la pantalla actual: cerrar el visor conserva lo escrito en el
  // formulario. PDF.js ya se distribuye localmente con el visor de la normativa.
  let visor;
  let cargaPdf;
  let apertura = 0;
  let scrollPrevio;
  function cerrarDocumento() {
    apertura++;
    cargaPdf?.destroy();
    cargaPdf = null;
    visor.querySelector('.g-app-documento-contenido').replaceChildren();
    document.body.classList.toggle('g-sin-scroll', scrollPrevio);
  }
  document.addEventListener('click', async evento => {
    const link = evento.target.closest('a[data-documento]');
    if (!link || evento.button !== 0 || evento.ctrlKey || evento.metaKey || evento.shiftKey || evento.altKey) return;
    const destino = new URL(link.href);
    if (destino.origin !== location.origin) return;
    evento.preventDefault();
    if (!visor) {
      visor = document.createElement('dialog');
      visor.className = 'g-app-documento';
      visor.setAttribute('aria-label', 'Vista del documento');
      visor.innerHTML = '<div class="g-app-documento-barra"><strong></strong>' +
        '<a class="g-btn-outline-dark" download>DESCARGAR PDF</a>' +
        '<button type="button" class="g-btn" autofocus>CERRAR</button></div>' +
        '<div class="g-app-documento-contenido" aria-live="polite"></div>';
      visor.querySelector('button').addEventListener('click', () => visor.close());
      visor.addEventListener('close', cerrarDocumento);
      document.body.append(visor);
    }
    const pdf = link.dataset.documento === 'pdf';
    const descarga = visor.querySelector('a');
    descarga.hidden = !pdf;
    descarga.href = link.href;
    visor.querySelector('strong').textContent = link.textContent.trim();
    const contenido = visor.querySelector('.g-app-documento-contenido');
    contenido.textContent = 'Cargando documento…';
    const estaApertura = ++apertura;
    scrollPrevio = document.body.classList.contains('g-sin-scroll');
    document.body.classList.add('g-sin-scroll');
    visor.showModal();
    if (!pdf) {
      const pagina = document.createElement('iframe');
      pagina.src = link.href;
      pagina.title = link.textContent.trim();
      contenido.replaceChildren(pagina);
      return;
    }
    try {
      const pdfjs = await import('/static/vendor/pdfjs/pdf.min.mjs');
      if (estaApertura !== apertura) return;
      pdfjs.GlobalWorkerOptions.workerSrc = '/static/vendor/pdfjs/pdf.worker.min.mjs';
      cargaPdf = pdfjs.getDocument(link.href);
      const documento = await cargaPdf.promise;
      if (estaApertura !== apertura) return;
      contenido.replaceChildren();
      for (let n = 1; n <= documento.numPages; n++) {
        const pagina = await documento.getPage(n);
        if (estaApertura !== apertura) return;
        const original = pagina.getViewport({ scale: 1 });
        const ancho = Math.min(contenido.clientWidth - 32, 1000);
        const escala = ancho / original.width * Math.min(devicePixelRatio || 1, 2);
        const vista = pagina.getViewport({ scale: escala });
        const canvas = document.createElement('canvas');
        canvas.width = Math.ceil(vista.width);
        canvas.height = Math.ceil(vista.height);
        canvas.setAttribute('role', 'img');
        canvas.setAttribute('aria-label', `Página ${n} de ${documento.numPages}`);
        contenido.append(canvas);
        await pagina.render({ canvasContext: canvas.getContext('2d'), viewport: vista }).promise;
        if (estaApertura !== apertura) return;
      }
    } catch (error) {
      if (estaApertura === apertura) contenido.textContent = 'No se pudo abrir el documento. Revisá la conexión e intentá de nuevo.';
    }
  });
})();
