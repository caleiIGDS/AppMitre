// Configuración
const HORAS_PROXIMAS = 2; // Rango en horas para la columna "Próximas"

// Datos y estado global
const rawData = window.APP_DATA ? window.APP_DATA.rawData : {};
let currentSearch = {
    modo: null,
    valor: null
};

// ─── MODO COMPARACIÓN ───────────────────────────────────────────────────────
const COMPARACION_COLORS = ['#1a3a5c', '#c0392b', '#27ae60', '#8e44ad', '#e67e22', '#16a085'];
let isComparacionMode = false;
let comparacionItems = [];
let lastFilas = null;

// ─── CACHÉ DE DATOS EN MEMORIA ───────────────────────────────────────────────
// El dataset es chico: se descarga una sola vez al cargar la web y las búsquedas
// de profesor/aula/curso/planilla se resuelven client-side, sin más requests.
let _allClases = null;            // todas las filas de la tabla `clases`
let _allPersonal = null;          // todo el personal no docente
let _horariosPreceptores = null;  // { nombre: [filas de su horario] }
let _planillaPreceptores = null;  // lista por curso con turnos (planilla + preceptor-por-curso)
let _datosPromise = null;         // evita descargas duplicadas

function cargarDatosIniciales() {
    if (_datosPromise) return _datosPromise;
    _datosPromise = Promise.all([
        fetch('/api/dashboard').then(r => r.json()),
        fetch('/api/personal_todos').then(r => r.json()).catch(() => []),
        fetch('/api/preceptores_data').then(r => r.json()).catch(() => ({ horarios: {}, planilla: [] }))
    ]).then(([clases, personal, prec]) => {
        _allClases = clases || [];
        _allPersonal = personal || [];
        _horariosPreceptores = (prec && prec.horarios) || {};
        _planillaPreceptores = (prec && prec.planilla) || [];
        // Reutilizar el mismo dataset para planilla general y dashboard
        allDataCache = _allClases;
        lastDashboardData = _allClases;
        return { clases: _allClases, personal: _allPersonal };
    }).catch(err => {
        console.error("Error cargando datos iniciales:", err);
        _datosPromise = null; // permitir reintento
        return { clases: null, personal: [] };
    });
    return _datosPromise;
}

// Deriva el preceptor-por-curso desde la planilla cacheada (reemplaza /api/preceptor/<valor>).
// Devuelve: objeto con datos | false (cargado, sin preceptor) | null (no cargado → fallback red).
function obtenerPreceptorLocal(valorCurso) {
    if (!_planillaPreceptores) return null;
    const v = String(valorCurso).trim();
    const idx = v.indexOf(' ');
    const cursoRaw = idx === -1 ? v : v.slice(0, idx);
    const divRaw   = idx === -1 ? "" : v.slice(idx + 1).trim();
    const num = (cursoRaw.match(/\d+/) || [cursoRaw])[0];
    const div = divRaw.toUpperCase();
    const fila = _planillaPreceptores.find(p =>
        String(p.curso) === num && String(p.division).toUpperCase() === div
    );
    if (!fila || (!fila.manana && !fila.tarde && !fila.vespertino)) return false;
    return {
        curso: num,
        division: div,
        preceptores_manana: fila.manana || "",
        preceptores_tarde: fila.tarde || "",
        preceptores_vespertino: fila.vespertino || "",
        turno: fila.turno,
    };
}

// Replica client-side la lógica de obtener_filas() de app.py.
// Devuelve null si el modo no es cacheable o los datos aún no cargaron → fallback al server.
function filtrarClasesLocal(modo, valor) {
    if (!_allClases) return null;
    switch (modo) {
        case 'profesor':
            return _allClases.filter(f => f.profesor === valor || (f.suplente_activo == 1 && f.prof_suplente === valor));
        case 'aula':
            return _allClases.filter(f => String(f.aula) === String(valor));
        case 'curso': {
            // "1° A" → curso='1', division='A' (igual que el server: quita ° y separa por espacio)
            const partes = valor.replace(/°/g, '').trim().split(/\s+/);
            if (partes.length >= 2) {
                return _allClases.filter(f => String(f.curso) === partes[0] && f.division === partes[1]);
            }
            return _allClases.filter(f => String(f.curso) === partes[0]);
        }
        case 'planilla': {
            if (!valor.includes('|')) return [];
            const [dia, piso] = valor.split('|');
            const aulas = (window.APP_DATA.floorMapping[piso] || []);
            if (!aulas.length) return [];
            return _allClases.filter(f => f.dia === dia && aulas.includes(String(f.aula)));
        }
        default:
            return null; // horario_preceptor / preceptor → tabla distinta, va al server
    }
}

function toggleComparacion() {
    if (isComparacionMode) {
        desactivarModoComparacion();
    } else {
        activarModoComparacion();
    }
}

function activarModoComparacion() {
    isComparacionMode = true;
    if (currentSearch.modo && currentSearch.valor && lastFilas) {
        comparacionItems = [{
            modo: currentSearch.modo,
            valor: currentSearch.valor,
            filas: lastFilas,
            color: COMPARACION_COLORS[0],
            label: currentSearch.valor
        }];
        generarCalendarioComparacion(comparacionItems);
    } else {
        comparacionItems = [];
        _mostrarPlaceholderComparacion();
    }
    actualizarEstadoComparacion();
}

function _mostrarPlaceholderComparacion() {
    const c = document.getElementById('contenedor-calendario');
    c.innerHTML = `<div style="padding:60px; text-align:center; color:#70757a; font-family:'Roboto Mono',monospace; letter-spacing:1px; font-size:14px;">Seleccioná un calendario para comparar.</div>`;
    c.style.display = 'block';
}

function removerItemComparacion(idx) {
    comparacionItems.splice(idx, 1);
    comparacionItems.forEach((item, i) => { item.color = COMPARACION_COLORS[i % COMPARACION_COLORS.length]; });
    actualizarEstadoComparacion();
    if (comparacionItems.length === 0) {
        _mostrarPlaceholderComparacion();
    } else {
        generarCalendarioComparacion(comparacionItems);
    }
}

function desactivarModoComparacion() {
    isComparacionMode = false;
    comparacionItems = [];
    lastFilas = null;
    actualizarEstadoComparacion();
    document.getElementById('contenedor-calendario').innerHTML = "";
    const workspaceHeader = document.getElementById('workspace-calendar-header');
    if (workspaceHeader) workspaceHeader.style.display = 'none';
}

function actualizarEstadoComparacion() {
    const banner = document.getElementById('comparacion-banner');

    if (isComparacionMode) {
        if (banner) {
            const chips = comparacionItems.map((item, idx) =>
                `<span class="comp-chip" style="background:${item.color};">${item.label}<button class="comp-chip-close" onclick="removerItemComparacion(${idx})">✕</button></span>`
            ).join('');
            document.getElementById('comp-banner-items').innerHTML = chips;
            banner.style.display = 'flex';
        }
        if (currentSearch.modo && ['profesor', 'curso', 'aula'].includes(currentSearch.modo)) {
            _crearChip('comparar', currentSearch.modo);
        }
        const workspaceHeader = document.getElementById('workspace-calendar-header');
        if (workspaceHeader) workspaceHeader.style.display = 'none';
    } else {
        if (banner) banner.style.display = 'none';
        _limpiarChipsComparar();
    }
}

function _limpiarChipsComparar() {
    document.querySelectorAll('[id^="chip-comparar-"]').forEach(chip => {
        const tabId = chip.id.replace('chip-comparar-', '');
        chip.remove();
        const panel = document.getElementById('slide-' + tabId);
        if (panel) {
            panel.querySelectorAll('.slide-opcion').forEach(btn => {
                if (btn.dataset.opcion === 'comparar') btn.style.display = '';
            });
        }
    });
}

function toggleSlidePanel(tabId) {
    const panel = document.getElementById('slide-' + tabId);
    const trigger = document.getElementById('trigger-' + tabId);
    const isOpen = panel.classList.contains('open');

    document.querySelectorAll('.slide-panel').forEach(p => p.classList.remove('open'));
    document.querySelectorAll('.btn-slide-trigger').forEach(b => b.classList.remove('panel-open'));

    if (!isOpen) {
        panel.classList.add('open');
        trigger.classList.add('panel-open');
    }
}

function seleccionarOpcionSlide(opcion, tabId) {
    const panel = document.getElementById('slide-' + tabId);
    const trigger = document.getElementById('trigger-' + tabId);
    panel.classList.remove('open');
    trigger.classList.remove('panel-open');

    if (opcion === 'comparar') {
        if (!currentSearch.modo || !currentSearch.valor || !lastFilas) {
            alert("Primero buscá un horario para poder comparar.");
            return;
        }
        panel.querySelectorAll('.slide-opcion').forEach(btn => {
            if (btn.dataset.opcion === 'comparar') btn.style.display = 'none';
        });
        _crearChip('comparar', tabId);
        if (!isComparacionMode) activarModoComparacion();
    } else if (opcion === 'planilla') {
        panel.querySelectorAll('.slide-opcion').forEach(btn => {
            if (btn.dataset.opcion === 'planilla') btn.style.display = 'none';
        });
        _crearChip('planilla', tabId);
        isPlanillaGeneral = true;
        const controls = document.getElementById('planilla-controls');
        const searchField = document.querySelector('#tab-aula .tech-field');
        controls.style.display = 'block';
        searchField.style.opacity = '0.5';
        searchField.style.pointerEvents = 'none';
        if (allDataCache) {
            generarPlanillaGeneral();
        } else {
            fetch('/api/dashboard').then(r => r.json()).then(d => { allDataCache = d; generarPlanillaGeneral(); });
        }
    }
}

function _crearChip(opcion, tabId) {
    const chipId = `chip-${opcion}-${tabId}`;
    if (document.getElementById(chipId)) return;
    const labels = { comparar: 'COMPARAR', planilla: 'PLANILLA' };
    const chip = document.createElement('div');
    chip.className = `opcion-chip ${opcion}-chip`;
    chip.id = chipId;
    chip.innerHTML = `${labels[opcion]} <button class="chip-close" onclick="removerChip('${opcion}','${tabId}')">✕</button>`;
    document.getElementById('chips-' + tabId).appendChild(chip);
}

function removerChip(opcion, tabId) {
    const chip = document.getElementById(`chip-${opcion}-${tabId}`);
    if (chip) chip.remove();

    const panel = document.getElementById('slide-' + tabId);
    if (panel) {
        panel.querySelectorAll('.slide-opcion').forEach(btn => {
            if (btn.dataset.opcion === opcion) btn.style.display = '';
        });
    }

    if (opcion === 'comparar') {
        if (isComparacionMode) desactivarModoComparacion();
    } else if (opcion === 'planilla') {
        isPlanillaGeneral = false;
        const controls = document.getElementById('planilla-controls');
        const searchField = document.querySelector('#tab-aula .tech-field');
        controls.style.display = 'none';
        searchField.style.opacity = '1';
        searchField.style.pointerEvents = 'auto';
        const input = document.querySelector('#tab-aula .tech-input');
        if (input.value) {
            buscarEnServidor('aula', input.value);
        } else {
            document.getElementById('contenedor-calendario').innerHTML = '';
            const workspaceHeader = document.getElementById('workspace-calendar-header');
            if (workspaceHeader) workspaceHeader.style.display = 'none';
        }
    }
}

function generarCalendarioComparacion(items) {
    const contenedor = document.getElementById('contenedor-calendario');
    const COL_WIDTH = 200;
    const N = items.length;
    const dias = window.APP_DATA.dias;

    const timeToMin = (t) => {
        if (!t || typeof t !== 'string' || !t.includes(':')) return 0;
        const [h, m] = t.split(':').map(Number);
        return h * 60 + m;
    };

    let tiempos = new Set();
    items.forEach(item => {
        item.filas.forEach(f => {
            if (f.hora_inicio) tiempos.add(f.hora_inicio);
            if (f.hora_fin) tiempos.add(f.hora_fin);
        });
    });

    if (tiempos.size === 0) {
        contenedor.innerHTML = "<div style='padding:20px; text-align:center; color:#70757a;'>Sin horarios.</div>";
        return;
    }

    const horariosDinamicos = Array.from(tiempos).sort((a, b) => timeToMin(a) - timeToMin(b));
    const minMins = timeToMin(horariosDinamicos[0]) - 30;
    const maxMins = timeToMin(horariosDinamicos[horariosDinamicos.length - 1]) + 30;
    const HORA_MIN = Math.max(0, minMins);
    const HORA_MAX = Math.min(1440, maxMins);
    const ALTURA_TOTAL = Math.max((HORA_MAX - HORA_MIN) * 1.05, 450);

    const getPosicionY = (horaStr) => {
        if (!horaStr) return 0;
        return ((timeToMin(horaStr) - HORA_MIN) / (HORA_MAX - HORA_MIN)) * ALTURA_TOTAL;
    };

    const gridCols = `60px repeat(${N * 5}, ${COL_WIDTH}px)`;
    const gridMinWidth = 60 + N * 5 * COL_WIDTH;

    let html = `<div class="comparacion-scroll-wrapper"><div class="calendario-grid" style="grid-template-columns:${gridCols}; min-width:${gridMinWidth}px;">`;

    // Fila 1: cabecera-vacia + encabezados de día (cada uno span N columnas)
    html += '<div class="cabecera-vacia"></div>';
    dias.forEach(dia => {
        html += `<div class="cabecera-dia cabecera-dia-grupo" style="grid-column:span ${N};">${dia}</div>`;
    });

    // Fila 2: placeholder + sub-encabezados de entidad
    html += '<div class="cabecera-entidad-placeholder"></div>';
    dias.forEach(() => {
        items.forEach(item => {
            html += `<div class="cabecera-entidad">
                <span class="comp-color-dot" style="background:${item.color};"></span>
                <span class="comp-entity-name" style="color:${item.color};">${item.label}</span>
            </div>`;
        });
    });

    // Fila 3: columna-horas + columnas de entidad por día
    html += `<div class="columna-horas" style="height:${ALTURA_TOTAL}px; position:relative;">`;
    horariosDinamicos.forEach(hora => {
        html += `<div class="hora-label" style="top:${getPosicionY(hora)}px;">${hora}</div>`;
    });
    html += '</div>';

    const renderBloqueComp = (clase, styleExtra, item) => {
        const inicio = clase.hora_inicio;
        const fin = clase.hora_fin;
        const top = getPosicionY(inicio) + 2;
        const alto = Math.max(getPosicionY(fin) - 2 - top, 20);
        const jsonClase = encodeURIComponent(JSON.stringify(clase));
        const modo = item.modo;
        const profName = (clase.suplente_activo === 1 && clase.prof_suplente) ? 'SUPLENTE: ' + clase.prof_suplente : (clase.profesor || '-');
        const detalleLinea = modo === 'profesor' ? `${clase.curso}° ${clase.division}` : profName;
        const aulaInd = modo === 'aula' ? `${clase.curso}° ${clase.division}` : (clase.aula || '?');
        const sinNumero = !(/\d/.test(clase.aula)) && modo !== 'aula' ? ' sin-numero' : '';
        return `<div class="materia-bloque"
            style="top:${top}px; height:${alto}px; ${styleExtra} background-color:${item.color};"
            onclick="mostrarInfoClase('${jsonClase}', this)"
            onmouseover="showTooltip(event,'${clase.materia.replace(/'/g,"\\'")}','${profName.replace(/'/g,"\\'")}','${(clase.aula||'-').replace(/'/g,"\\'")}','${inicio} - ${fin}','${clase.curso}° ${clase.division}')"
            onmouseout="hideTooltip()">
            <div class="materia-contenido">
                ${modo === 'profesor' && clase.suplente_activo === 1
                    ? `<div class="materia-nombre" style="color:var(--alert);font-weight:bold;display:flex;align-items:center;justify-content:center;height:100%;">LICENCIADA</div>`
                    : `<div class="materia-nombre">${clase.materia}</div><div class="materia-detalles">${detalleLinea}</div>`
                }
            </div>
            <div class="aula-indicador${sinNumero}">${aulaInd}</div>
        </div>`;
    };

    dias.forEach(dia => {
        items.forEach((item, itemIdx) => {
            const isLastEntity = itemIdx === N - 1;
            const borderRight = isLastEntity
                ? 'border-right: 2px solid var(--primary);'
                : 'border-right: 1px dashed rgba(0,0,0,0.15);';

            html += `<div class="columna-dia" style="height:${ALTURA_TOTAL}px; ${borderRight}">`;
            horariosDinamicos.forEach(hora => {
                html += `<div class="grid-line-horizontal" style="top:${getPosicionY(hora)}px;"></div>`;
            });

            const clasesDelDia = item.filas
                .filter(f => f.dia === dia)
                .sort((a, b) => timeToMin(a.hora_inicio) - timeToMin(b.hora_inicio));
            const modo = item.modo;

            let procesados = new Set();
            for (let i = 0; i < clasesDelDia.length; i++) {
                if (procesados.has(i)) continue;
                let cluster = [clasesDelDia[i]];
                let clusterIdx = [i];
                let maxFin = timeToMin(clasesDelDia[i].hora_fin);
                for (let j = i + 1; j < clasesDelDia.length; j++) {
                    if (timeToMin(clasesDelDia[j].hora_inicio) < maxFin) {
                        cluster.push(clasesDelDia[j]);
                        clusterIdx.push(j);
                        maxFin = Math.max(maxFin, timeToMin(clasesDelDia[j].hora_fin));
                    } else { break; }
                }

                const sinLicenciadas = cluster.filter(c => !(c.suplente_activo == 1 && c.profesor === currentSearch.valor));
                const clusterFinal = cluster.length > 1 && sinLicenciadas.length > 0 ? sinLicenciadas : cluster;

                const todosTienenGrupo = clusterFinal.every(c => c.grupo && c.grupo.trim() !== "");
                const haySuperposicion = clusterFinal.length > 1 && (modo === 'aula' || modo === 'profesor' || !todosTienenGrupo);

                if (haySuperposicion) {
                    const todosPermiten = clusterFinal.every(c => c.superposicion == 1);
                    if (todosPermiten) {
                        const estilos = calcularEstilosBloques(clusterFinal);
                        clusterFinal.forEach((clase, idx) => { html += renderBloqueComp(clase, estilos[idx], item); });
                    } else {
                        const top = getPosicionY(clusterFinal[0].hora_inicio);
                        const latestEnd = clusterFinal.reduce((max, c) => timeToMin(c.hora_fin) > timeToMin(max.hora_fin) ? c : max);
                        const alto = Math.max(getPosicionY(latestEnd.hora_fin) - top, 30);
                        const jsonD = encodeURIComponent(JSON.stringify(clusterFinal));
                        html += `<div class="bloque-superposicion" style="top:${top}px; height:${alto}px;" onclick="verDetalleSuperposicion('${jsonD}')">⚠️ Superposición (${clusterFinal.length})</div>`;
                    }
                } else {
                    const estilos = calcularEstilosBloques(clusterFinal);
                    clusterFinal.forEach((clase, idx) => { html += renderBloqueComp(clase, estilos[idx], item); });
                }
                clusterIdx.forEach(idx => procesados.add(idx));
            }
            html += '</div>';
        });
    });

    html += '</div></div>';
    contenedor.innerHTML = html;
    contenedor.style.display = 'block';
}
// ─── FIN MODO COMPARACIÓN ───────────────────────────────────────────────────

function actualizarDatos() {
    const btn = document.getElementById('btn-actualizar');
    const originalText = btn.innerText;
    
    btn.disabled = true;
    btn.innerText = "ACTUALIZANDO...";
    btn.classList.add('loading');

    // POST y no GET: reconstruye escuela.db entera, no puede dispararla un prefetch.
    fetch('/api/actualizar', { method: 'POST' })
        .then(res => res.json())
        .then(data => {
            if (data.status === "success") {
                btn.innerText = "¡ÉXITO!";
                btn.style.backgroundColor = "#28a745";
                setTimeout(() => {
                    location.reload();
                }, 1000);
            } else {
                alert("Error: " + data.message);
                btn.disabled = false;
                btn.innerText = originalText;
                btn.classList.remove('loading');
            }
        })
        .catch(err => {
            console.error("Error al actualizar:", err);
            alert("Error de conexión al servidor");
            btn.disabled = false;
            btn.innerText = originalText;
            btn.classList.remove('loading');
        });
}

function personalToFila(p) {
    const diaMap = Object.fromEntries(
        window.APP_DATA.dias.map(d => [d.normalize('NFD').replace(/[̀-ͯ]/g, '').toUpperCase(), d])
    );
    // Imita el objeto de una fila de `clases` para reusar el renderizado del calendario.
    // `tipo: 'personal'` es el marker que distingue estos bloques.
    return {
        curso: '', division: '', especialidad: '',
        materia: p.rol, tipo_materia: '',
        profesor: p.nombre, dni: '', telefono: '', email: '',
        aula: '', tipo_aula: '',
        dia: diaMap[p.dia] || p.dia,
        hora_inicio: p.hora_inicio, hora_fin: p.hora_fin,
        grupo: '', superposicion: 0, suplente_activo: 0,
        prof_suplente: '', sup_ini: '', sup_fin: '',
        tipo: 'personal'
    };
}

function normalize(text) {
    if (!text) return "";
    return text.toLowerCase()
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .replace(/\s+/g, "")
        .replace(/°/g, "");
}

function filtrarOpciones(input, modo) {
    const query = input.value;
    const normalizedQuery = normalize(query);
    const dropdown = document.getElementById(`dropdown-${modo}`);

    if (modo === 'profesor') {
        const profList = rawData['profesor'] || [];
        const personalList = rawData['personal'] || [];

        // Build combined items: {valor, display, rol?}
        const itemsMap = {};
        profList.forEach(nombre => {
            if (query.length === 0 || normalize(nombre).includes(normalizedQuery)) {
                itemsMap[normalize(nombre)] = { valor: nombre, display: nombre };
            }
        });
        personalList.forEach(p => {
            const matchNombre = normalize(p.nombre).includes(normalizedQuery);
            const matchRol = normalize(p.rol).includes(normalizedQuery);
            if (query.length === 0 || matchNombre || matchRol) {
                const key = normalize(p.nombre);
                if (itemsMap[key]) {
                    itemsMap[key].rol = p.rol;
                } else {
                    itemsMap[key] = { valor: p.nombre, display: p.nombre, rol: p.rol };
                }
            }
        });

        let items = Object.values(itemsMap).sort((a, b) => {
            const nA = normalize(a.display), nB = normalize(b.display);
            const sA = nA.startsWith(normalizedQuery), sB = nB.startsWith(normalizedQuery);
            if (sA && !sB) return -1;
            if (!sA && sB) return 1;
            return a.display.localeCompare(b.display);
        });

        if (items.length > 0) {
            dropdown.innerHTML = items.map(item => {
                const badge = item.rol ? ` <span class="rol-badge">${item.rol}</span>` : '';
                return `<div class="dropdown-item" onclick="seleccionarOpcion('${item.valor.replace(/'/g, "\\'")}', 'profesor')">${item.display}${badge}</div>`;
            }).join('');
            dropdown.style.display = 'block';
        } else {
            dropdown.style.display = 'none';
        }

        input.onkeydown = (e) => {
            if (e.key === 'Enter' && items.length > 0) {
                seleccionarOpcion(items[0].valor, 'profesor');
                input.blur();
            }
        };
        return;
    }

    let matches = [];
    if (query.length === 0) {
        matches = rawData[modo];
    } else {
        const allMatches = rawData[modo].filter(item => normalize(item).includes(normalizedQuery));
        matches = allMatches.sort((a, b) => {
            const normA = normalize(a);
            const normB = normalize(b);
            const startsA = normA.startsWith(normalizedQuery);
            const startsB = normB.startsWith(normalizedQuery);
            if (startsA && !startsB) return -1;
            if (!startsA && startsB) return 1;
            return a.localeCompare(b);
        });
    }

    if (matches.length > 0) {
        dropdown.innerHTML = matches.map(item => `<div class="dropdown-item" onclick="seleccionarOpcion('${item.replace(/'/g, "\\'")}', '${modo}')">${item}</div>`).join('');
        dropdown.style.display = 'block';
    } else {
        dropdown.style.display = 'none';
    }

    input.onkeydown = (e) => {
        if (e.key === 'Enter' && matches.length > 0) {
            seleccionarOpcion(matches[0], modo);
            input.blur();
        }
    };
}

function seleccionarOpcion(valor, modo) {
    const input = document.querySelector(`#tab-${modo} .search-input, #tab-${modo} .search-input-fun, #tab-${modo} .minimal-input, #tab-${modo} .tech-input`);
    input.value = valor;
    document.querySelectorAll('.custom-dropdown, .custom-dropdown-fun, .minimal-dropdown, .tech-dropdown').forEach(d => d.style.display = 'none');
    buscarEnServidor(modo, valor);
}

document.addEventListener('click', (e) => {
    const isSearchInput = e.target.classList.contains('search-input') || 
                          e.target.classList.contains('search-input-fun') || 
                          e.target.classList.contains('minimal-input') || 
                          e.target.classList.contains('tech-input');
                          
    if (!isSearchInput) {
        document.querySelectorAll('.custom-dropdown, .custom-dropdown-fun, .minimal-dropdown, .tech-dropdown').forEach(d => d.style.display = 'none');
    } else {
        // Si ya está enfocado pero el dropdown se cerró (clic drag afuera), lo forzamos a abrir
        if (typeof e.target.onfocus === 'function') {
            e.target.onfocus(e);
        } else {
            e.target.dispatchEvent(new Event('focus'));
        }
    }
});

function abrirModal(titulo, html) {
    document.getElementById('modal-titulo').innerText = titulo;
    document.getElementById('modal-body').innerHTML = html;
    document.getElementById('modal-detalles').style.display = 'flex';
}

function cerrarModal() {
    document.getElementById('modal-detalles').style.display = 'none';
    // Remove selected class from any class block when closing
    document.querySelectorAll('.materia-bloque').forEach(b => b.classList.remove('selected'));
}

window.onclick = function(event) {
    const modal = document.getElementById('modal-detalles');
    if (event.target == modal) cerrarModal();
}

function navegarDesdeModal(modo, valor) {
    if (!valor || valor === '-' || valor === '?') return;
    
    // Cerrar el modal actual
    cerrarModal();
    
    // Bandera para evitar el autofocus automático que abre el dropdown
    window.isProgrammaticNavigation = true;
    
    // Simular el clic en la pestaña correspondiente para limpiar el estado y cambiar la vista
    const tabBtn = document.querySelector(`button[onclick*="tab-${modo}"]`);
    if (tabBtn) {
        tabBtn.click();
    }
    
    // Ejecutar búsqueda con un retardo mínimo para que el cambio de tab sea fluido
    setTimeout(() => {
        const input = document.querySelector(`#tab-${modo} .tech-input`);
        if (input) {
            input.value = valor;
            buscarEnServidor(modo, valor);
            // Asegurarnos de que el dropdown esté oculto
            const dropdown = document.getElementById(`dropdown-${modo}`);
            if (dropdown) dropdown.style.display = 'none';
        }
        window.isProgrammaticNavigation = false;
    }, 10);
}

function mostrarInfoClase(json, element) {
    // Remove selected class from any other block
    document.querySelectorAll('.materia-bloque').forEach(b => b.classList.remove('selected'));
    if (element) element.classList.add('selected');

    const c = JSON.parse(decodeURIComponent(json));
    let cursoDisplay = `${c.curso}° ${c.division}`;
    if (c.grupo && c.grupo.trim() !== '') { // Check if group exists and is not empty
        cursoDisplay += ` (Grupo: ${c.grupo})`;
    }

    let profesorLabel = "Profesor";
    let profesorValor = c.profesor;
    if (c.suplente_activo === 1) {
        profesorLabel = "Suplente";
        profesorValor = `${c.prof_suplente} (desde ${c.sup_ini} hasta ${c.sup_fin})`;
    }

    const html = `
        <div class="info-card">
            <div class="info-label">Materia</div>
            <div class="info-valor">${c.materia}</div>
            <div class="info-label">${profesorLabel}</div>
            <div class="clickable-valor" onclick="navegarDesdeModal('profesor', '${c.profesor.replace(/'/g, "\\'")}')">${profesorValor}</div>
            <div class="info-label">Curso</div>
            <div class="clickable-valor" onclick="navegarDesdeModal('curso', '${c.curso} ${c.division}')">${cursoDisplay}</div>
            <div class="info-label">Aula</div>
            <div class="clickable-valor" onclick="navegarDesdeModal('aula', '${(c.aula || '-').replace(/'/g, "\\'")}')">${c.aula || '-'}</div>
            <div class="info-label">Horario</div>
            <div class="info-valor">${c.hora_inicio} - ${c.hora_fin} (${c.dia})</div>
        </div>
    `;
    abrirModal('Información de la Clase', html);
}

function verDetalleSuperposicion(json) {
    const clases = JSON.parse(decodeURIComponent(json));
    let html = '<p style="margin-bottom:15px; color:#5f6368;">Se han detectado las siguientes clases en el mismo horario:</p>';
    clases.forEach(c => {
        html += `
            <div class="info-card overlap">
                <div class="info-label">Materia</div>
                <div class="info-valor">${c.materia}</div>
                <div class="info-label">Profesor</div>
                <div class="clickable-valor" onclick="navegarDesdeModal('profesor', '${c.profesor.replace(/'/g, "\\'")}')">${c.profesor}</div>
                <div class="info-label">Curso</div>
                <div class="clickable-valor" onclick="navegarDesdeModal('curso', '${c.curso} ${c.division}')">${c.curso}° ${c.division}</div>
                <div class="info-label">Aula</div>
                <div class="clickable-valor" onclick="navegarDesdeModal('aula', '${(c.aula || '-').replace(/'/g, "\\'")}')">${c.aula || '-'}</div>
                <div class="info-label">Horario</div>
                <div class="info-valor">${c.hora_inicio} - ${c.hora_fin}</div>
            </div>
        `;
    });
    abrirModal('⚠️ Superposición Detectada', html);
}

function cambiarTab(evt, idTab) {
    var i, tabcontent, tablinks;
    tabcontent = document.getElementsByClassName("seccion-busqueda");
    for (i = 0; i < tabcontent.length; i++) tabcontent[i].style.display = "none";
    
    // Support for multiple design styles (tabs, vertical tabs, fun tabs, minimal links, tech tags)
    tablinks = document.querySelectorAll(".tab-btn, .tab-btn-vertical, .tab-btn-fun, .nav-link, .tech-tag");
    for (i = 0; i < tablinks.length; i++) tablinks[i].classList.remove("active");
    
    document.getElementById(idTab).style.display = "block";
    evt.currentTarget.classList.add("active");
    
    // Reset views
    currentSearch.modo = null;
    currentSearch.valor = null;
    // Actualizar el hash al modo del tab activo (buscarEnServidor lo completa con /VALOR al buscar)
    const TAB_A_MODO = {
        'tab-profesor': 'profesor', 'tab-aula': 'aula', 'tab-curso': 'curso',
        'tab-horario_preceptor': 'horario_preceptor', 'tab-envivo': 'envivo'
    };
    const _modoTab = TAB_A_MODO[idTab];
    if (_modoTab) history.replaceState(null, '', '#/' + _modoTab);
    document.querySelectorAll('.search-input, .search-input-fun, .minimal-input, .tech-input').forEach(input => input.value = "");
    document.querySelectorAll('.custom-dropdown, .custom-dropdown-fun, .minimal-dropdown, .tech-dropdown').forEach(d => d.style.display = 'none');
    
    // Solo borramos el calendario si es una navegación manual y no estamos en modo comparación
    if (!window.isProgrammaticNavigation && !isComparacionMode) {
        document.getElementById('contenedor-calendario').innerHTML = "";
        document.getElementById('contenedor-lista').innerHTML = "";
    }
    
    document.getElementById('contenedor-dashboard').style.display = 'none';
    document.getElementById('contenedor-calendario').style.display = 'block';
    document.getElementById('contenedor-lista').style.display = 'none';
    
    // Header management
    const workspaceHeader = document.getElementById('workspace-calendar-header');
    const calendarTitle = document.getElementById('calendar-title');
    if (!isComparacionMode) {
        if (workspaceHeader) workspaceHeader.style.display = 'none';
        if (calendarTitle) calendarTitle.textContent = "";
    }

    if (idTab === 'tab-envivo') {
        document.getElementById('contenedor-calendario').style.display = 'none';
        document.getElementById('contenedor-dashboard').style.display = 'block';
        iniciarDashboard();
    } else if (idTab === 'tab-horario_preceptor') {
        // En deep-link (navegación programática) no cargamos la planilla:
        // buscarEnServidor renderiza directo la tabla del preceptor (evita race en contenedor-lista)
        if (!window.isProgrammaticNavigation) mostrarPlanillaCursos();
    } else {
        // Focus the input inside the active tab ONLY if not navigating from modal
        if (!window.isProgrammaticNavigation) {
            const activeInput = document.querySelector(`#${idTab} input[type="text"]`);
            if (activeInput) {
                // Use setTimeout to ensure the element is fully rendered and visible before focusing
                setTimeout(() => activeInput.focus(), 50);
            }
        }
    }
}

let dashboardInterval = null;
let isManualClock = false;
let manualTime = null;
let manualDate = null;
let lastDashboardData = []; // Cache para filtrar en tiempo real

function setManualTime() {
    if (isManualClock) {
        manualTime = document.getElementById('manual-clock-input').value;
        manualDate = document.getElementById('manual-date-input').value;
        actualizarReloj();
        cargarDatosDashboard();
    }
}

function iniciarDashboard() {
    actualizarReloj();
    if (dashboardInterval) clearInterval(dashboardInterval);
    dashboardInterval = setInterval(() => {
        actualizarReloj();
        if (document.getElementById('tab-envivo').style.display === 'block' && !isManualClock) {
            cargarDatosDashboard();
        }
    }, 1000);
    cargarDatosDashboard();
}

function actualizarReloj() {
    const clock = document.getElementById('dashboard-clock');
    if (clock) {
        if (isManualClock && manualTime) {
            clock.textContent = manualTime + ":00";
        } else {
            const now = new Date();
            clock.textContent = now.toLocaleTimeString('es-AR', { hour12: false });
        }
    }
}

function cargarDatosDashboard() {
    fetch('/api/dashboard')
        .then(res => res.json())
        .then(filas => {
            lastDashboardData = filas;
            renderizarDashboard(filas);
        })
        .catch(err => console.error("Error Dashboard:", err));
}

function renderizarDashboard(filas) {
    if (!filas) return;
    const contenedor = document.getElementById('contenedor-dashboard');
    const filterInput = document.getElementById('dashboard-filter-input');
    const filterText = normalize(filterInput ? filterInput.value : "");
    const now = new Date();
    
    // Obtenemos el día actual (Lunes a Viernes)
    const dayNames = ["Domingo", "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"];
    
    let currentDay;
    let currentTime;

    if (isManualClock && manualDate && manualTime) {
        const [year, month, day] = manualDate.split('-').map(Number);
        const d = new Date(year, month - 1, day);
        currentDay = dayNames[d.getDay()];
        
        const [h, m] = manualTime.split(':').map(Number);
        currentTime = h * 60 + m;
    } else {
        currentDay = dayNames[now.getDay()];
        currentTime = now.getHours() * 60 + now.getMinutes();
    }

    const timeToMin = (t) => {
        if (!t) return 0;
        const [h, m] = t.split(':').map(Number);
        return h * 60 + m;
    };

    let inProgress = [];
    let upcoming = [];

    filas.forEach(f => {
        if (f.dia !== currentDay) return;

        // Aplicar filtro si existe texto
        if (filterText) {
            const curso = normalize(`${f.curso} ${f.division}`);
            const prof = normalize(f.suplente_activo === 1 ? f.prof_suplente : f.profesor);
            if (!curso.includes(filterText) && !prof.includes(filterText)) {
                return;
            }
        }

        const start = timeToMin(f.hora_inicio);
        const end = timeToMin(f.hora_fin);

        if (currentTime >= start && currentTime <= end) {
            inProgress.push(f);
        } else if (currentTime < start && start < currentTime + (HORAS_PROXIMAS * 60)) {
            upcoming.push(f);
        }
    });

    inProgress.sort((a, b) => timeToMin(a.hora_inicio) - timeToMin(b.hora_inicio));
    upcoming.sort((a, b) => timeToMin(a.hora_inicio) - timeToMin(b.hora_inicio));

    const renderList = (list) => {
        if (list.length === 0) return `<div style="text-align:center; padding:20px; color:#5f6368;">${filterText ? 'SIN COINCIDENCIAS' : 'SIN ACTIVIDAD'}</div>`;
        return list.map(f => {
            let profName = f.profesor;
            if (f.suplente_activo === 1) profName = 'SUPLENTE: ' + f.prof_suplente;
            const jsonClase = encodeURIComponent(JSON.stringify(f));
            return `
                <div class="class-item-light" style="cursor:pointer;" onclick="mostrarInfoClase('${jsonClase}', this)">
                    <div class="class-time-light">${f.hora_inicio} - ${f.hora_fin}</div>
                    <div class="class-info-light">
                        <span class="class-materia-light">${f.curso}° ${f.division} | ${profName}</span>
                        <span class="class-meta-light">${f.materia}</span>
                    </div>
                    <div class="class-room-light">${f.aula || '-'}</div>
                </div>
            `;
        }).join('');
    };

    contenedor.innerHTML = `
        <div class="dashboard-grid-light">
            <div class="dashboard-column-light in-progress">
                <h2>En Curso ${filterText ? '(Filtrado)' : ''}</h2>
                <div class="class-list-light">${renderList(inProgress)}</div>
            </div>
            <div class="dashboard-column-light upcoming">
                <h2>Próximas ${filterText ? '(Filtrado)' : ''}</h2>
                <div class="class-list-light">${renderList(upcoming)}</div>
            </div>
        </div>
    `;
}

function buscarEnServidor(modo, valor) {
    const workspaceHeader = document.getElementById('workspace-calendar-header');
    const calendarTitle = document.getElementById('calendar-title');
    const preceptorContainer = document.getElementById('preceptor-info-container');
    if (!valor) {
        if (workspaceHeader) workspaceHeader.style.display = 'none';
        return;
    }

    // En modo comparación, los preceptores no son comparables
    if (isComparacionMode && modo === 'horario_preceptor') {
        alert("Los horarios de preceptores no se pueden agregar al modo comparación.");
        return;
    }

    currentSearch.modo = modo;
    currentSearch.valor = valor;

    // Hash routing: hacer la búsqueda compartible vía URL (solo búsquedas individuales)
    if (!isComparacionMode && ['profesor', 'curso', 'aula', 'horario_preceptor'].includes(modo)) {
        history.replaceState(null, '', '#/' + modo + '/' + encodeURIComponent(valor));
    }

    if (!isComparacionMode && workspaceHeader && calendarTitle) {
        workspaceHeader.style.display = 'flex';
        calendarTitle.textContent = `Horario de ${modo.replace('_', ' ')}: ${valor}`;
        if (preceptorContainer) preceptorContainer.innerHTML = "";
    }

    document.getElementById('contenedor-calendario').innerHTML = '';
    const _lista = document.getElementById('contenedor-lista');
    if (_lista) _lista.innerHTML = '';

    // ── Camino rápido: resolver desde la caché en memoria, sin red ──
    const filasLocal = filtrarClasesLocal(modo, valor);
    if (filasLocal !== null) {
        let filas = filasLocal;
        if (modo === 'profesor' && !isComparacionMode) {
            const filasPersonal = (_allPersonal || [])
                .filter(p => p.nombre === valor)
                .map(p => personalToFila(p));
            filas = [...filas, ...filasPersonal];
        }
        procesarResultadoBusqueda(modo, valor, filas);
        return;
    }

    // ── Horario individual de preceptor desde la caché (tabla horarios_preceptores) ──
    if (modo === 'horario_preceptor' && _horariosPreceptores) {
        const cached = _horariosPreceptores[valor];
        if (cached !== undefined) {
            procesarResultadoBusqueda(modo, valor, cached);
            return;
        }
        // nombre no exacto → cae al fetch (el server aplica LIKE %nombre%)
    }

    // ── Fallback a red (datos aún no cargados, o caché vacía) ──
    if (modo === 'profesor' && !isComparacionMode) {
        Promise.all([
            fetch(`/api/profesor/${valor}`).then(r => r.json()),
            fetch(`/api/personal/${encodeURIComponent(valor)}`).then(r => r.json())
        ]).then(([filasClases, filasPersonal]) => {
            const filasConvertidas = (filasPersonal || []).map(p => personalToFila(p));
            procesarResultadoBusqueda(modo, valor, [...filasClases, ...filasConvertidas]);
        }).catch(mostrarErrorBusqueda);
        return;
    }

    const endpoint = modo === 'horario_preceptor' ? `/api/horario_preceptor/${valor}` : `/api/${modo}/${valor}`;

    fetch(endpoint)
        .then(res => res.json())
        .then(filas => procesarResultadoBusqueda(modo, valor, filas))
        .catch(mostrarErrorBusqueda);
}

// Renderiza el resultado de una búsqueda, ya venga de la caché o de la red.
function procesarResultadoBusqueda(modo, valor, filas) {
    if (isComparacionMode) {
        const yaExiste = comparacionItems.find(i => i.modo === modo && i.valor === valor);
        if (yaExiste) {
            alert(`"${valor}" ya está en la comparación.`);
            return;
        }
        const color = COMPARACION_COLORS[comparacionItems.length % COMPARACION_COLORS.length];
        comparacionItems.push({ modo, valor, filas, color, label: valor });
        actualizarEstadoComparacion();
        generarCalendarioComparacion(comparacionItems);
    } else {
        lastFilas = filas;
        if (modo === 'horario_preceptor') {
            renderizarTablaPreceptor(filas);
        } else {
            generarCalendario(filas, modo);
            if (modo === 'curso') {
                const preceptorLocal = obtenerPreceptorLocal(valor);
                if (preceptorLocal !== null) {
                    if (preceptorLocal) renderizarPreceptor(preceptorLocal);
                } else {
                    fetch(`/api/preceptor/${valor}`)
                        .then(r => r.json())
                        .then(preceptorData => {
                            if (preceptorData) renderizarPreceptor(preceptorData);
                        });
                }
            }
        }
    }
}

function mostrarErrorBusqueda(err) {
    console.error("Error API:", err);
    const c = document.getElementById('contenedor-calendario');
    c.innerHTML = `<div style="padding:40px; text-align:center; color:#c0392b;"><strong>Error al buscar el horario.</strong><br>Es posible que los datos estén actualizándose. Intentá de nuevo en unos segundos.</div>`;
    c.style.display = 'block';
}

function mostrarPlanillaCursos() {
    document.getElementById('contenedor-calendario').style.display = 'none';
    const lista = document.getElementById('contenedor-lista');
    lista.style.display = 'block';
    lista.innerHTML = '<div style="padding:20px;text-align:center;color:#70757a;">Cargando...</div>';
    const wh = document.getElementById('workspace-calendar-header');
    if (wh) wh.style.display = 'none';
    if (_planillaPreceptores) {
        renderizarPlanillaCursos(_planillaPreceptores);
        return;
    }
    fetch('/api/planilla_preceptores')
        .then(r => r.json())
        .then(filas => renderizarPlanillaCursos(filas))
        .catch(() => { lista.innerHTML = '<div style="padding:20px;color:#c0392b;">Error al cargar la planilla.</div>'; });
}

function renderizarPlanillaCursos(filas) {
    const lista = document.getElementById('contenedor-lista');
    if (!filas || filas.length === 0) {
        lista.innerHTML = "<div style='padding:20px;text-align:center;'>No hay datos disponibles.</div>";
        return;
    }
    const abrev = { 'MAÑANA': 'M', 'TARDE': 'T', 'VESPERTINO': 'V' };
    const rows = filas.map(f => {
        const turno = (f.turno || '').toUpperCase();
        const tm = f.manana || '';
        const tt = f.tarde  || '';
        const tv = f.vespertino  || '';
        return `<tr>
        <td>${f.curso}° ${f.division}</td>
        <td>${abrev[turno] || f.turno || ''}</td>
        <td>${turno === 'MAÑANA'     ? `<strong>${tm}</strong>` : tm}</td>
        <td>${turno === 'TARDE'      ? `<strong>${tt}</strong>` : tt}</td>
        <td>${turno === 'VESPERTINO' ? `<strong>${tv}</strong>` : tv}</td>
    </tr>`;
    }).join('');
    lista.innerHTML = `
        <table style="width:100%;table-layout:auto;">
            <thead><tr>
                <th>CURSO Y DIVISIÓN</th><th>TURNO</th><th>MAÑANA</th><th>TARDE</th><th>VESPERTINO</th>
            </tr></thead>
            <tbody>${rows}</tbody>
        </table>`;
}

function renderizarTablaPreceptor(filas) {
    const contenedorCalendario = document.getElementById('contenedor-calendario');
    const contenedorLista = document.getElementById('contenedor-lista');

    contenedorCalendario.style.display = 'none';
    contenedorLista.style.display = 'block';

    if (!filas || filas.length === 0) {
        contenedorLista.innerHTML = "<div style='padding:20px; text-align:center; color:#70757a;'>No hay horarios cargados para este preceptor.</div>";
        return;
    }

    const turnosOrden = ["MAÑANA", "TARDE", "VESPERTINO"];
    const turnosEncontrados = {};

    filas.forEach(f => {
        const turno = f.turno ? f.turno.toUpperCase() : "MAÑANA";
        if (!turnosEncontrados[turno]) {
            turnosEncontrados[turno] = [];
        }
        turnosEncontrados[turno].push(f);
    });

    let html = '';

    turnosOrden.forEach(turno => {
        if (!turnosEncontrados[turno]) return;

        const filasTurno = turnosEncontrados[turno];
        const diasSemana = window.APP_DATA.dias.map(d => d.normalize('NFD').replace(/[̀-ͯ]/g, '').toUpperCase());
        
        const cursosMap = {};
        filasTurno.forEach(f => {
            const key = `${f.preceptor}|${f.curso}|${f.division}|${f.estado}`;
            if (!cursosMap[key]) {
                cursosMap[key] = { preceptor: f.preceptor, curso: f.curso, division: f.division || '', estado: f.estado || '-', dias: [] };
            }
            cursosMap[key].dias.push(f.dia.toUpperCase());
        });
        const cursosLista = Object.values(cursosMap);

        html += `
            <h3 style="margin-top: 30px; margin-bottom: 15px; color: var(--primary); border-bottom: 2px solid var(--secondary); padding-bottom: 5px;">TURNO ${turno}</h3>
            <table style="table-layout: fixed; margin-bottom: 30px; width: 100%;">
                <thead>
                    <tr>
                        <th style="width: 20%;">PRECEPTOR</th>
                        <th style="width: 15%;">ESTADO</th>
                        ${diasSemana.map(d => `<th>${d}</th>`).join('')}
                    </tr>
                </thead>
                <tbody>
                    ${cursosLista.map(c => `
                        <tr>
                            <td style="padding: 10px; text-align: center;">${c.preceptor}</td>
                            <td style="padding: 10px; text-align: center;">${c.estado}</td>
                            ${diasSemana.map(d => `
                                <td style="padding: 10px; text-align: center; vertical-align: middle;">
                                    ${c.dias.includes(d) 
                                        ? `<div class="preceptor-curso-item" style="margin: 0 auto;">${c.curso}° ${c.division}</div>`
                                        : '<span style="opacity:0.3; font-style:italic;">-</span>'}
                                </td>
                            `).join('')}
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
    });

    contenedorLista.innerHTML = html;
}
function renderizarPreceptor(data) {
    const container = document.getElementById('preceptor-info-container');
    if (!container) return;

    const labels = {
        "preceptores_manana": "T.M:",
        "preceptores_tarde": "T.T:",
        "preceptores_vespertino": "T.V:"
    };

    const turnoCurso = (data.turno || "").trim().toUpperCase();
    const mapping = {
        "MAÑANA": "preceptores_manana",
        "TARDE": "preceptores_tarde",
        "VESPERTINO": "preceptores_vespertino"
    };
    const keyPrincipal = mapping[turnoCurso] || null;

    let html = "";
    ["preceptores_manana", "preceptores_tarde", "preceptores_vespertino"].forEach(key => {
        if (data[key] && data[key].trim() !== "") {
            const esPrincipal = (key === keyPrincipal);
            const label = esPrincipal ? "PRECEPTOR PRINCIPAL" : "Preceptor";
            const extraClass = esPrincipal ? ' class="principal"' : "";
            html += `<span${extraClass}>${label} ${labels[key]} <b>${data[key].trim()}</b></span>`;
        } else {
            html += `<span></span>`;
        }
    });

    container.innerHTML = html;
}

function calcularEstilosBloques(cluster) {
    const numClases = cluster.length;
    let styles = new Array(numClases).fill("");
    
    if (numClases <= 2) {
        let leftOcupado = false;
        let rightOcupado = false;
        let assignments = new Array(numClases).fill(null);

        for (let i = 0; i < numClases; i++) {
            let g = (cluster[i].grupo || "").trim().toUpperCase();
            if (g === 'A' && !leftOcupado) {
                assignments[i] = 'left';
                leftOcupado = true;
            } else if (g === 'B' && !rightOcupado) {
                assignments[i] = 'right';
                rightOcupado = true;
            }
        }

        for (let i = 0; i < numClases; i++) {
            if (assignments[i] === null) {
                if (!leftOcupado && numClases > 1) {
                    assignments[i] = 'left';
                    leftOcupado = true;
                } else if (!rightOcupado && numClases > 1) {
                    assignments[i] = 'right';
                    rightOcupado = true;
                } else {
                    assignments[i] = 'full';
                }
            }
        }

        for (let i = 0; i < numClases; i++) {
            if (assignments[i] === 'left') {
                styles[i] = `width: calc(50% - 6px); left: 4px; right: auto;`;
            } else if (assignments[i] === 'right') {
                styles[i] = `width: calc(50% - 6px); right: 4px; left: auto;`;
            } else {
                styles[i] = `left: 4px; right: 4px; width: auto;`;
            }
        }
    } else {
        const anchoPct = 100 / numClases;
        for (let i = 0; i < numClases; i++) {
            const leftPct = anchoPct * i;
            styles[i] = `width: calc(${anchoPct}% - 6px); left: calc(${leftPct}% + 4px); right: auto;`;
        }
    }
    return styles;
}

function generarCalendario(filas, modo) {
    const contenedor = document.getElementById('contenedor-calendario');
    const timeToMin = (t) => {
        if (!t || typeof t !== 'string' || !t.includes(':')) return 0;
        const [h, m] = t.split(':').map(Number);
        return h * 60 + m;
    };

    try {
        if (!filas || filas.length === 0) {
            contenedor.innerHTML = "<div style='padding:20px; text-align:center; color:#70757a;'>No hay clases para mostrar.</div>";
            const workspaceHeader = document.getElementById('workspace-calendar-header');
            if (workspaceHeader) workspaceHeader.style.display = 'none';
            return;
        }

        const dias = window.APP_DATA.dias;
        let tiempos = new Set();
        filas.forEach(f => {
            if (f.hora_inicio) tiempos.add(f.hora_inicio);
            if (f.hora_fin) tiempos.add(f.hora_fin);
        });
        
        if (tiempos.size === 0) {
            contenedor.innerHTML = "<div style='padding:20px; text-align:center; color:#70757a;'>Los datos no contienen horarios válidos.</div>";
            return;
        }

        const horariosDinamicos = Array.from(tiempos).sort((a, b) => timeToMin(a) - timeToMin(b));
        const minMins = timeToMin(horariosDinamicos[0]) - 30; 
        const maxMins = timeToMin(horariosDinamicos[horariosDinamicos.length - 1]) + 30;
        const HORA_MIN = Math.max(0, minMins);
        const HORA_MAX = Math.min(1440, maxMins);
        const duracionTotal = HORA_MAX - HORA_MIN;
        const ALTURA_TOTAL = Math.max(duracionTotal * 1.05, 450); 

        const getPosicionY = (horaStr) => {
            if (!horaStr) return 0;
            const minutos = timeToMin(horaStr);
            const porcentaje = (minutos - HORA_MIN) / (HORA_MAX - HORA_MIN);
            return porcentaje * ALTURA_TOTAL;
        };

        let html = '<div class="calendario-grid">';
        html += '<div class="cabecera-vacia"></div>';
        dias.forEach(dia => {
            html += `<div class="cabecera-dia"><div class="dia-nombre">${dia}</div></div>`;
        });

        html += `<div class="columna-horas" style="height:${ALTURA_TOTAL}px; position:relative;">`;
        horariosDinamicos.forEach(hora => {
            const top = getPosicionY(hora);
            html += `<div class="hora-label" style="top:${top}px;">${hora}</div>`;
        });
        html += '</div>';

        dias.forEach(dia => {
            html += `<div class="columna-dia" style="height:${ALTURA_TOTAL}px;">`;
            horariosDinamicos.forEach(hora => {
                const top = getPosicionY(hora);
                html += `<div class="grid-line-horizontal" style="top:${top}px;"></div>`;
            });

            const clasesDelDia = filas.filter(f => f.dia === dia).sort((a,b) => timeToMin(a.hora_inicio) - timeToMin(b.hora_inicio));
            let procesados = new Set();
            for (let i = 0; i < clasesDelDia.length; i++) {
                if (procesados.has(i)) continue;
                let cluster = [clasesDelDia[i]];
                let clusterIdx = [i];
                let maxFin = timeToMin(clasesDelDia[i].hora_fin);
                for (let j = i + 1; j < clasesDelDia.length; j++) {
                    let inicioJ = timeToMin(clasesDelDia[j].hora_inicio);
                    if (inicioJ < maxFin) {
                        cluster.push(clasesDelDia[j]);
                        clusterIdx.push(j);
                        maxFin = Math.max(maxFin, timeToMin(clasesDelDia[j].hora_fin));
                    } else { break; }
                }

                const sinLicenciadas = cluster.filter(c => !(c.suplente_activo == 1 && c.profesor === currentSearch.valor));
                const clusterFinal = cluster.length > 1 && sinLicenciadas.length > 0 ? sinLicenciadas : cluster;

                const todosTienenGrupo = clusterFinal.every(c => c.grupo && c.grupo.trim() !== "");
                const haySuperposicion = clusterFinal.length > 1 && (modo === 'aula' || modo === 'profesor' || !todosTienenGrupo);

                if (haySuperposicion) {
                    const todosPermitenSuperposicion = clusterFinal.every(c => c.superposicion == 1);
                    if (todosPermitenSuperposicion) {
                        const estilos = calcularEstilosBloques(clusterFinal);
                        const numClases = clusterFinal.length;
                        clusterFinal.forEach((clase, idxInCluster) => {
                            const inicio = clase.hora_inicio;
                            const fin = clase.hora_fin;
                            const top = getPosicionY(inicio) + 2;
                            const bottom = getPosicionY(fin) - 2;
                            const alto = Math.max(bottom - top, 20);
                            const styleExtra = estilos[idxInCluster];
                            const esPersonal = clase.tipo === 'personal';

                            const esLicenciadaProf = modo === 'profesor' && clase.suplente_activo === 1 && clase.profesor === currentSearch.valor;
                            const jsonClase = encodeURIComponent(JSON.stringify(clase));
                            html += `
                                <div class="materia-bloque${esPersonal ? ' personal-cargo-bloque' : ''}"
                                     style="top: ${top}px; height: ${alto}px; ${styleExtra}${esPersonal ? '' : (esLicenciadaProf ? ' opacity:0.28;' : '')}"
                                     onclick="mostrarInfoClase('${jsonClase}', this)"
                                     onmouseover="showTooltip(event, '${clase.materia.replace(/'/g, "\\'")}', '${clase.profesor.replace(/'/g, "\\'")}', '-', '${inicio} - ${fin}', '-')"
                                     onmouseout="hideTooltip()">
                                    <div class="materia-contenido">
                                        ${esPersonal ?
                                            `<div class="materia-nombre">${clase.materia}</div>
                                             <div class="materia-detalles">${inicio} - ${fin}</div>` :
                                            `<div class="materia-nombre">${clase.materia}</div>
                                             <div class="materia-detalles">
                                                ${(() => {
                                                    const profName = (clase.suplente_activo === 1 && clase.prof_suplente) ? 'SUPLENTE: ' + clase.prof_suplente : (clase.profesor || '-');
                                                    return modo === 'aula' ? profName : (modo === 'profesor' ? `${clase.curso}° ${clase.division}` : profName);
                                                })()}
                                             </div>`
                                        }
                                    </div>
                                    ${esPersonal ? '' : `<div class="aula-indicador${!(/\d/g.test(clase.aula)) && !(modo == "aula") ? ' sin-numero' : ''}">${modo === 'aula' ? `${clase.curso}° ${clase.division}` : (clase.aula || '?')}</div>`}
                                </div>`;
                        });
                    } else {
                        const top = getPosicionY(clusterFinal[0].hora_inicio);
                        const latestEndClase = clusterFinal.reduce((max, c) => timeToMin(c.hora_fin) > timeToMin(max.hora_fin) ? c : max);
                        const bottom = getPosicionY(latestEndClase.hora_fin);
                        const alto = Math.max(bottom - top, 30);
                        const jsonDetalles = encodeURIComponent(JSON.stringify(clusterFinal));
                        html += `<div class="bloque-superposicion" style="top: ${top}px; height: ${alto}px;" onclick="verDetalleSuperposicion('${jsonDetalles}')">⚠️ Superposición (${clusterFinal.length})</div>`;
                    }
                    clusterIdx.forEach(idx => procesados.add(idx));
                } else {
                    const estilos = calcularEstilosBloques(clusterFinal);
                    const numClases = clusterFinal.length;
                    clusterFinal.forEach((clase, idxInCluster) => {
                        const inicio = clase.hora_inicio;
                        const fin = clase.hora_fin;
                        const top = getPosicionY(inicio) + 2;
                        const bottom = getPosicionY(fin) - 2;
                        const alto = Math.max(bottom - top, 20);
                        const styleExtra = estilos[idxInCluster];
                        const esPersonal = clase.tipo === 'personal';
                        const esLicenciadaProf = modo === 'profesor' && clase.suplente_activo === 1 && clase.profesor === currentSearch.valor;
                        const jsonClase = encodeURIComponent(JSON.stringify(clase));
                        html += `
                            <div class="materia-bloque${esPersonal ? ' personal-cargo-bloque' : ''}"
                                 style="top: ${top}px; height: ${alto}px; ${styleExtra}${esPersonal ? '' : (esLicenciadaProf ? ' opacity:0.28;' : '')}"
                                 onclick="mostrarInfoClase('${jsonClase}', this)"
                                 onmouseover="showTooltip(event, '${clase.materia.replace(/'/g, "\\'")}', '${clase.profesor.replace(/'/g, "\\'")}', '-', '${inicio} - ${fin}', '-')"
                                 onmouseout="hideTooltip()">
                                <div class="materia-contenido">
                                    ${esPersonal ?
                                        `<div class="materia-nombre">${clase.materia}</div>
                                         <div class="materia-detalles">${inicio} - ${fin}</div>` :
                                        `<div class="materia-nombre">${clase.materia}</div>
                                         <div class="materia-detalles">
                                            ${(() => {
                                                const profName = (clase.suplente_activo === 1 && clase.prof_suplente) ? 'SUPLENTE: ' + clase.prof_suplente : (clase.profesor || '-');
                                                return modo === 'aula' ? profName : (modo === 'profesor' ? `${clase.curso}° ${clase.division}` : profName);
                                            })()}
                                         </div>`
                                    }
                                </div>
                                ${esPersonal ? '' : `<div class="aula-indicador${!(/\d/g.test(clase.aula)) && !(modo == "aula") ? ' sin-numero' : ''}">${modo === 'aula' ? `${clase.curso}° ${clase.division}` : (clase.aula || '?')}</div>`}
                            </div>`;
                    });
                    clusterIdx.forEach(idx => procesados.add(idx));
                }
            }
            html += '</div>';
        });
        html += '</div>';
        contenedor.innerHTML = html;
        contenedor.style.display = 'block';
    } catch (err) {
        console.error("Error crítico:", err);
    }
}

function showTooltip(e, materia, profe, aula, hora, curso) {
    const tooltip = document.getElementById('calendar-tooltip');
    tooltip.innerHTML = `
        <div class="tooltip-header">${materia}</div>
        <div class="tooltip-item"><b>Curso:</b> ${curso}</div>
        <div class="tooltip-item"><b>Prof:</b> ${profe}</div>
        <div class="tooltip-item"><b>Aula:</b> ${aula}</div>
        <div class="tooltip-item"><b>Horario:</b> ${hora}</div>
    `;
    tooltip.style.display = 'block';
    tooltip.style.left = (e.clientX + 15) + 'px';
    tooltip.style.top = (e.clientY + 15) + 'px';
}

function hideTooltip() {
    document.getElementById('calendar-tooltip').style.display = 'none';
}


function exportarAPDF() {
    if (isPlanillaGeneral) {
        window.open(`/export/pdf/planilla/${selectedDay}|${selectedFloor}`, '_blank');
    } else if (currentSearch.modo && currentSearch.valor) {
        window.open(`/export/pdf/${currentSearch.modo}/${currentSearch.valor}`, '_blank');
    }
}

function exportarPlanillaPreceptoresPDF() {
    window.open('/export/pdf/planilla_preceptores', '_blank');
}

/* --- Impresión múltiple de cursos --- */
let cursosSeleccionadosPDF = new Set();

function abrirModalImprimirCursos() {
    document.getElementById('slide-curso').classList.remove('open');
    document.getElementById('trigger-curso').classList.remove('panel-open');

    cursosSeleccionadosPDF = new Set();

    const cursos = rawData['curso'] || [];
    const porAnio = {};
    cursos.forEach(c => {
        const anio = c.split('°')[0].trim();
        if (!porAnio[anio]) porAnio[anio] = [];
        porAnio[anio].push(c);
    });

    let html = `<div class="print-cursos-selector">
        <button class="print-todos-btn" id="print-btn-todos" onclick="togglePrintTodos()">SELECCIONAR TODOS</button>
        <div class="print-cursos-filas">`;
    Object.keys(porAnio).forEach(anio => {
        html += `<div class="print-cursos-fila">
            <button class="print-anio-btn" data-anio="${anio}" onclick="togglePrintAnio('${anio}')">TODO ${anio}°</button>
            <div class="print-cursos-chips">
                ${porAnio[anio].map(c => `<button class="print-curso-chip" data-curso="${c}" onclick="togglePrintCurso('${c}')">${c.replace('° ', '°')}</button>`).join('')}
            </div>
        </div>`;
    });
    html += `</div>
        <div class="print-cursos-footer">
            <span id="print-contador" class="print-contador">Seleccionados: 0</span>
            <button class="print-generar-btn" id="print-generar-btn" onclick="generarPDFCursosSeleccionados()" disabled>GENERAR PDF</button>
        </div>
    </div>`;

    abrirModal('IMPRIMIR HORARIOS', html);
}

function togglePrintCurso(valor) {
    if (cursosSeleccionadosPDF.has(valor)) cursosSeleccionadosPDF.delete(valor);
    else cursosSeleccionadosPDF.add(valor);
    actualizarSeleccionImpresion();
}

function togglePrintAnio(anio) {
    const cursosAnio = (rawData['curso'] || []).filter(c => c.split('°')[0].trim() === anio);
    const todosMarcados = cursosAnio.length > 0 && cursosAnio.every(c => cursosSeleccionadosPDF.has(c));
    cursosAnio.forEach(c => todosMarcados ? cursosSeleccionadosPDF.delete(c) : cursosSeleccionadosPDF.add(c));
    actualizarSeleccionImpresion();
}

function togglePrintTodos() {
    const cursos = rawData['curso'] || [];
    if (cursosSeleccionadosPDF.size === cursos.length) cursosSeleccionadosPDF.clear();
    else cursos.forEach(c => cursosSeleccionadosPDF.add(c));
    actualizarSeleccionImpresion();
}

function actualizarSeleccionImpresion() {
    const cursos = rawData['curso'] || [];
    document.querySelectorAll('.print-curso-chip').forEach(chip => {
        chip.classList.toggle('selected', cursosSeleccionadosPDF.has(chip.dataset.curso));
    });
    document.querySelectorAll('.print-anio-btn').forEach(btn => {
        const cursosAnio = cursos.filter(c => c.split('°')[0].trim() === btn.dataset.anio);
        btn.classList.toggle('selected', cursosAnio.length > 0 && cursosAnio.every(c => cursosSeleccionadosPDF.has(c)));
    });
    const btnTodos = document.getElementById('print-btn-todos');
    if (btnTodos) btnTodos.classList.toggle('selected', cursos.length > 0 && cursosSeleccionadosPDF.size === cursos.length);
    const contador = document.getElementById('print-contador');
    if (contador) contador.textContent = `Seleccionados: ${cursosSeleccionadosPDF.size}`;
    const btnGenerar = document.getElementById('print-generar-btn');
    if (btnGenerar) btnGenerar.disabled = cursosSeleccionadosPDF.size === 0;
}

function generarPDFCursosSeleccionados() {
    const cursos = rawData['curso'] || [];
    if (cursosSeleccionadosPDF.size === 0) return;
    if (cursosSeleccionadosPDF.size === cursos.length) {
        window.open('/export/pdf/cursos/todos', '_blank');
    } else {
        const lista = cursos.filter(c => cursosSeleccionadosPDF.has(c));
        window.open('/export/pdf/cursos/' + encodeURIComponent(lista.join(',')), '_blank');
    }
    cerrarModal();
}

document.addEventListener('fullscreenchange', () => {
    if (document.fullscreenElement) {
        document.body.classList.add('is-fullscreen');
    } else {
        document.body.classList.remove('is-fullscreen');
    }
});

document.addEventListener('keydown', (e) => {
    if (e.key === 'F11') {
        e.preventDefault();
        if (!document.fullscreenElement) {
            document.documentElement.requestFullscreen().catch(err => {
                console.log(`Error attempting to enable fullscreen: ${err.message}`);
            });
        } else {
            if (document.exitFullscreen) {
                document.exitFullscreen();
            }
        }
    }
});

function generarBotonesPisos() {
    const container = document.getElementById('planilla-tabs-pisos');
    if (!container || !window.APP_DATA || !window.APP_DATA.floorMapping) return;
    container.innerHTML = '';
    Object.keys(window.APP_DATA.floorMapping).forEach((piso, index) => {
        const btn = document.createElement('button');
        btn.className = 'planilla-tab-btn' + (index === 0 ? ' active' : '');
        btn.textContent = piso;
        btn.onclick = function() { setPisoPlanilla(this, piso); };
        container.appendChild(btn);
    });
}

// ─── TEMA: blueprint (claro) ↔ nocturno (oscuro) ─────────────────────────────
const TEMAS_VALIDOS = ['blueprint', 'nocturno'];

// Íconos SVG (luna = pasar a oscuro; sol = volver a claro)
const ICONO_LUNA = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>';
const ICONO_SOL  = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>';

function applyTheme(nombre) {
    if (!TEMAS_VALIDOS.includes(nombre)) nombre = 'blueprint';
    const esOscuro = nombre === 'nocturno';
    document.body.setAttribute('data-theme', nombre);
    document.body.toggleAttribute('data-dark', esOscuro);
    localStorage.setItem('appmitre-theme', nombre);
    const btn = document.getElementById('btn-tema');
    if (btn) {
        btn.innerHTML = esOscuro ? ICONO_SOL : ICONO_LUNA;
        btn.title = esOscuro ? 'Modo claro' : 'Modo nocturno';
    }
}

function toggleTheme() {
    const actual = document.body.getAttribute('data-theme');
    applyTheme(actual === 'nocturno' ? 'blueprint' : 'nocturno');
}

function initTheme() {
    applyTheme(localStorage.getItem('appmitre-theme') || 'blueprint');
}

document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    generarBotonesPisos();
    const activeTab = document.querySelector('.seccion-busqueda.active');
    if (activeTab && activeTab.id === 'tab-envivo') {
        iniciarDashboard();
    }
});

function toggleMenu(e, id) {
    if (e) e.stopPropagation();
    const menu = document.getElementById(id);
    const isVisible = menu.style.display === "block";
    document.querySelectorAll('.menu-dropdown').forEach(m => m.style.display = 'none');
    menu.style.display = isVisible ? "none" : "block";
}

function toggleManualMode(checkbox) {
    const controls = document.getElementById('manual-controls');
    isManualClock = checkbox.checked;
    
    if (isManualClock) {
        controls.style.display = 'flex';
        const now = new Date();
        document.getElementById('manual-clock-input').value = now.toTimeString().slice(0, 5);
        document.getElementById('manual-date-input').value = now.toISOString().split('T')[0];
        manualTime = document.getElementById('manual-clock-input').value;
        manualDate = document.getElementById('manual-date-input').value;
    } else {
        controls.style.display = 'none';
        manualTime = null;
        manualDate = null;
        actualizarReloj();
    }
    cargarDatosDashboard();
}

let selectedDay = (window.APP_DATA.dias && window.APP_DATA.dias[0]) || 'Lunes';
let selectedFloor = 'Piso 1';
let isPlanillaGeneral = false;
let allDataCache = null;

function togglePlanillaGeneral(checkbox) {
    isPlanillaGeneral = checkbox.checked;
    const controls = document.getElementById('planilla-controls');
    const searchField = document.querySelector('#tab-aula .tech-field');
    
    if (isPlanillaGeneral) {
        controls.style.display = 'block';
        searchField.style.opacity = '0.5';
        searchField.style.pointerEvents = 'none';
        
        if (allDataCache) {
            generarPlanillaGeneral();
        } else {
            fetch('/api/dashboard')
                .then(res => res.json())
                .then(data => {
                    allDataCache = data;
                    generarPlanillaGeneral();
                });
        }
    } else {
        controls.style.display = 'none';
        searchField.style.opacity = '1';
        searchField.style.pointerEvents = 'auto';
        
        const input = document.querySelector('#tab-aula .tech-input');
        if (input.value) {
            buscarEnServidor('aula', input.value);
        } else {
            document.getElementById('contenedor-calendario').innerHTML = "";
            const workspaceHeader = document.getElementById('workspace-calendar-header');
            if (workspaceHeader) workspaceHeader.style.display = 'none';
        }
    }
}

function setDiaPlanilla(btn, dia) {
    selectedDay = dia;
    document.querySelectorAll('.planilla-tabs.dias .planilla-tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    generarPlanillaGeneral();
}

function setPisoPlanilla(btn, piso) {
    selectedFloor = piso;
    document.querySelectorAll('.planilla-tabs.pisos .planilla-tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    generarPlanillaGeneral();
}

function generarPlanillaGeneral() {
    if (!allDataCache) return;
    
    const contenedor = document.getElementById('contenedor-calendario');
    const classrooms = window.APP_DATA.floorMapping[selectedFloor];

    const timeToMin = (t) => {
        if (!t || typeof t !== 'string' || !t.includes(':')) return 0;
        const [h, m] = t.split(':').map(Number);
        return h * 60 + m;
    };

    const filasDia = allDataCache.filter(f => f.dia === selectedDay && classrooms.includes(String(f.aula)));
    
    if (filasDia.length === 0) {
        contenedor.innerHTML = `<div style='padding:20px; text-align:center; color:#70757a;'>No hay clases para ${selectedFloor} el ${selectedDay}.</div>`;
        return;
    }

    let tiempos = new Set();
    filasDia.forEach(f => {
        if (f.hora_inicio) tiempos.add(f.hora_inicio);
        if (f.hora_fin) tiempos.add(f.hora_fin);
    });
    
    const horariosDinamicos = Array.from(tiempos).sort((a, b) => timeToMin(a) - timeToMin(b));
    const minMins = timeToMin(horariosDinamicos[0]) - 30; 
    const maxMins = timeToMin(horariosDinamicos[horariosDinamicos.length - 1]) + 30;
    const HORA_MIN = Math.max(0, minMins);
    const HORA_MAX = Math.min(1440, maxMins);
    const ALTURA_TOTAL = Math.max((HORA_MAX - HORA_MIN) * 1.05, 450);

    const getPosicionY = (horaStr) => {
        const minutos = timeToMin(horaStr);
        return ((minutos - HORA_MIN) / (HORA_MAX - HORA_MIN)) * ALTURA_TOTAL;
    };

    let html = '<div class="calendario-grid" style="grid-template-columns: 60px repeat(' + classrooms.length + ', 1fr);">';
    html += '<div class="cabecera-vacia"></div>';
    classrooms.forEach(aula => {
        html += `<div class="cabecera-dia"><div class="dia-nombre">Aula ${aula}</div></div>`;
    });

    html += `<div class="columna-horas" style="height:${ALTURA_TOTAL}px; position:relative;">`;
    horariosDinamicos.forEach(hora => {
        html += `<div class="hora-label" style="top:${getPosicionY(hora)}px;">${hora}</div>`;
    });
    html += '</div>';

    classrooms.forEach(aula => {
        html += `<div class="columna-dia" style="height:${ALTURA_TOTAL}px;">`;
        horariosDinamicos.forEach(hora => {
            html += `<div class="grid-line-horizontal" style="top:${getPosicionY(hora)}px;"></div>`;
        });

        const clasesAula = filasDia.filter(f => String(f.aula) === aula).sort((a,b) => timeToMin(a.hora_inicio) - timeToMin(b.hora_inicio));
        let procesados = new Set();
        for (let i = 0; i < clasesAula.length; i++) {
            if (procesados.has(i)) continue;
            let cluster = [clasesAula[i]];
            let clusterIdx = [i];
            let maxFin = timeToMin(clasesAula[i].hora_fin);
            for (let j = i + 1; j < clasesAula.length; j++) {
                if (timeToMin(clasesAula[j].hora_inicio) < maxFin) {
                    cluster.push(clasesAula[j]);
                    clusterIdx.push(j);
                    maxFin = Math.max(maxFin, timeToMin(clasesAula[j].hora_fin));
                } else { break; }
            }

            const sinLicenciadas = cluster.filter(c => c.suplente_activo != 1);
            const clusterFinal = cluster.length > 1 && sinLicenciadas.length > 0 ? sinLicenciadas : cluster;

            const todosTienenGrupo = clusterFinal.every(c => c.grupo && c.grupo.trim() !== "");
            const haySuperposicion = clusterFinal.length > 1 && !todosTienenGrupo;

            if (haySuperposicion) {
                const todosPermitenSuperposicion = clusterFinal.every(c => c.superposicion == 1);
                if (todosPermitenSuperposicion) {
                    const numClases = clusterFinal.length;
                    clusterFinal.forEach((clase, idxInCluster) => {
                        const top = getPosicionY(clase.hora_inicio) + 2;
                        const bottom = getPosicionY(clase.hora_fin) - 2;
                        const alto = Math.max(bottom - top, 20);
                        const anchoPct = 100 / numClases;
                        const leftPct = anchoPct * idxInCluster;
                        const styleExtra = `width: calc(${anchoPct}% - 6px); left: calc(${leftPct}% + 4px);`;
                        const jsonClase = encodeURIComponent(JSON.stringify(clase));
                        html += `<div class="materia-bloque" style="top: ${top}px; height: ${alto}px; ${styleExtra}" onclick="mostrarInfoClase('${jsonClase}', this)">
                            <div class="materia-contenido" style="text-align:center;">
                                <div class="materia-nombre" style="font-size:14px;">${clase.curso}° ${clase.division}</div>
                            </div>
                            <div class="aula-indicador">${clase.curso}° ${clase.division}</div>
                        </div>`;
                    });
                } else {
                    const top = getPosicionY(clusterFinal[0].hora_inicio);
                    const latestEndClase = clusterFinal.reduce((max, c) => timeToMin(c.hora_fin) > timeToMin(max.hora_fin) ? c : max);
                    const alto = Math.max(getPosicionY(latestEndClase.hora_fin) - top, 30);
                    const jsonDetalles = encodeURIComponent(JSON.stringify(clusterFinal));
                    html += `<div class="bloque-superposicion" style="top: ${top}px; height: ${alto}px;" onclick="verDetalleSuperposicion('${jsonDetalles}')">⚠️ Superposición (${clusterFinal.length})</div>`;
                }
            } else {
                clusterFinal.forEach((clase) => {
                    const top = getPosicionY(clase.hora_inicio) + 2;
                    const bottom = getPosicionY(clase.hora_fin) - 2;
                    const alto = Math.max(bottom - top, 20);
                    const jsonClase = encodeURIComponent(JSON.stringify(clase));
                    html += `<div class="materia-bloque" style="top: ${top}px; height: ${alto}px; left:4px; right:4px;" onclick="mostrarInfoClase('${jsonClase}', this)">
                        <div class="materia-contenido" style="text-align:center;">
                            <div class="materia-nombre" style="font-size:14px;">${clase.curso}° ${clase.division}</div>
                        </div>
                        <div class="aula-indicador">${clase.curso}° ${clase.division}</div>
                    </div>`;
                });
            }
            clusterIdx.forEach(idx => procesados.add(idx));
        }
        html += '</div>';
    });
    
    html += '</div>';
    contenedor.innerHTML = html;
    contenedor.style.display = 'block';
    
    const workspaceHeader = document.getElementById('workspace-calendar-header');
    const calendarTitle = document.getElementById('calendar-title');
    if (workspaceHeader && calendarTitle) {
        workspaceHeader.style.display = 'flex';
        calendarTitle.textContent = `Planilla General: ${selectedFloor} - ${selectedDay}`;
    }
}

// Close menus and slide panels when clicking outside
document.addEventListener('click', (e) => {
    const menus = document.querySelectorAll(".menu-dropdown");
    menus.forEach(menu => {
        if (menu.style.display === "block" && !menu.contains(e.target) && !e.target.classList.contains('btn-menu')) {
            menu.style.display = "none";
        }
    });
    if (!e.target.closest('.slide-panel') && !e.target.closest('.btn-slide-trigger')) {
        document.querySelectorAll('.slide-panel').forEach(p => p.classList.remove('open'));
        document.querySelectorAll('.btn-slide-trigger').forEach(b => b.classList.remove('panel-open'));
    }
});

// ─── BOOTSTRAP: descargar datos a memoria y resolver la URL inicial (hash routing) ───
(function init() {
    const MODOS_VALIDOS = ['profesor', 'curso', 'aula', 'horario_preceptor'];
    const TAB_SOLO = {
        'profesor': 'tab-profesor', 'aula': 'tab-aula', 'curso': 'tab-curso',
        'horario_preceptor': 'tab-horario_preceptor', 'envivo': 'tab-envivo'
    };

    cargarDatosIniciales().then(() => {
        const hash = location.hash; // ej: "#/profesor/MACIEL%20MARTIN" o "#/aula"
        if (!hash.startsWith('#/')) return;
        const parts = hash.slice(2).split('/');
        const modo = parts[0];
        const valor = parts.length >= 2 ? decodeURIComponent(parts.slice(1).join('/')) : null;

        const tabId = TAB_SOLO[modo];
        if (!tabId) return;

        // Activar la tab correspondiente sin disparar el reset/focus de navegación manual
        const tabBtn = document.querySelector(`[onclick*="cambiarTab"][onclick*="${tabId}"]`);
        window.isProgrammaticNavigation = true;
        if (tabBtn) tabBtn.click();

        // Solo buscar si hay valor (si no, solo activar el tab)
        if (valor && MODOS_VALIDOS.includes(modo)) {
            buscarEnServidor(modo, valor);
        }
        window.isProgrammaticNavigation = false;
    });
})();
