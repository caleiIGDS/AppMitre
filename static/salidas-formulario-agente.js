(() => {
  const panel = document.getElementById("agente-formulario");
  const control = nombre => document.getElementById("agente-formulario-" + nombre);
  const iniciar = control("iniciar");
  const cancelar = control("cancelar");
  const aplicar = control("aplicar");
  const codigo = control("codigo");
  const mensaje = control("estado");
  const vacio = valor => valor === undefined || valor === null || valor === "";
  const definiciones = new Map();

  for (const {campos} of COMUNES) {
    for (const campo of campos) {
      if (!campo.fijo) definiciones.set("comunes." + campo.id, {campo, destino: estado.comunes});
    }
  }
  for (const anexo of ANEXOS) {
    for (const campo of anexo.campos) {
      if (!campo.auto && !campo.calc) {
        definiciones.set(anexo.n + "." + campo.id, {campo, destino: estado.anexos[anexo.n]});
      }
    }
  }

  function camposDisponibles() {
    const campos = {};
    for (const [clave, {campo, destino}] of definiciones) {
      const telefonos = campo.tipo === "acompañantes_telefonos";
      if (!telefonos && !vacio(destino[campo.id])) continue;
      campos[clave] = {tipo: telefonos ? "telefonos" : campo.tipo, label: campo.label};
      if (campo.opciones) campos[clave].opciones = campo.opciones;
    }
    if (!estado.personas.length) campos.personas = {tipo: "personas", label: "Nómina de participantes"};
    return campos;
  }

  function volcar(valores) {
    let aplicados = 0;
    for (const [clave, {campo, destino}] of definiciones) {
      if (!Object.hasOwn(valores, clave) || !vacio(destino[campo.id])
          || campo.tipo === "acompañantes_telefonos") continue;
      if (campo.cond && destino[campo.cond.campo] !== campo.cond.valor) continue;
      destino[campo.id] = valores[clave];
      if (campo.prellenar) destino["_" + campo.id + "_manual"] = true;
      aplicados++;
    }
    if (valores.personas && !estado.personas.length) {
      estado.personas = valores.personas.map(p => ({
        apellido_nombre: p.apellido_nombre,
        documento: p.documento || "",
        rol: p.rol,
        cargo: p.cargo || "",
        fecha_nacimiento: p.fecha_nacimiento || "",
        grupo_edad: p.rol === "estudiante" && p.fecha_nacimiento ? obtenerGrupoEdad(p.fecha_nacimiento) : null
      }));
      aplicados++;
    }
    const claveTelefonos = "VI.nombres_telefonos_acompanantes";
    if (Object.hasOwn(valores, claveTelefonos)) {
      const {campo, destino} = definiciones.get(claveTelefonos);
      const telefonos = Object.assign(Object.create(null), destino[campo.id]);
      let completados = 0;
      for (const {rol, apellido_nombre} of estado.personas) {
        if (rol === "estudiante" || !Object.hasOwn(valores[claveTelefonos], apellido_nombre)
            || !vacio(telefonos[apellido_nombre])) continue;
        telefonos[apellido_nombre] = valores[claveTelefonos][apellido_nombre];
        completados++;
      }
      if (completados) {
        destino[campo.id] = telefonos;
        aplicados++;
      }
    }
    if (aplicados) {
      dibujarTodo();
      marcarCambio();
    }
    return aplicados;
  }

  let receptor = null;
  let propuesta = null;
  let temporizador;

  function limpiar(texto) {
    clearTimeout(temporizador);
    receptor = null;
    propuesta = null;
    iniciar.disabled = false;
    codigo.hidden = aplicar.hidden = cancelar.hidden = true;
    codigo.value = "";
    mensaje.textContent = texto;
  }

  async function solicitar(datos) {
    const r = await fetch(panel.dataset.url, {
      method: "POST", cache: "no-store", headers: {"Content-Type": "application/json", "X-Mitre": "1"},
      body: JSON.stringify(datos)
    });
    if (!r.ok || r.redirected) throw new Error("No se pudo conectar.");
    return r.json();
  }

  async function recibir(actual, vence) {
    try {
      const datos = await solicitar({receptor: actual, accion: "recibir"});
      if (receptor !== actual) return;
      if (datos.estado === "recibido") {
        receptor = null;
        propuesta = datos.valores;
        codigo.hidden = true;
        codigo.value = "";
        aplicar.hidden = false;
        mensaje.textContent = "Propuesta recibida. Aplicala al formulario para revisar los campos.";
        return;
      }
      if (datos.estado === "vencido" || Date.now() >= vence) {
        limpiar("El código venció. Podés generar otro.");
        return;
      }
    } catch {
      if (receptor !== actual) return;
      if (Date.now() >= vence) {
        limpiar("No se pudo recibir la propuesta. Podés generar otro código.");
        return;
      }
    }
    temporizador = setTimeout(() => recibir(actual, vence), 3000);
  }

  iniciar.addEventListener("click", async () => {
    iniciar.disabled = true;
    mensaje.textContent = "Generando código…";
    try {
      const datos = await solicitar({campos: camposDisponibles()});
      receptor = datos.receptor;
      codigo.value = datos.codigo;
      codigo.hidden = cancelar.hidden = false;
      codigo.focus();
      codigo.select();
      mensaje.textContent = "Copiá el código al chat. Vence en 10 minutos.";
      recibir(receptor, Date.now() + datos.vence_en * 1000);
    } catch {
      limpiar("No se pudo generar el código. Revisá que la salida siga activa.");
    }
  });
  codigo.addEventListener("click", () => codigo.select());
  cancelar.addEventListener("click", async () => {
    const actual = receptor;
    limpiar("Propuesta descartada.");
    if (actual) {
      try {
        await solicitar({receptor: actual, accion: "cancelar"});
      } catch {
        if (!receptor && !iniciar.disabled) mensaje.textContent = "Se cerró la recepción en esta pestaña. El código vence en 10 minutos.";
      }
    }
  });
  aplicar.addEventListener("click", () => {
    const fechas = panel.ownerDocument.querySelectorAll('input[placeholder="dd/mm/yyyy"]');
    if ([...fechas].some(inp => inp.value && !validarFecha(inp.value))) {
      mensaje.textContent = "Terminá de escribir las fechas antes de aplicar la propuesta.";
      return;
    }
    const total = Object.keys(propuesta).length;
    const aplicados = volcar(propuesta);
    limpiar(`Campos aplicados: ${aplicados} de ${total}. Revisá los datos antes de guardar.`);
  });
  iniciar.disabled = false;
})();
