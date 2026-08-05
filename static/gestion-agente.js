// gestion-agente.js — Widget del asistente IA

document.addEventListener('DOMContentLoaded', function() {
  const widget = document.getElementById('agente-widget');
  const toggleBtn = document.getElementById('agente-toggle-btn');
  const closeBtn = document.getElementById('agente-close-btn');
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
    } else {
      msgDiv.className = 'agente-message agente-message-' + tipo;
      msgDiv.textContent = texto;
    }

    messagesDiv.appendChild(msgDiv);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
  }
});
