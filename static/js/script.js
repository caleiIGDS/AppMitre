// Datos y estado global
const rawData = window.APP_DATA ? window.APP_DATA.rawData : {};
let currentSearch = {
    modo: null,
    valor: null
};

function normalize(text) {
    return text.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/\s+/g, "");
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
}

function seleccionarOpcion(valor, modo) {
    const input = document.querySelector(`#tab-${modo} .search-input`);
    input.value = valor;
    document.getElementById(`dropdown-${modo}`).style.display = 'none';
    buscarEnServidor(modo, valor);
}

document.addEventListener('click', (e) => {
    if (!e.target.classList.contains('search-input')) {
        document.querySelectorAll('.custom-dropdown').forEach(d => d.style.display = 'none');
    }
});

function abrirModal(titulo, html) {
    document.getElementById('modal-titulo').innerText = titulo;
    document.getElementById('modal-body').innerHTML = html;
    document.getElementById('modal-detalles').style.display = 'flex';
}

function cerrarModal() {
    document.getElementById('modal-detalles').style.display = 'none';
}

window.onclick = function(event) {
    const modal = document.getElementById('modal-detalles');
    if (event.target == modal) cerrarModal();
}

function mostrarInfoClase(json) {
    const c = JSON.parse(decodeURIComponent(json));
    let cursoDisplay = `${c[0]}° ${c[1]}`;
    if (c[14] && c[14].trim() !== '') { // Check if group exists and is not empty
        cursoDisplay += ` (Grupo: ${c[14]})`;
    }
    const html = `
        <div class="info-card">
            <div class="info-label">Materia</div>
            <div class="info-valor">${c[3]}</div>
            <div class="info-label">Profesor</div>
            <div class="info-valor">${c[5]}</div>
            <div class="info-label">Curso</div>
            <div class="info-valor">${cursoDisplay}</div>
            <div class="info-label">Aula</div>
            <div class="info-valor">${c[9] || '-'}</div>
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
                <div class="info-valor">${c[5]}</div>
                <div class="info-label">Curso</div>
                <div class="info-valor">${c[0]}° ${c[1]}</div>
                <div class="info-label">Aula</div>
                <div class="info-valor">${c[9] || '-'}</div>
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
    tablinks = document.getElementsByClassName("tab-btn");
    for (i = 0; i < tablinks.length; i++) tablinks[i].className = tablinks[i].className.replace(" active", "");
    
    document.getElementById(idTab).style.display = "block";
    evt.currentTarget.className += " active";
    
    // Reset views
    document.querySelectorAll('.search-input').forEach(input => input.value = "");
    document.querySelectorAll('.custom-dropdown').forEach(d => d.style.display = 'none');
    document.getElementById('contenedor-calendario').innerHTML = "";
    document.getElementById('contenedor-lista').innerHTML = "";
    document.getElementById('contenedor-dashboard').style.display = 'none';
    document.getElementById('contenedor-calendario').style.display = 'block';
    
    if (idTab === 'tab-envivo') {
        document.getElementById('contenedor-calendario').style.display = 'none';
        document.getElementById('contenedor-dashboard').style.display = 'block';
        iniciarDashboard();
    }
    
    // Clear the dynamic title when tab changes
    const titleDisplay = document.getElementById('search-title-display');
    if (titleDisplay) titleDisplay.textContent = "";
    document.getElementById('export-pdf-btn').style.display = 'none';
}

let dashboardInterval = null;
let isManualClock = false;
let manualTime = null;
let manualDate = null;

function toggleManualClock() {
    isManualClock = document.getElementById('manual-clock-toggle').checked;
    if (!isManualClock) {
        manualTime = null;
        manualDate = null;
        actualizarReloj();
    } else {
        // Initialize manual inputs with current time/date
        const now = new Date();
        document.getElementById('manual-clock-input').value = now.toTimeString().slice(0, 5);
        document.getElementById('manual-date-input').value = now.toISOString().split('T')[0];
        manualTime = document.getElementById('manual-clock-input').value;
        manualDate = document.getElementById('manual-date-input').value;
    }
    cargarDatosDashboard();
}

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
        .then(filas => renderizarDashboard(filas))
        .catch(err => console.error("Error Dashboard:", err));
}

function renderizarDashboard(filas) {
    const contenedor = document.getElementById('contenedor-dashboard');
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

    const inProgress = [];
    const upcoming = [];
    const finished = [];

    filas.forEach(f => {
        if (f[11] !== currentDay) return;
        
        const start = timeToMin(f[12]);
        const end = timeToMin(f[13]);

        if (currentTime >= start && currentTime <= end) {
            inProgress.push(f);
        } else if (currentTime < start) {
            upcoming.push(f);
        } else if (currentTime > end) {
            finished.push(f);
        }
    });

    inProgress.sort((a, b) => timeToMin(a[12]) - timeToMin(b[12]));
    upcoming.sort((a, b) => timeToMin(a[12]) - timeToMin(b[12]));
    finished.sort((a, b) => timeToMin(b[13]) - timeToMin(a[13]));

    const renderList = (list) => {
        if (list.length === 0) return '<div style="text-align:center; padding:20px; color:#5f6368;">SIN ACTIVIDAD</div>';
        return list.map(f => `
            <div class="class-item-light">
                <div class="class-time-light">${f[12]}</div>
                <div class="class-info-light">
                    <span class="class-materia-light">${f[3]}</span>
                    <span class="class-meta-light">${f[0]}° ${f[1]} | ${f[5]}</span>
                </div>
                <div class="class-room-light">${f[9] || '-'}</div>
            </div>
        `).join('');
    };

    contenedor.innerHTML = `
        <div class="dashboard-grid-light">
            <div class="dashboard-column-light finished">
                <h2>Terminadas</h2>
                <div class="class-list-light">${renderList(finished.slice(0, 15))}</div>
            </div>
            <div class="dashboard-column-light in-progress">
                <h2>En Curso</h2>
                <div class="class-list-light">${renderList(inProgress)}</div>
            </div>
            <div class="dashboard-column-light upcoming">
                <h2>Próximas</h2>
                <div class="class-list-light">${renderList(upcoming.slice(0, 15))}</div>
            </div>
        </div>
    `;
}

function buscarEnServidor(modo, valor) {
    const titleDisplay = document.getElementById('search-title-display');
    const exportBtn = document.getElementById('export-pdf-btn');
    if (!valor) {
        if (titleDisplay) titleDisplay.textContent = ""; // Clear title if no value
        exportBtn.style.display = 'none';
        return;
    }
    currentSearch.modo = modo;
    currentSearch.valor = valor;
    // Update the title here
    if (titleDisplay) {
        let titleText = "";
        if (modo === 'profesor') {
            titleText = `Calendario semanal de Prof: ${valor}`;
        } else if (modo === 'aula') {
            titleText = `Calendario semanal de Aula: ${valor}`;
        } else if (modo === 'curso') {
            titleText = `Calendario semanal de Curso: ${valor}`;
        }
        titleDisplay.textContent = titleText;
        exportBtn.style.display = 'inline-block';
    }

    fetch(`/api/${modo}/${valor}`)
        .then(res => res.json())
        .then(filas => {
            generarCalendario(filas, modo);
            generarTablaDetallada(filas);
        })
        .catch(err => console.error("Error API:", err));
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
                if (cluster.length > 1 && !todosTienenGrupo) {
                    console.log("Cluster with superposition detected:", cluster);
                    console.log("Value of cluster[0][15]:", cluster[0][15]);
                    // Check for superposition split condition (clase[15] == 1)
                    if (cluster[0][15] == 1) { 
                        console.log("Executing split superposition logic (clase[15] == 1)");
                        const numClases = cluster.length;
                        cluster.forEach((clase, idxInCluster) => {
                            const inicio = clase[12];
                            const fin = clase[13];
                            const top = getPosicionY(inicio) + 2;
                            const bottom = getPosicionY(fin) - 2;
                            const alto = Math.max(bottom - top, 20);
                            const anchoPct = 100 / numClases;
                            const leftPct = anchoPct * idxInCluster;
                            const styleExtra = `width: calc(${anchoPct}% - 6px); left: calc(${leftPct}% + 4px);`;
                            const jsonClase = encodeURIComponent(JSON.stringify(clase));
                            html += `
                                <div class="materia-bloque" 
                                     style="top: ${top}px; height: ${alto}px; ${styleExtra}" 
                                     onclick="mostrarInfoClase('${jsonClase}')"
                                     onmouseover="showTooltip(event, '${clase[3].replace(/'/g, "\\'")}', '${clase[5].replace(/'/g, "\\'")}', '${clase[9].replace(/'/g, "\\'")}', '${inicio} - ${fin}', '${clase[0]}° ${clase[1]}')" 
                                     onmouseout="hideTooltip()">
                                    <div class="aula-indicador${!(/\d/g.test(clase[9])) && !(modo == "aula") ? ' sin-numero' : ''}">${modo === 'aula' ? `${clase[0]}° ${clase[1]}` : (clase[9] || '?')}</div>
                                    <div class="materia-contenido">
                                        <div class="materia-nombre">${clase[3]}</div>
                                        <div class="materia-detalles">
                                            ${modo === 'aula' ? (clase[5] || '-') : (modo === 'profesor' ? `${clase[0]}° ${clase[1]}` : (clase[5] || '-'))}
                                        </div>
                                    </div>
                                </div>`;
                        });
                    } else { // Original logic for F[15] != 1 or not present
                        console.log("Executing single superposition block logic (clase[15] != 1)");
                        const top = getPosicionY(cluster[0][12]);
                        const latestEndClase = cluster.reduce((max, c) => timeToMin(c[13]) > timeToMin(max[13]) ? c : max);
                        const bottom = getPosicionY(latestEndClase[13]);
                        const alto = Math.max(bottom - top, 30);
                        const jsonDetalles = encodeURIComponent(JSON.stringify(cluster));
                        html += `<div class="bloque-superposicion" style="top: ${top}px; height: ${alto}px;" onclick="verDetalleSuperposicion('${jsonDetalles}')">⚠️ Superposición (${cluster.length})</div>`;
                    }
                    clusterIdx.forEach(idx => procesados.add(idx));
                } else {
                    const numClases = cluster.length;
                    cluster.forEach((clase, idxInCluster) => {
                        const inicio = clase[12];
                        const fin = clase[13];
                        const top = getPosicionY(inicio) + 2;
                        const bottom = getPosicionY(fin) - 2;
                        const alto = Math.max(bottom - top, 20);
                        const anchoPct = 100 / numClases;
                        const leftPct = anchoPct * idxInCluster;
                        const styleExtra = numClases > 1 
                            ? `width: calc(${anchoPct}% - 6px); left: calc(${leftPct}% + 4px);`
                            : (clase[14] && clase[14].trim().toUpperCase() === 'A' 
                                ? `width: calc(50% - 6px); left: 4px;` 
                                : (clase[14] && clase[14].trim().toUpperCase() === 'B' 
                                    ? `width: calc(50% - 6px); right: 4px;` 
                                    : `left: 4px; right: 4px;`));
                        const jsonClase = encodeURIComponent(JSON.stringify(clase));
                        html += `
                            <div class="materia-bloque" 
                                 style="top: ${top}px; height: ${alto}px; ${styleExtra}" 
                                 onclick="mostrarInfoClase('${jsonClase}')"
                                 onmouseover="showTooltip(event, '${clase[3].replace(/'/g, "\\'")}', '${clase[5].replace(/'/g, "\\'")}', '${clase[9].replace(/'/g, "\\'")}', '${inicio} - ${fin}', '${clase[0]}° ${clase[1]}')" 
                                 onmouseout="hideTooltip()">
                                <div class="aula-indicador${!(/\d/g.test(clase[9])) && !(modo == "aula") ? ' sin-numero' : ''}">${modo === 'aula' ? `${clase[0]}° ${clase[1]}` : (clase[9] || '?')}</div>
                                <div class="materia-contenido">
                                    <div class="materia-nombre">${clase[3]}</div>
                                    <div class="materia-detalles">
                                        ${modo === 'aula' ? (clase[5] || '-') : (modo === 'profesor' ? `${clase[0]}° ${clase[1]}` : (clase[5] || '-'))}
                                    </div>
                                </div>
                            </div>`;
                    });
                    clusterIdx.forEach(idx => procesados.add(idx));
                }
            }
            html += '</div>';
        });
        html += '</div>';
        contenedor.innerHTML = html;
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
        html += `<tr>
            <td>${f[11]}</td><td>${f[12]}</td><td>${f[13]}</td>
            <td><b>${f[3]}</b></td><td>${f[5]}</td><td>${f[9]}</td><td>${f[14] || '-'}</td>
        </tr>`;
    });
    html += '</tbody></table>';
    contenedor.innerHTML = html;
}

function exportarAPDF() {
    if (currentSearch.modo && currentSearch.valor) {
        window.open(`/export/pdf/${currentSearch.modo}/${currentSearch.valor}`, '_blank');
    }
}
