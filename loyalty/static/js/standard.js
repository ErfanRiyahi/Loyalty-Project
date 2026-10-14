
const columnsListEl = document.getElementById('columnsList');
const addColumnBtn = document.getElementById('addColumnBtn');
const runBtn = document.getElementById('runBtn');
const statusArea = document.getElementById('statusArea');
const resultsArea = document.getElementById('resultsArea');

let columnCount = 0;

function addColumnRow(value) {
  columnCount += 1;
  const row = document.createElement('div');
  row.className = 'col-row';
  row.innerHTML = `
    <div class="order">${columnCount}</div>
    <input type="text" class="col-input" placeholder="e.g. MSISDN" value="${value || ''}">
    <button type="button" class="remove-col" title="remove">×</button>
  `;
  row.querySelector('.col-input').placeholder = value || 'Column name';
  row.querySelector('.remove-col').addEventListener('click', () => {
    row.remove();
    renumberColumns();
  });
  columnsListEl.appendChild(row);
}

function renumberColumns() {
  const rows = columnsListEl.querySelectorAll('.col-row');
  rows.forEach((row, i) => {
    row.querySelector('.order').textContent = i + 1;
  });
  columnCount = rows.length;
}

addColumnBtn.addEventListener('click', () => addColumnRow());

// Defaults come from the selected option, rendered from the shared backend schema.
const standardSelect = document.getElementById('standard');
function applyStandardDefaults() {
  const selected = standardSelect.selectedOptions[0];
  const address = document.getElementById('datasetAddress');
  address.value = selected.dataset.path;
  address.placeholder = selected.dataset.path;
  columnsListEl.replaceChildren();
  columnCount = 0;
  JSON.parse(selected.dataset.columns).forEach(value => addColumnRow(value));
}
standardSelect.addEventListener('change', applyStandardDefaults);
applyStandardDefaults();

function getColumns() {
  return Array.from(columnsListEl.querySelectorAll('.col-input'))
    .map(i => i.value.trim())
    .filter(v => v.length > 0);
}

function renderResults(data) {
  const overview = data.dataset_overview || {};
  const score = data.score || {};

  let overviewHtml = '';
  if (overview.rows !== undefined || overview.columns) {
    overviewHtml += `
      <div class="kv"><span class="k">Rows</span><span>${overview.rows ?? '—'}</span></div>
      <div class="kv"><span class="k">Columns used</span><span>${(overview.columns || []).join(', ') || '—'}</span></div>
    `;
    if (overview.missing_values !== undefined) {
      overviewHtml += `<div class="kv"><span class="k">Missing values</span><span>${overview.missing_values}</span></div>`;
    }
  }

  let previewHtml = '';
  if (Array.isArray(overview.preview) && overview.preview.length > 0) {
    const cols = Object.keys(overview.preview[0]);
    previewHtml = `<table><thead><tr>${cols.map(c => `<th>${escapeHtml(c)}</th>`).join('')}</tr></thead><tbody>`;
    overview.preview.slice(0, 8).forEach(row => {
      previewHtml += `<tr>${cols.map(c => `<td>${escapeHtml(String(row[c] ?? ''))}</td>`).join('')}</tr>`;
    });
    previewHtml += `</tbody></table>`;
  }

  const scoreValue = score.value !== undefined ? score.value : '—';
  const scorePct = (typeof score.value === 'number' && score.max)
    ? Math.max(0, Math.min(100, (score.value / score.max) * 100))
    : null;

  resultsArea.innerHTML = `
    <div class="panel">
      <h2>Dataset overview</h2>
      ${overviewHtml || '<div class="hint">No overview returned.</div>'}
      ${previewHtml ? `<div style="margin-top:12px;">${previewHtml}</div>` : ''}
    </div>
    <div class="panel">
      <h2>Score — ${escapeHtml(score.label || document.getElementById('standard').value)}</h2>
      <div class="score-card">
        <div>
          <div class="score-label">Result</div>
          <div class="score-value">${escapeHtml(String(scoreValue))}</div>
        </div>
        <div class="score-desc">${escapeHtml(score.description || 'No description returned by backend.')}</div>
      </div>
      ${scorePct !== null ? `<div class="bar-bg"><div class="bar-fill" style="width:${scorePct}%"></div></div>` : ''}
    </div>
    ${buildStatsPanelHtml(score.stats, 'standardStatsChart')}
  `;
  renderStatsChart(score.stats, 'standardStatsChart');
}

async function runAnalysis() {
  const apiUrl = document.getElementById('apiUrl').value.trim();
  const datasetAddress = document.getElementById('datasetAddress').value.trim();
  const columns = getColumns();
  const standard = document.getElementById('standard').value;

  if (!apiUrl) { setError('Please provide the backend API URL.'); return; }
  if (columns.length === 0) { setError('Please provide at least one required column.'); return; }

  runBtn.disabled = true;
  setLoading();

  try {
    const data = await postJson(apiUrl, {
      dataset_address: datasetAddress || undefined,  // blank -> backend default for this standard
      required_columns: columns,
      standard: standard
    });

    clearStatus();
    try {
      renderResults(data);
    } catch (renderErr) {
      setError({ source: 'frontend', message: renderErr.message || String(renderErr), trace: renderErr.stack || null });
    }
  } catch (err) {
    if (err && err.isBackendError) {
      setError({ source: 'backend', message: err.message, location: err.location, trace: err.trace });
    } else {
      setError({ source: 'frontend', message: (err && err.message) || String(err), trace: err && err.stack ? err.stack : null });
    }
  } finally {
    runBtn.disabled = false;
  }
}

runBtn.addEventListener('click', runAnalysis);

