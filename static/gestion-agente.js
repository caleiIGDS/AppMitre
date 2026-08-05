// gestion-agente.js — Widget del asistente IA

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

  let imagenSeleccionada = null;
  let imagenNombre = null;
  let enviando = false;

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
        inputField.focus();
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
          inputField.focus();
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
    agregarMensaje(mensaje, 'user');

    // Preparar payload
    const payload = { mensaje };
    if (imagenSeleccionada) {
      payload.imagen = imagenSeleccionada;
    }

    // Limpiar UI
    inputField.value = '';
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
        inputField.focus();
      });
  }

  // Event listeners
  if (sendBtn) {
    sendBtn.addEventListener('click', enviarMensaje);
  }

  if (inputField) {
    inputField.addEventListener('keydown', function(e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        enviarMensaje();
      }
    });

    inputField.addEventListener('input', function() {
      // Auto-resize textarea
      this.style.height = 'auto';
      this.style.height = Math.min(this.scrollHeight, 80) + 'px';
    });
  }

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
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
  }

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
