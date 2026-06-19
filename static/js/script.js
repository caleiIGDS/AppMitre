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

function toggleComparacion() {
    if (isComparacionMode) {
        desactivarModoComparacion();
    } else {
        activarModoComparacion();
    }
}

function activarModoComparacion() {
    if (!currentSearch.modo || !currentSearch.valor || !lastFilas) {
        alert("Primero buscá un horario para poder comparar.");
        return;
    }
    isComparacionMode = true;
    comparacionItems = [{
        modo: currentSearch.modo,
        valor: currentSearch.valor,
        filas: lastFilas,
        color: COMPARACION_COLORS[0],
        label: currentSearch.valor
    }];
    actualizarEstadoComparacion();
    generarCalendarioComparacion(comparacionItems);
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
    const btns = document.querySelectorAll('.btn-comparar');

    if (isComparacionMode) {
        if (banner) {
            const chips = comparacionItems.map(item =>
                `<span class="comp-chip" style="background:${item.color};">${item.label}</span>`
            ).join('');
            document.getElementById('comp-banner-items').innerHTML = chips;
            banner.style.display = 'flex';
        }
        btns.forEach(btn => {
            btn.textContent = 'COMPARANDO';
            btn.classList.add('activo');
        });
        const workspaceHeader = document.getElementById('workspace-calendar-header');
        if (workspaceHeader) workspaceHeader.style.display = 'none';
    } else {
        if (banner) banner.style.display = 'none';
        btns.forEach(btn => {
            btn.textContent = 'COMPARAR';
            btn.classList.remove('activo');
        });
    }
}

function generarCalendarioComparacion(items) {
    const contenedor = document.getElementById('contenedor-calendario');
    const COL_WIDTH = 200;
    const N = items.length;
    const dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"];

    const timeToMin = (t) => {
        if (!t || typeof t !== 'string' || !t.includes(':')) return 0;
        const [h, m] = t.split(':').map(Number);
        return h * 60 + m;
    };

    let tiempos = new Set();
    items.forEach(item => {
        item.filas.forEach(f => {
            if (f[12]) tiempos.add(f[12]);
            if (f[13]) tiempos.add(f[13]);
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
        const inicio = clase[12];
        const fin = clase[13];
        const top = getPosicionY(inicio) + 2;
        const alto = Math.max(getPosicionY(fin) - 2 - top, 20);
        const jsonClase = encodeURIComponent(JSON.stringify(clase));
        const modo = item.modo;
        const profName = (clase[16] === 1 && clase[17]) ? 'SUPLENTE: ' + clase[17] : (clase[5] || '-');
        const detalleLinea = modo === 'profesor' ? `${clase[0]}° ${clase[1]}` : profName;
        const aulaInd = modo === 'aula' ? `${clase[0]}° ${clase[1]}` : (clase[9] || '?');
        const sinNumero = !(/\d/.test(clase[9])) && modo !== 'aula' ? ' sin-numero' : '';
        return `<div class="materia-bloque"
            style="top:${top}px; height:${alto}px; ${styleExtra} background-color:${item.color};"
            onclick="mostrarInfoClase('${jsonClase}', this)"
            onmouseover="showTooltip(event,'${clase[3].replace(/'/g,"\\'")}','${profName.replace(/'/g,"\\'")}','${(clase[9]||'-').replace(/'/g,"\\'")}','${inicio} - ${fin}','${clase[0]}° ${clase[1]}')"
            onmouseout="hideTooltip()">
            <div class="materia-contenido">
                ${modo === 'profesor' && clase[16] === 1
                    ? `<div class="materia-nombre" style="color:var(--alert);font-weight:bold;display:flex;align-items:center;justify-content:center;height:100%;">LICENCIADA</div>`
                    : `<div class="materia-nombre">${clase[3]}</div><div class="materia-detalles">${detalleLinea}</div>`
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
                .filter(f => f[11] === dia)
                .sort((a, b) => timeToMin(a[12]) - timeToMin(b[12]));
            const modo = item.modo;

            let procesados = new Set();
            for (let i = 0; i < clasesDelDia.length; i++) {
                if (procesados.has(i)) continue;
                let cluster = [clasesDelDia[i]];
                let clusterIdx = [i];
                let maxFin = timeToMin(clasesDelDia[i][13]);
                for (let j = i + 1; j < clasesDelDia.length; j++) {
                    if (timeToMin(clasesDelDia[j][12]) < maxFin) {
                        cluster.push(clasesDelDia[j]);
                        clusterIdx.push(j);
                        maxFin = Math.max(maxFin, timeToMin(clasesDelDia[j][13]));
                    } else { break; }
                }

                const todosTienenGrupo = cluster.every(c => c[14] && c[14].trim() !== "");
                const haySuperposicion = cluster.length > 1 && (modo === 'aula' || modo === 'profesor' || !todosTienenGrupo);

                if (haySuperposicion) {
                    const todosPermiten = cluster.every(c => c[15] == 1);
                    if (todosPermiten) {
                        const estilos = calcularEstilosBloques(cluster);
                        cluster.forEach((clase, idx) => { html += renderBloqueComp(clase, estilos[idx], item); });
                    } else {
                        const top = getPosicionY(cluster[0][12]);
                        const latestEnd = cluster.reduce((max, c) => timeToMin(c[13]) > timeToMin(max[13]) ? c : max);
                        const alto = Math.max(getPosicionY(latestEnd[13]) - top, 30);
                        const jsonD = encodeURIComponent(JSON.stringify(cluster));
                        html += `<div class="bloque-superposicion" style="top:${top}px; height:${alto}px;" onclick="verDetalleSuperposicion('${jsonD}')">⚠️ Superposición (${cluster.length})</div>`;
                    }
                } else {
                    const estilos = calcularEstilosBloques(cluster);
                    cluster.forEach((clase, idx) => { html += renderBloqueComp(clase, estilos[idx], item); });
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

    fetch('/api/actualizar')
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

    // Enter key support to select first match
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
    let cursoDisplay = `${c[0]}° ${c[1]}`;
    if (c[14] && c[14].trim() !== '') { // Check if group exists and is not empty
        cursoDisplay += ` (Grupo: ${c[14]})`;
    }

    let profesorLabel = "Profesor";
    let profesorValor = c[5];
    if (c[16] === 1) {
        profesorLabel = "Suplente";
        profesorValor = `${c[17]} (desde ${c[18]} hasta ${c[19]})`;
    }

    const html = `
        <div class="info-card">
            <div class="info-label">Materia</div>
            <div class="info-valor">${c[3]}</div>
            <div class="info-label">${profesorLabel}</div>
            <div class="clickable-valor" onclick="navegarDesdeModal('profesor', '${c[5].replace(/'/g, "\\'")}')">${profesorValor}</div>
            <div class="info-label">Curso</div>
            <div class="clickable-valor" onclick="navegarDesdeModal('curso', '${c[0]} ${c[1]}')">${cursoDisplay}</div>
            <div class="info-label">Aula</div>
            <div class="clickable-valor" onclick="navegarDesdeModal('aula', '${(c[9] || '-').replace(/'/g, "\\'")}')">${c[9] || '-'}</div>
            <div class="info-label">Horario</div>
            <div class="info-valor">${c[12]} - ${c[13]} (${c[11]})</div>
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
                <div class="info-valor">${c[3]}</div>
                <div class="info-label">Profesor</div>
                <div class="clickable-valor" onclick="navegarDesdeModal('profesor', '${c[5].replace(/'/g, "\\'")}')">${c[5]}</div>
                <div class="info-label">Curso</div>
                <div class="clickable-valor" onclick="navegarDesdeModal('curso', '${c[0]} ${c[1]}')">${c[0]}° ${c[1]}</div>
                <div class="info-label">Aula</div>
                <div class="clickable-valor" onclick="navegarDesdeModal('aula', '${(c[9] || '-').replace(/'/g, "\\'")}')">${c[9] || '-'}</div>
                <div class="info-label">Horario</div>
                <div class="info-valor">${c[12]} - ${c[13]}</div>
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
        if (f[11] !== currentDay) return;
        
        // Aplicar filtro si existe texto
        if (filterText) {
            const curso = normalize(`${f[0]} ${f[1]}`);
            const prof = normalize(f[16] === 1 ? f[17] : f[5]);
            if (!curso.includes(filterText) && !prof.includes(filterText)) {
                return;
            }
        }

        const start = timeToMin(f[12]);
        const end = timeToMin(f[13]);

        if (currentTime >= start && currentTime <= end) {
            inProgress.push(f);
        } else if (currentTime < start && start < currentTime + (HORAS_PROXIMAS * 60)) {
            upcoming.push(f);
        }
    });

    inProgress.sort((a, b) => timeToMin(a[12]) - timeToMin(b[12]));
    upcoming.sort((a, b) => timeToMin(a[12]) - timeToMin(b[12]));

    const renderList = (list) => {
        if (list.length === 0) return `<div style="text-align:center; padding:20px; color:#5f6368;">${filterText ? 'SIN COINCIDENCIAS' : 'SIN ACTIVIDAD'}</div>`;
        return list.map(f => {
            let profName = f[5];
            if (f[16] === 1) profName = 'SUPLENTE: ' + f[17];
            const jsonClase = encodeURIComponent(JSON.stringify(f));
            return `
                <div class="class-item-light" style="cursor:pointer;" onclick="mostrarInfoClase('${jsonClase}', this)">
                    <div class="class-time-light">${f[12]} - ${f[13]}</div>
                    <div class="class-info-light">
                        <span class="class-materia-light">${f[0]}° ${f[1]} | ${profName}</span>
                        <span class="class-meta-light">${f[3]}</span>
                    </div>
                    <div class="class-room-light">${f[9] || '-'}</div>
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
    const exportBtn = document.getElementById('export-pdf-btn');

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

    if (!isComparacionMode && workspaceHeader && calendarTitle) {
        workspaceHeader.style.display = 'flex';
        calendarTitle.textContent = `Horario de ${modo.replace('_', ' ')}: ${valor}`;
        if (preceptorContainer) preceptorContainer.innerHTML = "";
        if (exportBtn) {
            exportBtn.style.display = (modo === 'horario_preceptor') ? 'none' : 'block';
        }
    }

    const endpoint = modo === 'horario_preceptor' ? `/api/horario_preceptor/${valor}` : `/api/${modo}/${valor}`;

    fetch(endpoint)
        .then(res => res.json())
        .then(filas => {
            if (isComparacionMode) {
                // Verificar si ya está en la comparación
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
                        fetch(`/api/preceptor/${valor}`)
                            .then(r => r.json())
                            .then(preceptorData => {
                                if (preceptorData) renderizarPreceptor(preceptorData);
                            });
                    }
                }
            }
        })
        .catch(err => console.error("Error API:", err));
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
        const diasSemana = ["LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES"];
        
        // Agrupar por preceptor, curso y estado (tipo) para tener una fila por curso
        const cursosMap = {};
        filasTurno.forEach(f => {
            const key = `${f.preceptor}|${f.curso}|${f.tipo}`;
            if (!cursosMap[key]) {
                cursosMap[key] = { preceptor: f.preceptor, curso: f.curso, estado: f.tipo || '-', dias: [] };
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
                                        ? `<div class="preceptor-curso-item" style="margin: 0 auto;">${c.curso}</div>` 
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
        "preceptores_noche": "T.N:"
    };
    
    // Mapeo del turno del curso a la columna de la DB
    const turnoCurso = (data.turno || "").trim().toUpperCase();
    const mapping = {
        "T.M": "preceptores_manana",
        "T.T": "preceptores_tarde",
        "T.N": "preceptores_noche",
        "T.V": "preceptores_noche"
    };

    let keyPrincipal = null;
    for (let k in mapping) {
        if (turnoCurso.startsWith(k)) {
            keyPrincipal = mapping[k];
            break;
        }
    }

    let html = "";
    ["preceptores_manana", "preceptores_tarde", "preceptores_noche"].forEach(key => {
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
            let g = (cluster[i][14] || "").trim().toUpperCase();
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

        const dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"];
        let tiempos = new Set();
        filas.forEach(f => {
            if (f[12]) tiempos.add(f[12]);
            if (f[13]) tiempos.add(f[13]);
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

            const clasesDelDia = filas.filter(f => f[11] === dia).sort((a,b) => timeToMin(a[12]) - timeToMin(b[12]));
            let procesados = new Set();
            for (let i = 0; i < clasesDelDia.length; i++) {
                if (procesados.has(i)) continue;
                let cluster = [clasesDelDia[i]];
                let clusterIdx = [i];
                let maxFin = timeToMin(clasesDelDia[i][13]);
                for (let j = i + 1; j < clasesDelDia.length; j++) {
                    let inicioJ = timeToMin(clasesDelDia[j][12]);
                    if (inicioJ < maxFin) {
                        cluster.push(clasesDelDia[j]);
                        clusterIdx.push(j);
                        maxFin = Math.max(maxFin, timeToMin(clasesDelDia[j][13]));
                    } else { break; }
                }
                const todosTienenGrupo = cluster.every(c => c[14] && c[14].trim() !== "");
                const haySuperposicion = cluster.length > 1 && (modo === 'aula' || modo === 'profesor' || !todosTienenGrupo);

                if (haySuperposicion) {
                    // Logic for superposition: only divide side-by-side if ALL classes allow it (F[15] == 1)
                    const todosPermitenSuperposicion = cluster.every(c => c[15] == 1);
                    if (todosPermitenSuperposicion) { 
                        const estilos = calcularEstilosBloques(cluster);
                        const numClases = cluster.length;
                        cluster.forEach((clase, idxInCluster) => {
                            const inicio = clase[12];
                            const fin = clase[13];
                            const top = getPosicionY(inicio) + 2;
                            const bottom = getPosicionY(fin) - 2;
                            const alto = Math.max(bottom - top, 20);
                            const styleExtra = estilos[idxInCluster];

                            const jsonClase = encodeURIComponent(JSON.stringify(clase));
                            html += `
                                <div class="materia-bloque" 
                                     style="top: ${top}px; height: ${alto}px; ${styleExtra}" 
                                     onclick="mostrarInfoClase('${jsonClase}', this)"
                                     onmouseover="showTooltip(event, '${clase[3].replace(/'/g, "\\'")}', '${(clase[16] === 1 ? 'SUPLENTE: ' + clase[17] : (clase[5] || '-')).replace(/'/g, "\\'")}', '${clase[9].replace(/'/g, "\\'")}', '${inicio} - ${fin}', '${clase[0]}° ${clase[1]}')" 
                                     onmouseout="hideTooltip()">
                                    <div class="materia-contenido">
                                        ${modo === 'profesor' && clase[16] === 1 ? 
                                            `<div class="materia-nombre" style="color:var(--alert); font-weight:bold; display:flex; align-items:center; justify-content:center; height:100%;">LICENCIADA</div>` :
                                            `<div class="materia-nombre">${clase[3]}</div>
                                             <div class="materia-detalles">
                                                ${(() => {
                                                    const profName = (clase[16] === 1 && clase[17]) ? 'SUPLENTE: ' + clase[17] : (clase[5] || '-');
                                                    return modo === 'aula' ? profName : (modo === 'profesor' ? `${clase[0]}° ${clase[1]}` : profName);
                                                })()}
                                             </div>`
                                        }
                                    </div>
                                    <div class="aula-indicador${!(/\d/g.test(clase[9])) && !(modo == "aula") ? ' sin-numero' : ''}">${modo === 'aula' ? `${clase[0]}° ${clase[1]}` : (clase[9] || '?')}</div>
                                </div>`;
                        });
                    } else { 
                        const top = getPosicionY(cluster[0][12]);
                        const latestEndClase = cluster.reduce((max, c) => timeToMin(c[13]) > timeToMin(max[13]) ? c : max);
                        const bottom = getPosicionY(latestEndClase[13]);
                        const alto = Math.max(bottom - top, 30);
                        const jsonDetalles = encodeURIComponent(JSON.stringify(cluster));
                        html += `<div class="bloque-superposicion" style="top: ${top}px; height: ${alto}px;" onclick="verDetalleSuperposicion('${jsonDetalles}')">⚠️ Superposición (${cluster.length})</div>`;
                    }
                    clusterIdx.forEach(idx => procesados.add(idx));
                } else {
                    const estilos = calcularEstilosBloques(cluster);
                    const numClases = cluster.length;
                    cluster.forEach((clase, idxInCluster) => {
                        const inicio = clase[12];
                        const fin = clase[13];
                        const top = getPosicionY(inicio) + 2;
                        const bottom = getPosicionY(fin) - 2;
                        const alto = Math.max(bottom - top, 20);
                        const styleExtra = estilos[idxInCluster];
                        const jsonClase = encodeURIComponent(JSON.stringify(clase));
                        html += `
                            <div class="materia-bloque" 
                                 style="top: ${top}px; height: ${alto}px; ${styleExtra}" 
                                 onclick="mostrarInfoClase('${jsonClase}', this)"
                                 onmouseover="showTooltip(event, '${clase[3].replace(/'/g, "\\'")}', '${(clase[16] === 1 ? 'SUPLENTE: ' + clase[17] : (clase[5] || '-')).replace(/'/g, "\\'")}', '${clase[9].replace(/'/g, "\\'")}', '${inicio} - ${fin}', '${clase[0]}° ${clase[1]}')" 
                                 onmouseout="hideTooltip()">
                                <div class="materia-contenido">
                                    ${modo === 'profesor' && clase[16] === 1 ? 
                                        `<div class="materia-nombre" style="color:var(--alert); font-weight:bold; display:flex; align-items:center; justify-content:center; height:100%;">LICENCIADA</div>` :
                                        `<div class="materia-nombre">${clase[3]}</div>
                                         <div class="materia-detalles">
                                            ${(() => {
                                                const profName = (clase[16] === 1 && clase[17]) ? 'SUPLENTE: ' + clase[17] : (clase[5] || '-');
                                                return modo === 'aula' ? profName : (modo === 'profesor' ? `${clase[0]}° ${clase[1]}` : profName);
                                            })()}
                                         </div>`
                                    }
                                </div>
                                <div class="aula-indicador${!(/\d/g.test(clase[9])) && !(modo == "aula") ? ' sin-numero' : ''}">${modo === 'aula' ? `${clase[0]}° ${clase[1]}` : (clase[9] || '?')}</div>

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

function generarTablaDetallada(filas) {
    const contenedor = document.getElementById('contenedor-lista');
    if (filas.length === 0) return;
    let html = `<h3>Detalle de Clases</h3><table>
        <thead>
            <tr><th>Día</th><th>Inicio</th><th>Fin</th><th>Materia</th><th>Profesor</th><th>Aula</th><th>Grupo</th></tr>
        </thead><tbody>`;
    filas.forEach(f => {
        let profName = f[16] === 1 ? 'SUPLENTE: ' + f[17] : f[5];
        html += `<tr>
            <td>${f[11]}</td><td>${f[12]}</td><td>${f[13]}</td>
            <td><b>${f[3]}</b></td><td>${profName}</td><td>${f[9]}</td><td>${f[14] || '-'}</td>
        </tr>`;
    });
    html += '</tbody></table>';
    contenedor.innerHTML = html;
}

function exportarAPDF() {
    if (isPlanillaGeneral) {
        window.open(`/export/pdf/planilla/${selectedDay}|${selectedFloor}`, '_blank');
    } else if (currentSearch.modo && currentSearch.valor) {
        window.open(`/export/pdf/${currentSearch.modo}/${currentSearch.valor}`, '_blank');
    }
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

document.addEventListener('DOMContentLoaded', () => {
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

let selectedDay = 'Lunes';
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

    const filasDia = allDataCache.filter(f => f[11] === selectedDay && classrooms.includes(String(f[9])));
    
    if (filasDia.length === 0) {
        contenedor.innerHTML = `<div style='padding:20px; text-align:center; color:#70757a;'>No hay clases para ${selectedFloor} el ${selectedDay}.</div>`;
        return;
    }

    let tiempos = new Set();
    filasDia.forEach(f => {
        if (f[12]) tiempos.add(f[12]);
        if (f[13]) tiempos.add(f[13]);
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

        const clasesAula = filasDia.filter(f => String(f[9]) === aula).sort((a,b) => timeToMin(a[12]) - timeToMin(b[12]));
        let procesados = new Set();
        for (let i = 0; i < clasesAula.length; i++) {
            if (procesados.has(i)) continue;
            let cluster = [clasesAula[i]];
            let clusterIdx = [i];
            let maxFin = timeToMin(clasesAula[i][13]);
            for (let j = i + 1; j < clasesAula.length; j++) {
                if (timeToMin(clasesAula[j][12]) < maxFin) {
                    cluster.push(clasesAula[j]);
                    clusterIdx.push(j);
                    maxFin = Math.max(maxFin, timeToMin(clasesAula[j][13]));
                } else { break; }
            }
            
            const todosTienenGrupo = cluster.every(c => c[14] && c[14].trim() !== "");
            const haySuperposicion = cluster.length > 1 && !todosTienenGrupo;

            if (haySuperposicion) {
                const todosPermitenSuperposicion = cluster.every(c => c[15] == 1);
                if (todosPermitenSuperposicion) {
                    const numClases = cluster.length;
                    cluster.forEach((clase, idxInCluster) => {
                        const top = getPosicionY(clase[12]) + 2;
                        const bottom = getPosicionY(clase[13]) - 2;
                        const alto = Math.max(bottom - top, 20);
                        const anchoPct = 100 / numClases;
                        const leftPct = anchoPct * idxInCluster;
                        const styleExtra = `width: calc(${anchoPct}% - 6px); left: calc(${leftPct}% + 4px);`;
                        const jsonClase = encodeURIComponent(JSON.stringify(clase));
                        html += `<div class="materia-bloque" style="top: ${top}px; height: ${alto}px; ${styleExtra}" onclick="mostrarInfoClase('${jsonClase}', this)">
                            <div class="materia-contenido" style="text-align:center;">
                                <div class="materia-nombre" style="font-size:14px;">${clase[0]}° ${clase[1]}</div>
                            </div>
                            <div class="aula-indicador">${clase[0]}° ${clase[1]}</div>
                        </div>`;
                    });
                } else {
                    const top = getPosicionY(cluster[0][12]);
                    const latestEndClase = cluster.reduce((max, c) => timeToMin(c[13]) > timeToMin(max[13]) ? c : max);
                    const alto = Math.max(getPosicionY(latestEndClase[13]) - top, 30);
                    const jsonDetalles = encodeURIComponent(JSON.stringify(cluster));
                    html += `<div class="bloque-superposicion" style="top: ${top}px; height: ${alto}px;" onclick="verDetalleSuperposicion('${jsonDetalles}')">⚠️ Superposición (${cluster.length})</div>`;
                }
            } else {
                cluster.forEach((clase) => {
                    const top = getPosicionY(clase[12]) + 2;
                    const bottom = getPosicionY(clase[13]) - 2;
                    const alto = Math.max(bottom - top, 20);
                    const jsonClase = encodeURIComponent(JSON.stringify(clase));
                    html += `<div class="materia-bloque" style="top: ${top}px; height: ${alto}px; left:4px; right:4px;" onclick="mostrarInfoClase('${jsonClase}', this)">
                        <div class="materia-contenido" style="text-align:center;">
                            <div class="materia-nombre" style="font-size:14px;">${clase[0]}° ${clase[1]}</div>
                        </div>
                        <div class="aula-indicador">${clase[0]}° ${clase[1]}</div>
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

// Close menus when clicking outside
document.addEventListener('click', (e) => {
    const menus = document.querySelectorAll(".menu-dropdown");
    menus.forEach(menu => {
        if (menu.style.display === "block" && !menu.contains(e.target) && !e.target.classList.contains('btn-menu')) {
            menu.style.display = "none";
        }
    });
});
