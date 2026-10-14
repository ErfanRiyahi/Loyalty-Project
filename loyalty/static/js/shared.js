// ---------- Shared stats + histogram panel ----------
const chartInstances = {}; // canvasId -> Chart instance, so re-runs don't leak/duplicate

function buildStatsPanelHtml(stats, canvasId) {
  if (!stats) return '';
  return `
    <div class="panel">
      <h2>Result statistics — ${escapeHtml(stats.column)}</h2>
      <div class="kv"><span class="k">Count</span><span>${stats.count}</span></div>
      <div class="kv"><span class="k">Mean</span><span>${stats.mean}</span></div>
      <div class="kv"><span class="k">Median</span><span>${stats.median}</span></div>
      <div class="kv"><span class="k">Std dev</span><span>${stats.std}</span></div>
      <div class="kv"><span class="k">Min</span><span>${stats.min}</span></div>
      <div class="kv"><span class="k">Max</span><span>${stats.max}</span></div>
      <div style="margin-top:14px;"><canvas id="${canvasId}" height="180"></canvas></div>
    </div>
  `;
}

function renderStatsChart(stats, canvasId) {
  if (!stats || !stats.histogram) return;
  const el = document.getElementById(canvasId);
  if (!el) return;
  if (typeof Chart === 'undefined') { el.replaceWith(document.createTextNode('Chart unavailable; summary statistics remain above.')); return; }

  const edges = stats.histogram.bin_edges;
  const labels = edges.slice(0, -1).map((e, i) => `${e}–${edges[i + 1]}`);

  if (chartInstances[canvasId]) chartInstances[canvasId].destroy();
  chartInstances[canvasId] = new Chart(el, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: stats.column + ' distribution',
        data: stats.histogram.counts,
        backgroundColor: '#2563eb'
      }]
    },
    options: {
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { font: { size: 10 } } },
        y: { beginAtZero: true, ticks: { precision: 0 } }
      }
    }
  });
}

function setLoading(targetStatusArea, targetResultsArea, message) {
  targetStatusArea = targetStatusArea || statusArea;
  targetResultsArea = targetResultsArea || resultsArea;
  targetStatusArea.innerHTML = `
    <div class="panel">
      <div class="loading"><div class="spinner"></div> ${escapeHtml(message || 'Processing dataset…')}</div>
    </div>`;
  targetResultsArea.innerHTML = '';
}

// errInfo shape: { source: 'frontend'|'backend'|'validation', message, location, trace }
let traceToggleCounter = 0;

function setError(errInfo, targetStatusArea, targetResultsArea) {
  targetStatusArea = targetStatusArea || statusArea;
  targetResultsArea = targetResultsArea || resultsArea;
  const info = typeof errInfo === 'string' ? { source: 'validation', message: errInfo } : errInfo;
  const tagLabel = info.source === 'backend' ? 'Backend (Python) error'
                  : info.source === 'frontend' ? 'Frontend (JavaScript) error'
                  : 'Input error';

  traceToggleCounter += 1;
  const traceId = 'trace-' + traceToggleCounter;

  const locationHtml = info.location
    ? `<div class="error-loc">${escapeHtml(info.location)}</div>`
    : '';

  const traceHtml = info.trace
    ? `<button type="button" class="error-trace-toggle" onclick="
        var el = document.getElementById('${traceId}');
        el.classList.toggle('open');
        this.textContent = el.classList.contains('open') ? 'Hide full traceback' : 'Show full traceback';
      ">Show full traceback</button>
      <div class="error-trace" id="${traceId}">${escapeHtml(info.trace)}</div>`
    : '';

  targetStatusArea.innerHTML = `
    <div class="panel">
      <div class="error-box">
        <span class="error-tag">${escapeHtml(tagLabel)}</span>
        <div class="error-message">${escapeHtml(info.message || 'Something went wrong.')}</div>
        ${locationHtml}
        ${traceHtml}
      </div>
    </div>`;
  targetResultsArea.innerHTML = '';
}

function clearStatus(targetStatusArea) {
  (targetStatusArea || statusArea).innerHTML = '';
}

// Catch any uncaught JS error anywhere on the page (e.g. a bug in a button
// handler) and report exactly where it happened: file, line, column.
window.addEventListener('error', function (event) {
  setError({
    source: 'frontend',
    message: event.message,
    location: `${event.filename ? event.filename.split('/').pop() : 'scoring_frontend.html'}:${event.lineno}:${event.colno}`,
    trace: event.error && event.error.stack ? event.error.stack : null
  });
});

// Catch rejected Promises that weren't handled with try/catch.
window.addEventListener('unhandledrejection', function (event) {
  const reason = event.reason;
  setError({
    source: 'frontend',
    message: (reason && reason.message) || String(reason),
    trace: reason && reason.stack ? reason.stack : null
  });
});

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// shared JSON POST helper: parses response, raises a tagged Error the existing
// catch blocks already know how to render via setError
async function postJson(apiUrl, body) {
  const response = await fetch(apiUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });

  const raw = await response.text();
  let data;
  try {
    data = JSON.parse(raw);
  } catch (e) {
    const parseErr = new Error('Backend did not return valid JSON (raw response below):\n' + raw.slice(0, 800));
    parseErr.isBackendError = true;
    parseErr.location = apiUrl;
    throw parseErr;
  }

  if (!response.ok || data.error) {
    const backendErr = new Error(data.error || `Backend returned status ${response.status}`);
    backendErr.isBackendError = true;
    if (data.file || data.line) {
      backendErr.location = `${data.file || 'unknown file'}${data.line ? ':' + data.line : ''}`
        + (data.error_type ? `  (${data.error_type})` : '');
    } else if (data.error_type) {
      backendErr.location = data.error_type;
    }
    backendErr.trace = data.traceback || null;
    throw backendErr;
  }

  return data;
}

