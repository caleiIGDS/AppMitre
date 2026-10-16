/* salidas-padron.js — el padrón de alumnos y profesores, que vive SÓLO en este navegador.
 *
 * Hasta 2026-09-12 esto era `estudiantes.py` + `database/estudiantes.db`: el CSV se subía
 * a `POST /salidas/api/estudiantes/csv` y el padrón entero (1452 DNI de menores) quedaba
 * en el disco del server, y encima viajaba embebido en el HTML de cada carga del
 * formulario. Ahora el CSV se parsea acá y se guarda en localStorage: el servidor no lo
 * ve nunca. La contra asumida es que cada dispositivo carga el suyo — ver
 * `agent_docs/salidas-educativas.md` y `dev-log/DECISIONS.md`.
 *
 * Desde 2026-09-17 (`VERSION = 2`) guarda DOS padrones bajo la misma clave: `alumnos`
 * (apellido_nombre, dni, curso, division) y `profesores` (apellido_nombre, dni), cada uno
 * editable a mano además de por CSV — ver `/salidas/padron`. Un CSV puede REEMPLAZAR el
 * padrón entero o FUSIONARSE por DNI (actualiza las filas que coinciden, agrega las que
 * no aparecían, no toca las que el CSV no repite) — así una carga nueva no borra lo que se
 * agregó a mano ni lo que quedó de una carga anterior.
 *
 * Lleva prefijo de área porque nombra dominio (apellido_nombre, dni, curso, la regla
 * "primer carácter = año"): no es capa 0 compartida, es de salidas, como `gestion.css`.
 *
 * Lo cargan `padron.html` (para escribirlo) y `formulario.html` (para leerlo: alumnos vía
 * `listar()`/`info()` sin argumento, que apuntan a `'alumnos'` por default, y profesores
 * con `'profesores'` para el autocompletado de docentes), SIN `defer`: el JS de esas páginas corre inline y
 * un `defer` correría después.
 */
(function () {
  'use strict';

  var CLAVE = 'appmitre.padron.v1';
  var VERSION = 2;

  // ---------------------------------------------------------------------------
  // Normalización
  // ---------------------------------------------------------------------------

  // Puerto de texto.py::norm. Está duplicado con normTexto() de formulario.html a
  // propósito: ese vive en el <script> inline del formulario, que no existe en
  // padron.html, donde este módulo también tiene que normalizar encabezados.
  function norm(s) {
    return (s || '')
      .normalize('NFD').replace(/[̀-ͯ]/g, '')
      .toLowerCase().split(/\s+/).join(' ').trim();
  }

  // ---------------------------------------------------------------------------
  // Detección de columnas — puerto de estudiantes._ALIAS_COLUMNAS/_detectar_columnas
  // ---------------------------------------------------------------------------

  // Array de pares y no objeto: el algoritmo depende del ORDEN. `curso` tiene que
  // consumir su encabezado antes de que `nombre` mire, porque "Apellido y Nombre del
  // Estudiante" contiene los dos alias de `nombre` y también podría robarle el suyo a
  // otra clave. Cualquier encabezado que CONTENGA un alias cuenta.
  var ALIAS_COLUMNAS = {
    alumnos: [
      ['curso',  ['curso', 'ano', 'anio']],
      ['nombre', ['apellido', 'nombre']],
      ['dni',    ['dni', 'documento']]
    ],
    // Profesores no tiene curso: es sólo nombre + DNI (confirmado con la escuela — no
    // hace falta cargo/materia para las tablas de docentes de los Anexos IV/V).
    profesores: [
      ['nombre', ['apellido', 'nombre']],
      ['dni',    ['dni', 'documento']]
    ]
  };

  // Devuelve {curso: idx, nombre: idx, dni: idx} (sin `curso` para profesores). Guarda el
  // ÍNDICE y no el nombre de columna, que es más correcto que el DictReader de Python
  // cuando el CSV trae dos encabezados con el mismo texto.
  function detectarColumnas(headers, aliasColumnas) {
    var restantes = headers.map(function (h, i) { return {texto: norm(h), i: i}; });
    var encontradas = {};
    var faltantes = [];

    aliasColumnas.forEach(function (par) {
      var clave = par[0], alias = par[1];
      for (var k = 0; k < restantes.length; k++) {
        var h = restantes[k];
        var pega = alias.some(function (a) { return h.texto.indexOf(a) !== -1; });
        if (pega) {
          encontradas[clave] = h.i;
          restantes.splice(k, 1);
          return;
        }
      }
      faltantes.push(clave);
    });

    if (faltantes.length) {
      throw new Error(
        'El CSV no tiene columna para: ' + faltantes.sort().join(', ') + '. ' +
        'Encabezados encontrados: ' + headers.join(', ')
      );
    }
    return encontradas;
  }

  // ---------------------------------------------------------------------------
  // Parser de CSV
  // ---------------------------------------------------------------------------

  // El separador se detecta en la fila de encabezados en vez de asumir la coma: el
  // export de Excel en español usa punto y coma, y con la coma fija eso daba "El CSV no
  // tiene columna para: curso, dni, nombre" — un error que no dice nada. Sólo se miran
  // los caracteres fuera de comillas.
  function detectarSeparador(texto) {
    var fin = texto.search(/\r\n|\n|\r/);
    var linea = fin === -1 ? texto : texto.slice(0, fin);
    var comas = 0, puntoycomas = 0, dentro = false;
    for (var i = 0; i < linea.length; i++) {
      var c = linea[i];
      if (c === '"') dentro = !dentro;
      else if (!dentro && c === ',') comas++;
      else if (!dentro && c === ';') puntoycomas++;
    }
    return puntoycomas > comas ? ';' : ',';
  }

  // Máquina de estados carácter a carácter — sin librerías (no hay build step ni CDN).
  // Respeta comillas ("" es un " literal adentro), separadores y saltos dentro de un
  // campo entrecomillado, y CRLF / LF / CR sueltos (Excel viejo).
  function parsearFilas(texto, sep) {
    var filas = [], fila = [], campo = '', dentro = false, i = 0;

    while (i < texto.length) {
      var c = texto[i];
      if (dentro) {
        if (c === '"') {
          if (texto[i + 1] === '"') { campo += '"'; i += 2; continue; }
          dentro = false; i++; continue;
        }
        campo += c; i++; continue;
      }
      if (c === '"') { dentro = true; i++; continue; }
      if (c === sep) { fila.push(campo); campo = ''; i++; continue; }
      if (c === '\r' || c === '\n') {
        fila.push(campo); filas.push(fila); fila = []; campo = '';
        i += (c === '\r' && texto[i + 1] === '\n') ? 2 : 1;
        continue;
      }
      campo += c; i++;
    }
    if (campo !== '' || fila.length) { fila.push(campo); filas.push(fila); }
    return filas;
  }

  /* Convierte el texto de un CSV en el array de personas, o tira Error con un mensaje
   * mostrable. `tipo` es 'alumnos' (default) o 'profesores'. Mismas reglas y mismos
   * mensajes que tenía estudiantes.cargar_csv para alumnos: el curso viene en un campo de
   * 2+ caracteres ("1A", "41"), el primero es el año (1-7) y el resto la división tal
   * cual. Profesores no pide curso, sólo nombre + DNI.
   *
   * Arma el array completo antes de devolver nada, así que el padrón guardado nunca
   * queda a medio reemplazar: quien llama recién después hace un único guardar(). */
  function parsearCSV(texto, tipo) {
    tipo = tipo === 'profesores' ? 'profesores' : 'alumnos';
    if (texto.charCodeAt(0) === 0xFEFF) texto = texto.slice(1);  // BOM (utf-8-sig)

    var filas = parsearFilas(texto, detectarSeparador(texto));
    if (!filas.length || (filas.length === 1 && filas[0].join('') === '')) {
      throw new Error('El CSV está vacío o no tiene fila de encabezados.');
    }

    var headers = filas[0];
    var col = detectarColumnas(headers, ALIAS_COLUMNAS[tipo]);
    var personas = [];

    for (var f = 1; f < filas.length; f++) {
      var fila = filas[f];
      var n = f + 1;  // la fila 1 es el encabezado, igual que en el Python original
      var nombre = (fila[col.nombre] || '').trim().split(/\s+/).join(' ');
      var dni = (fila[col.dni] || '').trim();

      if (tipo === 'alumnos') {
        var rawCurso = (fila[col.curso] || '').trim().toUpperCase();
        if (!rawCurso && !nombre && !dni) continue;  // fila en blanco
        if (rawCurso.length < 2 || '1234567'.indexOf(rawCurso[0]) === -1) {
          throw new Error('Fila ' + n + ': curso inválido "' + rawCurso +
                          '" (se espera algo como "1A" o "4to 1").');
        }
        if (!nombre || !dni) throw new Error('Fila ' + n + ': falta nombre o DNI.');
        personas.push({
          apellido_nombre: nombre,
          dni: dni,
          curso: rawCurso[0],
          division: rawCurso.slice(1)
        });
      } else {
        if (!nombre && !dni) continue;  // fila en blanco
        if (!nombre || !dni) throw new Error('Fila ' + n + ': falta nombre o DNI.');
        personas.push({apellido_nombre: nombre, dni: dni});
      }
    }

    if (!personas.length) throw new Error('El CSV no tiene ninguna fila válida.');
    return personas;
  }

  // ---------------------------------------------------------------------------
  // Leer el archivo elegido
  // ---------------------------------------------------------------------------

  /* Lee el File como texto. Decodifica UTF-8 y, si el resultado trae U+FFFD (el
   * carácter de reemplazo), lo relee como windows-1252: es el encoding con el que Excel
   * exporta por defecto en Windows, y antes ese caso era un 500 en el server
   * (UnicodeDecodeError, que no caía en el `except ValueError` de la ruta). */
  function leerArchivo(file) {
    return new Promise(function (resolve, reject) {
      var lector = new FileReader();
      lector.onerror = function () { reject(new Error('No se pudo leer el archivo.')); };
      lector.onload = function () {
        var buf = lector.result;
        var texto = new TextDecoder('utf-8').decode(buf);
        if (texto.indexOf('�') !== -1) {
          try { texto = new TextDecoder('windows-1252').decode(buf); } catch (e) { /* se queda el UTF-8 */ }
        }
        resolve(texto);
      };
      lector.readAsArrayBuffer(file);
    });
  }

  // ---------------------------------------------------------------------------
  // Persistencia
  // ---------------------------------------------------------------------------

  function bucketVacio() {
    return {cargado: null, archivo: '', lista: []};
  }

  // El objeto parseado se memoiza: `listar()` lo llama el autocompletado en cada tecla y
  // reparsear el JSON por pulsación no tiene sentido. `undefined` = no leído todavía;
  // `null` = leído y no hay nada guardado (ni alumnos ni profesores, nunca se usó esto).
  var cache;

  function leer() {
    if (cache !== undefined) return cache;
    cache = null;
    try {
      var crudo = localStorage.getItem(CLAVE);
      if (!crudo) return cache;
      var dato = JSON.parse(crudo);

      if (dato && dato.v === VERSION && dato.alumnos && dato.profesores) {
        cache = dato;
      } else if (dato && dato.v === 1 && Array.isArray(dato.alumnos)) {
        // Forma vieja (sólo alumnos, sin `profesores`): se migra sola, sin perder lo que
        // ya había cargado el dispositivo. Si el setItem de la migración falla (cuota,
        // ventana privada), se sigue igual en memoria para esta sesión.
        cache = {
          v: VERSION,
          alumnos: {cargado: dato.cargado || null, archivo: dato.archivo || '', lista: dato.alumnos},
          profesores: bucketVacio()
        };
        try { localStorage.setItem(CLAVE, JSON.stringify(cache)); } catch (e) { /* migra sólo en memoria */ }
      }
      // Cualquier otra forma (JSON roto, versión futura desconocida) se descarta entera.
    } catch (e) {
      cache = null;  // JSON roto, o un navegador que no deja tocar localStorage
    }
    return cache;
  }

  // Cargar el padrón en otra pestaña tiene que invalidar el cache de esta.
  window.addEventListener('storage', function (e) {
    if (e.key === CLAVE || e.key === null) cache = undefined;
  });

  function _persistir(dato) {
    try {
      localStorage.setItem(CLAVE, JSON.stringify(dato));
    } catch (e) {
      // Safari en ventana privada tira QuotaExceededError con cuota 0. Mejor decirlo que
      // dejar al usuario creyendo que guardó el cambio.
      throw new Error('Este navegador no permite guardar el padrón (¿ventana privada?). ' +
                      'Probá en una ventana normal.');
    }
    cache = dato;
  }

  function listar(tipo) {
    tipo = tipo === 'profesores' ? 'profesores' : 'alumnos';
    var dato = leer();
    return dato && dato[tipo] ? dato[tipo].lista : [];
  }

  function info(tipo) {
    tipo = tipo === 'profesores' ? 'profesores' : 'alumnos';
    var dato = leer();
    if (!dato || !dato[tipo]) return null;
    var b = dato[tipo];
    return {cantidad: b.lista.length, cargado: b.cargado, archivo: b.archivo};
  }

  // Fusiona por DNI: cada persona de `listaNueva` pisa la de `listaActual` con el mismo
  // DNI, o se agrega si no había ninguna. Lo que `listaActual` tiene y `listaNueva` no
  // repite queda intacto — así una carga nueva no borra lo agregado a mano ni lo que
  // quedó de un CSV anterior.
  function fusionar(listaActual, listaNueva) {
    var indicePorDni = {};
    listaActual.forEach(function (p, i) { indicePorDni[p.dni] = i; });
    var resultado = listaActual.slice();
    listaNueva.forEach(function (p) {
      if (Object.prototype.hasOwnProperty.call(indicePorDni, p.dni)) {
        resultado[indicePorDni[p.dni]] = p;
      } else {
        resultado.push(p);
      }
    });
    return resultado;
  }

  // Carga por CSV. `modo` es 'reemplazar' (default: pisa toda la lista de ese tipo) o
  // 'fusionar' (upsert por DNI, ver `fusionar()`). Actualiza `cargado`/`archivo` siempre,
  // aunque sea una fusión parcial, para que se vea cuándo fue la última carga.
  function guardar(lista, archivo, tipo, modo) {
    tipo = tipo === 'profesores' ? 'profesores' : 'alumnos';
    var dato = leer() || {v: VERSION, alumnos: bucketVacio(), profesores: bucketVacio()};
    if (!dato[tipo]) dato[tipo] = bucketVacio();

    var listaFinal = modo === 'fusionar' ? fusionar(dato[tipo].lista, lista) : lista;
    dato.v = VERSION;
    dato[tipo] = {cargado: new Date().toISOString(), archivo: archivo || '', lista: listaFinal};
    _persistir(dato);
  }

  // Sobrescribe sólo el array de un tipo, sin tocar `cargado`/`archivo` de la última
  // carga CSV — lo usa la tabla editable de `/salidas/padron` en cada alta/edición/borrado
  // manual de una fila.
  function guardarLista(tipo, lista) {
    tipo = tipo === 'profesores' ? 'profesores' : 'alumnos';
    var dato = leer() || {v: VERSION, alumnos: bucketVacio(), profesores: bucketVacio()};
    if (!dato[tipo]) dato[tipo] = bucketVacio();
    dato.v = VERSION;
    dato[tipo].lista = lista;
    _persistir(dato);
  }

  // Sin argumento borra los dos padrones (comportamiento legado); con `tipo` vacía sólo
  // ese.
  function borrar(tipo) {
    if (!tipo) {
      try { localStorage.removeItem(CLAVE); } catch (e) { /* nada que borrar */ }
      cache = null;
      return;
    }
    var dato = leer();
    if (!dato) return;
    dato[tipo === 'profesores' ? 'profesores' : 'alumnos'] = bucketVacio();
    _persistir(dato);
  }

  window.Padron = {
    listar: listar,
    info: info,
    parsearCSV: parsearCSV,
    guardar: guardar,
    guardarLista: guardarLista,
    borrar: borrar,
    leerArchivo: leerArchivo
  };
})();
