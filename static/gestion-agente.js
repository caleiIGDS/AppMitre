// gestion-agente.js
// Widget de chat para el asistente (agente.py)

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

  // Abrir/cerrar widget
  if (toggleBtn) {
    toggleBtn.addEventListener('click', function() {
      widget.hidden = !widget.hidden;
      if (!widget.hidden) {
        inputField.focus();
      }
    });
  }

  if (closeBtn) {
    closeBtn.addEventListener('click', function() {
      widget.hidden = true;
    });
  }

  // Imagen
  if (imageBtn) {
    imageBtn.addEventListener('click', function() {
      imageFile.click();
    });
  }

  if (imageFile) {
    imageFile.addEventListener('change', function(e) {
      const file = e.target.files[0];
      if (file) {
        const reader = new FileReader();
        reader.onload = function(evt) {
          imagenSeleccionada = evt.target.result; // data:image/xxx;base64,xxx
          imagePreview.textContent = '✅ Imagen cargada (' + file.name + ')';
        };
        reader.readAsDataURL(file);
      }
    });
  }

  // Enviar mensaje
  function enviarMensaje() {
    const mensaje = inputField.value.trim();
    if (!mensaje) return;

    // Mostrar mensaje del usuario
    agregarMensaje(mensaje, 'user');

    // Limpiar input
    inputField.value = '';
    imagenSeleccionada = null;
    imagePreview.textContent = '';

    // Deshabilitar botón mientras se envía
    sendBtn.disabled = true;

    // Preparar payload
    const payload = {
      mensaje: mensaje
    };
    if (imagenSeleccionada) {
      payload.imagen = imagenSeleccionada;
    }

    // Enviar al servidor
    fetch('/gestion/agente/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    })
      .then(response => {
        if (!response.ok) {
          throw new Error('Error HTTP: ' + response.status);
        }
        return response.json();
      })
      .then(data => {
        sendBtn.disabled = false;
        if (data.error) {
          agregarMensaje('Error: ' + data.error, 'error');
        } else {
          agregarMensaje(data.respuesta, 'assistant');
        }
      })
      .catch(error => {
        sendBtn.disabled = false;
        agregarMensaje('Error de conexión: ' + error.message, 'error');
      });
  }

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
  }

  function agregarMensaje(texto, tipo) {
    const msgDiv = document.createElement('div');
    msgDiv.className = 'agente-message agente-message-' + tipo;
    msgDiv.textContent = texto;
    messagesDiv.appendChild(msgDiv);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
  }
});
