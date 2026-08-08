// gestion-agente.js — Asistente IA
//
// Sirve a las DOS vistas del chat, que comparten markup (_agente_chat_core.html):
//   - el widget flotante que se abre desde el header en cualquier página de /gestion
//   - la pestaña a pantalla completa en /gestion/agente
// Nunca se renderizan juntas (base.html omite el widget en esa pestaña), así que los
// getElementById de abajo siempre encuentran uno solo. Los elementos exclusivos del
// widget (toggle, cerrar) pueden no existir: por eso cada listener va guardado.

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
  let imagenNombre = null;
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

  // Abrir/cerrar widget
  if (toggleBtn) {
    toggleBtn.addEventListener('click', function(e) {
      e.preventDefault();
      widget.hidden = !widget.hidden;
      if (!widget.hidden) {
        enfocarInput();
      }
    });
  }

  if (closeBtn) {
    closeBtn.addEventListener('click', function(e) {
      e.preventDefault();
      widget.hidden = true;
    });
  }

  if (resetBtn) {
    resetBtn.addEventListener('click', function(e) {
      e.preventDefault();
      if (enviando) return;
      if (!confirm('¿Reiniciar la conversación? Se perderá el contexto actual.')) return;

      fetch('/gestion/agente/reset', { method: 'POST' })
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
  if (imageBtn) {
    imageBtn.addEventListener('click', function(e) {
      e.preventDefault();
      imageFile.click();
    });
  }

  if (imageFile) {
    imageFile.addEventListener('change', function(e) {
      const file = e.target.files[0];
      if (file) {
        const reader = new FileReader();
        reader.onload = function(evt) {
          imagenSeleccionada = evt.target.result;
          imagenNombre = file.name;
          imagePreview.textContent = '✓ ' + file.name.substring(0, 20);
          imagePreview.classList.add('active');
        };
        reader.readAsDataURL(file);
      }
    });
  }

  // Enviar mensaje
  function enviarMensaje() {
    if (enviando) return;

    const mensaje = inputField.value.trim();
    if (!mensaje) return;

    limpiarBienvenida();
    // Un botón de confirmar de un mensaje anterior deja de valer: si el usuario siguió
    // escribiendo, lo más probable es que quiera cambiar algo, no guardar eso de antes.
    quitarConfirmaciones();
    agregarMensaje(mensaje, 'user');

    // Preparar payload
    const payload = { mensaje };
    if (imagenSeleccionada) {
      payload.imagen = imagenSeleccionada;
    }

    // Limpiar UI
    inputField.value = '';
    inputField.style.height = 'auto';  // deshacer el auto-resize del textarea
    imagenSeleccionada = null;
    imagenNombre = null;
    imagePreview.textContent = '';
    imagePreview.classList.remove('active');
    imageFile.value = '';

    // Mostrar loader
    agregarMensaje('', 'loading');

    enviando = true;
    sendBtn.disabled = true;

    fetch('/gestion/agente/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
      .then(response => {
        if (!response.ok) {
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
          if (data.confirmacion) agregarConfirmacion(data.confirmacion);
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

  // Agregar mensaje al chat
  function agregarMensaje(texto, tipo) {
    const msgDiv = document.createElement('div');

    if (tipo === 'loading') {
      msgDiv.className = 'agente-message agente-message-loading';
      msgDiv.innerHTML = '<div class="agente-loader"><span></span><span></span><span></span></div><span>Pensando...</span>';
    } else if (tipo === 'assistant') {
      msgDiv.className = 'agente-message agente-message-' + tipo;
      msgDiv.innerHTML = renderMarkdown(texto);
    } else {
      msgDiv.className = 'agente-message agente-message-' + tipo;
      msgDiv.textContent = texto;
    }

    messagesDiv.appendChild(msgDiv);
    irAlFinal();
  }

  // --- Botón de confirmar alta ---
  // El alta en el catálogo no se confirma escribiendo "sí": el backend manda `confirmacion`
  // con el token de la ficha que se acaba de mostrar y acá se pinta el botón. Al tocarlo,
  // /confirmar guarda directo desde lo que quedó en la sesión — sin pasar por el modelo,
  // así que es instantáneo, gratis, y guarda exactamente lo que el usuario leyó.

  function quitarConfirmaciones() {
    messagesDiv.querySelectorAll('.agente-confirm').forEach(el => el.remove());
  }

  function agregarConfirmacion(conf) {
    const caja = document.createElement('div');
    caja.className = 'agente-confirm';

    const btn = document.createElement('button');
    btn.className = 'agente-confirm-btn';
    btn.textContent = '✅ ' + (conf.etiqueta || 'Guardar');

    const nota = document.createElement('span');
    nota.className = 'agente-confirm-nota';
    nota.textContent = 'o seguí escribiendo para cambiar algo';

    btn.addEventListener('click', function() {
      if (enviando) return;
      enviando = true;
      btn.disabled = true;
      btn.textContent = 'Guardando…';

      fetch('/gestion/agente/confirmar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: conf.token })
      })
        .then(r => r.json().then(data => ({ ok: r.ok, data })))
        .then(({ data }) => {
          caja.remove();
          agregarMensaje(data.respuesta || 'Sin respuesta', data.ok ? 'assistant' : 'error');
        })
        .catch(error => {
          btn.disabled = false;
          btn.textContent = '✅ ' + (conf.etiqueta || 'Guardar');
          agregarMensaje('Error de conexión: ' + error.message, 'error');
        })
        .finally(() => {
          enviando = false;
          sendBtn.disabled = false;
        });
    });

    caja.appendChild(btn);
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

    fetch('/gestion/agente/historial')
      .then(r => (r.ok ? r.json() : null))
      .then(data => {
        if (!data || !data.mensajes || !data.mensajes.length) return;
        limpiarBienvenida();
        data.mensajes.forEach(m => agregarMensaje(m.texto, m.rol === 'user' ? 'user' : 'assistant'));
        // Un alta que quedó sin confirmar recupera su botón: si no, cambiar de página
        // dejaba la ficha viva en el servidor y sin forma de darle OK.
        if (data.confirmacion) agregarConfirmacion(data.confirmacion);
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
