// gestion-agente.js — Asistente IA
//
// Sirve a las DOS vistas del chat, que comparten markup (_agente_chat_core.html):
//   - el widget flotante que se abre desde el header en /gestion o /historia
//   - la pestaña a pantalla completa en /agente
// Nunca se renderizan juntas (base.html omite el widget en esa pestaña), así que los
// getElementById de abajo siempre encuentran uno solo. Los elementos exclusivos del
// widget (toggle, cerrar) pueden no existir: por eso cada listener va guardado. Lo mismo
// con los tres de la imagen (botón, input, chip), que sin `agente.vision` no se pintan.

document.addEventListener('DOMContentLoaded', function() {
  const widget = document.getElementById('agente-widget');
  const toggleBtn = document.getElementById('agente-toggle-btn');
  const closeBtn = document.getElementById('agente-close-btn');
  const resetBtn = document.getElementById('agente-reset-btn');
  const messagesDiv = document.getElementById('agente-messages');
  const inputField = document.getElementById('agente-input');
  const sendBtn = document.getElementById('agente-send-btn');
  const imageBtn = document.getElementById('agente-image-btn');
  const imageFile = document.getElementById('agente-image-file');
  const imagePreview = document.getElementById('agente-image-preview');

  if (!messagesDiv || !inputField || !sendBtn) return;

  // Las fotos van de a tandas: se mandan varias y sale una ficha por cada una, que después
  // se revisan de a una antes de guardar nada (ver "Botones de revisión del lote").
  let imagenesSeleccionadas = [];
  let enviando = false;
  // Las fichas pendientes tal como las devuelve el server, para saber si hay un lote abierto.
  let loteAbierto = [];

  // Pantalla táctil (celular/tablet): no se enfoca el campo solo, que abriría el teclado
  // de entrada. Enter envía en todos lados (ver listener de keydown).
  const esTactil = window.matchMedia('(pointer: coarse)').matches;

  function enfocarInput() {
    if (!esTactil) inputField.focus();
  }

  function irAlFinal() {
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
  }

  // Al abrirse el teclado el viewport se achica y el último mensaje queda tapado.
  // visualViewport avisa de ese resize (window.onresize no dispara en iOS).
  if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', irAlFinal);
  }
  inputField.addEventListener('focus', function() {
    setTimeout(irAlFinal, 250);  // después de que el teclado terminó de subir
  });

  // Limpiar bienvenida cuando se escriba algo
  function limpiarBienvenida() {
    const welcome = messagesDiv.querySelector('.agente-welcome');
    if (welcome) {
      welcome.remove();
    }
  }

  // Abrir/cerrar widget — persistir estado en localStorage
  function guardarEstadoWidget(abierto) {
    localStorage.setItem('agente-widget-open', abierto ? 'true' : 'false');
  }

  function restaurarEstadoWidget() {
    // Restaurar el estado guardado cuando el widget existe en el DOM.
    // Si el widget no está presente (ej: en /agente), la próxima vez
    // que se renderice (al volver a otra página) lo restaurará.
    const abierto = localStorage.getItem('agente-widget-open') === 'true';
    if (widget) {
      widget.hidden = !abierto;
    }
  }

  if (toggleBtn) {
    toggleBtn.addEventListener('click', function(e) {
      e.preventDefault();
      widget.hidden = !widget.hidden;
      guardarEstadoWidget(!widget.hidden);
      if (!widget.hidden) {
        enfocarInput();
      }
    });
  }

  if (closeBtn) {
    closeBtn.addEventListener('click', function(e) {
      e.preventDefault();
      widget.hidden = true;
      guardarEstadoWidget(false);
    });
  }

  // Restaurar estado del widget al cargar la página
  restaurarEstadoWidget();

  if (resetBtn) {
    resetBtn.addEventListener('click', function(e) {
      e.preventDefault();
      if (enviando) return;

      fetch('/agente/reset', { method: 'POST' })
        .catch(() => {})
        .finally(() => {
          // El server borró las fichas y sus fotos: si el lote quedara marcado acá, el
          // próximo turno pintaría botones de fichas que ya no existen.
          loteAbierto = [];
          messagesDiv.innerHTML = `
            <div class="agente-welcome">
              <div class="agente-welcome-icon">🤖</div>
              <div class="agente-welcome-text">
                <strong>¡Hola!</strong><br>
                Preguntá sobre horarios, recursos, historia de la escuela o cualquier otra cosa.
              </div>
            </div>`;
          enfocarInput();
        });
    });
  }

  // Manejo de imágenes
  //
  // La foto se achica ANTES de mandarla. Una foto de celular sale de 3-8 MB y en base64
  // pesa un tercio más: no entra en el límite de la API de visión y encima tarda una
  // eternidad por el wifi de la escuela. 1568 px de lado largo es lo que el modelo llega
  // a aprovechar; más grande lo reescala él y solo se paga el envío. Alcanza de sobra
  // para leer la letra chica de un datasheet.
  const IMAGEN_LADO_MAX = 1568;
  const IMAGEN_CALIDAD = 0.85;

  function achicarImagen(file) {
    return new Promise(function(resolve, reject) {
      const reader = new FileReader();
      reader.onerror = reject;
      reader.onload = function(evt) {
        const dataUrl = evt.target.result;
        const img = new Image();
        // Si el navegador no puede decodificarla (HEIC de iPhone, formato raro), se manda
        // tal cual: que decida el servidor, mejor que perder la foto.
        img.onerror = function() { resolve(dataUrl); };
        img.onload = function() {
          const lado = Math.max(img.width, img.height);
          if (lado <= IMAGEN_LADO_MAX) {
            resolve(dataUrl);
            return;
          }
          const escala = IMAGEN_LADO_MAX / lado;
          const canvas = document.createElement('canvas');
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

  if (imageBtn) {
    imageBtn.addEventListener('click', function(e) {
      e.preventDefault();
      imageFile.click();
    });
  }

  // Cuántas fotos se pueden mandar de una. Tiene que coincidir con db.FOTOS_MAX: acá es
  // para avisar antes de subirlas (en el wifi de la escuela, subir diez para que el server
  // descarte dos es un rato perdido), pero el corte que vale es el del server.
  const FOTOS_MAX = 8;

  function textoChip() {
    if (!imagenesSeleccionadas.length) return '';
    return imagenesSeleccionadas.length === 1
      ? '✓ 1 foto (tocá para sacarla)'
      : '✓ ' + imagenesSeleccionadas.length + ' fotos (tocá para sacarlas)';
  }

  function limpiarImagenes() {
    imagenesSeleccionadas = [];
    if (imagePreview) {
      imagePreview.textContent = '';
      imagePreview.classList.remove('active');
    }
    if (imageFile) imageFile.value = '';
  }

  // El chip es también el botón de deshacer: se eligieron seis fotos de la galería y salió
  // una de más, y sin esto la única salida era mandar el mensaje o recargar la página.
  if (imagePreview) {
    imagePreview.addEventListener('click', function() {
      if (imagenesSeleccionadas.length) limpiarImagenes();
    });
  }

  if (imageFile) {
    imageFile.addEventListener('change', function(e) {
      const files = Array.from(e.target.files || []);
      if (!files.length) return;

      const entran = files.slice(0, FOTOS_MAX);
      const sobran = files.length - entran.length;

      imagePreview.textContent = '⏳ preparando ' + entran.length + '…';
      imagePreview.classList.add('active');

      // Todas en paralelo: son canvas locales, y de a una se hace notar con ocho.
      Promise.all(entran.map(achicarImagen)).then(function(dataUrls) {
        imagenesSeleccionadas = dataUrls;
        imagePreview.textContent = textoChip()
          + (sobran ? ' — quedaron afuera ' + sobran + ', entran ' + FOTOS_MAX : '');
        imagePreview.classList.add('active');
      }).catch(function() {
        imagenesSeleccionadas = [];
        imagePreview.textContent = '✕ no se pudo leer';
        imageFile.value = '';
      });
    });
  }

  // Cambia el texto del loader por lo que el server dice que está haciendo ("buscando el
  // horario", "armando la ficha"). Si el loader ya no está —el turno terminó— no hace nada.
  function actualizarPaso(texto) {
    const etiqueta = messagesDiv.querySelector('.agente-message-loading .agente-loader-texto');
    if (etiqueta) etiqueta.textContent = texto.charAt(0).toUpperCase() + texto.slice(1) + '...';
  }

  // Lee la respuesta de /agente/chat/stream y devuelve el payload del evento `fin`, que es
  // el mismo objeto que /agente/chat contesta de una sola pieza. Los `paso` intermedios van
  // al loader por `onPaso`.
  //
  // Se parsea a mano en vez de usar EventSource porque EventSource solo hace GET, y acá hay
  // que mandar el mensaje (y hasta ocho fotos en base64) en el body de un POST.
  async function leerStream(response, onPaso) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let payload = null;

    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // Los eventos van separados por una línea en blanco. Lo que quede después del último
      // separador es un evento a medio llegar: se guarda para la próxima vuelta.
      const bloques = buffer.split('\n\n');
      buffer = bloques.pop();

      for (const bloque of bloques) {
        const linea = bloque.split('\n').find(l => l.startsWith('data:'));
        if (!linea) continue;
        let evento;
        try {
          evento = JSON.parse(linea.slice(5));
        } catch (e) {
          continue;  // un evento cortado no puede tirar abajo el turno entero
        }
        if (evento.tipo === 'paso') onPaso(evento.texto);
        else if (evento.tipo === 'error') throw new Error(evento.error);
        else if (evento.tipo === 'fin') payload = evento;
      }
    }

    // Sin `fin` el turno no terminó: se cortó la conexión en el medio. Decirlo es mejor que
    // pintar un mensaje vacío, que se lee como si el asistente no hubiera tenido nada que decir.
    if (!payload) throw new Error('Se cortó la conexión antes de que llegara la respuesta.');
    return payload;
  }

  // Enviar mensaje
  function enviarMensaje() {
    if (enviando) return;

    const mensaje = inputField.value.trim();
    // Una foto sola vale como mensaje: sacan la etiqueta y la mandan sin escribir nada.
    if (!mensaje && !imagenesSeleccionadas.length) return;

    limpiarBienvenida();
    // El botón verde de una ficha sola deja de valer: si el usuario siguió escribiendo, lo
    // más probable es que quiera cambiar algo, no guardar eso de antes. Un LOTE en cambio se
    // deja en pantalla: la revisión de ocho fichas está guardada en el server y no se puede
    // perder porque el usuario haya preguntado otra cosa en el medio (se repinta al llegar
    // la respuesta, con su estado).
    if (loteAbierto.length < 2) quitarConfirmaciones();
    agregarMensaje(mensaje, 'user', imagenesSeleccionadas);

    // Preparar payload
    const payload = { mensaje };
    if (imagenesSeleccionadas.length) {
      payload.imagenes = imagenesSeleccionadas;
    }

    // Limpiar UI. Lo de la imagen puede no existir: sin `agente.vision` el template no
    // pinta el botón ni el input (ver _agente_chat_core.html).
    inputField.value = '';
    inputField.style.height = 'auto';  // deshacer el auto-resize del textarea
    limpiarImagenes();

    // Mostrar loader
    agregarMensaje('', 'loading');

    enviando = true;
    sendBtn.disabled = true;

    fetch('/agente/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
      .then(response => {
        if (!response.ok) {
          // 401 = se venció la sesión; 403 = el acceso existe pero no alcanza. Sin este
          // caso el usuario vería un "Error HTTP: 403" pelado y no sabría qué hacer.
          // Los errores llegan como JSON normal: el stream recién arranca si el turno arrancó.
          if (response.status === 401) {
            throw new Error('Se cerró la sesión. Recargá la página para volver a entrar.');
          }
          if (response.status === 403) {
            throw new Error('Este acceso no puede hacer eso.');
          }
          throw new Error('Error HTTP: ' + response.status);
        }
        return leerStream(response, actualizarPaso);
      })
      .then(data => {
        // Remover loader
        const loader = messagesDiv.querySelector('.agente-message-loading');
        if (loader) loader.remove();

        if (data.error) {
          agregarMensaje('Error: ' + data.error, 'error');
        } else {
          agregarMensaje(data.respuesta, 'assistant');
          agregarConfirmaciones(data.confirmaciones);
        }
      })
      .catch(error => {
        // Remover loader
        const loader = messagesDiv.querySelector('.agente-message-loading');
        if (loader) loader.remove();

        agregarMensaje('Error de conexión: ' + error.message, 'error');
      })
      .finally(() => {
        enviando = false;
        sendBtn.disabled = false;
        enfocarInput();
      });
  }

  // Event listeners
  if (sendBtn) {
    sendBtn.addEventListener('click', enviarMensaje);
  }

  inputField.addEventListener('keydown', function(e) {
    // Enter envía (también en táctil); Shift+Enter hace salto de línea.
    // `isComposing`: con IME (acentos, teclados asiáticos) el Enter que confirma el
    // candidato no debe mandar el mensaje.
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      enviarMensaje();
    }
  });

  inputField.addEventListener('input', function() {
    // Auto-resize del textarea, hasta el max-height que fije el CSS (que en mobile
    // es más alto que en desktop — por eso se lee de ahí y no está hardcodeado).
    this.style.height = 'auto';
    const tope = parseInt(getComputedStyle(this).maxHeight, 10) || 80;
    this.style.height = Math.min(this.scrollHeight, tope) + 'px';
  });

  // Agregar mensaje al chat. `imagenes` (opcional, solo mensajes del usuario) pinta las
  // fotos adjuntas como miniaturas, clickeables para verlas enteras. Acepta una sola URL
  // suelta además de la lista, que es como la llama el historial viejo.
  function agregarMensaje(texto, tipo, imagenes) {
    const msgDiv = document.createElement('div');
    const urls = !imagenes ? [] : (Array.isArray(imagenes) ? imagenes : [imagenes]);

    if (tipo === 'loading') {
      msgDiv.className = 'agente-message agente-message-loading';
      msgDiv.innerHTML = '<div class="agente-loader"><span></span><span></span><span></span></div><span class="agente-loader-texto">Pensando...</span>';
    } else if (tipo === 'assistant') {
      msgDiv.className = 'agente-message agente-message-' + tipo;
      msgDiv.innerHTML = renderMarkdown(texto);
    } else {
      msgDiv.className = 'agente-message agente-message-' + tipo;
      if (urls.length) {
        // Con varias van en grilla y numeradas: el asistente las nombra por número ("la 3
        // no la pude leer") y sin el número no hay forma de saber a cuál se refiere.
        const galeria = document.createElement('div');
        galeria.className = 'agente-message-fotos';
        if (urls.length > 1) galeria.classList.add('is-multiple');
        urls.forEach(function(url, i) {
          const link = document.createElement('a');
          link.href = url;
          link.target = '_blank';
          link.rel = 'noopener';
          link.className = 'agente-message-foto';
          const img = document.createElement('img');
          img.src = url;
          img.className = 'agente-message-image';
          img.alt = 'Imagen adjunta ' + (i + 1);
          link.appendChild(img);
          if (urls.length > 1) {
            const num = document.createElement('span');
            num.className = 'agente-message-foto-num';
            num.textContent = i + 1;
            link.appendChild(num);
          }
          galeria.appendChild(link);
        });
        msgDiv.appendChild(galeria);
      }
      if (texto) {
        // textContent y no innerHTML: es texto del usuario, no se interpreta como HTML.
        const linea = document.createElement('div');
        linea.textContent = texto;
        msgDiv.appendChild(linea);
      }
    }

    messagesDiv.appendChild(msgDiv);
    irAlFinal();
  }

  // --- Botones de confirmar alta ---
  // El alta en el catálogo no se confirma escribiendo "sí": el backend manda
  // `confirmaciones` con el token de cada ficha pendiente y acá se pintan sus botones.
  //
  // Hay DOS circuitos, según cuántas fichas queden:
  //
  //   1 ficha  → el botón verde de siempre. /confirmar guarda directo desde lo que quedó en
  //              la sesión, sin pasar por el modelo: instantáneo, gratis, y guarda
  //              exactamente lo que el usuario leyó. Un solo click, que es lo que
  //              corresponde al caso de siempre.
  //
  //   2 o más  → el LOTE. Cada ficha se marca (está bien / corregir + qué está mal / no va)
  //              con /revisar, que NO escribe nada, y recién cuando están todas revisadas se
  //              habilita "Guardar" → /lote, que guarda las aprobadas y le manda al
  //              asistente las acotaciones juntas para que rearme esas fichas. Es el flujo
  //              de cargar una estantería entera: con el botón que guarda al toque había que
  //              decidir de a una y sin vuelta atrás, y pedir una corrección se llevaba
  //              puesto lo ya revisado.
  //
  // Es una LISTA y no una sola ficha porque un turno puede dar de alta varias cosas ("creá a
  // Pablo y a Ezequiel", u ocho fotos de etiquetas). Antes solo se pintaba el botón de la
  // última, así que las otras quedaban vivas en el servidor sin forma de guardarlas y el
  // usuario creía que se habían dado de alta todas.

  function quitarConfirmaciones() {
    messagesDiv.querySelectorAll('.agente-confirm').forEach(el => el.remove());
  }

  function textoBoton(conf) {
    // El nombre va en el botón, no al lado: con dos o tres botones seguidos, "Guardar
    // persona" repetido no dice cuál es cuál.
    return '✅ ' + (conf.etiqueta || 'Guardar') + (conf.nombre ? ': ' + conf.nombre : '');
  }

  // --- Circuito de una sola ficha: guardar al toque ---

  function botonConfirmar(conf, caja) {
    const btn = document.createElement('button');
    btn.className = 'agente-confirm-btn';
    btn.textContent = textoBoton(conf);

    btn.addEventListener('click', function() {
      if (enviando) return;
      enviando = true;
      btn.disabled = true;
      btn.textContent = 'Guardando…';

      fetch('/agente/confirmar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: conf.token })
      })
        .then(r => r.json().then(data => ({ ok: r.ok, data })))
        .then(({ data }) => {
          caja.remove();
          agregarMensaje(data.respuesta || 'Sin respuesta', data.ok ? 'assistant' : 'error');
          // Si quedaron altas sin guardar, vuelven a pintarse abajo del "✅ Guardado": si
          // se quedaran arriba, el usuario no las ve y las da por hechas.
          agregarConfirmaciones(data.confirmaciones);
          irAlFinal();
        })
        .catch(error => {
          btn.disabled = false;
          btn.textContent = textoBoton(conf);
          agregarMensaje('Error de conexión: ' + error.message, 'error');
        })
        .finally(() => {
          enviando = false;
          sendBtn.disabled = false;
        });
    });

    return btn;
  }

  // --- Circuito del lote: revisar primero, guardar al final ---

  const ETIQUETA_ESTADO = {
    ok: '✅ va',
    observada: '✏️ a corregir',
    descartada: '🗑️ no va'
  };

  // Marca una ficha sin escribir nada en el inventario. El estado vive en el server, así
  // que sobrevive a recargar la página o a mandar otro mensaje en el medio.
  //
  // No se pisa `loteAbierto` con lo que devuelve: es el MISMO array que quedó en `caja._fichas`,
  // y reemplazarlo por objetos nuevos dejaría a la barra contando sobre una copia vieja. Acá
  // se muta la ficha que cambió y con eso alcanza — el server ya tiene la verdad.
  //
  // Las marcas se encolan de a una (`colaRevision`). Cada /revisar es un lee-modifica-escribe
  // sobre la misma fila de la conversación, así que dos clicks rápidos en fichas distintas
  // pueden pisarse y perder una marca: el usuario la ve marcada y el server no.
  let colaRevision = Promise.resolve();

  function revisarFicha(token, estado, nota) {
    const pedido = colaRevision.then(() => fetch('/agente/revisar', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: token, estado: estado, nota: nota || '' })
    }).then(r => r.json()));
    // La cola no se corta si uno falla; el error lo recibe igual quien llamó.
    colaRevision = pedido.catch(() => {});
    return pedido;
  }

  function filaRevision(conf, caja) {
    const fila = document.createElement('div');
    fila.className = 'agente-revision';

    const cabecera = document.createElement('div');
    cabecera.className = 'agente-revision-cabecera';

    const nombre = document.createElement('span');
    nombre.className = 'agente-revision-nombre';
    nombre.textContent = (conf.foto ? conf.foto + '. ' : '') + (conf.nombre || 'sin nombre');
    cabecera.appendChild(nombre);

    const marca = document.createElement('span');
    marca.className = 'agente-revision-marca';
    cabecera.appendChild(marca);
    fila.appendChild(cabecera);

    const botones = document.createElement('div');
    botones.className = 'agente-revision-botones';

    // El campo de la acotación vive plegado en la fila: escribir qué está mal no puede
    // obligar a mandar un mensaje suelto, que es justo lo que rompía la revisión.
    const cajaNota = document.createElement('div');
    cajaNota.className = 'agente-revision-nota';
    cajaNota.hidden = true;
    const campo = document.createElement('input');
    campo.type = 'text';
    campo.className = 'agente-revision-input';
    campo.placeholder = '¿qué está mal? (ej: la marca es Makita)';
    campo.value = conf.nota || '';
    const anotar = document.createElement('button');
    anotar.className = 'agente-revision-anotar';
    anotar.textContent = 'Anotar';
    cajaNota.appendChild(campo);
    cajaNota.appendChild(anotar);

    function pintarEstado(estado, nota) {
      fila.classList.remove('is-ok', 'is-observada', 'is-descartada');
      if (estado && estado !== 'pendiente') fila.classList.add('is-' + estado);
      marca.textContent = ETIQUETA_ESTADO[estado] || '';
      botones.querySelectorAll('button').forEach(b => {
        b.setAttribute('aria-pressed', b.dataset.estado === estado ? 'true' : 'false');
      });
      if (estado === 'observada' && nota) {
        marca.textContent = '✏️ ' + nota;
      }
      cajaNota.hidden = estado !== 'observada';
    }

    function marcar(estado, nota) {
      if (enviando) return;
      revisarFicha(conf.token, estado, nota)
        .then(data => {
          if (data.ok === false) {
            agregarMensaje(data.respuesta || 'No se pudo marcar esa ficha', 'error');
            return;
          }
          conf.estado = estado;
          conf.nota = estado === 'observada' ? (nota || '') : '';
          pintarEstado(estado, conf.nota);
          actualizarBarra(caja);
        })
        .catch(error => agregarMensaje('Error de conexión: ' + error.message, 'error'));
    }

    [['ok', '✅ está bien'], ['observada', '✏️ corregir'], ['descartada', '✕ no va']]
      .forEach(function(par) {
        const btn = document.createElement('button');
        btn.className = 'agente-revision-btn agente-revision-' + par[0];
        btn.dataset.estado = par[0];
        btn.textContent = par[1];
        btn.addEventListener('click', function() {
          if (par[0] === 'observada') {
            // Abrir el campo no marca nada todavía: lo que marca es "Anotar", porque una
            // ficha observada sin decir qué está mal no le sirve al asistente.
            cajaNota.hidden = false;
            campo.focus();
            return;
          }
          marcar(par[0], '');
        });
        botones.appendChild(btn);
      });

    anotar.addEventListener('click', function() {
      const nota = campo.value.trim();
      if (!nota) { campo.focus(); return; }
      marcar('observada', nota);
    });
    campo.addEventListener('keydown', function(e) {
      if (e.key === 'Enter' && !e.isComposing) {
        e.preventDefault();
        anotar.click();
      }
    });

    fila.appendChild(botones);
    fila.appendChild(cajaNota);
    pintarEstado(conf.estado || 'pendiente', conf.nota);
    return fila;
  }

  // La barra de abajo: el botón que recién ahí escribe, y cuánto falta para poder tocarlo.
  function actualizarBarra(caja) {
    const barra = caja.querySelector('.agente-lote');
    if (!barra) return;
    const btn = barra.querySelector('.agente-lote-btn');
    const nota = barra.querySelector('.agente-lote-nota');

    const fichas = caja._fichas || [];
    const pendientes = fichas.filter(f => (f.estado || 'pendiente') === 'pendiente').length;
    const aprobadas = fichas.filter(f => f.estado === 'ok').length;
    const acotadas = fichas.filter(f => f.estado === 'observada').length;
    const tachadas = fichas.filter(f => f.estado === 'descartada').length;

    const partes = [];
    if (aprobadas) partes.push('Guardar ' + aprobadas);
    if (acotadas) partes.push('corregir ' + acotadas);
    if (tachadas && !aprobadas && !acotadas) partes.push('descartar ' + tachadas);
    btn.textContent = '📦 ' + (partes.length ? partes.join(' y ') : 'Guardar');

    // Se habilita recién cuando están todas revisadas: la idea del lote es mirar las ocho
    // antes de tocar nada, y con el botón vivo desde el principio es fácil mandar media
    // tanda sin querer.
    btn.disabled = pendientes > 0 || fichas.length === 0;
    nota.textContent = pendientes
      ? 'falta' + (pendientes > 1 ? 'n ' : ' ') + pendientes + ' por revisar'
      : 'nada se guardó todavía — esto lo escribe todo junto';
  }

  function barraLote(caja) {
    const barra = document.createElement('div');
    barra.className = 'agente-lote';

    const btn = document.createElement('button');
    btn.className = 'agente-lote-btn';
    const nota = document.createElement('span');
    nota.className = 'agente-lote-nota';
    barra.appendChild(btn);
    barra.appendChild(nota);

    btn.addEventListener('click', function() {
      if (enviando || btn.disabled) return;
      enviando = true;
      sendBtn.disabled = true;
      btn.disabled = true;
      btn.textContent = 'Guardando…';
      // La segunda vuelta pasa por el modelo y tarda; sin loader parece colgado.
      const hayCorrecciones = (caja._fichas || []).some(f => f.estado === 'observada');
      if (hayCorrecciones) agregarMensaje('', 'loading');

      fetch('/agente/lote', { method: 'POST', headers: { 'Content-Type': 'application/json' } })
        .then(r => r.json().then(data => ({ ok: r.ok, data })))
        .then(({ ok, data }) => {
          const loader = messagesDiv.querySelector('.agente-message-loading');
          if (loader) loader.remove();
          // Si falló, el lote SIGUE ahí: no se borra la revisión que el usuario ya hizo por
          // un error del server. Sólo se rehabilita el botón y se cuenta qué pasó.
          if (!ok) {
            agregarMensaje(data.respuesta || 'No se pudo guardar el lote', 'error');
            actualizarBarra(caja);
            irAlFinal();
            return;
          }
          caja.remove();
          agregarMensaje(data.respuesta || 'Sin respuesta', 'assistant');
          agregarConfirmaciones(data.confirmaciones);
          irAlFinal();
        })
        .catch(error => {
          const loader = messagesDiv.querySelector('.agente-message-loading');
          if (loader) loader.remove();
          agregarMensaje('Error de conexión: ' + error.message, 'error');
          actualizarBarra(caja);
        })
        .finally(() => {
          enviando = false;
          sendBtn.disabled = false;
        });
    });

    return barra;
  }

  function agregarConfirmaciones(lista) {
    quitarConfirmaciones();
    loteAbierto = lista || [];
    if (!loteAbierto.length) return;

    const caja = document.createElement('div');
    caja.className = 'agente-confirm';

    if (loteAbierto.length === 1) {
      const nota = document.createElement('span');
      nota.className = 'agente-confirm-nota';
      nota.textContent = 'o seguí escribiendo para cambiar algo';
      caja.appendChild(botonConfirmar(loteAbierto[0], caja));
      caja.appendChild(nota);
    } else {
      caja.classList.add('agente-confirm-lote');
      caja._fichas = loteAbierto;
      const titulo = document.createElement('span');
      titulo.className = 'agente-confirm-nota';
      titulo.textContent = 'Revisá las ' + loteAbierto.length
        + ' fichas: marcá cuáles van y cuáles hay que corregir. No se guarda nada hasta el final.';
      caja.appendChild(titulo);
      loteAbierto.forEach(conf => caja.appendChild(filaRevision(conf, caja)));
      caja.appendChild(barraLote(caja));
      actualizarBarra(caja);
    }

    messagesDiv.appendChild(caja);
    irAlFinal();
  }

  // --- Repintar la conversación guardada ---
  // La conversación vive en gestion.db, así que el servidor la recuerda al navegar entre
  // páginas — pero el chat se dibuja de cero en cada carga. Sin esto el historial estaba
  // ahí (el agente lo usaba de contexto) y el usuario no lo veía, que parecía un bug.

  function cargarHistorial() {
    // En el login el widget existe pero no hay sesión: pedir el historial daría 401.
    if (widget && !toggleBtn) return;

    fetch('/agente/historial')
      .then(r => (r.ok ? r.json() : null))
      .then(data => {
        if (!data || !data.mensajes || !data.mensajes.length) return;
        limpiarBienvenida();
        data.mensajes.forEach(m => agregarMensaje(m.texto, m.rol === 'user' ? 'user' : 'assistant',
                                                  m.imagenes));
        // Las altas sin guardar recuperan sus botones, y con el estado de revisión que
        // tenían: si no, cambiar de página dejaba las fichas vivas en el servidor y sin
        // forma de darles OK — y con un lote a medio revisar, había que revisarlo de nuevo.
        agregarConfirmaciones(data.confirmaciones);
      })
      .catch(() => {});  // sin historial el chat igual funciona: no vale molestar con un error
  }

  cargarHistorial();

  // En la pestaña dedicada arrancamos con el cursor puesto (en desktop).
  if (!widget) enfocarInput();

  // --- Renderizado de markdown liviano (negrita, listas, tablas) ---

  function escapeHtml(str) {
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function inlineMarkdown(str) {
    let s = escapeHtml(str);
    s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>');
    s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
    return s;
  }

  function partirFilaTabla(linea) {
    const celdas = linea.trim().split('|').map(c => c.trim());
    if (celdas.length && celdas[0] === '') celdas.shift();
    if (celdas.length && celdas[celdas.length - 1] === '') celdas.pop();
    return celdas;
  }

  function renderMarkdown(texto) {
    const lineas = (texto || '').replace(/\r\n/g, '\n').split('\n');
    let html = '';
    let listaActual = null; // 'ul' | 'ol'

    function cerrarLista() {
      if (listaActual) {
        html += '</' + listaActual + '>';
        listaActual = null;
      }
    }

    let i = 0;
    while (i < lineas.length) {
      const linea = lineas[i];
      const trimmed = linea.trim();

      // Tabla: fila con | seguida de fila separadora |---|---|
      if (trimmed.startsWith('|') && lineas[i + 1] && /^[\s|:-]+$/.test(lineas[i + 1].trim()) && lineas[i + 1].includes('-')) {
        cerrarLista();
        const headers = partirFilaTabla(trimmed);
        html += '<div class="agente-table-wrap"><table><thead><tr>';
        headers.forEach(h => { html += '<th>' + inlineMarkdown(h) + '</th>'; });
        html += '</tr></thead><tbody>';
        i += 2;
        while (i < lineas.length && lineas[i].trim().startsWith('|')) {
          const celdas = partirFilaTabla(lineas[i]);
          html += '<tr>';
          celdas.forEach(c => { html += '<td>' + inlineMarkdown(c) + '</td>'; });
          html += '</tr>';
          i++;
        }
        html += '</tbody></table></div>';
        continue;
      }

      // Lista numerada
      const matchOl = trimmed.match(/^(\d+)[.)]\s+(.*)$/);
      if (matchOl) {
        if (listaActual !== 'ol') { cerrarLista(); html += '<ol>'; listaActual = 'ol'; }
        html += '<li>' + inlineMarkdown(matchOl[2]) + '</li>';
        i++;
        continue;
      }

      // Lista con guiones/asteriscos
      const matchUl = trimmed.match(/^[-*]\s+(.*)$/);
      if (matchUl) {
        if (listaActual !== 'ul') { cerrarLista(); html += '<ul>'; listaActual = 'ul'; }
        html += '<li>' + inlineMarkdown(matchUl[1]) + '</li>';
        i++;
        continue;
      }

      cerrarLista();

      if (trimmed === '') {
        i++;
        continue;
      }

      // Encabezados (#, ##, ###...) -> párrafo destacado
      const matchH = trimmed.match(/^#{1,6}\s+(.*)$/);
      if (matchH) {
        html += '<p><strong>' + inlineMarkdown(matchH[1]) + '</strong></p>';
        i++;
        continue;
      }

      html += '<p>' + inlineMarkdown(trimmed) + '</p>';
      i++;
    }
    cerrarLista();
    return html || '';
  }
});
