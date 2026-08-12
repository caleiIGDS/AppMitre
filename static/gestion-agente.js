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

  let imagenSeleccionada = null;
  let enviando = false;

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
          messagesDiv.innerHTML = `
            <div class="agente-welcome">
              <div class="agente-welcome-icon">🤖</div>
              <div class="agente-welcome-text">
                <strong>¡Hola!</strong><br>
                Preguntá sobre horarios, recursos, préstamos o cualquier otra cosa.
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

  if (imageFile) {
    imageFile.addEventListener('change', function(e) {
      const file = e.target.files[0];
      if (!file) return;

      imagePreview.textContent = '⏳ preparando…';
      imagePreview.classList.add('active');

      achicarImagen(file).then(function(dataUrl) {
        imagenSeleccionada = dataUrl;
        imagePreview.textContent = '✓ ' + file.name.substring(0, 20);
        imagePreview.classList.add('active');
      }).catch(function() {
        imagenSeleccionada = null;
        imagePreview.textContent = '✕ no se pudo leer';
        imageFile.value = '';
      });
    });
  }

  // Enviar mensaje
  function enviarMensaje() {
    if (enviando) return;

    const mensaje = inputField.value.trim();
    // Una foto sola vale como mensaje: sacan la etiqueta y la mandan sin escribir nada.
    if (!mensaje && !imagenSeleccionada) return;

    limpiarBienvenida();
    // Un botón de confirmar de un mensaje anterior deja de valer: si el usuario siguió
    // escribiendo, lo más probable es que quiera cambiar algo, no guardar eso de antes.
    quitarConfirmaciones();
    agregarMensaje(mensaje, 'user', imagenSeleccionada);

    // Preparar payload
    const payload = { mensaje };
    if (imagenSeleccionada) {
      payload.imagen = imagenSeleccionada;
    }

    // Limpiar UI. Lo de la imagen puede no existir: sin `agente.vision` el template no
    // pinta el botón ni el input (ver _agente_chat_core.html).
    inputField.value = '';
    inputField.style.height = 'auto';  // deshacer el auto-resize del textarea
    imagenSeleccionada = null;
    if (imagePreview) {
      imagePreview.textContent = '';
      imagePreview.classList.remove('active');
    }
    if (imageFile) imageFile.value = '';

    // Mostrar loader
    agregarMensaje('', 'loading');

    enviando = true;
    sendBtn.disabled = true;

    fetch('/agente/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
      .then(response => {
        if (!response.ok) {
          // 401 = se venció la sesión; 403 = el acceso existe pero no alcanza. Sin este
          // caso el usuario vería un "Error HTTP: 403" pelado y no sabría qué hacer.
          if (response.status === 401) {
            throw new Error('Se cerró la sesión. Recargá la página para volver a entrar.');
          }
          if (response.status === 403) {
            throw new Error('Este acceso no puede hacer eso.');
          }
          throw new Error('Error HTTP: ' + response.status);
        }
        return response.json();
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

  // Agregar mensaje al chat. `imagenUrl` (opcional, solo mensajes del usuario) pinta la
  // foto adjunta como miniatura, clickeable para verla entera.
  function agregarMensaje(texto, tipo, imagenUrl) {
    const msgDiv = document.createElement('div');

    if (tipo === 'loading') {
      msgDiv.className = 'agente-message agente-message-loading';
      msgDiv.innerHTML = '<div class="agente-loader"><span></span><span></span><span></span></div><span>Pensando...</span>';
    } else if (tipo === 'assistant') {
      msgDiv.className = 'agente-message agente-message-' + tipo;
      msgDiv.innerHTML = renderMarkdown(texto);
    } else {
      msgDiv.className = 'agente-message agente-message-' + tipo;
      if (imagenUrl) {
        const link = document.createElement('a');
        link.href = imagenUrl;
        link.target = '_blank';
        link.rel = 'noopener';
        const img = document.createElement('img');
        img.src = imagenUrl;
        img.className = 'agente-message-image';
        img.alt = 'Imagen adjunta';
        link.appendChild(img);
        msgDiv.appendChild(link);
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
  // `confirmaciones` con el token de cada ficha pendiente y acá se pinta un botón por
  // ficha. Al tocarlo, /confirmar guarda directo desde lo que quedó en la sesión — sin
  // pasar por el modelo, así que es instantáneo, gratis, y guarda exactamente lo que el
  // usuario leyó.
  //
  // Es una LISTA y no una sola: "creá a Pablo y a Ezequiel" arma dos fichas en un turno y
  // antes solo se pintaba el botón de la última, así que la otra quedaba viva en el
  // servidor sin forma de guardarla y el usuario creía que se habían dado de alta las dos.

  function quitarConfirmaciones() {
    messagesDiv.querySelectorAll('.agente-confirm').forEach(el => el.remove());
  }

  function textoBoton(conf) {
    // El nombre va en el botón, no al lado: con dos o tres botones seguidos, "Guardar
    // persona" repetido no dice cuál es cuál.
    return '✅ ' + (conf.etiqueta || 'Guardar') + (conf.nombre ? ': ' + conf.nombre : '');
  }

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
          btn.remove();
          agregarMensaje(data.respuesta || 'Sin respuesta', data.ok ? 'assistant' : 'error');
          // Si quedan altas sin confirmar, la caja se remonta al final para que sus
          // botones sigan abajo del "✅ Guardado" y no queden perdidos más arriba.
          if (caja.querySelector('.agente-confirm-btn')) {
            messagesDiv.appendChild(caja);
          } else {
            caja.remove();
          }
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

  function agregarConfirmaciones(lista) {
    if (!lista || !lista.length) return;

    const caja = document.createElement('div');
    caja.className = 'agente-confirm';

    const nota = document.createElement('span');
    nota.className = 'agente-confirm-nota';
    nota.textContent = lista.length > 1
      ? 'confirmá las que estén bien, una por una — o seguí escribiendo para cambiar algo'
      : 'o seguí escribiendo para cambiar algo';

    lista.forEach(conf => caja.appendChild(botonConfirmar(conf, caja)));
    caja.appendChild(nota);
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
                                                  m.imagen));
        // Las altas que quedaron sin confirmar recuperan su botón: si no, cambiar de
        // página dejaba las fichas vivas en el servidor y sin forma de darles OK.
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
