// Funciones que usan todas las paginas.
const REFRESCO_MS = 5000;

async function pedir(url) {
  const r = await fetch(url, { cache: 'no-store' });
  if (!r.ok) throw new Error(url + ' -> ' + r.status);
  return r.json();
}

function hora(ms) {
  return new Date(ms).toLocaleTimeString('es-PE', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function haceTexto(s) {
  if (s === null || s === undefined) return 'nunca';
  if (s < 60) return 'hace ' + s + ' s';
  if (s < 3600) return 'hace ' + Math.round(s / 60) + ' min';
  return 'hace ' + Math.round(s / 3600) + ' h';
}

// Texto que viene del gateway (hex, nombre) se escapa antes de ponerlo en la pagina.
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function txt(v, dec) {
  if (v === null || v === undefined) return '—';
  return typeof v === 'number' && dec !== undefined ? v.toFixed(dec) : v;
}

function color(nombre) {
  return getComputedStyle(document.documentElement).getPropertyValue(nombre).trim();
}

// Grafico de lineas con eje X de tiempo (milisegundos) sin librerias extra.
function graficoTiempo(canvas, series) {
  return new Chart(canvas, {
    type: 'line',
    data: { datasets: series.map(s => Object.assign({ data: [], pointRadius: 0, borderWidth: 2, tension: 0.2 }, s)) },
    options: {
      animation: false,
      maintainAspectRatio: false,
      parsing: false,
      scales: {
        x: { type: 'linear', ticks: { callback: v => hora(v), maxTicksLimit: 6, color: color('--suave') }, grid: { color: color('--borde') } },
        y: { ticks: { color: color('--suave') }, grid: { color: color('--borde') } },
      },
      plugins: { legend: { labels: { color: color('--texto') } } },
    },
  });
}

function aPuntos(pares) {
  return pares.map(p => ({ x: p[0], y: p[1] }));
}

// Etiqueta del estado del rio en la cabecera de todas las paginas.
async function refrescarCabecera() {
  try {
    const r = await pedir('/api/resumen');
    const e = document.getElementById('estado-rio');
    e.className = 'etiqueta estado-rio ' + r.rio;
    e.textContent = 'Río: ' + r.rio;
    return r;
  } catch (err) {
    console.log(err);
  }
}

function cadaRato(f) {
  f();
  setInterval(f, REFRESCO_MS);
}
